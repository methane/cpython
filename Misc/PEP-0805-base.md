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
| LOCAL and IMMUTABLE ownership | Builtin/static metadata, public `__shareable__` state, common C API returns, VM heap loads, attributes and call expansion | Remaining API/VM acquisitions and shared static extension ownership |
| Parallel allocation and cyclic GC | Normal generational collector understands biased, deferred and per-thread counts | Concurrent allocation, internal world stops, owner-correct finalization and teardown |

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
been destroyed. Simultaneous use of managed static extension types by multiple
interpreters needs a design decision; see the
[Japanese questions](PEP-0805-open-questions-ja.md).

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
