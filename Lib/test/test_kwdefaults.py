"""Immutable keyword-only defaults required by PEP 805."""

import types
import unittest
import weakref

from test.support import gc_collect, nomemtest
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


class KwDefaultsTests(unittest.TestCase):
    def test_definition_and_shallow_values(self):
        child = []

        def func(*, value=child):
            return value

        self.assertIs(type(func.__kwdefaults__), frozendict)
        self.assertIs(func(), child)
        child.append(1)
        self.assertEqual(func(), [1])
        with self.assertRaises(TypeError):
            func.__kwdefaults__['value'] = 2
        with self.assertRaises(TypeError):
            del func.__kwdefaults__['value']

    def test_snapshot_and_reassignment(self):
        def func(*, value=1):
            return value

        source = {'value': 2}
        func.__kwdefaults__ = source
        old = func.__kwdefaults__
        source['value'] = 3
        for _ in range(100):
            self.assertEqual(func(), 2)
        func.__kwdefaults__ = frozendict(value=4)
        for _ in range(100):
            self.assertEqual(func(), 4)
        self.assertEqual(old, {'value': 2})
        self.assertIs(type(old), frozendict)
        del func.__kwdefaults__
        with self.assertRaises(TypeError):
            func()

    def test_constructor(self):
        def template(*, value):
            return value

        for source in ({'value': 42}, frozendict(value=42)):
            with self.subTest(type=type(source)):
                func = types.FunctionType(template.__code__, globals(),
                                          kwdefaults=source)
                self.assertIs(type(func.__kwdefaults__), frozendict)
                self.assertEqual(func(), 42)
                if isinstance(source, dict):
                    source.clear()
                    self.assertEqual(func(), 42)

    def test_dictionary_subclass_hooks_not_called(self):
        def func(*, value):
            return value

        for base in (dict, frozendict):
            with self.subTest(base=base):
                class Dict(base):
                    def keys(self):
                        raise AssertionError('keys called')

                    def __iter__(self):
                        raise AssertionError('iter called')

                    def __getitem__(self, key):
                        raise AssertionError('getitem called')

                source = Dict(value=42)
                func.__kwdefaults__ = source
                self.assertEqual(func(), 42)
                clone = types.FunctionType(func.__code__, globals(),
                                           kwdefaults=source)
                if base is dict:
                    source.clear()
                self.assertIs(type(clone.__kwdefaults__), frozendict)
                self.assertEqual(clone(), 42)
                self.assertEqual(func(), 42)

    def test_capi_setter(self):
        capi = import_module('_testcapi')

        def func(*, value):
            return value

        source = {'value': 42}
        capi.function_set_kw_defaults(func, source)
        self.assertIs(type(capi.function_get_kw_defaults(func)), frozendict)
        source.clear()
        self.assertEqual(func(), 42)
        capi.function_set_kw_defaults(func, frozendict(value=43))
        self.assertEqual(func(), 43)
        capi.function_set_kw_defaults(func, None)
        self.assertIsNone(func.__kwdefaults__)

    def test_cycle_is_collected(self):
        def func(*, value=None):
            pass

        func.__kwdefaults__ = {'value': func}
        ref = weakref.ref(func)
        del func
        gc_collect()
        self.assertIsNone(ref())

    def test_eval_code_ex(self):
        capi = import_module('_testcapi')

        def template(*, value):
            return value

        for defaults in ({'value': 42}, frozendict(value=42)):
            self.assertEqual(capi.eval_code_ex(template.__code__, {}, {},
                                               (), {}, (), defaults), 42)

    @nomemtest
    def test_creation_allocation_failure(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi
            import gc
            import types
            import weakref

            class Payload:
                pass

            def factory(value):
                def func(*, option=value):
                    return option
                return func

            def constructor(value):
                return types.FunctionType(factory(None).__code__, globals(),
                                          kwdefaults={'option': value})

            failures = 0
            for make in (factory, constructor):
                for start in range(40):
                    value = Payload()
                    ref = weakref.ref(value)
                    result = None
                    _testcapi.set_nomemory(start, start + 1)
                    try:
                        result = make(value)
                    except MemoryError:
                        failures += 1
                    finally:
                        _testcapi.remove_mem_hooks()
                    if result is not None:
                        assert type(result.__kwdefaults__) is frozendict
                        assert result() is value
                    del result, value
                    gc.collect()
                    assert ref() is None
            assert failures > 0
        ''')

    @nomemtest
    def test_allocation_failure_preserves_defaults(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi

            def func(*, value=1):
                return value

            failures = 0
            for setter in (lambda f, d: setattr(f, '__kwdefaults__', d),
                           _testcapi.function_set_kw_defaults):
                for start in range(20):
                    func.__kwdefaults__ = {'value': 1}
                    original = func.__kwdefaults__
                    replacement = {'value': 2}
                    failed = False
                    _testcapi.set_nomemory(start, start + 1)
                    try:
                        setter(func, replacement)
                    except MemoryError:
                        failed = True
                    finally:
                        _testcapi.remove_mem_hooks()
                    if failed:
                        failures += 1
                        assert func.__kwdefaults__ is original
                        assert func() == 1
                    else:
                        assert func() == 2
                    assert replacement == {'value': 2}
            assert failures > 0
        ''')


if __name__ == '__main__':
    unittest.main()
