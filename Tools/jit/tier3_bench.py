"""Measure the executor-integrated range kernel in the current process."""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import sysconfig
import time

import _opcode


def sum_from(n, initial):
    total = initial
    for item in range(n):
        total += item
    return total


def executors():
    for offset in range(0, len(sum_from.__code__.co_code), 2):
        try:
            yield offset, _opcode.get_executor(sum_from.__code__, offset)
        except (RuntimeError, ValueError):
            pass


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def tier3_executor():
    fallback = None
    for offset, candidate in executors():
        if fallback is None:
            fallback = (offset, candidate)
        if candidate.get_tier3_stats()["entries"]:
            return offset, candidate
    return fallback


def configuration():
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "python": sys.version,
        "commit": commit,
        "compiler": platform.python_compiler(),
        "architecture": platform.machine(),
        "configure_args": sysconfig.get_config_var("CONFIG_ARGS"),
        "jit_available": sys._jit.is_available(),
        "jit_enabled": sys._jit.is_enabled(),
        "tier3_setting": os.environ.get("PYTHON_TIER3_JIT"),
        "tier3_budget": os.environ.get("PYTHON_TIER3_BUDGET"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--initial", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=3000)
    parser.add_argument("--repeat", type=positive, default=9)
    parser.add_argument("--loops", type=positive, default=10000)
    args = parser.parse_args()

    expected = args.initial + sum(range(args.n))
    # Record the supported whole-loop trace from a compact accumulator before
    # measuring entry from a potentially non-compact exact int.
    for _ in range(args.warmup):
        sum_from(min(args.n, 1000), 0)
    for _ in range(args.warmup):
        assert sum_from(args.n, args.initial) == expected

    selected = tier3_executor()
    samples = []
    measurements = []
    for _ in range(args.repeat):
        selected = tier3_executor()
        before = selected[1].get_tier3_stats() if selected else None
        start = time.perf_counter_ns()
        for _ in range(args.loops):
            result = sum_from(args.n, args.initial)
        elapsed = (time.perf_counter_ns() - start) / args.loops
        selected_after = tier3_executor()
        stable = (
            selected is not None
            and selected_after is not None
            and selected[1] is selected_after[1]
        )
        after = selected[1].get_tier3_stats() if stable else None
        delta = (
            {key: after[key] - before[key] for key in before}
            if stable
            else None
        )
        measurements.append(
            {
                "elapsed_ns": elapsed,
                "status": "stable"
                if stable
                else ("executor replaced" if selected else "unavailable"),
                "tier3_delta": delta,
            }
        )
        if stable:
            samples.append(elapsed)
    if result != expected:
        raise AssertionError((result, expected))

    stable_measurements = [
        item for item in measurements if item["status"] == "stable"
    ]
    stable = bool(stable_measurements)
    try:
        native_code_verified = (
            stable and selected[1].get_jit_code() is not None
        )
    except RuntimeError:
        native_code_verified = False
    delta = (
        {
            key: sum(item["tier3_delta"][key] for item in stable_measurements)
            for key in stable_measurements[0]["tier3_delta"]
        }
        if stable
        else None
    )
    entered = delta is not None and delta["entries"] > 0
    processed = delta["iterations"] if entered else 0
    requested = args.n * args.loops * len(samples)
    print(
        json.dumps(
            {
                "configuration": configuration(),
                "workload": vars(args),
                "result": result,
                "expected": expected,
                "median_ns": statistics.median(samples) if samples else None,
                "samples_ns": samples,
                "measurements": measurements,
                "executor_offset": selected[0] if selected else None,
                "tier3_status": "entered"
                if entered
                else (
                    "executor replaced"
                    if selected and not stable
                    else ("not entered" if selected else "unavailable")
                ),
                "tier3_delta": delta,
                "kernel_iterations": processed,
                "requested_iterations": requested,
                "kernel_fraction": processed / requested if requested else 0.0,
                "native_code_verified": native_code_verified,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
