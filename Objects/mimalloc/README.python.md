# CPython's mimalloc copy

Upstream: https://github.com/microsoft/mimalloc/tree/v2.5.2

Version: **2.5.2**, commit `2406cc5f3ab6d6e54fe560cdd66fa46eee775312`.
The GitHub tag archive used for this update has SHA-256
`5cf9d2a10fae5551b764e888a623da411c6c6beb0221b847f83492ab1932bdab`.

`src/` is copied here; `include/mimalloc.h`, `include/mimalloc-stats.h`,
and `include/mimalloc/*.h` are under `Include/internal/mimalloc/`.
Trailing whitespace is removed, as in the original CPython import.
The MIT license is reproduced in `Doc/license.rst`.

## Local changes

* QSBR fields in heaps/pages and hooks in `heap.c`, `page.c`, and `segment.c`
  delay page reclamation until optimistic readers have finished. This includes
  forced abandonment, retired pages, abandoned pages, and the full queue fix
  from GH-145626. Empty pages may remain allocated while waiting for QSBR.
* `alloc.c` and `free.c` preserve object headers during debug filling.
  The free-list next field uses relaxed atomic accesses in `internal.h`.
* Heap visiting drains the heap's delayed-free list first; abandoned visiting
  collects page free lists before computing `area.used`, even when the caller
  only requests areas. GC must not visit freed blocks as Python objects.
* The owner-thread assertion in delayed freeing is disabled for free-threaded
  GC, which visits other threads' heaps under stop-the-world synchronization.
* `os.c` checks that the default heap is initialized before accessing its
  random state (CPython can initialize on a background thread).
* `alloc.c` prefixes the weak C++ new-handler symbol with `_Py`.
  `free.c` suppresses the heuristic heap-region warning, and `os.c` reports
  normal aligned-allocation fallback only at trace verbosity.
* `random.c` and the Linux overcommit query retain explicitly zero-initialized
  local buffers from the original import. Cygwin uses `arc4random_buf()`.
* `types.h` and `mimalloc-stats.h` include their dependencies relative to
  themselves so installed internal headers do not require an additional
  include search directory.

`pycore_mimalloc.h` supplies the CPython debug bytes, debug level, TSAN setting,
and free-threaded thread ID. It disables guarded allocations and enables
`MI_VISIT_ABANDONED` at compile time for free-threaded builds. GC visibility
must not depend on a user's environment-variable setting.

Each free-threaded interpreter has its own upstream subproc, and each Python
thread state retains its four tagged heaps and TLD. We assign the subproc to
that TLD directly: an OS thread may run multiple Python thread states, so
`mi_subproc_add_current_thread()` is not the appropriate interface here.
Subproc metadata is released only once no abandoned segments reference it.
Segments surviving interpreter teardown, and their subproc metadata, are
retained rather than leaving dangling interpreter pointers.

## History audit for the 2.5.2 update

Audit baseline: CPython `2d1007f931963ef907460ddaa110bac4e635eebd`.
The source/header path history has **41 commits after the initial import**
`05f2f0ac92a`. The audit also checked allocator integration outside those paths.

Issue https://github.com/python/cpython/issues/113141 and its comments are
useful records, but **do not enumerate every local change**. In particular,
the original import already renamed the new-handler symbol, suppressed two
warnings, and zero-initialized two buffers. Comparing the original import
against upstream v2.1.2, ignoring whitespace, identifies these five changes.

In the table, "upstream" means the old patch need not be reapplied, not that
the old patch applies textually. Platform classifications are based on source
inspection; they do not claim native testing on those platforms.

| CPython commit / PR | Change | Disposition in 2.5.2 |
| --- | --- | --- |
| `1673e440174` / #111524 | WASI sbrk declaration | Upstream: `unistd.h` in the sbrk branch |
| `801741ff815` / #111527 | Windows ARM64 atomics | Upstream: read-only volatile loads/barriers replace the old CAS loop |
| `794dff2fb1d` / #111593 | AIX build | Upstream: restricted syscall-header selection |
| `0ff6368519e` / #111907 | FreeBSD unused functions | Upstream: inline primitive wrappers |
| `9afb0e1606c` / #113372 | mmap hint warnings | Upstream: trace-level messages |
| `acf3bcc8861` / #113263 | Separate GC heaps | Upstream `_mi_tld_init` and `_mi_heap_init`; update CPython calls |
| `fcb3c2a4447` / #113717 | Interpreter isolation | Replace local abandoned pools with upstream subprocs |
| `0b7476080b5` / #113742 | Heap/page tags | Upstream heap `tag`, page `heap_tag`, matching-tag reclamation |
| `ae968d10326` / #112807 | Solaris unused functions | Upstream inline wrappers |
| `10d3f04aec7` / #112809 | Solaris large-page size | Upstream `_mi_os_large_page_size()` |
| `412920a41ef` / #114133 | Heap/abandoned visiting | Upstream bitmap/fast division and visiting APIs; retain heap delayed-free collection |
| `31633f44739` / #115188 | Accurate allocated-block counts | Upstream normal-area ordering; retain early collection for abandoned areas |
| `326119d3731` / #115488 | CPython thread ID | Upstream `MI_PRIM_THREAD_ID` hook; keep CPython's definition |
| `cc82e33af97` / #115573 | Preserve refcount fields | Retain `debug_offset` and debug-fill helper |
| `d7ddd903083` / #116153 | Debug-fill helper warning | Keep helper inline |
| `e7ba6e9dbe5` / #116345 | Typos | Use upstream comments |
| `72714c0266c` / #116343 | Internal debug assertions | Keep `MI_DEBUG=2` and cross-thread GC assertion exception |
| `c012c8ab7bb` / #115435 | QSBR | Retain, adapting all reclamation paths |
| `2067da25796` / #117548 | OpenBSD build | Upstream syscall selection/inline wrappers |
| `3fe03ccea61` / #117809 | s390x huge allocation | Upstream size limit and size_t block sizes |
| `71cc0651e79` / #118808 | Relative includes | Upstream for existing headers; adapt new stats header include |
| `6a97929a5ad` / #120188 | Comment typo | Use upstream comments |
| `0153fd09401` / #120821 | Comment typo | Use upstream comments |
| `31873bea471` / #121488 | ATOMIC_VAR_INIT warnings | Upstream C17/C++20 guards |
| `d005f2c1861` / #121732 | GNU/Hurd build | Upstream `fcntl.h` include |
| `d061ffea7b4` / #123052 | Background initialization | Retain initialized-heap checks in both address-hint paths |
| `9e108b87197` / #123336 | Typos | Use upstream comments |
| `9017b95ff2d` / #123775 | Typos | Use upstream comments |
| `4a6b1f17966` / #123827 | NetBSD unused functions | Upstream inline wrappers |
| `feda9aa73ab` / #125574 | Old ARM thread pointer | Upstream thread-pointer/TLS platform selection |
| `03f6c8e2397` / #131784 | ARM yield | Upstream `__ARM_ARCH` check and nop fallback |
| `317c4962239` / #134238 | Atomic free-list access | Retain relaxed atomic loads/stores |
| `c6003106632` / #134624 | Assertion attributes | Upstream noreturn/cold/noexcept declaration |
| `b525e31b7fc` / #134994 | Old compiler atomic typing | Retain atomic pointer casts (also explicit on stores) |
| `698bab5a403` / #136086 | Comment typo | Use upstream comments |
| `561212a0330` / #136299 | Comment typo | Use upstream comments |
| `73fa6be2fe6` / #144620 | C++ assertion declaration | Upstream trailing noexcept |
| `d76df75f51e` / #145626 | QSBR page leak | Retain queue re-fetch, owner TLD, and goal invalidation rules |
| `fdf064ca810` / #148462 | Cygwin randomness | Retain `__CYGWIN__` in arc4random branch |
| `80f9467434c` / #151066 | Thread metadata leak | Upstream preserves memid during cache clearing/OS allocation |
| `8b2433af48d` / #152477 | UWP build | Upstream dynamic NUMA calls and LONG status types replace the patch |

Outside the vendored paths, retain current GC synchronization and heap
initialization publication (#119923), debug realloc/fill behavior (#116018),
C++ header context (#122587), QSBR batching (#135473), raw allocation routing
(#144916), and interpreter teardown behavior (#153176). Header installation,
Makefile dependencies, and Windows project lists must include new upstream
files. These integration changes are not additional patches to upstream
mimalloc, but are part of the compatibility surface of an update.

## Updating again

Compare the current files with the recorded upstream tag, not just issue
#113141. Reconcile that diff with the path history, including the initial
import, and inspect CPython's allocator/GC/thread-state callers. Preserve the
QSBR invariants when upstream adds allocation or reclamation paths. Validate
debug and release builds with and without the GIL, installed headers, symbol
visibility, and the memory, GC, embedding, and free-threading tests.
