"""Fatora payment provider adapter.

Fatora (fatora.io) is a Qatar-based hosted-checkout gateway and is the primary
payment provider for this app (HPMS-DEC-024). The endpoint paths, request
shape and status vocabulary below are the best available reading of Fatora's
published API documentation at the time of writing. They are NOT verified
against a live sandbox and MUST be checked against the current Fatora API
reference before this adapter is used against real traffic.
"""

import hashlib
import hmac
import json
import time

import requests
from frappe import _

from hospitality_pms.integrations.payments.base import PaymentProvider, PaymentResult
from hospitality_pms.services.exceptions import IntegrationAmbiguousError, IntegrationError

#: Published Fatora API host. Fatora documents a single host for both test and
#: live API keys (the key itself determines the mode), so sandbox and
#: production default to the same value here. VERIFY against
#: https://docs.fatora.io before go-live - if Fatora introduces a distinct
#: sandbox host this constant must be split.
FATORA_DEFAULT_BASE_URLS = {
	"Sandbox": "https://api.fatora.io/v1",
	"Production": "https://api.fatora.io/v1",
}

FATORA_TIMEOUT_SECONDS = 30

#: Fatora's own status vocabulary translated to the Hospitality Payment
#: Transaction vocabulary. Keys are upper-cased before lookup so we are
#: tolerant of casing differences between endpoints.
FATORA_STATUS_MAP = {
	"CREATED": "Initiated",
	"INITIATED": "Initiated",
	"PENDING": "Pending",
	"PROCESSING": "Pending",
	"AUTHORIZED": "Authorised",
	"AUTHORISED": "Authorised",
	"SUCCESS": "Captured",
	"SUCCESSFUL": "Captured",
	"PAID": "Captured",
	"CAPTURED": "Captured",
	"FAILED": "Failed",
	"DECLINED": "Failed",
	"ERROR": "Failed",
	"REJECTED": "Failed",
	"CANCELLED": "Cancelled",
	"CANCELED": "Cancelled",
	"EXPIRED": "Cancelled",
	"REFUNDED": "Refunded",
	"PARTIALLY_REFUNDED": "Partially Refunded",
	"PARTIAL_REFUND": "Partially Refunded",
}

#: Statuses that represent an unsuccessful outcome for the operation that
#: reported them (as opposed to "successfully queried, payment still open").
FATORA_FAILURE_STATUSES = {"Failed", "Cancelled"}


def _translate_status(raw_status: str | None) -> str:
	"""Map a Fatora status string to our vocabulary.

	An unrecognised status is treated as still-open ("Pending") rather than
	guessed as success or failure - an unknown word from the provider is not
	licence to assume money moved either way. Reconciliation via
	`get_status` is expected to resolve it once Fatora's vocabulary is
	confirmed.
	"""
	if not raw_status:
		return "Pending"
	return FATORA_STATUS_MAP.get(raw_status.upper(), "Pending")


class FatoraAdapter(PaymentProvider):
	"""Hosted-checkout adapter for Fatora."""

	name = "Fatora"

	# -- plumbing --------------------------------------------------------

	def _base_url(self) -> str:
		configured = getattr(self.config, "api_base_url", None)
		if configured:
			return configured.rstrip("/")
		return FATORA_DEFAULT_BASE_URLS.get(self.config.environment, FATORA_DEFAULT_BASE_URLS["Production"])

	def _call(
		self,
		method: str,
		path: str,
		*,
		json_body: dict | None = None,
		idempotency_key: str | None = None,
	) -> dict:
		"""Make one Fatora API call, logging and translating errors.

		Every caller in this adapter goes through here so the URL building,
		auth header, timeout and logging happen exactly once.
		"""
		url = f"{self._base_url()}/{path.lstrip('/')}"
		headers = {
			"api_key": self.get_secret("api_key") or "",
			"Content-Type": "application/json",
		}
		if idempotency_key:
			headers["Idempotency-Key"] = idempotency_key

		started = time.monotonic()
		status_code: int | None = None
		response_body = None
		error_message: str | None = None

		try:
			response = requests.request(
				method, url, headers=headers, json=json_body, timeout=FATORA_TIMEOUT_SECONDS
			)
			status_code = response.status_code
			response.raise_for_status()
			response_body = response.json()
		except (requests.Timeout, requests.ConnectionError) as exc:
			# The request left and nothing came back, so the provider may well
			# have acted on it. Reported as ambiguous rather than as a refusal,
			# so a refund whose reply was lost is reconciled instead of retried.
			error_message = str(exc)
			self.log_request(
				direction="Outbound",
				endpoint=url,
				method=method,
				request_payload=json_body,
				response_payload=None,
				status_code=None,
				is_success=False,
				error_message=error_message,
				idempotency_key=idempotency_key,
				duration_ms=int((time.monotonic() - started) * 1000),
			)
			raise IntegrationAmbiguousError(
				_("No reply from Fatora for {0}; the outcome is unknown: {1}").format(path, error_message)
			) from exc
		except (requests.RequestException, ValueError) as exc:
			error_message = str(exc)
			duration_ms = int((time.monotonic() - started) * 1000)
			self.log_request(
				direction="Outbound",
				endpoint=url,
				method=method,
				request_payload=json_body,
				response_payload=response_body,
				status_code=status_code,
				is_success=False,
				error_message=error_message,
				idempotency_key=idempotency_key,
				duration_ms=duration_ms,
			)
			raise IntegrationError(
				_("Could not reach Fatora ({0}): {1}").format(path, error_message)
			) from exc

		duration_ms = int((time.monotonic() - started) * 1000)
		self.log_request(
			direction="Outbound",
			endpoint=url,
			method=method,
			request_payload=json_body,
			response_payload=response_body,
			status_code=status_code,
			is_success=True,
			idempotency_key=idempotency_key,
			duration_ms=duration_ms,
		)
		return response_body

	@staticmethod
	def _get_header(headers: dict, name: str) -> str | None:
		"""Case-insensitive header lookup; callback frameworks vary in casing."""
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
		payload = {
			"amount": amount,
			"currency": currency,
			"order_id": reference or idempotency_key,
			"note": description,
			"success_url": return_url,
			"failure_url": return_url,
			"idempotency_key": idempotency_key,
			"metadata": metadata or {},
		}
		body = self._call("POST", "payments/checkout", json_body=payload, idempotency_key=idempotency_key)
		result = body.get("result") or body
		raw_status = result.get("status") or body.get("status")
		status = _translate_status(raw_status)

		if status in FATORA_FAILURE_STATUSES:
			return PaymentResult(
				success=False,
				status=status,
				provider_reference=result.get("transaction_id") or result.get("order_id"),
				amount=amount,
				provider_status=raw_status,
				failure_reason=result.get("message") or body.get("message"),
				raw=body,
			)

		return PaymentResult(
			success=True,
			status="Pending",
			provider_reference=result.get("transaction_id") or result.get("order_id"),
			amount=amount,
			payment_url=result.get("checkout_url") or result.get("payment_url"),
			provider_status=raw_status,
			raw=body,
		)

	def get_status(self, provider_reference: str) -> PaymentResult:
		body = self._call("GET", f"payments/status/{provider_reference}")
		result = body.get("result") or body
		raw_status = result.get("status") or body.get("status")
		status = _translate_status(raw_status)

		return PaymentResult(
			success=status not in FATORA_FAILURE_STATUSES,
			status=status,
			provider_reference=result.get("transaction_id", provider_reference),
			amount=result.get("amount", 0.0) or 0.0,
			provider_status=raw_status,
			failure_reason=result.get("message") if status in FATORA_FAILURE_STATUSES else None,
			raw=body,
		)

	def refund(
		self, provider_reference: str, amount: float, idempotency_key: str, *, reason: str | None = None
	) -> PaymentResult:
		payload = {
			"transaction_id": provider_reference,
			"amount": amount,
			"reason": reason,
			"idempotency_key": idempotency_key,
		}
		body = self._call("POST", "payments/refund", json_body=payload, idempotency_key=idempotency_key)
		result = body.get("result") or body
		raw_status = result.get("status") or body.get("status")
		# Trust Fatora's own status word rather than inferring "it must be
		# refunded because we asked for a refund" - an async gateway can
		# legitimately hand back "PENDING"/"PROCESSING" here, and reporting
		# "Refunded" before the provider confirms it would let the folio
		# credit money that has not actually moved yet. get_status is the
		# path to resolve a refund that is still settling.
		status = _translate_status(raw_status)

		return PaymentResult(
			success=status not in FATORA_FAILURE_STATUSES,
			status=status,
			provider_reference=result.get("refund_id", provider_reference),
			amount=amount,
			provider_status=raw_status,
			failure_reason=result.get("message") if status in FATORA_FAILURE_STATUSES else None,
			raw=body,
		)

	def verify_callback(self, payload: dict, headers: dict, raw_body: bytes | None = None) -> dict:
		signature = self._get_header(headers, "X-Fatora-Signature")
		secret = self.get_secret("webhook_secret")
		started = time.monotonic()

		if not secret or not signature:
			self.log_request(
				direction="Inbound",
				endpoint="webhook",
				method="POST",
				request_payload=payload,
				is_success=False,
				error_message="Missing webhook secret or signature header",
				duration_ms=int((time.monotonic() - started) * 1000),
			)
			raise IntegrationError(_("Fatora callback is missing its signature."))

		# Signed over the canonical (sorted, compact) JSON encoding of the
		# payload; the exact canonicalisation Fatora uses on their side must
		# be confirmed against current docs before go-live.
		signed_body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
		expected = hmac.new(secret.encode(), signed_body, hashlib.sha256).hexdigest()

		# hmac.compare_digest runs in constant time regardless of where the
		# strings first differ. A plain `==` short-circuits on the first
		# mismatched byte, so its response time leaks how much of the guess
		# was correct - enough to brute-force the signature byte by byte.
		is_valid = hmac.compare_digest(expected, signature)
		duration_ms = int((time.monotonic() - started) * 1000)

		self.log_request(
			direction="Inbound",
			endpoint="webhook",
			method="POST",
			request_payload=payload,
			is_success=is_valid,
			error_message=None if is_valid else "Signature mismatch",
			duration_ms=duration_ms,
		)

		if not is_valid:
			raise IntegrationError(_("Fatora callback signature did not verify."))

		raw_status = payload.get("status")
		return {
			"provider_reference": payload.get("transaction_id") or payload.get("order_id"),
			"status": _translate_status(raw_status),
			"amount": payload.get("amount", 0.0) or 0.0,
			"provider_status": raw_status,
			"raw": payload,
		}
