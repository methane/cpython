#ifndef Py_INTERNAL_OBJECT_ALLOC_H
#define Py_INTERNAL_OBJECT_ALLOC_H

#include "pycore_object.h"      // _PyType_HasFeature()
#include "pycore_pystate.h"     // _PyThreadState_GET()
#include "pycore_tstate.h"      // _PyThreadStateImpl

#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

// Allocate on the heap matching the object's GC/preheader layout. These use
// the configured object allocator, including any embedding or tracing hooks.
extern void *_PyObject_MallocWithType(PyTypeObject *tp, size_t size);
extern void *_PyObject_ReallocWithType(PyTypeObject *tp, void *ptr, size_t size);

#ifdef __cplusplus
}
#endif
#endif  // !Py_INTERNAL_OBJECT_ALLOC_H
