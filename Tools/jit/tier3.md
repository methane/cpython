# Executor-integrated integer-loop experiment

This experiment is disabled unless a supported `PYTHON_TIER3_JIT` mode is
present at process startup.  `1` (or `helper`) selects the C-helper reference;
`2` (or `direct`) selects a second mode whose checked-int64 iteration loop is
emitted in the JIT stencil and never calls `_PyTier3_RunRange`.  Entry
conversion and exit materialization may still call existing C APIs.  It is
limited to GIL-enabled builds and exact built-in range iterators with unit step.

The optimizer recognizes the existing range iteration, integer addition, local
stores, and loop-back uops using their actual opcodes and operands.  It inserts
the mode-specific range chunk after the periodic/validity checks and the
not-exhausted-range guard, but before `_ITER_NEXT_RANGE`; unsupported traces
retain the existing executor unchanged.
The existing `_JUMP_TO_TOP`, its target fixup, and periodic-check loop header are
left intact.  No function, code-object, name, or complete uop-tuple template is
matched.  When the feature is disabled, recognition runs no transformation and
the experimental uop is absent from the executor.

The new non-terminating uop runs at the guarded loop header, then falls through
to the unchanged `_ITER_NEXT_RANGE`, ordinary body, and `_JUMP_TO_TOP`.  Its stack
inputs are the existing iterator and tagged index.  The private C kernel reads
the iterator's current `start` and `len`, and reads the current accumulator from
the frame local selected by the trace's `_SWAP_FAST` operand.  It performs at
most `PYTHON_TIER3_BUDGET` checked additions (1024 by default), while always
leaving at least one range item for the ordinary body, then
materializes the accumulator and last induction value into the same frame
locals and commits the iterator state.  Allocation occurs before any state is
committed.  The ordinary body consumes the reserved item, and the next executor
iteration starts with `_CHECK_PERIODIC`, providing
a bounded return to the existing safepoint and validity checks.

Executor-local counters exposed by `get_tier3_stats()` distinguish the helper
fields from direct mode's `native_entries`, `native_iterations`,
`native_budget_exits`, `native_overflow_exits`, and
`native_materialization_exits`.  This remains a fused-uop experiment, not a
general SSA compiler.  It uses no ctypes, replacement callable, Python compiler
API, or RWX mapping.

At entry the kernel accepts only an exact built-in `int` (not `bool` or an int
subclass) whose value converts to signed 64-bit without overflow.  This includes
non-compact `int` objects.  Conversion overflow is a zero-progress fallback and
does not leave an exception set.  Checked-add overflow stops before the first
unsupported iteration, commits any completed safe prefix, increments
`overflow_exits`, and leaves that iteration to Python bigint arithmetic.  The
supported `range(n)` shape has nonnegative, unit-step values, so it can exercise
the `INT64_MAX` boundary but cannot naturally drive a total toward `INT64_MIN`.

## State and failure contract

Recognition is deliberately tied to the complete observed executor loop: the
executor entry and periodic check, range guards and next operation, local
replacement/cleanup operations, the two exact local loads, the guarded integer
addition, its cleanup/store, and the original backedge must all occur in the
expected order.  The local operands must prove distinct induction and
accumulator slots.  This intentionally rejects traces with calls, branches,
extra arithmetic, changed stack cleanup, or an unproved prefix rather than
skipping their effects.

A zero-progress return changes neither locals nor iterator and the reserved
ordinary iteration continues.  On progress, both result objects are allocated before the
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
`native_code_verified` field reports whether the selected executor exposes
nonempty generated JIT code; an interpreter-only build reports false.  In either
case, the range chunk calls the same statically compiled C helper.

For example, run matched interpreters with the experiment absent and enabled:

```sh
PYTHON_JIT_STRESS=1 ./python Tools/jit/tier3_bench.py --n 1000 --initial 0
PYTHON_JIT_STRESS=1 PYTHON_TIER3_JIT=1 PYTHON_TIER3_BUDGET=64 \
  ./python Tools/jit/tier3_bench.py --n 1000 --initial 0
```
