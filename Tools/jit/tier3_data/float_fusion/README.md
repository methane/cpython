# Float product/add fusion validation

This checkpoint adds an opt-in (`PYTHON_TIER2_FLOAT_FUSION=1`) peephole for
`acc + left * right`.  It replaces the second boxed multiply and the existing
in-place add with one operation that computes two separately rounded binary64
operations and reuses the proven-unique accumulator box.  Thus it removes one
additional product allocation relative to the previous in-place-only path.

The generated optimizer was rebuilt before testing.  An ordinary pyperf nbody
worker, launched with explicit inheritance, emitted 16 fused operations in its
optimized traces.  A debug Tier-2 comparison (two fresh workers, pyperf `--fast
--min-time=0.05`) measured 964 ms +- 13 ms with fusion disabled and 950 ms +-
32 ms with fusion enabled.  Pyperf classified the difference as insignificant;
these debug timings establish coverage and an honest neutral result, not native
performance evidence.  Raw results are retained in `nbody-off.json` and
`nbody-on.json`.

Native validation was unavailable because `Tools/jit/ensure_llvm21.sh` found no
complete LLVM 21 prefix.  No earlier native result is attributed to this
change.
