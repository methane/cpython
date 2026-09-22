#include "parts.h"
#include "util.h"

#include "frameobject.h"          // PyFrame_New()

static PyObject *
threadstate_as_capsule(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    /* The test must keep this thread alive until all inspections finish. */
    PyObject *capsule = PyCapsule_New(PyThreadState_Get(),
                                     "_testcapi.threadstate", NULL);
    if (capsule == NULL) {
        return NULL;
    }
    PyObject *holder = PyTuple_Pack(1, capsule);
    Py_DECREF(capsule);
    return holder;
}

static PyObject *
threadstate_frame_from_tuple(PyObject *self, PyObject *holder)
{
    if (!PyTuple_Check(holder) || PyTuple_GET_SIZE(holder) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected a one-capsule tuple");
        return NULL;
    }
    PyThreadState *tstate = PyCapsule_GetPointer(PyTuple_GET_ITEM(holder, 0),
                                                "_testcapi.threadstate");
    if (tstate == NULL) {
        return NULL;
    }
    PyObject *frame = (PyObject *)PyThreadState_GetFrame(tstate);
    if (frame == NULL) {
        if (PyErr_Occurred()) {
            return NULL;
        }
        Py_RETURN_NONE;
    }
    /* Do not let a VM return check mask a missing native access check. */
    PyObject *result = PyTuple_Pack(1, frame);
    Py_DECREF(frame);
    return result;
}


static PyObject *
frame_get_from_tuple(PyObject *self, PyObject *args)
{
    PyObject *holder;
    PyObject *name_holder = NULL;
    const char *operation;
    if (!PyArg_ParseTuple(args, "O!s|O!", &PyTuple_Type, &holder, &operation,
                         &PyTuple_Type, &name_holder)) {
        return NULL;
    }
    if (PyTuple_GET_SIZE(holder) != 1 ||
        !PyFrame_Check(PyTuple_GET_ITEM(holder, 0))) {
        PyErr_SetString(PyExc_TypeError, "expected a one-frame tuple");
        return NULL;
    }
    /* Deliberately bypass Python's element access checks to exercise the
       public C API's receiver validation. The tuple keeps the frame alive. */
    PyFrameObject *frame = (PyFrameObject *)PyTuple_GET_ITEM(holder, 0);
    if (strcmp(operation, "code") == 0) {
        return (PyObject *)PyFrame_GetCode(frame);
    }
    if (strcmp(operation, "lineno") == 0 || strcmp(operation, "lasti") == 0) {
        int position = strcmp(operation, "lineno") == 0 ?
                       PyFrame_GetLineNumber(frame) : PyFrame_GetLasti(frame);
        if (position < 0 && PyErr_Occurred()) {
            return NULL;
        }
        return PyLong_FromLong(position);
    }
    PyObject *result;
    if (strcmp(operation, "back") == 0) {
        result = (PyObject *)PyFrame_GetBack(frame);
    }
    else if (strcmp(operation, "locals") == 0) {
        result = PyFrame_GetLocals(frame);
    }
    else if (strcmp(operation, "globals") == 0) {
        result = PyFrame_GetGlobals(frame);
    }
    else if (strcmp(operation, "builtins") == 0) {
        result = PyFrame_GetBuiltins(frame);
    }
    else if (strcmp(operation, "generator") == 0) {
        result = PyFrame_GetGenerator(frame);
    }
    else if (strcmp(operation, "var") == 0) {
        if (name_holder != NULL && PyTuple_GET_SIZE(name_holder) != 1) {
            PyErr_SetString(PyExc_TypeError, "expected a one-name tuple");
            return NULL;
        }
        PyObject *name = name_holder == NULL ? PyUnicode_FromString("results") :
                        Py_NewRef(PyTuple_GET_ITEM(name_holder, 0));
        if (name == NULL) {
            return NULL;
        }
        result = PyFrame_GetVar(frame, name);
        Py_DECREF(name);
    }
    else if (strcmp(operation, "varstring") == 0) {
        result = PyFrame_GetVarString(frame, "results");
    }
    else {
        PyErr_SetString(PyExc_ValueError, "unknown frame operation");
        return NULL;
    }
    if (result == NULL && PyErr_Occurred()) {
        return NULL;
    }
    /* Do not let VM call-result validation mask a missing receiver check. */
    int present = result != NULL;
    Py_XDECREF(result);
    return PyBool_FromLong(present);
}


static PyObject *
frame_getlocals(PyObject *self, PyObject *frame)
{
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }
    return PyFrame_GetLocals((PyFrameObject *)frame);
}


static PyObject *
frame_getglobals(PyObject *self, PyObject *frame)
{
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }
    return PyFrame_GetGlobals((PyFrameObject *)frame);
}


static PyObject *
frame_getgenerator(PyObject *self, PyObject *frame)
{
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }
    return PyFrame_GetGenerator((PyFrameObject *)frame);
}


static PyObject *
frame_getbuiltins(PyObject *self, PyObject *frame)
{
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }
    return PyFrame_GetBuiltins((PyFrameObject *)frame);
}


static PyObject *
frame_getlasti(PyObject *self, PyObject *frame)
{
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }
    int lasti = PyFrame_GetLasti((PyFrameObject *)frame);
    if (lasti < 0) {
        assert(lasti == -1);
        if (PyErr_Occurred()) {
            return NULL;
        }
        Py_RETURN_NONE;
    }
    return PyLong_FromLong(lasti);
}


static PyObject *
frame_new(PyObject *self, PyObject *args)
{
    PyObject *code, *globals, *locals;
    if (!PyArg_ParseTuple(args, "OOO", &code, &globals, &locals)) {
        return NULL;
    }
    if (!PyCode_Check(code)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a code object");
        return NULL;
    }
    PyThreadState *tstate = PyThreadState_Get();

    return (PyObject *)PyFrame_New(tstate, (PyCodeObject *)code, globals, locals);
}


static PyObject *
frame_getvar(PyObject *self, PyObject *args)
{
    PyObject *frame, *name;
    if (!PyArg_ParseTuple(args, "OO", &frame, &name)) {
        return NULL;
    }
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }

    return PyFrame_GetVar((PyFrameObject *)frame, name);
}


static PyObject *
frame_getvarstring(PyObject *self, PyObject *args)
{
    PyObject *frame;
    const char *name;
    if (!PyArg_ParseTuple(args, "Oy", &frame, &name)) {
        return NULL;
    }
    if (!PyFrame_Check(frame)) {
        PyErr_SetString(PyExc_TypeError, "argument must be a frame");
        return NULL;
    }

    return PyFrame_GetVarString((PyFrameObject *)frame, name);
}


static PyMethodDef test_methods[] = {
    {"threadstate_as_capsule", threadstate_as_capsule, METH_NOARGS, NULL},
    {"threadstate_frame_from_tuple", threadstate_frame_from_tuple, METH_O, NULL},
    {"frame_get_from_tuple", frame_get_from_tuple, METH_VARARGS, NULL},
    {"frame_getlocals", frame_getlocals, METH_O, NULL},
    {"frame_getglobals", frame_getglobals, METH_O, NULL},
    {"frame_getgenerator", frame_getgenerator, METH_O, NULL},
    {"frame_getbuiltins", frame_getbuiltins, METH_O, NULL},
    {"frame_getlasti", frame_getlasti, METH_O, NULL},
    {"frame_new", frame_new, METH_VARARGS, NULL},
    {"frame_getvar", frame_getvar, METH_VARARGS, NULL},
    {"frame_getvarstring", frame_getvarstring, METH_VARARGS, NULL},
    {NULL},
};

int
_PyTestCapi_Init_Frame(PyObject *m)
{
    return PyModule_AddFunctions(m, test_methods);
}
