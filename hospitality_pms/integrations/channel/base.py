"""The channel adapter interface.

Every channel-manager or OTA connection implements this and nothing more. A
domain service that needs a new capability adds it here first, which is what
stops one channel's quirks leaking into `ReservationService` (SAD section 10).

Neutral protocol
-----------------
`Booking Channel.provider` records who the connection is with -
Booking.com, Expedia, Agoda - but the adapter contract itself is
channel-manager-neutral (HPMS-DEC-018): every adapter speaks one normalised
message shape in both directions. A vendor that needs its own field names or
authentication scheme translates them to and from this shape inside its own
adapter; nothing above this layer ever sees a vendor-specific key.

Rules that hold for every provider:

* An inbound reservation message (pulled or pushed to us) is normalised to a
  dict shaped like a `Channel Reservation` row - the domain
  service decides what a duplicate or a modify means, never the adapter.
* An adapter never writes a `Reservation` or touches availability. It
  only talks to the channel and reports what happened.
* Every call is logged, success or failure, through `log_request`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import frappe
from frappe.utils import now_datetime

INTEGRATION_LOG = "PMS Integration Log"


@dataclass
class ChannelResult:
	"""What a channel connection says happened to one outbound call."""

	success: bool
	status: str | None = None
	channel_reference: str | None = None
	failure_reason: str | None = None
	raw: dict = field(default_factory=dict)


class ChannelAdapter(ABC):
	"""Base class for a channel-manager / OTA adapter."""

	#: Adapter name as it appears in the integration log.
	name: str = ""

	def __init__(self, config):
		self.config = config
		self.property = config.property

	# -- capabilities --------------------------------------------------

	@abstractmethod
	def push_availability(self, from_date, to_date, rows: list[dict]) -> ChannelResult:
		"""Send per-night, per-room-type available counts to the channel."""

	@abstractmethod
	def push_rates(self, from_date, to_date, rows: list[dict]) -> ChannelResult:
		"""Send per-night, per-room-type rates to the channel."""

	@abstractmethod
	def pull_reservations(self, since) -> list[dict]:
		"""Fetch reservation messages received since `since`.

		Returns a list of dicts normalised to the `Booking Channel
		Reservation` shape (`channel_reservation_id`, `message_type`, guest and
		stay fields, `raw`), one per message. An empty list means nothing new,
		never a partial or best-effort read.
		"""

	@abstractmethod
	def acknowledge_reservation(self, channel_reservation_id: str) -> ChannelResult:
		"""Tell the channel a reservation message has been processed.

		Channels that require acknowledgement will keep re-sending a message
		until this succeeds, so it is the adapter's job to make that happen
		exactly once per message, not the domain service's.
		"""

	@abstractmethod
	def verify_callback(self, payload: dict, headers: dict, raw_body: bytes | None = None) -> dict:
		"""Authenticate an inbound webhook and normalise it to one reservation message.

		Must raise if the signature does not verify. Returning an unverified
		payload would let anyone push a fabricated booking into the property.

		`raw_body` is the exact bytes the channel sent, for adapters that sign
		the body rather than a field subset; optional so an adapter that does
		not need it is not forced to require it.
		"""

	# -- shared plumbing -----------------------------------------------

	def get_secret(self, fieldname: str) -> str | None:
		"""Read an encrypted credential off the channel configuration row."""
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
				"integration_type": "Channel",
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
