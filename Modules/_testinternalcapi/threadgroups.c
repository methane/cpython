/* Exercise group scheduling without sharing Python functions or mutable
   Python containers between groups. */
#include "parts.h"
#include "pycore_lock.h"
#include "pycore_pystate.h"
#include "pycore_pythread.h"
#include "pycore_threadgroup.h"

struct group_probe {
    PyInterpreterState *interp;
    _PyThreadGroupState *state;
    PyObject *wrapper;
    PyEvent *events;
    uint8_t *flags;
    int index;
    int mode;
    PyTime_t timeout;
    int ok;
};

static void
group_probe_worker(void *arg)
{
    struct group_probe *probe = arg;
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

    if (probe->ok && probe->mode == 1) {
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
    if (!PyArg_ParseTuple(args, "O!id:threadgroup_probe", &PyTuple_Type,
                          &groups, &mode, &seconds)) {
        return NULL;
    }
    if (PyTuple_GET_SIZE(groups) != 2 || mode < 0 || mode > 2 ||
        !(seconds > 0.0 && seconds <= 300.0)) {
        PyErr_SetString(PyExc_ValueError, "invalid group probe arguments");
        return NULL;
    }

    PyInterpreterState *interp = PyInterpreterState_Get();
    PyEvent events[2] = {{0}, {0}};
    uint8_t flags[2] = {0, 0};
    struct group_probe probes[2] = {{0}, {0}};
    PyThread_handle_t handles[2];
    int started = 0;
    PyObject *result = NULL;
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
            .flags = flags,
            .index = i,
            .mode = mode,
            .timeout = (PyTime_t)(seconds * 1000000000.0),
        };
    }
    for (int i = 0; i < 2; i++) {
        PyThread_ident_t ident;
        if (PyThread_start_joinable_thread(group_probe_worker, &probes[i],
                                           &ident, &handles[i]) != 0) {
            PyErr_SetString(PyExc_RuntimeError, "failed to start group probe");
            goto done;
        }
        started++;
    }

done:
    /* The workers access stack storage. Join even on partial start failure. */
    Py_BEGIN_ALLOW_THREADS
    for (int i = 0; i < started; i++) {
        PyThread_join_thread(handles[i]);
    }
    Py_END_ALLOW_THREADS
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

static PyMethodDef methods[] = {
    {"threadgroup_probe", threadgroup_probe, METH_VARARGS, NULL},
    {NULL, NULL},
};

int
_PyTestInternalCapi_Init_ThreadGroups(PyObject *module)
{
    return PyModule_AddFunctions(module, methods);
}
