# PEP 805 runtime foundations

This branch, `codex/pep805-base`, isolates the first five stages of the
[implementation strategy](https://peps.python.org/pep-0805/appendix-implementation/#implementation-strategy)
from `experimental/pep-805` at `9a4de37db8`. Its CPython base is
`6dad8b88cc39d8f9f41c22502a0b52304b326dd9`.

The specification is [PEP 805](https://peps.python.org/pep-0805/) and its
[implementation appendix](https://peps.python.org/pep-0805/appendix-implementation/).
The five-stage implementation is **not complete**. The scope below retains the
five named stages originally requested. The public appendix, as read on
2026-09-26, now orders ABI change, development-only ThreadGroups, parallel
allocation/GC, reference counting and simple ownership first, with the public
ThreadGroups API following them. That reordered list does not remove the
ThreadGroups API already requested for this branch.

| Stage | Current implementation | Remaining work |
| --- | --- | --- |
| ThreadGroups | Group selection, group-only serialization from startup, detach/reattach, native parallel scheduling, fork and Main lifetime | Broader lifecycle validation |
| One-time ABI change | Compact owner/state and group-biased RC header; no cleanup queue fields | Complete the allocation/GC port and audit native layouts |
| Biased and deferred reference counting | Group bias, per-thread code counts, deferred stack roots and normal GC integration | Queue collection and reclamation with concurrent groups |
| LOCAL and IMMUTABLE ownership | Builtin/static metadata, public `__shareable__` state, common C API returns, VM heap loads, attributes and call expansion | Remaining API/VM acquisitions and migration of static extension types |
| Parallel allocation and cyclic GC | Per-thread heaps/freelists and bytecode, QSBR, paused snapshots, owned worklists and concurrent allocation/collection in the normal default path | Native extension destruction, cross-interpreter legacy objects and teardown |

Freezing, protective/compound locks, synchronized objects and functions,
TransferBox, Channel, the debugger StopTheWorld API, and performance work are
later stages and excluded. Internal GC world stops belong to the runtime port.
Windows and native machine-code JIT validation are deferred.
Changes are limited to these runtime stages and their direct regression tests.
Library compatibility failures are recorded rather than expanding this branch
to make the existing suite pass; Main-only failures are identified separately.

## Runtime configuration and layout

Build normally, for example `./configure --with-pydebug && make -j8`.
`Py_GIL_DISABLED` is zero. From startup, each ThreadGroup serializes its own
threads; the interpreter-wide GIL is disabled (`sys._is_gil_enabled()` is false).
Selecting `--disable-gil` is not the implementation of stages three and five.
The old free-threading backend still assumes OS-thread IDs and a larger local
counter and is not compatible with this intermediate header.

The normal scheduler honors the interpreter-lock enable state. The default-path
native test checks concurrent execution without changing that state. Older
isolated native probes also exercise an explicit switch with detached workers
and restore the previous state after joining them. The normal build's object/GC
implementations remain in use. Ordinary Python functions remain LOCAL at this
stage, so cross-group execution uses native fixtures until synchronized functions
are implemented in a later stage.

Interpreter pending calls notify all threads, including when group execution
does not hold the interpreter GIL. Attachment still refreshes pending calls and
instrumentation state. The queue mutex also protects clearing the active handler
in the normal build. If Main tried to process its own queue while a foreign
group was the handler, releasing that handler re-notifies Main. Native probes
exercise concurrent enqueueing, callbacks that detach, bounded queue draining
and Main-only handoff without sharing Python callbacks between groups.

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
including when another thread performs the cleanup. Mimalloc heap abandonment
requires an exclusively owned, finalizing thread state; cleanup by another
thread does not require the interpreter GIL or the heap's original OS thread.

The normal build now defaults to mimalloc when it is available, including its
ported per-thread heaps separated by object/GC/preheader layout. Exiting threads
abandon their live allocations to an interpreter pool; allocation accounting
includes other threads, abandoned blocks and legacy interpreters' own mimalloc
heaps. It inspects allocated heaps independently of wrappers such as tracemalloc;
shared pymalloc arenas are counted only once. Heap selection is scoped to each
allocator call, including recursive embedding/tracing hooks. Allocator ownership
is independent of the object's ThreadGroup owner and reference-count bias.
Without mimalloc, the normal build defaults to system malloc. The explicit
`PYTHONMALLOC=pymalloc` selection protects its pools, arenas and block accounting
with a recursive mutex in the allocator state. Waiting does not detach a thread
mid-allocation; `PYTHONMALLOCSTATS` can reenter the same mutex. Statistics
readers use that mutex too. Raw fallbacks run outside the mutex, including
realloc's move to a larger block, so hooks can detach without deadlocking
another allocator call in the same group. No object-header fields are added.
Static runtime initialization and preconfiguration choose the same defaults,
including debug hooks. Isolated native workers exercise default, explicit
mimalloc, pymalloc and system malloc allocation and reallocation concurrently
with cyclic collection in two groups. Their
immutable cycles have no Python finalizers or mutating API. Separate tests
below cover the decision to skip inaccessible Python finalization callbacks.

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
in the generation lists. Foreign LOCAL references remain on their owner's queue
while that group has threads. Following Mark's clarification, a group with no
thread states permits atomic adoption by the decrefing or collecting group.
Membership includes detached and not-yet-started states. Joining a group and
adopting its objects use the same BRC mutex. Counts are merged before publishing
the new owner ID, and remain merged afterwards. The object header is unchanged.
This covers both queued decrefs and zero merged counts when destroying a tuple
with LOCAL children. It also lets GC drain departed groups' LOCAL queue entries.
It does not transfer a Python finalizer's LOCAL class, function or globals.
Following Mark's subsequent clarification, inaccessible Python finalizers and
weakref callbacks are skipped with a diagnostic on C stderr.
GC also attempts atomic adoption before native `tp_finalize` and `tp_clear`
calls. Waiting until `_Py_Dealloc()` would let an abandoned cycle's native
callbacks run while the instance still belonged to its departed group. This
does not change ownership when the old group still has thread states. Following
the user's decision, native reclamation proceeds in the collecting/decrefing
group with a diagnostic on C stderr if the object remains inaccessible. It does
not wait for the owner to resume. This decision does not establish that existing
extensions' native callbacks are safe when they touch their group's other state.

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
no `__getattr__`. Native fixtures exercise shared immutable types with each
group's own instances, and shared immutable instances of shared immutable
types. They also check attribute insertion and acquisition,
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
versions. Synchronized functions remain outside this branch's scope; separate
finalization probes exercise skipping inaccessible Python callbacks.

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
Native probes exercise concurrent allocation and collection from separate
groups. Legacy extension objects shared across interpreters still need further
ownership and list-lifetime work.
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

The core `Template` and `Interpolation` types are shallow immutable containers,
including instances constructed by t-string bytecodes. Their iterators remain
LOCAL. Interpolation formatting checks each stored field before invoking its
representation; template concatenation checks the two strings it combines.
Copying untouched strings or interpolation values into another immutable
container does not acquire those elements. The `string.templatelib` Python
module and its functions retain their existing LOCAL state.

ThreadGroup is a managed static builtin type whose wrapper holds only an exact
string or None. Main survives interpreter dictionaries, finalizers and type
teardown. The public `PyInterpreterState_Clear()` path releases Main after
clearing the other interpreter state.

Reference acquisition accepts IMMUTABLE objects and LOCAL objects owned by the
current ThreadGroup. Rejected acquisitions raise `IllegalThreadAccessException`
without inspecting the foreign object's representation. C API checks apply to
acquired results; already-acquired arguments need no additional runtime check.
`PyObject_DeclareImmutable()` rejects an object whose class is LOCAL before
changing its state. The class must first be declared shareable; declaring a
class likewise requires a shareable metaclass. `PyType_Freeze()` alone only prevents
type mutation; it does not declare cross-group sharing. These declarations
remain shallow: a shared class can contain LOCAL methods or inherit from a LOCAL
base. Test fixtures declare their read-only classes before sharing instances.
`PyObject_Type()` validates its newly acquired class. `%T` formatting uses that
checked type acquisition before constructing a type name, and `object.__repr__`
checks its stored class before reading the class's module or name.
`PyType_GetDict()` also validates the returned dictionary, including Main-owned
dictionaries of shared builtin types.
`PyUnicode_FromObject`, joining, comparison, containment, concatenation, padding,
splitting and prefix/suffix matching check acquired classes before formatting
their legacy `tp_name` error messages. Successful operations and short-circuit
paths do not acquire unused classes; the existing message text is retained.
The Python `type.__dict__` getter validates the dictionary before wrapping it
in a mapping proxy, preventing a foreign group from reading it through a
newly created local proxy.
The annotation and ctypes callers of `PyType_GetDict()` propagate acquisition
failures.
Internal dictionary lookup and the raw `Py_TYPE` macro remain unchanged.
Heap type name/qualified-name getters check stored references before returning
or formatting them. Normal associated-module getters validate borrowed results;
the token getter and module-state getter inherit those checks. Their `DuringGC`
lookup helpers retain raw traversal semantics.
Type construction and `__bases__` replacement validate bases acquired from
tuples before reading their metadata. This includes C API construction of
immutable types and bases returned by `__mro_entries__`. Metaclass selection
also validates the acquired metaclass; a rejected base replacement leaves
the original bases intact.
`PyType_GetBaseByToken()` checks the returned base before taking a new reference,
clearing the output pointer and returning -1 on rejection. Queries with no
output pointer retain their status-only behavior. `PyType_GetSlot()` checks the
borrowed object pointers in `Py_tp_base` and `Py_tp_bases`; other slots keep
their native pointer semantics. A read-only extension type can be declared
immutable while its base or its tuple-subclass bases remain LOCAL.
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
class can have LOCAL methods; sharing an instance of that class does
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
Builtin iterator consumers validate owned results from direct native
`tp_iternext` calls before truth testing, passing arguments, converting values
or storing them in result containers. This covers `all`, `any`, `filter`,
`map`, `zip`, `enumerate`, list extension and bytearray construction, including
strict map/zip length probes. Short-circuiting leaves unconsumed values alone,
and both forms of iterator exhaustion retain their existing behavior.
Attribute-hook dispatch also checks the selected `__getattribute__` or
`__getattr__` and any callable returned by descriptor binding. An unused LOCAL
`__getattr__` does not block an existing accessible attribute. Descriptor slot
dispatch checks the acquired `__get__` before calling it.
C calls check the hidden receiver acquired from a bound builtin and the
defining class acquired from a `METH_METHOD` callable or descriptor. An
immutable instance with a shared class can inherit a method defined in a LOCAL
base; its defining class must still be checked. `PyCFunction_GetSelf()` checks
its borrowed result as well. The specialized `METH_O` and fast-call paths
perform the same acquisition checks;
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
Bound-method attribute forwarding, representation, hashing, comparison and
reduction acquire the stored function before inspecting it or invoking its
slots. Representation also acquires the receiver. Private-name reduction
checks the receiver and any class obtained from its header before reading the
class name. Receiver identity comparisons, pointer hashing and blind copying
into reduction tuples do not inspect the receiver and need no acquisition check.
The C API's `instancemethod` wrapper likewise checks its stored function in
`PyInstanceMethod_Function()`, calls, attribute forwarding and comparison.
Representation preserves the getter's access exception. Descriptor binding
only copies that function into a local bound method; the later call performs
the acquisition check.
`PyEval_GetFuncName()` acquires a method's stored function, a function's stored
name, or the fallback class before reading its name. A function created from
shared code may retain a LOCAL string subclass as its name. The getter does not
inspect a bound method's receiver. `PyEval_GetFuncDesc()` returns a constant
category from the object's type tag and does not acquire these stored fields.
The name getter reports access and UTF-8 encoding errors through `NULL`;
the limited-API test wrapper propagates that error before converting the result.

Code representation, hashing and equality acquire stored metadata before
formatting, hashing or comparing it. Code construction can retain LOCAL string,
tuple and bytes subclasses even though the code object itself is immutable.
Unused metadata and fields skipped by equality's short-circuit remain unacquired.
Constant-key construction retains its existing treatment of opaque references.
Function construction acquires the code's constants tuple and its docstring
only when `CO_HAS_DOCSTRING` is set. Rejection propagates the access exception
and releases partially acquired references, instead of dereferencing a NULL
docstring. Code without a docstring does not acquire unused constants.

Immutable descriptors publish their `__qualname__` cache once using atomic
compare/exchange. Concurrent readers retain the first cached string. A cold
lookup acquires the stored class before reading its qualified name; a cached
lookup only reads the immutable string. Metaclass reentry can populate the cache
during name calculation, but any error from the outer calculation still
propagates rather than returning a value with an exception pending.
Descriptor representation also acquires the stored class before reading its
mutable type name.

Tuple and list element operations check references before invoking repr, hash,
comparison or sorting callbacks. A local list copied from a shared tuple can
still contain foreign LOCAL elements. Sorting checks those elements and the
contents of tuple keys, including its specialized comparison path. Failed
acquisition preserves the list and releases temporary keys. Both the public
rich-comparison API and sorting's direct slot calls validate returned objects
before using their truth value. Container length, cached tuple hashes and
comparison paths that do not inspect an element need no element acquisition.
The tuple hash cache uses atomic reads and writes in the normal build too.

Slice repr, hashing and index conversion acquire stored start, stop and step
references before using them. The legacy integer-only C API checks an accepted
integer before reading its value. Slice comparisons retain their existing
tuple-based acquisition checks and short circuits. Copying components into a
reduction tuple does not acquire them. A zero step or invalid length can fail
before unused components are acquired.

Memoryview casting checks each acquired shape element before reading its integer
value. Tuple indexing checks each acquired index before conversion, for both
reads and writes. Shape/arity errors and an earlier out-of-bounds index still
fail before unused elements are acquired. Failed acquisitions leave buffer data
unchanged and release incomplete views.

Nested argument parsing acquires each tuple element before converting it or
returning it through a C output parameter. This applies recursively and after
normalizing a nested sequence to a tuple. Rejection preserves the access
exception and uses the existing cleanup path, including releasing buffers
acquired for earlier elements. Already-acquired top-level call arguments are
unchanged; length errors and earlier conversion errors retain their precedence.

Exception formatting acquires a sole `args` element before converting it to text
or repr. This includes `KeyError` quoting and `AttributeError`'s comparison with
the attribute name before synthesizing a message. Multiple-argument formatting
retains the tuple's existing element checks. Assigning, retrieving and copying
the `args` tuple into a reduction result does not acquire its elements.

Generic alias repr and type-parameter discovery acquire arguments before
inspecting their types, attributes or contents. A locally created alias can
retain a shared argument tuple containing another group's LOCAL class, list or
extension instance. Failed discovery discards the partial parameter tuple;
subsequent attempts still report the acquisition error. Returning `__args__`
and copying it into a reduction tuple preserve opaque references.
Substitution checks arguments acquired from its input tuple and arguments passed
to a substitution callback after unpacking or preparation. Variadic expansion
also checks a prepared tuple before reading its size or copying its elements.
An absent parameter list, wrong prepared arity or earlier unpacking error still
fails before unused substitution arguments are acquired.
Substitution also validates cached parameters before looking up preparation
hooks, and re-acquires stored arguments before processing them. A user-provided
`__parameters__` tuple can contain foreign LOCAL objects; a nested local list
can also gain such elements after parameter discovery was cached. Rejection
releases temporary tuples and partial results without altering the original
alias or its argument tuple.

Arithmetic dispatch validates native unary, binary, ternary and in-place slot
results before returning them to C callers. Sequence concatenation/repetition
and their numeric fallbacks validate newly returned references too. Existing
`NotImplemented` dispatch and reflected operand ordering are unchanged.

Numeric conversion checks newly returned `nb_index`, `nb_int` and `nb_float`
references before reporting type errors, issuing warnings or copying subclass
data into an exact numeric result. This includes the scalar `PyFloat_AsDouble`
API. Already-acquired input numbers need no additional checks.

`PyObject_Repr` and `PyObject_Str` check native slot results before inspecting
their type or returning them. A valid string result may be a LOCAL subclass.
`PyObject_ASCII` inherits the repr check before accessing or escaping the string.

String/bytes prefix and suffix matching acquire tuple alternatives as they are
used, preserving short-circuit matches. Joining acquires sequence elements before
reading string data or requesting buffers; rejection releases earlier buffers.
The bytes constructor's sequence fast path also checks elements before integer
conversion. Unicode joining from already-acquired argument arrays remains
unchecked; public joining validates heap elements in their original error order.

Marshal checks references loaded from container elements and code/slice fields
before serializing them. Set elements are checked before their separate encoding
used for sorting. An existing serialization error stops later acquisitions,
preserving the first exception and avoiding later buffer callbacks. Public
input arguments and newly created code bytes need no additional checks.
The wire format and the raw dictionary/set iteration contracts are unchanged.

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

Function construction checks each acquired closure element before inspecting its
cell type. `COPY_FREE_VARS` also checks cells before placing them in the frame:
a C setter can copy an immutable closure tuple containing foreign LOCAL cells.
Rejecting only the cell's contents would still permit nonlocal writes/deletion.
Tests cover construction, reads, writes, deletion, nested capture, warmed calls,
Main controls, and cleanup after the first local cell was already copied.

`PyFrame_GetVar()` validates its acquired result, including contents copied into
a local cell; `PyFrame_GetVarString()` uses the same check. The native regression
examines the result before a VM return check can mask an unchecked C API result.
The frame, closure cell and getter callable all belong to the executing worker.

`PyContextVar_Get()` checks values acquired from the variable's default, its
cache and the current context's HAMT. Denied access returns -1 with a NULL output
pointer. An absent value still succeeds with NULL; an explicitly supplied
fallback is already an acquired argument and needs no extra ownership check.
Native tests inspect the C output before it can reach a VM return check.

`PyFunction_GetModule()` checks the borrowed `__module__` reference. Its runtime
callers distinguish missing metadata from denied access: frame module lookup,
sentinel construction, type parameter construction and type alias module lookup
propagate acquisition errors. Native fixtures copy an opaque heap reference into
a local function and inspect the C result before VM checks, or invoke its
consumers. Missing metadata, `None` and non-string accessible values still work.

Exception group construction checks acquired tuple elements before inspecting
their exception types, and checks the implicit `ExceptionGroup` class selected
for ordinary exceptions. That mutable heap type belongs to Main; constructing
an otherwise local group does not grant access to it. `split()` and `subgroup()`
also validate all acquired matcher tuple members before testing their types.
The VM's shared validation for `except` and `except*` checks tuple members too,
including later members when an earlier class would match. These paths already
have an error return; the public boolean `PyErr_GivenExceptionMatches()` API's
failure contract remains a separate design question.

Debug tier-one dispatch validates all live evaluation-stack references after an
instruction's acquisition checks, including tracing redispatch, inlined calls
and return values on the C entry frame. NULL and tagged integers are not object
references. Temporary spills before `_CHECK_ACCESS` are not validation points:
that operation must be allowed to reject a heap reference normally. Release
builds omit these assertions. The negative regression deliberately corrupts a
local slot and verifies that `LOAD_FAST` is caught before the value is consumed.
This implements normal-interpreter validation from the
[appendix](https://peps.python.org/pep-0805/appendix-implementation/#validation);
machine-code JIT validation remains outside this branch's current scope.

Mark has resolved ownership of an individual object after its last owner thread
exits: the decrefing group may atomically adopt it. Python `__del__` and weakref
callbacks that cannot be accessed in the reclaiming group may be skipped.
`slot_tp_finalize` checks the object and class before method lookup and logs
inaccessible method acquisition. Both collectors and refcount destruction use
the same weakref callback acquisition helper, which checks the callback and the
weakref argument. Diagnostics are fixed strings on C stderr; they execute no
Python logging or object representation. Ordinary accessible callbacks retain
their existing error reporting, and pending exceptions survive reclamation.
No cleanup thread, group switching or implicit transfer of callback dependencies
is needed. Native destructors and GC clearing/finalization proceed with C stderr
diagnostics when adoption fails and the object remains inaccessible; Python
callbacks retain the access checks and skip behavior above.

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
The default-path parallel scheduling test requires group-only serialization
from startup and does not skip. The extension-import test also runs in the normal
build, checking that imports leave this scheduling state unchanged.

Earlier validation predates the explicit class-sharability check in
`PyObject_DeclareImmutable()`. Fixtures that formerly declared an immutable
instance of a LOCAL class now share the class first, or test declaration
failure. LOCAL method and LOCAL base acquisition tests remain relevant.

- Function module acquisition: debug and release each run 1,335 ownership,
  function API, builtin, sys, type parameter, type alias and typing tests with
  only the known Main-only `test_is_gil_enabled` failure (15 and 16 skips).
  Before the fix, direct C acquisition and sentinel construction both fail
  their foreign LOCAL regressions. Two focused tests, including consumers of
  the new error path, pass `-R 3:3` and TSan without suppressions. Logs:
  `test-function-module-{before,debug,release,refleak,tsan}.log`.
- VM exception matcher acquisitions: debug and release each run 399 ownership,
  exception group, `except*` and exception API tests without failures (three
  and four skips). The new regression reproduces four foreign LOCAL failures
  before the fix, and passes `-R 3:3` and TSan without suppressions afterwards.
  Logs: `test-except-acquisition-{before,debug,release,refleak,tsan}.log`.
- Exception group acquisitions: debug and release each run 398 ownership,
  exception group, `except*` and exception API tests without failures (three
  and four skips). Before the fix, 12 foreign LOCAL cases fail while Main
  and immutable controls pass. The three new tests pass `-R 3:3` and TSan
  without suppressions. Logs:
  `test-exception-group-acquisition-{before,debug,release,refleak,tsan}.log`.
- Context variable C API results: debug and release each run 235 ownership,
  context and group tests without failures (one and four skips). The three
  foreign LOCAL default/cache/HAMT cases fail before the fix. The native return
  probe passes `-R 3:3`; it and parallel context watchers pass TSan without
  suppressions. Logs: `test-context-return-{before,debug,release,refleak,tsan}.log`.
- Debug stack validation: debug and release each run 1,146 tests across 12
  ownership, scheduling, frame, tracing, monitoring, generator and opcode-cache
  files without failures (nine and twelve skips). The injected invalid local
  reaches `LOAD_FAST` without detection before the change, and now aborts at
  the stack assertion. Five focused TSan tests pass without suppressions,
  including parallel local function execution and GC. Logs:
  `test-stack-validation-debug-final.log`, `test-stack-validation-release.log`,
  `test-stack-validation-tsan.log`, `test-stack-validation-parallel-tsan.log`.
- Frame variable C APIs: debug and release each run 731 ownership, frame,
  scope, function and tracing tests without failures (nine skips). Both foreign
  LOCAL getters fail the native regression before the fix; Main and immutable
  controls pass. The regression passes `-R 3:3` and TSan without suppressions.
  Logs: `test-frame-acquisition-{before,debug,release,refleak,tsan}.log`.
- Native reclamation diagnostics and closure cells: debug and release each run
  1,097 tests across 11 files without failures (six and nine skips). Main-only
  controls pass, including empty stderr for native reclamation. Four in-process
  closure/orphan tests pass `-R 3:3`; eight focused tests pass TSan without
  suppressions. Before the closure fix, ten foreign acquisition cases fail.
  The diagnostics leave native reclamation enabled while the owner is still
  alive, and preserve pending exceptions without invoking Python logging.
  Logs: `test-reclaim-closure-{debug,release,refleak,tsan}.log`.
- Orphan cyclic reclamation: debug and release each pass 395 ownership, group,
  GC, weakref and finalization tests (five and eight skips). The new regression
  exercises eight combinations of merged/unmerged counts, an initially
  detached/pending owner and presence/absence of a native finalizer. All owner
  states are removed before collection. Four merged-count cases fail before
  the fix because native finalization or clearing sees the old owner ID.
  Both cycle and non-cycle orphan probes pass `-R 3:3`. Seven focused tests pass
  TSan without suppressions in normal debug/pymalloc. Debug and release use
  normal mimalloc builds. No new Main-only failure appears in this selection.
  Logs: `test-orphan-gc-before.log`, `test-orphan-gc-debug.log`,
  `test-orphan-gc-release.log`, `test-orphan-gc-refleak.log`,
  `test-orphan-gc-tsan.log`. This validation predates the decision to log and
  continue native reclamation while the owner is still alive.
- Class sharability: debug and release each pass 515 tests across ownership,
  type C APIs, descriptors, weakrefs and GC (six and seven skips). The previous
  implementation fails both the instance/class and class/metaclass rejection
  cases. The regressions check failure without a state change, declaration in
  dependency order, idempotence and the default LOCAL extension class. Existing
  native fixtures now declare their classes before their immutable instances;
  the inherited C-method test still rejects its LOCAL defining base before
  entering the native callback. Five focused tests pass `-R 3:3`; eight pass
  TSan without suppressions on normal debug/pymalloc, including parallel shared
  instance lookup and the finalization callbacks. Neither normal debug/mimalloc
  nor release/mimalloc shows a new Main-only failure in this selection.
  Logs: `test-class-declaration-before.log`,
  `test-class-declaration-debug-final.log`, `test-class-declaration-release-final.log`,
  `test-class-declaration-refleak.log` and `test-class-declaration-tsan.log`.
- Inaccessible Python finalization callbacks: debug and release each pass
  346 tests across ownership, GC, weakrefs and finalization (five and six skips).
  The regression covers 24 combinations of Main/foreign group, refcount/GC,
  departed/detached owner, shared callback and shared class. It checks skipped
  calls, C stderr diagnostics, pending exceptions and absence of Python logging
  or unraisable hooks. An in-process run of all 24 combinations passes `-R 3:3`.
  Six focused finalization, adoption and parallel-GC tests pass TSan without
  suppressions using normal debug/pymalloc (`--without-mimalloc`). Normal debug
  and release use mimalloc; none of these builds enables `--disable-gil`.
  No new Main-only failure appears in this selection. Logs:
  `test-skip-finalizers-debug-final.log`, `test-skip-finalizers-focused-final.log`,
  `test-skip-finalizers-release-final.log`, `test-skip-finalizers-refleak-final.log`
  and `test-skip-finalizers-tsan.log`.
- Orphan ownership adoption: debug passes 758 tests across ownership, groups,
  GC, weakrefs, threading, fork, memory C APIs and embedding (15 skips).
  Rebuilding group membership after fork then passes 50 group/fork tests.
  Release passes 377 ownership/group/GC/weakref/fork tests (eight skips).
  Native probes cover unmerged and merged tuple elements, detached and pending
  owner states, simultaneous adopters, and departed groups' LOCAL GC queues.
  Eight focused cases pass TSan without suppressions. Four adoption and existing
  VM/sequence tests pass `-R 3:3`; the 30-group weakref reproducer now retains
  zero references. No new Main-only failure appears in this selection.
  At that point a separate diagnostic observed zero Python `__del__` calls
  because its function remained foreign LOCAL. Mark has since confirmed that
  inaccessible Python callbacks may be skipped, with a stderr diagnostic.
  Logs: `test-orphan-debug.log`, `test-orphan-release.log`, `test-orphan-fork-final.log`,
  `tsan-orphan-final.log`, `test-orphan-refleak.log`, `orphan-leak-final.log`
  and `orphan-finalizer-evidence.log`.
- Legacy Unicode type errors: debug and release each pass 328 tests across
  ownership, strings and Unicode C APIs (six and seven skips). Two new tests
  exercise 66 worker calls covering 16 error paths, their ordinary messages,
  Main/shared-class controls and short-circuit operations that skip unused
  classes. The baseline reproduces 16 foreign-class failures; Main controls
  pass. Both tests pass TSan without suppressions. Twenty-eight existing
  Main-only operations pass `-R 3:3` (one skip), with no new Main-only failure in
  this selection. Logs: `test-unicode-error-before.log`,
  `test-unicode-error-debug.log`, `test-unicode-error-release.log`,
  `test-unicode-error-main-refleak.log` and `tsan-unicode-error.log`.
- String conversion slot results: debug and release each pass 513 tests across
  ownership, descriptors, builtins and Unicode C APIs (nine and ten skips).
  The new test exercises 32 native worker calls through repr, str, the str-to-repr
  fallback and ASCII conversion, including non-ASCII strings and invalid LOCAL
  results. Eleven foreign-group cases fail before the fix; Main and exact-string
  controls pass. The test passes TSan without suppressions. Eighteen existing
  Main-only conversion/formatting tests pass `-R 3:3` (two skips), with no new
  Main-only failure in this selection. Logs: `test-string-return-before.log`,
  `test-string-return-debug.log`, `test-string-return-release.log`,
  `test-string-return-main-refleak.log` and `tsan-string-return.log`.
- Type acquisition for formatting: debug and release each pass 512 tests across
  ownership, descriptors, builtins and Unicode C APIs (nine and ten skips).
  Two new tests exercise 16 worker calls, covering `%T` in argument errors and
  the default object representation through `repr` and `str`. The baseline has
  four foreign-LOCAL-class failures; Main and shared-class controls pass. Both
  tests pass TSan without suppressions. Thirteen existing Main-only formatting
  and representation tests pass `-R 3:3`, with no new Main-only failure in this
  selection. Logs: `test-type-format-baseline.log`, `test-type-format-debug.log`,
  `test-type-format-release.log`, `test-type-format-main-refleak.log` and
  `tsan-type-format.log`.
- Function docstring acquisition: debug and release each pass 205 tests across
  ownership, function attributes, code objects and opcodes (one skip). The new
  test exercises 40 worker cases, each twice, through the constructor and
  `MAKE_FUNCTION`, including Main controls and unused constants. Before the
  fix, a foreign LOCAL docstring crashes in `PyFunction_NewWithQualName`; a
  foreign tuple subclass containing an ordinary docstring is read unchecked.
  The test runs in a subprocess so regrtest's Main-owned Python audit hook
  cannot reject `function.__new__` before docstring acquisition. It passes TSan
  without suppressions. Existing Main-only tests pass `-R 3:3` (89 tests, one
  skip), with no new Main-only failure in this selection. Logs:
  `function-doc-before.log`, `function-doc-tuple-before.log`,
  `test-function-doc-debug-isolated.log`, `test-function-doc-release-isolated.log`,
  `test-function-doc-main-refleak.log` and `tsan-function-doc-isolated.log`.
- Template and interpolation ownership: debug and release each pass 184 tests
  across ownership, strings and t-strings. Three new tests cover shallow
  immutability, LOCAL iterators, field acquisition, formatting, concatenation
  and opaque reference copying. Enabling immutable classification alone exposes
  six foreign-group failures in formatting and concatenation; Main controls
  pass. With the acquisition checks, all three tests pass TSan without
  suppressions. Existing Main-only template and t-string tests pass `-R 3:3`
  (27 tests), with no new Main-only failure in this selection. Logs:
  `test-template-before.log`, `test-template-before-guards.log`,
  `test-template-debug.log`, `test-template-release.log`,
  `test-template-main-refleak.log` and `tsan-template.log`.
- Generic alias substitution metadata: debug and release each pass 924 tests
  across ownership, generic aliases, typing and type aliases. The new test
  exercises 32 worker calls with repeated substitutions, covering cached foreign
  parameters and nested lists changed after discovery, including rejection
  after processing earlier entries. Baseline runs reproduce eight foreign-group
  failures; Main and immutable controls pass. The targeted test passes TSan
  without suppressions. Existing Main-only generic/type-alias tests pass
  `-R 3:3` (70 tests), with no new Main-only failure in this selection. Logs:
  `test-alias-metadata-before.log`, `test-alias-metadata-debug.log`,
  `test-alias-metadata-release.log`, `test-alias-metadata-main-refleak.log`
  and `tsan-alias-metadata.log`.
- Generic alias substitution inputs: debug and release each pass 923 tests
  across ownership, generic aliases, typing and type aliases. Three new tests
  exercise 31 worker calls through local protocol implementations, covering
  direct, prepared and unpacked inputs, variadic tuple subclasses and earlier
  errors. Baseline runs reproduce seven foreign-group failures; Main and
  immutable controls pass. All three tests pass TSan without suppressions.
  Existing Main-only generic/type-alias tests pass `-R 3:3` (70 tests), with no
  new Main-only failure in this selection. Logs:
  `test-alias-substitution-before.log`, `test-alias-substitution-debug.log`,
  `test-alias-substitution-release.log`, `test-alias-substitution-main-refleak.log`
  and `tsan-alias-substitution.log`.
- Generic alias elements: debug and release each pass 920 tests across ownership,
  generic aliases, typing and type aliases. Three new tests exercise 43 worker
  calls, covering repr, parameter discovery, LOCAL class/list/native elements,
  immutable controls, opaque argument storage and repeated failed discovery
  after an accessible type parameter. Baseline runs reproduce 13 failures;
  Main and immutable controls pass. All three tests pass TSan without
  suppressions. Existing Main-only generic/type-alias tests pass `-R 3:3`
  (70 tests), with no new Main-only failure in this selection. Logs:
  `test-alias-elements-before.log`, `test-alias-elements-debug.log`,
  `test-alias-elements-release.log`, `test-alias-elements-main-refleak.log`
  and `tsan-alias-elements.log`.
- Exception argument formatting: debug and release each run 319 tests across
  ownership, base exceptions, exceptions, exception groups and exception C APIs
  (three skips). Both have one known Main-only failure: the fixed exception
  hierarchy omits `IllegalThreadAccessException`, as confirmed independently in
  the earlier `d800afe949` build. The remaining tests pass. Three new tests
  exercise 80 worker calls; baseline runs reproduce ten foreign-group failures,
  and all three tests pass TSan without suppressions. Main-only formatting and
  message tests pass `-R 3:3` (12 tests). Logs: `test-exception-arguments-before.log`,
  `test-exception-arguments-debug.log`, `test-exception-arguments-release.log`,
  `test-exception-arguments-main-refleak-focused.log` and
  `tsan-exception-arguments.log`. The initial broader reference-leak selection
  also included the failing hierarchy test.
- Nested argument acquisition: debug and release each pass 364 tests across
  ownership, argument-parsing C APIs and calls. Four new tests exercise 117
  worker calls through existing C API test functions, covering positional and
  keyword parsing, recursive tuple/list inputs, native conversions, object
  output parameters, earlier errors and buffer cleanup. Baseline runs reproduce
  28 foreign-group failures; Main and immutable controls pass. All four tests
  pass TSan without suppressions. Existing Main-only argument-parsing tests
  pass `-R 3:3` (73 tests), with no new Main-only failure in this selection.
  Logs: `test-getargs-nested-before.log`, `test-getargs-nested-debug-final.log`,
  `test-getargs-nested-release-final.log`, `test-getargs-nested-main-refleak.log`
  and `tsan-getargs-nested.log`. The initial broader command also named a
  nonexistent `test_capi.test_call`; the corrected selection passes.
- Memoryview shape/index acquisition: debug and release each pass 423 tests
  across ownership, memoryview, buffer and abstract C API files (21 skips).
  Four new tests exercise 106 worker calls, covering integer subclasses,
  native index callbacks, tuple/list shapes, C/F ordering, multidimensional
  reads/writes, earlier errors and buffer cleanup. Baseline runs reproduce
  24 foreign-group failures; Main and immutable controls pass. All four tests
  pass TSan without suppressions. Existing Main-only memoryview/buffer tests
  pass `-R 3:3` (22 tests, three skips), with no new Main-only failure in this
  selection. Logs: `test-memoryview-acquisition-before.log`,
  `test-memoryview-acquisition-debug.log`, `test-memoryview-acquisition-release.log`,
  `test-memoryview-acquisition-main-refleak.log` and
  `tsan-memoryview-acquisition.log`.
- Native iterator consumers: debug and release each pass 912 tests across nine
  ownership, builtin, list, bytes, enumerate, iterator and C API files (16 and
  17 skips). Four new tests exercise 122 worker calls, including Main and
  immutable controls, strict length errors, short-circuiting, partial extension
  and both forms of exhaustion. Baseline runs report 18 failures; callback
  counters demonstrate that rejecting a value after truth testing is too late.
  All four tests pass TSan without suppressions. Existing Main-only builtin,
  list and enumerate cases pass `-R 3:3` (38 tests, one skip), with no new
  Main-only failure in this selection. Logs: `test-iterator-consumers-before.log`,
  `test-iterator-consumers-controls-before.log`, `test-iterator-consumers-debug.log`,
  `test-iterator-consumers-release.log`, `test-iterator-consumers-main-refleak.log`
  and `tsan-iterator-consumers.log`.
- Base-class C API results: debug and release each pass 162 tests across five
  ownership, type/slot C API, xxlimited and defaultdict files. Native probes
  check token results before a VM return check can mask a failure, status-only
  token queries, borrowed base/bases slots and a LOCAL tuple subclass used for
  the bases. Baseline runs reproduce one token and three slot acquisition
  failures; Main and exact-tuple controls pass. Both targeted tests pass TSan
  without suppressions. Existing Main-only C API and extension tests pass
  `-R 3:3` (72 tests), with no new Main-only failure in this selection. Logs:
  `test-base-token-before.log`, `test-base-slot-before-release.log`,
  `test-base-returns-debug.log`, `test-base-returns-release.log`,
  `test-base-returns-main-refleak.log` and `tsan-base-returns.log`.
- Type dictionary proxies: debug and release each pass 457 tests across six
  ownership, types, descriptors, dictionary views and type/dictionary C API
  files (one and two skips). Before the fix, foreign groups acquire proxies for
  three builtin types' Main-owned dictionaries; indexing one asserts in debug
  and reads the dictionary in release. The getter now rejects that acquisition.
  Both targeted tests pass TSan without suppressions; local proxy construction,
  live updates and immutable mappings remain covered. Existing Main-only proxy
  tests pass `-R 3:3` (20 tests), with no new Main-only failure in this selection.
  Logs: `test-type-proxy-before.log`, `test-type-proxy-debug.log`,
  `test-type-proxy-release.log`, `test-type-proxy-main-refleak.log` and
  `tsan-type-proxy.log`.
- Base-class acquisitions: debug and release each pass 402 tests across seven
  ownership, type/slot C API, class, descriptor, subclass-init and super files
  (one skip). Four new tests exercise 44 native-worker calls, covering Python
  and C type creation, `__bases__` replacement and `__mro_entries__`. The
  baseline reports 13 failures; Main controls pass. After the fix all four tests
  also pass TSan without suppressions. Existing Main-only type/slot C API and
  subclass-init tests pass `-R 3:3` (64 tests). No new Main-only failure was found
  in this selection. Logs: `test-type-bases-before.log`,
  `test-type-bases-debug.log`, `test-type-bases-release.log`,
  `test-type-bases-main-refleak.log` and `tsan-type-bases.log`.
- Type name/module results: debug and release each pass 444 tests across six
  ownership, type/module C API, module, descriptor and exception files (four
  skips). Two native tests reproduce nine foreign-group failures before the
  fix and pass afterward. They cover name subclasses before full-name formatting,
  borrowed/owned module results, inherited module lookup and state pointers;
  Main and exact-string controls pass. Both tests also pass TSan without
  suppressions. Existing Main-only type/module C APIs pass `-R 3:3` (37 tests).
  No new Main-only failure was found. Logs: `test-type-metadata-before.log`,
  `test-type-metadata-debug.log`, `test-type-metadata-release.log`,
  `test-type-metadata-main-refleak.log` and `tsan-type-metadata.log`.
- Class/dictionary C API results: debug and release each pass 532 tests across
  ownership, types/descriptors, annotations and ctypes structures (three skips).
  Four foreign-group cases fail before the fix: an immutable instance's LOCAL
  class and the dictionaries of three shared builtin types. Afterward both new
  tests pass, including Main controls and the existing `type()`/`__class__`
  guards, and also pass TSan without suppressions. Existing Main-only type C API,
  type annotation and ctypes structure tests pass `-R 3:3` (88 tests, two skips).
  No new Main-only failure was found in this selection. Logs:
  `test-type-return-before.log`, `test-type-return-debug.log`,
  `test-type-return-release.log`, `test-type-return-main-refleak.log` and
  `tsan-type-return.log`.
- Arithmetic/sequence operator results: debug and release each pass 1,147 tests
  across twelve ownership, numeric, sequence, descriptor/operator and C API
  files (16 skips). Native tests cover 35 C APIs through 64 operand/fallback
  cases, with Main, foreign LOCAL and immutable controls. All 64 foreign LOCAL
  cases fail before the fix and pass afterward; checks occur before results
  reach the VM. Both new tests pass TSan without suppressions, and existing
  numeric/abstract C APIs pass `-R 3:3` (64 tests). No new Main-only failure was
  found. Logs: `test-operator-before.log`, `test-operator-debug.log`,
  `test-operator-release.log`, `test-operator-main-refleak.log` and
  `tsan-operator.log`.
- Numeric conversion results: debug and release each pass 387 tests across
  ownership, integer/index/float/complex operations and numeric C APIs (5/6 skips).
  The new native test covers four conversion APIs, exact and subclass results,
  wrong-type LOCAL results, both ownership directions and the valid -1 sentinel.
  Its eight failing baseline cases pass after the fix. The reverse direction
  creates a numeric subclass in a foreign group and consumes its opaque tuple
  from Main; otherwise the Main-owned warning module can mask the unchecked
  subclass conversion. The test also passes TSan without suppressions. Existing
  Main-only numeric C APIs pass `-R 3:3` (64 tests), and this selection found no
  new Main-only failure. Logs: `test-number-return-before-reverse.log`,
  `test-number-debug.log`, `test-number-release.log`,
  `test-number-main-refleak.log` and `tsan-number-return.log`.
- String sequence acquisition: debug and release each pass 853 tests across
  ownership, strings, bytes, formatting, their C APIs and regular expressions
  (17/30 skips). Before the fix, the four new tests report 33 failures involving
  foreign LOCAL elements; Main controls pass. Afterward all four pass, including
  native callback counts, short-circuit matching, first-error preservation and
  release of earlier buffers. The 20 selected existing Main-only operations pass
  `-R 3:3` (one skip). No new Main-only failure was found in this selection.
  The four new tests also pass TSan without suppressions (`tsan-string.log`).
  Logs: `test-string-acquisition-before.log`, `test-string-debug.log`,
  `test-string-release.log` and `test-string-main-refleak.log`.
- Marshal heap acquisition: debug and release each pass the six ownership,
  marshal/C API, code and compilation suites (381 tests, 15 skips). The 67
  source/sourceless-loader tests also pass after importing `unittest.mock` in
  their runner. Running that file alone initially produces six Main-only
  `AttributeError`s because it assumes that import has already occurred;
  both the test and `unittest` are unchanged from the branch's CPython base.
  The debug command additionally named a nonexistent bytecode test package.
  The two new tests pass TSan without suppressions. They use isolated processes
  so regrtest's Main-owned Python audit hook cannot reject the call before the
  serialization under test. Native buffer callbacks record no side effects on
  rejection; Main and immutable controls, versions 0–6, both C output APIs,
  copied local containers, code metadata, unsupported versions, disabled code
  serialization and first-error preservation are covered. Existing Main-only
  marshal/C API tests pass `-R 3:3` (87 tests, eight skips); this does not establish foreign
  LOCAL reclamation. Logs: `test-marshal-acquisition-before.log`,
  `test-marshal-debug.log`, `test-marshal-release.log`,
  `test-marshal-loader-details.log`, `test-marshal-loader-debug.log`,
  `test-marshal-loader-release.log`, `test-marshal-main-refleak.log` and
  `tsan-marshal.log`.
- Slice component acquisition: debug and release each run 694 tests across
  ownership, slices, ranges, tuples, lists, bytes and strings successfully
  (14 skips). Before the fix, 27 foreign-group cases fail; Main controls pass.
  Native callback counters verify repr/hash/index/conversion and comparisons
  have no side effects when an element is rejected. Exact integer controls,
  attributes, identity comparisons, reductions and early failures are covered.
  Final focused runs pass 110 ownership/slice/range tests in both builds
  (`test-slice-acquisition-sites.log`, `test-slice-release-final.log`).
  The three new tests also pass TSan without suppressions (`tsan-slice-final.log`).
  Logs: `test-slice-before.log`, `test-slice-debug-final.log` and
  `test-slice-release.log`. The initial debug command named a nonexistent
  `test_unicode` file; the final run uses `test_str`.
  Before the orphan-adoption change, reference-leak checks exposed retained
  LOCAL weakrefs after owner thread exit:
  the three new tests leak 96 references and blocks per measured repetition,
  and the existing `test_vm_heap_loads`/`test_sequence_element_operations`
  selection also leaks (114 per repetition). A separate native probe doing no
  slice operations leaves three LOCAL weakrefs per departed group on its BRC
  queue, even after ten collections; they are dead and have no callbacks.
  Its Main-only control is stable. Atomic adoption now fixes this queue leak;
  `orphan-leak-final.log` records zero retained references for the foreign-group
  reproducer, and `test-orphan-refleak.log` passes the existing VM/sequence cases
  and the new adoption tests with `-R 3:3`. The subsequent callback policy
  skips inaccessible finalizers instead of moving their dependencies. Existing
  `test_slice` alone passes `-R 3:3`. Earlier failure logs:
  `test-slice-refleak.log`, `test-default-startup-ownership-refleak.log`,
  `departed-weakref-probe.log` and `test-slice-main-refleak.log`.
- The full ThreadGroup file at `df77299a32` passes TSan from normal startup:
  46 tests, one mimalloc-only skip. No suppressions are used. This expands the
  earlier seven-case startup selection without proving owner-correct LOCAL
  reclamation. Log: `tsan-default-groups-audit.log`.
- Group-only serialization from normal startup: debug and release each pass
  964 tests across groups, ownership, reclamation, GC, threading, signal,
  memory/misc/eval C APIs, fork and embedding (19 and 37 skips). Both retain
  `Py_GIL_DISABLED=0` and a 24-byte object header. The default-path concurrency
  assertion fails before activation and passes afterwards; Main remains
  serialized. Activation also exposed an invalid mimalloc OS-thread/GIL
  assertion when exclusively clearing an inactive thread's heaps, including
  Main-only shutdown and fork cases. Cleanup now checks the finalizing state
  at its caller. The QSBR fixture explicitly detaches its caller before letting
  the worker test quiescence; debug reference totals include queued references,
  and foreign immutable heap allocations may await GC draining their BRC queues.
  Main's immediate reclamation assertion is retained. Five selected tests pass
  `-R 3:3`; seven scheduling, allocation, QSBR and accounting tests pass TSan
  without suppressions. That TSan build includes pymalloc but not mimalloc;
  debug and release cover mimalloc cleanup. Logs:
  `test-default-startup-before.log`, `test-default-startup-audit.log`,
  `test-default-startup-cleanup.log`, `test-default-startup-debug-final.log`,
  `test-default-startup-release-final.log`, `test-default-startup-refleak.log`
  and `tsan-default-startup.log`. These results do not settle LOCAL finalization
  in another group or the unchecked C getter macro contract.
- Pymalloc metadata synchronization: debug and release each pass 569 tests
  across groups, GC, memory/misc C APIs, embedding and fork with
  `PYTHONMALLOC=pymalloc_debug` (12 and 30 skips). The three allocator tests
  pass `-R 3:3` and a normal debug TSan build with pymalloc enabled, without
  suppressions. The original parallel probe aborts on a corrupted pool before
  synchronization. A separate Main-only raw-hook reproducer also verified that
  holding the new mutex across a detaching raw fallback deadlocks; the final
  lock scope fixes this and has a permanent regression test. Logs:
  `test-pymalloc-parallel-before.log`, `test-pymalloc-raw-detach-before.log`,
  `test-pymalloc-raw-detach-after.log`, `test-pymalloc-debug-final.log`,
  `test-pymalloc-release-final.log`, `test-pymalloc-refleak-final.log` and
  `tsan-pymalloc-final.log`.
- Code and descriptor metadata acquisition: debug and release each pass 291
  tests across ownership, code, codeop and descriptors (two skips). All three
  new tests pass `-R 3:3` and TSan without suppressions. Before the fix, 16
  foreign-group subcases fail while their Main controls pass. Logs:
  `test-code-metadata-before.log`, `test-code-metadata-debug.log`,
  `test-code-metadata-release.log`, `test-code-metadata-refleak.log` and
  `tsan-code-metadata.log`. The separate Main-only compatibility rerun still
  fails only the selected pickle mapping and descriptor tutorial cases below
  (`test-main-compat-audit.log`); their implementations and expectations are
  unchanged.
- Evaluation name metadata: debug and release each pass 346 tests across
  ownership, C API eval, function attributes, classes and calls. Both new tests
  pass `-R 3:3` and TSan without suppressions. Three foreign-name acquisition
  subcases fail before the runtime fix; Main and non-acquiring controls pass.
  The test wrapper also previously segfaulted on Main alone when a function name
  contained an unencodable surrogate. Logs: `test-funcname-before.log`,
  `test-funcname-surrogate-before.log`, `test-funcname-debug.log`,
  `test-funcname-release.log`, `test-funcname-refleak.log` and
  `tsan-funcname.log`.
- Pending-call notification and handler arbitration: the release build passes
  730 tests across groups, C API misc, threading, signal and GC (22 skips).
  The debug selection initially fails only on a one-argument fixture accidentally
  discovered as a no-argument `test_*` helper. After renaming it, C API misc's
  318 tests pass on rerun; the other four files already passed.
  Both new native pending-call tests and the renamed fixture's caller pass
  `-R 3:3` and TSan without suppressions. Before the fix, native group queues
  stall and a contended Main-only call loses its notification. Logs:
  `test-pending-native-before.log`, `test-pending-handoff-before.log`,
  `test-pending-debug.log`, `test-pending-debug-misc-final.log`,
  `test-pending-release.log`, `test-pending-refleak.log` and
  `tsan-pending-final.log`.
- A temporary normal release build with group serialization from startup
  reproduced a Main-only timeout in `TestPendingCalls.test_max_pending`; the
  pending-call fix removes it. A six-file audit then runs 789 tests, with failures
  in C API misc (the fixture name above), sys (expects the interpreter GIL to be
  enabled), and the allocation probe (expects immediate foreign-group frees).
  Separate measurements confirm Main-group allocations are reclaimed promptly;
  a foreign group's immutable tuple and its bytes need two collections to drain
  their BRC queues. The verbose group rerun reproduces the two allocator
  subcases; the initial run reports three subcase failures without identifying
  the extra failure, so this audit is not a completed parallel-runtime gate.
  The startup initializer was restored after the experiment. Logs:
  `test-default-parallel-before.log`, `test-default-parallel-audit.log`,
  `test-default-parallel-threadgroup-details.log` and
  `test-default-parallel-allocation-details.log`.
- Descriptor qualified-name caches: debug and release builds each run 469 tests
  across six files successfully (three and six skips). The three new tests pass
  `-R 3:3` and TSan without suppressions. Before the fix, concurrent native
  readers trigger a TSan race, cold lookup reads a foreign LOCAL class, and
  metaclass reentry followed by an exception aborts the debug build even with
  Main alone. Logs: `tsan-descriptor-before.log`,
  `test-descriptor-owner-before.log`, `test-descriptor-reentrant-before.log`,
  `test-descriptor-debug.log`, `test-descriptor-release.log`,
  `test-descriptor-refleak.log` and `tsan-descriptor.log`.
- C API instance-method wrappers: debug and release builds each run 694 tests
  across seven files successfully (one and two skips). Three selected tests
  pass `-R 3:3` and TSan without suppressions. Before the fix, 23 foreign
  subcases fail across the borrowed getter, calls, attributes and comparison.
  Descriptor binding still copies the stored reference; invoking the resulting
  bound method rejects a foreign function. Logs: `test-instance-methods-before.log`,
  `test-instance-methods-debug.log`, `test-instance-methods-release.log`,
  `test-instance-methods-refleak.log` and `tsan-instance-methods.log`.
- Bound-method attributes and slots: debug and release builds each run 692
  tests across seven files successfully (one and two skips). The three new
  tests pass `-R 3:3` and TSan without suppressions. Before the fix, 22 foreign
  subcases fail, including private-name reduction for an immutable instance
  with a LOCAL class. Controls preserve operations that only copy or compare
  receiver references. Ten existing method pickle round-trip tests also pass;
  no pickle implementation or compatibility test is changed. Logs:
  `test-method-metadata-before.log`, `test-method-metadata-debug.log`,
  `test-method-metadata-release.log`, `test-method-metadata-refleak.log`,
  `test-method-metadata-roundtrip.log` and `tsan-method-metadata.log`.
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
- Known Main-only failure: `test_baseexception.ExceptionClassTests.test_inheritance`
  compares builtin exceptions with `Lib/test/exception_hierarchy.txt`, which
  does not list `IllegalThreadAccessException`. The isolated test fails in both
  the current build and `d800afe949`; neither the test nor its fixture differs
  from the CPython base. Reproduce with
  `./python -m unittest test.test_baseexception.ExceptionClassTests.test_inheritance`.
  Logs: `test-exception-hierarchy-current.log` and
  `test-exception-hierarchy-baseline.log`.
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
- Known Main-only failure after group-only startup:
  `test_sys.SysModuleTest.test_is_gil_enabled` expects the interpreter-wide GIL
  to be enabled in a normal configured build. The runtime now reports false,
  while threads within Main remain serialized. The existing test is unchanged.
  A standalone rerun also confirms the pickle mapping failure above, and
  `test_descrtut` still fails only its fixed listing. Logs:
  `test-default-startup-main-compat.log` and
  `test-default-startup-main-descrtut.log`.
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
