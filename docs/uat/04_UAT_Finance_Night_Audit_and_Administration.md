# UAT — Finance, Night Audit and Administration

Audience: finance manager, accounts user, night auditor, hotel/general manager,
read-only auditor.

This set proves that money moves the way the approved documents say it does:
one posting per event, no silent edits, credit that only moves under a lock,
and a business date that only the Night Audit is allowed to touch. Every step,
refusal and figure below is read from the code that enforces it —
`services/night_audit.py`, `services/posting.py`, `services/folio.py`,
`services/payments.py`, `services/corporate.py`, `api/checkout.py`,
`api/night_audit.py`, `api/corporate.py` — not from what the specification
originally intended. Where the implementation has moved on from an older
guide (for example, the folio, checkout and Night Audit screens described as
"not built yet" in the Night Audit, Finance and Reconciliation Guide now
exist at `/pms/folios/:id`, `/pms/checkout/:stay` and `/pms/night-audit`),
this set follows the code, and says so.

Run the scenarios within each group in order — FIN-08 through FIN-10 in
particular build on the account state the previous scenario left behind.
Sign in as the named role for each scenario; do not run a scenario as
Administrator or System Manager unless that is the named role, because both
bypass every role check in `services.base.require_role()`.

## Baseline test data

Set this up once, before FIN-01, on the property you are testing against
(call it **the property** below):

- An active **Hospitality Posting Profile** for the property (Administrator
  and Setup Guide section 9), with **Room Charge** and **Room Service** both
  mapped to a valid Item, Income Account and Cost Centre in its Charge Item
  Mapping table, and a Default Receivable Account set.
- One test user per role used below, each holding exactly that Hospitality
  PMS role (plus a User Permission scoping them to the property, if the site
  has more than one): **Front Office Agent**, **Front Office Manager**,
  **Finance Manager**, **Accounts User**, **Night Auditor**, **Hotel
  Manager**, **Read-Only Auditor**, **Room Attendant**.
- A guest with a **Confirmed** reservation checked in for today's business
  date (Front Office Guide sections 3–6), giving you one **In House** stay
  with an open master folio. Keep its stay name and folio name to hand —
  later scenarios refer to it as **the test folio** / **the test stay**.

Where a scenario needs more than this (a broken posting profile, a second
guest, a corporate account), its own Precondition line says so.

---

## ERPNext posting

### FIN-01  Checkout posts a Sales Invoice and a Payment Entry

**Role:** Front Office Agent
**Precondition:** On the test folio, post one Room Charge (Folio page → Post
charge, e.g. 450.00) and take one payment for the same amount (Folio page →
Take payment, e.g. Cash, 450.00), so the folio's balance is 0.00 and neither
line has reached ERPNext yet.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open `/pms/checkout/:stay` for the test stay. | "No blockers. This stay is ready to check out." is shown; "Post to ERPNext on checkout" is ticked. |
| 2 | Note Total charges, Total payments and Balance in the details panel. | Balance reads 0.00; Total charges and Total payments match what you posted. |
| 3 | Click **Check out**. | A success panel appears: "Checked out", "The folio was settled and closed.", "The room was released to Vacant Dirty." |
| 4 | In Desk, open the Sales Invoice list for the guest's Customer. | Exactly one submitted (docstatus 1) Sales Invoice exists, posting date is the property's business date, Grand Total equals the charge you posted, Remarks read "Hospitality folio {folio}". |
| 5 | In Desk, open the Payment Entry list for the same Customer. | Exactly one submitted Payment Entry exists, Paid/Received Amount equals the payment you took, Remarks read "Hospitality folio {folio} payment {row}". |
| 6 | Open **Hospitality Financial Posting Log**, filtered to this folio. | Two rows: posting type Sales Invoice and Payment Entry, both Posting Status **Posted**, each carrying the ERP Document name found in steps 4–5. |

**Pass criteria:** Checkout completes and exactly one submitted Sales Invoice and one submitted Payment Entry exist in ERPNext, both recorded as Posted on the folio's posting log.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-02  Folio charges are stamped posted, and Folio vs Invoice reconciles

**Role:** Accounts User
**Precondition:** The folio checked out in FIN-01 (Settled and Closed, every charge posted).

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the folio in Desk (**Hospitality Guest Folio**) and expand the Charges table. | Every charge row shows "Posted to ERP" ticked and "Sales Invoice" populated with the invoice from FIN-01. |
| 2 | Run **Report → Folio vs Invoice** (module Hospitality Folio), Property = the property, run. | The folio's row appears. |
| 3 | Read the row. | Folio Charges = ERPNext Invoiced, Charge Variance = 0.00; Folio Payments = ERPNext Paid, Payment Variance = 0.00; Unposted Charge Count = 0; Reconciled = **Yes**. |

**Pass criteria:** Every charge shows Posted to ERP with its Sales Invoice populated, and Folio vs Invoice reports this folio as Reconciled = Yes with both variances at 0.00.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-03  A broken posting profile mapping fails, is retried, and posts once

**Role:** Finance Manager
**Precondition:** A folio with a fresh Room Charge posted on it that has not yet reached ERPNext (Folio page → Post charge, Charge type Room Charge). Call it **the test folio** for this scenario.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | In Desk, open the property's **Hospitality Posting Profile**. Clear Default Item, and in Charge Item Mapping untick Active on the Room Charge row (or delete it). Save. | The profile saves with no working mapping and no fallback item for Room Charge. |
| 2 | Call `POST /api/method/hospitality_pms.api.checkout.post_folio` with `folio` = the test folio (a REST client, or bench console: `from hospitality_pms.api import checkout; checkout.post_folio(folio="<folio>")`). | The call fails with "Charge type Room Charge is not mapped to an item, and the posting profile has no default." No Sales Invoice is created. |
| 3 | Run **Report → Failed Postings** (module Hospitality Folio), Property = the property. | One row for this folio: Posting Type "Sales Invoice", Attempts = 1, Error Message containing the text from step 2. |
| 4 | Reopen the Posting Profile. Re-tick Active on the Room Charge mapping (or set a valid Default Item). Save. | The profile now maps Room Charge correctly. |
| 5 | Call `POST /api/method/hospitality_pms.api.checkout.retry_posting` with `log` = the Failed posting log's name from step 3. | The call succeeds, returns `retried: true` and an `erp_document` naming a new Sales Invoice; the posting log's status is now **Posted**. |
| 6 | In Desk, open the Sales Invoice list for this folio's Customer. | Exactly one submitted Sales Invoice exists for the folio. |
| 7 | Call `retry_posting` again with the same log name. | The call succeeds and returns `retried: false` — the row was already Posted, so nothing is re-sent; the Sales Invoice count for the folio is still exactly one. |

**Pass criteria:** After the mapping is fixed and the posting is retried, exactly one Sales Invoice exists for the folio, the posting log shows Posted, and a second retry creates no further document.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Folio integrity

### FIN-04  A posted charge cannot be edited or deleted

**Role:** Finance Manager
**Precondition:** Post a fresh charge on any open folio (Folio page → Post charge, Charge type Room Service, amount 50.00, description "UAT FIN-04 test charge"). Note its amount.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | In Desk, open the folio (**Hospitality Guest Folio**) and find the FIN-04 charge row in the Charges table. | The row shows amount 50.00. |
| 2 | Change the row's Amount to a different value and Save the folio. | The save is refused with "Charge {row} is posted and cannot be edited; correct it with a reversal instead." |
| 3 | Reload the folio without saving your change. | The charge's amount is still 50.00. |
| 4 | Remove the same row entirely (delete it from the child table) and Save. | The save is refused with "Charge {row} is posted and cannot be deleted; correct it with a reversal instead." |

**Pass criteria:** Both the edit and the delete attempt are refused with the exact reversal-instead message, and the charge's amount is unchanged after reload.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-05  Reversing a charge with a reason

**Role:** Finance Manager
**Precondition:** Post a fresh charge on any open folio (Folio page → Post charge, Charge type Room Service, amount 75.00, description "UAT FIN-05 test charge"). Note the folio's Balance before reversal.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the folio at `/pms/folios/:id`. Click **Reverse** on the FIN-05 charge. | The "Reverse this charge" dialog opens with "A correction is a reversal, not an edit. This posts a compensating line for the same amount; the original charge stays on the folio and is marked reversed." |
| 2 | Leave Reason blank. | "Reverse charge" stays disabled. |
| 3 | Enter a reason, e.g. "Goodwill reversal — service complaint." Click **Reverse charge**. | The dialog closes with a success toast ("Folio updated."). |
| 4 | Reload the folio. | The original charge is struck through with a "Reversed" badge; directly beneath it, a line reads "Reversal of UAT FIN-05 test charge" for **−75.00**; the folio Balance is exactly 75.00 lower than before step 1. |
| 5 | Look for a Reverse button on either the original or the reversal line. | Neither offers one — Folio.vue hides Reverse once a charge is reversed or is itself a reversal. |

**Pass criteria:** The original charge remains, marked reversed, a compensating line for its exact negative amount appears referencing it, the folio balance reflects the net-zero effect, and no further reversal is offered on that charge.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-06  A front desk agent cannot reverse a charge; a finance manager can

**Role:** Front Office Agent (steps 1–3), then Finance Manager (step 4)
**Precondition:** Post a fresh charge on the test folio (Folio page → Post charge, Charge type Room Service, amount 60.00, description "UAT FIN-06 test charge").

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Signed in as Front Office Agent, open the folio and click **Reverse** on the FIN-06 charge. | The dialog opens — the button is not hidden by role; the server decides. |
| 2 | Enter a reason and click **Reverse charge**. | Refused with "This action requires one of the following roles: Finance Manager, Accounts User, Hospitality Administrator, System Manager." The dialog stays open showing this error. |
| 3 | Reload the folio. | The FIN-06 charge is unchanged — not reversed. |
| 4 | Sign in as Finance Manager, open the same folio, click Reverse on the same charge, enter a reason, confirm. | Succeeds: the charge is marked reversed and a compensating line appears, exactly as in FIN-05. |

**Pass criteria:** The Front Office Agent's attempt is refused with the exact role-requirement message and leaves the charge untouched; the same action by a Finance Manager succeeds.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-07  Splitting company-pay charges onto a company folio

**Role:** Front Office Manager
**Precondition:** The test folio has at least two Room Charge lines and one other charge (e.g. a Room Service line) still on it, none reversed. Note the folio's Total charges.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the folio. Note which charge rows exist and their amounts. | — |
| 2 | Click **Split folio**. | "Split charges onto a new folio" opens, listing every non-reversed, non-reversal charge with its amount; "Payer on the new folio" defaults to Company. |
| 3 | Select only the Room Charge rows. Click **Split selected charges**. | The dialog closes and a "Moved the selected charges to folio {new folio}" message appears. |
| 4 | Reload the original folio. | The selected Room Charge rows are gone from it; its Total charges is lower by exactly their sum; the Room Service line is still present. |
| 5 | Open the new folio (the link in the success message, or **Hospitality Guest Folio** filtered on Parent Folio = the original). | Folio Type = **Company**; it holds exactly the moved rows, each with Payer = Company; its Total charges equals what was removed in step 4. |
| 6 | Add the two folios' Total charges together. | The sum equals the original folio's Total charges from step 1 — nothing duplicated, nothing lost. |

**Pass criteria:** The selected charges exist only on the new Company folio, the source folio's total drops by exactly the moved amount, and the two totals sum to the original.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Corporate credit

`services/corporate.consume_credit()` and `release_credit()` are not yet
called from the reservation confirm/cancel flow, and are not exposed by
`api/corporate.py` (its own module comment says they run inside booking —
they do not, as at this build). The three scenarios below exercise the
service function directly, exactly as the Night Audit, Finance and
Reconciliation Guide section 6 already documents doing. Treat this gap as a
finding, not a scenario design choice: booking against a corporate account
today does not check or consume its credit at all.

**Precondition for FIN-08–FIN-10:** In Desk, create a **Hospitality
Corporate Account** for the property: Account Code and Account Name set,
Is Active ticked, Credit Limit **1000.00**, Credit Status **Active**,
Contract Start on or before today, Contract End blank or after today. Have a
way to run Python against the site as a specific user — bench console
(`bench --site <site> console`) with `frappe.set_user("<test-user>")`, or a
Desk **System Console** script — for each step below.

### FIN-08  Booking against a corporate account within its limit

**Role:** Finance Manager (as the console session's effective user)

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Run `frappe.set_user("<finance-manager-test-user>")`. | The session now acts as that user. |
| 2 | Run `from hospitality_pms.services import corporate; corporate.consume_credit("<account>", 400)`. | Returns `{"account": "<account>", "credit_used": 400.0, "exception_approved": False}`; no error. |
| 3 | Reload the Hospitality Corporate Account in Desk. | Credit Used = 400.00; Credit Available = 600.00; Credit Status unchanged (Active). |
| 4 | Open **Hospitality Corporate Credit Log**, filtered to this account. | A new row: Action "Credit consumed", Credit Before 0.00, Credit After 400.00, Approved By blank. |

**Pass criteria:** An amount within the limit is consumed without error, the account's Credit Used/Available update correctly, and the credit log records it with no approver.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-09  Exceeding the limit: refusal and Exception Required

**Role:** Finance Manager (as the console session's effective user)
**Precondition:** Following FIN-08 — Credit Used 400.00 of a 1000.00 limit, 600.00 available.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Run `corporate.consume_credit("<account>", 700)` (700 exceeds the 600.00 available). | Raises "This booking exceeds the credit limit for {account}. Finance approval is required." |
| 2 | Reload the account. | Credit Status is now **Exception Required**; Credit Used is still 400.00 — the refused attempt consumed nothing. |
| 3 | Open the Credit Log for this account. | A new row: Action "Credit exceeded", Amount 700.00, Before 400.00, After 1100.00, Reason "Requested amount exceeds the credit limit." |

**Pass criteria:** The over-limit attempt is refused with the exact message, the account flips to Exception Required, Credit Used is unchanged, and the attempt is logged as Credit exceeded.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-10  Approving the exception as finance

**Role:** Finance Manager (as the console session's effective user)
**Precondition:** Following FIN-09 — account is Exception Required, Credit Used 400.00 of a 1000.00 limit.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Confirm `frappe.set_user` is set to the Finance Manager test user. | — |
| 2 | Run `corporate.consume_credit("<account>", 700, allow_exception=True)`. | Succeeds: `{"account": "<account>", "credit_used": 1100.0, "exception_approved": True}`. |
| 3 | Reload the account. | Credit Used = 1100.00; Credit Available = −100.00 (over limit, by design once approved). |
| 4 | Open the Credit Log. | A new row: Action "Credit consumed (exception approved)", Before 400.00, After 1100.00, Approved By = the Finance Manager's user id. |
| 5 | Run `frappe.set_user` to a Corporate Sales Manager or Front Office Manager test user, then repeat `consume_credit("<account>", 50, allow_exception=True)` on a fresh over-limit amount. | Refused with "This action requires one of the following roles: Finance Manager, Hospitality Administrator, System Manager." |

**Pass criteria:** A Finance Manager's exception approval succeeds and is logged with their user id as approver; the same call from a user without one of the approval roles is refused with the exact message.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:** General Manager can restore a suspended/exception account to Active via `set_credit_status` (Workflow Matrix section 8's "Escalate → GM Review"), but cannot itself approve consuming credit past the limit through `consume_credit` — that is Finance Manager, Hospitality Administrator or System Manager only.

---

## Night audit

Run FIN-11 through FIN-15 in order, on the same business date, as the full
nightly procedure a night auditor would actually follow.

### FIN-11  Start and review; read the exception list

**Role:** Night Auditor
**Precondition:** At the property, one Confirmed or Guaranteed reservation with an arrival date on or before today, not checked in (produces an Unresolved Arrival); and one In House or Due Out stay with a departure date on or before today, still in house (produces an Unsettled Departure). Create both by leaving one reservation un-actioned and one departing guest's checkout undone.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open `/pms/night-audit`. | If no audit is open: "No audit has been started for this property yet." with a **Start audit** button. |
| 2 | Click **Start audit**. | An audit opens for the property's current business date; status badge reads **Open**. |
| 3 | Click **Run** on the Review step. | Status becomes **Reviewing**; the Figures section fills in (arrivals/departures expected and completed, in-house rooms, and more). |
| 4 | Read the Exceptions list. | The unresolved arrival appears: severity **Blocking**, "{guest} was due to arrive on {date} and has not checked in." The overdue departure appears: severity **Warning**, "{guest} in room {room} was due to depart on {date} and is still in house." |
| 5 | Count the exceptions. | The count matches exactly what the precondition created (2, unless other exceptions already existed). |

**Pass criteria:** Review moves the audit to Reviewing and lists exactly the exceptions the precondition created, with the correct type, severity and wording.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-12  Posting room charges twice charges nothing twice

**Role:** Night Auditor
**Precondition:** Continuing FIN-11. At least one In House stay not departing today exists, so it owes a room charge for the business date. Note its Room Rate.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Click **Run** on "Post room charges". | Status becomes **Posting**; "Rooms charged" and "Charges posted" equal the number of in-house stays owing a night; "Room revenue" equals the sum of their room rates; "Postings failed" is 0. |
| 2 | Note the exact "Charges posted" figure and "Room revenue". | — |
| 3 | Click **Run** on "Post room charges" again, same business date. | The step re-runs without error; "Charges posted" does not increase — every stay's charge for this date already exists under key `room-charge:{stay}:{business_date}` and is reported back as already posted. |
| 4 | Open the folio of the stay noted in the precondition. | Exactly one Room Charge line for today's business date — not two. |

**Pass criteria:** Re-running Post room charges for the same business date adds no second Room Charge line to any folio, and the Charges Posted count does not increase on the second run.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-13  Close is disabled while a blocking exception is open

**Role:** Night Auditor
**Precondition:** Continuing FIN-12. The Unresolved Arrival from FIN-11 (or any Blocking exception) is still unresolved.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Look at the Close step on the Night Audit screen. | Red text beneath it reads "{count} blocking exception(s) must be resolved before the business date can close."; the **Run** button next to Close is disabled. |
| 2 | Call `POST /api/method/hospitality_pms.api.night_audit.close` directly with `audit` = this audit's name (REST client, bypassing the disabled button). | Refused with "{count} blocking exception(s) must be resolved before the business date can close." — same count as step 1; the audit's status is unchanged. |

**Pass criteria:** Close is disabled in the UI while a blocking exception is open, and calling the endpoint directly is refused with the exact message; the business date does not move.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-14  Resolving the exception, reconciling and closing advances the business date by one day

**Role:** Night Auditor
**Precondition:** Continuing FIN-13. Note the property's current business date as **D**.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Check the guest in for the reservation behind the Unresolved Arrival (`/pms/check-in/:reservation` or Desk), moving it out of Confirmed/Guaranteed. | A resolution note alone does not clear this exception on the next review — the reservation itself must move. |
| 2 | If a Failed Posting exception is open (e.g. from FIN-03), fix its cause and retry, or resolve the row with a note. | The row is cleared or genuinely fixed. |
| 3 | Click **Run** on Review again. | The Exceptions list rebuilds; no Blocking exception remains. |
| 4 | Click **Run** on Reconcile. | If no new "Unposted Charge" exception is raised, the audit advances straight to **Ready to Close**. |
| 5 | Click **Run** on Close. | The "Close the business date" dialog reads "This closes {D} and moves the property to {D+1}. It cannot be undone without a manager reopening the day." |
| 6 | Click **Close business date**. | Dialog closes; status badge shows **Closed** with "Closed on {timestamp}. Starting a new audit opens the next business date." |
| 7 | In Desk, open the property's **Hospitality Property** record. | Business Date now reads D+1. |

**Pass criteria:** Once every blocking exception is genuinely resolved, Close succeeds, the audit shows Closed, and the property's business date has advanced by exactly one day.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-15  Reopening with a reason as a manager returns the business date

**Role:** Hotel Manager
**Precondition:** Continuing FIN-14 — the audit for date D is Closed and the property's business date is D+1.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open `/pms/night-audit` and click **Reopen** (visible because the audit is Closed). | "Reopen this business date" opens with "This re-opens a business date the hotel has already reported on. Use it only for a genuine correction." |
| 2 | Leave the reason blank. | "Reopen business date" stays disabled. |
| 3 | Enter a reason, e.g. "Late correction: a room charge was missed for room 204." Click **Reopen business date**. | Dialog closes; status returns to **Reviewing** (not Open, not Ready to Close); "Business date being closed" shows D again. |
| 4 | In Desk, open the Hospitality Property record. | Business Date is back to D. |
| 5 | Open the Hospitality Night Audit record for D. | Reopened On, Reopened By and Reopen Reason are populated with your user, the timestamp and the exact reason text. |

**Pass criteria:** Reopen restores the property's business date to D, moves the audit back to Reviewing, and records the reopening user, timestamp and reason.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-16  The business date cannot be edited directly anywhere, including Desk

**Role:** Hospitality Administrator
**Precondition:** None beyond an existing Hospitality Property record. This proves that even the most privileged Desk role cannot bypass the guard outside the Night Audit.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Open the property's **Hospitality Property** record in Desk. Note the Business Date value. | — |
| 2 | Change Business Date to any other date and Save. | Refused with "The business date is advanced by the Night Audit only. It cannot be edited directly."; the field reverts on reload. |
| 3 | Via bench console, run `doc = frappe.get_doc("Hospitality Property", "<property>"); doc.business_date = "<other date>"; doc.save()`, without setting the Night Audit's internal flag. | The same refusal — the guard is in the document's `validate()`, not the Desk form. |

**Pass criteria:** Every attempt to change the property's business date outside the Night Audit close/reopen flow is refused with the exact message, whether from Desk or from a direct document save.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

## Reports and access

### FIN-17  Occupancy and Revenue matches the Night Audit's own figures

**Role:** Revenue Manager
**Precondition:** Business date D was closed in FIN-14/15. Read this comparison **immediately** after closing, before any other stay checks in or out — the Night Audit's occupancy/ADR/RevPAR are recomputed from stays currently in house each time review or reconcile runs, while the report counts posted Room Charge lines for date D; the two are only guaranteed to agree for that snapshot.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | From the Hospitality Night Audit record for D, record: In-house rooms, Room revenue, Occupancy %, ADR, RevPAR. | — |
| 2 | Run **Report → Occupancy and Revenue** (module Hospitality Night Audit), Property = the property, From Date = To Date = D. | One data row for D. |
| 3 | Compare the row's Occupied Rooms, Sellable Rooms and Room Revenue against step 1. | Occupied Rooms equals the audit's In-house rooms figure from step 1; Room Revenue equals the audit's Room revenue. |
| 4 | Compare Occupancy %, ADR and RevPAR against step 1, and verify each by hand: <br>`Occupancy % = (occupied rooms ÷ sellable rooms) × 100` <br>`ADR = room revenue ÷ occupied rooms` (0 if no occupied rooms) <br>`RevPAR = room revenue ÷ sellable rooms` (0 if no sellable rooms) | All three match the audit's own figures for D, and match your own hand calculation from the report's columns. |

**Pass criteria:** The report's Occupancy %, ADR and RevPAR for D equal the Night Audit record's own figures for D, and both match the stated formulas.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-18  Failed Postings, Payment Reconciliation and Corporate Credit Exposure

**Role:** Finance Manager
**Precondition:** The records from FIN-01 (a posted payment), FIN-03 (if not fully retried, a Failed posting; otherwise create a fresh one the same way) and FIN-10 (the corporate account at 1,100.00 of 1,000.00 credit used) already exist.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Run **Report → Failed Postings** (module Hospitality Folio), Property = the property. | Every currently Failed Hospitality Financial Posting Log row for the property, sorted worst first (most attempts, then oldest last attempt), with columns Posting Log, Posting Type, Folio, Amount, Attempts, Last Attempt, Business Date, Error Message. |
| 2 | Run **Report → Payment Reconciliation** (module Hospitality Folio), Property = the property, no date filter. | One row per Hospitality Folio Payment line at the property (not aggregated); the FIN-01 payment shows Posted to ERP = **Yes** with its Payment Entry name. |
| 3 | Run **Report → Corporate Credit Exposure** (module Hospitality Sales), Property = the property. | A row for the FIN-10 account: Credit Limit 1,000.00, Credit Used 1,100.00, Credit Available −100.00, Utilisation % 110.00, Attention = "Over 90% utilisation". |

**Pass criteria:** All three reports run without error, scope strictly to the property, and each shows figures that match what was posted or consumed in the earlier scenarios.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-19  A Read-Only Auditor can read every record and change none

**Role:** Read-Only Auditor
**Precondition:** The folio, Night Audit record, corporate account and posting log created in earlier scenarios still exist.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | In Desk, open the test folio (**Hospitality Guest Folio**). | The record opens; every field, including Charges and Payments, is visible. |
| 2 | Change any field (e.g. Billing Instructions) and try to Save. | Refused by Desk's own permission check — no write permission on this doctype for this role. |
| 3 | Open the Hospitality Night Audit record for D. | Readable in full, including exceptions and figures; edit-and-save is refused the same way. |
| 4 | Open the Hospitality Corporate Account from FIN-08. | Readable, including negotiated rates and credit fields; edit-and-save refused the same way. |
| 5 | Open a Hospitality Financial Posting Log entry. | Readable; edit-and-save refused the same way. |
| 6 | Run Failed Postings, Folio vs Invoice, Payment Reconciliation, Guest Ledger, Occupancy and Revenue, Corporate Credit Exposure and Corporate Production. | Every report runs and returns data for the property — Read-Only Auditor is listed on all seven. |

**Pass criteria:** Read-Only Auditor can open and read every one of these records and reports, and every attempted edit is refused by Desk rather than silently succeeding.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**

---

### FIN-20  A Room Attendant cannot reach guest records or financial screens

**Role:** Room Attendant
**Precondition:** A Room Attendant test user with only that role. This role has `desk_access = 0`, so it works exclusively in `/pms`.

| # | Step | Expected result |
|---|------|-----------------|
| 1 | Sign in and land on `/pms`. | The side navigation shows only Dashboard, Reservations, In House, Room Rack, Availability and Housekeeping — no Guests, Guest Services, Night Audit, Maintenance or Setup entries. |
| 2 | Navigate directly to `/pms/night-audit` by typing the URL. | Redirected to the Forbidden page — this route requires Night Auditor, Finance Manager, Hotel Manager, General Manager, Hospitality Administrator or System Manager. |
| 3 | Navigate directly to `/pms/folios/<the test folio>`. | The page fails to load the folio with "You are not permitted to read Hospitality Guest Folio." — Room Attendant holds no permission at all on this doctype. |
| 4 | Navigate directly to `/pms/guests`. | The guest list fails to load with a permission error — Room Attendant holds no permission on Hospitality Guest. |
| 5 | Try to open Desk at `/app`. | The Desk workspace is not presented to this user (`desk_access = 0` for Room Attendant). |

**Pass criteria:** Room Attendant cannot open the Night Audit screen, cannot load a folio or the guest list (both refused with a permission error), and cannot reach Desk.
**Result:** ☐ Pass  ☐ Fail    **Tester:** ____________  **Date:** ________
**Notes:**
