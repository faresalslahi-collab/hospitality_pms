"""Stripe payment provider adapter.

Stripe is the fallback payment provider (HPMS-DEC-024), used through the
PaymentIntents API. The base URL, bearer-auth scheme, idempotency-key header
and the Stripe-Signature webhook format below match Stripe's public API
reference (https://stripe.com/docs/api) as of the time of writing and are
stable, long-standing parts of Stripe's API - but exact field names on
response objects should still be re-checked against current docs before
go-live, since Stripe evolves its object shapes over time.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import requests

import frappe
from frappe import _
from frappe.utils.number_format import NUMBER_FORMAT_MAP, NumberFormat

from hospitality_pms.integrations.payments.base import PaymentProvider, PaymentResult
from hospitality_pms.services.exceptions import IntegrationError

#: Stripe serves both test-mode and live-mode traffic from the same host; the
#: secret key used (test vs. live) determines the mode, not the URL. VERIFY
#: against https://stripe.com/docs/api before go-live in case this changes.
STRIPE_DEFAULT_BASE_URLS = {
	"Sandbox": "https://api.stripe.com/v1",
	"Production": "https://api.stripe.com/v1",
}

STRIPE_TIMEOUT_SECONDS = 30

#: Stripe recommends rejecting webhooks whose timestamp is older than this,
#: to stop a captured request being replayed later (Stripe's own guidance).
STRIPE_WEBHOOK_TOLERANCE_SECONDS = 300

#: PaymentIntent.status -> our vocabulary. "requires_payment_method" and
#: "requires_confirmation" are pre-checkout states (nothing has happened
#: yet), so they map to "Initiated" rather than "Pending".
STRIPE_STATUS_MAP = {
	"requires_payment_method": "Initiated",
	"requires_confirmation": "Initiated",
	"requires_action": "Pending",
	"processing": "Pending",
	"requires_capture": "Authorised",
	"succeeded": "Captured",
	"canceled": "Cancelled",
}

STRIPE_FAILURE_STATUSES = {"Failed", "Cancelled"}

#: Fallback used when a currency is not found in the Currency doctype. Two
#: decimals is correct for the large majority of currencies Stripe supports.
_DEFAULT_NUMBER_FORMAT = "#,###.##"


def _currency_precision(currency: str | None) -> int:
	"""Decimal places for a currency, read from the Currency master.

	Stripe's minor unit is not always "amount * 100": zero-decimal
	currencies (e.g. JPY, KRW) have no minor unit at all, and a few others
	use three decimals. Rather than hard-coding Stripe's zero-decimal list,
	this reads the precision Frappe already has configured for the
	currency (its `number_format`) and derives the multiplier from that -
	one source of truth instead of two lists that can drift apart.
	"""
	if not currency:
		return 2
	number_format = frappe.get_cached_value("Currency", currency, "number_format") or _DEFAULT_NUMBER_FORMAT
	if number_format not in NUMBER_FORMAT_MAP:
		number_format = _DEFAULT_NUMBER_FORMAT
	return NumberFormat.from_string(number_format).precision


def _to_minor_units(amount: float, currency: str | None) -> int:
	precision = _currency_precision(currency)
	return int(round(amount * (10**precision)))


def _to_major_units(minor_amount: int | float | None, currency: str | None) -> float:
	precision = _currency_precision(currency)
	return round((minor_amount or 0) / (10**precision), precision)


def _translate_status(raw_status: str | None) -> str:
	if not raw_status:
		return "Pending"
	return STRIPE_STATUS_MAP.get(raw_status, "Pending")


class StripeAdapter(PaymentProvider):
	"""PaymentIntents-based adapter for Stripe."""

	name = "Stripe"

	# -- plumbing --------------------------------------------------------

	def _base_url(self) -> str:
		configured = getattr(self.config, "api_base_url", None)
		if configured:
			return configured.rstrip("/")
		return STRIPE_DEFAULT_BASE_URLS.get(self.config.environment, STRIPE_DEFAULT_BASE_URLS["Production"])

	def _call(
		self,
		method: str,
		path: str,
		*,
		data: dict | None = None,
		idempotency_key: str | None = None,
	) -> dict:
		"""Make one Stripe API call, logging and translating errors.

		Stripe's API takes form-encoded bodies (not JSON) on every endpoint
		used here, so `data` is passed as form fields, matching Stripe's own
		client libraries.
		"""
		url = f"{self._base_url()}/{path.lstrip('/')}"
		api_secret = self.get_secret("api_secret")
		headers = {"Authorization": f"Bearer {api_secret or ''}"}
		if idempotency_key and method.upper() == "POST":
			headers["Idempotency-Key"] = idempotency_key

		started = time.monotonic()
		status_code: int | None = None
		response_body = None
		error_message: str | None = None

		try:
			response = requests.request(
				method, url, headers=headers, data=data, timeout=STRIPE_TIMEOUT_SECONDS
			)
			status_code = response.status_code
			response.raise_for_status()
			response_body = response.json()
		except (requests.RequestException, ValueError) as exc:
			error_message = str(exc)
			duration_ms = int((time.monotonic() - started) * 1000)
			self.log_request(
				direction="Outbound",
				endpoint=url,
				method=method,
				request_payload=data,
				response_payload=response_body,
				status_code=status_code,
				is_success=False,
				error_message=error_message,
				idempotency_key=idempotency_key,
				duration_ms=duration_ms,
			)
			raise IntegrationError(
				_("Could not reach Stripe ({0}): {1}").format(path, error_message)
			) from exc

		duration_ms = int((time.monotonic() - started) * 1000)
		self.log_request(
			direction="Outbound",
			endpoint=url,
			method=method,
			request_payload=data,
			response_payload=response_body,
			status_code=status_code,
			is_success=True,
			idempotency_key=idempotency_key,
			duration_ms=duration_ms,
		)
		return response_body

	@staticmethod
	def _get_header(headers: dict, name: str) -> str | None:
		lowered = {str(key).lower(): value for key, value in (headers or {}).items()}
		return lowered.get(name.lower())

	# -- interface ---------------------------------------------------------

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
		data = {
			"amount": _to_minor_units(amount, currency),
			"currency": currency.lower(),
			"payment_method_types[]": "card",
		}
		if description:
			data["description"] = description
		if reference:
			data["metadata[reference]"] = reference
		for key, value in (metadata or {}).items():
			data[f"metadata[{key}]"] = value

		body = self._call("POST", "payment_intents", data=data, idempotency_key=idempotency_key)
		raw_status = body.get("status")
		status = _translate_status(raw_status)

		return PaymentResult(
			success=status not in STRIPE_FAILURE_STATUSES,
			status=status,
			provider_reference=body.get("id"),
			amount=amount,
			# PaymentIntents is a client-confirmed flow, not hosted checkout,
			# so there is no redirect URL - the client_secret the frontend
			# needs to confirm the payment travels in `raw` instead.
			payment_url=None,
			provider_status=raw_status,
			raw=body,
		)

	def get_status(self, provider_reference: str) -> PaymentResult:
		body = self._call("GET", f"payment_intents/{provider_reference}")
		raw_status = body.get("status")
		status = _translate_status(raw_status)

		return PaymentResult(
			success=status not in STRIPE_FAILURE_STATUSES,
			status=status,
			provider_reference=body.get("id", provider_reference),
			amount=_to_major_units(body.get("amount"), body.get("currency")),
			provider_status=raw_status,
			failure_reason=(body.get("last_payment_error") or {}).get("message")
			if status in STRIPE_FAILURE_STATUSES
			else None,
			raw=body,
		)

	def refund(
		self, provider_reference: str, amount: float, idempotency_key: str, *, reason: str | None = None
	) -> PaymentResult:
		# Fetch the PaymentIntent first: refunds are expressed in minor units
		# and we need the intent's currency to convert correctly, plus its
		# total amount to tell a full refund from a partial one.
		intent = self._call("GET", f"payment_intents/{provider_reference}")
		currency = intent.get("currency")
		total_minor = intent.get("amount", 0) or 0
		refund_minor = _to_minor_units(amount, currency)

		data = {"payment_intent": provider_reference, "amount": refund_minor}
		if reason:
			# Stripe's `reason` field is a closed enum (duplicate / fraudulent /
			# requested_by_customer); free-text reasons go into metadata instead
			# of being forced into that enum.
			data["metadata[reason]"] = reason

		body = self._call("POST", "refunds", data=data, idempotency_key=idempotency_key)
		raw_status = body.get("status")

		if raw_status == "failed":
			status = "Failed"
		else:
			status = "Refunded" if refund_minor >= total_minor else "Partially Refunded"

		return PaymentResult(
			success=status != "Failed",
			status=status,
			provider_reference=body.get("id", provider_reference),
			amount=amount,
			provider_status=raw_status,
			failure_reason=body.get("failure_reason") if status == "Failed" else None,
			raw=body,
		)

	def verify_callback(self, payload: dict, headers: dict, raw_body: bytes | None = None) -> dict:
		secret = self.get_secret("webhook_secret")
		signature_header = self._get_header(headers, "Stripe-Signature")
		started = time.monotonic()

		if not secret or not signature_header:
			self.log_request(
				direction="Inbound",
				endpoint="webhook",
				method="POST",
				request_payload=payload,
				is_success=False,
				error_message="Missing webhook secret or Stripe-Signature header",
				duration_ms=int((time.monotonic() - started) * 1000),
			)
			raise IntegrationError(_("Stripe callback is missing its signature."))

		parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
		timestamp = parts.get("t")
		provided_signature = parts.get("v1")

		if not timestamp or not provided_signature:
			self.log_request(
				direction="Inbound",
				endpoint="webhook",
				method="POST",
				request_payload=payload,
				is_success=False,
				error_message="Malformed Stripe-Signature header",
				duration_ms=int((time.monotonic() - started) * 1000),
			)
			raise IntegrationError(_("Stripe callback signature header is malformed."))

		# Stripe signs the exact raw request bytes as `{timestamp}.{body}`, so
		# the raw body is the only thing that can be verified against. The API
		# layer captures it before Frappe parses the request and passes it in.
		#
		# Re-encoding the parsed dict is a fallback for callers that cannot
		# supply the raw bytes. It will fail for a genuine callback whenever
		# Stripe's key order or spacing differs from ours, so it exists to make
		# the failure loud rather than to be relied on.
		if raw_body:
			body = raw_body.decode("utf-8")
		else:
			frappe.log_error(
				title="Stripe webhook verified without raw body",
				message=(
					"verify_callback was called without raw_body. The signature is being "
					"checked against a re-encoded payload, which is not byte-identical to "
					"what Stripe signed and will reject valid callbacks."
				),
			)
			body = json.dumps(payload, separators=(",", ":"))

		signed_payload = f"{timestamp}.{body}".encode()
		expected_signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

		# hmac.compare_digest is constant-time; a plain `==` would return as
		# soon as it hits the first differing character, and that timing
		# difference is enough for an attacker to recover a valid signature
		# one byte at a time across repeated callback attempts.
		is_valid = hmac.compare_digest(expected_signature, provided_signature)

		is_fresh = True
		try:
			event_time = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
			now = datetime.now(timezone.utc)
			is_fresh = abs((now - event_time).total_seconds()) <= STRIPE_WEBHOOK_TOLERANCE_SECONDS
		except (TypeError, ValueError, OSError):
			is_fresh = False

		duration_ms = int((time.monotonic() - started) * 1000)
		self.log_request(
			direction="Inbound",
			endpoint="webhook",
			method="POST",
			request_payload=payload,
			is_success=is_valid and is_fresh,
			error_message=None
			if (is_valid and is_fresh)
			else ("Signature mismatch" if not is_valid else "Stale webhook timestamp"),
			duration_ms=duration_ms,
		)

		if not is_valid:
			raise IntegrationError(_("Stripe callback signature did not verify."))
		if not is_fresh:
			raise IntegrationError(_("Stripe callback timestamp is outside the allowed tolerance."))

		event_object = (payload.get("data") or {}).get("object") or {}
		raw_status = event_object.get("status")

		return {
			"provider_reference": event_object.get("id"),
			"status": _translate_status(raw_status),
			"amount": _to_major_units(event_object.get("amount"), event_object.get("currency")),
			"provider_status": raw_status,
			"event_type": payload.get("type"),
			"raw": payload,
		}
