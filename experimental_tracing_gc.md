# Experimental tracing GC: implementation and findings

Date: 2026-09-07. Implementation checkpoint: `1b990379c85` on
`experimental-tracing-gc`. [日本語版](experimental_tracing_gc.ja.md).

This report is for students familiar with pointers, graphs, threads, and basic
computer architecture. It describes a research prototype, not a production-ready
replacement for CPython's memory management. Compatibility changes were allowed
to explore performance potential. Measurements below belong to explicitly named
development stages; they are **not a complete benchmark of the final commit**.

## 1. What question does this experiment answer?

Can Python run faster if it stops updating reference counts on ordinary object
references, reclaims garbage by tracing, and avoids allocating objects for common
numbers?

The evidence says **yes for some workloads, but not yet in general**:

- Removing shared reference-count updates greatly helped a deliberately
  contended, four-thread read benchmark.
- Encoding floats and some integers directly in references eliminated most
  numerical temporary allocations. Some numerical workloads beat the reference
  counting comparators, and large numeric lists used substantially less memory.
- Reducing repeated collector scans and retiring empty allocator pages produced
  smaller but measurable improvements.
- A demanding parallel container-allocation workload still took about 7.9 times
  the reference-counted FT time, with about five times its peak resident memory,
  at a late development stage. There are also known test failures and numerical
  regressions. The general performance goal has not been reached.

These are results for this implementation and machine, not limits on what tracing
GC can achieve in other runtimes.

## 2. Background: where does the work go?

In reference counting (RC), acquiring or releasing an owned reference updates an
object's count. Reaching zero normally destroys the object immediately. A separate
cycle collector handles unreachable cycles, such as two lists referencing each
other. Free-threaded CPython uses optimized ownership-aware counting, not an
atomic operation for every reference, but shared-reference traffic can still be
expensive.

In tracing GC, the runtime starts from **roots**—references in active frames,
threads, and runtime state—and follows edges between objects. Unreachable objects
can then be reclaimed. A **non-moving** collector leaves surviving objects at their
existing addresses. This simplifies interaction with C pointers, but does not
compact the heap.

Trading RC for tracing moves work; it does not make memory management free:

| Source of cost | What the prototype changes |
| --- | --- |
| Reference operations during application execution | Avoid numeric count updates; retain alias/synchronization checks where needed |
| Object allocation | Use immediate numeric values and selected boxed-float reuse |
| Finding live objects | Trace roots, build allocation maps, and skip provably unchanged storage |
| Reclamation | Reduce repeated passes and reference-release loops; use safe allocator paths |
| Retained memory | Improve object lifetime handling and empty-page reclamation |

Application execution is often called the **mutator**, because it changes the
object graph. A faster collector can coexist with a slower mutator. Likewise,
fewer collections do not necessarily mean less total time or memory.

## 3. What has been implemented?

### 3.1 A tracing-based object lifetime

`--with-experimental-gc=tracing` selects an experimental collector built on the
free-threaded runtime and mimalloc, the allocator. Ordinary decrements no longer
destroy objects once tracing is active. Reference acquisition can still record a
sticky alias bit: optimizations must not mistake a shared object for a uniquely
owned one. Bootstrap handling and immortal objects remain special cases.

Heap enumeration and marking stop application threads. Python frame references
are visited precisely: the collector knows which fields contain references.
Native C stacks and saved registers are scanned **conservatively**: a machine word
that looks like a valid managed address may be treated as a reference. Allocation
maps reject addresses in free slots. This supports many existing C execution
paths, but stale or coincidental pointer-shaped words can keep garbage alive.

Lists, tuples, dictionaries, sets, functions, cells, and selected metadata have
precise traversal paths. Auxiliary buffers, such as list item arrays, are accounted
for separately from object headers. Audited regular-expression objects use their
traversal contract rather than treating numeric instructions as possible pointers.
Unaudited extension objects can still require conservative body scans.

Reclamation now covers tracked containers, newly created functions and code,
pure-Python modules, supported heap types and metaclasses, and exact scalar leaves
such as boxed integers, floats, strings, bytes, and complex numbers. Reachable
functions retain their globals even when the module object itself dies. Static
type metadata stays rooted without treating weak subclass links as strong roots.

This is deliberately incomplete: bootstrap objects, native modules with state or
callbacks, and types whose instances lack cyclic-GC support are pinned. Other
unsupported non-GC objects are not generally reclaimed. Extensions hiding pointers
outside managed heaps without exposing them through `tp_traverse` are unsupported.

Finalizers, weakrefs, resurrection, and type destruction require more than a
simple mark-and-free loop. Type headers must outlive instance deallocators that
still use them; resurrection requires fresh reachability information. Those
ordering rules received specific implementation work and regression tests.

### 3.2 Byte-based scheduling and an optional nursery

Automatic collection runs at interpreter **safepoints**, where threads can safely
participate in collection. The trigger counts allocated bytes, including scalar
objects and auxiliary storage. Threads batch accounting locally to avoid a shared
atomic update on every allocation, and publish remaining debt when they exit.
The budget grows with the live heap; the first GC threshold also supplies a
minimum of 4 KiB per threshold unit, about 8 MiB at the default setting.

An optional Linux **nursery** concentrates collection on recently allocated
objects. Unlike a copying nursery, it does not move them. It uses Linux soft-dirty
page information to find storage written since a full collection, while still
scanning roots. This helps find old-to-young references without adding a portable
software write barrier to every pointer store.

- `PYTHON_TRACING_GC_SOFT_DIRTY=1` enables the scalar nursery.
- Adding `PYTHON_TRACING_GC_YOUNG_CONTAINERS=1` includes newly allocated exact
  lists, tuples, and unwatched dictionaries, including their unreachable cycles.
- Unsupported types and older survivors wait for full tracing. Excessive
  unsupported allocation, retained descendants, or heap growth forces full GC.
  At most seven nursery collections occur consecutively; explicit `gc.collect()`
  always requests full tracing.
- Backoff avoids repeatedly attempting an unsuitable nursery on instance-heavy
  workloads. Eligible fallback paths reuse the already-built allocation snapshot.

Both options are off by default. The mechanism resets process-wide soft-dirty
history and must not be combined with tools relying on that history. Missing
tracking access, external resets, fork, or multiple interpreters cause fallback.
It is an experimental Linux backend, not a portable replacement for write barriers.

### 3.3 Less scanning and cheaper safe reclamation

The implementation attacks repeated work at several levels:

- Page-level allocation snapshots exclude free slots before reading headers.
  Mark maps use one byte per scalar slot and four bytes per other slot, with
  page-local traversal links and arena allocation for map storage.
- Up to eight independent allocator free lists are walked in an interleaved
  fashion. This exposes independent memory loads instead of following one long
  dependent pointer chain at a time. It is not parallel GC.
- Completely old, unchanged eligible container pages can skip map construction,
  header scanning, and sweeping. Fresh page-state and geometry checks guard this
  cache. Separate item/key buffers still need inspection: writing a list element
  need not modify its header.
- A successful container nursery combines accounting and destruction into one
  sweep. Containers die before their scalar children. It finishes destruction
  and flushes object freelists before restarting threads. A restricted full-GC
  path does the same for graphs containing only callback-free supported objects.
  General finalization paths can resume threads so callbacks can run safely.
- List clearing and list/tuple/dictionary destruction omit per-element decref
  loops when those decrefs cannot destroy children. Buffer ownership counts,
  container synchronization, and allocator safety checks remain.
- Before a fresh full snapshot, empty pages belonging to parked worker threads
  are collected through mimalloc's normal page-retirement machinery. Existing
  QSBR safety checks remain; QSBR delays storage reuse until threads can no longer
  access an old buffer. Returning an empty page to the allocator does not promise
  an immediate return of physical memory to the OS.

The collector is not a parallel or generally concurrent tracing collector.
Free-threaded application execution does not imply parallel marking or sweeping.

### 3.4 Numeric representation: NaN-boxing and immediate integers

`--with-experimental-nanboxing` changes a 64-bit object reference into a tagged
carrier that can contain a heap pointer or a value. An **immediate** value is the
number itself encoded in the reference, not a pointer to a separately allocated
number object. This applies inside containers as well as on interpreter stacks.

| Value | Representation in this checkpoint |
| --- | --- |
| Exact non-NaN float | Immediate binary64 value, preserving finite values, signed zero, subnormals, and infinities |
| NaN | Boxed, preserving payloads and distinct dictionary-key identities |
| Eligible exact integer | Immediate if its magnitude fits one Python integer digit, normally at most `2**30 - 1` |
| Large integer | Boxed arbitrary-precision integer; no truncation |
| Cached small integer, numeric subclass, bootstrap value, writable integer builder | Remains boxed; boxed and immediate forms coexist |
| `None`, `True`, `False` | Existing immortal singleton objects, not newly tagged immediates |

The existing small-integer cache is not the same as the new immediate integer
range. NaN-boxing could encode `None` and booleans too, but that was discussed,
not implemented. They already avoid per-use allocation, so their potential gain
would mainly be fewer pointer/header accesses, not fewer new objects.

Type, numeric, stack-reference, reference-count, locking, and GC helpers were
adapted so they never dereference an immediate as an object header. Specialized
arithmetic constructs immediate float results inline and avoids redundant tag
decoding. NaN allocation and error paths remain. Without NaN-boxing, selected
arithmetic can instead reuse a uniquely owned boxed temporary or JIT local;
aliases must preserve their original values.

This does **not** mean the JIT keeps every number unboxed in floating-point
registers across an entire trace. Tagged values still incur representation and
dispatch costs. The experiment currently requires Linux x86-64 and heap pointers
in the low 48 address bits. It breaks the C ABI and some identity behavior:
equal immediate values may be identical. Extensions must be rebuilt and use
accessors rather than raw header or numeric-payload access. `sys.getsizeof()`
still describes boxed layouts and does not measure these memory savings.

### 3.5 Two supported execution configurations

Both configurations use a `--disable-gil` tracing build, optionally with NaN-boxing:

| Configuration | Runtime settings | Meaning |
| --- | --- | --- |
| FT + tracing | `PYTHON_GIL=0 PYTHON_TLBC=1 PYTHON_JIT=0` | Free-threaded execution, JIT off |
| JIT + tracing | `PYTHON_GIL=1 PYTHON_TLBC=0 PYTHON_JIT=1` | Permanent runtime GIL, shared bytecode, native JIT |

The second configuration still has the free-threaded object layout; it is not a
conventional GIL-build ABI. Simultaneous FT execution and JIT are not supported or
required. Incompatible explicit JIT requests fail during initialization.

JIT work included scanning active trace/compiler buffers and executors as roots,
not keeping dead code alive through a borrowed executor registry, safely reclaiming
invalidated executors and native code, and enabling range specialization under
the permanent GIL. LLVM 21 generated the native stencils. Constant-pool retention
and local PC-relative relocation handling in the stencil tools were fixed with
regression tests; the optimizer was not simply bypassed.

## 4. How to interpret the measurements

The experiments ran on a Linux x86-64 Intel Core i5-12450H machine. Recorded native
builds used GCC `-O3`, without PGO or LTO, and LLVM 21.1.8 for JIT generation.
Single-thread measurements were pinned to CPU 2; four-worker measurements used
four distinct performance cores, CPUs 0, 2, 4, and 6.

The selected comparison drivers used serial fresh processes, alternating version
order, a discarded fresh-process warmup, fixed hash seed, and the normal allocator.
Builds, tests, profilers, and other measurements did not overlap their timed runs.
Tables report medians; `n` is measured processes per configuration, not loop
iterations. Automatic GC was enabled. Tracing comparisons used matching nursery
settings: scalar nursery for the early read/float experiments, and both nursery
options for the later integer/container experiments.

In-process warmup depends on the workload: many numeric drivers call `hot(5000)`
before timing, whereas the cited N-body runs do not use that extra warmup.
Compilation occurring inside a timed interval is included. These results should
not all be read as fully warmed-up, steady-state JIT throughput.

Results and runtime modes were checked. Numerical/container JIT timing drivers
also asserted generated native code existed for the hot function. This is stronger
than checking only “JIT enabled,” but is not a claim that every operation ran as
machine code. The read experiment was FT-only; the failed-constructor experiment
checked JIT configuration, not native compilation of its exception loop.

Important limitations:

- These are controlled development microbenchmarks with 3–9 samples, not a
  representative application suite or statistical confidence-interval study.
  Small differences need repetition; exact percentages are not guarantees.
  Pause-time percentiles and real-time latency guarantees were not established.
- RC FT uses a normal free-threaded build. RC JIT uses a conventional GIL layout,
  whereas tracing JIT retains the FT layout. RC comparisons are end-to-end
  implementation comparisons, not an isolated change of GC algorithm.
- Elapsed time includes ordinary RC destruction. Reported RC “GC time” measures
  its cycle collector, not all reference-counting work, so that column cannot
  compare total memory-management costs between RC and tracing.
- Peak RSS is the process high-water resident memory, including runtime/setup
  costs. Current RSS after collection, allocator-committed bytes, and live
  allocated bytes are different quantities. MiB means `2**20` bytes.
- Historical stage gains cannot be multiplied together: baselines and sometimes
  workload lengths differ. The final committed variant needs fresh full evaluation.

### 4.1 Removing contended reference updates

Ten million reads in total, four threads reading a shared list; `n=3` [E1]:

| Build | Median seconds |
| --- | ---: |
| RC FT | 0.501811 |
| Earlier tracing, before optimistic-read fix | 0.339537 |
| Tracing with direct alias-aware read path | 0.039527 |

That is about 12.7× the RC throughput in this particular contention test. The
underlying bug was concrete: 10,000 reads increased a raw local reference count
from 3 to 10,003 in the earlier tracing build. The fixed helper left numeric fields
unchanged while preserving alias information.

There was a tradeoff: against the earlier tracing build, single-thread list,
dictionary, and slot reads took 15.6%, 9.1%, and 8.5% more time respectively.
Removing shared count traffic does not automatically optimize every read path.

### 4.2 Float immediates remove allocation, not just collection calls

First float-only NaN-boxing stage versus its immediate tracing predecessor;
`n=3`, before immediate integers [E2]:

| Workload / mode | Before seconds | After seconds | Before → after peak RSS, MiB |
| --- | ---: | ---: | ---: |
| N-body / FT | 4.422181 | 2.313192 | 42.20 → 40.00 |
| N-body / JIT | 3.142806 | 2.345472 | 42.63 → 40.50 |
| One million live floats / FT | 0.129310 | 0.084963 | 97.13 → 47.38 |
| One million live floats / JIT | 0.127338 | 0.084230 | 97.29 → 47.63 |

N-body performed 30 × 20,000 integration steps and returned the same energy.
FT collections fell from 337 to 2 and recorded GC time from 1.824900 s to
0.010925 s; JIT collections fell from 235 to 2. A separate allocation-only test
performed four float operations per iteration for one million iterations with GC
disabled: allocated-block growth was just four blocks, including measurement/result
overhead. This verifies allocation elimination, not a faster run obtained by
leaving millions of unreclaimed floats behind.

The live-float list still allocates its pointer array and, at this stage, integer
loop counters. Its collections increased from 7 to 12 despite lower total GC time:
a smaller live heap also reduced the automatic collection budget.

Initially, the JIT float-local microbenchmark regressed from 0.017532 s to
0.020528 s. The subsequent inline encode/decode fast path reduced a separately
measured 0.020526 s to 0.017802 s, near the RC JIT result of 0.017845 s (`n=3`).
In that same comparison, N-body improved from 2.307779 to 2.100044 s in FT and
2.344607 to 2.099043 s in JIT [E3]. Representation helpers matter even after
allocation has disappeared.

### 4.3 Immediate integers help counters and numeric lists

Final integer V2 stage versus the later float-only baseline; `n=7` [E4]. This
baseline already contains improvements made after the first float experiment.

| Workload / mode | Float-only seconds | Integer V2 seconds | RC seconds |
| --- | ---: | ---: | ---: |
| 500,000 integer updates / FT | 0.016108 | 0.007395 | 0.007559 |
| 500,000 integer updates / JIT | 0.013233 | 0.004585 | 0.004527 |
| One million live integers / FT | 0.140142 | 0.042806 | 0.048184 |
| One million live integers / JIT | 0.144352 | 0.040528 | 0.029975 |
| 500,000 float-local iterations / FT | 0.023820 | 0.017701 | 0.023734 |
| 500,000 float-local iterations / JIT | 0.017937 | 0.008663 | 0.017707 |

Integer updates stopped causing collections (2 → 0). The integer list's peak RSS
fell from 97.82 to 39.50 MiB in FT and 98.22 to 40.00 MiB in JIT. Eliminating
integer loop counters also helped the float-local workload, whose JIT result was
about 2.04× as fast as RC in this test.

But larger-integer arithmetic still took about 1.68× the RC time. More importantly,
FT N-body **regressed** from 1.902379 to 2.243287 s, about 17.9%, even while peak
RSS fell from 39.63 to 28.50 MiB and collections fell from 2 to 0. JIT N-body
changed from 2.091505 to 2.122401 s; its RC comparator was 1.212032 s. This is
evidence of remaining mutator costs, not evidence that GC consumed more time.

### 4.4 Reducing collector work gives smaller, targeted wins

Each row compares adjacent experimental variants, not the original RC runtime.
The reclaim workload uses four persistent workers, 16 batches of one million
iterations total per batch, each creating a list/tuple/dictionary graph. Three
full collections between batches and after joining are included in elapsed time;
retained block counts must remain bounded [E5–E8].

| Change / workload | n | FT seconds, before → after | JIT seconds, before → after |
| --- | ---: | ---: | ---: |
| Fused nursery sweep / reclaim | 5 | 3.490332 → 3.320260 | 5.066526 → 4.899867 |
| Clean old-page cache / churn beside 100,000 old lists, 2M iterations | 5 | 0.538143 → 0.484102 | 0.528586 → 0.476000 |
| Clean old-page cache / churn beside 50,000 old dictionaries, 2M iterations | 5 | 0.472200 → 0.448722 | 0.462592 → 0.440073 |
| Interleaved free-list walks / reclaim | 5 | 3.279825 → 3.265414 | 4.855649 → 4.668431 |
| Idle-owner page retirement / reclaim | 3 | 3.251598 → 3.147612 | 4.721963 → 4.708072 |

The cache comparisons include the same freelist-flush correctness fix in both
versions. Its approximately 10%/5% time reductions are specific to those old-heap
workloads. Interleaving reproduced a roughly 3.9% JIT gain, but not a convincing
FT long-run gain. These changes did not demonstrate large peak-RSS reductions.

Page retirement did reduce **idle-phase current RSS**. Three fresh-process probes
per configuration kept four workers alive but parked after four allocation batches
and full collections. Median current RSS fell from 60.39 to 43.58 MiB in FT and
62.68 to 49.50 MiB in JIT: about 28% and 21% reductions [E8]. Live allocated
bytes stayed near 5.5 MiB. The improvement was mainly reclaiming empty allocator
storage, not discovering a much smaller live object graph. Peak RSS changed little.

The idle RSS probes varied noticeably: FT before/after ranges were 59.39–70.69 /
40.91–62.46 MiB; JIT ranges were 62.45–65.63 / 44.14–57.81 MiB. The medians
and allocator evidence support an idle-memory benefit, not a fixed saving on
every run or every application.

Controls also found costs: the old-page-cache stage increased a 10M-iteration FT
float-local loop by about 3.7% (`n=9`), and page retirement increased a 100M-update
JIT integer loop from 0.892289 to 0.906842 s, about 1.6% (`n=9`). Both ran with
zero collections. Code placement is a hypothesis, not a proven explanation.

### 4.5 The remaining RC gap and unsuccessful alternatives

A late, like-duration RC comparison used the page-retirement stage, before the
final frozenset error-path fix, on the same 16-batch reclaim workload; `n=3` [E9]:

| Build | Seconds | Peak RSS, MiB | Collections | Recorded GC seconds |
| --- | ---: | ---: | ---: | ---: |
| RC FT | 0.399584 | 16.13 | 51 | 0.032499 |
| Tracing FT | 3.151349 | 80.89 | 614 | 2.712212 |
| RC JIT | 1.189551 | 14.63 | 51 | 0.027110 |
| Tracing JIT | 4.680306 | 65.95 | 686 | 2.905096 |

Thus tracing still took 7.89× the FT time and 3.93× the JIT time. JIT-mode worker
threads are GIL-serialized; this is not a simultaneous FT+JIT scaling result.
Explicit reclamation prevents a variant from looking fast simply by postponing
garbage collection until after the timer.

Changing policy traded time against memory rather than solving both [E9]:

| Policy experiment | FT time change | FT peak RSS change | JIT time change | JIT peak RSS change |
| --- | ---: | ---: | ---: | ---: |
| Raise first threshold to 4000, about twice default | −13.6% | +62.8% | −8.5% | +53.0% |
| Immediate allocator purge (`MIMALLOC_PURGE_DELAY=0`) | +4.6% | −28.4% | +10.6% | −23.7% |

These policies were not adopted as new defaults. A separate prototype batched
free publication for dead object storage while retaining destructors. Its long
reclaim result improved FT by only 1.4% and worsened JIT by 1.6% (`n=5`), with
roughly 3–4% regressions in several container controls. It was rejected and is
not in the commit [E10].

Profiles pointed to allocation snapshots, free-list walks, dirty-page inspection,
marking, and individual frees as remaining costs. Sample shares are not wall-time
fractions, and profiling alone does not justify skipping ownership or destructor
work. A more direct generation map/write barrier or safe parallel reclamation
remains future work, not an implemented speedup.

### 4.6 Correctness can also recover memory: failed frozenset construction

An error while filling a new frozenset left an initialized but untracked object.
The old cleanup relied on decref destroying it. With tracing, the abandoned object
leaked, and its heap type could be collected first, leaving a dangling type pointer
that later crashed GC. The fix tracks the safe-to-traverse object before returning
the construction error, allowing normal reclamation.

An intermediate version of this fix was measured over 80,000 expected failed
constructions, with collection included; `n=3` [E11]:

| Mode | Seconds, before → fixed | Post-GC allocated-byte growth, MiB | Final current RSS, MiB |
| --- | ---: | ---: | ---: |
| FT | 0.184748 → 0.141044 | 17.092 → 0.0022 | 41.29 → 25.56 |
| JIT configuration | 0.185145 → 0.140349 | 17.092 → 0.0022 | 41.34 → 25.69 |

This is a genuine leak fix and roughly 24% time reduction on an error-heavy
workload, not a general collector speedup. That intermediate binary also regressed
3–8% on several zero-GC FT numerical controls. The committed variant changes the
rare-path tracking call from inline to the existing out-of-line API. It builds and
passes the focused regression in native FT, native JIT, and Debug configurations,
but its full test rerun and comparative timings are still pending. Do not assign
the intermediate measurements to the final variant.

## 5. Reliability and compatibility status

Tests cover root survival across threads and native JIT, reclamation of code,
modules and heap types, alias safety, weakrefs/finalizers, allocation failures,
soft-dirty invalidation/fallback, allocator ownership, and numeric bit patterns,
boundaries, serialization, and mixed boxed/immediate inputs.

Development exposed and fixed concrete crashes: dereferencing immediates in GC
and specialized `__class__` loads; untracking acyclic frozensets that still needed
tracing; failed-constructor cleanup; and executor/heap-type lifetime ordering.
Another test caught nursery freelists being flushed only after threads restarted;
the flush now occurs while stopped. Collection notifications were changed so a
callback can collect, or join another collecting thread, without recursively
dispatching notifications or blocking collection progress.

The intermediate failed-frozenset-fix stage passed focused suites of 265 tests in
Debug, 265 with 16 skips in NaN-boxing-OFF Debug, and 798 with 8 skips in each
native FT/JIT mode. Counts are tests run, including skips. Nevertheless, a broader
12-file Debug run completed with **32 failures among 2,912 tests and 69 skips**:
the previously tracked 30 failures plus two existing set-iterator failures. This
was progress from a crash, not a clean compatibility result [E11]. Other historical
suites had different coverage and failures; 32 is not an exhaustive repository-wide
failure count. The final out-of-line variant has only the focused verification
described above.

Immediate destruction, raw refcount expectations, object identity, native-module
pinning, and shutdown behavior remain compatibility issues. The final source has
not received a complete ordinary-RC build/regression run or non-Linux validation.
Compiler warnings remain, and the manually mirrored `configure` changes have not
been checked by regeneration with the required Autoconf 2.72 tooling. Passing
focused tests does not establish production safety.

## 6. Conclusions for a systems student

1. **Avoiding allocation can matter more than making collection faster.** Float
   and integer immediates remove objects that no collector then needs to visit.
2. **Concurrency changes the bottleneck.** Removing contended header updates
   helps shared reads, while a serial collector can dominate parallel allocation.
3. **Memory has layers.** Unreachable objects, live allocations, empty allocator
   pages, and resident OS pages need different diagnostics and different fixes.
4. **Correctness rules shape optimizations.** Aliases, finalizers, type lifetimes,
   external buffers, and JIT roots constrain which work can safely disappear.
5. **Measure the whole workload, including reclamation and regressions.** A faster
   arithmetic loop or lower collection count does not prove a faster Python.

There is demonstrated headroom beyond RC on selected workloads. A broadly faster,
memory-efficient tracing CPython remains an open implementation task. Future
experiments should reduce repeated whole-heap metadata work and representation
overhead, while validating broad applications, latency, and both required modes.

## 7. Source and evidence guide

Implementation entry points at the checkpoint:

- [Collector allocation graph and nursery](Python/gc_tracing.c.h),
  [collection lifecycle, roots and scheduling](Python/gc_free_threading.c).
- [Reference operations](Include/refcount.h),
  [allocator integration](Objects/obmalloc.c).
- [Immediate tags and type access](Include/object.h),
  [float fast paths](Include/internal/pycore_floatobject.h),
  [integer representation](Include/cpython/longintrepr.h),
  [integer operations](Objects/longobject.c).
- [Bytecodes](Python/bytecodes.c), [optimizer](Python/optimizer.c),
  [JIT assembly optimizer](Tools/jit/_optimizers.py),
  [stencil relocation handling](Tools/jit/_stencils.py).
- [Build/runtime documentation](Doc/using/configure.rst),
  [GC regression tests](Lib/test/test_experimental_tracing_gc.py),
  [NaN-boxing tests](Lib/test/test_experimental_nanboxing.py),
  [JIT-tool tests](Lib/test/test_tools/test_jit_optimizer.py).

Evidence IDs refer to local experimental artifacts under `/tmp` on the development
machine. JSON sample medians were checked while preparing this report. These
artifacts and historical source/build snapshots are **not committed**; the tables
above are self-contained summaries, not a substitute for archiving raw data for
publication. Checkpoints record exact executable paths and comparison settings.

| ID | Raw data / records, relative to `/tmp/` |
| --- | --- |
| E1 | `gc-readfast-final-benchmark.json`; `gc-readfast-progress.md` |
| E2 | `gc-nanbox-benchmark.json`; `gc-nanbox-progress.md` |
| E3 | `gc-nanfast-benchmark.json`; `gc-nanfast-progress.md` |
| E4 | `gc-int-v2-controls1.json`; `gc-int-progress.md` (final V2 section) |
| E5 | `gc-fused-reclaim-long1.json`; `gc-fused-progress.md` |
| E6 | `gc-oldpages-v2-old-roots-long1.json`, `gc-oldpages-v2-locals-long1.json`; `gc-oldpages-progress.md` |
| E7 | `gc-batch-reclaim-long1.json`; `gc-batch-progress.md` |
| E8 | `gc-retire-v2-reclaim-long1.json`, `gc-retire-v2-integer100m1.json`, `gc-retire-v2-idle-{memory,retire}-{ft,jit}-{1,2,3}.jsonl`; `gc-retire-progress.md` |
| E9 | `gc-policy-rc-long1.json`, `gc-policy-sweep1.json`, `gc-policy-extend1.json`; `gc-policy-progress.md` |
| E10 | `gc-batchpage-reclaim-long1.json`, `gc-batchpage-controls1.json`; `gc-batchpage-progress.md` |
| E11 | `gc-failedset-memory1.json`, `gc-failedset-controls1.json`, `gc-failedset-debug-stdlib1.log`; `gc-failedset-progress.md` |

For orientation, E2 adds float immediates to E1's tracing build; E3 improves their
fast paths; E4 adds integers after further intervening work. E5 → E6 → E7 → E8
are later collector stages. E9 changes policies on E8's executable. E10 was
rejected. E11 measures an intermediate fix; commit `1b990379c85` contains its
later, not yet fully measured, out-of-line-call variant. Early “not implemented”
or “tests running” statements in checkpoint files can be superseded by appended
results; they are not the final status used here.

The committed [benchmark tool](Tools/scripts/benchmark_tracing_gc.py) provides
`numeric`, `threads`, `reads`, `mixed`, `automatic`, and explicit-collection suites.
Its simple runner repeats within a process and does not reproduce all controls
of the private fresh-process drivers. Its default `refcounts` suite disables GC;
in a tracing build that can merely accumulate garbage. Use reclamation-inclusive
workloads, matching environment settings, separate build directories, native-code
checks, and independently repeated processes for meaningful new comparisons.
