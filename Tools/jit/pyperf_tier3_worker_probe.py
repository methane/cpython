"""Verify Tier-3 configuration and execution inside every pyperf worker."""

import os
import sys

import pyperf

from tier3_bench import sum_from, tier3_executor

EXPECTED_ENV = {"PYTHON_JIT": "1", "PYTHON_TIER3_JIT": "resident"}


def probe():
    for name, expected in EXPECTED_ENV.items():
        actual = os.environ.get(name)
        if actual != expected:
            raise RuntimeError(f"worker {name}={actual!r}, expected {expected!r}")
    if not sys._jit.is_available() or not sys._jit.is_enabled():
        raise RuntimeError("JIT is not available and enabled in the worker")

    expected = 2**40 + 1000 * 999 // 2
    for _ in range(300):
        if sum_from(1000, 2**40) != expected:
            raise AssertionError("resident-control result mismatch")
    selected = tier3_executor(sum_from)
    if selected is None or not selected[1].is_valid():
        raise RuntimeError("worker did not install a valid control executor")
    before = selected[1].get_tier3_stats()["resident_iterations"]
    result = sum_from(1000, 2**40)
    after = selected[1].get_tier3_stats()["resident_iterations"]
    if result != expected or after <= before:
        raise RuntimeError("worker control made no resident progress")


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_func("tier3_worker_probe", probe)
