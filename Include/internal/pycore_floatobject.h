#ifndef Py_INTERNAL_FLOATOBJECT_H
#define Py_INTERNAL_FLOATOBJECT_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pycore_stackref.h"      // _PyStackRef
#include "pycore_unicodeobject.h" // _PyUnicodeWriter


// Reuse an unaliased temporary operand for an exact float binary operation.
#define _PyEval_FloatBinaryOp(left, right, left_o, right_o, OP)          \
    _PyStackRef _float_binary_res;                                      \
    do {                                                                \
        double _dres =                                                   \
            ((PyFloatObject *)left_o)->ob_fval                          \
            OP ((PyFloatObject *)right_o)->ob_fval;                     \
        if (PyStackRef_RefcountOnObject(left) &&                         \
            _PyObject_IsUniquelyReferenced(left_o))                     \
        {                                                               \
            ((PyFloatObject *)left_o)->ob_fval = _dres;                 \
            _float_binary_res = left;                                   \
            left = PyStackRef_Borrow(left);                             \
        }                                                               \
        else if (PyStackRef_RefcountOnObject(right) &&                   \
                 _PyObject_IsUniquelyReferenced(right_o))               \
        {                                                               \
            ((PyFloatObject *)right_o)->ob_fval = _dres;                \
            _float_binary_res = right;                                  \
            right = PyStackRef_Borrow(right);                           \
        }                                                               \
        else {                                                          \
            PyObject *_d = PyFloat_FromDouble(_dres);                   \
            _float_binary_res = _d == NULL                              \
                ? PyStackRef_NULL                                       \
                : PyStackRef_FromPyObjectSteal(_d);                     \
        }                                                               \
    } while (0)

/* runtime lifecycle */

extern PyStatus _PyFloat_InitTypes(PyInterpreterState *);
extern void _PyFloat_FiniType(PyInterpreterState *);




PyAPI_FUNC(void) _PyFloat_ExactDealloc(PyObject *op);


extern void _PyFloat_DebugMallocStats(FILE* out);


/* Format the object based on the format_spec, as defined in PEP 3101
   (Advanced String Formatting). */
extern int _PyFloat_FormatAdvancedWriter(
    _PyUnicodeWriter *writer,
    PyObject *obj,
    PyObject *format_spec,
    Py_ssize_t start,
    Py_ssize_t end);

extern PyObject* _Py_string_to_number_with_underscores(
    const char *str, Py_ssize_t len, const char *what, PyObject *obj, void *arg,
    PyObject *(*innerfunc)(const char *, Py_ssize_t, void *));

extern double _Py_parse_inf_or_nan(const char *p, char **endptr);

extern int _Py_convert_int_to_double(PyObject **v, double *dbl);

/* Should match endianness of the platform in most (all?) cases. */

#ifdef DOUBLE_IS_BIG_ENDIAN_IEEE754
#  define _PY_FLOAT_BIG_ENDIAN 1
#  define _PY_FLOAT_LITTLE_ENDIAN 0
#else
#  define _PY_FLOAT_BIG_ENDIAN 0
#  define _PY_FLOAT_LITTLE_ENDIAN 1
#endif

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_FLOATOBJECT_H */
