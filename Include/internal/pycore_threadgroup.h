#ifndef Py_INTERNAL_THREADGROUP_H
#define Py_INTERNAL_THREADGROUP_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

/* The scheduling state has a separate lifetime from its Python wrapper:
   detaching and deleting a thread state must not run Python finalizers. */
typedef struct _PyThreadGroupState {
    PyMutex mutex;
    PyMutex holder_mutex;
    PyThreadState *holder;
    Py_ssize_t refcount;
    uint32_t id;
    struct _PyThreadGroupState *next;
    /* wrapper is non-owning and protected by holder_mutex. The name is raw
       UCS4 storage so detached scheduler destruction cannot run Python. */
    PyObject *wrapper;
    Py_UCS4 *name;
    Py_ssize_t name_length;
} _PyThreadGroupState;

extern _PyThreadGroupState *_PyThreadGroup_New(PyInterpreterState *interp);
/* Return a strong reference, or NULL if the ID belongs to no group in interp. */
PyAPI_FUNC(_PyThreadGroupState *) _PyThreadGroup_Find(
    PyInterpreterState *interp, uint32_t id);
PyAPI_FUNC(PyObject *) _PyThreadGroup_GetObject(
    PyInterpreterState *interp, uint32_t id);
extern void _PyThreadGroup_Fini(PyInterpreterState *interp);
extern void _PyThreadGroup_Acquire(PyThreadState *tstate);
extern void _PyThreadGroup_Release(PyThreadState *tstate);
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
