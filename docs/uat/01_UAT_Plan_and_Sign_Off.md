# Hospitality PMS — User Acceptance Testing

**Document version:** 2.0 · **Applies to:** Hospitality PMS 16.3.0 (branch `version-16`) · **Governing baseline:** v1.2 approved document set

UAT is the last requirement before production release. It is the one form of
validation the implementation team cannot perform on the hotel's behalf:
everything up to this point proves the system does what it was built to do, and
UAT proves it does what this hotel actually needs.

---

## 1. What changed in version 2.0 of this package

Version 1.0 was organised by department — front office, operations, finance.
That mirrored the code, not the hotel. A booking that arrives through a channel,
is confirmed by a reservation agent, checked in by the front desk, cleaned by
housekeeping, charged by a waiter and settled by a cashier crossed four separate
UAT documents and nobody owned the seam between them.

This version is organised by **end-to-end business journey**. Each journey is a
thing the hotel does from beginning to end, tested in order, by the roles that
really perform it. Handovers between departments are inside a journey rather
than between documents, because handovers are where systems fail.

It is also written against **16.3.0**. Version 16.2.0 added the front office
dashboard, the arrivals board, the departures board and the reservation
calendar; 16.3.0 added the room service board and the stay screen, and fixed
the arrivals board's assign-room link. None of those six screens had any
scenario before this package.

Every scenario from version 1.0 survives, re-homed into the journey it belongs
to and re-checked against the code as it stands today. Scenario references have
changed: the old FO-/OPS-/FIN- numbering is mapped to the new one in
[12_UAT_Coverage_Matrix_and_Gaps.md](12_UAT_Coverage_Matrix_and_Gaps.md).

---

## 2. What has already been proved, and what has not

Do not re-test what is already covered. UAT exists to find what automated
testing structurally cannot: whether the workflows match how this hotel really
operates.

**Already validated by the implementation team:**

| Area | Evidence |
|---|---|
| Business rules and state machines | 139 automated regression checks across seven suites |
| Release candidate programme | 16 checks: full permission matrix, financial reconciliation, localisation/RTL, performance, cross-module integration |
| API surface | 10 checks including property scoping and read side-effect freedom |
| Front office boards (16.2.0) | 12 checks: route resolution, read-only enforcement, permission and property scoping, query cost, translation completeness, RTL output |
| Reports | 21 of 21 execute against live data |
| Desk workspace and navigation | 10 checks: no broken links, role gating, deployment fixtures |
| Clean installation | App installs and migrates onto a fresh site from the repository alone |
| Backup and restore | Full backup with files restored onto a separate site; every row count matched |

**Not proved, and what UAT is for:**

- Does the arrival-day flow match how this front desk really works at 3pm on a busy Friday?
- Are the refusals understandable to the person who hits them, or merely correct?
- Is anything missing that this hotel cannot operate without?
- Do the Arabic translations read naturally to Arabic-speaking staff, and does the screen mirror properly?
- Are the reports the ones management will genuinely use?

A scenario can pass every automated check and still fail UAT. That is the point.

---

## 3. The journeys

| Journey | File | Scenarios | Primary signatory |
|---|---|---|---|
| **A** — Open the property for business | [02_UAT_Journey_A_Open_The_Property.md](02_UAT_Journey_A_Open_The_Property.md) | 8 | Hospitality Administrator |
| **B** — Sell a room and take the booking | [03_UAT_Journey_B_Sell_And_Book.md](03_UAT_Journey_B_Sell_And_Book.md) | 12 | Reservation Manager |
| **C** — Arrival day: prepare, greet, check in | [04_UAT_Journey_C_Arrival_Day.md](04_UAT_Journey_C_Arrival_Day.md) | 13 | Front Office Manager |
| **D** — Look after the guest in house | [05_UAT_Journey_D_Guest_In_House.md](05_UAT_Journey_D_Guest_In_House.md) | 26 | Housekeeping Manager, Maintenance Manager, Front Office Manager |
| **E** — Departure and settlement | [06_UAT_Journey_E_Departure_And_Settlement.md](06_UAT_Journey_E_Departure_And_Settlement.md) | 8 | Front Office Manager |
| **F** — Close the day | [07_UAT_Journey_F_Close_The_Day.md](07_UAT_Journey_F_Close_The_Day.md) | 9 | Night Auditor |
| **G** — Money reaches the ledger | [08_UAT_Journey_G_Money_To_The_Ledger.md](08_UAT_Journey_G_Money_To_The_Ledger.md) | 8 | Finance Manager |
| **H** — Corporate, groups and channels | [09_UAT_Journey_H_Business_Sources.md](09_UAT_Journey_H_Business_Sources.md) | 9 | Corporate Sales Manager |
| **I** — Reporting to management | [10_UAT_Journey_I_Management_Reporting.md](10_UAT_Journey_I_Management_Reporting.md) | 8 | General Manager |
| **J** — Trust: access, privacy, language | [11_UAT_Journey_J_Trust_Access_And_Language.md](11_UAT_Journey_J_Trust_Access_And_Language.md) | 10 | General Manager, Hospitality Administrator |

**111 scenarios.** Journeys A–J are ordered so that running them in sequence
takes one property from empty to trading to closed-and-reported. Data created in
an earlier journey is used by a later one; where that matters, the scenario says
so under **Prerequisites**.

[12_UAT_Coverage_Matrix_and_Gaps.md](12_UAT_Coverage_Matrix_and_Gaps.md) maps
every scenario to the screen, endpoint and report it exercises, and lists what is
implemented but **not** covered here, with the reason.

---

## 4. Before you start

**Environment.** Run UAT on a dedicated site, never on production and never on a
developer's site.

```bash
bench new-site uat.<yourdomain>
bench --site uat.<yourdomain> install-app erpnext
bench --site uat.<yourdomain> install-app hospitality_pms
bench --site uat.<yourdomain> migrate
```

Confirm the version before you begin. Every screen in this package is written
against 16.3.0; on an older build several will not exist.

```bash
bench --site uat.<yourdomain> version
# expect: hospitality_pms 16.3.0
```

**Configuration.** Journey A configures the property from scratch and is the
intended starting point. If you are testing against a pre-configured copy
instead, run Journey A as a verification pass rather than a build.

**Test users.** One per role, each holding **only** that role. Testing front
office as an administrator proves nothing about what a front desk agent can
actually do — the permission boundaries are a substantial part of what is being
accepted. Journey J depends entirely on this.

The roles used across this package:

| Journey | Roles you need |
|---|---|
| A | Hospitality Administrator, General Manager |
| B | Reservation Agent, Reservation Manager, Revenue Manager |
| C | Front Office Agent, Front Office Manager |
| D | Front Office Agent, Room Attendant, Housekeeping Supervisor, Housekeeping Manager, Maintenance Technician, Maintenance Manager, Guest Relations Officer, Kitchen User, Kitchen Manager (or Food and Beverage Manager) |
| E | Front Office Agent, Front Office Manager, Finance Manager |
| F | Night Auditor, Hotel Manager |
| G | Finance Manager, Accounts User, Front Office Agent |
| H | Corporate Sales Manager, Reservation Manager, Finance Manager, Hospitality Administrator |
| I | General Manager, Hotel Manager, Revenue Manager |
| J | Read-Only Auditor, Room Attendant, Front Office Agent, Hospitality Administrator |

**Do not test with production guest data.** Use invented names. Real guest
identification data in a test system is a privacy problem, not a testing detail.

**Two switches change several outcomes.** Before starting, ask whoever holds the
Hospitality Administrator role how this property is configured, and write the
answers here — scenarios in Journeys C and D branch on them.

| Setting | Where | Value for this UAT |
|---|---|---|
| Require ID at check-in | Hospitality Property (Desk) | ☐ On ☐ Off |
| Allow Vacant Dirty check-in | Hospitality Property (Desk) | ☐ On ☐ Off |

---

## 5. How to run a scenario

1. Sign in as the role named at the top of the scenario. Sign out between
   scenarios that name different roles.
2. Check the **Prerequisites** and **Test data** boxes before step 1. A scenario
   run without its prerequisites tests nothing.
3. Follow the steps in order and compare what you see to **Expected result**.
4. Tick Pass only if every step matched. Anything else is a Fail with a note.
5. Where a step expects a refusal, **the refusal is the pass**. A step that
   succeeds when it should have been refused is a Critical failure, not a
   cosmetic one.

Record what you saw, not whether you think it is acceptable. Every scenario
carries a pre-assigned **Severity if failed**, which is the implementation
team's assessment of what a failure there would mean. If your judgement differs,
tick your own severity in the result box and say why in Comments — a disagreement
about severity is useful information, not a problem.

---

## 6. Severity

| Severity | Meaning | Effect on go-live |
|---|---|---|
| **Critical** | Money is wrong, data is lost, a permission boundary is crossed, or the hotel cannot operate | Blocks release |
| **High** | A required workflow is unusable or badly wrong | Blocks release unless a workaround is accepted in writing |
| **Medium** | Works, but awkward or confusing | Fix in the first maintenance release |
| **Low** | Cosmetic, wording, layout | Batch for later |

Anything where the system **allowed something it should have refused** is
Critical regardless of how minor it looks. Those are the failures that cost money
quietly.

Log each defect with: scenario reference, role, what you did, what happened, what
you expected.

---

## 7. Known limitations at the time of UAT

Recorded so testers do not spend time raising them as defects. They are accepted,
not hidden. The fuller list, with the reason each one is not covered by a
scenario, is in
[12_UAT_Coverage_Matrix_and_Gaps.md](12_UAT_Coverage_Matrix_and_Gaps.md) §3.

| Limitation | Status |
|---|---|
| Fatora payment adapter | Endpoints and status vocabulary are best-effort and need verifying against current Fatora documentation before any live payment. Use the Manual provider for UAT. |
| Regulatory submission | Exports generate and are marked submitted for manual filing; no authority transport is wired |
| Hardware (door lock, ID scanner) | Ships with mock adapters until a vendor is chosen; key card issuance works, no physical encoder is driven |
| Group reservations | Blocks and rooming lists exist; pickup and cutoff release are not automated |
| Guest stay history | The guest profile shows aggregate figures; there is no itemised stay list |
| Some workflows run in Desk | Corporate accounts, group reservations, rate plans, restrictions, and kitchen **stores** (requisitions and wastage) have no dedicated `/pms` screen. Each scenario says which surface to use. Room service ordering **does** have one — see D-20 to D-22. |
| Dashboard performance figures | Occupancy, ADR and RevPAR come from the last **closed** Night Audit and are stamped with its date. Before the first close they are deliberately absent, not zero. Tested by **F-09**. |

---

## 8. Acceptance

UAT is accepted when every Critical and High defect is closed or formally
accepted in writing, and each journey below is signed.

| Journey | Accepted by | Role | Signature | Date |
|---|---|---|---|---|
| A — Open the property | | Hospitality Administrator | | |
| B — Sell and book | | Reservation Manager | | |
| C — Arrival day | | Front Office Manager | | |
| D — Guest in house (housekeeping) | | Housekeeping Manager | | |
| D — Guest in house (maintenance) | | Maintenance Manager | | |
| D — Guest in house (service and kitchen) | | Front Office Manager | | |
| E — Departure and settlement | | Front Office Manager | | |
| F — Close the day | | Night Auditor | | |
| G — Money to the ledger | | Finance Manager | | |
| H — Corporate, groups and channels | | Corporate Sales Manager | | |
| I — Reporting | | General Manager | | |
| J — Trust, access and language | | Hospitality Administrator | | |
| **Overall acceptance** | | General Manager | | |

**Outstanding defects accepted at sign-off:**

| Reference | Severity | Description | Accepted by | Agreed resolution |
|---|---|---|---|---|
| | | | | |

---

## 9. After UAT

Acceptance here satisfies the UAT requirement of the production release. The
remaining requirements are decisions, not tests:

- production migration approved
- deployment approved
- no unresolved critical defects — confirmed by the table above

The Operations Runbook covers the deployment itself, and its Known Limitations
section should be read alongside section 7 of this document before release is
approved.
