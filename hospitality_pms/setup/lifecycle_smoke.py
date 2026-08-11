"""One guest, all the way through, on the merged baseline.

Part 9 of the 16.6.5 integration validation. Not UAT: a single focused pass
through the chain the hotel actually runs, asserting at each hand-off that the
invariant the corresponding wave established still holds after the merge.

    Reservation -> Confirm -> Assign -> Check-In -> Folio -> Room Charge
      -> ERP Invoice + Tax -> Payment -> ERP allocation -> Checkout
      -> Night Audit post/reconcile/close -> business date advances

Disposable data only; everything is torn down at the end whether or not the
run succeeds. Run with:

    bench --site <site> execute hospitality_pms.setup.lifecycle_smoke.run
"""

import frappe
from frappe.utils import add_days, flt, getdate

from hospitality_pms.services import checkout as checkout_service
from hospitality_pms.services import folio as folio_service
from hospitality_pms.services import night_audit as audit_service
from hospitality_pms.services import posting as posting_service
from hospitality_pms.services import reservations as reservation_service
from hospitality_pms.services import stays as stay_service
from hospitality_pms.services.availability import get_availability, get_assignable_rooms
from hospitality_pms.services.property import get_business_date
from hospitality_pms.tests.posting_world import (
	folio_invoices,
	invoice_tax_rows,
	invoice_totals,
	payment_references,
)

ROOM_RATE = 200.0
TAX_RATE = 10.0
MINIBAR = 50.0

failures: list[str] = []
notes: list[str] = []


def check(label: str, condition: bool, detail: str = ""):
	mark = "ok  " if condition else "FAIL"
	if not condition:
		failures.append(f"{label} :: {detail}")
	print(f"  [{mark}] {label}{('  — ' + detail) if detail else ''}")


def run():
	from hospitality_pms.tests.posting_world import PostingWorld

	world = PostingWorld("LFSM", "LF")

	try:
		_lifecycle(world)
	finally:
		world.teardown()
		frappe.db.commit()
		print("\ntorn down.")

	print()
	if failures:
		print(f"LIFECYCLE SMOKE: FAILED ({len(failures)})")
		for failure in failures:
			print(f"  - {failure}")
	else:
		print("LIFECYCLE SMOKE: PASS")

	for note in notes:
		print(f"  note: {note}")


def _lifecycle(world):
	fixtures = world.fixtures
	prop = world.property

	room_type = fixtures.room_type(prop, base_rate=ROOM_RATE)
	rooms = fixtures.rooms(prop, room_type, count=2)
	rate_plan = fixtures.rate_plan(prop, room_type, base_rate=ROOM_RATE)
	guest = fixtures.guest("Lifecycle")
	frappe.db.commit()

	business_date = getdate(get_business_date(prop))
	print(f"\nproperty {prop} | business date {business_date} | rooms {len(rooms)}\n")

	# -- 1. Reservation ------------------------------------------------
	print("1. Reservation")
	reservation = fixtures.reservation(
		prop, room_type, guest, rate_plan=rate_plan, arrival=business_date, nights=1, rooms=1
	)
	frappe.db.commit()

	before = _available(prop, room_type, business_date)
	check("draft holds no inventory", before == len(rooms), f"available={before}")

	# -- 2. Confirm ----------------------------------------------------
	print("2. Confirm")
	reservation_service.confirm(reservation)
	frappe.db.commit()

	after = _available(prop, room_type, business_date)
	lines = frappe.get_all(
		"Reservation Room", filters={"parent": reservation}, fields=["name", "rooms"], order_by="idx"
	)

	check("confirmation consumes exactly one room", after == before - 1, f"{before} -> {after}")
	check("one operational row per physical room", len(lines) == 1 and lines[0]["rooms"] == 1,
	      f"lines={[(l['name'], l['rooms']) for l in lines]}")

	# -- 3. Assign room ------------------------------------------------
	print("3. Assign room")
	line = lines[0]["name"]
	offered = get_assignable_rooms(prop, room_type, business_date, add_days(business_date, 1))
	reservation_service.assign_room(reservation, line, offered[0]["name"])
	frappe.db.commit()

	assigned = frappe.db.get_value("Reservation Room", line, "assigned_room")
	still_offered = [
		row["name"]
		for row in get_assignable_rooms(prop, room_type, business_date, add_days(business_date, 1))
	]

	check("room assigned", assigned == offered[0]["name"], assigned)
	check("assigned room no longer offered", assigned not in still_offered)

	# -- 4. Check-in ---------------------------------------------------
	print("4. Check-in")
	result = stay_service.check_in(reservation, line, assigned)
	frappe.db.commit()
	stay, folio = result["stay"], result["folio"]

	check("one stay for one room", frappe.db.count("Stay", {"reservation": reservation}) == 1)
	check("one folio opened", bool(folio), folio)
	check("room now occupied",
	      frappe.db.get_value("Hotel Room", assigned, "occupancy_status") == "Occupied")
	check("reservation is Checked In",
	      frappe.db.get_value("Reservation", reservation, "reservation_status") == "Checked In")

	# -- 5. Folio charges, through the service only ----------------------
	print("5. Folio charges")
	folio_service.post_charge(
		folio, "Room Charge", "Night 1", ROOM_RATE, tax_amount=ROOM_RATE * TAX_RATE / 100,
		idempotency_key="lfsm:room:1",
	)
	folio_service.post_charge(
		folio, "Minibar", "Water", MINIBAR, tax_amount=MINIBAR * TAX_RATE / 100,
		idempotency_key="lfsm:minibar:1",
	)
	# The same key again must change nothing.
	replay = folio_service.post_charge(
		folio, "Minibar", "Water", MINIBAR, tax_amount=MINIBAR * TAX_RATE / 100,
		idempotency_key="lfsm:minibar:1",
	)
	frappe.db.commit()

	# `total_charges` sums each row's `total_amount`, which is net plus tax.
	expected_net = ROOM_RATE + MINIBAR
	expected_tax = expected_net * TAX_RATE / 100
	expected_gross = expected_net + expected_tax

	totals_folio = frappe.db.get_value(
		"Guest Folio", folio, ["total_charges", "total_taxes", "balance"], as_dict=True
	)

	check("replayed charge is refused as duplicate", bool(replay.get("duplicate")))
	check("folio gross charges correct",
	      abs(flt(totals_folio["total_charges"]) - expected_gross) < 0.01,
	      f"{totals_folio['total_charges']} vs {expected_gross}")
	check("folio tax correct", abs(flt(totals_folio["total_taxes"]) - expected_tax) < 0.01,
	      f"{totals_folio['total_taxes']} vs {expected_tax}")
	check("two charge rows, not three", frappe.db.count("Folio Charge", {"parent": folio}) == 2,
	      f"rows={frappe.db.count('Folio Charge', {'parent': folio})}")
	check("charge carries the business date",
	      getdate(frappe.db.get_value("Folio Charge", {"parent": folio}, "business_date")) == business_date)

	# -- 6. ERP invoice + tax -------------------------------------------
	print("6. ERP Sales Invoice")
	posting_service.post_folio_invoice(folio)
	frappe.db.commit()

	invoices = folio_invoices(folio)
	totals = invoice_totals(invoices[0])
	tax_rows = invoice_tax_rows(invoices[0])

	check("one invoice raised", len(invoices) == 1, str(invoices))
	check("invoice net matches folio net", abs(flt(totals["net_total"]) - expected_net) < 0.01,
	      f"net={totals['net_total']} vs {expected_net}")
	check("invoice tax matches folio tax", abs(flt(totals["total_taxes_and_charges"]) - expected_tax) < 0.01,
	      f"tax={totals['total_taxes_and_charges']} vs {expected_tax}")
	check("tax posted as Actual rows", bool(tax_rows) and all(r["charge_type"] == "Actual" for r in tax_rows),
	      f"{[r['charge_type'] for r in tax_rows]}")

	outstanding_before = flt(totals["outstanding_amount"])
	check("invoice outstanding equals its grand total",
	      abs(outstanding_before - flt(totals["grand_total"])) < 0.01,
	      f"{outstanding_before} vs {totals['grand_total']}")

	# -- 7. Payment + ERP allocation -------------------------------------
	print("7. Payment and allocation")
	due = flt(frappe.db.get_value("Guest Folio", folio, "balance"))
	payment = folio_service.post_payment(folio, due, "Cash", idempotency_key="lfsm:pay:1")
	posting_service.post_folio_payment(folio, payment["row"])
	frappe.db.commit()

	totals_after = invoice_totals(invoices[0])
	entries = frappe.get_all(
		"Payment Entry Reference", filters={"reference_name": invoices[0]}, pluck="parent"
	)
	allocated = sum(flt(r["allocated_amount"]) for r in payment_references(entries[0])) if entries else 0

	check("a payment entry was raised and allocated", bool(entries), str(entries))
	check("allocation reduces invoice outstanding",
	      flt(totals_after["outstanding_amount"]) < outstanding_before,
	      f"{outstanding_before} -> {totals_after['outstanding_amount']}")
	check("allocated amount matches the payment", abs(allocated - due) < 0.01,
	      f"allocated={allocated} paid={due}")
	check("folio balance cleared", abs(flt(frappe.db.get_value("Guest Folio", folio, "balance"))) < 0.01)

	# -- 8. Checkout -------------------------------------------------------
	print("8. Checkout")
	checkout_service.check_out(stay, post_to_erp=True)
	frappe.db.commit()

	folio_status = frappe.db.get_value("Guest Folio", folio, "folio_status")

	check("stay checked out",
	      frappe.db.get_value("Stay", stay, "stay_status") == "Checked Out",
	      frappe.db.get_value("Stay", stay, "stay_status"))
	check("folio settled or closed", folio_status in ("Settled", "Closed"), folio_status)
	check("room released",
	      frappe.db.get_value("Hotel Room", assigned, "occupancy_status") != "Occupied",
	      frappe.db.get_value("Hotel Room", assigned, "occupancy_status"))

	# -- 9. Night Audit ----------------------------------------------------
	print("9. Night Audit")
	audit = audit_service.start(prop)
	audit_service.review(audit)
	audit_service.post_room_charges(audit)
	audit_service.reconcile(audit)
	frappe.db.commit()

	markers = frappe.db.get_value(
		"Night Audit", audit,
		["review_completed_on", "posting_completed_on", "reconciliation_completed_on", "business_date"],
		as_dict=True,
	)

	check("audit is for the business date", getdate(markers["business_date"]) == business_date)
	check("review marker durable", bool(markers["review_completed_on"]))
	check("posting marker durable", bool(markers["posting_completed_on"]))
	check("reconciliation marker durable", bool(markers["reconciliation_completed_on"]))

	# -- 10. Close ---------------------------------------------------------
	print("10. Close")
	audit_service.close(audit)
	frappe.db.commit()

	advanced = getdate(get_business_date(prop))

	check("audit closed",
	      frappe.db.get_value("Night Audit", audit, "audit_status") == "Closed",
	      frappe.db.get_value("Night Audit", audit, "audit_status"))
	check("business date advances exactly one day", advanced == add_days(business_date, 1),
	      f"{business_date} -> {advanced}")

	# The audit and its exceptions are property-scoped fixtures; remove them
	# here because Fixtures does not track documents the service created.
	frappe.db.delete("Night Audit Exception", {"parenttype": "Night Audit"})
	frappe.db.delete("Night Audit", {"property": prop})
	frappe.db.commit()


def _available(prop: str, room_type: str, on_date) -> int:
	availability = get_availability(prop, on_date, add_days(on_date, 1), room_type)

	return int(availability["room_types"][room_type]["min_available"])
