# JIT bug-remediation plan

Updated: 2026-09-17

Current goal: completed. All eight standalone workloads, including SQLAlchemy,
meet candidate/main <=0.90 with each 95% interval upper bound below 0.90 in
the prespecified 12-block fixed-binary/CPU confirmation. See
[the final report](benchmarks/jit_comparison.md) and the final entries below.
The implementation, regression tests, final report and confirmation evidence
are included in this local changeset. Earlier sections retain the chronological
history of completed tasks and experiments.

## Scope

Fix and verify every actionable item in `bugs_report.md` on
`codex/method-jit`, starting from `d95f29589e03603aa13d8ca9d4f817dce77d357c`.
Keep all work local: no GitHub posts, pushes, or pull-request changes.  Builds
use the installed LLVM 21 and omit PGO and LTO.

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
