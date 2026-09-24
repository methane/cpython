#ifndef Py_INTERNAL_INDEX_POOL_H
#define Py_INTERNAL_INDEX_POOL_H

#include "Python.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pycore_interp_structs.h"

// Allocate unique indices in an array. Each thread has an interpreter-local
// index into code objects' thread-local bytecode arrays.


// Allocate the smallest available index. Returns -1 on error.
extern int32_t _PyIndexPool_AllocIndex(_PyIndexPool *indices);

// Release `index` back to the pool
extern void _PyIndexPool_FreeIndex(_PyIndexPool *indices, int32_t index);

extern void _PyIndexPool_Fini(_PyIndexPool *indices);

#ifdef __cplusplus
}
#endif
#endif // !Py_INTERNAL_INDEX_POOL_H
