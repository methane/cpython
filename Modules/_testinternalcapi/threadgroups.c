/* Exercise group scheduling without sharing Python functions or mutable
   Python containers between groups. */
#include "parts.h"
#include "pycore_code.h"
#include "pycore_freelist.h"
#include "pycore_lock.h"
#include "pycore_object.h"
#include "pycore_object_deferred.h"
#include "pycore_pystate.h"
#include "pycore_pythread.h"
#include "pycore_stackref.h"
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

struct deferred_shutdown_probe {
    PyObject *container;
    int child_destroyed;
};

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

static PyType_Slot member_box_slots[] = {
    {Py_tp_dealloc, return_box_dealloc},
    {Py_tp_traverse, return_box_traverse},
    {Py_tp_members, return_box_members},
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
    "PyVectorcall_Call_keywords", NULL,
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
    int warmups;
    int trials;
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
    int warmups, trials = 1;
    if (!PyArg_ParseTuple(args, "O!OO!i|i:threadgroup_vm_probe", &PyCode_Type,
                          &code, &group, &PyTuple_Type, &source, &warmups, &trials)) {
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
        return PyErr_Format(PyExc_AssertionError, "VM reference acquisition probe failed");
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

static PyMethodDef methods[] = {
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
    {NULL, NULL},
};

int
_PyTestInternalCapi_Init_ThreadGroups(PyObject *module)
{
    return PyModule_AddFunctions(module, methods);
}
