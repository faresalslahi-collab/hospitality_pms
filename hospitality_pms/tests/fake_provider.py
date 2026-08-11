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
from hospitality_pms.services.exceptions import IntegrationAmbiguousError, IntegrationError

#: Environment variable naming the file every call is appended to. Set by the
#: test before the workers are spawned, and inherited by them.
CALL_LOG_ENV = "HPMS_FAKE_PROVIDER_LOG"

#: How the adapter should behave on the next call. An environment variable so a
#: worker process inherits it, which a module-level flag could not do.
MODE_ENV = "HPMS_FAKE_PROVIDER_MODE"

#: Everything worked and the answer came back.
MODE_OK = "ok"

#: The provider refused outright. Nothing happened at the far end, so a retry
#: is safe - the "explicit failure" case.
MODE_REFUSE = "refuse"

#: The provider *did* the work and the reply was lost. This is the dangerous
#: one: the call is recorded, so the test can count it, and then the adapter
#: raises as though nothing came back.
MODE_TIMEOUT_AFTER_APPLY = "timeout_after_apply"

#: The request never reached the provider. Recorded as no call at all, but the
#: caller still cannot tell the difference - which is the point.
MODE_TIMEOUT_BEFORE_APPLY = "timeout_before_apply"


def set_mode(mode: str):
	os.environ[MODE_ENV] = mode


def current_mode() -> str:
	return os.environ.get(MODE_ENV, MODE_OK)


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

	set_mode(MODE_OK)


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
		mode = current_mode()
		applied = mode in (MODE_OK, MODE_TIMEOUT_AFTER_APPLY)

		if mode != MODE_TIMEOUT_BEFORE_APPLY:
			record(
				{
					"operation": "initiate_payment",
					"amount": float(amount),
					"idempotency_key": idempotency_key,
					"reference": reference,
					"applied": applied,
				}
			)

		if mode == MODE_REFUSE:
			raise IntegrationError("fake provider refused the payment")

		if mode in (MODE_TIMEOUT_AFTER_APPLY, MODE_TIMEOUT_BEFORE_APPLY):
			raise IntegrationAmbiguousError("fake provider timed out; outcome unknown")

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

	#: The recording adapter can say what became of a key, because it wrote
	#: every call down. A real gateway with an idempotency-key lookup is the
	#: same shape.
	supports_idempotent_replay = True

	def get_operation_status(self, idempotency_key: str) -> PaymentResult | None:
		"""What the provider did under this key, from its own record of calls.

		This is what lets a timed-out refund be resolved without asking the
		provider to do it again.
		"""
		applied = [
			call
			for call in calls()
			if call.get("idempotency_key") == idempotency_key and call.get("applied")
		]

		if not applied:
			return None

		return PaymentResult(
			success=True,
			status="Refunded" if applied[0]["operation"] == "refund" else "Captured",
			provider_reference=f"FAKE-{applied[0]['operation'].upper()}-{idempotency_key}",
			amount=float(applied[0]["amount"]),
			provider_status="found",
		)

	def refund(self, provider_reference, amount, idempotency_key, *, reason=None) -> PaymentResult:
		"""The call the over-refund tests count.

		`applied` records whether the money actually moved, which is the one
		thing the caller cannot know when the reply is lost - and the thing the
		tests must be able to check.
		"""
		mode = current_mode()
		applied = mode in (MODE_OK, MODE_TIMEOUT_AFTER_APPLY)

		if mode != MODE_TIMEOUT_BEFORE_APPLY:
			record(
				{
					"operation": "refund",
					"amount": float(amount),
					"idempotency_key": idempotency_key,
					"provider_reference": provider_reference,
					"reason": reason,
					"applied": applied,
				}
			)

		if mode == MODE_REFUSE:
			raise IntegrationError("fake provider refused the refund")

		if mode in (MODE_TIMEOUT_AFTER_APPLY, MODE_TIMEOUT_BEFORE_APPLY):
			raise IntegrationAmbiguousError("fake provider timed out; outcome unknown")

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
