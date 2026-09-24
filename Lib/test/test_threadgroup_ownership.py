"""LOCAL/IMMUTABLE reference acquisition from native ThreadGroup workers."""

import datetime
import sys
import threading
import unittest

from test.support import import_helper, threading_helper

internal = import_helper.import_module('_testinternalcapi')
threading_helper.requires_working_threading(module=True)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.foreign = threading.ThreadGroup('ownership probe')

    def check_access(self, value, foreign_access):
        self.assertTrue(internal.threadgroup_access_probe(
            sys.main_thread_group, value))
        self.assertIs(internal.threadgroup_access_probe(self.foreign, value),
                      foreign_access)

    def test_local_values(self):
        class Value:
            def __repr__(self):
                raise AssertionError('access errors must not call repr')

        for value in ([], {}, set(), object(), Value(), Value, lambda: None,
                      sys, datetime.date.today(), datetime.date):
            with self.subTest(type=type(value)):
                self.check_access(value, False)

    def test_immutable_values(self):
        for value in (None, True, False, Ellipsis, NotImplemented, 42,
                      12345678901234567890, 1.5, 2j, 'immutable', b'immutable',
                      (), ([],), frozenset(), frozendict({0: []}), range(3),
                      compile('pass', 'immutable-code', 'exec'),
                      int, object, type, list, ValueError,
                      threading.ThreadGroup(), sys.main_thread_group):
            with self.subTest(type=type(value)):
                self.check_access(value, True)

    def test_immutable_builtin_subclass_is_local(self):
        class String(str):
            pass

        value = String('local subclass')
        value.mutable = []
        self.check_access(value, False)

    def test_native_immutable_declaration(self):
        self.check_access(internal.make_immutable_capsule(), True)

    def test_static_immutable_access(self):
        internal.test_static_immutable_access()

    def test_api_return_values(self):
        apis = (
            'PyTuple_GetItem', 'PySequence_GetItem', 'PyObject_GetItem',
            'PyList_GetItem', 'PyList_GetItemRef',
            'PyDict_GetItem', 'PyDict_GetItemWithError', 'PyDict_GetItemRef',
            'PyDict_GetItemString', 'PyDict_GetItemStringRef',
            'PyMapping_GetOptionalItem', 'PyIter_Next', 'PyIter_NextItem',
            'PyIter_Send', 'PyObject_CallNoArgs', 'PyObject_GetAttr',
            'PyObject_GetAttrString', 'PyObject_GetOptionalAttr',
            'PyObject_GetOptionalAttrString', 'PyObject_GenericGetAttr',
        )

        class Value:
            def __repr__(self):
                raise AssertionError('access errors must not call repr')

        for value, immutable in ((Value(), False), (42, True)):
            source = (value, frozendict(value=value))
            for group in (sys.main_thread_group, self.foreign):
                for api in apis:
                    with self.subTest(immutable=immutable, group=group, api=api):
                        accessible = internal.threadgroup_return_probe(
                            source, group, api)
                        self.assertIs(accessible,
                                      immutable or group is sys.main_thread_group)


if __name__ == '__main__':
    unittest.main()
