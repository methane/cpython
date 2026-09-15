#!/usr/bin/env python3
"""Microbenchmark for the hot numeric kernel in pyperformance spectral_norm.

This is intentionally a standalone standard-library-only script.  One
operation evaluates ``eval_A()`` 676,000 times, the same number of evaluations
performed by one operation of the original benchmark with its default input.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time


SIZE = 130
PASSES = 40
EVALUATIONS = SIZE * SIZE * PASSES
EXPECTED_CHECKSUM = 409.3151805348543


def eval_A(i: int, j: int) -> float:
    return 1.0 / ((i + j) * (i + j + 1) // 2 + i + 1)


def spectral_norm_kernel() -> float:
    checksum = 0.0
    for _ in range(PASSES):
        for i in range(SIZE):
            partial_sum = 0.0
            for j in range(SIZE):
                partial_sum += eval_A(i, j)
            checksum += partial_sum
    return checksum


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loops", type=int, default=1,
                        help="kernel operations per measured value (default: 1)")
    parser.add_argument("--warmups", type=int, default=3,
                        help="unmeasured warmup values (default: 3)")
    parser.add_argument("--values", type=int, default=10,
                        help="measured values (default: 10)")
    parser.add_argument("--json", action="store_true",
                        help="write machine-readable output")
    args = parser.parse_args()
    if args.loops < 1:
        parser.error("--loops must be positive")
    if args.warmups < 0:
        parser.error("--warmups must be non-negative")
    if args.values < 1:
        parser.error("--values must be positive")
    return args


def run_loops(loops: int) -> float:
    result = 0.0
    for _ in range(loops):
        result = spectral_norm_kernel()
    return result


def check_result(result: float) -> None:
    if not math.isclose(result, EXPECTED_CHECKSUM, rel_tol=1e-12):
        raise RuntimeError(
            f"invalid checksum: got {result!r}, expected {EXPECTED_CHECKSUM!r}"
        )


def format_duration(seconds: float) -> str:
    if seconds >= 1.0:
        return f"{seconds:.6f} sec"
    return f"{seconds * 1_000:.3f} ms"


def main() -> None:
    args = parse_args()
    for _ in range(args.warmups):
        check_result(run_loops(args.loops))

    samples = []
    result = 0.0
    for _ in range(args.values):
        start = time.perf_counter()
        result = run_loops(args.loops)
        elapsed = time.perf_counter() - start
        check_result(result)
        samples.append(elapsed / args.loops)

    output = {
        "benchmark": "spectral_norm_kernel",
        "runtime": f"Python {platform.python_version()} "
                   f"({platform.python_implementation()})",
        "eval_A_calls_per_operation": EVALUATIONS,
        "loops": args.loops,
        "warmups": args.warmups,
        "values": args.values,
        "median_seconds": statistics.median(samples),
        "minimum_seconds": min(samples),
        "samples_seconds": samples,
        "checksum": result,
    }
    if args.json:
        print(json.dumps(output, indent=2))
        return

    print(output["runtime"])
    print(f"eval_A calls: {EVALUATIONS:,} per operation")
    print(f"median: {format_duration(output['median_seconds'])}")
    print(f"minimum: {format_duration(output['minimum_seconds'])}")
    print("values: " + ", ".join(format_duration(value) for value in samples))


if __name__ == "__main__":
    main()
