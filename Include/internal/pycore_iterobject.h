#ifndef Py_INTERNAL_ITEROBJECT_H
#define Py_INTERNAL_ITEROBJECT_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

extern PyTypeObject _PyACallIter_Type;
extern PyTypeObject _PyACallIterAwaitable_Type;

// Zip's ordinary next protocol, with a fast path for two list iterators.
// *direct is 0 for the ordinary path, 1 for tuple reuse, or 2 for allocation.
PyAPI_FUNC(PyObject *) _PyZip_NextListPair(PyObject *iter, int *direct);

// Like PyCallIter_New(), but the iteration also stops when *callable* raises
// an exception matching *stop_exc* (an exception class or a tuple of exception
// classes).  *sentinel* can be NULL; NULL *stop_exc* means StopIteration.
extern PyObject *_PyCallIter_NewEx(PyObject *callable, PyObject *sentinel,
                                   PyObject *stop_exc);

// The asynchronous counterpart of _PyCallIter_NewEx(): the result of
// *callable* is awaited, and NULL *stop_exc* means StopAsyncIteration.
extern PyObject *_PyACallIter_New(PyObject *callable, PyObject *sentinel,
                                  PyObject *stop_exc);

#ifdef __cplusplus
}
#endif
#endif   /* !Py_INTERNAL_ITEROBJECT_H */
