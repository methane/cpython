# JIT bug-remediation plan

Updated: 2026-09-16

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
