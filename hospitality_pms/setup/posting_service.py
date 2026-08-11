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


def ensure_posting_service() -> dict:
	"""Create or correct the role, its permissions and the identity."""
	result = {
		"role": _ensure_role(),
		"permissions": _ensure_permissions(),
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


def _ensure_permissions() -> list[str]:
	"""One Custom DocPerm per declared permission, and no more.

	Written as Custom DocPerm rather than by editing the DocType, so nothing
	in ERPNext core is modified and `bench migrate` cannot overwrite it.
	"""
	applied = []

	for declared in SERVICE_PERMISSIONS:
		doctype = declared["doctype"]
		existing = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": doctype, "role": POSTING_SERVICE_ROLE, "permlevel": declared["permlevel"]},
			"name",
		)

		if existing:
			applied.append(f"{doctype}: unchanged")
			continue

		perm = frappe.new_doc("Custom DocPerm")
		perm.parent = doctype
		perm.parenttype = "DocType"
		perm.parentfield = "permissions"
		perm.role = POSTING_SERVICE_ROLE
		perm.permlevel = declared["permlevel"]

		# Everything not declared stays off. Spelled out rather than left to
		# defaults so the grant is legible in the source.
		perm.read = declared.get("read", 0)
		perm.write = 0
		perm.create = 0
		perm.delete = 0
		perm.submit = 0
		perm.cancel = 0
		perm.amend = 0
		perm.report = 0
		perm.export = 0
		perm.share = 0
		perm.print = 0
		perm.email = 0

		perm.insert(ignore_permissions=True)
		applied.append(f"{doctype}: created")

	return applied


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
