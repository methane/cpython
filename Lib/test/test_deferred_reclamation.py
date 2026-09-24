"""Deferred counting is restricted to IMMUTABLE objects in the PEP 805 base."""

import gc
import sys
import threading
import types
import unittest
import weakref

from test import support
from test.support import import_helper, threading_helper
from test.support.script_helper import assert_python_ok

_testcapi = import_helper.import_module('_testcapi')
internal = import_helper.import_module('_testinternalcapi')


class DeferredReclamationTests(unittest.TestCase):
    @staticmethod
    def containers(value):
        return ((value,), frozenset((value,)), frozendict({0: value}))

    def test_acyclic_container(self):
        for index in range(3):
            with self.subTest(container=index), support.disable_gc():
                events = []

                class Value:
                    def __del__(self):
                        events.append('finalized')

                value = Value()
                reference = weakref.ref(value)
                container = self.containers(value)[index]
                self.assertEqual(
                    _testcapi.pyobject_enable_deferred_refcount(container), 1)
                self.assertTrue(internal.has_deferred_refcount(container))
                del value, container
                self.assertIsNotNone(reference())
                self.assertEqual(events, [])
                gc.collect()
                self.assertIsNone(reference())
                self.assertEqual(events, ['finalized'])

    def test_cycle_and_resurrection(self):
        for index in range(3):
            for resurrect in (False, True):
                with self.subTest(container=index, resurrect=resurrect):
                    self.check_cycle(index, resurrect)

    def check_cycle(self, index, resurrect):
        with support.disable_gc():
            events = []
            survivors = []

            class Value:
                def __del__(self):
                    events.append('finalized')
                    if resurrect:
                        survivors.append(self)

            value = Value()
            container = self.containers(value)[index]
            value.container = container
            reference = weakref.ref(value, lambda ref: events.append('weakref'))
            self.assertEqual(
                _testcapi.pyobject_enable_deferred_refcount(container), 1)
            del value, container
            gc.collect()
            self.assertIsNone(reference())
            self.assertEqual(events, ['weakref', 'finalized'])
            if resurrect:
                value, = survivors
                container = value.container
                self.assertIn(value, (container[0],) if index == 2 else container)
                reference = weakref.ref(value)
                del value, container
                survivors.clear()
                gc.collect()
                self.assertIsNone(reference())
                self.assertEqual(events, ['weakref', 'finalized'])

    def test_shared_child_survives_collection(self):
        with support.disable_gc():
            class Value:
                pass

            value = Value()
            reference = weakref.ref(value)
            container = (value,)
            self.assertEqual(
                _testcapi.pyobject_enable_deferred_refcount(container), 1)
            del container
            gc.collect()
            self.assertIs(reference(), value)
            del value
            self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_code_counts_survive_thread_exit(self):
        with support.disable_gc():
            functions = []
            references = []

            def publish():
                for index in range(40):
                    outer = compile('def f(): return 42', f'rc-{index}', 'exec')
                    code, = (c for c in outer.co_consts if isinstance(c, types.CodeType))
                    functions.append(types.FunctionType(code, {}))
                    references.append(weakref.ref(code))

            thread = threading.Thread(target=publish, group=sys.main_thread_group)
            thread.start()
            thread.join()
            gc.collect()
            self.assertEqual(len(functions), 40)
            self.assertTrue(all(ref() is not None for ref in references))
            self.assertTrue(all(function() == 42 for function in functions))
            functions.clear()
            gc.collect()
            self.assertTrue(all(ref() is None for ref in references))

    def test_code_cycle_resurrection(self):
        with support.disable_gc():
            events = []
            survivors = []

            class Value:
                def __del__(self):
                    events.append('finalized')
                    survivors.append(self.code)

            value = Value()
            code = compile('pass', 'code-cycle', 'exec').replace(co_consts=(value,))
            value.code = code
            self.assertTrue(gc.is_tracked(code))
            self.assertTrue(internal.has_deferred_refcount(code))
            reference = weakref.ref(code)
            del value, code
            gc.collect()
            code, = survivors
            self.assertIs(reference(), code)
            function = types.FunctionType(code, {})
            survivors.clear()
            del code
            gc.collect()
            self.assertIs(reference(), function.__code__)
            del function
            gc.collect()
            self.assertIsNone(reference())
            self.assertEqual(events, ['finalized'])

    def test_shutdown_restores_ordinary_counting(self):
        assert_python_ok('-c', 'import gc\nimport _testinternalcapi\ngc.disable()\n_testinternalcapi.check_deferred_shutdown()\n')

    def test_c_stack_reference(self):
        internal.test_deferred_c_stack_ref()

    def test_generator_holds_deferred_reference(self):
        for frozen in (False, True):
            with self.subTest(frozen=frozen), support.disable_gc():
                class Value:
                    pass

                namespace = {}
                exec('def gen():\n'
                     '    yield\n'
                     '    value = container\n'
                     '    yield\n'
                     '    yield value\n', namespace)
                gen = namespace['gen']()
                next(gen)
                gc.collect()  # Promote the generator before creating its value.
                if frozen:
                    gc.freeze()
                try:
                    value = Value()
                    reference = weakref.ref(value)
                    container = (value,)
                    self.assertEqual(
                        _testcapi.pyobject_enable_deferred_refcount(container), 1)
                    namespace['container'] = container
                    next(gen)
                    del namespace['container'], container, value
                    gc.collect(0)
                    self.assertIsNotNone(reference())
                    gc.collect()
                    self.assertIsNotNone(reference())
                    self.assertIs(next(gen)[0], reference())
                finally:
                    if frozen:
                        gc.unfreeze()
                    gen.close()
                gc.collect()
                self.assertIsNone(reference())

    def test_generator_resurrection(self):
        with support.disable_gc():
            survivors = []

            class Value:
                def __del__(self):
                    survivors.append(self.gen)

            namespace = {}
            exec('def gen():\n'
                 '    value = container\n'
                 '    yield\n'
                 '    yield value\n', namespace)
            gen = namespace['gen']()
            value = Value()
            value.gen = gen
            container = (value,)
            self.assertEqual(
                _testcapi.pyobject_enable_deferred_refcount(container), 1)
            namespace['container'] = container
            next(gen)
            del namespace['container'], container, value, gen
            gc.collect()
            gen, = survivors
            # Generator finalization may close the frame before resurrection.
            self.assertIsNotNone(gen.gi_code)
            gen.close()
            survivors.clear()
            del gen
            gc.collect()

    def test_local_objects_are_not_deferred(self):
        class Value:
            pass

        for value in ([], {}, set(), Value(), Value, lambda: None):
            with self.subTest(type=type(value)):
                self.assertEqual(
                    _testcapi.pyobject_enable_deferred_refcount(value), 0)
                self.assertFalse(internal.has_deferred_refcount(value))


if __name__ == '__main__':
    unittest.main()
