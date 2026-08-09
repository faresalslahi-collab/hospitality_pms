# Journey B — Sell a room and take the booking

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Reservation Manager
**Surface:** `/pms` throughout, except where a step says Desk.

From "do you have a room on the 14th?" to inventory held. This journey ends with
a confirmed booking that Journey C will check in, so run it before C.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first. Reference sections point at
[Front Office Guide](../guides/02_Front_Office_Guide.md).

**Prerequisites for the whole journey:** Journey A passed. Two room types with
rates loaded, at least eight rooms, a cancellation policy and a deposit policy.

**Test data to prepare before you start:**

- One **existing** Guest, not blacklisted — created in Desk.
- One Guest with **Is Blacklisted** ticked and a reason recorded, for **B-07**. There is no blacklist control in `/pms`; set it up in Desk.
- A date range 5–10 days out where you know both room types have rooms free.

Wording in angle brackets (`<name>`, `<date>`) is a placeholder the server fills
in — you will see the real reservation number or date on screen.

---

### B-01 · Availability search, and the per-night arithmetic behind it

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/availability` |
| **Prerequisites** | A-04 and A-05 passed |
| **Test data** | A 2–3 night range with rooms free |
| **Severity if failed** | Critical — the hotel cannot answer its most common question |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Availability**. | A search form: Arrival, Departure, Rooms, Adults, Children, defaulted to tonight/tomorrow, 1 room, 2 adults. |
| 2 | Set your date range, Rooms = 1, and search. | One card per room type, each showing a headline available figure and the party size the type takes. |
| 3 | Expand the per-night table under a room type. | A row per night showing **Sellable**, **Blocked**, **Sold** and **Available**. |
| 4 | Check the arithmetic on any night. | Available = Sellable − Blocked − Sold. |
| 5 | Compare the headline figure to the per-night rows. | The headline equals the **lowest** Available across the nights — a room type is only as bookable as its tightest night. |
| 6 | Search with Adults set above the room type's max occupancy. | That room type is shown as not fitting the party, rather than silently offered. |

**Pass criteria:** The arithmetic is internally consistent, the headline is the minimum across nights, and an over-sized party is refused rather than sold.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-02 · The reservation calendar shows the shape of the week — NEW in 16.2.0

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/calendar` |
| **Prerequisites** | A-04 passed. More meaningful once B-04 has created a booking — consider running this scenario twice, before and after. |
| **Test data** | None beyond room inventory |
| **Severity if failed** | High — the hotel can still trade from Availability, but nobody can see the shape of the coming fortnight |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Calendar** from the Bookings section of the sidebar. | A grid: rooms down the side, dates across the top, starting from the property's business date and showing 14 days. |
| 2 | Read the controls above the grid. | From, Days shown (7/14/21/28), Room type, Today, Previous, Next, Refresh. |
| 3 | Set Days shown to 28. | The grid redraws with 28 date columns. It scrolls sideways inside its own frame; the page itself does not scroll sideways. |
| 4 | Click **Next**, then **Previous**, then **Today**. | The window moves forward 28 days, back 28 days, then returns to the business date. |
| 5 | Filter by one room type. | Only that type's rooms are listed; the room count line below the grid changes to match. |
| 6 | If the property has more rooms than fit one page, use the paging control below the grid. | The visible page of rooms is **replaced**, not appended. The count line reads "Rooms *n* of *total*". |
| 7 | Find an occupied room and read its bar. | The bar spans the nights occupied and carries the guest's name as text. A guest departing on the 9th does not occupy the night of the 9th. |
| 8 | Click a bar belonging to a reservation or stay. | The reservation opens. |
| 9 | Read the legend and the **Booked without a room** panel below the grid. | Legend shows In house / Reserved / Blocked. The panel lists rooms sold in this window that still need a room assigned, each linking to its reservation. |

**Pass criteria:** The grid is readable, the date window moves as expected, bars match the nights actually occupied, and unassigned demand is visible rather than hidden.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-03 · Quote the price before anything is saved

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/reservations/new` |
| **Prerequisites** | B-01 passed |
| **Test data** | Deliberately a guest who does **not** exist yet |
| **Severity if failed** | High — an agent who cannot quote before saving will quote from memory |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **New reservation**. | The guest section defaults to "Search existing guest". |
| 2 | Switch to **New guest** and enter a name, email and mobile. | Those fields replace the guest search box. |
| 3 | Set arrival, departure, Rooms = 1, Adults = 2, then **Check availability**. | A tile per bookable room type with its available-nights figure. |
| 4 | Click a bookable room type. | A **Price** panel appears *before* anything is saved: a line per night, then average nightly rate, total per room and total amount. |
| 5 | Note the total, then **Save as draft**. | You land on the new reservation. Status badge reads **Draft** and the total matches step 4 exactly. |

**Pass criteria:** The quoted price and the saved price are the same figure.

**Known behaviour, not a defect:** a reservation for a typed-in guest with no
linked guest record can only be saved as **Draft**. The server refuses to move a
reservation past Draft without a real guest record, and this screen has no
"create guest" action. To carry a new guest further, create their Hospitality
Guest record in Desk first, then book using "Search existing guest" — which is
what B-04 does. Raise this only if the hotel considers it unworkable at the desk;
if so it is **High**, not Low.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-04 · Confirm a booking and watch inventory drop

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/availability`, `/pms/reservations/new`, `/pms/reservations/<name>` |
| **Prerequisites** | B-01 passed. An existing, non-blacklisted guest record. |
| **Test data** | A date range and room type where Availability currently shows **at least 2** rooms free |
| **Severity if failed** | Critical — this is the moment inventory is held; if it does not hold, the hotel oversells |

| # | Step | Expected result |
|---|---|---|
| 1 | On **Availability**, search your dates and room type. Note the Available figure on the constraining night — call it **A**. | The figure is visible in the per-night table. |
| 2 | On **New reservation**, choose **Search existing guest** and pick your test guest. Set the same dates, Rooms = 1, same room type. | The quote panel shows a total. |
| 3 | **Save as tentative**. | You land on the reservation; badge reads **Tentative**. |
| 4 | Click **Confirm**. | A short pause, then the badge changes to **Confirmed** and a "Reservation updated" toast appears. |
| 5 | Return to Availability and search the same dates and type. | Available on the constraining night is now **A − 1**, and Sold is one higher. |
| 6 | Note the reservation number. | **Journey C needs it.** Write it here: `________________` |

**Pass criteria:** Confirmation succeeds and availability falls by exactly the number of rooms confirmed.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-05 · Guarantee a booking

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/reservations/<name>` |
| **Prerequisites** | A confirmed reservation from B-04, or a second one created the same way |
| **Test data** | None |
| **Severity if failed** | Medium — the booking still holds inventory; the guarantee affects no-show charging |

| # | Step | Expected result |
|---|---|---|
| 1 | Open a **Confirmed** reservation. | Its available actions include **Guarantee**. |
| 2 | Click Guarantee and choose a guarantee type (for example Credit Card). | The badge changes to **Guaranteed** and the guarantee type is shown on the record. |
| 3 | Look for the guaranteed-on timestamp. | Recorded against the reservation. |

**Pass criteria:** The reservation reaches Guaranteed with its type and timestamp recorded.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-06 · The reservation list finds a booking the way the desk would

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/reservations` |
| **Prerequisites** | At least two reservations exist (B-04, B-05) |
| **Test data** | The guest name and reservation number from B-04 |
| **Severity if failed** | High — a guest standing at the desk cannot be found |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Reservations**. | A list with search, status, from-date and to-date filters. |
| 2 | Type part of the guest's **surname** into search and press Enter. | The booking appears. |
| 3 | Clear search and type the **reservation number** instead. | The same booking appears. |
| 4 | Set Status to **Confirmed**. | Only confirmed bookings are listed. |
| 5 | Set a date range that excludes your booking's stay entirely. | It disappears from the list. |
| 6 | Set a range that overlaps only the middle of the stay. | It **is** listed — a stay spanning the window belongs in it. |
| 7 | Click a row. | The reservation opens. |

**Pass criteria:** A booking can be found by guest name and by number, and the date filter treats an overlapping stay as in range.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-07 · Oversell is refused at confirmation, not at save

| | |
|---|---|
| **Role** | Reservation Agent, then Front Office Manager |
| **Surface** | `/pms` |
| **Prerequisites** | B-01 passed |
| **Test data** | A room type and single night where Available is a small number you can exhaust — a second room type exists so the property is not emptied |
| **Severity if failed** | **Critical** — a system that lets the last room be sold twice will sell it twice |

| # | Step | Expected result |
|---|---|---|
| 1 | Note Available for one room type on one night — call it **A**. | Visible on Availability. |
| 2 | Create and **confirm** bookings for that type and night until Available reaches 0. | Each confirms; Available falls by one each time. |
| 3 | Create one more booking for the same type and night and save it as Tentative. | The save **succeeds** — a tentative booking holds nothing. |
| 4 | Click **Confirm** on it. | **Refused**, with a message naming the room type and the night that is full. The badge stays Tentative. |
| 5 | Re-check Availability. | Still 0. The refused confirmation held nothing. |
| 6 | Sign in as a **Front Office Manager** and confirm the same reservation with the overbooking option and a reason. | Permitted, and the reason is recorded. If your hotel does not want managers to be able to do this, that is a policy finding — record it here. |

**Pass criteria:** The confirmation is refused for the agent, availability is unchanged by the refusal, and any manager override is recorded with a reason.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-08 · A restriction stops a sale the rate plan does not want

| | |
|---|---|
| **Role** | Revenue Manager (to set), Reservation Agent (to hit) |
| **Surface** | Desk → Rates and Revenue → Room Inventory Restriction, then `/pms/reservations/new` |
| **Prerequisites** | A-05 passed |
| **Test data** | One night in your test range on which you will set a restriction, then remove it |
| **Severity if failed** | High — revenue management cannot close a date, and the hotel sells inventory it meant to hold |

| # | Step | Expected result |
|---|---|---|
| 1 | As Revenue Manager, create a **Room Inventory Restriction** for one room type on one night, with **Stop sell** ticked. | Saves. |
| 2 | As Reservation Agent, try to quote a stay covering that night for that room type. | **Refused** with a message that the room type is closed for sale on that date. |
| 3 | Change the restriction: untick Stop sell, tick **Closed to arrival**. | Saves. |
| 4 | Quote a stay **arriving** on that night. | Refused — arrivals are closed on that date. |
| 5 | Quote a stay that **passes through** that night but arrives earlier. | Permitted. |
| 6 | Replace it with a **Minimum length of stay** of 3 nights and quote a 1-night stay covering it. | Refused, naming the minimum. |
| 7 | Quote a 3-night stay covering it. | Permitted. |
| 8 | Remove the restriction. | Quoting works normally again. |

**Pass criteria:** Each of the three restriction types refuses exactly the sale it is meant to refuse, and nothing else.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-09 · Booking a blacklisted guest is refused

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/reservations/new` |
| **Prerequisites** | A guest record with **Is Blacklisted** ticked and a reason, created in Desk |
| **Test data** | That guest |
| **Severity if failed** | **Critical** — a permission and safety boundary crossed |

| # | Step | Expected result |
|---|---|---|
| 1 | On **New reservation**, search for the blacklisted guest by name. | They appear in the search results — the desk must be able to see who they are dealing with. |
| 2 | Select them and complete a valid quote. | The quote may be produced. |
| 3 | Save the reservation. | **Refused**, with a message that the guest is blacklisted. |
| 4 | Read the refusal. | It says the guest is blacklisted. Confirm whether it also exposes the blacklist **reason** to a front-desk agent, and note what you see — the reason is meant to be management-only. |
| 5 | Check that no reservation was created. | The reservation list contains nothing new for that guest. |

**Pass criteria:** The booking is refused and no record is created. Whether the reason leaks to the agent is a privacy finding — Journey J tests it directly (**J-07**).

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-10 · A confirmed booking's dates cannot be quietly edited

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | Desk → Reservations → Reservation (this rule is enforced wherever the record is edited) |
| **Prerequisites** | A Confirmed reservation from B-04 |
| **Test data** | None |
| **Severity if failed** | **Critical** — inventory held for one date range would silently move to another |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the confirmed reservation in Desk. | It opens. |
| 2 | Change the **Arrival date** and save. | **Refused**, with a message that the field cannot be changed once the reservation is Confirmed and that you should cancel and rebook instead. |
| 3 | Try the same with **Departure date**, then **Property**, then **Guest**. | Each is refused the same way. |
| 4 | Change a field that is *not* protected — internal notes, say — and save. | Permitted. |
| 5 | Re-check availability for the original dates. | Unchanged. Nothing moved. |

**Pass criteria:** All four protected fields are refused on a confirmed booking, and unprotected fields still save.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-11 · Cancel a booking: policy charge applied, inventory released

| | |
|---|---|
| **Role** | Reservation Agent, then Front Office Manager |
| **Surface** | `/pms/reservations/<name>` |
| **Prerequisites** | A Confirmed reservation whose arrival is **inside** the cancellation policy's charging window (A-05) |
| **Test data** | The cancellation policy from A-05 |
| **Severity if failed** | High — the hotel either loses the fee or fails to release the room |

| # | Step | Expected result |
|---|---|---|
| 1 | Note Available for the booking's room type and dates. | Call it **A**. |
| 2 | Open the reservation and click **Cancel**. | A dialog asks for a **reason**, and warns what cancelling does. |
| 3 | Try to confirm the cancellation with the reason left empty. | Refused — the reason is mandatory. |
| 4 | Enter a reason and confirm. | Badge changes to **Cancelled**. The cancellation charge from the policy is shown on the record. |
| 5 | Re-check availability for those dates. | Available is back to **A** — the room is released. |
| 6 | Check who and when. | The record shows cancelled-by and cancelled-on, and the reason you typed. |
| 7 | Try to cancel a booking that is already cancelled. | Refused. |

**Pass criteria:** Cancellation requires a reason, applies the policy charge, releases inventory, and is attributable.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### B-12 · Find a guest and read what the hotel knows about them

| | |
|---|---|
| **Role** | Front Office Agent or Guest Relations Officer |
| **Surface** | `/pms/guests` and `/pms/guests/<guest>` |
| **Prerequisites** | Several guest records, at least one with previous stays |
| **Test data** | A guest with identification recorded, one alert, and a stated preference — set these up in Desk beforehand |
| **Severity if failed** | High — the desk cannot recognise a returning guest, and recognising them is most of hospitality |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Guests** from the sidebar. | A search box. The list is not pre-loaded with every guest the hotel has ever had. |
| 2 | Search by part of a surname. | Matching guests appear. |
| 3 | Search by email, then by mobile number. | Each finds the guest. |
| 4 | Search for something that matches nothing. | A clear empty message, not an error. |
| 5 | Open a guest's profile. | Name, contact details, VIP status, guest type, and aggregate stay history — total stays, total nights, last stay. |
| 6 | Look for the guest's **alerts** and **preferences**. | Alerts are shown. Record whether preferences, dietary requirements and accessibility requirements are visible — the desk needs them to prepare the room. |
| 7 | Look for an **itemised list of past stays**. | **Known limitation:** the profile shows aggregate figures only; there is no per-stay list. Confirm whether the desk can work without it. ☐ Yes ☐ No |
| 8 | Compare the aggregate figures to the guest's actual history in Desk. | They agree. |
| 9 | As a **Room Attendant**, try to open `/pms/guests`. | Refused — Journey J-02 covers this boundary in full. |

**Pass criteria:** A guest can be found by name, email and mobile, and their profile tells the desk enough to recognise and prepare for them. Step 7's answer is a recorded finding, not a defect — it is a known limitation in §7 of the plan.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey B sign-off

The hotel can quote, sell, refuse and cancel. At least one **Confirmed or
Guaranteed** booking arriving on the business date must exist before Journey C.

| | |
|---|---|
| **Scenarios passed** | ____ of 12 |
| **Critical/High defects open** | ____ |
| **Reservation number carried into Journey C** | ____________________ |
| **Accepted by** | ____________________ (Reservation Manager) |
| **Date** | ____________ |
