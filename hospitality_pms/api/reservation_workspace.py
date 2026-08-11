"""Read models for the Reservation Workspace.

Two endpoints, both read-only: the workspace payload the screen opens on, and the
booking's history. Every mutation the workspace performs goes through the hardened
reservation services in `api.reservations`; nothing here writes.

**Why this module exists separately from `api/reservations.py`.** That module is the
reservation *lifecycle* surface — create, quote, confirm, guarantee, cancel,
no-show, assign, modify. These two are a screen's read model: one aggregate
assembled for one page, and an audit view. Keeping them apart means the lifecycle
API is not gradually reshaped by what a particular screen wanted to display.

**The disclosure rule, which is the whole reason this file is careful.** A
reservation workspace is an aggregate, and an aggregate is where permission
boundaries quietly dissolve. 16.7.1 shipped a board that gated on `Stay.read` and
then handed out Guest Folio balances and Guest standing, because each field was
read with a permission-free `frappe.get_all` and only the endpoint's own DocType
was ever checked. Ten roles received data whose DocType they could not open.

So every field group below is gated on `frappe.has_permission(<the DocType the
value actually came from>, "read")`, and a caller who is not cleared gets **no
key** rather than a blanked one — absence reads as "not disclosed to you", where a
`0.00` reads as "nothing owed" and would be a lie. Reservation read is never
assumed to imply Guest, Guest Folio or Corporate Account read.

Concretely, per group:

- reservation's own fields, room lines, rate snapshot, deposit *expectation* -
  Reservation. `deposit_required`, `deposit_received`, `deposit_policy` and the
  per-line allocation are Reservation columns and arithmetic over them.
- `deposit_credited` - **Guest Folio**, because `reservations.deposit_credited`
  joins `Folio Payment` to `Guest Folio` to answer it.
- guest standing (`vip_status`, `guest_type`) - Guest. The blacklist flag is
  permlevel 2 on top of that and is answered by `guests.may_see_blacklist()`.
- corporate contract and credit position - Corporate Account.
"""

import frappe

from hospitality_pms.services import corporate as corporate_service
from hospitality_pms.services import guests as guest_service
from hospitality_pms.services import reservations as service
from hospitality_pms.services.base import authorise_document, require_permission

RESERVATION_DOCTYPE = "Reservation"
RESERVATION_LOG_DOCTYPE = "Reservation Log"
GUEST_DOCTYPE = "Guest"
FOLIO_DOCTYPE = "Guest Folio"
CORPORATE_DOCTYPE = "Corporate Account"
RATE_PLAN_DOCTYPE = "Rate Plan"
ROOM_DOCTYPE = "Hotel Room"
ROOM_TYPE_DOCTYPE = "Room Type"
STAY_DOCTYPE = "Stay"

#: The reservation's own columns the workspace renders. An allow list, so a field
#: added to the DocType later is not published by accident.
WORKSPACE_FIELDS = (
	"name",
	"property",
	"reservation_status",
	"reservation_type",
	"guest",
	"guest_name",
	"guest_mobile",
	"arrival_date",
	"departure_date",
	"arrival_time",
	"nights",
	"total_rooms",
	"total_adults",
	"total_children",
	"total_amount",
	"room_charges_total",
	"currency",
	"booking_source",
	"market_segment",
	"external_reference",
	"special_requests",
	"internal_notes",
	"guarantee_type",
	"guaranteed_on",
	"booked_on",
	"cancellation_charge",
)

#: Deposit expectation: Reservation columns, and arithmetic over them only.
DEPOSIT_FIELDS = ("deposit_policy", "deposit_required", "deposit_received", "deposit_due_date")

#: How many log rows a screen gets. History is a tab, not a report.
HISTORY_LIMIT = 100
MAX_HISTORY_LIMIT = 200


@frappe.whitelist(methods=["GET"])
def get_workspace(reservation: str) -> dict:
	"""Everything the Reservation Workspace opens with, in one request.

	One call rather than one per tab: the tabs are views of a single booking, and
	a screen that fetched six times would show six different moments of it.
	"""
	doc = authorise_document(RESERVATION_DOCTYPE, reservation, "read")

	may_read = _disclosure()

	payload = {
		"reservation": {field: doc.get(field) for field in WORKSPACE_FIELDS},
		"rooms": _room_lines(doc, may_read),
		"deposit": _deposit_position(doc, may_read),
		"editability": editability(doc.reservation_status),
		# Which source DocTypes this caller may read, so a missing block can be
		# told apart from an empty one. Without it, an absent `corporate` means
		# either "this booking has no company" or "you may not see the company",
		# and a screen cannot say the honest thing about either. This discloses
		# nothing about the record — only what the caller's own roles allow.
		"disclosure": dict(may_read),
		# The server's state machine, not a copy of it. The client offers what
		# this says and never derives it; a stale offer fails cleanly because
		# `_transition` re-reads the status under a lock.
		"allowed_transitions": sorted(service.TRANSITIONS.get(doc.reservation_status, set())),
	}

	payload.update(_guest_standing(doc.guest, may_read))
	payload.update(_corporate_context(doc, may_read))

	return payload


@frappe.whitelist(methods=["GET"])
def get_history(reservation: str, limit: int = HISTORY_LIMIT) -> dict:
	"""The booking's audit trail, shaped for an operator.

	`Reservation Log` is a purpose-built audit DocType written by
	`reservations._transition`, so there is no need to go near Frappe's `Version`
	rows — and no temptation to put raw document JSON in front of a reservation
	agent, which is how a screen ends up disclosing fields nobody reviewed.

	`details` is a JSON blob written by whichever service recorded the change. It
	is **not** passed through. Only the keys named in `_HISTORY_DETAIL_KEYS` are
	published, so a service that later logs something sensitive does not
	retroactively publish it here.
	"""
	# Both gates, and the second is the one this endpoint got wrong first time.
	#
	# `authorise_document` proves the caller may see *this booking*, including its
	# property. It does not prove they may see the booking's **log**, and those are
	# different reader sets by design: Reservation is readable by 23 roles
	# (OPERATIONAL + AUDITOR), Reservation Log by 9 (`setup.permissions`:
	# TECHNICAL_READERS + RESERVATIONS + Front Office Manager). The 14 in the gap
	# include Room Attendant, the kitchen and housekeeping — and a log row carries
	# `changed_by`, the transition, and a free-text `reason` that holds
	# cancellation reasons and manager override justifications.
	#
	# The first version of this reasoned that "permission to see the log is
	# permission to see that document". That is a decision, not a derivation, and
	# it contradicts the approved matrix — the same shape as the 16.7.1 defect this
	# whole file is written to avoid, in the one place the rule had not been
	# applied. `frappe.get_all` below is permission-free, so nothing else would
	# have caught it.
	require_permission(RESERVATION_LOG_DOCTYPE, "read")
	authorise_document(RESERVATION_DOCTYPE, reservation, "read")

	limit = max(1, min(int(limit or HISTORY_LIMIT), MAX_HISTORY_LIMIT))

	rows = frappe.get_all(
		RESERVATION_LOG_DOCTYPE,
		filters={"reservation": reservation},
		fields=[
			"name",
			"changed_by",
			"changed_at",
			"from_status",
			"to_status",
			"reason",
			"details",
		],
		order_by="changed_at desc, creation desc",
		limit=limit,
	)

	return {
		"reservation": reservation,
		"limit": limit,
		"entries": [_history_entry(row) for row in rows],
	}


# ---------------------------------------------------------------------------
# Editability
# ---------------------------------------------------------------------------


def editability(status: str) -> dict:
	"""What may be changed on a booking in this status, decided server side.

	Published so the workspace can disable a control without re-deriving the rule,
	and so there is exactly one statement of it. Every flag here mirrors a guard
	that already exists and will refuse regardless — `Reservation._is_editable`,
	`_guard_holding_immutability` and `_guard_room_line_immutability` — so this is
	what to *offer*, never a substitute for the check.

	The distinction the controller draws: a booking that has not yet committed to
	inventory (Draft, Tentative, Waitlisted) is still a working draft and its rate
	snapshot may be recomputed; once it holds inventory the guest has been quoted
	those amounts, and once it is terminal there is nothing left to price.
	"""
	from hospitality_pms.hospitality_reservations.doctype.reservation.reservation import (
		TERMINAL_STATES,
	)

	holding = status in service.HOLDING_STATES
	terminal = status in TERMINAL_STATES
	draft_like = not holding and not terminal
	checked_in = status == service.CHECKED_IN

	return {
		"status": status,
		# Draft-like: the snapshot is still a draft, so pricing may move.
		"is_draft_like": draft_like,
		"is_holding": holding,
		"is_terminal": terminal,
		# The non-inventory fields carry no availability consequence, so they stay
		# editable for as long as the booking is live.
		"may_edit_details": not terminal,
		# The move/rebook operation: permitted while draft-like and while holding,
		# but not once a Stay owns the dates (`extend_stay`/`shorten_stay` do that)
		# and not once terminal.
		"may_change_dates": (draft_like or holding) and not checked_in,
		# The controller refuses these beyond draft-like outright — "cancel and
		# rebook instead" — because they change what availability counted.
		"may_add_or_remove_rooms": draft_like,
		"may_change_room_type": draft_like,
		# Changing the rate plan re-quotes, which is only safe while the snapshot
		# is still a draft.
		"may_change_rate_plan": draft_like,
		"may_assign_room": (draft_like or holding) and not terminal,
		# Deposit is display-only in this build; money moves through the folio and
		# payment services, never through a reservation field.
		"may_edit_deposit": False,
	}


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------


def _disclosure() -> dict:
	"""Which source DocTypes this caller may read.

	Asked once per request: the answer cannot differ between fields of one
	response, and asking per field would be four permission checks per room line.
	"""
	return {
		"guest": frappe.has_permission(GUEST_DOCTYPE, "read"),
		"folio": frappe.has_permission(FOLIO_DOCTYPE, "read"),
		"corporate": frappe.has_permission(CORPORATE_DOCTYPE, "read"),
		"room": frappe.has_permission(ROOM_DOCTYPE, "read"),
		"room_type": frappe.has_permission(ROOM_TYPE_DOCTYPE, "read"),
		"rate_plan": frappe.has_permission(RATE_PLAN_DOCTYPE, "read"),
		"stay": frappe.has_permission(STAY_DOCTYPE, "read"),
	}


def _guest_standing(guest: str | None, may_read: dict) -> dict:
	"""The guest's standing, for a caller entitled to the Guest record.

	permlevel 0 means "unprivileged among people entitled to the record", not
	"public": a reservation reader who holds no Guest permission is not owed the
	guest's VIP standing. The blacklist flag is a second, narrower question and is
	answered by the one helper that owns it.
	"""
	if not guest or not may_read["guest"]:
		return {}

	fields = ["vip_status", "guest_type"]

	if guest_service.may_see_blacklist():
		fields.append("is_blacklisted")

	record = frappe.db.get_value(GUEST_DOCTYPE, guest, fields, as_dict=True) or {}

	standing = {
		"vip_status": record.get("vip_status") or "",
		"guest_type": record.get("guest_type") or "",
	}

	# Absent, never `False`: `False` is a claim about the guest that an uncleared
	# caller is not entitled to and that may be untrue.
	if "is_blacklisted" in record:
		standing["is_blacklisted"] = bool(record["is_blacklisted"])

	return {"guest_standing": standing}


def _deposit_position(doc, may_read: dict) -> dict:
	"""What is expected, and — for a folio reader — what has actually been credited.

	The expectation is Reservation's own: `deposit_required` is what the policy
	asks for and `deposit_received` is what the booking records having taken. The
	per-line allocation is arithmetic over those and the line values, so it needs
	nothing further.

	`deposit_credited` is a different thing and a different DocType:
	`reservations.deposit_credited` joins `Folio Payment` to `Guest Folio` to ask
	what the folios of this booking have actually been credited. That is folio
	money, so it is disclosed only to a folio reader.
	"""
	position = {field: doc.get(field) for field in DEPOSIT_FIELDS}

	# A pure function of what is stored — see `deposit_allocation`'s docstring for
	# why the shares are rounded so they add back to the deposit exactly.
	position["allocation"] = service.deposit_allocation(doc)

	if may_read["folio"]:
		position["credited"] = service.deposit_credited(doc.name)

	return position


def _corporate_context(doc, may_read: dict) -> dict:
	"""The company behind the booking, where there is one and the caller may see it.

	Operational context only — which account, is its contract valid, and (for a
	corporate reader) where its credit stands. Corporate master administration
	stays in Desk; nothing here edits an account.
	"""
	account = doc.get("corporate_account")

	if not account or not may_read["corporate"]:
		return {}

	context = {"account": account}

	record = frappe.db.get_value(
		CORPORATE_DOCTYPE, account, ["account_name", "credit_status"], as_dict=True
	)

	if record:
		context["account_name"] = record.get("account_name") or ""
		context["credit_status"] = record.get("credit_status") or ""

	# The credit position is the account's own money and is answered by the
	# hardened service, never recomputed here. A reservation is priced against the
	# night in question, so contract validity is asked for this booking's arrival
	# rather than for today.
	try:
		context["credit"] = corporate_service.get_credit_position(account)
	except Exception:  # noqa: BLE001
		# A configuration problem on the account must not take the workspace down;
		# the corporate tab reports that the position is unavailable instead.
		context["credit"] = None

	return {"corporate": context}


# ---------------------------------------------------------------------------
# Room lines and history rows
# ---------------------------------------------------------------------------


def _room_lines(doc, may_read: dict) -> list[dict]:
	"""One entry per operational room line, with its own rate snapshot.

	The snapshot is stored flat on the reservation because Frappe has no
	grandchild tables, so it is regrouped per line here — which is what lets the
	Rooms & Rates tab show a per-night breakdown without a second request.

	`rooms` is published deliberately: it is 1 on every operational line after
	confirmation (the Wave 5 invariant `normalise_room_lines` enforces), and a
	screen that can see the value is a screen that can prove it.

	Three enrichments, each gated on the DocType it comes from:

	- **the room's number and condition** (Hotel Room). `assigned_room` is a
	  docname, which is the room *code*, not the number on the door — a screen
	  that showed the code as a room number would disagree with every board.
	- **the room type's display name** (Room Type), for the same reason.
	- **the line's stay**, if it has become one (Stay). `Reservation Room.
	  reservation_status` is a *copy of the header status*, identical on all three
	  lines of a three-room booking, so it cannot say "room 1 is in house and the
	  other two are not" — which is exactly the per-line fact an agent needs. It
	  is still published, because it is the line's own column, but `stay` is what
	  a screen should read, and once a stay exists `stay_room` is where the guest
	  actually is: `stays.change_room` moves the Stay and the folio and never
	  writes back to `assigned_room`.
	"""
	rates_by_line: dict[str, list[dict]] = {}

	for rate in doc.rate_lines:
		rates_by_line.setdefault(rate.room_line, []).append(
			{
				"rate_date": rate.rate_date,
				"rate": rate.rate,
				"extra_adult_charge": rate.extra_adult_charge,
				"extra_child_charge": rate.extra_child_charge,
				"extra_bed_charge": rate.extra_bed_charge,
				"net_rate": rate.net_rate,
			}
		)

	room_states = _room_states(doc, may_read)
	room_type_names = _room_type_names(doc, may_read)
	rate_plan_names = _rate_plan_names(doc, may_read)
	stays_by_line = _stays_by_line(doc, may_read)

	lines = []

	for line in doc.rooms:
		entry = {
			"name": line.name,
			"idx": line.idx,
			"room_type": line.room_type,
			"rooms": line.rooms,
			"arrival_date": line.arrival_date,
			"departure_date": line.departure_date,
			"nights": line.nights,
			"adults": line.adults,
			"children": line.children,
			"extra_beds": line.extra_beds,
			"rate_plan": line.rate_plan,
			"assigned_room": line.assigned_room,
			# An average net rate *including* extra-adult, extra-child and
			# extra-bed supplements, so on any stay with an uplift or a free night
			# it equals no actual night. A screen must label it as an average and
			# put the real figures from `rate_lines` beside it.
			"room_rate": line.room_rate,
			"total_amount": line.total_amount,
			"reservation_status": line.reservation_status,
			"special_requests": line.special_requests,
			"rate_lines": rates_by_line.get(line.name, []),
		}

		if line.room_type in room_type_names:
			entry["room_type_name"] = room_type_names[line.room_type]

		if line.rate_plan in rate_plan_names:
			entry["rate_plan_name"] = rate_plan_names[line.rate_plan]

		state = room_states.get(line.assigned_room) if line.assigned_room else None

		if state:
			entry["room_number"] = state["room_number"]
			entry["room_ready"] = bool(state["ready"])
			entry["room_assignable"] = bool(state["assignable"])
			entry["housekeeping_status"] = state["housekeeping_status"]
			entry["occupancy_status"] = state["occupancy_status"]

		stay = stays_by_line.get(line.name)

		if stay:
			entry["stay"] = stay["name"]
			entry["stay_status"] = stay["stay_status"]
			# Where the guest actually is, which after a room move is not
			# `assigned_room`.
			entry["stay_room"] = stay["room"]

		lines.append(entry)

	return lines


def _room_states(doc, may_read: dict) -> dict[str, dict]:
	"""The assigned rooms' numbers and condition, in one query — for a room reader."""
	if not may_read["room"]:
		return {}

	rooms = [line.assigned_room for line in doc.rooms if line.assigned_room]

	if not rooms:
		return {}

	# The same helper the boards use, so a room reads identically on the workspace
	# and on the rack.
	from hospitality_pms.services.front_office import get_room_states

	return get_room_states(doc.property, rooms)


def _room_type_names(doc, may_read: dict) -> dict[str, str]:
	"""Display names for the room types on this booking — for a Room Type reader.

	Gated on Room Type, not on Hotel Room. They are separate DocTypes with
	separate permissions, and the first draft of this conflated them: close enough
	in practice on this site, wrong as a rule, and the rule is the point.
	"""
	if not may_read["room_type"]:
		return {}

	types = {line.room_type for line in doc.rooms if line.room_type}

	if not types:
		return {}

	records = frappe.get_all(
		ROOM_TYPE_DOCTYPE,
		filters={"name": ("in", list(types))},
		fields=["name", "room_type_name"],
		limit_page_length=0,
	)

	return {row["name"]: row["room_type_name"] or row["name"] for row in records}


def _rate_plan_names(doc, may_read: dict) -> dict[str, str]:
	"""Display names for the rate plans on this booking — for a Rate Plan reader.

	A rate plan's *name* is commercial configuration, so it follows the same rule
	as everything else here: the line's own `rate_plan` column travels regardless,
	the human-readable name only to a caller entitled to the record it comes from.
	Without it a screen has to print the docname where the picker prints the name,
	which is the same code-versus-name inconsistency `room_number` exists to avoid.
	"""
	if not may_read["rate_plan"]:
		return {}

	plans = {line.rate_plan for line in doc.rooms if line.rate_plan}

	if not plans:
		return {}

	records = frappe.get_all(
		RATE_PLAN_DOCTYPE,
		filters={"name": ("in", list(plans))},
		fields=["name", "rate_plan_name"],
		limit_page_length=0,
	)

	return {row["name"]: row["rate_plan_name"] or row["name"] for row in records}


def _stays_by_line(doc, may_read: dict) -> dict[str, dict]:
	"""Which room lines have become a stay, in one query — for a stay reader.

	Includes `Expected`, unlike the arrivals board's equivalent: a workspace
	deciding whether to offer "check in this room" needs to know a stay is already
	mid-creation, where a board only cares whether the guest is in.
	"""
	if not may_read["stay"]:
		return {}

	records = frappe.get_all(
		STAY_DOCTYPE,
		filters={"reservation": doc.name},
		fields=["name", "reservation_room_line", "stay_status", "room"],
		limit_page_length=0,
	)

	return {row["reservation_room_line"]: row for row in records if row["reservation_room_line"]}


#: Keys published out of a log row's `details` blob. An allow list: a service that
#: later records something sensitive in `details` does not retroactively publish it
#: through this endpoint.
_HISTORY_DETAIL_KEYS = (
	"room_line",
	"room_type",
	"assigned_room",
	"arrival_date",
	"departure_date",
	"nights",
	"rate_plan",
	"overbooked",
	"no_show_charge",
	"cancellation_charge",
	"waived",
	"fields",
)


def _history_entry(row: dict) -> dict:
	"""One log row, with its details filtered to reviewed keys."""
	details = row.get("details")

	if isinstance(details, str) and details:
		try:
			details = frappe.parse_json(details)
		except Exception:  # noqa: BLE001
			details = None

	if not isinstance(details, dict):
		details = {}

	return {
		"name": row["name"],
		"changed_by": row["changed_by"],
		"changed_at": row["changed_at"],
		"from_status": row["from_status"],
		"to_status": row["to_status"],
		"reason": row["reason"],
		"details": {key: details[key] for key in _HISTORY_DETAIL_KEYS if key in details},
	}
