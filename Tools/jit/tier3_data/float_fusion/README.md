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

The follow-up borrowed-operand implementation encodes the matcher proof in the
uop: multiplication operands consumed by `_POP_TOP_NOP` are marked dead rather
than closed.  Regenerated metadata consequently classifies the fused uop as
non-escaping and generated cached cases no longer publish the frame around two
fictitious decrefs.  A scoped `FP_CONTRACT OFF` preserves the two Python
rounding points without a volatile spill.

The expanded edge suite covers the cancellation witness, signed zero,
infinities, NaNs, subnormals, overflow, repeated identities, exact callback
order on guard failure, and exact-float re-entry.  A fresh three-worker debug
Tier-2 rerun (100 ms minimum worker time) measured 976 ms +- 9 ms OFF and
926 ms +- 7 ms ON (1.05x); unlike the older neutral run, pyperf reports this
focused result as faster.  These remain debug integration timings, not native
evidence.  Raw results are `nbody-borrowed-{off,on}.json`; validation is inside
each pyperf worker through the explicit inherited fusion setting.

The optimized native-JIT build used LLVM 21.1.8 and the documented
`-fno-vectorize -fno-slp-vectorize` stencil workaround.  Three fresh pyperf
workers measured 51.0 ms +- 1.1 ms OFF and 48.1 ms +- 0.9 ms ON (1.06x
faster).  Only `PYTHON_TIER2_FLOAT_FUSION` changed, and it was explicitly
inherited together with `PYTHON_JIT`; the unmodified pyperformance 1.14.0
nbody entrypoint was used.  Raw results are `nbody-native-{off,on}.json`.
Disassembly of the tested executable contains separate scalar `mulsd` and
`addsd` operations and no `vfmadd`, consistent with the cancellation test.
