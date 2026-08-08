# Operations UAT — housekeeping, maintenance, guest services, kitchen

**Applies to:** Hospitality PMS 16.1.0 (branch `version-16`)

**Signed by:** Housekeeping Supervisor / Housekeeping Manager, Maintenance Manager, and Guest Relations staff.
**Governing baseline:** v1.2 approved document set (SAS = Software Architecture Specification, Workflow Matrix, Roles and Permissions Matrix, Decision Log).

Read [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md) first — it explains how to run a scenario, how to log a defect, and why a refusal is the pass in a negative scenario. This file only contains the scenarios themselves.

## Surfaces used in this set

| Area | Screen | Route |
|---|---|---|
| Housekeeping tasks and inspection | Housekeeping board | `/housekeeping` |
| Maintenance tickets, out-of-service, verification | Maintenance board | `/maintenance` |
| Guest requests, complaints, service recovery | Guest Services board | `/guest-services` |
| Room status, availability effect | Room Rack, Availability | `/rooms`, `/availability` |
| Kitchen requisitions, room service/minibar orders, wastage | **No `/pms` screen** | see the note below |

**A note on Kitchen.** Unlike housekeeping, maintenance and guest services, kitchen requisitions, room service/minibar orders and wastage have no page on the `/pms` frontend, and — this is the part worth being precise about — no Desk automation either. The `Hospitality Kitchen Requisition`, `Hospitality Room Service Order` and `Hospitality Wastage Entry` Desk forms carry no client script and their DocType controllers are empty (`pass`); creating a record with the ordinary Desk "New" button saves a bare row but does **not** run the pricing, stock-movement or idempotency logic under test. That logic exists only behind the whitelisted API methods in `hospitality_pms.api.kitchen`. Scenarios OPS-16 to OPS-19 call those methods directly (from a Desk page's browser console, or a REST client such as Postman) and then check the result in Desk. This is a genuine gap against the Administrator Guide's description of "the standard back-office screens" for kitchen — record it as a limitation, not a scenario failure, unless the call itself misbehaves.

---

## Housekeeping

### OPS-01  A checkout raises a cleaning task automatically

**Role:** Front Office Manager
**Precondition:** A stay is in house with a zero folio balance and ready to check out. Hospitality Settings > **Create Housekeeping Task on Checkout** is on (the default).
**Reference:** SAS section 3.9 (Checkout) and section 3.11 (Housekeeping).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the stay's Checkout screen (`/checkout/:stay`). Confirm the balance is zero and no blockers are listed. | The **Check out** button is enabled. |
| 2 | Click **Check out**. | A "Checked out" confirmation appears showing "The folio was settled and closed.", "The room was released to Vacant Dirty.", and "A departure clean task was raised (`<task>`)." Note the task name shown. |
| 3 | Go to Housekeeping (`/housekeeping`) for the same property, for today. | The task named in step 2 appears on the board: task type **Departure Clean**, priority **High**, status **Pending**, unassigned. |
| 4 | Open the task tile. | The detail dialog shows the same task type, priority and status, and the scheduled date is today's business date. |
| 5 | Repeat the same checkout a second time (if your test setup allows re-running it) or re-run the underlying create-task call for the same room/date. | No second task is created for the same room, type and date — the existing one is reused. |

**Pass criteria:** The task named in the checkout confirmation is the same task that appears on today's Housekeeping board with status Pending, and a repeat does not create a duplicate.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-02  Assign, start and complete a clean; the room follows every step

**Role:** Housekeeping Supervisor
**Precondition:** A Pending housekeeping task exists for a room whose Housekeeping status is Dirty (the task from OPS-01 is fine). Hospitality Settings > **Require Inspection Before Room Release** is on (the default) — this scenario deliberately runs with inspection required, so it ends at Inspection Pending, not Clean; OPS-03/OPS-04 continue from there.
**Reference:** SAS section 3.11; Workflow Matrix section 5 (Room / Housekeeping).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open Room Rack (`/rooms`), open the room. | Housekeeping dimension reads **Dirty**. |
| 2 | Open the task on the Housekeeping board. In **Actions**, enter a room attendant's user ID or email and click **Assign**. | Task status badge changes to **Assigned**; "Assigned to" shows the attendant. |
| 3 | Reopen the same room in Room Rack. | Housekeeping dimension is still **Dirty** — assigning a task does not move the room. |
| 4 | Back in the task dialog, click **Start**. | Task status becomes **In Progress**. |
| 5 | Reopen the room in Room Rack. | Housekeeping dimension is now **In Progress**. Its status log (bottom of the dialog) shows an entry "Cleaning started". |
| 6 | Back in the task, click **Complete**. In the Complete cleaning dialog, enter minutes spent (e.g. 25), leave every checkbox unticked, and click **Complete**. | Dialog closes without error. |
| 7 | Reopen the task. | Task status is **Inspection Pending** (not Completed), because this task requires inspection. |
| 8 | Reopen the room in Room Rack. | Housekeeping dimension is **Inspection Pending**, not Clean. The log shows "Cleaning complete". |

**Pass criteria:** The room's Housekeeping dimension moves Dirty → (unchanged on assign) → In Progress → Inspection Pending in lock-step with the task, with no step skipped and no premature "Clean".
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-03  A failed inspection sends the room back to Dirty

**Role:** Housekeeping Supervisor
**Precondition:** The task from OPS-02, currently Inspection Pending.
**Reference:** SAS section 3.11; Workflow Matrix section 5.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the task, click **Inspect**. | The Inspect room dialog opens with **Passed** highlighted by default. |
| 2 | Click **Failed**. | A warning appears: "A failed inspection sends this room back to Dirty and reopens the task." |
| 3 | Leave Notes empty and try to click **Confirm**. | The button stays disabled and the hint "Describe what needs to be redone." shows under Notes. |
| 4 | Type a note, e.g. "Bathroom mirror still smudged, redo dusting", then click **Confirm**. | Dialog closes without error. |
| 5 | Reopen the task. | Task status is **In Progress** (reopened), not Completed. |
| 6 | Open the room in Room Rack. | Housekeeping dimension is **Dirty**, not In Progress and not Inspection Pending. |

**Pass criteria:** A failed inspection with no note is refused on screen; once noted, it puts the task back to In Progress and the room back to Dirty — never a quiet pass.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** If this rule is ever bypassed client-side (for example, by calling the API directly with no note), the server refuses independently with: "A failed inspection needs a note saying what to redo."

---

### OPS-04  A passed inspection reaches Inspected

**Role:** Housekeeping Supervisor
**Precondition:** The task from OPS-03. Re-clean it: open the task, click **Start**, then click **Complete** (minutes optional, no checkboxes needed) so it returns to Inspection Pending.
**Reference:** SAS section 3.11; Workflow Matrix section 5.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the task (now Inspection Pending again), click **Inspect**. | **Passed** is highlighted by default; no warning shown. |
| 2 | Optionally add a note, click **Confirm**. | Dialog closes without error. |
| 3 | Reopen the task. | Task status is **Completed**. |
| 4 | Open the room in Room Rack. | Housekeeping dimension is **Inspected**. |
| 5 | In Desk, open **Hospitality Room Inspection**, filter by Housekeeping Task = this task. | A record exists: Result = Passed, Inspected By = you, linked to both the room and the task. |

**Pass criteria:** Passing an inspection completes the task, moves the room to Inspected, and leaves a permanent inspection record.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-05  Damage found during a clean raises a linked maintenance ticket

**Role:** Room Attendant
**Precondition:** A housekeeping task in **In Progress** for a room (assign and start a fresh Pending task if none is available).
**Reference:** SAS section 3.11 and section 3.12 (the automatic ticket bridges both).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the task, click **Complete**. Tick **Damage found**, leave "Describe the damage" empty, and try to click **Complete**. | The button stays disabled and "Damage notes are required when damage is found." is shown. |
| 2 | Enter a description, e.g. "Cracked bathroom tile near shower", leave the other boxes unticked, click **Complete**. | Dialog closes without error. |
| 3 | Reopen the task. | The completed section shows "Damage found: Cracked bathroom tile near shower". |
| 4 | Open Maintenance (`/maintenance`) for the same property. | A new ticket titled "Issue found while cleaning room `<room>`" appears: category **Other**, priority **High**, description matching the damage note. |
| 5 | In Desk, open the housekeeping task record and check the **Maintenance Ticket** field; open the ticket record and check **Source Housekeeping Task**. | Each links to the other — the dialog on screen does not surface this link, only Desk does. |

**Pass criteria:** Ticking damage found without a description is refused on screen; once completed with a description, a High-priority ticket is raised automatically and linked both ways to the task, with no separate step needed to report it.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-06  Record DND and service refused

**Role:** Room Attendant
**Precondition:** Two Pending or Assigned housekeeping tasks, for two different rooms.
**Reference:** SAS section 3.11; Workflow Matrix section 5.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open task A, click **Mark do not disturb**. | Task status becomes **DND**. |
| 2 | Open room A in Room Rack. | Housekeeping dimension is **DND**. |
| 3 | Open task B, click **Mark service refused**. | Task status becomes **Service Refused**. |
| 4 | Open room B in Room Rack. | Housekeeping dimension is **Service Refused**. |
| 5 | Reopen task A. | **Mark do not disturb** / **Mark service refused** are no longer offered, but **Assign** and **Start** are. |
| 6 | Click **Start** on task A. | Task status returns to **In Progress**; room A's Housekeeping dimension also moves to In Progress. |

**Pass criteria:** DND and Service Refused are recorded against the task and the room without cancelling the task, and either state can be resumed with Assign/Start once the guest is available.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Maintenance

### OPS-07  Raise a ticket, assign it, log work

**Role:** Maintenance Manager
**Precondition:** A room exists on the property.
**Reference:** SAS section 3.12; Workflow Matrix section 6.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open Maintenance (`/maintenance`), click **Create ticket**. Fill Title "AC not cooling", Description "Guest reports the unit blows warm air", Category **HVAC**, Priority **High**, Room = a room number. Click **Create**. | A new ticket appears on the board: status **Open**, priority **High**, category HVAC. |
| 2 | Open the ticket. In **Actions**, enter a technician's user ID or email and click **Assign**. | "Assigned to" shows the technician; status badge stays **Open** — assigning does not itself move the ticket. |
| 3 | Click **Start work**. | Status becomes **In Progress**. Open the room in Room Rack: Maintenance dimension is **Required**. |
| 4 | Leave "Work done" empty and try **Log work**. | The button stays disabled. |
| 5 | Enter "Replaced capacitor, unit now cooling", minutes 45, click **Log work**. | An entry appears in the work log with a timestamp and "(45m)". |

**Pass criteria:** Raising, assigning and logging work all succeed for a manager; assigning records who and when without changing ticket status; starting work sets the room's Maintenance status to Required.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** Assigning a ticket is restricted to Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator or System Manager — a Maintenance Technician cannot self-assign, though they can log work, start work and complete work on a ticket already assigned to them.

---

### OPS-08  Take a room out of service; availability drops and a room block exists

**Role:** Maintenance Manager
**Precondition:** An Open or In Progress ticket against a specific room. Note the room's Room Type.
**Reference:** Workflow Matrix section 6; Roles and Permissions Matrix section 4 (Sensitive Actions); SAS section 3.2 (Rooms).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | On Availability (`/availability`), search a date range covering today for the room's Room Type. Note the **Min available** figure. | A baseline number is recorded. |
| 2 | Open the ticket, click **Take out of service**. | Warning shown: "This removes the room from sale immediately. It cannot be sold again until it is verified and released." |
| 3 | Leave Status = **Out of Service** (the default), enter Reason "Structural crack in wall, engineer called", click **Take out of service**. | Dialog closes without error; the ticket now carries the "Out of service" flag. |
| 4 | Open the room in Room Rack. | Maintenance dimension is **Out of Service**; Inventory dimension is **Blocked**; the room tile shows the crossed-out icon and cannot be assigned. |
| 5 | Repeat the Availability search from step 1 for the same room type and dates. | **Min available** is exactly one lower than the baseline. |
| 6 | In Desk, open **Hospitality Room Block**, filter by Room = this room. | A submitted record exists: Status **Active**, Block Type **Maintenance**, covering today's business date to seven days later (or your chosen date), referencing this ticket. |

**Pass criteria:** Taking the room out of service creates a real, submitted, Active Room Block for that room, drops the room type's available count by exactly one, and sets the room's Maintenance and Inventory status to match — not just a flag on the room.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** Choosing **Out of Order** instead behaves identically except the Room Block's Block Type reads "Out of Order" — the system does not otherwise distinguish the two.

---

### OPS-09  A failed verification keeps the room out of sale

**Role:** Maintenance Manager
**Precondition:** The ticket from OPS-08. Log some work and click **Complete work** so it moves to Verification.
**Reference:** Workflow Matrix section 6.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the ticket (now "Awaiting verification"), click **Verify and release**. | Dialog opens with **Passed** highlighted by default. |
| 2 | Click **Failed**. | Warning shown: "The room stays out of sale and the ticket returns to In Progress." |
| 3 | Leave Notes empty and try **Confirm**. | Button stays disabled; hint "Describe what is still wrong." is shown. |
| 4 | Enter "Crack still visible, sealant not fully cured", click **Confirm**. | Dialog closes without error. |
| 5 | Reopen the ticket. | Status is **In Progress**, not Completed. |
| 6 | Open the room in Room Rack. | Maintenance dimension is still **Out of Service**; Inventory dimension is still **Blocked**. |
| 7 | In Desk, check the Room Block from OPS-08. | Status is still **Active** — not released. |

**Pass criteria:** A failed verification with no note is refused on screen; once noted, it returns the ticket to In Progress and leaves the room block Active and the room out of sale.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-10  A passed verification returns the room to sale

**Role:** Maintenance Manager
**Precondition:** The ticket from OPS-09. Log the completing work and click **Complete work** again to return it to Verification.
**Reference:** Workflow Matrix section 6.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | On Availability, search the same room type and dates as OPS-08. | **Min available** is still one lower than the original OPS-08 baseline. |
| 2 | Open the ticket, click **Verify and release**, leave **Passed** selected, optionally add a note, click **Confirm**. | Dialog closes without error. |
| 3 | Reopen the ticket. | Status is **Completed**. |
| 4 | Open the room in Room Rack. | Maintenance dimension is **Operational**; Inventory dimension is **Available** (unless something else also blocks the room). |
| 5 | In Desk, check the Room Block. | Status is **Released**, with Released On/By populated. |
| 6 | Repeat the Availability search. | **Min available** is back to the original OPS-08 baseline. |

**Pass criteria:** Passing verification completes the ticket, releases the room block, returns Maintenance to Operational and Inventory to Available, and restores the room type's available count.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-11  A technician cannot take a room out of service; a manager can

**Role:** Maintenance Technician, then Maintenance Manager
**Precondition:** An Open or In Progress ticket against a room that is not already out of service.
**Reference:** Roles and Permissions Matrix section 4 (Sensitive Actions).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Sign in as the Maintenance Technician. Open the ticket. | The **Take out of service** button is visible — the screen does not hide it from a technician. |
| 2 | Click it, choose Status = **Out of Service**, Reason = "Testing refusal", click **Take out of service**. | The request is refused. The error line reads exactly: "This action requires one of the following roles: Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator, System Manager." |
| 3 | Reopen the ticket. | Nothing changed: no out-of-service flag, no Room Block created, ticket status unchanged. |
| 4 | Sign in as the Maintenance Manager. Open the same ticket and repeat the identical action. | It succeeds: the ticket carries the "Out of service" flag and the room's status changes as in OPS-08. |

**Pass criteria:** The technician is refused with the exact role-requirement wording above and causes no side effect; the identical action by a manager succeeds.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Guest services

### OPS-12  Raising a request sets its SLA due time from priority

**Role:** Guest Relations Officer
**Precondition:** None beyond an active property.
**Reference:** SAS section 3.15 (Guest Requests / Complaints).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open Guest Services (`/guest-services`), click **Create request**. Type = Request, Priority = **Urgent**, Category = Housekeeping, Subject = "Extra pillows", Description = "Guest called reception asking for two extra pillows". Leave the SLA minutes field blank. Click **Create request**. | New row appears: priority Urgent, status Open, SLA column reads "Due in 15m" (counting down). |
| 2 | Repeat with Priority = **High**. | SLA reads "Due in 30m". |
| 3 | Repeat with Priority = **Normal**. | SLA reads "Due in 2h 0m". |
| 4 | Repeat with Priority = **Low**. | SLA reads "Due in 8h 0m". |

**Pass criteria:** Each request's due-by time matches the default target for its priority — Urgent 15 minutes, High 30, Normal 120, Low 480 — set from the moment it was raised.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** A specific number of minutes can be typed into "SLA minutes (optional)" on the create form to override the default for a single request; this is used deliberately in OPS-14.

---

### OPS-13  Assign and complete within SLA; no breach is flagged

**Role:** Guest Relations Officer
**Precondition:** A request raised with a comfortable SLA (Normal priority, or a custom SLA of 60 minutes).
**Reference:** SAS section 3.15; Workflow Matrix section 9 (Guest Request).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the request, click **Assign**, enter an assignee, click **Confirm**. | Status becomes **Assigned**. |
| 2 | Click **Start**. | Status becomes **In progress**. |
| 3 | Click **Complete**, enter Resolution "Pillows delivered to room", tick "Guest confirmed satisfied", click **Confirm** — well before the due time. | Dialog closes without error; status is **Completed**. |
| 4 | Go back to the Guest Services board. | This request is not counted in the **Overdue** tile. |
| 5 | In Desk, open the guest request record. | Field **Is Breached** is unchecked (0). |

**Pass criteria:** A request completed before its due-by time is never marked breached.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-14  An overdue request escalates, and the level rises

**Role:** Guest Relations Officer, with an Administrator or System Manager for step 4
**Precondition:** A request raised with SLA minutes = 1 (using the optional SLA field), left Open and unassigned.
**Reference:** SAS section 3.15; Workflow Matrix section 9.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Wait at least two minutes without touching the request. Reopen the Guest Services board. | The request shows in red, "Overdue by `<time>`", and is counted in the **Overdue** tile — this reading is computed live in the browser from the due-by time. |
| 2 | Reopen the request detail. | Status is still **Open** and Escalation level is still 0 — being visibly overdue does not, by itself, escalate the request. |
| 3 | Ask an Administrator/System Manager to run, from the bench console: `bench --site <site> execute hospitality_pms.services.guest_services.sweep_sla --kwargs "{'property_name': '<property>'}"`. | The command completes and reports one request checked and escalated. |
| 4 | Reopen the request. | Status is now **Escalated**, Escalation level is **1**, and the escalation note reads "SLA target passed". |
| 5 | Run the identical bench command again immediately. | It completes without error. |
| 6 | Reopen the request. | Escalation level is still **1**, not 2 — a request already escalated at its current level is not escalated again by the same pass. |

**Pass criteria:** Once the sweep runs, an overdue request is escalated exactly once per pass, with the level rising by one and not compounding on a repeat run.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** `hooks.py` registers `scheduler_events = {}` — nothing in the current build calls `sweep_sla` on its own; it must be triggered manually as in step 3. Log this as a limitation (the guide describes it as "a scheduled job [that] periodically checks", which does not yet reflect the build) rather than a failure of steps 3–6, provided the manual run behaves as expected.

---

### OPS-15  Service recovery posts a discount once, never twice

**Role:** Guest Relations Officer
**Precondition:** A Complaint request exists, linked to a stay with an open folio.
**Reference:** Roles and Permissions Matrix section 4 (Sensitive Actions); SAS section 3.15.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the request, click **Service recovery**. Recovery type = Discount, Amount = 25.00, Reason = "Room was noisy, offered discount as apology". | A warning appears: "An amount greater than zero posts a discount to the guest's folio.", with a checkbox "I understand this posts a discount of `<25.00>` to the guest's folio." |
| 2 | Try clicking **Apply recovery** without ticking that checkbox. | The button stays disabled. |
| 3 | Tick the checkbox, click **Apply recovery**. | Dialog closes without error. |
| 4 | Open the guest's Folio. | A new charge line: type **Discount**, description "Service recovery for request `<request>`: Discount", amount **-25.00** (discounts are stored negative). |
| 5 | Repeat steps 1–3 exactly (same type, amount and reason) as if the approval had been clicked twice by mistake. | Dialog closes without error — no error is shown for the repeat. |
| 6 | Reopen the Folio. | Still exactly **one** Discount line for this request — the repeat did not add a second charge. |

**Pass criteria:** An amount-bearing recovery cannot be submitted without the explicit on-screen confirmation, posts exactly one Discount line to the folio, and approving the same recovery again does not discount the guest a second time.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Kitchen

These four scenarios have no `/pms` screen and no working Desk button — see the note at the top of this document. Steps call the whitelisted API methods directly. A Kitchen Manager or Food and Beverage Manager has Desk access and can run these from a Desk page's browser console with `frappe.call({...})`; a Kitchen User does not have Desk access at all (see OPS-19).

### OPS-16  Raise and issue a requisition; stock moves once

**Role:** Kitchen Manager
**Precondition:** The property has warehouse mappings for **General Store** and **Kitchen Store** (Hospitality Property > Warehouses), and the General Store holds stock of at least one item.
**Reference:** SAS section 3.16 (Kitchen / Room Service / Minibar); Decision Log HPMS-DEC-002 (ERPNext owns the stock ledger).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Call `hospitality_pms.api.kitchen.create_requisition` with `property`, and `lines` = `[{"item": "<item-code>", "quantity": 5}]`. | Response shows `requisition_status` = **Submitted** (never left at Draft), `from_warehouse`/`to_warehouse` auto-filled to the property's mapped stores. Note the requisition name. |
| 2 | In Desk, open **Hospitality Kitchen Requisition**, open that record. | Status **Submitted**; Stock Entry field still empty. |
| 3 | Call `hospitality_pms.api.kitchen.issue_requisition` with that requisition name. | Response shows a new `stock_entry` name and `duplicate: false`; requisition status becomes **Issued**. |
| 4 | In Desk, open Stock > Stock Entry, open that entry. | A submitted **Material Transfer** moving 5 of the item from the General Store to the Kitchen Store. |
| 5 | Call `issue_requisition` again with the same requisition name. | Response returns the **same** `stock_entry` name with `duplicate: true`; the Stock Entry list still shows only one entry for this requisition. |

**Pass criteria:** Issuing a requisition creates exactly one submitted Stock Entry transferring the requested quantity, and issuing it again returns the original entry instead of moving stock a second time.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-17  A room service order is priced from the menu, not the caller

**Role:** Kitchen Manager
**Precondition:** An in-house stay with an open folio; an active Hospitality Menu Item with a known selling rate (e.g. a QAR 45.00 item).
**Reference:** SAS section 3.16.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Call `hospitality_pms.api.kitchen.create_order` with `property`, `stay`, `order_type` = "Room Service", and `lines` = `[{"menu_item": "<code>", "quantity": 2, "rate": 1}]` — deliberately including a low `rate` the server does not accept as an argument. | Response `total_amount` = 2 × the menu item's real selling rate (e.g. 90.00), never 2 × 1. The returned line's `rate` equals the menu's selling rate. |
| 2 | In Desk, open **Hospitality Room Service Order**, open the new order. | Same figures stored on the record; `order_status` = **Placed**. |

**Pass criteria:** The order total is computed entirely from the menu item's own selling rate, regardless of any rate supplied in the call.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-18  Delivering an order charges the folio exactly once

**Role:** Kitchen Manager
**Precondition:** The order from OPS-17, still Placed.
**Reference:** SAS section 3.16.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Call `set_order_status` with status "Preparing". | `order_status` updates to Preparing. |
| 2 | Call `hospitality_pms.api.kitchen.deliver_order` with the order name. | Response shows `order_status` = **Delivered**, a populated `folio_charge`, `duplicate: false`. |
| 3 | Open the guest's Folio. | A new charge line: type **Room Service**, description "Room Service order `<order>`", amount equal to the order's total. |
| 4 | Call `deliver_order` again with the same order name. | Response returns the **same** `folio_charge` with `duplicate: true`. |
| 5 | Reopen the Folio. | Still exactly one Room Service line for this order. |

**Pass criteria:** Delivering an order posts exactly one folio charge for the menu-priced total, and delivering it again never adds a second charge.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### OPS-19  A kitchen user cannot record wastage; a manager can

**Role:** Kitchen User, then Kitchen Manager
**Precondition:** A stock item with quantity on hand in the Kitchen Store warehouse (e.g. from OPS-16).
**Reference:** SAS section 3.16; Roles and Permissions Matrix section 3 (Functional Matrix) and section 4 (Sensitive Actions).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | As the Kitchen User — who has no Desk access and no `/pms` screen for this — call `hospitality_pms.api.kitchen.record_wastage` directly (REST client, using the session from signing in at `/pms`) with `property`, `item`, `quantity`: 1, `reason`: "Spoilage", `notes`: "UAT refusal test". | Refused before the wastage rule itself is even reached, with: "You are not permitted to create Hospitality Wastage Entry." No Wastage Entry or Stock Entry is created. |
| 2 | Repeat the identical call as the Kitchen Manager. | Succeeds. Response includes `wastage.name`, a new `stock_entry` (Material Issue), and `wastage.estimated_value`. |
| 3 | In Desk, open **Hospitality Wastage Entry**, open the new record. | Recorded By and Approved By both show the Kitchen Manager; Stock Entry links to the Material Issue from step 2. |
| 4 | As the Kitchen Manager, repeat the call with `notes` left blank. | Refused with: "Wastage must be explained." |

**Pass criteria:** The Kitchen User is refused with the DocType-permission message above before any role check runs; the Kitchen Manager succeeds and the resulting entry carries a genuine Stock Entry; an unexplained wastage is refused regardless of role.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**
