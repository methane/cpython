# Controlled method JIT performance follow-up

Source base: d95f29589e0; starting implementation: 15c0e6113c1.
No PGO or LTO. LLVM 21, GCC release builds, CPU 2.

`summarize.py` produces the primary result tables.
`method_jit_performance.md` at the repository root describes conclusions and
limits; supplementary summaries combine every retained process. Raw measurements
and failures remain beside this file. The `main-src` control is a git archive
of the base with only `Tools/jit/_optimizers.py` replaced by the prerequisite
stencil-local-reference build fix. Instrumentation in `profile-src` is diagnostic
only and is not part of the working implementation.

`screen.py` rotates three process blocks of Go (5 warmups, 20 values) across
specified named binaries. `SCREEN_PREFIX` distinguishes independent experiments.
`cohort.py` fixes 24 pyperformance workloads before collecting results and runs
main/before/candidate then candidate/before/main using the same loop counts.
NetworkX's process group is killed after 15 seconds; other processes after 45.

Binary controls:

- `python-trace`: initial source with method compilation returning unsupported.
- `python-prototype`: prior prototype optimizer on the same current runtime.
- `python-before`: committed merge-aware frontend before this work.
- `python-cleanup`: local validity/IP cleanup only.
- `python-global-cache`: cleanup plus initial direct-mapped global miss cache.
- `python-cache-full`: cleanup plus associative four-entry global miss cache.
- `python-inline`: above plus bounded forward-branch inlining.
- `python-edges`: above plus adjacent single-predecessor edge elision.
- `python-before-matched`: initial optimizer relinked with final internal headers
  and stencils, so broad comparisons use identical extension-module layout.
- `python-final`: frozen final implementation used for the cohort.
- `python-trace-final`: final global cache with method compilation disabled.

The default `build-method-jit/python` was restored after controls. Subsequent
source edits only clarify comments; the frozen cohort binaries were not changed.

Snapshots of each optimizer variant, build logs, executable hashes, command
lines, native perf samples, and raw per-process timings are preserved. These
are fixed-executable comparisons on this machine, not independent-build or
cross-machine confidence claims. The 24-workload cohort is a performance screen,
not the entire pyperformance suite and not an unseen holdout.

The local commit includes raw JSON measurements, summaries, runner scripts,
profiles in text form and validation logs. Build trees, complete experimental
source snapshots, build logs and perf.data recordings remain local artifacts.
