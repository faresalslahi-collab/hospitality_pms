# Hospitality PMS — Operations Runbook

For whoever keeps the system running: deployment, backup and restore, upgrades,
failure recovery and the checks worth doing before anyone notices a problem.

Written against the implementation as built. Where something is not yet
automated, this says so rather than implying it is.

---

## 1. What the system is made of

```
Frappe Cloud private bench, or a self-hosted Frappe Bench
├── Frappe Framework v16
├── ERPNext v16                 the financial and inventory system of record
├── hospitality_pms             this app
│   ├── Python backend          DocTypes, services, whitelisted API
│   └── compiled Vue frontend   served from the site at /pms
├── MariaDB                     all data
├── Redis                       cache, queue and realtime
├── background workers          scheduled jobs
└── scheduler
```

There is no separate Node process in production. The Vue frontend is built at
deploy time into `hospitality_pms/public/frontend` and served as static site
assets, with `www/pms.html` as its entry point.

**Two surfaces:**

| Surface | Path | Used for |
|---|---|---|
| Operational frontend | `/pms` | Front office, housekeeping, maintenance, in-house |
| Frappe Desk | `/desk` | Configuration, master data, approvals, audit, ERPNext, reports |

Frappe v16 serves Desk at `/desk`. `/app` still works but only as a redirect.

---

## 2. Requirements

| Component | Version | Why it matters |
|---|---|---|
| Frappe Framework | v16 | The baseline the app is built against |
| ERPNext | v16 | System of record for invoices, payments and stock |
| Python | 3.11 or later | `pyproject.toml` declares `>=3.11` |
| Node | **24 or later** | Frappe v16 refuses to build assets on anything older |
| MariaDB | 10.6 or later | |
| Redis | Any supported by the bench | |

**Node 24 is not optional.** Frappe v16 declares `"node": ">=24"` and the asset
build fails outright on Node 18 with `The engine "node" is incompatible with
this module`. On a bench managed by nvm, set it as the default:

```bash
nvm install 24
nvm alias default 24
```

The bench's own `.nvmrc` should already say `24`.

---

## 3. Installing

```bash
cd frappe-bench

bench get-app hospitality_pms <repository-url>
bench --site <site> install-app hospitality_pms
bench --site <site> migrate
```

`install-app` runs `after_install`, which creates the 13 app modules and the 22
PMS roles. `migrate` runs `after_migrate`, which does the same thing again
idempotently — so a site that is upgraded rather than freshly installed still
converges.

Then follow the **Administrator and Setup Guide** to configure the property.
Nothing operational works until a property exists with a business date.

### Building the frontend

```bash
bench build --app hospitality_pms
```

This runs the app's root `package.json` build script, which runs the Vite build.
It is the same command Frappe Cloud runs on deploy, so if it works locally it
works there.

For frontend development:

```bash
cd apps/hospitality_pms/frontend
yarn install
yarn dev          # Vite dev server, proxied to the Frappe site
```

---

## 4. Backup

```bash
bench --site <site> backup                 # database + site config
bench --site <site> backup --with-files    # also public and private files
```

Use `--with-files` for anything you intend to restore from. Guest
identification images and regulatory export attachments live in the files
directory, not the database; a database-only backup will restore a site whose
guest ID scans are all missing.

Backups land in `sites/<site>/private/backups/`.

### What to keep, and for how long

The approved retention policy (SAS section 8) drives this:

| Data | Minimum retention |
|---|---|
| Reservation, stay and folio records | 10 years |
| Audit and security logs | 3 years |
| Integration logs | 1 year |
| Temporary provider payloads | 30–90 days |
| Guest ID images | Configurable, short — set on Hospitality Settings |
| Financial and statutory records | Whatever the country requires |

Backups must be retained to satisfy the longest of these. Take them off the
machine that runs the site: a backup sitting on the same disk as the database
protects you from a mistake, not from a failure.

### Suggested schedule

| When | What |
|---|---|
| Daily, after the night audit closes | Full backup with files |
| Before every deployment | Full backup with files |
| Before every `bench migrate` | Full backup with files |
| Monthly | Verify a restore actually works, on a scratch site |

That last one matters. A backup you have never restored is a hypothesis.

---

## 5. Restore

```bash
bench --site <site> restore <path-to-database.sql.gz> \
  --with-public-files <path-to-files.tar> \
  --with-private-files <path-to-private-files.tar>
```

`bench restore` needs the **MariaDB root password**, because it drops and
recreates the site database. Keep it where the person doing a 3am recovery can
actually reach it.

After any restore:

```bash
bench --site <site> migrate
bench build --app hospitality_pms
bench --site <site> clear-cache
```

Then check the site is genuinely healthy, not merely up:

```bash
bench --site <site> execute hospitality_pms.api.ping
```

and confirm in Desk that the property's **business date** is what you expect. A
restore rolls the business date back to whatever it was in the backup; if the
night audit has run since, that day will need re-running.

> **Not yet validated in this environment.** Backup has been exercised and
> produces a valid archive. Restore has not, because the MariaDB root password
> was not available. Validate a restore on a scratch site before go-live — it
> is a Release Candidate requirement that remains open.

---

## 6. Upgrading

```bash
bench --site <site> backup --with-files      # always first
bench update --apps hospitality_pms          # or bench get-app / pull
bench --site <site> migrate
bench build --app hospitality_pms
bench --site <site> clear-cache
bench restart
```

Then re-run the checks in section 9.

**Never modify Frappe or ERPNext core.** Every change belongs in this app. A
core edit will be silently reverted by the next framework update, usually at
the worst possible moment.

### After a schema change

`bench migrate` applies DocType changes. If a build has changed the permission
matrix, the matrix lives in `hospitality_pms/setup/permissions.py` and is
written into the DocType JSON files by:

```bash
bench --site <site> execute hospitality_pms.setup.permissions.apply_permissions
```

That is a **development-time** command. It rewrites files in the app directory,
so run it in development and commit the resulting JSON — do not run it against
production.

---

## 7. Scheduled work

The app relies on the Frappe scheduler being alive. Confirm it:

```bash
bench --site <site> doctor
bench --site <site> scheduler status
```

If the scheduler is paused, these stop happening silently:

| Job | Consequence if it stops |
|---|---|
| Guest service SLA sweep | Requests never escalate; breaches accumulate unseen |
| Channel availability push | Channels sell stale inventory, and you oversell |
| Integration failure queue retry | Failed payments and channel messages sit unretried |

The night audit is **not** scheduled to run itself. It is started by a Night
Auditor, on purpose: closing a business date over an unresolved exception is
exactly what an automated close would do.

---

## 8. Failure recovery

### A payment gateway callback never arrived

The guest paid, the folio does not show it.

1. Find the transaction: Desk → Hospitality Payment Transaction, filter by
   provider reference or folio.
2. Ask the provider what really happened:
   `bench --site <site> execute hospitality_pms.services.payments.sync_status --args "['<transaction>']"`
3. If the provider says captured, the payment posts to the folio automatically
   under a key derived from the transaction — so this is safe even if the
   callback arrives late as well. The guest is credited once.

### A posting to ERPNext failed

1. Desk → Hospitality Financial Posting Log, filter status `Failed`. Every
   failure carries its error and the payload that was sent.
2. Fix the cause. Most failures are configuration: a missing item mapping, an
   account belonging to another company, no valuation rate on a stock item.
3. Retry under the original key:
   `bench --site <site> execute hospitality_pms.services.posting.retry_posting --args "['<log-name>']"`

A posting that already succeeded is never re-sent, whatever you do to it. That
is the point of the key.

### A folio does not agree with ERPNext

Use the reconciliation view (`hospitality_pms.api.checkout.reconciliation`) or,
per folio:

```bash
bench --site <site> execute hospitality_pms.services.posting.reconcile_folio --args "['<folio>']"
```

It reports the variance rather than correcting it. That is deliberate — an
automatic correction would paper over the discrepancy finance needs to see.

### The night audit will not close

It refuses while any blocking exception is unresolved. Open the audit, work the
exception list, and resolve each with a note saying how. If an exception cannot
be resolved tonight, it is a genuine operational problem, not a system one —
the audit is doing its job.

### A business date needs to move back

Only through a night audit reopen, by a Hotel Manager, General Manager or
Finance Manager, with a reason. There is no other path, including in Desk: the
property record itself refuses a direct edit to the business date.

### A room is stuck out of sale

Check three things in order: the maintenance status on the room, whether an
active Room Block still covers it, and the inventory status. A room taken out
of service by a maintenance ticket is released by verifying that ticket, not by
editing the room.

---

## 9. Health checks

Quick, and worth doing after any change:

```bash
# The app answers
bench --site <site> execute hospitality_pms.api.ping

# Scheduler alive
bench --site <site> scheduler status

# Setup converges from the repository alone
bench --site <site> execute hospitality_pms.install.after_migrate
```

In the browser:

| Check | Expected |
|---|---|
| `/pms` while logged out | Redirects to `/login?redirect-to=/pms` |
| `/pms` while logged in | The operational frontend loads |
| `/desk/hospitality-pms` | The administrative workspace loads |

Worth a look weekly:

- Hospitality Financial Posting Log, status `Failed` — should be empty
- Hospitality Integration Failure Queue, status `Pending` — should be short
- Guest requests past their due time — should be short and escalating
- Rooms out of order for longer than their ticket suggests

---

## 10. Monitoring

Watch these. Each has a cheap signal and an expensive consequence.

| Signal | Why it matters |
|---|---|
| Scheduler heartbeat | Silence here stops SLA escalation and channel pushes |
| Failed postings | Revenue not reaching the ledger |
| Integration failure queue depth | Payments or channel messages piling up |
| Business date vs today | A property whose date has not advanced means the audit is not running |
| Redis and MariaDB availability | Everything |
| Disk on the backup volume | A full disk fails backups quietly |

---

## 11. Security notes

- Provider credentials — payment, channel, hardware, regulatory — are stored in
  Frappe `Password` fields, which are encrypted at rest. Never move one to a
  plain Data field to make debugging easier.
- The payment webhook is the only endpoint reachable without a session. It
  verifies the provider's signature against the raw request body before reading
  any field. Do not add another guest endpoint without a comparable check.
- Guest identification sits at permlevel 1, the blacklist flag at 2 and its
  reason at 3. Housekeeping, maintenance and kitchen roles cannot read guest
  records at all.
- Vue route guards are convenience. Every rule is enforced on the server.
- Keep CSRF protection on in production.

---

## 12. Known limitations

Honest list, current as of the Release Candidate:

| Area | Status |
|---|---|
| Clean installation on a fresh site | Not yet validated — needs MariaDB root access |
| Restore | Not yet validated — same reason. Backup is validated. |
| UAT | Not started — requires business users |
| Fatora adapter | Endpoints and status vocabulary are best-effort and need verifying against current provider documentation before go-live |
| Regulatory submission | Exports generate and are marked submitted for manual filing; no authority transport is wired |
| Hardware | Ships with mock door lock and ID scanner adapters until a vendor is chosen |
| Group reservations | Blocks and rooming lists exist; pickup and cutoff release are not yet automated |

---

## 13. Where things are

| What | Where |
|---|---|
| Approved governance baseline (v1.2) | `frappe-bench/docs/hospitality-pms/` |
| Coding conventions | `apps/hospitality_pms/CLAUDE.md` |
| Implementation decisions | `apps/hospitality_pms/docs/IMPLEMENTATION_DECISION_LOG.md` |
| Build acceptance records | `apps/hospitality_pms/docs/BUILD_LOG.md` |
| User guides | `apps/hospitality_pms/docs/guides/` |
| Domain logic | `apps/hospitality_pms/hospitality_pms/services/` |
| Provider adapters | `apps/hospitality_pms/hospitality_pms/integrations/` |
| Frontend source | `apps/hospitality_pms/frontend/src/` |
