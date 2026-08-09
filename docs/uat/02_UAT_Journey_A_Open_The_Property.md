# Journey A — Open the property for business

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Hospitality Administrator
**Surface:** Desk (`/desk`) throughout. Property configuration deliberately has no
`/pms` screen — it is set up once and then lived in, and putting it behind the
operational frontend would invite a receptionist to change the accounting mapping.

This journey takes a property from empty to able to trade. Everything Journeys
B–J do depends on it. Run it in order; each scenario builds on the one before.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first. Reference sections point at
[Administrator and Setup Guide](../guides/01_Administrator_and_Setup_Guide.md).

---

### A-01 · The property exists, with a business date and a company behind it

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Hospitality PMS → Setup → Hospitality Property |
| **Prerequisites** | ERPNext Company exists with a default currency and a Cost Center. Site is freshly installed and migrated. |
| **Test data** | Property code, name, country, time zone, and the ERPNext Company this property trades as. Decide the opening business date now — normally today. |
| **Severity if failed** | Critical — nothing else in the system can be configured or operated |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Hospitality Property** and create a new record. Fill property code, name, company, currency, country, time zone. | The form saves. Currency and company are the ERPNext ones, not free text. |
| 2 | Set **Business date** to today and save. | The business date is stored and shown. |
| 3 | Set check-in and check-out times, and rounding precision. | Values save and are shown on the record. |
| 4 | Note the **Total rooms** field. | It reads 0 or blank — no rooms exist yet. |
| 5 | Open `/pms` in another tab and sign in as the same user. | The property selector at the top of the sidebar lists this property, and the business date shown matches step 2. |

**Pass criteria:** The property is created with a business date, and `/pms` picks it up as the active property with the same date.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-02 · Physical structure: buildings, floors, wings, zones

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Setup → Hospitality Building / Floor / Wing / Zone |
| **Prerequisites** | A-01 complete |
| **Test data** | At least one building, two floors, and one housekeeping zone. Use this hotel's real names — the point is to find out whether the structure fits. |
| **Severity if failed** | High — room inventory can exist without it, but housekeeping allocation and the room rack become unusable |

| # | Step | Expected result |
|---|---|---|
| 1 | Create one **Hospitality Building** against the property. | Saves, linked to the property from A-01. |
| 2 | Create two **Hospitality Floor** records under that building. | Both save and show their building. |
| 3 | Create one **Hospitality Zone**. | Saves. |
| 4 | Try to create a floor against a property that does not exist. | Refused — the link field offers only existing properties. |

**Pass criteria:** The hotel's real physical structure can be expressed. If it cannot — for example this property has structure the model has no field for — that is the finding, and it is High, not Low.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-03 · Room types, occupancy limits and display order

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Rooms → Room Type |
| **Prerequisites** | A-01 complete |
| **Test data** | At least **two** room types. Two is the minimum that makes an oversell demonstrable in Journey B without emptying the property. |
| **Severity if failed** | Critical — availability, rates and booking all key off room type |

| # | Step | Expected result |
|---|---|---|
| 1 | Create a room type with a code, name, base occupancy, max occupancy and display order. | Saves against the property. |
| 2 | Create a second room type with a different code. | Saves. |
| 3 | Set max occupancy lower than base occupancy on one of them and save. | Refused with a message naming the two figures. |
| 4 | Correct it and save. | Saves. |

**Pass criteria:** Two room types exist, and an impossible occupancy pair is refused rather than stored.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-04 · Room inventory, and the four status dimensions

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Rooms → Hotel Room, then `/pms/rooms` |
| **Prerequisites** | A-02 and A-03 complete |
| **Test data** | At least **eight** rooms spread across the two room types, so availability arithmetic is visible and an oversell in Journey B is reachable. |
| **Severity if failed** | Critical — no inventory, no hotel |

| # | Step | Expected result |
|---|---|---|
| 1 | Create eight Hotel Rooms across the two room types, each with a room number, floor and Active ticked. | All eight save. |
| 2 | Look at the status fields on one room. | Four **separate** fields: Occupancy, Housekeeping, Maintenance, Inventory. New rooms default to Vacant / Clean / Operational / Available. |
| 3 | Set one room's Maintenance status to **Out of Order** and save. | Saves. The room's Occupancy status is untouched — it is still Vacant. |
| 4 | Open `/pms/rooms` (Room Rack). | All eight rooms appear grouped by room type. The out-of-order room is visibly marked and shows its blocking reason. |
| 5 | Read the summary strip at the top of the rack. | Rooms, Occupied, Vacant, Ready, Dirty, Out of order and Assignable counts. Out of order reads 1; Assignable is 7. |
| 6 | Return the room to **Operational** and refresh the rack. | Assignable returns to 8. |

**Pass criteria:** Eight rooms exist; the four status dimensions are independent of one another; the rack's counts agree with what you set.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-05 · A rate plan with real rates, and the policies attached to it

| | |
|---|---|
| **Role** | Hospitality Administrator (or Revenue Manager) |
| **Surface** | Desk → Rates and Revenue → Hospitality Rate Plan, Hospitality Daily Rate, Hospitality Rate Policy |
| **Prerequisites** | A-03 complete |
| **Test data** | One rate plan covering **both** room types, with daily rates loaded for a date range at least 30 days into the future. One cancellation policy that charges something outside its free window, and one deposit policy that requires a deposit — Journeys B and C both need these. |
| **Severity if failed** | Critical — a room with no rate cannot be sold |

| # | Step | Expected result |
|---|---|---|
| 1 | Create a **Hospitality Rate Plan** covering both room types. | Saves. |
| 2 | Load **Hospitality Daily Rate** rows for both room types across your test date range. | Rows save with a rate per room type per date. |
| 3 | Create a **Hospitality Rate Policy** of cancellation type that charges a fee outside a free-cancellation window, and attach it. | Saves and is linked. |
| 4 | Create a deposit policy requiring a deposit, and attach it. | Saves and is linked. |
| 5 | Sign in to `/pms` as a Reservation Agent and open **Availability**. Search a date in range. | Rates appear against both room types. A room type with no rate loaded for a night shows as unsellable for that night rather than as free. |

**Pass criteria:** Both room types are priced across the test range, and the two policies exist for Journey B to exercise.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-06 · Charges map to ERPNext, or nothing will post

| | |
|---|---|
| **Role** | Hospitality Administrator with Finance Manager, together |
| **Surface** | Desk → Setup → Hospitality Posting Profile, Hospitality Charge Item Map |
| **Prerequisites** | A-01 complete. ERPNext Items exist for room revenue and at least one incidental (minibar, laundry, or similar), each with an income account. |
| **Test data** | One posting profile for this property, mapping **Room Charge** and at least one other charge type to real ERPNext Items. |
| **Severity if failed** | Critical — checkout will fail to post and revenue will not reach the ledger |

| # | Step | Expected result |
|---|---|---|
| 1 | Create a **Hospitality Posting Profile** for the property. | Saves. |
| 2 | Map **Room Charge** to an ERPNext Item that has an income account. | Row saves. |
| 3 | Map one further charge type (for example Minibar) to a second Item. | Row saves. |
| 4 | Deliberately leave one charge type unmapped and note which. | No error yet — the gap only bites when something of that type is posted. Journey G (**G-03**) tests exactly that, so keep the note. |
| 5 | Confirm the property's ERPNext company, cost center and receivable account are set. | All three present on the property record. |

**Pass criteria:** Room Charge maps to a real Item; the mapping is complete enough for Journey E to check a guest out and Journey G to see a Sales Invoice.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-07 · Roles exist, and the operational ones have no Desk

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Users → Role, and Desk → Users → User |
| **Prerequisites** | A-01 complete. App installed, so `after_install` has created the roles. |
| **Test data** | One user per role listed in §4 of the plan, each holding exactly one hospitality role. |
| **Severity if failed** | Critical — Journey J cannot run, and permission boundaries are a substantial part of what is being accepted |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the Role list and filter for the hospitality roles. | All 22 approved roles exist. |
| 2 | Open **Front Office Agent**, **Reservation Agent**, **Room Attendant**, **Maintenance Technician**, **Kitchen User** and **Guest Relations Officer**. | Each has **Desk access unticked**. These roles work only in `/pms`. |
| 3 | Open **Front Office Manager**, **Finance Manager**, **Night Auditor**, **Hospitality Administrator**. | Each has Desk access ticked. |
| 4 | Create your test users, one role each. | All save. |
| 5 | Sign in as the Front Office Agent test user and go to `/desk`. | You are not given the Desk. Signing in and going to `/pms` works normally. |

**Pass criteria:** The six frontend-only roles genuinely cannot open Desk, and the management roles can. Note that Desk access is a usability switch, not the security boundary — Journey J tests the real one.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### A-08 · A second property, and a user who may only see one

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Setup → Hospitality Property; Desk → Users → User Permission; then `/pms` |
| **Prerequisites** | A-01 complete |
| **Test data** | A second Hospitality Property (it needs no rooms — it exists to prove isolation). One test user restricted to the first property by a User Permission. |
| **Severity if failed** | Critical — a group operator would see another hotel's guests and money |
| **Skip if** | This deployment will only ever run one property. Record that decision here rather than marking the scenario Pass. |

| # | Step | Expected result |
|---|---|---|
| 1 | Create a second Hospitality Property with its own code and business date. | Saves. |
| 2 | Sign in to `/pms` as an unrestricted user (Hotel Manager). | The property selector offers **both** properties and switching between them changes the dashboard figures. |
| 3 | Add a **User Permission** on Hospitality Property for your Front Office Agent test user, allowing only the first property. | Saves. |
| 4 | Sign in to `/pms` as that agent. | The property selector offers **only** the permitted property. The second is not listed. |
| 5 | With that agent still signed in, edit the browser address to a screen belonging to the other property — for example open a reservation you noted from the second property at `/pms/reservations/<name>`. | Refused, with a message about not having access to that property. Not a blank screen, and not another property's data. |

**Pass criteria:** A restricted user cannot see or reach the second property by any route tested, including a direct link.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey A sign-off

The property is configured and can trade. Journeys B–J assume everything above
passed.

| | |
|---|---|
| **Scenarios passed** | ____ of 8 |
| **Critical/High defects open** | ____ |
| **Accepted by** | ____________________ (Hospitality Administrator) |
| **Date** | ____________ |
