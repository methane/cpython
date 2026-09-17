#ifndef Py_INTERNAL_ENUMOBJECT_H
#define Py_INTERNAL_ENUMOBJECT_H

#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pycore_typedefs.h"

/* Advance a bounded, callback-free portion of an optimized enumerate loop. */
PyAPI_FUNC(void) _PyEnum_AdvanceIntTuple(
    PyObject *iterator, _PyInterpreterFrame *frame,
    uint32_t slots, Py_ssize_t field, int mask);

#ifdef __cplusplus
}
#endif

#endif /* Py_INTERNAL_ENUMOBJECT_H */
