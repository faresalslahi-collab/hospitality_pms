# Journey C — Arrival day: prepare, greet, check in

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Front Office Manager
**Surface:** `/pms` throughout.

The shift arrives, looks at the board, works the list and puts guests in rooms.
Six of these thirteen scenarios cover screens introduced in 16.2.0 and have never
been tested by a business user.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first. Reference sections point at
[Front Office Guide](../guides/02_Front_Office_Guide.md).

**Prerequisites for the whole journey:** Journeys A and B passed. At least one
Confirmed or Guaranteed reservation arriving on the property's **business date**.
If the booking you made in B-04 arrives later, create one more arriving today.

**Note the two property switches** you recorded in §4 of the plan — **Require ID
at check-in** and **Allow Vacant Dirty check-in**. C-10 and C-11 branch on them.

**Test data to prepare before you start:**

- 2–3 reservations arriving on the business date, at least one with **more than one room**, so the boards can be seen counting rooms rather than bookings.
- One arriving guest whose Guest record has **VIP status** set (Desk).
- One arriving reservation with a **required deposit not yet received** (from the deposit policy in A-05), for **C-06** and **C-11**.
- One room set to **Dirty** in Desk or on the Room Rack, for **C-10**.

---

### C-01 · The dashboard tells the shift where it stands — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms` |
| **Prerequisites** | Reservations arriving today exist |
| **Test data** | Note, from Desk or the Room Rack, the true number of rooms, occupied rooms and out-of-order rooms before you start |
| **Severity if failed** | High — the shift starts blind, though it can still work from the boards |

| # | Step | Expected result |
|---|---|---|
| 1 | Sign in and land on `/pms`. | The dashboard loads. The subtitle names the property and the **business date** — not necessarily today's calendar date. |
| 2 | Read the **Front desk today** section. | Seven figures: Arrivals today, Pending check-ins, Departures today, Pending check-outs, In-house rooms, In-house guests, Due out. |
| 3 | Read the **Rooms** section. | Total rooms, Occupied, Available now, Vacant clean, Vacant dirty, Out of order, Out of service, Blocked, and an "Occupied now" percentage. |
| 4 | Compare Total rooms and Out of order to the true figures you noted. | They match. |
| 5 | Read the small print under "Occupied now". | It says this is a live count against active inventory, not the audited figure. |
| 6 | Read the **Performance** section. | Before the first Night Audit has closed, it shows a sentence saying no audit has closed yet and **no numbers at all**. It must not show zeros for occupancy, ADR or RevPAR. |
| 7 | Read **Recorded today** and its note. | Room revenue, Payments received, Outstanding balance, with a note that room charges are posted by the Night Audit so the figure stays low until it runs. |
| 8 | Read **Open work**. | Housekeeping tasks, Maintenance tickets, Guest requests. |
| 9 | Click **Refresh**. | Figures reload without leaving the page. |

**Pass criteria:** Every figure matches reality, and the Performance section shows a sentence rather than zeros before the first audit closes. **A zero shown for occupancy or ADR before any audit has closed is a Fail**, not a rounding detail.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-02 · Dashboard tiles and quick actions go where they say — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms` |
| **Prerequisites** | C-01 passed |
| **Test data** | None |
| **Severity if failed** | Medium — the figures are still right; navigation is slower |

| # | Step | Expected result |
|---|---|---|
| 1 | Click the **Arrivals today** tile. | The arrivals board opens. |
| 2 | Go back and click **Departures today**. | The departures board opens. |
| 3 | Go back and click **In-house rooms**. | The in-house board opens. |
| 4 | Go back and click any **Rooms** tile. | The room rack opens. |
| 5 | In **Open work**, click Housekeeping tasks, then Maintenance tickets, then Guest requests. | Each opens its board — *if* your role may see it. As a Front Office Agent, Housekeeping and Maintenance are **not** links; the number is shown as plain text. That is correct. |
| 6 | Read the **Quick actions** row. | New reservation, Find a reservation, Today's arrivals, Today's departures, In house, Room rack, Availability, Reservation calendar. |
| 7 | Click each in turn. | Each opens the screen it names. None leads to a "not found" or an empty page. |
| 8 | Sign out, sign in as a **Room Attendant**, and open `/pms`. | **New reservation** is not offered. |

**Pass criteria:** Every tile and action reaches a working screen, and an action the server would refuse is not offered at all.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-03 · The arrivals board is the day's work list — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` |
| **Prerequisites** | Reservations arriving on the business date, at least one with more than one room |
| **Test data** | Know how many **rooms** (not bookings) are arriving today |
| **Severity if failed** | **Critical** — the front desk has no list of who is coming |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Arrivals** from the Front desk section of the sidebar. | A board for the business date. |
| 2 | Read the tiles across the top. | Arrivals, Pending, Checked in, Room assigned, No room, Ready, Not ready, VIP. |
| 3 | Count the rows in the table. | The row count equals the **Arrivals** tile, and both count **rooms**, not bookings. A two-room booking is two rows. |
| 4 | Read the columns. | Reservation, Guest, Arrival, Departure, Room type, Room, Readiness, Status, Guarantee, Deposit, Guests, Actions. |
| 5 | Find the multi-room booking. | Its rows share a guest name and reservation number but are separate lines, each able to carry its own room. |
| 6 | Click a reservation number. | The reservation opens. |
| 7 | Return, and click **Open** in the Actions column. | The same reservation opens. |
| 8 | Confirm the dates shown match the reservation. | Arrival and departure agree. |

**Pass criteria:** Every room arriving today appears exactly once, the tile totals agree with the rows, and a multi-room booking reads as multiple pieces of work.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-04 · Arrivals filters carve the list the way the desk thinks — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` |
| **Prerequisites** | C-03 passed. A mixture of assigned and unassigned arrivals, and at least one room not clean. |
| **Test data** | The Dirty room prepared for C-10 |
| **Severity if failed** | Medium — the whole list is still visible, just harder to work |

| # | Step | Expected result |
|---|---|---|
| 1 | Note the totals on each tile. | Written down for comparison. |
| 2 | Set the filter to **Room not assigned**. | Only rows with no room. The row count equals the **No room** tile. |
| 3 | Set it to **Room assigned**. | Row count equals the **Room assigned** tile. |
| 4 | Set it to **Ready**, then **Not ready**. | Ready = rooms assigned and clean; Not ready = rooms assigned but not clean. Counts match the matching tiles. |
| 5 | Set it to **Confirmed**, then **Guaranteed**. | Only rows with that reservation status. |
| 6 | Set it to **Not checked in**, then **Checked in**. | Counts match the Pending and Checked in tiles. |
| 7 | Choose a filter that matches nothing. | A clear "no arrivals match this filter" message — the tiles and the filter control stay on screen so you can change it. |
| 8 | Return to **All**. | The full list is back. |

**Pass criteria:** Every filter's row count equals its matching tile, and an empty filter result explains itself without hiding the controls.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-05 · VIP and blacklist are visible before the guest reaches the desk — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` |
| **Prerequisites** | One arriving guest with VIP status set on their guest record |
| **Test data** | Optionally, a second arriving guest who is blacklisted — note that B-09 means such a booking cannot normally be created, so this may only be reachable if a guest was blacklisted **after** booking, which is the realistic case. Set it up that way in Desk. |
| **Severity if failed** | High — the hotel greets a VIP as a stranger, or checks in someone it has barred |

| # | Step | Expected result |
|---|---|---|
| 1 | Find the VIP guest's row. | A badge beside the guest name showing their actual tier — VIP, VVIP, Loyalty Member or Repeat Guest — not a generic mark. |
| 2 | Check the **VIP** tile. | It counts that row. |
| 3 | Filter and scan the board for the blacklisted arrival, if you set one up. | A red **Blacklisted** badge beside the name. |
| 4 | Confirm the badge is readable without relying on colour. | Each badge carries its text label, not just a coloured dot. |

**Pass criteria:** VIP tier and blacklist state are visible on the board itself, in words as well as colour.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-06 · An unpaid deposit is visible before the guest arrives — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` |
| **Prerequisites** | One arriving reservation with a required deposit not yet received |
| **Test data** | The deposit policy from A-05 |
| **Severity if failed** | High — the desk discovers the problem with the guest standing in front of it |

| # | Step | Expected result |
|---|---|---|
| 1 | Find that reservation's row and read the **Deposit** column. | An amount outstanding, shown in the property's currency and marked in a warning colour. |
| 2 | Read the same column on a row with no deposit due. | A plain dash. |
| 3 | Compare the amount to the reservation record. | Outstanding = required − received. |
| 4 | If your multi-room booking has a deposit, check its rows. | The **deposit outstanding tile** counts the booking once, not once per room — a deposit is owed once. |

**Pass criteria:** The outstanding amount is correct and the tile counts bookings, not rooms.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-07 · Room readiness on the board agrees with the rack — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` and `/pms/rooms` |
| **Prerequisites** | At least one arrival with an assigned room |
| **Test data** | The Dirty room from C-10's preparation |
| **Severity if failed** | High — the desk sends a guest to a room housekeeping has not finished |

| # | Step | Expected result |
|---|---|---|
| 1 | On the arrivals board, note the **Readiness** badge for an assigned row. | A housekeeping status: Clean, Dirty, In Progress, Inspected and so on. |
| 2 | Open the **Room Rack** in another tab and find the same room. | Its housekeeping status matches the badge exactly. |
| 3 | On the rack, change that room's housekeeping status to **Dirty**. | The change saves. |
| 4 | Return to arrivals and click **Refresh**. | The Readiness badge now reads Dirty, and the Ready / Not ready tiles have moved by one. |
| 5 | Look at a row with **no** room assigned. | Readiness shows a dash, not "Ready" and not "Dirty". Readiness of a room you have not chosen is not a fact. |
| 6 | Confirm that occupancy, maintenance and inventory are **not** merged into this one badge. | The Readiness column shows housekeeping only. The other three dimensions live on the rack. |

**Pass criteria:** Readiness matches the rack, moves when the rack moves, is blank when no room is assigned, and does not collapse four independent statuses into one.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-08 · The board's arrivals count agrees with the dashboard — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms` and `/pms/arrivals` |
| **Prerequisites** | C-01 and C-03 passed |
| **Test data** | None |
| **Severity if failed** | High — two screens disagreeing about today's arrivals destroys trust in both |

| # | Step | Expected result |
|---|---|---|
| 1 | On the dashboard, note **Arrivals today** and **Pending check-ins**. | Two figures. |
| 2 | Open the arrivals board and note **Arrivals**, **Pending** and **Checked in**. | Three figures. |
| 3 | Compare. | Dashboard "Arrivals today" = board "Arrivals". Dashboard "Pending check-ins" = board "Pending". |
| 4 | Check in one guest (C-09 does this properly; a single check-in is enough here). | Check-in succeeds. |
| 5 | Refresh both screens. | Both Pending figures fall by one, both Checked in figures rise by one, and Arrivals is unchanged on both. |

**Pass criteria:** The two screens agree before and after a check-in.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-09 · Choose a room and check the guest in

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/arrivals` → `/pms/check-in/<reservation>` |
| **Prerequisites** | A Confirmed or Guaranteed reservation arriving today, with a clean room available in its room type |
| **Test data** | The reservation from B-04, or one arriving today |
| **Severity if failed** | **Critical** — the hotel cannot admit guests |

| # | Step | Expected result |
|---|---|---|
| 1 | On the arrivals board, click **Check in** on a pending row. | The check-in screen opens for that reservation. |
| 2 | Read the top of the screen. | Any readiness warnings, guest alerts and a blacklist warning if applicable are shown before you do anything. |
| 3 | Open the room selector for the room line. | Only rooms of the **right room type**, in this property, that are free for the whole stay. A room already occupied for any night of the stay is not offered. |
| 4 | Choose a clean room and click **Check in**. | Success. The screen confirms it. |
| 5 | Open the **Room Rack** and find that room. | Occupancy is now **Occupied**. |
| 6 | Open **In House**. | The guest appears with their room, dates, party size and a folio link. |
| 7 | Return to the arrivals board and refresh. | That row now shows **Checked in** and no longer offers a Check in link. |
| 8 | Note the room number and the folio number. | **Journeys D and E need both.** Room: `______` Folio: `________________` |

**Pass criteria:** The guest is in a room, the room shows Occupied, a folio exists, and the arrivals board reflects it.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-10 · Check-in before the arrival date is refused

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/check-in/<reservation>` |
| **Prerequisites** | A Confirmed reservation arriving on a **future** date |
| **Test data** | The B-04 booking if it arrives later, or a new one |
| **Severity if failed** | High — a room is consumed a night early and availability is wrong |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the check-in screen for a reservation arriving in the future. | It opens, and warns that the arrival date has not been reached. |
| 2 | Select a room and attempt to check in. | **Refused**, with a message naming the arrival date. |
| 3 | Check the Room Rack. | The room is unchanged — still Vacant. |
| 4 | Check In House. | No stay was created. |

**Pass criteria:** The check-in is refused and nothing was created or changed.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-11 · A room that is not clean: refused, then a manager override with a reason

| | |
|---|---|
| **Role** | Front Office Agent, then Front Office Manager |
| **Surface** | `/pms/check-in/<reservation>` |
| **Prerequisites** | A reservation arriving today, and a room of its type set to **Dirty** |
| **Test data** | The Dirty room. **Check the property switch** "Allow Vacant Dirty check-in" you recorded in the plan. |
| **Severity if failed** | **Critical** if an agent can override without a reason; High if the override is unavailable to a manager who needs it |

| # | Step | Expected result |
|---|---|---|
| 1 | As the agent, open check-in and select the **Dirty** room. | It is offered but visibly marked as not ready. |
| 2 | Attempt to check in. | Refused, naming the room's housekeeping status. |
| 3 | Look for an override control as the **agent**. | Either absent, or present but refused by the server. An agent completing the check-in with no reason recorded is a **Critical** failure. |
| 4 | Sign in as a **Front Office Manager** and repeat. | An override control is offered, requiring a tick **and** a typed reason. |
| 5 | Try to submit the override with the reason blank. | Refused. |
| 6 | Enter a reason and check in. | Succeeds. |
| 7 | Open the resulting stay in Desk and find the override fields. | The override flag is set and your reason is stored against the stay. |
| 8 | If "Allow Vacant Dirty check-in" is **off** for this property. | Even the manager is refused. Record which way the switch was set. |

**Pass criteria:** An unready room is refused for the agent; any override is manager-only, requires a reason, and the reason is stored.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-12 · Check-in with an unpaid required deposit

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/check-in/<reservation>` |
| **Prerequisites** | The reservation from C-06 with a deposit required and not received |
| **Test data** | The deposit policy from A-05 |
| **Severity if failed** | High — the hotel gives away a room it has not been paid for |

| # | Step | Expected result |
|---|---|---|
| 1 | Open check-in for that reservation. | A warning names the required and received deposit amounts before you act. |
| 2 | Attempt to check in. | Observe what happens and record it exactly: refused outright, or permitted with the warning. |
| 3 | Take the deposit as a payment on the folio, or record it against the reservation in Desk. | The received amount rises. |
| 4 | Return to check-in and repeat. | The warning is gone and check-in proceeds. |

**Pass criteria:** The unpaid deposit is surfaced clearly **before** the room is given away. Whether it hard-blocks or only warns is a policy decision for this hotel — record which behaviour you saw and whether it is what the hotel wants. If the hotel needs a hard block and only gets a warning, that is **High**.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### C-13 · A walk-in: no booking, guest at the desk, room tonight

| | |
|---|---|
| **Role** | Front Office Agent (with Reservation Agent if your hotel splits the roles) |
| **Surface** | `/pms` |
| **Prerequisites** | A clean room free tonight. A guest record you can use, or willingness to create one in Desk mid-scenario. |
| **Test data** | None beyond a free room |
| **Severity if failed** | **Critical** — walk-ins are revenue the hotel cannot take |

| # | Step | Expected result |
|---|---|---|
| 1 | Check **Availability** for tonight. | A room type shows availability. |
| 2 | Create a reservation for tonight through **New reservation**, using an existing guest record. | The quote appears and the booking saves. |
| 3 | Confirm it. | Badge reads Confirmed. |
| 4 | Open the **arrivals board** and refresh. | The walk-in appears in today's arrivals. |
| 5 | Check the guest in from the board. | Succeeds. |
| 6 | Time the whole sequence from step 1 to step 5. | Record the time here: `______`. A walk-in that takes a trained agent more than a few minutes is a **High** usability finding even if every step passed. |

**Pass criteria:** A guest with no booking can be sold a room and put in it, in one continuous flow, at a speed the desk can live with.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey C sign-off

Guests are in rooms. Journey D needs at least one **in-house** guest with a folio.

| | |
|---|---|
| **Scenarios passed** | ____ of 13 |
| **Critical/High defects open** | ____ |
| **Room and folio carried into Journeys D and E** | Room `______` Folio `________________` |
| **Accepted by** | ____________________ (Front Office Manager) |
| **Date** | ____________ |
