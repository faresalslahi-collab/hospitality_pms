"""Guest requests and complaints board and lifecycle endpoints."""

import frappe

from hospitality_pms.services import guest_services as service
from hospitality_pms.services.base import require_permission
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
	require_permission(REQUEST_DOCTYPE, "read")

	doc = frappe.get_doc(REQUEST_DOCTYPE, request)
	doc.check_permission("read")

	return {
		"request": {field: doc.get(field) for field in REQUEST_FIELDS},
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
	require_permission(REQUEST_DOCTYPE, "write")

	service.assign(request, assignee, department=department)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def start(request: str) -> dict:
	"""Start work on a request."""
	require_permission(REQUEST_DOCTYPE, "write")

	service.start(request)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def complete(request: str, resolution: str, guest_satisfied: int | None = None) -> dict:
	"""Complete a request."""
	require_permission(REQUEST_DOCTYPE, "write")

	service.complete(
		request,
		resolution,
		guest_satisfied=None if guest_satisfied is None else bool(int(guest_satisfied)),
	)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def escalate(request: str, escalate_to: str | None = None, reason: str | None = None) -> dict:
	"""Escalate a request by one level."""
	require_permission(REQUEST_DOCTYPE, "write")

	service.escalate(request, escalate_to=escalate_to, reason=reason)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def reopen(request: str, reason: str) -> dict:
	"""Reopen a completed request the guest is not satisfied with."""
	require_permission(REQUEST_DOCTYPE, "write")

	service.reopen(request, reason)

	return get_request(request)


@frappe.whitelist(methods=["POST"])
def close(request: str) -> dict:
	"""Close a completed request."""
	require_permission(REQUEST_DOCTYPE, "write")

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
	require_permission(REQUEST_DOCTYPE, "write")

	service.apply_service_recovery(
		request,
		recovery_type,
		amount=float(amount or 0),
		reason=reason,
		post_to_folio=bool(int(post_to_folio or 0)),
	)

	return get_request(request)
