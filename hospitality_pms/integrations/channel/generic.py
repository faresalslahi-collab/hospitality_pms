"""The channel-manager-neutral HTTP adapter.

HPMS-DEC-018: this is the only channel transport this build ships. It speaks
one normalised protocol - a JSON body of the shapes documented on
`ChannelAdapter` - over plain HTTPS with an API key/secret pair. It does not
know or care whether the connection is actually Booking.com, Expedia, Agoda
or a channel manager sitting in front of all three; that distinction lives on
`Booking Channel.provider` purely as a label until a vendor's real API
turns out to need its own request shapes, at which point it gets its own
adapter module here and its own entry in the registry - `ReservationService`
and the rest of the domain layer never change.
"""

import time

import requests
from frappe import _

from hospitality_pms.integrations.channel.base import ChannelAdapter, ChannelResult
from hospitality_pms.services.exceptions import IntegrationError

TIMEOUT_SECONDS = 30


class GenericChannelAdapter(ChannelAdapter):
	"""Neutral-protocol HTTP adapter used by every channel until a vendor needs its own."""

	name = "Generic Channel Manager"

	# -- plumbing --------------------------------------------------------

	def _base_url(self) -> str:
		if not self.config.api_base_url:
			raise IntegrationError(
				_("Channel {0} has no API base URL configured.").format(self.config.name)
			)
		return self.config.api_base_url.rstrip("/")

	def _call(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
		"""Make one call against the channel's normalised endpoint, logging and translating errors.

		Every capability below goes through here so the URL building, auth
		headers, timeout and logging happen exactly once.
		"""
		url = f"{self._base_url()}/{path.lstrip('/')}"
		headers = {
			"X-Api-Key": self.get_secret("api_key") or "",
			"X-Api-Secret": self.get_secret("api_secret") or "",
			"Content-Type": "application/json",
		}

		started = time.monotonic()
		status_code: int | None = None
		response_body = None
		error_message: str | None = None

		try:
			response = requests.request(method, url, headers=headers, json=json_body, timeout=TIMEOUT_SECONDS)
			status_code = response.status_code
			response.raise_for_status()
			response_body = response.json() if response.content else {}
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
				duration_ms=duration_ms,
			)
			raise IntegrationError(
				_("Could not reach channel {0} ({1}): {2}").format(self.config.name, path, error_message)
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
			duration_ms=duration_ms,
		)

		return response_body or {}

	def _hotel_path(self, suffix: str) -> str:
		hotel_code = self.config.hotel_code or self.config.name
		return f"/hotels/{hotel_code}/{suffix.lstrip('/')}"

	# -- capabilities ------------------------------------------------------

	def push_availability(self, from_date, to_date, rows: list[dict]) -> ChannelResult:
		body = self._call(
			"POST",
			self._hotel_path("availability"),
			json_body={"from_date": str(from_date), "to_date": str(to_date), "rows": rows},
		)
		return ChannelResult(success=True, status=body.get("status", "Success"), raw=body)

	def push_rates(self, from_date, to_date, rows: list[dict]) -> ChannelResult:
		body = self._call(
			"POST",
			self._hotel_path("rates"),
			json_body={"from_date": str(from_date), "to_date": str(to_date), "rows": rows},
		)
		return ChannelResult(success=True, status=body.get("status", "Success"), raw=body)

	def pull_reservations(self, since) -> list[dict]:
		body = self._call("GET", self._hotel_path("reservations"), json_body={"since": str(since)})
		return [self._normalise_reservation(row) for row in body.get("reservations", [])]

	def acknowledge_reservation(self, channel_reservation_id: str) -> ChannelResult:
		body = self._call(
			"POST", self._hotel_path(f"reservations/{channel_reservation_id}/ack")
		)
		return ChannelResult(success=True, status=body.get("status", "Acknowledged"), raw=body)

	def verify_callback(self, payload: dict, headers: dict, raw_body: bytes | None = None) -> dict:
		"""Verify an inbound webhook signed with the channel's shared secret.

		The neutral protocol signs the raw body with HMAC-SHA256 under the
		configured webhook secret; a channel that signs differently overrides
		this single method and nothing else.
		"""
		import hashlib
		import hmac

		secret = self.get_secret("webhook_secret")
		signature = headers.get("X-Channel-Signature") or headers.get("x-channel-signature")

		if not secret or not signature:
			raise IntegrationError(_("Channel {0} sent no verifiable signature.").format(self.config.name))

		body_bytes = raw_body if raw_body is not None else str(payload).encode("utf-8")
		expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

		if not hmac.compare_digest(expected, signature):
			self.log_request(
				direction="Inbound",
				endpoint=None,
				method="POST",
				request_payload=payload,
				is_success=False,
				error_message="Signature verification failed",
			)
			raise IntegrationError(_("Channel {0} callback failed signature verification.").format(self.config.name))

		self.log_request(direction="Inbound", endpoint=None, method="POST", request_payload=payload, is_success=True)

		return self._normalise_reservation(payload)

	def _normalise_reservation(self, row: dict) -> dict:
		"""Pass the neutral-protocol message through as-is.

		Because every channel already speaks this shape by contract (HPMS-DEC-018),
		there is no vendor translation to do here - that translation, if a real
		vendor ever needs one, belongs in that vendor's own adapter, which
		overrides this method rather than changing the shape everyone else relies on.
		"""
		return {
			"channel_reservation_id": row.get("channel_reservation_id"),
			"idempotency_key": row.get("message_id"),
			"message_type": row.get("message_type") or "New",
			"guest_name": row.get("guest_name"),
			"guest_email": row.get("guest_email"),
			"guest_phone": row.get("guest_phone"),
			"arrival_date": row.get("arrival_date"),
			"departure_date": row.get("departure_date"),
			"room_type_code": row.get("room_type_code"),
			"rate_code": row.get("rate_code"),
			"rooms": row.get("rooms") or 1,
			"adults": row.get("adults") or 2,
			"children": row.get("children") or 0,
			"total_amount": row.get("total_amount"),
			"currency": row.get("currency"),
			"commission_amount": row.get("commission_amount"),
			"raw": row,
		}
