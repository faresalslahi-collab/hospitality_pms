"""Payment provider adapters.

Core reservation, stay and folio services never import a concrete provider.
They call `get_provider(property)` and talk to the interface, so adding a
provider is a new module here plus a configuration row - not a change to any
domain service (SAD section 10).

Fatora is the primary provider and Stripe the fallback (HPMS-DEC-024).
"""

import frappe
from frappe import _

from hospitality_pms.services.exceptions import ConfigurationError, throw

PROVIDER_DOCTYPE = "Hospitality Payment Provider"

#: Provider name on the configuration row -> adapter class path. A provider the
#: registry does not know is a configuration error, never a silent no-op.
ADAPTERS = {
	"Fatora": "hospitality_pms.integrations.payments.fatora.FatoraAdapter",
	"Stripe": "hospitality_pms.integrations.payments.stripe.StripeAdapter",
	"Manual": "hospitality_pms.integrations.payments.manual.ManualAdapter",
}


def get_provider_config(property_name: str, provider: str | None = None) -> str:
	"""The configured provider row to use for a property."""
	filters = {"property": property_name, "is_active": 1}

	if provider:
		filters["name"] = provider
		config = frappe.db.get_value(PROVIDER_DOCTYPE, filters, "name")

		if not config:
			throw(
				_("Payment provider {0} is not active for property {1}.").format(provider, property_name),
				exc=ConfigurationError,
			)

		return config

	config = frappe.db.get_value(PROVIDER_DOCTYPE, {**filters, "is_default": 1}, "name")

	if not config:
		config = frappe.db.get_value(PROVIDER_DOCTYPE, filters, "name")

	if not config:
		throw(
			_("Property {0} has no active payment provider configured.").format(property_name),
			exc=ConfigurationError,
		)

	return config


def get_provider(property_name: str, provider: str | None = None):
	"""Instantiate the adapter for a property's configured provider."""
	config_name = get_provider_config(property_name, provider)
	config = frappe.get_cached_doc(PROVIDER_DOCTYPE, config_name)

	path = ADAPTERS.get(config.provider)

	if not path:
		throw(
			_("No adapter is registered for payment provider {0}.").format(config.provider),
			exc=ConfigurationError,
		)

	adapter_class = frappe.get_attr(path)

	return adapter_class(config)
