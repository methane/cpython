# PEP 805 implementation review and questions for Mark

Reviewed on 2026-09-23 against commit `29709794bc`.

Sources: [PEP 805](https://peps.python.org/pep-0805/),
[implementation appendix](https://peps.python.org/pep-0805/appendix-implementation/),
and [examples appendix](https://peps.python.org/pep-0805/appendix-examples/).
The PEP page reports its last modification as 2026-08-27.

This is an audit of the current experiment, not a claim of conformance.
Windows and native JIT execution were excluded as previously agreed. Code
inspection and targeted execution cannot establish coverage of every native
reference acquisition. No implementation changes were made for this review.

## Findings that do not need a specification decision

1. **The default build still serializes different ThreadGroups.**
   `_PyEval_AcquireLock()` acquires both the group lock and the interpreter
   GIL (`Python/ceval_gil.c:592`). `Include/refcount.h` still selects ordinary
   reference counting for that build. This is unfinished work, not an
   ambiguity about whether parallel ThreadGroups are required.
   See [parallelism](https://peps.python.org/pep-0805/#parallelism-and-context-switching)
   and the appendix's
   [implementation strategy](https://peps.python.org/pep-0805/appendix-implementation/#implementation-strategy).

2. **Reusing free-threading BRC has not preserved immediate LOCAL reclamation.**
   In the same-group example below, the free-threading build prints
   `['after del', 'finalized']`; the GIL build prints
   `['finalized', 'after del']`. The object is acyclic and is held in an
   ordinary local list, not a synchronized collection. The reference-count
   fast path still tests the OS-thread owner (`Include/refcount.h:352`).
   This needs to be reconciled with
   [deferred reclamation](https://peps.python.org/pep-0805/#deferred-reclamation).

   ```python
   import threading

   events = []
   class Value:
       def __del__(self):
           events.append('finalized')

   values = [Value()]
   def worker():
       value = values.pop()
       del value
       events.append('after del')

   t = threading.Thread(target=worker)  # Same Main ThreadGroup.
   t.start()
   t.join()
   print(events)
   ```

3. **Protected-reference validity is not established before removing input
   checks.** The following ordinary Python program aborts in
   `PyObject_GetItem`'s assertion in both current debug builds. At the previous
   commit, `0b0b55a5f4`, the free-threading build raises
   `UnprotectedAccessException` instead. This is a regression in the last
   change, not merely a missing optimization. Release-build behavior was not
   executed in this audit.

   ```python
   import threading

   lock = threading.Lock()
   def source():
       with lock:
           yield lock.protect([42])

   def probe():
       generator = source()
       value = next(generator)
       print(value[0])
       generator.close()       # Ends the protecting context.
       print(value[0])          # Aborts instead of rejecting the access.

   probe()
   ```

   `Python/flowgraph.c:3818` only marks locals assigned lexically within a
   `with`; `value` above is not one of them. Ordinary `LOAD_FAST` also lacks
   the accessibility assertion envisaged by the appendix's
   [debug validation](https://peps.python.org/pep-0805/appendix-implementation/#validation).
   Mark's incoming-reference contract is the target invariant, but the
   current VM does not yet maintain it.

4. **The previous input-check change also left a native test helper using
   the old contract.**
   `test_function_shareable.test_namespace_replacement_ownership` now aborts
   in `PyObject_SetAttrString`; it passes at `0b0b55a5f4`.
   `function_set_from_tuples` deliberately uses unchecked `PyTuple_GET_ITEM`
   loads before calling the setter (`Modules/_testcapi/function.c:176`).
   The helper/boundary audit is unfinished. This test failure alone should
   not be presented as proof that the setter needs runtime input checks.

5. **A published PEP example is unsupported.**
   `with lock: value = lock.protect(iter((1, 2)))` raises
   `TypeError: protect() does not support this native object layout` in both
   builds. `lock_protected_copy()` only handles exact lists/dicts/sets and
   selected Python instance layouts (`Modules/_threadmodule.c:1749`).
   The [tuple iterator example](https://peps.python.org/pep-0805/appendix-examples/#tuple-iterator)
   therefore cannot run as written.

6. **Public state inspection has an initialization dependency.**
   `object().__shareable__` raises `RuntimeError: threading module is not
   initialized` until `threading` is imported, although
   `sys.main_thread_group` already exists. `_PyObject_GetShareable()` looks
   up the Python enum through `sys.modules` (`Objects/object.c:3292`). This
   dependency is not described by the advertised attribute API.

7. **Owner-group finalization is still broken in a tested case.**
   `test_finalizer_access.test_finalizer_after_owner_thread_exits` fails with
   an unraisable `IllegalThreadAccessException`. This is also reproducible
   before the last commit. It is a current defect even though that commit
   did not introduce it.

8. **Header size does not follow the appendix's compact-layout direction.**
   Measured `object.__basicsize__` is 40 bytes in the GIL build and 56 bytes
   in the free-threading build on this 64-bit host. The illustrative
   [header](https://peps.python.org/pep-0805/appendix-implementation/#object-state)
   occupies 24 bytes with this ABI's usual layout. That exact layout is a
   suggestion, not a mandatory ABI. Explaining the current three cleanup
   fields does not justify their permanent cost or resolve Mark's concern.

9. **Extension type sharing has acquired an undocumented automatic opt-in.**
   `Objects/typeobject.c:5875` automatically declares constructed immutable
   extension types shareable, and `Objects/object.c:3133` handles initialized
   static immortal types similarly. For example, `_testcapi.matmulType` is
   IMMUTABLE without that extension's own PEP 805 declaration. The
   [extension defaults](https://peps.python.org/pep-0805/#c-extensions-and-the-c-api)
   do not describe `Py_TPFLAGS_IMMUTABLETYPE` as an opt-in. This exemption
   should be removed or separately proposed as a specification change; the
   current implementation must not be treated as establishing that policy.

## Questions to discuss with Mark

### 1. How is reference validity maintained when protection ends in another frame?

The generator example above creates a valid reference, then invalidates its
protection through a later call. Similar issues arise with suspended
coroutines, callbacks, debugger contexts and C locals retained across calls.

Is yielding/awaiting while holding a protective context supported? If so,
what is the intended invalidation rule for existing frame locals and
evaluation-stack/C references when a call ends that protection? Should the
compiler model potentially invalidating calls, should the runtime validate
affected frames on context exit, or is another restriction intended?
The lexical analysis in the
[compiler appendix](https://peps.python.org/pep-0805/appendix-implementation/#bytecode-compiler)
does not settle these cases. The need to reject the unsafe access is clear;
the question is how to maintain the incoming-reference invariant.

### 2. What is the accessibility contract of unchecked C API macros and borrowed outputs?

`PyList_GET_ITEM` and `PyTuple_GET_ITEM` still read storage directly
(`Include/cpython/listobject.h:44`, `Include/cpython/tupleobject.h:30`).
An accessible shallow tuple can contain an inaccessible local object, so
checking the tuple alone cannot validate such a load.

Must these macros gain checked semantics, become explicitly unsafe APIs
requiring caller changes, or be replaced by distinct checked/unchecked
interfaces? If a formerly infallible macro can return NULL, how should
existing extensions handle the new failure? What is the corresponding rule
for borrowed references and output-parameter APIs? This boundary needs an
explicit decision to satisfy the
[C API and extension contracts](https://peps.python.org/pep-0805/#c-extensions-and-the-c-api),
without reinstating checks on every operation.

### 3. Is a unique source reference a requirement for `protect()`, or only a copy-elision condition?

The current implementation rejects even `value = []; lock.protect(value)`
inside the owning context and accepts a temporary such as `lock.protect([])`.
It nevertheless creates a shallow copy.

The [operation table](https://peps.python.org/pep-0805/#allowed-operations)
and the [copying / del-expression discussion](https://peps.python.org/pep-0805/#make-del-an-expression)
leave the relationship between copying and uniqueness unclear. Is an aliased
source safe because the protected result is a distinct copy, or is the
source required to be unique regardless? If uniqueness is mandatory, what
is the supported ownership-consuming idiom before a `del` expression exists?

### 4. Does shallow transfer include an instance's own attribute storage?

`TransferBox.claim()` changes only the copied object's `ob_owner_id`
(`Modules/_threadmodule.c:387`). A transferred ordinary Python instance can
currently return a primitive `obj.x` in the receiving group while accessing
`obj.__dict__` raises `IllegalThreadAccessException`. This was reproduced in
both builds. By contrast, protection explicitly copies and protects an
instance's dictionary (`Modules/_threadmodule.c:1797`).

Should an instance's fresh dictionary be considered part of the transferred
object, with only its attribute values remaining shallow references? Or
should the dictionary retain the sender's owner like any other referenced
object? What constraints should apply when `__copy__` supplies shared or
aliased instance storage?
See [mutable-value transfer](https://peps.python.org/pep-0805/#passing-mutable-values-between-parallel-threads)
and [object dictionaries](https://peps.python.org/pep-0805/#object-dictionaries).

### 5. Should local reference-count ownership be biased to a ThreadGroup?

The current branch uses PEP 703's OS-thread bias in the free-threading build.
The same-group reclamation counterexample above shows that simply retaining
that implementation is insufficient for the stated LOCAL lifetime behavior.

Is the intended design a group-biased local count, rebiasing/merging on group
handoff, or a different mechanism? The required observable behavior is not
the question; the representation and handoff strategy are. The proposed
compact header and the default-build port should be designed together.
See [reference counting](https://peps.python.org/pep-0805/appendix-implementation/#reference-counting).

### 6. Where must finalizers and weakref callbacks run, and what cleanup guarantees are required during world stops?

The implementation dispatches foreign LOCAL finalizers to a newly created
thread in the owner group, acquires a PROTECTED object's mutex for its
finalizer, and dispatches weakref callbacks to their registration group
(`Modules/_threadmodule.c:2251`, `Modules/_threadmodule.c:3632`). An abandoned
unclaimed transfer is instead adopted by the group clearing its box.
These are substantial implementation choices, not specified callback rules.

Are those affinity rules intended, including when the original thread has
exited or the interpreter is shutting down? May finalization create a thread
or block on a protecting mutex? What should happen to unclaimed transfers
and objects whose lock wrapper has died?

Separately, is it necessary to retain arbitrarily many explicit non-GC
`PyObject_CallFinalizer` requests during an internal world stop, even under
allocator failure? That is the current queue's self-imposed/tested guarantee
(`Objects/object.c:585`), and it drove the three `ob_deferred_*` fields.
The PEP does not establish that guarantee. We should agree on the cleanup
contract before treating these fields as necessary or choosing an
out-of-header representation.

### 7. Can a published synchronized function become LOCAL after mutation?

The current implementation classifies read-only cell bindings as shareable,
then changes dependent functions from SYNCHRONIZED to LOCAL if a cell becomes
writable. This can happen even when its value remains an immutable integer:

```python
import threading
def factory():
    value = 42
    return lambda: value
f = factory()
print(f.__shareable__.name)   # SYNCHRONIZED
f.__closure__[0].cell_contents = 43
print(f.__shareable__.name)   # LOCAL
```

Is this dynamic reclassification intended, or should mutation be rejected
once a binding/function has been published as shareable? If reclassification
is allowed, which group becomes the owner, and how are references already
held by other groups invalidated? The code performs world-stop updates and
heap scans (`Objects/funcobject.c:116`), but the
[function specification](https://peps.python.org/pep-0805/#classes-functions-and-modules)
does not define this transition protocol.

### 8. Do the primitive/result-check exemptions apply only to exact builtin types?

The implementation treats exact `str` as intrinsically immutable and Python
subclasses as LOCAL. A custom `__str__` returning a `str` subclass causes
`str(obj)` to return that LOCAL subclass in the current build. Consequently
the appendix's suggested exemption for `PyObject_Str` needs qualification.

Should exact types alone receive the primitive guarantees, while subclass
results continue to be checked? Or should some APIs normalize results to
exact primitive types? This affects both access-check elision and the
no-context-switch guarantee. See
[primitive types](https://peps.python.org/pep-0805/#primitive-types) and
the appendix's [C API discussion](https://peps.python.org/pep-0805/appendix-implementation/#c-api).

## Validation performed

- Ran the 17 focused suites for sharing, ThreadGroups, protection, transfer,
  channels, freezing, synchronization, function sharing, protected locals and
  world stops, in separate worker processes. Sixteen files passed;
  `test_function_shareable` aborted. The runner reported 300 completed tests
  across the run; this is not an all-pass count.
- Isolated the failing function-namespace test and verified it passes at
  `0b0b55a5f4` in a separately built free-threading debug checkout.
- Ran the protected-generator example in current free-threading and GIL
  debug builds and in the previous free-threading debug build.
- Ran the same-group finalizer, native iterator protection, instance transfer,
  header-size and state-inspection probes in both current build variants.
  The relevant source files in the separate GIL checkout match this commit.
- Re-ran the owner-thread-exit finalizer test and confirmed its current failure.

Broad mechanisms have passing targeted tests, but those successes do not
establish the reference-validity invariant. The proven regressions above and
the unfinished default-build architecture prevent treating this branch as a
complete reference implementation.
