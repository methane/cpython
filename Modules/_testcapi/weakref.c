#include "parts.h"
#include "util.h"

/* Kept as a stable ABI symbol after its public declaration was removed. */
PyAPI_FUNC(PyObject *) PyWeakref_GetObject(PyObject *ref);


static PyObject *
pyweakref_getref(PyObject *module, PyObject *ref)
{
    NULLABLE(ref);
    PyObject *obj = UNINITIALIZED_PTR;
    int rc = PyWeakref_GetRef(ref, &obj);
    if (rc == -1 && PyErr_Occurred()) {
        assert(obj == NULL);
        return NULL;
    }
    if (obj == NULL) {
        return Py_BuildValue("i", rc);
    }
    else {
        assert(obj != UNINITIALIZED_PTR);
        return Py_BuildValue("iN", rc, obj);
    }
}

static PyObject *
pyweakref_getobject(PyObject *module, PyObject *ref)
{
    NULLABLE(ref);
    PyObject *obj = PyWeakref_GetObject(ref);
    if (obj == NULL) {
        return NULL;
    }
    return Py_NewRef(obj);
}

static PyObject *
pyweakref_isdead(PyObject *module, PyObject *obj)
{
    NULLABLE(obj);
    int rc = PyWeakref_IsDead(obj);
    if (rc == -1 && PyErr_Occurred()) {
        return NULL;
    }
    return PyLong_FromLong(rc);
}


static PyMethodDef test_methods[] = {
    {"pyweakref_getref", pyweakref_getref, METH_O},
    {"pyweakref_getobject", pyweakref_getobject, METH_O},
    {"pyweakref_isdead", pyweakref_isdead, METH_O},
    {NULL},
};

int
_PyTestCapi_Init_Weakref(PyObject *m)
{
    return PyModule_AddFunctions(m, test_methods);
}
