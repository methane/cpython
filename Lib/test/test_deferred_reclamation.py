"""Deferred counting is restricted to IMMUTABLE objects in the PEP 805 base."""

import gc
import unittest
import weakref

from test import support
from test.support import import_helper
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

    def test_shutdown_restores_ordinary_counting(self):
        assert_python_ok('-c', 'import gc\nimport _testinternalcapi\ngc.disable()\n_testinternalcapi.check_deferred_shutdown()\n')

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
