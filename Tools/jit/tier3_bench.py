"""Compare baseline, current JIT, and the experimental Tier-3 sidecar."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time

from _tier3_native import CompiledLoop, compile, find_executor


def sum_range(n):
    total = 0
    for i in range(n):
        total += i
    return total


def sum_squares(n):
    total = 0
    for i in range(n):
        total += i * i
    return total


BENCHMARKS = {"sum_range": sum_range, "sum_squares": sum_squares}


def _measure(function, n, loops, runs):
    samples = []
    result = None
    for _ in range(runs):
        start = time.perf_counter_ns()
        for _ in range(loops):
            result = function(n)
        samples.append((time.perf_counter_ns() - start) / loops)
    return statistics.median(samples), result


def child(mode, n, loops, warmup, runs):
    output = {"mode": mode, "benchmarks": {}}
    for name, function in BENCHMARKS.items():
        for _ in range(warmup):
            function(8)
        executor = find_executor(function)
        start = time.perf_counter_ns()
        target = compile(function, executor) if mode == "tier3" else function
        compile_ns = time.perf_counter_ns() - start
        median_ns, result = _measure(target, n, loops, runs)
        output["benchmarks"][name] = {
            "compiled": isinstance(target, CompiledLoop),
            "compile_ns": compile_ns,
            "executor_uops": len(executor) if executor is not None else None,
            "machine_code_bytes": (
                len(target.native.code) if isinstance(target, CompiledLoop) else None
            ),
            "median_ns": median_ns,
            "result": result,
        }
        if isinstance(target, CompiledLoop) and os.environ.get("PYTHON_TIER3_DUMP"):
            target.dump(f"{name}.tier3.bin")
            with open(f"{name}.tier3.ir", "w", encoding="utf-8") as dump:
                dump.write(target.native.ir + "\n")
    return output


def parent(args):
    results = []
    for mode in ("baseline", "current-jit", "tier3"):
        env = os.environ.copy()
        env["PYTHON_JIT"] = "0" if mode == "baseline" else "1"
        env["PYTHON_TIER3_JIT"] = "1" if mode == "tier3" else "0"
        command = [
            sys.executable,
            __file__,
            "--child",
            mode,
            "--n",
            str(args.n),
            "--loops",
            str(args.loops),
            "--warmup",
            str(args.warmup),
            "--runs",
            str(args.runs),
        ]
        process = subprocess.run(command, env=env, text=True, capture_output=True)
        if process.returncode:
            results.append({"mode": mode, "error": process.stderr.strip()})
        else:
            results.append(json.loads(process.stdout))
    by_mode = {item["mode"]: item for item in results}
    for benchmark in BENCHMARKS:
        times = []
        for mode in ("baseline", "current-jit", "tier3"):
            item = by_mode[mode]
            if "error" not in item:
                times.append(item["benchmarks"][benchmark]["median_ns"])
        if len(times) == 3:
            baseline = times[0]
            for mode, elapsed in zip(("baseline", "current-jit", "tier3"), times):
                by_mode[mode]["benchmarks"][benchmark]["speedup"] = baseline / elapsed
            current = times[1]
            tier3 = times[2]
            tier3_data = by_mode["tier3"]["benchmarks"][benchmark]
            tier3_data["speedup_vs_current_jit"] = current / tier3
            saving = current - tier3
            tier3_data["break_even_calls_vs_current_jit"] = (
                tier3_data["compile_ns"] / saving if saving > 0 else None
            )
            expected = by_mode["baseline"]["benchmarks"][benchmark]["result"]
            if any(
                by_mode[mode]["benchmarks"][benchmark]["result"] != expected
                for mode in ("current-jit", "tier3")
            ):
                raise RuntimeError(f"result mismatch in {benchmark}")
    valid_speedups = [
        item["benchmarks"][name].get("speedup")
        for item in results
        if "error" not in item
        for name in BENCHMARKS
        if item["mode"] == "tier3"
    ]
    return {
        "configuration": vars(args) | {"python": sys.executable},
        "results": results,
        "tier3_geomean_speedup": (
            math.prod(valid_speedups) ** (1 / len(valid_speedups))
            if valid_speedups
            else None
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=("baseline", "current-jit", "tier3"))
    parser.add_argument("--n", type=int, default=1_000)
    parser.add_argument("--loops", type=int, default=20_000)
    parser.add_argument("--warmup", type=int, default=2_000)
    parser.add_argument("--runs", type=int, default=9)
    args = parser.parse_args()
    result = (
        child(args.child, args.n, args.loops, args.warmup, args.runs)
        if args.child
        else parent(args)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
