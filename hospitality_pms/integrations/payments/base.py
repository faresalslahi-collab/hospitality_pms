"""The payment provider interface.

Every adapter implements this and nothing more. If a domain service needs a
capability, it is added here first and implemented by every provider - which is
what stops provider-specific behaviour leaking into the folio (SAD section 10).

Money rules that hold for every provider:

* An operation is identified by an idempotency key the caller supplies. The
  adapter passes it to the provider where the provider supports one, and the
  PaymentService uses it regardless, so a replayed callback is a no-op.
* An adapter never writes to a folio. It returns a result; the service decides
  what that means for the guest's balance.
* Every call is logged, success or failure, through `log_request`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import frappe
from frappe.utils import now_datetime

INTEGRATION_LOG = "PMS Integration Log"


@dataclass
class PaymentResult:
	"""What a provider says happened.

	`status` uses the Payment Transaction vocabulary, so adapters
	translate provider-specific status strings rather than leaking them.
	"""

	success: bool
	status: str
	provider_reference: str | None = None
	amount: float = 0.0
	payment_url: str | None = None
	provider_status: str | None = None
	failure_reason: str | None = None
	raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
	"""Base class for a payment provider adapter."""

	#: Provider name as it appears on the configuration row.
	name: str = ""

	def __init__(self, config):
		self.config = config
		self.property = config.property

	# -- capabilities --------------------------------------------------

	@abstractmethod
	def initiate_payment(
		self,
		amount: float,
		currency: str,
		idempotency_key: str,
		*,
		reference: str | None = None,
		description: str | None = None,
		return_url: str | None = None,
		metadata: dict | None = None,
	) -> PaymentResult:
		"""Start a payment and return where the guest should be sent."""

	@abstractmethod
	def get_status(self, provider_reference: str) -> PaymentResult:
		"""Ask the provider what happened to a transaction.

		This is the reconciliation path: when a callback is lost, the truth is
		whatever the provider says, not what the hotel assumed.
		"""

	@abstractmethod
	def refund(
		self, provider_reference: str, amount: float, idempotency_key: str, *, reason: str | None = None
	) -> PaymentResult:
		"""Refund all or part of a captured payment."""

	@abstractmethod
	def verify_callback(self, payload: dict, headers: dict, raw_body: bytes | None = None) -> dict:
		"""Authenticate an inbound callback and normalise it.

		Must raise if the signature does not verify. Returning an unverified
		payload would let anyone mark a folio as paid.

		`raw_body` is the exact bytes the provider sent. Providers that sign the
		body - Stripe among them - must verify against these bytes, never
		against a re-encoded `payload`: key order and separators would differ
		and every signature would fail. It is optional only so a provider that
		signs a field subset need not require it.

		Returns a dict with at least `provider_reference`, `status` and
		`amount`.
		"""

	# -- shared plumbing -----------------------------------------------

	def get_secret(self, fieldname: str) -> str | None:
		"""Read an encrypted credential off the configuration row."""
		return self.config.get_password(fieldname, raise_exception=False)

	def log_request(
		self,
		*,
		direction: str,
		endpoint: str | None,
		method: str | None,
		request_payload=None,
		response_payload=None,
		status_code: int | None = None,
		is_success: bool = True,
		error_message: str | None = None,
		idempotency_key: str | None = None,
		reference_doctype: str | None = None,
		reference_name: str | None = None,
		duration_ms: int | None = None,
	):
		"""Record a call in the integration log.

		Inserted with `ignore_permissions` because the log records what the
		system did, not what the user is allowed to write.
		"""
		import json

		frappe.get_doc(
			{
				"doctype": INTEGRATION_LOG,
				"property": self.property,
				"integration_type": "Payment",
				"provider": self.name or self.config.provider,
				"direction": direction,
				"endpoint": endpoint,
				"method": method,
				"idempotency_key": idempotency_key,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"request_payload": json.dumps(request_payload, default=str) if request_payload else None,
				"response_payload": json.dumps(response_payload, default=str) if response_payload else None,
				"status_code": status_code,
				"is_success": 1 if is_success else 0,
				"error_message": error_message,
				"duration_ms": duration_ms,
				"requested_on": now_datetime(),
			}
		).insert(ignore_permissions=True)
