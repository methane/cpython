# PEP 805 implementation review and questions for Mark

Initial review on 2026-09-23 against commit `29709794bc`.
Follow-up implementation validated through commit `2fc691bbbe` on the same
date; see the resolved findings and validation below.
Re-read of the complete PEP and both appendices on 2026-09-23 against
`37899fe75b` (implementation unchanged since `2fc691bbbe`). The new findings
below supersede the earlier assessment of remaining work.
Previous re-review: 2026-09-23 against `afa12c7930`, after the sorting and
list/cell/function/tuple/bytes C API repairs. Implementation follow-up on
2026-09-24 repairs constant acquisition, bytearray exception propagation and
foreign executor invalidation, and extends the C API input cleanup. The
current assessment supersedes the historical probe results at the end.
The latest follow-up makes the parallel runtime the default configure build
and removes global-GIL enabling during extension imports. Earlier follow-ups
repair immediate LOCAL reclamation and identify the first denied reference
in the existing subinterpreter import failure.
The subsequent import audit checks bootstrap callbacks directly and shares
the lazy-import registries. The next follow-up ports bootstrap lock state
and freezes its sentinels; the default finder/loader pipeline still needs work.
The finder follow-up shares the default registries and selected builtin
loader entry points, and repairs private compiler and shutdown metadata paths.
A further fix restores static-type registration after Main reinitialization.
The frozen-import follow-up shares the four native lookup/loader helpers and
the `sys.implementation` namespace, with worker imports and parallel code
loading verified. The file-import follow-up below ports exact FileFinder
instances and the dependencies needed for source, bytecode and package imports.

Sources: [PEP 805](https://peps.python.org/pep-0805/),
[implementation appendix](https://peps.python.org/pep-0805/appendix-implementation/),
and [examples appendix](https://peps.python.org/pep-0805/appendix-examples/).
The PEP page reports its last modification as 2026-08-27.

This is an audit of the current experiment, not a claim of conformance.
Windows and native JIT execution were excluded as previously agreed. Code
inspection and targeted execution cannot establish coverage of every native
reference acquisition. The follow-up repairs concrete defects; it does not
complete the reference-counting and parallelism architecture.

## Re-review summary

**The implementation is not yet conformant.** Constant acquisition and
bytearray exception propagation are now repaired. Foreign sort elements are
also rejected, but sorting still continues after a callback closes its
protecting context. A foreign group collecting a legacy extension still
crashes. Default-build parallelism and the reproduced LOCAL reclamation delays
are now repaired. Compact headers, reference-count optimization and a complete
native acquisition audit remain unfinished.
These are implementation defects or unfinished work, not questions about
whether unsafe access or crashes are acceptable.

The preceding audit executed 15 distinct subprocess probes in each
Linux/aarch64 debug build, with timeouts and core dumps disabled. The constant
and buffer-exporter probes were repeated after their repairs. The table
combines those results with the unchanged findings from the prior audit.
New suite results are recorded in the implementation follow-up below.
A successful demo or selected suite does not demonstrate parallel execution
in the GIL build or close the remaining failures.

The free-threading configuration in this historical table is now the default;
the GIL configuration is explicitly selected with `--enable-gil`.

| Audited check | Free-threading debug | GIL debug | Assessment |
| --- | --- | --- | --- |
| Subscript a foreign LOCAL list loaded from `co_consts`, cold function | IllegalThreadAccessException | Same | Repaired at constant acquisition |
| Same function after 100 calls in Main | IllegalThreadAccessException | Same | Repaired; also tested with a Tier 2 executor |
| Foreign LOCAL elements in `list.sort()` | IllegalThreadAccessException | Same | Repaired |
| Close protecting generator from sort key | Sort completes after unlock | Same | Remaining reference-lifetime defect |
| Foreign GC with `xxlimited_3_13` | SIGSEGV in `xx_traverse`, line 457 | Same | Remaining compatibility defect |
| Last LOCAL reference deleted by another thread in the same group | Finalizer before `after del` | Same | Repaired, including weakrefs and resurrection |
| Last reference to a claimed LOCAL transfer | Finalizer before `after del` | Same | Creator's refcount bias retired before publication |
| Acyclic LOCAL functions and descriptors, including removal from a class | Reclaimed without GC | Same | Automatic deferred counts and delayed class-attribute decrefs repaired |
| Object header size | 56 bytes | 40 bytes | Compact representation unfinished; 24 bytes is illustrative |
| Buffer exporter tries to return a foreign memoryview | Buffer acquisition, join, concatenation and in-place concatenation raise IllegalThreadAccessException | Same | Exception propagation repaired |
| Transfer an ordinary instance | Primitive attribute readable; `__dict__` denied | Same | Question 4 |
| Rebind a read-only closure cell | Function changes SYNCHRONIZED to LOCAL | Same | Question 7 |
| `__str__` returns a `str` subclass | LOCAL subclass preserved | Same | Question 8 |

The other probes confirm rejection of an aliased `protect()` argument,
working tuple-iterator protection, rejection of a local load after its
protecting generator closes, and a dictionary view remaining LOCAL when its
dictionary is frozen. The last observation alone is not an access violation.

The default build now reuses PEP 703 biased reference counting, with
synchronous merging when the allocating thread belongs to the current locked
group. The fast path remains OS-thread-biased. Global GIL acquisition is
disabled by default and extension imports no longer enable it. The explicit
`--enable-gil` comparison build retains ordinary reference counts and global
serialization. The three cleanup fields remain in both headers
(`Include/object.h`); they implement deferred cleanup, not biased reference
counting. Mark's header-size and redundant-input-check comments remain only
partially addressed.

The input-check cleanup now covers bytearray, integer/float/complex and
Unicode accessors as well as the earlier container and function APIs. Raw
vectorcall arrays now use assertions in the common call, native-method,
descriptor and Python-frame entry paths. Heap acquisitions and revalidation
after potentially invalidating callbacks retain runtime checks. Other C API
families and their internal callers still need auditing.
`PyObject_GetItem` asserts its inputs and validates its returned reference.

## Implementation follow-up on 2026-09-24

- **Code constants:** `LOAD_CONST` now includes `_CHECK_CONST_ACCESS`. Keeping
  that check separate from the load preserves it when the optimizer replaces
  the load with an inline constant. Regressions cover cold and specialized
  execution, identity operations, protected constants and shallow immutable
  constants. A Tier 2 test requires an actual executor containing the inline
  foreign constant and its access check, then verifies rejection in another
  group. Both original cold/warm crash or bypass probes now raise the expected
  access exception in both default interpreter builds.
- **Bytearray buffers:** concatenation and in-place concatenation preserve
  IllegalThreadAccessException and UnprotectedAccessException from exporters.
  Regressions check both operands, the public C API, unchanged destination
  contents and release of an already acquired buffer when the next fails.
  Other buffer failures retain their existing TypeError behavior.
- **Executor invalidation:** a private VM work list retains executors through
  `_PyList_AppendTakeRef`, not the public `PyList_Append` API, because an
  executor may belong to a different group. Both dependency and cold-executor
  invalidation use this internal path. A regression first reproduced the
  public input assertion failure and now verifies that invalidation succeeds
  while Python acquisition of the foreign executor remains denied.
- **Tier 2 expectations:** an old generator fixture expected an access error
  only after yielding a foreign local. Checked local loads now reject that
  read inside the producer. The regression verifies the failing LOAD_FAST
  instruction and generator closure. Two optimizer tests now separately
  verify the original call/pop validity checks and the additional check after
  checked local loads. Their exception-construction path remains classified
  as escaping; it has not been made artificially non-escaping to remove a
  guard. Reducing this conservative overhead is still outstanding work.
- **Numeric C APIs:** another 23 input checks become debug assertions
  (18 integer, two float, three complex APIs). Together with five bytearray
  APIs and the previous 32 APIs, this follow-up series covers 60 APIs.
  Index/float/complex conversion-result checks remain. Complex conversion now
  also revalidates a subclass result after its deprecation-warning callback:
  a callback ending StopTheWorld previously allowed all three complex
  accessors to read the foreign result. The regression covers that rejection,
  allowed access and preservation of exceptions raised by the callback.

Validation before the numeric follow-up: the 74-file PEP/access/compiler/C API
selection passed in both Linux/aarch64 debug builds, reporting 2,378 tests
(351 free-threading skips, 357 GIL skips). After adding the executor regression,
four affected suites passed in both builds (349 tests, 333 skips). The skips
include Tier 2 tests because those two builds do not enable the optimizer.

A separate GIL debug build configured with
`--enable-experimental-jit=interpreter` executes the Tier 2 uop interpreter
without the native machine-code JIT. Its eight-file run of `test_const_access`,
`test_capi.test_opt`, `test_dis`, `test_peepholer`, `test_code`,
`test_generated_cases`, `test_bytes_access` and `test_capi.test_bytearray`
passed: 780 tests, five skips. This exercises the optimizer rather than
counting skipped tests as validation. Its initial build reported four unused
variable/function warnings; the optional `_decimal` extension is unavailable.

After the numeric changes, the 14-file selection covering numeric access,
warning filters, integer/float/complex C APIs and argument parsing, plus
`test_long`, `test_float`, `test_complex`, `test_math`, `test_cmath` and
`test_struct`, passed in all three builds: 529 tests, four skips per build.
Before the fix, the new complex warning regression failed for all three
accessors when the warning handler ended StopTheWorld without raising.
The two further numeric/abstract C API suites passed in each build (64 tests).
The sample application also passed in all three builds, calculating 61,620
and rejecting foreign LOCAL and unprotected PROTECTED access. These runs do
not measure parallel speedup.

The subsequent Unicode audit reproduced two more access violations without
depending on any of the open design questions. `str.join()` and
`PyUnicode_Join()` read foreign LOCAL string subclasses stored in an exact
tuple or list; the SynchronizedList iterator already rejected those reads.
Joining also retained a separator after an iterable ended StopTheWorld.
The fix validates references acquired from fast-sequence storage before
calling the internal array-join helper and revalidates the separator after
conversion that may invoke iteration. The regression checks singleton and
multi-element joins, both public entry paths, allowed debugger access and
preservation of the iterator's own exception.

Direct input checks in 27 public Unicode APIs and the internal UTF-8 encoder
become assertions, preserving null/type/error-output handling. Codec result
checks remain. The series now covers 87 public APIs, but this is not a claim
that every input check in those APIs' callees has been removed: for example,
the shared `_PyUnicode_EnsureUnicode` helper still performs a runtime check.

The Unicode follow-up passes the same 11-file selection in all three debug
builds: 908 reported tests with 23 skips per build. The selection is
`test_unicode_access`, `test_capi.test_unicode`, `test_capi.test_codecs`,
`test_codecs`, `test_str`, `test_string`, `test_format`, `test_fstring`,
`test_re`, `test_type_access` and `test_warning_filter_access`. Compilation
produced no warnings. Before the repair, the two new tests reported 17 failing
subtests. An initial suite invocation also named the nonexistent
`test_unicode` module; the corrected selection above was rerun successfully.

### Debug stack validation follow-up

Tier 1 generation now inserts `ASSERT_STACK_ACCESS` at successful instruction
dispatch for the outputs represented by its stack model. Direct frame pushes
also assert accessibility. These assertions do not run in release builds and
do not set or replace Python exceptions. The generator regression explicitly
checks that validation follows the access-check micro-op, including an early
dispatch, rather than the temporary GC spill before that check. Existing
generated-code fixtures retain their previous output with the new assertion
lines inserted.

The custom `_testinternalcapi` evaluator still declared a whole-instruction
`LOAD_CONST` override after the earlier repair converted it into a macro.
The generated macro retained its access check, but silently lost the test
evaluator's constant-load counter. Overriding `_LOAD_CONST` restores that
instrumentation while retaining `_CHECK_CONST_ACCESS`. A subprocess regression
checks protected constants before and after warmup and verifies that the load
counter is positive. Before the repair, it failed with `loads == 0`; the
access-denial assertions themselves already passed.

The remaining coverage limits are recorded in finding 8 below. In particular,
testing a Tier 2 build also exercises Tier 1 but does not establish equivalent
validation inside every Tier 2 micro-op.

Validation for this follow-up:

- Free-threading: the 43-file PEP/access selection reported 519 tests, with
  only the new load-counter regression failing before its repair. The final
  constant-access and `test_capi.test_misc` run passed 318 tests with 3 skips.
  The eight-file evaluator/generator/coroutine/monitoring selection passed
  674 tests with 3 skips, and `test_generated_cases` passed all 100 tests.
  These selections overlap and their counts must not be added together.
- GIL: 50 completed PEP/access/generator/evaluator files passed, reporting
  975 tests with 11 skips. All 12 tests selected by `Test_Pep523*` also passed.
- Tier 2 interpreter: the same selection plus `test_optimizer` passed in
  51 completed files, reporting 981 tests with 11 skips. The separate
  `test_capi.test_opt` file passed 333 tests with 3 skips, and all 12
  `Test_Pep523*` tests passed.
- The initial file-list invocation accidentally expanded dotted C API names
  to the whole `test_capi` package. Those unintended package workers were
  stopped; the completed files above remain valid, and the requested C API
  files were then invoked by their explicit dotted names.
- The complete `test_capi.test_misc` file **does not pass** in either GIL
  build: subinterpreter extension-import tests fail, and importing
  `_testcapi` from a subinterpreter aborts in `type_call()` with an exception
  already set. The single test
  `SubinterpreterTest.test_py_config_isoloated_per_interpreter` reproduces
  the same abort in a separately rebuilt, unchanged `3657b0d87c` GIL tree.
  It is an existing compatibility defect, not a failure of the new stack
  assertion. The free-threading build skips this particular test by its
  existing `requires_gil_enabled` decorator.
- Compilation succeeds in all three builds. The GIL and free-threading
  builds have no warnings; Tier 2 repeats its four previously recorded unused
  variable/function warnings. The final custom-evaluator rebuild repeats
  only the existing `dump_cache_item` warning.

### Immediate LOCAL reclamation follow-up

The free-threading counterexample in finding 2 now finalizes before the
statement after `del`, as the GIL build does. `_Py_brc_queue_object()` merges
immediately if the current thread holds the allocating thread's group lock.
That lock prevents the allocator from changing its local count; the BRC
bucket lock protects its thread-state record. Other-group owners retain the
existing queue path. Deallocation runs after releasing the bucket lock.
This preserves the OS-thread-biased representation; it is not a completed
group-biased implementation or default-build port.

Two other sources of delayed reclamation were reproduced and repaired:

- A `TransferBox` copy retained its creator's bias after being claimed by a
  different group. Its counts are now merged before the unaliased copy loses
  its group ownership, so its receiver need not wait for the creator's queue.
- LOCAL functions and method wrappers received deferred reference counts
  automatically. Function creation and class publication now enable those
  counts only for shareable values; LOCAL classmethod/staticmethod wrappers
  retain ordinary counts. Removing a LOCAL attribute from a LOCAL class also
  retained a real reference in the delayed-decref queue. After invalidating
  the type cache and releasing its locks, a world-stop barrier now waits for
  outstanding cache readers, then resumes execution before releasing that
  reference. This avoids freeing memory under lock-free readers. Its global
  synchronization cost is an outstanding optimization concern.

`test_local_reclamation` disables GC in its lifetime probes. It covers
same-group deletion in Main and a new group, finalizers, weakrefs,
resurrection, claimed transfers, acyclic LOCAL functions, and five descriptor
forms both directly and through class creation/assignment. A separate test
updates a LOCAL class while another group looks up attributes through a
frozen instance. Before these repairs, four same-group finalizer cases,
the transfer ordering case, and 16 function/descriptor subtests failed in
free-threading; the corresponding GIL cases passed. Fixing deferred flags
alone still left 13 failures, which exposed the class-attribute queue path.

Validation after all repairs:

- Free-threading: 16 files, 805 reported tests and 20 skips; no test assertion
  failures. `test_free_threading.test_type` reported a changed
  `threading._dangling` environment. Its isolated rerun with
  `--fail-env-changed` passed all 13 tests without the warning; the cause of
  the first warning has not been established.
- GIL: 14 files, 786 reported tests and 23 skips, all passed.
- Tier 2 interpreter: 10 files, 622 reported tests and 13 skips, all passed,
  including `test_optimizer` and `test_capi.test_opt`.
- Free-threading reference-leak checking (`-R 3:3`) passed `test_gc`,
  `test_weakref` and `test_capi.test_object`: 218 reported tests, 13 skips,
  with no positive reference deltas in the measured repetitions.
- All three builds compiled successfully without warnings in this incremental
  rebuild. An earlier test invocation named a nonexistent
  `test_capi.test_refcount` file; the final selections use the existing
  `test_capi.test_object` suite instead.

These selections overlap. The subprocess lifetime tests demonstrate ordering
and prompt reclamation, not absence of every native leak. Broader refcount
coverage, the compact header and default-build parallelism remain open.

### Native call acquisitions and callback boundaries

Raw vectorcall arguments are now treated as already-acquired thread
references. The common call adapter, Python-frame setup, native function and
method-descriptor adapters assert that invariant in debug builds instead of
raising access errors on those inputs in release builds. Method constructors
and accessors follow the same input contract; accessors still check returned
references. `_Py_CheckFunctionResult()` retains return-value validation.

The checks needed at actual heap acquisitions remain explicit:

- Tuple-based calls, tuple expansion in `PyObject_CallFunction("O", tuple)`,
  keyword names and values, and bound-method fields are checked when unpacked.
  The `_testcapi` raw-vector adapter now checks its own tuple reads.
- Attribute lookup and format converters may invoke callbacks that end
  protection. Surviving arguments are revalidated at those sites, and the
  interpreter retains its checks after argument evaluation and monitoring.
  Regressions end StopTheWorld inside a property lookup or an `O&` converter
  and verify rejection before entering the intended callee. This preserves
  existing behavior without claiming to solve question 1's general lifetime
  problem.
- `_PyStack_UnpackDict()` previously decrefed the full argument allocation
  when rejecting a partially unpacked dictionary, including uninitialized
  slots. A direct internal-helper regression reproduced SIGSEGV at all three
  rejection positions. Cleanup now releases only initialized keyword values.
  Weakrefs verify that earlier values are released, and valid, empty and
  non-string-key dictionaries retain their expected behavior.

Broader validation also exposed two related compatibility paths:

- A closure-bearing method initially classified LOCAL can become SYNCHRONIZED
  when its cells are attached. That creation path now enables deferred
  counting under the same conditions as other shareable methods. The existing
  `LOAD_ATTR_PROPERTY` specialization regression passes again, while the LOCAL
  immediate-reclamation regressions remain intact.
- Creating an `lru_cache` in another group was rejected while obtaining its
  defining module's native state. `_functools` now uses an internal metadata
  lookup; the public module-returning API still checks access. The cache's
  private keyword marker is explicitly immutable. Without that declaration,
  four cached keyword-call variants still rejected the Main-owned marker.
  Tests cover disabled, unbounded and bounded caches, both `typed` modes,
  hit/miss accounting and clearing.

Reading cache-info fields also exposed `PyDescr_IsData()` setting an access
exception while the VM was only inspecting a descriptor's native slot flags.
Its callers treated the error as a true predicate, eventually aborting with
an exception pending. The public predicate now asserts its input contract;
VM lookup inspects native slot metadata directly. A regression reads a field
of an instance of a frozen namedtuple class in another group while still
requiring acquisition of the LOCAL descriptor itself to raise. This does not
declare arbitrary descriptors or extension modules shareable, nor resolve
legacy extension GC compatibility.

Final validation for the call/metadata follow-up:

- Free-threading: all 38 selected files passed, 1,878 reported tests, 4 skips.
- GIL: all 36 selected files passed, 1,873 reported tests, 12 skips.
- Tier 2 interpreter: the GIL selection plus `test_optimizer` and
  `test_capi.test_opt` passed in 38 files, 2,212 reported tests, 15 skips.
- The demo passed in all three builds with result 61,620 and both expected
  access denials. This is functional validation, not a speedup measurement.
- All modified source/test files match the two build mirrors. Compilation
  succeeds; the Tier 2 header rebuild repeats its four recorded unused-code
  warnings, and the final incremental rebuild has no warnings. `_decimal`
  remains unavailable. `git diff --check` passes.

The selection includes native calls, attributes, cells, frames, generators,
coroutines, finalizers, monitoring/profiling/tracing, method/descriptor and
functools behavior, LOCAL reclamation, and the C API evaluation/function/type/
slot/abstract suites. An initial invocation named the nonexistent
`test_sys_monitoring`; the final selections above use `test_monitoring`.
The results overlap and must not be added together. They do not close the
known subinterpreter import failure or establish full-suite conformance.

### Tuple-array acquisition follow-up

`PyTuple_FromArray()` now asserts accessibility of its C-array inputs rather
than checking it at runtime. Its native-call, exception-construction and
Argument Clinic callers already have valid argument references. Container
storage callers use `_PyTuple_FromArrayChecked()` to retain their existing
acquisition checks before crossing that boundary: list-to-tuple conversion,
C API and specialized tuple slicing, struct-sequence reduction and four
itertools cached-result copies. Null/size handling and tuple GC tracking are
unchanged.

The `_testcapi` array adapter now uses checked tuple acquisition. Its legacy
`PyEval_EvalCodeEx` adapter also checks positional/default tuple elements and
propagates errors from `PyDict_Next` instead of continuing with a partially
filled keyword array and an exception pending. Regressions cover each input
source, denial before the target executes, allowed calls under protection,
and reference release on tuple-construction failure.

The broader sequence suite exposed another missed heap acquisition following
the prior call-input assertion change: SQLite invoked its stored default
cursor type without validating that reference. It now validates that field
before calling it; explicit factory arguments retain the normal valid-input
contract. The existing SQLite access regression reproduced the assertion.

During development, changing only the public array check to an assertion
caused nine new subprocess cases to abort. Fixing their callers restores the
expected access exceptions. A tenth exploratory expectation was incorrect:
ordinary Python tuple slicing copies storage directly, whereas the C API
slice path calls the array constructor. That expectation was removed from
the new test; the public C API slice regression remains. This change preserves
existing acquisition checks and does not establish uniform acceptance of
inaccessible elements across all shallow-copy implementations.

Validation for the tuple-array follow-up:

- Free-threading: 21 files passed in the initial 22-file selection (1,421
  reported tests, 20 skips); the sequence worker aborted at SQLite's cursor
  factory acquisition. After that repair, `test_sequence_access` and the
  complete `test_sqlite3` package passed (564 tests, five skips).
- GIL: the 23-file selection, including SQLite, passed (1,985 tests, 20 skips).
- Tier 2 interpreter: the same selection plus `test_optimizer` and
  `test_capi.test_opt` passed (2,324 tests, 23 skips in 25 files).
- The demo passed in all three builds, returning 61,620 and rejecting both
  foreign LOCAL and unprotected PROTECTED access. All ten changed source/test
  files match between the three build trees. Compilation succeeds, with only
  the four previously recorded Tier 2 unused-code warnings; `_decimal` remains
  unavailable. `git diff --check` passes.

The selection covers tuple/list/struct-sequence/itertools behavior, native
calls and call expansion, Argument Clinic, relevant C APIs, protection,
constants, exceptions, strings, monitoring, GC and LOCAL reclamation. It does
not close the remaining parallelism, header, lifetime or compatibility gaps.

### Default parallel runtime and extension imports

The canonical configure build now selects the existing free-threading
substrate without requiring `--disable-gil`. This provides biased reference
counting, parallel allocation and GC while the ThreadGroup scheduler retains
serialization within Main and each other group. The reference-count fast
path and object headers are unchanged by this configuration change.
`--enable-gil` explicitly selects the legacy serialized comparison build;
`-X gil=1` remains an explicit runtime diagnostic option in the parallel build.

Extension import no longer enables the global GIL, either transiently during
initialization or permanently afterward. This includes single-phase imports,
multi-phase modules with no GIL slot, and the module-export/slots API. The
`Py_mod_gil` slot remains accepted for compatibility but does not make a
module or its objects shareable. The new test checks five import variants,
LOCAL module ownership, and two distinct groups meeting at a native barrier
while both retain their execution rights. A single-phase fixture also checks
that the GIL is disabled inside its initializer. Existing same-group
serialization tests remain in place.

Making the free-threading substrate the default must not silently change the
classic defaults for context inheritance and warning contexts. Both flags
therefore default to zero in compatibility, Python and isolated configuration
initializers. Explicit options remain supported. Configuration, embedding
and thread behavior tests exercise these defaults. Old extension-import
expectations that the GIL becomes enabled now instead require the scheduling
state to remain unchanged, with import warnings treated as errors.

The expanded regression run also exposed two earlier acquisition defects.
Import paths acquired the interpreter's stored LOCAL importlib module without
checking it before calling public attribute/call APIs. Those acquisitions
and the stored import callable are now checked; the cached module reference
is revalidated after testing the from-list's truth value, which can invoke a
callback. When the traceback formatter or
import machinery is inaccessible, the native exception printer handles the
original worker exception without reporting that expected denial as another
unraisable exception. The existing seven failing subprocess cases in
`test_thread_error_output` now pass unchanged. The `test_freeze` native helper
also checks its tuple element before supplying it as a call argument;
foreign ownership is rejected before executing `__freeze__`.

These repairs do not make importlib or traceback modules shareable. Foreign
groups can still be unable to initialize modules through LOCAL bootstrap
state; the bootstrap's sharing and acquisition audit remains unfinished.
The compact-header, C-reference lifetime and legacy GC/subinterpreter
compatibility findings below also remain open.

Validation on Linux/aarch64:

| Configuration | Selected files | Reported tests | Skips | Result |
| --- | ---: | ---: | ---: | --- |
| Default, configured with only `--with-pydebug` | 52 | 3,597 | 65 | Passed |
| Legacy `--enable-gil --with-pydebug` | 52 | 3,597 | 61 | 51 files passed; six existing failures in `test_import` |
| Legacy GIL plus Tier 2 interpreter | 54 | 3,936 | 64 | 53 files passed; the same six failures in `test_import` |

The selection includes the previous 23 tuple/call/access suites, threading,
context and warning behavior, extension import/configuration, command-line
and sysconfig checks, finalization, protection, transfer, synchronized
collections, freezing, and the full `test_import` and `test_traceback` files.
Tier 2 additionally executes `test_optimizer` and `test_capi.test_opt`.

The six import failures occur in four methods: the two
`SinglephaseInitTests.test_basic_multiple_interpreters_*` methods,
`SubinterpImportTests.test_single_init_extension_compat`, and three subtests
of `SubinterpImportTests.test_singlephase_check_with_setting_and_override`.
They report owner group 1 versus the subinterpreter's distinct Main group.
The saved GIL baseline at `3657b0d87c` reproduces all six failures in the same
tests, before this follow-up. These are additional reproductions for question
9, not successful compatibility validation. The default parallel build does
not exercise all of these legacy-GIL cases.

The 11 selected embedding-configuration tests pass in each configuration,
with one existing skip. An explicit `-X gil=1` scheduler selection also passes
(three reported tests, one parallel-only skip). All three sample-app runs
produce 61,620 and reject both forbidden access cases. The canonical runtime
reports `Py_GIL_DISABLED=1`, `sys._is_gil_enabled() == False`, both context
flags zero, and a 56-byte object header. No header-size improvement is claimed.

The changed runtime/test sources match across the three build trees.
Incremental repair builds emit no compiler warnings; the initial Tier 2
build retains the four previously recorded unused-code warnings. The optional
`_decimal` module remains unavailable. `git diff --check` passes. Logs and
the exact suite selection are in `/tmp/pep805-default-build/`.

### Import callback acquisition and lazy-import metadata

The preceding import checks prevented a worker from representing even its
own module, because the interpreter's bootstrap module belongs to Main.
Native import paths now fetch a bootstrap attribute through the private
namespace and check the acquired value. As with a function's globals, this
does not publish the metadata container itself. LOCAL callbacks remain
inaccessible, and PROTECTED callbacks require their lock. Lazy bindings,
missing attributes and module subclasses retain ordinary attribute lookup
with its receiver check. Surviving call arguments are revalidated after a
lookup that can invoke user code; a regression ends StopTheWorld inside
`__getattr__` and verifies rejection before calling with the foreign module.
The bootstrap reference can also be absent during teardown. An embedding
regression reproduced a NULL dereference in that case; the helper now reports
ImportError and works normally again after the bootstrap reference is restored.

There was a second obstruction to module representation: every missing
attribute consults the interpreter's lazy-import registries, whose LOCAL
dictionary caused an access exception even for a worker-owned module.
The registry dictionary, its per-parent sets, and `sys.lazy_modules` now use
synchronized containers. Allocation failure during registry initialization
is propagated before trying to initialize the next container. The new tests
check ordinary AttributeError behavior, resolution of a submodule registered
in another group, and concurrent registration of 64 names from four groups.

The remaining import restriction is concrete implementation work, not a
request for Mark's approval. With the original bootstrap callbacks, a fresh
worker import of `_ast` still fails in `_find_and_load` while acquiring the
LOCAL `_NEEDS_LOADING` sentinel. The lock-management classes and graph,
`_module_locks`, `_imp`/other native dependencies, and the external finders and
path caches also need an explicit sharing policy and concurrency review.
No blanket declaration that bootstrap modules or their contents are safe
has been added. The successful custom-hook tests do not establish that the
default finder/loader pipeline works across groups.

Validation for this follow-up:

- Before the final NULL guard, the nine-file selection of `test_import_access`,
  `test_importlib`, `test_lazy_import`, `test_import`, `test_module`, `test_sys`,
  `test_threadgroup`, `test_thread_error_output` and `test_freeze_module`
  passed in the default parallel debug build: 1,700 tests, 41 skips.
  The legacy GIL and Tier 2 builds each passed eight files and reproduced
  the six existing `test_import` failures (1,700 tests, 31 skips each).
  Targeted verbose reruns confirm that all six failure identities match the
  saved `3657b0d87c` baseline recorded above.
- After the NULL guard, all 14 import-access regressions and the new embedding
  test pass in each of the three configurations: 15 tests per build, no skips.
  Five of the first eight regressions failed before the callback repair.
  The two lazy-metadata regressions failed before synchronizing the registries.
  A further regression caught a lazy callback being called before resolution;
  lazy bindings now fall back to ordinary attribute resolution. The embedding
  test reproduced SIGSEGV before the NULL guard. An initial debugger-context
  fixture mistakenly called the StopTheWorld singleton; that fixture was
  corrected before the final runs.
- The default sample application still produces 61,620 and rejects the two
  forbidden access cases. Changed runtime/test sources match across the build
  trees; final builds emit no compiler warnings. `git diff --check` passes.
  Logs and the remaining ordinary-import probe are in `/tmp/pep805-bootstrap/`.

### Bootstrap locks across ThreadGroups

The two identity-only sentinels, `_NEEDS_LOADING` and `_POPULATE`, are now
frozen. The module-lock registry uses SynchronizedDict, and the exact
`_ModuleLock` instances publish a synchronized namespace with synchronized
recursion and waiter lists. The existing native RLock still serializes
compound lock-state changes. Subclasses remain LOCAL, since their additional
state has not been audited.

Deadlock detection also reads other threads' wait lists. These lists now use
SynchronizedList storage behind a frozen, weak-referenceable wrapper. The
weak-value mapping retains weak ownership, pending-removal bookkeeping and
the atomic dead-reference check; it does not keep lists alive after their
last user exits. Its weakrefs are exact native references with the key held
in a callback closure, replacing the mutable `KeyedRef` subclass. The mapping's
namespace and containers are synchronized. This preserves cleanup when a
worker-created module lock is last released in a different group.

Bootstrap setup explicitly shares the lock-management classes and three
native helpers: import-lock acquire/release and atomic dead-weakref removal.
Those functions use the native import mutex or dictionary locking and do not
read their bound module's state. Bootstrap retains checked references to
these helpers without exposing the LOCAL `_imp` or `_weakref` module.
Foreign LOCAL values inserted into the shared lock registry are still
rejected before they can be called.

`test_import_lock_access` runs six cases against both source and frozen
importlib: recursive use of another group's lock, four-group contention on
one registered lock, worker-created lock lifetime, a cross-group deadlock,
LOCAL subclass storage, and denial of an inaccessible registry callback.
Before the repair, eight subtests of the original five cases failed.
The existing 34 import-lock tests also passed in the first focused run.

This completes the lock-graph portion of the preceding import finding,
not the full import port. A fresh worker import of `_ast` now passes the
sentinel and module-lock paths and fails when the audit arguments acquire
`sys.meta_path`, which is still LOCAL. The finder registries, native loader
dependencies and external path caches remain independent implementation
work. The successful direct lock tests do not prove that this default
finder/loader pipeline works across groups.

Validation logs and the ordinary-import probe are in
`/tmp/pep805-import-locks/`. Frozen importlib was regenerated before building
each configuration. The sample still computes 61,620 and rejects foreign
LOCAL and unprotected access.

The final nine-file selection (`test_import_lock_access`, `test_import_access`,
`test_importlib`, `test_lazy_import`, `test_import`, `test_module`, `test_sys`,
`test_threadgroup`, and `test_weakref`) passes in the default parallel debug
build: 1,820 reported tests, 45 skips. The legacy GIL and Tier 2 comparison
builds pass eight files and report the same six existing `test_import`
failures (1,820 tests, 35 skips each). Targeted verbose reruns confirm all six
failure identities match the saved `3657b0d87c` baseline. The source and frozen
lock cases pass in all three builds. An earlier selection mistakenly named
`test_threaded_import` as a top-level test; its load error was a command error,
and the actual suite is included under `test_importlib` in the final selection.
Changed runtime/test sources match across the three trees, the builds emit
no compiler warnings, and `git diff --check` passes.

### Finder registries, builtin imports and private runtime metadata

`sys.meta_path` and `sys.path_hooks` now start as SynchronizedList, and
`sys.path_importer_cache` as SynchronizedDict. Bootstrap explicitly
synchronizes ModuleSpec, BuiltinImporter, FrozenImporter and PathFinder.
Instances and values stored in the registries retain their individual states.
The `_imp` namespace is now synchronized; an audited allowlist of native
functions is shared for builtin imports and lazy-import setup. This does not
implicitly share every `_imp` function or imported extension module.

`PyImport_GetImporter` holds an owned reference to a hook while calling it,
rechecks retained values after callbacks that can end protection, and checks
its final returned finder. Incoming path arguments are asserted accessible.
The C API test helper and a new direct API test cover caching, failed hooks
and NULL input. Cross-group tests cover shared finders and hooks, rejection
of foreign LOCAL entries, and debugger access ending inside a hook.

First import of `_symtable` or `_ast` in a worker exposed additional bugs:

- AST classification tried to acquire the canonical AST class through a
  public API. It now uses the existing private native subtype helper for
  an ordinary class, retaining checked `__class__` lookup and custom
  metaclass access. AST deallocation also reads native type metadata
  directly. AST classes are not implicitly made shareable.
- The symbol-table wrapper now propagates an AST-classification exception
  instead of treating its negative result as true.
- Inherited globals and builtins are retained as private frame metadata for
  eval/exec. Acquired names and individual loaded values remain checked;
  writing an inaccessible namespace is still rejected.
- Shutdown traverses module storage privately and builds callback-free
  metadata weakrefs, including reuse of a weakref owned by a stopped group.
  It no longer leaves an access exception pending before cyclic GC.

The ten new `test_import_finder_access` cases pass in all three builds.
The default 20-file regression selection reports 2,700 tests and 69 skips:
19 files pass, with one `test_embed` repeated-initialization failure. The
tenth new case was added afterward and passed in a rerun of the complete
new file. GIL/Tier 2 report 2,701 tests and 62 skips: 18 files pass, with
the six prior subinterpreter import failures and the same embedding failure.
The embedding failure also reproduces in the saved `3657b0d87c` baseline;
GDB identifies `LegacyGetAttr_Type` retaining its old Main owner because
`PyModule_AddType` skips the existing reinitialization path for ready types.
That is separate follow-up work, not a reason to wait for question 9.

Runtime/test sources and generated AST/importlib files were checked across
builds. Default/GIL builds emit no compiler warnings; Tier 2 retains the
four previously recorded unused-variable/function warnings. The sample
still computes 61,620 and rejects foreign LOCAL and unprotected access.
Logs are in `/tmp/pep805-finders/`.

The general file-loader pipeline remains incomplete: a fresh worker import
of `colorsys` now fails while acquiring `_imp.find_frozen`. Frozen-loader
native helpers, external finder/loader dependencies and cached finder state
remain implementation work that does not require Mark's feedback.

### Re-registering static types after interpreter reinitialization

The embedding failure above also occurs in the saved pre-finder baseline.
`PyType_Ready` already refreshes a ready static type's LOCAL owner when
Main is reinitialized, but `PyModule_AddType` bypassed that step for ready
types. It now always calls `PyType_Ready`, preserving its fast ready-type
path. A repeated-initialization regression imports `_testcapi`, verifies
that `LegacyGetAttr` remains LOCAL with the current Main owner, and creates
and uses an instance in every initialization cycle.

This repair needs no new rule for simultaneous interpreters: the old Main
has already been destroyed. Question 9 still concerns live interpreters
sharing one static extension object.

The new regression fails before the fix and passes afterward in all three
builds, as does the original specialization/reinitialization test. The
seven-file selection (`test_embed`, `test_static_type_access`, `test_module`,
`test_capi.test_type`, `test_capi.test_import`, `test_import`, and
`test_import_finder_access`) passes in the default build: 315 reported tests,
20 skips. GIL/Tier 2 pass six files and report only the same six existing
`test_import` failures (315 tests, nine skips). Verbose failure identities
match the saved baseline exactly. Builds emit no compiler warnings, changed
sources match across trees, and `git diff --check` passes. Logs:
`/tmp/pep805-finders/reinit-*.log`.

### Frozen import across ThreadGroups

The `_imp` allowlist now includes `find_frozen`, `get_frozen_object`,
`is_frozen` and `is_frozen_package`. They read native frozen tables and
construct results for the calling group; they do not use mutable native
per-module state. The test override of the frozen-module setting now uses
atomic reads and writes because lookups can execute concurrently.

FrozenImporter also creates loader state using `type(sys.implementation)`.
The implementation namespace now has a synchronized dictionary and an
explicit SYNCHRONIZED declaration. Its existing mutable-attribute behavior
is preserved; values retain their own access states, and ordinary
SimpleNamespace instances remain LOCAL.

Four new tests cover first frozen-module/package imports in a worker,
source and frozen importer methods, implementation-namespace updates and
rejection of foreign values, and repeated code loading/execution in four
groups. Imported modules remain LOCAL, and other groups cannot acquire them
from `sys.modules`. The original three new cases fail before the repair;
all 14 finder/access cases pass after it.

The eight-file selection (`test_import_finder_access`, `test_import_access`,
`test_import_lock_access`, `test_importlib`, `test_import`, `test_sys`,
`test_types`, and `test_embed`) passes in the default build: 1,715 reported
tests, 47 skips. GIL/Tier 2 pass seven files and report only the six existing
`test_import` failures (1,715 tests, 35 skips). Verbose failure identities
match the saved baseline. Changed sources match across builds, compilation
emits no warnings, and `git diff --check` passes. Logs are in
`/tmp/pep805-file-import/`.

An ordinary `colorsys` import now reaches PathFinder and rejects a cached
LOCAL FileFinder. Isolated dependency probes additionally identify the
native filesystem helpers, the external loader's bootstrap reference and
its mutable suffix lists. Those probes manually expose selected objects to
locate subsequent acquisitions; they are not thread-safety tests or an
implementation. FileFinder cache synchronization and an audit of these
dependencies remain independent work, without requiring Mark's feedback.

### File imports across ThreadGroups

Exact FileFinder instances now have synchronized namespaces, immutable loader
tables and directory-cache snapshots, and an RLock around cache refresh and
invalidation. Loader constructors run after releasing that lock. Subclasses
stay LOCAL. The standard loader classes and suffix registries are explicitly
shared, but loader instances, module specs and imported modules retain their
own states. Both bootstrap module namespaces are explicitly synchronized;
their values are still checked individually. Repeated bootstrap setup accepts
an already synchronized namespace without attempting an invalid state change.

The native allowlists now include the filesystem operations used by source
loading, `_io` constructors/helpers, bytes-based marshal entry points, and
`_imp` suffix, source-hash and code-filename helpers. Only the zipimporter and
ZipImportError classes are shared so the default hook can reject ordinary
directories; ZIP caches, importer instances and decompression remain unported.
Dynamic extension loading and standard stream sharing remain separate work.

Two private-metadata paths also needed repairs. OSError's fixed errno map is
read internally, checking the selected exception type. PyImport_Import reads
inherited frame globals and builtins internally, checks the selected import
hook, and checks globals before exposing them to a custom hook. Its incoming
name uses an assertion and its result remains checked after cleanup. Updating
shared code filenames now stops parallel execution and checks acquired
filename references before comparison, propagating failures recursively.

Ten new tests cover new and cached finders, generated pyc reuse, concurrent
cache invalidation, ordinary and namespace packages, LOCAL subclass/loader
rejection, shared code metadata, filesystem exception types, and native import
with inherited globals or inaccessible hooks. Existing import-access tests now
expect the explicit bootstrap declaration and preserve the denial test using
an ordinary LOCAL module containing a callback. No access check is disabled.

The six-file import selection passes in all three Linux/aarch64 debug builds:
1,286 reported tests, 20 default-build skips and 19 GIL/Tier 2 skips. It covers
`test_import_file_access`, `test_import_access`, `test_import_lock_access`,
`test_import_finder_access`, `test_importlib` and `test_capi.test_import`.
The broad import/sys/I/O/OS/marshal/exceptions/embed/ThreadGroup selection
previously ran 3,453 tests per build. It exposed the repeated-setup failure
repaired above and, in the default build, a MemoryError shutdown GC assertion.
That GC failure also reproduces in an exact `6deee568de` baseline and is
repaired in the following follow-up. GIL/Tier 2 additionally
retain the six previously recorded subinterpreter import failures. Erroneous
top-level `test_fileio`/`test_posix` selections were command errors; their real
`test_io.test_fileio`/`test_os.test_posix` suites passed. Logs and the baseline
comparison are in `/tmp/pep805-source-import/`.

The sample application still calculates 61,620 and rejects foreign LOCAL and
unprotected PROTECTED access. These results do not establish full conformance.

### GC allocation-failure cleanup

The default build's shutdown assertion came from an earlier failed collection.
Merging delayed decrefs can leave tracked objects with zero references for the
collector to reclaim. If marking then ran out of memory, the collector returned
without reclaiming those objects or releasing its worklist references. A later
collection rejected the invalid zero-refcount objects. Frozen objects instead
leaked through an abandoned decref worklist.

The failure path now retains zero-refcount objects in the existing intrusive
worklist while the world is stopped, restarts other threads, and releases all
worklists before reporting MemoryError. Finding and retaining these objects
requires no allocation, and deallocators run after the heap traversal and world
stop have ended. This adds no object-header fields or new finalizer policy.

The regression injects allocation failure with delayed decrefs pending during
both marking phases and with a frozen object excluded from cyclic collection.
In the `6deee568de` baseline, the first two cases abort at the next collection
and the frozen case retains the object. All three pass after the repair, as
does the original `test_exceptions.test_exec_set_nomemory_hang` reproducer.
This fixes an implementation error without resolving or depending on any of
the questions for Mark below.

Validation in the default debug build passes nine suites across two runs:
`test_gc`, `test_exceptions`, `test_finalizer_access`, `test_threadgroup`,
`test_import_file_access`, `test_embed`, `test_weakref`,
`test_free_threading.test_gc` and `test_gc_stats` (494 reported tests,
23 skips in total). The first command also named the nonexistent
`test_weakref_access`; the real `test_weakref` suite passes in the second run.
GIL and Tier 2 both pass `test_gc` and `test_exceptions` (178 tests, five skips),
including skipping the new regression for their different collector.
The rebuilt sources match across configurations and compilation emits no
warnings. Logs are under `/tmp/pep805-source-import/gc-*`.

### Super lookup of builtin type metadata

Creating an Exception subclass in another ThreadGroup failed because
`_PySuper_LookupDescr` tried to acquire the builtin base's private type
dictionary through the public dictionary API. This also prevented extension
modules from creating their own exception classes during initialization.
The lookup now reads the dictionary internally and checks the returned
descriptor after releasing its retained MRO reference. Descriptor invocation
and final attribute-result checks remain in place, including the optimizer's
lookup path.

The new regression fails before the repair and passes afterward. It creates
Exception, list and int subclasses in a worker and exercises repeated super
method calls while verifying that the exception class and instance stay LOCAL.
The five suites `test_attribute_vm_access`, `test_super`, `test_type_access`,
`test_descr` and `test_types` pass in default, GIL and Tier 2 debug builds:
354 tests and one skip per build. Existing foreign-attribute, callable and
descriptor rejection tests still pass. Logs are in `/tmp/pep805-dynamic-import/`.

This repair lets a diagnostic probe proceed through multi-phase extension
initialization. The subsequent single-phase probe trips the public list
input assertion on the interpreter's private modules-by-index registry;
the following follow-up repairs that path.

### Native extension imports and module registration

The two dynamic-loader entry points are now explicitly synchronized. Their
package context is thread-local, and imported modules retain their individual
states. The modules-by-index registry is initialized as a SynchronizedList
alongside sys.modules, before extension imports can start in other groups.
This removes the foreign-LOCAL-list assertion during single-phase initialization
and avoids racing lazy initialization of the registry pointer. Raw array
lookups and duplicate-registration checks now hold the list's critical section.
Shutdown reads module-definition metadata privately without exposing foreign
modules through the public module API.

PyState_FindModule now checks the acquired module. A native test helper consumes
its borrowed result in C and returns only a boolean, ensuring that the VM's
outer return check cannot mask a missing C API check. The regression rejects
Main's registration from a worker and the worker's replacement from Main,
while permitting each owning group to find its module. The baseline runtime
at `6deee568de`, rebuilt with only the test helper, wrongly returns true for the
foreign registration. Its borrowed-reference lifetime contract remains the
existing API contract; the broader question 2 is not resolved by this fix.

PyModuleDef_Init also locks the definition while assigning its type and native
index. Different specs can refer to the same definition, so a name-specific
Python import lock alone cannot serialize that initialization. A four-group
regression creates 100 module instances from one native definition. Separate
tests execute multi-phase and single-phase imports, repeat a single-phase
cache load within its owner group, import three independent extensions in
parallel, and verify that foreign groups cannot acquire the resulting modules.
The two worker-import tests fail before the loader repair and pass afterward.
This does not declare arbitrary extension globals or exported objects safe
for sharing, nor settle the legacy-interpreter ownership question.

The ten-suite import/C API/embedding/ThreadGroup selection passes in the default
debug build: 1,557 reported tests, 40 skips. GIL and Tier 2 pass nine suites and
retain six failures in `test_import` (1,557 tests, 30 skips); verbose reruns
match all six saved failure identities. The five new extension-access tests
pass in each build. Changed native sources and tests match across configurations.
The full Tier 2 rebuild reports three unused-variable warnings in unchanged
generated executor cases; the subsequent module-definition changes compile
without warnings in all three builds. The demo still produces 61,620 and the
expected access denials. Logs are in `/tmp/pep805-dynamic-import/`.

### ZIP importer caches and uncompressed archives

Uncompressed ZIP imports failed in a worker both with a cold cache (the
Main-owned directory registry) and with a Main-cached importer (the importer
instance itself). Exact zipimporter instances now synchronize their namespace,
and both the registry and its per-archive directory mappings use synchronized
dictionaries. Directory mappings retain their existing mutable interface;
foreign values inserted by user code still fail when acquired. Reading the
archive occurs before publication, without holding a Python cache lock across
file or import callbacks. Cache invalidation can overlap a directory read and
does not provide a transaction with external filesystem changes.

The zipimport module namespace is explicitly synchronized. Importer subclasses
remain LOCAL, as do newly imported modules. Reinitializing an exact importer
and reloading zipimport preserve their supported single-thread behavior.
The timestamp-bytecode path captures an explicitly synchronized time.mktime
entry point. Its private module state supplies only type metadata; the two
stored timezone fields outside the parsed nine-item tuple now get access
checks before conversion. A native test helper explicitly shares shallow
struct_time records so the regression reaches those fields. With only the
native function explicitly shared in the earlier runtime, a valid record
works but a foreign timezone string loses its access exception to TypeError;
the repaired path raises IllegalThreadAccessException for both stored fields.

Eight new ZIP tests cover cold and cached source imports, regular and namespace
packages, timestamp/hash/sourceless bytecode, concurrent invalidation and reads
in four groups, LOCAL subclasses, foreign directory entries, and repeated
initialization/reload. Five of the initial seven cases failed before the fix;
all eight now pass. The eight-suite import/ZIP/time/sequence selection passes
in the default debug build (1,493 reported tests, 33 skips). GIL and Tier 2
passed the other suites during the initial run; the corrected timezone test
and final eight ZIP cases pass in both (74 tests, three skips in each focused
run). Existing ZIP suites also pass after the final reload guard. Changed
sources and tests match across the three builds. Logs and the baseline probe
are in `/tmp/pep805-zip-import/`.

This follow-up enables uncompressed archives across groups. The next follow-ups
handle zlib and the native _zstd helpers. The existing
Main-group compressed ZIP tests remain enabled and passing.

### DEFLATE archives and shared zlib initialization

The zlib namespace, decompress function, error class and missing-attribute hook
now explicitly support sharing. Each decompression call owns its native stream
and output buffer. The attribute hook is also needed because a from-import
probes the absent __path__ attribute before acquiring decompress. Other native
functions, stream constructors and instances keep their individual states.
The existing namespace synchronization helper is exported internally so a
dynamically linked standard library extension can opt in; this does not add
an API to the limited ABI or automatically share other extensions.

zipimport protects the decompressor cache's initialization flag with zlib's
existing recursive module lock. An initializer in another group waits for
publication instead of reporting recursive import, while the existing fake
zlib-in-a-compressed-archive case still fails without infinite recursion.
The cached callable is retained in a local variable before testing/returning
it. Inaccessible callables inserted into the cache are rejected on acquisition.

Five regressions cover cold native import, Main-cached decompression, four
parallel compressed module imports, native error handling and cache injection,
and a deliberately suspended first initializer. The three import cases failed
on the previous GIL runtime. The suspended-initializer test also failed there:
the second group raised ZipImportError before the first import was released.
No Mark decision is needed for this repair or the following Zstandard port.

The final seven-suite ZIP/zlib/importlib selection passes in the default debug
build (2,062 tests, 34 skips). GIL and Tier 2 each pass 2,060 tests with 33 skips;
their free-threading-only zlib suite is skipped. All 13 cross-group ZIP cases
pass in each configuration. The comparison builds initially retained an old
zlib object file after a timestamp-preserving source copy; forcing its rebuild
and checking the two native functions' actual sharing states resolved those
failures before the final suites. Sources and tests match across builds.
The full Tier 2 rebuild still reports the three known unused-variable warnings
in generated executor cases; the final zlib rebuilds have no warnings. Logs
are the `deflate-*` files in `/tmp/pep805-zip-import/`.

### Zstandard archives and native constructor inputs

The Zstandard importer now guards its initialization flag and class cache with
the existing _zstd module lock, retaining a local reference to the selected
class. The _zstd module namespace, ZstdDecompressor and ZstdDict classes and
ZstdError explicitly support sharing. Instances remain LOCAL: a worker creates
its own native context, buffers and dictionary caches. Other native exports
retain their individual sharing states. Dictionary instances are not implicitly
shared merely because their class is synchronized.

The shared dictionary-argument parser now obtains both tuple elements through
the checked tuple API before using either dictionary state or the integer tag.
A probe against the previous GIL runtime explicitly shares only the module,
decompressor class and error class to isolate this parser. That runtime accepts
a foreign dictionary hidden in the tuple; the repaired runtime rejects it and
also rejects a foreign integer tag. The test's second case explicitly shares
its native dictionary solely to reach the tag check.

Both compressor and decompressor option parsers retain a private dictionary
snapshot while integer conversion can call Python. Concurrent changes to a
synchronized source dictionary cannot remove the snapshot's entries while the
parser holds borrowed references to them. PyDict_Next acquisition errors now
propagate instead of returning a
native instance with an exception pending. The old runtime reports SystemError
for a protected option value and can skip validating a second invalid option
when the first value's __index__ clears the original dictionary. The regressions
preserve UnprotectedAccessException and validate every snapshotted option.
Parameter-type cache readers and the setter use the module's critical section;
the setter publishes both replacements before releasing old references outside
the lock. This does not settle the general borrowed-reference API contract.

Five additional ZIP cases cover cold/cached Zstandard imports, parallel imports,
a suspended initializer, concatenated and truncated frames, and a foreign cache
class. All five fail on the previous runtime and pass after the repair. Six
native tests cover local dictionaries in workers, foreign dictionary/tag and
option references, protected-value errors, conversion callbacks, and concurrent
option/metadata changes. Existing fake-compression-module recursion tests remain
enabled. The default seven-suite Zstandard/ZIP/importlib selection passes with
2,101 reported tests and 32 skips. GIL and Tier 2 also pass the same 2,101 tests,
with 31 skips each. Changed sources/tests match across the builds, and actual
native sharing states were checked before running the comparison suites.
The incremental builds have no compiler warnings or failed module imports.
Logs and the isolated tuple probe are in `/tmp/pep805-zstd/`.
No Mark decision was needed for this repair.

### GenericAlias stored-reference acquisition

GenericAlias operations now validate their stored origins before calling,
representing, comparing, hashing or forwarding attributes to them. Reduction,
MRO entries and starred-alias construction also check references acquired from
alias storage before passing them to C APIs. The constructor checks its tuple
elements; its setup helper asserts the valid-input contract instead of
rechecking incoming references.

Argument representation, parameter discovery and substitution now validate
acquired non-type arguments and cached parameter elements before operating on
them. Substitution also checks replacements obtained from a prepare hook's
tuple. The shared parameter helpers retain their private pointer-comparison
and copy-only paths: returning an accessible outer tuple does not require
access to all of its elements. The __shareable__ attribute is now handled by
the alias itself. Previously list[int] reported its origin's IMMUTABLE state
even though the alias was LOCAL.

Isolated probes against the previous runtime abort on an unprotected origin
in calls, representation, attribute forwarding and MRO-entry construction.
The first seven regression methods produce eleven subtest failures before
the repair. The final eight-method regression suite covers protected origins,
direct/nested/protected-list arguments, cold and cached parameters, prepare-hook
results, shallow tuple retention, state inspection and foreign arguments in a
worker-created alias. Its protected contexts end before the tested operation
begins; these failures do not depend on question 1's callback-lifetime decision.

The default, GIL and Tier 2 ten-suite typing/iterator/access selections each
pass with 1,178 reported tests and one skip. The default build's additional
AST and abstract C API selection passes with 277 reported tests and two skips.
The incremental builds have no compiler warnings or failed module imports.
Logs and the isolated crash probes are in
`/tmp/pep805-generic-alias/`. The broader union/type-variable and native
reference-acquisition audit remains unfinished. No Mark decision was needed
for this repair.

### Union and native typing references

Union representation and the hash/comparison paths for unhashable arguments
now acquire tuple elements through the checked API. Flattening nested unions
checks their argument elements at acquisition; the tuple container is created
internally and is always an exact immutable tuple. Redundant input checks in
the union slots and builders are now assertions. The single-element builder
also checks the reference returned from its internal list.

Union construction previously cleared an access exception raised by hashing
an accessible GenericAlias containing an inaccessible value, recording the
alias as merely unhashable and returning successfully. Both access exception
types now propagate. Other hash failures retain their prior behavior,
including a user-defined __hash__ that raises ValueError. No eager traversal
of the elements of cached hashable-argument sets was added.

Constant evaluators now check their stored values before formatting or
returning them, and check each tuple element used for string-format output.
Value-format output can still return an accessible tuple containing protected
elements. The TypeVar default getter is also called directly by generic-alias
substitution, bypassing ordinary descriptor-result checks; it now validates
the returned stored default. The corresponding ParamSpec and TypeVarTuple
getters and their stored evaluator calls follow the same rule.

TypeAliasType construction now rejects a foreign type parameter obtained from
an otherwise accessible tuple. Previously it could inspect that parameter's
default directly and accept it. ParamSpec args/kwargs wrappers transferred
through TransferBox now check their origin before representation or comparison,
and their representation checks the name fetched from that origin. The origin
itself retains its original ownership during shallow transfer.

The nine-method regression suite reports seventeen failures including subtests
on the previous runtime. Separate probes confirm SIGABRT for unprotected union
representation and constant string evaluation, and a normal return when union
construction suppresses an access exception. The protected-default regression
also reproduces an input assertion in PyTuple_Pack. Logs and reproductions are
in `/tmp/pep805-typing-acquisition/`.

The eleven-suite typing, AST and abstract C API selection passes on the
default, GIL and Tier 2 debug builds: each reports 1,403 tests and two skips.
All three incremental builds complete without compiler warnings or failed
module imports. The changed native sources and regression tests match across
the builds.

These repairs do not depend on a decision about protection ending inside a
callback. The remaining native typing paths and wider acquisition audit still
need review; the nine questions for Mark remain separate from this work.

### GenericAlias error cleanup

The invalid-unpacked-substitution error path now formats its TypeError before
releasing the tuple snapshot of list arguments. Previously it fetched the
original parameter from that snapshot after decrefing it. A 101-element
argument list avoids the small-tuple freelist and reproduces SIGSEGV on the
previous runtime; the repair retains the expected TypeError and message.

Reducing a transferred GenericAlias iterator correctly rejects its retained
foreign alias, but previously leaked the builtin iter reference acquired before
that check. Fifty rejected reductions increase iter's reference count by fifty
on the previous runtime. The error path now releases that reference, and a
failed builtin lookup returns immediately. Both regressions fail before the
repair. Logs and standalone reproductions are in
`/tmp/pep805-generic-alias-cleanup/`.

The seven-suite generic-alias, typing and iterator selection passes on the
default, GIL and Tier 2 builds, each with 963 tests and no skips. The incremental
builds report no compiler warnings or failed module imports. Sources and tests
match across the three builds.

### Composed iterator acquisitions and callable-iterator state

Sequence iterators and generic reversed iterators now check their stored
sequence before indexing, querying its length or using it to restore a cursor.
Access denial leaves the reverse cursor intact, allowing iteration to resume
after reacquiring protection. Before the repair, transferring either iterator
could reach PySequence_GetItem's input assertion; reversed length hints and
state restoration similarly reached PySequence_Size's assertion.

Enumerate, filter, map and zip now check stored iterators before calling their
native next slots. A tuple iterator's own check had concealed this omission:
with itertools.count instead, all four wrappers advanced a foreign LOCAL
counter after shallow transfer. Map and zip also check iterators in their
strict-exhaustion paths, and zip checks its cached and freshly allocated result
paths. Map and zip constructors acquire their tuple arguments through the
checked API. Map/filter check stored callables before invocation; their previous
raw calls could abort in the vectorcall input assertion.

Callable iterators now retain their callable under the iterator's critical
section before checking and invoking it. After the call, they take a coherent
snapshot of the sentinel and stopping exception, respecting reentrant
exhaustion. Reduction snapshots the same fields. Exhaustion and state restoration
publish all changed fields under the lock, then release old references outside
it. The previous state setter could invoke an old sentinel's destructor between
publishing the new sentinel and its stopping exception. A deterministic
regression observes that mixed state before the repair. Parallel consumers and
state updates, and simultaneous exhaustion, are covered separately. Sequence
and callable iterator reductions now release their acquired builtin reference
when access is denied; both previously leaked one reference per denied call.

The first eight regression methods report 22 failures including subtests on the
previous runtime. They cover transferred sequences, native iterator wrappers,
strict exhaustion, the fresh zip result path, foreign callables, protected
reverse cursors, reduction cleanup, reentrant state observation and parallel
state changes. A ninth method covers simultaneous callable-iterator exhaustion.
Logs and subprocess reproductions are in `/tmp/pep805-composed-iterators/`.

The default six-suite iterator/builtin selection passes with 378 reported
tests and eight skips; the final nine-method regression suite also passes
after adding the simultaneous-exhaustion case. GIL and Tier 2 each pass the
six-suite selection with 379 tests and eight skips. The incremental builds
have no compiler warnings or failed module imports. Changed native sources
and tests match across the three builds.

The following follow-up repairs enumerate and generic reversed state
propagation. The broader itertools/native caller audit and question 1's
callback-lifetime decision remain open.

### Enumerate and generic reversed sharing state

Both iterators now inherit the mutable source's sharing state. Enumerate uses
its retained iterator as the source; generic reversed uses its sequence. An
immutable source still produces a LOCAL iterator. The initial seven regression
methods reported 13 failures including subtests on the previous runtime.

Enumerate updates both small and large indices and reuses its cached result
tuple under its internal mutex. It calls the underlying iterator and releases
old result elements outside that critical section. Concurrent consumers obtain
distinct indices and source items; this does not promise index/value ordering
between overlapping calls. Reduction retains a long-index snapshot under the
same mutex before allocating its result.

A synchronized generic reversed iterator reserves a position before calling
__getitem__, since a Python callback can suspend a critical section. It retains
its source after exhaustion, snapshots reduction state, and rechecks exhaustion
after the length callback in __setstate__. Regression coverage forces four
sequence callbacks to overlap and checks that every position is visited once.
Additional tests cover exceptions and exhaustion inside the length callback.

Subclass namespaces now inherit the same protective lock or become
SynchronizedDict objects before the iterator is published. Managed namespace
replacement also synchronizes the supplied dictionary without breaking aliases,
matching the existing nonmanaged path. A worker-group regression exercises
namespace creation, attribute updates and dictionary replacement.

The parallel enumerate fixture passes its per-run inputs as defaults: rebinding
captured loop variables makes its function LOCAL under the existing function
classification rules. A separate small probe confirmed that fixture issue;
it was not an enumerate synchronization failure.

Validation logs and the pre-repair failures are in
`/tmp/pep805-iterator-sharing/`. The final regression suite contains ten methods.
The eight-suite iterator/descriptor/function selection passes on the default,
GIL and Tier 2 interpreter builds, each with 422 reported tests and one skip.
The new suite also passes the default build's -R 3:3 reference-leak check.
Incremental builds report no warnings or failed module imports. Changed native
sources and tests match across all three builds. This is targeted validation,
not completion of the overall PEP audit.

### Generic forward sequence iterator synchronization

Generic sequence iterators already inherited SYNCHRONIZED state, but their
load/callback/store sequence could visit the same position in several groups.
The new parallel regression performs 40 calls through four overlapping callbacks:
before the repair, positions 0 through 9 are repeated instead of visiting 0
through 39. Wrapping the sequence iterator in enumerate reproduces the same
source-item duplication. A reentrant next() also reads position 0 twice.
These account for three failures including subtests in the initial four methods.

Synchronized sequence iterators now reserve the cursor under their internal
mutex before invoking the sequence. They retain the sequence after exhaustion
in both comparison configurations. IndexError and StopIteration mark exhaustion
before clearing the exception, so exception cleanup cannot revive the iterator.
Other errors restore the reserved position when the cursor still immediately
follows it. This preserves sequential retry without overwriting intervening
progress or exhaustion; overlapping callbacks do not constitute a transaction.
LOCAL and PROTECTED iterators keep their existing callback ordering.

Reduction retains the source and cursor together under the mutex before access
validation and tuple construction. State restoration checks and updates the
cursor under the same mutex. The final six regression methods cover parallel
consumers, composition with enumerate, reentrant next/exhaustion, error retry,
a delayed failure after another consumer succeeds, copying and index overflow.
Logs are in `/tmp/pep805-seqiter-sharing/`. The seven-suite iterator selection
passes with 238 tests and no skips in each of the default, GIL and Tier 2
interpreter builds. The new six-method suite also passes -R 3:3 on the default
build. Incremental builds report no warnings or failed module imports, and
changed sources and tests match across all three builds.

### Itertools stored references and reentrant count lifetime

The retained-iterator callers of PyIter_Next now validate their acquisitions,
matching the existing direct-slot helpers. This covers groupby, cycle, chain,
tee and both zip_longest result-allocation paths. Dropwhile, takewhile,
filterfalse, starmap, groupby and accumulate validate stored callables before
calling C APIs whose arguments must already be accessible. Accumulate checks
its stored total before arithmetic or passing it as a callback argument.
Count checks both retained operands before addition and snapshots operands for
representation. Groupby and grouper key comparisons now check their owned
snapshots at acquisition, rather than relying on PyObject_RichCompareBool's
remaining input checks.

Grouper validates its mutable parent before inspecting or changing its state.
A debugger-created local grouper could previously consume another group's
cached groupby value after leaving StopTheWorld. Tee now uses an owned,
checked data-buffer snapshot in both configurations and validates acquired
links. A shallow transferred branch previously consumed a foreign group's
cached buffer, or aborted in PyIter_Next when fetching from the foreign input.
Cycle also handles a rejected cached-list acquisition: the previous assert
aborted instead of propagating UnprotectedAccessException. Its position stays
unchanged on that failure, so iteration resumes under the protecting lock.

Count and accumulate retain their arithmetic operand across a potentially
reentrant callback. Count previously treated its stored reference as a returned
reference even if recursive __add__ had replaced that storage. The standalone
GIL probe returns a freed object, fails its weakref identity assertion and
crashes during GC/shutdown before the repair. The repaired counter replaces
its current stored value normally and returns its independently owned snapshot.

The initial seven valid regression methods report 18 failures including
subtests; their log is `before-valid.log` in `/tmp/pep805-itertools-access/`.
The count lifetime and grouper-parent probes separately fail against the
previous GIL executable. The final eleven-method suite adds those cases, the
fresh zip_longest result path and 150 denied arithmetic acquisitions with a
reference-count stability check. The directory also contains build and suite
logs. Itertools sharing-state propagation and the broader native constructor
and acquisition audit remain unfinished; question 1's callback-lifetime
mechanism is not established by these repairs.

The final six-suite iterator/sequence selection passes on the default, GIL and
Tier 2 interpreter builds, each with 211 reported tests and six skips.
Incremental builds report no compiler warnings or failed module imports.
Changed native source and tests match across all three builds.

### FileFinder reinitialization and coherent cache settings

An exact FileFinder's second __init__ previously called synchronize() on its
already synchronized namespace and raised TypeError. It also replaced the cache
mutex while searches could still hold the old one. Reinitialization now computes
its inputs first, preserves the mutex and namespace identity, and updates the
path, loader table and empty caches while holding the existing mutex. The
namespace conversion is skipped for an already synchronized dictionary.

Find_spec retains the path and loader table with its directory-cache snapshot.
It uses those references after releasing the cache mutex, including for every
candidate suffix and for package lookup. Directory discovery similarly retains
its path and suffix table before opening scandir. Loader constructors still
run outside the mutex. Deterministic reinitialization callbacks previously
returned a different directory's module, turned a regular package into a
namespace package, or filtered one directory with another configuration's
suffixes. Concurrent reinitializers and searches also lost expected results.

The mutex is reentrant, so a filesystem audit hook can still reinitialize a
finder while listdir is running. A generation counter now identifies that
change. Cache filling builds local immutable sets and publishes them only if
the generation is unchanged; find_spec retries when its stat/cache generation
changes. With equal directory mtimes, the previous implementation could retain
the old directory's entries indefinitely under the new path. A standalone
os.listdir audit-hook probe reproduces that stale-cache failure.

Five added methods exercise both frozen and source importlib implementations:
namespace/mutex preservation and reinitialization in a worker; module/package
lookup snapshots; discovery snapshots; the audit-hook case with equal mtimes;
and concurrent reinitialization versus two searches. The initial three methods
reported eight failures including subtests before the constructor repair. The
snapshot, discovery and audit probes separately establish the configuration
mixing defects. Logs and the standalone audit probe are in
`/tmp/pep805-finder-reinit/`.

The final six-file import selection passes in all three builds with 1,291
reported tests: 20 skips in the default build and 19 in GIL and Tier 2.
Incremental builds have no compiler warnings or failed module imports. Source
and tests match across the builds, and make regenerated frozen importlib in
each. Its marshal reference encoding differs between the free-threading and
GIL configurations; unmarshalling and recursively comparing all 128 code
objects confirms identical bytecode, constants, flags and source locations.

### FileIO state synchronization before standard-stream sharing

The PEP's function example prints from a new ThreadGroup. A direct probe of
the current runtime raises IllegalThreadAccessException: stdin, stdout and
stderr, including their buffered and raw layers, are still LOCAL. Making
that example work requires native I/O ports; this is independent work and
does not need a decision on the nine questions below.

FileIO previously had no critical sections around its mutable descriptor,
mode bits and allocated stat cache. Initialization even passed the shared
stat pointer to fstat while detached, allowing a concurrent close or init to
free that memory. It also mutated mode bits before calling an opener. An
ordinary second init retained old flags; reentrant or overlapping initializers
mixed settings, leaked the replaced descriptor, or discarded an inner
initializer's valid state when the outer opener failed.

Native methods and metadata getters now lock the object. Initialization keeps
its descriptor, mode flags and stat result private until all setup callbacks
succeed, then publishes the complete native state together. It closes any
replaced owned descriptor after publication. Failure cleans up only resources
opened by that invocation, including failure in a reentrant name setter.
Close removes the descriptor and stat storage before detaching. Detached I/O
uses a copied descriptor, and the fast closed check is atomic without taking
a child lock from buffered/text I/O.

A FileIO-specific generation counter prevents a completed seek or truncate
from overwriting the metadata of a later initialization, including descriptor
number reuse. In the deterministic seek regression, __index__ replaces a
borrowed pipe with a regular file: the old pipe's ESPIPE must not mark the
new file unseekable. In the truncate regression, __index__ installs another
file whose stat cache must survive truncation of the borrowed old descriptor.
This counter is native FileIO metadata, not an addition to PyObject's header.
The changes do not promise atomicity across independent OS descriptor calls.

The first four regressions all fail before the fix in the default build.
The expanded seven-method suite reports six failures against the previous
GIL executable, including both stale-cache cases. The final nine-method suite
also exercises name-setter failure, four groups writing to one explicitly
declared native FileIO, and two metadata readers racing reinitialization and
close. Only the internal test helper declares those instances synchronized;
ordinary files and runtime standard streams remain LOCAL. Buffered/text I/O
stored references, pending buffers and codec state still need work before
publishing synchronized standard streams. Arbitrary custom codecs must not
be implicitly declared safe to share.

The final selection (`test_fileio_shareable`, `test_io`,
`test_import_file_access`, `test_finalizer_access`) passes in all three debug
builds, with 1,108 reported tests: 29 skips in the default build and 37 in GIL
and Tier 2 interpreter builds. Incremental builds report no compiler warnings
or failed module imports; the optional _decimal module remains unavailable.
Native source, generated Clinic wrappers and tests match across the builds.
Baseline, build and suite logs are in `/tmp/pep805-fileio-state/`.

## Earlier re-review and implementation follow-ups

One earlier question was incorrect: footnote 3 of the
[allowed-operations table](https://peps.python.org/pep-0805/#allowed-operations)
explicitly requires the argument to `protect()` to be the sole reference.
Rejecting `value = []; lock.protect(value)` is therefore consistent with the
PEP, even though the implementation copies the object. The open discussion
about a `del` expression does not remove that requirement. This is no longer
a question for Mark. Copy elision is a separate optimization.

Implementation follow-up after this re-review: sorting now validates stored
elements before inspecting or comparing them, including tuple keys and direct
native comparison results. `test_sort_access` covers foreign/protected elements,
key callbacks, the C API, and preservation of elements on failure. The six
suites `test_sort_access`, `test_sort`, `test_list`, `test_capi.test_list`,
`test_sequence_access`, and `test_synchronized_list` pass in both debug builds
(163 reported tests, one skip each). This closes the unchecked sort-element
finding, but not the separate problem of the list's own protection ending
during a callback, nor the GC compatibility finding.

The subsequent C API cleanup converts input checks to assertions in six list
APIs (`Size`, `GetItem`, `GetItemRef`, `SetItem`, `Insert`, `Append`), the three
cell APIs, and seven function getters plus four function setters. Return-value
checks remain. The cell test helper now validates its tuple element before
passing that reference to `PyCell_Get`. New tests exercise protected values
stored through these APIs and denied retrieval outside the locking context.
Input checks in other APIs and checks around callbacks still need auditing;
this is not a blanket claim that Mark's second comment is fully addressed.
After this cleanup, the earlier 61-file suite plus `test_sort_access`,
`test_sort`, `test_list`, `test_capi.test_list`, and `test_capi.test_function`
passes in both builds: 66 files, 1,490 reported tests, with 13 free-threading
and 16 GIL skips. The demo still computes 61,620 and rejects foreign LOCAL
and unprotected accesses in both builds. These results do not cover or close
the remaining reference-lifetime, GC, or refcounting design issues.

The next cleanup applies the same input contract to five tuple APIs (`Size`,
`GetItem`, `SetItem`, `Pack`, `GetSlice`) and seven bytes APIs (`Size`,
`AsString`, `AsStringAndSize`, `Repr`, `Join`, `FromObject`, `Concat`). Heap
acquisitions inside bytes construction and bytes/bytearray joining are checked
before invoking the element's C APIs. Joining also preserves access exceptions
raised by buffer exporters. A subprocess regression reproduces the former
assertion failure on foreign stored buffers, including a LOCAL bytes subclass,
bytearray and memoryview. The tuple setter test helper now propagates a failed
element acquisition instead of returning a result with an exception pending;
the new protected-element test reproduced that former fatal error.
After these changes, the 66-file suite plus `test_capi.test_tuple`,
`test_capi.test_bytes`, and `test_bytes` passes in both debug builds: 69 files,
1,891 reported tests, with 18 free-threading and 24 GIL skips. Compilation
produced no compiler warnings; the optional `_decimal` extension remains
unavailable. Source and test changes match between the two build trees.

The questions below distinguish unspecified contracts from optional choices
of implementation strategy. None is a reason to postpone fixing a known
unsafe access. Reproduction programs and current results follow the earlier
validation record at the end of this document.

## Resolved findings from the initial audit

- **Finalizer dispatch:** an owner-group finalizer is now transported in an
  internal shallow tuple. The destination acquires the actual object after
  entering its owner group. Previously, constructing the dispatcher checked
  its foreign `self` in the sending group. The full finalizer suite now runs,
  including finalization after the original owner thread exits.
- **Native test helpers:** function-setter and cell-mutation helpers acquire
  references with checked tuple APIs before invoking native or attribute
  setters. This repairs their unchecked acquisition from tuple storage; it
  does not mean all public setter input checks have been converted to asserts.
- **State inspection:** `__shareable__` lazily initializes its enum instead of
  raising merely because `threading` has not yet been imported. A clean-process
  test covers both a local object and an immutable primitive.
- **Tuple iterator protection:** exact tuple iterators now support protected
  shallow copying, including partially consumed and exhausted iterators. The
  PEP's wrapper example is exercised with two distinct ThreadGroups and an
  inaccessible nested element. Other native layouts still require explicit
  support; this does not make arbitrary extension objects copyable.
- **Extension defaults:** `IMMUTABLETYPE` alone no longer declares an extension
  type shareable. Only core static builtins receive that implicit treatment.
  Explicit declarations also publish the type namespace. Tests cover static
  and heap extension types, denied foreign acquisition, and explicit opt-in.
- **References surviving protection:** fast-local loads now conservatively
  check accessibility, including borrowed, fused and comprehension-save
  variants. Internal closure-cell transport remains separate from reading
  the cell contents. Call completion also checks the live evaluation stack
  for operands invalidated by the call; inlined Python returns check the
  caller stack after clearing the callee. Optimizers may no longer erase a
  checked local load as a pure push/pop pair.

  The initial generator example now raises `UnprotectedAccessException`, as
  do expressions such as `value[generator.close() or 0]`. A debugger pause
  ending in another frame likewise cannot leave usable foreign locals.
  Generator tests that formerly assumed an unchecked foreign local reached
  `YIELD_VALUE` now assert rejection at the local load, normal unwinding, and
  the producer's ability to catch that error. Native iterator result checks
  still have their separate coverage.

  This is a conservative correctness measure with additional runtime work,
  **not** the appendix's proposed near-zero-overhead local analysis. It does
  not prove the lifetime invariant for every callback, C local, or VM escape.
  Question 1 remains relevant to a complete, optimized solution.
- **termios error propagation:** ordinary operations now propagate failure
  from `PyModule_GetState` in both builds instead of returning a result with
  an exception pending. GC traversal/clearing uses the GC accessor. The
  sequence tests explicitly publish module state when testing element access;
  a separate clean-process test verifies rejection with unpublished state.

- **GC metadata access:** heap-type slot traversal and standard-library module
  traversal/clear/free callbacks now use the existing `*_DuringGC` accessors.
  Normal object accessibility is not a precondition for GC to inspect a
  different group's layout or native module state. A regression test holds
  a local slotted object and extension modules in Main while another group
  performs a full collection. No Python-code access exemption was added.

## Remaining implementation work

The following are known gaps, not questions about whether the PEP requires
parallel groups or immediate reclamation of ordinary LOCAL objects.
Question 5 is an implementation-design consultation: the observable
requirement is already clear. Question 6 asks about unspecified cleanup
semantics that affect the header design. Neither makes the defects below
acceptable or establishes that Mark's approval is needed for routine fixes.

1. **Default-build parallelism is repaired; architecture optimization remains.**
   Configure now defaults to the existing free-threading substrate, including
   biased reference counting and parallel allocation/GC. Native barrier tests
   verify concurrent execution by distinct groups, including after extension
   imports; same-group serialization remains tested. Importing an extension
   no longer transiently or permanently enables a global GIL. An explicitly
   selected `--enable-gil` build remains available for comparison and cannot
   execute groups in parallel. This does not finish compact headers,
   group-biased refcount optimization or performance validation.
   See [parallelism](https://peps.python.org/pep-0805/#parallelism-and-context-switching)
   and the appendix's
   [implementation strategy](https://peps.python.org/pep-0805/appendix-implementation/#implementation-strategy).

2. **The reproduced LOCAL delays are repaired; the refcount audit is not complete.**
   Both builds now print `['finalized', 'after del']` in the same-group
   example below. Previously free-threading printed the reverse order even
   though the object is acyclic and held in an ordinary local list. The
   follow-up also repairs transferred copies and LOCAL function/descriptor
   lifetime. Its regressions exercise the required
   [deferred reclamation](https://peps.python.org/pep-0805/#deferred-reclamation).
   The reference-count fast path still tests the OS-thread owner
   (`Include/refcount.h`); the fix merges when a same-group reference enters
   the slow path. Other automatic deferred-count paths and shareable-to-LOCAL
   transitions still need auditing. The latter also depend on question 7's
   state-transition contract. No claim of general lifetime conformance is
   made from these examples alone.

   ```python
   import threading

   events = []
   class Value:
       def __del__(self):
           events.append('finalized')

   values = [Value()]
   def worker():
       value = values.pop()
       del value
       events.append('after del')

   t = threading.Thread(target=worker)  # Same Main ThreadGroup.
   t.start()
   t.join()
   print(events)
   ```

3. **Header size does not follow the appendix's compact-layout direction.**
   Measured `object.__basicsize__` is 40 bytes in the GIL build and 56 bytes
   in the free-threading build on this 64-bit host. The illustrative
   [header](https://peps.python.org/pep-0805/appendix-implementation/#object-state)
   occupies 24 bytes with this ABI's usual layout. That exact layout is a
   suggestion, not a mandatory ABI. Explaining the current three cleanup
   fields does not justify their permanent cost or resolve Mark's concern.

4. **Sorting: element acquisition repaired; receiver lifetime still open.**
   At the current HEAD, sorting the foreign elements from a shallow
   `TransferBox` correctly raises `IllegalThreadAccessException`. The
   historical failure and the repair are recorded separately above and below.

   Another probe starts sorting a protected list with valid input, then
   closes its protecting generator from the key callback. Sorting completes
   and restores the reordered list while the external lock is no longer
   held. Rechecking Python locals and call results does not protect this
   surviving C reference. Question 1 concerns the general lifetime mechanism,
   not whether this unchecked continuation is correct.

5. **Legacy extension GC compatibility remains broken.** With
   `xxlimited_3_13` imported in Main, collecting from another group crashes
   both builds with SIGSEGV. Symbolizing each fault address resolves to
   `xx_traverse()` at `Modules/xxlimited_3_13.c:457`. Its
   `PyModule_GetState(module)` returns NULL because the module is foreign,
   then the visitor dereferences that pointer. Publishing only the
   `gc.collect` callable suffices to reproduce the failure; the extension
   module itself remains LOCAL. Updating the stdlib's other visitors to
   `*_DuringGC` did not resolve this compatibility problem. The runtime must
   support safe GC of LOCAL extensions; question 3 concerns the contract for
   doing so without requiring existing extension callbacks to change.

6. **Mark's input-check comment has only been addressed partially.**
   `PyObject_GetItem` already used assertions at re-review. The follow-up
   now also replaces direct input checks in the 87 list, cell, function,
   tuple, bytes, bytearray, numeric and Unicode APIs listed above. Other
   APIs and common helpers remain to be audited. The subsequent call audit
   replaces runtime scans of raw vectorcall arrays with debug assertions,
   including native functions, descriptors and Python-frame setup. Tuple
   expansion, keyword-name/value acquisition, and bound-method fields still
   receive runtime checks. `_testcapi`'s vectorcall adapter now checks its own
   tuple acquisitions instead of relying on an invalid-input check downstream.
   Attribute lookup and format conversion may invoke callbacks, so their
   surviving C references are revalidated after those callbacks. Interpreter
   checks after argument evaluation and monitoring are also retained. These
   distinctions implement the valid-input invariant without assuming the
   unresolved lifetime mechanism in question 1 is already in place.
   The tuple-array follow-up also removes the raw-input access scan from
   `PyTuple_FromArray()` on tuple-building fallback paths and retains checks
   at its container-storage callers. Other C API families still require their
   own caller audit; this is not a claim that every downstream check has been
   removed.

7. **Local-load checking remains substantially more conservative than the
   appendix's design.** `_PyEval_CheckLocalAccess()` runs on ordinary fast
   local loads, not only the compiler-selected maybe-unprotected loads.
   Calls also scan the live evaluation stack (`Python/ceval.c:749`, `:778`).
   This departs from the appendix's performance strategy, not necessarily
   its observable semantics, and still misses the C callback case above.
   No performance measurements establish that this approach meets the PEP's
   expectations. The intended invariant must be settled before claiming that
   these checks can be removed safely.

8. **Uniform debug validation of stack publication remains incomplete.**
   The appendix's [validation section](https://peps.python.org/pep-0805/appendix-implementation/#validation)
   calls for validating references whenever they are pushed to the interpreter
   stack. The follow-up adds debug assertions for completed Tier 1 instruction
   outputs, including explicit dispatch paths, and `_PyFrame_StackPush()`.
   Validation follows the instruction's access checks: temporary stack spills
   needed for GC may contain a reference that the next micro-op will reject.
   Interpreter-owned entry frames are excluded because they carry VM metadata
   and pending native returns; `INTERPRETER_EXIT` checks the returned object.
   Fast-local loads retain the existing narrow exception for a frame's own
   closure cells, whose contents are checked by `LOAD_DEREF`. Heap and call
   results do not get this exception.
   Tier 2 internal publication still needs equivalent validation, and a
   complete audit of frame-changing and manually managed stack paths remains.
   Passing selected tests does not establish this invariant at every point.

9. **Subinterpreter extension imports have an additional compatibility
   failure.** The GIL build aborts while importing `_testcapi` in
   `test_capi.test_misc.SubinterpreterTest.test_py_config_isoloated_per_interpreter`.
   `type_call()` finds a pending exception during module initialization.
   This also reproduces before the stack-validation changes at `3657b0d87c`.
   The first denied reference is now identified: `_testcapi_exec()` publishes
   the process-global `matmulType`, owned by group 1, in a subinterpreter
   whose Main group is 257. `PyDict_SetItem()` rejects it through
   `PyModule_AddObject()`. The test extension ignores that return code and
   later aborts with the access exception still pending. Each interpreter
   currently allocates a distinct Main group, including legacy interpreters
   sharing a GIL. Other tests in that file also report foreign-group access
   exceptions on extension import. Converting the setter's input check to an
   assertion would merely move the failure earlier. Declaring all static
   extension types shareable would contradict the PEP's LOCAL default.
   Question 9 asks which ownership/scheduling contract should preserve this
   legacy usage. The compatibility failure itself remains to be repaired.

## Questions to discuss with Mark

Questions 1–4 and 6–9 concern unspecified contracts or clarifications to the
PEP/appendix. Question 5 asks for design guidance, not clarification of whether
LOCAL objects must be reclaimed promptly. The complete question wording and
the concrete behavior motivating each question follow.

These questions are not a blanket dependency on Mark's approval. Native
reference-acquisition repairs, redundant-input-check cleanup, debug
validation and work on specified behavior can continue independently.
Reference-counting representation is a design consultation, not an external
authorization requirement. Only changes that choose an unresolved observable
contract need to remain separate from the conformance work.

### 1. How is reference validity maintained when protection ends in another frame?

A generator can yield a valid protected reference, then invalidate its
protection when the caller later closes that generator. The follow-up now
rejects subsequent local loads and checks surviving call-stack operands.
Similar issues arise with suspended coroutines, callbacks, debugger contexts
and C locals retained across calls.
The protected `list.sort(key=...)` reproduction below now demonstrates a
remaining C-reference failure, rather than just a theoretical concern.

Is yielding/awaiting while holding a protective context supported? If so,
what is the intended invalidation rule for existing frame locals and
evaluation-stack/C references when a call ends that protection? Should the
compiler model potentially invalidating calls, should the runtime validate
affected frames on context exit, or is another restriction intended?
The lexical analysis in the
[compiler appendix](https://peps.python.org/pep-0805/appendix-implementation/#bytecode-compiler)
does not settle these cases. The need to reject the unsafe access is clear;
the question is how to maintain the incoming-reference invariant.

### 2. What is the accessibility contract of unchecked C API macros and borrowed outputs?

`PyList_GET_ITEM` and `PyTuple_GET_ITEM` still read storage directly
(`Include/cpython/listobject.h`, `Include/cpython/tupleobject.h`).
An accessible shallow tuple can contain an inaccessible local object, so
checking the tuple alone cannot validate such a load.

Must these macros gain checked semantics, become explicitly unsafe APIs
requiring caller changes, or be replaced by distinct checked/unchecked
interfaces? If a formerly infallible macro can return NULL, how should
existing extensions handle the new failure? What is the corresponding rule
for borrowed references and output-parameter APIs? For example,
`PyDict_Next` now returns 0 with an exception set when an output is foreign
(`Objects/dictobject.c:3496`), whereas an unchanged caller can interpret 0 as
normal exhaustion. This boundary needs an
explicit decision to satisfy the
[C API and extension contracts](https://peps.python.org/pep-0805/#c-extensions-and-the-c-api),
without reinstating checks on every operation.

### 3. What access contract applies while the VM invokes legacy GC callbacks?

The PEP promises that extension callbacks do not need modification. Existing
visitors use ordinary `PyModule_GetState` and type-data accessors to inspect
their own objects, even when the collecting thread belongs to another group.
The `xxlimited_3_13` reproduction below confirms that simply checking the
ordinary accessor and converting selected stdlib visitors to `*_DuringGC`
does not implement that promise.

Should the VM provide a restricted GC-metadata access context for the old
APIs, or should such metadata accessors be exempt from ownership checks
because they expose native state rather than Python object references?
What separates this permission from executing arbitrary Python callbacks,
especially during clear, deallocation and finalization? The required safety
and compatibility are clear; the boundary and mechanism are not specified.
This should be resolved together with the valid-input invariant, rather than
by requiring extensions to ignore NULL results or bypass access control.

### 4. Does shallow transfer include an instance's own attribute storage?

`TransferBox.claim()` changes only the copied object's `ob_owner_id`
(`Modules/_threadmodule.c`). A transferred ordinary Python instance can
currently return a primitive `obj.x` in the receiving group while accessing
`obj.__dict__` raises `IllegalThreadAccessException`. This was reproduced in
both builds. By contrast, protection explicitly copies and protects an
instance's dictionary (`Modules/_threadmodule.c`).

Should an instance's fresh dictionary be considered part of the transferred
object, with only its attribute values remaining shallow references? Or
should the dictionary retain the sender's owner like any other referenced
object? What constraints should apply when `__copy__` supplies shared or
aliased instance storage?
See [mutable-value transfer](https://peps.python.org/pep-0805/#passing-mutable-values-between-parallel-threads)
and [object dictionaries](https://peps.python.org/pep-0805/#object-dictionaries).

### 5. Should local reference-count ownership be biased to a ThreadGroup?

The current default build uses PEP 703's OS-thread bias.
It now merges synchronously on the same-group slow path and retires the bias
before publishing a transferred copy. These repairs satisfy the reproduced
ordering requirements without choosing a new header representation.

Is the intended design a group-biased local count, rebiasing/merging on group
handoff, or a different mechanism? The required observable behavior is not
the question; the representation and handoff strategy are. The proposed
compact header and the refcount fast path should be designed together.
See [reference counting](https://peps.python.org/pep-0805/appendix-implementation/#reference-counting).

### 6. Where must finalizers and weakref callbacks run, and what cleanup guarantees are required during world stops?

The implementation dispatches foreign LOCAL finalizers to a newly created
thread in the owner group, acquires a PROTECTED object's mutex for its
finalizer, and dispatches weakref callbacks to their registration group
(`Modules/_threadmodule.c`, `Objects/weakrefobject.c`). An abandoned
unclaimed transfer is instead adopted by the group clearing its box.
These are substantial implementation choices, not specified callback rules.

Are those affinity rules intended, including when the original thread has
exited or the interpreter is shutting down? May finalization create a thread
or block on a protecting mutex? What should happen to unclaimed transfers
and objects whose lock wrapper has died?

Separately, must repeated explicit non-GC `PyObject_CallFinalizer` requests
during an internal world stop each be replayed, even under allocator failure?
That is the current queue's self-imposed/tested guarantee
(`Objects/object.c`), and it drove the three `ob_deferred_*` fields.
The PEP does not establish that guarantee. Please clarify whether it is part
of the intended cleanup contract before we treat it as a requirement of the
PEP. This does not block work on a smaller header: representations that
preserve required lifetime and callback behavior can be developed and tested
independently.

### 7. Can a published synchronized function become LOCAL after mutation?

The current implementation classifies read-only cell bindings as shareable,
then changes dependent functions from SYNCHRONIZED to LOCAL if a cell becomes
writable. This can happen even when its value remains an immutable integer:

```python
import threading
def factory():
    value = 42
    return lambda: value
f = factory()
print(f.__shareable__.name)   # SYNCHRONIZED
f.__closure__[0].cell_contents = 43
print(f.__shareable__.name)   # LOCAL
```

Is this dynamic reclassification intended, or should mutation be rejected
once a binding/function has been published as shareable? If reclassification
is allowed, which group becomes the owner, and how are references already
held by other groups invalidated? The code performs world-stop updates and
heap scans (`Objects/funcobject.c`), but the
[function specification](https://peps.python.org/pep-0805/#classes-functions-and-modules)
does not define this transition protocol.

### 8. Do the primitive/result-check exemptions apply only to exact builtin types?

The implementation treats exact `str` as intrinsically immutable and Python
subclasses as LOCAL. A custom `__str__` returning a `str` subclass causes
`str(obj)` to return that LOCAL subclass in the current build. Consequently
the appendix's suggested exemption for `PyObject_Str` needs qualification.
`PyObject_Str` currently checks the returned value, which is the conservative
choice; this observation is not a reason to remove that check.

Can the appendix explicitly limit the exemption to paths proven to return
an exact builtin, retaining the existing possibility of subclass results?
Alternatively, is normalizing these results to exact primitives an intended
semantic change? The former preserves current Python behavior. This is a
request to clarify the appendix's optimization claim, not a proposal to
grant arbitrary mutable subclasses the primitive guarantees. It affects
both access-check elision and the
no-context-switch guarantee. See
[primitive types](https://peps.python.org/pep-0805/#primitive-types) and
the appendix's [C API discussion](https://peps.python.org/pep-0805/appendix-implementation/#c-api).

### 9. How should Main ownership work across legacy interpreters sharing a GIL?

Legacy extensions can expose the same process-global static type to several
interpreters sharing a GIL. Currently each interpreter has a distinct Main
ThreadGroup, and such a type belongs to the first group initializing it.
Importing `_testcapi` in the second interpreter therefore rejects
`matmulType`, even though the two interpreters are serialized by one GIL.

Sequential destruction and recreation of Main is a separate case. The
`PyModule_AddType` re-registration bug found by the embedding tests has
been repaired without deciding the ownership of simultaneously live
interpreters.

Should these legacy interpreters share a Main ownership/serialization domain,
or should interpreter-local Main groups admit such static extension globals
through another explicit rule? How should that interact with subinterpreters
using separate GILs? The PEP defines Main at interpreter startup, defaults
extension classes to LOCAL, and promises default-build compatibility, but
does not describe how to reconcile these rules for existing shared globals.
This is not a request to permit arbitrary cross-group access to LOCAL types.
See [Main](https://peps.python.org/pep-0805/#the-main-threadgroup),
[extension defaults](https://peps.python.org/pep-0805/#c-extensions-and-the-c-api)
and [compatibility](https://peps.python.org/pep-0805/#backwards-compatibility).

## Follow-up commits

- `d149d16b05`: finalizer transport, native helper acquisitions, state inspection.
- `f2ae1c67b6`: protected tuple-iterator copying and the PEP wrapper example.
- `ff60f55d63`: explicit sharing declarations for extension types.
- `65d89f831d`: conservative local and surviving call-operand validation.
- `ef68bf8a82`: consistent termios module-state error propagation.
- `2fc691bbbe`: GC metadata access for foreign groups.
- `a1a1e19daa`: sort-element acquisition and comparison-result checks.
- `08cf7ba093`: list, cell and function C API input assertions.
- `afa12c7930`: tuple and bytes input assertions, stored-buffer acquisition,
  and tuple test-helper error propagation.
- `b9e28c41d8`: checked code constants in both interpreter tiers.
- `76155a60fb`: bytearray input assertions and exporter exception propagation.
- `9dc37a0f0d`: internal retention of foreign executors during invalidation.
- `cbfc681dcc`: Tier 2 regressions for checked local acquisition.
- `0a0fb73ca8`: numeric input assertions and complex conversion-result lifetime.

## Earlier implementation validation

The following suite and demo results are historical. The newer implementation
and validation record above supersedes their scope.

Both Linux/aarch64 debug variants were rebuilt, and the opcode/uop generated
files were regenerated. The GIL checkout's changed source/test/generated
files match the free-threading checkout.

The final run used `./python -m test -q -j2 --timeout=120` with the 50 PEP 805
suites and `test_dis`, `test_peepholer`, `test_scope`, `test_generators`,
`test_genexps`, `test_listcomps`, `test_coroutines`, `test_context`, `test_tuple`,
`test_gc`, and `test_capi.test_module`:

| Build | Test files | Reported tests | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Free-threading debug | 61 | 1,359 | 13 | SUCCESS |
| GIL debug | 61 | 1,359 | 16 | SUCCESS |

`Tools/scripts/pep805_demo.py` also succeeds in both rebuilt variants: two
ThreadGroups process four chunks, the weighted square sum is 61,620, and
foreign LOCAL and unprotected PROTECTED access are rejected.

The original audit probes were repeated in both builds. Tuple iterator
protection and the generator-local rejection now work. The header sizes,
same-group LOCAL finalizer delay in free-threading, transfer namespace
behavior, protect uniqueness restriction and dynamic function
reclassification remain as described above.

The optional `_decimal` extension is unavailable in this environment.
Windows and native JIT execution remain deferred. These checks do not prove
complete native reference-acquisition coverage or PEP 805 conformance, and
no performance claim is made for the conservative VM checks.

## Re-review validation and reproductions

This section preserves the results at review commit `897dd73703`, before the
subsequent sorting repair. See the follow-up status near the top for current
results; the foreign-element reproduction now raises the expected exception.

The re-review used the same two Linux/aarch64 debug executables and reran
the eight original audit probes, then added the sorting, legacy GC, and
string-subclass probes. Each probe ran in a separate subprocess with a
15-second timeout and core dumps disabled. This was targeted validation,
not a full test-suite run or a release-build/performance measurement.

| Probe | Free-threading debug | GIL debug | Assessment |
| --- | --- | --- | --- |
| Sort foreign LOCAL elements | Succeeds; direct element access is denied | Same | Access-control defect |
| Close protecting generator from sort key | Sort succeeds after unlock | Same | Reference-lifetime defect |
| Foreign GC with `xxlimited_3_13` | SIGSEGV in `xx_traverse`, line 457 | Same | GC compatibility defect |
| Same-group LOCAL last-reference deletion | Finalizer runs after the following statement | Finalizer runs before it | Free-threading reclamation gap |
| Header size | 56 bytes | 40 bytes | Compact representation unfinished |
| Protect an aliased source | TypeError | TypeError | Matches table footnote 3 |
| Protect a temporary tuple iterator | First value is 1 | Same | Repaired behavior retained |
| Read a local after closing its protecting generator | UnprotectedAccessException | Same | Repaired Python-local case retained |
| Transfer an ordinary instance | Primitive attribute readable; `__dict__` denied | Same | Question 4 |
| Rebind a read-only closure cell | Function changes SYNCHRONIZED to LOCAL | Same | Question 7 |
| `__str__` returns a `str` subclass | Result preserves the LOCAL subclass | Same | Question 8 |

An existing dictionary view also remains LOCAL after freezing its dictionary;
that observation alone does not demonstrate an access-control violation.

### Foreign element sorting

Run this in either debug build. The expected access denial occurs only for
the final explicit element read, after sorting has already used the elements.

```python
import threading

@freeze
class Number(float):
    pass

box = threading.TransferBox([Number(2), Number(1)])
output = SynchronizedList()

def worker(box, output):
    values = box.claim()
    try:
        values.sort()
    except BaseException as exc:
        output.append(('sort raised', type(exc).__name__))
    else:
        output.append(('sort returned', len(values)))
    try:
        values[0]
    except BaseException as exc:
        output.append(('element raised', type(exc).__name__))

t = threading.Thread(target=worker, args=(box, output),
                     group=threading.ThreadGroup())
t.start()
t.join()
print(list(output))
# [('sort returned', 2), ('element raised', 'IllegalThreadAccessException')]
```

### Protection ending during a native operation

This uses ordinary generator closure, without calling a lock's `__exit__`
manually. The source generator holds the context when sorting starts.

```python
import threading

lock = threading.Lock()

def source():
    with lock:
        yield lock.protect([3, 1, 2])

generator = source()
values = next(generator)

def key(value):
    generator.close()
    return value

try:
    values.sort(key=key)
    print('sort returned normally; lock held:', lock.locked())
except BaseException as exc:
    print('sort raised:', type(exc).__name__, str(exc))
with lock:
    print('list after reacquiring lock:', values)
# sort returned normally; lock held: False
# list after reacquiring lock: [1, 2, 3]
```

### Legacy GC visitor

Run only as a subprocess: this reproduces a process crash. The internal
declaration publishes the collection function, not the extension module.
The worker performs no printing or imports, to isolate the GC failure from
unrelated foreign access in I/O or exception reporting. This reproducer uses
the repository's existing test extension; no third-party package is needed.

```python
import gc
import threading
import _testinternalcapi
import xxlimited_3_13

gc.disable()
collect = gc.collect
_testinternalcapi.object_declare_synchronized(collect)
output = SynchronizedList()

def error_hook(args):
    output.append(('error', type(args.exc_value).__name__, str(args.exc_value)))

threading.excepthook = error_hook

def worker(collect, output):
    output.append('before collect')
    collect()
    output.append('after collect')

t = threading.Thread(target=worker, args=(collect, output),
                     group=threading.ThreadGroup())
t.start()
t.join()
print(list(output))
# SIGSEGV; xx_traverse dereferences state at Modules/xxlimited_3_13.c:457.
```

## Additional reproduction at `afa12c7930`

These two failures are historical and have been repaired by the 2026-09-24
follow-up. The programs remain here to make the original findings reproducible
against that earlier commit. Current execution raises
IllegalThreadAccessException for the constant probes and all four buffer
operations.

### A foreign LOCAL object in code constants

Run only in a subprocess with core dumps disabled: the cold case aborts at
`Objects/abstract.c:171` in both debug builds. To reproduce the specialized
variant, add `for _ in range(100): read(0)` immediately after constructing
`read`. The GIL build then prints `[('returned', 42)]`; the free-threading
build still aborts. The expected outcome in the worker is an
IllegalThreadAccessException at constant acquisition.

```python
import threading

def read(index):
    return 'replace this'[index]

foreign = [42]
code = read.__code__.replace(
    co_consts=tuple(foreign if value == 'replace this' else value
                    for value in read.__code__.co_consts))
read = type(read)(code, read.__globals__)
print('function state:', read.__shareable__.name, flush=True)
print('constant state:', foreign.__shareable__.name, flush=True)
output = SynchronizedList()

def worker(function, output):
    try:
        output.append(('returned', function(0)))
    except BaseException as exc:
        output.append(('raised', type(exc).__name__))

t = threading.Thread(target=worker, args=(read, output),
                     group=threading.ThreadGroup())
t.start()
t.join()
print(list(output))
```

### Access exceptions from bytearray buffer exporters

The exporter belongs to the receiving group; only the memoryview retained
inside the shallow tuple belongs to Main. Thus the exception originates from
a new heap-reference acquisition in `__buffer__`, not an invalid C API input.

```python
import threading

payload = (memoryview(b'x'),)
output = SynchronizedList()

def worker(payload, output):
    class Exporter:
        def __buffer__(self, flags):
            return payload[0]

    exporter = Exporter()
    for operation in ('buffer', 'join', 'concat', 'inplace_concat'):
        try:
            if operation == 'buffer':
                memoryview(exporter)
            elif operation == 'join':
                bytearray().join([exporter])
            elif operation == 'concat':
                bytearray() + exporter
            else:
                target = bytearray()
                target += exporter
        except BaseException as exc:
            output.append((operation, type(exc).__name__))
        else:
            output.append((operation, 'allowed'))

t = threading.Thread(target=worker, args=(payload, output),
                     group=threading.ThreadGroup())
t.start()
t.join()
print(list(output))
# [('buffer', 'IllegalThreadAccessException'),
#  ('join', 'IllegalThreadAccessException'),
#  ('concat', 'TypeError'), ('inplace_concat', 'TypeError')]
```
