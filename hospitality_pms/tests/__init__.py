"""Regression suites for Hospitality PMS.

Why the suites are here and not in the DocType folders
------------------------------------------------------
Frappe's convention is one suite per DocType, in that DocType's folder, and the
empty scaffolding for those is still in place. It cannot be used for these
tests.

`IntegrationTestCase` infers `cls.doctype` from the folder a suite sits in, and
then recursively generates test records for every link field that DocType
reaches. Every operational DocType here carries `property`, `Property` links to
`Company`, and importing ERPNext's `Company` test module builds its master data
at import time - which raises `DuplicateEntryError` on a site that already has
a company. So the moment a suite in a DocType folder grows its first test
method, it fails before that method runs, on a defect that belongs to neither
this app nor this wave.

Suites outside a DocType folder have no inferred `cls.doctype`, so no dependency
walk happens. That is the right answer for these tests anyway: they build their
own world explicitly through `tests.fixtures`, and depend on none of Frappe's
generated records.

The file names match the suites named in the Wave-1 brief.
"""
