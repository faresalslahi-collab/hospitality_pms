"""Hospitality PMS domain services.

This package holds the authoritative business logic of the product. One module
per domain, named after the service in SAD section 6 (`availability.py`,
`rates.py`, `reservations.py`, ...).

Callers - whitelisted APIs, Desk document hooks, background jobs, Night Audit
and integration adapters - all go through these functions, so a rule is written
once and enforced everywhere (Master Prompt section 6).

Services must not import Vue-facing serialisation helpers, and must not assume
an HTTP request exists.
"""
