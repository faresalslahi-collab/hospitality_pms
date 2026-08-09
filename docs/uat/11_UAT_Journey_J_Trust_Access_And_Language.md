# Journey J — Trust: access, privacy and language

**Applies to:** Hospitality PMS 16.2.0
**Signed by:** General Manager and Hospitality Administrator
**Surface:** `/pms` and Desk, as each scenario says.

The journey that decides whether the hotel can trust the system with its guests
and its money. Everything here is about boundaries: who can see what, who can do
what, and whether staff who work in Arabic get the same product as staff who work
in English.

**Run this journey last.** It needs data created by every other journey, and its
findings are the ones most likely to block go-live.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journeys A–I run. Test users holding
exactly one role each, as set up in **A-07**.

---

### J-01 · A Read-Only Auditor can read everything and change nothing

| | |
|---|---|
| **Role** | Read-Only Auditor |
| **Surface** | Desk and `/pms` |
| **Prerequisites** | A user holding **only** Read-Only Auditor |
| **Test data** | Records from every journey |
| **Severity if failed** | **Critical** — an audit role that can write is not an audit role |

| # | Step | Expected result |
|---|---|---|
| 1 | Sign in and open a Reservation, a Stay, a Folio, a Night Audit and a Corporate Account in Desk. | All readable. |
| 2 | Try to save a change on each. | Each refused. |
| 3 | Try to create a new record of any hospitality type. | Refused. |
| 4 | Try to delete anything. | Refused. |
| 5 | Try to post a charge or a payment on a folio. | Refused. |
| 6 | Run every report from Journey I. | All run. |
| 7 | Open `/pms` and work through the boards. | Readable. Attempt one state change — a check-in, a status change, a payment — and confirm it is refused. |
| 8 | Check the guest blacklist reason on a blacklisted guest. | **Readable** — the auditor is one of the roles trusted with it. |

**Pass criteria:** Every read succeeds and every write is refused, on both surfaces. **A single successful write is Critical.**

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-02 · A Room Attendant cannot reach guests or money

| | |
|---|---|
| **Role** | Room Attendant |
| **Surface** | `/pms` and Desk |
| **Prerequisites** | A user holding **only** Room Attendant |
| **Test data** | A folio number and a guest name from Journey D |
| **Severity if failed** | **Critical** — guest privacy and financial data exposed to the whole hotel |

| # | Step | Expected result |
|---|---|---|
| 1 | Sign in to `/pms`. | The sidebar shows Front desk, Bookings, Rooms and service — **not** Guests, and not Night Audit. |
| 2 | Confirm **Housekeeping** is present. | It is. This is the attendant's job. |
| 3 | Type `/pms/guests` into the address bar directly. | Refused — a "not permitted" screen, not the guest list. |
| 4 | Type a folio address directly, using the folio number from Journey D. | Refused. |
| 5 | Type `/pms/night-audit` directly. | Refused. |
| 6 | Go to `/desk`. | No Desk — the role has no desk access (A-07). |
| 7 | On the dashboard, look at the **Open work** section. | Housekeeping and Maintenance counts are shown as plain numbers, not links, because this role cannot open those boards. |
| 8 | Open the arrivals board and read a row. | Consider what is visible: guest names, VIP status. Judge whether an attendant seeing arriving guests' names is acceptable to this hotel, and record the answer. |

**Pass criteria:** Every direct address is refused, not merely hidden from the menu. Step 8 is a policy judgement — record it either way.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-03 · Navigation shows each role only what it can use

| | |
|---|---|
| **Role** | Front Office Agent, Night Auditor, Maintenance Technician, Guest Relations Officer, in turn |
| **Surface** | `/pms` |
| **Prerequisites** | One user per role |
| **Test data** | None |
| **Severity if failed** | Medium — a usability failure, not a security one, since J-02 proves the boundary holds |

| # | Step | Expected result |
|---|---|---|
| 1 | Sign in as each role in turn and record which sidebar sections appear. | Fill the table below. |
| 2 | For each role, click every section shown. | Every one opens. **A section shown that leads to a refusal is a defect.** |
| 3 | Check the section headings. | Front desk, Bookings, Rooms and service, Guests, Administration — and a heading with nothing under it is never shown. |

| Role | Sections shown | All open? |
|---|---|---|
| Front Office Agent | | ☐ Yes ☐ No |
| Night Auditor | | ☐ Yes ☐ No |
| Maintenance Technician | | ☐ Yes ☐ No |
| Guest Relations Officer | | ☐ Yes ☐ No |

**Pass criteria:** Every section offered to a role actually works for that role, and no empty group headings are shown.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-04 · One hotel cannot see another hotel

| | |
|---|---|
| **Role** | Front Office Agent restricted to one property |
| **Surface** | `/pms` and Desk |
| **Prerequisites** | **A-08** passed — a second property exists and a user is restricted to the first |
| **Test data** | A reservation number and a folio number belonging to the **second** property |
| **Severity if failed** | **Critical** — a group operator leaks guests and revenue between hotels |
| **Skip if** | Single-property deployment, recorded in A-08 |

| # | Step | Expected result |
|---|---|---|
| 1 | Sign in as the restricted agent. | The property selector shows only the permitted property. |
| 2 | Open the dashboard, arrivals, departures, calendar, room rack and in-house. | All show only the permitted property's data. |
| 3 | Open a reservation belonging to the **other** property by typing its address directly. | Refused. |
| 4 | Open a folio belonging to the other property by address. | Refused. |
| 5 | Search for a guest who has only ever stayed at the other property. | Consider what you can see. Record whether guest records are shared across properties in this deployment and whether that is intended. |
| 6 | Run any report available to this role. | Only the permitted property's rows. |

**Pass criteria:** No screen, address or report exposes the other property's operational data.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-05 · Arabic across the new boards, and the screen mirrors — NEW coverage in 16.2.0

| | |
|---|---|
| **Role** | Front Office Agent — ideally a **native Arabic speaker who works at this desk** |
| **Surface** | `/pms` |
| **Prerequisites** | Journeys C and E run, so the boards have rows |
| **Test data** | Real screens with real rows |
| **Severity if failed** | High — half the staff get a worse product |

| # | Step | Expected result |
|---|---|---|
| 1 | Switch the language to Arabic using the switcher at the bottom of the sidebar. | The interface changes to Arabic and the whole layout mirrors right-to-left. |
| 2 | Open the **dashboard**. | Every tile label, section heading, hint sentence and quick action is in Arabic. No English text remains except data — property names, guest names, room numbers, currency codes. |
| 3 | Open **arrivals**. | Column headings, tile labels, filter options and action links all in Arabic. The table scrolls the correct way. |
| 4 | Open **departures**. | The same. Check the blocker sentences beneath a blocked row — **these come from the server and must also be in Arabic**. |
| 5 | Open the **calendar**. | Controls in Arabic. The **Previous and Next arrows point the correct way** for right-to-left. The grid runs right to left. |
| 6 | Open **folio**, **check-in**, **housekeeping** and **night audit**. | Fully Arabic. |
| 7 | Trigger a refusal — attempt a checkout with a balance. | The refusal message is in Arabic and reads naturally. |
| 8 | Read dates and money throughout. | Formatted for the Arabic locale, not English formatting with Arabic labels around it. |
| 9 | Ask the Arabic-speaking tester the real question. | **Would you rather work in this, or switch to English?** ☐ Arabic is fine ☐ I would switch to English |

**Pass criteria:** No untranslated label anywhere, the layout mirrors correctly including directional arrows, and server refusals arrive in Arabic. **Step 9 is the scenario's real finding** — an Arabic UI that a native speaker would abandon has failed even if every string is present. Record it as **High**.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-06 · The language choice sticks

| | |
|---|---|
| **Role** | Front Office Agent |
| **Surface** | `/pms` |
| **Prerequisites** | J-05 run |
| **Test data** | None |
| **Severity if failed** | Medium — staff re-set their language every shift |

| # | Step | Expected result |
|---|---|---|
| 1 | With Arabic selected, sign out and sign back in. | The interface is still Arabic. |
| 2 | Open a screen you had not visited in Arabic. | Also Arabic. |
| 3 | Switch back to English without reloading the page. | The interface changes immediately, including **filter dropdown options and tile labels** — not just headings. |
| 4 | Reload. | Still English. |
| 5 | Sign in as a different user. | That user's own language, not the previous user's. |

**Pass criteria:** The choice persists per user and takes effect everywhere immediately, including controls, without a reload.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-07 · Guest privacy: identification, blacklist and the reason behind it

| | |
|---|---|
| **Role** | Front Office Agent, Reservation Agent, Guest Relations Officer, Room Attendant, in turn |
| **Surface** | Desk and `/pms` |
| **Prerequisites** | A guest with identification recorded and a blacklisted guest with a reason (Journey B) |
| **Test data** | Both guest records |
| **Severity if failed** | **Critical** — a privacy breach, and in most jurisdictions a legal one |

The design intent, which this scenario checks:

| Data | Who should see it |
|---|---|
| Identification documents | Front office and reservations staff, guest relations, management; finance and audit read-only |
| **That** a guest is blacklisted | Front desk and reservations — they must be able to refuse the booking |
| **Why** a guest is blacklisted | Management and guest relations only — not the front desk |

| # | Step | Expected result |
|---|---|---|
| 1 | As **Front Office Agent**, open the guest with identification. | Identification is visible. |
| 2 | As **Front Office Agent**, open the blacklisted guest. | You can see **that** they are blacklisted. |
| 3 | As **Front Office Agent**, look for the blacklist **reason**. | **Not visible.** If it is, that is Critical. |
| 4 | As **Reservation Agent**, repeat steps 2 and 3. | Same: the flag yes, the reason no. |
| 5 | As **Guest Relations Officer**, open the same guest. | Both the flag and the reason are visible. |
| 6 | As **Room Attendant**, attempt to open any guest record. | Refused entirely. |
| 7 | Trigger the blacklist refusal as an agent (B-09) and read the message. | It says the guest is blacklisted. Confirm the **reason does not appear in the message** — a refusal is a common route for privileged text to leak. |

**Pass criteria:** The three-way split holds on both surfaces, and the refusal message does not leak the reason.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-08 · Sensitive actions leave a name, a time and a reason

| | |
|---|---|
| **Role** | Hospitality Administrator or Read-Only Auditor |
| **Surface** | Desk |
| **Prerequisites** | Journeys B–G run, so the sensitive actions have all happened |
| **Test data** | The records you touched in earlier journeys |
| **Severity if failed** | **Critical** — nothing can be investigated after the fact |

For each action below, find the record and confirm **who**, **when** and **why**
are all recorded.

| # | Action | From | Who? | When? | Reason? |
|---|---|---|---|---|---|
| 1 | Overbooking override at confirmation | B-07 | ☐ | ☐ | ☐ |
| 2 | Reservation cancellation | B-11 | ☐ | ☐ | ☐ |
| 3 | Unready-room check-in override | C-11 | ☐ | ☐ | ☐ |
| 4 | Charge reversal | D-03 / G-05 | ☐ | ☐ | ☐ |
| 5 | Folio adjustment | G-05 | ☐ | ☐ | ☐ |
| 6 | Service recovery discount | D-19 | ☐ | ☐ | ☐ |
| 7 | Room taken out of service | D-12 | ☐ | ☐ | ☐ |
| 8 | Checkout reversal | E-07 | ☐ | ☐ | ☐ |
| 9 | Night audit reopen | F-07 | ☐ | ☐ | ☐ |
| 10 | Corporate credit exception approval | H-03 | ☐ | ☐ | ☐ |

| # | Step | Expected result |
|---|---|---|
| 1 | Work down the table, opening each record. | All three columns tick for every row. |
| 2 | Confirm the reason is the text the operator actually typed. | Not a generic placeholder. |
| 3 | Try to edit a recorded reason after the fact. | Record what happens. |

**Pass criteria:** All ten actions are fully attributable. **Any row missing a reason is Critical** — those are exactly the actions that need explaining months later.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-09 · Staff can find the system in the first place

| | |
|---|---|
| **Role** | Hotel Manager (Desk user), then Front Office Agent (no Desk) |
| **Surface** | Desk and `/pms` |
| **Prerequisites** | App installed and migrated |
| **Test data** | None |
| **Severity if failed** | Medium — staff can be told the URL, but a new starter will not find it |

| # | Step | Expected result |
|---|---|---|
| 1 | As **Hotel Manager**, sign in and look at the Desk apps screen. | A **Hospitality PMS** tile is present, carrying the app logo. |
| 2 | Click it. | The Hospitality PMS navigation opens. |
| 3 | Work through the sidebar: Home, Dashboard, the five workspaces, PMS Console and the sections beneath. | Every link opens something. **No broken link.** |
| 4 | Click **PMS Console**. | `/pms` opens. |
| 5 | Open the Reports section in the sidebar. | The eight linked reports all run. |
| 6 | As a **Front Office Agent** with no Desk access, sign in. | You reach `/pms` directly. Record how — a bookmark, a redirect, or being told the URL — and whether a new starter would manage it unaided. |

**Pass criteria:** The Desk tile and sidebar work with no broken links, and there is a workable route to `/pms` for staff who have no Desk.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### J-10 · Refusals are understandable to the person who hits them

| | |
|---|---|
| **Role** | Front Office Agent — ideally someone who has **not** read this document |
| **Surface** | `/pms` |
| **Prerequisites** | Journeys B–F run |
| **Test data** | None |
| **Severity if failed** | High — correct refusals that nobody understands generate support calls and workarounds |

This scenario tests wording, not behaviour. Every refusal below has already been
proved correct elsewhere. Here the only question is: **would the person who hit
this know what to do next?**

| # | Refusal | From | Understandable? | Knows what to do next? |
|---|---|---|---|---|
| 1 | Confirming an oversold room type | B-07 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 2 | Booking a blacklisted guest | B-09 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 3 | Checking in before the arrival date | C-10 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 4 | Checking in to a room that is not clean | C-11 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 5 | Checking out with a balance | E-03 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 6 | Checking out with a split folio outstanding | E-06 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 7 | An agent reversing a charge | G-06 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 8 | Closing a day with a blocking exception | F-05 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 9 | A restriction closing a date | B-08 | ☐ Yes ☐ No | ☐ Yes ☐ No |
| 10 | Exceeding corporate credit | H-02 | ☐ Yes ☐ No | ☐ Yes ☐ No |

| # | Step | Expected result |
|---|---|---|
| 1 | Reproduce each refusal and read the message aloud to the tester. | They can explain, unprompted, what went wrong. |
| 2 | Ask what they would do next in each case. | They have an answer that does not involve calling IT. |
| 3 | Note any message that is a code, an identifier or a stack trace. | Any such message is an automatic **High**. |

**Pass criteria:** Eight or more of the ten are understood without help. Fewer than eight means the refusals are correct but unusable, which is a **High** finding.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey J sign-off

| | |
|---|---|
| **Scenarios passed** | ____ of 10 |
| **Critical defects open** | ____ |
| **Arabic-speaking tester would work in Arabic** | ☐ Yes ☐ No |
| **Refusals understood** | ____ of 10 |
| **Accepted by** | ____________________ (General Manager) |
| **Accepted by** | ____________________ (Hospitality Administrator) |
| **Date** | ____________ |
