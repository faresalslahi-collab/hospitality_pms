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

- Every operational DocType carries `property` (Link: Hospitality Property).
- Index the fields we filter on at scale: property, status, arrival/departure dates.
- Naming series are explicit and readable; no auto-hash names on operational records.
- DocType names follow SAD section 7 verbatim, no prefix.

## Audit

Sensitive actions listed in SAS section 7 must write an audit record with actor,
timestamp, before/after and reason. Reason is mandatory for overrides, discounts,
adjustments, reversals and Night Audit reopen.

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
