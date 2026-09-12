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
