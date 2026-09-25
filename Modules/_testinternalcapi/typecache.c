// Test wrappers for the per-type lookup cache (pycore_typecache.h).
//
// Insertion is exercised indirectly through normal attribute access (which
// calls _PyType_Lookup); only Lookup and Invalidate need direct wrappers.

#include "parts.h"

#include "pycore_critical_section.h"
#include "pycore_lock.h"
#include "pycore_pystate.h"       // _PyInterpreterState_GET()
#include "pycore_stackref.h"      // PyStackRef_AsPyObjectSteal()
#include "pycore_typecache.h"     // _PyTypeCache_Lookup()


static int
require_type(PyObject *obj)
{
    if (!PyType_Check(obj)) {
        PyErr_SetString(PyExc_TypeError, "expected a type");
        return -1;
    }
    return 0;
}

static PyObject *
intern_name(PyObject *name)
{
    if (!PyUnicode_CheckExact(name)) {
        PyErr_SetString(PyExc_TypeError, "name must be a str");
        return NULL;
    }
    Py_INCREF(name);
    PyUnicode_InternInPlace(&name);
    return name;
}

// type_cache_lookup(type, name) -> (cache_hit, value_or_None, version_tag)
static PyObject *
type_cache_lookup(PyObject *Py_UNUSED(self), PyObject *args)
{
    PyObject *type_obj, *name;
    if (!PyArg_ParseTuple(args, "OU", &type_obj, &name)) {
        return NULL;
    }
    if (require_type(type_obj) < 0) {
        return NULL;
    }
    name = intern_name(name);
    if (name == NULL) {
        return NULL;
    }
    struct _PyTypeCacheLookupResult r =
        _PyTypeCache_Lookup((PyTypeObject *)type_obj, name);
    Py_DECREF(name);
    PyObject *value;
    if (PyStackRef_IsNull(r.value)) {
        value = Py_NewRef(Py_None);
    }
    else {
        value = PyStackRef_AsPyObjectSteal(r.value);
    }
    return Py_BuildValue("(iNk)",
                         r.cache_hit, value,
                         (unsigned long)r.version_tag);
}

static PyObject *
type_cache_invalidate(PyObject *Py_UNUSED(self), PyObject *type_obj)
{
    if (require_type(type_obj) < 0) {
        return NULL;
    }
    PyThreadState *tstate = _PyThreadState_GET();
    PyCriticalSection section;
    _PyCriticalSection_BeginMutex(tstate, &section, &tstate->interp->types.mutex);
    _PyTypeCache_Invalidate((PyTypeObject *)type_obj);
    _PyCriticalSection_End(tstate, &section);
    Py_RETURN_NONE;
}

struct cache_reader_probe {
    PyThreadState *tstate;
    PyTypeObject *type;
    PyObject *name;
    PyEvent done;
    int cache_hit;
};

static void
cache_reader_worker(void *arg)
{
    struct cache_reader_probe *probe = arg;
    PyEval_AcquireThread(probe->tstate);
    struct _PyTypeCacheLookupResult result =
        _PyTypeCache_Lookup(probe->type, probe->name);
    probe->cache_hit = result.cache_hit;
    PyStackRef_XCLOSE(result.value);
    _PyEvent_Notify(&probe->done);
    PyThreadState_Clear(probe->tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
type_cache_reader_waits(PyObject *Py_UNUSED(self), PyObject *args)
{
    PyObject *type_obj, *name;
    if (!PyArg_ParseTuple(args, "OU", &type_obj, &name) ||
        require_type(type_obj) < 0) {
        return NULL;
    }
    name = intern_name(name);
    if (name == NULL) {
        return NULL;
    }
    PyObject *value = _PyType_LookupRef((PyTypeObject *)type_obj, name);
    if (value == NULL) {
        Py_DECREF(name);
        return PyErr_Format(PyExc_AssertionError, "expected a type attribute");
    }
    Py_DECREF(value);
    struct _PyTypeCacheLookupResult initial =
        _PyTypeCache_Lookup((PyTypeObject *)type_obj, name);
    PyStackRef_XCLOSE(initial.value);
    if (!initial.cache_hit) {
        Py_DECREF(name);
        return PyErr_Format(PyExc_AssertionError, "expected a populated cache");
    }

    PyInterpreterState *interp = PyInterpreterState_Get();
    struct cache_reader_probe probe = {
        .tstate = PyThreadState_New(interp),
        .type = (PyTypeObject *)type_obj,
        .name = name,
    };
    if (probe.tstate == NULL) {
        Py_DECREF(name);
        return PyErr_NoMemory();
    }
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(cache_reader_worker, &probe,
                                      &ident, &handle) < 0) {
        PyThreadState_Clear(probe.tstate);
        PyThreadState_Delete(probe.tstate);
        Py_DECREF(name);
        return PyErr_Format(PyExc_RuntimeError, "failed to start cache reader");
    }

    // Keep the mutex held while detached so the worker can attempt a lookup.
    // Observe actual contention, rather than assuming it after a fixed sleep.
    PyMutex *mutex = &interp->types.mutex;
    PyMutex_Lock(mutex);
    int parked = 0;
    Py_BEGIN_ALLOW_THREADS
    for (int i = 0; i < 1000; i++) {
        if (_Py_atomic_load_uint8_relaxed(&mutex->_bits) & _Py_HAS_PARKED) {
            parked = 1;
            break;
        }
        if (PyEvent_WaitTimed(&probe.done, 10 * 1000 * 1000, 0)) {
            break;
        }
    }
    Py_END_ALLOW_THREADS
    _PyTypeCache_Invalidate(probe.type);
    PyMutex_Unlock(mutex);

    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    Py_DECREF(name);
    return Py_BuildValue("(ii)", parked, probe.cache_hit);
}


static PyMethodDef test_methods[] = {
    {"type_cache_lookup", type_cache_lookup, METH_VARARGS},
    {"type_cache_invalidate", type_cache_invalidate, METH_O},
    {"type_cache_reader_waits", type_cache_reader_waits, METH_VARARGS},
    {NULL},
};

int
_PyTestInternalCapi_Init_TypeCache(PyObject *m)
{
    if (PyModule_AddFunctions(m, test_methods) < 0) {
        return -1;
    }
    if (PyModule_AddIntMacro(m, _Py_TYPECACHE_MINSIZE) < 0) {
        return -1;
    }
    return 0;
}
