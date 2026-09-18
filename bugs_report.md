# CPython `main` defects found during the tracing-JIT experiments

## Scope and evidence standard

This document records defects and concrete optimization limitations found while
developing the local Tier 2 experiments in this checkout.  It is not a survey of
all known CPython bugs.  An item is included only when one of the following is
available:

- a reproducer run against the fixed comparison build from CPython `main`;
- a failure from the unmodified archived `main` source; or
- a source-level defect in `main` exercised by a generated experimental input.

The tested source revision is
`a60343ed17785ebbcd43de9080cadd8e2541db6f`.  Its native-JIT executable has
SHA-256
`8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`.
At the time this report was written, the local `main` reference was
`2fcb0e27d959345151750b756af79054c3230531`; the intervening changes do not
modify the JIT, optimizer, or generator files discussed here.

All local fixes named below are on the experimental branch.  None have been
submitted to GitHub as part of this work.  A local fix commit often also contains
experimental optimization work and should be split before any upstream review.
The fixes were reapplied and verified on `codex/method-jit`, starting from
`d95f29589e03603aa13d8ca9d4f817dce77d357c`.

| ID | Classification | Effect | Local status |
| --- | --- | --- | --- |
| M-1 | Optimizer correctness | A dict guard is attached to the wrong stack value | Fixed on `codex/method-jit` |
| M-2 | Optimizer correctness | A function can use a value from the wrong builtins mapping | Fixed on `codex/method-jit` |
| M-3 | Optimizer correctness | A function can use a value from the wrong globals mapping | Fixed on `codex/method-jit` |
| M-4 | JIT lifecycle | A short loop uses the RESUME retry threshold | Fixed on `codex/method-jit` |
| M-5 | Resource retention | JIT-created functions show linear allocated-block growth | Diagnosed as bounded deferred deletion |
| M-6 | Code generation | Two-digit uop replicas receive incompatible IDs | Fixed on `codex/method-jit` |
| M-7 | Build correctness | A header layout change can reuse stale native stencils | Fixed on `codex/method-jit` |
| M-8 | Generator interface | The recorder generator's default output has the wrong name | Fixed on `codex/method-jit` |
| M-9 | Incremental build | `optimizer.o` can retain a stale recorder table | Fixed on `codex/method-jit` |
| M-10 | Generator analysis | Non-escaping operations are classified as escaping | Fixed on `codex/method-jit` |
| M-11 | LLVM integration | Ordinary LLVM 21 stencil generation fails on a constant pool | Fixed on `codex/method-jit` |
| M-12 | Stencil optimization | Jump-table targets can be removed from a generic stencil | Fixed on `codex/method-jit` |
| M-13 | JIT hotness | A ready counter wraps while another trace is active | Fixed on `codex/method-jit` |
| M-14 | GIL handoff | Repeated short I/O can indefinitely restart a waiter's switching interval | Fixed locally; debug, native and PGO/LTO validation pass |
| P-1 | Optimization coverage | Valid method-descriptor calls on subclasses are rejected | Fixed on `codex/method-jit` |
| P-2 | Optimization precision | Unrelated global writes invalidate optimized code | Fixed on `codex/method-jit` |
| P-3 | Optimization coverage | Materialized dictionaries prevent valid inline attribute loads from specializing | Fixed locally for GIL builds |

## M-1: dict-subscript guards inspect the wrong stack value

**Impact:** latent correctness and safety risk in Tier 2 dict specialization.

The abstract optimizer handles `_GUARD_NOS_DICT_SUBSCRIPT` and
`_GUARD_NOS_DICT_STORE_SUBSCRIPT` by learning the type of `nos`, which is the
mapping receiver.  For a probable dict subclass, however, `main` emits
`_GUARD_TYPE`.  That uop guards TOS, which is the key for a read and a different
operand for a store.  The generated guard therefore does not prove the receiver
type required by the following dict-specific uop.

The regression fixture uses a hashable dict subclass as both receiver type and
key type.  On the fixed `main` build the trace contains `_GUARD_TYPE` where the
fixture requires `_GUARD_NOS_TYPE`.  This isolates the slot error even though a
particular continuation may still leave the trace through another check before
misusing the receiver.

The local fix introduces the correct NOS guard and tests reads and writes after
changing the receiver to an unrelated object.  It is part of commit
`e2fe92a4b591315bab547de3ebf9c38d9e22edf7`.  The focused test is
`TestUopsOptimization.test_dict_subclass_guards_receiver` in
[`Lib/test/test_capi/test_opt.py`](Lib/test/test_capi/test_opt.py).

## M-2: copied builtins mappings can be constant-folded as interpreter builtins

**Impact:** wrong Python result with the JIT enabled.

`_LOAD_GLOBAL_BUILTINS` in `main` obtains the candidate constant from
`interp->builtins` and relies on its watcher.  A function can instead have a
copied `func_builtins` dictionary.  Dict copies can share a keys version while
holding different values, and the interpreter-builtins watcher does not cover
mutations of the copy.

The reproducer creates functions under
`{"__builtins__": vars(builtins).copy()}`, warms `len()` to form an executor,
and then replaces `len` in that copy.  The expected result is `42`; the fixed
`main` executable returns the stale value `1`:

```text
AssertionError: 1 != 42
```

The local fix folds a builtin only when `func_builtins` is the interpreter's
builtins dictionary and retains an identity guard in the optimized trace.  It is
in commit `9e96c11b1ba08bf39709363e1db176eca29f24c0`.  The direct regression tests
are `test_copied_builtins_value_change` and
`test_same_function_version_different_builtins` in
[`Lib/test/test_capi/test_opt.py`](Lib/test/test_capi/test_opt.py).

## M-3: a globals keys version does not identify the globals mapping

**Impact:** wrong Python result with the JIT enabled.

The existing `_GUARD_GLOBALS_VERSION` proves a dict-keys version but does not
prove the identity of `func_globals`.  Different functions can share a code
object and valid function version while using copied globals dictionaries.  A
copy can preserve the keys version even when values differ.  Constant folding a
global under the version-only guard can therefore reuse a constant from another
namespace.

The preserved reproducer warms a function whose `stable.value` is `7`, creates a
new function from the same code with a copied globals mapping where the value is
`19`, and calls the new function eight times.  The expected sum is `152`; `main`
returns `68`, while the original function still returns `56`.  The complete uop
trace and binary identity are in
[`copied-globals-main.json`](jit-artifacts/benchmark-suite/copied-globals-main.json),
and the reproducer is
[`check-copied-globals.py`](jit-artifacts/benchmark-suite/check-copied-globals.py).

The local fix combines the keys version with the actual globals identity and
registers the mapping as an executor dependency so a borrowed identity cannot
outlive the mapping.  It is in commit
`4b54f1d098d499b98f8fdc249c2ab9b4bf8323a2`.

## M-4: successful short-loop traces use the wrong retry countdown

**Impact:** an invalidated short-loop executor is not recreated at the configured
loop threshold.

After successful compilation, `_PyJit_FinalizeTracing()` chooses between the
loop and RESUME counters by inspecting the instruction that triggered tracing.
Compilation may already have replaced that instruction with `ENTER_EXECUTOR`.
For a short backward jump, `main` consequently selects the RESUME countdown.
An `EXTENDED_ARG` happens to preserve the distinction and masks the problem for
large jump operands.

On the fixed `main` build, the short-loop case records `8190` instead of `4000`
and does not retrace after the expected number of iterations.  The long-jump
control records `4000` and retraces, while the function-entry RESUME control
correctly records `8190`.  Raw results are in
[`retry-counter-main.json`](jit-artifacts/benchmark-suite/retry-counter-main.json),
with the reproducer in
[`check-retry-counter.py`](jit-artifacts/benchmark-suite/check-retry-counter.py).

The local fix reads the original opcode with `_Py_GetBaseCodeUnit()` before
selecting the counter.  It is in commit
`0654d6f85344842944c9356e9a889572bef045a2`, with short-jump, extended-jump,
invalidation, and RESUME tests in
[`Lib/test/test_capi/test_opt.py`](Lib/test/test_capi/test_opt.py).

## M-5: linear allocated-block growth when the JIT sees new functions

**Impact:** bounded temporary retention from the executor deletion queue; this
is not an unbounded resource leak.

A `-R 3:3` run completed all semantic and optimized-path checks but failed its
allocated-block check by roughly 61--62 blocks per repetition.  A smaller
reproducer creates 100 new functions in each batch.  The unchanged archived JIT,
the candidate with experiments disabled, and the candidate with experiments
enabled all produced the same cumulative sequence:

```text
101, 205, 307, 409, 511, 613
```

With `PYTHON_JIT=0`, the corresponding sequence was:

```text
1, 5, 7, 9, 11, 13
```

The primary evidence is
[`block-growth-baseline.log`](jit-artifacts/local-regions/block-growth-baseline.log),
[`block-growth-disabled.log`](jit-artifacts/local-regions/block-growth-disabled.log),
[`block-growth-enabled.log`](jit-artifacts/local-regions/block-growth-enabled.log),
and
[`block-growth-no-jit.log`](jit-artifacts/local-regions/block-growth-no-jit.log).
The follow-up run continued for 25 batches.  The delta rose to `818`, fell to
`20` when the cleanup threshold was reached, rose to `938`, and fell to `40` at
the next cleanup.  `_Py_ClearExecutorDeletionList()` intentionally defers
executor destruction until the periodic `JIT_CLEANUP_THRESHOLD` event so code
cannot be freed while a thread is executing it.  The original six-batch sample
stopped before the first cleanup.  No runtime fix is needed.

## M-6: replicated uop IDs are lexicographic rather than numeric

**Impact:** an optimizer selecting a replica as `base_id + oparg + 1` can execute
the wrong uop, hit a debug assertion, or crash a release/native build.

`uop_id_generator.py` in `main` sorts generated names as strings.  For a family
with at least eleven replicas, `_BASE_10` sorts before `_BASE_2`.  The optimizer
and generated metadata require the replicas to be contiguous and ordered by
their numeric suffix.  A 20-replica call family exposed the mismatch through an
`oparg == CURRENT_OPARG()` assertion in debug builds and a native crash.

This is latent in the generator even though the unmodified `main` input did not
contain the triggering family.  The local fix sorts replicas by parent and
integer suffix and adds a generator-only test for `replicate(12)`,
`replicate(8:13)`, and a similarly named non-replica uop.  See commit
`cbcf14f0e6ed2e517dd92902bc0c243f83b41bc3` and
`TestUopIdGeneration.test_replica_ids_are_contiguous_and_numeric` in
[`Lib/test/test_generated_cases.py`](Lib/test/test_generated_cases.py).

## M-7: `pycore_optimizer.h` is missing from native-stencil dependencies

**Impact:** an ordinary incremental build can silently combine machine-code
stencils using an old structure layout with a runtime using the new layout.

The native stencil templates include optimizer definitions, but `main` omits
`Include/internal/pycore_optimizer.h` from all three freshness mechanisms:

- `JIT_DEPS` in `Makefile.pre.in`;
- `_JITSources` in `PCbuild/regen.targets`; and
- `_Target._compute_digest()` in `Tools/jit/_targets.py`.

Changing only a counter's position in the header therefore reused old stencils.
The debug build, which does not use native stencils, passed.  The native build
then failed 410 region tests because counter offsets disagreed.  Force-generating
stencils restored the expected offsets.  The before/after offsets are recorded
in
[`conditional-attribute-stale-stencil-evidence.json`](jit-artifacts/benchmark-suite/conditional-attribute-stale-stencil-evidence.json).

The local fix adds the header to the POSIX and Windows input lists and to the
digest, with an offline digest regression test.  It is in commit
`4fec509cf5713f9f72f27afd9900c1f3e1131c43`; the test is
[`Lib/test/test_tools/test_jit.py`](Lib/test/test_tools/test_jit.py).

## M-8: recorder generation defaults to an unused filename

**Impact:** invoking the generator directly without `-o` appears successful but
does not update the header consumed by the build.

`Tools/cases_generator/record_function_generator.py` defaults to
`Python/recorder_functions.c.h`, while CPython includes and the Make target
updates `Python/record_functions.c.h`.  The configured
`regen-record-functions` target supplies the correct explicit output and is not
affected.  Direct developer use is affected, which is especially confusing when
changing a bytecode macro's recording uops.

The branch changes the default to the header consumed by the build.  The
explicit form remains valid:

```sh
python3 Tools/cases_generator/record_function_generator.py \
    -o Python/record_functions.c.h Python/bytecodes.c
```

A generator test checks the default output basename.

## M-9: `optimizer.o` does not depend on its generated recorder table

**Impact:** an incremental build can keep recorder indices and slot maps compiled
from an old generated header.

`Python/optimizer.c` includes `Python/record_functions.c.h`, but the `main`
dependency list for `Python/optimizer.o` omits that header.  After correctly
regenerating the table, an incremental build retained the old object and repeated
a recorder-slot assertion.  Explicitly rebuilding `Python/optimizer.o` made the
new table effective.

The local fix adds the generated header to the object's prerequisites.  It is in
commit `00fcaf8462ddc60fc48586b65fb8ad5c271e95fa`.  This defect is independent
of M-8: using the right output path still leaves a stale object without this
dependency.

## M-10: known non-escaping operations are treated as escaping

**Impact:** lost stack-cache and trace optimization opportunities; no semantic
misbehavior has been observed.

The cases generator uses a conservative list of C operations that cannot retain
or otherwise escape stack references.  `main` omits operations whose contracts
are sufficient to classify them as non-escaping, including
`PyTuple_SET_ITEM`, `_PyTuple_Recycle`, `Py_MIN`, `Py_MAX`, and `Py_SET_SIZE`.
Generated uops around these operations therefore spill or terminate analysis
more often than required.  For `_PyTuple_Recycle`, element decrefs remain the
observable/escaping part; resetting the tuple hash and GC links is not itself a
Python re-entry point.

The branch classifies each of these five established operations as
non-escaping.  A generator analysis test verifies that none creates an escape
point.

## M-11: LLVM 21 vectorization produces an unsupported stencil constant pool

**Impact:** native JIT stencil generation fails on Linux x86-64 with the required
LLVM version and ordinary flags.

Both the archived `main` source and the experimental source failed stencil
generation under LLVM 21.1.8 with repeated diagnostics:

```text
<unknown>:0: error: Undefined temporary symbol .LCPI0_0
```

The affected generated stencil was traced to `_GUARD_TOS_SLICE_r11`.
Vectorization introduces a temporary constant-pool reference that the stencil
processing pipeline does not preserve.  The unmodified-main failure is in
[`build-baseline-driver316.log`](jit-artifacts/local-regions/build-baseline-driver316.log);
the candidate failure is in
[`build-native-driver316.log`](jit-artifacts/local-regions/build-native-driver316.log).

The stencil optimizer now follows local-label references in ordinary
instructions and data directives.  Its regression fixture covers a `.LCPI`
constant pool before the global entry point.  Full LLVM 21 stencil generation
also succeeds with ordinary flags; the vectorization workaround is no longer
needed for this branch.  PGO and LTO are unrelated and were not enabled.

## M-12: the stencil optimizer can discard jump-table destinations

**Impact:** valid C for a generic uop can fail during native stencil assembly.

An experimental generic integer-comparison uop used a runtime selector with six
branches.  LLVM 21 lowered it to a jump table.  The JIT assembly optimizer did
not retain labels referenced only through the table and removed the destination
blocks.  Assembly then failed with undefined `.LBB0_26` through `.LBB0_29`
symbols.  Constant replicas of the same uop compiled successfully.

The corrected diagnosis is preserved in
[`enum-compare-stencil-diagnosis-corrected.log`](jit-artifacts/benchmark-suite/enum-compare-stencil-diagnosis-corrected.log).
The trigger is not part of unmodified `main`, so this is a latent limitation in
the `main` stencil optimizer rather than a failure of the shipped stencil set.
The same local-reference traversal now treats the preserved jump table as a
root and retains every case block named by its entries.  A focused assembly
fixture reproduces both the constant-pool and jump-table forms.

## M-13: a ready JIT counter wraps while another trace is active

**Impact:** hot functions can wait another 8192 calls for compilation after
being encountered during tracing.

The tracer sets specialization counters to zero. In `_JIT`, tracing suppresses
compilation, but the fallback still decrements that zero counter. Its 16-bit
representation becomes 65528, whose countdown value is 8191. A caller loop with
4002 iterations reproduces this on the matched `main` build; the next direct
leaf call still does not create an entry executor.

Evidence: [reproducer](jit-artifacts/all-benchmarks-10pct-20260916/check-ready-counter.py)
and [main result](jit-artifacts/all-benchmarks-10pct-20260916/ready-counter-main.json).
The local fix preserves an already-ready counter when compilation is temporarily
blocked. The regression test checks both the counter and compilation on the
next direct call. The candidate preserves zero and creates an entry executor
on that call: [candidate result](jit-artifacts/all-benchmarks-10pct-20260916/ready-counter-candidate.json).
All 362 GIL native optimizer tests pass (four skips). The existing super-call
test now accepts a replacement trace rooted in its callee and additionally
checks invalidation after changing the second superclass method.

## P-1: method-descriptor specialization rejects compatible subclasses

**Impact:** avoidable call overhead and premature trace termination for inherited
builtin methods.

The Tier 1 and Tier 2 method-descriptor guards in `main` require
`Py_IS_TYPE(receiver, descriptor_type)`.  Ordinary descriptor dispatch uses the
equivalent of `PyObject_TypeCheck`, so a subclass that inherits the descriptor
is a valid receiver.  Calls such as inherited `list.append`, `list.copy`,
`list.index`, and `list.sort` therefore miss specialization despite having the
same receiver validity rules as the accepted base type.

The local change uses the descriptor's subtype-compatible condition for
`METH_O`, `METH_NOARGS`, `METH_FASTCALL`, and
`METH_FASTCALL | METH_KEYWORDS`, while retaining descriptor, call-shape, and
error checks.  It is part of commit
`e2fe92a4b591315bab547de3ebf9c38d9e22edf7`.  Focused bound/unbound, override,
wrong-receiver, and exception tests passed.  A DeltaBlue comparison for the
whole checkpoint measured a candidate/before geometric mean of `0.955919`; this
includes both Tier 1 and Tier 2 guard changes and should not be attributed solely
to native JIT code.  Raw results are in
[`descriptor-subclass-deltablue-summary.json`](jit-artifacts/benchmark-suite/descriptor-subclass-deltablue-summary.json).

## P-2: global dependencies are tracked at whole-dictionary granularity

**Impact:** changing an unrelated global invalidates otherwise valid optimized
code and can delay its recreation.

On both fixed `main` and the pre-fix candidate, changing the value of an unrelated
entry in a function's globals dictionary invalidated an executor that used only
`stable`.  Changing `stable` also invalidated it, as required.  Results are in
[`global-dependencies-main-v2.json`](jit-artifacts/benchmark-suite/global-dependencies-main-v2.json),
with the reproducer in
[`check-global-dependencies.py`](jit-artifacts/benchmark-suite/check-global-dependencies.py).

This behavior is safe but unnecessarily broad.  The local implementation records
the exact global names folded into constants, watches structural changes to the
dict separately, and invalidates through per-name dependencies.  It is in commit
`4a0328435496475ecc2ced6605c36c3ac8fb97fa`.  The namespace-identity guard from
M-3 remains necessary; precise name dependencies do not make a keys version
identify a mapping.

## P-3: materializing a dictionary prevents inline attribute-load specialization

**Impact:** ordinary attribute reads remain generic after `obj.__dict__` is
accessed, even while the object's inline values remain valid. This affects
Tier 1 and both JIT frontends; it is an optimization limitation, not a
wrong-result bug.

Reproduced on the matched `main` revision
`d95f29589e03603aa13d8ca9d4f817dce77d357c`, executable SHA-256
`a245f5d91e4e5007af841be2296e55634aa8a29605b03af70fb3f772a6e7370b`.
The [reproducer](jit-artifacts/all-benchmarks-10pct-20260916/check-materialized-load.py)
materializes a dict subclass's attribute dictionary before warming a getter
10,000 times. With the JIT disabled,
[main](jit-artifacts/all-benchmarks-10pct-20260916/materialized-load-main.json)
retains `LOAD_ATTR`, whereas the
[local debug build](jit-artifacts/all-benchmarks-10pct-20260916/materialized-load-debug.json)
uses `LOAD_ATTR_INSTANCE_VALUE`. Both observe a subsequent dictionary write.

`specialize_dict_access()` checks that inline values are valid, but then
rejects an already materialized dictionary as though materialization had just
raced with specialization. In a GIL build, reads may use the same valid inline
storage, guarded by the existing type-version and inline-validity checks.
The local fix permits this case only for loads. Stores retain the dictionary
restriction so that dictionary watchers are honored. Free-threaded builds keep
the previous policy because materialized-dictionary mutation can invalidate
inline storage independently of the owner lock.

The regression covers a dictionary materialized before warming, mutation through
that dictionary, clearing it, replacing it, and adding a data descriptor.
All four GIL/free-threaded debug/native builds pass 83 JIT-disabled opcode-cache
tests and 1,312 JIT-enabled regression tests (four/five skips). The
[native reproducer result](jit-artifacts/all-benchmarks-10pct-20260916/materialized-load-native.json)
also confirms specialization. No timing benefit is claimed by this reproducer;
benchmark results are recorded separately in `plan.md`.

## Observations deliberately excluded from the defect list

- The base16 regression in one pyperformance comparison is not listed as a
  source bug.  `Lib/base64.py` was identical to `main`, and the measurements
  were sensitive to rebuild and code-layout differences.
- Failures, timeouts, and unavailable dependencies in the pyperformance runner
  are workload/environment outcomes, not CPython correctness defects.
- Experimental region bugs found and fixed while developing new uops are not
  `main` bugs.  Examples include missing constructor return offsets, incorrect
  custom exit reconstruction, and a mismatched `get_region_stats()` format.
- Float contraction and operation-order requirements arose from newly fused
  arithmetic uops.  No incorrect fused operation exists in unmodified `main`.
- The generic-base jump-table trigger is included as M-12 because it exercises
  `main` stencil infrastructure, but it is explicitly marked latent.  Other
  failures caused solely by unfinished experimental C or missing experimental
  declarations are excluded.
- Regrtest temporary-directory collisions under separate PID namespaces and a
  Python 3.13 host's stalled asyncio subprocess handling are environment/tooling
  interactions, not established defects in the tested CPython `main` runtime.
- Functions constructed directly with `types.FunctionType` retaining an unset
  function version is treated as a current specialization limitation.  The
  incorrect results in M-3 do not depend on that limitation: functions created
  by `MAKE_FUNCTION` can share a valid code/function version across namespaces.

## Local verification performed for this report

The M-1, M-2, and M-4 regression tests were loaded from the current test source
and run against the fixed `main` executable with `PYTHON_JIT=1`.  They failed in
the expected pre-fix ways: wrong dict guard, stale copied-builtin value, and
`8190` versus `4000`.  The M-3 standalone reproducer was rerun against the same
binary and returned `68` instead of `152`.  The executable SHA-256 matched the
preserved evidence.

All actionable fixes were then applied to the fresh `codex/method-jit` branch.
A fresh native LLVM 21 JIT build completed with ordinary compiler flags and no
PGO or LTO.  A warmed executor reported a nonempty 4096-byte `get_jit_code()`
result, proving that the native backend rather than only the Tier-2 interpreter
was exercised.

The final native build passed `test_optimizer test_capi.test_opt` with the JIT
disabled and again with `PYTHON_JIT=1`: each run executed 327 tests with three
skips.  The generator and JIT-tool suites passed 104 tests.  These cover the
dict receiver, copied builtins and globals, retry counters, numeric replicas,
dependency digest, recorder output, escape analysis, stencil reachability,
method subclasses, precise global invalidation, namespace lifetime, and
non-string equivalent-key cases.

Full x86-64 stencil generation succeeded with LLVM 21 and ordinary flags.  A
normal incremental build detected the optimizer header dependency and
regenerated the stencils before relinking.  All affected generated files were
regenerated from source, and a second pass produced identical SHA-256 hashes.
The 25-batch M-5 follow-up reproduced periodic deletion-queue cleanup, confirming
that its apparent linear growth is bounded temporary retention.

## M-14: short I/O can starve GIL waiters

Added 2026-09-18 while investigating `concurrent_imap`. The relevant
`take_gil()` and `drop_gil()` implementation in the pre-fix method-JIT branch
is identical to `main` at `d95f29589e03603aa13d8ca9d4f817dce77d357c`.

Each iteration of `take_gil()` started another full switching-interval wait.
If the same holder released and reacquired the GIL quickly, its condition-variable
signals could repeatedly wake the waiter before its timeout. `switch_number`
did not change, but the waiter never reached the timeout needed to request a
forced handoff. A permanently ready poll descriptor is a practical trigger:
the polling thread can prevent the result-consumer thread from running, which
in turn keeps the descriptor ready.

The candidate native JIT and debug Tier 2 interpreter both reproduced multi-second
stalls and timeouts while repeatedly constructing `multiprocessing.Pool` and
consuming 1,000 identity results. Disabling method compilation alone did not
solve it. The frozen main baseline and JIT-off candidate completed the initial
control trials; that timing difference does not make the shared GIL algorithm
correct. A suspected glibc condition-variable defect was not sufficient to
explain this failure: both ABBA trials with private glibc 2.41 also timed out.
The system libc and global settings were not changed.

The local repair retains a monotonic deadline until `switch_number` changes
or a handoff request is sent. After a request, it starts another normal interval
so a holder still running C code does not cause short retry spinning.
Repeated signals from the same holder no longer restart the whole interval.
It affects only the contended acquisition path. A subprocess regression test
uses a permanently ready pipe and verifies progress while another thread polls.
Three debug trials of 100 Pools each complete with the repair. The optimized
GIL candidate also completes both `concurrent_imap` results with the original
6 workers, 5 warmups and 5 measured values, retaining the 60-second worker limit.
The final GIL PGO/full-LTO candidate also completes both results with that
original protocol in 33 seconds, with all 12 measured workers retaining JIT/GIL
and the executable hash verified unchanged. These are local validation results,
not an upstream submission or a proof of fairness on every platform.

Evidence: `jit-artifacts/pyperformance-fixes-20260917/`, especially
`pool-hot-before.log`, `pool-trace-only-debug.log`, `libc-diagnostic/`,
`pool-deadline-debug-{0,1,2}.log`, `pool-full-gil-native-v1.json`, and
`pool-full-gil-pgo-v6-state.json`.
