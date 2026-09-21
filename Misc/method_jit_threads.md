# Concurrent method JIT prototype

This follow-up to M56b keeps method JIT enabled when a free-threaded
interpreter gains additional thread states. It is an experimental correctness
baseline, not a claim of production readiness or parallel speedup.

## Execution and compilation contract

Before a second thread state is published, stop the interpreter, invalidate
its existing executors, and set a permanent `jit_multithreaded` flag. The JIT
remains enabled. Single-thread startup retains the existing optimizer; after
the transition, all threads use conservative lowering, including after workers
have exited. Returning to the more aggressive mode would require proving that
objects and assumptions no longer escape to other threads.

Each executor belongs to one thread-local bytecode (TLBC) copy. Compilation,
lookup, and cache reads use that copy. The code object's executor table is
shared, but individual entries name a particular bytecode copy. The existing
256-entry limit is consequently shared across threads; exhaustion falls back
to Tier 1. Executor entry
checks the frame's TLBC index; a generator resumed by another thread must
reload that thread's bytecode through Tier 1. TLBC retirement detaches entries
before freeing bytecode. `-X tlbc=0` disables JIT.

Compilation, publication, invalidation, table resizing, and reclamation run
inside interpreter stop-the-world scopes. Scopes nest under existing GC and
instrumentation stops, including a global stop. Code-object cleanup receives
the executor registry's owning interpreter explicitly: during subinterpreter
bootstrap this may differ from the current interpreter. Native execution does
not hold a JIT-wide execution lock.

Reclamation scans stable `current_executor` pointers while the world is
stopped. Nested native calls already retain callers. An additional per-thread
hazard slot protects a zero-refcount executor whose deallocator is waiting to
acquire stop-the-world, including objects already on the pending deletion list.

## Conservative concurrent lowering

Dependency callbacks may run before a mutation is complete. Merely serializing
a callback and compilation does not prevent compilation from publishing an
assumption between that callback and the actual write. Concurrent mode
therefore bypasses the symbolic optimizer that folds mutable values through
watchers. Globals and attribute loads/stores use generic runtime operations;
ordinary calls use the generic vectorcall path. CFG dataflow is normalized to
the generic bytecodes too, so it cannot infer the return type of an obsolete
call specialization.

Keyword/starred call transitions and closure-cell operations currently fall
back to Tier 1. Raw list-pair and enumerate-scan fusions are disabled in
concurrent mode. Guarded scalar arithmetic, method CFGs, ordinary control flow,
and FT-aware container operations remain available. This deliberately trades
some single-worker throughput after the transition for a smaller concurrency
contract. It does not add path recording or side traces.

## Validation and remaining work

Validation results and exact local commands are recorded in `plan.md` and
`jit-artifacts/regressions-20260919/mt*-*.log`. New tests cover distinct
executors for shared code across four live threads, native activity with the
GIL disabled, concurrent invalidation/collection, shared mutations, monitoring,
thread/index reuse, generator migration, and the TLBC-disabled configuration.

The first implementation exposed two test/setup issues (single-thread opcode
expectations after a thread-mode transition, and generator warmup below its
actual threshold) and an interpreter-ownership deadlock during subinterpreter
bootstrap. The tests and ownership handling were corrected; final validation
is recorded separately rather than treating those initial attempts as passes.

Final validation on Linux x86-64 with GCC 13.3 and LLVM 21:

| Check | Result |
| --- | --- |
| FT debug/O3, 13 runtime and concurrency modules | 1,065 tests passed; 50 skipped |
| GIL O3, optimizer/monitoring/generators/threading | 981 tests passed; 9 skipped |
| Final FT binary, optimizer plus eight new tests | 586 tests passed; 44 skipped |
| Final GIL binary, optimizer suite | 578 tests passed; 5 skipped |
| Generated cases | 84 tests passed |
| Eight concurrency tests, 20 fresh processes | 160 passes; no skips or timeouts |

Neither build uses PGO or LTO. Final source/binary identities are in
`jit-artifacts/regressions-20260919/mt5-final-identity.json`. The earlier wider
run precedes the final foreign-executor lookup and diagnostic fixes; those
fixes were checked with the final suites and repeated concurrency tests.
The separate `test_sys` attempt encountered 11 sandbox permission errors and
one tracing-timing assertion; the latter also fails on the frozen M56b binary.

Before expanding optimization coverage, give dependency publication and each
shared-object fast path a complete concurrency contract. Before evaluating
performance, measure compilation pause time, executor memory per thread,
steady-state throughput, and scaling with matched builds and workloads. A
TSAN/ASAN campaign and broader architectures remain necessary; the current
checks do not establish absence of races. The historical M56b performance
numbers do not measure this implementation.

## Post-commit GIL performance check

Commit `e3fb6e8edee` was rebuilt with GIL, PGO, and full LTO and compared with
frozen main `d95f29589e0`. Across 122 completed pyperformance results, the
candidate/main elapsed-time geometric mean is 0.9772 (95% worker-bootstrap
interval 0.9753–0.9791). The largest regression is sympy_expand at 1.1448;
FastAPI dependencies and NetworkX k-core timeouts remain incomplete. All
samples and failures are retained in the [measurement report](../benchmarks/method_jit_mt6_results.md).
This compares the entire branches on fixed binaries. It does not measure
free-threaded throughput, scaling, or the causal cost of concurrent JIT support.
