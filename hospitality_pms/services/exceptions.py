"""Domain exception hierarchy for Hospitality PMS.

Services raise these instead of generic exceptions so that API controllers,
Desk actions, background jobs and integrations can map failures to consistent
HTTP status codes and translated user messages.

All messages must be translatable; never embed untranslated English inside
reusable service logic (Frontend Standards section 10).
"""

import frappe
from frappe.exceptions import ValidationError


class HospitalityPMSError(ValidationError):
	"""Base class for every Hospitality PMS domain error."""

	http_status_code = 417


class ConfigurationError(HospitalityPMSError):
	"""Required property/system configuration is missing or invalid."""


class PermissionDeniedError(HospitalityPMSError):
	"""The current user is not authorised for this operation."""

	http_status_code = 403


class PropertyAccessError(PermissionDeniedError):
	"""The current user has no access to the requested property."""


class InvalidStateTransitionError(HospitalityPMSError):
	"""The requested transition is not allowed from the current document state."""


class AvailabilityError(HospitalityPMSError):
	"""Requested inventory cannot be sold or held."""


class RoomNotAssignableError(AvailabilityError):
	"""The room cannot be assigned in its current status."""


class OverbookingError(AvailabilityError):
	"""The operation would exceed the approved overbooking threshold."""


class RateError(HospitalityPMSError):
	"""A rate could not be resolved or is not authorised."""


class FolioError(HospitalityPMSError):
	"""A folio operation is not valid."""


class PostingError(HospitalityPMSError):
	"""An ERPNext financial or inventory posting failed."""


class ReconciliationError(PostingError):
	"""Posted documents do not reconcile with the operational subledger."""


class NightAuditError(HospitalityPMSError):
	"""Night Audit cannot proceed in the current state."""


class IntegrationError(HospitalityPMSError):
	"""An external provider call failed."""

	http_status_code = 502


class DuplicateRequestError(IntegrationError):
	"""An idempotent operation was replayed; the original result stands."""

	http_status_code = 409


def throw(message: str, exc: type[Exception] = HospitalityPMSError, title: str | None = None):
	"""Raise a translated domain error."""
	frappe.throw(message, exc=exc, title=title or frappe._("Hospitality PMS"))
