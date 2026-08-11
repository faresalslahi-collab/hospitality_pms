# Hospitality PMS — Coding Conventions

Governing baseline: `frappe-bench/docs/hospitality-pms/` (v1.2 APPROVED).
This file records **how** we write the code; it never overrides the approved documents.

## Platform

- Frappe Framework v16, ERPNext v16, Python 3.11+ (bench runs 3.14).
- Frontend toolchain runs on **Node 24** (`bench/.nvmrc`). Frappe v16 refuses Node < 24.
- Never modify Frappe or ERPNext core. Extend only through this app.

## Repository layout

```
hospitality_pms/
  api/            whitelisted endpoints for the Vue frontend (thin)
  services/       authoritative domain logic (SAD section 6)
  integrations/   provider adapters only
  utils/          small dependency-free helpers
  fixtures/       reproducible configuration
  patches/        data migrations
  www/            /pms entry point
  workspace_sidebar/  Desk sidebar (app-level, imported by bench migrate)
  desktop_icon/       Desk desktop tile (app-level, imported by bench migrate)
  hospitality_*/  one Frappe module per domain, each with doctype/
```

Modules: Setup, Rooms, Guests, Rates, Reservations, Front Office, Folio,
Night Audit, Housekeeping, Maintenance, Sales, Services, Integrations.

## Layering

```
Vue page -> composable/store -> resource -> whitelisted API -> service -> ORM
```

- Business rules live in `services/`. Never in Vue, never duplicated in a DocType
  controller. DocType `validate()` may call a service, not reimplement it.
- API modules validate input, call a service, shape the response.
- No raw SQL where the ORM or query builder will do. When raw SQL is unavoidable,
  it is parameterised and permissions are checked explicitly.

## Server authority (non-negotiable)

The frontend never owns: permission decisions, rate authorisation, availability
locking, financial posting rules, workflow authorisation, audit decisions, tax
calculation, collision prevention, Night Audit closure.

- Every whitelisted method that bypasses ORM permission checks calls
  `services.base.require_permission()` or `require_role()`.
- Mutating endpoints are `@frappe.whitelist(methods=["POST"])` so CSRF applies.
- Route guards in Vue are UX only.

## Concurrency and integrity

- Use `services.base.lock_document()` / `lock_documents()` before reading state
  the same operation will change: reservation confirmation, room assignment,
  check-in, room change, checkout, night audit close, OOO release, posting,
  payment callbacks, channel import (SAD section 8).
- `lock_documents()` sorts keys; keep lock ordering deterministic to avoid deadlocks.
- Financial posting and every external callback carry an idempotency key. Replay
  returns the original result and never double-posts.
- Use `services.base.transaction()` (savepoint) for sub-operations that may fail
  without discarding the caller's work.

## Data model

- Every operational DocType carries `property` (Link: Property).
- Index the fields we filter on at scale: property, status, arrival/departure dates.
- Naming series are explicit and readable; no auto-hash names on operational records.
- DocType names follow SAD section 7 verbatim, no prefix.

## Audit

Sensitive actions listed in SAS section 7 must write an audit record with actor,
timestamp, before/after and reason. Reason is mandatory for overrides, discounts,
adjustments, reversals and Night Audit reopen.

## Dates: which kind, and when

Four different things get called "the date" in a hotel, and mixing them up was
the single largest class of defect Phase 1 found. Every new date must be one of
these deliberately.

**Business date** — the hotel's operational and accounting day. *Every*
operational default. A property that has not yet run its Night Audit is still
working yesterday, and its arrivals board, folio postings, availability defaults
and audit must all agree on which day that is.

    from hospitality_pms.services.property import resolve_operational_date
    on_date = resolve_operational_date(property_name, on_date)

One implementation, in `services/property.py`. `front_office.resolve_business_date`
delegates to it. Never write a second one.

**Calendar date** — a real civil date, used only where a civil date is what is
meant: when something physically happened (`charge_date`, `payment_date`,
`booked_on`), or a reporting lookback over wall-clock data. These sit *alongside*
the operational `business_date` on the same row, never instead of it.

**Wall-clock timestamp** — `now_datetime()`, for audit trail and provider events:
`started_on`, `*_completed_on`, `initiated_on`, `completed_on`. Never moved onto
a business date; doing so makes the audit trail lie about real time.

**Reservation service date** — the date being *priced or checked*, which for a
future booking is neither today nor the business date. Contract validity, rate
plan validity and negotiated rates are evaluated against the night in question
when the caller supplies one, and fall back to the business date when the
question is operational rather than forward-looking.

Server side, `nowdate()` and `today()` in `services/` and `api/` are refused by
`tests/test_final_integrity.py` unless allow-listed with a reason. Client side,
operational screens default from `property.businessDate` via
`utils/operationalDate.js` — never `new Date()`.

## Localisation

- Every user-facing string is translatable: `frappe._()` server side, the i18n
  helper client side. No English literals inside reusable logic.
- Layouts must not assume left/right. Arabic + RTL is a first-release requirement.

## Testing policy (v1.2, mandatory)

- While coding: syntax/import check, one targeted unit test for high-risk server
  logic, one direct API or page smoke check, migrate only on schema change.
- Do **not** run full regression, E2E, permission matrix, clean install or
  performance suites after individual features.
- At build completion: one consolidated validation, recorded in `docs/BUILD_LOG.md`.
- Full test program only at Release Candidate (HPMS-0.90.0).

## Records kept in this repo

- `docs/IMPLEMENTATION_DECISION_LOG.md` — decisions from HPMS-DEC-049 onward.
- `docs/BUILD_LOG.md` — one acceptance record per completed build.
