"""Manual payment "provider" - cash and card-present payments taken at the desk.

There is no gateway here and nothing to verify against external
documentation: this adapter exists so that a property with no payment
gateway configured is a supported configuration, not a crash. Every
operation completes synchronously and is logged like any other provider so
the audit trail stays uniform regardless of which provider handled a
transaction.
"""

import time

from frappe import _

from hospitality_pms.integrations.payments.base import PaymentProvider, PaymentResult
from hospitality_pms.services.exceptions import IntegrationError


class ManualAdapter(PaymentProvider):
	"""No-gateway adapter for cash / card-present payments recorded at the desk."""

	name = "Manual"

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
		started = time.monotonic()
		provider_reference = reference or idempotency_key
		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={
				"amount": amount,
				"currency": currency,
				"reference": reference,
				"description": description,
				"metadata": metadata,
			},
			response_payload={"status": "Captured", "provider_reference": provider_reference},
			is_success=True,
			idempotency_key=idempotency_key,
			duration_ms=int((time.monotonic() - started) * 1000),
		)
		# Cash and card-present tender is taken and confirmed by the desk
		# clerk before this is ever called - there is no intermediate state.
		return PaymentResult(
			success=True,
			status="Captured",
			provider_reference=provider_reference,
			amount=amount,
			provider_status="Captured",
			raw={"currency": currency, "reference": reference},
		)

	def get_status(self, provider_reference: str) -> PaymentResult:
		started = time.monotonic()
		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={"provider_reference": provider_reference},
			response_payload={"status": "Captured"},
			is_success=True,
			duration_ms=int((time.monotonic() - started) * 1000),
		)
		# A manual payment has no external system to reconcile against - the
		# desk's record at capture time is the only truth there is.
		return PaymentResult(
			success=True,
			status="Captured",
			provider_reference=provider_reference,
			provider_status="Captured",
		)

	def refund(
		self, provider_reference: str, amount: float, idempotency_key: str, *, reason: str | None = None
	) -> PaymentResult:
		started = time.monotonic()
		self.log_request(
			direction="Outbound",
			endpoint=None,
			method=None,
			request_payload={
				"provider_reference": provider_reference,
				"amount": amount,
				"reason": reason,
			},
			response_payload={"status": "Refunded"},
			is_success=True,
			idempotency_key=idempotency_key,
			duration_ms=int((time.monotonic() - started) * 1000),
		)
		# The cash/card-present refund itself happens at the desk; this call
		# only records that it happened, same as initiate_payment does.
		return PaymentResult(
			success=True,
			status="Refunded",
			provider_reference=provider_reference,
			amount=amount,
			provider_status="Refunded",
		)

	def verify_callback(self, payload: dict, headers: dict, raw_body: bytes | None = None) -> dict:
		# A manual provider has no gateway to send one, so a callback arriving
		# here can only be a misconfiguration or an attempt to forge a
		# payment confirmation - either way it must not be trusted.
		started = time.monotonic()
		self.log_request(
			direction="Inbound",
			endpoint=None,
			method=None,
			request_payload=payload,
			is_success=False,
			error_message="Manual provider does not accept callbacks",
			duration_ms=int((time.monotonic() - started) * 1000),
		)
		raise IntegrationError(_("The manual payment provider does not accept callbacks."))
