"""Scheduled work.

Each task runs for every active property and is defensive by design: one
property's failure must not stop the others, because these run unattended and a
silent halt is indistinguishable from nothing needing done.
"""

import frappe

from hospitality_pms.services.property import get_active_properties


def _for_each_property(label: str, fn):
	"""Run a job per active property, logging failures without aborting the rest."""
	results = []

	for property_name in get_active_properties():
		try:
			results.append({"property": property_name, "result": fn(property_name)})
		except Exception:  # noqa: BLE001
			frappe.log_error(
				title=f"Hospitality PMS scheduled task failed: {label}",
				message=f"Property {property_name}\n\n{frappe.get_traceback()}",
			)

	return results


def sweep_guest_service_sla():
	"""Escalate guest requests past their due time."""
	from hospitality_pms.services.guest_services import sweep_sla

	return _for_each_property("guest service SLA sweep", sweep_sla)


def sync_channels():
	"""Push availability to every active channel."""
	from hospitality_pms.services.channel import sync_all

	return _for_each_property("channel sync", sync_all)


def retry_failed_integrations():
	"""Work the integration failure queue with backoff."""
	from hospitality_pms.services.payments import retry_failed

	return _for_each_property("integration failure retry", retry_failed)
