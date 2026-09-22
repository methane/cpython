#include "parts.h"
#include "util.h"

typedef struct {
    PyObject_HEAD
    PyObject *value;
} LegacyGetAttr;

static int
legacy_getattr_traverse(PyObject *op, visitproc visit, void *arg)
{
    Py_VISIT(((LegacyGetAttr *)op)->value);
    return 0;
}

static int
legacy_getattr_clear(PyObject *op)
{
    Py_CLEAR(((LegacyGetAttr *)op)->value);
    return 0;
}

static void
legacy_getattr_dealloc(PyObject *op)
{
    PyObject_GC_UnTrack(op);
    legacy_getattr_clear(op);
    Py_TYPE(op)->tp_free(op);
}

static PyObject *
legacy_getattr(PyObject *op, char *name)
{
    PyObject *value = ((LegacyGetAttr *)op)->value;
    if (strcmp(name, "value") == 0 && value != NULL) {
        return Py_NewRef(value);
    }
    PyErr_SetString(PyExc_AttributeError, name);
    return NULL;
}

static PyTypeObject LegacyGetAttr_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_testcapi.LegacyGetAttr",
    .tp_basicsize = sizeof(LegacyGetAttr),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_getattr = legacy_getattr,
    .tp_traverse = legacy_getattr_traverse,
    .tp_clear = legacy_getattr_clear,
    .tp_dealloc = legacy_getattr_dealloc,
    .tp_free = PyObject_GC_Del,
};

static PyObject *
make_legacy_getattr(PyObject *self, PyObject *value)
{
    LegacyGetAttr *obj = PyObject_GC_New(LegacyGetAttr, &LegacyGetAttr_Type);
    if (obj == NULL) {
        return NULL;
    }
    obj->value = Py_NewRef(value);
    PyObject_GC_Track(obj);
    return (PyObject *)obj;
}


static PyObject *
return_tuple_item_unchecked(PyObject *self, PyObject *holder)
{
    if (!PyTuple_Check(holder) || PyTuple_GET_SIZE(holder) == 0) {
        PyErr_SetString(PyExc_TypeError, "expected a nonempty tuple");
        return NULL;
    }
    /* Deliberately rely on the call protocol to validate the native result. */
    return Py_NewRef(PyTuple_GET_ITEM(holder, 0));
}

/* Preserve a native result without a VM check on the result itself. */
static PyObject *
call_cfunction_return_in_tuple(PyObject *self, PyObject *args)
{
    PyObject *callable, *call_args;
    if (!PyArg_ParseTuple(args, "OO!:call_cfunction_return_in_tuple",
                          &callable, &PyTuple_Type, &call_args)) {
        return NULL;
    }
    if (!PyCFunction_Check(callable)) {
        PyErr_SetString(PyExc_TypeError, "expected a native callable");
        return NULL;
    }
    PyObject *result = PyObject_Call(callable, call_args, NULL);
    if (result == NULL) {
        return NULL;
    }
    PyObject *holder = PyTuple_Pack(1, result);
    Py_DECREF(result);
    return holder;
}

/* Test an API wrapper without generic call argument/result validation. */
static PyObject *
call_cfunction_raw_return_in_tuple(PyObject *self, PyObject *args)
{
    PyObject *callable, *call_args;
    if (!PyArg_ParseTuple(args, "OO!:call_cfunction_raw_return_in_tuple",
                          &callable, &PyTuple_Type, &call_args)) {
        return NULL;
    }
    if (!PyCFunction_Check(callable)) {
        PyErr_SetString(PyExc_TypeError, "expected a native callable");
        return NULL;
    }
    if (PyObject_CheckAccess(callable) == NULL ||
        PyObject_CheckAccess(call_args) == NULL) {
        return NULL;
    }
    PyCFunction function = PyCFunction_GET_FUNCTION(callable);
    PyObject *receiver = PyCFunction_GET_SELF(callable);
    Py_ssize_t nargs = PyTuple_GET_SIZE(call_args);
    PyObject *const *argv = ((PyTupleObject *)call_args)->ob_item;
    int flags = PyCFunction_GET_FLAGS(callable) &
        (METH_VARARGS | METH_FASTCALL | METH_NOARGS | METH_O |
         METH_KEYWORDS | METH_METHOD);
    if ((flags == METH_NOARGS && nargs != 0) ||
        (flags == METH_O && nargs != 1)) {
        PyErr_SetString(PyExc_TypeError, "incorrect native argument count");
        return NULL;
    }
    if (Py_EnterRecursiveCall(" in raw native test call")) {
        return NULL;
    }
    PyObject *result;
    switch (flags) {
        case METH_NOARGS:
            result = function(receiver, NULL);
            break;
        case METH_O:
            result = function(receiver, argv[0]);
            break;
        case METH_VARARGS:
            result = function(receiver, call_args);
            break;
        case METH_VARARGS | METH_KEYWORDS:
            result = _PyCFunctionWithKeywords_CAST(function)(receiver, call_args, NULL);
            break;
        case METH_FASTCALL:
            result = _PyCFunctionFast_CAST(function)(receiver, argv, nargs);
            break;
        case METH_FASTCALL | METH_KEYWORDS:
            result = _PyCFunctionFastWithKeywords_CAST(function)(receiver, argv, nargs, NULL);
            break;
        case METH_METHOD | METH_FASTCALL | METH_KEYWORDS:
            result = _Py_FUNC_CAST(PyCMethod, function)(
                receiver, PyCFunction_GET_CLASS(callable), argv, nargs, NULL);
            break;
        default:
            PyErr_SetString(PyExc_ValueError, "unsupported native calling convention");
            result = NULL;
    }
    Py_LeaveRecursiveCall();
    if (result == NULL) {
        return NULL;
    }
    /* Build the wrapper with the stealing macro so this raw helper can
       preserve an inaccessible native result for the caller to inspect. */
    PyObject *holder = PyTuple_New(1);
    if (holder == NULL) {
        Py_DECREF(result);
        return NULL;
    }
    PyTuple_SET_ITEM(holder, 0, result);
    return holder;
}

static PyObject *
object_getoptionalattr(PyObject *self, PyObject *args)
{
    PyObject *obj, *attr_name, *value = UNINITIALIZED_PTR;
    if (!PyArg_ParseTuple(args, "OO", &obj, &attr_name)) {
        return NULL;
    }
    NULLABLE(obj);
    NULLABLE(attr_name);

    switch (PyObject_GetOptionalAttr(obj, attr_name, &value)) {
        case -1:
            assert(value == NULL);
            return NULL;
        case 0:
            assert(value == NULL);
            return Py_NewRef(PyExc_AttributeError);
        case 1:
            return value;
        default:
            Py_FatalError("PyObject_GetOptionalAttr() returned invalid code");
            Py_UNREACHABLE();
    }
}

static PyObject *
object_getoptionalattrstring(PyObject *self, PyObject *args)
{
    PyObject *obj, *value = UNINITIALIZED_PTR;
    const char *attr_name;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "Oz#", &obj, &attr_name, &size)) {
        return NULL;
    }
    NULLABLE(obj);

    switch (PyObject_GetOptionalAttrString(obj, attr_name, &value)) {
        case -1:
            assert(value == NULL);
            return NULL;
        case 0:
            assert(value == NULL);
            return Py_NewRef(PyExc_AttributeError);
        case 1:
            return value;
        default:
            Py_FatalError("PyObject_GetOptionalAttrString() returned invalid code");
            Py_UNREACHABLE();
    }
}

static PyObject *
object_hasattrwitherror(PyObject *self, PyObject *args)
{
    PyObject *obj, *attr_name;
    if (!PyArg_ParseTuple(args, "OO", &obj, &attr_name)) {
        return NULL;
    }
    NULLABLE(obj);
    NULLABLE(attr_name);
    RETURN_INT(PyObject_HasAttrWithError(obj, attr_name));
}

static PyObject *
object_hasattrstringwitherror(PyObject *self, PyObject *args)
{
    PyObject *obj;
    const char *attr_name;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "Oz#", &obj, &attr_name, &size)) {
        return NULL;
    }
    NULLABLE(obj);
    RETURN_INT(PyObject_HasAttrStringWithError(obj, attr_name));
}

static PyObject *
mapping_getoptionalitemstring(PyObject *self, PyObject *args)
{
    PyObject *obj, *value = UNINITIALIZED_PTR;
    const char *attr_name;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "Oz#", &obj, &attr_name, &size)) {
        return NULL;
    }
    NULLABLE(obj);

    switch (PyMapping_GetOptionalItemString(obj, attr_name, &value)) {
        case -1:
            assert(value == NULL);
            return NULL;
        case 0:
            assert(value == NULL);
            return Py_NewRef(PyExc_KeyError);
        case 1:
            return value;
        default:
            Py_FatalError("PyMapping_GetOptionalItemString() returned invalid code");
            Py_UNREACHABLE();
    }
}

static PyObject *
mapping_getoptionalitem(PyObject *self, PyObject *args)
{
    PyObject *obj, *attr_name, *value = UNINITIALIZED_PTR;
    if (!PyArg_ParseTuple(args, "OO", &obj, &attr_name)) {
        return NULL;
    }
    NULLABLE(obj);
    NULLABLE(attr_name);

    switch (PyMapping_GetOptionalItem(obj, attr_name, &value)) {
        case -1:
            assert(value == NULL);
            return NULL;
        case 0:
            assert(value == NULL);
            return Py_NewRef(PyExc_KeyError);
        case 1:
            return value;
        default:
            Py_FatalError("PyMapping_GetOptionalItem() returned invalid code");
            Py_UNREACHABLE();
    }
}

static PyObject *
object_getiter(PyObject *self, PyObject *obj)
{
    return PyObject_GetIter(obj);
}

static PyObject *
object_getaiter(PyObject *self, PyObject *obj)
{
    return PyObject_GetAIter(obj);
}

static PyObject *
pyiter_next(PyObject *self, PyObject *iter)
{
    PyObject *item = PyIter_Next(iter);
    if (item == NULL && !PyErr_Occurred()) {
        Py_RETURN_NONE;
    }
    return item;
}

static PyObject *
pyiter_send(PyObject *self, PyObject *args)
{
    PyObject *iter, *arg, *result;
    if (!PyArg_ParseTuple(args, "OO", &iter, &arg)) {
        return NULL;
    }
    PySendResult status = PyIter_Send(iter, arg, &result);
    if (status == PYGEN_ERROR) {
        assert(result == NULL);
        assert(PyErr_Occurred());
        return NULL;
    }
    assert(result != NULL);
    assert(!PyErr_Occurred());
    return Py_BuildValue("iN", (int)status, result);
}

static PyObject *
pyiter_nextitem(PyObject *self, PyObject *iter)
{
    PyObject *item;
    int rc = PyIter_NextItem(iter, &item);
    if (rc < 0) {
        assert(PyErr_Occurred());
        assert(item == NULL);
        return NULL;
    }
    assert(!PyErr_Occurred());
    if (item == NULL) {
        Py_RETURN_NONE;
    }
    return item;
}


static PyObject *
sequence_fast_get_size(PyObject *self, PyObject *obj)
{
    NULLABLE(obj);
    return PyLong_FromSsize_t(PySequence_Fast_GET_SIZE(obj));
}


static PyObject *
sequence_fast_get_item(PyObject *self, PyObject *args)
{
    PyObject *obj;
    Py_ssize_t index;
    if (!PyArg_ParseTuple(args, "On", &obj, &index)) {
        return NULL;
    }
    NULLABLE(obj);
    return PySequence_Fast_GET_ITEM(obj, index);
}


static PyObject *
object_setattr_null_exc(PyObject *self, PyObject *args)
{
    PyObject *obj, *name, *exc;
    if (!PyArg_ParseTuple(args, "OOO", &obj, &name, &exc)) {
        return NULL;
    }

    PyErr_SetObject((PyObject*)Py_TYPE(exc), exc);
    if (PyObject_SetAttr(obj, name, NULL) < 0) {
        return NULL;
    }
    assert(PyErr_Occurred());
    return NULL;
}


static PyObject *
object_setattrstring_null_exc(PyObject *self, PyObject *args)
{
    PyObject *obj, *exc;
    const char *name;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "Oz#O", &obj, &name, &size, &exc)) {
        return NULL;
    }

    PyErr_SetObject((PyObject*)Py_TYPE(exc), exc);
    if (PyObject_SetAttrString(obj, name, NULL) < 0) {
        return NULL;
    }
    assert(PyErr_Occurred());
    return NULL;
}

static PyObject *
object_length_hint(PyObject *self, PyObject *arg)
{
    if (arg == Py_None) {
        arg = NULL;
    }
    Py_ssize_t result = PyObject_LengthHint(arg, 0);
    if (result < 0) {
        return NULL;
    }
    return PyLong_FromSsize_t(result);
}

static PyObject *
slice_unpack(PyObject *self, PyObject *arg)
{
    Py_ssize_t start, stop, step;
    if (PySlice_Unpack(arg, &start, &stop, &step) < 0) {
        return NULL;
    }
    return Py_BuildValue("(nnn)", start, stop, step);
}

static PyObject *
slice_getindices(PyObject *self, PyObject *args)
{
    PyObject *slice;
    Py_ssize_t length, start, stop, step;
    if (!PyArg_ParseTuple(args, "On", &slice, &length)) {
        return NULL;
    }
    if (PySlice_GetIndices(slice, length, &start, &stop, &step) < 0) {
        return NULL;
    }
    return Py_BuildValue("(nnn)", start, stop, step);
}

static PyObject *
memoryview_fromobject(PyObject *self, PyObject *arg)
{
    return PyMemoryView_FromObject(arg);
}

static PyObject *
memoryview_getcontiguous(PyObject *self, PyObject *arg)
{
    return PyMemoryView_GetContiguous(arg, PyBUF_READ, 'C');
}

static PyObject *
object_hash(PyObject *self, PyObject *arg)
{
    Py_hash_t result = PyObject_Hash(arg);
    if (result == -1 && PyErr_Occurred()) {
        return NULL;
    }
    return PyLong_FromSsize_t(result);
}

static PyObject *
object_is_true(PyObject *self, PyObject *arg)
{
    int result = PyObject_IsTrue(arg);
    if (result < 0) {
        return NULL;
    }
    return PyLong_FromLong(result);
}


static PyMethodDef test_methods[] = {
    {"return_tuple_item_unchecked", return_tuple_item_unchecked, METH_O},
    {"call_cfunction_return_in_tuple", call_cfunction_return_in_tuple, METH_VARARGS},
    {"call_cfunction_raw_return_in_tuple", call_cfunction_raw_return_in_tuple, METH_VARARGS},
    {"make_legacy_getattr", make_legacy_getattr, METH_O},
    {"object_getoptionalattr", object_getoptionalattr, METH_VARARGS},
    {"object_getoptionalattrstring", object_getoptionalattrstring, METH_VARARGS},
    {"object_hasattrwitherror", object_hasattrwitherror, METH_VARARGS},
    {"object_hasattrstringwitherror", object_hasattrstringwitherror, METH_VARARGS},
    {"mapping_getoptionalitem", mapping_getoptionalitem, METH_VARARGS},
    {"mapping_getoptionalitemstring", mapping_getoptionalitemstring, METH_VARARGS},

    {"PyObject_GetIter", object_getiter, METH_O},
    {"PyObject_GetAIter", object_getaiter, METH_O},
    {"PyIter_Next", pyiter_next, METH_O},
    {"PyIter_Send", pyiter_send, METH_VARARGS},
    {"PyIter_NextItem", pyiter_nextitem, METH_O},
    {"PyObject_LengthHint", object_length_hint, METH_O},
    {"PySlice_Unpack", slice_unpack, METH_O},
    {"PySlice_GetIndices", slice_getindices, METH_VARARGS},
    {"memoryview_fromobject", memoryview_fromobject, METH_O},
    {"memoryview_getcontiguous", memoryview_getcontiguous, METH_O},
    {"object_hash", object_hash, METH_O},
    {"object_is_true", object_is_true, METH_O},

    {"sequence_fast_get_size", sequence_fast_get_size, METH_O},
    {"sequence_fast_get_item", sequence_fast_get_item, METH_VARARGS},
    {"object_setattr_null_exc", object_setattr_null_exc, METH_VARARGS},
    {"object_setattrstring_null_exc", object_setattrstring_null_exc, METH_VARARGS},
    {NULL},
};

int
_PyTestCapi_Init_Abstract(PyObject *m)
{
    if (PyModule_AddType(m, &LegacyGetAttr_Type) < 0) {
        return -1;
    }
    if (PyModule_AddFunctions(m, test_methods) < 0) {
        return -1;
    }

    return 0;
}
