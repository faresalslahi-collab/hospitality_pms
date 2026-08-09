# Journey D — Look after the guest in house

**Applies to:** Hospitality PMS 16.2.0
**Signed by:** Housekeeping Manager, Maintenance Manager, Front Office Manager (one signature per section)
**Surface:** `/pms`, with Desk and direct API calls where a step says so.

The longest journey, because it is the longest part of the guest's stay. It runs
in six sections: the folio, housekeeping, maintenance, guest services, the
kitchen, and the changes a stay needs while the guest is still here. Each section can be signed separately, and each is signed by the
department that owns it.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journey C passed. At least one in-house
stay with an open folio, and the room number and folio number recorded at the
end of Journey C.

**Test data to prepare:**

- The in-house stay and folio from **C-09**.
- PMS Settings → **Create Housekeeping Task on Checkout** on (default), and **Require Inspection Before Room Release** on (default). Confirm both in Desk before starting the housekeeping section.
- For the kitchen section: warehouse mappings for **General Store** and **Kitchen Store** on the property, stock on hand in the General Store, and one active **Menu Item** with a known selling rate.

---

## Section D.1 — The folio · signed by Front Office Manager

### D-01 · The in-house board is the house list

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/in-house` |
| **Prerequisites** | At least one checked-in guest |
| **Test data** | The stay from C-09 |
| **Severity if failed** | High — the desk cannot see who is in the hotel |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **In House**. | Tiles: In house, Due out, Adults, Children. A table of stays ordered by room. |
| 2 | Find your guest. | Room, guest name, arrival, departure, party size, status, rate. |
| 3 | Compare the **In house** tile to the dashboard's In-house rooms figure. | They agree. |
| 4 | Click the **Folio** link on the row. | The guest's folio opens. |
| 5 | Go back and click **Checkout**. | The checkout screen opens for that stay. Do not complete it — Journey E does. |

**Pass criteria:** Every in-house guest is listed once, and both onward links work.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-02 · Post a charge and take a payment

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/folios/<folio>` |
| **Prerequisites** | An open folio (C-09). A charge type mapped in A-06. |
| **Test data** | One charge of a known amount, one payment of a smaller amount |
| **Severity if failed** | **Critical** — the hotel cannot bill or take money |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the folio. | Charges, payments and a running balance. |
| 2 | Note the current balance. | Call it **B**. |
| 3 | Click **Post charge**. Choose a charge type, enter a description, quantity and unit price, and post. | A new charge line appears with your description and amount. |
| 4 | Re-read the balance. | Increased by the charge total, including any tax the server calculated. **Confirm the tax was calculated by the server, not typed by you.** |
| 5 | Click **Post payment**. Enter an amount smaller than the balance, choose a method, and post. | A payment line appears. |
| 6 | Re-read the balance. | Reduced by exactly the payment amount. |
| 7 | Read the totals block. | Total charges, total taxes, total payments and balance are internally consistent. |

**Pass criteria:** Charges and payments post, and the balance is arithmetically correct after each.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-03 · A posted charge can be reversed, never edited

| | |
|---|---|
| **Role** | Front Office Agent, then Finance Manager |
| **Surface** | `/pms/folios/<folio>` and Desk |
| **Prerequisites** | The charge posted in D-02 |
| **Test data** | None |
| **Severity if failed** | **Critical** — an editable posted charge means the subledger cannot be reconciled and revenue can be altered after the fact |

| # | Step | Expected result |
|---|---|---|
| 1 | On the folio, look for any way to edit or delete the posted charge as the **agent**. | None offered. |
| 2 | Open the folio in **Desk** and try to change the charge line's amount, then save. | Refused. |
| 3 | Try to delete the charge row in Desk and save. | Refused. |
| 4 | Back in `/pms`, look for a **Reverse** action on the charge as the agent. | Either not offered, or offered and refused by the server — an agent must not be able to reverse. |
| 5 | Sign in as **Finance Manager** and reverse the charge, leaving the reason blank. | Refused — a reason is mandatory. |
| 6 | Enter a reason and reverse. | A **new** reversing line appears. The original line remains, marked reversed. |
| 7 | Re-read the balance. | Net effect of the pair is zero. |

**Pass criteria:** The original charge is never altered or removed; a reversal is a new line, requires a reason, and is restricted to finance.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-04 · Split company-pay charges onto a company folio

| | |
|---|---|
| **Role** | Front Office Manager or Finance Manager |
| **Surface** | `/pms/folios/<folio>` |
| **Prerequisites** | A folio with at least two charges, one of which the company would pay |
| **Test data** | The folio from D-02 with a second charge added |
| **Severity if failed** | High — corporate guests cannot be billed correctly and the guest is asked to pay the company's share |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the folio and click **Split folio**. | A dialog listing the charge lines with selection. |
| 2 | Select one charge, set the payer to **Company**, and confirm. | A second folio is created. |
| 3 | Read the original folio. | The selected charge is gone from it and its balance has fallen by that amount. |
| 4 | Open the new company folio. | It carries exactly that charge, with folio type reflecting the split. |
| 5 | Confirm both folios link to the same stay. | They do. |
| 6 | Add the two balances together. | The total equals the original folio's balance before the split. Nothing was created or destroyed — it moved. |

**Pass criteria:** Charges move between folios without changing the total owed, and both folios remain attached to the stay.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Section D.2 — Housekeeping · signed by Housekeeping Manager

### D-05 · A checkout raises a cleaning task by itself

| | |
|---|---|
| **Role** | Front Office Manager |
| **Surface** | `/pms/checkout/<stay>` then `/pms/housekeeping` |
| **Prerequisites** | An in-house stay with a **zero** folio balance, ready to check out. PMS Settings → Create Housekeeping Task on Checkout is on. |
| **Test data** | Use a second in-house stay if you want to keep C-09's guest for Journey E |
| **Severity if failed** | High — rooms are checked out and never cleaned because nobody was told |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the checkout screen and confirm the balance is zero and no blockers are listed. | **Check out** is enabled. |
| 2 | Click **Check out**. | A confirmation naming three things: the folio was settled and closed, the room was released to Vacant Dirty, and a departure clean task was raised. Note the task name. |
| 3 | Open **Housekeeping** for today. | That task is on the board: type **Departure Clean**, priority **High**, status **Pending**, unassigned. |
| 4 | Open the task tile. | Same type, priority and status; scheduled date is today's business date. |
| 5 | Check the room on the **Room Rack**. | Occupancy **Vacant**, Housekeeping **Dirty**. |

**Pass criteria:** The task named in the checkout confirmation is the same task on today's board, and the room is Vacant Dirty.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-06 · The room follows the clean, step for step

| | |
|---|---|
| **Role** | Housekeeping Supervisor |
| **Surface** | `/pms/housekeeping` and `/pms/rooms` |
| **Prerequisites** | The Pending task from D-05, on a room that is Dirty. Require Inspection Before Room Release is **on**, so this ends at Inspection Pending, not Clean. |
| **Test data** | A Room Attendant's user ID to assign to |
| **Severity if failed** | High — the rack lies about which rooms are sellable |

| # | Step | Expected result |
|---|---|---|
| 1 | On the Room Rack, open the room. | Housekeeping reads **Dirty**. |
| 2 | Open the task, enter a room attendant and click **Assign**. | Task becomes **Assigned**; "Assigned to" shows the attendant. |
| 3 | Re-open the room on the rack. | Still **Dirty** — assigning a task does not move the room. |
| 4 | Click **Start** on the task. | Task becomes **In Progress**. |
| 5 | Re-open the room. | Housekeeping is **In Progress**, and the room's status log shows "Cleaning started". |
| 6 | Click **Complete**, enter minutes spent, leave the checkboxes unticked, confirm. | Closes without error. |
| 7 | Re-open the task. | Status is **Inspection Pending** — not Completed. |
| 8 | Re-open the room. | Housekeeping is **Inspection Pending**, not Clean. The log shows "Cleaning complete". |

**Pass criteria:** The room moves Dirty → (unchanged on assign) → In Progress → Inspection Pending in lock-step with the task, with no step skipped and no premature Clean.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-07 · A failed inspection sends the room back to Dirty

| | |
|---|---|
| **Role** | Housekeeping Supervisor |
| **Surface** | `/pms/housekeeping` |
| **Prerequisites** | The task from D-06, at Inspection Pending |
| **Test data** | None |
| **Severity if failed** | **Critical** — a room that failed inspection would be sold as clean |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the task and click **Inspect**. | The dialog opens with **Passed** highlighted by default. |
| 2 | Click **Failed**. | A warning appears saying a failed inspection sends the room back to Dirty and reopens the task. |
| 3 | Leave Notes empty and try to confirm. | The confirm button stays disabled, with a hint asking what needs redoing. |
| 4 | Type a note describing the fault, and confirm. | Closes without error. |
| 5 | Re-open the task. | Status is **In Progress** — reopened, not Completed. |
| 6 | Open the room on the rack. | Housekeeping is **Dirty**. |

**Pass criteria:** A failed inspection cannot be recorded without a note, and it returns both the task and the room to their unfinished state.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-08 · A passed inspection reaches Inspected and leaves a record

| | |
|---|---|
| **Role** | Housekeeping Supervisor |
| **Surface** | `/pms/housekeeping`, `/pms/rooms`, Desk |
| **Prerequisites** | The task from D-07. Re-clean it first: Start, then Complete, so it returns to Inspection Pending. |
| **Test data** | None |
| **Severity if failed** | Medium — the room becomes sellable either way; the audit trail is what is lost |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the task and click **Inspect**. | **Passed** is highlighted; no warning shown. |
| 2 | Optionally add a note, and confirm. | Closes without error. |
| 3 | Re-open the task. | Status is **Completed**. |
| 4 | Open the room on the rack. | Housekeeping is **Inspected**. |
| 5 | In Desk, open **Room Inspection** filtered by this task. | A record exists: result Passed, inspected by you, linked to both the room and the task. |

**Pass criteria:** Passing completes the task, moves the room to Inspected, and leaves a permanent inspection record.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-09 · Damage found during a clean raises a linked maintenance ticket

| | |
|---|---|
| **Role** | Room Attendant or Housekeeping Supervisor |
| **Surface** | `/pms/housekeeping` |
| **Prerequisites** | A housekeeping task In Progress |
| **Test data** | A description of the fault |
| **Severity if failed** | High — faults found in the room never reach maintenance |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the task and click **Complete**. | The complete dialog offers a **maintenance required** option. |
| 2 | Tick it and describe the fault. | The field accepts the description. |
| 3 | Confirm. | Closes without error. |
| 4 | Open **Maintenance**. | A new ticket exists for that room carrying your description. |
| 5 | Re-open the housekeeping task. | It links to the ticket just raised. |

**Pass criteria:** One action by the attendant produces a real maintenance ticket linked back to the clean.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-10 · Do not disturb, and service refused

| | |
|---|---|
| **Role** | Room Attendant |
| **Surface** | `/pms/housekeeping` |
| **Prerequisites** | A task on an occupied room |
| **Test data** | None |
| **Severity if failed** | Medium — the attendant has no way to explain an uncleaned room |

| # | Step | Expected result |
|---|---|---|
| 1 | Open a task and record **Do not disturb**. | The task shows DND. |
| 2 | Check the room on the rack. | Housekeeping reads **DND**. |
| 3 | On another task, record **service refused**. | The task and the room both read Service Refused. |
| 4 | Confirm neither is treated as a completed clean. | Neither room reads Clean or Inspected. |

**Pass criteria:** DND and service refused are recorded as their own outcomes and never as a finished clean.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Section D.3 — Maintenance · signed by Maintenance Manager

### D-11 · Raise a ticket, assign it, log the work

| | |
|---|---|
| **Role** | Maintenance Manager |
| **Surface** | `/pms/maintenance` and `/pms/rooms` |
| **Prerequisites** | A room exists |
| **Test data** | A technician's user ID |
| **Severity if failed** | High — faults are not tracked |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Maintenance** and click **Create ticket**. Fill title, description, category, priority High, and a room. Create. | The ticket appears on the board: status **Open**, priority High. |
| 2 | Open it, enter a technician and click **Assign**. | "Assigned to" shows the technician; status stays **Open** — assigning does not itself move the ticket. |
| 3 | Click **Start work**. | Status becomes **In Progress**. |
| 4 | Open that room on the rack. | Maintenance dimension is **Required**. |
| 5 | Leave "Work done" empty and try **Log work**. | The button stays disabled. |
| 6 | Enter the work done and minutes, and log it. | An entry appears in the work log with a timestamp and the minutes. |

**Pass criteria:** The ticket lifecycle works, assignment records who without changing status, and starting work marks the room as needing attention.

**Note:** Assignment is restricted to Maintenance Manager and above. A technician cannot self-assign but can start, log and complete work on a ticket already assigned to them.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-12 · Taking a room out of service really removes it from sale

| | |
|---|---|
| **Role** | Maintenance Manager |
| **Surface** | `/pms/maintenance`, `/pms/availability`, `/pms/rooms`, Desk |
| **Prerequisites** | An Open or In Progress ticket against a specific room. Note the room's room type. |
| **Test data** | None |
| **Severity if failed** | **Critical** — a room with a structural fault would still be sold |

| # | Step | Expected result |
|---|---|---|
| 1 | On **Availability**, search a range covering today for that room type. Note the minimum available figure — the **baseline**. | Recorded. |
| 2 | Open the ticket and click **Take out of service**. | A warning that this removes the room from sale immediately and it cannot be sold until verified and released. |
| 3 | Leave status at **Out of Service**, enter a reason, and confirm. | Closes without error; the ticket carries the out-of-service flag. |
| 4 | Open the room on the rack. | Maintenance is **Out of Service**, Inventory is **Blocked**, the tile is marked and not assignable. |
| 5 | Repeat the availability search. | Minimum available is exactly **one lower** than the baseline. |
| 6 | In Desk, open **Room Block** filtered by that room. | A **submitted**, **Active** block exists, of type Maintenance, covering the date range, referencing this ticket. |

**Pass criteria:** A real, submitted, Active room block exists; availability falls by exactly one; and the room's Maintenance and Inventory statuses both move — not just a flag on the ticket.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-13 · A failed verification keeps the room out of sale

| | |
|---|---|
| **Role** | Maintenance Manager |
| **Surface** | `/pms/maintenance`, `/pms/rooms`, Desk |
| **Prerequisites** | The ticket from D-12. Log work and click **Complete work** so it moves to Verification. |
| **Test data** | None |
| **Severity if failed** | **Critical** — an unrepaired room returns to sale |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the ticket and click **Verify and release**. | Dialog opens with **Passed** highlighted by default. |
| 2 | Click **Failed**. | Warning: the room stays out of sale and the ticket returns to In Progress. |
| 3 | Leave notes empty and try to confirm. | Refused, with a hint asking what is still wrong. |
| 4 | Enter a note and confirm. | Closes without error. |
| 5 | Re-open the ticket. | Status is **In Progress**. |
| 6 | Check the room and the room block. | Maintenance still Out of Service, Inventory still Blocked, block still **Active**. |

**Pass criteria:** A failed verification needs a note, and leaves the room out of sale.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-14 · A passed verification returns the room to sale

| | |
|---|---|
| **Role** | Maintenance Manager |
| **Surface** | `/pms/maintenance`, `/pms/availability`, `/pms/rooms`, Desk |
| **Prerequisites** | The ticket from D-13. Log the completing work and click Complete work again to return it to Verification. |
| **Test data** | The baseline figure from D-12 |
| **Severity if failed** | High — a repaired room stays unsellable and revenue is lost |

| # | Step | Expected result |
|---|---|---|
| 1 | Re-run the availability search from D-12. | Still one lower than the baseline. |
| 2 | Open the ticket, click **Verify and release**, leave **Passed**, confirm. | Closes without error. |
| 3 | Re-open the ticket. | Status **Completed**. |
| 4 | Open the room on the rack. | Maintenance **Operational**, Inventory **Available** — unless something else independently blocks it. |
| 5 | In Desk, check the room block. | Status **Released**, with released-on and released-by filled in. |
| 6 | Re-run the availability search. | Back to the D-12 baseline. |

**Pass criteria:** Passing verification completes the ticket, releases the block, restores both statuses and restores availability.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-15 · A technician cannot take a room out of service; a manager can

| | |
|---|---|
| **Role** | Maintenance Technician, then Maintenance Manager |
| **Surface** | `/pms/maintenance` |
| **Prerequisites** | An Open or In Progress ticket on a room that is not already out of service |
| **Test data** | None |
| **Severity if failed** | **Critical** — a permission boundary crossed; anyone could pull rooms out of sale |

| # | Step | Expected result |
|---|---|---|
| 1 | Sign in as the **technician** and open the ticket. | The **Take out of service** button is visible — the screen does not hide it. |
| 2 | Click it, choose Out of Service, enter a reason and submit. | **Refused**, with a message naming the roles this action requires. |
| 3 | Re-open the ticket. | Nothing changed: no flag, no room block, status unchanged. |
| 4 | Check the room on the rack. | Unchanged. |
| 5 | Sign in as the **Maintenance Manager** and repeat the identical action. | Succeeds, and the room changes as in D-12. |

**Pass criteria:** The technician is refused **and causes no side effect**; the identical action by a manager succeeds.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Section D.4 — Guest services · signed by Front Office Manager

### D-16 · A request's due time comes from its priority

| | |
|---|---|
| **Role** | Guest Relations Officer |
| **Surface** | `/pms/guest-services` |
| **Prerequisites** | An active property |
| **Test data** | Four requests, one at each priority |
| **Severity if failed** | Medium — requests still work; the SLA promise is what is lost |

| # | Step | Expected result |
|---|---|---|
| 1 | Click **Create request**. Priority **Urgent**, any category and subject. Leave the SLA minutes field blank. Create. | The row shows status Open and an SLA reading **due in 15m**, counting down. |
| 2 | Repeat at **High**. | Due in **30m**. |
| 3 | Repeat at **Normal**. | Due in **2h**. |
| 4 | Repeat at **Low**. | Due in **8h**. |
| 5 | Create one more with a typed SLA of 60 minutes. | Due in 1h — the typed value overrides the default. |

**Pass criteria:** Each default matches its priority — 15 / 30 / 120 / 480 minutes — measured from when the request was raised.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-17 · Completed inside the SLA is never flagged as breached

| | |
|---|---|
| **Role** | Guest Relations Officer |
| **Surface** | `/pms/guest-services`, Desk |
| **Prerequisites** | A request with a comfortable SLA (Normal, or a typed 60 minutes) |
| **Test data** | None |
| **Severity if failed** | Medium — SLA reporting becomes untrustworthy |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the request, **Assign** it to someone, confirm. | Status **Assigned**. |
| 2 | Click **Start**. | Status **In progress**. |
| 3 | Well before the due time, click **Complete**, enter a resolution, tick guest satisfied, confirm. | Status **Completed**. |
| 4 | Return to the board. | The request is **not** counted in the Overdue tile. |
| 5 | In Desk, open the request record. | **Is Breached** is unticked. |

**Pass criteria:** A request finished before its due time is never marked breached.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-18 · An overdue request escalates

| | |
|---|---|
| **Role** | Guest Relations Officer, with an administrator for the escalation step |
| **Surface** | `/pms/guest-services` |
| **Prerequisites** | A request raised with a typed SLA of **1 minute**, left Open and unassigned |
| **Test data** | None |
| **Severity if failed** | High — complaints go cold with nobody told |

| # | Step | Expected result |
|---|---|---|
| 1 | Create the request with SLA 1 minute. | It appears, due in 1m. |
| 2 | Wait until the due time passes and refresh. | The request shows as overdue and is counted in the **Overdue** tile. |
| 3 | Escalate it. | Status becomes **Escalated** and the escalation level rises. |
| 4 | Escalate again. | The level rises again rather than staying put. |
| 5 | In Desk, open the record. | Is Breached is ticked, and the escalation level matches what you saw. |

**Pass criteria:** Breach is detected, escalation works, and repeated escalation raises the level rather than doing nothing.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-19 · Service recovery discounts the guest once, never twice

| | |
|---|---|
| **Role** | Guest Relations Officer |
| **Surface** | `/pms/guest-services` and `/pms/folios/<folio>` |
| **Prerequisites** | A **Complaint** request linked to a stay with an open folio |
| **Test data** | A recovery amount of a known value |
| **Severity if failed** | **Critical** — the hotel gives away money twice |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the request and click **Service recovery**. Choose Discount, enter the amount and a reason. | A warning appears that an amount greater than zero posts a discount to the guest's folio, with a confirmation checkbox naming the amount. |
| 2 | Try to apply without ticking the checkbox. | The button stays disabled. |
| 3 | Tick and apply. | Closes without error. |
| 4 | Open the guest's folio. | Exactly one new line: type **Discount**, description naming the request, amount **negative**. |
| 5 | Repeat steps 1–3 identically, as if the button had been clicked twice. | Closes without error — no error is shown for the repeat. |
| 6 | Re-open the folio. | Still exactly **one** Discount line for this request. |

**Pass criteria:** The recovery cannot be applied without explicit confirmation, posts exactly one discount, and a repeat never discounts a second time.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Section D.5 — Room service and the kitchen · signed by Front Office Manager with Kitchen Manager

> **Room service has its own screen** at `/pms/kitchen`, added in 16.3.0, so a
> waiter or a receptionist can take an order without an API client. Requisitions
> and wastage stay in Desk and the API: moving stock between stores is a stores
> job, not a waiter's, and both roles that do it have Desk.

### D-20 · The room service board is a queue

| | |
|---|---|
| **Role** | Kitchen User (or Food and Beverage Manager) |
| **Surface** | `/pms/kitchen` |
| **Prerequisites** | At least one in-house stay with an open folio |
| **Test data** | One active **Menu Item** flagged available for room service, with a known selling rate |
| **Severity if failed** | **High** — the kitchen cannot see what it has to cook |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Room Service** from the Rooms and service section of the sidebar. | A board with tiles: Open, Placed, Preparing, Ready, Open value. |
| 2 | Read the columns. | Order, Room, Guest, Type, Items, Placed, Status, Total. |
| 3 | Check the row order. | **Oldest first.** The order that has waited longest is at the top, because that is the one to cook next. |
| 4 | Tick **Include delivered**. | Delivered and cancelled orders join the list; the board reloads. |
| 5 | Untick it. | Only open orders again. |
| 6 | Use the filter: Placed, then Preparing, then Ready, then Delivered. | Each row count matches its matching tile. |
| 7 | Check **Open value**. | A money figure — the value of everything not yet delivered. |

**Pass criteria:** Every open order is listed once, oldest first, and the tiles agree with the rows.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-21 · Take an order, and the menu sets the price

| | |
|---|---|
| **Role** | Front Office Agent (the phone rings at reception) or Kitchen User |
| **Surface** | `/pms/kitchen` |
| **Prerequisites** | D-20 passed. An in-house stay with an open folio. |
| **Test data** | The menu item and its **real selling rate** — write it here: `________` |
| **Severity if failed** | **Critical** — a screen that let staff set their own price would give the hotel's food away |

| # | Step | Expected result |
|---|---|---|
| 1 | Click **Take an order**. | A dialog opens. |
| 2 | Read the guest selector. | It lists **in-house guests only**, by room and name, and explains that an order is charged to the guest's folio. |
| 3 | Confirm there is **no price field anywhere on the form**. | There is none. Item and quantity only. This is the point of the scenario. |
| 4 | Choose a guest, leave order type at **Room Service**, pick the menu item, set quantity 2. | The item's own price is shown beside its name, for you to read to the guest. |
| 5 | Switch order type to **Minibar**. | The item list reloads for that type, and your chosen line is cleared rather than left pointing at an item that type cannot sell. |
| 6 | Switch back to Room Service, re-pick the item, quantity 2, and add a second line. | Both lines accepted. |
| 7 | Place the order. | A confirmation appears and the order joins the board as **Placed**. |
| 8 | Open the order and read the total. | Quantity × the menu's rate — exactly 2 × the rate you wrote down. |
| 9 | Check the folio. | **Nothing has been charged yet.** An order that has not been delivered is not a charge. |

**Pass criteria:** The order is priced entirely from the menu, no price can be typed, and placing an order charges nothing.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-22 · Cook it, deliver it, and charge the guest exactly once

| | |
|---|---|
| **Role** | Kitchen User, then whoever delivers |
| **Surface** | `/pms/kitchen` |
| **Prerequisites** | The order from D-21, still Placed. Stock on hand for the item, if it is a stocked item — see the note below. |
| **Test data** | The folio balance before delivery: `________` |
| **Severity if failed** | **Critical** — the guest is billed twice for one tray |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the order from the board. | Its lines, quantities, rates and total, with the guest's room and the time it was placed. |
| 2 | Click **Start preparing**. | Status becomes Preparing; the board tile moves. |
| 3 | Click **Mark ready**. | Status becomes Ready. |
| 4 | Read the line beneath the **Deliver and charge** button. | It names the exact amount that will be posted to the guest's folio. |
| 5 | Click **Deliver and charge**. | Status becomes Delivered and a note confirms the folio was charged. |
| 6 | Open the guest's folio. | Exactly **one** new line, of type Room Service, for the order's total. |
| 7 | Go back to the order and click **Deliver and charge** again if it is still offered; otherwise re-open the order. | No second charge is possible. |
| 8 | Re-open the folio. | Still exactly **one** line for this order. |
| 9 | Note what happens if the item is stocked and the store is empty. | The delivery is **refused** and nothing is charged — the guest is not billed for something the kitchen could not issue. Record the wording: an ERPNext stock message here is a **Medium** usability finding, not a correctness one. |

**Pass criteria:** Delivery charges the folio once and only once, and a failed delivery charges nothing at all.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-23 · A requisition moves stock exactly once

| | |
|---|---|
| **Role** | Kitchen Manager |
| **Surface** | Desk + API — there is no `/pms` screen for stores movements, by design |
| **Prerequisites** | Property warehouse mappings for General Store and Kitchen Store; stock on hand in the General Store |
| **Test data** | One stock item code and a quantity of 5 |
| **Severity if failed** | High — kitchen stock is wrong, or double-issued |

| # | Step | Expected result |
|---|---|---|
| 1 | Call `kitchen.create_requisition` with the property and one line of 5 units. | Status **Submitted** — never left at Draft — with warehouses filled from the property mapping. Note the name. |
| 2 | In Desk, open the requisition. | Status Submitted; Stock Entry still empty. |
| 3 | Call `kitchen.issue_requisition`. | A stock entry name is returned with `duplicate: false`; status becomes **Issued**. |
| 4 | In Desk, open that Stock Entry. | A submitted **Material Transfer** of 5 units, General Store → Kitchen Store. |
| 5 | Call `issue_requisition` **again**. | The **same** stock entry is returned with `duplicate: true`. |
| 6 | Re-check the Stock Entry list. | Still exactly one entry. |

**Pass criteria:** Issuing creates exactly one submitted Stock Entry, and issuing again returns the original rather than moving stock twice.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-24 · A kitchen user cannot write off stock; a manager can, with a reason

| | |
|---|---|
| **Role** | Kitchen User, then Kitchen Manager |
| **Surface** | Desk + API |
| **Prerequisites** | Stock on hand in the Kitchen Store (from D-23) |
| **Test data** | One item and a quantity of 1 |
| **Severity if failed** | **Critical** — stock can be written off by anyone, untraceably |

| # | Step | Expected result |
|---|---|---|
| 1 | As the **Kitchen User**, call `kitchen.record_wastage` with an item, quantity 1, a reason and notes. | **Refused** — not permitted to create a wastage entry. No wastage entry and no stock entry are created. |
| 2 | Repeat identically as the **Kitchen Manager**. | Succeeds: a wastage entry, a **Material Issue** stock entry and an estimated value are returned. |
| 3 | In Desk, open the wastage entry. | Recorded-by and approved-by both show the manager; the stock entry links to the Material Issue. |
| 4 | As the manager, repeat with **notes left blank**. | Refused — wastage must be explained. |

**Pass criteria:** The kitchen user is refused before any stock moves; the manager succeeds with a genuine stock movement; unexplained wastage is refused regardless of role.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Section D.6 — Changing a stay in flight · signed by Front Office Manager

### D-25 · Move a guest, extend and shorten a stay, leave a handover note

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/in-house` → `/pms/stays/<stay>` |
| **Prerequisites** | An in-house stay. A second clean room of the same room type, free for the rest of the stay. |
| **Test data** | The stay from C-09 |
| **Severity if failed** | **High** — mid-stay changes are routine work; a desk that cannot do them phones a manager every time |

> **New in 16.3.0.** These four operations were previously Desk-only, which put
> them out of reach of the six operational roles that have no Desk. The rules
> have not changed — the same services run underneath — only where they can be
> reached from.

| # | Step | Expected result |
|---|---|---|
| 1 | On **In House**, click the guest's **room number**. | The stay screen opens, showing guest, room, dates, nights, party size, rate, and links to the folio and the reservation. |
| 2 | Read the **Stay actions** row. | Move room, Extend stay, Shorten stay, Add a note. |
| 3 | Click **Move room**. | A dialog listing only rooms of the same type that are free for the rest of the stay. The guest's current room is **not** offered — it is not a move. |
| 4 | Try to confirm with the reason blank. | Refused; the button stays disabled. |
| 5 | Choose a room, type a reason, and confirm. | Success. The screen reloads showing the new room. |
| 6 | Read the **Room moves** section. | An entry showing from-room → to-room, the timestamp, and your reason. |
| 7 | Check both rooms on the **Room Rack**. | The old room is released; the new one is Occupied. |
| 8 | Click **Extend stay** and choose a date **earlier** than the current departure. | Refused on screen, with a message that the new date must be later. |
| 9 | Choose a date one night later and confirm. | Success; the departure date moves out by one night. |
| 10 | Extend again into a night where the room is **already sold**. | Refused by the server, naming the conflict. The stay is unchanged. |
| 11 | Click **Shorten stay**, choose the original departure date, and try to confirm with no reason. | Refused — a reason is mandatory. |
| 12 | Add a reason and confirm. | Success; the departure returns to where it was. |
| 13 | Click **Add a note**, choose **Shift Handover**, type a note and add it. | The note appears under **Stay notes** with its type, your name and the time. |
| 14 | Sign in as a **Room Attendant** and open the same stay address directly. | Refused — this role has no business changing a stay. |
| 15 | Open a stay that has already **checked out**. | The Stay actions row is **not** shown. A departed stay is history. |

**Pass criteria:** All four operations work from `/pms`, each records who and why where the domain requires it, and neither an unauthorised role nor a closed stay can be operated on.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### D-26 · Assign a room before the guest arrives

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` → `/pms/reservations/<name>` |
| **Prerequisites** | A Confirmed or Guaranteed reservation with **no room assigned** |
| **Test data** | The unassigned arrival prepared for C-04 |
| **Severity if failed** | **High** — pre-assignment is normal practice for VIPs, connecting rooms and groups |

> **Fixes a defect found in UAT preparation.** In 16.2.0 the arrivals board's
> **Assign room** action opened the reservation, which showed the assigned room
> read-only and offered no way to change it. Rooms could only be chosen during
> check-in. The control now exists on the reservation itself.

| # | Step | Expected result |
|---|---|---|
| 1 | On the **arrivals board**, find a row with no room and click **Assign room**. | The reservation opens. |
| 2 | Look at the room line. | An **Assign a room** button is present on the line. |
| 3 | Click it. | A dialog offering rooms of that room type, free for the whole stay. |
| 4 | Choose a clean room and confirm. | Success. The line now shows the assigned room. |
| 5 | Return to the arrivals board and refresh. | That row shows the room number, its readiness badge, and no longer offers **Assign room**. |
| 6 | Check the **Room assigned** and **No room** tiles. | They have moved by one. |
| 7 | Back on the reservation, click **Change room** on the same line. | The dialog reopens so the room can be swapped. |
| 8 | Choose a room that is **not clean**, if one exists. | The dialog marks it as not ready and asks for an explicit tick before it will submit. |
| 9 | Submit without ticking. | Refused. |
| 10 | Tick and submit. | Permitted, and the server records the override. |
| 11 | Open a **Cancelled** reservation. | No assign control is offered — there is nothing to hold a room for. |

**Pass criteria:** A room can be assigned and changed before arrival from `/pms`, the arrivals board reflects it immediately, and an unready room needs a deliberate override.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey D sign-off

| Section | Scenarios | Accepted by | Role | Signature | Date |
|---|---|---|---|---|---|
| D.1 Folio | D-01…D-04 | | Front Office Manager | | |
| D.2 Housekeeping | D-05…D-10 | | Housekeeping Manager | | |
| D.3 Maintenance | D-11…D-15 | | Maintenance Manager | | |
| D.4 Guest services | D-16…D-19 | | Front Office Manager | | |
| D.5 Room service and kitchen | D-20…D-24 | | Kitchen Manager | | |
| D.6 Changing a stay in flight | D-25, D-26 | | Front Office Manager | | |

| | |
|---|---|
| **Scenarios passed** | ____ of 26 |
| **Critical/High defects open** | ____ |
