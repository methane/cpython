# Experimental tracing GC: implementation and findings

Date: 2026-09-07. Implementation checkpoint: `1b990379c85` on
`experimental-tracing-gc`.

This report is for students familiar with pointers, graphs, threads, and basic
computer architecture. It describes a research prototype, not a production-ready
replacement for CPython's memory management. Compatibility changes were allowed
to explore performance potential. Measurements below belong to explicitly named
development stages; they are **not a complete benchmark of the final commit**.
Sections 8–16 record subsequent development separately.

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
  Mark maps use one byte per scalar slot and two bytes per other slot, with
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

## 8. Follow-up: set-operation cleanup and a rejected scan optimization

This section records work after the checkpoint above, also on 2026-09-07.
The final constructor fix was evaluated first. It preserved the failed-frozenset
memory improvement, but FT N-body still took about 3.9% more time than the earlier
page-retirement build. The earlier integer/float-local regressions were much
smaller in this comparison. These results do not erase the historical regressions.

### A scan optimization that did not pay off

A candidate counted potential dirty roots per allocator page during existing
classification and buffer-ownership work. It then avoided another slot-map walk
whose only purpose was to ask whether such roots existed. Debug builds recomputed
the counts independently and asserted equality before traversal.

Focused tests passed, but five fresh-process measurements of the 16-batch parallel
reclaim workload gave FT 3.105051 → 3.159997 s (1.8% worse) and JIT
4.716666 → 4.707909 s (essentially unchanged). Old-heap controls improved by
less than 1%, without a meaningful memory reduction. The implementation was
reverted; only an additional mixed-buffer root-survival/reclamation test remains.
Eliminating a loop is not sufficient if maintaining its summary adds other costs.

### Fixing abandoned temporary sets

Broader testing exposed a crash in the committed baseline as well as the candidate.
The debugger showed an untracked exact set containing a freed element, visited
from the nursery's deferred-object traversal. The constructor fix had not covered
all temporary sets created by collection operations.

The new `set_decref_untracked()` helper registers a completed, abandoned set with
tracing GC before the otherwise ineffective decref. Constructor, copy, union,
intersection, difference, and symmetric-difference cleanup paths use it where the
temporary is still untracked. Already-tracked objects keep their existing cleanup.
Successful construction is not tracked prematurely, and ordinary RC behavior is
preserved. This fixes storage leaks and prevents full GC from freeing children
while an abandoned, untracked parent can still be encountered later.

A new regression test covers `set`/`frozenset`, four operations, and iterator/hash
failures: 16 combinations, each performing 256 failures in an exited worker.
All 16 failed the post-collection allocation bound on the preceding build and
passed after the fix.

The following dedicated experiment performs 80,000 failing operations across four
batches, alternating set and frozenset. Automatic GC is enabled and three explicit
full collections per batch are timed. Immortal `None`/`True` elements let the
leaking baseline finish without dangling-child crashes. Medians of three fresh
processes per mode, with the same isolation/affinity rules as section 4:

| Mode | Seconds, before → after | Post-GC allocated-byte growth, MiB | Final current RSS, MiB |
| --- | ---: | ---: | ---: |
| FT | 0.204710 → 0.148158 | 17.0937 → 0.0039 | 42.25 → 27.08 |
| JIT configuration | 0.210108 → 0.148259 | 17.0937 → 0.0039 | 42.29 → 26.95 |

That is about 28%/29% less time for this error-heavy workload. JIT runtime settings,
not native compilation of the exception loop, were asserted. This is a lifetime
and memory improvement, not evidence of general tracing-GC superiority.

Ordinary controls exposed a cost. Five-sample long reclaim times were nearly flat:
FT 3.142610 → 3.139654 s; JIT 4.654538 → 4.684329 s. Peak RSS was
79.59 → 79.83 MiB and 66.19 → 67.39 MiB respectively. Numerical N-body and
float-local controls changed little, but the short container controls regressed.
Longer, separately repeated controls confirmed that regression (`n=5`):

| Workload | FT seconds, before → after | JIT seconds, before → after |
| --- | ---: | ---: |
| 100M integer updates | 1.410078 → 1.430473 | 0.896351 → 0.892278 |
| 2M container-churn iterations | 0.413191 → 0.425554 | 0.404749 → 0.416761 |
| 2M iterations beside old lists | 0.465606 → 0.479496 | 0.458932 → 0.470186 |
| 2M iterations beside old dictionaries | 0.433313 → 0.445835 | 0.425188 → 0.436107 |

The container regressions are approximately 2.5–3%, with almost unchanged recorded
GC durations and matching collection/block counts. The FT integer regression is
about 1.4%, with zero collections. Their cause has not been established; attributing
them to additional collector work would be unsupported. The correctness fix is
retained, and these performance regressions remain open work.

Validation of this follow-up:

- Native FT/JIT focused suites: 800 tests each, 9 skips, success; another 100
  repeated GC methods per mode passed, including repeated error-path subtests.
- Debug focused suite: 284 tests, success; NaN-boxing-OFF Debug: 284 tests,
  16 skips, success.
- The 12-file Debug run now completes: 2,912 tests, the same 32 failure IDs as
  the earlier completed run, 69 skips. It is not a clean suite.
- Native `test_set` completes with 644 tests and three iterator-cycle failures
  per mode. All three were also observed in the baseline's full-suite context;
  isolated tests alone did not reproduce every one. The baseline JIT full run
  itself aborted, illustrating why incomplete-run totals are misleading.
- A newly rebuilt ordinary RC FT executable passed 1,260 tests with 9 skips,
  covering sets, integers, floats, math, selected C APIs, types, and JSON. This
  narrows the previous RC-build validation gap; it is not a full RC test run or
  a conventional-GIL RC build.

Local evidence: `/tmp/gc-failedset-v2-{controls1,reclaim-long1,memory1}.json`,
`/tmp/gc-rootcounts-{reclaim-long1,controls1}.json`,
`/tmp/gc-setcleanup-{memory1,reclaim-long1,controls1,confirm1}.json`, and
`/tmp/gc-setcleanup-progress.md`. The corresponding drivers and test logs are
retained locally. No general throughput win or production-readiness claim follows
from this update.

## 9. Follow-up: bulk set release, three rejected variants

This experiment, also on 2026-09-07, produced useful negative results. **None of
the three speed-change variants below is retained.** The implementation returns
to section 8's set-operation cleanup; new tests and benchmark workloads remain.

A dead set still needs its table freed, but tracing GC already determines which
children are reachable elsewhere. Decrementing every child's reference count is
therefore unnecessary once decrefs are inert. Unlike list and tuple destruction,
set destruction still walked the entries. Native disassembly confirmed that this
was a real loop, including a tracing-enabled check for each occupied entry.

Three prototypes skipped that loop and similar work in `set.clear()`:

- V1 reset the set and freed its old table through an early tracing-only path,
  without copying the inline table or visiting its keys.
- V2 avoided resetting an already-empty inline table in that path.
- V3 removed the duplicate early path, retaining the original reset/free control
  flow and guarding only the inline copy and per-entry decref loops.

All kept weakref handling and the normal delayed free for shared tables. None
changed collection thresholds or intentionally postponed reclamation. V3 was a
control-flow simplification, not an attempt to pad or align the executable.

### Local gains did not establish an acceptable overall improvement

V1 improved the following workloads, using medians of seven fresh processes per
configuration. The baseline is section 8's cleanup build. Automatic GC and both
experimental nurseries were enabled; builds/tests/profiles did not overlap timing.
Versions alternated on CPU 2, with fixed hash seed and a discarded warmup process.

| Workload | FT seconds, before → V1 | JIT-enabled configuration, before → V1 |
| --- | ---: | ---: |
| Copy a 4,096-key set and clear it, 20,000 times | 0.710523 → 0.674735 | 0.712913 → 0.677504 |
| Create 8,192 frozensets in 64 batches, with full GC between batches | 2.021534 → 1.988979 | 2.019310 → 1.992120 |

The first gain is about 5%; the second is only 1–2%. The set loops had no native
executor at measurement end, so these are **JIT-enabled configuration results,
not demonstrated native-loop speedups**. Existing numerical, container, and
parallel-reclaim controls retained their native-code assertions.

Collection counts and final allocated-block counts matched exactly in these
target workloads. Peak RSS was effectively unchanged: about 19 MiB for clear and
30 MiB for frozenset reclamation. Frozenset timings include three full collections
after each batch, with a bound on retained-block growth.

The 16-batch parallel list/tuple/dict reclaim workload was essentially flat
(`n=5`): FT 3.167725 → 3.160779 s, JIT 4.722452 → 4.718345 s.
V1's ordinary container controls were about 3% faster with nearly unchanged GC
durations, but that does not establish a causal collector improvement.

Further controls exposed regressions. The following rows use a nine-process
three-way comparison for V1/V2, and seven processes for V3; each row reports its
own baseline rather than mixing measurements from different runs:

| Candidate / control | FT seconds, before → candidate | JIT-enabled seconds, before → candidate |
| --- | ---: | ---: |
| V1: 10M calls to `clear()` on an already-empty set | 0.229310 → 0.262327 | 0.216106 → 0.247699 |
| V2: 100M integer updates | 1.441579 → 1.479357 | 0.893306 → 0.958833 |
| V3: 100M integer updates | 1.424464 → 1.476458 | 0.892693 → 0.898397 |

V1 made empty clear about 14% slower. V2 fixed that case but made the integer
control about 2.6% slower in FT and 7.3% slower in JIT; a preceding independent
five-process comparison had already shown the regression. V3 preserved empty
clear performance but still regressed the FT integer control by about 3.6%.
These integer loops had zero collections, so additional GC execution cannot
explain their slowdown. Binary layout is a possible explanation, not a diagnosis
established by this experiment. No fourth layout variant was tried.

The selective gains were insufficient to accept these tradeoffs. All prototype
C changes were reverted, preserving the preceding correctness fixes. In
particular, the positive prototype measurements must not be assigned to the
current implementation.

### Tests retained and the next hypothesis

`test_set_bulk_release` covers 36 configurations: builtin/subclass sets and
frozensets, empty/small/large storage, sparse/dense mutable sets, clear/destruction,
child finalization, weakrefs, retained children, and reuse after clearing.
Allocation happens in exited workers to avoid stale conservative C-stack roots.
It passes on the original implementation too: this is semantic regression
coverage, not a timing assertion.

Each prototype passed the focused Debug suite (285 tests), NaN-boxing-OFF Debug
(285, 16 skips), native FT/JIT (801 each, 9 skips), ordinary RC FT (1,260,
9 skips), and seven free-threading set race tests. Complete native `test_set`
runs still had the known three iterator-cycle failures, and some FT runs also
showed an intermittent `TestFrozenSetSubclass.test_free_after_iterating` failure.
The extra passed in isolation and in two full V1 reruns. This is not a clean
compatibility result. An initial two-failure nursery-policy test run was caused
by forcing container-nursery settings onto scalar-only tests; the same failures
were reproduced on the baseline before rerunning with per-test settings.

After reverting, the new test and two related set tests were each repeated three
times against the original native FT, native JIT, Debug, and NaN-OFF Debug builds:
nine methods per configuration, all passed. At the end of that stage, the C source
matched the preserved section 8 snapshot exactly.

A more substantial remaining opportunity is allocation accounting. The wide-set
clear workload still triggered 625 collections despite promptly releasing each
external table. The allocator records gross requested bytes but does not credit
these frees. Accounting for released auxiliary storage might avoid unnecessary
collections; this is **a hypothesis, not an implemented speedup**. Correctly
handling old-epoch frees, allocator size rounding, ownership, and delayed QSBR
storage is essential—naively subtracting usable sizes could undercount real debt.
This would address immediately released storage, not automatically solve the
large parallel-reclaim gap to RC.

Reproducible workloads were added to the benchmark tool as `wide_set_clear` and
`wide_frozenset_reclaim` in the mixed suite. Their public defaults are shorter
than the private long runs above. Local evidence is preserved in
`/tmp/gc-setbulk-{target3,controls1,reclaim-long1,selection1}.json`,
`/tmp/gc-setbulk-v2-{target1,controls1,reclaim-long1}.json`,
`/tmp/gc-setbulk-v3-preflight1.json`, the corresponding drivers/test logs, and
`/tmp/gc-setbulk-progress.md`.

## 10. Follow-up: check outstanding storage before tracing

### Why gross allocation is sometimes misleading

A list can repeatedly allocate a large element array and release it with
`clear()`, while the list object itself stays alive. Counting every requested
byte toward the next collection makes this look like a growing heap—even when
almost all the storage has already been returned to the allocator. In a new
regression test, 128 repetitions of a roughly 1 MiB list buffer caused 16
automatic collections on the preceding implementation.

The new pressure check runs only after the ordinary byte-debt trigger fires.
It stops the interpreter's threads and sums allocated slots from mimalloc's
page metadata, including the abandoned heaps of exited threads. It does not
trace object references or construct allocation maps. Enumeration stops early
when enough outstanding storage is found; an incomplete traversal or arithmetic
overflow conservatively requests a real collection.

Let `L` be the existing live-byte estimate from the last collection, and let
`B = max(L, threshold * 4096)` be the ordinary allocation budget. The retained
candidate dismisses an automatic trigger only when outstanding allocated
storage is below `L + B/2`. On dismissal, it rebases allocation debt on the
observed excess over `L`, but **never moves `L` forward**. Otherwise a small
amount of garbage accumulating between checks could escape collection forever.
Explicit `gc.collect()` calls bypass this gate. Nursery age bits, dirty-page
epochs, and conservative nonleaf pressure are not reset by a skipped collection.

An initial variant allowed growth up to the full budget, `L + B`. It improved
buffer reuse but increased peak RSS by roughly 3.5–7 MiB on ordinary mixed
container workloads. The half-budget rule is a memory-policy correction, not a
change to object representation or a new tracing algorithm. Neither rule places
a hard limit on RSS: allocated slots, committed allocator pages, and resident
memory are different quantities.

These checks still pause threads. They do not send GC callbacks or increment
collection counts/durations when tracing is skipped. Therefore zero reported
collections does **not** mean zero pauses; end-to-end timings include the checks.

### Correctness checks

Three new tests cover promptly released buffers (including a subsequent explicit
collection), slow accumulation of cyclic garbage across repeated pressure
checks, and garbage left in an exited worker's allocator heaps. The first test
fails on the preceding implementation and passes with the gate. Tests also
exercise mixed buffer ownership, finalization/resurrection, nursery fallback,
and stopped-world reclamation.

The half-budget candidate passed 288 focused tests in Debug and in
NaN-boxing-OFF Debug (16 skips in the latter), and 804 in each native FT and
JIT-enabled configuration (9 skips). A stricter `MI_DEBUG=3` allocator build
passed 24 repeated regression methods. The ordinary RC FT build passed 1,260
tests (4 skips under the unittest runner). The broader Debug run still reported
32 failures and 69 skips among 2,912 tests, with the same nine failing modules
as the preceding stage. This is not a clean compatibility result.

### Measurement method and ordinary-workload controls

The before/after comparison uses the preserved section 8 implementation and the
half-budget candidate, with both scalar and container nurseries enabled. Native
builds use GCC 13.3, `-O3`, no PGO/LTO, and LLVM 21 JIT stencils. FT runs have
the GIL disabled and JIT disabled; JIT-enabled runs have the GIL permanently
enabled. Each timing is a fresh process, with fixed hash seed, normal allocator,
discarded warmup, and alternating version order. Builds, tests, and profiling
do not overlap measurements. Single-thread runs use CPU 2; four-worker runs use
CPUs 0, 2, 4, and 6, separate physical performance cores on this machine.

Five-process medians on three ordinary container controls were:

| Workload | FT seconds, before → candidate | JIT-enabled seconds, before → candidate | FT peak RSS MiB, before → candidate |
| --- | ---: | ---: | ---: |
| 2M mixed container iterations | 0.426976 → 0.414720 | 0.417399 → 0.407086 | 22.375 → 22.625 |
| Same, with 100k old lists | 0.482547 → 0.468695 | 0.471272 → 0.459844 | 36.563 → 36.566 |
| Same, with 50k old dictionaries | 0.433580 → 0.421024 | 0.423739 → 0.412861 | 37.500 → 37.473 |

Unlike the full-budget variant, these runs had the same collection counts and
final allocated-block counts as the baseline. JIT-enabled peak RSS also stayed
within 0.125 MiB of its baseline. The roughly 2.4–2.9% timing differences are
end-to-end observations, not evidence that the gate reduced tracing in these
controls: it did not reduce their collection counts.

Numerical controls did not show a substantial regression. The 100M-integer JIT
loop measured 0.893162 → 0.893685 seconds; the 10M-float-local loop measured
0.357447 → 0.357211 seconds in FT and 0.173110 → 0.173022 in JIT. FT integer
and n-body medians were lower, but these timed loops performed no collections;
their differences cannot be attributed to avoided collector work. In particular,
the integer FT baseline ranged from 1.372376 to 1.438401 seconds, overlapping
the candidate's range. No binary-layout explanation was established or tuned.

### Large-buffer results and their limits

The targeted workloads use 512 serial list-buffer reuses, four workers with
128 reuses each, 20k copies/clears of a 4,096-element set, and 64 batches of
128 wide frozensets respectively. Five-process medians were:

| Workload | FT seconds, before → candidate | JIT-enabled seconds, before → candidate | FT peak RSS MiB, before → candidate |
| --- | ---: | ---: | ---: |
| Reused list buffer | 0.113651 → 0.050125 | 0.113586 → 0.049680 | 21.500 → 20.625 |
| Four-worker buffer reuse | 0.093494 → 0.019428 | 0.139967 → 0.061807 | 28.336 → 25.500 |
| Wide set copy/clear | 0.713140 → 0.261113 | 0.715440 → 0.258784 | 19.000 → 22.500 |
| Wide frozenset creation/reclamation | 2.017541 → 2.019612 | 2.024023 → 2.020798 | 30.125 → 30.125 |

Serial buffer reuse improved about 2.3x in both configurations. Four-worker
reuse improved about 4.8x in FT and 2.3x with the GIL enabled. Their collection
counts changed from 64 to zero (serial), 34 to one (FT parallel), and 52 to one
(GIL-enabled parallel). The latter's peak RSS also fell, 28.270 → 25.324 MiB.
These are C-heavy workloads: the driver recorded no native executor code for
these loops. The JIT-enabled column is therefore a runtime-configuration result,
**not a claim that these loops executed as native JIT code**.

Set copy/clear improved about 2.7x, but this has a memory tradeoff. The candidate
retained roughly 3,600 additional allocated blocks at the end of the timed
region, principally empty set bodies awaiting GC; peak RSS increased about
3.5 MiB. It performed one collection instead of 625. Frozenset reclamation was
essentially unchanged, with 448 collections in both versions: avoiding gross
debt from promptly freed storage does not make ordinary object tracing free.

The demanding four-worker container-reclaim test includes 16 allocation batches
and explicit collections between batches. FT time changed 3.178086 → 3.104315
seconds, while peak RSS increased 79.637 → 81.340 MiB. JIT-enabled time changed
4.660439 → 4.683813 seconds, with RSS 65.488 → 66.793 MiB. This is not a
substantial improvement to the general reclamation bottleneck. Its RC
comparators measured 0.402136 seconds / 16.125 MiB in FT and 1.192935 seconds /
15.242 MiB in conventional GIL-enabled JIT. The tracing candidate still took
about 7.7x and 3.9x those times respectively. These are whole-runtime comparisons
with different representations/build configurations, not isolated collector
costs; the conventional RC JIT comparator is an older preserved build.

### Include reclamation before calling it a speedup

A second experiment repeats eight batches and performs three full collections
after **every** batch, inside the timer. It also checks that post-collection
allocated-block counts stabilize. Three-process medians were:

| Eight-batch workload, including 24 explicit GCs | FT seconds, before → candidate | JIT-enabled seconds, before → candidate |
| --- | ---: | ---: |
| Wide set copy/clear, 20k iterations per batch | 5.665689 → 2.023969 | 5.684349 → 2.020127 |
| List-buffer reuse, 512 iterations per batch | 0.911444 → 0.454693 | 0.909023 → 0.454519 |

The speedups survive actual reclamation: about 2.8x for set clear and 2x for
buffer reuse. Final block counts matched the baseline exactly in three of the
four comparisons and differed by one in the fourth. Buffer-reuse peak RSS fell
by 0.375 MiB in both modes. Set-clear peak RSS still increased, from 19.000 to
23.750 MiB in FT and 19.375 to 23.875 MiB with the GIL enabled. Stable retained
blocks do not erase a peak-memory tradeoff.

The half-budget gate is retained as a targeted scheduling improvement. It
recovers much of the unnecessary collection cost on immediately released
buffers, without the initial variant's ordinary-control memory growth. It does
not resolve the large parallel allocation/reclamation gap or the existing
compatibility failures; further work must address those, not just optimize the
already-improved buffer benchmark.

Public workloads are `reused_list_buffer` in the mixed suite and
`parallel_buffer_reuse` in the threads suite of
`Tools/scripts/benchmark_tracing_gc.py`. Exact long-run measurements above are
preserved in `/tmp/gc-heapgate-v2-{controls1,parallel1,target1,lifecycle1}.json`
and their logs. Drivers are `/tmp/gc-heapgate-v2-benchmark.py` and
`/tmp/gc-heapgate-v2-lifecycle-benchmark.py`; the local checkpoint
`/tmp/gc-heapgate-progress.md` records source snapshots, build configurations,
test evidence, and the superseded full-budget experiment separately.

## 11. Follow-up: header prefetching did not improve reclamation

After the pressure-gate change, a fresh profile of the demanding parallel
reclaim workload attributed about 11.3% of sampled user-space core cycles to
snapshot construction. Within that function, samples clustered around dependent
free-list loads and object-header loads. This identifies places to investigate;
it does not prove that explicit prefetching will make them faster.

A prototype used the completed allocation map to prefetch an allocated header
16 slots ahead, bounded to the same allocator page, while all interpreter
threads remained stopped. It added no allocation/free-path work or persistent
metadata. This is distinct from the earlier rejected pagemap-read prefetching.

The primary test used four workers, 16 batches of one million total container
iterations per batch, and explicit collections between batches. Five fresh
processes per configuration, alternating version order, a discarded warmup,
fixed hash seed and four physical performance cores gave these medians:

| Configuration | Seconds, pressure gate → prefetch prototype | Peak RSS MiB, pressure gate → prototype |
| --- | ---: | ---: |
| FT, JIT disabled | 3.100087 → 3.177241 | 80.543 → 81.004 |
| Permanent GIL, native JIT enabled | 4.654104 → 4.650879 | 66.066 → 67.512 |

FT was about 2.5% slower and JIT was essentially unchanged. All runtime-mode,
native-code, workload-result and bounded-reclamation assertions passed. The
prototype also passed 289 focused Debug tests and 805 tests in each native
FT/JIT configuration (9 skips). Passing tests did not justify retaining a
performance regression: **the prefetch code was reverted**.

A separate three-run FT counter diagnostic found about 1.3% more retired core
instructions (50.159 → 50.800 billion), with essentially unchanged generic
cache-miss counts (240.283 → 240.627 million). Only the performance-core counters
had nearly complete running coverage; efficiency-core counters were not used.
These instrumented, sequential diagnostic runs are not the alternating timing
comparison above and do not establish a complete causal explanation. They do
not support further tuning of this lookahead as the main solution.

The retained regression test mixes cyclic containers and tuples ranging from
empty to 32,768 entries, created by exited workers. Repeated collections check
exact weakref survival and payload integrity across sparse and huge pages.
It passes the preceding implementation too; this is semantic coverage, not a
claim of fixing an existing bug. After reverting, this test and two related
sparse-page tests were repeated three times each on the retained native FT,
native JIT, Debug, and NaN-boxing-OFF Debug builds: nine methods per configuration,
all passed. The next performance direction is reducing
mandatory snapshot work, rather than merely adding hints around the same work.
The general speed/memory objective remains unmet.

Local evidence is preserved in `/tmp/gc-header-reclaim1.json`, its driver/log,
`/tmp/gc-heapgate-current-perf1.data`, snapshot annotations, and
`/tmp/gc-header-{baseline,candidate}-stat1.log`. Source/build/test provenance is
recorded in `/tmp/gc-header-progress.md`. None of the rejected prototype's
results should be described as an improvement in the retained implementation.

## 12. Follow-up: combine header classification and buffer preparation

### Remove a repeated walk, not just its cache misses

The container nursery classified object headers, then walked the typed heap
again to identify young lists' element arrays and young dictionaries' private
storage. Such buffers must not independently keep a dead young owner's children
alive. They should be traced only when their owner or another real root reaches
them. The second walk repeated header and allocation-map reads.

The new implementation identifies those buffers during the first header pass.
It first completes the allocation maps for the untyped MEM and OBJECT heaps
and sorts that prefix of the page table. Young-header classification can then
look up private buffers without waiting for the remaining typed heaps. This
trades an additional prefix sort for removing the later whole typed-heap walk.
Shared dictionary keys and embedded values retain their existing ownership rules.

Two details are essential for correctness. Cached page-table pointers are
cleared when the table grows and after its final sort. Also, an early fallback
to full tracing must reset the private-buffer marks that classification may
already have set, as well as the typed-object marks, so that full tracing
receives the same unmarked allocation maps as a fresh full snapshot. No edges
have been traced at that point. The world remains stopped throughout these operations; no
mutator allocation/free hook, nursery budget, or reclamation eligibility changed.

### Validation and controls

The existing fallback/resurrection test now additionally retains 64 young
list/dictionary cycles through an old owner. It checks buffer contents and
cycles after fallback and three more full collections, while keeping its
original finalizer/resurrection assertions. The extended test also passed the
preceding implementation. Debug and NaN-boxing-OFF Debug each passed 289 focused
tests (16 skips in OFF). Native FT and JIT each passed 805 tests (9 skips), plus
30 repeated methods covering fallback, buffer ownership, watched/external roots,
split storage, sparse abandoned pages and huge objects. The broader Debug run
still had 32 failures and 69 skips among 2,912 tests; its exact failure names
matched the earlier pressure-gate run. Existing compatibility issues remain.

Five-process ordinary-workload controls used the same isolated, fresh-process,
alternating-order method as section 10. Both nursery options were enabled.

| Workload | FT seconds, pressure gate → fused preparation | JIT-enabled seconds, pressure gate → fused preparation |
| --- | ---: | ---: |
| 2M mixed container iterations | 0.414228 → 0.408519 | 0.404210 → 0.401445 |
| Same, with 100k old lists | 0.466169 → 0.460173 | 0.458010 → 0.451564 |
| Same, with 50k old dictionaries | 0.419545 → 0.414234 | 0.411660 → 0.405686 |

These runs improved roughly 0.7–1.5%, with identical collection counts and final
allocated-block counts. Peak RSS stayed within 0.125 MiB of the baseline.
Numerical controls stayed essentially flat: the 100M-integer loop measured
1.379877 → 1.380260 seconds in FT and 0.891539 → 0.891661 in JIT. Float-local
and n-body median changes were below 0.5%; those timed loops had no collections.
The previously improved serial buffer-reuse workload also stayed around
0.050 seconds and 20.625 MiB in both modes, with zero timed collections.

### Repeated primary measurement and remaining limits

The primary workload again uses four workers, 16 batches of one million total
container iterations per batch, and explicit full collections between batches.
Both independent comparisons passed all result, native-JIT and bounded-retention
assertions. Each row below uses its own baseline, not measurements selected from
different runs:

| Comparison | FT seconds, before → after | JIT-enabled seconds, before → after |
| --- | ---: | ---: |
| First comparison, 5 processes | 3.140473 → 3.049577 | 4.705277 → 4.488543 |
| Independent repeat, 7 processes | 3.127844 → 3.049702 | 4.731511 → 4.479786 |

The repeat shortened FT time by about 2.5% and JIT-enabled time by 5.3%.
Reported GC time fell 2.658126 → 2.570966 seconds in FT and 2.941909 → 2.702616
in JIT. Peak RSS changed 82.070 → 82.320 MiB in FT and 66.453 → 65.613 MiB in
JIT: **this is primarily a speed improvement, not a memory breakthrough**.
Final allocated-block medians were identical in FT and differed by one in JIT.

The same repeat included RC comparators: 0.411909 seconds / 16.125 MiB for FT
and 1.202261 seconds / 15.238 MiB for conventional GIL-enabled JIT. The tracing
candidate still took about 7.4x and 3.7x those times, respectively, and over
four times their peak RSS. The RC JIT executable is an older preserved build;
these remain end-to-end configuration comparisons, not isolated collector costs.

Parallel buffer reuse was a less clear control. The initial short test's median
was roughly 2.7–2.9% slower, despite lower reported GC time. An independent
11-process repeat instead measured 0.019090 → 0.018731 seconds in FT and
0.061471 → 0.061905 in the GIL-enabled configuration. With eight times the work
(1,024 reuses per worker), nine-process medians were 0.114255 → 0.112185 in FT
and 0.669007 → 0.694067 in the GIL-enabled configuration. The latter had wide,
overlapping ranges. A further 15-process same-affinity confirmation measured
0.645060 → 0.649417 seconds, again with wide overlapping ranges.

For diagnosis only, pinning all four GIL-enabled workers to CPU 2 produced
0.405925 → 0.405914 seconds over 11 processes. That changed-affinity result must
not replace the original four-core comparison. These C-heavy loops had no
native executor code. Their variability does not establish a scheduling cause
or prove equivalence, and they do not support a universal speedup claim.

The fused preparation is retained for its repeated primary-workload improvement
and modest ordinary-container gains, with the above limitations recorded.
The broader objective is still unmet: collector work remains substantial and
serialized, peak memory is high, and known compatibility failures remain.

Evidence is preserved in `/tmp/gc-bufferfusion-{reclaim1,reclaim2,controls1}.json`,
the separate buffer-control JSON/log files, and their benchmark drivers.
`/tmp/gc-bufferfusion-progress.md` records the unchanged candidate source,
builds, test results and timing sequence. No timings overlapped builds, tests,
profiling or other benchmark runs.

## 13. Follow-up: completing scheduled memory purges at full GC (not retained)

Reclaiming an object, freeing its allocator page, and returning physical memory
to the operating system are different operations. A diagnostic with four workers
found roughly 5.6 MiB of allocated slots after full collections, but much higher
process RSS. Per-area allocator statistics do not include all committed free
spans in otherwise occupied segments. An idle thread may not allocate again to
finish those spans' delayed purges.

The prototype completed already scheduled segment purges before fresh full-GC
snapshots, after the existing normal page-retirement pass. It visited active
owners and abandoned segments while the world was stopped. It did not force
occupied or QSBR-protected pages to retire, change the allocator's global purge
delay, add a per-free hook, or purge empty segments already returned to shared
arenas. Saved fallback snapshots and minor collections were unchanged.

### Repeated time and peak-memory measurements

The comparator was section 12's fused preparation. The primary workload, build
flags, four-core affinity, nursery settings and serial fresh-process method were
unchanged. Each comparison alternated execution order and discarded a warmup.
All benchmark result, native-JIT and bounded-retention assertions passed.
Numbers below are medians; RSS is the process peak measured with `ru_maxrss`.

| Comparison | Mode | Seconds, baseline → purge | Peak MiB, baseline → purge |
| --- | --- | ---: | ---: |
| 5 processes per configuration | FT | 3.027961 → 3.106948 | 80.746 → 68.184 |
| 5 processes per configuration | JIT-enabled | 4.500864 → 4.552518 | 66.457 → 64.590 |
| Independent 7-process repeat | FT | 3.036604 → 3.107116 | 81.023 → 67.867 |
| Independent 7-process repeat | JIT-enabled | 4.494736 → 4.584948 | 66.328 → 65.438 |

The repeat reduced FT peak memory about 16.2%, but increased time about 2.3%.
JIT-enabled peak memory fell only 1.3%, with about 2.0% more time. This is a
memory/throughput tradeoff, not a speed improvement. A separate untimed diagnostic
also showed lower RSS after workers exited: 64,852 → 29,724 KiB in FT and
58,196 → 28,952 KiB in JIT. Those are single approximate `/proc/self/status`
snapshots from a different workload, not repeated peak-memory measurements.
They suggest useful idle-memory release but cannot establish its typical size.

### Validation, unresolved failure, and disposition

A new semantic test parks four workers across three allocation epochs, retains
nonzero 64 KiB buffers and container results, and verifies their contents after
each of three full collections per epoch. It uses a long allocator purge delay,
checks clean thread termination and reuse, and makes no fragile RSS assertion.
This test also passes the preceding implementation and is retained.

The prototype initially passed 290 focused Debug tests, 290 NaN-boxing-OFF Debug
tests (16 skips), and 806 native tests in each mode (9 skips). An `MI_DEBUG=3`
build passed 45 repeated methods. The broader Debug run had the same 32 failure
names and 69 skips among 2,912 tests as the preceding implementation.

However, a separate 45-method native FT repetition failed the existing
fallback/resurrection test's final weak-reference count assertion three times.
Native JIT passed all 45 methods. The FT suite passed on rerun, and an unchanged
test run 200 times with hash seed zero and 200 times with randomized seeds passed
on **each** binary. These later passes do not explain or erase the first failures;
they establish neither a fix nor pre-existing baseline flakiness.

The forced-purge runtime change was therefore removed. Its replicated throughput
cost, small JIT peak-memory benefit, and unresolved correctness-test result do
not justify adopting it. Section 12's runtime optimizations remain intact.
Ordinary-workload controls were not pursued after these adoption gates failed.
The overall speed/memory objective remains unmet.

Evidence is preserved in `/tmp/gc-fullpurge-reclaim1.json`,
`/tmp/gc-fullpurge-reclaim2b.json`, the memory and test logs, and
`/tmp/gc-fullpurge-progress.md`. The `reclaim2` launch used an incorrect workload
alias and exited before running a child; it supplied no measurements. Prototype
sources and builds remain available for diagnosis. No timings overlapped builds,
tests, profiling or other benchmark runs.

## 14. Follow-up: two-byte allocation maps

The snapshot's non-scalar allocation maps now use 16-bit entries instead of
32-bit entries. This halves their **per-slot payload**, not the whole heap or
process memory. Scalar maps still use one byte. Arena allocations retain the
same 64 KiB minimum payload, so rounding and other metadata still cost memory.

This works because a pending traversal stores a slot index within one allocator
page, not an object address. Current page geometry limits the number of slots
well below the 16-bit range, including space reserved for traversal links and
three special states. Compile-time geometry assertions and a runtime capacity
guard protect this bound. Object addresses, strides and general indices retain
their width. Compiled debug information confirmed 2-byte entries versus 4 bytes
in the comparator, with the page descriptor still 96 bytes in both builds.
No object layout, allocation hook, nursery budget, or reclamation rule changed.

### Safety coverage

A new test builds 8,193 cyclic list/dictionary graphs containing tuples, byte
strings and explicitly boxed floats. Across three epochs it checks payloads,
creates holes by dropping alternate roots, collects, and refills them. This
exercises mixed scalar/non-scalar maps, slot reuse and long pending chains.
It also passes the preceding implementation. Existing tests cover deferred
objects, old slots, young buffers, fallback/resurrection, abandoned owners and
small through huge allocator pages.

Debug and NaN-boxing-OFF Debug each passed 291 focused tests (16 skips in OFF).
Native FT and JIT each passed 807 tests (9 skips), plus 55 repeated methods.
The broad Debug run retained exactly the preceding 32 failure names and 69 skips
among 2,912 tests. This is not a claim that compatibility is complete, or that
the earlier rejected purge prototype's unexplained failure has been fixed.

### Measurements and remaining limits

The comparator is section 12's fused preparation, without section 13's rejected
purge code. Build flags, workloads, separate FT/JIT configurations and measurement
method were unchanged: isolated fresh processes, alternating order, discarded
warmup, fixed affinity/hash seed and the default allocator. Both nursery options
were enabled. Each comparison below uses its own matched baseline. All result,
native-JIT and bounded-retention assertions passed.

| Comparison | Mode | Median seconds, before → after | Peak MiB, before → after |
| --- | --- | ---: | ---: |
| 5 processes per configuration | FT | 3.045740 → 2.979494 | 81.527 → 75.840 |
| 5 processes per configuration | JIT-enabled | 4.518280 → 4.404221 | 65.848 → 62.469 |
| Independent 7-process repeat | FT | 3.010239 → 2.957861 | 81.383 → 76.684 |
| Independent 7-process repeat | JIT-enabled | 4.383792 → 4.327875 | 66.914 → 62.434 |

The repeat shortened time about 1.7% in FT and 1.3% in JIT-enabled mode, while
reducing peak RSS about 5.8% and 6.7%. Reported GC time fell from 2.538982 to
2.492771 seconds in FT and 2.638818 to 2.579510 in JIT. Collection counts changed
619 → 618 in FT and stayed at 676 in JIT. Final allocated-block counts differed
by eight in FT and were identical in JIT. These are modest improvements on one
allocation-heavy workload, not a universal speedup or a halving of total memory.

Five-process ordinary-container controls were roughly 0.5–0.9% faster, with
identical collection and final block counts, and the same or lower peak RSS.
Float-local, n-body and serial buffer-reuse timings stayed close to their
comparators. The FT 100-million-integer loop was an exception: its first median
increased 1.370696 → 1.384371 seconds. A separate nine-process comparison measured
1.377278 → 1.384452 seconds, about 0.5% slower, with overlapping ranges. Both had
zero timed collections. The cause is unproven; the result is retained as a
limitation, not explained away as collector overhead or corrected by code-layout
tuning. The corresponding JIT integer control stayed essentially flat.

Explicit full-GC controls also passed. Eight collections of 210,000 live lists
measured 0.084229 → 0.082456 seconds in FT and 0.084241 → 0.082330 in the
GIL-enabled configuration, with peak RSS 0.75 MiB lower in each. The analogous
20,000-live-dictionary control changed less than 1%, with essentially unchanged
peak memory. These C-heavy collection loops had no native executor code.
Short parallel buffer reuse had overlapping timing ranges: 0.018711 → 0.018394
seconds in FT and 0.060931 → 0.061419 in the GIL-enabled configuration. It likewise
had no native executor code and does not establish a general parallel speedup.

The two-byte maps are retained for their repeated primary time/memory gains,
modest ordinary-container gains and validation, with the numerical limitation
above. The same primary repeat measured RC FT at 0.425462 seconds / 16.125 MiB
and conventional GIL-enabled RC JIT at 1.189588 seconds / 15.125 MiB. Tracing still
took about 7.0x and 3.6x those times, and four to five times their peak memory.
The RC JIT comparator remains an older preserved build; these are end-to-end
configuration comparisons, not isolated collector costs. The overall objective
is still unmet.

Evidence is preserved in `/tmp/gc-halfmarks-{reclaim1,reclaim2,controls1}.json`,
`/tmp/gc-halfmarks-integer2.json`, `/tmp/gc-halfmarks-full1.json`, their logs and
`/tmp/gc-halfmarks-progress.md`. No timing overlapped builds, tests, profiling or
other benchmark runs.

## 15. Dictionary destruction-watcher resurrection and pyperformance

### Correct watcher ordering and a second resurrection pass

The tracing collector's resurrection protocol had one remaining unsafe callback.
`dict_dealloc()` sends its destruction-watcher event after the collector's last
root scan. A watcher that saved the dictionary in a Python list therefore left a
freed dictionary reachable from that list. The Debug reproducer crashed with a
poisoned type pointer; the reference-counting collector preserved all 32 watched
dictionaries.

The checkpoint attempted to notify watchers from `finalize_garbage()`. Although
that avoided the use-after-free, it sent the event before a dictionary subtype's
finalizer. Ordinary `subtype_dealloc()` runs that finalizer before calling the
base dictionary deallocator, so a `__del__` method that unwatched its dictionary
incorrectly received a destruction event.

The retained implementation first runs finalizers and performs the existing root
rescan. Only still-dead watched dictionaries are then notified while mutators may
run. The world is stopped a second time and roots are scanned again, rescuing
dictionaries published by watcher callbacks. Watcher bits are cleared only from
dictionaries that remain dead after this second scan, preventing the real
`dict_dealloc()` from sending an event after the final resurrection check.
Finalizer resurrection and unwatching are therefore visible before notification,
while watcher resurrection retains the dictionary's contents and watcher state.

The regression test allocates and releases its candidates in worker threads that
exit. This is necessary because stale values in a completed Python data stack are
valid conservative roots even when no Python reference remains; those values had
caused the checkpoint test's missing second notification. The test checks intact
contents, reuse after resurrection, a later destruction notification, explicit
unwatching, and a dictionary-subclass `__del__` that unwatches before the event.

The complete Debug experimental tracing-GC module passed all 173 tests. The new
test also passed the optimized FT configuration and the optimized JIT-enabled
configuration. In the latter, the existing JIT stack-root test observed active
native traces and native JIT code. The original ctypes reproducer preserved all
32 dictionaries in both Debug and optimized FT runs. A non-tracing build compiled
`Python/gc_free_threading.o`. The broader watcher suites still have pre-existing
tracing-GC compatibility failures for immediate destruction notifications; this
is not a claim that every watcher semantic is implemented.

### End-to-end comparison with main

pyperformance 1.14.0 and pyperf 2.10.0 ran 20 selected benchmark groups on CPU 2
with hash seed zero and `--fast`. Both sides used GCC `-O3` without PGO or LTO.
The main source was `c8da735f4f05`; the experimental side matched watcher-fix
commit `901122c50b0`. FT used free-threaded binaries with the GIL and JIT off.
The JIT comparison used a conventional GIL main build and the experimental
free-threaded build with its GIL restored. Separate tests proved native JIT
execution in both JIT comparators. Both tracing nursery options were enabled.

The FT runs used ten worker processes with two measured values each; JIT used
three workers with six measured values each. Every worker had one warmup, in
addition to a calibration run. Multi-result groups expanded the main suite to 28
subbenchmarks. Tracing produced comparable timings for 26. For each common
benchmark, the ratio below is its mean tracing time divided by its mean main time;
the aggregate is the geometric mean of those 26 ratios.

| Mode | Common results | Geometric mean | Slower / faster | Missing on tracing |
| --- | ---: | ---: | ---: | --- |
| FT | 26 | **2.050x** | 24 / 2 | `create_gc_cycles`, `gc_traversal` |
| JIT | 26 | **2.559x** | 26 / 0 | same |

The largest FT ratios were `pickle` 3.27x, `deepcopy` 3.14x and
`deepcopy_reduce` 3.08x. `float` was 0.936x and `nbody` 0.915x. In the valid JIT
comparison, every common benchmark was slower: `deepcopy_reduce` 4.18x,
`deepcopy` 4.08x, `regex_compile` 3.97x, `pickle` 3.52x and `pathlib` 3.43x were
the largest ratios.

The two missing GC benchmarks rejected tracing semantics before timing.
`gc_collect` asserts a minimum returned collection count, while `gc_traversal`
asserts that the returned count is zero. Conservative stale roots can defer some
of the intended cycles, and a tracing pass can collect unrelated garbage, so the
respective assertions failed during calibration. The benchmark sources and
assertions were not weakened to manufacture timings.

This is an end-to-end branch/configuration comparison. The experimental branch
also changes object representation, immediate integers, NaN boxing and JIT
support, so the ratios do not isolate tracing-GC cost. Some `--fast` results have
pyperf stability warnings. Raw suites and comparison CSV files are under
`/tmp/pyperformance-gc-results.wgIXfy/`. An initial main run used a free-threaded
build with the GIL restored; its JIT was enabled but never active. That invalid
run is retained as `main-jit-inactive.json` and excluded from every result above.

## 16. Follow-up: split precise typed-object marking

Profiling a callback-free `deepcopy` full collection attributed about 6.6% of
self samples to `tracing_mark_address` and another 3.3% to `tracing_visit`.
Precise `tp_traverse` visitors provide valid `PyObject *` references, but the
shared marking function still handled them like arbitrary words: it checked
interior-pointer padding, identified young auxiliary buffers, and repeatedly
combined typed and untyped byte-accounting rules.

The retained change separates marking after the page lookup. Typed object pages
use a helper that only handles scalar leaves or pending container traversal and
sets the object's alive bit. Untyped auxiliary allocations retain their own
young-buffer and accounting rules. Conservative stack, register and object-body
words still use the general address function, including tag removal and padding
validation. A precise reference to an object allocated on an untyped page also
keeps the untyped path. No mark state, reachability policy, nursery budget or
reclamation order changed.

Five pyperformance implementations that were expensive in the branch comparison
were called with their standard loop bodies: `deepcopy`, `deepcopy_reduce`,
`deepcopy_memo`, `pickle` and `regex_compile`. The comparator was the committed
watcher fix. Each automatic-GC result is the median of five isolated processes,
with version order alternated, CPU 2, hash seed zero, the normal allocator and
the nursery disabled. A later audit found that the driver set the nonexistent
`PYTHON_GC_NURSERY=1` variable rather than either tracing-GC nursery variable.
The measurements therefore remain valid comparisons of the full-GC marking
change, but they are not nursery-enabled results. Each process measured eight
values after an untimed warmup. Collection counts matched within every pair.

| Mode | Geometric mean of five elapsed-time ratios | Largest improvements | Small regressions |
| --- | ---: | --- | --- |
| FT | **0.9926x** | `deepcopy_memo` 0.9728x; `pickle` 0.9922x | `deepcopy` 1.0012x; `deepcopy_reduce` 1.0020x |
| JIT-enabled | **0.9944x** | `deepcopy` 0.9887x; `pickle` 0.9924x | `regex_compile` 1.0032x |

The JIT `regex_compile` collector duration improved to 0.9914x despite its
0.3% total-time increase. A separate explicit-full-GC comparison improved all
five FT collector medians to 0.9556--0.9945x. Three JIT medians improved, while
two measured 1.0019x and 1.0192x. These small workload-specific changes do not
establish a universal speedup, but the automatic-GC aggregate improved in both
supported modes and the code change targets the profiled mark path directly.

The Debug tracing-GC module passed all 173 tests. Native FT and JIT each passed
172 of 173; the sole `test_set_bulk_release` failure is also reproducible in the
unchanged native comparator and depends on conservative stale-root retention.
The JIT validation observed both an enabled JIT and execution inside an active
native trace.

Two smaller marking and scheduling trials were rejected. Branching to a shift
for power-of-two allocation strides made all five explicit JIT collection
medians 0.5--1.6% slower. Increasing the container-nursery failure backoff from
four to sixteen full collections did not change automatic collection counts and
made FT `deepcopy_reduce` 3.4% slower in the screening run. A cursor optimization,
conditional alive-bit clearing and a fused heap-classification experiment also
failed their performance or maintenance gates and were removed.

## 17. Why tracing remains much slower than reference counting

The collector cost was isolated at source revision `2a7c7a505dc`. New builds
used conventional reference counting, tracing without NaN boxing, and the
current tracing configuration with NaN boxing. The free-threaded comparison has
the same `--disable-gil` object layout in all builds and is the cleanest collector
comparison. The RC JIT comparator is a conventional-GIL build, so that result
also contains layout and optimizer differences. Five expensive pyperformance
loop bodies were run for eight values in five fresh processes per configuration,
with alternating order, CPU 2, hash seed zero and the normal allocator. The
table reports geometric means across workloads; the GC columns are medians.

| Mode | Tracing configuration | Elapsed / RC | Residual after reported GC / RC | GC share of elapsed | Share of excess explained by GC | Peak RSS / RC |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| FT | no NaN boxing | **2.455x** | 1.178x | 55.2% | 88.4% | 1.803x |
| FT | NaN boxing | **2.569x** | 1.300x | 52.9% | 81.3% | 1.806x |
| JIT-enabled | no NaN boxing | **2.924x** | 1.323x | 58.4% | 84.0% | 2.195x |
| JIT-enabled | NaN boxing | **3.177x** | 1.556x | 52.1% | 73.3% | 2.152x |

Scheduling and repeated full-heap work are the primary cause. Reference counting
destroys short-lived acyclic objects as soon as their count reaches zero and
subtracts deallocations from the cyclic collector's allocation count. It ran
zero cyclic collections in every measured interval. Tracing accounts gross
allocated bytes in the allocator and does not reclaim those objects until a
collection. It ran 24--92 collections over the same work, mostly taking a heap
snapshot, marking roots, traversing typed objects, classifying dead allocations,
and clearing and freeing them. Reported GC time alone explains a median 73--88%
of the excess over RC.

Hardware counters on the FT `deepcopy` profile reinforce that result. Relative
to RC, tracing without NaN boxing used 2.51x cycles, 1.63x instructions, 5.85x
branch misses, 29.7x cache references, 62.0x cache misses and 5.40x page faults.
IPC fell from 3.33 to 2.15. Self samples were distributed across the collection
pipeline: `gc_collect_main_impl` 9.5%, snapshotting 4.3%, address marking 4.2%,
garbage deletion 3.9%, heap scanning 3.5%, root marking 3.3%, and typed and dict
traversal about 2.5% each. No single helper dominates; repeatedly touching the
whole heap creates the instruction, branch and cache cost.

Enabling the real nursery variables did not help these workloads. The elapsed
ON/OFF geometric mean was 1.057x FT and 1.107x JIT without NaN boxing, and 1.069x
FT and 1.093x JIT with it. The FT `deepcopy` nursery run incurred 36.2x the RC
page faults and 6.70x the nursery-off tracing faults. It paid soft-dirty page
protection and snapshot costs, then fell back to a full collection.

The container nursery directly accepts only exact lists, exact tuples and
unwatched exact dictionaries. A census with collection disabled estimated that
47--58% of newly created tracked objects in the five workloads were unsupported.
They included frames, exceptions and tracebacks, iterators, bound and builtin
methods, user instances, Picklers, and regular-expression generators,
`SubPattern` and `Pattern` objects. When unsupported young bodies exceed one
eighth of the full-GC budget, the snapshot changes to a full fallback and starts
a four-full-collection backoff. An instrumented `deepcopy` run repeatedly crossed
that limit by a small amount and recorded no successful minor collection.

A separate delayed-reclamation stress disabled GC after warmup and ran one
measured value. Without NaN boxing, tracing took 1.465x RC in FT and 1.663x in
JIT, while peak RSS was 3.93x and 4.68x. This is not a pure instruction-only
mutator comparison: it intentionally includes storage that RC immediately
destroys and reuses but tracing retains until collection. Together with the
1.178x FT residual under automatic collection, it identifies allocation
accounting, delayed-reclamation allocator/cache pressure, and representation
and dispatch costs as secondary causes. NaN boxing is not the central gap, but
it added 1.046x FT and 1.087x JIT to these five nursery-off tracing workloads.

The next material optimization needs to reduce full collection frequency or
scope: a young heap that covers common builtin and user objects with reliable
write/dirty tracking, scheduling informed by collection yield and RSS, and less
memory traffic in full snapshot/mark/sweep. Further isolated helper tuning cannot
recover the majority of the measured gap. Until unsupported coverage improves,
the soft-dirty nursery should reject unsuitable attempts early rather than add
fault and snapshot cost before the same full collection.

## 18. Remove the initial full-mark header-clear pass

The full snapshot previously cleared `ALIVE` in every non-leaf header. Marking
set it again on reachable objects, and GC-heap classification usually cleared
it a second time. No object is staged as `UNREACHABLE` when the initial root
mark begins. The retained change therefore reuses `UNREACHABLE` as a temporary
reachability bit while the world is stopped. The existing GC-heap
classification visit reads it and produces the normal reachable or unreachable
state. The post-finalizer resurrection pass still clears and uses `ALIVE` as
before. Scalar leaves continue to use their snapshot map. This removes one
whole-heap header pass from the common initial full collection.

An unsafe first prototype tried to allocate bit 7 of `ob_gc_bits` for this
state. It crashed in `PyBuffer_Release()` after collecting live bytes owned by a
memoryview. A GDB watchpoint traced the destruction to `tracing_delete_leaf()`.
Bit 7 was already `_Py_TRACING_GC_SHARED_BIT`, the sticky multiple-owner state,
so shared objects were mistaken for marked objects. That prototype was removed;
the retained implementation assumes no unused header bit.

The comparator was typed-mark commit `2a7c7a505dc`. Five standard pyperformance
loop bodies ran for eight values in five fresh processes per version, with
alternating order, CPU 2, hash seed zero, the normal allocator and the nursery
disabled. Ratios are candidate divided by comparator, geometrically averaged
over `deepcopy`, `deepcopy_reduce`, `deepcopy_memo`, `pickle` and
`regex_compile`.

| Mode | Automatic elapsed | Reported automatic GC | Peak RSS |
| --- | ---: | ---: | ---: |
| FT | **0.9843x** | **0.9591x** | 1.0291x |
| JIT-enabled | **0.9777x** | **0.9574x** | 1.0022x |

The FT RSS aggregate is caused by one fewer terminal `deepcopy` collection:
49.8 MiB became 57.5 MiB, while the other four workloads were unchanged. A
separate explicit-full-GC comparison fixed the count at five collections per
process. Collection time was **0.9466x** FT and **0.9446x** JIT, with RSS at
1.0001x and 0.9905x. A four-worker, sixteen-batch, one-million-container stress
also improved: FT elapsed/GC/RSS were 0.9716x/0.9692x/0.9717x, while JIT was
0.9799x/0.9752x/0.9991x. The isolated terminal RSS result was therefore not
treated as a general memory regression.

The Debug focused module passed all 173 tests. Native FT and JIT each passed 172
of 173; the sole `test_set_bulk_release` failure is reproducible in the
comparator. Native JIT execution became active. Non-tracing and non-NaN-boxing
objects compiled, and the complete Debug and native builds checked 116 modules
with no import failures.

Raising the full-GC threshold from 2,000 to 4,000 was rejected separately. It
reduced the five-workload elapsed aggregate to 0.9488x FT and 0.9604x JIT, but
the four-worker stress raised peak RSS from 193.98 to 222.10 MiB FT and from
60.53 to 101.75 MiB JIT. That trade merely delays collection and worsens the
retention cost identified in section 17.

## 19. Use snapshot marks for initial precise visits

After section 18's change, a profile still attributed 7.16% of self samples to
`tracing_visit.part.0`. Its largest local sample site loaded `ob_gc_bits` from
each referenced object to reject an already marked container before the page
lookup. The initial full mark already maintains a dense snapshot map whose slot
states distinguish unmarked, pending and reached allocations. That map is the
authoritative duplicate check for scalar leaves and auxiliary allocations as
well.

The retained change lets every initial precise visit use the snapshot map and
avoids loading the referenced object's header. Resurrection and nursery passes
keep the `ALIVE` header shortcut. Reachability, reclamation order, collection
thresholds and the map state machine are unchanged.

The comparator was initial-mark commit `45d88d7530e`. The same five workloads
and controls as section 18 ran for eight values in five fresh processes per
version. Ratios are candidate divided by comparator and geometrically averaged.

| Mode | Automatic elapsed | Reported automatic GC | Peak RSS |
| --- | ---: | ---: | ---: |
| FT | **0.9695x** | **0.9359x** | 1.0029x |
| JIT-enabled | **0.9710x** | **0.9422x** | 0.9992x |

Elapsed and GC duration improved in all ten workload-mode pairs. With exactly
five explicit full collections per process, collection time was 0.9746x FT and
0.9878x JIT; RSS was 0.9992x and 1.0007x. A four-worker, sixteen-batch,
one-million-container stress measured elapsed/GC ratios of 0.9666x/0.9614x FT
and 0.9783x/0.9690x JIT. JIT RSS was 0.9940x. The FT candidate ran 1.038x as
many collections but had a lower median peak RSS, so the stress did not show a
memory regression.

A supplementary candidate profile attributed 5.48% of self samples to
`tracing_visit.part.0`; annotation confirmed that the initial path skipped the
referenced-object header load. The Debug focused module passed all 173 tests.
Native FT and JIT each passed 172 of 173, with only the comparator-reproducible
`test_set_bulk_release` failure. Complete Debug and native builds checked 116
modules with no import failures.

## 20. Classify the heap from the retained snapshot map

The initial mark map already distinguishes free, unmarked, pending and reached
slots. The implementation nevertheless wrote `UNREACHABLE` into each reached
non-leaf header during marking, then called `gc_visit_heaps()` to enumerate the
allocator again, read those headers and build the collector worklists. The
retained change classifies non-leaf objects directly from the map after pending
traversal drains. It removes both the random temporary-header writes and the
second allocator heap visit. Resurrection still uses `ALIVE` headers because
finalizers may mutate the graph after the initial map has been released.

An initial version classified the address-sorted pages directly. That changed
deallocation and freelist-reuse order, made automatic collection counts diverge
between versions, and regressed the explicit-full-GC JIT geometric mean to
1.0409x. The snapshot now records the allocator's prior order: each thread's GC
heap followed by its preheader heap, then the abandoned GC and preheader heaps.
After marking, pages return to that order before classification. All ten pairs
in the screening run then had matching collection counts.

The comparator was snapshot-visit commit `2aa8452100e`. The same five workloads
and controls as section 19 ran for eight values in five fresh processes per
version. Ratios are candidate divided by comparator and geometrically averaged.

| Mode | Automatic elapsed | Reported automatic GC | Peak RSS |
| --- | ---: | ---: | ---: |
| FT | **0.9894x** | **0.9850x** | 1.0010x |
| JIT-enabled | **0.9953x** | **0.9882x** | 1.0035x |

Reported GC time improved in all ten workload-mode pairs. JIT
`regex_compile` was the only elapsed-time regression at 1.0033x, while its GC
duration improved to 0.9937x. A short repeat after the final code layout gave
elapsed ratios of 0.9922x FT and 0.9946x JIT, with GC ratios of 0.9889x and
0.9891x. Five explicit full collections per process measured collection time
at 0.9981x FT and 0.9966x JIT; RSS was 1.0001x and 1.0023x.

The four-worker stress improved elapsed/GC/RSS to
0.9856x/0.9822x/0.8981x FT and 0.9725x/0.9673x/0.9713x JIT. A supplementary
profile no longer contained `scan_heap_visitor`; classification was folded
into `tracing_mark_roots`.

The Debug focused module passed all 173 tests. Native FT and JIT each passed 172
of 173, with only the comparator-reproducible `test_set_bulk_release` failure;
native JIT execution became active. Non-tracing and non-NaN-boxing objects
compiled, and the complete Debug and native builds checked 116 modules with no
import failures.

A smaller trial retained the separate heap visit but combined its temporary
mark cleanup and final classification into one header write. Automatic GC time
was 0.9989x FT and 0.9999x JIT, while elapsed time was 1.0005x and 1.0024x. It
provided no useful speedup and was removed.

## 21. Final pyperformance rerun against main

The end-to-end comparison in section 15 was rerun after all retained
optimizations through commit `3bcdb09e4b9`. The saved main baselines remained
commit `c8da735f4f05`; the benchmark checkout, CPU 2 affinity, hash seed zero,
GCC `-O3` builds without PGO/LTO, pyperformance 1.14.0, pyperf 2.10.0 and
`--fast` selection were unchanged. The tracing nursery's soft-dirty and young
container options were enabled. FT ran with the GIL and JIT disabled; JIT ran
with the GIL restored and native JIT active.

The 20 selected groups again yielded 26 common subbenchmarks. Ratios are the
new tracing mean divided by the saved main mean, and the aggregate is their
geometric mean.

| Mode | Common results | Geometric mean | Slower / faster | Missing on tracing |
| --- | ---: | ---: | ---: | --- |
| FT | 26 | **2.073x** | 24 / 2 | `create_gc_cycles`, `gc_traversal` |
| JIT | 26 | **2.559x** | 26 / 0 | same |

The largest FT ratios were `pickle` 3.28x, `pathlib` 3.16x,
`regex_compile` 3.16x, `deepcopy` 3.12x and `deepcopy_reduce` 2.94x. `nbody`
and `float` were 0.949x and 0.983x. The largest JIT ratios were
`regex_compile` 3.92x, `deepcopy_reduce` 3.89x, `deepcopy` 3.77x, `pickle`
3.52x and `pathlib` 3.44x; all 26 were slower.

The earlier watcher-fix run measured 2.050x FT and 2.559x JIT. The final FT
aggregate moved by about one percent in a separate `--fast` run, while the JIT
aggregate was unchanged. Several final results emitted pyperf stability
warnings. This non-interleaved suite comparison is therefore retained as the
current end-to-end result, not as an estimate of the individual optimizations;
sections 18--20 use alternating, repeated candidate/comparator runs for those
estimates.

The two GC-specific benchmarks still failed their collection-count assertions
before timing, for the tracing-semantics reason described in section 15. Their
assertions were not changed. Raw suites are
`/tmp/pyperformance-gc-results.wgIXfy/final-tracing-{ft,jit}.json`; per-benchmark
ratios and the aggregate are in `final-compare-{ft,jit}.csv` and
`final-compare-summary.json` in the same directory.

## 22. Expand nursery type coverage and collect completed generators

The reference-counting comparison in section 17 identified delayed reclamation
as the largest remaining cost. The original container nursery only accepted
exact lists, exact tuples and unwatched exact dictionaries. Object censuses of
the five diagnostic workloads found that 47--58% of newly tracked objects were
unsupported. Frames, methods, C functions, tracebacks, iterators, exceptions,
Python instances, picklers and generators repeatedly exhausted the unsupported
body budget, converted attempted minors into full collections, and entered the
four-full-collection backoff.

Commit `f08a66295e8` adds types whose young destruction cannot run a callback:
selected exact builtin iterators and views, slices, enumerate/map/zip, common
exact exceptions, and frames, C functions and methods without weak references.
Pure Python heap types are accepted only when `subtype_dealloc` resolves to an
`object_dealloc` base; C-extension bases are rejected. Finalizers, `tp_del` and
actual weak references remain full-collection-only. `_pickle.Pickler` explicitly
opts in. List iterators were left out because enabling them substantially
increased conservative temporary retention in an existing shared-storage test.

Commit `22ab6381f8d` additionally accepts exact generators only after their frame
state is `FRAME_CLEARED`. Finalization is a no-op in that state. Suspended
generators remain excluded because collection can execute `finally` blocks. A
regression test verifies that a suspended generator cycle survives a minor and
is finalized by a subsequent full collection.

In alternating five-workload screening against `3bcdb09e4b9`, the type expansion
reduced FT elapsed time to 0.874x for `deepcopy`, 0.779x for
`deepcopy_reduce`, and 0.766x for `pickle`. The JIT-enabled ratios were 0.870x,
0.779x and 0.821x. `deepcopy_memo` was nearly neutral at 0.991x/0.978x;
`regex_compile` was 1.022x/1.048x. Comparing the completed-generator change
directly with the type-expansion build put `regex_compile` at 0.996x FT and
0.954x JIT, with reported GC time at 0.958x and 0.895x.

The retained changes reduce the number of short-lived allocations held until a
full collection; they do not reduce the allocations requested by Python code.
Peak RSS in the short type-expansion runs varied from 1.03x to 1.39x because
fewer full collections allowed more data to remain until the next minor. Trials
that set the next allocation budget to one half of live bytes reduced RSS by
about 20% but generally slowed elapsed time by 11--24%. Three quarters reduced
RSS by 9--18% but slowed time by 5--11% and GC time by 10--24%. Reducing the
periodic-full limit from seven minors to three did not produce a consistent RSS
gain and slowed `deepcopy_reduce` by 6.8% FT and 11.5% JIT. These scheduling
changes were removed.

The next memory optimization should make each minor cheaper before increasing
its frequency. An old-to-young write barrier and card table could replace Linux
soft-dirty page faults and broad old-heap rescanning with dirty-card scanning.
Only after that change is a smaller allocation budget likely to reduce retained
memory without the measured time penalty. Further exact callback-free C types,
type-specific ownership for young private buffers, and quicker allocator page
reuse or purge are secondary opportunities.

The new eight focused tests passed. The native tracing module passed 175 of 176
tests; the only failure, `test_set_bulk_release`, also reproduced with the saved
pre-change executable.

The end-to-end pyperformance run used the same saved main `c8da735f4f05`
baselines, 20 groups, CPU 2, hash seed zero, GCC `-O3` builds without PGO/LTO,
pyperformance 1.14.0, pyperf 2.10.0 and `--fast` settings as section 21. Across
the same 26 common subbenchmarks, tracing/main improved from 2.073x to
**1.985x** FT and from 2.559x to **2.479x** JIT. The new/old-tracing geometric
means were 0.957x and 0.969x. `deepcopy_reduce`, `pickle`, and `deepcopy`
improved to 0.815x/0.778x, 0.846x/0.810x, and 0.855x/0.874x in FT/JIT. The JIT
`regex_compile` suite result was 1.038x with a 12% standard deviation, whereas
the alternating generator-only comparison was 0.954x; the latter is the better
estimate of that individual change.

The two GC-specific benchmarks still rejected conservative collection-count
semantics before timing. Raw suites are
`/tmp/pyperformance-gc-results.wgIXfy/nurserytypes-tracing-{ft,jit}.json`;
per-benchmark ratios and the summary are in the corresponding
`nurserytypes-compare-{ft,jit}.csv` and `nurserytypes-compare-summary.json`.
