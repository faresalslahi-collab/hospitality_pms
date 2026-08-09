# Journey H — Corporate, groups and channels

**Applies to:** Hospitality PMS 16.2.0 · **Signed by:** Corporate Sales Manager
**Surface:** Desk throughout, with `/pms` where a step says so.

Business that does not walk in off the street: companies with credit, groups with
blocks, and rooms sold through online channels. Almost none of this has a `/pms`
screen — it is maintained in Desk by people who have Desk. That is by design, and
whether it is acceptable is part of what this journey asks.

Read §4, §5 and §6 of [01_UAT_Plan_and_Sign_Off.md](01_UAT_Plan_and_Sign_Off.md)
first.

**Prerequisites for the whole journey:** Journey A passed.

**Test data to prepare in Desk before you start:**

- One **Corporate Account** with a credit limit small enough that a booking or two will exhaust it, plus a contact and a negotiated rate.
- One **Booking Channel** configured, set to a test or manual mode.
- One **Regulatory Profile** for the property.

---

### H-01 · A corporate booking within the credit limit

| | |
|---|---|
| **Role** | Corporate Sales Manager, then Reservation Agent |
| **Surface** | Desk → Reservations → Corporate Account; `/pms/reservations/new` |
| **Prerequisites** | A corporate account with a credit limit and available credit |
| **Test data** | The account's limit, and its current used credit |
| **Severity if failed** | High — corporate business cannot be taken |

| # | Step | Expected result |
|---|---|---|
| 1 | Open the corporate account in Desk and note the credit limit and credit used. | Recorded. |
| 2 | Create a reservation against that account for an amount **well within** the remaining credit, and confirm it. | Confirms normally. |
| 3 | Re-open the account. | Credit used has risen by the reservation's amount. |
| 4 | Check the credit log on the account. | An entry records this booking's consumption, with its reservation reference. |
| 5 | Cancel that reservation. | Credit used falls back. |

**Pass criteria:** Confirming consumes credit, cancelling releases it, and both movements are logged.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-02 · Exceeding the credit limit is refused, and the account is flagged

| | |
|---|---|
| **Role** | Reservation Agent |
| **Surface** | `/pms/reservations/new` and Desk |
| **Prerequisites** | H-01 passed. Enough bookings to bring the account near its limit. |
| **Test data** | A booking that would push it over |
| **Severity if failed** | **Critical** — the hotel extends credit it never agreed to |

| # | Step | Expected result |
|---|---|---|
| 1 | Book against the account until the remaining credit is smaller than one more booking. | Each confirms while there is credit. |
| 2 | Attempt one more booking that exceeds the limit. | **Refused**, with a message about the credit limit, naming the shortfall. |
| 3 | Re-open the account. | Its status reads **Exception Required** — the request was neither silently allowed nor simply thrown away. |
| 4 | Check that the refused reservation did not consume credit. | Credit used is unchanged from before the attempt. |
| 5 | Check the credit log. | The refusal is recorded. |

**Pass criteria:** The booking is refused, no credit is consumed, and the account is flagged for a human to decide.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-03 · Finance decides the exception, not sales

| | |
|---|---|
| **Role** | Corporate Sales Manager, then Finance Manager |
| **Surface** | Desk |
| **Prerequisites** | The account left at Exception Required by H-02 |
| **Test data** | A reason |
| **Severity if failed** | **Critical** — sales could grant itself credit |

| # | Step | Expected result |
|---|---|---|
| 1 | As **Corporate Sales Manager**, try to clear the exception or raise the limit. | Refused, naming the roles required. |
| 2 | As **Finance Manager**, set the credit status back to normal with a reason. | Succeeds. |
| 3 | Check the credit log. | The approval is recorded with who, when and why. |
| 4 | Re-attempt the booking from H-02. | Now permitted, if the limit was raised; still refused if the limit was not. |

**Pass criteria:** Only finance can release the exception, and the decision is attributable.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-04 · Corporate exposure and production are visible to management

| | |
|---|---|
| **Role** | Corporate Sales Manager or Finance Manager |
| **Surface** | Desk → Reports |
| **Prerequisites** | H-01 to H-03 run, so the account has history |
| **Test data** | The account name |
| **Severity if failed** | Medium — the data exists; the reporting view is what is missing |

| # | Step | Expected result |
|---|---|---|
| 1 | Run **Corporate Credit Exposure**. | The account appears with its limit, used credit and remaining credit. |
| 2 | Compare to the account record. | The figures agree. |
| 3 | Run **Corporate Production** for the account over your test period. | The bookings made in H-01 and H-02 appear, with room nights and revenue. |
| 4 | Check a cancelled booking's treatment. | Cancelled business is not counted as production. |

**Pass criteria:** Both reports agree with the underlying records and treat cancellations correctly.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-05 · A group block and its rooming list

| | |
|---|---|
| **Role** | Reservation Manager |
| **Surface** | Desk → Reservations → Group Reservation |
| **Prerequisites** | Room types with availability across a date range |
| **Test data** | A group of several rooms over two nights, and a handful of names |
| **Severity if failed** | High — group business cannot be handled |

| # | Step | Expected result |
|---|---|---|
| 1 | Create a **Group Reservation** with block lines for a room type, quantity and dates. | Saves. |
| 2 | Check availability for those dates. | Record whether the block has reduced it, and by how much. |
| 3 | Add rooming list entries with guest names. | They save against the group. |
| 4 | Convert or link a rooming list entry to an individual reservation. | Record what the system does and how much manual work it takes. |
| 5 | Judge the workflow. | **Answer here:** is this workable for the group business this hotel actually takes? ☐ Yes ☐ No |

**Pass criteria:** A block can be held and a rooming list captured. **Known limitation:** pickup and cutoff release are not automated — see the plan's §7. Step 5 is the finding; if the answer is No, raise one High defect against H-05.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-06 · A channel booking becomes a real reservation

| | |
|---|---|
| **Role** | Hospitality Administrator with Reservation Manager |
| **Surface** | Desk → Integrations |
| **Prerequisites** | A configured Booking Channel and room type mappings |
| **Test data** | A test channel message, supplied by the implementation team |
| **Severity if failed** | **Critical** if bookings are lost or corrupted; High if only awkward |

| # | Step | Expected result |
|---|---|---|
| 1 | Submit a test channel booking. | A **Channel Reservation** record is created holding the raw message. |
| 2 | Inspect it before it is mapped. | The raw payload is stored intact and keyed. |
| 3 | Let it map to a reservation. | A Reservation is created with the right guest, dates, room type and rate. |
| 4 | Check the reservation's source and external reference. | Both record where it came from. |
| 5 | Check availability. | Reduced by the channel booking. |
| 6 | Open the arrivals board for its arrival date. | The channel booking appears alongside direct bookings, indistinguishable in the day's work. |

**Pass criteria:** A channel message becomes a working reservation that behaves exactly like a direct one, with its origin recorded.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-07 · The same channel booking twice does not become two bookings

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Integrations |
| **Prerequisites** | H-06 passed |
| **Test data** | The **same** test message, resubmitted unchanged |
| **Severity if failed** | **Critical** — the hotel double-books its own inventory from a retry |

| # | Step | Expected result |
|---|---|---|
| 1 | Note the reservation created in H-06 and the current availability. | Recorded. |
| 2 | Submit the **identical** channel message again. | Accepted without error. |
| 3 | Check the reservation list. | Still **one** reservation for that external reference — not two. |
| 4 | Check availability. | Unchanged by the resubmission. |
| 5 | Check the channel sync log. | The duplicate is recorded as a duplicate rather than silently discarded. |
| 6 | Submit a **malformed** message. | It is stored and flagged for attention. It does not corrupt any reservation, and it does not disappear. |

**Pass criteria:** A repeat message creates nothing new and consumes no inventory; a malformed message is quarantined rather than lost or destructive.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-08 · A regulatory export is produced and marked submitted

| | |
|---|---|
| **Role** | Hospitality Administrator |
| **Surface** | Desk → Integrations → Regulatory Export |
| **Prerequisites** | A regulatory profile for the property; guests checked in during Journey C |
| **Test data** | A date range covering your check-ins |
| **Severity if failed** | High — a legal obligation cannot be met |

| # | Step | Expected result |
|---|---|---|
| 1 | Generate a regulatory export for the period. | A record is created containing the guests in house. |
| 2 | Inspect the content. | The fields the authority requires are present and correctly populated. |
| 3 | Check a guest's identification data is included as required. | It is. |
| 4 | Mark it submitted. | Status changes and the timestamp is recorded. |
| 5 | Run the **Regulatory Submissions** report. | The export appears with its status. |

**Pass criteria:** A complete, correct export is produced and its submission is recorded.

**Known limitation:** no transport to the authority is wired — the file is for
manual filing. Confirm that matches this jurisdiction's process; if the authority
requires automated submission, that is a **High** gap, recorded here.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

### H-09 · A key card is issued for a stay

| | |
|---|---|
| **Role** | Front Office Agent with Hospitality Administrator |
| **Surface** | Desk → Integrations → Key Card |
| **Prerequisites** | An in-house stay from Journey C |
| **Test data** | None |
| **Severity if failed** | Medium — guests can be let in manually while a vendor is chosen |

| # | Step | Expected result |
|---|---|---|
| 1 | Issue a key card for the in-house stay. | A record is created linked to the stay, the room and the guest, with a validity window matching the stay. |
| 2 | Check the validity dates. | They match the stay's arrival and departure. |
| 3 | Attempt to issue a card for a stay that has checked out. | Refused, or the card is not valid. |

**Pass criteria:** Cards are issued against real stays with a correct validity window.

**Known limitation:** the door-lock adapter is a mock — no physical encoder is
driven. Confirm the hotel accepts that this is unproven against its actual lock
vendor before go-live.

| Result | Severity observed | Tester | Date |
|---|---|---|---|
| ☐ Pass ☐ Fail | ☐ Critical ☐ High ☐ Medium ☐ Low | | |

**Comments:**

---

## Journey H sign-off

| | |
|---|---|
| **Scenarios passed** | ____ of 9 |
| **Critical/High defects open** | ____ |
| **Is Desk-only corporate and group working acceptable?** | ☐ Yes ☐ No |
| **Accepted by** | ____________________ (Corporate Sales Manager) |
| **Date** | ____________ |
