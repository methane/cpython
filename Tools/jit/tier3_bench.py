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


def sum_squares_from(n, initial):
    total = initial
    for item in range(n):
        total += item * item
    return total


WORKLOADS = {"sum": sum_from, "squares": sum_squares_from}


def executors(function):
    for offset in range(0, len(function.__code__.co_code), 2):
        try:
            yield offset, _opcode.get_executor(function.__code__, offset)
        except (RuntimeError, ValueError):
            pass


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def measure_sample(function, n, initial, expected, loops, lookup=None):
    """Measure calls made while one executor remains selected.

    Executor-derived evidence is deliberately kept on the sample that observed
    it.  In particular, callers must not combine an old stable sample with a
    later lookup that returned no executor or a replacement.
    """
    if lookup is None:
        lookup = tier3_executor
    selected = lookup(function)
    before = selected[1].get_tier3_stats() if selected else None
    start = time.perf_counter_ns()
    for _ in range(loops):
        result = function(n, initial)
        if result != expected:
            raise AssertionError((result, expected))
    elapsed = (time.perf_counter_ns() - start) / loops
    selected_after = lookup(function)
    stable = (
        selected is not None
        and selected_after is not None
        and selected[1] is selected_after[1]
    )
    after = selected[1].get_tier3_stats() if stable else None
    delta = {key: after[key] - before[key] for key in before} if stable else None
    native_code_bytes = 0
    if stable:
        try:
            native_code = selected[1].get_jit_code()
        except RuntimeError:
            native_code = None
        native_code_bytes = len(native_code) if native_code else 0
    return {
        "elapsed_ns": elapsed,
        "status": (
            "stable"
            if stable
            else (
                "executor replaced"
                if selected is not None and selected_after is not None
                else "unavailable"
            )
        ),
        "tier3_delta": delta,
        "executor_offset": selected[0] if stable else None,
        "executor_identity": id(selected[1]) if stable else None,
        "native_code_bytes": native_code_bytes,
    }


def tier3_executor(function):
    fallback = None
    for offset, candidate in executors(function):
        if fallback is None:
            fallback = (offset, candidate)
        stats = candidate.get_tier3_stats()
        if stats["entries"] or stats["native_entries"] or stats["resident_entries"]:
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
    try:
        tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"],
            text=True,
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
        ).strip()
        tracked_dirty = (
            subprocess.run(
                ["git", "diff", "--quiet"], cwd=os.path.dirname(__file__)
            ).returncode
            != 0
        )
    except (OSError, subprocess.CalledProcessError):
        tree = None
        tracked_dirty = None
    return {
        "python": sys.version,
        "commit": commit,
        "tree": tree,
        "tracked_dirty": tracked_dirty,
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
    parser.add_argument("--workload", choices=WORKLOADS, default="sum")
    parser.add_argument(
        "--training-profile",
        choices=("same-input", "compact-seeded"),
        default="same-input",
    )
    parser.add_argument("--warmup", type=positive, default=3000)
    parser.add_argument("--repeat", type=positive, default=9)
    parser.add_argument("--loops", type=positive, default=10000)
    args = parser.parse_args()
    build_manifest = configuration()

    function = WORKLOADS[args.workload]
    expected = args.initial + sum(
        item * item if args.workload == "squares" else item for item in range(args.n)
    )
    if args.training_profile == "compact-seeded":
        for _ in range(args.warmup):
            function(min(args.n, 1000), 0)
    for _ in range(args.warmup):
        assert function(args.n, args.initial) == expected

    samples = []
    measurements = []
    for _ in range(args.repeat):
        measurement = measure_sample(
            function, args.n, args.initial, expected, args.loops
        )
        measurements.append(measurement)
        if measurement["status"] == "stable":
            samples.append(measurement["elapsed_ns"])

    stable_measurements = [item for item in measurements if item["status"] == "stable"]
    stable = bool(stable_measurements)
    native_code_bytes = max(
        (item["native_code_bytes"] for item in stable_measurements), default=0
    )
    native_code_verified = native_code_bytes > 0
    delta = (
        {
            key: sum(item["tier3_delta"][key] for item in stable_measurements)
            for key in stable_measurements[0]["tier3_delta"]
        }
        if stable
        else None
    )
    entered = delta is not None and (
        delta["entries"] > 0
        or delta["native_entries"] > 0
        or delta["resident_entries"] > 0
    )
    processed = (
        delta["iterations"] + delta["native_iterations"] + delta["resident_iterations"]
        if entered
        else 0
    )
    requested = max(args.n, 0) * args.loops * len(samples)
    rejection_reason = None
    if not entered:
        if not stable:
            rejection_reason = "executor unavailable or replaced during measurement"
        elif args.training_profile == "same-input" and abs(args.initial) >= 2**30:
            rejection_reason = (
                "no resident progress from the noncompact-only trace; "
                "the current builder requires compact arithmetic facts"
            )
        else:
            rejection_reason = "stable executor made no Tier-3 range progress"
    print(
        json.dumps(
            {
                "configuration": build_manifest,
                "workload": vars(args),
                "callable": function.__name__,
                "result": expected,
                "expected": expected,
                "median_ns": statistics.median(samples) if samples else None,
                "samples_ns": samples,
                "measurements": measurements,
                "executor_offset": (
                    stable_measurements[-1]["executor_offset"] if stable else None
                ),
                "executor_identity": (
                    stable_measurements[-1]["executor_identity"] if stable else None
                ),
                "tier3_status": (
                    "entered"
                    if entered
                    else (
                        "zero native progress" if stable else "unavailable or replaced"
                    )
                ),
                "tier3_delta": delta,
                "rejection_reason": rejection_reason,
                "kernel_iterations": processed,
                "requested_iterations": requested,
                "kernel_fraction": processed / requested if requested else 0.0,
                "native_code_verified": native_code_verified,
                "native_code_bytes": native_code_bytes,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
