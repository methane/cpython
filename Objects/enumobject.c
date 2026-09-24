/* enumerate object */

#include "Python.h"
#include "pycore_call.h"          // _PyObject_CallNoArgs()
#include "pycore_dict.h"          // _PyDict_SynchronizeNamespace()
#include "pycore_long.h"          // _PyLong_GetOne()
#include "pycore_modsupport.h"    // _PyArg_NoKwnames()
#include "pycore_object.h"        // _PyObject_GC_TRACK()
#include "pycore_unicodeobject.h" // _PyUnicode_EqualToASCIIString
#include "pycore_tuple.h"         // _PyTuple_Recycle()

#include "clinic/enumobject.c.h"

/*[clinic input]
class enumerate "enumobject *" "&PyEnum_Type"
class reversed "reversedobject *" "&PyReversed_Type"
[clinic start generated code]*/
/*[clinic end generated code: output=da39a3ee5e6b4b0d input=d2dfdf1a88c88975]*/

typedef struct {
    PyObject_HEAD
    Py_ssize_t en_index;           /* current index of enumeration */
    PyObject* en_sit;              /* secondary iterator of enumeration */
    PyObject* en_result;           /* result tuple  */
    PyObject* en_longindex;        /* index for sequences >= PY_SSIZE_T_MAX */
    PyObject* one;                 /* borrowed reference */
} enumobject;

#define _enumobject_CAST(op)    ((enumobject *)(op))

// Initialize a subclass's namespace before publishing a shared iterator.
// The base types have no dictionary; subclasses may use managed inline values.
static int
inherit_iterator_state(PyObject *iterator, PyObject *source)
{
    _PyObject_InheritShareable(iterator, source);
    uint8_t state = FT_ATOMIC_LOAD_UINT8(iterator->ob_shareable);
    if (state == _Py_SHAREABLE_LOCAL ||
        Py_TYPE(iterator)->tp_dictoffset == 0) {
        return 0;
    }
    PyObject *dict = PyObject_GenericGetDict(iterator, NULL);
    if (dict == NULL) {
        return -1;
    }
    int res = 0;
    if (state == _Py_SHAREABLE_SYNCHRONIZED) {
        res = _PyDict_SynchronizeNamespace(dict);
    }
    else {
        assert(state == _Py_SHAREABLE_PROTECTED);
        _PyObject_InheritShareable(dict, iterator);
    }
    Py_DECREF(dict);
    return res;
}

/*[clinic input]
@vectorcall
@classmethod
enumerate.__new__ as enum_new

    iterable: object
        an object supporting iteration
    start: object = 0

Return an enumerate object.

The enumerate object yields pairs containing a count (from start, which
defaults to zero) and a value yielded by the iterable argument.

enumerate is useful for obtaining an indexed list:
    (0, seq[0]), (1, seq[1]), (2, seq[2]), ...
[clinic start generated code]*/

static PyObject *
enum_new_impl(PyTypeObject *type, PyObject *iterable, PyObject *start)
/*[clinic end generated code: output=e95e6e439f812c10 input=a139e88889360e8f]*/
{
    enumobject *en;

    if (PyObject_CheckAccess(iterable) == NULL ||
        (start != NULL && PyObject_CheckAccess(start) == NULL)) {
        return NULL;
    }

    en = (enumobject *)type->tp_alloc(type, 0);
    if (en == NULL)
        return NULL;
    if (start != NULL) {
        start = PyNumber_Index(start);
        if (start == NULL) {
            Py_DECREF(en);
            return NULL;
        }
        assert(PyLong_Check(start));
        en->en_index = PyLong_AsSsize_t(start);
        if (en->en_index == -1 && PyErr_Occurred()) {
            PyErr_Clear();
            en->en_index = PY_SSIZE_T_MAX;
            en->en_longindex = start;
        } else {
            en->en_longindex = NULL;
            Py_DECREF(start);
        }
    } else {
        en->en_index = 0;
        en->en_longindex = NULL;
    }
    en->en_sit = PyObject_GetIter(iterable);
    if (en->en_sit == NULL) {
        Py_DECREF(en);
        return NULL;
    }
    en->en_result = _PyTuple_FromPairSteal(Py_None, Py_None);
    if (en->en_result == NULL) {
        Py_DECREF(en);
        return NULL;
    }
    en->one = _PyLong_GetOne();    /* borrowed reference */
    if (inherit_iterator_state((PyObject *)en, en->en_sit) < 0) {
        Py_DECREF(en);
        return NULL;
    }
    return (PyObject *)en;
}

static void
enum_dealloc(PyObject *op)
{
    enumobject *en = _enumobject_CAST(op);
    PyObject_GC_UnTrack(en);
    Py_XDECREF(en->en_sit);
    Py_XDECREF(en->en_result);
    Py_XDECREF(en->en_longindex);
    Py_TYPE(en)->tp_free(en);
}

static int
enum_traverse(PyObject *op, visitproc visit, void *arg)
{
    enumobject *en = _enumobject_CAST(op);
    Py_VISIT(en->en_sit);
    Py_VISIT(en->en_result);
    Py_VISIT(en->en_longindex);
    return 0;
}

// increment en_longindex with lock held, return the next index to be used
// or NULL on error
static inline PyObject *
increment_longindex_lock_held(enumobject *en)
{
    if (en->en_longindex == NULL) {
        en->en_longindex = PyLong_FromSsize_t(PY_SSIZE_T_MAX);
        if (en->en_longindex == NULL) {
            return NULL;
        }
    }
    assert(en->en_longindex != NULL);
    // We hold one reference to "next_index" (a.k.a. the old value of
    // en->en_longindex); we'll either return it or keep it in en->en_longindex
    PyObject *next_index = en->en_longindex;
    PyObject *stepped_up = PyNumber_Add(next_index, en->one);
    if (stepped_up == NULL) {
        return NULL;
    }
    en->en_longindex = stepped_up;
    return next_index;
}

static PyObject *
enum_next(PyObject *op)
{
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    enumobject *en = _enumobject_CAST(op);
    PyObject *it = PyObject_CheckAccess(en->en_sit);
    if (it == NULL) {
        return NULL;
    }
    PyObject *next_item = (*Py_TYPE(it)->tp_iternext)(it);
    next_item = _PyObject_CheckAccessNullable(next_item);
    if (next_item == NULL) {
        return NULL;
    }

    PyObject *next_index;
    PyObject *result = en->en_result;
    PyObject *old_index = NULL;
    PyObject *old_item = NULL;
    // The source iterator can run arbitrary code. Only the index update and
    // reuse of the cached tuple belong in this critical section.
    Py_BEGIN_CRITICAL_SECTION(en);
    if (en->en_index == PY_SSIZE_T_MAX) {
        next_index = increment_longindex_lock_held(en);
    }
    else {
        next_index = PyLong_FromSsize_t(en->en_index);
        if (next_index != NULL) {
            en->en_index++;
        }
    }
    if (next_index != NULL && _PyObject_IsUniquelyReferenced(result)) {
        Py_INCREF(result);
        old_index = PyTuple_GET_ITEM(result, 0);
        old_item = PyTuple_GET_ITEM(result, 1);
        PyTuple_SET_ITEM(result, 0, next_index);
        PyTuple_SET_ITEM(result, 1, next_item);
        // bpo-42536: The GC may have untracked this result tuple. Since we're
        // recycling it, make sure it's tracked again:
        _PyTuple_Recycle(result);
    }
    Py_END_CRITICAL_SECTION();

    if (next_index == NULL) {
        Py_DECREF(next_item);
        return NULL;
    }
    if (old_index != NULL) {
        // Releasing the old item may run a finalizer that re-enters enumerate.
        Py_DECREF(old_index);
        Py_DECREF(old_item);
        return result;
    }
    return _PyTuple_FromPairSteal(next_index, next_item);
}

static PyObject *
enum_reduce(PyObject *op, PyObject *Py_UNUSED(ignored))
{
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    enumobject *en = _enumobject_CAST(op);
    PyObject *longindex;
    Py_ssize_t index;
    Py_BEGIN_CRITICAL_SECTION(en);
    longindex = Py_XNewRef(en->en_longindex);
    index = en->en_index;
    Py_END_CRITICAL_SECTION();

    if (longindex != NULL) {
        PyObject *result = Py_BuildValue("O(OO)", Py_TYPE(en), en->en_sit,
                                         longindex);
        Py_DECREF(longindex);
        return result;
    }
    return Py_BuildValue("O(On)", Py_TYPE(en), en->en_sit, index);
}

PyDoc_STRVAR(reduce_doc, "Return state information for pickling.");

static PyMethodDef enum_methods[] = {
    {"__reduce__", enum_reduce, METH_NOARGS, reduce_doc},
    {"__class_getitem__",    Py_GenericAlias,
    METH_O|METH_CLASS,       PyDoc_STR("'enumerate' objects are generic over the type of their values")},
    {NULL,              NULL}           /* sentinel */
};

PyTypeObject PyEnum_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "enumerate",                    /* tp_name */
    sizeof(enumobject),             /* tp_basicsize */
    0,                              /* tp_itemsize */
    /* methods */
    enum_dealloc,                   /* tp_dealloc */
    0,                              /* tp_vectorcall_offset */
    0,                              /* tp_getattr */
    0,                              /* tp_setattr */
    0,                              /* tp_as_async */
    0,                              /* tp_repr */
    0,                              /* tp_as_number */
    0,                              /* tp_as_sequence */
    0,                              /* tp_as_mapping */
    0,                              /* tp_hash */
    0,                              /* tp_call */
    0,                              /* tp_str */
    PyObject_GenericGetAttr,        /* tp_getattro */
    0,                              /* tp_setattro */
    0,                              /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC |
        Py_TPFLAGS_BASETYPE,        /* tp_flags */
    enum_new__doc__,                /* tp_doc */
    enum_traverse,                  /* tp_traverse */
    0,                              /* tp_clear */
    0,                              /* tp_richcompare */
    0,                              /* tp_weaklistoffset */
    PyObject_SelfIter,              /* tp_iter */
    enum_next,                      /* tp_iternext */
    enum_methods,                   /* tp_methods */
    0,                              /* tp_members */
    0,                              /* tp_getset */
    0,                              /* tp_base */
    0,                              /* tp_dict */
    0,                              /* tp_descr_get */
    0,                              /* tp_descr_set */
    0,                              /* tp_dictoffset */
    0,                              /* tp_init */
    PyType_GenericAlloc,            /* tp_alloc */
    enum_new,                       /* tp_new */
    PyObject_GC_Del,                /* tp_free */
    .tp_vectorcall = enum_vectorcall
};

/* Reversed Object ***************************************************************/

typedef struct {
    PyObject_HEAD
    Py_ssize_t      index;
    PyObject* seq;
} reversedobject;

#define _reversedobject_CAST(op)    ((reversedobject *)(op))

/*[clinic input]
@vectorcall
@classmethod
reversed.__new__ as reversed_new

    object as seq: object
    /

Return a reverse iterator over the values of the given sequence.
[clinic start generated code]*/

static PyObject *
reversed_new_impl(PyTypeObject *type, PyObject *seq)
/*[clinic end generated code: output=f7854cc1df26f570 input=7db568182ab28c59]*/
{
    Py_ssize_t n;
    PyObject *reversed_meth;
    reversedobject *ro;

    if (PyObject_CheckAccess(seq) == NULL) {
        return NULL;
    }

    reversed_meth = _PyObject_LookupSpecial(seq, &_Py_ID(__reversed__));
    reversed_meth = _PyObject_CheckAccessNullable(reversed_meth);
    if (reversed_meth == Py_None) {
        Py_DECREF(reversed_meth);
        PyErr_Format(PyExc_TypeError,
                     "'%.200s' object is not reversible",
                     Py_TYPE(seq)->tp_name);
        return NULL;
    }
    if (reversed_meth != NULL) {
        PyObject *res = _PyObject_CallNoArgs(reversed_meth);
        Py_DECREF(reversed_meth);
        return _PyObject_CheckAccessNullable(res);
    }
    else if (PyErr_Occurred())
        return NULL;

    if (!PySequence_Check(seq)) {
        PyErr_Format(PyExc_TypeError,
                     "'%.200s' object is not reversible",
                     Py_TYPE(seq)->tp_name);
        return NULL;
    }

    n = PySequence_Size(seq);
    if (n == -1)
        return NULL;

    ro = (reversedobject *)type->tp_alloc(type, 0);
    if (ro == NULL)
        return NULL;

    ro->index = n-1;
    ro->seq = Py_NewRef(seq);
    if (inherit_iterator_state((PyObject *)ro, seq) < 0) {
        Py_DECREF(ro);
        return NULL;
    }
    return (PyObject *)ro;
}

static void
reversed_dealloc(PyObject *op)
{
    reversedobject *ro = _reversedobject_CAST(op);
    PyObject_GC_UnTrack(ro);
    Py_XDECREF(ro->seq);
    Py_TYPE(ro)->tp_free(ro);
}

static int
reversed_traverse(PyObject *op, visitproc visit, void *arg)
{
    reversedobject *ro = _reversedobject_CAST(op);
    Py_VISIT(ro->seq);
    return 0;
}

static PyObject *
reversed_next_shared(reversedobject *ro)
{
    if (FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index) < 0) {
        return NULL;
    }
    // Shared iterators retain their sequence even after exhaustion.
    PyObject *seq = PyObject_CheckAccess(ro->seq);
    if (seq == NULL) {
        return NULL;
    }
    Py_ssize_t index;
    Py_BEGIN_CRITICAL_SECTION(ro);
    index = FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index);
    if (index >= 0) {
        // Reserve the index before calling the sequence: __getitem__ can
        // suspend a critical section or recursively advance this iterator.
        FT_ATOMIC_STORE_SSIZE_RELAXED(ro->index, index - 1);
    }
    Py_END_CRITICAL_SECTION();
    if (index < 0) {
        return NULL;
    }
    PyObject *item = PySequence_GetItem(seq, index);
    if (item != NULL) {
        return item;
    }
    Py_BEGIN_CRITICAL_SECTION(ro);
    FT_ATOMIC_STORE_SSIZE_RELAXED(ro->index, -1);
    Py_END_CRITICAL_SECTION();
    if (PyErr_ExceptionMatches(PyExc_IndexError) ||
        PyErr_ExceptionMatches(PyExc_StopIteration)) {
        PyErr_Clear();
    }
    return NULL;
}

static PyObject *
reversed_next(PyObject *op)
{
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    reversedobject *ro = _reversedobject_CAST(op);
    if (FT_ATOMIC_LOAD_UINT8(op->ob_shareable) == _Py_SHAREABLE_SYNCHRONIZED) {
        return reversed_next_shared(ro);
    }
    PyObject *item;
    Py_ssize_t index = FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index);

    if (index >= 0) {
        if (PyObject_CheckAccess(ro->seq) == NULL) {
            return NULL;
        }
        item = PySequence_GetItem(ro->seq, index);
        if (item != NULL) {
            FT_ATOMIC_STORE_SSIZE_RELAXED(ro->index, index - 1);
            return item;
        }
        if (PyErr_ExceptionMatches(PyExc_IndexError) ||
            PyErr_ExceptionMatches(PyExc_StopIteration))
            PyErr_Clear();
    }
    FT_ATOMIC_STORE_SSIZE_RELAXED(ro->index, -1);
#ifndef Py_GIL_DISABLED
    Py_CLEAR(ro->seq);
#endif
    return NULL;
}

static PyObject *
reversed_len(PyObject *op, PyObject *Py_UNUSED(ignored))
{
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    reversedobject *ro = _reversedobject_CAST(op);
    Py_ssize_t position, seqsize;
    Py_ssize_t index = FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index);

    if (index == -1)
        return PyLong_FromLong(0);
    assert(ro->seq != NULL);
    if (PyObject_CheckAccess(ro->seq) == NULL) {
        return NULL;
    }
    seqsize = PySequence_Size(ro->seq);
    if (seqsize == -1)
        return NULL;
    position = index + 1;
    return PyLong_FromSsize_t((seqsize < position)  ?  0  :  position);
}

PyDoc_STRVAR(length_hint_doc, "Private method returning an estimate of len(list(it)).");

static PyObject *
reversed_reduce(PyObject *op, PyObject *Py_UNUSED(ignored))
{
    if (PyObject_CheckAccess(op) == NULL) {
        return NULL;
    }
    reversedobject *ro = _reversedobject_CAST(op);
    Py_ssize_t index;
    PyObject *seq;
    Py_BEGIN_CRITICAL_SECTION(ro);
    index = FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index);
    seq = index >= 0 ? Py_NewRef(ro->seq) : NULL;
    Py_END_CRITICAL_SECTION();
    if (seq != NULL) {
        PyObject *result = Py_BuildValue("O(O)n", Py_TYPE(ro), seq, index);
        Py_DECREF(seq);
        return result;
    }
    return Py_BuildValue("O(())", Py_TYPE(ro));
}

static PyObject *
reversed_setstate(PyObject *op, PyObject *state)
{
    if (PyObject_CheckAccess(op) == NULL ||
        PyObject_CheckAccess(state) == NULL) {
        return NULL;
    }
    reversedobject *ro = _reversedobject_CAST(op);
    Py_ssize_t index = PyLong_AsSsize_t(state);
    if (index == -1 && PyErr_Occurred())
        return NULL;
    Py_ssize_t ro_index = FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index);
    // if the iterator is exhausted we do not set the state
    // this is for backwards compatibility reasons. in practice this situation
    // will not occur, see gh-120971
    if (ro_index != -1) {
        if (PyObject_CheckAccess(ro->seq) == NULL) {
            return NULL;
        }
        Py_ssize_t n = PySequence_Size(ro->seq);
        if (n < 0)
            return NULL;
        if (index < -1)
            index = -1;
        else if (index > n-1)
            index = n-1;
        Py_BEGIN_CRITICAL_SECTION(ro);
        // The size callback may have exhausted the iterator in the meantime.
        if (FT_ATOMIC_LOAD_SSIZE_RELAXED(ro->index) != -1) {
            FT_ATOMIC_STORE_SSIZE_RELAXED(ro->index, index);
        }
        Py_END_CRITICAL_SECTION();
    }
    Py_RETURN_NONE;
}

PyDoc_STRVAR(setstate_doc, "Set state information for unpickling.");

static PyMethodDef reversediter_methods[] = {
    {"__length_hint__", reversed_len, METH_NOARGS, length_hint_doc},
    {"__reduce__", reversed_reduce, METH_NOARGS, reduce_doc},
    {"__setstate__", reversed_setstate, METH_O, setstate_doc},
    {NULL,              NULL}           /* sentinel */
};

PyTypeObject PyReversed_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "reversed",                     /* tp_name */
    sizeof(reversedobject),         /* tp_basicsize */
    0,                              /* tp_itemsize */
    /* methods */
    reversed_dealloc,               /* tp_dealloc */
    0,                              /* tp_vectorcall_offset */
    0,                              /* tp_getattr */
    0,                              /* tp_setattr */
    0,                              /* tp_as_async */
    0,                              /* tp_repr */
    0,                              /* tp_as_number */
    0,                              /* tp_as_sequence */
    0,                              /* tp_as_mapping */
    0,                              /* tp_hash */
    0,                              /* tp_call */
    0,                              /* tp_str */
    PyObject_GenericGetAttr,        /* tp_getattro */
    0,                              /* tp_setattro */
    0,                              /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC |
        Py_TPFLAGS_BASETYPE,        /* tp_flags */
    reversed_new__doc__,            /* tp_doc */
    reversed_traverse,              /* tp_traverse */
    0,                              /* tp_clear */
    0,                              /* tp_richcompare */
    0,                              /* tp_weaklistoffset */
    PyObject_SelfIter,              /* tp_iter */
    reversed_next,                  /* tp_iternext */
    reversediter_methods,           /* tp_methods */
    0,                              /* tp_members */
    0,                              /* tp_getset */
    0,                              /* tp_base */
    0,                              /* tp_dict */
    0,                              /* tp_descr_get */
    0,                              /* tp_descr_set */
    0,                              /* tp_dictoffset */
    0,                              /* tp_init */
    PyType_GenericAlloc,            /* tp_alloc */
    reversed_new,                   /* tp_new */
    PyObject_GC_Del,                /* tp_free */
    .tp_vectorcall = reversed_vectorcall,
};
