/* Exercise group scheduling without sharing Python functions or mutable
   Python containers between groups. */
#include "parts.h"
#include "pycore_lock.h"
#include "pycore_object.h"
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

static PyMethodDef methods[] = {
    {"threadgroup_refcount_probe", threadgroup_refcount_probe, METH_VARARGS, NULL},
    {"test_threadgroup_refcount_overflow", test_threadgroup_refcount_overflow,
     METH_NOARGS, NULL},
    {"threadgroup_probe", threadgroup_probe, METH_VARARGS, NULL},
    {NULL, NULL},
};

int
_PyTestInternalCapi_Init_ThreadGroups(PyObject *module)
{
    return PyModule_AddFunctions(module, methods);
}
