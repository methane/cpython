#ifndef Py_INTERNAL_RANGE_H
#define Py_INTERNAL_RANGE_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#ifdef Py_GIL_DISABLED
#  include "pycore_object.h"      // _PyObject_IsUniquelyReferenced()
#  ifdef Py_EXPERIMENTAL_TRACING_GC
#    include "pycore_initconfig.h" // _PyConfig_GIL_ENABLE
#    include "pycore_pystate.h"    // _PyInterpreterState_GET()
#  endif

static inline int
_PyRangeIter_IsSafeForSpecialization(PyObject *iter)
{
#ifdef Py_EXPERIMENTAL_TRACING_GC
    // A permanent GIL permits unsynchronized iterator updates even when
    // there are aliases. A temporarily enabled GIL is not sufficient.
    if (_PyInterpreterState_GET()->config.enable_gil == _PyConfig_GIL_ENABLE) {
        return 1;
    }
#endif
    return _PyObject_IsUniquelyReferenced(iter);
}
#endif

typedef struct {
    PyObject_HEAD
    long start;
    long step;
    long len;
} _PyRangeIterObject;

#ifdef __cplusplus
}
#endif
#endif   /* !Py_INTERNAL_RANGE_H */
