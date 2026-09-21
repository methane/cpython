# Comparing tracing JIT optimizations with the method JIT

September 20, 2026. This report compares **`codex/tracing-jit` with the current
method JIT**. Despite the filename, tracing garbage collection is outside its
scope. The analysis uses existing implementations and saved measurements; no
new performance measurements were run.

## 1. Assessment

Across broad benchmark suites, both GIL configurations have demonstrated about
a 3% reduction in runtime relative to their respective main baselines. The
optimized tracing JIT achieved **0.97238** across 117 results; the method JIT
achieved **0.97051** across 122. Different main revisions, PGO/LTO settings,
benchmark sets, and measurement protocols prevent interpreting this difference
as evidence that the method JIT is faster. The method experiment's main baseline
uses the ordinary upstream tracing JIT. **It is not a direct comparison against
the optimized `codex/tracing-jit` branch.**

The tracing work was substantial, too. Additions and deletions in handwritten
runtime code total approximately 11,700 lines for tracing and 12,800 for the
method implementation. The tracing branch adds many restricted transformations
to the existing compiler. The method branch rebuilds compilation entry points,
control-flow analysis, calls, and execution-state management. Both required
substantial implementation and validation. There are no person-hour records,
and line counts cannot be converted into development time.

The evidence supports three conclusions:

- **The tracing branch has stronger demonstrated gains on selected Python
  computations.** Spectral Norm, Hexiom, and Go benefit substantially, with
  smaller gains outside the targeted workloads. These transformations match
  guarded code shapes rather than benchmark names, but their applicability is
  narrow.
- **The method branch has invested in infrastructure for more general
  optimization.** It handles both branch successors, merges, on-stack replacement
  (OSR), and general Python calls. It has not demonstrated a 20% reduction across
  the broad GIL suite or replaced every effective transformation from the
  earlier tracing work.
- **The method branch has made progress on free-threaded (FT) execution, but
  concurrent JIT execution remains unfinished.** It reduced runtime by 7.29%
  across 121 results relative to the FT interpreter, while disabling the JIT
  when a second thread state is created. The tracing branch explicitly excludes
  FT from its added region optimizations and has no corresponding performance
  results. Both still face the work required for a truly concurrent JIT.

## 2. Main changes from main

### Optimized tracing JIT

The inspected ref is `codex/tracing-jit` at
`26c62af79da3a0587e068692d35ae025ed4b9cc9`. Its merge base with main is
`a60343ed17785ebbcd43de9080cadd8e2541db6f`. The principal records are that
branch's `Tools/jit/optimization_report.md`, `Tools/jit/regions.md`, and
sections 21–23 of `plan.md`.

The implementation retains trace recording, the symbolic optimizer, side exits,
the stack cache, and copy-and-patch, adding the following:

| Change | Purpose and implementation obligations |
|---|---|
| Checked i64 and bounded integer regions | Eliminate intermediate PyLong values across arithmetic and comparisons. Validate overflow, arbitrary-precision fallback, borrowed-reference lifetimes, and original exception locations. |
| Float fusion and range reduction | Reduce intermediate representations and repeated boxing/unboxing. Establish rounding order, NaN behavior, exception flags, alias safety, and fallback separately. |
| `len` consumers, string methods, tuple/list comparisons, range/enumerate | Fuse calls with the operations consuming their results. Preserve exact-type checks, mutation semantics, and iterator exhaustion. |
| Replacements for selected call and loop shapes | Handle attribute-returning leaves, attribute-list searches and removals, generator aggregation, float dot products, and Go's recursive root lookup. Match the callee's full shape and guard descriptors, defaults, and instance overrides. |
| Global dependencies and executor lifecycle | Distinguish dictionary identity from version and track dependencies by name to avoid unnecessary invalidations. Correct short-loop recording and executor lifetime behavior. |
| Generation and build infrastructure | Correct uop ID ordering, stencil inputs, and LLVM 21 support. |

Performance measurements enabled `PYTHON_JIT=1`, the resident policy, and all
six experimental options. The added regions are disabled by default, so these
results do not describe gains under default settings. Principal implementation
files include `Python/optimizer_analysis.c`, `Python/bytecodes.c`,
`Python/optimizer.c`, and `Python/optimizer_*region*.h`.

### Current method JIT

The main baseline is `d95f29589e03603aa13d8ca9d4f817dce77d357c`.
At measurement time, HEAD was `14defe7e06ef37956989e46c74710293d33df41e`;
the measured implementation also included the then-uncommitted M56b changes.
This report and that implementation are now being preserved together in a local
checkpoint. The measured patch hash below identifies the original snapshot. See the
[design documentation](../InternalDocs/jit.md) and
[final results](../benchmarks/method_only_m56b_results.md).

| Change | Purpose and implementation obligations |
|---|---|
| Static method frontend | Remove recording dispatch, recorded values, and side-trace generation. Build basic blocks, stack depths, and a control-flow graph (CFG) from bytecode, translating both conditional successors. |
| Value analysis across the CFG | At merges, retain only type, constant, and ownership facts valid on every incoming path. Discard facts that may be invalidated by reentry into Python. |
| OSR and partial compilation | Enter at hot `RESUME` instructions, backedges, and generator loop bodies. Treat live entry values as unknown, return unsupported execution to Tier 1, and suppress unproductive entries and recompilation. |
| Python call optimization | Support bounded inlining with real frames, calls into callee executors, constructors, and `__getitem__`. Preserve recursion, defaults, function replacement, exceptions, and monitoring. |
| Shared arithmetic, reference, and attribute optimizations | Use int/float regions, fewer guards and reference operations, type/function versions, named global dependencies, module attributes, and `isinstance` with default metaclass behavior. |
| Generator boundaries | Support ordinary generator resume/yield and consumer bodies. Direct native generator connections were removed after unfavorable measurements. Coroutines, async generators, and other unsupported cases retain Tier 1 paths. |
| Restricted FT support | Implement FT ownership and constant restrictions, invalidate executors before publishing another thread state, and stop JIT execution. Record actual GIL/JIT state in benchmark workers. |
| Changes outside the JIT | Include C codec and regex improvements and GIL handoff-related fixes. Overall gains cannot be attributed entirely to the method frontend. |

The uop IR, symbolic optimizer, stack cache, and copy-and-patch backend are
reused. Removing tracing does not remove the need for guards, deoptimization,
dependencies, or native-code lifetime management. Not every restricted range
or call transformation from the earlier tracing experiments has been ported.

## 3. Performance across broad benchmark suites

Each time ratio is candidate runtime divided by **its own fixed main baseline**.
Lower is better.

| Comparison | Results in primary aggregate | Geometric mean [95% interval] | Runtime reduction | Faster point estimates |
|---|---:|---:|---:|---:|
| Optimized tracing, GIL, no PGO/LTO | 117 | 0.97238 [0.97100, 0.97375] | 2.76% | 76 / 117 |
| Method, GIL, PGO/full-LTO | 122 | 0.97051 [0.96825, 0.97310] | 2.95% | 67 / 122 |
| Method, FT, no PGO/LTO | 121 | 0.92705 [0.92648, 0.92763] | 7.29% | 99 / 121 |

For tracing, pyperf's default significance test reports 51 improvements,
33 regressions, and 33 nonsignificant differences. For the method JIT, the
worker-bootstrap interval has an upper endpoint below 1 for 57 GIL results and
96 FT results. **These use different statistical tests; differences in their
counts do not establish a difference in the breadth of significant gains.**
All intervals describe execution variability for fixed builds. They do not
include independent rebuilds or reproducibility on other CPUs.

### Conditions and missing results

Both experiments used the same Intel Core i5-12450H, CPU 2 for ordinary single
workers, GCC 13.3, and LLVM 21. They were nevertheless separate experiments.

- The tracing comparison ran on September 15, 2026, with GIL, O3, and no
  PGO/LTO. Of 96 requested specifications, 93 produced 119 results. Mismatched
  loop counts excluded `deepcopy_memo` and `deepcopy_reduce` from the primary
  117-result aggregate. Including all 119 gives a sensitivity result of
  0.97232. FastAPI was excluded before execution. A websockets port conflict,
  Dask/cloudpickle incompatibility, and Genshi incompatibility caused missing
  results.
- Tracing groups A and B contained **different sets of specifications**.
  Main ran first in A, and the candidate ran first in B. Each result had six
  measured processes per side, but individual results were not measured in
  both orders. The bootstrap used 20,000 resamples. The group geometric means,
  0.96106 and 0.98034, must not be interpreted as an order effect measured on
  the same workloads.
- The method comparison ran on September 20, 2026. Each specification used two
  blocks, with main first and candidate first, three workers per side per block,
  five warmups, five values, and independent calibration. The bootstrap used
  4,000 resamples. FastAPI dependencies and NetworkX k-core's 15-second worker
  timeout caused missing results in both configurations. FT additionally
  excluded an incomplete Dask pair after main received SIGSEGV. Failed runs
  were retained.
- Only the method GIL comparison used PGO/full-LTO, so differences from the
  earlier tracing ratios include build conditions. The method FT baseline
  creates no executors. Its 7.29% improvement is **relative to the FT
  interpreter**, not a tracing JIT or a measure of parallel scaling.
- The method experiment verified C `_decimal` in all four builds. The earlier
  tracing report records a stage without `_decimal`, and its broad comparison
  lacks the current backend verification. Matching result names alone cannot
  guarantee identical execution paths for Decimal and similar workloads.

### Matching names and concentration of gains

There are 116 names shared by the old 117-result aggregate and both method
configurations; `k_core` is missing from the latter. Restricting each analysis
to those names gives **0.97349** for tracing, **0.96724** for method GIL, and
**0.92660** for method FT. This reduces differences in the named workload set;
it does not establish identical baselines, inputs, dependencies, or builds.
Dividing these ratios would not yield a measured method/tracing speed ratio.

The table below separates six results directly targeted during earlier
development (`bpe_tokeniser`, `deltablue`, `go`, `hexiom`, `raytrace`, and
`spectral_norm`) from the rest. **This is a post-hoc descriptive analysis.
The remaining results are not an unexplored holdout set.**

| Subset of shared names | Count | Tracing / old main | Method GIL / new main | Method FT / FT main |
|---|---:|---:|---:|---:|
| Six directly targeted results | 6 | 0.70277 | 0.82501 | 0.75167 |
| Remaining results | 110 | 0.99095 | 0.97567 | 0.93723 |

Tracing reduced runtime by approximately 29.7% on the six targets and 0.9% on
the other 110. Benefits extend beyond the targets, but their contribution to
the overall mean is concentrated. The method results show gains outside those
targets as well, but C changes and build conditions prevent attributing that
spread to the method frontend. In particular, excluding `bench_mp_pool` and
`bench_thread_pool` from the full method GIL suite gives a sensitivity result
of 0.97948. Its primary 2.95% improvement cannot all be credited to Python code
generation.

The following entries also use each experiment's own main baseline. Differences
between columns are not directly measured ratios between the candidates.

| Result | Tracing GIL | Method GIL | Method FT |
|---|---:|---:|---:|
| `bpe_tokeniser` | 0.8013 | 0.8509 | 0.8026 |
| `deltablue` | 0.9462 | 1.0051 | 0.8793 |
| `go` | 0.7776 | 0.8660 | 0.8145 |
| `hexiom` | 0.5794 | 0.7771 | 0.8556 |
| `raytrace` | 0.7296 | 0.9712 | 0.9149 |
| `spectral_norm` | 0.4835 | 0.5641 | 0.4009 |
| `richards` | 1.0054 | 0.9082 | 0.7713 |
| `richards_super` | 1.0136 | 0.9979 | 0.7989 |
| `django_template` | 0.9169 | 0.9668 | 0.9454 |
| `chameleon` | 0.9444 | 0.9603 | 0.9085 |
| `unpickle_pure_python` | 0.9174 | 0.9888 | 0.8106 |
| `sqlglot_v2_normalize` | 1.0074 | 1.0628 | 0.9723 |
| `sqlalchemy_imperative` | 0.8826 | 1.0482 | 0.8701 |
| `base16_large` | 1.1240 | 0.8236 | 0.8277 |
| `base32_small` | 1.0539 | 1.1011 | 0.9405 |
| `regex_compile` | 1.0109 | 1.0073 | 0.8433 |
| `shortest_path` | 1.0179 | 1.1492 | 0.9812 |
| `sympy_expand` | 0.9665 | 1.1480 | 0.8996 |
| `bench_mp_pool` | 1.0073 | 0.3680 | 1.0022 |

Three method GIL regressions exceed 10%. Candidate processes for
`shortest_path` fall into two speed groups, with the cause unresolved. The
earlier tracing Base16 difference also reproduced with JIT disabled and was
sensitive to build/layout and the release of large temporary bytes objects.
Neither observation isolates the effect of frontend design.

The earlier standalone six-script ratio of 0.37909 must be kept separate from
the broad pyperformance ratio of 0.97238. Spectral Norm was 0.01866 in that
standalone aggregate, while the other five scripts averaged 0.69232
geometrically. The pyperformance Spectral Norm ratio was 0.4835: the workload
and applicable optimization differ despite the shared name. The current local
eight-script ratios, GIL 0.82743 and FT 0.74136, are likewise separate metrics.

## 4. Implementation, maintenance, and validation effort

The same classification rules were applied to `git diff --numstat`. Tracing
was measured from its merge base above to `26c62af79da`; method was measured
from its main baseline above to the current working tree. These figures
describe **the size of the resulting changes**, excluding time spent on
rejected experiments, diagnosis, rebuilding, and validation.

| Tracked-file category | Tracing: files / added / deleted | Method: files / added / deleted |
|---|---:|---:|
| Handwritten runtime: Include, Python, Objects, Modules; excluding tests and generated files | 27 / 11,549 / 122 | 43 / 9,854 / 2,931 |
| Tests: Lib/test and Modules/_test*; excluding generated files | 7 / 8,056 / 1 | 10 / 9,959 / 1,057 |
| Generated files, as defined below | 15 / 34,354 / 13,352 | 13 / 24,736 / 13,530 |

Generated files comprise `*_generated.h`, opcode/uop IDs and metadata,
`Lib/_opcode_metadata.py`,
`Python/{executor_cases,generated_cases,optimizer_cases,record_functions}.c.h`,
`Python/opcode_targets.h`,
`Modules/_testinternalcapi/test_{cases.c,targets}.h`, `configure`, and
`pyconfig.h.in`. Documentation, logs, JSON, benchmarks, build/generation tools,
and untracked files are excluded from the handwritten runtime counts. Uop
replication can greatly expand generated output, so the total diff size is not
a measure of handwritten implementation volume.

Tracing adds many passes and uops that recognize and replace individual code
shapes. Even a small transformation needs separate validation of types,
reference ownership, aliases, rounding, changed defaults, monitoring, and
resumption after side effects. More shapes require more matchers and fallback
paths. Effective transformations can be enabled locally, but expanding their
scope requires additional correctness arguments.

The method implementation incurred substantial initial costs for its frontend,
weakening facts at merges, connecting callees, preserving real frames and
exception state, handling instruction pointers for wide jumps, generator
suspension, and rejecting unproductive executors. Removing tracing reduces one
maintenance burden while introducing a CFG compiler to maintain. Generality of
source structure and benefits across real programs require separate evidence.

Validation records also differ. At tracing's final Go stage, both debug and
native builds ran 229 region tests, plus Tier 3 and optimizer suites. Earlier
float validation included 576 cases across four rounding modes. The older
report also records mismatched opcode-shape expectations with all options
enabled and an unresolved pre-existing reference-leak check; it does not claim
all tests passed in all configurations.

For method M56b, both final configurations successfully ran 578 optimizer
tests, 788 related tests, 1,154 C-related tests, and 97 opcache tests with JIT
disabled. Debug checks, new reference-leak checks, and 84 generator tests also
passed. Counts include configuration-specific skips and overlapping coverage;
adding them does not produce a comparative measure of quality or productivity.

## 5. Additional work for free-threading

### Implemented scope

Tracing's `Python/optimizer_regions.h:region_enabled()` requires
`!defined(Py_GIL_DISABLED)`. Transformations such as Go's root lookup also
explicitly exclude FT. There is therefore no evidence that its successful GIL
optimizations were validated under FT, and no basis for claiming inexpensive
FT support. That work was outside the implementation's scope.

The method branch has executed native code in FT builds and validated types,
ownership, invalidation, and fallback. However,
`Python/pystate.c:add_threadstate()` stops the JIT and invalidates executors
before publishing a second thread state. JIT execution is not automatically
restored when that thread exits. Optimizations such as mutable global handling
also have stricter limits than in GIL builds. This implements single-thread
JIT execution with the FT ABI and a safe transition to concurrent Tier 1.

### Remaining work for concurrent JIT execution

The following tasks are inferred from the source. They are not completed work
or estimates of person-hours or completion dates.

| Concern | Porting the tracing optimizations to FT | Making the method JIT concurrent |
|---|---|---|
| Guards and mutable-object access | Another thread can mutate lists, dictionaries, attributes, or recursive chains after a guard. Direct traversal, writes, and borrowing that rely on the GIL need redesign. | CFG facts do not prevent runtime races. Loads, guards, reference acquisition, and facts across callbacks must follow FT access contracts. |
| Compilation inputs | Manage synchronization and lifetimes of recorded values, specialization caches, and tracer state. | Recorded values are absent, reducing that state, but bytecode, caches, and type/function versions still need consistent reads. |
| Dependencies and invalidation | Global/type watchers race with execution and updates to traces and side-exit graphs. | Watchers race with executor publication, entry patching, and invalidation. Method compilation alone does not resolve these races. |
| Native-code and constant lifetimes | Protect executing traces and their targets against invalidation and reclamation by other threads. | Protect executing methods, inlined-callee dependencies, constants, and return targets; define safe reclamation points. |
| Thread-local bytecode (TLBC) and ownership | Validate the mapping between thread-local bytecode and executors, and reference acquisition for shared objects. | Define OSR/entry patching against thread-local bytecode and revalidate paths currently protected by the single-thread restriction. |
| Validation | Add concurrent mutation, class/default replacement, finalizer reentry, thread exit, and invalidation races. | Cover the same races plus concurrent compilation, publication, OSR, and returns from inlined calls. |

Removing recording and side-trace management may reduce the design surface for
concurrent method compilation. Both approaches still face borrowed references,
mutable containers, watchers, and executing-code lifetimes. **A method frontend
is not itself proof of thread safety.** The current 7.29% gain cannot predict
multithreaded performance after adding the necessary concurrency mechanisms.

## 6. Return on effort and the next investment

Current broad GIL performance alone does not establish that the large method
migration has paid for itself. Both experiments show gains of roughly 3% under
different conditions, and some targets retain larger gains in the tracing
experiment. Nor does the evidence justify discarding all tracing work as
overfitting. Integer box elimination, fusion of builtins with their consumers,
and finer dependencies are reusable components that can be separated from
transformations tied to narrow code shapes and ported to the method compiler.

The next useful investment is to use the existing method frontend and port
proven representation, call, and container optimizations into shared passes.
Measure whether benefits accumulate through the general CFG infrastructure and
reusable transformations, including workloads outside the immediate targets.
This helps distinguish broader progress from simply adding more matchers for
individual benchmarks. Evaluate improvements to C loops, allocation, I/O, and
startup separately from JIT code generation.

A direct comparison of the approaches requires **upstream tracing, optimized
tracing, and method configurations built from the same main revision, with
matching compiler, PGO/LTO, dependencies, and C backends**. Align shared runtime
fixes, reverse measurement order for each workload, and report targets, other
results, and failures separately. For FT, distinguish single-thread execution
with JIT from multithreaded execution with JIT disabled. Measure concurrent JIT
performance after implementing it. No such new builds or measurements were
undertaken for this report.

### Preparation before external design review

The prototype is suitable for exploratory review now. Two practical
improvements would make that review more useful. These are proposed follow-up
tasks; the portable reproduction workflow and separated patch series have not
yet been prepared.

#### 1. Make reproduction possible from a fresh checkout

The current benchmark runner depends on local build directories and cached
wheels. Saved measurements allow inspection of the results, but do not provide
a complete setup procedure for another developer.

Provide a short, executable workflow that:

- Identifies the source revisions, compiler and LLVM requirements, native
  dependencies, and Python benchmark dependencies.
- Builds both main and the candidate in fresh directories, with explicit GIL,
  JIT, frame-pointer, PGO, and LTO settings. Use builds without PGO/LTO for the
  initial review cycle, and document the optimized measurement configuration
  separately.
- Runs the relevant correctness tests and checks the actual worker runtime,
  including native JIT execution, the FT single-thread restriction, and the
  C `_decimal` backend.
- Runs a small representative comparison with fixed workloads and recorded
  execution order, then explains how to launch the broader suite and inspect
  failures, raw samples, and build identities.

Validate those instructions without the author's existing build trees or wheel
cache. Clearly distinguish newly reproduced measurements from the historical
M56b results; a new build is not the original measured binary.

#### 2. Separate the changes into reviewable units

The checkpoint combines frontend replacement, optimization work, C runtime
changes, tests, generated code, and measurement records. Provide a dependency
map and a reading order so reviewers can assess each design decision without
first understanding the entire diff.

A useful decomposition is:

| Review unit | Main question |
|---|---|
| Shared correctness and runtime fixes | Which changes are independently useful to main, regardless of frontend choice? |
| Minimal method frontend and removal of recording | Are CFG construction, merge rules, OSR, Tier 1 fallback, and executor lifecycle understandable and correct? |
| Call, arithmetic, attribute, and generator optimizations | What additional assumptions does each transformation require, and what measured benefit does it provide? |
| FT execution restrictions and invalidation | What safety contract is implemented today, and what remains necessary for concurrent JIT execution? |
| Benchmark infrastructure and evidence | Can the reported effects be reproduced, and can frontend effects be distinguished from shared runtime changes? |

Keep the relevant regression tests with each implementation unit and identify
its generated outputs separately from handwritten source. State dependencies
and validation results for each unit; do not imply that arbitrary subsets of
the current checkpoint are independently buildable. A review branch or patch
series can be prepared without rewriting the saved experimental history.

Neither preparation task requires eliminating every remaining performance
regression before requesting feedback on the architecture.

## 7. Evidence and verification

- Tracing design and history:
  `git show 26c62af79da:Tools/jit/optimization_report.md`,
  `git show 26c62af79da:Tools/jit/regions.md`, and
  `git show 26c62af79da:plan.md`. Keep earlier checkpoint measurements distinct
  from the later broad-suite results.
- Tracing raw data and analysis:
  [summary.md](../jit-artifacts/pyperformance-rerun-current/summary.md),
  [analysis.json](../jit-artifacts/pyperformance-rerun-current/analysis.json),
  [ratios.csv](../jit-artifacts/pyperformance-rerun-current/ratios.csv), and
  `a-{main,candidate}.json` / `b-{main,candidate}.json` in the same directory.
  The four raw JSON hashes were checked against the saved manifest. Ratios
  for all 119 rows were recomputed from six process means per side, confirming
  the 117-result geometric mean of 0.9723832438.
- Tracing measured executable SHA-256 values:
  main `8fb6c5b87dec8e272c1acfad0197dc086bcd3e0c93912d949d43d5c4d9603407`;
  candidate `ebb86d4a70b9dda5c4f70d4d49196cc5a87986c41ced14951f73dd0eef2fb457`.
- Method results, executable hashes, and correctness validation:
  [M56b results](../benchmarks/method_only_m56b_results.md),
  [FT analysis](../jit-artifacts/method-only-m56b-full/ft/worker-analysis.json),
  and [GIL analysis](../jit-artifacts/method-only-m56b-full/gil-pgo-lto/worker-analysis.json).
  The measured patch is
  `jit-artifacts/regressions-20260919/m56b-method-only.patch`, with SHA-256
  `6c30ed6fec1151f4cd2354665dc95517779162b05fd0a31f496910af58fad573`.
  Subsequent cleanup in two generator files changed neither generated output
  nor compiled runtime sources.
- The shared-name set is the intersection of the old CSV rows with
  `loop_matched=True` and the `rows` in both method analyses. Aggregation uses
  `exp(mean(log(candidate/main)))`. No other results were discarded after
  inspecting their performance. The report's numbers, links, and diff were
  checked without additional timing runs or runtime changes.
