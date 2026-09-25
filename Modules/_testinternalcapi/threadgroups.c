/* Exercise group scheduling without sharing Python functions or mutable
   Python containers between groups. */
#include "parts.h"
#include "pycore_ceval.h"
#include "pycore_code.h"
#include "pycore_dict.h"
#include "pycore_freelist.h"
#include "pycore_function.h"
#include "pycore_lock.h"
#include "pycore_object.h"
#include "pycore_object_deferred.h"
#include "pycore_pystate.h"
#include "pycore_pymem.h"
#include "pycore_pythread.h"
#include "pycore_qsbr.h"
#include "pycore_stackref.h"
#include "pycore_threadgroup.h"
#include "pycore_unicodeobject.h"

struct parallel_gc_counts {
    int refs;
    int created;
    int freed;
    int freed_while_stopped;
    int local_freed_elsewhere;
};

static void
parallel_gc_counts_release(struct parallel_gc_counts *counts)
{
    if (_Py_atomic_add_int(&counts->refs, -1) == 1) {
        PyMem_RawFree(counts);
    }
}

typedef struct {
    PyObject_HEAD
    PyObject *cycle;
    struct parallel_gc_counts *counts;
} parallel_gc_object;

static int
parallel_gc_traverse(PyObject *op, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(((parallel_gc_object *)op)->cycle);
    return 0;
}

static int
parallel_gc_clear(PyObject *op)
{
    Py_CLEAR(((parallel_gc_object *)op)->cycle);
    return 0;
}

static void
parallel_gc_dealloc(PyObject *op)
{
    PyObject_GC_UnTrack(op);
    parallel_gc_clear(op);
    struct parallel_gc_counts *counts = ((parallel_gc_object *)op)->counts;
    if (counts != NULL) {
        PyThreadState *tstate = _PyThreadState_GET();
        if (tstate->interp->stoptheworld.world_stopped) {
            _Py_atomic_add_int(&counts->freed_while_stopped, 1);
        }
        if (op->ob_shareable == _Py_SHAREABLE_LOCAL &&
            op->ob_owner_id != tstate->threadgroup->id) {
            _Py_atomic_add_int(&counts->local_freed_elsewhere, 1);
        }
        _Py_atomic_add_int(&counts->freed, 1);
        parallel_gc_counts_release(counts);
    }
    PyTypeObject *type = Py_TYPE(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static PyObject *
parallel_gc_type(void)
{
    PyType_Slot slots[] = {
        {Py_tp_traverse, parallel_gc_traverse},
        {Py_tp_clear, parallel_gc_clear},
        {Py_tp_dealloc, parallel_gc_dealloc},
        {0, NULL},
    };
    PyType_Spec spec = {
        .name = "_testinternalcapi.ParallelGCProbe",
        .basicsize = sizeof(parallel_gc_object),
        .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
        .slots = slots,
    };
    PyObject *type = PyType_FromSpec(&spec);
    if (type != NULL) {
        PyObject_DeclareImmutable(type);
    }
    return type;
}

struct group_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *state;
    PyObject *wrapper;
    PyEvent *events;
    PyEvent *start;
    uint8_t *flags;
    int index;
    int mode;
    PyTime_t timeout;
    int ok;
    PyTypeObject *cycle_type;
    struct parallel_gc_counts *counts;
    struct parallel_intern_probe *intern;
    uint32_t *versions;
    int version_count;
    PyObject *code;
    PyObject *lookup_objects;
    int *lookup_rounds;
    char error[256];
};

#define PARALLEL_CODE_COUNT 16384

static int
noop_code_watcher(PyCodeEvent event, PyCodeObject *code)
{
    return 0;
}

static int
noop_func_watcher(PyFunction_WatchEvent event, PyFunctionObject *func,
                  PyObject *value)
{
    return 0;
}

static int
noop_dict_watcher(PyDict_WatchEvent event, PyObject *dict,
                  PyObject *key, PyObject *value)
{
    return 0;
}

static int
noop_context_watcher(PyContextEvent event, PyObject *context)
{
    return 0;
}

// The clearing probe runs in an isolated process with one Python thread.
static int watcher_to_clear = -1;
static int cleared_watcher_calls;
static int (*clear_watcher)(int);

static int
clear_later_watcher(void)
{
    if (watcher_to_clear >= 0) {
        if (clear_watcher(watcher_to_clear) < 0) {
            return -1;
        }
        watcher_to_clear = -1;
    }
    return 0;
}

static int
clear_later_code_watcher(PyCodeEvent event, PyCodeObject *code)
{
    return clear_later_watcher();
}

static int
clear_later_func_watcher(PyFunction_WatchEvent event, PyFunctionObject *func,
                        PyObject *value)
{
    return clear_later_watcher();
}

static int
clear_later_context_watcher(PyContextEvent event, PyObject *context)
{
    return clear_later_watcher();
}

static int
clear_later_dict_watcher(PyDict_WatchEvent event, PyObject *dict,
                        PyObject *key, PyObject *value)
{
    return clear_later_watcher();
}

static int
cleared_code_watcher(PyCodeEvent event, PyCodeObject *code)
{
    cleared_watcher_calls++;
    return 0;
}

static int
cleared_func_watcher(PyFunction_WatchEvent event, PyFunctionObject *func,
                     PyObject *value)
{
    cleared_watcher_calls++;
    return 0;
}

static int
cleared_context_watcher(PyContextEvent event, PyObject *context)
{
    cleared_watcher_calls++;
    return 0;
}

static int
cleared_dict_watcher(PyDict_WatchEvent event, PyObject *dict,
                     PyObject *key, PyObject *value)
{
    cleared_watcher_calls++;
    return 0;
}

static int
add_clearing_watcher(int kind, int first)
{
    switch (kind) {
        case 0:
            return PyFunction_AddWatcher(first ? clear_later_func_watcher :
                                                 cleared_func_watcher);
        case 1:
            return PyCode_AddWatcher(first ? clear_later_code_watcher :
                                             cleared_code_watcher);
        case 2:
            return PyContext_AddWatcher(first ? clear_later_context_watcher :
                                                cleared_context_watcher);
        case 3:
            return PyDict_AddWatcher(first ? clear_later_dict_watcher :
                                             cleared_dict_watcher);
        default:
            Py_UNREACHABLE();
    }
}

static PyObject *
threadgroup_watcher_clear_probe(PyObject *self, PyObject *arg)
{
    static int (*const clear_functions[])(int) = {
        PyFunction_ClearWatcher, PyCode_ClearWatcher,
        PyContext_ClearWatcher, PyDict_ClearWatcher,
    };
    int kind = PyLong_AsInt(arg);
    if (kind == -1 && PyErr_Occurred()) {
        return NULL;
    }
    if (kind < 0 || kind >= (int)Py_ARRAY_LENGTH(clear_functions)) {
        return PyErr_Format(PyExc_ValueError, "invalid watcher kind");
    }
    clear_watcher = clear_functions[kind];
    PyObject *globals = PyDict_New();
    PyObject *code = (PyObject *)PyCode_NewEmpty("watcher-clear", "probe", 1);
    if (globals == NULL || code == NULL) {
        Py_XDECREF(globals);
        Py_XDECREF(code);
        return NULL;
    }
    int first = add_clearing_watcher(kind, 1);
    if (first < 0) {
        Py_DECREF(globals);
        Py_DECREF(code);
        return NULL;
    }
    cleared_watcher_calls = 0;
    watcher_to_clear = add_clearing_watcher(kind, 0);
    PyObject *watched = NULL;
    if (watcher_to_clear >= 0) {
        switch (kind) {
            case 0:
                watched = PyFunction_New(code, globals);
                break;
            case 1:
                watched = (PyObject *)PyCode_NewEmpty("watcher-clear", "watched", 1);
                break;
            case 2:
                watched = PyContext_New();
                if (watched != NULL && PyContext_Enter(watched) == 0) {
                    PyContext_Exit(watched);
                }
                break;
            case 3:
                watched = PyDict_New();
                if (watched != NULL && PyDict_Watch(first, watched) == 0 &&
                    PyDict_Watch(watcher_to_clear, watched) == 0) {
                    PyDict_SetItemString(watched, "value", Py_None);
                }
                break;
        }
    }
    int ok = watched != NULL && watcher_to_clear == -1 &&
             cleared_watcher_calls == 0;
    clear_watcher(first);
    if (watcher_to_clear >= 0) {
        clear_watcher(watcher_to_clear);
    }
    watcher_to_clear = -1;
    Py_XDECREF(watched);
    Py_DECREF(code);
    Py_DECREF(globals);
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "a cleared watcher received a later notification");
    }
    Py_RETURN_NONE;
}

static int
parallel_context_dict_worker(struct group_probe *probe)
{
    int context = probe->mode == 10;
    PyThreadState *tstate = PyThreadState_Get();
    for (int i = 0; i < 2048; i++) {
        int watcher = context ? PyContext_AddWatcher(noop_context_watcher) :
                                PyDict_AddWatcher(noop_dict_watcher);
        if (watcher < 0) {
            return 0;
        }
        PyObject *watched = context ? PyContext_New() : PyDict_New();
        int ok = watched != NULL;
        if (ok && context) {
            ok = PyContext_Enter(watched) == 0;
            if (ok) {
                ok = PyContext_Exit(watched) == 0;
            }
        }
        else if (ok) {
            ok = PyDict_Watch(watcher, watched) == 0 &&
                 PyDict_SetItemString(watched, "value", Py_None) == 0 &&
                 PyDict_DelItemString(watched, "value") == 0 &&
                 PyDict_Unwatch(watcher, watched) == 0;
        }
        int cleared = context ? PyContext_ClearWatcher(watcher) :
                                PyDict_ClearWatcher(watcher);
        Py_XDECREF(watched);
        if (!ok || cleared < 0 || _Py_HandlePending(tstate) < 0) {
            return 0;
        }
    }
    return 1;
}

static PyObject *
parallel_slot_getattribute(PyObject *self, PyObject *name)
{
    return PyObject_GenericGetAttr(self, name);
}

static PyMethodDef parallel_slot_getattribute_def = {
    "__getattribute__", parallel_slot_getattribute, METH_O, NULL,
};

// The reentrant watcher probe runs in an isolated, single-threaded process.
static PyObject *keys_watcher_target;
static int keys_watcher_entered;
static int keys_watcher_calls;

static int
reentrant_keys_watcher(PyTypeObject *type)
{
    if (keys_watcher_target == NULL || keys_watcher_entered ||
        type != Py_TYPE(keys_watcher_target)) {
        return 0;
    }
    keys_watcher_entered = 1;
    keys_watcher_calls++;
    int res = PyObject_SetAttrString(keys_watcher_target, "inner", Py_None);
    keys_watcher_entered = 0;
    return res;
}

static PyObject *
test_shared_keys_type_watcher(PyObject *self, PyObject *instance)
{
    int watcher = PyType_AddWatcher(reentrant_keys_watcher);
    if (watcher < 0) {
        return NULL;
    }
    keys_watcher_target = instance;
    keys_watcher_calls = 0;
    int watched = PyType_Watch(watcher, (PyObject *)Py_TYPE(instance)) == 0;
    // Populate the type version so insertion invalidates it and notifies.
    PyObject *value = watched ? PyObject_GetAttrString(instance, "value") : NULL;
    int ok = value != NULL &&
             PyObject_SetAttrString(instance, "outer", Py_None) == 0;
    Py_XDECREF(value);
    if (watched) {
        PyType_Unwatch(watcher, (PyObject *)Py_TYPE(instance));
    }
    PyType_ClearWatcher(watcher);
    keys_watcher_target = NULL;
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (!ok || keys_watcher_calls != 1) {
        return PyErr_Format(PyExc_AssertionError,
                            "shared keys insertion did not notify its type watcher");
    }
    Py_RETURN_NONE;
}

static PyObject *
parallel_slot_type(int with_dict)
{
    // A native method descriptor keeps the fixture independent of
    // synchronized Python functions, which belong to a later PEP stage.
    PyObject *method = PyDescr_NewMethod(&PyBaseObject_Type,
                                         &parallel_slot_getattribute_def);
    if (method == NULL) {
        return NULL;
    }
    if (PyObject_DeclareImmutable(method) < 0) {
        Py_DECREF(method);
        return NULL;
    }
    PyObject *namespace = Py_BuildValue("{s:O,s:O,s:s}",
        "__getattribute__", method, "value", Py_None,
        "__module__", "_testinternalcapi");
    Py_DECREF(method);
    if (namespace == NULL) {
        return NULL;
    }
    if (!with_dict) {
        PyObject *slots = PyTuple_New(0);
        int res = slots == NULL ? -1 :
            PyDict_SetItemString(namespace, "__slots__", slots);
        Py_XDECREF(slots);
        if (res < 0) {
            Py_DECREF(namespace);
            return NULL;
        }
    }
    PyObject *type = PyObject_CallFunction((PyObject *)&PyType_Type, "s()O",
                                          "ParallelSlotLookup", namespace);
    Py_DECREF(namespace);
    if (type == NULL) {
        return NULL;
    }
    if (PyType_Freeze((PyTypeObject *)type) < 0) {
        Py_DECREF(type);
        return NULL;
    }
    return type;
}

static PyObject *
parallel_lookup_objects(int mode)
{
    int instances = mode != 7;
    PyType_Slot slots[] = {
        {0, NULL},
    };
    PyType_Spec spec = {
        .name = "_testinternalcapi.ParallelLookup",
        .basicsize = sizeof(PyObject),
        .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE,
        .slots = slots,
    };
    PyObject *types = PyTuple_New(instances ? 128 : 1024);
    if (types == NULL) {
        return NULL;
    }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(types); i++) {
        PyObject *type = instances ? parallel_slot_type(mode == 11) :
                                    PyType_FromSpec(&spec);
        if (mode == 12 && type != NULL) {
            // Share an immutable instance while its class remains LOCAL.
            // Only native method descriptors are reached through that class.
            PyObject *instance = PyObject_CallNoArgs(type);
            Py_DECREF(type);
            type = instance;
        }
        if (type == NULL ||
            (!instances && PyDict_SetItemString(((PyTypeObject *)type)->tp_dict,
                                                "value", Py_None) < 0) ||
            PyObject_DeclareImmutable(type) < 0) {
            Py_XDECREF(type);
            Py_DECREF(types);
            return NULL;
        }
        PyTuple_SET_ITEM(types, i, type);
    }
    return types;
}

static int
parallel_instance_attributes(PyObject *instance, int worker)
{
    PyObject *dict = PyObject_GenericGetDict(instance, NULL);
    if (dict == NULL) {
        return 0;
    }
    int ok = 1;
    // The workers add distinct names to one shared keys table. This covers
    // split dictionaries, their copies, and conversion to combined tables.
    for (int i = 0; i < 40; i++) {
        PyObject *name = PyUnicode_FromFormat("attribute_%d_%d", worker, i);
        PyObject *value = PyLong_FromLong(worker * 40 + i);
        PyObject *found = NULL;
        if (name == NULL || value == NULL ||
            PyObject_SetAttr(instance, name, value) < 0 ||
            (found = PyObject_GetAttr(instance, name)) == NULL ||
            found != value) {
            ok = 0;
        }
        Py_XDECREF(found);
        found = NULL;
        if (ok && (PyDict_GetItemRef(dict, name, &found) != 1 || found != value)) {
            ok = 0;
        }
        Py_XDECREF(found);
        Py_XDECREF(name);
        Py_XDECREF(value);
        if (!ok) {
            break;
        }
        if (i == 4 || i == 39) {
            PyObject *copy = PyDict_Copy(dict);
            PyObject *items = PyDict_Items(dict);
            ok = copy != NULL && items != NULL &&
                 PyDict_Size(copy) == i + 1 && PyList_GET_SIZE(items) == i + 1;
            Py_XDECREF(copy);
            Py_XDECREF(items);
            if (!ok) {
                break;
            }
        }
    }
    if (ok) {
        PyDict_Clear(dict);
        ok = PyObject_SetAttrString(instance, "last", Py_None) == 0 &&
             PyDict_Size(dict) == 1;
    }
    Py_DECREF(dict);
    return ok;
}

static int
parallel_lookup_worker(struct group_probe *probe)
{
    PyThreadState *tstate = PyThreadState_Get();
    PyTime_t now;
    if (PyTime_Monotonic(&now) < 0) {
        return 0;
    }
    PyTime_t deadline = now + probe->timeout;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(probe->lookup_objects); i++) {
        // Bring both readers to each cold type before either fills its cache.
        _Py_atomic_store_int(&probe->lookup_rounds[probe->index], (int)i + 1);
        while (_Py_atomic_load_int(&probe->lookup_rounds[1 - probe->index]) <= i) {
            if (_Py_HandlePending(tstate) < 0 ||
                PyTime_Monotonic(&now) < 0 || now >= deadline) {
                return 0;
            }
        }
        PyObject *item = PyTuple_GET_ITEM(probe->lookup_objects, i);
        PyObject *target = probe->mode == 11 ? PyObject_CallNoArgs(item) :
                                              Py_NewRef(item);
        if (target == NULL) {
            return 0;
        }
        for (int repeat = 0; repeat < 8; repeat++) {
            PyObject *value = PyObject_GetAttr(target, &_Py_ID(value));
            if (value == NULL) {
                Py_DECREF(target);
                return 0;
            }
            int ok = value == Py_None;
            Py_DECREF(value);
            if (!ok) {
                Py_DECREF(target);
                return 0;
            }
        }
        int ok = probe->mode != 11 ||
                 parallel_instance_attributes(target, probe->index);
        Py_DECREF(target);
        if (!ok) {
            return 0;
        }
    }
    return 1;
}

static PyObject *
parallel_vm_collect(PyObject *self, PyObject *unused)
{
    return PyLong_FromSsize_t(PyGC_Collect());
}

static PyMethodDef parallel_vm_collect_def = {
    "gc_collect", parallel_vm_collect, METH_NOARGS, NULL,
};

static PyObject *
parallel_vm_record_keys(PyObject *self, PyObject *mapping)
{
    struct group_probe *probe = PyCapsule_GetPointer(self, "parallel VM probe");
    if (probe == NULL) {
        return NULL;
    }
    if (!PyDict_CheckExact(mapping) || probe->version_count == PARALLEL_CODE_COUNT) {
        return PyErr_Format(PyExc_ValueError, "invalid dictionary version probe");
    }
    uint32_t version = _PyDictKeys_GetVersionForCurrentState(
        _PyInterpreterState_GET(), ((PyDictObject *)mapping)->ma_keys);
    probe->versions[probe->version_count++] = version;
    return PyLong_FromUnsignedLong(version);
}

static PyMethodDef parallel_vm_record_keys_def = {
    "record_keys_version", parallel_vm_record_keys, METH_O, NULL,
};

static int
parallel_vm_worker(struct group_probe *probe)
{
    PyObject *globals = PyDict_New();
    PyObject *builtins = PyDict_New();
    PyObject *collect = PyCFunction_NewEx(&parallel_vm_collect_def, NULL, NULL);
    PyObject *context = PyCapsule_New(probe, "parallel VM probe", NULL);
    PyObject *record = context == NULL ? NULL :
        PyCFunction_NewEx(&parallel_vm_record_keys_def, context, NULL);
    PyObject *func = NULL;
    PyObject *result = NULL;
    struct {
        const char *name;
        PyTypeObject *type;
    } types[] = {
        {"int", &PyLong_Type}, {"float", &PyFloat_Type},
        {"str", &PyUnicode_Type}, {"list", &PyList_Type},
        {"tuple", &PyTuple_Type}, {"dict", &PyDict_Type},
        {"set", &PySet_Type}, {"frozenset", &PyFrozenSet_Type},
        {"range", &PyRange_Type}, {"type", &PyType_Type},
        {"object", &PyBaseObject_Type},
    };
    if (globals == NULL || builtins == NULL || collect == NULL || record == NULL ||
        PyDict_SetItemString(globals, "__builtins__", builtins) < 0 ||
        PyDict_SetItemString(builtins, "gc_collect", collect) < 0 ||
        PyDict_SetItemString(builtins, "record_keys_version", record) < 0 ||
        PyDict_SetItemString(builtins, "AssertionError", PyExc_AssertionError) < 0) {
        goto done;
    }
    for (size_t i = 0; i < Py_ARRAY_LENGTH(types); i++) {
        if (PyDict_SetItemString(builtins, types[i].name,
                                 (PyObject *)types[i].type) < 0) {
            goto done;
        }
    }
    // Only code is shared. Each worker creates its own function, namespace,
    // builtins dictionary and native callable in its current ThreadGroup.
    func = PyFunction_New(probe->code, globals);
    if (func != NULL) {
        result = PyObject_CallNoArgs(func);
    }
done:
    int ok = result == Py_True;
    Py_XDECREF(result);
    Py_XDECREF(func);
    Py_XDECREF(collect);
    Py_XDECREF(record);
    Py_XDECREF(context);
    Py_XDECREF(builtins);
    Py_XDECREF(globals);
    return ok;
}

static int
parallel_code_worker(struct group_probe *probe, PyThreadState *tstate)
{
    PyObject *globals = PyDict_New();
    PyObject *builtins = PyDict_New();
    if (globals == NULL || builtins == NULL ||
        PyDict_SetItemString(globals, "__builtins__", builtins) < 0) {
        Py_XDECREF(globals);
        Py_XDECREF(builtins);
        return 0;
    }
    Py_DECREF(builtins);
    int ok = 1;
    int iterations = probe->mode == 8 ? 2048 : PARALLEL_CODE_COUNT;
    for (int i = 0; i < iterations; i++) {
        int code_watcher = -1;
        int func_watcher = -1;
        if (probe->mode == 8) {
            code_watcher = PyCode_AddWatcher(noop_code_watcher);
            func_watcher = PyFunction_AddWatcher(noop_func_watcher);
        }
        PyCodeObject *code = PyCode_NewEmpty("parallel-code", "probe", 1);
        PyObject *func = NULL;
        if (code == NULL || (probe->mode == 8 &&
                            (code_watcher < 0 || func_watcher < 0))) {
            ok = 0;
            goto iteration_done;
        }
        probe->versions[i] = code->co_version;
        probe->version_count++;
        func = PyFunction_New((PyObject *)code, globals);
        if (func == NULL) {
            ok = 0;
            goto iteration_done;
        }
        _PyFunction_SetVersion((PyFunctionObject *)func, code->co_version);
        if (i % 64 == 0 && PyFunction_SetDefaults(func, Py_None) < 0) {
            ok = 0;
        }
iteration_done:
        Py_XDECREF(func);
        Py_XDECREF(code);
        if (code_watcher >= 0 && PyCode_ClearWatcher(code_watcher) < 0) {
            ok = 0;
        }
        if (func_watcher >= 0 && PyFunction_ClearWatcher(func_watcher) < 0) {
            ok = 0;
        }
        if (i % 256 == 0) {
            PyGC_Collect();
        }
        if (_Py_HandlePending(tstate) < 0) {
            ok = 0;
        }
        if (!ok) {
            break;
        }
    }
    Py_DECREF(globals);
    return ok;
}

static int
compare_versions(const void *a, const void *b)
{
    uint32_t first = *(const uint32_t *)a;
    uint32_t second = *(const uint32_t *)b;
    return (first > second) - (first < second);
}

struct parallel_intern_probe {
    PyObject *value;
    int phase;
    int failed;
    uint64_t serial;
};

static int
parallel_intern_pending(PyThreadState *tstate, struct parallel_intern_probe *probe,
                        PyTime_t deadline)
{
    PyTime_t now;
    if (_Py_HandlePending(tstate) < 0 || PyTime_Monotonic(&now) < 0 ||
        now >= deadline) {
        _Py_atomic_store_int(&probe->failed, 1);
    }
    return !_Py_atomic_load_int(&probe->failed);
}

static int
parallel_intern_worker(struct group_probe *group, PyThreadState *tstate)
{
    struct parallel_intern_probe *probe = group->intern;
    PyTime_t now;
    if (PyTime_Monotonic(&now) < 0) {
        _Py_atomic_store_int(&probe->failed, 1);
        return 0;
    }
    PyTime_t deadline = now + group->timeout;
    for (int round = 0; round < 2000; round++) {
        if (group->index == 0) {
            PyObject *value = PyUnicode_FromFormat(
                "parallel immortal intern %llu:%d",
                (unsigned long long)probe->serial, round);
            if (value == NULL) {
                _Py_atomic_store_int(&probe->failed, 1);
                return 0;
            }
            _PyUnicode_InternMortal(tstate->interp, &value);
            _Py_atomic_store_ptr(&probe->value, value);
            _Py_atomic_store_int(&probe->phase, round * 2 + 1);
            do {
                if (round % 4 == 1) {
                    // Cross the eight-bit limit while promotion can race
                    // with merging the local count into the shared field.
                    for (int i = 0; i < 256; i++) {
                        Py_INCREF(value);
                    }
                    for (int i = 0; i < 256; i++) {
                        Py_DECREF(value);
                    }
                }
                else if (round % 4 == 3) {
                    // tuple repetition adds references in bulk, including
                    // an overflowing local-to-shared merge on alternate rounds.
                    PyObject *single = PyTuple_Pack(1, value);
                    if (single == NULL) {
                        _Py_atomic_store_int(&probe->failed, 1);
                        break;
                    }
                    PyObject *repeated = PySequence_Repeat(
                        single, round & 4 ? 256 : 7);
                    Py_DECREF(single);
                    if (repeated == NULL) {
                        _Py_atomic_store_int(&probe->failed, 1);
                        break;
                    }
                    Py_DECREF(repeated);
                }
                else {
                    for (int i = 0; i < 64; i++) {
                        if (round % 4 == 0) {
                            Py_INCREF(value);
                        }
                        else if (!_Py_TryIncref(value)) {
                            _Py_atomic_store_int(&probe->failed, 1);
                            break;
                        }
                        Py_DECREF(value);
                        // Our strong reference keeps the target alive, as
                        // a container's lock would at an ordinary call site.
                        PyObject *ref = _Py_NewRefWithLock(value);
                        Py_DECREF(ref);
                    }
                }
                if (!parallel_intern_pending(tstate, probe, deadline)) {
                    break;
                }
            } while (_Py_atomic_load_int(&probe->phase) < round * 2 + 2);
            if (!_Py_IsImmortal(value)) {
                _Py_atomic_store_int(&probe->failed, 1);
            }
            // On failure the coordinator retains this reference until both
            // workers have exited; the promoter may still be acquiring it.
            if (!_Py_atomic_load_int(&probe->failed)) {
                Py_DECREF(value);
            }
        }
        else {
            while (_Py_atomic_load_int(&probe->phase) < round * 2 + 1) {
                if (!parallel_intern_pending(tstate, probe, deadline)) {
                    return 0;
                }
            }
            PyObject *value = _Py_atomic_load_ptr(&probe->value);
            // Alternate direct promotion with acquiring the canonical string
            // through an equal copy's lookup in the weak intern table.
            PyObject *interned = round & 1
                ? _PyUnicode_Copy(value) : Py_NewRef(value);
            if (interned == NULL) {
                _Py_atomic_store_int(&probe->failed, 1);
                return 0;
            }
            _PyUnicode_InternImmortal(tstate->interp, &interned);
            if (interned != value || !_Py_IsImmortal(interned)) {
                _Py_atomic_store_int(&probe->failed, 1);
            }
            Py_DECREF(interned);
            _Py_atomic_store_int(&probe->phase, round * 2 + 2);
        }
        if (_Py_atomic_load_int(&probe->failed)) {
            return 0;
        }
    }
    return 1;
}

static void
group_probe_worker(void *arg)
{
    struct group_probe *probe = arg;
    PyEvent_Wait(probe->start);
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->state;
    probe->state = NULL;
    tstate->threadgroup_object = probe->wrapper;
    probe->wrapper = NULL;
    PyEval_AcquireThread(tstate);

    PyObject *wrapper = _PyThreadGroup_GetObject(probe->interp,
                                               tstate->threadgroup->id);
    probe->ok = wrapper != NULL && wrapper == tstate->threadgroup_object &&
                tstate->holds_threadgroup;
    Py_XDECREF(wrapper);
    PyErr_Clear();

    if (probe->ok && (probe->mode == 1 || probe->mode >= 3)) {
        /* Both workers must reach this barrier without releasing execution
           rights. Interleaving bytecode in one group cannot satisfy it. */
        PyTime_t now;
        if (PyTime_Monotonic(&now) < 0) {
            probe->ok = 0;
        }
        else {
            PyTime_t deadline = now + probe->timeout;
            _Py_atomic_store_uint8(&probe->flags[probe->index], 1);
            while (!_Py_atomic_load_uint8(&probe->flags[1 - probe->index])) {
                if (PyTime_Monotonic(&now) < 0 || now >= deadline) {
                    probe->ok = 0;
                    break;
                }
            }
        }
    }
    else if (probe->ok && probe->mode == 2) {
        /* Waiting must detach so another worker in this group can run. */
        _PyEvent_Notify(&probe->events[probe->index]);
        probe->ok = PyEvent_WaitTimed(&probe->events[1 - probe->index],
                                     probe->timeout, 1);
        probe->ok &= tstate->holds_threadgroup;
    }

    if (probe->ok && probe->mode == 4) {
        probe->ok = parallel_intern_worker(probe, tstate);
    }

    if (probe->ok && (probe->mode == 5 || probe->mode == 8)) {
        probe->ok = parallel_code_worker(probe, tstate);
    }

    if (probe->ok && (probe->mode == 9 || probe->mode == 10)) {
        probe->ok = parallel_context_dict_worker(probe);
    }

    if (probe->ok && (probe->mode == 7 || probe->mode >= 11)) {
        probe->ok = parallel_lookup_worker(probe);
    }

    if (probe->ok && probe->mode == 6) {
        probe->ok = parallel_vm_worker(probe);
        PyObject *exc = PyErr_GetRaisedException();
        if (exc != NULL) {
            PyObject *message = PyObject_Str(exc);
            const char *text = message == NULL ? NULL : PyUnicode_AsUTF8(message);
            PyOS_snprintf(probe->error, sizeof(probe->error), "%s: %s",
                          Py_TYPE(exc)->tp_name, text == NULL ? "" : text);
            Py_XDECREF(message);
            Py_DECREF(exc);
        }
    }

    if (probe->ok && probe->mode == 3) {
        for (int i = 0; i < 2000; i++) {
            Py_ssize_t size = 64 + i % 1024;
            PyObject *bytes = PyBytes_FromStringAndSize(NULL, size);
            if (bytes == NULL) {
                probe->ok = 0;
                break;
            }
            memset(PyBytes_AS_STRING(bytes), (unsigned char)i, size);
            parallel_gc_object *cycle = (parallel_gc_object *)
                PyType_GenericAlloc(probe->cycle_type, 0);
            if (cycle == NULL) {
                Py_DECREF(bytes);
                probe->ok = 0;
                break;
            }
            cycle->counts = probe->counts;
            _Py_atomic_add_int(&probe->counts->refs, 1);
            cycle->cycle = Py_NewRef((PyObject *)cycle);
            // This fixture has no mutating API or Python finalizers. GC may
            // clear it in either group without deciding LOCAL finalization.
            PyObject_DeclareImmutable((PyObject *)cycle);
            _Py_atomic_add_int(&probe->counts->created, 1);
            Py_DECREF(cycle);
            if (i % 64 == 0) {
                PyGC_Collect();
            }
            if (_Py_HandlePending(tstate) < 0) {
                probe->ok = 0;
            }
            for (Py_ssize_t j = 0; j < size; j++) {
                probe->ok &= (unsigned char)PyBytes_AS_STRING(bytes)[j] ==
                    (unsigned char)i;
            }
            Py_DECREF(bytes);
            if (!probe->ok) {
                break;
            }
        }
    }

    PyErr_Clear();
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_probe(PyObject *self, PyObject *args)
{
    PyObject *groups;
    int mode;
    double seconds;
    int parallel = 0;
    PyObject *code = NULL;
    if (!PyArg_ParseTuple(args, "O!id|pO!:threadgroup_probe", &PyTuple_Type,
                          &groups, &mode, &seconds, &parallel, &PyCode_Type, &code)) {
        return NULL;
    }
    if (PyTuple_GET_SIZE(groups) != 2 || mode < 0 || mode > 12 ||
        !(seconds > 0.0 && seconds <= 300.0) ||
        ((mode == 6) != (code != NULL)) ||
        (code != NULL && ((PyCodeObject *)code)->co_nfreevars != 0)) {
        PyErr_SetString(PyExc_ValueError, "invalid group probe arguments");
        return NULL;
    }

    PyInterpreterState *interp = PyInterpreterState_Get();
    struct _gil_runtime_state *gil = interp->ceval.gil;
    int saved_gil = _Py_atomic_load_int_relaxed(&gil->enabled);
    PyEvent events[2] = {{0}, {0}};
    PyEvent start = {0};
    uint8_t flags[2] = {0, 0};
    int lookup_rounds[2] = {0, 0};
    struct group_probe probes[2] = {{0}, {0}};
    PyThread_handle_t handles[2];
    int started = 0;
    PyObject *result = NULL;
    PyObject *cycle_type = NULL;
    PyObject *types = NULL;
    struct parallel_gc_counts *counts = NULL;
    uint32_t *versions = NULL;
    static uint64_t intern_serial;
    struct parallel_intern_probe intern = {0};
    if (mode >= 3) {
        const char *allocator = _PyMem_GetCurrentAllocatorName();
        if (!parallel || allocator == NULL ||
            (strcmp(allocator, "mimalloc") != 0 &&
             strcmp(allocator, "mimalloc_debug") != 0 &&
             strcmp(allocator, "malloc") != 0 &&
             strcmp(allocator, "malloc_debug") != 0))
        {
            return PyErr_Format(PyExc_ValueError,
                                "parallel allocation probe requires a thread-safe allocator");
        }
    }
    if (mode == 3) {
        cycle_type = parallel_gc_type();
        if (cycle_type == NULL) {
            return NULL;
        }
        counts = PyMem_RawCalloc(1, sizeof(*counts));
        if (counts == NULL) {
            Py_DECREF(cycle_type);
            return PyErr_NoMemory();
        }
        counts->refs = 1;
        // Discard pre-existing garbage in the caller's owning group.
        PyGC_Collect();
    }
    if (mode == 4) {
        intern.serial = _Py_atomic_add_uint64(&intern_serial, 1);
        PyThreadState *tstate = PyThreadState_Get();
        _Py_set_eval_breaker_bit(tstate, _PY_EVAL_EXPLICIT_MERGE_BIT);
        if (_Py_HandlePending(tstate) < 0) {
            return NULL;
        }
    }
    if (mode == 5 || mode == 6 || mode == 8) {
        versions = PyMem_RawCalloc(2 * PARALLEL_CODE_COUNT, sizeof(*versions));
        if (versions == NULL) {
            return PyErr_NoMemory();
        }
    }
    if (mode == 7 || mode >= 11) {
        types = parallel_lookup_objects(mode);
        if (types == NULL) {
            return NULL;
        }
    }
#ifdef Py_REF_DEBUG
    Py_ssize_t refs_before = mode == 4 ? _Py_GetGlobalRefTotal() : 0;
#endif
    int start_failed = 0;
    int use_parallel = 0;
    for (int i = 0; i < 2; i++) {
        PyObject *wrapper = PyTuple_GetItem(groups, i);
        if (wrapper == NULL) {
            goto done;
        }
        _PyThreadGroupState *state = _PyThreadGroup_GetState(wrapper);
        if (state == NULL) {
            goto done;
        }
        probes[i] = (struct group_probe){
            .interp = interp,
            .state = state,
            .wrapper = Py_NewRef(wrapper),
            .events = events,
            .start = &start,
            .flags = flags,
            .index = i,
            .mode = mode,
            .timeout = (PyTime_t)(seconds * 1000000000.0),
            .cycle_type = (PyTypeObject *)cycle_type,
            .counts = counts,
            .intern = &intern,
            .versions = versions == NULL ? NULL : versions + i * PARALLEL_CODE_COUNT,
            .code = code,
            .lookup_objects = types,
            .lookup_rounds = lookup_rounds,
        };
    }
    if (parallel) {
        // Preparation can run GC callbacks. Check isolation after it, before
        // any worker starts: no unrelated Python execution may enter here.
        PyThreadState *current = PyThreadState_Get();
        HEAD_LOCK(interp->runtime);
        int isolated = interp == interp->runtime->interpreters.head &&
            interp->next == NULL && interp->threads.head == current &&
            current->next == NULL;
        HEAD_UNLOCK(interp->runtime);
        if (!isolated) {
            PyErr_SetString(PyExc_RuntimeError,
                            "parallel probe requires an isolated process");
            goto done;
        }
        use_parallel = 1;
    }
    for (int i = 0; i < 2; i++) {
        PyThread_ident_t ident;
        if (PyThread_start_joinable_thread(group_probe_worker, &probes[i],
                                           &ident, &handles[i]) != 0) {
            start_failed = 1;
            goto done;
        }
        started++;
    }

done:
    /* The workers access stack storage. Join even on partial start failure. */
    Py_BEGIN_ALLOW_THREADS
    // Change the lock's state only when no thread is attached. Workers wait
    // at the start gate until the caller has released its execution rights.
    if (use_parallel) {
        _Py_atomic_store_int_relaxed(&gil->enabled, 0);
    }
    _PyEvent_Notify(&start);
    for (int i = 0; i < started; i++) {
        PyThread_join_thread(handles[i]);
    }
    // Every native worker is gone. Restore serialization before reattaching
    // and returning to Python, including on partial thread-start failure.
    if (use_parallel) {
        _Py_atomic_store_int_relaxed(&gil->enabled, saved_gil);
    }
    Py_END_ALLOW_THREADS
    if (start_failed) {
        PyErr_SetString(PyExc_RuntimeError, "failed to start group probe");
    }
    if (mode == 6 && started == 2 && !PyErr_Occurred()) {
        for (int i = 0; i < 2; i++) {
            if (!probes[i].ok) {
                PyErr_Format(PyExc_AssertionError,
                             "parallel VM worker %d failed: %s", i, probes[i].error);
                break;
            }
        }
    }
    if (mode == 4 && !PyErr_Occurred()) {
        // Worker teardown queues references to the caller-owned wrappers.
        // Drain them at a safepoint before checking the reference total.
        PyThreadState *tstate = PyThreadState_Get();
        _Py_set_eval_breaker_bit(tstate, _PY_EVAL_EXPLICIT_MERGE_BIT);
        int pending = _Py_HandlePending(tstate);
#ifdef Py_REF_DEBUG
        Py_ssize_t delta = _Py_GetGlobalRefTotal() - refs_before;
        if (pending == 0 && probes[0].ok && probes[1].ok && delta != 0) {
            PyErr_Format(PyExc_AssertionError,
                         "parallel immortalization changed total references by %zd",
                         delta);
        }
#else
        (void)pending;
#endif
    }
    if (mode == 4 && intern.failed) {
        Py_XDECREF(intern.value);
    }
    if (versions != NULL && probes[0].ok && probes[1].ok && !PyErr_Occurred()) {
        int count = probes[0].version_count + probes[1].version_count;
        memmove(versions + probes[0].version_count,
                versions + PARALLEL_CODE_COUNT,
                probes[1].version_count * sizeof(*versions));
        qsort(versions, count, sizeof(*versions), compare_versions);
        for (int i = 1; i < count; i++) {
            if (versions[i] == versions[i - 1]) {
                PyErr_Format(PyExc_AssertionError,
                             "parallel %s creation reused version %u",
                             mode == 6 ? "dictionary" : "code", versions[i]);
                break;
            }
        }
    }
    PyMem_RawFree(versions);
    Py_XDECREF(types);
    if (cycle_type != NULL) {
        PyGC_Collect();
        if (counts->created != counts->freed && !PyErr_Occurred()) {
            PyErr_Format(PyExc_AssertionError,
                         "parallel GC freed %d of %d cycles",
                         counts->freed, counts->created);
        }
        // Even a failing probe may leave cycles for a later collection.
        parallel_gc_counts_release(counts);
        Py_DECREF(cycle_type);
    }
    if (!PyErr_Occurred()) {
        result = Py_BuildValue("(OO)", probes[0].ok ? Py_True : Py_False,
                              probes[1].ok ? Py_True : Py_False);
    }
    for (int i = 0; i < 2; i++) {
        if (probes[i].state != NULL) {
            _PyThreadGroup_Decref(probes[i].state);
        }
        Py_XDECREF(probes[i].wrapper);
    }
    return result;
}

/* Keep the creating OS thread alive while another thread in its group changes
   the local count, then repeat after the creating thread has exited. */
struct refcount_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyEvent created;
    PyEvent checked;
    PyObject *object;
    int phase;
    int ok;
};

static void
refcount_probe_worker(void *arg)
{
    struct refcount_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->created);
        _PyEvent_Notify(&probe->checked);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    PyEval_AcquireThread(tstate);
    if (probe->phase == 0) {
        probe->object = PyBytes_FromString("group-biased reference count");
        _PyEvent_Notify(&probe->created);
        PyEvent_WaitTimed(&probe->checked, 10000000000LL, 1);
    }
    else {
        PyObject *op = probe->object;
        if (op != NULL) {
            uint32_t owner = op->ob_owner_id;
            Py_INCREF(op);
            if (probe->phase == 3) {
                probe->ok = op->ob_ref_local == 1 &&
                    op->ob_ref_shared == _Py_REF_SHARED(1, 0) &&
                    owner != probe->group->id;
            }
            else {
                probe->ok = op->ob_ref_local == 2 &&
                    op->ob_ref_shared == 0 && owner == probe->group->id;
            }
            Py_DECREF(op);
            probe->ok &= Py_REFCNT(op) == 1 && op->ob_owner_id == owner;
        }
        _PyEvent_Notify(&probe->checked);
    }
    PyErr_Clear();
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static int
start_refcount_probe(struct refcount_probe *probe, PyThread_handle_t *handle)
{
    PyThread_ident_t ident;
    if (PyThread_start_joinable_thread(refcount_probe_worker, probe,
                                       &ident, handle) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "failed to start refcount probe");
        return -1;
    }
    return 0;
}

static void
join_refcount_probe(PyThread_handle_t handle)
{
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
}

static PyObject *
threadgroup_refcount_probe(PyObject *self, PyObject *args)
{
    PyObject *owner, *foreign;
    if (!PyArg_ParseTuple(args, "OO:threadgroup_refcount_probe", &owner, &foreign)) {
        return NULL;
    }
    _PyThreadGroupState *groups[2];
    groups[0] = _PyThreadGroup_GetState(owner);
    if (groups[0] == NULL) {
        return NULL;
    }
    groups[1] = _PyThreadGroup_GetState(foreign);
    if (groups[1] == NULL) {
        _PyThreadGroup_Decref(groups[0]);
        return NULL;
    }
    struct refcount_probe create = {
        .interp = PyInterpreterState_Get(), .group = groups[0],
    };
    PyThread_handle_t creator;
    PyObject *result = NULL;
    if (start_refcount_probe(&create, &creator) < 0) {
        goto done;
    }
    if (!PyEvent_WaitTimed(&create.created, 10000000000LL, 1)) {
        PyErr_SetString(PyExc_RuntimeError, "refcount probe timed out");
        _PyEvent_Notify(&create.checked);
        join_refcount_probe(creator);
        goto done;
    }
    int ok = create.object != NULL;
    for (int phase = 1; phase <= 3; phase++) {
        struct refcount_probe check = {
            .interp = create.interp,
            .group = groups[phase == 3],
            .object = create.object,
            .phase = phase,
        };
        PyThread_handle_t worker;
        int started = start_refcount_probe(&check, &worker) == 0;
        if (started) {
            join_refcount_probe(worker);
        }
        if (phase == 1) {
            _PyEvent_Notify(&create.checked);
            join_refcount_probe(creator);
        }
        if (!started) {
            goto done;
        }
        ok &= check.ok;
    }
    result = PyBool_FromLong(ok);
done:
    Py_XDECREF(create.object);
    _PyThreadGroup_Decref(groups[0]);
    _PyThreadGroup_Decref(groups[1]);
    return result;
}

static PyObject *
test_threadgroup_refcount_overflow(PyObject *self, PyObject *unused)
{
    /* A local count overflow must preserve both lifetime and ownership. */
    PyObject *op = PyList_New(0);
    if (op == NULL) {
        return NULL;
    }
    uint32_t owner = op->ob_owner_id;
    assert(sizeof(PyObject) == 8 + 2 * sizeof(void *));
    assert(owner == _Py_GetThreadGroupId());
    for (int i = 1; i < 1024; i++) {
        Py_INCREF(op);
        assert(Py_REFCNT(op) == i + 1);
        assert(!_Py_IsImmortal(op));
        assert(op->ob_owner_id == owner);
    }
    for (int i = 1024; i > 1; i--) {
        Py_DECREF(op);
        assert(Py_REFCNT(op) == i - 1);
    }
    Py_DECREF(op);

    Py_RETURN_NONE;
}

struct deferred_shutdown_probe {
    PyObject *container;
    int child_destroyed;
};

static PyObject *
unicode_intern_dead_entry(PyObject *self, PyObject *unused)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    PyObject *original = PyUnicode_FromString("intern entry awaiting deallocation");
    if (original == NULL) {
        return NULL;
    }
    _PyUnicode_InternMortal(interp, &original);
    PyObject *copy = _PyUnicode_Copy(original);
    if (copy == NULL) {
        Py_DECREF(original);
        return NULL;
    }
    assert(Py_REFCNT(original) == 1);
    // Reproduce the interval between the last decref and unicode_dealloc
    // acquiring the intern-table mutex. The table must not resurrect it.
    Py_SET_REFCNT(original, 0);
#ifdef Py_REF_DEBUG
    _Py_DecRefTotal(_PyThreadState_GET());
#endif
    _PyUnicode_InternMortal(interp, &copy);
    if (copy == original) {
        Py_DECREF(copy);
        return PyErr_Format(PyExc_AssertionError,
                            "interning resurrected a zero-reference string");
    }
    _Py_Dealloc(original);
    // The old deallocator must not remove the replacement's equal key.
    PyObject *again = _PyUnicode_Copy(copy);
    if (again == NULL) {
        Py_DECREF(copy);
        return NULL;
    }
    _PyUnicode_InternMortal(interp, &again);
    int same = again == copy;
    Py_DECREF(again);
    Py_DECREF(copy);
    if (!same) {
        return PyErr_Format(PyExc_AssertionError,
                            "deallocation removed the replacement intern entry");
    }
    Py_RETURN_NONE;
}

static PyObject *
threadgroup_immortal_brc(PyObject *self, PyObject *arg)
{
    int queued = PyLong_AsInt(arg);
    if (queued == -1 && PyErr_Occurred()) {
        return NULL;
    }
#ifdef Py_REF_DEBUG
    Py_ssize_t refs_before = _Py_GetGlobalRefTotal();
#endif
    static uint64_t serial;
    unsigned long long id = _Py_atomic_add_uint64(&serial, 1);
    PyObject *value = PyUnicode_FromFormat("pending intern merge %llu", id);
    if (value == NULL) {
        return NULL;
    }
    PyThreadState *tstate = _PyThreadState_GET();
    _PyUnicode_InternMortal(tstate->interp, &value);
    uint32_t owner = value->ob_owner_id;
    if (queued) {
        // Stage a queue-owned reference before promotion. A raw allocation
        // has the same lifetime/allocator as an ordinary object-stack chunk.
        _PyObjectStackChunk *chunk = PyMem_RawMalloc(sizeof(*chunk));
        if (chunk == NULL) {
            Py_DECREF(value);
            return PyErr_NoMemory();
        }
        chunk->n = 1;
        chunk->objs[0] = Py_NewRef(value);
        _PyThreadGroupState *group = tstate->threadgroup;
        PyMutex_LockFlags(&group->brc_mutex, _Py_LOCK_DONT_DETACH);
        chunk->prev = group->objects_to_merge.head;
        group->objects_to_merge.head = chunk;
        assert(value->ob_ref_shared == _Py_REF_MAYBE_WEAKREF);
        _Py_atomic_store_ssize_relaxed(&value->ob_ref_shared, _Py_REF_QUEUED);
        PyMutex_Unlock(&group->brc_mutex);
    }
    _PyUnicode_InternImmortal(tstate->interp, &value);
    if (queued) {
        _Py_set_eval_breaker_bit(tstate, _PY_EVAL_EXPLICIT_MERGE_BIT);
        if (_Py_HandlePending(tstate) < 0) {
            Py_DECREF(value);
            return NULL;
        }
    }
    else {
        // Reproduce a foreign decref that observed the mortal local count,
        // then entered its slow path after the owner immortalized the string.
#ifdef Py_REF_DEBUG
        _Py_DecRefTotal(tstate);
#endif
        _Py_DecRefShared(value);
    }
    // Other late slow paths must leave the closed counters unchanged, even
    // when their caller observed a mortal count before promotion.
    int ok = !_Py_IncRefShared(value, 1) &&
        _Py_TryIncRefShared(value) && !_Py_IncRefLocalOverflow(value) &&
        _Py_ExplicitMergeRefcount(value, 3) == _Py_IMMORTAL_INITIAL_REFCNT &&
        _Py_IsImmortal(value) && value->ob_owner_id == owner &&
        value->ob_ref_shared == _Py_REF_SHARED_IMMORTAL;
#ifdef Py_REF_DEBUG
    ok &= _Py_GetGlobalRefTotal() == refs_before;
#endif
    Py_DECREF(value);
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "BRC changed an immortal string's lifetime or owner");
    }
    Py_RETURN_NONE;
}

static PyObject *
threadgroup_gc_brc_probe(PyObject *self, PyObject *args)
{
    PyObject *wrapper;
    int keep_owner;
    int retry = 0;
    if (!PyArg_ParseTuple(args, "Op|p:threadgroup_gc_brc_probe",
                          &wrapper, &keep_owner, &retry)) {
        return NULL;
    }
    _PyThreadGroupState *group = _PyThreadGroup_GetState(wrapper);
    if (group == NULL) {
        return NULL;
    }
    PyThreadState *current = PyThreadState_Get();
    PyThreadState *owner = PyThreadState_New(current->interp);
    PyObject *type = parallel_gc_type();
    struct parallel_gc_counts *counts = PyMem_RawCalloc(1, sizeof(*counts));
    _PyObjectStackChunk *chunk = PyMem_RawCalloc(1, sizeof(*chunk));
    if (owner == NULL || type == NULL || counts == NULL || chunk == NULL) {
        if (owner != NULL) {
            PyThreadState_Clear(owner);
            PyThreadState_Delete(owner);
        }
        Py_XDECREF(type);
        PyMem_RawFree(counts);
        PyMem_RawFree(chunk);
        _PyThreadGroup_Decref(group);
        return PyErr_NoMemory();
    }
    counts->refs = 1;
    _PyThreadGroup_Decref(owner->threadgroup);
    _PyThreadGroup_Incref(group);
    owner->threadgroup = group;
    owner->threadgroup_object = Py_NewRef(wrapper);
    PyThreadState_Swap(owner);
    PyObject *external = NULL;
    int ok = 1;
    for (int i = 0; i < 4 + keep_owner; i++) {
        PyObject *op = ((PyTypeObject *)type)->tp_alloc((PyTypeObject *)type, 0);
        if (op == NULL) {
            ok = 0;
            break;
        }
        parallel_gc_object *obj = (parallel_gc_object *)op;
        obj->counts = counts;
        counts->refs++;
        counts->created++;
        if (i != 4) {
            PyObject_DeclareImmutable(op);
        }
        if (i == 1) {
            obj->cycle = Py_NewRef(op);
        }
        else if (i == 2) {
            PyObject_GC_UnTrack(op);
        }
        else if (i == 3) {
            external = Py_NewRef(op);
        }
        // Stage the reference stolen by a foreign decref's BRC queue.
        // Keep the owner's local count intact until the collector merges it.
        assert(op->ob_ref_shared == 0);
        _Py_atomic_store_ssize_relaxed(&op->ob_ref_shared, _Py_REF_QUEUED);
        chunk->objs[chunk->n++] = op;
    }
    // An entry immortalized after enqueueing must also be discarded.
    chunk->objs[chunk->n++] = Py_NewRef(Py_None);
    PyErr_Clear();
    PyThreadState_Swap(current);
    PyMutex_LockFlags(&group->brc_mutex, _Py_LOCK_DONT_DETACH);
    chunk->prev = group->objects_to_merge.head;
    group->objects_to_merge.head = chunk;
    PyMutex_Unlock(&group->brc_mutex);
    if (!keep_owner) {
        PyThreadState_Clear(owner);
        PyThreadState_Delete(owner);
        owner = NULL;
    }

    PyGC_Collect();
    if (retry) {
        // A failed queue transfer must preserve references for the next GC.
        PyGC_Collect();
    }
    int foreign_local = keep_owner && group != current->threadgroup;
    PyMutex_LockFlags(&group->brc_mutex, _Py_LOCK_DONT_DETACH);
    Py_ssize_t pending = _PyObjectStack_Size(&group->objects_to_merge);
    PyMutex_Unlock(&group->brc_mutex);
    ok &= pending == foreign_local &&
        counts->freed == 3 + (keep_owner && !foreign_local) &&
        external != NULL && Py_REFCNT(external) == 1 &&
        external->ob_owner_id == group->id;
    Py_XDECREF(external);
    if (owner != NULL) {
        // Foreign LOCAL references must wait for their own group's safepoint.
        PyThreadState_Swap(owner);
        _Py_set_eval_breaker_bit(owner, _PY_EVAL_EXPLICIT_MERGE_BIT);
        ok &= _Py_HandlePending(owner) == 0;
        PyErr_Clear();
        PyThreadState_Swap(current);
        PyThreadState_Clear(owner);
        PyThreadState_Delete(owner);
    }
    PyGC_Collect();
    ok &= counts->freed == counts->created &&
        counts->freed_while_stopped == 0 && counts->local_freed_elsewhere == 0;
    parallel_gc_counts_release(counts);
    Py_DECREF(type);
    _PyThreadGroup_Decref(group);
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "GC did not drain eligible group BRC references");
    }
    Py_RETURN_NONE;
}

static void
deferred_shutdown_child(PyObject *capsule)
{
    struct deferred_shutdown_probe *probe = PyCapsule_GetPointer(
        capsule, "deferred shutdown child");
    assert(probe != NULL);
    probe->child_destroyed = 1;
}

static void
deferred_shutdown_parent(PyObject *capsule)
{
    struct deferred_shutdown_probe *probe = PyCapsule_GetPointer(
        capsule, "deferred shutdown parent");
    assert(probe != NULL);
    // interp->dict is cleared after the shutdown collections in
    // finalize_modules(). Its remaining objects must reclaim normally.
    assert(!_PyObject_HasDeferredRefcount(probe->container));
    Py_CLEAR(probe->container);
    assert(probe->child_destroyed);
    PyMem_RawFree(probe);
}

static PyObject *
check_deferred_shutdown(PyObject *self, PyObject *unused)
{
    struct deferred_shutdown_probe *probe = PyMem_RawCalloc(1, sizeof(*probe));
    if (probe == NULL) {
        return PyErr_NoMemory();
    }
    PyObject *child = PyCapsule_New(probe, "deferred shutdown child",
                                    deferred_shutdown_child);
    if (child == NULL) {
        PyMem_RawFree(probe);
        return NULL;
    }
    probe->container = PyTuple_New(1);
    if (probe->container == NULL) {
        Py_DECREF(child);
        PyMem_RawFree(probe);
        return NULL;
    }
    PyTuple_SET_ITEM(probe->container, 0, child);
    PyObject *parent = PyCapsule_New(probe, "deferred shutdown parent",
                                     deferred_shutdown_parent);
    if (parent == NULL) {
        Py_DECREF(probe->container);
        PyMem_RawFree(probe);
        return NULL;
    }
    PyObject *dict = PyInterpreterState_GetDict(PyInterpreterState_Get());
    if (dict == NULL ||
        PyDict_SetItemString(dict, "deferred_shutdown_probe", parent) < 0) {
        Py_DECREF(parent);
        return NULL;
    }
    // No allocation follows enabling deferral, so tuple untracking cannot
    // run before the flag is set. The test invokes this once per interpreter.
    assert(PyUnstable_Object_EnableDeferredRefcount(probe->container) == 1);
    Py_DECREF(parent);
    Py_RETURN_NONE;
}

static PyObject *
test_deferred_c_stack_ref(PyObject *self, PyObject *unused)
{
    struct deferred_shutdown_probe probe = {0};
    PyObject *child = PyCapsule_New(&probe, "deferred shutdown child",
                                    deferred_shutdown_child);
    if (child == NULL) {
        return NULL;
    }
    PyObject *container = PyTuple_New(1);
    if (container == NULL) {
        Py_DECREF(child);
        return NULL;
    }
    PyTuple_SET_ITEM(container, 0, child);
    assert(PyUnstable_Object_EnableDeferredRefcount(container) == 1);

    PyThreadState *tstate = PyThreadState_Get();
    _PyCStackRef ref;
    _PyThreadState_PushCStackRefNew(tstate, &ref, container);
    assert(!PyStackRef_RefcountOnObject(ref.ref));
    Py_DECREF(container);
    PyGC_Collect();
    assert(!probe.child_destroyed);
    assert(PyTuple_GetItem(PyStackRef_AsPyObjectBorrow(ref.ref), 0) == child);
    _PyThreadState_PopCStackRef(tstate, &ref);
    PyGC_Collect();
    assert(probe.child_destroyed);
    Py_RETURN_NONE;
}

static void
check_main_group_at_shutdown(PyObject *capsule)
{
    PyInterpreterState *interp = PyCapsule_GetPointer(capsule, "main group lifetime");
    assert(interp != NULL && interp == PyInterpreterState_Get());
    assert(interp->main_threadgroup_object != NULL);
    PyObject *main = _PyThreadGroup_GetObject(interp, interp->main_threadgroup->id);
    assert(main == interp->main_threadgroup_object);
    PyObject *name = PyObject_GetAttrString(main, "name");
    assert(name != NULL && PyUnicode_CompareWithASCIIString(name, "Main") == 0);
    Py_DECREF(name);
    Py_DECREF(main);
}

static PyObject *
check_main_group_lifetime(PyObject *self, PyObject *unused)
{
    PyInterpreterState *interp = PyInterpreterState_Get();
    // Retain no Python reference to Main: only the interpreter's own lifetime
    // guarantee can keep it available after modules and thread states clear.
    PyObject *capsule = PyCapsule_New(interp, "main group lifetime",
                                    check_main_group_at_shutdown);
    if (capsule == NULL) {
        return NULL;
    }
    PyObject *dict = PyInterpreterState_GetDict(interp);
    int result = dict == NULL ? -1 :
        PyDict_SetItemString(dict, "main_group_lifetime", capsule);
    Py_DECREF(capsule);
    if (result < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

struct access_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyObject *value;  // A heap reference, checked before the worker uses it.
    int accessible;
    int ok;
};

static void
access_probe_worker(void *arg)
{
    struct access_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    PyEval_AcquireThread(tstate);

    PyObject *value = probe->value;
    uint32_t owner = value->ob_owner_id;
    Py_ssize_t count = Py_REFCNT(value);
    probe->accessible = PyObject_IsAccessible(value);
    int ok = !PyErr_Occurred();
    PyObject *checked = PyObject_CheckAccess(value);
    if (probe->accessible) {
        ok &= checked == value && !PyErr_Occurred();
    }
    else {
        ok &= checked == NULL &&
            PyErr_ExceptionMatches(PyExc_IllegalThreadAccessException);
    }
    PyErr_Clear();
    // Copy the heap reference without accessing its contents, then validate
    // the new reference using the helper intended for API return values.
    checked = _PyObject_CheckAccessNullable(Py_NewRef(value));
    if (probe->accessible) {
        ok &= checked == value && !PyErr_Occurred();
        Py_XDECREF(checked);
    }
    else {
        ok &= checked == NULL &&
            PyErr_ExceptionMatches(PyExc_IllegalThreadAccessException);
    }
    PyErr_Clear();
    ok &= value->ob_owner_id == owner && Py_REFCNT(value) == count;

    PyErr_SetString(PyExc_ValueError, "existing exception");
    ok &= PyObject_IsAccessible(value) == probe->accessible;
    ok &= _PyObject_CheckAccessNullable(NULL) == NULL;
    ok &= PyErr_ExceptionMatches(PyExc_ValueError);
    PyErr_Clear();
    probe->ok = ok;
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_access_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *value;
    if (!PyArg_ParseTuple(args, "OO:threadgroup_access_probe", &group, &value)) {
        return NULL;
    }
    // The caller obtained this ordinary argument in its own group.
    assert(PyObject_IsAccessible(value));
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    struct access_probe probe = {
        .interp = PyInterpreterState_Get(),
        .group = state,
        .value = value,
    };
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(access_probe_worker, &probe,
                                      &ident, &handle) != 0) {
        _PyThreadGroup_Decref(state);
        return PyErr_Format(PyExc_RuntimeError, "failed to start access probe");
    }
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    _PyThreadGroup_Decref(state);
    if (!probe.ok) {
        return PyErr_Format(PyExc_AssertionError, "reference access probe failed");
    }
    return PyBool_FromLong(probe.accessible);
}

static PyObject *
make_immutable_capsule(PyObject *self, PyObject *unused)
{
    static const char data[] = "immutable native data";
    PyObject *capsule = PyCapsule_New((void *)data, "PEP 805 immutable data", NULL);
    if (capsule == NULL) {
        return NULL;
    }
    uint32_t owner = capsule->ob_owner_id;
    assert(capsule->ob_shareable == _Py_SHAREABLE_LOCAL);
    assert(PyObject_DeclareImmutable(capsule) == 0);
    assert(PyObject_DeclareImmutable(capsule) == 0);
    assert(capsule->ob_shareable == _Py_SHAREABLE_IMMUTABLE);
    assert(capsule->ob_owner_id == owner);
    return capsule;
}

static PyObject *
test_static_immutable_access(PyObject *self, PyObject *unused)
{
    PyObject *code = (PyObject *)&_Py_InitCleanup;
    assert(PyObject_IsAccessible(code));
    assert(PyObject_CheckAccess(code) == code);
    assert(PyObject_DeclareImmutable(code) == 0);
    assert(!PyObject_IS_GC(code));
    Py_RETURN_NONE;
}

struct unicode_intern_probe {
    struct access_probe base;
    PyObject *result;
    int immortal;
};

static void
unicode_intern_worker(void *arg)
{
    struct unicode_intern_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->base.interp);
    if (tstate == NULL) {
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->base.group;
    _PyThreadGroup_Incref(tstate->threadgroup);
    PyEval_AcquireThread(tstate);
    if (PyObject_CheckAccess(probe->base.value) != NULL) {
        PyObject *value = Py_NewRef(probe->base.value);
        if (probe->immortal) {
            _PyUnicode_InternImmortal(tstate->interp, &value);
        }
        else {
            _PyUnicode_InternMortal(tstate->interp, &value);
        }
        probe->base.ok = PyUnicode_CHECK_INTERNED(value) != SSTATE_NOT_INTERNED &&
            !PyErr_Occurred();
        probe->result = value;
    }
    PyErr_Clear();
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_intern(PyObject *self, PyObject *args)
{
    PyObject *group, *value;
    int immortal;
    if (!PyArg_ParseTuple(args, "OO!p:threadgroup_intern", &group,
                          &PyUnicode_Type, &value, &immortal)) {
        return NULL;
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    struct unicode_intern_probe probe = {
        .base = {.interp = PyInterpreterState_Get(), .group = state,
                 .value = value},
        .immortal = immortal,
    };
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    int started = PyThread_start_joinable_thread(
        unicode_intern_worker, &probe, &ident, &handle);
    if (started == 0) {
        Py_BEGIN_ALLOW_THREADS
        PyThread_join_thread(handle);
        Py_END_ALLOW_THREADS
    }
    _PyThreadGroup_Decref(state);
    if (!probe.base.ok) {
        Py_XDECREF(probe.result);
        return PyErr_Format(PyExc_AssertionError, "Unicode interning probe failed");
    }
    return _PyObject_CheckAccessNullable(probe.result);
}

struct unicode_cache_probe {
    struct access_probe base;
    PyMemAllocatorEx original;
    PyThreadState *worker;
    PyEvent allocated;
    PyEvent resume;
    size_t cache_size;
    void *candidate;
    const char *worker_cache;
    Py_ssize_t worker_size;
    Py_hash_t worker_hash;
    int armed;
    int discarded;
    int timed_out;
};

static void *
unicode_cache_malloc(void *ctx, size_t size)
{
    struct unicode_cache_probe *probe = ctx;
    void *ptr = probe->original.malloc(probe->original.ctx, size);
    if (ptr != NULL && size == probe->cache_size &&
        _Py_atomic_load_int(&probe->armed) &&
        _PyThreadState_GET() == probe->worker &&
        _Py_atomic_exchange_int(&probe->armed, 0)) {
        _Py_atomic_store_ptr(&probe->candidate, ptr);
        _PyEvent_Notify(&probe->allocated);
        // Let the caller publish a cache while this allocation is in flight.
        probe->timed_out = !PyEvent_WaitTimed(&probe->resume, 10000000000LL, 1);
    }
    return ptr;
}

static void *
unicode_cache_calloc(void *ctx, size_t nelem, size_t size)
{
    struct unicode_cache_probe *probe = ctx;
    return probe->original.calloc(probe->original.ctx, nelem, size);
}

static void *
unicode_cache_realloc(void *ctx, void *ptr, size_t size)
{
    struct unicode_cache_probe *probe = ctx;
    return probe->original.realloc(probe->original.ctx, ptr, size);
}

static void
unicode_cache_free(void *ctx, void *ptr)
{
    struct unicode_cache_probe *probe = ctx;
    if (ptr != NULL && ptr == _Py_atomic_load_ptr(&probe->candidate)) {
        _Py_atomic_store_ptr(&probe->candidate, NULL);
        _Py_atomic_store_int(&probe->discarded, 1);
    }
    probe->original.free(probe->original.ctx, ptr);
}

static void
unicode_cache_worker(void *arg)
{
    struct unicode_cache_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->base.interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->allocated);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->base.group;
    _PyThreadGroup_Incref(tstate->threadgroup);
    PyEval_AcquireThread(tstate);
    probe->worker = tstate;
    if (PyObject_CheckAccess(probe->base.value) != NULL) {
        probe->worker_hash = PyObject_Hash(probe->base.value);
        if (probe->worker_hash != -1) {
            _Py_atomic_store_int(&probe->armed, 1);
            probe->worker_cache = PyUnicode_AsUTF8AndSize(
                probe->base.value, &probe->worker_size);
            probe->base.ok = probe->worker_cache != NULL && !PyErr_Occurred();
        }
    }
    PyErr_Clear();
    _PyEvent_Notify(&probe->allocated);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_unicode_cache_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *value, *expected;
    if (!PyArg_ParseTuple(args, "OO!O!:threadgroup_unicode_cache_probe",
                          &group, &PyUnicode_Type, &value, &PyBytes_Type,
                          &expected)) {
        return NULL;
    }
    if (PyUnicode_IS_ASCII(value) || PyUnicode_GET_LENGTH(value) < 2) {
        return PyErr_Format(PyExc_ValueError, "non-ASCII string required");
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    // A fresh exact str has neither a UTF-8 cache nor a cached hash.
    PyObject *fresh = _PyUnicode_Copy(value);
    if (fresh == NULL) {
        _PyThreadGroup_Decref(state);
        return NULL;
    }
    struct unicode_cache_probe probe = {
        .base = {.interp = PyInterpreterState_Get(), .group = state,
                 .value = fresh},
        .cache_size = (size_t)PyBytes_GET_SIZE(expected) + 1,
    };
    PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &probe.original);
    PyMemAllocatorEx watch = {
        .ctx = &probe,
        .malloc = unicode_cache_malloc,
        .calloc = unicode_cache_calloc,
        .realloc = unicode_cache_realloc,
        .free = unicode_cache_free,
    };
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &watch);
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    int started = PyThread_start_joinable_thread(
        unicode_cache_worker, &probe, &ident, &handle);
    int ok = 0;
    if (started == 0) {
        ok = PyEvent_WaitTimed(&probe.allocated, 10000000000LL, 1) &&
            _Py_atomic_load_ptr(&probe.candidate) != NULL;
        Py_ssize_t size = 0;
        const char *cache = PyUnicode_AsUTF8AndSize(fresh, &size);
        Py_hash_t hash = PyObject_Hash(fresh);
        _PyEvent_Notify(&probe.resume);
        Py_BEGIN_ALLOW_THREADS
        PyThread_join_thread(handle);
        Py_END_ALLOW_THREADS
        ok &= cache != NULL && hash != -1 && probe.base.ok &&
            !probe.timed_out && _Py_atomic_load_int(&probe.discarded) &&
            cache == probe.worker_cache && size == probe.worker_size &&
            size == PyBytes_GET_SIZE(expected) && hash == probe.worker_hash;
        if (ok) {
            ok = memcmp(cache, PyBytes_AS_STRING(expected), size) == 0 &&
                cache[size] == '\0' && PyUnicode_AsUTF8(fresh) == cache;
        }
    }
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &probe.original);
    Py_DECREF(fresh);
    _PyThreadGroup_Decref(state);
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "Unicode cache publication probe failed");
    }
    Py_RETURN_NONE;
}

// Native callbacks deliberately return a heap reference without exposing its
// contents. The public API must validate that reference before its caller uses it.
static PyObject *
return_heap_value(PyObject *self, PyObject *unused)
{
    return Py_NewRef(PyTuple_GET_ITEM(self, 0));
}

static PyMethodDef return_heap_value_def = {
    "return_heap_value", return_heap_value, METH_NOARGS, NULL,
};

typedef struct {
    PyObject_HEAD
    PyObject *value;
    int descriptor_calls;
    vectorcallfunc vectorcall;
} return_box;

static int
return_box_traverse(PyObject *op, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(((return_box *)op)->value);
    return 0;
}

static void
return_box_dealloc(PyObject *op)
{
    PyTypeObject *type = Py_TYPE(op);
    PyObject_GC_UnTrack(op);
    Py_XDECREF(((return_box *)op)->value);
    type->tp_free(op);
    Py_DECREF(type);
}

static PyObject *
return_box_getattr(PyObject *op, char *name)
{
    if (strcmp(name, "value") == 0) {
        return Py_NewRef(((return_box *)op)->value);
    }
    return PyErr_Format(PyExc_AttributeError, "unknown attribute %s", name);
}

static PyObject *
return_box_getattro(PyObject *op, PyObject *name)
{
    if (PyUnicode_CompareWithASCIIString(name, "value") == 0) {
        return Py_NewRef(((return_box *)op)->value);
    }
    return PyObject_GenericGetAttr(op, name);
}

static PyMemberDef return_box_members[] = {
    {"value", Py_T_OBJECT_EX, offsetof(return_box, value), Py_READONLY},
    {NULL},
};

static PyType_Slot return_box_slots[] = {
    {Py_tp_dealloc, return_box_dealloc},
    {Py_tp_traverse, return_box_traverse},
    {Py_tp_getattr, return_box_getattr},
    {Py_tp_getattro, return_box_getattro},
    {Py_tp_members, return_box_members},
    {0, NULL},
};

static PyType_Spec return_box_spec = {
    .name = "_testinternalcapi.ReturnBox",
    .basicsize = sizeof(return_box),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = return_box_slots,
};

static PyObject *
return_box_compare(PyObject *self, PyObject *other, int comparison)
{
    return Py_NewRef(((return_box *)self)->value);
}

static PyType_Slot member_box_slots[] = {
    {Py_tp_dealloc, return_box_dealloc},
    {Py_tp_traverse, return_box_traverse},
    {Py_tp_members, return_box_members},
    {Py_tp_richcompare, return_box_compare},
    {0, NULL},
};

static PyType_Spec member_box_spec = {
    .name = "_testinternalcapi.MemberBox",
    .basicsize = sizeof(return_box),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = member_box_slots,
};

static PyObject *
return_box_vectorcall(PyObject *self, PyObject *const *args,
                      size_t nargsf, PyObject *kwnames)
{
    return Py_NewRef(((return_box *)self)->value);
}

static PyMemberDef vector_box_members[] = {
    {"__vectorcalloffset__", Py_T_PYSSIZET,
     offsetof(return_box, vectorcall), Py_READONLY},
    {NULL},
};

static PyType_Slot vector_box_slots[] = {
    {Py_tp_dealloc, return_box_dealloc},
    {Py_tp_traverse, return_box_traverse},
    {Py_tp_call, PyVectorcall_Call},
    {Py_tp_members, vector_box_members},
    {0, NULL},
};

static PyType_Spec vector_box_spec = {
    .name = "_testinternalcapi.VectorBox",
    .basicsize = sizeof(return_box),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_HAVE_VECTORCALL,
    .slots = vector_box_slots,
};

static PyObject *
make_return_box(PyType_Spec *spec, PyObject *value)
{
    PyTypeObject *type = (PyTypeObject *)PyType_FromSpec(spec);
    if (type == NULL) {
        return NULL;
    }
    return_box *box = (return_box *)type->tp_alloc(type, 0);
    Py_DECREF(type);
    if (box != NULL) {
        box->value = Py_NewRef(value);  // Blind heap-to-heap copy.
        box->vectorcall = return_box_vectorcall;
    }
    return (PyObject *)box;
}

static PyObject *
access_descriptor_get(PyObject *self, PyObject *obj, PyObject *type)
{
    _Py_atomic_add_int(&((return_box *)self)->descriptor_calls, 1);
    Py_RETURN_NONE;
}

static PyType_Slot access_descriptor_slots[] = {
    {Py_tp_dealloc, return_box_dealloc},
    {Py_tp_traverse, return_box_traverse},
    {Py_tp_descr_get, access_descriptor_get},
    {0, NULL},
};

static PyType_Spec access_descriptor_spec = {
    .name = "_testinternalcapi.AccessDescriptor",
    .basicsize = sizeof(return_box),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = access_descriptor_slots,
};

static PyObject *
make_access_descriptor(PyObject *self, PyObject *unused)
{
    return make_return_box(&access_descriptor_spec, Py_None);
}

static PyObject *
access_descriptor_calls(PyObject *self, PyObject *descriptor)
{
    if (Py_TYPE(descriptor)->tp_descr_get != access_descriptor_get) {
        return PyErr_Format(PyExc_TypeError, "expected an access descriptor");
    }
    return PyLong_FromLong(_Py_atomic_load_int(
        &((return_box *)descriptor)->descriptor_calls));
}

// Native slots avoid a later Python method lookup masking an unchecked
// container acquisition. Count calls so rejection cannot hide a side effect.
typedef struct {
    PyObject_HEAD
    int calls;
} container_element;

static void
container_element_dealloc(PyObject *op)
{
    PyTypeObject *type = Py_TYPE(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static PyObject *
container_element_repr(PyObject *op)
{
    _Py_atomic_add_int(&((container_element *)op)->calls, 1);
    return PyUnicode_FromString("container element");
}

static Py_hash_t
container_element_hash(PyObject *op)
{
    _Py_atomic_add_int(&((container_element *)op)->calls, 1);
    return 0;
}

static int
container_element_bool(PyObject *op)
{
    _Py_atomic_add_int(&((container_element *)op)->calls, 1);
    return 1;
}

static PyObject *
container_element_compare(PyObject *op, PyObject *other, int comparison)
{
    _Py_atomic_add_int(&((container_element *)op)->calls, 1);
    return PyBool_FromLong(comparison == Py_NE);
}

static PyObject *
make_container_element(PyObject *self, PyObject *immutable)
{
    int shareable = PyObject_IsTrue(immutable);
    if (shareable < 0) {
        return NULL;
    }
    PyType_Slot slots[] = {
        {Py_tp_dealloc, container_element_dealloc},
        {Py_tp_repr, container_element_repr},
        {Py_tp_hash, container_element_hash},
        {Py_nb_bool, container_element_bool},
        {Py_tp_richcompare, container_element_compare},
        {0, NULL},
    };
    PyType_Spec spec = {
        .name = "_testinternalcapi.ContainerElement",
        .basicsize = sizeof(container_element),
        .flags = Py_TPFLAGS_DEFAULT,
        .slots = slots,
    };
    PyTypeObject *type = (PyTypeObject *)PyType_FromSpec(&spec);
    if (type == NULL) {
        return NULL;
    }
    PyObject *element = type->tp_alloc(type, 0);
    Py_DECREF(type);
    if (element != NULL && shareable && PyObject_DeclareImmutable(element) < 0) {
        Py_CLEAR(element);
    }
    return element;
}

static PyObject *
container_element_calls(PyObject *self, PyObject *element)
{
    if (Py_TYPE(element)->tp_hash != container_element_hash) {
        return PyErr_Format(PyExc_TypeError, "expected a container element");
    }
    return PyLong_FromLong(_Py_atomic_load_int(
        &((container_element *)element)->calls));
}

static const char *return_apis[] = {
    "PyTuple_GetItem", "PySequence_GetItem", "PyObject_GetItem",
    "PyList_GetItem", "PyList_GetItemRef",
    "PyDict_GetItem", "PyDict_GetItemWithError", "PyDict_GetItemRef",
    "PyDict_GetItemString", "PyDict_GetItemStringRef",
    "PyMapping_GetOptionalItem", "PyIter_Next", "PyIter_NextItem", "PyIter_Send",
    "PyObject_CallNoArgs", "PyObject_GetAttr", "PyObject_GetAttrString",
    "PyObject_GetOptionalAttr", "PyObject_GetOptionalAttrString",
    "PyObject_GenericGetAttr", "PyCell_Get", "PyVectorcall_Call",
    "PyObject_Call", "PyObject_Vectorcall", "PyObject_VectorcallDict",
    "PyVectorcall_Call_keywords", "PyEval_GetBuiltins", "PyImport_GetModuleDict",
    "PySys_GetXOptions", "PyEval_GetFrameBuiltins",
    "PyObject_RichCompare", "PyObject_RichCompareBool", NULL,
};

struct return_probe {
    struct access_probe base;
    int api;
};

static void
return_probe_worker(void *arg)
{
    struct return_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->base.interp);
    if (tstate == NULL) {
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->base.group;
    _PyThreadGroup_Incref(tstate->threadgroup);
    PyEval_AcquireThread(tstate);

    PyObject *source = probe->base.value;
    assert(PyObject_IsAccessible(source));
    PyObject *value = PyTuple_GET_ITEM(source, 0);  // Raw heap reference.
    PyObject *mapping = PyTuple_GET_ITEM(source, 1);
    assert(PyObject_IsAccessible(mapping));
    probe->base.accessible = PyObject_IsAccessible(value);
    PyObject *key = PyUnicode_FromString("value");
    PyObject *list = NULL, *iter = NULL, *func = NULL, *box = NULL;
    PyObject *callargs = NULL, *kwargs = NULL;
    PyObject *result = NULL;
    int status = -2;  // Pointer-returning API, with no separate status code.
    int owned = 1;
    if (key == NULL) {
        goto done;
    }
    switch (probe->api) {
        case 0:
            result = PyTuple_GetItem(source, 0);
            owned = 0;
            break;
        case 1:
            result = PySequence_GetItem(source, 0);
            break;
        case 2: {
            PyObject *index = PyLong_FromLong(0);
            if (index == NULL) {
                goto done;
            }
            result = PyObject_GetItem(source, index);
            Py_DECREF(index);
            break;
        }
        case 3:
        case 4:
            // Copying a tuple's heap references into a local list is allowed.
            // Retrieving the copied value still needs a thread access check.
            list = PySequence_List(source);
            if (list == NULL) {
                goto done;
            }
            if (probe->api == 3) {
                result = PyList_GetItem(list, 0);
                owned = 0;
            }
            else {
                result = PyList_GetItemRef(list, 0);
            }
            break;
        case 5:
            result = PyDict_GetItem(mapping, key);
            owned = 0;
            break;
        case 6:
            result = PyDict_GetItemWithError(mapping, key);
            owned = 0;
            break;
        case 7:
            status = PyDict_GetItemRef(mapping, key, &result);
            break;
        case 8:
            result = PyDict_GetItemString(mapping, "value");
            owned = 0;
            break;
        case 9:
            status = PyDict_GetItemStringRef(mapping, "value", &result);
            break;
        case 10:
            status = PyMapping_GetOptionalItem(mapping, key, &result);
            break;
        case 11:
        case 12:
        case 13:
            iter = PyObject_GetIter(source);
            if (iter == NULL) {
                goto done;
            }
            if (probe->api == 11) {
                result = PyIter_Next(iter);
            }
            else if (probe->api == 12) {
                status = PyIter_NextItem(iter, &result);
            }
            else {
                PySendResult sent = PyIter_Send(iter, Py_None, &result);
                status = sent == PYGEN_NEXT ? 1 : sent == PYGEN_ERROR ? -1 : 0;
            }
            break;
        case 14:
            func = PyCFunction_NewEx(&return_heap_value_def, source, NULL);
            if (func == NULL) {
                goto done;
            }
            result = PyObject_CallNoArgs(func);
            break;
        case 20:
            box = PyCell_New(value);
            if (box == NULL) {
                goto done;
            }
            result = PyCell_Get(box);
            break;
        case 21:
        case 22:
        case 23:
        case 24:
        case 25:
            box = make_return_box(&vector_box_spec, value);
            callargs = PyTuple_New(0);
            kwargs = PyDict_New();
            if (box == NULL || callargs == NULL || kwargs == NULL ||
                PyDict_SetItemString(kwargs, "x", Py_None) < 0) {
                goto done;
            }
            switch (probe->api) {
                case 21: result = PyVectorcall_Call(box, callargs, NULL); break;
                case 22: result = PyObject_Call(box, callargs, NULL); break;
                case 23: result = PyObject_Vectorcall(box, NULL, 0, NULL); break;
                case 24: result = PyObject_VectorcallDict(box, NULL, 0, kwargs); break;
                case 25: result = PyVectorcall_Call(box, callargs, kwargs); break;
            }
            break;
        case 26:
            result = PyEval_GetBuiltins();
            owned = 0;
            break;
        case 27:
            result = PyImport_GetModuleDict();
            owned = 0;
            break;
        case 28:
            result = PySys_GetXOptions();
            owned = 0;
            break;
        case 29:
            result = PyEval_GetFrameBuiltins();
            break;
        case 30:
        case 31:
            box = make_return_box(&member_box_spec, value);
            if (box == NULL) {
                goto done;
            }
            if (probe->api == 30) {
                result = PyObject_RichCompare(box, Py_None, Py_LT);
            }
            else if (PyObject_RichCompareBool(box, Py_None, Py_LT) >= 0) {
                // Normalize a successful scalar result for the probe below.
                result = Py_NewRef(value);
            }
            break;
        default:
            box = make_return_box(&return_box_spec, value);
            if (box == NULL) {
                goto done;
            }
            switch (probe->api) {
                case 15: result = PyObject_GetAttr(box, key); break;
                case 16: result = PyObject_GetAttrString(box, "value"); break;
                case 17: status = PyObject_GetOptionalAttr(box, key, &result); break;
                case 18: status = PyObject_GetOptionalAttrString(box, "value", &result); break;
                case 19: result = PyObject_GenericGetAttr(box, key); break;
                default: Py_UNREACHABLE();
            }
    }
    if (status == -2) {
        status = result == NULL ? -1 : 1;
    }
    if (probe->base.accessible) {
        probe->base.ok = status == 1 && result == value && !PyErr_Occurred();
    }
    else {
        probe->base.ok = status == -1 && result == NULL &&
            PyErr_ExceptionMatches(PyExc_IllegalThreadAccessException);
    }
    if (owned) {
        Py_XDECREF(result);
    }
done:
    PyErr_Clear();
    Py_XDECREF(key);
    Py_XDECREF(list);
    Py_XDECREF(iter);
    Py_XDECREF(func);
    Py_XDECREF(box);
    Py_XDECREF(callargs);
    Py_XDECREF(kwargs);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_return_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *source;
    const char *api;
    if (!PyArg_ParseTuple(args, "O!Os:threadgroup_return_probe", &PyTuple_Type,
                          &source, &group, &api)) {
        return NULL;
    }
    if (PyTuple_GET_SIZE(source) != 2 ||
        !PyAnyDict_Check(PyTuple_GET_ITEM(source, 1))) {
        return PyErr_Format(PyExc_ValueError, "invalid return probe source");
    }
    int index;
    for (index = 0; return_apis[index] != NULL; index++) {
        if (strcmp(api, return_apis[index]) == 0) {
            break;
        }
    }
    if (return_apis[index] == NULL) {
        return PyErr_Format(PyExc_ValueError, "unknown API %s", api);
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    struct return_probe probe = {
        .base = {.interp = PyInterpreterState_Get(), .group = state, .value = source},
        .api = index,
    };
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(return_probe_worker, &probe,
                                      &ident, &handle) != 0) {
        _PyThreadGroup_Decref(state);
        return PyErr_Format(PyExc_RuntimeError, "failed to start return probe");
    }
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    _PyThreadGroup_Decref(state);
    if (!probe.base.ok) {
        return PyErr_Format(PyExc_AssertionError, "return access probe failed for %s", api);
    }
    return PyBool_FromLong(probe.base.accessible);
}

/* Execute shared immutable code using functions and namespaces created by the
   worker. No LOCAL Python callable is transferred between ThreadGroups. */
struct vm_probe {
    struct access_probe base;
    PyObject *code;
    PyObject *bytecode;
    int warmups;
    int trials;
    int capture_bytecode;
};

static PyObject *
make_vm_probe_class(void)
{
    PyObject *name = PyUnicode_FromString("VMProbe");
    PyObject *bases = PyTuple_Pack(1, &PyBaseObject_Type);
    PyObject *namespace = PyDict_New();
    PyObject *cls = NULL;
    if (name != NULL && bases != NULL && namespace != NULL) {
        cls = PyObject_CallFunctionObjArgs((PyObject *)&PyType_Type,
                                          name, bases, namespace, NULL);
    }
    Py_XDECREF(name);
    Py_XDECREF(bases);
    Py_XDECREF(namespace);
    return cls;
}

static PyObject *
make_vm_probe_instance(void)
{
    // Keep the instance's type stable when the separate class fixture changes.
    PyObject *cls = make_vm_probe_class();
    if (cls == NULL) {
        return NULL;
    }
    PyObject *instance = PyObject_CallNoArgs(cls);
    Py_DECREF(cls);
    return instance;
}

static int
set_vm_probe_values(PyObject *globals, PyObject *builtins, PyObject *cell,
                    PyObject *source, PyObject *box, PyObject *instance,
                    PyObject *cls, PyObject *module)
{
    PyObject *value = PyTuple_GET_ITEM(source, 0);  // Raw heap reference.
    PyObject *items = PySequence_List(source);
    PyObject *mapping = PyDict_New();
    int ok = items != NULL && mapping != NULL &&
        PyDict_SetItemString(mapping, "value", value) == 0 &&
        PyDict_SetItemString(globals, "value", value) == 0 &&
        PyDict_SetItemString(globals, "source", source) == 0 &&
        PyDict_SetItemString(globals, "items", items) == 0 &&
        PyDict_SetItemString(globals, "mapping", mapping) == 0 &&
        PyDict_SetItemString(builtins, "builtin_value", value) == 0 &&
        PyCell_Set(cell, value) == 0 &&
        PyObject_SetAttrString(instance, "value", value) == 0 &&
        PyObject_SetAttrString(cls, "value", value) == 0 &&
        PyObject_SetAttrString(module, "value", value) == 0;
    // The member is read-only to Python. Update the worker's own fixture in
    // native code, preserving the type and instance through specialization.
    Py_SETREF(((return_box *)box)->value, Py_NewRef(value));
    Py_XDECREF(mapping);
    Py_XDECREF(items);
    return ok ? 0 : -1;
}

static PyObject *
consume_probe_args(PyObject *self, PyObject *const *args,
                   Py_ssize_t nargs, PyObject *kwnames)
{
    Py_RETURN_TRUE;
}

static PyMethodDef consume_probe_args_def = {
    "consume", _PyCFunction_CAST(consume_probe_args),
    METH_FASTCALL | METH_KEYWORDS, NULL,
};

static PyObject *
legacy_probe_call(PyObject *consumer, PyObject *args)
{
    return PyObject_CallFunction(consumer, "O", args);
}

static PyObject *
prepend_probe_call(PyObject *consumer, PyObject *args)
{
    PyObject *cls = make_vm_probe_class();
    PyObject *method = PyStaticMethod_New(consumer);
    PyObject *result = NULL;
    if (cls != NULL && method != NULL &&
        PyObject_SetAttrString(cls, "__new__", method) == 0) {
        // Invoke the extension slot directly: its Python __new__ adapter
        // prepends the class while expanding the args tuple.
        PyTypeObject *type = (PyTypeObject *)cls;
        result = type->tp_new(type, args, NULL);
    }
    Py_XDECREF(method);
    Py_XDECREF(cls);
    return result;
}

static PyMethodDef legacy_probe_call_def = {
    "legacy_call", legacy_probe_call, METH_O, NULL,
};

static PyMethodDef prepend_probe_call_def = {
    "prepend_call", prepend_probe_call, METH_O, NULL,
};

static int
set_vm_probe_defaults(PyObject *func, PyObject *globals, PyObject *source)
{
    if (func == NULL) {
        return 0;
    }
    PyCodeObject *code = (PyCodeObject *)PyFunction_GET_CODE(func);
    if (code->co_argcount == 3 && PyFunction_SetDefaults(func, source) < 0) {
        return -1;
    }
    if (code->co_kwonlyargcount) {
        PyObject *mapping = PyDict_GetItemString(globals, "mapping");
        if (mapping == NULL || PyFunction_SetKwDefaults(func, mapping) < 0) {
            return -1;
        }
    }
    return 0;
}

static void
vm_probe_worker(void *arg)
{
    struct vm_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->base.interp);
    if (tstate == NULL) {
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->base.group;
    _PyThreadGroup_Incref(tstate->threadgroup);
    PyEval_AcquireThread(tstate);

    PyObject *source = probe->base.value;
    probe->base.accessible = PyObject_IsAccessible(PyTuple_GET_ITEM(source, 0));
    PyObject *globals = PyDict_New();
    PyObject *builtins = PyDict_New();
    PyObject *cell = PyCell_New(NULL);
    PyObject *box = make_return_box(&member_box_spec, Py_None);
    PyObject *cls = make_vm_probe_class();
    PyObject *instance = make_vm_probe_instance();
    PyObject *module = PyModule_New("_testinternalcapi.vm_probe");
    PyObject *consumer = PyCFunction_NewEx(&consume_probe_args_def, NULL, NULL);
    PyObject *legacy = consumer == NULL ? NULL :
        PyCFunction_NewEx(&legacy_probe_call_def, consumer, NULL);
    PyObject *prepend = consumer == NULL ? NULL :
        PyCFunction_NewEx(&prepend_probe_call_def, consumer, NULL);
    PyObject *func = NULL, *closure = NULL, *warm = NULL, *result = NULL;
    if (globals == NULL || builtins == NULL || cell == NULL || box == NULL ||
        cls == NULL || instance == NULL || module == NULL || consumer == NULL ||
        legacy == NULL || prepend == NULL ||
        PyDict_SetItemString(globals, "__builtins__", builtins) < 0 ||
        PyDict_SetItemString(builtins, "TypeError", PyExc_TypeError) < 0 ||
        PyDict_SetItemString(globals, "box", box) < 0 ||
        PyDict_SetItemString(globals, "instance", instance) < 0 ||
        PyDict_SetItemString(globals, "cls", cls) < 0 ||
        PyDict_SetItemString(globals, "module", module) < 0 ||
        PyDict_SetItemString(globals, "legacy_call", legacy) < 0 ||
        PyDict_SetItemString(globals, "prepend_call", prepend) < 0 ||
        PyDict_SetItemString(globals, "consumer", consumer) < 0) {
        goto done;
    }
    int is_function = ((PyCodeObject *)probe->code)->co_flags & CO_NEWLOCALS;
    if (is_function) {
        func = PyFunction_New(probe->code, globals);
        if (func == NULL) {
            goto done;
        }
        if (((PyCodeObject *)probe->code)->co_nfreevars) {
            closure = PyTuple_Pack(1, cell);
            if (closure == NULL || PyFunction_SetClosure(func, closure) < 0) {
                goto done;
            }
        }
    }
    warm = PyTuple_Pack(3, Py_None, Py_None, Py_None);
    if (warm == NULL || set_vm_probe_values(globals, builtins, cell, warm,
                                            box, instance, cls, module) < 0 ||
        set_vm_probe_defaults(func, globals, warm) < 0) {
        goto done;
    }
    for (int i = 0; i < probe->warmups; i++) {
        result = is_function ? PyObject_CallNoArgs(func) :
            PyEval_EvalCode(probe->code, globals, globals);
        if (result == NULL) {
            goto done;
        }
        Py_CLEAR(result);
    }
    if (set_vm_probe_values(globals, builtins, cell, source,
                            box, instance, cls, module) < 0 ||
        set_vm_probe_defaults(func, globals, source) < 0) {
        goto done;
    }
    for (int i = 0; i < probe->trials; i++) {
        result = is_function ? PyObject_CallNoArgs(func) :
            PyEval_EvalCode(probe->code, globals, globals);
        if (probe->base.accessible) {
            // Test code consumes acquired values and returns only a primitive.
            probe->base.ok = result != NULL &&
                (result == Py_None || PyBool_Check(result)) && !PyErr_Occurred();
        }
        else {
            probe->base.ok = result == NULL &&
                PyErr_ExceptionMatches(PyExc_IllegalThreadAccessException);
        }
        if (!probe->base.ok) {
            goto done;
        }
        Py_CLEAR(result);
        PyErr_Clear();
    }
    if (probe->capture_bytecode) {
        PyCodeObject *code = (PyCodeObject *)probe->code;
        _Py_CODEUNIT *bytecode = _PyCode_GetTLBCFast(tstate, code);
        if (bytecode == NULL) {
            // Argument acquisition can reject the call before the first RESUME.
            probe->bytecode = Py_NewRef(Py_None);
        }
        else {
            probe->bytecode = PyBytes_FromStringAndSize(
                (const char *)bytecode, _PyCode_NBYTES(code));
        }
        probe->base.ok = probe->bytecode != NULL;
    }
done:
    PyErr_Clear();
    Py_XDECREF(result);
    Py_XDECREF(warm);
    Py_XDECREF(closure);
    Py_XDECREF(func);
    Py_XDECREF(cell);
    Py_XDECREF(box);
    Py_XDECREF(instance);
    Py_XDECREF(cls);
    Py_XDECREF(module);
    Py_XDECREF(consumer);
    Py_XDECREF(legacy);
    Py_XDECREF(prepend);
    Py_XDECREF(builtins);
    Py_XDECREF(globals);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_vm_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *source, *code;
    int warmups, trials = 1, capture_bytecode = 0;
    if (!PyArg_ParseTuple(args, "O!OO!i|ip:threadgroup_vm_probe", &PyCode_Type,
                          &code, &group, &PyTuple_Type, &source, &warmups,
                          &trials, &capture_bytecode)) {
        return NULL;
    }
    if (PyTuple_GET_SIZE(source) != 3 || warmups < 0 || warmups > 1000 ||
        trials < 1 || trials > 1000 ||
        (((PyCodeObject *)code)->co_argcount != 0 &&
         ((PyCodeObject *)code)->co_argcount != 3) ||
        ((PyCodeObject *)code)->co_nfreevars > 1) {
        return PyErr_Format(PyExc_ValueError, "invalid VM probe arguments");
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    struct vm_probe probe = {
        .base = {.interp = PyInterpreterState_Get(), .group = state, .value = source},
        .code = code,
        .warmups = warmups,
        .trials = trials,
        .capture_bytecode = capture_bytecode,
    };
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(vm_probe_worker, &probe, &ident, &handle) != 0) {
        _PyThreadGroup_Decref(state);
        return PyErr_Format(PyExc_RuntimeError, "failed to start VM probe");
    }
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    _PyThreadGroup_Decref(state);
    if (!probe.base.ok) {
        Py_XDECREF(probe.bytecode);
        return PyErr_Format(PyExc_AssertionError, "VM reference acquisition probe failed");
    }
    if (capture_bytecode) {
        return Py_BuildValue("NN", PyBool_FromLong(probe.base.accessible),
                             probe.bytecode);
    }
    return PyBool_FromLong(probe.base.accessible);
}

struct freelist_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyEvent ready;
    PyEvent collected;
    PyEvent detached;
    PyEvent cleared;
    uintptr_t caller_cached;
    PyThreadState *to_clear;
    int clear_elsewhere;
    int ok;
};

static void
freelist_probe_worker(void *arg)
{
    struct freelist_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->ready);
        _PyEvent_Notify(&probe->detached);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    PyEval_AcquireThread(tstate);

    PyObject *value = PyFloat_FromDouble(1.25);
    struct _Py_freelists *freelists = _Py_freelists_GET();
    if (value != NULL) {
        uintptr_t address = (uintptr_t)value;
        probe->ok = address != probe->caller_cached &&
            value->ob_owner_id == tstate->threadgroup->id;
        Py_DECREF(value);
        // Allocation in this thread reuses its own cache and resets the header.
        value = PyFloat_FromDouble(2.5);
        probe->ok &= value != NULL && (uintptr_t)value == address &&
            value->ob_owner_id == tstate->threadgroup->id &&
            PyFloat_AS_DOUBLE(value) == 2.5;
        Py_XDECREF(value);
    }
    _PyEvent_Notify(&probe->ready);
    if (!PyEvent_WaitTimed(&probe->collected, 10000000000LL, 1)) {
        probe->ok = 0;
    }
    // Full GC must clear the detached worker's cache as well as its caller's.
    probe->ok &= freelists->floats.size == 0;
    value = PyFloat_FromDouble(3.75);
    probe->ok &= value != NULL;
    Py_XDECREF(value);
    probe->ok &= freelists->floats.size == 1;
    PyErr_Clear();
    if (probe->clear_elsewhere) {
        probe->to_clear = tstate;
        PyEval_ReleaseThread(tstate);
        _PyEvent_Notify(&probe->detached);
        PyEvent_Wait(&probe->cleared);
        // Unbind on the OS thread which owns the GILState TLS slot.
        PyThreadState_Delete(tstate);
    }
    else {
        PyThreadState_Clear(tstate);
        probe->ok &= freelists->floats.size == -1 &&
            freelists->floats.freelist == NULL;
        PyThreadState_DeleteCurrent();
    }
}

static PyObject *
threadgroup_freelist_probe(PyObject *self, PyObject *args)
{
    PyObject *group;
    int clear_elsewhere;
    if (!PyArg_ParseTuple(args, "Op:threadgroup_freelist_probe",
                          &group, &clear_elsewhere)) {
        return NULL;
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    PyObject *value = PyFloat_FromDouble(0.625);
    if (value == NULL) {
        _PyThreadGroup_Decref(state);
        return NULL;
    }
    struct freelist_probe probe = {
        .interp = PyInterpreterState_Get(),
        .group = state,
        .caller_cached = (uintptr_t)value,
        .clear_elsewhere = clear_elsewhere,
    };
    Py_DECREF(value);
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(freelist_probe_worker, &probe,
                                       &ident, &handle) != 0) {
        _PyThreadGroup_Decref(state);
        return PyErr_Format(PyExc_RuntimeError, "failed to start freelist probe");
    }
    int ok = PyEvent_WaitTimed(&probe.ready, 10000000000LL, 1);
    PyGC_Collect();
    struct _Py_freelists *freelists = _Py_freelists_GET();
    ok &= freelists->floats.size == 0;
    _PyEvent_Notify(&probe.collected);
    if (clear_elsewhere) {
        PyEvent_Wait(&probe.detached);
    }
    if (clear_elsewhere && probe.to_clear != NULL) {
        value = PyFloat_FromDouble(4.5);
        ok &= value != NULL;
        Py_XDECREF(value);
        void *cached = freelists->floats.freelist;
        Py_ssize_t size = freelists->floats.size;
        PyThreadState_Clear(probe.to_clear);
        struct _Py_freelists *other =
            &((_PyThreadStateImpl *)probe.to_clear)->freelists;
        ok &= other->floats.size == -1 && other->floats.freelist == NULL;
        // Clearing another state must not disable or empty our own cache.
        ok &= size > 0 && freelists->floats.size == size &&
            freelists->floats.freelist == cached;
    }
    _PyEvent_Notify(&probe.cleared);
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    _PyThreadGroup_Decref(state);
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (!ok || !probe.ok) {
        return PyErr_Format(PyExc_AssertionError, "thread-local freelist probe failed");
    }
    Py_RETURN_NONE;
}

struct world_stop_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyThreadState *tstate;
    PyEvent ready;
    PyEvent proceed;
    PyEvent attempted;
    PyEvent entered;
    int ok;
};

static void
world_stop_probe_worker(void *arg)
{
    struct world_stop_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->ready);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    probe->tstate = tstate;
    _PyEvent_Notify(&probe->ready);
    PyEvent_Wait(&probe->proceed);
    _PyEvent_Notify(&probe->attempted);
    PyEval_AcquireThread(tstate);
    probe->ok = tstate->holds_threadgroup &&
        _Py_atomic_load_int(&tstate->state) == _Py_THREAD_ATTACHED;
    _PyEvent_Notify(&probe->entered);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_world_stop_probe(PyObject *self, PyObject *args)
{
    PyObject *group;
    int create_during_stop;
    if (!PyArg_ParseTuple(args, "Op:threadgroup_world_stop_probe",
                          &group, &create_during_stop)) {
        return NULL;
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    struct world_stop_probe probe = {
        .interp = PyInterpreterState_Get(), .group = state,
    };
    if (create_during_stop) {
        _PyEval_StopTheWorld(probe.interp);
    }
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(world_stop_probe_worker, &probe,
                                       &ident, &handle) != 0) {
        if (create_during_stop) {
            _PyEval_StartTheWorld(probe.interp);
        }
        _PyThreadGroup_Decref(state);
        return PyErr_Format(PyExc_RuntimeError, "failed to start world-stop probe");
    }
    // Creating a detached state does not require Python execution rights.
    int ok = PyEvent_WaitTimed(&probe.ready, 10000000000LL, 0);
    if (!create_during_stop) {
        _PyEval_StopTheWorld(probe.interp);
    }
    ok &= probe.interp->stoptheworld.world_stopped;
    if (ok && probe.tstate != NULL) {
        ok &= _Py_atomic_load_int(&probe.tstate->state) == _Py_THREAD_SUSPENDED;
        _PyEvent_Notify(&probe.proceed);
        // Release both the interpreter GIL and our group while the world is
        // stopped: those locks must not be what keeps the worker suspended.
        Py_BEGIN_ALLOW_THREADS
        ok &= PyEvent_WaitTimed(&probe.attempted, 10000000000LL, 0);
        ok &= !PyEvent_WaitTimed(&probe.entered, 10000000LL, 0);
        Py_END_ALLOW_THREADS
    }
    _PyEval_StartTheWorld(probe.interp);
    _PyEvent_Notify(&probe.proceed);
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    _PyThreadGroup_Decref(state);
    if (!ok || !probe.ok) {
        return PyErr_Format(PyExc_AssertionError, "ThreadGroup world-stop probe failed");
    }
    Py_RETURN_NONE;
}

static PyObject *
threadgroup_world_is_stopped(PyObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = PyInterpreterState_Get();
    return PyBool_FromLong(interp->stoptheworld.world_stopped ||
                           interp->runtime->stoptheworld.world_stopped);
}

typedef struct {
    PyObject_HEAD
    PyObject *cycle;
    unsigned *observed;
} gc_world_stop_probe;

enum {
    GC_PROBE_TRAVERSED = 1,
    GC_PROBE_CLEARED = 2,
    GC_PROBE_FREED = 4,
    GC_PROBE_BAD_PHASE = 8,
};

static int
gc_world_stop_traverse(PyObject *op, visitproc visit, void *arg)
{
    gc_world_stop_probe *probe = (gc_world_stop_probe *)op;
    if (probe->observed != NULL) {
        *probe->observed |= GC_PROBE_TRAVERSED;
        if (!_PyInterpreterState_GET()->stoptheworld.world_stopped) {
            *probe->observed |= GC_PROBE_BAD_PHASE;
        }
    }
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(probe->cycle);
    return 0;
}

static int
gc_world_stop_clear(PyObject *op)
{
    gc_world_stop_probe *probe = (gc_world_stop_probe *)op;
    if (probe->observed != NULL) {
        *probe->observed |= GC_PROBE_CLEARED;
        if (_PyInterpreterState_GET()->stoptheworld.world_stopped) {
            *probe->observed |= GC_PROBE_BAD_PHASE;
        }
        if (op->ob_ref_local != 0 || !_Py_REF_IS_MERGED(op->ob_ref_shared)) {
            *probe->observed |= GC_PROBE_BAD_PHASE;
        }
    }
    Py_CLEAR(probe->cycle);
    return 0;
}

static void
gc_world_stop_dealloc(PyObject *op)
{
    PyObject_GC_UnTrack(op);
    gc_world_stop_probe *probe = (gc_world_stop_probe *)op;
    if (probe->observed != NULL) {
        *probe->observed |= GC_PROBE_FREED;
    }
    gc_world_stop_clear(op);
    PyTypeObject *type = Py_TYPE(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static gc_world_stop_probe *
new_gc_world_stop_probe(unsigned *observed)
{
    PyType_Slot slots[] = {
        {Py_tp_traverse, gc_world_stop_traverse},
        {Py_tp_clear, gc_world_stop_clear},
        {Py_tp_dealloc, gc_world_stop_dealloc},
        {0, NULL},
    };
    PyType_Spec spec = {
        .name = "_testinternalcapi.GCWorldStopProbe",
        .basicsize = sizeof(gc_world_stop_probe),
        .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
        .slots = slots,
    };
    PyObject *type = PyType_FromSpec(&spec);
    if (type == NULL) {
        return NULL;
    }
    gc_world_stop_probe *probe = (gc_world_stop_probe *)
        PyType_GenericAlloc((PyTypeObject *)type, 0);
    Py_DECREF(type);
    if (probe == NULL) {
        return NULL;
    }
    probe->observed = observed;
    probe->cycle = Py_NewRef((PyObject *)probe);
    return probe;
}

static PyObject *
test_gc_world_stop(PyObject *self, PyObject *Py_UNUSED(args))
{
    unsigned observed = 0;
    gc_world_stop_probe *probe = new_gc_world_stop_probe(&observed);
    if (probe == NULL) {
        return NULL;
    }
    Py_DECREF(probe);
    PyGC_Collect();
    if (!(observed & GC_PROBE_FREED)) {
        // Keep the native observation storage alive until the cycle is gone,
        // even when the collector failed to reclaim it.
        Py_INCREF(probe);
        Py_CLEAR(probe->cycle);
        Py_DECREF(probe);
        observed |= GC_PROBE_BAD_PHASE;
    }
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (observed != (GC_PROBE_TRAVERSED | GC_PROBE_CLEARED | GC_PROBE_FREED)) {
        return PyErr_Format(PyExc_AssertionError, "incorrect GC world-stop phases");
    }
    Py_RETURN_NONE;
}

static PyObject *
gc_traversal_world_stop_probe(PyObject *self, PyObject *callback)
{
    unsigned observed = 0;
    gc_world_stop_probe *probe = new_gc_world_stop_probe(&observed);
    if (probe == NULL) {
        return NULL;
    }
    PyObject *result = PyObject_CallOneArg(callback, (PyObject *)probe);
    int found = 0;
    if (result != NULL && PyList_Check(result)) {
        for (Py_ssize_t i = 0; i < PyList_GET_SIZE(result); i++) {
            found |= PyList_GET_ITEM(result, i) == (PyObject *)probe;
        }
    }
    int ok = observed == GC_PROBE_TRAVERSED && found &&
             !_PyInterpreterState_GET()->stoptheworld.world_stopped;
    // The callback may retain the probe, but the observation storage is local.
    probe->observed = NULL;
    Py_CLEAR(probe->cycle);
    Py_DECREF(probe);
    if (result == NULL) {
        return NULL;
    }
    Py_DECREF(result);
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "GC introspection did not traverse while paused");
    }
    Py_RETURN_NONE;
}

struct gc_visit_probe {
    int calls;
    int bad_phase;
    int limit;
};

static int
gc_visit_world_stop(PyObject *op, void *arg)
{
    struct gc_visit_probe *probe = arg;
    probe->calls++;
    if (!_PyInterpreterState_GET()->stoptheworld.world_stopped) {
        probe->bad_phase = 1;
    }
    return probe->limit == 0 || probe->calls < probe->limit;
}

static PyObject *
test_gc_visit_world_stop(PyObject *self, PyObject *Py_UNUSED(args))
{
    int enabled = PyGC_IsEnabled();
    for (int limit = 0; limit <= 1; limit++) {
        struct gc_visit_probe probe = {.limit = limit};
        PyUnstable_GC_VisitObjects(gc_visit_world_stop, &probe);
        if (probe.calls == 0 || probe.bad_phase ||
            (limit && probe.calls != limit) ||
            _PyInterpreterState_GET()->stoptheworld.world_stopped ||
            PyGC_IsEnabled() != enabled)
        {
            return PyErr_Format(PyExc_AssertionError,
                                "incorrect GC visitor world-stop phases");
        }
    }
    Py_RETURN_NONE;
}

struct qsbr_probe {
    PyMemAllocatorEx original;
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyObject *code;
    PyObject *error;
    PyEvent ready;
    PyEvent resume;
    void *target;
    int freed;
    int freed_while_stopped;
    int fail_calloc;
    int mode;
    int ok;
};

static void
qsbr_probe_collect(void)
{
    // Unlike Python's gc.collect(), PyGC_Collect() honors gc.disable().
    int enabled = PyGC_Enable();
    PyGC_Collect();
    if (!enabled) {
        PyGC_Disable();
    }
}

static void *
qsbr_probe_malloc(void *ctx, size_t size)
{
    struct qsbr_probe *probe = ctx;
    return probe->original.malloc(probe->original.ctx, size);
}

static void *
qsbr_probe_calloc(void *ctx, size_t nelem, size_t size)
{
    struct qsbr_probe *probe = ctx;
    if (_Py_atomic_exchange_int(&probe->fail_calloc, 0)) {
        return NULL;
    }
    return probe->original.calloc(probe->original.ctx, nelem, size);
}

static void *
qsbr_probe_realloc(void *ctx, void *ptr, size_t size)
{
    struct qsbr_probe *probe = ctx;
    return probe->original.realloc(probe->original.ctx, ptr, size);
}

static void
qsbr_probe_free(void *ctx, void *ptr)
{
    struct qsbr_probe *probe = ctx;
    if (ptr != NULL && ptr == _Py_atomic_load_ptr(&probe->target)) {
        _Py_atomic_store_ptr(&probe->target, NULL);
        _Py_atomic_store_int(&probe->freed, 1);
        PyThreadState *tstate = PyThreadState_Get();
        _Py_atomic_store_int(&probe->freed_while_stopped,
                            tstate->interp->stoptheworld.world_stopped);
    }
    probe->original.free(probe->original.ctx, ptr);
}

static void
qsbr_probe_worker(void *arg)
{
    struct qsbr_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->ready);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    PyEval_AcquireThread(tstate);
    _PyThreadStateImpl *ts = (_PyThreadStateImpl *)tstate;
    PyObject *func = NULL, *globals = NULL;
    if (probe->mode == 2) {
        globals = PyDict_New();
        if (globals == NULL ||
            PyDict_SetItemString(globals, "__builtins__", Py_None) < 0) {
            goto done;
        }
        // Compile in the caller: Python audit hooks belong to its group.
        // The code is immutable; the function and globals belong to this one.
        func = PyFunction_New(probe->code, globals);
        if (func == NULL) {
            goto done;
        }
    }
    // A large retirement advances the write sequence and requests processing
    // by the eval breaker. Smaller ones target the next, unadvanced sequence.
    size_t size = probe->mode == 2 ? 1024 * 1024 + 1 : 32;
    char *ptr;
    if (probe->mode == 7) {
        Py_ssize_t index = PyUnstable_Eval_RequestCodeExtraIndex(NULL);
        if (index < 0 ||
            PyUnstable_Code_SetExtra(probe->code, index, (void *)1) < 0) {
            goto done;
        }
        ptr = ((PyCodeObject *)probe->code)->co_extra;
    }
    else {
        ptr = PyMem_Malloc(size);
    }
    if (ptr == NULL) {
        goto done;
    }
    if (probe->mode != 7) {
        ptr[0] = 'Q';
    }
    _Py_atomic_store_ptr(&probe->target, ptr);
    if (probe->mode == 6) {
        // This fresh thread has no work buffer. Fail only its allocation.
        _Py_atomic_store_int(&probe->fail_calloc, 1);
    }
    if (probe->mode == 7) {
        // Grow shared code metadata while this reader still has the old array.
        Py_ssize_t index = PyUnstable_Eval_RequestCodeExtraIndex(NULL);
        if (index < 0 ||
            PyUnstable_Code_SetExtra(probe->code, index, (void *)2) < 0) {
            goto done;
        }
    }
    else {
        _PyMem_FreeDelayed(ptr, size);
    }
    probe->ok = !_Py_atomic_load_int(&probe->freed);
    if (probe->mode == 6) {
        probe->ok = _Py_atomic_load_int(&probe->freed) &&
            _Py_atomic_load_int(&probe->freed_while_stopped) &&
            !_Py_atomic_load_int(&probe->fail_calloc) &&
            !tstate->interp->stoptheworld.world_stopped;
    }
    else if (probe->ok && (probe->mode <= 1 || probe->mode == 7)) {
        _Py_qsbr_advance(&tstate->interp->qsbr);
        _PyMem_ProcessDelayed(tstate);
        probe->ok = !_Py_atomic_load_int(&probe->freed);
        if (probe->ok) {
            // Still a valid uncounted pointer until this reader quiesces.
            if (probe->mode != 7) {
                probe->ok = ptr[0] == 'Q';
            }
            if (probe->mode != 1) {
                _Py_qsbr_quiescent_state(ts->qsbr);
            }
            else {
                Py_BEGIN_ALLOW_THREADS
                Py_END_ALLOW_THREADS
            }
            _PyMem_ProcessDelayed(tstate);
            probe->ok &= _Py_atomic_load_int(&probe->freed);
        }
    }
    else if (probe->ok && probe->mode == 2) {
        _Py_set_eval_breaker_bit(tstate, _PY_EVAL_EXPLICIT_MERGE_BIT);
        PyObject *result = PyObject_CallNoArgs(func);
        probe->ok = result != NULL && _Py_atomic_load_int(&probe->freed);
        Py_XDECREF(result);
    }
    else if (probe->ok && probe->mode == 3) {
        qsbr_probe_collect();
        probe->ok = _Py_atomic_load_int(&probe->freed) &&
            _Py_atomic_load_int(&probe->freed_while_stopped) &&
            !tstate->interp->stoptheworld.world_stopped;
    }
    else if (probe->ok && probe->mode == 5) {
        _PyEvent_Notify(&probe->ready);
        probe->ok = PyEvent_WaitTimed(&probe->resume, 10000000000LL, 1) &&
            _Py_atomic_load_int(&probe->freed);
    }
    // Mode 4 leaves the request in this thread's queue at thread exit.
done:
    _PyEvent_Notify(&probe->ready);
    probe->ok &= !PyErr_Occurred();
    if (PyErr_Occurred()) {
        PyObject *exc = PyErr_GetRaisedException();
        probe->error = PyObject_Str(exc);
        Py_DECREF(exc);
        PyErr_Clear();
    }
    Py_XDECREF(func);
    Py_XDECREF(globals);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_qsbr_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *code;
    int mode;
    if (!PyArg_ParseTuple(args, "OiO!:threadgroup_qsbr_probe", &group, &mode,
                          &PyCode_Type, &code)) {
        return NULL;
    }
    if (mode < 0 || mode > 7) {
        return PyErr_Format(PyExc_ValueError, "invalid QSBR probe mode");
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    PyThreadState *tstate = PyThreadState_Get();
    struct qsbr_probe probe = {
        .interp = tstate->interp, .group = state, .mode = mode, .code = code,
    };
    qsbr_probe_collect();
    int enabled = PyGC_Disable();
    PyMemAllocatorEx watch = {
        .ctx = &probe,
        .malloc = qsbr_probe_malloc,
        .calloc = qsbr_probe_calloc,
        .realloc = qsbr_probe_realloc,
        .free = qsbr_probe_free,
    };
    _PyEval_StopTheWorldAll(&_PyRuntime);
    PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &probe.original);
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &watch);
    _PyEval_StartTheWorldAll(&_PyRuntime);

    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(qsbr_probe_worker, &probe,
                                      &ident, &handle) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "failed to start QSBR probe");
    }
    else {
        if (mode == 5) {
            PyEvent_WaitTimed(&probe.ready, 10000000000LL, 1);
            qsbr_probe_collect();
            _PyEvent_Notify(&probe.resume);
        }
        Py_BEGIN_ALLOW_THREADS
        PyThread_join_thread(handle);
        Py_END_ALLOW_THREADS
        // Also collects the exited producer's abandoned queue in mode 4.
        qsbr_probe_collect();
    }
    _PyEval_StopTheWorldAll(&_PyRuntime);
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &probe.original);
    _PyEval_StartTheWorldAll(&_PyRuntime);
    if (enabled) {
        PyGC_Enable();
    }
    _PyThreadGroup_Decref(state);
    if (PyErr_Occurred()) {
        Py_XDECREF(probe.error);
        return NULL;
    }
    if (!probe.ok || !probe.freed) {
        PyErr_Format(PyExc_AssertionError,
                     "QSBR grace period failed in mode %d (worker error: %S)",
                     mode, probe.error != NULL ? probe.error : Py_None);
        Py_XDECREF(probe.error);
        return NULL;
    }
    assert(probe.error == NULL);
    Py_RETURN_NONE;
}

static PyObject *
test_qsbr_thread_states(PyObject *self, PyObject *unused)
{
    // Keep enough states live to grow the QSBR array, then reuse their slots.
    PyThreadState *current = PyThreadState_Get();
    PyThreadState *states[32] = {0};
    int ok = 1;
    for (int round = 0; round < 2 && ok; round++) {
        for (int i = 0; i < 32; i++) {
            states[i] = PyThreadState_New(current->interp);
            if (states[i] == NULL) {
                ok = 0;
                break;
            }
            struct _qsbr_thread_state *qsbr =
                ((_PyThreadStateImpl *)states[i])->qsbr;
            ok &= qsbr != NULL && qsbr->allocated &&
                qsbr->tstate == states[i] && qsbr->seq == QSBR_OFFLINE;
        }
        struct _qsbr_thread_state *qsbr =
            ((_PyThreadStateImpl *)current)->qsbr;
        ok &= qsbr != NULL && qsbr->allocated && qsbr->tstate == current &&
            qsbr->seq != QSBR_OFFLINE;
        for (int i = 0; i < 32; i++) {
            if (states[i] != NULL) {
                PyThreadState_Clear(states[i]);
                PyThreadState_Delete(states[i]);
                states[i] = NULL;
            }
        }
    }
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError, "QSBR state registration failed");
    }
    Py_RETURN_NONE;
}

#define ALLOCATION_PROBE_COUNT 4096
#define ALLOCATION_PROBE_SIZE 32

#ifdef WITH_MIMALLOC
struct reentrant_allocation_probe {
    PyMemAllocatorEx original;
    int active;
    int calls;
    int changed_heap;
    mi_heap_t *expected_heap;
};

static void
allocation_probe_reenter(struct reentrant_allocation_probe *probe)
{
    _PyThreadStateImpl *tstate = (_PyThreadStateImpl *)_PyThreadState_GET();
    if (probe->active) {
        probe->changed_heap |= (probe->expected_heap != NULL &&
            tstate->mimalloc.current_object_heap != probe->expected_heap);
        return;
    }
    probe->active = 1;
    probe->calls++;
    mi_heap_t *heap = tstate->mimalloc.current_object_heap;
    // Too large for a freelist: this must re-enter the object allocator.
    PyObject *nested = PyTuple_New(100);
    Py_XDECREF(nested);
    // Raw object-domain allocations in the hook have no GC prefix.
    probe->expected_heap = &tstate->mimalloc.heaps[_Py_MIMALLOC_HEAP_OBJECT];
    void *raw = PyObject_Malloc(32);
    if (raw != NULL) {
        void *resized = PyObject_Realloc(raw, 64);
        PyObject_Free(resized != NULL ? resized : raw);
    }
    raw = PyObject_Calloc(1, 32);
    PyObject_Free(raw);
    probe->expected_heap = NULL;
    probe->changed_heap |= tstate->mimalloc.current_object_heap != heap;
    probe->active = 0;
}

static void *
allocation_probe_malloc(void *ctx, size_t size)
{
    struct reentrant_allocation_probe *probe = ctx;
    allocation_probe_reenter(probe);
    return probe->original.malloc(probe->original.ctx, size);
}

static void *
allocation_probe_calloc(void *ctx, size_t nelem, size_t size)
{
    struct reentrant_allocation_probe *probe = ctx;
    allocation_probe_reenter(probe);
    return probe->original.calloc(probe->original.ctx, nelem, size);
}

static void *
allocation_probe_realloc(void *ctx, void *ptr, size_t size)
{
    struct reentrant_allocation_probe *probe = ctx;
    allocation_probe_reenter(probe);
    return probe->original.realloc(probe->original.ctx, ptr, size);
}

static void
allocation_probe_free(void *ctx, void *ptr)
{
    struct reentrant_allocation_probe *probe = ctx;
    probe->original.free(probe->original.ctx, ptr);
}

static PyObject *
test_reentrant_allocation_heap(PyObject *self, PyObject *Py_UNUSED(args))
{
    struct reentrant_allocation_probe probe = {0};
    PyMem_GetAllocator(PYMEM_DOMAIN_OBJ, &probe.original);
    PyMemAllocatorEx wrapper = {
        .ctx = &probe,
        .malloc = allocation_probe_malloc,
        .calloc = allocation_probe_calloc,
        .realloc = allocation_probe_realloc,
        .free = allocation_probe_free,
    };
    PyMem_SetAllocator(PYMEM_DOMAIN_OBJ, &wrapper);
    PyObject *value = PyTuple_New(100);
    if (value != NULL) {
        _PyTuple_Resize(&value, 200);
    }
    PyMem_SetAllocator(PYMEM_DOMAIN_OBJ, &probe.original);
    Py_XDECREF(value);
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (probe.calls < 2 || probe.changed_heap) {
        return PyErr_Format(PyExc_AssertionError,
                            "nested allocation changed its caller's GC heap");
    }
    Py_RETURN_NONE;
}
#endif

struct allocation_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyObject *values;
    PyEvent ready;
    PyEvent exit;
};

static void
allocation_probe_worker(void *arg)
{
    struct allocation_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->ready);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    PyEval_AcquireThread(tstate);
    PyObject *values = PyTuple_New(ALLOCATION_PROBE_COUNT);
    if (values != NULL) {
        for (int i = 0; i < ALLOCATION_PROBE_COUNT; i++) {
            PyObject *value = PyBytes_FromStringAndSize(NULL, ALLOCATION_PROBE_SIZE);
            if (value == NULL) {
                Py_CLEAR(values);
                break;
            }
            memset(PyBytes_AS_STRING(value), (unsigned char)i, ALLOCATION_PROBE_SIZE);
            PyTuple_SET_ITEM(values, i, value);
        }
    }
    probe->values = values;
    PyErr_Clear();
    _PyEvent_Notify(&probe->ready);
    PyEvent_Wait(&probe->exit);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_allocation_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *measure;
    if (!PyArg_ParseTuple(args, "OO:threadgroup_allocation_probe", &group, &measure)) {
        return NULL;
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    PyObject *before = PyObject_CallNoArgs(measure);
    if (before == NULL) {
        _PyThreadGroup_Decref(state);
        return NULL;
    }
    struct allocation_probe probe = {
        .interp = PyInterpreterState_Get(), .group = state,
    };
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(allocation_probe_worker, &probe,
                                       &ident, &handle) != 0) {
        _PyThreadGroup_Decref(state);
        Py_DECREF(before);
        return PyErr_Format(PyExc_RuntimeError, "failed to start allocation probe");
    }
    PyEvent_Wait(&probe.ready);
    PyObject *live = PyObject_CallNoArgs(measure);
    _PyEvent_Notify(&probe.exit);
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    _PyThreadGroup_Decref(state);
    PyObject *abandoned = NULL, *freed = NULL, *result = NULL;
    if (live == NULL) {
        goto done;
    }
    abandoned = PyObject_CallNoArgs(measure);
    if (abandoned == NULL) {
        goto done;
    }
    if (probe.values == NULL) {
        PyErr_SetString(PyExc_AssertionError, "worker allocation failed");
        goto done;
    }
    for (int i = 0; i < ALLOCATION_PROBE_COUNT; i++) {
        PyObject *value = PyTuple_GetItem(probe.values, i);
        if (value == NULL) {
            goto done;
        }
        unsigned char *data = (unsigned char *)PyBytes_AS_STRING(value);
        for (int j = 0; j < ALLOCATION_PROBE_SIZE; j++) {
            if (data[j] != (unsigned char)i) {
                PyErr_SetString(PyExc_AssertionError, "abandoned allocation corrupted");
                goto done;
            }
        }
    }
    Py_CLEAR(probe.values);
    freed = PyObject_CallNoArgs(measure);
    if (freed != NULL) {
        result = PyTuple_Pack(4, before, live, abandoned, freed);
    }
done:
    Py_XDECREF(probe.values);
    Py_DECREF(before);
    Py_XDECREF(live);
    Py_XDECREF(abandoned);
    Py_XDECREF(freed);
    return result;
}

struct weakref_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *group;
    PyObject *target;
    PyEvent ready;
    PyEvent exit;
    int ok;
};

static void
weakref_probe_worker(void *arg)
{
    struct weakref_probe *probe = arg;
    PyThreadState *tstate = PyThreadState_New(probe->interp);
    if (tstate == NULL) {
        _PyEvent_Notify(&probe->ready);
        return;
    }
    _PyThreadGroup_Decref(tstate->threadgroup);
    tstate->threadgroup = probe->group;
    _PyThreadGroup_Incref(probe->group);
    PyEval_AcquireThread(tstate);
    assert(PyObject_IsAccessible(probe->target));

    PyObject *ref = PyWeakref_NewRef(probe->target, NULL);
    PyObject *proxy = PyWeakref_NewProxy(probe->target, NULL);
    PyObject *again = PyWeakref_NewRef(probe->target, NULL);
    PyObject *proxy_again = PyWeakref_NewProxy(probe->target, NULL);
    PyObject *target = NULL;
    probe->ok = ref != NULL && proxy != NULL && ref == again &&
        proxy == proxy_again && PyObject_IsAccessible(ref) &&
        PyObject_IsAccessible(proxy) &&
        ref->ob_owner_id == probe->group->id &&
        proxy->ob_owner_id == probe->group->id &&
        PyWeakref_GetRef(ref, &target) == 1 && target == probe->target;
    Py_XDECREF(target);
    Py_XDECREF(again);
    Py_XDECREF(proxy_again);
    probe->ok &= !PyErr_Occurred();
    PyErr_Clear();
    _PyEvent_Notify(&probe->ready);
    PyEvent_Wait(&probe->exit);
    Py_XDECREF(ref);
    Py_XDECREF(proxy);
    PyThreadState_Clear(tstate);
    PyThreadState_DeleteCurrent();
}

static PyObject *
threadgroup_weakref_probe(PyObject *self, PyObject *args)
{
    PyObject *group, *target;
    if (!PyArg_ParseTuple(args, "OO!:threadgroup_weakref_probe",
                         &group, &PyCode_Type, &target)) {
        return NULL;
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    // The target is immutable, but the cached weakrefs themselves are LOCAL.
    PyObject *ref = PyWeakref_NewRef(target, NULL);
    PyObject *proxy = PyWeakref_NewProxy(target, NULL);
    if (ref == NULL || proxy == NULL) {
        Py_XDECREF(ref);
        Py_XDECREF(proxy);
        _PyThreadGroup_Decref(state);
        return NULL;
    }
    struct weakref_probe probe = {
        .interp = PyInterpreterState_Get(), .group = state, .target = target,
    };
    PyThread_ident_t ident;
    PyThread_handle_t handle;
    if (PyThread_start_joinable_thread(weakref_probe_worker, &probe,
                                       &ident, &handle) != 0) {
        Py_DECREF(ref);
        Py_DECREF(proxy);
        _PyThreadGroup_Decref(state);
        return PyErr_Format(PyExc_RuntimeError, "failed to start weakref probe");
    }
    PyEvent_Wait(&probe.ready);
    // The foreign refs are still alive and ahead of this group's cache.
    PyObject *again = PyWeakref_NewRef(target, NULL);
    PyObject *proxy_again = PyWeakref_NewProxy(target, NULL);
    int ok = probe.ok && again == ref && proxy_again == proxy;
    Py_XDECREF(again);
    Py_XDECREF(proxy_again);
    _PyEvent_Notify(&probe.exit);
    Py_BEGIN_ALLOW_THREADS
    PyThread_join_thread(handle);
    Py_END_ALLOW_THREADS
    Py_DECREF(ref);
    Py_DECREF(proxy);
    _PyThreadGroup_Decref(state);
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "weakref cache returned another group's LOCAL ref");
    }
    Py_RETURN_NONE;
}

#ifdef Py_REF_DEBUG
static PyObject *
threadgroup_reftotal_fork_probe(PyObject *self, PyObject *fork_func)
{
    PyThreadState *current = PyThreadState_Get();
    PyInterpreterState *interp = current->interp;
    PyThreadState *worker = PyThreadState_New(interp);
    if (worker == NULL) {
        return PyErr_NoMemory();
    }
    PyThreadState_Swap(worker);
    PyObject *value = PyBytes_FromString("fork reference total probe");
    PyErr_Clear();
    PyThreadState_Swap(current);
    if (value == NULL) {
        PyThreadState_Clear(worker);
        PyThreadState_Delete(worker);
        return PyErr_NoMemory();
    }
    Py_ssize_t contribution = ((_PyThreadStateImpl *)worker)->reftotal;
    Py_ssize_t accumulated = interp->object_state.reftotal;
    PyObject *pid = PyObject_CallNoArgs(fork_func);
    int ok = 1;
    if (pid != NULL && PyLong_AsLong(pid) == 0) {
        // AfterFork_Child has removed and freed the other state. Its objects
        // can outlive it, so its reference total must still be accounted for.
        ok = contribution != 0 &&
            interp->object_state.reftotal == accumulated + contribution;
    }
    else {
        PyThreadState_Clear(worker);
        PyThreadState_Delete(worker);
    }
    Py_DECREF(value);
    if (PyErr_Occurred()) {
        Py_XDECREF(pid);
        return NULL;
    }
    if (!ok) {
        Py_DECREF(pid);
        return PyErr_Format(PyExc_AssertionError,
                            "fork lost a removed thread's reference total");
    }
    return pid;
}

static PyObject *
threadgroup_reftotal_probe(PyObject *self, PyObject *args)
{
    PyObject *group;
    int clear_elsewhere;
    if (!PyArg_ParseTuple(args, "Op:threadgroup_reftotal_probe",
                          &group, &clear_elsewhere)) {
        return NULL;
    }
    _PyThreadGroupState *state = _PyThreadGroup_GetState(group);
    if (state == NULL) {
        return NULL;
    }
    PyThreadState *current = PyThreadState_Get();
    PyInterpreterState *interp = current->interp;
    PyThreadState *worker = PyThreadState_New(interp);
    if (worker == NULL) {
        _PyThreadGroup_Decref(state);
        return PyErr_NoMemory();
    }
    _PyThreadGroup_Decref(worker->threadgroup);
    worker->threadgroup = state;

    // Switch states on the same OS thread to measure exact deltas without
    // concurrent Python execution changing the interpreter/global totals.
    _PyThreadStateImpl *current_impl = (_PyThreadStateImpl *)current;
    _PyThreadStateImpl *worker_impl = (_PyThreadStateImpl *)worker;
    Py_ssize_t current_total = current_impl->reftotal;
    PyThreadState_Swap(worker);
    // Keep an immutable object alive after its creating state is deleted.
    PyObject *value = PyBytes_FromStringAndSize("reference total probe", 21);
    if (value == NULL) {
        PyErr_Clear();
        PyThreadState_Clear(worker);
        PyThreadState_Swap(current);
        PyThreadState_Delete(worker);
        return PyErr_NoMemory();
    }
    Py_ssize_t local = worker_impl->reftotal;
    Py_ssize_t accumulated = interp->object_state.reftotal;
    Py_ssize_t total = _PyInterpreterState_GetRefTotal(interp);
    Py_ssize_t global = _Py_GetGlobalRefTotal();
    Py_INCREF(value);
    int ok = worker_impl->reftotal == local + 1 &&
        current_impl->reftotal == current_total &&
        interp->object_state.reftotal == accumulated &&
        _PyInterpreterState_GetRefTotal(interp) == total + 1 &&
        _Py_GetGlobalRefTotal() == global + 1;
    Py_DECREF(value);
    ok &= worker_impl->reftotal == local &&
        _PyInterpreterState_GetRefTotal(interp) == total &&
        _Py_GetGlobalRefTotal() == global;

    if (!clear_elsewhere) {
        PyThreadState_Clear(worker);
    }
    PyThreadState_Swap(current);
    if (clear_elsewhere) {
        PyThreadState_Clear(worker);
    }
    local = worker_impl->reftotal;
    accumulated = interp->object_state.reftotal;
    total = _PyInterpreterState_GetRefTotal(interp);
    global = _Py_GetGlobalRefTotal();
    PyThreadState_Delete(worker);
    // Deleting the state must transfer its contribution exactly once.
    ok &= local != 0 && interp->object_state.reftotal == accumulated + local &&
        _PyInterpreterState_GetRefTotal(interp) == total &&
        _Py_GetGlobalRefTotal() == global;
    Py_DECREF(value);
    ok &= _PyInterpreterState_GetRefTotal(interp) == total - 1 &&
        _Py_GetGlobalRefTotal() == global - 1;
    if (!ok) {
        return PyErr_Format(PyExc_AssertionError,
                            "thread reference totals were lost or shared");
    }
    Py_RETURN_NONE;
}
#endif

static PyMethodDef methods[] = {
#ifdef Py_REF_DEBUG
    {"threadgroup_reftotal_fork_probe", threadgroup_reftotal_fork_probe, METH_O, NULL},
    {"threadgroup_reftotal_probe", threadgroup_reftotal_probe, METH_VARARGS, NULL},
#endif
    {"threadgroup_intern", threadgroup_intern, METH_VARARGS, NULL},
    {"unicode_intern_dead_entry", unicode_intern_dead_entry, METH_NOARGS, NULL},
    {"threadgroup_immortal_brc", threadgroup_immortal_brc, METH_O, NULL},
    {"threadgroup_gc_brc_probe", threadgroup_gc_brc_probe, METH_VARARGS, NULL},
    {"threadgroup_unicode_cache_probe", threadgroup_unicode_cache_probe,
     METH_VARARGS, NULL},
    {"threadgroup_qsbr_probe", threadgroup_qsbr_probe, METH_VARARGS, NULL},
    {"test_qsbr_thread_states", test_qsbr_thread_states, METH_NOARGS, NULL},
    {"make_container_element", make_container_element, METH_O, NULL},
    {"container_element_calls", container_element_calls, METH_O, NULL},
    {"threadgroup_weakref_probe", threadgroup_weakref_probe, METH_VARARGS, NULL},
#ifdef WITH_MIMALLOC
    {"test_reentrant_allocation_heap", test_reentrant_allocation_heap, METH_NOARGS, NULL},
#endif
    {"threadgroup_allocation_probe", threadgroup_allocation_probe, METH_VARARGS, NULL},
    {"threadgroup_world_is_stopped", threadgroup_world_is_stopped, METH_NOARGS, NULL},
    {"test_gc_world_stop", test_gc_world_stop, METH_NOARGS, NULL},
    {"gc_traversal_world_stop_probe", gc_traversal_world_stop_probe, METH_O, NULL},
    {"test_gc_visit_world_stop", test_gc_visit_world_stop, METH_NOARGS, NULL},
    {"threadgroup_world_stop_probe", threadgroup_world_stop_probe, METH_VARARGS, NULL},
    {"threadgroup_freelist_probe", threadgroup_freelist_probe, METH_VARARGS, NULL},
    {"make_access_descriptor", make_access_descriptor, METH_NOARGS, NULL},
    {"access_descriptor_calls", access_descriptor_calls, METH_O, NULL},
    {"threadgroup_vm_probe", threadgroup_vm_probe, METH_VARARGS, NULL},
    {"threadgroup_return_probe", threadgroup_return_probe, METH_VARARGS, NULL},
    {"test_static_immutable_access", test_static_immutable_access, METH_NOARGS, NULL},
    {"threadgroup_access_probe", threadgroup_access_probe, METH_VARARGS, NULL},
    {"make_immutable_capsule", make_immutable_capsule, METH_NOARGS, NULL},
    {"check_main_group_lifetime", check_main_group_lifetime, METH_NOARGS, NULL},
    {"test_deferred_c_stack_ref", test_deferred_c_stack_ref, METH_NOARGS, NULL},
    {"check_deferred_shutdown", check_deferred_shutdown, METH_NOARGS, NULL},
    {"threadgroup_refcount_probe", threadgroup_refcount_probe, METH_VARARGS, NULL},
    {"test_threadgroup_refcount_overflow", test_threadgroup_refcount_overflow,
     METH_NOARGS, NULL},
    {"threadgroup_probe", threadgroup_probe, METH_VARARGS, NULL},
    {"threadgroup_watcher_clear_probe", threadgroup_watcher_clear_probe, METH_O, NULL},
    {"test_shared_keys_type_watcher", test_shared_keys_type_watcher, METH_O, NULL},
    {NULL, NULL},
};

int
_PyTestInternalCapi_Init_ThreadGroups(PyObject *module)
{
    return PyModule_AddFunctions(module, methods);
}
