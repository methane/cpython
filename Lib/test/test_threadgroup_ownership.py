"""LOCAL/IMMUTABLE reference acquisition from native ThreadGroup workers."""

import _thread
import builtins
import datetime
import dis
import gc
import sys
import textwrap
import threading
import unittest

from test.support import (
    Py_GIL_DISABLED, import_helper, nomemtest, requires_specialization,
    script_helper, threading_helper,
)

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

    def test_shareable_attribute(self):
        class Value:
            pass

        for value in (object(), [], {}, set(), Value(), Value, lambda: None,
                      sys, datetime.date.today(), datetime.date):
            with self.subTest(value_type=type(value)):
                self.assertIs(value.__shareable__, threading.Shareable.LOCAL)
        for value in (None, True, 42, 1.5, 2j, 'text', b'bytes', (), ([],),
                      frozenset(), frozendict(value=[]), range(2), slice([]),
                      int, list, type, ValueError, sys.main_thread_group,
                      threading.Shareable, threading.Shareable.LOCAL,
                      threading.Shareable.IMMUTABLE,
                      internal.make_immutable_capsule()):
            with self.subTest(value_type=type(value)):
                self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)

        for value in (Value(), Value, object(), [], (), sys, 42):
            with self.subTest(value_type=type(value)):
                with self.assertRaisesRegex(TypeError, 'cannot assign to __shareable__'):
                    value.__shareable__ = True
                with self.assertRaisesRegex(TypeError, 'cannot assign to __shareable__'):
                    del value.__shareable__
        value = Value()
        value.__dict__['__shareable__'] = threading.Shareable.IMMUTABLE
        self.assertIs(value.__shareable__, threading.Shareable.LOCAL)

    def test_shareable_constants(self):
        self.assertIs(threading.Shareable, _thread.Shareable)
        for name in ('LOCAL', 'IMMUTABLE'):
            state = getattr(threading.Shareable, name)
            self.assertEqual(state.name, name)
            self.assertEqual(repr(state), f'Shareable.{name}')
            self.assertEqual(str(state), repr(state))
            self.check_access(state, True)
            with self.assertRaises((AttributeError, TypeError)):
                state.name = 'changed'
            with self.assertRaises(AttributeError):
                state.extra = []
            with self.assertRaises(TypeError):
                setattr(threading.Shareable, name, None)
        with self.assertRaises(TypeError):
            threading.Shareable()
        with self.assertRaises(TypeError):
            class State(threading.Shareable):
                pass

    def test_shareable_without_threading_import(self):
        script_helper.assert_python_ok('-S', '-c', '''
import sys
assert 'threading' not in sys.modules
assert repr(object().__shareable__) == 'Shareable.LOCAL'
assert repr((1,).__shareable__) == 'Shareable.IMMUTABLE'
assert 'threading' not in sys.modules
''')

    def test_shareable_in_foreign_group(self):
        def probe():
            assert items.__shareable__ is source[1]
            assert cls.__shareable__ is source[1]
            assert value.__shareable__ is value
            assert value.name == 'IMMUTABLE'
            assert value.__class__.LOCAL is source[1]
            assert value.__repr__() == 'Shareable.IMMUTABLE'
            return True

        self.assertTrue(internal.threadgroup_vm_probe(
            probe.__code__, self.foreign,
            (threading.Shareable.IMMUTABLE, threading.Shareable.LOCAL, None), 0))

    def test_static_immutable_access(self):
        internal.test_static_immutable_access()

    def test_unicode_cache_publication_across_groups(self):
        for char in ('\u00e9', '\u65e5', '\U0001f40d'):
            value = char * 19 + '\0suffix'
            expected = value.encode('utf-8')
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(char=char, group=group):
                    internal.threadgroup_unicode_cache_probe(group, value,
                                                             expected)

    def test_string_interning_across_groups(self):
        for char in ('a', '\u00e9', '\u65e5', '\U0001f40d'):
            for group in (sys.main_thread_group, self.foreign):
                for immortal in (False, True):
                    with self.subTest(char=char, group=group, immortal=immortal):
                        value = f'group intern {char * 19}\0{group.name}:{immortal}'
                        expected = value.encode('utf-8')
                        interned = internal.threadgroup_intern(group, value,
                                                              immortal)
                        self.assertEqual(interned, value)
                        self.assertEqual(len(interned), len(value))
                        self.assertEqual(interned.encode('utf-8'), expected)
                        self.assertIs(sys.intern(value), interned)
                        self.assertIs(sys._is_immortal(interned), immortal)
                        copy = expected.decode('utf-8')
                        self.assertIsNot(copy, interned)
                        self.assertIs(internal.threadgroup_intern(group, copy,
                                                                 immortal),
                                      interned)

    def test_mortal_interned_string_reclamation(self):
        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                value = f'mortal intern reclamation {id(self)}:{group.name}'
                gc.collect()
                count = sys.getunicodeinternedsize()
                interned = internal.threadgroup_intern(group, value, False)
                self.assertIs(interned, value)
                self.assertFalse(sys._is_immortal(interned))
                self.assertEqual(sys.getunicodeinternedsize(), count + 1)
                del value, interned
                gc.collect()
                self.assertEqual(sys.getunicodeinternedsize(), count)

    @unittest.skipIf(Py_GIL_DISABLED, "requires mortal interned strings")
    def test_interning_does_not_resurrect_dead_entry(self):
        internal.unicode_intern_dead_entry()

    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_immortal_string_brc_transitions(self):
        for queued in (False, True):
            with self.subTest(queued=queued):
                internal.threadgroup_immortal_brc(queued)

    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_gc_drains_group_brc_queues(self):
        for keep_owner in (False, True):
            for foreign in (False, True):
                with self.subTest(keep_owner=keep_owner, foreign=foreign):
                    script_helper.assert_python_ok('-c', textwrap.dedent(f'''
                        import _testinternalcapi as internal
                        import sys
                        import threading

                        group = (threading.ThreadGroup('GC queue owner')
                                 if {foreign} else sys.main_thread_group)
                        internal.threadgroup_gc_brc_probe(group, {keep_owner})
                    '''))

    @nomemtest
    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_gc_brc_queue_memory_error(self):
        import_helper.import_module('_testcapi')
        script_helper.assert_python_ok('-c', textwrap.dedent('''
            import _testcapi
            import _testinternalcapi as internal
            import gc
            import sys
            import threading

            errors = []
            fail = True
            def callback(phase, info):
                global fail
                if phase == 'start' and fail:
                    fail = False
                    _testcapi.set_nomemory(0, 1)

            group = threading.ThreadGroup('GC queue allocation failure')
            gc.collect()  # Empty the collector's object-stack freelist.
            gc.set_threshold(1000000)
            gc.callbacks.append(callback)
            hook = sys.unraisablehook
            sys.unraisablehook = lambda info: errors.append(info.exc_type)
            try:
                internal.threadgroup_gc_brc_probe(group, True, True)
            finally:
                _testcapi.remove_mem_hooks()
                gc.callbacks.remove(callback)
                sys.unraisablehook = hook
            assert errors == [MemoryError], errors
            assert not internal.threadgroup_world_is_stopped()
        '''))

    def test_static_type_with_zero_initialized_header(self):
        capi = import_helper.import_module('_testcapi')
        typ = capi.RecursingInfinitelyError
        self.assertIs(typ.__shareable__, threading.Shareable.LOCAL)
        self.check_access(typ, False)

    def test_code_caches_across_groups(self):
        def outer(cell):
            def inner(arg):
                return cell + arg
            return inner

        def probe():
            assert (value.co_varnames, value.co_cellvars, value.co_freevars,
                    value.co_code) == source[1]
            assert value.co_varnames is value.co_varnames
            assert value.co_cellvars is value.co_cellvars
            assert value.co_freevars is value.co_freevars
            assert value.co_code is value.co_code
            return True

        for code in (outer.__code__, outer(1).__code__):
            expected = (code.co_varnames, code.co_cellvars, code.co_freevars,
                        code.co_code)
            fresh = code.replace()
            for group in (self.foreign, sys.main_thread_group):
                with self.subTest(group=group, code=code.co_name):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group, (fresh, expected, None), 0, 50))

    def test_weakref_cache_is_local_to_group(self):
        target = compile('pass', 'weakref-target', 'exec')
        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                internal.threadgroup_weakref_probe(group, target)

    def test_code_metadata_acquisition(self):
        class String(str):
            pass

        class Tuple(tuple):
            pass

        class Bytes(bytes):
            pass

        def target(arg):
            return arg.value

        code = target.__code__
        fields = {
            'co_name': String,
            'co_filename': String,
            'co_qualname': String,
            'co_consts': Tuple,
            'co_names': Tuple,
            'co_linetable': Bytes,
            'co_exceptiontable': Bytes,
        }
        cases = (
            ('source[1].__repr__()', ('co_name', 'co_filename')),
            ('source[1].__hash__()',
             ('co_name', 'co_consts', 'co_names', 'co_linetable',
              'co_exceptiontable')),
            ('assert source[1] == source[2]',
             ('co_name', 'co_names', 'co_linetable', 'co_exceptiontable')),
            ('assert not (source[2] != source[1])',
             ('co_name', 'co_names', 'co_linetable', 'co_exceptiontable')),
        )
        for statement, acquired_fields in cases:
            namespace = {}
            exec(f'def probe():\n    {statement}\n    return True', namespace)
            probe = namespace['probe'].__code__
            for field in acquired_fields:
                value = fields[field](getattr(code, field))
                replaced = code.replace(**{field: value})
                self.assertIs(getattr(replaced, field), value)
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(statement=statement, field=field, group=group):
                        self.assertIs(internal.threadgroup_vm_probe(
                            probe, group, (value, replaced, code), 0),
                            group is sys.main_thread_group)
            # Exact builtins remain accessible in both groups.
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(statement=statement, group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe, group, (True, code, code.replace()), 0))

    def test_code_metadata_not_acquired(self):
        class String(str):
            pass

        class Tuple(tuple):
            pass

        def target():
            return None

        code = target.__code__

        def unused():
            source[1].__hash__()
            assert source[1] == source[2]
            assert not (source[1] != source[2])
            source[2].__repr__()
            return True

        # Filename and qualname do not participate in hash or equality;
        # repr reads the filename, but not the qualname.
        named = code.replace(co_qualname=String('local qualname'))
        self.assertTrue(internal.threadgroup_vm_probe(
            unused.__code__, self.foreign,
            (True, named.replace(co_filename=String('local filename')), named), 0))

        def short_circuit():
            assert source[1] != source[2]
            return True

        # A different name short-circuits comparison of later stored fields.
        self.assertTrue(internal.threadgroup_vm_probe(
            short_circuit.__code__, self.foreign,
            (True, code.replace(co_names=Tuple(code.co_names)),
             code.replace(co_name='different')), 0))

    @requires_specialization
    def test_code_specialization_across_groups(self):
        def probe(a, b, expected):
            assert a + b == expected
            return True

        def opnames():
            return {inst.opname for inst in dis._get_instructions_bytes(
                internal.get_tlbc(probe))}

        for _ in range(100):
            probe(1, 2, 3)
        self.assertIn('BINARY_OP_ADD_INT', opnames())
        for group in (self.foreign, sys.main_thread_group):
            with self.subTest(group=group):
                accessible, bytecode = internal.threadgroup_vm_probe(
                    probe.__code__, group, ('a', 'b', 'ab'), 0, 100, True)
                self.assertTrue(accessible)
                worker_opnames = {inst.opname for inst in
                                  dis._get_instructions_bytes(bytecode)}
                self.assertIn('BINARY_OP_ADD_UNICODE', worker_opnames)
                self.assertNotIn('BINARY_OP_ADD_INT', worker_opnames)
                self.assertIn('BINARY_OP_ADD_INT', opnames())
                self.assertNotIn('BINARY_OP_ADD_UNICODE', opnames())

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
            'PyVectorcall_Call', 'PyObject_Call', 'PyObject_Vectorcall',
            'PyObject_VectorcallDict', 'PyVectorcall_Call_keywords',
            'PyObject_RichCompare', 'PyObject_RichCompareBool',
            'PyCFunction_GetSelf', 'PyMethod_Function', 'PyMethod_Self',
            'PyInstanceMethod_Function',
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

    def test_numeric_conversion_slot_returns(self):
        import warnings

        class Integer(int):
            pass

        class Float(float):
            pass

        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            for api, typ, subtype in (
                ('PyNumber_Index', int, Integer),
                ('PyNumber_Long', int, Integer),
                ('PyNumber_Float', float, Float),
                ('PyFloat_AsDouble', float, Float),
            ):
                for value in (typ(-1), subtype(-1)):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(api=api, value_type=type(value), group=group):
                            self.assertIs(internal.threadgroup_return_probe(
                                (value, frozendict()), group, api),
                                type(value) is typ or group is sys.main_thread_group)
                # An inaccessible return is rejected before reporting an
                # invalid numeric return type as well.
                with self.subTest(api=api, invalid_return=True):
                    self.assertFalse(internal.threadgroup_return_probe(
                        ([], frozendict()), self.foreign, api))
                # Reverse the direction: Main can process deprecation warnings,
                # so warning-module ownership cannot mask an unchecked copy.
                source = (internal.threadgroup_number_source(self.foreign, typ)
                          + (frozendict(),))
                with self.subTest(api=api, foreign_number_in_main=True):
                    self.assertFalse(internal.threadgroup_return_probe(
                        source, sys.main_thread_group, api))

    def test_interpreter_namespace_returns(self):
        for api, value in (
            ('PyEval_GetBuiltins', builtins.__dict__),
            ('PyEval_GetFrameBuiltins', builtins.__dict__),
            ('PyImport_GetModuleDict', sys.modules),
            ('PySys_GetXOptions', sys._xoptions),
        ):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(api=api, group=group):
                    self.assertIs(internal.threadgroup_return_probe(
                        (value, frozendict()), group, api),
                        group is sys.main_thread_group)

    def check_vm_code(self, code, warmups, specialized=None):
        for value, immutable in ((object(), False), (42, True)):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(immutable=immutable, group=group):
                    probe_code = code.replace()
                    accessible, bytecode = internal.threadgroup_vm_probe(
                        probe_code, group, (value, None, None), warmups, 1, True)
                    self.assertIs(accessible,
                                  immutable or group is sys.main_thread_group)
                    if specialized is not None:
                        self.assertIn(specialized, {
                            i.opname for i in dis._get_instructions_bytes(
                                bytecode)})

    def test_sequence_element_operations(self):
        cases = {
            'tuple repr': 'source.__repr__()',
            'tuple hash': 'source.__hash__()',
            'tuple contains': 'None in source',
            'tuple count': 'source.count(None)',
            'tuple index': 'source.index(None)',
            'tuple equality': 'source == (None, None, None)',
            'tuple ordering': 'source < (None, None, None)',
            'tuple identity shortcut': 'source == source',
            'list repr': 'items.__repr__()',
            'list contains': 'None in items',
            'list count': 'items.count(None)',
            'list index': 'items.index(None)',
            'list remove': 'items.remove(None)',
            'list equality': 'items == [None, None, None]',
            'list ordering': 'items < [None, None, None]',
            'list identity shortcut': 'items == items',
            'list sort': 'items[:] = source[:1] * 2\nitems.sort()',
            'list sort key': (
                'def key(item):\n    return 0\nitems.sort(key=key)'),
            'list sort tuple first': (
                'items[:] = [source[:1], (None,)]\nitems.sort()'),
            'list sort tuple later': (
                'items[:] = [(0,) + source[:1], (0, None)]\nitems.sort()'),
            'comparison return': 'box < None',
            'comparison truth': 'if box < None:\n    pass',
            'sort comparison return': 'items[:] = [box, box]\nitems.sort()',
            'tuple sort comparison return': (
                'items[:] = [(box,), (None,)]\nitems.sort()'),
        }
        for name, body in cases.items():
            namespace = {}
            exec('def probe():\n' + textwrap.indent(body, '    ') +
                 '\n    return True', namespace)
            code = namespace['probe'].__code__
            for immutable in (False, True):
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(operation=name, immutable=immutable,
                                      group=group):
                        value = internal.make_container_element(immutable)
                        accessible = immutable or group is sys.main_thread_group
                        self.assertIs(internal.threadgroup_vm_probe(
                            code.replace(), group, (value, None, None), 0),
                            accessible)
                        if not accessible:
                            self.assertEqual(
                                internal.container_element_calls(value), 0)

    def test_slice_component_acquisition(self):
        cases = (
            ('source[1].__repr__()', None),
            ('source[1].__hash__()', None),
            ('source[1].indices(10)', None),
            ('[][source[1]]', None),
            ('()[source[1]]', None),
            ('b""[source[1]]', None),
            ('""[source[1]]', None),
            ('source[2][source[1]]', range(10)),
            ('source[1] == source[2]', slice(0, 3, 1)),
            ('source[2] < source[1]', slice(0, 3, 1)),
        )
        for index, field in enumerate(('start', 'stop', 'step')):
            for statement, other in (*cases, (f'source[1].{field}', None)):
                namespace = {}
                exec(f'def probe():\n    {statement}\n    return True', namespace)
                for immutable in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(field=field, statement=statement,
                                          immutable=immutable, group=group):
                            value = internal.make_container_element(immutable)
                            parts = [0, 3, 1]
                            parts[index] = value
                            item = slice(*parts)
                            accessible = immutable or group is sys.main_thread_group
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__, group,
                                (value, item, other), 0), accessible)
                            if not accessible:
                                self.assertEqual(
                                    internal.container_element_calls(value), 0)

    def test_slice_getindices_acquisition(self):
        class Index(int):
            pass

        def probe():
            try:
                result = bound_builtin(source[1])
            except source[2][0]:
                assert source[2][1]
            else:
                assert not source[2][1]
                assert result == source[2][2]
            return True

        for index in range(3):
            for integer_type in (int, Index):
                parts = [0, 3, 1]
                parts[index] = integer_type(parts[index])
                item = slice(*parts)
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(index=index, integer_type=integer_type,
                                      group=group):
                        inaccessible = (integer_type is Index and
                                        group is self.foreign)
                        expected = (IllegalThreadAccessException, inaccessible,
                                    (0, 3, 1))
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group, (True, item, expected),
                            0, 1, False, internal.slice_getindices_probe))

    def test_slice_without_component_acquisition(self):
        def identity_and_copy():
            item = source[1]
            assert item == item and item <= item and item >= item
            assert not (item != item or item < item or item > item)
            assert not (item == ())
            state = item.__reduce__()
            assert state[0] is item.__class__
            assert state[1].__len__() == 3
            return True

        value = internal.make_container_element(False)
        self.assertTrue(internal.threadgroup_vm_probe(
            identity_and_copy.__code__, self.foreign,
            (True, slice(value, value, value), None), 0))
        self.assertEqual(internal.container_element_calls(value), 0)

        def short_circuit():
            assert source[1] < source[2]
            assert source[2] != source[1]
            return True

        self.assertTrue(internal.threadgroup_vm_probe(
            short_circuit.__code__, self.foreign,
            (True, slice(0, value, value), slice(1, value, value)), 0))
        self.assertEqual(internal.container_element_calls(value), 0)

        # Invalid length or a zero step fails before acquiring start and stop.
        for statement, item in (
            ('source[1].indices(-1)', slice(value, value, value)),
            ('source[1].indices(10)', slice(value, value, 0)),
            ('[][source[1]]', slice(value, value, 0)),
        ):
            namespace = {}
            exec('def probe():\n    try:\n' +
                 f'        {statement}\n' +
                 '    except source[2]:\n        return True\n' +
                 '    assert False', namespace)
            with self.subTest(statement=statement):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, item, ValueError), 0))
        self.assertEqual(internal.container_element_calls(value), 0)

        def invalid_step():
            assert bound_builtin(source[1]) is None
            return True

        # The legacy API rejects non-integer steps by type, without conversion.
        self.assertTrue(internal.threadgroup_vm_probe(
            invalid_step.__code__, self.foreign,
            (True, slice(value, value, value), None),
            0, 1, False, internal.slice_getindices_probe))
        self.assertEqual(internal.container_element_calls(value), 0)

    def test_string_tailmatch_acquires_alternatives(self):
        class String(str):
            pass

        class Bytes(bytes):
            pass

        native_values = [internal.make_container_element(immutable)
                         for immutable in (False, True)]
        for receiver, values in (
            ("'buffer'", ('buffer', String('buffer'))),
            ("b'buffer'", (b'buffer', Bytes(b'buffer'), *native_values)),
            ("source[2](b'buffer')",
             (b'buffer', Bytes(b'buffer'), *native_values)),
        ):
            for method in ('startswith', 'endswith'):
                namespace = {}
                exec('def probe():\n'
                     f'    assert {receiver}.{method}(source[1])\n'
                     '    return True', namespace)
                for value in values:
                    for group in (sys.main_thread_group, self.foreign):
                        accessible = (group is sys.main_thread_group or
                                      value.__shareable__ is
                                      threading.Shareable.IMMUTABLE)
                        native = type(value) not in (str, String, bytes, Bytes)
                        before = (internal.container_element_calls(value)
                                  if native else 0)
                        with self.subTest(receiver=receiver, method=method,
                                          value_type=type(value), group=group):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__, group,
                                (value, (value,), bytearray), 0), accessible)
                            if native:
                                self.assertEqual(
                                    internal.container_element_calls(value),
                                    before + accessible)

    def test_string_join_acquires_elements(self):
        class String(str):
            pass

        class Bytes(bytes):
            pass

        native_values = [internal.make_container_element(immutable)
                         for immutable in (False, True)]
        for separator, values, prefix in (
            ("'-'", ('buffer', String('buffer')), 'first'),
            ("b'-'", (b'buffer', Bytes(b'buffer'), *native_values), b'first'),
            ("source[2][1](b'-')",
             (b'buffer', Bytes(b'buffer'), *native_values), b'first'),
        ):
            namespace = {}
            exec('def probe():\n'
                 '    values = source[1]\n'
                 '    if source[2][0] is not None:\n'
                 '        values = source[2][0](values)\n'
                 f'    assert {separator}.join(values) == source[2][2]\n'
                 '    return True', namespace)
            for value in values:
                for multiple in (False, True):
                    items = (prefix, value) if multiple else (value,)
                    expected = ('first-buffer' if multiple else 'buffer')
                    if isinstance(prefix, bytes):
                        expected = expected.encode()
                    for copy in (None, list):
                        for group in (sys.main_thread_group, self.foreign):
                            accessible = (group is sys.main_thread_group or
                                          value.__shareable__ is
                                          threading.Shareable.IMMUTABLE)
                            native = type(value) not in (str, String, bytes, Bytes)
                            before = (internal.container_element_calls(value)
                                      if native else 0)
                            with self.subTest(separator=separator, copy=copy,
                                              multiple=multiple, group=group,
                                              value_type=type(value)):
                                self.assertIs(internal.threadgroup_vm_probe(
                                    namespace['probe'].__code__, group,
                                    (value, items, (copy, bytearray, expected)),
                                    0), accessible)
                                if native:
                                    self.assertEqual(
                                        internal.container_element_calls(value),
                                        before + accessible)

    def test_bytes_from_sequence_acquires_elements(self):
        class Integer(int):
            pass

        def probe():
            values = source[1]
            if source[2][1] is not None:
                values = source[2][1](values)
            assert source[2][0](values) == b'\x00\x01'
            return True

        for value in (1, Integer(1), internal.make_container_element(False),
                      internal.make_container_element(True)):
            for copy in (None, list):
                for group in (sys.main_thread_group, self.foreign):
                    accessible = (group is sys.main_thread_group or
                                  value.__shareable__ is
                                  threading.Shareable.IMMUTABLE)
                    native = type(value) not in (int, Integer)
                    before = internal.container_element_calls(value) if native else 0
                    with self.subTest(value_type=type(value), copy=copy, group=group):
                        self.assertIs(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (value, (0, value), (bytes, copy)), 0), accessible)
                        if native:
                            self.assertEqual(internal.container_element_calls(value),
                                             before + accessible)

    def test_string_sequence_short_circuit_and_cleanup(self):
        def probe():
            bytearray_type, access_error = source[2]
            foreign = source[1]
            assert 'buffer'.startswith(('buffer',) + foreign)
            assert 'buffer'.endswith(('buffer',) + foreign)
            assert b'buffer'.startswith((b'buffer',) + foreign)
            assert b'buffer'.endswith((b'buffer',) + foreign)
            mutable = bytearray_type(b'buffer')
            assert mutable.startswith((b'buffer',) + foreign)
            assert mutable.endswith((b'buffer',) + foreign)
            for separator in ('-', b'-', bytearray_type(b'-')):
                try:
                    separator.join((0,) + foreign)
                except TypeError:
                    pass
                else:
                    assert False
            for separator in (b'-', bytearray_type(b'-')):
                try:
                    separator.join((mutable,) + foreign)
                except access_error:
                    pass
                else:
                    assert False
                # A rejected later element must release the earlier buffer.
                mutable.extend(b'!')
            return True

        value = internal.make_container_element(False)
        self.assertTrue(internal.threadgroup_vm_probe(
            probe.__code__, self.foreign,
            (True, (value,), (bytearray, IllegalThreadAccessException)), 0))
        self.assertEqual(internal.container_element_calls(value), 0)

    def test_marshal_heap_acquisition(self):
        import_helper.import_module('_testcapi')
        # Regrtest's Python audit hook belongs to Main. An isolated process
        # lets serialization reach its heap reads in the foreign group.
        script_helper.assert_python_ok('-c', textwrap.dedent('''
            import os
            import sys
            import tempfile
            import threading
            import _testcapi as capi
            import _testinternalcapi as internal

            class Bytes(bytes):
                pass

            def target():
                return None

            def encode():
                obj = source[1]
                if source[2][3] is not None:
                    obj = source[2][3](obj)
                try:
                    bound_builtin(obj, source[2][1])
                except source[2][0]:
                    assert source[2][2]
                else:
                    assert not source[2][2]
                return True

            def encode_file():
                obj = source[1]
                if source[2][3] is not None:
                    obj = source[2][3](obj)
                try:
                    bound_builtin(obj, source[2][4], source[2][1])
                except source[2][0]:
                    assert source[2][2]
                else:
                    assert not source[2][2]
                return True

            cases = (
                ('tuple', lambda v: (v,), None, 0),
                ('list copy', lambda v: (v,), list, 0),
                ('dict copy', lambda v: frozendict(value=v), dict, 0),
                ('frozendict value', lambda v: frozendict(value=v), None, 6),
                ('frozendict key', lambda v: frozendict({v: 1}), None, 6),
                ('frozenset', lambda v: frozenset([v]), None, 0),
                ('set copy', lambda v: frozenset([v]), set, 0),
                ('slice start', lambda v: slice(v, None), None, 5),
                ('slice stop', lambda v: slice(None, v), None, 5),
                ('slice step', lambda v: slice(None, None, v), None, 5),
                ('code consts', lambda v: target.__code__.replace(co_consts=(v,)),
                 None, 0),
            )
            group = threading.ThreadGroup('marshal')
            with tempfile.TemporaryDirectory() as directory:
                filename = os.fsencode(os.path.join(directory, 'object.bin'))
                for name, make, copy, first_version in cases:
                    for version in range(first_version, 7):
                        for value in (b'bytes', Bytes(b'bytes'),
                                      internal.make_container_element(False),
                                      internal.make_container_element(True)):
                            shared = value.__shareable__ is threading.Shareable.IMMUTABLE
                            obj = make(value)
                            for owner in (sys.main_thread_group, group):
                                rejected = not shared and owner is group
                                options = (IllegalThreadAccessException, version,
                                           rejected, copy, filename)
                                for code, api in (
                                    (encode.__code__, capi.pymarshal_writeobjecttostring),
                                    (encode_file.__code__, capi.pymarshal_write_object_to_file),
                                ):
                                    native = type(value) not in (bytes, Bytes)
                                    before = internal.container_element_calls(value) if native else 0
                                    try:
                                        assert internal.threadgroup_vm_probe(
                                            code, owner, (True, obj, options),
                                            0, 1, False, api)
                                        if rejected and native:
                                            assert internal.container_element_calls(value) == before
                                    except Exception:
                                        print(name, version, type(value), owner, api.__name__)
                                        raise
        '''))

    def test_marshal_code_metadata_acquisition(self):
        import_helper.import_module('_testcapi')
        script_helper.assert_python_ok('-c', textwrap.dedent('''
            import marshal
            import sys
            import threading
            import _testcapi as capi
            import _testinternalcapi as internal

            class String(str):
                pass
            class Tuple(tuple):
                pass
            class Bytes(bytes):
                pass

            def target():
                return None

            def encode():
                try:
                    bound_builtin(source[1], source[2][2])
                except source[2][0]:
                    assert source[2][1]
                else:
                    assert not source[2][1]
                return True

            fields = {'co_name': String, 'co_filename': String,
                      'co_qualname': String, 'co_names': Tuple,
                      'co_consts': Tuple, 'co_linetable': Bytes,
                      'co_exceptiontable': Bytes}
            group = threading.ThreadGroup('marshal metadata')
            for field, cls in fields.items():
                value = cls(getattr(target.__code__, field))
                obj = target.__code__.replace(**{field: value})
                assert getattr(obj, field) is value
                for owner in (sys.main_thread_group, group):
                    # Marshal does not support str/tuple subclasses at all;
                    # preserve that Main error, while foreign reads are denied.
                    unsupported = cls is not Bytes
                    foreign = owner is group
                    expected = (IllegalThreadAccessException if foreign else ValueError,
                                foreign or unsupported, 6)
                    try:
                        assert internal.threadgroup_vm_probe(
                            encode.__code__, owner, (True, obj, expected),
                            0, 1, False, capi.pymarshal_writeobjecttostring)
                    except Exception:
                        print(field, owner)
                        raise

            for obj, version in ((slice([], []), 4),
                                 (frozendict(value=[]), 5)):
                assert internal.threadgroup_vm_probe(
                    encode.__code__, group,
                    (True, obj, (ValueError, True, version)),
                    0, 1, False, capi.pymarshal_writeobjecttostring)

            def disallow_code():
                try:
                    bound_builtin(source[1], 6, allow_code=False)
                except source[2]:
                    return True
                assert False

            assert internal.threadgroup_vm_probe(
                disallow_code.__code__, group,
                (True, target.__code__.replace(co_consts=([],)), ValueError),
                0, 1, False, marshal.dumps)

            element = internal.make_container_element(False)
            for obj, error in (((range(2), element), ValueError),
                               ((element, range(2)), IllegalThreadAccessException)):
                assert internal.threadgroup_vm_probe(
                    encode.__code__, group, (True, obj, (error, True, 6)),
                    0, 1, False, capi.pymarshal_writeobjecttostring)
                assert internal.container_element_calls(element) == 0
        '''))

    def test_sequence_operations_without_element_access(self):
        cases = (
            'assert source[1].__len__() == 1',
            'assert source[1] != ()',
            'assert None in (None,) + source[1]',
            'assert ((None,) + source[1]).index(None) == 0',
            'assert (source[1] + (None,)).index(None, 1) == 1',
            'items[:] = source[1]\nassert items != []',
            'items[:] = (None,) + source[1]\nassert None in items',
            'items[:] = [(0,) + source[1], (1,) + source[1]]\nitems.sort()',
        )
        for body in cases:
            with self.subTest(body=body):
                value = internal.make_container_element(False)
                namespace = {}
                exec('def probe():\n' + textwrap.indent(body, '    ') +
                     '\n    return True', namespace)
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, (value,), None), 0))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_immutable_container_cached_hash_does_not_acquire_elements(self):
        def probe():
            assert source[1].__hash__() == source[2]
            return True

        for factory in (lambda v: (v,), lambda v: frozenset([v]),
                        lambda v: frozendict(value=v)):
            value = internal.make_container_element(False)
            container = factory(value)
            expected = hash(container)
            calls = internal.container_element_calls(value)
            with self.subTest(container_type=type(container)):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, self.foreign,
                    (True, container, expected), 0))
                self.assertEqual(internal.container_element_calls(value), calls)

    def test_frozendict_hash_acquires_values(self):
        def probe():
            source[1].__hash__()
            return True

        for immutable in (False, True):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(immutable=immutable, group=group):
                    value = internal.make_container_element(immutable)
                    container = frozendict(value=value)
                    accessible = immutable or group is sys.main_thread_group
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe.__code__, group, (value, container, None), 0),
                        accessible)
                    self.assertEqual(internal.container_element_calls(value),
                                     int(accessible))

    def test_immutable_hash_uses_stored_key_hashes(self):
        def probe():
            source[1].__hash__()
            return True

        for factory in (lambda v: frozenset([v]),
                        lambda v: frozendict({v: 42})):
            value = internal.make_container_element(False)
            container = factory(value)
            calls = internal.container_element_calls(value)
            with self.subTest(container_type=type(container)):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, self.foreign, (True, container, None), 0))
                self.assertEqual(internal.container_element_calls(value), calls)

    def test_immutable_hash_caches_across_groups(self):
        def probe():
            assert value.__hash__() == source[1]
            return True

        cases = (
            ('immutable hash cache', lambda: ''.join(('immutable ', 'hash cache'))),
            (b'cached bytes', lambda: bytes(bytearray(b'cached bytes'))),
            ((123, 456), lambda: tuple([123, 456])),
            (frozenset([123, 456]), lambda: frozenset([123, 456])),
            (frozendict(value=42), lambda: frozendict(value=42)),
        )
        for control, factory in cases:
            expected = hash(control)
            fresh = factory()
            self.assertIsNot(fresh, control)
            for group in (self.foreign, sys.main_thread_group):
                with self.subTest(value_type=type(fresh), group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group, (fresh, expected, None), 0, 10))
            self.assertEqual(hash(fresh), expected)

    def test_hash_table_lookup_acquires_keys(self):
        cases = (
            (frozenset, None, 'assert 0 not in table'),
            (frozenset, set, 'assert 0 not in table'),
            (frozenset, set, 'table.add(0)'),
            (frozenset, set, 'table.discard(0)'),
            (lambda v: frozendict.fromkeys(v), None, 'assert 0 not in table'),
            (lambda v: frozendict.fromkeys(v), None, 'table.get(0)'),
            (lambda v: frozendict.fromkeys(v), dict, 'assert 0 not in table'),
            (lambda v: frozendict.fromkeys(v), dict, 'table.get(0)'),
            (lambda v: frozendict.fromkeys(v), dict, 'table.setdefault(0)'),
            (lambda v: frozendict.fromkeys(v), dict, 'table[0] = None'),
            (lambda v: frozendict.fromkeys(v), dict, 'table.pop(0, None)'),
        )
        for factory, copy_type, body in cases:
            namespace = {}
            exec('def probe():\n'
                 '    table = source[1]\n'
                 '    if source[2] is not None:\n'
                 '        table = source[2](table)\n' +
                 textwrap.indent(body, '    ') + '\n    return True', namespace)
            for immutable in (False, True):
                for group in (sys.main_thread_group, self.foreign):
                    value = internal.make_container_element(immutable)
                    table = factory([value])
                    calls = internal.container_element_calls(value)
                    accessible = immutable or group is sys.main_thread_group
                    with self.subTest(table_type=type(table), copy_type=copy_type,
                                      body=body, immutable=immutable, group=group):
                        self.assertIs(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__.replace(), group,
                            (value, table, copy_type), 0), accessible)
                        calls_after = internal.container_element_calls(value)
                        if accessible:
                            self.assertGreater(calls_after, calls)
                        else:
                            self.assertEqual(calls_after, calls)

    def test_hash_table_lookup_without_key_acquisition(self):
        def probe():
            assert 1 not in source[1]
            return True

        for factory in (frozenset, lambda v: frozendict.fromkeys(v)):
            value = internal.make_container_element(False)
            table = factory([value])
            calls = internal.container_element_calls(value)
            with self.subTest(table_type=type(table)):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, self.foreign, (True, table, None), 0))
                self.assertEqual(internal.container_element_calls(value), calls)

    def test_bulk_hash_table_operations_acquire_source_keys(self):
        dict_from_key = lambda v: frozendict({v: None})
        dict_with_collision = lambda v: frozendict({0: None, v: None})
        set_from_key = lambda v: frozenset([v])
        set_with_collision = lambda v: frozenset([0, v])
        cases = (
            (set_from_key, set, 'table & {0, 1}'),
            (set_from_key, set, 'table.isdisjoint({0, 1})'),
            (set_from_key, set, 'table.difference({0})'),
            (set_from_key, set, 'table.difference({0: None})'),
            (set_from_key, set, 'table.issubset({0})'),
            (set_from_key, set, 'table < {0, 1}'),
            (set_from_key, set, '{0} | table'),
            (set_from_key, set, '{0} ^ table'),
            (set_from_key, set, 'target = {0}; target.update(table)'),
            (set_from_key, set, 'target = {0}; target.difference_update(table)'),
            (set_from_key, set,
             'target = {0}; target.symmetric_difference_update(table)'),
            (set_from_key, set,
             'target = {0, 1}; target.intersection_update(table)'),
            (dict_from_key, dict, 'target = {0}; target.update(table)'),
            (dict_from_key, dict,
             'target = {0}; target.symmetric_difference_update(table)'),
            (dict_from_key, dict, 'target = {0: None}; target.update(table)'),
            (dict_from_key, dict, '{0: None} | table'),
            (dict_from_key, dict, '{0: None, **table}'),
            (dict_with_collision, dict, 'dict.fromkeys(table)'),
            (set_with_collision, set, 'dict.fromkeys(table)'),
        )
        for factory, copy_type, body in cases:
            namespace = {}
            exec('def probe():\n'
                 '    dict = {}.__class__\n'
                 '    table = source[1]\n'
                 '    if source[2] is not None:\n'
                 '        table = source[2](table)\n' +
                 textwrap.indent(body, '    ') + '\n    return True', namespace)
            for copy in (None, copy_type):
                for immutable in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        value = internal.make_container_element(immutable)
                        table = factory(value)
                        calls = internal.container_element_calls(value)
                        accessible = immutable or group is sys.main_thread_group
                        with self.subTest(body=body, copy=copy,
                                          immutable=immutable, group=group):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__.replace(), group,
                                (value, table, copy), 0), accessible)
                            if not accessible:
                                self.assertEqual(
                                    internal.container_element_calls(value), calls)

    def test_bulk_copy_does_not_acquire_elements(self):
        cases = (
            (lambda v: frozenset([v]), 'target = set(table)'),
            (lambda v: frozenset([v]), 'target = set(); target.update(table)'),
            (lambda v: frozenset([v]), 'target = table | table.__class__()'),
            (lambda v: frozendict({v: None}), 'target = dict(table)'),
            (lambda v: frozendict({v: None}), 'target = {}; target.update(table)'),
            (lambda v: frozendict(value=v), 'target = {0: None, **table}'),
        )
        for factory, body in cases:
            value = internal.make_container_element(False)
            table = factory(value)
            calls = internal.container_element_calls(value)
            namespace = {}
            exec('def probe():\n'
                 '    set = {0}.__class__\n'
                 '    dict = {}.__class__\n'
                 '    table = source[1]\n' +
                 textwrap.indent(body, '    ') +
                 '\n    assert target.__len__() >= table.__len__()\n'
                 '    return True',
                 namespace)
            with self.subTest(body=body):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, table, None), 0))
                self.assertEqual(internal.container_element_calls(value), calls)

    def test_dict_element_operations(self):
        cases = (
            (lambda v: (frozendict({v: None}), None), 'table.__repr__()'),
            (lambda v: (frozendict(value=v), None), 'table.__repr__()'),
            (lambda v: (frozendict({v: None}), None), 'table == table'),
            (lambda v: (frozendict(value=v), None), 'table == table'),
            (lambda v: (frozendict(value=v), None), "table == {'value': None}"),
            (lambda v: (frozendict(value=v), None), "{'value': None} == table"),
            (lambda v: (frozendict({0: None}), (v, None)),
             'source[2] in table.items()'),
            (lambda v: (frozendict({0: None}), (0, v)),
             'source[2] in table.items()'),
            (lambda v: (frozendict({v: None}), None),
             'table.items() ^ table.items()'),
            (lambda v: (frozendict(value=v), None),
             'table.items() ^ table.items()'),
            (lambda v: (frozendict(value=v), None),
             "table.items() ^ {'value': None}.items()"),
            (lambda v: (frozendict(value=v), None),
             "{'value': None}.items() ^ table.items()"),
        )
        for index, (factory, body) in enumerate(cases):
            for copy in (False, True):
                prefix = 'table = {**source[1]}' if copy else 'table = source[1]'
                namespace = {}
                exec('def probe():\n' + textwrap.indent(prefix + '\n' + body,
                                                       '    ') +
                     '\n    return True', namespace)
                for immutable in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        value = internal.make_container_element(immutable)
                        table, operand = factory(value)
                        calls = internal.container_element_calls(value)
                        accessible = immutable or group is sys.main_thread_group
                        with self.subTest(case=index, copy=copy,
                                          immutable=immutable, group=group):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__.replace(), group,
                                (value, table, operand), 0), accessible)
                            if not accessible:
                                self.assertEqual(
                                    internal.container_element_calls(value), calls)

    def test_dict_comparison_without_value_acquisition(self):
        cases = (
            (lambda v: frozendict(value=v), 'assert table != {}'),
            (lambda v: frozendict(value=v), "assert table != {'missing': None}"),
            (lambda v: frozendict({0: None}), 'assert source[2] not in table.items()'),
        )
        for factory, body in cases:
            value = internal.make_container_element(False)
            table = factory(value)
            calls = internal.container_element_calls(value)
            namespace = {}
            exec('def probe():\n    table = source[1]\n' +
                 textwrap.indent(body, '    ') + '\n    return True', namespace)
            with self.subTest(body=body):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, table, (1, value)), 0))
                self.assertEqual(internal.container_element_calls(value), calls)

    def test_sort_access_failure_restores_list(self):
        for reverse in (False, True):
            for key in ('None', 'key'):
                for size in (2, 260):
                    with self.subTest(reverse=reverse, key=key, size=size):
                        value = internal.make_container_element(False)
                        namespace = {}
                        exec(textwrap.dedent(f'''
                            def probe():
                                def key(item):
                                    return item
                                first = source[1]
                                second = (None,)
                                items[:] = [first, second] * {size // 2}
                                original = items.copy()
                                try:
                                    items.sort(key={key}, reverse={reverse})
                                except source[2]:
                                    assert items.__len__() == {size}
                                    i = 0
                                    while i < {size}:
                                        assert items[i] is original[i]
                                        i += 1
                                else:
                                    assert False, 'sort must reject LOCAL elements'
                                return True
                        '''), namespace)
                        self.assertTrue(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__, self.foreign,
                            (True, (value,), IllegalThreadAccessException), 0))
                        self.assertEqual(internal.container_element_calls(value), 0)

    def test_vm_heap_loads(self):
        cases = {
            'global': 'return value is None',
            'builtin': 'return builtin_value is None',
            'tuple_item': 'return source[0] is None',
            'tuple_negative_item': 'return source[-3] is None',
            'list_item': 'return items[0] is None',
            'dict_item': "return mapping['value'] is None",
            'slot_attribute': 'return box.value is None',
            'instance_attribute': 'return instance.value is None',
            'class_attribute': 'return cls.value is None',
            'module_attribute': 'return module.value is None',
            'slot_method': 'try:\n    box.value()\nexcept TypeError:\n    return True',
            'instance_method': 'try:\n    instance.value()\nexcept TypeError:\n    return True',
            'class_method': 'try:\n    cls.value()\nexcept TypeError:\n    return True',
            'module_method': 'try:\n    module.value()\nexcept TypeError:\n    return True',
            'native_star_args': 'return consumer(*source)',
            'native_star_kwargs': 'return consumer(**mapping)',
            'native_star_kwargs_partial': 'return consumer(**{"safe": None, **mapping})',
            'native_star_both': 'return consumer(*source, extra=None)',
            'native_legacy_expansion': 'return legacy_call(source)',
            'native_prepend_expansion': 'return prepend_call(source)',
            'python_star_args': 'def consume(*args):\n    return True\nreturn consume(*source)',
            'python_star_kwargs': 'def consume(**kwargs):\n    return True\nreturn consume(**mapping)',
            'python_star_kwargs_partial': 'def consume(**kwargs):\n    return True\nreturn consume(**{"safe": None, **mapping})',
            'python_star_both': 'def consume(*args, **kw):\n    return True\nreturn consume(*source, extra=None)',
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
            ('return box.value is None', 'LOAD_ATTR_SLOT'),
            ('return instance.value is None', 'LOAD_ATTR_INSTANCE_VALUE'),
            ('return module.value is None', 'LOAD_ATTR_MODULE'),
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

    def test_descriptor_qualname_class_acquisition(self):
        def probe():
            assert source[1].__qualname__ == source[2]
            return True

        for cached in (False, True):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(cached=cached, group=group):
                    class Owner:
                        __slots__ = ('field',)

                    descriptor = Owner.field
                    expected = Owner.__qualname__ + '.field'
                    if cached:
                        self.assertEqual(descriptor.__qualname__, expected)
                    # Reading a populated cache does not acquire the class.
                    marker = None if cached else Owner
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (marker, descriptor, expected), 0),
                        cached or group is sys.main_thread_group)

    def test_descriptor_repr_class_acquisition(self):
        class Owner:
            __slots__ = ('field',)

        def probe():
            assert source[1].__repr__() == source[2]
            return True

        for descriptor in (Owner.field, list.append, int.real, int.__add__,
                           object.__str__):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(descriptor=descriptor, group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (descriptor.__objclass__, descriptor, repr(descriptor)), 0),
                        descriptor is not Owner.field or group is sys.main_thread_group)

    def test_vm_descriptor_checked_before_call(self):
        for warmups in (0, 64):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(warmups=warmups, group=group):
                    descriptor = internal.make_access_descriptor()
                    namespace = {}
                    exec('def probe():\n    return cls.value is None', namespace)
                    self.assertIs(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (descriptor, None, None), warmups),
                        group is sys.main_thread_group)
                    self.assertEqual(internal.access_descriptor_calls(descriptor),
                                     1 if group is sys.main_thread_group else 0)

    def test_foreign_special_methods(self):
        def getitem(self, key):
            return 42

        def add(self, other):
            return 42

        def to_bytes(self):
            return b'result'

        def enter(self):
            return None

        def exit(self, *args):
            return None

        cases = (
            ({'__getitem__': getitem}, getitem, 'return source[1][0] == 42'),
            ({'__getitem__': getitem}, getitem,
             'for item in source[1]:\n    return item == 42'),
            ({'__add__': add}, add, 'return source[1] + 1 == 42'),
            ({'__bytes__': to_bytes}, to_bytes,
             "return source[2](source[1]) == b'result'"),
            ({'__enter__': enter, '__exit__': exit}, enter,
             'with source[1]:\n    pass\nreturn True'),
        )
        for methods, method, body in cases:
            instance = internal.make_immutable_special_method_instance(methods)
            self.assertIs(instance.__shareable__, threading.Shareable.IMMUTABLE)
            self.assertIs(type(instance).__shareable__, threading.Shareable.LOCAL)
            namespace = {}
            exec('def probe():\n' + textwrap.indent(body, '    '), namespace)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(operation=body, group=group):
                    # The first element gives the expected access result;
                    # the code obtains the method through the shared instance.
                    self.assertIs(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (method, instance, bytes), 0, 32),
                        group is sys.main_thread_group)

    def test_foreign_attribute_hooks(self):
        def hook(self, name):
            return 42

        cases = (
            {'__getattr__': hook},
            {'__getattribute__': hook},
            {'__getattribute__': hook, '__getattr__': hook},
        )

        def probe():
            assert source[1].missing == 42
            return True

        for methods in cases:
            instance = internal.make_immutable_special_method_instance(methods)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(methods=tuple(methods), group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe.__code__, group, (hook, instance, None), 0, 32),
                        group is sys.main_thread_group)

        # A LOCAL fallback hook must not prevent access to an existing value.
        instance = internal.make_immutable_special_method_instance(
            {'__getattr__': hook, 'present': 42})

        def existing():
            assert source[1].present == 42
            return True

        self.assertTrue(internal.threadgroup_vm_probe(
            existing.__code__, self.foreign, (None, instance, None), 0, 32))

    def test_foreign_builtin_class_receiver(self):
        instance = internal.make_immutable_special_method_instance({})
        for expression in ('source[1].__init_subclass__()',
                           'source[1].__subclasshook__(source[2])'):
            namespace = {}
            exec(f'def probe():\n    {expression}\n    return True', namespace)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(expression=expression, group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (type(instance), instance, object), 0, 32),
                        group is sys.main_thread_group)

    def test_foreign_builtin_defining_class(self):
        clinic = import_helper.import_module('_testclinic')
        instance = internal.make_immutable_call_receiver(clinic.TestClass)

        bodies = (
            'source[1].get_defining_class_arg(None)',
            'method = source[1].get_defining_class_arg\nmethod(None)',
        )
        for body in bodies:
            namespace = {}
            exec('def probe():\n' + textwrap.indent(body, '    ') +
                 '\n    return True', namespace)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(body=body, group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (clinic.TestClass, instance, None), 0, 32),
                        group is sys.main_thread_group)

    def test_builtin_bound_receiver_acquisition(self):
        capi = import_helper.import_module('_testcapi')
        cases = (
            ('meth_noargs', ''),
            ('meth_o', 'None'),
            ('meth_fastcall', 'None'),
            ('meth_fastcall_keywords', 'None'),
            ('meth_fastcall_keywords', 'key=None'),
            ('meth_varargs', 'None'),
            ('meth_varargs_keywords', 'key=None'),
        )
        for name, args in cases:
            namespace = {}
            exec(f'def probe():\n    bound_builtin({args})\n    return True',
                 namespace)
            for value in ([], None):
                for group in (sys.main_thread_group, self.foreign):
                    for warmups in (0, 64):
                        with self.subTest(name=name, args=args, value=value,
                                          group=group, warmups=warmups):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__, group,
                                (value, None, None), warmups, 32, False,
                                getattr(capi, name)),
                                value is None or group is sys.main_thread_group)

    @requires_specialization
    def test_builtin_bound_receiver_specializations(self):
        capi = import_helper.import_module('_testcapi')
        cases = (
            ('meth_o', 'CALL_BUILTIN_O'),
            ('meth_fastcall', 'CALL_BUILTIN_FAST'),
            ('meth_fastcall_keywords', 'CALL_BUILTIN_FAST_WITH_KEYWORDS'),
        )
        for name, opcode in cases:
            with self.subTest(name=name):
                def probe():
                    bound_builtin(None)
                    return True

                accessible, bytecode = internal.threadgroup_vm_probe(
                    probe.__code__, self.foreign, ([], None, None),
                    64, 32, True, getattr(capi, name))
                self.assertFalse(accessible)
                self.assertIn(opcode, {
                    instruction.opname
                    for instruction in dis._get_instructions_bytes(bytecode)})

    def test_foreign_descriptor_get(self):
        def get(self, instance, owner):
            return 42

        descriptor = internal.make_immutable_special_method_instance(
            {'__get__': get})
        for expression in ('cls.descriptor', 'cls().descriptor'):
            namespace = {}
            exec('def probe():\n    cls.descriptor = source[1]\n'
                 f'    assert {expression} == 42\n    return True', namespace)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(expression=expression, group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (get, descriptor, None), 0, 32),
                        group is sys.main_thread_group)

    def check_bound_method_calls(self, warmups, specialized=False):
        cases = (
            ('method(None)', 'CALL_BOUND_METHOD_EXACT_ARGS'),
            ('method()', 'CALL_BOUND_METHOD_GENERAL'),
            ('method(arg=None)', 'CALL_KW_BOUND_METHOD'),
            ('method(*(None,))', None),
            ('method(**{"arg": None})', None),
        )

        def consume(self, arg=None):
            return True

        for foreign_field in ('self', 'function'):
            binding = ('bind_method(module.consume, source)' if foreign_field == 'self'
                       else 'bind_method(module.consume, (None,), source)')
            for call, opcode in cases:
                namespace = {}
                exec(textwrap.dedent(f'''
                    def probe():
                        if module.__dict__.get('consume') is None:
                            def consume(self, arg=None):
                                return True
                            module.consume = consume
                        method = {binding}
                        {call}
                        return True
                '''), namespace)
                for value in (object() if foreign_field == 'self' else consume, None):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(field=foreign_field, call=call,
                                          control=value is None, group=group):
                            accessible, bytecode = internal.threadgroup_vm_probe(
                                namespace['probe'].__code__.replace(), group,
                                (value, None, None), warmups, 1, True)
                            self.assertIs(accessible,
                                          value is None or group is sys.main_thread_group)
                            if specialized and opcode is not None:
                                self.assertIn(opcode, {
                                    instruction.opname for instruction in
                                    dis._get_instructions_bytes(bytecode)})

    def test_bound_method_calls(self):
        self.check_bound_method_calls(0)

    @requires_specialization
    def test_specialized_bound_method_calls(self):
        self.check_bound_method_calls(64, specialized=True)

    def test_bound_method_metadata(self):
        def target(self):
            return True

        cases = (
            ('function', 'method.__doc__'),
            ('function', 'method.__name__'),
            ('function', 'method.__repr__()'),
            ('function', 'method.__hash__()'),
            ('function', 'method == other'),
            ('function', 'method != other'),
            ('function', 'other == method'),
            ('function', 'method.__reduce__()'),
            ('self', 'method.__repr__()'),
            ('self', 'method.__reduce__()'),
        )
        for field, expression in cases:
            binding = ('bind_method(local, source)' if field == 'self'
                       else 'bind_method(local, (None,), source)')
            namespace = {}
            exec(textwrap.dedent(f'''
                def probe():
                    __builtins__['getattr'] = consumer
                    def __private(self):
                        return True
                    local = __private
                    method = {binding}
                    other = bind_method(local, (None,))
                    {expression}
                    return True
            '''), namespace)
            for value in (object() if field == 'self' else target, None):
                for group in (sys.main_thread_group, self.foreign):
                    for warmups in (0, 32):
                        with self.subTest(field=field, expression=expression,
                                          control=value is None, group=group,
                                          warmups=warmups):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__.replace(), group,
                                (value, None, None), warmups),
                                value is None or group is sys.main_thread_group)

    def test_eval_function_metadata_acquisition(self):
        limited = import_helper.import_module('_testlimitedcapi')

        class Name(str):
            pass

        def target(self):
            return True

        code = target.__code__.replace(co_name=Name('stored_name'))
        instance = internal.make_immutable_special_method_instance({})
        cases = (
            ('bound function', target,
             'bind_method(local, (None,), source[1])', 'target', '()', True),
            ('stored name', code, 'local', 'stored_name', '()', True),
            ('instance class', instance, 'source[1][0]',
             limited.eval_get_func_name(instance), ' object', True),
            ('bound receiver', object(), 'bind_method(local, source[1])',
             'local', '()', False),
        )
        for case, value, expression, name, desc, reads_field in cases:
            namespace = {}
            exec(textwrap.dedent(f'''
                def probe():
                    def local(self):
                        return True
                    value = {expression}
                    try:
                        actual = bound_builtin(value)
                    except source[2]:
                        assert source[1][1] is None
                    else:
                        assert actual == source[1][1]
                    return True
            '''), namespace)
            probe_code = namespace['probe'].__code__
            if case == 'stored name':
                # MAKE_FUNCTION copies this code's stored name without an
                # explicit function.__new__ call or its separate audit event.
                probe_code = probe_code.replace(co_consts=tuple(
                    code if isinstance(const, type(code)) and const.co_name == 'local'
                    else const for const in probe_code.co_consts))
            for getter, result in ((limited.eval_get_func_name, name),
                                   (limited.eval_get_func_desc, desc)):
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(case=case, getter=getter.__name__, group=group):
                        expected = result
                        if (getter is limited.eval_get_func_name and reads_field
                                and group is self.foreign):
                            expected = None
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe_code, group,
                            (True, (value, expected), IllegalThreadAccessException),
                            0, 1, False, getter))

    def test_bound_method_private_name_owner(self):
        def probe():
            __builtins__['getattr'] = consumer

            def __private(self):
                return True

            method = bind_method(__private, (source[1],))
            method.__reduce__()
            return True

        instance = internal.make_immutable_special_method_instance({})
        for value in (instance, 42):
            for group in (sys.main_thread_group, self.foreign):
                for warmups in (0, 32):
                    with self.subTest(value=value, group=group, warmups=warmups):
                        self.assertIs(internal.threadgroup_vm_probe(
                            probe.__code__.replace(), group,
                            (type(value), value, None), warmups),
                            value is not instance or group is sys.main_thread_group)

    def test_bound_method_unaccessed_fields(self):
        def target(self):
            return True

        def probe():
            __builtins__['getattr'] = consumer

            def local(self):
                "local doc"
                return True

            method = bind_method(local, source[1])
            other = bind_method(local, source[1])
            assert method.__doc__ == 'local doc'
            assert method.__name__ == 'local'
            # These operations use only the receiver's identity or copy its
            # heap reference. None exposes it as a thread-owned reference.
            assert method == other
            assert method.__hash__() == other.__hash__()
            reduced = method.__reduce__()
            assert reduced[0] is consumer
            assert reduced[1].__len__() == 2
            # Getting __self__ likewise does not acquire the stored function.
            method = bind_method(local, (None,), source[2])
            assert method.__self__ is None
            return True

        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, group, (True, (object(),), (target,)), 0))

    def test_instance_method_acquisition(self):
        def target(*args, **kwargs):
            return True

        expressions = (
            'method()',
            'method(None)',
            'method(arg=None)',
            'method(*(None,))',
            'method(**{"arg": None})',
            'method.__doc__',
            'method.__name__',
            'method.__repr__()',
            'method == other',
            'method != other',
            'other == method',
            'method.__func__',
            'method.__get__(None, cls)',
        )
        for expression in expressions:
            namespace = {}
            exec(textwrap.dedent(f'''
                def probe():
                    def local(*args, **kwargs):
                        return True
                    method = bind_method(local, (), source)
                    other = bind_method(local, ())
                    {expression}
                    return True
            '''), namespace)
            for value in (target, None):
                for group in (sys.main_thread_group, self.foreign):
                    for warmups in (0, 32):
                        with self.subTest(expression=expression, group=group,
                                          control=value is None, warmups=warmups):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__.replace(), group,
                                (value, None, None), warmups),
                                value is None or group is sys.main_thread_group)

    def test_instance_method_binding_copies_function(self):
        def target(self):
            return True

        def probe():
            cls.method = bind_method(consumer, (), source[1])
            instance = cls()
            # Binding only copies the descriptor's stored reference. Calling
            # the resulting bound method must acquire the function later.
            method = instance.method
            assert method.__self__ is instance
            try:
                method()
            except source[2]:
                return True
            assert False, 'calling must reject the stored foreign function'

        self.assertTrue(internal.threadgroup_vm_probe(
            probe.__code__, self.foreign,
            (True, (target,), IllegalThreadAccessException), 0))

    def check_c_call_results(self, warmups, specialized=False):
        cases = (
            ("mapping.get('value')", 'CALL_METHOD_DESCRIPTOR_FAST'),
            ('box.get_noargs()', 'CALL_METHOD_DESCRIPTOR_NOARGS'),
            ('box.get_o(None)', 'CALL_METHOD_DESCRIPTOR_O'),
            ('box.get_fast(None)', 'CALL_METHOD_DESCRIPTOR_FAST'),
            ('box.get_keywords(None)', 'CALL_METHOD_DESCRIPTOR_FAST_WITH_KEYWORDS'),
            ('method = box.get_o\nmethod(None)', 'CALL_BUILTIN_O'),
            ('method = box.get_fast\nmethod(None)', 'CALL_BUILTIN_FAST'),
            ('method = box.get_keywords\nmethod(None)', 'CALL_BUILTIN_FAST_WITH_KEYWORDS'),
            ('box.__class__(box)', 'CALL_BUILTIN_CLASS'),
        )
        for body, opcode in cases:
            with self.subTest(body=body):
                namespace = {}
                exec('def probe():\n' + textwrap.indent(body, '    ') +
                     '\n    return True', namespace)
                self.check_vm_code(namespace['probe'].__code__, warmups,
                                   opcode if specialized else None)

        # type() also acquires a new reference, even for an immutable instance.
        instance = internal.make_immutable_special_method_instance({})

        def probe_type():
            type_ = cls.__class__
            type_(source[1])
            return True

        for value in (instance, 42):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(type_of=type(value), group=group):
                    accessible, bytecode = internal.threadgroup_vm_probe(
                        probe_type.__code__.replace(), group,
                        (type(value), value, None), warmups, 1, True)
                    self.assertIs(accessible,
                                  value is not instance or group is sys.main_thread_group)
                    if specialized:
                        self.assertIn('CALL_TYPE_1', {
                            instruction.opname
                            for instruction in dis._get_instructions_bytes(bytecode)})

    def test_vm_c_call_results(self):
        self.check_c_call_results(0)

    @requires_specialization
    def test_vm_specialized_c_call_results(self):
        self.check_c_call_results(64, specialized=True)

    def test_attribute_hook_descriptor_result(self):
        def hook(name):
            return 42

        def probe():
            assert source[1].missing == 42
            return True

        for name in ('__getattr__', '__getattribute__'):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(hook=name, group=group):
                    descriptor = internal.make_access_descriptor(hook, True)
                    methods = {'__getattr__': descriptor, name: descriptor}
                    instance = internal.make_immutable_special_method_instance(
                        methods)
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe.__code__, group, (hook, instance, None), 0, 32),
                        group is sys.main_thread_group)
                    # Binding is allowed, but the returned LOCAL callable
                    # must be checked before it is invoked.
                    self.assertEqual(internal.access_descriptor_calls(descriptor),
                                     32)

    @requires_specialization
    def test_foreign_specialized_getitem(self):
        def getitem(self, key):
            return 42

        instance = internal.make_immutable_special_method_instance(
            {'__getitem__': getitem})

        def probe():
            return source[1][0] == 42

        values = (getitem, instance, bytes)
        accessible, bytecode = internal.threadgroup_vm_probe(
            probe.__code__, sys.main_thread_group, values, 0, 64, True)
        self.assertTrue(accessible)
        self.assertIn('BINARY_OP_SUBSCR_GETITEM', {
            instruction.opname
            for instruction in dis._get_instructions_bytes(bytecode)})
        # The type cache remains populated after the first worker exits.
        self.assertFalse(internal.threadgroup_vm_probe(
            probe.__code__, self.foreign, values, 0, 128))

    def test_vm_repeated_rejected_attribute(self):
        # Changing a class attribute invalidates its old type cache. Keep
        # trying after rejection so respecialization cannot bypass the check.
        for name in ('box', 'instance', 'cls', 'module'):
            with self.subTest(name=name):
                namespace = {}
                exec(f'def probe():\n    return {name}.value is None', namespace)
                self.assertFalse(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (object(), None, None), 64, 128))

    def test_vm_cell_load(self):
        value = None

        def probe():
            return value is None

        for warmups in (0, 64):
            with self.subTest(warmups=warmups):
                self.check_vm_code(probe.__code__, warmups)

    def test_vm_default_arguments(self):
        def positional(value=None, b=None, c=None):
            return value is None

        def keyword(*, value=None):
            return value is None

        for probe in (positional, keyword):
            for warmups in (0, 64):
                with self.subTest(probe=probe.__name__, warmups=warmups):
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
