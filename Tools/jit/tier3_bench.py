"""Measure individual experimental tier-3 value-IR transformations."""

from __future__ import annotations

import argparse
import json
import statistics
import time

from _tier3 import Instruction, allocate_registers, optimize


def sample_trace() -> list[Instruction]:
    """Return a synthetic trace shaped like a small integer reduction loop."""
    return [
        Instruction("parameter", 0),
        Instruction("guard_int", inputs=(0,), effect=True),
        Instruction("const", 1, immediate=2),
        Instruction("const", 2, immediate=3),
        Instruction("add_int", 3, (1, 2), loop=True),
        Instruction("add_int", 4, (1, 2), loop=True),
        Instruction("mul_int", 5, (3, 4), loop=True),
        Instruction("add_int", 6, (0, 5), loop=True),
        Instruction("add_int", 7, (0, 5), loop=True),
        Instruction("result", inputs=(6,), effect=True),
    ]


def measurements(disable: set[str], repeat: int = 1_000) -> dict[str, object]:
    trace = sample_trace()
    options = {
        "constant_folding": "fold" not in disable,
        "cse": "cse" not in disable,
        "dce": "dce" not in disable,
        "licm": "licm" not in disable,
    }
    samples = []
    for _ in range(repeat):
        start = time.perf_counter_ns()
        optimized = optimize(trace, **options)
        samples.append(time.perf_counter_ns() - start)
    allocations = allocate_registers(optimized, 3)
    return {
        "input_instructions": len(trace),
        "median_optimizer_ns": statistics.median(samples),
        "output_instructions": len(optimized),
        "eliminated_instructions": len(trace) - len(optimized),
        "register_values": sum(item.register is not None for item in allocations),
        "spills": sum(item.spill is not None for item in allocations),
        "disabled": sorted(disable),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--disable",
        action="append",
        choices=("fold", "cse", "dce", "licm"),
        default=[],
    )
    parser.add_argument("--repeat", type=int, default=1_000)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    print(
        json.dumps(
            measurements(set(args.disable), args.repeat), indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
