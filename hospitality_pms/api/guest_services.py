"""Guest requests and complaints board and lifecycle endpoints."""

import frappe

from hospitality_pms.services import guest_services as service
from hospitality_pms.services.base import authorise_document, require_permission
from hospitality_pms.services.property import resolve_property

REQUEST_DOCTYPE = "Guest Request"

REQUEST_FIELDS = (
	"name",
	"property",
	"request_status",
	"request_type",
	"category",
	"priority",
	"subject",
	"description",
	"guest",
	"stay",
	"room",
	"reservation",
	"department",
	"assigned_to",
	"assigned_on",
	"sla_minutes",
	"due_by",
	"responded_on",
	"completed_on",
	"is_breached",
	"escalated_on",
	"escalated_to",
	"escalation_reason",
	"escalation_level",
	"requires_service_recovery",
	"recovery_type",
	"recovery_amount",
	"recovery_approved_by",
	"recovery_folio_charge",
	"resolution",
	"guest_satisfied",
	"reopened_count",
	"currency",
)

#: Fields on a Guest Request that belong to another DocType, and the DocType each
#: one belongs to (16.7.5-R1B).
#:
#: The same shape as `api/kitchen.py`'s `_ORDER_FIELD_SOURCE`, and for the same
#: reason: Guest Request is read by every operational role in the estate, and ten
#: of them - Room Attendant, the housekeeping and maintenance lines, the kitchen
#: roles, Revenue Manager, Corporate Sales Manager - hold neither Guest nor Guest
#: Folio read. `Guest Request.read` is not a licence to disclose whatever the
#: request happens to point at.
#:
#: `guest` is a Guest identifier. It resolves to nothing for these roles - every
#: guest endpoint refuses them - which is exactly why handing it over is a
#: disclosure rather than a convenience: accumulated across a season's requests it
#: is the correlation key the Guest permission was drawn around. `kitchen.py` had
#: already settled the principle for the identifier beside it: "The stay is a Stay
#: identifier like any other, and follows the same rule as the guest and the folio
#: beside it."
#:
#: `recovery_folio_charge` is a Folio Charge child-row name, so a pointer into a
#: Guest Folio; `kitchen.py` pops its equivalent `folio_charge_row` already.
#: `recovery_amount` and `recovery_approved_by` join it: "this guest was given
#: QAR 400, approved by that manager" is a statement about a guest's money and a
#: colleague's authority, and nobody cleaning a room needs either.
#:
#: `requires_service_recovery` and `recovery_type` are deliberately **not** here.
#: "This complaint is being made good, by a voucher" is the operational fact a
#: service team acts on, and it names no money.
#:
#: `stay`, `room`, `reservation`, `department` and `currency` are deliberately not
#: here either, and that is not an oversight. Every one of those DocTypes has a
#: reader set identical to Guest Request's own, so a check on them would never
#: refuse anybody - it would be dead code that reads as protection and misleads
#: the next reviewer into thinking the question had been asked.
_REQUEST_FIELD_SOURCE = {
	"guest": "Guest",
	"recovery_folio_charge": "Guest Folio",
	"recovery_amount": "Guest Folio",
	"recovery_approved_by": "Guest Folio",
}


def _request_disclosure() -> set[str]:
	"""Which request fields this caller may be told, asked once per request.

	Once, not once per row: the answer cannot differ between rows of a single
	response, and asking per row would add a permission lookup per row to a board.
	"""
	allowed = {field for field in REQUEST_FIELDS if field not in _REQUEST_FIELD_SOURCE}

	for field, doctype in _REQUEST_FIELD_SOURCE.items():
		if frappe.has_permission(doctype, "read"):
			allowed.add(field)

	return allowed


def _allowed_transitions(status: str) -> list[str]:
	"""States reachable from `status`, straight from the service.

	Returned so a screen offers exactly what the domain permits instead of
	mirroring the transition table in JavaScript, where the two would
	eventually drift apart.
	"""
	return sorted(service.TRANSITIONS.get(status, set()))


@frappe.whitelist(methods=["GET"])
def board(property: str | None = None, include_closed: int = 0) -> dict:
	"""The guest services board."""
	require_permission(REQUEST_DOCTYPE, "read")
	property_name = resolve_property(property)

	return service.get_board(property_name, include_closed=bool(int(include_closed or 0)))


@frappe.whitelist(methods=["GET"])
def get_request(request: str) -> dict:
	"""One guest request."""
	# `authorise_document` rather than `check_permission` alone (16.7.5). A User
	# Permission created without `apply_to_all_doctypes` restricts only the
	# DocTypes it names, so step 2 can legitimately pass for a record in a
	# property the caller may not operate in - and every one of these DocTypes
	# carries a required `property`, so the third check always fires.
	doc = authorise_document(REQUEST_DOCTYPE, request, "read")

	# Omitted, never blanked. An empty `guest` would read as "no guest raised this
	# request", which for a request raised from a stay is false, and a `0`
	# `recovery_amount` would read as "nothing was paid out".
	allowed = _request_disclosure()

	return {
		"request": {field: doc.get(field) for field in REQUEST_FIELDS if field in allowed},
		"allowed_transitions": _allowed_transitions(doc.request_status),
	}


@frappe.whitelist(methods=["POST"])
def create_request(
	property: str,
	subject: str,
	description: str,
	category: str,
	request_type: str = "Request",
	priority: str = "Normal",
	guest: str | None = None,
	stay: str | None = None,
	room: str | None = None,
	reservation: str | None = None,
	department: str | None = None,
	sla_minutes: int | None = None,
) -> dict:
	"""Raise a guest request or complaint."""
	require_permission(REQUEST_DOCTYPE, "write")
	property_name = resolve_property(property)

	request = service.create_request(
		property_name,
		subject=subject,
		description=description,
		category=category,
		request_type=request_type,
		priority=priority,
		guest=guest,
		stay=stay,
		room=room,
		reservation=reservation,
		department=department,
		sla_minutes=int(sla_minutes) if sla_minutes not in (None, "") else None,
	)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def assign(request: str, assignee: str, department: str | None = None) -> dict:
	"""Assign a request and record its first response."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.assign(request, assignee, department=department)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def start(request: str) -> dict:
	"""Start work on a request."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.start(request)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def complete(request: str, resolution: str, guest_satisfied: int | None = None) -> dict:
	"""Complete a request."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.complete(
		request,
		resolution,
		guest_satisfied=None if guest_satisfied is None else bool(int(guest_satisfied)),
	)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def escalate(request: str, escalate_to: str | None = None, reason: str | None = None) -> dict:
	"""Escalate a request by one level."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.escalate(request, escalate_to=escalate_to, reason=reason)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def reopen(request: str, reason: str) -> dict:
	"""Reopen a completed request the guest is not satisfied with."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.reopen(request, reason)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def close(request: str) -> dict:
	"""Close a completed request."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.close(request)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def apply_service_recovery(
	request: str,
	recovery_type: str,
	reason: str,
	amount: float = 0,
	post_to_folio: int = 1,
) -> dict:
	"""Compensate a guest, posting the cost to their folio when there is one."""
	authorise_document(REQUEST_DOCTYPE, request, "write")

	service.apply_service_recovery(
		request,
		recovery_type,
		amount=float(amount or 0),
		reason=reason,
		post_to_folio=bool(int(post_to_folio or 0)),
	)

	return get_request(request)
