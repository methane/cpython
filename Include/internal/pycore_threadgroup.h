#ifndef Py_INTERNAL_THREADGROUP_H
#define Py_INTERNAL_THREADGROUP_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pycore_object_stack.h"

/* The scheduling state has a separate lifetime from its Python wrapper:
   detaching and deleting a thread state must not run Python finalizers. */
typedef struct _PyThreadGroupState {
    PyMutex mutex;
    PyMutex holder_mutex;
    PyThreadState *holder;
    /* Foreign decrefs wait here until the owning group can merge them. */
    PyMutex brc_mutex;
    _PyObjectStack objects_to_merge;
    /* Includes detached and not-yet-started thread states. Protected by
       brc_mutex, together with adoption of an abandoned object's bias. */
    Py_ssize_t threads;
    Py_ssize_t refcount;
    uint32_t id;
    struct _PyThreadGroupState *next;
    /* wrapper is non-owning and protected by holder_mutex. The name is raw
       UCS4 storage so detached scheduler destruction cannot run Python. */
    PyObject *wrapper;
    Py_UCS4 *name;
    Py_ssize_t name_length;
} _PyThreadGroupState;

extern PyTypeObject _PyThreadGroup_Type;

extern _PyThreadGroupState *_PyThreadGroup_New(PyInterpreterState *interp);
/* Return a strong reference, or NULL if the ID belongs to no group in interp. */
PyAPI_FUNC(_PyThreadGroupState *) _PyThreadGroup_Find(
    PyInterpreterState *interp, uint32_t id);
// Whether any live interpreter still owns this process-wide group ID.
extern int _PyThreadGroup_OwnerIsAlive(uint32_t id);
PyAPI_FUNC(PyObject *) _PyThreadGroup_GetObject(
    PyInterpreterState *interp, uint32_t id);
/* Validate a Python wrapper and return a strong native reference. */
PyAPI_FUNC(_PyThreadGroupState *) _PyThreadGroup_GetState(PyObject *group);
extern void _PyThreadGroup_Fini(PyInterpreterState *interp);
extern void _PyThreadGroup_Acquire(PyThreadState *tstate);
extern void _PyThreadGroup_Release(PyThreadState *tstate);
/* Assign a new, detached thread state, or remove a cleared thread state.
   Takes its own reference to group; NULL removes membership. */
PyAPI_FUNC(void) _PyThreadGroup_SetThreadState(
    PyThreadState *tstate, _PyThreadGroupState *group);
/* Take ownership only if the old group has no thread states. The caller
   holds a reference, or has exclusive responsibility for deallocation. */
PyAPI_FUNC(int) _PyThreadGroup_TryAdopt(PyObject *op, PyThreadState *tstate);
PyAPI_FUNC(void) _PyThreadGroup_Decref(_PyThreadGroupState *group);

static inline void
_PyThreadGroup_Incref(_PyThreadGroupState *group)
{
    _Py_atomic_add_ssize(&group->refcount, 1);
}

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_THREADGROUP_H */
