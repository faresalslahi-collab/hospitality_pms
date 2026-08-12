"""The identity Hospitality PMS posts to ERPNext under.

A Front Office Agent checks guests out. Checkout raises an ERPNext Payment
Entry, and ERPNext's own validation reads the Sales Invoice it allocates
against - `get_reference_details` calls `frappe.has_permission("Sales Invoice",
"read", ...)` before anything else. That call answers for the session user and
ignores `ignore_permissions` entirely, so the agent was refused with a bare
`PermissionError` (UAT-004).

There were three ways out and two of them are worse than the problem:

* give the front desk Sales Invoice read - every agent in the estate could then
  browse the company's invoices, which is a much larger hole than the one being
  closed;
* post as Administrator - unbounded authority, and the accounting documents
  would carry no useful actor at all.

So the posting runs as a **dedicated identity with one permission**. It is not
an account anyone signs in as and it holds nothing beyond what the validated
call path was observed to need: `Sales Invoice` read, and nothing else. Every
document Hospitality creates is still inserted with `ignore_permissions`, so
this role does not need create or submit rights on anything - it exists purely
to satisfy ERPNext's internal read check.

The authorisation decision is *not* made here. It is made in
`services.posting.erp_posting_authority`, as the real caller, against the
property read from the folio - and only then is this identity used, for the
length of one document operation.

Everything below is idempotent: `after_install`, `after_migrate` and repeated
migrates converge on the same state and create no duplicates.

**How the permission is granted, and why it matters (16.7.5-R1C).** Through
`frappe.permissions.add_permission`, never by inserting a `Custom DocPerm` row
directly. Frappe replaces a DocType's entire permission list once any Custom
DocPerm exists for it, so a bare insert does not add a grant - it becomes the
whole grant set and silently revokes every standard ERPNext permission on that
DocType, for every role. This module did exactly that until R1C, and it cost
122 grants on four DocTypes. `add_permission` copies the standard rows into
Custom DocPerm first, which is the difference between adding a grant and
deleting a permission model.

It is not, however, the difference between adding a grant and *replacing* one.
`add_permission` still leaves Custom DocPerm populated for these four DocTypes
permanently, so `Meta.set_custom_permissions` will keep preferring the snapshot
and a future ERPNext release that changes their shipped permissions will have no
effect on this site. That is inherent to the only supported API for the job, and
it is enormously better than deleting 122 grants - but it is a snapshot, not a
passthrough, and `tests/test_posting_service_permissions.py` exists partly as the
drift detector for it.
"""

import frappe

#: The role carrying the one permission ERPNext's posting path needs.
POSTING_SERVICE_ROLE = "Hospitality Posting Service"

#: The identity itself. Not a person, and not signed in to.
#:
#: `.invalid` is the RFC 2606 reserved TLD: it is guaranteed never to resolve,
#: so this address can never receive mail or be mistaken for a real mailbox.
#: Frappe requires a syntactically valid address, and this is the honest way to
#: give it one.
POSTING_SERVICE_USER = "hospitality.posting.service@hospitality-pms.invalid"

#: Exactly what the validated call path was observed to require - read only,
#: each entry earned by a reproduced failure rather than granted in advance.
#: Extending this list is a security decision and needs the same evidence:
#: run the posting flow, watch it refuse, and record which call refused.
#:
#: * `Sales Invoice` - `PaymentEntry.validate` calls `set_missing_ref_details`,
#:   whose `get_reference_details` reads the invoice being allocated against.
#: * `Account` - `get_party_account` runs `frappe.has_permission("Account", ...)`
#:   on the receivable it resolves.
#: * `Item` - building the Sales Invoice calls `set_missing_item_details`,
#:   whose `get_item_details` does `doc.check_permission()` on the item.
#: * `Customer` - the Payment Entry validates its party.
#:
#: Deliberately *not* granted: `Item Price` write. ERPNext checks it while
#: building an invoice and simply skips the price update when it is absent -
#: the invoice posts correctly either way, so a write permission would be
#: bought for nothing.
#:
#: No create, write or submit anywhere: Hospitality inserts every document with
#: `ignore_permissions`, so this identity only has to satisfy ERPNext's own
#: internal *read* checks.
SERVICE_PERMISSIONS = (
	{"doctype": "Sales Invoice", "permlevel": 0, "read": 1},
	{"doctype": "Account", "permlevel": 0, "read": 1},
	{"doctype": "Item", "permlevel": 0, "read": 1},
	{"doctype": "Customer", "permlevel": 0, "read": 1},
)


def ensure_posting_service(*, repair: bool = False) -> dict:
	"""Create or correct the role, its permissions and the identity.

	`repair` is off for the `after_migrate` path and on only for the one-shot
	patch that undoes the previous implementation's damage - see
	`grant_service_permission` for why that distinction matters.
	"""
	result = {
		"role": _ensure_role(),
		"permissions": _ensure_permissions(repair=repair),
		"user": _ensure_user(),
	}

	return result


def _ensure_role() -> str:
	"""The role, with no desk access - it is not a person's role."""
	if not frappe.db.exists("Role", POSTING_SERVICE_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": POSTING_SERVICE_ROLE,
				"desk_access": 0,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)

		return "created"

	doc = frappe.get_doc("Role", POSTING_SERVICE_ROLE)

	# Only save when something actually differs, so a migrate that changes
	# nothing does not write a document version.
	if int(doc.desk_access or 0) != 0:
		doc.desk_access = 0
		doc.save(ignore_permissions=True)

		return "corrected"

	return "unchanged"


def _ensure_permissions(*, repair: bool = False) -> list[str]:
	"""The declared grants, added without destroying anybody else's.

	This function used to insert a bare `Custom DocPerm` row per DocType, on the
	reasoning recorded in its old docstring: "written as Custom DocPerm rather
	than by editing the DocType, so nothing in ERPNext core is modified and
	`bench migrate` cannot overwrite it". The first half was true. The second was
	the opposite of what happens, and the whole approach was the more invasive of
	the two options rather than the safer one (16.7.5-R1C).

	Frappe replaces a DocType's **entire** permission list as soon as any Custom
	DocPerm exists for it - `frappe/model/meta.py::Meta.set_custom_permissions`
	does `self.permissions = [Document(d) for d in custom_perms]`, and
	`permissions.get_all_perms` reads exactly that list. So a one-permission row
	did not add a grant; it became the whole grant set. Measured on this bench:
	**122** individual `(role, permlevel, ptype)` grants destroyed across the four
	DocTypes. Accounts Manager and Accounts User lost Sales Invoice and Account
	outright; Item Manager, the Stock roles, Sales User, Purchase User,
	Maintenance User and Manufacturing User lost Item; the Sales and Stock roles
	lost Customer. `install.py` calls this from `after_migrate`, so every migrate
	re-applied it.

	Frappe's own API always did the safe thing, and is now what is used - see
	`grant_service_permission`.
	"""
	applied = []

	for declared in SERVICE_PERMISSIONS:
		applied.append(
			"{doctype}: {outcome}".format(
				doctype=declared["doctype"],
				outcome=grant_service_permission(
					declared["doctype"],
					permlevel=declared["permlevel"],
					ptype="read",
					repair=repair,
				),
			)
		)

	return applied


def grant_service_permission(
	doctype: str, *, permlevel: int = 0, ptype: str = "read", repair: bool = False
) -> str:
	"""Give the posting role one permission on `doctype`, preserving all others.

	Two steps, and the order matters.

	**First, repair.** If this DocType's only Custom DocPerm rows are the posting
	service's own, they are the previous implementation's damage and the standard
	rows they displaced are restored beside them. That is done before the grant so
	an already-broken site converges on the same state as a fresh one, rather than
	staying broken because the grant it needed was already there.

	**Then, grant.** Through `frappe.permissions.add_permission`, which calls
	`setup_custom_perms(doctype)` -> `copy_perms(parent)` first: on a DocType with
	no custom rows yet, every standard DocPerm is copied into Custom DocPerm
	*before* the new row joins them, so nothing is displaced. It also returns
	early when the row already exists, which is what makes repeated migrates
	idempotent.

	Returns a short outcome word for the setup log: `created`, `unchanged`,
	`repaired` or `repaired+created`.
	"""
	from frappe.permissions import add_permission

	repaired = _restore_standard_permissions(doctype) if repair else False

	existing = frappe.db.exists(
		"Custom DocPerm",
		{"parent": doctype, "role": POSTING_SERVICE_ROLE, "permlevel": permlevel, "if_owner": 0},
	)

	if existing:
		outcome = "repaired" if repaired else "unchanged"
	else:
		add_permission(doctype, POSTING_SERVICE_ROLE, permlevel, ptype)
		outcome = "repaired+created" if repaired else "created"

	# The grant is read-only, and `add_permission` sets only the one ptype it is
	# given - but a row created by an older build, or by hand, could carry more.
	# Narrowed rather than trusted: least privilege is the property this identity
	# is defined by, and it is cheap to assert on every migrate.
	_narrow_service_row(doctype, permlevel, ptype)

	return outcome


def _restore_standard_permissions(doctype: str) -> bool:
	"""Put back the standard rows a bare insert displaced, when it is safe to.

	Safe means: every Custom DocPerm on this DocType belongs to the posting
	service role. That is the fingerprint of our own damage - the previous code
	inserted exactly one row per DocType and nothing else - and it is what the
	R1C audit found on this bench: one row per affected DocType, owner
	Administrator, created within four minutes of each other, and no other custom
	row on any of the four parents.

	If a row exists for **any other role**, this DocType's permission set is
	somebody's configuration rather than our accident - an operator's, or another
	app's, and the audit found seventeen such rows on this bench belonging to
	ERPNext's own regional VAT DocTypes. Those are left exactly alone: restoring
	"standard" rows beside a deliberate custom set would silently widen access,
	which is the same class of mistake in the other direction.

	Returns whether anything was restored, so the caller can say so.
	"""
	custom_roles = set(
		frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="role")
	)

	if not custom_roles:
		# Nothing to repair; `add_permission` will copy the standard rows itself.
		return False

	if custom_roles - {POSTING_SERVICE_ROLE}:
		# Class B/C: not ours to normalise. Reported, never rewritten.
		return False

	standard = frappe.get_all("DocPerm", filters={"parent": doctype}, fields="*")

	if not standard:
		return False

	present = {
		(row["role"], row["permlevel"], row["if_owner"])
		for row in frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype},
			fields=["role", "permlevel", "if_owner"],
		)
	}

	restored = False

	for row in standard:
		key = (row["role"], row["permlevel"], row.get("if_owner") or 0)

		if key in present:
			continue

		# Added to `present` as well as inserted. `DocPerm` is only checked for
		# duplicate `(role, permlevel, if_owner)` triples when a DocType is saved,
		# so a bad fixture or import can leave two identical standard rows - and
		# inserting both would make the *next* `add_permission` on this parent throw
		# "Only one rule allowed with the same Role, Level and If Owner" and abort
		# the migrate.
		present.add(key)

		# Copied field for field from the DocPerm, the way `copy_perms` does it,
		# so the restored grant is ERPNext's own and not an approximation of it.
		perm = frappe.new_doc("Custom DocPerm")
		perm.update(row)
		perm.parent = doctype
		perm.parenttype = "DocType"
		perm.parentfield = "permissions"

		# `update(row)` carried the DocPerm's own `name`, `owner` and `creation`
		# across. The name is harmless - `Custom DocPerm` autonames by hash, and
		# `set_new_name` discards whatever was there - but the timestamps are not:
		# `after_migrate` runs under `frappe.flags.in_migrate`, which suppresses
		# `set_user_and_timestamp`, so a restored row would otherwise present itself
		# as having been created years ago by whoever owned the ERPNext DocPerm.
		# That is exactly the forensic signal the R1C audit relied on to prove these
		# rows were ours, and a repair that erases it makes the next audit harder.
		perm.name = None
		perm.owner = frappe.session.user
		perm.creation = None
		perm.modified = None

		perm.insert(ignore_permissions=True)

		restored = True

	if restored:
		frappe.clear_cache(doctype=doctype)

	return restored


def _narrow_service_row(doctype: str, permlevel: int, ptype: str):
	"""Keep every row the service holds on this DocType to its one permission.

	Every row, not the declared one: the lookup deliberately does not filter on
	`permlevel` or `if_owner`. An older build, a hand edit or an import could have
	left a row at another permlevel, or an `if_owner=1` row beside the ordinary
	one - and a narrowing that only inspected `(declared permlevel, if_owner=0)`
	would leave such a row untouched while reporting that the identity holds read
	and nothing else. `if_owner=1` in particular would give the posting identity
	write on any document it owns, which is every document it creates.

	Permission fieldnames come from the DocType's own meta rather than a tuple
	maintained here, so a permission type this app has never heard of - `import`
	and `mask` exist today - cannot be granted through a gap in a hand-written
	list. `read`'s counterpart matters too: `Custom DocPerm.export` defaults to
	`1`, so `add_permission`'s freshly created row arrives with `export` set and is
	narrowed here in the same uncommitted transaction.
	"""
	fields = [
		field.fieldname
		for field in frappe.get_meta("Custom DocPerm").fields
		if field.fieldtype == "Check" and field.fieldname not in ("if_owner",)
	]

	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": POSTING_SERVICE_ROLE},
		fields=["name", "permlevel", "if_owner"],
	)

	for found in rows:
		row = frappe.get_doc("Custom DocPerm", found["name"])

		# The one row the identity is entitled to keeps `ptype`; any other row it
		# holds - wrong permlevel, or owner-scoped - is stripped to nothing and
		# left in place rather than deleted, so the change is visible in the
		# permission manager instead of silently vanishing.
		entitled = int(found["permlevel"] or 0) == permlevel and not int(found["if_owner"] or 0)

		desired = {field: 0 for field in fields}
		if entitled:
			desired[ptype] = 1

		drift = {field: value for field, value in desired.items() if int(row.get(field) or 0) != value}

		if not drift:
			continue

		for field, value in drift.items():
			row.set(field, value)

		row.save(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)
	frappe.clear_cache(doctype=doctype)


def _ensure_user() -> str:
	"""The identity: enabled, no desk, no password, one role."""
	if not frappe.db.exists("User", POSTING_SERVICE_USER):
		user = frappe.new_doc("User")
		user.email = POSTING_SERVICE_USER
		user.first_name = "Hospitality Posting Service"
		user.user_type = "System User"
		user.enabled = 1
		# Nobody signs in as this: no welcome mail, no password, and the role
		# it holds carries no desk access.
		user.send_welcome_email = 0
		user.flags.ignore_permissions = True
		user.flags.no_welcome_mail = True
		user.append("roles", {"role": POSTING_SERVICE_ROLE})
		user.insert(ignore_permissions=True)

		return "created"

	user = frappe.get_doc("User", POSTING_SERVICE_USER)
	dirty = False

	if not user.enabled:
		user.enabled = 1
		dirty = True

	held = {row.role for row in user.roles}

	if POSTING_SERVICE_ROLE not in held:
		user.append("roles", {"role": POSTING_SERVICE_ROLE})
		dirty = True

	# The identity must not accumulate authority over time. Anything beyond
	# its own role is removed - including roles an operator may have added by
	# hand, which is exactly the drift this guards against.
	surplus = held - {POSTING_SERVICE_ROLE}

	if surplus:
		user.roles = [row for row in user.roles if row.role == POSTING_SERVICE_ROLE]
		dirty = True

	if dirty:
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)

		return "corrected"

	return "unchanged"
