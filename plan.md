# Method-only JIT implementation and performance plan

Updated: 2026-09-20

Current goal: achieved for the measured cohort, with the exclusions below.
The candidate now uses static method compilation
and Tier 1 fallback only. The recording frontend and dispatch, side traces,
and tracing fallback have been removed. The user revised the performance goal
on 2026-09-20: individual regressions above 10% are acceptable; the complete
suite's geometric mean of candidate/main runtime ratios must be at most 1.00.
Evaluate GIL and free-threaded configurations separately, report all individual
regressions and missing specifications, and retain every measured worker.

## Current execution status

M56b is the final measured candidate. Both complete pyperformance profiles,
the original local eight, correctness validation, identity audits, and the
report are finished. Compiled runtime sources and generated outputs still
exactly match the measured snapshot (patch SHA-256
6c30ed6fec1151f4cd2354665dc95517779162b05fd0a31f496910af58fad573).
After measurement, the unused TIER2_TO_TIER2 generator handler was removed
and the retained Tier 1 exit handler was named directly. Regeneration changed
no output; all 84 generated-cases tests passed. An audit of 3,869 tracked
source files found only these two generator scripts different from the frozen
source. The separate cleanup patch and audit are saved as
`jit-artifacts/regressions-20260919/m56b-final-generator-cleanup.patch` and
`m56b-postmeasurement-generator-audit.json` in the same directory.

- GIL PGO/full-LTO: 122 results, geometric mean 0.97050770,
  95% worker-bootstrap interval [0.96825009, 0.97309775]. Runtime is 2.95%
  lower than tracing main. Both ordered blocks are below 1.00.
- FT O3, no PGO/LTO: 121 results, geometric mean 0.92705223,
  interval [0.92648257, 0.92762676]. Runtime is 7.29% lower than main Tier 1;
  this fixed FT main does not create JIT executors.
- Remaining GIL point regressions above 10%: shortest_path 1.14919,
  sympy_expand 1.14804, base32_small 1.10108. They remain in the aggregate.
  shortest_path has two candidate process speed bands; its cause is unknown.
- Missing specifications: FastAPI dependencies and networkx_k_core timeouts
  in both profiles; additionally FT Dask due to main's block-0 SIGSEGV. Dask's
  other FT runs and all four GIL runs succeeded. Failed attempts are retained.
- All 64 original local-eight runs passed, including checksums and identities.
  Separate local geometric means: FT 0.74136, GIL 0.82743. The FT SQLAlchemy
  declarative ratio is 1.01171; every other local point estimate is below 1.
- Frozen GIL/debug/FT correctness checks and the eight runner tests passed.
  The full four-way suite attempted 384 runs per profile. No more builds,
  timing runs, or required implementation work remain for the revised goal.

Final report: [benchmarks/method_only_m56b_results.md](benchmarks/method_only_m56b_results.md).
It includes all results, intervals, missing specifications, binary hashes,
methodology, and the separate boundary confirmation. The comparison includes
existing C fixes as well as JIT changes; it does not isolate the frontend's
causal contribution. FT still disables JIT on a second live thread state.
Potential subsequent work is to diagnose the retained process speed bands and
SymPy regression, and reproduce main's frame-inspection crash; these are not
requirements of the user's revised geometric-mean goal. No upstream actions
were performed. The user subsequently requested a local checkpoint commit of
the implementation, tests, reports, and principal measurement records.

The checkpoint preserves the measured runtime and both language versions of
the comparison report. Source identity was checked again against the frozen
M56b tree: only the two already-validated generator cleanup files differ.
Saved final validation records all report success; no runtime change requires
another build or benchmark run. Build trees, dependency caches, and unrelated
local files remain outside the commit. The pre-existing go.py executable-bit
change is also left in the working tree.

This is suitable for exploratory design review, with known limits stated.
Before using it to decide between frontends, align the main revision, runtime
fixes, and build conditions for a direct three-way comparison. Before asking
others to reproduce it, replace local build/cache assumptions with documented
fresh-checkout steps. Concurrent FT JIT, broader platform validation, and
separating the frontend, optimizations, and C fixes into reviewable changes
remain future work, not claims of this checkpoint.

## Comparison with the earlier optimized tracing JIT

On 2026-09-20, compared `codex/tracing-jit` (`26c62af79da`) with M56b
in [Misc/method_gc.md](Misc/method_gc.md), following the user's correction
that the comparison concerns tracing JIT, not tracing GC. The report covers
changes from each main baseline, handwritten runtime/test diff sizes,
full-suite and matched-name performance, implementation effort, and the
remaining work for concurrent free-threaded JIT execution. The older raw
JSON hashes and process-mean ratios were rechecked, along with M56b's
worker-mean ratios. No new runtime changes, builds, or timing runs were needed.
The two historical GIL results both show about 3% less runtime than their
respective main baselines; their different build settings and baselines do not
establish a direct performance advantage for either frontend. A future direct
comparison requires matching those conditions. No such run is pending here.

## Execution history

The following are chronological status snapshots, including earlier criteria
and intermediate candidates. They do not replace the final result above.

The complete M56b FT comparison has finished: 384 planned run attempts,
121 comparable results, all runtime/dependency/workload identities verified.
The balanced two-block geometric mean is 0.92705223 (7.29% less runtime).
No individual completed point estimate exceeds 1.10. Missing specifications:
FastAPI dependencies, networkx_k_core timeouts, and Dask's main block-0 SIGSEGV.
Dask's other three runs, including main block 1, succeeded; its failed cohort
is retained and the incomplete specification is excluded. GIL PGO/full-LTO
measurement is now running. Bootstrap analysis follows both profiles so that
analysis does not compete with timing. Local eight and final report remain.

The first complete GIL PGO/full-LTO block has 122 comparable results and a
provisional geometric mean of 0.97018531 (2.98% less runtime than tracing main).
Individual ratios above 1.10 in that block are sympy_expand 1.14887,
deepcopy_memo 1.10899, and base32_small 1.10214. These are retained under the
revised aggregate criterion, not individually tuned away. The reversed GIL
block is running; await it and the identity audit before accepting the result.

Following that explicit goal change, use the already validated M56b snapshot
for the full four-way comparison and the original local eight. An unvalidated
tuple-isinstance prototype was saved as m57-unvalidated-tuple-first-experiment.patch
and removed from the working runtime; both edited files match the frozen M56b
source again. Do not introduce another build merely to meet the old individual
base32 threshold. The existing boundary confirmation is retained, not rerun.
The new full-suite controller is m56b-full-geomean-controller.log; it reports
individual regressions without blocking the suite at 1.10. The public runner
is repinned to the validated M56b GIL PGO/full-LTO and FT O3 no-PGO/no-LTO builds.
All full-suite/local results and the resulting report must still be inspected.

The full suite is running. FT block 0 Dask completed for the candidate, but
the fixed main worker crashed during loop calibration with SIGSEGV (-11).
The Python stack is distributed.profile.process reading prev.f_code (line 192),
and the native fault resolves to Py_INCREF inside PyFrame_GetCode. This is a new observed failure of
the comparison baseline, not evidence of a method-JIT regression. Preserve
the failed run and exclude an incomplete Dask pair from the aggregate; do not
retry until favorable. Inspect both profiles/blocks and report the failure
without claiming its root cause or that the candidate fixes it.

FT block 0 completed. Its provisional geometric mean is 0.92677 over 121
comparable results; this is not the final acceptance estimate. Dask is missing
because main crashed, and networkx_k_core timed out on both sides at the
predeclared 15-second worker limit. FastAPI dependencies remain unavailable.
The reversed second block is running; GIL PGO/full-LTO follows, then the local
eight and complete identity verification. Do not mix this one-block estimate
with the earlier screens or the one-off borderline confirmation.

The records below used the previous per-result <=1.10 criterion.

The M56b final FT screen also completed (28 runs, 10 results), with verified
identities and every confidence-interval upper endpoint below 1.10. The one
predeclared boundary confirmation is complete: base32_small 1.10183
[1.10063, 1.10309], deepcopy_memo 1.09651 [1.05581, 1.13812], Genshi XML
1.09106 [1.08586, 1.09588]. All workers are retained. Consequently the full
matrix gate stopped before repinning the public runner or starting that suite.
M56b is not an accepted final candidate. Native perf with the original base32
worker, fixed binaries and common loops, main/candidate and JIT 0/1, is next.
Use the resulting evidence for a focused correction; do not repeat the same
confirmation until favorable. deepcopy_memo's two process speed bands remain
an uncertainty even though its aggregate point estimate is below the limit.

M56 development is in progress. M55 final FT screen completed all 28 runs,
10 results, identities verified, no failures; every CI upper endpoint is below
1.10. Its GIL screen has one point-estimate failure: SQLGlot normalize 1.10958.
Four separate native perf runs (main/candidate, JIT 0/1) and a debug executor
dump completed with no errors. Candidate JIT still spends 18.43% of cycles in
EvalFrame (main 9.32%); special-method lookup/type lookup/isinstance also remain
material costs. Perf runs are diagnostics, not replacement timing evidence.

M56 adds a guarded default-metaclass isinstance operation. A static namespace
binding is a compile-time hint only: the live metaclass version must still
match the version whose __instancecheck__ descriptor was type's default.
The operation calls _PyObject_RealIsInstance, preserving overridden __class__
and its errors. Custom checkers and metaclass reassignment deoptimize. Two new
tests fail on frozen M55 at the missing optimization assertion. The initial
build lacked pycore_abstract.h in the JIT template; M56b adds that declaration.
All 1,366 debug/native tests and both new -R 3:3 tests now pass. All 20
M56b/M55 comparison runs succeed and identities match. Ratios (both method
JITs, no PGO/LTO): SQLGlot normalize 0.95275 [0.94545, 0.95954], Genshi text
0.99799, XML 1.00057, nqueens 1.00410, dulwich 1.00575, unpack_sequence 1.00332.
This supports retaining the change. Final FT debug validation, GIL PGO/full-LTO
and FT release builds/tests, and balanced main screens are now running in that
order. Development binary SHA-256:
1e2701a90487a4da0bd1f9fe83ab76db148bfd76b3fc0118dfe555e316a350b3.
No complete-suite run or public runner repin yet. All M55 results remain saved.

M56b FT debug validation and all GIL PGO/full-LTO validation groups passed.
The PGO corpus completed 43 files, 10,632 tests (265 skipped), JIT disabled,
seed 0; generation/training/final phases took 306.3/139.1/202.5 seconds.
Final GIL SHA-256: 9cb1ae62d6ae5a61f1bbbc56e7fbb9e9bdaae4128d2f516641b71e212c740e4b.
FT release build is next. `finish_m56b_full_and_local.py` waits for both final
screens, refuses any known point estimate above 1.10, then runs the complete
four-way matrix and original local eight sequentially and writes a full report.
It cannot mark the task complete; every result/failure still requires review.

Both M56b final-profile builds and all validation groups passed. FT release
SHA-256: 842f4ab84873e8132b08c82210199b5fd4702019acee4db49ebbc97184b48db0.
The final GIL screen is running. Both SQLGlot blocks now succeed at roughly
1.062 combined versus main (M55 was 1.10958): the metaclass correction also
helps the required PGO/full-LTO profile. Genshi XML is currently below 1.10;
deepcopy_memo remains noisy and near the boundary. Complete remaining screens
and the full matrix before making the overall claim; no source edits during
measurement. The automatic full-suite gate remains at every point ratio <=1.10.

Before any full M56b matrix, one bounded borderline confirmation is now
predeclared for base32_small and deepcopy_memo: two reversed blocks, six
independent workers per side/block, five warmups/five values, CPU 2, seed 0,
original unmodified workload scripts via --worker-task. Common fixed loops:
1024 for base32_small and 8192 for deepcopy_memo. All workers remain in the
primary mean; retain confirmation and screening separately. Motivation:
base32_small's first block is ~1.104, whereas one slower main worker lowers
the combined mean below 1.10. deepcopy_memo has two visible speed bands.
Do not declare equivalence from either distribution or discard slow workers.
`run_m56b_full.py` now runs this confirmation after the final screens and
refuses the full matrix if either confirmation point estimate exceeds 1.10.
The comparison is fixed once; do not repeat until favorable. Diagnose and
change the implementation if the regression is confirmed.

M56b GIL screen finished: 17 specifications / 36 results / 68 successful runs,
identities verified. All point estimates <=1.10. SQLGlot normalize is 1.06207
[1.05111, 1.07168]. Three CI upper endpoints cross 1.10: deepcopy_memo 1.09595
[1.03860, 1.15198], base32_small 1.09437 [1.07546, 1.10499], Genshi XML 1.08795
[1.07191, 1.10377]. FT screening is running. Before executing the already
planned borderline confirmation, extend its fixed cases to Genshi XML too:
original worker task 1, four fixed loops, otherwise the same six workers and
two reversed blocks. This is one confirmation of each of the three uncertain
results, not repeated screening until a favorable result appears.

### Previous frozen M55 validation

M55 is frozen for final-profile validation. All 1,364 debug/native tests and
six targeted -R 3:3 tests pass. All 20 fixed development comparison runs succeed;
binary/source/dependency identities match. M55/M41 (both method JIT, no PGO/LTO):

- dulwich_log: 0.98596 [0.97749, 0.99602]
- genshi_text: 0.90435 [0.89866, 0.90960]
- genshi_xml: 0.97478 [0.96870, 0.98028]
- nqueens: 0.97285 [0.96857, 0.97648]
- sqlglot_v2_normalize: 0.99175 [0.98877, 0.99446]
- unpack_sequence: 0.77574 [0.77378, 0.77809]

FT debug validation passed: 576 optimizer tests (42 skipped), 788 boundary
tests (1 skipped), and six continuation tests under -R 3:3. GIL PGO/full-LTO
and FT O3 no-PGO/no-LTO builds and validation also passed. The balanced final
main screens are running sequentially, without overlapping builds/tests.
Both GIL SQLGlot normalize blocks remain approximately 1.11: M55 does not yet
meet the +10% goal. Genshi XML, nqueens and dulwich point estimates have fallen
below 1.10. After both screens finish, diagnose SQLGlot using separate native
perf and executor inspection, then validate a focused correction before the
complete suite and original local-eight comparison. All builds use C _decimal.
No final main +10% claim yet; retain all M55 screen results even if superseded.
Frozen development binary SHA-256:
74fafd3c378cb2e0ebb9a803321f8768724b5a7ffb7f0ac977f50ac4c7186b66.
Controller: jit-artifacts/regressions-20260919/finalize_m55.py.
The public four-way runner remains pinned to M40c until a final candidate passes.

M55 final GIL screen completed: 17 specifications, 36 results, 68 successful
runs; identities verified before/after. Only SQLGlot normalize exceeds the
point-estimate limit: 1.10958 [1.10165, 1.11812]. Genshi XML is 1.09599
[1.09001, 1.10199], and deepcopy_memo 1.07616 [1.02740, 1.12958], so their
intervals still cross 1.10. FT screening is next. Separate four-way SQLGlot
native perf (main/candidate, JIT 0/1) and an untimed debug executor dump are
queued after both screens. Complete-suite scripts remain gated; do not run
them or repin the public runner until known regressions are corrected.

## Historical experiment notes

The following entries retain each experiment's observations and planned next
step at the time. The current execution status above takes precedence.

M52b passed all 1,359 debug/native tests and -R 3:3. All 16 comparison runs
succeeded, identities matched. M52b/M41: text 0.97977, XML 1.00906, nqueens
0.98325, dulwich 0.99787, SQLGlot normalize 0.98723. Retry backoff removes the
M52 regression but does not materially improve XML. Final-profile builds have
not started; the main +10% criterion is still unmet.

M51b validation completed: all 1,358 debug/native tests pass and its two new
tests pass -R 3:3. All 16 development runs succeed with matching identities.
M51b/M41: genshi_text 0.98413, XML 1.00812, nqueens 0.98542, dulwich 1.00402,
SQLGlot normalize 0.99367. Identity fusion has not produced a substantial XML
improvement. M49's removal of native generator connection remains; M45 ordinary
generator RESUME support and M47/M50 correctness fixes remain. After M52 is
validated, evaluate GIL PGO/full-LTO and FT snapshots, then complete-suite and
original local-suite comparisons. The 10% goal remains unmet.


M46b development timing exposed a correctness failure in both Genshi variants:
TypeError on generator iteration; debug asserts that the caller IP is not
FOR_ITER/SEND. A 270-NOP loop reproduces it without Genshi. The saved IP points
to EXTENDED_ARG, while generator yield/exhaustion continuations are relative to
the actual FOR_ITER opcode. M46c saves opcode_offset for normal emitted uops;
guard exits still restart at the prefix offset. A regression test covers warm
and cold generators and exhaustion. Both failed timing orders are preserved;
M46b comparisons are not valid performance evidence. Debug validation comes
before rebuilding and remeasuring the corrected candidate.

M46c's EXTENDED_ARG fix passes the original Genshi reproducer and all 1,356
combined debug tests (6 skipped). The new regression test fails on frozen
M46b as intended. Its first -R 3:3 run retained executor-deletion memory;
M46d adds the same explicit executor cleanup used by neighboring tests, and
-R 3:3 passes. A fresh no-PGO/no-LTO snapshot, native tests and a fixed balanced
comparison against M41 are queued sequentially. Native perf diagnostics will
follow timing, separately, for Genshi XML and nqueens if needed.

M46d's frozen native build passed all 1,356 tests (8 skipped). Balanced M46d/M41
comparison completed with no failures and matching identities: Genshi text
1.04408 [1.03823, 1.04971], XML 1.04799 [1.03810, 1.05769], nqueens 1.04052
[1.03789, 1.04293], dulwich 1.00090, SQLGlot 0.99241. This is not an accepted
speedup. Four separate native perf runs completed after timing. Nqueens spends
less time in EvalFrame (19.39% to 6.99%) but adds per-yield native call overhead.
Genshi _include/_flatten lack hot resume executors: a debug reproduction reports
CFG analysis rejection. Investigate that rejection before further design changes.

M47 fixes a second EXTENDED_ARG issue: when a loop executor replaces its first
prefix, method_decode_cfg unwrapped ENTER_EXECUTOR only after accumulating
prefixes. It then analyzed the prefix and jump separately with a truncated
jump distance. This caused Genshi resume roots to follow impossible control
flow and fail stack analysis. Decode the original code unit before accumulating
each prefix. A long-generator-loop regression test fails on frozen M46d (missing
resume executor). The debug Genshi probe now installs _include/_flatten resume
executors without analysis rejection. Also align dynamic-call return offsets
with the actual opcode IP fixed in M46c. Full debug/native tests and fixed
M47/M41 measurements are running sequentially; no full-suite claim yet.

M47 passes 1,357 debug/native tests and the new test's -R 3:3 check. All 16 timing
runs succeed, identities match, but M47/M41 remains slower: Genshi XML 1.05855
[1.0486, 1.0685], text 1.0309, nqueens 1.0418, dulwich 0.9929, SQLGlot 0.9989.
Keep both EXTENDED_ARG correctness fixes regardless of generator-path policy.
M48 generalizes the existing unknown-type module-binding load to other mutable
global objects. Watched dictionary bindings supply identity, never a constant
type; __class__ mutation, custom truth testing, replacement and deletion remain
observable. The new semantic/optimization regression test fails on M47. Rename
_LOAD_MODULE_BINDING to _LOAD_GLOBAL_BINDING and regenerate metadata. FT retains
its immortal-only embedding policy. Validate before fixed-binary comparison.

The current source is M51b development; M41 was debug/native validated. M40c is the
completed comparison baseline below. M41 passes the initializer object already
found in the constructor's type cache to method_lookup_function, instead of
depending on the direct-mapped function-version cache. A cache-eviction and
initializer-code-mutation regression test fails on M40c (_METHOD_CALL(1)) and
passes on M41 (_METHOD_CALL(2)). The incremental debug build succeeded in 28.2s;
isolated test_opt passes 562 tests (5 skipped), and five constructor tests pass
-R 3:3. The seven related files pass 589 tests. A combined single-process run
has 35 optimization-expectation failures; the identical order also fails those
35 tests on frozen M40c. Keep that separate test-isolation issue recorded.
The fresh GIL development build without PGO/LTO passed native opt (562 tests)
and related boundaries (589 tests). Its SHA-256 is
f53e6bcf0a365a4617c12625df56d41e5d55d0c633f2c502dd368a7740a40919.
Direct fixed-binary M41/M40c float comparison is 0.9292 [0.9240, 0.9348],
blocks 0.9287 / 0.9296, with identities verified. This is a 7.1% reduction
without PGO/LTO, not a final main comparison. The 13-specification M41/main
development screen completed all 52 runs and 32 results, identities verified;
all 95% interval upper bounds are below 1.10. The slowest is genshi_text
1.0865 [1.0797, 1.0949]; genshi_xml 1.0769, sqlglot_v2_normalize 1.0748,
nqueens 1.0666, deepcopy_memo 1.0482 and logging_format 1.0286.
The frozen M41 GIL PGO/full-LTO build passed (generate 304.9s, standard JIT-off
PGO training 139.8s, final build 203.0s), with SHA-256
32486c192eb3bd26ed2046beea1000e6896b7290da60f609f10d6f41369ab4cd.
All four final native validation groups passed. The 16-specification / 35-result
targeted screen completed; its results are recorded below. This does not
replace the unfinished final full-suite verification or FT connected-components
uncertainty confirmation.

M41 final targeted comparison is complete: all 64 runs / 35 results succeeded,
with identities verified. Float is 1.0275 [1.0251, 1.0295], but genshi_xml is
1.1356 [1.1287, 1.1421], dulwich_log 1.1114 [1.0542, 1.1510], and nqueens
1.1040 [1.0838, 1.1194]. Genshi text, SQLGlot normalize, deepcopy_memo and
shortest_path also have intervals crossing 1.10. Keep both orders and all workers.
The goal is still unmet. M42 development now tests generator creation directly
from the frame whose arguments have already been bound by the call uops.
It preserves the compiled caller's continuation, uses RETURN_GENERATOR's frame
transfer, and leaves MAKE_CELL/extended prefixes in Tier 1. This is different
from rejected M37's vectorcall rebinding. The new native-continuation test fails
on M41 as expected. Debug build M42 exposed an unavailable ceval-only inline
helper; M42b uses the equivalent recursion-depth increment and is building.
A separate test-only setUpModule resets rare-event counters using the existing
internal test API, to verify the previously recorded 35 order-dependent failures.
M42c debug creation tests pass for generators, coroutines (including origin
tracking) and async generators. The OOM expectation was corrected against M41:
incomplete generator frames do not appear in tracebacks, so the caller CALL is
the proper location. All 565 isolated optimizer tests passed. Resetting rare-event
counters removes the earlier 35 combined-order failures; two new continuation
assertions remain after prior monitoring changes. M42e recognizes creation before
the first traceable instruction, leaving instrumentation and pending-event handling
to first RESUME. A local PY_START monitoring test checks that creation emits no
start event and first resume emits exactly one. M42/M42b build errors were missing
header/ceval-only helper declarations, fixed without changing the runtime design.
M42e passes the combined debug order (1,155 tests), coroutine/async-generator
boundaries (199 tests), and the five creation-related tests. Initial -R 3:3
reported memory-block growth in the two new in-process tests (no reference-count
growth). Explicit caller-executor cleanup and draining the deferred deletion list
resolve it: M42g passes all five tests with blocks [2, -3, 3], sum 2 accepted by
the harness. Resetting the shared generator code itself was rejected because it
changes the function-version identity being tested; only caller code is reset.
No runtime change was needed for that test cleanup. Fresh GIL development and
FT debug snapshots are now building/validating from m42g-method-only.patch;
the affected-workload fixed-binary old/new comparison follows sequentially.
M42g GIL development build completed in 80.9s (configure 21.0s), SHA-256
2d9e0c32211ef1adc211e11f35aab73ffd0b0dfc95ab5e8eebf6e1e5904db8a0.
Its native optimizer tests (566, 5 skipped), seven boundary files, and both async
files pass. Patch SHA-256 is
612492779d7f461f0969dc6446727b4f58c483ef7d5719e252b0e4ef770bf6b5.
FT debug completed in 104.1s; all three native validation groups passed,
including test_opt 566 tests (39 skipped). The fixed M42g/M41 development
comparison completed 16 runs / 5 results, all identities verified:
genshi_xml 1.02435 [1.01876, 1.03015], genshi_text 1.00565,
nqueens 1.01005 [1.00655, 1.01382], SQLGlot normalize 1.01083,
and dulwich_log 0.99708 [0.99179, 1.00187]. This form is rejected as a speedup.
The _METHOD_CALL native stencil grew from 761 to 1,247 bytes because each call
site contains generator allocation and frame-transfer code. M43 moves that code
to _PyJit_CreateGenerator in optimizer.c, keeping ordinary compiled-method calls
on their previous inline path. Existing creation/monitoring/OOM/refleak tests
are reused. Debug validation, a fresh GIL development build, and the same
M41 comparison are sequential; FT validation of the outlined version remains pending.
M43 debug creation/combined/async/refleak groups all passed. Its fresh GIL native
build completed in 81.2s, SHA-256
d3e0134fec989bdb19c45c1d09d7d6aefdf2997700f7344161591e7a864ff96e.
Native optimizer/boundary/async groups also passed. The _METHOD_CALL stencil is
880 bytes, down from M42g's 1,247 but still above M41's 761. The fixed M43/M41
five-result comparison is now running. Code-size reduction alone is not evidence
of a runtime improvement.
M43/M41 measurement completed with all identities verified: Genshi XML 0.99939
[0.99230, 1.00605], Genshi text 0.99490, dulwich 0.99759, SQLGlot 1.00068,
but nqueens 1.00834 [1.00355, 1.01369]. Outlining removes the larger slowdown,
without a useful speedup. Both M42/M43 generator-creation changes and their
feature-specific tests are reverted; M41 constructor discovery and the independent
rare-event test isolation fix remain. Frozen snapshots, failures and timings remain.
M44 lowers specialized FOR_ITER_GEN through existing _METHOD_FOR_ITER so a
synchronous iterator call can return to a compiled consumer body. It reuses the
existing exhaustion edge, exception handling and escaping-call semantics; no new
recording, generator-state prediction or suspension-crossing facts are introduced.
A native-consumer test fails on M41 (active count 0); an exception/finally-state
test accompanies it. Debug validation is running. Existing tests that require
consumer compilation to be unavailable will be reviewed against observed results.
This experiment may trade direct frame transitions for C-call overhead, so it
must be retained only if balanced measurements support it.
M44's two new tests pass. Full debug test_opt runs 564 tests and fails only
three old expectations that generator consumers cannot have executors; Python
results and the other 561 tests pass. Those tests now require a useful compiled
consumer loop, including recursive trees and 12-layer delegation. The five
consumer-related tests are running -R 3:3; that includes the expensive recursive
tree fixture. After it passes, the combined debug order, async tests, fresh GIL
development build/native checks, and fixed M44b/M41 comparison run sequentially.
The M42/M43 creation experiments remain available as frozen artifacts, but are
not part of M44b. Any interaction with consumer compilation must be measured
separately before such a path could be reconsidered.
M44b's five consumer/delegation tests pass -R 3:3 (three measured iterations
have no growth; total 123s). Combined debug validation passes 1,153 tests,
and both async files pass. The frozen GIL development build and native checks
completed before the four-specification old/new comparison. M44b/M41 results
reject the generic C-iterator approach: genshi_text 1.24771, genshi_xml 1.29424,
nqueens 1.13686, dulwich_log 1.00656, SQLGlot normalize 1.01656, with all identities
verified. The consumer lowering and its feature-specific test changes are reverted.
Direct FOR_ITER_GEN frame transitions remain unchanged.

M45b enables method compilation at ordinary-generator RESUME locations before
and after a yield (excluding yield-from, coroutines and async generators). Such
entries use the live stack depth and unknown locals, just like generator OSR;
no type or ownership facts cross suspension. CFG layout starts at that resume.
Generator close decodes an installed executor's original RESUME argument before
using the existing fast-close condition, preserving finally/unwind behavior.
Two tests fail on M41 due to absent RESUME executors and pass on M45. Full debug
optimizer validation passes all 564 tests (5 skipped). The generator assertion
helper now accepts either RESUME or JUMP_BACKWARD entry. Combined/async/refleak
validation, fresh GIL native build/tests, then the same old/new performance
comparison are running sequentially. FT validation and final-profile measurements
remain pending.
M45b combined debug validation passes 1,153 tests; async boundaries and both
new resume tests under -R 3:3 also pass. A fresh GIL development build is now
completed, along with all native checks. M45b/M41 completed all 16 runs / 5 results,
identities verified: nqueens 0.98394 [0.98119, 0.98673], dulwich 0.99160,
Genshi text 0.98810, SQLGlot normalize 0.98858, but Genshi XML 1.02337
[1.01205, 1.03524]. RESUME compilation alone is insufficient.

M46b retains M45b resume entries and adds a dedicated _METHOD_GENERATOR_CALL.
FOR_ITER_GEN keeps its direct frame transition and exception-state setup. The new
helper enters an existing native RESUME executor (handling the initial None pop)
and returns to the compiled consumer only when the frame and yield continuation
match. Missing executors, changed instrumentation/TLBC, recursion margin, errors
or other continuations return to Tier 1 with synchronized frames. Ordinary
_METHOD_CALL code is unchanged. Frame-transition and optimizer barriers include
the new uop, and all 11 generated files were regenerated.
Three new native-consumer/exception/invalidation-GC tests pass. The invalidation
callback also overwrites the consumer's iterator local; no Python reference to the
executor is retained by the test. All three pass -R 3:3. Full debug test_opt
fails only the three old no-consumer-executor expectations; these now validate
the native-call operation and intact recursive/delegation results. Combined and
async validation, fresh GIL native build/tests, then fixed M46b/M45b and M46b/M41
comparisons are sequential. FT and final builds remain pending. Combined debug
validation passes 1,156 tests and async files pass. The fresh native GIL build
completed in 81.3s, SHA-256
8db320e6c2f10453063f05e2b87f38eed56d3da068d1bf3a8b52a240ddc98348;
its opt/boundary/async groups all pass. Ordinary _METHOD_CALL remains 761 bytes;
the new dedicated generator-call stencil is 406 bytes. The two fixed-binary
comparisons are now running, with no concurrent builds or tests.

M40c retains M39's cached-small-int range path and
retires stale extended-arithmetic guards only after Tier 1 changes their opcode
or descriptor. Ordinary polymorphic guard misses keep the method valid.
Deterministic direct-call, inlined-call, descriptor-change and logging elapsed-time
probes validate this behavior in GIL and free-threaded builds.

All development validation, the 15-result no-PGO/no-LTO screen, both final builds
and their eight validation groups pass. The final GIL screen completed all 40 runs
and 26 results with identities verified and every 95% interval upper bound below
1.10. Nqueens is 1.0842 [1.0807, 1.0875], logging_simple 1.0473 [1.0283, 1.0655],
and logging_format 1.0784 [1.0642, 1.0946]. This resolves the known M38b screen
uncertainties; these targeted results do not establish the complete-suite goal.

The public comparison runner pins M40c, and its eight tests pass. The full
97-specification, four-configuration comparison finished at
jit-artifacts/method-only-m40c-full with identities verified. Both profiles have
95 successful specifications / 122 results. Fastapi dependency preparation and
networkx_k_core's short timeout remain explicit failures.
FT's geometric mean is 0.9281, with all point estimates below 1.10 (largest:
gc_traversal 1.0569). GIL's mean is 0.9792, but six results exceed 1.10:
float 1.1181, genshi_xml 1.1118, deepcopy_memo 1.1094,
sqlglot_v2_normalize 1.1093, dulwich_log 1.1070, regex_v8 1.1009.
The local eight finished in both profiles, with all ratios below 1.10 and
identities/checksums verified. FT ranges from 0.3442 to 1.0063; GIL from
0.5233 to 0.9925. The complete-suite goal remains unmet.
Genshi_text, logging_format, and connected_components also have intervals
crossing 1.10; connected_components needs confirmation in both profiles.
Preserve all workers and this fixed M40c dataset while diagnosing and fixing
the remaining regressions. The complete M40c dataset is reported in
[the fixed M40c results](benchmarks/method_only_m40c_results.md).
All uninstrumented M40c timing has stopped; a balanced JIT-disabled comparison of deepcopy,
dulwich_log, float, genshi, regex_v8, sqlglot_v2 and logging completed: all 28 runs
and 12 results pass, identities verified. JIT-off ratios: float 1.0034,
genshi_xml 0.9539, deepcopy_memo 0.9816, sqlglot_v2_normalize 1.0108,
dulwich_log 0.9838, regex_v8 1.0320, logging_format 1.0078.
Original-worker perf profiles exclude imports, warmups and executor dumps.
The float candidate spends 9.82% in EvalFrameDefault, versus under 0.3% in main's
flat profile. Its constructor loop contains _METHOD_CALL(1), with no initializer
executor. Both binaries report Point.__init__ version 822 evicted by
ZipExtFile.read1. Main traces inline it; the method compiler finds the initializer
but omits the known callable hint. This is the concrete M41 fix above.

The first GIL full-suite block has a new over-threshold result: deepcopy_memo
1.1752 (main worker means 11.854/11.898/11.826 us; candidate
14.417/12.941/14.452 us). Ordinary deepcopy is 1.0280 and deepcopy_reduce
1.0039. Finish both orders before diagnosis/profiling, preserving all workers;
this is an open performance issue, not a successful complete-suite result.
The complete first GIL block has 95 successful specifications / 122 results,
geometric mean 0.9814. Its six over-threshold results are deepcopy_memo 1.1752,
regex_v8 1.1729, float 1.1322, genshi_xml 1.1138, dulwich_log 1.1096 and
sqlglot_v2_normalize 1.1086. The reverse-order block is now running. After the
matrix and local eight finish, diagnose these with matched JIT-on/off runs and
perf before changing runtime code. Keep the completed M40c dataset intact.

The existing main module-subclass descriptor bug is fixed in M36 and retained
(M-18 in bugs_report.md). Earlier M33 full-suite timing was cancelled for an
integer-correctness bug, and the first M34 screen was invalidated for overlapping
a diagnostic. Those logs are retained separately and are not performance evidence
for the current candidate. See [the current report](benchmarks/method_only_report.md).

Prior goal (the hybrid implementation): all eight standalone workloads, including SQLAlchemy,
meet candidate/main <=0.90 with each 95% interval upper bound below 0.90 in
the prespecified 12-block fixed-binary/CPU confirmation. See
[the final report](benchmarks/jit_comparison.md) and the final entries below.
The implementation, regression tests, final report and confirmation evidence
are included in this local changeset. Earlier sections retain the chronological
history of completed tasks and experiments.

## Scope

Implement and validate the method-only JIT on `codex/method-jit`, comparing
with main `d95f29589e03603aa13d8ca9d4f817dce77d357c`. Record newly discovered
main bugs and their fixes in `bugs_report.md`.
Keep all work local: no GitHub posts, pushes, or pull-request changes.  Builds
use the installed LLVM 21. Development builds omit PGO and LTO; use them for
the requested final GIL profile comparison. Both sides use C `_decimal`.

## Progress

- Completed M-1 through M-4: corrected dict receiver guards, builtins and
  globals identity guards, and short-loop retry countdown selection.
- Diagnosed M-5: the apparent linear growth is the bounded executor deletion
  queue.  A 25-batch run showed periodic drops at the 1000-executor cleanup
  threshold, so no runtime change is warranted.
- Completed M-6 through M-10: numeric replica ordering, complete stencil and
  recorder dependencies, the recorder default path, and reviewed non-escaping
  API classifications.
- Completed M-11 and M-12 in the assembly optimizer: local references from
  instructions and preserved data now keep constant pools and jump-table case
  blocks live.
- Completed P-1 and P-2: inherited method descriptors accept compatible
  subclasses, and folded globals use per-name value dependencies while keys
  structure and namespace identity remain guarded.
- Regenerated all affected checked-in cases from their source definitions.
- Completed native LLVM 21 stencil generation and release JIT builds with
  ordinary compiler flags.  A normal incremental `make` detected the optimizer
  header change, regenerated stencils, rebuilt `optimizer.o`, and relinked the
  executable.

## Design decisions

- Globals identity stays separate from the keys version because copied dicts
  can share keys while holding different values.
- Globals dependencies distinguish value replacement from structural mutation.
  Bloom-filter collisions may conservatively invalidate but cannot preserve an
  invalid executor.
- Stencil reachability scans known assembler labels instead of recognizing a
  target-specific jump-table syntax.  This also covers compiler-created
  constant pools.
- M-5 retains the existing delayed deletion protocol because immediate freeing
  would risk releasing machine code still active on another thread.

## Validation

- Fresh Tier-2 debug interpreter build: success.
- Fresh native JIT release build: success.  Its configure arguments contain
  `--enable-experimental-jit=yes` without PGO or LTO.
- Native executor probe: `sys._jit.is_available()` and
  `sys._jit.is_enabled()` are true, and `get_jit_code()` returned 4096 bytes.
- Native `test_optimizer test_capi.test_opt`, with JIT disabled: 327 run,
  3 skipped, success.
- Native `test_optimizer test_capi.test_opt`, with `PYTHON_JIT=1`: 327 run,
  3 skipped, success.  The final run used the final rebuilt executable.
- Tier-2 debug `PYTHON_JIT=1 test_capi.test_opt`: 319 run, 3 skipped,
  success.
- `test_generated_cases test_tools.test_jit`: 104 run, success.
- Namespace lifetime and non-string equivalent-key globals cases: success.
- Full LLVM 21 x86-64 stencil generation with ordinary flags: success after the
  reachability fix.  The focused fixture reproduced the latent constant-pool
  and jump-table deletion before the fix and passes after it.
- All affected generators were rerun.  A second regeneration preserved the
  SHA-256 hashes of every checked artifact.
- Python sources compile, the new standalone test file passes Ruff, and
  `git diff --check` passes.
- No PGO or LTO was used.

Native evidence identity:

- HEAD: `d95f29589e03603aa13d8ca9d4f817dce77d357c`
- HEAD tree: `b4962cb04902e6fe831959b47784e91214f68f32`
- Tracked working-tree diff SHA-256:
  `8d134b3de7ccc5b2f808f342568fc2954a103d520db13a147f23ebd82805d3bf`
- Native executable SHA-256:
  `69fb7ca0fbf0fbb100e7f6a65d6bde270c0ede73c502b8f94f3d1368ed8a0621`
- The working tree is dirty with the remediation changes; the new JIT tool
  test is still untracked and has SHA-256
  `d04480a1c10b222dc92a4f27f719845529f3c475c8852cb56289ec3db31521dc`.

## Next work

All bug-remediation work in this plan is complete.  The implementation,
regression tests, and reports are included in the same local changeset.  No
GitHub post, push, or pull-request change has been made.

The AGENTS.md command naming `test_tier3` cannot run on this revision because
that module is absent; `test_optimizer` is the current corresponding module.
`make patchcheck` also cannot determine the base branch because this checkout's
CPython remote has no discoverable default branch.  Its substantive whitespace
and syntax checks were run directly instead.

# PEP 836 method-JIT and free-threading plan

Updated: 2026-09-16

## Scope

Replace runtime path recording with a method-oriented frontend while retaining
the existing uop optimizer and copy-and-patch backend.  Make the resulting JIT
usable in a `--disable-gil` build.  Preserve the completed bug fixes above,
keep all work local, and build with LLVM 21 without PGO or LTO.

## Progress

- Read PEP 836 and mapped its frontend, middle-end, and free-threading goals to
  the current tree.
- Confirmed that current `main` has no method frontend: it records one executed
  path and turns conditional branches into guards and side exits.
- Located the free-threading blockers: `_PyOptimizer_Optimize()` returns early,
  executor insertion assumes the main bytecode array, reverse function/type
  caches are disabled, tests are skipped, and configure emits a warning.
- Reviewed the PEP author's public `method_jit` prototypes.  They predate the
  current recording frontend and are not the newer proof of concept described
  by PEP 836, so their code cannot be applied directly.
- Reviewed the public free-threaded JIT implementation.  Its first safe stage
  runs the JIT while an interpreter has one thread, atomically disables it and
  invalidates executors before a second thread runs, and re-enables it after
  returning to one thread.  This is the initial concurrency policy used here.
- Implemented a method-entry frontend.  It decodes the complete bytecode into
  basic blocks, discovers reachable blocks with a worklist, emits direct uop
  edges for conditional branches, jumps, and iterator exhaustion, and installs
  one executor at the entry `RESUME`.
- Kept the runtime recorder as a compatibility frontend for backedges and for
  methods outside the first supported subset.  The method frontend currently
  rejects generators, coroutines, exception tables, oversized methods, and
  Python-call inlining; an unsupported instruction exits explicitly to Tier 1.
- Regenerated all opcode and uop cases after adding the method control-flow
  uops.  Stack-cache allocation now records input-to-output offsets so direct
  CFG edges remain correct after inserted spill/reload operations.
- Enabled Tier 2 in a free-threaded build.  The JIT gate is atomic, reverse
  function/type caches use their existing locks, and executor insertion and
  restoration account for thread-local bytecode.
- Made executor validity atomic.  This is the synchronization point used when
  thread creation disables JIT execution and invalidates installed executors.
- Completed an LLVM 21 native JIT build with `--disable-gil`.  Method-sized
  branch and range executors both compile through the copy-and-patch backend.

## Design decisions

- The first free-threaded implementation preserves thread-local bytecode.  Its
  index 0 is the code object's main bytecode and is used while only one thread
  exists; later thread-local copies restore an `ENTER_EXECUTOR` to its original
  opcode when copied.
- Creating a thread state stops the target interpreter before publishing the
  new state.  JIT disablement, executor invalidation, code detachment, and exit
  table updates happen while the existing interpreter threads are stopped.
  This closes the transition race where a native executor could otherwise be
  modified while its first thread was still executing it.
- Function/type reverse caches are maintained under their existing locks in a
  free-threaded Tier-2 build.  The optimizer reads them only while JIT execution
  is restricted to the sole interpreter thread.
- Backward jumps and eligible method-entry `RESUME` instructions retain a
  dynamically gated JIT check in a free-threaded build.  Their hotness counters
  pause while a second thread exists, so temporary suspension cannot permanently
  prevent recompilation after the interpreter returns to one thread.
- The tracing recorder's strong reference to a range iterator is discounted
  only when it accounts for every reference beyond the active frame's reference.
  This preserves the free-threading ownership rule while allowing the existing
  range specialization to run during trace construction.
- Method compilation will be attached to the method entry and will select the
  full code object as its compilation unit.  Unsupported blocks will leave an
  explicit exit to Tier 1 rather than falling back to runtime trace recording.
- Method CFG construction and uop optimization remain separate so control-flow
  merge handling can be tested independently.
- Method CFG edges use an empty stack-cache signature.  Every predecessor
  spills before its edge, so a block has the same Python value-stack convention
  regardless of which predecessor reached it.
- Returns currently deopt immediately before `RETURN_VALUE`.  This lets Tier 1
  restore either an interpreter caller or a caller with Tier 2 cached state.
  Straight-line functions remain with the trace frontend until method returns
  can restore both caller forms without losing cross-call specialization.
- The existing linear symbolic optimizer is not run over a method CFG yet; it
  requires explicit merge-state handling first.  Specialized bytecode still
  expands to specialized uops, and the copy-and-patch backend consumes the same
  executor representation.

## Validation

- Fresh `--disable-gil --with-pydebug --enable-experimental-jit=interpreter`
  build: success, without PGO or LTO.
- Free-threaded runtime lifecycle probe: JIT enabled with one thread, disabled
  while a second thread was live, and re-enabled after it exited.
- Free-threaded `PYTHON_JIT=1 test_capi.test_opt`: 324 run, 3 skipped,
  success.  The three former class-wide free-threading skips were removed.
- Added a regression test covering executor invalidation, suppression of
  compilation while two threads are live, and recompilation after returning to
  one thread.
- Added method tests proving that an unexecuted conditional arm is present in
  the compiled CFG and that a specialized range loop follows direct method
  edges.  Both tests execute alternate inputs after compilation.
- A free-threaded debug probe compiled entry executors for a conditional loop
  and a range loop, then produced correct results for values that exercise all
  branches.  Direct Python callers remain correct because returns deopt before
  frame teardown.
- The generic method iterator error path now emits a declared uop error edge;
  generated metadata and handlers therefore distinguish exhaustion from an
  exception.
- Final free-threaded and GIL debug regression runs each passed
  `test_capi.test_opt`, `test_optimizer`, `test_generated_cases`, and
  `test_tools.test_jit`: 435 tests run, with 3 and 4 skips respectively.
- The free-threaded native LLVM 21 build passed the same 435 tests, plus all
  245 `test_threading` tests and 17 focused free-threading code, function, and
  thread-state tests.
- The native branch method produced 4096 bytes of machine code and correctly
  executed both arms, including the arm not used during warmup.  The native
  range method produced 8192 bytes, was invalidated while a second thread was
  live, and was regenerated as a distinct 8192-byte executor after that thread
  exited.  A 25-cycle invalidate/recompile stress probe also passed.
- `make regen-cases` was run with `/usr/bin/python3.12`; all 11 generated-file
  SHA-256 values matched the pre-regen snapshot.  `git diff --check` passed.
- The host's user-installed Python 3.13.11 intermittently failed to reap short
  asyncio LLVM subprocesses.  Stencil generation used `/usr/bin/python3.12`
  with `/usr/lib/llvm-21`; no source workaround, PGO, or LTO was used.
- `method_jit_status.md` records the final implementation boundary, supported
  subset, validation matrix, and remaining work for this local snapshot.

## Next work

Add merge-aware symbolic optimization so type and constant facts can flow
through the method CFG.  Then replace the current Tier-1 return deopt with a
method return protocol that preserves cached state for both Tier-1 and Tier-2
callers.  Those pieces are prerequisites for enabling straight-line methods,
Python-call inlining, exception-table regions, and performance evaluation of a
broader method-JIT subset.

# Merge-aware optimization and call/return plan

Updated: 2026-09-16

## Scope

Implement the next six method-JIT milestones: per-block symbolic state,
conservative merge, loop fixpoint, CFG regression tests, focused benchmark
measurement, and a return protocol that enables straight-line methods plus a
guarded exact-Python-call inline path.  Retain the free-threaded single-thread
execution policy.  Use ordinary LLVM 21 builds without PGO or LTO.

## Progress

- Inspected the current frontend and confirmed that it linearizes reachable
  blocks but bypasses `_Py_uop_analyze_and_optimize()`.  Its branch uops carry
  no cache signature, and every return currently emits `_METHOD_DEOPT`.
- Chose a method-specific portable value lattice for locals and the Python
  value stack.  Block input states will be merged independently from the
  mutable symbol arena used by the tracing optimizer.
- Chose a bounded worklist fixpoint.  A successor is requeued only when its
  merged input loses or gains information, so loop headers converge to a
  conservative state.
- The first inline subset is an exact-argument Python function call whose
  function-version cache identifies one small, straight-line callee.  Version,
  PEP 523, recursion, stack-space, and code dependencies remain guarded.
- Implemented per-basic-block locals/value-stack states and conservative
  successor merging.  The worklist reaches a fixed point across range-loop
  backedges.
- Modeled the local transfers performed by `LOAD_FAST_LOAD_FAST`,
  `LOAD_FAST_BORROW_LOAD_FAST_BORROW`, `STORE_FAST_LOAD_FAST`, and
  `STORE_FAST_STORE_FAST`.  Without these cases, generated stack-effect data
  lost the value assigned by a fused instruction before the next bytecode.
- Verified the range-sum loop in the GIL debug build.  Its two exact-integer
  operand guards reduce to one `_GUARD_NOS_OVERFLOWED`: the range item remains
  a compact integer while the loop-carried accumulator conservatively loses
  the compact representation fact.  Results match Tier 1 for inputs 0--16.
- Added regression coverage for a same-type diamond, an incompatible
  int/string diamond, a same-type float diamond, and nested range loops.  The
  int merge reduces exact guards to overflow checks, the float merge removes
  both operand guards, the mixed merge deliberately retains its guards, and
  both loop headers converge.
- Replaced the method-return side exit with `_RETURN_VALUE` followed by
  `_METHOD_EXIT`.  Straight-line entry methods now tear down their frame and
  resume Tier 1 at the saved caller return offset.  Calls from both C (`map`)
  and a Python frame return the expected value.
- Added a bounded exact-call inline path.  It reads the specialized function
  version, resolves that version through the interpreter's reverse cache under
  its mutex, retains the function during compilation, and admits only an
  ordinary optimized function with no exception table, varargs, control-flow
  split, recursion to the root, or more than 128 code units.  The callee's
  `_RETURN_VALUE` continues the caller in the same executor.
- Added the inlined function to the executor dependency filter.  Replacing the
  callee's `__code__` invalidates the caller executor before the next call; the
  replacement result is then produced by Tier 1.  Eight focused method
  frontend tests pass in the GIL debug interpreter-JIT build.

## Design decisions

- Equal constants merge as that constant.  Different constants of the same
  exact type merge as the type; incompatible values merge as unknown.  Null
  and unbound-local state remain distinct.
- Unsupported bytecodes preserve correctness by applying their generated
  stack effect and producing unknown values.  Optimization is only performed
  when a fact is proved on every incoming edge.
- Loop backedges use the same merge operation as forward edges.  No widening
  beyond the finite constant/type/unknown lattice is needed.
- A top-level method return will tear down the current frame and resume Tier 1
  at the caller's saved return offset.  An inlined callee uses the existing
  `_RETURN_VALUE` uop and continues in its caller inside the same executor.
- Recursive, branching, generator/coroutine, exception-table, keyword, and
  general-call callees remain explicit side exits in this stage.

## Completed implementation

- Milestones 1--4 are complete: each block owns an input state for locals and
  the value stack, merges preserve only facts proved on every incoming edge,
  the circular worklist reaches a bounded loop-header fixed point, and tests
  cover int and float same-type diamonds, a mixed-type diamond, and nested
  loops.
- Milestone 6 is complete for its initial bounded subset.  `_METHOD_EXIT`
  returns a top-level compiled method to Tier 1 after `_RETURN_VALUE`, allowing
  straight-line methods called from C or Python.  `CALL_PY_EXACT_ARGS` can
  inline a small straight-line exact Python callee, and the caller executor is
  invalidated when the callee's code changes.
- NetworkX exposed a method-frontend side-exit bug after the initial focused
  tests.  An `_TIER2_RESUME_CHECK` following a completed call retained the
  call bytecode as its deoptimization target.  Once the periodic counter fired,
  Tier 1 repeated the call with its result stack and eventually raised
  `TypeError: 'str' object is not callable` in `Graph.add_edges_from`.  The
  method translator now resumes at the next bytecode, matching the trace
  translator, and restores the original target before translating every uop.
  A regression test drives the counter through the periodic exit using calls
  from C `map`.

## Validation

- GIL debug, free-threaded debug, GIL native JIT, and free-threaded native JIT
  builds all pass `test_capi.test_opt`: 332 tests run in each build, with four
  and three skips respectively.  The native free-threaded lifecycle test also
  confirms that JIT execution is disabled while a second thread lives and is
  re-enabled afterward.
- The same four builds pass `test_optimizer`, `test_generated_cases`, and
  `test_tools.test_jit`. The generated-case tests use fixed filenames such as
  `/tmp/input.txt`, so concurrent runs can interfere. The suite was rerun sequentially with a
  separate bytecode-cache prefix per build; every isolated run passed all 102
  tests.
- Fresh bytecode caches also exposed two stale free-threaded test expectations:
  ordinary int and float constants cannot use deferred refcounting because
  their types are not GC tracked.  The tests now require `_POP_TOP_INT` and
  `_POP_TOP_FLOAT` in both build modes; only immortal or genuinely borrowed
  values may reduce the operation to `_POP_TOP_NOP`.
- The completed-call regression passes a 3:3 debug refleak run with block
  deltas `[0, 1, -1]`, whose sum is zero.
- `make regen-cases` was run twice with `/usr/bin/python3.12`.  All 12 generated
  outputs matched both the pre-regeneration and second-regeneration SHA-256
  snapshots.
- Final LLVM 21 native executable SHA-256 values are
  `09ea0b2ed0658fbd439f619ea67fe9bf9d5176093f9ad15b491179127fe75a5b`
  for GIL and
  `76e5e1eeb57642bd4dcf6b5dfaf7ab5c3397246b2c2d19cd11cccdc21d6f61fa`
  for free-threaded.  Both report JIT available and enabled; the latter reports
  the GIL disabled.  No PGO or LTO was used.
- Milestone 5 used fixed-workload ABBA screens on CPU 2.  Candidate/main
  geometric-mean ratios were 0.9936 for Richards, 0.9932 for NetworkX
  `connected_components`, and 1.3418 for standalone Go.  NetworkX used an
  independent bytecode cache for each binary and a 15-second hard timeout;
  all four runs completed within nine seconds.
- The Go regression is stable rather than measurement noise.  A 20-value
  `perf stat` comparison found 48.1% more retired instructions, 40.5% more
  branches, and 32.7% more cycles in the candidate, while branch misses rose
  only 6.3%.  Executor inventories show that branch-heavy methods repeatedly
  pay empty stack-cache signatures at CFG edges, and Python calls outside the
  small straight-line inline subset return to Tier 1.  The path recorder can
  specialize across those executed calls. These are possible contributors,
  not a measured attribution of the regression.
- Raw samples, binary identities, perf counters, and the benchmark diagnosis
  are in `jit-artifacts/method-jit-milestones-20260916/summary.md`.

## Next work

All six milestones in this section are implemented and validated within the
subset described above. Performance improvement remains an open objective.

The commit audit found that the benchmark control is the archived September 13
main binary from `a60343ed17785ebbcd43de9080cadd8e2541db6f`, not this branch's
`d95f29589e03603aa13d8ca9d4f817dce77d357c` base. Its manifest also records
disabled LLVM vectorization for stencils. Keep the measured ratios as historical
comparisons, but do not attribute the whole difference to the method frontend.

1. Establish controls with identical source base, compiler and stencil flags:
   trace frontend, the prior method prototype, and the current implementation.
   Use the same prerequisite build fixes if main needs them, documenting each.
   Compare JIT on/off as well as the frontend variants, without PGO or LTO.
2. Measure dynamic method entries, exits by reason, return transitions,
   compilation time and native hot paths. Separate startup from steady state.
   Test feature variants individually to attribute costs; static uop inventories
   and aggregate perf counters alone do not establish causation.
3. Address the largest measured cost first. Candidates are repeated
   `_CHECK_VALIDITY` / `_SET_IP`, CFG-edge spills, and Tier-1 transitions at calls
   and returns. Preserve checks at escape/invalidation boundaries; propagate
   stack-cache signatures first across single-predecessor edges, then joins.
4. Extend bounded inlining to branching callees after measuring call-exit costs.
   Preserve function/code invalidation, error paths and the free-threaded gate.
   Validate mixed-type joins, overflow, callbacks and thread transitions.
5. Recheck Go, Richards and NetworkX after each independent change, then a
   fixed broader pyperformance cohort. Keep NetworkX's 15-second screen limit.
   Report geometric-mean runtime ratios together with individual regressions;
   these three screens cannot establish the broader 20% performance objective.

`git diff --check` passes. `make patchcheck` remains blocked by default-branch
discovery (`None` base branch); no source check failure was reported before it
stopped. No GitHub post, push, or PR change has been made.

# Controlled method-JIT performance follow-up

## Protocol and progress

- Compare three controls on the same patched d95f295 source base and the same
  GCC/LLVM 21 flags: trace-only (method compile returns unsupported), the prior
  prototype frontend, and the committed merge-aware frontend. Standard-library
  sources, native extensions and stencils are shared. Save distinct executables
  after each incremental link and record hashes in controls.json.
- Screen Go in three rotated process blocks, five warmups and twenty measured
  fixed-workload values. Use process means and geometric means of paired ratios.
  No builds run during measurements. Keep all runs, including failures.
- Artifact directory: jit-artifacts/method-perf-20260916. No PGO or LTO.
- First isolated candidate removes redundant validity/IP operations within
  basic blocks. It resets reasoning at every block entry and frame change,
  preserves IP before errors/escapes, and preserves validity after escapes.
  CFG joins and stack-cache conventions are unchanged in this experiment.

## Controlled diagnosis

- Rebuilt d95f295 main with identical LLVM 21 flags, plus only the prerequisite
  stencil local-reference reachability fix in Tools/jit/_optimizers.py.
  Go remains about 63.5 ms versus 84--89 ms for frontend controls. JIT-off is
  about 69.6 ms on main and 71--73 ms on this branch. Thus the historical LLVM
  flag difference does not explain the regression.
- A separate 55-operation native perf recording attributes 10.78% of samples
  to invalidate_dependencies and 3.64% to global-dependency invalidation.
  Named-global watching survives unrelated value changes but rescans every
  executor on each change. This is shared by trace and method controls.
- Add a four-slot negative dependency cache keyed by dictionary address and
  name hash, cleared on every executor link and dependency extension. Only
  value-only changes with no matching executor can enter the cache. Structural
  changes still scan, and removal of executors cannot introduce dependencies.
  This experiment retains the prior IP/validity cleanup; compare to that binary
  to isolate the cache contribution. Correctness tests cover dependency creation
  and extension after repeated negative lookups.

## Inline and edge implementation

- Extended the 128-code-unit inline budget to acyclic callee CFGs. Analyze
  callee joins independently; map each forward edge to a uop offset and each
  return to one caller continuation. Recursive/nested Python calls, loops,
  generators and exception-table callees remain outside this bounded subset.
- Remove adjacent unconditional edges only with one incoming edge. That lets
  the existing allocator retain cached values into that successor; multi-input
  joins keep the empty-stack-cache convention. Do not speculate across joins.
- New tests exercise both callee return paths, mixed joins, overflow, callback
  invalidation, and traceback instruction positions. GIL debug: 338 tests pass.
- Go after associative global miss caching and inline extension is about
  70.5 ms; adjacent-edge elimination is neutral in the isolated Go screen.
  Broader fixed cohort is predeclared in cohort.py: 24 workloads, identical
  calibrated loops, two reversed blocks of main/before/candidate, CPU 2,
  five measured values after three warmups, 45-second process cap (NetworkX
  15 seconds). All failures and raw pyperf data will be retained.
- An isolated instrumented native build will count method entries, exits and
  uops and method compilation time. Its timings are diagnostic only; unmodified
  executables are used for all performance comparisons.

## Dynamic diagnosis and validation

- Isolated native instrumentation counts Go's five steady-state operations:
  2,367,446 method entries, 1,043,586 unsupported-bytecode exits (44.1%),
  1,323,860 root returns, and no guard/periodic exits during this segment.
  Entries and return/exit counts are unchanged by this patch. Validity checks
  drop from 41,462,069 to 23,170,322 (-44.1%), saved IPs from 40,418,483 to
  17,218,663 (-57.4%), and method jumps from 2,286,412 to 626,499 (-72.6%).
  Spill/reload operations remain 21,923,473: adjacent-edge removal helps code
  shape but does not reduce Go's dynamic spilling. Branching inlining does not
  remove Go's remaining unsupported-call transitions.
- Method compilation during five warmup operations takes approximately
  0.77 ms before and 1.12 ms after (12 successes); five steady operations
  contain 15 failed attempts taking 0.31/0.26 ms. Instrumented wall times are
  not performance comparisons. Native perf and controlled timings are separate.
- GIL native release: 338 optimizer tests pass. GIL debug numeric, generator,
  tracing, monitoring and threading tests pass. Socket-based concurrent.futures
  tests initially fail in the sandbox; the authorized unsandboxed rerun passes
  all 746 tests across ten files (26 skips, including optimizer tests).
- Free-threaded debug and release optimizer suites each pass 338 tests after
  correcting two old assertions: numeric constants can be immortal depending
  on test-code loading, and then POP_TOP_NOP is the correct specialization.
  The tests now inspect the actual constant's immortality rather than assuming
  deferred refcounting or ordinary refcounting. FT threading/monitoring also pass.

## Fixed-cohort result

- All 24 workloads completed all paired runs; no timeout/failure. Main was
  calibrated once per workload and all three executables used those loop counts.
  Final identity checks passed. The equal-weight geometric-mean runtime ratio
  is 1.0076 versus main and 0.9984 versus the starting implementation: broadly
  neutral, not a 20% improvement. Go is 0.8375 versus the starting implementation
  (16.25% shorter), but still 1.1240 versus main. Richards is 1.0286 versus main.
- Retain all primary results, including Chaos's 0.984--1.135 and NetworkX's
  0.991--1.288 paired-ratio spread. Predeclare three additional rotated process
  blocks for Chaos, NetworkX, Raytrace and regex_dna to characterize process
  variability and the material non-Go differences; do not replace the primary
  aggregate with favorable samples. NetworkX retains its 15-second cap.

## Final attribution and supplementary measurements

- Three additional process blocks completed without failures/timeouts. NetworkX
  showed the ~399 ms slow mode in the starting implementation as well as in the
  primary candidate run; most processes were ~307--314 ms. Combining all five
  processes per binary gives candidate/before 0.9984 for NetworkX. Do not call
  the primary 12.7% difference a stable patch regression. Chaos remains variable;
  Raytrace's initial regression did not reproduce in the additional blocks.
  regex_dna's ~4.7% improvement reproduces, but its cause is not established.
- A final trace-only control with the new global miss cache runs Go at
  67.3--68.1 ms, versus final method 70.8--71.3 ms and main 63.4--63.7 ms.
  The residual cost is shared-runtime changes plus about 5% additional runtime
  with the method frontend; it is not exclusively method CFG/inlining cost.
- Primary 24-workload data and aggregate remain unchanged. Supplementary data,
  dynamic counts, control source snapshots, and build identities are retained.
  See method_jit_performance.md for current conclusions and remaining limits.

## Completion of requested steps 1--4

- Final native perf: global-dependency invalidation is 0.57% of samples;
  invalidate_dependencies falls below the 0.2% report threshold, versus
  3.64% and 10.78% respectively before. This corroborates the cache attribution.
- Final constant-specialization assertions pass independently on all four
  configurations. Optimizer/generator/JIT-tool checks pass another 110 tests;
  git diff --check passes. Diagnostic controls were restored to the actual
  implementation at build-method-jit/python. No PGO/LTO, GitHub post, push,
  PR modification, or commit was performed in this follow-up.
- Steps 1--4 are complete within the bounded inline/single-predecessor subset
  documented above. The broader 20% goal remains unmet. Next: classify the
  remaining dynamic unsupported call exits, expand the frequent call protocols,
  and measure multi-predecessor stack-cache propagation separately.

## Commit checkpoint

At the user's request, package the implementation, regression tests, reports,
and benchmark evidence in a local commit. Previously completed correctness
checks and the 24-workload results were verified; git diff --check passes.
Build directories and unrelated earlier experiments remain local.

# All standalone benchmarks: 10% runtime reduction goal

The user now requests every benchmark in benchmarks/ to beat main by 10%.
The current workload set is bpe_tokeniser, btree, deltablue, go, hexiom, raytrace,
spectral_norm, and sqlalchemy_declarative (added at the user’s request below).
Treat the target as runtime candidate/main <= 0.90 for each
item; a suite geometric mean cannot substitute for a failing item. Preserve
all supplied workloads, checksums and the user's existing file changes.

Use the d95f295 main control with the documented prerequisite stencil fix,
LLVM 21, GCC and frame pointers, no PGO/LTO, CPU 2. Initial screens use three
alternating process blocks, hash seeds 0/1/2 shared by paired processes, three
warmups and seven values; retain all trials and verify hashes/checksums.
Repeat final verification with more independent processes and report process
uncertainty, not just minimum timings. No builds run alongside timing trials.
New artifacts live in jit-artifacts/all-benchmarks-10pct-20260916.

The initial seven-workload phase measured dynamic unsupported calls. Prior evidence
shows a high method-to-Tier-1 exit rate, so expand common call protocols and
optimize actual hot paths instead of changing benchmark work.

Initial fixed-suite result (three processes per runtime/workload, all checksums
passed): bpe_tokeniser 0.994, btree 1.053, deltablue 0.956, go 1.135,
hexiom 0.989, raytrace 0.987, spectral_norm 1.008 (candidate/main).
No workload meets 0.90. Raw process means and binary/workload hashes are in
start-state.json.

Next implementation extends bounded inlining to specialized positional calls
with defaults and stored bound methods, using existing argument binding and
function-version guards. Callee size/control-flow limits remain in force.
A separate diagnostic runtime records unsupported method exits by code/offset;
its timings are never performance evidence.

Call expansion passed all 341 optimizer tests on both GIL debug and native
JIT builds (four skips each). The first calls screen accidentally overlapped
with the diagnostic profiler: keep calls-state.json but exclude it from
performance claims. calls-clean-state.json reruns the six shorter workloads
without competing work. No source/build mutation occurred during either run.

Dynamic unsupported exits concentrate in Go's recursive Square.find and
B-tree's search/get_position call chain. BPE, Hexiom and Spectral Norm have
no such exits in the observed steady phase; this does not imply full method
coverage. Next port the generic bounded-integer expression lowering to CFG
basic blocks, proving all intermediates fit before replacing them with tagged
native values. Stop at every block boundary, frame change, call or callback;
keep original bytecode as the guard failure path.

Bounded integer lowering now passes all 343 optimizer tests in GIL debug and
native JIT builds, including native-entry guards, huge integers, float inputs,
zero division and large integer-to-double conversion. Added explicit Makefile
header dependencies and non-escaping helper annotations in the generator.
The first method-only screen shows no Spectral Norm gain: its hot loop's trace
already inlines the scalar callee before a root method becomes hot. Apply the
same expression pass to trace fallback as well; retain this negative result.

The next call change uses the existing JIT entry ABI to call another method
executor and resume the caller directly on a normal return. Non-return exits,
exceptions, pending instrumentation and C-stack pressure fall back to Tier 1.
Keep an explicit strong caller-executor reference across nested execution, so
invalidation/GC cannot free a live native return address. This requires tests
for recursion, exceptions, callbacks and invalidation before performance claims.

The full method-only integer screen completed, all paired checksums matched:
BPE 0.993, B-tree 1.138, DeltaBlue 0.948, Go 1.127, Hexiom 1.006,
Raytrace 1.017, Spectral Norm 1.004. No target met. The expanded call handling
regresses B-tree against the initial candidate; do not treat passing functional
tests as performance acceptance. Reassess after adding direct method returns.

Direct method calls plus trace integer lowering passed 347 optimizer tests
on GIL debug and native builds (four skips), including real nested executor
invalidation/GC, recursion limits, callee exceptions and trace arithmetic.
Six-workload screen: B-tree 1.178, DeltaBlue 0.954, Go 1.129, Hexiom 1.007,
Raytrace 1.026, Spectral Norm 0.523. This is the first target-sized improvement,
but only for Spectral Norm; the suite goal is still unmet.

Bounded inlining now permits short loops and one level of recursive expansion;
further calls use method entry, bounding code growth. Backedges retain periodic
checks. The 347 tests pass in both builds. Screen: B-tree 1.128, DeltaBlue 0.970,
Go 1.113, Hexiom 1.004, Raytrace 1.054, Spectral Norm 0.519. Retain these negative
results: direct calls/inlining are not sufficient to beat main generally.

Added generic len-consumer fusion and immutable tuple-pair equality, shared by
method basic blocks and trace fallback. Guard exact builtin types; preserve
custom __len__/__eq__ effects and tuple identity semantics for NaNs. The first
debug run passes the new behavior tests; an existing test's expected _CALL_LEN
is now fused and is being updated to accept the optimized representation.

Builtin fusion passed 350 optimizer tests in debug/native GIL builds (four
skips). Full-suite screen: BPE 0.923, B-tree 1.142, DeltaBlue 0.957, Go 1.112,
Hexiom 0.968, Raytrace 1.011, Spectral Norm 0.518. Only Spectral Norm meets the
individual target; BPE is close but still fails. All checksums and identities
were verified; detailed process pairs are in builtins-state.json.

Next preserve argument ownership/type facts through the fused uops so the
existing trace optimizer can eliminate redundant cleanup/guards. Native tagged
values stay opaque until boxing. The method value analysis additionally tracks
unique float temporaries within a basic block and selects existing inplace
arithmetic only for values without aliases. Clear these facts at merges,
stores, copies and escaping operations; borrowed native attribute reads can
preserve them. Added tests for arithmetic chains, attribute products and alias
rejection. A tuple-return test had no root executor, so use a COPY/alias case
that actually compiles and checks the inplace instruction is absent.

Float reuse and fused-op symbolic facts passed 353 optimizer tests on native
GIL JIT; debug's only test issue (an uncompiled tuple-return alias test) was
replaced with an actually compiled COPY alias regression and passed separately.
Full screen: BPE 0.924, B-tree 1.135, DeltaBlue 0.962, Go 1.121, Hexiom 0.969,
Raytrace 1.040, Spectral Norm 0.446. Retain the Raytrace regression; float reuse
alone is not a broad performance win in this implementation.

Track object origins and proven layout versions within each basic block.
Repeated borrowed attribute loads from the same local now share their type
version check; calls/escapes and block merges clear these facts. Added callback
class-change coverage. All 354 tests pass in both GIL builds. Six-workload
screen: B-tree 1.126, DeltaBlue 0.908, Go 1.114, Hexiom 0.967, Raytrace 1.024,
Spectral Norm 0.447. DeltaBlue is closer but still not a passing result.

Next fold immortal global/builtin bindings in methods with named dependency
watchers, explicit globals/builtins identity guards, and fact propagation.
Existing 354 debug tests and two new mapping/rebinding tests pass. Native build
and full regression checks are in progress. Avoid folding mutable numeric
counter bindings into repeated method invalidations in this first extension.

The free-threaded debug build passes all 356 optimizer tests (three skips).
GIL debug numeric/control regressions pass 806 tests (two skips). Native GIL's
full optimizer suite reproducibly loses the iterator test's executor, although
that test passes in isolation. Disabling automatic GC for a diagnostic full
suite gives 356 passing tests (four skips); investigate collection/invalidation
during warmup before changing the assertion. The global-constant performance
screen is running with the frozen binary, independently of builds and tests.

Global-constant screen completed with matching checksums: B-tree 1.123,
DeltaBlue 0.969, Go 1.110, Hexiom 0.966, Raytrace 1.026, Spectral Norm 0.448.
In particular DeltaBlue loses the previous layout-only improvement; investigate
code growth and guard overhead rather than accepting this as a universal win.
The iterator assertion now disables automatic GC within that test only; separate
callback/GC invalidation tests remain enabled. Next fuse adjacent list element
comparison after trace value analysis, retaining exact-type and both-index
guards before eliding temporary references. Added negative-index, bounds,
NaN-identity and user-defined subscription/comparison regression coverage.

Adjacent-list comparison passes 357 optimizer tests on GIL debug and native
JIT (four skips), including the GC-stabilized iterator assertion. Collection
regressions (list, tuple, dict, iter, itertools) pass 457 debug tests, five skips.
Free-threaded native validation is building. Before further call changes,
refresh the diagnostic build to the current source and count method entry
fallbacks as well as explicit deoptimization; the earlier profile predates
direct method calls and cannot establish current bottlenecks.

Refreshed diagnostic results: B-tree's earlier get_position/search call exits
are gone. Remaining per-workload fallbacks include Square.move entry (21,393),
BinaryConstraint.choose_method entry (9,288 per 32 DeltaBlue runs), and Raytrace
constructor calls (Point.__sub__ 109,005; Vector.__add__ 20,000). Diagnostic
build timings are not performance evidence. Free-threaded native passes all
357 optimizer tests (three skips).

Next changes under test: derive exact enumerate/zip iterator types from guarded
builtin constructor bindings, and emit direct method iteration; analyze the
logical completed stack effects of frame-pushing specialized bytecodes instead
of their immediate evaluator transition; support keyword Python calls using
the existing argument binder and function/method version guards. Route class
allocation calls through existing generic vectorcall to retain the method
continuation until init-cleanup trampolines have a native representation.
Added iterator exhaustion/error, keyword-binding/rebinding, and constructor
mutation/GC/invalid-init-result tests. No performance acceptance yet.

Adjacent-list screen: BPE 0.912, DeltaBlue 0.959, Go 1.103, Hexiom 0.965,
Raytrace 1.022, Spectral Norm 0.449. B-tree aggregates to 1.078 because main's
first process was slow (pair ratios 0.978, 1.130, 1.132); retain it and do not
interpret that aggregate as a new improvement. BPE still misses the 0.90 target.

Coverage changes pass 362 GIL debug/native optimizer tests after correcting
three tests to use default arguments: closure code begins COPY_FREE_VARS,
which the current entry frontend does not compile. Six-workload screen:
B-tree 1.111, DeltaBlue 0.962, Go 1.086, Hexiom 0.966, Raytrace 1.107,
Spectral Norm 0.446. Reject the generic constructor-vectorcall experiment:
it regresses Raytrace substantially despite avoiding exits. Remove that route
and its representation-specific test; native init-trampoline handling needs
a separate design.

Found a concrete warmup bug while inspecting DeltaBlue: the tracer sets RESUME's
counter to zero, then _JIT decrements it while tracing blocks compilation,
wrapping it to 8191. A small caller/leaf loop reproduces counter=65528 after
4002 iterations. Preserve a ready counter until tracing permits compilation.
Added a test asserting zero after tracing and successful compilation on the
next direct leaf call. This also exists in main's _JIT logic; benchmark control
remains unchanged. Validation and timing of this fix are next.

Ready-counter fix passes 362 optimizer tests in GIL native, free-threaded
debug and free-threaded native (four/three/three skips). GIL debug optimizer,
monitoring, settrace, generators, coroutines, float and long total 1,168 passes
(six skips). Super-call retracing can now start inside a callee: the test keeps
its initial two-load folding assertions and verifies superclass mutation also
invalidates the replacement trace. Full-suite frozen-binary timing is running.

Next fuse len(list[index]) comparisons after trace analysis. Check exact list,
compact index, builtin len and callback-free inner length; retain a surviving
list owner before eliding the selected element's temporary reference. Preserve
normal fallback for custom length/subscription, wrong types and index errors.

Ready-counter full screen: BPE 0.914, B-tree 1.105, DeltaBlue 0.959,
Go 1.085, Hexiom 0.972, Raytrace 1.029, Spectral Norm 0.445. The counter fix
is a verified bug fix, not a broad performance success. Only Spectral Norm
meets the target so far.

Method entry now marks non-argument locals as uninitialized. Replacing such a
local, or an exact scalar without a finalizer, need not discard layout facts.
Preserve agreed layout versions at CFG joins, while still dropping ownership
and local-origin assumptions there. Added a branch/scalar-store guard-count
test and a finalizer that changes the receiver's class to ensure potentially
escaping stores still discard those facts. Build and regression checks pending.

Length-subscription fusion and scalar-store/join facts pass all 365 GIL debug
and native optimizer tests (four skips). Their full-suite screen is running.
Next remove the extra ordinary-C wrapper and entry shim from nested native
method calls. Keep the shared entry checks, caller-executor lifetime protection
and exception/frame restoration in one inline helper; the stencil invokes the
callee with preserve_none directly. Tier 2 interpretation keeps its existing
entry function. Include the new helper and ceval_macros.h in stencil dependency
hashes and Unix/Windows build rules. Validate native stack pressure, callbacks,
invalidation and free-threaded transitions before accepting any speedup.

Local-facts screen: BPE 0.909, B-tree 1.110, DeltaBlue 0.955, Go 1.078,
Hexiom 0.945, Raytrace 1.038, Spectral Norm 0.444. Hexiom improves modestly;
BPE remains just outside the target and the three regressing workloads remain
unacceptable. All paired checksums match. Add 20,000-deep recursion with a
100,000 Python recursion limit to exercise C-stack fallback for the native-call
change, separately from the existing Python-recursion-limit assertion.

Direct native entry passes 367 GIL debug/native tests including tool digest
checks and 20,000-deep recursion. Screen: B-tree 1.072, DeltaBlue 0.965,
Go 1.070, Hexiom 0.944, Raytrace 1.041, Spectral Norm 0.443. It reduces part of
B-tree's regression but does not meet the goal. Next give method CFG blocks
explicit stack-cache entry conventions (up to two cached values), instead of
forcing every conditional/unconditional edge through an empty cache. Iterator
exhaustion edges initially retain the empty convention. Validate joins and
inlined returns carefully before performance acceptance.

CFG cache implementation now represents labels explicitly during compilation,
with up to two cached values on incoming edges. Taken edges skip the conversion
needed only for physical fallthrough. Inlined returns join an empty-cache label.
Iterator uops now declare their two preserved operands and use generated
branch/error handling, allowing those edges to use the same convention too.
No labels remain in executable uops. Added conditional-expression stack-prefix
and nested list-loop break/continue/error tests. Debug build/validation pending.

CFG cache conventions pass all 367 GIL debug/native optimizer tests (four
skips), including the new join/nested-loop cases and deep recursion. Stencil
inspection confirms the native method-call wrapper symbols are absent (the
shared entry helper and direct preserve_none call are inlined). A six-workload
cache screen is running before wider free-threaded and monitoring regressions.

CFG cache screen: B-tree 1.083, DeltaBlue 0.960, Go 1.048, Hexiom 0.961,
Raytrace 1.009, Spectral Norm 0.448. These are three-process screening results,
not confidence bounds; only Spectral Norm meets the target. Next preserve
short-circuit equality in pair fusion, then accelerate callback-free runs of
enumerate(list) loops that unpack a tuple and compare one integer field.
The scan must preserve iterator/local state, stop before unsupported values,
and retain periodic checks by bounding each batch. No workload changes.

Implemented the enumerate scan as a C helper in enumobject.c (the private
enumerator layout stays private). A method CFG matcher recognizes unpack,
tuple-field subscription, compact-int comparison and a fallthrough continue
edge. It batches at most 64 iterations with cached small integer indices,
retains the original next/unpack for all fallback cases, and checks that old
local references are still owned by the list and cached enumeration tuple.
Free-threaded builds currently use a no-op helper and retain normal iteration.
GIL debug optimizer/tool checks pass 371 tests, with four skips. Extra cases
cover arbitrary comparison callbacks, list mutation, nonzero/huge enumeration
starts, exhaustion and overwritten-local finalizers. Native build exposed a
missing declaration in jit.c's stencil symbol table; added the internal header
there and am rebuilding before timing. The initial failed log is retained.

Enum + short-circuit comparison screen (all checksum/hash checks passed):
BPE 0.9042, B-tree 0.8841, DeltaBlue 0.9629, Go 1.0632, Hexiom 0.9446,
Raytrace 1.0372, Spectral Norm 0.4441. B-tree's three pairs are
0.8941/0.8782/0.8801, so it now passes the screening threshold alongside
Spectral Norm. This is not yet the final repeated confidence check. Native
optimizer/tool validation passed 372 tests with four skips before timing.

Next lower two/three float attribute products plus their ordered additions
within a method basic block. Preserve the original frame, type/layout checks,
all field type guards before arithmetic, binary64 rounding boundaries, and
the final addition's exception location. This removes intermediate float
allocations without changing benchmark source. Added slots/managed-dict,
2/3-term, FMA-sensitive, order-sensitive, NaN, signed-zero, subclass callback,
missing attribute and replaced-dictionary regression cases. Build in progress.

Float attribute fusion passes 373 native GIL, free-threaded debug and
free-threaded native optimizer/tool tests (four/three/three skips). An existing
test specifically for in-place float ownership initially expected the old
addition uop; changed its expression to keep individual attribute reads outside
sum-of-products fusion, retaining its ownership and guard-count assertions.
Dedicated fusion tests assert the new uop and cover both two and three terms.
The unchanged Raytrace workload uses the fusion, but its third product was
compiled as a mixed float/int BINARY_OP_EXTEND and remains outside the region.
Next examine primitive mixed arithmetic and eliminate borrowed-owner cleanup
spills in method attribute loads. The current frozen binary is being measured.

Prepared a broader primitive float path: accept exact floats and compact ints,
but require at least one float in each product, so every product/addition has
the same float result type and rounding as Python. Integer-only products,
large ints, subclasses and descriptors keep the original path. The matcher
can recognize mixed-arithmetic extension uops or generic numeric uops, guarded
by those new primitive checks. Also replace the attribute expansion's receiver
cleanup with POP_TOP_NOP only when the bytecode-entry state proves it borrowed;
temporary owned receivers retain their destructor path. New tests explicitly
exercise mixed warmup types, integer-only fallback, huge-int overflow and
temporary receiver finalizers. These follow-up changes await build/validation.

Float-attribute/bytes-prefix screen: BPE 0.9022, B-tree 0.8736,
DeltaBlue 0.9687, Go 1.0519, Hexiom 0.9411, Raytrace 1.0323,
Spectral Norm 0.4434. Two-float-product fusion alone did not materially improve
Raytrace; do not describe it as a workload speedup. All checksums match. The
mixed-arithmetic and borrowed-cleanup follow-up is now building.

Mixed arithmetic and borrowed receiver cleanup pass 375 GIL debug/native
optimizer/tool tests (four skips). The owned-receiver regression uses a Python
factory and asserts an actual method executor retains POP_TOP, so the finalizer
test cannot pass solely because a class-construction call prevented compilation.
Free-threaded validation is rebuilding; performance measurement waits for all
builds/tests to finish.

The mixed/borrowed-cleanup change also passes 375 free-threaded debug/native
tests (three skips each); a full seven-workload screen is running. Inspection
shows Vector.dot now contains the three-product fusion (53 total uops versus
97 at the previous stage), and Square.move shrinks from 880 to 814 uops.
These are code-coverage observations, not performance measurements.

While that frozen binary is measured, bring method call checks in line with
existing trace analysis: fold the PEP 523 check when executor invalidation
guards the absent hook, use the guarded callee's fixed frame size, and omit
the exact-argument check only for a proven null-self or bound-method convention.
Retain the function-version and recursion checks. Added code-replacement,
argument/default changes and larger-frame regression cases; validation pending.

Mixed/borrowed full screen: BPE 0.8914, B-tree 0.8712, DeltaBlue 0.9508,
Go 1.0215, Hexiom 0.9418, Raytrace 1.0041, Spectral Norm 0.4478. All paired
checksums match. BPE joins B-tree and Spectral Norm below 0.90 in this screen;
four workloads remain above target, and final confidence checks remain pending.

Alongside the call-check simplification, fuse compact-int comparisons whose
inputs are a guarded slot/instance attribute and another local or attribute.
Use each input's own layout version (including different receiver classes),
check managed-values validity, and retain normal fallback for large ints,
missing fields, changed layouts and arbitrary comparison results. The region
does not allocate or release the integers held by the original owners. Added
slot-vs-dict, reversed/local operands, large ints, missing fields, replaced
dictionaries and custom-comparator tests. This next candidate is building.

Call-check simplification and integer-attribute comparisons pass 377 GIL
debug/native optimizer/tool tests (four skips). A six-workload screen is now
running; the larger BPE workload was below target in the previous full screen
and will be rerun with the next full comparison. No result is final yet.

Integer-attribute/call-check screen: B-tree 0.8630, DeltaBlue 0.9436,
Go 0.9979, Hexiom 0.9435, Raytrace 1.0025, Spectral Norm 0.4420.
Go has recovered approximate parity but still misses the target.

Recorded native cycles separately from timing, on CPU 2 with period 1,000,003
and frozen python-goal-attrint (attrint-{go,ray,delta,hex}-perf.*). No lost
samples. Hexiom's list_contains, PyObject_RichCompareBool and long_richcompare
account for 3.30% + 5.09% + 5.91% self samples. Add a JIT-only exact-list/tuple
compact-int membership scan; encountering any unsupported item restarts the
ordinary search, whose skipped prefix was callback-free. Keep free-threaded
containment on the ordinary path. Tests cover mutation/comparison callbacks,
exceptions, list subclasses, bools, floats and large ints. Extend borrowed
receiver cleanup to non-escaping list/tuple subscription, while retaining
owned temporary-container destruction and enum-loop matching.

The same profiles show substantial frame clear/pop cost in Go, Raytrace and
DeltaBlue (roughly 7–9% across the two primary functions), plus frame binding
and stack management. Investigate a guarded fast return/clear path next, with
normal fallback for materialized frames, generators, profiling and stack-chunk
boundaries. This is a diagnosis, not an implemented optimization yet.

Containment/subscript cleanup passes 379 GIL debug/native optimizer/tool tests
(four skips). Screen: B-tree 0.8734, DeltaBlue 0.9570, Go 1.0118,
Hexiom 0.8398, Raytrace 1.0274, Spectral Norm 0.4451. Hexiom now clears the
screening threshold; BPE passed in the previous full run. The small shifts in
other workloads do not establish improvements and remain part of the record.

Implemented a JIT-only inline return cleanup for thread-owned frames without
a frame object or locals dictionary, away from a stack-chunk boundary. It
preserves unlink-before-clear, reverse local cleanup, function/code release
order, profile-frame bookkeeping and reservation of stack storage during
finalizer reentry. All other cases, including free-threaded builds, use the
original helper. Added retained-frame and finalizer/reentry/GC regressions;
broader monitoring, settrace, generator and coroutine validation is running.

Fast return cleanup passes 1,086 tests in GIL debug/native and free-threaded
debug (five/five/four skips), plus 381 free-threaded native optimizer/tool tests
(three skips). Full common-binary screen: BPE 0.9021, B-tree 0.8499,
DeltaBlue 0.9111, Go 1.0054, Hexiom 0.8187, Raytrace 1.0061,
Spectral Norm 0.3925. BPE is again just outside target, so this binary has only
three workloads below 0.90. No previous-stage pass substitutes for final
common-binary validation.

Next remove frames for exact positional leaf calls that only return one
argument or an immortal constant. Retain call/function-version/recursion and
periodic checks, close arguments in reverse order and callable last, and own
returned argument references. Reject closures, extra locals, generators and
monitored callees; add code dependencies so enabling local monitoring on the
callee invalidates its caller. Added code replacement, bound-self/argument,
finalizer/GC and local-monitoring regressions. Build and focused validation
are in progress; this optimization is initially GIL-only.

Leaf-call debug validation passes 1,089 tests (five skips). An initial focused
failure exposed an overly restrictive eligibility check: a code object's
monitoring allocation can remain after monitoring is disabled. Check current
global/local/active event masks instead of allocation presence. The initial
failure and retry logs are retained. Native validation is building/running.
Next investigate keeping constructor calls and their initialization cleanup
trampoline inside method JIT execution, preserving argument binding, invalid
__init__ return errors, recursion accounting and ordinary deoptimization.

Native leaf-call validation also passes 1,089 tests (five skips); full matched
suite screening is running with frozen python-goal-leaf. During measurement,
implemented constructor method-entry support without running builds: accept
CALL_ALLOC_AND_ENTER_INIT's existing type guard/allocation/argument binding,
enter a compiled __init__, then complete the private initialization trampoline
when it returns None. Other exits return to the interpreter with their actual
frame/IP intact. Keep both frames and recursion accounting; do not substitute
an ordinary vectorcall. Tests cover __init__/__new__ replacement, invalid
return, raised exceptions, materialized initialization frames and changed
argument requirements. Validation waits for the timing run to finish.

Leaf-call common-binary screen: bpe_tokeniser 0.9029, btree 0.8393, deltablue 0.9113, go 1.0091, hexiom 0.8307, raytrace 0.9840, spectral_norm 0.3902. Checksums and identities match; screening only. Constructor debug build and focused tests are now running.

Constructor's first debug test caught a stack-pointer synchronization assertion
in the new private-trampoline path. Its manually popped values must explicitly
update the frame's saved stack pointer before the generator's SAVE_STACK
(which can otherwise emit only an equality assertion). Correcting the
synchronization and rerunning focused tests; the failed log is retained.

Focused constructor tests pass after synchronizing the trampoline's stack.
Also synchronize the caller's pushed result, preserve DTrace/low-level trace
return bookkeeping, and disable frameless leaves in DTrace builds. Added
nested constructor calls and recursion-limit recovery. Broader GIL debug
validation is running before native timing. A remaining candidate for
DeltaBlue is classmethod lookup/binding, but it needs normal-metaclass and
descriptor-precedence guards plus compatible call-stack normalization; no
such optimization is implemented yet.

Constructor support passes 1,092 GIL debug/native tests (five skips).
Free-threaded validation exposed a pre-existing method-inlining dependency
omission: enabling local monitoring on an inlined callee did not invalidate
its caller, because the dependency covered the function but not its code.
The new leaf-monitoring regression catches this even with frameless calls
disabled. Add the callee code to ordinary CFG-inlining dependencies too, then
rerun both GIL modes. The FT failure is retained. A six-workload constructor
screen uses the frozen pre-fix binary; this dependency-only correction must
still be present in final correctness/performance validation.

Constructor screen: btree 0.8588, deltablue 0.9011, go 1.0175, hexiom 0.8283, raytrace 1.0024, spectral_norm 0.3905. DeltaBlue is close to target, but constructor method entry alone does not improve Raytrace, and Go still regresses. This is not a passing candidate.

Next extend frameless leaves to guarded slot/managed-attribute getters, retaining the owning reference before argument cleanup and ordinary fallback for changed layout, missing attributes and descriptors. Add getter correctness/fallback/frame-observation tests. Also give the existing initialization-frame uop a JIT-only exact positional argument copy path; general binding remains for defaults, keyword-only and variadic signatures. The opcode generator rejected a preprocessor-split else in the first draft; rewrite as a compile-time false eligibility flag for Tier 1. Regeneration/debug validation is running.

Seven getter/constructor focused tests pass. Before broad validation, restrict
exact constructor binding to GIL builds and recheck available frame space
after object allocation: a GC callback can replace __init__.__code__ with a
larger frame between the original allocation guard and frame creation. Add
default, keyword-only, *args and **kwargs binding fallbacks. Broad tests now
also include the ordinary-inline local-monitoring dependency fix.

GIL debug broad validation passes 1,094 tests (five skips). GIL native and
both free-threaded builds are rebuilding/testing. Prepared a diagnostic-only
perf symbol map writer that snapshots live benchmark executor code ranges
and matches their emitted bytes to functions, without installing an eval-frame
hook (which disables JIT). Keep timing and profiling separate; temporarily
disable GC only while taking the address snapshot and retain executor objects
to avoid address reuse. Native profiles will identify the remaining Go/Raytrace
costs after the next measured candidate, rather than assuming earlier profiles
still apply.

Getter/exact-init-binding and the code dependency correction pass all 1,094
tests in GIL debug/native (five skips) and free-threaded debug/native (four
skips). The previously failing local-monitoring test now passes in both FT
builds. Frozen python-goal-getter is entering a six-workload matched screen;
profiling will follow it, with no builds running during either measurement.

Getter/exact-init-binding screen: btree 0.8796, deltablue 0.8974, go 1.0145, hexiom 0.8266, raytrace 0.9904, spectral_norm 0.3906. Three paired processes, unchanged workloads/checksums. Native profiling follows.

Named native samples identify Go's largest JIT bodies: Board.useful ~25.5%,
Square.move ~11.5%, Square.find ~10.8%, Square.remove ~7.5%. General argument
binding still costs ~1.6% and long_bitwise ~1.6% in C. Retook profiles with a
fixed initial symbol map (getter-*-stable.*), retaining mapped executors;
later mappings could otherwise misattribute earlier samples at recycled
addresses. These profiles are diagnosis, not benchmark timing evidence.

For Raytrace, proceed beyond merely entering __init__ natively: inline small
initializers guarded by the constructor's existing type version and the
initializer function/code dependencies, then complete the private shim after
the inlined return. Retain the outlined native/interpreter path for other
initializers. This is initially GIL-only for inlining; source and regression
assertions are updated, with validation to follow profiling.

Initializer inlining passes four focused constructor tests. Broad validation
is running. Moved the GIL-only exact-binding eligibility check into a helper
parsed before the native template undefines Py_GIL_DISABLED; a conditional
inside bytecodes.c alone would accidentally enable it in FT native stencils.
The helper also documents/rechecks frame capacity after allocation callbacks.
Stable Raytrace native samples show Point.__sub__ ~6.75% and Vector.__init__
~2.03%, alongside trace code in _lightIsVisible ~12.27% and rayColour ~5.45%.
Go's generated compare regions also spend instructions unpacking descriptors;
link-time field immediates are a possible later improvement, not implemented.

Initializer inlining passes 1,094 GIL debug/native broad tests (five skips)
and 389 free-threaded debug/native optimizer/tool tests (three skips). A
six-workload screen now uses frozen python-goal-initinline. No final all-seven
validation has passed; BPE, Go and Raytrace were still above target in the
latest applicable screens, and DeltaBlue's latest margin is small.

Initializer-inlining screen: btree 0.8665, deltablue 0.8971, go 1.0070, hexiom 0.8367, raytrace 0.9773, spectral_norm 0.3936. No unchanged seven-workload candidate passes yet.

Added a GIL-only no-allocation frame-binding helper for ordinary positional
calls with optional trailing defaults. It checks signature shape, missing
arguments and stack capacity before stealing inputs; all other calls keep
ordinary binding. Defaults receive owned references in the new frame. Added
default mutation/removal and retained-frame lifetime tests, and marked this
helper and exact-init eligibility non-escaping in the opcode generator.
GIL debug passes 1,095 broad tests (five skips); native validation is building.

Positional/default binding passes 1,095 native broad tests (five skips). Screen: btree 0.8686, deltablue 0.9059, go 1.0020, hexiom 0.8280, raytrace 0.9702, spectral_norm 0.3892. DeltaBlue again narrowly misses; retain all results rather than taking each workload's best stage.

Prototype a general simple-initializer fast path: one to three positional arguments copied once each, in any order, into distinct specialized slot or managed fields, followed by return None. Keep normal allocation/type/recursion guards. After allocation, require executor validity, the recorded type version, valid inline storage with no materialized dict, and initially empty destination fields. On any failed guard take an internal CFG edge to the original frame creation/initializer path, preserving the already allocated instance. Success owns each stored argument, records dict insertion order, and returns the instance without initialization frames. Exclude monitoring, DTrace, FT, unsupported signatures and bodies. Added slot/dict field order and local monitoring tests; regeneration/debug tests are running.

Simple initializer validation passes 1,098 tests in GIL debug/native and FT
debug/native (five skips each). Retained an initial generator rejection of
transferring a middle input while the argument array was live; use an owned
result reference through normal argument cleanup instead. Fixed the RESUME
cache-size lookup after an initial compile error. Added an entry-event guard:
if allocation schedules GC or any other event, create the real initializer
frame before handling it. A targeted regression observes that frame from a
GC callback, prepopulates its field, and verifies the original setter releases
the old object with __init__ still visible. Full seven-workload screening is
now running with frozen python-goal-simpleinit, without concurrent builds.

Simple-initializer full common-binary screen: bpe_tokeniser 0.9005, btree 0.8611, deltablue 0.9025, go 1.0088, hexiom 0.8317, raytrace 0.9506, spectral_norm 0.3919. All workload hashes and checksums match; this remains screening, not final verification.

Next fuse guarded compact-integer attribute += / -= small constants within a
single basic block. Require matching slot/managed load and store offsets,
exact compact old integers and an unchanged type version; preserve managed
dict fallback and arithmetic-error IP. The receiver stays alive in its local,
integer cleanup cannot call Python, and no native value escapes. Added slot/
managed, sign/boundary/big-int/bool/float, missing/replaced-dict and descriptor-
changing __iadd__ fallback tests. The first focused run reused a managed
instance whose preceding fallback test replaced its __dict__, so the next
case correctly used WITH_HINT rather than the new inline-value path. Give
each operation a fresh instance for its positive optimization assertion;
retain the explicit replaced-dict fallback checks. Broad debug tests run now.

Integer attribute updates pass 1,100 GIL debug/native broad tests (five
skips). Frozen attrupdate screen: btree 0.8820, deltablue 0.9076, go 0.9724,
hexiom 0.8260, raytrace 0.9624, spectral_norm 0.3924. This improves Go but
leaves the all-seven target unmet. Next annotate attribute loads in traced
loops too, and apply guarded float-product, integer-comparison and update
regions after trace analysis. Added exception-table loop tests to exercise
the tracing frontend and verify both positive fusion and exception/finally
fallback behavior. These trace extensions are not yet validated.

Trace-region positive tests initially failed because observations still
separated executable operations, small constants became borrowed constants,
and analyzed integer cleanup could become a no-op. Drop consumed observations
before post-analysis fusion, recognize borrowed constants/cleanup, and retain
integer arithmetic bytecode locations explicitly when _SET_IP is removed.
The focused loop test now passes, and GIL debug/native and FT debug each pass
1,101 broad tests (five skips); FT native validation is finishing.

Allocation-failure inspection found a correctness issue in our new attribute
regions: _ERROR_POP_N overwrote their explicitly selected arithmetic IP with
the fused prefix's target. A deterministic compact-int-to-two-digit allocation
failure reproduces a traceback at LOAD_FAST_BORROW instead of BINARY_OP.
This is a bug in the current optimization, not a main-branch bug. Fix it with
an explicit synchronized Tier-1 error return and add a subprocess regression
before final validation. Preserve this diagnostic in check-region-memory.py.

FT native also passed 1,101 tests. Frozen traceregions screening (before the
allocation-error fix): btree 0.8732, deltablue 0.8896, go 0.9969, hexiom
0.8251, raytrace 0.8920, spectral_norm 0.3909. Raytrace improves substantially;
Go remains near main, and these short screens do not establish a robust
all-seven pass. BPE still needs remeasurement on the common final binary.
The allocation-error fix now synchronizes the stack and returns directly to
Tier 1 after setting the arithmetic IP. Added a subprocess regression that
crosses an integer digit boundary to bypass the freelist, injects exactly one
allocation failure, and checks the traceback opcode and unchanged attribute.
Regeneration/focused debug validation is running.

Direct Tier-1 error returns were rejected by the opcode generator for cached
float results. Keep the normal error stub and give region errors an explicit
sentinel target that preserves their already selected IP. The integer and
float allocation-failure subprocess tests both pass with this approach.

Expanded attribute comparison descriptors from 3-bit to 8-bit local indices
and added compact integer constants on either side, including the common -1
opcode. Keep the float-product encoding's independent two-owner limit. Added
positive constant/later-local fusion assertions and big-int/bool/float fallback
checks. GIL debug passes 1,102 broad tests (five skips); native validation is
finishing, then run a common-binary all-seven screen. Earlier failed generator
and -1 matcher attempts remain in the artifact logs.

Attribute-constant full common-binary screen: bpe_tokeniser 0.9043, btree 0.8567, deltablue 0.9053, go 0.9903, hexiom 0.8029, raytrace 0.8985, spectral_norm 0.3897. All workloads complete with matching hashes/checksums; no all-seven pass. Native correctness also passed 1,102 tests (five skips). Next specialize the five attribute/local/constant comparison operand combinations at stencil generation, keeping the comparison mask and guards; avoid repeated runtime operand-kind dispatch. Regeneration/debug validation is running.

Comparison-kind specialization passes 1,102 GIL debug/native broad tests (five skips). Six-workload screen: btree 0.8543, deltablue 0.9092, go 0.9863, hexiom 0.8290, raytrace 0.8761, spectral_norm 0.3911. Still below the requested all-seven improvement. Next propagate the unchecked-escape bit over method CFG edges to remove join validity checks only when all incoming paths are already checked. Escapes, periodic checks, and frame changes reset this fact; saved IPs stay block-local. Added branch coverage and callback fallback tests. Debug validation is running.

CFG validity propagation passes 1,103 GIL debug/native tests (five skips). Added a callback that mutates a watched global on one incoming path, checking invalidation at the join. Six-workload screen: btree 0.8587, deltablue 0.9059, go 0.9762, hexiom 0.8118, raytrace 0.8776, spectral_norm 0.3929. Native Go profile has no lost samples: Board.useful 26.33%, Square.move 10.86%, Square.find 10.42%, Square.remove 7.26%; generated method code still dominates. Next try guarded non-escaping local stores for scalar assignments whose previous local is unknown; retain the original STORE_FAST if releasing that value could execute Python.

Guarded scalar local stores pass the focused finalizer test and 1,104 GIL
debug broad tests (five skips). For an assignment of a known scalar to an
unknown previous local, check that releasing the old reference cannot run
Python (null/borrowed, refcount greater than one, or exact primitive type).
Only then store/close without an escaping operation and preserve receiver
layout facts. Sole-owned user objects exit at the original STORE_FAST with
its input untouched, so finalizers see the replacement installed by ordinary
execution. Added that observation and shared-reference/primitive tests.
Native and both FT configurations are rebuilding/testing; the new guarded
store is disabled in FT, including native templates.

User added benchmarks/sqlalchemy_declarative.py to the measurement scope. The goal now covers all eight unchanged workloads, including its default 100 people/addresses and 100 loads. The storeguard runner correctly stopped before timing when it detected an eighth script; retain that log, extend the manifest, and prepare identical SQLAlchemy dependencies for main/candidate. Do not modify the user-provided benchmark. GIL native and FT debug/native storeguard validation all passed 1,104 tests (five skips GIL, six FT).

SQLAlchemy 1.4.19 and greenlet 3.2.4 were extracted from existing cp316 cached wheels into shared-deps; wheel hashes are in dependency-manifest.json. Both variants use identical package sources/native extension bytes and SQLite 3.45.1. Runner records/verifies a dependency tree hash and package/SQLite versions. Both smoke runs validate 100 people/100 addresses, person IDs sum 5050 and post codes sum 4950. Seven-workload storeguard8 screen (BPE omitted for this intermediate run): btree 0.8634, deltablue 0.9114, go 0.9810, hexiom 0.8253, raytrace 0.8883, spectral_norm 0.3921, sqlalchemy_declarative 0.9891. The new SQL workload also remains above target.

Next fuse attribute/subscript operations with their immediately following borrowed-input cleanup, after higher-level region matching. Inputs proven borrowed/immortal no longer travel through unused output stack-cache slots. Keep existing type/layout guards and owning result references; leave owned temporary receivers untouched. Added tuple/negative-index/bounds and slot/missing/descriptor-replacement checks alongside existing finalizer tests. Debug regeneration/validation is running.

Borrowed-cleanup debug validation initially had 12 failures: 11 stale opcode/
cleanup-count assertions after successful fusion, and one missed fusion because
method subscripting retained _POP_TOP_INT for a borrowed index. Recognize that
borrowed index too, while preserving owned temporary container cleanup. Update
only the affected positive assertions, retaining type/bounds guard assertions,
functional results, and finalizer checks. GIL debug now passes all 1,104 broad
unittest cases (four skips; unittest invokes one test skipped by regrtest).
Native build/validation is running. Prepared SQLAlchemy native profiling that
collects ORM function executors without installing an eval-frame hook.

Borrowed-cleanup native validation also passes 1,104 cases (four skips).
Full eight-workload common-binary screen: BPE 0.9036, btree 0.8559,
deltablue 0.9042, go 0.9764, hexiom 0.8282, raytrace 0.8888,
spectral_norm 0.3919, SQLAlchemy 0.9956. All workload/dependency/binary
identities and result checks pass. Four workloads remain above 0.90; these
three-process screens do not establish final confidence. Added SQLAlchemy
usage/dependency/measurement-boundary documentation to standalone_benchmarks.md.

Next prototype normal-path method compilation for functions with exception
tables, previously rejected wholesale. Keep real frames and return errors to
Tier 1 at the recorded bytecode; handlers are not extra CFG roots. Split CFG
blocks at protected-range starts/ends and handler entries, preventing region
fusion across protection boundaries. Parse the table with bounds/overflow
checks and reject malformed tables. Callee inlining still excludes exception
tables. Added guarded lookup/except/else/finally, outer exception-state, and
compiled arithmetic error routing tests. SQLAlchemy profiling runs first on
the frozen borrowed-cleanup executable; no build overlaps that profile.

Protected-region support passes 1,106 tests in all four builds (four skips
GIL, five FT). The initial new division test assumed a specialized division
uop, but this frontend emits the generic compiled _BINARY_OP; retain a
positive arithmetic-uop assertion including that valid form. Correct-handler
and outer exception-state checks pass. Seven-workload screen (BPE omitted):
btree 0.8615, deltablue 0.8932, go 0.9892, hexiom 0.8263, raytrace 0.8786,
spectral_norm 0.3909, SQLAlchemy 1.0106. In particular this change does not
improve SQLAlchemy in this screen; keep the unfavorable result.

Initial SQL profile includes symbol-discovery costs and misses dynamically
created closures. Correct the diagnostic by collecting functions after warmup
and using perf control/ack FIFOs to enable sampling only after symbol mapping.
Do not use the initial _Py_GetExecutor/_PyInstruction_GetLength costs as
workload bottlenecks. Controlled profile is running on frozen borrowfuse.

Next compile closure/cell function bodies from co_firsttraceable (their first
RESUME), after Tier 1 has created cells and bound free variables. Decode the
CFG from that entry offset and mark cell/free-variable locals live/unknown.
Nested direct method entry still falls back for prefix initialization; do not
skip or repeat MAKE_CELL/COPY_FREE_VARS. Ordinary small-callee inlining still
starts at offset zero and rejects such prefixes. Added shared-code closures
with distinct environments, nonlocal replacement/type change/empty-cell
fallback, and per-call cell identity tests. Not yet built or validated.

Closure entry support passes 1,108 tests in all four configurations (four
skips GIL, five FT). The existing recursive-closure resume test now exercises
method entry, so it checks the method prefix including its validity check.
Full common-binary screen: BPE 0.9012, btree 0.8528, deltablue 0.8958,
go 0.9748, hexiom 0.8281, raytrace 0.8993, spectral_norm 0.3915,
SQLAlchemy 0.9926. This still does not meet the all-eight target; Raytrace's
margin in particular is too narrow for a final claim.

Controlled SQL profiling succeeds with 42,687 samples and no losses; local
perf acknowledgments contain a NUL after the newline, so strip that protocol
terminator too. Retain both failed initial control logs. Symbols are captured
before measured work, and sampling excludes imports/warmup/symbol discovery.
The interpreter is 14.84%, type-cache lookup 4.35%, WeakInstanceDict.get JIT
code 3.58%, object allocation 2.51%; SQLite VM itself is 0.56%. This supports
working on runtime/JIT overhead rather than changing the SQL workload.

Inspection of saved Go machine code shows repeated movabs/shift/mask sequences
for packed attribute descriptors. Prototype patch-time extraction of bounded
operand fields (up to 32 bits), starting with integer attribute comparisons.
Native 64-bit templates emit field symbols; the stencil patcher extracts
local/offset/type-version/layout/mask fields once at code emission. Tier-2
interpreter and 32-bit templates retain ordinary extraction. Keep all runtime
object/type/layout/integer guards unchanged. Added patch expression/addend,
invalid field, and GOT relocation tests; debug regeneration/build/test runs now.

Patch-time comparison fields pass 1,111 GIL debug/native tests (four skips).
Seven-workload screen: btree 0.8626, deltablue 0.8913, go 0.9757,
hexiom 0.8213, raytrace 0.8726, spectral_norm 0.3944, SQLAlchemy 1.0071.
Generated stencils confirm field shifts/masks are done while patching, but
LLVM still emits 10-byte movabs loads for those small constants.

Add an ELF x86-64 assembly pass that narrows only bounded operand-field
symbols without addends to zero-extending movl loads, with R_X86_64_32
relocation support. Ordinary pointers, wider fields and symbols with addends
retain movabs; other targets retain their existing optimizer. Added assembly
rewrite/negative cases and relocation emission tests. Native validation
passes 1,113 cases (four skips); the frozen field32 screen is running. FT
validation of the field changes remains to be run before final acceptance.

Field-only 32-bit loads screen: btree 0.8598, deltablue 0.8913,
go 0.9648, hexiom 0.8213, raytrace 0.8883, spectral_norm 0.3924,
SQLAlchemy 1.0120. Next enable the existing small-constant template aliases
on ELF x86-64 and narrow oparg, target, and 16/32-bit operand aliases too.
Explicitly mask operand aliases to their declared C widths at patch time;
keep all pointer operands and addended assembly expressions unchanged.
Native correctness passes 1,114 cases (four skips). FT builds/tests include
the pending field-extraction changes and are running before further timing.
The SQL symbol collector now also visits nested code constants, since a
factory closure can be dead while its shared code/executor remains alive.

General small-constant support passes 1,114 tests in GIL native and FT
debug/native (four/five skips). Full eight-workload screen: BPE 0.9050,
btree 0.8510, deltablue 0.8911, go 0.9794, hexiom 0.8267, raytrace 0.9203,
spectral_norm 0.3931, SQLAlchemy 1.0054. Broadening the narrow loads has not
shown a performance benefit and Raytrace is worse in this screen. Diagnose
with fixed field32/smallconst binaries in a predeclared ABBA order for Go
and Raytrace, collecting cycles/instructions/branch misses. Those counters
include process startup, warmup, and validation and are diagnostic only.
No build overlaps these runs.

Prepared patch-time fields for attribute-return calls, simple initializer
layouts, compact-int attribute updates and float product regions. Retain all
existing guards and error IPs; constructors use three fixed descriptors so
constant replication can eliminate unused fields. Extended field-width test
cases. GIL debug passes 1,114 tests (four skips). Native build waits until the
counter diagnostic ends. This extension is not yet measured or accepted as a
performance improvement; the all-eight objective remains unmet.

ABBA counter diagnostics completed with matching checksums and binary hashes.
Raytrace's instruction totals are nearly equal within each neighboring pair;
branch misses vary substantially between processes (about 6.6M–15.8M).
Go's instruction totals are also nearly equal, and the long diagnostic favors
smallconst slightly, unlike the short screen. These results do not establish
a stable general small-constant gain or a uniquely identified cause. Revert
that broadening, retaining only field-symbol narrowing; keep ordinary alias
loads as negative rewrite tests. All counter data remains saved.

The extended field-region code passes 1,113 GIL native tests (four skips);
GIL debug had passed the same runtime coverage plus the now-removed alias
unit test. Frozen fieldregions screening is running. A non-timed SQL code
snapshot now includes nested code constants: _instance remains a trace at
byte offset 2 even after closure support. Its body has 935 code units and
383 instructions, with no exception table or raise opcodes. Investigate the
method frontend's bounded code budget rather than exception handling for
that function; do not add benchmark-specific compilation rules.

Confirmed with a debug-only generic rejection diagnostic: SQLAlchemy's
_instance hits 1,255 emitted uops and previously rejects the entire method.
Reserve a label and deoptimization stub for each remaining reachable CFG
block, and compile each block only within its share of the existing global
budget. Unsupported instructions or budget exhaustion resume at that exact
bytecode offset; compiled branches still target valid labels. No budget
increase or function-specific policy is used. A large generated function
test covers a compiled early return, partial-path side effects, large ints,
and an exception after returning to Tier 1.

GIL debug/native and free-threaded debug/native each pass 1,114 focused
optimizer/JIT-tool/monitoring/tracing/generator/coroutine tests (four skips
with GIL, five without). These builds also validate the pending region field
extraction changes. SQLAlchemy's debug smoke checksum matches and _instance
now has a 1,214-uop method executor with 18 deoptimization sites. Freeze the
native executable as python-goal-budget; run all eight unchanged workloads
against matched main with no concurrent builds/profiling. The earlier
fieldregions seven-workload screen was btree 0.8614, deltablue 0.9042,
go 0.9746, hexiom 0.8300, raytrace 0.8968, spectral_norm 0.3936,
SQLAlchemy 1.0045. The all-eight goal remains unmet.

While the frozen budget binary is measured, prepare a separate truth-test
cleanup change. Specialized int/list/str/always-true conversions preserve
the input's ownership facts until their cleanup; borrowed inputs use the
existing no-op pop. Owned temporary inputs still close normally, before
entering the branch body. Also correct the local uop model for generic
_TO_BOOL: it consumes its input itself and produces only one boolean.
Added type-change/error and temporary-finalizer ordering tests. Build and
test this change after timing ends; no performance claim yet.

The budget8 screen completed all eight with verified binary/dependency/workload
identities and matching checksums. Candidate/main: BPE 0.9022, btree 0.8889,
deltablue 0.8956, go 0.9973, hexiom 0.8235, raytrace 0.9129,
spectral_norm 0.3934, SQLAlchemy 1.0052. Process variation is material for
btree (0.8622–0.9359) and Go (0.9749–1.0368); these three-block results
are screening evidence, not a final confidence bound. Partial compilation
has not demonstrated a SQLAlchemy speedup. Profile the frozen budget SQL
workload with perf enabled only after warmup and symbol discovery, then
build/test the separate borrowed truth cleanup.

Borrowed truth cleanup passes all 1,115 native GIL and free-threaded
debug/native tests (four/five skips). GIL debug's first run had only a test
lookup error: the temporary-finalizer function is a closure, so its RESUME
is after COPY_FREE_VARS, not offset zero. Corrected the executor lookup and
the focused test passes. Runtime finalizer ordering and type mutation pass.

The controlled budget SQL perf run has 43,848 samples, no loss: interpreter
16.70%, type-cache lookup 4.36%, allocation 2.50%, SQLite VM 0.51%.
The _instance method itself accounts for only 0.02%. A separate structural
diagnostic (not a timing result, run alongside builds) confirms its executor
remains installed/valid, as do all 28 collected executors after 20 workloads.
No executor invalidation explanation is established. Its primary-key getter
call uses a function-version guard, which cannot accept a newly constructed
closure sharing the same code. Investigate this general call-site limitation.

Implement a GIL-only method-frontend selection of a code-version guard for
non-inlined CALL_PY_EXACT_ARGS/CALL_PY_GENERAL to closures. Guard both Python
function type and ordinary vectorcall; compare the nonzero, non-reused code
version. Keep the actual callable in the real frame so globals, defaults and
closure cells remain dynamic. Retain function-version guards elsewhere and
free-threaded behavior. Tests cover distinct closures sharing code, defaults
changes, missing arguments, code replacement, non-functions and errors.
This is a hypothesis-driven prototype, not yet measured; debug regeneration
and validation are running.

Frozen truth7 screen: btree 0.8712, deltablue 0.8826, go 0.9743,
hexiom 0.8381, raytrace 0.9019, spectral_norm 0.3933,
SQLAlchemy 1.0133. BPE was not rerun for this screen. The all-eight target
is still unmet; neither truth cleanup nor partial compilation establishes a
SQLAlchemy gain. Extend closure code-guard coverage to vectorcall replacement,
which must leave the optimized path and invoke the replacement callback.

Closure code guards pass 1,117 GIL debug tests and 1,306 GIL native /
free-threaded debug/native tests (the latter includes test_call; four/five
skips). Saved the dirty source diff, new headers and file hashes alongside
the frozen executable's upcoming seven-workload screen.

The nested-call helper currently accepts only ENTER_EXECUTOR at code offset
zero. A closure's COPY_FREE_VARS prefix therefore sends the call and its
continuation through Tier 1. Prepare a separate GIL-only fast path for exactly
one COPY_FREE_VARS followed by an executor: check recursion, instrumentation
and executor entry before copying the actual function's cell references.
Keep allocating MAKE_CELL / extended prefixes and FT on the existing path.
Add a test using sys._jit.is_active() after the call to verify return to the
compiled caller, distinct closure cells, stable cell refcounts and exceptions.
Build this second change only once the frozen code-guard screen completes.

Closurecode7 completed with identities/checksums verified: btree 0.8883,
deltablue 0.8968, go 0.9710, hexiom 0.8147, raytrace 0.8856,
spectral_norm 0.3922, SQLAlchemy 0.9973. Code guards alone do not demonstrate
a SQLAlchemy gain. The cell-entry helper and its tests are now building in
GIL/free-threaded debug configurations, after that screen completed.

Cell entry passes all 1,307 tests in GIL debug/native and free-threaded
debug/native (four/five skips). The GIL test confirms native/Tier-2 execution
continues in the caller after distinct closures sharing a code object;
the closure cell refcount remains unchanged across repeated calls. Captured
the source diff/new headers/hashes and froze python-goal-cellentry. Run a
fresh all-eight screen against matched main, without concurrent builds or
profiling. The latest complete all-eight performance result is still budget8
until this new run finishes; intermediate seven-workload screens are separate.

Correction to the code-guard hypothesis: Objects/funcobject.c documents and
implements MAKE_FUNCTION assigning func_version from co_version. Unmodified
closures sharing code already share their function version. Only later
attribute changes clear it. Thus the claim that reconstructing a closure by
itself fails the existing guard was wrong. Remove the unneeded code-version
opcode/selection, keeping the cell-entry helper and the shared-closure,
defaults/code/vectorcall mutation correctness tests under the original guard.
The frozen cellentry8 run still includes the now-rejected guard experiment;
preserve its data, regenerate/revalidate the reduced implementation after
timing, and measure that implementation separately. The direct-entry test is
independent of the rejected guard hypothesis.

Cellentry8 (including the subsequently rejected code-guard prototype)
completed with all checksums/identities verified: BPE 0.8995, btree 0.8704,
deltablue 0.8869, go 0.9748, hexiom 0.8224, raytrace 0.8827,
spectral_norm 0.3922, SQLAlchemy 1.0010. These are screening point estimates;
BPE being barely below 0.90 is not verification of the target. SQLAlchemy
still shows no demonstrated gain. Regenerate and validate cellonly, which
retains direct closure entry and restores the existing function-version guard.

Cellonly passes 1,307 tests in each of GIL debug/native and FT debug/native
(four/five skips). Generated files contain no rejected code-guard opcode.
Save source identities and freeze python-goal-cellonly for a new all-eight
screen. The runner now also hashes both builds' standard extension modules
before/after, in addition to executables, workloads and shared dependencies.

A separate debug structural diagnostic warms the unchanged SQL workload
three times and traces one subsequent 100-row query (30-second timeout,
64-MiB output cap). It completes/checks 100 rows and ID sum 5,050. This is
not timing evidence and ran alongside compilation. Its filtered opcode log
confirms the ordinary function-version guard passes for the generated
primary-key getter, and the new cell-entry helper returns directly to the
_instance method. Full/filtered logs are retained for inspecting later exits.

The same diagnostic identifies a more substantial integration issue. On the
first row, _instance executes its method and later deopts at code-unit 603
(an attribute load). On the next 99 rows, the existing chunks@202 loop trace
inlines the start of _instance and its primary-key getter, then unconditionally
deopts after the getter's LIST_APPEND at code-unit 25. The remainder of
_instance runs in Tier 1, even though it has a valid method executor. This
explains why making a method executor available need not make it execute.
The earlier exit JSON's frame field is only the last LLTRACE resume label,
not a reliable executor owner across nested returns; the filtered sequence
establishes the chunks trace and nested getter ownership.

Next investigate the ENTER_EXECUTOR tracing policy: it currently deliberately
traces through RESUME executors, which makes sense for old resume traces but
also bypasses method executors. A bounded experiment is to stop tracing at an
existing method executor while retaining the old policy for resume traces,
using the existing stop_tracing / _EXIT_TRACE path. Add a generator-caller
regression (so the caller uses tracing fallback), warm its closure callee's
method first, verify results and that the trace stops before inlining its
body; then validate recursion, monitoring, FT and all eight workloads.
This change is not implemented yet. No benchmark-specific policy is proposed.

Reduced cellonly8 screen completed with binary/standard-extension/dependency/
workload identities and all checksums verified: BPE 0.9069, btree 0.8782,
deltablue 0.8955, go 0.9781, hexiom 0.8167, raytrace 0.8886,
spectral_norm 0.3922, SQLAlchemy 1.0084. The eight-workload goal is not met.
The Japanese table and exact executable hashes are in cellonly8-compare.md;
the rejected guard experiment's numbers are not substituted for these.
Proceed to the method/trace boundary experiment described above.

Implemented the first boundary prototype in ENTER_EXECUTOR: preserve the
existing trace-through policy only for non-method executors; methods take
the existing stop_tracing path. Added a warmed closure method called from
a generator loop, asserting correct values/type changes/errors and that the
loop trace does not inline the callee's integer addition. Regeneration and
the GIL debug regression suite are running before native/FT acceptance.

The all-method boundary prototype passes the new focused test but the broad
suite reports four optimization-shape failures: super-call guard folding and
None/int/float result cleanup after a tiny identity call. The trace now stops
before those useful small-call optimizations. Preserve small-method tracing
instead of weakening those tests: share the existing 128-code-unit CFG-inline
bound in pycore_optimizer.h, and stop tracing only at larger method executors.
The generator regression now uses a generated 40-addition closure beyond that
bound. Rebuild/retest this large-method boundary variant; no timing result yet.

Largeboundary passes all 1,308 tests in all four configurations (four/five
skips), retaining the four small-call optimization assertions unchanged.
However, the repeated structural query still records one _instance method
entry and 99 getter-loop deopts. The loop trace predates the method executor,
so a policy applied only when making new traces cannot replace it. No
performance timing was run for this intermediate variant.

Add an optional dependency invalidation after successfully installing a large
method: invalidate only non-method executors whose Bloom filters may contain
the code object. Existing trace analysis records inlined code dependencies.
Keep the new method and other method executors. Reuse dependency scanning
with a traces-only mode; allocation failure in this optional optimization
retains old traces instead of clearing all executors, while correctness-driven
invalidations keep their existing fallback. Extend the generator regression
to build an inlined trace first, then warm the callee and verify the old trace
is invalidated and rebuilt with the method boundary. Debug validation runs now.

Refreshtraces passes all 1,308 GIL debug tests (four skips), including the
extended cold-trace-to-method transition regression. The same bounded debug
query now enters _instance's method 100 times, versus once in cellonly and
largeboundary; the getter-loop deopt falls from 99 occurrences to zero.
All diagnostic queries return/check the same 100 rows. This establishes an
execution-path improvement, not a timing gain. Native and FT build/test runs
are in progress; benchmark only after all builds finish.

Refreshtraces now passes 1,308 tests in all four configurations (four/five
skips). Captured its source manifest/diff/new headers and froze
python-goal-refreshtraces. The all-eight screen is running with the extended
identity checks and no simultaneous build/profiler. Cellonly8 remains the
latest completed performance comparison until this run finishes.

Refreshtraces8 completed all eight with identities/checksums verified. Ratios:
BPE 0.9050, btree 0.8174, deltablue 0.9071, go 0.9398, hexiom 0.8338,
raytrace 0.9015, spectral_norm 0.3929, SQLAlchemy 0.9933. Btree and Go's
point estimates improve versus cellonly, but all-eight <=0.90 is still unmet.
Go varies 0.9210–0.9500 and Raytrace 0.8802–0.9350 across blocks; retain
all values. See refreshtraces8-compare.md and matching state/raw files.
Run a controlled native SQL perf profile after this screen to identify costs
inside the method path now that it is actually used. No build overlaps perf.

Controlled native SQL perf completed: 44,433 samples, no loss. _instance's
method now accounts for 3.01% (previously 0.02%); interpreter remains 15.11%,
type-cache lookup 4.31%, allocation 2.62%. Do not confuse those sample shares
with wall-time speedups. Its generated method repeatedly treats LOAD_DEREF
as escaping because empty-cell error formatting can run Python.

Implement a GIL method-only _LOAD_DEREF_GUARDED: acquire the actual cell
value with the existing non-escaping PyCell_GetRef, deopt on NULL, otherwise
return the owned value. The original bytecode handles unbound errors at the
correct instruction and exception table. Preserve method facts across this
successful load; retain FT's existing lock-free getter. Add a protected
empty-cell/delete/rebind/None test and assert lowering in the existing
closure-mutation test. Debug regeneration/build/validation are running.

Cellload passes all 1,309 tests in GIL debug/native and FT debug/native
(four/five skips). Generated metadata confirms the guarded load has an exit
but no escape/error flag. Freeze python-goal-cellload and screen the seven
shorter workloads before deciding whether to run BPE/full eight again.
The main control and measurement parameters remain unchanged; no builds
overlap this timing.

While the frozen cellload binary is timed, prepare a separate local-store
cleanup improvement. The method uop model already knows the previous local
after _SWAP_FAST, but translation left its _POP_TOP generic even for NULL or
exact primitive types. Restrict specialization to STORE_FAST and its two
superinstructions: no-op for proven NULL/borrowed/immortal/bool/None, existing
int/float/str cleanup otherwise. Unknown values keep ordinary cleanup. Tests
cover initial local assignment, replacing a freshly computed float, and a
callback mutating f_locals to install a finalizer-bearing object (which must
invalidate the assumptions and observe the replacement already stored).
Build/test after the cellload screen ends; no performance claim yet.

Cellload7 completes all seven checksummed workloads with unchanged binary/extension/dependency identities. Ratios: btree 0.8394, deltablue 0.9079, go 0.9450, hexiom 0.8367, raytrace 0.8754, spectral_norm 0.3890, SQLAlchemy 1.0000. This is a screen, not evidence of all-eight success. Local-store cleanup passes all 1,310 GIL debug tests (four skips); native/FT validation follows before timing.

Local cleanup passes all 1,310 tests in all four configurations (four/five skips). Freeze python-goal-localcleanup and capture source identities before the next experiment. Seven-workload screening is running without concurrent builds. SQL structural inspection confirms the earlier code-unit 603 exit loads InstanceState.modified: an instance field may be absent while the class provides False. Investigate a guarded immutable class-default fallback for this general attribute pattern.

Localcleanup7 ratios are btree 0.8197, deltablue 0.9021, go 0.9334, hexiom 0.8341, raytrace 0.8786, spectral_norm 0.3914, SQLAlchemy 0.9753. SQL block ratios vary 0.9334–0.9983, so do not infer a stable 2.5% gain from this screen. All identity and output checks pass.

Prepare method-only LOAD_ATTR_INSTANCE_VALUE_OR_DEFAULT for GIL builds. Resolve the existing cached type version at compilation; accept only immortal class defaults with immutable, non-descriptor types. Keep existing type-version and inline-values-valid guards and owned/borrowed cleanup. Load the instance value when present, otherwise the immortal default. FT and unsupported defaults retain original behavior. Test inherited default, deleting/rebinding instance attributes, class mutation, property replacement, dictionary replacement and __getattr__. Regeneration/debug validation is running.

Attrdefault passes 1,311 GIL debug tests (four skips). Structural SQL query now executes the new default load at code unit 603 and reaches the method return at 700 for all 100 rows; prior refreshtraces deoptimized at 603. See attrdefault-path-diagnostic.json and filtered trace. This diagnostic ran during builds and is not timing evidence. Native and both FT validations are still running.

Attrdefault passes 1,311 tests in all four configurations (four/five skips); source snapshot and frozen python-goal-attrdefault captured. Run all eight workloads including SQLAlchemy as one common comparison, without concurrent builds/profiling.

Prepare a separate conditional-NULL lowering while attrdefault8 times frozen binaries. Method translation retained _PUSH_NULL_CONDITIONAL even though oparg fixes its stack effect. Static Go disassembly shows an unnecessary spill before this uop after ordinary attribute loads; the tracing optimizer already lowers it to _PUSH_NULL or _NOP. Apply the same lowering before method stack-cache assignment. Tests cover ordinary instance loads and callable instance attributes, callable replacement, non-callables and missing attributes. Build only after attrdefault8 ends.

Attrdefault8 completed all eight unchanged workloads with verified identities/checksums. Ratios: bpe_tokeniser 0.8979, btree 0.8320, deltablue 0.8966, go 0.9367, hexiom 0.8353, raytrace 0.8866, spectral_norm 0.3920, sqlalchemy_declarative 0.9918. All-eight <=0.90 remains unmet. Full comparison: jit-artifacts/all-benchmarks-10pct-20260916/attrdefault8-compare.md. Structural default-load improvement did not establish a large SQL wall-time benefit (0.9918). The next nullstatic lowering is now building/testing; no build overlapped timing.

Nullstatic passes all 1,312 tests in four configurations (four/five skips). Go structure comparison shows Board.useful spills/reloads 95→73, uops 858→804 and executable allocation 40→36 KiB; Square.find spills 6→4, Square.move 67→57. See nullstatic-structure-comparison.json; these are structural counts, not speedups. Freeze python-goal-nullstatic and source snapshot; run full eight comparison without overlapping builds/profiling.

Next diagnostic hypothesis (not implemented as a default change): RESUME_INITIAL_VALUE remains 8190, a tracing policy explicitly intended to let loop traces inline functions before function entries compile. SQL warmup invokes some ORM functions only hundreds of times, so method coverage may remain limited. After nullstatic8, use the existing PYTHON_JIT_RESUME_INITIAL_VALUE override to compare default 8190 against 510 on unchanged SQL and Go workloads, three alternating process blocks, identical frozen binary, warmups/values and output checks. Record whole-process wall time as well as timed samples to expose added compilation/startup cost. Do not treat an environment-only probe as the final main comparison or adopt the threshold without evidence and validation.

Nullstatic8 completes with verified identities/checksums. Ratios: bpe_tokeniser 0.9003, btree 0.8046, deltablue 0.8885, go 0.9011, hexiom 0.8345, raytrace 0.8696, spectral_norm 0.3913, sqlalchemy_declarative 0.9868. See nullstatic8-compare.md and raw/state files. This supersedes attrdefault8 as the common full-eight screen; all-eight target still unmet. Proceed with the predeclared threshold probe on frozen nullstatic, changing only the existing resume threshold environment override.

Reject lowering the default resume threshold based on the fixed probe: SQL runtime at 510/default = 1.1389 (all three blocks regress, range 1.1233–1.1590), whole-process wall ratio 1.0979; Go runtime ratio 0.9891. Identities/checksums pass. Keep 8190 unchanged. Earlier method compilation alone is not a solution for SQL. Next run a controlled native default-configuration SQL perf profile after all timing completes.

Default nullstatic SQL perf: 43,012 samples, no loss; interpreter 15.09%, type-cache lookup 4.36%, _instance method 3.06%. Separate JIT-disabled cProfile call counts confirm hot new_instance calls; LLTRACE shows new_instance is already inlined, so missing standalone executors do not establish lack of JIT coverage. Its self.class_ and _state_constructor loads nevertheless remain generic. Source inspection and a matched-main reproducer identify a shared Tier-1/JIT specialization gap after dictionary materialization (bugs_report.md P-3). Permit valid inline-value LOAD_ATTR specialization in GIL builds after materialization, keeping stores and FT policy unchanged. All 83 debug opcode-cache tests pass; remaining four-configuration coverage is running before timing.

Materialdict passes all 1,312 JIT tests (four/five skips) plus 83 JIT-disabled opcode-cache tests in each of the four configurations. Native candidate also specializes the main reproducer correctly. Freeze python-goal-materialdict and capture the expanded source manifest including specialize.c/test_opcache.py. Screen the seven shorter workloads before the next full eight run; no build/profiler overlap.

Materialdict7 ratios (all identities/checksums verified): btree 0.8145, deltablue 0.8857, go 0.9030, hexiom 0.8345, raytrace 0.8865, spectral_norm 0.3907, sqlalchemy_declarative 0.9700. SQL remains above the target despite the valid specialization fix; retain all blocks. Next inspect the remaining generic ClassManager accesses after the normal three warmups to separate compilation coverage from unspecialized attribute paths.

Materialdict manager diagnostic confirms valid inline dictionaries and specialized class_ loads. _state_constructor remains generic because its memoizing descriptor has a mutable Python type. Implement a general LOAD_ATTR_INSTANCE_VALUE_NONDATA specialization in GIL builds: retain owner type-version/inline-valid guards, borrow the descriptor protected by that owner guard, dynamically reject tp_descr_set, and require a present instance value. This preserves priority if the descriptor type gains __set__ or changes class; empty fields fall back to normal descriptor lookup. Cache footprint remains nine entries (compile-time sizeof check). FT retains the previous generic path. Tests cover materialized dictionaries, descriptor-type mutation, deletion/rebinding, callable attributes and collection/replacement of the borrowed descriptor. Regeneration and debug validation are running; this is a new coverage optimization, not a new wrong-result bug in main.

Nondata GIL debug passes all 84 opcode-cache tests and 1,313 JIT regression tests (four skips). Other builds/tests continue. Also correct the diagnostic perf mapper to collect all live functions for SQL: generated ORM functions can have __module__ = None and were excluded by the earlier module-prefix filter. Record mapped/unmapped range counts in a new coverage sidecar; previous raw-address JIT samples must not be treated as interpreter work or assumed absent code. Re-profile only after builds and timing finish.

Nondata passes 1,313 JIT tests (four/five skips) and all 84 opcode-cache tests in each configuration. Freeze python-goal-nondata, capture source/diff/new headers including the expanded generated opcode metadata, then screen seven short workloads with no builds/profilers overlapping.

Nondata7 completes with all identities/checksums verified: btree 0.8153, deltablue 0.8801, go 0.9018, hexiom 0.8437, raytrace 0.8818, spectral_norm 0.3927, sqlalchemy_declarative 0.9611. SQL improves directionally but remains above 0.90. Run the corrected all-function native profiler before selecting the next change, with no timing/build overlap.

Corrected nondata SQL perf maps all 29 ranges present after warmup; 41,521 samples, no loss. Interpreter 15.70%, type-cache lookup 3.92%, generic getattr helpers 0.91/0.92%, _instance method 3.24%; generated attrsetter jit::None.set is only 0.11% self samples. Do not infer that a frameless-setter optimization alone would close the SQL gap. Next obtain a native BPE profile as it also remains on the 0.90 boundary; select its next optimization from actual costs rather than changing benchmark inputs or warmup.

Profile validity caveat: nondata SQL ends with 8 of 29 captured executors invalid and 5 replaced. Its initial map has complete snapshot coverage but not lifetime coverage; later executors must remain unattributed rather than inherit old names. Preserve this limitation when reading the profile and inspect which executors change.

BPE native profile: 35,114 samples, no loss; dict lookup 6.29%, bpe_train@828 5.80%, tuple deallocation 4.29%, interpreter 4.10%, plus substantial allocation/GC work. 16 of 21 initial ranges mapped (all raw/coverage/validity artifacts retained). The hot @828 trace still spills around fused left-versus-len comparisons and closes a known len callable through generic POP_TOP. Prototype a GIL-only fused comparison with internal guarded non-escaping cleanup of callable/container/left, preserving cleanup order and deopting before work if a close could invoke Python. This targets a concrete JIT overhead; do not change GC settings or benchmark inputs. FT keeps its current uop.

Lenclean adds _CALL_LEN_LEFT_COMPARE_CLEAN selected only by GIL region lowering. Before any mutation it checks supported length/int arithmetic and all three references with _PyJit_CanCloseNoEscape; it then returns the boolean and closes callable, container and integer in the original order. This removes three stack outputs/cleanup uops and preserves FT behavior. Tests retain scalar/custom-length/large-integer fallbacks and add a freshly allocated list with a finalizer, comparison TypeError and raising __len__. The finalizer-bearing factory is used during warmup too, so changing the callable guard cannot mask the owned-container fallback. The strengthened focused debug test passes; broad debug tests and native/FT builds continue.

Lenclean passes all 1,314 tests in four configurations (four/five skips); the strengthened cleanup test was also rerun separately on debug. Generated metadata confirms the fused uop has exits but no escape flag. Capture source snapshot and frozen python-goal-lenclean; run all eight including SQLAlchemy as a common comparison, no concurrent builds/profilers.

While frozen lenclean8 runs, prepare GIL-only cached descriptor binding for inline-value instances whose shared keys exclude the attribute. Reuse the existing owner type-version/inline-valid guards and nine-entry method cache. Cache the immutable-type non-data descriptor, acquire a strong reference before calling its current tp_descr_get, and return its current binding (never freeze staticmethod/classmethod.__func__). Preserve the generic escaping/error path and owner cleanup; FT keeps previous behavior. Cover bound methods, staticmethods, classmethods, descriptor __init__ mutation, instance shadowing/dictionary replacement, owner-class replacement and callable/error cases. Build only after timing ends.

Lenclean8 completes all eight with verified identities/checksums: bpe_tokeniser 0.8973, btree 0.8115, deltablue 0.8852, go 0.9368, hexiom 0.8410, raytrace 0.8987, spectral_norm 0.3944, sqlalchemy_declarative 0.9446. All-eight target remains unmet. The cached-descriptor prototype keeps direct classmethod call syntax on the existing generic method-load path, which already avoids a bound-method allocation; only ordinary classmethod retrieval is newly specialized. Begin regeneration/build/test now that timing has ended.

Lenclean8 Go block ratios are [0.894323944890476, 0.8815822831552317, 1.0427452632084233]. Its aggregate 0.9368 is worse than nullstatic/nondata short screens; do not discard the slower blocks or claim a universal win from lenclean. After the current descriptor build, inspect Go lowering and compare the frozen candidates in a prespecified paired run if the regression remains.

Descriptor regeneration initially rejected ERROR_IF because the receiver remains live on binding failure. Use the existing ERROR_NO_POP convention so the unchanged receiver remains available to exception unwinding; retry regeneration. Add descriptor/functools/weakref/GC suites to GIL validation for the new binding/allocation path.

Go slow-block evidence: lenclean8 block 2 main samples are 65–68 ms, candidate starts at 65–67 ms then rises to 75–78 ms (earlier candidate blocks about 57 ms). This is within-process drift, not just a stable rebuilt-binary shift; no cause established. Preserve all samples. Extend the next suite runs with before/after CPU 2/SMT-sibling 3 /proc/stat ticks, instantaneous frequency snapshots, actual worker cgroup membership and child CPU time/fault/context-switch deltas. Instantaneous clocks alone do not establish frequency causality. Save the prior runner as run_suite-before-telemetry.py; workload/timing parameters remain unchanged.

Descrbind passes 1,315 JIT tests and all 85 JIT-disabled opcode-cache tests in each of four configurations (four/five JIT skips). Additional GIL debug/native descriptor, functools, weakref and GC suites pass 707 tests (two expected failures, two/three skips). Freeze python-goal-descrbind and source identities, then run all eight unchanged workloads with new read-only host telemetry; no concurrent build/profiler.

Descrbind8 completes all identity/checksum checks. Ratios: bpe_tokeniser 0.9044, btree 0.7990, deltablue 0.8837, go 0.8998, hexiom 0.8293, raytrace 0.8837, spectral_norm 0.3925, sqlalchemy_declarative 0.9517. See descrbind8-compare.md. Go samples are stable around 57 ms across all three candidate processes; recorded SMT sibling CPU 3 stays idle during each Go process, but this does not establish the cause of the earlier lenclean drift. All-eight target remains unmet.

Additional code review found a correctness gap in the new descriptor binding: an immutable user-defined descriptor may raise AttributeError while its owner defines __getattr__. The frozen descrbind debug reproducer fails, so reject binding specialization for owners whose tp_getattro is not PyObject_GenericGetAttr. Keep generic lookup responsible for invoking __getattr__ once. Add both Tier-1 and method-JIT regression tests using PyType_Freeze; this is a bug in the new prototype, not main. Validate before replacing the frozen performance candidate.

Descrsafe passes all 86 opcode-cache and 1,316 JIT tests in four configurations (four/five JIT skips). Freeze corrected binary and source identities. Next inspect the normal warmed SQL query trace and a separate default-workload native perf profile with frame-pointer call chains; these diagnostics are not wall-time comparisons.

Descrsafe SQL native profile: 41,314 samples, no loss, all 29 initial JIT ranges mapped. Type-cache lookup 3.54% self; call chains include 0.59% through generic attribute stores. InstanceState._cleanup contains four generic STORE_ATTR uops despite valid inline dictionaries. Implement a separate GIL-only STORE_ATTR_INLINE_WITH_DICT for materialized, valid inline dictionaries without watchers. Guard validity/materialization/watcher bits before mutation; maintain dictionary size and insertion order before decref can invoke finalizers. Keep existing no-dict store and FT paths unchanged. Tests cover insertion/replacement/order/iteration, dictionary replacement/clear, descriptor mutation, finalizer reentry, and adding a dictionary watcher after specialization/compilation.

Inlinestore passes all 88 opcode-cache, 1,317 JIT and 263 dictionary/watcher/GC tests in all four configurations (expected configuration-specific skips). Freeze and screen seven shorter workloads without build overlap. Structural SQL tracing corrects the initial hypothesis: generic STORE_ATTR count remains 900 per 100-row query, because assignments overriding immutable class defaults are rejected before the dictionary specialization helper. This is distinct from dictionary materialization. The inspected InstanceState has valid inline values; session_id/_strong_obj are None class defaults. Next allow NON_DESCRIPTOR stores in GIL builds through existing type-version guarded paths; immutable non-descriptors cannot intercept assignment, while replacing a class binding invalidates its version. Tests cover inherited defaults, missing/reinserted fields, materialized and unmaterialized dictionaries, and replacement by a data descriptor after specialization/JIT compilation.

Inlinestore7 finishes with verified identities/checksums. Ratios: btree 0.7999, deltablue 0.8891, go 0.8950, hexiom 0.8353, raytrace 0.8657, spectral_norm 0.3938, sqlalchemy_declarative 0.9436. This screen does not establish a material SQL speedup; proceed with the separately identified class-default store coverage change.

Defaultstore passes all 1,318 JIT tests in four configurations and 89 opcode-cache tests. The new two-subcase opcode test initially reused one adaptive code object; reset_code now isolates materialized/unmaterialized cases, and GIL opcode suites pass after correction. SQL structural trace shows generic STORE_ATTR 900→300 per 100-row query and STORE_ATTR_INSTANCE_VALUE 400→1,000; the new materialized-dict store itself was not executed in that query. See defaultstore-path-diagnostic.json. Freeze candidate and run all eight for wall-time evidence before claiming an improvement.

While defaultstore8 times frozen executables, prepare a focused escape-analysis correction: _PyList_FromStackRefStealOnSuccess only allocates and transfers references, like the already non-escaping tuple helper. Both GIL/FT allocators schedule GC rather than invoking Python there. Mark this helper non-escaping so BUILD_LIST preserves facts and avoids unnecessary validity checks/frame synchronization. The captured BPE hot @828 trace currently checks validity immediately after building each empty new_word list. Add alias-preservation and allocation-failure/traceback tests; no build until defaultstore8 completes.

Defaultstore8 completes all identity/checksum checks. Ratios: bpe_tokeniser 0.8952, btree 0.8024, deltablue 0.8890, go 0.8983, hexiom 0.8387, raytrace 0.8867, spectral_norm 0.3919, sqlalchemy_declarative 0.9225. SQL block ratios 0.9228/0.9219/0.9226 agree, but remain above target. The materialized-dict path plus class-default coverage improves directionally over descrbind/inlinestore; cross-build screens do not isolate exact attribution. Build/test the list escape correction now that timing has completed.

Listescape passes 1,320 JIT tests and 132 list/GC tests in all four configurations (expected skips), including allocation-failure traceback and alias checks. Generator suite passes all 102 tests. Freeze candidate and run all eight; no builds/profilers overlap.

Prepare guarded GIL-only DELETE_ATTR_INSTANCE_VALUE while frozen listescape8 runs. SQL cleanup deletes two fields per row; STORE_ATTR with a NULL value currently never specializes. Reuse the same family/cache size and type-version guard, accept absent or immutable non-overriding class bindings, require valid inline values and no dictionary watcher, and exit before mutation for missing fields or invalid dictionaries. Move the existing insertion-order deletion helper into pycore_dict.h and reuse it; update size/order before decref can invoke a finalizer. FT keeps generic deletion. Add tests for class-default and method shadow deletion, missing fields, insertion order/iterators, dictionary replacement/clear, watcher activation, finalizer reentry and replacing the class binding with a data descriptor. No build until listescape8 finishes.

Listescape8 completes all identity/checksum checks. Ratios: bpe_tokeniser 0.9001, btree 0.8045, deltablue 0.8915, go 0.9025, hexiom 0.8563, raytrace 0.8952, spectral_norm 0.3943, sqlalchemy_declarative 0.9158. SQL remains above target; retain all blocks. Begin deletion specialization regeneration and four-configuration correctness validation after timing.

Deletion regeneration initially failed because the cases parser did not accept a preprocessor directive between if and else; keep the directive inside the else body, regenerate successfully. GIL debug passes all 91 opcode-cache, 1,321 JIT and 431 dictionary/watcher/GC/descriptor tests (one skip/two expected failures in the extra suite). Remaining configurations build/test. The old structural query harness retains rows until tracing stops, so its unchanged 300 generic stores do not measure weakref cleanup. Do not use that count to reject the deletion or materialized-store path. Warmed cleanup bytecode does contain two DELETE_ATTR_INSTANCE_VALUE and two STORE_ATTR_INLINE_WITH_DICT instructions. Add a separately labeled row-release phase to the diagnostic harness to observe actual cleanup, keeping benchmark workloads unchanged.

Inlinedelete passes 91 opcode-cache, 1,321 JIT and 431 dictionary/watcher/GC/descriptor tests in all four configurations (expected skips/failures). The newly observed 100-row release executes 200 _DELETE_ATTR_INSTANCE_VALUE and 200 _STORE_ATTR_INSTANCE_VALUE uops; warm bytecode may later switch to the materialized-dict variant in other phases. Freeze candidate/source and screen seven short workloads, with no build/profiler overlap.

Prepare a JIT-selected zip fast path from BPE profile evidence: listiter_next 2.96%, zip_next 1.69%, tuple allocation/deallocation and GC are substantial. When a zip result is retained and both inputs are distinct exact list iterators with available items, create the next pair directly with _PyTuple_FromPair and advance only after successful allocation. This avoids two generic iterator calls and does not track scalar-only tuples. Keep tuple recycling, aliased iterators, arbitrary iterators, exhaustion and strict-mode checking on zip_next; keep all FT behavior unchanged. Select the helper in both trace and method compilation, retaining escaping/error handling. Tests cover retained values/identity, GC-containing pairs, independent and aliased iterators, exceptions, unequal lengths and strict mode. Build only after the inlinedelete7 screen finishes.

Inlinedelete7 completes identity/checksum checks. Ratios: btree 0.7987, deltablue 0.8841, go 0.9057, hexiom 0.8317, raytrace 0.8657, spectral_norm 0.3933, sqlalchemy_declarative 0.9134. SQL 0.9134 still misses target; do not infer a stable incremental deletion gain from adjacent screens. Begin zip fast-path regeneration and validation.

Zippair passes all 1,323 JIT tests and 328 builtin/tuple/list/GC tests in four configurations (expected skips). Scalar pair tests verify the GIL fast path produces untracked fresh tuples while GC-containing pairs stay tracked; strict and aliased-iterator fallbacks pass. Freeze source and binary, run all eight with no concurrent builds/profilers.

While zippair8 times frozen binaries, prepare a separate extended specialization for non-negative integers up to UINT64_MAX under &, | and ^ (including augmented forms). Go uses 64-bit Zobrist hashes; the native profile still attributes time to long_bitwise/dispatch, outside compact-int coverage. Keep compact signed cases first, guard exact type/sign/digit bounds, use defined uint64_t operations, then box normally. Larger, negative and subclass operands retain Python semantics. Add 30/60/63/64/100-bit boundary and fallback tests; apply to shared adaptive/JIT operation dispatch, not benchmark code. Build only after zippair8 completes and retain only with validation/performance evidence.

Zippair8 completes identity/checksum checks for all eight. Ratios: BPE 0.9044, btree 0.7999, deltablue 0.8803, Go 0.9023, hexiom 0.8377, raytrace 0.8687, spectral_norm 0.3915, SQLAlchemy 0.9052. All-eight target remains unmet; SQL blocks range 0.8921–0.9146. BPE does not establish a zip improvement. Inspect a separate native BPE profile before the uint64 build.

UInt64 passes 1,324 JIT and 92 opcode-cache tests in all four configurations, and 99 integer tests in both GIL builds. Additional FT integer tests crash reproducibly in subinterpreter creation, including the isolated int-limit test. GDB identifies add_threadstate(main) invalidating main executors while the current interpreter is the new subinterpreter. unlink_executor and the pending-deletion list incorrectly use the current interpreter. This predates the uint64 change (same implementation in HEAD), but blocks validation. Store the owning interpreter in each executor, use its registry/deletion list/cold-exit sentinels during invalidation, and assert registry identity. Add a subprocess regression that warms a main executor before repeated subinterpreter creation. Suspend timings until fixed.

Owner-interpreter fix passes the previously crashing isolated integer test and the corrected subprocess regression. The initial new test used a Python warmup loop, which traced/inlined its leaf instead of creating a leaf executor; use C map for that precondition. Native GIL/FT each pass all 1,424 JIT+integer tests (7/8 skips). Debug GIL/FT pass the other 1,423; their only failure was the already-corrected warmup fixture, separately rerun successfully with eight subinterpreter tests (FT one skip/two expected failures). Native subinterpreter suites also pass. Freeze uint64owner and screen seven shorter workloads before the next implementation. No main-defect claim for the new FT invalidation bug.

The zippair profile confirms the helper executes (1.28% self), with listiter_next 1.58% and zip_next 1.21%; this is coverage evidence, not wall-time attribution. Extend its exact-list fast path to unique recycled result tuples only when replacing old entries cannot destroy them. Refcount guards account for two slots sharing one old object; otherwise fall back before mutation so finalizers can still alter the second iterator between advances. Preserve tuple recycling/hash reset/GC tracking. Add regression tests whose old-item finalizer clears the second list, including aliasing both result slots. Build after the frozen uint64owner7 screen completes.

Uint64owner7 completes verified identities/checksums: btree 0.7977, deltablue 0.8813, go 0.8833, hexiom 0.8445, raytrace 0.8762, spectral_norm 0.3919, sqlalchemy_declarative 0.9198. Go is now below target in all three blocks; this screening comparison includes the required ownership fix, so it does not isolate code-layout effects. SQL remains above target. Begin zip recycling validation.

Zip recycling validation: all 1,325 existing JIT tests pass in four configurations. The new finalizer fixture initially wrote right[0] on a later iteration after deliberately clearing it; restrict that fixture mutation to its first iteration. The corrected regression plus 328 builtin/tuple/list/GC tests pass in all four configurations (8/9/13/14 skips). Preserve failed logs; implementation needed no correction. Freeze ziprecycle and run all eight unchanged workloads.

Prepare a Tier-2-only list-slice fast path, motivated by BPE samples in _PyEval_SliceIndex and PySlice_AdjustIndices. For exact list plus None/exact compact-int bounds, normalize negative indices without overflow and use PyList_GetSlice for clipping/allocation. Keep the original path for wide integers, __index__ callbacks, and all FT builds (the compile-time guard lives before template undefines Py_GIL_DISABLED). Preserve cleanup/error behavior. Add empty/nonempty, negative/out-of-range/huge bounds, list subclass, tuple/string fallback, mutation-order and exception tests. No build while ziprecycle8 times.

Ziprecycle8 verified comparison: bpe_tokeniser 0.9033, btree 0.8052, deltablue 0.8866, go 0.8963, hexiom 0.8380, raytrace 0.8817, spectral_norm 0.3938, sqlalchemy_declarative 0.8975. SQL is below 0.90 only in the aggregate; blocks 0.8810/0.9031/0.9087 do not establish a reliable 10% gain. BPE still misses target. Take a separate frozen-binary SQL profile before slice build.

Latest SQL native profile (ziprecycle): 40,405 samples, zero loss, 30/30 initial ranges mapped. Interpreter 16.25%, type-cache lookup 3.28%, _instance JIT 3.27%, malloc 2.80%, initialize_locals and frame-clear 1.33% each. The frame costs mostly enter through generic interpreter/C-call paths, so do not attribute them wholesale to the generated attribute setter. Attribute stores no longer dominate the top C symbols. See ziprecycle-sql.{txt,json,coverage.json} and the separately labeled frame call chains.

Listslice passes all 1,409 JIT/list/slice tests in each of four configurations (GIL four skips, FT five). Freeze source and executable, run the unchanged full eight with no builds or profilers. After that run, compare frozen ziprecycle against frozen inlinedelete on BPE only for three alternating blocks; this is an explicitly non-main diagnostic for whether the added zip complexity has a measurable net benefit (it also spans uint64/ownership changes, so exact causality remains limited). Preserve every sample.

While frozen timings run, prepare a bounded frameless setter optimization using the existing trivial-call guards/dependencies. Recognize only argument-to-attribute stores followed by return None, for specialized slot or unmaterialized inline storage. Guard owner version/dictionary state and old-value destruction before mutation; fall back if a finalizer could observe the omitted setter frame. Preserve insertion order and argument cleanup. The SQL setter is only 0.11% self in the latest profile, so treat its overall effect as an experiment rather than attributing all frame costs to it. Build only after both scheduled measurements finish.

Listslice8 completes verified identities/checksums: bpe_tokeniser 0.8965, btree 0.7995, deltablue 0.8996, go 0.8691, hexiom 0.8381, raytrace 0.8763, spectral_norm 0.3939, sqlalchemy_declarative 0.9122. The scheduled non-main zip diagnostic now runs. Prepared confirm_comparison.py for a future prespecified 8- or 12-block full-suite confirmation; it reports per-benchmark log-ratio Student-t intervals, never treating within-process samples as independent replicates, and explicitly limits claims to the fixed binaries/CPU.

Frozen BPE candidate-to-candidate diagnostic completes with ratio ziprecycle/inlinedelete 0.998022, blocks [0.997653032439748, 0.9967688423496714, 0.9996456887139679]. No main comparison or isolated zip attribution is claimed. Retain the coverage-tested path provisionally; its wall-time gain is small and not established as robust. Proceed with the separately prepared setter validation now that all timing ended.

Setter code review removes a temporary owning stackref used only to check old-value cleanup: creating one without consuming it would leak tracking state in Py_STACKREF_DEBUG builds. Factor the existing raw-object safety predicate into _PyJit_CanDecRefNoEscape and reuse it from both setter and stackref cleanup; no ownership conversion is needed. Apply after the first debug build finishes, then regenerate and validate this corrected implementation.

Settersafe passes all 1,330 JIT tests and 263 dictionary/watcher/GC tests in four configurations (expected skips), plus 102 generator tests. Tests exercise slot/inline insertion and replacement, reversed/bound arguments, owner class and function-code changes, local return monitoring, materialized/replaced dictionaries and watcher activation, and old-value finalizers observing the actual setter frame. Freeze and screen seven shorter workloads.

Settersafe7 completes verified identities/checksums: btree 0.8019, deltablue 0.8828, go 0.8772, hexiom 0.8329, raytrace 0.8660, spectral_norm 0.3917, sqlalchemy_declarative 0.9232. SQL remains above target; do not claim a wall-time win for setter elision. Inspect query+release LLTRACE to verify the new call path, then target repeated attribute-store escape bookkeeping.

Setter query+release LLTRACE executes 100 _CALL_STORE_ATTRIBUTE operations for 100 rows, confirming coverage despite no established wall-time win. Prepare non-escaping GIL slot/inline stores: guard old-value cleanup before transfer, retain existing owner type/dictionary guards, and leave unsafe destruction to the original bytecode. Keep owned-owner cleanup separately observable; omit it only for a compiler-proven borrowed receiver after the non-escaping store. FT helpers always decline and FT selectors retain old operations. This targets the 1,500 specialized attribute stores in the SQL query/release diagnostic and ordinary record updates generally.

Storeclean first GIL compilation exposed a generator-context mistake: CURRENT_OPERAND0_64 belongs to execution templates, not optimizer analysis. Pass the already-decoded offset/index variables to ADD_OP instead. FT debug/native each already pass 1,332 JIT and 431 dictionary/watcher/GC/descriptor tests (two expected failures in extra suite); the corrected lines are GIL-only. Regenerate and retry GIL validation. Generated new store metadata has HAS_EXIT_FLAG and no escape flag.

Corrected GIL storeclean builds exposed three existing integer-attribute-region regression failures: the fusion matcher recognized only the original store opcodes and no longer combined +=/-=. Accept both original and guarded non-escaping variants; the fused operation already proves an exact integer old value, so it satisfies the new destruction guard. Keep these structural tests, including allocation-failure traceback, instead of weakening them. Rebuild/retest GIL; FT behavior is unchanged.

Storeclean with fusion repair passes 1,332 JIT and 431 dictionary/watcher/GC/descriptor tests in both GIL builds; FT builds passed the same tests using their unchanged selectors. Extra suites have two expected failures and the usual skips. Float-alias tests pass in both method and loop-trace compilation, and old-value finalizers retain their frame/ordering semantics. Freeze and compare all eight without build/profiler overlap.

While storeclean8 times frozen binaries, prepare the remaining immutable non-data store coverage. analyze_descriptor_store already classifies METHOD/NON_OVERRIDING/classmethod only when the descriptor type is immutable and has no tp_descr_set, but STORE_ATTR still rejects those assignments. Permit the existing guarded dictionary/inline store specializations for these kinds in GIL builds; keep FT behavior. This covers ordinary instance fields shadowing class methods (including InstanceState.obj/_instance_dict), without invoking descriptor binding. Add Tier-1 and method tests for Python methods, static/class methods, builtin descriptors and frozen custom descriptors, materialization/replacement, deletion/reinsertion and replacing the class binding with a data descriptor. No build until storeclean8 finishes.

Storeclean8 completes all checks: bpe_tokeniser 0.8941, btree 0.8043, deltablue 0.8872, go 0.8884, hexiom 0.8295, raytrace 0.8916, spectral_norm 0.3912, sqlalchemy_declarative 0.9128. SQL remains above target; no large incremental store-cleanup speedup established. Begin immutable non-data store coverage build/tests now that timings ended.

Methodstore passes 93 opcode-cache, 1,333 JIT and 431 dictionary/watcher/GC/descriptor tests in all four configurations. Query+release structural counts are saved in methodstore-path-diagnostic.json: {'settersafe': {'_STORE_ATTR_SLOT_': 400, '_STORE_ATTR_INSTANCE_VALUE_': 1100, '_STORE_ATTR_': 300, '_CALL_STORE_ATTRIBUTE_': 100}, 'methodstore': {'_STORE_ATTR_SLOT_NOESCAPE_': 400, '_STORE_ATTR_INSTANCE_VALUE_NOESCAPE_': 1300, '_CALL_STORE_ATTRIBUTE_': 100, '_STORE_ATTR_': 100}}. Freeze and run all eight unchanged workloads without concurrent diagnostics/builds.

Prepare a follow-up to guarded stores: when the receiver is statically borrowed, the store either exits before mutation or completes without any callback/owned-owner cleanup. Preserve and learn its type-version facts across the bytecode, allowing consecutive field stores/loads to reuse their guard. Keep all facts conservative for FT or owned receivers. Add slot/inline tests that require a single receiver-version guard across two stores and a load; an old-value finalizer replacing the second field with a property must still force ordinary frame-visible behavior. This may also reduce method budget pressure; do not claim extra coverage until observed. Build only after methodstore8 timing completes.

Methodstore8 verified ratios: bpe_tokeniser 0.8935, btree 0.8009, deltablue 0.8933, go 0.8762, hexiom 0.8371, raytrace 0.8822, spectral_norm 0.3925, sqlalchemy_declarative 0.9103. SQL structural generic stores fell from 300 to 100 per query/release, but the runtime ratio remains above target. Begin guarded-store type-fact validation. The remaining generic SQL store is _instance offset 336/name index 11, consistent with the mutable load_path class default; a future specialization must check descriptor-type mutation, not assume this default stays non-data.

Storefacts first validation passes all 1,334 tests in both FT builds, but its new GIL structural test finds two guards for managed attributes. Slot stores already reuse one guard; managed stores use _GUARD_TYPE_VERSION_LOCKED, which the elimination predicate did not recognize. In GIL builds locking is a no-op, so extend that predicate to the locked guard only there. Keep FT locking/guard semantics unchanged, preserve the failed logs and rerun GIL validation, including the finalizer mutation fallback.

Storefacts with the GIL locked-guard correction passes 1,334 JIT and 431 dictionary/watcher/GC/descriptor tests in both GIL configurations; both FT configurations passed before the GIL-only correction. The structural test now proves one owner-version guard across two stores plus load, while finalizer-driven class mutation follows ordinary semantics. Freeze storefacts and screen all eight unchanged workloads; no build/profiler overlap.

Prepare GIL-only STORE_ATTR_INSTANCE_VALUE_NONDATA for mutable class defaults currently lacking tp_descr_set. Keep the four-entry STORE_ATTR cache and reject materialized dictionaries. Tier 1 checks the current class binding's descriptor type; method/trace compilation can replace that lookup with a cached pointer guarded by the preceding owner-version check. Check the descriptor's current type each execution, so adding __set__/__delete__ or changing its __class__ cannot bypass assignment semantics. Keep fact propagation conservative for this new opcode initially. Add Tier-1/method tests for mutable plain defaults and __get__ descriptors, setter/deleter changes, descriptor-class mutation, binding replacement/destruction, and dictionary materialization/replacement. Build only after storefacts8 finishes.

Storefacts8 completes all identity/checksum checks. Ratios: bpe_tokeniser 0.8999, btree 0.8163, deltablue 0.8883, go 0.8848, hexiom 0.8447, raytrace 0.8662, spectral_norm 0.3914, sqlalchemy_declarative 0.9081. SQL remains above target and BPE is borderline across blocks (0.8982–0.9014); no completion claim. Begin mutable-default store regeneration and four-configuration validation after timing. Include a loop-trace regression checking descriptor setter changes as well as method compilation.

Runtime introspection of sqlalchemy.orm.loading._instance_processor's nested _instance code confirms co_names[11] is load_path; this resolves the earlier structural inference. GIL debug passes 94 opcode-cache and 1,336 JIT tests; 102 case-generator tests pass. Remaining configurations and dictionary/descriptor suites continue.

Mutablestore passes 94 opcode-cache, 1,336 JIT and 431 dictionary/watcher/GC/descriptor tests in all four configurations, with expected skips/two expected failures in extra suites. Query/release tracing confirms the remaining 100 generic stores are gone: 400 slot no-escape stores, 1,400 inline no-escape stores, 100 cached mutable-descriptor checks, and 100 frameless setter calls. This establishes coverage, not wall-time gain. Freeze source/binary and compare all eight unchanged workloads without concurrent builds or diagnostics.

Mutablestore8 verified ratios: bpe_tokeniser 0.8915, btree 0.7834, deltablue 0.8865, go 0.8683, hexiom 0.8422, raytrace 0.8834, spectral_norm 0.3927, sqlalchemy_declarative 0.9105. The mutable-store coverage does not establish an incremental SQL speedup. Take a separate current-binary SQL native profile before choosing the next change. Structural initialization still includes 100 empty BUILD_MAP operations and 100 zero-argument builtin-class calls per query, with validity/frame synchronization around those allocations; potential allocation-only specialization must retain error locations and call-boundary periodic checks.

Latest native SQL profile records 40,536 samples with interpreter 16.52%, type-cache lookup 3.19%, _instance 3.17%, allocation 2.68%, frame clear 1.39% and locals initialization 1.32%. Small attribute-store changes did not remove the dominant costs. Before further allocation experiments, temporarily make the debug-only LLTRACE instruction printer emit the current frame header on every interpreter instruction. This resolves missing parent labels after calls through C (ordinary resume-only headers are insufficient for attributing bytecodes). Save the exact original ceval.h, rebuild only debug, collect a structural query/release trace, then restore/rebuild before any candidate freeze or timing. This is not a timing experiment and does not affect the frozen native binary.

Frame diagnostic restored ceval.h byte-for-byte and rebuilt debug. Query-only interpretation executes 4,550 bytecodes; largest groups are HasCacheKey._gen_cache_key (504), generated cache traversal (255), DefaultExecutionContext._init_compiled (235), and _instance_processor (165). Exclude the diagnostic's extra row-id assertion: it accounts for the apparent 2,096 InstrumentedAttribute.__get__ bytecodes and is not timed benchmark work. Counts are coverage evidence, not cycle attribution.

Correct the native profiling boundary: prior profile_named SQL runs also recorded untimed table cleanup and result verification. Preserve those profiles with this limitation. Add --sql-timed-only to gate perf around exactly benchmark(session, 100), leaving deletions/checks outside recording. New timed-sql profile: 39,502 samples, 29/29 initial ranges mapped, interpreter 16.48%, _instance 3.28%, type-cache 3.23%, allocation 2.55%, locals init 1.43%, frame clear 1.35%. Main timing comparisons already used correct benchmark boundaries and are unaffected.

Extend guarded-store fact preservation/borrowed-owner cleanup to the newly validated mutable-default opcode. Method compilation always replaces its lookup by the non-escaping cached descriptor check (or declines compilation), so the same no-callback proof applies. Keep its descriptor-type check even when owner-version guards are reused. Extend the consecutive-store/finalizer test to mutable class defaults. Validate this focused C-only follow-up before considering more allocation specializations.

Mutablefacts passes 1,336 JIT and 431 dictionary/watcher/GC/descriptor tests in all four builds (usual skips/two expected failures in extra suites). Freeze source/binary and screen the seven shorter workloads; BPE remains included in the goal but is deferred to the next full-suite comparison, not silently removed.

Prepare a narrow allocation-only specialization: BUILD_MAP 0 becomes _BUILD_EMPTY_MAP using PyDict_New, which schedules GC without calling Python. Preserve receiver facts in method analysis and avoid post-allocation validity/frame synchronization in both frontends; nonempty dictionary construction retains hashing/callback semantics. Add fresh-object identity/mutation, method guard reuse, loop-trace coverage, and forced allocation-failure traceback tests (drain the dictionary freelist first). No changes to benchmark code or call periodic checks. Regenerate/build after mutablefacts7 timing ends.

Mutablefacts7 verified ratios: btree 0.7947, deltablue 0.8660, go 0.8804, hexiom 0.8446, raytrace 0.8789, spectral_norm 0.3924, sqlalchemy_declarative 0.9140. One main deltablue process is slower (1.825 ms versus ~1.70 ms); retain it and do not attribute that lower ratio to the candidate. SQL still misses. Begin empty-map regeneration/validation.

Emptymap passes 1,339 JIT and 431 dictionary/watcher/GC/descriptor tests in all four configurations, plus 102 generator tests. Allocation-failure traceback and independent mutable dictionaries pass. Warmup diagnostics show HasCacheKey._gen_cache_key has no method rejection: after three default warmups its RESUME counter still has 5,738 calls remaining (about 2,452 calls consumed), with only loop executors at offsets 714/758. Thus method compilation occurs during later measured processes/values, not during initial warmup. The longer native profiles may include later compilation; initial JIT map coverage is not whole-run coverage.

Freeze emptymap and compare all eight normally. After that, prespecify a separate three-block same-binary probe of RESUME thresholds 8190 vs 2046 on SQL and Go. This tests a moderate threshold, unlike the previously rejected 510 probe; retain all process times/checksums and compilation/startup wall times. It is not a main comparison or a default-setting change. Do not build or profile during either measurement.

Timed-sql profile validity audit: only 21 of the 29 initially mapped executors remain valid/installed at the end, with five replacements. Its 100 repetitions extend far beyond the comparison's seven measured values and include additional warmup/compilation behavior. Use C-symbol costs and explicit initial coverage with that limitation; do not treat the initial map as complete JIT coverage for the whole profile or directly equate it with the shorter timing run. The query LLTRACE diagnostic also renders stack values, so function counts can include tracing-induced repr work; they identify investigation candidates, not measured time shares.

Emptymap8 verified ratios: bpe_tokeniser 0.8858, btree 0.7738, deltablue 0.8907, go 0.8828, hexiom 0.8374, raytrace 0.8641, spectral_norm 0.3913, sqlalchemy_declarative 0.9075. Retain all samples; the first main btree process is slower than the other two. SQL still fails the individual target, despite a small directional improvement.

Prespecified 2046/8190 threshold probe completes with verified identities/checksums: SQL runtime ratio 1.0401 (blocks 1.0558/1.0245/1.0402), Go 1.0035. Reject lowering the default to 2046. Process wall times are also retained but include cold pycache creation in the first block and coarse subprocess polling, so do not interpret their nearly quantized differences as precise startup costs. Keep the default 8190. Investigate compilation behavior under the rejected threshold separately; do not keep retuning thresholds until a favorable result appears.

Under the rejected 2046 threshold, _gen_cache_key does compile a 1,045-uop root (and keeps a loop executor); Session.get_bind is rejected during CFG analysis. This does not prove why the threshold regresses; keep 8190 and do not introduce a polymorphic __class__ fast path without stronger evidence.

Prepare a bounded zero-argument set() call specialization, observed 100 times per query in InstanceState initialization. Require a compiler-known canonical builtin set and a NULL receiver, retain runtime identity/NULL guards, allocate via a dedicated no-iterator helper, and keep the existing post-call periodic check at the next bytecode. Support method and loop compilation without changing Tier 1 or nonempty/keyword calls. Add fresh-set identity/mutation, global callable replacement, structural periodic-check retention, and allocation-failure traceback tests. This targets generic call/stack conversion overhead; no predicted percentage is claimed.

Emptyset passes 1,342 JIT and 1,075 dictionary/watcher/GC/descriptor/set tests in all four builds, plus 102 generator tests. Keep the call-boundary periodic check after successful construction; it exits before handling callbacks, so method receiver facts can remain valid on the successful native path. The new test verifies one receiver guard across stores separated by set(), in addition to callable replacement and allocation-error locations. Freeze and screen seven shorter workloads; run BPE again in the next full-suite comparison.

Prepare GIL-only reuse of managed-storage guards across non-escaping operations. Track valid-inline-values/no-materialized-dictionary facts alongside receiver type versions, clear them on every escape, and drop them conservatively at incompatible CFG joins. Reuse _GUARD_DORV_NO_DICT and _CHECK_MANAGED_OBJECT_HAS_VALUES only for the same local-origin receiver after an earlier successful guard. Also remove method _LOCK_OBJECT uops in GIL builds: their LOCK_OBJECT macro is literally 1, so retaining them wastes uop/exit-stub budget even though native compilation removes the lock body. FT keeps all locking/storage checks. Extend consecutive-store tests to require one storage guard and to materialize __dict__ from an old-value finalizer before the second store. Build only after emptyset7 finishes.

Emptyset7 completes all identity/checksum checks: btree 0.7941, deltablue 0.8762, go 0.8850, hexiom 0.8291, raytrace 0.8725, spectral_norm 0.3914, sqlalchemy_declarative 0.9153. No incremental SQL wall-time gain is established. Begin managed-storage fact/no-op-lock validation after timings end; do not claim completion or a successful set()-specific speedup.

Managedfacts initially passes the existing 1,342/1,075 tests in all four configurations, but review identifies a missing escape boundary: CALL_PY_EXACT_ARGS has no HAS_ESCAPES metadata because it transfers to a Python frame. The method dataflow therefore retained receiver facts across that call. A new isolated reproducer, whose callee replaces obj.__dict__ and returns the value for the next field store, aborts in GIL debug with the managed-store no-dict assertion. This is a bug introduced/exposed by the new prototype, not a main bug. The slot/__class__ variant does not fail (retain that negative result too). No managedfacts binary was frozen or timed.

Fix the frontend to treat every CALL/CALL_KW as escaping unless its dedicated empty-set construction proof applies. Add subprocess regression cases for small inlined and larger non-inlined Python callees that replace the receiver dictionary. Rebuild/retest four configurations before performance work resumes.

Managedsafe fixes the new callback escape bug and passes 1,343 JIT and 1,075 dictionary/watcher/GC/descriptor/set tests in all four configurations (expected skips/two expected failures). Both inlined and non-inlined callback dictionary replacements pass; finalizer materialization and class mutation still pass. Record the current query/release path counts separately, then freeze and compare all eight unchanged workloads with no concurrent build/profile.

Managedsafe8 verifies all identities/checksums: bpe_tokeniser 0.8891, btree 0.7937, deltablue 0.8834, go 0.8765, hexiom 0.8389, raytrace 0.8683, spectral_norm 0.3937, sqlalchemy_declarative 0.9064. SQL remains above the individual target. Prepare a bounded C-vectorcall path for already-compiled trivial method roots: argument/immortal-constant/guarded-attribute returns only, no setters. Reuse the existing body recognizer and cache its result in the executor. Require exact positional arity, no keywords, valid root, ordinary evaluation, no tracing/profiling, matching instrumentation/eval-breaker state and recursion margin. Fall back before any effects on a failed guard; FT and DTrace keep ordinary calls. C callers already hold argument references, so omitted frame cleanup cannot destroy them. Validate monitoring, code/type/dictionary changes, errors and lifetimes before timing.

Trivialroot passes 1,346 JIT tests and 1,075 extra tests in all four configurations. One concurrent FT-native GC test initially lost its shared TESTFN file (separate PID namespaces reused the same filename/cwd); the isolated full extra suite passes. Preserve both logs and use separate build working directories for future concurrent suites. A bounded GDB child diagnostic confirms no successful trivial C return in the SQL warmup3/value1 run: simple argument/constant/attribute bodies alone do not cover its C-call leaves. Freeze and screen the shorter seven to assess overhead before extending recognition to the observed BaseRow-style attribute-plus-index getter.

Trivialroot7 verified ratios: btree 0.8296 (candidate block spread 0.8061–0.8766 retained), deltablue 0.8815, go 0.8768, hexiom 0.8490, raytrace 0.8686, spectral_norm 0.4009, SQL 0.9113. No SQL benefit established; simple-root C shortcut remains experimental pending actual coverage. Extend the shared recognizer to return obj.field[key] with a specialized slot/inline attribute and exact tuple/list integer subscript. Cache both argument indices with the existing owner-version/offset layout. Add a guarded frameless uop for JIT callers and the corresponding C-vectorcall case; exact sequence/key, valid owner storage and bounds are required before cleanup. Callback-capable indices/sequences, missing attributes and errors fall back with the getter frame intact. Add method/C-call tests for negative/wide/out-of-range indices, custom callbacks, list/tuple changes and replaced dictionaries/properties.

Attributeitem validation initially exposes test-fixture issues: the closure caller has its entry after COPY_FREE_VARS, and reset_code assigns __code__, permanently clearing function-version specialization eligibility. Use fresh FunctionType instances with copied code and an explicit default callee, retaining the structural optimization assertion. No runtime correction was needed for these failures. Put the cached-kind rejection in the vectorcall entry so ordinary nontrivial roots avoid an extra out-of-line helper call. Complete a second dependency-checking make after regeneration before validating the final build.

The first fixture revision using FunctionType also lacks specialization versions: only MAKE_FUNCTION initializes them in this CPython. Correct the fixture with freshly compiled def statements in a new namespace for each receiver class; the focused structural/fallback test passes. Keep both prior failed test logs. The bounded GDB diagnostic now observes 500 successful C shortcuts, all BaseRow._get_by_int_impl, before disabling the breakpoint and finishing with correct SQL output. This establishes actual SQL coverage (not timing). Rerun the final corrected suites in separate build working directories.

Attributeitem passes the corrected 1,347 JIT and 1,075 dictionary/watcher/GC/descriptor/set tests in all four configurations, plus 102 generator tests; diff-check is clean. Freeze final source/native executable and compare all eight unchanged workloads. If all eight point estimates meet 0.90, prespecify a separate 12-block confirmation on these fixed binaries, with per-benchmark log-ratio Student-t intervals; otherwise diagnose the remaining gap before further changes. No concurrent builds/tests/profiling during timing.

Attributeitem8 verified ratios: BPE 0.8701, btree 0.7992, deltablue 0.8825, go 0.8790, hexiom 0.8427, raytrace 0.8800, spectral_norm 0.3928, SQL 0.90013 (blocks 0.89904/0.89538/0.90600). Do not round this into a target pass or run confirmation yet. Review reproduces a cache-liveness omission in the new C entry: it bypasses _MAKE_WARM, so two cold scans invalidate a root despite a call between them. The isolated ctypes reproducer fails on the frozen candidate. Set cold=false after entry guards and add a deterministic regression through a test-only cold-scan helper, also verifying genuinely unused roots remain collectible. This is a prototype defect, not a main defect.

Correct the coverage wording above: the initial GDB breakpoint is before attribute/item guards, proving 500 eligible C-entry attempts, not 500 successful returns. A source-line return breakpoint mapped to the following function due to inlining, so its empty result is not usable. Use a function entry/finish breakpoint pair to count actual non-NULL returns.

Entry/finish GDB pairs confirm 500 actual non-NULL returns from BaseRow._get_by_int_impl (no fallbacks in that bounded sample). The new cold-scan test also reveals cold was initialized only under _Py_JIT: interpreted Tier 2 can install a root, then scan it before any _MAKE_WARM execution, with an uninitialized flag. Initialize cold=false in _Py_ExecutorInit for both backends; keep the C-entry warm update. Native tests passed the warm-retention regression, while debug exposed this earlier initial-scan failure. Extra-suite commands accidentally included nonexistent test.test_capi.test_capi; correct the command and retain its import-error logs.

Leafwarmfixed passes 1,348 JIT tests and 1,075 extra tests in all four configurations; isolated before/after cold-scan reproductions now keep the used executor valid in debug and native. The regression also collects it after a subsequent scan without a call. Freeze this required liveness correction and compare all eight, retaining the same prespecified confirmation rule. No timing overlaps.

Leafwarmfixed8 completes identity/checksum verification but SQL remains 0.90439, so do not launch confirmation. Prepare exact-positional frame binding for compiled method roots reached through C vectorcall (including COPY_FREE_VARS prefixes). It keeps the real interpreter frame and ordinary evaluation entry, avoiding the temporary argument array and general binder. Require valid method root, JIT enabled, exact positional arity, no keywords/keyword-only/variadic/generator flags and available thread-stack space; all other cases use the existing path. This targets the residual initialize_locals/frame-entry costs without bypassing tracing, PEP523, recursion or closure initialization. Validate materialized-frame locals with >8 arguments, closures and recursive C callbacks.

Framebind passes 1,352 JIT and 1,075 extra tests in all four configurations. New cases verify real-frame locals for nine object arguments plus a control argument, closure cells and changes, recursive C callbacks/RecursionError, and a code object without RESUME (guard the firsttraceable index before dereferencing). Keyword/default/wrong-arity paths retain the general binder. Freeze and compare all eight unchanged workloads, with no concurrent build/test/profile.

2026-09-17: Framebind8 completes all identity/checksum checks. Ratios: BPE 0.8739, btree 0.7923, deltablue 0.8806, go 0.8906, hexiom 0.8415, raytrace 0.8581, spectral_norm 0.3925, SQL 0.89299. All eight screening point estimates now meet 0.90, but Go blocks range 0.8696–0.9122; retain this variation. As prespecified, launch exactly 12 new alternating blocks on the same frozen framebind/main binaries (warmups3/values7, CPU2, seeds0–11). No changes/rebuilds during confirmation; no early stopping or discarded slow trials. Evaluate each benchmark using its two-sided 95% log-ratio Student-t interval upper bound <=0.90, limited to these fixed binaries/CPU. Tag: framebind-confirm12-20260917.

2026-09-17: Goal achieved under the prespecified fixed-binary/CPU criterion. All 192 processes in the 12-block confirmation complete successfully; workload outputs, dependency versions and pre/post binary/extension/dependency/workload SHA checks agree. No samples were discarded, no early stop, and no builds/tests/profilers overlapped. Current runtime source files match the frozen framebind manifest (only this progress document changed).

| Workload | candidate/main | 95% log-ratio t interval |
|---|---:|---:|
| bpe_tokeniser | 0.873087 | 0.869321–0.876868 |
| btree | 0.791745 | 0.789867–0.793628 |
| deltablue | 0.884660 | 0.882461–0.886865 |
| go | 0.880638 | 0.874156–0.887167 |
| hexiom | 0.837734 | 0.827332–0.848267 |
| raytrace | 0.855502 | 0.850311–0.860726 |
| spectral_norm | 0.391896 | 0.391025–0.392769 |
| sqlalchemy_declarative | 0.892030 | 0.887262–0.896824 |

Each upper bound is <=0.90. These intervals cover run-to-run variation for these fixed binaries on CPU2, not independent rebuilds, other hardware, family-wise 95% coverage or a general Python-wide speedup. Some individual blocks exceed 0.90; the criterion is each workload’s paired process aggregate and interval, never the across-workload geometric mean.

Final evidence: benchmarks/jit_comparison.md and jit-artifacts/all-benchmarks-10pct-20260916/framebind-confirm12-20260917-{state.json,confirmation.md,confirmation.json}. Candidate: build-method-jit/python-goal-framebind, SHA-256 b434803ae2dc3ba8347d5eb7f9a39cdc9d9abea8574beeeb3767f68681a719ac. Main: jit-artifacts/method-perf-20260916/main-build/python, SHA-256 a245f5d91e4e5007af841be2296e55634aa8a29605b03af70fb3f772a6e7370b.

Final correctness: 1,352 JIT and 1,075 extra tests in each GIL debug/native and FT debug/native configuration, with expected skips/two extra-suite expected failures; 102 generator tests passed before the subsequent C-only changes. PGO/LTO remain off. No commits, pushes, GitHub posts or PR changes were made for this goal. No required implementation or validation work remains for the eight-workload target. Future broader claims would require separate rebuilds/hardware and a broader workload suite; they are not prerequisites added to this completed fixed-control task.

2026-09-17: At the user's request, prepare a local commit of the implementation,
regression tests, standalone workload sources, reports and final confirmation
evidence. Preserve the measured source and workload contents. Include all 192
process sample files, identity manifest, comparison scripts and final test logs;
exclude build trees, dependency installations and intermediate experiments.
The pre-existing executable-bit change to benchmarks/go.py remains outside
this commit. No push, GitHub post or PR change is authorized or performed.

## 2026-09-17: Full free-threaded pyperformance comparison preparation

The user will run the benchmark suite locally. Prepare a script that freezes
local main and HEAD, builds both with --disable-gil, native JIT and -O3, and
explicitly disables PGO, LTO and pydebug. Main receives only the previously
documented LLVM 21 local-reference reachability build fix. Do not reuse the
GIL-enabled eight-workload measurements for this new comparison.

Select pyperformance 1.14.0's all group, including explicit records for Python
version exclusions and dependency failures. Prepare identical external wheels
for both FT environments before timing. Run two reversed-order blocks, retaining
all failures and samples; check actual worker GIL/JIT state via a pyperf hook.
Keep NetworkX's worker timeout at 15 seconds and bound its complete process
tree at 180 seconds. Parallel workloads retain a shared multiple-CPU affinity.

Implementation: benchmarks/run_pyperformance_compare.sh, the helper and hook in
Tools/benchmarks/, and benchmarks/pyperformance_compare.md. Preparation and
runner validation are in progress; the full timing run is reserved for the user.

Preparation validation: six harness regression tests pass, including rejection
of wrong GIL/JIT/PGO/LTO state, equal weighting of worker means, dependency and
missing-run reporting, immutable input hashing, and killing grandchildren on
timeout. Real pyperf 2.10 JSON loading/multi-result aggregation also passes, and
the hook reports FT=1, GIL=0, JIT=1 on the existing native FT interpreter.
Separate build and runtime environments: PYTHON_GIL=0 cannot be passed to the
ordinary host bootstrap Python. The installed 3.13 again stalled reaping LLVM
children; use PYTHON_FOR_REGEN=/usr/bin/python3.12 as recorded earlier in this
plan. Main now builds successfully; candidate/dependency preparation continues.

Preparation completed for main d95f29589e03 and candidate 20c964a7486c from
committed source archives. Both report cpython-316t, GIL disabled, JIT enabled,
GCC -O3/frame pointers, and explicit PGO/LTO/pydebug disable flags. Artifacts:
jit-artifacts/pyperformance-ft-20260917/. The selected suite has 97 specifications
and 22 dependency groups; 94 specifications are ready. FastAPI's pydantic-core
uses PyO3 with a Python 3.14 maximum, and both SQLAlchemy specifications require
greenlet code referring to the removed FRAME_OWNED_BY_CSTACK. These three
dependency failures remain explicit in suite.json, not silently excluded.

Reuse pure-Python wheels to avoid obsolete packaging backends (observed with
cloudpickle/flit), while native dependencies are source-built with shared flags
and the same wheels installed on both sides. Preserve the previous failed
preparation and its logs. Seven harness tests pass, including actual pyperf JSON
roundtrips, multi-result aggregation and corruption detection; Ruff, shell
syntax and diff checks pass. The final end-to-end runner validation uses base64
and json_dumps, both binaries and two reversed blocks: all eight commands pass,
with worker runtime metadata and pre/post identities verified. It is stored
separately in runner-validation-v2 and is not a performance comparison. The
first validation exposed a symlinked-venv path comparison issue; retain it too.
The runner now compares canonical venv directories and checks each venv binary
hash against its intended build.

Before finalizing identities.json, verified that both builds, stdlib trees,
workload files and all prepared dependency trees are unchanged. No full timing
run has started. Next action belongs to the user: execute
benchmarks/run_pyperformance_compare.sh --run-only
jit-artifacts/pyperformance-ft-20260917. It records all outcomes and writes
compare.md; an exit status of 1 is expected while any specification remains
unavailable or fails. No runtime implementation changes, commits, pushes,
GitHub posts or PR edits were made for this preparation task.

## 2026-09-17: User-run free-threaded pyperformance results

The user completed the full run. Analyze the saved data without rebuilding,
rerunning benchmarks or profiling. The runner finished all 376 scheduled
commands and verified post-run identities. A separate read-only verification
also confirms that binaries, extensions, stdlib, dependencies, workloads and
the frozen runner still match their recorded identities. Verify every saved
JSON hash and reproduce the original 105 result aggregates from raw values.

The original compare.md contains 83 complete specifications / 105 results,
with a candidate/main runtime geometric mean of 0.933551 (6.64% reduction).
The two startup specifications actually completed successfully: our collector
incorrectly required python_executable metadata for bench_command, which uses
command instead. Audit all eight raw command results, executable paths,
arguments, runtime metadata and measured workers, then supplement the analysis
without changing state.json, raw JSON or the original comparison. Startup
ratios are 1.001232 and 1.001814. Their hook checks the measuring interpreter,
not the internal state of each spawned startup child; retain this limitation.

The supplemented comparison covers 85 of 97 specifications / 107 results.
Its geometric mean is 0.934779: 6.52% less elapsed time, about 1.070x speed.
There are 23 results with >=10% reduction, 37 with 2--10% reduction, 41 within
2%, and six with >2% increases. These are descriptive effect bands, not
significance tests. The median ratio is 0.974896. Improvements include
spectral_norm (-64.52%), richards (-42.14%), nbody (-40.72%), html5lib (-15.03%),
go (-13.94%), Mako (-11.80%) and Chameleon (-10.80%). Excluding six names
overlapping earlier standalone targets gives 0.948056, but this post-hoc
sensitivity check is not an independent holdout evaluation.

The largest regression is unpack_sequence: 1.361553 (+36.16%), with both
ordering blocks regressing (1.3775 / 1.3458). Its cause remains unprofiled.
Other >2% increases are deepcopy_reduce (+5.34%), regex_dna (+3.45%), regex_v8
(+3.41%), asyncio_tcp (+3.33%) and generators (+3.00%). Two blocks and the
pyperf stability warnings do not justify narrow confidence claims.

Twelve specifications remain incomplete. Distinguish dependency/API failures,
our missing pip/distutils compatibility preparation, port 8001 already in use,
and NetworkX's retained 15-second worker timeout from performance regressions.
Both SQLAlchemy workloads remain unavailable because greenlet fails to build.
Candidate tornado_http (both blocks) and concurrent_imap (one block) fail the
hook's final JIT-enabled check, rather than crashing. Python/pystate.c disables
FT JIT and invalidates executors when a second thread state joins, and can
re-enable JIT on returning to a single thread state. The observations are
consistent with this safety guard; no transition timeline was recorded and
no parallel specification supplies a complete paired comparison. Before/after
hooks do not prove uninterrupted JIT operation during the measured interval.

Evidence and the Japanese report are in
jit-artifacts/pyperformance-ft-20260917/{summary.md,ratios.csv,analysis.json,
summarize_results.py}. Both branches used FT, JIT enabled, -O3, no PGO/LTO;
these results must not be substituted for the earlier GIL standalone goal.
The comparison shows broader improvements, but does not establish a 20%
suite-wide gain or a 10% gain for every benchmark. Without a JIT-off control,
attribute the result to the branch, not solely to method JIT.

Next proposed work: diagnose unpack_sequence; address the multiple-thread JIT
restriction; fix startup/vendor/compatibility preparation for future runs;
then investigate the smaller regressions and mostly unchanged workloads.
This analysis task changes neither runtime implementation nor the frozen
runner, and performs no commit, push, GitHub post or PR edit.

## 2026-09-17: GIL-enabled PGO/full-LTO comparison preparation

The user requests another full pyperformance comparison, this time with the
ordinary GIL build and PGO plus LTO enabled. Prepare committed local main and
HEAD in a new directory, jit-artifacts/pyperformance-gil-pgo-lto-20260917; leave
the full timing run to the user. Both sides retain native JIT, GCC -O3 and
frame pointers. Main keeps only the documented LLVM 21 reachability patch.

Add a gil-pgo-lto profile and a dedicated shell entry point. Use the standard
PGO test selection with random seed 0, JIT disabled during training, and a
private cold pycache prefix with bytecode writes disabled. Preserve build logs
and per-build GCC profile hashes. This is one fixed independently trained
binary per branch, not a measurement of variance across rebuilds.

Fix command-based pyperf metadata validation for startup/2to3 and install the
vendored lib2to3 plus pinned setuptools before timing, so legacy distutils users
can import and benchmark execution does not install dependencies. Preserve the
previous FT runner under its experiment's frozen-runner/ directory, matching
the original recorded source hashes. No previous raw data or identities change.

Initial harness validation passes eight tests; one real-pyperf roundtrip test
requires the prepared controller. Build/dependency preparation and end-to-end
validation are in progress. NetworkX keeps its 15-second worker timeout.

The first main PGO training attempt fails test_re because the sandbox prohibits
the multiprocessing forkserver's socket bind. Preserve that log and all its
profiles; do not accept incomplete training. Split profile generation, training
and final linking into explicit stages. Before training either side, move all
bootstrap or failed-attempt .gcda files to an archival directory so they cannot
accumulate into the successful training. Resume preparation with the required
ordinary socket/network permissions. All nine harness tests, including real
pyperf roundtrips, pass; Ruff and shell/diff checks also pass.

Main's ordinary-permission PGO training passes all 43 selected test files
(10,468 tests, 460 skips), and its final build confirms GIL=1, JIT=1,
-fprofile-use/-fprofile-correction and GCC full LTO. Its binary SHA is
dd63a277fd879d2f0993655c0502ee26f98bf37656890ae30fdeedb734287c49.
The candidate build is underway. All 84 source files in the selected training
test modules are byte-identical between the two commits; save training-corpus.json
and representative parser/compiler profile-counter dumps. _decimal and _tkinter
are unavailable in this host configuration; record the Python Decimal fallback
explicitly rather than presenting it as the native backend.

Candidate PGO training also passes 43/43 files (10,468 tests, 460 skips), in
the same recorded order as main. Representative GCC parser/compiler profiles
have matching function/counter counts, but aggregate arc counts differ by
about 0.7--0.8%; do not claim identical executed training work from matching
test sources and seeds. Retain both raw counter dumps and training-validation.json.
The final candidate PGO/LTO link and dependency preparation are still pending.

Preparation complete. Candidate's final SHA is
bdf6485883f352519b20ba77efbb7674bef4ae30e8be4be94f021cbaf09497e4;
both builds verify GIL=1/JIT=1, actual PGO/full-LTO flags and frame pointers
in representative native functions. All 97 specifications remain selected;
94 have installed dependencies across 23 groups. FastAPI and both SQLAlchemy
specifications retain their Python 3.16 dependency build errors. Untimed checks
confirm Django/SymPy imports now work with the distutils compatibility package;
Dask/cloudpickle still fails on DELETE_GLOBAL and Genshi expression compilation
still fails on ast.Expression's required body argument. Preserve these results
in preflight.json and logs instead of dropping the specifications.

The actual prepared PGO/LTO controller passes all nine harness tests. End-to-end
runner validation covers 2to3, base64 and both startup specifications on both
binaries in two reversed blocks: all 16 commands pass, with runtime metadata,
result parsing and pre/post identity checks. Its 1-worker/1-value data is only
validation, saved separately in runner-validation/, not a speed comparison.
A final --prepare-only reuse verifies the frozen preparation without rebuilding.
Ruff, shell syntax and git diff --check pass. Main and candidate PGO/profile
artifacts, backend inventory, compiler identities and frozen runner copies are
preserved. The Japanese preparation report is preparation.md in the new output
directory; benchmarks/pyperformance_compare.md documents both profiles.

The full timing run remains unstarted (no top-level state.json). User command:
benchmarks/run_pyperformance_gil_pgo_lto.sh --run-only
jit-artifacts/pyperformance-gil-pgo-lto-20260917.
No runtime implementation changes, commits, pushes, GitHub posts or PR edits.

## 2026-09-17: GIL/PGO/full-LTO user-run results

The user completed the full comparison. Analyze saved data only: no rebuild,
benchmark rerun or profiling. All 376 scheduled commands finished: 360 succeed,
12 fail and four reach the NetworkX worker timeout. Three specifications have
dependency preparation failures. Ninety of 97 specifications / 116 results
have complete main/candidate data in both blocks.

The runtime geometric mean is 1.026787: candidate takes 2.68% longer than main.
The two block geometric means are 1.025716 and 1.027859. Seventeen results
improve by >=2%, 45 are within 2%, and 54 regress by >=2%; only four improve by
>=10%. These are descriptive bands, not significance tests. The median ratio
is 1.014633; equal weighting of specifications gives 1.022469.

Improvements remain for spectral_norm (-44.94%), hexiom (-12.77%), raytrace
(-11.51%), BPE (-11.41%), deltablue (-7.87%) and go (-6.62%). Major regressions
include richards_super (+49.31%), richards (+41.57%), logging_format (+20.17%),
pprint_safe_repr (+18.20%) and deepcopy_memo (+17.28%). Both Richards results
regress in both ordering blocks with worker-mean CVs around 0.3--1.2%; these
large differences merit investigation. Their causes remain unprofiled.

bench_mp_pool averages +59.78% but is highly variable (block ratios 1.4763 /
1.7293, worker-mean CVs 44.9% / 31.4%). Keep it in the primary aggregate.
The post-hoc aggregate without it still regresses by 2.28%, so the suite-level
direction is not solely due to this unstable result. Telco uses Python Decimal
because both builds lack _decimal; excluding it still gives 1.025659.

On the 107 results common with the earlier FT/no-PGO/no-LTO experiment, the
branch ratio changes from 0.934779 to 1.023079. Thus the larger completed set
does not explain the reversal. Richards changes from a large gain to a large
regression, while the previous unpack_sequence regression disappears (0.9991).
GIL and PGO/LTO changed together, with some dependency preparation changes too;
do not attribute the reversal to PGO alone. Neither experiment has a JIT-off
control or independent replicate builds.

Remaining failures: port 8001 occupied for asyncio_websockets; cloudpickle's
DELETE_GLOBAL incompatibility for Dask; Genshi's required ast.Expression body;
NetworkX k_core's retained 15-second timeout; PyO3's Python-version limit for
FastAPI; greenlet's removed FRAME_OWNED_BY_CSTACK reference for both SQLAlchemy
specifications. 2to3, Django, SymPy, tornado_http and concurrent_imap now complete.

Verify every saved JSON SHA, all accepted workers' GIL/JIT states, executable
paths, worker/value/warmup counts and means against raw data. All 116 aggregates
match the original runner. Recheck current binaries, extensions, stdlib,
dependencies, workloads and runner against frozen identities: all match.
Recompute the previous common FT ratios from their raw data as well. Retain
pyperf warnings (42 main / 45 candidate results) and the two-block limitation.

Save summary.md, ratios.csv, compare_ft.csv, analysis.json and the reproducible
summarize_results.py under jit-artifacts/pyperformance-gil-pgo-lto-20260917/;
preserve original compare.md, state.json and raw results. The analysis script
passes Ruff and git diff --check is clean. Suggested next investigation is the
Richards regression, with a GIL/no-PGO/no-LTO control to separate build factors,
then logging/deepcopy/pprint. This turn performs analysis only, with no runtime
or runner changes, commits, pushes, GitHub posts or PR edits.

## 2026-09-17: Richards Super regression investigation

The user requests diagnosis and a JIT improvement. Preserve the completed
pyperformance experiments and use a new richards-super-20260917 artifact tree.
The fixed-work driver imports the unmodified pyperformance implementation,
checks its return value and final counters, and uses identical iteration counts.
Two reversed screening blocks reproduce the regression in both configurations:
PGO/LTO main about 13.0ms versus candidate 17.6ms; no-PGO/no-LTO main about
13.5ms versus candidate 18.7ms. These exploratory timings include identical
warmup/iteration growth and are not substitutes for the original pyperf data.
The regression is not exclusive to PGO. Next inspect generated method/loop
executors and profile fixed work before deciding on a runtime change.

Fixed-work perf (300 iterations, CPU 2, cpu_core/cycles/u, FP call graphs)
records no lost samples. Candidate spends more cycles in type/attribute/super
lookup; main's trace optimizer folds super lookup, whereas candidate methods
retain _LOAD_SUPER_ATTR_METHOD. JIT-off controls instead slightly favor the
candidate (about 28.7ms versus 29.8ms), localizing this regression to JIT paths.
The main trace crosses Task.runTask into subclass fn; the candidate loop ends
at the runTask method entry because its 130 code units exceed the 128-unit
tracing boundary. Attribute inline caches inflate that size without executing
instructions. An ablation removing the boundary/invalidation screens at 15.0ms
versus the frozen pre-change 18.7ms (no PGO/LTO); it remains slower than main.
This is exploratory evidence, not the final performance comparison.

Implement a focused alternative: retain the CFG inliner's existing budget,
but decide trace-through eligibility from decoded instruction count (128),
excluding cache storage. Store the decision before publishing the executor;
use it consistently for ENTER_EXECUTOR and invalidating older caller traces.
Retain the existing 40-addition long-method boundary test and add a short,
attribute-heavy callee regression: both existing and newly generated caller
traces must inline, while method entry, changed values and TypeError still
work. Build and validate this version before selecting it; then compare both
Richards variants and the previous standalone workloads. Preserve all frozen
experiment executables and original pyperformance results.

The instruction-count variant passes the new regression and existing large
callee boundary test. The new test fails on the frozen pre-change executable
because installing the callee invalidates an already useful caller trace.
GIL native/debug and FT debug each pass 1,346 JIT, monitoring, tracing,
generator, coroutine and call tests (five/six expected skips). FT native is
building. No ownership/arithmetic operation or workload is changed.

Two reversed no-PGO screening blocks give richards_super main 13.53/13.69ms,
before 18.85/19.00ms, after 14.60/14.64ms; richards main 12.19/12.26ms,
before 16.75/16.76ms, after 12.83/12.82ms. All outputs/counters check out.
These are fixed-work exploratory results with ten warmup iterations, five
values of ten iterations, fresh processes and CPU 2. Preserve the raw samples
and binaries. The residual main gap remains; do not claim it is eliminated.

Prepare an isolated PGO/full-LTO candidate from HEAD plus the five runtime/test
files, leaving the previous PGO experiment untouched. Use the original GCC/FP
configure flags and standard --pgo training, JIT disabled, seed zero, private
cold pycache, and isolate bootstrap profiles before training. PGO is needed
here specifically to validate the reported optimized-build regression. Final
measurements will start only after all builds/tests stop, compare the original
pyperformance Richards workloads, and screen the existing standalone cohort.

FT native also passes all 1,346 related tests (six skips), completing validation
in all four configurations. Preserve the expected failing new-test-before.log
as evidence that the regression test distinguishes the old policy. Static
inspection counts Task.runTask at 130 code units but only 36 instructions;
Device/Idle/Work fn likewise have 55/69/82 instructions despite their cache-
expanded sizes. The helper profile alone does not explain every excess cycle.

The final PGO comparison protocol is fixed before timing: original unmodified
richards and richards_super scripts, main/before/after in three rotating order
blocks, four fresh workers per variant/block, five warmups and five measured
values with eight loops (matching the original experiment's loop count), CPU 2.
Use the runtime-checking pyperf hook, verify worker GIL/JIT state and exact
counts, and retain warnings/raw results. Report geometric means of block ratios
and log-ratio t intervals over the three blocks; these do not cover build/CPU
variation. No outlier removal or early success stopping. Then screen all eight
standalone workloads against the frozen pre-change no-PGO binary with two
reversed blocks, three warmups and five values. The full pyperformance suite
is not being rerun for this focused change.

The first PGO training attempt fails solely in test_re's forkserver startup:
AF_UNIX listener.bind raises PermissionError under the sandbox. It runs 10,468
tests with 460 skips, but is not accepted as training data. Preserve its log
and move all .gcda files and any private pycache into the failed-training
artifact directories. Re-run the identical 43-file standard training under
approved sandbox escalation, then perform the PGO/LTO rebuild. Do not skip the
failed test or mix its profiles with the successful retry. finish_pgo.py and
pgo-retry-progress.log record this recovery. Performance timing remains paused.

PGO training retry succeeds with the same 10,468 tests / 460 skips as the
original experiment. The final private PGO/full-LTO binary SHA is
cf8599235cf221e63aa750218f6daf07a1d7a0ddb7f3dc3128dbaac1fa6ed6a1.
It also passes the 1,346 related tests and the fixed-work Richards output checks.
The private source snapshot still matches the five validated working files.

The two-block no-PGO standalone screen completes all 32 runs with hashes and
checksums verified. After/before ratios: BPE 1.0029, btree 1.0598, deltablue
0.9990, go 1.0022, hexiom 1.0014, raytrace 0.9996, spectral_norm 0.9988,
SQLAlchemy 0.9947. Btree regresses in both blocks (1.0613/1.0582): this is a
material tradeoff, not noise to omit or a claim of universal improvement.
Seven other point estimates remain within 0.6% of before, with only two blocks.
The original pyperformance Richards comparison is now running without build,
test, profiler or other benchmark overlap. Final report must include the btree
regression and the residual main gap, not only Richards improvements.

Final PGO/LTO comparison completes all 18 commands / 72 timed workers. All
binary/extension/dependency/workload identities match before and after; runtime
hooks confirm GIL=1, JIT=1, non-FT, CPU 2 and the declared loop/value/warmup
counts. Recompute each saved JSON SHA and worker mean from raw data: all match.
The three-block geometric after/before ratios are richards_super 0.720512
(95% block-log t interval 0.704350--0.737044) and richards 0.723878
(0.667661--0.784829). Mean times are 19.399ms -> 13.977ms for richards_super
and 16.896ms -> 12.225ms for richards. Main averages 13.028ms / 11.672ms.
After/main ratios remain 1.072811 and 1.047437: the regression is reduced,
not eliminated. Nine of 18 results retain pyperf stability warnings; before
richards worker means vary 16.18--20.00ms (CV 6.84%). Keep every worker.
Richards_super CVs are main 1.23%, before 0.82%, after 0.31%. This is a
fixed-build comparison, not a claim about independent rebuilds or the suite.

After timing stops, repeat the fixed-work native profile with the original
300 measured iterations + 10 warmups and identical perf event/period. No lost
samples. Cycles fall from 11.424 to 9.058 billion (20.7%); type lookup self share
4.47% -> 2.39%, instance attribute lookup 2.49% -> 1.13%, super lookup 2.21% ->
about 0.01%. These measurements use the diagnostic driver, not the pyperf timing
protocol, and retain the anonymous-JIT-symbol limitation. They support the
cross-function optimization explanation, without assigning every saved cycle.

Record the implementation, original-policy reproducer, four configuration
validations plus final PGO validation, primary comparison/intervals/warnings,
no-PGO cohort regression, binaries and artifact paths in
benchmarks/richards_super_report.md. Keep this as a local JIT improvement with
an explicit btree tradeoff; do not claim all eight improve or that the earlier
main-relative ten-percent goal has been revalidated. Next work is to profile
btree's newly traceable callees (including loops) to refine boundary selection,
and inspect the remaining Richards method guards/polymorphic exits. No new
runtime edits are made after the validated/frozen snapshot. No commit, push,
GitHub post or PR change is performed. Preserve the user's go.py mode change.

## 2026-09-17: Continue Richards Super and B-tree optimization

The user explicitly requests committing the current JIT change, then continuing
until richards_super and btree are each faster than the frozen main baseline.
Commit the focused runtime change, both generated evaluation-loop headers,
regression test, report and progress log; preserve unrelated working changes
and all existing frozen binaries. No push, GitHub post or PR edit is authorized.
Use richards-btree-20260917 for new experiments. Iterate with GIL/no-PGO/no-LTO
builds, retaining FT correctness checks, and validate the final candidate with
the GIL/PGO/full-LTO configuration that exposed Richards Super's regression.
Measure btree against main directly (the preceding 6% loss was against the
older candidate, not main). Keep workload/input/output checks unchanged.

Committed the preceding change as c2def12a37e. The generated-case test suite
also passes all 102 tests. A direct two-block PGO comparison of standalone
btree confirms the current candidate is already faster than main (roughly
49ms versus 57ms); the earlier 6% regression used an older candidate baseline.

Inspecting method translation reveals both root and inlined CFG compilation
emit _CHECK_PERIODIC before JUMP_FORWARD as well as backward jumps. Match
normal bytecode semantics: keep checks only for JUMP_BACKWARD, retain the
no-interrupt backward variant, and preserve method-entry/call checks. Add a
branching root/inlined-callee regression and retain the existing short-loop
periodic regression. Screen this C-only change before adding other optimizations.

The forward-jump fix passes the three periodic-check tests. Its two reversed
fixed-work screens show little Richards Super benefit; retain it for matching
bytecode semantics, without claiming it closes the main gap. The first test
body was too small (the bytecode optimizer duplicated its tail and removed
JUMP_FORWARD); a larger shared tail now tests the intended CFG edge.

A named-executor native profile identifies repeated None guards and inline-value
checks in the hot cross-function traces. Introduce borrowed-reference None
operations in both trace and method compilation. They discard only references
already proved borrowed, preserve branch side exits, and cannot call finalizers.
Keep ordinary owned-reference tests on the original closing operation. Seven
focused None tests pass, including an owned temporary with an observed finalizer
and both borrowed guard side exits. Two reversed no-PGO screens improve Richards
Super from approximately 14.64ms to 14.34ms, still behind main's 13.54ms.

Next experiment removes repeated managed-inline-value guards for the same
symbol in a trace until an emitted operation can escape. A no-dict store guard
also proves the weaker read guard. Restrict this to GIL builds: another thread
can change inline values in FT. Add regressions for repeated reads, replacing
__dict__, and the same callback changing __dict__ after trace warmup. Artifacts
are in richards-btree-20260917; none of these exploratory timings overlap builds,
correctness tests, or profiling. Final correctness and PGO validation remain.

The managed-guard screen gives only a small additional benefit, with substantial
main-process variation (14.94ms then 13.72ms); it is not sufficient evidence that
main has been beaten. Add a GIL-only shared-reference cleanup: an owned local
alias or an existing embedded executor constant proves that closing the stack
reference cannot call a finalizer. Keep the decrement, and fail loudly if the
ownership proof is broken. Tests cover returned aliases, reference counts,
finalizer order, embedded constants and global replacement. The initial full
optimizer run exposes one region-matcher interaction and a cleanup-count
expectation; teach existing length/list regions to accept shared cleanup and
retain the original reference releases. All 460 optimizer tests then pass
(4 skips). The shared-cleanup screen is about 14.15ms versus 14.28ms before;
main again varies by process (15.93ms / 13.63ms), so use the final multi-worker
protocol rather than selecting the favorable main process.

Extend existing integer-attribute update fusion to a receiver already on the
stack, including globals and temporary call results. Preserve that receiver
and its final cleanup after the completed store; guard type, dictionary layout
and exact compact integers before any mutation. This retains the existing
fallbacks and arithmetic error location. Tests will cover integer boundaries,
float fallback, dictionary replacement and a temporary receiver whose finalizer
observes the new value. This targets ordinary attribute counters, not benchmark
names or inputs. Final configuration matrix and PGO comparison remain pending.

Integer attribute fusion needs the BINARY_OP annotation to take precedence over
an earlier saved LOAD_ATTR IP. The temporary-receiver regression exposed that
missed match; fix it and keep both failure logs. Extend the guarded region to
reuse an exact compact integer only when the field has the sole reference,
excluding cached small integers and representation overflow. Test aliases,
compact boundaries, large-int/float fallback, and finalizer order. Mark the
sign/digit-count setter as non-escaping in the case generator; it only writes
integer representation fields. All 462 optimizer tests pass (4 skips).

A further borrowed-owner store-fusion experiment passes correctness tests but
regresses Richards Super (~14.02ms versus reuse's 13.86ms in two reversed
blocks). Reject that experiment and restore the unfused stores. Preserve its
binaries/results. The accepted runtime is the reuse2 candidate, approximately
1% behind the faster main processes without PGO. Freeze that source and run the
full correctness matrix and original PGO/full-LTO build before judging the
requested main comparison. A six-block/four-worker protocol (all permutations
of main, c2def-before, after) is prepared for both Richards Super and standalone
B-tree; its outcome is not yet known.

The frozen accepted source passes all seven related test files in both debug
configurations: 1,458 tests with 5 GIL skips and 11 FT skips. This includes
reference/debug assertions and generated-case tests, not just timing checks.
The native GIL/FT matrix and a private PGO/full-LTO build are in progress. PGO
uses the original standard task, hash seed and compiler flags, with JIT disabled
during training and isolated bootstrap profiles; local IPC is permitted for
the standard test task. No performance measurements run alongside these jobs.

Native GIL and FT also pass the same 1,458-test matrix (5 / 11 skips).
The complete standard PGO training passes 43 files / 10,468 tests (460 skips),
with no failed profiles mixed into the build. The final profile-use/LTO link is
in progress. Working runtime and test hashes match all 12 changed files in the
private source manifest. Final comparisons additionally probe GIL/JIT/debug,
frame-pointer, optimization, PGO and LTO settings for every binary.

The first complete PGO comparison verifies all 36 result files / 144 processes
and all identities. Richards Super: main 12.998ms, c2def-before 13.980ms,
after 13.379ms. After/before improves 4.3%, but after/main is still about 1.0294.
B-tree: main 56.815ms, before 49.481ms, after 48.923ms; after/main 0.86109
(95% block interval 0.85740--0.86479). The target is not achieved yet. Keep all
six blocks and continue; these frozen results belong to the reuse2 source.

A subsequent attempt to remove globals/builtins guards using a symbolic
constant function is rejected by two existing semantic regressions: functions
sharing code/version can have different globals or builtins. The symbolic
optimizer can learn a function constant from a version guard, so this is not
proof of exact function identity. Restore all mapping identity guards; do not
weaken those tests. Preserve the failed logs. Continue with guarded constant
attribute stores, whose type/layout and value proofs are explicit.

Constant attribute stores now fuse an immortal value and a guarded local
receiver. Preserve exactly the type/layout checks that remain in the input;
write only after proving the old value can be closed without calling Python.
Skip the write when the field already holds the constant. Managed dictionaries
retain insertion-order updates. Slot/managed tests cover finalizer order,
deleted fields and replaced dictionaries. All 463 optimizer tests pass. Two
reversed screening blocks improve about 1.2% over reuse2; PGO is still pending.

Splitting exact-call argument binding into known-self/absent-self operations
passes 653 optimizer/call tests, but does not show a reproducible timing gain.
Keep the initial 16.54ms slow process and all six follow-up processes (roughly
13.7--13.9ms); the outlier is not explained by those repetitions. Remove that
split. Try fusing exact-call initialization, saved return offset and frame
entry after symbolic analysis instead. The real Python frame, recursion count,
stack state and instrumentation entry remain present. Initially apply only to
three adjacent tracing operations; method CFG lowering is unchanged. This is
an experiment, not an accepted speedup.

Frame-entry fusion also shows no improvement (~13.84ms versus ~13.81ms), so
remove it. A warmed-up-only perf recording maps all 59 live JIT ranges and
attributes most time to schedule traces and their side traces; the previous
unmapped side traces are now visible. Preserve the perf data, map, binary
images and samples. A fixed inline-values offset prototype passes optimizer
tests but is slower in its short screen, including one 15.99ms process; remove
it rather than retaining an unproved optimization.

The traces still contain generic isinstance calls even when the observed
instance has exactly the constant class being tested. Record the instance type
in CALL_ISINSTANCE, and emit an exact-type guard before folding a witnessed
exact match. Do not assume unrelated types return false: __class__ can invoke
Python or raise. Tuple class sets and custom metaclasses retain existing
behavior. Add fallback tests for subclasses, unrelated objects, __class__
properties and raised exceptions. Validate correctness and screen the change
before another PGO build. None of these exploratory screens replaces the
completed phase-one PGO comparison.

The first isinstance recording prototype crashes during bootstrap: recording
shapes are shared across the CALL family, and a fixed NOS read can dereference
the absent-self NULL marker on a one-argument call. gdb confirms the fault in
that recorder. Replace it with an argument-array recorder that first checks
oparg > 0. Add a regression mixing zero/one-argument, bound-method and builtin
calls. Keep the failed build and debugger output; only a rebuilt and fully
validated candidate can be benchmarked or accepted.

The safe recorder and exact-match isinstance optimization pass all 465
optimizer tests (4 skips). The witnessed-match candidate takes 13.52/13.59ms
in two reversed screening blocks versus main 13.74/13.79ms. Keep the slow
16.87ms const-store process too; do not use it to inflate the claimed gain.
The no-PGO screen is promising, but primary PGO confirmation remains required.

Extend the existing GIL method _LOAD_DEREF_GUARDED operation to tracing.
Successful cell reads cannot invoke Python; empty cells exit without changing
the stack and execute the original unbound-cell error path. FT retains its
existing getter. Add a traced-cell mutation, deletion and repopulation test.
Prepare a separate v2 artifact directory for final source/build identities;
never overwrite or relabel the completed phase-one PGO measurements.

Freeze the phase-two source (constant stores, witnessed isinstance matches,
traced guarded cell reads) for the final matrix. GIL native and debug each pass
all seven files / 1,462 tests (5 skips). The FT builds and private v2 PGO/full-LTO
build run without simultaneous performance measurements. The new report now
separates phase-one measured results from pending phase-two results and records
the rejected experiments and recording-layout failure.

The native FT build also passes all seven files / 1,462 tests (13 skips).
All four correctness configurations are now complete. The private PGO
source matches all 14 changed runtime/test files. Performance timing remains
paused until the full PGO training and final link have completed.

The v2 PGO training completes successfully using the standard task; the
profile-use/LTO build is now running. A separate, untimed executor dump confirms
that the sampled schedule trace contains the new exact-type guard and guarded
cell load, with no generic isinstance call or generic cell load in that trace.
The dump is diagnostic only: its incidental timing is excluded from all
performance comparisons.

The v2 PGO/full-LTO binary is complete, SHA-256
babf6145453655e71b4abc068f5f4a232caed4e7069259cf3821a1039f54d861.
Its JIT-enabled seven-file validation passes 1,462 tests (5 skips), and the
working runtime/test files match the frozen source manifest. The six-block
primary comparison is running with no overlapping builds or tests. Early
blocks suggest Richards around 12.9ms versus main 13.1ms, and B-tree around
48.5ms versus main 57.0ms; retain these as preliminary observations only until
all blocks and the independent worker-file audit complete.

The completed v2 PGO comparison achieves the requested fixed-build target:
Richards Super main 12.990626ms, before 14.014115ms, after 12.902483ms;
after/main geometric ratio 0.993224 (95% block interval 0.989157--0.997309),
after/before 0.920696. B-tree main 56.944422ms, before 49.619643ms,
after 48.539315ms; after/main 0.852399 (0.850716--0.854084),
after/before 0.978237. Both beat main in every block. Preserve all 144 workers,
including slower before samples; all 36 raw files/checksums/identities pass the
independent audit. Richards' 0.68% margin is small and specific to these fixed
GIL/PGO/full-LTO builds. Do not generalize it to FT or the whole suite.

Run a separate reversed two-block screen of all eight standalone workloads
against c2def-before, because these optimizations affect shared JIT paths.
Finish the report with those results and keep benchmarks/go.py's unrelated
executable-bit change outside the implementation commits.

The separate standalone regression screen completes all eight workloads /
32 processes, with identical result checks and verified binary, extension,
workload and dependency identities. Candidate/c2def-before ratios: BPE 0.9922,
B-tree 0.9695, DeltaBlue 0.9858, Go 0.9856, Hexiom 0.9867, raytrace 1.0062,
spectral_norm 0.9962, SQLAlchemy 1.0005. This small screen is not a significance
test; retain raytrace's +0.62% point estimate and SQLAlchemy's flat result.
The larger 24-worker main comparison establishes the requested two-workload
outcome. The implementation and report are complete; no further code change or
performance tuning is needed for this task. Future work can test independent
rebuilds and the full pyperformance suite, rather than inferring those results
from the two targets. Initial changes were committed as c2def12a37e; this
follow-up implementation, tests, generated files and report are included in
this commit at the user's request. The unrelated benchmarks/go.py mode change
is excluded.

## 2026-09-17: Four existing interpreters for full pyperformance

Prepare `benchmarks/run_pyperformance_four_way.sh` to compare main and the
current method-JIT implementation under both FT/no-PGO/no-LTO and
GIL/PGO/full-LTO. Reuse the existing four binaries, including the latest
`build-method-ft-jit/python` and the Richards/B-tree v2 PGO build. Do not
rebuild Python or run the full suite inside the sandbox. Main remains
d95f29589e0 plus the LLVM 21 compatibility patch; the candidate binaries
contain the implementation committed as 15d10bd6f03, although their embedded
version strings predate that commit.

Use the existing comparison runner for balanced main/candidate blocks,
worker runtime checks, process-group timeouts, immutable results and identity
verification. Prepare both configurations before timing; continue to the GIL
comparison even if FT benchmarks fail. Keep the networkx limits of 15 seconds
per worker and 180 seconds per specification invocation. Each configuration
has its own report; the sequential FT/GIL order does not establish a balanced
comparison of FT against GIL. Add a wrapper, an offline preparation driver,
Japanese usage documentation and focused orchestration/dependency tests.

Reuse the same pure Python wheels and workload files in all four environments,
with native wheels selected for each main build's ABI and shared with its
candidate. Fresh venvs preserve previous experiments. Include setuptools and
vendored lib2to3 in FT as well. Effective flags permit FT's implicit configure
defaults for disabled PGO/LTO; incorrect runtime settings and enabled
optimization flags still fail validation.

The user requested SQLAlchemy without greenlet. Both upstream specifications
use synchronous SQLite APIs. SQLAlchemy 1.4.19 handles the absence of greenlet
and reserves the error for async bridge calls. Install the cached 1.4.19
wheels with `--no-deps`, explicitly recording the omission of greenlet 3.2.4
and retaining the original dependency failure. Require greenlet to be absent,
the requested SQLAlchemy version, and successful C-extension import. Preserve
the benchmark scripts and their default 100-row workload.

Validation so far: 14 harness tests pass, including continuation after a failed
profile, preparation-only behavior, changed input rejection, FT wheel selection,
and the narrowly scoped SQLAlchemy dependency override. The shell syntax check
passes. Short runs of Richards Super, Python startup and 2to3 succeed on all
four interpreters (12 invocations). Separate declarative/imperative SQLAlchemy
runs without greenlet succeed on all four (8 invocations), including worker
GIL/JIT/executable checks and post-run identities. These are functional smoke
tests, not performance evidence. Artifacts are under
`jit-artifacts/pyperformance-four-way-smoke-20260917/` and
`jit-artifacts/pyperformance-four-way-sqlalchemy-smoke-20260917/`.

The final full-suite preparation is complete in
`jit-artifacts/pyperformance-four-way-current/`: each profile has 96 runnable
specifications out of 97, with only FastAPI unavailable, and 22 dependency
environment pairs (88 venvs total). Both SQLAlchemy specifications are ready
without greenlet in every interpreter. A second preparation-only invocation
successfully reuses and verifies every binary, extension, standard library,
dependency, workload and harness identity. The current 14 changed runtime/test/
generated source files match the candidate PGO source manifest. The full suite
has not started; neither profile has a measurement state file. Preserve the
preparation, verification and 14-test logs in the output directory.

Hand off the following command from the repository root:

```sh
./benchmarks/run_pyperformance_four_way.sh jit-artifacts/pyperformance-four-way-current --run-only
```

Results will appear in `ft/compare.md` and `gil-pgo-lto/compare.md`, linked from
the output directory's `compare.md`. FastAPI's retained preparation failure
means the all-specification run returns 1 even if every runnable benchmark
succeeds. Next work is the user's full-suite execution and subsequent result
analysis. No GitHub operations or commits were performed; benchmarks/go.py's
unrelated mode change remains untouched.

## 2026-09-17: Completed four-build pyperformance analysis

The user completed the full run. Analyze the saved results without rebuilding,
rerunning benchmarks, changing runtime/harness code or changing the measurement
protocol. The Japanese report is `benchmarks/pyperformance_four_way_report.md`;
reproducible auditing code, detailed JSON and CSV are in
`jit-artifacts/pyperformance-four-way-current/`.

Both profiles finished and passed their post-run identity checks. Repeat the
preparation-only verification successfully, then audit all 732 raw JSON hashes.
For all 730 successful invocations, independently recompute the state means and
verify actual worker executable, GIL/JIT metadata, six workers and five measured
values per result. Two FT concurrent_imap partial JSONs remain excluded from
the complete-specification comparison, but their hashes are also verified.

FT completes 90/97 specifications and 115 result comparisons. The geometric
candidate/main execution-time ratio is 0.9240197569 (7.60% shorter). Seventy
results improve by at least 2%, 35 lie inside +/-2%, and ten regress by at least
2%. Main improvements include spectral_norm (-64.78%), richards_super (-61.67%),
richards (-61.01%), nbody (-40.87%), scimark_lu (-29.14%), float (-23.44%),
unpickle_pure_python (-22.49%), pyflate (-19.79%) and SQLAlchemy imperative
(-18.86%). The largest unresolved regression is unpack_sequence (+36.22%),
consistent with the older FT run. Other regressions include deepcopy_reduce
(+5.43%), asyncio_tcp (+4.69%), sympy_sum (+4.48%) and SQLAlchemy declarative
(+2.83%).

GIL/PGO/full-LTO completes 91/97 specifications and 116 result comparisons.
The ratio is 1.0104583207 (1.05% longer), with 20 results improving at least 2%,
50 inside +/-2%, and 46 regressing at least 2%. Improvements include spectral_norm
(-44.96%), BPE (-13.09%), Hexiom (-13.00%), raytrace (-10.77%), DeltaBlue
(-10.11%), SQLAlchemy imperative (-10.04%), declarative (-8.40%) and Go (-8.22%).
Richards Super is only 0.42% shorter; btree is absent from this selection and
cannot be assessed with this run. The large regressions include pprint_pformat
(+18.37%), pprint_safe_repr (+18.00%), logging_format (+16.85%), deepcopy_memo
(+16.80%), pickle_pure_python (+14.65%), telco (+14.15%), logging_simple
(+13.83%), async I/O variants (+11--13%) and base64_small (+11.32%).

All >=2% regressions have the same direction in both reversed-order blocks;
worker-median sensitivity also retains their regression direction. The same
115-result intersection yields FT 0.924020 and GIL 1.010309. Equal-specification
weighting and removing spectral_norm as sensitivity checks do not reverse the
overall direction. Save 10,000-replicate worker bootstrap intervals stratified
by fixed block/interpreter (seed 20260917); these are conditional on the two
observed blocks, without rebuild/hardware uncertainty or multiplicity correction.
Do not call the +/-2% categories statistical significance or equivalence tests.
FT connected_components (-2.31%) is an example whose interval crosses one.

Failures matter separately: FT candidate concurrent_imap and tornado_http fail
the final JIT-enabled hook in both blocks while main passes. This is consistent
with the existing second-thread JIT suspension in pystate.c; no thread-state
timeline was recorded. GIL candidate concurrent_imap times out after 60 seconds
in both blocks while main passes, so investigate it independently instead of
assigning a speed ratio or assuming the same cause. Shared failures are port
8001 contention (websockets), cloudpickle's removed DELETE_GLOBAL assumption
(dask), obsolete AST construction (Genshi), NetworkX k-core's retained short
timeout, and the prior FastAPI dependency failure. Both SQLAlchemy benchmarks
finish on all four builds without greenlet.

The base64, pprint, copy and logging Python sources are byte-identical across
the four source trees. Their regression causes remain unprofiled; this run
does not separate JIT changes, other runtime changes, PGO or code layout.
There is no JIT-off control, and the FT/GIL profiles also change PGO/LTO, so
attribute the observed differences to these fixed branch builds only.

Next recommended work: resolve candidate-only concurrency failures/constraints,
investigate FT unpack_sequence, then profile GIL pprint/deepcopy/logging while
preserving the measured improvements. This analysis task is complete; no runtime
changes, benchmark reruns, commit, push or GitHub actions were performed.

## 2026-09-17: Fix failed workloads, then eliminate observed regressions

The user now authorizes runtime and benchmark-environment fixes, followed by
investigation and removal of the measured regressions. Preserve the completed
four-way raw results and old PGO binaries. Use normal no-PGO/no-LTO builds for
development; repeat the requested optimized-build comparison only after
targeted correctness and performance checks justify the expensive build.
No GitHub operations or automatic commits are authorized.

Start with a bounded multiprocessing reproducer and fault-handler stacks for
the GIL candidate's concurrent_imap timeout. Local Unix socket creation is
denied by the sandbox, so request execution of this local diagnostic outside
the sandbox with a 28-second timeout. FT's JIT-disable failures must retain the
concurrency safety requirements; do not mask them by removing measurement
checks or claiming fallback timing as an always-enabled JIT comparison.
Also investigate external compatibility failures (cloudpickle/Genshi/FastAPI),
the occupied websocket port and the intentionally limited NetworkX case in a
fresh experiment directory. Then prioritize FT unpack_sequence and the GIL
object-processing regressions, while testing the existing improvements too.
Artifacts and diagnostics: `jit-artifacts/pyperformance-fixes-20260917/`.

Diagnostic update: GIL native candidate Pool repetition can grow from milliseconds
per Pool to 17.6 seconds and time out; JIT-off candidate and JIT-on main finish
100 iterations. The debug Tier 2 interpreter also stalls. A diagnostic build
that disables only method compilation still stalls, so method CFG lowering
alone does not explain it. Both perf and strace perturb timing enough for some
runs to finish; retain these successful diagnostics alongside the timeouts.
A stopped debug process has all Python threads in GIL condition-variable
handoff, one inside glibc __condvar_quiesce_and_switch_g1. The upstream glibc
2.39 lost-wakeup repair removes this wait, but an OS-library cause has not been
established. Do not change global libraries or treat a timing perturbation as a
runtime fix. Module-local monitoring probes did not isolate the cause.

Add strict, recorded compatibility patches for fresh four-way environments:
cloudpickle must tolerate removal of DELETE_GLOBAL; Genshi must provide AST
constructor fields up front (both clone and _new); WebSocket must reserve an
ephemeral localhost port instead of using occupied port 8001. Cache and completed
results remain unchanged. Dask import and cloudpickle lambda roundtrip already
pass; the first Genshi probe exposed its second constructor helper, now patched.
These are under validation, not yet claimed as resolved benchmark failures.

Compatibility validation (compat-v4): all 5 repaired/clarified specifications
(websockets, concurrent_imap, dask, Genshi, Tornado) complete on all four builds
in a one-worker/one-value/one-warmup smoke run, with before/after identity checks.
These short runs are correctness probes, not performance evidence. Long GIL
Pool repetition is still unresolved. The FT hook now permits suspension only
for explicitly selected threaded workloads, records actual start/end state,
and reports observed fallback separately. It still rejects unexpected JIT-off,
wrong build/GIL state, and all GIL-build JIT suspension. All 19 harness tests pass.
FastAPI's cached PyO3 rejects Python 3.16; do not bypass its ABI/version guard.
NetworkX k-core uses the large Amazon graph and remains subject to the user's
short timeout; do not shrink the workload or extend that limit silently.

Regression diagnosis: a balanced JIT-on/off screen is in progress. FT unpack
currently reproduces about +20% rather than the old +36% with identical binaries;
about +7% remains with JIT disabled. Preserve both experiments. Its trace has
repeated SWAP_FAST/POP_TOP pairs and validity checks/spills for every pair of
stores. Add a guarded batch operation for consecutive local stores, preserving
all original references and the precise deopt point if any old value may invoke
a finalizer. Extend FT no-escape closing only to null/borrowed references and
exact primitive types, never based on a racy shared reference count.
GIL pprint JIT-off main/candidate times agree, whereas main's trace JIT speeds
it up and the candidate's JIT does not. A partial method currently blocks trace
inlining solely because the whole function is large. Restrict that preservation
policy to complete methods, leaving partial methods' short paths traceable.
Both runtime changes are implementation candidates awaiting builds/tests/timings.

GIL failure diagnosis is now narrower and has a working fix. The same unchanged
native binary still stalls in both ABBA trials using a private glibc 2.41,
as well as both system-glibc trials. Thus the glibc-only hypothesis is rejected;
no system libraries were installed/changed. The GIL waiter restarted its entire
5 ms timeout after each signal even when the same I/O thread reacquired the GIL.
A repeatedly ready poll could therefore prevent a drop request indefinitely.
Keep a deadline until switch_number changes, and request a handoff when total
waiting time reaches the interval. With this change the debug JIT completes
three independent 100-Pool repetitions, each previously timing out within 20 s.
Add a subprocess liveness test with a permanently ready poll descriptor.

Debug validation: new finalizer-order, repeated-store-target and partial-method
inlining tests pass; 583 JIT/generator tests pass. With the GIL deadline change,
829 tests pass across threading and those same files; the enclosing command
reported failure only because it also requested the nonexistent test_lock module.
Correct the selection to test_thread: all 36 additional primitive-thread tests
pass. Optimized GIL/FT native and FT debug rebuilds are underway without PGO/LTO.

The normal optimized (no-PGO/no-LTO) GIL candidate now completes concurrent_imap
with the original 6 workers, 5 warmups, 5 values, 0.1-second minimum, all CPUs,
and 60-second worker timeout. Both mp_pool and thread_pool have all six workers
and runtime hook validation. Timing is noisy and this is not a same-PGO
speed comparison; it establishes completion of the previously failing workload.
GIL native validation: 865 tests pass (8 skips). FT debug and FT native each pass
583 JIT/generator tests (12 skips). Balanced no-PGO main/before/after performance
comparisons now cover FT unpack and the main GIL regressions plus retained gains.

Development v1 results (two reverse-order blocks, four worker processes per
side, identical no-PGO settings): pprint_pformat changes from 1.150 to 0.993
times main, pprint_safe_repr 1.159 to 1.001, deepcopy 1.050 to 1.004,
deepcopy_memo 1.175 to 1.049, and base64_small 1.089 to 0.975. Logging still
takes 1.12–1.13 times main and telco 1.059. These are development-build results,
not a replacement for the original PGO comparison. Richards and spectral_norm
remain faster than main, although spectral_norm is 4.6% slower than before.
FT unpack worsens from 35.6 to 43.4 ns (main 29.6 ns): retain the adverse result
and do not accept the generic batch store as a successful optimization. Test
constant-count replicas so LLVM can unroll the guards and stores, then remove
or redesign this optimization if it still loses. The logging native profile
records 10K samples with mapped JIT code; inspect method calls and Tier 1
fallback to explain its remaining lost tracing benefit.

The constant-count store replicas (v2) still take about 43 ns in FT unpack,
and spectral_norm remains slower than the previous implementation. Reject this
form. Replace it with direct sequence-to-local unpacking, removing the temporary
stack slice as well as the separate stores. Batch guards must use exact primitive
types, null or borrowed references: checking each old reference count separately
would be unsound when several locals own the last references to the same object.
Add that alias/finalizer case to the tests. This flaw was found in the uncommitted
experiment; it is not a main-branch bug.

Also turn a partial method's unconditional fallback into an ordinary traceable
side exit. Its unsupported or over-budget continuation currently stays in Tier 1
even after becoming hot; the existing side-exit machinery can compile that
observed path without discarding the method CFG. Add a test checking the hot
continuation link and result/error preservation. These v3 changes await validation.

V3 debug validation now passes all 584 JIT/generator tests (4 skips), including
hot partial-method continuation links, tuple/list finalizer ordering, shared old
references, unpack-length errors and repeated targets. Three initial failures
only expected the old unfused tuple uop; update those assertions to the exact
new fused operation, preserving their type-propagation and non-unique ownership
checks. The GIL handoff test is also placed after the complete existing
test_main_thread body, preserving that test's original thread checks. Native FT
and GIL development builds are running before the next balanced comparison.

V3 passes 584 tests in each of the four debug/native GIL/FT configurations.
Balanced no-PGO results recover pprint (1.007/1.017 times main), deepcopy
(1.013), pickle_pure_python (1.016), and base64_small (0.983); spectral_norm
returns to 0.498, Richards 0.943 and Richards-super 0.985. Logging still takes
1.157–1.173 times main, deepcopy_memo 1.051 and telco 1.079. FT unpack remains
slow at 38.7 ns versus main 29.7 ns and the original candidate 35.6 ns.
GIL unpack is 39.5 ns versus main 43.7 ns and the original candidate 35.2 ns;
do not call this new fusion an accepted improvement yet.

A temporary same-binary switch disabling only method compilation (trace JIT
remains enabled and is verified) restores logging and telco performance and
improves deepcopy_memo. The source and default binary are restored; the switch
exists only in python-method-probe, with its source diff and SHA recorded.
The make-python diagnostic reset pybuilddir.txt to 'none'; restore the existing
extension-directory marker before verification/measurement. No measurements
from the failed import probe are counted.

Next adapt partial methods to observed fallback frequency: keep rarely used
unsupported paths as side traces, but switch a method entry to tracing when
its native execution repeatedly leaves before completing. Use a bounded entry
window and a per-code preference so the frontend cannot repeatedly reinstall
the same ineffective method. Test both rare and frequent fallbacks, including
invalidation and exceptions. Separately, elide an unpack's identical assignments
only when the locals already own those objects (or they are immortal); borrowed
mortal locals must still acquire their original new references. V4 source for
the latter is written but has not yet been regenerated or built.

V4 adaptive fallback passes the JIT suite after correcting its warmup test:
executor detachment deliberately restores RESUME, whose specialization resets
its normal entry counter. A direct probe confirms a trace replaces the invalid
method after that new warmup. Remove the ineffective counter assignment instead
of bypassing RESUME's instrumentation checks; allow both sampling and the normal
warmup in the test. Rare fallback still produces a linked continuation and keeps
the method. Extended debug tests now cover monitoring, frames, GC and threading;
optimized GIL/FT and FT debug builds are in progress without PGO/LTO.

The decimal build audit also matters for interpreting telco: all five compared
interpreters lack _decimal and therefore execute Python's decimal implementation.
The reported telco regression is not evidence of a regression in libmpdec.
The same-binary method-off diagnostic improves logging_format by 14.8%,
logging_simple by 19.0%, deepcopy_memo by 8.8% and telco by 5.2%; logging_silent
is unchanged. Both diagnostic modes keep trace JIT enabled. This motivates the
adaptive policy, but only actual v4 measurements can establish its benefit.

V4 validation: GIL debug/native each pass 1,094 tests (17/18 skips).
FT debug/native each pass 812 tests (26/27 skips), including monitoring, frames
and GC in addition to the JIT/generator suite. No heavy builds overlap the
subsequent balanced measurements. The fixed v4 screen selects FT unpack,
deepcopy and logging, then GIL logging/deepcopy/telco/unpack plus spectral_norm,
Richards and Richards-super to check retained gains. Keep the earlier v1–v3
measurements and their adverse unpack results; do not merge versions.
The original regression selection is frozen in original-regression-selection.json
for the broader follow-up (10 FT specifications, 40 GIL specifications).

V4 targeted measurements are complete with identities verified before/after.
FT after/main: unpack 0.7300 (before 1.2062), deepcopy 0.9674,
deepcopy_memo 0.8103, deepcopy_reduce 1.0038, logging_format 0.8934,
logging_simple 0.8673, logging_silent 0.8995. deepcopy_reduce differs between
blocks, so its average alone is not evidence of equivalence.
GIL no-PGO after/main: logging_format 1.0138 (before 1.1568), logging_simple
1.0014 (before 1.1596), deepcopy 1.0074, deepcopy_memo 1.0399,
deepcopy_reduce 0.9856, telco 1.0257, unpack 0.4960, spectral_norm 0.4959,
Richards-super 0.9723 and Richards 0.9336. Retained gains remain, while memo
and telco still need attention. The raw worker bootstrap intervals are in
v4-{ft,gil}-analysis.json and are conditional on these fixed builds/blocks.

Next run all ten original FT regression specifications in reversed-order
main/after comparisons, without concurrent builds. Then build the candidate
with the original GIL PGO/full-LTO protocol in a new private directory and
validate the original GIL regression selection. This is the necessary final
configuration check; development iterations have used no PGO/LTO.

The broader FT screen completes nine specifications. After/main ratios are
asyncio_tcp 1.0267, deepcopy_reduce 0.9603, docutils 1.0406,
gc_traversal 1.0576, generators 1.0337, regex_dna 1.0391, regex_v8 1.0446,
SQLAlchemy declarative 1.0207 and unpack 0.7301 (memo 0.8183).
These residuals prevent a no-regression claim. SymPy fails in this auxiliary
runner because PYTHONPATH alone does not process setuptools' .pth file providing
distutils; the original venv runner works. Preserve the failed invocations and
rerun SymPy with normal site-directory processing, without changing SymPy.

Before the final PGO build, isolate four representative FT residuals using
same-binary JIT on/off ABBA comparisons and a mode-aware runtime hook. Initial
regex results retain their slowdown with JIT disabled. The main and candidate
_sre object .text sections are byte-identical (SHA 93df642a...c71af), although
linked function addresses differ. This refutes attributing the entire regex
regression to generated JIT code; native layout is a hypothesis to investigate,
not a proven cause or justification to discard these measurements.

The JIT-mode screen verifies worker states and fixed identities. FT regex_dna
is 1.0382 times main with JIT and 1.0369 without; regex_v8 is 1.0429/1.0415.
The candidate's own on/off times are essentially unchanged for both. Generators
is 1.0212 with JIT versus 1.0008 without. Inspection finds a trace containing
six nested SEND_GEN frame entries and guards, then an exit before any body work.
V5 rejects only incomplete generator-delegation prefixes that contain no other
work; full loops and traces reaching useful body operations remain eligible.
A deep delegation-chain test checks results and absence of the useless prefix.
The predicate must ignore recording metadata, which analysis has not removed yet.
GIL debug and FT native each pass 579 optimizer/generator/yield-from tests so far.

To test the native-layout hypothesis, relink the exact same FT v5 object files
at four predeclared .text offsets (0/16/32/48 bytes), preserving all four controls.
Compare both regex workloads in forward/reverse order with JIT disabled and
runtime-state verification. This is a diagnostic experiment, not a policy of
selecting the fastest executable or changing system ASLR settings.

V5 passes all 579 selected optimizer/generator/yield-from tests in all four
GIL/FT debug/native configurations. A 3:3 debug leak check initially reports
allocated blocks for both the new adaptive test and the existing partial-CFG
test. The generator-prefix test passes in isolation. These tests deliberately
disable automatic GC, leaving executor objects in the deferred deletion list.
Use the existing deletion-list cleanup in those two tests; the combined three
cases then pass 3:3 with no reference leaks and block deltas [0, -1, 2].
No runtime collection policy is changed to hide the test result.
SymPy's corrected FT comparison completes all four results: expand 0.8991,
integrate 0.9909, str 0.9764, sum 1.0327 times main. The sum residual remains.

The four-layout diagnostic establishes a native-placement effect: regex_dna
ratios for offsets 0/16/32/48 are 1.0000/1.0409/1.0224/0.9893, and regex_v8
1.0037/1.0433/1.0541/1.0292. Every binary uses identical object files and JIT-off;
both orders complete with verified identities. Do not choose the fastest
layout or attribute this effect to JIT optimization. Continue with the ordinary
v5 build. Its generator screen improves only partly (about 1.027 times main).
The fresh GIL PGO/full-LTO build is now running with the original training and
frame-pointer protocol. The four-way runner's candidate path/provenance and
instructions are updated for this new candidate; its 19 tests pass.

Final review finds one necessary correction to the GIL repair: after sending a
handoff request, reset the deadline so a holder continuing in C does not cause
one-microsecond retry waits. V6 makes that adjustment; debug/native GIL each
pass all 282 thread/threading tests. The already-running PGO training was
stopped at test 29/43; preserve its source diff, instrumented executable and
partial profiles under aborted-v5-pgo. Reuse only unchanged instrumented object
files, recompile the changed GIL source, quarantine all bootstrap profiles and
rerun the entire training with fresh profiles. No cross-source profiles are
used for the final build. Rebuild FT as well to keep source/binary consistency.
The GIL report is M-14: M-13 was already assigned to the earlier ready-counter
bug, and its table entry is restored.

V6's full PGO training ran all 43 files, but test_re's multiprocessing forkserver
failed when the sandbox denied its local socket bind. Preserve and quarantine
that failed run's profiles, and rerun the same complete training outside the
sandbox before profile-use compilation. This is an execution-environment failure,
not evidence of a new runtime regression; no failed training profiles are reused.

The unsandboxed v6 PGO training completes all 43 files (10,468 tests, 460
skips). Profile-use/full-LTO linking is in progress. The current harness passes
19 tests using its existing controller environment; an initial invocation with
system Python lacked pyperf and is retained separately. Freeze v6 for the
original 10 FT and 40 GIL regression specifications, plus ten GIL gain controls.
A read-only deepcopy executor probe finds zero counted unsupported-path misses
in the current sampling window. Its polymorphic callable guards exit through
ordinary side traces, which are not counted by the current adaptive policy.
Do not infer that unsupported-path fallback explains the remaining memo residual;
validate final-config timing before extending the policy.

V6 final GIL PGO/full-LTO build completes with SHA256
876561f96fb3213f9a535684278db15dee93f5ee8d679313738b712741bb86d5.
Its 1,088 selected optimizer/generator/thread/monitoring/frame/GC tests pass
(18 skips). Sequential original-regression comparisons are running, starting
with FT. Preserve all worker values and both order blocks, and do not treat
this smaller validation selection as a rerun of the entire original suite.

V6 FT validation completes all ten specifications (15 results) with matching
binary identities. Ratios after/main: unpack 0.7301, deepcopy/memo/reduce
0.9765/0.8127/0.9675, regex_dna/v8 0.9947/0.9975. Remaining >=2% regressions:
docutils 1.0519, SQLAlchemy declarative 1.0245, SymPy sum 1.0335. Generators is
1.0168; GC traversal is 1.0181 with opposing block ratios 1.0455/0.9915 and an
interval spanning parity. Retain the disagreement instead of calling GC fixed.
GIL PGO validation is now running sequentially. Next diagnose the three FT
residuals with the prepared same-binary JIT-on/off runner. If guard-heavy partial
methods are responsible, consider counting their side exits in the adaptive
policy, rather than only unsupported-path exits. This remains a hypothesis.

V6 GIL PGO/full-LTO validation completes 50 specifications / 75 results with no
failed invocations and verified binary identities. Of 46 original >=2% result
regressions, 22 remain >=2%; xml_etree_iterparse newly exceeds 2% in this screen.
The full selected table is v6-validation-summary.md. These are not all-suite
geomeans and must not be reported as complete regression elimination.
Logging format exposes two worker regimes: about 3.23us versus 3.94us in the
same binary, despite the same calibrated loop count (2048). Keep every worker.
The next JIT-mode diagnostic uses the original 6 worker / 5 warmup / 5 value /
0.1s minimum protocol for logging, deepcopy and scimark_sor, and saves executor
shapes after timing. Other diagnostic specifications retain the smaller screen.
The v7 guard-feedback patch and regression-test snippet are prepared as artifacts
only; no runtime source or frozen binary has changed during v6 measurements.

The final GIL PGO Pool verification succeeds under the original six-worker
protocol in 33 seconds (both outputs, runtime-state checks, unchanged binary).
FT JIT-mode comparisons complete: after/main JIT-on vs JIT-off is docutils
1.0447/1.0080, SQLAlchemy 1.0191/1.0143, SymPy sum 1.0373/0.9975. The candidate's
own JIT on/off is 1.0291/1.0169/1.0507, supporting further JIT investigation.
The GIL diagnostic is aborted because its new executor-dump hook mistakenly ran
at both warmup and value teardown, colliding on filenames and perturbing warmup.
Preserve the failed outputs and initial hook source; do not aggregate them.
The FT diagnostic did not enable dumping and remains valid. Move dumping to
process exit and validate a small run before repeating GIL diagnostics in a new
output set. Production benchmark hooks and completed v6 comparisons are unchanged.

The corrected process-exit dump passes a one-worker logging smoke and records
23 executor snapshots after the benchmark process finishes. Restarted GIL-mode
diagnostics use the new v6-gil-pgo-modes-b prefix; the aborted run is preserved.
The first six-worker block has logging_format near parity and deepcopy_memo
about 2.3% slower, rather than the larger short-screen differences. Await both
blocks. Snapshots confirm that main's deepcopy helpers have inlined loop traces,
while v6 also installs complete method entries containing METHOD_CALL and no
inlining of the large deepcopy callee. A possible subsequent policy is to retain
an existing useful inlined loop when method compilation would reintroduce that
call boundary. Keep this distinct from the prepared partial-method guard-exit
feedback experiment; neither speculative policy has been applied yet.

Further diagnostic reasoning: deepcopy's list/tuple helpers retain closed,
inlined loop traces (PUSH_FRAME plus JUMP_TO_TOP), but their method entries use
METHOD_CALL to the oversized deepcopy function. If guard-exit feedback does not
recover this loss, investigate declining a method that would introduce calls
where an already compiled loop has useful inlining. Restrict such a policy to
actual existing inlined loops and methods still containing METHOD_CALL; do not
blanket-disable methods for every loop or benchmark by name. Preserve improvements
in go/Richards/spectral_norm when evaluating any such policy.

A second adaptive-policy limitation is visible in the source: a syntactically
complete method can repeatedly abandon execution at METHOD_CALL if its callee
has no enterable executor. The current partial_method gate ignores those misses.
Before extending the draft, probe the actual base64 functions for base16
(main gains from JIT while v6 does not) and distinguish unsuccessful complete
callers from useful successful nested method calls. The current b16decode uses
a six-byte membership loop and binascii, not the older regex implementation;
re.search is not part of this workload. A possible extension is feedback for incomplete
methods OR methods with non-inlined METHOD_CALL, retaining zero profiling for
complete call-free/trivial methods. This requires a targeted complete-caller
fallback test and gain controls, not just blanket profiling of all methods.

The process-exit SOR snapshots narrow its call-boundary issue: both main and v6
SOR_execute traces inline five Array2D getters/_idx pairs, but the setters remain
outside that long trace. Main's __setitem__ entry is a trace inlining _idx;
v6's entry is a complete method with METHOD_CALL to _idx. The new unpack-to-local
fusion is absent here (the existing TWO_TUPLE opcode is used), so do not blame
that fusion for the SOR residual. An alternative, simpler cost-policy experiment
is to defer small methods that still contain non-inlined METHOD_CALL to entry
tracing, using the existing METHOD_TRACE_MAX_INSTRUCTIONS boundary. Successful
nested calls can still be slower than traced inlining, so guard feedback alone
may not resolve these cases. Evaluate any such policy separately with gain controls.

V6 diagnostic completion is recorded in v6-modes-analysis.log / *-analysis.json.
The longer GIL protocol gives logging_format 1.0072 and deepcopy_memo 1.0022
relative to main, so the large short-screen differences are not stable estimates.
Remaining JIT-specific losses include base16_small (on 1.0836 / off 0.9814),
SOR (1.0473 / 0.9976), telco (1.0578 / 1.0082), dulwich (1.0568 / 0.9998),
and docutils (1.0275 / 0.9998). Pickle_dict remains slower even JIT-off
(1.0492 / 1.0588), supporting a native-runtime/build contribution.
The base16 probe shows b16encode has a partial method with zero explicit
unsupported-path misses, while b16decode already uses entry/loop traces.

V7 now moves partial-method fallback accounting to actual side exits, covering
ordinary type/call guards as well as METHOD_DEOPT. Unsupported-path exits are
counted once. The new int-to-float short-path test fails on v6 (the stale method
remains valid) and passes with v7. It never takes the large unsupported branch.
GIL debug/native and FT debug optimizer/generator suites pass 580 tests so far;
FT native is rebuilding. No complete-caller or inlined-loop cost policy has been
applied yet. Save all v6 development binaries and source diff before rebuilding.
The four-way runner now rejects differing FT/PGO candidate source versions,
preventing an accidental mixed-version comparison during this work; 20 harness
tests pass. Rebuild final PGO only after development performance checks warrant it.

V7 correctness validation is complete: all four development configurations pass
580 selected tests (4 GIL skips, 12 FT skips). The sequential FT comparison is
running against frozen main and v6, with gain controls. First-block docutils
and SymPy sum show little change; do not infer elimination from feedback alone.
Further base16 inspection finds repeated BUILTINS_IDENTITY checks within one
abstract frame. Frame builtins pointers are immutable for that activation;
an optimizer fact can retain the first check across calls while fresh frames
start unchecked. Prepare this separately from partial-CFG inlining, with tests
for different builtins dictionaries and frame transitions. Main's correctness
bug must not be restored merely to recover its performance.

V7 FT balanced results (v6 / v7, both relative to main): docutils 1.0514 /
1.0480; SymPy sum 1.0426 / 1.0359; SQLAlchemy declarative 1.0304 / 1.0204;
unpack .7323 / .7363; Richards super .3863 / .3909; spectral_norm .3518 / .3539.
The residuals remain. Preserve this neutral/adverse result as well as the useful
correctness/feedback test. No GIL performance claim for v7 alone yet.

V8 removes duplicate builtins identity checks in a trace abstract frame. A fresh
frame resets the fact; the first check is retained, including shared code with a
different builtins dict. The new regression test observes 4 guards and fails on
v7, passes with one guard on v8, and verifies custom builtins still work. All479
GIL optimizer tests pass. Frozen v7 development binaries retained as python-v7;
the v8 GIL base64/telco comparison is running before any further rebuild.

V9 source preparation, not yet built: inline supported paths of a small callee
CFG even when a cold arm is unsupported. Keep the callee frame and emit its
METHOD_DEOPT at that bytecode, require a compiled return, and retain all prior
size/recursion/exception-table restrictions. This targets the observed SOR
setter/_idx boundary without a benchmark-name or blanket method-disable policy.
A test covers cold exception traceback, different argument types, and callee
code invalidation. Complete v8 timing before v9 builds or tests.

V8 no-PGO GIL comparison (all11 base64 results plus telco, both orders, no
failed invocation): base16_small v7/main1.0536 -> v8/main1.0304; telco1.0164 ->
.9908. ASCII85_small moves1.0030 ->1.0226, so retain the adverse observation
and do not equate the source change with every rebuild-sensitive difference.
Both binary identities and shared extension identities verified after measuring.

V9 all four build configurations pass582 tests. One old test specifically
asserted a nested METHOD_CALL for a callee newly eligible for partial inlining;
keep testing actual nested exception propagation by giving it an exception table,
which the inliner still rejects. The new cold-arm test fails on v8, passes on v9,
and checks the callee traceback and invalidation. V9 GIL performance is running;
SOR/deepcopy use6 workers with5 warmups and5 values, others the smaller development
screen. First SOR block improves from v8/main1.0205 to v9/main.9791; await reverse
order and gain controls before drawing a conclusion.

V9 GIL comparison complete, no failed invocations, identities verified. Ratios
v8/main -> v9/main: SOR1.0087 ->.9775 (both full-protocol blocks improve),
deepcopy.9685 ->.9805, deepcopy_reduce.9724 ->.9723, deepcopy_memo1.0376 ->1.0376,
Richards.9677 ->.9700, Richards super1.0025 ->1.0060, spectral_norm.4977 ->.4980,
go.8974 ->.8945. These are no-PGO builds, not the final PGO claim. FT residual
checks now run against v7 and main before another rebuild.

V10 source preparation: include complete methods containing METHOD_CALL in the
same 256-entry fallback-feedback window. They can repeatedly abandon activation
when a callee requires a MAKE_CELL prefix even though their own body is complete.
Rename the VM flag from partial_method to method_feedback to reflect this scope;
complete call-free methods retain no profile uop. A targeted test verifies that
such a caller initially has METHOD_CALL and no METHOD_DEOPT, then invalidates
and prefers entry tracing after repeated call failures. V10 is not built yet.

Do not remove mapping identity checks merely because the optimizer's callable
symbol says constant: CHECK_FUNCTION_VERSION promotes a recorded function to a
constant, but shared code can share the version across different mappings.
The V8 per-frame builtins dedup is safe without weakening the first guard.

V9 FT residual comparison complete: v7/main -> v9/main docutils1.0497 ->1.0504,
SymPy sum1.0372 ->1.0405, SQLAlchemy declarative1.0223 ->1.0178. V9 helps SOR but
not these dynamic workloads. Read-only executor probes precede the V10 rebuild;
FT method_window/misses offsets114/116 were read from that binary's DWARF (GIL
has different offsets98/100). The probes assert the recorded v9 binary SHA.

Report audit: regenerated the early gil-before JIT-mode table from both raw
blocks with equal worker weights. Corrected missing cells and provisional numbers
for deepcopy_memo/logging/telco. This is historical original-binary diagnosis,
not a current-candidate result; preserve the distinction from final v6 and later
no-PGO development comparisons.

V9 read-only probes find185 docutils methods, including83 complete callers
without feedback; SymPy has76 methods,24 complete callers without feedback.
These are executor shapes, not call-frequency or timing measurements. V10's
MAKE_CELL-callee test fails on v9 because no profile uop exists, and passes on
v10; all583 GIL native selected tests pass after adapting test_resume to allow
its recursive method to detach and its replacement entry trace to warm up.
The resume test still checks a real executor with the entry periodic check.
Debug and FT builds are running. The next V10 performance screen is a fixed
v9/v10 candidate-pair comparison (two reversed orders), explicitly NOT a main
comparison, to isolate this policy before final matched-build validation.

V10 FT debug exposed one structural-test interaction: the shared-closure test
made40 calls whose FT closure entry intentionally falls back, enough to trigger
the new32-miss adaptation. Limit this particular identity/invalidation check to
8 pairs (below adaptation), retaining different closures/defaults, mutation and
error checks; the dedicated repeated-fallback tests verify adaptation itself.
FT debug/native validation is continuing. No timing data are discarded for this
expected policy change, and no performance conclusion is drawn from test changes.

V10 validation is complete in all four development configurations:583 selected
tests each, with4 GIL and12 FT skips. Capture the final test-adjusted source diff
and all four binary SHA256 values in v10-development-binaries.json. The FT
candidate-pair timing is running before any further source/build changes.
A possible next FT-specific improvement is allowing the same allocation-free
COPY_FREE_VARS entry prefix already supported in GIL calls, after all recursion,
instrumentation and TLBC guards. This would retain compiled caller continuations
instead of relying on fallback adaptation. Ordinary COPY_FREE_VARS uses exactly
the same tuple-cell acquisition primitive on FT. It needs an FT active-JIT
return assertion and normal closure mutation/refcount/error tests; not applied yet.

V10 is REJECTED. The GIL candidate-pair comparison gives Go1.2312 vs v9 with
both blocks near+23%, while docutils improves only1.4% and most other results
are neutral or slightly worse. GDB at the actual adaptation decision (ASLR
left enabled) identifies EmptySet.random_choice, Board.random_move and Board.move,
all detached at32 entries/32 misses. None is a preserved large method, so merely
excluding large methods would not fix this. Failure rate alone is not an adequate
cost model for complete callers that already perform useful compiled work.
Retain all raw data, v10 source/binary hashes and the GDB log. Restore the v9
partial-only feedback implementation and original structural tests; remove the
experimental complete-caller test along with the rejected policy.

V11 is now v9 PLUS FT COPY_FREE_VARS entry support, not v10 plus that support.
Keep the same recursion/instrumentation/TLBC checks before acquiring cell refs;
MAKE_CELL and extended prefixes still use Tier1. The existing closure-return test
now asserts active JIT execution for FT too, while retaining distinct closures,
wrong types and GIL refcount checks. Save rejected v10 binaries as python-v10,
run the FT assertion against them to establish failure, then rebuild/test all4.
V11 comparisons use v9 as their baseline, avoiding a misleading improvement claim
against the rejected Go regression. No PGO build has been started for v7–v11 yet.

V11 validation:582 selected tests pass in each of the4 configurations. The
expanded FT closure-return assertion fails on frozen v10 and succeeds on v11.
The restored GIL native .text is byte-identical to v9 (3,948,146 bytes,
SHA256764e11a94585b52d41edd06024e4d2b389756625b87894bfd904b9d162022f39).
The FT v11/v9 comparison is running with docutils/SymPy/SQLAlchemy and gain controls.
Do not describe results as improvements over v10, whose Go regression was rejected.

V11 GIL readonly-data audit also matches v9 except4 bytes in the build timestamp;
.text is identical. This independently confirms that the rejected v10 runtime
policy was restored, rather than merely obtaining a favorable timing sample.

Prepare a separate V12 cost policy while frozen v11 FT timing finishes: if a
complete method still contains METHOD_CALL and the code already has a valid
closed loop trace with inlined Python calls (PUSH_FRAME plus JUMP_TO_TOP), defer
to entry tracing. This preserves an observed useful specialization rather than
judging all callers by failure rate. No loop trace, incomplete methods, or fully
inlined methods are unaffected by this check. The test establishes the existing
inlined loop first, warms the function entry, and verifies it is retained without
introducing METHOD_CALL. This targets the deepcopy helper evidence; test gain
controls, especially Go, before accepting. V12 source is prepared, not built.

V11 FT candidate-pair results vs v9: docutils.9939, SymPy sum.9938,
SQLAlchemy1.0003, Richards super.9661, spectral_norm1.0045. The residuals are
not eliminated. V12's new loop-preservation test fails on v11 (METHOD_CALL in
the entry) and succeeds on v12; all583 GIL selected tests pass. Measure the
GIL pair first, with6-worker deepcopy/SOR plus Go/Richards super/docutils controls,
before investing in the remaining builds. Preserve the complete v11 binary set.

V12 GIL pair complete: deepcopy_memo0.9080, deepcopy0.9914, reduce0.9826,
Go1.0211, SOR0.9961, Richards super1.0019, docutils0.9889 versus frozen v11.
Retain the adverse Go result; remaining development builds and FT validation
are next. This is not a final PGO/main comparison.

V12 passes583 selected tests in each of four development builds. FT timing
is running against frozen v11. Prepare V13 as a separate guard-only adaptation
experiment: complete methods count ordinary side exits, but METHOD_CALL failures
still count only for partial methods. The rejected V10 treated both the same.
A complete int-specialized method that repeatedly sees float arguments should
yield to entry tracing. Keep Go and Richards controls, since useful complete
methods must not be indiscriminately discarded. V13 is not built yet.

V12 FT pair complete: deepcopy_memo0.9557, reduce0.9788, deepcopy0.9955;
docutils1.0012, SymPy sum0.9971, SQLAlchemy0.9998, Go1.0104, Richards super1.0003,
spectral_norm0.9961 vs v11. All raw workers and reversed blocks retained.
V13 adds two complementary checks: repeated complete-method type-guard failures
adapt, whereas repeated MAKE_CELL call fallback preserves the complete caller.
The guard-adaptation assertion fails on frozen v12. Build/test all4 next.
Native pickle memo probe simulation on the unchanged MICRO_DICT graph found
806 probes with shift3 versus742 with shift4. This is a single address layout,
not evidence of runtime improvement; no pickle source change is applied.

V13 debug found3 structural-test failures, no wrong runtime results: two
subtests reuse one code object across different types and now trigger adaptation
before their one-warmup executor lookup; give each monomorphic case a fresh code
copy. The resume prefix expectation must include METHOD_PROFILE. Preserve the
initial failure and verbose logs; rerun the changed assertions and full set.

Pickle memo algorithm diagnostic extended to12 fresh processes in each mode:
mean probes GIL850.17 ->692.50, FT813.50 ->671.00 (shift3 ->standard rotate4
for these16-byte-aligned pointers). Keep all addresses/counts in
pickle-memo-probe-restarts.json. This supports a bounded fixed-core extension
comparison, not an attribution of the original PGO regression. Do it after
the V13 JIT pair to keep factors separate; no pickle product change yet.

V13 all585 selected tests pass in each of GIL debug/native and FT debug/native
(4/12 skips). Freeze python-v13 and source diff. Three-worker reversed-order
comparisons against frozen v12 are running: FT docutils/SymPy plus Go/Richards
super/spectral controls, then GIL docutils/Go/Richards/base64/telco/dulwich.
The next pickle experiment will compile a private copy of _pickle.c and vary
only that extension against one fixed core with JIT off; no product mutation
until the fixed-core timing supports the hash change.

V13 FT pair: docutils0.9875, SymPy sum0.9962, Go1.0027, Richards super1.0445,
spectral_norm1.0040 vs v12. Broad profiling of complete leaf methods has a
material cost; the first GIL block also has base32_small+5.6%. Finish the planned
GIL block pair without discarding it. Prepare V14 limiting complete-method guard
feedback to methods retaining nested Python calls. Complete leaf methods keep
ordinary side traces and no entry profile; UINT16_MAX marks their inactive
window, with no executor-layout change. The targeted type-change test now uses
a non-inlined identity callee to check this narrower policy. Not built yet.

V13 GIL pair is neutral on docutils0.9996, Go0.9982, telco0.9999; Richards
super1.0053, dulwich1.0119, base32_small1.0292. The latter differs by block
(first+5.6%, second about+0.3%), so do not equate its mean with a stable cost.
GDB on frozen V13 FT Richards confirms actual complete-method detachments,
including TaskState predicates, Task.fn, Task.runTask and Task.addPacket. The
FT loss may include adaptation decisions as well as entry-counter overhead.
V14 therefore excludes complete leaf methods from both profiling and helper
calls at exits. Finish correctness and compare against V12, not V13.

The private pickle a/b builds have identical .text size (GIL70976, FT76208),
with only18 bytes different in each: exactly9 SAR-by-3 instructions replaced
by equal-length ROR-by-4 instructions at identical offsets. No other .text
instruction or relative placement changed; disassembly diffs are retained.
This controls extension code placement for the forthcoming hash comparison.

V14 passes585 selected tests in each of the4 configurations. The revised
complete-caller test initially had an unwarmed call in the cold branch, making
that caller partial; move its single call after the branch to exercise the
intended complete-caller case. Initial failure log is retained. Freeze V14
binaries/source, then run the V12/V14 pair and fixed-core pickle comparison
sequentially, with no builds during timing.

Reject both V13 and V14 complete-method feedback extensions. V14 FT vs V12
leaves docutils0.9976/SymPy0.9945 but Richards super1.0377 (blocks1.0136/1.0623);
GIL docutils0.9966, Go1.0045, Richards super1.0098, telco1.0030, dulwich1.0101.
Small target gains do not justify these adverse effects. Restore the entire
runtime/test diff byte-for-byte to frozen V12, verified against
v12-runtime-source.diff. Preserve both rejected binary sets and all measurements.
The current development executables are still V14 until the next rebuild; use
frozen python-v12 for residual diagnostics, not the current executable name.

Private pickle test initially failed6 cleanup operations because user site was
visible and read-only in the sandbox, including the pure-Python test variant.
No incorrect serialization result was observed. Disable user site (as the
benchmark runner already does) and repeat with separate logs, then measure.

Accept the small native pickle hash improvement, separate from JIT work:
fixed-core GIL b/a ratios pickle_dict0.9914, pickle_list0.9783, pickle1.0001;
FT pickle_dict1.0000, pickle_list1.0007, pickle0.9933. Unpickle controls are
within about0.5%, so do not overinterpret sub-percent FT differences. Both
configurations pass1,084 pickle tests (57 skips) with the private candidate
extension asserted at import. Replace shift3 with _Py_HashPointerRaw in product
source; this is not enough to claim the original PGO pickle regression fixed.
No rebuild yet, to keep residual profiling on fixed V12 core/extensions.

Residual FT counter diagnostic, two reversed blocks: V12/main docutils
instructions0.9501/cycles1.0419, SymPy sum instructions0.9260/cycles1.0733.
Counts cover whole workload calls (including file reads/cache clears), unlike
pyperf inner timers. Their separately recorded inner-time ratios are1.0445/1.0785;
not interchangeable with pyperf results. The first attempt failed after a
completed count because perf FIFO acknowledgements include a NUL terminator;
retain it but exclude it from the completed pair. Corrected run label ends-b.
Named JIT/native perf samples are next; no system tuning is used.

The four-way runner now requires separate final FT and PGO build records,
including native extensions/configuration hashes, and matching source manifests.
This prevents an old FT binary or stale extension from being called the same
source revision just because the working tree matches the PGO snapshot. Final
records and final PGO build do not exist yet; preparation intentionally fails
until those builds and their validation are complete.

FT baseline audit: main _PyOptimizer_Optimize returns0 unconditionally under
Py_GIL_DISABLED. Both named diagnostic workloads installed0 executors despite
sys._jit.is_enabled()==True. Describe FT as main interpreter versus method JIT;
the frozen baseline flags/binary are unchanged. Enabled metadata alone is not
evidence of compiled execution.

V15 bounded experiment: allow small protected callees to use the same normal
CFG compilation already used for protected method roots. Retain real callee
frames, exception-table block boundaries, and original error instruction
positions; handlers still run through Tier1. Add a structural/runtime test for
caught and propagated exceptions, finally exactly once, and traceback frames.
No timing verdict yet; build only after the sequential counter diagnostics.

Residual FT hardware counters (two reversed blocks, fixed V12/main):
branch misses docutils0.9881 / SymPy1.0747; frontend uops not delivered
1.1815 /1.2041; frontend-retired L1I-miss events1.4523 /1.1411. Cycles remain
1.0276 /1.0720 in the frontend run despite instructions0.9498 /0.9269.
This supports frontend/code-footprint pressure as a contributor, not proof
of one responsible code change. All events ran100%, no system tuning.
Named record holds executor references, asymmetrically0 in main and284/168
in candidate, so its GC cost distribution is diagnostic only.

Harness tests with system Python:16 passed/1 skipped (pyperf unavailable in
that interpreter). Repeat full harness set under the existing controller
with pyperf before final validation. Documentation now distinguishes main
FT enabled flags from actual compilation and points to final build records.

V15 passes584 selected tests (JIT/optimizer/generator/yield-from) in each of
GIL debug/native and FT debug/native. Old V12 fails the new inlining assertion,
while exception results are correct. Frozen python-v15 copies and source diff
are preserved. Run two reversed blocks,3 workers/3 warmups/3 values/.05sec,
V15/V12 first FT(docutils,SymPy sum,SQLAlchemy,Go,Richards super,spectral norm),
then GIL(docutils,Go,Richards super,base64,telco,dulwich,deepcopy,SOR).
The native pickle extension is now rebuilt; both sides in these development
pairs share exactly the same extensions. They isolate the core change, not
the pickle hash improvement. No rebuild or profiler runs during timing.
The existing controller passes all20 harness tests without skips.

V15 FT/V12 pair completed without failures; all before/after binary and shared
extension identities match after measurement. Ratios: docutils0.9960, SymPy
sum0.9985, SQLAlchemy0.9960, Go0.9914, Richards super0.9988, spectral norm1.0017.
Richards' first-block slowdown reverses in block2; preserve both rather than
selecting either. These near-neutral results do not establish the residual
main-relative regressions resolved. GIL pair is now running sequentially.

Code review following frontend counters found another concrete redundancy:
method translation emits a builtins-identity guard for each folded builtin
within one basic block. V8 removed it only in the tracing analyzer. V16 will
retain the first guard per block/frame and remove subsequent identical guards;
frame changes and block boundaries reset the fact. Frame builtins identity is
immutable; executor validity checks/named binding dependencies remain, including
a callback rebinding a global between builtin calls. Add a structural test plus
shared-code/custom-builtins and mid-call invalidation checks. This source-only
edit does not change the frozen V15 binaries in the ongoing GIL pair. Build
and compare only after that pair completes.

V16 also deduplicates identical folded-global mapping/version guards within
the same block/frame. Only exactly matching operand pairs are reused. Each
folded name already has its own invalidation dependency; existing validity
checks after callbacks continue to cover value insertion/rebinding/deletion.
A frame's globals mapping itself cannot change. Test asserts one guard of
each kind and checks rebinding from __len__ before the later folded loads.

V15 GIL/V12 pair completed without failures. docutils0.9980, Go0.9951,
Richards super1.0001, telco1.0036, dulwich0.9831, deepcopy0.9909/reduce0.9920/
memo1.0117, SOR0.9986. Base16_small0.9967; base32_large1.0090; other base64
results0.9849--1.0056. Keep V15 for the protected-call improvement with its
modest dulwich benefit, while retaining the small adverse memo/base32 results.
No broad residual-regression claim. V16 correctness build begins after timing
completes; both debug/native modes preserve V15 snapshots for comparison.

V16 first test fixture failed on both old and new binaries: len itself is not
an immortal folded binding, so it generated0 identity guards. This was a test
assumption failure, not an incorrect runtime result. Use immortal builtin types
list/tuple around an intervening len callback instead. That callback binds a
global list name, checking invalidation before the later folded load. Preserve
initial logs, then verify old/new guard counts and rerun the complete set.

The second V16 fixture constructed a tuple, which took the unsupported path
and adapted away from the method before inspection. Replace it with two
folded list-type loads around len(values); the callback inspects the earlier
local through its real caller frame and rebinds list before the final load.
This directly covers the intended path without unsupported tuple construction.
The new focused debug check passes. Preserve both previous fixture failures.

The final V16 fixture now fails on frozen V15 with2 versus1 builtin guards
and passes on V16, including custom builtins, caller-frame locals inspection,
and rebinding during the compiled call. No runtime source fix was needed
for the two earlier fixture errors. The small independent FT compilation
probe also confirms main reports enabled but installs0 executors, while
frozen V15 installs2 valid loop executors on the identical workload; see
compilation-ft-{main,v15}.json. This probe is separate from timed workloads.

V16 all4 builds now pass585 selected tests each (4 skips GIL,12 skips FT).
Snapshots python-v16 and the source diff are preserved. Compare V16/V15 with
the same two reversed blocks,3 workers,3 warmups,3 values,.05s protocol and
FT/GIL target/control selections as V15. Builds and profilers are stopped.

Final-validation preparation: build_final_pgo.py snapshots all changed runtime
and test sources, including Modules/_pickle.c, into a new final-pgo-src tree.
It keeps the original matched GCC/frame-pointer/PGO-with-JIT-off/full-LTO
protocol and isolated successful profile data. validate_final_builds.py will
run10 files including monitoring/frame/GC/threading/pickle on final GIL PGO
and FT native, then write final-ft-build.json only after success and check
source/binary/extension identity agreement with the final PGO record.
compare_final.py is prepared for both modes, including before/after native
extension/configuration hashes and the original regression/control selection.
None of these final build/validation/comparison scripts has run yet.

V16 FT/V15 pair completed: docutils0.9968, SymPy sum0.9992, SQLAlchemy0.9996,
Go1.0046 (blocks0.9987/1.0106), Richards super0.9983, spectral norm0.9975.
All invocations and identity checks succeeded. The gain is small and does not
prove the remaining main-relative gaps closed. GIL pair now runs with the
same predeclared target/control set; no further source experiments during it.

V16 GIL/V15 pair completed: docutils0.9968, Go1.0020, Richards super1.0075,
telco0.9969, dulwich0.9998, deepcopy1.0102/reduce0.9802/memo0.9953, SOR0.9983.
Base64 result range0.9928--1.0102. Keep the bounded mapping-check elimination
with its structural/correctness proof; the measured benefit is small and the
adverse controls are retained. No claim of main-relative parity from these
development pairs. All identities and invocations passed.

Start the final matched GIL PGO/full-LTO build from the V16 runtime plus the
accepted native pickle hash change. Disk has175GiB available. No benchmarks
or profilers will run during this build. The final source snapshot includes
all current runtime/test edits; original main and V6 PGO binaries remain intact.

Final snapshot verification: all20 changed runtime/test files still match
final-pgo-build.json. Configure completed successfully; profile-generation
build is running. A separate bounded docutils GC diagnostic is prepared but
not run: frozen V16/main, default versus disabled GC, two reversed blocks,
original inputs and separately labelled GC-callback/inner-time data. Use it
only if the final FT docutils gap remains, to separate GC cost from generated
code/frontend pressure without the named-profiler's retained executors. Do
not use disabled-GC timings as official benchmark comparisons or product settings.

PGO training succeeded:43 files,10,468 tests,460 skips,141.4seconds, matching
the original successful training workload. Final full-LTO optimization build
is now running. For the forthcoming final regression/control screen, retain
two reversed blocks and2 workers but use5 warmups,5 values and.1s minimum,
matching the original per-worker warmup/measurement protocol. The original
full run used6 workers; this selected screen is not a full-suite rerun.
This protocol is fixed before inspecting any final-binary timings.

Final GIL PGO/full-LTO build succeeded. SHA256
beb4cea863c62feb8aea145fa3fdb865d2c36b205429d6ad077e09a8df9da8b5.
The final source diff is byte-identical to the frozen V16 source diff, including
the native pickle change. Correctness validation now runs on final GIL PGO and
FT native. Before starting, verify FT core against v16-build-tests.json and all
FT extensions against the completed v16-ft-pair snapshot, so the new provenance
record cannot merely relabel an older binary or modified extension as V16.

Final native correctness validation succeeded in both modes:10 test files
including JIT/optimizer/generators/threading/thread/monitoring/frame/GC/pickle.
GIL PGO:2,178 tests,75 skips. The separate final FT provenance was written only
after its validation; candidate_provenance verifies both cores, configuration
files, native extensions and matching source manifests. Start final4-build
compatibility smoke for asyncio_websockets,dask,genshi,concurrent_imap,tornado_http
in fresh private environments, one block/worker/warmup/value. This is functional
validation, not a performance comparison. Full final regression screens follow.

Final FT correctness count:2,178 tests,90 skips; GIL PGO count2,178/75.
The final four-way compatibility smoke has completed the FT cases successfully;
GIL cases follow in the same fresh-environment run. Preserve their result
timings only as smoke output, not as a speedup estimate.

Final four-way compatibility smoke completed successfully:5 specifications /
7 results in each of4 builds, all20 specification invocations return0, overall
runner return0. Logs/patch identities/runtime suspension metadata are under
compat-final/. FastAPI remains an external unsupported dependency and NetworkX
retains its15s budget; neither was silently substituted in this smoke selection.
Start final-ft original regression/control comparison with the predeclared
2 workers,5 warmups,5 values,.1s minimum and2 reversed blocks.

Final FT screen completed, with all identities verified and no failed
invocations (18 specifications / 23 results, two reversed blocks). Ratios
after/main: unpack0.7011, deepcopy0.9295/reduce0.9646/memo0.7748,
Go0.8810, Richards0.3976/super0.3859, spectral0.3521, regexdna0.9917,
regexv8 1.0093. Remaining regressions: docutils1.0462, SymPy sum1.0515,
SQLAlchemy declarative1.0276, generators1.0288, asyncio_tcp1.0279,
gc_traversal1.0326. These remain unresolved, not rounded into parity.
Start the final GIL PGO/full-LTO screen with the same predeclared protocol.
No heavy build/profiler runs concurrently. Investigation of decorator kwargs
copying is source inspection only: PyDict_Copy can invoke Python for sparse
general-key dictionaries, so globally marking it non-escaping would be unsafe.

V17 proposal (not built or accepted): fuse empty-dictionary plus borrowed
local merge/update to a direct copy, but only for exact dictionaries with
exact Unicode keys. A helper checks key-table kind under the same FT lock
as the copy; general keys and subclasses deopt before any allocation,
preserving arbitrary mapping callbacks. The helper schedules GC without
calling Python, allowing the existing intermediate spills and validity checks
to be removed. Add mapping fallback, split/sparse table, independent copy,
keyword forwarding and duplicate-key tests. The final V16 GIL screen uses
an immutable source/build and continues; no build runs concurrently.

A separate follow-up hypothesis (not applied): compiling a large complete
method currently invalidates every dependent trace, including closed caller
loops that already inline its hot path. V12 protected only loops owned by the
callee. Preserve closed dependent loops during this optional replacement,
while retaining mandatory dependency invalidation on mutation and replacing
incomplete prefixes. This may preserve main's tracing benefit without the
broad complete-method feedback rejected in V10/V13/V14. It needs an explicit
old-loop lifetime/mutation test and independent before/after measurement; do
not bundle it into the dictionary-copy experiment.

V17's static pattern is present in six retained docutils executor bodies and
the hot SymPy cache decorator body in the separate V12 named diagnostic.
This establishes coverage, not dynamic hit counts or speedup. Test the same
pattern with both dict-unpack and keyword forwarding, including repeated
keyword merges that must still detect duplicates. V18's proposed optional
replacement scan is restricted to bloom-matched traces to avoid scanning
unrelated executor bodies; mandatory invalidation remains unchanged.

Prepared, not executed: fixed V16 final-PGO concurrent_imap validation with
the original6 workers/5 warmups/5 values/.1s/60s worker protocol; and separate
GIL perf-record diagnostics for original async-tree IO and chaos inputs.
The diagnostic driver retains observed executors for symbol mapping and is
explicitly excluded from timing evidence. It will follow the ongoing screen,
not overlap it.

Further source-inspection hypotheses, not implemented: entry varargs/kwargs
slots are currently abstractly unknown even though the binder supplies exact
tuple/dict objects (except cell slots). Carrying those facts could remove
_MAKE_CALLARGS_A_TUPLE in decorators and redundant type guards; assignments,
CFG joins and f_locals invalidation must remain correct. Separately, method
global folding accepts only immortal values while tracing also supports owned
constant loads. Do not extend this without lifetime/invalidation tests: the
interpreter callable cache contains borrowed references, not strong owners.

V16 GIL PGO/full-LTO screen complete:50 specifications /75 results,200
invocations, all successful, core/config/extension identities verified.
24 results exceed+2% in this selected set. After/main: unpack0.4460,
deepcopy1.0136/reduce0.9537/memo0.9934, pickle_dict0.9721/list0.9758,
SOR0.9983, Go0.9276, hexiom0.8749, spectral0.5524, SQLdeclarative0.9426.
Remaining: argparse1.1037, telco1.0939, eagerIO1.0901, IO1.0790,
chaos1.0882, docutils1.0397, SymPy sum1.0395, Richards super1.0261.
Chaos workers differ considerably (about30.4--33.9ms after versus28.8--29.4ms
main); within-worker values are stable. Do not discard the slow worker or
attribute this directly to ASLR. Raw data and conditional intervals remain.
Serialized follow-up driver starts Pool validation, then GIL perf-record,
FT GC diagnosis, and only then V17's non-PGO builds/tests.

V17's new2 focused tests pass in debug. The initial full run fails only the
existing dict-update/merge structural expectations, now replaced by the fused
copy; retain logs and update those expectations. Inspection also identified
that a string-only guard would repeatedly fall back for ordinary integer-key
dict copies. Broaden the helper to empty dictionaries and the exact dense-table
cases already cloned by dict_dict_merge, under the same lock. Do NOT accept
other general-key tables merely because PyDict_Copy would clone them: the
original merge may invoke equality callbacks there. The sparse collision test
checks those callbacks run in the original Python caller frame. Retry all4
builds/tests, preserving the first failed run and before-change failures.

V16 final-PGO concurrent_imap passes both results with6 workers each under
the original60s worker budget; SHA/runtime flags verified. FT docutils GC
diagnostic completed both orders: default after/main1.0327 versus disabled
1.0413 (diagnostic callbacks/driver, not official timings). GC pause totals
are not higher in the candidate; default collection counts295 versus297.
This does not support extra GC pause time as the primary cause of the gap.

V16 GIL named perf-record completed. TimerHandle.__lt__ accounts for only
about1--2% of samples, so its comparator alone cannot explain the IO gap.
Main's named coverage is26/30 regions, candidate33/89; many candidate side
traces were not named by the code-attached executor probe. No mapped
executors were invalidated/replaced. Prepare a diagnostic-only C extension
against each frozen build's own headers to retain/snapshot all registered
executors and their exit edges, then map side traces too. Keep these separate
from official timings; retained references and the driver affect performance.
Chaos's diagnostic run is nearly tied, whereas official workers vary; retain
both facts and avoid deriving a speed ratio from the profile.

V17 all4 configurations pass729 selected tests each (4 GIL skips,12 FT
skips), including the full dict tests. Strengthen the collision fixture to
cover dense general keys, one deleted entry (where PyDict_Copy alone would
clone but the original merge calls equality), and a mostly empty table. All4
focused reruns pass. Freeze python-v17 and the final source diff. Next run the
expanded diagnostic mapping on immutable V16, then V17/V16 comparisons with
3 workers/5 warmups/5 values/.1s and two reversed blocks. Predeclared FT set:
docutils,SymPy sum,SQLdeclarative,Go,Richards super,spectral; GIL set additionally
argparse,chaos,telco,dulwich,base64,SOR,deepcopy. No PGO/LTO development build.

V17 FT comparison finished: all24 invocations pass and identities match.
V17/V16: docutils0.9944, SymPy sum0.9917, SQLdeclarative0.9963,
Go0.9931, Richards super1.0034, spectral1.0104. These are small development
changes, not proof that the main-relative gaps are gone. Preserve both blocks.

New V18 investigation: expanded asyncio mapping identifies54 nearly identical
side traces after TimerHandle.cancel/exit18, totaling7.78% rounded self samples.
A tiny slot-clearing loop reproduces growth from5 such traces at20K iterations
to26 at100K; depths cycle1,2,3,0 despite MAX_CHAIN_DEPTH=4. Constant-store
fusion moves a failing old-value destruction guard before the trace's first
LOAD_CONST, undoing the translator's progress guarantee. Protect the first
bytecode from region fusion in traces requiring progress, before and after
abstract optimization. Method lowering remains unchanged. Initial debug probe
has only depths1..3 at20K and no such chains at100K. Add a deterministic
correctness/progress regression test, then test all4 development builds.
Prioritize this defect before the optional caller-loop preservation proposal.
The previously declared V17 GIL comparison will use frozen python-v17/v16
and explicitly shared ABI-compatible extensions after V18 correctness work;
no timing overlaps a build or another performance job.

V18 regression fixture now fails on frozen V17 and passes on the fixed GIL
debug build. The fixture checks that finalizers run once and that a side trace
can remain attached at LOAD_COMMON_CONSTANT with an unconditional first load.
Initial fixture incorrectly checked LOAD_CONST (None now uses COMMON_CONSTANT);
retain both initial failing logs and the corrected before/after evidence.
All4 selected correctness suites are running serially. Next predeclared V18
comparisons, same3-worker/5-warmup/5-value/two-order protocol: GIL async IO,
IO TaskGroup,chaos,telco,argparse,Richards super,Go,spectral; FT docutils,
SymPy sum,generators,gc traversal,Go,Richards super. V17 GIL's13-spec comparison
runs first using immutable python-v16/v17. No new PGO build until these checks.

V18 all4 builds pass730 tests each (GIL4 skips,FT13 including GIL-only
constant-store regression). Optimized-build reproduction confirms the same
result as debug: V17 has5/26 repeated fused-store traces at20K/100K iterations,
V18 has4/0. Frozen python-v18 and v18-runtime-source.diff saved. This fixes a
branch-specific progress defect; it is not a main-branch bug-report entry.
Serial V17 GIL / V18 GIL / V18 FT comparisons are now running. Final v16 PGO
artifacts remain immutable, and their runner provenance deliberately does not
claim to represent these newer changes.

Read-only follow-up during timings: the54 duplicated async side-trace regions
occupy221,184 mapped bytes out of548,864 (mapping/allocation size, not exact
instruction bytes). This strengthens the code-footprint explanation but is
not a measured speedup. Source review also prepared an unapplied argument-type
proposal: binders create exact tuple/dict varargs/kwargs, except cell slots;
propagating those facts could remove MAKE_CALLARGS_A_TUPLE and tuple/dict guards.
Keep it separate from the more promising optional closed-caller-loop retention
proposal. Neither proposal is part of the running V17/V18 binaries or results.

Source-review detail for the next experiment: ENTER_EXECUTOR stops tracing at
preserved large complete methods; it does not emit a returning METHOD_CALL
inside the caller trace. Thus an already closed/inlined caller loop can lose
its closed-loop form when optional method compilation invalidates it. The
prepared retention proposal changes only traces_only profitability invalidation;
function/type/global mutations still use mandatory invalidation. Retain the
existing generator test that deliberately rejects an oversized partial trace.
Consider retention of proven closed loops before any broader inlining-policy
change; do not silently weaken the existing method-boundary tests.

Prepared (not executed) profile_more_gil.py for frozen main/V16 final-PGO
argparse many_optionals and telco. It uses original benchmark functions/inputs,
1000/10 warmup calls and20000/100 diagnostic calls respectively, with the same
perf FIFO gating and ABI-matched all-executor mapping as the earlier IO probe.
Run it serially after the current comparisons to check whether retained closed
caller loops address the remaining large GIL gaps. Profiling times remain
excluded from speed comparisons. A dict-copy entry-progress reproducer is also
prepared for a short correctness run after timings; no concurrent workload.

V17 GIL complete:13spec/25results,52 successful invocations, identities match.
Targeted docutils1.0022,SymPy sum1.0088,SQLdeclarative1.0023; controls Go1.0072,
super0.9963,spectral1.0022. urlsafe_base64_small1.0222 in both orders;
telco1.0199 with1.0370/1.0030 blocks; SOR1.0072. All data retained. This does
not establish a useful general gain from V17; core/layout effects on unrelated
operations remain possible. Plan to remove the dictionary-copy experiment
from the final candidate, keeping the independently reproduced V18 progress
fix. First finish the already declared V18/V17 comparisons; do not stop them
based on favorable or unfavorable interim values. The running comparison
contains V17 on both sides and therefore isolates V18.

Corrected the not-yet-run argparse diagnostic budget after checking original
worker loops: both frozen PGO builds used512 loops and5 warmup/5 value batches.
Use2560 warmup and2560 measured calls instead of1000/20000. The latter would
heat the benchmark wrapper beyond the original worker lifetime, changing which
methods compile. Keep telco's10 warmups/100 measured calls (its wrapper still
remains below entry hotness); original iterations/input per call unchanged.

V18 GIL pair complete:32 invocations successful and identities match.
async_tree_io: V18/V17 0.9181, blocks [0.9101212680197397, 0.9261229006979149].
async_tree_io_tg: V18/V17 0.9311, blocks [0.9358387815211884, 0.9264388546901022].
chaos: V18/V17 1.0018, blocks [1.0103955745352005, 0.9932296379763218].
telco: V18/V17 0.9906, blocks [0.9878799188330758, 0.9932739181221985].
many_optionals: V18/V17 1.0137, blocks [1.0250713765060668, 1.0023687170769295].
richards_super: V18/V17 1.0005, blocks [0.9966623748618376, 1.0043283514012686].
go: V18/V17 0.9953, blocks [0.9859263023682117, 1.004825439479973].
spectral_norm: V18/V17 1.0006, blocks [1.0002679670772652, 1.0008889611063703].
The IO improvements reproduce both orders; this is still a development
V18/V17 comparison, not a final PGO/main result. FT comparisons now running.

V18 FT comparison complete:24 invocations pass, identities match.
docutils: V18/V17 1.0066.
sympy_sum: V18/V17 1.0004.
generators: V18/V17 0.9957.
gc_traversal: V18/V17 0.9985.
go: V18/V17 1.0025.
richards_super: V18/V17 1.0047.
All differences are within1%; no evidence this GIL-focused progress fix
resolves the larger FT/main gaps. Serial follow-up is now running the small
caller-loop and dict-progress fixtures, then frozen-PGO argparse/telco perf.

V19 applies only the optional closed-caller-loop retention change, while
keeping V17 temporarily for an isolated V19/V18 comparison. The prepared
no-dict rollback is held for the next candidate, not silently mixed into this
one. Before-change fixture fails exactly because the old loop is invalidated;
its initial standalone runner also discovered imported test classes (481 tests,
only the intended fixture failed). Restrict that runner to Regression for later
focused checks; the repository matrix still runs its normal full selected suite.

Frozen PGO profile_more_gil completed with verified identities and input hashes.
Argparse mapped148 main /132 after executors (~1.47/1.46MB); no long duplicate
chain (maximum3 side edges). Telco main has5 closed-loop traces, after hasnone.
After's Decimal._fix is737uops/partial, __mul__857uops/partial with7 METHOD_CALLs;
__bool__38uops/complete. These are diagnostic retained-reference observations,
not timings. Decimal.__bool__ notably retains generic constant loads and both
Unicode cleanup uops, and a generic bool POP plus a second receiver guard.
Potential next independent optimization: preserve known input ownership facts
through arithmetic/comparison, remove guaranteed non-owning primitive cleanup,
and inline immortal LOAD_CONST. Rebinding/frame invalidation, aliases and
in-place operands require tests before implementation. No such change yet.

V19 all4 configurations pass731 tests each (4 GIL skips,13 FT). The new test
also verifies helper.__code__ replacement invalidates the retained loop and
returns the new results. Freeze python-v19 and v19-runtime-source.diff.
Predeclare V19/V18 pairs: GIL argparse,telco,chaos,super,Go,docutils,SymPy sum,
async IO; FT docutils,SymPy sum,generators,gc traversal,Go,super,SQLdeclarative,
async TCP. Same3 workers/5warmups/5values/.1s/CPU2/two reversed orders. No
PGO/LTO builds until the development candidates are settled.

Prepared (not applied) entry-frontend-choice-proposal.patch and isolated tests.
Profiles also show missing loops rooted at small leaf method entries, which
V19 cannot retain if they were never recorded. Proposed experiment records an
entry trace first: if it closes a loop through its caller, compile that trace;
otherwise compile the original function with the method frontend, falling back
to the recorded trace if unsupported. Factor method compilation into an
internal (tstate,func,code) helper; keep the frame wrapper for tracing-init
failure. The original func/code are held by tracer state, and compilation is
skipped if func.__code__ changed while tracing. Method compilation must happen
before interp->compiling is set; FinalizeTracing still releases recorded refs.
This preserves standalone method compilation (C map callers cannot close a
Python caller loop). Inspect failures rather than weakening method-front-end
coverage, especially always-raising functions and monitoring. Proposal is only
an experiment after the current fixed-protocol pairs, not an accepted change.

Independent future cleanup idea grounded in Decimal.__bool__ profile: method
uop analysis currently replaces both pass-through arithmetic/comparison inputs
with UNKNOWN, losing borrowed/immortal facts. Generic POP_TOP for known bools
also clears receiver facts as if it could call Python. Preserving proven input
ownership, specializing ordinary primitive POP cleanup, and folding immortal
LOAD_CONST could remove refcount and redundant receiver checks. Avoid broad
mortal-global folding without lifetime tests; no cleanup changes applied yet.

V19 GIL comparison complete:32 calls pass, identities verified.
many_optionals: V19/V18 1.0047, blocks [1.0007640776087745, 1.0085995826592467].
telco: V19/V18 1.0021, blocks [1.0010421558544242, 1.0031169855490316].
chaos: V19/V18 0.9985, blocks [0.9963865800156351, 1.0005227794611984].
richards_super: V19/V18 1.0105, blocks [1.0023609025152458, 1.0186107071132489].
go: V19/V18 1.0013, blocks [1.0000433722484958, 1.0025485086890615].
docutils: V19/V18 1.0035, blocks [1.0018641843663916, 1.0051248075564525].
sympy_sum: V19/V18 0.9976, blocks [0.9904414966741855, 1.0048854461220127].
async_tree_io: V19/V18 1.0012, blocks [0.9938781214001532, 1.0086539547594195].
No useful broad gain is established; super has about+1%. Retention alone
cannot recover entry-rooted loops which were never discovered because method
compilation ran first. FT run continues. Preserve the adverse data. The entry
frontend-selection proposal remains unapplied; its standalone-method and
closed-caller-loop tests have not yet been run. Always-raising functions, code
replacement during tracing, monitoring and shared-code closures need coverage.

After V19 pairs finish, run the prepared entry-choice fixture on frozen V19
GIL/FT (expected failure only for closed-entry-loop selection; inspect logs),
then remove V17 with remove-v17-dict-fusion.patch and rebuild/test all4 as V20.
V20 is a clean baseline for a subsequent independent frontend-choice experiment;
no V20/V19 speed claim is planned from merely removing the rejected experiment.
The final main comparisons will validate aggregate performance. Added a draft
code-replacement-at-entry-warmup test (16 offsets) to cover deferred compilation
using the original frame's code while func.__code__ is changed.

V19 FT pairs completed:32 calls passed and identities verified. Ratios V19/V18:
docutils .9976, sympy_sum .9983, generators .9875, gc_traversal 1.0016,
go 1.0023, richards_super .9913, sqlalchemy_declarative 1.0041, asyncio_tcp .9989.
No broad improvement established.

V20 removes the rejected V17 dictionary fusion while retaining V18/V19.
All4 configurations pass729 tests (GIL4 skips, FT13). Initial debug failure
was2 obsolete dictionary opcode expectations left by the rollback script;
restored their original V16 assertions. No runtime failure. Frozen V16 source
hashes were checked and remain unchanged. Logs and both attempts are preserved
in v20-build-tests.json; immutable python-v20 and v20-runtime-source.diff saved.

V21 entry frontend selection experiment applied after V20 passed. The draft
3-test fixture on frozen V19 GIL/FT failed only closed-entry-loop selection,
as expected; standalone method selection and code replacement passed.
Next: debug build and draft regression tests, then integrate coverage and
run the four-build correctness matrix before any timings.

V21 debug draft3 tests passed, but the existing full opt suite initially failed
32 errors/265 assertions (mostly missing executors, no incorrect return values).
Keep all logs v21-{debug,b,c,d}*. Isolated classes differed, so diagnose the
interaction rather than lowering assertions. Temporary debug-only diagnostics
identified TRACE_BUSY: entry exploration rooted in unittest helpers remained
suspended across C-mediated Python callbacks. Loops inside those callbacks
could not start tracing and backed off. Removed the diagnostic instrumentation.

Refine V21: only treat closed entry traces with net frame depth zero as loops;
recursive entry traces still use the method frontend. Stop exploratory entry
tracing before CALL/CALL_KW/CALL_FUNCTION_EX unless a specialized opcode directly
enters a Python frame. This lets callback loops compile while retaining direct
Python caller loops. Adapt the ready-resume-counter test to return via C map
before checking compilation; the counter assertion is unchanged. Added4 tests:
closed caller selection/code invalidation, standalone methods, callback-loop
compilation, and code replacement during entry recording. Full debug suite is
running; performance comparisons remain deferred until correctness checks pass.

V21-e regeneration failed because the bytecode DSL parser does not accept the
new C switch statement. Its following build/test commands mistakenly continued
using the previous generated cases; those results do NOT validate the callback
fix. Preserve the logs and use checked subprocess return codes / set -e. Replace
the switch with ordinary comparisons supported by the DSL, then regenerate.

V21-f regenerated cases successfully and the full opt suite passed483 tests
(4 skips). The callback-boundary refinement removes the large set of missing
executor failures without weakening their assertions. Temporary diagnostics
were removed. Next all4 debug/native, GIL/FT builds run opt, optimizer, generators,
yield_from, dict, monitoring and frame tests, then freeze binaries/source.
Predeclared V21/V20 pairs: GIL argparse,telco,chaos,super,Go,docutils,SymPy sum,
async IO; FT docutils,SymPy sum,generators,GC traversal,Go,super,SQLdeclarative,
async TCP. Each3 workers/5warmups/5values/.1s/CPU2/two reversed orders. Compare
frozen binaries with explicitly shared ABI-compatible standard extensions.

V21 all4 configurations passed899 tests (GIL12 skips, FT21); frozen python-v21
and v21-runtime-source.diff. Fixed-protocol V21/V20 pairs running sequentially.
Initial GIL order has adverse telco/super values; retain them and await the
reverse order before deciding. No improvement or main-regression resolution
is claimed yet.

Prepared, not applied: method-primitive-cleanup-proposal.patch. Based on
Decimal.__bool__ diagnostics, fold immortal LOAD_CONST; recognize primitive
POP_TOP as nonescaping in CFG state; preserve input ownership across arithmetic
and comparison uops, skipping borrowed/immortal cleanup. Restrict cleanup to
known pass-through expansions: generic uop state does not model every opcode.
The temporary uop stack may lack room for the extra result; in that case the
unchanged inputs still correctly describe the two cleanup operands. Need tests
for reference counts, aliases, polymorphic fallback and callback/frame-local
mutation, then independent before/after comparisons. Do not apply while current
frozen comparisons are incomplete.

V21 GIL pairs completed:32 calls passed, identities verified. V21/V20:
many_optionals: 0.9963, blocks [0.9970955825616843, 0.9955764241929066].
telco: 1.0439, blocks [1.0375460261423384, 1.0503819815648359].
chaos: 0.9977, blocks [0.9932943743586087, 1.002201002707717].
richards_super: 1.0262, blocks [1.0222160460254937, 1.030240200916673].
go: 1.0111, blocks [1.0023035295687421, 1.0199927167956007].
docutils: 1.0043, blocks [1.004192012239213, 1.0044897347074828].
sympy_sum: 1.0087, blocks [1.016307189408638, 1.0010832412207809].
async_tree_io: 1.0030, blocks [0.9831243245849439, 1.0233066297404454].
Both orders regress telco and super. No useful broad gain; GIL adoption rejected. FT data collection continues. Prepared remove-v21-entry-choice.patch without applying it; all3 original files reconstructed/retained.

Refined unapplied primitive cleanup proposal after inspecting CFG analysis:
TO_BOOL_BOOL proves only the copied TOS currently, leaving the surviving COPY
unknown at short-circuit POP_TOP. Give COPY values a block-local alias identity
(negative bytecode offset; positive origins remain local indices), and narrow
all live stack aliases after the exact-bool guard. Origins are already cleared
on escapes and CFG merges. Use signed32 origin (internal optimizer-only type);
do not speculate about aliases across joins. Draft3-test coverage is
method_primitive_cleanup_test.py, not yet executed during timing runs.

Another independent, unapplied hypothesis from code inspection: _JIT now reads
interp->jit on every cold RESUME/backedge, whereas main only checks its hotness
first. It may be possible to decrement cold counters first and read JIT state
only at a ready counter. Keep ready counters at zero while JIT is disabled;
never compile/execute while an FT second thread is attached. This changes cold
counter freezing, an internal policy, so add a suspension/warmup/resumption
test before considering it. No timing evidence yet; do not bundle it into the
primitive ownership experiment.

V21 FT pairs complete:32 calls passed, identities verified. V21/V20:
docutils: 0.9981, blocks [0.9921275946569927, 1.0041608986173038].
sympy_sum: 0.9885, blocks [0.9817514852624828, 0.9952281978544084].
generators: 0.9871, blocks [0.988259948979362, 0.985911157272119].
gc_traversal: 0.9812, blocks [0.9751725524317328, 0.9872494121777815].
go: 0.9957, blocks [0.992654260126292, 0.998788324817569].
richards_super: 1.0282, blocks [1.0113375607354333, 1.0453412891855989].
sqlalchemy_declarative: 0.9942, blocks [0.9935189459964444, 0.9949642079298259].
asyncio_tcp: 1.0251, blocks [1.0003847878355236, 1.0503703771411919].
V21 rejected in BOTH configurations. The modest FT gains do not justify
super+2.8% and asyncTCP+2.5% (latter varies across blocks). Restore all3 V20
source files using the prepared patch; preserve V21 binaries, diff, correctness
and performance evidence. Do not claim main regressions resolved.

V22 applies only the primitive/immortal cleanup proposal on top of V20.
Before fixtures run on immutable GIL/FT python-v20; inspect failures before
regeneration/debug build. V21 entry-policy experiments are fully removed.

V22 before fixture failed5 optimization assertions in3 tests on frozen GIL/FT
V20, as expected. New debug candidate passed the ownership/boolean fixtures,
but the code-replacement fixture incorrectly expected the old code executor
to become invalid. Root executors belong to code objects, which may still be
shared by other functions. Correct the fixture to verify an alias retaining
the old code and the function using its new constants both return correct
results. No runtime change was needed for that assertion. Preserve first log.

Audit found enumerate scan fusion expected two owned-int cleanup uops after
comparison; permit the equivalent borrowed POP_TOP_NOP forms so the new
ownership optimization does not disable existing fusion. Region arithmetic
and float matchers already accept these forms. Integrate3 tests and repeat
debug correctness before four-build matrix.

V22-b debug passed the draft3 tests and all732 tests in opt/optimizer/generator/
yield_from/dict. Add warmup of the replacement-code function so both the old
alias and the new function exercise compiled constants. Next all4 configurations
run those suites plus monitoring/frame, and debug builds run3:3 reference-leak
checks for the new ownership/alias/constant tests. No timings until completed.

Predeclare V22/V20 development pairs with the same8 specifications per mode
and protocol used for V21 (3 workers,5 warmup,5 values,min.1s,CPU2,two reversed
orders). Both sides include V18/V19 and exclude rejected V17/V21. This isolates
primitive cleanup while retaining improvements and regressions for all controls.
The comparison scripts are prepared but not yet running.

V22-c full debug correctness passed898 tests, but the new3 tests'3:3 leak
check reported6/6/7 memory blocks (no reference-count leak). Add the existing
clear_executor_deletion_list cleanup to these GC-disabled executor tests.

Static review found a real flaw in V22's initial alias narrowing: a positive
local origin is not a value identity after the local is reassigned while its
previous value remains on the stack. A valid handcrafted bytecode regression
reproduces an invalid POP_TOP_NOP assertion in the new debug candidate; frozen
V20 passes. Logs v22-before-alias-fix.log and v20-alias-reassignment-control.log.
This is an experimental V22 bug, not a main bug. Keep the failed candidate source.

Fix uses a separate stack_alias field for COPY groups, leaving local origins
unchanged. Clear alias IDs at local stores, escaping instructions and CFG joins.
Only aliases established by COPY are narrowed after TO_BOOL_BOOL. Add the
reassignment/finalizer test; repeat correctness and3:3 leak checks on all4 builds.

V22-d debug passed899 tests after separating stack aliases from local origins.
The4-test refleak group still reported20 refs/run. Isolated checks showed the
original3 new tests now pass3:3; only the new handcrafted-bytecode fixture
retained objects. Frozen V20 shows the identical20 refs/13-15 blocks pattern,
so this is not introduced by primitive cleanup. The fixture's shared generator
expression can cache a fresh local Value class on each repetition. Produce
values via C itertools.starmap instead, preserving the exact drop/finalizer
workload; rerun3:3 on both frozen V20 and the candidate. Keep both control logs.

The corrected C-factory alias fixture passes3:3 on frozen V20 and fixed V22.
An immutable pre-alias-fix debug binary was preserved as
build-method-debug/python-v22-before-alias-fix (SHA8d3a2a8f0f389d3825c4fbb9344a40105523ebec9e930259ffde1fc7ddfd7ab9).
The final fixture still aborts on that binary at POP_TOP_NOP, so replacing the
fixture generator has not hidden the actual compiler bug. Preserve the return
code/log in v22-before-alias-fix-final-fixture.json.

V22-e debug and FT-debug passed899 tests each and all4 new tests'3:3 leak
checks. GIL native passed899; FT native completing. No timings started yet.

V22-e completed: all4 configurations passed899 tests each (GIL12skip,FT21skip).
Both debug configurations passed the4 new tests with3:3 reference-leak checks.
Corrected valid-bytecode alias fixture still aborts the frozen pre-fix candidate
and passes V20/fixedV22, so it exercises the actual bug. Full source diff and
binary hashes are in v22-runtime-source.diff and v22-build-tests.json.
The primitive diagnostic (v22-primitive-cleanup-uops.json) reduced short-circuit
attribute access from38 to33 GIL uops /38 to34 FT uops; type guards2->1,
validity checks3->2. This is an instruction diagnostic, not a timing claim.
V22/V20 pairs are running sequentially; source/builds remain frozen throughout.

V22 GIL pairs completed32 calls, identities verified. V22/V20 ratios:
many_optionals .9971, telco .9834, chaos .9966, super1.0025, Go .9980,
docutils1.0061, SymPy sum .9855, async IO .9968. FT pairs continue.

Prepared (NOT applied during timings) v23-validity-proposal.patch and two
standalone tests. Method validity dataflow currently treats _START_EXECUTOR
as unchecked and HAS_PERIODIC as escaping. The trace frontend already knows
START checks validity and a _TIER2_RESUME_CHECK fallthrough cannot run arbitrary
code: the pending-work arm permanently exits Tier2. Propagate those facts
through the method CFG, retaining checks after actual escaping operations,
frame transitions, and periodic backedges that do handle pending work inline.
Test folded-global invalidation both before entry and through len callbacks.
This is separate from the previously considered cold-interpreter change.

Prepared v24-cold-jit-proposal.patch independently of V23: check/decrement a
cold hotness counter before loading interp->jit; hold zero when JIT is disabled
or another trace is active. A new FT test warms a fresh function while another
thread is attached, checks that no executor was compiled and the counter stays
ready, then checks compilation after that thread leaves. This changes only the
internal cold-counter policy; the multiple-thread JIT suspension remains.

After V22 pairs finish, validate V23 and freeze all4 binaries, then validate V24
and freeze all4. Both correctness matrices must pass before timing. The next
performance screen is explicitly the combined V24/V22 change (same8 specs/mode,
3 workers/5 warmup/5 values/two reversed blocks); do not attribute its timing
separately to V23 or V24. Frozen V23 permits a focused isolation if an adverse
result warrants it. No further source edits while those timings run.

V22 FT pairs completed32 calls, all successful, hashes verified. V22/V20:
docutils: 1.0054, blocks [0.9955224288164336, 1.0152927695918832].
sympy_sum: 1.0023, blocks [0.9987001942917185, 1.0058446896189739].
generators: 1.0010, blocks [0.9970681812759962, 1.0049360175174968].
gc_traversal: 1.0116, blocks [1.004096020414305, 1.0191755942703948].
go: 0.9937, blocks [0.9943184550818286, 0.993032364279401].
richards_super: 1.0007, blocks [1.0115970676345811, 0.9899547848508414].
sqlalchemy_declarative: 0.9913, blocks [0.9892207790745536, 0.993479580845366].
asyncio_tcp: 1.0080, blocks [1.006535076865469, 1.009443235777843].
Retain V22 provisionally: GIL SymPy improved, FT Go/SQL modestly improve; FT GC+1.16% and TCP+0.80% remain adverse. This does not resolve main regressions. Begin V23 correctness matrix; V24 stays unapplied until it passes.

V23 complete: the two before fixtures fail exactly the expected redundant-check
assertion on both frozen V22 builds; callback invalidation already passes.
Afterward all4 configurations passed901 tests (GIL12skip,FT21skip), both debug
builds passed the2 new tests'3:3 leak checks. The recursive-resume test now expects
START_EXECUTOR's existing validity check followed directly by the periodic check.
V23 binaries/diff are frozen. Begin V24 counter-order correctness validation.

V24 before-control failure confirms the suspended function remains cold (raw
counter65526). Static inspection caught an overly strict new fixture assertion:
the countdown's low3 bits contain its backoff, so a ready counter may be6 rather
than raw0. Correct the fixture to assert countdown (counter>>3)==0, retaining
backoff bits, and rerun the before control with the final fixture. Runtime policy
is unchanged; this correction precedes the four-build correctness runs.

V24 GIL debug/native and FT debug passed902 tests each (GIL13skip,FT21skip).
The new FT suspension test's leak check reports2/1/2 memory blocks without a
reference-count leak. Add the standard executor deletion-list cleanup used by
the other new tests and repeat the leak check before finishing the FT matrix.
No benchmark timings or PGO build have started for V24.

V24 final correctness complete: all4 builds passed902 tests each; GIL13skip,
FT21skip. The FT suspension test passed3:3 with the executor deletion-list
cleanup (the initial failed leak log is retained). V24 binaries and full source
diff frozen. Start predeclared V24/V22 development pairs sequentially, GIL then
FT; all builds/tests/profilers stay idle while timing. The source remains fixed.

Additional static review during V24 timing: stack alias IDs are bounded by the
method frontend's INT16_MAX code-size limit; aliases are not retained across
CFG joins. The START/periodic validity simplification retains checks after
actual escapes and frame changes, and FT thread publication still uses STW.
No new runtime edit was made.

A remaining hypothesis (not implemented) concerns cold CFG size. The existing
V16 diagnostic shows _ActionsContainer.__init__ at1175 uops, Decimal._fix at737,
and Decimal.__mul__ at857. A possible future experiment would use the existing
16-bit branch histories (initialized to alternating bits) to leave consistently
cold blocks as correct deopt continuations in large methods, keeping normal
analysis and stack conventions. This could reduce code footprint but could also
increase fallbacks when inputs change; it needs path-change, alias/exception and
performance controls. Do not present it as an established cause or improvement.
First finish V24 pairs and, if no material adverse effect is demonstrated,
rebuild with the matched original PGO/full-LTO protocol and remeasure main. No
branch-history change will be bundled into that comparison.

V24 GIL pairs complete:32 successful calls, hashes verified. V24/V22:
many_optionals: 0.9911, blocks [0.9959363172848578, 0.9863035359304984].
telco: 1.0062, blocks [0.9978052347543586, 1.0146488550068018].
chaos: 1.0020, blocks [1.00331459534307, 1.0006603957770903].
richards_super: 0.9999, blocks [0.9983498574800643, 1.001360327716445].
go: 0.9974, blocks [0.9983089080677885, 0.9964104416202694].
docutils: 1.0007, blocks [1.0053516003575604, 0.9960097556627989].
sympy_sum: 1.0003, blocks [1.0041950094675864, 0.996489083308874].
async_tree_io: 0.9837, blocks [0.9858370395415912, 0.9814965319497582].
Async IO improves1.6% and argparse0.9%; telco+0.6% remains adverse, other controls nearly neutral. FT continues. No main-relative conclusion yet.

V24 FT pairs complete:32 successful calls, hashes verified. V24/V22:
docutils: 1.0006, blocks [1.0025054829344735, 0.9987441907160463].
sympy_sum: 0.9951, blocks [0.9934892863600646, 0.9967309866941216].
generators: 1.0084, blocks [1.0126799848991164, 1.0041703224897538].
gc_traversal: 1.0029, blocks [1.0078563698371674, 0.9980131187193861].
go: 0.9923, blocks [0.9916345441052997, 0.9928684652602364].
richards_super: 1.0018, blocks [1.003604703478994, 0.9999955278799334].
sqlalchemy_declarative: 1.0055, blocks [1.000813164441019, 1.0101864038036394].
asyncio_tcp: 0.9909, blocks [0.9790039517874258, 1.0029112653875054].
Retain V23/V24 for matched main validation. FT effects are all below1% in their geometric-mean point estimates; preserve generators+0.84% and SQL+0.55%. No no-regression claim. Capture a short diagnostic of current large-method branch histories, without changing code or treating its timing as performance. Then build V24 with the same PGO/full-LTO protocol as main; keep all V16 artifacts immutable.

V24 branch-cache diagnostic completed separately from timing. The helper was
compiled against the current GIL build/header configuration; binary and standard
extension hashes were checked. It retains executor references only after warmup.
This is bytecode reachability from cached histories, not measured execution
coverage or a performance result. Files v24-method-branches-*.json.
Examples (normal/profile-reachable bytecodes):
ActionsContainer.__init__134/134 at1147 uops: root cold-branch pruning alone would
not reduce it. Decimal._fix313/54 at732uops; __mul__177/94 at849uops;
quantize226/123 at916uops. Cold CFG size remains a plausible telco hypothesis,
not a demonstrated cause. A future pruning experiment must preserve loop exits
regardless of saturated branch histories (e.g. protect conditional edges in SCCs),
or normal loop termination would become a frequent method fallback.

Matched V24 PGO/full-LTO build started in v24-final-pgo-{src,build}. Source is
frozen. Retain the old final-pgo-* V16 build and profiles unchanged. The default
PGO corpus matches main:43 files and expected10468 tests/460 skips; JIT0, seed0,
separate pycache, bootstrap profiles quarantined before training.

V24 PGO training attempt1 failed only in test_re.test_regression_gh94675:
sandbox denied forkserver's Unix-domain listener.bind with EPERM. The unchanged
43-file corpus otherwise completed10468 tests/460skips. Do not use its profiles.
Quarantine all351 generated .gcda files in v24-final-pgo-rejected-training,
record their hashes and the instrumented binary hash, and rerun the entire same
corpus with socket permission. The dedicated training pycache did not exist;
profile-run-stamp was not created. No runtime/test workaround or skip added.
The original failed log stays in the build manifest. No timings are running.

Read-only residual-workload audit while PGO runs: bm_gc_traversal times only the
second gc.collect(), after graph construction and another gc.collect(). Its
remaining gap cannot be treated as time spent in generated loop code; inspect
GC/heap/executor population and native collection if it persists. bm_generators
builds its100000-node tree before its timer; old v5b diagnostics show only tree
and Tree.__init__ executors after rejecting the delegation-only loop trace.
Do not generalize the sends>1 filter without first showing new unhelpful traces.
The frozen main FT _RESUME_CHECK already has the same TLBC-index guard as the
candidate, so that guard is not a newly introduced explanation of the gap.

V24 matched PGO/full-LTO build completed. The clean training retry passed all43
files,10468tests/460skips with the unchanged corpus, seed and JIT0 settings.
The failed attempt's351 profiles remain quarantined. Final binary SHA256:
bd1cea28f945b03f5ac30bff3107a0a5be901c013b24634ba259eb394e11c159.
Final source, extension and configuration hashes are in v24-final-pgo-build.json.
The GIL validation passed2187tests/76skips; FT validation is running next.
Next: complete correctness, original6-worker Pool validation, update the runner
to this verified source pair, and rerun the fixed main regression selection.

V24 final correctness completed:2187tests each,76GIL/91FT skips. The original
6-worker concurrent_imap protocol passed both Pool results with GIL/JIT verified.
All20 four-build compatibility smokes passed (5specifications/7results perbuild).
Runner now points to the verified V24 pair;20controller tests and candidate
provenance checks passed. Old V16 artifacts remain immutable.
Run full --prepare-only into pyperformance-four-way-v24, then sequentially the
same selected main comparisons as V16:18FTspec/23results and50GILspec/75results,
2workers,5warmups,5values,min.1,CPU2,2reversedorders,45sworker/150sspec limits.
No runtime edits, rebuilds or profiling during these fixed-binary comparisons.

V24 preparation passed for all97 specifications in both configurations; FastAPI
remains explicitly unavailable. FT timing is in progress without failures.
Read-only V16 chaos-profile audit provides a narrower next hypothesis than CFG
pruning: Spline.__call__@0 is partial, has METHOD_CALL and method loop edges,
while the same code also owns closed inlined traces at984/992. The existing
V12 profitability check excludes partial methods. Also, its has_method_call
scan stops at the first METHOD_DEOPT, so widening the condition alone would
miss calls in later blocks. Prepare a separate partial-loop regression fixture
and test widening this policy after V24 main comparison. Preserve rare cold
path correctness and mandatory mutation invalidation. No runtime change yet.
The larger cold-CFG proposal and three draft semantic tests are saved separately
as cold-cfg-proposal.patch and method_cold_cfg_test_draft.py, not applied.
Its loop protection conservatively retains all backward-edge intervals and
both FOR_ITER successors. Do not combine it with the smaller loop-policy trial.

V24 final FT screen completed:72calls/18specifications/23results, all successful,
binary/config/standard-extension hashes unchanged. Candidate/main time ratios:
asyncio_tcp: 1.0278, blocks [1.0360039348823629, 1.0196037813638847].
deepcopy: 0.9265, blocks [0.9232552597473526, 0.9297150589627742].
deepcopy_reduce: 0.9667, blocks [0.9675905821214627, 0.9658792171186752].
deepcopy_memo: 0.7685, blocks [0.7704574607081512, 0.7665112161315195].
deltablue: 0.7922, blocks [0.7982780819620309, 0.7862183268015229].
docutils: 1.0468, blocks [1.0512918549609793, 1.0423210105247933].
gc_traversal: 1.0228, blocks [1.0187879554510304, 1.026858293062319].
generators: 1.0320, blocks [1.0333995931617441, 1.030553953735181].
go: 0.8587, blocks [0.8627382884521535, 0.8546749161074603].
hexiom: 0.8529, blocks [0.8523993674055167, 0.8533275163735135].
raytrace: 0.8500, blocks [0.8525004756050146, 0.8474560587387492].
regex_dna: 1.0181, blocks [1.0138544208609015, 1.0223216576870842].
regex_v8: 1.0490, blocks [1.0488108569901666, 1.049226895355312].
richards: 0.3987, blocks [0.39762880301935183, 0.3998072067422463].
richards_super: 0.3900, blocks [0.39025278147084463, 0.38979027574076713].
spectral_norm: 0.3542, blocks [0.3548618768187032, 0.3536203184767451].
sqlalchemy_declarative: 1.0253, blocks [1.0273903965358329, 1.0232531549577235].
sqlalchemy_imperative: 0.8003, blocks [0.8101962074790481, 0.7905035321004787].
sympy_expand: 0.8941, blocks [0.8988326596802612, 0.8893788669817205].
sympy_integrate: 0.9980, blocks [0.9981207830245963, 0.9978863131800478].
sympy_sum: 1.0396, blocks [1.0286289274796696, 1.0507501890047575].
sympy_str: 0.9501, blocks [0.9505100610590019, 0.9497134951089935].
unpack_sequence: 0.6988, blocks [0.6969944817641487, 0.7006801564330858].
Seven point estimates exceed1.02:docutils,regex_v8,SymPy sum,generators,TCP,
SQLAlchemy declarative,GC traversal. Regex DNA is+1.81%,also adverse.
These are selected results,not a complete-suite geometric mean. Worker CIs
are conditional on this fixed pair and two orders; no multiplicity correction.
GIL PGO comparison follows sequentially. Add regex_v8 JIT-on/off/native
profiling to the residual investigation; do not dismiss the new+4.9% result.

Before any V25 source edit, isolate the latest V24 counter change using the
frozen V23/V24 FT binaries on regex_v8,regex_dna,generators:3workers,5warmups,
5values,min.1,CPU2,2reversedorders,shared current ABI-compatible extensions.
Prepared compare_v24_counter_pair.py/analyze_v24_counter_pair.py; not run yet.
V24 also advances cold counters during tracing/suspension, unlike V23, so a
changed warmup/executor selection is a hypothesis alongside native code layout.
No attribution without this check. Separate perf scripts preserve original
timed bodies via timer-boundary gating for FT generators,GC traversal,regex_v8,
with JIT1/JIT0 and main/candidate; FIFO overhead precludes official time claims.

Static bytecode audit (definitions compiled but no workload calls) confirms an
independent inlining-limit issue: GVector.linear_combination has40 instructions
but153 code units, GVector.__add__38/156, GVector.dist28/139, Spline.GetIndex55/170.
All exceed the128-code-unit small-CFG limit despite modest executable bodies.
The existing tracing boundary already uses actual instruction count. Consider
the same distinction for bounded CFG inlining, with a separate allocation bound
and the existing uop budget. Keep it separate from partial-loop retention and
cold-CFG pruning. Save sizes in chaos-static-bytecode-sizes-v24.json; this audit
does not establish a speedup. No source proposal for the limit has been applied.

V24 final GIL PGO/full-LTO screen completed:200calls/50specifications/75results,
all successful; fixed binary/config/extension hashes verified after measurement.
23point estimates exceed1.02. Preserve the following residuals:
many_optionals: 1.1021, blocks [1.0964475792296955, 1.1078787436384565].
async_generators: 1.0310, blocks [1.0324519186420227, 1.029532015852022].
async_tree_io: 1.0239, blocks [1.0370834444641392, 1.0107925244848466].
urlsafe_base64_small: 1.0519, blocks [1.0542976827422177, 1.049416119320428].
base16_small: 1.0603, blocks [1.0606359399232304, 1.059934699268538].
base16_large: 1.0477, blocks [1.0532039886849924, 1.0423015122080437].
base85_small: 1.0752, blocks [1.025408270891324, 1.1273700073236421].
chaos: 1.0871, blocks [1.1440157588041409, 1.0330639391660827].
coverage: 1.0379, blocks [1.036680662307723, 1.0392026160618486].
docutils: 1.0303, blocks [1.028035872328649, 1.0325558378387].
dulwich_log: 1.0606, blocks [1.040172495613214, 1.0814377777462696].
fannkuch: 1.0441, blocks [1.0471047189307618, 1.0411174897617586].
gc_traversal: 1.0416, blocks [1.0471265385537993, 1.0360052758581377].
meteor_contest: 1.0299, blocks [1.0318273775326638, 1.0280485089986993].
nbody: 1.0262, blocks [1.02585417742304, 1.0265721873550415].
pickle_pure_python: 1.0309, blocks [1.0369382795490012, 1.024836459971119].
pprint_safe_repr: 1.0516, blocks [1.005721109928758, 1.0994731277797607].
pprint_pformat: 1.0272, blocks [1.0213889119625053, 1.0331342225113347].
sqlglot_v2_parse: 1.0321, blocks [1.0183926224060473, 1.0459799902162141].
sqlglot_v2_transpile: 1.0536, blocks [1.0474152329033235, 1.0598066428712156].
sympy_sum: 1.0487, blocks [1.046044354675442, 1.0513160059764584].
telco: 1.0836, blocks [1.0837601114526063, 1.083386809266615].
tornado_http: 1.0263, blocks [1.042324001195413, 1.0105049337005714].
EagerIO.9920,eagerIOtg1.0057,IO1.0239,IOtg1.0145: prior IO gaps reduced;
not all erased. Logging format.9887,simple1.0143;Super1.0150;Go.9420;
SQLdecl.9362. Chaos blocks1.1440/1.0331 and base85small1.0254/1.1274 are
heterogeneous; all workers retained. Base16large1.0477 is adverse in bothorders,
so native/JIT0 effects and PGO/build variation also need investigation.
No claim these inter-build changes identify a source-level cause.
Start serial post-comparison input audits,V24/V23 FT counter pair,then separate
FT perf stat/record on generators,GC traversal,regex_v8,JIT1/JIT0. No source edit
or build until these diagnostic processes finish.

The post-comparison audit passed for both full prepared environments (including
stdlib), selected original workload/dependency hashes and site bootstrap. Full
tables are saved in v24-final-comparison.md;23 GIL and7 FT ratios exceed1.02.
V24/V23 FT counter-isolation pair completed12calls,all successful,hashes verified:
regex_v8 1.00303,blocks1.00563/1.00044,conditional95%1.00017–1.00768;
regex_dna1.00174,blocks1.00226/1.00123,CI.99887–1.00546;
generators1.00767,blocks1.00663/1.00871,CI1.00461–1.01083.
The counter change alone does not explain regex_v8's4.9% main gap. Keep the
adverse+0.77% generator result; do not call V24's FT performance equivalent.
Separate FT native/JIT1/JIT0 counter diagnostics are running sequentially.

New generator diagnostic evidence (not a timing conclusion): current V24 can
attach a218-uop bench_generators@240 trace with9 SEND_GEN_FRAME,10PUSH_FRAME,
6attribute loads and3GET_ITER, but noYIELD_VALUE orJUMP_TO_TOP. Unlike the old
V5b pure-delegation dump, this prefix also starts child generators and reads
their attributes, so the narrow existing rejection filter does not match.
Investigate a conservative extension for such setup-only prefixes, preserving
traces that reach a yield,finish a loop,or perform optimizable body work. This
is now evidence-based, not the previously rejected blind sends-count heuristic.
The first main/JIT1 perf-stat generator process was much slower despite nearly
unchanged instruction count; retain it and inspect both orders, not just a
favorable subset. FIFO-gated diagnostic times are not official pyperf results.

V24 FTの追加診断を完了した（stat 24回、record 12回、全て成功）。
実行前後のバイナリ・設定・依存・workloadのハッシュも一致する。
元の関数と入力を使い、内部タイマー境界でperfを制御した。FIFOの制御が
加わるため、この時間をpyperfの性能比較には使わない。

- regex_v8: JIT無効でもcandidate/mainのcyclesは1.0583/1.0573。
  JIT有効では1.0463/1.0477。sre_ucs1_matchが大半を占める。
  同関数の2,920命令はアドレス差を正規化すると一致する。SHAは
  1dd352b1f241cd0d7d6c8da7c27ede8fe406d7077edc36cbac15cffb8779a4ea。
  O3・FP・leaf FPの実効フラグも同等。同関数の命令列の悪化が原因ではないが、
  アドレス、呼び出し先、メモリなどの影響は未分離。mainとの差は未解消。
  v5で保存した配置実験も参照し、最速の配置を選ぶ変更は採用しない。
- GC: 命令数はほぼ等しく、cyclesは順序間で変わる。新しいソース上の原因は未特定。
- generators: candidateのJIT有効時は無効時より命令数が約0.67%増え、
  cyclesも約2–3%増える。mainの最初のJIT有効試行の遅い値も保存した。

V25試作では、SENDによる委譲に入った後の子ノードの属性・slot読み取り、
スタック操作、GET_ITERも「準備だけの接頭部分」に含める。算術、yield、
閉じたループに達するトレースは維持する。元のbalanced treeから218 uopの
問題を再現した。単純な委譲・共有部分木だけの最初のfixtureは修正前も成功しており、
回帰テストとしては採用しなかった。反復を続けて初回拒否のbackoffを越える
fixtureは修正前のGILあり・なし両方で失敗する。

新しいテストは繰り返し時にコード状態を引き継ぐ問題があり、reset_codeで各回を
初期化した。最初の失敗ログは保存。修正後FT debugは904テスト、21 skipを通過し、
追加2テストの3:3参照漏れ検査も成功した。他の構成の検証を続ける。
V25の採用判断は次の固定比較後に行う。性能向上はまだ未確認。

V25/V24の事前指定比較:
FTはgenerators、async_generators、docutils、SymPy sum、Richards Super、
regex_v8、regex_dna、SQL declarative、GC。GILはgenerators、async_generators、
Richards Super、Go、docutils、SymPy sum。3 worker、5 warmup、5 value、min .1s、
CPU 2、順序反転2ブロック、PGO/LTOなし。全ての試行を残し、4構成の検証後に開始する。

次は部分methodによる既存の閉じたループの置き換えを抑えるV26の独立試作。
chaosのSpline.__call__に部分methodと閉じたinlined loopが共存する証拠がある。
その後の候補として、small CFGのinline上限を実行命令数128と割り当て用の
code unit上限に分ける案を準備した。現状は40命令/153 code unitsの
GVector.linear_combination等がcache領域だけで展開対象から外れる。
これらの案とcold CFG案はまだruntimeソースへ適用していない。

V25の4構成が各904テストを通過した（GIL 13 skip、FT 21 skip）。
追加2テストはGIL/FT debugの3:3参照漏れ検査も成功。初回のテスト状態の
引き継ぎによる失敗と、その後の再検証はv25-build-tests.jsonに両方残した。
python-v25を4構成で凍結し、差分をv25-runtime-source.diffへ保存した。
通常GIL SHA:5550a7a0d4f180a84736f1ea547b145a92d6f7e66d004539281829c671d3255a。
FT SHA:3bc8e4f89a439f5c07fe31009c156dba18fe9db36e07e10a6c7166f81ebe44fb。
事前指定したV25/V24の性能比較を開始。競合するビルドや測定は実行しない。

V25/V24のFT比較36回が全て完了し、前後のハッシュが一致した。
全workerを含めた点推定はgenerators .98282（両順序 .98176/.98388）、
async_generators 1.00023、docutils .99315、SymPy sum .99542、
Richards Super .99947、regex_v8 .99798、regex_dna 1.00219、
SQL declarative 1.00166、GC 1.00397。GCの順序別は .99447/1.01356で変動する。
GILの比較とworker区間の集計は継続中。main比ではないため、mainの回帰が
消えたという判定にはしない。SENDはcoroutineでも使われるので、次の
4構成の検証にはtest_coroutines/test_asyncgenも追加する。

V25の開発比較はFT 36回、GIL 24回とも成功し、前後hashは一致した。
比はV25/V24、区間は2つの固定ブロック・固定ビルド内のworker bootstrap 95%。
ビルド間変動や多重比較を含めた再現性の証明ではない。全workerを保持する。
ft generators: 0.98282, CI 0.98044–0.98541, blocks 0.98176/0.98388.
ft async_generators: 1.00023, CI 0.99857–1.00192, blocks 0.99852/1.00194.
ft docutils: 0.99315, CI 0.98688–0.99943, blocks 0.98756/0.99878.
ft sympy_sum: 0.99542, CI 0.99081–1.00055, blocks 0.99436/0.99649.
ft richards_super: 0.99947, CI 0.99712–1.00216, blocks 0.99648/1.00248.
ft regex_v8: 0.99798, CI 0.99555–1.00083, blocks 0.99936/0.99660.
ft regex_dna: 1.00219, CI 0.99825–1.00544, blocks 1.00142/1.00297.
ft sqlalchemy_declarative: 1.00166, CI 0.99849–1.00482, blocks 1.00220/1.00112.
ft gc_traversal: 1.00397, CI 0.99532–1.01328, blocks 0.99447/1.01356.
gil generators: 0.98713, CI 0.97916–0.99385, blocks 0.98625/0.98801.
gil async_generators: 0.99927, CI 0.99515–1.00321, blocks 0.99938/0.99916.
gil richards_super: 0.99723, CI 0.99433–0.99991, blocks 0.99835/0.99611.
gil go: 0.99662, CI 0.98873–1.00412, blocks 1.00497/0.98834.
gil docutils: 0.99315, CI 0.98690–0.99982, blocks 1.00051/0.98585.
gil sympy_sum: 0.98988, CI 0.97784–1.00128, blocks 0.99827/0.98157.
generatorsは両構成・両順序で短縮。対照の区間にも明確な悪化はなく、V25を採用する。
全main回帰が消えたという判定ではない。次のV26は既存の閉じたinlined loopを
部分methodで置き換えない変更だけとする。冷たい経路のMETHOD_DEOPTを見つけても
走査を続け、後続のMETHOD_CALLを検出する。cold CFG・inline上限の案は混ぜない。
元のgenerator reproducerをV24/V25の両通常ビルドで確認し、最終fixtureのV24での
失敗も再確認してからV26を適用する。V26の事前指定比較はFT chaos/Go/Super/
docutils/SymPy sum/SQL declarative/generators/unpack、GIL chaos/telco/Go/
Super/argparse/docutils/SymPy sum/deepcopy。元と同じ3 worker・5 warmup・5 value、
CPU 2、独立校正、逆順2ブロック。PGO/LTOなし。

元のgenerator reproducerでもV24→V25で不要なexecutorが消えた。
GILは212 uop→0、FTは218 uop→0（v2{4,5}-generator-original-*.json）。
reset_codeを含む最終fixtureも、凍結V24のGIL/FT通常ビルドで期待どおり失敗した。
V26の新しいループ保持fixtureは修正前の両debugで失敗し、修正後の4構成は
各1,104テストで成功した（GIL 13 skip、FT 21 skip）。coroutine/async generatorも含む。
追加ループテストの3:3参照漏れ検査は両debugで成功した。
V26/V25の比較を開始した。source diffと4実行物を凍結し、個別の性能結果が
揃うまでは次のruntime変更・ビルドを行わない。

V26/V25の比較はFT 32回、GIL 32回とも全て成功し、前後hash一致。
固定ビルド・2ブロック内のworker bootstrap 95%区間を以下に保存する。
ft chaos: 0.93245, CI 0.91860–0.94311, blocks 0.94223/0.92278.
ft go: 0.98906, CI 0.98071–0.99716, blocks 0.98939/0.98872.
ft richards_super: 1.00688, CI 0.99738–1.02077, blocks 0.99731/1.01655.
ft docutils: 0.99427, CI 0.98456–1.00443, blocks 1.00175/0.98684.
ft sympy_sum: 0.99566, CI 0.98531–1.00747, blocks 0.98799/1.00340.
ft sqlalchemy_declarative: 0.99832, CI 0.99585–1.00078, blocks 0.99427/1.00238.
ft generators: 0.99716, CI 0.99203–1.00205, blocks 0.99644/0.99788.
ft unpack_sequence: 0.99902, CI 0.99601–1.00159, blocks 0.99914/0.99890.
gil chaos: 0.94848, CI 0.93343–0.96482, blocks 0.94103/0.95599.
gil telco: 0.98832, CI 0.96801–1.00629, blocks 0.98731/0.98934.
gil go: 0.99868, CI 0.99628–1.00087, blocks 0.99807/0.99930.
gil richards_super: 1.00734, CI 0.99890–1.02039, blocks 1.00359/1.01109.
gil many_optionals: 1.00114, CI 0.98752–1.01608, blocks 1.00685/0.99546.
gil docutils: 0.99812, CI 0.99458–1.00213, blocks 0.99535/1.00089.
gil sympy_sum: 0.99533, CI 0.98227–1.00785, blocks 0.99677/0.99389.
gil deepcopy: 0.98517, CI 0.96488–1.00438, blocks 0.98367/0.98667.
gil deepcopy_reduce: 0.99593, CI 0.98936–1.00318, blocks 0.99327/0.99859.
gil deepcopy_memo: 0.99691, CI 0.98522–1.00863, blocks 0.99781/0.99600.
chaosはFT約6.8%、GIL約5.2%短縮した。FT Goも約1.1%短縮。
Richards Superは両構成で約0.7%増加し、区間は1を含む。この不利な結果も残す。
元のchaosを40回、Richards Superを80回実行した後のexecutorをV25/V26・両構成で
採取し、変更したコードとの対応を確認する。これは性能測定ではなく、各workerの
JIT状態の分布を代表するものとも扱わない。B-treeは既存20,000件のCLI・入力・
検算を維持し、CPU 2、1 loop、3 warmup、5 value、各3プロセス、順序反転2ブロックで
V26/V25を比較する。元pyperformanceの大きいB-treeとは混同しない。

V26の補足確認を完了した。chaosのSpline.__call__@0は、GILで727 uopの
部分method→508 uopのtrace、FTで769→557。GetIndexもmethod entryから
閉じたループへ変わり、採取した全executorの合計はGIL 5,423→4,957、
FT 5,646→5,168となった。これは元の入力を使った単独の事後観測で、全workerを
代表する統計ではない。Richards Superは同じ25 executor、GIL 3,296/FT 4,472 uopで、
opcode/oparg/targetの列も両構成で一致した。約0.7%の時間差の原因は未特定。
これだけで配置が原因とは断定せず、最終main比較でも悪化を確認する。

既存の20,000件B-treeは24プロセス全て成功し、元のchecksum、JIT/GIL状態、
実行前後の実行物・標準拡張・stdlib・workload hashも検証した。
V26/V25はFT 1.00086、95%区間 .99416–1.00878、順序別 .99777/1.00396。
GIL 1.00145、区間 .99821–1.00448、順序別1.00289/1.00002。
chaosの両構成での改善と構造の変化を確認し、V26を採用する。

V27はsmall CFGの上限を実行命令128と疎なbytecode/cache領域1,024 code unitsに分ける。
1段の展開と既存のuop数の上限を維持する。cacheを多用する短いcalleeを展開する
テストと、実行処理が多いcalleeは別のmethodとして呼ぶテストを準備した。
型・calleeコードの変更、元のcallee内の例外処理も確認する。
性能比較の事前指定はV26と同じ対象にFT argparse/telcoを追加し、B-treeも同条件で
比較する。4構成での検証後にのみ計測し、cold CFG案はまだ適用しない。

V27の最初のGIL debug検証で、既存のcaller寿命テストのcalleeが新しい基準では
inline可能になり、METHOD_CALLを通らなくなった。assertを弱めず、lenの加算を
16個→32個（実行命令129）にして境界を保った。期待値は23→39に更新し、
callee自体にもMETHOD_EXITがあることを確認する。修正版は凍結V26 debugと
V27 debugの両方で成功した。初回の失敗ログは保存した。
その後V27 GIL debugの1,106テストと追加・更新3テストの3:3参照漏れ検査が成功。
残りの構成を検証してから、事前指定したV27/V26の比較へ進む。

V27の4構成は最終的に各1,106テストで成功した（GIL 13 skip、FT 21 skip）。
追加2テストと更新したcaller寿命テストは両debug構成の3:3検査も成功した。
4実行物をpython-v27として保存し、v27-runtime-source.diffを固定した。
V27/V26の比較を開始した。データ取得中は次のruntime変更や重い処理を行わない。

V27の事前指定した72回のpyperf呼び出し、24回のB-tree対照は全て成功した。
GILではGo 0.97485、telco 1.02786、many_optionals 1.01278、docutils 1.00418、
deepcopy 1.00770、memo 1.00928。telcoとargparseは両順序で悪化した。
FT telco 0.98672の改善もあるが、リグレッション解消の目的ではV27を採用しない。
全測定・4構成の実行物・失敗を含む検証ログを保存し、変更した3ファイルのみ
V26とバイト単位で同じ内容へ戻した。runtime全差分もv26-runtime-source.diffと一致。
次にcold CFG案を独立したV28として検証する。

V27のB-tree対照ではGIL 1.13130（95%区間1.10891–1.15072）、FT .99021だった。
このGIL約13%の悪化も不採用の根拠として残す。

V28はV26を基準に、128実行命令を超えるroot methodの分岐履歴が0/65535の
経路を探索し、cold blockを元bytecode位置へのMETHOD_DEOPTへ置き換える。
全CFGで解析した保守的な状態を維持し、後方辺の区間とFOR_ITERの両辺は残す。
4テストを追加。変更前は3件が「cold blockが省かれない」assertで両debug構成で
失敗し、通常のループ終了のテストは成功した。既存のcomplete methodのテストは
両分岐を交互に暖めて、完全なmethodと既存の閉じたcaller loopを検査する。
V27の展開上限変更は含めない。4構成での正しさ確認後にV28/V26を比較する。

V28の追加4テストはGIL debugで成功。最初の全体実行では既存2テストが
未使用分岐のcompileを前提にしていたため失敗した。完全methodのfixtureはcallerから
正負の両引数を使い、code budgetのfixtureも短いreturnと長いarmを交互に暖める。
完全method、既存loop保持、部分CFG、元の例外処理に関するassertは維持した。
調整後の2テストはV28と凍結V26のGIL debugで成功。失敗ログは保存した。

V28の最終検証は4構成で各1,108テスト成功（GIL 13 skip、FT 21 skip）。
追加4件と調整した既存2件は両debug構成の3:3参照漏れ検査も成功した。
4実行物をpython-v28として保存し、v28-runtime-source.diffを固定した。
V28/V26はCPU 2、各3 worker、5 warmup、5 value、min-time .1秒、逆順2ブロック。
FT 10仕様、GIL 8仕様と既存20,000件B-treeを事前指定し、逐次測定を開始した。
main比の結果ではなく、性能上の採否は未決定。

V28のFT測定でGoが両順序とも約32%悪化した。V28はそのまま採用しない。
コード上ではcold blockを早期に省くことで、complete/partial判定、既存loopを保つ
METHOD_CALL判定、後続blockに残るcode budgetまで変わることを確認した。
V29案は全CFGの元の生成結果でこれらを判定し、その後cold blockを通常のDEOPTと
NOPへ置き換える。元々completeだったmethodの呼び出し境界を維持する一方、
cold経路が多用されれば既存のfallback feedbackで見直す。
この案と境界検査のテストを準備したが、V28測定中のruntimeにはまだ適用していない。

V29案をさらに限定し、prune前のcomplete/partial判定とentry profile方針も維持する。
元からunsupported/budget退出があるmethodには従来どおりfallback feedbackを使う。
省いたcold armがhotへ変わった場合は既存のside traceで継続部分をcompileする。
この経路変化とcallee書き換えも新しい境界テストで検証する。まだruntimeは変更しない。

V28は不採用。72回のpyperf呼び出しと24回のB-tree対照は全て成功し、hashも確認した。
ft chaos: 0.99637, CI 0.98952–1.00381, blocks 0.99399/0.99875.
ft many_optionals: 0.98747, CI 0.97676–0.99945, blocks 0.98128/0.99369.
ft telco: 0.99590, CI 0.98168–1.01108, blocks 0.99605/0.99575.
ft go: 1.32024, CI 1.31335–1.32699, blocks 1.31740/1.32308.
ft richards_super: 1.00448, CI 0.98617–1.02429, blocks 1.02184/0.98742.
ft docutils: 1.00249, CI 0.99626–1.00896, blocks 1.01203/0.99305.
ft sympy_sum: 1.00230, CI 0.99151–1.01181, blocks 1.01084/0.99383.
ft sqlalchemy_declarative: 0.99974, CI 0.99091–1.00811, blocks 0.99768/1.00181.
ft generators: 0.99994, CI 0.99565–1.00460, blocks 1.00364/0.99625.
ft unpack_sequence: 1.00052, CI 0.99713–1.00428, blocks 0.99990/1.00114.
gil chaos: 1.01216, CI 0.99938–1.02560, blocks 1.02880/0.99578.
gil telco: 0.99331, CI 0.98753–0.99974, blocks 0.99523/0.99139.
gil go: 1.39556, CI 1.37280–1.41611, blocks 1.40548/1.38571.
gil richards_super: 1.00355, CI 0.99889–1.00921, blocks 0.99931/1.00780.
gil many_optionals: 1.00505, CI 0.99186–1.01866, blocks 0.99408/1.01613.
gil docutils: 0.99998, CI 0.99612–1.00400, blocks 1.00047/0.99949.
gil sympy_sum: 1.00106, CI 0.99293–1.00951, blocks 1.00425/0.99788.
gil deepcopy: 1.00235, CI 0.99401–1.01010, blocks 1.01095/0.99382.
gil deepcopy_reduce: 1.00812, CI 1.00222–1.01421, blocks 1.00354/1.01272.
gil deepcopy_memo: 0.99991, CI 0.99571–1.00417, blocks 1.00421/0.99564.
区間は同じ2ビルド・2ブロック内のworker bootstrapで、多重比較補正や再ビルドの変動を含まない。
GoはFT 1.32024、GIL 1.39556。B-treeはFT 1.00461、GIL .98208（GIL区間 .94719–1.00513）。
全試行を残す。V29はGoとB-treeを先に比較し、Goが両順序で2%以上悪化してworker区間も1を上回る場合、広い比較には進まない。

V29の境界テストは凍結V28の両debug構成で、calleeの加算がcaller traceへ展開される
ことを検出して失敗した。V29の後段pruneを適用し、両方向の分岐処理とbudget・
既存loop・entry profileの判定をprune前のCFGに保つ。既存のcold-pathテストに加え、
途中のbreakでwhile条件の履歴が偏る場合にもwhile-elseの終了経路を残すテストへ補強した。
GoとB-treeの対照を先に行う。いずれかが両順序で2%以上悪化し、区間の下限も1を
上回る場合は広い比較を打ち切る。良ければ他の事前指定項目を測る。

V29の初回GIL debug全体検証は追加した境界テスト1件のみ失敗した。
原因は「function.__code__を差し替えると旧codeのmethod自体も無効になる」という
テスト側の誤った前提。executorはcodeに属し、同じ旧codeを使う別functionには使える。
caller traceの無効化と新しい戻り値のassertは維持し、旧codeで作った別functionの
正しい戻り値も検査する形へ修正した。修正版の単独検証は成功した。
境界保持・hotへ変わったcold armのside trace・補強したwhile-elseは通過している。
Goの単独採取ではV28でBoard.useful@0のmethod（FT879/GIL742 uop）が消えた。
生成uop合計の減少を速度向上と同一視せず、V29で元のmethodの維持と性能を確認する。

V29も不採用。4構成の最終各1,109テストと両debugの関連7件3:3検査は成功した。
事前指定したGo/B-treeの対照で打ち切り条件に達したため、他のベンチマークは測らない。
Go ft: 1.02099, blocks [1.0198703232901423, 1.0221171076089346], CI [1.0171083687807192, 1.023759008276752].
Go gil: 1.05769, blocks [1.0672843105020497, 1.0481740121233092], CI [1.0470991065786714, 1.0692968215957648].
GIL Goは両順序で2%以上悪化し区間の下限も1を超えた。FTも平均約2.1%増加。
B-treeはFT .98888、GIL 1.00362。改善した試行だけを選ばずV26へ戻す。
ユーザーの追加指示に従い、採用済みの修正と検証レポートをコミットし、そのcommitの
FT（PGO/LTOなし）とGIL PGO/full-LTOを準備する。mainの同条件2本と合わせて
夜間に実行できる4構成の全件比較をprepare-onlyまで行う。全件測定はユーザーが実行する。

## 2026-09-18: 採用版を確定して夜間比較へ

V29の追加6診断も正常終了。runtimeをV26へ戻し、Include/Python/Lib/test/Modules/
Objects/Tools/cases_generatorの全差分がv26-runtime-source.diffと完全一致した。
最終採用はV26、V27–V29は不採用。現時点でmain比の全回帰を解消したとは言えない。

四者比較runnerをコミット後のビルド記録へ切り替える。未コミット差分だけでなく、
runtime・標準ライブラリ・ビルド入力の全対象ファイルをFT/PGO両方で照合し、
commit後の空diffによる同一性検証の抜けを防ぐ。異なるソースコピーの改変、空の
ソースmanifest、拡張だけの更新を拒否するテストを追加した。

次の順序: ハーネス検証→採用版とレポートをcommit→FTとGIL PGO/full-LTOをbuild→
最終正しさ・互換性の確認→全97仕様のprepare-only。全件の性能測定は実行しない。
ビルド・準備の実績はcommitted-final-*.jsonと準備先のpreparation.jsonに記録する。

コミット前のハーネス20テスト、git diff --check、bash構文検査は成功した。
benchmarks/go.pyの実行権限変更はユーザーの既存変更なのでコミット対象から除外する。

ステージ後の差分検査では既存main-llvm21.patchの空行context（単一空白）2行だけが
whitespace警告になった。unified diffのcontextと既存キャッシュのSHAを維持するため
変更しない。このpatchを除くステージ済み全差分のgit diff --checkは成功した。

## コミット後の最終ビルド・準備（2026-09-18）

採用版runtimeは `718d2ff2ef9705a8cdbfa7b345038f5b484a7343` でコミットした。
コミット内容が保存済みV26のruntime差分と完全一致することも確認済み。
同commitのソース3,943ファイルがFT作業ツリーとPGO用archiveで一致する。

| 最終候補 | SHA-256 | 正しさの検証 |
|---|---|---|
| FT、PGO/LTOなし | `5483c5085c6a50e0891e864305261d0f7c82d5dad7619d5b5a403bb6947d8fb0` | 2,389テスト、91 skip、成功 |
| GIL、PGO/full LTO | `912a24825e847ef11d469fab72b566c45bb656d765e59cfb7bead6c2c962877c` | 2,389テスト、76 skip、成功 |

GIL PGOはGCC 13.3.0、JIT無効、seed 0、cold private pycacheで43/43学習テスト成功。
学習成功後の354個のプロファイルを記録し、bootstrapのプロファイルは分離した。
各開発用ビルドもV26へ再ビルドしてあり、不採用V29のままのlive実行ファイルは残していない。

`jit-artifacts/pyperformance-four-way-fixed/` はFT/GILとも97仕様・23依存グループを
prepare-onlyで準備済み。mainのSHAは元の2本と一致する。FastAPIは依存未対応として
残し、同期SQLAlchemy 2仕様はgreenletを省いて準備した。全件のstate.jsonは未作成で、
本測定は開始していない。短い互換性確認を別ディレクトリで実行中。

ソース・ビルド・正しさ・PGO学習・準備コマンドの記録は
`jit-artifacts/pyperformance-fixes-20260917/committed-final-*.json` と対応ログにある。
これらは新しい最終バイナリの速度を実証する結果ではない。main比と回帰の残存は
夜間の全件比較で評価する。

最終smokeの36呼び出しでFT candidateのDaskだけが校正workerのSIGSEGVで失敗した。
他35回は成功。本測定は未実行のまま、準備完了の判定を保留して追加診断に進む。
単独workerとGDBの校正workerは一度ずつ成功。現在main/JIT無効/debugとの対照を
実行し、全ログをfinal-dask-*へ保存している。この1回の失敗を除外して成功とは扱わない。

## Daskの追加診断と夜間用runnerの更新

初回smokeではFT candidateのDask校正workerが1回SIGSEGV。他35呼び出しは成功した。
単独worker16回（candidate JIT/debug/main/candidate JIT無効を各4回）、
元のpyperf親子構成20回、cold import 9回（candidate JIT/main/candidate JIT無効を各3回）は
全て成功した。別の単独workerとGDBの校正workerも成功したが、原因は未特定。
再現しないことを根拠に解決済みとはしない。推測だけによるruntime変更は加えていない。

夜間用runnerは全4構成でPYTHONFAULTHANDLER=1をworkerへ継承し、
faulthandler_enabledを結果metadataに記録する。再発時はPython/Cスタックをログへ残す。
Daskを測定から外さず、失敗を含む全記録を維持する。ハーネス20テストは成功した。
本測定の新しい出力先はjit-artifacts/pyperformance-four-way-overnight。
旧fixed/fixed-smokeは元のハーネスに対応する記録として保存し、再開には使わない。
runtimeは引き続き718d2ff2ef9で、両ビルドの実行物とソースは変更していない。

## 夜間実行の準備完了

最終出力先 `jit-artifacts/pyperformance-four-way-overnight/` でFT/GILとも
97仕様・23依存グループの準備と入力同一性の検証が成功した。本測定のstate.jsonは
両方とも存在せず、全件測定はユーザー実行待ち。

新しい環境でDask/concurrent_imap/python_startupをmain/candidate・FT/GILの
計12回確認し、全て成功。結果の全workerでfaulthandler_enabled=1を確認した。
さらに候補GIL PGOの元の6-worker・5 warmup・5 value条件でbench_mp_poolと
bench_thread_poolが完走し、両方に6 workerがあることとJIT/GIL状態を検証した。
記録は `jit-artifacts/pyperformance-fixes-20260917/overnight-readiness.json` と
`overnight-*.log/json`。これらの短い確認をmain比の性能評価には使わない。

Daskの最初のSIGSEGVは原因未特定のまま。再試行の成功で取り消さず、
all_failures_resolved=falseとして記録する。回帰の全解消も未確認。
次の作業はユーザーによる全件測定と、その結果の比較・残る失敗/回帰の解析。

```bash
./benchmarks/run_pyperformance_four_way.sh jit-artifacts/pyperformance-four-way-overnight --run-only
```

FastAPIの未対応やtimeoutがあれば終了コード1になるが、他の測定は継続して保存される。
NetworkXのworker上限15秒を維持する。実行中は比較対象ビルド・依存・runnerを変更しない。

## 2026-09-19: 夜間4構成比較の結果レポート

ユーザー実行済みの `jit-artifacts/pyperformance-four-way-overnight/` を解析し、
`benchmarks/pyperformance_overnight_report.md` に日本語でまとめた。
全result一覧、全未完了仕様、前回との共通項目比較、worker単位の区間推定、
集計対象を変えた感度分析、クラッシュログの停止位置を記載した。
今回は既存データの解析のみで、追加ベンチマーク・再ビルド・runtime修正は行っていない。

| 構成 | 完了仕様 | result数 | candidate/main幾何平均 | 実行時間変化 | 2%以上悪化 |
|---|---:|---:|---:|---:|---:|
| FT、PGO/LTOなし | 94/97 | 121 | 0.910105 | −8.99% | 11 |
| GIL、PGO/full LTO | 78/97 | 105 | 0.983138 | −1.69% | 23 |

main/candidateの両ブロックが成功した仕様だけを主集計に使用した。
失敗した仕様の成功ブロックは採用しない。欠落込みの全97仕様の性能とは扱わない。
2%は効果量の分類であって有意差の基準ではない。FTの悪化11件中unpickleと
shortest_pathは順序で方向が逆転する。他9件とGILの23件は両順序で悪化し、
固定ビルド・固定ブロック内のworker bootstrap 95%区間も1を上回った。
区間は再ビルドや別環境の変動、多重比較の選択効果を含まない。

以前のunpack_sequence、deepcopy、pprint、loggingの大きな悪化は縮小または反転した。
GoはFT 14.02%、GIL 6.73%短縮。richards_superはFT 61.20%短縮だがGIL 2.30%悪化。
btreeは今回のpyperformance対象外。同期SQLAlchemyはgreenlet省略で両仕様が完了し、
declarativeはFT 2.19%悪化、GIL 5.61%短縮だった。

最も大きい新たな回帰はregex_compile（FT 1.745倍、GIL 3.228倍）。
両ブロックで再現し、前回からmainの時間はほぼ変わらない。停止位置や速度差だけでは
原因を確定せず、採取入力・仕事量、JITコンパイルと無効化、生成コードを次に調べる。
GILは最大級の改善3件を除くと幾何平均1.004947で、広範な回帰解消は未達成。

FT DaskのSIGSEGVは第2ブロックcandidateで再発した。faulthandlerと固定バイナリの
addr2lineから、distributedの別スレッドframeの `f_code` 参照、
`PyFrame_GetCode` / `Py_INCREF` 中の停止まで特定した。根本原因は未特定。
GILでは第2ブロックにmain 10回・candidate 11回、計21回のSIGSEGVがあり、
18ログはGC中。async_tree群とdocutilsに集中した。ほかにSSLエラー、TypeErrorもある。
mainでも起きることを理由にcandidateの問題を否定せず、共通原因も調べる必要がある。
FastAPI未対応とNetworkXのtimeoutは継続。NetworkX k-coreは約18秒で打ち切られ、
worker上限15秒は機能した。WebSocket・Genshi・concurrent_imapは完了した。

検証: FT/GILとも完走記録と測定後同一性検証はtrue。今回の `--phase verify` も両方成功。
成功生JSONから全workerの値とstateの平均を再計算し、保存SHAと一致した。
前回結果のSHA、共通仕様スクリプト、mainバイナリの不変性も確認した。
解析とアドレス解決の記録は `jit-artifacts/pyperformance-overnight-analysis-20260919/`。
候補runtimeは718d2ff2ef9のまま、ハーネスは08a1b60bdfc。

次の優先順位は、(1) FT DaskとGIL両側のクラッシュを分けて再現・切り分け、
(2) regex_compileの大幅悪化を導入した差分の特定、(3) GILのtelco・Genshi・
argparse・pickle・richards_superとFTの残る悪化の調査。

## 2026-09-19: regex_compileの回帰修正に着手

夜間レポートと計画の更新を `14defe7e06e` にコミットした。既存のユーザー変更である
benchmarks/go.pyの実行権限は維持した。今回の実装対象はregex_compileの回帰。

まず夜間と同じ固定4バイナリ・同じbenchmarkを使い、JIT有無で採取入力の件数・SHAと
固定仕事量の時間を確認する。CPU 2、seed 0、5 warmup・5 value、順序を反転した
2ブロックを診断として保存する。主性能評価には元のpyperf worker構成を使用する。
探索用ビルドはPGO/LTOなしを基本とし、修正が有望なら元のGIL PGO/full-LTO条件でも確認する。
修正の対象経路と境界条件をテストし、regex_compileのmain比と修正前比に加え、
regex_effbot/regex_v8・Go・richards_super・unpack_sequenceへの影響も確認する。
全試行を `jit-artifacts/regex-compile-20260919/` に残す。

初期診断: 全4バイナリ・JIT有無で入力は4,267件、SHAも一致した。JIT無効時の
候補/mainはほぼ同時間で、JIT有効時のみ大幅悪化。固定仕事量のperfでは候補の
cycles sampleの22.33%がmethod_merge_block、8.57%がmethod_decode_cfgだった。
debug診断の1 warmup・1 value（採取時も含む）では_parseのmethod却下が1,317回。
735回はinlined loop、582回はanalyze段階で、重いコンパイル再試行を繰り返していた。

修正案は既存の閉じたインライン化ループを優先してmethodを却下した際にも
co_executors->prefer_traceを保持すること。既存のpartial methodの頻繁なfallbackと
同じ選択を使い、入口traceの無効化・再作成ごとに同じmethod解析をやり直さない。
関数名や正規表現に依存する条件は加えない。
既存テストに依存無効化後・空ループで再warmupする検査を追加した。
修正前はGIL/FT debugともMETHOD_EXITが再出現して失敗、修正後は両debugと
GIL releaseで成功した。新しいFT releaseをビルド中。夜間の4バイナリは保持する。

R1検証: _parseのmethod却下は診断で1回になった。関連10ファイル、各1,274テストが
GIL/FT・debug/releaseの4構成で成功し、debug両方の追加ケース3:3リーク検査も成功。
最初のsandbox内test_reはforkserverのUnix socketでPermissionErrorだった。
ローカルソケットを許可した再検証で同テストを含めて成功し、テスト除外は行っていない。
元のpyperf条件（6 worker、5 warmup/value、逆順2ブロック）のFTは、
main約117.7ms、修正前約205.4ms、R1約126.0ms。約7%の回帰が残り、R1で完了とはしない。

R2の仮説: TRACE_RECORDがトレース優先にした関数のRESUME/JUMP_BACKWARDにも
specialization用の強制ゼロを設定し、再試行のbackoffを消している。
選択済みのprefer_traceに限りそのcountdownを保持する。新規の関数のwarmupや
既存のゼロcounterのwrap防止は維持する。別callerによる記録後にcountdownが
ゼロになることをR1で検出したテストを追加し、変更後の動作と性能を検証する。
テスト初稿で仮定した閉ループは成立せず、必要なPUSH_FRAMEの検査を残した。
初稿の失敗ログも保存し、countdownそのものの失敗を別ログで確認した。

R2の短い固定仕事量screenはFT約98–100ms（main約118ms、修正前約204ms）、
GIL PGO/LTOなし約85ms（修正前約242ms）。両順序で改善し、入力SHAは一致。
これを本測定の代わりにはせず、関連テストを4構成で再検証してから、
GIL PGO/full-LTOを夜間と同じ43テスト・JIT無効・seed 0・cold private pycacheで新規学習する。
最終測定はregex_compileを6 worker、残る事前指定5仕様を3 worker、各5 warmup/value、
2ブロックの逆順でmain/修正前/修正後を比較する。対象はFTとGIL PGO/full-LTO。
他の重い処理とは競合させない。改善しなかった試行も保存する。

R2の4構成は各1,274テスト成功（GIL release 15 skip/debug 14 skip、
FT release 23 skip/debug 22 skip）。両debugの追加ケース3:3リーク検査も成功。
PGO用の隔離ソースは作業ツリーの対象3,943ファイルとSHAが一致する。
新規PGOビルドを開始し、完了後に同じ関連テストをJIT有効で実行してから最終測定へ進む。

PGOビルド完了: 43/43学習ファイル、10,468テスト（460 skip）、354個の学習profile。
生成303.0秒・学習141.4秒・最終ビルド201.0秒。JIT有効で関連1,274テスト（15 skip）も成功。
実行物SHAは `c4f7559ec0b596dc7f4d82be4f11616cecd32de74e38aeed64ef38af0da69d84`。
ソース・実行物を固定して、FTとGIL PGO/full-LTOの最終6仕様比較を開始した。

最終6仕様は72呼び出し全て成功し、同一性検証も全4測定群で成功。
regex_compileはFTで修正前/main 1.74483→修正後/main .83210、
GIL PGO/full-LTOで3.21821→.98135。両順序で改善した。
GIL Goは修正後6 worker中1つが約64.94ms、他5つが約55–56msで、
全値の修正後/修正前は1.02897、worker区間 .99887–1.08043。
遅いworker内の5値はすべて遅く、単発値の外れではない。削除しない。
追加診断として同じmain/修正前/修正後でGoを各8 worker×逆順2ブロック測定する。
まず追加分16 worker/側と元の6 worker/側を分けて報告し、遅い群の再発を確認する。
追加後に都合の良い測定だけへ主集計を置き換えない。

最終判定: regex_compileの回帰修正を採用する。FTは117.563ms→97.825ms
（修正後/main .83210、95%区間 .82688–.83809）、GIL PGO/full-LTOは
75.435ms→74.026ms（.98135、区間 .96091–.99609）。修正前からはそれぞれ
52.31%、69.51%短縮した。中央値を使ったmain比もFT .82899、GIL .99191。

Go追加分の修正後/修正前は .99945、区間 .99553–1.00353、main比 .93216。
追加16 worker/側では低速群は再発しなかった。初回の1 workerは保持し、原因未特定と記録。
再現性のあるGoの回帰は未確認。GIL regex_v8の約0.70%増加は両順序で観測した。
全ベンチマークの回帰解消・完全不変とは扱わない。

性能測定後のFT固定仕事量perfでは、R1からR2でtrace翻訳/最適化のself sample比が
4.78%/2.66%から両方0.1%未満へ低下し、推定cyclesも197.4億→157.3億。
import・5 warmup・30反復を含む各1回の診断で、主性能測定とは分けた。lost sampleは両方0。

最終レポートは `benchmarks/regex_compile_regression_report.md`。
実装はPython/optimizer.cの選択保存とPython/bytecodes.cのbackoff保持、
生成した2ヘッダ、既存テストの拡張。元の夜間4実行物は保持した。
今回の修正・新レポート・計画追記は未コミット。最初の比較レポートのコミットは14defe7e06e。
次は必要に応じてこの修正版で全体比較し、元のレポートに残る他の回帰とクラッシュを調べる。


## 2026-09-19: C decimalと3%以上の回帰解消

対象は直近の4構成比較（FT、PGO/LTOなし、およびGIL、PGO/full LTO）の
main比の実行時間増加3%以上。regex_compile修正済みの作業ツリーを出発点にする。
元の入力・依存版・仕事量を維持し、まず前回3%以上の全項目とtelcoを逆順2ブロックで
再測定する。screenは各3 worker、5 warmup/value、min-time 0.1秒、CPU 2、seed 0。
主集計はworker平均の等重み平均とブロック比の幾何平均。最終確認では全成功仕様も
対象に含め、新たな回帰を確認する。失敗・timeout・低速workerは保存する。

_decimal不在の原因はconfigure時のlibmpdec未検出。公式mpdecimal 4.0.1をSHA検証して
専用prefixへビルドする。初期の固定バイナリ比較には各ABI/ヘッダに対応する
FP有効・PGO/LTOなしの_decimal拡張を外部overlayとして追加し、元の4実行物は保持する。
coreのGIL PGO/full LTO設定は維持する。両側でdecimal.Decimal is _decimal.Decimalと
ロードされた拡張SHAを検証する。最終ビルドはconfigureで同ライブラリを検出させる。
初回libmpdec checkはsandboxのDNS制限で公式テストデータ取得に失敗したため、
ネットワーク許可を付けて再実行する。数値演算の不一致を示す失敗ではない。

記録先: jit-artifacts/regressions-20260919/。探索時はPGO/LTOを避け、必要な最後の
GIL比較のみPGO/full LTOで検証する。今回の新たなコミットは依頼されていない。

libmpdecのstatic/shared公式・追加テストは成功。CPython test_decimalは4構成で
各738テスト（9 skip）成功。初期overlay測定はPGO学習にもtest_decimalが含まれることを
再確認したため途中で停止し、部分データと理由を保存した。C decimalありの学習を
両側でそろえた新しい4ビルドをr0-*へ作成する。PGOはJIT無効・seed 0・専用cold pycache、
bootstrap profile分離という従来の規約を維持する。libmpdecは同一FP有効static library。
完成後の通常importでC backendを検証し、overlay不要の比較へ移行する。

ビルド中の非計時debug診断ではGenshi XMLの2回描画とargparseの2回実行が成功し、
regex_compileで見つけたmethod却下の反復ログは出なかった。この小さい診断だけで
コンパイル費用を否定せず、新しいPGO対照でperfを採って処理箇所を確認する。

測定ハーネスにtelcoのC decimal必須チェックを追加。workerの開始/終了でbackendを
確認し、_decimalの実パス・libmpdec版をmetadataへ記録する。将来の測定で同名の
Python fallbackを混ぜない。検証用の旧controllerにも_decimalがないため、追加の
単体テスト初稿のホスト依存を取り除き、C backendの同一性/欠落/fallbackを明示的に
模擬する形へ直した。4実行物での実C backend検証は別途成功済み。

C版のtelco出力検証: 元の5,000件の入力をC/Python両backendで計算し、全4実行物で
出力SHA 0abe923a18fc0268f442198542abcba203623a1e31136bd9e97a7a50343c5617が一致した。
測定ハーネス22テスト成功。新PGOのmain/候補は両方43/43ファイル・10,623テスト
（265 skip）で学習成功した。最終リンクおよびFTビルドを継続している。

r0 screenの順序は、1仕様ごとにmain/candidate、candidate/mainの両ブロックを
連続して測定してから次へ進む。長い仕様間の時刻差を避け、完了した仕様から解析する。
C版telco、Genshi、pickle、argparseを先に確認し、前回3%以上の全仕様を含める。
worker数・warmup・value・入力は既定の3/5/5を維持する。

C decimal入りr0の4ビルド完成。通常importでC backend確認済み（overlay不要）。

| Build | Python SHA-256 | libmpdec |
|---|---|---|
| r0-ft-main | 44c9f1615910b76898e1eb6cd478a36c151f21cf5bc99ea95aa6ac115c85fefb | 4.0.1 |
| r0-ft-candidate | af62115344bbcd7accbb325a560cde43cde723a5a01b5158bc3fff6244ed0d7c | 4.0.1 |
| r0-gil-main | 29f98fde43417b99bad02a6710ad55e55f343a574f8fff306932d1e75b010044 | 4.0.1 |
| r0-gil-candidate | 4dfb2b28fd032c4366361a1fa3022b499cce8393949c835f774dd1661357e4e5 | 4.0.1 |

4構成の関連テスト後、r0の全回帰screenを逐次実行する。結果はr0-*-state.json、
分析はr0-*-analysis.jsonに保存する。元の実行物は変更していない。

r0の最初の同一プロセス検証では、test_decimalの後のmain test_capi.test_optに21失敗。
単独test_capi.test_optは新旧mainとも308テスト（3 skip）成功。C decimalを追加した
旧mainでもtest_decimal→test_capi.test_optの順で同じ21テストが失敗し、期待された
builtinsの定数化/ガード削除が行われないことを確認した。値の計算結果の不一致ではない。
新たなruntime差分やC decimalの誤計算とせず、順序依存の既存問題として全ログを保存。
各ファイルを別workerで実行する通常のregrtest -j1で全11ファイルを検証する。
テスト本文・期待値・選択は変更しない。結果を同一プロセス実行成功と表現しない。

r0関連テストは-j1で4構成すべて成功。mainは各1,831テスト（GIL22/FT327 skip）、
候補は各2,012テスト（GIL24/FT32 skip）。最初の同一プロセス順序依存は未解決として残す。

GIL r0 screenの完了項目の暫定値: telco 1.0111、pickle_list 1.0020、pickle_dict 0.9926。
前回のこれらの大幅な悪化は新条件で再現しない。ただしC版追加と両側のPGO再学習を
含む条件変更であり、JIT修正の効果とは呼ばない。Genshi XML1.0923/text1.0785、
argparse many_optionals1.1264は両順序で悪化する。SymPy sum1.0235は両ブロックで
1.0110/1.0361と差があり、最終の増強測定で確認する。全項目screenは実行中。
Genshiでは式評価ごとにglobalsを作る処理とJIT guard/invalidationの関係を仮説とし、
screen完了後に同じ固定仕事量のperfで調べる。まだ原因を確定したとは扱わない。

R1試作（未ビルド・未採用）: _PyFunction_Vectorcallのmethod入口探索を短くする。
既存_ExecutorArrayのpaddingに収まるuint16のindex+1を記録し、通常traceや未コンパイルの
C→Python呼び出しでは先頭bytecode/index/executorの連続ロードを避ける。
method挿入時に設定、detach/無効化時に消す。既存の引数・validity・JIT状態・観測hookの
条件は維持する。コード差替え、global無効化直後、再warmup、引数エラーをC側mapから
検証するテストを追加した。Genshi/argparseの原因をこれと確定したわけではない。
r0のコピー済みビルド/ソースは不変で、screenにこの試作は入らない。screen完了後に
perf診断とPGO/LTOなしの対照を行い、有効でなければ試作を取り除く。

r0 screen完了: GIL31結果、FT10結果、失敗0、開始終了のidentity一致。
GILで残る3%以上はmany_optionals1.1264、genshi_xml1.0923、genshi_text1.0785、
dulwich_log1.0608、base16_small1.0577、nbody1.0562、sqlglot_v2_optimize1.0407、
sqlglot_v2_transpile1.0401、pickle_pure_python1.0340。
FTはdocutils1.0382、regex_v8 1.0361、sympy_sum1.0345。
このscreenは旧回帰仕様の選択集合であり、全体の回帰なしを意味しない。
GIL perfではGenshiのtupleiter_next/tuple_iter/汎用unpack費用増を観測した。
JITコードの帰属を追加診断し、汎用展開に落ちる原因を確認する。
R1はキーワードあり/引数個数不一致もcache参照前に除外するよう試作を調整。
まだ未ビルド・未採用。r0のtiming/profile対象は不変。

JIT帰属付きGenshi診断で、候補のTemplate._flatten/WhitespaceFilterのtraceに
汎用_UNPACK_SEQUENCEが残ることを確認。mainの対応する採取済みexecutorには汎用unpackが
ない。R2試作として汎用unpack helperのexact tuple・個数一致・starなしの場合に
iteratorの生成/呼び出しを省く。tuple subclass、個数不一致、star付きは従来経路。
FTでも不変のtuple要素を新しい所有参照として取得する。polymorphic traceの後のtuple、
subclassの独自iter、個数エラーを検証するテストを追加。まだ未ビルド。
R1ビルドのsource snapshot取得後に編集したため、R1にはこの変更は入らない。

nbodyの主traceはmain415uop/16KiB、候補379uop/20KiB。主なuop差は
UNPACK_LIST_TO_FAST_3とborrowed-input添字取得。少ないuopでも生成コードが大きくなるため、
融合の利益を分離測定する。まだ原因・採用する修正を確定していない。

R1 GIL開発版は関連5ファイル1,400テスト（22 skip）成功。速度はこれから比較する。
R2のsource snapshot取得後、R3試作としてtraceの短いunpack融合を制限した。
method側の適用範囲は維持し、traceの2/3要素は既存stack cacheと通常storeを使う。
4要素以上は従来どおり。短いlist unpackのtraceと結果を検証するテストを追加。
採用判断にはnbody、Genshi、unpack_sequence、Go/Richardsの対照を含める。
なお前記16/20KiBはページ単位のJIT割当範囲であり、実命令バイト数の25%増を意味しない。
該当する3要素list融合stencilは406bytes、元unpackは131bytesで、融合側には
3個のループと追加レジスタ退避がある。この費用を時間測定で確認する。

R2 GIL開発版は関連7ファイル1,409テスト（22 skip）成功。
R3は既存test_non_unique_three_tuple_unpackの「融合命令を生成する」という期待値だけが
失敗した。短いtrace融合を外す設計に合わせ、通常_UNPACK_SEQUENCE_TUPLEを要求する
期待値へ変更し、結果とunique参照の区別の検査は維持した。
R3 binary/source snapshotは不変のまま、PYTHONPATH=作業ツリーLibで修正済みのテストを
読み、7ファイル1,410テスト（22 skip）成功。旧失敗ログも保持する。
R1/R0、R2/R1、R3/R2の固定開発版比較を順次実行する。

R4試作（未ビルド）: 全bytecodeを変換できたmethodでも、残ったMETHOD_CALLのcalleeが
MAKE_CELL等の未対応入口を持つと呼出元に戻れず、毎回Tier 1へ落ちる。従来はcompleteと
判定してfallback監視を省いていた。argparse採取ではこの分類のmethodが多数存在した。
METHOD_CALLが残るmethodにも既存256-entry window/32-missの監視を適用する。
完全変換時のmethod保持方針は最初は維持し、実際の繰返しfallbackでentry traceへ移る。
calleeのMAKE_CELL入口を使い、従来のcomplete判定・繰返し退出・再加熱後の結果を
検証するテストを追加。argparseの原因をこれで確定したとはまだ扱わない。

R1/R0開発比較はGenshi text1.0196、XML1.0045、argparse0.9868。
argparseの2ブロックは1.0111/0.9632と一致せず、Genshi textは悪化。
入口cache試作の明確な利益を確認できないため採用せず、各単一因子の診断後に外す。
R2/R1のGenshiは両ブロックで約8%短縮。残りの比較を継続中。

R5試作（未ビルド）: binasciiのignorecharsなし16進デコードを2文字ずつ処理し、
各文字のhalf-byte状態分岐を省く。C処理の改善でありJIT最適化とは呼ばない。
末尾が奇数の場合も文字検証を先に行い、既存のinvalid-character優先のエラーを維持。
空/非空ignorechars、両API、全バイト範囲、ペア/端数/エラー優先度を検査するテストを追加。
R4/R5の差分を各patchへ固定し、現在実行中の比較に混入させない。

R6試作（未ビルド）: FT regex_v8のperf annotateでBRANCH入口のLASTMARK_SAVE周辺が熱い。
literal/setの先頭検査だけですべての選択肢を棄却できる場合もcapture情報を保存していた。
同じ検査で最初の候補を探してから保存するよう変更し、再試行時も同じhelperを使う。
これはC正規表現エンジンの処理削減であり、命令配置のpaddingを選ぶ方法は使わない。
ネストしたcapture/repeat、候補の途中失敗、bytesとUnicodeの各幅を検証するテストを追加。
初回FT perf診断中の無効なoptional-hook追加は既述のharness noteに記録済み。
採用する原因の説明には固定したscriptでの再診断と通常の時間比較を必要とする。

R3/R2開発比較完了、全6結果成功、identity一致。nbody0.9747、Genshi text0.9592/XML0.9461、
Go0.9851、unpack_sequence1.0011、richards_super1.0042。短い融合の制限を維持する。
R1の入口index cacheを作業ツリーから取り除いた（専用の追加テストも除去）。
凍結済みのr1–r6ビルド/patchは因子を比較するため元のまま保持する。
作業ツリーの統合候補（R1除去、R2–R6あり）をr7.patchにも保存した。
R4–R6の個別ビルドとテストをこれから行うため、統合候補の完成はまだ主張しない。

R4初回検証はtest_resumeのexecutor常駐前提と、test_reのsandbox内ソケット拒否で失敗。
再帰の値は新旧候補の単独診断で一致し、単独ではexecutorも残った。full suiteでは
fallback監視による加熱中の退避があり得るため、重複した入口validityチェックを調べる
このテストはcalleeのない関数をmapで同回数温める形にした。入口命令列への要求は維持。
再帰・再帰上限・callee fallbackの別テストも含め、ローカルソケットを許可して再検証。
凍結したR4 binaryのまま最新テストを作業ツリーLibから読み、10ファイル1,889テスト
（41 skip）が成功した。最初の失敗と診断は削除していない。
R5/R6用にはテスト修正だけを追加したr5b/r6b.patchを作成し、旧patchも保存する。

R5/R6のGIL開発版が完成し、各10ファイル1,889/1,890テスト（41 skip）成功。
R4/R3はargparse、dulwich、sqlglot 2仕様、pure-Python pickle、SymPy、Go、richards_super、
R5/R4はbase64全11結果、R6/R5はregex_v8、regex_effbot、regex_compile、docutilsを比較する。
各比較は3 worker・5 warmup・5 value・逆順2ブロックを維持し、逐次実行する。
argparseの診断用mappingをwarmup後と測定後の両方で採り、新たに生成されたJITコードの
帰属漏れを補う。診断workerは各labelの専用コピーへ固定し、終了時にSHAを再検証する。

R4/R3比較のGoで約14%以上の悪化を観測したため、R4の広い監視は不採用。
complete methodの型ガード退出までpartialと同じように数える点を分離する。
R8試作ではPROFILEを残し、METHOD_CALLから戻れない場合は数えるが、complete methodの
通常型ガード退出は従来どおりside traceへ進める。partial methodの監視は維持。
未対応callee入口からの繰返し退出テストに加え、calleeは使えるがint→floatのguard退出を
繰り返すcomplete methodが有効なまま残ることを検証するテストを追加（まだ未実行）。
R4–R6の現在の測定は凍結済みなので、この変更を混ぜずに完了させる。

R4–R6の比較完了、各11/11/4結果、失敗0、identity一致。
R4のGo1.1405は両ブロック1.1397/1.1413。argparse0.9846、SymPy sum0.9803の利益では
正当化できず、広い監視は不採用。元Goを40回動かしたexecutor診断ではBoard.move、
Board.random_move、EmptySet.random_choice等のmethodが消える差を確認した。
R5のbase16 small0.9105/large0.8683、他base64結果の最大悪化1.0040。
R6はregex_v8 0.9152、regex_effbot0.9723、regex_compile0.9946、docutils1.0003。
R8の通常guard退出を数えない変更をR7（R1除去後の広い監視）と比較するため、
両ソースpatchを固定して新規開発ビルドを行う。最終PGO/FTでのmain比はまだ未確認。

R7/R8は11ファイル3,855/3,856テスト（41 skip）成功。R8のguard保持テストはR6で
期待どおり失敗しR8で成功したが、GoのR8/R7比1.0081（1.0092/1.0070）はR4の悪化を
回復しない。R8も不採用として追加比較を途中で停止し、取得済みargparseの4回と
SymPyの部分結果も保持した（r8-trial-stop.json）。この部分集合を完成比較としない。
広い監視・狭い監視の両方と専用テストを作業ツリーから除去し、test_resumeも元に戻した。
R9統合候補はR2/R3/R5/R6と以前のregex_compile修正だけ。これを最終構成でscreenする。
R6/R5の固定scriptによるperf statはcycles比0.9011、instructions比1.0213。
capture保存を遅らせた経路で時間は減るが、実行命令数削減とは主張しない。

R9のソースを固定してFT/GIL PGO+LTOのビルドを開始。これと独立にR10を準備した。
R10はLOAD_ATTR_METHOD_NO_DICTの型guardで確定するimmutable static typeのdescriptorを
methodの抽象スタックへ伝え、既存FAST/FAST_WITH_KEYWORDS_INLINE命令を使う。
同じdescriptor・receiver型で証明済みのcallable guardだけを省く。型変更・heap type・FTは
対象外にし、通常の呼び出し境界・例外・後始末を維持する。dict.getのmissing/default、
unhashable、subclass override、str.replaceの型変更・エラーを検証するテストを追加。
まだ未ビルドで、改善したともargparseの原因を確定したとも扱わない。
R9の測定へ混ぜないようr10.patchへ別途固定した。

R9 FT版は16ファイル4,297テスト（49 skip）成功。GILのPGO学習は43ファイル・
10,628テスト（265 skip）で成功し、LTOの最終リンク中。mainは10,623テストで、
候補は追加したC処理のテストを5件多く学習している。この差を隠さず記録し、
R5/R6そのものの効果の根拠は既述のPGO/LTOなし単一因子比較と区別する。
四者比較runnerは依存キャッシュと実行物を分離し、新C-decimal main/候補のbuild record・
source・全標準拡張を照合するよう更新。通常importのC backend確認と同じmpdecimal archive
のSHA比較を加え、ハーネス23テストが成功。候補の既定値は現時点ではR9。
R10テストにはdict keyの__hash__からcaller codeを差し替えGCを走らせる場合も追加した。

R9の両最終構成が完成し、各16ファイル4,297テスト成功（GIL41/FT49 skip）。
四者runnerのprovenanceで候補ソースの同一性・全実行物・通常C-decimal importを確認した。
R10開発版の初回4,165テストはstr.replaceの直接呼び出し期待値だけ失敗した。
dict.getの直接化と値の検証は成功。別の初期化漏れを発見し、r0 mainでもstrの型versionは
予約値5ではなく80、dictは予約値8だった。strの一般version-cache slotが失われると
_PyType_LookupByVersionで型を取得できない。str以外の予約済みbuiltinは初期値を設定している。
R10単体のKEYWORDS命令検証には予約値を持つbytes.splitを使い、入力型の変更・例外の要求を
維持する。凍結R10 binaryで修正後の単独テストは成功（旧失敗ログ・旧snapshotは保存）。
別因子R11としてstr.tp_version_tagに既存_Py_TYPE_VERSION_STRを設定し、builtinの予約version
を検証するテストを追加。main/旧候補でのred確認、R10 full suite再確認、R11のGIL/FT開発版を
検証した後に、既に用意したR9のmain比較と個別変更比較を順に行う。まだ時間改善は未確認。

R10の修正済みfixtureを同じ凍結binaryで読み、13ファイル4,165テスト（42 skip）成功。
予約versionの新テストはr0 GIL/FT mainとR10でstrの80 != 5だけを検出して失敗した。
R11 GIL開発版の最初の検証は18ファイル4,483テスト成功、指定したtest_unicodeが
このリビジョンには存在せず1ファイルだけimport失敗。実際のtest_strとtest_capi.test_unicode
へ指定を修正して再実行し、FTにはtest_free_threading.test_strも加える。
補助診断でunsafe version再登録helperをstatic strに使おうとし、変更前のmutable-type
assertでプロセスが終了した。この失敗・空出力も保持し、修正の証拠には使わない。
状態を変更しない診断を凍結R10/R11で実施した結果、同じstr.replaceと8,192回の入力で
version80/汎用call → version5/FAST_WITH_KEYWORDS_INLINEを確認し、値も全件一致した。
これは生成形の証拠であり、まだ速度の証拠ではない。

R11の最終開発検証はGIL20ファイル4,688テスト（48 skip）、FT21ファイル4,692テスト
（57 skip）成功。文字列C APIとFT並行文字列テストも含む。通常/FT debug検証はまだ。
全ビルドが終わってからcompare_integrated.pyを開始した。
順番はR9/mainのGIL PGO+LTO、R9/mainのFT、R10/R9開発GIL、R11/R10開発GIL、R11/R9 FT。
main比較と変更単体の比較を混同せず、各仕様3 worker・5 warmup・5 value・逆順2ブロックを
維持する。今は選択集合のscreenで、全成功仕様の再実行と最終の回帰判定はまだ残る。

R9 GIL PGO+LTO screen完了: 11仕様22結果、失敗0、前後identity一致。
Genshi text/XML0.9868/0.9934、nbody1.0204、base16 small/large0.8195/0.7779、Go0.9460。
3%以上は次の6結果（候補/main）:
many_optionals: 1.1065（95% CI 1.1003–1.1131）。
regex_v8: 1.1005（95% CI 1.0990–1.1022）。
sqlglot_v2_transpile: 1.0623（95% CI 1.0527–1.0729）。
pickle_pure_python: 1.0502（95% CI 1.0358–1.0651）。
ascii85_large: 1.0485（95% CI 1.0481–1.0490）。
richards_super: 1.0384（95% CI 1.0343–1.0430）。
R6のregex helperはPGO後にsre_ucs1_next_branchへのcallとレジスタ退避が3か所残り、
開発R6には独立helper symbolがない。R12としてその小helperにPy_ALWAYS_INLINEを付ける
単一因子patch（R9基準）を用意。まだ未ビルド。全体配置だけの影響とは断定しない。
R10/R11の比較完了後に、残った対象を固定仕事量のperfとJIT無効の対照で切り分ける。

R13試作: R10のdescriptor取得をFTでも予約済みbuiltin version 1–12に限定して許可。
_PyType_LookupByVersionの固定switchだけを通し、共有の可変version-cacheは読まない。
immutable static type所有のdescriptorを参照し、既存の直接C-call命令・型guard・cleanupを維持する。
GIL専用だった直接callの意味検証をFTにも適用。単独因子patchはR11+この変更だけ、
R12のC inline変更と分離した。まだビルド・性能とも未検証。

R14試作: argparseの最大methodの熱いside exitはroot offset22（最初のreceiver store）で、
約900uopずつのside traceを2段通る。同じ入口で型が変わるlarge methodだけ早期guard退出を
既存256-entry windowへ数える。小method、callee内、後半の退出、completeのcallee fallbackは
対象外。広い監視R4/R8とは区別し、Goのmethod保持を検証する。まだ未ビルド。

R9 FT screen完了、5仕様8結果、失敗0、前後identity一致。
docutils: 1.0506（1.0407–1.0594）。
go: 0.8588（0.8526–0.8659）。
regex_v8: 1.0234（1.0224–1.0246）。
richards_super: 0.3853（0.3842–0.3862）。
sympy_expand: 0.8948（0.8918–0.8976）。
sympy_integrate: 1.0168（1.0009–1.0389）。
sympy_str: 0.9505（0.9478–0.9531）。
sympy_sum: 1.0506（1.0417–1.0591）。
docutils/SymPy sumの3%以上の後退は残る。R10/R11の単独因子比較へ進んだ。

R10/R9 GIL開発版比較完了、6結果・失敗0・identity一致。SQLGlot optimize0.9950、
argparse1.0089、transpile1.0033、pure pickle1.0098、Go1.0024、richards_super1.0016。
大きい利益は確認できず、この変更だけを回帰修正成功としない。R11とFT拡張R13を別途評価する。
R14は入口基本blockとcodeの最初1/8の共通範囲だけを監視し、閾値をEXIT_TRACEの定数opargに
入れる設計に絞った。loop headerやcallee内の型guard退出は数えない。未生成・未ビルド。

R11/R10 GIL開発比較は8結果、失敗0、identity一致。argparse1.0076、SQLGlot
optimize0.9965/transpile1.0032、pure pickle1.0044、Go1.0003、richards_super1.0047、
Genshi text1.0167/XML0.9906。直接call生成は確認できても大きな速度改善は確認できない。
M-15のレポートをrelease検証済み・debug/最終統合検証待ちへ更新した。

R12–R14に進む前のR14 red testは期待したMETHOD_PROFILE不在を検出した。
補助driverが失敗exit codeを1と誤って固定していたため停止したが、regrtestの実際の
テスト失敗コードは2。ログで期待した1件のfailureを確認し、再生成・再実行はせず
続行用driverでR13 red test、診断、ビルドへ進む。旧driver失敗ログも保持する。

固定仕事量のR9 GIL診断でargparseはcycles1.0819/instructions0.9586、regex_v8は
1.0955/1.1456、ascii85_largeは1.0465/1.0495。ascii85はC decoderが約70%を占める。
R15試作はASCII85の通常5文字組をまとめて復号し、tableの0..84/255を使う1回の
非digit検査と64bitのoverflow検査で、1文字ごとの状態更新を省く。省略・無視文字・
端数は元のincremental path、canonical/error処理は共通。入力型・境界値・全invalid byte
位置・前後のgroup遷移を検証するテストを追加。R9基準の単独patchへ固定、まだ未ビルド。


R11/R9 FT比較完了、7結果・失敗0・identity一致。docutils0.9959、SymPy sum0.9943、
integrate0.9884、expand0.9938、str0.9963、regex_v8 0.9785、Go0.9911。
R13 FTは21ファイル4,692テスト（56 skip）成功。R14 GIL開発版は20ファイルのうち
19ファイル成功、test_reのみsandboxのsocket拒否。許可されたローカルソケットで
test_reを単独再実行して成功した。R13/R14の性能はまだ未測定。

R15 GIL開発版の初回4,690テストは新しい4入力型のテストだけ失敗。C APIのignorechars
既定値を誤って想定したfixtureで、空白を明示した後、同じ凍結binaryでbinascii/base64の
全テストが成功。新旧C decoderの134,928ケースを固定seedで比較し、値・例外名・message
が一致した（r15-ascii85-differential.json）。C実装の差し戻しやbinary差し替えはない。
旧テスト・失敗ログも保存し、今後の統合snapshotにはfixture修正を含める。

continue_r12_and_compare.pyでR12だけのGIL PGO+LTO版を新規ビルド中。
終了後はR14/R11 GIL開発、R13/R11 FT、R15/R9 GIL開発、R12/R9 GIL PGOを順番に比較。
各仕様の逆順2ブロック・3 workerを維持し、重いビルドを競合させない。

固定仕事量の追加診断: GIL argparseはJIT無効ではcycles0.9930/instructions0.9995、
pure pickleは0.9871/0.9971で、JIT有効経路に原因がある。richards_superは無効でも
cycles1.0343/instructions1.0026で、C配置等の影響も残る。これらは単一perf診断であり
正式な時間比とは区別する。FT docutilsはcycles1.0372/instructions0.9486、SymPy sumは
1.0631/0.9240。保持したexecutor mapと生IPから帰属したJIT試料は全体の12.15%/16.86%、
SymPyのFactKB.deduce_all_factsが3.70%。mappingはexecutor寿命とGCを変える診断に限定する。

R16試作: exact tupleのunpack後は全要素の独立参照が既にあるため、tupleを閉じても
要素のfinalizerは呼ばれない。専用deallocator経由でこの条件をgeneratorへ伝え、通常の
2/3要素unpackとtuple→localsの不要なstack同期・validity checkを省く。共有可変listは
対象外。要素が最後まで生存し、結果破棄後に解放されることと長さエラーのテストを追加。
R9基準の単独patchへ固定して再生成中。まだビルド・正しさ・速度とも未確認。


R16のroot/単独因子snapshotを再生成済み。次のR17はFTのLOAD_DEREFを安全な取得に限定して
既存GUARDED命令へ変換する試作。通常getterの_Py_TryIncrefCompareは競合時のDECREFで
finalizerを呼び得るため、全getterをnon-escapingとは宣言しない。atomic load後に
_Py_TryIncrefFastで現在thread所有またはimmortalだけを取得し、NULL/共有取得は元opcodeへ
退出する。GIL側getterは同じ。既存のempty/mutated cell・例外テストをFTにも適用し、
終了した別thread由来の値のfallbackと寿命のテストを追加。R9+R17単独patchも再生成・固定。
R16/R17はいずれも未ビルドで、性能の結論はまだない。


R12 GIL PGO+LTOが完成。学習10,628テスト、関連20ファイル4,686テスト（48 skip）成功。
独立したsre_ucs1/2/4_next_branch symbolはなくなった。速度比較はR13/R15の後に実行する。
R14/R11 GIL開発比較は8結果・失敗0・identity一致。argparse1.0150（1.0053–1.0255）、
Genshi XML1.0187（1.0079–1.0306）、他6結果1.0011–1.0110。改善がなく現状のR14は
採用しない。実際のmethod状態・退出先を追加診断して設計の対象条件を確認する。
R13/R15/R12の計時完了を待つ続行driver（after_r12_r17.py）を用意した。
以後は詳細map診断→R16 FT/GIL開発・R17 FTのビルド/テスト→単独因子比較を逐次行う。
R16/R17と既存比較の重い作業は重ねない。R16/R17のdebug検証と最終統合suiteはまだ残る。


R13/R11 FT比較完了、8結果・失敗0・identity一致。
docutils: 1.0029（0.9979–1.0077）。
go: 1.0004（0.9981–1.0033）。
regex_v8: 1.0223（1.0210–1.0236）。
richards_super: 0.9940（0.9814–1.0036）。
sympy_expand: 0.9983（0.9935–1.0030）。
sympy_integrate: 1.0058（0.9965–1.0152）。
sympy_str: 1.0042（0.9988–1.0104）。
sympy_sum: 1.0016（0.9872–1.0168）。
docutils/SymPy sumの後退を解消できず、regex_v8は2.2%悪化。この直接call拡張は
現状では採用根拠がなく、R10とともに最終候補から除く方向。C処理への影響とJITによる
効果は区別し、型version初期値修正R11の採否とは分ける。


R15/R9 GIL開発比較完了、base64全11結果・失敗0・identity一致。
ASCII85 small0.9426（0.9390–0.9452）、large0.9068（0.9035–0.9106）。
他結果は0.9936–1.0183で、最大のurlsafe smallはCI 0.9976–1.0521と広い。
全workerを保持する。R15は採用候補とし、PGO最終構成でASCII85のmain比と
他base64結果の3%閾値を再確認する。開発版の単独効果を最終結果とはしない。


R18の単独試作patchをR9基準で作成（まだ未適用・未ビルド）。大きいcomplete methodの
呼び出し境界を保持する条件へCFG backedgeの存在を加え、acyclicな関数の短いhot returnを
caller traceが通れるようにする。method自体のコンパイルとCからの呼び出しは維持する。
既存テストはcaller loopを先に温める順だけだったため、methodを先に温めた場合にも
callerがhot returnをinlineして閉じたloopになり、実際のコード変更で無効化されるテストを
追加した。大きいloopの境界を維持し、静的な構造の規則とする。測定前の仮説であり、
argparse/pure pickle/SQLGlot/FT docutilsに効くと確定したわけではない。


R12/R9 GIL PGO+LTO比較完了、6仕様16結果・失敗0・identity一致。regex_v8は
0.8976（95% CI 0.8914–0.9071）、regex_effbot0.9986、regex_compile0.9982、docutils0.9940。
一方でbase16 small1.0329、large1.0946、urlsafe base64 small1.0271、richards_super1.0058。
別ビルドのC処理の差も含むため、R12によるregex改善だけを全体改善とはしない。
base16はR9/mainで大きな改善があったが、最終統合版/mainで改めて判定する。
追加map診断v2は存在しないcast macroを使った診断拡張のImportErrorで開始前に失敗した。
凍結binary/sourceは変更せず、v2ログを残して型を確認するcastへ修正したv3を別作成。
コンパイル時の暗黙宣言をエラーにし、事前import検証を加えた。continue_r16_r17.pyで
診断→R16/R17のビルド・検証・計時を再開。R18はこの完了後にred test→開発ビルド→
単独比較を逐次実行する待機driverを用意。まだR16–R18の性能の結論はない。


詳細map診断v3は全コマンド成功・worker/probeの前後identity一致。argparseの
_ActionsContainer.__init__はR14でもmethodのままで、window125/misses49（約39%）と
既存50%閾値に届かず、同じside trace列が残った。pickle/SQLのpreserves_methodは0で、
R18の境界変更だけでは両者への効果を説明できない。pickle putは44命令/140 code units、
SQL Tokenizer._advanceは52命令/195 unitsで、128 code unitsのinline上限にかかる。
R19はキャッシュを除く実命令数でcalleeの上限を管理する単独試作。未ビルド・未測定。
R10/R13/R14は作業ツリーから除去した（旧差分を保存）。生成ファイルの更新はdebugビルド後。

R16 FTビルド成功、20ファイル初回検証は18成功。driverに存在しないtest_cellを指定した
誤りがあり、今後はtest_scopeとFT cell raceを使う。test_optでは21failure/1errorが発生。
同じ新テストファイルで旧R9にも再現、旧R9+元ファイルは491テスト成功、TestUopsだけは
新R16でも24テスト成功。新しい寿命テスト単体→basic_loopは成功し、新テストをsubprocessに
隔離しても全ファイルでは同じ失敗。GCだけが原因という仮説は確認できず隔離変更は戻した。
失敗時JITは有効・thread1、basic_loopの最初のtrace試行がbackoffへ進むことまで確認。
テスト名や結果を削って成功とはしない。FT debugを作り内部ログで追跡し、ログ全件を保存。
R16の性能、R17/R18/R19のビルド・性能、最終統合suiteはまだ残る。


順序依存の原因を特定。JITが壊れて無効になったのではなく、外側のTestSuite.runが
tracerを保持したままC経由で内側のTestUops suiteを実行していた。再帰的なtrace生成は
抑止されるので、内側の最初のTIER2_THRESHOLD回だけではexecutorができない。
固定FT releaseでPYTHON_GIL=0を明示した読み取り診断でも、失敗前後に同じ
TestSuite.runの114 uopとis_tracing=1を確認した。最初のdebug診断拡張はimport時に
GILを有効にしてしまったため、FT状態の根拠は再実行したtracer-state-ft-release.logを使う。
TestUops全クラスを既存isolation.runInSubprocessで隔離し、全492テストが新R16/旧R9
双方で成功。数値計算やtracerの動作は変更せず、テストのJIT開始条件を独立させた。
新tupleテストだけの隔離は効かなかったので採用していない。

R16 FT debugの寿命テストで最初は7/7/8 memory blocksが残った。既存パターンの
clear_executor_deletion_listをテストcleanupへ登録すると3:3の参照リーク検査が成功。
遅延解放の後始末不足であり、その失敗ログも保存。debugのtuple/unpack/base64/binascii/
regex/decimal計7ファイル1,264テスト（27 skip）も成功。root生成ファイルも更新済み。
R16 GIL開発版はcleanupとクラス隔離を含むr16d.patchでビルド中。R17 FTはr17c.patch、
R18/R19も同じクラス隔離を含む別patchへ固定。待機driverの旧test_cell指定を削除し、
前段の比較成功を確認した場合だけ順番に進む構成へ更新した。まだ最終統合評価ではない。


R16 GIL開発版は19ファイル4,546テスト（42 skip）成功。R17 FT初回は18/19ファイル成功、
新しいcell寿命テストだけmethod executorなしで失敗。Pythonのfor loopからreadを呼ぶ
warmupはcaller traceにinlineされ得るため、既存closureテストと同じCのstarmap経由へ変更。
同じ凍結binaryでtest_opt全492テスト（12 skip）成功、FT cell race2テストも成功。
R17の実装は差し替えていない。r17d.patchとrootにはwarmup修正を残した。
R16/R17の個別性能比較を開始し、その終了後にR18/R19の個別ビルド・比較が続く。

richards_superの保存したJIT imageと生IPを照合。Packet.append_to@26はmain440 uop/
20 KiBのimageに対してR9は341 uop/24 KiB、schedule@332も415/16 KiB対326/20 KiB。
imageにはdata/paddingも含むため、割り当てサイズを純粋な命令byte数とは扱わない。
R9のreturnにはframe解放loopのinlineコピーがあり、最熱IPにもそのDECREF分岐が現れる。
R20はそのGIL側fast cleanupを共有C helperへ出す単独試作を用意（未ビルド・root未適用）。
FTの既存generic callは維持。意味は同じで既存のframe/finalizer/exception検証を使う。
新helperはJIT無効PGO学習では実行されない点にも注意し、開発版の結果だけで採用しない。

R20のサイズ診断を補足: 対象固定buildのstencil tableでは_RETURN_VALUE_r11のcode sizeが
main44 byte、R9 233 byte。これはimageのpaddingを含まないcode量で、各returnの追加
189 byteを確認できる。r20-return-stencil-sizes.jsonに入力を記録した。R20の速度は未測定。


R16/R9 FT比較完了、5仕様8結果・失敗0・identity一致。
docutils: 0.9963（95% CI 0.9822–1.0106）。
go: 1.0035（95% CI 1.0001–1.0066）。
richards_super: 1.0071（95% CI 1.0042–1.0099）。
sympy_expand: 1.0128（95% CI 0.9989–1.0274）。
sympy_integrate: 1.0007（95% CI 0.9964–1.0048）。
sympy_str: 1.0076（95% CI 0.9997–1.0163）。
sympy_sum: 0.9894（95% CI 0.9819–0.9976）。
unpack_sequence: 0.9814（95% CI 0.9795–0.9832）。
SymPy sumとunpack_sequenceに小さい利益があるが、docutilsの改善は未確認。
残るmain比3%以上の回帰が消えたとはまだいえない。R17/R9 FTの比較へ進んだ。
R16のGIL開発比較完了後に採否を決める。


R16/R9 GIL開発比較は5結果・失敗0・identity一致。pure pickle0.9918、Go0.9982、
richards_super0.9986、unpack_sequence0.9995、SQL transpile1.0005。FTのunpack/sumの
小さい利益を踏まえR16は統合候補へ残すが、最終main比較はまだ必要。
R17/R9 FTは7結果・失敗0・identity一致。docutils0.9943、sum1.0078、integrate1.0076、
str1.0112、expand0.9916、Go1.0004、richards_super1.0154。明確な利益がなくR17は
作業ツリーから除去。cellの既存FT経路とテスト条件へ戻し、旧差分・測定は保存した。

R18はred testが旧R9で想定どおり失敗、新GIL開発版で新テストは成功。ただし既存の
長い直線calleeの境界維持テストが失敗した。これは既存の有益な保護を広く外したためで、
テストを緩めず、loopまたは分岐のない長いbodyの境界を保持するr18d.patchを別に作成。
分岐で短い経路を選べるacyclic bodyのみ許可する。R18bを新しい凍結buildとして再検証中。
以前のR18失敗ログ/実行物は保持し、R19/R20はR18の検証・比較終了を待つ。


R21単独試作を用意。methodの部分変換は途中でMETHOD_DEOPTへ退出した後も、bytecode
CFG上の後続blockを生成していた。保存したexecutorの静的走査でSQLGlot 358/5,748 uop、
FT docutils704/29,636、SymPy1,087/13,840 uopが到達不能という診断を得た。
通常edge・guard退出・例外edgeを明示化した後に到達可能部分だけへ圧縮し、全jump/error
offsetを再対応させる実装を単独patchに固定。codeの意味とside exit先bytecodeは維持する。
importによる無条件退出以後の積が除かれる例と、別のpredecessorから到達する積が残る例を
テストに追加。まだred test・ビルド・検証・速度のどれも未実施。rootへは未適用。


R18bはGIL/FTとも19ファイル4,546テスト成功（GIL42 skip、FT50 skip）。
GIL開発のR18b/R9は9結果・失敗0・identity一致:
chaos: 1.0125（95% CI 1.0033–1.0253）。
go: 1.0016（95% CI 0.9985–1.0051）。
many_optionals: 1.0114（95% CI 0.9989–1.0235）。
nbody: 0.9979（95% CI 0.9938–1.0021）。
pickle_pure_python: 0.9949（95% CI 0.9842–1.0020）。
raytrace: 0.9984（95% CI 0.9802–1.0130）。
richards_super: 0.9932（95% CI 0.9779–1.0062）。
sqlglot_v2_optimize: 1.0017（95% CI 0.9963–1.0074）。
sqlglot_v2_transpile: 1.0029（95% CI 0.9913–1.0159）。
argparse/SQLGlot等の残存回帰を消す利益はまだなく、FT比較の後に採否を確定する。

R22はR20で外へ出したframe cleanupをFTにも適用する単独試作。frame objectの検査は
FT atomic loadを使い、現在threadの通常frame・f_localsなし・chunk先頭でない場合だけ、
既存と同じlocals→func→codeの解放順とstack領域の予約期間を維持する。通常のframe
所有権移動、generator、chunk回収は元helperへ戻す。FT診断でframe解放の複数C helperが
費用を占めたことが動機。R21までの比較後に19関連ファイルとFT frame/cprofile/monitoring
を検証してFTの8仕様を比較する。root未適用、ビルド・正しさ・速度とも未確認。


R18b/R9 FT比較完了。7結果・失敗0・identity一致。
docutils: 0.9951（95% CI 0.9852–1.0058）。
go: 1.0074（95% CI 1.0022–1.0160）。
richards_super: 1.0008（95% CI 0.9863–1.0098）。
sympy_expand: 1.0022（95% CI 0.9990–1.0061）。
sympy_integrate: 1.0064（95% CI 0.9998–1.0136）。
sympy_str: 1.0077（95% CI 1.0034–1.0124）。
sympy_sum: 0.9964（95% CI 0.9846–1.0077）。
GIL/FTとも回帰を消す明確な利益がないためR18bは不採用。元々rootへ適用していない。
R19の属性cacheが大きいcalleeのテストは旧R9でMETHOD_CALLが残って失敗し、
想定した制限を確認した。R19 GIL開発版をビルド中。


R21のred fixtureをビルド待ち中に事前確認。import、組み込み関数への*argsは実際には
変換できるため、初案は想定の無条件退出を作らなかった。旧fixture/失敗ログを保存し、
Python関数への*args（現在methodでは未対応）へ変更したr21c.patchを固定。旧R9で
退出後の_BINARY_OP_MULTIPLY_INTが残る期待どおりの失敗となり、別predecessorのある
乗算を保持する対照テストは成功した。測定中のCPU負荷を避け、R19ビルド中に各0.4秒未満の
fixture検査だけを実行した。待機中のR21 driverは停止してv2へ置換。R21の実装検証は未実施。


R19はGIL/FTとも19ファイル4,546テスト成功（42/50 skip）。GIL開発比較は9結果、
失敗0・identity一致。
chaos: 1.0066（95% CI 0.9822–1.0316）。
go: 0.9985（95% CI 0.9965–1.0003）。
many_optionals: 1.0092（95% CI 0.9966–1.0233）。
nbody: 1.0020（95% CI 0.9982–1.0062）。
pickle_pure_python: 1.0013（95% CI 0.9860–1.0177）。
raytrace: 1.0047（95% CI 0.9895–1.0189）。
richards_super: 1.0018（95% CI 0.9970–1.0066）。
sqlglot_v2_optimize: 0.9887（95% CI 0.9831–0.9948）。
sqlglot_v2_transpile: 0.9892（95% CI 0.9820–0.9984）。
SQLGlotの2仕様で約1.1%短縮。pure pickleには利益未確認。FTの比較と最終PGO/main
比較がまだ必要で、3%回帰を消したとは判定しない。


R20/R22の統合用差分では、共有helperの宣言にも実装と同じ_TIER2条件を追加した。
Tier 2なしの構成へ未定義のexport宣言を出さないため。試作用の凍結patch/buildは変更せず、
今回測るTier 2ありのLinuxでは実効Cコードは同じ。採用後の最終snapshotへ含める。


R19/R9 FT比較完了、7結果・失敗0・identity一致。
docutils: 1.0013（95% CI 0.9909–1.0120）。
go: 1.0047（95% CI 1.0034–1.0058）。
richards_super: 1.0017（95% CI 0.9889–1.0165）。
sympy_expand: 0.9942（95% CI 0.9853–1.0028）。
sympy_integrate: 1.0015（95% CI 0.9960–1.0065）。
sympy_str: 1.0095（95% CI 1.0021–1.0149）。
sympy_sum: 1.0044（95% CI 1.0006–1.0089）。
FTには明確な利益がなくGo約0.47%、str約0.95%の小さい悪化もある。GILのSQL 2仕様の
約1.1%改善とcache領域に依存しない上限という設計を踏まえ、R19を統合候補としてrootへ
適用。採用確定・全回帰解消とはしない。最終FT/GILのmain比較で副作用を含めて判定する。
R20のGIL開発版をビルド中。


R20 GIL開発版が完成（e92b7420c7677a3d2e302348479f7834a2197491d791c589e8f1619a4fb1aadc）。
19ファイル4,545テスト（42 skip）成功。_RETURN_VALUE_r11のstencil本体は233→44 byteと
実際に縮小し、r20-return-stencil-sizes-verified.jsonへheader SHAとともに保存。
個別性能比較を開始。まだPGO構成・main比の性能は未検証。


R20/R9 GIL開発比較完了、8仕様9結果・失敗0・identity一致。
genshi_text: 1.0052（95% CI 0.9918–1.0197）。
genshi_xml: 0.9899（95% CI 0.9725–1.0086）。
go: 0.9892（95% CI 0.9816–0.9972）。
many_optionals: 0.9610（95% CI 0.9521–0.9705）。
nbody: 0.9992（95% CI 0.9932–1.0049）。
pickle_pure_python: 0.9914（95% CI 0.9832–0.9990）。
richards_super: 0.9210（95% CI 0.9157–0.9271）。
sqlglot_v2_transpile: 0.9768（95% CI 0.9724–0.9817）。
telco: 1.0035（95% CI 0.9964–1.0101）。
return stencilの233→44 byte縮小と複数項目の短縮が一致し、R20を統合候補へ採用。
rootへ共有C helperと_TIER2を含む宣言条件を適用した。PGO学習ではJIT無効なので、
新helperの学習・配置の影響は最終PGO/mainで別途検証する。R21 GIL開発版をビルド中。


R21 GIL/FTは19ファイル各4,547テスト成功（42/50 skip）。GIL開発の6結果・失敗0・identity一致。
go: 1.0009（95% CI 0.9981–1.0033）。
many_optionals: 1.0081（95% CI 0.9955–1.0199）。
pickle_pure_python: 0.9937（95% CI 0.9899–0.9977）。
richards_super: 1.0072（95% CI 1.0008–1.0145）。
sqlglot_v2_optimize: 1.0042（95% CI 0.9973–1.0112）。
sqlglot_v2_transpile: 1.0065（95% CI 0.9997–1.0138）。
GILでは大きな時間改善を確認できず、FT評価の後に採否を判断する。
統合検証driver validate_integrated.pyを準備。採用後の固定patchからFT/GIL debugを作り、
関連24ファイル（FTは5追加）と4つの寿命・frame関連テストの3:3リーク検査を逐次実行。
テスト後も実行物/標準拡張/source SHAを照合する。まだ統合buildは開始していない。


R21/R9 FT比較完了、7結果・失敗0・identity一致。
docutils: 0.9980（95% CI 0.9913–1.0053）。
go: 1.0066（95% CI 1.0008–1.0136）。
richards_super: 1.0056（95% CI 0.9972–1.0196）。
sympy_expand: 1.0014（95% CI 0.9948–1.0092）。
sympy_integrate: 1.0042（95% CI 0.9995–1.0083）。
sympy_str: 1.0145（95% CI 1.0005–1.0296）。
sympy_sum: 0.9972（95% CI 0.9876–1.0079）。
code量を削減できてもGIL/FTの回帰を解消する時間改善は確認できず、R21は不採用。
rootへは適用していない。R22のFT releaseをビルド中。これを最後の個別試作として、
評価後は統合debug→同一ソースFT/GIL PGO→main比の選択screen/全体比較へ進む。


R22 FTは22ファイル4,574テスト（50 skip）成功。frame/cprofile/monitoringのFT専用テストも含む。
実行物SHAは7e6e152a4ac28744ec47b46fddafc0becf1187448012f82194fea739b46311b1。
R9比の8仕様を順序反転2ブロックで測定中。結果が揃うまでは採否を確定しない。
統合後はr23-integrated.patchを固定し、FT/GIL debug、同一ソースFT/GIL PGOを逐次検証する。


統合版の最初のmain比較はintegrated_screen.pyに事前固定：FT 9仕様、GIL 13仕様、
各3 worker/5 warmup/5 value、順序反転2ブロック。既知の回帰に加えGo/super/telco等を含む。
個別因子の倍率を掛け合わせて統合結果の代用にはしない。screenの後、全97仕様を検証する。


R22/R9 FT比較完了。8仕様12結果・失敗0・identity一致。
docutils: 0.9916（95% CI 0.9829–1.0009）。
genshi_text: 0.9999（95% CI 0.9950–1.0058）。
genshi_xml: 0.9893（95% CI 0.9658–1.0151）。
go: 0.9816（95% CI 0.9766–0.9865）。
many_optionals: 0.9811（95% CI 0.9733–0.9889）。
pickle_pure_python: 1.0014（95% CI 0.9748–1.0403）。
richards_super: 0.9555（95% CI 0.9522–0.9592）。
sympy_expand: 0.9890（95% CI 0.9794–1.0003）。
sympy_integrate: 0.9936（95% CI 0.9895–0.9985）。
sympy_str: 0.9998（95% CI 0.9920–1.0065）。
sympy_sum: 0.9748（95% CI 0.9606–0.9887）。
telco: 0.9957（95% CI 0.9764–1.0155）。
sympy_sum約2.5%、super約4.4%、Go約1.8%、argparse約1.9%改善。
docutilsのCIは1を跨ぎ、pickleのCIは1.03も跨ぐため無回帰を保証しない。
R22をR20のFT拡張としてrootへ統合。通常frameのatomic frame_obj検査、参照解放順、
stack領域を保持する期間を維持。生成ケースを再生成した。
r23-integrated.patch SHA-256: bcdf36980a2b180ffc801f19d5f74aa44a6292533d209b61f1eb2e7171c4f3bd
同じpatchからFT/GIL debugを作り、関連テスト・リーク検査を開始する。


全体比較ハーネスの候補参照をr23の同一ソースreleaseへ更新した。依存入りcontrollerで
ハーネス23テスト成功（r23-harness-tests-controller.log）。最初のホストpython3.12実行は
pyperf/packaging未導入でimport失敗し、そのログも保存。実装の失敗とは区別する。


統合R23の初回FT debugビルドはstencil生成で失敗。統合時に追加したhelper宣言の
_TIER2条件が原因で、stencilのclangには_Py_JITのみ渡されるため宣言が隠れていた。
headerを_TIER2 || _Py_JITに修正し、非Tier2構成への宣言制限は維持。個別試作の
R20/R22にはこの統合時条件がなかったため、既測定の性能結果には影響しない。
失敗成果物を保持し、r23b-integrated.patchから新しいビルドへ進む。SHA-256: ee0afc306868ad5d06aa77d6b44d8d6c8c76b59512466ddbc2b43325638993ce


R23b FT debugは29ファイル4,906テスト（59 skip）、新しいtuple/inlineの3:3リーク検査に成功。
既存return materialized/finalizerのリーク検査は両方失敗。R16 FT debugでも同じ失敗で、
前者は[3,2,4]、後者は[1,1,2]のmemory block差。executorの遅延解放cleanupだけを
加えた独立overlayで新旧・両テストとも成功した（r23b-frame-refleak-controls.json,
r23b-frame-refleak-cleanup.json）。その2行をrootへ適用。期待値・本体処理は変更していない。
最終ソースr23c-integrated.patchを再固定：98892307d1595ce6c9ce7ec1483cc53e759fe56c7e4235e5f9dcfadbc44253ee。
C側はR23bと同一。固定したテストを含めてFT/GIL debugから逐次検証を再開する。


R23c FT debug: 29ファイル4,906テスト（59 skip）、tuple/属性の多いcallee/保存frame/
finalizer再入の4件で3:3リーク検査成功。ソース・python・標準拡張の前後SHA一致。
python SHA-256: 962bcd469d2afbcc4c78fe5e89817980936aed1d1a4493105968319ead866ca0。GIL debugへ進む。


R23c GIL debugは24ファイル4,863テスト（46 skip）と4件の3:3リーク検査成功。
FT/GILの全3,943ソース一致、実行物/標準拡張/ソースの検証後SHA一致。debug段階完了。
GIL debug SHA-256: de46c0c3d62b64125403652332160b4a8c65cef6af8bbc6a2f1b0ee5dd0579fe。同じpatchでFT releaseとGIL PGO/full LTOを開始。


R23c FT releaseも29ファイル4,906テスト（61 skip）成功。GIL PGOのビルドへ進む。
過去の失敗を再確認：fastapiはベンチマーク実行のTypeErrorではなく、pydantic-coreの
PyO3がPython 3.16未対応としてwheel構築を拒否した準備失敗（実行callなし）。
GIL asyncio_tcp_sslでは両側にSSLのBAD_RECORD_MAC系エラーがある。FT Daskは候補の
distributed/profile.py:62のframe参照中SIGSEGV。現在の原因・修正済みとは判断しない。
最終分析にdependency preparation failureと実行欠落の対応を追加し、未測定を成功へ数えない。


R23c GIL PGO学習は43ファイル10,632テスト（265 skip）成功。mainの10,623に対し
R5/R6/R15の追加テスト9件が増えている。学習JIT無効・seed0・cold専用pycache・
bootstrap profile分離の条件を維持し、140.6秒で終了。full LTOの最終ビルド中。


R23c release段階完了。GIL PGO/full LTOは24ファイル4,863テスト（48 skip）成功。
FT/GILの3,943ソース一致、mainを含む4構成のlibmpdec.a SHA一致、通常decimal importで
C backendを確認。FT SHA-256: 283bd9d4f7927e3c4a5efa1ff58d7e040413e59a025de95840e1a1672339762c。
GIL SHA-256: 897f9daf8195577eff39e69eab705cc0da5bc11fe1214cb404aa46f172657e8e。
FT 9仕様→GIL 13仕様のmain比較を開始（r23c-*-main-screen）。全97仕様はまだ未実施。


R23c最終機械語の静的確認：共有frame helperはGIL開発R20で473 byte、PGO統合R23cで
179 byte。PGO版ではlocal/function/codeのPyStackRef_CLOSEが各々out-of-line callになり、
開発版のinline decrefとは異なる（r23c-frame-cleanup-native.jsonとdisassembly保存）。
JIT無効学習でhelperが未実行なことと整合するが、サイズ差だけで性能悪化の原因とはしない。
main screen完了後に差が残る場合、PGOで通常frame処理とfast pathを共有する設計を検討する。


待機中の静的設計としてr24-frame-draft.patchを作成（未適用・未ビルド・生成ケース未更新）。
R23cの既存fast pathを通常の_PyEval_FrameClearAndPopへ共通化し、Tier1/JITの両方から
呼んで通常PGO学習でも実行される案。新しいrefcount規則は導入しない。現在の固定buildや
測定ソースは変更していない。現在のmain screen結果を確認後、必要性と採否を判断する。


R23c/main FT screen完了。9仕様13結果、失敗0、前後identity一致。
docutils: 1.0341（95% CI 1.0247–1.0440）。
sympy_sum: 1.0264（95% CI 1.0224–1.0303）。
regex_v8: 1.0141（95% CI 1.0115–1.0171）。
many_optionals: 1.0084（95% CI 0.9975–1.0228）。
sympy_integrate: 0.9968（95% CI 0.9904–1.0023）。
telco: 0.9550（95% CI 0.9429–0.9685）。
sympy_str: 0.9444（95% CI 0.9391–0.9496）。
genshi_xml: 0.9272（95% CI 0.9161–0.9382）。
sympy_expand: 0.8811（95% CI 0.8792–0.8836）。
genshi_text: 0.8705（95% CI 0.8682–0.8728）。
pickle_pure_python: 0.8556（95% CI 0.8536–0.8576）。
go: 0.8403（95% CI 0.8345–0.8465）。
richards_super: 0.3715（95% CI 0.3685–0.3765）。
docutilsは3.4%回帰が残り、全回帰解消ではない。sympy_sumも点推定2.6%、上端3.03%で
確認の余地がある。GIL PGO/full LTOの13仕様の比較を続ける。


R23c/main GIL PGO/full LTO screen完了。13仕様24結果、失敗0、前後identity一致。
pickle_pure_python: 1.0842（95% CI 1.0773–1.0912）。
many_optionals: 1.0674（95% CI 1.0560–1.0784）。
richards_super: 1.0571（95% CI 1.0347–1.0760）。
base85_small: 1.0523（95% CI 1.0447–1.0596）。
regex_compile: 1.0400（95% CI 1.0309–1.0511）。
nbody: 1.0389（95% CI 1.0348–1.0437）。
dulwich_log: 1.0367（95% CI 1.0279–1.0466）。
sqlglot_v2_transpile: 1.0332（95% CI 1.0297–1.0368）。
genshi_xml: 1.0324（95% CI 1.0027–1.0809）。
genshi_text: 1.0308（95% CI 1.0208–1.0404）。
sqlglot_v2_optimize: 1.0304（95% CI 1.0199–1.0398）。
base32_small: 1.0241（95% CI 1.0222–1.0259）。
go: 1.0120（95% CI 0.9931–1.0418）。
telco: 1.0114（95% CI 1.0092–1.0137）。
base32_large: 1.0102（95% CI 1.0090–1.0115）。
urlsafe_base64_small: 0.9997（95% CI 0.9926–1.0042）。
base85_large: 0.9960（95% CI 0.9953–0.9968）。
base64_small: 0.9924（95% CI 0.9899–0.9941）。
base64_large: 0.9899（95% CI 0.9891–0.9905）。
regex_v8: 0.9756（95% CI 0.9742–0.9770）。
ascii85_small: 0.9364（95% CI 0.9349–0.9380）。
base16_small: 0.8615（95% CI 0.8603–0.8629）。
ascii85_large: 0.7958（95% CI 0.7952–0.7964）。
base16_large: 0.7954（95% CI 0.7928–0.7984）。
11結果に3%以上の回帰が残る。R20開発版の利益がPGOで保たれていない。
PGO版helperのout-of-line PyStackRef_CLOSEという機械語の観測を踏まえ、
通常のframe解放と共通化するR24を次に検証する。R23cの成果物/生データは全て保持する。


R23c両構成の選択screen完了後、R24の共通frame解放fast pathをrootへ適用。
JIT専用の重複helperを除去し、通常の_PyEval_FrameClearAndPopからも同じ処理を使う。
参照の解放順、frameのunlink、stack領域の保持期間と特殊frameのfallbackは維持。
PGOでこの経路が学習されることとTier1の多段call削減を検証する。まだ高速化成功とはしない。
生成ケースを更新しr24-integrated.patchを固定。SHA-256: da454345bc1152c1376422f2b162ed4ba78b6b3aeac4c71836286808ff5a0c8c。
通常のframe解放も変更するため、cprofile/profile/sys_settraceを追加した
FT 32/GIL 27ファイルと4件のリーク検査をdebugで実行後、releaseを検証する。


R24 FT debugビルド完成（f7fe0fa00f8b65ec73ec0cd11373fc64096560ecf6c6236d9945e78c63489a30）。
拡張検証は31ファイル5,361テスト（60 skip）成功し、追加名test_cprofileだけModuleNotFoundError。
このソースではC profilerテストはtest_profiling.test_tracing_profilerに移動済みだった。
実装失敗ではなくrunnerの指定誤り。全テスト名のファイル存在を事前確認するよう点検し、
validate_r24_v2.pyで正しいモジュールを実行する。元の失敗ログ/JSONを保持し、通過済み31
ファイルの結果とSHAを参照してFT debugビルドを再利用。4件リーク検査後にGILへ進む。


R24 FT debugの正しいC profilerテスト27件成功。通過済み31ファイルの5,361件と合わせ
32ファイル5,388件を検証し、4件の3:3リーク検査にも成功。source/python/標準拡張SHA一致。
再開runnerの失敗code照合はregrtestの実際の値2に修正し、初回のassert失敗ログも保持。
GIL debugビルドへ進んだ（r24-continue-driver-v2.log）。


R24 GIL debugも27ファイル5,345テスト（47 skip）と4件の3:3リーク検査成功。
FT/GILの3,943ソース一致、実行物/標準拡張/ソースの前後SHA一致。debug段階完了。
GIL debug SHA-256: 699d26ef64624c8c52f7bda520285dcec17bd495022c8c44146b96221730157b。FT releaseをビルド中。


R24 FT release完成。SHA-256: 50f92267bf2a1c995069d5443dd76ec274f5761459651106ef730903e6354679。
32ファイル5,388テスト（62 skip）成功、前後のsource/python/標準拡張SHA一致。
GIL PGO学習も正常終了し最終リンク中。性能の採否は固定binaryのmain比較後に判断する。


R24 release両構成完了。GIL SHA-256: 363aab337485c903950b692aee73683e77c40a86205a9e7009da62ba540d18f1。
GIL 27ファイル5,345テスト（49 skip）成功。PGO学習43ファイル成功。
機械語では_PyEval_FrameClearAndPopのhot部分777 byte、cold28 byteとなり、
R23cのJIT専用helperに残った各PyStackRef_CLOSEのcallがなく、decrefを直接実行する。
_RETURN_VALUE_r11 stencilは44 byte。これはコード生成の確認で、性能の結論ではない。
inspect_cleanup.pyとnative JSON/disassemblyを保存。両releaseはsource/python/標準拡張identity一致。
同じC decimal mainとのFT 9仕様/GIL 13仕様の選択screenを開始した。


R24/main FT選択screen完了。9仕様13結果、失敗0、前後identity一致。
sympy_sum: 1.0380（95% CI 1.0289–1.0470）。
docutils: 1.0321（95% CI 1.0242–1.0393）。
regex_v8: 1.0202（95% CI 1.0175–1.0223）。
many_optionals: 1.0056（95% CI 0.9999–1.0107）。
sympy_integrate: 0.9931（95% CI 0.9917–0.9943）。
telco: 0.9550（95% CI 0.9453–0.9638）。
sympy_str: 0.9524（95% CI 0.9486–0.9563）。
genshi_xml: 0.9076（95% CI 0.9038–0.9117）。
sympy_expand: 0.8838（95% CI 0.8823–0.8854）。
genshi_text: 0.8828（95% CI 0.8659–0.9005）。
pickle_pure_python: 0.8446（95% CI 0.8290–0.8545）。
go: 0.8400（95% CI 0.8356–0.8446）。
richards_super: 0.3712（95% CI 0.3700–0.3724）。
docutilsとsympy_sumが3%以上。GIL screen後にJIT有効/無効の固定仕事量の診断を行う。
両者を未解消とし、FT全体や3%以上全解消とはしない。


R24/main GIL PGO/full LTO選択screen完了。13仕様24結果、失敗0、前後identity一致。
nbody: 1.0436（95% CI 1.0417–1.0455）。
many_optionals: 1.0366（95% CI 1.0324–1.0404）。
pickle_pure_python: 1.0243（95% CI 1.0134–1.0353）。
telco: 1.0241（95% CI 1.0189–1.0293）。
dulwich_log: 1.0177（95% CI 1.0042–1.0314）。
sqlglot_v2_optimize: 1.0115（95% CI 1.0053–1.0173）。
urlsafe_base64_small: 1.0111（95% CI 1.0075–1.0139）。
base32_large: 1.0089（95% CI 1.0075–1.0101）。
sqlglot_v2_transpile: 1.0072（95% CI 1.0043–1.0104）。
base85_large: 0.9963（95% CI 0.9957–0.9969）。
genshi_text: 0.9944（95% CI 0.9776–1.0121）。
regex_compile: 0.9918（95% CI 0.9860–0.9981）。
base64_large: 0.9895（95% CI 0.9889–0.9901）。
base85_small: 0.9894（95% CI 0.9843–0.9936）。
genshi_xml: 0.9873（95% CI 0.9575–1.0131）。
regex_v8: 0.9839（95% CI 0.9795–0.9893）。
base32_small: 0.9752（95% CI 0.9739–0.9762）。
richards_super: 0.9414（95% CI 0.9314–0.9486）。
base64_small: 0.9378（95% CI 0.9282–0.9433）。
go: 0.9353（95% CI 0.9334–0.9371）。
ascii85_small: 0.8860（95% CI 0.8841–0.8876）。
base16_small: 0.8423（95% CI 0.8412–0.8434）。
base16_large: 0.8400（95% CI 0.8372–0.8432）。
ascii85_large: 0.7972（95% CI 0.7966–0.7977）。
3%以上はnbody/argparseの2結果（R23cでは11）。FTのdocutils/sympy_sumと合わせ4件が未解消。
pure pickle、telco、dulwichは平均3%未満だが最終確認対象に含める。
diagnose_r24.pyでFT docutils/sympy、GIL argparse/nbodyをJIT 0/1の固定仕事量で逐次診断する。
診断はperf statのinstructions/cyclesで原因を切り分ける補助であり、pyperfの置き換えではない。


R24固定仕事量のJIT切り分け（各1組のperf stat。pyperfの代用ではない）:
ft docutils JIT=0: cycles 1.0195, instructions 0.9960。
ft docutils JIT=1: cycles 1.0372, instructions 0.9346。
ft sympy JIT=0: cycles 0.9881, instructions 0.9861。
ft sympy JIT=1: cycles 1.0601, instructions 0.9128。
gil argparse JIT=0: cycles 0.9925, instructions 0.9986。
gil argparse JIT=1: cycles 1.0020, instructions 0.9634。
gil nbody JIT=0: cycles 1.0031, instructions 0.9992。
gil nbody JIT=1: cycles 1.0425, instructions 1.0046。
FT SymPy/nbodyはJIT経路に差が残る。docutilsにはJIT無効時の差もある。
argparseの固定仕事量では差が小さく、実際のpyperf worker（512loops/5warmups/5values）
をprofileする。warmup長さ・呼び出し方・importでのspecialization等を区別し、
差が小さい診断値を通常pyperfの3.7%回帰の解消として扱わない。
FT docutils/sympy、GIL argparse/nbodyのJIT map付き診断も逐次実行する。
mapはexecutor保持がGC/寿命を変えるため、通常時間比に使わない。


R24追加profile完了。実pyperf argparse workerでも3.9%/4.3%回帰を再現。
nbodyのhot loopはmain/candidateともtraceで、候補のuop数は415→394だがimageは16→20KiB
（data/paddingを含む）。定数添字を毎回Python整数から取り出していることを確認。
R25はexact compactな非負定数list添字をoperandへ埋め込む専用uopを追加。
元のstack/exit/cleanup規約とFTのlist取得APIを維持する。負数・動的indexは既存経路。
listの要素変更、縮小・空listのIndexError、subclassへの切替をテストに追加し、
旧R24で新uopがないため失敗することを確認した。生成casesを更新し試作patch固定。
R25 patch SHA-256: a46960cda8022ddcc40dc367ebdc9b32a1d92ea2724914cd9f419c4993da7892。


R25は既存のlist pair比較/len融合を維持するため、新命令を対応matcherで同等に扱う
r25bへ更新して開発ビルド。GIL SHA: 091d346bff1edac698f5509dcaced23ac5fab43751b6df71d359715da7a3eec0。
18ファイル1,691テストのうち、既存slice型伝播テストが旧list添字命令名を期待した1失敗。
型ガード1個の条件を保って期待名だけ更新し、同じ固定binaryでtest_optの494件が成功。
元の失敗ログ/build/sourceを保持。rootはテスト修正のみを含むr25c-integrated.patchへ固定。
continue_r25.pyでR24 GIL non-PGO control、R25c FTをビルド・検証後、
GIL 6仕様とFT 5仕様を反転2block・3workerで比較する。まだ性能の採否は未確定。


R25c検証: R24 GIL controlは18ファイル1,690件成功、R25c FTは21ファイル1,723件
（33 skip）成功。FT SHA: 1b931664697fbdc7e81e5b5a191679a0c2356ad8f06a757df6e755e1886813a8。
定数list添字stencilはGIL 69 byte（従来101/borrowed103）、FT 104 byte（従来137）。
GIL non-PGO因子比較7結果は失敗0・identity一致: nbody0.9496（CI0.9446–0.9560）、
argparse0.9973、pickle0.9966、Go1.0046、super0.9937、Genshi text0.9969/XML0.9997。
これはR24開発版比であり、最終PGO/mainの解消判定ではない。FT比較を続行中。

argparseのR24 mapでは_ActionsContainer.__init__が134命令、1168uop、
PUSH_FRAME15件、METHOD_CALL1件、分岐0でpreserves_method=true。
R26-draftは「未inlineのPython呼出しを残すacyclic method」のcaller tracingを許す案。
loopを持つmethodや、calleeを全てinlineできた大きい直線bodyの境界は維持する。
既存R18の「分岐のあるacyclic body」案とは対象が異なる。root未適用・未実行。
R25の性能測定が終わってから新しいgenerator caller/closure変更テストで旧版との差を確認する。


R25c FT因子比較完了（8結果、失敗0・identity一致）:
docutils0.9996、sympy_sum0.9867（CI0.9735–1.0000、block0.9750/0.9986）、
nbody0.9878、Go0.9964、super1.0004、SymPy他0.9999–1.0047。
SymPy sumはblock間差があり、main比の解消と扱わない。
R26新テストは旧R25bでcallerのPUSH_FRAME不足により失敗し、問題の再現を確認。
R26案をrootへ適用しpatchを固定。開発版の正しさと因子比較へ進む。


R26開発版の検証成功: GIL 19ファイル3,658テスト（20 skip）、FT 22ファイル
3,690テスト（33 skip）。反転2blockの性能比較を実行中。GIL argparseの初回
2blockは方向が一致せず、改善を確認できていない。全予定の結果を保持して判断する。
R27-draftはFTのborrowed attribute receiver後の不要なoutput/POP_TOP_NOPを除く案。
従来FTでfuse_borrowed_input_cleanup全体を無効にしていたが、属性loadだけを対象にし、
FT uop interpreterでは既存と同じacquire load/TryIncrefCompareStackRefを使う。
list/tupleのborrowed融合は従来通りFTで無効。属性寿命、削除、dict clear、descriptor変更、
一時receiverのfinalizer検査を維持・追加する。root未適用・性能未評価。
FT JIT templateは既存の単一Python thread制約でGIL相当のobject操作を生成しており、
R25のFT list添字もnative stencilではこの既存経路、FT uop interpreterではGetItemRef経路。
両者を混同しない。スレッド停止・参照カウントの既存条件は緩めない。


R26のGIL 7結果はargparse1.0068（CI0.9891–1.0238）、Genshi text1.0122/XML0.9945、
Go1.0110、pickle1.0054、nbody1.0017、super0.9976。FTでも完了済みdocutils1.0048、
SymPy sum0.9975・他1.0018–1.0041で回帰解消につながらないため採用しない方針。
残りのFT反転比較は終了まで継続し、全結果を保存する。rootからR26を戻しR27を適用。
R27の生成・ビルド・検証は現在の測定終了後に行う。
R28はR25cから独立に作ったpatchを固定。大きいcomplete acyclic bodyが未inlineの
Python呼出しを残す場合、入口からtraceを選び、prefer_traceで再解析を防ぐ試作。
loopやcalleeを取り込めたbodyは維持する。まだ実行・採用していない。


R26 FTも8結果・失敗0・identity一致で完了。採用せず全試行を保持。
docutils: 1.0048（CI0.9969–1.0131）。
go: 0.9947（CI0.9844–1.0012）。
many_optionals: 1.0042（CI0.9935–1.0164）。
richards_super: 1.0014（CI0.9992–1.0033）。
sympy_expand: 1.0041（CI0.9950–1.0150）。
sympy_integrate: 1.0034（CI0.9911–1.0160）。
sympy_str: 1.0018（CI0.9933–1.0102）。
sympy_sum: 0.9975（CI0.9837–1.0094）。
R27/R28のfixtureは旧R25 FT/GILでそれぞれ融合命令の欠落・METHOD_CALLの存在により
失敗し、差を再現。R27のcases生成・diff checkが成功しpatch固定。
run_r27_r28.pyでFT属性cleanupとGIL入口trace選択を独立に検証する。


R27 FTは24ファイル3,705テスト成功（33 skip）、SHA
0c9b01763fe21a0877ccd8e6d2b8226e436544a547572df8ce61f12244a5d60b。
属性loadのr12 stencil 91 byteに対し、borrowed-owner r11は85 byte。
R28 GIL試作はtest_optの新テストとtest_argparseでSIGSEGV。性能測定へは進めず。
faulthandlerのPCを固定binaryで解決するとoptimizer.c:5026のprefer_trace書込み。
初回method compileではco_executorsがまだNULLで、既存inlined-loop判定と異なる。
R28b-draftは必要な場合のみget_index_for_executorで配列を確保してから記録する。
確保失敗は既存unsupported経路で安全に戻る。新テストがこのcold初回経路を含む。
旧R28のbinary/差分/失敗ログは保存。現在R27 FT測定中のためR28bのビルドは終了後。


旧overnightのGIL docutils失敗ログにはfaulthandlerのCアドレスが含まれていた。
旧main/candidate binaryのSHAが当時のpreparation.jsonと一致することを確認し、
addr2lineでGCのdeduce_unreachable/gc_collect_main付近へ解決した結果を
old-docutils-faulthandler-symbols.jsonへ保存。native coreやレジスタ状態はなく、
根本原因を特定したわけではない。最終の全体比較で再発の有無を確認する。
R28b実行はR27のanalysis.json完成・identity確認後に開始する逐次queueとした。


R27 FT因子比較完了（失敗0・identity一致）。
docutils: 1.0050（CI0.9978–1.0108）。
go: 0.9910（CI0.9892–0.9931）。
many_optionals: 1.0011（CI0.9897–1.0139）。
richards_super: 0.9942（CI0.9897–0.9990）。
sympy_expand: 0.9952（CI0.9845–1.0038）。
sympy_integrate: 0.9966（CI0.9927–1.0004）。
sympy_str: 1.0063（CI0.9954–1.0180）。
sympy_sum: 1.0009（CI0.9853–1.0156）。
Go/superには小幅の利益があるがdocutils/SymPy sumの回帰解消にはならない。
rootはR27を保持し、最終main比で判断する。R29-draftはhotになったreceiver型guard
のside traceをコンパイルする時にcomplete methodをretireしてentry tracingへ戻す案。
対象は最初のself load/type guardまでに通常の仕事がないprefixだけ。呼び出し毎の
新カウンタは追加しない。tracerのstrong refとfinalizationのinvalid分岐を利用する。
root未適用、性能未評価。


R28b GIL検証は19ファイル3,658件成功（20 skip）。SHA:
5e3b10a5fda2eb2c3a15fdf1f1881f60d167f3cde4b3888f871ff65a5c79beeb。
argparseは反転2blockとも改善（約0.9945/0.9801、平均0.9873）。最終PGO/mainで確認する。
R29新テストは旧R27 FTでmethodがvalidのままという期待通りの失敗を確認。
この単独テスト（実行0.003秒）の終了時刻13:43:00 UTCはR28b Genshi比較の段階と重なった。
元の全workerを保持し、このGenshi因子の確定には使わず、同じbinaryで両blockを1回だけ
独立に再測定することを結果確定前に決める。run_r29.pyへ逐次queueを追加。
R29はその後にFT/GIL開発版をビルド・検証し、GIL/R25・FT/R27を比較する。


R28b GIL因子比較完了（7結果・失敗0・identity一致）。
genshi_text: 1.0144（CI0.9996–1.0333）。
genshi_xml: 1.0068（CI0.9848–1.0295）。
go: 1.0075（CI1.0000–1.0169）。
many_optionals: 0.9873（CI0.9689–1.0061）。
nbody: 0.9990（CI0.9922–1.0070）。
pickle_pure_python: 0.9916（CI0.9811–1.0017）。
richards_super: 1.0062（CI1.0019–1.0106）。
Genshiには前述の微小な単独テストとの重複があり、固定binaryで確認を実行する。
argparseは効果候補、他への影響は最終main比較を含めて判断する。


R29 FTの新しいpolymorphic receiverテストは成功。既存
 test_trivial_root_c_vectorcall_attribute_fallbacks が2種類のクラスに同じcodeを使い回し、
2周目のwarmupでentry tracingを選んだためget_executor(0)がValueErrorとなった。
クラスごとにfresh codeを使うfixtureへ変更し、既存のexecutor存在・値・例外・traceback・
descriptorのassertは全て維持する（隣の属性itemテストと同じ隔離方式）。
rootをR29b試作へ更新しpatch固定。runtimeはR29と同じでテストfixtureだけの変更。
全体の23ファイルは成功済み。固定binaryで更新test_optを再検証してから比較へ進む。


R29b fixtureの再検証は固定FT/GIL binaryともtest_opt 495テストに成功。
R29b GIL/R25の7結果・失敗0・identity一致: argparse1.0253（CI1.0129–1.0380）、
Go1.0022、pickle1.0005、nbody1.0004、Genshi text0.9958/XML0.9871、super0.9814。
目的のargparseを悪化させるため採用しない方向。FT測定を最後まで保持する。
R30b-draftはR27から独立したclosure prefixのinline対応。既存のnested method helperと
同じ単独COPY_FREE_VARS・MAKE_CELLなしのprefixを、新しいcallee frameへ一度だけ発行。
解析はRESUMEから開始し、実行中のfunctionのcellを使う。拡張prefix/MAKE_CELLは従来通り。
cell更新・別closure・空cell例外・tracebackの新テストを用意し、既存nested methodの
例外テストはinline命令上限を超えるcalleeへ変更して元の_METHOD_CALL検証を維持する。
最初の未実行fixtureでassertRaises終了後に消されたtracebackを参照する誤りを静的に
見つけ、except内の検査へ直したr30b patchを保存。まだビルド・root適用していない。

R29b FTの完了済みdocutilsは両blockとも約1.3–1.5%悪化、SymPy sumも
改善していない。残りの比較・frontendカウンタ診断を継続しつつ、rootからR29を撤回し
R30b closure inline試作へ更新。R29のpatch・binary・全workerは保持する。
R30bのビルドはR29の計測・perf診断終了後に逐次実行する。


R29b FT/R27の8結果も失敗0・identity一致で完了。R29は採用しない。
docutils: 1.0140（CI1.0038–1.0241）。
go: 1.0106（CI0.9982–1.0295）。
many_optionals: 1.0138（CI0.9985–1.0272）。
richards_super: 0.9825（CI0.9636–1.0005）。
sympy_expand: 1.0015（CI0.9882–1.0142）。
sympy_integrate: 0.9937（CI0.9833–1.0029）。
sympy_str: 0.9837（CI0.9766–0.9921）。
sympy_sum: 1.0113（CI0.9990–1.0225）。
改善したstr/superも含め全workerを保持。残るfrontend診断は時間測定と分離する。

R29b/main FT frontendカウンタ診断は全5イベント同時計測・稼働率100%、
全4実行成功・binary/worker identity一致で完了。固定仕事量、各1組の探索的診断で
通常pyperf時間比とは別。docutils cycles1.0377/instructions0.9332、icache stalls1.5289、
iTLB walks3.6566。SymPy sum cycles1.0494/instructions0.9084、icache stalls1.6434、
iTLB walks2.7371。分岐missは約1.006/1.033。この1組だけで因果を確定しない。
R30bのred testは旧R27で_COPY_FREE_VARSがないという期待した失敗。
FT/GIL開発版のビルドと検証を開始。比較中は他のCPU負荷を重ねない。


R30b closure inlineの検証成功。FT 26ファイル4,183件（34 skip）、GIL 21ファイル
4,135件（21 skip）、全runtime/source identity一致。SHA:
FT 2f078116a7217878b09cabb178dfc8f61c5c1e250d918989e64ff23738e43b67、
GIL 658623b29f74374267416933d9b3cf1d79e5edf3e72e67827cf93201a7997b25。
FT/R27・GIL/R25の反転2block・3worker因子比較へ進んだ。
R31-draftはR27起点の独立実験。既存の末尾paddingだけでJIT entryを64-byte刻みに分散。
総割当ページ数・stencilコード量・W^X条件は変えない。jit_code/jit_sizeはentryから
allocation末尾までのviewとし、freeでpage先頭を復元する。global連番はatomicで更新。
ページ先頭へ集中した入口によるL1 instruction cacheの競合を減らす仮説であり、
iTLBページ数の削減を主張しない。独立FT/GIL正しさ・性能比較、その後FT/R27の
frontendカウンタをA/B・B/A各1回で比較する計画。まだroot適用・ビルドしていない。
新テストはcode view・native address分類・無効化/GC/再生成/解放を3×64個で検査。

R31は未実行の静的レビューでpaddingが丸1ページある場合の境界を発見。
entry offsetが丸1ページになるとfree側のpage切り下げで先頭ページを復元できないため、
offsetを必ず1ページ未満に制限したR31bを別保存。旧案は実行しない。
ページ数はそのまま、allocation baseからentryまでのoffsetのみを制限する。


R30b FT因子比較は8結果・失敗0・identity一致で完了。
docutils: 0.9983（CI0.9947–1.0022）。
go: 1.0061（CI1.0031–1.0095）。
many_optionals: 1.0070（CI1.0010–1.0137）。
richards_super: 1.0011（CI0.9983–1.0036）。
sympy_expand: 1.0098（CI0.9974–1.0223）。
sympy_integrate: 0.9998（CI0.9926–1.0067）。
sympy_str: 0.9987（CI0.9923–1.0051）。
sympy_sum: 0.9995（CI0.9865–1.0127）。
SymPy sumはblock0.9774/1.0222で改善を確認できない。docutilsもほぼ同速、
Goは両順序で約0.6%悪化。目的の回帰を解消しないためR30bをrootから撤回。
GILの残り比較は終了まで保持する。R31b配置試作をrootへ適用し、R30b両構成の
比較終了後にのみビルドを始める逐次queueを開始。rootのruntimeはR27+R31b。

R31bのnative code viewテストはuop interpreter backendでは実行不可なので、
get_jit_backendでnative専用のskipを追加したr31c-integrated.patchを保存。
ビルドlabelはR31bのまま（runtime同一）、queue開始前に使用patchをr31cへ固定。
旧patchは保持。新しいテストをuop interpreter全体の回帰にしないための検査条件。


R30b GIL因子も7結果・失敗0・identity一致で完了。撤回を確定。
genshi_text: 1.0133（CI1.0041–1.0273）。
genshi_xml: 1.0035（CI0.9900–1.0146）。
go: 1.0053（CI0.9994–1.0115）。
many_optionals: 1.0112（CI1.0006–1.0227）。
nbody: 0.9973（CI0.9911–1.0013）。
pickle_pure_python: 0.9884（CI0.9698–1.0024）。
richards_super: 1.0087（CI1.0010–1.0163）。
R31b（fixtureを含むpatchはr31c）のFTビルド開始。R30測定との重複はない。

R31b FTは21ファイル4,006テスト成功（37 skip）、SHA
0078d64f5455813063b24e59144105d58042a73ed67fe1d9291ded5d88d53ae5。
新しいcode view/反復解放テストとtest_c_stack_unwindを含む。GILビルド継続。
ビルド中に既存R24 perf.dataをオフライン解析（新規計測なし）。初回の-F ip出力には
callchainが含まれたため、そのファイルは保持し、-Gでleaf IPだけを抽出して再解析。
r24-entry-leaf-sample-distribution.jsonが正しいleaf集計。docutilsは59,505中7,442、
SymPyは51,974中8,593がJIT sample。L1の64-byte/64-setの仮定でset0への集中は
JIT sampleの12.5%/14.9%、entry先頭256byteは19.5%/23.9%。これはcycle sampleの
位置分布でありcache missの位置を直接測ったものではない。配置仮説の補助資料。

R31b GILも17ファイル3,965件成功（21 skip）、SHA
 a5bd576b5e30744a3622fd3f482efa98d4478cea1a383a4588770794ac38dbfc。
両構成runtime/source identity一致を確認し、FT/R27・GIL/R25の因子比較を開始。
r31b-ft stencil headerが基準と完全一致: False。
r31b-gil-dev stencil headerが基準と完全一致: False。
R31b stencil headerの差は先頭2行のinput digest/build command pathのcommentのみ。
全emit関数・機械語byte列・patch処理はFT/GILとも基準と完全一致。
別artifact r31b-stencil-body-identity.jsonへ本文SHAを保存した。

最終検証helperに--reuse-ftを追加。採用patchがR31cのままなら固定済みR31b FTを
再ビルドせず追加の全関連テストで検証して使える。patch全文、非debug/FT設定、
source/runtime SHAを照合し、既存の試作テストlogを上書きしない別labelに保存する。
GILは必要なPGO/full LTO build、debugはFT/GIL新規検証。まだ実行していない。


R31b FT/R27の9結果・失敗0・identity一致で完了。
docutils: 0.9872（CI0.9812–0.9927）。
go: 1.0013（CI0.9944–1.0073）。
many_optionals: 0.9916（CI0.9776–1.0043）。
nbody: 1.0052（CI0.9948–1.0166）。
richards_super: 0.9711（CI0.9568–0.9830）。
sympy_expand: 0.9925（CI0.9855–0.9994）。
sympy_integrate: 0.9952（CI0.9874–1.0034）。
sympy_str: 0.9840（CI0.9770–0.9921）。
sympy_sum: 1.0024（CI0.9935–1.0123）。
docutilsは両順序で改善。sumはほぼ同速。GIL比較とカウンタ診断を継続する。


R31b GIL/R25は7結果・失敗0・identity一致で完了。
genshi_text: 1.0160（CI0.9985–1.0406）。
genshi_xml: 1.0108（CI1.0045–1.0173）。
go: 1.0034（CI0.9992–1.0089）。
many_optionals: 0.9976（CI0.9829–1.0112）。
nbody: 1.0304（CI0.9891–1.1001）。
pickle_pure_python: 1.0007（CI0.9966–1.0056）。
richards_super: 0.9916（CI0.9826–1.0003）。
nbodyの候補1 workerが約48.3ms（他は約39ms）で、warmup5回・測定5回とも
遅い状態で安定した。周波数約4.39GHz、runnable1で、一時的外れ値として除外しない。
最終validationの事前条件（全因子3%未満）によりR32 queueはビルド前に停止した。
同じbinaryのnbody/Genshiを6worker・反転2blockで1回だけ追加確認すると事前決定。
元の全workerも保持する。現在はこの確認だけを実行中。
docutils frontend因子（R31b/R27、A/B・B/A、全稼働率100%）: {"cpu_core/cycles/u": 0.9861051288180608, "cpu_core/instructions/u": 1.0001412791861453, "cpu_core/branch-misses/u": 0.9947275896631197, "cpu_core/icache_data.stalls/u": 0.9265128178197607, "cpu_core/itlb_misses.walk_completed/u": 0.751268139449668}
sympy frontend因子（R31b/R27、A/B・B/A、全稼働率100%）: {"cpu_core/cycles/u": 0.9953471270056076, "cpu_core/instructions/u": 1.0013877386208831, "cpu_core/branch-misses/u": 1.0358072813977741, "cpu_core/icache_data.stalls/u": 0.949735647669691, "cpu_core/itlb_misses.walk_completed/u": 0.7397220183291605}


R31bの追加GIL確認（6worker×反転2block）は全3結果成功・identity一致。
genshi_text: 0.9988（CI0.9934–1.0041）。
genshi_xml: 0.9952（CI0.9861–1.0041）。
nbody: 0.9945（CI0.9931–0.9959）。
元の48.3ms workerを削除しない。過去の同じR25b baseline計48workerは39.1–40.8ms、
R31bは通常/追加計18worker中1つが48.3ms、他は38.9–39.6ms。差の原因は未確定。
同一R31b binaryの私有jit_code_sequenceだけを、単一GILプロセス内で64初期値へ
固定shuffle順に変える探索的診断を開始。ELF symbol offsetとbinary SHA、writable mapを
確認し、プロセス内データだけ変更する。OS設定や実行ファイルは変更しない。
元のbm_nbodyをwarmup5回/測定10回（loops4）実行し、測定後にGCを停止してexecutorを記録。
通常pyperf測定とは別に扱う。初回probeのenum ID解析とゼロ長stencilの集計不備は修正、
失敗記録を保持。v2はstencil tableから実際に生成されるIDのみ読み、未生成70 IDを区別する。
R31dは大きいbodyを配置変更対象から外す未実行案として保存。まだ適用・採用していない。


R31bの64条件配置診断が完了（失敗0・binary/worker一致）。phase21の1プロセスで
warmupも測定も約54.3ms（通常約39ms）という安定した遅延を再現。
主要advance traceは全条件で18,413byteの同じcached uop列。問題のプロセスでは
そのentry offset=1,472byte。他の大きいtraceの配置も同時に変わるため、特定offsetだけ
を原因と断定しない。phase21と22を2回ずつ固定順で追加再現確認する。
R31dはcode_sizeが1ページ未満の小さいbodyだけに既存余白の分散を適用し、
既に1ページ分のcache setを跨ぐ大きいbodyは元の配置を維持する。benchmark名や
module名による分岐はない。rootへ適用しpatch固定、再生診断終了後にFT/GILを検証。
元のR31bの改善・不利なworker・追加確認・64条件の全結果を保持する。

phase21/22の再生は各2回とも38.7–39.3msで、遅い状態は再現しなかった。
同じcounter初期値だけを原因と断定しない。64条件では平均39.4ms付近、最大54.3msの
1プロセスが安定して遅く、実アドレス等も変わるため因果の留保を残す。
R31dの検証開始。大きいコードの配置を変えない版で通常比較と配置診断を再確認する。

R31d FTは21ファイル4,006件成功（37 skip）、SHA
27b4801e2cdbb6315a4037a87ae795952e93466695ab840485ba70133389c84b。
GIL開発版ビルド継続。R31d用の同じ64条件診断を準備するhelperも保存し、
実際の新binaryのSHA/ELF symbolと対応headerでprobeを作る。まだ診断は実行していない。

R31d GILは17ファイル3,965件成功（21 skip）、SHA
1970463304e857a8df8b74c2fc1b7dbf8185bf3895363db3b9110dcf67ee177b。
両構成source/runtime identity一致。GIL/R25比較を先に実行し、その後FT/R27・
反転frontendカウンタ・64条件診断を逐次実行するqueueを開始。
通常因子比較と診断が成功した場合の最終検証driver finalize_r31d.pyも準備。
labelはR33、patchはR31d、FTは固定R31d binary再利用。まだ最終検証は実行しない。


R31d GIL/R25の7結果・失敗0・identity一致で完了。
genshi_text: 1.0032（CI0.9960–1.0102）。
genshi_xml: 1.0032（CI0.9990–1.0071）。
go: 0.9919（CI0.9803–0.9998）。
many_optionals: 0.9834（CI0.9652–0.9986）。
nbody: 0.9987（CI0.9951–1.0031）。
pickle_pure_python: 1.0021（CI0.9788–1.0254）。
richards_super: 1.0027（CI0.9988–1.0066）。
argparseは両順序で改善。nbodyはほぼ同速で今回の6候補workerに大きな遅延なし。
FT比較へ進み、追加の64条件診断はその後に実行する。

R31eを未実行の代替案として保存。code_sizeの閾値ではなく、vm_data.is_methodの
executorだけ入口を分散し、既存tracing frontendのloop traceを元の配置に保つ。
vm_data.is_methodは_PyJIT_Compile呼出しより前に初期化済み、cold executorではfalseと
sourceで確認。R31dの最終結果を見て必要な場合だけ比較し、まだrootへは適用しない。


R31d FT/R27は9結果、失敗0・identity一致。
docutils: 0.9993（CI0.9888–1.0099）。
go: 0.9956（CI0.9915–0.9991）。
many_optionals: 0.9946（CI0.9909–0.9985）。
nbody: 0.9992（CI0.9930–1.0051）。
richards_super: 1.0030（CI1.0017–1.0044）。
sympy_expand: 1.0000（CI0.9855–1.0158）。
sympy_integrate: 0.9991（CI0.9929–1.0046）。
sympy_str: 0.9965（CI0.9923–1.0008）。
sympy_sum: 1.0058（CI0.9970–1.0144）。
docutils/sumは改善せず、配置だけでは残る回帰を解消できない。R31dの64条件診断も完了。
R31e method-only配置案は未実行のまま保留し、R34を独立評価する。
R34はR27を基点にPOSIX x86-64のmmap hintをインタプリタ付近に置く。
Linuxは既存patch_x86_64_32rxによるGOT間接call/loadの直接化、Darwinは既存trampoline省略
を期待する。MAP_FIXEDは使わず既存mappingを置換しない。hint無視・失敗時は従来の
遠距離relocation経路を維持。page数、W^X、allocation所有権は変更しない。
rootからR31dの配置変更を除いてR34へ置換し、FT/GIL開発版の正しさ・因子比較へ進む。

R31d配置診断64プロセスの平均時間範囲は38.95–40.46ms。
FT docutilsのfrontendカウンタ（R27比、反転2block）: cpu_core/cycles/u=0.9988, cpu_core/instructions/u=1.0001, cpu_core/branch-misses/u=1.0073, cpu_core/icache_data.stalls/u=1.0108, cpu_core/itlb_misses.walk_completed/u=1.3823。
FT sympyのfrontendカウンタ（R27比、反転2block）: cpu_core/cycles/u=1.0011, cpu_core/instructions/u=0.9993, cpu_core/branch-misses/u=1.0142, cpu_core/icache_data.stalls/u=0.9798, cpu_core/itlb_misses.walk_completed/u=1.0018。
全イベント稼働率100%。通常pyperf比較と診断を区別し、命令供給カウンタだけで原因を断定しない。

R34関連検証完了。FTは21ファイル4,006件（37 skip）、GIL開発版は17ファイル3,965件（21 skip）成功。
ft SHA: 4de62807fafabb2cdcce13e2ff3b054e70a32b508b9393463180c5ff7a1dbb7d。
gil-dev SHA: 10045f5d8dc69f8cd02915e13b8ca690961da659a00e8233f7d7470c328339d6。
両構成source/runtime identity一致。因子比較を継続し、成功時の同一patch最終検証R35を準備。
FT releaseはR34を再利用し、debug FT/GILとGIL PGO/full LTOを検証後mainと直接比較する。

R34/R25 GIL開発版の7結果・失敗0・identity一致で完了。
genshi_text: 0.9965（CI0.9910–1.0017）。
genshi_xml: 0.9807（CI0.9655–0.9939）。
go: 0.9804（CI0.9644–0.9899）。
many_optionals: 0.8739（CI0.8656–0.8813）。
nbody: 1.0003（CI0.9950–1.0059）。
pickle_pure_python: 1.0057（CI1.0025–1.0080）。
richards_super: 0.9933（CI0.9875–0.9991）。
argparseは両順序で約12–13%短縮。これは開発版同士の因子比較であり、PGO/mainの結果ではない。

R34の機械語診断初回はobjdumpのアドレス接頭辞0xを正規表現が認識せず停止。
生成コードには直接callが存在し、runtimeの失敗ではない。初回出力を保持し、
parserを修正したv2は新しいファイル名で4バイナリを確認する。

R34/R27 FTの9結果・失敗0・identity一致で完了。
docutils: 0.9674（CI0.9612–0.9730）。
go: 0.9958（CI0.9941–0.9976）。
many_optionals: 0.9249（CI0.9223–0.9268）。
nbody: 0.9988（CI0.9957–1.0025）。
richards_super: 1.0013（CI0.9991–1.0036）。
sympy_expand: 0.9578（CI0.9501–0.9655）。
sympy_integrate: 0.9923（CI0.9870–0.9974）。
sympy_str: 0.9140（CI0.9083–0.9201）。
sympy_sum: 0.9575（CI0.9502–0.9643）。
単純なmethodの_RETURN_VALUEについて、FT/GILとも旧版はGOT間接call、R34は
_PyEval_FrameClearAndPopへの直接rel32 callと確認。生成コード・実アドレス・binary SHAを
r34-native-call-analysis.jsonに保存。これはnear mappingと既存relaxationが働く証拠であり、
各性能差の全てを単一要因に帰属するものではない。R35のdebug/最終release検証へ進む。

R34/R27 FT固定work診断（反転2block、イベント稼働率100%）:
docutils: cpu_core/cycles/u=0.9718, cpu_core/instructions/u=1.0013, cpu_core/branch-misses/u=0.8722, cpu_core/icache_data.stalls/u=0.9960, cpu_core/itlb_misses.walk_completed/u=0.7901。
sympy: cpu_core/cycles/u=0.9301, cpu_core/instructions/u=1.0006, cpu_core/branch-misses/u=0.6785, cpu_core/icache_data.stalls/u=1.0379, cpu_core/itlb_misses.walk_completed/u=0.8543。
通常pyperf比較とは別に保存し、計数範囲はimport/warmupを除く元benchmark関数全体。

R35 FT debug通常38ファイル5,542件成功（63 skip）。追加3:3反復で
constant_list_index_checks_current_sizeに[1,1,2]ブロックの残留。
固定6:10診断はR24の同じ境界値テスト（旧opcode名だけ適合）も+21、R35も+19。
clear_executors(read)とclear_executor_deletion_listの後始末を加えると両方-1で成功。
この既存パターンをテストに適用。初回診断driverはregrtestのCLI引数をtests位置引数に
誤って渡したため停止し、v2の正しい4条件の結果を採用。初回ログも保持。
R34bはこのテストの2行だけ変更しruntimeはR34と同一。R36としてdebug/releaseを
新規検証し、同一ソースのFTとGIL PGOを直接mainと比較する。
R35は未完成の検証記録として保持し、完了とは扱わない。

R36 FT debugは38ファイル5,542件（63 skip）と7種類の3:3参照リーク検査が成功。
定数リスト添字の後始末修正後は[-1,0,1]ブロック、合計0。JIT allocation/view/releaseも成功。
R34とR36の凍結ソース全件照合で差はtest_opt.pyの2行のみ、runtimeソースは同一。
patch SHA: accd970d82f07fcf222bf55a8d109a56b2afcd43d5d80dbe3ba0f2578b91618e。

R36 debug全体が完了。FTは38ファイル5,542件（63 skip）、GILは30ファイル5,476件
（47 skip）。それぞれ7種類の3:3参照リーク検査も成功し、凍結source/runtime identity一致。
GIL debug SHA: b990e6984715965f892df7326c5219b6ed9022383df6cac72b8361ff8d972c21。
FT/GIL release検証へ進む。最終PGO以外はPGO/LTOを使わない。

R36 FT releaseも38ファイル5,542件（65 skip）成功、source/runtime identity一致。
SHA: f25d4ff55e7f2c48f18c50febe252d0537f70a96110a4da9abf2d2919ab9d22e。C decimalの通常import確認済み。
GIL PGO/full LTOの学習用ビルドを開始。

R36 release検証完了。FTは38ファイル5,542件（65 skip）、GIL PGO/full LTOは
30ファイル5,476件（49 skip）、全て成功。両構成の全3,943 source SHA一致。
GIL SHA: 9d78e3358068c5bc3075c0c243a9ee636ec397a6b6b611e636d8f2a4a3923800。
PGOはgenerate306.6秒、学習139.7秒（43ファイル10,632件・265 skip成功）、final203.8秒。
通常C decimalとruntime/source identity検証に成功。mainへの選択screenを開始。

R36/main FTの選択screenが13結果・失敗0・identity一致で完了。
regex_v8: 1.0179（CI1.0107–1.0279）。
docutils: 0.9996（CI0.9973–1.0019）。
sympy_sum: 0.9914（CI0.9849–0.9977）。
sympy_integrate: 0.9843（CI0.9807–0.9881）。
telco: 0.9573（CI0.9443–0.9731）。
many_optionals: 0.9250（CI0.9218–0.9280）。
genshi_xml: 0.9034（CI0.8992–0.9073）。
sympy_str: 0.8776（CI0.8752–0.8798）。
genshi_text: 0.8662（CI0.8643–0.8680）。
pickle_pure_python: 0.8584（CI0.8560–0.8607）。
sympy_expand: 0.8488（CI0.8469–0.8507）。
go: 0.8223（CI0.8205–0.8244）。
richards_super: 0.3677（CI0.3672–0.3681）。
3%以上の回帰数: 0。全97仕様はこれから。

R36/main GIL PGOの選択screenは24結果・失敗0・identity一致で完了。
dulwich_log: 1.0931（CI1.0848–1.1001）。
regex_v8: 1.0691（CI0.9746–1.2106）。
pickle_pure_python: 1.0339（CI1.0268–1.0422）。
richards_super: 1.0098（CI1.0024–1.0185）。
telco: 1.0075（CI1.0028–1.0125）。
base32_large: 1.0051（CI1.0040–1.0061）。
nbody: 1.0009（CI0.9966–1.0050）。
base32_small: 1.0002（CI0.9965–1.0047）。
sqlglot_v2_transpile: 0.9998（CI0.9966–1.0031）。
sqlglot_v2_optimize: 0.9977（CI0.9950–1.0003）。
base85_small: 0.9977（CI0.9956–0.9998）。
base85_large: 0.9953（CI0.9949–0.9956）。
genshi_xml: 0.9934（CI0.9888–0.9972）。
genshi_text: 0.9860（CI0.9777–0.9941）。
base64_large: 0.9860（CI0.9856–0.9864）。
urlsafe_base64_small: 0.9818（CI0.9811–0.9825）。
many_optionals: 0.9631（CI0.9466–0.9760）。
base64_small: 0.9531（CI0.9521–0.9541）。
go: 0.9305（CI0.9271–0.9337）。
regex_compile: 0.9244（CI0.9186–0.9298）。
ascii85_small: 0.8891（CI0.8869–0.8915）。
base16_small: 0.8308（CI0.8277–0.8343）。
ascii85_large: 0.7979（CI0.7964–0.7994）。
base16_large: 0.7976（CI0.7924–0.8026）。
dulwich_log・regex_v8・pickle_pure_pythonに3%以上が残り、全97仕様queueは条件不成立で実行前に停止。
これは自動承認拒否ではなく性能条件のチェック。2.5%以上の全3仕様を6worker×反転2blockで
1回追加確認する。最初のscreenと遅いworkerは削除しない。

R36診断初回はDulwichへPathを渡してTypeError。通常benchmarkはstrを渡すため、
診断driverだけ元workloadと同じstrへ修正しv2別名で再実行。通常pyperf結果には影響なし。

R36 pickle固定work診断v2はpyperfのinner_loops=20正規化を回数見積りから落とし、
main側が180秒timeout。元のbench_pickleには1loopで60 dumpsがあり、診断だけ反復を
100×loops64へ固定してv3を実行。pyperf比較のworkload/入力/回数規約は変更しない。
失敗counterを比較に用いず保持し、反転2blockを新しいlabelで最初から測る。

近接mapping切り分けの初回shimはmmapを捕捉したが、この実行物はmmap64を参照するため
match=0の事前検証で停止。通常性能比較は開始していない。nmで参照を確認しmmap64版を
v2別名で作成。実コードの近距離/遠距離配置確認に成功した場合だけ診断比較を開始する。


## 2026-09-19: method JIT単独への移行（新しいユーザー指示）

ユーザーの最新指示により、候補からtracing JITを全削除し、mainのtracing JITと
method JIT単独を比較する。許容回帰は各比較結果の実行時間比1.10以下へ変更。
従来の3%条件と、R37草案のlarge partial methodをtracingへ戻す案は廃止する。
C `_decimal`、FT noPGO/noLTO、GIL PGO/fullLTO、変更しないworkload、短いnetworkx
timeout、binary/依存SHA、順序反転と生データ保存は継続。GitHub投稿/push/PR変更なし。

PEP 836とCPython AI policyを再読。PEPはフロントエンドの置換と既存middle/backendの
再利用を提案している。実装では記録dispatch、tracer状態、録画開始/翻訳/終了、side trace、
methodからtraceへの選択を削除する。共通uop最適化、copy-and-patch、executorの安全な
寿命管理は残す。Pythonのsys.settrace/monitoringはJIT記録と別物であり維持する。

比較上の制約: 現mainのFTはJIT enabledでもexecutorを生成せずTier 1で実行する。
tracing対methodの直接比較はGIL構成。FTはmain Tier 1対methodとして明記する。
R36までの結果はhybridの履歴であり、method単独の成績として転用しない。

作業順:
1. tracingフロントエンドとフォールバックを物理的に削除し、生成器/生成物を更新。
2. 静的CFGのmethod入口・ループ入口、Tier 1復帰/再試行を実装・検証。
3. GIL/FTのnoPGO/noLTO開発ビルドで正しさ、監視、例外、寿命、スレッドを検証。
4. main比較で10%超過を調べ、methodのcoverage/型情報/呼び出しを改善。
5. 同一ソースの最終2構成で全pyperformanceを比較し、成功/失敗/回帰をレポート。

前タスクの最後の固定バイナリmapping診断は完了（6結果、失敗0、identity一致）。
near対mirrorはdulwich 0.9172、richards_super 0.9461、pickle 0.9935、
regex 1.0010、nbody 1.0036、argparse 1.0457。生データを保持し、
この時点では配置変更を採用しない。旧hybrid sourceはm0-before-tracer-removal.patch
とR36の凍結source/buildに保存。

M1/M2: 記録dispatch、tracer構造体/寿命管理、開始/翻訳/終了、entry/side trace生成、
prefer_trace方針、recorder関数生成器/生成物を削除。M1 buildで共通exit処理の
is_for_iter_test削除過多、M2で旧fitness設定の参照残りを検出し修正。失敗ログは保存。
M3: side-traceリンク、cold sentinel executor、exit temperature、chain depth、
jit_exit、タグ付きTier1帰還ポインタも削除。guard失敗は直接Tier1へ復帰。
CFGをループbackedgeから静的にコンパイルするOSRを追加し、entry stack depthは
実フレームから取得、locals/stackの値や型は未知から解析する。EXTENDED_ARGも
挿入点に含め、再試行counterは実opcodeのcacheで更新する。
記録生成器のテストは削除された機能と共に除去し、一般生成器/最適化器のテストは維持。
M3 GIL debug（noPGO/noLTO）を凍結ソースからビルド中。性能は未計測。

M4: GIL debug noPGO/noLTOビルド成功。実行物のnmにCompileMethodがあり、
tracer/trace optimizer/cold-executor生成のシンボルはなし。方法別テスト156件は
142成功・1skip・13失敗。新規OSR（両分岐、ネストしたiterator、型変更、例外位置）は成功。
全uop/生成器432件は228failure・3error・4skip。旧trace形状の期待値と、
method側の型推論/guard除去等の未実装が混在しており、完了扱いしない。

M5: block内list-pair/len-subscript融合をmethodにも適用。methodが保持するlenの
callable/null guardは融合uop自身が同じチェックを行うため吸収。定数1のint cleanupと
overflow guardもpair matcherで認識。コンパイル成功時に現在の呼び出しから実行開始し、
初回のzip専用iterator経路が実際に使われるよう修正。245件中235成功・1skip・
残る9failureは旧side trace/trace loop期待値。入力/出力・エラー・変更後動作を維持し、
method CFGまたは明示したgenerator Tier1 fallbackの契約へ書き換えて再検証中。
main GIL noPGO/noLTO、C decimalビルド完成: cafdcfa052a142b456095b69ec8f99c7a0fcac701403055bfaae587e0de770ea。
性能比較用の候補は別の凍結ビルドを用意し、開発用増分treeは測定に使わない。

M5凍結GIL noPGO/noLTO releaseビルド成功（C decimal）。SHA
776fc7083db32d64c76fa3db66b1a03751fcfd5a7364914aa36abfdae1233071。
method/生成器245件は244成功・1skip（testのspecialized opcode参照を
`dis._all_opmap`へ修正後、root Libから検証）。初回のKeyErrorもログ保存。
14仕様のmain比較を3worker×順序反転2blockで開始。旧hybrid結果は流用しない。
途中値でrichards_superが約2.2倍、Goは約0.90、spectral_normは約0.70。
全体集計前の数値であり、10%条件は未達。

M6実装中: 共通symbolic uop optimizerを静的CFGの直線部分に適用。
入力はmethod解析の保証済み事実のみとし、実フレームの値を観察しない。
frame切り替え/inline CFGを含むblockは除外、短縮分をNOPで埋めてCFGの
参照先を保存する。古いlinear trace後処理は削除し、methodのCFG対応処理を使う。
STORE_FAST_NOESCAPEのsymbol更新を追加。現時点で未ビルド・未検証。
性能測定と重いbuild/testを競合させず、M5比較後にM6 debug検証へ進む。

M5 main比較完了: 14仕様、失敗0、identity一致。10%超過はrichards_super 2.1919、
pickle_pure_python 1.2191、fannkuch 1.1878、regex_compile 1.1218、deltablue 1.1209。
Go 0.8999、spectral_norm 0.6976。詳細と不確実性、全14結果を
benchmarks/method_only_report.mdへ保存した。PGO/FT/全suiteの結果ではない。
別の非計時40回診断でschedule/HandlerTask.fnにexecutorが残らないことを確認。

M6初回は共通型guard解析のrecorded-type assert、M6bはconstructorの
probable-callable assertで停止。型はguardのversion cacheから取得し、
constructorの観察値なしを許す形へ修正。M6cは280件完走、7failure・2skip。
M7ではsymbolic最適化で残ったNOPを詰め、lenのguard除去結果を採用。
定数load/inplace整数演算/借用参照cleanupの変化をregion/enum融合でも認識。
M7は281件完走、7failure・2skip。失敗は形状変化と不足を特定して修正。

M8: CALL_EX_PYをmethodの通常call境界へ対応し、calleeの未知のcode/versionは
runtimeのcallability checkと通常引数処理で扱う。native calleeが未準備ならTier1。
len/float-divide融合は簡略化したcleanupも認識し、元の所有権を保存。
同一localを2回読むdiamondは1つの型guardで十分なことをテストへ反映。
iteratorの記録型に依存した期待値をstatic CFGの汎用iterator経路へ変更。
method/OSR・無効化・uop基本動作・生成器281件は279成功・2skip。
新しいstatic builtin guard除去、local更新後の事実、260回の再コンパイルも成功。
無効化済みco_executorsの空きslotを再利用する修正を含む。
M8の旧uop最適化全体と広い動作検証、Richards診断、凍結release比較へ進む。

M8b: 広い19ファイル検証で18ファイルが成功、test_weakrefでコンパイラの
NULL参照を検出。superの未知のclass引数を定数扱いしていた共通解析を修正。
custom metaclassを含むsuper再現テストを追加し、weakrefと合わせ140件成功。
method関連282件は280成功・2skip。旧最適化310件には122failure・3skipが残る。
これらを一括skipして完了とはしない。静的解析で実現すべき最適化を分類する。
M8b凍結GIL release SHA 7337b327059a22b91410a3510a00dc4d08777492f7455bc02d83a4f744bb2a0e。
14仕様比較を進行中。Richardsは依然約2.2倍で、10%条件は未達。
M9: 記録用pseudouopとDSLのrecords_value属性、関連生成器処理を削除。
抽象RETURN等の未定義出力で生成器エラーとなり、明示的な出力代入を追加して
再生成に成功。まだM9のビルド/動作検証は未実施。

M8b比較完了: 14仕様すべて成功、identity一致。Go 0.8970、spectral_norm 0.6885、
nbody 0.9609。10%超過はrichards_super 2.2337、pickle 1.2130、fannkuch 1.1351、
regex_compile 1.1305、deltablue 1.1166。float 1.0979の95%CI上限は1.1087。
M9は記録pseudouop削除後にビルド成功。277件中1failure・2skip。failureは
warmup呼び出しがcallerのinlineに吸収され、独立したcallee entryが温まらない
テスト前提による。C mapからwarmupするよう修正し、最適化要求自体は保持する。
RAISE/RERAISEをCFG終端として扱い、架空のfallthroughの解析を止めた。

M9の非計時Richards診断（元workload40回）: scheduleは519回、HandlerTask.fnは
113回、WorkTask.fnは22回、Task.qpktは7回、frequent fallbackで破棄されていた。
code budget不足ではなく、冷たい未対応armを含むmethodに対して普通のguard失敗や
callee復帰まで退役判定に数えていた。M10では未対応命令のMETHOD_DEOPTのみを
退役判断へ加算する。多態的guard失敗で元のfast pathを捨てない契約をテストする。
M10 debug build中。性能改善はまだ未計測。

M10: 277件は275成功・2skip。40回の非計時診断でschedule両backedge、
HandlerTask.fn/Task.runTask/Task.qpktのmethod executorが有効なまま残ることを確認。
凍結release SHA d3a1e53109c3d5c721eeded5641fe9e91cde0f6d2fa30004af1279662495f4e5。
6仕様の再比較中。pickleの回帰は縮小、Richardsは依然約2倍。完成扱いしない。
M11実装中: recorder専用symbolのtype/gen-functionとframe-pop復元を削除。
静的lookup由来のprobable valueは共通middle-endとして残し、そのlatticeテストも維持。
呼び出しの前までのprefixとinline calleeの各blockへ共通最適化を適用。
追加guardが必要な定数化も採用できるよう、uop増加時は後続label/inline edgeを再配置。
frameを作るuopより前で解析を止め、calleeのlocalsをcallerのlocalsとして解釈しない。
未ビルド。比較完了後にM11の動作・既存最適化テストとFTを検証する。

M11c: GIL関連284件は282成功・2skip、FT debug関連284件は280成功・4skip。
GIL debugの広い19ファイルは1,858件・15skip、すべて成功。旧uop最適化310件は
98failure・3skip（M8の122failureから減少）。要求される最適化の残りは維持する。
M11初回buildはObjects/call.cのis_method参照残りで失敗して修正。
M11bの初回テストはbuild終了前に開始したため、M11cの完了後に再検証した。
M11c固定release SHA 2763ca5d328b89b5affbf77d2ad5489b8829a5e6e2b68b12b73ef8bd312ed479、
FT debug SHA 04083db2e2bd5ce20c733b66033c27d5c1a5ed281047b6dcc6a59481091376a5。
M10の6仕様比較はidentity一致、失敗0。Richards 1.9719、regex 1.1475、
fannkuch 1.1351、deltablue 1.0946、float 1.0923、pickle 1.0239。
M10 Richardsの別perf診断（200回、timingではない）はTier1 evaluator自身42.08%、
native JIT領域26.45%、フレーム破棄5.25%。退出を減らす改善が必要。

M12実装中: COPY_FREE_VARS前置の小さなclosureも静的CFGとしてinlineする。
GILでは、既存type-version cacheの兄弟型のうち同一属性offset/descriptorを検証
できる最大4型を1つのguardで受け入れる。ライブ引数の記録も命令列の記録もしない。
versionは個々の型の変更で失効し、OR条件から特定の型を推論しない。
属性offsetの異なる兄弟、instanceで隠されたmethod、property差替えをテストする。
FTでは既存の単一型guardを維持。M11c比較と並行してsource編集のみ。未ビルド。

M12b: GIL method関連280件は278成功・2skip。兄弟型guardのoffset不一致、
instance shadow、property変更、slots変更も成功。closureをinline可能にしたため、
実際のnative call境界を検査する既存テストはvariadic calleeで境界を固定した。
固定release SHA 3bd37807b8aab4d942b25055fd269135dd8e585ce9de5f2b67a7207e9d4887a8。
4仕様比較は失敗0、identity一致。Richardsは1.4063へ改善したが条件未達。
regex 1.1579、fannkuch 1.1418、deltablue 1.0809。全suiteではない。
Regex別perf診断40反復はmethod_merge_block 4.19%、finish_uops 1.18%、
apply_stack_effect 1.13%を占める。コンパイルの繰り返しも次に調べる。
M13実装中: 全CFGからOSR位置のbuiltin型を推論し、入口で各localの型をguard。
実フレームの観察値は使わず、定数値/compact/uniqueの事実は引き継がない。
guard失敗はbackedgeの設置位置でなくloop headerへ復帰して進捗を保証する。
list/tuple/dict等の既知のbuiltin constructorの戻り型も伝播。GIL debug build中。

M13: GIL debug関連287件は285成功・2skip。固定releaseも作成したが未計測。
regex_compileの別診断40反復ではunsupported経路の頻発によるmethod破棄が1,266回。
M14ではcodeごとの小さなbackoff cacheを追加し、同じbytecodeの再解析を15回分
遅延する。特殊化が変われば即時再試行し、変わらなくても周期的に再試行するので、
後からhot pathが変わった場合も永久に最適化を諦めない。
初回増分buildではcode.h変更がJIT stencilの依存関係に入っておらずSIGSEGV。
Makefile・Windows regen・stencil digestへcode.hを追加して再生成すると解消。
M14b関連288件は285成功・2skip・1error。errorは特殊化変更の即時retry検証で、
fingerprintがGetBaseCodeUnitにより特殊化opcodeを消していたことが原因。
実opcodeを保持するよう修正。M14b診断で破棄回数は393回に減少（性能値ではない）。

M15実装中: 兄弟型が異なるPythonメソッドを上書きしている場合も型version群を
検証し、実際のdescriptorをtype lookup cacheから取得する。呼出し側は特定calleeを
inlineせず、実calleeの現在のcode/defaultsへ引数を束縛してmethod entryを呼ぶ。
function vectorcall変更・instance shadow・descriptor差替え・例外も検証対象。
M14のfingerprint修正を含めてGIL debugをbuild中。次は正しさ検証と固定releaseでの
Richards/regex/fannkuch/deltablue再比較、その後FT検証と全suite。10%条件は未達。

M15: GIL debug関連289件は287成功・2skip、FT debugは282成功・7skip。
GIL広域19ファイル1,858件（15skip）はすべて成功。元のRichards 40回の結果も正しい。
固定release SHA 7344398f237ad15c52029cf4b4cdfaff97a21b09c86e42de62cc7834e62a98e4、
FT debug SHA 80167b7ab8b36f1693279f9c2852825bc5f790d33f9b24d7b04c9df08477aba2。
4仕様比較中。M14bの診断では_compileに15、_parseに13の異なる入口があり、4slotの
backoff履歴を頻繁に追い出していた。M16では16slotに広げ、単一入口の周期retryは維持。
また成功したscalar guardが証明するlocalの型・compactnessをCFGへ伝播する。
live frameを観察せず、途中のlocal上書きではstackの古いoriginを無効にする。
分岐先での重複guard削減、walrusによるlocal上書き、巨大int/float/complexのfallbackを
検証するテストを追加。source編集のみでM15の計測にbuild/testを重ねていない。

M15の4仕様比較完了: 失敗0、identity一致。Richards 1.3547 [1.3488,1.3601]、
regex 1.1562 [1.1468,1.1662]、fannkuch 1.1361 [1.1340,1.1383]、
deltablue 1.0775 [1.0710,1.0842]。まだ3仕様が10%を超える。
別Richards perf診断200回ではTier1自己時間14.23%、FrameClearAndPop 9.17%。

M16増分検証は古いstencilを使いSIGSEGV。code.hを追加した先がJIT_DEPSでなく
既存PYTHON_HEADERSの同名行だったため、正しい依存箇所へ修正した。
開発build helperもconfig.status Makefile.preでMakefileを更新するよう修正。
M16で先に見えた最適化shapeのfailure 2件は新しい型伝播による融合への影響を要調査。
M17ではlocalsplus数が0〜4のmethod returnについて既存のframe cleanupをinline化。
通常の逆順decref、関数/codeのcleanup順、finalizer中のstack storage保持を維持する。
frame object/localsが実体化済み、generator、stack chunk境界は既存cleanupへ戻す。
各local数のfinalizer順序・再入・GCと、materialized frameを検証する。GIL debug build中。

M17b: GIL関連292件は290成功・2skip。新しいscalar guard伝播、0〜4localsのreturn
cleanup、既存の2つの融合も成功。融合器がtype既知時のoverflow-only guardを受理する
よう修正した。tracing frontendなしで動作。M17bの固定GIL releaseとFT debugを新規build中。
M18では、GIL時に関数の静的namespaceにある非immortal bindingも定数化する。
既存の名前単位watcherとglobals identity guardで変更を検出し、通常の所有参照loadを
使う。live frameの値は参照しない。非immortal値の破棄中の再入・GC、同一codeを別globals
で使う場合、削除後のNameErrorを検証する。FTはimmortal値のみに制限を維持。
M18のsource/testを編集したが未ビルド。M17b測定候補にはこの変更を含めない。

M17b固定GIL release SHA 43c2e28b42bdb7b29311eeb458c2f008f4ce23d854d637727f108843938c9196、
FT debug SHA cc3459bf9d8a17c13653147127cd38d34e8fa757d74f3383ededaec9444f6aa7。
GIL広域19ファイル1,858件（15skip）成功。FT関連テストとM18開発buildを実行中。
削除済みget_exit_executorを呼ぶ旧テストは、nested-loopの単一method CFGとguard失敗時に
side executorを生成しないこと・無効化後の再コンパイルを検査するテストへ変更した。
観察したtuple要素からfloat型を記録する2テストも、未知型のgeneric演算・ゼロ除算・
独自operandのcallbackを検証する1つのparameterizedテストへ変更。
静的にfloat型が証明された場合の最適化テストは維持しており、一括skipはしない。

M17b FT関連292件は285成功・7skip。M18の全非immortal binding定数化は、レビューで
mutable instanceの__class__変更がbinding変更を伴わない問題に気づいたため未実行のまま
制限した。M18bはPy_TYPEがimmutableでmoduleではない値のみを追加対象とする。
型が変わり得るインスタンスは従来のguard付きloadを維持する。
非immortal関数のweakref callback中の再入/GCと、global instanceの__class__変更をテスト。
M18b GIL開発build中。次は関連テストとM17b固定候補の4仕様比較。

M18b GIL関連294件は292成功・2skip。旧最適化テスト309件は93failure・3skip。
M11cから改善した検証もあるが、OSR入口/他のCFG経路のcleanup増加やguard除去に伴う
shape差も含むため、単純にfailure数だけで最適化効果を判断しない。要求される未移植の
最適化と、削除したfrontend固有の期待を引き続き区別する。
M17bの4仕様比較は16runすべて成功、identity一致。regex_compileは約1.05倍へ改善し、
10%条件を満たす。Richardsは約1.35倍、fannkuchは約1.12倍で残る。deltablueは約1.05倍。
M18b固定GIL release buildとGIL広域テストを開始した。次はその性能比較と、Richardsで
頻繁な短い属性predicateをframeなしで静的inlineできる範囲を調査する。

M17b確定比: Richards 1.3534 [1.3458,1.3583]、fannkuch 1.1242 [1.1219,1.1269]、
deltablue 1.0524 [1.0482,1.0567]、regex_compile 1.0491 [1.0374,1.0587]。
M18b固定release SHA e6bc0b2e51f0915e24eb43c84265ce9fa724ff73e9721dc18947d2974b007db6。
M18b GIL広域19ファイル1,858件（15skip）成功。固定releaseはまだ未計測。
M19実装中: stored attribute最大3個の短いboolean predicateの全bytecode CFGから
truth tableを静的に計算し、引数を消費する前に型version群・属性配置・exact boolを
検証してframeなしで実行する。callback/descriptor/missing属性/非boolの場合は元のcallへ
戻し、short-circuitとframe可視性を保つ。監視中・FT・DTraceは対象外。
dict/slotと兄弟クラス、8通りのtruth table、bound/unbound call、__bool__ callback、
未評価のmissing属性、property差替え、profile hookを検証するテストを追加した。
ベンチマーク名の条件分岐やlive frameの記録は使わない。M19 GIL debugをbuild中。

M19初回295件は291成功・2skip・2failure（新predicateテストのdict/slot両ケース）。
テスト内のreset_codeがfunction versionを無効にしてCALL特殊化を妨げていたので、
独立したcodeから新規functionを作って隔離する形に修正。bytecodeのNOT_TAKEN markerも
predicate解析で許可する。callee codeを依存集合へ加え、calleeだけのmonitoring開始でも
呼出し側のframe省略を無効にする。code変更・local monitoringも検証に追加した。
M19b GIL debugをbuild中。M18b固定releaseは未計測のまま維持している。

M19c: fresh defで生成するpredicateテストへ修正後、GIL関連295件は293成功・2skip。
mutable開発treeへテストのみ更新して実行し、固定releaseは更新済みの完全patchから
新規buildした。SHA 7963e71b42477397fead573cb9eefdc5f6bce70c8cc33e70f4825bcc6e7e5c63。
元Richards40回すべて成功、scheduleの静的CFGで_CALL_BOOL_ATTRIBUTESを2か所確認。
M19cの4仕様比較（Richards/fannkuch/regex/deltablue、逆順2block・各3worker）を開始。
ビルドと重い検証は測定完了まで止める。M18bは未計測。

M20実装中: 元fannkuchのflip分岐でBINARY_OP/TO_BOOL/COMPARE_OPのcounterが9のまま
残っていた。未実行armの汎用uopを静的CFGへ入れると、以降はnative実行されるため
Tier 1の特殊化が永久に進まない。初期warmup状態の演算をTier 1 fallbackにし、
通常の特殊化後にmethodを再構築する。既に特殊化が失敗した汎用命令は引き続き生成。
冷たいarmを後で熱くするテストとfloat/巨大整数/例外の意味検証を追加。未build・未検証。

M19c比較完了: identity一致。Richards 1.3560 [1.3515,1.3606]、fannkuch 1.1293
[1.1265,1.1324]、regex_compile 1.0604 [1.0586,1.0624]。deltablue候補は両block失敗。
M18bとM19cで元deltablueのAttributeErrorを再現、M17bは1,000回成功。
追加の最小テストも修正前に失敗した。lookup_attrのPOP_TOP＋定数loadへ分解された
class attribute値を後段のstore融合が取り込み、guard失敗時に消費済みownerが必要な
LOAD_ATTRへdeoptしていた。prefix POP_TOPの属性置換を元の一つのuopのまま残し、
定数のsymbol情報と型watcherは維持する修正をM20へ追加した。
class属性変更・削除・別receiver・property callbackのframeも新規テストで検証する。
M20 GIL debugをbuild中。M19cはdeltablueの正しさを満たさない候補として保存する。

M20b: GIL関連297件は295成功・2skip。新しい2テストも成功した。
完全callee CFGを検査する既存2テストは両armを4回ずつ事前実行するよう変更し、
元の3return/全CFG/例外検証を保持した。未学習armの特殊化は新規専用テストで検証。
GIL広域19ファイル1,628件（15skip）成功。今回はtest_capi/type/unicodeとmonitoringを
含む構成で、以前の1,858件セットと対象が異なる。deltablue元workload1,000回成功。
fannkuch元workload4回すべて30。flip分岐に整数演算・list slice・TO_BOOL_INTが現れ、
該当する汎用演算は残らない。M20b固定releaseをbuild中。

M20b固定release SHA 87277d53d30dac1f210a51180b2dcf5fff2ccdaa58ba099c7ebebc5f86454b56。
Richardsの別perf診断（元workload200回、lost 0）ではTier 1自己時間14.72%、
FrameClearAndPop 2.68%。これらは測定時間比の代用にはしない。
4仕様のM20b比較を開始し、ビルド・検証を止めた。
旧最適化309件は93failure・2error・3skip。2errorは定数load分解を止めたための
opcode期待差であり、他の失敗とともに更新・未移植最適化の分類が必要。

M21実装中: method呼出しのC境界を減らすため、静的inlineを2段まで許可する。
2段目は48命令以下、全体uop budgetは既存上限。既に解決済みの内側CFG辺を
外側のblock番号として再解釈しないようにする。Pythonフレームは通常通り残す。
三関数の値・分岐・callbackからのframe可視性・孫calleeのcode変更によるinvalidation
を検証するテストを追加した。未build・未検証、M20b測定終了後に検証する。

M20bの4仕様比較は16run成功・identity一致。Richards 1.3577 [1.3469,1.3641]、
regex_compile 1.0524 [1.0453,1.0599]、deltablue 1.0191 [0.9874,1.0396]、
fannkuch 0.9158 [0.9135,0.9188]。fannkuchの10%超回帰を解消し、mainより8.4%高速化。
Richardsは約36%で残る。他仕様・FT・PGO/fullLTOはまだ現候補で比較していない。
M21 GIL debugをbuild開始。2段inlineの正しさを確認して固定buildでRichardsを比較する。

M21 GIL関連298件は296成功・2skip。元Richards40回も成功。
未固定・未計測の中間実装として保存する。
RichardsのM19c生成uopを調べるとDevice/Handler/Idle/Workの4つのfnのsuper().fn呼出しに
同一の_CALL_STORE_ATTRIBUTE（型version 131883）が埋め込まれていた。共有calleeの
一つのcacheだけを使うフレーム省略が、他receiverでのTier 1復帰を増やす候補となる。
M22: 同じlayoutの型familyが既に見つかる小さいgetter/setterは通常の静的callee CFGを
選び、複数型のguardを維持する。2兄弟型・caller内のfamily guard保持・property差替え
とsetter frameを検査するテストを追加した。M22 debugをbuild中。M21とM22を統合して
次の固定releaseで比較するため、両変更の個別寄与は未分離となる。

M22 GIL関連299件は297成功・2skip、Richards元workload40回成功。
一方deltablueでmethod_finish_uopsのlabel assertionを検出し、性能測定は開始しなかった。
gdbのsandbox ptrace拒否後、許可された外側実行でcoreとuop列を/tmpへ保存して調査。
自動承認レビューの拒否はない。globalなgdb/OS設定は変更していない。
原因: nested calleeの最適化でuop列を伸長するとき、外側calleeの未解決return sentinel
UINT64_MAXまで絶対offsetとして加算していた。overflowでtarget 0になっていた。
M22bではsentinelをrelocation対象から外す。nested loop・early return・list subclass
へのappend・fallback例外を検証するテストも追加（この小さいケース単独では旧版の
assertionは再現せず、元deltablueが検出した失敗を直接の回帰検証に使う）。build中。

M22b: GIL関連300件は298成功・2skip。GIL広域1,628件（15skip）成功。
元deltablue1,000回成功で、検出したlabel assertionが解消した。
完全差分をm22b-method-only.patchへ固定し、GIL/noPGO/noLTO releaseとFT debugを新規build。
同じpatchから両構成を検証する。タイミング測定は両buildとFT検証が終わってから再開。
次はRichardsと既知14仕様の比較、全pyperformanceのscreen、残る旧最適化テストの移行。

M22b固定build完成: GIL release SHA 85131c6be05bbfee337737f74247df56ad55f8ac0480480dccebb92c4c55b943、
FT debug SHA 4a86389cbc44b4fc449e1c2214941bdf10004c953ec19ac9c47d46955d3cf99f。
新規5テストのGIL参照リーク検査（-R 3:3）は成功。FT関連300件とfree-threadingの8ファイルを
検証中。旧最適化309件は94failure・2error・3skip。2errorは、属性の原子的uop維持に伴い
実際の属性loadとcall後のvalidity checkを検査する期待に修正し、個別に成功した。
このテストのみの修正はM22cと呼び、固定M22bのruntime/build内容は変更しない。

M22b FT関連300件は290成功・10skip。free-threading関連8ファイル66件成功。
固定GIL releaseでも元deltablue1,000回成功。重いbuild/testを終えて、全97仕様の
GIL/noPGO/noLTO screenを開始した（m22b-gil-all-screen）。各仕様をmain→candidate、
candidate→mainの2block、各2worker・5warmup・5value・min-time 0.1秒、CPU 2で実行。
既知14仕様を先にし、残る83仕様は名前順。networkx workerは15秒、他60秒、仕様300秒。
全workerを保存し、上限付近/超過や不安定な項目は別の宣言した追加比較で検証する。
まず固定build一組の開発screenであり、FT/PGO/fullLTOの性能結果ではない。
測定中はビルド・重い検証・perfを並行しない。

M22b全体screenは14仕様56run成功後、2to3のmetadata検証でKeyError停止。
command benchmarkの実行ファイルはpython_executableではなくcommandに保存される。
14完了分の全identityを監査・一致確認して保存し、検証分岐のみ直して残る83仕様を
m22b-gil-rest-screenへ再開。2to3の未記録JSON/logも保持した。
14仕様ではRichards 1.3603 [1.3558,1.3649]が10%超。ほか最大float 1.0592、
fannkuch 0.9081、nbody 0.9038、spectral_norm 0.6661。最新表をmethod_only_report.mdへ更新。
M21/M22で生成コードは変わったがRichards速度は改善せず、実pyperf workerのexecutorと
Tier 1復帰を診断する準備を進める。測定中のbuild/test/perfは引き続き止める。

M23実装中: 同じreceiverで繰り返す型family guardの静的な共通化を追加。
単一型だと仮定せず、最大32個のversion集合をCFG内でinternし、抽象値には小さいIDのみ保持。
borrowed属性の読み書き後に証明をlocalへ伝え、Pythonへescapeする操作で破棄する。
同じ集合だけguardを省略し、一部だけ重なる集合は区別する。dict/slot、property変更、
callback中の__class__変更、異なるoffsetを持つ重なるfamilyのテストを追加した。
未build・未検証・未計測であり、Richards改善を確認したものではない。

旧named-global検証のfixtureを、__class__変更可能なheap instanceから、属性dictとweakrefを
持つimmutable typeのfunction objectへ変更。監視対象はnamespaceのbindingであり、
新frontendが定数化する対象でwatcher・コピーしたglobalsのidentity・寿命を検査する。
元のheap instanceの__class__変更は専用の意味検証を残す。未実行。

M23に合わせたテスト移行準備: GenericHashの定数keyはimmutableなobject()で検証し、
heap keyの__class__変更で__hash__が差し替わるfallbackを別テストへ追加。
部分型guard/aliasの検証は入口で未知な引数へ変更し、OSRの型推論だけで検査が消えるのを防ぐ。
callee frame数の検証は保持し、全CFGに含まれるcallerのreturnをreturn数へ追加。
generatorの旧記録frame期待は、Tier 1での値・yield-fromの返却値・非コンパイルを検査する形に移行。
4種比較runnerも削除済みsourceのmanifest tombstoneを検査できるよう修正し、復活したfileや
dangling symlinkを拒否するテストを追加。以上まだ未実行。

M22b追加screenでasyncio_tcp、asyncio_tcp_ssl、asyncio_websocketsが両側ともsocketの生成/bindに失敗。
sandbox内のsystem Pythonによる最小socket生成でもEPERMを確認した。元の失敗ログは保存し、
本screen後にこの3仕様をsandbox外で両側再測定する。失敗を性能回帰や成功数へ数えない。

M24設計候補（未適用）: dynamic Python method callを専用のEvalFrame境界で実行し、
callee内部のTier 1復帰後もnative callerを継続する案をm24-dynamic-call-proposal.patchへ保存。
現在の_METHOD_CALLはcalleeがnativeから外れたときcallerもTier 1へ戻す。
このC評価境界はcall setupを増やすので、速くなるかは未確定。実workerの診断とM23検証後に
独立候補として評価する。M23 runtime/test差分はm23-method-only-pending.patchへ固定した。

M22b screenの失敗を追加分類: concurrent_imap/daskは両側ともプロセス同期資源の
作成でEPERM。fastapiは両側ともhttpx未導入だが、元の準備ログまで遡ると
pydantic-core 2.46.5 / PyO3 0.28.3がPython 3.16を拒否し、依存group全体が未準備だった。
httpxだけを追加して解決とは扱わない。固定依存treeは測定中に変更せず、失敗ログを保持する。
このscreenには準備失敗groupも含めたため、完了後は実行成功、sandbox制限、依存未準備を
区別して集計する。networkxは15秒worker上限を維持して実行中。

全体screenの途中でlogging_format、nqueens、networkx shortest_pathも10%境界付近/超過を検出。
まだ最後のidentity監査前の暫定値で、全結果確定後に追加workerで再確認する。
nqueensの元workloadは探索・順列生成・内包表記がgenerator中心で、現在のTier 1 fallback方針の
影響を切り分ける必要がある。loggingはvarargsを持つPython calleeから戻った後のcaller継続も
診断対象とする。ベンチマーク固有の名前による選別やworkload変更は行わない。
Richards用診断hookにcached opcode番号と固定stencilサイズによるuop別perf mapを追加した。
これは測定対象外のshadow hookだけの変更で、M22b固定runtime/依存/harnessを変えていない。

InternalDocs/jit.mdを実際のmethod frontend、静的CFG/OSR、Tier 1 fallback、共有uop最適化、
executor寿命に合わせて更新し、削除済みrecord_functions.c.hの.gitattributes項目を削除。
FTでは2個目のthread state作成時にJITを無効化し、そのthread終了後も自動再有効化しない
現在の制限を明記した。旧trace専用の未使用frame/IP guard定義とstats補助関数も残っており、
M23比較後の削除対象として確認した（現在のmethod生成経路からは参照されない）。

M22b全97仕様screen完了・両区間identity監査一致。89仕様115結果で4run完了、
成功結果の時間比の幾何平均0.9850。10%超はrichards_super 1.3603、richards 1.2519、
scimark_lu 1.2477、logging_format 1.1265、nqueens 1.1067、shortest_path 1.1010。
base32_small 1.0987とlogging_simple 1.0969も追加確認対象。8仕様失敗:
socket/同期EPERMの6仕様、依存未準備fastapi、15秒timeoutのnetworkx_k_core。
networkx timeoutは延長しない。全表をbenchmarks/method_only_m22b_screen.mdへ保存。

実pyperf workerのRichards診断成功。perfのtaskset -c2引数エラーを-c 2へ直し、
失敗記録を別保存して再実行。約19K samples、lost 0。teardown時点のexecutor mapで
85.77%がnative uopに対応。family guard 13.09%、METHOD_CALL 12.52%、managed values 5.17%、
stack check 4.03%、C側FrameClearAndPop 2.55%、recursion margin check 2.54%。
この結果はcalleeのTier 1 fallbackが支配的という仮説を支持しない。型guard共通化を検証し、
初期にcompileされたcallerがcallee特殊化後のinline機会を取り逃していないかを調べる。
method_windowは256周期であり、255だから実行1回だけとは解釈しない。

M23の新family guard検証は変更前でdict/slotの2subtestが失敗し、変更後の
TestMethodFrontend 179件（1skip）成功。旧最適化310件は70failure・3skip・0errorまで移行。
残る失敗には未移植最適化があり、全テスト成功とは報告しない。4種runnerの8テスト成功。
完全差分m23-method-only.patchを固定し、GIL release buildと追加GIL検証を開始。
全測定とperfは終了しており、build/testとのtiming競合はない。

M23追加検証: executor invalidation/TestUopsの34件（1skip）、広域15ファイル2,239件
（24skip）成功。固定GIL/noPGO/noLTO release SHA
58af103caacbaf2c95d1ffb506900e49bb9f0bbaa631f94a0885ea00d9a4b318。
10仕様を各3worker・逆順2blockで比較開始（m23-gil-regression-screen）。測定中のbuild/test/perfを停止。

実workerで最初のwarmup後に元workloadのexecutorを強制invalidateする別診断では、
再compile後もTask.runTaskのMETHOD_CALL 4個とfamily guard 8個は同じだった。
次にfunction version cacheを直接診断し、実関数845のslotが4941に上書きされ、
Task.runTask/他calleeのslotもNULLまたは別versionになっていることを確認。
next_version=5565で、4096枠のdirect-map cacheがpyperfの起動中に衝突していた。
slotを失うと生きた関数でもmethod_lookup_functionがNULLを返し、静的inlineができない。
以前の直接workload診断と実workerの生成codeが異なる原因の一つと考えられる。

M24実装中（未build・未検証）: 呼出し先が静的に分かるglobal/function descriptorを
抽象値として保持し、version cache検索より先に、その関数とCALL cacheのversion一致を検査する。
receiver型/family/descriptorとfunction versionの既存guardは維持。異なるoverrideの
familyは従来のdynamic method経路のまま。キャッシュ容量は変えない。
テスト用に弱参照のfunction version cacheだけを空にするhelperを追加し、global関数・
同じ継承methodを持つ兄弟receiverのinline、およびcallee.__code__変更後の値を検査する。
以前M24と呼んだEvalFrame境界案は未適用proposalとして保留し、このcache衝突対策を優先する。

M23比較は10仕様26結果・40runすべて成功、identity一致。Richards Super 1.2984
[1.2945,1.3017]、Richards 1.1894 [1.1650,1.2043]で重複family guard削減の改善を確認。
10%超はほかscimark_lu 1.2493、logging_format 1.1207、nqueens 1.1116。
shortest_pathは0.9881 [0.9181,1.0333]となり、前screenの10%超は再現しないが、
block間の変動が大きいのでM23の改善寄与とは断定しない。base32_small 1.0938、
logging_simple 1.0951は境界付近。regex_compile 1.0541、go 1.0542、fannkuch 0.9127。

M24のcache evictionテストは旧M23 runtimeに試験用のcache-clear shimだけを入れて実行し、
global関数・継承methodの両subtestでMETHOD_CALLが残る失敗を確認した。
初回buildでmethod cacheを_PyAttrCacheとして記述した型名誤りを検出。
正しい_PyLoadMethodCache/type_versionへ直してM24bをbuild中。失敗ログも保持する。

M24b検証完了: TestMethodFrontend 180件（1skip）、executor/TestUops 34件（1skip）、
新cache evictionテストの-R3:3参照リーク検査、広域15ファイル2,239件（24skip）、
元Richards 40回とdeltablue 1,000回が成功。旧最適化は310件中70failure・3skipで未移植が残る。
M24cでは既知calleeのversion照合を既存func_state mutex内に置き、FTの同期規則を統一。
incremental buildとcache eviction/test_optimizerの7件が成功（test_optimizer単独も6件成功）。完全差分を固定し、
GIL releaseとFT debugを新規build中。M24の性能効果はまだ未測定。

M24cの新規GIL release SHA 50cec7b24f223690c9ffeda872f6eb999de94270816cf622a42ff1a3e0934638、
FT debug SHA 8a3971bd724b90fcc6dbebb75eec0efab5a02506f214126f904319c2514d6542。
GIL/FT method関連214件ずつ、FTの8ファイル、元deltablue1,000回成功。
5仕様を3worker・逆順2blockで比較中。固定ソースと測定中のbinaryは変更しない。

M26ソース作業（未生成・未build・未検証）: Python __getitem__への静的inlineに着手。
BINARY_OPの既存5cache unitsを維持し、GETITEMの未使用4unitsに型・関数versionを保存する。
Tier 1のpolymorphic hit経路はそのまま。methodは型とcompile時関数versionを明示guardし、
既存のCHECK/INIT_CALL/PUSH_FRAMEとcallee CFGをつなぐ。別call siteによる型の
getitem cache更新でも古いCFGが新関数を受け入れないよう、固定versionを比較する。
GILのみ有効。cache衝突、__code__変更・型変更・listへの変更・例外・frame観測のテストを追加。
旧tracerの未使用8種のframe/IP guard、dynamic exit判定とuop、side-trace用exit flag、
未使用effective_trace_lengthも削除。生成ファイル更新と変更前後検証は測定完了後に行う。

M24c比較完了: 5仕様11結果20run成功・identity一致。richards 0.8702
[0.8679,0.8722]、richards_super 1.0220 [1.0202,1.0236]、logging_format 1.0754
[1.0664,1.0853]で10%以内。nqueens 1.0932 [1.0752,1.1099]は境界を追加確認。
再比較で10%超はscimark_lu 1.2393 [1.2318,1.2446]のみ。全suiteと最終構成は未測定。
M26の新3テストはM24c以前runtimeで期待するinline uopがなく3failure（errorなし）。
生成ファイル11個の再生成成功、開発debug build開始。再帰上限guardとPython
getitem境界での型family/所有権fact破棄も追加。性能測定との競合なし。

M26初回build成功。新3テストの最初の失敗原因はfixture: 関数入口閾値8192に対し
ループ閾値4002×2=8004しか呼んでおらず、readのexecutorが未生成だった。
初回before/afterの3failureだけを変更前の証拠とは扱わない。map経由でcallerによる
inlineを防ぎ、TIER2_RESUME_THRESHOLD+10へ修正。固定M24cでは3件とも
_METHOD_SUBSCR_CHECK_FUNCがなく失敗し、M26では値/書換え/frame/例外の2件成功。
再帰1件でRecursionErrorが出ない問題を発見。

この再帰問題は固定main・JIT=0でも再現した。BINARY_OP_SUBSCR_GETITEMは
PUSH_FRAME前に再帰残量を検査せず、スタック領域が残っていると上限を超えて進む。
test_opcacheの新テスト（現在depth+40の上限で60段の添字再帰）もmainで失敗。
M26bでは既存_CHECK_RECURSION_REMAININGをGETITEM macroへ追加し、Tier 1と
methodの両方で所有権移動前に検査する。重複するmethod専用チェックは除去。
生成ファイル更新成功、debug再build中。

M24c実pyperf workerのteardown診断も完了（比較timingとしては使用しない）。
M22b scheduleは_CALL_BOOL_ATTRIBUTES 0個・METHOD_CALL 2個、M24cはそれぞれ2個・1個。
Task.runTaskはM24cで独立executorを持たずcaller側のinlineを調べる必要があるため、
単独uop数の増減は比較しない。元workerの生成codeでもcache修正の反映を確認した。

M26b修正後: 新3件+旧getitem inlineの4件、JIT有効の再帰テスト、JIT無効
test_opcache 95件、method関連217件（2skip）、添字新3件の-R3:3、広域2,239件
（24skip）、元deltablue1,000回成功。追加の__class__変更callbackテストも成功。
旧最適化310件は68failure・3skipへ減少したが、まだ全test_opt成功ではない。
完全差分M26cを固定し、GIL releaseとFT debugを新規build中。
tracer削除の再検索でanalyzer.pyに削除済み_DYNAMIC_EXITの文字列だけ残存を発見。
実行時の生成経路はなく、次のソース整理で削除する。

M26c固定後の小整理（次の候補に反映）: analyzer.pyの削除済み_DYNAMIC_EXIT文字列を除去。
method_optimize_blocksのframe生成境界へ_BINARY_OP_SUBSCR_INIT_CALLを追加し、
通常CALLと同じくcallee CFGを独立に最適化する。M26cではunknown callableで
frame_new_from_symbolがctx->doneを立てて停止していたため、実行時の誤ったframe
推論は行われないが、明示的に境界を揃えた。M26cの固定ソース・binaryは変えない。

M26c新規build完了: GIL release SHA
7326bfc1c4842439d1da1edecfab7798244f147ca2172c3b665a44cb439dfe32、
FT debug SHA e26733ae90e7636ac8362fd5d6f35c1999a4092f1d33dd451bbbb983808d1a4e。
両方でC _decimalを確認。GIL/FT method関連218件ずつ、FTのJIT無効test_opcacheと
並行実行8ファイル、元deltablue1,000回成功。7仕様を3worker・逆順2blockで比較開始。
測定中のbuild/test/perfは停止。

M26cのscimark両blockは完了したが、LUは約1.26で改善しない（全screenの監査待ち）。
元workerのexecutorと数値出力を測定後に診断するscriptを準備。

M27ソース作業（未build・未検証）: inline calleeを全引数unknownで解析する制限を緩める。
callerの静的CFGで既に証明済みの、immortal/immutableな組み込み型だけをcallee入口へ渡す。
通常のCALL_PY_EXACT_ARGSとPython添字アクセスに限定し、bound-methodのslot変換、
可変引数/default bindingは対象外。定数identity・compact性・所有権・heap型は渡さない。
これによりrange由来のintやリテラルの型からcallee内isinstanceを定数化できる見込み。
通常関数/添字双方のinlineとcode変更を検査する新テストを追加。これは実行記録ではなく
caller CFGの事実の引継ぎであり、M26cの固定比較候補には含まれない。

M26c比較完了: 7仕様23結果28run成功・identity一致。LU 1.2616
[1.2581,1.2651]で10%条件未達。Richards 0.8712、Richards Super 1.0206、
logging_format 1.0933（CI上端1.1056）、nqueens 1.0910、base85_small 1.0893。
scimark_sorはM24c 0.9619→M26c 1.0573となり、10%以内だが悪化を追跡する。
元LUのサイズ1/2/5/17/100×seed3種×3反復の行列/pivot結果を、
main/candidate×JIT0/1の4通りで比較し、全SHA-256一致。
実workerでLU_factorのexecutorが残らず、debugでは頻繁なfallbackで破棄されていた。

M27の引数型伝播は変更前2件で_CALL_ISINSTANCEが残り失敗、変更後6件成功。
未知入力と__class__を偽装する可変オブジェクトを渡す追加テストも成功。
method関連220件、広域2,239件、参照リーク検査、元deltablueとLU数値比較が成功。
旧最適化は310件中67failure・3skip。M27は独立したrelease性能測定を行っていない。
LUはM27でもuop予算が内側ループのSWAP/STORE_SUBSCR/末尾に達してfallbackし、
executorが破棄されるため、次の対策を優先する。

M28実装・build中: OSRの静的backedgeが指すループheaderから基本blockを配置し、
その後に関数の残りを回り込んで配置する。入口型推論は従来のCFGで済ませた後、
block番号と全edgeを一括で付け替え、両方の分岐経路は維持する。
またpartial methodだけでnative backedgeを上限8まで数え、十分なloop進行後の
unsupported exitは破棄理由としない。進行しないentryは従来の32miss閾値で破棄する。
新counterは既存executorのpaddingに収まり、complete methodには計測uopを追加しない。
初回fixtureのIMPORT_NAMEは既に対応済みだったため、未対応property参照へ変更。
修正済みfixtureでは、変更前は有用loopの保持と大きな外側bodyでのOSRが失敗し、
進行しないloopの破棄は成功。生成ファイル更新成功、M28 debug build中。

M28 debug build成功、新3テスト成功。method関連224件（2skip）、
追加/関連10件の-R3:3、広域2,239件（24skip）、JIT無効test_opcache 95件、
元deltablue1,000回、LU数値比較が成功。元LU直接診断では、M26/M27で繰り返していた
frequent fallbackによるLU_factor executor破棄が消えた。これは性能値ではない。
旧最適化310件は67failure・3skipのまま。
完全差分m28-method-only.patchを固定し、GIL release/FT debugを新規build中。
続いてscimark・logging・regex_compile・nqueens・richards_super・goの6仕様を
3worker・逆順2blockで比較する。最終構成・全suiteの10%条件はまだ未達/未確認。

M28固定比較完了: 6仕様12結果24runすべて成功、実行前後のidentity一致。
GIL release SHA 44e2f2ca28440e03c1c5ad2609e095056dd9156098b46dfe27a12893646436f8、
FT debug SHA 4d700e4a7991c05381f75976a9191f4c3a68ec6709de58497546566f371b3ae5。
固定GIL/FTのmethod224件ずつ、FT JIT無効opcache95件、並行実行66件成功。
LU 0.7211 [0.7194,0.7228]まで改善。Richards Super 1.0224、regex_compile 1.0202、
SOR 1.0290。一方go 1.1312 [1.1208,1.1404]、nqueens 1.1073 [1.1032,1.1112]で
10%超過。logging_format 1.0965 [1.0862,1.1070]も境界を追跡する。
次はgo/nqueensの元workerのexecutorをM26cとM28で比較し、最終PGO/FT構成へ進む。

M26cのGoを追加固定比較: 1.1438 [1.1379,1.1508]、4run成功・identity一致。
Goの10%超はM28 OSR配置以前から再現した。M26c/M28の元nqueens workerでは
permutations/n_queens/bench_n_queensのすべてにexecutorがない。
M29実装中: ordinary generatorのbackedge OSRのみを許可し、入口locals/stackは
毎回unknown。yieldをCFG終端として扱い、yield/returnは既存_DEOPTでTier 1へ戻す。
callee generatorはinlineせず、FOR_ITER_GENは既存の一般iterator呼び出し経路へ下げる。
coroutine/async generator/iterable coroutineは対象外。新5テストを追加して検証中。

M29初期buildでjson.dumpが終了しない問題を発見。生成したFOR_ITER_GENの
exhaustion edgeにtarget blockを設定し忘れていた。GDBのC/Python stackを保存し、
該当build childだけを停止。設定を追加したM29bはbuild成功・新5テスト成功。
旧methodテスト229件中5failureはgenerator/consumerにexecutorがないという期待。
OSR入口・native iterator呼び出し・非native yieldの検査へ更新した。
-R3:3の初回失敗は参照数判定ではなく2巡目のexecutor存在assert。入力型を変える
前の実行のcompile backoffが同じcodeへ残るため、各fixtureでreset_codeする。
修正後7関連テスト成功。M29cを固定してGIL release/FT debugの新規build、
新テストの参照リーク・広域テスト・旧最適化テストを実行中。性能はまだ未測定。

M29cのGIL/FT build完了。SHA: GIL 65eb49aed0e085b7554035a485cb44555ae6934d7b6fe26616cc1e803cbb8401、
FT debug fcd1a9c68ec179f8409f1c29d6fb6ee930fd3ddca5dcd50c2ffccd547ffbdcdf。
両方のmethod229件、新generator5件の-R3:3、FT generator/frame/monitoring、
FT opcache95件と並行実行66件が成功。debug広域2,239件成功、旧最適化67failure。
固定比較を実行中。nqueens両blockは約1.23へ悪化、Goも約1.13のまま。
generator OSRと、FOR_ITER_GENをC境界へ下げる変更を分離して調べる必要がある。

M30ソース案（未build、M29c固定候補とは別）: 名前ごとのglobal依存失効を
64entryのbounded cacheに記録し、既存の6回閾値を超えたbindingを定数化しない。
namespace全体を停止せず、無関係なstable bindingの最適化は継続できる設計。
キャッシュはGIL buildのみ。アドレス/hashの再利用や衝突は定数化の機会にだけ影響し、
記録値からPython値・型・実行経路を推論しない。frontendと共通optimizer両方で参照。
新2テストを追加し、測定終了後に変更前の失敗を確認する。
interp構造体headerをJIT stencilのMakefile依存・digest・Windows再生成入力にも追加。

M29c固定比較完了: 6仕様12結果24run成功・identity一致。
nqueens 1.2269 [1.2228,1.2310]へ悪化、Go 1.1337 [1.1188,1.1437]。
LU 0.7198、Richards Super 1.0211、regex_compile 1.0229、logging_format 1.0941。
M29d実験を作成: M29cからFOR_ITER_GENのC呼び出しloweringだけを取り除き、
generator OSRの効果と分離する。rootは別のM30候補で、M29dは独立固定ソース。
M30新globalテスト2件は変更前に両方executorなしで失敗。M30 debug build中。

M29dの分離比較完了: nqueens 1.0609 [1.0239,1.0862]、Go 1.1341 [1.1285,1.1394]。
両block・全8run成功、identity一致。C経由のFOR_ITER_GEN loweringが大きな悪化を
起こしており、取り除く。generator本体のOSRとTier 1 suspensionは残す。
M30 global対策は新2件、method231件、7ケース-R3:3、広域2,239件成功。
旧最適化67failureは継続。M30は独立したrelease性能を測定していない。
M31はM30のglobal対策とM29dのgenerator境界を統合した候補。
非対応consumerのretirementテスト3件を元の期待へ戻し、GIL/FT buildと検証中。

M31固定build完了: GIL 5740afd5177cd0a3c90d56dc72542abe17dbd38d4fe50f82279ddbb375f74fd9、
FT debug c21fd9e4d63165ca4a767709543d200b5b695ed2ceab86dd4ad0ff70bb1d35fc。
GIL/FT method231件ずつ、GIL新7件-R3:3、広域2,239件、FT generator関連・
opcache・並行実行、元deltablue成功。9仕様の固定比較を実行中。

M32テスト移行（runtimeはM31のまま）: OSR上の未知iteratorの型を記録する期待8件を
METHOD_FOR_ITERへ変更。None判定は片側guardではなく両分岐を検査し、isinstanceの
未知入力は一般呼び出しを保持する期待へ変更、evalで型の変わる入力も追加した。
文字列/sequence添字のテストは特殊化と借用cleanupを保持し、whole-CFG内の他blockに
あるcleanupまで含むtrace時代の個数制約を外した。計21テスト成功。
固定M31のソース・binaryは変更せず、rootのテスト変更として次のbuildへ含める。
残る未移植最適化のテストを一括skipしたり、性能値で成功扱いしたりはしない。


M31固定比較完了: 9仕様25結果36run成功、実行前後のidentity一致。
Go 0.8100 [0.7992,0.8179]、LU 0.7235 [0.7223,0.7247]、Richards 0.8678、
Richards Super 1.0225、nqueens 1.0899、regex_compile 1.0171。
10%を超える点推定はbase85_small 1.1019 [1.1001,1.1038]のみ。
logging_format 1.0966 [1.0871,1.1055]も境界として追跡する。
これらはGIL/noPGO/noLTOの部分比較であり、最終2構成・全suite・local8は未確認。
生データ: `jit-artifacts/regressions-20260919/m31-gil-regression-screen-state.json`、
集計: 同名 `-analysis.json`。全worker・逆順両blockを保持した。

M32: M27の引数型伝播で、immutableなModuleTypeを持つinstanceは型も変わらないと
誤って仮定する不具合を発見。moduleは__class__を変更できるため、calleesとOSR入口に
渡す安定型からmoduleを除外した。__class__を差し替えた後のisinstanceの結果が
誤る新テストはM31で失敗し、修正後成功。これは候補で発見した不具合であり、mainの
バグと確認したものではない。関連・参照リーク・広域検査を継続中。


M32開発検証完了: 新module型変更・OSR関連、method232件、参照リーク、広域2,239件成功。
旧310件は最初47failure。直接return/property fallback等の8テスト移行後には39failureで、
propertyの残るconstant-load期待を削除し、戻り値とTier 1境界を明示的に検査した。
さらにlen比較融合、dict receiver guard、tuple→locals融合、store後の借用cleanupを
現行uopに合わせて検査するテスト変更を準備中。未対応のbranch narrowing・calleeを
またぐ所有権推論などの期待は一括skipせず、失敗として保存している。

固定 `m32-method-only.patch` からGIL PGO/fullLTOとFT debugを新規build中。
FT debugの型変更・OSR・generator・並行実行検査後、同じpatchでFT releaseを作る。
どのbuildにも同じC mpdecimal archiveをリンクする。固定ソースは変更しない。
以後のrootテスト移行は別のソースidentityとして扱う。
次は両最終構成の全pyperformanceとlocal8を逆順blockで比較し、1.10超の項目を調べる。


M32dのGIL全test_opt 542件成功（5skip）。旧tracing前提のテストを、methodの
直接return/attribute-return、全CFGの両分岐、callee境界の所有権、Tier 1で行う
property/特殊メソッドへ移行。定数推論・所有権推論の未移植部分を実装済みとせず、
通常/未訪問分岐、コード差し替え、参照数、例外・副作用を検査する。
FT全test_optでは35件の最適化期待が失敗。mutable globalの保持やGIL専用call
短縮との違いを確認し、FTのguarded load/frame呼び出しと意味論を検査する移行中。
これらのrootテスト変更は固定M32の性能比較用ソースとは別に記録している。

M32 FT release完成: c853b66f696991c54cbde4c915c2532396b96c26b335a5c389df1035b47905c8。
FT debugのmethod232件（21skip）・関連12件-R3:3・core635件（9skip）・
並行実行66件・JIT無効opcache95件成功。FT release method232件成功。
FTのC系1,154件とGIL PGO学習はtest_reのforkserver socket.bindがsandboxの
EPERMで失敗。ログと失敗PGOの.gcdaを保存し、空のprofileから同じseed/taskで
sandbox外の学習をやり直した。再学習は成功、最終PGO/LTOリンクと検査を継続中。
性能値はまだ測定しておらず、全構成10%条件の達成は未確認。


M32fの全test_optはGIL/FTとも542件成功（5/30skip）。新規の一括skipは追加していない。
FTはmutable globalを一般loadで読むためGIL専用定数化/call短縮の期待を分け、
値の置換・namespace寿命・構造変更・コード置換後の意味論を両構成で検査した。
構造変更/namespace解放時はFTでもexecutorを失効させることを確認して期待を維持。
テストの固定コピー/ハッシュと使用binaryは `m32f-test-provenance.json` に保存。
rootのLibをPYTHONPATHに指定した正しさの検査であり、性能測定にはこのoverlayを使わない。
旧branch narrowing、calleeをまたぐ所有権・戻り値の定数推論は未移植のまま。
現行method CFG/短縮命令と両分岐・参照数・副作用のテストに移行したのであって、
旧最適化をすべて実装したという意味ではない。

PGOのsandbox外再学習43ファイルは成功（同じrandseed/profile task）。
FT C系1,154件と元deltablue1,000回もsandbox外で成功。
最終PGO/fullLTOリンク完了後の検査と、両profileの全suite/local8比較が次の作業。


M32最終GIL PGO/fullLTO build完成: 127564ec79cde3ee5a5028583bb7320bcd5684f9a8397ababb22bcbde88b5781。
method232件、C系1,154件、元deltablue成功。four-way runnerをM32固定候補へ更新し、
依存を用意した環境でrunner unit8件成功。host Python単体での初回2errorはpackaging未導入。
10仕様（go/nqueens/scimark/logging/regex_compile/richards_super/richards/base64/networkx/telco）
をGIL→FTの順で3worker・逆順2block・CPU2・seed0で確認中。計測中のbuild/testは停止。
networkx worker上限15秒を維持する。終了後に全suiteとlocal8へ進む。


M32最終GIL PGO/fullLTOの10仕様26結果40runが完了。全run成功・identity一致。
10%超の点推定はbase32_small 1.1494 [1.1273,1.1903]、logging_format 1.1071
[1.1003,1.1138]、nqueens 1.1046 [1.0959,1.1120]。Go 0.8665、LU 0.7557、
Richards 0.9201、Richards Super 1.0332、C telco 0.9840。
base85_smallは1.0457 [0.9498,1.1115]で、block比0.9877/1.1072と変動が大きい。
初期blockだけを改善の根拠にせず、全worker・両blockを保持する。
結果: `m32-gil-final-screen-state.json` / `m32-gil-final-screen-analysis.json`。
FTの同じ10仕様を継続測定中。終了後に元logging/base32 workerをJIT有効/無効で
別途profileし、呼び出し処理とC処理の寄与を分離する。診断値を比較結果へ混ぜない。
property再初期化時のcache保持についてもソース上の懸念があり、測定後に再現を確認する。
現段階では新たなmainのバグとして確定/報告していない。


比較中のソース確認: CALL_PY_GENERALのdefault/keyword-only引数初期化では、
callerで証明済みのimmutableな実引数型もcalleeへ渡していない。また、module属性
loadが必ずpushするNULL self-slotの静的情報が失われる。base32 wrapperの改善候補。
引数の型だけを伝播し、変更可能なkwdefaultsの値/型や実行中frameからの情報は推論しない。
現時点では仮説であり、M32の測定用ソースを変更していない。profilingを先に行う。


### M32: 最終 FT 確認と呼び出しの診断（2026-09-20）

FT 最終ビルドの 10 specification / 26 結果は、全 40 run が成功し、
実行ファイル・入力の同一性検証も成功した。全結果の点推定が main 比 1.10 以下。
最大は logging_silent 1.0627 [1.0577, 1.0680]。
shortest_path は 1.0233 [0.9755, 1.1079] と幅があり、全体の達成はまだ主張しない。
GIL 側の base32_small 1.1494、logging_format 1.1071、nqueens 1.1046 は未解決。
全 suite と local 8 の現在の候補による検証も残っている。

元の logging/base32 workload を JIT 有効・無効で perf 採取した。
JIT 無効では main と候補の時間は近く、有効時の Python 呼び出しが次の調査対象。
診断 hook 初版はゼロ長 stencil の名前を解決できず失敗したため、ゼロ長も登録して
新しい出力先で全 8 run を再実行し成功した。失敗記録を保持し、この計測を
通常の性能比較には混ぜない。次は一般呼び出しの引数型伝播と inlining を調べる。

property 再初期化後の古い getter 呼び出しを main/candidate × GIL/FT × JIT on/off
の全 8 通りで確認した。main 由来の未修正バグとして bugs_report.md の M-17 に記録。
重複していた番号は Python indexing の項目を M-16 に整理した。


### M33: 呼び出し境界の改善（実装・検証中）

- `CALL_PY_GENERAL` の NULL self slot が静的に証明できる場合、明示された位置引数の
  不変組み込み型を callee CFG に渡す。位置・keyword-only default は未知のまま。
  LOAD_ATTR の展開が必ず NULL を積む場合も、この事実を CFG に残す。
  新規 2 テストは M32 で失敗、M33a の全 test_opt 544 テストは成功（skip 5）。
- property と独自 `__getattribute__` は `_LOAD_ATTR` の通常呼び出しへ展開して
  native continuation へ戻す。キャッシュされた getter の埋め込みは行わない。
  呼び出し後の receiver guard は破棄する。再初期化・例外・呼び出し回数を検証。
  M33b の全テストでは旧 Tier 1 fallback 前提の 3 箇所だけが失敗したため、
  property の期待を新しい通常呼び出しへ更新し、retirement のテストは引き続き
  未対応命令を使うよう変更した。
- 実際の base32 worker で module 経由の関数が weak function-version cache から
  消え、全呼び出しが `_METHOD_CALL` になることを確認した。
  GIL build で静的名前空間の binding hint を保持してコンパイル対象を回復する。
  hint は実行時の identity/type の証明には使わず、関数バージョンのガードを残す。
  cache eviction の再現テストは M33b で失敗。M33c で検証中。

性能への効果はまだ測定していない。次は正当性テスト後に凍結した非 PGO ビルドで
独立比較し、有効なら最終 4 構成比較へ進む。


M33c の全 546 test_opt は、retirement fixture の 1 件を除き成功した。
generator iteration に置き換えた fixture では保持した executor の破棄条件を
満たせなかったため、`raise ValueError(total)` で未対応 continuation へ戻る形に
変更した。長い native loop を保持する場合・短い loop を破棄する場合の両方が成功。
失敗した fixture の記録は m33c-retirement.log に保存した。
M33d は runtime を変えずこの fixture だけ修正し、全体を再検証中。
M33 の固定 patch から GIL release（非 PGO/LTO）と FT debug を作成している。


M33d GIL debug: test_opt 全 546 成功（skip 5）、呼び出し境界関連 1,202 成功
（10 ファイル、skip 5）、新規 4 テストの `-R 3:3` 成功。
GIL release / FT debug のビルド・FT 検証後、`base64,logging,nqueens` の
3 worker × 2 逆順 block を実施する自動制御を起動した。
この制御はすべてのビルドと正当性テストの終了を確認してから計測を開始する。


M33 正当性検証完了: GIL debug 全 546（skip 5）と境界関連 1,202（skip 5）、
FT debug 全 546（skip 31）と境界・並行関連 1,231（skip 5）、
GIL/FT 新規テスト `-R 3:3`、GIL release method frontend 202（skip 1）が成功した。
FT の追加 skip 1 は、生の namespace binding hint を使う GIL 専用最適化のテスト。
新規テストを一括 skip する変更はない。

固定 GIL 非 PGO/LTO 実行ファイル SHA-256:
`473df2ec1bad758c2ef233bc8a3199a7d183bb3d885a179edc87e2a8e350cb87`。
固定 FT debug SHA-256:
`8c1b06d8ab471affdbd1024ad433c6ed6ede9f450c9e3fc867902b847ef43315`。
全ビルド・正当性テスト終了後、M33 GIL 非 PGO/LTO の 3 specification の
両順序比較を開始した。結果確定前なので性能改善の達成はまだ主張しない。


### M33 非 PGO/LTO screen 結果と namespace lookup の修正

3 specification / 15 結果、両順序の全 12 run が成功し、入力・実行ファイルの
同一性確認も成功。main 比: base32_small 1.0527 [1.0505, 1.0551]、
logging_format 1.0647 [1.0379, 1.0862]、nqueens 1.0883 [1.0788, 1.0968]。
全点推定は 1.10 以下だが、base64_small は 1.0950 [1.0492, 1.1793] で
block 間にも差（1.1413 / 1.0506）がある。全 worker を保持し、最終ビルドで確認する。
これは非 PGO/LTO の screen であり、M32 PGO/LTO との差を単独変更の効果とはしない。

レビューで namespace hint の通常辞書検索が任意キーの `__eq__` を実行し得ると
分かった。M33e の新規テストでは、実行しない分岐のコンパイル中に equality が
4 回呼ばれることを修正前バイナリで確認した（m33e-binding-before.log）。
これは今回追加した候補側の不具合で、main の不具合とは分類しない。
修正は unicode-key 辞書とキャッシュの keys version/index を検証して直接値を読む。
コンパイル中の Python 呼び出しを避け、関数の実行時ガードもそのまま保持する。
併せて符号の違う整数比較の警告 2 箇所を整理した。固定 M33 screen のソース・
バイナリは変更していない。M33e の再検証後に最終ビルドへ進む。


M33e の namespace 修正後は GIL debug test_opt 全 547（skip 5）と新規 5 テストの
`-R 3:3` が成功した。four-way runner の 8 テストも成功。
worker 単位の集計処理は既存の両構成の完全な比較データで検証し、元の結果を変更せず
一時ディレクトリへ再集計して成功した。

最終候補は `m33e-method-only.patch` で固定。FT release は完成し SHA-256 は
`1042e1f4a1cc1ed9319c0f4995b95b693a57c40ed0f395c9e0f17010af3be1fd`。
GIL PGO/full-LTO は学習用ビルド成功後、sandbox 外で seed 0・JIT 無効の同じ
PGO 学習 task を実行中。最終リンク後、GIL/FT の JIT・属性・C 関連テストを実施する。
その完了を待つ four-way controller を起動済み。3 worker、2 block、5 warmup、
5 value、CPU 2、worker timeout 60 秒（networkx は 15 秒、specification 上限 60 秒）。
両構成を準備してから FT と GIL を順番に計測する。並行するビルド・テストは行わない。
出力予定: `jit-artifacts/method-only-m33-full/`。local 8 と独立した確認比較はその後。


M33e 最終 GIL PGO/fullLTO が完成。SHA-256:
`b0d6fefaccd4f69a2c01785cc10e90309dfe08c67af1ebcb4cfe3c80d75dd50c`。
PGO 学習は一度で成功（139.3 秒）。失敗した profile の再利用はない。
FT/GIL の最終 native build ともに test_opt 547（skip 32 / 5）、
属性・呼び出し・monitoring 486（skip 3）、C decimal/binascii/re 1,154（skip 28）が成功。
実行ファイルの検証前後の SHA も一致した。four-way 全 suite の依存準備を開始した。
録画frontend・side traceの旧entry/exit名がソース・ビルド定義に残らないことも再確認。
共通uop backendやPythonのtraceback/tracemallocは別の機能として維持する。


全 suite は両構成とも 97 specification、23 dependency group を準備した。
既存の固定 fastapi group は Python 3.16 非対応の依存により準備できず、失敗を保持。
残る 96 specification の計測を FT から開始した。各仕様は同じ block 内で
main/candidate を続けて実行し、全仕様を一巡した後の次 block で順序を逆転する。
開発用 compare.py の「各仕様で両 block を続けて測る」順序とは区別する。
最終判定は両 block 完了後の全 worker と測定後 identity 検証に基づく。


M33 全体比較の FT 第1 block: asyncio_tcp / asyncio_tcp_ssl / asyncio_websockets が
main・candidate ともに成功した。以前の sandbox 制限による失敗はこの実行条件では
再発していない。ここまで 46 run に実行失敗なし。まだ逆順 block の前なので
この段階の値は最終比較として扱わない。


FT 第1 block の networkx と connected_components は両者成功。
networkx_k_core は main/candidate とも worker の15秒上限で timeout（rc 124）。
候補側の全体打ち切りは18.9秒で、ログに `Timed out after 15 seconds` を確認。
上限を延長せず比較不成立として残し、他の仕様の計測を継続した。


### M34: rangeのcompactness誤認を修正し、M33比較を中止

静的frontendがFOR_ITER_RANGEの返すC longをcompact intと仮定していた。
ブロック境界を越えて比較のcompactness guardが消え、`value < 5` が
`range(1 << 30, (1 << 30) + 20000)` の先頭5個を誤ってtrueとした。
GIL/FTのM33 release・JIT有効で期待値0に対し5。mainと候補のJIT無効は正常。
mainに由来する不具合ではなく、このmethod frontendの不具合である。
別の加算probeはdebug assertionを再現するがreleaseでは正しいため、
誤結果の根拠は比較probe（m33-range-comparison-results.json）と区別する。

M34はrangeの要素についてexact intだけを伝播し、compactnessを仮定しない。
新規テストは大小・正負の境界ごとにcodeを初期化して再compileし、先行guard missで
後続ケースが隠れないようにした。GIL debug全548（skip 5）と新規テストの
`-R 3:3`が成功（m34b-opt-full.log / m34b-range-refleak.log）。
修正前FT debugでも同じテストのassertion failureを確認済み。

M33のFT controllerを停止し、実行中worker終了後にcontrollerを終了した。
計測workerと再現テストは重ねていない。FT第1blockの188 runを保持し、
GIL・逆順block・local 8は未実施。中止理由・時刻はm33-boundary-pause.json。
この不完全な旧候補の測定を最終比較として集計しない。
次は同一M34 patchのFT debugと最終FT/GILビルドを検証し、別出力先
`jit-artifacts/method-only-m34-full/`で比較を最初から実施する。


M33中止後のFT/GIL identity再検証はともに成功。旧runnerも保存してから、
通常のfour-way runnerをM34の固定buildへ向けた。M34では最終buildの正当性検証後、
既知のGIL回帰10仕様を3 worker・両順序で先に確認する。点推定1.10超または失敗なら
そこで止めて調査し、通過後に全97仕様・local 8へ進む。判定前に測定回数を固定し、
遅いworkerを削除しない。PGOは最終GIL比較だけに使用する。


M34のFT debug/releaseビルドが成功（239.2秒 / 218.6秒）。
FT release SHA-256: `d3c547119584aaa1fb272ff8e36d16186c5f1278538db25591784866bccb3935`。
GILの新規PGO学習は139.4秒で成功した。同じ標準task、seed 0、JIT無効を維持し、
前候補のprofileは混ぜていない。最終リンク後に3構成の正当性検証へ進む。


M34最終GIL PGO/fullLTO SHA-256:
`44ca073ed4bca19fd04de31abd553c730ac799bf1a5debb3bc66fcfe05bb22d9`。
3構成でtest_opt全548、属性・呼び出し・monitoring 486、C関連1,154が成功。
skip数はFT debug 32/1/27、FT release 32/3/28、GIL release 5/3/28。
rangeの比較probeは3構成×JIT有効/無効の全6条件で正解し、FT debugの新規テスト
`-R 3:3`も成功。GIL debugの同テストも既に成功している。

最初のM34先行計測は無効とする。03:03:31 UTCに追加の短い正当性probeを実行し、
自動開始済みの計測と重なったため。遅い値を理由に除外するものではない。
controllerを停止し、実行中workerの終了を15.1秒待ってから終了した。
理由・時刻はm34-screen-protocol-violation.json、生データはm34-gil-final-screen-*に保持。
ソース・バイナリ・入力を変えず、同じ3 worker×2 block・10仕様すべてを
`m34b-gil-final-screen-*`へ取り直す。M34bは測定の識別名であり、runtime変更はない。
以後は計測終了を確認するまで追加の実行診断も行わない。


M34b先行比較は29/40 runまで実行失敗なし。両順序が終わった項目では、
Goは約0.87、Richardsは約0.92、Richards superは約1.04。
nqueensは約1.115、logging_formatは約1.134で10%超が見えている。
全runと測定後identity検証・worker単位の区間計算はまだ完了していない。

次の診断候補はgeneratorのsuspension境界とloggingのproperty/callee境界。
ソース上、現在のgenerator OSRはYIELD_VALUEの直前でTier 1へ戻る。
propertyは汎用属性取得を通すためgetterを静的inlineしない。
これらは時間差の原因とまだ確定していない。先行比較終了後、同じ固定buildで
main/candidate×JIT有効/無効のperfと実際のworkerのexecutorを調べる。
診断用の拡張・driverは準備だけとし、計測が終わるまでビルド・実行しない。


### M34b GIL PGO/fullLTO 先行比較の確定結果

10仕様・26結果、全40 run成功。測定前後のidentityが一致した。3 worker、両順序、全workerを等しく集計した結果。

| Benchmark | candidate/main | worker bootstrap 95% CI |
|---|---:|---:|
| logging_format | 1.1339 | [1.1244, 1.1443] |
| nqueens | 1.1152 | [1.1078, 1.1236] |
| logging_simple | 1.0917 | [1.0849, 1.0990] |
| base32_small | 1.0850 | [1.0837, 1.0863] |
| scimark_sor | 1.0649 | [1.0617, 1.0688] |
| base85_small | 1.0619 | [1.0563, 1.0667] |
| base64_small | 1.0591 | [1.0577, 1.0604] |
| regex_compile | 1.0439 | [1.0301, 1.0556] |
| richards_super | 1.0373 | [1.0356, 1.0390] |
| logging_silent | 1.0141 | [1.0107, 1.0176] |
| base32_large | 1.0088 | [1.0075, 1.0099] |
| shortest_path | 0.9999 | [0.9966, 1.0035] |
| telco | 0.9978 | [0.9946, 1.0009] |
| base85_large | 0.9953 | [0.9943, 0.9962] |
| base64_large | 0.9884 | [0.9871, 0.9897] |
| urlsafe_base64_small | 0.9816 | [0.9806, 0.9825] |
| scimark_fft | 0.9620 | [0.9559, 0.9702] |
| scimark_sparse_mat_mult | 0.9412 | [0.9327, 0.9547] |
| ascii85_small | 0.9343 | [0.9322, 0.9363] |
| richards | 0.9228 | [0.9131, 0.9296] |
| scimark_monte_carlo | 0.8865 | [0.8847, 0.8885] |
| base16_small | 0.8740 | [0.8720, 0.8760] |
| go | 0.8726 | [0.8643, 0.8781] |
| base16_large | 0.8046 | [0.7064, 0.8523] |
| ascii85_large | 0.7986 | [0.7973, 0.7997] |
| scimark_lu | 0.7598 | [0.7585, 0.7610] |

logging_formatとnqueensは区間の下端も1.10超。全suite・local 8を開始せず、修正に戻る。
logging_simpleは1.0917で境界に近い。base16_largeはblock間の差が大きいが全workerを保持した。
生データ: `jit-artifacts/regressions-20260919/m34b-gil-final-screen-*`。
未修正mainのFTはTier 1であり、今の表はGILのtracing/method比較だけを表す。
測定終了を確認してから、ABIを合わせた診断拡張をビルドし、perfの別実験を開始した。


### M35: generator yieldとmodule属性ロードを改善（実装・検証中）

M34のperf診断12 run（3仕様×両者×JIT有効/無効）が完了し、すべて成功した。
これは比較本番とは別の固定仕事量の診断。loggingは1,048,576 loop、nqueensは64 loop、
base32_smallは32,768 loop。loggingの各loop内部の反復も含むため、1 runは約1分になる。
全記録はm34-profiling.jsonとm34-perf-*。perfの時間を先行比較へ混ぜない。
nqueens候補のEvalFrameDefault selfは22.49%（coldは別に1.79%）。
ソース行ではFOR_ITER_GEN、YIELD_VALUE、POP_TOP、JUMP_BACKWARD_JIT、RESUME_CHECKが上位。
実際のexecutorではmainがgenerator間のframe遷移とyieldを含み、候補はyield直前でdeoptする。

M35は既存の_YIELD_VALUEを静的CFGの終端として使い、callerへTier 1で復帰する。
普通のreturn_offsetはiteratorの「終了先」なので、yieldではSEND/FOR_ITERのcache直後へ
戻る専用exitを設けた。suspensionを越える型推論やrecordingは追加しない。
frame遷移としてIP保存を保持し、callbackでmonitoring等が変わった場合のvalidity検査も入れる。

logging候補では、0.3%以上の行だけでも_LOAD_ATTR_MODULEが計4.18%を占めた。
M35では静的namespace hintから安定した属性を解決し、named dictionary dependencyと
実行時のexact-module/dictionary-identity検査を組み合わせる。
module自体を定数型として扱わず、__class__変更後も検査を残す。
属性値は型が不変なものに限定し、module値は除く。guardと結果ロードを一つのuopに保ち、
owner消費後のguard失敗でstack契約が壊れる既知パターンを避ける。FTではこの定数化をしない。

generatorのC/Python/yield-from callerと例外状態、moduleのbinding/dictionary/class変更・
unrelated値更新・値の寿命を含む5テストを追加。旧M34での失敗は新規native経路の不在であり、
旧候補の意味論の不具合を示すものではない。初回の生成器はFT条件分岐内のDEAD(owner)に対し
所有権の不一致を検出したため、FTの即時exit後に共通の所有権処理を置く形へ修正した。
生成器再実行後、非PGO/LTOのdebug buildで検証する。性能への効果はまだ未測定。

### M35b: 新規module命令のコード生成を修正（検証中）

M35の生成器は、専用yield exitのcache depthを0へ固定した後に成功し、
非PGO/LTO debug buildも成功した。しかし新規テストはnative codeでabortした。
gdb、最終uop列、stencilの機械語オフセットを照合し、原因はyieldではなく
_LOAD_ATTR_MODULE_CONSTと確定した。生成器は#ifdef内のEXIT_IF(true)を終端と解釈し、
後続のmodule guard/loadを削除していた。GIL専用frontendだけがこの命令を発行するため、
不要な条件付き無条件exitを除去した。11生成物を再生成して再ビルド中。
monitoringがcallback内で有効になるケースを加え、新規テストは計6件。
この6件、test_opt全体、refleak、generator/monitoring、生成器/JIT toolを順に検証する。
失敗したM35のログ・バックトレース・stencil照合結果は保持し、性能測定には使わない。

M35bの修正後、新規6件は成功。test_opt全554件は旧yield非対応を期待する2件だけ失敗し、
双方をnative yieldと専用exitの存在検査へ更新した。refleak用にgenerator codeを毎回
resetする。callback自体のreset_codeはfunction versionを恒久的にclearedへ変えるため、
通常の新規callbackを事前warmupして使う。M35c/dのテスト調整失敗も保存した。
runtimeはM35bのまま、最終テスト定義でM35e検証を進める。

M35eのGIL debug検証はすべて成功。test_opt 554件（5skip）、新規6件R3:3、
generator/genexp/yield-from/monitoring 201件、生成器/JITツール91件。
実行済みruntimeはM35bで、M35eはテスト定義調整後の検証ラベル。
独立source snapshotからFT debugとGIL release（非PGO/LTO）をビルドし、両者の
JIT全体・generator・C decimal等を検証してから、nqueens/logging/base64を
同条件main非PGO/LTOと逆順2block×3workerで測る。ビルド/検証中に測定しない。

### M35b: 独立ビルドの検証と非PGO先行比較が完了

FT debug: test_opt 554件（35skip）、generator/monitoring 201件、新規yield3件R3:3に成功。
C検証1154件ではtest_reのforkserver socketがsandboxに拒否されたが、通常環境で
そのファイルを再実行して成功。GIL releaseもtest_opt・generator・C検証に成功。
GIL非PGO/LTO先行比較は3仕様15結果、全12 run成功、identity一致。
main非PGO/LTOとの比較であり、PGO/fullLTOの合否には流用しない。

| Result | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0836 | 1.0681–1.0942 |
| logging_format | 1.0540 | 1.0414–1.0639 |
| base32_small | 1.0368 | 1.0330–1.0415 |
| base64_small | 1.0354 | 1.0337–1.0371 |
| logging_simple | 1.0309 | 1.0214–1.0390 |
| base85_small | 1.0192 | 1.0174–1.0210 |
| base64_large | 1.0074 | 1.0064–1.0085 |
| base32_large | 1.0036 | 1.0024–1.0050 |
| base85_large | 1.0010 | 1.0004–1.0017 |
| logging_silent | 0.9846 | 0.9796–0.9903 |
| ascii85_small | 0.9666 | 0.9651–0.9681 |
| base16_small | 0.9610 | 0.9569–0.9654 |
| urlsafe_base64_small | 0.9537 | 0.9520–0.9554 |
| ascii85_large | 0.9064 | 0.9061–0.9067 |
| base16_large | 0.8896 | 0.8871–0.8921 |

同じsource snapshotで最終GIL PGO/fullLTOとFT releaseをビルドする。
検証後に10仕様screenを行い、合格してから全suiteとlocal8へ進む。

### M36: mainにもあるmodule subclass属性の誤結果を修正

module.__class__をdata descriptor付きsubclassへ変更すると、直接参照は2000を
返すが、特殊化済み関数は辞書に残る1000を返す。main/M35b×GIL/FT×JIT0/1の
8構成すべてで再現した。最初からsubclassでも特殊化後に誤結果となる。
_LOAD_ATTR_MODULEとspecializerがtp_getattroの同一性だけでmodule属性アクセスを
選んでいたため、継承getterを持つsubclassのdata descriptorを無視していた。
両者をexact moduleに限定し、subclassは通常の属性探索へ戻す。
Tier1の2テストとnative method内callback越しの1テストを追加し、修正前の失敗を確認。
詳細はbugs_report.md M-18。M35bの最終比較・全suite待機プロセスを停止し、
最終計測は未開始であることをm35b-final-measurements-cancelled.jsonに記録した。
M35b最終ビルドは参照用に完了させるが、合格候補にはせず、M36を非PGO debugで検証する。

M36 GIL debug検証完了: JIT無効test_opcache 97件、JIT有効test_opt 555件（5skip）、
property/descriptor/monitoring/generatorと生成器/JIT toolを合わせて491件（1skip）が成功。
新規native1件とTier1の2件のR3:3も成功した。
mainへの新規テスト適用は、最初のLib overlayではdisのopcode metadataが候補側になったため、
そのログを意味論の根拠には使わない。frozen mainのLib/disを保ってテストファイルのみ
読み込む再実行で、両件とも1000 != 2000という誤結果を確認した
（m36-main-opcache-before-matched-lib.log）。8構成の独立probeも各binary固有Libを使用した。
修正済みsnapshotからFT debug/releaseとGIL PGO/fullLTOを作成中。

### M36: 最終ビルドの正しさ検証が完了、先行比較中

FT debug/releaseとGIL PGO/fullLTOの全12検証groupが成功。
各構成でtest_opt 555件、call/property/descriptor/monitoring/generator 589件、
C decimal/binascii/re 1154件、JIT無効test_opcache 97件を実行した。
M18の独立probeは3構成×JIT0/1の全6回が成功。FTのnative1件・Tier1の2件のR3:3も成功。
最終GIL build SHA-256: 9443d6899ff5ab7dcc116442fd0a82dac61ff06c65d7b1b3dac4b7f689ba55f5。
同一ソースの2 releaseを固定し、10仕様のGIL先行比較を開始した。
計測中にビルド・テスト・profilingは実行しない。途中の遅い値も含め、全40 runを保持する。

### M36: 最終先行比較は3項目で10%を超過

GIL PGO/fullLTOの10仕様26結果、全40 runが成功し、前後のidentityも一致。
logging_format 1.1173（95% CI 1.1015–1.1324）、logging_simple 1.1065
（1.0860–1.1288）、nqueens 1.1007（1.0991–1.1025）が基準を超えた。
残る23結果は1.10以下。Go 0.8538、Richards 0.9162、LU 0.7576、
regex_compile 1.0610、C decimal使用telco 1.0054。全suite/local8は未開始。
全workerを保持し、判定gateで後続測定を停止した。

測定終了後、固定work量のperf診断12回（3仕様×main/candidate×JIT0/1）を実施、
全回成功。候補nqueensのEvalFrameは19.37%+cold1.83%、mainは0.50%。
permutationsの生成器作成CALLは_METHOD_CALLとなり、RETURN_GENERATOR非対応の
calleeへ入った後、callerのnative継続を失う。生成器本体のnative yieldは既に存在する。
logging候補のnative _LOAD_ATTR_MODULEが1.94%、_LOAD_GLOBAL_MODULEが1.78%。
プロファイルは原因調査用で、上記時間比には混ぜない。

次は、生成器作成を通常vectorcallで完了してnative callerへ戻す経路と、
型を定数と仮定しないmodule bindingロードを実装・検証する。
既存一般vectorcall helperはPython callableにも対応し、実際のcallableを毎回呼ぶ。
moduleのbinding監視とruntime属性guardを維持し、__class__変更を型定数化で消さない。

### M37: 生成器作成の継続とmodule bindingロードを実装（未検証）

生成器のcode versionを既存cacheから参照し、通常vectorcallの既存uopを選ぶ。
cacheのcodeはFT mutex内だけで読み、関数オブジェクトが死んだgenexprにも使える。
これは選択用hintであり、実際のcallableへの通常呼出しを省略しないため、
関数code変更や異なるcallableにも意味論を維持する。生成器の反復方法は変更しない。

GILではmoduleのglobal bindingも監視付きで埋め込むが、新規_LOAD_MODULE_BINDINGは
型不明のsymbolを返す。module値の属性ロードも同様に型を仮定しない。
既存namespace identity・named dependency・exact module runtime guardを保つ。
FTは引き続きmodule bindingを定数化しない。

生成器作成後の継続/遅延実行/code変更/引数エラー、短命genexpr関数、
moduleの直接/入れ子参照での__class__変更、binding置換/削除/寿命の4テストを追加。
旧M36で新規native経路の不在による5 failure（4テスト）を確認した。
11生成物の再生成は成功し、非PGO/LTO debug buildで検証を開始する。

M37 GIL debug検証は全4group成功。新規4件、test_opt 559件（5skip）、
新規4件のR3:3、call/property/descriptor/monitoring/generator/生成器/JIT toolの
680件（1skip）が通った。codeの種類を変える代入には既存のDeprecationWarningを
明示的に検査する。凍結patchにもこのテスト定義を含めた。
FT debugとGIL非PGO/LTO releaseを独立にビルド中。両者のテスト後、
同設定mainとのnqueens/logging/base64先行比較を2順序×3workerで行う。

M37独立ビルドの検証も成功。FT debug/GIL releaseともtest_opt 559件
（FT 37skip、GIL 5skip）、関連589件、C decimal/binascii/re 1154件が成功。
FTの生成器作成2件R3:3も成功した。GIL release SHA-256は
 d4223de840fbe04fca3e96f665dd753d124d0fdfedb65f91ec1534d9245ca9d2。
非PGO/LTOの3仕様15結果を計測開始。計測中の追加ビルド・テスト・profilingは行わない。
後続の最終ビルド、最終検証、10仕様screen、全97仕様×4構成、local8は
順次のgateで接続した。先行比較が10%を超えれば後続へ進まない。

### M37: 非PGO先行比較で生成器作成の変更を棄却

全12 run・15結果が成功し、identity一致。Nqueensは両順序で悪化し、
最終ビルドgateで停止した。PGO/FT releaseと全suite/local8は未実行。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.1609 | 1.1575–1.1638 |
| logging_format | 1.0284 | 1.0231–1.0346 |
| base32_small | 1.0150 | 1.0138–1.0160 |
| base85_small | 1.0085 | 1.0067–1.0104 |
| base64_small | 1.0041 | 1.0026–1.0057 |
| logging_simple | 1.0035 | 0.9976–1.0093 |
| base64_large | 1.0020 | 1.0017–1.0022 |
| base85_large | 1.0005 | 0.9999–1.0011 |
| base32_large | 0.9977 | 0.9953–0.9998 |
| logging_silent | 0.9763 | 0.9699–0.9829 |
| base16_small | 0.9591 | 0.9423–0.9867 |
| urlsafe_base64_small | 0.9385 | 0.9127–0.9600 |
| ascii85_small | 0.9363 | 0.9349–0.9376 |
| ascii85_large | 0.9037 | 0.9007–0.9056 |
| base16_large | 0.8690 | 0.8660–0.8723 |

生成器作成に汎用C vectorcallを挟む変更を外す。native継続を保つだけでは
追加の呼出し境界を取り戻せなかった。module bindingの改善は残す。
これは非PGO比較であり、最終PGO構成の性能値にはしない。

### M38: rangeの検査を取り出し地点へ集約（検証中）

_ITER_NEXT_RANGE_COMPACTを追加。現在のC long値が1 Python digit内であることを
反復子のstart/len更新前に検査し、成功した後続CFGでのみcompact intとする。
大きい値では同じ未消費の要素をTier1へ渡す。yieldを越えて事実を保持しない。
従来のM34大整数テストに加え、正負のdigit境界を両方向にまたぐrangeと、
yield中のiterator.__setstate__変更を検査する2テストを追加。旧M37は新命令の
不在によりこの2テストで失敗した。11生成物の再生成は成功しdebug build中。
M38のソース編集は固定M37の終盤に行ったが、M37のfrozen source/binaryは
変更せず、前後identity一致を確認。再生成とビルドは全計測完了後に開始した。

M38新規検証の初回は5件中、setstateの期待値1件だけ失敗。
iterator.__setstate__は元のrangeではなく残りのrangeから位置を進めるため、
すでに1個消費したテスト側のoffsetが1大きかった。mainと候補のJIT0でも
同じ挙動を確認し、Objects/rangeobject.cの実装に合わせてテストを修正した。
正負の境界4方向、M34大整数、module2件は成功していた。
runtimeを変更せず、修正したテストでM38b検証を行う。失敗ログは保持する。

M38bの修正後テストは全group成功。新規range2件・M34大整数・module2件の5件、
test_opt 559件（5skip）、同5件のR3:3、関連680件（1skip）。
新range命令のguard失敗は値を消費せず、yield後に変化したiteratorも再検査できた。
同runtimeと修正済みテストを凍結してFT debug/GIL非PGO releaseをビルド中。

M38b独立ビルド検証は全7group成功。両構成でtest_opt 559件
（FT 38skip/GIL 5skip）、関連589件、C関連1154件が成功。
FTのrange検査R3:3も成功し、非PGOの3仕様比較を開始した。
FTで新規setstateテストをskipするのは、外部と共有されたrange iteratorが
既存のunique-reference guardでTier1へ戻るため。通常の境界テストは両構成で実行した。

### M38b: 非PGO先行比較は15結果すべて10%以内

全12 run成功、前後identity一致。全workerを保持し、全15結果で95%区間上端も1.10未満。
同じmain非PGO/LTOとの比較であり、PGO設定の合否には流用しない。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0730 | 1.0687–1.0779 |
| logging_format | 1.0323 | 1.0200–1.0458 |
| base32_small | 1.0223 | 1.0215–1.0232 |
| base85_small | 1.0176 | 1.0079–1.0336 |
| base85_large | 1.0023 | 1.0004–1.0048 |
| base64_large | 1.0021 | 1.0016–1.0026 |
| base64_small | 0.9999 | 0.9982–1.0018 |
| base32_large | 0.9996 | 0.9992–1.0000 |
| logging_simple | 0.9927 | 0.9680–1.0103 |
| logging_silent | 0.9916 | 0.9883–0.9956 |
| urlsafe_base64_small | 0.9686 | 0.9647–0.9722 |
| ascii85_small | 0.9427 | 0.9332–0.9596 |
| base16_small | 0.9356 | 0.9331–0.9380 |
| ascii85_large | 0.9051 | 0.9047–0.9055 |
| base16_large | 0.8698 | 0.8616–0.8782 |

生成器作成のC呼出しを外し、range guardを集約した候補を採用する。
最終比較用FT releaseとGIL PGO/fullLTOのビルドを開始。開発比較は引き続き
非PGO/LTOで行い、PGOは最終構成の比較にだけ用いる。最終検証後は10仕様screen、
合格後に4構成の全suiteとlocal8へ進む。

M38bの大きなstepとC long端点の補助検証も成功。5ケースをmain/candidate×GIL/FT×
JIT0/1の8構成で比較し、全結果が一致。両candidateのJIT1で新compact guardを確認した。
probe_m38b_range_steps.py と m38b-range-steps.json に入力・結果を保存。
FT最終releaseのビルドは成功（SHA-256:
4ae870d62a4e22e0eeabb62f90b7f827cfc4c472141a49a6dec8f962c83719e1）。
GILはPGO計装ビルド中。これらのビルド・補助検証は先行計測完了後に実行した。

M38bの生成コードを固定入力の補助診断でも確認。元のnqueens(8)を16回実行し、
毎回92解であることを検査した後、2つのgenexprのexecutorを取得した。
M36では各bodyに_ITER_NEXT_RANGEと_GUARD_TOS_OVERFLOWEDが2個あった。
M38bは_ITER_NEXT_RANGE_COMPACTの取り出し時検査で、後続2個を除去できていた。
タプルのindex boundsと取り出した値の検査は別に行う。
診断はM36最終GILとM38b開発GILのコード構造比較であり、実行時間は比較していない。
バイナリ・workload hash、warmup回数、解数、全uopをm38b-nqueens-ir-*.jsonに保存。
実施時は最終PGO学習中で、性能計測との重複はない。

### M39: small-int range経路を準備（未検証）

最終M38bのNqueensは両順序で約1.10となり、境界に近い。既知screenの95%区間が
1.10をまたぐ場合は全matrixの前に解決するgateを追加した。全測定は保持する。
次候補では、compact rangeのうち既存small-int cache内の値を直接borrowし、
PyLong_FromLongへのC呼出しを省く。それ以外は既存の通常割当てを使う。
負側・正側のsmall-int cache境界を既存テストに追加。runtime/テストのソース編集のみで、
M38bの固定binary/sourceは変更していない。再生成・ビルドは最終screenと
後続gateが停止したことを確認してから実行する。性能効果は未測定。

M38b最終GIL buildも成功。SHA-256:
eee1d260681749005121575d52af384e1146f6959be6fd7123ee4d624eac55dd。
PGO計装368.1秒、標準43テストの学習139.0秒、最終ビルド203.4秒。
FT/GILの全8検証group（JIT559件、関連589件、C関連1154件、JIT0 opcache97件）が成功。
M18 probeはFT debug/release/GIL×JIT0/1の6回も成功した。最終GIL screenを継続中。
M39は同screenを最後まで保持し、既知結果が未解決で後続gateが停止した後にだけ再生成・
ビルド・テストを行う。先行比較・全suite・local8は異なる候補の値を混ぜない。

### M38b: 最終GIL先行比較は全平均が1.10以下、2結果は区間が境界をまたぐ

10仕様26結果、全40 run成功、identity一致。全workerを保持した。
nqueens 1.0996 [1.0970, 1.1023]、logging_simple 1.0847 [1.0481, 1.1169]。
他の24結果は95%区間の上端も1.10以下。全suite/local8は未開始。
平均のgateは通過したが、既知結果の不確かさを解決するgateで後続を停止した。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0996 | 1.0970–1.1023 |
| base32_small | 1.0869 | 1.0858–1.0880 |
| logging_simple | 1.0847 | 1.0481–1.1169 |
| scimark_sor | 1.0792 | 1.0784–1.0801 |
| logging_format | 1.0604 | 1.0455–1.0739 |
| regex_compile | 1.0458 | 1.0354–1.0545 |
| base64_small | 1.0457 | 1.0449–1.0466 |
| base85_small | 1.0347 | 1.0333–1.0360 |
| richards_super | 1.0137 | 0.9854–1.0297 |
| shortest_path | 1.0075 | 1.0034–1.0140 |
| base32_large | 1.0051 | 1.0044–1.0058 |
| telco | 1.0008 | 1.0000–1.0016 |
| base85_large | 0.9974 | 0.9964–0.9983 |
| logging_silent | 0.9875 | 0.9722–0.9980 |
| base64_large | 0.9847 | 0.9827–0.9861 |
| urlsafe_base64_small | 0.9701 | 0.9688–0.9713 |
| scimark_fft | 0.9583 | 0.9575–0.9591 |
| scimark_sparse_mat_mult | 0.9540 | 0.9435–0.9681 |
| ascii85_small | 0.9266 | 0.9242–0.9301 |
| richards | 0.9226 | 0.9171–0.9276 |
| scimark_monte_carlo | 0.9220 | 0.9190–0.9242 |
| go | 0.8612 | 0.8584–0.8637 |
| base16_small | 0.8513 | 0.8501–0.8527 |
| base16_large | 0.8077 | 0.8062–0.8095 |
| ascii85_large | 0.7962 | 0.7956–0.7968 |
| scimark_lu | 0.7816 | 0.7805–0.7827 |

logging_simpleのcandidate worker平均は約2.928–3.230µsと幅があり、
中央値での時間比も1.0990。速いworkerを除外したり、平均だけで合格とはしない。
M39の非PGO比較完了後、最終PGO buildの前に、固定M38b/mainで追加の診断を行う。

### M39: debug検証完了

small-int cacheを直接borrowする変更は、新規/境界5件、test_opt559件（5skip）、
同5件R3:3、関連680件（1skip）が成功。small-int cacheの正負境界と、
cache外・compact範囲外の既存ケースを実行した。FT debug/GIL非PGO releaseを
独立snapshotからビルド中。性能は未測定。M38bの全計測と後続gate停止後に
再生成・ビルドを開始した。

M39独立ビルドの全検証も成功。GIL/FTともJIT559件、関連589件、C関連1154件、
FT境界R3:3を通過し、非PGOの15結果比較を開始した。
PGOの追加ビルドはまだ開始しない。M39の計測完了後、固定M38b/mainでloggingの
診断を2逆順group×各6worker（合計各12worker）実行する。workloadは元のlogging3項目。
診断hookは計測後にPIDとexecutor列を保存し、workerの速さと生成コードを対応づける。
診断の時間を性能目標の判断用データへ混ぜない。診断中はビルド/別測定を行わない。

### M39: 非PGO比較は全15結果で95%区間上端も1.10未満

全12 run成功、identity一致。追加のsmall-int cache経路を採用する。
nqueensは1.0642 [1.0605, 1.0672]。最終PGOでの効果はまだ測っていない。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0642 | 1.0605–1.0672 |
| logging_format | 1.0299 | 1.0202–1.0414 |
| base32_small | 1.0216 | 1.0147–1.0307 |
| base85_small | 1.0110 | 1.0075–1.0142 |
| logging_simple | 1.0108 | 1.0056–1.0171 |
| base64_large | 1.0034 | 1.0031–1.0038 |
| base85_large | 1.0021 | 1.0003–1.0047 |
| base32_large | 0.9994 | 0.9989–1.0001 |
| base64_small | 0.9959 | 0.9805–1.0049 |
| logging_silent | 0.9759 | 0.9707–0.9810 |
| urlsafe_base64_small | 0.9621 | 0.9605–0.9639 |
| ascii85_small | 0.9376 | 0.9362–0.9389 |
| base16_small | 0.9327 | 0.9057–0.9495 |
| ascii85_large | 0.9064 | 0.9055–0.9078 |
| base16_large | 0.8632 | 0.8599–0.8664 |

logging診断の初回はhook名をcheck_runtimeと誤記し、argparse段階で停止。
測定は未開始で、失敗ログを保持。登録済みft_jitへ修正し、workerへ必要な環境変数を
明示的に継承してdiagnostic2として再実行する。ABIを一致させたmain/candidateの
診断helperを用意済み。M39最終PGOのビルドは診断終了・評価まで開始しない。

### M40: stale arithmetic specializationの再現と修正を実装

M38b logging診断は両逆順group、各側12worker、3結果、全4 run成功。binary identity一致。
同一uop形状でもlogging_simpleは約2.97µsまたは3.28µsとなる。遅いworkerでは
LogRecord.__init__の経過nanosecond/1e6について、Tier 1は既にBINARY_OPへ戻っているが、
methodにはcompact int専用の_GUARD_BINARY_OP_EXTENDが残る。
M39固定binaryで1000→2**32へ変える決定的probeでも、Tier 1が汎用除算へ変わった後、
同じ古いexecutorが有効なまま残ることを確認。probeのJSONと診断worker全件を保存。

M40ではextended arithmetic guardの失敗出口だけで、実行中frameのopcodeとdescriptorを
確認する。Tier 1の特殊化が変更済みならexecutorを無効化し、通常の静的method再構築に
委ねる。単発のguard missでは無効化せず、多態的な処理の有効なmethodを維持する。
inline calleeでもcallee側の命令を見る。成功するguardには追加処理を入れない。
直接呼出し・inline calleeの回帰テストを追加し、11生成物を再生成してdebugビルド中。
次は正しさ・参照リーク・FTを検証し、固定release比較後に最終PGO/fullLTOへ進む。

M40初回ビルドは新規exit uopのdescriptorが生成器でPyObject*型となり、helperの
uint64_t引数へ暗黙変換できず失敗。明示的なuintptr_t経由の変換を追加してM40bとして
再生成・再ビルドした。初回失敗ログを保存し、後続検証は新しいlabelへ分離。

### M40c: stale guardの直接・inline回帰テストが成功

M40b runtimeで小→大int probeを再実行し、旧executorが無効化され、
新executorに汎用_BINARY_OPが含まれることを確認した。単発miss時は旧executorが有効。
inlineテストは新しい関数にreset_codeをかけてしまい、関数変更によるinlining対象外の
条件を作っていた。独立namespaceで毎回新規作成する関数をそのまま使用する形へ修正。
直接/inline両テストが成功。runtimeはM40bと同じで、テスト修正を含むsnapshotをM40c
として保存する。初回失敗を含む全ログを保持し、広域debug検証からやり直す。

実際のLogRecord.__init__にも決定的probeを追加した。time_nsをmutable値を返す
関数に固定し、_startTimeとの差を1000ns→2**32nsへ変更する。M39では除算guardと
同一executorが残り、M40cでは旧executorが無効化され除算guardが消える。
両方のrelativeCreatedは4294.967296msで一致。構造・正しさの検証であり性能値ではない。

opcodeをBINARY_OP_EXTENDのまま保ち、descriptorだけ変わるint+float→float+intの
probeも成功。旧methodは無効化され、異なるdescriptorの新methodへ移行した。
最終FT/GIL検証にもこのprobeとlogging phase probeを加える。
M40cのGIL debugは新規/境界7件、JIT561件（5skip）、新規7件R3:3、
関連680件（1skip）がすべて成功。固定FT-debug/GIL非PGO buildに進んだ。

M40cの固定FT debug/GIL releaseのビルドは成功（それぞれ164.2秒/145.5秒）。
FT JIT561件・関連589件は成功。C関連のtest_reだけforkserverのAF_UNIX bindが
sandbox制限でPermissionErrorとなり停止した。runtime failureではない。失敗ログと
元validation JSONを保存し、成功済みgroupはbinary hashを再確認して保持する。
残りの検証を通常環境で再開し、集約結果はdevelopment-native-validation2.jsonへ保存。
最終ビルドは開発比較完了まで待機する。途中で測定とビルドを重ねない。

M40c通常環境での再開後、全7group（成功済み2groupを含む）の検証が完了。
FT/GILともJIT561件、関連589件、C関連1154件に成功し、FT新規/境界5件の
R3:3も成功した。追加7件のGIL debug R3:3は先に成功済み。
非PGO比較15結果を開始し、最終ビルドはその完了と合否確認まで待機する。

### M40c: 非PGO比較の全15結果で95%区間上端も1.10未満

全12 run成功、identity一致。遅いworkerを含めてすべて保持した。
この構成ではnqueens 1.0735、logging_format 1.0299、logging_simple 1.0140。
最終PGO構成でのloggingのばらつき解消はまだ未確認。GIL PGO/fullLTOと
FT O3/noPGO/noLTOの最終buildを開始する。全suite/local8はまだ未開始。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0735 | 1.0706–1.0766 |
| logging_format | 1.0299 | 1.0233–1.0371 |
| base32_small | 1.0198 | 1.0181–1.0213 |
| base64_small | 1.0169 | 1.0015–1.0449 |
| logging_simple | 1.0140 | 1.0052–1.0236 |
| base85_small | 1.0071 | 1.0059–1.0084 |
| base64_large | 1.0019 | 0.9998–1.0033 |
| base32_large | 0.9995 | 0.9985–1.0002 |
| base85_large | 0.9991 | 0.9964–1.0006 |
| logging_silent | 0.9857 | 0.9836–0.9877 |
| urlsafe_base64_small | 0.9608 | 0.9588–0.9627 |
| base16_small | 0.9494 | 0.9481–0.9507 |
| ascii85_small | 0.9377 | 0.9360–0.9394 |
| ascii85_large | 0.9050 | 0.9045–0.9055 |
| base16_large | 0.8616 | 0.8585–0.8646 |

M40c FT最終release build成功（146.4秒）。SHA-256: a3d144e5e8df2460041dfeb7be350a6cce42442a4f0afcd3f8f953a6e25e0fdb。GIL PGO buildは継続中。最終候補の測定は未開始。

M40c GIL PGO計装ビルド367.3秒、標準43テストの学習139.9秒で成功。
学習はmainと同じJIT無効・seed=0条件。PGO/fullLTOの最終ビルドへ進んだ。

### M40c: 最終buildと全8検証groupが成功

GIL最終PGO/fullLTO buildは203.6秒、SHA-256: 70920f0a2bf782feab44bd448cd709ff433ac44ef66835c911ab4beda6d969b8。
FT/GILともJIT561件、関連589件、C関連1154件、JIT0 opcache97件が成功。
M18 module-class probeはFT debug/release/GIL×JIT0/1の全6回成功。
M40 descriptor変更・logging phaseのprobeもFT debug/release/GILの全6回成功し、
いずれも旧executorが無効化されることを確認した。
最終GIL10仕様26結果の先行比較を開始。全suite/local8はその合否確認後。

M40c最終GIL screen途中経過: Goは両順序で約0.88、nqueensは両順序で約1.084。
前回nqueensの境界付近の平均から改善している。まだ全26結果の集計前であり、
区間確認・loggingのphase問題・全suiteでの10%条件は未確認のままとする。

### M40c: 最終GIL screenの全26結果で95%区間上端も1.10未満

10仕様・全40 run成功、実行ファイル/入力のidentity一致、失敗なし。全workerを保持。
既知のnqueensとlogging_simpleの閾値不確かさを解消し、全suiteへのgateを通過した。
logging_simpleの候補worker平均は今回2.988–3.152µs（前の診断では最大3.287µs）。
ばらつきがゼロになったという意味ではない。成功経路のsmall-int cache利用と、
Tier 1が変更済みの算術特殊化から再コンパイルする処理を維持する。

| Benchmark | method/main | 95% CI |
|---|---:|---:|
| nqueens | 1.0842 | 1.0807–1.0875 |
| logging_format | 1.0784 | 1.0642–1.0946 |
| base32_small | 1.0668 | 1.0658–1.0676 |
| scimark_sor | 1.0587 | 1.0576–1.0597 |
| base64_small | 1.0519 | 1.0511–1.0528 |
| logging_simple | 1.0473 | 1.0283–1.0655 |
| regex_compile | 1.0286 | 1.0145–1.0436 |
| base85_small | 1.0270 | 1.0263–1.0277 |
| richards_super | 1.0231 | 1.0148–1.0290 |
| shortest_path | 1.0094 | 1.0078–1.0109 |
| base32_large | 1.0070 | 1.0046–1.0101 |
| telco | 0.9993 | 0.9944–1.0046 |
| logging_silent | 0.9966 | 0.9919–1.0023 |
| base85_large | 0.9952 | 0.9934–0.9964 |
| urlsafe_base64_small | 0.9847 | 0.9831–0.9862 |
| base64_large | 0.9846 | 0.9835–0.9857 |
| scimark_fft | 0.9706 | 0.9659–0.9783 |
| scimark_sparse_mat_mult | 0.9698 | 0.9605–0.9850 |
| ascii85_small | 0.9335 | 0.9330–0.9340 |
| scimark_monte_carlo | 0.9167 | 0.9155–0.9179 |
| richards | 0.9155 | 0.9077–0.9217 |
| base16_small | 0.8884 | 0.8860–0.8909 |
| go | 0.8779 | 0.8751–0.8809 |
| base16_large | 0.8051 | 0.8038–0.8064 |
| ascii85_large | 0.7970 | 0.7961–0.7979 |
| scimark_lu | 0.7506 | 0.7489–0.7525 |

public four-way runnerの候補をM40cへ固定し、harnessの8テストも成功。
出力先 jit-artifacts/method-only-m40c-full で全97仕様の準備・実行を開始した。
FTを先に、次にGILを順次測る。各構成2逆順block、3worker×5warmup×5value。
fastapiは既知の依存準備失敗が残り、未完了として記録される。
全suite後にbenchmarks/の元の8本（SQLAlchemy含む）を比較する。全体の10%達成は未確認。

M40c全suiteは両構成の依存環境・入力を固定し、FT block 1の測定を開始。
fastapiの元の失敗ログを再確認: pydantic-core 2.46.5 / PyO3 0.28.3が
Python 3.16を拒否しており、runtimeの回帰としては扱わない。

M40c全suite途中: FT block 1の21仕様/42runまで成功。asyncio_tcpのローカル
ソケットも通常環境で実行成功。ここまでの片順序の最大時間比は約1.017。
逆順・GIL・local 8は未完了で、全体の合否には使わない。

M40c全suite途中: FT block 1はfastapiを除く40仕様が両者で成功。
BPE tokeniserは片順序0.804、chaos 0.847、comprehensions 0.909。docutils、
dulwich、Dask、並列pool、fannkuch、floatも成功。最大の暫定遅れはthread pool約4%。
まだ逆順を含む最終性能結果ではない。全workerを保持して続行する。

M40c全suite途中: FT block 1の58仕様が両者で成功。networkx_k_coreは両者とも
worker 15秒上限でtimeout（manager終了まで約19秒、rc=124）。失敗ログを保持し、
時間比の集計には含めない。既知のfastapi依存失敗と区別する。
成功分の暫定最大遅れはgc_traversal約6.6%、connected_components約6.4%。
両順序を揃えた評価はまだ未実施。

M40c全suite途中: FT block 1は76仕様が両者で成功し、成功結果の片順序比は
すべて1.10以下。Python起動、regex_compile、Richards両種、SciMark、spectral_norm
も通過。gc_traversal約1.066、connected_components約1.064が暫定で遅い側。
全体の測定を継続し、逆順の確認と最終identity検証後に評価する。

### M40c: FT全suiteの第1block完了、95仕様で両者が成功

95仕様・122結果が比較でき、片順序の全時間比が1.10以下。最大は
gc_traversal 1.0657、connected_components 1.0641、logging_silent 1.0515。
参考の幾何平均は0.9283。これはまだ単独blockの暫定値で、
FT mainはTier 1、候補はmethod JIT（複数threadstate時はTier 1）である。
fastapiの依存失敗とnetworkx_k_coreの両者timeoutは未完了として保持。
順序を反転したFT第2blockを開始した。最終identity検証・区間評価は両block完了後。
GILの全suiteとlocal 8はまだ未実施。

### M51b validation history

M51b adds a local fusion for unknown-type global binding loads followed by
identity comparison and right-operand cleanup. It omits the temporary reference
owned by the watched dictionary; left-operand cleanup stays in its original
position, including finalizers. The pattern cannot cross a remaining guard exit,
escaping call or CFG edge. Tests cover is/is-not, rebinding during the function,
deletion, and finalizer-driven invalidation/GC. All 1,358 debug tests pass and
both identity tests pass -R 3:3. The initial test mistakenly deleted a global
named sentinel, which falls back to Python's builtin sentinel rather than
raising NameError. Rename the test binding to identity_marker; this was a test
expectation error, not an invalidation bug. The first old-binary test filter ran
no tests; its corrected rerun and the final-name rerun both fail on the old
binary because the fusion is absent. All logs are preserved. Native validation
and the fixed M51b/M41 development comparison are running sequentially.
M50 independently fixes saved property/module-load IPs after EXTENDED_ARG. Its
new f_lasti test fails on M48, passes on M50 with -R 3:3, and all 1,356 combined
debug tests pass. Timing was held until those checks completed.
M49 removed the unprofitable M46 native generator connection. Its 1,355 debug/
native tests and prefix test's -R 3:3 pass. All 16 M49/M41 development runs succeed
and identities match: genshi_text 0.99303 [0.99007, 0.99566], XML 1.00917
[1.00353, 1.01474], nqueens 0.98426 [0.97992, 0.98881], dulwich 0.99251,
SQLGlot 0.99176. Generator RESUME compilation, EXTENDED_ARG fixes, M41 constructor
lookup, and M48 binding loads remain. Next validate/freeze M51, measure the same
four specifications, then evaluate final GIL PGO/full-LTO and FT snapshots,
followed by complete-suite and original local-suite comparisons. The 10% goal
remains unmet until those final-profile comparisons pass.


### M52/M52b experiment history

M52b adds retry backoff when an empty native entry is rejected. M52 passed
all 1,359 debug/native tests and its -R 3:3 check, but its fixed development
comparison regressed Genshi text/XML and nqueens. All 16 runs succeeded and
identities matched; these unfavorable results are retained. The same Genshi
probe shows seven native-reachability rejections per affected generator in M52,
versus two emitted/retired executors for several such generators in M51b.
The new rejection path repeated CFG analysis without the deferred retries used
for retired partial methods. M52b applies that existing cache to rejected empty
entries. Its regression test also changes from generator to range iteration and
requires compilation to resume after specialization changes. Debug validation
precedes a new frozen native comparison. No final PGO build has started.

M52 removes native blocks unreachable after unsupported-operation exits and
rejects resume/pop/jump-only entries. Native targets are resolved before CFG
traversal; inlined return edges remain reachable and indices stay stable until
stack allocation. The pre-fix regression test fails on M51b. Its initial filter
missed RESUME flag bits; the corrected failure and both attempts are preserved.

### M53 continuation experiment history

M53e fixes entry-guard progress in the experiment with static native continuations after FOR_ITER_GEN. A hot
backedge which cannot compile its generator frame transition can install an
executor at the loop body. The generator transition stays in Tier 1, and its
ordinary yield continuation enters the compiled body. Both CFG successors are
compiled statically; no recording or side traces are introduced. Continuation
locals/stack start unknown. FOR_ITER_GEN is a planned Tier 1 boundary for this
entry. Executor retirement updates a backoff counter only for RESUME/backedge
entries; ordinary bytecode entries have no such counter. New tests cover native
body installation, changing globals, iterator/body exceptions and exhaustion.
The initial two tests fail on M52b and pass on M53b. An initial build caught
an incorrect STORE_FAST uop name; use the actual store/swap operations. The
first implementation let a short header executor suppress the body attempt;
select the static body entry first for FOR_ITER_GEN loops. M53c adds a test that
retires an executor at a normal instruction without overwriting adjacent
bytecode. M53d resets that test's reused code between refleak repetitions,
so a previous run's backoff does not suppress its warmup. All 1,361 debug tests
and all three new tests under -R 3:3 now pass. The frozen M53d native build and all 1,361 native tests pass, but Genshi
times out in its first candidate worker. Stop the comparison and retain the
incomplete state; it is not valid performance evidence. A small tuple/list
unpacking test reproduces an infinite loop: an entry guard deopts to the same
ENTER_EXECUTOR without changing its inputs. M53e makes Tier 1 execute the
original bytecode once when a method returns to its unchanged entry. It looks
up the executor after returning because callbacks can invalidate/replace it.
The new regression test times out on M53d. Both it and the actual Genshi
reproducer pass on M53e. All 1,362 debug tests and four targeted -R 3:3 tests
also pass. All 1,362 native tests and all 16 comparison runs pass; identities
match. M53e/M41: text 0.99310, XML 1.03840 [1.02682, 1.05105], nqueens
1.03720 [1.03408, 1.04062], dulwich 0.99847, SQLGlot normalize 0.99280.
This is not an accepted performance improvement. Diagnose entry guard returns
in a separate instrumented development build; do not mix those diagnostics
with timings. Final GIL/FT builds remain pending.

### M54 unpack experiment history

M54 narrows unpack/store fusion for static generator-loop continuations.
M53e diagnostic output shows Template._flatten returning to entry 60 with an
exact tuple: the fused _UNPACK_TUPLE_TO_FAST_3 guard rejects cleanup of old
non-primitive locals. Thus native entry repeatedly falls back instead of
executing the body. For continuation roots, fuse only when symbolic cleanup is
already non-escaping; otherwise retain individual stores so finalizers can run
and execution can continue natively. Existing non-continuation fusion is kept.
A new test checks the unfused native body and the sequence of locals visible to
three finalizers. Its structural assertion fails on M53e. Temporary debug-only
instrumentation has been removed by the clean development rebuild. Run the
combined suite, five targeted -R 3:3 tests, a fixed native build, and the same
four-specification comparison plus unpack_sequence to check collateral impact.
Final-profile builds have not started; the +10% main criterion remains unmet.

### M55 profitability experiment history

M55 rejects generator-loop continuations with only one useful operation.
M54's nqueens diagnostic found complete 13-uop executors whose entire useful
body was one SET_ADD or LIST_APPEND. Repeated native entry/exit for each yielded
item adds overhead while leaving that operation's C implementation unchanged.
Keep these bodies in Tier 1, with the same cached retry mechanism. This is a
structural profitability check, not a benchmark-name special case. The new
list/set test fails on M54 in both cases. All 1,364 debug tests and six targeted
-R 3:3 tests pass on M55. A frozen native build, native validation and the same
five-specification comparison are running sequentially.

M54 passed all 1,363 debug/native tests and five -R 3:3 tests. All 20 comparison
runs succeeded with matching identities. M54/M41 ratios and intervals are
recorded below. Genshi improves, while nqueens still needs the M55 correction.
After validating M55, evaluate final GIL PGO/full-LTO and FT builds, then the
complete suite and original local eight. The main +10% criterion remains unmet.
- dulwich_log: 0.99249 [0.98396, 1.00195]
- genshi_text: 0.91854 [0.91499, 0.92238]
- genshi_xml: 0.97707 [0.96794, 0.98658]
- nqueens: 1.03737 [1.03492, 1.04002]
- sqlglot_v2_normalize: 0.98688 [0.97897, 0.99423]
- unpack_sequence: 0.77525 [0.77216, 0.77864]
