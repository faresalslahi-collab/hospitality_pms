"""Idempotent site setup routines for Hospitality PMS.

Everything in this package is run from the app's `install.py` hooks
(`after_install`, `after_migrate`) and must converge to the same state
whether the site is freshly installed, re-installed, or upgraded from an
older build. Modules here never assume they run exactly once.
"""
