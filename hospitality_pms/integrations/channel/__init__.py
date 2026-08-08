"""Channel adapters.

`ChannelService` never imports a concrete adapter. It calls `get_adapter(channel)`
and talks to the interface, so adding a real vendor adapter - if Booking.com,
Expedia, Agoda or Airbnb ever needs behaviour the neutral protocol cannot
express - is a new module here plus a registry entry, not a change to any
domain service (SAD section 10).
"""

import frappe
from frappe import _

from hospitality_pms.services.exceptions import ConfigurationError, throw

CHANNEL_DOCTYPE = "Hospitality Channel"

#: `Hospitality Channel.provider` -> adapter class path. Every provider maps to
#: the neutral `GenericChannelAdapter` today (HPMS-DEC-018): the connections
#: differ only by configuration (base URL, hotel code, credentials, room
#: mapping), not by code. A vendor whose real API needs its own adapter slots
#: in here - `hospitality_pms.integrations.channel.booking_com.BookingComAdapter`,
#: say - without touching `ChannelService` or any other domain service.
ADAPTERS = {
	"Booking.com": "hospitality_pms.integrations.channel.generic.GenericChannelAdapter",
	"Expedia": "hospitality_pms.integrations.channel.generic.GenericChannelAdapter",
	"Agoda": "hospitality_pms.integrations.channel.generic.GenericChannelAdapter",
	"Airbnb": "hospitality_pms.integrations.channel.generic.GenericChannelAdapter",
	"Generic Channel Manager": "hospitality_pms.integrations.channel.generic.GenericChannelAdapter",
	"Other": "hospitality_pms.integrations.channel.generic.GenericChannelAdapter",
}


def get_adapter(channel: str):
	"""Instantiate the adapter configured for a channel row."""
	config = frappe.get_cached_doc(CHANNEL_DOCTYPE, channel)

	path = ADAPTERS.get(config.provider)

	if not path:
		throw(
			_("No adapter is registered for channel provider {0}.").format(config.provider),
			exc=ConfigurationError,
		)

	adapter_class = frappe.get_attr(path)

	return adapter_class(config)
