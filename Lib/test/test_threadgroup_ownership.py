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
    Py_DEBUG, Py_GIL_DISABLED, import_helper, nomemtest, requires_specialization,
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

    def test_immutable_declaration_requires_shareable_class(self):
        capi = import_helper.import_module('_testlimitedcapi')

        class Meta(type):
            pass

        class Value(metaclass=Meta):
            __slots__ = ()

        value = Value()
        # A read-only type definition does not opt into cross-group sharing.
        capi.type_freeze(Meta)
        capi.type_freeze(Value)
        for obj in (value, Value):
            with self.subTest(object=obj):
                with self.assertRaises(TypeError):
                    internal.object_declare_immutable(obj)
                self.assertIs(obj.__shareable__, threading.Shareable.LOCAL)
                self.check_access(obj, False)

        # Declare the metaclass, class and instance in dependency order.
        for obj in (Meta, Value, value):
            with self.subTest(object=obj):
                self.assertIsNone(internal.object_declare_immutable(obj))
                self.assertIsNone(internal.object_declare_immutable(obj))
                self.assertIs(obj.__shareable__, threading.Shareable.IMMUTABLE)
                self.check_access(obj, True)

    def test_immutable_declaration_rejects_local_extension_class(self):
        clinic = import_helper.import_module('_testclinic')
        value = clinic.TestClass()
        with self.assertRaisesRegex(TypeError, 'class is not shareable'):
            internal.object_declare_immutable(value)
        self.assertIs(value.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(clinic.TestClass.__shareable__, threading.Shareable.LOCAL)
        self.check_access(value, False)

    def test_template_shallow_immutability(self):
        from string.templatelib import Interpolation, Template

        def probe():
            template, interpolation = source[1]
            local, immutable, error = source[2]
            assert template.__shareable__ is immutable
            assert interpolation.__shareable__ is immutable
            assert template.__iter__().__shareable__ is local
            assert template.interpolations[0] is interpolation
            # Copying references into another immutable tuple is permitted.
            values = template.values
            assert values.__len__() == 1
            try:
                values[0]
            except error:
                pass
            else:
                assert False
            own_value = []
            own_template = t'{own_value}'
            assert own_template.__shareable__ is immutable
            assert own_template.interpolations[0].__shareable__ is immutable
            assert own_template.values[0] is own_value
            return True

        value = internal.make_container_element(False)
        interpolation = Interpolation(value)
        template = Template(interpolation)
        for item in (interpolation, template, t'{value}', Template('text')):
            self.check_access(item, True)
        self.assertTrue(internal.threadgroup_vm_probe(
            probe.__code__, self.foreign,
            (True, (template, interpolation),
             (threading.Shareable.LOCAL, threading.Shareable.IMMUTABLE,
              IllegalThreadAccessException)), 0))
        self.assertEqual(internal.container_element_calls(value), 0)

    def test_interpolation_reference_acquisition(self):
        from string.templatelib import Interpolation

        class String(str):
            pass

        def probe():
            interpolation = source[1]
            field, operation, error, rejected, expected = source[2]
            try:
                if operation == 'repr':
                    assert bound_builtin(interpolation) == expected
                else:
                    interpolation.__getattribute__(field)
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        fields = ('value', 'expression', 'conversion', 'format_spec')
        for index, field in enumerate(fields):
            for immutable in (False, True):
                value = (internal.make_container_element(immutable) if index == 0
                         else ('r' if immutable else String('r')))
                args = [1, 'x', None, '']
                args[index] = value
                interpolation = Interpolation(*args)
                expected = repr(interpolation)
                for operation in ('getattr', 'repr'):
                    for group in (sys.main_thread_group, self.foreign):
                        rejected = not immutable and group is self.foreign
                        before = internal.container_element_calls(value) if index == 0 else 0
                        with self.subTest(field=field, immutable=immutable,
                                          operation=operation, group=group):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe.__code__, group,
                                (True, interpolation, (field, operation,
                                 IllegalThreadAccessException, rejected, expected)),
                                0, 1, False, repr))
                            if index == 0:
                                calls = before + (operation == 'repr' and not rejected)
                                self.assertEqual(internal.container_element_calls(value), calls)

    def test_template_string_acquisition(self):
        from string.templatelib import Interpolation, Template

        class String(str):
            pass

        def probe():
            template, suffix, opaque = source[1]
            operation, error, rejected = source[2]
            # An unexamined prefix can be copied through concatenation.
            copied = opaque + suffix
            assert copied.strings.__len__() == 2
            assert copied.strings[1] == 'tail!'
            try:
                if operation == 'concat left':
                    template + suffix
                elif operation == 'concat right':
                    suffix + template
                elif operation == 'iter':
                    template.__iter__().__next__()
                else:
                    template.__repr__()
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        for value in ('text', String('text')):
            values = (Template(value), Template('!'),
                      Template(value, Interpolation(1), 'tail'))
            for operation in ('concat left', 'concat right', 'iter', 'repr'):
                for group in (sys.main_thread_group, self.foreign):
                    rejected = type(value) is String and group is self.foreign
                    with self.subTest(value_type=type(value), operation=operation,
                                      group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, values,
                             (operation, IllegalThreadAccessException, rejected)), 0))

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

    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_orphan_tuple_decref(self):
        for merged in (False, True):
            for keep_owner in (False, True):
                with self.subTest(merged=merged, keep_owner=keep_owner):
                    group = threading.ThreadGroup('departed tuple owner')
                    internal.threadgroup_orphan_decref_probe(
                        group, merged, keep_owner)

    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_orphan_cycle_reclamation(self):
        for merged in (False, True):
            for keep_owner in (False, True):
                for finalizer in (False, True):
                    with self.subTest(merged=merged, keep_owner=keep_owner,
                                      finalizer=finalizer):
                        group = threading.ThreadGroup('departed cycle owner')
                        internal.threadgroup_orphan_decref_probe(
                            group, merged, keep_owner, True, finalizer)

    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_native_reclamation_with_live_owner(self):
        for foreign in (False, True):
            for cyclic in (False, True):
                for finalizer in (False, True):
                    with self.subTest(foreign=foreign, cyclic=cyclic,
                                      finalizer=finalizer):
                        _, _, err = script_helper.assert_python_ok(
                            '-c', textwrap.dedent(f'''
                                import _testinternalcapi as internal
                                import sys
                                import threading

                                group = (threading.ThreadGroup('live owner')
                                         if {foreign} else sys.main_thread_group)
                                class Stderr:
                                    def write(self, text):
                                        raise AssertionError('logging ran Python')
                                stderr = sys.stderr
                                sys.stderr = Stderr()
                                try:
                                    internal.threadgroup_orphan_decref_probe(
                                        group, True, True, {cyclic}, {finalizer}, True)
                                finally:
                                    sys.stderr = stderr
                            '''))
                        if foreign:
                            self.assertEqual(err.count(b'calling tp_dealloc:'), 1, err)
                            self.assertEqual(err.count(b'calling tp_clear:'), cyclic, err)
                            self.assertEqual(err.count(b'calling tp_finalize:'),
                                             cyclic and finalizer, err)
                        else:
                            self.assertEqual(err, b'')

    @unittest.skipIf(Py_GIL_DISABLED, "requires the normal-build group BRC port")
    def test_orphan_adoption_race(self):
        for _ in range(20):
            internal.threadgroup_adoption_race(
                threading.ThreadGroup('departed owner'),
                threading.ThreadGroup('first contender'),
                threading.ThreadGroup('second contender'))

    def test_foreign_finalization_callbacks(self):
        source = '''
del_events = []
weak_events = []
def finalize(self):
    del_events.append(None)
def callback(ref):
    weak_events.append(ref() is None)
namespace = {'__del__': finalize}
value = type('Finalized', (), namespace)()
if cyclic:
    value.cycle = value
'''
        configurations = ((False, False), (True, False), (False, True))
        for shared_callback, shared_class in configurations:
            for foreign in (False, True):
                for cyclic in (False, True):
                    for keep_owner in (False, True):
                        with self.subTest(foreign=foreign, cyclic=cyclic,
                                          keep_owner=keep_owner,
                                          shared_callback=shared_callback,
                                          shared_class=shared_class):
                            _, _, err = script_helper.assert_python_ok(
                                '-c', textwrap.dedent(f'''
                                    import _testinternalcapi as internal
                                    import sys
                                    import threading

                                    errors = []
                                    sys.unraisablehook = lambda info: errors.append(info)
                                    group = (threading.ThreadGroup('finalization owner')
                                             if {foreign} else sys.main_thread_group)
                                    code = compile({source!r}, '<finalization probe>', 'exec')
                                    class Stderr:
                                        def write(self, text):
                                            raise AssertionError('logging ran Python')
                                    stderr = sys.stderr
                                    sys.stderr = Stderr()
                                    try:
                                        result = internal.threadgroup_finalization_probe(
                                            code, group, {cyclic}, {keep_owner},
                                            {shared_callback}, {shared_class})
                                    finally:
                                        sys.stderr = stderr
                                    assert result == {(0, 0, 1) if foreign else (1, 1, 1)}, result
                                    assert not errors, errors
                                '''))
                            if foreign:
                                self.assertEqual(err.count(b'skipping __del__:'), 1, err)
                                self.assertEqual(err.count(b'skipping weakref callback:'), 1, err)
                            else:
                                self.assertEqual(err, b'')

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

    def test_function_docstring_acquisition(self):
        # Regrtest's Main-owned audit hook otherwise rejects function.__new__
        # before it reaches the code object's docstring in the foreign group.
        script_helper.assert_python_ok('-m', 'unittest',
            f'{__name__}.OwnershipTests._check_function_docstring_acquisition')

    def _check_function_docstring_acquisition(self):
        import inspect

        class String(str):
            pass

        class Tuple(tuple):
            pass

        def target():
            'docstring'
            return 42

        operations = {
            'constructor': 'created = local.__class__(source[1], {})',
            'MAKE_FUNCTION': 'def created():\n    return 42',
        }
        cases = (
            ('exact string', 'docstring', False),
            ('string subclass', String('docstring'), False),
            ('local non-string', object(), False),
            ('immutable non-string', 1, False),
            ('tuple subclass', 'docstring', True),
        )
        for case, doc, tuple_subclass in cases:
            consts = (doc,) + target.__code__.co_consts[1:]
            if tuple_subclass:
                consts = Tuple(consts)
            local = tuple_subclass or doc.__shareable__ is threading.Shareable.LOCAL
            for has_docstring in (False, True):
                flags = target.__code__.co_flags
                if not has_docstring:
                    flags &= ~inspect.CO_HAS_DOCSTRING
                code = target.__code__.replace(co_consts=consts, co_flags=flags)
                expected = 'docstring' if has_docstring and isinstance(doc, str) else None
                for operation, statement in operations.items():
                    namespace = {}
                    exec('def probe():\n'
                         '    def local():\n        pass\n'
                         '    error, rejected, expected = source[2]\n'
                         '    for attempt in (0, 1):\n'
                         '        try:\n' + textwrap.indent(statement, '            ') + '\n'
                         '        except error:\n            assert rejected\n'
                         '        else:\n'
                         '            assert not rejected\n'
                         '            assert created.__doc__ == expected\n'
                         '    return True', namespace)
                    probe_code = namespace['probe'].__code__
                    if operation == 'MAKE_FUNCTION':
                        probe_code = probe_code.replace(co_consts=tuple(
                            code if isinstance(item, type(code)) and item.co_name == 'created'
                            else item for item in probe_code.co_consts))
                    for group in (sys.main_thread_group, self.foreign):
                        rejected = local and has_docstring and group is self.foreign
                        with self.subTest(case=case, docstring=has_docstring,
                                          operation=operation, group=group):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe_code, group,
                                (True, code, (IllegalThreadAccessException,
                                             rejected, expected)), 0))

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
            'PyContextVar_Get_default', 'PyContextVar_Get_cached',
            'PyContextVar_Get_uncached',
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

    def test_function_module_acquisition(self):
        def probe():
            constructor, error, rejected = source[2]
            def callback():
                return constructor('marker')
            try:
                if constructor is None:
                    bound_builtin(source[1])
                else:
                    bound_builtin(source[1], callback)
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        for carrier in ((), (None,), (42,), (object(),)):
            for constructor in (None, sentinel):
                for group in (sys.main_thread_group, self.foreign):
                    rejected = (group is self.foreign and carrier and
                                type(carrier[0]) is object)
                    with self.subTest(carrier=carrier, constructor=constructor,
                                      group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, carrier, (constructor,
                             IllegalThreadAccessException, bool(rejected))),
                            0, 1, False, internal.function_reference_probe))

    def test_function_module_consumers(self):
        import _typing

        type Alias = Alias.__module__
        callbacks = (
            sys._getframemodulename,
            lambda: sentinel('marker'),
            lambda: _typing.TypeVar('T'),
            lambda: _typing.ParamSpec('P'),
            lambda: _typing.TypeVarTuple('Ts'),
            lambda: _typing.TypeAliasType('Marker', int),
            Alias.evaluate_value,
        )
        # The immutable carrier lets Main hold a foreign LOCAL number without
        # acquiring it. All functions and consumers here belong to Main.
        foreign = internal.threadgroup_number_source(self.foreign, int)
        for carrier in ((), (None,), (42,), foreign):
            for callback in callbacks:
                with self.subTest(foreign=carrier is foreign, callback=callback):
                    if carrier is foreign:
                        with self.assertRaises(IllegalThreadAccessException):
                            internal.function_reference_probe(carrier, callback)
                    else:
                        internal.function_reference_probe(carrier, callback)

    def test_function_reference_acquisition(self):
        class LocalTuple(tuple):
            pass

        def probe():
            field, error, rejected, attribute = source[2]
            def callback():
                return callback.__annotations__
            try:
                bound_builtin(source[1], callback if attribute else None, field)
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        fields = {
            'globals': ({},),
            'defaults': ((), LocalTuple()),
            'kwdefaults': ({},),
            'closure': ((), LocalTuple()),
            'annotations': ({},),
            'annotate': (lambda format: {},),
        }
        for field, values in fields.items():
            for value in values:
                attributes = (False, True) if field in ('annotations', 'annotate') else (False,)
                for attribute in attributes:
                    for group in (sys.main_thread_group, self.foreign):
                        rejected = not internal.threadgroup_access_probe(group, value)
                        with self.subTest(field=field, type=type(value), group=group,
                                          attribute=attribute):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe.__code__, group,
                                (True, (value,), (field, IllegalThreadAccessException,
                                 rejected, attribute)), 0, 1, False,
                                internal.function_reference_probe))

    def test_function_annotation_tuple_acquisition(self):
        def probe():
            field, error, rejected, attribute = source[2]
            def callback():
                return callback.__annotations__
            try:
                bound_builtin(source[1], callback if attribute else None, field)
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        for key in (False, True):
            for immutable in (False, True):
                for attribute in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        value = internal.make_container_element(immutable)
                        pair = (value, None) if key else ('annotation', value)
                        annotations = ('first', 0) + pair
                        rejected = key and not immutable and group is self.foreign
                        with self.subTest(key=key, immutable=immutable, group=group,
                                          attribute=attribute):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe.__code__, group,
                                (True, (annotations,), ('annotations',
                                 IllegalThreadAccessException, rejected, attribute)),
                                0, 1, False, internal.function_reference_probe))
                            self.assertEqual(internal.container_element_calls(value),
                                             int(key and not rejected))

    def test_type_reference_returns(self):
        def get_class():
            source[1].__class__
            return True

        def call_type():
            source[2](source[1])
            return True

        for value in (internal.make_container_element(True), 42):
            cls = type(value)
            shared_type = cls.__shareable__ is threading.Shareable.IMMUTABLE
            self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)
            for group in (sys.main_thread_group, self.foreign):
                accessible = shared_type or group is sys.main_thread_group
                with self.subTest(cls=cls, group=group):
                    self.assertIs(internal.threadgroup_return_probe(
                        (cls, frozendict(value=value)), group, 'PyObject_Type'),
                        accessible)
                    for code in (get_class.__code__, call_type.__code__):
                        self.assertIs(internal.threadgroup_vm_probe(
                            code, group, (cls, value, type), 0), accessible)

    def test_type_dictionary_returns(self):
        def get_proxy():
            source[1].__dict__
            return True

        for cls in (int, list, type):
            self.assertIs(cls.__shareable__, threading.Shareable.IMMUTABLE)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(cls=cls, group=group):
                    self.assertIs(internal.threadgroup_return_probe(
                        (cls, frozendict()), group, 'PyType_GetDict'),
                        group is sys.main_thread_group)
                    self.assertIs(internal.threadgroup_vm_probe(
                        get_proxy.__code__, group, (object(), cls, None), 0),
                        group is sys.main_thread_group)

    def test_mappingproxy_creation(self):
        capi = import_helper.import_module('_testlimitedcapi')
        proxy_type = type(type.__dict__)

        def local_mapping():
            cls.value = 1
            proxy = cls.__dict__
            assert proxy['value'] == 1
            cls.value = 2
            assert proxy['value'] == 2

            mapping = {'value': 1}
            for proxy in (source[2](mapping), bound_builtin(mapping)):
                assert proxy.__shareable__ is source[1]
                assert proxy['value'] == mapping['value']
                mapping['value'] += 1
                assert proxy['value'] == mapping['value']
            return True

        def immutable_mapping():
            proxy = source[2](source[1])
            proxy['value']
            return True

        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                self.assertTrue(internal.threadgroup_vm_probe(
                    local_mapping.__code__, group,
                    (True, threading.Shareable.LOCAL, proxy_type),
                    0, 1, False, capi.dictproxy_new))
                for value in (42, object()):
                    # The immutable mapping is shareable; its contents may
                    # still belong to another group and need checked getters.
                    self.assertIs(internal.threadgroup_vm_probe(
                        immutable_mapping.__code__, group,
                        (value, frozendict(value=value), proxy_type), 0),
                        type(value) is int or group is sys.main_thread_group)

    def test_type_name_returns(self):
        class String(str):
            pass

        for api in ('PyType_GetName', 'PyType_GetQualName',
                    'PyType_GetFullyQualifiedName', 'PyType_GetModuleName'):
            for value in ('stored_name', String('stored_name')):
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(api=api, value_type=type(value), group=group):
                        self.assertIs(internal.threadgroup_return_probe(
                            (value, frozendict(value='_testinternalcapi.stored_name')),
                            group, api), type(value) is str or
                            group is sys.main_thread_group)

    def test_type_name_format_acquisition(self):
        capi = import_helper.import_module('_testlimitedcapi')

        def probe():
            error, rejected, position, expected = source[2]
            try:
                if position == 0:
                    bound_builtin(source[1], '')
                else:
                    bound_builtin('', source[1])
            except error:
                assert rejected
            except TypeError as exc:
                assert not rejected
                assert exc.__str__() == expected
            else:
                assert False
            return True

        for value in (internal.make_immutable_special_method_instance({}),
                      internal.make_immutable_call_receiver(object)):
            local_type = type(value).__shareable__ is threading.Shareable.LOCAL
            for position, ordinal in enumerate(('first', 'second')):
                expected = f'{ordinal} argument must be str, not {type(value).__name__}'
                for group in (sys.main_thread_group, self.foreign):
                    rejected = local_type and group is self.foreign
                    with self.subTest(local_type=local_type, position=position,
                                      group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, value, (IllegalThreadAccessException,
                             rejected, position, expected)),
                            0, 1, False, capi.unicode_equal))

    def test_object_repr_type_acquisition(self):
        def probe():
            error, rejected, expected, converter = source[2]
            try:
                actual = (bound_builtin(source[1]) if converter is None
                          else converter(source[1]))
            except error:
                assert rejected
            else:
                assert not rejected
                assert actual == expected
            return True

        for value in (internal.make_immutable_special_method_instance({}),
                      internal.make_immutable_call_receiver(object)):
            local_type = type(value).__shareable__ is threading.Shareable.LOCAL
            expected = repr(value)
            for operation in (repr, str):
                for group in (sys.main_thread_group, self.foreign):
                    rejected = local_type and group is self.foreign
                    with self.subTest(local_type=local_type,
                                      operation=operation, group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, value, (IllegalThreadAccessException,
                             rejected, expected, str if operation is str else None)),
                            0, 1, False, repr))

    def test_unicode_error_type_acquisition(self):
        capi = import_helper.import_module('_testlimitedcapi')
        cases = (
            ('bound_builtin(source[1])', capi.unicode_fromobject),
            ("bound_builtin(source[1], '')", capi.unicode_compare),
            ("bound_builtin('', source[1])", capi.unicode_compare),
            ("bound_builtin('', source[1])", capi.unicode_concat),
            ("source[1] in 'text'", None),
            ("'text'.center(8, source[1])", None),
            ("'text'.ljust(8, source[1])", None),
            ("'text'.rjust(8, source[1])", None),
            ("'text'.split(source[1])", None),
            ("'text'.rsplit(source[1])", None),
            ("''.join(('text', source[1]))", None),
            ("bound_builtin(source[1], ('text', 'suffix'))", capi.unicode_join),
            ("'text'.startswith(source[1])", None),
            ("'text'.endswith(source[1])", None),
            ("'text'.startswith(('nomatch', source[1]))", None),
            ("'text'.endswith(('nomatch', source[1]))", None),
        )
        for value in (internal.make_immutable_special_method_instance({}),
                      internal.make_immutable_call_receiver(object)):
            local_type = type(value).__shareable__ is threading.Shareable.LOCAL
            for expression, builtin in cases:
                # Keep the ordinary error text, including legacy type names.
                with self.assertRaises(TypeError) as cm:
                    eval(expression, {'source': (True, value),
                                      'bound_builtin': builtin})
                expected = str(cm.exception)
                namespace = {}
                exec('def probe():\n'
                     '    error, rejected, expected = source[2]\n'
                     '    try:\n        ' + expression + '\n'
                     '    except error:\n        assert rejected\n'
                     '    except TypeError as exc:\n'
                     '        assert not rejected\n'
                     '        assert exc.__str__() == expected\n'
                     '    else:\n        assert False\n'
                     '    return True', namespace)
                for group in (sys.main_thread_group, self.foreign):
                    rejected = local_type and group is self.foreign
                    with self.subTest(expression=expression, local_type=local_type,
                                      group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__, group,
                            (True, value, (IllegalThreadAccessException,
                             rejected, expected)), 0, 1, False, builtin or repr))

    def test_unicode_error_skips_unused_types(self):
        capi = import_helper.import_module('_testlimitedcapi')

        def probe():
            value = source[1]
            assert bound_builtin(value, ()) == ''
            assert bound_builtin(value, ('text',)) == 'text'
            assert 'text'.startswith(('text', value))
            assert 'text'.endswith(('text', value))
            return True

        value = internal.make_immutable_special_method_instance({})
        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, group, (True, value, None),
                    0, 1, False, capi.unicode_join))

    def test_type_module_returns(self):
        for api in ('PyType_GetModule', 'PyType_GetModuleByDef',
                    'PyType_GetModuleByToken', 'PyType_GetModuleState'):
            # The token/definition APIs can also find an ancestor's module.
            positions = (0, 1) if api in (
                'PyType_GetModuleByDef', 'PyType_GetModuleByToken') else (0,)
            for position in positions:
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(api=api, inherited=position, group=group):
                        self.assertIs(internal.threadgroup_return_probe(
                            (internal, frozendict()), group, api, position),
                            group is sys.main_thread_group)

    def test_type_base_acquisition(self):
        class Base:
            pass

        def create_type():
            ctor, error, rejected = source[2]
            try:
                child = ctor('Child', source[1], {})
            except error:
                assert rejected
            else:
                assert not rejected
                assert child.__bases__ is source[1]
            return True

        for base in (Base, int, object(), 42):
            for group in (sys.main_thread_group, self.foreign):
                foreign = (group is self.foreign and
                           base.__shareable__ is threading.Shareable.LOCAL)
                error = IllegalThreadAccessException if foreign else TypeError
                rejected = foreign or not isinstance(base, type)
                with self.subTest(base=base, group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        create_type.__code__, group,
                        (True, (base,), (type, error, rejected)), 0))

    def test_capi_type_base_acquisition(self):
        capi = import_helper.import_module('_testlimitedcapi')

        class Base:
            pass

        def create_type():
            flags, from_slots, error, rejected = source[2]
            try:
                child = bound_builtin(source[1], flags, from_slots)
            except error:
                assert rejected
            else:
                assert not rejected
                assert child.__bases__ is source[1]
            return True

        # IMMUTABLETYPE prevents type mutation; it does not make a newly
        # created extension type shareable between ThreadGroups.
        fixed_base = capi.type_from_slots('flags')
        self.assertIs(fixed_base.__shareable__, threading.Shareable.LOCAL)
        for base in (Base, fixed_base, object):
            for flags in (False, True):
                for from_slots in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        foreign = group is self.foreign and base is not object
                        error = (IllegalThreadAccessException if foreign
                                 else TypeError)
                        rejected = foreign or (flags and base is Base)
                        with self.subTest(base=base, flags=flags,
                                          from_slots=from_slots, group=group):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                create_type.__code__, group,
                                (True, (base,), (flags, from_slots, error, rejected)),
                                0, 1, False, internal.threadgroup_type_from_bases))

    def test_type_set_bases_acquisition(self):
        # Regrtest's Main-local audit hook otherwise rejects __bases__ writes
        # before the setter reaches the base tuple.
        script_helper.assert_python_ok('-c', textwrap.dedent('''
            import sys
            import threading
            import _testinternalcapi as internal

            class Base:
                pass

            def replace_bases():
                ctor, error, rejected = source[2]
                child = ctor('Child', (cls,), {})
                old_bases = child.__bases__
                try:
                    child.__bases__ = source[1]
                except error:
                    assert rejected
                    assert child.__bases__ is old_bases
                else:
                    assert not rejected
                    assert child.__bases__ is source[1]
                return True

            foreign = threading.ThreadGroup('base replacement')
            for group in (sys.main_thread_group, foreign):
                for base in (Base, object()):
                    error = (IllegalThreadAccessException if group is foreign
                             else TypeError)
                    rejected = group is foreign or base is not Base
                    assert internal.threadgroup_vm_probe(
                        replace_bases.__code__, group,
                        (True, (base,), (type, error, rejected)), 0)
        '''))

    def test_mro_entries_base_acquisition(self):
        class Base:
            pass

        def create_type():
            ctor, error, rejected, explicit = source[2]

            def resolve(self, bases):
                return source[1]

            def body():
                pass

            entry = ctor('Entry', (), {'__mro_entries__': resolve})()
            try:
                if explicit:
                    child = bound_builtin(body, 'Child', entry, metaclass=ctor)
                else:
                    child = bound_builtin(body, 'Child', entry)
            except error:
                assert rejected
            else:
                assert not rejected
                assert child.__bases__ == source[1]
            return True

        for base in (Base, int):
            for explicit in (False, True):
                for group in (sys.main_thread_group, self.foreign):
                    rejected = group is self.foreign and base is Base
                    with self.subTest(base=base, explicit=explicit, group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            create_type.__code__, group,
                            (True, (base,),
                             (type, IllegalThreadAccessException, rejected, explicit)),
                            0, 1, False, builtins.__build_class__))

    def test_type_base_token_return(self):
        base, subtype = internal.make_immutable_subtype(tuple)
        self.assertIs(base.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(subtype.__shareable__, threading.Shareable.IMMUTABLE)

        def get_base():
            source[1].__base__
            return True

        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                self.assertIs(internal.threadgroup_vm_probe(
                    get_base.__code__, group, (base, subtype, None), 0),
                    group is sys.main_thread_group)
                for expected in (base, subtype):
                    with self.subTest(expected=expected):
                        self.assertIs(internal.threadgroup_return_probe(
                            (expected, frozendict(value=subtype)), group,
                            'PyType_GetBaseByToken'),
                            expected is subtype or group is sys.main_thread_group)

    def test_type_base_slot_returns(self):
        class Bases(tuple):
            pass

        for tuple_type in (tuple, Bases):
            base, subtype = internal.make_immutable_subtype(tuple_type)
            bases = subtype.__bases__
            self.assertIs(type(bases), tuple_type)
            for group in (sys.main_thread_group, self.foreign):
                for api, expected in (
                    ('PyType_GetSlot_base', base),
                    ('PyType_GetSlot_bases', bases),
                ):
                    with self.subTest(tuple_type=tuple_type, group=group, api=api):
                        shared = (expected.__shareable__ is
                                  threading.Shareable.IMMUTABLE)
                        self.assertIs(internal.threadgroup_return_probe(
                            (expected, frozendict(value=subtype)), group, api),
                            shared or group is sys.main_thread_group)

    def test_numeric_operator_slot_returns(self):
        unary = ('Negative', 'Positive', 'Invert', 'Absolute')
        binary = ('Add', 'Subtract', 'Multiply', 'MatrixMultiply', 'FloorDivide',
                  'TrueDivide', 'Remainder', 'Divmod', 'Lshift', 'Rshift',
                  'And', 'Xor', 'Or')
        operations = [(name, 1) for name in unary]
        operations += [(name, 2) for name in binary]
        operations += [('Power', 3), ('InPlacePower', 1)]
        operations += [('InPlace' + name, 1) for name in binary if name != 'Divmod']
        for name, positions in operations:
            api = 'PyNumber_' + name
            for position in range(positions):
                for value in (None, 42, object()):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(api=api, position=position,
                                          value_type=type(value), group=group):
                            self.assertIs(internal.threadgroup_return_probe(
                                (value, frozendict()), group, api, position),
                                type(value) is not object or
                                group is sys.main_thread_group)

    def test_sequence_operator_slot_returns(self):
        operations = (
            'PySequence_Concat', 'PySequence_Repeat',
            'PySequence_InPlaceConcat', 'PySequence_InPlaceRepeat',
            'PySequence_InPlaceConcat_fallback',
            'PySequence_InPlaceRepeat_fallback',
            'PySequence_Concat_numeric', 'PySequence_Repeat_numeric',
            'PySequence_InPlaceConcat_numeric',
            'PySequence_InPlaceRepeat_numeric',
            'PyNumber_Add_sequence', 'PyNumber_Multiply_sequence',
            'PyNumber_InPlaceAdd_sequence', 'PyNumber_InPlaceMultiply_sequence',
            'PyNumber_InPlaceAdd_sequence_fallback',
            'PyNumber_InPlaceMultiply_sequence_fallback',
        )
        for api in operations:
            # Number multiplication also tries repetition of its right operand.
            positions = ((0, 1) if api in (
                'PyNumber_Multiply_sequence',
                'PyNumber_InPlaceMultiply_sequence_fallback',
            ) else (0,))
            for position in positions:
                for value in (None, 42, object()):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(api=api, position=position,
                                          value_type=type(value), group=group):
                            self.assertIs(internal.threadgroup_return_probe(
                                (value, frozendict()), group, api, position),
                                type(value) is not object or
                                group is sys.main_thread_group)

    def test_string_conversion_slot_returns(self):
        class String(str):
            pass

        for api in ('PyObject_Repr', 'PyObject_Str', 'PyObject_Str_repr',
                    'PyObject_ASCII'):
            texts = ('ascii',) if api == 'PyObject_ASCII' else ('ascii', 'caf\u00e9')
            for text in texts:
                for value in (text, String(text)):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(api=api, value_type=type(value),
                                          text=text, group=group):
                            self.assertIs(internal.threadgroup_return_probe(
                                (value, frozendict()), group, api),
                                type(value) is str or group is sys.main_thread_group)
            # Reject an inaccessible slot result before validating its type.
            with self.subTest(api=api, invalid_result=True):
                self.assertFalse(internal.threadgroup_return_probe(
                    ([], frozendict()), self.foreign, api))

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

    def test_native_iterator_consumers(self):
        iterator_type = internal.make_raw_iterator_type()
        cases = (
            ('all', 'bound_builtin(it)', None, all),
            ('any', 'bound_builtin(it)', None, any),
            ('filter none', 'bound_builtin(ctor(None, it))', filter, next),
            ('filter bool', 'bound_builtin(ctor(truth, it))', filter, next),
            ('map', 'bound_builtin(ctor(consumer, it))', map, next),
            ('map heap arguments',
             'bound_builtin(ctor(consumer, it, *((0,),) * 10))', map, next),
            ('zip', 'bound_builtin(ctor(it))', zip, next),
            ('zip new tuple',
             'it = iterator_type((0,) + source[1])\n'
             'adapted = ctor(it)\n'
             'held = bound_builtin(adapted)\n'
             'bound_builtin(adapted)', zip, next),
            ('enumerate', 'bound_builtin(ctor(it))', enumerate, next),
            ('enumerate long index',
             'bound_builtin(ctor(it, 1 << 128))', enumerate, next),
            ('list', 'ctor(it)', list, next),
            ('list extend', 'copied = []\ncopied.extend(it)', None, next),
            ('bytearray', 'ctor(it)', bytearray, next),
            # These already use checked iteration/return APIs.
            ('bytes', 'ctor(it)', bytes, next),
            ('min', 'bound_builtin(it)', None, min),
            ('max', 'bound_builtin(it)', None, max),
            ('next', 'bound_builtin(it)', None, next),
        )
        for name, body, ctor, builtin in cases:
            namespace = {}
            exec('def probe():\n'
                 '    iterator_type, ctor, error, rejected, truth = source[2]\n'
                 '    it = iterator_type(source[1])\n'
                 '    try:\n' + textwrap.indent(body, '        ') + '\n'
                 '    except error:\n        assert rejected\n'
                 '    else:\n        assert not rejected\n'
                 '    return True', namespace)
            for immutable in (False, True):
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(operation=name, immutable=immutable, group=group):
                        value = internal.make_container_element(immutable)
                        rejected = not immutable and group is self.foreign
                        options = (iterator_type, ctor, IllegalThreadAccessException,
                                   rejected, bool)
                        self.assertTrue(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__, group,
                            (True, (value,), options), 0, 1, False, builtin))
                        if rejected:
                            self.assertEqual(internal.container_element_calls(value), 0)

    def test_native_iterator_strict_errors(self):
        iterator_type = internal.make_raw_iterator_type()
        for ctor, arguments in ((map, 'consumer, '), (zip, '')):
            for iterables in ('(), it', '(0,), it, ()'):
                namespace = {}
                exec('def probe():\n'
                     '    iterator_type, ctor, error = source[2]\n'
                     '    it = iterator_type(source[1])\n'
                     f'    adapted = ctor({arguments}{iterables}, strict=True)\n'
                     '    try:\n        bound_builtin(adapted)\n'
                     '    except error:\n        return True\n'
                     '    assert False', namespace)
                for immutable in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        with self.subTest(ctor=ctor, iterables=iterables,
                                          immutable=immutable, group=group):
                            value = internal.make_container_element(immutable)
                            error = (IllegalThreadAccessException if
                                     not immutable and group is self.foreign
                                     else ValueError)
                            self.assertTrue(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__, group,
                                (True, (value,), (iterator_type, ctor, error)),
                                0, 1, False, next))
                            self.assertEqual(internal.container_element_calls(value), 0)

    def test_native_iterator_short_circuit(self):
        iterator_type = internal.make_raw_iterator_type()
        cases = (
            ('all', 'assert bound_builtin(it) is False', None, all, (False,), 1),
            ('any', 'assert bound_builtin(it) is True', None, any, (True,), 1),
            ('filter', 'assert bound_builtin(ctor(None, it)) is True',
             filter, next, (True,), 1),
            ('map', 'assert bound_builtin(ctor(consumer, (), it), None) is None',
             map, next, (), 0),
            ('zip', 'assert bound_builtin(ctor((), it), None) is None',
             zip, next, (), 0),
            ('list extend',
             'copied = [0]\n'
             'try:\n    copied.extend(it)\n'
             'except error:\n    pass\n'
             'else:\n    assert False\n'
             'assert copied == [0, 1]', None, next, (1,), 2),
        )
        for name, body, ctor, builtin, prefix, position in cases:
            namespace = {}
            exec('def probe():\n'
                 '    iterator_type, ctor, error, position = source[2]\n'
                 '    it = iterator_type(source[1])\n' +
                 textwrap.indent(body, '    ') + '\n'
                 '    assert it.position == position\n'
                 '    return True', namespace)
            value = internal.make_container_element(False)
            with self.subTest(operation=name):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, prefix + (value,),
                     (iterator_type, ctor, IllegalThreadAccessException, position)),
                    0, 1, False, builtin))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_native_iterator_exhaustion(self):
        iterator_type = internal.make_raw_iterator_type()
        cases = (
            ('all', 'bound_builtin(it) is True', None, all),
            ('any', 'bound_builtin(it) is False', None, any),
            ('filter', 'bound_builtin(ctor(None, it), 42) == 42', filter, next),
            ('map', 'bound_builtin(ctor(consumer, it), 42) == 42', map, next),
            ('zip', 'bound_builtin(ctor(it), 42) == 42', zip, next),
            ('enumerate', 'bound_builtin(ctor(it), 42) == 42', enumerate, next),
            ('list', 'ctor(it) == []', list, next),
            ('bytearray', 'ctor(it) == b""', bytearray, next),
        )
        for name, expression, ctor, builtin in cases:
            namespace = {}
            exec('def probe():\n'
                 '    iterator_type, ctor, raise_stop = source[2]\n'
                 '    it = iterator_type((), raise_stop)\n'
                 f'    assert {expression}\n'
                 '    return True', namespace)
            for raise_stop in (False, True):
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(operation=name, raise_stop=raise_stop,
                                      group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__, group,
                            (True, None, (iterator_type, ctor, raise_stop)),
                            0, 1, False, builtin))

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

    def test_generic_alias_element_acquisition(self):
        class LocalClass:
            pass

        def probe():
            origin, error, rejected, operation, expected = source[2]
            alias = origin[source[1]]
            try:
                if operation == 'repr':
                    assert bound_builtin(alias) == expected
                else:
                    assert alias.__parameters__ == ()
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        native_values = [internal.make_container_element(immutable)
                         for immutable in (False, True)]
        for value in (1, LocalClass, [1], *native_values):
            immutable = value.__shareable__ is threading.Shareable.IMMUTABLE
            native = type(value) not in (int, type, list)
            for args in ((value,), (0, value)):
                expected = repr(list[args])
                for operation in ('repr', 'parameters'):
                    for group in (sys.main_thread_group, self.foreign):
                        rejected = not immutable and group is self.foreign
                        before = internal.container_element_calls(value) if native else 0
                        with self.subTest(value_type=type(value), size=len(args),
                                          operation=operation, group=group):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe.__code__, group,
                                (True, args, (list, IllegalThreadAccessException,
                                 rejected, operation, expected)),
                                0, 1, False, repr))
                            if native:
                                calls = before + (operation == 'repr' and not rejected)
                                self.assertEqual(internal.container_element_calls(value), calls)

    def test_generic_alias_argument_storage(self):
        def probe():
            alias = source[2][source[1]]
            assert alias.__args__ is source[1]
            assert alias.__reduce__()[1][1] is source[1]
            return True

        value = internal.make_container_element(False)
        for group in (sys.main_thread_group, self.foreign):
            with self.subTest(group=group):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, group, (True, (value,), list), 0))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_generic_alias_parameter_failure_cleanup(self):
        def probe():
            origin, error = source[2]

            def generic[T]():
                pass

            parameter = generic.__type_params__[0]
            assert origin[parameter].__parameters__ == (parameter,)
            alias = origin[(parameter,) + source[1]]
            for attempt in (0, 1):
                try:
                    alias.__parameters__
                except error:
                    pass
                else:
                    assert False
            assert alias.__args__[0] is parameter
            return True

        value = internal.make_container_element(False)
        self.assertTrue(internal.threadgroup_vm_probe(
            probe.__code__, self.foreign,
            (True, (value,), (list, IllegalThreadAccessException)), 0))
        self.assertEqual(internal.container_element_calls(value), 0)

    def test_generic_alias_substitution_acquisition(self):
        class LocalClass:
            pass

        def probe():
            origin, error, rejected, path = source[2]
            type_type = ().__class__.__class__
            Parameter = type_type('Parameter', (), {'__typing_subst__': consumer})

            def prepare(self, alias, arguments):
                return source[1]

            Prepared = type_type('Prepared', (Parameter,),
                                 {'__typing_prepare_subst__': prepare})

            assert origin[Parameter()][1].__args__ == (True,)
            parameter = Prepared() if path == 'prepared' else Parameter()
            alias = origin[parameter]
            arguments = source[1]
            if path == 'prepared':
                arguments = 1
            elif path == 'unpacked':
                tuple_type = ().__class__
                arguments = (*tuple_type[arguments],)[0]
            try:
                result = alias[arguments]
            except error:
                assert rejected
            else:
                assert not rejected
                assert result.__args__ == (True,)
            return True

        for value in (1, LocalClass, internal.make_container_element(False),
                      internal.make_container_element(True)):
            immutable = value.__shareable__ is threading.Shareable.IMMUTABLE
            for path in ('direct', 'prepared', 'unpacked'):
                for group in (sys.main_thread_group, self.foreign):
                    rejected = not immutable and group is self.foreign
                    with self.subTest(value_type=type(value), path=path, group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, (value,), (list, IllegalThreadAccessException,
                             rejected, path)), 0))

    def test_generic_alias_variadic_substitution_acquisition(self):
        class Tuple(tuple):
            pass

        def probe():
            origin, error, rejected = source[2]
            type_type = ().__class__.__class__

            def iterate(self):
                return ().__iter__()

            def prepare(self, alias, arguments):
                return source[1]

            Parameter = type_type('Parameter', (), {
                '__typing_subst__': consumer,
                '__iter__': iterate,
                '__typing_prepare_subst__': prepare,
            })

            def getitem(self, arguments):
                assert arguments == (1, 2)
                return 42

            Nested = type_type('Nested', (), {
                '__parameters__': (Parameter(),),
                '__getitem__': getitem,
            })

            alias = origin[Nested()]
            try:
                result = alias[0]
            except error:
                assert rejected
            else:
                assert not rejected
                assert result.__args__ == (42,)
            return True

        for value in ((1, 2), Tuple((1, 2))):
            for group in (sys.main_thread_group, self.foreign):
                rejected = type(value) is Tuple and group is self.foreign
                with self.subTest(value_type=type(value), group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (True, (value,), (list, IllegalThreadAccessException, rejected)), 0))

    def test_generic_alias_unused_substitution_arguments(self):
        def probe():
            origin, error, path = source[2]
            type_type = ().__class__.__class__
            arguments = source[1]
            if path == 'no parameters':
                alias = origin[0]
            elif path == 'prepared arity':
                def prepare(self, alias, arguments):
                    return (0,) + source[1]

                Parameter = type_type('Parameter', (), {
                    '__typing_subst__': consumer,
                    '__typing_prepare_subst__': prepare,
                })
                alias = origin[Parameter()]
                arguments = 0
            else:
                def getattribute(self, name):
                    raise error

                Bad = type_type('Bad', (), {'__getattribute__': getattribute})
                Parameter = type_type('Parameter', (), {'__typing_subst__': consumer})
                alias = origin[Parameter()]
                arguments = (Bad(),) + source[1]
            try:
                alias[arguments]
            except error:
                return True
            assert False

        value = internal.make_container_element(False)
        for path, error in (('no parameters', TypeError),
                            ('prepared arity', TypeError),
                            ('earlier unpack error', ValueError)):
            with self.subTest(path=path):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, self.foreign,
                    (True, (value,), (list, error, path)), 0))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_generic_alias_substitution_metadata(self):
        class LocalClass:
            pass

        def probe():
            origin, error, rejected, path, later = source[2]
            type_type = ().__class__.__class__
            Parameter = type_type('Parameter', (), {'__typing_subst__': consumer})
            parameter = Parameter()
            if path == 'parameters':
                def getitem(self, arguments):
                    return 42

                parameters = ((parameter,) if later else ()) + source[1]
                Nested = type_type('Nested', (), {
                    '__parameters__': parameters,
                    '__getitem__': getitem,
                })
                alias = origin[Nested()]
                assert alias.__parameters__.__len__() == parameters.__len__()
                arguments = (0,) * parameters.__len__()
            else:
                values = [parameter]
                args = (parameter, values) if later else (values,)
                alias = origin[args]
                assert alias.__parameters__ == (parameter,)
                # Mutating a nested list does not invalidate cached parameters.
                values[:] = source[1]
                arguments = (0,)
            original_args = alias.__args__
            for attempt in (0, 1):
                try:
                    alias[arguments]
                except error:
                    assert rejected
                else:
                    assert not rejected
                assert alias.__args__ is original_args
            return True

        for value in (1, LocalClass, internal.make_container_element(False),
                      internal.make_container_element(True)):
            immutable = value.__shareable__ is threading.Shareable.IMMUTABLE
            for path in ('parameters', 'nested list'):
                for later in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        rejected = not immutable and group is self.foreign
                        with self.subTest(value_type=type(value), path=path,
                                          later=later, group=group):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe.__code__, group,
                                (True, (value,), (list, IllegalThreadAccessException,
                                 rejected, path, later)), 0))

    def test_exception_argument_formatting(self):
        for exception_type in (BaseException, Exception, KeyError, AttributeError):
            for method in ('__str__', '__repr__'):
                for size in (1, 2):
                    namespace = {}
                    exec('def probe():\n'
                         '    error = source[2]()\n'
                         '    error.args = source[1]\n'
                         f'    error.{method}()\n'
                         '    return True', namespace)
                    for immutable in (False, True):
                        for group in (sys.main_thread_group, self.foreign):
                            value = internal.make_container_element(immutable)
                            args = (value,) if size == 1 else (0, value)
                            accessible = immutable or group is sys.main_thread_group
                            with self.subTest(exception_type=exception_type,
                                              method=method, size=size,
                                              immutable=immutable, group=group):
                                self.assertIs(internal.threadgroup_vm_probe(
                                    namespace['probe'].__code__, group,
                                    (value, args, exception_type), 0), accessible)
                                self.assertEqual(internal.container_element_calls(value),
                                                 int(accessible))

    def test_exception_reraise_acquisition(self):
        def probe():
            leaf, constructor, grouped, error = source[2]
            try:
                try:
                    if grouped:
                        raise constructor('group', (leaf(),))
                    raise leaf()
                except leaf as orig:
                    bound_builtin(orig, source[1])
            except error:
                pass
            else:
                assert error is None
            return True

        for value in (BaseException(), None, object(), 42):
            for grouped in (False, True):
                for group in (sys.main_thread_group, self.foreign):
                    valid = isinstance(value, BaseException) or value is None
                    error = None if valid else TypeError
                    if not internal.threadgroup_access_probe(group, value):
                        error = IllegalThreadAccessException
                    with self.subTest(type=type(value), grouped=grouped, group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, (value,), (BaseException, BaseExceptionGroup,
                             grouped, error)), 0, 1, False,
                            internal.reraise_star_probe))

    def test_exception_reference_returns(self):
        class LocalArgs(tuple):
            pass

        cases = (
            ('PyException_GetCause', BaseException()),
            ('PyException_GetArgs', (object(),)),
            ('PyException_GetArgs', LocalArgs()),
        )
        for api, value in cases:
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(api=api, type=type(value), group=group):
                    accessible = internal.threadgroup_access_probe(group, value)
                    self.assertIs(internal.threadgroup_return_probe(
                        (value, frozendict()), group, api), accessible)

    def test_exception_group_cause_acquisition(self):
        def probe():
            constructor, leaf, matcher, error, rejected, split = source[2]
            group = constructor('group', (leaf(), matcher()))
            bound_builtin(group, source[1])
            try:
                if split:
                    group.split(matcher)
                else:
                    group.subgroup(matcher)
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        cause = BaseException()
        for split in (False, True):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(split=split, group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (True, (cause,), (BaseExceptionGroup, BaseException,
                         KeyboardInterrupt, IllegalThreadAccessException,
                         group is self.foreign, split)), 0, 1, False,
                        internal.copy_exception_cause))

    def test_except_matcher_acquisition(self):
        class LocalError(BaseException):
            pass

        for clause in ('except', 'except*'):
            namespace = {}
            exec(f'''def probe():
    constructor, error = source[2]
    try:
        try:
            raise constructor()
        {clause} source[1]:
            pass
    except error:
        pass
    else:
        assert error is None
    return True
''', namespace)
            for value in (LocalError, BaseException, object(), 42):
                for group in (sys.main_thread_group, self.foreign):
                    error = None if isinstance(value, type) else TypeError
                    if (group is self.foreign and
                        value is not BaseException and type(value) is not int):
                        error = IllegalThreadAccessException
                    with self.subTest(clause=clause, value=value, group=group):
                        # Validate later tuple members even if the first matches.
                        self.assertTrue(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__, group,
                            (True, (BaseException, value),
                             (BaseException, error)), 0))

    def test_exception_group_element_acquisition(self):
        def probe():
            constructor, error = source[2]
            if error is None:
                constructor('group', source[1])
            else:
                try:
                    constructor('group', source[1])
                except error:
                    pass
                else:
                    assert False
            return True

        for value in (BaseException(), ValueError(), object(), 42):
            for group in (sys.main_thread_group, self.foreign):
                error = None if isinstance(value, BaseException) else ValueError
                if group is self.foreign and type(value) is not int:
                    error = IllegalThreadAccessException
                with self.subTest(value=type(value), group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (True, (value,), (BaseExceptionGroup, error)), 0))

    def test_exception_group_implicit_class_acquisition(self):
        def probe():
            constructor, leaf_type, error, rejected = source[2]
            leaf = leaf_type()
            try:
                constructor('group', (leaf,))
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        for leaf_type in (BaseException, ValueError):
            for group in (sys.main_thread_group, self.foreign):
                # ExceptionGroup is a mutable heap type created in Main.
                rejected = leaf_type is ValueError and not (
                    internal.threadgroup_access_probe(group, ExceptionGroup))
                with self.subTest(leaf_type=leaf_type, group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (True, None, (BaseExceptionGroup, leaf_type,
                         IllegalThreadAccessException, rejected)), 0))

    def test_exception_group_matcher_acquisition(self):
        class LocalError(BaseException):
            pass

        def probe():
            constructor, leaf_type, error, split = source[2]
            group = constructor('group', (leaf_type(),))
            method = group.split if split else group.subgroup
            if error is None:
                method(source[1])
            else:
                try:
                    method(source[1])
                except error:
                    pass
                else:
                    assert False
            return True

        for value in (LocalError, BaseException, object(), 42):
            for prefix in ((), (BaseException,)):
                for split in (False, True):
                    for group in (sys.main_thread_group, self.foreign):
                        error = None if isinstance(value, type) else TypeError
                        if (group is self.foreign and
                            value is not BaseException and type(value) is not int):
                            error = IllegalThreadAccessException
                        with self.subTest(value=value, prefix=prefix,
                                          split=split, group=group):
                            self.assertTrue(internal.threadgroup_vm_probe(
                                probe.__code__, group,
                                (True, prefix + (value,),
                                 (BaseExceptionGroup, BaseException, error, split)), 0))

    def test_attribute_error_message_acquisition(self):
        class String(str):
            pass

        def probe():
            exception_type, expected = source[2]
            error = exception_type(name='missing', obj=None)
            error.args = source[1]
            assert error.__str__() == expected
            return True

        for message in ('missing', 'custom', String('missing'), String('custom')):
            for group in (sys.main_thread_group, self.foreign):
                accessible = type(message) is str or group is sys.main_thread_group
                expected = ("'NoneType' object has no attribute 'missing'"
                            if message == 'missing' else 'custom')
                with self.subTest(message=message, value_type=type(message), group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (message, (message,), (AttributeError, expected)), 0), accessible)

    def test_exception_argument_storage(self):
        def probe():
            error = source[2]()
            error.args = source[1]
            assert error.args is source[1]
            assert error.__reduce__()[1] is source[1]
            return True

        for exception_type in (BaseException, Exception, KeyError, AttributeError):
            value = internal.make_container_element(False)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(exception_type=exception_type, group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group, (True, (value,), exception_type), 0))
                    self.assertEqual(internal.container_element_calls(value), 0)

    def test_nested_argument_integer_acquisition(self):
        capi = import_helper.import_module('_testcapi')

        class Integer(int):
            pass

        cases = (
            (capi.getargs_tuple, 'bound_builtin(0, values)'),
            (capi.getargs_keywords, 'bound_builtin((0, 0), 0, (0, values))'),
            (capi.getargs_keywords,
             'bound_builtin((0, 0), 0, arg3=(0, values))'),
        )
        for api, expression in cases:
            namespace = {}
            exec('def probe():\n'
                 '    copy_type, error, rejected = source[2]\n'
                 '    values = source[1]\n'
                 '    if copy_type is not None:\n'
                 '        values = copy_type(values)\n'
                 '    try:\n' + f'        {expression}\n'
                 '    except error:\n        assert rejected\n'
                 '    else:\n        assert not rejected\n'
                 '    return True', namespace)
            for value in (1, Integer(1), internal.make_container_element(False),
                          internal.make_container_element(True)):
                native = type(value) not in (int, Integer)
                immutable = value.__shareable__ is threading.Shareable.IMMUTABLE
                for position in (0, 1):
                    values = (value, 0) if position == 0 else (0, value)
                    for copy_type in (None, list):
                        for group in (sys.main_thread_group, self.foreign):
                            rejected = not immutable and group is self.foreign
                            before = internal.container_element_calls(value) if native else 0
                            with self.subTest(expression=expression,
                                              value_type=type(value), position=position,
                                              copy_type=copy_type, group=group):
                                self.assertTrue(internal.threadgroup_vm_probe(
                                    namespace['probe'].__code__, group,
                                    (True, values, (copy_type,
                                     IllegalThreadAccessException, rejected)),
                                    0, 1, False, api))
                                if native:
                                    self.assertEqual(internal.container_element_calls(value),
                                                     before + (not rejected))

    def test_nested_argument_object_acquisition(self):
        capi = import_helper.import_module('_testcapi')

        class String(str):
            pass

        class Bytes(bytes):
            pass

        def probe():
            format, error, rejected = source[2]
            try:
                bound_builtin((source[1],), {}, format, ['arg'])
            except error:
                assert rejected
            else:
                assert not rejected
            return True

        native_values = [internal.make_container_element(immutable)
                         for immutable in (False, True)]
        for format, values in (('(O)', native_values), ('(p)', native_values),
                               ('(U)', ('text', String('text'))),
                               ('(S)', (b'data', Bytes(b'data')))):
            for value in values:
                for group in (sys.main_thread_group, self.foreign):
                    immutable = value.__shareable__ is threading.Shareable.IMMUTABLE
                    rejected = not immutable and group is self.foreign
                    native = format in ('(O)', '(p)')
                    before = internal.container_element_calls(value) if native else 0
                    with self.subTest(format=format, value_type=type(value), group=group):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, (value,), (format, IllegalThreadAccessException, rejected)),
                            0, 1, False, capi.parse_tuple_and_keywords))
                        if native:
                            expected = before + (format == '(p)' and not rejected)
                            self.assertEqual(internal.container_element_calls(value), expected)

    def test_nested_argument_unused_elements(self):
        capi = import_helper.import_module('_testcapi')
        for expression in ('bound_builtin(0, source[1])',
                           "bound_builtin(0, ('bad',) + source[1])",
                           "bound_builtin('bad', (0,) + source[1])"):
            namespace = {}
            exec('def probe():\n'
                 '    try:\n' + f'        {expression}\n'
                 '    except TypeError:\n        return True\n'
                 '    assert False', namespace)
            value = internal.make_container_element(False)
            with self.subTest(expression=expression):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, (value,), None), 0, 1, False, capi.getargs_tuple))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_nested_argument_acquisition_failure_cleanup(self):
        capi = import_helper.import_module('_testcapi')

        def probe():
            bytearray_type, copy_type, error = source[2]
            data = bytearray_type(b'data')
            values = (data,) + source[1]
            if copy_type is not None:
                values = copy_type(values)
            try:
                bound_builtin((values,), {}, '(y*i)', ['arg'])
            except error:
                pass
            else:
                assert False
            # Rejection must release the buffer acquired for the first item.
            data.extend(b'!')
            assert data == b'data!'
            return True

        for copy_type in (None, list):
            value = internal.make_container_element(False)
            with self.subTest(copy_type=copy_type):
                self.assertTrue(internal.threadgroup_vm_probe(
                    probe.__code__, self.foreign,
                    (True, (value,), (bytearray, copy_type, IllegalThreadAccessException)),
                    0, 1, False, capi.parse_tuple_and_keywords))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_memoryview_shape_acquisition(self):
        class Integer(int):
            pass

        def probe():
            view_type, copy_type, order = source[2]
            shape = source[1]
            if copy_type is not None:
                shape = copy_type(shape)
            view = view_type(b'a')
            cast = view.cast('B', shape, order=order)
            assert cast.tobytes() == b'a'
            return True

        for value in (1, Integer(1)):
            for shape in ((value,), (value, 1), (1, value)):
                for copy_type in (None, list):
                    for order in ('C', 'F'):
                        for group in (sys.main_thread_group, self.foreign):
                            accessible = (type(value) is int or
                                          group is sys.main_thread_group)
                            with self.subTest(value_type=type(value), shape=shape,
                                              copy_type=copy_type, order=order,
                                              group=group):
                                self.assertIs(internal.threadgroup_vm_probe(
                                    probe.__code__, group,
                                    (value, shape, (memoryview, copy_type, order)),
                                    0), accessible)

    def test_memoryview_tuple_index_acquisition(self):
        class Integer(int):
            pass

        for write in (False, True):
            namespace = {}
            operation = ('view[source[1]] = 90\n'
                         'assert view[index] == 90' if write else
                         'assert view[source[1]] == view[index]')
            exec('def probe():\n'
                 '    view_type, bytearray_type, index = source[2]\n'
                 "    view = view_type(bytearray_type(b'abcd'))\n"
                 '    if index.__len__() == 2:\n'
                 "        view = view.cast('B', (2, 2))\n" +
                 textwrap.indent(operation, '    ') + '\n'
                 '    return True', namespace)
            for value in (1, Integer(1), internal.make_container_element(False),
                          internal.make_container_element(True)):
                native = type(value) not in (int, Integer)
                immutable = value.__shareable__ is threading.Shareable.IMMUTABLE
                for key, index in (((value,), (1,)),
                                   ((value, 0), (1, 0)),
                                   ((0, value), (0, 1))):
                    for group in (sys.main_thread_group, self.foreign):
                        accessible = immutable or group is sys.main_thread_group
                        before = internal.container_element_calls(value) if native else 0
                        with self.subTest(write=write, value_type=type(value),
                                          index=index, group=group):
                            self.assertIs(internal.threadgroup_vm_probe(
                                namespace['probe'].__code__, group,
                                (value, key, (memoryview, bytearray, index)), 0),
                                accessible)
                            if native:
                                self.assertEqual(internal.container_element_calls(value),
                                                 before + accessible)

    def test_memoryview_unused_elements(self):
        cases = (
            ("view.cast('B', (0,) + source[1])", ValueError),
            ("view.cast('B', ('bad',) + source[1])", TypeError),
            ('view[(0,) + source[1]]', TypeError),
            ("view.cast('B', (2, 2))[source[1]]", NotImplementedError),
            ("view.cast('B', (2, 2))[(99,) + source[1]]", IndexError),
            ("view.cast('B', (2, 2))[(99,) + source[1]] = 90", IndexError),
            ('view.toreadonly()[source[1]] = 90', TypeError),
            ('view.release()\nview[source[1]]', ValueError),
        )
        for body, error in cases:
            namespace = {}
            exec('def probe():\n'
                 '    view_type, bytearray_type, error = source[2]\n'
                 "    view = view_type(bytearray_type(b'abcd'))\n"
                 '    try:\n' + textwrap.indent(body, '        ') + '\n'
                 '    except error:\n        return True\n'
                 '    assert False', namespace)
            value = internal.make_container_element(False)
            with self.subTest(body=body):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, (value,), (memoryview, bytearray, error)), 0))
                self.assertEqual(internal.container_element_calls(value), 0)

    def test_memoryview_acquisition_failure_cleanup(self):
        class Integer(int):
            pass

        for body, value in (
            ("view.cast('B', (4,) + source[1])", Integer(1)),
            ("view.cast('B', (2, 2))[(0,) + source[1]] = 90",
             internal.make_container_element(False)),
        ):
            namespace = {}
            exec('def probe():\n'
                 '    view_type, bytearray_type, error = source[2]\n'
                 "    data = bytearray_type(b'abcd')\n"
                 '    view = view_type(data)\n'
                 '    try:\n' + textwrap.indent(body, '        ') + '\n'
                 '    except error:\n        pass\n'
                 '    else:\n        assert False\n'
                 "    assert data == b'abcd'\n"
                 '    view.release()\n'
                 "    data.extend(b'e')\n"
                 "    assert data == b'abcde'\n"
                 '    return True', namespace)
            with self.subTest(body=body):
                self.assertTrue(internal.threadgroup_vm_probe(
                    namespace['probe'].__code__, self.foreign,
                    (True, (value,),
                     (memoryview, bytearray, IllegalThreadAccessException)), 0))

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
            self.assertIs(type(instance).__shareable__, threading.Shareable.IMMUTABLE)
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

    def test_shared_builtin_class_receiver(self):
        instance = internal.make_immutable_special_method_instance({})
        for expression in ('source[1].__init_subclass__()',
                           'source[1].__subclasshook__(source[2])'):
            namespace = {}
            exec(f'def probe():\n    {expression}\n    return True', namespace)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(expression=expression, group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (type(instance), instance, object), 0, 32))

    def test_foreign_builtin_defining_class(self):
        base, subtype = internal.make_immutable_subtype(tuple)
        instance = internal.make_immutable_call_receiver(subtype)
        self.assertIs(base.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(subtype.__shareable__, threading.Shareable.IMMUTABLE)

        bodies = (
            'source[1].method()',
            'method = source[1].method\nmethod()',
        )
        for body in bodies:
            namespace = {}
            exec('def probe():\n' + textwrap.indent(body, '    ') +
                 '\n    return True', namespace)
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(body=body, group=group):
                    self.assertIs(internal.threadgroup_vm_probe(
                        namespace['probe'].__code__, group,
                        (base, instance, None), 0, 32),
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
            ('shared instance class', instance, 'source[1][0]',
             limited.eval_get_func_name(instance), ' object', False),
            ('bound receiver', object(), 'bind_method(local, source[1])',
             'local', '()', False),
        )
        for case, value, expression, name, desc, local_metadata in cases:
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
                        if (getter is limited.eval_get_func_name and local_metadata
                                and group is self.foreign):
                            expected = None
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe_code, group,
                            (True, (value, expected), IllegalThreadAccessException),
                            0, 1, False, getter))

    def test_bound_method_private_name_shared_class(self):
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
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__.replace(), group,
                            (type(value), value, None), warmups))

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

        # The class of an immutable instance must itself be shareable, so
        # type() must succeed across groups, including after specialization.
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
                    self.assertTrue(accessible)
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

    @unittest.skipUnless(Py_DEBUG, "requires debug stack validation")
    def test_debug_stack_access_validation(self):
        code = textwrap.dedent('''
            import _testinternalcapi as internal
            import threading
            from test.support import SuppressCrashReport

            def probe():
                injected = None
                bound_builtin(source[1])
                return injected is None

            with SuppressCrashReport():
                internal.threadgroup_vm_probe(
                    probe.__code__, threading.ThreadGroup('invalid stack'),
                    (True, (object(),), None), 0, 1, False,
                    internal.inject_inaccessible_local)
        ''')
        _, _, err = script_helper.assert_python_failure('-c', code)
        self.assertIn(b'PyObject_IsAccessible', err)

    def test_frame_variable_capi_acquisition(self):
        value = None

        def probe():
            # Keep a free variable in the frame without reading its contents.
            def capture():
                return value
            try:
                bound_builtin(source[1], source[2][2])
            except source[2][0]:
                assert source[2][1]
            else:
                assert not source[2][1]
            return True

        for use_string in (False, True):
            for value, immutable in ((object(), False), (42, True)):
                for group in (sys.main_thread_group, self.foreign):
                    with self.subTest(use_string=use_string, group=group,
                                      immutable=immutable):
                        self.assertTrue(internal.threadgroup_vm_probe(
                            probe.__code__, group,
                            (True, (value,), (IllegalThreadAccessException,
                             not immutable and group is self.foreign, use_string)),
                            0, 1, False, internal.frame_getvar_probe))

    def test_function_constructor_closure_acquisition(self):
        from types import CellType, FunctionType

        value = None

        def target():
            return value

        def probe():
            constructor, error, rejected, is_cell = source[2]
            code, closure = source[1]
            try:
                constructor(code, {}, closure=closure)
            except error:
                assert rejected
            except TypeError:
                assert not rejected and not is_cell
            else:
                assert not rejected and is_cell
            return True

        for cell in (CellType(None), object()):
            for group in (sys.main_thread_group, self.foreign):
                with self.subTest(cell=isinstance(cell, CellType), group=group):
                    self.assertTrue(internal.threadgroup_vm_probe(
                        probe.__code__, group,
                        (True, (target.__code__, (cell,)),
                         (FunctionType, IllegalThreadAccessException,
                          group is self.foreign, isinstance(cell, CellType))), 0))

    def test_vm_closure_cell_acquisition(self):
        from types import CellType
        capi = import_helper.import_module('_testcapi')
        bodies = {
            'read': 'return value',
            'write': 'nonlocal value\nvalue = 42',
            'delete': 'nonlocal value\ndel value',
            'capture': 'def inner():\n    return value\nreturn inner',
        }
        for operation, body in bodies.items():
            namespace = {}
            exec('def probe():\n'
                 '    global entered\n'
                 '    first = None\n'
                 '    value = None\n'
                 '    def target():\n'
                 '        global entered\n'
                 '        entered = True\n'
                 '        assert first is None\n' + textwrap.indent(body, '        ') + '\n'
                 '    for _ in (None,) * source[2][2]:\n'
                 '        value = None\n'
                 '        target()\n'
                 '    entered = False\n'
                 '    closure = target.__closure__[:1] + source[1]\n'
                 '    bound_builtin(target, closure)\n'
                 '    try:\n'
                 '        target()\n'
                 '    except source[2][0]:\n'
                 '        assert source[2][1]\n'
                 '    else:\n'
                 '        assert not source[2][1]\n'
                 '    assert entered is (not source[2][1])\n'
                 '    return True\n', namespace)
            for group in (sys.main_thread_group, self.foreign):
                for warmups in (0, 64):
                    with self.subTest(operation=operation, group=group,
                                      warmups=warmups):
                        cell = CellType(None)
                        # The C setter copies a safe tuple without acquiring
                        # its cell. COPY_FREE_VARS must reject that cell before
                        # any Python body runs, including nonlocal writes.
                        # The first, local cell also exercises partial cleanup.
                        self.assertTrue(internal.threadgroup_vm_probe(
                            namespace['probe'].__code__, group,
                            (True, (cell,), (IllegalThreadAccessException,
                             group is self.foreign, warmups)),
                            0, 1, False, capi.function_set_closure))
                        if group is sys.main_thread_group and operation == 'delete':
                            with self.assertRaises(ValueError):
                                cell.cell_contents
                        else:
                            expected = (42 if group is sys.main_thread_group and
                                        operation == 'write' else None)
                            self.assertIs(cell.cell_contents, expected)

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
