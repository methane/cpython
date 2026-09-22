"""Access checks at public numeric C API boundaries."""

import sys
import threading
import unittest
import warnings

from test.support import import_helper, swap_attr, threading_helper


capi = import_helper.import_module('_testcapi')
threading_helper.requires_working_threading(module=True)


class NumberAccessTests(unittest.TestCase):
    def test_object_type_and_size_foreign_operand(self):
        limited = import_helper.import_module('_testlimitedcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        holder = self.foreign_value(value=42)
        for api in (limited.object_type, limited.object_size,
                    capi.PyObject_LengthHint, limited.mapping_size,
                    limited.mapping_length):
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, holder)
                with sys.monitoring.StopTheWorld:
                    try:
                        expected = api(holder[0])
                    except TypeError:
                        with self.assertRaises(TypeError):
                            invoke(api, holder)
                    else:
                        self.assertEqual(invoke(api, holder), (expected,))

    def test_abstract_sequence_and_mapping_foreign_operands(self):
        limited = import_helper.import_module('_testlimitedcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        sequence_holder = self.foreign_container('list')
        mapping_holder = self.foreign_container('dict')
        with sys.monitoring.StopTheWorld:
            sequence = sequence_holder[0]
            mapping = mapping_holder[0]
        with sys.monitoring.StopTheWorld:
            cases = (
                (limited.sequence_size, (sequence,)),
                (limited.sequence_length, (sequence,)),
                (limited.sequence_concat, (sequence, [4])),
                (limited.sequence_repeat, (sequence, 2)),
                (limited.sequence_inplaceconcat, (sequence, [4])),
                (limited.sequence_inplacerepeat, (sequence, 2)),
                (limited.sequence_getitem, (sequence, 0)),
                (limited.sequence_getslice, (sequence, 0, 1)),
                (limited.sequence_setitem, (sequence, 0, 4)),
                (limited.sequence_delitem, (sequence, 0)),
                (limited.sequence_setslice, (sequence, 0, 1, [4])),
                (limited.sequence_delslice, (sequence, 0, 1)),
                (limited.sequence_count, (sequence, 1)),
                (limited.sequence_contains, (sequence, 1)),
                (limited.sequence_index, (sequence, 1)),
                (limited.sequence_list, (sequence,)),
                (limited.sequence_tuple, (sequence,)),
                (limited.sequence_fast, (sequence, 'sequence required')),
                (limited.mapping_keys, (mapping,)),
                (limited.mapping_values, (mapping,)),
                (limited.mapping_items, (mapping,)),
            )
        for api, args in cases:
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, args)

    def test_cfunction_getself_foreign_result(self):
        holder = self.foreign_value()
        with sys.monitoring.StopTheWorld:
            api_args = (holder[0].bit_length,)
        invoke = capi.call_cfunction_raw_return_in_tuple
        with self.assertRaises(IllegalThreadAccessException):
            invoke(capi.pycfunction_getself, api_args)
        with sys.monitoring.StopTheWorld:
            self.assertIs(invoke(capi.pycfunction_getself, api_args)[0], holder[0])

    def foreign_cfunction(self):
        results = threading.Channel()
        def worker():
            results.put((int(42).bit_length,))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        return results.get()

    def foreign_container(self, kind):
        results = threading.Channel()
        def worker(kind):
            if kind == 'list':
                results.put(([1, 2, 3],))
            else:
                results.put(({'key': 42},))
        thread = threading.Thread(target=worker, args=(kind,),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        return results.get()

    def test_cfunction_accessors_foreign_operand(self):
        holder = self.foreign_cfunction()
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in (capi.pycfunction_getself, capi.pycfunction_getfunction,
                    capi.pycfunction_getflags):
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, holder)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(invoke(api, holder), (api(holder[0]),))

    def test_cfunction_accessors_contracts(self):
        self.assertIsNone(capi.pycfunction_getself(capi.MethStatic.meth_noargs))
        self.assertIs(capi.pycfunction_getself(capi.meth_noargs), capi)
        receiver = capi.MethInstance()
        self.assertIs(capi.pycfunction_getself(receiver.meth_noargs), receiver)
        self.assertTrue(capi.pycfunction_getfunction(receiver.meth_noargs))
        self.assertEqual(capi.pycfunction_getflags(receiver.meth_noargs), 4)  # METH_NOARGS
        for api in (capi.pycfunction_getself, capi.pycfunction_getfunction,
                    capi.pycfunction_getflags):
            with self.subTest(api=api.__name__):
                with self.assertRaises(SystemError):
                    api(object())

    def test_json_encoder_foreign_native_function(self):
        json = import_helper.import_module('_json')
        holder = self.foreign_cfunction()
        with sys.monitoring.StopTheWorld:
            args = (None, None, holder[0], None, ':', ',', False, False, True)
        with self.assertRaises(IllegalThreadAccessException):
            capi.pyobject_vectorcall(json.make_encoder, args, None)
        with sys.monitoring.StopTheWorld:
            encoder = capi.pyobject_vectorcall(json.make_encoder, args, None)
            self.assertIsInstance(encoder, json.make_encoder)

    def test_bound_native_foreign_receiver(self):
        holder = self.foreign_value()
        with sys.monitoring.StopTheWorld:
            methods = (holder[0].bit_length, holder[0].bit_count,
                       holder[0].as_integer_ratio)
        for api in methods:
            with self.subTest(name=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.pyobject_vectorcall(api, (), None)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(capi.pyobject_vectorcall(api, (), None),
                                     getattr(42, api.__name__)())

    def test_native_function_foreign_argument(self):
        holder = self.foreign_value()
        for obj in (capi, capi.MethInstance(), capi.MethClass, capi.MethStatic):
            for name in ('meth_o', 'meth_varargs', 'meth_varargs_keywords',
                         'meth_fastcall', 'meth_fastcall_keywords'):
                api = getattr(obj, name)
                with self.subTest(kind=type(obj).__name__, name=name):
                    with self.assertRaises(IllegalThreadAccessException):
                        capi.pyobject_vectorcall(api, holder, None)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(capi.pyobject_vectorcall(api, holder, None),
                                         api(*holder))

    def test_native_function_foreign_keyword(self):
        holder = self.foreign_value()
        names = self.foreign_value(str, 'value')
        for obj in (capi, capi.MethInstance(), capi.MethClass, capi.MethStatic):
            for name in ('meth_varargs_keywords', 'meth_fastcall_keywords'):
                api = getattr(obj, name)
                for args, kwnames in ((holder, ('value',)), ((42,), names)):
                    with self.subTest(kind=type(obj).__name__, name=name):
                        with self.assertRaises(IllegalThreadAccessException):
                            capi.pyobject_vectorcall(api, args, kwnames)
                        with sys.monitoring.StopTheWorld:
                            self.assertEqual(capi.pyobject_vectorcall(api, args, kwnames),
                                             api(value=42))

    def test_method_descriptor_foreign_receiver(self):
        holder = self.foreign_value()
        for api in (int.bit_length, int.bit_count, int.as_integer_ratio):
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.pyobject_vectorcall(api, holder, None)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(capi.pyobject_vectorcall(api, holder, None),
                                     api(42))

    def test_method_descriptor_foreign_argument(self):
        holder = self.foreign_value()
        receiver = capi.MethInstance()
        for name in ('meth_o', 'meth_varargs', 'meth_varargs_keywords',
                     'meth_fastcall', 'meth_fastcall_keywords'):
            api = getattr(capi.MethInstance, name)
            with sys.monitoring.StopTheWorld:
                args = (receiver, holder[0])
            with self.subTest(name=name):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.pyobject_vectorcall(api, args, None)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(capi.pyobject_vectorcall(api, args, None),
                                     api(*args))

    def test_method_descriptor_foreign_keyword(self):
        holder = self.foreign_value()
        receiver = capi.MethInstance()
        for name in ('meth_varargs_keywords', 'meth_fastcall_keywords'):
            api = getattr(capi.MethInstance, name)
            with sys.monitoring.StopTheWorld:
                args = (receiver, holder[0])
            with self.subTest(name=name):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.pyobject_vectorcall(api, args, ('value',))
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(capi.pyobject_vectorcall(api, args, ('value',)),
                                     api(receiver, value=holder[0]))

    def test_method_descriptor_foreign_keyword_name(self):
        names = self.foreign_value(str, 'value')
        receiver = capi.MethInstance()
        for name in ('meth_varargs_keywords', 'meth_fastcall_keywords'):
            api = getattr(capi.MethInstance, name)
            with self.subTest(name=name):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.pyobject_vectorcall(api, (receiver, 42), names)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(capi.pyobject_vectorcall(api, (receiver, 42), names),
                                     api(receiver, value=42))

    def test_comparison_wrapper_foreign_operand(self):
        for base in (int, float):
            holder = self.foreign_value(base)
            for name in ('__lt__', '__le__', '__eq__', '__ne__', '__gt__', '__ge__'):
                with sys.monitoring.StopTheWorld:
                    cases = ((getattr(float, name), (1.0, holder[0])),
                             (getattr(1.0, name), holder))
                for api, args in cases:
                    with self.subTest(base=base, name=name):
                        with self.assertRaises(IllegalThreadAccessException):
                            capi.pyobject_vectorcall(api, args, None)
                        with sys.monitoring.StopTheWorld:
                            self.assertEqual(capi.pyobject_vectorcall(api, args, None),
                                             getattr(1.0, name)(base(42)))

    def test_comparison_wrapper_foreign_receiver(self):
        holder = self.foreign_value(float)
        for name in ('__lt__', '__le__', '__eq__', '__ne__', '__gt__', '__ge__'):
            with sys.monitoring.StopTheWorld:
                cases = ((getattr(float, name), (holder[0], 1.0)),
                         (getattr(holder[0], name), (1.0,)))
            for api, args in cases:
                with self.subTest(name=name):
                    with self.assertRaises(IllegalThreadAccessException):
                        capi.pyobject_vectorcall(api, args, None)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(capi.pyobject_vectorcall(api, args, None),
                                         getattr(42.0, name)(1.0))

    def test_slot_wrapper_protected_receiver(self):
        for lock in (threading.Lock(), threading.RLock()):
            with lock:
                holder = (lock.protect([42]),)
                cases = ((list.__len__, holder), (holder[0].__len__, ()))
            for api, args in cases:
                with self.subTest(lock=type(lock).__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        capi.pyobject_vectorcall(api, args, None)
                    with lock:
                        self.assertEqual(capi.pyobject_vectorcall(api, args, None), 1)

    def test_slot_wrapper_keyword_argument(self):
        holder = self.foreign_value()
        with sys.monitoring.StopTheWorld:
            kwargs = {'value': holder[0]}
        for bound in (False, True):
            target = {}
            api, args = ((target.__init__, ()) if bound
                         else (dict.__init__, (target,)))
            with self.subTest(bound=bound):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.pyobject_fastcalldict(api, args, kwargs)
                self.assertEqual(target, {})
                with sys.monitoring.StopTheWorld:
                    capi.pyobject_fastcalldict(api, args, kwargs)
                    self.assertIs(target['value'], holder[0])

    def uid_gid_apis(self):
        os = import_helper.import_module('os')
        pwd = import_helper.import_module('pwd')
        grp = import_helper.import_module('grp')
        return ((pwd.getpwuid, os.getuid()), (grp.getgrgid, os.getgid()))

    def test_uid_gid_foreign_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api, value in self.uid_gid_apis():
            holder = self.foreign_value(value=value)
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, holder)
                with sys.monitoring.StopTheWorld:
                    try:
                        expected = api(value)
                    except KeyError:
                        with self.assertRaises(KeyError):
                            invoke(api, holder)
                    else:
                        self.assertEqual(invoke(api, holder), (expected,))

    def test_uid_gid_foreign_index_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api, value in self.uid_gid_apis():
            receiver = capi.NativeIndexResult(self.foreign_value(value=value))
            with self.subTest(api=api.__name__):
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter('always', DeprecationWarning)
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, (receiver,))
                    self.assertEqual(recorded, [])
                    with sys.monitoring.StopTheWorld:
                        try:
                            expected = api(value)
                        except KeyError:
                            with self.assertRaises(KeyError):
                                invoke(api, (receiver,))
                        else:
                            self.assertEqual(invoke(api, (receiver,)), (expected,))
                    self.assertEqual(len(recorded), 1)

    def test_uid_gid_index_exception(self):
        class Index:
            def __index__(self):
                raise LookupError('uid/gid index error')

        for api, value in self.uid_gid_apis():
            with self.subTest(api=api.__name__):
                with self.assertRaisesRegex(LookupError, 'uid/gid index error'):
                    api(Index())
                with self.assertRaises(TypeError):
                    api(object())

    def test_integer_sign_foreign_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for value in (0, 42, -1, 1 << 80, -(1 << 80)):
            holder = self.foreign_value(value=value)
            for api in (capi.pylong_getsign, capi.pylong_ispositive,
                        capi.pylong_isnegative, capi.pylong_iszero):
                with self.subTest(value=value, api=api.__name__):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, holder)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, holder), (api(value),))

    def test_integer_export_foreign_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for value in (0, 42, -1, 1 << 80, -(1 << 80)):
            holder = self.foreign_value(value=value)
            with self.subTest(value=value):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(capi.pylong_export, holder)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(invoke(capi.pylong_export, holder),
                                     (capi.pylong_export(value),))

    def test_fixedwidth_foreign_operand(self):
        limited = import_helper.import_module('_testlimitedcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        for value in (42, -1, 1 << 80, -(1 << 80)):
            holder = self.foreign_value(value=value)
            for name in ('pylong_asint32', 'pylong_asuint32',
                         'pylong_asint64', 'pylong_asuint64'):
                api = getattr(limited, name)
                with self.subTest(value=value, api=name):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, holder)
                    with sys.monitoring.StopTheWorld:
                        try:
                            expected = api(value)
                        except (OverflowError, ValueError) as exc:
                            with self.assertRaises(type(exc)):
                                invoke(api, holder)
                        else:
                            self.assertEqual(invoke(api, holder), (expected,))

    def test_nativebytes_foreign_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for value in (42, -1, 1 << 80, -(1 << 80)):
            holder = self.foreign_value(value=value)
            for size in (0, 1, 16):
                for flags in (-1, 0, 1, 4, 8, 16):
                    with self.subTest(value=value, size=size, flags=flags):
                        output = bytearray(b'\xa5' * 16)
                        with sys.monitoring.StopTheWorld:
                            args = (holder[0], output, size, flags)
                        with self.assertRaises(IllegalThreadAccessException):
                            invoke(capi.pylong_asnativebytes, args)
                        self.assertEqual(output, b'\xa5' * 16)
                        expected = bytearray(b'\xa5' * 16)
                        with sys.monitoring.StopTheWorld:
                            try:
                                count = capi.pylong_asnativebytes(
                                    value, expected, size, flags)
                            except ValueError:
                                with self.assertRaises(ValueError):
                                    invoke(capi.pylong_asnativebytes, args)
                            else:
                                self.assertEqual(
                                    invoke(capi.pylong_asnativebytes, args),
                                    (count,))
                            self.assertEqual(output, expected)

    def test_nativebytes_foreign_index_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeIndexResult(self.foreign_value())
        output = bytearray(b'\xa5' * 16)
        # ALLOW_INDEX with little endian output.
        args = (receiver, output, len(output), 16 | 1)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter('always', DeprecationWarning)
            with self.assertRaises(IllegalThreadAccessException):
                invoke(capi.pylong_asnativebytes, args)
            self.assertEqual(output, b'\xa5' * 16)
            self.assertEqual(recorded, [])
            with sys.monitoring.StopTheWorld:
                invoke(capi.pylong_asnativebytes, args)
            self.assertEqual(output, b'\x2a' + b'\x00' * 15)
            self.assertEqual(len(recorded), 1)

    def test_nativebytes_warning_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeIndexResult(self.foreign_value())
        for raises in (False, True):
            with self.subTest(raises=raises):
                output = bytearray(b'\xa5' * 16)
                args = (receiver, output, len(output), 16 | 1)
                calls = []
                def showwarning(*args, **kwargs):
                    calls.append(True)
                    sys.monitoring.StopTheWorld.__exit__(None, None, None)
                    if raises:
                        raise LookupError('native bytes warning error')
                with warnings.catch_warnings(), swap_attr(
                        warnings, 'showwarning', showwarning):
                    warnings.simplefilter('always', DeprecationWarning)
                    sys.monitoring.StopTheWorld.__enter__()
                    try:
                        error = (LookupError if raises
                                 else IllegalThreadAccessException)
                        with self.assertRaises(error):
                            invoke(capi.pylong_asnativebytes, args)
                    finally:
                        if not calls:
                            sys.monitoring.StopTheWorld.__exit__(None, None, None)
                    self.assertEqual(calls, [True])
                    self.assertEqual(output, b'\xa5' * 16)

    def integer_scalar_apis(self):
        limited = import_helper.import_module('_testlimitedcapi')
        names = ('PyLong_AsInt', 'pylong_aslong', 'pylong_aslongandoverflow',
                 'pylong_asunsignedlong', 'pylong_asunsignedlongmask',
                 'pylong_aslonglong', 'pylong_aslonglongandoverflow',
                 'pylong_asunsignedlonglong', 'pylong_asunsignedlonglongmask',
                 'pylong_as_ssize_t', 'pylong_as_size_t', 'pylong_asdouble')
        return (*[getattr(limited, name) for name in names],
                capi.long_asvoidptr_value)

    def test_integer_scalar_foreign_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for value in (42, -1, 1 << 80, -(1 << 80)):
            holder = self.foreign_value(value=value)
            for api in self.integer_scalar_apis():
                with self.subTest(value=value, api=api.__name__):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, holder)
                    with sys.monitoring.StopTheWorld:
                        try:
                            expected = api(value)
                        except OverflowError:
                            with self.assertRaises(OverflowError):
                                invoke(api, holder)
                        else:
                            self.assertEqual(invoke(api, holder), (expected,))

    def test_integer_scalar_index_result(self):
        limited = import_helper.import_module('_testlimitedcapi')
        names = ('PyLong_AsInt', 'pylong_aslong', 'pylong_aslongandoverflow',
                 'pylong_asunsignedlongmask', 'pylong_aslonglong',
                 'pylong_aslonglongandoverflow', 'pylong_asunsignedlonglongmask',
                 'pylong_asint32', 'pylong_asuint32',
                 'pylong_asint64', 'pylong_asuint64')
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeIndexResult(self.foreign_value())
        for name in names:
            api = getattr(limited, name)
            with self.subTest(api=name):
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter('always', DeprecationWarning)
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, (receiver,))
                    self.assertEqual(recorded, [])
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, (receiver,)), (api(42),))
                    self.assertEqual(len(recorded), 1)

    def test_integer_native_argument_conversion(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        holder = self.foreign_value(value=8)
        with sys.monitoring.StopTheWorld:
            args = (holder[0], 42.0, 0)
        with self.assertRaises(IllegalThreadAccessException):
            invoke(capi.float_pack, args)
        with sys.monitoring.StopTheWorld:
            self.assertEqual(invoke(capi.float_pack, args),
                             (b'@E\x00\x00\x00\x00\x00\x00',))

    def test_float_asdouble_foreign_operand(self):
        api = import_helper.import_module('_testlimitedcapi').float_asdouble
        invoke = capi.call_cfunction_raw_return_in_tuple
        for base in (int, float):
            holder = self.foreign_value(base)
            with self.subTest(base=base):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, holder)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(invoke(api, holder), (42.0,))

    def test_float_asdouble_native_result(self):
        api = import_helper.import_module('_testlimitedcapi').float_asdouble
        invoke = capi.call_cfunction_raw_return_in_tuple
        for base, factory in ((int, capi.NativeIndexResult),
                              (float, capi.NativeConversionResult)):
            receiver = factory(self.foreign_value(base))
            with self.subTest(base=base):
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter('always', DeprecationWarning)
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, (receiver,))
                    self.assertEqual(recorded, [])
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, (receiver,)), (42.0,))
                    self.assertEqual(len(recorded), 1)

    def test_float_asdouble_warning_lifetime(self):
        api = import_helper.import_module('_testlimitedcapi').float_asdouble
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeConversionResult(self.foreign_value(float))
        for raises in (False, True):
            with self.subTest(raises=raises):
                calls = []
                def showwarning(*args, **kwargs):
                    calls.append(True)
                    sys.monitoring.StopTheWorld.__exit__(None, None, None)
                    if raises:
                        raise LookupError('double conversion warning error')
                with warnings.catch_warnings(), swap_attr(
                        warnings, 'showwarning', showwarning):
                    warnings.simplefilter('always', DeprecationWarning)
                    sys.monitoring.StopTheWorld.__enter__()
                    try:
                        error = (LookupError if raises
                                 else IllegalThreadAccessException)
                        with self.assertRaises(error):
                            invoke(api, (receiver,))
                    finally:
                        if not calls:
                            sys.monitoring.StopTheWorld.__exit__(None, None, None)
                    self.assertEqual(calls, [True])

    def test_float_asdouble_protected_operand(self):
        class Number:
            def __float__(self):
                return 42.0
        api = import_helper.import_module('_testlimitedcapi').float_asdouble
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                holder = (lock.protect(Number()),)
            with self.subTest(lock_type=lock_type):
                with self.assertRaises(UnprotectedAccessException):
                    invoke(api, holder)
                with lock:
                    self.assertEqual(invoke(api, holder), (42.0,))

    def test_float_native_argument_conversion(self):
        holder = self.foreign_value(float)
        invoke = capi.call_cfunction_raw_return_in_tuple
        with sys.monitoring.StopTheWorld:
            args = (8, holder[0], 0)
        with self.assertRaises(IllegalThreadAccessException):
            invoke(capi.float_pack, args)
        with sys.monitoring.StopTheWorld:
            self.assertEqual(invoke(capi.float_pack, args),
                             (b'@E\x00\x00\x00\x00\x00\x00',))

    def test_conversion_foreign_numeric_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for base in (int, float):
            holder = self.foreign_value(base)
            for api in (capi.number_long, capi.number_float):
                with self.subTest(base=base, api=api.__name__):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, holder)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, holder), (42,))

    def test_conversion_foreign_text_operand(self):
        results = threading.Channel()
        def worker():
            class Text(str):
                pass
            class Bytes(bytes):
                pass
            results.put(((Text('42'),), (Bytes(b'42'),), (bytearray(b'42'),)))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        invoke = capi.call_cfunction_raw_return_in_tuple
        for position, holder in enumerate(results.get()):
            for api in (capi.number_long, capi.number_float):
                with self.subTest(position=position, api=api.__name__):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, holder)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, holder), (42,))

    def test_conversion_foreign_native_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for base, api in ((int, capi.number_long), (float, capi.number_float)):
            receiver = capi.NativeConversionResult(self.foreign_value(base))
            with self.subTest(api=api.__name__):
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter('always', DeprecationWarning)
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, (receiver,))
                    self.assertEqual(recorded, [])
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, (receiver,)), (42,))
                    self.assertEqual(len(recorded), 1)

    def test_conversion_warning_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for base, api in ((int, capi.number_long), (float, capi.number_float)):
            receiver = capi.NativeConversionResult(self.foreign_value(base))
            for raises in (False, True):
                with self.subTest(api=api.__name__, raises=raises):
                    calls = []
                    def showwarning(*args, **kwargs):
                        calls.append(True)
                        sys.monitoring.StopTheWorld.__exit__(None, None, None)
                        if raises:
                            raise LookupError('conversion warning error')
                    with warnings.catch_warnings(), swap_attr(
                            warnings, 'showwarning', showwarning):
                        warnings.simplefilter('always', DeprecationWarning)
                        sys.monitoring.StopTheWorld.__enter__()
                        try:
                            error = (LookupError if raises
                                     else IllegalThreadAccessException)
                            with self.assertRaises(error):
                                invoke(api, (receiver,))
                        finally:
                            if not calls:
                                sys.monitoring.StopTheWorld.__exit__(
                                    None, None, None)
                        self.assertEqual(calls, [True])

    def test_conversion_protected_operand(self):
        class Number:
            def __int__(self):
                return 42
            def __float__(self):
                return 42.0
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                holder = (lock.protect(Number()),)
            for api in (capi.number_long, capi.number_float):
                with self.subTest(lock_type=lock_type, api=api.__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        invoke(api, holder)
                    with lock:
                        self.assertEqual(invoke(api, holder), (42,))

    def index_calls(self, holder):
        with sys.monitoring.StopTheWorld:
            return ((capi.number_index, holder, 42),
                    (capi.number_asssizet, (holder[0], OverflowError), 42),
                    (capi.number_tobase, (holder[0], 16), '0x2a'))

    def test_index_foreign_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api, args, expected in self.index_calls(self.foreign_value()):
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, args)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(invoke(api, args), (expected,))

    def test_index_foreign_native_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeIndexResult(self.foreign_value())
        cases = (*self.index_calls((receiver,)),
                 (capi.number_long, (receiver,), 42),
                 (capi.number_float, (receiver,), 42.0))
        for api, args, expected in cases:
            with self.subTest(api=api.__name__):
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter('always', DeprecationWarning)
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, args)
                    self.assertEqual(recorded, [])
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, args), (expected,))
                    self.assertEqual(len(recorded), 1)

    def test_index_warning_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeIndexResult(self.foreign_value())
        cases = (*self.index_calls((receiver,)),
                 (capi.number_long, (receiver,), 42),
                 (capi.number_float, (receiver,), 42.0))
        for api, args, expected in cases:
            for raises in (False, True):
                with self.subTest(api=api.__name__, raises=raises):
                    calls = []
                    def showwarning(*args, **kwargs):
                        calls.append(True)
                        sys.monitoring.StopTheWorld.__exit__(None, None, None)
                        if raises:
                            raise LookupError('warning handler error')
                    with warnings.catch_warnings(), swap_attr(
                            warnings, 'showwarning', showwarning):
                        warnings.simplefilter('always', DeprecationWarning)
                        sys.monitoring.StopTheWorld.__enter__()
                        try:
                            error = (LookupError if raises
                                     else IllegalThreadAccessException)
                            with self.assertRaises(error):
                                invoke(api, args)
                        finally:
                            if not calls:
                                sys.monitoring.StopTheWorld.__exit__(
                                    None, None, None)
                        self.assertEqual(calls, [True])

    def test_index_protected_operand(self):
        class Index:
            def __index__(self):
                return 42
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                holder = (lock.protect(Index()),)
            for api, args, expected in self.index_calls(holder):
                with self.subTest(lock_type=lock_type, api=api.__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        invoke(api, args)
                    with lock:
                        self.assertEqual(invoke(api, args), (expected,))

    def test_power_foreign_operand(self):
        foreign = self.foreign_value()
        with sys.monitoring.StopTheWorld:
            pairs = ((foreign[0], 2), (2, foreign[0]),
                     (foreign[0], 2, 3), (2, foreign[0], 3), (2, 3, foreign[0]))
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in (capi.number_power, capi.number_inplacepower):
            for position, args in enumerate(pairs):
                with self.subTest(api=api.__name__, position=position):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, args)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, args), (pow(*args),))

    def test_power_native_result(self):
        foreign = self.foreign_value()
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                protected = (lock.protect([]),)
            for holder, error in ((foreign, IllegalThreadAccessException),
                                  (protected, UnprotectedAccessException)):
                receiver = capi.NativePowerResult(holder)
                pairs = ((receiver, 2), (2, receiver), (receiver, 2, 3),
                         (2, receiver, 3), (2, 3, receiver))
                for api in (capi.number_power, capi.number_inplacepower):
                    for position, args in enumerate(pairs):
                        with self.subTest(lock_type=lock_type, error=error,
                                          api=api.__name__, position=position):
                            with self.assertRaises(error):
                                invoke(api, args)
                            with sys.monitoring.StopTheWorld:
                                self.assertIs(invoke(api, args)[0], holder[0])

    def test_power_protected_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativePowerResult((42,))
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                value = lock.protect([])
                pairs = ((value, receiver), (receiver, value),
                         (value, receiver, 3), (receiver, value, 3),
                         (receiver, 2, value))
                del value
            for api in (capi.number_power, capi.number_inplacepower):
                for position, args in enumerate(pairs):
                    with self.subTest(lock_type=lock_type, api=api.__name__,
                                      position=position):
                        with self.assertRaises(UnprotectedAccessException):
                            invoke(api, args)
                        with lock:
                            self.assertEqual(invoke(api, args), (42,))

    def test_power_subclass_notimplemented_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            calls = []
            class Derived(capi.NativePowerResult):
                def __rpow__(self, base, modulus=None):
                    calls.append(True)
                    lock.__exit__(None, None, None)
                    return NotImplemented
            with lock:
                args = (capi.NativePowerResult((42,)), Derived((43,)),
                        lock.protect([]))
            lock.__enter__()
            try:
                with self.assertRaises(UnprotectedAccessException):
                    invoke(capi.number_power, args)
            finally:
                if not calls:
                    lock.__exit__(None, None, None)
            self.assertEqual(calls, [True])

    def test_power_modulus_callback_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            for api in (capi.number_power, capi.number_inplacepower):
                for raises in (False, True):
                    with self.subTest(lock_type=lock_type, api=api.__name__,
                                      raises=raises):
                        lock = lock_type()
                        calls = []
                        def callback():
                            calls.append(True)
                            lock.__exit__(None, None, None)
                            if raises:
                                raise LookupError('modulus callback error')
                            return NotImplemented
                        modulus = capi.NativePowerCallback((callback,))
                        with lock:
                            args = (lock.protect([]), 2, modulus)
                        lock.__enter__()
                        try:
                            error = (LookupError if raises
                                     else UnprotectedAccessException)
                            with self.assertRaises(error):
                                invoke(api, args)
                        finally:
                            if not calls:
                                lock.__exit__(None, None, None)
                        self.assertEqual(calls, [True])

    def test_power_callback_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            for api in (capi.number_power, capi.number_inplacepower):
                for side in ('left', 'right'):
                    for raises in (False, True):
                        with self.subTest(lock_type=lock_type, api=api.__name__,
                                          side=side, raises=raises):
                            lock = lock_type()
                            calls = []
                            class Callback:
                                def __pow__(self, other, modulus=None):
                                    calls.append(True)
                                    lock.__exit__(None, None, None)
                                    if raises:
                                        raise LookupError('callback error')
                                    return NotImplemented
                                __rpow__ = __ipow__ = __pow__
                            with lock:
                                value = lock.protect([])
                                args = ((Callback(), value) if side == 'left'
                                        else (value, Callback()))
                                del value
                            lock.__enter__()
                            try:
                                error = (LookupError if raises
                                         else UnprotectedAccessException)
                                with self.assertRaises(error):
                                    invoke(api, args)
                            finally:
                                if not calls:
                                    lock.__exit__(None, None, None)
                            self.assertEqual(calls, [True])

    def inplace_apis(self):
        return tuple(getattr(capi, 'number_inplace' + name) for name in (
            'add', 'subtract', 'multiply', 'matrixmultiply', 'floordivide',
            'truedivide', 'remainder', 'lshift', 'rshift', 'and', 'xor', 'or'))

    def test_inplace_foreign_operand(self):
        results = threading.Channel()
        def worker():
            with sys.monitoring.StopTheWorld:
                results.put((capi.NativeBinaryResult((42,)),))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        foreign = results.get()
        local = capi.NativeBinaryResult((42,))
        with sys.monitoring.StopTheWorld:
            pairs = ((foreign[0], 2), (local, foreign[0]))
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in self.inplace_apis():
            for side, args in enumerate(pairs):
                with self.subTest(api=api.__name__, side=side):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, args)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, args), (42,))

    def test_inplace_protected_operand(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        receiver = capi.NativeBinaryResult((42,))
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                args = (receiver, lock.protect([]))
            for api in self.inplace_apis():
                with self.subTest(lock_type=lock_type, api=api.__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        invoke(api, args)
                    with lock:
                        self.assertEqual(invoke(api, args), (42,))

    def test_inplace_native_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        foreign = self.foreign_value()
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                protected = (lock.protect([]),)
            for holder, error in ((foreign, IllegalThreadAccessException),
                                  (protected, UnprotectedAccessException)):
                receiver = capi.NativeBinaryResult(holder)
                for api in self.inplace_apis():
                    with self.subTest(lock_type=lock_type, error=error,
                                      api=api.__name__):
                        with self.assertRaises(error):
                            invoke(api, (receiver, 2))
                        with sys.monitoring.StopTheWorld:
                            self.assertIs(invoke(api, (receiver, 2))[0], holder[0])

    def test_inplace_callback_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            for raises in (False, True):
                with self.subTest(lock_type=lock_type, raises=raises):
                    lock = lock_type()
                    calls = []
                    class Callback:
                        def __iadd__(self, other):
                            calls.append('inplace')
                            lock.__exit__(None, None, None)
                            if raises:
                                raise LookupError('native callback error')
                            return NotImplemented
                        def __add__(self, other):
                            calls.append('ordinary')
                            return 42
                    with lock:
                        holder = (lock.protect(Callback()),)
                    lock.__enter__()
                    try:
                        args = (holder[0], 2)
                        error = LookupError if raises else UnprotectedAccessException
                        with self.assertRaises(error):
                            invoke(capi.number_inplaceadd, args)
                    finally:
                        if not calls:
                            lock.__exit__(None, None, None)
                    self.assertEqual(calls, ['inplace'])

    def binary_apis(self):
        return tuple(getattr(capi, 'number_' + name) for name in (
            'add', 'subtract', 'multiply', 'matrixmultiply', 'floordivide',
            'truedivide', 'remainder', 'divmod', 'lshift', 'rshift',
            'and', 'xor', 'or'))

    def test_binary_foreign_operand(self):
        holder = self.foreign_value()
        with sys.monitoring.StopTheWorld:
            pairs = ((holder[0], 2), (2, holder[0]))
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in self.binary_apis():
            for side, args in enumerate(pairs):
                with self.subTest(api=api.__name__, side=side):
                    with self.assertRaises(IllegalThreadAccessException):
                        invoke(api, args)

    def test_binary_native_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        foreign = self.foreign_value()
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                protected = (lock.protect([]),)
            for holder, error in ((foreign, IllegalThreadAccessException),
                                  (protected, UnprotectedAccessException)):
                receiver = capi.NativeBinaryResult(holder)
                for api in self.binary_apis():
                    for side, args in enumerate(((receiver, 2), (2, receiver))):
                        with self.subTest(lock_type=lock_type, error=error,
                                          api=api.__name__, side=side):
                            with self.assertRaises(error):
                                invoke(api, args)
                            with sys.monitoring.StopTheWorld:
                                self.assertIs(invoke(api, args)[0], holder[0])

    def test_sequence_fallback_native_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                holder = (lock.protect([]),)
                receiver = capi.NativeSequenceResult(holder)
            for api, args in ((capi.number_add, (receiver, ())),
                              (capi.number_inplaceadd, (receiver, ())),
                              (capi.number_multiply, (receiver, 2)),
                              (capi.number_multiply, (2, receiver)),
                              (capi.number_inplacemultiply, (receiver, 2))):
                with self.subTest(lock_type=lock_type, api=api.__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        invoke(api, args)
                    with lock:
                        self.assertIs(invoke(api, args)[0], holder[0])

    def test_binary_notimplemented_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            for side in ('left', 'right'):
                with self.subTest(lock_type=lock_type, side=side):
                    lock = lock_type()
                    calls = []
                    class Callback:
                        def __add__(self, other):
                            calls.append(True)
                            lock.__exit__(None, None, None)
                            return NotImplemented
                        __radd__ = __add__
                    with lock:
                        holder = (lock.protect([42]),)
                    lock.__enter__()
                    try:
                        args = ((Callback(), holder[0]) if side == 'left'
                                else (holder[0], Callback()))
                        with self.assertRaises(UnprotectedAccessException):
                            invoke(capi.number_add, args)
                    finally:
                        if not calls:
                            lock.__exit__(None, None, None)
                    self.assertEqual(calls, [True])
                    with lock:
                        self.assertEqual(holder[0], [42])

    def test_sequence_repeat_index_lifetime(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            for api in (capi.number_multiply, capi.number_inplacemultiply):
                for side in ('left', 'right'):
                    with self.subTest(lock_type=lock_type, api=api.__name__,
                                      side=side):
                        lock = lock_type()
                        calls = []
                        class Index:
                            def __index__(self):
                                calls.append(True)
                                lock.__exit__(None, None, None)
                                return 2
                        with lock:
                            holder = (lock.protect([42]),)
                        lock.__enter__()
                        try:
                            args = ((holder[0], Index()) if side == 'left'
                                    else (Index(), holder[0]))
                            # Python instances have a sequence table, so the
                            # inplace API does not try right-hand repetition.
                            unsupported = (api is capi.number_inplacemultiply
                                           and side == 'right')
                            error = (TypeError if unsupported
                                     else UnprotectedAccessException)
                            with self.assertRaises(error):
                                invoke(api, args)
                        finally:
                            if not calls:
                                lock.__exit__(None, None, None)
                        self.assertEqual(calls, [] if unsupported else [True])
                        with lock:
                            self.assertEqual(holder[0], [42])

    def unary_apis(self):
        return (capi.number_negative, capi.number_positive,
                capi.number_absolute, capi.number_invert)

    def foreign_value(self, base=int, value=42):
        results = threading.Channel()
        def worker(base, value):
            class Number(base):
                pass
            results.put((Number(value),))
        thread = threading.Thread(target=worker, args=(base, value), group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        return results.get()

    def test_unary_foreign_operand(self):
        holder = self.foreign_value()
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in self.unary_apis():
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, holder)
                with sys.monitoring.StopTheWorld:
                    self.assertEqual(invoke(api, holder), (api(holder[0]),))

    def test_unary_foreign_native_result(self):
        holder = self.foreign_value()
        receiver = capi.NativeUnaryResult(holder)
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in self.unary_apis():
            with self.subTest(api=api.__name__):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(api, (receiver,))
                with sys.monitoring.StopTheWorld:
                    self.assertIs(invoke(api, (receiver,))[0], holder[0])

    def test_unary_protected_operand(self):
        class Number:
            def __neg__(self):
                return 42
            __pos__ = __abs__ = __invert__ = __neg__

        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                holder = (lock.protect(Number()),)
            for api in self.unary_apis():
                with self.subTest(lock_type=lock_type, api=api.__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        invoke(api, holder)
                    with lock:
                        self.assertEqual(invoke(api, holder), (42,))

    def test_unary_protected_native_result(self):
        invoke = capi.call_cfunction_raw_return_in_tuple
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()
            with lock:
                holder = (lock.protect([]),)
                receiver = capi.NativeUnaryResult(holder)
            for api in self.unary_apis():
                with self.subTest(lock_type=lock_type, api=api.__name__):
                    with self.assertRaises(UnprotectedAccessException):
                        invoke(api, (receiver,))
                    with lock:
                        self.assertIs(invoke(api, (receiver,))[0], holder[0])

    def test_unary_native_error(self):
        receiver = capi.NativeUnaryResult(())
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api in self.unary_apis():
            with self.subTest(api=api.__name__):
                with self.assertRaisesRegex(TypeError, 'one stored result'):
                    invoke(api, (receiver,))


if __name__ == '__main__':
    unittest.main()
