"""A two-process harness for tests that must race genuinely.

Why processes and not threads
-----------------------------
The defects this harness exists to catch are properties of *database
transactions*, not of Python. Frappe keeps one database connection per process
in `frappe.local`, so two threads in one process share a connection, share a
transaction, and therefore share a snapshot - the exact thing under test would
be absent. A sequential simulation is worse still: it passes against code that
is broken in production.

So each worker is a real OS process with its own connection, its own
transaction and its own REPEATABLE-READ snapshot, and the two are choreographed
through a file barrier.

Writing a worker
----------------
A worker is a module-level function that takes a `barrier` keyword argument and
whatever else the test passes it. It runs inside its own Frappe context and is
responsible for its own `frappe.db.commit()` - which is the point, because
*when* it commits is usually what the test is about.

    def _worker(barrier, account):
        barrier.wait("go")
        ...
        frappe.db.commit()
        return {"credit_used": ...}

    results = run_workers([
        Worker("hospitality_pms.tests.test_locking._worker", {"account": name}),
        ...
    ])

`run_workers` returns one result dict per worker, in the order given:

    {"status": "committed", "result": <return value>}
    {"status": "failed", "error": "ExceptionType: message", "traceback": "..."}

The caller must commit its fixtures before spawning workers - a separate
process cannot see an uncommitted transaction - and must clean them up itself,
because a worker's commit is not covered by the test case's rollback.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import frappe

#: How long a worker may run before the harness gives up on it. Generous: a
#: worker that is *supposed* to block on a row lock is doing its job.
DEFAULT_TIMEOUT = 180

#: How long `Barrier.wait` blocks before deciding the other side is never
#: coming. Shorter than DEFAULT_TIMEOUT so a stuck barrier reports itself as a
#: barrier problem rather than as an opaque harness timeout.
BARRIER_TIMEOUT = 60

#: Poll interval for the barrier. Short enough not to distort the timing the
#: tests depend on, long enough not to spin a core.
POLL_SECONDS = 0.02


@dataclass
class Worker:
	"""One process to run: a dotted path to a function, and its arguments."""

	path: str
	kwargs: dict = field(default_factory=dict)
	user: str = "Administrator"


class Barrier:
	"""Cross-process signalling through files in a shared directory.

	A file system is used rather than a socket or a pipe because it needs no
	setup, no teardown and no ordering: a signal that arrives before the other
	side waits for it is still there when it does.
	"""

	def __init__(self, path: str):
		self.path = Path(path)
		self.path.mkdir(parents=True, exist_ok=True)

	def signal(self, name: str, value=None):
		"""Raise a flag, optionally carrying a JSON payload.

		Written to a temporary file and renamed, because rename is atomic: a
		waiter can never observe a half-written signal.
		"""
		target = self.path / f"{name}.json"
		staging = self.path / f".{name}.{os.getpid()}.tmp"
		staging.write_text(json.dumps(value))
		staging.replace(target)

	def is_set(self, name: str) -> bool:
		return (self.path / f"{name}.json").exists()

	def read(self, name: str):
		return json.loads((self.path / f"{name}.json").read_text())

	def wait(self, name: str, timeout: float = BARRIER_TIMEOUT):
		"""Block until another worker signals `name`. Returns its payload."""
		deadline = time.monotonic() + timeout

		while time.monotonic() < deadline:
			if self.is_set(name):
				return self.read(name)
			time.sleep(POLL_SECONDS)

		raise TimeoutError(f"barrier {name!r} was never signalled within {timeout}s")


# The bootstrap each worker process runs. It is deliberately tiny: everything
# interesting lives in the worker function, which is ordinary importable app
# code and so can be read, linted and debugged like any other module.
_BOOTSTRAP = """
import json, sys, traceback

import frappe

spec = json.loads(sys.argv[1])

frappe.init(site=spec["site"], sites_path=spec["sites_path"])
frappe.connect()

try:
    frappe.set_user(spec["user"])

    from hospitality_pms.tests.concurrency import Barrier

    worker = frappe.get_attr(spec["path"])
    result = worker(barrier=Barrier(spec["barrier"]), **spec["kwargs"])

    # The worker owns its own commit; anything it left open is its intent to
    # discard, not the harness's to guess at.
    outcome = {"status": "committed", "result": result}
except Exception as exc:
    frappe.db.rollback()
    outcome = {
        "status": "failed",
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
    }
finally:
    frappe.destroy()

sys.stdout.write("<<<HPMS>>>" + json.dumps(outcome, default=str))
"""


def run_workers(
	workers: list[Worker], *, timeout: int = DEFAULT_TIMEOUT, barrier_dir: str | None = None
) -> list[dict]:
	"""Run every worker concurrently in its own process and collect the results.

	Results come back in the order the workers were given, so a test can name
	them positionally without having to correlate on content.
	"""
	site = frappe.local.site
	sites_path = os.path.abspath(frappe.local.sites_path)

	with tempfile.TemporaryDirectory(prefix="hpms-race-") as scratch:
		barrier = barrier_dir or os.path.join(scratch, "barrier")
		Path(barrier).mkdir(parents=True, exist_ok=True)

		processes = []

		for worker in workers:
			spec = {
				"site": site,
				"sites_path": sites_path,
				"path": worker.path,
				"kwargs": worker.kwargs,
				"user": worker.user,
				"barrier": barrier,
			}

			processes.append(
				subprocess.Popen(
					[sys.executable, "-c", _BOOTSTRAP, json.dumps(spec)],
					stdout=subprocess.PIPE,
					stderr=subprocess.PIPE,
					cwd=sites_path,
					text=True,
				)
			)

		results = [_collect(process, timeout) for process in processes]

	# The caller is about to assert on what the workers committed. Its own
	# transaction is still holding the REPEATABLE-READ snapshot it opened
	# before the race, and would answer every one of those assertions from
	# before the race - N1, reappearing inside the test that exists to catch
	# it. Ending the transaction here gives the caller a current view.
	#
	# Safe to commit rather than roll back: suites must commit their fixtures
	# before spawning workers anyway, since a separate process cannot see an
	# open transaction, and they clean up through `Fixtures.teardown`.
	frappe.db.commit()

	return results


def _collect(process: subprocess.Popen, timeout: int) -> dict:
	try:
		stdout, stderr = process.communicate(timeout=timeout)
	except subprocess.TimeoutExpired:
		process.kill()
		stdout, stderr = process.communicate()
		return {"status": "timeout", "error": f"worker exceeded {timeout}s", "stderr": stderr}

	# The sentinel separates our payload from anything Frappe logged to stdout
	# on the way past, which it does freely.
	marker = stdout.rfind("<<<HPMS>>>")

	if marker == -1:
		return {
			"status": "crashed",
			"error": "worker produced no result",
			"stdout": stdout,
			"stderr": stderr,
		}

	return json.loads(stdout[marker + len("<<<HPMS>>>") :])


def assert_all_ran(results: list[dict]):
	"""Fail loudly when a worker crashed rather than merely losing its race.

	A crashed worker often still leaves the assertions downstream satisfiable
	by accident, so tests check this first.
	"""
	for index, result in enumerate(results):
		if result["status"] in ("crashed", "timeout"):
			raise AssertionError(
				f"worker {index} did not run: {result.get('error')}\n"
				f"stdout: {result.get('stdout', '')}\nstderr: {result.get('stderr', '')}"
			)
