# Journey G — Money reaches the ledger

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Finance Manager
**Surface:** `/pms` and Desk (ERPNext), together.

The PMS is a subledger. This journey proves that what the front desk records
reaches ERPNext once, correctly, and can be reconciled afterwards — and that
nobody can quietly change it once it has.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journeys C, D, E and F passed. The
posting profile from **A-06**, with at least one charge type deliberately left
unmapped for **G-03**.

**Test data to prepare:** one in-house stay you can check out during this
journey, with a charge and a payment on its folio.

---

### G-01 · Checkout posts a Sales Invoice and a Payment Entry

| | |
|---|---|
| **Role** | Front Office Agent to check out, Finance Manager to inspect |
| **Surface** | `/pms/checkout/<stay>` then Desk → Accounting |
| **Prerequisites** | A stay ready to check out with a settled folio carrying at least one charge and one payment |
| **Test data** | The folio's total charges and total payments |
| **Severity if failed** | **Critical** — revenue never reaches the ledger |

| # | Step | Expected result |
|---|---|---|
| 1 | Note the folio's total charges and total payments. | Recorded. |
| 2 | Check the guest out. | Succeeds. |
| 3 | In Desk, open **Sales Invoice** and find the one raised for this stay. | It exists and is **submitted**. |
| 4 | Compare its total to the folio's total charges. | They match. |
| 5 | Check its line items. | Each maps to the ERPNext Item you configured in A-06 — not a generic catch-all. |
| 6 | Open **Payment Entry** and find the one for this folio's payment. | It exists, is submitted, and its amount matches the payment. |
| 7 | Check the customer on both. | The guest's linked ERPNext Customer, and the property's company and cost center. |

**Pass criteria:** One submitted Sales Invoice for the charges and one submitted Payment Entry per payment, with amounts matching the folio exactly.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-02 · Folio and invoice reconcile, and the folio says so

| | |
|---|---|
| **Role** | Finance Manager |
| **Surface** | Desk → Reports → Folio vs Invoice; `/pms/folios/<folio>` |
| **Prerequisites** | G-01 passed |
| **Test data** | The folio from G-01 |
| **Severity if failed** | **Critical** — finance cannot prove the subledger agrees with the ledger |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the folio and inspect the charge lines. | Each posted line is stamped as posted to ERP and carries its Sales Invoice reference. |
| 2 | Run the **Folio vs Invoice** report for the period. | The folio appears with matching folio and invoice totals, and a zero difference. |
| 3 | Look for any row in that report with a non-zero difference. | Investigate and record any you find — a difference is a finance defect, not a display issue. |
| 4 | Open the **Financial Posting Log** in Desk and find this folio's entries. | One entry per posting, each with a unique idempotency key and a success status. |

**Pass criteria:** The report shows zero difference for this folio, and every posting is traceable in the log.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-03 · A broken mapping fails loudly, is retried, and posts exactly once

| | |
|---|---|
| **Role** | Finance Manager |
| **Surface** | `/pms`, Desk |
| **Prerequisites** | The charge type you deliberately left unmapped in **A-06** |
| **Test data** | An in-house stay with an open folio |
| **Severity if failed** | **Critical** — either revenue is lost silently, or it is posted twice |

| # | Step | Expected result |
|---|---|---|
| 1 | Post a charge of the **unmapped** type onto a folio. | The charge posts to the folio — the PMS side works. |
| 2 | Check that stay out, or run the posting for its folio. | Posting to ERPNext **fails**. The failure is reported, not swallowed. |
| 3 | Confirm the guest's operational state. | Still in house, room still theirs — nothing was lost. The financial step comes first on purpose. |
| 4 | Run the **Failed Postings** report. | This failure is listed, with its reason. |
| 5 | Fix the posting profile: map that charge type to a real Item. | Saves. |
| 6 | Retry the posting. | Succeeds. |
| 7 | Check ERPNext. | Exactly **one** Sales Invoice for this folio, not two. |
| 8 | Re-run **Failed Postings**. | The entry is cleared or marked resolved. |

**Pass criteria:** The failure is visible and non-destructive, the retry succeeds, and the retry produces exactly one invoice.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-04 · A posted charge cannot be edited or deleted, by anyone

| | |
|---|---|
| **Role** | Finance Manager, then System Manager |
| **Surface** | Desk |
| **Prerequisites** | A folio with posted charges |
| **Test data** | None |
| **Severity if failed** | **Critical** — the subledger becomes unreconcilable and revenue can be altered after posting |

| # | Step | Expected result |
|---|---|---|
| 1 | In Desk, open the folio and try to change a posted charge's amount. Save. | Refused. |
| 2 | Try to delete the charge row. Save. | Refused. |
| 3 | Try to delete a **payment** row. Save. | Refused. |
| 4 | Repeat all three as **System Manager**. | Also refused. Being an administrator is not a route around this. |
| 5 | Try to delete the whole folio. | Refused. |

**Pass criteria:** Every attempt is refused, including as System Manager. **Any route that succeeds is Critical and must be named in Comments.**

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-05 · A correction is a reversal, with a reason and a name against it

| | |
|---|---|
| **Role** | Finance Manager |
| **Surface** | `/pms/folios/<folio>` |
| **Prerequisites** | A folio with a charge to correct |
| **Test data** | A reason |
| **Severity if failed** | High — corrections happen without an audit trail |

| # | Step | Expected result |
|---|---|---|
| 1 | Reverse a charge, leaving the reason blank. | Refused. |
| 2 | Enter a reason and reverse. | A new reversing line appears; the original stays, marked reversed. |
| 3 | Read both lines. | The reversal names what it reverses and carries your reason. |
| 4 | Check who and when. | Reversed-by and reversed-on are recorded. |
| 5 | Check the balance. | Net effect of the pair is zero. |
| 6 | Post an **adjustment** with a reason, and check the folio. | An adjustment line appears with the reason recorded. |

**Pass criteria:** Corrections are additive and attributable — never edits.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-06 · A front desk agent cannot reverse a charge; finance can

| | |
|---|---|
| **Role** | Front Office Agent, then Finance Manager |
| **Surface** | `/pms/folios/<folio>` |
| **Prerequisites** | A folio with a posted charge |
| **Test data** | None |
| **Severity if failed** | **Critical** — a permission boundary crossed on money |

| # | Step | Expected result |
|---|---|---|
| 1 | As the **agent**, open the folio and attempt to reverse a charge. | Refused, naming the roles required. If the control is not shown at all, attempt the same through the API to prove the server refuses too. |
| 2 | Re-open the folio. | Unchanged — no reversal line, no balance movement. |
| 3 | As **Finance Manager**, perform the identical reversal with a reason. | Succeeds. |

**Pass criteria:** The agent is refused **and causes no side effect**; finance succeeds.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-07 · Payments reconcile against the ledger

| | |
|---|---|
| **Role** | Finance Manager or Accounts User |
| **Surface** | Desk → Reports → Payment Reconciliation |
| **Prerequisites** | Several payments taken across Journeys D and E, by more than one method |
| **Test data** | Know how much was taken, and by what method |
| **Severity if failed** | High — the cashier's drawer cannot be balanced |

| # | Step | Expected result |
|---|---|---|
| 1 | Run **Payment Reconciliation** for the period you have been testing. | Every folio payment appears. |
| 2 | Check each row carries its method and its ERPNext Payment Entry. | It does. |
| 3 | Total the report and compare to the payments you actually took. | They agree. |
| 4 | Look for rows with no Payment Entry. | Any such row is a payment that never reached the ledger — record it. |
| 5 | Cross-check one row against Desk's Payment Entry list. | Amount, date and customer agree. |

**Pass criteria:** Every payment taken appears with a matching ledger entry, and the totals agree.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### G-08 · Night audit revenue reaches the ledger and matches the report

| | |
|---|---|
| **Role** | Finance Manager |
| **Surface** | Desk → Reports; `/pms/night-audit` |
| **Prerequisites** | Journey F completed — one closed audit exists with posted room charges |
| **Test data** | The Room revenue figure from the closed audit |
| **Severity if failed** | **Critical** — the hotel's headline revenue figure disagrees with its own ledger |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the closed audit and note **Room revenue**. | Recorded. |
| 2 | Run **Occupancy and Revenue** for that business date. | Its room revenue figure matches the audit exactly. |
| 3 | Open the folios that were charged that night. | Each carries one Room Charge for that date, and they sum to the same figure. |
| 4 | Run **Revenue by Room Type** for the same date. | It totals to the same room revenue. |
| 5 | Check that these charges have reached, or are queued to reach, ERPNext. | Posted charges carry an invoice reference; any not yet posted are visible in **Failed Postings** or are attached to a stay that has not checked out yet. Nothing is silently missing. |

**Pass criteria:** Three independent views of the same night's room revenue — the audit, the report and the folios — agree to the currency's precision.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey G sign-off

| | |
|---|---|
| **Scenarios passed** | ____ of 8 |
| **Critical/High defects open** | ____ |
| **Accepted by** | ____________________ (Finance Manager) |
| **Date** | ____________ |
