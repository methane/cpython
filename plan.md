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
