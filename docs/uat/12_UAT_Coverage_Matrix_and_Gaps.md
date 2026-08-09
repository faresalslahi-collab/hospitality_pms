# UAT coverage matrix and gap register

**Applies to:** Hospitality PMS 16.3.0 · **Maintained by:** the implementation team

This document exists so nobody has to guess what UAT covers. §1 maps the old
scenario numbers to the new ones. §2 maps every user-facing surface in the
application to the scenario that exercises it. §3 lists what is **implemented and
not covered**, with the reason — the honest part.

Read it before signing anything off. A journey signed without reading §3 has been
signed without knowing what was left out.

---

## 1. Where the old scenarios went

Version 1.0's 54 scenarios all survive. Nothing was dropped; several were split
or merged where the journey made a different cut.

| Old | New | Note |
|---|---|---|
| FO-01 | B-01 | |
| FO-02 | B-03 | |
| FO-03 | B-04 | |
| FO-04 | C-09 | Now reached from the arrivals board rather than a list |
| FO-05 | D-02 | |
| FO-06 | E-03 | Merged with the balance-blocking scenario |
| FO-07 | B-07 | |
| FO-08 | C-10 | |
| FO-09 | C-11 | |
| FO-10 | C-12 | |
| FO-11 | B-10 | |
| FO-12 | D-03 | |
| FO-13 | E-03 | Merged with FO-06 |
| FO-14 | B-11 | |
| FO-15 | B-09 | |
| OPS-01…06 | D-05…D-10 | Housekeeping, unchanged in substance |
| OPS-07…11 | D-11…D-15 | Maintenance, unchanged in substance |
| OPS-12…15 | D-16…D-19 | Guest services, unchanged in substance |
| OPS-16…19 | D-20…D-23 | Kitchen, unchanged in substance |
| FIN-01 | G-01 | |
| FIN-02 | G-02 | |
| FIN-03 | G-03 | |
| FIN-04 | G-04 | |
| FIN-05 | G-05 | |
| FIN-06 | G-06 | |
| FIN-07 | D-04 | Moved into the in-house journey, where the split actually happens |
| FIN-08…10 | H-01…H-03 | |
| FIN-11 | F-01 | |
| FIN-12 | F-03 | |
| FIN-13 | F-05 | Extended to prove the API refuses, not just the button |
| FIN-14 | F-06 | |
| FIN-15 | F-07 | |
| FIN-16 | F-08 | |
| FIN-17 | I-01 | |
| FIN-18 | I-05 | Expanded from 3 reports to all 6 finance reports |
| FIN-19 | J-01 | |
| FIN-20 | J-02 | |

**55 scenarios are new in version 2.0**, covering the 16.2.0 boards, the reports
that were never named, guest search, restrictions, walk-ins, credit balances,
language, navigation, audit attribution and refusal wording.

---

## 2. Coverage matrix

### 2.1 Operational frontend — every `/pms` route

| Route | Screen | Covered by |
|---|---|---|
| `/pms` | Dashboard | **C-01, C-02**, C-08, E-05, F-09 |
| `/pms/arrivals` | Arrivals board | **C-03, C-04, C-05, C-06, C-07**, C-08 |
| `/pms/departures` | Departures board | **E-01, E-02**, E-05 |
| `/pms/calendar` | Reservation calendar | **B-02** |
| `/pms/reservations` | Reservation list | **B-06** |
| `/pms/reservations/new` | New reservation | B-03, B-04, B-07, B-08, B-09, C-13 |
| `/pms/reservations/:id` | Reservation detail | B-04, B-05, B-11, **D-26** |
| `/pms/check-in/:reservation` | Check-in | C-09, C-10, C-11, C-12 |
| `/pms/in-house` | In-house board | **D-01**, D-25, F-04 |
| `/pms/folios/:id` | Folio | D-02, D-03, D-04, E-03, G-02, G-05, G-06 |
| `/pms/checkout/:stay` | Checkout | E-02, E-03, E-04, E-06, E-07, E-08, G-01 |
| `/pms/guests` | Guest search | **B-12**, J-02 |
| `/pms/guests/:id` | Guest profile | **B-12**, J-07 |
| `/pms/stays/:id` | Stay detail and in-stay changes | **D-25** |
| `/pms/kitchen` | Room service board | **D-20, D-21, D-22** |
| `/pms/guest-services` | Guest services board | D-16, D-17, D-18, D-19 |
| `/pms/housekeeping` | Housekeeping board | D-05, D-06, D-07, D-08, D-09, D-10 |
| `/pms/maintenance` | Maintenance board | D-11, D-12, D-13, D-14, D-15 |
| `/pms/night-audit` | Night audit | F-01…F-07 |
| `/pms/availability` | Availability search | B-01, D-12, D-14 |
| `/pms/rooms` | Room rack | A-04, C-07, D-06, D-12, D-14 |
| `/pms/forbidden` | Permission refusal | J-02, J-04 |
| `/:pathMatch(.*)*` | Not found | *not covered — see §3.4* |

Bold entries are scenarios written specifically for that screen rather than
passing through it.

### 2.2 Front office API — the 16.2.0 read models

| Endpoint | Covered by |
|---|---|
| `front_office.dashboard` | C-01, C-02, C-08, E-05, F-09 |
| `front_office.arrivals` | C-03…C-08 |
| `front_office.departures` | E-01, E-02, E-05 |
| `front_office.calendar` | B-02 |

### 2.3 Domain modules

| Module | Covered by |
|---|---|
| Property, buildings, floors, zones | A-01, A-02, A-08 |
| Room types and rooms | A-03, A-04 |
| Room status — four dimensions | A-04, C-07, D-06, D-12 |
| Rates, daily rates, policies | A-05, B-03 |
| Inventory restrictions | **B-08** |
| Availability engine | B-01, B-07, D-12, D-14 |
| Reservations and state machine | B-03…B-11 |
| Guests, VIP, blacklist | B-09, B-12, C-05, J-07 |
| Check-in and stays | C-09…C-12 |
| Folio, charges, payments | D-02, D-03, D-04 |
| Housekeeping | D-05…D-10 |
| Maintenance and room blocks | D-11…D-15 |
| Guest services and SLA | D-16…D-19 |
| Room service ordering and delivery | D-20…D-22 |
| Kitchen stores and wastage | D-23, D-24 |
| Room assignment before arrival | **D-26** |
| In-stay changes: move, extend, shorten, notes | **D-25** |
| Checkout and settlement | E-01…E-08 |
| Night audit | F-01…F-08 |
| ERPNext posting and reconciliation | G-01…G-08 |
| Corporate accounts and credit | H-01…H-04 |
| Group reservations | H-05 |
| Channel integration | H-06, H-07 |
| Regulatory export | H-08 |
| Key cards | H-09 |
| Permissions and roles | A-07, D-15, G-06, J-01, J-02, J-03 |
| Property isolation | A-08, J-04 |
| Localisation and RTL | J-05, J-06 |
| Audit trail | J-08 |
| Desk navigation | J-09 |

### 2.4 Reports — all 21

| Report | Covered by |
|---|---|
| Arrivals | I-02 |
| Departures | I-02 |
| In House | I-02 |
| Room Status | I-02 |
| Occupancy and Revenue | **I-01**, G-08 |
| Revenue by Room Type | I-03, G-08 |
| Revenue by Source | I-03 |
| Availability Forecast | I-03, I-06 |
| Cancellations and No Shows | I-03 |
| Housekeeping Productivity | I-04 |
| Maintenance Response Times | I-04 |
| Guest Request SLA | I-04 |
| Rooms Out of Service | I-04 |
| Guest Ledger | I-05 |
| Folio vs Invoice | I-05, G-02 |
| Payment Reconciliation | I-05, G-07 |
| Failed Postings | I-05, G-03 |
| Corporate Credit Exposure | I-05, H-04 |
| Corporate Production | I-05, H-04 |
| Kitchen Consumption and Wastage | I-06 |
| Regulatory Submissions | I-06, H-08 |

**21 of 21 covered.** In version 1.0, 13 of them were never named in a scenario.

### 2.5 Desk dashboard cards — all 8

| Card | Covered by |
|---|---|
| Arrivals Today | I-07 |
| In House | I-07 |
| Rooms Out of Order | I-07 |
| Housekeeping Tasks Pending | I-07 |
| Open Maintenance Tickets | I-07 |
| Failed Postings | I-07 |
| Integration Failures Pending | I-07 |
| Overdue Guest Requests | I-07 |

---

## 3. Implemented and NOT covered by a scenario

This is the list to read before sign-off. Each entry is something the code can
do that no tester will exercise, and why.

### 3.1 Closed in 16.3.0

The two largest gaps in this register have been built and are now covered
scenarios, not gaps.

| Was | Now | Covered by |
|---|---|---|
| Room service had no screen; ordering ran through the API | `/pms/kitchen` — an order board, order taking with no price field, and delivery that charges the folio once | D-20, D-21, D-22 |
| Room assignment, room moves, extend, shorten and stay notes were Desk-only, out of reach of the six roles with no Desk | `/pms/stays/<stay>` for in-stay changes, and an assign-room control on the reservation itself | D-25, D-26 |

The arrivals board's **Assign room** action, which in 16.2.0 opened a screen with
no assign control, now reaches a working one. That defect is closed.

### 3.2 Still implemented on the server with no `/pms` screen

| Capability | Where it works today | Why not covered | Severity if the hotel needs it |
|---|---|---|---|
| **Kitchen requisitions and wastage** | Desk / API | Deliberate: moving stock between stores is a stores job, and both roles that do it hold Desk. Covered as API scenarios by **D-23** and **D-24** | Low |
| **Mark an individual reservation no-show** | Desk / API | Only the night audit's bulk step is covered, by **F-02** | Medium — the desk may need to no-show one booking before the audit runs |
| **Guest duplicate matching and merge** | Desk / API | No `/pms` screen and no scenario. The endpoints exist and are permission-gated | Medium — duplicate guest records accumulate quickly and distort history |
| **Night audit history** | API only | No screen lists previous audits; only the current one is shown | Low — the records are readable in Desk |
| **Folio reconciliation and posting retry screen** | API + Desk reports | `checkout.reconciliation`, `reconcile_folio`, `retry_posting` and `post_folio` have no `/pms` screen. **G-03** covers the retry through Desk | Medium — finance can work in Desk, which they have |
| **Corporate accounts** | Desk | Covered by H-01…H-04 in Desk. Corporate Sales Manager has Desk access, so this is workable by design | Low |
| **Group reservations** | Desk | Covered by H-05 in Desk | Medium — pickup and cutoff release are not automated |
| **Rate plans, daily rates, restrictions** | Desk | Covered by A-05 and B-08 in Desk. Revenue Manager has Desk access | Low |

### 3.3 Implemented but unproven against the real world

| Capability | State | Why not covered |
|---|---|---|
| **Payment gateway (Fatora)** | Adapter written; endpoints and status vocabulary are best-effort | No sandbox available. UAT uses the Manual provider. `payments.initiate`, `sync_status`, `refund` and `webhook` are **not exercised by any scenario**. This must be proved against the live gateway before any real payment is taken. **Critical to close before go-live if card payments are in scope.** |
| **Door lock encoder** | Mock adapter | H-09 issues a key card record; no physical lock is driven. Unproven against this hotel's actual vendor |
| **ID scanner** | Mock adapter | No scenario. Identification is typed by hand in UAT |
| **Regulatory transport** | Export generates; no submission channel | H-08 covers generation and manual filing only |

### 3.4 Deliberately not covered

| Item | Reason |
|---|---|
| The "not found" page | A missing-page screen is not a business workflow |
| `availability.check` endpoint | Subsumed by the availability search that B-01 covers; no separate user-facing behaviour |
| Guest preferences, dietary and accessibility requirements | Stored and readable; **B-12** step 6 asks the tester to record whether they are visible where the desk needs them, rather than asserting a behaviour that has not been designed into a workflow |
| **Food and Beverage Manager** as a distinct role | The role holds write access to menu items, kitchen requisitions, room service orders, wastage and guest requests — the same surface D-20…D-23 exercise as Kitchen Manager. Those scenarios name Kitchen Manager because it is the narrower role; if this hotel staffs an F&B Manager instead, run D-20…D-23 as that role and record it. No separate scenario exists |
| Superseded frontend resources | `reservations.arrivals`, `reservations.departures` and `reservations.calendar` were replaced by the `front_office` endpoints in 16.2.0 and are no longer called by any screen. Dead code, not a user-facing gap — flagged here for the implementation team to remove |
| Backup, restore, deployment | Already validated by the implementation team; the Operations Runbook covers them |

### 3.5 Summary for the sign-off meeting

Two of the three decisions this register carried in version 2.0 have been closed
by building the screens. **One remains, and it is the serious one:**

**The payment gateway is unproven.** `payments.initiate`, `sync_status`, `refund`
and `webhook` are exercised by no scenario, because no sandbox is available.
If cards will be taken through Fatora on day one, that needs its own testing
round against the live gateway before go-live. Nothing in this package covers it.

Smaller items still open, each with a severity in §3.2 and §3.3: guest merge,
individual no-show marking, night-audit history, the reconciliation screen, the
door-lock encoder, the ID scanner and regulatory transport.

## 4. Maintaining this document

When a scenario is added, changed or removed, update §2 in the same commit. A
coverage matrix that has drifted is worse than none, because it is believed.

When a gap in §3 is closed by new work, move it into §2 and say which release
closed it.
