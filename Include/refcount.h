#ifndef _Py_REFCOUNT_H
#define _Py_REFCOUNT_H
#ifdef __cplusplus
extern "C" {
#endif


#if !defined(_Py_OPAQUE_PYOBJECT)
// Py_REFCNT retains the conventional large value for immortal objects.
#if SIZEOF_VOID_P > 4
#  define _Py_IMMORTAL_INITIAL_REFCNT (3ULL << 30)
#  define _Py_IMMORTAL_MINIMUM_REFCNT (1ULL << 31)
#else
#  define _Py_IMMORTAL_INITIAL_REFCNT ((Py_ssize_t)(5L << 28))
#  define _Py_IMMORTAL_MINIMUM_REFCNT ((Py_ssize_t)(1L << 30))
#endif

// Immortal objects use a reserved value in the local reference count.
#define _Py_IMMORTAL_REFCNT_LOCAL UINT8_MAX


   // The shared reference count uses the two least-significant bits to store
   // flags. The remaining bits are used to store the reference count.
#  define _Py_REF_SHARED_SHIFT        2
#  define _Py_REF_SHARED_FLAG_MASK    0x3

   // The shared flags are initialized to zero.
#  define _Py_REF_SHARED_INIT         0x0
#  define _Py_REF_MAYBE_WEAKREF       0x1
#  define _Py_REF_QUEUED              0x2
#  define _Py_REF_MERGED              0x3

// A dynamic immortalization closes the shared counter to late operations.
// This reserved value never participates in reference-count arithmetic.
#  define _Py_REF_SHARED_IMMORTAL     PY_SSIZE_T_MIN

   // Create a shared field from a refcnt and desired flags
#  define _Py_REF_SHARED(refcnt, flags) \
              (((refcnt) << _Py_REF_SHARED_SHIFT) + (flags))
#endif  // _Py_OPAQUE_PYOBJECT

// Returns the ID of the current ThreadGroup, or zero without a thread state.
PyAPI_FUNC(uint32_t) _Py_GetThreadGroupId(void);

#if !defined(Py_LIMITED_API)
static inline Py_ALWAYS_INLINE int
_Py_IsOwnedByCurrentThread(PyObject *ob)
{
    // The name is retained for internal callers ported from PEP 703. The bias
    // belongs to the whole group, not to the allocating OS thread.
    uint8_t local = _Py_atomic_load_uint8_relaxed(&ob->ob_ref_local);
    return local != 0 && local != _Py_IMMORTAL_REFCNT_LOCAL &&
           ob->ob_owner_id != 0 && ob->ob_owner_id == _Py_GetThreadGroupId();
}

// Merge an overflowing local count into the shared field and add one.
PyAPI_FUNC(int) _Py_IncRefLocalOverflow(PyObject *op);

// Return whether the operation changed a mortal reference count. Increments
// completed before immortalization must still be included in debug totals.
static inline int
_Py_IncRefShared(PyObject *op, Py_ssize_t n)
{
    Py_ssize_t shared = _Py_atomic_load_ssize_relaxed(&op->ob_ref_shared);
    for (;;) {
        if (shared == _Py_REF_SHARED_IMMORTAL) {
            return 0;
        }
        if (_Py_atomic_compare_exchange_ssize(
                &op->ob_ref_shared, &shared,
                shared + (n << _Py_REF_SHARED_SHIFT))) {
            return 1;
        }
    }
}

// -1 requires the shared path, 0 is immortal, 1 increments a local count.
static inline int
_Py_TryIncRefLocal(PyObject *op, uint8_t local)
{
    if (!_Py_IsOwnedByCurrentThread(op)) {
        return -1;
    }
    for (;;) {
        if (local == _Py_IMMORTAL_REFCNT_LOCAL) {
            return 0;
        }
        if (local == 0) {
            return -1;
        }
        if (local == _Py_IMMORTAL_REFCNT_LOCAL - 1) {
            return _Py_IncRefLocalOverflow(op);
        }
        if (_Py_atomic_compare_exchange_uint8(&op->ob_ref_local,
                                              &local, local + 1)) {
            return 1;
        }
    }
}
#endif

// Py_REFCNT() implementation for the stable ABI
PyAPI_FUNC(Py_ssize_t) Py_REFCNT(PyObject *ob);

#if defined(Py_LIMITED_API)
    // Keep the layout and atomic operations out of limited API callers.
#else
    static inline Py_ssize_t _Py_REFCNT(PyObject *ob) {
        uint8_t local = _Py_atomic_load_uint8_relaxed(&ob->ob_ref_local);
        if (local == _Py_IMMORTAL_REFCNT_LOCAL) {
            return _Py_IMMORTAL_INITIAL_REFCNT;
        }
        Py_ssize_t shared = _Py_atomic_load_ssize_relaxed(&ob->ob_ref_shared);
        if (shared == _Py_REF_SHARED_IMMORTAL) {
            return _Py_IMMORTAL_INITIAL_REFCNT;
        }
        return _Py_STATIC_CAST(Py_ssize_t, local) +
               Py_ARITHMETIC_RIGHT_SHIFT(Py_ssize_t, shared, _Py_REF_SHARED_SHIFT);
    }
    #if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 < 0x030b0000
    #  define Py_REFCNT(ob) _Py_REFCNT(_PyObject_CAST(ob))
    #else
    #  define Py_REFCNT(ob) _Py_REFCNT(ob)
    #endif
#endif

#if !defined(Py_LIMITED_API)
static inline Py_ALWAYS_INLINE int _Py_IsImmortal(PyObject *op)
{
    return (_Py_atomic_load_uint8_relaxed(&op->ob_ref_local) ==
            _Py_IMMORTAL_REFCNT_LOCAL);
}
#define _Py_IsImmortal(op) _Py_IsImmortal(_PyObject_CAST(op))


static inline Py_ALWAYS_INLINE int _Py_IsStaticImmortal(PyObject *op)
{
    return (_Py_atomic_load_uint8_relaxed(&op->ob_flags) &
            _Py_STATICALLY_ALLOCATED_FLAG) != 0;
}
#define _Py_IsStaticImmortal(op) _Py_IsStaticImmortal(_PyObject_CAST(op))
#endif // !defined(_Py_OPAQUE_PYOBJECT)

// Py_SET_REFCNT() implementation for stable ABI
PyAPI_FUNC(void) _Py_SetRefcnt(PyObject *ob, Py_ssize_t refcnt);

static inline void Py_SET_REFCNT(PyObject *ob, Py_ssize_t refcnt) {
    assert(refcnt >= 0);
#if defined(Py_LIMITED_API)
    // Limited API callers use the runtime's reference-count representation.
    _Py_SetRefcnt(ob, refcnt);
#else
    // This immortal check is for code that is unaware of immortal objects.
    // The runtime tracks these objects and we should avoid as much
    // as possible having extensions inadvertently change the refcnt
    // of an immortalized object.
    if (_Py_IsImmortal(ob)) {
        return;
    }
    if (_Py_IsOwnedByCurrentThread(ob) && refcnt < _Py_IMMORTAL_REFCNT_LOCAL) {
        ob->ob_ref_local = _Py_STATIC_CAST(uint8_t, refcnt);
        ob->ob_ref_shared &= _Py_REF_SHARED_FLAG_MASK;
        if (refcnt == 0) {
            ob->ob_ref_shared |= _Py_REF_MERGED;
        }
    }
    else {
        // Preserve the ownership ID when the reference count becomes shared.
        ob->ob_ref_local = 0;
        ob->ob_ref_shared = _Py_REF_SHARED(refcnt, _Py_REF_MERGED);
    }
#endif  // Py_LIMITED_API
}
#if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 < 0x030b0000
#  define Py_SET_REFCNT(ob, refcnt) Py_SET_REFCNT(_PyObject_CAST(ob), (refcnt))
#endif


/*
The macros Py_INCREF(op) and Py_DECREF(op) are used to increment or decrement
reference counts.  Py_DECREF calls the object's deallocator function when
the refcount falls to 0; for
objects that don't contain references to other objects or heap memory
this can be the standard function free().  Both macros can be used
wherever a void expression is allowed.  The argument must not be a
NULL pointer.  If it may be NULL, use Py_XINCREF/Py_XDECREF instead.
The macro _Py_NewReference(op) initialize reference counts to 1, and
in special builds (Py_REF_DEBUG, Py_TRACE_REFS) performs additional
bookkeeping appropriate to the special build.

We assume that the reference count field can never overflow; this can
be proven when the size of the field is the same as the pointer size, so
we ignore the possibility.  Provided a C int is at least 32 bits (which
is implicitly assumed in many parts of this code), that's enough for
about 2**31 references to an object.

XXX The following became out of date in Python 2.2, but I'm not sure
XXX what the full truth is now.  Certainly, heap-allocated type objects
XXX can and should be deallocated.
Type objects should never be deallocated; the type pointer in an object
is not considered to be a reference to the type object, to save
complications in the deallocation function.  (This is actually a
decision that's up to the implementer of each new type so if you want,
you can count such references to the type object.)
*/

#if defined(Py_REF_DEBUG) && !defined(Py_LIMITED_API)
PyAPI_FUNC(void) _Py_NegativeRefcount(const char *filename, int lineno,
                                      PyObject *op);
PyAPI_FUNC(void) _Py_INCREF_IncRefTotal(void);
PyAPI_FUNC(void) _Py_DECREF_DecRefTotal(void);
#endif  // Py_REF_DEBUG && !Py_LIMITED_API

PyAPI_FUNC(void) _Py_Dealloc(PyObject *);


/*
These are provided as conveniences to Python runtime embedders, so that
they can have object code that is not dependent on Python compilation flags.
*/
PyAPI_FUNC(void) Py_IncRef(PyObject *);
PyAPI_FUNC(void) Py_DecRef(PyObject *);

// Similar to Py_IncRef() and Py_DecRef() but the argument must be non-NULL.
// Private functions used by Py_INCREF() and Py_DECREF().
PyAPI_FUNC(void) _Py_IncRef(PyObject *);
PyAPI_FUNC(void) _Py_DecRef(PyObject *);

static inline Py_ALWAYS_INLINE void Py_INCREF(PyObject *op)
{
#if defined(Py_LIMITED_API)
    // Limited API callers perform reference counting through the runtime.
    // _Py_IncRef() was added to Python 3.10.0a7, use Py_IncRef() on older versions.
    // Py_IncRef() accepts NULL whereas _Py_IncRef() doesn't.
#  if Py_LIMITED_API+0 >= 0x030a00A7
    _Py_IncRef(op);
#  else
    Py_IncRef(op);
#  endif
#else
    // Non-limited C API and limited C API for Python 3.9 and older access
    // the object header directly.
    uint8_t local = _Py_atomic_load_uint8_relaxed(&op->ob_ref_local);
    if (local == _Py_IMMORTAL_REFCNT_LOCAL) {
        _Py_INCREF_IMMORTAL_STAT_INC();
        // local is equal to _Py_IMMORTAL_REFCNT_LOCAL: do nothing
        return;
    }
    int changed = _Py_TryIncRefLocal(op, local);
    if (changed < 0) {
        changed = _Py_IncRefShared(op, 1);
    }
    if (!changed) {
        _Py_INCREF_IMMORTAL_STAT_INC();
        return;
    }
    _Py_INCREF_STAT_INC();
#ifdef Py_REF_DEBUG
    _Py_INCREF_IncRefTotal();
#endif
#endif
}
#if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 < 0x030b0000
#  define Py_INCREF(op) Py_INCREF(_PyObject_CAST(op))
#endif

#if !defined(Py_LIMITED_API)
// Implements Py_DECREF on objects not owned by the current thread.
PyAPI_FUNC(void) _Py_DecRefShared(PyObject *);
PyAPI_FUNC(void) _Py_DecRefSharedDebug(PyObject *, const char *, int);

// Called from Py_DECREF by the owning thread when the local refcount reaches
// zero. The call will deallocate the object if the shared refcount is also
// zero. Otherwise, the thread gives up ownership and merges the reference
// count fields.
PyAPI_FUNC(void) _Py_MergeZeroLocalRefcount(PyObject *);

// As above: -1 requires the shared path, 0 is immortal, 1 decrements locally.
static inline int
_Py_DecRefLocal(PyObject *op, uint8_t local)
{
    for (;;) {
        if (local == _Py_IMMORTAL_REFCNT_LOCAL) {
            return 0;
        }
        if (local == 0) {
            return -1;
        }
        uint8_t new_local = local - 1;
        if (_Py_atomic_compare_exchange_uint8(&op->ob_ref_local,
                                              &local, new_local)) {
            if (new_local == 0) {
                _Py_MergeZeroLocalRefcount(op);
            }
            return 1;
        }
    }
}
#endif  // Py_LIMITED_API

#if defined(Py_LIMITED_API)
// Limited API callers perform reference counting through the runtime.
// _Py_DecRef() was added to Python 3.10.0a7, use Py_DecRef() on older versions.
// Py_DecRef() accepts NULL whereas _Py_DecRef() doesn't.
static inline void Py_DECREF(PyObject *op) {
#  if Py_LIMITED_API+0 >= 0x030a00A7
    _Py_DecRef(op);
#  else
    Py_DecRef(op);
#  endif
}
#define Py_DECREF(op) Py_DECREF(_PyObject_CAST(op))

#elif defined(Py_REF_DEBUG)
static inline void Py_DECREF(const char *filename, int lineno, PyObject *op)
{
    uint8_t local = _Py_atomic_load_uint8_relaxed(&op->ob_ref_local);
    if (local == _Py_IMMORTAL_REFCNT_LOCAL) {
        _Py_DECREF_IMMORTAL_STAT_INC();
        return;
    }
    _Py_DECREF_STAT_INC();
    _Py_DECREF_DecRefTotal();
    if (_Py_IsOwnedByCurrentThread(op)) {
        int changed = _Py_DecRefLocal(op, local);
        if (changed == 0) {
            _Py_INCREF_IncRefTotal();
            return;
        }
        if (changed > 0) {
            return;
        }
    }
    _Py_DecRefSharedDebug(op, filename, lineno);
}
#define Py_DECREF(op) Py_DECREF(__FILE__, __LINE__, _PyObject_CAST(op))

#else
static inline void Py_DECREF(PyObject *op)
{
    uint8_t local = _Py_atomic_load_uint8_relaxed(&op->ob_ref_local);
    if (local == _Py_IMMORTAL_REFCNT_LOCAL) {
        _Py_DECREF_IMMORTAL_STAT_INC();
        return;
    }
    _Py_DECREF_STAT_INC();
    if (_Py_IsOwnedByCurrentThread(op)) {
        if (_Py_DecRefLocal(op, local) >= 0) {
            return;
        }
    }
    _Py_DecRefShared(op);
}
#define Py_DECREF(op) Py_DECREF(_PyObject_CAST(op))

#endif


/* Safely decref `op` and set `op` to NULL, especially useful in tp_clear
 * and tp_dealloc implementations.
 *
 * Note that "the obvious" code can be deadly:
 *
 *     Py_XDECREF(op);
 *     op = NULL;
 *
 * Typically, `op` is something like self->containee, and `self` is done
 * using its `containee` member.  In the code sequence above, suppose
 * `containee` is non-NULL with a refcount of 1.  Its refcount falls to
 * 0 on the first line, which can trigger an arbitrary amount of code,
 * possibly including finalizers (like __del__ methods or weakref callbacks)
 * coded in Python, which in turn can release the GIL and allow other threads
 * to run, etc.  Such code may even invoke methods of `self` again, or cause
 * cyclic gc to trigger, but-- oops! --self->containee still points to the
 * object being torn down, and it may be in an insane state while being torn
 * down.  This has in fact been a rich historic source of miserable (rare &
 * hard-to-diagnose) segfaulting (and other) bugs.
 *
 * The safe way is:
 *
 *      Py_CLEAR(op);
 *
 * That arranges to set `op` to NULL _before_ decref'ing, so that any code
 * triggered as a side-effect of `op` getting torn down no longer believes
 * `op` points to a valid object.
 *
 * There are cases where it's safe to use the naive code, but they're brittle.
 * For example, if `op` points to a Python integer, you know that destroying
 * one of those can't cause problems -- but in part that relies on that
 * Python integers aren't currently weakly referencable.  Best practice is
 * to use Py_CLEAR() even if you can't think of a reason for why you need to.
 *
 * gh-98724: Use a temporary variable to only evaluate the macro argument once,
 * to avoid the duplication of side effects if the argument has side effects.
 *
 * gh-99701: If the PyObject* type is used with casting arguments to PyObject*,
 * the code can be miscompiled with strict aliasing because of type punning.
 * With strict aliasing, a compiler considers that two pointers of different
 * types cannot read or write the same memory which enables optimization
 * opportunities.
 *
 * If available, use _Py_TYPEOF() to use the 'op' type for temporary variables,
 * and so avoid type punning. Otherwise, use memcpy() which causes type erasure
 * and so prevents the compiler to reuse an old cached 'op' value after
 * Py_CLEAR().
 */
#ifdef _Py_TYPEOF
#define Py_CLEAR(op) \
    do { \
        _Py_TYPEOF(&(op)) _tmp_op_ptr = &(op); \
        _Py_TYPEOF(op) _tmp_old_op = (*_tmp_op_ptr); \
        if (_tmp_old_op != _Py_NULL) { \
            *_tmp_op_ptr = _Py_NULL; \
            Py_DECREF(_tmp_old_op); \
        } \
    } while (0)
#else
#define Py_CLEAR(op) \
    do { \
        PyObject **_tmp_op_ptr = _Py_CAST(PyObject**, &(op)); \
        PyObject *_tmp_old_op = (*_tmp_op_ptr); \
        if (_tmp_old_op != _Py_NULL) { \
            PyObject *_null_ptr = _Py_NULL; \
            memcpy(_tmp_op_ptr, &_null_ptr, sizeof(PyObject*)); \
            Py_DECREF(_tmp_old_op); \
        } \
    } while (0)
#endif


/* Function to use in case the object pointer can be NULL: */
static inline void Py_XINCREF(PyObject *op)
{
    if (op != _Py_NULL) {
        Py_INCREF(op);
    }
}
#if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 < 0x030b0000
#  define Py_XINCREF(op) Py_XINCREF(_PyObject_CAST(op))
#endif

static inline void Py_XDECREF(PyObject *op)
{
    if (op != _Py_NULL) {
        Py_DECREF(op);
    }
}
#if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 < 0x030b0000
#  define Py_XDECREF(op) Py_XDECREF(_PyObject_CAST(op))
#endif

// Create a new strong reference to an object:
// increment the reference count of the object and return the object.
PyAPI_FUNC(PyObject*) Py_NewRef(PyObject *obj);

// Similar to Py_NewRef(), but the object can be NULL.
PyAPI_FUNC(PyObject*) Py_XNewRef(PyObject *obj);

static inline PyObject* _Py_NewRef(PyObject *obj)
{
    Py_INCREF(obj);
    return obj;
}

static inline PyObject* _Py_XNewRef(PyObject *obj)
{
    Py_XINCREF(obj);
    return obj;
}

// Py_NewRef() and Py_XNewRef() are exported as functions for the stable ABI.
// Names overridden with macros by static inline functions for best
// performances.
#if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 < 0x030b0000
#  define Py_NewRef(obj) _Py_NewRef(_PyObject_CAST(obj))
#  define Py_XNewRef(obj) _Py_XNewRef(_PyObject_CAST(obj))
#else
#  define Py_NewRef(obj) _Py_NewRef(obj)
#  define Py_XNewRef(obj) _Py_XNewRef(obj)
#endif


#ifdef __cplusplus
}
#endif
#endif   // !_Py_REFCOUNT_H
