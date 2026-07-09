# JIT performance roadmap

This note summarizes what would be required to improve Python execution speed
when the JIT is enabled. It is intentionally focused on end-to-end Python speed,
not just JIT compilation latency or isolated generated-code peepholes.

## Current pipeline and why local codegen fixes are not enough

The current JIT is a tracing JIT layered on the adaptive interpreter. Execution
starts in tier 1, hot `JUMP_BACKWARD`/`RESUME` instructions trigger trace
recording, the recorder translates bytecodes into micro-ops, the uop optimizer
runs, and the full JIT copy-and-patches stencil code for the optimized executor.
See [The JIT](jit.md) for the detailed control flow.

Small native-code improvements can help individual uops, but large Python-level
speedups need changes that increase the amount of time spent in optimized,
stable tier-2 traces and reduce the amount of Python object work that remains
inside those traces. The main limiting factors are:

* **Warmup and trace selection.** Default loop and resume thresholds are high
  (`JUMP_BACKWARD_INITIAL_VALUE`, `RESUME_INITIAL_VALUE`) to avoid tracing before
  specialization has stabilized. This protects steady-state quality, but it also
  means short-running code sees little or no JIT benefit.
* **Trace coverage.** The tracer records linear traces and side exits. A Python
  workload with frequent side exits, polymorphism, exceptions, generator state,
  or megamorphic attribute access spends less time in hot compiled traces.
* **Optimizer scope.** The uop optimizer has symbolic analysis and removes some
  unneeded uops, but it does not yet perform the kind of broad scalar
  replacement, allocation sinking, loop-invariant hoisting, or aggressive
  inlining needed for large speedups on object-heavy Python code.
* **Runtime helper boundaries.** Many uops still call C helpers or perform
  generic object operations. Native dispatch is faster than interpreter dispatch,
  but it is not enough if the trace still performs the same refcount, allocation,
  dict, descriptor, and call machinery as tier 1.
* **Invalidation and deoptimization costs.** Executors depend on recorded values
  and version checks. Broadening optimization requires equally strong guard,
  dependency, and invalidation machinery so optimized traces stay correct without
  deopting too often.

## Changes needed for large end-to-end speedups

### 1. Measure coverage before optimizing codegen

A full `--enable-experimental-jit` build should be benchmarked with `pyperformance`
and pystats enabled. For every benchmark, track at least:

* percentage of executed bytecodes/uops covered by tier-2 executors;
* traces created, traces executed, side exits, deopts, and invalidations;
* average trace run length and top exit reasons;
* JIT memory/code size and time spent compiling;
* speed with `PYTHON_JIT=0` versus `PYTHON_JIT=1`.

This should drive decisions about thresholds, trace length, side-exit linking,
and optimizer work. A generated-code peephole should be considered secondary if
coverage or deopt rate is the dominant loss.

### 2. Improve trace formation and side-exit linking

For many real programs, the important question is not whether a single trace is
fast, but whether execution remains in tier 2 after common branches. The next
major changes should be:

* use pystats to identify bytecodes that stop tracing or force cold exits most
  often;
* raise or reshape `FITNESS_INITIAL`/trace-cost accounting only after measuring
  code-size and compile-time tradeoffs;
* compile common side exits into linked traces sooner when they are stable;
* avoid recording traces on atypical loop iterations, such as exhaustion or
  error paths;
* preserve tier-1 specialization quality before tracing, because the recorder
  relies on specialized bytecodes and cache state.

### 3. Add optimizer passes that remove Python object work

Large speedups require fewer Python object operations inside hot loops. The uop
optimizer should grow passes such as:

* compact-int and exact-float arithmetic chains that keep unboxed values across
  multiple uops;
* allocation sinking for temporary tuples/lists/ranges when escape analysis can
  prove they do not escape;
* loop-invariant guard and load hoisting for stable globals, builtins, types,
  and descriptor lookups;
* redundant reference-count operation elimination where ownership is proven;
* stronger call inlining for monomorphic Python functions, with robust guards on
  code object, defaults, closure cells, globals, and callable versioning.

These are semantic optimizer changes. They should be developed with targeted
trace dumps plus end-to-end benchmarks, not as isolated stencil rewrites.

### 4. Specialize high-impact runtime operations in tier 2

After coverage data identifies hot uops and helper calls, add JIT-friendly fast
paths for operations that dominate Python workloads:

* exact `int`, `float`, `str`, `list`, `tuple`, and `dict` operations;
* monomorphic attribute loads and method calls;
* `FOR_ITER` over `range`, `list`, `tuple`, and dict views;
* common Python-to-Python calls, including vectorcall setup;
* common C builtin calls where arguments are exact and stable.

The goal is to keep hot traces in straight-line native code with guards, not to
bounce through generic C APIs for every operation.

### 5. Make generated code quality a measured follow-up

Once coverage and semantic optimization are improved, generated-code work should
focus on the remaining hottest stencils:

* remove unnecessary GOT/data loads for patched operands;
* keep hot paths fall-through and move deopt paths cold;
* reduce tail-call chain overhead between adjacent uops where safe;
* add architecture-specific immediate and branch relaxations only when they show
  up in disassembly and benchmarks;
* track code size so better local code does not reduce instruction-cache
  behavior or trace residency.

## Suggested milestone plan

1. **Measurement milestone:** add a reproducible full-JIT `pyperformance` job
   that emits coverage, deopt, side-exit, trace-length, and memory stats.
2. **Coverage milestone:** fix the top trace abort and side-exit causes from
   the measurement data.
3. **Semantic optimizer milestone:** implement one high-value unboxing or
   allocation-sinking optimization and prove it on multiple benchmarks.
4. **Call/attribute milestone:** inline monomorphic Python calls and hoist stable
   attribute/global guards in tier 2.
5. **Codegen milestone:** apply architecture peepholes to the remaining hottest
   stencils after the semantic wins are visible.

The expected large wins come from milestones 2--4. Codegen-only work is still
useful, but it is unlikely to produce a broad, substantial improvement by itself.
