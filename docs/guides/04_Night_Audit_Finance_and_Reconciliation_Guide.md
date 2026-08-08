# Night Audit, Finance and Reconciliation Guide

**Applies to:** Hospitality PMS 16.1.0 (branch `version-16`)

Audience: night auditor, accounts user, finance manager.

This guide describes exactly what the system does with a hotel's money: how a
charge reaches a guest folio, how that folio reaches ERPNext, what the Night
Audit checks before a business date is allowed to close, and what to do when
something does not reconcile. Every rule below is read from the service code
that enforces it — `services/night_audit.py`, `services/folio.py`,
`services/posting.py`, `services/payments.py`, `services/corporate.py`,
`services/checkout.py` and `api/checkout.py` — not from intent.

**Where the work happens.** The folio and the Night Audit now have their own
screens in the operational frontend:

| Page | Route | What it does |
|---|---|---|
| Folio | `/pms/folios/:id` | Charges, payments and balance for one folio, with buttons to post a charge, take a payment, post an adjustment, split, reverse a charge, and move it between statuses (section 2 onward). |
| Checkout | `/pms/checkout/:stay` | The checkout summary and its blockers, with Check Out and Reverse (section 11). |
| Night Audit | `/pms/night-audit` | The current audit's figures and exceptions, and the seven-step close sequence run in order, each step gated by the server's own blocking-exception rule (section 7). |

Corporate credit, payments and reconciliation are still not on any frontend
page. Corporate accounts have an API (`api/corporate.py` — listing accounts,
one account's negotiated rates and credit position, a credit check, and
`set_credit_status` to suspend, restore or flag an account), but nothing in
`/pms` calls it, so working an account, approving a credit exception or
applying a billing split is done in **Desk**. Gateway payment initiation, refunds, status sync and the
reconciliation view have no API caller in `/pms` at all. Everything in this
guide that has no frontend page — opening a corporate credit exception,
retrying a failed posting, issuing a refund, reconciling a folio — is done in
Desk, on the underlying doctypes, or through the whitelisted API endpoints
directly. Each section below says which doctype, endpoint, or `/pms` screen to
use.

---

## 1. What the folio is, and is not

The **Hospitality Guest Folio** is the operational subledger: the itemised,
running account of what a guest (or a company) has been charged and has paid
during a stay. It is what the front desk and the auditor work with.

The folio is **not** the general ledger. ERPNext remains the system of
record for financial reporting (this is a fixed product decision, not a
configuration choice). The folio's numbers are only correct until they are
compared against ERPNext — that comparison is reconciliation, described in
section 12.

What this means day to day:

- A folio can be looked at, added to and corrected all day without touching
  ERPNext. Nothing is final until it is posted (section 11).
- A closed folio is a promise that everything on it has reached ERPNext. The
  folio state machine enforces this directly: it refuses to let a folio move
  to **Closed** while any charge has not been posted (section 2).
- If the folio and ERPNext ever disagree, ERPNext is not "corrected" to match
  the folio, and the folio is not silently corrected to match ERPNext. The
  disagreement is a variance that a person resolves (section 12).

---

## 2. The folio lifecycle

A folio has seven states (`services/folio.py`, `TRANSITIONS`):

| State | Meaning |
|---|---|
| **Open** | The folio is live. Charges and payments post freely. |
| **Under Review** | Front desk or finance is checking the folio, typically at checkout. |
| **Disputed** | The guest or the hotel disputes something on it. Checkout is blocked while a folio is in this state. |
| **Ready for Settlement** | Reviewed and ready to be paid off. |
| **Partially Settled** | Some but not all of the balance has been paid. |
| **Settled** | The balance is zero. The folio may still be reopened. |
| **Closed** | Final. Every charge has reached ERPNext. |

Allowed moves:

```
Open            -> Under Review, Disputed, Ready for Settlement, Closed
Under Review    -> Disputed, Ready for Settlement, Open
Disputed        -> Under Review, Ready for Settlement
Ready           -> Partially Settled, Settled, Disputed, Under Review
Partially Settled -> Settled, Disputed, Ready for Settlement
Settled         -> Closed, Under Review
Closed          -> Under Review
```

Any move not on this list is refused outright (`assert_transition`).

What must be true to cross a particular line:

- **Into Settled or Closed**: the folio's balance must be zero, to the
  penny (`abs(balance) > 0.005` refuses the move). A folio cannot be marked
  settled while it still owes, or is owed, money.
- **Into Closed specifically**: every charge on the folio must already be
  posted to ERPNext (`is_posted_to_erp` on each charge line). A folio with
  even one unposted charge is refused with the exact count of charges still
  outstanding. This is the rule that stops revenue leaving the building
  unrecorded — post the folio first (section 11), then close it.
- **From Closed back to Under Review** (reopening a closed folio): restricted
  to Finance Manager, Hotel Manager, General Manager, Hospitality
  Administrator or System Manager, and a reason is mandatory. Reopening a
  closed folio reopens something ERPNext has already been told about, so it
  is treated as a controlled exception, not a routine correction.

Postable states — where a **new** charge may still land — are Open, Under
Review, Disputed, Ready for Settlement and Partially Settled. **Settled and
Closed refuse new charges outright.** This is what stops a late minibar
charge landing on a folio after the guest has paid and left: post it to a new
folio, or reopen the closed one under finance authority first.

Every folio operation writes a **Hospitality Folio Log** row — action, actor,
timestamp, before/after status, amount and reason where one applies. This is
the audit trail an auditor reads to answer "who did what to this folio,
when."

---

## 3. Corrections

**A posted charge is never edited or deleted.** There is no operation
anywhere in the service layer that mutates a charge's amount or removes a
row once posted. This is deliberate: an auditor and, eventually, an external
auditor must be able to see what was originally charged, that it was later
reversed, by whom, and why. Silent edits are exactly what makes a subledger
unreconcilable against a ledger that has already been told the original
number.

**How a reversal works** (`folio.reverse_charge`):

1. The original charge line is marked `is_reversed`, stamped with who
   reversed it and when, and carries the reversal reason. It stays on the
   folio exactly as it was posted.
2. A new charge line is appended: type **Adjustment**, description "Reversal
   of `<original description>`", for the exact negative of the original
   amount, tax and total. It references the original row (`reversal_of`).
3. The folio's totals are recalculated from the full set of lines, so the
   reversed original and its compensating line net to zero without any
   special-casing elsewhere.
4. A folio log entry records the reversal, its amount and its reason.

A charge already reversed cannot be reversed again — the service refuses a
second reversal of the same row.

**Who may reverse**: Finance Manager, Accounts User, Hospitality
Administrator or System Manager (`FINANCE_ROLES`). Front desk roles cannot
reverse a charge.

**A reason is always required.** `reverse_charge` refuses with no reason, or
one that is empty after trimming whitespace. The same is true of every other
correction described in this guide: adjustments, reopening a folio, reopening
a business date, refunds, and checking a guest out with an open balance.
There is no code path that performs any of these without a non-blank reason
on file.

---

## 4. Adjustments, discounts and compensation

A manual adjustment (`folio.post_adjustment`) is a charge like any other —
positive to add to the balance, negative to reduce it — posted with its own
reason and idempotency key, so it shows on the folio and, once invoiced,
prints on the guest's bill as an itemised line rather than a hidden
correction.

**Who may post an adjustment**: Finance Manager, Front Office Manager, Hotel
Manager, General Manager, Hospitality Administrator or System Manager
(`ADJUSTMENT_ROLES`). This is a wider group than can reverse a charge,
because compensation and small discounts are a routine front-office and duty
manager decision, while reversing a posted charge is a finance decision.

**Discounts** are the one charge type stored as a credit automatically: an
operator enters a discount as a positive number and the folio stores it
negative (`CREDIT_CHARGE_TYPES`), so every other place that sums charges —
the balance, the invoice, reconciliation — does a plain addition without
having to know that discounts subtract.

Both a reversal and an adjustment are recorded on the folio log with a
reason, actor and timestamp, so a discount and a correction are equally
visible to whoever reviews the folio later.

---

## 5. Splitting a folio

`folio.split_folio` moves a chosen set of charge rows from one folio onto a
new one — the standard company-pay / guest-pay separation, and the mechanism
`corporate.split_folio_by_billing_rule` uses to apply an account's billing
rule automatically (section 6).

**Charges are moved, not copied.** Each selected row is appended to the new
folio and removed from the source; both folios are then recalculated. A
charge exists on exactly one folio at any time. If the split copied instead
of moved, the source and target folios would sum to more than the guest
actually owes — a duplicate liability that would show up as a variance the
first time either folio was reconciled against ERPNext.

A folio that is **Settled** or **Closed** cannot be split — there is nothing
left to redirect once the balance is paid off and the charges have posted.

**Who may split**: the same `ADJUSTMENT_ROLES` as an adjustment (Finance
Manager, Front Office Manager, Hotel Manager, General Manager, Hospitality
Administrator, System Manager).

Both the source and the new folio are logged (`"Charges split out"` /
`"Charges split in"`) with the row list and each other's name, so the split
can be traced in either direction.

Merging works the same way in reverse (`folio.merge_folio`): every charge and
payment line moves from the source folio to the target, the source is
recalculated to empty and transitioned to **Closed** with a reason recording
which folio it merged into, and neither folio involved may already be
Settled or Closed.

---

## 6. Corporate credit

A **Hospitality Corporate Account** carries a credit limit, and every booking
that draws on it is checked against that limit under a row lock
(`corporate.consume_credit`), so two bookings confirmed at the same instant
cannot both read the same remaining credit and both fit inside it.

**What happens when a booking would exceed the limit:**

- If the account's credit limit is exceeded and the caller has not asked for
  an exception, the attempt is refused outright with
  *"This booking exceeds the credit limit for `<account>`. Finance approval
  is required."* The account's credit status is set to **Exception
  Required**, and a credit log entry records the attempt, the amount, and
  that it was refused.
- If the caller does ask for an exception (`allow_exception=True`), the
  system requires the approving user to hold one of the
  `CREDIT_APPROVAL_ROLES` — **Finance Manager**, **Hospitality
  Administrator** or **System Manager** — before letting the credit be
  consumed past the limit. The credit log records the approval and who gave
  it.
- `set_credit_status` is the wider control: it can move an account between
  **Active**, **Exception Required** and **Suspended**. Restoring an account
  to Active additionally allows **General Manager** as an escalation above
  Finance. Every status change requires a reason.
- An account with a credit limit of zero or less is treated as
  **unlimited** — every check against it passes automatically. This is a
  configuration choice on the account, not an override.
- A **suspended** account fails every credit check outright, regardless of
  amount.
- A booking is also refused if the corporate contract is not currently valid
  — before its start date, after its end date, or on an inactive account
  (`assert_contract_valid`).

**How credit is released**: `corporate.release_credit` reduces
`credit_used` by the given amount (never below zero) when a booking that
consumed credit is cancelled, or when its invoice is settled. This, too,
writes a credit log entry, with a reason if one is given.

**Billing rules and company-pay**: an account's `billing_rule` decides which
charge types the company picks up —

| Billing rule | Company pays |
|---|---|
| Company Pays All | every charge type |
| Company Pays Room Only | Room Charge |
| Company Pays Room and Tax | Room Charge, Tax, Service Charge |
| Guest Pays All | nothing |

`corporate.split_folio_by_billing_rule` reads this rule, finds every
unreversed charge on the folio that the rule assigns to the company, and
splits them onto a new folio of type **Company** using the move-not-copy
mechanism in section 5.

`api/corporate.py` exposes an account's negotiated rates and credit position,
a read-only credit check, and `set_credit_status` for suspending, restoring or
flagging an account, but nothing in `/pms` calls it and there is no corporate
screen. Working an account, approving a credit exception and applying a
billing split are performed from Desk, against the Hospitality Corporate
Account doctype and its child tables, through that API directly, or by
calling the service functions (bench console / server script) — credit
consumption and release themselves (`consume_credit` / `release_credit`) are
deliberately not exposed anywhere outside the booking flow they run under, as
described above.

---

## 7. The night audit, step by step

A property has exactly one business date at a time
(`Hospitality Property.business_date`), and the Night Audit is the only
process allowed to move it forward. Follow this sequence in order; each step
is safe to re-run if the shift is interrupted.

Where to do this: **Night Audit** (`/pms/night-audit`), which lays the steps
out in this exact order and disables Close purely from the server's own
blocking-exception count — or the **Hospitality Night Audit** doctype in Desk,
which drives the same service calls.

1. **Start the audit.**
   Open (or resume) the audit for the property's current business date. If
   an audit for that date is already open, the same record is returned — two
   auditors starting at once work on one audit, not two. Starting an audit
   for a date that is already **Closed** is refused.
   Requires: Night Auditor, Hotel Manager, General Manager, Hospitality
   Administrator or System Manager (`AUDITOR_ROLES`, required for every audit
   step in this section).

2. **Review.**
   Moves the audit from **Open** to **Reviewing** and rebuilds the exception
   list from scratch — a resolved exception disappears rather than lingering
   as a stale blocker. Review reads and records only; it posts nothing and
   forces no other state. It is safe, and expected, to run more than once
   while exceptions are cleared. Review also recomputes the day's figures
   (arrivals, departures, in-house count, occupancy, ADR, RevPAR — see
   section 15).

3. **Resolve exceptions.**
   Work through the exception list (section 8) one row at a time. Each
   resolution requires a note describing how it was dealt with; the
   resolving user and timestamp are recorded automatically. A **Warning**
   exception can be cleared this way. A **Blocking** exception must
   genuinely be fixed — see section 8 for what "fixed" means for each type,
   since some cannot be waived by a note alone.

4. **Mark no-shows.**
   A deliberate, separate step — not automatic — because marking a no-show
   applies a cancellation charge under the guest's no-show policy, and the
   auditor should choose to apply it rather than have it happen as a side
   effect of review. This turns every unresolved arrival for the business
   date into a no-show and updates the audit's no-show count. (The
   underlying `mark_no_show` also refuses if the reservation's arrival date
   is still ahead of the business date — a guest cannot be a no-show on a
   day that has not ended.)

5. **Post room charges.**
   Moves the audit into **Posting** and posts one night's room charge to the
   folio of every in-house stay that owes one for this business date — a
   stay arriving on or before the date and departing after it (a departure
   on the business date itself does not consume that night). Each post is
   idempotent per stay per date (section 9); re-running this step for a date
   already posted charges nothing again and is reported back as "already
   posted," not as an error. A stay with no folio is recorded as a failure
   rather than silently skipped. The audit's posted/skipped/failed counts and
   room revenue total are updated.

6. **Mark due-outs.**
   Flags every in-house stay departing tomorrow (or earlier, if overdue) as
   **Due Out**, so the morning shift knows who is leaving before the guest
   reaches the desk.

7. **Reconcile.**
   Recomputes the day's figures again, then compares every Settled or Closed
   folio at the property against what actually reached ERPNext (section 12).
   Any folio that does not reconcile adds a **Blocking** "Unposted Charge"
   exception naming the folio and the variance. If no blocking exception
   remains after this, the audit advances to **Ready to Close** on its own —
   an audit with nothing left to post does not need to pass through Posting
   to become closable.

8. **Close.**
   Refuses outright while any blocking exception is unresolved, giving the
   exact count still open. If the audit is not yet at Ready to Close, closing
   forces that transition first (again gated on no blocking exceptions).
   Close also re-checks that the property's current business date still
   matches the date this audit is closing — if someone else has already
   moved the date, the close is refused rather than moving the date twice.
   Only `close` may ever set the property's business date. On success it
   advances the property's business date by one day, moves the audit to
   **Closed**, and stamps who closed it and when.

A convenience path, `run_full_audit`, chains start → review → post room
charges → mark due-outs → reconcile in one call, but it stops there
deliberately: a human decides the day is actually done. It never calls
`close` itself, because an automated close would defeat the entire point of
the exception list.

---

## 8. Exceptions

Every exception the audit raises falls into one of four types
(`audit_exceptions` child table, rebuilt on every `review`):

| Exception type | Raised when | Severity | How it clears |
|---|---|---|---|
| **Unresolved Arrival** | A confirmed or guaranteed reservation was due to arrive on or before the business date and has not checked in. | **Blocking** | Check the guest in, or mark the reservation a no-show (step 4). Simply annotating a resolution note does not make the underlying reservation disappear from this list on the next review — the reservation itself must move out of Confirmed/Guaranteed. |
| **Unsettled Departure** | A stay that is In House or Due Out has a departure date on or before the business date. | Warning | Check the guest out, or resolve the row with a note explaining why the stay is staying (e.g. an extension). |
| **Failed Posting** | A Sales Invoice or Payment Entry posting attempt is in the **Failed** state on the property's posting log. | **Blocking** | Fix the underlying problem (missing posting profile, missing item mapping, missing account) and retry the posting under its original key (section 11), or resolve the row with a note if finance has decided to handle it outside the audit. |
| **Unposted Charge** | Raised only during `reconcile` (step 7): a Settled or Closed folio's totals do not match what ERPNext actually shows posted against it. | **Blocking** | Post the folio's outstanding charges to ERPNext (section 11) and reconcile again; the variance will not reappear once the folio and ERPNext agree. |

**Blocking exceptions are what stop a close.** `close` refuses unconditionally
while any exception is both severity Blocking and not marked resolved,
regardless of how many Warning-severity rows remain open. An auditor can
close a business date with unresolved Unsettled Departures on it (a guest who
is genuinely staying longer), but never with an unresolved Unresolved
Arrival, Failed Posting or Unposted Charge.

Resolving any exception — blocking or not — always requires a non-blank
resolution note; the resolving user and timestamp are recorded.

---

## 9. Why posting is safe to re-run

Every charge, every payment, and every ERPNext document raised from a folio
carries an **idempotency key** — a string that names *what this posting is*,
not *when it happened*. The room charge posted for a given stay on a given
business date is always keyed
`room-charge:{stay}:{business_date}`; the invoice for a given folio is
always keyed `folio-invoice:{folio}`; the payment entry for a given folio
payment line is always keyed `folio-payment:{payment_row}`; a gateway
payment applied to a folio is keyed `gateway:{transaction}`.

Before anything is written, the code looks for a row already posted under
that key:

- On a folio, `post_charge` and `post_payment` check the charge/payment
  child table for a row with that `idempotency_key`. If one exists, the
  original row is returned with `duplicate: true` and nothing new is
  appended.
- On the ERPNext boundary, the **Hospitality Financial Posting Log** carries
  a database-level unique constraint on `idempotency_key`. `_claim` looks up
  the key first; if a log row already exists and is Posted or Reconciled,
  the original result is returned. If two requests somehow race past that
  check at once, the unique constraint itself decides: the second insert
  fails with a duplicate-entry error, rolls back, and reads back the
  winner's row. The database, not application logic, is the final guard.

**In plain terms**: running the Night Audit twice for the same business date
does not charge a guest twice, because the second run recognises every room
charge it is about to post as one it has already posted, under the same key,
and returns "already posted" instead. The same guarantee is what makes a
replayed payment gateway callback credit a guest once no matter how many
times the gateway resends it (section 13), and what makes retrying a failed
ERPNext posting (section 11) safe to do as many times as it takes.

---

## 10. Closing and reopening the business date

**Closing** (`night_audit.close`) does exactly three things once every
blocking exception is clear: it advances `Hospitality Property.business_date`
by one day (the *only* place in the system that field is permitted to move —
enforced by a dedicated flag the property document checks), it moves the
audit to **Closed**, and it stamps who closed it and when.

Blocking exceptions exist specifically so that closing over one is not
possible: an Unresolved Arrival, a Failed Posting or an Unposted Charge left
open at close time is exactly how a hotel would lose a day's revenue quietly
— a guest who never checked in and was never marked a no-show, an invoice
that never reached ERPNext, or a folio whose totals silently drifted from the
ledger. The refusal is unconditional; there is no override that skips it.

**Reopening** (`night_audit.reopen`) is a manager exception, not a routine
step. It:

- is restricted to **Hotel Manager**, **General Manager**, **Finance
  Manager**, **Hospitality Administrator** or **System Manager**
  (`REOPEN_ROLES`) — a wider group than closes the audit day-to-day, because
  reopening is specifically a management decision;
- requires a non-blank reason, recorded on the audit along with who reopened
  it and when;
- only works on an audit that is currently **Closed**;
- sets the property's business date back to the audit's business date, and
  moves the audit back to **Reviewing** — not to Open, and not straight to
  Ready to Close — so the day is worked through the exception list again
  before it can be closed a second time.

Reopening the business date does not, by itself, reopen any folio that was
closed while working that date. A folio reopening is a separate action
(section 2) with its own role check and its own reason.

---

## 11. Posting to ERPNext

**When it happens.** A folio's charges and payments reach ERPNext at one of
three points:

- **At checkout** (`checkout.check_out`, via `_post_to_erp`): if the folio
  has any charge not yet posted, a Sales Invoice is raised for all of them
  together; every payment line not yet posted is then raised as its own
  Payment Entry. This happens *before* the folio is settled/closed and
  *before* the stay is checked out and the room released — deliberately, so
  that if posting fails, the guest is still in house and the room is still
  theirs, and nothing about the stay is lost. Reversing that order would risk
  a room being resold while the previous guest's revenue was never recorded.
- **During the Night Audit**, for any folio a reconciliation pass finds with
  unposted charges (section 7), or ahead of time via the standalone endpoint
  below.
- **On demand**, via `POST /api/method/hospitality_pms.api.checkout.post_folio`
  (`folio` argument) — posts a folio's invoice and payments without checking
  the guest out. This is what the Night Audit and finance use to catch up a
  folio that failed to post at checkout. Restricted to the same
  `RECONCILIATION_ROLES` as the reconciliation views below, plus write
  permission on the folio.

**What documents are created:**

- **Sales Invoice** — one per folio, for every charge line not yet marked
  `is_posted_to_erp`. Reversed charges and their compensating reversal lines
  are both included, so the invoice matches the folio line-for-line. A
  charge already carried on an earlier invoice for the same folio is
  skipped, so a second invoicing run for the same folio only picks up what
  is genuinely new. Once submitted, every included charge line is stamped
  `is_posted_to_erp = 1` with the invoice name, so it cannot be picked up by
  a later invoice.
- **Payment Entry** — one per folio payment line, not aggregated, so a
  refund, a deposit and a settlement each reconcile against their own ledger
  entry. A receipt debits the receivable account and credits the resolved
  cash/bank/mode-of-payment account; a refund runs the other way. Getting
  this the wrong way round is exactly the failure the code calls out
  explicitly in comments — it would post the payment to the wrong side of
  the ledger.

Both raise against the property's active **Hospitality Posting Profile**,
which supplies the receivable account, income accounts, cost centre, tax
template and item mapping per charge type. **A property with no active
posting profile cannot post at all** — the system refuses rather than
guessing a default account, because posting to an account nobody chose is
how a hotel's revenue ends up in the wrong place for a month.

**When a posting fails.** Every attempt — success or failure — writes a
**Hospitality Financial Posting Log** row first, before the ERPNext document
is created, so the attempt is on record regardless of outcome. On failure,
the log row is marked **Failed** with the attempt count incremented and the
full error message recorded, and the original exception is re-raised to the
caller. To recover:

1. Open the failed log row (Desk: **Hospitality Financial Posting Log**, or
   the reconciliation view in section 12) and read `error_message` — this is
   the actual exception from ERPNext (a missing account, a missing item
   mapping, a validation error), not a generic failure.
2. Fix the underlying cause (configure the posting profile, activate the
   missing charge-item mapping, correct the customer record, whatever the
   error names).
3. Retry under the same key: `POST
   /api/method/hospitality_pms.api.checkout.retry_posting` with the log
   name, or `posting.retry_posting(log)` directly. This re-runs
   `post_folio_invoice` or `post_folio_payment` against the same folio using
   the log's own idempotency key — a **Posted** or **Reconciled** row is
   never re-sent (retrying it is a no-op that reports the existing result), a
   **Cancelled** row cannot be retried at all, and only a genuinely
   **Failed** row is actually retried. Retrying is restricted to
   `RECONCILIATION_ROLES` (section 12).

A failed posting also surfaces automatically as a **Blocking** "Failed
Posting" exception the next time the Night Audit reviews the business date
(section 8), so it cannot be missed by staying only in the posting log.

---

## 12. Reconciliation

**The reconciliation view.** `GET
/api/method/hospitality_pms.api.checkout.reconciliation` (property optional,
defaults to the caller's resolved property) returns two things a finance user
needs every day: the full list of currently **Failed** postings for the
property, and every Settled or Closed folio that still has a charge marked
`is_posted_to_erp = 0` — the folios finance most needs to see, because the
guest has already gone and the revenue is not yet in the ledger. Restricted
to `RECONCILIATION_ROLES`: Finance Manager, Accounts User, Night Auditor,
Hotel Manager, General Manager, Hospitality Administrator, System Manager.

**One folio at a time**: `GET
/api/method/hospitality_pms.api.checkout.reconcile_folio` (`folio`) runs
`posting.reconcile_folio`, which is also what the Night Audit calls against
every Settled/Closed folio during its own reconcile step (section 7). It
returns:

- the folio's own totals (`folio_charges`, `folio_payments`);
- what ERPNext actually shows against submitted documents linked from this
  folio (`erp_invoiced`, `erp_paid`) — computed by summing only charge/payment
  lines whose linked Sales Invoice / Payment Entry is docstatus 1 (submitted);
- the differences (`charge_variance`, `payment_variance`);
- the specific unposted charge and payment row names;
- any Failed posting log rows tied to the folio;
- `is_reconciled`: true only when both variances are under half a cent and
  there are no failed postings for the folio.

**What a variance means.** A non-zero `charge_variance` or `payment_variance`
means the folio's operational total and what ERPNext has actually recorded
for it disagree — either because something has not been posted yet, or
because a posting failed. This function deliberately **reports** the
difference; it does not correct it. Auto-correcting here would paper over
the exact discrepancy finance is meant to see and act on.

**The routine for clearing a variance:**

1. Look at `unposted_charges` / `unposted_payments` on the reconciliation
   result — if either is non-empty, the folio simply has not been posted yet.
   Post it (`post_folio`, section 11) and reconcile again.
2. If `failed_postings` is non-empty, resolve each one as in section 11
   (read the error, fix the cause, retry under its original key).
3. Once `is_reconciled` is true, and the posting has genuinely been checked
   off, mark the relevant posting log row **Reconciled**
   (`posting.mark_reconciled`) so it is recorded as reviewed and does not
   surface again as an open item.
4. If a variance persists after every unposted item is posted and every
   failed posting is retried, it is a data problem (an invoice cancelled in
   ERPNext outside this app, a manually edited amount) that needs a finance
   investigation outside the automated tools — the system will keep
   reporting it accurately rather than hiding it.

---

## 13. Payments and refunds

**Gateway transactions.** Every card or online payment is tracked as a
**Hospitality Payment Transaction**, separate from the folio payment it
eventually produces. `payments.initiate_payment` starts one under its own
idempotency key; replaying that key returns the original transaction rather
than starting a second charge attempt. A provider that captures immediately
(a manual desk card payment) applies straight to the folio; a hosted
checkout waits for the provider's callback.

**What a lost callback looks like.** If the gateway's callback never arrives,
or arrives and is lost, the transaction sits in whatever non-terminal state
it was last set to (commonly **Initiated** or **Pending**) — the folio never
gets its payment line, and the guest believes they have paid while the folio
still shows a balance.

**How status sync resolves it.** `payments.sync_status` (`POST
/api/method/hospitality_pms.api.payments.sync_status`, transaction name) asks
the provider directly what actually happened — "the provider is the
authority on its own transaction, so whatever it says wins." Whatever status
comes back is written onto the transaction, and if it is now Captured, the
payment is applied to the folio under the key `gateway:{transaction}` — the
same key `_apply_to_folio` always uses for that transaction, so however many
times this ends up running (immediate capture, a delayed callback, a manual
sync), the guest is credited exactly once.

A callback that names a transaction the system has no record of, or one
addressed to a transaction already in a terminal state (Captured, Failed,
Cancelled, Refunded), is not treated as an error: an unmatched callback is
parked in the **Hospitality Integration Failure Queue** for someone to
reconcile by hand, and a callback replayed against a transaction already
finished is reported back as a duplicate and otherwise ignored.

**The webhook itself never trusts an amount or a status until the provider's
signature over the raw request body is verified.** An unsigned or
mis-signed callback is refused before anything from the payload is read or
written.

**Refunds** (`payments.refund_payment`, `POST
/api/method/hospitality_pms.api.payments.refund`) — always require a reason,
can only be issued against a transaction currently in a settled
(**Captured**) state, and cannot exceed what remains un-refunded on that
transaction (amount already refunded is tracked and checked). A successful
refund updates the transaction (moving it to **Refunded** or **Partially
Refunded**) and posts a negative payment line to the folio under
`gateway-refund:{key}`, so it is idempotent under retry exactly like every
other posting in this system.

**Who may issue a refund**: Finance Manager, Front Office Manager, Hotel
Manager, General Manager, Hospitality Administrator or System Manager
(`REFUND_ROLES`).

---

## 14. Daily and monthly checklist

### Daily (night auditor, every business date)

- [ ] Start the Night Audit for the business date (or confirm one is already open).
- [ ] Run review; read the exception list.
- [ ] Resolve every Warning-severity exception, or record a note explaining why it stands.
- [ ] Check in or no-show every Unresolved Arrival — a Blocking exception cannot be waived by a note alone.
- [ ] Mark no-shows for arrivals genuinely not coming.
- [ ] Post room charges; confirm the posted/skipped/failed counts make sense for the in-house count.
- [ ] Investigate every failed room charge posting (missing folio, posting error) before moving on.
- [ ] Mark due-outs for tomorrow's departures.
- [ ] Reconcile; confirm no new Unposted Charge exceptions appeared.
- [ ] Resolve every remaining Failed Posting exception (retry under its original key, or escalate to finance).
- [ ] Confirm zero blocking exceptions remain.
- [ ] Close the business date.
- [ ] Spot-check the day's occupancy, ADR and RevPAR against expectations.

### Daily (accounts user)

- [ ] Check the reconciliation view for the property: any failed postings, any Settled/Closed folio with unposted charges.
- [ ] Retry failed postings once their underlying cause is fixed.
- [ ] Mark cleared postings Reconciled.
- [ ] Review gateway transactions stuck in a non-terminal state; run status sync on any older than expected.
- [ ] Review the Integration Failure Queue for unmatched payment callbacks.

### Monthly (finance manager)

- [ ] Confirm every business date in the period is Closed with no outstanding blocking exceptions on record.
- [ ] Review every corporate account's credit log for exceptions approved during the period; confirm each has a documented reason and an authorised approver.
- [ ] Review every folio reversal and adjustment in the period for a valid reason and an appropriate approving role.
- [ ] Reconcile total posted Sales Invoice and Payment Entry values against the folio totals for the period.
- [ ] Review any reopened business dates or reopened folios in the period, and confirm each carries a reason and was actioned by an authorised role.
- [ ] Review refunds issued in the period for reason and authorisation.

---

## 15. Occupancy, ADR and RevPAR

All three are computed by `night_audit._refresh_figures`, run every time an
audit is reviewed or reconciled, from that business date's own figures —
not a rolling average.

**Occupancy** is occupied rooms over sellable rooms, as a percentage:

```
occupancy % = (occupied rooms / sellable rooms) × 100
```

- *Occupied rooms* is the count of stays currently In House or Due Out at
  the property.
- *Sellable rooms* is the count of active `Hotel Room` records at the
  property (`is_active = 1`) — rooms taken permanently out of inventory are
  not counted as sellable; rooms temporarily out of service are (there is no
  separate out-of-service exclusion in this calculation).

**ADR (average daily rate)** is revenue per *occupied* room:

```
ADR = room revenue for the business date / occupied rooms
```

`room revenue` here is exactly the `room_revenue` figure the audit itself
posted in step 5 (section 7) for that business date — the sum of the room
charges the audit posted, not the folio's total charges (which would also
include tax, services and adjustments). If there are no occupied rooms, ADR
is reported as zero rather than dividing by zero.

**RevPAR (revenue per available room)** is the same room revenue spread over
every *sellable* room, whether occupied or not:

```
RevPAR = room revenue for the business date / sellable rooms
```

This is precisely why a hotel can show a high ADR and a poor RevPAR at the
same time: ADR only measures what occupied rooms earned, while RevPAR
measures how well the whole inventory performed, occupied or empty. If there
are no sellable rooms, RevPAR is reported as zero.

All three figures, along with arrivals/departures expected and completed,
payments received and outstanding balance for the business date, are stored
on the Night Audit record itself and recomputed — not accumulated — every
time `review` or `reconcile` runs, so they always reflect the current state
of the day rather than a snapshot from whenever they were first calculated.
