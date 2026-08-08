# Hospitality PMS — Front Office Guide

For reservation agents, front desk agents and front office managers.

Written against the implementation as built, not against the specification.
Where a workflow described in the baseline has no screen in the `/pms`
frontend yet, this guide says so and points you at Desk instead of pretending
a button exists.

---

## 1. Getting around

The front office works in two places:

| Surface | Path | What it is for |
|---|---|---|
| Operational frontend | `/pms` | The screens in this guide: availability, reservations, the room rack, the in-house board |
| Frappe Desk | `/desk` | Everything this guide has to send you to because the frontend does not do it yet |

### Pages that exist today in `/pms`

| Page | Route | What it does |
|---|---|---|
| Dashboard | `/pms` | A landing page showing your session, language and role count. No operational data yet. |
| Availability | `/pms/availability` | Search what can be sold for a date range (section 2). |
| Reservations | `/pms/reservations` | The filtered reservation list (section 3). |
| Reservation | `/pms/reservations/:id` | One reservation: its rooms, rate breakdown, and Confirm / Guarantee / Cancel buttons (sections 3–4). |
| Room Rack | `/pms/rooms` | Every room, its four status dimensions, and a dialog to change one (section 10). |
| In House | `/pms/in-house` | A read-only board of who is currently in the house (section 7). |

### What is not in the frontend yet, and must be done in Desk

Read this list once, because it shapes the rest of the guide:

- **Creating a reservation.** There is no "new reservation" form in `/pms`. A
  reservation is created in Desk, on the **Hotel Reservation** doctype, or
  arrives already created from a channel import.
- **Room assignment.** The frontend has no screen to pick a specific room for
  a reservation line. Assign the room in Desk.
- **Check-in.** There is no check-in screen. Check-in is done in Desk.
- **Room changes, extending or shortening an in-house stay.** The In House
  page is read-only — it lists who is in house but has no actions. These
  operations are done in Desk.
- **The folio.** There is no folio screen. Charges, payments, reversals and
  splits are posted in Desk.
- **Checkout.** There is no checkout screen. Checkout is done in Desk.
- **Guest search and guest profile.** There is no guest screen in `/pms`.
  Guest records, duplicate checks and identification are managed in Desk.
- **Marking a no-show, moving a reservation to Waitlisted or back to
  Tentative.** These transitions exist on the server but are not wired to any
  button in `/pms` or in Desk yet.

Everything the server refuses to let happen (the rules in sections 2–10) holds
regardless of which surface you use to attempt it — the service layer is the
same either way.

---

## 2. Finding a room

**Availability** (`/pms/availability`) answers one question: what can
actually be sold for a date range. It calls the same engine a reservation
confirmation uses, so what you see here is not an estimate.

### What counts against availability

For every night of the stay, a room type's availability is:

```
sellable rooms  −  rooms blocked for that night  −  rooms already sold
```

- **Sellable** rooms are active rooms that are not Under Maintenance, Out of
  Service, Out of Order, Blocked, Not Assignable or Stop Sell. A room that is
  merely dirty still counts as sellable — housekeeping status never removes a
  room from availability, because otherwise the whole house would show as sold
  out every morning before it is cleaned.
- **Blocked** rooms are those covered by an active room block for that night —
  either a specific room or a quantity of a room type held for maintenance,
  a group, or house use.
- **Sold** is the number of rooms already committed to reservations in
  **Confirmed**, **Guaranteed** or **Checked In** status for that night.
  Tentative and Draft reservations do not hold inventory and are not counted.

A stay's nights run from the arrival date up to, but not including, the
departure date. A stay from the 10th to the 12th consumes the nights of the
10th and 11th; the 12th is a departure day, not a night sold.

### Reading the per-night breakdown

Each room type's result shows, per night: **sellable**, **blocked**, **sold**,
and **available**. A stay is only bookable if every one of its nights has at
least the number of rooms requested — one tight night is enough to refuse the
whole stay, even if every other night is wide open. The search screen shows
you which night is the constraint so you are not left guessing.

### Why a room type can show rooms free but still refuse the sale

Two things can make a room type unbookable even when `available` is greater
than zero:

1. **It does not fit the party.** The search checks the requested adults and
   children against the room type's `max_adults`, `max_children` and
   `max_occupancy` (extra beds count towards capacity). If the party does not
   fit, the row is marked "This room type cannot take the requested party
   size" and is not bookable, whatever the room count shows.
2. **A rate restriction closes the sale**, even though physical rooms exist.
   These are checked when you actually try to price or confirm the stay
   (Availability search does not evaluate them), and include:
   - **Stop sell** for the room type on a date.
   - **Closed to arrival** — you cannot start a stay on that date, even
     though the room type is open for guests already in house.
   - **Closed to departure** — the departure date itself is closed.
   - **Minimum or maximum length of stay** — set at the daily rate, the rate
     plan's own row, or a rate plan restriction; the strictest of the three
     applies.
   - **Minimum or maximum advance booking days** on the rate plan.

   Restrictions are checked for every night of the stay, not just the arrival
   night — a stay that spans a closed date is refused even if the arrival
   night itself is open.

---

## 3. Taking a booking

### Statuses and what each means

| Status | Meaning |
|---|---|
| **Draft** | Being put together. No guest or room lines are required yet. Inventory is not held. |
| **Tentative** | A soft hold with intent, but still does not hold inventory. |
| **Confirmed** | Inventory is held for every night of every room line. This is the point of no return for availability. |
| **Guaranteed** | Confirmed, plus a guarantee (a card, a deposit, a company or travel agent guarantee) is on file. |
| **Waitlisted** | Availability or a restriction could not be satisfied when it mattered; parked rather than lost. |
| **Checked In** | Every room line on the reservation has a guest physically in the room. |
| **Checked Out** | Every stay on the reservation has checked out. |
| **Closed** | Fully wrapped up. |
| **Cancelled** | Withdrawn, with a cancellation charge recorded if the policy calls for one. |
| **No Show** | The guest never arrived and the arrival date has passed. |

### Creating a reservation

There is no reservation-creation screen in `/pms` today (see section 1).
Reservations are created in Desk as a **Hotel Reservation**, or arrive already
created from a channel import. A few rules apply regardless of who creates it
or how:

- A new reservation may only be saved as **Draft** or **Tentative**. Nothing
  can be inserted directly as Confirmed — that would let someone hold
  inventory just by typing a status, bypassing the availability lock.
- Once the reservation leaves Draft it must have a guest and at least one
  room line.
- Every room line's dates must fall inside the reservation's own arrival and
  departure dates.
- Each room line must book at least one room, and its room type must belong
  to the reservation's property.
- A blacklisted guest cannot be attached to a live (non-Draft, non-Cancelled)
  reservation.
- The rate is priced and re-priced automatically while the reservation is
  still Draft, Tentative or Waitlisted — this is the "working draft" phase.
  Once it reaches Confirmed, Guaranteed or Checked In, the snapshot is frozen:
  re-running today's rate grid against a live reservation would silently
  change what the guest owes.

### Confirming — the moment inventory is held

Confirming is the single point where the reservation goes from a paper
booking to a hold on real rooms. From the Reservation page (or the
`reservations.confirm` action), Confirm is only offered when the server says
the reservation can reach Confirmed from its current status (Draft or
Tentative).

Behind the button:

1. The reservation is locked, then every room type on it is locked, in a
   fixed order, so two agents cannot both confirm the last room of a type at
   the same instant.
2. Availability is re-checked under that lock for every room line, every
   night. If any night no longer has room, the whole confirm is refused — you
   will see the same "Only N room(s) of type X are available on \<date\>; M
   requested" message the availability search would have shown you.
3. Only once every line clears does the reservation move to Confirmed, and
   `confirmed_on` / `confirmed_by` are stamped.

If the property allows overbooking, a manager or agent may pass an
overbooking allowance with the confirm request; the frontend's Confirm button
does not currently offer this option, so an overbooking confirm has to be
done from Desk or by API.

### Guaranteeing

Guarantee moves a **Confirmed** reservation to **Guaranteed** once you have a
credit card, deposit, company guarantee or travel agent voucher on file. It
requires a guarantee type — you cannot guarantee with "None". The frontend's
Guarantee button currently always submits "Credit Card"; if the actual
guarantee is something else, correct it in Desk.

---

## 4. Changing and cancelling

### What can change after confirmation, and what cannot

Once a reservation is holding inventory (Confirmed, Guaranteed or Checked In)
or has reached a terminal state (Checked Out, Closed, Cancelled, No Show), its
**arrival date, departure date, property and guest are locked**. The server's
refusal is direct: *"\<field\> cannot be changed once a reservation is
\<status\>; cancel and rebook instead."*

This is deliberate, not a missing feature: changing those fields safely means
re-running the availability lock, and the only tool that exists for that today
is confirm itself. There is no "move" or "amend dates" operation yet — the
only correct path is to cancel and create a new booking.

Other fields (special requests, notes, guarantee type, adding a companion, and
so on) can still be edited through Desk while the reservation is in a holding
state; only the fields that availability depends on are frozen.

### Why dates are locked once inventory is held

The lock exists because the moment a reservation is Confirmed, some other
guest may already have been refused a room because this reservation took the
last one. Letting the dates move afterwards without re-running the same
lock-and-check confirm goes through would silently break that promise.

### Cancelling

Cancellation always requires a reason — the server refuses a blank one. What
happens next:

1. The cancellation charge is computed from the reservation's cancellation
   policy, evaluated at the moment you cancel:
   - **No Charge** — nothing is owed.
   - **Fixed Amount** — a flat charge.
   - **Percentage of Stay** — a percentage of the total reservation amount.
   - **Full Stay** — the whole reservation amount.
   - **First Night** — the first night's net rate, taken from the rate
     snapshot the guest was actually quoted, not today's rate grid.
   - If the policy has a **free cancellation window** (a number of hours
     before arrival) and you are cancelling outside that window, the charge is
     waived automatically regardless of the basis above.
2. **Who may waive the charge:** a Front Office Manager, Reservation Manager,
   Hotel Manager, General Manager, Hospitality Administrator or System
   Manager. Waiving is an explicit choice at the point of cancelling — anyone
   without one of these roles who tries to waive a charge is refused with
   *"This action requires one of the following roles: …"*.
3. **Cancelling after arrival has passed** (the reservation's arrival date is
   before the property's current business date) also needs one of those same
   manager roles, whether or not a charge is being waived — cancelling a
   booking whose arrival has already come and gone is treated as an
   exception, not routine housekeeping.

The frontend's Cancel dialog on the Reservation page collects the reason and
submits the cancellation, but does not currently offer the waive-charge
option or show the computed charge before you confirm — check the result
after cancelling, or use Desk if you need to waive a charge up front.

### No-show

Marking a reservation as No Show is restricted to a Night Auditor, Front
Office Manager, Hotel Manager, General Manager, Hospitality Administrator or
System Manager, and is refused if the reservation's arrival date is still in
the future relative to the property's business date — *"Reservation \<name\>
arrives on \<date\>, which is after the business date \<date\>."* A no-show
charge is computed the same way a cancellation charge is, from the
reservation's no-show policy. There is no button for this in `/pms` today; it
is done in Desk (or normally raised automatically by the Night Audit).

---

## 5. Guests

There is no guest search or guest profile screen in `/pms` yet (see section
1). Guest records, searching, duplicate checks and merging are all done in
Desk against the **Hospitality Guest** doctype and its API. This section
describes what happens there so you know what to expect and who can see what.

### Searching and duplicate detection

A guest search matches on identification number, email, mobile number, or
name (with or without date of birth). Each signal carries a different
confidence weight, and a candidate is only surfaced once its total score
reaches the threshold of 30:

| Signal | Weight |
|---|---|
| Same identification number | 60 |
| Same email address | 30 |
| Same mobile number | 30 |
| Same name and date of birth | 25 |
| Same name only | 10 |

A same-name-only match (10 points) never crosses the threshold by itself —
you need at least a second matching signal, or a name-and-DOB match, before
the system calls it a likely duplicate. This is deliberate: two different
guests can easily share a common name, and merging the wrong two records is
worse than leaving a duplicate in place.

### What to do when a guest is flagged

The system never merges automatically — it returns scored candidates and
leaves the decision to a person. If you find a genuine duplicate:

- Merging is restricted to a Hospitality Administrator, System Manager, Hotel
  Manager or Guest Relations Officer, and always requires a reason.
- The merge repoints every reservation, stay and folio reference from the
  source guest onto the target guest. The source record is kept, not
  deleted — its history stays intact for the ten-year retention requirement —
  but it is marked as merged and taken out of operational use.

If a guest is **blacklisted**, any operation that touches that guest
(attaching them to a live reservation, checking them in) is refused with
*"Guest \<name\> is blacklisted: \<reason, or 'no reason recorded'\>"*.

### Who can see identification

Guest data carries three tiers above the ordinary front-desk fields (name,
contact details, preferences), and each tier is gated by role:

| What | Who can see it |
|---|---|
| Identification documents | Front Office Manager, Front Office Agent, Reservation Manager, Guest Relations Officer, Night Auditor, Finance Manager, Accounts User, Hotel Manager, General Manager, Hospitality Administrator, System Manager, Read-Only Auditor |
| That a guest is blacklisted (flag only) | Front Office Manager, Front Office Agent, Reservation Manager, Reservation Agent, Night Auditor, Guest Relations Officer, Hotel Manager, General Manager, Hospitality Administrator, System Manager, Read-Only Auditor |
| Why a guest is blacklisted (the reason) | Guest Relations Officer, Hotel Manager, General Manager, Hospitality Administrator, System Manager, Read-Only Auditor |

Note the gap: a **Reservation Agent** can see that a guest is blacklisted but
not their identification documents; identification is reserved for the roles
that actually check guests in. And the blacklist *flag* is visible more
widely than the blacklist *reason* — the desk needs to know to refuse
service, not the incident detail behind it.

Guest search results shown to the front desk (name, email, mobile,
nationality, VIP status, stay history) never include identification numbers
or blacklist status directly in the list — those are only on the full guest
record, gated as above. A blacklisted guest is also excluded from a name/
email/mobile search for anyone who is not cleared to see the blacklist flag.

---

## 6. Arrivals and check-in

There is no check-in screen in `/pms` (see section 1); check-in is performed
in Desk against the reservation and its room line. The checks below run in
this exact order, and the first one that fails is the one you are shown —
knowing the order tells you what to fix first.

1. **The room line is not already checked in.** Checking in the same line
   twice is refused: *"This room line is already checked in."* Safe to retry
   a failed check-in — it will not create a second stay.
2. **The reservation is Confirmed or Guaranteed.** Any other status —
   including Draft, Tentative or Waitlisted — is refused: *"Reservation
   \<name\> is \<status\> and cannot be checked in."* Confirm (and guarantee,
   if required) it first.
3. **The arrival date is due.** You cannot check in before the property's
   business date reaches the reservation's arrival date: *"Reservation
   \<name\> arrives on \<date\>; the business date is \<date\>."*
4. **The guest is not blacklisted.** Refused with the same blacklist message
   as section 5.
5. **Identification has been captured**, if the property requires ID at
   check-in (`require_id_at_check_in`). Refused with *"This property requires
   guest identification before check-in."* This check can be skipped for a
   specific check-in call (`skip_id_check`), but that is an explicit override
   an operator makes, not a default.
6. **Any required deposit has been received.** If the reservation has a
   `deposit_required` greater than zero and the amount received falls short
   (even by a fraction of a currency unit), you are refused: *"A deposit of
   \<required\> is required; \<received\> has been received."* Take the
   deposit first.
7. **The room is assignable** (see section 10 for what that means) — active,
   not under maintenance, not blocked from sale, not already occupied, and
   physically ready (Clean or Inspected housekeeping status) — unless you use
   the Vacant Dirty override below.

### The Vacant Dirty override

If the only thing wrong with the room is housekeeping status, a manager can
check the guest in anyway:

- **Who can authorise it:** Front Office Manager, Hotel Manager, General
  Manager, Hospitality Administrator or System Manager.
- **A reason is mandatory.** Checking in without one is refused: *"A reason is
  required to check in to a room that is not ready."*
- **The property must permit it.** If the property's
  `allow_vacant_dirty_check_in` setting is off, the override itself is
  refused — *"This property does not permit check-in to a room that is not
  ready."* — regardless of who is asking.
- The override relaxes **housekeeping only**. Maintenance, inventory,
  occupancy and the room's active flag are never overridden this way; a room
  that is Out of Order, Blocked or already Occupied still cannot be assigned,
  manager override or not.
- The override and its reason are recorded on the Stay record, so it is
  always visible afterwards who authorised checking a guest into a room that
  was not ready, and why.

### What check-in does

Once every check above clears: the room is assigned to the reservation line
(re-checking that no other holding reservation already claims it for these
dates), a **Hospitality Stay** record is created, a **Guest Folio** is opened
for it (or the existing one reused, so a retried check-in never produces a
second folio), the room is marked Occupied, and — once every room line on the
reservation has a stay — the reservation itself moves to **Checked In**. A
multi-room reservation does not become Checked In until the whole party has
arrived.

Any deposit already recorded against the reservation is moved onto the new
folio automatically as a Deposit payment, so the guest is not asked to pay it
a second time at the desk.

---

## 7. In house

The **In House** page (`/pms/in-house`) is a read-only board: room, guest,
arrival, departure, occupants and rate, with **In House** / **Due Out** status
badges and summary tiles. It has no actions — room change, extend, shorten and
notes are all done in Desk against the Hospitality Stay record.

### Room change

Only an **In House** or **Due Out** stay can change room; anything else is
refused with *"Only an in-house stay can change room; this stay is
\<status\>."* A reason is mandatory. Both the old and new room are locked
before the check runs, so two simultaneous moves cannot cross over. Moving to
the room the guest is already in is refused outright. The new room must pass
the same assignability check as check-in (with the same Vacant Dirty
override available). When the move completes, the vacated room becomes Vacant
and Dirty, the new room becomes Occupied, and the folio's room reference
follows the guest.

### Extending a stay

Only the added nights are checked against availability — the nights already
in house are the guest's by right and are never re-questioned. The specific
room must also be free for those extra nights (no other holding reservation
already has it). A Due Out stay that is extended reverts to In House.

### Shortening a stay

The new departure must be after arrival, before the current departure, and
not before the property's business date — you cannot shorten a stay into the
past. A reason is mandatory.

---

## 8. The folio

There is no folio screen in `/pms` (see section 1). Charges, payments,
reversals and splits are posted in Desk against the **Hospitality Guest
Folio**. This section describes the rules that apply wherever it is done.

### Posting charges and payments

Every charge and every payment carries an idempotency key. Retrying the exact
same posting — a double-click, a replayed gateway callback, a re-run of the
night audit — returns the original line unchanged instead of charging or
crediting the guest twice.

Charges can only be posted while the folio is in a postable state: **Open**,
**Under Review**, **Disputed**, **Ready for Settlement** or **Partially
Settled**. A **Settled** or **Closed** folio refuses new charges outright —
*"Folio \<name\> is \<status\> and cannot take new charges."* — which is
exactly what stops a late minibar charge landing after the guest has paid and
left; post it before checkout, or reopen the folio (below) if it is already
closed.

Payments are refused only once a folio is **Closed**: *"Folio \<name\> is
closed and cannot take payments."* Discounts are entered as a positive amount
by the operator but stored as a negative charge, so the running balance is
always a plain sum.

### Why a mistake is corrected by reversal, never by editing

A posted charge is never modified or deleted. Correcting one always means:

1. Marking the original as reversed (who reversed it, when, and why).
2. Posting a new, negative compensating line that references the original.

This requires Finance Manager, Accounts User, Hospitality Administrator or
System Manager, and always requires a reason — *"A reason is required to
reverse a charge."* Reversing an already-reversed charge is refused. This is
what keeps the folio reconcilable: an auditor can always see what was
charged, that it was corrected, by whom, and why — nothing simply
disappears or changes in place.

A manual **adjustment** (a fee waived, a goodwill credit) follows the same
audited path: Finance Manager, Front Office Manager, Hotel Manager, General
Manager, Hospitality Administrator or System Manager, and a mandatory reason.

### Splitting company-pay charges

Splitting moves selected charges onto a new folio — it does not copy them, so
a charge exists on exactly one folio and the two together never add up to
more than the guest actually owes. This is how a company-pay/guest-pay
separation works: room and breakfast go to the company's folio, incidentals
stay on the guest's own. Splitting requires the same adjustment roles as
above, and is refused on a folio that is already Settled or Closed.

### Reopening a closed folio

Moving a **Closed** folio back to **Under Review** is a controlled exception —
it reopens something that may already have been reported to ERPNext — and
requires Finance Manager, Hotel Manager, General Manager, Hospitality
Administrator or System Manager, plus a reason.

---

## 9. Checkout

There is no checkout screen in `/pms` (see section 1); checkout is performed
in Desk against the Hospitality Stay. The blockers below are exactly what a
checkout summary reports before you attempt it, so read the summary first.

### Blockers you may see, and how to clear each

| Blocker | What it means | How to clear it |
|---|---|---|
| "The stay is \<status\>." | The stay is not In House or Due Out — it may already be checked out, or not yet checked in. | Nothing to do; checkout does not apply. |
| "The folio is disputed and must be resolved first." | The folio is in the **Disputed** state. | Resolve the dispute and move the folio out of Disputed before checking out. |
| "The folio has an outstanding balance of \<amount\>." | The guest's own folio does not net to zero. | Take payment for the balance, or use the open-balance override below. |
| "Split folio \<name\> still has a balance of \<amount\>." | A folio split off this stay (for example, a company-pay folio) is not settled. | Settle the split folio too — it must clear before the guest can leave, or the balance would walk out with them. |

### The open-balance (city ledger) override

For a corporate account whose balance is transferred to accounts receivable
rather than collected at the desk, checkout can proceed with an outstanding
balance — but only when the *only* blockers are balance blockers (a disputed
folio still stops checkout outright). This requires Front Office Manager,
Finance Manager, Hotel Manager, General Manager, Hospitality Administrator or
System Manager, and a mandatory reason: *"A reason is required to check out
with an open balance."* Letting a guest leave owing money is treated as a
credit decision, not a routine checkout.

### What checkout does, in order

1. **Validates the folio** — nothing is settled while charges are disputed.
2. **Posts the invoice to ERPNext**, so the ledger has the revenue.
3. **Posts the payments**, so the ledger has the money.
4. **Settles and closes the folio** (or, on the open-balance override, leaves
   it open for finance rather than falsely marking it settled).
5. **Closes the stay**, releases the room to **Vacant** and **Dirty**, and
   raises the departure-clean housekeeping task if the property is configured
   to create one automatically.
6. Advances the reservation to **Checked Out**, once every stay on it has
   left.

The financial steps deliberately come before the operational ones. If posting
to ERPNext fails, the guest is still in house and the room is still theirs —
nothing about the stay is lost. Reversing that order would risk selling the
room to the next guest while the previous guest's revenue was never recorded.

### Reversing a checkout

Reversing a checkout requires Front Office Manager, Finance Manager, Hotel
Manager, General Manager, Hospitality Administrator or System Manager, and a
mandatory reason. It puts the stay back to In House and the room back to
Occupied, and — if the folio had reached Settled or Closed — reopens it to
Under Review. Any invoice already submitted to ERPNext is **left standing**;
it is not cancelled by the reversal, because cancelling a submitted invoice is
a finance decision with its own approval, and doing it silently here would
break the ledger the hotel reports from. The reversal leaves a note that
finance must handle any standing invoice.

---

## 10. The room rack

The **Room Rack** (`/pms/rooms`) shows every room in the property, grouped by
room type, with a summary strip and a detail dialog per room.

### The four status dimensions

A room carries four independent dimensions at once. They are deliberately
never collapsed into a single status, because a room genuinely can be
Occupied, Dirty, Operational and Available all at the same time, and a PMS
that only has one status field cannot then answer "which occupied rooms still
need cleaning today."

| Dimension | Values |
|---|---|
| **Occupancy** | Vacant, Reserved, Due In, Occupied, Due Out, House Use |
| **Housekeeping** | Clean, Dirty, In Progress, Inspection Pending, Inspected, DND, Service Refused |
| **Maintenance** | Operational, Required, Under Maintenance, Out of Service, Out of Order |
| **Inventory** | Available, Blocked, Not Assignable, Stop Sell |

Each dimension has its own allowed transitions — the rack's dropdown will let
you pick any value, but the server refuses one that is not reachable from the
room's current value in that dimension: *"Room \<name\> cannot move from
\<current\> to \<target\>."*

### What makes a room unassignable

A room cannot be given to a guest — at check-in, room change, or reservation
room assignment — if any of the following is true, and the rack's red
highlight and "blocking reason" tell you which:

1. **Inactive** — the room is not marked active at all.
2. **Maintenance is Under Maintenance, Out of Service or Out of Order.**
3. **Inventory is Blocked, Not Assignable or Stop Sell.**
4. **Occupancy is already Occupied or House Use.**
5. **Housekeeping is not Clean or Inspected** — unless a manager applies the
   Vacant Dirty override described in section 6, which relaxes this check
   alone and none of the others.

The order above is the order the checks run in, so it is also the order a
manager should read a refusal in: an Out of Order room is never made
assignable by cleaning it, and a Clean room that is already Occupied is not
assignable either.

### Which statuses you can change yourself

Each dimension has its own list of roles, so a Room Attendant can finish
cleaning a room without being handed the ability to take it out of sale:

| Dimension | Who may change it |
|---|---|
| **Occupancy** | Front Office Manager, Front Office Agent, Night Auditor, Hotel Manager, General Manager, Hospitality Administrator, System Manager |
| **Housekeeping** | Room Attendant, Housekeeping Supervisor, Housekeeping Manager, Front Office Manager, Front Office Agent, Hotel Manager, General Manager, Hospitality Administrator, System Manager |
| **Maintenance** | Maintenance Technician, Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator, System Manager |
| **Inventory** | Front Office Manager, Reservation Manager, Revenue Manager, Housekeeping Manager, Maintenance Manager, Hotel Manager, General Manager, Hospitality Administrator, System Manager |

Two maintenance values need more than the dimension role: moving a room to
**Out of Service** or **Out of Order** additionally requires a Maintenance
Manager, Hotel Manager or General Manager (or an administrator role) —
taking sellable inventory out of the house is an accountable decision, not a
routine technician action.

Every change — whoever makes it — is written to the room's status log with
who changed it, when, from what, to what, and the reason given, visible in
the rack's room detail dialog.

---

## 11. When something is refused

The wording below is copied from the service that raises it, so it is what
you will actually see on screen or in the error toast.

| You did this | Message | What it means | What to do |
|---|---|---|---|
| Searched or booked dates the wrong way round | "Departure \<date\> must be after arrival \<date\>." | The departure is not after the arrival. | Fix the dates. |
| Requested more rooms than are left | "Only \<n\> room(s) of type \<type\> are available on \<date\>; \<m\> requested." | One night of the stay does not have enough rooms of that type. | Reduce the room count, shorten the stay to avoid that night, or choose another room type. |
| Booked a room type with no active rooms | "Room type \<type\> has no active rooms in property \<property\>." | The room type is not actually stocked for this property. | Choose a different room type, or ask setup to add rooms. |
| Chose a rate plan that does not apply | "Rate plan \<plan\> does not cover room type \<type\>." | The named plan does not sell this room type. | Choose an applicable plan, or leave the plan blank to let the system pick the standard one. |
| Priced a room type with no plan at all | "No active rate plan covers room type \<type\> on \<date\>." | Nothing is configured to sell this room type on this date. | This is a setup gap — raise it with whoever manages rates. |
| Tried to sell a stopped date | "Room type \<type\> is closed for sale on \<date\>." / "Sale is stopped for \<type\> on \<date\>." | A stop-sell restriction is in force. | The date genuinely cannot be sold; offer different dates. |
| Tried to start a stay on a closed arrival date | "Arrivals are closed on \<date\>." | Closed-to-arrival restriction. | Guests already in house can stay through that date; new arrivals cannot start on it. |
| Tried to end a stay on a closed departure date | "Departures are closed on \<date\>." | Closed-to-departure restriction. | Move the departure date. |
| Booked fewer nights than a minimum-stay rule allows | "A minimum stay of \<n\> night(s) applies on \<date\>." | Min-length-of-stay restriction. | Extend the stay to meet the minimum, or choose a different rate plan. |
| Booked more nights than a maximum-stay rule allows | "A maximum stay of \<n\> night(s) applies on \<date\>." | Max-length-of-stay restriction. | Shorten the stay, or split it across a booking that changes plan. |
| Booked too close to, or too far from, arrival | "This rate plan must be booked at least \<n\> day(s) in advance." / "…cannot be booked more than \<n\> day(s) in advance." | Advance-booking restriction on the rate plan. | Choose a different rate plan, or adjust the booking date. |
| Tried to confirm a reservation with no rooms | "A reservation must have at least one room line before it can be confirmed." | Nothing to hold inventory for. | Add a room line first. |
| Tried to guarantee without a guarantee type | "A guarantee type is required to guarantee a reservation." | Guarantee needs to know what the guarantee actually is. | Pick a guarantee type (card, deposit, company, travel agent, cash). |
| Cancelled without a reason | "A reason is required to cancel a reservation." | Cancellation always needs a stated reason. | Enter a reason. |
| Tried to waive a cancellation charge without the role | "This action requires one of the following roles: …" | Waiving is a manager decision. | Ask a Front Office Manager, Reservation Manager, Hotel Manager, General Manager, Hospitality Administrator or System Manager. |
| Tried to mark a no-show before the arrival date has passed | "Reservation \<name\> arrives on \<date\>, which is after the business date \<date\>." | You cannot no-show a guest on a day that has not ended yet. | Wait for the business date to reach or pass the arrival date. |
| Tried to check in a Draft, Tentative or Waitlisted reservation | "Reservation \<name\> is \<status\> and cannot be checked in." | Only Confirmed or Guaranteed reservations can check in. | Confirm (and guarantee, if required) first. |
| Tried to check in before the business date reaches arrival | "Reservation \<name\> arrives on \<date\>; the business date is \<date\>." | Too early. | Wait for the business date. |
| Tried to check in a room line twice | "This room line is already checked in." | Safe to have retried; nothing further to do. | Look up the existing stay instead. |
| Tried to check in without required identification | "This property requires guest identification before check-in." | The property's ID-at-check-in setting is on and no ID is recorded. | Capture identification, or use the documented skip if the operator is authorised to bypass it. |
| Tried to check in with a deposit still owing | "A deposit of \<required\> is required; \<received\> has been received." | The reservation's required deposit has not been fully paid. | Take the balance of the deposit first. |
| Tried to check in / assign / move to a room that is not ready | "Room \<label\> is \<status\> and is not ready for a guest." | Housekeeping status is not Clean or Inspected. | Wait for the room to be cleaned, or have a manager apply the Vacant Dirty override with a reason. |
| Tried to check in / assign / move to a room that is out of order or blocked | "Room \<label\> is \<status\> and cannot be assigned." / "…is \<status\> and is not available for sale." | Maintenance or inventory status blocks the room outright — never overridable from the front desk. | Choose another room. |
| Tried to assign / move to a room that is already taken | "Room \<label\> is already \<status\>." / "Room \<room\> is already assigned to reservation \<other\> for these dates." | The room is occupied, or already promised to another holding reservation for overlapping dates. | Choose another room. |
| Tried to change room to the room the guest is already in | "The guest is already in room \<room\>." | Nothing to do. | — |
| Changed room, extended, or shortened a stay that is not in house | "Only an in-house stay can change room; this stay is \<status\>." / "Only an in-house stay can be extended; this stay is \<status\>." | Only In House or Due Out stays support these actions. | Check the stay status. |
| Shortened a stay to before arrival, after current departure, or before today's business date | "The departure must be after the arrival date." / "The new departure must be before the current departure." / "A stay cannot be shortened to a date before the business date." | Basic date sanity for a shortened stay. | Pick a valid new departure date. |
| Changed room / shortened stay without a reason | "A reason is required to change room." / "A reason is required to shorten a stay." | Both operations are always reasoned for audit. | Enter a reason. |
| Posted a charge or payment to a settled/closed folio | "Folio \<name\> is \<status\> and cannot take new charges." / "Folio \<name\> is closed and cannot take payments." | The folio is done. | Reopen the folio first (Finance/manager role, with a reason), or post to a new folio. |
| Tried to reverse a charge without the role, or without a reason | "A reason is required to reverse a charge." plus a role check | Reversal is a finance-authorised, always-reasoned action. | Ask Finance Manager, Accounts User, Hospitality Administrator or System Manager. |
| Tried to reverse an already-reversed charge | "Charge \<row\> has already been reversed." | Nothing further to reverse. | Check the folio history for the original reversal. |
| Tried to move a folio to Settled or Closed with money still owing | "Folio \<name\> has an outstanding balance of \<amount\> and cannot be \<status\>." | The balance is not zero. | Take payment, or use the open-balance checkout override. |
| Tried to close a folio with charges never posted to ERPNext | "Folio \<name\> has \<n\> charge(s) that have not reached ERPNext. Post the folio before closing it." | Closing must not strand revenue outside the ledger. | Post the folio (or retry the failed posting) before closing. |
| Tried to split or merge a settled/closed folio | "A \<status\> folio cannot be split." / "Folio \<name\> is \<status\> and cannot be merged." | Nothing further can move once a folio is done. | — |
| Tried checkout with the folio disputed | "This stay cannot be checked out: The folio is disputed and must be resolved first." | Disputed charges block checkout outright, even with the open-balance override. | Resolve the dispute first. |
| Tried checkout with money owing, without the override | "This stay cannot be checked out: The folio has an outstanding balance of \<amount\>." | Balance is not zero and no override was requested. | Take payment, or have a manager authorise the open-balance override with a reason. |
| Tried the open-balance override without a reason, or without the role | "A reason is required to check out with an open balance." plus a role check | Letting a guest leave owing money is a credit decision. | Ask Front Office Manager, Finance Manager, Hotel Manager, General Manager, Hospitality Administrator or System Manager, and give a reason. |
| Tried to reverse a checkout without a reason, or without the role | "A reason is required to reverse a checkout." plus a role check | Reopening settled money needs both front office and finance authority. | Ask Front Office Manager, Finance Manager, Hotel Manager, General Manager, Hospitality Administrator or System Manager. |
| Tried to reverse a checkout on a stay that is not Checked Out | "Stay \<name\> is \<status\>; only a checked out stay can be reversed." | Nothing to reverse. | — |
| Tried to change a room status the transition table does not allow | "Room \<name\> cannot move from \<from\> to \<to\>." | That dimension cannot jump straight there from its current value. | Move it through the intermediate status the transition table expects (see section 10). |
| Tried to change a room status without the dimension role | "This action requires one of the following roles: …" | Each status dimension is gated to specific roles. | Ask someone holding the right role for that dimension (section 10). |
| Attached a blacklisted guest, or tried to check one in | "Guest \<name\> is blacklisted: \<reason, or 'no reason recorded'\>." | The guest record is blacklisted. | This needs a manager decision outside the system — the block is deliberate. |

---

**Related guides:** the Administrator and Setup Guide covers configuring
properties, room types, rate plans and restrictions; the Night Audit, Finance
and Reconciliation Guide covers business date rollover, ERPNext posting and
reconciliation in more depth than section 9 here.
