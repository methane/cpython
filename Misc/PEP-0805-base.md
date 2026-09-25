# PEP 805 runtime foundations

This branch, `codex/pep805-base`, isolates the first five stages of the
[implementation strategy](https://peps.python.org/pep-0805/appendix-implementation/#implementation-strategy)
from `experimental/pep-805` at `9a4de37db8`. Its CPython base is
`6dad8b88cc39d8f9f41c22502a0b52304b326dd9`.

The specification is [PEP 805](https://peps.python.org/pep-0805/) and its
[implementation appendix](https://peps.python.org/pep-0805/appendix-implementation/).
The five-stage implementation is **not complete**.

| Stage | Current implementation | Remaining work |
| --- | --- | --- |
| ThreadGroups | Group selection, serialization, detach/reattach, native identity, fork and Main lifetime | Parallel execution in the normal build |
| One-time ABI change | Compact owner/state and group-biased RC header; no cleanup queue fields | Complete the allocation/GC port and audit native layouts |
| Biased and deferred reference counting | Group bias, per-thread code counts, deferred stack roots and normal GC integration | Queue collection and reclamation with concurrent groups |
| LOCAL and IMMUTABLE ownership | Builtin/static metadata, public `__shareable__` state, common C API returns, VM heap loads, attributes and call expansion | Remaining API/VM acquisitions and migration of static extension types |
| Parallel allocation and cyclic GC | Per-thread heaps/freelists and bytecode, QSBR, paused reachability snapshots, owned worklists and synchronized tracking | Concurrent execution, owner-correct finalization, cross-interpreter legacy objects and teardown |

Freezing, protective/compound locks, synchronized objects and functions,
TransferBox, Channel, the debugger StopTheWorld API, and performance work are
later stages and excluded. Internal GC world stops belong to the runtime port.
Windows and native machine-code JIT validation are deferred.

## Runtime configuration and layout

Build normally, for example `./configure --with-pydebug && make -j8`.
`Py_GIL_DISABLED` is zero; the interpreter GIL remains enabled during the port.
Selecting `--disable-gil` is not the implementation of stages three and five.
The old free-threading backend still assumes OS-thread IDs and a larger local
counter and is not compatible with this intermediate header.

The reference-counting bias belongs to a **ThreadGroup**, not an OS thread.
Objects retain their owner IDs on merging, resurrection and creator-thread
exit. A 64-bit `PyObject` occupies 24 bytes: a 32-bit owner/bias ID, an 8-bit local
count, state, flags and GC bits, a pointer-sized shared count and a type pointer.
The shared count retains PEP 703's two flag bits. Local overflow merges the
count into the shared field instead of making the object immortal.
There is no object mutex, OS-thread ID or deferred-cleanup linkage in the header.
GC-tracked objects currently retain the normal collector's separate GC prefix.
Tracking and finalization status use the existing `ob_gc_bits` byte, with
atomic read-modify-write updates that preserve other flags. The GC prefix holds
list links and temporary reachability counts, not finalization state.

Object freelists are per-thread in the normal build too. Full GC clears all
thread caches, and thread-state clearing disables the target state's caches,
including when another thread performs the cleanup. The underlying allocator
and collector still require the interpreter GIL; this is preparation for their
parallel implementation.

With `PYTHONMALLOC=mimalloc` or `mimalloc_debug`, the normal build uses the
ported per-thread heaps, separated by object/GC/preheader layout. Exiting threads
abandon their live allocations to an interpreter pool; allocation accounting
includes other threads and abandoned blocks. Heap selection is scoped to each
allocator call, including recursive embedding/tracing hooks. Allocator ownership
is independent of the object's ThreadGroup owner and reference-count bias.
The default remains pymalloc while parallel heap tracking is being implemented.

Audit hooks and interpreter views that span initialization use the non-swappable
raw allocator. Its debug backend is also independent of runtime allocator
configuration, so `PYTHONMALLOC` changes cannot mismatch allocation and freeing.

Internal per-interpreter and process-wide stop-the-world operations are active
in the normal build. Detached states, including states created during a pause,
cannot attach until it ends. Attachment drops group/GIL execution rights before
waiting on a suspended state. Fork, shutdown and existing introspection callers
use this mechanism; the later-stage public debugger API is not exposed.

QSBR registration and quiescence are active in the normal build. Retired internal
buffers remain allocated until attached readers have passed a safepoint or
detached. GC drains all threads' queues while paused, including abandoned queues;
allocation failure falls back to a world stop. Fork and thread/interpreter
teardown maintain the reader registry. Replaced thread-local bytecode arrays
use this machinery. This is not proof of parallel execution. QSBR read epochs
belong to thread states; object reference-count bias still belongs to ThreadGroups.
The normal build does not defer LOCAL object decrefs through these queues.

Internal explicit-mutex critical sections are available in the normal build.
They suspend their locks on detach or a blocking nested acquisition, and resume
the innermost section on attachment. This allows shared runtime structures such
as code metadata to use dedicated locks without adding a mutex to every object.
The public object-based critical sections retain their normal-build behavior;
LOCAL objects rely on group serialization. A skipped two-mutex acquisition
during a world stop releases any first mutex acquired by its fast path.

Code objects use a dedicated mutex and acquire/release publication for their
lazy variable-name and bytecode caches. `co_extra` growth publishes a copied
array and retires the old array through QSBR; extra-slot registration uses the
interpreter's code-state mutex. Replaced extra values are still released after
unlocking, so extension free callbacks can re-enter. On Linux/aarch64 the mutex
occupies existing code-object padding; the generic object header remains 24 bytes.

Immutable strings publish their lazy UTF-8 cache with an atomic compare/exchange.
Competing encoders preserve the first buffer, whose address may already be held
by a C caller, and free the redundant allocation. The cache length is published
before the pointer; readers acquire the pointer before using the length.
String, bytes, tuple, frozenset and frozendict hash caches use atomic accesses
in the normal build. A cold frozendict hash checks acquired values before
invoking their hash callbacks; cached container hashes and stored key hashes
do not acquire the elements. Unicode interning and other shared runtime caches
still require a concurrency port before groups can execute in parallel.
The interning-state byte is now separate from Unicode's immutable bit fields,
with atomic publication and reads in both builds. Mortal interning and canonical
identity are preserved, including use by another group and survival after that
worker exits. The normal intern table still depends on the interpreter GIL:
parallel removal/retrieval of its uncounted references and conversion of a
group-biased mortal string to an immortal string need further coordination.

Thread-local bytecode is active in the normal build, including thread lifecycle,
frame migration, generator throws and specialization. `-X tlbc=0` and
`PYTHON_TLBC=0` disable both copies and specialization. Monitoring updates all
copies under the code mutex or a world stop. Publishing tables and entries uses
acquire/release atomics; QSBR retirement happens after unlocking, since its OOM
fallback can suspend critical sections. These copies and their interpreter-local
indices belong to threads, independently of ThreadGroup reference-count bias.
Instrumentation versions are checked inside tracing callbacks too. Monitoring
preserves disabled specialization counters, and RESUME does not update them;
this also prevents audit callbacks from attempting to restart an unreachable
counter with `tlbc=0`. Threaded monitoring tests run in normal-build discovery.
Code objects gain one pointer for the copy table (224-byte basic size on
Linux/aarch64). Cache cleanup retains copies referenced by suspended generators,
coroutines, async generators and retained frames after their thread exits,
including frames in frozen GC generations. Remote unwinding uses the frame's
copy to resolve line numbers and refreshes lazily populated table entries.
This does not yet enable concurrent group execution or establish safe sharing of
code objects across interpreters.

The normal collector pauses threads while merging per-thread counts, scanning
stack roots, determining reachability and clearing callback-bearing weakrefs.
It restarts them for weakref callbacks, finalizers, debug output and destruction,
and pauses again to detect resurrection. Full collections also pause while
clearing all threads' freelists.
Heap introspection (`gc.get_objects()`, `gc.get_referrers()`,
`gc.get_referents()` and the native GC visitor) also pauses threads during its
walk. Existing GC freeze/unfreeze operations pause while moving generation
lists. Failed result allocation resumes threads before releasing partial results.
GC debug output holds a separate snapshot of strong references taken during a
pause. A reentrant `sys.stderr.write()` can reclaim cycle members without
invalidating the output walk. Snapshot references are released before checking
resurrection; no debug queue fields are added to object headers.
Finalization and destruction now use separate worklists holding strong references
to candidates. Those references are subtracted when computing resurrection, using
the existing unreachable bit to identify the collector's reference. Weakref
callback entries are all allocated before any weakref is cleared. Allocation
failure restores the generation lists and releases partial worklists with threads
running, preserving callbacks for a later collection. Legacy finalizer handling
also runs from an owned snapshot; list reconciliation happens during pauses.

Within an interpreter, tracking/untracking, allocation counters, configuration
and statistics use a GC mutex when threads are running. Nothing may detach,
stop the world or execute Python while holding it. Result construction and
destructors run after unlocking; heap-size observations use atomic counts.
This is not yet proof of concurrent collection: execution still uses the
interpreter GIL, and legacy extension objects shared across interpreters need
further ownership and list-lifetime work.
Shutdown merges/disables per-thread counts under a pause before releasing deferred
references. Shutdown list moves use the GC mutex, releasing it before dropping
sentinels that can execute destructors.
The free-threading collector reuses `ob_tid` as scratch space; its replacement
must preserve the compact header's group owner ID throughout collection.

Deferred counting is restricted to immutable GC-tracked objects. Per-thread
counts currently supplement the group bias for code objects; LOCAL heap types
and dictionaries use ordinary biased counts. The collector merges thread
counter tables before computing reachability and disables unique IDs before
finalization, including possible resurrection.

Uncounted VM and registered C stack references are GC roots. Older and frozen
heap frames also supply roots for younger collections. Unreachable heap frames
acquire counted references before finalization. Static immortal code objects
are excluded from GC-prefix access. Shutdown disables further deferral and
restores ordinary counts for survivors before late interpreter-dict cleanup.
The normal VM's borrowed-reference optimizations are retained.

Objects and types expose their state through the read-only `__shareable__`
descriptor. `threading.Shareable.LOCAL` and `.IMMUTABLE` are native immutable
singletons; reading the descriptor does not import `threading`. They support
identity comparison, a read-only `name`, and the PEP's `Shareable.LOCAL` repr.
No Python enum methods, mutable enum dictionaries, numeric enum contract or
later-stage sharing states are needed for this interface.

ThreadGroup is a managed static builtin type whose wrapper holds only an exact
string or None. Main survives interpreter dictionaries, finalizers and type
teardown. The public `PyInterpreterState_Clear()` path releases Main after
clearing the other interpreter state.

Reference acquisition accepts IMMUTABLE objects and LOCAL objects owned by the
current ThreadGroup. Rejected acquisitions raise `IllegalThreadAccessException`
without inspecting the foreign object's representation. C API checks apply to
acquired results; already-acquired arguments need no additional runtime check.
Extension objects remain LOCAL unless explicitly declared immutable. Static
extension objects can rebind to a new Main after their former interpreter has
been destroyed. `PyType_Ready()` also marks static types whose object headers
were zero-initialized, so they follow the same ownership rule. Each subinterpreter
will retain its own Main ThreadGroup. Static extension types will eventually
be replaced by types created separately for each interpreter; sharing Main or
adding an ownership exception for shared static types is not the chosen design.
Simultaneous use of the existing managed static extension types still has a
compatibility limitation until that migration; see the
[Japanese design notes](PEP-0805-open-questions-ja.md).

Weakref and proxy caches only reuse accessible objects. An immutable referent
can have separate LOCAL basic refs in multiple groups, and each group retains
its canonical ref/proxy while those references are alive. Public weakref getters
also check their acquired referents.

Public builtin-namespace getters and `PyImport_GetModuleDict()` check the
dictionary they return. A frameless native thread in another group cannot obtain
Main's LOCAL interpreter dictionaries. VM namespace storage still uses internal
references; individual values obtained from those namespaces are checked.

Tuple and list element operations check references before invoking repr, hash,
comparison or sorting callbacks. A local list copied from a shared tuple can
still contain foreign LOCAL elements. Sorting checks those elements and the
contents of tuple keys, including its specialized comparison path. Failed
acquisition preserves the list and releases temporary keys. Both the public
rich-comparison API and sorting's direct slot calls validate returned objects
before using their truth value. Container length, cached tuple hashes and
comparison paths that do not inspect an element need no element acquisition.
The tuple hash cache uses atomic reads and writes in the normal build too.

Hash-table lookup checks stored keys before invoking equality callbacks.
Dictionary repr, equality, item-view membership and item-view symmetric
difference check the keys and values they acquire. A shallow copy into a local
dictionary or set can still contain foreign LOCAL elements, so these checks
apply to mutable containers too. Missing hashes/keys and unequal dictionary
lengths can determine an answer without acquiring the unused elements.
Bulk set operations, dictionary merging and `fromkeys` also check source keys
before using them in lookups or insertions that can invoke comparisons.
Existing clone/pointer-copy paths still copy heap references without acquiring
elements, and copied dictionary values do not need acquisition just for copying.
Other C API/VM acquisition paths still need an audit.

Cross-group LOCAL reclamation still needs a choice of execution context,
especially after every thread in the owning group has exited. The immediate
GIL-serialized BRC merge is not an owner-correct finalization mechanism. The
Japanese questions record this separately from static extension ownership and
unchecked C macros. This execution-context decision is deferred until discussion
with Mark; a dedicated cleanup thread has not been adopted.

## Extraction provenance

`7201b6539e` was applied with `git cherry-pick --no-commit`. Since it mixes all
stages, only its ThreadGroup scheduler, native wrapper, thread-state integration
and Python group-selection changes were retained in the first split.

`d92bde8de7` was selectively applied for fixed GIL configuration during extension
imports and classic context-inheritance/warnings defaults. Its change to the
configure default was reverted in `a13a6f3a10`. Early validation using the
free-threading configuration did not establish the required normal-build port.
LOCAL reclamation guards and tests were selected from `a26d4fff4c`, again
excluding later-stage functionality.

## Validation

Tests run on Linux/aarch64. Logs are under `/tmp/pep805-base/`. The optional
`_decimal` module is unavailable. The native scheduling probes exchange raw
flags/events rather than foreign LOCAL Python functions or mutable results.
Parallel scheduling tests remain skipped while the interpreter GIL is enabled.

- Bulk hash-table acquisitions: 1,136 tests pass across ten files covering
  ownership, sets, dictionaries, dictionary views, C APIs, comparison, repr,
  unpacking and calls (two skips). Ownership and dictionary views pass `-R 3:3`
  with `mimalloc_debug` (56 tests). Native callback counters exposed 36 failures
  before the fixes, including reflected comparisons on inaccessible source keys.
  Tests cover shared immutable containers and their local mutable copies,
  same-group and foreign-group access, and both LOCAL and declared IMMUTABLE
  keys. Separate cases retain pointer-only cloning and copying of LOCAL values
  without invoking their callbacks.
- The non-debug normal build at `8fc12d73f3` passes 1,414 tests across 15 files
  covering Unicode interning, ownership, strings, code, monitoring, tracing,
  profiling, specialization, test support and embedding (38 skips). Its
  `tlbc=0` monitoring selection passes 599 tests (four skips), and its
  `mimalloc_debug` ownership/monitoring/bytecode selection passes 62 tests.
  `Py_GIL_DISABLED=0`, `Py_DEBUG=0`, and the interpreter GIL remains enabled;
  object, code and string basic sizes remain 24, 224 and 72 bytes respectively.
- Monitoring and thread-local bytecode: 828 tests pass across nine files covering
  monitoring, tracing, profiling, specialization, generated cases, ownership and
  evaluation APIs (one skip). The threaded monitoring and bytecode suites pass
  `-R 3:3` with `mimalloc_debug` (23 tests). Regressions first reproduced twelve
  failures with `tlbc=0`, including an audit-hook assertion failure and unwanted
  specialization after monitoring. The corrected disabled-copy configuration
  passes 599 tests across five files (four skips). The existing specialization
  requirement now also reads the runtime TLBC configuration; no assertions were
  removed from the specialization tests. Test-support, monitoring and bytecode
  suites pass another 186 tests with the default enabled configuration (six
  skips), including verification of the requirement in both configurations.
- Atomic Unicode interning state: 658 tests pass across 14 files covering
  ownership, sys, strings, Unicode C APIs, marshal, code, embedding, remote
  inspection and GDB (51 skips). Ownership and sys pass `-R 3:3` with
  `mimalloc_debug` (140 tests, seven skips). Native workers exercise mortal and
  immortal interning for all character widths, canonical identity across groups,
  survival after worker exit and reclamation of mortal strings. On Linux/aarch64,
  `str.__basicsize__` remains 72 bytes, and empty/non-ASCII sample string sizes
  match the preceding build. This validates metadata publication and existing
  lifecycle behavior; the intern-table concurrency port remains incomplete.
- The non-debug normal build at `3ca90372f0` passes 1,885 tests across 15 files
  covering immutable caches, ownership, ThreadGroups, strings, bytes, hashes,
  dictionaries, sets, views, comparison, repr, codecs and related C APIs
  (44 skips). Its `mimalloc_debug` selection passes 76 ownership, ThreadGroup
  and dictionary-view tests (two skips). `Py_GIL_DISABLED=0`, `Py_DEBUG=0`,
  and the interpreter GIL remains enabled; object and code basic sizes remain
  24 and 224 bytes. These results verify the ported paths with serialized
  execution, not parallel group execution.
- Hash-table acquisitions: 932 tests pass across eight files covering ownership,
  dicts/frozendicts, sets, dictionary views, comparison, repr and C APIs
  (two skips). Ownership and dictionary views pass `-R 3:3` with
  `mimalloc_debug` (52 tests). Before the fixes, native callback counters exposed
  11 key-lookup, 16 dictionary-operation and eight item-view symmetric-difference
  failures. Rejected operations now leave those callbacks untouched, including
  after copying a shared container into a local dict/set. Separate regressions
  retain lookups and comparisons that need no inaccessible element.
- Immutable caches: 1,821 tests pass across 12 files covering ownership,
  ThreadGroups, strings, bytes, sets, dicts, hashes, codecs and related C APIs
  (30 skips). Ownership and ThreadGroups pass `-R 3:3` with `mimalloc_debug`
  (56 tests, two skips). A native allocator hook pauses one UTF-8 cache creator
  until another publishes its buffer, then verifies both callers retain the
  first address and the redundant buffer is freed. All six publication cases
  failed before the fix. A separate cold frozendict hash regression exposed
  an unchecked foreign LOCAL value; the rejected callback now has no effects.
- Thread-local bytecode: 22 related test files pass, including frames,
  generators, monitoring, disassembly, remote inspection, configuration,
  embedding, threading and generated interpreter cases. New tests cover table
  growth with 32 live workers, retained/frozen heap frames, specialization in
  foreign groups and lazy debugger-cache population. The debugger regression
  returned line -1 before the fix. TLBC, ownership, ThreadGroups and deferred
  reclamation pass `-R 3:3` with `mimalloc_debug` (69 tests, two skips).
- The expanded selection exposed a pre-existing zero-header static-type
  ownership failure in `test_exceptions`, also reproduced in the earlier
  release build. After correcting `PyType_Ready()`, 555 tests pass across
  exceptions, ownership, types, descriptors, C API types and embedding
  (ten skips). The new ownership regression verifies the type belongs to Main
  and remains inaccessible to a foreign group.
- The non-debug normal build at `5335bbdef2` passes 831 tests across ten files
  covering TLBC, ownership, ThreadGroups, code, monitoring, remote inspection,
  exceptions, embedding, GC and internal critical sections (24 skips).
  `Py_GIL_DISABLED=0`, `Py_DEBUG=0`, and the interpreter GIL remains enabled;
  object and code basic sizes are 24 and 224 bytes respectively.
  The 13 existing threaded monitoring tests also pass when invoked directly
  in the debug normal build; their package still skips normal builds.
- Shared code metadata: 981 tests pass across ten files covering code objects,
  ownership, ThreadGroups, GC, C APIs, sys, monitoring, embedding, disassembly
  and frames (30 skips). Code, ownership and ThreadGroups also pass `-R 3:3`
  with `mimalloc_debug` (92 tests, three skips). The `co_extra` growth probe
  failed for both Main and foreign groups before the fix; it now verifies the
  retired array survives until quiescence and is then freed. A separate probe
  creates code caches in a foreign group before reading them from Main.
- Internal explicit-mutex critical sections: 743 tests pass across C API misc,
  ThreadGroups, GC, threading and embedding (16 skips). Native tests exercise
  recursive and nested blocking acquisition, suspension, innermost resumption,
  two-mutex ordering and identical mutexes, and skipped acquisition while the
  world is stopped. The latter covers an unavailable second mutex after the
  first was acquired, which previously left the first mutex locked.
- Normal-build QSBR: 804 tests pass across nine files covering ThreadGroups,
  GC, threading, fork, embedding, memory/thread-state APIs and reclamation
  (16 skips). ThreadGroups, ownership, GC and reclamation also pass `-R 3:3`
  with `mimalloc_debug` (128 tests, three skips). Native tests cover explicit
  quiescence, detach/reattach, eval-breaker processing, paused GC, exited and
  detached producers, allocation failure, registry growth and slot reuse.
  The eval-breaker probe shares immutable code and creates its function and
  globals in the worker's group; compiling there would invoke Main's LOCAL
  Python audit hooks, outside the first-five-stage scope.
- The non-debug normal build at `ebf2efe11b` passes 829 tests across ten files
  covering QSBR, threading, GC, reclamation, ownership, embedding, memory APIs
  and fork (32 skips). `Py_GIL_DISABLED=0`, `Py_DEBUG=0`, the interpreter GIL
  is enabled and the object header remains 24 bytes.
- Sequence element acquisition and comparison results: 1,716 tests pass across
  15 files covering tuples, lists, sorting, ownership, ThreadGroups, GC,
  weakrefs, comparison, descriptors, dictionaries, sets and C APIs (14 skips).
  Ownership and sorting also pass `-R 3:3` with `mimalloc_debug` (46 tests).
  Before the fix, all 20 initial foreign-element operations failed the new
  regressions. Native slot counters now verify rejected operations have no
  repr/hash/comparison/truth side effects. Tests also cover short circuits,
  cached hashes and restoration after sorting errors with stack/heap keys
  and reverse sorting. The initial broader run exposed a regression in
  uninitialized tuple repr; the existing C API test passes after preserving
  its NULL-element display behavior.
- The non-debug normal build at `1820814319` passes the same 1,716-test
  selection (21 skips), plus 46 ownership/sorting tests with `mimalloc_debug`.
  It retains `Py_GIL_DISABLED=0`, `Py_DEBUG=0`, an enabled interpreter GIL
  and a 24-byte object header.
- Owned GC worklists and tracking synchronization: 958 tests passed across
  GC, finalization, ThreadGroups, reclamation, weakrefs, embedding, threading,
  fork and C APIs (20 skips). GC, ThreadGroups and deferred reclamation pass
  `-R 3:3` with `mimalloc_debug` (97 tests, three skips). Tests cover retracking
  inside a finalizer, resurrection with and without retracking, GC API calls
  from callbacks, and failures in candidate/callback/debug worklist allocation.
  Failed preparation leaves callbacks pending; retry invokes every weakref
  callback and finalizer exactly once. The worklist-only build also passed
  a 699-test VM/frame/fork/C API selection (12 skips) and a 254-test leak
  selection including finalization and weakrefs (seven skips).
- The non-debug normal build at `1be617ada4` passes the same 958-test selection
  (36 skips). Its `mimalloc_debug` GC, ThreadGroup and deferred-reclamation
  selection passes 97 tests (four skips). A separate diagnostic found that
  forking while another thread is waiting inside a GC finalizer leaves the
  child unable to collect; the same diagnostic reproduces on unmodified
  Python 3.12.3. This is recorded as an existing multithreaded-fork limitation,
  not evidence of a regression introduced by the worklists.

- GC bitmap migration: 545 tests passed across ten files covering GC,
  ThreadGroups, ownership, weakrefs, reclamation, tuples, generators,
  async-generators and embedding (13 skips). GC and reclamation also pass
  `-R 3:3` with `mimalloc_debug` (76 tests, one skip). The new regression verifies
  that both refcount and cyclic resurrection finalize only once, even after
  untracking and retracking the surviving object.
- Paused heap introspection: the corrected GC, ThreadGroup and C API selection
  passes 399 tests (six skips). The preceding broader run also passes embedding,
  memory APIs, code, sys and fork; its sole failure was an argument-taking test
  helper incorrectly using the automatic `test_` naming convention, fixed before
  the successful rerun. Native probes verify paused traversal and both complete
  and early visitor returns. Memory-error injection covers result construction
  and growth. GC and ThreadGroups pass `-R 3:3` with `mimalloc_debug` (84 tests,
  three skips).
- Reentrant GC debug output: both ordinary cycles and legacy-finalizer cycles
  reproduce a segmentation fault before the fix and pass afterwards. The GC,
  ThreadGroup, weakref, reclamation, C API and embedding selection passes 644
  tests (16 skips), and GC/ThreadGroups pass `-R 3:3` with `mimalloc_debug`
  (85 tests, three skips). A further failure-injection test verifies reclamation
  when the debug snapshot allocation fails initially or after a partial snapshot.
  Finalization, tuple C APIs, type caching and subclass initialization pass
  another 74 tests.
- The non-debug normal build at `0bab8b44df` passes 643 tests across GC,
  ThreadGroups, C APIs, reclamation, weakrefs and embedding (23 skips). This
  validates the bitmap and introspection changes before the debug-output fix.
- The non-debug normal build at `806db9bcb5` passes 663 tests across eight
  files, including finalization and the debug-output/failure-injection
  regressions (23 skips). Its `mimalloc_debug` selection passes 96 tests across
  GC, ThreadGroups and deferred reclamation (four skips). This build retains
  `Py_GIL_DISABLED=0`, `Py_DEBUG=0`, an enabled interpreter GIL and a 24-byte
  object header.

- Group bias: 844 tests passed across ThreadGroups, local reclamation, object
  and miscellaneous C APIs, GC, threading, embedding and sys. Native probes cover
  two live OS threads in one group, creator-thread exit, foreign shared counts
  and local-count overflow. Targeted RC/GC tests also pass `-R 3:3`.
- Deferred/per-thread counts: container cycles, immediate LOCAL reclamation,
  weakref callbacks, resurrection, code counts after thread exit and late
  shutdown pass, including reference-leak checks.
- Deferred stack roots: 557 tests passed across GC, generators, coroutines,
  async generators, frames, code, C evaluation APIs, ThreadGroups and embedding.
  New regressions exercise a sole C stack root, older/frozen generators and
  resurrection. The four targeted stack/GC files pass `-R 3:3` (198 tests).
- Main lifetime: 524 tests passed across ThreadGroups, threading, fork, module
  C APIs, sys, embedding and deferred reclamation. A native late-cleanup probe
  retains no Python reference to Main. `test_threadgroup` also passes `-R 3:3`.
- Ownership and common C API returns: 493 tests passed across native ownership
  probes, abstract/object/dict/list/tuple APIs, calls, embedding and interpreters
  (12 skips). The probes cover 20 APIs with both LOCAL and IMMUTABLE results,
  within and across groups. Ownership/object/dict tests also pass `-R 3:3`
  (55 tests, 3 skips).
- VM heap loads: 506 tests passed across ownership, specialization, unpacking,
  iteration, generators, coroutines, GC, ThreadGroups, embedding and evaluation
  APIs (9 skips). Native workers construct their own LOCAL functions and
  namespaces from shared code. Tests consume acquired values before returning
  primitives and verify eight specialized instructions as well as cold paths.
  The ownership suite, now also covering `PyCell_Get`, passes `-R 3:3` (11 tests).
  All acquisition guards publish stack roots before raising, so rejected values
  are released by normal exception cleanup. Attribute and callable acquisition
  paths still need further work.
- Thread startup refuses a LOCAL callable owned by another group before
  creating its OS thread, avoiding a bootstrap wait that could never complete.
  Threading, thread APIs, function/cell attributes and ownership pass 383 tests
  (6 skips); ownership also passes `-R 3:3` (12 tests). Native workers remain
  necessary for execution in foreign groups until the later synchronized
  function stage.
- Attribute acquisition: 773 tests passed across ownership, specialization,
  descriptors, classes, inheritance, properties, object APIs, function attributes,
  calls, GC and embedding (11 skips). Native fixtures verify that inaccessible
  descriptors are never invoked, and repeated rejected lookups remain rejected
  after cache invalidation and respecialization. Slot, instance and module loads
  are checked in specialized code too. Ownership passes `-R 3:3` (14 tests).
- Call expansion and defaults: 884 tests passed across ownership, calls,
  function/argument APIs, function attributes, scopes, specialization, GC,
  embedding, descriptors, classes, inheritance and properties (8 skips).
  The native probes cover positional/keyword expansion, partial keyword cleanup,
  legacy format-string calls, the `__new__` adapter and 26 result-returning paths.
  Foreign defaults are rejected when bound, while existing argument vectors need
  no new checks. Ownership passes `-R 3:3` (15 tests). A shadowed non-descriptor
  builtin function on the metatype is not acquired merely to inspect the class's
  own attribute; selected results remain checked.
- Public sharing states: 641 tests passed across ownership, ThreadGroups,
  threading, descriptors, classes, GC and embedding (14 skips). The ownership
  suite passes `-R 3:3` (19 tests), including native foreign-group introspection,
  immutable state constants and startup without importing `threading`.
- Per-thread freelists: 413 tests passed across ThreadGroups, GC, embedding and
  threading (13 skips). The native probe exercises reuse within a thread,
  isolation between threads in the same or different groups, collection of a
  detached worker's cache, and clearing by its owner or another thread.
  ThreadGroups, ownership and GC pass `-R 3:3` (97 tests, 3 skips). The broader
  allocation run also passed float, complex, tuple, list, dict, range, generator,
  async-generator, context and memory API suites; its first version exposed an
  invalid test cleanup, fixed before the successful lifecycle/leak runs.
- Internal world stops: 1,023 tests passed across ThreadGroups, ownership,
  threading, GC, embedding, fork, tracing, profiling, monitoring and evaluation
  APIs (14 skips). Native probes release the interpreter GIL and group while
  the world is stopped and verify existing/new states cannot attach until
  restart. ThreadGroups and ownership pass `-R 3:3` (37 tests, 2 skips).
- Paused GC snapshots: 807 tests passed across ThreadGroups, ownership, GC,
  weakrefs, local/deferred reclamation, embedding, threading, generators,
  async-generators, contexts and fork (18 skips). A native cyclic object verifies
  traversal is paused and clearing/destruction are not; Python callbacks also
  verify the world is running. ThreadGroups, reclamation and GC pass `-R 3:3`
  (94 tests, 3 skips).
- Per-thread mimalloc port: the `mimalloc` selection passes 1,354 tests across
  15 files (29 skips), including allocation, ownership, GC, embedding, tracing,
  threading and fork. The `mimalloc_debug` selection passes 513 tests across
  six files (14 skips). The default allocator passes the 217-test lifecycle,
  GC and memory API selection (9 skips). Native probes cover foreign-thread
  accounting, survival after thread exit, content integrity and recursive
  allocator hooks; a subprocess matrix checks preinitialization lifetimes
  across malloc, pymalloc and mimalloc with and without their debug hooks.
  A non-debug normal build at `dde92fa9aa` passes a 1,030-test mimalloc selection
  across ten files (39 skips).
- Weakref ownership: 395 tests passed across ownership, ThreadGroups, weakrefs,
  weakref C APIs, GC, reclamation, code and embedding (14 skips). The native
  cache probe keeps both groups' refs alive and verifies each group's repeated
  requests return its own ref/proxy. Ownership and weakref suites pass `-R 3:3`
  with `mimalloc_debug` (167 tests, 4 skips).
- Interpreter namespace getters: 504 tests passed across ownership, evaluation,
  code evaluation, import/function C APIs, builtins, modules, embedding, scopes,
  code and GC (16 skips). The native probe covers borrowed and strong builtin
  getters, the module dictionary and the already-guarded xoptions getter from
  frameless threads. Ownership passes `-R 3:3` (21 tests).
- Paused weakref preparation and freelist clearing: 570 tests passed across
  ThreadGroups, GC, weakrefs, reclamation, embedding and threading (17 skips).
  ThreadGroups and GC pass `-R 3:3` with `mimalloc_debug` (81 tests, 3 skips).
  Debug output verifies callback-bearing weakrefs are already dead before
  Python code resumes, while their callbacks are still pending. The preceding
  weakref-phase run also passes type-cache and subclass-initialization tests.
- The non-debug normal build at `d78376927b` passes 638 tests across 13 files
  covering the weakref cache, namespace acquisitions and paused GC cleanup
  (24 skips). Its `mimalloc_debug` selection passes 110 tests across four files
  (4 skips). Both debug and non-debug builds retain `Py_GIL_DISABLED=0`, an
  enabled interpreter GIL, and a 24-byte `PyObject` header on Linux/aarch64.
- The non-debug normal build at `9a07ddfce7` passes 1,378 tests across 16 files
  covering sharing states, per-thread freelists, allocation, threading, GC and
  embedding (34 skips). This predates the internal world-stop activation.
- The non-debug normal build at `e3b47b1253` passes 1,393 tests across 16 files
  including the internal world stops and paused GC snapshots (22 skips).
- The non-debug normal build at `19030fdd7f` passes 645 tests covering the first
  C API/VM acquisition changes (17 skips). This validation predates the thread
  entry and attribute acquisition changes.
- The non-debug normal build at `00a29b07b1` also passes 838 tests covering the
  thread entry and attribute acquisition changes (20 skips). This predates
  the call expansion/defaults changes.
- The non-debug normal build at `0ae5c9dfbc` passes the 884-test call expansion
  and defaults selection (13 skips), including the `__new__` shadowing
  regression. It still uses `Py_GIL_DISABLED=0` and has the interpreter GIL
  enabled. No concurrent allocation/collection is claimed by these results.
- A separate non-debug build (`./configure`, `Py_GIL_DISABLED=0`, `Py_DEBUG=0`,
  empty ABI flags, interpreter GIL enabled) passes 782 tests across
  `test_threadgroup`, `test_local_reclamation`, `test_deferred_reclamation`,
  `test_gc`, `test_frame`, `test_generators`, `test_coroutines`, `test_asyncgen`,
  `test_capi.test_object`, `test_capi.test_eval`, `test_code`, `test_sys`,
  `test_crossinterp` and `test_embed` (34 skips).
