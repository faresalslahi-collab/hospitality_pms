# Housekeeping, maintenance and guest services guide

**Applies to:** Hospitality PMS 16.1.0 (branch `version-16`)

This guide is for housekeeping supervisors, room attendants, maintenance technicians and guest relations staff. It covers how a room gets cleaned and checked, how a broken fitting gets fixed, how a guest request or complaint is handled, and how room service, minibar and kitchen stock are recorded.

**A note on where you do this work.** Housekeeping tasks, maintenance tickets and guest requests now have their own boards in the operational frontend at `/pms`:

| Page | Route | What it does |
|---|---|---|
| Housekeeping | `/pms/housekeeping` | The task board: summary tiles and one tap per task to assign, start, complete, inspect, or mark DND/Service Refused (sections 2–4). |
| Maintenance | `/pms/maintenance` | The ticket board: raise a ticket, and one tap per ticket to assign, log work, start, take out of service, complete work, or verify and release (sections 6–8). |
| Guest services | `/pms/guest-services` | The request board: raise a request or complaint, and one tap per request to start, assign, complete, escalate, reopen, close, or record service recovery (sections 9–10). |

Each board offers exactly the actions the server currently allows from the record's status, and the server refuses anything it does not — a tap that is no longer valid by the time you make it comes back as an ordinary refusal, not a hidden button. Kitchen requisitions, room service and minibar orders, and wastage entries are the exception: they are created and moved through their steps in the Frappe Desk (the standard back-office screens), using the "Kitchen Requisition", "Room Service Order" and "Wastage Entry" doctypes (section 11). The room rack itself (occupancy, housekeeping, maintenance and inventory status at a glance) is also on the frontend, at `/pms/rooms`.

---

## 1. How rooms move

Every room in the system carries **four separate status flags**, not one:

| Dimension | What it tracks | Who mainly moves it |
|---|---|---|
| **Occupancy** | Is there a guest in the room right now, or committed to arrive | Front desk, night audit |
| **Housekeeping** | Is the room physically clean and checked | Room attendants, supervisors |
| **Maintenance** | Is anything broken or being worked on | Technicians, maintenance managers |
| **Inventory** | Is the room allowed to be sold at all | Front office, revenue, housekeeping and maintenance managers |

These four are deliberately kept apart. A room can be **Occupied**, **Dirty**, **Operational** and **Available** all at the same time — a guest is staying in it, it needs a stayover clean, nothing is broken, and it is still part of saleable inventory. If housekeeping status were merged into one big "room status" field, nobody could answer a simple question like "which occupied rooms still need cleaning today". Keep this separation in mind: cleaning a room does not touch whether it is occupied, and fixing a fault does not touch whether it is clean.

The everyday housekeeping flow runs through the housekeeping dimension like this:

1. Guest checks out. The system automatically sets the room's **Occupancy** to Vacant and its **Housekeeping** to **Dirty** in one step, and (if the setting is on) raises a cleaning task.
2. An attendant starts cleaning. Housekeeping status moves to **In Progress**.
3. The attendant finishes. If the room does not need inspection, housekeeping status goes straight to **Clean**. If it does need inspection, it goes to **Inspection Pending** instead.
4. A supervisor inspects. If it passes, housekeeping status becomes **Inspected**. If it fails, the room goes back to **Dirty**.
5. Once housekeeping status is **Clean** or **Inspected**, the room counts as physically ready for a new guest — provided its Maintenance status is not blocking and its Inventory status is not blocking and it is not already occupied.

The full set of housekeeping values a room can carry: **Clean, Dirty, In Progress, Inspection Pending, Inspected, DND, Service Refused.** An inspected room is not a dead end — it can be sent back into Dirty, In Progress or Inspection Pending later (turndown service, a deep clean, a stayover service), which is why the diagram is a loop, not a straight line.

---

## 2. Housekeeping tasks

A **Housekeeping Task** is the unit of work an attendant is given. It is a separate record from the room's housekeeping status, but the two are always moved together by the system so they never disagree.

### Where tasks come from

- **Automatically on checkout.** When a stay is checked out, the system raises a task for that room (task type "Departure Clean") for the property's current business date — but only if the hotel's setting **Create Housekeeping Task on Checkout** is switched on (it is on by default). If a task already exists for that room, type and date, checkout does not create a duplicate; it reuses the existing one.
- **Manually**, for any other reason: a stayover clean, a turndown, a deep clean, a linen change, a minibar check, an inspection visit, or a special request.

### Task states

A task moves through these states:

- **Pending** — raised, not yet given to anyone.
- **Assigned** — given to a room attendant.
- **In Progress** — the attendant is cleaning.
- **Inspection Pending** — cleaning is done and a supervisor still needs to sign it off (only used when the task requires inspection).
- **Completed** — finished (and inspected, if required).
- **Cancelled**.
- **DND** — the guest asked not to be disturbed.
- **Service Refused** — the guest declined the service.

A task can move from Pending or Assigned into DND or Service Refused, and back out of either of those into Pending, Assigned, In Progress or Cancelled once the guest is available again.

### Assigning a task

Only a supervisor or manager may assign a task to an attendant: **Housekeeping Supervisor, Housekeeping Manager, Front Office Manager, Hotel Manager, General Manager, Hospitality Administrator** or **System Manager**. Assigning records who did it and when.

### Starting a task

The attendant starts the task once they begin cleaning. This moves the task to **In Progress** and moves the room's housekeeping status to **In Progress** at the same time.

### Completing a task

When the attendant finishes, they record:

1. How many minutes it took (optional — if not given, it is recorded as zero).
2. Whether the minibar was checked.
3. Whether damage was found (and, if so, a description — this is mandatory once damage is flagged).
4. Whether anything was found and needs recording as lost property (and an optional note).
5. Whether a maintenance issue needs raising, with an optional description.

What happens next depends on whether the task requires inspection:

- **No inspection required** — the task goes to **Completed** and the room's housekeeping status goes to **Clean**.
- **Inspection required** — the task goes to **Inspection Pending** and the room's housekeeping status goes to **Inspection Pending** too, not Clean. "The attendant says it's clean" and "a supervisor has checked it" are different facts, and the room rack must show which one is true.

A task can only be completed while it is **In Progress** — you cannot complete a task that has not been started.

Whether a task requires inspection is decided when it is raised: either it is set explicitly, or it falls back to the hotel-wide setting **Require Inspection Before Room Release** (on by default).

---

## 3. Inspection

Only a supervisor or manager may sign off an inspection: **Housekeeping Supervisor, Housekeeping Manager, Front Office Manager**... actually, specifically **Housekeeping Supervisor, Housekeeping Manager, Hotel Manager, General Manager, Hospitality Administrator** or **System Manager**. A room attendant cannot inspect their own work.

An inspection can only be recorded against a task that is currently **Inspection Pending** — you cannot inspect a task that has not reached that state.

1. The inspector records a pass or fail, an optional score, and notes.
2. **If it passes:** the task moves to **Completed** and the room's housekeeping status moves to **Inspected**. An inspection record is saved against the room and the task.
3. **If it fails:** you must give a note saying what needs to be redone — a failed inspection with no note is rejected. The task goes back to **In Progress**, and the room's housekeeping status goes back to **Dirty**, not to In Progress. This is deliberate: a room does not "quietly pass" — a failed inspection puts the room visibly back among the rooms that still need cleaning, and the attendant has to clean it again and complete it again before it can be inspected a second time.

Every inspection, pass or fail, creates a permanent **Room Inspection** record: who inspected, when, the result, the score and the notes, linked to both the room and the task.

---

## 4. DND and refused service

Sometimes you cannot clean a room because the guest has asked not to be disturbed, or because they have been offered the service and turned it down. Record this against the task rather than leaving it Pending or marking it Cancelled — it is not a failure to clean, and the system tracks it separately:

- **Do Not Disturb** — the guest has a DND sign up or has otherwise asked not to be disturbed. The task moves to **DND** and the room's housekeeping status moves to **DND**.
- **Service Refused** — the guest was offered cleaning and declined it. The task moves to **Service Refused** and the room's housekeeping status moves to **Service Refused**.

Either of these can be recorded from Pending, Assigned or In Progress. Once the guest is available again, the task (and the room) can be moved back into Pending, Assigned, In Progress or Cancelled so cleaning can resume.

---

## 5. Damage, minibar and lost property

These are recorded as part of completing a housekeeping task (see section 2), not as separate documents:

- **Minibar checked** — a simple yes/no flag confirming the attendant checked it.
- **Damage found** — a yes/no flag with a mandatory description once it is ticked.
- **Lost and found** — a yes/no flag with an optional note describing what was found.
- **Maintenance required** — a yes/no flag with an optional description of the issue, used only to build the maintenance ticket (it is not itself saved on the task).

**Raising damage or a maintenance issue automatically opens a maintenance ticket.** If either "damage found" or "maintenance required" is ticked when the task is completed, the system creates a new maintenance ticket for that room straight away:

- Title: "Issue found while cleaning room `<room>`".
- Description: whatever was typed in, or the damage notes if nothing else was given.
- Category: **Other**.
- Priority: **High** if damage was found, otherwise **Normal**.
- The ticket is linked back to the housekeeping task it came from, and the task is linked forward to the ticket it created.

You do not need to separately log into maintenance to report something an attendant found while cleaning — completing the task with the right boxes ticked does it for you.

---

## 6. Maintenance tickets

### Raising a ticket

Anyone can raise a maintenance ticket, giving at minimum a title and a description. You can also record:

- **Ticket type** — Corrective, Preventive, Inspection or Improvement.
- **Priority** — Low, Normal, High or Urgent.
- **Category** — Electrical, Plumbing, HVAC, Furniture, Appliance, IT and Network, Safety, Structural or Other.
- Room, zone, area and asset, as applicable.

If the same room has had a **completed** ticket in the same category within the last 30 days, the new ticket is automatically flagged as a **repeat defect** and linked to the earlier one — worth a second look, since the same fault may be coming back.

### Ticket states

- **Open** — raised, not yet started.
- **In Progress** — a technician is working on it.
- **Verification** — the technician says the work is done; someone still needs to check it.
- **Completed** — verified and closed off.
- **Cancelled**.

### Assigning and working

- **Assigning** a ticket to a technician needs a manager: **Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator** or **System Manager**.
- **Starting work** moves the ticket to **In Progress**. If the ticket is against a room, the room's maintenance status moves to **Required**.
- **Logging work** lets the technician add an entry to the ticket's work log at any point — what was done, minutes spent, and parts used. A description of the work is mandatory for each entry.
- **Completing work** moves the ticket to **Verification**. This is the technician's step, not the final word — the room is not released yet.

---

## 7. Taking a room out of service

Sometimes a fault is bad enough that the room must stop being sold while it is fixed. This is done from a maintenance ticket, and it is a manager decision:

Only **Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator** or **System Manager** may take a room out of service. A reason is mandatory.

Doing this does more than set a flag on the room. It raises a genuine, submitted **Room Block** covering the room for a date range (by default, from today's business date for seven days, though this can be changed). Because it is a real block, the availability engine, the room rack and revenue reporting all see the same fact — the room is genuinely gone from sale, not just marked as such on one screen. At the same time, the room's maintenance status is set to match.

Two statuses are available, and they are handled identically by the system in terms of who may set them, what block they raise, and how they are released — the only difference is which one you choose and the label it leaves in the room's history:

- **Out of Service** — records a "Maintenance" type room block.
- **Out of Order** — records an "Out of Order" type room block.

Both statuses stop the room being assigned to any guest, exactly like the ordinary **Under Maintenance** status does. Choose whichever matches how your hotel classifies the severity of the issue; the system does not distinguish between them beyond the label.

---

## 8. Releasing a room back to sale

A room that has been taken out of service is **not** put back on sale just because the technician says the job is done. It goes through a verification step, and only a manager can complete it:

Only **Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator** or **System Manager** may verify and release a ticket. Verification can only be recorded while the ticket is in the **Verification** state.

1. **If verification passes:** the ticket moves to **Completed**, the room block is released (cancelled), and the room's maintenance status is set back to **Operational**. The room becomes sellable again as far as maintenance is concerned (it must still be clean and not blocked for another reason to actually be assignable).
2. **If verification fails:** you must give a note describing what is still wrong — a failed verification with no note is rejected. The ticket goes back to **In Progress**, and the room block stays active. The room stays out of sale. That is the entire point of the verification step: a technician's word that the job is finished is not, on its own, enough to put a room back in front of a guest.

---

## 9. Guest requests and complaints

Use a **Guest Request** for anything a guest asks for or complains about — an extra pillow, a late checkout, a noise complaint, a billing query.

### Raising a request

A subject and a description are required. You also choose:

- **Request type** — Request or Complaint.
- **Category** — Housekeeping, Maintenance, Front Office, Food and Beverage, Transport, Concierge, IT and Network, Billing or Other.
- **Priority** — Low, Normal, High or Urgent.
- Guest, stay, room, reservation and department, as applicable.

### The SLA clock

The moment a request is raised, the system starts a response-time clock and works out a **due-by time** based on the priority. Unless a different number of minutes is set explicitly, the default targets are:

| Priority | Default response target |
|---|---|
| Urgent | 15 minutes |
| High | 30 minutes |
| Normal | 2 hours (120 minutes) |
| Low | 8 hours (480 minutes) |

The clock is set the instant the request is created — nobody decides after the fact whether it was late; the system records it.

### Assignment and progress

- **Assigning** a request to a member of staff (and, optionally, to a department) also records the first response time, if one has not already been logged.
- **Starting** work also records the first response time, if assignment did not already do so.
- **Completing** a request needs a resolution note, and records whether the guest was satisfied. At this point the system stamps whether the SLA was **breached** — the due-by time had already passed when the request was completed.
- **Closing** a completed request is a separate final step.
- A completed or closed request can be **reopened** if the guest is not satisfied. Reopening needs a reason, clears the "guest satisfied" flag, and counts up how many times the request has been reopened.

### Escalation

A request can be escalated by staff at any point before it is resolved, to a named person, with a reason. Each escalation raises the request's **escalation level** by one, so a request that keeps missing its target keeps climbing rather than sitting at the same escalation level forever. A request already completed, closed or cancelled cannot be escalated.

### The automatic SLA sweep

A scheduled job periodically checks every open, assigned, in-progress or reopened request against its due-by time and automatically escalates anything that is overdue. This runs regularly and is safe to run often — a request already escalated at the current level is not escalated again by the same pass, so the sweep cannot inflate escalation levels just by running more frequently.

---

## 10. Service recovery

When a complaint needs compensating the guest, this is recorded as **service recovery** against the guest request. Only the following roles may approve it: **Front Office Manager, Guest Relations Officer, Hotel Manager, General Manager, Finance Manager, Hospitality Administrator** or **System Manager**. A reason is always required.

The recovery types available are: **Apology, Discount, Complimentary Service, Room Upgrade, Folio Adjustment, Loyalty Points** and **Other**.

If the recovery has a monetary amount and is to be posted to the folio, the guest's stay must have an open folio — if it does not, the recovery cannot be posted. When it can be posted, the amount is charged to the folio as a **Discount** line, referencing the request. The charge carries a key derived from the request itself, so if the same recovery is approved a second time (for example, by an accidental repeat click), it is **not** posted to the folio twice — the guest is only ever discounted once for the same approval.

---

## 11. Kitchen, room service and minibar

### Requisitions (store to kitchen)

A requisition moves stock from one warehouse to another — typically the general store to the kitchen store, or to the minibar stock location — and always needs at least one line.

1. Raise the requisition: it starts as **Draft** and is immediately moved to **Submitted**.
2. **Issue** the requisition to actually move the stock. This creates and submits a real stock transfer entry. Issuing an already-issued requisition simply returns the existing transfer rather than moving the stock a second time, so retrying is safe. A cancelled requisition cannot be issued.

### Room service and minibar orders

An order (room service or minibar) is placed against a guest's stay, and the stay must have an open folio to charge — if it doesn't, the order cannot be placed.

**The price always comes from the menu, never from whoever is placing the order.** Each line names a menu item and a quantity; the rate is read from that menu item's selling price at the moment the order is placed, and the item must be marked active. This means nobody entering an order — including the guest-facing side — can give an item away at a different price than the one set up on the menu.

Orders move through these states: **Placed, Preparing, Ready, Delivered, Cancelled.**

**Delivering an order charges the guest's folio, exactly once.** Moving an order to Delivered:

1. Posts the order total to the folio, as a **Minibar** or **Room Service** charge depending on the order type.
2. Is safe to retry — an order that has already been charged is not charged again; the existing charge is simply returned.
3. Issues the stock actually consumed, for any menu item that is mapped to a real stock item (a service-only line, such as a corkage fee, has nothing to issue). If the property has not set up a warehouse for that order type, the charge still goes through — only the stock movement is skipped, and that gap shows up separately as a configuration issue rather than blocking the guest's bill.

### Wastage

Recording stock written off (spoilage, breakage, over-production) needs manager approval: **Kitchen Manager, Food and Beverage Manager, Hotel Manager, General Manager, Hospitality Administrator** or **System Manager**. It always needs a reason, explanatory notes, and a quantity greater than zero. Recording wastage creates a real stock issue behind it, so the stock ledger and the wastage log always agree.

---

## 12. Quick reference

### Housekeeping task status

| Status | What it means |
|---|---|
| Pending | Raised, not yet assigned |
| Assigned | Given to an attendant |
| In Progress | Attendant is cleaning |
| Inspection Pending | Cleaning done, awaiting supervisor sign-off |
| Completed | Finished (and inspected, if required) |
| Cancelled | Task called off |
| DND | Guest asked not to be disturbed |
| Service Refused | Guest declined the service |

### Room housekeeping status (on the room rack)

| Status | What it means |
|---|---|
| Clean | Ready — attendant has finished, no inspection was required |
| Dirty | Needs cleaning (including after a failed inspection) |
| In Progress | Being cleaned right now |
| Inspection Pending | Cleaning done, waiting for a supervisor to check it |
| Inspected | Ready — a supervisor has signed it off |
| DND | Guest does not want to be disturbed |
| Service Refused | Guest declined cleaning |

### Room maintenance status (on the room rack)

| Status | What it means |
|---|---|
| Operational | No known issue |
| Required | A maintenance ticket is being worked on for this room |
| Under Maintenance | Set manually when work is under way (not produced automatically by a ticket) |
| Out of Service | Taken out of sale for maintenance; a room block is in force |
| Out of Order | Taken out of sale for a more serious issue; a room block is in force |

### Room inventory status (on the room rack)

| Status | What it means |
|---|---|
| Available | Sellable |
| Blocked | Held by a room block (including maintenance, out of order, group, house use, and similar reasons) |
| Not Assignable | Taken out of sale for another operational reason |
| Stop Sell | Taken out of sale, typically for a revenue reason |

### Room inspection result

| Result | What it means |
|---|---|
| Passed | Room accepted; housekeeping status becomes Inspected |
| Failed | Room rejected; housekeeping status goes back to Dirty, task goes back to In Progress |

### Maintenance ticket status

| Status | What it means |
|---|---|
| Open | Raised, not yet started |
| In Progress | A technician is working on it |
| Verification | Technician says it's done; awaiting sign-off |
| Completed | Verified and closed; room (if any) released |
| Cancelled | Ticket called off |

### Guest request status

| Status | What it means |
|---|---|
| Open | Raised, not yet assigned |
| Assigned | Given to a member of staff |
| In Progress | Being worked on |
| Escalated | Overdue or otherwise raised in urgency |
| Completed | Resolved, with a resolution recorded |
| Closed | Finished, no further action |
| Reopened | Guest was not satisfied; being worked again |
| Cancelled | Withdrawn |

### Room service / minibar order status

| Status | What it means |
|---|---|
| Placed | Order taken, priced from the menu |
| Preparing | Kitchen is preparing it |
| Ready | Ready to send up |
| Delivered | Delivered and charged to the folio |
| Cancelled | Order called off |

### Kitchen requisition status

| Status | What it means |
|---|---|
| Draft | Being built |
| Submitted | Requested, stock not yet moved |
| Issued | Stock has been transferred |
| Cancelled | Requisition called off |

### Room block status (behind Out of Service / Out of Order)

| Status | What it means |
|---|---|
| Active | Currently keeping the room out of sale |
| Released | Manually or automatically returned to sale ahead of schedule |
| Cancelled | Block withdrawn |
