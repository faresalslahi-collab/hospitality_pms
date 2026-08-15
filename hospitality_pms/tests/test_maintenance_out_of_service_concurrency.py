"""Out-of-service control must raise exactly one Room Block per ticket.

`take_out_of_service` removes a room from sale by raising a *submitted* Room
Block, and records the block's name on the ticket. Releasing the room later
(`verify_and_release`) cancels the block the ticket points at.

The defect this suite exists to catch is that the block was raised
unconditionally, with no guard on an existing `ticket.room_block`, and read the
ticket through the stale-snapshot anti-pattern (`lock_document` + a separate
`frappe.get_doc`). `lock_document` serialises but does not refresh (N1), so a
double-clicked or retried request that queued behind the winner read
`room_block` as empty from its pre-lock snapshot, submitted a *second* Active
Room Block for the same room, and overwrote the ticket's reference with the
newer one. The first block is then orphaned: `verify_and_release` releases only
the block the ticket names, so the orphan stays Active and holds the room out of
sale for good after the repair is signed off.

The overlap guard on Room Block does not save this. It reads with a plain
`get_all`, answered from the same stale snapshot, so under a genuine race it does
not see the winner's block either. A sequential second call *is* refused by that
guard - which is why this has to be a real two-process race to reproduce, not a
sequential simulation. See `tests/concurrency.py` for why processes, not threads.

The invariant asserted is the persisted one:

    a ticket's room is covered by at most one submitted, Active Room Block,
    and that block is the one the ticket references

and, after a passing verification, by none - never merely "one worker raised".
"""

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_pms.services import maintenance as maintenance_service
from hospitality_pms.tests.concurrency import Worker, assert_all_ran, run_workers
from hospitality_pms.tests.fixtures import Fixtures

BLOCK_DOCTYPE = "Room Block"
TICKET_DOCTYPE = "Maintenance Ticket"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
#
# Module level and JSON-serialisable arguments only: each is imported by a fresh
# process through `frappe.get_attr`. The worker opens its read view with a plain
# read *before* the barrier releases it, which fixes the REPEATABLE-READ snapshot
# early - the condition under which the lock-without-refresh bug (N1) actually
# bites. A worker that took its first read after the rival committed would see
# the rival's block through no merit of the code under test.


def _take_out_of_service_worker(barrier, ticket: str, room: str, tag: str, partner: str) -> dict:
    """One operator taking the ticket's room out of order."""
    # Open this transaction's snapshot on the pre-race state: no block yet.
    frappe.db.sql("select room_block from `tabMaintenance Ticket` where name = %s", ticket)
    frappe.db.sql(
        "select name from `tabRoom Block` where room = %s and status = 'Active' and docstatus = 1",
        room,
    )

    barrier.signal(f"ready_{tag}")
    barrier.wait(f"ready_{partner}")

    result = maintenance_service.take_out_of_service(ticket, status="Out of Order", reason="Unsafe")
    frappe.db.commit()

    return {"room_block": result["room_block"]}


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------


class TestOutOfServiceIsIdempotent(IntegrationTestCase):
    """Two operators, one ticket, the same instant - one Room Block.

    Fixtures commit and workers commit, so nothing a race leaves behind is
    covered by `IntegrationTestCase`'s rollback; the suite clears its own world
    before every test and tears it down at the end.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixtures = Fixtures("MOOS")
        cls.property = cls.fixtures.property("MO")
        cls.room_type = cls.fixtures.room_type(cls.property, base_rate=100)
        cls.rooms = cls.fixtures.rooms(cls.property, cls.room_type, count=1)
        cls.room = cls.rooms[0]
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.teardown()
        super().tearDownClass()

    def setUp(self):
        frappe.set_user("Administrator")
        # Workers commit, so residue is not rolled back for us. Clear the blocks
        # and tickets, and put the room back to a clean, sellable, operational
        # state before each race.
        frappe.db.delete(BLOCK_DOCTYPE, {"property": self.property})
        frappe.db.delete(TICKET_DOCTYPE, {"property": self.property})
        frappe.db.set_value(
            "Hotel Room",
            self.room,
            {
                "maintenance_status": "Operational",
                "inventory_status": "Available",
                "occupancy_status": "Vacant",
                "housekeeping_status": "Clean",
            },
            update_modified=False,
        )
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def _ticket(self) -> str:
        return maintenance_service.create_ticket(
            property_name=self.property,
            title="Air conditioning dead",
            description="Reported by the guest",
            room=self.room,
            category="HVAC",
        )

    def _active_blocks(self) -> list[str]:
        """Every submitted, Active Room Block on the room, read fresh."""
        return frappe.get_all(
            BLOCK_DOCTYPE,
            filters={"room": self.room, "status": "Active", "docstatus": 1},
            pluck="name",
            order_by="creation asc",
        )

    def test_double_click_raises_one_block_and_release_leaves_none(self):
        """A retried take-out must not orphan a block that outlives the repair."""
        ticket = self._ticket()
        frappe.db.commit()

        results = run_workers(
            [
                Worker(
                    f"{__name__}._take_out_of_service_worker",
                    {"ticket": ticket, "room": self.room, "tag": "a", "partner": "b"},
                ),
                Worker(
                    f"{__name__}._take_out_of_service_worker",
                    {"ticket": ticket, "room": self.room, "tag": "b", "partner": "a"},
                ),
            ]
        )
        assert_all_ran(results)

        active = self._active_blocks()

        self.assertEqual(
            len(active),
            1,
            msg=(
                f"the room ended with {len(active)} Active Room Blocks {active} - a retried "
                f"take-out raised a second block for the same room"
            ),
        )

        referenced = frappe.db.get_value(TICKET_DOCTYPE, ticket, "room_block")
        self.assertEqual(
            referenced,
            active[0],
            msg=(
                f"the ticket references {referenced} but the room's only Active block is "
                f"{active[0]} - the referenced block was orphaned"
            ),
        )

        # And the room comes fully back into sale once the work is verified: the
        # release must leave no Active block stranded behind it.
        maintenance_service.start_work(ticket)
        maintenance_service.complete_work(ticket, notes="Compressor replaced")
        maintenance_service.verify_and_release(ticket, passed=True, notes="Cold air, signed off")
        frappe.db.commit()

        self.assertEqual(
            self._active_blocks(),
            [],
            msg="a Room Block stayed Active after the repair was verified - the room is stranded out of sale",
        )
