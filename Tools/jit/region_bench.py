"""Fixed exploratory workload panel for the opt-in straight-line regions.

Run one process per mode, in rotating order and pinned to the same CPU. The
JSON includes all samples (and immediate counter deltas), cold call, warmup,
and the actual executor code. Diagnostic profiling is a separate invocation.
This is a local panel, not the pyperformance suite.
"""

import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import time

from tier3_bench import executors


def int_chain(n):
    a, b, c = 331, 173, 917
    value = 0
    for _ in range(n):
        value = a * b + c
    return value


def int_predicate(n):
    a, b, c, limit = 331, 173, 917, 60000
    value = False
    for _ in range(n):
        value = a * b + c < limit
    return value


def offset_checksum(n):
    width, header = 173, 917
    value = 0
    for index in range(n):
        value ^= index * width + header
    return value


def float_shared(n):
    a, b, c = 7.25, 3.125, 2.5
    value = 0.0
    for _ in range(n):
        value = a + b * c
    return value


def float_unique(n):
    a, b, c, d = 7.25, 3.125, 2.5, 4.25
    value = 0.0
    for _ in range(n):
        value = a * b + c * d
    return value


HEADERS = tuple(f"X-Data: {'entry-' * 60}{i}\r\n" for i in range(32))
UNICODE_LINES = tuple(f"項目{i}: {'🐍漢字' * 120}\r\n" for i in range(32))


def parse_headers(n):
    # Count payload bytes in an ASCII extension-header block, excluding CRLF.
    prefix, minimum, trim = "X-Data:", 9, 9
    total = 0
    for _ in range(n // len(HEADERS)):
        for line in HEADERS:
            if line.startswith(prefix) and len(line) >= minimum:
                total += len(line) - trim
    return total


def parse_unicode(n):
    suffix, trim = "\r\n", 2
    total = 0
    for _ in range(n // len(UNICODE_LINES)):
        for line in UNICODE_LINES:
            if line.endswith(suffix):
                total += len(line) - trim
    return total


def dict_control(n):
    values = {str(i): i for i in range(32)}
    total = 0
    for _ in range(n // 32):
        for key in values:
            total += values.get(key, -1)
    return total


def json_control(n):
    value = {"name": "example", "items": list(range(8)), "valid": True}
    result = None
    for _ in range(n // 128):
        result = json.loads(json.dumps(value))
    return result


def template_control(n):
    template = "<p>{name}: {value}</p>"
    value = ""
    for i in range(n):
        value = template.format(name="entry", value=i)
    return value


WORKLOADS = {
    f.__name__: f
    for f in (
        int_chain,
        int_predicate,
        offset_checksum,
        float_shared,
        float_unique,
        parse_headers,
        parse_unicode,
        dict_control,
        json_control,
        template_control,
    )
}


def stats(selected):
    result = {}
    for _, ex in selected:
        if hasattr(ex, "get_region_stats"):
            for key, value in ex.get_region_stats().items():
                result[key] = result.get(key, 0) + value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--n", type=int, default=65536)
    parser.add_argument("--samples", type=int, default=9)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--allow-interpreter", action="store_true")
    args = parser.parse_args()
    assert sys._jit.is_available() and sys._jit.is_enabled()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "executable": sys.executable,
        "binary_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "workload_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "config": sysconfig.get_config_var("CONFIG_ARGS"),
        "affinity": sorted(os.sched_getaffinity(0)),
        "environment": {
            key: os.getenv(key)
            for key in (
                "PYTHON_JIT",
                "PYTHON_TIER2_INT_REGIONS",
                "PYTHON_TIER2_BUILTIN_REGIONS",
                "PYTHON_TIER2_FLOAT_FUSION",
                "PYTHON_JIT_STRESS",
            )
        },
        "n": args.n,
        "warmup": args.warmup,
        "samples": args.samples,
        "workloads": {},
    }
    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        for function in WORKLOADS.values():
            function(args.n)
        profiler.disable()
        profiler.dump_stats(str(args.output))
        return
    for name, function in WORKLOADS.items():
        start = time.perf_counter_ns()
        expected = function(args.n)
        cold_ns = time.perf_counter_ns() - start
        start = time.perf_counter_ns()
        for _ in range(args.warmup):
            assert function(args.n) == expected
        warmup_ns = time.perf_counter_ns() - start
        selected = list(executors(function))
        if name not in {"json_control", "template_control"}:
            assert selected, name
        code = []
        for offset, ex in selected:
            try:
                native = ex.get_jit_code()
            except RuntimeError:
                assert args.allow_interpreter
                native = b""
            if not args.allow_interpreter:
                assert native, (name, offset)
            path = args.output.with_name(f"{args.output.stem}-{name}-{offset}.bin")
            path.write_bytes(native)
            code.append(
                {
                    "offset": offset,
                    "bytes": len(native),
                    "path": str(path),
                    "uops": list(ex),
                }
            )
        samples = []
        for _ in range(args.samples):
            before = stats(selected)
            start = time.perf_counter_ns()
            actual = function(args.n)
            elapsed = time.perf_counter_ns() - start
            after = stats(selected)
            assert actual == expected, (name, actual, expected)
            assert all(ex.is_valid() for _, ex in selected), name
            samples.append(
                {
                    "ns": elapsed,
                    "counter_delta": {
                        key: after[key] - value for key, value in before.items()
                    },
                }
            )
        result["workloads"][name] = {
            "result": expected,
            "cold_ns": cold_ns,
            "warmup_ns": warmup_ns,
            "code": code,
            "measurements": samples,
        }
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
