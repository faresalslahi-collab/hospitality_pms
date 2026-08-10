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
# Concurrency
# ---------------------------------------------------------------------------


def lock_document(doctype: str, name: str) -> str:
	"""Take a `SELECT ... FOR UPDATE` row lock on a single document.

	The lock is held until the surrounding transaction commits or rolls back,
	which for a whitelisted method is the end of the request. Use this before
	reading state that the same operation is about to change.
	"""
	locked = frappe.db.get_value(doctype, name, "name", for_update=True)

	if not locked:
		frappe.throw(_("{0} {1} not found.").format(_(doctype), name), frappe.DoesNotExistError)

	return locked


def lock_documents(doctype: str, names: Iterable[str]) -> list[str]:
	"""Lock several documents of one DocType in a deterministic order.

	Sorting the keys before locking keeps concurrent callers from deadlocking
	against each other when they touch overlapping sets of rows.
	"""
	return [lock_document(doctype, name) for name in sorted(set(names))]


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
