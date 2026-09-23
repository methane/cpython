# PEP 805 implementation review and questions for Mark

Initial review on 2026-09-23 against commit `29709794bc`.
Follow-up implementation validated through commit `2fc691bbbe` on the same
date; see the resolved findings and validation below.

Sources: [PEP 805](https://peps.python.org/pep-0805/),
[implementation appendix](https://peps.python.org/pep-0805/appendix-implementation/),
and [examples appendix](https://peps.python.org/pep-0805/appendix-examples/).
The PEP page reports its last modification as 2026-08-27.

This is an audit of the current experiment, not a claim of conformance.
Windows and native JIT execution were excluded as previously agreed. Code
inspection and targeted execution cannot establish coverage of every native
reference acquisition. The follow-up repairs concrete defects; it does not
complete the reference-counting and parallelism architecture.

## Resolved findings from the initial audit

- **Finalizer dispatch:** an owner-group finalizer is now transported in an
  internal shallow tuple. The destination acquires the actual object after
  entering its owner group. Previously, constructing the dispatcher checked
  its foreign `self` in the sending group. The full finalizer suite now runs,
  including finalization after the original owner thread exits.
- **Native test helpers:** function setters and cell mutation helpers acquire
  references with checked tuple APIs before calling C APIs whose argument
  accessibility is asserted. The public setter argument checks stay asserts.
- **State inspection:** `__shareable__` lazily initializes its enum instead of
  raising merely because `threading` has not yet been imported. A clean-process
  test covers both a local object and an immutable primitive.
- **Tuple iterator protection:** exact tuple iterators now support protected
  shallow copying, including partially consumed and exhausted iterators. The
  PEP's wrapper example is exercised with two distinct ThreadGroups and an
  inaccessible nested element. Other native layouts still require explicit
  support; this does not make arbitrary extension objects copyable.
- **Extension defaults:** `IMMUTABLETYPE` alone no longer declares an extension
  type shareable. Only core static builtins receive that implicit treatment.
  Explicit declarations also publish the type namespace. Tests cover static
  and heap extension types, denied foreign acquisition, and explicit opt-in.
- **References surviving protection:** fast-local loads now conservatively
  check accessibility, including borrowed, fused and comprehension-save
  variants. Internal closure-cell transport remains separate from reading
  the cell contents. Call completion also checks the live evaluation stack
  for operands invalidated by the call; inlined Python returns check the
  caller stack after clearing the callee. Optimizers may no longer erase a
  checked local load as a pure push/pop pair.

  The initial generator example now raises `UnprotectedAccessException`, as
  do expressions such as `value[generator.close() or 0]`. A debugger pause
  ending in another frame likewise cannot leave usable foreign locals.
  Generator tests that formerly assumed an unchecked foreign local reached
  `YIELD_VALUE` now assert rejection at the local load, normal unwinding, and
  the producer's ability to catch that error. Native iterator result checks
  still have their separate coverage.

  This is a conservative correctness measure with additional runtime work,
  **not** the appendix's proposed near-zero-overhead local analysis. It does
  not prove the lifetime invariant for every callback, C local, or VM escape.
  Question 1 remains relevant to a complete, optimized solution.
- **termios error propagation:** ordinary operations now propagate failure
  from `PyModule_GetState` in both builds instead of returning a result with
  an exception pending. GC traversal/clearing uses the GC accessor. The
  sequence tests explicitly publish module state when testing element access;
  a separate clean-process test verifies rejection with unpublished state.

- **GC metadata access:** heap-type slot traversal and standard-library module
  traversal/clear/free callbacks now use the existing `*_DuringGC` accessors.
  Normal object accessibility is not a precondition for GC to inspect a
  different group's layout or native module state. A regression test holds
  a local slotted object and extension modules in Main while another group
  performs a full collection. No Python-code access exemption was added.

## Remaining implementation work

The following are known gaps, not questions about whether the PEP requires
parallel groups or immediate reclamation of ordinary LOCAL objects. The
representation and cleanup contract in questions 5 and 6 should be settled
before the refcounting/header port; these gaps have not been fixed by the
follow-up.

1. **The default build still serializes different ThreadGroups.**
   `_PyEval_AcquireLock()` acquires both the group lock and the interpreter
   GIL (`Python/ceval_gil.c`). `Include/refcount.h` still selects ordinary
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
   fast path still tests the OS-thread owner (`Include/refcount.h`).
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

3. **Header size does not follow the appendix's compact-layout direction.**
   Measured `object.__basicsize__` is 40 bytes in the GIL build and 56 bytes
   in the free-threading build on this 64-bit host. The illustrative
   [header](https://peps.python.org/pep-0805/appendix-implementation/#object-state)
   occupies 24 bytes with this ABI's usual layout. That exact layout is a
   suggestion, not a mandatory ABI. Explaining the current three cleanup
   fields does not justify their permanent cost or resolve Mark's concern.

## Questions to discuss with Mark

### 1. How is reference validity maintained when protection ends in another frame?

A generator can yield a valid protected reference, then invalidate its
protection when the caller later closes that generator. The follow-up now
rejects subsequent local loads and checks surviving call-stack operands.
Similar issues arise with suspended coroutines, callbacks, debugger contexts
and C locals retained across calls.

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
(`Include/cpython/listobject.h`, `Include/cpython/tupleobject.h`).
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

The same contract matters for legacy extension GC visitors. Modern CPython
provides `*_DuringGC` metadata APIs, now used by the repaired stdlib visitors,
but unchanged older extensions may call ordinary module/type-data accessors.
How should those visitors remain compatible when collection runs in a group
that cannot normally access the object? Converting stdlib callers alone does
not settle compatibility for third-party extensions.

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
(`Modules/_threadmodule.c`). A transferred ordinary Python instance can
currently return a primitive `obj.x` in the receiving group while accessing
`obj.__dict__` raises `IllegalThreadAccessException`. This was reproduced in
both builds. By contrast, protection explicitly copies and protects an
instance's dictionary (`Modules/_threadmodule.c`).

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
(`Modules/_threadmodule.c`, `Modules/_threadmodule.c`). An abandoned
unclaimed transfer is instead adopted by the group clearing its box.
These are substantial implementation choices, not specified callback rules.

Are those affinity rules intended, including when the original thread has
exited or the interpreter is shutting down? May finalization create a thread
or block on a protecting mutex? What should happen to unclaimed transfers
and objects whose lock wrapper has died?

Separately, is it necessary to retain arbitrarily many explicit non-GC
`PyObject_CallFinalizer` requests during an internal world stop, even under
allocator failure? That is the current queue's self-imposed/tested guarantee
(`Objects/object.c`), and it drove the three `ob_deferred_*` fields.
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
heap scans (`Objects/funcobject.c`), but the
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

## Follow-up commits

- `d149d16b05`: finalizer transport, native helper acquisitions, state inspection.
- `f2ae1c67b6`: protected tuple-iterator copying and the PEP wrapper example.
- `ff60f55d63`: explicit sharing declarations for extension types.
- `65d89f831d`: conservative local and surviving call-operand validation.
- `ef68bf8a82`: consistent termios module-state error propagation.
- `2fc691bbbe`: GC metadata access for foreign groups.

## Validation performed

Both Linux/aarch64 debug variants were rebuilt, and the opcode/uop generated
files were regenerated. The GIL checkout's changed source/test/generated
files match the free-threading checkout.

The final run used `./python -m test -q -j2 --timeout=120` with the 50 PEP 805
suites and `test_dis`, `test_peepholer`, `test_scope`, `test_generators`,
`test_genexps`, `test_listcomps`, `test_coroutines`, `test_context`, `test_tuple`,
`test_gc`, and `test_capi.test_module`:

| Build | Test files | Reported tests | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Free-threading debug | 61 | 1,359 | 13 | SUCCESS |
| GIL debug | 61 | 1,359 | 16 | SUCCESS |

`Tools/scripts/pep805_demo.py` also succeeds in both rebuilt variants: two
ThreadGroups process four chunks, the weighted square sum is 61,620, and
foreign LOCAL and unprotected PROTECTED access are rejected.

The original audit probes were repeated in both builds. Tuple iterator
protection and the generator-local rejection now work. The header sizes,
same-group LOCAL finalizer delay in free-threading, transfer namespace
behavior, protect uniqueness restriction and dynamic function
reclassification remain as described above.

The optional `_decimal` extension is unavailable in this environment.
Windows and native JIT execution remain deferred. These checks do not prove
complete native reference-acquisition coverage or PEP 805 conformance, and
no performance claim is made for the conservative VM checks.
