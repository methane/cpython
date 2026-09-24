"""LOCAL/IMMUTABLE reference acquisition from native ThreadGroup workers."""

import _thread
import datetime
import dis
import sys
import textwrap
import threading
import unittest

from test.support import import_helper, requires_specialization, threading_helper

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
                      slice(2), slice([], None),
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

    def test_thread_start_rejects_foreign_local_callable(self):
        calls = []

        def target():
            calls.append(True)

        thread = threading.Thread(group=self.foreign, target=target)
        with self.assertRaises(IllegalThreadAccessException):
            thread.start()
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [])

        handle = _thread._ThreadHandle()
        with self.assertRaises(IllegalThreadAccessException):
            _thread.start_joinable_thread(target, handle=handle, group=self.foreign)
        self.assertTrue(handle.is_done())
        self.assertEqual(calls, [])

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
            'PyCell_Get',
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

    def check_vm_code(self, code, warmups, specialized=None):
        for value, immutable in ((object(), False), (42, True)):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(immutable=immutable, group=group):
                    probe_code = code.replace()
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe_code, group, (value, None, None), warmups),
                        immutable or group is sys.main_thread_group)
                    if specialized is not None:
                        self.assertIn(specialized, {
                            i.opname for i in dis.get_instructions(
                                probe_code, adaptive=True)})

    def test_vm_heap_loads(self):
        cases = {
            'global': 'return value is None',
            'builtin': 'return builtin_value is None',
            'tuple_item': 'return source[0] is None',
            'tuple_negative_item': 'return source[-3] is None',
            'list_item': 'return items[0] is None',
            'dict_item': "return mapping['value'] is None",
            'unpack_two': 'a, b = source[:2]\nreturn a is None',
            'unpack_tuple': 'a, b, c = source\nreturn a is None',
            'unpack_list': 'a, b, c = items\nreturn a is None',
            'unpack_last': 'a, b, c = source[::-1]\nreturn c is None',
            'unpack_ex_first': 'a, *rest = source\nreturn a is None',
            'unpack_ex_last': '*rest, z = source[::-1]\nreturn z is None',
            'for_tuple': 'for item in source:\n    pass',
            'for_list': 'for item in items:\n    pass',
            'for_iterator': 'for item in source.__iter__():\n    pass',
            'for_generator': 'for item in (x for x in source):\n    pass',
        }
        for name, body in cases.items():
            for warmups in (0, 64):
                with self.subTest(case=name, warmups=warmups):
                    namespace = {}
                    exec('def probe():\n' + textwrap.indent(body, '    '), namespace)
                    self.check_vm_code(namespace['probe'].__code__, warmups)

    @requires_specialization
    def test_vm_specialized_heap_loads(self):
        cases = (
            ('return source[0] is None', 'BINARY_OP_SUBSCR_TUPLE_INT'),
            ('return items[0] is None', 'BINARY_OP_SUBSCR_LIST_INT'),
            ("return mapping['value'] is None", 'BINARY_OP_SUBSCR_DICT'),
            ('a, b = source[:2]\nreturn a is None', 'UNPACK_SEQUENCE_TWO_TUPLE'),
            ('a, b, c = source\nreturn a is None', 'UNPACK_SEQUENCE_TUPLE'),
            ('a, b, c = items\nreturn a is None', 'UNPACK_SEQUENCE_LIST'),
            ('for item in source:\n    pass', 'FOR_ITER_TUPLE'),
            ('for item in items:\n    pass', 'FOR_ITER_LIST'),
        )
        for body, opcode in cases:
            with self.subTest(opcode=opcode):
                namespace = {}
                exec('def probe():\n' + textwrap.indent(body, '    '), namespace)
                self.check_vm_code(namespace['probe'].__code__, 64, opcode)

    def test_vm_name_load(self):
        self.check_vm_code(compile('value is None', '<probe>', 'exec'), 0)

    def test_vm_cell_load(self):
        value = None

        def probe():
            return value is None

        for warmups in (0, 64):
            with self.subTest(warmups=warmups):
                self.check_vm_code(probe.__code__, warmups)

    def test_vm_constant_load(self):
        def probe():
            constant = 'constant'
            return constant is None

        self.assertIn('LOAD_CONST', {i.opname for i in dis.get_instructions(probe)})
        for value, immutable in ((object(), False), (42, True)):
            code = probe.__code__.replace(co_consts=tuple(
                value if item == 'constant' else item
                for item in probe.__code__.co_consts))
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(immutable=immutable, group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        code, group, (value, None, None), 0),
                        immutable or group is sys.main_thread_group)


if __name__ == '__main__':
    unittest.main()
