#ifndef Py_INTERNAL_OBJECT_DEFERRED_H
#define Py_INTERNAL_OBJECT_DEFERRED_H

#ifdef __cplusplus
extern "C" {
#endif

#include "pycore_gc.h"

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

// Enable deferred reference counting for a newly created immutable object.
// It must subsequently be tracked by the GC so it is eventually collected.
extern void _PyObject_SetDeferredRefcount(PyObject *op);

static inline int
_PyObject_HasDeferredRefcount(PyObject *op)
{
    return _PyObject_HAS_GC_BITS(op, _PyGC_BITS_DEFERRED);
}

#ifdef __cplusplus
}
#endif
#endif  // !Py_INTERNAL_OBJECT_DEFERRED_H
