"""Small JIT-focused benchmark driver.

This is intentionally lightweight: it runs a few hot-loop microbenchmarks under
both ``PYTHON_JIT=0`` and ``PYTHON_JIT=1`` for a supplied Python executable.
Use it after building with ``--enable-experimental-jit`` or
``--enable-experimental-jit=interpreter`` to confirm that a proposed JIT change
moves execution time in the expected direction before running larger suites.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


BENCHMARK = r'''
import json
import statistics
import sys
import time


def loop_add(n):
    total = 0
    for i in range(n):
        total += i
    return total


def loop_attr(n):
    class C:
        def __init__(self):
            self.x = 1
    obj = C()
    total = 0
    for _ in range(n):
        total += obj.x
    return total


def loop_call(n):
    def f(x):
        return x + 1
    total = 0
    for i in range(n):
        total += f(i)
    return total


def run(fn, n, warmups, samples):
    for _ in range(warmups):
        fn(10_000)
    timings = []
    for _ in range(samples):
        start = time.perf_counter()
        fn(n)
        timings.append(time.perf_counter() - start)
    return {
        "best": min(timings),
        "mean": statistics.mean(timings),
        "stdev": statistics.pstdev(timings),
    }


jit = getattr(sys, "_jit", None)
print(json.dumps({
    "jit_available": bool(jit and jit.is_available()),
    "jit_enabled": bool(jit and jit.is_enabled()),
    "benchmarks": {
        "loop_add": run(loop_add, 3_000_000, 5, 7),
        "loop_attr": run(loop_attr, 3_000_000, 5, 7),
        "loop_call": run(loop_call, 2_000_000, 5, 7),
    },
}, sort_keys=True))
'''


def run_once(python: str, jit: bool) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHON_JIT"] = "1" if jit else "0"
    proc = subprocess.run(
        [python, "-c", BENCHMARK],
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    return json.loads(proc.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare hot-loop timings with PYTHON_JIT disabled/enabled."
    )
    parser.add_argument("python", nargs="?", default=sys.executable)
    args = parser.parse_args()

    disabled = run_once(args.python, False)
    enabled = run_once(args.python, True)
    print(f"Python: {args.python}")
    print(f"JIT available: {enabled['jit_available']}")
    print("benchmark          jit-off best   jit-on best    speedup")
    for name, off in disabled["benchmarks"].items():
        on = enabled["benchmarks"][name]
        speedup = off["best"] / on["best"]
        print(f"{name:16} {off['best']:11.6f} {on['best']:11.6f} {speedup:9.3f}x")


if __name__ == "__main__":
    main()
