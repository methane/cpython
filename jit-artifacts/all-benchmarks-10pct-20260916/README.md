# Final standalone benchmark confirmation

The Japanese report is [benchmarks/jit_comparison.md](../../benchmarks/jit_comparison.md).
This directory retains the final fixed-binary, CPU 2 comparison from 2026-09-17:

- `framebind-confirm12-20260917-state.json`: commands, process means, checksums,
  environment observations, binary/extension/dependency/workload identities and
  the completed identity checks.
- `framebind-confirm12-20260917-<block>-<workload>-<variant>.json`: all 192
  process results, with seven raw measured samples each. Blocks are 0 through 11;
  variants are `main` and `candidate`. No samples were discarded.
- `framebind-confirm12-20260917-confirmation.{json,md}`: paired ratios and
  two-sided 95% log-ratio Student t intervals for each of the eight workloads.
- `run_suite.py` and `confirm_comparison.py`: the runner and interval calculation.
- `framebind-source-manifest.json`: measured source hashes and the pre-commit
  parent revision. The source and new headers are included in this commit;
  `plan.md` was updated after the source freeze.
- `dependency-manifest.json`: the shared SQLAlchemy and greenlet wheel versions
  and hashes.
- `framebind-tests-*.log` and `framebind-extra-*.log`: final correctness results
  for GIL debug/native and free-threaded debug/native builds.
- `attributeitem-generator-tests.log`: the 102 generator tests, preceding the
  subsequent C-only implementation changes.

Build trees, executables, installed third-party dependencies, intermediate
experiments and duplicate source snapshots remain local and are not included.
The runner expects the existing main build and `shared-deps` tree at the paths
recorded in the report; it does not build Python or install dependencies.
Raw process stderr logs and the runner log remain available locally.

The final confirmation measures these fixed binaries on this CPU, with PGO and
LTO disabled. It does not establish independent rebuild/hardware reproducibility,
simultaneous 95% coverage for the whole suite, or a general Python-wide speedup.
