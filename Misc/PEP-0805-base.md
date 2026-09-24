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
| One-time ABI change | Owner/state metadata with room for later states; no per-object cleanup queue fields; consistent native layouts | Pending |
| Biased and deferred reference counting | Port the necessary PEP 703 mechanisms into the normal build; same-group LOCAL reclamation remains immediate | Pending |
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
The native barrier helper comes from `d92bde8de7` and validates simultaneous
execution while both threads retain their groups' execution rights.

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
