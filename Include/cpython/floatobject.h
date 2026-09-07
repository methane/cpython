#ifndef Py_CPYTHON_FLOATOBJECT_H
#  error "this header file must not be included directly"
#endif

typedef struct {
    PyObject_HEAD
    double ob_fval;
} PyFloatObject;

#define _PyFloat_CAST(op) \
    (assert(PyFloat_Check(op)), _Py_CAST(PyFloatObject*, op))

#ifdef Py_EXPERIMENTAL_NANBOX
static inline PyObject *
_PyFloat_EncodeImmediate(double value)
{
    uint64_t bits;
#if defined(__GNUC__)
    __builtin_memcpy(&bits, &value, sizeof(bits));
#else
    memcpy(&bits, &value, sizeof(bits));
#endif
    assert((bits & UINT64_C(0x7fffffffffffffff)) <= UINT64_C(0x7ff0000000000000));
    return (PyObject *)(uintptr_t)(bits + (UINT64_C(1) << 49));
}
#endif

// Static inline version of PyFloat_AsDouble() trading safety for speed.
// It doesn't check if op is a double object.
static inline double PyFloat_AS_DOUBLE(PyObject *op) {
#ifdef Py_EXPERIMENTAL_NANBOX
    if (_PyFloat_IsImmediate(op)) {
        uint64_t bits = (uintptr_t)op - (UINT64_C(1) << 49);
        double value;
#if defined(__GNUC__)
        // JIT stencils use -fno-builtin, but this is a bit cast, not a call.
        __builtin_memcpy(&value, &bits, sizeof(value));
#else
        memcpy(&value, &bits, sizeof(value));
#endif
        return value;
    }
#endif
    return _PyFloat_CAST(op)->ob_fval;
}
#define PyFloat_AS_DOUBLE(op) PyFloat_AS_DOUBLE(_PyObject_CAST(op))


PyAPI_FUNC(int) PyFloat_Pack2(double x, char *p, int le);
PyAPI_FUNC(int) PyFloat_Pack4(double x, char *p, int le);
PyAPI_FUNC(int) PyFloat_Pack8(double x, char *p, int le);

PyAPI_FUNC(double) PyFloat_Unpack2(const char *p, int le);
PyAPI_FUNC(double) PyFloat_Unpack4(const char *p, int le);
PyAPI_FUNC(double) PyFloat_Unpack8(const char *p, int le);
