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
crashes. The default-build parallelism and LOCAL reclamation gaps remain.
These are implementation defects or unfinished work, not questions about
whether unsafe access or crashes are acceptable.

The preceding audit executed 15 distinct subprocess probes in each
Linux/aarch64 debug build, with timeouts and core dumps disabled. The constant
and buffer-exporter probes were repeated after their repairs. The table
combines those new results with the unchanged findings from the prior audit.
New suite results are recorded in the implementation follow-up below.
A successful demo or selected suite does not demonstrate parallel execution
in the GIL build or close the remaining failures.

| Current check | Free-threading debug | GIL debug | Assessment |
| --- | --- | --- | --- |
| Subscript a foreign LOCAL list loaded from `co_consts`, cold function | IllegalThreadAccessException | Same | Repaired at constant acquisition |
| Same function after 100 calls in Main | IllegalThreadAccessException | Same | Repaired; also tested with a Tier 2 executor |
| Foreign LOCAL elements in `list.sort()` | IllegalThreadAccessException | Same | Repaired |
| Close protecting generator from sort key | Sort completes after unlock | Same | Remaining reference-lifetime defect |
| Foreign GC with `xxlimited_3_13` | SIGSEGV in `xx_traverse`, line 457 | Same | Remaining compatibility defect |
| Last LOCAL reference deleted by another thread in the same group | `after del` before finalizer | Finalizer before `after del` | Free-threading reclamation gap |
| Object header size | 56 bytes | 40 bytes | Compact representation unfinished; 24 bytes is illustrative |
| Buffer exporter tries to return a foreign memoryview | Buffer acquisition, join, concatenation and in-place concatenation raise IllegalThreadAccessException | Same | Exception propagation repaired |
| Transfer an ordinary instance | Primitive attribute readable; `__dict__` denied | Same | Question 4 |
| Rebind a read-only closure cell | Function changes SYNCHRONIZED to LOCAL | Same | Question 7 |
| `__str__` returns a `str` subclass | LOCAL subclass preserved | Same | Question 8 |

The other probes confirm rejection of an aliased `protect()` argument,
working tuple-iterator protection, rejection of a local load after its
protecting generator closes, and a dictionary view remaining LOCAL when its
dictionary is frozen. The last observation alone is not an access violation.

Source inspection confirms that `_PyEval_AcquireLock()` still takes the
interpreter GIL as well as the group lock (`Python/ceval_gil.c:592`), that
the default build still uses ordinary reference counts (`Include/refcount.h`),
and that the three cleanup fields remain in both headers
(`Include/object.h:163`, `:188`). They implement a queue for deferred cleanup,
not biased reference counting. Free-threading does reuse PEP 703 BRC, but
that OS-thread bias does not meet the observed same-group LOCAL lifetime
requirement. Mark's two comments therefore remain only partially addressed.

The input-check cleanup now covers bytearray, integer/float/complex and
Unicode accessors as well as the earlier container and function APIs.
Vectorcall argument scans and other C API families remain to be audited.
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

1. **The default build still serializes different ThreadGroups.**
   `_PyEval_AcquireLock()` acquires both the group lock and the interpreter
   GIL (`Python/ceval_gil.c`). `Include/refcount.h` still selects ordinary
   reference counting for that build. This is unfinished work, not an
   ambiguity about whether parallel ThreadGroups are required.
   See [parallelism](https://peps.python.org/pep-0805/#parallelism-and-context-switching)
   and the appendix's
   [implementation strategy](https://peps.python.org/pep-0805/appendix-implementation/#implementation-strategy).

2. **Reusing free-threading BRC has not preserved immediate LOCAL reclamation.**
   In the same-group example below, the free-threading build prints
   `['after del', 'finalized']`; the GIL build prints
   `['finalized', 'after del']`. The object is acyclic and is held in an
   ordinary local list, not a synchronized collection. The reference-count
   fast path still tests the OS-thread owner (`Include/refcount.h`).
   This needs to be reconciled with
   [deferred reclamation](https://peps.python.org/pep-0805/#deferred-reclamation).

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
   APIs and common helpers remain to be audited.
   `_PyObject_CheckVectorcallArgs()` still scans raw C argument arrays
   (`Include/internal/pycore_call.h:114`). Those array entries are
   incoming references, unlike acquiring values from an argument tuple or
   keyword dictionary. This is unfinished implementation cleanup under the
   intended valid-input invariant. Checks after potentially invalidating
   callbacks, and checks when acquiring stored elements, must be considered
   separately; simply deleting all checks would not establish that invariant.

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
   Other tests in that file report foreign-ThreadGroup access exceptions when
   importing shared extension modules. These failures need diagnosis and
   repair; they are not an acceptable outcome of the intended access model.

## Questions to discuss with Mark

Questions 1–4 and 6–8 concern unspecified contracts or clarifications to the
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

The current branch uses PEP 703's OS-thread bias in the free-threading build.
The same-group reclamation counterexample above shows that simply retaining
that implementation is insufficient for the stated LOCAL lifetime behavior.

Is the intended design a group-biased local count, rebiasing/merging on group
handoff, or a different mechanism? The required observable behavior is not
the question; the representation and handoff strategy are. The proposed
compact header and the default-build port should be designed together.
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
The PEP does not establish that guarantee. We should agree on the cleanup
contract before treating these fields as necessary or choosing an
out-of-header representation.

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
