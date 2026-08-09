"""Channel reservation import and inventory push, independent of any OTA.

Duplicate protection, twice
----------------------------
A channel message is written to `Channel Reservation` under its
own idempotency key *before* anything else happens (SAS 3.4). A retried or
re-delivered message finds that row already there and stops - it is marked a
duplicate and nothing downstream runs again. If it gets past that point, the
`Reservation` it produces carries `external_reference` set to the
channel's own reservation id, so `ReservationService`'s own duplicate check
(`find_by_external_reference`, enforced in `Reservation.validate`) is a
second, independent guard against the same channel booking landing twice -
belt and braces, because the two checks protect against different failure
modes: a replayed message, and two different messages somehow describing the
same booking.

Modify is cancel-and-rebook
----------------------------
`Reservation` refuses to change `arrival_date`, `departure_date`,
`property` or `guest` once a reservation is holding inventory
(`_guard_holding_immutability`) - the only place those are safely changed is
`ReservationService.confirm`, which locks the room type and re-checks
availability first. Editing a confirmed reservation's dates in place to
reflect a channel modify would bypass that lock entirely. Cancelling the old
booking and creating a fresh one for the new dates reuses the same safe,
locked path a brand-new booking uses; there is no shortcut that is both fast
and correct here.
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from hospitality_pms.integrations.channel import get_adapter
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services.availability import get_availability
from hospitality_pms.services.exceptions import ConfigurationError, throw
from hospitality_pms.services.rates import get_rate_breakdown

CHANNEL_DOCTYPE = "Booking Channel"
CHANNEL_RESERVATION_DOCTYPE = "Channel Reservation"
SYNC_LOG_DOCTYPE = "Channel Sync Log"
FAILURE_QUEUE = "PMS Integration Failure Queue"
GUEST_DOCTYPE = "Guest"

#: How far ahead `sync_all` refreshes availability and rates when the
#: scheduler calls it with no explicit range. Channels are pushed a rolling
#: window rather than the whole rate horizon so a routine sync stays cheap;
#: a wider one-off push is still available by calling `push_availability` /
#: `push_rates` directly with a longer range.
DEFAULT_SYNC_HORIZON_DAYS = 90


# ---------------------------------------------------------------------------
# Reservation import
# ---------------------------------------------------------------------------


def import_reservation(property_name: str, channel: str, payload: dict) -> dict:
	"""Import one reservation message from a channel.

	`payload` is whatever the channel adapter normalised - `pull_reservations`
	or `verify_callback` - shaped like a `Channel Reservation` row.
	The row is written first, under its own idempotency key, before any
	interpretation of the message happens; see the module docstring.
	"""
	idempotency_key = payload.get("idempotency_key") or "{0}:{1}:{2}".format(
		channel, payload.get("channel_reservation_id"), payload.get("message_type") or "New"
	)

	existing = frappe.db.get_value(
		CHANNEL_RESERVATION_DOCTYPE,
		{"idempotency_key": idempotency_key},
		["name", "processing_status", "reservation"],
		as_dict=True,
	)

	if existing:
		return {**existing, "duplicate": True}

	channel_doc = frappe.get_cached_doc(CHANNEL_DOCTYPE, channel)

	row = frappe.get_doc(
		{
			"doctype": CHANNEL_RESERVATION_DOCTYPE,
			"property": property_name,
			"channel": channel,
			"channel_reservation_id": payload.get("channel_reservation_id"),
			"idempotency_key": idempotency_key,
			"message_type": payload.get("message_type") or "New",
			"processing_status": "Received",
			"guest_name": payload.get("guest_name"),
			"guest_email": payload.get("guest_email"),
			"guest_phone": payload.get("guest_phone"),
			"arrival_date": payload.get("arrival_date"),
			"departure_date": payload.get("departure_date"),
			"room_type_code": payload.get("room_type_code"),
			"rate_code": payload.get("rate_code"),
			"rooms": payload.get("rooms") or 1,
			"adults": payload.get("adults") or 2,
			"children": payload.get("children") or 0,
			"total_amount": payload.get("total_amount"),
			"currency": payload.get("currency"),
			"commission_amount": payload.get("commission_amount"),
			"received_on": now_datetime(),
			"raw_payload": json.dumps(payload, default=str),
		}
	).insert(ignore_permissions=True)

	try:
		if row.message_type == "Cancel":
			reservation = handle_cancel(row, channel_doc)
		elif row.message_type == "Modify":
			reservation = handle_modify(row, channel_doc)
		else:
			reservation = _book_new(row, channel_doc)
	except Exception as exc:  # noqa: BLE001
		frappe.db.set_value(
			CHANNEL_RESERVATION_DOCTYPE,
			row.name,
			{"processing_status": "Failed", "error_message": str(exc)[:2000]},
			update_modified=True,
		)
		_queue_failure(property_name, channel, "import_reservation", idempotency_key, payload, str(exc))
		raise

	frappe.db.set_value(
		CHANNEL_RESERVATION_DOCTYPE,
		row.name,
		{"processing_status": "Processed", "processed_on": now_datetime(), "reservation": reservation},
		update_modified=True,
	)

	return {"name": row.name, "processing_status": "Processed", "reservation": reservation, "duplicate": False}


def _book_new(row, channel_doc) -> str:
	"""Map a channel reservation message onto a confirmed `Reservation`."""
	room_type = _resolve_room_type(channel_doc, row.room_type_code)
	rate_plan = _resolve_rate_plan(channel_doc, row.room_type_code) or channel_doc.default_rate_plan
	guest = _resolve_guest(row)

	reservation = frappe.get_doc(
		{
			"doctype": reservation_service.RESERVATION_DOCTYPE,
			"property": row.property,
			"reservation_status": reservation_service.DRAFT,
			"reservation_type": "OTA",
			"booking_source": channel_doc.channel_name,
			"channel": channel_doc.channel_code,
			# ReservationService's own duplicate check (find_by_external_reference,
			# enforced in Reservation.validate) keys off this field, so a
			# message that somehow slipped past the idempotency check above is
			# still caught here as a second, independent guard.
			"external_reference": row.channel_reservation_id,
			"guest": guest,
			"guest_email": row.guest_email,
			"guest_mobile": row.guest_phone,
			"arrival_date": row.arrival_date,
			"departure_date": row.departure_date,
			"rate_plan": rate_plan,
			"market_segment": channel_doc.default_market_segment,
			"rooms": [
				{
					"room_type": room_type,
					"rooms": row.rooms or 1,
					"arrival_date": row.arrival_date,
					"departure_date": row.departure_date,
					"rate_plan": rate_plan,
					"adults": row.adults or 2,
					"children": row.children or 0,
				}
			],
		}
	).insert(ignore_permissions=True)

	# Confirmed through the service so the room type is locked and availability
	# re-checked exactly as it is for a booking taken at the desk.
	reservation_service.confirm(
		reservation.name, reason=_("Channel booking from {0}").format(channel_doc.channel_name)
	)

	return reservation.name


def handle_modify(row, channel_doc) -> str:
	"""Cancel the existing booking for this channel reference and rebook fresh.

	See the module docstring for why this is cancel-and-rebook rather than an
	in-place date change.
	"""
	existing = reservation_service.find_by_external_reference(row.property, row.channel_reservation_id)

	if existing:
		reservation_service.cancel(
			existing, _("Modified by channel {0}; rebooking with new details").format(channel_doc.channel_name)
		)

	return _book_new(row, channel_doc)


def handle_cancel(row, channel_doc) -> str | None:
	"""Cancel the reservation this channel reference points to, if any."""
	existing = reservation_service.find_by_external_reference(row.property, row.channel_reservation_id)

	if not existing:
		# A cancel for a booking we never confirmed - nothing to undo.
		return None

	reservation_service.cancel(existing, _("Cancelled by channel {0}").format(channel_doc.channel_name))

	return existing


def _resolve_room_type(channel_doc, room_type_code: str | None) -> str:
	mapping = next(
		(m for m in channel_doc.room_mappings if m.is_active and m.channel_room_code == room_type_code), None
	)

	if not mapping:
		throw(
			_("Channel {0} has no active room mapping for code {1}.").format(channel_doc.name, room_type_code),
			exc=ConfigurationError,
		)

	return mapping.room_type


def _resolve_rate_plan(channel_doc, room_type_code: str | None) -> str | None:
	mapping = next(
		(m for m in channel_doc.room_mappings if m.is_active and m.channel_room_code == room_type_code), None
	)

	return mapping.rate_plan if mapping else None


def _resolve_guest(row) -> str:
	"""Find the guest by contact details, or create one from the channel message.

	Matches on email or mobile only. A name match would risk merging two
	unrelated guests who happen to share a common name, which is worse than a
	duplicate profile the front desk can merge later (see
	`services.guests.find_duplicates`, which scores a name-only match lowest
	for the same reason).
	"""
	guest = None

	if row.guest_email:
		guest = frappe.db.get_value(GUEST_DOCTYPE, {"email_id": row.guest_email}, "name")

	if not guest and row.guest_phone:
		guest = frappe.db.get_value(GUEST_DOCTYPE, {"mobile_no": row.guest_phone}, "name")

	if guest:
		return guest

	first_name, _sep, last_name = (row.guest_name or _("Guest")).partition(" ")

	new_guest = frappe.get_doc(
		{
			"doctype": GUEST_DOCTYPE,
			"first_name": first_name,
			"last_name": last_name or None,
			"guest_name": row.guest_name or _("Guest"),
			"email_id": row.guest_email,
			"mobile_no": row.guest_phone,
			"guest_type": "Individual",
			"source": "Channel",
		}
	).insert(ignore_permissions=True)

	return new_guest.name


# ---------------------------------------------------------------------------
# Outbound sync
# ---------------------------------------------------------------------------


def push_availability(property_name: str, channel: str, from_date, to_date) -> dict:
	"""Push per-night, per-room-type available counts to a channel."""
	channel_doc = frappe.get_cached_doc(CHANNEL_DOCTYPE, channel)

	if not channel_doc.push_availability:
		return {"skipped": True, "reason": _("Availability push is disabled for channel {0}.").format(channel)}

	rows = []

	for mapping in channel_doc.room_mappings:
		if not mapping.is_active:
			continue

		availability = get_availability(property_name, from_date, to_date, mapping.room_type)
		bucket = availability["room_types"].get(mapping.room_type)

		if not bucket:
			continue

		for night, figures in bucket["by_night"].items():
			rows.append(
				{"channel_room_code": mapping.channel_room_code, "date": night, "available": figures["available"]}
			)

	return _run_sync(
		channel_doc, "Availability", from_date, to_date, rows, lambda adapter: adapter.push_availability(from_date, to_date, rows)
	)


def push_rates(property_name: str, channel: str, from_date, to_date) -> dict:
	"""Push per-night, per-room-type rates to a channel."""
	channel_doc = frappe.get_cached_doc(CHANNEL_DOCTYPE, channel)

	if not channel_doc.push_rates:
		return {"skipped": True, "reason": _("Rate push is disabled for channel {0}.").format(channel)}

	rows = []

	for mapping in channel_doc.room_mappings:
		if not mapping.is_active:
			continue

		rate_plan = mapping.rate_plan or channel_doc.default_rate_plan
		if not rate_plan:
			continue

		breakdown = get_rate_breakdown(
			property_name, mapping.room_type, from_date, to_date, rate_plan=rate_plan, check_restrictions=False
		)

		for line in breakdown["lines"]:
			rows.append(
				{
					"channel_room_code": mapping.channel_room_code,
					"channel_rate_code": mapping.channel_rate_code,
					"date": line["rate_date"],
					"rate": line["net_rate"],
					"currency": breakdown["currency"],
				}
			)

	return _run_sync(
		channel_doc, "Rates", from_date, to_date, rows, lambda adapter: adapter.push_rates(from_date, to_date, rows)
	)


def _run_sync(channel_doc, sync_type: str, from_date, to_date, rows: list[dict], call) -> dict:
	"""Shared push/log/queue plumbing for `push_availability` and `push_rates`."""
	started = time.monotonic()
	adapter = get_adapter(channel_doc.name)

	try:
		result = call(adapter)
	except Exception as exc:  # noqa: BLE001
		_write_sync_log(
			channel_doc,
			sync_type,
			from_date,
			to_date,
			int((time.monotonic() - started) * 1000),
			sync_status="Failed",
			records_sent=0,
			records_failed=len(rows),
			request_payload={"rows": rows},
			error_message=str(exc),
		)
		_queue_failure(
			channel_doc.property,
			channel_doc.name,
			f"push_{sync_type.lower()}",
			f"{channel_doc.name}:{sync_type}:{from_date}:{to_date}",
			{"rows": rows},
			str(exc),
		)
		raise

	_write_sync_log(
		channel_doc,
		sync_type,
		from_date,
		to_date,
		int((time.monotonic() - started) * 1000),
		sync_status="Success" if result.success else "Failed",
		records_sent=len(rows) if result.success else 0,
		records_failed=0 if result.success else len(rows),
		request_payload={"rows": rows},
		response_payload=result.raw,
		error_message=None if result.success else result.failure_reason,
	)

	if result.success:
		field = "last_availability_push" if sync_type == "Availability" else "last_rate_push"
		frappe.db.set_value(CHANNEL_DOCTYPE, channel_doc.name, field, now_datetime(), update_modified=False)

	return {"records_sent": len(rows), "status": result.status}


def _write_sync_log(
	channel_doc,
	sync_type: str,
	from_date,
	to_date,
	duration_ms: int,
	*,
	sync_status: str,
	records_sent: int = 0,
	records_failed: int = 0,
	request_payload=None,
	response_payload=None,
	error_message: str | None = None,
):
	frappe.get_doc(
		{
			"doctype": SYNC_LOG_DOCTYPE,
			"property": channel_doc.property,
			"channel": channel_doc.name,
			"sync_type": sync_type,
			"sync_status": sync_status,
			"from_date": from_date,
			"to_date": to_date,
			"records_sent": records_sent,
			"records_failed": records_failed,
			"synced_on": now_datetime(),
			"duration_ms": duration_ms,
			"error_message": error_message,
			"request_payload": json.dumps(request_payload, default=str) if request_payload else None,
			"response_payload": json.dumps(response_payload, default=str) if response_payload else None,
		}
	).insert(ignore_permissions=True)


def sync_all(property_name: str) -> dict:
	"""Push availability and rates to every active channel. Scheduler entry point.

	One channel's failure is logged and queued (inside `push_availability` /
	`push_rates`) but does not stop the others - a scheduler job that aborts
	on the first bad channel would leave every channel after it stale.
	"""
	from_date = nowdate()
	to_date = add_days(from_date, DEFAULT_SYNC_HORIZON_DAYS)

	results: dict[str, list] = {"availability": [], "rates": [], "failed": []}

	channels = frappe.get_all(CHANNEL_DOCTYPE, filters={"property": property_name, "is_active": 1}, pluck="name")

	for channel in channels:
		channel_doc = frappe.get_cached_doc(CHANNEL_DOCTYPE, channel)

		if channel_doc.push_availability:
			try:
				results["availability"].append(
					{"channel": channel, **push_availability(property_name, channel, from_date, to_date)}
				)
			except Exception as exc:  # noqa: BLE001
				results["failed"].append({"channel": channel, "operation": "availability", "error": str(exc)})

		if channel_doc.push_rates:
			try:
				results["rates"].append(
					{"channel": channel, **push_rates(property_name, channel, from_date, to_date)}
				)
			except Exception as exc:  # noqa: BLE001
				results["failed"].append({"channel": channel, "operation": "rates", "error": str(exc)})

	return results


# ---------------------------------------------------------------------------
# Failure queue
# ---------------------------------------------------------------------------


def _queue_failure(property_name: str, provider: str, operation: str, idempotency_key: str, payload, error: str):
	frappe.get_doc(
		{
			"doctype": FAILURE_QUEUE,
			"property": property_name,
			"integration_type": "Channel",
			"provider": provider,
			"operation": operation,
			"idempotency_key": idempotency_key,
			"payload": json.dumps(payload, default=str),
			"queue_status": "Pending",
			"attempts": 0,
			"last_error": error[:2000],
			"next_attempt_on": add_to_date(now_datetime(), minutes=5),
		}
	).insert(ignore_permissions=True)
