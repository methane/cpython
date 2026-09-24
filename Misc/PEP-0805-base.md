# PEP 805 runtime foundations

This branch isolates the first five stages of the
[implementation strategy](https://peps.python.org/pep-0805/appendix-implementation/#implementation-strategy)
from `experimental/pep-805` at `9a4de37db8`. Its CPython base is
`6dad8b88cc39d8f9f41c22502a0b52304b326dd9`.

The specification is [PEP 805](https://peps.python.org/pep-0805/) and its
[implementation appendix](https://peps.python.org/pep-0805/appendix-implementation/).
The appendix's sample object layout is illustrative. Its ownership rules,
same-group serialization, parallel groups and immediate reclamation of ordinary
LOCAL objects are requirements, not optional optimizations.

| Stage | Completion criteria | Current status |
| --- | --- | --- |
| ThreadGroups | Main identity and lifetime, explicit/default group selection, serialization, parallel execution, detach/reattach, fork and shutdown | Extracted; initial regressions pass, lifetime audit remains |
| One-time ABI change | Owner/state metadata with room for later states; no per-object cleanup queue fields; consistent native layouts | Compact header implemented and checked in the normal build; remaining runtime port in progress |
| Biased and deferred reference counting | Port the necessary PEP 703 mechanisms into the normal build; same-group LOCAL reclamation remains immediate | Group-biased RC works in the normal build; deferred/per-thread RC and parallel queue collection remain |
| LOCAL and IMMUTABLE ownership | Correct initialization and checked C API/VM reference acquisition; shallow immutable containers do not expose foreign LOCAL values | Pending |
| Parallel allocation and cyclic GC | Concurrent allocation/collection, safe foreign traversal, finalization and interpreter teardown | Pending |

Freezing, protective/compound locks, synchronized collections, TransferBox,
Channel, the debugger StopTheWorld API, and performance optimization are later
stages and are excluded. Internal GC world stops remain part of the runtime.
Windows and native machine-code JIT validation remain outside the current scope.
Enabling `--disable-gil` is not the implementation of stages three and five.
The normal build must acquire the required reference-counting, allocation and
GC mechanisms without selecting the free-threading build. The final header
layout must also be assessed against the appendix, not obtained by appending
all ownership and cleanup fields to the PEP 703 layout.

## Extraction provenance

`7201b6539e` was applied with `git cherry-pick --no-commit`. That commit mixes
all stages, so only the ThreadGroup scheduler, native wrapper, thread-state
integration and Python group-selection changes are retained in the first split.
The higher-stage module, collection, lock and debugger changes are excluded.
Subsequent fixes will identify their original commits when carried over.
The native scheduler probes use raw atomic flags and events. They test
execution rights without transporting Python functions, Events or mutable
Python result containers into another group.

The new scheduler tests initially validate the isolated first stage before
ownership is enabled. They do not establish completion of stages two through
five or conformance to the full PEP.

First split validation: Linux/aarch64 debug build configured with
`--with-pydebug --disable-gil`. `test_threadgroup`, `test_threading`,
`test_thread`, `test_fork1`, `test_gc` and `test_embed` pass with `-X gil=0 -j2`:
445 tests, 17 skips. Build and test logs are under `/tmp/pep805-base/`.
The optional _decimal module is unavailable. These checks precede the default
port of the reference-counting runtime and ownership enforcement.

`d92bde8de7` was applied with `git cherry-pick --no-commit` for fixed GIL
configuration during extension imports and classic defaults for context
inheritance and warnings. Its change of the configure default has been
reverted: selecting the free-threading build is not the port described by
the implementation strategy. Its later-stage
ownership and synchronized-container changes are excluded. After rebuilding,
`test_threadgroup`, `test_capi.test_config`, `test_capi.test_module`,
`test_import`, `test_importlib` and `test_embed` pass: 1,480 tests, 40 skips.
That validation used the explicit `--disable-gil` configuration and does not
establish completion of the normal-build port.

The scheduler probes have also been checked in a clean normal build:
`./configure --with-pydebug`, `Py_GIL_DISABLED=0`, `sys.abiflags == "d"`.
`test_threadgroup`, `test_local_reclamation`, `test_capi.test_object`, `test_gc`,
`test_threading` and `test_embed` pass: 429 tests, 13 skips. Parallel execution
is still skipped in that build until the runtime port is complete. The local
reclamation checks at this point do not establish biased-RC correctness.

The reference-counting bias is to be a ThreadGroup, not an OS thread. Group
ownership must survive exit of the allocating thread. The object header will
not retain an OS thread ID or per-object deferred-cleanup queue fields.

The normal build now uses a 24-byte `PyObject` on 64-bit platforms: a 32-bit
owner/bias ID, an 8-bit local count, state, flags and GC bits, a pointer-sized
shared count and a type pointer. The shared count retains PEP 703's two flag
bits. The local count's reserved immortal value is never reached by ordinary
increments: overflow merges the count into the shared field. Ownership is
preserved on merging, resurrection and thread exit. There is no object mutex,
OS thread ID or deferred-cleanup linkage in this header.

Normal debug validation (`Py_GIL_DISABLED=0`, interpreter GIL still enabled):
`test_threadgroup`, `test_local_reclamation`, `test_capi.test_object`,
`test_capi.test_misc`, `test_gc`, `test_threading`, `test_embed`, and `test_sys`
pass: 844 tests, 21 skips. The first four targeted RC/GC files
(`test_threadgroup`, `test_local_reclamation`, `test_capi.test_object`, `test_gc`)
also pass `-R 3:3` without reference leaks. The native probes cover two live OS
threads in one group, reuse after creator-thread exit, foreign shared counts,
and local-count overflow. The Python reclamation tests cover finalizers,
weakrefs and resurrection with GC disabled, plus bulk reference-count overflow.
The local-reclamation guards and tests were selected from `a26d4fff4c` using
`git cherry-pick --no-commit`, with later-stage functionality excluded.

This is an intermediate normal-build port, not completion of the five stages.
In particular, the old free-threading collector still assumes OS-thread IDs
and a larger local counter; it must not be selected with this header. The normal collector now handles biased and deferred counts.
Ownership access checks and parallel execution are not enabled yet.

Deferred reclamation is now also enabled in the normal build for immutable,
GC-tracked objects. The normal generational collector excludes the deferred
sentinel when finding roots and removes it while holding a real reference
before reclaiming garbage. Tuples with deferred counts remain tracked. Shutdown
collections disable further deferral and restore ordinary RC for survivors,
including objects retained until interpreter-dict cleanup.

`test_deferred_reclamation`, `test_local_reclamation`, `test_threadgroup`,
`test_capi.test_object`, `test_gc` and `test_embed` pass: 192 tests, 9 skips.
`test_deferred_reclamation`, `test_gc` and `test_capi.test_object` also pass
`-R 3:3` without reference leaks. These tests include cyclic and acyclic
immutable containers, resurrection, weakref callbacks and late shutdown.
This does not yet port deferred VM stack references or per-thread counts;
those remain necessary before declaring the reference-counting stage complete.

Per-thread counting for deferred immutable code objects now supplements the
ThreadGroup bias. Code objects are GC-tracked in the normal build, and the
collector merges thread tables before computing reachability. It disables
unique IDs before finalizers can resurrect garbage. Thread exit flushes its
counters; LOCAL types and dictionaries continue to use ordinary biased RC.
`test_deferred_reclamation`, `test_local_reclamation`, `test_threadgroup`,
`test_capi.test_object`, `test_code`, `test_gc`, `test_funcattrs`, `test_sys`
and `test_embed` pass (375 tests, 17 skips). After adding code-specific
thread-exit and resurrection tests, `test_deferred_reclamation`, `test_code`
and `test_capi.test_object` also pass `-R 3:3` (66 tests, one skip).
Deferred VM stack references are still being ported.
