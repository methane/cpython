/* Function object implementation */

#include "Python.h"
#include "pycore_gc.h"
#include "pycore_code.h"          // _PyCode_VerifyStateless()
#include "pycore_dict.h"          // _Py_INCREF_DICT()
#include "pycore_function.h"      // _PyFunction_Vectorcall
#include "pycore_long.h"          // _PyLong_GetOne()
#include "pycore_modsupport.h"    // _PyArg_NoKeywords()
#include "pycore_object.h"        // _PyObject_GC_UNTRACK()
#include "pycore_object_deferred.h" // _PyObject_SetDeferredRefcount()
#include "pycore_optimizer.h"       // _Py_Executors_InvalidateDependency()
#include "pycore_pyerrors.h"      // _PyErr_Occurred()
#include "pycore_setobject.h"     // _PySet_NextEntry()
#include "pycore_stats.h"
#include "pycore_threadgroup.h"   // _PyThreadGroupState
#include "pycore_weakref.h"       // FT_CLEAR_WEAKREFS()

static const char *
func_event_name(PyFunction_WatchEvent event) {
    switch (event) {
        #define CASE(op)                \
        case PyFunction_EVENT_##op:         \
            return "PyFunction_EVENT_" #op;
        PY_FOREACH_FUNC_EVENT(CASE)
        #undef CASE
    }
    Py_UNREACHABLE();
}

static int
warn_function_mutation(const char *attribute)
{
    return PyErr_WarnFormat(PyExc_DeprecationWarning, 1,
                           "Modifying a function's %s is deprecated", attribute);
}

/* The binding byte is zero for mutable cells. Otherwise it is one plus a
   saturating count of attached functions. A cell with no surviving readers
   can become mutable without scanning the interpreter heap. */
static void
func_register_closure(PyObject *closure, int add)
{
    if (closure == NULL) {
        return;
    }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(closure); i++) {
        PyObject *item = PyTuple_GET_ITEM(closure, i);
        if (!PyCell_Check(item)) {
            continue;
        }
        PyCellObject *cell = (PyCellObject *)item;
        uint8_t readers = _Py_atomic_load_uint8(&cell->ob_readonly_binding);
        while (readers != 0 && readers != UINT8_MAX) {
            assert(add || readers > 1);
            uint8_t next = add ? readers + 1 : readers - 1;
            if (_Py_atomic_compare_exchange_uint8(&cell->ob_readonly_binding,
                                                  &readers, next)) {
                break;
            }
        }
    }
}

static int
func_can_share(PyCodeObject *code, PyObject *closure)
{
    Py_ssize_t size = closure == NULL ? 0 : PyTuple_GET_SIZE(closure);
    if (size != code->co_nfreevars) {
        return 0;
    }
    for (Py_ssize_t i = 0; i < size; i++) {
        PyObject *cell = PyTuple_GET_ITEM(closure, i);
        if (!PyCell_Check(cell) ||
            !_Py_atomic_load_uint8(&((PyCellObject *)cell)->ob_readonly_binding)) {
            return 0;
        }
    }
    // Per-call cells are safe unless nested code can rebind them.
    for (int i = 0; i < code->co_nlocalsplus; i++) {
        if (_PyLocals_GetKind(code->co_localspluskinds, i) &
            CO_FAST_NONLOCAL_WRITE) {
            return 0;
        }
    }
    return 1;
}

/* A local function with mutable captures must belong to their owner, not
   merely to the group constructing a new wrapper around foreign cells.
   Conflicting local owners cannot be represented by a single valid owner. */
static uint32_t
func_closure_owner(PyObject *closure, uint32_t fallback)
{
    uint32_t owner = 0;
    if (closure == NULL) {
        return fallback;
    }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(closure); i++) {
        PyObject *cell = PyTuple_GET_ITEM(closure, i);
        if (!PyCell_Check(cell) ||
            _Py_atomic_load_uint8(&((PyCellObject *)cell)->ob_readonly_binding) ||
            _Py_atomic_load_uint8(&cell->ob_shareable) >= _Py_SHAREABLE_SYNCHRONIZED) {
            continue;
        }
        uint32_t cell_owner = _Py_atomic_load_uint32_relaxed(&cell->ob_owner_id);
        if (cell_owner == 0 || (owner != 0 && owner != cell_owner)) {
            return 0;
        }
        owner = cell_owner;
    }
    return owner == 0 ? fallback : owner;
}

/* Called before publication, or with the world stopped when execution
   attributes change. Cells retain their own ownership; sharing a reader does
   not grant access to its captured values. */
static void
func_update_shareable(PyFunctionObject *func)
{
    PyObject *op = (PyObject *)func;
    PyCodeObject *code = (PyCodeObject *)func->func_code;
    uint8_t state = FT_ATOMIC_LOAD_UINT8(op->ob_shareable);
    if (state != _Py_SHAREABLE_LOCAL && state != _Py_SHAREABLE_SYNCHRONIZED) {
        return;
    }
    if (func_can_share(code, func->func_closure)) {
        _Py_atomic_store_uint32_relaxed(&op->ob_owner_id, 0);
        _Py_atomic_store_uint8(&op->ob_shareable, _Py_SHAREABLE_SYNCHRONIZED);
    }
    else {
        uint32_t owner = state == _Py_SHAREABLE_LOCAL ?
            _Py_atomic_load_uint32_relaxed(&op->ob_owner_id) :
            _PyThreadState_GET()->threadgroup->id;
        owner = func_closure_owner(func->func_closure, owner);
        _Py_atomic_store_uint32_relaxed(&op->ob_owner_id, owner);
        _Py_atomic_store_uint8(&op->ob_shareable, _Py_SHAREABLE_LOCAL);
    }
}

static void func_clear_version(PyInterpreterState *, PyFunctionObject *);

/* The world is stopped and this callback must not allocate or invoke Python.
   A binding, not a code object, is the unit of dependency: separate calls of
   the same factory create independent cells. */
static int
localize_cell_reader(PyObject *op, void *arg)
{
    if (!PyFunction_Check(op)) {
        return 1;
    }
    uint8_t state = _Py_atomic_load_uint8(&op->ob_shareable);
    if (state != _Py_SHAREABLE_LOCAL && state != _Py_SHAREABLE_SYNCHRONIZED) {
        return 1;
    }
    PyFunctionObject *func = (PyFunctionObject *)op;
    PyObject *closure = func->func_closure;
    if (closure == NULL || func->func_code == NULL) {
        return 1;
    }
    PyCellObject *cell = arg;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(closure); i++) {
        if (PyTuple_GET_ITEM(closure, i) == (PyObject *)cell) {
            func_clear_version(_PyInterpreterState_GET(), func);
            func_update_shareable(func);
            break;
        }
    }
    return 1;
}

static void
cell_became_writable_stopped(PyCellObject *cell)
{
    uint8_t readers = _Py_atomic_load_uint8(&cell->ob_readonly_binding);
    if (readers == 0) {
        return;
    }
    _Py_atomic_store_uint8(&cell->ob_readonly_binding, 0);
    if (readers == 1) {
        return;
    }
#ifdef Py_GIL_DISABLED
    _PyGC_VisitObjectsWorldStopped(_PyInterpreterState_GET(),
                                 localize_cell_reader, cell);
#else
    PyUnstable_GC_VisitObjects(localize_cell_reader, cell);
#endif
}

void
_PyFunction_CellBecameWritable(PyCellObject *cell)
{
    uint8_t readers = _Py_atomic_load_uint8(&cell->ob_readonly_binding);
    if (readers == 0) {
        return;
    }
    // Registration uses the same byte, so a concurrent new reader either
    // prevents this transition or observes the already mutable binding.
    if (readers == 1 && _Py_atomic_compare_exchange_uint8(
            &cell->ob_readonly_binding, &readers, 0)) {
        return;
    }
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PyEval_StopTheWorld(interp);
    cell_became_writable_stopped(cell);
    _PyEval_StartTheWorld(interp);
}

/* Connecting writer code to a previously read-only cell also affects readers
   that have already been published. Called with the world stopped. */
static void
func_mark_closure_writers(PyCodeObject *code, PyObject *closure)
{
    if (closure == NULL) {
        return;
    }
    int offset = code->co_nlocalsplus - code->co_nfreevars;
    Py_ssize_t size = PyTuple_GET_SIZE(closure);
    if (size > code->co_nfreevars) {
        size = code->co_nfreevars;
    }
    for (Py_ssize_t i = 0; i < size; i++) {
        if (_PyLocals_GetKind(code->co_localspluskinds, offset + i) &
            CO_FAST_NONLOCAL_WRITE) {
            PyObject *cell = PyTuple_GET_ITEM(closure, i);
            if (PyCell_Check(cell)) {
                cell_became_writable_stopped((PyCellObject *)cell);
            }
        }
    }
}

/* Check without allocating: callers may have stopped the world. Report the
   error only after resuming it, since creating an exception can trigger GC. */
static PyObject *
func_mutation_error(PyObject *op)
{
    uint8_t state = FT_ATOMIC_LOAD_UINT8(op->ob_shareable);
    if (state == _Py_SHAREABLE_IMMUTABLE || FT_ATOMIC_LOAD_UINT8(op->ob_frozen)) {
        return PyExc_TypeError;
    }
    if (_PyThreadState_GET()->debugger_stop_depth != 0) {
        return NULL;
    }
    if (state == _Py_SHAREABLE_PROTECTED) {
        return PyExc_UnprotectedAccessException;
    }
    if (state == _Py_SHAREABLE_LOCAL &&
        FT_ATOMIC_LOAD_UINT32_RELAXED(op->ob_owner_id) !=
            _PyThreadState_GET()->threadgroup->id) {
        return PyExc_IllegalThreadAccessException;
    }
    return NULL;
}

static int
func_check_mutation(PyObject *op)
{
    PyObject *error = func_mutation_error(op);
    if (error != NULL) {
        PyErr_SetString(error, "cannot modify function in its current sharing state");
        return -1;
    }
    return 0;
}

static int
func_begin_mutation(PyInterpreterState *interp, PyObject *op)
{
    _PyEval_StopTheWorld(interp);
    PyObject *error = func_mutation_error(op);
    if (error != NULL) {
        _PyEval_StartTheWorld(interp);
        PyErr_SetString(error, "cannot modify function in its current sharing state");
        return -1;
    }
    return 0;
}

/* On success leave the world stopped, ready to commit code or closure.
   Namespace conversion can allocate and wait, so perform it outside this
   interval and retry against the current function fields afterwards. */
static int
func_begin_execution_mutation(PyInterpreterState *interp, PyFunctionObject *func,
                              PyObject *code, PyObject *closure)
{
    for (;;) {
        if (func_begin_mutation(interp, (PyObject *)func) < 0) {
            return -1;
        }
        PyCodeObject *new_code = (PyCodeObject *)(code ? code : func->func_code);
        PyObject *new_closure = code ? func->func_closure : closure;
        if (code != NULL) {
            Py_ssize_t nclosure = new_closure ? PyTuple_GET_SIZE(new_closure) : 0;
            if (nclosure != new_code->co_nfreevars) {
                PyObject *name = Py_NewRef(func->func_name);
                int nfree = new_code->co_nfreevars;
                _PyEval_StartTheWorld(interp);
                PyErr_Format(PyExc_ValueError,
                             "%U() requires a code object with %zd free vars,"
                             " not %d", name, nclosure, nfree);
                Py_DECREF(name);
                return -1;
            }
        }
        if (!func_can_share(new_code, new_closure) || func->func_dict == NULL ||
            PySynchronizedDict_CheckExact(func->func_dict))
        {
            return 0;
        }
        PyObject *dict = Py_NewRef(func->func_dict);
        _PyEval_StartTheWorld(interp);
        int res = _PyDict_SynchronizeNamespace(dict);
        Py_DECREF(dict);
        if (res < 0) {
            return -1;
        }
    }
}

int
_PyFunction_SetClosureForCreation(PyFunctionObject *func, PyObject *closure)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_execution_mutation(interp, func, NULL, closure) < 0) {
        return -1;
    }
    PyObject *old_closure = func->func_closure;
    func_register_closure(closure, 1);
    func->func_closure = Py_NewRef(closure);
    func_register_closure(old_closure, 0);
    func_mark_closure_writers((PyCodeObject *)func->func_code, closure);
    func_update_shareable(func);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_closure);
    return 0;
}

int
_PyFunction_SetDict(PyObject *func, PyObject *dict)
{
    assert(PyFunction_Check(func));
    if (func_check_mutation(func) < 0) {
        return -1;
    }
    if (dict == NULL || !PyDict_Check(dict)) {
        PyErr_SetString(PyExc_TypeError, "__dict__ must be set to a dictionary");
        return -1;
    }
    if (PyObject_CheckAccess(dict) == NULL) {
        return -1;
    }
    int res;
    Py_BEGIN_CRITICAL_SECTION(func);
    res = func_check_mutation(func);
    if (res == 0 &&
        FT_ATOMIC_LOAD_UINT8(func->ob_shareable) == _Py_SHAREABLE_SYNCHRONIZED)
    {
        // Preserve all aliases to the supplied namespace, including split
        // instance dictionaries. This may suspend the function's lock.
        res = _PyDict_SynchronizeNamespace(dict);
    }
    if (res == 0) {
        res = func_check_mutation(func);
    }
    if (res == 0) {
        // Preserve the delayed release used by generic dictionary replacement:
        // attribute readers may still hold borrowed references to the old dict.
        _PyObject_XSetRefDelayed(&((PyFunctionObject *)func)->func_dict,
                                Py_NewRef(dict));
    }
    Py_END_CRITICAL_SECTION();
    return res;
}

static void
notify_func_watchers(PyInterpreterState *interp, PyFunction_WatchEvent event,
                     PyFunctionObject *func, PyObject *new_value)
{
    uint8_t bits = interp->active_func_watchers;
    int i = 0;
    while (bits) {
        assert(i < FUNC_MAX_WATCHERS);
        if (bits & 1) {
            PyFunction_WatchCallback cb = interp->func_watchers[i];
            // callback must be non-null if the watcher bit is set
            assert(cb != NULL);
            if (cb(event, func, new_value) < 0) {
                PyErr_FormatUnraisable(
                    "Exception ignored in %s watcher callback for function %U at %p",
                    func_event_name(event), func->func_qualname, func);
            }
        }
        i++;
        bits >>= 1;
    }
}

static inline void
handle_func_event(PyFunction_WatchEvent event, PyFunctionObject *func,
                  PyObject *new_value)
{
    assert(Py_REFCNT(func) > 0);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    assert(interp->_initialized);
    if (interp->active_func_watchers) {
        notify_func_watchers(interp, event, func, new_value);
    }
    switch (event) {
        case PyFunction_EVENT_MODIFY_CODE:
        case PyFunction_EVENT_MODIFY_DEFAULTS:
        case PyFunction_EVENT_MODIFY_KWDEFAULTS:
        case PyFunction_EVENT_MODIFY_QUALNAME:
#if _Py_TIER2
            // Note: we only invalidate JIT code if a function version changes.
            // Not when the function is deallocated.
            // Function deallocation occurs frequently (think: lambdas),
            // so we want to minimize dependency invalidation there.
            _Py_Executors_InvalidateDependency(interp, func, 1);
#endif
            RARE_EVENT_INTERP_INC(interp, func_modification);
            break;
        default:
            break;
    }
}

int
PyFunction_AddWatcher(PyFunction_WatchCallback callback)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    assert(interp->_initialized);
    for (int i = 0; i < FUNC_MAX_WATCHERS; i++) {
        if (interp->func_watchers[i] == NULL) {
            interp->func_watchers[i] = callback;
            interp->active_func_watchers |= (1 << i);
            return i;
        }
    }
    PyErr_SetString(PyExc_RuntimeError, "no more func watcher IDs available");
    return -1;
}

int
PyFunction_ClearWatcher(int watcher_id)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (watcher_id < 0 || watcher_id >= FUNC_MAX_WATCHERS) {
        PyErr_Format(PyExc_ValueError, "invalid func watcher ID %d",
                     watcher_id);
        return -1;
    }
    if (!interp->func_watchers[watcher_id]) {
        PyErr_Format(PyExc_ValueError, "no func watcher set for ID %d",
                     watcher_id);
        return -1;
    }
    interp->func_watchers[watcher_id] = NULL;
    interp->active_func_watchers &= ~(1 << watcher_id);
    return 0;
}
PyObject *
_PyFunction_CopyKwDefaults(PyObject *defaults)
{
    if (!PyAnyDict_Check(defaults)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(defaults) == NULL) {
        return NULL;
    }
    if (PyAnyDict_CheckExact(defaults)) {
        return PyFrozenDict_New(defaults);
    }
    PyObject *copy = _PyDict_CopyStorage(defaults);
    if (copy == NULL) {
        return NULL;
    }
    PyObject *frozen = PyFrozenDict_New(copy);
    Py_DECREF(copy);
    return frozen;
}

PyFunctionObject *
_PyFunction_FromConstructor(PyFrameConstructor *constr)
{
    PyObject *kwdefaults = NULL;
    if (constr->fc_kwdefaults != NULL) {
        kwdefaults = _PyFunction_CopyKwDefaults(constr->fc_kwdefaults);
        if (kwdefaults == NULL) {
            return NULL;
        }
    }
    PyObject *module;
    if (PyDict_GetItemRef(constr->fc_globals, &_Py_ID(__name__), &module) < 0) {
        Py_XDECREF(kwdefaults);
        return NULL;
    }

    PyFunctionObject *op = PyObject_GC_New(PyFunctionObject, &PyFunction_Type);
    if (op == NULL) {
        Py_XDECREF(module);
        Py_XDECREF(kwdefaults);
        return NULL;
    }
    _Py_INCREF_DICT(constr->fc_globals);
    op->func_globals = constr->fc_globals;
    _Py_INCREF_BUILTINS(constr->fc_builtins);
    op->func_builtins = constr->fc_builtins;
    op->func_name = Py_NewRef(constr->fc_name);
    op->func_qualname = Py_NewRef(constr->fc_qualname);
    _Py_INCREF_CODE((PyCodeObject *)constr->fc_code);
    op->func_code = constr->fc_code;
    op->func_defaults = Py_XNewRef(constr->fc_defaults);
    op->func_kwdefaults = kwdefaults;
    op->func_closure = Py_XNewRef(constr->fc_closure);
    op->func_doc = Py_NewRef(Py_None);
    op->func_dict = NULL;
    op->func_weakreflist = NULL;
    op->func_module = module;
    op->func_annotations = NULL;
    op->func_annotate = NULL;
    op->func_typeparams = NULL;
    op->vectorcall = _PyFunction_Vectorcall;
    op->func_version = FUNC_VERSION_UNSET;
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PyEval_StopTheWorld(interp);
    func_register_closure(op->func_closure, 1);
    func_mark_closure_writers((PyCodeObject *)op->func_code, op->func_closure);
    func_update_shareable(op);
    // NOTE: functions created via FrameConstructor do not use deferred
    // reference counting because they are typically not part of cycles
    // nor accessed by multiple threads.
    _PyObject_GC_TRACK(op);
    _PyEval_StartTheWorld(interp);
    handle_func_event(PyFunction_EVENT_CREATE, op, NULL);
    return op;
}

PyObject *
PyFunction_NewWithQualName(PyObject *code, PyObject *globals, PyObject *qualname)
{
    if (code == NULL || globals == NULL) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(code) == NULL ||
        PyObject_CheckAccess(globals) == NULL ||
        (qualname != NULL && PyObject_CheckAccess(qualname) == NULL)) {
        return NULL;
    }
    if (!PyCode_Check(code) || !PyAnyDict_Check(globals)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    assert(globals != NULL);
    assert(PyAnyDict_Check(globals));
    _Py_INCREF_DICT(globals);

    PyCodeObject *code_obj = (PyCodeObject *)code;
    _Py_INCREF_CODE(code_obj);

    assert(code_obj->co_name != NULL);
    PyObject *name = Py_NewRef(code_obj->co_name);

    if (!qualname) {
        qualname = code_obj->co_qualname;
    }
    assert(qualname != NULL);
    Py_INCREF(qualname);

    PyObject *consts = code_obj->co_consts;
    assert(PyTuple_Check(consts));
    PyObject *doc;
    PyObject *module = NULL;
    PyObject *builtins = NULL;
    if (code_obj->co_flags & CO_HAS_DOCSTRING) {
        assert(PyTuple_Size(consts) >= 1);
        doc = PyTuple_GetItem(consts, 0);
        if (doc == NULL) {
            goto error;
        }
        if (!PyUnicode_Check(doc)) {
            doc = Py_None;
        }
    }
    else {
        doc = Py_None;
    }
    Py_INCREF(doc);

    // __module__: Use globals['__name__'] if it exists, or NULL.
    if (PyDict_GetItemRef(globals, &_Py_ID(__name__), &module) < 0) {
        goto error;
    }

    builtins = _PyDict_LoadBuiltinsFromGlobals(globals);
    if (builtins == NULL) {
        goto error;
    }

    PyFunctionObject *op = PyObject_GC_New(PyFunctionObject, &PyFunction_Type);
    if (op == NULL) {
        goto error;
    }
    /* Note: No failures from this point on, since func_dealloc() does not
       expect a partially-created object. */

    op->func_globals = globals;
    op->func_builtins = builtins;
    op->func_name = name;
    op->func_qualname = qualname;
    op->func_code = (PyObject*)code_obj;
    op->func_defaults = NULL;    // No default positional arguments
    op->func_kwdefaults = NULL;  // No default keyword arguments
    op->func_closure = NULL;
    op->func_doc = doc;
    op->func_dict = NULL;
    op->func_weakreflist = NULL;
    op->func_module = module;
    op->func_annotations = NULL;
    op->func_annotate = NULL;
    op->func_typeparams = NULL;
    op->vectorcall = _PyFunction_Vectorcall;
    op->func_version = FUNC_VERSION_UNSET;
    func_update_shareable(op);
    if (((code_obj->co_flags & CO_NESTED) == 0) ||
        (code_obj->co_flags & CO_METHOD)) {
        // Use deferred reference counting for top-level functions, but not
        // nested functions because they are more likely to capture variables,
        // which makes prompt deallocation more important.
        //
        // Nested methods (functions defined in class scope) are also deferred,
        // since they will likely be cleaned up by GC anyway.
        _PyObject_SetDeferredRefcount((PyObject *)op);
    }
    _PyObject_GC_TRACK(op);
    handle_func_event(PyFunction_EVENT_CREATE, op, NULL);
    return (PyObject *)op;

error:
    Py_DECREF(globals);
    Py_DECREF(code_obj);
    Py_DECREF(name);
    Py_DECREF(qualname);
    Py_XDECREF(doc);
    Py_XDECREF(module);
    Py_XDECREF(builtins);
    return NULL;
}

/*
(This is purely internal documentation. There are no public APIs here.)

Function (and code) versions
----------------------------

The Tier 1 specializer generates CALL variants that can be invalidated
by changes to critical function attributes:

- __code__
- __defaults__
- __kwdefaults__
- __closure__

For this purpose function objects have a 32-bit func_version member
that the specializer writes to the specialized instruction's inline
cache and which is checked by a guard on the specialized instructions.

The MAKE_FUNCTION bytecode sets func_version from the code object's
co_version field.  The latter is initialized from a counter in the
interpreter state (interp->func_state.next_version) and never changes.
When this counter overflows, it remains zero and the specializer loses
the ability to specialize calls to new functions.

The func_version is reset to zero when any of the critical attributes
is modified; after this point the specializer will no longer specialize
calls to this function, and the guard will always fail.

The function and code version cache
-----------------------------------

The Tier 2 optimizer now has a problem, since it needs to find the
function and code objects given only the version number from the inline
cache.  Our solution is to maintain a cache mapping version numbers to
function and code objects.  To limit the cache size we could hash
the version number, but for now we simply use it modulo the table size.

There are some corner cases (e.g. generator expressions) where we will
be unable to find the function object in the cache but we can still
find the code object.  For this reason the cache stores both the
function object and the code object.

The cache doesn't contain strong references; cache entries are
invalidated whenever the function or code object is deallocated.

Invariants
----------

These should hold at any time except when one of the cache-mutating
functions is running.

- For any slot s at index i:
    - s->func == NULL or s->func->func_version % FUNC_VERSION_CACHE_SIZE == i
    - s->code == NULL or s->code->co_version % FUNC_VERSION_CACHE_SIZE == i
    if s->func != NULL, then s->func->func_code == s->code

*/

#ifndef Py_GIL_DISABLED
static inline struct _func_version_cache_item *
get_cache_item(PyInterpreterState *interp, uint32_t version)
{
    return interp->func_state.func_version_cache +
           (version % FUNC_VERSION_CACHE_SIZE);
}
#endif

void
_PyFunction_SetVersion(PyFunctionObject *func, uint32_t version)
{
    assert(func->func_version == FUNC_VERSION_UNSET);
    assert(version >= FUNC_VERSION_FIRST_VALID);
    // This should only be called from MAKE_FUNCTION. No code is specialized
    // based on the version, so we do not need to stop the world to set it.
    func->func_version = version;
#ifndef Py_GIL_DISABLED
    PyInterpreterState *interp = _PyInterpreterState_GET();
    struct _func_version_cache_item *slot = get_cache_item(interp, version);
    slot->func = func;
    slot->code = func->func_code;
#endif
}

static void
func_clear_version(PyInterpreterState *interp, PyFunctionObject *func)
{
    if (func->func_version < FUNC_VERSION_FIRST_VALID) {
        // Version was never set or has already been cleared.
        return;
    }
#ifndef Py_GIL_DISABLED
    struct _func_version_cache_item *slot =
        get_cache_item(interp, func->func_version);
    if (slot->func == func) {
        slot->func = NULL;
        // Leave slot->code alone, there may be use for it.
    }
#endif
    func->func_version = FUNC_VERSION_CLEARED;
}

void
_PyFunction_ClearCodeByVersion(uint32_t version)
{
#ifndef Py_GIL_DISABLED
    PyInterpreterState *interp = _PyInterpreterState_GET();
    struct _func_version_cache_item *slot = get_cache_item(interp, version);
    if (slot->code) {
        assert(PyCode_Check(slot->code));
        PyCodeObject *code = (PyCodeObject *)slot->code;
        if (code->co_version == version) {
            slot->code = NULL;
            slot->func = NULL;
        }
    }
#endif
}

uint32_t
_PyFunction_GetVersionForCurrentState(PyFunctionObject *func)
{
    return func->func_version;
}

PyObject *
PyFunction_New(PyObject *code, PyObject *globals)
{
    return PyFunction_NewWithQualName(code, globals, NULL);
}

PyObject *
PyFunction_GetCode(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    // This is a borrowed reference: rejection must not decref the value.
    return PyObject_CheckAccess(((PyFunctionObject *)op)->func_code);
}

PyObject *
PyFunction_GetGlobals(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    return PyObject_CheckAccess(((PyFunctionObject *)op)->func_globals);
}

PyObject *
PyFunction_GetModule(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    return PyObject_CheckAccess(((PyFunctionObject *)op)->func_module);
}

PyObject *
PyFunction_GetDefaults(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    return PyObject_CheckAccess(((PyFunctionObject *)op)->func_defaults);
}

int
PyFunction_SetDefaults(PyObject *op, PyObject *defaults)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return -1;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return -1;
    }
    if (func_check_mutation(op) < 0) {
        return -1;
    }
    if (defaults != NULL && defaults != Py_None &&
        PyObject_CheckAccess(defaults) == NULL) {
        return -1;
    }
    if (defaults == Py_None)
        defaults = NULL;
    else if (defaults && PyTuple_Check(defaults)) {
        Py_INCREF(defaults);
    }
    else {
        PyErr_SetString(PyExc_SystemError, "non-tuple default args");
        return -1;
    }
    PyFunctionObject *func = (PyFunctionObject *)op;
    if (warn_function_mutation("__defaults__") < 0) {
        Py_XDECREF(defaults);
        return -1;
    }
    handle_func_event(PyFunction_EVENT_MODIFY_DEFAULTS, func, defaults);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, op) < 0) {
        Py_XDECREF(defaults);
        return -1;
    }
    func_clear_version(interp, func);
    PyObject *old_defaults = func->func_defaults;
    func->func_defaults = defaults;
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_defaults);
    return 0;
}

void
PyFunction_SetVectorcall(PyFunctionObject *func, vectorcallfunc vectorcall)
{
    assert(func != NULL);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PyEval_StopTheWorld(interp);
    func_clear_version(interp, func);
    func->vectorcall = vectorcall;
    _PyEval_StartTheWorld(interp);
}

PyObject *
PyFunction_GetKwDefaults(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    return PyObject_CheckAccess(((PyFunctionObject *)op)->func_kwdefaults);
}

int
PyFunction_SetKwDefaults(PyObject *op, PyObject *defaults)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return -1;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return -1;
    }
    if (func_check_mutation(op) < 0) {
        return -1;
    }
    if (defaults != NULL && defaults != Py_None &&
        PyObject_CheckAccess(defaults) == NULL) {
        return -1;
    }
    if (defaults == Py_None)
        defaults = NULL;
    else if (defaults && PyAnyDict_Check(defaults)) {
        defaults = _PyFunction_CopyKwDefaults(defaults);
        if (defaults == NULL) {
            return -1;
        }
    }
    else {
        PyErr_SetString(PyExc_SystemError,
                        "non-dict keyword only default args");
        return -1;
    }
    PyFunctionObject *func = (PyFunctionObject *)op;
    if (warn_function_mutation("__kwdefaults__") < 0) {
        Py_XDECREF(defaults);
        return -1;
    }
    handle_func_event(PyFunction_EVENT_MODIFY_KWDEFAULTS, func, defaults);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, op) < 0) {
        Py_XDECREF(defaults);
        return -1;
    }
    func_clear_version(interp, func);
    PyObject *old_kwdefaults = func->func_kwdefaults;
    func->func_kwdefaults = defaults;
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_kwdefaults);
    return 0;
}

PyObject *
PyFunction_GetClosure(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    return PyObject_CheckAccess(((PyFunctionObject *)op)->func_closure);
}

int
PyFunction_SetClosure(PyObject *op, PyObject *closure)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return -1;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return -1;
    }
    if (func_check_mutation(op) < 0) {
        return -1;
    }
    if (closure != NULL && closure != Py_None &&
        PyObject_CheckAccess(closure) == NULL) {
        return -1;
    }
    if (closure == Py_None)
        closure = NULL;
    else if (PyTuple_Check(closure)) {
        Py_INCREF(closure);
    }
    else {
        PyErr_Format(PyExc_SystemError,
                     "expected tuple for closure, got '%.100s'",
                     Py_TYPE(closure)->tp_name);
        return -1;
    }
    PyFunctionObject *func = (PyFunctionObject *)op;
    if (warn_function_mutation("__closure__") < 0) {
        Py_XDECREF(closure);
        return -1;
    }
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_execution_mutation(interp, func, NULL, closure) < 0) {
        Py_XDECREF(closure);
        return -1;
    }
    func_clear_version(interp, func);
    PyObject *old_closure = func->func_closure;
    func_register_closure(closure, 1);
    func->func_closure = closure;
    func_register_closure(old_closure, 0);
    func_mark_closure_writers((PyCodeObject *)func->func_code, closure);
    func_update_shareable(func);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_closure);
    return 0;
}

static PyObject *
func_get_annotation_dict(PyFunctionObject *op)
{
    if (op->func_annotations == NULL) {
        if (op->func_annotate == NULL || !PyCallable_Check(op->func_annotate)) {
            Py_RETURN_NONE;
        }
        PyObject *one = _PyLong_GetOne();
        PyObject *ann_dict = _PyObject_CallOneArg(op->func_annotate, one);
        if (ann_dict == NULL) {
            return NULL;
        }
        if (!PyDict_Check(ann_dict)) {
            PyErr_Format(PyExc_TypeError,
                         "__annotate__() must return a dict, not %T",
                         ann_dict);
            Py_DECREF(ann_dict);
            return NULL;
        }
        Py_XSETREF(op->func_annotations, ann_dict);
        return ann_dict;
    }
    if (PyTuple_CheckExact(op->func_annotations)) {
        PyObject *ann_tuple = op->func_annotations;
        PyObject *ann_dict = PyDict_New();
        if (ann_dict == NULL) {
            return NULL;
        }

        assert(PyTuple_GET_SIZE(ann_tuple) % 2 == 0);

        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(ann_tuple); i += 2) {
            int err = PyDict_SetItem(ann_dict,
                                     PyTuple_GET_ITEM(ann_tuple, i),
                                     PyTuple_GET_ITEM(ann_tuple, i + 1));

            if (err < 0) {
                Py_DECREF(ann_dict);
                return NULL;
            }
        }
        Py_SETREF(op->func_annotations, ann_dict);
    }
    assert(PyDict_Check(op->func_annotations));
    return op->func_annotations;
}

PyObject *
PyFunction_GetAnnotations(PyObject *op)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return NULL;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    return PyObject_CheckAccess(func_get_annotation_dict((PyFunctionObject *)op));
}

int
PyFunction_SetAnnotations(PyObject *op, PyObject *annotations)
{
    if (!PyFunction_Check(op)) {
        PyErr_BadInternalCall();
        return -1;
    }
    if (PyObject_CheckAccess(op) == NULL) {
        return -1;
    }
    if (func_check_mutation(op) < 0) {
        return -1;
    }
    if (annotations != NULL && annotations != Py_None &&
        PyObject_CheckAccess(annotations) == NULL) {
        return -1;
    }
    if (annotations == Py_None)
        annotations = NULL;
    else if (annotations && PyDict_Check(annotations)) {
        Py_INCREF(annotations);
    }
    else {
        PyErr_SetString(PyExc_SystemError,
                        "non-dict annotations");
        return -1;
    }
    PyFunctionObject *func = (PyFunctionObject *)op;
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, op) < 0) {
        Py_XDECREF(annotations);
        return -1;
    }
    PyObject *old_annotations = func->func_annotations;
    func->func_annotations = annotations;
    PyObject *old_annotate = func->func_annotate;
    func->func_annotate = NULL;
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_annotations);
    Py_XDECREF(old_annotate);
    return 0;
}

/* Methods */

#define OFF(x) offsetof(PyFunctionObject, x)

static PyMemberDef func_memberlist[] = {
    {"__closure__",   _Py_T_OBJECT,     OFF(func_closure), Py_READONLY},
    {"__globals__",   _Py_T_OBJECT,     OFF(func_globals), Py_READONLY},
    {"__builtins__",  _Py_T_OBJECT,     OFF(func_builtins), Py_READONLY},
    {NULL}  /* Sentinel */
};

/*[clinic input]
class function "PyFunctionObject *" "&PyFunction_Type"
[clinic start generated code]*/
/*[clinic end generated code: output=da39a3ee5e6b4b0d input=70af9c90aa2e71b0]*/

#include "clinic/funcobject.c.h"

static PyObject *
func_get_code(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    if (PySys_Audit("object.__getattr__", "Os", op, "__code__") < 0) {
        return NULL;
    }

    return Py_NewRef(op->func_code);
}

static int
func_set_code(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    if (func_check_mutation(self) < 0) {
        return -1;
    }

    /* Not legal to del f.func_code or to set it to anything
     * other than a code object. */
    if (value == NULL || !PyCode_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "__code__ must be set to a code object");
        return -1;
    }

    if (PySys_Audit("object.__setattr__", "OsO",
                    op, "__code__", value) < 0) {
        return -1;
    }

    int nfree = ((PyCodeObject *)value)->co_nfreevars;
    Py_ssize_t nclosure = (op->func_closure == NULL ? 0 :
                                        PyTuple_GET_SIZE(op->func_closure));
    if (nclosure != nfree) {
        PyErr_Format(PyExc_ValueError,
                     "%U() requires a code object with %zd free vars,"
                     " not %d",
                     op->func_name,
                     nclosure, nfree);
        return -1;
    }

    PyObject *func_code = PyFunction_GET_CODE(op);
    int old_flags = ((PyCodeObject *)func_code)->co_flags;
    int new_flags = ((PyCodeObject *)value)->co_flags;
    int mask = CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR;
    if ((old_flags & mask) != (new_flags & mask)) {
        if (PyErr_Warn(PyExc_DeprecationWarning,
            "Assigning a code object of non-matching type is deprecated "
            "(e.g., from a generator to a plain function)") < 0)
        {
            return -1;
        }
    }
    else if (warn_function_mutation("__code__") < 0) {
        return -1;
    }

    handle_func_event(PyFunction_EVENT_MODIFY_CODE, op, value);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_execution_mutation(interp, op, value, NULL) < 0) {
        return -1;
    }
    func_clear_version(interp, op);
    PyObject *old_code = op->func_code;
    op->func_code = Py_NewRef(value);
    func_mark_closure_writers((PyCodeObject *)value, op->func_closure);
    func_update_shareable(op);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_code);
    return 0;
}

static PyObject *
func_get_name(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    return Py_NewRef(op->func_name);
}

static int
func_set_name(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    if (func_check_mutation(self) < 0) {
        return -1;
    }
    PyFunctionObject *op = _PyFunction_CAST(self);
    /* Not legal to del f.func_name or to set it to anything
     * other than a string object. */
    if (value == NULL || !PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "__name__ must be set to a string object");
        return -1;
    }
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, self) < 0) {
        return -1;
    }
    PyObject *old_name = op->func_name;
    op->func_name = Py_NewRef(value);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_name);
    return 0;
}

static PyObject *
func_get_qualname(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    return Py_NewRef(op->func_qualname);
}

static int
func_set_qualname(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    if (func_check_mutation(self) < 0) {
        return -1;
    }
    PyFunctionObject *op = _PyFunction_CAST(self);
    /* Not legal to del f.__qualname__ or to set it to anything
     * other than a string object. */
    if (value == NULL || !PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "__qualname__ must be set to a string object");
        return -1;
    }
    handle_func_event(PyFunction_EVENT_MODIFY_QUALNAME, (PyFunctionObject *) op, value);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, self) < 0) {
        return -1;
    }
    PyObject *old_qualname = op->func_qualname;
    op->func_qualname = Py_NewRef(value);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_qualname);
    return 0;
}

static PyObject *
func_get_doc(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    PyObject *doc = op->func_doc;
    if (doc == NULL) {
        doc = Py_None;
    }
    return Py_NewRef(doc);
}

static int
func_set_doc(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    if (func_check_mutation(self) < 0) {
        return -1;
    }
    /* Legal to del f.__doc__ or to set it to any object. */
    PyFunctionObject *op = _PyFunction_CAST(self);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, self) < 0) {
        return -1;
    }
    PyObject *old_doc = op->func_doc;
    op->func_doc = Py_XNewRef(value);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_doc);
    return 0;
}

static PyObject *
func_get_module(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    PyObject *module = op->func_module;
    if (module == NULL) {
        module = Py_None;
    }
    return Py_NewRef(module);
}

static int
func_set_module(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    if (func_check_mutation(self) < 0) {
        return -1;
    }
    /* Legal to del f.__module__ or to set it to any object. */
    PyFunctionObject *op = _PyFunction_CAST(self);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, self) < 0) {
        return -1;
    }
    PyObject *old_module = op->func_module;
    op->func_module = Py_XNewRef(value);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_module);
    return 0;
}

static PyObject *
func_get_defaults(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    if (PySys_Audit("object.__getattr__", "Os", op, "__defaults__") < 0) {
        return NULL;
    }
    if (op->func_defaults == NULL) {
        Py_RETURN_NONE;
    }
    return Py_NewRef(op->func_defaults);
}

static int
func_set_defaults(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    /* Legal to del f.func_defaults.
     * Can only set func_defaults to NULL or a tuple. */
    PyFunctionObject *op = _PyFunction_CAST(self);
    if (func_check_mutation(self) < 0) {
        return -1;
    }
    if (value == Py_None)
        value = NULL;
    if (value != NULL && !PyTuple_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "__defaults__ must be set to a tuple object");
        return -1;
    }
    if (value) {
        if (PySys_Audit("object.__setattr__", "OsO",
                        op, "__defaults__", value) < 0) {
            return -1;
        }
    } else if (PySys_Audit("object.__delattr__", "Os",
                           op, "__defaults__") < 0) {
        return -1;
    }

    if (warn_function_mutation("__defaults__") < 0) {
        return -1;
    }
    handle_func_event(PyFunction_EVENT_MODIFY_DEFAULTS, op, value);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, self) < 0) {
        return -1;
    }
    func_clear_version(interp, op);
    PyObject *old_defaults = op->func_defaults;
    op->func_defaults = Py_XNewRef(value);
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_defaults);
    return 0;
}

static PyObject *
func_get_kwdefaults(PyObject *self, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    if (PySys_Audit("object.__getattr__", "Os",
                    op, "__kwdefaults__") < 0) {
        return NULL;
    }
    if (op->func_kwdefaults == NULL) {
        Py_RETURN_NONE;
    }
    return Py_NewRef(op->func_kwdefaults);
}

static int
func_set_kwdefaults(PyObject *self, PyObject *value, void *Py_UNUSED(ignored))
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    if (func_check_mutation(self) < 0) {
        return -1;
    }
    if (value == Py_None)
        value = NULL;
    /* Legal to del f.func_kwdefaults.
     * Dictionary inputs are copied into a frozendict. */
    if (value != NULL && !PyAnyDict_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
            "__kwdefaults__ must be set to a dict or frozendict object");
        return -1;
    }
    if (value) {
        if (PySys_Audit("object.__setattr__", "OsO",
                        op, "__kwdefaults__", value) < 0) {
            return -1;
        }
    } else if (PySys_Audit("object.__delattr__", "Os",
                           op, "__kwdefaults__") < 0) {
        return -1;
    }

    if (warn_function_mutation("__kwdefaults__") < 0) {
        return -1;
    }
    PyObject *defaults = NULL;
    if (value != NULL) {
        defaults = _PyFunction_CopyKwDefaults(value);
        if (defaults == NULL) {
            return -1;
        }
    }
    handle_func_event(PyFunction_EVENT_MODIFY_KWDEFAULTS, op, defaults);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (func_begin_mutation(interp, self) < 0) {
        Py_XDECREF(defaults);
        return -1;
    }
    func_clear_version(interp, op);
    PyObject *old_kwdefaults = op->func_kwdefaults;
    op->func_kwdefaults = defaults;
    _PyEval_StartTheWorld(interp);
    Py_XDECREF(old_kwdefaults);
    return 0;
}

/*[clinic input]
@critical_section
@getter
function.__annotate__

Get the code object for a function.
[clinic start generated code]*/

static PyObject *
function___annotate___get_impl(PyFunctionObject *self)
/*[clinic end generated code: output=5ec7219ff2bda9e6 input=7f3db11e3c3329f3]*/
{
    if (self->func_annotate == NULL) {
        Py_RETURN_NONE;
    }
    return Py_NewRef(self->func_annotate);
}

/*[clinic input]
@critical_section
@setter
@deleter
function.__annotate__
[clinic start generated code]*/

static int
function___annotate___set_impl(PyFunctionObject *self, PyObject *value)
/*[clinic end generated code: output=05b7dfc07ada66cd input=4bcfad0bdcfec768]*/
{
    if (func_check_mutation((PyObject *)self) < 0) {
        return -1;
    }
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError,
            "__annotate__ cannot be deleted");
        return -1;
    }
    if (Py_IsNone(value)) {
        Py_XSETREF(self->func_annotate, Py_NewRef(value));
        return 0;
    }
    else if (PyCallable_Check(value)) {
        PyObject *old_annotate = self->func_annotate;
        PyObject *old_annotations = self->func_annotations;
        self->func_annotate = Py_NewRef(value);
        self->func_annotations = NULL;
        Py_XDECREF(old_annotate);
        Py_XDECREF(old_annotations);
        return 0;
    }
    else {
        PyErr_SetString(PyExc_TypeError,
            "__annotate__ must be callable or None");
        return -1;
    }
}

/*[clinic input]
@critical_section
@getter
function.__annotations__

Dict of annotations in a function object.
[clinic start generated code]*/

static PyObject *
function___annotations___get_impl(PyFunctionObject *self)
/*[clinic end generated code: output=a4cf4c884c934cbb input=92643d7186c1ad0c]*/
{
    PyObject *d = NULL;
    if (self->func_annotations == NULL &&
        (self->func_annotate == NULL || !PyCallable_Check(self->func_annotate))) {
        self->func_annotations = PyDict_New();
        if (self->func_annotations == NULL)
            return NULL;
    }
    d = func_get_annotation_dict(self);
    return Py_XNewRef(d);
}

/*[clinic input]
@critical_section
@setter
@deleter
function.__annotations__
[clinic start generated code]*/

static int
function___annotations___set_impl(PyFunctionObject *self, PyObject *value)
/*[clinic end generated code: output=a61795d4a95eede4 input=71f6a58c00ac6745]*/
{
    if (func_check_mutation((PyObject *)self) < 0) {
        return -1;
    }
    if (value == Py_None)
        value = NULL;
    /* Legal to del f.func_annotations.
     * Can only set func_annotations to NULL (through C api)
     * or a dict. */
    if (value != NULL && !PyDict_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
            "__annotations__ must be set to a dict object");
        return -1;
    }
    PyObject *old_annotations = self->func_annotations;
    PyObject *old_annotate = self->func_annotate;
    self->func_annotations = Py_XNewRef(value);
    self->func_annotate = NULL;
    Py_XDECREF(old_annotations);
    Py_XDECREF(old_annotate);
    return 0;
}

/*[clinic input]
@critical_section
@getter
function.__type_params__

Get the declared type parameters for a function.
[clinic start generated code]*/

static PyObject *
function___type_params___get_impl(PyFunctionObject *self)
/*[clinic end generated code: output=eb844d7ffca517a8 input=0864721484293724]*/
{
    if (self->func_typeparams == NULL) {
        return PyTuple_New(0);
    }

    assert(PyTuple_Check(self->func_typeparams));
    return Py_NewRef(self->func_typeparams);
}

/*[clinic input]
@critical_section
@setter
@deleter
function.__type_params__
[clinic start generated code]*/

static int
function___type_params___set_impl(PyFunctionObject *self, PyObject *value)
/*[clinic end generated code: output=038b4cda220e56fb input=c0e33abc5901a2f5]*/
{
    if (func_check_mutation((PyObject *)self) < 0) {
        return -1;
    }
    /* Not legal to del f.__type_params__ or to set it to anything
     * other than a tuple object. */
    if (value == NULL || !PyTuple_Check(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "__type_params__ must be set to a tuple");
        return -1;
    }
    Py_XSETREF(self->func_typeparams, Py_NewRef(value));
    return 0;
}

PyObject *
_Py_set_function_type_params(PyThreadState *Py_UNUSED(ignored), PyObject *func,
                             PyObject *type_params)
{
    assert(PyFunction_Check(func));
    assert(PyTuple_Check(type_params));
    PyFunctionObject *f = (PyFunctionObject *)func;
    Py_XSETREF(f->func_typeparams, Py_NewRef(type_params));
    return Py_NewRef(func);
}

static PyGetSetDef func_getsetlist[] = {
    {"__code__", func_get_code, func_set_code},
    {"__defaults__", func_get_defaults, func_set_defaults},
    {"__kwdefaults__", func_get_kwdefaults, func_set_kwdefaults},
    FUNCTION___ANNOTATIONS___GETSETDEF
    FUNCTION___ANNOTATE___GETSETDEF
    {"__dict__", PyObject_GenericGetDict, PyObject_GenericSetDict},
    {"__doc__", func_get_doc, func_set_doc},
    {"__module__", func_get_module, func_set_module},
    {"__name__", func_get_name, func_set_name},
    {"__qualname__", func_get_qualname, func_set_qualname},
    FUNCTION___TYPE_PARAMS___GETSETDEF
    {NULL} /* Sentinel */
};

/* function.__new__() maintains the following invariants for closures.
   The closure must correspond to the free variables of the code object.

   if len(code.co_freevars) == 0:
       closure = NULL
   else:
       len(closure) == len(code.co_freevars)
   for every elt in closure, type(elt) == cell
*/

/*[clinic input]
@classmethod
function.__new__ as func_new
    code: object(type="PyCodeObject *", subclass_of="&PyCode_Type")
        a code object
    globals: object
        the globals dictionary
    name: object = None
        a string that overrides the name from the code object
    argdefs as defaults: object = None
        a tuple that specifies the default argument values
    closure: object = None
        a tuple that supplies the bindings for free variables
    kwdefaults: object = None
        a dictionary that specifies the default keyword argument values

Create a function object.
[clinic start generated code]*/

static PyObject *
func_new_impl(PyTypeObject *type, PyCodeObject *code, PyObject *globals,
              PyObject *name, PyObject *defaults, PyObject *closure,
              PyObject *kwdefaults)
/*[clinic end generated code: output=de72f4c22ac57144 input=fa23f0af20c9ac47]*/
{
    PyFunctionObject *newfunc;
    Py_ssize_t nclosure;

    if (!PyAnyDict_Check(globals)) {
        _PyArg_BadArgument("function", "argument 'globals'",
                           "dict or frozendict", globals);
        return NULL;
    }
    if (name != Py_None && !PyUnicode_Check(name)) {
        PyErr_SetString(PyExc_TypeError,
                        "arg 3 (name) must be None or string");
        return NULL;
    }
    if (defaults != Py_None && !PyTuple_Check(defaults)) {
        PyErr_SetString(PyExc_TypeError,
                        "arg 4 (defaults) must be None or tuple");
        return NULL;
    }
    if (!PyTuple_Check(closure)) {
        if (code->co_nfreevars && closure == Py_None) {
            PyErr_SetString(PyExc_TypeError,
                            "arg 5 (closure) must be tuple");
            return NULL;
        }
        else if (closure != Py_None) {
            PyErr_SetString(PyExc_TypeError,
                "arg 5 (closure) must be None or tuple");
            return NULL;
        }
    }
    if (kwdefaults != Py_None && !PyAnyDict_Check(kwdefaults)) {
        PyErr_SetString(PyExc_TypeError,
                        "arg 6 (kwdefaults) must be None, dict or frozendict");
        return NULL;
    }

    /* check that the closure is well-formed */
    nclosure = closure == Py_None ? 0 : PyTuple_GET_SIZE(closure);
    if (code->co_nfreevars != nclosure)
        return PyErr_Format(PyExc_ValueError,
                            "%U requires closure of length %d, not %zd",
                            code->co_name, code->co_nfreevars, nclosure);
    if (nclosure) {
        Py_ssize_t i;
        for (i = 0; i < nclosure; i++) {
            PyObject *o = PyTuple_GET_ITEM(closure, i);
            if (!PyCell_Check(o)) {
                return PyErr_Format(PyExc_TypeError,
                    "arg 5 (closure) expected cell, found %s",
                                    Py_TYPE(o)->tp_name);
            }
        }
    }
    if (PySys_Audit("function.__new__", "O", code) < 0) {
        return NULL;
    }

    PyObject *frozen_kwdefaults = NULL;
    if (kwdefaults != Py_None) {
        frozen_kwdefaults = _PyFunction_CopyKwDefaults(kwdefaults);
        if (frozen_kwdefaults == NULL) {
            return NULL;
        }
    }
    newfunc = (PyFunctionObject *)PyFunction_New((PyObject *)code,
                                                 globals);
    if (newfunc == NULL) {
        Py_XDECREF(frozen_kwdefaults);
        return NULL;
    }
    if (name != Py_None) {
        Py_SETREF(newfunc->func_name, Py_NewRef(name));
    }
    if (defaults != Py_None) {
        newfunc->func_defaults = Py_NewRef(defaults);
    }
    if (closure != Py_None &&
        _PyFunction_SetClosureForCreation(newfunc, closure) < 0) {
        Py_DECREF(newfunc);
        Py_XDECREF(frozen_kwdefaults);
        return NULL;
    }
    newfunc->func_kwdefaults = frozen_kwdefaults;

    return (PyObject *)newfunc;
}

static int
func_clear(PyObject *self)
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    func_clear_version(_PyInterpreterState_GET(), op);
    PyObject *globals = op->func_globals;
    op->func_globals = NULL;
    if (globals != NULL) {
        _Py_DECREF_DICT(globals);
    }
    PyObject *builtins = op->func_builtins;
    op->func_builtins = NULL;
    if (builtins != NULL) {
        _Py_DECREF_BUILTINS(builtins);
    }
    Py_CLEAR(op->func_module);
    Py_CLEAR(op->func_defaults);
    Py_CLEAR(op->func_kwdefaults);
    Py_CLEAR(op->func_doc);
    Py_CLEAR(op->func_dict);
    PyObject *old_closure = op->func_closure;
    op->func_closure = NULL;
    func_register_closure(old_closure, 0);
    Py_XDECREF(old_closure);
    Py_CLEAR(op->func_annotations);
    Py_CLEAR(op->func_annotate);
    Py_CLEAR(op->func_typeparams);
    // Don't Py_CLEAR(op->func_code), since code is always required
    // to be non-NULL. Similarly, name and qualname shouldn't be NULL.
    // However, name and qualname could be str subclasses, so they
    // could have reference cycles. The solution is to replace them
    // with a genuinely immutable string.
    Py_SETREF(op->func_name, &_Py_STR(empty));
    Py_SETREF(op->func_qualname, &_Py_STR(empty));
    return 0;
}

static void
func_dealloc(PyObject *self)
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    _PyObject_ResurrectStart(self);
    handle_func_event(PyFunction_EVENT_DESTROY, op, NULL);
    if (_PyObject_ResurrectEnd(self)) {
        return;
    }
    _PyObject_GC_UNTRACK(op);
    FT_CLEAR_WEAKREFS(self, op->func_weakreflist);
    (void)func_clear((PyObject*)op);
    // These aren't cleared by func_clear().
    _Py_DECREF_CODE((PyCodeObject *)op->func_code);
    Py_DECREF(op->func_name);
    Py_DECREF(op->func_qualname);
    PyObject_GC_Del(op);
}

static PyObject*
func_repr(PyObject *self)
{
    PyFunctionObject *op = _PyFunction_CAST(self);
    return PyUnicode_FromFormat("<function %U at %p>",
                                op->func_qualname, op);
}

static int
func_traverse(PyObject *self, visitproc visit, void *arg)
{
    PyFunctionObject *f = _PyFunction_CAST(self);
    Py_VISIT(f->func_code);
    Py_VISIT(f->func_globals);
    Py_VISIT(f->func_builtins);
    Py_VISIT(f->func_module);
    Py_VISIT(f->func_defaults);
    Py_VISIT(f->func_kwdefaults);
    Py_VISIT(f->func_doc);
    Py_VISIT(f->func_name);
    Py_VISIT(f->func_dict);
    Py_VISIT(f->func_closure);
    Py_VISIT(f->func_annotations);
    Py_VISIT(f->func_annotate);
    Py_VISIT(f->func_typeparams);
    Py_VISIT(f->func_qualname);
    return 0;
}

/* Bind a function to an object */
static PyObject *
func_descr_get(PyObject *func, PyObject *obj, PyObject *type)
{
    if (obj == Py_None || obj == NULL) {
        return Py_NewRef(func);
    }
    return PyMethod_New(func, obj);
}

PyTypeObject PyFunction_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "function",
    sizeof(PyFunctionObject),
    0,
    func_dealloc,                               /* tp_dealloc */
    offsetof(PyFunctionObject, vectorcall),     /* tp_vectorcall_offset */
    0,                                          /* tp_getattr */
    0,                                          /* tp_setattr */
    0,                                          /* tp_as_async */
    func_repr,                                  /* tp_repr */
    0,                                          /* tp_as_number */
    0,                                          /* tp_as_sequence */
    0,                                          /* tp_as_mapping */
    0,                                          /* tp_hash */
    PyVectorcall_Call,                          /* tp_call */
    0,                                          /* tp_str */
    0,                                          /* tp_getattro */
    0,                                          /* tp_setattro */
    0,                                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC |
    Py_TPFLAGS_HAVE_VECTORCALL |
    Py_TPFLAGS_METHOD_DESCRIPTOR,               /* tp_flags */
    func_new__doc__,                            /* tp_doc */
    func_traverse,                              /* tp_traverse */
    func_clear,                                 /* tp_clear */
    0,                                          /* tp_richcompare */
    offsetof(PyFunctionObject, func_weakreflist), /* tp_weaklistoffset */
    0,                                          /* tp_iter */
    0,                                          /* tp_iternext */
    0,                                          /* tp_methods */
    func_memberlist,                            /* tp_members */
    func_getsetlist,                            /* tp_getset */
    0,                                          /* tp_base */
    0,                                          /* tp_dict */
    func_descr_get,                             /* tp_descr_get */
    0,                                          /* tp_descr_set */
    offsetof(PyFunctionObject, func_dict),      /* tp_dictoffset */
    0,                                          /* tp_init */
    0,                                          /* tp_alloc */
    func_new,                                   /* tp_new */
};


int
_PyFunction_VerifyStateless(PyThreadState *tstate, PyObject *func)
{
    assert(!PyErr_Occurred());
    assert(PyFunction_Check(func));

    // Check the globals.
    PyObject *globalsns = PyFunction_GET_GLOBALS(func);
    if (globalsns != NULL && !PyDict_Check(globalsns)) {
        _PyErr_Format(tstate, PyExc_TypeError,
                      "unsupported globals %R", globalsns);
        return -1;
    }
    // Check the builtins.
    PyObject *builtinsns = _PyFunction_GET_BUILTINS(func);
    if (builtinsns != NULL && !PyDict_Check(builtinsns)) {
        _PyErr_Format(tstate, PyExc_TypeError,
                      "unsupported builtins %R", builtinsns);
        return -1;
    }
    // Disallow __defaults__.
    PyObject *defaults = PyFunction_GET_DEFAULTS(func);
    if (defaults != NULL) {
        assert(PyTuple_Check(defaults));  // per PyFunction_New()
        if (PyTuple_GET_SIZE(defaults) > 0) {
            _PyErr_SetString(tstate, PyExc_ValueError,
                             "defaults not supported");
            return -1;
        }
    }
    // Disallow __kwdefaults__.
    PyObject *kwdefaults = PyFunction_GET_KW_DEFAULTS(func);
    if (kwdefaults != NULL) {
        assert(PyFrozenDict_CheckExact(kwdefaults));
        if (PyDict_Size(kwdefaults) > 0) {
            _PyErr_SetString(tstate, PyExc_ValueError,
                             "keyword defaults not supported");
            return -1;
        }
    }
    // Disallow __closure__.
    PyObject *closure = PyFunction_GET_CLOSURE(func);
    if (closure != NULL) {
        assert(PyTuple_Check(closure));  // per PyFunction_New()
        if (PyTuple_GET_SIZE(closure) > 0) {
            _PyErr_SetString(tstate, PyExc_ValueError, "closures not supported");
            return -1;
        }
    }
    // Check the code.
    PyCodeObject *co = (PyCodeObject *)PyFunction_GET_CODE(func);
    if (_PyCode_VerifyStateless(tstate, co, NULL, globalsns, builtinsns) < 0) {
        return -1;
    }
    return 0;
}


static int
functools_copy_attr(PyObject *wrapper, PyObject *wrapped, PyObject *name)
{
    PyObject *value;
    int res = PyObject_GetOptionalAttr(wrapped, name, &value);
    if (value != NULL) {
        res = PyObject_SetAttr(wrapper, name, value);
        Py_DECREF(value);
    }
    return res;
}

// Similar to functools.wraps(wrapper, wrapped)
static int
functools_wraps(PyObject *wrapper, PyObject *wrapped)
{
#define COPY_ATTR(ATTR) \
    do { \
        if (functools_copy_attr(wrapper, wrapped, &_Py_ID(ATTR)) < 0) { \
            return -1; \
        } \
    } while (0) \

    COPY_ATTR(__module__);
    COPY_ATTR(__name__);
    COPY_ATTR(__qualname__);
    COPY_ATTR(__doc__);
    return 0;

#undef COPY_ATTR
}

// Used for wrapping __annotations__ and __annotate__ on classmethod
// and staticmethod objects.
static PyObject *
descriptor_get_wrapped_attribute(PyObject *wrapped, PyObject *obj, PyObject *name)
{
    PyObject *dict = PyObject_GenericGetDict(obj, NULL);
    if (dict == NULL) {
        return NULL;
    }
    PyObject *res;
    if (PyDict_GetItemRef(dict, name, &res) < 0) {
        Py_DECREF(dict);
        return NULL;
    }
    if (res != NULL) {
        Py_DECREF(dict);
        return res;
    }
    res = PyObject_GetAttr(wrapped, name);
    if (res == NULL) {
        Py_DECREF(dict);
        return NULL;
    }
    if (PyDict_SetItem(dict, name, res) < 0) {
        Py_DECREF(dict);
        Py_DECREF(res);
        return NULL;
    }
    Py_DECREF(dict);
    return res;
}

static int
descriptor_set_wrapped_attribute(PyObject *oobj, PyObject *name, PyObject *value,
                                 char *type_name)
{
    PyObject *dict = PyObject_GenericGetDict(oobj, NULL);
    if (dict == NULL) {
        return -1;
    }
    if (value == NULL) {
        if (PyDict_DelItem(dict, name) < 0) {
            if (PyErr_ExceptionMatches(PyExc_KeyError)) {
                PyErr_Clear();
                PyErr_Format(PyExc_AttributeError,
                             "'%.200s' object has no attribute '%U'",
                             type_name, name);
                Py_DECREF(dict);
                return -1;
            }
            else {
                Py_DECREF(dict);
                return -1;
            }
        }
        Py_DECREF(dict);
        return 0;
    }
    else {
        Py_DECREF(dict);
        return PyDict_SetItem(dict, name, value);
    }
}


/* Class method object */

/* A class method receives the class as implicit first argument,
   just like an instance method receives the instance.
   To declare a class method, use this idiom:

     class C:
         @classmethod
         def f(cls, arg1, arg2, argN):
             ...

   It can be called either on the class (e.g. C.f()) or on an instance
   (e.g. C().f()); the instance is ignored except for its class.
   If a class method is called for a derived class, the derived class
   object is passed as the implied first argument.

   Class methods are different than C++ or Java static methods.
   If you want those, see static methods below.
*/

typedef struct {
    PyObject_HEAD
    PyObject *cm_callable;
    PyObject *cm_dict;
} classmethod;

#define _PyClassMethod_CAST(cm) \
    (assert(PyObject_TypeCheck((cm), &PyClassMethod_Type)), \
     _Py_CAST(classmethod*, cm))

static void
cm_dealloc(PyObject *self)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    _PyObject_GC_UNTRACK((PyObject *)cm);
    Py_XDECREF(cm->cm_callable);
    Py_XDECREF(cm->cm_dict);
    Py_TYPE(cm)->tp_free((PyObject *)cm);
}

static int
cm_traverse(PyObject *self, visitproc visit, void *arg)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    Py_VISIT(cm->cm_callable);
    Py_VISIT(cm->cm_dict);
    return 0;
}

static int
cm_clear(PyObject *self)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    Py_CLEAR(cm->cm_callable);
    Py_CLEAR(cm->cm_dict);
    return 0;
}


static PyObject *
cm_descr_get(PyObject *self, PyObject *obj, PyObject *type)
{
    classmethod *cm = (classmethod *)self;
    if (type == NULL)
        type = (PyObject *)(Py_TYPE(obj));
    return PyMethod_New(cm->cm_callable, type);
}

static int
cm_set_callable(classmethod *cm, PyObject *callable)
{
    assert(callable != NULL);
    if (PyObject_CheckAccess((PyObject *)cm) == NULL ||
        PyObject_CheckAccess(callable) == NULL) {
        return -1;
    }
    if (cm->cm_callable == callable) {
        // cm_init() sets the same callable than cm_new()
        return 0;
    }

    Py_XSETREF(cm->cm_callable, Py_NewRef(callable));
    return functools_wraps((PyObject *)cm, cm->cm_callable);
}

static PyObject *
cm_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    if (!_PyArg_NoKeywords("classmethod", kwds)) {
        return NULL;
    }
    PyObject *callable;  // borrowed ref
    if (!PyArg_UnpackTuple(args, "classmethod", 1, 1, &callable)) {
        return NULL;
    }

    classmethod *cm = (classmethod *)PyType_GenericAlloc(type, 0);
    if (cm == NULL) {
        return NULL;
    }
    _PyObject_SetDeferredRefcount((PyObject *)cm);
    if (cm_set_callable(cm, callable) < 0) {
        Py_DECREF(cm);
        return NULL;
    }
    return (PyObject *)cm;
}

static int
cm_init(PyObject *self, PyObject *args, PyObject *kwds)
{
    if (!_PyArg_NoKeywords("classmethod", kwds)) {
        return -1;
    }
    PyObject *callable;  // borrowed ref
    if (!PyArg_UnpackTuple(args, "classmethod", 1, 1, &callable)) {
        return -1;
    }

    classmethod *cm = (classmethod *)self;
    return cm_set_callable(cm, callable);
}

static PyMemberDef cm_memberlist[] = {
    {"__func__", _Py_T_OBJECT, offsetof(classmethod, cm_callable), Py_READONLY},
    {"__wrapped__", _Py_T_OBJECT, offsetof(classmethod, cm_callable), Py_READONLY},
    {NULL}  /* Sentinel */
};

static PyObject *
cm_get___isabstractmethod__(PyObject *self, void *closure)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    int res = _PyObject_IsAbstract(cm->cm_callable);
    if (res == -1) {
        return NULL;
    }
    else if (res) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *
cm_get___annotations__(PyObject *self, void *closure)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    return descriptor_get_wrapped_attribute(cm->cm_callable, self, &_Py_ID(__annotations__));
}

static int
cm_set___annotations__(PyObject *self, PyObject *value, void *closure)
{
    return descriptor_set_wrapped_attribute(self, &_Py_ID(__annotations__), value, "classmethod");
}

static PyObject *
cm_get___annotate__(PyObject *self, void *closure)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    return descriptor_get_wrapped_attribute(cm->cm_callable, self, &_Py_ID(__annotate__));
}

static int
cm_set___annotate__(PyObject *self, PyObject *value, void *closure)
{
    return descriptor_set_wrapped_attribute(self, &_Py_ID(__annotate__), value, "classmethod");
}


static PyGetSetDef cm_getsetlist[] = {
    {"__isabstractmethod__", cm_get___isabstractmethod__, NULL, NULL, NULL},
    {"__dict__", PyObject_GenericGetDict, PyObject_GenericSetDict, NULL, NULL},
    {"__annotations__", cm_get___annotations__, cm_set___annotations__, NULL, NULL},
    {"__annotate__", cm_get___annotate__, cm_set___annotate__, NULL, NULL},
    {NULL} /* Sentinel */
};

static PyMethodDef cm_methodlist[] = {
    {"__class_getitem__", Py_GenericAlias, METH_O|METH_CLASS, NULL},
    {NULL} /* Sentinel */
};

static PyObject*
cm_repr(PyObject *self)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    return PyUnicode_FromFormat("<classmethod(%R)>", cm->cm_callable);
}

PyDoc_STRVAR(classmethod_doc,
"classmethod(function, /)\n\
--\n\
\n\
Convert a function to be a class method.\n\
\n\
A class method receives the class as implicit first argument,\n\
just like an instance method receives the instance.\n\
To declare a class method, use this idiom:\n\
\n\
  class C:\n\
      @classmethod\n\
      def f(cls, arg1, arg2, argN):\n\
          ...\n\
\n\
It can be called either on the class (e.g. C.f()) or on an instance\n\
(e.g. C().f()).  The instance is ignored except for its class.\n\
If a class method is called for a derived class, the derived class\n\
object is passed as the implied first argument.\n\
\n\
Class methods are different than C++ or Java static methods.\n\
If you want those, see the staticmethod builtin.");

PyTypeObject PyClassMethod_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "classmethod",
    sizeof(classmethod),
    0,
    cm_dealloc,                                 /* tp_dealloc */
    0,                                          /* tp_vectorcall_offset */
    0,                                          /* tp_getattr */
    0,                                          /* tp_setattr */
    0,                                          /* tp_as_async */
    cm_repr,                                    /* tp_repr */
    0,                                          /* tp_as_number */
    0,                                          /* tp_as_sequence */
    0,                                          /* tp_as_mapping */
    0,                                          /* tp_hash */
    0,                                          /* tp_call */
    0,                                          /* tp_str */
    0,                                          /* tp_getattro */
    0,                                          /* tp_setattro */
    0,                                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    classmethod_doc,                            /* tp_doc */
    cm_traverse,                                /* tp_traverse */
    cm_clear,                                   /* tp_clear */
    0,                                          /* tp_richcompare */
    0,                                          /* tp_weaklistoffset */
    0,                                          /* tp_iter */
    0,                                          /* tp_iternext */
    cm_methodlist,                              /* tp_methods */
    cm_memberlist,                              /* tp_members */
    cm_getsetlist,                              /* tp_getset */
    0,                                          /* tp_base */
    0,                                          /* tp_dict */
    cm_descr_get,                               /* tp_descr_get */
    0,                                          /* tp_descr_set */
    offsetof(classmethod, cm_dict),             /* tp_dictoffset */
    cm_init,                                    /* tp_init */
    PyType_GenericAlloc,                        /* tp_alloc */
    cm_new,                                     /* tp_new */
    PyObject_GC_Del,                            /* tp_free */
};

PyObject *
PyClassMethod_New(PyObject *callable)
{
    classmethod *cm = (classmethod *)
        PyType_GenericAlloc(&PyClassMethod_Type, 0);
    if (cm == NULL) {
        return NULL;
    }
    if (cm_set_callable(cm, callable) < 0) {
        Py_DECREF(cm);
        return NULL;
    }
    return (PyObject *)cm;
}


/* Static method object */

/* A static method does not receive an implicit first argument.
   To declare a static method, use this idiom:

     class C:
         @staticmethod
         def f(arg1, arg2, argN):
             ...

   It can be called either on the class (e.g. C.f()) or on an instance
   (e.g. C().f()). Both the class and the instance are ignored, and
   neither is passed implicitly as the first argument to the method.

   Static methods in Python are similar to those found in Java or C++.
   For a more advanced concept, see class methods above.
*/

typedef struct {
    PyObject_HEAD
    PyObject *sm_callable;
    PyObject *sm_dict;
} staticmethod;

#define _PyStaticMethod_CAST(cm) \
    (assert(PyObject_TypeCheck((cm), &PyStaticMethod_Type)), \
     _Py_CAST(staticmethod*, cm))

static void
sm_dealloc(PyObject *self)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    _PyObject_GC_UNTRACK((PyObject *)sm);
    Py_XDECREF(sm->sm_callable);
    Py_XDECREF(sm->sm_dict);
    Py_TYPE(sm)->tp_free((PyObject *)sm);
}

static int
sm_traverse(PyObject *self, visitproc visit, void *arg)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    Py_VISIT(sm->sm_callable);
    Py_VISIT(sm->sm_dict);
    return 0;
}

static int
sm_clear(PyObject *self)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    Py_CLEAR(sm->sm_callable);
    Py_CLEAR(sm->sm_dict);
    return 0;
}

static PyObject *
sm_descr_get(PyObject *self, PyObject *obj, PyObject *type)
{
    staticmethod *sm = (staticmethod *)self;
    return Py_NewRef(sm->sm_callable);
}

static int
sm_set_callable(staticmethod *sm, PyObject *callable)
{
    assert(callable != NULL);
    if (PyObject_CheckAccess((PyObject *)sm) == NULL ||
        PyObject_CheckAccess(callable) == NULL) {
        return -1;
    }
    if (sm->sm_callable == callable) {
        // sm_init() sets the same callable than sm_new()
        return 0;
    }

    Py_XSETREF(sm->sm_callable, Py_NewRef(callable));
    return functools_wraps((PyObject *)sm, sm->sm_callable);
}

static PyObject *
sm_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    if (!_PyArg_NoKeywords("staticmethod", kwds)) {
        return NULL;
    }
    PyObject *callable;  // borrowed ref
    if (!PyArg_UnpackTuple(args, "staticmethod", 1, 1, &callable)) {
        return NULL;
    }

    staticmethod *sm = (staticmethod *)PyType_GenericAlloc(type, 0);
    if (sm == NULL) {
        return NULL;
    }
    _PyObject_SetDeferredRefcount((PyObject *)sm);
    if (sm_set_callable(sm, callable) < 0) {
        Py_DECREF(sm);
        return NULL;
    }
    return (PyObject *)sm;
}

static int
sm_init(PyObject *self, PyObject *args, PyObject *kwds)
{
    if (!_PyArg_NoKeywords("staticmethod", kwds)) {
        return -1;
    }
    PyObject *callable;  // borrowed ref
    if (!PyArg_UnpackTuple(args, "staticmethod", 1, 1, &callable)) {
        return -1;
    }

    staticmethod *sm = (staticmethod *)self;
    return sm_set_callable(sm, callable);
}

static PyObject*
sm_call(PyObject *callable, PyObject *args, PyObject *kwargs)
{
    staticmethod *sm = (staticmethod *)callable;
    return PyObject_Call(sm->sm_callable, args, kwargs);
}

static PyMemberDef sm_memberlist[] = {
    {"__func__", _Py_T_OBJECT, offsetof(staticmethod, sm_callable), Py_READONLY},
    {"__wrapped__", _Py_T_OBJECT, offsetof(staticmethod, sm_callable), Py_READONLY},
    {NULL}  /* Sentinel */
};

static PyObject *
sm_get___isabstractmethod__(PyObject *self, void *closure)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    int res = _PyObject_IsAbstract(sm->sm_callable);
    if (res == -1) {
        return NULL;
    }
    else if (res) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *
sm_get___annotations__(PyObject *self, void *closure)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    return descriptor_get_wrapped_attribute(sm->sm_callable, self, &_Py_ID(__annotations__));
}

static int
sm_set___annotations__(PyObject *self, PyObject *value, void *closure)
{
    return descriptor_set_wrapped_attribute(self, &_Py_ID(__annotations__), value, "staticmethod");
}

static PyObject *
sm_get___annotate__(PyObject *self, void *closure)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    return descriptor_get_wrapped_attribute(sm->sm_callable, self, &_Py_ID(__annotate__));
}

static int
sm_set___annotate__(PyObject *self, PyObject *value, void *closure)
{
    return descriptor_set_wrapped_attribute(self, &_Py_ID(__annotate__), value, "staticmethod");
}

static PyGetSetDef sm_getsetlist[] = {
    {"__isabstractmethod__", sm_get___isabstractmethod__, NULL, NULL, NULL},
    {"__dict__", PyObject_GenericGetDict, PyObject_GenericSetDict, NULL, NULL},
    {"__annotations__", sm_get___annotations__, sm_set___annotations__, NULL, NULL},
    {"__annotate__", sm_get___annotate__, sm_set___annotate__, NULL, NULL},
    {NULL} /* Sentinel */
};

static PyMethodDef sm_methodlist[] = {
    {"__class_getitem__", Py_GenericAlias, METH_O|METH_CLASS, NULL},
    {NULL} /* Sentinel */
};

static PyObject*
sm_repr(PyObject *self)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    return PyUnicode_FromFormat("<staticmethod(%R)>", sm->sm_callable);
}

PyDoc_STRVAR(staticmethod_doc,
"staticmethod(function, /)\n\
--\n\
\n\
Convert a function to be a static method.\n\
\n\
A static method does not receive an implicit first argument.\n\
To declare a static method, use this idiom:\n\
\n\
     class C:\n\
         @staticmethod\n\
         def f(arg1, arg2, argN):\n\
             ...\n\
\n\
It can be called either on the class (e.g. C.f()) or on an instance\n\
(e.g. C().f()). Both the class and the instance are ignored, and\n\
neither is passed implicitly as the first argument to the method.\n\
\n\
Static methods in Python are similar to those found in Java or C++.\n\
For a more advanced concept, see the classmethod builtin.");

PyTypeObject PyStaticMethod_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "staticmethod",
    sizeof(staticmethod),
    0,
    sm_dealloc,                                 /* tp_dealloc */
    0,                                          /* tp_vectorcall_offset */
    0,                                          /* tp_getattr */
    0,                                          /* tp_setattr */
    0,                                          /* tp_as_async */
    sm_repr,                                    /* tp_repr */
    0,                                          /* tp_as_number */
    0,                                          /* tp_as_sequence */
    0,                                          /* tp_as_mapping */
    0,                                          /* tp_hash */
    sm_call,                                    /* tp_call */
    0,                                          /* tp_str */
    0,                                          /* tp_getattro */
    0,                                          /* tp_setattro */
    0,                                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    staticmethod_doc,                           /* tp_doc */
    sm_traverse,                                /* tp_traverse */
    sm_clear,                                   /* tp_clear */
    0,                                          /* tp_richcompare */
    0,                                          /* tp_weaklistoffset */
    0,                                          /* tp_iter */
    0,                                          /* tp_iternext */
    sm_methodlist,                              /* tp_methods */
    sm_memberlist,                              /* tp_members */
    sm_getsetlist,                              /* tp_getset */
    0,                                          /* tp_base */
    0,                                          /* tp_dict */
    sm_descr_get,                               /* tp_descr_get */
    0,                                          /* tp_descr_set */
    offsetof(staticmethod, sm_dict),            /* tp_dictoffset */
    sm_init,                                    /* tp_init */
    PyType_GenericAlloc,                        /* tp_alloc */
    sm_new,                                     /* tp_new */
    PyObject_GC_Del,                            /* tp_free */
};

PyObject *
PyStaticMethod_New(PyObject *callable)
{
    staticmethod *sm = (staticmethod *)
        PyType_GenericAlloc(&PyStaticMethod_Type, 0);
    if (sm == NULL) {
        return NULL;
    }
    _PyObject_SetDeferredRefcount((PyObject *)sm);
    if (sm_set_callable(sm, callable) < 0) {
        Py_DECREF(sm);
        return NULL;
    }
    return (PyObject *)sm;
}

PyObject *
_PyClassMethod_GetFunc(PyObject *self)
{
    classmethod *cm = _PyClassMethod_CAST(self);
    return cm->cm_callable;
}

PyObject *
_PyStaticMethod_GetFunc(PyObject *self)
{
    staticmethod *sm = _PyStaticMethod_CAST(self);
    return sm->sm_callable;
}
