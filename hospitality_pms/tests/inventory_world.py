"""A property with rooms to sell, for the Wave-5 inventory suites.

Deliberately lighter than the posting worlds: nothing here needs a chart of
accounts or a tax template, because inventory is about whether a room can be
sold on a night, not about what it costs in ERPNext.
"""

import frappe
from frappe.utils import add_days, getdate

from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.availability import get_availability
from hospitality_pms.services.property import BUSINESS_DATE_FLAG
from hospitality_pms.tests.fixtures import Fixtures

ROOM_RATE = 100.0


class InventoryWorld:
	"""A property, its rooms, and the means to fill them."""

	def __init__(self, tag: str, code: str, *, rooms: int = 1):
		self.tag = tag
		self.fixtures = Fixtures(tag)

		self.property = self.fixtures.property(code, require_id_at_check_in=0)
		self.room_type = self.fixtures.room_type(self.property, base_rate=ROOM_RATE)
		self.rooms = self.fixtures.rooms(self.property, self.room_type, count=rooms)
		self.rate_plan = self.fixtures.rate_plan(self.property, self.room_type, base_rate=ROOM_RATE)

		frappe.db.commit()

	# -- dates ------------------------------------------------------------

	@property
	def business_date(self):
		return getdate(frappe.db.get_value("Property", self.property, "business_date"))

	def day(self, offset: int):
		return add_days(self.business_date, offset)

	def set_business_date(self, value):
		"""Move the property's operating day, for arranging a test's premise.

		Through the same guarded flag the Night Audit uses: the Property
		controller refuses any other writer, and that control is one to work
		with rather than around.
		"""
		frappe.flags[BUSINESS_DATE_FLAG] = True
		try:
			frappe.db.set_value("Property", self.property, "business_date", getdate(value))
		finally:
			frappe.flags[BUSINESS_DATE_FLAG] = False

		frappe.db.commit()

	# -- bookings ---------------------------------------------------------

	def reservation(self, *, nights: int = 2, rooms: int = 1, arrival=None, guest=None) -> str:
		return self.fixtures.reservation(
			self.property,
			self.room_type,
			guest or self.fixtures.guest("Inventory"),
			rate_plan=self.rate_plan,
			arrival=arrival or self.business_date,
			nights=nights,
			rooms=rooms,
		)

	def reservation_with_lines(self, specs: list[dict], *, deposit: float = 0, guest=None) -> str:
		"""A booking whose rooms differ - different lengths, so different values."""
		guest = guest or self.fixtures.guest("Multi")
		arrival = self.business_date

		doc = frappe.get_doc(
			{
				"doctype": "Reservation",
				"property": self.property,
				"reservation_status": "Draft",
				"reservation_type": "Individual",
				"guest": guest,
				"arrival_date": arrival,
				"departure_date": add_days(arrival, max(spec.get("nights", 2) for spec in specs)),
				"rate_plan": self.rate_plan,
				"deposit_received": deposit,
				"rooms": [
					{
						"room_type": spec.get("room_type", self.room_type),
						"rooms": spec.get("rooms", 1),
						"adults": 1,
						"arrival_date": arrival,
						"departure_date": add_days(arrival, spec.get("nights", 2)),
					}
					for spec in specs
				],
			}
		).insert(ignore_permissions=True)

		self.fixtures.track_fresh("Reservation", doc.name, {"Reservation Log": "reservation"})
		frappe.db.commit()

		return doc.name

	def set_deposit(self, reservation: str, amount: float):
		frappe.db.set_value("Reservation", reservation, "deposit_received", amount, update_modified=False)
		frappe.db.commit()

	def confirmed(self, **kwargs) -> str:
		name = self.reservation(**kwargs)
		reservation_service.confirm(name)
		frappe.db.commit()

		return name

	def lines(self, reservation: str) -> list[dict]:
		return frappe.get_all(
			"Reservation Room",
			filters={"parent": reservation},
			fields=[
				"name",
				"room_type",
				"rooms",
				"arrival_date",
				"departure_date",
				"assigned_room",
				"room_rate",
				"total_amount",
				"adults",
			],
			order_by="idx asc",
		)

	def check_in(self, reservation: str, *, line: str | None = None, room: str | None = None) -> dict:
		"""Check one room line in. Defaults to the first line and first free room."""
		lines = self.lines(reservation)
		line = line or lines[0]["name"]

		if not room:
			taken = {
				row["assigned_room"] for row in self.lines(reservation) if row["assigned_room"]
			}
			room = next(name for name in self.rooms if name not in taken)

		result = stay_service.check_in(reservation, line, room)
		frappe.db.commit()

		return result

	# -- what the engine says ---------------------------------------------

	def sold(self, start_offset: int, end_offset: int) -> int:
		"""The highest sold count across the nights in the interval."""
		availability = get_availability(
			self.property, self.day(start_offset), self.day(end_offset), self.room_type
		)
		bucket = availability["room_types"][self.room_type]

		return max(int(figures["sold"]) for figures in bucket["by_night"].values())

	def available(self, start_offset: int, end_offset: int) -> int:
		"""The lowest availability across the nights in the interval."""
		availability = get_availability(
			self.property, self.day(start_offset), self.day(end_offset), self.room_type
		)

		return int(availability["room_types"][self.room_type]["min_available"])

	def teardown(self):
		self.fixtures.teardown()
