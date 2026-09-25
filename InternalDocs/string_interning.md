# String interning

*Interned* strings are conceptually part of an interpreter-global
*set* of interned strings, meaning that:

- no two interned strings have the same content (across an interpreter);
- two interned strings can be safely compared using pointer equality
  (Python `is`).

This is used to optimize dict and attribute lookups, among other things.

Python uses two different mechanisms to intern strings: singletons and
dynamic interning.

## Singletons

The 256 possible one-character latin-1 strings, which can be retrieved with
`_Py_LATIN1_CHR(c)`, are stored in statically allocated arrays,
`_PyRuntime.static_objects.singletons.strings.ascii` and
`_PyRuntime.static_objects.singletons.strings.latin1`.

Longer singleton strings are marked in C source with `_Py_ID` (if the string
is a valid C identifier fragment) or `_Py_STR` (if it needs a separate
C-compatible name.)
These are also stored in statically allocated arrays.
They are collected from CPython sources using `make regen-global-objects`
(`Tools/build/generate_global_objects.py`), which generates code
for declaration, initialization and finalization.

The empty string is one of the singletons: `_Py_STR(empty)`.

The three sets of singletons (`_Py_LATIN1_CHR`, `_Py_ID`, `_Py_STR`)
are disjoint.
If you have such a singleton, it (and no other copy) will be interned.

These singletons are interned in a runtime-global lookup table,
`_PyRuntime.cached_objects.interned_strings` (`INTERNED_STRINGS`),
at runtime initialization, and immutable until it's torn down
at runtime finalization.
It is shared across threads and interpreters without any synchronization.


## Dynamically allocated strings

All other strings are allocated dynamically, and have their
`_PyUnicode_STATE(s).statically_allocated` flag set to zero.
When interned, such strings are added to
`PyInterpreterState.cached_objects.interned_strings`.
The normal build uses a weak native hash table protected by the interpreter's
intern mutex. Legacy interpreters which share the main interpreter's table
also share its mutex. The free-threaded build uses a dictionary whose key and
value both reference the same immortal object.


## Immortality and reference counting

In the GIL-enabled build interned strings may be mortal or immortal. In the
free-threaded build, interned strings are always immortal.

For mortal interned strings:

- the normal table holds no strong references and sets the BRC maybe-weakref
  flag before publishing a new entry
- lookup holds the table mutex while attempting to acquire a strong reference;
  if that fails, the entry is removed and can be replaced by an equal string
- the deallocator (`unicode_dealloc`) takes the same mutex and removes only an
  entry pointing to that exact allocation, leaving any replacement intact
- at shutdown the table temporarily acquires strong references, clears the
  interned states and releases its references after `unicode.ids` has acquired
  the references it needs to survive table destruction

As with any type, you should only immortalize strings that will live until
interpreter shutdown.
We currently also immortalize strings contained in code objects and similar,
specifically in the compiler and in `marshal`.
These are “close enough” to immortal: even in use cases like hot reloading
or `eval`-ing user input, the number of distinct identifiers and string
constants is expected to stay low.


## Internal API

We have the following *internal* API for interning:

- `_PyUnicode_InternMortal`: just intern the string
- `_PyUnicode_InternImmortal`: intern, and immortalize the result
- `_PyUnicode_InternStatic`: intern a static singleton (`_Py_STR`, `_Py_ID`
  or one-byte). Not for general use.

All take an interpreter state, and a pointer to a `PyObject*` which they
modify in place.

The functions take ownership of (“steal”) the reference to their argument,
and update the argument with a *new* reference.
This means:

- They're “reference neutral”.
- They must not be called with a borrowed reference.


## State

The intern state (retrieved by `PyUnicode_CHECK_INTERNED(s)`;
stored in `_PyUnicode_STATE(s).interned`) can be:

- `SSTATE_NOT_INTERNED` (defined as 0, which is useful in a boolean context)
- `SSTATE_INTERNED_MORTAL` (1)
- `SSTATE_INTERNED_IMMORTAL` (2)
- `SSTATE_INTERNED_IMMORTAL_STATIC` (3)

The state occupies a separate byte, accessed atomically in both builds.
It does not share a bit-field storage location with the immutable character
kind, compactness or ASCII flags. Publishing an interned state follows the
corresponding reference-count updates. This does not by itself synchronize
the reference-count transition to immortality. Table operations are serialized
by the intern mutex, but the normal build still relies on the interpreter GIL
when promoting a string whose biased count may belong to another ThreadGroup.

The valid transitions between these states are:

- For dynamically allocated strings:

  - 0 -> 1 (`_PyUnicode_InternMortal`)
  - 1 -> 2 or 0 -> 2 (`_PyUnicode_InternImmortal`)

  Using `_PyUnicode_InternStatic` on these is an error; the other cases
  don't change the state.

- Singletons are interned (0 -> 3) at runtime init;
  after that all interning functions don't change the state.
