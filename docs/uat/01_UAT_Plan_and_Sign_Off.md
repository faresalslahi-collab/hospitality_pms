# Hospitality PMS — User Acceptance Testing

**Document version:** 1.0 · **Applies to:** Hospitality PMS 16.1.0 (branch `version-16`) · **Governing baseline:** v1.2 approved document set

UAT is the last requirement before HPMS-1.0.0 Production Release. It is the one
form of validation the implementation team cannot perform on the hotel's behalf:
everything up to this point proves the system does what it was built to do, and
UAT proves it does what the hotel actually needs.

---

## 1. What has already been proved, and what has not

Do not re-test what is already covered. UAT exists to find what automated
testing structurally cannot: whether the workflows match how this hotel really
operates.

**Already validated by the implementation team:**

| Area | Evidence |
|---|---|
| Business rules and state machines | 139 automated regression checks across seven suites |
| Release candidate programme | 16 checks: full permission matrix, financial reconciliation, localisation/RTL, performance, cross-module integration |
| API surface | 10 checks including property scoping and read side-effect freedom |
| Reports | 21 of 21 execute against live data |
| Desk workspace | 10 checks: no broken links, role gating, deployment fixtures |
| Clean installation | App installs and migrates onto a fresh site from the repository alone |
| Backup and restore | Full backup with files restored onto a separate site; every row count matched and the restored site was functionally healthy |

**Not proved, and what UAT is for:**

- Does the check-in flow match how this front desk actually works at 3pm on a busy Friday?
- Are the refusals understandable to the person who hits them, or merely correct?
- Is anything missing that this hotel cannot operate without?
- Do the Arabic translations read naturally to Arabic-speaking staff?
- Are the reports the ones management will genuinely use?

A scenario can pass every automated check and still fail UAT. That is the point.

---

## 2. Scenario sets

| Set | File | Scenarios | Signed by |
|---|---|---|---|
| Front office | [02_UAT_Front_Office.md](02_UAT_Front_Office.md) | 15 | Front Office Manager |
| Operations | [03_UAT_Operations.md](03_UAT_Operations.md) | 19 | Housekeeping Manager, Maintenance Manager |
| Finance, night audit and administration | [04_UAT_Finance_Night_Audit_and_Administration.md](04_UAT_Finance_Night_Audit_and_Administration.md) | 20 | Finance Manager, Night Auditor |

Every scenario carries its own tester name, date and pass/fail box. The
signatures in section 7 of this document accept the set as a whole.

---

## 3. Before you start

**Environment.** Run UAT on a dedicated site, never on production and never on
a developer's site. Restore a copy of the intended production configuration so
testers work against realistic data.

```bash
bench new-site uat.<yourdomain>
bench --site uat.<yourdomain> install-app erpnext
bench --site uat.<yourdomain> install-app hospitality_pms
bench --site uat.<yourdomain> migrate
```

**Configuration.** Follow the Administrator and Setup Guide in full. UAT starts
from a configured property, not an empty one. At minimum you need:

- one Hospitality Property with a business date, company, currency and accounting mapping
- at least two Room Types and eight Hotel Rooms, so availability arithmetic is visible
- one Rate Plan with rates, and a cancellation and no-show policy
- one Posting Profile mapping charge types to ERPNext items
- one Corporate Account with a credit limit
- one payment provider, set to Manual for UAT unless a sandbox gateway is available

**Test users.** One per role being tested, each with only that role. Testing
front office as an administrator proves nothing about what a front desk agent
can actually do — the permission boundaries are a substantial part of what is
being accepted.

**Do not test with production guest data.** Use invented names. Real guest
identification data in a test system is a privacy problem, not a testing detail.

---

## 4. How to run a scenario

1. Sign in as the role named at the top of the scenario.
2. Follow the steps in order.
3. Compare what you see to the **Expected result** column.
4. Tick Pass only if every step matched. Anything else is a Fail with a note.
5. Where a step expects a refusal, the refusal is the pass. A step that succeeds
   when it should have been refused is a **critical** failure, not a cosmetic one.

Record what you saw, not whether you think it is acceptable. Judgement about
severity happens in the triage in section 5.

---

## 5. Defect handling

| Severity | Meaning | Effect on go-live |
|---|---|---|
| Critical | Money is wrong, data is lost, a permission boundary is crossed, or the hotel cannot operate | Blocks release |
| High | A required workflow is unusable or badly wrong | Blocks release unless a workaround is accepted in writing |
| Medium | Works, but awkward or confusing | Fix in the first maintenance release |
| Low | Cosmetic, wording, layout | Batch for later |

Anything where the system **allowed something it should have refused** is
Critical regardless of how minor it looks. Those are the failures that cost
money quietly.

Log each defect with: scenario reference, role, what you did, what happened,
what you expected.

---

## 6. Known limitations at the time of UAT

Recorded so testers do not raise them as defects. They are accepted, not hidden.

| Limitation | Status |
|---|---|
| Fatora payment adapter | Endpoints and status vocabulary are best-effort and need verifying against current Fatora documentation before any live payment. Use the Manual provider for UAT. |
| Regulatory submission | Exports generate and are marked submitted for manual filing; no authority transport is wired |
| Hardware (door lock, ID scanner) | Ships with mock adapters until a vendor is chosen; key card issuance works, no physical encoder is driven |
| Group reservations | Blocks and rooming lists exist; pickup and cutoff release are not yet automated |
| Guest stay history | The guest profile shows aggregate figures; there is no itemised stay list |
| Some workflows run in Desk | Corporate accounts, group reservations, rate plans and kitchen requisitions have no dedicated `/pms` screen and are maintained in Desk. Each scenario says which surface to use. |

---

## 7. Acceptance

UAT is accepted when every Critical and High defect is closed or formally
accepted in writing, and each set below is signed.

| Set | Accepted by | Role | Signature | Date |
|---|---|---|---|---|
| Front office | | Front Office Manager | | |
| Operations — housekeeping | | Housekeeping Manager | | |
| Operations — maintenance | | Maintenance Manager | | |
| Finance and night audit | | Finance Manager | | |
| Night audit procedure | | Night Auditor | | |
| Overall acceptance | | General Manager | | |

**Outstanding defects accepted at sign-off:**

| Reference | Severity | Description | Accepted by | Agreed resolution |
|---|---|---|---|---|
| | | | | |

---

## 8. After UAT

Acceptance here satisfies the UAT requirement of HPMS-1.0.0. The remaining
requirements are decisions, not tests:

- production migration approved
- deployment approved
- no unresolved critical defects — confirmed by the table above

The Operations Runbook covers the deployment itself, and its Known Limitations
section should be read alongside section 6 of this document before release is
approved.
