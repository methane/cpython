#ifndef Py_ODICTOBJECT_H
#define Py_ODICTOBJECT_H
#ifdef __cplusplus
extern "C" {
#endif


/* OrderedDict */

#ifndef Py_LIMITED_API

typedef struct _odictobject PyODictObject;

PyAPI_DATA(PyTypeObject) PyODict_Type;
PyAPI_DATA(PyTypeObject) PyODictIter_Type;
PyAPI_DATA(PyTypeObject) PyODictKeys_Type;
PyAPI_DATA(PyTypeObject) PyODictItems_Type;
PyAPI_DATA(PyTypeObject) PyODictValues_Type;

#define PyODict_Check(op) PyObject_TypeCheck(op, &PyODict_Type)
#define PyODict_CheckExact(op) (Py_TYPE(op) == &PyODict_Type)
#define PyODict_SIZE(op) PyDict_GET_SIZE((op))

#endif /* Py_LIMITED_API */

#if !defined(Py_LIMITED_API) || Py_LIMITED_API+0 >= 0x03050000

PyAPI_FUNC(PyObject *) PyODict_New(void);
PyAPI_FUNC(int) PyODict_SetItem(PyObject *od, PyObject *key, PyObject *item);
PyAPI_FUNC(int) PyODict_DelItem(PyObject *od, PyObject *key);

/* wrappers around PyDict* functions */
#define PyODict_GetItem(od, key) PyDict_GetItem((PyObject *)od, key)
#define PyODict_GetItemWithError(od, key) \
    PyDict_GetItemWithError((PyObject *)od, key)
#define PyODict_Contains(od, key) PyDict_Contains((PyObject *)od, key)
#define PyODict_Size(od) PyDict_Size((PyObject *)od)
#define PyODict_GetItemString(od, key) \
    PyDict_GetItemString((PyObject *)od, key)

/* Private API for using ODict for LRU */
PyAPI_FUNC(PyObject *) _PyODict_LRUGetItem(
    PyObject *od, PyObject *key, Py_hash_t hash);
PyAPI_FUNC(int) _PyODict_SetItem_KnownHash(PyObject *od, PyObject *key,
                                           PyObject *value, Py_hash_t hash);
PyAPI_FUNC(int) _PyODict_LRULimitSize(PyObject *od, Py_ssize_t maxsize);

#endif

#ifdef __cplusplus
}
#endif
#endif /* !Py_ODICTOBJECT_H */
