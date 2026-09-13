#ifndef Py_INTERNAL_RANGE_H
#define Py_INTERNAL_RANGE_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

typedef struct {
    PyObject_HEAD
    PyObject *start;
    PyObject *stop;
    PyObject *step;
    PyObject *length;
} _PyRangeObject;

typedef struct {
    PyObject_HEAD
    long start;
    long step;
    long len;
} _PyRangeIterObject;

extern PyObject *_PyRange_FromCompactStop(PyObject *stop);
extern PyObject *_PyRangeIter_FromCompactRange(PyObject *range);

#ifdef __cplusplus
}
#endif
#endif   /* !Py_INTERNAL_RANGE_H */
