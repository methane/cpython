# Executor-integrated integer-loop experiment

This experiment is disabled unless `PYTHON_TIER3_JIT=1` is present at process
startup.  It is limited to GIL-enabled builds and exact built-in range iterators
with unit step.

The optimizer recognizes the existing range iteration, integer addition, local
stores, and loop-back uops using their actual opcodes and operands.  It replaces
the instruction immediately before the existing loop-back with
`_TIER3_RANGE_CHUNK`; unsupported traces retain the existing executor unchanged.
The existing `_JUMP_TO_TOP`, its target fixup, and periodic-check loop header are
left intact.  No function, code-object, name, or complete uop-tuple template is
matched.  When the feature is disabled, recognition runs no transformation and
the experimental uop is absent from the executor.

The new non-terminating uop runs at the boundary after one iteration has
committed, then falls through to the original `_JUMP_TO_TOP`.  Its stack
inputs are the existing iterator and tagged index.  The private C kernel reads
the iterator's current `start` and `len`, and reads the current accumulator from
the frame local selected by the trace's `_SWAP_FAST` operand.  It performs at
most `PYTHON_TIER3_BUDGET` additional checked additions (1024 by default), then
materializes the accumulator and last induction value into the same frame
locals and commits the iterator state.  Allocation occurs before any state is
committed.  The next executor iteration starts with `_CHECK_PERIODIC`, providing
a bounded return to the existing safepoint and validity checks.

Executor-local counters exposed by `get_tier3_stats()` distinguish entries,
native C iterations, budget exits, and overflow exits.  This is a statically
compiled C-kernel integration experiment, not an SSA compiler or dynamic native
code emitter.  It uses no ctypes, replacement callable, Python compiler API, or
RWX mapping.

The kernel only starts from a compact exact-int accumulator because that is the
state proven by the current trace.  A non-compact accumulator therefore follows
the existing executor/deoptimization path.  This means an actual int64 overflow
inside the kernel is not currently reachable for the supported `range(n)`
shape; the checked-add exit is retained as part of the state contract, but no
performance claim is made for overflow handling.

## State and failure contract

Recognition is deliberately tied to the complete observed executor loop: the
executor entry and periodic check, range guards and next operation, local
replacement/cleanup operations, the two exact local loads, the guarded integer
addition, its cleanup/store, and the original backedge must all occur in the
expected order.  The local operands must prove distinct induction and
accumulator slots.  This intentionally rejects traces with calls, branches,
extra arithmetic, changed stack cleanup, or an unproved prefix rather than
skipping their effects.

A zero-progress return changes neither locals nor iterator and ordinary executor
execution continues.  On progress, both result objects are allocated before the
iterator or either local is changed; the update is then committed as one
boundary transition.  If either allocation fails, the unchanged boundary state
is routed through the integer addition's bytecode error target, not the
backedge's unused target.  Thus the selected exception handler and traceback
correspond to the operation represented by the chunk, and no completed Python
iteration or pre-loop effect is replayed.

Budgets greater than 4096 are rejected and use the default of 1024.  Every
bounded chunk falls through to the original backedge, whose loop header starts
with the existing periodic and validity checks.

## Measurement

`tier3_bench.py` validates every result and reports counters immediately before
and after its measured calls.  `kernel_iterations` and `kernel_fraction` are
measurement deltas, and `tier3_status` explicitly distinguishes unavailable or
non-entered paths.  It also records the interpreter, configure arguments,
compiler, architecture, commit, experiment settings, and JIT state.  The
`native_code_verified` field is false by design: this is Tier-2 executor code
calling a statically compiled C helper, not generated native code.

For example, run matched interpreters with the experiment absent and enabled:

```sh
PYTHON_JIT_STRESS=1 ./python Tools/jit/tier3_bench.py --n 1000 --initial 0
PYTHON_JIT_STRESS=1 PYTHON_TIER3_JIT=1 PYTHON_TIER3_BUDGET=64 \
  ./python Tools/jit/tier3_bench.py --n 1000 --initial 0
```
