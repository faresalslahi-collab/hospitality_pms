# Journey E — Departure and settlement

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Front Office Manager
**Surface:** `/pms` throughout.

The guest wants to leave, the hotel wants to be paid, and the room has to go back
into stock. Three of these eight scenarios cover the departures board introduced
in 16.2.0.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journeys C and D passed. At least two
in-house stays, one departing on the business date. At least one with a
**non-zero** folio balance, which E-03 needs.

**Test data to prepare:** in Desk, set one in-house stay's departure date to the
property's business date so it becomes due out, and leave a balance on its folio.

---

### E-01 · The departures board is the day's other work list — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/departures` |
| **Prerequisites** | At least one stay departing on the business date |
| **Test data** | Know how many stays depart today, and which have balances |
| **Severity if failed** | **Critical** — the desk has no list of who is leaving, and guests walk out unbilled |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Departures** from the Front desk section of the sidebar. | A board for the business date. |
| 2 | Read the tiles. | Departures, Due out, Checked out, Ready to check out, Blocked, Balance pending, Outstanding. |
| 3 | Read the **Outstanding** tile. | A money figure in the property's currency, not a count. |
| 4 | Read the columns. | Guest, Room, Stay, Folio, Balance, Status, Checkout, Actions. |
| 5 | Count the rows. | Equals the **Departures** tile. Each row is one **stay** — a guest with two rooms is two departures. |
| 6 | Check a row's balance against its folio. | Open the folio from the row; the balance matches. |
| 7 | Look at a guest whose folio has split folios. | A note beneath the balance says how many split folios exist. |

**Pass criteria:** Every stay departing today appears once, the balances match the folios, and the outstanding total is money rather than a count.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-02 · The board says what is blocking each departure — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/departures` and `/pms/checkout/<stay>` |
| **Prerequisites** | E-01 passed. One departing stay with a balance, one with a zero balance. |
| **Test data** | None |
| **Severity if failed** | High — the desk cannot triage the morning rush |

| # | Step | Expected result |
|---|---|---|
| 1 | Find the row with a zero balance. | The **Checkout** column shows a green *Ready to check out* badge. |
| 2 | Find the row with an outstanding balance. | An orange **Blocked** badge, and beneath it a short list of what is blocking — including the outstanding balance and its amount. |
| 3 | Read the blocker text. | It is a plain sentence, in the language you are using, not a code or an identifier. |
| 4 | Open the **checkout screen** for that same blocked stay. | The blockers listed there are **the same blockers**, word for word. The board and the checkout screen must not disagree. |
| 5 | Confirm the **Check out** action is still offered on the blocked row. | It is. The checkout screen is where a manager resolves a blocker, so the link stays and the badge explains the state. |
| 6 | Set the filter to **Ready for checkout**, then **Balance pending**, then **Checked out**, then **Due out**. | Each row count matches its matching tile. |
| 7 | Choose a filter matching nothing. | A clear message, with the tiles and filter still on screen. |

**Pass criteria:** Blockers on the board are identical to those on the checkout screen, and every filter's count matches its tile.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-03 · Checkout with an outstanding balance is blocked, then cleared

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/checkout/<stay>` and `/pms/folios/<folio>` |
| **Prerequisites** | A departing stay with a non-zero balance |
| **Test data** | The balance amount |
| **Severity if failed** | **Critical** — guests leave without paying |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the checkout screen for that stay. | It shows total charges, total payments and the balance. |
| 2 | Read the blockers. | The outstanding balance is listed, with its amount. |
| 3 | Attempt to check out. | **Refused** — either the button is disabled or the server refuses. Nothing changes. |
| 4 | Open the folio and take a payment that clears the balance exactly. | The balance reaches zero. |
| 5 | Return to checkout and refresh. | No blockers. Check out is enabled. |
| 6 | Check out. | Succeeds, with a confirmation naming what happened. |
| 7 | Check the room on the rack. | Occupancy **Vacant**, Housekeeping **Dirty**. |
| 8 | Check the departures board. | The row now reads **Checked out** and no longer offers Check out. |

**Pass criteria:** A balance genuinely blocks departure, clearing it genuinely unblocks it, and the room returns to stock as Vacant Dirty.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-04 · A credit balance: the hotel owes the guest

| | |
|---|---|
| **Role** | Front Office Agent, then Finance Manager |
| **Surface** | `/pms/folios/<folio>` and `/pms/checkout/<stay>` |
| **Prerequisites** | A departing stay whose folio you will deliberately **overpay** |
| **Test data** | Overpay by a small amount |
| **Severity if failed** | Medium — see the note below; this scenario is a policy question as much as a test |

| # | Step | Expected result |
|---|---|---|
| 1 | On a departing guest's folio, take a payment **larger** than the balance. | The balance goes negative — the hotel now owes the guest. |
| 2 | Open the departures board and read that row. | The balance is shown as a credit, visibly distinguished from an amount owed. |
| 3 | Open the checkout screen. | Record exactly what you see. |
| 4 | Attempt to check out. | **Expected today:** refused, because the current rule blocks on any non-zero balance in either direction. |
| 5 | Judge it. | **Answer here:** should a guest the hotel owes money be blocked from leaving, or should the system let them go and flag the refund? ☐ Block is right ☐ Should allow and flag |

**Pass criteria:** The credit is visible and clearly distinguished from a debt. Step 5 is the finding. This is **known current behaviour**, recorded in the plan's limitations — raise it as a **defect only if** this hotel needs the other behaviour, in which case it is High.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-05 · The departures board agrees with the dashboard — NEW in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms` and `/pms/departures` |
| **Prerequisites** | E-01 passed |
| **Test data** | None |
| **Severity if failed** | High — two screens disagreeing destroys trust in both |

| # | Step | Expected result |
|---|---|---|
| 1 | On the dashboard, note **Departures today** and **Pending check-outs**. | Two figures. |
| 2 | On the departures board, note **Departures** and **Due out**. | Two figures. |
| 3 | Compare. | Departures today = Departures. Pending check-outs = Due out. |
| 4 | Check one guest out. | Succeeds. |
| 5 | Refresh both. | Both pending figures fall by one, both checked-out figures rise by one, and the day's total is unchanged on both. |

**Pass criteria:** The two screens agree before and after a checkout.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-06 · A split folio still owing money holds the departure

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/checkout/<stay>` |
| **Prerequisites** | The split folio created in **D-04**, with a balance left on the company side |
| **Test data** | None |
| **Severity if failed** | **Critical** — a company-pay balance walks out of the door with the guest |

| # | Step | Expected result |
|---|---|---|
| 1 | Settle the **guest's** folio to zero, leaving the company folio outstanding. | Guest folio balance is zero. |
| 2 | Open the checkout screen for that stay. | A blocker names the **split folio** and its outstanding amount specifically. |
| 3 | Attempt to check out. | Refused. |
| 4 | Settle the company folio. | Its balance reaches zero. |
| 5 | Return to checkout and refresh. | No blockers; checkout succeeds. |

**Pass criteria:** A balance on any folio attached to the stay blocks departure, not merely the guest's own.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-07 · Reversing a checkout, and who may do it

| | |
|---|---|
| **Role** | Front Office Agent, then Finance Manager (or Hotel Manager) |
| **Surface** | `/pms/checkout/<stay>` |
| **Prerequisites** | A stay checked out in E-03 |
| **Test data** | A reason for the reversal |
| **Severity if failed** | **Critical** — a settled folio and a posted invoice could be reopened by anyone |

| # | Step | Expected result |
|---|---|---|
| 1 | As the **agent**, open the checked-out stay and look for a reverse action. | Either not offered, or offered and refused by the server. An agent completing a reversal is a Critical failure. |
| 2 | Sign in as **Finance Manager** and reverse, leaving the reason blank. | Refused — the reason is mandatory. |
| 3 | Enter a reason and reverse. | Succeeds. |
| 4 | Check **In House**. | The guest is back in house. |
| 5 | Check the room on the rack. | Occupied again. |
| 6 | Check the folio. | Re-opened. |
| 7 | In Desk, look at the ERPNext Sales Invoice raised at checkout. | It is **not** cancelled. Cancelling a submitted invoice is a finance decision with its own approval — the reversal deliberately leaves it alone. Confirm your finance team accepts that. |

**Pass criteria:** Reversal is restricted, requires a reason, restores the operational state, and does not silently cancel a submitted invoice.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### E-08 · The morning rush: five departures, one desk

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms/departures` |
| **Prerequisites** | Five stays departing on the business date, with a mixture of zero balances, outstanding balances and one already checked out |
| **Test data** | Set this up in Desk before starting |
| **Severity if failed** | High — the system works one guest at a time but not at checkout hour |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the departures board and filter to **Ready for checkout**. | Only the ones that can go now. |
| 2 | Check them out one after another, returning to the board each time. | Each succeeds; the board reflects each one. |
| 3 | Switch to **Balance pending**. | Only the ones needing money. |
| 4 | Work one of those: open the folio from the row, take payment, return, check out. | The round trip works without hunting for the guest again. |
| 5 | Time the whole set. | Record here: `______`. Judge whether this is workable at 11am with a queue. |
| 6 | Confirm the board never showed a stale figure. | After each checkout the tiles moved. |

**Pass criteria:** The board supports working a queue rather than one guest in isolation, and stays accurate throughout. A pass that took an unreasonable amount of time is still a **High** usability finding — say so in Comments.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey E sign-off

Guests have left, rooms are back in stock and money has been taken. Journey F
closes the day.

| | |
|---|---|
| **Scenarios passed** | ____ of 8 |
| **Critical/High defects open** | ____ |
| **Accepted by** | ____________________ (Front Office Manager) |
| **Date** | ____________ |
