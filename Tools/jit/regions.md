# Experimental straight-line Tier 2 regions

For the design rationale, semantic constraints, and measured results across the
completed experiments, see [the optimization report](optimization_report.md).

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
The loop performs every binary64 division and preserves the original sequence
of additions, then updates the unique accumulator, cached induction local, and iterator
without allocation. It consumes the remaining range and takes a copy of the
original exhaustion guard's exit, retaining the iterator/index stack expected
after `END_FOR`. A chunk has at most the small-int-cache span of iterations.
On SSE2 builds without fast-math, adjacent divisions use two SIMD lanes when
all MXCSR exception traps are masked. Their results enter two separate scalar
additions in the original order; the terms are never summed together first.
Enabled traps and other targets retain the scalar division/addition sequence.
When the denominator, first difference, and second difference fit signed int32,
an additional endpoint check can prove every denominator fits int32. That path
updates two packed integer recurrences and converts both denominators with one
SIMD instruction. Packed step updates use modulo-2**32 arithmetic; only proved
int32 denominators are consumed. `range_int32_iterations` counts its iterations.
Wider denominators keep the two separate int64-to-double conversions.
The final one or two terms are peeled to avoid conditional recurrence updates
inside the chunk. Clang uses a local `FENV_ACCESS ON` helper so constrained floating-point
operations preserve separate rounding after inlining without volatile memory
traffic. The scalar helper retains a volatile evaluation boundary with other compilers.
NaN accumulators retain ordinary execution to preserve payload selection as
well as rounding; constrained operations alone do not fix register-operand
choices when both operands are NaNs.
Any failed proof exits at the original `FOR_ITER`, before committing effects.
`range_entries`, `range_iterations`, and `range_guard_exits` record execution.
This experiment is disabled on free-threaded, 32-bit, DTrace, Emscripten, and
targets without a native 128-bit integer type.

Builtin regions also inline the common `enumerate(list)` next operation after
abstract interpretation. The receiver must be an exact enumerate. Its fast path
requires an exact list iterator, a cached integer index, a uniquely referenced
result tuple, and an available next element. Other inner iterators, shared
tuples, large indices, and exhaustion call ordinary `enum_next` within the trace.
Normal exhaustion uses the original exit after `END_FOR`; exceptions use the
saved `FOR_ITER` location. The result tuple remains observable through the
enumerate: its contents, reference-release order, hash reset, and GC re-tracking
match `enum_next`. Old-element finalizers may re-enter the same iterator.
`enum_entries` counts the fast path, `enum_fallbacks` the ordinary calls, and
`enum_guard_exits` failures of the enumerate-type guard itself.

For a loop that only unpacks enumerate results, reads a constant tuple field,
and compares its exact compact integer with an unchanged local, the builtin
group can scan up to 64 consecutive items taking the same loop branch.
The six integer comparisons use replicated stencils. `_ENUM_LIST_INT_SCAN`
leaves the original next/unpack/comparison in place for
the first different branch, unsupported element, or exhaustion. It preserves
the header's periodic check and requires the list still to own the previous
local and cached-tuple item, so omitted reference releases cannot run finalizers.
Shared enumerate result tuples and indices outside the small-int cache retain
ordinary iteration. `enum_scan_entries`, `enum_scan_iterations`, and
`enum_scan_misses` distinguish chunk execution from the original next path.

`_LIST_PAIR_APPEND_SCAN` recognizes the nonmatching branch of a loop that
compares `(source[index], source[index + 1])` with a local pair, appends
`source[index]` to an output list, and increments the index by one. It retains
the original iteration and consumes up to 64 preceding iterations using only
the output list's existing capacity. Both lists must be exact and distinct,
the pair and compared elements must contain exact bytes, and the resulting
index must remain in the small-int cache. There is no allocation or callback
inside the scan. Capacity exhaustion, matching pairs, and unsupported values
leave the remaining append, error location, and comparison to the original
trace. The final complete pair is also left to the original iteration, whose
header has already been evaluated.

The matcher verifies the nonmatching trace through its backedge and decodes
the original loop header, including saved instructions under `ENTER_EXECUTOR`.
The header must test `index < global_name(source) - 1` and lead to the same
pair read. This admits side traces without assuming their incoming branch
proves the next iteration's condition. At runtime the global name must resolve
to the canonical `len`; globals and builtins must have unicode-key tables so
this check cannot invoke a colliding key's `__eq__`. Other headers, extra body
effects, aliased local slots, and frame transitions are rejected. The GIL and
64-bit builtin-region gates apply. `pair_scan_entries`, `pair_scan_iterations`,
and `pair_scan_misses` report actual skipped iterations separately from the
ordinary comparisons that remain.

`_CONTAINS_OP_LIST_INT` scans exact lists of compact exact integers directly.
For unsupported operands or the first unsupported element it calls ordinary
`PySequence_Contains` in the trace. Restarting that operation repeats only
the preceding exact-integer comparisons, which have no callbacks or mutations.
The original operand cleanup and error location are retained. The
`contains_entries`, `contains_iterations`, and `contains_fallbacks` counters
separate completed direct searches, tested integer elements, and ordinary calls.

Several accompanying guard changes apply independently of the region options.
Dict subscription and assignment use `_GUARD_NOS_TYPE` to check the receiver,
instead of checking the key at TOS. Builtin method-descriptor guards accept
subtypes using `PyObject_TypeCheck`, as ordinary descriptor calls do; this
allows inherited methods such as `list.append` to stay in a trace. The latter
also applies to Tier 1. The separate `CALL_LIST_APPEND` specialization still
requires an exact list.

Builtin constant folding also checks the function's actual builtins mapping.
Only the interpreter's canonical builtins dictionary is covered by the builtin
watcher; custom dictionaries keep the ordinary load. Folded loads carry
`_GUARD_BUILTINS_IDENTITY`, since functions with the same code/function version
can use different mappings. A copied dictionary can preserve a keys version
while changing values, so the keys version alone does not prove the binding.

For a dict subclass whose generic assignment slot resolves `__setitem__` to
dict's original descriptor, `_STORE_SUBSCR_DICT_INHERITED` calls `PyDict_SetItem`
directly. Overriding `__delitem__` alone can cause this generic slot, as in
`collections.Counter`. The optimizer checks the slot itself to exclude custom
C implementations and watches the type. The uop checks the receiver's type
version before the call; a mismatch uses ordinary `PyObject_SetItem` in the
trace. Hash/equality callbacks, errors, and operand cleanup use the original
dict and bytecode protocols. `dict_store_entries` and `dict_store_fallbacks`
count direct and ordinary calls.

`_DICT_PAIR_INCREMENT` additionally recognizes subscription, addition of a
nonnegative small integer constant, and inherited dict assignment using the
same dict and key. The fast path accepts an existing exact compact integer
value and an exact two-tuple of exact bytes. A restricted lookup uses the
ordinary tuple hash cache and dict probe sequence, but checks any colliding
stored key before comparing it. Encountering a key with a possible equality
callback retains the original operations. Missing keys, watched dictionaries,
split tables, unsupported values, and changed type/slot assumptions also exit
at the subscription. The matcher requires the augmented assignment's two
operand copies in the trace, so a side trace starting at a failed subscription
retains the ordinary lookup. Generic assignment records its receiver type for
abstract interpretation; this lets inherited dict assignment remain direct
even when the side trace's incoming stack has no type information.

Successful lookup and compact-int boxing cannot invoke Python or schedule GC,
so the existing entry remains stable through replacement. The uop allocates
the normal new integer and replaces the value without a second lookup. It
preserves the four operand references and their cleanup order; it does not
reuse a published integer or synthesize a missing-key result. Allocation errors
use the original addition's bytecode offset, including the executor's error
stub, while successful cleanup uses the original assignment's offset.
`dict_update_entries` and `dict_update_guard_exits` distinguish direct updates
and fallbacks. The generator treats the restricted lookup as non-escaping,
and the old integer uses the existing exact-int cleanup. Dictionary operand
cleanup retains ordinary escaping decrements, since a last reference can still
run a subclass finalizer. Debug allocation injection accepts `dict_update`.

The builtin option specializes a known `range(stop)` call with an exact compact
int, and `GET_ITER` on a known range whose four integer fields are compact.
Both use the ordinary range/iterator allocation and freelists. The range object
still owns its original stop, has a separately created length, and lives until
the original iterator operation consumes it. This preserves its lifetime across
periodic checks. Wider integers and `__index__` inputs use the original operations.
`range_call_entries` and `range_iter_entries` count the two successful paths.
Debug allocation injection accepts `range_call` and `range_iter` to check their
original CALL and GET_ITER error locations.

The builtin group fuses `len(value)` with an immediate comparison, addition, or
subtraction using another local or a `LOAD_SMALL_INT` constant. It accepts exact
str, bytes, tuple, list, and dict operands. The receiver must be borrowed,
immortal, or have another strong reference, so closing it cannot run finalizers
before the consumer. Mutable lengths are read at the call, without crossing
any call, store, or periodic check. Callable identity is still checked by the
existing len guard. Solely owned receivers, subclasses, and replaced builtins
follow the ordinary call path.

`_LEN_SUBSCR_LIST` additionally fuses an exact list subscript with a following
length comparison against a local integer or small constant. It checks the
index, selected item's builtin length, and callable before consuming inputs.
The outer list must be borrowed or have another owner: freeing a unique list
could run another element's finalizer and change the selected item's length.
Guard failures resume at the original subscript. `len_subscript_entries` counts
successful fusions; unsupported cases increment `len_guard_exits`.

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

`_CALL_PY_LIST` extends call frame elimination to a cached attribute's exact
list item, optionally consumed by a builtin length comparison against a small
constant. It accepts compact integer indices, including negative indices,
and checks bounds before removing the callee frame. Length predicates retain
the globals keys version and canonical builtins identity checks. Missing
attributes, custom indexing or length methods, and out-of-range indices resume
at the original CALL, preserving the callee's exception and callback context.
Result ownership, reverse argument cleanup, code lifetime, instrumentation,
and the caller's return offset are preserved. `call_list_entries` counts this
path, under the existing call-region option and platform restrictions.

The same uop also handles `return len(self.items) OP constant`, for each of
the six integer comparisons. Replicas 0 through 4 select indexed items, and
replicas 5 through 9 select the attribute list itself. The explicit argument
count is `oparg % 5`. Selecting the mode when generating the stencil keeps
direct-length checks out of existing indexed calls.
The fast path reads the exact list's size directly and returns a Boolean;
it needs neither an intermediate `int` nor a callee frame. The owner argument
keeps the list alive until the comparison completes. A list subclass, changed
builtin, missing attribute, or instrumentation request takes the original CALL
path, so a user-defined `__len__` observes the real callee frame and the original
evaluation order. Direct predicates use the existing `call_list_entries`
counter. Bounds are currently limited to nonnegative 16-bit constants.

Some bounds become constant only during abstract interpretation, as in
`len(self.items) == 2 * self.minimum_degree - 1`. A cleanup pass before call
matching removes unused local load/pop pairs, including short-local replicas,
and the load/rotate/pop traffic left when both folded operands are immortal.
The result load remains. These local matches cross only NOPs, instruction
position updates, and value records; they do not cross validity guards,
periodic checks, calls, or stores. The existing unnecessary-uop pass runs before
and between these matches to remove checks already proved redundant. This
cleanup is enabled by any of the integer, builtin, or call-region options.

Folded class-attribute bounds currently fuse on the slot-attribute path where
no intermediate instance-shadowing guard remains. Instances with a dictionary
retain their managed-values guard and use ordinary execution for that pattern;
literal bounds can fuse for both layouts. The pass does not independently fuse
an arbitrary post-optimization `CALL_LEN`: moving its cleanup could allow a
finalizer to change the later bound or leave an exit with the wrong operand
stack. It instead requires the complete short callee and its retained owner.
Tests cover all comparisons and supported layouts, class and function changes,
instance shadowing, copied builtins, and callbacks that change a class attribute
or raise from `__len__`.

`_CALL_CLASS_ATTRIBUTES` handles constructors whose entire initializer stores
each of one to four explicit positional arguments once into distinct inline
instance attributes, then returns `None`. Matching is bounded to 96 uops and
uses the recorded function and type versions. It allocates a fresh instance
with the original allocator and transfers the argument references in attribute
assignment order, preserving identity and `__dict__` insertion order. The
function version, argument shape, inline layout, recursion, stack capacity,
and instrumentation checks retain ordinary execution when unsuitable.

Allocation can schedule GC. If pending work appears after allocation, or the
fresh inline layout is unsuitable, the uop creates the original initializer
and cleanup frames and exits to the initializer's entry before any stores.
GC callbacks and monitoring therefore see the original frame and arguments.
The successful path omits both frames but retains the caller's return offset.
When the recorded trace stops at the cleanup trampoline's final `RETURN_VALUE`,
a dynamic exit resumes the real caller immediately after its constructor CALL.
`class_entries`, `class_guard_exits`, and `class_materializations` distinguish
these paths. The same call-region option and platform restrictions apply.

The integer and builtin experiments require a 64-bit GIL build with GCC/Clang
checked arithmetic. Other configurations do not enable them. The existing
float fusion preserves its volatile binary64 rounding boundary; shared results
allocate a fresh float, and unique results reuse their private accumulator.
The `_BINARY_OP_MULTIPLY_{ADD,SUBTRACT}_FLOAT_OWNED` variants also accept owned
factor references when the accumulator is already proved unique. They return
both factor references to the original exact-float cleanup uops, preserving
their order. Exact floats cannot run Python finalizers, so the update can
precede those decrements without exposing a boxed intermediate product.
`float_owned_entries` counts these updates and is included in
`float_unique_entries`. Existing type guards and the shared-accumulator path
remain in place. Tests compare finite results and signed zeros bitwise, and
NaNs by classification; NaN payload selection can differ between the debug
Tier-2 interpreter's C operations. Separate native diagnostics record payload
bits and floating-point exception flags as additional evidence.

The same `PYTHON_TIER2_FLOAT_FUSION=1` option also recognizes a straight-line
sum of three products of cached float attributes, for example:

```python
return self.x * other.x + self.y * other.y + self.z * other.z
```

`_FLOAT_ATTRIBUTE_SUM_PRODUCTS` retains the callee frame and replaces the six
attribute loads, three products, two left-associated additions, and their
temporary reference cleanup. Recognition follows the uops rather than names:
each product loads from the same two owner locals, which may alias or be the
same local. All six attributes must share a recorded nonzero type version and
layout kind (slots or managed inline values). Owner indices are limited to
0 through 7; field offsets must be pointer-aligned and fit in eight bits when
scaled by the pointer size. The search is bounded to 128 uops and cannot cross
calls, stores, periodic checks, or frame transitions. Layout annotations are
preserved before abstract interpretation removes redundant type guards;
matching runs before the existing product-update fusion.

The uop checks both owner types and managed-values validity when applicable,
then guards each field immediately after its pointer load. All six nonnull
exact-float checks precede any double loads or arithmetic. Keeping each check
next to its load avoids constructing six nullable results and testing them
again later in the native stencil. A failed guard resumes at the first
original `LOAD_FAST` with the unchanged entry
stack. The owner locals retain the attributes, and no callback or owner-local
replacement can occur within the region. This permits raw field reads without
temporary `INCREF`/`DECREF` operations. Attribute changes, numeric subclasses,
overridden attribute access, and instrumentation retain ordinary execution.

Explicit C evaluation boundaries preserve all five binary64 rounding points,
including the first product and the partial sum. Only the final result is
boxed, as a fresh float. Its allocation error uses the real callee frame and
the final original `ADD` position. That position is stored as an absolute
16-bit code-unit offset: the first `LOAD_FAST` need not have a surviving
`SET_IP`. Expressions beyond this encoding's range are left unchanged.
`float_attribute_entries` counts successful results, `float_guard_exits`
counts failed entry checks, and debug allocation injection accepts
`PYTHON_TIER2_REGION_FAIL_ALLOC=float_attributes`. The 64-bit GIL and GCC/Clang
restrictions apply to this new attribute region; it does not require call
regions to be enabled.

`executor.get_region_stats()` reports entries, guard/overflow exits, integer
boxing operations, and allocation errors. Counters are per executor; an entry
alone is not proof of success. Inspect deltas around the specific input and
check that the corresponding failure counters stay unchanged. `int_boxes`
counts boxing operations, including small-int cache hits, not heap allocations.

Debug builds support `PYTHON_TIER2_REGION_FAIL_ALLOC=int|len|float` to exercise
the fused allocation's error edge and in-frame handlers. The probe is absent
from release execution. It is intended only for private tests.
The probe requires no pending raised exception and uses the preallocated
`MemoryError` path. It is classified as non-escaping, so its presence in the
uop source does not force operand-stack publication in release code.
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
