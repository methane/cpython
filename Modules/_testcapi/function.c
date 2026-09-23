#include "parts.h"
#include "util.h"


static PyObject *
function_get_code(PyObject *self, PyObject *func)
{
    PyObject *code = PyFunction_GetCode(func);
    if (code != NULL) {
        return Py_NewRef(code);
    } else {
        return NULL;
    }
}


static PyObject *
function_get_globals(PyObject *self, PyObject *func)
{
    PyObject *globals = PyFunction_GetGlobals(func);
    if (globals != NULL) {
        return Py_NewRef(globals);
    } else {
        return NULL;
    }
}


static PyObject *
function_get_module(PyObject *self, PyObject *func)
{
    PyObject *module = PyFunction_GetModule(func);
    if (module != NULL) {
        return Py_NewRef(module);
    } else {
        return NULL;
    }
}


static PyObject *
function_get_defaults(PyObject *self, PyObject *func)
{
    PyObject *defaults = PyFunction_GetDefaults(func);
    if (defaults != NULL) {
        return Py_NewRef(defaults);
    } else if (PyErr_Occurred()) {
        return NULL;
    } else {
        Py_RETURN_NONE;  // This can happen when `defaults` are set to `None`
    }
}


static PyObject *
function_set_defaults(PyObject *self, PyObject *args)
{
    PyObject *func = NULL, *defaults = NULL;
    if (!PyArg_ParseTuple(args, "OO", &func, &defaults)) {
        return NULL;
    }
    int result = PyFunction_SetDefaults(func, defaults);
    if (result == -1)
        return NULL;
    Py_RETURN_NONE;
}


static PyObject *
function_get_kw_defaults(PyObject *self, PyObject *func)
{
    PyObject *defaults = PyFunction_GetKwDefaults(func);
    if (defaults != NULL) {
        return Py_NewRef(defaults);
    } else if (PyErr_Occurred()) {
        return NULL;
    } else {
        Py_RETURN_NONE;  // This can happen when `kwdefaults` are set to `None`
    }
}


static PyObject *
function_set_kw_defaults(PyObject *self, PyObject *args)
{
    PyObject *func = NULL, *defaults = NULL;
    if (!PyArg_ParseTuple(args, "OO", &func, &defaults)) {
        return NULL;
    }
    int result = PyFunction_SetKwDefaults(func, defaults);
    if (result == -1)
        return NULL;
    Py_RETURN_NONE;
}


static PyObject *
function_get_closure(PyObject *self, PyObject *func)
{
    PyObject *closure = PyFunction_GetClosure(func);
    if (closure != NULL) {
        return Py_NewRef(closure);
    } else if (PyErr_Occurred()) {
        return NULL;
    } else {
        Py_RETURN_NONE;  // This can happen when `closure` is set to `None`
    }
}


static PyObject *
function_set_closure(PyObject *self, PyObject *args)
{
    PyObject *func = NULL, *closure = NULL;
    if (!PyArg_ParseTuple(args, "OO", &func, &closure)) {
        return NULL;
    }
    int result = PyFunction_SetClosure(func, closure);
    if (result == -1) {
        return NULL;
    }
    Py_RETURN_NONE;
}


static PyObject *
function_get_annotations(PyObject *self, PyObject *func)
{
    return Py_XNewRef(PyFunction_GetAnnotations(func));
}


static PyObject *
function_set_annotations(PyObject *self, PyObject *args)
{
    PyObject *func, *annotations;
    if (!PyArg_ParseTuple(args, "OO", &func, &annotations)) {
        return NULL;
    }
    if (PyFunction_SetAnnotations(func, annotations) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}


static PyObject *
function_set_dict(PyObject *self, PyObject *args)
{
    PyObject *func, *dict;
    if (!PyArg_ParseTuple(args, "OO", &func, &dict)) {
        return NULL;
    }
    if (PyObject_GenericSetDict(func, dict, NULL) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}


static PyObject *
function_set_from_tuples(PyObject *self, PyObject *args)
{
    PyObject *receiver, *value_holder;
    const char *name;
    int native = 0;
    if (!PyArg_ParseTuple(args, "OOs|p:function_set_from_tuples",
                          &receiver, &value_holder, &name, &native)) {
        return NULL;
    }
    if (!PyTuple_Check(receiver) || PyTuple_GET_SIZE(receiver) != 1 ||
        !PyTuple_Check(value_holder) || PyTuple_GET_SIZE(value_holder) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected two one-item tuples");
        return NULL;
    }
    /* Check references acquired from the heap before entering the setter. */
    PyObject *func = PyTuple_GetItem(receiver, 0);
    if (func == NULL) {
        return NULL;
    }
    PyObject *value = PyTuple_GetItem(value_holder, 0);
    if (value == NULL) {
        return NULL;
    }
    int result;
    if (!native) {
        result = PyObject_SetAttrString(func, name, value);
    }
    else if (strcmp(name, "__defaults__") == 0) {
        result = PyFunction_SetDefaults(func, value);
    }
    else if (strcmp(name, "__kwdefaults__") == 0) {
        result = PyFunction_SetKwDefaults(func, value);
    }
    else if (strcmp(name, "__closure__") == 0) {
        result = PyFunction_SetClosure(func, value);
    }
    else if (strcmp(name, "__annotations__") == 0) {
        result = PyFunction_SetAnnotations(func, value);
    }
    else if (strcmp(name, "__dict__") == 0) {
        result = PyObject_GenericSetDict(func, value, NULL);
    }
    else {
        PyErr_SetString(PyExc_ValueError, "unknown native function setter");
        return NULL;
    }
    if (result < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
cell_get(PyObject *self, PyObject *cell)
{
    PyObject *value = PyCell_Get(cell);
    if (value == NULL && !PyErr_Occurred()) {
        Py_RETURN_NONE;
    }
    return value;
}

static PyObject *
cell_get_from_tuple(PyObject *self, PyObject *holder)
{
    if (!PyTuple_Check(holder) || PyTuple_GET_SIZE(holder) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected a one-item tuple");
        return NULL;
    }
    /* Acquire the receiver without a Python subscription access check. */
    return cell_get(self, PyTuple_GET_ITEM(holder, 0));
}

static PyObject *
cell_set(PyObject *self, PyObject *args)
{
    PyObject *cell, *value = NULL;
    if (!PyArg_ParseTuple(args, "O|O:cell_set", &cell, &value)) {
        return NULL;
    }
    if (PyCell_Set(cell, value) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
cell_set_from_tuple(PyObject *self, PyObject *args)
{
    PyObject *cell, *holder;
    if (!PyArg_ParseTuple(args, "OO:cell_set_from_tuple", &cell, &holder)) {
        return NULL;
    }
    if (!PyTuple_Check(holder) || PyTuple_GET_SIZE(holder) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected a one-item tuple");
        return NULL;
    }
    /* This helper deliberately installs a foreign value so the tests can
       exercise reads from a cell.  PyCell_Set() quite correctly rejects the
       value at its public API boundary; use the legacy raw macro here after
       checking the cell receiver instead. */
    if (PyObject_CheckAccess(cell) == NULL || !PyCell_Check(cell)) {
        if (!PyErr_Occurred()) {
            PyErr_BadInternalCall();
        }
        return NULL;
    }
    PyObject *value = PyTuple_GET_ITEM(holder, 0);
    Py_INCREF(value);
    PyObject *old_value = PyCell_GET(cell);
    PyCell_SET(cell, value);
    Py_XDECREF(old_value);
    Py_RETURN_NONE;
}

static PyObject *
cell_mutate_from_tuple(PyObject *self, PyObject *args)
{
    PyObject *holder, *value = NULL;
    const char *operation;
    if (!PyArg_ParseTuple(args, "Os|O:cell_mutate_from_tuple",
                          &holder, &operation, &value)) {
        return NULL;
    }
    if (!PyTuple_Check(holder) || PyTuple_GET_SIZE(holder) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected a one-item tuple");
        return NULL;
    }
    PyObject *cell = PyTuple_GetItem(holder, 0);
    if (cell == NULL) {
        return NULL;
    }
    int result;
    if (strcmp(operation, "attribute") == 0) {
        result = PyObject_SetAttrString(cell, "cell_contents", value);
    }
    else if (strcmp(operation, "native") == 0) {
        result = PyCell_Set(cell, value);
    }
    else {
        PyErr_SetString(PyExc_ValueError, "unknown cell mutation operation");
        return NULL;
    }
    if (result < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
cell_set_raw(PyObject *self, PyObject *args)
{
    PyObject *cell, *value = NULL;
    if (!PyArg_ParseTuple(args, "O|O:cell_set_raw", &cell, &value)) {
        return NULL;
    }
    if (!PyCell_Check(cell)) {
        PyErr_SetString(PyExc_TypeError, "expected a cell");
        return NULL;
    }
    if (PyObject_CheckAccess(cell) == NULL) {
        return NULL;
    }
    /* Like other unchecked C API tests, this requires exclusive access to
       the cell. Exercise the raw setter's own mutation notification. */
    PyObject *old = PyCell_GET(cell);
    PyCell_SET(cell, Py_XNewRef(value));
    Py_XDECREF(old);
    Py_RETURN_NONE;
}

static PyMethodDef test_methods[] = {
    {"function_set_from_tuples", function_set_from_tuples, METH_VARARGS, NULL},
    {"cell_set", cell_set, METH_VARARGS, NULL},
    {"cell_mutate_from_tuple", cell_mutate_from_tuple, METH_VARARGS, NULL},
    {"cell_set_from_tuple", cell_set_from_tuple, METH_VARARGS, NULL},
    {"cell_set_raw", cell_set_raw, METH_VARARGS, NULL},
    {"cell_get", cell_get, METH_O, NULL},
    {"cell_get_from_tuple", cell_get_from_tuple, METH_O, NULL},
    {"function_get_code", function_get_code, METH_O, NULL},
    {"function_get_globals", function_get_globals, METH_O, NULL},
    {"function_get_module", function_get_module, METH_O, NULL},
    {"function_get_defaults", function_get_defaults, METH_O, NULL},
    {"function_set_defaults", function_set_defaults, METH_VARARGS, NULL},
    {"function_get_kw_defaults", function_get_kw_defaults, METH_O, NULL},
    {"function_set_kw_defaults", function_set_kw_defaults, METH_VARARGS, NULL},
    {"function_get_closure", function_get_closure, METH_O, NULL},
    {"function_set_closure", function_set_closure, METH_VARARGS, NULL},
    {"function_get_annotations", function_get_annotations, METH_O, NULL},
    {"function_set_dict", function_set_dict, METH_VARARGS, NULL},
    {"function_set_annotations", function_set_annotations, METH_VARARGS, NULL},
    {NULL},
};

int
_PyTestCapi_Init_Function(PyObject *m)
{
    return PyModule_AddFunctions(m, test_methods);
}
