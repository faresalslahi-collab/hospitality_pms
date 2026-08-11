"""Make the folio idempotency key unique per folio in the database (N5).

Until this patch, idempotency rested entirely on the service reading before it
wrote. Two concurrent posts could both read "key not seen" and both insert, and
a row created outside the service - which was possible before this release -
was never checked at all.

The patch is deliberately conservative about existing money. If the site
already holds duplicate keys it stops and reports them rather than choosing a
row to delete: which of two identical charges is the real one is a question for
the hotel's finance team, not for a migration.
"""

from hospitality_pms.setup.schema import apply_financial_idempotency_constraints


def execute():
	apply_financial_idempotency_constraints()
