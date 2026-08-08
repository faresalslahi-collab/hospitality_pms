# Hospitality PMS

**Version 16.1.0** · branch `version-16` · released 2026-08-08

Hotel Property Management System built as an independent Frappe custom application
on Frappe Framework v16 and ERPNext v16, with a Vue 3 operational frontend served
from the Frappe site at `/pms`.

ERPNext remains the financial and enterprise system of record. Hospitality PMS owns
the operational hospitality domain: property and room configuration, guests,
reservations and availability, rates, front office, stay, guest folio, checkout,
Night Audit, housekeeping, maintenance, corporate accounts, groups, guest services,
kitchen/room service/minibar, and the payment, channel, hardware and regulatory
adapter layers.

## Requirements

- Frappe Framework v16
- ERPNext v16
- Python 3.11+
- Node 24 (Frappe v16 requirement; see bench `.nvmrc`)
- MariaDB 10.6+, Redis

## Installation

```bash
cd frappe-bench
bench get-app hospitality_pms <repo-url>
bench --site <site> install-app hospitality_pms
bench --site <site> migrate
```

## Development

```bash
# backend
bench --site <site> migrate

# frontend (Node 24)
cd apps/hospitality_pms/frontend
yarn install
yarn dev            # Vite dev server, proxied to the Frappe site
yarn build          # writes to hospitality_pms/public/frontend
```

The operational frontend is available at `http://<site>/pms`.
Frappe Desk remains the surface for configuration, master data, administration,
approvals, ERP functions, audit and standard reporting.

## Versioning

The application follows the Frappe ecosystem convention: the major version tracks
the framework generation it targets, and the branch is named for it.

```
16 . 1 . 0
│    │   └── patch — fixes, no schema or API change
│    └────── minor — features, additive schema, backward compatible
└─────────── major — Frappe/ERPNext generation (16 = Frappe v16, ERPNext v16)
```

```bash
$ bench version
hospitality_pms 16.1.0
```

A move to Frappe v17 becomes 17.x.y on a `version-17` branch, with `version-16`
kept for maintenance — the same way Frappe and ERPNext themselves are released.

The `HPMS-x.y.z` identifiers in the roadmap and build log are **build numbers**
from the approved v1.2 governance baseline, not application versions. They record
which increment of work delivered a change and are not renumbered. Build
HPMS-1.0.0 Production Release is delivered by application version 16.1.0.

## Documentation

- Approved governance baseline (v1.2): `frappe-bench/docs/hospitality-pms/`
- Coding conventions: [`CLAUDE.md`](CLAUDE.md)
- Implementation decisions: [`docs/IMPLEMENTATION_DECISION_LOG.md`](docs/IMPLEMENTATION_DECISION_LOG.md)
- Build acceptance records: [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md)

## Licence

MIT
