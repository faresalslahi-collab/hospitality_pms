# Journey I — Reporting to management

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** General Manager
**Surface:** Desk → Reports, plus `/pms` and the Desk dashboard.

Twenty-one reports, eight dashboard cards and two dashboards. This journey asks
two questions of each: **is it right**, and **would this hotel actually use it**.
The second question matters as much as the first — a correct report nobody opens
is dead weight, and a missing report is a gap worth knowing about before go-live.

Run this journey **after** Journeys C–G, so there is a real day of trading behind
the numbers.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journeys C, D, E, F and G passed, so at
least one business day has been traded and closed.

**For every report below, answer both columns.** "Correct" is a test. "Would
use" is a business judgement, and a No there is a finding worth recording even
when the report is perfectly accurate.

---

### I-01 · Occupancy and Revenue is the number management will quote

| | |
|---|---|
| **Role** | General Manager or Hotel Manager |
| **Surface** | Desk → Reports → Occupancy and Revenue |
| **Prerequisites** | Journey F completed — one closed audit |
| **Test data** | Occupancy, ADR, RevPAR and room revenue from the closed audit record |
| **Severity if failed** | **Critical** — the hotel's headline figures are wrong |

| # | Step | Expected result |
|---|---|---|
| 1 | Run the report for the closed business date. | It returns rows. |
| 2 | Compare occupancy percentage to the audit. | Identical. |
| 3 | Compare ADR. | Identical. |
| 4 | Compare RevPAR. | Identical. |
| 5 | Compare room revenue. | Identical. |
| 6 | Open `/pms` and read the dashboard's Performance section. | The same four figures, stamped with the same business date. |
| 7 | Confirm the definitions match how this hotel counts. | ADR is revenue per **occupied** room; RevPAR is revenue per **available** room. Confirm that is your hotel's definition — if not, that is a High finding even though the arithmetic is internally consistent. |

**Pass criteria:** The audit, the report and the dashboard agree to the currency's precision, and the definitions are the ones this hotel uses.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-02 · The four front office reports

| | |
|---|---|
| **Role** | Front Office Manager or Hotel Manager |
| **Surface** | Desk → Reports |
| **Prerequisites** | Journeys C and E run |
| **Test data** | What you know actually happened today |
| **Severity if failed** | High — the shift handover and the manager's morning check both rely on these |

| # | Report | Check | Correct? | Would use? |
|---|---|---|---|---|
| 1 | **Arrivals** | Lists the same rooms as `/pms/arrivals` for the same date | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 2 | **Departures** | Lists the same stays as `/pms/departures` for the same date | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 3 | **In House** | Matches `/pms/in-house` row for row | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 4 | **Room Status** | Every room appears with all four status dimensions, matching the room rack | ☐ Yes ☐ No | ☐ Yes ☐ No |

| # | Step | Expected result |
|---|---|---|
| 1 | Run each of the four for today's business date. | Each returns rows. |
| 2 | Compare each to its `/pms` equivalent. | Same rooms, same stays, same statuses. Any disagreement between a report and a board is a defect — name both in Comments. |
| 3 | Check that Room Status shows the dimensions **separately**. | Four columns, not one merged status. |

**Pass criteria:** All four agree with the operational screens. Any "Would use? No" is recorded as a Low finding unless the manager explains it is essential, in which case Medium.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-03 · The four revenue and inventory reports

| | |
|---|---|
| **Role** | Revenue Manager or General Manager |
| **Surface** | Desk → Reports |
| **Prerequisites** | Journeys B, F and G run |
| **Test data** | The room revenue from the closed audit |
| **Severity if failed** | High — revenue management has no view |

| # | Report | Check | Correct? | Would use? |
|---|---|---|---|---|
| 1 | **Revenue by Room Type** | Totals to the same room revenue as the closed audit | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 2 | **Revenue by Source** | Splits by booking source; direct and channel bookings from Journey H appear under the right source | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 3 | **Availability Forecast** | Forward availability per room type agrees with `/pms/availability` for the same dates | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 4 | **Cancellations and No Shows** | The cancellation from B-11 and the no-show from F-02 both appear, with their charges | ☐ Yes ☐ No | ☐ Yes ☐ No |

| # | Step | Expected result |
|---|---|---|
| 1 | Run each report over the period you have tested. | Each returns rows. |
| 2 | Cross-check the two revenue reports against each other and against the audit. | They reconcile. |
| 3 | Cross-check Availability Forecast against a live availability search. | Same figures for the same dates. |
| 4 | Confirm the no-show and the cancellation are attributed to the right dates. | They are. |

**Pass criteria:** Revenue reconciles across all views, and forward availability agrees with the live search.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-04 · The four operations reports

| | |
|---|---|
| **Role** | Housekeeping Manager, Maintenance Manager, Front Office Manager |
| **Surface** | Desk → Reports |
| **Prerequisites** | Journey D run |
| **Test data** | What you actually did in Journey D |
| **Severity if failed** | Medium — operations can be run from the boards; these are for managing the department |

| # | Report | Check | Correct? | Would use? |
|---|---|---|---|---|
| 1 | **Housekeeping Productivity** | The cleans from D-06 to D-08 appear with their attendant and minutes | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 2 | **Maintenance Response Times** | The ticket from D-11 appears with the time from raise to completion | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 3 | **Guest Request SLA** | The requests from D-16 to D-18 appear; the breached one is marked breached and the on-time ones are not | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 4 | **Rooms Out of Service** | The room taken out in D-12 appears while out, and leaves the report after D-14 releases it | ☐ Yes ☐ No | ☐ Yes ☐ No |

| # | Step | Expected result |
|---|---|---|
| 1 | Run each report for the period. | Each returns rows. |
| 2 | Check the SLA report's breach flags against what you observed in D-17 and D-18. | They agree — the completed-in-time request is **not** flagged. |
| 3 | Check Rooms Out of Service reflects the current state, not a historical one. | A released room is gone from it. |

**Pass criteria:** Each report reflects the work actually done in Journey D.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-05 · The six finance reports

| | |
|---|---|
| **Role** | Finance Manager |
| **Surface** | Desk → Reports |
| **Prerequisites** | Journeys D, E, G and H run |
| **Test data** | The folios, payments and corporate account from those journeys |
| **Severity if failed** | **Critical** for the reconciliation reports; High for the rest |

| # | Report | Check | Correct? | Would use? |
|---|---|---|---|---|
| 1 | **Guest Ledger** | Every folio for the period with its balance; agrees with the folios themselves | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 2 | **Folio vs Invoice** | Zero difference on every settled folio (G-02) | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 3 | **Payment Reconciliation** | Every payment with its Payment Entry (G-07) | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 4 | **Failed Postings** | The G-03 failure appeared, and cleared after the retry | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 5 | **Corporate Credit Exposure** | Agrees with the account record (H-04) | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 6 | **Corporate Production** | Room nights and revenue for the account (H-04) | ☐ Yes ☐ No | ☐ Yes ☐ No |

| # | Step | Expected result |
|---|---|---|
| 1 | Run all six. | Each returns rows. |
| 2 | Confirm **Folio vs Invoice** shows no unexplained difference. | Any non-zero difference is a **Critical** finance defect. |
| 3 | Confirm **Failed Postings** is empty or contains only failures you know about. | An unexplained failure is revenue that has not reached the ledger. |
| 4 | Total Guest Ledger's outstanding balances and compare to the dashboard's Outstanding balance figure. | They agree. |

**Pass criteria:** The reconciliation reports show nothing unexplained, and the ledger total agrees with the operational dashboard.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-06 · The remaining three reports

| | |
|---|---|
| **Role** | Hotel Manager |
| **Surface** | Desk → Reports |
| **Prerequisites** | Journeys D and H run |
| **Test data** | The kitchen activity from D-20 to D-23, the export from H-08 |
| **Severity if failed** | Medium |

| # | Report | Check | Correct? | Would use? |
|---|---|---|---|---|
| 1 | **Kitchen Consumption and Wastage** | The requisition and wastage from D-20 and D-23 appear with quantities and values | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 2 | **Regulatory Submissions** | The export from H-08 appears with its status | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 3 | **Availability Forecast** *(if not already checked in I-03)* | Forward view is usable for a revenue meeting | ☐ Yes ☐ No | ☐ Yes ☐ No |

| # | Step | Expected result |
|---|---|---|
| 1 | Run each. | Each returns rows or a clear empty state. |
| 2 | Confirm every one of the 21 reports has now been opened at least once across I-01 to I-06. | Tick off against the list in [12_UAT_Coverage_Matrix_and_Gaps.md](12_UAT_Coverage_Matrix_and_Gaps.md) §2. |

**Pass criteria:** All 21 reports have been run and none errors.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-07 · The Desk dashboard cards read live data

| | |
|---|---|
| **Role** | Hotel Manager |
| **Surface** | Desk → Hospitality PMS → Dashboard |
| **Prerequisites** | Journeys C to F run |
| **Test data** | Today's real figures |
| **Severity if failed** | Medium — the same figures exist elsewhere |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the **Hospitality PMS** dashboard in Desk. | Eight number cards render: Arrivals Today, In House, Rooms Out of Order, Housekeeping Tasks Pending, Open Maintenance Tickets, Failed Postings, Integration Failures Pending, Overdue Guest Requests. |
| 2 | Compare **Arrivals Today** and **In House** to the `/pms` dashboard. | They agree, allowing for the different unit — the Desk card counts reservations, the `/pms` tile counts rooms. Note any difference and confirm it is explained by that, not by an error. |
| 3 | Compare **Rooms Out of Order** to the room rack. | Agrees. |
| 4 | Compare the remaining five to their boards. | Each agrees. |
| 5 | Confirm no card is blank or errored. | All eight render a number. |

**Pass criteria:** All eight cards render live figures that agree with the operational screens.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### I-08 · What management still cannot see

| | |
|---|---|
| **Role** | General Manager, with Hotel Manager and Finance Manager |
| **Surface** | Discussion, with the reports open |
| **Prerequisites** | I-01 to I-07 complete |
| **Test data** | This hotel's existing management pack, if it has one |
| **Severity if failed** | Recorded as a gap, not a defect |

This scenario has no steps to pass or fail in the usual sense. It is the one
place in the package where the hotel is asked what is **missing**.

| # | Question | Answer |
|---|---|---|
| 1 | Which report in your current management pack has **no equivalent** here? | |
| 2 | Which figure does the owner or board ask for monthly that you could not produce from this system today? | |
| 3 | Is there a forecast or pace report you need that does not exist? | |
| 4 | Does any report exist here that you would **never** open? | |
| 5 | Is anything reported in a unit that does not match how you count — rooms vs bookings, gross vs net, inclusive vs exclusive of tax? | |

**Pass criteria:** The questions are answered by the people who will live with the
system. Each "missing" item is logged as a gap with an agreed severity, not left
in a meeting note.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Complete ☐ Incomplete | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey I sign-off

| | |
|---|---|
| **Reports run** | ____ of 21 |
| **Reports management would use** | ____ of 21 |
| **Scenarios passed** | ____ of 8 |
| **Critical/High defects open** | ____ |
| **Gaps recorded from I-08** | ____ |
| **Accepted by** | ____________________ (General Manager) |
| **Date** | ____________ |
