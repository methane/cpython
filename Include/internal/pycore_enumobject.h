#ifndef Py_INTERNAL_ENUMOBJECT_H
#define Py_INTERNAL_ENUMOBJECT_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

typedef struct {
    PyObject_HEAD
    Py_ssize_t en_index;
    PyObject *en_sit;
    PyObject *en_result;
    PyObject *en_longindex;
    PyObject *one;  /* borrowed */
} _PyEnumObject;

#ifdef __cplusplus
}
#endif
#endif  /* !Py_INTERNAL_ENUMOBJECT_H */
