"""Measure the executor-integrated range kernel in the current process."""
import _opcode
import json
import statistics
import sys
import time


def sum_from(n, initial):
    total = initial
    for item in range(n):
        total += item
    return total


def executor():
    for offset in range(0, len(sum_from.__code__.co_code), 2):
        try:
            return _opcode.get_executor(sum_from.__code__, offset)
        except ValueError:
            pass
    return None


for _ in range(3000):
    sum_from(1000, 0)

samples = []
for _ in range(9):
    start = time.perf_counter_ns()
    for _ in range(10000):
        result = sum_from(1000, 0)
    samples.append((time.perf_counter_ns() - start) / 10000)

trace = executor()
print(json.dumps({
    "python": sys.version,
    "jit_available": sys._jit.is_available(),
    "jit_enabled": sys._jit.is_enabled(),
    "median_ns": statistics.median(samples),
    "samples_ns": samples,
    "result": result,
    "tier3": trace.get_tier3_stats() if trace is not None else None,
}, indent=2))
