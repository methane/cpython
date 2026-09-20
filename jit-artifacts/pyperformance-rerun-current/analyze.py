#!/usr/bin/env python3
"""Summarize the fixed-main versus current JIT pyperformance run."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

import pyperf
from pyperf._cli import format_checks
from pyperf._compare import is_significant_benchs


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOOTSTRAP_ITERATIONS = 20_000
BOOTSTRAP_SEED = 20_260_915
EXPECTED_SHA256 = {
    "a-main.json": "fd1b4f6653dfbf095583b9fa0f8255cdc112ed1a0ddfbe5043e0cd2ea8fe9396",
    "a-candidate.json": "eb22445bd6debee318d8a1f7f891328e49fb4e45d9e17779c105b6d00fdec7bf",
    "b-main.json": "3f360cd85e390e35d510e9006d5c43e3b63e8b1a2d1d9ae96f2b8eef5847d188",
    "b-candidate.json": "9e421c6eb04b2580b8b3646245a03482fa5aae3d028fa30dfb9cc8ba24b5acbe",
}
EXPECTED_BINARY_SHA256 = {
    "main": "8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407",
    "candidate": "ebb86d4a70b9dda5c4f70d4d49196cc5a87986c41ced14951f73dd0eef2fb457",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def geomean(values: list[float]) -> float:
    return math.exp(statistics.fmean(math.log(value) for value in values))


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    position = fraction * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def process_means(benchmark: pyperf.Benchmark) -> list[float]:
    return [statistics.fmean(run.values) for run in benchmark.get_runs() if run.values]


def loops(benchmark: pyperf.Benchmark) -> list[int]:
    return [run.get_total_loops() for run in benchmark.get_runs() if run.values]


def bootstrap(process_pairs: list[tuple[list[float], list[float]]]) -> tuple[float, float]:
    rng = random.Random(BOOTSTRAP_SEED)
    samples = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        log_ratio = 0.0
        for baseline, candidate in process_pairs:
            baseline_mean = statistics.fmean(
                baseline[rng.randrange(len(baseline))] for _ in baseline
            )
            candidate_mean = statistics.fmean(
                candidate[rng.randrange(len(candidate))] for _ in candidate
            )
            log_ratio += math.log(candidate_mean / baseline_mean)
        samples.append(math.exp(log_ratio / len(process_pairs)))
    return percentile(samples, 0.025), percentile(samples, 0.975)


def warning_details(benchmark: pyperf.Benchmark) -> list[str]:
    return [line[2:] for line in format_checks(benchmark) if line.startswith("* ")]


def markdown_table(rows: list[dict[str, object]], suites: dict[str, pyperf.BenchmarkSuite]) -> list[str]:
    lines = [
        "| Benchmark | Main | Candidate | Candidate/main | Time change | Significant |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for row in rows:
        baseline = suites["main"].get_benchmark(row["name"])
        candidate = suites["candidate"].get_benchmark(row["name"])
        lines.append(
            f"| {row['name']} | {baseline.format_value(row['main_mean_seconds'])} "
            f"| {candidate.format_value(row['candidate_mean_seconds'])} "
            f"| {row['candidate_over_main']:.4f} | {row['time_change_percent']:+.1f}% "
            f"| {'yes' if row['pyperf_significant'] else 'no'} |"
        )
    return lines


def main() -> None:
    input_hashes = {name: sha256(HERE / name) for name in EXPECTED_SHA256}
    if input_hashes != EXPECTED_SHA256:
        raise RuntimeError(f"input identity changed: {input_hashes}")
    binary_hashes = {
        "main": sha256(ROOT / "build-main-jit/python"),
        "candidate": sha256(ROOT / "build-jit/python"),
    }
    if binary_hashes != EXPECTED_BINARY_SHA256:
        raise RuntimeError(f"binary identity changed: {binary_hashes}")

    raw = {
        f"{group}-{side}": pyperf.BenchmarkSuite.load(
            str(HERE / f"{group}-{side}.json")
        )
        for group in ("a", "b")
        for side in ("main", "candidate")
    }
    names = {key: set(suite.get_benchmark_names()) for key, suite in raw.items()}
    for group in ("a", "b"):
        if names[f"{group}-main"] != names[f"{group}-candidate"]:
            raise RuntimeError(f"group {group} result names differ")
    if names["a-main"] & names["b-main"]:
        raise RuntimeError("groups overlap")
    for suite in raw.values():
        metadata = suite.get_metadata()
        expected = {
            "cpu_affinity": "2",
            "perf_version": "2.10.0",
            "performance_version": "1.14.0",
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise RuntimeError(f"unexpected {key}: {metadata.get(key)!r}")

    suites = {
        side: pyperf.BenchmarkSuite.load(str(HERE / f"{side}.json"))
        for side in ("main", "candidate")
    }
    all_names = sorted(suites["main"].get_benchmark_names())
    if all_names != sorted(suites["candidate"].get_benchmark_names()):
        raise RuntimeError("merged result names differ")

    rows = []
    warnings = {"main": {}, "candidate": {}}
    process_pairs = []
    for name in all_names:
        baseline = suites["main"].get_benchmark(name)
        candidate = suites["candidate"].get_benchmark(name)
        if baseline.get_unit() != candidate.get_unit():
            raise RuntimeError(f"unit mismatch for {name}")
        baseline_processes = process_means(baseline)
        candidate_processes = process_means(candidate)
        if len(baseline_processes) != 6 or len(candidate_processes) != 6:
            raise RuntimeError(f"unexpected process count for {name}")
        baseline_loops = loops(baseline)
        candidate_loops = loops(candidate)
        loop_matched = baseline_loops == candidate_loops
        ratio = candidate.mean() / baseline.mean()
        significant, t_score = is_significant_benchs(baseline, candidate)
        group = "A" if name in names["a-main"] else "B"
        for side, benchmark in (("main", baseline), ("candidate", candidate)):
            details = warning_details(benchmark)
            if details:
                warnings[side][name] = details
        row = {
            "name": name,
            "group": group,
            "first_side": "main" if group == "A" else "candidate",
            "tags": ",".join(baseline.get_metadata().get("tags", [])),
            "unit": baseline.get_unit(),
            "main_loops": baseline_loops[0],
            "candidate_loops": candidate_loops[0],
            "loop_matched": loop_matched,
            "main_mean_seconds": baseline.mean(),
            "candidate_mean_seconds": candidate.mean(),
            "candidate_over_main": ratio,
            "time_change_percent": 100.0 * (ratio - 1.0),
            "speedup": 1.0 / ratio,
            "pyperf_significant": significant,
            "pyperf_t_score": t_score,
            "main_stdev_percent": 100.0 * baseline.stdev() / baseline.mean(),
            "candidate_stdev_percent": 100.0 * candidate.stdev() / candidate.mean(),
        }
        rows.append(row)
        if loop_matched:
            process_pairs.append((baseline_processes, candidate_processes))

    primary = [row for row in rows if row["loop_matched"]]
    mismatched = [row for row in rows if not row["loop_matched"]]
    ratio = geomean([row["candidate_over_main"] for row in primary])
    all_ratio = geomean([row["candidate_over_main"] for row in rows])
    without_base16 = geomean(
        [
            row["candidate_over_main"]
            for row in primary
            if row["name"] not in {"base16_small", "base16_large"}
        ]
    )
    interval = bootstrap(process_pairs)
    group_ratios = {
        group: geomean(
            [row["candidate_over_main"] for row in primary if row["group"] == group]
        )
        for group in ("A", "B")
    }
    tags = sorted({tag for row in primary for tag in str(row["tags"]).split(",") if tag})
    tag_ratios = {
        tag: geomean(
            [
                row["candidate_over_main"]
                for row in primary
                if tag in str(row["tags"]).split(",")
            ]
        )
        for tag in tags
    }
    significant_faster = sum(
        bool(row["pyperf_significant"]) and row["candidate_over_main"] < 1.0
        for row in primary
    )
    significant_slower = sum(
        bool(row["pyperf_significant"]) and row["candidate_over_main"] > 1.0
        for row in primary
    )

    old_csv = HERE.parent / "pyperformance-20260915/analysis/ratios.csv"
    old_rows = {}
    if old_csv.exists():
        with old_csv.open(newline="") as file:
            old_rows = {row["name"]: float(row["candidate_over_main"]) for row in csv.DictReader(file)}
    common_old = [row for row in primary if row["name"] in old_rows]
    newly_covered = sorted(set(all_names) - set(old_rows))
    old_common_ratio = geomean([old_rows[row["name"]] for row in common_old])
    current_common_ratio = geomean(
        [row["candidate_over_main"] for row in common_old]
    )

    with (HERE / "ratios.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (HERE / "warnings.json").write_text(
        json.dumps(warnings, indent=2, sort_keys=True) + "\n"
    )

    result = {
        "definition": "candidate elapsed time / main elapsed time",
        "primary": {
            "loop_matched_results": len(primary),
            "geometric_mean_ratio": ratio,
            "time_reduction_percent": 100.0 * (1.0 - ratio),
            "speedup": 1.0 / ratio,
            "process_bootstrap_95_percent": list(interval),
            "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "nominal_faster": sum(row["candidate_over_main"] < 1.0 for row in primary),
            "nominal_slower": sum(row["candidate_over_main"] > 1.0 for row in primary),
            "significant_faster": significant_faster,
            "significant_slower": significant_slower,
            "not_significant": len(primary) - significant_faster - significant_slower,
        },
        "all_common_results_sensitivity": {
            "result_count": len(rows),
            "geometric_mean_ratio": all_ratio,
        },
        "without_base16_layout_sensitivity": {
            "result_count": len(primary) - 2,
            "geometric_mean_ratio": without_base16,
            "status": "post-hoc diagnostic; primary result is unchanged",
        },
        "loop_mismatches": [
            {
                "name": row["name"],
                "main_loops": row["main_loops"],
                "candidate_loops": row["candidate_loops"],
                "candidate_over_main": row["candidate_over_main"],
            }
            for row in mismatched
        ],
        "group_geometric_mean_ratios": group_ratios,
        "tag_geometric_mean_ratios": tag_ratios,
        "warning_counts": {side: len(items) for side, items in warnings.items()},
        "previous_run_common_subset": {
            "result_count": len(common_old),
            "old_candidate_over_main": old_common_ratio,
            "current_candidate_over_main": current_common_ratio,
        },
        "newly_covered_result_names": newly_covered,
        "failed_specifications": {
            "asyncio_websockets": "TCP port 8001 was already in use",
            "dask": "cloudpickle expects the removed DELETE_GLOBAL opcode",
            "genshi": "incompatible with the Python 3.16 ast.Expression constructor",
        },
        "input_sha256": input_hashes,
        "binary_sha256": binary_hashes,
    }
    (HERE / "analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )

    fastest = sorted(primary, key=lambda row: row["candidate_over_main"])[:15]
    slowest = sorted(primary, key=lambda row: row["candidate_over_main"], reverse=True)[:15]
    lines = [
        "# Current native-JIT pyperformance comparison",
        "",
        "Ratios are candidate elapsed time divided by fixed-main elapsed time; smaller is faster.",
        "",
        f"- Primary loop-matched results: **{len(primary)}** of {len(rows)}",
        f"- Equal-weight geometric mean: **{ratio:.6f}** "
        f"(**{100.0 * (1.0 - ratio):.2f}% less time**, **{1.0 / ratio:.3f}x speed**)",
        f"- 95% process-bootstrap interval: **[{interval[0]:.6f}, {interval[1]:.6f}]**",
        f"- Group A / B ratios: **{group_ratios['A']:.6f} / {group_ratios['B']:.6f}**",
        f"- Nominally faster / slower: **{result['primary']['nominal_faster']} / {result['primary']['nominal_slower']}**",
        f"- pyperf-significant faster / slower / not significant: "
        f"**{significant_faster} / {significant_slower} / {result['primary']['not_significant']}**",
        f"- Unstable warnings, main / candidate: **{len(warnings['main'])} / {len(warnings['candidate'])}**",
        "",
        f"Including the two loop-mismatched deepcopy subresults gives a sensitivity ratio of **{all_ratio:.6f}** across all {len(rows)} results. They are excluded from the primary result because main used 1,024 loops while candidate used 65,536 (`deepcopy_reduce`) or 8,192 (`deepcopy_memo`).",
        "",
        f"Across the {len(common_old)} loop-matched results also present in the previous analysis, the old/current ratios are **{old_common_ratio:.6f} / {current_common_ratio:.6f}**.",
        "",
        f"Focused JIT-off diagnosis shows that the Base16 regression remains with identical `base64.py` source and predates the Go work. It is sensitive to executable layout and the immediate release of multi-megabyte temporary bytes; see `base16-diagnosis/summary.md`. Removing its two results as a post-hoc sensitivity calculation gives **{without_base16:.6f}** across {len(primary) - 2} results. The primary result is unchanged.",
        "",
        "Of the 96 requested specifications, 93 completed on both sides and produced 119 result names. The nine result names newly covered relative to the earlier sandbox run are: "
        + ", ".join(f"`{name}`" for name in newly_covered)
        + ".",
        "",
        "All three NetworkX specifications completed with the 60-second worker timeout. `shortest_path` was 1.0179, `k_core` was 0.8518, and `connected_components` was 1.0160 candidate/main. The main-side `k_core` result has 9.6% standard deviation, so its large improvement is less precise than most entries.",
        "",
        "Three specifications failed symmetrically: `asyncio_websockets` could not bind TCP port 8001 because it was already in use; `dask` failed because cloudpickle expects `DELETE_GLOBAL`; and `genshi` failed on the Python 3.16 `ast.Expression` constructor.",
        "",
        "## Largest improvements",
        "",
        *markdown_table(fastest, suites),
        "",
        "## Largest regressions",
        "",
        *markdown_table(slowest, suites),
        "",
    ]
    (HERE / "summary.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
