"""Night Audit: close the business date.

The Night Audit is the daily reconciliation that makes a PMS trustworthy. It
posts the day's room charges, resolves what the shift left open, checks that
the operational subledger agrees with ERPNext, and then moves the property's
business date forward.

The rule that matters most: **daily posting is idempotent** (SAS section 3.10).
Room charges post under `room-charge:{stay}:{business_date}`, so re-running an
audit for a date that already posted charges nothing again. That is what makes
the audit safe to retry after a crash, which is exactly when it is most likely
to be retried.

The business date only moves through `close`, and `close` is the only caller
permitted to set the property's business date at all (see PropertyService's
`BUSINESS_DATE_FLAG`).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime

from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services import durability
from hospitality_pms.services.base import (
	NIGHT_AUDIT_SERVICE,
	assert_transition,
	lock_and_get_doc,
	lock_and_read,
	lock_document,
	require_role,
	service_context,
	transaction,
)
from hospitality_pms.services.exceptions import NightAuditError, throw
from hospitality_pms.services.property import BUSINESS_DATE_FLAG, get_business_date, get_property

AUDIT_DOCTYPE = "Night Audit"

#: Where reconciliation writes down the exact set of financial postings it
#: validated, so that `close` can re-check that same set rather than deriving a
#: new one (16.7.5-R1F).
RECONCILED_POSTING_DOCTYPE = "Night Audit Reconciled Posting"

OPEN = "Open"
REVIEWING = "Reviewing"
POSTING = "Posting"
READY_TO_CLOSE = "Ready to Close"
CLOSED = "Closed"

#: Night Audit state machine, from Workflow Matrix section 7.
TRANSITIONS = {
	OPEN: {REVIEWING},
	# Ready to Close is reachable straight from Reviewing: a day with nothing
	# left to post should not have to pass through Posting to be closable.
	REVIEWING: {POSTING, REVIEWING, READY_TO_CLOSE},
	POSTING: {READY_TO_CLOSE, REVIEWING},
	# An auditor who finds a missed charge at the last moment must be able to
	# go back and post it rather than close the day knowingly short.
	READY_TO_CLOSE: {CLOSED, REVIEWING, POSTING},
	CLOSED: {REVIEWING},
}

AUDITOR_ROLES = (
	"Night Auditor",
	"Hotel Manager",
	"General Manager",
	"Hospitality Administrator",
	"System Manager",
)

#: Reopening a closed business date is a manager exception (Workflow Matrix
#: section 7): it re-opens a day the hotel has already reported on.
REOPEN_ROLES = (
	"Hotel Manager",
	"General Manager",
	"Finance Manager",
	"Hospitality Administrator",
	"System Manager",
)

BLOCKING = "Blocking"

#: How many folios one page of the reconciliation population fetches. A page
#: size, not a limit: pagination runs to exhaustion.
RECONCILIATION_PAGE = 500


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start(property_name: str, business_date=None) -> str:
	"""Open the audit for a business date.

	Returns the existing audit if one is already open for that date, so two
	auditors starting at once work on the same record instead of two.

	Serialised on the Property row, and backed by a unique index on
	`(property, business_date)`. The check-then-insert on its own was a race:
	two schedulers reading "no audit yet" at the same instant both created one,
	and a property with two audits for one date has two sets of figures and two
	ways to close it (P2-1).
	"""
	require_role(AUDITOR_ROLES)

	# Locked first: the audit for a date and the property's date are one
	# decision, and this is the row every other Night Audit operation
	# serialises on.
	current = lock_and_read("Property", property_name, ["business_date"])
	business_date = getdate(business_date or current["business_date"])

	existing = frappe.db.get_value(
		AUDIT_DOCTYPE,
		{"property": property_name, "business_date": business_date},
		["name", "audit_status"],
		as_dict=True,
	)

	if existing:
		if existing["audit_status"] == CLOSED:
			throw(
				_("The business date {0} is already closed.").format(business_date),
				exc=NightAuditError,
			)
		return existing["name"]

	try:
		with service_context(NIGHT_AUDIT_SERVICE):
			doc = frappe.get_doc(
				{
					"doctype": AUDIT_DOCTYPE,
					"property": property_name,
					"business_date": business_date,
					"next_business_date": add_days(business_date, 1),
					"audit_status": OPEN,
					"started_on": now_datetime(),
					"started_by": frappe.session.user,
				}
			).insert(ignore_permissions=True)
	except frappe.UniqueValidationError:
		# The database refused a second audit for this date. Another caller got
		# there first, so hand back theirs rather than an opaque duplicate-key
		# error - starting an audit twice is a normal thing for two schedulers
		# to do, not a failure.
		frappe.db.rollback()

		return frappe.db.get_value(
			AUDIT_DOCTYPE, {"property": property_name, "business_date": business_date}, "name"
		)

	return doc.name


def review(audit: str) -> dict:
	"""Gather the day's exceptions and figures.

	Read-and-record only: nothing is posted and no state is forced. Running
	review twice is safe and is expected while the auditor clears exceptions.
	"""
	require_role(AUDITOR_ROLES)

	doc = lock_and_get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status == CLOSED:
		throw(_("This audit is closed."), exc=NightAuditError)

	if doc.audit_status == OPEN:
		_transition(doc, REVIEWING)

	business_date = getdate(doc.business_date)

	# Exceptions are rebuilt each review so a resolved one disappears rather
	# than lingering as a stale blocker.
	doc.set("audit_exceptions", [])

	unresolved = reservation_service.get_unresolved_arrivals(doc.property, business_date)
	for row in unresolved:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unresolved Arrival",
				"reference_doctype": reservation_service.RESERVATION_DOCTYPE,
				"reference_name": row["name"],
				# The guest's name is not in the sentence (16.7.5-R1B). An
				# exception description is stored text, rendered on the Night Audit
				# screen to every one of the twenty-three roles that can read a
				# Night Audit - including the kitchen, housekeeping and maintenance
				# lines, none of which may read `Guest`. A name baked into the
				# string cannot be gated afterwards, so it is not put there:
				# identity travels in `reference`, which `api/night_audit.py` gates
				# against the DocType it names. A Reservation reader can still
				# resolve who this is; a Kitchen User cannot, which is correct.
				"description": _("Reservation {0} was due to arrive on {1} and has not checked in.").format(
					row["name"], row["arrival_date"]
				),
				"severity": BLOCKING,
			},
		)

	overdue = frappe.get_all(
		stay_service.STAY_DOCTYPE,
		filters={
			"property": doc.property,
			"stay_status": ("in", (stay_service.IN_HOUSE, stay_service.DUE_OUT)),
			"departure_date": ("<=", business_date),
		},
		fields=["name", "guest_name", "room", "departure_date"],
	)
	for row in overdue:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unsettled Departure",
				"reference_doctype": stay_service.STAY_DOCTYPE,
				"reference_name": row["name"],
				# The stay and the room, not the guest's name, for the reason
				# recorded on the arrival exception above. Both of these are
				# readable by every role that can read a Night Audit, so the
				# sentence stays as useful to the night auditor as it was - the
				# room number is what they walk to - while the guest's identity
				# travels in the gated `reference` instead.
				"description": _("Stay {0} in room {1} was due to depart on {2} and is still in house.").format(
					row["name"], row["room"], row["departure_date"]
				),
				"severity": "Warning",
			},
		)

	failed = posting_service.get_failed_postings(doc.property, limit=50)
	for row in failed:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Failed Posting",
				"reference_doctype": posting_service.POSTING_LOG,
				"reference_name": row["name"],
				"description": _("{0} posting failed after {1} attempt(s).").format(
					row["posting_type"], row["attempts"]
				),
				"severity": BLOCKING,
			},
		)

	_refresh_figures(doc, business_date, room_revenue=flt(doc.room_revenue))

	doc.review_completed_on = now_datetime()
	doc.review_completed_by = frappe.session.user

	_save(doc)

	return {
		"audit": audit,
		"business_date": str(business_date),
		"exceptions": len(doc.audit_exceptions),
		"blocking": sum(1 for row in doc.audit_exceptions if row.severity == BLOCKING and not row.is_resolved),
	}


def resolve_exception(audit: str, row_name: str, resolution: str) -> str:
	"""Mark one exception as dealt with, with a note saying how."""
	require_role(AUDITOR_ROLES)

	if not resolution or not resolution.strip():
		throw(_("A resolution note is required."), exc=NightAuditError)

	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)
	row = next((line for line in doc.audit_exceptions if line.name == row_name), None)

	if not row:
		throw(_("Exception {0} does not belong to this audit.").format(row_name), exc=NightAuditError)

	row.is_resolved = 1
	row.resolution = resolution.strip()
	row.resolved_by = frappe.session.user
	row.resolved_on = now_datetime()

	_save(doc)

	return row_name


def mark_no_shows(audit: str) -> list[str]:
	"""Turn unresolved arrivals into no-shows.

	Deliberately a separate, explicit step rather than part of review: a
	no-show applies a charge under the guest's policy, and the auditor should
	choose to do it.

	One booking that refuses does not stop the sweep. `get_unresolved_arrivals`
	selects on the *header* status, and a multi-room booking whose party has only
	partly arrived still reads `Confirmed` - `stays.check_in` does not promote the
	header until every line is in house. `reservations.mark_no_show` now refuses
	such a booking outright, because calling a room a no-show while its guest is
	asleep in it is a lie that also releases corporate credit for a consumed room.
	Before this containment the refusal propagated out of the loop, so a single
	partly-arrived booking stopped the whole step and the genuine no-shows queued
	behind it were never marked.

	Nothing is hidden by skipping one. A booking that is not marked stays an
	unresolved arrival, and `review` already raises a **blocking** "Unresolved
	Arrival" exception for each of those, so the day still cannot close until the
	auditor resolves it by hand - which is the correct outcome, because only a
	human can decide whether the rest of that party is arriving.

	Each attempt runs in its own savepoint so a refusal rolls back only that
	booking and leaves the sweep's earlier work intact.
	"""
	require_role(AUDITOR_ROLES)

	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)
	marked = []
	refused = []

	for row in reservation_service.get_unresolved_arrivals(doc.property, doc.business_date):
		try:
			with transaction():
				reservation_service.mark_no_show(
					row["name"], reason=_("Night Audit {0}").format(audit)
				)

			marked.append(row["name"])
		except Exception as exc:  # noqa: BLE001
			# Diagnosable without putting a stack trace in front of an auditor.
			# The operational signal is review's blocking exception, not this.
			refused.append(row["name"])
			frappe.log_error(
				title=f"Night Audit {audit}: no-show refused for {row['name']}",
				message=str(exc),
			)

	frappe.db.set_value(AUDIT_DOCTYPE, audit, "no_shows", len(marked), update_modified=False)

	return marked


def post_room_charges(audit: str) -> dict:
	"""Post one night's room charge for every in-house stay.

	Idempotent per stay per business date. A stay departing on the business
	date does not consume that night, which is why the query lives in
	StayService alongside the same night arithmetic availability uses.
	"""
	require_role(AUDITOR_ROLES)

	doc = lock_and_get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status == CLOSED:
		throw(_("This audit is closed."), exc=NightAuditError)

	_transition(doc, POSTING)

	business_date = getdate(doc.business_date)
	posted = 0
	skipped = 0
	failed = []

	for stay in stay_service.get_stays_for_room_charge(doc.property, business_date):
		if not stay["folio"]:
			failed.append({"stay": stay["name"], "error": "no folio"})
			continue

		try:
			result = folio_service.post_charge(
				stay["folio"],
				"Room Charge",
				_("Room {0} on {1}").format(stay["room"], business_date),
				flt(stay["room_rate"]),
				idempotency_key=f"room-charge:{stay['name']}:{business_date}",
				business_date=business_date,
				charge_date=business_date,
				reference_doctype=stay_service.STAY_DOCTYPE,
				reference_name=stay["name"],
			)

			if result.get("duplicate"):
				skipped += 1
			else:
				posted += 1
		except Exception as exc:  # noqa: BLE001
			failed.append({"stay": stay["name"], "error": str(exc)[:200]})

	# Derived from what is on the folios, not from what this run happened to
	# insert. The figures used to be built out of `posted` and a running total
	# of newly created rows, so a retry - which correctly posts nothing -
	# overwrote the day's revenue with zero and took ADR and RevPAR with it
	# (P2-1). Read back, they are the same on every run.
	charged = _posted_room_charges(doc.property, business_date)

	# Figures are refreshed *after* room revenue is resolved, and given that
	# revenue explicitly. Previously `_refresh_figures` read `doc.room_revenue`
	# from before the posting run, so ADR and RevPAR were always one operation
	# behind whatever had just been posted.
	doc = lock_and_get_doc(AUDIT_DOCTYPE, audit)
	_refresh_figures(doc, business_date, room_revenue=charged["revenue"])

	doc.rooms_charged = charged["rooms"]
	doc.charges_posted = charged["rooms"]
	doc.postings_failed = len(failed)
	doc.room_revenue = flt(charged["revenue"], 2)
	doc.posting_completed_on = now_datetime()
	doc.posting_completed_by = frappe.session.user

	_save(doc)

	return {
		"audit": audit,
		"posted": posted,
		"already_posted": skipped,
		"rooms_charged": charged["rooms"],
		"room_revenue": flt(charged["revenue"], 2),
		"failed": failed,
	}


def mark_due_outs(audit: str) -> list[str]:
	"""Flag tomorrow's departures so the morning shift sees them."""
	doc = frappe.get_doc(AUDIT_DOCTYPE, audit)

	return stay_service.mark_due_out(doc.property, add_days(getdate(doc.business_date), 1))


def reconcile(audit: str) -> dict:
	"""Check the subledger against ERPNext before allowing a close.

	Examines its whole population, and records how big that population was.

	It used to take `limit=200` folios ordered by `modified desc`. The ordering
	is perfectly deterministic, which is precisely what made it dangerous: the
	oldest folios were never the newest two hundred, so a variance in one of
	them was not occasionally missed but *systematically* invisible, and the
	day closed over it every time (P1-9).
	"""
	require_role(AUDITOR_ROLES)

	doc = lock_and_get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status == CLOSED:
		throw(_("This audit is closed."), exc=NightAuditError)

	business_date = getdate(doc.business_date)

	population = reconciliation_population(doc.property, business_date)
	variances = []
	accepted = set()

	for folio in population:
		result = posting_service.reconcile_folio(folio)

		if result["is_reconciled"]:
			accepted.add(folio)
		else:
			variances.append(result)

	# The financial postings this reconciliation is accountable for, and whether
	# the ledger still supports them. Built from the Financial Posting Log rather
	# than from the folios, so that a folio's *current* status cannot decide what
	# gets checked - see `posting.posting_rows_for_finality` (16.7.5-R1F).
	evidence = posting_service.finality_evidence(
		posting_service.posting_rows_for_finality(
			doc.property,
			since=_previous_closed_audit_date(doc.property, business_date),
			folios=population,
		),
		# Only a folio this run examined *and found to agree* may have its
		# credit notes recorded as the accepted state. Everything else is
		# baselined at zero, so an existing credit note on a folio that has left
		# the population is a break rather than a new normal.
		accepted_folios=accepted,
	)
	breaks = posting_service.finality_breaks(evidence)

	# Rebuilt rather than appended to, so a variance that has since been fixed
	# stops blocking the close instead of lingering from an earlier run.
	doc.set(
		"audit_exceptions",
		[row for row in doc.audit_exceptions if row.exception_type != "Unposted Charge"],
	)

	for variance in variances:
		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unposted Charge",
				"reference_doctype": folio_service.FOLIO_DOCTYPE,
				"reference_name": variance["folio"],
				# Neither the folio's name nor the variance amount is in the
				# sentence (16.7.5-R1B). This description is rendered on the Night
				# Audit screen, and ten of the roles that can open it cannot read
				# `Guest Folio` - so it was telling a room attendant which folio
				# disagrees with the ledger and by how much money.
				#
				# Both facts still reach the people who need them: the folio's
				# identity through the gated `reference`, and the amount through the
				# reconciliation endpoint, which is `RECONCILIATION_ROLES`-gated and
				# is where finance works the variance. What is lost here is only the
				# ability to read it off a screen without the permission for it.
				"description": (
					# Two different problems needing two different people. "Does not
					# agree" reads as work for whoever posts the day; a posting whose
					# document has left the ledger is an accounting decision, and
					# retrying it is refused. Saying so here is what stops the second
					# being worked as the first.
					_(
						"A folio on this business date was posted to ERPNext and that "
						"document is no longer in the ledger. It needs reconciliation."
					)
					if variance.get("needs_erp_reconciliation")
					else _("A folio on this business date does not agree with ERPNext.")
				),
				"severity": BLOCKING,
			},
		)

	# A posting whose folio is already carrying a variance row is not reported
	# twice. The folio row is the more useful of the two - it names the record
	# finance works from - so the log-level row is raised only for postings whose
	# folio this reconciliation did not examine, which is exactly the population
	# the R1F escape lived in.
	varied_folios = {variance["folio"] for variance in variances}

	for row in breaks:
		if row["folio"] and row["folio"] in varied_folios:
			continue

		doc.append(
			"audit_exceptions",
			{
				"exception_type": "Unposted Charge",
				"reference_doctype": posting_service.POSTING_LOG,
				"reference_name": row["posting_log"],
				# The accounting document is not in the sentence, for the reason the
				# folio's name is not in the one above (16.7.5-R1B): this description
				# is rendered on the Night Audit screen to every role that can open
				# one. The posting log's identity travels in the gated `reference`.
				"description": _(
					"A posting this business date reconciled is no longer supported by the "
					"ledger. It needs reconciliation."
				),
				"severity": BLOCKING,
			},
		)

	_refresh_figures(doc, business_date, room_revenue=flt(doc.room_revenue))

	fingerprint = _audit_date_fingerprint(doc.property, business_date)

	doc.reconciliation_completed_on = now_datetime()
	doc.reconciliation_completed_by = frappe.session.user
	doc.reconciliation_population = len(population)
	doc.reconciliation_variances = len(variances) + len(breaks)
	doc.reconciled_row_count = fingerprint["rows"]
	doc.reconciled_row_total = flt(fingerprint["total"], 2)

	_record_reconciled_postings(audit, doc.property, evidence)

	if not _blocking_exceptions(doc):
		_transition(doc, READY_TO_CLOSE)

	_save(doc)

	return {
		"audit": audit,
		"population": len(population),
		"postings": len(evidence),
		"variances": len(variances),
		"stale_postings": len(breaks),
		"blocking": len(_blocking_exceptions(doc)),
		"audit_status": doc.audit_status,
	}


def _record_reconciled_postings(audit: str, property_name: str, evidence: list[dict]):
	"""Write down the postings this reconciliation validated, once each.

	**Write-once per (audit, posting).** A row records the state of the ledger
	when this audit *first* accepted that posting, and a later reconciliation
	never revises it. That is the whole mechanism: if revisiting were allowed,
	re-running reconciliation after finance cancelled an invoice or raised a
	credit note would quietly re-baseline the audit against the damaged state and
	hand back exactly the close R1F exists to refuse.

	**Additive.** A posting that enters the set on a later run is added. The set
	only ever grows within one audit, and is cleared only by `reopen`, which
	discards the reconciliation itself.
	"""
	if not evidence:
		return

	# A locking read, not a plain one. `reconcile` holds the audit row, which
	# serialises two runs but does not refresh either one's snapshot: the second
	# would still see the set as it stood before the first wrote to it and insert
	# every row again. Duplicates fail safe - the original baseline survives and
	# still fires at close - but they inflate `reconciliation_variances` and the
	# count in the refusal, which is a number finance reads.
	already = {
		row["posting_log"]
		for row in frappe.db.get_values(
			RECONCILED_POSTING_DOCTYPE,
			{"night_audit": audit},
			["posting_log"],
			as_dict=True,
			order_by="posting_log asc",
			for_update=True,
		)
		or []
	}

	for row in evidence:
		if row["posting_log"] in already:
			continue

		with service_context(NIGHT_AUDIT_SERVICE):
			frappe.get_doc(
				{
					"doctype": RECONCILED_POSTING_DOCTYPE,
					"night_audit": audit,
					"property": property_name,
					"posting_log": row["posting_log"],
					"folio": row["folio"],
					"posting_type": row["posting_type"],
					"erp_doctype": row["erp_doctype"],
					"erp_document": row["erp_document"],
					"amount": flt(row["amount"]),
					"returned_total": flt(row["returned_total"]),
				}
			).insert(ignore_permissions=True)

		already.add(row["posting_log"])


def reconciled_postings(audit: str) -> list[dict]:
	"""The evidence set a close will be checked against.

	Ordered on the posting log's name so the close-time reads are deterministic
	whatever order the rows were written in.

	A locking read, like the two other reads in this scheme. It is the read that
	decides whether there is anything to check at all, so a stale snapshot of it
	does not weaken the gate - it skips it. `close` blocks on the audit row while
	a reconciliation holds it; when the lock is released the evidence has been
	committed, and a plain `SELECT` would still be answered from the read view
	`close` opened before it waited. Empty set, early return, no finality check.
	"""
	return (
		frappe.db.get_values(
			RECONCILED_POSTING_DOCTYPE,
			{"night_audit": audit},
			[
				"posting_log",
				"folio",
				"posting_type",
				"erp_doctype",
				"erp_document",
				"amount",
				"returned_total",
			],
			as_dict=True,
			order_by="posting_log asc",
			for_update=True,
		)
		or []
	)


def reconciliation_population(property_name: str, business_date) -> list[str]:
	"""The folios this audit is responsible for checking.

	Two clauses, and both are needed:

	* folios in a settled state touched since the last closed audit - the money
	  this audit period is actually accountable for, rather than every folio
	  the hotel has ever settled, which would grow without bound and re-check
	  2019 on every run;
	* any **settled** folio still carrying a charge that has not reached
	  ERPNext, whatever its date. This is the safety net: a variance cannot
	  fall out of the window and become permanently invisible, which is the
	  failure P1-9 was.

	An in-house folio is deliberately not in either clause. A guest still in the
	hotel accumulates charges all week and they reach ERPNext at checkout, so
	treating those as unreconciled would block every close at a hotel with
	anybody staying in it.

	Read once, to exhaustion, paginated on `name`. Keyed on the primary key
	rather than on `modified` so a folio changing while reconciliation runs
	cannot shuffle itself past the cursor and be skipped, or back behind it and
	be counted twice.
	"""
	since = _previous_closed_audit_date(property_name, business_date)
	names: list[str] = []
	cursor = ""

	while True:
		page = frappe.db.sql(
			"""
			select f.name
			from `tabGuest Folio` f
			where f.property = %(property)s
			  and f.name > %(cursor)s
			  and (
			        (f.folio_status in ('Settled', 'Closed') and f.modified >= %(since)s)
			     or (
			            f.folio_status in ('Settled', 'Closed')
			            and exists (
			                select 1 from `tabFolio Charge` c
			                where c.parent = f.name and ifnull(c.is_posted_to_erp, 0) = 0
			            )
			        )
			  )
			order by f.name asc
			limit %(page_size)s
			""",
			{
				"property": property_name,
				"cursor": cursor,
				"since": since,
				"page_size": RECONCILIATION_PAGE,
			},
			pluck=True,
		)

		if not page:
			return names

		names.extend(page)
		cursor = page[-1]


def _previous_closed_audit_date(property_name: str, business_date):
	"""The last date this property closed, or the beginning of time.

	With no previous close there is no window to speak of, so the first audit
	examines everything settled - which is the right answer for a property
	being audited for the first time.
	"""
	previous = frappe.db.get_value(
		AUDIT_DOCTYPE,
		{
			"property": property_name,
			"audit_status": CLOSED,
			"business_date": ("<", getdate(business_date)),
		},
		"business_date",
		order_by="business_date desc",
	)

	return getdate(previous) if previous else getdate("1900-01-01")


def close(audit: str) -> dict:
	"""Close the business date and roll the property forward.

	The only place the property's business date moves, and the gate everything
	else in this wave exists to make meaningful.

	It used to check the workflow status and the exception list. Neither is
	evidence: `review()` moves the audit to Reviewing, Reviewing may legally
	reach Ready to Close, and so review-then-close advanced the date with no
	room charge posted anywhere and `room_revenue = 0` (P1-7). A status says
	what someone pressed, not what the accounting did.

	Every precondition below is re-read under the locks, immediately before the
	date moves, and the date and the audit status move together.
	"""
	require_role(AUDITOR_ROLES)

	# Locked in a fixed order - audit, then property - and read from those same
	# locking reads, so nothing here is decided from a snapshot taken before
	# another close was let through (Wave 1, N1).
	doc = lock_and_get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status == CLOSED:
		throw(_("Audit {0} is already closed.").format(audit), exc=NightAuditError)

	business_date = getdate(doc.business_date)

	_assert_steps_complete(doc, business_date)
	_assert_no_blocking_exceptions(doc)
	_assert_no_unresolved_posting_failures(doc.property)

	property_state = lock_and_read("Property", doc.property, ["business_date"])

	if getdate(property_state["business_date"]) != business_date:
		throw(
			_("The property's business date is {0}, but this audit closes {1}.").format(
				property_state["business_date"], business_date
			),
			exc=NightAuditError,
		)

	# Last, and deliberately last. Everything above is read from the PMS's own
	# records; this is the one check that asks the accounting system a question,
	# and it asks it under the audit and property locks with nothing left to do
	# afterwards but move the date. That is what makes the race safe: a
	# cancellation either commits before this read, in which case it is seen and
	# the close is refused, or it waits behind the locking read and lands after
	# the business date has already moved over an ledger that was intact when it
	# moved. What cannot happen is the date closing over accounting that was
	# already invalid when the check ran.
	_assert_reconciled_postings_are_final(doc)

	next_date = add_days(business_date, 1)

	_set_business_date(doc.property, next_date)
	_transition(doc, CLOSED)

	frappe.db.set_value(
		AUDIT_DOCTYPE,
		audit,
		{
			"closed_on": now_datetime(),
			"closed_by": frappe.session.user,
			"next_business_date": next_date,
		},
		update_modified=True,
	)

	return {
		"audit": audit,
		"closed_business_date": str(business_date),
		"new_business_date": str(next_date),
	}


def _assert_steps_complete(doc, business_date):
	"""Every mandatory step must have said, durably, that it finished."""
	if not doc.review_completed_on:
		throw(_("The day has not been reviewed."), exc=NightAuditError)

	if not doc.posting_completed_on:
		throw(
			_("The day's room charges have not been posted."),
			exc=NightAuditError,
		)

	if not doc.reconciliation_completed_on:
		throw(
			_("The folios have not been reconciled against ERPNext."),
			exc=NightAuditError,
		)

	if getdate(doc.reconciliation_completed_on) and doc.posting_completed_on:
		if doc.reconciliation_completed_on < doc.posting_completed_on:
			throw(
				_("Room charges were posted after the last reconciliation. Reconcile again."),
				exc=NightAuditError,
			)

	# The money on this date must be the money that was reconciled. Comparing a
	# fingerprint rather than trusting a flag means any later posting - through
	# any path, by any service - invalidates the reconciliation, without every
	# one of those paths having to remember to say so.
	fingerprint = _audit_date_fingerprint(doc.property, business_date)

	if int(fingerprint["rows"]) != int(doc.reconciled_row_count or 0) or flt(
		fingerprint["total"], 2
	) != flt(doc.reconciled_row_total, 2):
		throw(
			_(
				"Money has been posted to {0} since it was reconciled. Reconcile again before "
				"closing."
			).format(business_date),
			exc=NightAuditError,
		)


def _assert_no_blocking_exceptions(doc):
	blocking = _blocking_exceptions(doc)

	if blocking:
		throw(
			_("{0} blocking exception(s) must be resolved before the business date can close.").format(
				len(blocking)
			),
			exc=NightAuditError,
		)

	# The check above reads the exception rows, and reads nothing if there are
	# none. `reconcile()` writes the rows and `reconciliation_variances` in the same
	# save, so a positive count with no row to account for it does not mean the day
	# came out clean - it means the evidence is gone, and this guard was about to
	# pass on its absence. `HPMS-NA-2026-00004` is in exactly that state: one
	# recorded variance, no exception rows, and until now a close that consulted
	# both and objected to neither.
	#
	# Resolved rows still satisfy it. Marking an exception resolved without
	# re-running reconciliation is a legitimate path and leaves the row behind as
	# its own record; what is refused is a count with nothing behind it at all.
	#
	# Deliberately re-reconcile rather than re-derive the variance here: `reconcile`
	# owns that computation, it is idempotent, and it rewrites both the rows and the
	# count together. A second opinion computed in the close path would be a second
	# definition of whether the day agrees with ERPNext.
	recorded = cint(doc.reconciliation_variances)

	if recorded and not [
		row for row in doc.audit_exceptions if row.exception_type == "Unposted Charge"
	]:
		throw(
			_(
				"This audit recorded {0} reconciliation variance(s) but carries no exception "
				"to account for them. Reconcile again before closing."
			).format(recorded),
			exc=NightAuditError,
		)


def _assert_no_unresolved_posting_failures(property_name: str):
	"""Wave 3's durable ledger is the authority on whether posting worked.

	A posting that took its own transaction down left no Financial Posting Log
	row at all - that was P1-14 - so an audit that consulted only the log would
	be told everything was fine by the absence of the evidence.
	"""
	unresolved = durability.failed_posting_operations(property_name, limit=20)

	if unresolved:
		throw(
			_(
				"{0} financial posting operation(s) have not completed. Resolve them before "
				"closing the business date."
			).format(len(unresolved)),
			exc=NightAuditError,
		)


def _assert_reconciled_postings_are_final(doc):
	"""Re-check the exact set reconciliation accepted, against the live ledger.

	This is 16.7.5-R1F, and the thing it does differently from R1E is the whole
	of it: the set is **read back from what reconciliation wrote down**, not
	recomputed from the folios.

	R1E recomputed it, from `reconciliation_population`, which selects folios by
	their *current* `folio_status`. `checkout.reverse_checkout` is a supported
	operation that moves a Settled folio to Under Review - so a folio could be
	settled, be reconciled, be reversed out of the population, have its invoice
	cancelled, and close: the guard no longer had anything to look at. The audit
	was checking the set it could see rather than the set it had claimed.

	So `close` now asks the question reconciliation's own evidence poses. Any
	posting that evidence names, whose folio may since have gone anywhere at all,
	must still be supported by the ledger:

	* the log row must still claim the document reconciliation accepted, or have
	  been explicitly withdrawn by finance;
	* the document must still be submitted;
	* and it must not have been credited back since.

	The reads are batched by DocType and taken in a fixed order, once. Nothing is
	written to ERPNext, here or anywhere else on this path.
	"""
	evidence = reconciled_postings(doc.name)

	if not evidence:
		return

	breaks = posting_service.finality_breaks(evidence, current=True)

	if not breaks:
		return

	# The posting log rows are named. Every role that can reach this refusal is in
	# `AUDITOR_ROLES`, and all five of them may read `Financial Posting Log`; the
	# accounting document is *not* named, because none of them may read one - the
	# same division `posting._stale_posting_message` draws, for the same reason.
	# Capped, because the sentence has to stay readable when a batch run has gone
	# wrong wholesale, and the count carries the scale.
	logs = sorted(row["posting_log"] for row in breaks)[:5]

	throw(
		_(
			"{0} posting(s) this audit reconciled are no longer supported by the accounting "
			"system: {1}. The business date cannot close over them. Finance must either put "
			"the accounting back, or withdraw the posting claim and settle the folio, before "
			"reconciliation is run again."
		).format(len(breaks), ", ".join(logs)),
		exc=NightAuditError,
	)


def reopen(audit: str, reason: str) -> dict:
	"""Reopen a closed business date by exactly one day. Manager exception only.

	Reopen used to check only that the audit was closed, and then set the
	property's date to that audit's date. Reopening the 8th while the 9th and
	10th were also closed rewound the property three days and left the chain
	unfinishable: the 9th could not close because the property was no longer on
	the 9th, and nothing could move it back (P1-8).

	So a reopen is only ever the *undo of the last close*. The audit must be
	the newest closed one, and the property must be sitting exactly one day
	past it - which is precisely the state the last close left behind.
	"""
	require_role(REOPEN_ROLES)

	if not reason or not reason.strip():
		throw(_("A reason is required to reopen a closed business date."), exc=NightAuditError)

	doc = lock_and_get_doc(AUDIT_DOCTYPE, audit)

	if doc.audit_status != CLOSED:
		throw(_("Audit {0} is not closed.").format(audit), exc=NightAuditError)

	business_date = getdate(doc.business_date)

	later = frappe.db.get_value(
		AUDIT_DOCTYPE,
		{
			"property": doc.property,
			"business_date": (">", business_date),
			"audit_status": CLOSED,
		},
		["name", "business_date"],
		as_dict=True,
		order_by="business_date asc",
	)

	if later:
		throw(
			_(
				"{0} was closed after this one. Reopen the most recent closed date ({1}) first."
			).format(later["name"], later["business_date"]),
			exc=NightAuditError,
		)

	property_state = lock_and_read("Property", doc.property, ["business_date"])
	expected = add_days(business_date, 1)

	if getdate(property_state["business_date"]) != expected:
		throw(
			_(
				"The property is on {0}. Only the audit for the day immediately before it ({1}) "
				"can be reopened."
			).format(property_state["business_date"], business_date),
			exc=NightAuditError,
		)

	_set_business_date(doc.property, business_date)
	_transition(doc, REVIEWING)

	# The close is undone, and so is the proof that supported it. Posting is
	# deliberately left marked: the room charges are already on the folios and
	# are idempotent, so re-closing must not post them again. What has to be
	# earned again is the reconciliation - the day is open for changes, and any
	# change invalidates it.
	frappe.db.set_value(
		AUDIT_DOCTYPE,
		audit,
		{
			"reopened_on": now_datetime(),
			"reopened_by": frappe.session.user,
			"reopen_reason": reason.strip(),
			"closed_on": None,
			"closed_by": None,
			"reconciliation_completed_on": None,
			"reconciliation_completed_by": None,
			"reconciled_row_count": 0,
			"reconciled_row_total": 0,
		},
		update_modified=True,
	)

	# The evidence goes with the reconciliation it belongs to. Leaving it would
	# mean the next close was gated on postings accepted before the day was
	# reopened for changes, and the whole point of a reopen is that the day may
	# now change. `reconcile` rebuilds the set from the log, so nothing is lost:
	# a posting that still matters is claimed again on the next run.
	frappe.db.delete(RECONCILED_POSTING_DOCTYPE, {"night_audit": audit})

	return {"audit": audit, "business_date": str(business_date), "reason": reason.strip()}


def _set_business_date(property_name: str, value):
	"""Move the property's business date, through the one guarded path."""
	frappe.flags[BUSINESS_DATE_FLAG] = True
	try:
		property_doc = lock_and_get_doc("Property", property_name)
		property_doc.business_date = getdate(value)
		property_doc.save(ignore_permissions=True)
	finally:
		frappe.flags[BUSINESS_DATE_FLAG] = False

	frappe.clear_document_cache("Property", property_name)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _transition(doc, target: str):
	# Re-running a step that is already in progress is normal - an auditor
	# posts charges, fixes something, posts again - so staying put is a no-op
	# rather than an error.
	if doc.audit_status == target:
		return target

	assert_transition(doc.audit_status, target, TRANSITIONS, _("Night Audit"))

	# `update_modified=False` because the caller usually saves this same
	# in-memory document afterwards; bumping `modified` here would make that
	# save fail with a timestamp mismatch.
	frappe.db.set_value(AUDIT_DOCTYPE, doc.name, "audit_status", target, update_modified=False)
	doc.audit_status = target

	return target


def _save(doc):
	"""Save an audit from inside this service, past the controller's guard."""
	with service_context(NIGHT_AUDIT_SERVICE):
		doc.save(ignore_permissions=True)


def _posted_room_charges(property_name: str, business_date) -> dict:
	"""The night's room revenue, read back off the folios.

	The authoritative answer to "what did this property charge for rooms on
	this date", independent of which run posted it. Reversed rows are excluded:
	a reversal is not revenue.
	"""
	row = frappe.db.sql(
		"""
		select count(*) as rooms, coalesce(sum(c.total_amount), 0) as revenue
		from `tabFolio Charge` c
		inner join `tabGuest Folio` f on f.name = c.parent
		where f.property = %(property)s
		  and c.business_date = %(date)s
		  and c.charge_type = 'Room Charge'
		  and ifnull(c.is_reversed, 0) = 0
		""",
		{"property": property_name, "date": getdate(business_date)},
		as_dict=True,
	)[0]

	return {"rooms": int(row["rooms"] or 0), "revenue": flt(row["revenue"])}


def _audit_date_fingerprint(property_name: str, business_date) -> dict:
	"""A cheap summary of every monetary row dated to this audit.

	Compared at close against the value taken when reconciliation ran. If it
	has moved, something was posted in between and the reconciliation no longer
	describes the money on the folios - so it has to be earned again.

	A fingerprint rather than a flag on purpose: it catches a late charge
	whatever path posted it, without every posting path having to remember to
	invalidate an audit it may know nothing about.
	"""
	charges = frappe.db.sql(
		"""
		select count(*) as rows_count, coalesce(sum(c.total_amount), 0) as total
		from `tabFolio Charge` c
		inner join `tabGuest Folio` f on f.name = c.parent
		where f.property = %(property)s and c.business_date = %(date)s
		""",
		{"property": property_name, "date": getdate(business_date)},
		as_dict=True,
	)[0]

	payments = frappe.db.sql(
		"""
		select count(*) as rows_count, coalesce(sum(p.amount), 0) as total
		from `tabFolio Payment` p
		inner join `tabGuest Folio` f on f.name = p.parent
		where f.property = %(property)s and p.business_date = %(date)s
		""",
		{"property": property_name, "date": getdate(business_date)},
		as_dict=True,
	)[0]

	return {
		"rows": int(charges["rows_count"] or 0) + int(payments["rows_count"] or 0),
		"total": flt(charges["total"]) + flt(payments["total"]),
	}


def _blocking_exceptions(doc) -> list:
	return [row for row in doc.audit_exceptions if row.severity == BLOCKING and not row.is_resolved]


def _refresh_figures(doc, business_date, *, room_revenue: float = 0.0):
	"""Recompute the day's operational and revenue statistics."""
	property_name = doc.property

	arrivals = reservation_service.get_arrivals(property_name, business_date)
	departures = reservation_service.get_departures(property_name, business_date)
	in_house = stay_service.get_in_house(property_name)

	sellable = frappe.db.count("Hotel Room", {"property": property_name, "is_active": 1})
	occupied = len(in_house)

	room_revenue = flt(room_revenue)

	payments = frappe.db.sql(
		"""
		select coalesce(sum(p.amount), 0)
		from `tabFolio Payment` p
		inner join `tabGuest Folio` f on f.name = p.parent
		where f.property = %(property)s and p.business_date = %(date)s
		""",
		{"property": property_name, "date": business_date},
	)[0][0]

	outstanding = frappe.db.sql(
		"""
		select coalesce(sum(balance), 0)
		from `tabGuest Folio`
		where property = %(property)s and folio_status not in ('Settled', 'Closed')
		""",
		{"property": property_name},
	)[0][0]

	doc.arrivals_expected = len(arrivals)
	doc.arrivals_completed = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{"property": property_name, "arrival_date": business_date, "stay_status": ("!=", "Expected")},
	)
	doc.departures_expected = len(departures)
	doc.departures_completed = frappe.db.count(
		stay_service.STAY_DOCTYPE,
		{"property": property_name, "departure_date": business_date, "stay_status": "Checked Out"},
	)
	doc.in_house_rooms = occupied
	doc.payments_received = flt(payments, 2)
	doc.outstanding_balance = flt(outstanding, 2)
	doc.total_revenue = flt(room_revenue, 2)

	# The standard hospitality metrics. ADR is revenue per occupied room;
	# RevPAR is revenue per available room, which is why a hotel can have a
	# high ADR and poor RevPAR at the same time.
	doc.occupancy_percentage = flt((occupied / sellable * 100) if sellable else 0, 2)
	doc.adr = flt((room_revenue / occupied) if occupied else 0, 2)
	doc.revpar = flt((room_revenue / sellable) if sellable else 0, 2)


def run_full_audit(property_name: str, business_date=None) -> dict:
	"""Convenience path: review, post, reconcile.

	Stops short of closing on purpose. A human decides that the day is done -
	an automated close would defeat the exception list.
	"""
	audit = start(property_name, business_date)

	review(audit)
	posting = post_room_charges(audit)
	mark_due_outs(audit)
	reconciliation = reconcile(audit)

	return {
		"audit": audit,
		"posting": posting,
		"reconciliation": reconciliation,
		"audit_status": frappe.db.get_value(AUDIT_DOCTYPE, audit, "audit_status"),
	}
