# Experimental straight-line Tier 2 regions

These experiments use the existing abstract interpreter, stack cache, and
copy-and-patch backend. They are disabled by default. Enable individual groups
before compiling a trace:

```sh
PYTHON_JIT=1 PYTHON_TIER2_INT_REGIONS=1 \
  PYTHON_TIER2_BUILTIN_REGIONS=1 PYTHON_TIER2_FLOAT_FUSION=1 \
  build-jit/python program.py
```

Integer regions contain exactly two dependent add/subtract/multiply operations,
optionally followed by a comparison. The first two inputs are retained on the
operand stack; further inputs are unchanged local slots. All inputs must be
exact signed-i64 ints. Each operation checks overflow in Python order. Failure
exits at the first operation with the original stack, so ordinary arbitrary
precision arithmetic and subclass dispatch remain available. Only the final
object result is boxed; a comparison produces the existing bool singleton.

Recognition happens before abstract interpretation to avoid propagating removed
compact-int guards into later operations. The nine operation pairs use the
existing uop replication mechanism, with separate object and predicate outputs.
There is no runtime operation-selection loop. Matching is bounded to 32 uops
and rejects calls, stores, frame changes, and periodic checks. If an experimental
whole-range mode is also requested, range traces are reserved for that pass.

`PYTHON_TIER2_BOUNDED_INT_REGIONS=1` additionally enables expression trees with
three to eight operations: add/subtract/multiply and floor division by a known
nonzero integer. Leaves are local reads and `LOAD_SMALL_INT` constants. An
entry guard admits exact int inputs in `[-(2**28-1), 2**28-1]`. Interval analysis
proves that every intermediate fits the existing signed 62-bit tagged integer
representation. The native values use the ordinary operand stack and register
cache; arithmetic uses a small replicated stencil family. No runtime IR
interpreter is added. Scanning stops at 128 uops, four additional locals, or
four native stack values. Unsupported operations and unprovable intervals
retain ordinary execution.
If the first result is still on top and the same two locals are used for the
same operation again, the region duplicates that native value. This common
subexpression rule applies to addition, subtraction, and multiplication.

The first two references must be borrowed or immortal. Further inputs remain
in unchanged locals; repeated checks are removed only when adjacent local
loads identify the entry operands. Guard failure preserves the original
operand stack. There are no exits, allocations, frame transitions, or Python
callbacks while native intermediates are live. The final boxing operation
consumes all tagged values before it can allocate or raise. Its allocation
error is attributed to the first original arithmetic operation.

An immediate true-division consumer can use the integer result directly when
its numerator is an exact borrowed or immortal float. That numerator is also
guarded before entering the region. Integers up to 53 bits convert exactly;
larger values use `PyLong_AsDouble` to retain Python's rounding. Division by
zero and float allocation errors retain the original division's instruction
location. The common case creates a float without an intermediate PyLong.
The new `bounded_entries`, `bounded_guard_exits`, `bounded_boxes`, and
`bounded_divisions` counters distinguish this path from checked-i64 regions.
As with `int_boxes`, `bounded_boxes` counts representations, including cached
ints, rather than heap allocations.

`PYTHON_TIER2_FLOAT_RANGE=1`, together with bounded integer regions, enables
short range reductions of a constant float divided by an integer polynomial.
The matcher follows the optimized uop dependencies of an exact positional
Python call with up to four arguments and a three-to-eight-operation integer
expression. It supports degree zero, one, or two. It does not inspect function
names or benchmark inputs. Other calls, stores, effects, or consumers reject
the region. The original trace remains the fallback.

The integer-valued basis `1, j, j*(j-1)/2` gives three coefficients. A bounded
compile-time expression graph folds constants and factors exact divisions,
then emits ordinary tagged-integer uops with a signed-62-bit interval proof.
Its maximum stack depth must fit the original frame's unused operand-stack
capacity. Failed proofs and capacity limits retain the checked coefficient
stencils, which use a bounded four-slot scratch array in the executor without
adding operand-stack entries. Both setups require the GIL and cannot escape,
allocate, or re-enter Python; neither has a runtime node-dispatch loop.
Nonconstant coefficients must divide exactly. Runtime exactness checks remain
even when later constant folding removes the corresponding value. Known powers
of two use a mask and arithmetic shift. The final three coefficients feed the
same range reduction, which rejects overflowing or otherwise unproved chunks.
Coefficient intervals also select a 64-bit setup when every intermediate in
the initial-denominator and endpoint calculations is proved to fit. Otherwise
the setup retains 128-bit arithmetic. Both apply the same runtime monotonicity,
sign, and exact-integer-conversion checks.

The range must have step one and fit wholly in the small-int cache. Its
accumulator must be an exact, owned, uniquely referenced non-NaN float; integer
arguments retain the bounded-input contract. The old induction local must be
null or an exact int. Function, stack-space, recursion, globals (when present),
and callee instrumentation checks precede the chunk. The denominator must be
monotone, nonzero with one sign, and within `[-2**53, 2**53]` throughout it.
The loop performs every binary64 division and addition in the original order,
then updates the unique accumulator, cached induction local, and iterator
without allocation. It consumes the remaining range and takes a copy of the
original exhaustion guard's exit, retaining the iterator/index stack expected
after `END_FOR`. A chunk has at most the small-int-cache span of iterations.
The final term is peeled to avoid conditional recurrence updates inside the
chunk. Clang uses a local `FENV_ACCESS ON` helper so constrained floating-point
operations preserve separate rounding after inlining without volatile memory
traffic. Other compilers retain the volatile evaluation boundary.
NaN accumulators retain ordinary execution to preserve payload selection as
well as rounding; constrained operations alone do not fix register-operand
choices when both operands are NaNs.
Any failed proof exits at the original `FOR_ITER`, before committing effects.
`range_entries`, `range_iterations`, and `range_guard_exits` record execution.
This experiment is disabled on free-threaded, 32-bit, DTrace, Emscripten, and
targets without a native 128-bit integer type.

Builtin regions also inline the common `enumerate(list)` next operation after
abstract interpretation. The receiver must be an exact enumerate with an exact
list iterator, a cached integer index, a uniquely referenced result tuple, and
an available next element. Unsupported inputs and exhaustion leave through the
original `FOR_ITER` guard, rather than the next operation's end-of-loop exit.
The result tuple remains observable through the enumerate: its contents,
reference-release order, hash reset, and GC re-tracking match `enum_next`.
Old-element finalizers may re-enter the same iterator. `enum_entries` counts
the fast path; `enum_guard_exits` includes ordinary exhaustion.

The builtin group fuses `len(value)` with an immediate comparison, addition, or
subtraction using another local or a `LOAD_SMALL_INT` constant. It accepts exact
str, bytes, tuple, list, and dict operands. The receiver must be borrowed,
immortal, or have another strong reference, so closing it cannot run finalizers
before the consumer. Mutable lengths are read at the call, without crossing
any call, store, or periodic check. Callable identity is still checked by the
existing len guard. Solely owned receivers, subclasses, and replaced builtins
follow the ordinary call path.

The same group can produce a bool directly for `left CMP len(value)` or
`left CMP (len(value) +/- small_constant)`. The left operand must be an exact
signed-i64 int. Both the length and adjusted length stay unboxed; an arithmetic
overflow exits at the original call with all inputs intact. All six integer
comparisons use the existing comparison mask, and the original operand cleanup
order is retained.

The builtin group also removes a newly built two-element tuple when its sole
consumer is equality or inequality against a local tuple. The right operand
must be an exact tuple of length two. Corresponding elements must have the
same exact bytes, str, int, or float type; comparison then uses their existing
immutable equality semantics without allocating the left tuple. Tuple's
identity shortcut is retained for NaNs. Other lengths, mixed types (including
comparisons that can emit `BytesWarning`), and subclasses exit at the original
`BUILD_TUPLE`. `tuple_entries` and `tuple_guard_exits` report this path.

When both left elements come from `items[i]` and `items[i + 1]`, the builtin
group can also fuse the lookups and index addition into the comparison.
Both reads must use the same borrowed list/index locals, with no intervening
effects or stores. The receiver must be an exact list and the index an exact
compact int. Both indices are checked before comparing either element; negative
indices are normalized independently. The existing exact-tuple and immutable
element-type checks still apply. Failure resumes at the first subscript, so
second-index errors and subclass callbacks retain their original evaluation
order. List contents are read on each execution. `tuple_list_entries` counts
successful fused lookups within `tuple_entries`.

`str.startswith` and `str.endswith` accept an exact str receiver, an exact str
single argument, and default bounds. The optimizer verifies the actual builtin
descriptor identity and preserves the existing call guards and periodic check.
The runtime calls `PyUnicode_Tailmatch` directly. Result-type propagation removes
redundant bool conversions; the result is still the existing bool singleton.
Tuple affixes, explicit bounds, keywords, and overrides use ordinary calls.

`PYTHON_TIER2_CALL_REGIONS=1` removes matched inlined call/return frames when
the entire body only returns an argument or an immortal constant. Recognition
is limited to 64 uops and four explicit arguments, after abstract interpretation.
The existing function version, argument count, recursion, and stack checks
remain. Before consuming the call stack, the replacement checks the callee's
instrumentation version against the eval breaker; a mismatch returns to the
original CALL. There is no callee operation that can expose its frame.
Returned arguments acquire a strong reference before the remaining arguments
are closed in reverse order, with the callable last. Temporary references live
off the operand stack during finalizer reentry. `call_entries` and
`call_guard_exits` report this path. It requires the same 64-bit GIL gate and
is disabled in DTrace and Emscripten builds.
The callee's code keeps a strong reference through argument and callable
cleanup, preserving its lifetime if a finalizer replaces `__code__`.

The same option handles short callees that return a cached attribute, compare
it with `None` by identity, or compare two cached exact compact integer
attributes. A separate `_CALL_PY_ATTRIBUTE` family keeps the simple argument
and constant return stencils small. It accepts slots and managed inline values,
with up to four explicit arguments and a 64-uop scan limit. Attribute offsets
remain paired with the recorded type versions, even if abstract interpretation
removes redundant guards. The call checks those versions, inline-value validity,
and attribute presence before consuming any inputs. Missing attributes,
descriptors, noncompact integers, and subclass comparisons fall back at the
original call, retaining the callee frame for exceptions and callbacks.
`call_attr_entries` counts successful attribute calls; cleanup retains the same
reference order and code lifetime as the simpler family.

The integer and builtin experiments require a 64-bit GIL build with GCC/Clang
checked arithmetic. Other configurations do not enable them. The existing
float fusion preserves its volatile binary64 rounding boundary; shared results
allocate a fresh float, and unique results reuse their private accumulator.

`executor.get_region_stats()` reports entries, guard/overflow exits, integer
boxing operations, and allocation errors. Counters are per executor; an entry
alone is not proof of success. Inspect deltas around the specific input and
check that the corresponding failure counters stay unchanged. `int_boxes`
counts boxing operations, including small-int cache hits, not heap allocations.

Debug builds support `PYTHON_TIER2_REGION_FAIL_ALLOC=int|len|float` to exercise
the fused allocation's error edge and in-frame handlers. The probe is absent
from release execution. It is intended only for private tests.
The bounded path also accepts `bounded`, `bounded_float`, and
`bounded_conversion` for final integer, final float, and large-integer
conversion allocation failures respectively.

```sh
build-tier2-debug/python -m test test_capi.test_opt_regions -v
build-jit/python -m test test_capi.test_opt_regions test_tier3 test_capi.test_opt -v
```

`region_bench.py` supplies a fixed ten-workload exploratory panel, including two
representative header parsers and dict/JSON/template controls. It records cold
calls, warmup, every steady-state sample, immediate executor counter deltas,
and the selected native code. Run modes in rotating order on the same CPU with
no competing builds. `--profile` is a separate diagnostic invocation. This
panel is not the pyperformance suite.

Local results, commands, the immutable source baseline, build identities,
known limitations, and raw-log paths are recorded in the checkout's `plan.md`.
The experiments remain opt-in: checked integer predicates and builtin consumers
show useful gains in the local panel; boxed integer chains and shared float
updates do not yet show a reliable speed benefit.
