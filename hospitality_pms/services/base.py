"""Shared building blocks for Hospitality PMS domain services.

Rules that every service in this package follows:

* The server is authoritative. Services never trust a caller supplied
  permission, rate, availability or workflow decision (HPMS-DEC-030).
* Services are reusable by Vue APIs, Desk actions, background jobs and
  integrations. They must not depend on an HTTP request being present.
* Operations that mutate shared operational state (availability, room
  assignment, folio settlement, night audit) take database row locks inside
  the caller's transaction (HPMS-DEC-053).
"""

from collections.abc import Iterable
from contextlib import contextmanager

import frappe
from frappe import _

from hospitality_pms.services.exceptions import (
	HospitalityPMSError,
	InvalidStateTransitionError,
	PermissionDeniedError,
	throw,
)


class BaseService:
	"""Optional base for stateful services bound to a property.

	Stateless helper functions are preferred; subclass this only when a service
	genuinely carries context across several calls.
	"""

	def __init__(self, property_name: str | None = None, user: str | None = None):
		self.property = property_name
		self.user = user or frappe.session.user

	@property
	def is_system_user(self) -> bool:
		return self.user in ("Administrator", "System")


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def require_permission(doctype: str, ptype: str = "read", doc=None):
	"""Raise unless the session user holds `ptype` on `doctype`/`doc`.

	Always call this from whitelisted methods that bypass the ORM's automatic
	permission checks (raw queries, aggregate endpoints, service entry points).
	"""
	if frappe.has_permission(doctype, ptype=ptype, doc=doc):
		return

	throw(
		_("You are not permitted to {0} {1}.").format(_(ptype), _(doctype)),
		exc=PermissionDeniedError,
	)


def authorise_document(doctype: str, name: str, ptype: str = "read"):
	"""Load a named document and prove the caller may use *that* document.

	The guard for every endpoint that takes a document identifier from the
	client. `require_permission(doctype, ptype)` on its own is not one: it
	answers "may this user ever charge a folio", which every front office agent
	may, for every property in the estate. It does not answer "may this user
	charge *this* folio", and several endpoints asked only the first question
	and then acted on whatever name arrived (P1-15, N2).

	Three checks, in the order that refuses soonest:

	1. the DocType permission, which needs no query;
	2. `doc.check_permission`, which is Frappe's own document-level check and
	   is what applies the Property User Permission the product relies on
	   (HPMS-DEC-052) - it already answered correctly everywhere it was called;
	3. `require_property_access`, which re-asks the question against the
	   property resolved *from the record*, never from the request.

	The third is not redundant. A User Permission without `apply_to_all_doctypes`
	restricts only the DocTypes it names, so step 2 can legitimately pass for a
	document whose property the user may not operate in. It is also the check
	that would survive someone loosening a permission row by mistake.

	Returns the loaded document, so the caller need not read it twice.

	Deliberately at the controller boundary and not inside the services. The
	same service functions are called by the night audit, by gateway callbacks
	and by the channel importer, none of which act for a session user with
	property permissions - gating them here would break approved automation
	while protecting nothing a client can reach.
	"""
	require_permission(doctype, ptype)

	doc = frappe.get_doc(doctype, name)

	try:
		doc.check_permission(ptype)
	except frappe.PermissionError:
		# Frappe's document check raises with no message at all, so a front
		# desk agent who picks up somebody else's stay saw a blank error box
		# and had nothing to act on (found in UAT). The refusal itself is
		# correct; only its silence was the defect. Deliberately says what was
		# refused and not why - the reason would disclose the very record the
		# check just decided this user may not see.
		throw(
			_("You are not permitted to {0} {1} {2}.").format(_(ptype), _(doctype), name),
			exc=PermissionDeniedError,
		)

	property_name = doc.get("property")

	if property_name:
		# Imported here rather than at module scope: `services.property` is a
		# higher layer than this one, and importing it eagerly would make the
		# base module depend on property configuration to load at all.
		from hospitality_pms.services.property import require_property_access

		require_property_access(property_name)

	return doc


def require_role(roles: str | Iterable[str]):
	"""Raise unless the session user holds at least one of `roles`.

	Role checks are a coarse guard for operational actions that have no single
	owning DocType. Prefer `require_permission` when a DocType exists.
	"""
	if isinstance(roles, str):
		roles = [roles]

	roles = list(roles)
	user_roles = set(frappe.get_roles())

	if user_roles.intersection(roles) or "Administrator" in user_roles:
		return

	throw(
		_("This action requires one of the following roles: {0}.").format(", ".join(_(r) for r in roles)),
		exc=PermissionDeniedError,
	)


# ---------------------------------------------------------------------------
# Operation identity
# ---------------------------------------------------------------------------

#: `Folio Charge.idempotency_key` and its siblings are Data columns, which
#: MariaDB stores as varchar(140). A longer key would be truncated, and two
#: operations whose keys differ only past the cut would silently become one.
MAX_OPERATION_KEY_LENGTH = 140


def require_operation_key(idempotency_key: str | None, operation: str) -> str:
	"""Insist the caller names the operation it is performing.

	A mutating financial endpoint used to invent a key when the caller supplied
	none - `f"manual:{folio}:{frappe.generate_hash()}"`. That reads like
	idempotency and is the opposite of it: the key was regenerated on every
	HTTP attempt, so a client that timed out and retried produced a *new*
	identity and the guest was charged twice (P2-3).

	The key belongs to the user's action, not to the HTTP attempt, so only the
	caller can supply it: one key per thing the operator did, reused across
	every retry of that thing, replaced only when they do something new.

	Deriving the key from the payload instead was considered and rejected. Two
	minibar waters at the same price with the same description are genuinely
	two charges, and a content hash cannot tell them from one charge sent
	twice.
	"""
	key = (idempotency_key or "").strip()

	if not key:
		throw(
			_(
				"{0} requires an operation key. Send one key per action and reuse it if the "
				"request is retried, so a lost response cannot post twice."
			).format(_(operation)),
			exc=HospitalityPMSError,
		)

	if len(key) > MAX_OPERATION_KEY_LENGTH:
		throw(
			_("An operation key may not be longer than {0} characters.").format(
				MAX_OPERATION_KEY_LENGTH
			),
			exc=HospitalityPMSError,
		)

	return key


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def lock_document(doctype: str, name: str) -> str:
	"""Take a `SELECT ... FOR UPDATE` row lock on a single document.

	The lock is held until the surrounding transaction commits or rolls back,
	which for a whitelisted method is the end of the request.

	**This serialises, it does not refresh.** It returns only the name, which
	never changes, and any plain read that follows it is still answered from
	this transaction's REPEATABLE-READ snapshot - taken before the lock was
	granted. So a caller that locks, waits behind another writer, and then
	reads with `frappe.get_doc()` or a plain `frappe.db.get_value()` sees the
	*pre-lock* value and decides on state that is no longer true (N1).

	Use this only to serialise access to a row whose current values the
	operation does not read - a Hotel Room locked so two check-ins cannot pick
	it at once, say. Whenever a guard, a total or a state transition depends on
	the row's contents, use `lock_and_read()` or `lock_and_get_doc()` instead.
	"""
	locked = frappe.db.get_value(doctype, name, "name", for_update=True)

	if not locked:
		frappe.throw(_("{0} {1} not found.").format(_(doctype), name), frappe.DoesNotExistError)

	return locked


def lock_and_read(doctype: str, name: str, fields: str | Iterable[str]) -> dict:
	"""Lock a row and return its **current** values from that same locking read.

	This is the primitive to reach for before any locked read-decide-write. Its
	contract is the one `lock_document()` cannot offer:

	    the values returned are the latest committed values as of the moment
	    the lock was granted, not this transaction's earlier snapshot.

	That holds because InnoDB answers a locking read (`SELECT ... FOR UPDATE`)
	from the current row version rather than from the consistent snapshot, and
	because the fields the caller will decide on are selected *by that same
	statement*. Splitting it into a lock and a later read reintroduces N1, so
	the two are deliberately one call.

	Raises `DoesNotExistError` when the row is gone, which is the same contract
	as `lock_document()`.
	"""
	if isinstance(fields, str):
		fields = [fields]

	# Deduplicated, order preserved: a caller composing a field list from
	# several guards should not have to care whether they overlap.
	fields = list(dict.fromkeys(fields))

	values = frappe.db.get_value(doctype, name, fields, as_dict=True, for_update=True)

	if not values:
		frappe.throw(_("{0} {1} not found.").format(_(doctype), name), frappe.DoesNotExistError)

	return values


def lock_and_find(doctype: str, filters: dict, fields: str | Iterable[str]) -> dict | None:
	"""Look a row up by filters with a **current** read, or answer None.

	`lock_and_read`'s contract for a lookup that may legitimately find nothing -
	"has this operation already been claimed?" being the case it exists for.

	A plain read cannot answer that question under concurrency. The transaction
	asking it opened its snapshot before the winner committed the claim, so it
	sees no row, concludes the operation is free, and performs it a second time.
	A locking read is answered from the current row version instead, so the
	claim the winner just committed is visible - and, when there is still no
	row, the gap is locked, so the answer stays true until this transaction
	ends.
	"""
	if isinstance(fields, str):
		fields = [fields]

	return frappe.db.get_value(doctype, filters, list(fields), as_dict=True, for_update=True)


def lock_and_get_doc(doctype: str, name: str):
	"""Lock a document and load it, parent and children, with current values.

	The whole-document form of `lock_and_read()`, for operations that need more
	than a handful of fields or that need the child tables - a folio's charges
	and payments, a reservation's room lines.

	Frappe's own `for_update` load is what makes this current: it selects the
	parent row and every child row with `FOR UPDATE`, so all of them come back
	as locking reads rather than snapshot reads. The child rows are locked too,
	which is wanted here - the money on a folio is in its child tables, and a
	guard that read those from the snapshot would be exactly as wrong as one
	that read a stale parent.
	"""
	return frappe.get_doc(doctype, name, for_update=True)


def lock_documents(doctype: str, names: Iterable[str]) -> list[str]:
	"""Lock several documents of one DocType in a deterministic order.

	Sorting the keys before locking keeps concurrent callers from deadlocking
	against each other when they touch overlapping sets of rows.

	Carries the same caveat as `lock_document()`: this serialises and does not
	refresh.
	"""
	return [lock_document(doctype, name) for name in sorted(set(names))]


# ---------------------------------------------------------------------------
# Internal service contexts
# ---------------------------------------------------------------------------
#
# Some records may only come into existence through an approved service, never
# through a generic document save. Permissions cannot express that: the front
# desk legitimately holds write on Guest Folio and Stay, and the rule is about
# *which code path* created the row, not about who asked.
#
# So an approved service marks the narrow window in which it is doing that
# work, and the DocType controller refuses the write outside it.
#
# Three properties make this a boundary rather than a suggestion:
#
# * It lives in `frappe.flags`, which is `frappe.local.flags` - created fresh
#   per request and discarded with it. There is no field, argument or payload
#   key through which a caller can set it. (`flags` is also one of Frappe's
#   RESERVED_KEYWORDS, so it cannot be smuggled in through a document dict.)
# * It is entered only by a context manager that restores the previous value in
#   a `finally`, so an exception mid-post cannot leave the door open for the
#   rest of the request.
# * It nests by depth rather than by boolean, because approved services call
#   one another - `reverse_charge` posts through `post_charge` - and the inner
#   call must not close the door behind the outer one on the way out.

#: Creating or mutating the monetary child rows of a Guest Folio.
FINANCIAL_POSTING = "hpms_financial_posting"

#: Creating a Stay as part of check-in or another approved orchestration.
STAY_ORCHESTRATION = "hpms_stay_orchestration"

#: Writing the Night Audit's workflow status, completion markers and figures.
NIGHT_AUDIT_SERVICE = "hpms_night_audit_service"


@contextmanager
def service_context(flag: str):
	"""Mark the narrow window in which an approved service is doing its work.

	Wrap the smallest possible region - ideally the single `insert()` or
	`save()` that has to be authorised - so unrelated writes that happen to
	occur in the same request are not swept in with it.
	"""
	previous = frappe.flags.get(flag) or 0
	frappe.flags[flag] = previous + 1

	try:
		yield
	finally:
		frappe.flags[flag] = previous


def in_service_context(flag: str) -> bool:
	"""Whether an approved service is currently inside `flag`'s window."""
	return bool(frappe.flags.get(flag))


def assert_service_context(flag: str, message: str):
	"""Refuse a write that did not come through the approved service."""
	if in_service_context(flag):
		return

	throw(message, exc=PermissionDeniedError)


@contextmanager
def transaction():
	"""Run a block inside a savepoint, rolling back only that block on failure.

	This keeps a failed sub-operation from discarding work the caller already
	committed to the current transaction.
	"""
	# The `sp_` prefix is not cosmetic. A savepoint name is an unquoted SQL
	# identifier, and a random hex hash such as `06e5d9b647` is lexed by MariaDB
	# as the number `06e5` followed by junk - a syntax error that would strike
	# only on the fraction of hashes that happen to start `<digits>e`. Leading
	# with a letter makes the identifier unambiguous every time.
	savepoint = f"sp_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(savepoint)

	try:
		yield
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------


def assert_transition(current: str, target: str, allowed: dict[str, Iterable[str]], label: str):
	"""Validate a state machine transition declared by a service.

	`allowed` maps a current state to the states reachable from it. Services
	keep their own transition table so the rule stays close to the logic that
	enforces it, and so the Workflow Matrix can be read directly off the code.
	"""
	if target in (allowed.get(current) or ()):
		return

	throw(
		_("{0} cannot move from {1} to {2}.").format(_(label), _(current), _(target)),
		exc=InvalidStateTransitionError,
	)
