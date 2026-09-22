"""Module freezing preserves namespace aliases and lazy annotations."""

import gc
import importlib
import pathlib
import sys
import tempfile
import threading
import types
import unittest
import weakref

from test import support
from test.support import import_helper, threading_helper
from test.support.script_helper import assert_python_ok


class FreezeModuleTests(unittest.TestCase):
    def test_identity_and_namespace(self):
        module = types.ModuleType('frozen_example')
        namespace = module.__dict__
        module.answer = 42
        ref = weakref.ref(module)
        method = module.__freeze__
        self.assertIs(method(), module)
        self.assertIs(freeze(module), module)
        self.assertIs(method(), module)
        self.assertIs(ref(), module)
        self.assertIs(module.__module__, module)
        self.assertIs(module.__dict__, namespace)
        self.assertIs(type(namespace), frozendict)
        self.assertIs(module.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIn('answer', dir(module))
        self.assertIn('frozen_example', repr(module))

    def test_freeze_at_end_of_module(self):
        module = types.ModuleType('frozen_script')
        namespace = module.__dict__
        exec('answer = 42\n'
             'values = []\n'
             'def read(): return answer\n'
             'def write():\n global answer\n answer = 43\n'
             'freeze(__module__)\n', namespace)
        self.assertIs(module.read.__globals__, namespace)
        self.assertIs(type(namespace), frozendict)
        for _ in range(200):
            self.assertEqual(module.read(), 42)
        with self.assertRaises(TypeError):
            module.write()
        module.values.append(1)
        self.assertEqual(module.values, [1])

    def test_import_frozen_module(self):
        name = 'pep805_frozen_module_test'
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, name + '.py').write_text(
                'answer: int = 42\n'
                'def read(): return answer\n'
                'freeze(__module__)\n', encoding='utf-8')
            with import_helper.DirsOnSysPath(directory):
                try:
                    module = importlib.import_module(name)
                    self.assertEqual(module.read(), 42)
                    self.assertIs(module.__shareable__, threading.Shareable.IMMUTABLE)
                    self.assertEqual(module.__annotations__, {'answer': int})
                finally:
                    sys.modules.pop(name, None)

    def test_declared_immutable_extension(self):
        import_helper.import_module('_testinternalcapi')
        import_helper.import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi
            import _testinternalcapi
            _testinternalcapi.object_declare_immutable(_testcapi)
            assert freeze(_testcapi) is _testcapi
        ''')

    def test_saved_mutators(self):
        module = types.ModuleType('original')
        module.answer = 42
        namespace = module.__dict__
        setter, deleter, initializer = module.__setattr__, module.__delattr__, module.__init__
        freeze(module)
        class Submodule(types.ModuleType):
            pass
        operations = (
            lambda: setattr(module, 'answer', 43),
            lambda: setattr(module, 'new', 1),
            lambda: delattr(module, 'answer'),
            lambda: setter('answer', 43),
            lambda: deleter('answer'),
            lambda: initializer('changed'),
            lambda: setattr(module, '__class__', Submodule),
            lambda: namespace.__setitem__('answer', 43),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, AttributeError)):
                    operation()
        self.assertEqual(module.__name__, 'original')
        self.assertEqual(module.answer, 42)

    def test_lazy_annotations(self):
        module = types.ModuleType('annotated')
        calls = []

        def annotate(format):
            calls.append(format)
            return {'self': module}

        module.__annotate__ = annotate
        freeze(module)
        self.assertEqual(calls, [])
        result = module.__annotations__
        self.assertIs(result['self'], module)
        self.assertIs(module.__annotations__, result)
        self.assertEqual(calls, [1])
        with self.assertRaises(TypeError):
            module.__annotations__ = {}
        with self.assertRaises(TypeError):
            module.__annotate__ = None

    def test_annotation_error_retry(self):
        module = types.ModuleType('annotation_error')
        calls = []

        def annotate(format):
            calls.append(format)
            if len(calls) == 1:
                raise ValueError('try again')
            return {'x': int}

        module.__annotate__ = annotate
        freeze(module)
        with self.assertRaisesRegex(ValueError, 'try again'):
            module.__annotations__
        self.assertEqual(module.__annotations__, {'x': int})
        self.assertEqual(calls, [1, 1])

    def test_freeze_during_annotation_evaluation(self):
        module = types.ModuleType('freeze_during_annotation')

        def annotate(format):
            freeze(module)
            return {'x': int}

        module.__annotate__ = annotate
        result = module.__annotations__
        self.assertEqual(result, {'x': int})
        self.assertIs(module.__annotations__, result)
        self.assertIs(type(module.__dict__), frozendict)

    def test_annotations_during_initialization(self):
        module = types.ModuleType('initializing_annotations')
        spec = importlib.machinery.ModuleSpec(module.__name__, loader=None)
        spec._initializing = True
        module.__spec__ = spec
        calls = []

        def annotate(format):
            calls.append(format)
            return {'x': len(calls)}

        module.__annotate__ = annotate
        freeze(module)
        self.assertEqual(module.__annotations__, {'x': 1})
        spec._initializing = False
        result = module.__annotations__
        self.assertEqual(result, {'x': 2})
        self.assertIs(module.__annotations__, result)

    def test_namespace_watcher(self):
        capi = import_helper.import_module('_testcapi')
        module = types.ModuleType('watched_namespace')
        watcher = capi.add_dict_watcher(0)
        try:
            capi.watch_dict(watcher, module.__dict__)
            self.assertIs(freeze(module), module)
            self.assertIs(freeze(module), module)
            self.assertEqual(capi.get_dict_watcher_events(), ['freeze'])
        finally:
            capi.unwatch_dict(watcher, module.__dict__)
            capi.clear_dict_watcher(watcher)

    def test_empty_annotations(self):
        module = types.ModuleType('empty_annotations')
        freeze(module)
        original_keys = list(module.__dict__)
        self.assertIsNone(module.__annotate__)
        result = module.__annotations__
        self.assertEqual(result, {})
        self.assertIs(module.__annotations__, result)
        self.assertEqual(list(module.__dict__), original_keys)

    def test_preexisting_annotations(self):
        module = types.ModuleType('existing_annotations')
        annotations = {'x': int}
        module.__annotations__ = annotations
        freeze(module)
        self.assertIs(module.__annotations__, annotations)
        annotations['y'] = str
        self.assertEqual(module.__annotations__, {'x': int, 'y': str})

    def test_frozen_namespace(self):
        module = types.ModuleType('frozen_namespace')
        namespace = freeze(module.__dict__)
        self.assertIs(freeze(module).__dict__, namespace)

    def test_unsupported_modules(self):
        capi = import_helper.import_module('_testcapi')
        class Submodule(types.ModuleType):
            pass
        for module in (capi, sys, Submodule('submodule')):
            with self.subTest(module=module):
                original = module.__shareable__
                with self.assertRaisesRegex(TypeError, 'cannot freeze'):
                    freeze(module)
                self.assertIs(module.__shareable__, original)

    def test_gc_with_annotation_cache(self):
        module = types.ModuleType('annotation_cycle')
        exec('self: __module__\n', module.__dict__)
        freeze(module)
        self.assertIs(module.__annotations__['self'], module)
        ref = weakref.ref(module)
        module_id = id(module)
        del module
        support.gc_collect()
        self.assertIsNone(ref())
        self.assertFalse(any(id(obj) == module_id for obj in gc.get_objects()))

    @threading_helper.requires_working_threading()
    def test_foreign_freeze_rejected(self):
        module = types.ModuleType('local_module')
        results = threading.Channel()

        def worker():
            try:
                freeze(module)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(module.__shareable__, threading.Shareable.LOCAL)


if __name__ == '__main__':
    unittest.main()
