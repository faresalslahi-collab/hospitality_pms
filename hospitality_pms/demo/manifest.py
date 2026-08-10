"""The demo seed's record of what it created.

Two independent ways to recognise a demo record, because either one alone is a
way to delete the wrong thing:

  1. **The manifest** — a JSON file under the site's private files listing every
     document this seed inserted, by doctype and name, keyed by a stable seed
     key. It is what makes the seed idempotent (a rerun reuses what is already
     there) and what makes cleanup exact.

  2. **The marker** — the literal string ``LOCAL DEMO DATA`` written into a
     human-readable field on every record the schema gives us one on. It is what
     tells a person looking at a record in Desk where it came from.

Cleanup requires *both*: a record is only removed if the manifest claims it and
the record still carries the marker. A manifest that has drifted from the site
therefore fails safe — it skips, and says so — rather than deleting a document
someone created by hand.
"""

import json
import os

import frappe

#: Written into a text field on every seeded record. Searchable in Desk.
MARKER = "LOCAL DEMO DATA"

#: Bumped only if the manifest layout changes incompatibly.
VERSION = 1

FILENAME = "hpms_demo_manifest.json"


def marker(key: str) -> str:
	"""The marker line for one seeded record, carrying its seed key."""
	return f"{MARKER} [{key}]"


def path() -> str:
	return os.path.join(frappe.get_site_path("private", "files"), FILENAME)


def load() -> dict:
	"""The manifest for this site, or an empty one."""
	try:
		with open(path(), encoding="utf-8") as handle:
			data = json.load(handle)
	except (FileNotFoundError, json.JSONDecodeError):
		return _empty()

	if data.get("version") != VERSION:
		return _empty()

	return data


def save(data: dict):
	os.makedirs(os.path.dirname(path()), exist_ok=True)

	with open(path(), "w", encoding="utf-8") as handle:
		json.dump(data, handle, indent=1, sort_keys=True)


def _empty() -> dict:
	return {"version": VERSION, "property": None, "records": {}}


class Manifest:
	"""Seed keys to the documents they produced.

	A seed key is stable and descriptive — ``guest:04``, ``room:305``,
	``stay:d0:07`` — so a rerun can ask "did I already make this?" and get an
	answer that survives renaming, reordering and partial failures.
	"""

	def __init__(self):
		self.data = load()
		self.created = []
		self.reused = []

	@property
	def records(self) -> dict:
		return self.data.setdefault("records", {})

	def get(self, key: str) -> str | None:
		"""The document this key made, if it is still on the site."""
		entry = self.records.get(key)
		if not entry:
			return None

		if not frappe.db.exists(entry["doctype"], entry["name"]):
			# Someone deleted it by hand. Forget it rather than handing back a
			# name that will fail on the next `frappe.get_doc`.
			self.records.pop(key, None)
			return None

		return entry["name"]

	def remember(self, key: str, doctype: str, name: str, *, created: bool = True) -> str:
		self.records[key] = {"doctype": doctype, "name": name}
		(self.created if created else self.reused).append(f"{doctype} {name}")

		return name

	def note_reuse(self, doctype: str, name: str):
		self.reused.append(f"{doctype} {name}")

	def flush(self, property_name: str | None = None):
		if property_name:
			self.data["property"] = property_name

		save(self.data)

	def by_doctype(self) -> dict[str, list[str]]:
		grouped: dict[str, list[str]] = {}

		for entry in self.records.values():
			grouped.setdefault(entry["doctype"], []).append(entry["name"])

		return grouped
