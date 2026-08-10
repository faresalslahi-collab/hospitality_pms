"""Local demo seed for the operational screens.

**Local development and UAT preparation only.** Nothing here is wired into
install, migrate, or the scheduler; it is run by hand:

    bench --site <site> execute hospitality_pms.demo.seed_dashboard_demo.seed
    bench --site <site> execute hospitality_pms.demo.seed_dashboard_demo.report
    bench --site <site> execute hospitality_pms.demo.seed_dashboard_demo.cleanup \\
        --kwargs "{'confirm': 'DELETE LOCAL DEMO DATA'}"

Every figure the dashboard shows is derived by the application from records
this script creates through the ordinary services — `reservations.confirm`,
`stays.check_in`, `folio.post_charge`, `night_audit.close` and the rest. The
seed never writes a computed field, never sets a status the transition table
forbids, and never puts a number anywhere the frontend reads directly. If a
metric cannot legitimately display, the seed leaves it empty and the report
says why.

Two consequences worth knowing before running it:

  * **The business date moves.** Occupancy, ADR and RevPAR are only
    authoritative once a Night Audit has closed, and closing a business date is
    the only thing that advances it. Producing a credible performance history
    therefore means running the audit for real, once per day of history, and
    the property ends up that many days further on. That is the system working
    as designed, not a side effect to be worked around.

  * **It is idempotent, not transactional.** A rerun reuses everything the
    manifest already knows about. A run interrupted half way leaves what it
    had already committed, and the next run continues from there.
"""

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from hospitality_pms.demo import data as fixture
from hospitality_pms.demo.manifest import MARKER, Manifest, marker
from hospitality_pms.services import checkout as checkout_service
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import guest_services as request_service
from hospitality_pms.services import housekeeping as housekeeping_service
from hospitality_pms.services import maintenance as maintenance_service
from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import rooms as room_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.property import get_business_date

RATE_PLAN = "BAR"

#: How the demo hotel should look once the seed has finished. The seed aims at
#: these and reports what it actually reached, because the arithmetic depends
#: on what was already on the site.
TARGET_IN_HOUSE = 20
TARGET_DEPARTURES_TODAY = 7
TARGET_ARRIVALS_TODAY = 10
TARGET_VACANT_DIRTY = 4
TARGET_RESERVED = 5

#: Arrivals per historical day, and the nights each of them stays. Written out
#: rather than drawn at random so two seeds of the same site agree, and so the
#: arithmetic that lands 14 guests in house on the day of the review is
#: readable: 16 arrive, 8 leave over the two following days, 6 more arrive.
HISTORY_PLAN = [
	# Day 0 fills the house: four one-nighters, four two-nighters and so on up
	# to a week, so that by the day under review some guests are leaving, some
	# are mid-stay, and the folios carry different amounts of accumulated
	# spend rather than all looking alike.
	[1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8],
	# day 1
	[2, 2, 4],
	# day 2
	[1, 3, 5],
]


def seed(
	property: str | None = None,
	history_days: int = 3,
	start_todays_audit: int = 1,
	force: int = 0,
) -> dict:
	"""Populate this site with a reviewable day of hotel operations.

	`history_days` closed Night Audits are run before the review day, because
	the performance card needs one closed audit to show anything, two to show a
	change, and a handful to draw a trend. Each one moves the business date on
	by a day.

	Seed keys for anything dated carry the business date they belong to. A
	rerun therefore continues the hotel from wherever the property now is,
	rather than deciding that yesterday's arrivals are today's and leaving the
	board empty.
	"""
	seeder = _Seeder(property_name=property, history_days=int(history_days))

	# A second run is not a repeat, it is a continuation: seed keys carry the
	# business date, so running again would build another `history_days` of
	# history and move the property on again. That is almost never what
	# somebody re-running a seed script wants, so it has to be asked for.
	previous = seeder.manifest.data.get("last_review_day")
	if previous and not int(force):
		return {
			"skipped": True,
			"reason": (
				f"This site already carries a demo seed for business date {previous} "
				f"({len(seeder.manifest.records)} records). Re-running would add another "
				f"{history_days} day(s) of history and move the business date again. "
				"Run cleanup first, or pass force=1 to continue from where the hotel now is."
			),
			"manifest": manifest_path(),
		}

	seeder.run(start_todays_audit=bool(int(start_todays_audit)))

	return seeder.summary()


def report(property: str | None = None) -> dict:
	"""What the dashboard would show right now, without changing anything."""
	from hospitality_pms.services import front_office as front_office_service

	property_name = _resolve_property(property)
	manifest = Manifest()

	dashboard = front_office_service.get_dashboard(property_name)
	arrivals = front_office_service.get_arrivals_board(property_name)
	departures = front_office_service.get_departures_board(property_name)

	sources: dict[str, int] = {}
	for row in arrivals["rows"]:
		key = row.get("booking_source") or "Not recorded"
		sources[key] = sources.get(key, 0) + 1

	result = {
		"property": property_name,
		"business_date": dashboard["business_date"],
		"rooms": dashboard["rooms"],
		"front_office": dashboard["front_office"],
		"revenue": dashboard["revenue"],
		"performance": dashboard["performance"],
		"workload": dashboard["workload"],
		"arrivals_rows": len(arrivals["rows"]),
		"departures_rows": len(departures["rows"]),
		"booking_sources": sources,
		"demo_records": {k: len(v) for k, v in manifest.by_doctype().items()},
	}

	print(frappe.as_json(result))

	return result


def cleanup(confirm: str = "", property: str | None = None) -> dict:
	"""Remove what this seed created, and only that.

	Deletion is doubly gated: a record must be named in the manifest *and*
	still carry the demo marker. Anything the manifest claims but that no
	longer looks like demo data is left alone and reported.

	**This is a partial clean, and it is meant to be.** Most of what a seeded
	hotel consists of cannot be deleted once it has been operated on: a guest
	who has stayed is linked from a stay, a room from a stay and a status log,
	a request from its own log, and reservations that have left Draft are
	retained for ten years by design (SAS section 8). The application refuses
	all of those, and this function reports the refusal rather than forcing it
	— a demo utility is not the place to defeat a retention rule.

	**To actually reset a local site, restore a backup taken before seeding.**
	That is the only complete undo, and it is one command:

	    bench --site <site> backup            # before you seed
	    bench --site <site> --force restore <that backup>

	What this function is good for is clearing the deletable remainder and
	releasing the seed keys, so a subsequent `seed()` starts clean.
	"""
	if confirm != "DELETE LOCAL DEMO DATA":
		frappe.throw(
			"Pass confirm='DELETE LOCAL DEMO DATA' to remove the seeded demo records."
		)

	manifest = Manifest()
	deleted: dict[str, int] = {}
	retained: list[str] = []
	skipped: list[str] = []

	# Children before parents: a room cannot go while a stay points at it.
	order = [
		"Guest Request",
		"Housekeeping Task",
		"Maintenance Ticket",
		"Room Block",
		"Reservation",
		"Hotel Room",
		"Guest",
		"Room Type",
		"Floor",
		"Zone",
		"Building",
	]

	entries = list(manifest.records.items())
	by_doctype: dict[str, list[tuple[str, str]]] = {}
	for key, entry in entries:
		by_doctype.setdefault(entry["doctype"], []).append((key, entry["name"]))

	for doctype in order + [d for d in by_doctype if d not in order]:
		for key, name in by_doctype.get(doctype, []):
			if not frappe.db.exists(doctype, name):
				manifest.records.pop(key, None)
				continue

			if not _carries_marker(doctype, name):
				skipped.append(f"{doctype} {name} (no demo marker)")
				continue

			try:
				frappe.delete_doc(doctype, name, force=False, ignore_permissions=True)
				deleted[doctype] = deleted.get(doctype, 0) + 1
				manifest.records.pop(key, None)
			except Exception as exc:  # noqa: BLE001
				retained.append(f"{doctype} {name}: {str(exc)[:160]}")

	manifest.data.pop("last_review_day", None)
	manifest.flush()
	frappe.db.commit()

	result = {"deleted": deleted, "retained_by_the_application": retained, "skipped": skipped}
	print(frappe.as_json(result))

	return result


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


class _Seeder:
	def __init__(self, property_name: str | None, history_days: int):
		self.property = _resolve_property(property_name)
		self.history_days = max(0, min(history_days, len(HISTORY_PLAN)))
		self.manifest = Manifest()
		self.currency = frappe.db.get_value("Property", self.property, "currency")
		self.notes: list[str] = []
		self.unavailable: list[str] = []
		self.room_types: dict[str, str] = {}
		self.rooms_by_number: dict[int, str] = {}
		self.building: str | None = None
		self.floor_names: dict[str, str] = {}
		self.zone_names: dict[str, str] = {}
		self.guests: list[str] = []
		self.audits_closed: list[str] = []

	# -- orchestration ---------------------------------------------------

	def run(self, *, start_todays_audit: bool):
		frappe.set_user("Administrator")

		self._ensure_room_types()
		self._ensure_rate_plan()
		self._ensure_locations()
		self._ensure_rooms()
		self._ensure_guests()
		self._commit("masters")

		for day in range(self.history_days):
			self._seed_history_day(day)
			self._commit(f"history day {day}")

		self._seed_today()
		self._commit("review day")

		self._seed_room_states()
		self._seed_maintenance()
		self._seed_housekeeping()
		self._seed_guest_requests()
		self._seed_future_reservations()
		self._commit("workload")

		if start_todays_audit:
			self._start_todays_audit()
			self._commit("night audit")

		self.manifest.data["last_review_day"] = str(getdate(get_business_date(self.property)))
		self.manifest.flush(self.property)
		frappe.db.commit()

	def _commit(self, phase: str):
		"""Commit between phases so an interrupted run keeps its progress."""
		self.manifest.flush(self.property)
		frappe.db.commit()
		print(f"  ... {phase} done")

	# -- masters ---------------------------------------------------------

	def _ensure_room_types(self):
		for spec in fixture.ROOM_TYPES:
			key = f"room_type:{spec['code']}"
			existing = frappe.db.exists("Room Type", spec["code"])

			if existing:
				self.room_types[spec["code"]] = spec["code"]
				# Pre-existing masters are never adopted into the manifest:
				# cleanup must not delete a room type the site had before.
				if self.manifest.get(key):
					self.manifest.note_reuse("Room Type", spec["code"])
				else:
					self.notes.append(f"Room Type {spec['code']} already existed and was left as it is.")
				continue

			doc = frappe.get_doc(
				{
					"doctype": "Room Type",
					"room_type_code": spec["code"],
					"room_type_name": spec["name"],
					"property": self.property,
					"is_active": 1,
					"display_order": spec["order"],
					"base_occupancy": spec["base_occupancy"],
					"max_occupancy": spec["max_occupancy"],
					"max_adults": spec["max_adults"],
					"max_children": spec["max_children"],
					"currency": self.currency,
					"base_rate": spec["rate"],
					"description": marker(key),
				}
			).insert(ignore_permissions=True)

			self.room_types[spec["code"]] = doc.name
			self.manifest.remember(key, "Room Type", doc.name)

	def _ensure_rate_plan(self):
		"""Give the rate plan a line for every demo room type.

		Without one, pricing a reservation for a new type throws — which is the
		right behaviour, and the reason the seed adds the rates rather than
		hard-coding a room rate onto the reservation.
		"""
		if not frappe.db.exists("Rate Plan", RATE_PLAN):
			self.unavailable.append(
				f"Rate Plan {RATE_PLAN} does not exist; reservations were priced by the "
				"controller's fallback."
			)
			return

		plan = frappe.get_doc("Rate Plan", RATE_PLAN)
		have = {row.room_type for row in plan.room_types}
		added = 0

		for spec in fixture.ROOM_TYPES:
			if spec["code"] in have or spec["code"] not in self.room_types:
				continue

			plan.append(
				"room_types",
				{
					"room_type": spec["code"],
					"base_rate": spec["rate"],
					"extra_adult_rate": round(spec["rate"] * 0.15, 2),
					"extra_child_rate": round(spec["rate"] * 0.08, 2),
					"currency": self.currency,
				},
			)
			added += 1

		if added:
			plan.save(ignore_permissions=True)
			self.notes.append(f"Added {added} room type rate line(s) to Rate Plan {RATE_PLAN}.")

	def _ensure_locations(self):
		"""Building, floors and zones, because Hotel Room links to all three.

		Each helper returns the document's *actual* name rather than the code
		it was asked for: these doctypes normalise their code on save, so the
		link value a room must store is not necessarily the string handed in.
		Assuming otherwise writes a link that points at nothing.
		"""
		self.building = self._ensure_building()

		for floor in fixture.FLOORS:
			self.floor_names[floor["floor"]] = self._ensure_floor(floor)
			self.zone_names[floor["zone"]] = self._ensure_zone(floor)

	def _ensure_building(self) -> str:
		existing = frappe.db.get_value("Building", {"property": self.property}, "name")
		if existing:
			return existing

		doc = frappe.get_doc(
			{
				"doctype": "Building",
				"building_code": fixture.BUILDING["code"],
				"building_name": fixture.BUILDING["name"],
				"property": self.property,
				"is_active": 1,
				"description": marker("building"),
			}
		).insert(ignore_permissions=True)

		return self.manifest.remember("building", "Building", doc.name)

	def _ensure_floor(self, floor: dict) -> str:
		# Matched on the level, which is the fact that cannot be spelled two
		# ways, rather than on the code, which can.
		existing = frappe.db.get_value(
			"Floor", {"property": self.property, "floor_level": floor["level"]}, "name"
		)
		if existing:
			return existing

		doc = frappe.get_doc(
			{
				"doctype": "Floor",
				"floor_code": floor["floor"],
				"floor_name": floor["floor"],
				"property": self.property,
				"building": self.building,
				"floor_level": floor["level"],
				"is_active": 1,
				"has_elevator_access": 1,
				"is_executive_floor": 1 if floor["level"] >= 4 else 0,
			}
		).insert(ignore_permissions=True)

		return self.manifest.remember(f"floor:{floor['level']}", "Floor", doc.name)

	def _ensure_zone(self, floor: dict) -> str:
		existing = frappe.db.get_value(
			"Zone", {"property": self.property, "zone_code": floor["zone"].upper()}, "name"
		)
		if existing:
			return existing

		doc = frappe.get_doc(
			{
				"doctype": "Zone",
				"zone_code": floor["zone"],
				"zone_name": f"Housekeeping {floor['zone']}",
				"property": self.property,
				"zone_purpose": "Housekeeping",
				"is_active": 1,
				"description": marker(f"zone:{floor['level']}"),
			}
		).insert(ignore_permissions=True)

		return self.manifest.remember(f"zone:{floor['level']}", "Zone", doc.name)

	def _ensure_rooms(self):
		for floor in fixture.FLOORS:
			for number in floor["numbers"]:
				code = f"{self.property}-{number}"
				type_code = fixture.ROOM_TYPE_BY_NUMBER[number]
				key = f"room:{number}"

				if frappe.db.exists("Hotel Room", code):
					self.rooms_by_number[number] = code

					# A room that predates the seed keeps its type, but the
					# floor is filled in when it is blank: the status board
					# groups on it, and a null floor is a data gap rather than
					# a decision anyone made.
					if not frappe.db.get_value("Hotel Room", code, "floor"):
						frappe.db.set_value(
							"Hotel Room", code, "floor", self.floor_names[floor["floor"]]
						)
						self.notes.append(f"Set floor on pre-existing room {code}.")

					if self.manifest.get(key):
						self.manifest.note_reuse("Hotel Room", code)
					continue

				doc = frappe.get_doc(
					{
						"doctype": "Hotel Room",
						"room_code": code,
						"room_number": str(number),
						"property": self.property,
						"room_type": self.room_types.get(type_code, type_code),
						"is_active": 1,
						"building": self.building,
						"floor": self.floor_names[floor["floor"]],
						"zone": self.zone_names[floor["zone"]],
						"view_type": fixture.VIEW_BY_FLOOR[floor["floor"]],
						"is_smoking": 0,
						"is_accessible": 1 if number % 100 == 1 else 0,
						"housekeeping_credits": 30,
						"notes": marker(key),
					}
				).insert(ignore_permissions=True)

				self.rooms_by_number[number] = doc.name
				self.manifest.remember(key, "Hotel Room", doc.name)

	def _ensure_guests(self):
		for index, (first, last, kind, nationality, language, vip) in enumerate(fixture.GUESTS):
			key = f"guest:{index:02d}"
			existing = self.manifest.get(key)

			if existing:
				self.guests.append(existing)
				self.manifest.note_reuse("Guest", existing)
				continue

			guest_type, _reservation_type = fixture.KIND_TO_TYPES[kind]

			doc = frappe.get_doc(
				{
					"doctype": "Guest",
					"first_name": first,
					"last_name": last,
					"gender": _link_or_none("Gender", "Male" if index % 2 == 0 else "Female"),
					"nationality": _link_or_none("Country", nationality),
					"country": _link_or_none("Country", nationality),
					"preferred_language": _link_or_none("Language", language),
					"guest_type": guest_type,
					"vip_status": vip,
					# Documentation ranges and example.com: neither can reach a
					# real person, which is the point.
					"mobile_no": f"+974 5500 {1000 + index:04d}",
					"email_id": f"demo.guest{index:02d}@example.com",
					"city": "Doha",
					"corporate_account": "Demo Corporate Account" if kind == "corporate" else None,
					"originating_property": self.property,
					"notes": marker(key),
				}
			)

			# The property requires identification at check-in, so every demo
			# guest carries one. The number is obviously fictional.
			doc.append(
				"identifications",
				{
					"id_type": "Passport",
					"id_number": f"DEMO{index:05d}",
					"issuing_country": _link_or_none("Country", nationality),
					"expiry_date": add_days(nowdate(), 900),
				},
			)

			doc.insert(ignore_permissions=True)

			self.guests.append(doc.name)
			self.manifest.remember(key, "Guest", doc.name)

	# -- operating days --------------------------------------------------

	def _seed_history_day(self, day: int):
		"""One full day of trading, closed by a real Night Audit.

		The close is what makes the day's occupancy, ADR and RevPAR
		authoritative, and it is also what moves the business date on.
		"""
		business_date = getdate(get_business_date(self.property))
		print(f"  history day {day}: business date {business_date}")

		self._check_out_due(business_date)

		for slot, nights in enumerate(HISTORY_PLAN[day]):
			self._make_stay(
				key=f"stay:{business_date}:{slot:02d}",
				guest_index=(day * 17 + slot) % len(self.guests),
				arrival=business_date,
				nights=nights,
				source_index=day * 7 + slot,
			)

		self._run_audit_to_close(business_date)

	def _seed_today(self):
		"""The day under review: what the desk still has in front of it."""
		business_date = getdate(get_business_date(self.property))
		print(f"  review day: business date {business_date}")

		self._align_departures(business_date)

		# Arrivals. Most are still to be walked to a room, which is what the
		# board is for; two are already in house so the "checked in" state is
		# visible too.
		for slot in range(TARGET_ARRIVALS_TODAY):
			checked_in = slot < 2
			assigned = slot < 7

			self._make_reservation_for_today(
				key=f"arrival:{business_date}:{slot:02d}",
				guest_index=(23 + slot * 3) % len(self.guests),
				arrival=business_date,
				nights=[2, 3, 1, 4, 2, 3, 5, 2, 3, 4][slot],
				source_index=slot,
				assign=assigned,
				check_in=checked_in,
				# One arrival is deliberately walked into a room that is not
				# ready, through the override the property allows, so the
				# readiness warning on the board has something to show.
				unready=(slot == 5),
			)

		self._post_ancillary_spend(business_date)
		self._settle_some_departures(business_date)

	def _align_departures(self, business_date):
		"""Make sure the review day actually has departures to work.

		Stays are shortened through `stays.shorten_stay`, which re-prices and
		re-checks the same way a front desk change does; the seed never edits a
		departure date directly.
		"""
		in_house = stay_service.get_in_house(self.property)
		leaving = [s for s in in_house if getdate(s["departure_date"]) == business_date]
		shortfall = TARGET_DEPARTURES_TODAY - len(leaving)

		if shortfall <= 0:
			return

		candidates = [
			s
			for s in in_house
			if getdate(s["departure_date"]) > business_date
			and getdate(s["arrival_date"]) < business_date
		]

		for stay in candidates[:shortfall]:
			try:
				stay_service.shorten_stay(
					stay["name"],
					business_date,
					reason=f"{MARKER}: guest asked to leave earlier",
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Could not shorten stay {stay['name']}: {str(exc)[:120]}")

	def _settle_some_departures(self, business_date):
		"""Leave the departures board with a realistic spread.

		Some guests have paid and are clear to go, some still owe money and are
		legitimately blocked, one is a corporate account leaving on the city
		ledger, and two have already gone. The blockers are the checkout
		service's own — the seed does not decide who may leave.
		"""
		rows = [
			s
			for s in stay_service.get_in_house(self.property)
			if getdate(s["departure_date"]) == business_date
		]
		rows.sort(key=lambda row: row["room"] or "")

		for position, stay in enumerate(rows):
			folio = frappe.db.get_value("Stay", stay["name"], "folio")
			if not folio:
				continue

			balance = flt(frappe.db.get_value("Guest Folio", folio, "balance"))

			# 0,1 -> paid and checked out. 2,3 -> paid, ready, still here.
			# 4 -> city ledger, checked out owing. Rest -> outstanding balance.
			if position in (0, 1, 2, 3) and balance > 0.005:
				folio_service.post_payment(
					folio,
					balance,
					"Credit Card" if position % 2 else "Cash",
					idempotency_key=f"demo-settle:{stay['name']}",
					reference=f"{MARKER} settlement",
					business_date=business_date,
				)

			if position in (0, 1):
				self._safe_check_out(stay["name"])
			elif position == 4:
				self._safe_check_out(
					stay["name"],
					allow_open_balance=True,
					reason=f"{MARKER}: corporate account settled on the city ledger",
				)

	def _post_ancillary_spend(self, business_date):
		"""Room service, minibar, laundry and the rest, onto in-house folios.

		Posted through `folio.post_charge` with a stable idempotency key, so a
		rerun finds the same lines instead of charging the guest twice — the
		same guarantee the night audit relies on.
		"""
		in_house = stay_service.get_in_house(self.property)

		for index, stay in enumerate(in_house):
			folio = frappe.db.get_value("Stay", stay["name"], "folio")
			if not folio:
				continue

			charge_type, description, amount = fixture.EXTRAS[index % len(fixture.EXTRAS)]

			try:
				folio_service.post_charge(
					folio,
					charge_type,
					description,
					amount,
					idempotency_key=f"demo-extra:{stay['name']}:{index}",
					business_date=business_date,
					charge_date=business_date,
					# 10% service charge on ancillary spend, which is what the
					# property's fee configuration would apply if it were set.
					tax_amount=round(amount * 0.10, 2),
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Extra charge on {folio} refused: {str(exc)[:120]}")

			# Every third guest leaves a deposit at the desk, so payments and
			# outstanding balances are both represented.
			if index % 3 == 0:
				try:
					folio_service.post_payment(
						folio,
						400.0,
						"Credit Card",
						payment_type="Deposit",
						idempotency_key=f"demo-deposit:{stay['name']}",
						business_date=business_date,
					)
				except Exception as exc:  # noqa: BLE001
					self.notes.append(f"Deposit on {folio} refused: {str(exc)[:120]}")

	# -- reservations and stays ------------------------------------------

	def _make_stay(self, *, key, guest_index, arrival, nights, source_index):
		"""A confirmed reservation checked straight into a room."""
		if self.manifest.get(key):
			self.manifest.note_reuse("Stay", self.manifest.get(key))
			return

		reservation = self._make_reservation(
			key=f"res:{key}",
			guest_index=guest_index,
			arrival=arrival,
			nights=nights,
			source_index=source_index,
		)
		if not reservation:
			return

		result = self._check_in(reservation)
		if result:
			self.manifest.remember(key, "Stay", result["stay"])

	def _make_reservation_for_today(
		self, *, key, guest_index, arrival, nights, source_index, assign, check_in, unready
	):
		reservation = self._make_reservation(
			key=f"res:{key}",
			guest_index=guest_index,
			arrival=arrival,
			nights=nights,
			source_index=source_index,
			# Half of today's arrivals carry a guarantee, which is what the
			# arrivals board's guarantee column is for.
			guarantee="Credit Card" if source_index % 2 == 0 else None,
		)
		if not reservation:
			return

		if not assign:
			return

		room = self._assign_room(reservation, allow_unready=unready)
		if not room:
			return

		if check_in:
			self._check_in(reservation, allow_unready=unready)

	def _make_reservation(
		self, *, key, guest_index, arrival, nights, source_index, guarantee=None, confirm=True
	):
		existing = self.manifest.get(key)
		if existing:
			self.manifest.note_reuse("Reservation", existing)
			return existing

		guest = self.guests[guest_index % len(self.guests)]
		guest_doc = frappe.db.get_value(
			"Guest", guest, ["guest_name", "email_id", "mobile_no", "guest_type"], as_dict=True
		)

		source = fixture.SOURCE_PATTERN[source_index % len(fixture.SOURCE_PATTERN)]
		reservation_type = dict(fixture.BOOKING_SOURCES)[source]
		room_type = self._pick_room_type(source_index)
		departure = add_days(getdate(arrival), nights)

		adults, children = self._party(guest_doc.guest_type, room_type)

		try:
			doc = frappe.get_doc(
				{
					"doctype": "Reservation",
					"property": self.property,
					"reservation_status": "Draft",
					"reservation_type": reservation_type,
					"booking_source": source,
					"channel": "Booking.com" if source == "OTA" else None,
					"guest": guest,
					"guest_name": guest_doc.guest_name,
					"guest_email": guest_doc.email_id,
					"guest_mobile": guest_doc.mobile_no,
					"arrival_date": arrival,
					"departure_date": departure,
					"arrival_time": "14:00:00",
					"rate_plan": RATE_PLAN if frappe.db.exists("Rate Plan", RATE_PLAN) else None,
					"currency": self.currency,
					"market_segment": "Corporate" if source == "Corporate" else "Leisure",
					"internal_notes": marker(key),
					"special_requests": _special_request(source_index),
					"rooms": [
						{
							"room_type": room_type,
							"rooms": 1,
							"arrival_date": arrival,
							"departure_date": departure,
							"adults": adults,
							"children": children,
						}
					],
				}
			).insert(ignore_permissions=True)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Reservation {key} refused: {str(exc)[:160]}")
			return None

		self.manifest.remember(key, "Reservation", doc.name)

		if not confirm:
			return doc.name

		try:
			reservation_service.confirm(doc.name, reason=f"{MARKER}: demo booking confirmed")
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Could not confirm {doc.name}: {str(exc)[:160]}")
			return doc.name

		if guarantee:
			try:
				reservation_service.guarantee(
					doc.name, guarantee, reason=f"{MARKER}: card held"
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Could not guarantee {doc.name}: {str(exc)[:120]}")

		return doc.name

	def _assign_room(self, reservation: str, *, allow_unready: bool = False) -> str | None:
		"""Give the reservation the first room its line can legally take.

		Candidates are tried in turn and the service is allowed to refuse:
		`assign_room` re-checks the room's four dimensions and the date clash
		under a lock, and a refusal here means the room genuinely could not be
		given away — which is exactly the check that keeps the demo internally
		consistent.
		"""
		doc = frappe.get_doc("Reservation", reservation)

		for line in doc.rooms:
			if line.assigned_room:
				continue

			for room in self._candidate_rooms(line.room_type):
				try:
					reservation_service.assign_room(
						reservation, line.name, room, allow_unready=allow_unready
					)
					return room
				except Exception:  # noqa: BLE001, S112
					continue

			self.notes.append(
				f"No assignable {line.room_type} room was free for {reservation}."
			)

		return None

	def _candidate_rooms(self, room_type: str) -> list[str]:
		rows = frappe.get_all(
			"Hotel Room",
			filters={"property": self.property, "room_type": room_type, "is_active": 1},
			fields=["name", "occupancy_status", "housekeeping_status", "maintenance_status", "inventory_status", "is_active"],
			order_by="room_number asc",
		)

		occupied = set(
			frappe.get_all(
				"Stay",
				filters={
					"property": self.property,
					"stay_status": ("in", ("In House", "Due Out")),
				},
				pluck="room",
			)
		)
		rows = [r for r in rows if r["name"] not in occupied]

		# Ready rooms first, so the seed only reaches for a dirty one when it
		# has to and the readiness override stays the exception it should be.
		ready = [r["name"] for r in rows if room_service.is_assignable(r["name"], state=r)]
		fallback = [
			r["name"]
			for r in rows
			if r["name"] not in ready
			and room_service.is_assignable(r["name"], allow_unready_housekeeping=True, state=r)
		]

		return ready + fallback

	def _check_in(self, reservation: str, *, allow_unready: bool = False):
		doc = frappe.get_doc("Reservation", reservation)

		for line in doc.rooms:
			room = line.assigned_room or self._assign_room(reservation, allow_unready=allow_unready)
			if not room:
				return None

			try:
				return stay_service.check_in(
					reservation,
					line.name,
					room,
					allow_unready_room=allow_unready,
					readiness_reason=(
						f"{MARKER}: guest waiting, room release agreed with housekeeping"
						if allow_unready
						else None
					),
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Check-in refused for {reservation}: {str(exc)[:160]}")
				return None

		return None

	def _check_out_due(self, business_date):
		"""Check out everyone whose departure date has arrived.

		Balances are cleared first with a real payment, because a guest with an
		open folio is legitimately refused at the desk and the seed should not
		be the thing that overrides that.
		"""
		for stay in stay_service.get_in_house(self.property):
			if getdate(stay["departure_date"]) > business_date:
				continue

			folio = frappe.db.get_value("Stay", stay["name"], "folio")
			if folio:
				balance = flt(frappe.db.get_value("Guest Folio", folio, "balance"))
				if balance > 0.005:
					try:
						folio_service.post_payment(
							folio,
							balance,
							"Credit Card",
							idempotency_key=f"demo-checkout-settle:{stay['name']}",
							business_date=business_date,
						)
					except Exception as exc:  # noqa: BLE001
						self.notes.append(f"Settlement on {folio} refused: {str(exc)[:120]}")

			self._safe_check_out(stay["name"])
			self._release_room(stay.get("room"))

	def _safe_check_out(self, stay: str, **kwargs):
		"""Check out through the full path, ledger included.

		`post_to_erp` is deliberately left at its default. A folio may not
		close while it holds charges that never reached ERPNext — that is the
		rule which stops revenue being stranded outside the ledger — so a
		checkout that skips the posting cannot finish, and a checkout that
		cannot finish leaves a guest in a room the next arrival is then given.
		"""
		try:
			return checkout_service.check_out(stay, **kwargs)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Checkout refused for {stay}: {str(exc)[:160]}")
			return None

	def _release_room(self, room: str | None):
		"""Put a departed room back into service the way housekeeping does."""
		if not room:
			return

		for task in frappe.get_all(
			"Housekeeping Task",
			filters={
				"room": room,
				"task_status": ("not in", ("Completed", "Cancelled")),
			},
			pluck="name",
		):
			self._finish_task(task)

		if frappe.db.get_value("Hotel Room", room, "housekeeping_status") not in ("Clean", "Inspected"):
			try:
				room_service.set_status(
					room, room_service.HOUSEKEEPING, "Clean", reason=f"{MARKER}: room released"
				)
			except Exception:  # noqa: BLE001, S110
				pass

	def _finish_task(self, task: str):
		"""Take one cleaning task all the way through its state machine.

		Pending does not go straight to Inspection Pending — an attendant is
		assigned, starts, finishes, and a supervisor signs off. Walking the
		states is how the room's housekeeping dimension ends up Clean without
		anyone writing to it.
		"""
		status = frappe.db.get_value("Housekeeping Task", task, "task_status")

		try:
			if status == "Pending":
				housekeeping_service.assign(task, "Administrator")
				status = "Assigned"

			if status in ("Assigned", "DND", "Service Refused"):
				housekeeping_service.start(task)
				status = "In Progress"

			if status == "In Progress":
				status = housekeeping_service.complete(
					task, minutes=35, minibar_checked=True
				)["task_status"]

			if status == "Inspection Pending":
				housekeeping_service.inspect(
					task, passed=True, notes=f"{MARKER}: spot check", score=9
				)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Could not close housekeeping task {task}: {str(exc)[:120]}")

	# -- night audit -----------------------------------------------------

	def _run_audit_to_close(self, business_date):
		"""Drive one business date through the audit and close it.

		Every step is the real service call in the real order. Blocking
		exceptions are resolved with an explicit note rather than bypassed,
		because `close` refuses while any remain and that refusal is the point
		of the rule.
		"""
		audit = self._current_audit(business_date)
		if not audit:
			return

		try:
			audit_service.review(audit)
			audit_service.mark_no_shows(audit)
			audit_service.review(audit)
			audit_service.post_room_charges(audit)
			audit_service.mark_due_outs(audit)
			audit_service.reconcile(audit)
			# Resolving comes last. `reconcile` appends a fresh variance row
			# every time it runs, so resolving before a further reconcile would
			# always leave one new blocker standing and `close` would always
			# refuse - which is the rule doing its job, not a bug to route
			# around.
			self._resolve_blocking(audit)
			audit_service.close(audit)
			self.audits_closed.append(audit)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Night Audit {audit} for {business_date} did not close: {str(exc)[:200]}")

	def _current_audit(self, business_date) -> str | None:
		existing = frappe.db.get_value(
			"Night Audit", {"property": self.property, "business_date": business_date}, "name"
		)
		if existing:
			return existing

		try:
			return audit_service.start(self.property, business_date)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Could not open a Night Audit for {business_date}: {str(exc)[:160]}")
			return None

	def _resolve_blocking(self, audit: str):
		doc = frappe.get_doc("Night Audit", audit)

		for row in doc.audit_exceptions:
			if row.severity != "Blocking" or row.is_resolved:
				continue

			audit_service.resolve_exception(
				audit,
				row.name,
				f"{MARKER}: reviewed on a local demo site. "
				"ERPNext posting is not configured here, so the subledger is the "
				"only record and there is nothing to reconcile against.",
			)

	def _start_todays_audit(self):
		"""Open and review the current business date, and stop there.

		The dashboard's audit card reads the audit's own status, so leaving it
		part way through is what gives the card something true to show. It is
		not closed: closing would move the business date off the day being
		reviewed.
		"""
		business_date = getdate(get_business_date(self.property))
		audit = self._current_audit(business_date)

		if not audit:
			return

		try:
			audit_service.review(audit)
			# Posting the night's room charges is a step of the audit, not a
			# short cut around it: it is what puts room revenue on the business
			# date, and it is idempotent per stay per date. Stopping here
			# leaves the audit mid-run, which is the state the card describes.
			audit_service.post_room_charges(audit)
			audit_service.mark_due_outs(audit)
			audit_service.review(audit)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Could not run tonight's audit: {str(exc)[:160]}")

	# -- room states, workload -------------------------------------------

	def _seed_room_states(self):
		"""Spread the vacant rooms across the states the board draws.

		Only rooms with no guest and no maintenance claim are touched, and each
		move goes through `rooms.set_status`, which enforces the transition
		table and writes a Room Status Log line.
		"""
		free = self._free_rooms()

		# Rooms held for guests arriving today, which the board shows as Reserved.
		assigned_today = frappe.get_all(
			"Reservation Room",
			filters={
				"parenttype": "Reservation",
				"property": self.property,
				"arrival_date": getdate(get_business_date(self.property)),
				"reservation_status": ("in", ("Confirmed", "Guaranteed")),
				"assigned_room": ("is", "set"),
			},
			pluck="assigned_room",
		)

		vacant_and_held = [
			room
			for room in assigned_today
			if frappe.db.get_value("Hotel Room", room, "occupancy_status") == "Vacant"
		]

		for room in vacant_and_held[:TARGET_RESERVED]:
			self._set_occupancy(room, "Reserved", "held for an arrival today")

		already_dirty = frappe.db.count(
			"Hotel Room",
			{"property": self.property, "occupancy_status": "Vacant", "housekeeping_status": "Dirty"},
		)
		shortfall = max(TARGET_VACANT_DIRTY - already_dirty, 0)

		dirty = [r for r in free if r not in assigned_today][:shortfall]
		for room in dirty:
			try:
				room_service.set_status(
					room,
					room_service.HOUSEKEEPING,
					"Dirty",
					reason=f"{MARKER}: departure not yet serviced",
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Could not mark {room} dirty: {str(exc)[:120]}")

	def _set_occupancy(self, room: str, status: str, why: str):
		try:
			room_service.set_status(
				room, room_service.OCCUPANCY, status, reason=f"{MARKER}: {why}"
			)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Could not set {room} to {status}: {str(exc)[:120]}")

	def _free_rooms(self) -> list[str]:
		rows = frappe.get_all(
			"Hotel Room",
			filters={"property": self.property, "is_active": 1},
			fields=[
				"name",
				"occupancy_status",
				"housekeeping_status",
				"maintenance_status",
				"inventory_status",
			],
			order_by="room_number desc",
		)

		return [
			r["name"]
			for r in rows
			if r["occupancy_status"] == "Vacant"
			and r["maintenance_status"] == "Operational"
			and r["inventory_status"] == "Available"
		]

	def _seed_maintenance(self):
		"""Tickets, and the two rooms a ticket legitimately takes out of sale."""
		free = self._free_rooms()
		cursor = 0

		for index, (category, priority, title, description, out_of_service) in enumerate(
			fixture.MAINTENANCE_PLAN
		):
			key = f"ticket:{index:02d}"
			if self.manifest.get(key):
				self.manifest.note_reuse("Maintenance Ticket", self.manifest.get(key))
				continue

			room = None
			if cursor < len(free):
				room = free[cursor]
				cursor += 1

			try:
				ticket = maintenance_service.create_ticket(
					self.property,
					title=title,
					description=f"{description}\n\n{marker(key)}",
					category=category,
					priority=priority,
					ticket_type="Preventive" if "Planned" in title else "Corrective",
					room=room,
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Maintenance ticket {index} refused: {str(exc)[:140]}")
				continue

			self.manifest.remember(key, "Maintenance Ticket", ticket)

			# A spread of progress, so the board is not a wall of "Open".
			try:
				if index % 3 == 1:
					maintenance_service.assign(ticket, "Administrator")
				elif index % 3 == 2:
					maintenance_service.assign(ticket, "Administrator")
					maintenance_service.start_work(ticket)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Could not progress ticket {ticket}: {str(exc)[:120]}")

			if out_of_service and room:
				try:
					result = maintenance_service.take_out_of_service(
						ticket,
						out_of_service,
						f"{MARKER}: {title.lower()}",
					)
					if result.get("room_block"):
						self.manifest.remember(
							f"block:{index:02d}", "Room Block", result["room_block"]
						)
				except Exception as exc:  # noqa: BLE001
					self.notes.append(f"Could not take {room} out of sale: {str(exc)[:140]}")

		self._mark_one_under_maintenance()

	def _mark_one_under_maintenance(self):
		"""One room mid-repair, which is a different state from out of sale."""
		free = self._free_rooms()
		if not free:
			return

		room = free[-1]
		try:
			room_service.set_status(
				room,
				room_service.MAINTENANCE,
				"Under Maintenance",
				reason=f"{MARKER}: fan coil unit service in progress",
			)
		except Exception as exc:  # noqa: BLE001
			self.notes.append(f"Could not set {room} under maintenance: {str(exc)[:120]}")

	def _seed_housekeeping(self):
		"""A day's cleaning list, at a spread of stages."""
		business_date = getdate(get_business_date(self.property))
		rooms = [
			r["name"]
			for r in frappe.get_all(
				"Hotel Room",
				filters={"property": self.property, "is_active": 1},
				fields=["name"],
				order_by="room_number asc",
			)
		]

		for index, (task_type, priority) in enumerate(fixture.HOUSEKEEPING_PLAN):
			key = f"task:{business_date}:{index:02d}"
			if self.manifest.get(key):
				self.manifest.note_reuse("Housekeeping Task", self.manifest.get(key))
				continue

			room = rooms[(index * 4) % len(rooms)]

			try:
				task = housekeeping_service.create_task(
					self.property,
					room,
					task_type=task_type,
					priority=priority,
					scheduled_date=business_date,
					notes=marker(key),
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Housekeeping task {index} refused: {str(exc)[:140]}")
				continue

			self.manifest.remember(key, "Housekeeping Task", task)

			# 0-2 stay Pending, 3-5 assigned or started, 6-7 awaiting
			# inspection, 8-9 finished. Each stage is reached by calling the
			# service, so the room's housekeeping dimension follows along.
			try:
				if index in (3, 4, 5):
					housekeeping_service.assign(task, "Administrator")
					if index != 3:
						housekeeping_service.start(task)
				elif index in (6, 7):
					housekeeping_service.assign(task, "Administrator")
					housekeeping_service.start(task)
					housekeeping_service.complete(task, minutes=40, minibar_checked=True)
				elif index in (8, 9):
					housekeeping_service.assign(task, "Administrator")
					housekeeping_service.start(task)
					result = housekeeping_service.complete(task, minutes=32)
					if result["task_status"] == "Inspection Pending":
						housekeeping_service.inspect(
							task, passed=True, notes=f"{MARKER}: passed", score=9
						)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Could not progress task {task}: {str(exc)[:120]}")

	def _seed_guest_requests(self):
		in_house = stay_service.get_in_house(self.property)

		for index, (category, priority, subject, description) in enumerate(
			fixture.GUEST_REQUEST_PLAN
		):
			key = f"request:{index:02d}"
			if self.manifest.get(key):
				self.manifest.note_reuse("Guest Request", self.manifest.get(key))
				continue

			stay = in_house[index % len(in_house)] if in_house else None

			try:
				request = request_service.create_request(
					self.property,
					subject=subject,
					description=f"{description}\n\n{marker(key)}",
					category=category,
					request_type="Complaint" if priority == "Urgent" else "Request",
					priority=priority,
					guest=stay["guest"] if stay else None,
					stay=stay["name"] if stay else None,
					room=stay["room"] if stay else None,
				)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Guest request {index} refused: {str(exc)[:140]}")
				continue

			self.manifest.remember(key, "Guest Request", request)

			try:
				if index % 4 == 1:
					request_service.assign(request, "Administrator")
				elif index % 4 == 2:
					request_service.assign(request, "Administrator")
					request_service.start(request)
				elif index % 4 == 3 and index > 8:
					request_service.escalate(
						request, reason=f"{MARKER}: not answered inside the SLA"
					)
			except Exception as exc:  # noqa: BLE001
				self.notes.append(f"Could not progress request {request}: {str(exc)[:120]}")

	def _seed_future_reservations(self):
		"""The next fortnight's book, for the calendar and availability screens."""
		business_date = getdate(get_business_date(self.property))

		for index in range(12):
			key = f"future:{business_date}:{index:02d}"
			if self.manifest.get(key):
				self.manifest.note_reuse("Reservation", self.manifest.get(key))
				continue

			self._make_reservation(
				key=key,
				guest_index=(5 + index * 5) % len(self.guests),
				arrival=add_days(business_date, 1 + index),
				nights=[2, 3, 1, 4, 2, 5, 3, 2, 4, 1, 3, 2][index],
				source_index=index + 3,
				guarantee="Credit Card" if index % 3 == 0 else None,
				# Two are left unconfirmed on purpose: a book with nothing
				# tentative in it is not a book anyone recognises.
				confirm=index not in (4, 9),
			)

	# -- helpers ---------------------------------------------------------

	def _pick_room_type(self, index: int) -> str:
		"""Spread demand across the house roughly in proportion to inventory."""
		# Weighted by how many rooms of each type the house actually has, so
		# demand does not repeatedly ask for the four Deluxe Kings and get
		# refused by the availability engine.
		weighted = [
			"STD", "EXK", "DLXT", "STD", "EXK", "DLXT", "STD", "EXK",
			"FAM", "STD", "DLXT", "EXK", "STD", "DLX", "EXK", "DLXT",
		]
		code = weighted[index % len(weighted)]

		return self.room_types.get(code, code)

	def _party(self, guest_type: str, room_type: str) -> tuple[int, int]:
		if room_type.startswith("FAM"):
			return 2, 2
		if guest_type == "Corporate Guest":
			return 1, 0

		return 2, 0

	def verify(self) -> dict:
		"""Check the seeded hotel is internally possible.

		Not a test of the application - a test of what this script left behind.
		A room with two guests in it, or a guest whose room is not occupied,
		means the seed built something the hotel could not actually be in, and
		the reviewer needs to know that before reading anything off the screen.
		"""
		stays = frappe.get_all(
			"Stay",
			filters={"property": self.property, "stay_status": ("in", ("In House", "Due Out"))},
			fields=["name", "room", "departure_date"],
		)

		occupancy = {
			row["name"]: row["occupancy_status"]
			for row in frappe.get_all(
				"Hotel Room", filters={"property": self.property}, fields=["name", "occupancy_status"]
			)
		}

		seen: dict[str, list[str]] = {}
		for stay in stays:
			seen.setdefault(stay["room"], []).append(stay["name"])

		business_date = getdate(get_business_date(self.property))

		return {
			"rooms_with_more_than_one_active_stay": {
				room: names for room, names in seen.items() if len(names) > 1
			},
			"active_stays_whose_room_is_not_occupied": [
				stay["name"]
				for stay in stays
				if occupancy.get(stay["room"]) not in ("Occupied", "House Use", "Due Out")
			],
			"stays_past_their_departure_date": [
				stay["name"] for stay in stays if getdate(stay["departure_date"]) < business_date
			],
		}

	def summary(self) -> dict:
		from hospitality_pms.services import front_office as front_office_service

		dashboard = front_office_service.get_dashboard(self.property)

		result = {
			"property": self.property,
			"business_date": dashboard["business_date"],
			"created": len(self.manifest.created),
			"reused": len(self.manifest.reused),
			"records_by_doctype": {k: len(v) for k, v in self.manifest.by_doctype().items()},
			"audits_closed": self.audits_closed,
			"rooms": dashboard["rooms"],
			"front_office": dashboard["front_office"],
			"revenue": dashboard["revenue"],
			"performance": dashboard["performance"],
			"workload": dashboard["workload"],
			"consistency": self.verify(),
			"notes": self.notes,
			"could_not_display": self.unavailable,
			"manifest": manifest_path(),
		}

		print(frappe.as_json(result))

		return result


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def manifest_path() -> str:
	from hospitality_pms.demo import manifest as manifest_module

	return manifest_module.path()


def _resolve_property(property_name: str | None) -> str:
	if property_name:
		return property_name

	default = frappe.db.get_single_value("PMS Settings", "default_property")
	if default:
		return default

	names = frappe.get_all("Property", filters={"is_active": 1}, pluck="name", limit=2)

	if not names:
		frappe.throw("No active Property exists on this site.")

	if len(names) > 1:
		frappe.throw("Several properties exist; pass property='<name>'.")

	return names[0]


def _link_or_none(doctype: str, value: str | None) -> str | None:
	"""A link value only if the target actually exists on this site.

	Country, Gender and Language lists differ between installs, and a demo
	seed should degrade to a blank field rather than fail on one.
	"""
	if not value:
		return None

	return value if frappe.db.exists(doctype, value) else None


def _special_request(index: int) -> str | None:
	requests = [
		None,
		"High floor away from the lift, please.",
		"Late arrival, flight lands at 23:40.",
		None,
		"Twin beds if available.",
		"Quiet room, guest works nights.",
		None,
		"Cot required for an infant.",
	]

	return requests[index % len(requests)]


def _carries_marker(doctype: str, name: str) -> bool:
	"""Does this record still look like something the seed made?

	Checked against the free-text field the seed writes into for each doctype.
	A doctype with no such field falls back to the manifest alone, which is why
	only doctypes the seed inserts itself are ever listed here.
	"""
	fields = {
		"Guest": "notes",
		"Hotel Room": "notes",
		"Room Type": "description",
		"Reservation": "internal_notes",
		"Housekeeping Task": "notes",
		"Maintenance Ticket": "description",
		"Guest Request": "description",
		"Room Block": "reason",
		"Zone": "description",
		"Building": "description",
	}

	field = fields.get(doctype)
	if not field:
		return True

	value = frappe.db.get_value(doctype, name, field) or ""

	return MARKER in value
