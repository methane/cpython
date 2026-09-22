#include "parts.h"
#include "util.h"

static PyObject *
native_unary_result(PyObject *self)
{
    if (PyTuple_GET_SIZE(self) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected one stored result");
        return NULL;
    }
    /* Deliberately leave validation to the public numeric API. */
    return Py_NewRef(PyTuple_GET_ITEM(self, 0));
}

static PyType_Slot native_unary_slots[] = {
    {Py_nb_negative, native_unary_result},
    {Py_nb_positive, native_unary_result},
    {Py_nb_absolute, native_unary_result},
    {Py_nb_invert, native_unary_result},
    {0, NULL},
};

static PyType_Spec native_unary_spec = {
    .name = "_testcapi.NativeUnaryResult",
    .flags = Py_TPFLAGS_DEFAULT,
    .slots = native_unary_slots,
};

static PyObject *
native_binary_result(PyObject *left, PyObject *right)
{
    return native_unary_result(PyTuple_Check(left) ? left : right);
}

static PyType_Slot native_binary_slots[] = {
    {Py_nb_add, native_binary_result},
    {Py_nb_subtract, native_binary_result},
    {Py_nb_multiply, native_binary_result},
    {Py_nb_matrix_multiply, native_binary_result},
    {Py_nb_floor_divide, native_binary_result},
    {Py_nb_true_divide, native_binary_result},
    {Py_nb_remainder, native_binary_result},
    {Py_nb_divmod, native_binary_result},
    {Py_nb_lshift, native_binary_result},
    {Py_nb_rshift, native_binary_result},
    {Py_nb_and, native_binary_result},
    {Py_nb_xor, native_binary_result},
    {Py_nb_or, native_binary_result},
    {Py_nb_inplace_add, native_binary_result},
    {Py_nb_inplace_subtract, native_binary_result},
    {Py_nb_inplace_multiply, native_binary_result},
    {Py_nb_inplace_matrix_multiply, native_binary_result},
    {Py_nb_inplace_floor_divide, native_binary_result},
    {Py_nb_inplace_true_divide, native_binary_result},
    {Py_nb_inplace_remainder, native_binary_result},
    {Py_nb_inplace_lshift, native_binary_result},
    {Py_nb_inplace_rshift, native_binary_result},
    {Py_nb_inplace_and, native_binary_result},
    {Py_nb_inplace_xor, native_binary_result},
    {Py_nb_inplace_or, native_binary_result},
    {0, NULL},
};

static PyType_Spec native_binary_spec = {
    .name = "_testcapi.NativeBinaryResult",
    .flags = Py_TPFLAGS_DEFAULT,
    .slots = native_binary_slots,
};

static PyObject *
native_repeat_result(PyObject *self, Py_ssize_t count)
{
    return native_unary_result(self);
}

static PyType_Slot native_sequence_slots[] = {
    {Py_sq_concat, native_binary_result},
    {Py_sq_inplace_concat, native_binary_result},
    {Py_sq_repeat, native_repeat_result},
    {Py_sq_inplace_repeat, native_repeat_result},
    {0, NULL},
};

static PyType_Spec native_sequence_spec = {
    .name = "_testcapi.NativeSequenceResult",
    .flags = Py_TPFLAGS_DEFAULT,
    .slots = native_sequence_slots,
};

static PyObject *
native_power_result(PyObject *base, PyObject *exponent, PyObject *modulus)
{
    PyObject *holder = PyTuple_Check(base) ? base :
                       PyTuple_Check(exponent) ? exponent : modulus;
    if (!PyTuple_Check(holder)) {
        Py_RETURN_NOTIMPLEMENTED;
    }
    return native_unary_result(holder);
}

static PyType_Slot native_power_slots[] = {
    {Py_nb_power, native_power_result},
    {Py_nb_inplace_power, native_power_result},
    {0, NULL},
};

static PyType_Spec native_power_spec = {
    .name = "_testcapi.NativePowerResult",
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    .slots = native_power_slots,
};

static PyObject *
native_power_callback(PyObject *base, PyObject *exponent, PyObject *modulus)
{
    PyObject *callback = native_power_result(base, exponent, modulus);
    if (callback == NULL || callback == Py_NotImplemented) {
        return callback;
    }
    PyObject *result = PyObject_CallNoArgs(callback);
    Py_DECREF(callback);
    return result;
}

static PyType_Slot native_power_callback_slots[] = {
    {Py_nb_power, native_power_callback},
    {0, NULL},
};

static PyType_Spec native_power_callback_spec = {
    .name = "_testcapi.NativePowerCallback",
    .flags = Py_TPFLAGS_DEFAULT,
    .slots = native_power_callback_slots,
};

static PyType_Slot native_index_slots[] = {
    {Py_nb_index, native_unary_result},
    {0, NULL},
};

static PyType_Spec native_index_spec = {
    .name = "_testcapi.NativeIndexResult",
    .flags = Py_TPFLAGS_DEFAULT,
    .slots = native_index_slots,
};

static PyType_Slot native_conversion_slots[] = {
    {Py_nb_int, native_unary_result},
    {Py_nb_float, native_unary_result},
    {0, NULL},
};

static PyType_Spec native_conversion_spec = {
    .name = "_testcapi.NativeConversionResult",
    .flags = Py_TPFLAGS_DEFAULT,
    .slots = native_conversion_slots,
};

static PyObject *
long_asvoidptr_value(PyObject *self, PyObject *arg)
{
    void *value = PyLong_AsVoidPtr(arg);
    if (value == NULL && PyErr_Occurred()) {
        return NULL;
    }
    /* Compare the pointer's bits without dereferencing arbitrary addresses. */
    return PyLong_FromVoidPtr(value);
}

static PyObject *
number_check(PyObject *Py_UNUSED(module), PyObject *obj)
{
    NULLABLE(obj);
    return PyLong_FromLong(PyNumber_Check(obj));
}

#define BINARYFUNC(funcsuffix, methsuffix)                           \
    static PyObject *                                                \
    number_##methsuffix(PyObject *Py_UNUSED(module), PyObject *args) \
    {                                                                \
        PyObject *o1, *o2;                                           \
                                                                     \
        if (!PyArg_ParseTuple(args, "OO", &o1, &o2)) {               \
            return NULL;                                             \
        }                                                            \
                                                                     \
        NULLABLE(o1);                                                \
        NULLABLE(o2);                                                \
        return PyNumber_##funcsuffix(o1, o2);                        \
    };

BINARYFUNC(Add, add)
BINARYFUNC(Subtract, subtract)
BINARYFUNC(Multiply, multiply)
BINARYFUNC(MatrixMultiply, matrixmultiply)
BINARYFUNC(FloorDivide, floordivide)
BINARYFUNC(TrueDivide, truedivide)
BINARYFUNC(Remainder, remainder)
BINARYFUNC(Divmod, divmod)

#define TERNARYFUNC(funcsuffix, methsuffix)                          \
    static PyObject *                                                \
    number_##methsuffix(PyObject *Py_UNUSED(module), PyObject *args) \
    {                                                                \
        PyObject *o1, *o2, *o3 = Py_None;                            \
                                                                     \
        if (!PyArg_ParseTuple(args, "OO|O", &o1, &o2, &o3)) {        \
            return NULL;                                             \
        }                                                            \
                                                                     \
        NULLABLE(o1);                                                \
        NULLABLE(o2);                                                \
        return PyNumber_##funcsuffix(o1, o2, o3);                    \
    };

TERNARYFUNC(Power, power)

#define UNARYFUNC(funcsuffix, methsuffix)                            \
    static PyObject *                                                \
    number_##methsuffix(PyObject *Py_UNUSED(module), PyObject *obj)  \
    {                                                                \
        NULLABLE(obj);                                               \
        return PyNumber_##funcsuffix(obj);                           \
    };

UNARYFUNC(Negative, negative)
UNARYFUNC(Positive, positive)
UNARYFUNC(Absolute, absolute)
UNARYFUNC(Invert, invert)

BINARYFUNC(Lshift, lshift)
BINARYFUNC(Rshift, rshift)
BINARYFUNC(And, and)
BINARYFUNC(Xor, xor)
BINARYFUNC(Or, or)

BINARYFUNC(InPlaceAdd, inplaceadd)
BINARYFUNC(InPlaceSubtract, inplacesubtract)
BINARYFUNC(InPlaceMultiply, inplacemultiply)
BINARYFUNC(InPlaceMatrixMultiply, inplacematrixmultiply)
BINARYFUNC(InPlaceFloorDivide, inplacefloordivide)
BINARYFUNC(InPlaceTrueDivide, inplacetruedivide)
BINARYFUNC(InPlaceRemainder, inplaceremainder)

TERNARYFUNC(InPlacePower, inplacepower)

BINARYFUNC(InPlaceLshift, inplacelshift)
BINARYFUNC(InPlaceRshift, inplacershift)
BINARYFUNC(InPlaceAnd, inplaceand)
BINARYFUNC(InPlaceXor, inplacexor)
BINARYFUNC(InPlaceOr, inplaceor)

UNARYFUNC(Long, long)
UNARYFUNC(Float, float)
UNARYFUNC(Index, index)

static PyObject *
number_tobase(PyObject *Py_UNUSED(module), PyObject *args)
{
    PyObject *n;
    int base;

    if (!PyArg_ParseTuple(args, "Oi", &n, &base)) {
        return NULL;
    }

    NULLABLE(n);
    return PyNumber_ToBase(n, base);
}

static PyObject *
number_asssizet(PyObject *Py_UNUSED(module), PyObject *args)
{
    PyObject *o, *exc;
    Py_ssize_t ret;

    if (!PyArg_ParseTuple(args, "OO", &o, &exc)) {
        return NULL;
    }

    NULLABLE(o);
    NULLABLE(exc);
    ret = PyNumber_AsSsize_t(o, exc);

    if (ret == (Py_ssize_t)(-1) && PyErr_Occurred()) {
        return NULL;
    }

    return PyLong_FromSsize_t(ret);
}


static PyMethodDef test_methods[] = {
    {"long_asvoidptr_value", long_asvoidptr_value, METH_O},
    {"number_check", number_check, METH_O},
    {"number_add", number_add, METH_VARARGS},
    {"number_subtract", number_subtract, METH_VARARGS},
    {"number_multiply", number_multiply, METH_VARARGS},
    {"number_matrixmultiply", number_matrixmultiply, METH_VARARGS},
    {"number_floordivide", number_floordivide, METH_VARARGS},
    {"number_truedivide", number_truedivide, METH_VARARGS},
    {"number_remainder", number_remainder, METH_VARARGS},
    {"number_divmod", number_divmod, METH_VARARGS},
    {"number_power", number_power, METH_VARARGS},
    {"number_negative", number_negative, METH_O},
    {"number_positive", number_positive, METH_O},
    {"number_absolute", number_absolute, METH_O},
    {"number_invert", number_invert, METH_O},
    {"number_lshift", number_lshift, METH_VARARGS},
    {"number_rshift", number_rshift, METH_VARARGS},
    {"number_and", number_and, METH_VARARGS},
    {"number_xor", number_xor, METH_VARARGS},
    {"number_or", number_or, METH_VARARGS},
    {"number_inplaceadd", number_inplaceadd, METH_VARARGS},
    {"number_inplacesubtract", number_inplacesubtract, METH_VARARGS},
    {"number_inplacemultiply", number_inplacemultiply, METH_VARARGS},
    {"number_inplacematrixmultiply", number_inplacematrixmultiply, METH_VARARGS},
    {"number_inplacefloordivide", number_inplacefloordivide, METH_VARARGS},
    {"number_inplacetruedivide", number_inplacetruedivide, METH_VARARGS},
    {"number_inplaceremainder", number_inplaceremainder, METH_VARARGS},
    {"number_inplacepower", number_inplacepower, METH_VARARGS},
    {"number_inplacelshift", number_inplacelshift, METH_VARARGS},
    {"number_inplacershift", number_inplacershift, METH_VARARGS},
    {"number_inplaceand", number_inplaceand, METH_VARARGS},
    {"number_inplacexor", number_inplacexor, METH_VARARGS},
    {"number_inplaceor", number_inplaceor, METH_VARARGS},
    {"number_long", number_long, METH_O},
    {"number_float", number_float, METH_O},
    {"number_index", number_index, METH_O},
    {"number_tobase", number_tobase, METH_VARARGS},
    {"number_asssizet", number_asssizet, METH_VARARGS},
    {NULL},
};

int
_PyTestCapi_Init_Numbers(PyObject *mod)
{
    if (PyModule_AddFunctions(mod, test_methods) < 0) {
        return -1;
    }

    PyObject *bases = PyTuple_Pack(1, &PyTuple_Type);
    if (bases == NULL) {
        return -1;
    }
    struct {
        const char *name;
        PyType_Spec *spec;
    } types[] = {
        {"NativeUnaryResult", &native_unary_spec},
        {"NativeBinaryResult", &native_binary_spec},
        {"NativeSequenceResult", &native_sequence_spec},
        {"NativePowerResult", &native_power_spec},
        {"NativePowerCallback", &native_power_callback_spec},
        {"NativeIndexResult", &native_index_spec},
        {"NativeConversionResult", &native_conversion_spec},
    };
    for (size_t i = 0; i < (sizeof(types) / sizeof(types[0])); i++) {
        PyObject *type = PyType_FromSpecWithBases(types[i].spec, bases);
        if (type == NULL) {
            Py_DECREF(bases);
            return -1;
        }
        int result = PyModule_AddObjectRef(mod, types[i].name, type);
        Py_DECREF(type);
        if (result < 0) {
            Py_DECREF(bases);
            return -1;
        }
    }
    Py_DECREF(bases);
    return 0;
}
