"""One Night Audit per property per business date (P2-1).

Two audits for one date mean two sets of figures and two ways to close the day.
Nothing repairs existing duplicates automatically: the migration reports them
and stops, because choosing which of two audits is the real one is the hotel's
decision, not a patch's.
"""

from hospitality_pms.setup.schema import apply_night_audit_uniqueness


def execute():
	apply_night_audit_uniqueness()
