/* Thread module */
/* Interface to Sjoerd's portable C thread library */

#include "Python.h"
#include "pycore_dict.h"          // _PyDict_SynchronizeNamespace()
#include "pycore_fileutils.h"     // _PyFile_Flush
#include "pycore_interp.h"        // _PyInterpreterState.threads.count
#include "pycore_lock.h"
#include "pycore_modsupport.h"    // _PyArg_NoKeywords()
#include "pycore_moduleobject.h"  // _PyModule_GetState()
#include "pycore_object.h"        // _PyObject_CheckMutable()
#include "pycore_parking_lot.h"
#include "pycore_object_deferred.h" // _PyObject_SetDeferredRefcount()
#include "pycore_pylifecycle.h"
#include "pycore_pystate.h"       // _PyThreadState_SetCurrent()
#include "pycore_time.h"          // _PyTime_FromSeconds()
#include "pycore_tuple.h"         // _PyTuple_FromPairSteal
#include "pycore_weakref.h"       // _PyWeakref_GET_REF()

#include <stddef.h>               // offsetof()
#ifdef HAVE_SIGNAL_H
#  include <signal.h>             // SIGINT
#endif

// ThreadError is just an alias to PyExc_RuntimeError
#define ThreadError PyExc_RuntimeError

// Forward declarations
static struct PyModuleDef thread_module;

// Module state
typedef struct {
    PyTypeObject *excepthook_type;
    PyTypeObject *lock_type;
    PyTypeObject *rlock_type;
    PyTypeObject *compound_lock_type;
    PyTypeObject *local_type;
    PyTypeObject *local_dummy_type;
    PyTypeObject *thread_handle_type;
    PyTypeObject *thread_base_type;
    PyTypeObject *threadgroup_type;
    PyTypeObject *transferbox_type;
    PyTypeObject *channel_queue_type;
    PyObject *copy_function;

    // Linked list of handles to all non-daemon threads created by the
    // threading module. We wait for these to finish at shutdown.
    struct llist_node shutdown_handles;
} thread_module_state;

typedef struct {
    PyObject_HEAD
    _PyThreadGroupState *state;
    PyObject *name;
    int64_t interpreter_id;
} threadgroupobject;

static PyObject *
threadgroup_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"name", NULL};
    PyObject *name = Py_None;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|O:ThreadGroup", keywords,
                                    &name)) {
        return NULL;
    }
    if (name != Py_None && !PyUnicode_Check(name)) {
        PyErr_SetString(PyExc_TypeError, "name must be a str or None");
        return NULL;
    }
    threadgroupobject *self = (threadgroupobject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }
    self->state = _PyThreadGroup_New(_PyInterpreterState_GET());
    if (self->state == NULL) {
        Py_DECREF(self);
        return PyErr_NoMemory();
    }
    self->name = name == Py_None ? Py_NewRef(name) : PyUnicode_FromObject(name);
    if (self->name == NULL) {
        Py_DECREF(self);
        return NULL;
    }
    if (self->name != Py_None) {
        Py_ssize_t length = PyUnicode_GET_LENGTH(self->name);
        if ((size_t)length > SIZE_MAX / sizeof(Py_UCS4) - 1) {
            Py_DECREF(self);
            return PyErr_NoMemory();
        }
        self->state->name = PyMem_RawMalloc((length + 1) * sizeof(Py_UCS4));
        if (self->state->name == NULL) {
            Py_DECREF(self);
            return PyErr_NoMemory();
        }
        if (PyUnicode_AsUCS4(self->name, self->state->name, length + 1, 1) == NULL) {
            Py_DECREF(self);
            return NULL;
        }
        self->state->name_length = length;
    }
    self->interpreter_id = PyInterpreterState_GetID(_PyInterpreterState_GET());
    if (PyObject_DeclareImmutable((PyObject *)self) < 0) {
        Py_DECREF(self);
        return NULL;
    }
#ifdef Py_GIL_DISABLED
    _PyObject_SetMaybeWeakref((PyObject *)self);
#endif
    PyMutex_LockFlags(&self->state->holder_mutex, 0);
    self->state->wrapper = (PyObject *)self;
    PyMutex_Unlock(&self->state->holder_mutex);
    return (PyObject *)self;
}

static void
threadgroup_dealloc(PyObject *op)
{
    threadgroupobject *self = (threadgroupobject *)op;
    PyTypeObject *type = Py_TYPE(op);
    PyObject_GC_UnTrack(op);
    if (self->state != NULL) {
        PyMutex_LockFlags(&self->state->holder_mutex, 0);
        if (self->state->wrapper == op) {
            self->state->wrapper = NULL;
        }
        PyMutex_Unlock(&self->state->holder_mutex);
        _PyThreadGroup_Decref(self->state);
    }
    Py_XDECREF(self->name);
    type->tp_free(op);
    Py_DECREF(type);
}

PyObject *
_PyThreadGroup_GetObject(PyInterpreterState *interp, uint32_t id)
{
    assert(interp == _PyInterpreterState_GET());
    _PyThreadGroupState *group = _PyThreadGroup_Find(interp, id);
    if (group == NULL) {
        PyErr_SetString(PyExc_ValueError, "unknown ThreadGroup owner ID");
        return NULL;
    }
    PyMutex_LockFlags(&group->holder_mutex, 0);
    PyObject *existing = group->wrapper;
    if (existing != NULL && !_Py_TryIncref(existing)) {
        existing = NULL;
    }
    PyMutex_Unlock(&group->holder_mutex);
    if (existing != NULL) {
        _PyThreadGroup_Decref(group);
        return existing;
    }
    if (interp->main_threadgroup_object == NULL) {
        _PyThreadGroup_Decref(group);
        PyErr_SetString(PyExc_RuntimeError, "ThreadGroup type is unavailable");
        return NULL;
    }
    PyTypeObject *type = Py_TYPE(interp->main_threadgroup_object);
    threadgroupobject *wrapper = (threadgroupobject *)type->tp_alloc(type, 0);
    if (wrapper == NULL) {
        _PyThreadGroup_Decref(group);
        return NULL;
    }
    wrapper->state = group;  /* Transfer the lookup reference. */
    wrapper->interpreter_id = PyInterpreterState_GetID(interp);
    wrapper->name = group->name_length < 0 ? Py_NewRef(Py_None) :
        PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, group->name,
                                 group->name_length);
    if (wrapper->name == NULL ||
        PyObject_DeclareImmutable((PyObject *)wrapper) < 0) {
        Py_DECREF(wrapper);
        return NULL;
    }

    /* Allocation can run Python and another thread can publish a wrapper.
       Only one live wrapper is published for a scheduler. */
#ifdef Py_GIL_DISABLED
    _PyObject_SetMaybeWeakref((PyObject *)wrapper);
#endif
    PyMutex_LockFlags(&group->holder_mutex, 0);
    existing = group->wrapper;
    if (existing != NULL && !_Py_TryIncref(existing)) {
        existing = NULL;
    }
    if (existing == NULL) {
        group->wrapper = (PyObject *)wrapper;
    }
    PyMutex_Unlock(&group->holder_mutex);
    if (existing != NULL) {
        Py_DECREF(wrapper);
        return existing;
    }
    return (PyObject *)wrapper;
}

static int
threadgroup_traverse(PyObject *op, visitproc visit, void *arg)
{
    threadgroupobject *self = (threadgroupobject *)op;
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(self->name);
    return 0;
}

static PyObject *
threadgroup_repr(PyObject *op)
{
    threadgroupobject *self = (threadgroupobject *)op;
    if (self->name == Py_None) {
        return PyUnicode_FromString("<ThreadGroup>");
    }
    return PyUnicode_FromFormat("<ThreadGroup %R>", self->name);
}

static PyMemberDef threadgroup_members[] = {
    {"name", Py_T_OBJECT_EX, offsetof(threadgroupobject, name), Py_READONLY},
    {NULL},
};

static PyType_Slot threadgroup_slots[] = {
    {Py_tp_new, threadgroup_new},
    {Py_tp_dealloc, threadgroup_dealloc},
    {Py_tp_traverse, threadgroup_traverse},
    {Py_tp_repr, threadgroup_repr},
    {Py_tp_members, threadgroup_members},
    {Py_tp_doc, "ThreadGroup(name=None)\n--\n\n"
                "A group of threads whose Python execution is serialized."},
    {0, NULL},
};

static PyType_Spec threadgroup_spec = {
    .name = "threading.ThreadGroup",
    .basicsize = sizeof(threadgroupobject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_HAVE_GC,
    .slots = threadgroup_slots,
};

typedef struct {
    PyObject_HEAD
    _PyProtectiveMutexState *state;
} lockobject;

#define lockobject_CAST(op) ((lockobject *)(op))

typedef struct {
    PyObject_HEAD
    _PyProtectiveMutexState *state;
} rlockobject;

#define rlockobject_CAST(op) ((rlockobject *)(op))

typedef struct compound_context {
    struct compound_context *next;
    uint32_t group;
    uint64_t thread;
} compound_context;

typedef struct {
    PyObject_HEAD
    PyObject *locks;
    compound_context *contexts;
} compoundlockobject;

enum {
    LOCK_MANUAL,
    LOCK_CONTEXT,
    LOCK_COMPOUND_CONTEXT,
};

static PyObject *lock_add(PyObject *, PyObject *);

static inline thread_module_state*
get_thread_state(PyObject *module)
{
    void *state = _PyModule_GetState(module);
    assert(state != NULL);
    return (thread_module_state *)state;
}

static inline thread_module_state*
get_thread_state_by_cls(PyTypeObject *cls)
{
    // Use PyType_GetModuleByDef() to handle (R)Lock subclasses.
    PyObject *module = PyType_GetModuleByDef(cls, &thread_module);
    if (module == NULL) {
        return NULL;
    }
    return get_thread_state(module);
}

typedef struct {
    PyObject_HEAD
    PyObject *value;
    PyObject *sink;
} transferboxobject;

static int
transferbox_check_sink(PyTypeObject *type, PyObject *sink)
{
    thread_module_state *state = get_thread_state_by_cls(type);
    if (state == NULL) {
        return -1;
    }
    if (sink == NULL) {
        PyErr_SetString(PyExc_TypeError, "cannot delete sink");
        return -1;
    }
    if (sink == Py_None) {
        return 0;
    }
    if (!Py_IS_TYPE(sink, state->threadgroup_type)) {
        PyErr_SetString(PyExc_TypeError, "sink must be a ThreadGroup or None");
        return -1;
    }
    if (((threadgroupobject *)sink)->interpreter_id !=
        PyInterpreterState_GetID(_PyInterpreterState_GET())) {
        PyErr_SetString(PyExc_ValueError, "sink belongs to another interpreter");
        return -1;
    }
    return 0;
}

static PyObject *
transferbox_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"obj", "sink", NULL};
    PyObject *obj, *sink = Py_None;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|O:TransferBox", keywords,
                                    &obj, &sink)) {
        return NULL;
    }
    if (transferbox_check_sink(type, sink) < 0) {
        return NULL;
    }
    if (PyObject_CheckAccess(obj) == NULL) {
        return NULL;
    }
    PyObject *value;
    if (_Py_atomic_load_uint8(&obj->ob_shareable) == _Py_SHAREABLE_LOCAL) {
        thread_module_state *state = get_thread_state_by_cls(type);
        if (state == NULL) {
            return NULL;
        }
        if (state->copy_function == NULL) {
            PyErr_SetString(PyExc_RuntimeError,
                            "threading has not initialized copy support");
            return NULL;
        }
        value = PyObject_CallOneArg(state->copy_function, obj);
        if (value == NULL) {
            return NULL;
        }
        if (PyObject_CheckAccess(value) == NULL) {
            Py_DECREF(value);
            return NULL;
        }
        if (_Py_atomic_load_uint8(&value->ob_shareable) == _Py_SHAREABLE_LOCAL &&
            (value == obj || !_PyObject_IsUniquelyReferenced(value))) {
            Py_DECREF(value);
            PyErr_SetString(PyExc_TypeError,
                            "copy must return an unaliased local object");
            return NULL;
        }
    }
    else {
        value = Py_NewRef(obj);
    }
    transferboxobject *self = (transferboxobject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        Py_DECREF(value);
        return NULL;
    }
    self->sink = Py_NewRef(sink);
    self->value = value;
    if (PyObject_DeclareSynchronized((PyObject *)self) < 0) {
        Py_DECREF(self);
        return NULL;
    }
    if (_Py_atomic_load_uint8(&value->ob_shareable) == _Py_SHAREABLE_LOCAL) {
        _Py_atomic_store_uint32_relaxed(&value->ob_owner_id, 0);
    }
    return (PyObject *)self;
}

static PyObject *
transferbox_claim(PyObject *op, PyObject *Py_UNUSED(ignored))
{
    transferboxobject *self = (transferboxobject *)op;
    PyObject *value = NULL;
    int wrong_sink = 0;
    int access_error = 0;
    _PyThreadGroupState *group = _PyThreadState_GET()->threadgroup;
    Py_BEGIN_CRITICAL_SECTION(op);
    if (self->value != NULL) {
        if (self->sink != Py_None &&
            ((threadgroupobject *)self->sink)->state != group) {
            wrong_sink = 1;
        }
        else {
            PyObject *candidate = self->value;
            int local = (_Py_atomic_load_uint8(&candidate->ob_shareable) ==
                         _Py_SHAREABLE_LOCAL);
            if (!local && PyObject_CheckAccess(candidate) == NULL) {
                access_error = 1;
            }
            else {
                value = candidate;
                self->value = NULL;
                if (local) {
                    _Py_atomic_store_uint32_relaxed(&value->ob_owner_id, group->id);
                }
            }
        }
    }
    Py_END_CRITICAL_SECTION();
    if (value == NULL && !access_error) {
        PyErr_SetString(PyExc_ValueError, wrong_sink ?
                        "TransferBox is addressed to another ThreadGroup" :
                        "TransferBox has already been claimed");
    }
    return value;
}

static int
transferbox_traverse(PyObject *op, visitproc visit, void *arg)
{
    transferboxobject *self = (transferboxobject *)op;
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(self->value);
    Py_VISIT(self->sink);
    return 0;
}

static int
transferbox_clear(PyObject *op)
{
    transferboxobject *self = (transferboxobject *)op;
    PyObject *value = self->value;
    self->value = NULL;
    if (value != NULL &&
        _Py_atomic_load_uint8(&value->ob_shareable) == _Py_SHAREABLE_LOCAL &&
        _Py_atomic_load_uint32_relaxed(&value->ob_owner_id) == 0) {
        // An abandoned value is adopted before releasing its last reference.
        _Py_atomic_store_uint32_relaxed(&value->ob_owner_id,
                                        _PyThreadState_GET()->threadgroup->id);
    }
    Py_XDECREF(value);
    Py_CLEAR(self->sink);
    return 0;
}

static void
transferbox_dealloc(PyObject *op)
{
    PyTypeObject *type = Py_TYPE(op);
    PyObject_GC_UnTrack(op);
    transferbox_clear(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static PyMethodDef transferbox_methods[] = {
    {"claim", transferbox_claim, METH_NOARGS,
     PyDoc_STR("Claim the boxed value for the current ThreadGroup, once.")},
    {"__class_getitem__", Py_GenericAlias, METH_O | METH_CLASS,
     PyDoc_STR("See PEP 585")},
    {NULL},
};

static PyObject *
transferbox_get_sink(PyObject *op, void *closure)
{
    PyObject *sink;
    Py_BEGIN_CRITICAL_SECTION(op);
    sink = Py_XNewRef(((transferboxobject *)op)->sink);
    Py_END_CRITICAL_SECTION();
    if (sink == NULL) {
        PyErr_SetString(PyExc_AttributeError, "sink");
    }
    return sink;
}

static int
transferbox_set_sink(PyObject *op, PyObject *sink, void *closure)
{
    if (transferbox_check_sink(Py_TYPE(op), sink) < 0) {
        return -1;
    }
    Py_INCREF(sink);
    PyObject *old_sink;
    Py_BEGIN_CRITICAL_SECTION(op);
    transferboxobject *self = (transferboxobject *)op;
    old_sink = self->sink;
    self->sink = sink;
    Py_END_CRITICAL_SECTION();
    Py_XDECREF(old_sink);
    return 0;
}

static PyGetSetDef transferbox_getsets[] = {
    {"sink", transferbox_get_sink, transferbox_set_sink,
     PyDoc_STR("The destination ThreadGroup, or None for any group."), NULL},
    {NULL},
};

static PyType_Slot transferbox_slots[] = {
    {Py_tp_new, transferbox_new},
    {Py_tp_dealloc, transferbox_dealloc},
    {Py_tp_traverse, transferbox_traverse},
    {Py_tp_clear, transferbox_clear},
    {Py_tp_methods, transferbox_methods},
    {Py_tp_getset, transferbox_getsets},
    {Py_tp_doc, "TransferBox(obj, sink=None)\n--\n\n"
                "A synchronized container for transferring a value once."},
    {0, NULL},
};

static PyType_Spec transferbox_spec = {
    .name = "threading.TransferBox",
    .basicsize = sizeof(transferboxobject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_HAVE_GC,
    .slots = transferbox_slots,
};

typedef struct channel_node {
    struct channel_node *next;
    PyObject *box;
} channel_node;

typedef struct {
    PyObject_HEAD
    channel_node *head;
    channel_node *tail;
} channelqueueobject;

static PyObject *
channelqueue_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    if (!_PyArg_NoPositional("_ChannelQueue", args) ||
        !_PyArg_NoKeywords("_ChannelQueue", kwargs)) {
        return NULL;
    }
    PyObject *self = type->tp_alloc(type, 0);
    if (self != NULL && PyObject_DeclareSynchronized(self) < 0) {
        Py_CLEAR(self);
    }
    return self;
}

static PyObject *
channelqueue_put(PyObject *op, PyObject *value)
{
    thread_module_state *state = get_thread_state_by_cls(Py_TYPE(op));
    if (state == NULL) {
        return NULL;
    }
    // Copying can run arbitrary Python code, including reentrant puts/gets.
    PyObject *box = PyObject_CallOneArg((PyObject *)state->transferbox_type,
                                      value);
    if (box == NULL) {
        return NULL;
    }
    channel_node *node = PyMem_Malloc(sizeof(*node));
    if (node == NULL) {
        Py_DECREF(box);
        return PyErr_NoMemory();
    }
    node->box = box;
    node->next = NULL;
    channelqueueobject *self = (channelqueueobject *)op;
    Py_BEGIN_CRITICAL_SECTION(op);
    if (self->tail == NULL) {
        self->head = node;
    }
    else {
        self->tail->next = node;
    }
    self->tail = node;
    Py_END_CRITICAL_SECTION();
    Py_RETURN_NONE;
}

static PyObject *
channelqueue_get(PyObject *op, PyObject *Py_UNUSED(ignored))
{
    channelqueueobject *self = (channelqueueobject *)op;
    channel_node *node;
    Py_BEGIN_CRITICAL_SECTION(op);
    node = self->head;
    if (node != NULL) {
        self->head = node->next;
        if (self->head == NULL) {
            self->tail = NULL;
        }
    }
    Py_END_CRITICAL_SECTION();
    if (node == NULL) {
        PyErr_SetString(PyExc_IndexError, "get from an empty Channel");
        return NULL;
    }
    PyObject *box = node->box;
    PyMem_Free(node);
    PyObject *value = transferbox_claim(box, NULL);
    Py_DECREF(box);
    return value;
}

static int
channelqueue_traverse(PyObject *op, visitproc visit, void *arg)
{
    channelqueueobject *self = (channelqueueobject *)op;
    Py_VISIT(Py_TYPE(op));
    for (channel_node *node = self->head; node != NULL; node = node->next) {
        Py_VISIT(node->box);
    }
    return 0;
}

static int
channelqueue_clear(PyObject *op)
{
    channelqueueobject *self = (channelqueueobject *)op;
    channel_node *node = self->head;
    self->head = self->tail = NULL;
    // Detach the whole queue before releasing references that may run code.
    while (node != NULL) {
        channel_node *next = node->next;
        Py_DECREF(node->box);
        PyMem_Free(node);
        node = next;
    }
    return 0;
}

static void
channelqueue_dealloc(PyObject *op)
{
    PyTypeObject *type = Py_TYPE(op);
    PyObject_GC_UnTrack(op);
    channelqueue_clear(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static PyMethodDef channelqueue_methods[] = {
    {"put", channelqueue_put, METH_O, NULL},
    {"get", channelqueue_get, METH_NOARGS, NULL},
    {NULL},
};

static PyType_Slot channelqueue_slots[] = {
    {Py_tp_new, channelqueue_new},
    {Py_tp_dealloc, channelqueue_dealloc},
    {Py_tp_traverse, channelqueue_traverse},
    {Py_tp_clear, channelqueue_clear},
    {Py_tp_methods, channelqueue_methods},
    {0, NULL},
};

static PyType_Spec channelqueue_spec = {
    .name = "_thread._ChannelQueue",
    .basicsize = sizeof(channelqueueobject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_HAVE_GC,
    .slots = channelqueue_slots,
};


#ifdef MS_WINDOWS
typedef HRESULT (WINAPI *PF_GET_THREAD_DESCRIPTION)(HANDLE, PWSTR*);
typedef HRESULT (WINAPI *PF_SET_THREAD_DESCRIPTION)(HANDLE, PCWSTR);
static PF_GET_THREAD_DESCRIPTION pGetThreadDescription = NULL;
static PF_SET_THREAD_DESCRIPTION pSetThreadDescription = NULL;
#endif


/*[clinic input]
module _thread
class _thread.lock "lockobject *" "clinic_state()->lock_type"
class _thread.RLock "rlockobject *" "clinic_state()->rlock_type"
[clinic start generated code]*/
/*[clinic end generated code: output=da39a3ee5e6b4b0d input=c5a0f8c492a0c263]*/

#define clinic_state() get_thread_state_by_cls(type)
#include "clinic/_threadmodule.c.h"
#undef clinic_state

// _ThreadHandle type

// Handles state transitions according to the following diagram:
//
//     NOT_STARTED -> STARTING -> RUNNING -> DONE
//                       |                    ^
//                       |                    |
//                       +----- error --------+
typedef enum {
    THREAD_HANDLE_NOT_STARTED = 1,
    THREAD_HANDLE_STARTING = 2,
    THREAD_HANDLE_RUNNING = 3,
    THREAD_HANDLE_DONE = 4,
} ThreadHandleState;

// A handle to wait for thread completion.
//
// This may be used to wait for threads that were spawned by the threading
// module as well as for the "main" thread of the threading module. In the
// former case an OS thread, identified by the `os_handle` field, will be
// associated with the handle. The handle "owns" this thread and ensures that
// the thread is either joined or detached after the handle is destroyed.
//
// Joining the handle is idempotent; the underlying OS thread, if any, is
// joined or detached only once. Concurrent join operations are serialized
// until it is their turn to execute or an earlier operation completes
// successfully. Once a join has completed successfully all future joins
// complete immediately.
//
// This must be separately reference counted because it may be destroyed
// in `thread_run()` after the PyThreadState has been destroyed.
typedef struct {
    struct llist_node node;  // linked list node (see _pythread_runtime_state)

    // linked list node (see thread_module_state)
    struct llist_node shutdown_node;

    // The `ident`, `os_handle`, `has_os_handle`, and `state` fields are
    // protected by `mutex`.
    PyThread_ident_t ident;
    PyThread_handle_t os_handle;
    int has_os_handle;

    // Holds a value from the `ThreadHandleState` enum.
    int state;

    PyMutex mutex;

    // Set immediately before `thread_run` returns to indicate that the OS
    // thread is about to exit. This is used to avoid false positives when
    // detecting self-join attempts. See the comment in `ThreadHandle_join()`
    // for a more detailed explanation.
    PyEvent thread_is_exiting;

    // Serializes calls to `join` and `set_done`.
    _PyOnceFlag once;

    Py_ssize_t refcount;
} ThreadHandle;

static inline int
get_thread_handle_state(ThreadHandle *handle)
{
    PyMutex_Lock(&handle->mutex);
    int state = handle->state;
    PyMutex_Unlock(&handle->mutex);
    return state;
}

static inline void
set_thread_handle_state(ThreadHandle *handle, ThreadHandleState state)
{
    PyMutex_Lock(&handle->mutex);
    handle->state = state;
    PyMutex_Unlock(&handle->mutex);
}

static PyThread_ident_t
ThreadHandle_ident(ThreadHandle *handle)
{
    PyMutex_Lock(&handle->mutex);
    PyThread_ident_t ident = handle->ident;
    PyMutex_Unlock(&handle->mutex);
    return ident;
}

static int
ThreadHandle_get_os_handle(ThreadHandle *handle, PyThread_handle_t *os_handle)
{
    PyMutex_Lock(&handle->mutex);
    int has_os_handle = handle->has_os_handle;
    if (has_os_handle) {
        *os_handle = handle->os_handle;
    }
    PyMutex_Unlock(&handle->mutex);
    return has_os_handle;
}

static void
add_to_shutdown_handles(thread_module_state *state, ThreadHandle *handle)
{
    HEAD_LOCK(&_PyRuntime);
    llist_insert_tail(&state->shutdown_handles, &handle->shutdown_node);
    HEAD_UNLOCK(&_PyRuntime);
}

static void
clear_shutdown_handles(thread_module_state *state)
{
    HEAD_LOCK(&_PyRuntime);
    struct llist_node *node;
    llist_for_each_safe(node, &state->shutdown_handles) {
        llist_remove(node);
    }
    HEAD_UNLOCK(&_PyRuntime);
}

static void
remove_from_shutdown_handles(ThreadHandle *handle)
{
    HEAD_LOCK(&_PyRuntime);
    if (handle->shutdown_node.next != NULL) {
        llist_remove(&handle->shutdown_node);
    }
    HEAD_UNLOCK(&_PyRuntime);
}

static ThreadHandle *
ThreadHandle_new(void)
{
    ThreadHandle *self =
        (ThreadHandle *)PyMem_RawCalloc(1, sizeof(ThreadHandle));
    if (self == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    self->ident = 0;
    self->os_handle = 0;
    self->has_os_handle = 0;
    self->thread_is_exiting = (PyEvent){0};
    self->mutex = (PyMutex){_Py_UNLOCKED};
    self->once = (_PyOnceFlag){0};
    self->state = THREAD_HANDLE_NOT_STARTED;
    self->refcount = 1;

    HEAD_LOCK(&_PyRuntime);
    llist_insert_tail(&_PyRuntime.threads.handles, &self->node);
    HEAD_UNLOCK(&_PyRuntime);

    return self;
}

static void
ThreadHandle_incref(ThreadHandle *self)
{
    _Py_atomic_add_ssize(&self->refcount, 1);
}

static int
detach_thread(ThreadHandle *self)
{
    if (!self->has_os_handle) {
        return 0;
    }
    // This is typically short so no need to release the GIL
    if (PyThread_detach_thread(self->os_handle)) {
        fprintf(stderr, "detach_thread: failed detaching thread\n");
        return -1;
    }
    return 0;
}

// NB: This may be called after the PyThreadState in `thread_run` has been
// deleted; it cannot call anything that relies on a valid PyThreadState
// existing.
static void
ThreadHandle_decref(ThreadHandle *self)
{
    if (_Py_atomic_add_ssize(&self->refcount, -1) > 1) {
        return;
    }

    // Remove ourself from the global list of handles
    HEAD_LOCK(&_PyRuntime);
    if (self->node.next != NULL) {
        llist_remove(&self->node);
    }
    HEAD_UNLOCK(&_PyRuntime);

    assert(self->shutdown_node.next == NULL);

    // It's safe to access state non-atomically:
    //   1. This is the destructor; nothing else holds a reference.
    //   2. The refcount going to zero is a "synchronizes-with" event; all
    //      changes from other threads are visible.
    if (self->state == THREAD_HANDLE_RUNNING && !detach_thread(self)) {
        self->state = THREAD_HANDLE_DONE;
    }

    PyMem_RawFree(self);
}

void
_PyThread_AfterFork(struct _pythread_runtime_state *state)
{
    // gh-115035: We mark ThreadHandles as not joinable early in the child's
    // after-fork handler. We do this before calling any Python code to ensure
    // that it happens before any ThreadHandles are deallocated, such as by a
    // GC cycle.
    PyThread_ident_t current = PyThread_get_thread_ident_ex();

    struct llist_node *node;
    llist_for_each_safe(node, &state->handles) {
        ThreadHandle *handle = llist_data(node, ThreadHandle, node);
        if (handle->ident == current) {
            continue;
        }

        // Keep handles for threads that have not been started yet. They are
        // safe to start in the child process.
        if (handle->state == THREAD_HANDLE_NOT_STARTED) {
            continue;
        }

        // Mark all threads as done. Any attempts to join or detach the
        // underlying OS thread (if any) could crash. We are the only thread;
        // it's safe to set this non-atomically.
        handle->state = THREAD_HANDLE_DONE;
        handle->once = (_PyOnceFlag){_Py_ONCE_INITIALIZED};
        handle->mutex = (PyMutex){_Py_UNLOCKED};
        _PyEvent_Notify(&handle->thread_is_exiting);
        llist_remove(node);
        remove_from_shutdown_handles(handle);
    }
}

// bootstate is used to "bootstrap" new threads. Any arguments needed by
// `thread_run()`, which can only take a single argument due to platform
// limitations, are contained in bootstate.
struct bootstate {
    PyThreadState *tstate;
    PyObject *func;
    PyObject *args;
    PyObject *kwargs;
    ThreadHandle *handle;
    PyEvent handle_ready;
};

static void
thread_bootstate_free(struct bootstate *boot, int decref)
{
    if (decref) {
        Py_DECREF(boot->func);
        Py_DECREF(boot->args);
        Py_XDECREF(boot->kwargs);
    }
    ThreadHandle_decref(boot->handle);
    PyMem_RawFree(boot);
}

static void
thread_run(void *boot_raw)
{
    struct bootstate *boot = (struct bootstate *) boot_raw;
    PyThreadState *tstate = boot->tstate;

    // Wait until the handle is marked as running
    PyEvent_Wait(&boot->handle_ready);

    // `handle` needs to be manipulated after bootstate has been freed
    ThreadHandle *handle = boot->handle;
    ThreadHandle_incref(handle);

    // gh-108987: If _thread.start_new_thread() is called before or while
    // Python is being finalized, thread_run() can called *after*.
    // _PyRuntimeState_SetFinalizing() is called. At this point, all Python
    // threads must exit, except of the thread calling Py_Finalize() which
    // holds the GIL and must not exit.
    if (_PyThreadState_MustExit(tstate)) {
        // Don't call PyThreadState_Clear() nor _PyThreadState_DeleteCurrent().
        // These functions are called on tstate indirectly by Py_Finalize()
        // which calls _PyInterpreterState_Clear().
        //
        // Py_DECREF() cannot be called because the GIL is not held: leak
        // references on purpose. Python is being finalized anyway.
        thread_bootstate_free(boot, 0);
        goto exit;
    }

    _PyThreadState_Bind(tstate);
    PyEval_AcquireThread(tstate);
    _Py_atomic_add_ssize(&tstate->interp->threads.count, 1);

    PyObject *res = PyObject_Call(boot->func, boot->args, boot->kwargs);
    if (res == NULL) {
        if (PyErr_ExceptionMatches(PyExc_SystemExit))
            /* SystemExit is ignored silently */
            PyErr_Clear();
        else {
            PyErr_FormatUnraisable(
                "Exception ignored in thread started by %R", boot->func);
        }
    }
    else {
        Py_DECREF(res);
    }

    thread_bootstate_free(boot, 1);

    _Py_atomic_add_ssize(&tstate->interp->threads.count, -1);
    PyThreadState_Clear(tstate);
    _PyThreadState_DeleteCurrent(tstate);

exit:
    // Don't need to wait for this thread anymore
    remove_from_shutdown_handles(handle);

    _PyEvent_Notify(&handle->thread_is_exiting);
    ThreadHandle_decref(handle);

    // bpo-44434: Don't call explicitly PyThread_exit_thread(). On Linux with
    // the glibc, pthread_exit() can abort the whole process if dlopen() fails
    // to open the libgcc_s.so library (ex: EMFILE error).
    return;
}

static int
force_done(void *arg)
{
    ThreadHandle *handle = (ThreadHandle *)arg;
    assert(get_thread_handle_state(handle) == THREAD_HANDLE_STARTING);
    _PyEvent_Notify(&handle->thread_is_exiting);
    set_thread_handle_state(handle, THREAD_HANDLE_DONE);
    return 0;
}

static int
ThreadHandle_start(ThreadHandle *self, PyObject *func, PyObject *args,
                   PyObject *kwargs, int daemon, PyObject *group)
{
    // Mark the handle as starting to prevent any other threads from doing so
    PyMutex_Lock(&self->mutex);
    if (self->state != THREAD_HANDLE_NOT_STARTED) {
        PyMutex_Unlock(&self->mutex);
        PyErr_SetString(ThreadError, "thread already started");
        return -1;
    }
    self->state = THREAD_HANDLE_STARTING;
    PyMutex_Unlock(&self->mutex);

    // Do all the heavy lifting outside of the mutex. All other operations on
    // the handle should fail since the handle is in the starting state.

    // gh-109795: Use PyMem_RawMalloc() instead of PyMem_Malloc(),
    // because it should be possible to call thread_bootstate_free()
    // without holding the GIL.
    struct bootstate *boot = PyMem_RawMalloc(sizeof(struct bootstate));
    if (boot == NULL) {
        PyErr_NoMemory();
        goto start_failed;
    }
    PyInterpreterState *interp = _PyInterpreterState_GET();
    uint8_t whence = daemon ? _PyThreadState_WHENCE_THREADING_DAEMON : _PyThreadState_WHENCE_THREADING;
    boot->tstate = _PyThreadState_New(interp, whence);
    if (boot->tstate == NULL) {
        PyMem_RawFree(boot);
        if (!PyErr_Occurred()) {
            PyErr_NoMemory();
        }
        goto start_failed;
    }
    if (group != NULL) {
        threadgroupobject *owner = (threadgroupobject *)group;
        _PyThreadGroup_Decref(boot->tstate->threadgroup);
        boot->tstate->threadgroup = owner->state;
        _PyThreadGroup_Incref(owner->state);
        boot->tstate->threadgroup_object = Py_NewRef(group);
    }
    boot->func = Py_NewRef(func);
    boot->args = Py_NewRef(args);
    boot->kwargs = Py_XNewRef(kwargs);
    boot->handle = self;
    ThreadHandle_incref(self);
    boot->handle_ready = (PyEvent){0};

    PyThread_ident_t ident;
    PyThread_handle_t os_handle;
    if (PyThread_start_joinable_thread(thread_run, boot, &ident, &os_handle)) {
        PyThreadState_Clear(boot->tstate);
        PyThreadState_Delete(boot->tstate);
        thread_bootstate_free(boot, 1);
        PyErr_SetString(ThreadError, "can't start new thread");
        goto start_failed;
    }

    // Mark the handle running
    PyMutex_Lock(&self->mutex);
    assert(self->state == THREAD_HANDLE_STARTING);
    self->ident = ident;
    self->has_os_handle = 1;
    self->os_handle = os_handle;
    self->state = THREAD_HANDLE_RUNNING;
    PyMutex_Unlock(&self->mutex);

    // Unblock the thread
    _PyEvent_Notify(&boot->handle_ready);

    return 0;

start_failed:
    _PyOnceFlag_CallOnce(&self->once, force_done, self);
    return -1;
}

static int
join_thread(void *arg)
{
    ThreadHandle *handle = (ThreadHandle*)arg;
    assert(get_thread_handle_state(handle) == THREAD_HANDLE_RUNNING);
    PyThread_handle_t os_handle;
    if (ThreadHandle_get_os_handle(handle, &os_handle)) {
        int err = 0;
        Py_BEGIN_ALLOW_THREADS
        err = PyThread_join_thread(os_handle);
        Py_END_ALLOW_THREADS
        if (err) {
            PyErr_SetString(ThreadError, "Failed joining thread");
            return -1;
        }
    }
    set_thread_handle_state(handle, THREAD_HANDLE_DONE);
    return 0;
}

static int
check_started(ThreadHandle *self)
{
    ThreadHandleState state = get_thread_handle_state(self);
    if (state < THREAD_HANDLE_RUNNING) {
        PyErr_SetString(ThreadError, "thread not started");
        return -1;
    }
    return 0;
}

static int
ThreadHandle_join_impl(ThreadHandle *self, PyTime_t timeout_ns,
                       PyObject **interrupted)
{
    if (check_started(self) < 0) {
        return -1;
    }

    // We want to perform this check outside of the `_PyOnceFlag` to prevent
    // deadlock in the scenario where another thread joins us and we then
    // attempt to join ourselves. However, it's not safe to check thread
    // identity once the handle's os thread has finished. We may end up reusing
    // the identity stored in the handle and erroneously think we are
    // attempting to join ourselves.
    //
    // To work around this, we set `thread_is_exiting` immediately before
    // `thread_run` returns.  We can be sure that we are not attempting to join
    // ourselves if the handle's thread is about to exit.
    if (!_PyEvent_IsSet(&self->thread_is_exiting)) {
        if (ThreadHandle_ident(self) == PyThread_get_thread_ident_ex()) {
            // PyThread_join_thread() would deadlock or error out.
            PyErr_SetString(ThreadError, "Cannot join current thread");
            return -1;
        }
        if (Py_IsFinalizing()) {
            // gh-123940: On finalization, other threads are prevented from
            // running Python code. They cannot finalize themselves,
            // so join() would hang forever (or until timeout).
            // We raise instead.
            PyErr_SetString(PyExc_PythonFinalizationError,
                            "cannot join thread at interpreter shutdown");
            return -1;
        }
    }

    // Wait until the deadline for the thread to exit.
    PyTime_t deadline = timeout_ns != -1 ? _PyDeadline_Init(timeout_ns) : 0;
    int detach = 1;
    for (;;) {
        PyTime_t wait_ns = timeout_ns;
        if (interrupted != NULL && (wait_ns < 0 || wait_ns > 50000000)) {
            // A signal can arrive while handling the previous interrupt,
            // before we park again. Bound cleanup waits to service pending
            // calls even when no native wait was interrupted (50 ms).
            wait_ns = 50000000;
        }
        if (PyEvent_WaitTimed(&self->thread_is_exiting, wait_ns, detach)) {
            break;
        }
        if (deadline) {
            // _PyDeadline_Get will return a negative value if the deadline has
            // been exceeded.
            timeout_ns = _PyDeadline_Get(deadline);
            timeout_ns = Py_MAX(timeout_ns, 0);
        }

        if (timeout_ns) {
            // Interrupted
            if (Py_MakePendingCalls() < 0) {
                if (interrupted == NULL) {
                    return -1;
                }
                // Cleanup callbacks must finish before their caller resumes.
                // Preserve the first interrupt while still servicing signals.
                if (*interrupted == NULL) {
                    *interrupted = PyErr_GetRaisedException();
                }
                else {
                    PyErr_Clear();
                }
            }
        }
        else {
            // Timed out
            return 0;
        }
    }

    if (_PyOnceFlag_CallOnce(&self->once, join_thread, self) == -1) {
        return -1;
    }
    assert(get_thread_handle_state(self) == THREAD_HANDLE_DONE);
    return 0;
}

static int
ThreadHandle_join(ThreadHandle *self, PyTime_t timeout_ns)
{
    return ThreadHandle_join_impl(self, timeout_ns, NULL);
}

static int
set_done(void *arg)
{
    ThreadHandle *handle = (ThreadHandle*)arg;
    assert(get_thread_handle_state(handle) == THREAD_HANDLE_RUNNING);
    if (detach_thread(handle) < 0) {
        PyErr_SetString(ThreadError, "failed detaching handle");
        return -1;
    }
    _PyEvent_Notify(&handle->thread_is_exiting);
    set_thread_handle_state(handle, THREAD_HANDLE_DONE);
    return 0;
}

static int
ThreadHandle_set_done(ThreadHandle *self)
{
    if (check_started(self) < 0) {
        return -1;
    }

    if (_PyOnceFlag_CallOnce(&self->once, set_done, self) ==
        -1) {
        return -1;
    }
    assert(get_thread_handle_state(self) == THREAD_HANDLE_DONE);
    return 0;
}

// A wrapper around a ThreadHandle.
typedef struct {
    PyObject_HEAD

    ThreadHandle *handle;
} PyThreadHandleObject;

#define PyThreadHandleObject_CAST(op)   ((PyThreadHandleObject *)(op))

static PyThreadHandleObject *
PyThreadHandleObject_new(PyTypeObject *type)
{
    ThreadHandle *handle = ThreadHandle_new();
    if (handle == NULL) {
        return NULL;
    }

    PyThreadHandleObject *self =
        (PyThreadHandleObject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        ThreadHandle_decref(handle);
        return NULL;
    }

    self->handle = handle;
    // The native handle serializes its mutable fields, completion and joins.
    if (PyObject_DeclareSynchronized((PyObject *)self) < 0) {
        Py_DECREF(self);
        return NULL;
    }

    return self;
}

static PyObject *
PyThreadHandleObject_tp_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    return (PyObject *)PyThreadHandleObject_new(type);
}

static void
PyThreadHandleObject_dealloc(PyObject *op)
{
    PyThreadHandleObject *self = PyThreadHandleObject_CAST(op);
    PyObject_GC_UnTrack(self);
    PyTypeObject *tp = Py_TYPE(self);
    ThreadHandle_decref(self->handle);
    tp->tp_free(self);
    Py_DECREF(tp);
}

static PyObject *
PyThreadHandleObject_repr(PyObject *op)
{
    PyThreadHandleObject *self = PyThreadHandleObject_CAST(op);
    PyThread_ident_t ident = ThreadHandle_ident(self->handle);
    return PyUnicode_FromFormat("<%s object: ident=%" PY_FORMAT_THREAD_IDENT_T ">",
                                Py_TYPE(self)->tp_name, ident);
}

static PyObject *
PyThreadHandleObject_get_ident(PyObject *op, void *Py_UNUSED(closure))
{
    PyThreadHandleObject *self = PyThreadHandleObject_CAST(op);
    return PyLong_FromUnsignedLongLong(ThreadHandle_ident(self->handle));
}

static PyObject *
PyThreadHandleObject_join(PyObject *op, PyObject *args)
{
    PyThreadHandleObject *self = PyThreadHandleObject_CAST(op);

    PyObject *timeout_obj = NULL;
    if (!PyArg_ParseTuple(args, "|O:join", &timeout_obj)) {
        return NULL;
    }

    PyTime_t timeout_ns = -1;
    if (timeout_obj != NULL && timeout_obj != Py_None) {
        if (_PyTime_FromSecondsObject(&timeout_ns, timeout_obj,
                                      _PyTime_ROUND_TIMEOUT) < 0) {
            return NULL;
        }
    }

    if (ThreadHandle_join(self->handle, timeout_ns) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
PyThreadHandleObject_is_done(PyObject *op, PyObject *Py_UNUSED(dummy))
{
    PyThreadHandleObject *self = PyThreadHandleObject_CAST(op);
    if (_PyEvent_IsSet(&self->handle->thread_is_exiting)) {
        if (_PyOnceFlag_CallOnce(&self->handle->once, join_thread, self->handle) == -1) {
            return NULL;
        }
        Py_RETURN_TRUE;
    }
    else {
        Py_RETURN_FALSE;
    }
}

static PyObject *
PyThreadHandleObject_set_done(PyObject *op, PyObject *Py_UNUSED(dummy))
{
    PyThreadHandleObject *self = PyThreadHandleObject_CAST(op);
    if (ThreadHandle_set_done(self->handle) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyGetSetDef ThreadHandle_getsetlist[] = {
    {"ident", PyThreadHandleObject_get_ident, NULL, NULL},
    {0},
};

static PyMethodDef ThreadHandle_methods[] = {
    {"join", PyThreadHandleObject_join, METH_VARARGS, NULL},
    {"_set_done", PyThreadHandleObject_set_done, METH_NOARGS, NULL},
    {"is_done", PyThreadHandleObject_is_done, METH_NOARGS, NULL},
    {0, 0}
};

static PyType_Slot ThreadHandle_Type_slots[] = {
    {Py_tp_dealloc, PyThreadHandleObject_dealloc},
    {Py_tp_repr, PyThreadHandleObject_repr},
    {Py_tp_getset, ThreadHandle_getsetlist},
    {Py_tp_traverse, _PyObject_VisitType},
    {Py_tp_methods, ThreadHandle_methods},
    {Py_tp_new, PyThreadHandleObject_tp_new},
    {0, 0}
};

static PyType_Spec ThreadHandle_Type_spec = {
    "_thread._ThreadHandle",
    sizeof(PyThreadHandleObject),
    0,
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_HAVE_GC,
    ThreadHandle_Type_slots,
};

/* Synchronized namespaces for Thread and audited threading primitives. */
typedef struct {
    PyObject_HEAD
    PyObject *dict;
    PyObject *weakrefs;
} threadbaseobject;

static int
threadbase_traverse(PyObject *op, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(((threadbaseobject *)op)->dict);
    return 0;
}

static int
threadbase_clear(PyObject *op)
{
    Py_CLEAR(((threadbaseobject *)op)->dict);
    return 0;
}

static void
threadbase_dealloc(PyObject *op)
{
    PyObject_GC_UnTrack(op);
    if (((threadbaseobject *)op)->weakrefs != NULL) {
        PyObject_ClearWeakRefs(op);
    }
    threadbase_clear(op);
    PyTypeObject *type = Py_TYPE(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static int
threadbase_has_python_storage(PyTypeObject *type)
{
    PyObject *module = PyType_GetModuleByDef(type, &thread_module);
    assert(module != NULL);
    PyTypeObject *base = get_thread_state(module)->thread_base_type;
    while (type != base) {
        if (!(type->tp_flags & Py_TPFLAGS_HEAPTYPE)) {
            return 0;
        }
        PyObject *slots = ((PyHeapTypeObject *)type)->ht_slots;
        Py_ssize_t count = slots == NULL ? 0 : PyTuple_GET_SIZE(slots);
        if (type->tp_itemsize != 0 ||
            type->tp_basicsize != type->tp_base->tp_basicsize +
                                 count * (Py_ssize_t)sizeof(PyObject *))
        {
            // Additional opaque C storage needs its own synchronization.
            return 0;
        }
        type = type->tp_base;
    }
    return 1;
}

static PyObject *
threadbase_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    threadbaseobject *self = (threadbaseobject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }
    self->dict = PySynchronizedDict_New();
    if (self->dict == NULL ||
        (threadbase_has_python_storage(type) &&
         PyObject_DeclareSynchronized((PyObject *)self) < 0))
    {
        Py_DECREF(self);
        return NULL;
    }
    return (PyObject *)self;
}

static PyObject *
threadbase_getweakref(PyObject *op, void *Py_UNUSED(context))
{
    PyObject *result = NULL;
    LOCK_WEAKREFS(op);
    PyWeakReference *ref = (PyWeakReference *)((threadbaseobject *)op)->weakrefs;
    while (ref != NULL) {
        if (_Py_TryIncref((PyObject *)ref)) {
            result = (PyObject *)ref;
            break;
        }
        ref = ref->wr_next;
    }
    UNLOCK_WEAKREFS(op);
    return result != NULL ? result : Py_NewRef(Py_None);
}

static PyGetSetDef threadbase_getset[] = {
    {"__dict__", PyObject_GenericGetDict, PyObject_GenericSetDict, NULL, NULL},
    {"__weakref__", threadbase_getweakref, NULL, NULL, NULL},
    {NULL}
};

static PyMemberDef threadbase_members[] = {
    {"__dictoffset__", Py_T_PYSSIZET, offsetof(threadbaseobject, dict), Py_READONLY},
    {"__weaklistoffset__", Py_T_PYSSIZET, offsetof(threadbaseobject, weakrefs), Py_READONLY},
    {NULL}
};

static PyType_Slot threadbase_slots[] = {
    {Py_tp_new, threadbase_new},
    {Py_tp_dealloc, threadbase_dealloc},
    {Py_tp_traverse, threadbase_traverse},
    {Py_tp_clear, threadbase_clear},
    {Py_tp_getset, threadbase_getset},
    {Py_tp_members, threadbase_members},
    {0, NULL}
};

static PyType_Spec threadbase_spec = {
    .name = "_thread._ThreadBase",
    .basicsize = sizeof(threadbaseobject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC |
             Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_BASETYPE,
    .slots = threadbase_slots,
};

static int
finalizer_can_wait(PyThreadState *tstate)
{
    PyInterpreterState *interp = tstate->interp;
    _PyRuntimeState *runtime = interp->runtime;
    HEAD_LOCK(runtime);
    int paused =
        (interp->stoptheworld.requested &&
         interp->stoptheworld.requester == tstate) ||
        (runtime->stoptheworld.requested &&
         runtime->stoptheworld.requester == tstate);
    HEAD_UNLOCK(runtime);
    if (paused) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot dispatch a finalizer while stopping the world");
        return -1;
    }
    if (Py_IsFinalizing() || _PyInterpreterState_GetFinalizing(interp) != NULL) {
        PyErr_SetString(PyExc_PythonFinalizationError,
                        "cannot dispatch a finalizer at interpreter shutdown");
        return -1;
    }
    return 0;
}

/* Lock objects */

static void
lock_dealloc(PyObject *self)
{
    PyObject_GC_UnTrack(self);
    PyObject_ClearWeakRefs(self);
    _PyProtectiveMutex_Decref(((lockobject *)self)->state);
    PyTypeObject *tp = Py_TYPE(self);
    tp->tp_free(self);
    Py_DECREF(tp);
}


static int
lock_acquire_parse_timeout(PyObject *timeout_obj, int blocking, PyTime_t *timeout)
{
    // XXX Use PyThread_ParseTimeoutArg().

    const PyTime_t unset_timeout = _PyTime_FromSeconds(-1);
    *timeout = unset_timeout;

    if (timeout_obj
        && _PyTime_FromSecondsObject(timeout,
                                     timeout_obj, _PyTime_ROUND_TIMEOUT) < 0)
        return -1;

    if (!blocking && *timeout != unset_timeout ) {
        PyErr_SetString(PyExc_ValueError,
                        "can't specify a timeout for a non-blocking call");
        return -1;
    }
    if (*timeout < 0 && *timeout != unset_timeout) {
        PyErr_SetString(PyExc_ValueError,
                        "timeout value must be a non-negative number");
        return -1;
    }
    if (!blocking)
        *timeout = 0;
    else if (*timeout != unset_timeout) {
        PyTime_t microseconds;

        microseconds = _PyTime_AsMicroseconds(*timeout, _PyTime_ROUND_TIMEOUT);
        if (microseconds > PY_TIMEOUT_MAX) {
            PyErr_SetString(PyExc_OverflowError,
                            "timeout value is too large");
            return -1;
        }
    }
    return 0;
}
/* All primitive-lock state changes share the object's critical section.
   Waiters use compare-and-park, not PyMutex's ownership-handoff protocol:
   context ownership must be recorded atomically with physical acquisition. */
static int
lock_context_owned(_PyProtectiveMutexState *state, PyThreadState *tstate)
{
    return state->context_group == tstate->threadgroup->id &&
           state->context_thread == tstate->id;
}

static PyObject *
lock_acquire(_PyProtectiveMutexState *state, PyTime_t timeout, int context)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyTime_t deadline = timeout > 0 ? _PyDeadline_Init(timeout) : 0;
    for (;;) {
        /* Pending calls during a wait can change the registry's size. */
        if (context && _PyThreadState_ReserveHeldMutex(tstate) < 0) {
            return NULL;
        }
        int acquired = 0;
        int forbidden = 0;
        PyMutex_LockFlags(&state->metadata_mutex, 0);
        if (state->protective && !context) {
            forbidden = 1;
        }
        else if (PyMutex_LockFast(&state->lock.plain)) {
            state->context_epoch++;
            state->context_group = context ? tstate->threadgroup->id : 0;
            state->context_thread = context ? tstate->id : 0;
            if (state->protective) {
                _PyThreadState_PushHeldMutex(tstate, state->mutex_id);
            }
            acquired = 1;
        }
        PyMutex_Unlock(&state->metadata_mutex);
        if (forbidden) {
            PyErr_SetString(PyExc_RuntimeError,
                            "protective locks can only be acquired with a context manager");
            return NULL;
        }
        if (acquired) {
            Py_RETURN_TRUE;
        }
        if (timeout == 0) {
            Py_RETURN_FALSE;
        }
        if (Py_IsFinalizing()) {
            PyErr_SetString(PyExc_PythonFinalizationError,
                            "cannot acquire lock at interpreter finalization");
            return NULL;
        }
        uint8_t locked = _Py_LOCKED;
        int result = _PyParkingLot_Park(&state->lock.plain._bits, &locked,
                                       sizeof(locked), timeout, NULL, 1);
        if (result == Py_PARK_INTR && Py_MakePendingCalls() < 0) {
            return NULL;
        }
        if (result == Py_PARK_TIMEOUT) {
            Py_RETURN_FALSE;
        }
        if (deadline) {
            timeout = Py_MAX(_PyDeadline_Get(deadline), 0);
        }
    }
}

static PyObject *
lock_release(_PyProtectiveMutexState *state, int context)
{
    PyThreadState *tstate = _PyThreadState_GET();
    int error = 0;
    PyMutex_LockFlags(&state->metadata_mutex, 0);
    if ((state->protective && !context) ||
        ((state->protective || context == LOCK_COMPOUND_CONTEXT) && !lock_context_owned(state, tstate))) {
        error = 1;
    }
    else if (!PyMutex_IsLocked(&state->lock.plain)) {
        error = 2;
    }
    else {
        if (state->protective) {
            int removed = _PyThreadState_RemoveHeldMutex(tstate, state->mutex_id);
            assert(removed);
            (void)removed;
        }
        state->context_group = 0;
        state->context_thread = 0;
        int unlocked = _PyMutex_TryUnlock(&state->lock.plain);
        assert(unlocked == 0);
        (void)unlocked;
    }
    PyMutex_Unlock(&state->metadata_mutex);
    if (error) {
        PyErr_SetString(PyExc_RuntimeError, error == 1 ?
                        "protective locks can only be released by their owning context" :
                        "release unlocked lock");
        return NULL;
    }
    _PyParkingLot_UnparkAll(&state->lock.plain._bits);
    Py_RETURN_NONE;
}

static int
lock_python_instance(PyObject *value)
{
    PyObject *mro = Py_TYPE(value)->tp_mro;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(mro); i++) {
        PyTypeObject *base = (PyTypeObject *)PyTuple_GET_ITEM(mro, i);
        if (base != &PyBaseObject_Type &&
            (!(base->tp_flags & Py_TPFLAGS_HEAPTYPE) ||
             !((PyHeapTypeObject *)base)->ht_is_python)) {
            return 0;
        }
    }
    return 1;
}

static PyObject *
lock_copy_namespace(PyObject *copy)
{
    if (Py_TYPE(copy)->tp_dictoffset == 0) {
        return NULL;
    }
    if (Py_TYPE(copy)->tp_flags & Py_TPFLAGS_MANAGED_DICT) {
        return (PyObject *)_PyObject_GetManagedDict(copy);
    }
    return *_PyObject_ComputedDictPointer(copy);
}

/* No allocation or callbacks: called under the owning lock's metadata guard. */
static int
lock_publish_copy(PyObject *copy, uint32_t mutex_id)
{
    PyObject *dict = lock_copy_namespace(copy);
    if (copy->ob_shareable != _Py_SHAREABLE_LOCAL || copy->ob_frozen ||
        (Py_TYPE(copy)->tp_dictoffset != 0 && dict == NULL) ||
        !_PyObject_IsUniquelyReferenced(copy) ||
        (dict != NULL && !_PyObject_IsUniquelyReferenced(dict))) {
        return -1;
    }
    copy->ob_owner_id = mutex_id;
    copy->ob_shareable = _Py_SHAREABLE_PROTECTED;
    if (dict != NULL) {
        _PyObject_InheritShareable(dict, copy);
    }
    return 0;
}

static PyObject *
lock_protected_copy(PyObject *value)
{
    if (PyObject_CheckAccess(value) == NULL) {
        return NULL;
    }
    /* A borrowed argument can have refcount one while a local still owns it. */
    if (value->ob_shareable != _Py_SHAREABLE_LOCAL ||
        !PyUnstable_Object_IsUniqueReferencedTemporary(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "protect() requires the sole reference to a local object");
        return NULL;
    }
    if (PyList_CheckExact(value)) {
        return PyList_GetSlice(value, 0, PyList_GET_SIZE(value));
    }
    else if (PyDict_CheckExact(value)) {
        return PyDict_Copy(value);
    }
    else if (PySet_CheckExact(value)) {
        return PySet_New(value);
    }
    if (!lock_python_instance(value)) {
        PyErr_SetString(PyExc_TypeError,
                        "protect() does not support this native object layout");
        return NULL;
    }
    PyObject *module = PyImport_ImportModule("copy");
    if (module == NULL) {
        return NULL;
    }
    PyObject *copy = PyObject_CallMethod(module, "copy", "(O)", value);
    Py_DECREF(module);
    if (copy == NULL) {
        return NULL;
    }
    if (PyObject_CheckAccess(copy) == NULL) {
        Py_DECREF(copy);
        return NULL;
    }
    if (copy == value || Py_TYPE(copy) != Py_TYPE(value) ||
        !lock_python_instance(copy) ||
        copy->ob_shareable != _Py_SHAREABLE_LOCAL ||
        !_PyObject_IsUniquelyReferenced(copy)) {
        Py_DECREF(copy);
        PyErr_SetString(PyExc_TypeError,
                        "protect() copy must be an unaliased local instance of the same type");
        return NULL;
    }
    if (Py_TYPE(copy)->tp_dictoffset != 0) {
        PyObject *dict = PyObject_GenericGetDict(copy, NULL);
        if (dict == NULL) {
            Py_DECREF(copy);
            return NULL;
        }
        PyObject *fresh = NULL;
        if (PyObject_CheckAccess(dict) != NULL) {
            fresh = _PyDict_CopyStorage(dict);
        }
        Py_DECREF(dict);
        if (fresh == NULL) {
            Py_DECREF(copy);
            return NULL;
        }
        int err = _PyObject_SetDict(copy, fresh);
        Py_DECREF(fresh);
        if (err < 0) {
            Py_DECREF(copy);
            return NULL;
        }
    }
    return copy;
}

static PyObject *
lock_protect(PyObject *op, PyObject *value)
{
    lockobject *self = lockobject_CAST(op);
    PyThreadState *tstate = _PyThreadState_GET();
    int owned;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    owned = PyMutex_IsLocked(&self->state->lock.plain) && lock_context_owned(self->state, tstate);
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (!owned) {
        PyErr_SetString(PyExc_UnprotectedAccessException,
                        "protect() requires an owning lock context");
        return NULL;
    }
    PyObject *copy = lock_protected_copy(value);
    if (copy == NULL) {
        return NULL;
    }
    if (_PyThreadState_ReserveHeldMutex(tstate) < 0) {
        Py_DECREF(copy);
        return NULL;
    }
    int private_copy = 1;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    owned = PyMutex_IsLocked(&self->state->lock.plain) && lock_context_owned(self->state, tstate);
    if (owned) {
        private_copy = lock_publish_copy(copy, self->state->mutex_id) == 0;
    }
    if (owned && private_copy) {
        if (!self->state->protective) {
            _PyThreadState_PushHeldMutex(tstate, self->state->mutex_id);
            _PyProtectiveMutex_Register(tstate->interp, self->state);
            self->state->protective = 1;
        }
    }
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (!owned || !private_copy) {
        Py_DECREF(copy);
        PyErr_SetString(owned ? PyExc_TypeError : PyExc_UnprotectedAccessException,
                        owned ? "protect() copy escaped before publication" :
                        "lock context ended during protect()");
        return NULL;
    }
    return copy;
}

/*[clinic input]
_thread.lock.acquire
    blocking: bool = True
    timeout as timeoutobj: object(py_default="-1") = NULL

Lock the lock.

Without argument, this blocks if the lock is already locked
(even by the same thread), waiting for another thread to release
the lock, and return True once the lock is acquired.
With an argument, this will only block if the argument is true,
and the return value reflects whether the lock is acquired.
The blocking operation is interruptible.
[clinic start generated code]*/

static PyObject *
_thread_lock_acquire_impl(lockobject *self, int blocking,
                          PyObject *timeoutobj)
/*[clinic end generated code: output=569d6b25d508bf6f input=73e75b3d2ec32677]*/
{
    PyTime_t timeout;

    if (lock_acquire_parse_timeout(timeoutobj, blocking, &timeout) < 0) {
        return NULL;
    }

    return lock_acquire(self->state, timeout, LOCK_MANUAL);
}

/*[clinic input]
_thread.lock.acquire_lock = _thread.lock.acquire

An obsolete synonym of acquire().
[clinic start generated code]*/

static PyObject *
_thread_lock_acquire_lock_impl(lockobject *self, int blocking,
                               PyObject *timeoutobj)
/*[clinic end generated code: output=ea6c87ea13b56694 input=5e65bd56327ebe85]*/
{
    return _thread_lock_acquire_impl(self, blocking, timeoutobj);
}

/*[clinic input]
_thread.lock.release

Release the lock.

Allows another thread that is blocked waiting for
the lock to acquire the lock.  The lock must be in the locked state,
but it needn't be locked by the same thread that unlocks it.
[clinic start generated code]*/

static PyObject *
_thread_lock_release_impl(lockobject *self)
/*[clinic end generated code: output=a4ab0d75d6e9fb73 input=dfe48f962dfe99b4]*/
{
    return lock_release(self->state, LOCK_MANUAL);
}

/*[clinic input]
_thread.lock.release_lock

An obsolete synonym of release().
[clinic start generated code]*/

static PyObject *
_thread_lock_release_lock_impl(lockobject *self)
/*[clinic end generated code: output=43025044d51789bb input=74d91374fc601433]*/
{
    return _thread_lock_release_impl(self);
}

/*[clinic input]
_thread.lock.__enter__

Lock the lock.
[clinic start generated code]*/

static PyObject *
_thread_lock___enter___impl(lockobject *self)
/*[clinic end generated code: output=f27725de751ae064 input=8f982991608d38e7]*/
{
    return lock_acquire(self->state, -1, LOCK_CONTEXT);
}

/*[clinic input]
_thread.lock.__exit__
    exc_type: object
    exc_value: object
    exc_tb: object
    /

Release the lock.
[clinic start generated code]*/

static PyObject *
_thread_lock___exit___impl(lockobject *self, PyObject *exc_type,
                           PyObject *exc_value, PyObject *exc_tb)
/*[clinic end generated code: output=c9e8eefa69beed07 input=c74d4abe15a6c037]*/
{
    return lock_release(self->state, LOCK_CONTEXT);
}


/*[clinic input]
_thread.lock.locked

Return whether the lock is in the locked state.
[clinic start generated code]*/

static PyObject *
_thread_lock_locked_impl(lockobject *self)
/*[clinic end generated code: output=63bb94e5a9efa382 input=d8e3d64861bbce73]*/
{
    return PyBool_FromLong(PyMutex_IsLocked(&self->state->lock.plain));
}

/*[clinic input]
_thread.lock.locked_lock

An obsolete synonym of locked().
[clinic start generated code]*/

static PyObject *
_thread_lock_locked_lock_impl(lockobject *self)
/*[clinic end generated code: output=f747c8329e905f8e input=500b0c3592f9bf84]*/
{
    return _thread_lock_locked_impl(self);
}

static PyObject *
lock_repr(PyObject *op)
{
    lockobject *self = lockobject_CAST(op);
    return PyUnicode_FromFormat("<%s %s object at %p>",
        PyMutex_IsLocked(&self->state->lock.plain) ? "locked" : "unlocked", Py_TYPE(self)->tp_name, self);
}

#ifdef HAVE_FORK
/*[clinic input]
_thread.lock._at_fork_reinit
[clinic start generated code]*/

static PyObject *
_thread_lock__at_fork_reinit_impl(lockobject *self)
/*[clinic end generated code: output=d8609f2d3bfa1fd5 input=a970cb76e2a0a131]*/
{
    int protective;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    protective = self->state->protective;
    if (!protective) {
        _PyMutex_at_fork_reinit(&self->state->lock.plain);
        self->state->context_group = 0;
        self->state->context_thread = 0;
    }
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (protective) {
        PyErr_SetString(PyExc_RuntimeError, "cannot reset a protective lock");
        return NULL;
    }
    Py_RETURN_NONE;
}
#endif  /* HAVE_FORK */

/*[clinic input]
@classmethod
_thread.lock.__new__ as lock_new
[clinic start generated code]*/

static PyObject *
lock_new_impl(PyTypeObject *type)
/*[clinic end generated code: output=eab660d5a4c05c8a input=260208a4e277d250]*/
{
    lockobject *self = (lockobject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }
    self->state = _PyProtectiveMutex_New(0);
    if (self->state == NULL) {
        Py_DECREF(self);
        return NULL;
    }
    if (PyObject_DeclareSynchronized((PyObject *)self) < 0) {
        Py_DECREF(self);
        return NULL;
    }
    return (PyObject *)self;
}


static PyMethodDef lock_methods[] = {
    {"protect", lock_protect, METH_O,
     PyDoc_STR("Create a protected shallow copy while holding this lock's context.")},
    _THREAD_LOCK_ACQUIRE_LOCK_METHODDEF
    _THREAD_LOCK_ACQUIRE_METHODDEF
    _THREAD_LOCK_RELEASE_LOCK_METHODDEF
    _THREAD_LOCK_RELEASE_METHODDEF
    _THREAD_LOCK_LOCKED_LOCK_METHODDEF
    _THREAD_LOCK_LOCKED_METHODDEF
    _THREAD_LOCK___ENTER___METHODDEF
    _THREAD_LOCK___EXIT___METHODDEF
#ifdef HAVE_FORK
    _THREAD_LOCK__AT_FORK_REINIT_METHODDEF
#endif
    {NULL,           NULL}              /* sentinel */
};

PyDoc_STRVAR(lock_doc,
"lock()\n\
--\n\
\n\
A lock object is a synchronization primitive.  To create a lock,\n\
call threading.Lock().  Methods are:\n\
\n\
acquire() -- lock the lock, possibly blocking until it can be obtained\n\
release() -- unlock of the lock\n\
locked() -- test whether the lock is currently locked\n\
\n\
A lock is not owned by the thread that locked it; another thread may\n\
unlock it.  A thread attempting to lock a lock that it has already locked\n\
will block until another thread unlocks it.  Deadlocks may ensue.");

static PyType_Slot lock_type_slots[] = {
    {Py_nb_add, lock_add},
    {Py_tp_dealloc, lock_dealloc},
    {Py_tp_repr, lock_repr},
    {Py_tp_doc, (void *)lock_doc},
    {Py_tp_methods, lock_methods},
    {Py_tp_traverse, _PyObject_VisitType},
    {Py_tp_new, lock_new},
    {0, 0}
};

static PyType_Spec lock_type_spec = {
    .name = "_thread.lock",
    .basicsize = sizeof(lockobject),
    .flags = (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC |
              Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_MANAGED_WEAKREF),
    .slots = lock_type_slots,
};

/* Recursive lock objects */

static int
rlock_context_owned(_PyProtectiveMutexState *state, PyThreadState *tstate)
{
    return state->context_only &&
           state->context_group == tstate->threadgroup->id &&
           state->context_thread == tstate->id &&
           _PyRecursiveMutex_IsLockedByCurrentThread(&state->lock.recursive);
}

static PyObject *
rlock_acquire(_PyProtectiveMutexState *state, PyTime_t timeout, int context)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyTime_t deadline = timeout > 0 ? _PyDeadline_Init(timeout) : 0;
    for (;;) {
        if (context && _PyThreadState_ReserveHeldMutex(tstate) < 0) {
            return NULL;
        }
        int acquired = 0;
        int forbidden = 0;
        int overflow = 0;
        PyMutex_LockFlags(&state->metadata_mutex, 0);
        int recursive = _PyRecursiveMutex_IsLockedByCurrentThread(&state->lock.recursive);
        if (state->protective &&
            (!context || (recursive && !rlock_context_owned(state, tstate)))) {
            forbidden = 1;
        }
        else if (recursive &&
                 _Py_atomic_load_uintptr_relaxed(&state->lock.recursive.level) == UINTPTR_MAX) {
            overflow = 1;
        }
        else if (_PyRecursiveMutex_LockTimed(&state->lock.recursive, 0, 0) == PY_LOCK_ACQUIRED) {
            if (!recursive) {
                state->context_epoch++;
                state->context_group = tstate->threadgroup->id;
                state->context_thread = tstate->id;
                state->context_only = context;
                if (state->protective) {
                    _PyThreadState_PushHeldMutex(tstate, state->mutex_id);
                }
            }
            else if (!context || state->context_group != tstate->threadgroup->id ||
                     state->context_thread != tstate->id) {
                state->context_only = 0;
            }
            acquired = 1;
        }
        PyMutex_Unlock(&state->metadata_mutex);
        if (forbidden) {
            PyErr_SetString(PyExc_RuntimeError,
                            "protective locks can only be acquired with an owning context");
            return NULL;
        }
        if (overflow) {
            PyErr_SetString(PyExc_OverflowError, "RLock recursion count overflow");
            return NULL;
        }
        if (acquired) {
            Py_RETURN_TRUE;
        }
        if (timeout == 0) {
            Py_RETURN_FALSE;
        }
        if (Py_IsFinalizing()) {
            PyErr_SetString(PyExc_PythonFinalizationError,
                            "cannot acquire lock at interpreter finalization");
            return NULL;
        }
        uint8_t locked = _Py_LOCKED;
        int result = _PyParkingLot_Park(&state->lock.recursive.mutex._bits, &locked,
                                       sizeof(locked), timeout, NULL, 1);
        if (result == Py_PARK_INTR && Py_MakePendingCalls() < 0) {
            return NULL;
        }
        if (result == Py_PARK_TIMEOUT) {
            Py_RETURN_FALSE;
        }
        if (deadline) {
            timeout = Py_MAX(_PyDeadline_Get(deadline), 0);
        }
    }
}

static PyObject *
rlock_release(_PyProtectiveMutexState *state, int context)
{
    PyThreadState *tstate = _PyThreadState_GET();
    int error = 0;
    int wake = 0;
    PyMutex_LockFlags(&state->metadata_mutex, 0);
    if (state->protective && (!context || !rlock_context_owned(state, tstate))) {
        error = 1;
    }
    else if (context == LOCK_COMPOUND_CONTEXT &&
             (state->context_group != tstate->threadgroup->id ||
              state->context_thread != tstate->id)) {
        error = 1;
    }
    else if (!_PyRecursiveMutex_IsLockedByCurrentThread(&state->lock.recursive)) {
        error = 2;
    }
    else {
        if (_Py_atomic_load_uintptr_relaxed(&state->lock.recursive.level) == 0) {
            if (state->protective) {
                int removed = _PyThreadState_RemoveHeldMutex(tstate, state->mutex_id);
                assert(removed);
                (void)removed;
            }
            state->context_group = 0;
            state->context_thread = 0;
            state->context_only = 0;
            wake = 1;
        }
        else if (!context) {
            state->context_only = 0;
        }
        int unlocked = _PyRecursiveMutex_TryUnlock(&state->lock.recursive);
        assert(unlocked == 0);
        (void)unlocked;
    }
    PyMutex_Unlock(&state->metadata_mutex);
    if (error) {
        PyErr_SetString(PyExc_RuntimeError, error == 1 ?
                        "protective locks can only be released by their owning context" :
                        "cannot release un-acquired lock");
        return NULL;
    }
    if (wake) {
        _PyParkingLot_UnparkAll(&state->lock.recursive.mutex._bits);
    }
    Py_RETURN_NONE;
}

/* Run with the real protecting mutex, including when its wrapper has died. */
int
_PyProtectiveMutex_CallFinalizer(PyObject *op)
{
    PyThreadState *tstate = _PyThreadState_GET();
    _PyProtectiveMutexState *state = _PyProtectiveMutex_Find(
        tstate->interp, _Py_atomic_load_uint32_relaxed(&op->ob_owner_id));
    if (state == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "protecting mutex is unavailable");
        return -1;
    }
    PyObject *acquired = state->recursive ?
        rlock_acquire(state, 0, LOCK_CONTEXT) :
        lock_acquire(state, 0, LOCK_CONTEXT);
    if (acquired == Py_False) {
        Py_CLEAR(acquired);
        if (finalizer_can_wait(tstate) == 0) {
            acquired = state->recursive ?
                rlock_acquire(state, -1, LOCK_CONTEXT) :
                lock_acquire(state, -1, LOCK_CONTEXT);
        }
    }
    if (acquired == NULL) {
        _PyProtectiveMutex_Decref(state);
        return -1;
    }
    assert(acquired == Py_True);
    Py_DECREF(acquired);
    PyMutex_LockFlags(&state->metadata_mutex, 0);
    uint64_t epoch = state->context_epoch;
    PyMutex_Unlock(&state->metadata_mutex);
    if (Py_TYPE(op)->tp_finalize != NULL) {
        Py_TYPE(op)->tp_finalize(op);
    }
    /* A callback may explicitly exit this context and acquire a new one.
       Never release that new context, or another thread's acquisition. */
    PyMutex_LockFlags(&state->metadata_mutex, 0);
    int release = state->context_epoch == epoch &&
                  state->context_group == tstate->threadgroup->id &&
                  state->context_thread == tstate->id;
    PyMutex_Unlock(&state->metadata_mutex);
    PyObject *result = NULL;
    if (release) {
        result = state->recursive ?
            rlock_release(state, LOCK_CONTEXT) :
            lock_release(state, LOCK_CONTEXT);
    }
    _PyProtectiveMutex_Decref(state);
    if (release && result == NULL) {
        return -1;
    }
    Py_XDECREF(result);
    return 0;
}

static PyObject *
rlock_protect(PyObject *op, PyObject *value)
{
    rlockobject *self = rlockobject_CAST(op);
    PyThreadState *tstate = _PyThreadState_GET();
    int owned;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    owned = rlock_context_owned(self->state, tstate);
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (!owned) {
        PyErr_SetString(PyExc_UnprotectedAccessException,
                        "protect() requires exclusively owning lock contexts");
        return NULL;
    }
    PyObject *copy = lock_protected_copy(value);
    if (copy == NULL) {
        return NULL;
    }
    if (_PyThreadState_ReserveHeldMutex(tstate) < 0) {
        Py_DECREF(copy);
        return NULL;
    }
    int private_copy = 1;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    owned = rlock_context_owned(self->state, tstate);
    if (owned) {
        private_copy = lock_publish_copy(copy, self->state->mutex_id) == 0;
    }
    if (owned && private_copy) {
        if (!self->state->protective) {
            /* One held-mutex entry lasts until the outermost release, including
               when protect() is first called inside nested contexts. */
            _PyThreadState_PushHeldMutex(tstate, self->state->mutex_id);
            _PyProtectiveMutex_Register(tstate->interp, self->state);
            self->state->protective = 1;
        }
    }
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (!owned || !private_copy) {
        Py_DECREF(copy);
        PyErr_SetString(owned ? PyExc_TypeError : PyExc_UnprotectedAccessException,
                        owned ? "protect() copy escaped before publication" :
                        "lock context ended during protect()");
        return NULL;
    }
    return copy;
}

static int
rlock_locked_impl(rlockobject *self)
{
    return PyMutex_IsLocked(&self->state->lock.recursive.mutex);
}

static void
rlock_dealloc(PyObject *self)
{
    PyObject_GC_UnTrack(self);
    PyObject_ClearWeakRefs(self);
    _PyProtectiveMutex_Decref(((rlockobject *)self)->state);
    PyTypeObject *tp = Py_TYPE(self);
    tp->tp_free(self);
    Py_DECREF(tp);
}

/*[clinic input]
_thread.RLock.acquire
    blocking: bool = True
    timeout as timeoutobj: object(py_default="-1") = NULL

Lock the lock.

`blocking` indicates whether we should wait
for the lock to be available or not.  If `blocking` is False
and another thread holds the lock, the method will return False
immediately.  If `blocking` is True and another thread holds
the lock, the method will wait for the lock to be released,
take it and then return True.
(note: the blocking operation is interruptible.)

In all other cases, the method will return True immediately.
Precisely, if the current thread already holds the lock, its
internal counter is simply incremented. If nobody holds the lock,
the lock is taken and its internal counter initialized to 1.
[clinic start generated code]*/

static PyObject *
_thread_RLock_acquire_impl(rlockobject *self, int blocking,
                           PyObject *timeoutobj)
/*[clinic end generated code: output=73df5af6f67c1513 input=d55a0f5014522a8d]*/
{
    PyTime_t timeout;

    if (lock_acquire_parse_timeout(timeoutobj, blocking, &timeout) < 0) {
        return NULL;
    }

    return rlock_acquire(self->state, timeout, LOCK_MANUAL);
}

/*[clinic input]
_thread.RLock.__enter__

Lock the lock.
[clinic start generated code]*/

static PyObject *
_thread_RLock___enter___impl(rlockobject *self)
/*[clinic end generated code: output=63135898476bf89f input=33be37f459dca390]*/
{
    return rlock_acquire(self->state, -1, LOCK_CONTEXT);
}

/*[clinic input]
_thread.RLock.release

Release the lock.

Allows another thread that is blocked waiting for the lock
to acquire the lock.  The lock must be in the locked state,
and must be locked by the same thread that unlocks it; otherwise a
`RuntimeError` is raised.

Do note that if the lock was acquire()d several times in a row by
the current thread, release() needs to be called as many times for
the lock to be available for other threads.
[clinic start generated code]*/

static PyObject *
_thread_RLock_release_impl(rlockobject *self)
/*[clinic end generated code: output=51f4a013c5fae2c5 input=7c188f60189be13a]*/
{
    return rlock_release(self->state, LOCK_MANUAL);
}

/*[clinic input]
_thread.RLock.__exit__
    exc_type: object
    exc_value: object
    exc_tb: object
    /

Release the lock.

[clinic start generated code]*/

static PyObject *
_thread_RLock___exit___impl(rlockobject *self, PyObject *exc_type,
                            PyObject *exc_value, PyObject *exc_tb)
/*[clinic end generated code: output=79bb44d551aedeb5 input=79accf0778d91002]*/
{
    return rlock_release(self->state, LOCK_CONTEXT);
}

/*[clinic input]
_thread.RLock.locked

Return a boolean indicating whether this object is locked right now.
[clinic start generated code]*/

static PyObject *
_thread_RLock_locked_impl(rlockobject *self)
/*[clinic end generated code: output=e9b6060492b3f94e input=8866d9237ba5391b]*/
{
    int is_locked = rlock_locked_impl(self);
    return PyBool_FromLong(is_locked);
}

/*[clinic input]
_thread.RLock._acquire_restore
    state: object
    /

For internal use by `threading.Condition`.
[clinic start generated code]*/

static PyObject *
_thread_RLock__acquire_restore_impl(rlockobject *self, PyObject *state)
/*[clinic end generated code: output=beb8f2713a35e775 input=c8f2094fde059447]*/
{
    PyThread_ident_t owner;
    Py_ssize_t count;

    if (!PyArg_Parse(state, "(n" Py_PARSE_THREAD_IDENT_T "):_acquire_restore",
            &count, &owner))
        return NULL;

    PyObject *acquired = rlock_acquire(self->state, -1, LOCK_MANUAL);
    if (acquired == NULL) {
        return NULL;
    }
    Py_DECREF(acquired);
    int error = 0;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    /* A concurrent ordinary _at_fork_reinit can invalidate the acquisition. */
    if (self->state->protective ||
        !_PyRecursiveMutex_IsLockedByCurrentThread(&self->state->lock.recursive)) {
        error = 1;
    }
    else {
        _Py_atomic_store_ullong_relaxed(&self->state->lock.recursive.thread, owner);
        _Py_atomic_store_uintptr_relaxed(&self->state->lock.recursive.level, (uintptr_t)count - 1);
        self->state->context_only = 0;
    }
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (error) {
        PyErr_SetString(PyExc_RuntimeError, "cannot restore RLock ownership");
        return NULL;
    }
    Py_RETURN_NONE;
}


/*[clinic input]
_thread.RLock._release_save

For internal use by `threading.Condition`.
[clinic start generated code]*/

static PyObject *
_thread_RLock__release_save_impl(rlockobject *self)
/*[clinic end generated code: output=d2916487315bea93 input=809d227cfc4a112c]*/
{
    int error = 0;
    PyThread_ident_t owner = 0;
    Py_ssize_t count = 0;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    if (self->state->protective) {
        error = 1;
    }
    else if (!_PyRecursiveMutex_IsLockedByCurrentThread(&self->state->lock.recursive)) {
        error = 2;
    }
    else {
        owner = _Py_atomic_load_ullong_relaxed(&self->state->lock.recursive.thread);
        count = _Py_atomic_load_uintptr_relaxed(&self->state->lock.recursive.level) + 1;
        // Ensure the unlock releases the lock.
        _Py_atomic_store_uintptr_relaxed(&self->state->lock.recursive.level, 0);
        self->state->context_group = 0;
        self->state->context_thread = 0;
        self->state->context_only = 0;
        _PyRecursiveMutex_Unlock(&self->state->lock.recursive);
    }
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (error) {
        PyErr_SetString(PyExc_RuntimeError, error == 1 ?
                        "cannot suspend a protective lock context" :
                        "cannot release un-acquired lock");
        return NULL;
    }
    _PyParkingLot_UnparkAll(&self->state->lock.recursive.mutex._bits);
    return Py_BuildValue("n" Py_PARSE_THREAD_IDENT_T, count, owner);
}


/*[clinic input]
_thread.RLock._recursion_count

For internal use by reentrancy checks.
[clinic start generated code]*/

static PyObject *
_thread_RLock__recursion_count_impl(rlockobject *self)
/*[clinic end generated code: output=7993fb9695ef2c4d input=7fd1834cd7a4b044]*/
{
    if (_PyRecursiveMutex_IsLockedByCurrentThread(&self->state->lock.recursive)) {
        return PyLong_FromSize_t(
            _Py_atomic_load_uintptr_relaxed(&self->state->lock.recursive.level) + 1);
    }
    return PyLong_FromLong(0);
}


/*[clinic input]
_thread.RLock._is_owned

For internal use by `threading.Condition`.
[clinic start generated code]*/

static PyObject *
_thread_RLock__is_owned_impl(rlockobject *self)
/*[clinic end generated code: output=bf14268a3cabbe07 input=fba6535538deb858]*/
{
    long owned = _PyRecursiveMutex_IsLockedByCurrentThread(&self->state->lock.recursive);
    return PyBool_FromLong(owned);
}

/*[clinic input]
@classmethod
_thread.RLock.__new__ as rlock_new
[clinic start generated code]*/

static PyObject *
rlock_new_impl(PyTypeObject *type)
/*[clinic end generated code: output=bb4fb1edf6818df5 input=013591361bf1ac6e]*/
{
    rlockobject *self = (rlockobject *) type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }
    self->state = _PyProtectiveMutex_New(1);
    if (self->state == NULL) {
        Py_DECREF(self);
        return NULL;
    }
    thread_module_state *state = get_thread_state_by_cls(type);
    if (state == NULL) {
        Py_DECREF(self);
        return NULL;
    }
    // A Python subclass may add mutable state that has no internal locking.
    if (type == state->rlock_type &&
        PyObject_DeclareSynchronized((PyObject *)self) < 0) {
        Py_DECREF(self);
        return NULL;
    }

    return (PyObject *) self;
}

static PyObject *
rlock_repr(PyObject *op)
{
    rlockobject *self = rlockobject_CAST(op);
    PyThread_ident_t owner = FT_ATOMIC_LOAD_ULLONG_RELAXED(self->state->lock.recursive.thread);
    int locked = rlock_locked_impl(self);
    size_t count;
    if (locked) {
        count = _Py_atomic_load_uintptr_relaxed(&self->state->lock.recursive.level) + 1;
    }
    else {
        count = 0;
    }
    return PyUnicode_FromFormat(
        "<%s %s object owner=%" PY_FORMAT_THREAD_IDENT_T " count=%zu at %p>",
        locked ? "locked" : "unlocked",
        Py_TYPE(self)->tp_name, owner,
        count, self);
}


#ifdef HAVE_FORK
/*[clinic input]
_thread.RLock._at_fork_reinit
[clinic start generated code]*/

static PyObject *
_thread_RLock__at_fork_reinit_impl(rlockobject *self)
/*[clinic end generated code: output=d77a4ce40351817c input=a3b625b026a8df4f]*/
{
    int protective;
    PyMutex_LockFlags(&self->state->metadata_mutex, 0);
    protective = self->state->protective;
    if (!protective) {
        self->state->lock.recursive = (_PyRecursiveMutex){0};
        self->state->context_group = 0;
        self->state->context_thread = 0;
        self->state->context_only = 0;
    }
    PyMutex_Unlock(&self->state->metadata_mutex);
    if (protective) {
        PyErr_SetString(PyExc_RuntimeError, "cannot reset a protective lock");
        return NULL;
    }
    Py_RETURN_NONE;
}
#endif  /* HAVE_FORK */


static PyMethodDef rlock_methods[] = {
    {"protect", rlock_protect, METH_O,
     PyDoc_STR("Create a protected shallow copy while holding this lock's contexts.")},
    _THREAD_RLOCK_ACQUIRE_METHODDEF
    _THREAD_RLOCK_RELEASE_METHODDEF
    _THREAD_RLOCK_LOCKED_METHODDEF
    _THREAD_RLOCK__IS_OWNED_METHODDEF
    _THREAD_RLOCK__ACQUIRE_RESTORE_METHODDEF
    _THREAD_RLOCK__RELEASE_SAVE_METHODDEF
    _THREAD_RLOCK__RECURSION_COUNT_METHODDEF
    _THREAD_RLOCK___ENTER___METHODDEF
    _THREAD_RLOCK___EXIT___METHODDEF
#ifdef HAVE_FORK
    _THREAD_RLOCK__AT_FORK_REINIT_METHODDEF
#endif
    {NULL,           NULL}              /* sentinel */
};


static PyType_Slot rlock_type_slots[] = {
    {Py_nb_add, lock_add},
    {Py_tp_dealloc, rlock_dealloc},
    {Py_tp_repr, rlock_repr},
    {Py_tp_methods, rlock_methods},
    {Py_tp_alloc, PyType_GenericAlloc},
    {Py_tp_new, rlock_new},
    {Py_tp_traverse, _PyObject_VisitType},
    {0, 0},
};

static PyType_Spec rlock_type_spec = {
    .name = "_thread.RLock",
    .basicsize = sizeof(rlockobject),
    .flags = (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE |
              Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_MANAGED_WEAKREF),
    .slots = rlock_type_slots,
};

/* Compound locks contain a sorted, deduplicated tuple of native locks.
   Context records belong to Python threads, not to ThreadGroups. */

static uint32_t
compound_member_id(PyObject *member, thread_module_state *state)
{
    if (Py_IS_TYPE(member, state->lock_type)) {
        return lockobject_CAST(member)->state->mutex_id;
    }
    assert(Py_IS_TYPE(member, state->rlock_type));
    return rlockobject_CAST(member)->state->mutex_id;
}

static Py_ssize_t
compound_operand_size(PyObject *op, thread_module_state *state)
{
    if (Py_IS_TYPE(op, state->lock_type) || Py_IS_TYPE(op, state->rlock_type)) {
        return 1;
    }
    if (Py_IS_TYPE(op, state->compound_lock_type)) {
        return PyTuple_GET_SIZE(((compoundlockobject *)op)->locks);
    }
    return -1;
}

static PyObject *
compound_operand_item(PyObject *op, Py_ssize_t index, thread_module_state *state)
{
    if (Py_IS_TYPE(op, state->compound_lock_type)) {
        return PyTuple_GET_ITEM(((compoundlockobject *)op)->locks, index);
    }
    assert(index == 0);
    return op;
}

static PyObject *
lock_add(PyObject *left, PyObject *right)
{
    /* nb_add can be invoked with the native lock on either side. */
    PyTypeObject *type = Py_TYPE(left);
    if (type->tp_as_number == NULL || type->tp_as_number->nb_add != lock_add) {
        type = Py_TYPE(right);
    }
    thread_module_state *state = get_thread_state_by_cls(type);
    if (state == NULL) {
        return NULL;
    }
    Py_ssize_t left_size = compound_operand_size(left, state);
    Py_ssize_t right_size = compound_operand_size(right, state);
    if (left_size < 0 || right_size < 0) {
        Py_RETURN_NOTIMPLEMENTED;
    }
    if (left_size > PY_SSIZE_T_MAX - right_size) {
        return PyErr_NoMemory();
    }
    PyObject *members = PyTuple_New(left_size + right_size);
    if (members == NULL) {
        return NULL;
    }
    Py_ssize_t i = 0, j = 0, count = 0;
    while (i < left_size || j < right_size) {
        PyObject *a = i < left_size ? compound_operand_item(left, i, state) : NULL;
        PyObject *b = j < right_size ? compound_operand_item(right, j, state) : NULL;
        PyObject *member;
        if (b == NULL || (a != NULL &&
                         compound_member_id(a, state) < compound_member_id(b, state))) {
            member = a;
            i++;
        }
        else if (a == NULL || compound_member_id(b, state) < compound_member_id(a, state)) {
            member = b;
            j++;
        }
        else {
            assert(a == b);
            member = a;
            i++;
            j++;
        }
        PyTuple_SET_ITEM(members, count++, Py_NewRef(member));
    }
    if (_PyTuple_Resize(&members, count) < 0) {
        return NULL;
    }
    compoundlockobject *self = (compoundlockobject *)
        state->compound_lock_type->tp_alloc(state->compound_lock_type, 0);
    if (self == NULL) {
        Py_DECREF(members);
        return NULL;
    }
    self->locks = members;
    if (PyObject_DeclareSynchronized((PyObject *)self) < 0) {
        Py_DECREF(self);
        return NULL;
    }
    return (PyObject *)self;
}

static int
compound_release_members(compoundlockobject *self, Py_ssize_t count,
                         thread_module_state *state)
{
    /* Preserve the original acquisition error during rollback. On exit,
       attempt every release and propagate the first failure. */
    PyObject *error = PyErr_GetRaisedException();
    while (count > 0) {
        PyObject *member = PyTuple_GET_ITEM(self->locks, --count);
        PyObject *result;
        if (Py_IS_TYPE(member, state->lock_type)) {
            result = lock_release(lockobject_CAST(member)->state, LOCK_COMPOUND_CONTEXT);
        }
        else {
            result = rlock_release(rlockobject_CAST(member)->state, LOCK_COMPOUND_CONTEXT);
        }
        if (result == NULL) {
            if (error == NULL) {
                error = PyErr_GetRaisedException();
            }
            else {
                PyErr_Clear();
            }
        }
        else {
            Py_DECREF(result);
        }
    }
    if (error != NULL) {
        PyErr_SetRaisedException(error);
        return -1;
    }
    return 0;
}

static PyObject *
compound_enter(PyObject *op, PyObject *unused)
{
    compoundlockobject *self = (compoundlockobject *)op;
    thread_module_state *state = get_thread_state_by_cls(Py_TYPE(op));
    if (state == NULL) {
        return NULL;
    }
    compound_context *context = PyMem_Malloc(sizeof(*context));
    if (context == NULL) {
        return PyErr_NoMemory();
    }
    PyThreadState *tstate = _PyThreadState_GET();
    context->group = tstate->threadgroup->id;
    context->thread = tstate->id;
    Py_ssize_t count = PyTuple_GET_SIZE(self->locks);
    for (Py_ssize_t i = 0; i < count; i++) {
        PyObject *member = PyTuple_GET_ITEM(self->locks, i);
        PyObject *result;
        if (Py_IS_TYPE(member, state->lock_type)) {
            result = lock_acquire(lockobject_CAST(member)->state, -1, LOCK_COMPOUND_CONTEXT);
        }
        else {
            result = rlock_acquire(rlockobject_CAST(member)->state, -1, LOCK_COMPOUND_CONTEXT);
        }
        if (result == NULL) {
            compound_release_members(self, i, state);
            PyMem_Free(context);
            return NULL;
        }
        assert(result == Py_True);
        Py_DECREF(result);
    }
    Py_BEGIN_CRITICAL_SECTION(self);
    context->next = self->contexts;
    self->contexts = context;
    Py_END_CRITICAL_SECTION();
    return Py_NewRef(op);
}

static PyObject *
compound_exit(PyObject *op, PyObject *args)
{
    PyObject *exc_type, *exc_value, *exc_tb;
    if (!PyArg_UnpackTuple(args, "__exit__", 3, 3, &exc_type, &exc_value, &exc_tb)) {
        return NULL;
    }
    compoundlockobject *self = (compoundlockobject *)op;
    thread_module_state *state = get_thread_state_by_cls(Py_TYPE(op));
    if (state == NULL) {
        return NULL;
    }
    PyThreadState *tstate = _PyThreadState_GET();
    compound_context *context = NULL;
    Py_BEGIN_CRITICAL_SECTION(self);
    compound_context **link = &self->contexts;
    while (*link != NULL) {
        if ((*link)->group == tstate->threadgroup->id && (*link)->thread == tstate->id) {
            context = *link;
            *link = context->next;
            break;
        }
        link = &(*link)->next;
    }
    Py_END_CRITICAL_SECTION();
    if (context == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "no compound lock context owned by this thread");
        return NULL;
    }
    PyMem_Free(context);
    if (compound_release_members(self, PyTuple_GET_SIZE(self->locks), state) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static int
compound_traverse(PyObject *op, visitproc visit, void *arg)
{
    compoundlockobject *self = (compoundlockobject *)op;
    Py_VISIT(Py_TYPE(op));
    Py_VISIT(self->locks);
    return 0;
}

static void
compound_dealloc(PyObject *op)
{
    compoundlockobject *self = (compoundlockobject *)op;
    PyObject_GC_UnTrack(op);
    Py_XDECREF(self->locks);
    compound_context *context = self->contexts;
    while (context != NULL) {
        compound_context *next = context->next;
        PyMem_Free(context);
        context = next;
    }
    PyTypeObject *type = Py_TYPE(op);
    type->tp_free(op);
    Py_DECREF(type);
}

static PyMethodDef compound_methods[] = {
    {"__enter__", compound_enter, METH_NOARGS, NULL},
    {"__exit__", compound_exit, METH_VARARGS, NULL},
    {NULL, NULL}
};

static PyType_Slot compound_type_slots[] = {
    {Py_nb_add, lock_add},
    {Py_tp_dealloc, compound_dealloc},
    {Py_tp_traverse, compound_traverse},
    {Py_tp_methods, compound_methods},
    {0, NULL}
};

static PyType_Spec compound_type_spec = {
    .name = "_thread._CompoundLock",
    .basicsize = sizeof(compoundlockobject),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC |
             Py_TPFLAGS_IMMUTABLETYPE | Py_TPFLAGS_DISALLOW_INSTANTIATION,
    .slots = compound_type_slots,
};

/* Thread-local objects */

/* Quick overview:

   We need to be able to reclaim reference cycles as soon as possible
   (both when a thread is being terminated, or a thread-local object
    becomes unreachable from user data).  Constraints:
   - it must not be possible for thread-state dicts to be involved in
     reference cycles (otherwise the cyclic GC will refuse to consider
     objects referenced from a reachable thread-state dict, even though
     local_dealloc would clear them)
   - the death of a thread-state dict must still imply destruction of the
     corresponding local dicts in all thread-local objects.

   Our implementation uses small "localdummy" objects in order to break
   the reference chain. These trivial objects are hashable (using the
   default scheme of identity hashing) and weakrefable.

   Each thread-state holds two separate localdummy objects:

   - `threading_local_key` is used as a key to retrieve the locals dictionary
     for the thread in any `threading.local` object.
   - `threading_local_sentinel` is used to signal when a thread is being
     destroyed. Consequently, the associated thread-state must hold the only
     reference.

   Each `threading.local` object contains a dict mapping localdummy keys to
   locals dicts and a set containing weak references to localdummy
   sentinels. Each sentinel weak reference has a callback that removes itself
   and the locals dict for the key from the `threading.local` object when
   called.

   Therefore:
   - The thread-state only holds strong references to localdummy objects, which
     cannot participate in cycles.
   - Only outside objects (application- or library-level) hold strong
     references to the thread-local objects.
   - As soon as thread-state's sentinel dummy is destroyed the callbacks for
     all weakrefs attached to the sentinel are called, and destroy the
     corresponding local dicts from thread-local objects.
   - As soon as a thread-local object is destroyed, its local dicts are
     destroyed.
   - The GC can do its work correctly when a thread-local object is dangling,
     without any interference from the thread-state dicts.

   This dual key arrangement is necessary to ensure that `threading.local`
   values can be retrieved from finalizers. If we were to only keep a mapping
   of localdummy weakrefs to locals dicts it's possible that the weakrefs would
   be cleared before finalizers were called (GC currently clears weakrefs that
   are garbage before invoking finalizers), causing lookups in finalizers to
   fail.
*/

typedef struct {
    PyObject_HEAD
    PyObject *weakreflist;      /* List of weak references to self */
} localdummyobject;

#define localdummyobject_CAST(op)   ((localdummyobject *)(op))

static void
localdummy_dealloc(PyObject *op)
{
    localdummyobject *self = localdummyobject_CAST(op);
    FT_CLEAR_WEAKREFS(op, self->weakreflist);
    PyTypeObject *tp = Py_TYPE(self);
    tp->tp_free(self);
    Py_DECREF(tp);
}

static PyMemberDef local_dummy_type_members[] = {
    {"__weaklistoffset__", Py_T_PYSSIZET, offsetof(localdummyobject, weakreflist), Py_READONLY},
    {NULL},
};

static PyType_Slot local_dummy_type_slots[] = {
    {Py_tp_dealloc, localdummy_dealloc},
    {Py_tp_doc, "Thread-local dummy"},
    {Py_tp_members, local_dummy_type_members},
    {0, 0}
};

static PyType_Spec local_dummy_type_spec = {
    .name = "_thread._localdummy",
    .basicsize = sizeof(localdummyobject),
    .flags = (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_DISALLOW_INSTANTIATION |
              Py_TPFLAGS_IMMUTABLETYPE),
    .slots = local_dummy_type_slots,
};


typedef struct {
    PyObject_HEAD
    PyObject *args;
    PyObject *kw;
    PyObject *weakreflist;      /* List of weak references to self */
    /* A {localdummy -> localdict} dict */
    PyObject *localdicts;
    /* A set of weakrefs to thread sentinels localdummies*/
    PyObject *thread_watchdogs;
} localobject;

#define localobject_CAST(op)    ((localobject *)(op))

/* Forward declaration */
static int create_localsdict(localobject *self, thread_module_state *state,
                             PyObject **localsdict, PyObject **sentinel_wr);
static PyObject *clear_locals(PyObject *meth_self, PyObject *dummyweakref);

/* Create a weakref to the sentinel localdummy for the current thread */
static PyObject *
create_sentinel_wr(localobject *self)
{
    static PyMethodDef wr_callback_def = {
        "clear_locals", clear_locals, METH_O
    };

    PyThreadState *tstate = PyThreadState_Get();

    /* We use a weak reference to self in the callback closure
       in order to avoid spurious reference cycles */
    PyObject *self_wr = PyWeakref_NewRef((PyObject *) self, NULL);
    if (self_wr == NULL) {
        return NULL;
    }

    // Callback-free weakrefs can be cached and reused by other threads.
    // A shared local object's control weakref must be accessible there too.
    if (_Py_atomic_load_uint8(&self->ob_base.ob_shareable) == _Py_SHAREABLE_SYNCHRONIZED &&
        PyObject_DeclareSynchronized(self_wr) < 0)
    {
        Py_DECREF(self_wr);
        return NULL;
    }

    PyObject *args = _PyTuple_FromPairSteal(self_wr,
                                            Py_NewRef(tstate->threading_local_key));
    if (args == NULL) {
        return NULL;
    }

    PyObject *cb = PyCFunction_New(&wr_callback_def, args);
    Py_DECREF(args);
    if (cb == NULL) {
        return NULL;
    }

    if (PyObject_DeclareSynchronized(cb) < 0) {
        Py_DECREF(cb);
        return NULL;
    }
    PyObject *wr = PyWeakref_NewRef(tstate->threading_local_sentinel, cb);
    Py_DECREF(cb);
    if (wr != NULL && PyObject_DeclareSynchronized(wr) < 0) {
        Py_CLEAR(wr);
    }
    return wr;
}

static PyObject *
local_new(PyTypeObject *type, PyObject *args, PyObject *kw)
{
    if (type->tp_init == PyBaseObject_Type.tp_init) {
        int rc = 0;
        if (args != NULL)
            rc = PyObject_IsTrue(args);
        if (rc == 0 && kw != NULL)
            rc = PyObject_IsTrue(kw);
        if (rc != 0) {
            if (rc > 0) {
                PyErr_SetString(PyExc_TypeError,
                          "Initialization arguments are not supported");
            }
            return NULL;
        }
    }

    PyObject *module = PyType_GetModuleByDef(type, &thread_module);
    assert(module != NULL);
    thread_module_state *state = get_thread_state(module);

    localobject *self = (localobject *)type->tp_alloc(type, 0);
    if (self == NULL) {
        return NULL;
    }

    // gh-128691: Use deferred reference counting for thread-locals to avoid
    // contention on the shared object.
    _PyObject_SetDeferredRefcount((PyObject *)self);

    self->args = Py_XNewRef(args);
    self->kw = Py_XNewRef(kw);

    self->localdicts = PySynchronizedDict_New();
    if (self->localdicts == NULL) {
        goto err;
    }

    self->thread_watchdogs = PySynchronizedSet_New(NULL);
    if (self->thread_watchdogs == NULL) {
        goto err;
    }

    if (type == state->local_type &&
        PyObject_DeclareSynchronized((PyObject *)self) < 0)
    {
        goto err;
    }

    PyObject *localsdict = NULL;
    PyObject *sentinel_wr = NULL;
    if (create_localsdict(self, state, &localsdict, &sentinel_wr) < 0) {
        goto err;
    }
    Py_DECREF(localsdict);
    Py_DECREF(sentinel_wr);

    return (PyObject *)self;

  err:
    Py_DECREF(self);
    return NULL;
}

static int
local_traverse(PyObject *op, visitproc visit, void *arg)
{
    localobject *self = localobject_CAST(op);
    Py_VISIT(Py_TYPE(self));
    Py_VISIT(self->args);
    Py_VISIT(self->kw);
    Py_VISIT(self->localdicts);
    Py_VISIT(self->thread_watchdogs);
    return 0;
}

static int
local_clear(PyObject *op)
{
    localobject *self = localobject_CAST(op);
    Py_CLEAR(self->args);
    Py_CLEAR(self->kw);
    Py_CLEAR(self->localdicts);
    Py_CLEAR(self->thread_watchdogs);
    return 0;
}

static void
local_dealloc(PyObject *op)
{
    localobject *self = localobject_CAST(op);
    /* Weakrefs must be invalidated right now, otherwise they can be used
       from code called below, which is very dangerous since Py_REFCNT(self) == 0 */
    if (self->weakreflist != NULL) {
        PyObject_ClearWeakRefs(op);
    }
    PyObject_GC_UnTrack(self);
    (void)local_clear(op);
    PyTypeObject *tp = Py_TYPE(self);
    tp->tp_free(self);
    Py_DECREF(tp);
}

/* Create the TLS key and sentinel if they don't exist */
static int
create_localdummies(thread_module_state *state)
{
    PyThreadState *tstate = _PyThreadState_GET();

    if (tstate->threading_local_key != NULL) {
        return 0;
    }

    PyTypeObject *ld_type = state->local_dummy_type;
    tstate->threading_local_key = ld_type->tp_alloc(ld_type, 0);
    if (tstate->threading_local_key == NULL) {
        return -1;
    }

    tstate->threading_local_sentinel = ld_type->tp_alloc(ld_type, 0);
    if (tstate->threading_local_sentinel == NULL) {
        Py_CLEAR(tstate->threading_local_key);
        return -1;
    }

    // These private tokens have identity but no mutable Python-visible state.
    if (PyObject_DeclareImmutable(tstate->threading_local_key) < 0 ||
        PyObject_DeclareImmutable(tstate->threading_local_sentinel) < 0)
    {
        Py_CLEAR(tstate->threading_local_key);
        Py_CLEAR(tstate->threading_local_sentinel);
        return -1;
    }
    return 0;
}

/* Insert a localsdict and sentinel weakref for the current thread, placing
   strong references in localsdict and sentinel_wr, respectively.
*/
static int
create_localsdict(localobject *self, thread_module_state *state,
                  PyObject **localsdict, PyObject **sentinel_wr)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyObject *ldict = NULL;
    PyObject *wr = NULL;

    if (create_localdummies(state) < 0) {
        goto err;
    }

    /* Create and insert the locals dict and sentinel weakref */
    ldict = PyDict_New();
    if (ldict == NULL) {
        goto err;
    }

    if (PyDict_SetItem(self->localdicts, tstate->threading_local_key,
                       ldict) < 0)
    {
        goto err;
    }

    wr = create_sentinel_wr(self);
    if (wr == NULL) {
        PyObject *exc = PyErr_GetRaisedException();
        if (PyDict_DelItem(self->localdicts,
                           tstate->threading_local_key) < 0)
        {
            PyErr_FormatUnraisable("Exception ignored while deleting "
                                   "thread local of %R", self);
        }
        PyErr_SetRaisedException(exc);
        goto err;
    }

    if (PySet_Add(self->thread_watchdogs, wr) < 0) {
        PyObject *exc = PyErr_GetRaisedException();
        if (PyDict_DelItem(self->localdicts,
                           tstate->threading_local_key) < 0)
        {
            PyErr_FormatUnraisable("Exception ignored while deleting "
                                   "thread local of %R", self);
        }
        PyErr_SetRaisedException(exc);
        goto err;
    }

    *localsdict = ldict;
    *sentinel_wr = wr;
    return 0;

err:
    Py_XDECREF(ldict);
    Py_XDECREF(wr);
    return -1;
}

/* Return a strong reference to the locals dict for the current thread,
   creating it if necessary.
*/
static PyObject *
_ldict(localobject *self, thread_module_state *state)
{
    if (create_localdummies(state) < 0) {
        return NULL;
    }

    /* Check if a localsdict already exists */
    PyObject *ldict;
    PyThreadState *tstate = _PyThreadState_GET();
    if (PyDict_GetItemRef(self->localdicts, tstate->threading_local_key,
                          &ldict) < 0) {
        return NULL;
    }
    if (ldict != NULL) {
        return ldict;
    }

    /* threading.local hasn't been instantiated for this thread */
    PyObject *wr;
    if (create_localsdict(self, state, &ldict, &wr) < 0) {
        return NULL;
    }

    /* run __init__ if we're a subtype of `threading.local` */
    if (Py_TYPE(self)->tp_init != PyBaseObject_Type.tp_init &&
        Py_TYPE(self)->tp_init((PyObject *)self, self->args, self->kw) < 0) {
        /* we need to get rid of ldict from thread so
           we create a new one the next time we do an attr
           access */
        PyObject *exc = PyErr_GetRaisedException();
        if (PyDict_DelItem(self->localdicts,
                           tstate->threading_local_key) < 0)
        {
            PyErr_FormatUnraisable("Exception ignored while deleting "
                                   "thread local of %R", self);
            assert(!PyErr_Occurred());
        }
        if (PySet_Discard(self->thread_watchdogs, wr) < 0) {
            PyErr_FormatUnraisable("Exception ignored while discarding "
                                   "thread watchdog of %R", self);
        }
        PyErr_SetRaisedException(exc);
        Py_DECREF(ldict);
        Py_DECREF(wr);
        return NULL;
    }
    Py_DECREF(wr);

    return ldict;
}

static int
local_setattro(PyObject *op, PyObject *name, PyObject *v)
{
    localobject *self = localobject_CAST(op);
    PyObject *module = PyType_GetModuleByDef(Py_TYPE(self), &thread_module);
    assert(module != NULL);
    thread_module_state *state = get_thread_state(module);

    PyObject *ldict = _ldict(self, state);
    if (ldict == NULL) {
        goto err;
    }

    int r = PyObject_RichCompareBool(name, &_Py_ID(__dict__), Py_EQ);
    if (r == -1) {
        goto err;
    }
    if (r == 1) {
        PyErr_Format(PyExc_AttributeError,
                     "'%.100s' object attribute %R is read-only",
                     Py_TYPE(self)->tp_name, name);
        goto err;
    }

    int st = _PyObject_GenericSetAttrWithDict(op, name, v, ldict);
    Py_DECREF(ldict);
    return st;

err:
    Py_XDECREF(ldict);
    return -1;
}

static PyObject *local_getattro(PyObject *, PyObject *);

static PyMemberDef local_type_members[] = {
    {"__weaklistoffset__", Py_T_PYSSIZET, offsetof(localobject, weakreflist), Py_READONLY},
    {NULL},
};

static PyType_Slot local_type_slots[] = {
    {Py_tp_dealloc, local_dealloc},
    {Py_tp_getattro, local_getattro},
    {Py_tp_setattro, local_setattro},
    {Py_tp_doc, "_local()\n--\n\nThread-local data"},
    {Py_tp_traverse, local_traverse},
    {Py_tp_clear, local_clear},
    {Py_tp_new, local_new},
    {Py_tp_members, local_type_members},
    {0, 0}
};

static PyType_Spec local_type_spec = {
    .name = "_thread._local",
    .basicsize = sizeof(localobject),
    .flags = (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC |
              Py_TPFLAGS_IMMUTABLETYPE),
    .slots = local_type_slots,
};

static PyObject *
local_getattro(PyObject *op, PyObject *name)
{
    localobject *self = localobject_CAST(op);
    PyObject *module = PyType_GetModuleByDef(Py_TYPE(self), &thread_module);
    assert(module != NULL);
    thread_module_state *state = get_thread_state(module);

    PyObject *ldict = _ldict(self, state);
    if (ldict == NULL)
        return NULL;

    int r = PyObject_RichCompareBool(name, &_Py_ID(__dict__), Py_EQ);
    if (r == 1) {
        return ldict;
    }
    if (r == -1) {
        Py_DECREF(ldict);
        return NULL;
    }

    if (!Py_IS_TYPE(self, state->local_type)) {
        /* use generic lookup for subtypes */
        PyObject *res = _PyObject_GenericGetAttrWithDict(op, name, ldict, 0);
        Py_DECREF(ldict);
        return res;
    }

    /* Optimization: just look in dict ourselves */
    PyObject *value;
    if (PyDict_GetItemRef(ldict, name, &value) != 0) {
        // found or error
        Py_DECREF(ldict);
        return value;
    }

    /* Fall back on generic to get __class__ and __dict__ */
    PyObject *res = _PyObject_GenericGetAttrWithDict(op, name, ldict, 0);
    Py_DECREF(ldict);
    return res;
}

/* Called when a dummy is destroyed, indicating that the owning thread is being
 * cleared. */
static PyObject *
clear_locals(PyObject *locals_and_key, PyObject *dummyweakref)
{
    PyObject *localweakref = PyTuple_GetItem(locals_and_key, 0);
    if (localweakref == NULL) {
        return NULL;
    }
    localobject *self = localobject_CAST(_PyWeakref_GET_REF(localweakref));
    if (self == NULL) {
        Py_RETURN_NONE;
    }

    /* If the thread-local object is still alive and not being cleared,
       remove the corresponding local dict */
    if (self->localdicts != NULL) {
        PyObject *key = PyTuple_GetItem(locals_and_key, 1);
        if (key == NULL) {
            Py_DECREF(self);
            return NULL;
        }
        if (PyDict_Pop(self->localdicts, key, NULL) < 0) {
            PyErr_FormatUnraisable("Exception ignored while clearing "
                                   "thread local %R", (PyObject *)self);
        }
    }
    if (self->thread_watchdogs != NULL) {
        if (PySet_Discard(self->thread_watchdogs, dummyweakref) < 0) {
            PyErr_FormatUnraisable("Exception ignored while clearing "
                                   "thread local %R", (PyObject *)self);
        }
    }

    Py_DECREF(self);
    Py_RETURN_NONE;
}

/* Module functions */

static PyObject *
thread_current_threadgroup(PyObject *module, PyObject *Py_UNUSED(ignored))
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyObject *group = tstate->threadgroup_object;
    if (group == NULL && tstate->threadgroup == tstate->interp->main_threadgroup) {
        group = tstate->interp->main_threadgroup_object;
    }
    if (group == NULL) {
        return _PyThreadGroup_GetObject(tstate->interp, tstate->threadgroup->id);
    }
    return Py_NewRef(group);
}

static PyObject *
thread_declare_synchronized(PyObject *module, PyObject *obj)
{
    if (PyObject_DeclareSynchronized(obj) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
thread_set_copy_function(PyObject *module, PyObject *obj)
{
    if (!PyCallable_Check(obj)) {
        PyErr_SetString(PyExc_TypeError, "copy function must be callable");
        return NULL;
    }
    thread_module_state *state = get_thread_state(module);
    Py_INCREF(obj);
    Py_XSETREF(state->copy_function, obj);
    Py_RETURN_NONE;
}

static PyObject *
thread_daemon_threads_allowed(PyObject *module, PyObject *Py_UNUSED(ignored))
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->feature_flags & Py_RTFLAGS_DAEMON_THREADS) {
        Py_RETURN_TRUE;
    }
    else {
        Py_RETURN_FALSE;
    }
}

PyDoc_STRVAR(daemon_threads_allowed_doc,
"daemon_threads_allowed($module, /)\n\
--\n\
\n\
Return True if daemon threads are allowed in the current interpreter,\n\
and False otherwise.\n");

static int
do_start_new_thread(thread_module_state *state, PyObject *func, PyObject *args,
                    PyObject *kwargs, ThreadHandle *handle, int daemon,
                    PyObject *group)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (!_PyInterpreterState_HasFeature(interp, Py_RTFLAGS_THREADS)) {
        PyErr_SetString(PyExc_RuntimeError,
                        "thread is not supported for isolated subinterpreters");
        return -1;
    }
    if (_PyInterpreterState_GetFinalizing(interp) != NULL) {
        PyErr_SetString(PyExc_PythonFinalizationError,
                        "can't create new thread at interpreter shutdown");
        return -1;
    }

    if (!daemon) {
        // Add the handle before starting the thread to avoid adding a handle
        // to a thread that has already finished (i.e. if the thread finishes
        // before the call to `ThreadHandle_start()` below returns).
        add_to_shutdown_handles(state, handle);
    }

    if (ThreadHandle_start(handle, func, args, kwargs, daemon, group) < 0) {
        if (!daemon) {
            remove_from_shutdown_handles(handle);
        }
        return -1;
    }

    return 0;
}

static PyObject *
run_group_finalizer(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    if (PyObject_CheckAccess(self) == NULL) {
        return NULL;
    }
    /* GC may have marked the object finalized before dispatching it. */
    _PyObject_RunFinalizer(self);
    Py_RETURN_NONE;
}

static PyMethodDef group_finalizer_method = {
    "_finalize", run_group_finalizer, METH_NOARGS, NULL
};

static int
call_in_threadgroup(uint32_t group_id, PyMethodDef *method, PyObject *self)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyInterpreterState *interp = tstate->interp;
    if (finalizer_can_wait(tstate) < 0) {
        return -1;
    }
    PyObject *name = PyUnicode_FromString("_thread");
    if (name == NULL) {
        return -1;
    }
    PyObject *module = PyImport_GetModule(name);
    Py_DECREF(name);
    if (module == NULL) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_RuntimeError, "_thread module is unavailable");
        }
        return -1;
    }
    if (!PyModule_Check(module) || PyModule_GetDef(module) != &thread_module) {
        Py_DECREF(module);
        PyErr_SetString(PyExc_RuntimeError, "_thread module was replaced");
        return -1;
    }
    thread_module_state *state = get_thread_state(module);
    PyObject *group = _PyThreadGroup_GetObject(interp, group_id);
    PyObject *callable = NULL;
    PyObject *args = NULL;
    ThreadHandle *handle = NULL;
    int result = -1;
    if (group == NULL) {
        goto done;
    }
    callable = PyCFunction_NewEx(method, self, NULL);
    if (callable == NULL || PyObject_DeclareSynchronized(callable) < 0) {
        goto done;
    }
    args = PyTuple_New(0);
    if (args == NULL) {
        goto done;
    }
    handle = ThreadHandle_new();
    if (handle == NULL) {
        goto done;
    }
    if (do_start_new_thread(state, callable, args, NULL, handle, 0, group) < 0) {
        goto done;
    }
    /* Joining releases the caller's group/GIL. Even when a signal handler
       raises, wait for cleanup to finish before reporting the exception:
       deallocation and subsequent weakref callbacks must not run ahead. */
    PyObject *interrupted = NULL;
    result = ThreadHandle_join_impl(handle, -1, &interrupted);
    if (interrupted != NULL) {
        if (result < 0) {
            _PyErr_ChainExceptions1(interrupted);
        }
        else {
            PyErr_SetRaisedException(interrupted);
            result = -1;
        }
    }
done:
    if (handle != NULL) {
        ThreadHandle_decref(handle);
    }
    Py_XDECREF(args);
    Py_XDECREF(callable);
    Py_XDECREF(group);
    Py_DECREF(module);
    return result;
}

int
_PyThreadGroup_CallFinalizer(PyObject *op)
{
    return call_in_threadgroup(
        _Py_atomic_load_uint32_relaxed(&op->ob_owner_id),
        &group_finalizer_method, op);
}

static PyObject *
run_group_weakref_callback(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyWeakReference *ref = (PyWeakReference *)PyTuple_GET_ITEM(self, 0);
    PyObject *callback = PyTuple_GET_ITEM(self, 1);
    _PyWeakref_CallCallback(ref, callback);
    Py_RETURN_NONE;
}

static PyMethodDef group_weakref_callback_method = {
    "_weakref_callback", run_group_weakref_callback, METH_NOARGS, NULL
};

int
_PyThreadGroup_CallWeakrefCallback(PyWeakReference *ref, PyObject *callback)
{
    /* The callback and weakref belong to the destination group.  Build the
       dispatch context with the internal tuple constructor so transferring
       those references does not apply the caller's access check. */
    PyObject *context = _PyTuple_FromPair((PyObject *)ref, callback);
    if (context == NULL) {
        return -1;
    }
    int result = call_in_threadgroup(ref->wr_callback_group,
                                    &group_weakref_callback_method, context);
    Py_DECREF(context);
    return result;
}

static PyObject *
thread_PyThread_start_new_thread(PyObject *module, PyObject *fargs)
{
    PyObject *func, *args, *kwargs = NULL;
    thread_module_state *state = get_thread_state(module);

    if (!PyArg_UnpackTuple(fargs, "start_new_thread", 2, 3,
                           &func, &args, &kwargs))
        return NULL;
    if (!PyCallable_Check(func)) {
        PyErr_SetString(PyExc_TypeError,
                        "first arg must be callable");
        return NULL;
    }
    if (!PyTuple_Check(args)) {
        PyErr_SetString(PyExc_TypeError,
                        "2nd arg must be a tuple");
        return NULL;
    }
    if (kwargs != NULL && !PyDict_Check(kwargs)) {
        PyErr_SetString(PyExc_TypeError,
                        "optional 3rd arg must be a dictionary");
        return NULL;
    }

    if (PySys_Audit("_thread.start_new_thread", "OOO",
                    func, args, kwargs ? kwargs : Py_None) < 0) {
        return NULL;
    }

    ThreadHandle *handle = ThreadHandle_new();
    if (handle == NULL) {
        return NULL;
    }

    int st =
        do_start_new_thread(state, func, args, kwargs, handle, /*daemon=*/1, NULL);
    if (st < 0) {
        ThreadHandle_decref(handle);
        return NULL;
    }
    PyThread_ident_t ident = ThreadHandle_ident(handle);
    ThreadHandle_decref(handle);
    return PyLong_FromUnsignedLongLong(ident);
}

PyDoc_STRVAR(start_new_thread_doc,
"start_new_thread($module, function, args, kwargs={}, /)\n\
--\n\
\n\
Start a new thread and return its identifier.\n\
\n\
The thread will call the function with positional arguments from the\n\
tuple args and keyword arguments taken from the optional dictionary\n\
kwargs.  The thread exits when the function returns; the return value\n\
is ignored.  The thread will also exit when the function raises an\n\
unhandled exception; a stack trace will be printed unless the exception\n\
is SystemExit.");

PyDoc_STRVAR(start_new_doc,
"start_new($module, function, args, kwargs={}, /)\n\
--\n\
\n\
An obsolete synonym of start_new_thread().");

static PyObject *
thread_PyThread_start_joinable_thread(PyObject *module, PyObject *fargs,
                                      PyObject *fkwargs)
{
    static char *keywords[] = {"function", "handle", "daemon", "group", NULL};
    PyObject *func = NULL;
    int daemon = 1;
    thread_module_state *state = get_thread_state(module);
    PyObject *hobj = NULL;
    PyObject *group = Py_None;
    if (!PyArg_ParseTupleAndKeywords(fargs, fkwargs,
                                     "O|OpO:start_joinable_thread", keywords,
                                     &func, &hobj, &daemon, &group)) {
        return NULL;
    }

    if (!PyCallable_Check(func)) {
        PyErr_SetString(PyExc_TypeError,
                        "thread function must be callable");
        return NULL;
    }

    if (group == Py_None) {
        group = NULL;
    }
    else if (!Py_IS_TYPE(group, state->threadgroup_type)) {
        PyErr_SetString(PyExc_TypeError, "group must be a ThreadGroup or None");
        return NULL;
    }
    else if (((threadgroupobject *)group)->interpreter_id !=
             PyInterpreterState_GetID(_PyInterpreterState_GET())) {
        PyErr_SetString(PyExc_ValueError, "ThreadGroup belongs to another interpreter");
        return NULL;
    }

    if (hobj == NULL) {
        hobj = Py_None;
    }
    else if (hobj != Py_None && !Py_IS_TYPE(hobj, state->thread_handle_type)) {
        PyErr_SetString(PyExc_TypeError, "'handle' must be a _ThreadHandle");
        return NULL;
    }

    if (PySys_Audit("_thread.start_joinable_thread", "OiO", func, daemon,
                    hobj) < 0) {
        return NULL;
    }

    if (hobj == Py_None) {
        hobj = (PyObject *)PyThreadHandleObject_new(state->thread_handle_type);
        if (hobj == NULL) {
            return NULL;
        }
    }
    else {
        Py_INCREF(hobj);
    }

    PyObject* args = PyTuple_New(0);
    if (args == NULL) {
        return NULL;
    }
    int st = do_start_new_thread(state, func, args,
                                 /*kwargs=*/ NULL, ((PyThreadHandleObject*)hobj)->handle, daemon, group);
    Py_DECREF(args);
    if (st < 0) {
        Py_DECREF(hobj);
        return NULL;
    }
    return (PyObject *) hobj;
}

PyDoc_STRVAR(start_joinable_doc,
"start_joinable_thread($module, /, function, handle=None, daemon=True, group=None)\n\
--\n\
\n\
*For internal use only*: start a new thread.\n\
\n\
Like start_new_thread(), this starts a new thread calling the given function.\n\
Unlike start_new_thread(), this returns a handle object with methods to join\n\
or detach the given thread.\n\
This function is not for third-party code, please use the\n\
`threading` module instead. During finalization the runtime will not wait for\n\
the thread to exit if daemon is True. If handle is provided it must be a\n\
newly created thread._ThreadHandle instance.");

static PyObject *
thread_PyThread_exit_thread(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyErr_SetNone(PyExc_SystemExit);
    return NULL;
}

PyDoc_STRVAR(exit_doc,
"exit($module, /)\n\
--\n\
\n\
This is synonymous to ``raise SystemExit''.  It will cause the current\n\
thread to exit silently unless the exception is caught.");

PyDoc_STRVAR(exit_thread_doc,
"exit_thread($module, /)\n\
--\n\
\n\
An obsolete synonym of exit().");

static PyObject *
thread_PyThread_interrupt_main(PyObject *self, PyObject *args)
{
    int signum = SIGINT;
    if (!PyArg_ParseTuple(args, "|i:signum", &signum)) {
        return NULL;
    }

    if (PyErr_SetInterruptEx(signum)) {
        PyErr_SetString(PyExc_ValueError, "signal number out of range");
        return NULL;
    }
    Py_RETURN_NONE;
}

PyDoc_STRVAR(interrupt_doc,
"interrupt_main($module, signum=signal.SIGINT, /)\n\
--\n\
\n\
Simulate the arrival of the given signal in the main thread,\n\
where the corresponding signal handler will be executed.\n\
If *signum* is omitted, SIGINT is assumed.\n\
A subthread can use this function to interrupt the main thread.\n\
\n\
Note: the default signal handler for SIGINT raises ``KeyboardInterrupt``."
);

static PyObject *
thread_PyThread_allocate_lock(PyObject *module, PyObject *Py_UNUSED(ignored))
{
    thread_module_state *state = get_thread_state(module);
    return lock_new_impl(state->lock_type);
}

PyDoc_STRVAR(allocate_lock_doc,
"allocate_lock($module, /)\n\
--\n\
\n\
Create a new lock object. See help(type(threading.Lock())) for\n\
information about locks.");

PyDoc_STRVAR(allocate_doc,
"allocate($module, /)\n\
--\n\
\n\
An obsolete synonym of allocate_lock().");

static PyObject *
thread_get_ident(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyThread_ident_t ident = PyThread_get_thread_ident_ex();
    if (ident == PYTHREAD_INVALID_THREAD_ID) {
        PyErr_SetString(ThreadError, "no current thread ident");
        return NULL;
    }
    return PyLong_FromUnsignedLongLong(ident);
}

PyDoc_STRVAR(get_ident_doc,
"get_ident($module, /)\n\
--\n\
\n\
Return a non-zero integer that uniquely identifies the current thread\n\
amongst other threads that exist simultaneously.\n\
This may be used to identify per-thread resources.\n\
Even though on some platforms threads identities may appear to be\n\
allocated consecutive numbers starting at 1, this behavior should not\n\
be relied upon, and the number should be seen purely as a magic cookie.\n\
A thread's identity may be reused for another thread after it exits.");

#ifdef PY_HAVE_THREAD_NATIVE_ID
static PyObject *
thread_get_native_id(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    unsigned long native_id = PyThread_get_thread_native_id();
    return PyLong_FromUnsignedLong(native_id);
}

PyDoc_STRVAR(get_native_id_doc,
"get_native_id($module, /)\n\
--\n\
\n\
Return a non-negative integer identifying the thread as reported\n\
by the OS (kernel). This may be used to uniquely identify a\n\
particular thread within a system.");
#endif

static PyObject *
thread__count(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    return PyLong_FromSsize_t(_Py_atomic_load_ssize(&interp->threads.count));
}

PyDoc_STRVAR(_count_doc,
"_count($module, /)\n\
--\n\
\n\
Return the number of currently running Python threads, excluding\n\
the main thread. The returned number comprises all threads created\n\
through `start_new_thread()` as well as `threading.Thread`, and not\n\
yet finished.\n\
\n\
This function is meant for internal and specialized purposes only.\n\
In most applications `threading.enumerate()` should be used instead.");

static PyObject *
thread_stack_size(PyObject *self, PyObject *args)
{
    size_t old_size;
    Py_ssize_t new_size = 0;
    int rc;

    if (!PyArg_ParseTuple(args, "|n:stack_size", &new_size))
        return NULL;

    Py_ssize_t min_size = _PyOS_MIN_STACK_SIZE + SYSTEM_PAGE_SIZE;
    if (new_size != 0 && new_size < min_size) {
        PyErr_Format(PyExc_ValueError,
                     "size must be at least %zi bytes", min_size);
        return NULL;
    }

    old_size = PyThread_get_stacksize();

    rc = PyThread_set_stacksize((size_t) new_size);
    if (rc == -1) {
        PyErr_Format(PyExc_ValueError,
                     "size not valid: %zd bytes",
                     new_size);
        return NULL;
    }
    if (rc == -2) {
        PyErr_SetString(ThreadError,
                        "setting stack size not supported");
        return NULL;
    }

    return PyLong_FromSsize_t((Py_ssize_t) old_size);
}

PyDoc_STRVAR(stack_size_doc,
"stack_size($module, size=0, /)\n\
--\n\
\n\
Return the thread stack size used when creating new threads.  The\n\
optional size argument specifies the stack size (in bytes) to be used\n\
for subsequently created threads, and must be 0 (use platform or\n\
configured default) or a positive integer value of at least 32,768 (32k).\n\
If changing the thread stack size is unsupported, a ThreadError\n\
exception is raised.  If the specified size is invalid, a ValueError\n\
exception is raised, and the stack size is unmodified.  32k bytes\n\
 currently the minimum supported stack size value to guarantee\n\
sufficient stack space for the interpreter itself.\n\
\n\
Note that some platforms may have particular restrictions on values for\n\
the stack size, such as requiring a minimum stack size larger than 32 KiB or\n\
requiring allocation in multiples of the system memory page size\n\
- platform documentation should be referred to for more information\n\
(4 KiB pages are common; using multiples of 4096 for the stack size is\n\
the suggested approach in the absence of more specific information).");

static int
thread_excepthook_file(PyObject *file, PyObject *exc_type, PyObject *exc_value,
                       PyObject *exc_traceback, PyObject *thread)
{
    /* print(f"Exception in thread {thread.name}:", file=file) */
    if (PyFile_WriteString("Exception in thread ", file) < 0) {
        return -1;
    }

    PyObject *name = NULL;
    if (thread != Py_None) {
        if (PyObject_GetOptionalAttr(thread, &_Py_ID(name), &name) < 0) {
            return -1;
        }
    }
    if (name != NULL) {
        if (PyFile_WriteObject(name, file, Py_PRINT_RAW) < 0) {
            Py_DECREF(name);
            return -1;
        }
        Py_DECREF(name);
    }
    else {
        PyThread_ident_t ident = PyThread_get_thread_ident_ex();
        PyObject *str = PyUnicode_FromFormat("%" PY_FORMAT_THREAD_IDENT_T, ident);
        if (str != NULL) {
            if (PyFile_WriteObject(str, file, Py_PRINT_RAW) < 0) {
                Py_DECREF(str);
                return -1;
            }
            Py_DECREF(str);
        }
        else {
            PyErr_Clear();

            if (PyFile_WriteString("<failed to get thread name>", file) < 0) {
                return -1;
            }
        }
    }

    if (PyFile_WriteString(":\n", file) < 0) {
        return -1;
    }

    /* Display the traceback */
    _PyErr_Display(file, exc_type, exc_value, exc_traceback);

    /* Call file.flush() */
    if (_PyFile_Flush(file) < 0) {
        return -1;
    }

    return 0;
}


PyDoc_STRVAR(ExceptHookArgs__doc__,
"ExceptHookArgs\n\
\n\
Type used to pass arguments to threading.excepthook.");

static PyStructSequence_Field ExceptHookArgs_fields[] = {
    {"exc_type", "Exception type"},
    {"exc_value", "Exception value"},
    {"exc_traceback", "Exception traceback"},
    {"thread", "Thread"},
    {0}
};

static PyStructSequence_Desc ExceptHookArgs_desc = {
    .name = "_thread._ExceptHookArgs",
    .doc = ExceptHookArgs__doc__,
    .fields = ExceptHookArgs_fields,
    .n_in_sequence = 4
};


static PyObject *
thread_excepthook_access_fallback(void)
{
    if (!PyErr_ExceptionMatches(PyExc_IllegalThreadAccessException) &&
        !PyErr_ExceptionMatches(PyExc_UnprotectedAccessException)) {
        return NULL;
    }
    // Error reporting must not acquire a stream owned by another group or
    // protected by an unheld mutex. Use a fresh, locally owned raw printer;
    // its writes go to the process stderr without touching that stream.
    PyErr_Clear();
    return PyFile_NewStdPrinter(fileno(stderr));
}

static PyObject *
thread_get_stderr(PyObject *module, PyObject *Py_UNUSED(ignored))
{
    PyObject *file = PySys_GetAttr(&_Py_ID(stderr));
    if (file == NULL) {
        return thread_excepthook_access_fallback();
    }
    return file;
}

static PyObject *
thread_excepthook(PyObject *module, PyObject *args)
{
    thread_module_state *state = get_thread_state(module);

    if (!Py_IS_TYPE(args, state->excepthook_type)) {
        PyErr_SetString(PyExc_TypeError,
                        "_thread.excepthook argument type "
                        "must be ExceptHookArgs");
        return NULL;
    }

    /* Borrowed reference */
    PyObject *exc_type = PyStructSequence_GET_ITEM(args, 0);
    if (exc_type == PyExc_SystemExit) {
        /* silently ignore SystemExit */
        Py_RETURN_NONE;
    }

    /* Borrowed references */
    PyObject *exc_value = PyStructSequence_GET_ITEM(args, 1);
    PyObject *exc_tb = PyStructSequence_GET_ITEM(args, 2);
    PyObject *thread = PyStructSequence_GET_ITEM(args, 3);

    PyObject *file;
    if (PySys_GetOptionalAttr(&_Py_ID(stderr), &file) < 0) {
        file = thread_excepthook_access_fallback();
        if (file == NULL) {
            return NULL;
        }
    }
    if (file == NULL || file == Py_None) {
        Py_XDECREF(file);
        if (thread == Py_None) {
            /* do nothing if sys.stderr is None and thread is None */
            Py_RETURN_NONE;
        }

        file = PyObject_GetAttrString(thread, "_stderr");
        if (file == NULL) {
            file = thread_excepthook_access_fallback();
            if (file == NULL) {
                return NULL;
            }
        }
        if (file == Py_None) {
            Py_DECREF(file);
            /* do nothing if sys.stderr is None and sys.stderr was None
               when the thread was created */
            Py_RETURN_NONE;
        }
    }

    int res = thread_excepthook_file(file, exc_type, exc_value, exc_tb,
                                     thread);
    Py_DECREF(file);
    if (res < 0) {
        return NULL;
    }

    Py_RETURN_NONE;
}

PyDoc_STRVAR(excepthook_doc,
"_excepthook($module, args, /)\n\
--\n\
\n\
Handle uncaught Thread.run() exception.");

static PyObject *
thread__is_main_interpreter(PyObject *module, PyObject *Py_UNUSED(ignored))
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    return PyBool_FromLong(_Py_IsMainInterpreter(interp));
}

PyDoc_STRVAR(thread__is_main_interpreter_doc,
"_is_main_interpreter($module, /)\n\
--\n\
\n\
Return True if the current interpreter is the main Python interpreter.");

static PyObject *
thread_shutdown(PyObject *self, PyObject *args)
{
    PyThread_ident_t ident = PyThread_get_thread_ident_ex();
    thread_module_state *state = get_thread_state(self);

    for (;;) {
        ThreadHandle *handle = NULL;

        // Find a thread that's not yet finished.
        HEAD_LOCK(&_PyRuntime);
        struct llist_node *node;
        llist_for_each_safe(node, &state->shutdown_handles) {
            ThreadHandle *cur = llist_data(node, ThreadHandle, shutdown_node);
            if (ThreadHandle_ident(cur) != ident) {
                ThreadHandle_incref(cur);
                handle = cur;
                break;
            }
        }
        HEAD_UNLOCK(&_PyRuntime);

        if (!handle) {
            // No more threads to wait on!
            break;
        }

        // Wait for the thread to finish. If we're interrupted, such
        // as by a ctrl-c we print the error and exit early.
        if (ThreadHandle_join(handle, -1) < 0) {
            ThreadHandle_decref(handle);
            return NULL;
        }

        ThreadHandle_decref(handle);
    }

    Py_RETURN_NONE;
}

PyDoc_STRVAR(shutdown_doc,
"_shutdown($module, /)\n\
--\n\
\n\
Wait for all non-daemon threads (other than the calling thread) to stop.");

static PyObject *
thread__make_thread_handle(PyObject *module, PyObject *identobj)
{
    thread_module_state *state = get_thread_state(module);
    if (!PyLong_Check(identobj)) {
        PyErr_SetString(PyExc_TypeError, "ident must be an integer");
        return NULL;
    }
    PyThread_ident_t ident = PyLong_AsUnsignedLongLong(identobj);
    if (PyErr_Occurred()) {
        return NULL;
    }
    PyThreadHandleObject *hobj =
        PyThreadHandleObject_new(state->thread_handle_type);
    if (hobj == NULL) {
        return NULL;
    }
    PyMutex_Lock(&hobj->handle->mutex);
    hobj->handle->ident = ident;
    hobj->handle->state = THREAD_HANDLE_RUNNING;
    PyMutex_Unlock(&hobj->handle->mutex);
    return (PyObject*) hobj;
}

PyDoc_STRVAR(thread__make_thread_handle_doc,
"_make_thread_handle($module, ident, /)\n\
--\n\
\n\
Internal only. Make a thread handle for threads not spawned\n\
by the _thread or threading module.");

static PyObject *
thread__get_main_thread_ident(PyObject *module, PyObject *Py_UNUSED(ignored))
{
    return PyLong_FromUnsignedLongLong(_PyRuntime.main_thread);
}

PyDoc_STRVAR(thread__get_main_thread_ident_doc,
"_get_main_thread_ident($module, /)\n\
--\n\
\n\
Internal only. Return a non-zero integer that uniquely identifies the main thread\n\
of the main interpreter.");

#if defined(__OpenBSD__)
    /* pthread_*_np functions, especially pthread_{get,set}_name_np().
       pthread_np.h exists on both OpenBSD and FreeBSD but the latter declares
       pthread_getname_np() and pthread_setname_np() in pthread.h as long as
       __BSD_VISIBLE remains set.
     */
#   include <pthread_np.h>
#endif

#if defined(HAVE_PTHREAD_GETNAME_NP) || defined(HAVE_PTHREAD_GET_NAME_NP) || defined(MS_WINDOWS)
/*[clinic input]
_thread._get_name

Get the name of the current thread.
[clinic start generated code]*/

static PyObject *
_thread__get_name_impl(PyObject *module)
/*[clinic end generated code: output=20026e7ee3da3dd7 input=35cec676833d04c8]*/
{
#ifndef MS_WINDOWS
    // Linux and macOS are limited to respectively 16 and 64 bytes
    char name[100];
    pthread_t thread = pthread_self();
#ifdef HAVE_PTHREAD_GETNAME_NP
    int rc = pthread_getname_np(thread, name, Py_ARRAY_LENGTH(name));
#else /* defined(HAVE_PTHREAD_GET_NAME_NP) */
    int rc = 0; /* pthread_get_name_np() returns void */
    pthread_get_name_np(thread, name, Py_ARRAY_LENGTH(name));
#endif
    if (rc) {
        errno = rc;
        return PyErr_SetFromErrno(PyExc_OSError);
    }

#ifdef __sun
    // gh-138004: Decode Solaris/Illumos (e.g. OpenIndiana) thread names
    // from ASCII, since OpenIndiana only supports ASCII names.
    return PyUnicode_DecodeASCII(name, strlen(name), "surrogateescape");
#else
    return PyUnicode_DecodeFSDefault(name);
#endif
#else
    // Windows implementation
    assert(pGetThreadDescription != NULL);

    wchar_t *name;
    HRESULT hr = pGetThreadDescription(GetCurrentThread(), &name);
    if (FAILED(hr)) {
        PyErr_SetFromWindowsErr(0);
        return NULL;
    }

    PyObject *name_obj = PyUnicode_FromWideChar(name, -1);
    LocalFree(name);
    return name_obj;
#endif
}
#endif  // HAVE_PTHREAD_GETNAME_NP || HAVE_PTHREAD_GET_NAME_NP || MS_WINDOWS


#if defined(HAVE_PTHREAD_SETNAME_NP) || defined(HAVE_PTHREAD_SET_NAME_NP) || defined(MS_WINDOWS)
/*[clinic input]
_thread.set_name

    name as name_obj: unicode

Set the name of the current thread.
[clinic start generated code]*/

static PyObject *
_thread_set_name_impl(PyObject *module, PyObject *name_obj)
/*[clinic end generated code: output=402b0c68e0c0daed input=7e7acd98261be82f]*/
{
#ifndef MS_WINDOWS
#ifdef __sun
    // gh-138004: Encode Solaris/Illumos thread names to ASCII,
    // since OpenIndiana does not support non-ASCII names.
    const char *encoding = "ascii";
#else
    // Encode the thread name to the filesystem encoding using the "replace"
    // error handler
    PyInterpreterState *interp = _PyInterpreterState_GET();
    const char *encoding = interp->unicode.fs_codec.encoding;
#endif
    PyObject *name_encoded;
    name_encoded = PyUnicode_AsEncodedString(name_obj, encoding, "replace");
    if (name_encoded == NULL) {
        return NULL;
    }

#ifdef _PYTHREAD_NAME_MAXLEN
    // Truncate to _PYTHREAD_NAME_MAXLEN bytes + the NUL byte if needed
    if (PyBytes_GET_SIZE(name_encoded) > _PYTHREAD_NAME_MAXLEN) {
        PyObject *truncated;
        truncated = PyBytes_FromStringAndSize(PyBytes_AS_STRING(name_encoded),
                                              _PYTHREAD_NAME_MAXLEN);
        if (truncated == NULL) {
            Py_DECREF(name_encoded);
            return NULL;
        }
        Py_SETREF(name_encoded, truncated);
    }
#endif

    const char *name = PyBytes_AS_STRING(name_encoded);
#ifdef __APPLE__
    int rc = pthread_setname_np(name);
#elif defined(__NetBSD__)
    pthread_t thread = pthread_self();
    int rc = pthread_setname_np(thread, "%s", (void *)name);
#elif defined(HAVE_PTHREAD_SETNAME_NP)
    pthread_t thread = pthread_self();
    int rc = pthread_setname_np(thread, name);
#else /* defined(HAVE_PTHREAD_SET_NAME_NP) */
    pthread_t thread = pthread_self();
    int rc = 0; /* pthread_set_name_np() returns void */
    pthread_set_name_np(thread, name);
#endif
    Py_DECREF(name_encoded);
    if (rc) {
        errno = rc;
        return PyErr_SetFromErrno(PyExc_OSError);
    }
    Py_RETURN_NONE;
#else
    // Windows implementation
    assert(pSetThreadDescription != NULL);

    Py_ssize_t len;
    wchar_t *name = PyUnicode_AsWideCharString(name_obj, &len);
    if (name == NULL) {
        return NULL;
    }

    if (len > _PYTHREAD_NAME_MAXLEN) {
        // Truncate the name
        Py_UCS4 ch = name[_PYTHREAD_NAME_MAXLEN-1];
        if (Py_UNICODE_IS_HIGH_SURROGATE(ch)) {
            name[_PYTHREAD_NAME_MAXLEN-1] = 0;
        }
        else {
            name[_PYTHREAD_NAME_MAXLEN] = 0;
        }
    }

    HRESULT hr = pSetThreadDescription(GetCurrentThread(), name);
    PyMem_Free(name);
    if (FAILED(hr)) {
        PyErr_SetFromWindowsErr((int)hr);
        return NULL;
    }
    Py_RETURN_NONE;
#endif
}
#endif  // HAVE_PTHREAD_SETNAME_NP || HAVE_PTHREAD_SET_NAME_NP || MS_WINDOWS


static PyMethodDef thread_methods[] = {
    {"_get_stderr", thread_get_stderr, METH_NOARGS,
     "Return accessible stderr or a local raw printer for thread diagnostics."},
    {"_current_thread_group", thread_current_threadgroup, METH_NOARGS, NULL},
    {"_declare_synchronized", thread_declare_synchronized, METH_O, NULL},
    {"_set_copy_function", thread_set_copy_function, METH_O, NULL},
    {"start_new_thread",        thread_PyThread_start_new_thread,
     METH_VARARGS, start_new_thread_doc},
    {"start_new",               thread_PyThread_start_new_thread,
     METH_VARARGS, start_new_doc},
    {"start_joinable_thread",   _PyCFunction_CAST(thread_PyThread_start_joinable_thread),
     METH_VARARGS | METH_KEYWORDS, start_joinable_doc},
    {"daemon_threads_allowed",  thread_daemon_threads_allowed,
     METH_NOARGS, daemon_threads_allowed_doc},
    {"allocate_lock",           thread_PyThread_allocate_lock,
     METH_NOARGS, allocate_lock_doc},
    {"allocate",                thread_PyThread_allocate_lock,
     METH_NOARGS, allocate_doc},
    {"exit_thread",             thread_PyThread_exit_thread,
     METH_NOARGS, exit_thread_doc},
    {"exit",                    thread_PyThread_exit_thread,
     METH_NOARGS, exit_doc},
    {"interrupt_main",          thread_PyThread_interrupt_main,
     METH_VARARGS, interrupt_doc},
    {"get_ident",               thread_get_ident,
     METH_NOARGS, get_ident_doc},
#ifdef PY_HAVE_THREAD_NATIVE_ID
    {"get_native_id",           thread_get_native_id,
     METH_NOARGS, get_native_id_doc},
#endif
    {"_count",                  thread__count,
     METH_NOARGS, _count_doc},
    {"stack_size",              thread_stack_size,
     METH_VARARGS, stack_size_doc},
    {"_excepthook",             thread_excepthook,
     METH_O, excepthook_doc},
    {"_is_main_interpreter",    thread__is_main_interpreter,
     METH_NOARGS, thread__is_main_interpreter_doc},
    {"_shutdown",               thread_shutdown,
     METH_NOARGS, shutdown_doc},
    {"_make_thread_handle", thread__make_thread_handle,
     METH_O, thread__make_thread_handle_doc},
    {"_get_main_thread_ident", thread__get_main_thread_ident,
     METH_NOARGS, thread__get_main_thread_ident_doc},
    _THREAD_SET_NAME_METHODDEF
    _THREAD__GET_NAME_METHODDEF
    {NULL,                      NULL}           /* sentinel */
};


/* Initialization function */

static int
thread_module_exec(PyObject *module)
{
    thread_module_state *state = get_thread_state(module);
    PyObject *d = PyModule_GetDict(module);

    // Initialize the C thread library
    PyThread_init_thread();

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->main_threadgroup_object == NULL) {
        state->threadgroup_type = (PyTypeObject *)PyType_FromSpec(&threadgroup_spec);
    }
    else {
        state->threadgroup_type = (PyTypeObject *)Py_NewRef(
            Py_TYPE(interp->main_threadgroup_object));
    }
    if (state->threadgroup_type == NULL ||
        PyModule_AddType(module, state->threadgroup_type) < 0) {
        return -1;
    }
    if (interp->main_threadgroup_object == NULL) {
        threadgroupobject *main = (threadgroupobject *)PyObject_CallFunction(
            (PyObject *)state->threadgroup_type, "s", "Main");
        if (main == NULL) {
            return -1;
        }
        _PyThreadGroupState *temporary = main->state;
        size_t name_size = (temporary->name_length + 1) * sizeof(Py_UCS4);
        Py_UCS4 *name = PyMem_RawMalloc(name_size);
        if (name == NULL) {
            Py_DECREF(main);
            PyErr_NoMemory();
            return -1;
        }
        memcpy(name, temporary->name, name_size);
        PyMutex_LockFlags(&temporary->holder_mutex, 0);
        temporary->wrapper = NULL;
        PyMutex_Unlock(&temporary->holder_mutex);
        main->state = interp->main_threadgroup;
        _PyThreadGroup_Incref(main->state);
        PyMutex_LockFlags(&main->state->holder_mutex, 0);
        assert(main->state->name == NULL);
        main->state->name = name;
        main->state->name_length = temporary->name_length;
        main->state->wrapper = (PyObject *)main;
        PyMutex_Unlock(&main->state->holder_mutex);
        _PyThreadGroup_Decref(temporary);
        interp->main_threadgroup_object = (PyObject *)main;
    }
    if (PySys_SetObject("main_thread_group", interp->main_threadgroup_object) < 0) {
        return -1;
    }

    state->transferbox_type = (PyTypeObject *)PyType_FromModuleAndSpec(
        module, &transferbox_spec, NULL);
    if (state->transferbox_type == NULL ||
        PyObject_DeclareImmutable((PyObject *)state->transferbox_type) < 0 ||
        PyModule_AddType(module, state->transferbox_type) < 0) {
        return -1;
    }

    state->channel_queue_type = (PyTypeObject *)PyType_FromModuleAndSpec(
        module, &channelqueue_spec, NULL);
    if (state->channel_queue_type == NULL ||
        PyObject_DeclareImmutable((PyObject *)state->channel_queue_type) < 0 ||
        PyModule_AddType(module, state->channel_queue_type) < 0) {
        return -1;
    }

    state->thread_base_type = (PyTypeObject *)PyType_FromModuleAndSpec(
        module, &threadbase_spec, NULL);
    if (state->thread_base_type == NULL ||
        PyModule_AddType(module, state->thread_base_type) < 0) {
        return -1;
    }

    // _ThreadHandle
    state->thread_handle_type = (PyTypeObject *)PyType_FromSpec(&ThreadHandle_Type_spec);
    if (state->thread_handle_type == NULL) {
        return -1;
    }
    if (PyDict_SetItemString(d, "_ThreadHandle", (PyObject *)state->thread_handle_type) < 0) {
        return -1;
    }

    // Lock
    state->lock_type = (PyTypeObject *)PyType_FromModuleAndSpec(module, &lock_type_spec, NULL);
    if (state->lock_type == NULL) {
        return -1;
    }
    if (PyModule_AddType(module, state->lock_type) < 0) {
        return -1;
    }
    // Old alias: lock -> LockType
    if (PyDict_SetItemString(d, "LockType", (PyObject *)state->lock_type) < 0) {
        return -1;
    }

    // RLock
    state->rlock_type = (PyTypeObject *)PyType_FromModuleAndSpec(module, &rlock_type_spec, NULL);
    if (state->rlock_type == NULL) {
        return -1;
    }
    if (PyModule_AddType(module, state->rlock_type) < 0) {
        return -1;
    }

    state->compound_lock_type = (PyTypeObject *)PyType_FromModuleAndSpec(
        module, &compound_type_spec, NULL);
    if (state->compound_lock_type == NULL ||
        PyModule_AddType(module, state->compound_lock_type) < 0) {
        return -1;
    }

    // Local dummy
    state->local_dummy_type = (PyTypeObject *)PyType_FromSpec(&local_dummy_type_spec);
    if (state->local_dummy_type == NULL) {
        return -1;
    }

    // Local
    state->local_type = (PyTypeObject *)PyType_FromModuleAndSpec(module, &local_type_spec, NULL);
    if (state->local_type == NULL) {
        return -1;
    }
    if (PyModule_AddType(module, state->local_type) < 0) {
        return -1;
    }

    // Add module attributes
    if (PyDict_SetItemString(d, "error", ThreadError) < 0) {
        return -1;
    }

    // _ExceptHookArgs type
    state->excepthook_type = PyStructSequence_NewType(&ExceptHookArgs_desc);
    if (state->excepthook_type == NULL) {
        return -1;
    }
    /* Every group constructs these records when reporting an exception. */
    if (PyType_Freeze(state->excepthook_type) < 0) {
        return -1;
    }
    if (_PyDict_SynchronizeNamespace(
            _PyType_GetDict(state->excepthook_type)) < 0 ||
        PyObject_DeclareImmutable((PyObject *)state->excepthook_type) < 0) {
        return -1;
    }
    if (PyModule_AddType(module, state->excepthook_type) < 0) {
        return -1;
    }

    // TIMEOUT_MAX
    double timeout_max = (double)PY_TIMEOUT_MAX * 1e-6;
    double time_max = PyTime_AsSecondsDouble(PyTime_MAX);
    timeout_max = Py_MIN(timeout_max, time_max);
    // Round towards minus infinity
    timeout_max = floor(timeout_max);

    if (PyModule_Add(module, "TIMEOUT_MAX",
                        PyFloat_FromDouble(timeout_max)) < 0) {
        return -1;
    }

    llist_init(&state->shutdown_handles);

#ifdef _PYTHREAD_NAME_MAXLEN
    if (PyModule_AddIntConstant(module, "_NAME_MAXLEN",
                                _PYTHREAD_NAME_MAXLEN) < 0) {
        return -1;
    }
#endif

#ifdef MS_WINDOWS
    HMODULE kernelbase = GetModuleHandleW(L"kernelbase.dll");
    if (kernelbase != NULL) {
        if (pGetThreadDescription == NULL) {
            pGetThreadDescription = (PF_GET_THREAD_DESCRIPTION)GetProcAddress(
                                        kernelbase, "GetThreadDescription");
        }
        if (pSetThreadDescription == NULL) {
            pSetThreadDescription = (PF_SET_THREAD_DESCRIPTION)GetProcAddress(
                                        kernelbase, "SetThreadDescription");
        }
    }

    if (pGetThreadDescription == NULL) {
        if (PyObject_DelAttrString(module, "_get_name") < 0) {
            return -1;
        }
    }
    if (pSetThreadDescription == NULL) {
        if (PyObject_DelAttrString(module, "set_name") < 0) {
            return -1;
        }
    }
#endif

    /* These entry points implement cross-thread operations. Their native
       state is synchronized independently of the caller's ThreadGroup. */
    Py_ssize_t pos = 0;
    PyObject *value;
    while (PyDict_Next(d, &pos, NULL, &value)) {
        if (PyCFunction_Check(value)) {
            if (PyObject_DeclareSynchronized(value) < 0) {
                return -1;
            }
        }
        else if (PyType_Check(value) &&
                 PyType_HasFeature((PyTypeObject *)value, Py_TPFLAGS_IMMUTABLETYPE))
        {
            if (PyObject_DeclareImmutable(value) < 0) {
                return -1;
            }
        }
    }
    if (_PyDict_SynchronizeNamespace(d) < 0 ||
        PyObject_DeclareSynchronized(module) < 0)
    {
        return -1;
    }

    return 0;
}


static int
thread_module_traverse(PyObject *module, visitproc visit, void *arg)
{
    thread_module_state *state = get_thread_state(module);
    Py_VISIT(state->excepthook_type);
    Py_VISIT(state->lock_type);
    Py_VISIT(state->rlock_type);
    Py_VISIT(state->compound_lock_type);
    Py_VISIT(state->local_type);
    Py_VISIT(state->local_dummy_type);
    Py_VISIT(state->thread_handle_type);
    Py_VISIT(state->thread_base_type);
    Py_VISIT(state->threadgroup_type);
    Py_VISIT(state->transferbox_type);
    Py_VISIT(state->channel_queue_type);
    Py_VISIT(state->copy_function);
    return 0;
}

static int
thread_module_clear(PyObject *module)
{
    thread_module_state *state = get_thread_state(module);
    Py_CLEAR(state->excepthook_type);
    Py_CLEAR(state->lock_type);
    Py_CLEAR(state->rlock_type);
    Py_CLEAR(state->compound_lock_type);
    Py_CLEAR(state->local_type);
    Py_CLEAR(state->local_dummy_type);
    Py_CLEAR(state->thread_handle_type);
    Py_CLEAR(state->thread_base_type);
    Py_CLEAR(state->threadgroup_type);
    Py_CLEAR(state->transferbox_type);
    Py_CLEAR(state->channel_queue_type);
    Py_CLEAR(state->copy_function);
    // Remove any remaining handles (e.g. if shutdown exited early due to
    // interrupt) so that attempts to unlink the handle after our module state
    // is destroyed do not crash.
    clear_shutdown_handles(state);
    return 0;
}

static void
thread_module_free(void *module)
{
    (void)thread_module_clear((PyObject *)module);
}



PyDoc_STRVAR(thread_doc,
"This module provides primitive operations to write multi-threaded programs.\n\
The 'threading' module provides a more convenient interface.");

static PyModuleDef_Slot thread_module_slots[] = {
    _Py_ABI_SLOT,
    {Py_mod_exec, thread_module_exec},
    {Py_mod_multiple_interpreters, Py_MOD_PER_INTERPRETER_GIL_SUPPORTED},
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
    {0, NULL}
};

static struct PyModuleDef thread_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_thread",
    .m_doc = thread_doc,
    .m_size = sizeof(thread_module_state),
    .m_methods = thread_methods,
    .m_traverse = thread_module_traverse,
    .m_clear = thread_module_clear,
    .m_free = thread_module_free,
    .m_slots = thread_module_slots,
};

PyMODINIT_FUNC
PyInit__thread(void)
{
    return PyModuleDef_Init(&thread_module);
}
