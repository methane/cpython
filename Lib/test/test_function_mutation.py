"""PEP 805 deprecations for changes to function execution attributes."""

import threading
import types
import unittest
import warnings

from test.support import swap_attr, threading_helper
from test.support.import_helper import import_module


class FunctionMutationTests(unittest.TestCase):
    def test_attribute_assignment(self):
        def func(value=1, *, option=2):
            return value, option

        def other(value=1, *, option=2):
            return option, value

        for name, value in (('__defaults__', (3,)),
                            ('__kwdefaults__', {'option': 4}),
                            ('__code__', other.__code__)):
            with self.subTest(name=name):
                with self.assertWarnsRegex(DeprecationWarning, name) as caught:
                    setattr(func, name, value)
                self.assertEqual(caught.filename, __file__)
        self.assertEqual(func(), (4, 3))

    def test_warning_as_error_preserves_attributes(self):
        def func(value=1, *, option=2):
            return value, option

        def other(value=1, *, option=2):
            return option, value

        for name, value in (('__defaults__', (3,)),
                            ('__kwdefaults__', {'option': 4}),
                            ('__code__', other.__code__)):
            with self.subTest(name=name), warnings.catch_warnings():
                original = getattr(func, name)
                warnings.simplefilter('error', DeprecationWarning)
                with self.assertRaisesRegex(DeprecationWarning, name):
                    setattr(func, name, value)
                self.assertIs(getattr(func, name), original)
                self.assertEqual(func(), (1, 2))

    def test_deleting_defaults(self):
        for name in ('__defaults__', '__kwdefaults__'):
            def func(value=1, *, option=2):
                return value, option

            original = getattr(func, name)
            with warnings.catch_warnings():
                warnings.simplefilter('error', DeprecationWarning)
                with self.assertRaises(DeprecationWarning):
                    delattr(func, name)
            self.assertIs(getattr(func, name), original)
            with self.assertWarnsRegex(DeprecationWarning, name):
                delattr(func, name)
            self.assertIsNone(getattr(func, name))

    def test_invalid_assignment_keeps_type_errors(self):
        def func(value=1, *, option=2):
            pass

        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)
            for name in ('__defaults__', '__kwdefaults__', '__code__'):
                with self.subTest(name=name), self.assertRaises(TypeError):
                    setattr(func, name, 42)

    def test_construction_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)

            def func(value=1, *, option=2):
                return value, option

            clone = types.FunctionType(func.__code__, globals(),
                                       argdefs=(3,), kwdefaults={'option': 4})
            self.assertEqual(func(), (1, 2))
            self.assertEqual(clone(), (3, 4))

    def test_namedtuple_defaults_do_not_warn(self):
        from collections import namedtuple

        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)
            Point = namedtuple('Point', ('x', 'y'), defaults=(2,))
            self.assertEqual(Point(1), (1, 2))
            self.assertEqual(Point.__new__.__defaults__, (2,))

    def test_coroutine_decorator_preserves_identity_without_warning(self):
        def generator():
            yield 1

        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)
            self.assertIs(types.coroutine(generator), generator)
            self.assertTrue(generator.__code__.co_flags & 0x100)
            # Suppression is confined to the decorator's internal update.
            with self.assertRaises(DeprecationWarning):
                generator.__code__ = generator.__code__

    def test_capi_setters(self):
        capi = import_module('_testcapi')
        cell = types.CellType(10)

        def factory(value):
            def func(arg=1, *, option=2):
                return arg, option, value
            return func

        for name, setter, value in (
            ('__defaults__', capi.function_set_defaults, (3,)),
            ('__kwdefaults__', capi.function_set_kw_defaults, {'option': 4}),
            ('__closure__', capi.function_set_closure, (cell,)),
        ):
            with self.subTest(name=name):
                func = factory(5)
                original = getattr(func, name)
                with warnings.catch_warnings():
                    warnings.simplefilter('error', DeprecationWarning)
                    with self.assertRaisesRegex(DeprecationWarning, name):
                        setter(func, value)
                self.assertIs(getattr(func, name), original)
                self.assertEqual(func(), (1, 2, 5))
                with self.assertWarnsRegex(DeprecationWarning, name) as caught:
                    setter(func, value)
                self.assertEqual(caught.filename, __file__)
                self.assertEqual(getattr(func, name), value)


class FunctionMutationAccessTests(unittest.TestCase):
    @staticmethod
    def make_function():
        value = 10
        def func(arg=1, *, option=2):
            nonlocal value
            value += 0
            return value, arg, option
        return func

    @staticmethod
    def setters():
        capi = import_module('_testcapi')
        return (
            ('__defaults__', lambda f, v: setattr(f, '__defaults__', v), (3,)),
            ('__kwdefaults__', lambda f, v: setattr(f, '__kwdefaults__', v), {'option': 4}),
            ('__code__', lambda f, v: setattr(f, '__code__', v),
             FunctionMutationAccessTests.make_function().__code__),
            ('__defaults__', capi.function_set_defaults, (3,)),
            ('__kwdefaults__', capi.function_set_kw_defaults, {'option': 4}),
            ('__closure__', capi.function_set_closure, (types.CellType(20),)),
        )

    def test_immutable_function_rejects_execution_changes(self):
        internal = import_module('_testinternalcapi')
        for name, setter, value in self.setters():
            with self.subTest(name=name, setter=setter):
                func = self.make_function()
                original = getattr(func, name)
                internal.object_declare_immutable(func)
                with self.assertRaises(TypeError):
                    setter(func, value)
                self.assertIs(getattr(func, name), original)
                self.assertEqual(func(), (10, 1, 2))

    @threading_helper.requires_working_threading()
    def test_foreign_local_function_rejects_execution_changes(self):
        func = self.make_function()
        setters = self.setters()
        originals = {name: getattr(func, name) for name, _, _ in setters}
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        mutate = capi.function_set_from_tuples
        internal.object_declare_synchronized(mutate)
        results = threading.Channel()
        # Native acquisition ensures rejection happens at the setter API.
        def worker(receiver, value_holder, name, native):
            try:
                mutate(receiver, value_holder, name, native)
            except IllegalThreadAccessException:
                results.put(1)
            else:
                results.put(0)

        threads = []
        for name, setter, value in setters:
            native = isinstance(setter, types.BuiltinFunctionType)
            threads.append(threading.Thread(target=worker,
                           args=((func,), (value,), name, native),
                           group=threading.ThreadGroup()))
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(sum(results.get() for _ in threads), len(setters))
        for name, original in originals.items():
            self.assertIs(getattr(func, name), original)
        self.assertEqual(func(), (10, 1, 2))

    def test_warning_callback_changes_closure_shape(self):
        capi = import_module('_testcapi')
        func = lambda: 1
        original_code = func.__code__
        def showwarning(*args, **kwargs):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                capi.function_set_closure(func, (types.CellType(1),))
        with warnings.catch_warnings():
            warnings.simplefilter('always', DeprecationWarning)
            with swap_attr(warnings, 'showwarning', showwarning):
                with self.assertRaisesRegex(ValueError, 'free vars'):
                    func.__code__ = (lambda: 2).__code__
        self.assertIs(func.__code__, original_code)
        self.assertEqual(len(func.__closure__), 1)

    def test_warning_callback_changes_state(self):
        internal = import_module('_testinternalcapi')
        for name, setter, value in self.setters():
            with self.subTest(name=name, setter=setter):
                func = self.make_function()
                original = getattr(func, name)
                def showwarning(*args, **kwargs):
                    internal.object_declare_immutable(func)
                with warnings.catch_warnings():
                    warnings.simplefilter('always', DeprecationWarning)
                    with swap_attr(warnings, 'showwarning', showwarning):
                        with self.assertRaises(TypeError):
                            setter(func, value)
                self.assertIs(getattr(func, name), original)
                self.assertEqual(func(), (10, 1, 2))

    def test_watcher_changes_state(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        for name, setter, value in self.setters():
            if name == '__closure__':
                continue  # The existing watcher API has no closure event.
            with self.subTest(name=name, setter=setter):
                func = self.make_function()
                original = getattr(func, name)
                def watcher(event, target, new_value):
                    if target is func and event in (
                        capi.PYFUNC_EVENT_MODIFY_CODE,
                        capi.PYFUNC_EVENT_MODIFY_DEFAULTS,
                        capi.PYFUNC_EVENT_MODIFY_KWDEFAULTS,
                    ):
                        internal.object_declare_immutable(target)
                wid = capi.add_func_watcher(watcher)
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', DeprecationWarning)
                        with self.assertRaises(TypeError):
                            setter(func, value)
                finally:
                    capi.clear_func_watcher(wid)
                self.assertIs(getattr(func, name), original)
                self.assertEqual(func(), (10, 1, 2))


class FunctionMetadataMutationTests(unittest.TestCase):
    @staticmethod
    def setters():
        capi = import_module('_testcapi')
        pairs = [('__name__', 'new_name'), ('__qualname__', 'new_qualname'),
                 ('__doc__', 'new doc'), ('__module__', 'new_module'),
                 ('__annotations__', {'x': int}),
                 ('__annotate__', lambda format: {}),
                 ('__type_params__', (int,))]
        return [(name, lambda f, v, name=name: setattr(f, name, v), value)
                for name, value in pairs] + [
                    ('__annotations__', capi.function_set_annotations, {'x': str})]

    def test_immutable_rejects_metadata_changes(self):
        internal = import_module('_testinternalcapi')
        for name, setter, value in self.setters():
            with self.subTest(name=name, setter=setter):
                func = FunctionMutationAccessTests.make_function()
                original = getattr(func, name)
                internal.object_declare_immutable(func)
                with self.assertRaises(TypeError):
                    setter(func, value)
                self.assertIs(getattr(func, name), original)
                with self.assertRaises(TypeError):
                    delattr(func, name)
                self.assertIs(getattr(func, name), original)

    @threading_helper.requires_working_threading()
    def test_foreign_local_rejects_metadata_changes(self):
        func = FunctionMutationAccessTests.make_function()
        setters = self.setters()
        originals = {name: getattr(func, name) for name, _, _ in setters}
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        mutate = capi.function_set_from_tuples
        internal.object_declare_synchronized(mutate)
        results = threading.Channel()
        # Native acquisition ensures rejection happens at the setter API.
        def worker(receiver, value_holder, name, native):
            try:
                mutate(receiver, value_holder, name, native)
            except IllegalThreadAccessException:
                results.put(1)
            else:
                results.put(0)
        threads = []
        for name, setter, value in setters:
            native = isinstance(setter, types.BuiltinFunctionType)
            threads.append(threading.Thread(target=worker,
                           args=((func,), (value,), name, native),
                           group=threading.ThreadGroup()))
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(sum(results.get() for _ in threads), len(setters))
        for name, original in originals.items():
            self.assertIs(getattr(func, name), original)

    def test_allowed_metadata_changes_do_not_warn(self):
        for name, setter, value in self.setters():
            for func in (FunctionMutationAccessTests.make_function(), lambda: None):
                with self.subTest(name=name, state=func.__shareable__):
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', DeprecationWarning)
                        setter(func, value)
                    self.assertIs(getattr(func, name), value)

    def test_qualname_watcher_freezes_function(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        func = FunctionMutationAccessTests.make_function()
        original = func.__qualname__
        def watcher(event, target, new_value):
            if target is func and event == capi.PYFUNC_EVENT_MODIFY_QUALNAME:
                internal.object_declare_immutable(target)
        wid = capi.add_func_watcher(watcher)
        try:
            with self.assertRaises(TypeError):
                func.__qualname__ = 'new'
        finally:
            capi.clear_func_watcher(wid)
        self.assertEqual(func.__qualname__, original)

    def test_annotation_replacement_publishes_before_finalizers(self):
        internal = import_module('_testinternalcapi')
        for attribute in ('__annotations__', '__annotate__'):
            with self.subTest(attribute=attribute):
                func = lambda: None
                observed = []
                replacement = ({} if attribute == '__annotations__'
                               else lambda format: {})
                class Annotator:
                    def __call__(self, format):
                        return {}
                    def __del__(self):
                        observed.append((func.__annotate__, func.__annotations__))
                        internal.object_declare_immutable(func)
                func.__annotate__ = Annotator()
                setattr(func, attribute, replacement)
                self.assertEqual(len(observed), 1)
                if attribute == '__annotations__':
                    self.assertEqual(observed[0], (None, replacement))
                else:
                    self.assertIs(observed[0][0], replacement)
                self.assertIs(func.__shareable__, threading.Shareable.IMMUTABLE)

    def test_annotation_dict_finalizer_sees_cleared_annotator(self):
        func = lambda: None
        observed = []
        class Annotations(dict):
            def __del__(self):
                observed.append(func.__annotate__)
        func.__annotate__ = lambda format: Annotations()
        self.assertIsInstance(func.__annotations__, Annotations)
        func.__annotations__ = {}
        self.assertEqual(observed, [None])

    def test_c_annotations_validation_and_clear(self):
        capi = import_module('_testcapi')
        func = lambda: None
        annotations = {'x': int}
        capi.function_set_annotations(func, annotations)
        self.assertIs(func.__annotations__, annotations)
        with self.assertRaises(SystemError):
            capi.function_set_annotations(func, ())
        self.assertIs(func.__annotations__, annotations)
        capi.function_set_annotations(func, None)
        self.assertEqual(func.__annotations__, {})


if __name__ == '__main__':
    unittest.main()
