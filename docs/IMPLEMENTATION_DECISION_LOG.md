# Hospitality PMS — Implementation Decision Log

**Current application version:** 16.1.0 (branch `version-16`)

Continues the approved governance Decision Log
(`docs/hospitality-pms/08_Hospitality_PMS_Decision_Log_v1.2_APPROVED.md`, HPMS-DEC-001..048).

Entries here are **implementation** decisions taken inside the approved v1.2 baseline,
per Master Development Roadmap section 4. Anything that would change approved scope,
architecture, financial integrity or data safety is escalated instead of logged.

| ID | Decision | Rationale | Build | Status |
|---|---|---|---|---|
| HPMS-DEC-049 | Frontend toolchain runs on Node 24 | Frappe v16 declares `"node": ">=24"`; bench `.nvmrc` is already 24. Bench default alias set to 24. | 0.1.0 | Approved |
| HPMS-DEC-050 | `/pms` is served from `www/pms.html` with the Vite build output in `hospitality_pms/public/frontend` | Frappe CRM pattern; no standalone Node runtime in production (HPMS-DEC-040, HPMS-DEC-042) | 0.1.0 | Approved |
| HPMS-DEC-051 | DocType names are taken verbatim from SAD section 7 with no app prefix | Verified collision-free against frappe and erpnext v16 | 0.1.0 | Approved |
| HPMS-DEC-052 | Property isolation is enforced with permission query conditions plus User Permissions | Server-side enforcement without duplicating a parallel ACL model (HPMS-DEC-030) | 0.1.0 | Approved |
| HPMS-DEC-053 | Concurrency uses `SELECT ... FOR UPDATE` row locks inside the request transaction; idempotency keys guard posting and callbacks | Transaction-safe without an external lock service; portable to Frappe Cloud (SAD section 8) | 0.1.0 | Approved |
| HPMS-DEC-054 | The app declares 13 Frappe modules, one per roadmap domain | Keeps Desk navigable and gives every build an unambiguous home | 0.1.0 | Approved |
| HPMS-DEC-055 | `requires-python` is relaxed from the generated `>=3.14` to `>=3.11` | The generated pin matched only this bench's interpreter and would block Frappe Cloud deployment (HPMS-DEC-007) | 0.1.0 | Approved |
| HPMS-DEC-056 | `required_apps = ["frappe/erpnext"]` is declared in hooks | ERPNext is the system of record; installing PMS without it is unsupported (HPMS-DEC-002) | 0.1.0 | Approved |
| HPMS-DEC-057 | Frontend dependency matrix pinned to Frappe UI 0.1.278's supported set: Vue 3.5, vue-router 4, TailwindCSS 3.4, Vite 6 | Frappe UI declares `vue-router ^4.1.6` and builds against Tailwind 3; vue-router 5 / Tailwind 4 are not supported by it | 0.2.0 | Approved |
| HPMS-DEC-058 | Frontend UI strings live in JSON catalogues (`frontend/src/locales/*.json`); server-generated messages use Frappe's own translations | One source of truth per message, no duplicated catalogue, and no build-time extraction step for `.vue` files | 0.2.0 | Approved |
| HPMS-DEC-059 | The app root `package.json` exposes a `build` script that runs the Vite build | `bench build --app hospitality_pms` is what Frappe Cloud runs on deploy, so the frontend ships with the app and needs no separate pipeline (HPMS-DEC-040) | 0.2.0 | Approved |
| HPMS-DEC-060 | Frontend build output (`public/frontend/`, `www/pms.html`) is git-ignored | Generated on every build; committing it would create merge noise and stale assets | 0.2.0 | Approved |
| HPMS-DEC-061 | The app declares 13 modules and creates DocTypes through the Frappe API, keeping the generated JSON as the source of truth | Guarantees the files match the exact v16 schema instead of hand-written JSON drifting from it | 0.3.0 | Approved |
| HPMS-DEC-062 | Operational codes are normalised at `before_naming`, not in `validate` | `autoname` runs before `validate`, so normalising later leaves `name` and the code field disagreeing on case | 0.3.0 | Approved |
| HPMS-DEC-063 | Roles are declared in `setup/roles.py` and synced from `after_install`/`after_migrate`; DocType permissions live in the DocType JSON | Frappe auto-creates roles referenced by a DocType JSON with desk access on, so the sync exists to correct desk access for frontend-only roles. Custom DocPerm records would be discarded by migrate. | 0.4.0 | Approved |
| HPMS-DEC-064 | The existing ERPNext roles `Accounts User` and `Maintenance Manager` are reused rather than duplicated | Both appear in the approved matrix and already carry the ERP permissions those users need | 0.4.0 | Approved |
| HPMS-DEC-065 | Six operational roles get `desk_access = 0` (Front Office Agent, Reservation Agent, Room Attendant, Maintenance Technician, Kitchen User, Guest Relations Officer) | They work only in `/pms`. Desk access is a UX switch, not a security boundary; DocType permissions still govern them. | 0.4.0 | Approved |
| HPMS-DEC-066 | Property isolation relies on Frappe User Permissions on Hospitality Property, verified by test, rather than custom permission query conditions | Frappe applies user permissions to link fields automatically for ORM reads, so custom conditions would duplicate framework behaviour. Custom queries use `PropertyService.get_permitted_properties()`. | 0.4.0 | Approved |
| HPMS-DEC-067 | Property accounting fields sit at permlevel 1, readable by finance/management and writable by Finance Manager and administrators | Establishes the sensitive-field mechanism now; guest ID and payment fields reuse it in 0.6.0 and 0.15.0 | 0.4.0 | Approved |
| HPMS-DEC-068 | Frontend links to Desk use `/desk/...`, not `/app/...` | Frappe v16 serves Desk at `/desk`; `/app` only 301-redirects, costing an extra round trip | 0.4.0 | Approved |
| HPMS-DEC-069 | Room status changes are authorised per dimension, not by blanket write access on Hotel Room | A Room Attendant must finish cleaning without being able to stop sale or rename a room | 0.5.0 | Approved |
| HPMS-DEC-070 | Guest blacklist flag sits at permlevel 2, the reason at permlevel 3 | The desk must see that a guest is blacklisted to refuse a check-in; incident detail is not front-desk information | 0.6.0 | Approved |
| HPMS-DEC-071 | A dirty room is still sellable inventory; only maintenance and inventory status remove it from sale | Treating dirty as unavailable would collapse availability every morning | 0.7.0 | Approved |
| HPMS-DEC-072 | Availability reads reservation demand through an extension point that returns nothing until reservations exist | Keeps the arithmetic correct at every build stage without importing a DocType that does not exist yet | 0.7.0 | Approved |
| HPMS-DEC-073 | Confirmation locks the Room Type rows, then re-reads availability, then writes | Makes the read-check-write sequence atomic so two agents cannot both sell the last room (HPMS-DEC-053) | 0.9.0 | Approved |
| HPMS-DEC-074 | The per-night rate snapshot is stored flat on Hotel Reservation with a `room_line` back-reference | Frappe has no grandchild tables, so the snapshot cannot hang off Reservation Room | 0.9.0 | Approved |
| HPMS-DEC-075 | `Confirmed` is not a creatable status; it is reachable only through ReservationService.confirm | Inserting straight into Confirmed would bypass the availability lock and oversell the house | 0.9.0 | Approved |
| HPMS-DEC-076 | Folio corrections are reversals only; posted charges and payments are immutable and undeletable | What makes the subledger reconcilable against ERPNext (HPMS-DEC-003, HPMS-DEC-031) | 0.13.0 | Approved |
| HPMS-DEC-077 | Folio split and merge set an explicit `flags.hpms_moving_rows` marker to move rows past the immutability guard | A move is not a deletion: the row exists on the target and both sides are logged. Only the service may set the flag. | 0.13.0 | Approved |
| HPMS-DEC-078 | Hospitality Stay and Hospitality Guest Folio link to each other, so install creates a Stay stub first | Neither can be created before the other; the stub is immediately replaced by the real definition | 0.11.0 | Approved |
| HPMS-DEC-079 | ERP posting is claimed through a unique idempotency key on the Financial Posting Log before any document is created | The unique constraint serialises two concurrent attempts: the loser cannot create a second invoice (HPMS-DEC-031) | 0.14.0 | Approved |
| HPMS-DEC-080 | A Payment Entry is raised per folio payment line, not per folio | A deposit, a settlement and a refund each reconcile against their own ledger entry | 0.14.0 | Approved |
| HPMS-DEC-081 | Provider credentials use the Frappe `Password` fieldtype and are read only through `get_secret()` | Frappe encrypts Password fields at rest; a plaintext Data field would expose keys in the database and in exports | 0.15.0 | Approved |
| HPMS-DEC-082 | Webhook signatures are verified against the raw request body, threaded through the API layer | Stripe and similar providers sign exact bytes; a re-encoded payload changes key order and every signature check fails | 0.15.0 | Approved |
| HPMS-DEC-083 | Checkout posts to ERPNext before releasing the room | A posting failure then leaves the guest in house with nothing lost; the reverse order would sell a room while the revenue went unrecorded | 0.16.0 | Approved |
| HPMS-DEC-084 | Reversing a checkout does not cancel a submitted Sales Invoice | Cancelling a submitted invoice is a finance decision with its own approval; doing it silently would break the ledger the hotel reports from | 0.16.0 | Approved |
| HPMS-DEC-085 | Night audit room charges post under `room-charge:{stay}:{business_date}` | Makes the audit safe to re-run after a crash, which is exactly when it is most likely to be re-run | 0.17.0 | Approved |
| HPMS-DEC-086 | Taking a room out of service raises a submitted Room Block, not just a status flag | Availability, the room rack and revenue then all agree the room is gone; a flag alone would leave availability still selling it | 0.19.0 | Approved |
| HPMS-DEC-087 | Exceeding a corporate credit limit is refused and flags the account Exception Required, rather than being blocked outright or allowed silently | Matches Workflow Matrix section 8: the corporate desk escalates and finance approves | 0.20.0 | Approved |
| HPMS-DEC-088 | Room service orders are priced from the menu record, never from the caller-supplied rate | A client able to set its own price could give the hotel's stock away | 0.23.0 | Approved |
| HPMS-DEC-089 | A channel message is stored raw and keyed before it is mapped to a reservation | A malformed or duplicate channel message can then never corrupt the operational record, and the raw payload survives for diagnosis | 0.24.0 | Approved |
