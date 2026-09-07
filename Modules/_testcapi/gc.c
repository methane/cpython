#include "parts.h"

static PyObject*
test_gc_control(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    int orig_enabled = PyGC_IsEnabled();
    const char* msg = "ok";
    int old_state;

    old_state = PyGC_Enable();
    msg = "Enable(1)";
    if (old_state != orig_enabled) {
        goto failed;
    }
    msg = "IsEnabled(1)";
    if (!PyGC_IsEnabled()) {
        goto failed;
    }

    old_state = PyGC_Disable();
    msg = "disable(2)";
    if (!old_state) {
        goto failed;
    }
    msg = "IsEnabled(2)";
    if (PyGC_IsEnabled()) {
        goto failed;
    }

    old_state = PyGC_Enable();
    msg = "enable(3)";
    if (old_state) {
        goto failed;
    }
    msg = "IsEnabled(3)";
    if (!PyGC_IsEnabled()) {
        goto failed;
    }

    if (!orig_enabled) {
        old_state = PyGC_Disable();
        msg = "disable(4)";
        if (old_state) {
            goto failed;
        }
        msg = "IsEnabled(4)";
        if (PyGC_IsEnabled()) {
            goto failed;
        }
    }

    Py_RETURN_NONE;

failed:
    /* Try to clean up if we can. */
    if (orig_enabled) {
        PyGC_Enable();
    } else {
        PyGC_Disable();
    }
    PyErr_Format(PyExc_ValueError, "GC control failed in %s", msg);
    return NULL;
}

static PyObject *
without_gc(PyObject *Py_UNUSED(self), PyObject *obj)
{
    PyTypeObject *tp = (PyTypeObject*)obj;
    if (!PyType_Check(obj) || !PyType_HasFeature(tp, Py_TPFLAGS_HEAPTYPE)) {
        return PyErr_Format(PyExc_TypeError, "heap type expected, got %R", obj);
    }
    if (PyType_IS_GC(tp)) {
        // Don't try this at home, kids:
        tp->tp_flags -= Py_TPFLAGS_HAVE_GC;
        tp->tp_free = PyObject_Free;
        tp->tp_traverse = NULL;
        tp->tp_clear = NULL;
    }
    assert(!PyType_IS_GC(tp));
    return Py_NewRef(obj);
}

static void
slot_tp_del(PyObject *self)
{
    PyObject *del, *res;

    /* Temporarily resurrect the object. */
    assert(Py_REFCNT(self) == 0);
    Py_SET_REFCNT(self, 1);

    /* Save the current exception, if any. */
    PyObject *exc = PyErr_GetRaisedException();

    PyObject *tp_del = PyUnicode_InternFromString("__tp_del__");
    if (tp_del == NULL) {
        PyErr_FormatUnraisable("Exception ignored while deallocating");
        PyErr_SetRaisedException(exc);
        return;
    }
    /* Execute __del__ method, if any. */
    del = _PyType_LookupRef(Py_TYPE(self), tp_del);
    Py_DECREF(tp_del);
    if (del != NULL) {
        res = PyObject_CallOneArg(del, self);
        Py_DECREF(del);
        if (res == NULL) {
            PyErr_FormatUnraisable("Exception ignored while calling "
                                   "deallocator %R", del);
        }
        else {
            Py_DECREF(res);
        }
    }

    /* Restore the saved exception. */
    PyErr_SetRaisedException(exc);

    /* Undo the temporary resurrection; can't use DECREF here, it would
     * cause a recursive call.
     */
    assert(Py_REFCNT(self) > 0);
    Py_SET_REFCNT(self, Py_REFCNT(self) - 1);
    if (Py_REFCNT(self) == 0) {
        /* this is the normal path out */
        return;
    }

    /* __del__ resurrected it!  Make it look like the original Py_DECREF
     * never happened.
     */
    {
        _Py_ResurrectReference(self);
    }
    assert(!PyType_IS_GC(Py_TYPE(self)) || PyObject_GC_IsTracked(self));
}

static PyObject *
with_tp_del(PyObject *self, PyObject *args)
{
    PyObject *obj;
    PyTypeObject *tp;

    if (!PyArg_ParseTuple(args, "O:with_tp_del", &obj))
        return NULL;
    tp = (PyTypeObject *) obj;
    if (!PyType_Check(obj) || !PyType_HasFeature(tp, Py_TPFLAGS_HEAPTYPE)) {
        PyErr_Format(PyExc_TypeError,
                     "heap type expected, got %R", obj);
        return NULL;
    }
    tp->tp_del = slot_tp_del;
    return Py_NewRef(obj);
}


struct gc_visit_state_basic {
    PyObject *target;
    int found;
};

static int
gc_visit_callback_basic(PyObject *obj, void *arg)
{
    struct gc_visit_state_basic *state = (struct gc_visit_state_basic *)arg;
    if (obj == state->target) {
        state->found = 1;
        return 0;
    }
    return 1;
}

static PyObject *
test_gc_visit_objects_basic(PyObject *Py_UNUSED(self),
                            PyObject *Py_UNUSED(ignored))
{
    PyObject *obj;
    struct gc_visit_state_basic state;

    obj = PyList_New(0);
    if (obj == NULL) {
        return NULL;
    }
    state.target = obj;
    state.found = 0;

    PyUnstable_GC_VisitObjects(gc_visit_callback_basic, &state);
    Py_DECREF(obj);
    if (!state.found) {
        PyErr_SetString(
             PyExc_AssertionError,
             "test_gc_visit_objects_basic: Didn't find live list");
         return NULL;
    }
    Py_RETURN_NONE;
}

static int
gc_call_no_args(const char *method)
{
    PyObject *gc = PyImport_ImportModule("gc");
    if (gc == NULL) {
        return -1;
    }
    PyObject *res = PyObject_CallMethod(gc, method, NULL);
    Py_DECREF(gc);
    if (res == NULL) {
        return -1;
    }
    Py_DECREF(res);
    return 0;
}

// gh-131740: frozen objects must be visited too.
static PyObject *
test_gc_visit_objects_frozen(PyObject *Py_UNUSED(self),
                             PyObject *Py_UNUSED(ignored))
{
    PyObject *obj;
    struct gc_visit_state_basic state;

    obj = PyList_New(0);
    if (obj == NULL) {
        return NULL;
    }
    if (gc_call_no_args("freeze") < 0) {
        Py_DECREF(obj);
        return NULL;
    }
    state.target = obj;
    state.found = 0;

    PyUnstable_GC_VisitObjects(gc_visit_callback_basic, &state);

    int err = gc_call_no_args("unfreeze");
    Py_DECREF(obj);
    if (err < 0) {
        return NULL;
    }
    if (!state.found) {
        PyErr_SetString(
             PyExc_AssertionError,
             "test_gc_visit_objects_frozen: Didn't find frozen list");
         return NULL;
    }
    Py_RETURN_NONE;
}

static int
gc_visit_callback_exit_early(PyObject *obj, void *arg)
 {
    int *visited_i = (int *)arg;
    (*visited_i)++;
    if (*visited_i == 2) {
        return 0;
    }
    return 1;
}

static PyObject *
test_gc_visit_objects_exit_early(PyObject *Py_UNUSED(self),
                                 PyObject *Py_UNUSED(ignored))
{
    int visited_i = 0;
    PyUnstable_GC_VisitObjects(gc_visit_callback_exit_early, &visited_i);
    if (visited_i != 2) {
        PyErr_SetString(
            PyExc_AssertionError,
            "test_gc_visit_objects_exit_early: did not exit when expected");
    }
    Py_RETURN_NONE;
}

typedef struct {
    PyObject_HEAD
} ObjExtraData;

static PyObject *
obj_extra_data_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    size_t extra_size = sizeof(PyObject *);
    PyObject *obj = PyUnstable_Object_GC_NewWithExtraData(type, extra_size);
    if (obj == NULL) {
        return PyErr_NoMemory();
    }
    PyObject_GC_Track(obj);
    return obj;
}

static PyObject **
obj_extra_data_get_extra_storage(PyObject *self)
{
    return (PyObject **)((char *)self + Py_TYPE(self)->tp_basicsize);
}

static PyObject *
obj_extra_data_get(PyObject *self, void *Py_UNUSED(ignored))
{
    PyObject **extra_storage = obj_extra_data_get_extra_storage(self);
    PyObject *value = *extra_storage;
    if (!value) {
        Py_RETURN_NONE;
    }
    return Py_NewRef(value);
}

static int
obj_extra_data_set(PyObject *self, PyObject *newval, void *Py_UNUSED(ignored))
{
    PyObject **extra_storage = obj_extra_data_get_extra_storage(self);
    Py_CLEAR(*extra_storage);
    if (newval) {
        *extra_storage = Py_NewRef(newval);
    }
    return 0;
}

static PyGetSetDef obj_extra_data_getset[] = {
    {"extra", obj_extra_data_get, obj_extra_data_set, NULL},
    {NULL}
};

static int
obj_extra_data_traverse(PyObject *self, visitproc visit, void *arg)
{
    PyObject **extra_storage = obj_extra_data_get_extra_storage(self);
    PyObject *value = *extra_storage;
    Py_VISIT(value);
    return 0;
}

static int
obj_extra_data_clear(PyObject *self)
{
    PyObject **extra_storage = obj_extra_data_get_extra_storage(self);
    Py_CLEAR(*extra_storage);
    return 0;
}

static void
obj_extra_data_dealloc(PyObject *self)
{
    PyTypeObject *tp = Py_TYPE(self);
    PyObject_GC_UnTrack(self);
    obj_extra_data_clear(self);
    tp->tp_free(self);
    Py_DECREF(tp);
}

static PyType_Slot ObjExtraData_Slots[] = {
    {Py_tp_getset, obj_extra_data_getset},
    {Py_tp_dealloc, obj_extra_data_dealloc},
    {Py_tp_traverse, obj_extra_data_traverse},
    {Py_tp_clear, obj_extra_data_clear},
    {Py_tp_new, obj_extra_data_new},
    {Py_tp_free, PyObject_GC_Del},
    {0, NULL},
};

static PyType_Spec ObjExtraData_TypeSpec = {
    .name = "_testcapi.ObjExtraData",
    .basicsize = sizeof(ObjExtraData),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    .slots = ObjExtraData_Slots,
};

#ifdef Py_EXPERIMENTAL_TRACING_GC
// Deliberately not exposed in the module dictionary: PyType_Ready must keep
// the metadata alive when only native code can reach the static type.
static PyTypeObject GCStaticType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_testcapi.GCStaticType",
    .tp_basicsize = sizeof(PyListObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    .tp_base = &PyList_Type,
};

static PyObject *
get_tracing_gc_static_type(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    if (PyType_Ready(&GCStaticType) < 0) {
        return NULL;
    }
    return Py_NewRef((PyObject *)&GCStaticType);
}

static PyObject *
set_tracing_gc_static_type_payload(PyObject *self, PyObject *value)
{
    if (PyType_Ready(&GCStaticType) < 0) {
        return NULL;
    }
    PyType_Modified(&GCStaticType);
    if (PyDict_SetItemString(GCStaticType.tp_dict, "payload", value) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

// A GC edge outside the managed allocator. Updating it need not dirty the
// owner's page; the nursery must still invoke this object's tp_traverse.
typedef struct {
    PyObject_HEAD
    PyObject **storage;
} GCExternalBuffer;

static int
external_buffer_traverse(PyObject *self, visitproc visit, void *arg)
{
    GCExternalBuffer *op = (GCExternalBuffer *)self;
    Py_VISIT(Py_TYPE(self));
    if (op->storage != NULL) {
        Py_VISIT(*op->storage);
    }
    return 0;
}

static int
external_buffer_clear(PyObject *self)
{
    GCExternalBuffer *op = (GCExternalBuffer *)self;
    if (op->storage != NULL) {
        Py_CLEAR(*op->storage);
    }
    return 0;
}

static void
external_buffer_dealloc(PyObject *self)
{
    PyTypeObject *type = Py_TYPE(self);
    PyObject_GC_UnTrack(self);
    external_buffer_clear(self);
    PyMem_RawFree(((GCExternalBuffer *)self)->storage);
    type->tp_free(self);
    Py_DECREF(type);
}

static PyObject *
external_buffer_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    GCExternalBuffer *op = (GCExternalBuffer *)type->tp_alloc(type, 0);
    if (op == NULL) {
        return NULL;
    }
    op->storage = PyMem_RawCalloc(1, sizeof(*op->storage));
    if (op->storage == NULL) {
        Py_DECREF(op);
        return PyErr_NoMemory();
    }
    return (PyObject *)op;
}

static PyObject *
external_buffer_get(PyObject *self, void *closure)
{
    PyObject *value;
    Py_BEGIN_CRITICAL_SECTION(self);
    PyObject *stored = *((GCExternalBuffer *)self)->storage;
    value = Py_NewRef(stored == NULL ? Py_None : stored);
    Py_END_CRITICAL_SECTION();
    return value;
}

static int
external_buffer_set(PyObject *self, PyObject *value, void *closure)
{
    Py_BEGIN_CRITICAL_SECTION(self);
    Py_XSETREF(*((GCExternalBuffer *)self)->storage, Py_XNewRef(value));
    Py_END_CRITICAL_SECTION();
    return 0;
}

static PyGetSetDef external_buffer_getset[] = {
    {"value", external_buffer_get, external_buffer_set, NULL, NULL},
    {NULL},
};

static PyType_Slot external_buffer_slots[] = {
    {Py_tp_new, external_buffer_new},
    {Py_tp_dealloc, external_buffer_dealloc},
    {Py_tp_traverse, external_buffer_traverse},
    {Py_tp_clear, external_buffer_clear},
    {Py_tp_getset, external_buffer_getset},
    {0, NULL},
};

static PyType_Spec external_buffer_spec = {
    .name = "_testcapi.GCExternalBuffer",
    .basicsize = sizeof(GCExternalBuffer),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = external_buffer_slots,
};

static PyObject *tracing_function_sink;
static PyObject *tracing_code_sink;

static int
tracing_function_watcher(PyFunction_WatchEvent event, PyFunctionObject *function,
                         PyObject *new_value)
{
    if (event == PyFunction_EVENT_DESTROY &&
        PyUnicode_CompareWithASCIIString(
            ((PyCodeObject *)function->func_code)->co_filename,
            "<tracing-watchers>") == 0)
    {
        return PyList_Append(tracing_function_sink, (PyObject *)function);
    }
    return 0;
}

static int
tracing_code_watcher(PyCodeEvent event, PyCodeObject *code)
{
    if (event == PY_CODE_EVENT_DESTROY &&
        PyUnicode_CompareWithASCIIString(code->co_filename,
                                         "<tracing-watchers>") == 0)
    {
        return PyList_Append(tracing_code_sink, (PyObject *)code);
    }
    return 0;
}

static PyObject *
test_tracing_gc_watcher_resurrection(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *functions = PyList_New(0);
    PyObject *codes = PyList_New(0);
    PyObject *globals = PyDict_New();
    int function_watcher = -1, code_watcher = -1;
    PyObject *result = NULL;
    if (functions == NULL || codes == NULL || globals == NULL) {
        goto done;
    }
    // The sinks are also held in this native frame throughout collection.
    tracing_function_sink = functions;
    tracing_code_sink = codes;
    function_watcher = PyFunction_AddWatcher(tracing_function_watcher);
    if (function_watcher < 0) {
        goto done;
    }
    code_watcher = PyCode_AddWatcher(tracing_code_watcher);
    if (code_watcher < 0) {
        goto done;
    }
    for (int i = 0; i < 100; i++) {
        PyObject *code = Py_CompileString("42", "<tracing-watchers>", Py_eval_input);
        if (code == NULL) {
            goto done;
        }
        PyObject *function = PyFunction_New(code, globals);
        Py_DECREF(code);
        if (function == NULL) {
            goto done;
        }
        Py_DECREF(function);
    }
    PyGC_Collect();
    if (PyErr_Occurred()) {
        goto done;
    }
    result = PyTuple_Pack(2, functions, codes);
done:
    if (code_watcher >= 0) {
        PyCode_ClearWatcher(code_watcher);
    }
    if (function_watcher >= 0) {
        PyFunction_ClearWatcher(function_watcher);
    }
    tracing_function_sink = NULL;
    tracing_code_sink = NULL;
    Py_XDECREF(functions);
    Py_XDECREF(codes);
    Py_XDECREF(globals);
    return result;
}

static PyObject *
test_tracing_gc_c_roots(PyObject *self, PyObject *callback)
{
    PyObject *roots[64] = {NULL};
    PyObject *result = NULL;
    for (int i = 0; i < 64; i++) {
        roots[i] = PyLong_FromLong(1000000 + i);
        if (roots[i] == NULL) {
            goto done;
        }
    }
    // These strong references exist only in native storage. The callback
    // may explicitly collect, or allocate until automatic GC runs.
    result = PyObject_CallNoArgs(callback);
    if (result == NULL) {
        goto done;
    }
    Py_CLEAR(result);
    for (int i = 0; i < 64; i++) {
        if (PyLong_AsLong(roots[i]) != 1000000 + i) {
            if (!PyErr_Occurred()) {
                PyErr_SetString(PyExc_AssertionError, "lost native GC root");
            }
            goto done;
        }
    }
    result = Py_NewRef(Py_None);
done:
    for (int i = 0; i < 64; i++) {
        Py_XDECREF(roots[i]);
    }
    return result;
}
#endif

static PyMethodDef test_methods[] = {
#ifdef Py_EXPERIMENTAL_TRACING_GC
    {"get_tracing_gc_static_type", get_tracing_gc_static_type, METH_NOARGS, NULL},
    {"set_tracing_gc_static_type_payload", set_tracing_gc_static_type_payload,
     METH_O, NULL},
    {"test_tracing_gc_watcher_resurrection", test_tracing_gc_watcher_resurrection,
     METH_NOARGS, NULL},
    {"test_tracing_gc_c_roots", test_tracing_gc_c_roots, METH_O, NULL},
#endif
    {"test_gc_control", test_gc_control, METH_NOARGS},
    {"test_gc_visit_objects_basic", test_gc_visit_objects_basic, METH_NOARGS, NULL},
    {"test_gc_visit_objects_frozen", test_gc_visit_objects_frozen, METH_NOARGS, NULL},
    {"test_gc_visit_objects_exit_early", test_gc_visit_objects_exit_early, METH_NOARGS, NULL},
    {"without_gc", without_gc, METH_O, NULL},
    {"with_tp_del", with_tp_del, METH_VARARGS, NULL},
    {NULL}
};

int _PyTestCapi_Init_GC(PyObject *mod)
{
#ifdef Py_EXPERIMENTAL_TRACING_GC
    PyObject *external_type = PyType_FromModuleAndSpec(mod, &external_buffer_spec, NULL);
    if (external_type == NULL) {
        return -1;
    }
    if (PyModule_AddObjectRef(mod, "GCExternalBuffer", external_type) < 0) {
        Py_DECREF(external_type);
        return -1;
    }
    Py_DECREF(external_type);
#endif
    if (PyModule_AddFunctions(mod, test_methods) < 0) {
        return -1;
    }
    if (PyModule_AddFunctions(mod, test_methods) < 0) {
        return -1;
    }

    PyObject *ObjExtraData_Type = PyType_FromModuleAndSpec(
        mod, &ObjExtraData_TypeSpec, NULL);
    if (ObjExtraData_Type == 0) {
        return -1;
    }
    int ret = PyModule_AddType(mod, (PyTypeObject*)ObjExtraData_Type);
    Py_DECREF(ObjExtraData_Type);
    if (ret < 0) {
        return ret;
    }

    return 0;
}
