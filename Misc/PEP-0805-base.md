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
| ThreadGroups | Group selection, serialization, detach/reattach, native parallel scheduling, fork and Main lifetime | Parallel execution in the normal default path |
| One-time ABI change | Compact owner/state and group-biased RC header; no cleanup queue fields | Complete the allocation/GC port and audit native layouts |
| Biased and deferred reference counting | Group bias, per-thread code counts, deferred stack roots and normal GC integration | Queue collection and reclamation with concurrent groups |
| LOCAL and IMMUTABLE ownership | Builtin/static metadata, public `__shareable__` state, common C API returns, VM heap loads, attributes and call expansion | Remaining API/VM acquisitions and migration of static extension types |
| Parallel allocation and cyclic GC | Per-thread heaps/freelists and bytecode, QSBR, paused snapshots, owned worklists and native concurrent allocation/collection | General concurrent execution, owner-correct finalization, cross-interpreter legacy objects and teardown |

Freezing, protective/compound locks, synchronized objects and functions,
TransferBox, Channel, the debugger StopTheWorld API, and performance work are
later stages and excluded. Internal GC world stops belong to the runtime port.
Windows and native machine-code JIT validation are deferred.
Changes are limited to these runtime stages and their direct regression tests.
Library compatibility failures are recorded rather than expanding this branch
to make the existing suite pass; Main-only failures are identified separately.

## Runtime configuration and layout

Build normally, for example `./configure --with-pydebug && make -j8`.
`Py_GIL_DISABLED` is zero; the interpreter GIL remains enabled during the port.
Selecting `--disable-gil` is not the implementation of stages three and five.
The old free-threading backend still assumes OS-thread IDs and a larger local
counter and is not compatible with this intermediate header.

The normal scheduler now honors the interpreter-lock enable state. A private
native probe can temporarily disable that lock in an isolated process, retaining
group serialization and the normal build's object/GC implementations. Its start
gate keeps workers detached during the switch; after joining them, it restores
the lock before returning to Python. This is a test facility, not a public
parallel-execution mode or evidence that arbitrary Python code is ready for it.

The reference-counting bias belongs to a **ThreadGroup**, not an OS thread.
Objects retain their owner IDs on merging, resurrection and creator-thread
exit. A 64-bit `PyObject` occupies 24 bytes: a 32-bit owner/bias ID, an 8-bit local
count, state, flags and GC bits, a pointer-sized shared count and a type pointer.
The shared count retains PEP 703's two flag bits. Local overflow merges the
count into the shared field instead of making the object immortal.
Local updates use compare/exchange so a foreign group's immortalization cannot
be overwritten by a stale update. Dynamic immortalization closes the local
counter and then the shared counter, using a reserved shared value that late
operations recognize without arithmetic. Static immortals keep their existing
initializers. Interned strings subtract the counts captured by these exchanges
from debug totals; a concurrent merge accounts for any local count in transit.
This preserves canonical intern identity and adds no object-header fields.
The cost of compare/exchange on local operations has not been measured;
performance work remains a later stage.
BRC queue entry, draining and the paused allocation-failure fallback skip
objects that have become immortal. Their queue reference no longer needs to
be merged, and their lifetime and ownership must remain unchanged.
There is no object mutex, OS-thread ID or deferred-cleanup linkage in the header.
GC-tracked objects currently retain the normal collector's separate GC prefix.
Tracking and finalization status use the existing `ob_gc_bits` byte, with
atomic read-modify-write updates that preserve other flags. The GC prefix holds
list links and temporary reachability counts, not finalization state.

Debug reference totals use per-thread counters in the normal build too.
Readers sum live states using atomic loads; thread and interpreter deletion
transfer their contributions under the same registry lock used by readers.
Bulk removal after fork or during shutdown transfers totals while removing
the discarded states from that registry.
This preserves `sys.gettotalrefcount()` across teardown without requiring
every reference operation to update an interpreter-wide counter. This debug
accounting is separate from the ThreadGroup bias of object reference counts.

Object freelists are per-thread in the normal build too. Full GC clears all
thread caches, and thread-state clearing disables the target state's caches,
including when another thread performs the cleanup. The general runtime still
retains the interpreter GIL by default.

The normal build now defaults to mimalloc when it is available, including its
ported per-thread heaps separated by object/GC/preheader layout. Exiting threads
abandon their live allocations to an interpreter pool; allocation accounting
includes other threads, abandoned blocks and legacy interpreters' own mimalloc
heaps. It inspects allocated heaps independently of wrappers such as tracemalloc;
shared pymalloc arenas are counted only once. Heap selection is scoped to each
allocator call, including recursive embedding/tracing hooks. Allocator ownership
is independent of the object's ThreadGroup owner and reference-count bias.
Without mimalloc, the normal build defaults to system malloc. The explicit
`PYTHONMALLOC=pymalloc` selection remains available under interpreter-wide
serialization; the private parallel-allocation probe rejects it. Static runtime
initialization and preconfiguration choose the same defaults, including debug
hooks. Isolated native workers exercise default, explicit mimalloc and system
malloc allocation concurrently with cyclic collection in two groups. Their
immutable cycles have no Python finalizers or mutating API, so this does not
decide the pending LOCAL finalization design.

Audit hooks and interpreter views that span initialization use the non-swappable
raw allocator. Its debug backend is also independent of runtime allocator
configuration, so `PYTHONMALLOC` changes cannot mismatch allocation and freeing.

Internal per-interpreter and process-wide stop-the-world operations are active
in the normal build. Detached states, including states created during a pause,
cannot attach until it ends. Attachment drops group/GIL execution rights before
waiting on a suspended state. Fork, shutdown and existing introspection callers
use this mechanism; the later-stage public debugger API is not exposed.
The paused collector merges BRC counts when taking its strong references to
unreachable objects. This prevents later clearing from leaving the final
reference on a departed owner's merge queue. Clearing and destruction still
run after the world resumes. Before the cycle snapshot, GC also merges pending
BRC queues from every registered group, including groups without thread states.
It releases immutable and collector-owned references after resuming the world,
then pauses again for cycle detection. Keeping those queue references until
resumption avoids both destructors during a pause and zero-count tracked objects
in the generation lists. Foreign LOCAL references remain on their owner's queue;
owner-correct LOCAL destruction still awaits the finalization design decision.
In particular, destroying a shallow-immutable container can release foreign
LOCAL children through the existing decref paths; draining immutable queue
entries does not resolve that general ownership problem.

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

Type metadata updates use the interpreter's existing type mutex in the normal
build. Type-slot and flag updates use internal world stops, with the type mutex
pinned while waiting for the pause. Instance shared-key insertion takes the same
mutex before invalidating its type's version and cache. Type-watcher registration,
removal and watch-bit updates also use it. Debug builds enable the existing
revealed-type lock and world-stop assertions in both builds.

Type-watcher callbacks use atomic publication and acquisition, including the
optimizer's reserved callback and registry clearing during shutdown. A type's
watched bits are atomic too. Destruction notifies watchers outside the type
mutex, so it must synchronize with another group's registration changes even
when the type itself is LOCAL. Empty callback slots are skipped; clearing a
watcher does not wait for a callback already acquired by another group.
The native regression creates and collects 512 LOCAL types in one group while
the other group only replaces registrations. Weak references confirm that all
512 types die. No LOCAL object or Python callback is shared between the workers.

Type-version publication, unlocked cache guards and the version-use counter
use atomic operations in the normal build. Immutable types still initialize
these caches lazily, so group serialization alone cannot protect their first
attribute lookup. A native probe brings two groups to each of 1,024 previously
unqueried immutable extension types and checks repeated attribute acquisition.

Normal-build per-type lookup-cache readers take that mutex too, acquiring a
strong result reference before unlocking. Unlike the free-threading cache, this
cache owns mortal interned names and can contain LOCAL values. Its invalidated
storage and name references are released under the lock; the free-threading
branch retains lock-free readers and QSBR retirement. This port does not yet
establish safety of every type-version or specialization-cache fast path under
concurrent groups, and does not change LOCAL object finalization.

Shared instance-key tables now use their existing key mutex, atomic reference
counts and atomic size publication in the normal build. Distinct LOCAL
instances of an IMMUTABLE type can share this table even though their attribute
values remain private to their groups. Lookup and insertion synchronize on
the table; equality and type-watcher callbacks run after releasing its mutex
so they can re-enter attribute operations. The table's borrowed type hint is
acquired with a conditional incref under the type mutex. Type destruction
clears the hint under that mutex before dismantling its metadata. Dictionaries
that survive their type retain the keys without retaining or accessing the
dead type. A VM attribute-cache guard reads the shared entry count atomically
before deciding whether the table is suitable for specialization.

Attribute and descriptor access no longer rewrite their type's slots lazily.
Slot publication selects the simpler attribute dispatcher when the type has
no `__getattr__`. Restricting lazy writes to LOCAL types would be insufficient:
an IMMUTABLE instance can have a LOCAL class. Native fixtures exercise both
shared immutable types with each group's own instances, and shared immutable
instances of LOCAL types. They also check attribute insertion and acquisition,
dictionary copies and conversion from shared keys to combined tables. The
attribute methods are native descriptors; no Python function is shared.

Code objects use a dedicated mutex and acquire/release publication for their
lazy variable-name and bytecode caches. `co_extra` growth publishes a copied
array and retires the old array through QSBR; extra-slot registration uses the
interpreter's code-state mutex. Replaced extra values are still released after
unlocking, so extension free callbacks can re-enter. On Linux/aarch64 the mutex
occupies existing code-object padding; the generic object header remains 24 bytes.

Code-version allocation and function/code version-cache publication and removal
also use the interpreter's function-state mutex in the normal build. The cache
keeps borrowed pointers, so removal inspects the cached code under that mutex
before a concurrent destructor can free it. Fork reinitializes the mutex. Native
workers create and retire 32,768 code/function pairs across two groups, invalidate
function versions and run GC, then check that every code version was unique.
This does not change the LOCAL state of Python functions or permit sharing them.

Code and function watcher registrations, removals and notification lookups use
that mutex too. Their active bit masks are atomic fast filters; each callback
pointer is read under the mutex and invoked after unlocking. Empty slots are
skipped, including those cleared by an earlier callback in the same notification.
Error construction and callback execution never hold the registry mutex, so
callbacks may re-enter the registration APIs. Shutdown clears these registries
under the same mutex. Native workers repeatedly register and remove watchers
while creating, modifying and destroying their own functions and code objects.

Dictionary watcher registration and removal use their existing interpreter
mutex in normal builds too. Callback publication uses release stores and
notification uses acquire loads, including the reserved runtime callbacks.
Context watcher registration, removal and callback lookup use a dedicated
interpreter mutex, with an atomic active mask. Fork reinitializes this mutex.
Both registries release their locks before constructing errors or invoking
callbacks, and skip slots cleared during notification. Removing a watcher
does not wait for a callback that another group has already obtained.
Native workers register, notify and remove dictionary and context watchers
using objects owned by their own group and native callbacks with no shared
mutable Python state.

Interpreter-wide rare-event counters also use atomic accesses, with saturating
compare/exchange increments. Independent groups can modify their own LOCAL
functions concurrently; those updates must not lose counts or overwrite a
saturated counter with an older value. A native VM regression checks both the
exact count below saturation and the 255 limit after further modifications.

Dictionary key-version allocation uses the interpreter-wide atomic counter in
normal builds too. Concurrent readers publish a key table's first version with
compare/exchange; cache guards and invalidation use atomic accesses. This avoids
assigning the same version to unrelated dictionaries in different groups.
The isolated native VM probe shares only immutable code and creates each
worker's function, globals, builtins and native callables in its own group.
It exercises namespace and attribute caches, class/method changes, containers,
generators, exceptions and GC while recording 32,000 distinct dictionary-key
versions. It neither introduces synchronized functions nor settles the pending
execution context for LOCAL finalizers.

Immutable strings publish their lazy UTF-8 cache with an atomic compare/exchange.
Competing encoders preserve the first buffer, whose address may already be held
by a C caller, and free the redundant allocation. The cache length is published
before the pointer; readers acquire the pointer before using the length.
String, bytes, tuple, frozenset and frozendict hash caches use atomic accesses
in the normal build. A cold frozendict hash checks acquired values before
invoking their hash callbacks; cached container hashes and stored key hashes
do not acquire the elements. Shared runtime caches still require further
concurrency work before groups can execute in parallel.
The interning-state byte is now separate from Unicode's immutable bit fields,
with atomic publication and reads in both builds. Mortal interning and canonical
identity are preserved, including use by another group and survival after that
worker exits. The normal intern table is now a weak native hash table protected
by an interpreter mutex. Legacy interpreters which share the table use the
same mutex. New entries set BRC's maybe-weakref flag; lookup acquires a strong
reference before unlocking and rejects entries whose count has reached zero.
An old deallocator removes only its own allocation, preserving an equal
replacement. No dictionary references are hidden from the refcount. Shutdown
temporarily makes the table strong to preserve borrowed Unicode ID entries
until they acquire references. Table allocation uses the raw allocator.
Conversion of a group-biased mortal string to an immortal string now uses the
counter-closing protocol described above. Native workers exercise it concurrently
with local, shared and bulk updates, overflow merging and strong acquisitions
from the weak table. This validates that transition, not general parallel
execution of the remaining runtime caches.

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

The common special-method lookup helpers check methods acquired from a type
before invoking or binding them, and also check descriptor results. An immutable
instance can have a LOCAL class and LOCAL methods; sharing that instance does
not grant access to those methods. Sequence-iteration fallback preserves a
failed acquisition instead of replacing it with a non-iterable `TypeError`.
Subscript specialization declines inaccessible Python functions. Existing
getitem cache entries are acquired under the type mutex, returning an accessible
strong reference before unlocking. The helper reads the instance's type after
acquiring the mutex, since waiting may release group execution rights. A cache
miss falls back to the checked method lookup. The generated VM cases treat
this acquisition as an escape and publish their stack roots accordingly.
Native fixtures declare only their slotted instance immutable; the class and
Python methods stay LOCAL. Regressions cover subscription, iteration, arithmetic,
bytes conversion and context entry, plus a getitem cache populated by an earlier
worker in the method's owner group.
Attribute-hook dispatch also checks the selected `__getattribute__` or
`__getattr__` and any callable returned by descriptor binding. An unused LOCAL
`__getattr__` does not block an existing accessible attribute. Descriptor slot
dispatch checks the acquired `__get__` before calling it.
C calls check the hidden receiver acquired from a bound builtin and the
defining class acquired from a `METH_METHOD` callable or descriptor. An
immutable instance does not grant access to its LOCAL class as an implicit
argument. `PyCFunction_GetSelf()` checks its borrowed result as well. The
specialized `METH_O` and fast-call paths perform the same acquisition checks;
explicit arguments already held by the caller need no additional checks.
Specialized builtin, method-descriptor and type-vectorcall paths also validate
their returned references, matching the generic C-call path. The `type()`
specialization ends with a separate `_CHECK_ACCESS` micro-op so replacing the
type lookup with a constant does not remove the acquisition check. Native test
callbacks deliberately return stored heap references without checking them;
the VM must reject foreign LOCAL results even after call specialization.
Python bound-method dispatch acquires its stored receiver and function before
passing either to the callee, including positional, keyword and specialized
paths. `PyMethod_Function()` and `PyMethod_Self()` check their borrowed results.
Call specialization and version guards check access before reading a stored
function's mutable fields. The native probe can copy opaque tuple references
into a local method to verify these acquisition boundaries.

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
The default-path parallel scheduling test remains skipped while the interpreter
GIL is enabled. The isolated native probe additionally tests real parallelism.

- Python bound-method calls and C API getters: debug and release builds each
  run 748 tests across eight files successfully (one skip in each build).
  Before the fix, 22 foreign subcases fail; owner and immutable controls pass.
  The three selected tests pass `-R 3:3` and TSan without suppressions, and the
  existing parallel LOCAL function probe passes. The regressions verify both
  stored fields, ordinary and expanded arguments, and all three bound-method
  specializations. Logs: `test-python-methods-before.log`,
  `test-python-methods-targeted-final.log`, `test-python-methods-debug.log`,
  `test-python-methods-release.log`, `test-python-methods-refleak.log`,
  `test-python-methods-parallel.log` and `tsan-python-methods.log`.
- Specialized C call results: debug and release builds each run 1,198 tests
  across nine files successfully (four and six skips). Before the fix, ten
  foreign specialized subcases fail while the cold paths reject access.
  Both new tests pass `-R 3:3` and TSan without suppressions; the existing
  parallel LOCAL function probe also passes. Coverage includes builtin,
  method-descriptor and type-vectorcall results, plus `type()`, with owner
  and immutable controls and assertions that specialization remains active.
  Logs: `test-c-call-results-before.log`, `test-c-call-results-debug.log`,
  `test-c-call-results-release.log`, `test-c-call-results-refleak.log`,
  `test-c-call-results-parallel.log` and `tsan-c-call-results.log`.
- Bound C receivers and defining classes: debug and release builds each run
  1,013 tests across seven files successfully (four and six skips). The initial
  regressions fail in 15 foreign cases before the fix. Five selected tests
  pass `-R 3:3` and TSan without suppressions, and the existing parallel LOCAL
  function probe passes. Coverage includes all C calling conventions, bound
  and unbound `METH_METHOD` dispatch, and the borrowed receiver getter. Three
  regressions inspect bytecode to verify the specialized call paths remain
  active while rejecting foreign receivers. Logs:
  `test-bound-builtins-before.log`, `test-bound-builtins-debug.log`,
  `test-bound-builtins-release.log`, `test-bound-builtins-refleak.log`,
  `test-bound-builtins-parallel.log` and `tsan-bound-builtins.log`.
- Attribute hooks and descriptor dispatch: debug and release builds each run
  370 tests across six files successfully (four and eight skips). Six foreign
  subcases fail before the acquisition checks; all three new tests pass
  afterwards, including `-R 3:3`. Eight selected ownership tests pass under
  TSan without suppressions. Logs: `test-attribute-hooks-before.log`,
  `test-attribute-hook-results-before.log`,
  `test-attribute-hooks-debug-scoped.log`, `test-attribute-hooks-release.log`,
  `test-attribute-hooks-refleak.log` and `tsan-attribute-hooks.log`.
- Special-method acquisition: normal debug and release builds each run 653
  tests across ten files successfully (six and ten skips), covering ownership,
  groups, descriptors, type caches, specialization, generated VM cases,
  iteration, context managers and abstract/object C APIs. The parallel and
  foreign-special-method selection runs 18 tests under TSan successfully
  (two skips), without suppressions. Logs:
  `test-special-methods-debug-scoped.log`,
  `test-special-methods-release-scoped.log` and
  `tsan-special-methods-final.log`.
- Known Main-only failure: `test_pickle.CompatPickleTests.test_exceptions`
  expects the new `IllegalThreadAccessException` to have a Python 2
  `exceptions` mapping, but the existing mapping returns `__builtin__`.
  Running this test alone creates no foreign ThreadGroup and fails both in
  the current build and at `d800afe949`, before the special-method changes.
  Pickle implementation and compatibility tests are unchanged. Reproduce with
  `./python -m unittest test.test_pickle.CompatPickleTests.test_exceptions`.
  Logs: `test-pickle-access-exception-current.log` and
  `test-pickle-access-exception-baseline.log`.
- Known Main-only failure: `test_descrtut`'s `tut3` expects a fixed `dir(list)`
  listing without the added `__shareable__` attribute. The standalone test
  fails identically in the current build and at `d800afe949`. Its expected
  output is unchanged. Reproduce with `./python -m test test_descrtut`.
  Logs: `test-descrtut-shareable-current.log` and
  `test-descrtut-shareable-baseline.log`.
- Type-watcher destruction: normal debug and release builds each run 734 tests
  across eleven files successfully (14 and 19 skips), covering groups,
  ownership, watcher/type APIs, descriptors, caches, GC, weakrefs, embedding,
  fork and specialization. Before the fix, TSan reports `type_dealloc` reading
  the callback slot concurrently with `PyType_ClearWatcher`. After the fix,
  all 65 selected watcher tests pass under TSan without suppressions, including
  the parallel native workers and the existing destruction/error cases.
  Logs: `tsan-type-watcher-before.log`, `tsan-type-watchers-after.log`,
  `test-type-watchers-debug.log` and `test-type-watchers-release.log`.
- Shared instance keys and type slots: normal debug and release builds each
  run 1,008 tests across fourteen files successfully (14 and 19 skips), covering
  groups, ownership, dictionaries, type caches and descriptors, watcher APIs,
  GC, weakrefs, embedding, fork, specialization and generated VM cases. Before
  the fixes, TSan reports races in inline-value capacity accounting and lazy
  attribute-slot replacement. Restricting slot replacement to LOCAL types
  still races when their IMMUTABLE instances are shared. The regressions cover
  both ownership combinations, shared-key growth and conversion to combined
  tables, reentrant equality/type-watcher callbacks, and keys outliving their
  type. After the fix, the parallel/shared-key selection runs 19 tests under
  TSan successfully (two skips), without suppressions. Logs:
  `tsan-type-attribute-slot-before.log`,
  `tsan-shared-type-caches-old-slot.log`,
  `tsan-local-type-immutable-instance-before.log`,
  `tsan-shared-type-slots-parallel.log`,
  `test-shared-type-slots-debug-final.log` and
  `test-shared-type-slots-release-final.log`.
- Dictionary/context watcher registries: normal debug and release builds each
  run 533 tests across nine files successfully (10 and 15 skips), covering
  groups, ownership, contexts, watcher APIs, dictionaries, GC, embedding and
  fork. The native fixture performs 4,096 registration/notification/removal
  cycles for each
  kind of watcher across two groups. Before the fix, TSan reports races in
  both registration APIs, and clearing a later context watcher during
  notification aborts on a NULL-callback assertion. After the fix, all three
  watcher regressions pass under TSan without suppressions, including the
  previous code/function tests and clearing probes for all four registries.
  Logs: `test-context-watcher-clear-before.log`,
  `tsan-dict-context-watchers-before.log`,
  `tsan-dict-context-watchers-after.log` and `test-dict-context-watchers-*`.
- Code/function watcher registries: debug and release normal builds each pass
  395 tests across nine files (10 and 15 skips), including watcher APIs, code,
  functions, groups, ownership, GC, embedding and fork. Before the change,
  clearing a later watcher from an earlier callback aborts both code and
  function notification, and TSan reports competing registrations in
  `PyCode_AddWatcher`. After the change, both new tests pass under TSan without
  suppressions. The native parallel fixture creates 4,096 code/function pairs
  while registering/removing both kinds of watcher in each group.
  Logs: `test-watcher-clear-before-verbose.log`, `tsan-watchers-before.log`,
  `tsan-watchers-after.log` and `test-watchers-*`.
- Concurrent runtime metadata: debug and release normal builds each pass 679
  tests across twelve files (6 and 9 skips), covering types, attribute caches,
  functions, watchers, counters, groups, ownership, GC and generated VM cases.
  ThreadSanitizer first reports races in the function-modification counter and
  in a cold immutable type's version publication. After the fixes, the parallel
  selection passes under ThreadSanitizer (11 tests, two skips), without adding
  suppressions. The new regressions check exact/saturated modification counts
  and concurrent first lookups of immutable types. A separate native VM workload
  creating, deriving, changing and discarding LOCAL classes also passes TSan.
  Logs: `test-runtime-counters-*`, `tsan-parallel-*`, `tsan-cold-types-before2.log`
  and `tsan-type-churn-before.log`.
  The sanitizer worktree is configured with `--with-pydebug
  --with-thread-sanitizer --without-mimalloc --without-pymalloc`, retaining
  `Py_GIL_DISABLED=0` and a 24-byte header. On this Linux/aarch64 host, configure,
  make and the test process need `setarch aarch64 -R` to avoid TSan's startup
  memory-mapping failure; tests use `TSAN_OPTIONS=halt_on_error=1`.
- Parallel LOCAL VM execution and dictionary versions: debug, release and
  `--without-mimalloc` debug normal builds each pass 764 tests across thirteen
  files (7, 10 and 8 skips), covering dictionaries and their C APIs, VM caches,
  types, groups, ownership, GC, code, generated cases, generators and exceptions.
  Before the fix, the native VM regression detects two dictionary key tables
  assigned version 2045. The same regression passes after the atomic port,
  alongside the existing code-version probe. All three builds retain
  `Py_GIL_DISABLED=0`, an enabled default interpreter GIL and a 24-byte header.
  Logs: `test-parallel-vm-*`.
- Code/function version state: debug, release and `--without-mimalloc` debug
  normal builds each pass 423 tests across eleven files (10, 15 and 11 skips),
  covering code, functions, watchers, type caches, groups, ownership, GC,
  deferred reclamation, embedding and fork. The new parallel allocation probe
  first reproduces a duplicate code version, then passes with normal-build
  locking. Ten successive rounds with new groups and intervening collections
  also pass, exercising 327,680 code allocations and function-cache updates.
  Logs: `test-code-versions-*`.
- Pending group BRC queues: debug, release and `--without-mimalloc` debug
  normal builds each pass 429 tests across eight files (13, 27 and 23 skips).
  The new native fixture fails all four cases before the collector change,
  then verifies tracked/untracked reclamation, cycles, surviving external
  references, immortal entries, departed thread states and LOCAL queue
  retention. Failure injection verifies recovery on the next collection.
  GC and ownership pass `-R 3:3` (109 tests, one skip). The debug weakref and
  embedding files exceed the initial 120-second limit during concurrent
  builds, then pass with a 600-second limit. All three builds retain
  `Py_GIL_DISABLED=0`, an enabled interpreter GIL and a 24-byte object header.
  Logs: `test-gc-brc-*`.
- Default parallel allocator: debug and release normal builds each pass a
  650-test selection across nine files covering command-line configuration,
  embedding, memory C APIs, groups, ownership, sys, GC, weakrefs and tracemalloc
  (30 and 44 skips). A separate `--with-pydebug --without-mimalloc` build
  validates the same selection using system malloc (42 skips); its allocation
  statistics test was corrected to select the allocator it tests, then the
  full command-line file passes on rerun. Default/debug/explicit allocator
  selections exercise concurrent allocation and collection of 4,000 immutable
  cycles each. Both pymalloc and mimalloc statistics remain covered explicitly.
  Regression tests first reproduce counts dropping to zero under tracemalloc
  and missing legacy interpreters' mimalloc allocations, then verify live and
  freed blocks after the accounting fix. Sys and groups pass `-R 3:3` with the
  default allocator (135 tests, nine skips). All three builds have
  `Py_GIL_DISABLED=0` and retain interpreter-wide serialization outside the
  native probes. Logs: `test-default-allocator-*`, `test-allocator-accounting-*`
  and `test-allocator-stats-*`.
- Concurrent immortalization: normal debug and release builds successfully run
  1,183 tests across eighteen files covering groups, ownership, reference-count
  C APIs, Unicode, GC, weakrefs, code, types, threading, fork, embedding and
  reclamation (34 and 43 skips respectively). An initial native regression
  reproduced a negative string refcount and process abort. The fixed probe
  checks reference totals after both workers exit and management references
  are drained. It covers INCREF/DECREF, weak acquisitions, overflow merging,
  tuple repetition's bulk updates and canonical intern-table lookup. Additional
  debug/mimalloc_debug and release/mimalloc stress runs each complete 50,000
  promotions. Groups, ownership, immortal/Unicode C APIs, GC and weakrefs pass
  `-R 3:3` with `mimalloc_debug` (346 tests, seven skips). Public headers compile
  as C++11 with and without the limited API.
  Both builds retain `Py_GIL_DISABLED=0`, an enabled default interpreter GIL and
  a 24-byte object header. Logs: `test-immortal-counters-*` and
  `test-parallel-intern-*` under the log directory above.
- Native parallel scheduling and GC: debug and non-debug normal builds each
  successfully run 731 tests across ten files covering groups, ownership, GC,
  weakrefs, reclamation, threading, fork, embedding and sys (24 and 29 skips).
  Groups, GC and weakrefs pass `-R 3:3` with `mimalloc_debug` (233 tests,
  seven skips). Two native groups retain execution rights at a barrier, while
  workers in one group cannot do so. Concurrent allocation/collection checks
  bytes contents and destruction of all 4,000 immutable cycles with both
  mimalloc variants. Before merging candidate counts, one run freed only
  3,988 cycles; after the fix, an additional 25-round stress run collects all
  100,000 cycles. The probe rejects unrelated live states and restores the
  interpreter lock before returning. General Python parallelism is unfinished.
- Debug reference totals: debug and non-debug normal builds each successfully
  run 608 tests across 11 files covering groups, ownership, sys, GC, threading,
  fork, embedding, object/immortal C APIs and reclamation (23 and 30 skips).
  Groups, ownership and sys pass `-R 3:3` with `mimalloc_debug` (170 tests,
  nine skips). Native probes check isolated live-state accounting, transfer on
  deletion, objects surviving their creating state, and bulk removal by fork.
  The live-state probe fails before the per-thread port; the fork probe fails
  before preserving totals during bulk removal. Both pass after their fixes.
  These results do not establish concurrent execution safety for the runtime.
- Immortal BRC transitions: debug and non-debug normal builds each pass 357
  tests across nine files covering ownership, groups, sys, GC, reclamation,
  object/immortal C APIs and embedding (19 and 24 skips respectively).
  Ownership passes `-R 3:3` with `mimalloc_debug` (42 tests). Native probes
  stage a slow decref arriving after immortalization and a queued reference
  immortalized before draining; both abort in the preceding runtime and pass
  after the guards. Concurrent reference-count promotion remains unfinished.
- Weak intern table (`5082181131`): debug and non-debug normal builds each pass 982 tests
  across 14 files covering ownership, sys, type caching, strings, Unicode C
  APIs, marshal, code, embedding, groups, GC, threading, fork and tracemalloc
  (36 and 39 skips respectively). Ownership, sys and type-cache suites pass
  `-R 3:3` with `mimalloc_debug` (166 tests, seven skips). A native regression
  reproduces a zero-reference entry awaiting deallocation: the old table
  incorrectly resurrects it, while the weak table replaces it and preserves
  the replacement when the old allocation is freed. This validates that
  lifetime boundary, not concurrent execution or immortalization safety.
- Type metadata and per-type caches: a native contention probe verifies that a
  cache reader waits for the type mutex and observes invalidation after the
  wait. The new test fails against the preceding release runtime, where the
  reader proceeds before invalidation. Type-cache, watcher and subclass
  initialization suites pass `-R 3:3` with `mimalloc_debug` (100 tests).
  The non-debug normal build passes 1,284 tests across 18 files covering types,
  descriptors, specialization, ownership, watchers, GC, threading, fork and
  embedding (24 skips). The debug selection passes the same 1,284 tests
  (17 skips). Its embedding and threading suites first reached the 120-second
  limit while the release compiler was running; both pass with the same limit
  after compilation finishes. Both builds retain `Py_GIL_DISABLED=0`, the
  enabled interpreter GIL and the 24-byte object header.
- Bulk hash-table acquisitions: 1,136 tests pass across ten files covering
  ownership, sets, dictionaries, dictionary views, C APIs, comparison, repr,
  unpacking and calls (two skips). Ownership and dictionary views pass `-R 3:3`
  with `mimalloc_debug` (56 tests). Native callback counters exposed 36 failures
  before the fixes, including reflected comparisons on inaccessible source keys.
  Tests cover shared immutable containers and their local mutable copies,
  same-group and foreign-group access, and both LOCAL and declared IMMUTABLE
  keys. Separate cases retain pointer-only cloning and copying of LOCAL values
  without invoking their callbacks.
- The non-debug normal build at `acea7f58dc` passes the same 1,136-test bulk
  acquisition selection (ten files, two skips). Its `mimalloc_debug` ownership
  and dictionary-view selection passes 56 tests. These checks retain the
  interpreter GIL and do not validate concurrent group execution.
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
