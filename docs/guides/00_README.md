# Hospitality PMS — Operational Guides

**Applies to:** Hospitality PMS 16.1.0 (branch `version-16`)

Written against the implementation as built, not against the specification.
Where a workflow is not yet available in the `/pms` frontend, the guides say so
and point at Desk instead.

| Guide | Who it is for |
|---|---|
| [01 Administrator and Setup Guide](01_Administrator_and_Setup_Guide.md) | The person configuring the property, rooms, rates, users and integrations |
| [02 Front Office Guide](02_Front_Office_Guide.md) | Reservation agents, front desk agents, front office managers |
| [03 Housekeeping, Maintenance and Guest Services Guide](03_Housekeeping_Maintenance_and_Guest_Services_Guide.md) | Housekeeping, maintenance, guest relations and kitchen |
| [04 Night Audit, Finance and Reconciliation Guide](04_Night_Audit_Finance_and_Reconciliation_Guide.md) | Night auditors, accounts users, finance managers |
| [05 Operations Runbook](05_Operations_Runbook.md) | Whoever keeps the system running |

## Two surfaces

| Surface | Path | Used for |
|---|---|---|
| Operational frontend | `/pms` | High-frequency hotel workflows |
| Frappe Desk | `/desk` | Configuration, master data, approvals, audit, ERPNext, reports |

## Governing documents

These guides describe how to use the system. They do not override the approved
v1.2 baseline in `frappe-bench/docs/hospitality-pms/`, which governs scope,
architecture, roles, workflows and acceptance.

Implementation decisions taken inside that baseline are recorded in
[`../IMPLEMENTATION_DECISION_LOG.md`](../IMPLEMENTATION_DECISION_LOG.md), and
each build's acceptance result in [`../BUILD_LOG.md`](../BUILD_LOG.md).

## Before go-live

The Operations Runbook carries a **Known limitations** section listing what has
not yet been validated — clean installation, restore, UAT — and the integration
points that need verifying against current provider documentation. Read it
before signing off a production release.
