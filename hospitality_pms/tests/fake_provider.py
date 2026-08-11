"""A payment adapter that contacts nothing and counts everything.

No test in this repository may reach a real gateway, and the refund tests need
something stronger than "no network call happened": they have to count the
calls made by *two separate processes* and prove the total never exceeds the
captured amount. A counter in memory cannot do that, so every call is appended
to a shared file as one JSON line.

Registered at runtime by the code that needs it:

    from hospitality_pms.integrations.payments import ADAPTERS
    ADAPTERS["Manual"] = "hospitality_pms.tests.fake_provider.RecordingAdapter"

Runtime rather than a permanent registry entry, so no test-only provider ships
in the production adapter table. Each worker process registers it for itself.
"""

import json
import os
from pathlib import Path

from hospitality_pms.integrations.payments.base import PaymentProvider, PaymentResult

#: Environment variable naming the file every call is appended to. Set by the
#: test before the workers are spawned, and inherited by them.
CALL_LOG_ENV = "HPMS_FAKE_PROVIDER_LOG"


def call_log_path() -> Path | None:
	path = os.environ.get(CALL_LOG_ENV)

	return Path(path) if path else None


def record(entry: dict):
	"""Append one call. Line-buffered append is atomic enough for this.

	Each write is a single short line opened in append mode, which the kernel
	will not interleave with another process's line at these sizes - so the
	file can be read back as one JSON object per line.
	"""
	path = call_log_path()

	if not path:
		return

	with path.open("a") as handle:
		handle.write(json.dumps({**entry, "pid": os.getpid()}) + "\n")


def calls(operation: str | None = None) -> list[dict]:
	"""Every call recorded so far, optionally of one kind."""
	path = call_log_path()

	if not path or not path.exists():
		return []

	entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

	return [e for e in entries if operation is None or e["operation"] == operation]


def reset():
	path = call_log_path()

	if path and path.exists():
		path.unlink()


class RecordingAdapter(PaymentProvider):
	"""Succeeds at everything, contacts nothing, records every call."""

	name = "Manual"

	def initiate_payment(
		self,
		amount,
		currency,
		idempotency_key,
		*,
		reference=None,
		description=None,
		return_url=None,
		metadata=None,
	) -> PaymentResult:
		record(
			{
				"operation": "initiate_payment",
				"amount": float(amount),
				"idempotency_key": idempotency_key,
				"reference": reference,
			}
		)

		return PaymentResult(
			success=True,
			status="Captured",
			provider_reference=f"FAKE-{reference or idempotency_key}",
			amount=float(amount),
			provider_status="captured",
		)

	def get_status(self, provider_reference) -> PaymentResult:
		record({"operation": "get_status", "provider_reference": provider_reference})

		return PaymentResult(
			success=True,
			status="Captured",
			provider_reference=provider_reference,
			provider_status="captured",
		)

	def refund(self, provider_reference, amount, idempotency_key, *, reason=None) -> PaymentResult:
		"""The call the over-refund tests count.

		Recorded before returning, so a call that happened is counted even if
		the caller's transaction later rolls back - which is exactly the
		provider-succeeded-database-failed case the tests need to see.
		"""
		record(
			{
				"operation": "refund",
				"amount": float(amount),
				"idempotency_key": idempotency_key,
				"provider_reference": provider_reference,
				"reason": reason,
			}
		)

		return PaymentResult(
			success=True,
			status="Refunded",
			provider_reference=f"FAKE-REFUND-{idempotency_key}",
			amount=float(amount),
			provider_status="refunded",
		)

	def verify_callback(self, payload, headers, raw_body=None) -> dict:
		record({"operation": "verify_callback"})

		return dict(payload or {})
