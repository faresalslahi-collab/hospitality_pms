# Hospitality PMS — Administrator and setup guide

**Applies to:** Hospitality PMS 16.1.0 (branch `version-16`)

This guide is for the person configuring Hospitality PMS for a property: setting up
ERPNext prerequisites, installing the app, building the physical and commercial
structure of the hotel, and preparing the system for go-live. It assumes you can
already operate Frappe Desk and have (or can obtain) System Manager access on the
site.

Two surfaces are referred to throughout:

- **Desk** — the standard Frappe/ERPNext administration interface, at `/app`.
- **`/pms`** — the operational Vue frontend used by front office, housekeeping,
  maintenance and kitchen staff for day-to-day work.

Configuration, master data, approvals, ERP functions and standard reporting are
all done in Desk. `/pms` is for running the floor, not for setting the property up.

---

## 1. Before you start

Hospitality PMS does not replace ERPNext's financial and enterprise setup — it
sits on top of it. The following must exist in ERPNext **before** you create a
Property, or property setup will fail validation or, worse, save
with gaps that surface later as posting errors.

| ERPNext master | Why it is needed |
|---|---|
| **Company** | Every Property links to exactly one Company, and every Posting Profile links to exactly one Company. All accounting for the property is booked under this Company. |
| **Chart of Accounts / Account** | The property's Default Receivable Account, Room Revenue Account and Deposit Liability Account, the posting profile's income/receivable/deposit accounts, each Property Fee's Income Account, and each Payment Provider's Payment Account are all Account links. They must exist in the Company's chart before you can save these forms. |
| **Cost Center** | The property's Cost Center and the posting profile's Default Cost Center attribute room and folio revenue to the right cost centre for P&L reporting. |
| **Warehouse** | The property's Warehouses table maps each stock purpose (General Store, Kitchen Store, Minibar, Housekeeping Store, Laundry, Maintenance Store) to an ERPNext Warehouse. Minibar consumption, kitchen requisitions and housekeeping/laundry stock all post against these. Without a mapped warehouse for a purpose, the service refuses the transaction rather than guessing. |
| **Item Group** | Required by ERPNext before you can create the Items you will map in the Posting Profile's Charge Item Mapping (Room Charge, Minibar, Laundry, and so on) and any stock items used for kitchen or minibar. |
| **Customer Group** and **Territory** | When a guest folio needs to raise its first financial document, the system creates an ERPNext Customer for the guest automatically. It uses the Customer Group and Territory set in Selling Settings if present, otherwise the first non-group Customer Group and Territory it finds. If neither exists anywhere in the system, guest-to-Customer creation fails outright. Set Selling Settings defaults explicitly rather than relying on "whichever one exists". |
| **Mode of Payment** | Each Payment Provider (Fatora, Stripe, or a manual/offline provider) links to a Mode of Payment for how its receipts post in ERPNext. |
| **Sales Taxes and Charges Template** | Used as the property's Default Sales Taxes and Charges Template and the posting profile's Default Tax Template, and optionally per charge-type mapping row. |
| **Price List** | Used as the property's Default Selling Price List. |

Have all of these ready — including the actual account numbers, cost centre and
warehouse names you intend to use — before opening the Property form.
Retrofitting them later means correcting every record that already used the wrong
one.

---

## 2. Installing the app

Hospitality PMS runs on Frappe Framework v16 and ERPNext v16, Python 3.11+, and
requires **Node 24** for its frontend toolchain — Frappe v16 will not build with
an older Node. Check `bench/.nvmrc` if you are unsure which Node the bench
expects, and switch to it (`nvm use`) before building the frontend.

Backend installation, from the bench directory:

```bash
cd frappe-bench
bench get-app hospitality_pms <repo-url>
bench --site <site> install-app hospitality_pms
bench --site <site> migrate
```

Frontend build (Node 24 required):

```bash
cd apps/hospitality_pms/frontend
yarn install
yarn build            # writes to hospitality_pms/public/frontend
```

`yarn dev` starts a Vite dev server proxied to the Frappe site instead of the
production build — use this only for development, not on a live property.

Once installed and migrated, `/pms` on the site serves the operational
frontend and Desk (`/app`) carries configuration and administration as normal.

Do not run `bench migrate` or touch the database as part of following this
guide beyond the installation step above — all configuration from here on is
done by filling in Desk forms.

---

## 3. Setting up your property

Create the record at **Desk → Property → New**. The form is
organised into sections; fields are listed below in the order the form
presents them.

### Identity

| Field | Notes |
|---|---|
| Property Code | Required, unique. This becomes the document name — choose it deliberately, it is hard to rename later. |
| Property Name | Required. |
| Property Type | Hotel, Resort, Serviced Apartment, Hostel or Other. Defaults to Hotel. |
| Active | Ticked by default. Untick to retire a property without deleting it. |
| Star Rating | Optional, 1–5. |
| Total Rooms | Read-only — maintained automatically as you build room inventory. Do not expect to set this by hand. |

### ERPNext mapping

| Field | Notes |
|---|---|
| Company | Required. The ERPNext Company this property's finances belong to. |
| Cost Center | The cost centre room and folio revenue is attributed to. |
| Currency | Required. Every rate, rate plan and daily rate on this property inherits this currency. |
| Abbreviation | Read-only, fetched from the Company's abbreviation. |

### Location and locale

| Field | Notes |
|---|---|
| Country | Required. |
| Time Zone | Required (autocomplete). |
| Address | Optional link to an ERPNext Address. |
| Phone / Email / Website | Optional contact details. |

### Languages

| Field | Notes |
|---|---|
| Default Language | Required, defaults to `en`. |
| Supported Languages | A table of additional languages (Property Language: Language, Default, Guest Communication) for guest-facing communication. |

### Operations

| Field | Notes |
|---|---|
| **Business Date** | Required. See "The business date", below. |
| Check-In Time | Defaults to 14:00. |
| Check-Out Time | Defaults to 12:00. |
| Overbooking Limit (Rooms) | Rooms sellable beyond physical inventory. Zero disables overbooking outright for this property. |
| Allow Check-In to Vacant Dirty | When ticked, a Front Office Manager may check a guest into a room that has not yet been cleaned, with a recorded reason. Leave unticked unless this is a deliberate operating policy. |
| Require Guest ID at Check-In | Ticked by default. |

**The business date.** The business date is the property's operating day — not
today's calendar date. A property that has not yet run its Night Audit is
still operating on yesterday's business date, and every charge, folio posting
and report for "today" uses this date, not the server clock. The field is
required on the form, but **only the Night Audit service may advance it**: the
property controller actively rejects any other attempt to change
`business_date`, including a direct edit in Desk. If you need to correct the
business date outside of a normal audit run, that is a Night Audit reopen, not
a field edit — do not try to fix it by editing the property record, it will be
refused.

### Accounting

| Field | Notes | Permission level |
|---|---|---|
| Default Receivable Account | Where guest balances are booked. | Permlevel 1 |
| Room Revenue Account | Where room charges post. | Permlevel 1 |
| Deposit Liability Account | Where guest deposits are held until applied or refunded. | Permlevel 1 |
| Default Sales Taxes and Charges Template | | Permlevel 1 |
| Default Selling Price List | | Permlevel 0 |
| Currency Precision | Defaults to 2. | Permlevel 0 |

**These four permlevel-1 fields are the single most consequential setting on
this form.** They are read-only to everyone except Finance Manager, Hospitality
Administrator and System Manager (General Manager, Hotel Manager, Accounts
User and Read-Only Auditor may only *see* them). A wrong account here does not
fail loudly — it **misdirects every future posting**: room charges land in the
wrong revenue account, guest balances reconcile against the wrong receivable
account, and deposits sit in the wrong liability account, silently, until
someone in finance notices the ledger does not add up. Set these once, get
them checked by whoever owns the chart of accounts, and change them only with
the same care you would give a live chart-of-accounts change.

### Fees and charges

A table of **Property Fee** rows — hospitality-specific charges
such as service charge, municipality fee, tourism fee or city tax. Statutory
VAT stays in the ERPNext tax template, not here.

| Field | Notes |
|---|---|
| Fee Type | Service Charge, Municipality Fee, Tourism Fee, City Tax or Other. |
| Charge Basis | Percentage of Room Charge, Percentage of All Charges, Fixed per Night, Fixed per Stay, or Fixed per Person per Night. |
| Rate | The percentage or fixed amount, to 4 decimal places. |
| Income Account | Where this fee posts. |
| Active | |
| Valid From / Valid Upto | Optional date window; leave blank for always-on. |

### Warehouses

A table of **Property Warehouse** rows mapping a stock purpose
(General Store, Kitchen Store, Minibar, Housekeeping Store, Laundry,
Maintenance Store) to an ERPNext Warehouse, with one row per purpose marked
Default for Purpose. Map every purpose you intend to use operationally —
minibar posting, for example, will refuse to proceed if no warehouse is
mapped for Minibar.

### Policies

A free-text **Operating Policies** field (rich text) for house rules and
policy notes that do not belong in a structured field elsewhere.

---

## 4. Physical structure

Build the physical hierarchy before creating rooms. All four doctypes are
property-scoped and are administered under **Hospitality Administrator** /
**System Manager** only (every other role, including General Manager and
Hotel Manager, has read-only access to these four).

**Building** — a physical building on the property.

| Field | Notes |
|---|---|
| Building Code | Required, unique — becomes the document name. |
| Building Name | Required. |
| Property | Required. |
| Active | |
| Address | Optional link to an ERPNext Address. |
| Description | |

**Wing** — a wing within a building, for wayfinding and reporting.

| Field | Notes |
|---|---|
| Wing Code | Required, unique. |
| Wing Name | Required. |
| Property | Required. |
| Building | Required. |
| Active | |

**Floor** — a floor within a building, optionally within a wing.

| Field | Notes |
|---|---|
| Floor Code | Required, unique. |
| Floor Name | Required. |
| Property | Required. |
| Building | Required. |
| Wing | Optional — leave blank if the building has no wings. |
| Floor Level | Required. Use negative numbers for basement levels. |
| Active | |
| Smoking Floor / Executive Floor / Has Elevator Access | Flags used by room search and wayfinding. |

**Zone** — a cross-building grouping of rooms used to assign
housekeeping, maintenance, service or security responsibility. A zone is
**not** tied to a building — it exists specifically to group rooms that share
an operational responsibility regardless of where they physically sit.

| Field | Notes |
|---|---|
| Zone Code | Required, unique. |
| Zone Name | Required. |
| Property | Required. |
| Zone Purpose | Required: Housekeeping, Maintenance, Service, Security or Other. |
| Active | |
| Description | |

Relationship: a **Hotel Room** (section 6) links to a Building, a Wing
(optional), a Floor and a Zone independently — a room's floor is not derived
from its zone, and its zone is not derived from its building. Set all four
that apply to the room directly.

---

## 5. Departments and shifts

**Property Department** — an operational department within the property.
Writable by General Manager, Hotel Manager, Hospitality Administrator and
System Manager; everyone else operational is read-only.

| Field | Notes |
|---|---|
| Department Code | Required, unique. |
| Department Name | Required. |
| Property | Required. |
| Active | |
| Department Type | Required: Front Office, Housekeeping, Maintenance, Food and Beverage, Kitchen, Finance, Sales and Marketing, Security, Human Resources, Management or Other. |
| Parent Department | Optional, if this department reports into a larger division. |
| Manager | A User. |
| ERPNext Department | Optional link to the ERPNext Department, so HR data ties in without duplication. |

**Property Shift** — a recurring duty shift, for staff scheduling and
shift-scoped permissions. Same writer roles as Department.

| Field | Notes |
|---|---|
| Shift Code | Required, unique. |
| Shift Name | Required. |
| Property | Required. |
| Active | |
| Department | Optional link to Property Department. |
| Start Time / End Time | Required, default 07:00–15:00. |
| Crosses Midnight | Tick for a night shift that ends the following day. |
| Days Run | A table of individual weekdays (Property Shift Day) this shift runs on. |

---

## 6. Rooms

Configure **Room Type** first, then **Hotel Room**. Room Type write access is
Revenue Manager, General Manager, Hotel Manager, Hospitality Administrator and
System Manager — room configuration is treated as commercial, not purely
operational.

### Room Type

| Field | Notes |
|---|---|
| Room Type Code | Required, unique. |
| Room Type Name | Required. |
| Property | Required. |
| Active | |
| Display Order | Controls sort order on room racks and rate grids. |
| Base Occupancy / Max Occupancy / Max Adults | Required, default 2. |
| Max Children / Max Extra Beds | Optional. |
| Bed Configuration | Free text, e.g. "1 King" or "2 Twin". |
| Room Size (sqm) | |
| Smoking / Accessible / Allows Connecting Rooms | Flags. |
| Currency | Read-only, fetched from the property. |
| Base Rate / Extra Adult Charge / Extra Child Charge / Extra Bed Charge | **Fallback defaults only**, used where no Rate Plan applies. Once rate plans exist (section 7), they are the authoritative source of sellable rates — do not expect a change here to move a live rack rate. |
| Amenities | A table (Room Type Amenity: Amenity, Quantity, Notes) of what comes with the room type. |
| Description | |

### Hotel Room

Write access for Hotel Room is Front Office Manager, Housekeeping Manager,
Maintenance Manager, General Manager, Hotel Manager, Hospitality Administrator
and System Manager. Note carefully what that write access covers.

| Field | Notes |
|---|---|
| Room Code | Required, unique — typically `PROPERTY-ROOMNUMBER`. |
| Room Number | Required. |
| Property | Required. |
| Room Type | Required. |
| Active | |
| Building / Wing / Floor / Zone | Location links, set independently (section 4). |
| Occupancy Status, Housekeeping Status, Maintenance Status, Inventory Status | **Read-only on this form.** See below. |
| Smoking / Accessible / Has Balcony / View Type | Attributes. |
| Features | A table (Room Feature: Feature, Notes) for room-specific features such as "Sea View" or "Corner Room". |
| Housekeeping Credits | Cleaning effort units, used for workload balancing. |
| Last Cleaned On | Read-only, set by housekeeping completion. |
| Notes | |
| Connecting Rooms | A table of other rooms this one connects with — only meaningful when the room's Room Type allows connecting rooms. |

### The four status dimensions

Every Hotel Room carries **four independent status dimensions**. They are
independent by design: a room can be Occupied, Dirty, Operational and
Available all at the same time, and collapsing them into a single status is
exactly how a PMS ends up unable to answer "which occupied rooms still need
cleaning today". The exact values of each dimension are:

| Dimension | Values |
|---|---|
| Occupancy Status | Vacant, Reserved, Occupied, Due In, Due Out, House Use |
| Housekeeping Status | Clean, Dirty, In Progress, Inspection Pending, Inspected, DND, Service Refused |
| Maintenance Status | Operational, Required, Under Maintenance, Out of Service, Out of Order |
| Inventory Status | Available, Blocked, Not Assignable, Stop Sell |

**Staff never edit these four fields directly** — all four are read-only on
the Hotel Room form itself, whatever a user's write access to the record
otherwise is. They change only through operational actions that call the
room status service: check-in and checkout move Occupancy; a housekeeping
task or inspection moves Housekeeping; a maintenance ticket moves
Maintenance; a stop-sell or block action moves Inventory. Every transition is
validated against an explicit table of allowed moves, is locked so two
concurrent operations cannot race, and is written to the **Hospitality Room
Status Log** with who changed it, when, and why. If Desk shows you these
fields as read-only, that is not a bug to work around — use the Change
Status action from the relevant operational screen instead, so the transition
is recorded.

Two points worth knowing when something looks "stuck":

- **Out of Order** and **Out of Service** are elevated maintenance states —
  only a Maintenance Manager, Hotel Manager or General Manager (plus
  Hospitality Administrator/System Manager) may set them, regardless of who
  otherwise has the Maintenance role.
- A room is assignable to a guest only when it is **active**, its maintenance
  status is not one of Under Maintenance / Out of Service / Out of Order, its
  inventory status is not one of Blocked / Not Assignable / Stop Sell, its
  occupancy status is not Occupied or House Use, and its housekeeping status
  is Clean or Inspected — unless the property's "Allow Check-In to Vacant
  Dirty" setting is enabled and a Front Office Manager deliberately overrides
  it with a reason.

---

## 7. Rates

Configure **Rate Plan**, its **Rate Policy** links,
**Room Inventory Restriction** rows, and the **Hospitality Daily
Rate** grid. Rate plan and policy write access is Revenue Manager, General
Manager, Hotel Manager, Hospitality Administrator and System Manager (Rate
Policy also allows Finance Manager to write).

### Rate Plan

| Field | Notes |
|---|---|
| Rate Plan Code | Required, unique. |
| Rate Plan Name | Required. |
| Property | Required. |
| Active | |
| Display Order | Sort order on booking screens and rate grids. |
| Rate Type | Required — see the 13 values below. |
| Valid From | Required. |
| Valid Upto | Leave blank for an open-ended plan. |
| Currency | Read-only, fetched from the property. |
| Refundable | Default ticked. |
| Includes Breakfast | |
| Includes Taxes | **If ticked, the rate on this plan and on every Daily Rate row under it is the gross, tax-inclusive figure — it is not stored net of tax.** The charge service extracts the tax portion at posting time. Do not enter a net rate here expecting tax to be added on top; that will overcharge the guest. |
| Market Segment / Booking Source | Free text, for reporting. |
| Room Types | A table (Rate Plan Room Type) of the per-room-type rate this plan sells at — see below. |
| Restrictions | A table (Rate Restriction) of stay-shape rules — see below. |
| Cancellation Policy / No Show Policy / Deposit Policy | Links to Rate Policy. |
| Terms | Free text. |

**The 13 rate types** (Select field `rate_type`): Standard, Corporate, Travel
Agent, Group, Government, Promotional, Long Stay, Weekend, Seasonal, Event,
Package, Complimentary, House Use. Complimentary and House Use are always
sold at zero regardless of any rate configured underneath them — they never
fall back to a positive rate.

**Room Types row** (Rate Plan Room Type): Room Type, Base Rate,
Single Occupancy Rate, Extra Adult Charge, Extra Child Charge, Extra Bed
Charge, Active. One row per room type this plan covers — a plan with no row
for a room type does not sell that room type at all.

**Restrictions row** (Rate Restriction): Room Type (blank = every
room type on the plan), Min/Max Length of Stay, Closed to Arrival, Closed to
Departure, Min/Max Advance Days, Applies From/Upto, Days of Week
(comma-separated, e.g. "Fri,Sat"; blank = every day).

### Rate Policy

Reusable cancellation, no-show, deposit or guarantee terms, referenced by one
or more rate plans instead of being retyped on each.

| Field | Notes |
|---|---|
| Policy Code | Required, unique. |
| Policy Name | Required. |
| Property | Required. |
| Policy Type | Cancellation, No Show, Deposit or Guarantee. |
| Active | |
| Charge Basis | No Charge, First Night, Percentage of Stay, Fixed Amount or Full Stay. |
| Charge Value | A percentage (Percentage of Stay) or an amount (Fixed Amount); unused for the other bases. |
| Free Cancellation Hours | Hours before arrival up to which cancellation is free. |
| Deposit Percentage / Deposit Fixed Amount / Deposit Due Days | |
| Description | |

### Room Inventory Restriction

Property-level stop-sell or stay-shape restrictions, independent of any rate
plan. One row per property/room-type/date.

| Field | Notes |
|---|---|
| Property | Required. |
| Room Type | Blank applies to every room type on the property. |
| Restriction Date | Required. |
| Stop Sell / Closed to Arrival / Closed to Departure | |
| Min Length of Stay | |
| Rooms to Sell | Cap on rooms sellable, independent of any plan-level cap. |
| Reason | |

### Daily Rate grid

The date-level rate and restriction grid that revenue management edits
directly — one row per property, rate plan, room type and date.

| Field | Notes |
|---|---|
| Property, Rate Plan, Room Type, Rate Date | Together unique — enforced by the controller, since Frappe cannot express a multi-column unique key in the DocType JSON directly. |
| Rate | Required. |
| Extra Adult Charge / Extra Child Charge | |
| Min/Max Length of Stay, Closed, Closed to Arrival, Closed to Departure, Stop Sell, Rooms to Sell | Date-level overrides. |

### Rate resolution order

For a given night, the system prices a room type in this order, most
specific first:

1. **Daily Rate** for the exact property, rate plan, room type
   and date, if one exists.
2. Failing that, the **rate plan's own room-type row** (Base Rate on
   Rate Plan Room Type).
3. Failing that, the **room type's fallback Base Rate**.

A deliberately entered zero at any level is respected as a real decision (for
example, a free night in a package) — it does not fall through to the next
level just because it is zero. Restrictions are gathered from **all three
levels at once** (the Daily Rate row, the property-level Room Inventory
Restriction, and the rate plan's own Restrictions table), and the strictest
rule always wins: a date-level stop-sell is never softened by a permissive
plan-level rule.

---

## 8. Users, roles and access

Hospitality PMS defines **22 roles**, grouped below by function. A role's
"Desk access" column is a UX convenience only — it decides whether the user
can open `/app` at all, nothing more. The real enforcement boundary is each
DocType's permission rows (what you have been reading throughout this guide)
and the checks inside the whitelisted API. A role with Desk access off can
still be exactly as privileged, or as restricted, as its DocType permissions
say; turning Desk access on for an operational role does not grant anything
by itself.

| Function | Role | Desk access |
|---|---|---|
| Administration | Hospitality Administrator | Yes |
| Management | General Manager | Yes |
| Management | Hotel Manager | Yes |
| Front Office | Front Office Manager | Yes |
| Front Office | Front Office Agent | No — `/pms` only |
| Reservations | Reservation Manager | Yes |
| Reservations | Reservation Agent | No — `/pms` only |
| Revenue | Revenue Manager | Yes |
| Housekeeping | Housekeeping Manager | Yes |
| Housekeeping | Housekeeping Supervisor | Yes |
| Housekeeping | Room Attendant | No — `/pms` only |
| Maintenance | Maintenance Manager | Yes |
| Maintenance | Maintenance Technician | No — `/pms` only |
| Food and Beverage | Food and Beverage Manager | Yes |
| Food and Beverage | Kitchen Manager | Yes |
| Food and Beverage | Kitchen User | No — `/pms` only |
| Sales | Corporate Sales Manager | Yes |
| Guest Relations | Guest Relations Officer | No — `/pms` only |
| Night Audit | Night Auditor | Yes |
| Finance | Finance Manager | Yes |
| Finance | Accounts User | Yes |
| Audit | Read-Only Auditor | Yes |

`System Manager` is Frappe's own built-in role and sits above all of these —
it is never created or modified by this app, and typically only your Frappe
site administrator holds it.

Six roles are `/pms`-only by design: Front Office Agent, Reservation Agent,
Room Attendant, Maintenance Technician, Kitchen User and Guest Relations
Officer. Give these to staff who work exclusively from the front desk,
housekeeping trolley, maintenance handheld or kitchen screen — there is no
reason to also grant them Desk access.

### Restricting a user to one property

Hospitality PMS's own access model is deliberately just Frappe's **User
Permission** mechanism applied to Property, so that Desk, the
REST API and the `/pms` frontend all obey the same restriction without a
parallel access model of their own. To confine a user to a single property:

1. Go to **Desk → User Permission → New**.
2. Set **User** to the person you are restricting.
3. Set **Allowed Document Type** to `Property`.
4. Set **Value** to the specific property.
5. Save.

A user with **no** User Permission on Property is unrestricted
and can operate in every active property — this is Frappe's own default
behaviour and is what keeps a single-property site simple: you do not need to
create a User Permission at all if you only run one property. Once a
restriction exists, the user's default property resolves to their
configured default (if permitted), then to their single permitted property,
and every operation is checked against the same list — there is no separate
"PMS property access" setting to remember to update.

---

## 9. ERPNext posting profile

Before any folio charge can be invoiced against ERPNext, create a
**Posting Profile** for the property. Nothing posts without one —
this is a hard prerequisite, not an optional refinement. Write access is
Finance Manager, Hospitality Administrator and System Manager; General
Manager, Hotel Manager and Accounts User can only view it.

| Field | Notes |
|---|---|
| Profile Code | Required, unique. |
| Profile Name | Required. |
| Property | Required. |
| Active | |
| Company | Required. |
| Default Income Account | |
| Default Cost Center | |
| Default Receivable Account | |
| Default Tax Template | |
| Default Item | Used to post a charge whose charge type has no explicit mapping below. |
| Charge Item Mapping | A table (Charge Item Map) of Charge Type → Item, Income Account, Cost Center, Tax Template, Active. See charge types below. |
| Deposit Liability Account | |
| Update Stock on Posting | Only applies to charges carrying an item with stock (minibar, room service); a plain room charge or fee never touches stock regardless of this setting. |

**Charge types** available in the mapping table: Room Charge, Service Charge,
Tax, Tourism Fee, Municipality Fee, Room Service, Minibar, Laundry,
Transport, Telephone, Miscellaneous, Adjustment, Discount. Map every charge
type your property actually raises to a specific Item and Income Account; any
charge type left unmapped falls back to the profile's own Default Item and
default accounts, so an unmapped charge does not fail — but it will not post
to the account you expect for that charge type, so treat "unmapped" the same
way you treat a wrong account: as a posting error waiting to be noticed.

---

## 10. Integrations

All four integration doctypes are property-scoped and administratively
restricted — API keys, secrets and webhook secrets are stored in encrypted
`Password` fields and are never shown in plain text once saved.

### Payment Provider

Write access: Hospitality Administrator and System Manager only (Finance
Manager, General Manager and Hotel Manager can view).

| Field | Notes |
|---|---|
| Provider Code / Provider Name | Required, unique code. |
| Property | Required. |
| Provider | **Fatora**, **Stripe**, or **Manual**. Fatora is the primary payment provider, Stripe the fallback; Manual records an offline payment with no live gateway. |
| Active / Default Provider | |
| Environment | Sandbox or Production. |
| Supports Refund | |
| API Base URL, API Key, API Secret, Webhook Secret | Credentials — API Key/Secret/Webhook Secret are encrypted Password fields. |
| Mode of Payment / Payment Account | ERPNext accounting mapping for this provider's receipts. |
| Notes | |

**Fatora needs verifying before go-live.** The Fatora adapter shipped with
this app is built against the best available reading of Fatora's published
API documentation at the time of writing. It is **not verified against a
live sandbox**, and the code itself flags that the endpoint host, request
shape and status vocabulary must be checked against Fatora's current API
reference (`https://docs.fatora.io`) before the adapter is used against real
traffic. Do not point a Fatora Payment Provider at Production until someone
has confirmed the adapter's behaviour against a live Fatora sandbox account.

### Channel

Write access: Hospitality Administrator and System Manager only (Revenue
Manager, Reservation Manager, General Manager and Hotel Manager can view).

| Field | Notes |
|---|---|
| Channel Code / Channel Name | Required, unique code. |
| Property | Required. |
| Active | |
| Channel Type | Channel Manager, OTA Direct, GDS or Website. |
| Provider | Booking.com, Expedia, Agoda, Airbnb, Generic Channel Manager, or Other. |
| Environment | Sandbox or Production. |
| API Base URL, Hotel Code | |
| API Key, API Secret, Webhook Secret | Encrypted. |
| Push Availability / Push Rates / Pull Reservations | Sync direction toggles. |
| Sync Interval (Minutes) | Default 15. |
| Last Availability Push / Last Rate Push / Last Reservation Pull | Read-only, maintained by the sync process. |
| Default Rate Plan / Default Market Segment / Commission Percentage | Defaults applied to reservations pulled from this channel. |
| Room Mappings | A table mapping this channel's room codes to Hotel Room Types. |
| Notes | |

The channel model is deliberately provider-neutral: Booking.com, Expedia,
Agoda, Airbnb or any future channel manager all use the same doctype
structure, distinguished only by the Provider and Channel Type values and
their own room mapping rows.

### Hardware Device

Write access: Hospitality Administrator and System Manager only (Front
Office Manager, General Manager and Hotel Manager can view).

| Field | Notes |
|---|---|
| Device Code / Device Name | Required, unique code. |
| Property | Required. |
| Active | |
| Device Type | Door Lock Controller, ID Scanner, Key Card Encoder, Payment Terminal, or Other. |
| Provider | Free text — the vendor adapter for this device is resolved by this name at runtime. |
| Location / Room | Optional physical location and, for a door lock, a link to the Hotel Room it controls. |
| API Base URL, API Key, API Secret | Credentials, encrypted where applicable. |
| Last Seen On | Read-only. |
| Device Status | Unknown, Online, Offline or Error. |
| Notes | |

**No vendor hardware is bundled.** This doctype is a contract, not an
implementation: no door lock, ID scanner or key card vendor has been chosen
yet. Until a vendor is selected, the app ships with a **deterministic mock
adapter** for door locks and ID scanners — it always succeeds, never touches
a network, and returns predictable values, which is exactly what lets
check-in, key issuance and ID capture be built and tested now. Do not expect
a Hardware Device record configured here to talk to real hardware until a
vendor adapter has been written and registered for the `provider` name you
enter — creating the record alone does not connect to a physical door lock or
scanner.

### Regulatory Profile

Write access: Hospitality Administrator and System Manager only (General
Manager, Hotel Manager, Finance Manager and Accounts User can view — this
data is statutory and privacy sensitive, so access is kept tight).

| Field | Notes |
|---|---|
| Profile Code / Profile Name | Required, unique code. |
| Property | Required. |
| Country | Required. |
| Active | |
| Requires Guest Registration / Requires Police Reporting / Requires Tourism Levy Report / Requires E-Invoicing | Plain flags — a new country needs configuration here, not a schema change. |
| E-Invoice Provider | Free text. |
| Guest Registration Endpoint / Police Endpoint | |
| API Key / API Secret | Encrypted. |
| Submission Frequency | Real Time, Daily, Weekly or Monthly. |
| Retention (Years) | Default 10, per the approved retention policy. |
| Notes | |

Initial readiness covers **Saudi Arabia, Qatar, Oman and Pakistan** — a
requirement is only switched on where it has been legally confirmed for that
country. If your property is outside these four, do not assume a requirement
flag is safe to leave off; confirm the actual statutory obligation before
going live and configure the profile to match.

---

## 11. Going live checklist

Work through this in order — later steps depend on earlier ones.

**ERPNext prerequisites**

- [ ] Company created, with the Chart of Accounts fully built out.
- [ ] Cost Centre(s) created.
- [ ] Warehouses created for every stock purpose you will use (General Store, Kitchen Store, Minibar, Housekeeping Store, Laundry, Maintenance Store).
- [ ] Item Group, Customer Group and Territory exist; Selling Settings has sensible defaults for Customer Group and Territory.
- [ ] Mode of Payment created for each payment method you accept.
- [ ] Sales Taxes and Charges Template(s) created.
- [ ] Price List created.

**Installation**

- [ ] App installed and migrated (`bench get-app`, `install-app`, `migrate`).
- [ ] Frontend built with Node 24 (`yarn install && yarn build`), and `/pms` loads on the site.

**Property**

- [ ] Property created, with a correct Company, Currency, Country and Time Zone.
- [ ] Business Date set to the correct opening operating day.
- [ ] Accounting mapping (Receivable, Room Revenue, Deposit Liability accounts, Tax Template) checked by finance before anything is invoiced.
- [ ] Property Fees configured, if applicable (service charge, tourism fee, municipality fee, city tax).
- [ ] Warehouses mapped by purpose on the property record.

**Physical structure**

- [ ] Buildings, Wings, Floors and Zones created to match the property's actual layout.

**Departments and shifts**

- [ ] Departments created for each operating department.
- [ ] Shifts created with correct timing and days run.

**Rooms**

- [ ] Room Types created, with occupancy limits and fallback rates set.
- [ ] Hotel Rooms created, each with Building/Wing/Floor/Zone assigned.
- [ ] Spot-check a few rooms' default statuses (Vacant / Clean / Operational / Available) before opening for business.

**Rates**

- [ ] At least one active Standard Rate Plan exists for every sellable Room Type, with Valid From covering today.
- [ ] Rate Plan Room Type rows entered for every Room Type the plan covers.
- [ ] Cancellation, No Show and Deposit policies created and linked where needed.
- [ ] Daily Rate grid populated for the near-term booking window, if you rely on date-level pricing rather than the plan-level rate.

**Users, roles and access**

- [ ] Staff accounts created and assigned the correct roles from the 22-role list.
- [ ] `/pms`-only roles (Front Office Agent, Reservation Agent, Room Attendant, Maintenance Technician, Kitchen User, Guest Relations Officer) are not also given unnecessary Desk access.
- [ ] User Permissions on Property created for any user who must be confined to a single property.

**Posting profile**

- [ ] Posting Profile created and marked Active for the property.
- [ ] Every charge type your property actually raises is mapped to a specific Item, Income Account and Cost Centre — nothing left to the fallback that does not need to be.

**Integrations**

- [ ] Payment Provider(s) configured; if using Fatora, its adapter has been verified against a live Fatora sandbox before switching Environment to Production.
- [ ] Channel(s) configured, if selling through OTAs or a channel manager, with room mappings complete.
- [ ] Hardware Device(s) recorded, understanding that door locks and ID scanners run on the mock adapter until a vendor is selected and its adapter is registered.
- [ ] Regulatory Profile configured and checked against the property's actual statutory obligations, not just left at defaults.

**Final check**

- [ ] Run a complete dry-run booking: reservation → check-in → a folio charge → checkout → Night Audit, and confirm every step posts to the accounts you expect.
