"""PEP 805 classification and namespaces of synchronized functions."""

import threading
import types
import unittest
import warnings

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


# Publish only the native testing entry points used across groups. Their
# wrappers must reach the function or returned-reference check under test.
_internal = import_module('_testinternalcapi')
_capi = import_module('_testcapi')
_function_get_annotations = _capi.function_get_annotations
_function_get_closure = _capi.function_get_closure
_function_get_code = _capi.function_get_code
_function_get_defaults = _capi.function_get_defaults
_function_get_globals = _capi.function_get_globals
_function_get_kw_defaults = _capi.function_get_kw_defaults
_function_get_module = _capi.function_get_module
_function_set_closure = _capi.function_set_closure
_function_set_dict = _capi.function_set_dict
_object_check_access = _internal.object_check_access
_object_declare_immutable = _internal.object_declare_immutable
_object_owner_id = _internal.object_owner_id
for _helper in (_function_get_annotations, _function_get_closure,
                _function_get_code, _function_get_defaults, _function_get_globals,
                _function_get_kw_defaults, _function_get_module,
                _function_set_closure, _function_set_dict, _object_check_access,
                _object_declare_immutable, _object_owner_id):
    _internal.object_declare_synchronized(_helper)
del _helper, _internal, _capi

Shareable = threading.Shareable


class FunctionShareableTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_factory_cells_are_per_call(self):
        def factory():
            value = []
            def append(item):
                value.append(item)
                return tuple(value)
            return append

        self.assertTrue(factory.__code__.co_cellvars)
        self.assertFalse(factory.__code__.co_freevars)
        self.assertIs(factory.__shareable__, Shareable.SYNCHRONIZED)
        results = threading.Channel()
        barrier = threading.Barrier(4)
        def worker(number):
            first, second = factory(), factory()
            assert first.__shareable__ is threading.Shareable.SYNCHRONIZED
            assert second.__shareable__ is threading.Shareable.SYNCHRONIZED
            barrier.wait(SHORT_TIMEOUT)
            for _ in range(100):
                first(number)
            assert second(number) == (number,)
            results.put(first(number))
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        values = sorted(results.get() for _ in threads)
        self.assertEqual(values, [(number,) * 101 for number in range(4)])

    def test_plain_functions(self):
        def plain(arg=1, *, option=2):
            return arg + option

        def generator():
            yield 1

        async def coroutine():
            return 1

        async def async_generator():
            yield 1

        class C:
            def method(self):
                return 1

        for func in (plain, generator, coroutine, async_generator, C.method,
                     lambda: 1):
            with self.subTest(func=func):
                self.assertIs(func.__shareable__, Shareable.SYNCHRONIZED)
                func.extra = []
                self.assertEqual(func.extra, [])

    def test_new_function_namespaces(self):
        def plain():
            return 1
        def outer():
            value = 1
            return lambda: value
        for template in (plain, outer, outer()):
            for create_by_attribute in (False, True):
                with self.subTest(template=template, attribute=create_by_attribute):
                    func = types.FunctionType(template.__code__, globals(),
                                              closure=template.__closure__)
                    payload = []
                    owner = _object_owner_id(payload)
                    if create_by_attribute:
                        func.payload = payload
                    namespace = func.__dict__
                    expected = (SynchronizedDict
                                if func.__shareable__ is Shareable.SYNCHRONIZED
                                else dict)
                    self.assertIs(type(namespace), expected)
                    self.assertIs(namespace.__shareable__, func.__shareable__)
                    self.assertEqual(_object_owner_id(namespace),
                                     _object_owner_id(func))
                    self.assertIs(vars(func), namespace)
                    if not create_by_attribute:
                        namespace['payload'] = payload
                    self.assertIs(func.payload, payload)
                    self.assertEqual(_object_owner_id(payload), owner)
                    del func.payload
                    self.assertEqual(namespace, {})

    @threading_helper.requires_working_threading()
    def test_parallel_namespace_creation(self):
        for create_by_attribute in (False, True):
            with self.subTest(attribute=create_by_attribute):
                def func():
                    return 1
                barrier = threading.Barrier(4)
                results = threading.Channel()
                def worker(number, *, create_by_attribute=create_by_attribute,
                           func=func, barrier=barrier, results=results):
                    barrier.wait(timeout=SHORT_TIMEOUT)
                    if not create_by_attribute:
                        namespace = func.__dict__
                        _object_check_access(namespace)
                    for index in range(100):
                        setattr(func, f'key_{number}_{index}', index)
                    namespace = func.__dict__
                    _object_check_access(namespace)
                    results.put(namespace)
                threads = [threading.Thread(target=worker, args=(number,),
                                            group=threading.ThreadGroup())
                           for number in range(4)]
                with threading_helper.start_threads(threads):
                    pass
                for _ in threads:
                    self.assertIs(results.get(), func.__dict__)
                self.assertEqual(len(func.__dict__), 400)
                for number in range(4):
                    for index in range(100):
                        self.assertEqual(getattr(func, f'key_{number}_{index}'), index)

    @staticmethod
    def namespace_setters():
        return (lambda func, value: setattr(func, '__dict__', value),
                _function_set_dict)

    def test_replace_shared_namespace_preserves_aliases(self):
        class Record:
            pass
        for setter in self.namespace_setters():
            for split in (False, True):
                with self.subTest(setter=setter, split=split):
                    func = lambda: None
                    old = func.__dict__
                    old['old'] = 1
                    record = Record()
                    record.value = 42
                    payload = []
                    namespace = record.__dict__ if split else {'value': 42}
                    namespace['payload'] = payload
                    owner = _object_owner_id(payload)
                    setter(func, namespace)
                    self.assertIs(func.__dict__, namespace)
                    self.assertIs(type(namespace), SynchronizedDict)
                    self.assertEqual(_object_owner_id(namespace), 0)
                    self.assertEqual(func.value, 42)
                    self.assertIs(func.payload, payload)
                    self.assertEqual(_object_owner_id(payload), owner)
                    func.extra = 3
                    self.assertEqual(namespace['extra'], 3)
                    self.assertEqual(old, {'old': 1})
                    if split:
                        self.assertIs(record.__dict__, namespace)
                        self.assertEqual(record.extra, 3)
                        record.value = 43
                        self.assertEqual(func.value, 43)

    def test_replace_local_namespace(self):
        class DictSubclass(dict):
            pass
        value = 1
        for setter in self.namespace_setters():
            for container in (dict, DictSubclass, SynchronizedDict):
                def func():
                    nonlocal value
                    value += 0
                    return value
                self.assertIs(func.__shareable__, Shareable.LOCAL)
                namespace = container(a=1)
                setter(func, namespace)
                self.assertIs(func.__dict__, namespace)
                self.assertIs(type(namespace), container)

    def test_namespace_replacement_rejections(self):
        class DictSubclass(dict):
            pass
        for setter in self.namespace_setters():
            for namespace in (None, 42, frozendict(a=1), DictSubclass(a=1)):
                func = lambda: None
                original = func.__dict__
                with self.assertRaises(TypeError):
                    setter(func, namespace)
                self.assertIs(func.__dict__, original)
            func = lambda: None
            original = func.__dict__
            _object_declare_immutable(func)
            namespace = {}
            with self.assertRaises(TypeError):
                setter(func, namespace)
            self.assertIs(func.__dict__, original)
            self.assertIs(type(namespace), dict)

    @threading_helper.requires_working_threading()
    def test_namespace_replacement_ownership(self):
        value = 1
        def local():
            nonlocal value
            value += 0
            return value
        self.assertIs(local.__shareable__, Shareable.LOCAL)
        shared = lambda: None
        foreign_namespace = {}
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        mutate = capi.function_set_from_tuples
        internal.object_declare_synchronized(mutate)
        results = threading.Channel()
        def worker(local_holder, namespace_holder):
            denied = 0
            for native in (False, True):
                try:
                    mutate(local_holder, ({},), '__dict__', native)
                except IllegalThreadAccessException:
                    denied += 1
                try:
                    mutate((shared,), namespace_holder, '__dict__', native)
                except IllegalThreadAccessException:
                    denied += 1
                namespace = {'value': 42}
                mutate((shared,), (namespace,), '__dict__', native)
                assert shared.__dict__ is namespace
                assert type(namespace) is SynchronizedDict
            results.put(denied)
        thread = threading.Thread(target=worker,
                                  args=((local,), (foreign_namespace,)),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 4)
        self.assertEqual(shared.value, 42)
        self.assertEqual(foreign_namespace, {})
        self.assertIs(type(foreign_namespace), dict)
        self.assertEqual(local.__dict__, {})

    @threading_helper.requires_working_threading()
    def test_parallel_namespace_replacement(self):
        func = lambda: None
        func.value = 0
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            barrier.wait(timeout=SHORT_TIMEOUT)
            for index in range(200):
                if number % 2:
                    func.__dict__ = {'value': index}
                else:
                    assert 0 <= func.value < 200
                    assert type(func.__dict__) is SynchronizedDict
            results.put(True)
        threads = [threading.Thread(target=worker, args=(number,),
                                    group=threading.ThreadGroup())
                   for number in range(4)]
        with threading_helper.start_threads(threads):
            pass
        for _ in threads:
            self.assertTrue(results.get())

    def test_code_replacement_preserves_synchronized_namespace(self):
        class Record:
            pass
        def plain():
            return 42
        def outer():
            value = 1
            return lambda: value
        for split in (False, True):
            with self.subTest(split=split):
                func = types.FunctionType(outer.__code__, globals())
                record = Record()
                record.value = 3
                if split:
                    func.__dict__ = record.__dict__
                namespace = func.__dict__
                namespace['extra'] = 7
                self.assertIs(type(namespace), SynchronizedDict)
                with self.assertWarns(DeprecationWarning):
                    func.__code__ = plain.__code__
                self.assertIs(func.__shareable__, Shareable.SYNCHRONIZED)
                self.assertIs(func.__dict__, namespace)
                self.assertIs(type(namespace), SynchronizedDict)
                self.assertEqual(_object_owner_id(namespace), 0)
                self.assertEqual(func(), 42)
                self.assertEqual(func.extra, 7)
                if split:
                    self.assertIs(record.__dict__, namespace)
                    record.value = 4
                    self.assertEqual(func.value, 4)
                with self.assertWarns(DeprecationWarning):
                    func.__code__ = outer.__code__
                self.assertIs(func.__shareable__, Shareable.SYNCHRONIZED)
                self.assertIs(func.__dict__, namespace)
                self.assertIs(type(namespace), SynchronizedDict)

    def test_closure_transition_synchronizes_existing_namespace(self):
        for closure in (None, ()):
            with self.subTest(closure=closure):
                func = lambda: 42
                with self.assertWarns(DeprecationWarning):
                    _function_set_closure(func, (types.CellType(1),))
                self.assertIs(func.__shareable__, Shareable.LOCAL)
                namespace = func.__dict__
                namespace['extra'] = 7
                self.assertIs(type(namespace), dict)
                with self.assertWarns(DeprecationWarning):
                    _function_set_closure(func, closure)
                self.assertIs(func.__shareable__, Shareable.SYNCHRONIZED)
                self.assertIs(func.__dict__, namespace)
                self.assertIs(type(namespace), SynchronizedDict)
                self.assertEqual(func(), 42)
                self.assertEqual(func.extra, 7)

    def test_failed_namespace_conversion_preserves_execution_state(self):
        class DictSubclass(dict):
            pass
        def outer():
            value = 1
            return lambda: value
        for change_code in (False, True):
            func = (types.FunctionType(outer.__code__, globals())
                    if change_code else lambda: 42)
            with self.assertWarns(DeprecationWarning):
                _function_set_closure(func, (types.CellType(1),))
            namespace = DictSubclass(extra=7)
            func.__dict__ = namespace
            if change_code:
                original_code = func.__code__
                with self.assertRaises(ValueError):
                    func.__code__ = (lambda: 42).__code__
                self.assertIs(func.__code__, original_code)
                self.assertIs(func.__shareable__, Shareable.LOCAL)
            original_code, original_closure = func.__code__, func.__closure__
            with self.assertWarns(DeprecationWarning):
                with self.assertRaises(TypeError):
                    _function_set_closure(func, None)
            self.assertIs(func.__shareable__, Shareable.LOCAL)
            self.assertIs(func.__code__, original_code)
            self.assertIs(func.__closure__, original_closure)
            self.assertIs(func.__dict__, namespace)
            self.assertIs(type(namespace), DictSubclass)

    def test_function_constructor(self):
        def plain():
            return 42

        clone = types.FunctionType(plain.__code__, globals())
        self.assertIs(clone.__shareable__, Shareable.SYNCHRONIZED)
        self.assertEqual(_object_owner_id(clone), 0)
        self.assertEqual(clone(), 42)

    def test_mutable_closure_stays_local(self):
        def outer():
            value = 0
            def writer():
                nonlocal value
                value += 1
            def reader():
                return value
            return writer, reader

        writer, reader = outer()
        self.assertIs(outer.__shareable__, Shareable.LOCAL)
        for func in (writer, reader):
            self.assertIs(func.__shareable__, Shareable.LOCAL)
        writer()
        self.assertEqual(reader(), 1)

    def test_code_replacement_with_local_cells(self):
        def plain():
            return 42
        def outer():
            value = 0
            def writer():
                nonlocal value
                value += 1
            return writer

        original = plain.__code__
        with self.assertWarns(DeprecationWarning):
            plain.__code__ = outer.__code__
        self.assertIs(plain.__shareable__, Shareable.LOCAL)
        self.assertNotEqual(_object_owner_id(plain), 0)
        self.assertIs(plain().__shareable__, Shareable.LOCAL)
        with self.assertWarns(DeprecationWarning):
            plain.__code__ = original
        self.assertIs(plain.__shareable__, Shareable.SYNCHRONIZED)
        self.assertEqual(_object_owner_id(plain), 0)
        self.assertEqual(plain(), 42)

    def test_failed_replacement_preserves_state(self):
        def plain():
            return 42
        def outer():
            value = 0
            return lambda: value

        original = plain.__code__
        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)
            with self.assertRaises(DeprecationWarning):
                plain.__code__ = outer.__code__
        self.assertIs(plain.__code__, original)
        self.assertIs(plain.__shareable__, Shareable.SYNCHRONIZED)

    def test_capi_closure_replacement(self):
        def plain():
            return 42

        # The C API allows attaching an unused closure to closure-free code.
        with self.assertWarns(DeprecationWarning):
            _function_set_closure(plain, (types.CellType(1),))
        self.assertIs(plain.__shareable__, Shareable.LOCAL)
        with self.assertWarns(DeprecationWarning):
            _function_set_closure(plain, None)
        self.assertIs(plain.__shareable__, Shareable.SYNCHRONIZED)

    @threading_helper.requires_working_threading()
    def test_cross_group_access_check(self):
        def plain():
            return 42

        results = threading.Channel()
        def worker():
            func = _object_check_access(plain)
            results.put(func())

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 42)

    def test_transfer_preserves_identity(self):
        def plain():
            return 42

        self.assertIs(threading.TransferBox(plain).claim(), plain)

    @threading_helper.requires_working_threading()
    def test_capi_getters_check_returned_references(self):
        class Payload:
            pass

        payload = Payload()
        namespace = {'__name__': 'getter_test'}
        def plain(arg=1, *, option=2):
            return arg + option

        func = types.FunctionType(plain.__code__, namespace,
                                  argdefs=(1,), kwdefaults={'option': 2})
        func.__module__ = payload
        annotations = {'arg': int}
        func.__annotations__ = annotations
        results = threading.Channel()
        def worker():
            denied = 0
            for getter in (_function_get_globals, _function_get_module,
                           _function_get_annotations):
                for _ in range(20):
                    try:
                        getter(func)
                    except IllegalThreadAccessException:
                        denied += 1
            results.put((denied,
                         _function_get_code(func) is plain.__code__,
                         _function_get_defaults(func) == (1,),
                         _function_get_kw_defaults(func) == {'option': 2},
                         _function_get_closure(func) is None))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), (60, True, True, True, True))
        # Denying a borrowed reference must not release the function's value.
        self.assertIs(_function_get_globals(func), namespace)
        self.assertIs(_function_get_module(func), payload)
        self.assertIs(_function_get_annotations(func), annotations)

    @threading_helper.requires_working_threading()
    def test_capi_getters_allow_shared_values(self):
        def plain():
            return answer

        namespace = freeze({'__name__': 'frozen_getter_test', 'answer': 42})
        func = types.FunctionType(plain.__code__, namespace)
        results = threading.Channel()
        def worker():
            results.put((_function_get_globals(func) is namespace,
                         _function_get_module(func) == 'frozen_getter_test',
                         _function_get_defaults(func) is None,
                         _function_get_kw_defaults(func) is None))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), (True, True, True, True))
        self.assertEqual(func(), 42)

    def test_capi_annotation_error_preserved(self):
        def plain():
            return 42
        def annotate(format):
            raise ValueError('annotation failure')
        plain.__annotate__ = annotate
        with self.assertRaisesRegex(ValueError, 'annotation failure'):
            _function_get_annotations(plain)


if __name__ == '__main__':
    unittest.main()
