# Hospitality PMS — Front Office UAT Scenarios

**Applies to:** Hospitality PMS 16.1.0 (branch `version-16`)

**Signed by:** Front Office Manager · **Surface under test:** `/pms` (the operational
frontend), with Desk (`/desk`) used only where a step has no `/pms` screen —
each such step says so explicitly.

Written against the implementation as built. Every screen, label, button and
refusal message below is what a tester will actually see; where the workflow
has no `/pms` screen today, the scenario says so and sends you to Desk instead
of describing a button that does not exist.

Read section 3, 4 and 6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
before you start: how to run a scenario, how to log a defect, and the known
limitations that are accepted rather than defects.

**Test data you will need before you start:**

- At least two Room Types, each with several active, clean rooms, so a
  room-type-level oversell can be demonstrated without emptying the whole
  property.
- At least one Rate Plan covering those room types with rates loaded for the
  dates you will test.
- At least one existing Hospitality Guest record (not blacklisted) for the
  scenarios that need "an existing guest".
- One Hospitality Guest record with **Is Blacklisted** checked and a reason
  recorded, for FO-15. Set this up in Desk beforehand — there is no blacklist
  control in `/pms`.
- A Cancellation Policy on the property's rate plan (or reservation) that
  charges something outside its free-cancellation window, for FO-14.
- Confirm with whoever holds the Hospitality Administrator role whether this
  property has **Require ID at check-in** and **Allow Vacant Dirty check-in**
  switched on (Hospitality Property, in Desk) — several scenarios below depend
  on which way those two switches are set, and say so.
- Test users holding exactly one role each: Reservation Agent, Front Office
  Agent, Front Office Manager, Finance Manager. Testing front office as an
  administrator proves nothing about what a front desk agent can actually do.

Every reference below to a section number ("Front Office Guide §6") points at
[docs/guides/02_Front_Office_Guide.md](../guides/02_Front_Office_Guide.md),
which is the approved description of front office behaviour this set proves
against. Wording shown in angle brackets (`\<name\>`, `\<date\>`) is a
placeholder the server fills in — you will see the actual reservation name,
date or amount on screen, not the brackets.

---

## Happy paths

### FO-01  Search availability and read the per-night breakdown

**Role:** Front Office Agent
**Precondition:** At least one Room Type with active rooms and a rate plan covering it. No booking needs to exist yet.
**Reference:** Front Office Guide §2 — Finding a room

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Go to **Availability** (`/pms/availability`). | The page shows a search form: Arrival, Departure, Rooms, Adults, Children, defaulted to tonight/tomorrow, 1 room, 2 adults. |
| 2 | Set Arrival and Departure to a 2–3 night range you know has rooms free, leave Rooms at 1, and click **Search**. | One card per room type appears, each showing a headline "Available all nights" figure and the party size the room type takes. |
| 3 | Expand the per-night table under a room type. | A row per night in the stay, each showing **Sellable**, **Blocked**, **Sold** and **Available**. Available = Sellable − Blocked − Sold for that night. |
| 4 | Note which night (if any) has the lowest Available figure. | The headline figure at the top of the card equals the lowest per-night Available figure across the stay — the room type is only as bookable as its tightest night. |

**Pass criteria:** The per-night table's figures are internally consistent (Available = Sellable − Blocked − Sold) and the card's headline figure equals the minimum Available across the nights shown.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-02  Create a reservation for a new guest, see the price before saving

**Role:** Reservation Agent
**Precondition:** None beyond FO-01's test data. This scenario deliberately uses a guest who does not exist yet in the system.
**Reference:** Front Office Guide §3 — Taking a booking

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Go to **New reservation** (`/pms/reservations/new`). | Guest section defaults to "Search existing guest". |
| 2 | Switch the guest selector to **New guest**. Enter a name, email and mobile number. | Name/email/mobile fields appear in place of the guest search box. |
| 3 | Set Arrival, Departure, Rooms = 1, Adults = 2, then click **Check availability**. | A tile per bookable room type appears, each showing its available-nights figure. |
| 4 | Click a bookable room type. | The **Price** panel appears below, before you have saved anything: a line per night, then Average nightly rate, Total per room, and Total amount. |
| 5 | Read the total amount shown, then click **Save as draft**. | You are taken to the new reservation's page. Its status badge reads **Draft**, and the total shown there matches the total you read in step 4 exactly. |

**Pass criteria:** The price shown before saving and the price on the saved reservation are the same figure, and the reservation is created.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** A reservation for a guest who is only a typed name (no linked guest record) can only be saved as **Draft** here — the New reservation screen has no "create guest" action, and the server refuses to move a reservation past Draft without a linked guest (see FO-15's note on the same rule). To carry a new guest's booking further, create their Hospitality Guest record in Desk first, then build the reservation again using "Search existing guest" — which is exactly what FO-03 and FO-04 do next.

---

### FO-03  Confirm a reservation and watch availability drop

**Role:** Reservation Agent
**Precondition:** An existing (non-blacklisted) Hospitality Guest record to book. Note a date range and room type where Availability (FO-01) currently shows at least 2 rooms free.
**Reference:** Front Office Guide §3 — Confirming: the moment inventory is held

| # | Step | Expected result |
|---|------|-----------------|
| 1 | On **Availability**, search your chosen dates and room type. Note the **Available** figure for the constraining night — call it **A**. | The figure is visible in the per-night table (FO-01). |
| 2 | Go to **New reservation**, choose **Search existing guest**, and select your test guest. Set the same dates, Rooms = 1, select the same room type, and check the quote appears. | Quote panel shows a total. |
| 3 | Click **Save as tentative**. | You land on the reservation's page; status badge reads **Tentative**. |
| 4 | Click **Confirm**. | A short pause, then the status badge changes to **Confirmed**, and a "Reservation updated." toast appears. |
| 5 | Return to **Availability** and search the same dates and room type again. | The Available figure for the constraining night is now **A − 1**, and the Sold figure for that night is one higher than before. |

**Pass criteria:** Confirming succeeds and the Availability search afterwards shows Available reduced by exactly the number of rooms just confirmed.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-04  Assign a room and check the guest in

**Role:** Front Office Agent
**Precondition:** A Confirmed or Guaranteed reservation for an existing guest whose arrival date is on or before the property's current business date (shown in the app header). At least one room of the matching room type is currently Clean or Inspected on the Room Rack. If this property has **Require ID at check-in** switched on, the guest already has an identification document on file (added in Desk).
**Reference:** Front Office Guide §6 — Arrivals and check-in

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the reservation and click **Check in**. | You land on the Check-in page, one panel per room line. |
| 2 | In the **Room** dropdown for the line, select a room shown without the "(Not ready…)" suffix. | The room readiness warning panel does not appear. |
| 3 | Optionally enter billing instructions, then click **Check in**. | A short pause, then the panel shows a green **Checked in.** badge and a "Go to folio" link. |
| 4 | Go back to the reservation. | Status badge now reads **Checked In**. |
| 5 | Go to **Room Rack** (`/pms/rooms`) and find the assigned room. | The room's card shows **Occupied** occupancy. |

**Pass criteria:** Check-in succeeds only after a ready room is chosen, and the reservation, the folio link and the Room Rack all agree afterwards that the guest is in that room.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-05  Post a charge and take a payment on the folio

**Role:** Front Office Agent
**Precondition:** The folio opened at FO-04 check-in (or any other open folio for an in-house stay).
**Reference:** Front Office Guide §8 — The folio

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the folio (`/pms/folios/:id`, e.g. via "Go to folio"). | Charges and Payments panels, both showing a balance summary on the right. |
| 2 | Click **Post charge**. Choose a charge type (e.g. Room Service), enter a description and an amount, leave tax at 0, and click **Post charge**. | Dialog closes; the charge appears at the top of the Charges list with the amount you entered, and the folio's **Balance** in the summary increases by the same amount. |
| 3 | Click **Take payment**. Choose a payment method (e.g. Cash), enter an amount equal to the balance, and click **Take payment**. | Dialog closes; the payment appears in the Payments list, **Total payments** increases by that amount, and **Balance** returns to 0.00. |

**Pass criteria:** After both postings, Balance in the summary panel equals Total charges minus Total payments, exactly.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-06  Check the guest out; the room goes to Vacant Dirty

**Role:** Front Office Agent
**Precondition:** The stay from FO-04/FO-05, with the folio balance at 0.00. Confirm with an administrator that **Hospitality Settings → Auto-create housekeeping task on checkout** is switched on, so step 4 below can be observed; if it is off, expect "No housekeeping task was raised" instead and mark that line as expected, not a defect.
**Reference:** Front Office Guide §9 — Checkout

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Go to **In House** (`/pms/in-house`) and click **Checkout** next to the stay. | You land on the Checkout page. |
| 2 | Read the panel above the details. | A green panel reads "No blockers. This stay is ready to check out." and the **Check out** button is enabled. |
| 3 | Leave **Post to ERPNext on checkout** ticked and click **Check out**. | A green success panel appears: "The folio was settled and closed.", "The room was released to Vacant Dirty." and (if the setting is on) "A departure clean task was raised (\<task\>)." |
| 4 | Go to **Room Rack** and find the room. | The room's card shows **Vacant** occupancy and **Dirty** housekeeping. |
| 5 | Go back to the reservation. | Once every stay on it has left, status reads **Checked Out**. |

**Pass criteria:** The stay, folio and reservation all show as closed/checked-out, and the room's occupancy and housekeeping status match Vacant/Dirty exactly.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Exception paths

### FO-07  Oversell is refused at confirmation

**Role:** Reservation Agent
**Precondition:** An existing guest to book. A date range and room type where Availability currently shows a specific, small Available figure — note it as **N** (N ≥ 1).
**Reference:** Front Office Guide §2 ("Why a room type can show rooms free but still refuse the sale") and §3 ("Confirming")

| # | Step | Expected result |
|---|------|-----------------|
| 1 | On **Availability**, confirm the Available figure for your chosen room type/dates is **N**. | As before. |
| 2 | Go to **New reservation**, existing guest, same dates, same room type, but set **Rooms = N + 1**, then **Check availability**. | The room type tile shows in red/not-bookable styling with "N Available all nights" — it can still be clicked. |
| 3 | Click the room type anyway, confirm a quote appears, then **Save as tentative**. | The reservation saves; status **Tentative**. Nothing is refused yet — Tentative does not hold inventory. |
| 4 | Open the reservation and click **Confirm**. | Confirm fails. The error shown reads exactly: *"Only N room(s) of type \<room type\> are available on \<date\>; N+1 requested."* |
| 5 | Reload the reservation. | Status is still **Tentative** — the confirm did not partially apply. |
| 6 | Re-check Availability for the same dates/room type. | Available is still **N** — nothing was held. |

**Pass criteria:** Confirm is refused with the exact "Only N room(s)… requested" message, the reservation stays Tentative, and Availability is unchanged.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-08  Check-in before the arrival date is refused

**Role:** Front Office Agent
**Precondition:** A Confirmed or Guaranteed reservation for an existing guest whose arrival date is **after** the property's current business date (shown in the app header).
**Reference:** Front Office Guide §6, check 3

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the reservation and click **Check in**. | Check-in page loads. An amber panel reads: "The arrival date (\<date\>) has not yet been reached." |
| 2 | Select any ready room in the **Room** dropdown for the line. | Room selected; no readiness warning (the room itself is fine). |
| 3 | Click **Check in**. | The attempt fails. An error appears under that line reading exactly: *"Reservation \<name\> arrives on \<date\>; the business date is \<date\>."* |
| 4 | Reload the reservation. | Status is unchanged (still Confirmed/Guaranteed); no stay or folio was created. |

**Pass criteria:** Check-in is refused with the exact "arrives on … business date is …" message, and no Stay or Folio exists afterwards for that room line.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-09  Check-in to a room that is not clean, then a manager override

**Role:** Front Office Agent (steps 1–4), then Front Office Manager (steps 5–8)
**Precondition:** A Confirmed reservation for an existing guest, arrival due today. At least one otherwise-assignable room of the matching room type has Housekeeping status **Dirty** (set it yourself via Room Rack → open the room → Change status → Housekeeping → Dirty, if none already is). Confirm with an administrator that **Allow Vacant Dirty check-in** is switched on for this property — the override itself is refused outright if it is not, whoever asks.
**Reference:** Front Office Guide §6 — "The Vacant Dirty override"

| # | Step | Expected result |
|---|------|-----------------|
| 1 | As **Front Office Agent**, open the reservation, click **Check in**, and select the Dirty room from the **Room** dropdown (it is listed with a "(Not ready (Vacant Dirty))" suffix). | An amber panel appears: "Not ready (Vacant Dirty)", followed by "Ask a Front Office Manager to override an unready room." No override checkbox is shown. |
| 2 | Try to click **Check in**. | The button is disabled — you cannot submit. |
| 3 | Sign out. | — |
| 4 | Sign in as **Front Office Manager** and reopen the same Check-in page. | Same amber panel, but this time an "I confirm assigning a room that is not ready" checkbox and a reason field are shown. |
| 5 | Select the same Dirty room. Tick the checkbox and enter a reason, e.g. "Only room available for an early arrival, cleaning in progress." | The **Check in** button becomes enabled. |
| 6 | Click **Check in**. | Succeeds: green "Checked in." badge and a "Go to folio" link appear. |
| 7 | In Desk, open the new **Hospitality Stay** record. | The **Readiness Override** checkbox is ticked and **Readiness Override Reason** shows exactly the text you entered in step 5. |

**Pass criteria:** A Front Office Agent cannot check in to the dirty room under any circumstances (button stays disabled); a Front Office Manager can, only after ticking the box and giving a reason, and that reason is visible afterwards on the Stay record in Desk.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** The override reason is not shown anywhere in `/pms` — only on the Hospitality Stay record in Desk.

---

### FO-10  Check-in with an unpaid required deposit is refused

**Role:** Front Office Agent
**Precondition:** A Confirmed reservation for an existing guest, arrival due today, with a **Deposit Required** amount greater than the **Deposit Received** amount. Set both fields on the Hotel Reservation record in Desk beforehand — there is no deposit field on the `/pms` reservation screens.
**Reference:** Front Office Guide §6, check 6

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the reservation and click **Check in**. | An amber panel reads: "A deposit of \<required\> is required; \<received\> has been received." |
| 2 | Select a ready room and click **Check in**. | The attempt fails. An error appears under the line reading exactly: *"A deposit of \<required\> is required; \<received\> has been received."* |
| 3 | Reload the reservation. | Status unchanged; no stay or folio was created. |

**Pass criteria:** Check-in is refused with the exact deposit message and the reservation's deposit figures are unchanged.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** Once the deposit is topped up (in Desk, or by taking a payment against the reservation before it holds a folio), check-in should be re-tried to confirm it now succeeds — not required for this scenario's pass mark, but worth doing while the data is set up.

---

### FO-11  Changing a confirmed reservation's arrival date is refused

**Role:** Front Office Manager
**Precondition:** Any reservation currently Confirmed, Guaranteed or Checked In (for example, the one from FO-03 or FO-04).
**Reference:** Front Office Guide §4 — "What can change after confirmation, and what cannot"

| # | Step | Expected result |
|---|------|-----------------|
| 1 | In Desk, open the **Hotel Reservation** record. | There is no field-lock warning shown up front — the fields are editable in the form. |
| 2 | Change **Arrival Date** to a different date and click **Save**. | Save is refused. The error reads exactly: *"Arrival Date cannot be changed once a reservation is \<status\>; cancel and rebook instead."* (with the reservation's actual status in place of \<status\>). |
| 3 | Reload the document. | Arrival Date is unchanged from before your edit. |

**Pass criteria:** The save is refused with the exact "cancel and rebook instead" message, and the arrival date is unchanged.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** There is no screen in `/pms` for editing an existing reservation's dates at all; this is a Desk-only action, and the refusal is enforced the same way regardless of which surface is used.

---

### FO-12  A posted folio charge cannot be edited; only reversed

**Role:** Front Office Manager (steps 1–3, Desk), then Finance Manager (steps 4–7, `/pms`)
**Precondition:** An open folio with at least one posted charge (e.g. from FO-05).
**Reference:** Front Office Guide §8 — "Why a mistake is corrected by reversal, never by editing"

| # | Step | Expected result |
|---|------|-----------------|
| 1 | In Desk, open the **Hospitality Guest Folio** record for that folio. | The Charges child table shows the posted charge row. |
| 2 | Change the **Amount** on that row and click **Save**. | Save is refused. The error reads exactly: *"Charge \<row\> is posted and cannot be edited; correct it with a reversal instead."* |
| 3 | Reload the document. | The charge's amount is unchanged. |
| 4 | As **Finance Manager**, open the same folio at `/pms/folios/:id` and click **Reverse** next to the charge. | A dialog opens, warning: "A correction is a reversal, not an edit. This posts a compensating line for the same amount; the original charge stays on the folio and is marked reversed." |
| 5 | Enter a reason and click **Reverse charge**. | Dialog closes. |
| 6 | Look at the Charges panel. | The original charge now shows struck through with a **Reversed** badge, and directly beneath it, indented, a line reading "Reversal of \<description\>" for the same amount. |
| 7 | Check the Balance in the summary panel. | It has moved by exactly the reversed amount — both lines are visible, nothing was deleted. |

**Pass criteria:** The direct edit in Desk is refused with the exact message; the reversal in `/pms` succeeds and both the original (marked Reversed) and its compensating line remain visible together.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** A Front Office Manager cannot perform the reversal itself — only Finance Manager, Accounts User, Hospitality Administrator or System Manager may. If a Front Office role attempts the **Reverse** button, expect: *"This action requires one of the following roles: Finance Manager, Accounts User, Hospitality Administrator, System Manager."*

---

### FO-13  Checkout with an outstanding balance is blocked, then cleared

**Role:** Front Office Agent
**Precondition:** An in-house stay whose folio has a balance above zero (post a charge on the folio and do not pay it, e.g. step 2 of FO-05 without step 3).
**Reference:** Front Office Guide §9 — "Blockers you may see, and how to clear each"

| # | Step | Expected result |
|---|------|-----------------|
| 1 | From **In House**, click **Checkout** for the stay. | Checkout page loads. |
| 2 | Read the panel above the details. | A red panel reads "Resolve the following before checking out" and lists: *"The folio has an outstanding balance of \<amount\>."* |
| 3 | Try to click **Check out**. | The button is disabled — you cannot submit. |
| 4 | Click **Go to folio**, take a payment for at least the outstanding amount, then return to the Checkout page and refresh the browser (the blockers do not update automatically without a reload). | The red panel is gone; a green panel reads "No blockers. This stay is ready to check out." and **Check out** is now enabled. |
| 5 | Click **Check out**. | Succeeds, as in FO-06. |

**Pass criteria:** Check out stays disabled and shows the exact balance blocker while money is owed, and becomes available the moment the balance reaches zero.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FO-14  Cancel a reservation: policy charge applied, inventory released

**Role:** Reservation Agent
**Precondition:** A Confirmed reservation (holding inventory) whose cancellation policy charges something for cancelling now — check with a Reservation Manager which policy is configured that way, or set the Hotel Reservation's Cancellation Policy field in Desk to one with a non-zero charge basis and confirm you are cancelling outside its free-cancellation window.
**Reference:** Front Office Guide §4 — "Cancelling"

| # | Step | Expected result |
|---|------|-----------------|
| 1 | On **Availability**, note the Available figure for the reservation's room type and dates. | As in FO-01/FO-03. |
| 2 | Open the reservation and click **Cancel booking**. | Dialog opens: "This releases the held inventory and may apply a cancellation charge under the booking's policy." |
| 3 | Try clicking **Cancel reservation** with the reason field left blank. | The confirm button stays disabled — a reason is required before you can submit. |
| 4 | Enter a reason and click **Cancel reservation**. | Dialog closes; status badge changes to **Cancelled**; "Reservation updated." toast appears. |
| 5 | In Desk, open the same Hotel Reservation record and check the **Cancellation Charge** field. | It shows a non-zero amount, computed from the policy's basis (fixed amount, percentage of the stay, full stay, or the first night's rate, whichever the policy uses). |
| 6 | Return to **Availability** and search the same dates/room type again. | Available has returned to (at least) the figure noted in step 1 — the room(s) held by this reservation are released. |

**Pass criteria:** Cancellation is refused without a reason, succeeds with one, the Cancellation Charge field shows a non-zero amount consistent with the configured policy, and Availability shows the inventory released.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** `/pms` does not display the computed cancellation charge or offer to waive it — check the amount, and waive a charge if needed, in Desk.

---

### FO-15  Booking a blacklisted guest is refused

**Role:** Reservation Agent
**Precondition:** A Hospitality Guest record with **Is Blacklisted** checked and a reason recorded (set up in Desk beforehand).
**Reference:** Front Office Guide §5 — "What to do when a guest is flagged" / §11

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Go to **New reservation**, **Search existing guest**, and type the blacklisted guest's name. | The guest still appears in the search results — a Reservation Agent is cleared to see the blacklist flag. |
| 2 | Select them, set dates, Rooms = 1, check availability, select a room type, and confirm a quote appears. | As in FO-02/FO-03. |
| 3 | Click **Save as tentative**. | Saving fails. The error reads exactly: *"Guest \<name\> is blacklisted: \<reason\>."* (or "no reason recorded" if none was set). No reservation is created. |
| 4 | With the same guest and details, click **Save as draft** instead. | This succeeds — Draft is exempt from the blacklist check. |

**Pass criteria:** Saving as Tentative is refused with the exact blacklist message and reason, and no reservation is created by the failed attempt; saving the same details as Draft succeeds.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** The same refusal applies to check-in (Front Office Guide §6, check 4) — a blacklisted guest already on a Draft/Cancelled reservation can never be checked in, since check-in itself calls the same blacklist check.

---

**Sign-off for this set:** recorded in section 7 of
[01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md).
