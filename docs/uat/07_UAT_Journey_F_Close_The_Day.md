# Journey F — Close the day

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Night Auditor
**Surface:** `/pms/night-audit`, with Desk and direct API calls where a step says so.

The night audit is the hinge of the whole system: it charges the rooms, catches
what the day left undone, and moves the business date. Everything downstream —
revenue reporting, occupancy, ADR, RevPAR — is only as good as this.

Run these nine in order. They are one continuous sequence and each depends on
the one before.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journeys C, D and E passed.

**Test data to prepare, deliberately, before you start:**

- **One Confirmed or Guaranteed reservation** with an arrival date on or before the business date that was **never checked in**. This produces an *Unresolved Arrival* exception, which is **Blocking**.
- **One In House or Due Out stay** whose departure date is on or before the business date, **still in house**. This produces an *Unsettled Departure*, which is a **Warning**.
- **At least one in-house stay not departing today**, so it genuinely owes a room charge. Note its room rate.

Record the property's current business date here — call it **D**: `____________`

---

### F-01 · Start the audit and read the exception list

| | |
|---|---|
| **Role** | Night Auditor |
| **Surface** | `/pms/night-audit` |
| **Prerequisites** | The two deliberate exceptions above exist |
| **Test data** | Know how many exceptions you created |
| **Severity if failed** | **Critical** — the day cannot be closed |

| # | Step | Expected result |
|---|---|---|
| 1 | Open **Night Audit**. | If none is open, a message saying no audit has been started, with a **Start audit** button. |
| 2 | Click **Start audit**. | An audit opens for business date **D**; the badge reads **Open**. |
| 3 | Run the **Review** step. | The badge becomes **Reviewing** and the Figures section fills in: arrivals expected and completed, departures expected and completed, in-house rooms and more. |
| 4 | Read the exception list. | The unresolved arrival appears with severity **Blocking**, naming the guest and the date they were due. The overdue departure appears with severity **Warning**, naming the guest, room and date. |
| 5 | Count the exceptions. | Exactly what your preconditions created — no more, no fewer. |
| 6 | Compare the audit's arrival and departure figures to what Journeys C and E actually did. | They agree. |

**Pass criteria:** Review lists exactly the exceptions you created, with the right severity, and the figures match the day you just ran.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-02 · No-shows are marked, and charged according to policy

| | |
|---|---|
| **Role** | Night Auditor |
| **Surface** | `/pms/night-audit` |
| **Prerequisites** | Continuing F-01. The unresolved arrival is still unresolved. |
| **Test data** | The no-show policy on the reservation's rate plan (A-05) |
| **Severity if failed** | High — the hotel neither recovers no-show revenue nor releases the room |

| # | Step | Expected result |
|---|---|---|
| 1 | Run the **Mark no-shows** step. | It completes and reports how many reservations were marked. |
| 2 | Open that reservation. | Status is **No Show**. |
| 3 | Check the no-show charge. | Applied according to the policy attached to the reservation. |
| 4 | Re-run **Review**. | The Unresolved Arrival exception for that reservation is gone — it was genuinely resolved, not merely dismissed. |
| 5 | Check availability for that reservation's dates. | The room it was holding has been released. |

**Pass criteria:** Marking a no-show changes the reservation, applies the policy charge, releases inventory and clears the exception.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-03 · Posting room charges twice charges nothing twice

| | |
|---|---|
| **Role** | Night Auditor |
| **Surface** | `/pms/night-audit` and `/pms/folios/<folio>` |
| **Prerequisites** | Continuing F-02. At least one in-house stay not departing today. |
| **Test data** | That stay's room rate |
| **Severity if failed** | **Critical** — every guest is charged twice for the night, and the ledger is wrong |

| # | Step | Expected result |
|---|---|---|
| 1 | Run **Post room charges**. | The badge becomes **Posting**. Rooms charged and Charges posted equal the number of in-house stays owing a night. Room revenue equals the sum of their rates. Postings failed is 0. |
| 2 | Write down the exact Charges posted and Room revenue figures. | Recorded. |
| 3 | Open the folio of your noted stay. | Exactly **one** Room Charge line for business date D, at the room rate. |
| 4 | Run **Post room charges** again for the same date. | The step re-runs **without error** and Charges posted does **not** increase. |
| 5 | Re-open the folio. | Still exactly **one** Room Charge line for D. Not two. |
| 6 | Check a stay that **departed** on D. | It has **no** room charge for D — a guest leaving on the 9th does not consume the night of the 9th. |

**Pass criteria:** Re-running the step adds no second charge to any folio, the counter does not move, and departing guests are not charged for the night they leave.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-04 · Due-outs are marked for tomorrow's desk

| | |
|---|---|
| **Role** | Night Auditor |
| **Surface** | `/pms/night-audit`, `/pms/in-house` |
| **Prerequisites** | Continuing F-03. At least one in-house stay departing on D+1. |
| **Test data** | None |
| **Severity if failed** | Medium — the morning shift loses its due-out list but can rebuild it |

| # | Step | Expected result |
|---|---|---|
| 1 | Run **Mark due outs**. | Completes, reporting how many stays were marked. |
| 2 | Open **In House**. | Those stays now read **Due Out**. |
| 3 | Check the dashboard's **Due out** tile. | It matches. |

**Pass criteria:** Stays departing on the next business date are marked Due Out and the figure reaches the dashboard.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-05 · Close is refused while a blocking exception is open — including from outside the screen

| | |
|---|---|
| **Role** | Night Auditor |
| **Surface** | `/pms/night-audit`, plus an API client |
| **Prerequisites** | Continuing F-04, with at least one **Blocking** exception still open. If F-02 cleared them all, create another by leaving a second arrival unactioned and re-running Review. |
| **Test data** | The audit's name, from Desk or the screen |
| **Severity if failed** | **Critical** — a day could be closed over the top of unresolved problems, and closing is not easily undone |

| # | Step | Expected result |
|---|---|---|
| 1 | Look at the **Close** step. | Text beneath it says how many blocking exceptions must be resolved first, and the Run button is **disabled**. |
| 2 | Call the close endpoint **directly** with the audit's name, bypassing the disabled button. | **Refused**, with the same count and message. |
| 3 | Check the audit status. | Unchanged. |
| 4 | Check the property's business date in Desk. | Still **D**. It did not move. |

**Pass criteria:** The disabled button is backed by a server refusal. **A close that succeeds through the API while the screen disables it is a Critical failure** — the button would be the only thing protecting the ledger.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-06 · Resolve, reconcile, close — and the date moves by exactly one day

| | |
|---|---|
| **Role** | Night Auditor |
| **Surface** | `/pms/night-audit`, Desk |
| **Prerequisites** | Continuing F-05 |
| **Test data** | The business date **D** you recorded at the top |
| **Severity if failed** | **Critical** — the hotel cannot close a day |

| # | Step | Expected result |
|---|---|---|
| 1 | Genuinely resolve the remaining blocking exception — check the guest in, or mark them no-show. A resolution note alone must not clear it. | The underlying record moves. |
| 2 | Re-run **Review**. | The exception list rebuilds with no Blocking rows left. |
| 3 | Run **Reconcile**. | The audit advances to **Ready to Close**, unless reconciliation raises a new exception — in which case resolve that too. |
| 4 | Run **Close**. | A dialog states that this closes D and moves the property to D+1, and that it cannot be undone without a manager reopening the day. |
| 5 | Confirm. | The badge reads **Closed** with a timestamp. |
| 6 | In Desk, open the property. | Business date now reads **D+1**. |
| 7 | Open `/pms`. | The dashboard subtitle now shows D+1, and the boards show the new day's arrivals and departures. |

**Pass criteria:** Close succeeds only after every blocking exception is genuinely resolved, and the business date advances by exactly one day everywhere.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-07 · Reopening a closed day is a manager's decision, with a reason

| | |
|---|---|
| **Role** | Night Auditor, then Hotel Manager |
| **Surface** | `/pms/night-audit` |
| **Prerequisites** | The audit for D is Closed and the business date is D+1 |
| **Test data** | A reason for reopening |
| **Severity if failed** | **Critical** — a closed financial day could be reopened by anyone, untraceably |

| # | Step | Expected result |
|---|---|---|
| 1 | As the **Night Auditor**, attempt to reopen the closed audit. | Refused, naming the roles required. |
| 2 | Sign in as **Hotel Manager** and reopen with the reason blank. | Refused — the reason is mandatory. |
| 3 | Enter a reason and reopen. | Succeeds. |
| 4 | Check the property's business date. | Back to **D**. |
| 5 | Open the audit record in Desk. | Reopened-on, reopened-by and your reason are all recorded. |
| 6 | Close the day again to leave the site tidy for Journey G. | Closes; date returns to D+1. |

**Pass criteria:** Reopening is manager-only, requires a reason, returns the business date, and is fully attributable.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-08 · The business date cannot be edited directly, anywhere

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk |
| **Prerequisites** | A property with a business date |
| **Test data** | None |
| **Severity if failed** | **Critical** — the entire audit trail could be bypassed by typing a date into a field |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the property in Desk and try to change **Business date** by hand. Save. | **Refused** — the field is only moved by the night audit. |
| 2 | Try the same as **System Manager**. | Also refused. |
| 3 | Try to bypass the form: change it through the Desk API or a bulk edit. | Refused. |
| 4 | Confirm the date is unchanged. | Still D+1. |

**Pass criteria:** No route through Desk lets a human type a new business date. If any route succeeds, that is Critical and must name the route in Comments.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### F-09 · The dashboard's performance figures appear only once a day has closed — NEW in 16.2.0

| | |
|---|---|
| **Role** | Hotel Manager or Front Office Agent |
| **Surface** | `/pms` |
| **Prerequisites** | F-06 completed, so exactly one audit has been closed |
| **Test data** | The occupancy, ADR and RevPAR figures from the closed audit record in Desk |
| **Severity if failed** | High — management reads an invented number and trusts it |

| # | Step | Expected result |
|---|---|---|
| 1 | Cast your mind back to **C-01**, before any audit had closed. | The Performance section showed a sentence, not zeros. |
| 2 | Open `/pms` now. | The **Performance** section now shows Occupancy, ADR, RevPAR and Room revenue. |
| 3 | Read the note beneath them. | It names the business date these figures belong to — **D**, the day just closed — and says today's are not final until tonight's audit closes. |
| 4 | Open the closed Night Audit record in Desk and compare all four figures. | They match exactly. The dashboard is reporting the audit's own numbers, not recalculating them. |
| 5 | Compare the dashboard's **Occupied now** percentage to the audited occupancy. | They are different figures and are labelled differently. The live one is a count of occupied rooms right now; the audited one belongs to date D. Confirm nobody could mistake one for the other. |

**Pass criteria:** Performance figures match the closed audit exactly and are stamped with its date, and the live occupancy figure is clearly distinguished from the audited one.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey F sign-off

The day is closed, the room charges are posted and the business date has moved.

| | |
|---|---|
| **Scenarios passed** | ____ of 9 |
| **Critical/High defects open** | ____ |
| **Business date at start (D)** | ____________ |
| **Business date at end** | ____________ |
| **Accepted by** | ____________________ (Night Auditor) |
| **Date** | ____________ |
