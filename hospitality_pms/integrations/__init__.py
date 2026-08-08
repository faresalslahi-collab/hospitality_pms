"""External provider adapters.

Provider specific code lives only in this package, behind a stable interface
per provider category: payment, channel manager, door lock, ID scanner,
messaging and regulatory/e-invoicing (SAD section 10).

Core reservation, stay and folio services must never import a concrete
provider. They depend on the interface, and the active provider is resolved
from configuration at runtime.

Every outbound call and inbound callback is logged and idempotent
(HPMS-DEC-031, HPMS-DEC-032).
"""
