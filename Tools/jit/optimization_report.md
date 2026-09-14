# Tier 2 region optimizations: design and experimental results

This report describes the local optimizations implemented and validated through
commit `a021ff543bcf618671bcb5fb5abe29944db608f6`, for review by CPython core
developers. The implementation extends the existing Tier 2 optimizer and
copy-and-patch backend: it removes intermediate object representations, combines
builtin calls with their consumers, eliminates selected leaf-call frames, and
lowers a restricted numeric loop to a native recurrence.

With all six experimental options enabled, the six standalone scripts in
[`benchmarks/`](../../benchmarks/) had a geometric mean execution-time ratio of
**0.492077 relative to the fixed main build**, or **2.032 times faster**. This
result is strongly concentrated in the Spectral Norm kernel: its ratio was
0.018425, while the other five scripts together had a ratio of 0.949200.
Whole-process time, including startup and warmup, had a ratio of 0.628911.
These are local, exploratory results on one Linux x86-64 machine. The options
remain disabled by default.

The measurement checkpoint is dated September 13, 2026. This report was written
on September 14 from the implementation, test logs, native-code probes, and raw
measurements. [`regions.md`](regions.md) is the compact usage and implementation
contract; [`plan.md`](../../plan.md) contains the development record.
The final section records a later local checkpoint using an arithmetic-mean
objective; the historical results above retain their original scope.

## Scope and integration

The starting revision, `2e3c7f3fc36fa6389f00c5de4a2010ccb0fc7127`, already
contained integer range experiments and float product/update fusion, including
unique and shared accumulator paths. This work added the general integer and
builtin regions, extended their consumers, and established additional numerical,
ownership, and native-code evidence for float fusion. The reciprocal-polynomial
range reduction described below is a later addition. The final measurement does
not select the older `PYTHON_TIER3_JIT` range modes.

The implementation uses the existing trace recorder, abstract interpreter,
dependency tracking, stack cache, uop replication, and stencil generator. LLVM
compiles stencils at build time. There is no additional runtime compiler,
assembler backend, or runtime expression interpreter.

| Environment option, set to `1` | Enabled transformations |
| --- | --- |
| `PYTHON_TIER2_INT_REGIONS` | Two checked signed-i64 operations, optionally followed by a comparison |
| `PYTHON_TIER2_BOUNDED_INT_REGIONS` | Small integer expression trees, including constant floor division and an immediate float-division consumer |
| `PYTHON_TIER2_BUILTIN_REGIONS` | Length consumers, string tail matching, tuple/list comparisons, enumerate iteration, compact range construction and iteration |
| `PYTHON_TIER2_FLOAT_FUSION` | Float multiply followed by accumulator addition/subtraction |
| `PYTHON_TIER2_CALL_REGIONS` | Selected argument/constant returns and cached-attribute leaf calls |
| `PYTHON_TIER2_FLOAT_RANGE` | Short reciprocal-polynomial range reductions; requires the bounded-integer lowering |

Set the options before traces are compiled. The integer, builtin, and call
regions require a 64-bit GIL build with GCC/Clang arithmetic support. Call-frame
elimination is additionally disabled with DTrace and on Emscripten. The float
range path also requires native 128-bit integer support and excludes those
configurations. Its paired arithmetic path additionally requires SSE2 and no
fast-math.

Pass order matters. In `_Py_uop_analyze_and_optimize`, attribute loads first
receive their recorded type-version annotations. Bounded integers, checked
integers, length consumers, and tuple comparisons are recognized before
abstract interpretation. This prevents facts established by removed compact-int
guards from being incorrectly propagated into the replacement. Abstract
interpretation also selects the direct string and range operations. Leaf-frame
elimination, list-pair fusion, and enumerate lowering follow it; float product
fusion follows removal of unnecessary uops. The float range matcher runs later
in `optimizer.c` and consumes the resulting bounded-integer uops.

## Integer values across several operations

### Checked signed-i64 regions

Representative shapes are:

```python
def arithmetic(a, b, c):
    return a * b + c

def predicate(a, b, c, limit):
    return a * b + c < limit
```

The matcher uses uop dependencies, not function names. It accepts exactly two
dependent additions, subtractions, or multiplications, with an optional integer
comparison. All nine operation pairs use `replicate(9)` to select arithmetic
during stencil compilation. The emitted native code has no per-operation
runtime dispatch. Recognition scans at most 32 uops and excludes intervening
calls, stores, frame transitions, and periodic checks.

Inputs must be exact Python integers representable as signed i64. Compactness
is a conversion fast path, not the semantic bound: noncompact exact integers
can use `PyLong_AsLongLongAndOverflow`. Booleans, subclasses, and values outside
i64 retain ordinary execution. Each arithmetic operation checks overflow in
Python evaluation order. If the product succeeds but the subsequent addition
overflows, execution resumes at the first operation with the original operands;
no partially computed Python state has been committed.

The first two references remain available on the operand stack and later inputs
remain in unchanged locals. `_INT_REGION` materializes only the final integer;
`_INT_REGION_COMPARE` returns a bool singleton without materializing either
intermediate or final arithmetic values. This matters most for predicates. A
boxed arithmetic chain still pays for conversion and its final object, and the
ordinary optimizer may already reuse the product's box.

### Bounded expression trees

The separate bounded path admits three to eight operations, including floor
division by a known nonzero integer. Leaves are local reads or small-integer
constants. Its fixed limits are a 128-uop scan, four additional local inputs,
and four native stack values. Exact input integers must lie in
`[-(2**28 - 1), 2**28 - 1]`; interval analysis proves that **every intermediate**
fits the existing signed 62-bit tagged-integer representation. A final result
fitting the bound is insufficient if an earlier operation does not.

`_INT_REGION_START`, `_INT_REGION_LOCAL`, `_INT_REGION_CONST`, and the replicated
arithmetic uops use `PyStackRef` tagged integers and the ordinary stack cache.
Known power-of-two floor divisions can become arithmetic shifts. A limited
common-subexpression rule duplicates the first native result when the same
local operands and operation occur again. This avoids recomputing `(i + j)` in
the numeric example below.

The entry operands must be borrowed or immortal. All required guards precede
the unboxed interval, which contains no allocation, callback, frame transition,
or side exit. Tagged intermediates are consumed before final materialization
can allocate or raise. Failed recognition or entry guards leave the ordinary
arithmetic path available. Final integer materialization errors use the first
original arithmetic instruction's error location.

An immediate `float_numerator / integer_result` can consume the native integer
directly. The numerator must be an exact borrowed or immortal float, guarded
before entering the region. Values in the exact binary64 integer range convert
directly; larger values materialize an integer and use `PyLong_AsDouble` to
preserve Python's conversion rounding. Division by zero and float allocation
errors use the original division instruction. Thus the common path removes the
denominator's intermediate PyLong, while the larger-value path deliberately
retains conversion machinery.

## Builtin calls and their consumers

### Length and string methods

`_CALL_LEN_CONSUMER` combines `len(value)` with comparison, addition, or
subtraction against a local integer or small-integer constant. Exact `str`,
`bytes`, `tuple`, `list`, and `dict` receivers expose their lengths directly.
The existing callable-identity guard remains, so replacing `len` or providing a
user-defined receiver takes the original call path.

`_CALL_LEN_LEFT_COMPARE` also handles a comparison whose right side is a length
or an adjusted length:

```python
def has_room(index, items):
    return index < len(items) - 1
```

The length and adjusted length remain native integers through all six
comparisons. Checked overflow returns to the original call before consuming
inputs. Arithmetic results needed as objects are boxed once; comparisons use
the existing bool singletons.

Mutable lengths are read at the call on every execution. The matcher cannot
move the read across mutation, calls, or periodic checks. Receiver ownership
also constrains fusion: closing a solely owned list or tuple could release an
element whose finalizer changes a later operand. The fast path therefore
requires a borrowed or immortal receiver, or another strong reference under
the GIL. Tests exercise finalizers and mutation as well as type guards.

For `str.startswith` and `str.endswith`, `_CALL_STR_TAILMATCH` requires the
actual builtin descriptor, an exact string receiver, one exact string affix,
and default bounds. It calls `PyUnicode_Tailmatch` directly. Existing call
guards, cleanup, and periodic checks remain; result-type propagation removes
redundant bool conversions. Tuple affixes, explicit bounds, keyword forms, and
overrides use the ordinary call. The gain comes from call/wrapper and consumer
overhead; the Unicode matching algorithm is unchanged.

Neither path should be described simply as eliminating an allocation per call.
Small lengths can already use cached integers, and bool results are already
singletons. The useful distinction is removal of dispatch, intermediate object
representations, and reference traffic, with heap-allocation savings only where
the original path actually allocated.

### Temporary tuples and adjacent list reads

The builtin group removes a newly constructed two-element tuple when its sole
consumer is `==` or `!=` against a local tuple. `_COMPARE_TUPLE_PAIR` requires an
exact right-hand tuple of length two. Each pair of corresponding elements must
have the same exact immutable builtin type: bytes, str, int, or float. Its
equality helper avoids Python callbacks and preserves tuple comparison's
identity shortcut, including for a shared NaN object. Large integer equality
compares sign, digit count, and digits without entering generic rich comparison.

Mixed types, subclasses, and comparisons that could issue `BytesWarning` fall
back at `BUILD_TUPLE`. The permitted operand ownership also prevents removing
the temporary tuple from changing an observable finalizer sequence.

A subsequent pass recognizes `(items[i], items[i + 1]) == pair`, including the
two list reads and index addition. It requires the same borrowed list/index
locals, an exact list, an exact compact integer index, and no intervening
effects. Both bounds are checked before comparing elements. Negative indices
are normalized independently: for `i == -1`, the second index is `0`. Failure
resumes at the first subscript, preserving evaluation and error order. List
contents are read anew each time. This shape occurs in the BPE tokenizer's
merge loop.

### Enumerate iteration and compact ranges

`_ITER_NEXT_ENUM_LIST` inlines the common `enumerate(list)` next operation when
the inner iterator is an exact list iterator, the index is cached, the cached
result tuple is uniquely referenced, and an element remains. The tuple remains
an actual observable object owned by the enumerate. Publication of its new
contents, release of old references, hash reset, and GC re-tracking follow
`enum_next`; an old element's finalizer may re-enter the same iterator.

Unsupported inner iterators, shared tuples, large indices, and exhaustion call
ordinary `enum_next` **inside the trace**. Only failure of the exact-enumerate
guard requires a type side exit. This replaced an earlier implementation that
repeatedly exited on ordinary fallback conditions. Normal exhaustion resumes
after `END_FOR`; other errors retain the saved `FOR_ITER` location. These are
distinct destinations: treating unsupported input as exhaustion would silently
truncate the loop.

The final addition specializes known `range(stop)` calls with exact compact
integer arguments and `GET_ITER` on known ranges with four compact integer
fields. `_CALL_RANGE_COMPACT` and `_GET_ITER_RANGE` share ordinary range and
iterator allocation helpers and freelists. They avoid repeated generic integer
conversion and length calculation.

The intermediate range object is retained across the original periodic check.
It still owns the original `stop`, creates its length separately, and is
released by the original iterator operation. Checking all four fields,
including `stop`, preserves the normal iterator choice even for empty ranges
with wide endpoints. Wider integers, bools, and `__index__` arguments use
ordinary construction. Allocation failures retain the original `CALL` or
`GET_ITER` location and cleanup.

## Eliminating selected leaf-call frames

`_CALL_PY_TRIVIAL` replaces an inlined call/return sequence whose entire body
returns an argument or an immortal constant. Recognition is bounded to 64 uops
and four explicit arguments. Existing function-version, argument-count,
recursion, and stack-space guards remain. The replacement also checks the
callee's instrumentation version before consuming the call stack, so tracing
or monitoring changes fall back to a real call.

The returned argument acquires a strong reference before other inputs are
closed. Cleanup follows the callee's reverse-local order, with the callable
last. Temporary references live off the visible operand stack during finalizer
reentry, since reentry may reuse consumed stack slots. The code object stays
strongly referenced through cleanup, including when a finalizer replaces the
function's `__code__`.

`_CALL_PY_ATTRIBUTE` extends this to short slot or managed-inline-value getters,
identity comparisons with `None`, and comparisons of two cached exact compact
integer attributes. A separate stencil family keeps the simpler return paths
small. Attribute offsets are paired with the **recorded** type versions before
abstract interpretation can remove redundant guards. Looking up a fresh type
version later would incorrectly validate an offset from an older layout.

At the call boundary, the replacement checks those versions, inline-value
validity, attribute presence, and required integer types before consuming
inputs. Missing attributes, descriptors, and subclass comparisons fall back to
the original call, preserving the frame needed for exceptions or callbacks.
This is a deliberately limited body recognizer, not general frame elimination
for arbitrary Python calls.

## Floating-point semantics

Product/update fusion preserves two binary64 rounding points:

```text
product = round_binary64(left * right)
result = round_binary64(accumulator +/- product)
```

`_PyFloat_MultiplyThenUpdate` uses a volatile `double` product as the C
evaluation boundary, including after stencil inlining. Native disassembly
shows separate `mulsd` and `addsd` instructions. The cancellation witness
`-1.0 + (1.0 + 2**-27) * (1.0 - 2**-27)` distinguishes these semantics from an
FMA: under round-to-nearest, the separate operations produce zero, while a
contracted operation can retain the small negative residual.

The unique path reuses a privately owned accumulator; the shared path produces
a new float so external aliases retain their original value. The shared path
does not necessarily save a heap allocation relative to an ordinary trace
that already reuses the product's box. Tests cover aliasing, guard order,
subclasses, allocation failure, signed zero, infinities, NaNs, subnormals, and
overflow/underflow. Validation of the shared path is a correctness result; the
initial panel did not establish a reliable speed benefit for it.

## Reciprocal-polynomial range reduction

The largest measured gain comes from replacing the repeated interpreter-level
work in a restricted loop with a native arithmetic loop. The standalone
Spectral Norm script contains this shape:

```python
def eval_A(i, j):
    return 1.0 / ((i + j) * (i + j + 1) // 2 + i + 1)

partial_sum = 0.0
for j in range(size):
    partial_sum += eval_A(i, j)
```

The matcher follows the optimized dependencies of an exact positional Python
call with at most four arguments. Its denominator must already be a supported
three-to-eight-operation bounded integer expression, and its numerator a
constant float. Other calls, stores, effects, or consumers reject the match.
Function names, `SIZE`, checksums, and benchmark identities are not inputs to
recognition. Tests use several different expressions and argument layouts.

### Polynomial setup and recurrence

The denominator is represented in the integer-valued basis
`1, j, j*(j - 1)/2`, with coefficients `c0`, `c1`, and `c2`. In the example:

```text
d(j) = (i + 1)*(i + 2)/2 + (i + 1)*j + j*(j - 1)/2
```

For the first index `s`, the setup computes:

```text
denominator = c0 + c1*s + c2*s*(s - 1)/2
delta       = c1 + c2*s
difference  = c2
```

Subsequent denominators need only `denominator += delta` and
`delta += difference`. Every original term is still divided and accumulated.
There is no closed-form floating-point sum or memoized result.

A bounded compile-time expression graph folds constants, shares expressions,
and factors divisions. For division by a constant, nonconstant coefficients
must divide exactly; the constant component retains Python floor rounding.
Runtime divisibility checks survive even when a later multiplication by zero
would otherwise remove their value. Powers of two use a mask and arithmetic
shift where permitted.

When signed-62-bit interval proofs succeed and the original frame has enough
unused operand-stack capacity, setup lowers to tagged scalar uops. Otherwise,
checked coefficient stencils use the executor's bounded four-by-three scratch
array. Neither path interprets expression nodes at runtime or adds unaccounted
stack slots. A further compile-time proof selects 64-bit endpoint setup when
all its intermediates fit; the conservative alternative uses 128-bit arithmetic.

### Entry, commit, and fallback

The fast path requires all of the following:

- An exact range iterator with step one and more than one remaining item; all
  remaining indices must lie in the small-int cache. The chunk is bounded by
  the cache span, 1,030 indices in this build.
- An exact, owned, uniquely referenced, non-NaN float accumulator; bounded
  integer arguments; and a null or exact-int previous induction local.
- Preserved function, recursion, stack-space, globals where applicable, and
  instrumentation checks, plus the original loop-header periodic check.
- A monotone denominator with a single nonzero sign throughout the chunk,
  entirely within `[-2**53, 2**53]`, so every integer-to-double conversion is
  exact. Endpoint and difference arithmetic must also pass the width proofs.

After successful setup, `_FLOAT_RANGE_REDUCE` performs the remaining arithmetic
without allocation or Python reentry. It commits the accumulator, iterator
position/length, and final cached induction value, then takes a copy of the
original exhaustion guard's exit with the stack expected after `END_FOR`.
Proof failure exits at the original `FOR_ITER` before loop effects. The
original trace is retained. The chunk contains no intermediate periodic check;
the cache bound limits the uninterrupted work, so this is not an unrestricted
long-loop transformation.

NaN accumulator inputs deliberately keep ordinary execution. Constrained
floating-point instructions alone cannot force identical payload selection
when native register-operand choices differ. The NaN regression uses a matching
warmed bytecode control with the range option disabled; an `operator.add`
control can select a different payload even in the ordinary JIT.

### Paired division with ordered accumulation

`_PyRegion_DivideThenAdd` preserves division rounding before addition. Under
Clang without fast-math, a local `FENV_ACCESS ON` produces constrained operations
that survive inlining without a volatile memory round trip. Other compiler
paths retain the volatile boundary. A local `FP_CONTRACT OFF` alone was
insufficient in the tested inlining configuration.

On SSE2, with all MXCSR exception traps masked, adjacent independent divisions
use the two lanes of `divpd`. Their results feed **two scalar additions in the
original order**:

```text
(term0, term1) = divide_two_lanes(numerator, (d0, d1))
accumulator = round_binary64(accumulator + term0)
accumulator = round_binary64(accumulator + term1)
```

The terms are never added together first. With traps enabled, the original
scalar division/addition sequence remains: a second division must not trap
before the preceding addition. Wider-denominator paired loops peel the last
one or two terms so recurrence updates remain within their proved bounds.

If the initial denominator, first difference, and second difference fit int32,
an additional endpoint check combines with monotonicity to prove that every
consumed denominator fits int32. The fastest path then uses packed integer
recurrences: `cvtdq2pd`, `divpd`, two ordered `addsd`, and two `paddd`
instructions form the central loop. Packed step updates use modulo-2**32
arithmetic, including for steps or unused final updates outside signed int32;
only proved int32 denominators are converted and consumed. An odd last term
uses the scalar helper. Wider values retain the paired int64 or scalar paths.

## Performance evidence and its limits

### Final six-script comparison

Both builds used GCC 13.3.0 at `-O3`, LLVM 21.1.8, frame pointers, and native
copy-and-patch JIT, without PGO or LTO. Stencil generation used
`-fno-vectorize -fno-slp-vectorize` in both builds for the documented LLVM
constant-pool-symbol workaround. Explicit SSE2 intrinsics remain available.
The host was an Intel Core i5-12450H; processes were pinned to CPU 2. The
governor was left unchanged. Builds, tests, and diagnostic probes did not run
concurrently with timings.

The fixed main revision was
`a60343ed17785ebbcd43de9080cadd8e2541db6f`. The candidate implementation tree was
`5411c3570b81161fde590e971fc10d9c837effb1`. The historical initial region-panel
baseline is a different revision and is not used for this main comparison.
The candidate/main executable SHA256 values are recorded in the manifests
linked below; `sys.version` alone is insufficient because the candidate was
built before its implementation commit and retains an older dirty revision
label.

Each of four blocks ran all six original script CLIs on both binaries, with
three warmups, ten measured values, and one loop per value. Main/candidate
order alternated; `PYTHONHASHSEED` was the block number. All **48 processes and
480 measured values** were retained, with no exclusions. The script inputs,
algorithms, and work counts were unchanged, and all reported checksums matched.
JIT stress and dump options were absent from timed runs.

For each script and block, the ratio is the arithmetic mean of its ten
candidate values divided by the corresponding mean for main. Script ratios
are geometric means across blocks; the overall result is an equal-weight
geometric mean across scripts. The millisecond columns below are arithmetic
means of all 40 values for each mode, so dividing rounded columns need not
exactly reproduce the paired ratios.

| Script | Main, ms | Candidate, ms | Candidate/main ratio |
| --- | ---: | ---: | ---: |
| `bpe_tokeniser.py` | 3006.598 | 2735.585 | 0.909866 |
| `btree.py` | 64.876 | 60.355 | 0.930317 |
| `deltablue.py` | 1.980 | 1.981 | 1.000295 |
| `hexiom.py` | 3.573 | 3.434 | 0.961082 |
| `raytrace.py` | 154.527 | 146.318 | 0.946874 |
| `spectral_norm.py` | 33.786 | 0.623 | 0.018425 |
| **Geometric mean** | | | **0.492077** |

Block geometric means were 0.493877, 0.490743, 0.491368, and 0.492327. The
0.949200 ratio for the other five scripts is a derived diagnostic showing the
concentration of the result; the reported six-script metric includes Spectral
Norm. DeltaBlue was essentially unchanged. These scripts were used during
optimization, not reserved as a holdout, and the standalone Spectral Norm
kernel is not the full pyperformance benchmark.

Whole-process elapsed time, including startup, warmups, measurements, and CLI
overhead, had a geometric mean ratio of **0.628911**. That metric did not reach
half the baseline. Equal script weights also mean the execution-time geometric
mean is not the ratio of total wall time spent running the entire suite. No
cross-machine confidence interval or full-pyperformance result is claimed.

### Evidence for the individual transformations

An earlier ten-workload panel compared individual feature groups with all
options off in the same binary. It was fixed before its timing results were
observed, but after initial implementation, and used three blocks. Selected
ratios illustrate where the general regions helped:

| Workload | Option enabled | Time ratio to that panel's all-off control |
| --- | --- | ---: |
| Integer arithmetic with comparison | Integer regions | 0.647 |
| Boxed integer chain | Integer regions | 0.999 |
| Header parser using lengths and prefixes | Builtin regions | 0.713 |
| Unique float accumulator | Float fusion | 0.751 |
| Shared float accumulator | Float fusion | 1.008 |

All ten workloads with all three original groups enabled had a ratio of 0.868.
The largest mean regression was about 2.1% in the dict control. A Unicode
parser control changed timing regime within one block; its unusually large
gain was retained in the raw data and is not treated as a uniform improvement.
Short/long prefix diagnostics also showed that the parser's benefit cannot be
assigned solely to `startswith`. These are historical ablations, not estimates
of each feature's independent contribution to the final six-script result.

Separate native probes establish execution rather than relying on elapsed time
alone. The final Spectral probe recorded 5,200 successful chunks containing
670,800 range iterations, all on the int32 path, with zero range guard exits.
The workload still evaluates 676,000 terms; first iterations and trace-entry
paths account for work outside those chunks. It also recorded 5,160 bounded
divisions and 5,160 calls through each compact range helper. The observed four
executors occupied 24,576 bytes of returned JIT code, including padding; this
is not a measurement of total process JIT memory or compile latency.

Paired stage comparisons retained all 90 values at each step. On Spectral,
paired division had a ratio of 0.77176 to its preceding scalar stage, int32
recurrences 0.93225 to the paired-int64 stage, and compact range operations
0.87883 to the preceding stage. These local comparisons explain successive
cost reductions; their benefits should not be added together.

For enumerate, a BPE diagnostic changed from 1,033,510 enumerate guard exits
to zero, with 81,840 ordinary fallback calls retained inside traces. Observed
executor count/code bytes fell from 72/348,160 to 38/180,224. Its immediate
timing gain was small (ratio 0.9954), which demonstrates why fewer exits alone
are not sufficient performance evidence.

## Correctness and review status

[`test_capi.test_opt_regions`](../../Lib/test/test_capi/test_opt_regions.py)
checks actual executors and counter changes as well as returned values. Its
cases cover overflow at different operations, large integers, bools and
subclasses, division errors, mutable containers, replacement of builtins and
descriptors, negative indexing, NaN identity, finalizer reentry, code-object
lifetime, monitoring, iterator exhaustion, and original error locations.

At the final implementation checkpoint:

- The final region suite ran 70 tests successfully in the debug Tier 2
  interpreter; native ran 70 with five debug-only skips.
- The preceding combined native region/optimizer/Tier 3/range run completed
  426 tests with eight skips. The subsequent addition was a debug allocation
  handler/cleanup test, followed by the 70-test region runs above. Related
  generator, range, iterator, GC, and monitoring suites were also checked.
- A separate final native diagnostic with all six options enabled passed 576
  cases across four rounding modes, with traps either all masked or
  `FE_DIVBYZERO` enabled, comparing result bits and floating-point exception
  flags. Another 56 special-value cases matched, including tested NaN payloads.
  These counts describe the diagnostic inputs, not exhaustive IEEE-754 or
  enabled-trap coverage.
- Generated uop/optimizer outputs were regenerated and checked for bytewise
  idempotence. Native executor disassembly confirmed checked arithmetic,
  separate multiply/update instructions, and the packed recurrence sequence.

Debug-only `PYTHON_TIER2_REGION_FAIL_ALLOC` injection exercises surviving
integer, length, float, conversion, and range allocation error paths, including
same-frame handlers and reference cleanup. Eliminated temporary allocations
are no longer allocation-failure sites; these tests do not claim otherwise.

Several limitations remain relevant to review:

- Five older tests asserting specific opcode shapes disagreed with fusion when
  the original experimental groups were all enabled; two already disagreed
  with float fusion alone. They were not changed to hide those failures.
  Default-configuration optimizer tests and focused enabled-path tests passed.
  The all-options-on opcode-shape suite is not claimed to be fully passing.
- An earlier `-R 3:3` run failed its memory-block check, growing by roughly
  61–62 blocks per repetition. A per-new-function growth reproducer showed the
  same growth in the unchanged archived JIT and candidate with options off/on.
  No additional feature-specific growth was detected there; the underlying
  growth remains unresolved and the refleak run is not a pass.
- Free-threaded and 32-bit execution, other architectures/compilers, ASan, and
  a full pyperformance comparison were not validated. `_decimal` and
  `_tkinter` were unavailable in both comparison builds.
- Full pre-commit hooks were not run: Black/prek were unavailable. Available
  lint and whitespace checks passed. This report does not constitute an
  independent human review or a proposal to enable the experiments by default.

## Source and evidence map

| Source | Review focus |
| --- | --- |
| [`Python/optimizer_regions.h`](../../Python/optimizer_regions.h) | Entry matching, scan limits, integer/length/tuple lowering, recorded attribute versions |
| [`Python/optimizer_region_bounds.h`](../../Python/optimizer_region_bounds.h) | Shared interval arithmetic for tagged integer proofs |
| [`Python/optimizer_analysis.c`](../../Python/optimizer_analysis.c) | Pass ordering, leaf calls, list-pair fusion, enumerate, float fusion |
| [`Python/optimizer_bytecodes.c`](../../Python/optimizer_bytecodes.c) | Abstract semantics and direct builtin selection |
| [`Python/optimizer_float_range.h`](../../Python/optimizer_float_range.h) | Range recognition, preserved guards and exits |
| [`Python/optimizer_poly_scalar.h`](../../Python/optimizer_poly_scalar.h) | Compile-time coefficient graph, exactness, stack and width proofs |
| [`Python/bytecodes.c`](../../Python/bytecodes.c) | Executable uop contracts, ownership, commit and error paths |
| [`Python/ceval_macros.h`](../../Python/ceval_macros.h) | Checked conversions, equality, coefficient and floating-point helpers |
| [`Objects/rangeobject.c`](../../Objects/rangeobject.c), [`pycore_range.h`](../../Include/internal/pycore_range.h) | Shared range allocation and compact conversions |
| [`Objects/enumobject.c`](../../Objects/enumobject.c), [`pycore_enumobject.h`](../../Include/internal/pycore_enumobject.h) | Ordinary enumerate semantics and shared internal layout |
| [`Python/optimizer.c`](../../Python/optimizer.c), [`pycore_optimizer.h`](../../Include/internal/pycore_optimizer.h) | Executor preparation, saved exits, scratch state and counters |
| [`test_opt_regions.py`](../../Lib/test/test_capi/test_opt_regions.py) | Feature and fallback regressions through real executors |

`executor.get_region_stats()` exposes per-executor counters for entries,
fallbacks, guards, overflow, materialization, and allocation errors. Entry alone
does not prove completion; use deltas and corresponding exit/error counters.
`int_boxes` and `bounded_boxes` count object-representation operations, including
small-int cache hits, rather than heap allocations.

Coverage probes also traverse outgoing executors through
`gc.get_referents(executor)`, deduplicating by identity. Only inspecting
code-attached roots can miss hot side traces. A side trace is not assigned to a
Python function merely because traversal reached it from that function's root.
Raw `get_jit_code()` bytes and stencil relocations provide the native evidence;
generated C alone does not establish native register allocation or instructions.

The following evidence is retained locally under the untracked
`jit-artifacts/` directory. These links are usable in this checkout; the files
would need to accompany any independently reproducible distribution of the
report. No GitHub publication is part of this work.

- [Final identity manifest](../../jit-artifacts/benchmark-suite/final-manifest.json)
  and [implementation/build manifest](../../jit-artifacts/benchmark-suite/range-objects-manifest.json):
  commit/tree identity, tracked dirty state at measurement, binary/configuration
  and stencil hashes. The former links the measurement checkpoint to its
  subsequent documentation commit.
- [Full tracked-source hashes](../../jit-artifacts/benchmark-suite/range-objects-source-hashes.json),
  [all six-script observations](../../jit-artifacts/benchmark-suite/range-objects-suite-rows.json),
  and [summary](../../jit-artifacts/benchmark-suite/range-objects-suite-summary.json):
  source/script identity, commands, explicit experiment environment, checksums,
  raw samples, and process elapsed times; per-process stdout/stderr is alongside.
- [Final Spectral native probe](../../jit-artifacts/benchmark-suite/range-objects-spectral-native.json),
  [rounding/trap checks](../../jit-artifacts/benchmark-suite/range-objects-fenv-all-native.json),
  and [special-value checks](../../jit-artifacts/benchmark-suite/range-objects-specials-all-native.json).
- [Debug region tests](../../jit-artifacts/benchmark-suite/test-range-objects-handlers-debug.log),
  [native region tests](../../jit-artifacts/benchmark-suite/test-range-objects-handlers-native.log),
  and [combined native tests](../../jit-artifacts/benchmark-suite/test-range-objects-final-native.log).
- [Initial region-panel summary](../../jit-artifacts/local-regions/summary-final.json)
  and the accompanying `local-regions/` probes, assembly, perf data, and
  unsuccessful refleak logs. Historical failures remain in the evidence set.

## Running the implementation and repeating checks

From the checkout root, use the native build and enable the desired options:

```sh
PYTHON_JIT=1 \
PYTHON_TIER2_INT_REGIONS=1 \
PYTHON_TIER2_BOUNDED_INT_REGIONS=1 \
PYTHON_TIER2_BUILTIN_REGIONS=1 \
PYTHON_TIER2_FLOAT_FUSION=1 \
PYTHON_TIER2_CALL_REGIONS=1 \
PYTHON_TIER2_FLOAT_RANGE=1 \
./build-jit/python benchmarks/spectral_norm.py --warmups 3 --values 10 --json
```

Check `sys._jit.is_available()` and `sys._jit.is_enabled()` in the selected
binary. A warmed executor must also return nonempty `get_jit_code()` before
claiming native execution. The debug Tier 2 interpreter is useful for
invariants and allocation injection, but its execution times are not native
JIT performance results.

Focused tests can be run sequentially as follows, from a shell without exported
experiment options; the region tests arrange their own feature settings:

```sh
PYTHON_JIT=1 ./build-tier2-debug/python -m test test_capi.test_opt_regions -v
PYTHON_JIT=1 ./build-jit/python -m test \
    test_capi.test_opt_regions test_capi.test_opt test_tier3 test_range -v
```

The local six-script runner reproduces the final block/sample design using the
preserved binaries:

```sh
python3 jit-artifacts/benchmark-suite/screen-float-range.py report-repeat 4 10
```

Use a fresh output prefix. That local runner pins CPU 2; select an allowed CPU
and record the change on another machine. Rebuild both binaries with matched
settings before comparing different source revisions. Keep tests and builds
out of the timing interval. Preserve the original samples and separate
diagnostic/stress runs from the comparison.

For source changes, follow the LLVM preflight and regeneration instructions in
[`AGENTS.md`](../../AGENTS.md), including all four case generators when relevant.
The most useful next review work is to audit guard/exit and reference-lifetime
contracts, resolve the known refleak and shape-test issues, and measure
profitability and code-size costs on independent workloads and builds before
considering broader enablement.


## September 14 follow-up: bounded attribute-list searches

The later `_CALL_PY_ATTRIBUTE_SEARCH` experiment eliminates calls implementing
a positional search over a cached list attribute. It proves the complete
original bytecode, including both returns and all jump destinations. A
successful call scans at most 64 exact tuple elements with exact compact
integer fields and returns a cached integer position. It avoids the callee
frame, enumerate iterator, and intermediate tuples. This is a structural
match; neither function names nor benchmark names select it.

The function version, instrumentation state, attribute layout, and current
callee-side resolution of `enumerate` and `len` are guarded. All argument and
stack checks preceding the original call remain. Guard failures resume the
original CALL, so Python comparison callbacks, descriptors, and exceptions
retain their real callee frame. The scan cannot allocate or call Python;
reverse argument cleanup and code lifetime preserve finalizer behavior. The
successful path ends the trace and resumes Tier 1 immediately after CALL.
[`regions.md`](regions.md) describes the exact supported body and guards.

The final matched comparison used the retained zip optimization checkpoint
`0ddb447533f` as its preceding candidate, the same fixed main executable as
before, CPU 2, three process blocks, and each script's original three warmups
and ten single-loop values. Native builds used LLVM 21 stencils at `-Os`, the
recorded vectorization workaround, and no PGO or LTO. All 540 result checksums
matched; no samples were excluded. Builds, tests, and probes ran separately
from these timings.

| Workload | Final / preceding candidate | Final / fixed main |
| --- | ---: | ---: |
| BPE | 0.997882 | 0.808582 |
| B-tree | 0.799769 | 0.569790 |
| DeltaBlue | 1.001024 | 0.967519 |
| Hexiom | 0.999817 | 0.831643 |
| Raytrace | 0.997551 | 0.824048 |
| Spectral Norm | 0.997532 | 0.018595 |

Entries are arithmetic means of the three per-block time ratios. The
six-workload arithmetic mean relative to main decreased from **0.694339 to
0.670030**. The current objective of 0.5 remains unmet. B-tree improved in every
block of two individual comparisons and two six-workload comparisons, by
roughly 19–20%. The other workloads' final directions were mixed. An earlier
search build had a 0.7% Hexiom regression across all three blocks; that result
is retained, although the final comparison did not reproduce a consistent
regression. These results do not establish a general application speedup.

The B-tree diagnostic observed 177,958 successful fused searches and no call
guard exits in its measured call. Its reachable executors decreased from 26
to 20, and native code from 258,048 to 135,168 bytes. Ten added search tests
cover layouts, argument conventions, all six comparisons, bounds, unsupported
types, mutation and callback behavior, finalizers, namespaces, code changes,
and monitoring. The final relevant ten-file runs passed 1,372 debug tests
(36 skips) and 1,285 native tests (47 skips). Eight generated outputs reproduced
byte for byte. A separate generator fix keeps replica IDs contiguous in
numeric order, including families with two-digit suffixes.

The final native executable SHA256 is
`d7185a95fc22975fff8b6f36926347bb11c5b29d859e10a8fa305a87043133e7`.
The local `jit-artifacts/benchmark-suite/attribute-search-final-*` files record
source/build identities, original samples, tests, counter probes, and native
assembly. Saved candidate executables share the current extension modules;
they are not complete independent build archives. Earlier unsuccessful call
mode replication trials and all comparison data remain in the local artifacts.


A subsequent change selects twelve search replicas by comparison operator and
explicit argument count. Each loop uses a direct integer comparison in place
of the repeated comparison-mask construction. The generic base stencil uses
bitwise boolean composition to avoid a jump table unsupported by the assembly
optimizer; all twelve actual replicas retain identical machine code across
that formulation change. The ten-file debug/native tests passed again, and
all eight generated outputs reproduced exactly.

The matched follow-up comparison improved B-tree by another **2.1%** (ratios
0.984554, 0.968711, and 0.984577). All checksums matched and no values were
excluded. The arithmetic mean relative to main changed from **0.674354 to
0.670577** in that comparison. Other workloads had mixed block directions;
the earlier 0.670030 result is a separate comparison, not its matched control.
B-tree's observed counters were unchanged, with 20 reachable executors and
131,072 native bytes. The adopted binary SHA256 is
`c94079b27ee5b3851c19346d09545fb4064789ff1adcf3521733562831828297`;
`search-comparison-*` holds its local evidence. The 0.5 objective remains open.


The next checkpoint fixes the countdown reset after successful root tracing.
Executor insertion can replace a short loop's `JUMP_BACKWARD_JIT` with
`ENTER_EXECUTOR` before finalization examines it. Testing the patched opcode
therefore selected the RESUME countdown (8190) instead of the loop countdown
(4000). `_Py_GetBaseCodeUnit()` recovers the original opcode. Configured
thresholds are unchanged. A regression test reproduces the failure to retrace
an invalidated short loop at its intended threshold; extended-argument loops
and C-driven function-entry calls provide controls. Both builds passed the
1,268 tests in seven related files (4 debug and 15 native skips).

This is retained as a correctness fix, with no speedup claim. A matched
three-block six-workload comparison changed the arithmetic mean relative to
main from 0.6686175 to 0.6691246. B-tree and Hexiom regressed in all three
blocks; DeltaBlue improved there but had mixed directions in its separate
comparison (geometric ratio 1.007766). All 540 suite checksums matched and no
samples were excluded. The before/after ten-value DeltaBlue coverage probes
observed the same counters, but cannot capture executors both created and
destroyed within a measured call. Native stencils were unchanged. The binary
SHA256 is `0e5b3a081be0820afefd878e56a5dc5c8639832c132bf12f06db44105c17571e`;
`retry-counter-*` records the local evidence. The arithmetic-mean goal remains
unmet.


## Conditional list removal (2026-09-14 follow-up)

The next experiment recognizes a complete three-argument Python function
implementing `if value in owner.cells[index]: ...remove(value); return True`,
with a False return on absence. It proves both branches and their destinations,
the repeated attribute/index, and the exact `remove` method name. Function and
attribute names are otherwise unrestricted. The implementation is enabled by
`PYTHON_TIER2_CALL_REGIONS=1`; the exact contract is in
[`regions.md`](regions.md).

Both the outer and inner lists must be exact lists, and the index and searched
value must be exact compact ints. Negative indices are supported. Scanning is
bounded to 64 elements and stops at the first match, without inspecting later
unsupported objects. A guard failure precedes mutation and resumes ordinary
Python. Successful deletion reuses `PyList_SetSlice()` and its guarantee that
deleting one item cannot fail. The removed exact int cannot invoke Python,
and the remaining elements retain their ownership. There is no intermediate
result allocation and no Python callback within the shared runtime helper.

`_CALL_PY_LIST_REMOVE` omits the callee frame while preserving the preceding
call checks, current function version, instrumentation, code lifetime, and
reverse argument cleanup. `_LIST_REMOVE_LOCAL` handles function-entry root
traces: it retains the real frame and resumes at the original branch's
RETURN_VALUE. Treating these paths separately matters when describing the
work eliminated. The call-site-only prototype reached just 339 operations
and five deletions in the first Hexiom diagnostic value. Adding the entry
path reached 2,675 operations and 395 deletions, with no guard exits. Native
code decreased from 77,824 to 73,728 bytes across 15 reachable executors.
The entry executor for `Done.remove` decreased from 8,192 to 4,096 bytes.

The ten-value coverage probe observed 2,675/2,716/2,717 operations in the first
three values, and 2,717 thereafter, with 395/436/436 deletions respectively.
All ten values had zero removal guard exits. These are separate diagnostics,
not the timing samples. Ten added tests cover both paths, layouts, argument
conventions, bounds, duplicate deletion, aliases, unsupported inputs, callbacks,
descriptor and code changes, monitoring, finalizers, and extra-effect bodies.
Both builds passed 1,469 tests in ten relevant files (4 debug and 15 native
skips), before the additional C-profile test. The final ten focused tests
passed in both builds, including the original list.remove C-call/C-return
events under profiling. All ten also passed with the other five experiment
flags disabled. Eight generated outputs reproduced byte for byte.

The final individual Hexiom comparison against the preceding countdown-fix
build used three rotated process blocks, the original three warmups and ten
single-loop values, and CPU 2. Ratios were 0.992870, 0.991241, and 0.992094
(geometric mean 0.992068). Comparing entry support against the call-site-only
prototype gave mixed directions (geometric mean 0.997752), so its incremental
speed benefit is not independently established.

The subsequent six-workload comparison preserved all 540 checksums and
excluded no values. Hexiom improved in all three blocks, with an arithmetic
mean ratio of 0.987740. BPE regressed in all three blocks, with a mean ratio
of 1.007009. The BPE diagnostic observed no removal operations; all existing
counters and its 34 executors / 167,936 native bytes matched the control.
That does not establish the cause of the timing regression. Other workloads
had mixed directions. The suite's arithmetic mean relative to fixed main
changed from 0.6713321 to 0.6704071; the 0.5 objective remains unmet.

The candidate binary SHA256 is
`c8d787052e4eabcc53fdbf9f3fca1727fcd3e97d033d859bbfd56b2ca4e499ff`.
The `list-remove-call-*`, `list-remove-local-*`, and `list-remove-final-*`
artifacts preserve source/build identities, original samples, tests, coverage,
and machine code. Both native builds used the same LLVM 21 stencil flags,
frame-pointer settings, and no PGO or LTO. Saved executables share the current
extension modules, whose identities are recorded by the probes.


A predeclared three-block BPE follow-up with the same fixed binaries gave
ratios 1.000629, 1.001148, and 0.997738 (geometric mean 0.999837), with matching
checksums and zero exclusions. It did not reproduce a consistent regression;
the original six-workload result remains part of the evidence. The combined
removal optimization is retained for its repeated Hexiom improvement, without
a BPE speedup claim or a claim that the entry path alone has a reliable benefit.
The native deletion call-table slot resolves to `PyList_SetSlice`, using a
load bias independently verified from the list and int type addresses.


## Globals identity and constant folding (2026-09-14 follow-up)

Investigating invalidation uncovered an independent correctness bug: a dict
copy can retain the original keys version while holding different values.
A function whose code already has a loop executor can be recreated with
`types.FunctionType(code, copied_globals)`. A keys-version-only guard then
allows constants from the original globals mapping to be used by the copy.
In the reduced case, eight additions of the copied value 19 returned **68**
instead of **152**: the first iteration used 19, and the seven JIT iterations
used the original value 7. This reproduced in both the preceding candidate
and the fixed main executable used for these comparisons.

`_GUARD_GLOBALS_VERSION_AND_IDENTITY` checks the actual mapping pointer as
well as its keys version wherever watched globals permit constant folding.
The existing dict dependency protects the borrowed mapping pointer: changing
or destroying that dictionary invalidates dependent executors before old
values or the mapping can be freed. No extra ownership is added to extend
their lifetimes. The ordinary dynamic global-load path remains available
when constant folding is not justified. The two call-pattern recognizers and
the float-range lowerer accept the stronger guard; the latter preserves the
entire instruction, including its namespace operand, in the region prefix.

Four added tests cover shared code with copied globals, structural mutation,
replacement and destruction of the original namespace, and a copied
float-range caller with a different term function. The first broad run caught
20 float-range formation subtest failures because that lowerer recognized
only the old guard; those failures are retained. After correcting the
recognizer, both builds passed 1,546 tests in thirteen relevant files
(4 debug and 15 native skips). Eight generated outputs reproduced exactly.
The reduced native example now returns 152, while the original still returns
56. B-tree and Spectral Norm probes retained their previous counters and
native sizes: 20 executors / 131,072 bytes and 4 / 24,576 bytes respectively.

The final native binary SHA256 is
`d4072ddeb417870a3f5f45c321cbae46047678e25d16f7358d7ae825c2bf949e`.
`globals-identity-*` and `copied-globals-*` preserve the local source/build
identities, failing and successful reproductions, tests, and coverage.
The compiler, stencil, frame-pointer, and no-PGO/no-LTO settings are unchanged.
This checkpoint is a correctness repair; the subsequent section describes
the separate change to the granularity of globals invalidation.


The matched six-workload comparison completed with 540 matching checksums and
no exclusions. Its arithmetic mean relative to fixed main changed from
0.6653419 to 0.6644558; the mean ratio against the preceding candidate was
0.9997148, with mixed block directions. BPE and B-tree improved in all blocks
(mean ratios 0.986170 and 0.996398); DeltaBlue and Spectral Norm regressed in
all blocks (1.003498 and 1.006191). Hexiom and Raytrace had mixed directions.
BPE's third control block was slower than its other two and remains included.
The previous 0.6704071 result was measured separately, not the matched control
for this change. The repair is retained for correctness, without a general
speedup claim. The 0.5 arithmetic-mean objective remains unmet. A native
reproduction with only `PYTHON_JIT=1` also returned the correct copied and
original results; the repair is not restricted to the experiment flags.


## Named globals dependencies (2026-09-14 follow-up)

The preceding watcher invalidated every executor depending on a globals
dictionary whenever any entry changed. DeltaBlue replaces its `planner`
global between constraint graphs; executors using other stable globals were
also discarded. An isolated reproduction confirmed this in both fixed main
and the preceding candidate. A value guard alone would not protect the
lifetime of folded constants, and retaining arbitrary global values would
change when their finalizers run. The implementation keeps dict notification
as the invalidation boundary and makes dependencies more selective.

Under `PYTHON_TIER2_CALL_REGIONS=1`, global constant folding adds domain-separated
Bloom tokens for dictionary structure and `(dictionary, unicode key hash)`.
Equal unicode keys share the latter token. A MODIFIED event with an exact
unicode key invalidates its key token and all legacy raw-dictionary tokens.
Every other event invalidates structural and legacy tokens. This covers
addition and builtin shadowing, deletion, clear, deallocation, and general-key
operations without invoking arbitrary key hashing in the watcher. False
positives only discard additional executors. Module-attribute folding retains
its original conservative raw-dictionary dependency in this version.

After invalidation, surviving structural dependencies keep the watcher
subscribed. The existing dictionary mutation count saturates at its unchanged
limit; the opt-in named path can continue folding beyond that limit. The
legacy path retains its limit. Both paths share the original collect-first
invalidation implementation and its allocation-failure fallback to invalidating
all executors. Namespace identity/version guards remain, and no value or
dictionary references are added. There are no new executor fields or watchers.

Seven new tests cover repeated unrelated changes, recompilation after repeated
referenced-value changes, finalizer reentry, a general-key replacement, builtin
shadowing, mixed legacy/named dependencies, and allocation failure during
invalidation. Retention checks use several namespaces/keys to allow individual
Bloom false positives; required invalidation and Python results are checked
in every case. Both builds passed the final eleven focused tests including
the previous namespace/lifetime/range regressions. Before the last two tests
were added, thirteen related files passed 1,551 tests (4 debug / 15 native
skips); a separate dict/watchers group passed 234 tests in each build. Eight
generated files reproduced exactly. The native stencil header is byte-for-byte
identical to the preceding identity-guard build.

The unchanged DeltaBlue probe, with three warmups and ten values, observed
attribute-call counts of 0, 0, 14, 100, 100, 100, 133, 598, 598, 598. The control
had zero in its first eight values, followed by 48 and 99. The candidate ended
with 14 reachable executors and 155,648 native bytes. These diagnostics show
earlier observed use of the existing optimization, but cannot count an
executor both created and destroyed within one measured call. Diagnostic
elapsed times are not used as benchmark evidence.

A separate matched DeltaBlue comparison gave ratios 0.967158, 0.965862, and
0.956110 (geometric mean 0.963031) against the preceding candidate. The full
six-workload screen also improved DeltaBlue in every block: 0.955686, 0.973587,
and 0.973046 (arithmetic mean 0.967440). Other workloads had mixed directions,
with means BPE 0.999160, B-tree 0.997842, Hexiom 0.997842, Raytrace 0.995609,
and Spectral Norm 1.002595. All 540 checksums matched and no values were
excluded. The suite's arithmetic mean relative to fixed main changed from
**0.6672309 to 0.6607413** in this comparison; the mean against the preceding
candidate was 0.9934147. The 0.5 objective remains unmet.

The implementation is retained for the repeated DeltaBlue improvement. The
candidate SHA256 is
`681e401eb5d4b312661e5a4514a22a680f06fd94a4b780d9c629bd8b5f4aaa2a`.
`named-globals-*` artifacts preserve source/build identities, tests, native
coverage, and all original samples. Compiler flags, warmups, inputs, and the
fixed main build are unchanged, with no PGO or LTO. Saved executables share
current extension modules; their hashes are recorded by the coverage probes.
