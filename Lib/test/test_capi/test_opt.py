import contextlib
import dis
import itertools
import sys
import sysconfig
import textwrap
import unittest
import gc
import os
import struct
import threading
import types
import weakref

import _opcode

from test.support import (script_helper, requires_specialization,
                          import_helper, Py_GIL_DISABLED, requires_jit_enabled,
                          reset_code, SHORT_TIMEOUT, isolation, disable_gc)

_testinternalcapi = import_helper.import_module("_testinternalcapi")

from _testinternalcapi import _PY_NSMALLPOSINTS, TIER2_THRESHOLD, TIER2_RESUME_THRESHOLD


def setUpModule():
    # Earlier test files may exhaust the builtin-mutation budget and disable
    # optimizations whose generated code is checked by this module.
    _testinternalcapi.reset_rare_event_counters()


#For test of issue 136154
GLOBAL_136154 = 42

# For frozendict JIT tests
FROZEN_DICT_CONST = frozendict(x=1, y=2)

# For frozenset JIT tests
FROZEN_SET_CONST = frozenset({1, 2, 3})

# PyObject_GenericHash with an immutable type, eligible for a constant hash.
_GENERIC_KEY = object()


def make_global_constant():
    # Functions have an immutable type, a writable attribute dictionary, and
    # weakrefs. Use independent globals so copied-namespace lifetime tests do
    # not retain the original namespace through the constant itself.
    def value():
        pass
    return types.FunctionType(value.__code__, {})


@contextlib.contextmanager
def clear_executors(func):
    # Clear executors in func before and after running a block
    reset_code(func)
    try:
        yield
    finally:
        reset_code(func)


def get_first_executor(func):
    code = func.__code__
    co_code = code.co_code
    for i in range(0, len(co_code), 2):
        try:
            return _opcode.get_executor(code, i)
        except ValueError:
            pass
    return None

def get_all_executors(func):
    code = func.__code__
    co_code = code.co_code
    executors = []
    for i in range(0, len(co_code), 2):
        try:
            executors.append(_opcode.get_executor(code, i))
        except ValueError:
            pass
    return executors


def iter_opnames(ex):
    for item in ex:
        yield item[0]


def get_opnames(ex):
    return list(iter_opnames(ex))

def iter_ops(ex):
    for item in ex:
        yield item

def get_ops(ex):
    return list(iter_ops(ex))


def count_return_ops(opnames):
    return sum(name == "_RETURN_VALUE" or name.startswith("_METHOD_RETURN_VALUE_")
               for name in opnames)

def count_ops(ex, name):
    return len([opname for opname in iter_opnames(ex) if opname == name])


@requires_specialization
@requires_jit_enabled
class TestMethodFrontend(unittest.TestCase):
    @disable_gc()
    def test_binary_op_guard_refreshes_changed_specialization(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def divide(value):
            result = value / 1e6
            return result + 1.0

        reset_code(divide)
        count = TIER2_RESUME_THRESHOLD * 16
        self.assertEqual(list(itertools.starmap(
            divide, itertools.repeat((1000,), count))), [1.001] * count)
        executor = get_first_executor(divide)
        self.assertIsNotNone(executor)
        self.assertIn('_GUARD_BINARY_OP_EXTEND', get_opnames(executor))
        self.assertIn('_EXIT_BINARY_OP', get_opnames(executor))

        # A single guard miss must not discard a useful specialization.
        large = 1 << (sys.int_info.bits_per_digit + 2)
        expected = large / 1e6 + 1.0
        self.assertEqual(divide(large), expected)
        self.assertTrue(executor.is_valid())

        # Once Tier 1 has changed to generic division, the stale native guard
        # must not permanently force the rest of the function into Tier 1.
        self.assertEqual(list(itertools.starmap(
            divide, itertools.repeat((large,), count))), [expected] * count)
        self.assertFalse(executor.is_valid())
        replacement = get_first_executor(divide)
        self.assertIsNotNone(replacement)
        self.assertNotIn('_GUARD_BINARY_OP_EXTEND', get_opnames(replacement))
        self.assertEqual(divide(1000), 1.001)

    @disable_gc()
    def test_binary_op_guard_refreshes_inlined_callee(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def divide(value):\n'
             '    return value / 1e6\n'
             'def caller(value):\n'
             '    return divide(value) + 1.0\n', namespace)
        caller = namespace['caller']
        count = TIER2_RESUME_THRESHOLD * 16
        list(itertools.starmap(caller, itertools.repeat((1000,), count)))
        executor = get_first_executor(caller)
        self.assertIsNotNone(executor)
        self.assertIn('_PUSH_FRAME', get_opnames(executor))
        self.assertIn('_GUARD_BINARY_OP_EXTEND', get_opnames(executor))
        large = 1 << (sys.int_info.bits_per_digit + 2)
        expected = large / 1e6 + 1.0
        self.assertEqual(list(itertools.starmap(
            caller, itertools.repeat((large,), count))), [expected] * count)
        self.assertFalse(executor.is_valid())
        replacement = get_first_executor(caller)
        self.assertIsNotNone(replacement)
        self.assertNotIn('_GUARD_BINARY_OP_EXTEND', get_opnames(replacement))

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Global invalidation feedback requires the GIL')
    def test_mutating_global_keeps_method_executor(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('counter = 1000\n'
             'def increment():\n'
             '    global counter\n'
             '    counter += 1\n'
             '    return counter\n', namespace)
        increment = namespace['increment']
        count = TIER2_RESUME_THRESHOLD * 16
        self.assertEqual(list(itertools.starmap(increment, itertools.repeat((), count))),
                         list(range(1001, 1001 + count)))
        executor = get_first_executor(increment)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_GLOBAL_MODULE', get_opnames(executor))
        for index in range(64):
            self.assertEqual(increment(), 1001 + count + index)
        self.assertTrue(executor.is_valid())
        namespace['counter'] = 0.5
        self.assertEqual(increment(), 1.5)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Global invalidation feedback requires the GIL')
    def test_mutating_global_read_by_other_function(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('counter = 1000\n'
             'def read(count):\n'
             '    result = 0\n'
             '    for index in range(count):\n'
             '        result += counter\n'
             '    return result\n', namespace)
        read = namespace['read']
        count = TIER2_THRESHOLD * 2
        for value in range(1000, 1020):
            namespace['counter'] = value
            self.assertEqual(read(count), value * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_GLOBAL_MODULE', get_opnames(executor))
        namespace['counter'] = 1020
        self.assertEqual(read(10), 10200)
        self.assertTrue(executor.is_valid())

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Mutable global binding hints require the GIL')
    def test_isinstance_default_metaclass_binding(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('class Meta(type):\n'
             '    pass\n'
             'class Target(metaclass=Meta):\n'
             '    pass\n'
             'class Child(Target):\n'
             '    pass\n'
             'def check(value):\n'
             '    return isinstance(value, Target)\n', namespace)
        check = namespace['check']
        target = namespace['Target']
        child = namespace['Child']
        meta = namespace['Meta']
        self.enterContext(clear_executors(check))
        instance = child()
        for _ in range(TIER2_RESUME_THRESHOLD * 2):
            self.assertTrue(check(instance))
        executor = get_first_executor(check)
        self.assertIsNotNone(executor)
        self.assertIn('_CALL_ISINSTANCE_DEFAULT', get_opnames(executor))

        class Pretender:
            @property
            def __class__(self):
                return child

        class Broken:
            @property
            def __class__(self):
                raise ValueError('class lookup')

        self.assertTrue(check(Pretender()))
        self.assertFalse(check(object()))
        with self.assertRaisesRegex(ValueError, 'class lookup'):
            check(Broken())
        self.assertTrue(check(instance))
        meta.__instancecheck__ = lambda cls, value: False
        self.assertFalse(check(instance))
        # Exact matches bypass __instancecheck__ even when it is overridden.
        self.assertTrue(check(target()))
        del meta.__instancecheck__
        self.assertTrue(check(instance))
        namespace['Target'] = int
        self.assertFalse(check(instance))
        self.assertTrue(check(123))

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Mutable global binding hints require the GIL')
    def test_isinstance_metaclass_reassignment(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('class Meta(type):\n'
             '    pass\n'
             'class Target(metaclass=Meta):\n'
             '    pass\n'
             'class Child(Target):\n'
             '    pass\n'
             'def check(value):\n'
             '    return isinstance(value, Target)\n', namespace)
        check = namespace['check']
        target = namespace['Target']
        instance = namespace['Child']()
        self.enterContext(clear_executors(check))
        for _ in range(TIER2_RESUME_THRESHOLD * 2):
            self.assertTrue(check(instance))
        executor = get_first_executor(check)
        self.assertIsNotNone(executor)
        self.assertIn('_CALL_ISINSTANCE_DEFAULT', get_opnames(executor))

        class Replacement(type):
            def __instancecheck__(cls, value):
                return value is marker

        marker = object()
        target.__class__ = Replacement
        self.assertFalse(check(instance))
        self.assertTrue(check(marker))
        self.assertTrue(check(target()))
        target.__class__ = namespace['Meta']
        self.assertTrue(check(instance))
        self.assertFalse(check(marker))

    def assert_generator_entries(self, function):
        executors = get_all_executors(function)
        self.assertTrue(executors)
        for executor in executors:
            self.assertIn(dis._deoptop(executor.get_opcode()),
                          (dis.opmap['JUMP_BACKWARD'], dis.opmap['RESUME']))
            if '_YIELD_VALUE' in get_opnames(executor):
                self.assertIn('_METHOD_YIELD_EXIT', get_opnames(executor))
            self.assertNotIn('_RETURN_GENERATOR', get_opnames(executor))

    @disable_gc()
    def test_generator_resume_compiles_without_backedge(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def generate(value):
            yield value + 1
            yield value + 2

        self.enterContext(clear_executors(generate))
        count = TIER2_RESUME_THRESHOLD * 2
        self.assertEqual([list(generate(10)) for _ in range(count)],
                         [[11, 12]] * count)
        resumes = [i.offset for i in dis.get_instructions(generate)
                   if i.opname == 'RESUME']
        self.assertGreaterEqual(len(resumes), 2)
        for offset in resumes[:2]:
            executor = _opcode.get_executor(generate.__code__, offset)
            self.assertIn('_YIELD_VALUE', get_opnames(executor))
            self.assertIn('_METHOD_YIELD_EXIT', get_opnames(executor))
        self.assertEqual(list(generate(0.5)), [1.5, 2.5])

    @disable_gc()
    def test_generator_resume_send_and_close(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        closed = []

        def generate():
            try:
                value = yield 0
                yield value + 1
            finally:
                closed.append(True)

        self.enterContext(clear_executors(generate))
        count = TIER2_RESUME_THRESHOLD * 2
        for _ in range(count):
            iterator = generate()
            self.assertEqual(next(iterator), 0)
            self.assertEqual(iterator.send(10), 11)
            iterator.close()
        self.assertEqual(len(closed), count)
        resumes = [i.offset for i in dis.get_instructions(generate)
                   if i.opname == 'RESUME']
        self.assertIn('_YIELD_VALUE', get_opnames(
            _opcode.get_executor(generate.__code__, resumes[1])))
        iterator = generate()
        self.assertEqual(next(iterator), 0)
        self.assertEqual(iterator.send(0.5), 1.5)
        iterator.close()
        iterator = generate()
        self.assertEqual(next(iterator), 0)
        with self.assertRaisesRegex(ValueError, 'from consumer'):
            iterator.throw(ValueError('from consumer'))
        self.assertEqual(len(closed), count + 2)

    @disable_gc()
    def test_generator_native_yield_resumes_caller(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def generate(count):
            for index in range(count):
                yield index
            return 'finished'

        reset_code(generate)
        count = TIER2_THRESHOLD * 2
        # list() resumes through a C caller; the for loop below has a Python
        # caller whose normal return offset instead points to loop exhaustion.
        self.assertEqual(list(generate(count)), list(range(count)))
        self.assert_generator_entries(generate)
        self.assertTrue(any('_YIELD_VALUE' in get_opnames(executor)
                            for executor in get_all_executors(generate)))
        result = []
        for value in generate(20):
            result.append(value + 1)
        self.assertEqual(result, list(range(1, 21)))

        def delegate(count):
            result = yield from generate(count)
            yield result

        self.assertEqual(list(delegate(20)), [*range(20), 'finished'])

    @disable_gc()
    def test_generator_native_yield_exception_state(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def generate(count):
            try:
                raise ValueError('inside')
            except ValueError as error:
                for index in range(count):
                    yield index, sys.exception() is error
                    if sys.exception() is not error:
                        raise AssertionError('lost generator exception state')

        reset_code(generate)
        count = TIER2_THRESHOLD * 2
        self.assertEqual(list(generate(count)), [(i, True) for i in range(count)])
        self.assertTrue(any('_YIELD_VALUE' in get_opnames(executor)
                            for executor in get_all_executors(generate)))
        try:
            raise RuntimeError('outside')
        except RuntimeError as error:
            generator = generate(20)
            self.assertEqual(next(generator), (0, True))
            self.assertIs(sys.exception(), error)
            self.assertEqual(generator.send(None), (1, True))
            self.assertIs(sys.exception(), error)
            generator.close()
            self.assertIs(sys.exception(), error)
            generator = generate(20)
            next(generator)
            with self.assertRaisesRegex(LookupError, 'thrown'):
                generator.throw(LookupError('thrown'))
            self.assertIs(sys.exception(), error)

    @disable_gc()
    def test_generator_native_yield_monitoring_after_callback(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        monitoring = sys.monitoring
        tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
        seen = []
        armed = [False]

        def generate(count, callback):
            for index in range(count):
                yield callback(index)

        def identity(value):
            if armed[0]:
                monitoring.set_local_events(
                    tool, generate.__code__, monitoring.events.PY_YIELD)
            return value

        reset_code(generate)
        count = TIER2_THRESHOLD * 2
        # Assign the callback's function version before compiling its caller.
        list(map(identity, range(TIER2_RESUME_THRESHOLD + 10)))
        monitoring.use_tool_id(tool, 'test native yield')
        try:
            monitoring.register_callback(tool, monitoring.events.PY_YIELD,
                lambda code, offset, value: seen.append(value))
            self.assertEqual(list(generate(count, identity)), list(range(count)))
            self.assertTrue(any('_YIELD_VALUE' in get_opnames(executor)
                                for executor in get_all_executors(generate)))

            generator = generate(4, identity)
            self.assertEqual(next(generator), 0)
            # The next resume enters the compiled backedge. Mutating a list
            # item keeps both the callback and the executor unchanged.
            armed[0] = True
            self.assertTrue(any(executor.is_valid()
                                for executor in get_all_executors(generate)))
            self.assertEqual(list(generator), [1, 2, 3])
            self.assertEqual(seen, [1, 2, 3])
        finally:
            monitoring.set_local_events(tool, generate.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_YIELD, None)
            monitoring.free_tool_id(tool)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Module constant folding requires the GIL')
    def test_module_constant_dictionary_and_binding_guards(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        module.value = 1000
        module.other = 1
        namespace = {'module': module}
        exec('def read():\n    return module.value\n', namespace)
        read = namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(read, itertools.repeat((), count))),
                         [1000] * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_ATTR_MODULE_CONST', get_opnames(executor))
        module.other = 2
        self.assertEqual(read(), 1000)
        self.assertTrue(executor.is_valid())
        other = types.ModuleType('other')
        other.value = 2000
        namespace['module'] = other
        self.assertEqual(read(), 2000)
        namespace['module'] = module
        self.assertEqual(read(), 1000)
        module.value = 'changed'
        self.assertFalse(executor.is_valid())
        self.assertEqual(read(), 'changed')
        del module.value
        with self.assertRaises(AttributeError):
            read()
        module.value = 3000
        self.assertEqual(read(), 3000)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Module constant folding requires the GIL')
    def test_module_constant_checks_class_after_call(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        module.value = 1000
        namespace = {'module': module}
        exec('def read(callback):\n'
             '    first = module.value\n'
             '    callback()\n'
             '    return first, module.value\n', namespace)
        read = namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(lambda: None, count))),
                         [(1000, 1000)] * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_ATTR_MODULE_CONST', get_opnames(executor))

        class ChangedModule(types.ModuleType):
            def __getattribute__(self, name):
                if name == 'value':
                    return 'intercepted'
                return super().__getattribute__(name)

        def change_class():
            module.__class__ = ChangedModule

        self.assertEqual(read(change_class), (1000, 'intercepted'))

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Module binding folding requires the GIL')
    def test_module_binding_does_not_prove_constant_type(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for expression in ('module', 'module.child'):
            with self.subTest(expression=expression):
                module = types.ModuleType('subject')
                module.child = types.ModuleType('child')
                subject = module if expression == 'module' else module.child
                namespace = {'module': module}
                exec(f'def read(callback):\n'
                     f'    before = type({expression})\n'
                     f'    callback()\n'
                     f'    return before, type({expression})\n', namespace)
                read = namespace['read']
                noop = lambda: None
                count = TIER2_RESUME_THRESHOLD + 10
                self.assertEqual(list(map(read, itertools.repeat(noop, count))),
                                 [(types.ModuleType, types.ModuleType)] * count)
                executor = get_first_executor(read)
                self.assertIsNotNone(executor)
                self.assertIn('_LOAD_GLOBAL_BINDING', get_opnames(executor))
                if expression == 'module.child':
                    self.assertIn('_LOAD_ATTR_MODULE_CONST', get_opnames(executor))

                class Changed(types.ModuleType):
                    pass

                def change_class():
                    subject.__class__ = Changed

                self.assertEqual(read(change_class), (types.ModuleType, Changed))
                self.assertEqual(read(noop), (Changed, Changed))

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Mutable binding folding requires the GIL')
    def test_global_binding_preserves_mutable_instance_semantics(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        class First:
            value = 10

            def __bool__(self):
                return True

        class Second:
            value = 20

            def __bool__(self):
                return False

        subject = First()
        namespace = {'subject': subject}
        exec('def read(callback):\n'
             '    before = type(subject)\n'
             '    callback()\n'
             '    return before, type(subject), subject.value, bool(subject)\n',
             namespace)
        read = namespace['read']
        self.enterContext(clear_executors(read))
        noop = lambda: None
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(noop, count))),
                         [(First, First, 10, True)] * count)
        executor = get_first_executor(read)
        self.assertIn('_LOAD_GLOBAL_BINDING', get_opnames(executor))

        def change_class():
            subject.__class__ = Second

        self.assertEqual(read(change_class), (First, Second, 20, False))
        self.assertEqual(read(noop), (Second, Second, 20, False))

        def replace_binding():
            namespace['subject'] = First()

        self.assertEqual(read(replace_binding), (Second, First, 10, True))
        self.assertFalse(executor.is_valid())
        del namespace['subject']
        with self.assertRaises(NameError):
            read(noop)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Mutable binding folding requires the GIL')
    def test_global_identity_preserves_binding_changes(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        class Sentinel:
            pass

        sentinel = Sentinel()
        namespace = {'identity_marker': sentinel}
        exec('def check(value, callback):\n'
             '    before = value is identity_marker\n'
             '    callback()\n'
             '    return before, value is not identity_marker\n', namespace)
        check = namespace['check']
        self.enterContext(clear_executors(check))
        noop = lambda: None
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(check,
                         itertools.repeat((sentinel, noop), count))),
                         [(True, False)] * count)
        executor = get_first_executor(check)
        self.assertIn('_IS_GLOBAL_BINDING', get_opnames(executor))

        def replace():
            namespace['identity_marker'] = Sentinel()

        self.assertEqual(check(sentinel, replace), (True, True))
        self.assertFalse(executor.is_valid())
        self.assertEqual(check(sentinel, noop), (False, True))
        del namespace['identity_marker']
        with self.assertRaises(NameError):
            check(sentinel, noop)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Mutable binding folding requires the GIL')
    def test_global_identity_preserves_finalizer(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        events = []
        change = False

        class Sentinel:
            pass

        namespace = {'identity_marker': Sentinel()}
        replacement = Sentinel()

        class Left:
            def __del__(self):
                if change:
                    namespace['identity_marker'] = replacement
                    events.append('finalized')
                    gc.collect()
                    _testinternalcapi.clear_executor_deletion_list()

        def make():
            return Left()

        namespace['make'] = make
        exec('def check():\n'
             '    return make() is identity_marker\n', namespace)
        check = namespace['check']
        self.enterContext(clear_executors(check))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(check, itertools.repeat((), count))),
                         [False] * count)
        executor = get_first_executor(check)
        self.assertIn('_IS_GLOBAL_BINDING', get_opnames(executor))
        change = True
        self.assertIs(check(), False)
        self.assertEqual(events, ['finalized'])
        self.assertIs(namespace['identity_marker'], replacement)
        self.assertFalse(executor.is_valid())

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Module binding folding requires the GIL')
    def test_module_binding_replacement_and_lifetime(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        module.child = types.ModuleType('child')
        namespace = {'module': module}
        exec('def read():\n    return module.child\n', namespace)
        read = namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        list(itertools.starmap(read, itertools.repeat((), count)))
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_ATTR_MODULE_CONST', get_opnames(executor))
        old = weakref.ref(module.child)
        module.child = types.ModuleType('replacement')
        self.assertFalse(executor.is_valid())
        self.assertIs(read(), module.child)
        _testinternalcapi.clear_executor_deletion_list()
        self.assertIsNone(old())
        old = weakref.ref(module)
        replacement = types.ModuleType('new namespace')
        replacement.child = 42
        namespace['module'] = replacement
        del module
        self.assertEqual(read(), 42)
        _testinternalcapi.clear_executor_deletion_list()
        self.assertIsNone(old())
        del namespace['module']
        with self.assertRaises(NameError):
            read()

    @disable_gc()
    def test_module_attribute_data_descriptor_after_call(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        module.value = 1000
        namespace = {'module': module}
        exec('def read(callback):\n'
             '    first = module.value\n'
             '    callback()\n'
             '    return first, module.value\n', namespace)
        read = namespace['read']
        noop = lambda: None
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(noop, count))),
                         [(1000, 1000)] * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_ATTR_MODULE' if Py_GIL_DISABLED else
                      '_LOAD_ATTR_MODULE_CONST', get_opnames(executor))

        class ChangedModule(types.ModuleType):
            @property
            def value(self):
                return 2000

        def change_class():
            module.__class__ = ChangedModule

        self.assertEqual(read(change_class), (1000, 2000))
        for _ in range(100):
            self.assertEqual(read(noop), (2000, 2000))

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'Module constant folding requires the GIL')
    def test_module_constant_replacement_lifetime(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        original = make_global_constant()
        module.value = original
        namespace = {'module': module}
        exec('def read():\n    return module.value\n', namespace)
        read = namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        list(itertools.starmap(read, itertools.repeat((), count)))
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_ATTR_MODULE_CONST', get_opnames(executor))
        events = []
        reference = weakref.ref(original, lambda _: events.append(read()))
        del original
        module.value = 'replacement'
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(events, ['replacement'])
        self.assertFalse(executor.is_valid())

    @disable_gc()
    def test_generator_osr_suspends_and_returns(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def generate(count):
            for index in range(count):
                total = 0
                for value in range(64):
                    total += value
                yield total + index
            return 'finished'

        count = TIER2_THRESHOLD * 2
        reset_code(generate)
        iterator = generate(count)
        for index in range(count):
            self.assertEqual(next(iterator), 2016 + index)
        executor = get_first_executor(generate)
        self.assertIsNotNone(executor)
        self.assertTrue(executor.is_valid())
        self.assertIn('_YIELD_VALUE', get_opnames(executor))
        self.assertIn('_METHOD_YIELD_EXIT', get_opnames(executor))
        self.assertNotIn('_RETURN_VALUE', get_opnames(executor))
        with self.assertRaises(StopIteration) as caught:
            next(iterator)
        self.assertEqual(caught.exception.value, 'finished')
        self.assertIsNone(iterator.gi_frame)

    @disable_gc()
    def test_generator_osr_send_throw_close(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        closed = []
        def generate():
            value = 1
            try:
                while True:
                    for index in range(64):
                        value += index
                    try:
                        incoming = yield value
                    except ValueError:
                        value = -1
                    else:
                        if incoming is not None:
                            value = incoming
            finally:
                closed.append(value)

        reset_code(generate)
        iterator = generate()
        for index in range(100):
            self.assertEqual(next(iterator), 1 + (index + 1) * 2016)
        self.assertIsNotNone(get_first_executor(generate))
        self.assertEqual(iterator.send(0.5), 2016.5)
        self.assertEqual(iterator.throw(ValueError), 2015)
        iterator.close()
        self.assertEqual(closed, [2015])
        iterator.close()
        self.assertEqual(closed, [2015])

    @disable_gc()
    def test_generator_osr_suspended_locals_change(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def generate():
            value = 1
            for index in range(TIER2_THRESHOLD * 3):
                yield value + 1

        reset_code(generate)
        iterator = generate()
        self.addCleanup(iterator.close)
        for _ in range(TIER2_THRESHOLD * 2):
            self.assertEqual(next(iterator), 2)
        self.assertIsNotNone(get_first_executor(generate))
        iterator.gi_frame.f_locals['value'] = 0.5
        self.assertEqual(next(iterator), 1.5)
        class Number:
            def __add__(self, other):
                return 42
        iterator.gi_frame.f_locals['value'] = Number()
        self.assertEqual(next(iterator), 42)

    @disable_gc()
    def test_generator_osr_callee_invalidation(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def leaf(value):\n'
             '    return value + 1\n'
             'def generate(count):\n'
             '    for value in range(count):\n'
             '        yield leaf(value)\n'
             'def replacement(value):\n'
             '    return value - 1\n', namespace)
        count = TIER2_RESUME_THRESHOLD + 10
        list(map(namespace['leaf'], range(count)))
        generate = namespace['generate']
        iterator = generate(count * 2)
        self.addCleanup(iterator.close)
        for index in range(count):
            self.assertEqual(next(iterator), index + 1)
        self.assertIsNotNone(get_first_executor(generate))
        namespace['leaf'].__code__ = namespace['replacement'].__code__
        self.assertEqual(next(iterator), count - 1)

    @disable_gc()
    def test_generator_iteration_compiles_static_continuation(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def generate(count):
            for index in range(count):
                yield index
        def consume(count):
            total = 0
            for value in generate(count):
                total += value
            return total
        count = TIER2_THRESHOLD * 3
        reset_code(generate)
        reset_code(consume)
        self.assertEqual(consume(count), count * (count - 1) // 2)
        instructions = list(dis.get_instructions(consume))
        continuation = next(instructions[index + 1].offset
                            for index, instruction in enumerate(instructions)
                            if instruction.opname == 'FOR_ITER')
        executor = _opcode.get_executor(consume.__code__, continuation)
        self.assertTrue(executor.is_valid())
        self.assertNotIn('_METHOD_DEOPT', get_opnames(executor))
        self.assertEqual(consume(5), 10)

    @disable_gc()
    def test_generator_continuation_preserves_exceptions_and_invalidation(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('marker = 1\n'
             'def consume(iterator):\n'
             '    total = 0\n'
             '    for value in iterator:\n'
             '        total += value + marker\n'
             '    return total\n', namespace)
        consume = namespace['consume']
        def generate(count):
            yield from range(count)
        count = TIER2_THRESHOLD * 3
        self.assertEqual(consume(generate(count)), count * (count + 1) // 2)
        self.assertIsNotNone(get_first_executor(consume))
        def change_binding():
            yield 2
            namespace['marker'] = 10
            yield 3
        self.assertEqual(consume(change_binding()), 16)
        def fail():
            yield 2
            raise ValueError('iteration failed')
        with self.assertRaisesRegex(ValueError, 'iteration failed'):
            consume(fail())
        with self.assertRaises(TypeError):
            consume(iter([None]))
        self.assertEqual(consume(generate(5)), 60)

    @disable_gc()
    def test_generator_continuation_retirement_preserves_bytecode(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def consume(iterator):
            total = 0
            for value in iterator:
                if value < 0:
                    raise ValueError(value)
                total += value
            return total
        def generate(values):
            yield from values
        reset_code(consume)
        reset_code(generate)
        self.enterContext(clear_executors(consume))
        self.enterContext(clear_executors(generate))
        count = TIER2_THRESHOLD * 3
        self.assertEqual(consume(generate(range(count))), count * (count - 1) // 2)
        instructions = list(dis.get_instructions(consume))
        continuation = next(instructions[index + 1].offset
                            for index, instruction in enumerate(instructions)
                            if instruction.opname == 'FOR_ITER')
        executor = _opcode.get_executor(consume.__code__, continuation)
        self.assertIn('_METHOD_DEOPT', get_opnames(executor))
        for _ in range(256):
            with self.assertRaises(ValueError) as raised:
                consume(generate([-1]))
            self.assertEqual(raised.exception.args, (-1,))
        self.assertFalse(executor.is_valid())
        # A continuation starts at an ordinary store, without an adaptive
        # backoff counter. Retirement must not overwrite the next opcode.
        self.assertEqual(consume(generate(range(5))), 10)

    @disable_gc()
    def test_generator_continuation_entry_guard_makes_progress(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def consume(iterator):
            total = 0
            for left, right in iterator:
                total += left + right
            return total
        def generate(values):
            yield from values
        self.enterContext(clear_executors(consume))
        self.enterContext(clear_executors(generate))
        count = TIER2_THRESHOLD * 3
        self.assertEqual(consume(generate([(1, 2)] * count)), 3 * count)
        self.assertIsNotNone(get_first_executor(consume))
        # The entry is an UNPACK_SEQUENCE specialized for tuples. Its guard
        # must execute the original operation in Tier 1 on a list, rather
        # than re-entering the same executor with unchanged inputs.
        self.assertEqual(consume(generate([[3, 4], (5, 6)])), 18)
        with self.assertRaises(ValueError):
            consume(generate([(1, 2, 3)]))
        self.assertEqual(consume(generate([(7, 8)])), 15)

    @disable_gc()
    def test_generator_continuation_unpack_preserves_finalizers(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        events = []
        class Tracked:
            def __init__(self, name):
                self.name = name
            def __del__(self):
                variables = sys._getframe(1).f_locals
                events.append((self.name, tuple(type(variables[name]).__name__
                                               for name in ('first', 'second', 'third'))))
        def consume(iterator):
            total = 0
            for first, second, third in iterator:
                total += 1
            return total, first, second, third
        def generate(values):
            yield from values
        self.enterContext(clear_executors(consume))
        self.enterContext(clear_executors(generate))
        count = TIER2_THRESHOLD * 3
        self.assertEqual(consume(generate([(0, 0, 0)] * count)), (count, 0, 0, 0))
        executor = get_first_executor(consume)
        self.assertIsNotNone(executor)
        self.assertNotIn('_UNPACK_TUPLE_TO_FAST_3', get_opnames(executor))
        def values():
            yield Tracked('first'), Tracked('second'), Tracked('third')
            yield 1, 2, 3
        self.assertEqual(consume(values()), (2, 1, 2, 3))
        self.assertEqual(events, [('first', ('int', 'Tracked', 'Tracked')),
                                  ('second', ('int', 'int', 'Tracked')),
                                  ('third', ('int', 'int', 'int'))])

    @disable_gc()
    def test_generator_continuation_skips_single_collection_operation(self):
        import builtins
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for kind, opname in (('list', 'LIST_APPEND'), ('set', 'SET_ADD')):
            with self.subTest(kind=kind):
                namespace = {}
                exec(f'def collect(count):\n'
                     f'    return {kind}(value + 1 for value in range(count))\n',
                     namespace)
                collect = namespace['collect']
                self.enterContext(clear_executors(collect))
                count = TIER2_THRESHOLD * 3
                self.assertEqual(collect(count), getattr(builtins, kind)(range(1, count + 1)))
                entries = [instruction.offset for instruction in
                           dis.get_instructions(collect) if instruction.opname == opname]
                self.assertTrue(entries)
                for offset in entries:
                    with self.assertRaises(ValueError):
                        _opcode.get_executor(collect.__code__, offset)

    @disable_gc()
    def test_generator_resume_does_not_compile_empty_prefix(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def generate(count):
            for value in range(count):
                yield value
        def forward(iterator):
            for value in iterator:
                yield value + 1
        reset_code(generate)
        reset_code(forward)
        resume = next(instruction.offset for instruction in
                      dis.get_instructions(forward)
                      if instruction.opname == 'RESUME' and instruction.arg & 3 == 1)
        count = TIER2_RESUME_THRESHOLD * 3
        iterator = forward(generate(count))
        self.addCleanup(iterator.close)
        for value in range(count):
            self.assertEqual(next(iterator), value + 1)
            # This entry only discards the sent value and jumps to a
            # generator iteration that Tier 1 must execute. The compiled
            # body after that exit would be unreachable from this entry.
            with self.assertRaises(ValueError):
                _opcode.get_executor(forward.__code__, resume)
        with self.assertRaises(StopIteration):
            next(iterator)
        # A supported iterator specialization makes the same entry useful.
        # Backoff must not permanently suppress compilation after that change.
        self.assertEqual(list(forward(range(count))), list(range(1, count + 1)))
        executor = _opcode.get_executor(forward.__code__, resume)
        self.assertIn('_YIELD_VALUE', get_opnames(executor))

    def check_partial_loop_retirement(self, iterations, expected_valid):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def work(count):\n'
             '    total = 0\n'
             '    for value in range(count):\n'
             '        total += value\n'
             '    raise ValueError(total)\n', namespace)
        work = namespace['work']
        executor = None
        for _ in range(TIER2_THRESHOLD):
            with self.assertRaises(ValueError) as raised:
                work(32)
            self.assertEqual(raised.exception.args, (496,))
            executor = get_first_executor(work)
            if executor is not None:
                break
        self.assertIsNotNone(executor)
        self.assertTrue(executor.is_valid())
        self.assertIn('_METHOD_DEOPT', get_opnames(executor))
        for _ in range(64):
            with self.assertRaises(ValueError) as raised:
                work(iterations)
            self.assertEqual(raised.exception.args,
                             (iterations * (iterations - 1) // 2,))
        self.assertEqual(executor.is_valid(), expected_valid)

    @disable_gc()
    def test_partial_method_keeps_completed_loops(self):
        self.check_partial_loop_retirement(32, True)

    @disable_gc()
    def test_partial_method_retires_without_loop_progress(self):
        self.check_partial_loop_retirement(1, False)

    @disable_gc()
    def test_osr_loop_precedes_large_outer_body(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        source = ('def leaf(value):\n'
                  '    return value + 1\n'
                  'def work(count):\n'
                  '    total = 0\n'
                  '    for outer in range(count):\n')
        source += '        total += leaf(1)\n' * 100
        source += ('        for inner in range(128):\n'
                   '            total += inner\n'
                   '    return total\n')
        exec(source, namespace)
        work = namespace['work']
        self.assertEqual(work(80), 80 * (200 + 127 * 128 // 2))
        executor = get_first_executor(work)
        self.assertIsNotNone(executor)
        self.assertTrue(executor.is_valid())
        opnames = get_opnames(executor)
        self.assertIn('_METHOD_DEOPT', opnames)
        self.assertIn('_METHOD_CHECK_PERIODIC', opnames)
        self.assertEqual(work(2), 2 * (200 + 127 * 128 // 2))
        self.assertTrue(executor.is_valid())

    @disable_gc()
    def test_range_items_need_compact_integer_guards(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def sum_range(start, count):
            total = 0
            for value in range(start, start + count):
                if value >= 0:
                    total += value
            return total

        # A FOR_ITER_RANGE result is a C long, which may need several Python
        # digits. A block boundary must not silently mark it as compact.
        count = TIER2_THRESHOLD * 4
        self.assertEqual(sum_range(0, count), count * (count - 1) // 2)
        self.assertIsNotNone(get_first_executor(sum_range))
        for start in (1 << 30, 1 << 40, 1 << 60, -(1 << 40)):
            with self.subTest(start=start):
                expected = (count * start + count * (count - 1) // 2
                            if start >= 0 else 0)
                self.assertEqual(sum_range(start, count), expected)

        def count_small(start, count):
            total = 0
            for value in range(start, start + count):
                if value < 5:
                    total += 1
            return total

        for start in (1 << 30, -(1 << 30), 1 << 40, -(1 << 40), 1 << 60):
            with self.subTest(comparison_start=start):
                # Each boundary must enter freshly compiled code: an earlier
                # guard miss could otherwise hide an incorrect later case.
                reset_code(count_small)
                self.assertEqual(count_small(0, count), 5)
                self.assertIsNotNone(get_first_executor(count_small))
                self.assertEqual(count_small(start, count), count if start < 0 else 0)

    @disable_gc()
    def test_range_compact_guard_before_advancing(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def collect(start, stop, step):
            result = []
            for value in range(start, stop, step):
                result.append(value + 1)
            return result

        limit = 1 << sys.int_info.bits_per_digit
        count = TIER2_THRESHOLD * 2
        for start, stop, step in ((limit - 3, limit + 4, 1),
                                  (-limit + 3, -limit - 4, -1),
                                  (limit + 3, limit - 4, -1),
                                  (-limit - 3, -limit + 4, 1),
                                  (-7, 2, 1), (254, 260, 1)):
            with self.subTest(start=start, step=step):
                reset_code(collect)
                self.assertEqual(collect(0, count, 1), list(range(1, count + 1)))
                executor = get_first_executor(collect)
                self.assertIsNotNone(executor)
                self.assertIn('_ITER_NEXT_RANGE_COMPACT', get_opnames(executor))
                self.assertEqual(collect(start, stop, step),
                                 [value + 1 for value in range(start, stop, step)])

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, 'A shared range iterator stays in Tier 1')
    def test_generator_range_compact_guard_after_setstate(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def generate(iterator):
            for value in iterator:
                yield value + 1

        reset_code(generate)
        count = TIER2_THRESHOLD * 2
        self.assertEqual(list(generate(iter(range(count)))), list(range(1, count + 1)))
        self.assertTrue(any('_ITER_NEXT_RANGE_COMPACT' in get_opnames(executor)
                            for executor in get_all_executors(generate)))
        limit = 1 << sys.int_info.bits_per_digit
        iterator = iter(range(limit + 4))
        generator = generate(iterator)
        self.assertEqual(next(generator), 1)
        # __setstate__ advances relative to the remaining range, whose start
        # is now 1. Resume just below the compact-integer boundary.
        iterator.__setstate__(limit - 3)
        self.assertEqual(list(generator), list(range(limit - 1, limit + 5)))
        self.assertIsNone(next(iterator, None))

    def check_inline_argument_types(self, method):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        if method:
            exec('class Container:\n'
                 '    def __getitem__(self, key):\n'
                 '        return isinstance(key, tuple)\n'
                 'def read(container):\n'
                 '    return container[7]\n'
                 'def replacement(self, key):\n'
                 '    return isinstance(key, int)\n', namespace)
            container = namespace['Container']()
            callee = namespace['Container'].__getitem__
            callee_args = (container, 7)
            caller_args = (container,)
        else:
            exec('def value(key):\n'
                 '    return isinstance(key, tuple)\n'
                 'def read():\n'
                 '    return value(7)\n'
                 'def replacement(key):\n'
                 '    return isinstance(key, int)\n', namespace)
            callee = namespace['value']
            callee_args = (7,)
            caller_args = ()
        read = namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(
            callee, itertools.repeat(callee_args, count))), [False] * count)
        self.assertEqual(list(itertools.starmap(
            read, itertools.repeat(caller_args, count))), [False] * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        opnames = get_opnames(executor)
        self.assertIn('_PUSH_FRAME', opnames)
        self.assertNotIn('_METHOD_CALL', opnames)
        self.assertNotIn('_CALL_ISINSTANCE', opnames)
        callee.__code__ = namespace['replacement'].__code__
        self.assertTrue(read(*caller_args))

    @disable_gc()
    def test_inline_argument_types_from_caller(self):
        self.check_inline_argument_types(False)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static Python subscript inlining requires the GIL")
    def test_inline_subscript_argument_types_from_caller(self):
        self.check_inline_argument_types(True)

    @disable_gc()
    def test_inline_argument_types_with_positional_defaults(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def classify(value, extra=7):\n'
             '    return isinstance(value, bytes), extra\n'
             'def read():\n'
             '    return classify(b"value")\n'
             'def replacement(value, extra=7):\n'
             '    return isinstance(value, str), extra\n', namespace)
        classify, read = namespace['classify'], namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(classify, itertools.repeat(b'value', count))),
                         [(True, 7)] * count)
        self.assertEqual(list(itertools.starmap(read, itertools.repeat((), count))),
                         [(True, 7)] * count)
        opnames = get_opnames(get_first_executor(read))
        self.assertIn('_PY_FRAME_GENERAL', opnames)
        self.assertIn('_PUSH_FRAME', opnames)
        self.assertNotIn('_CALL_ISINSTANCE', opnames)
        classify.__defaults__ = ('changed',)
        self.assertEqual(read(), (True, 'changed'))
        classify.__code__ = namespace['replacement'].__code__
        self.assertEqual(read(), (False, 'changed'))

    @disable_gc()
    def test_inline_module_call_keeps_mutable_keyword_defaults(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        namespace = {'module': module}
        exec('def classify(value, *, expected=int):\n'
             '    return isinstance(value, bytes), isinstance(value, expected)\n'
             'def read():\n'
             '    return module.classify(b"value")\n', namespace)
        classify, read = namespace['classify'], namespace['read']
        module.classify = classify
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(classify, itertools.repeat(b'value', count))),
                         [(True, False)] * count)
        self.assertEqual(list(itertools.starmap(read, itertools.repeat((), count))),
                         [(True, False)] * count)
        opnames = get_opnames(get_first_executor(read))
        self.assertIn('_PY_FRAME_GENERAL', opnames)
        self.assertIn('_PUSH_FRAME', opnames)
        self.assertEqual(opnames.count('_CALL_ISINSTANCE'), 1)
        # In-place mutation need not change the function version. Only the
        # explicitly supplied argument has a type proved by the caller.
        classify.__kwdefaults__['expected'] = bytes
        self.assertEqual(read(), (True, True))
        module.classify = lambda value: ('replacement', value)
        self.assertEqual(read(), ('replacement', b'value'))

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static namespace hints require the GIL")
    def test_module_call_after_function_cache_eviction(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        namespace = {'module': module}
        exec('def classify(value, extra=7):\n'
             '    return isinstance(value, bytes), extra\n'
             'def read():\n'
             '    return module.classify(b"value")\n', namespace)
        classify, read = namespace['classify'], namespace['read']
        module.classify = classify
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(classify, itertools.repeat(b'value', count))),
                         [(True, 7)] * count)
        _testinternalcapi.clear_function_version_cache()
        self.assertEqual(list(itertools.starmap(read, itertools.repeat((), count))),
                         [(True, 7)] * count)
        opnames = get_opnames(get_first_executor(read))
        self.assertIn('_CHECK_FUNCTION_VERSION', opnames)
        self.assertIn('_PUSH_FRAME', opnames)
        self.assertNotIn('_METHOD_CALL', opnames)
        self.assertNotIn('_CALL_ISINSTANCE', opnames)
        # The namespace is a compile-time hint, not a constant binding.
        module.classify = lambda value: ('changed', value)
        self.assertEqual(read(), ('changed', b'value'))
        other = types.ModuleType('replacement')
        other.classify = lambda value: 42
        namespace['module'] = other
        self.assertEqual(read(), 42)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static namespace hints require the GIL")
    def test_module_binding_hint_never_calls_key_equality(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        module = types.ModuleType('subject')
        namespace = {'module': module}
        exec('def classify(value):\n'
             '    return value + 1\n'
             'def read(use_module):\n'
             '    if use_module:\n'
             '        return module.classify(7)\n'
             '    return False\n', namespace)
        module.classify = namespace['classify']
        read = namespace['read']
        self.assertEqual(list(map(read, itertools.repeat(True, 16))), [8] * 16)
        self.assertIsNone(get_first_executor(read))
        events = []

        class Key:
            def __hash__(self):
                return hash('classify')

            def __eq__(self, other):
                events.append(other)
                return False

        other = types.ModuleType('replacement')
        other.__dict__[Key()] = None
        namespace['module'] = other
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(False, count))),
                         [False] * count)
        self.assertIsNotNone(get_first_executor(read))
        # The attribute arm is not executed. Compiling it must not perform
        # a generic lookup in the replacement module's mixed-key namespace.
        self.assertEqual(events, [])

    @disable_gc()
    def test_method_property_reinitialization_and_exceptions(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        events = []

        def original(owner):
            events.append('original')
            return 1

        def replacement(owner):
            events.append('replacement')
            return 2

        def failing(owner):
            events.append('failing')
            raise ValueError('getter failed')

        class Owner:
            value = property(original)

        def read(owner):
            return owner.value + 10

        owner = Owner()
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(owner, count))),
                         [11] * count)
        self.assertEqual(events, ['original'] * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_LOAD_ATTR', get_opnames(executor))
        events.clear()
        Owner.value.__init__(replacement)
        self.assertEqual(read(owner), 12)
        self.assertEqual(events, ['replacement'])
        Owner.value.__init__(failing)
        with self.assertRaisesRegex(ValueError, 'getter failed'):
            read(owner)
        self.assertEqual(events, ['replacement', 'failing'])
        self.assertTrue(executor.is_valid())

    @disable_gc()
    def test_inline_argument_types_keep_unknown_inputs(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def classify(value):\n'
             '    return isinstance(value, int)\n'
             'def read(value):\n'
             '    return classify(value)\n', namespace)
        count = TIER2_RESUME_THRESHOLD + 10
        classify, read = namespace['classify'], namespace['read']
        self.assertEqual(list(map(classify, itertools.repeat(1, count))),
                         [True] * count)
        self.assertEqual(list(map(read, itertools.repeat(1, count))),
                         [True] * count)
        opnames = get_opnames(get_first_executor(read))
        self.assertIn('_PUSH_FRAME', opnames)
        self.assertIn('_CALL_ISINSTANCE', opnames)
        self.assertFalse(read(1.5))

        class ReportedType:
            reported_type = int

            @property
            def __class__(self):
                return self.reported_type

        value = ReportedType()
        self.assertTrue(read(value))
        value.reported_type = str
        self.assertFalse(read(value))

    @disable_gc()
    def test_inline_argument_type_after_module_class_change(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def classify(value):\n'
             '    return isinstance(value, int)\n'
             'def read():\n'
             '    return classify("module constant")\n', namespace)
        module = types.ModuleType('subject')
        classify, read = namespace['classify'], namespace['read']
        read.__code__ = read.__code__.replace(co_consts=tuple(
            module if value == 'module constant' else value
            for value in read.__code__.co_consts))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(classify, itertools.repeat(module, count))),
                         [False] * count)
        self.assertEqual(list(itertools.starmap(read, itertools.repeat((), count))),
                         [False] * count)
        self.assertIsNotNone(get_first_executor(read))

        class Pretender(types.ModuleType):
            def __getattribute__(self, name):
                if name == '__class__':
                    return int
                return super().__getattribute__(name)

        # The builtin module type is immutable, but its instances may change
        # __class__. A constant reference does not imply an immutable type.
        module.__class__ = Pretender
        self.assertTrue(classify(module))
        self.assertTrue(read())

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static Python subscript inlining requires the GIL")
    def test_python_subscript_static_inline(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('class Container:\n'
             '    def __getitem__(self, key):\n'
             '        return key + 1\n'
             'def read(container, key):\n'
             '    value = container[key]\n'
             '    return value + 5\n', namespace)
        container = namespace['Container']()
        read = namespace['read']
        for _ in range(TIER2_THRESHOLD):
            self.assertEqual(container[2], 3)
        _testinternalcapi.clear_function_version_cache()
        # Enter read through map so this test's own CFG cannot inline it and
        # prevent its standalone method entry from becoming hot.
        for value in map(read, itertools.repeat(container, TIER2_RESUME_THRESHOLD + 10),
                         itertools.repeat(2, TIER2_RESUME_THRESHOLD + 10)):
            self.assertEqual(value, 8)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        opnames = get_opnames(executor)
        self.assertIn('_METHOD_SUBSCR_CHECK_FUNC', opnames)
        self.assertIn('_BINARY_OP_SUBSCR_INIT_CALL', opnames)
        self.assertIn('_PUSH_FRAME', opnames)
        self.assertNotIn('_METHOD_CALL', opnames)
        self.assertEqual(count_return_ops(opnames), 2)

        # Refresh the type's shared specialization cache from another site
        # before reentering the compiled caller with a changed function body.
        def replacement(self, key):
            return key + 10
        type(container).__getitem__.__code__ = replacement.__code__
        for _ in range(TIER2_THRESHOLD):
            self.assertEqual(container[2], 12)
        self.assertEqual(read(container, 2), 17)

        class Other:
            def __getitem__(self, key):
                return key + 20
        self.assertEqual(read(Other(), 2), 27)
        self.assertEqual(read([10, 20, 30], 2), 35)
        with self.assertRaises(IndexError):
            read([], 2)
        type(container).__getitem__ = lambda self, key: key + 30
        self.assertEqual(read(container, 2), 37)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static Python subscript inlining requires the GIL")
    def test_python_subscript_inline_exception_and_frame(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        events = []
        def observe(key):
            frame = sys._getframe(1)
            events.append((frame.f_code.co_name, frame.f_back.f_code.co_name, key))
            if key < 0:
                raise ValueError(key)
            return key + 1
        namespace = {'observe': observe}
        exec('class Container:\n'
             '    def __getitem__(self, key):\n'
             '        return observe(key)\n'
             'def read(container, key):\n'
             '    value = container[key]\n'
             '    return value + 5\n', namespace)
        container = namespace['Container']()
        read = namespace['read']
        for _ in range(TIER2_THRESHOLD):
            self.assertEqual(container[2], 3)
        for value in map(read, itertools.repeat(container, TIER2_RESUME_THRESHOLD + 10),
                         itertools.repeat(2, TIER2_RESUME_THRESHOLD + 10)):
            self.assertEqual(value, 8)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_METHOD_SUBSCR_CHECK_FUNC', get_opnames(executor))
        events.clear()
        self.assertEqual(read(container, 4), 10)
        self.assertEqual(events, [('__getitem__', 'read', 4)])
        events.clear()
        with self.assertRaisesRegex(ValueError, '-1'):
            read(container, -1)
        self.assertEqual(events, [('__getitem__', 'read', -1)])

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static Python subscript inlining requires the GIL")
    def test_python_subscript_inline_recursion_limit(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('class Container:\n'
             '    def __getitem__(self, key):\n'
             '        if key <= 0:\n'
             '            return 0\n'
             '        return self[key - 1] + 1\n'
             'def read(container, key):\n'
             '    return container[key]\n', namespace)
        container = namespace['Container']()
        read = namespace['read']
        for value in map(read, itertools.repeat(container, TIER2_RESUME_THRESHOLD + 10),
                         itertools.repeat(10, TIER2_RESUME_THRESHOLD + 10)):
            self.assertEqual(value, 10)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_METHOD_SUBSCR_CHECK_FUNC', get_opnames(executor))
        with self.assertRaises(RecursionError):
            read(container, sys.getrecursionlimit() + 10)
        self.assertEqual(read(container, 10), 10)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Static Python subscript inlining requires the GIL")
    def test_python_subscript_forgets_receiver_guards(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('class First:\n'
             '    pass\n'
             'class Second:\n'
             '    @property\n'
             '    def value(self):\n'
             '        return 100\n'
             'class Container:\n'
             '    change = False\n'
             '    def __getitem__(self, owner):\n'
             '        if self.change:\n'
             '            owner.__class__ = Second\n'
             '        return 0\n'
             'def read(owner, container):\n'
             '    first = owner.value\n'
             '    container[owner]\n'
             '    return first + owner.value\n', namespace)
        owner = namespace['First']()
        owner.value = 1
        container = namespace['Container']()
        # Specialize both callee arms before compiling the caller.
        container.change = True
        for _ in range(_testinternalcapi.SPECIALIZATION_THRESHOLD):
            container[owner]
            owner.__class__ = namespace['First']
        container.change = False
        read = namespace['read']
        count = TIER2_RESUME_THRESHOLD + 10
        for value in map(read, itertools.repeat(owner, count),
                         itertools.repeat(container, count)):
            self.assertEqual(value, 2)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_METHOD_SUBSCR_CHECK_FUNC', get_opnames(executor))
        container.change = True
        self.assertEqual(read(owner, container), 101)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Non-immortal callable constants require the GIL")
    def test_known_functions_inline_after_version_cache_eviction(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for method in (False, True):
            with self.subTest(method=method):
                namespace = {}
                if method:
                    exec('class Base:\n'
                         '    def value(self, arg):\n'
                         '        return arg + 1\n'
                         'class First(Base):\n'
                         '    pass\n'
                         'class Second(Base):\n'
                         '    pass\n'
                         'def call(obj, arg):\n'
                         '    return obj.value(arg)\n', namespace)
                    first, second = namespace['First'](), namespace['Second']()
                    # Populate both receiver versions and warm the callee.
                    first.value
                    second.value
                    callee = namespace['Base'].value
                    callee_args = (first, 10)
                    caller_args = callee_args
                else:
                    exec('def value(arg):\n'
                         '    return arg + 1\n'
                         'def call(arg):\n'
                         '    return value(arg)\n', namespace)
                    callee = namespace['value']
                    callee_args = caller_args = (10,)
                call = namespace['call']
                self.enterContext(clear_executors(call))
                count = TIER2_RESUME_THRESHOLD + 10
                self.assertEqual(list(itertools.starmap(
                    callee, itertools.repeat(callee_args, count))), [11] * count)
                # Cache eviction must not invalidate the live function's
                # version or prevent a statically known call from inlining.
                _testinternalcapi.clear_function_version_cache()
                self.assertEqual(list(itertools.starmap(
                    call, itertools.repeat(caller_args, count))), [11] * count)
                names = get_opnames(get_first_executor(call))
                self.assertIn('_PUSH_FRAME', names)
                self.assertNotIn('_METHOD_CALL', names)
                self.assertEqual(count_return_ops(names), 2)
                if method:
                    self.assertEqual(call(second, 20), 21)
                    exec('def replacement(self, arg):\n'
                         '    return arg + 2\n', namespace)
                else:
                    exec('def replacement(arg):\n'
                         '    return arg + 2\n', namespace)
                callee.__code__ = namespace['replacement'].__code__
                self.assertEqual(call(*caller_args), 12)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Attribute family guards require the GIL")
    def test_repeated_attribute_family_guard(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for slots in (False, True):
            with self.subTest(slots=slots):
                class Base:
                    if slots:
                        __slots__ = ('a', 'b', 'c')
                class First(Base):
                    __slots__ = ()
                class Second(Base):
                    __slots__ = ()
                first, second = First(), Second()
                for obj in (first, second):
                    obj.a, obj.b, obj.c = 1, 2, 3
                    # Populate both type versions before compiling read().
                    self.assertEqual(obj.a, 1)
                namespace = {}
                exec('def read(obj):\n'
                     '    return obj.a + obj.b + obj.c\n', namespace)
                read = namespace['read']
                self.enterContext(clear_executors(read))
                count = TIER2_RESUME_THRESHOLD + 10
                self.assertEqual(list(map(read, itertools.repeat(first, count))),
                                 [6] * count)
                names = get_opnames(get_first_executor(read))
                self.assertEqual(names.count('_GUARD_TYPE_VERSION_FAMILY'), 1)
                for obj in (first, second):
                    self.assertEqual(read(obj), 6)
                seen = []
                def getter(obj):
                    seen.append(sys._getframe(1).f_code)
                    return 20
                Second.b = property(getter)
                self.assertEqual(read(second), 24)
                self.assertEqual(seen, [read.__code__])
                self.assertEqual(read(first), 6)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Attribute family guards require the GIL")
    def test_attribute_family_facts_do_not_cross_calls(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Base:
            pass
        class First(Base):
            pass
        class Second(Base):
            pass
        first, second = First(), Second()
        for obj in (first, second):
            obj.a, obj.b = 1, 2
            self.assertEqual(obj.a, 1)
        namespace = {}
        exec('def read(obj, callback):\n'
             '    before = obj.a\n'
             '    callback()\n'
             '    return before + obj.b\n', namespace)
        read = namespace['read']
        self.enterContext(clear_executors(read))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(
            read, itertools.repeat((first, lambda: None), count))), [3] * count)
        names = get_opnames(get_first_executor(read))
        self.assertEqual(names.count('_GUARD_TYPE_VERSION_FAMILY'), 2)
        class Changed:
            @property
            def b(self):
                return 20
        def change():
            first.__class__ = Changed
        self.assertEqual(read(first, change), 21)
        self.assertEqual(read(second, lambda: None), 3)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Attribute family guards require the GIL")
    def test_overlapping_attribute_families_keep_distinct_guards(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Base:
            pass
        class First(Base):
            pass
        class Second(Base):
            pass
        class Third(Base):
            pass
        first, second, third = First(), Second(), Third()
        first.a, first.b = 1, 2
        second.a, second.other, second.b = 10, 99, 20
        third.other, third.b, third.a = 99, 200, 100
        for obj in (first, second, third):
            getattr(obj, 'a')
        namespace = {}
        exec('def read(obj):\n'
             '    return obj.a + obj.b\n', namespace)
        read = namespace['read']
        self.enterContext(clear_executors(read))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(first, count))),
                         [3] * count)
        names = get_opnames(get_first_executor(read))
        self.assertEqual(names.count('_GUARD_TYPE_VERSION_FAMILY'), 2)
        self.assertEqual(read(second), 30)
        self.assertEqual(read(third), 300)

    @disable_gc()
    def test_nested_inline_loop_growth_preserves_return_target(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Output(list):
            pass
        namespace = {}
        exec('def leaf(values, output):\n'
             '    for value in values:\n'
             '        output.append(value)\n'
             'def middle(values, output):\n'
             '    if not values:\n'
             '        return\n'
             '    leaf(values, output)\n'
             'def caller(values, output):\n'
             '    middle(values, output)\n'
             '    return len(output)\n', namespace)
        leaf, middle, caller = (namespace[n] for n in ('leaf', 'middle', 'caller'))
        self.enterContext(clear_executors(caller))
        for _ in range(4):
            leaf((1, 2), Output())
            middle((1, 2), Output())
            middle((), Output())
        output = Output()
        count = TIER2_RESUME_THRESHOLD + 10
        results = list(itertools.starmap(
            caller, itertools.repeat(((1, 2), output), count)))
        self.assertEqual(results, list(range(2, 2 * count + 1, 2)))
        self.assertEqual(output, [1, 2] * count)
        names = get_opnames(get_first_executor(caller))
        self.assertEqual(names.count('_PUSH_FRAME'), 2)
        self.assertNotIn('_METHOD_CALL', names)
        self.assertEqual(caller((), output), 2 * count)
        with self.assertRaises(TypeError):
            caller(1, output)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Attribute family guards require the GIL")
    def test_small_shared_setter_keeps_attribute_family(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Base:
            pass
        class First(Base):
            pass
        class Second(Base):
            pass
        namespace = {}
        exec('def store(obj, value):\n'
             '    obj.value = value\n'
             'def caller(obj, value):\n'
             '    store(obj, value)\n'
             '    return obj.value\n', namespace)
        store, caller = namespace['store'], namespace['caller']
        self.enterContext(clear_executors(caller))
        first, second = First(), Second()
        for _ in range(100):
            store(first, 1)
            store(second, 2)
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(
            caller, itertools.repeat((first, 7), count))), [7] * count)
        names = get_opnames(get_first_executor(caller))
        self.assertIn('_PUSH_FRAME', names)
        self.assertIn('_GUARD_TYPE_VERSION_FAMILY', names)
        self.assertNotIn('_CALL_STORE_ATTRIBUTE', names)
        for value in range(100):
            self.assertEqual(caller(first, value), value)
            self.assertEqual(caller(second, value), value)
        seen = []
        def setter(obj, value):
            seen.append((value, sys._getframe(1).f_code))
        Second.value = property(lambda obj: 42, setter)
        self.assertEqual(caller(second, 9), 42)
        self.assertEqual(seen, [(9, store.__code__)])

    @disable_gc()
    def test_nested_inline_frames_and_callee_invalidation(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def leaf(value):\n'
             '    if value < 0:\n'
             '        raise LookupError("negative")\n'
             '    return value + 1\n'
             'def middle(value):\n'
             '    return leaf(value) * 2\n'
             'def caller(value):\n'
             '    return middle(value) + 3\n', namespace)
        leaf, middle, caller = (namespace[n] for n in ('leaf', 'middle', 'caller'))
        self.enterContext(clear_executors(caller))
        for _ in range(4):
            self.assertEqual(leaf(10), 11)
            self.assertEqual(middle(10), 22)
            with self.assertRaises(LookupError):
                leaf(-1)
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(caller, itertools.repeat(10, count))), [25] * count)
        executor = get_first_executor(caller)
        names = get_opnames(executor)
        self.assertEqual(names.count('_PUSH_FRAME'), 2)
        self.assertNotIn('_METHOD_CALL', names)
        self.assertEqual(count_return_ops(names), 3)
        frames = []
        class Number:
            def __lt__(self, other):
                return False
            def __add__(self, other):
                frame = sys._getframe(1)
                for _ in range(3):
                    frames.append(frame.f_code)
                    frame = frame.f_back
                return 7
        self.assertEqual(caller(Number()), 17)
        self.assertEqual(frames, [leaf.__code__, middle.__code__, caller.__code__])
        with self.assertRaises(LookupError) as caught:
            caller(-1)
        self.assertEqual(str(caught.exception), 'negative')
        def replacement(value):
            return 100
        leaf.__code__ = replacement.__code__
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(10), 203)

    @disable_gc()
    def test_folded_class_attribute_store_preserves_fallback_stack(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        class Constants:
            missing = 0
        class First:
            pass
        class Second:
            pass
        namespace = {'Constants': Constants}
        exec('def assign(obj):\n    obj.value = Constants.missing\n', namespace)
        assign = namespace['assign']
        self.enterContext(clear_executors(assign))
        first = First()
        count = TIER2_RESUME_THRESHOLD + 10
        list(map(assign, itertools.repeat(first, count)))
        self.assertIsNotNone(get_first_executor(assign))
        self.assertEqual(first.value, 0)
        second = Second()
        assign(second)
        self.assertEqual(second.value, 0)
        events = []
        class Watched:
            @property
            def value(self):
                return 99
            @value.setter
            def value(self, value):
                events.append((value, sys._getframe(1).f_code))
        assign(Watched())
        self.assertEqual(events, [(0, assign.__code__)])
        Constants.missing = 41
        assign(first)
        self.assertEqual(first.value, 41)
        del Constants.missing
        with self.assertRaises(AttributeError):
            assign(first)

    @disable_gc()
    def test_cold_scalar_arm_can_specialize_after_method_compilation(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def calculate(values, active):
            total = 0
            for value in values:
                if active:
                    if value:
                        total += value + 1
                    if total > 1000:
                        return total
            return total

        self.enterContext(clear_executors(calculate))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(
            calculate, itertools.repeat(([1, 2, 3], False), count))), [0] * count)
        self.assertIsNotNone(get_first_executor(calculate))
        # Compile both successors before the scalar arm has warmed up, then
        # make that arm hot. Its adaptive caches must still be able to learn.
        for _ in range(count):
            self.assertEqual(calculate([1, 2, 3], True), 9)
        names = [op for executor in get_all_executors(calculate)
                 for op in get_opnames(executor)]
        self.assertIn('_BINARY_OP_ADD_INT', names)
        self.assertIn('_COMPARE_OP_INT', names)
        self.assertIn('_TO_BOOL_INT', names)
        self.assertEqual(calculate([0, 1.5, 2.5], True), 6.0)
        self.assertEqual(calculate([10**100], True), 10**100 + 1)
        with self.assertRaises(TypeError):
            calculate([object()], True)
        self.assertEqual(calculate([object()], False), 0)

    @disable_gc()
    def test_static_super_with_unknown_class_cell(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        class Meta(type):
            pass

        class Collection(list, metaclass=Meta):
            def count_from_base(self, value):
                return super().count(value)

        values = Collection([1, 1, 2])
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(values.count_from_base,
                                  itertools.repeat(1, count))), [2] * count)
        self.assertIsNotNone(get_first_executor(Collection.count_from_base))
        values.append(1)
        self.assertEqual(values.count_from_base(1), 3)
        self.assertEqual(values.count_from_base(2), 1)
        class Raises:
            def __eq__(self, other):
                raise ValueError('comparison')
        with self.assertRaisesRegex(ValueError, 'comparison'):
            values.count_from_base(Raises())

    @disable_gc()
    def test_static_block_builtin_guards(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def calculate(values, count):
            total = 0
            for _ in range(count):
                total += len(values) + len((1, 2))
            return total

        self.enterContext(clear_executors(calculate))
        count = TIER2_THRESHOLD + 100
        self.assertEqual(calculate([1, 2, 3], count), 5 * count)
        executor = get_first_executor(calculate)
        self.assertIsNotNone(executor)
        self.assertNotIn('_GUARD_NOS_NULL', get_opnames(executor))
        self.assertEqual(calculate('abcd', count), 6 * count)
        class Sized:
            def __len__(self):
                return 7
        self.assertEqual(calculate(Sized(), count), 9 * count)
        with self.assertRaises(TypeError):
            calculate(None, count)

    @disable_gc()
    def test_static_block_replaces_local_facts(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def calculate(value):
            if value:
                previous = 1
                previous = value + 2
                return previous + 3
            return 0

        self.enterContext(clear_executors(calculate))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(calculate, itertools.repeat(1, count))),
                         [6] * count)
        self.assertIsNotNone(get_first_executor(calculate))
        self.assertEqual(calculate(0), 0)
        self.assertEqual(calculate(1.5), 6.5)
        self.assertEqual(calculate(2 ** 80), 2 ** 80 + 5)
        with self.assertRaises(TypeError):
            calculate('changed')

    @disable_gc()
    def test_static_callee_cfg_growth_preserves_branch_targets(self):
        namespace = {}
        exec("def callee(values, which):\n"
             "    if which:\n"
             "        return len(values) + 1\n"
             "    return len(values) + 2\n"
             "def caller(values, which):\n"
             "    return callee(values, which) + 3\n", namespace)
        callee, caller = namespace['callee'], namespace['caller']
        self.enterContext(clear_executors(callee))
        self.enterContext(clear_executors(caller))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(callee,
                         itertools.repeat(([1, 2], True), count))), [3] * count)
        self.assertEqual(list(itertools.starmap(caller,
                         itertools.repeat(([1, 2], True), count))), [6] * count)
        self.assertIsNotNone(get_first_executor(caller))
        self.assertEqual(caller('abc', False), 8)
        self.assertEqual(caller([], True), 4)
        # Changing the binding invalidates folded builtin facts in either
        # the caller or the separately compiled callee.
        namespace['len'] = lambda value: 20
        self.assertEqual(caller([], True), 24)
        self.assertEqual(caller([], False), 25)
        del namespace['len']
        with self.assertRaises(TypeError):
            caller(None, True)

    @unittest.skipIf(Py_GIL_DISABLED, "Sibling type guards require the GIL")
    @disable_gc()
    def test_static_attribute_family_guards(self):
        class Base:
            def answer(self):
                return 17
        class First(Base):
            pass
        class Second(Base):
            pass
        class Different(Base):
            pass
        a, b, c = First(), Second(), Different()
        for value in (a, b, c):
            value.x = 10
        a.y = b.y = 20
        c.padding = 99
        c.y = 30
        c.answer = lambda: 40
        # Populate type lookup caches without observing arguments in the JIT.
        for value in (a, b, c):
            self.assertEqual(value.x, 10)
            value.answer()

        def read(value):
            return value.x + value.y
        def call(value):
            return value.answer()
        def write(value):
            value.x = 11
            return value.y
        count = TIER2_RESUME_THRESHOLD + 10
        for function, expected in ((read, 30), (call, 17), (write, 20)):
            self.enterContext(clear_executors(function))
            self.assertEqual(list(map(function, itertools.repeat(a, count))),
                             [expected] * count)
            executor = get_first_executor(function)
            self.assertIsNotNone(executor)
            self.assertIn('_GUARD_TYPE_VERSION_FAMILY', get_opnames(executor))
        self.assertEqual(read(b), 30)
        # x has the same offset, but y does not. The first disjunctive guard
        # must not prove an exact type and remove the following y guard.
        self.assertEqual(read(c), 40)
        self.assertEqual(call(c), 40)
        self.assertEqual(write(c), 30)
        self.assertEqual(c.x, 11)
        Second.answer = lambda self: 50
        self.assertEqual(call(b), 50)
        self.assertEqual(call(a), 17)
        First.x = property(lambda self: 60)
        self.assertEqual(read(a), 80)
        with self.assertRaises(AttributeError):
            write(a)

    @unittest.skipIf(Py_GIL_DISABLED, "Sibling type guards require the GIL")
    @disable_gc()
    def test_overridden_sibling_methods_use_dynamic_call(self):
        class Base:
            pass
        class First(Base):
            def answer(self, value=4, *unused):
                return value + 1
        class Second(Base):
            def answer(self, value=5, *unused):
                if value < 0:
                    raise ValueError(value)
                return value + 10
        a, b = First(), Second()
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(a.answer, itertools.repeat(3, count))),
                         [4] * count)
        self.assertEqual(list(map(b.answer, itertools.repeat(3, count))),
                         [13] * count)
        def call(obj):
            return obj.answer(3)
        def default(obj):
            return obj.answer()
        for function, expected in ((call, 4), (default, 5)):
            self.enterContext(clear_executors(function))
            self.assertEqual(list(map(function, itertools.repeat(a, count))),
                             [expected] * count)
            opnames = get_opnames(_opcode.get_executor(function.__code__, 0))
            self.assertIn('_LOAD_ATTR_METHOD_DYNAMIC', opnames)
            self.assertIn('_CHECK_PY_FUNCTION', opnames)
        self.assertEqual(call(b), 13)
        self.assertEqual(default(b), 15)
        Second.answer.__defaults__ = (-1,)
        with self.assertRaisesRegex(ValueError, '-1'):
            default(b)
        self.assertEqual(default(a), 5)
        Second.answer.__code__ = (lambda self, value=0: value + 20).__code__
        self.assertEqual(call(b), 23)
        self.assertEqual(default(b), 19)
        b.answer = lambda *args: 99
        self.assertEqual(call(b), 99)
        self.assertEqual(default(b), 99)
        self.assertEqual(call(a), 4)
        from _testcapi import function_setvectorcall
        function_setvectorcall(First.answer)
        self.assertEqual(call(a), 'overridden')
        First.answer = property(lambda self: lambda *args: 101)
        self.assertEqual(call(a), 101)

    @unittest.skipIf(Py_GIL_DISABLED, "Sibling type guards require the GIL")
    @disable_gc()
    def test_static_slot_family_guards(self):
        class Base:
            __slots__ = ('value',)
        class First(Base):
            __slots__ = ()
        class Second(Base):
            __slots__ = ('other',)
        a, b = First(), Second()
        a.value, b.value, b.other = 7, 9, 11
        self.assertEqual(b.value, 9)
        def read(obj):
            return obj.value
        self.enterContext(clear_executors(read))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(map(read, itertools.repeat(a, count))), [7] * count)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn('_GUARD_TYPE_VERSION_FAMILY', get_opnames(executor))
        self.assertEqual(read(b), 9)
        del b.value
        with self.assertRaises(AttributeError):
            read(b)
        Second.value = property(lambda self: 19)
        self.assertEqual(read(b), 19)
        self.assertEqual(read(a), 7)

    @disable_gc()
    def test_scalar_input_guard_facts_across_blocks(self):
        def calculate(value, branch):
            value + 1
            if branch:
                return value + 2
            return value + 3
        self.enterContext(clear_executors(calculate))
        count = TIER2_RESUME_THRESHOLD + 10
        args = itertools.islice(itertools.cycle([(4, True), (4, False)]), count)
        self.assertEqual(list(itertools.starmap(calculate, args)),
                         [6, 7] * (count // 2) + ([6] if count % 2 else []))
        opnames = get_opnames(_opcode.get_executor(calculate.__code__, 0))
        self.assertEqual(opnames.count('_GUARD_NOS_INT'), 1)
        for value in (2**100, 1.5, 1+2j):
            self.assertEqual(calculate(value, True), value + 2)
            self.assertEqual(calculate(value, False), value + 3)
        with self.assertRaises(TypeError):
            calculate(None, True)

    @disable_gc()
    def test_scalar_input_guard_does_not_refine_reassigned_local(self):
        def calculate(value, replacement):
            result = value + ((value := replacement), 1)[1]
            return result, value + 1
        self.enterContext(clear_executors(calculate))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(calculate, itertools.repeat(
            (2, 3), count))), [(3, 4)] * count)
        self.assertIsNotNone(_opcode.get_executor(calculate.__code__, 0))
        self.assertEqual(calculate(2, 1.5), (3, 2.5))
        self.assertEqual(calculate(2, 2**100), (3, 2**100 + 1))
        with self.assertRaises(TypeError):
            calculate(2, None)

    @disable_gc()
    def test_osr_inferred_local_types_are_guarded(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def accumulate(count, seed):
            total = seed
            for index in range(count):
                total += index
            return total
        self.enterContext(clear_executors(accumulate))
        count = TIER2_THRESHOLD + 100
        expected = count * (count - 1) // 2
        self.assertEqual(accumulate(count, 0), expected)
        executors = get_all_executors(accumulate)
        self.assertTrue(executors)
        self.assertTrue(any('_GUARD_OSR_LOCAL_TYPE' in get_opnames(executor)
                            for executor in executors))
        # The guard proves neither a particular value nor a compact integer.
        self.assertEqual(accumulate(count, 2**100), 2**100 + expected)
        # A failed entry guard must resume at the loop header, making progress
        # without re-entering the same executor at its installed backedge.
        self.assertEqual(accumulate(count, 0.5), expected + 0.5)
        self.assertEqual(accumulate(count, 2j), expected + 2j)
        with self.assertRaises(TypeError):
            accumulate(count, 'changed')

    def test_recording_frontend_removed(self):
        self.assertNotIn("TRACE_RECORD", dis.opmap)
        self.assertFalse(hasattr(_testinternalcapi, "get_exit_executor"))

    @disable_gc()
    def test_osr_compiles_both_branch_successors(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def choose(count, positive):
            total = 0
            for value in range(count):
                if positive:
                    total += value
                else:
                    total -= value
            return total

        self.enterContext(clear_executors(choose))
        count = TIER2_THRESHOLD + 100
        self.assertEqual(choose(count, True), count * (count - 1) // 2)
        executors = get_all_executors(choose)
        self.assertTrue(executors)
        for executor in executors:
            names = get_opnames(executor)
            self.assertIn("_METHOD_JUMP", names)
            self.assertIn("_METHOD_POP_JUMP_IF_FALSE", names)
            self.assertNotIn("_JUMP_TO_TOP", names)
        self.assertEqual(choose(count, False), -count * (count - 1) // 2)
        self.assertTrue(all(executor.is_valid() for executor in executors))

    @disable_gc()
    def test_osr_preserves_live_locals_and_nested_iterator_stack(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def accumulate(count, start):
            total = start
            for outer in (1, 2):
                for inner in range(count):
                    total += outer + inner
            return total

        self.enterContext(clear_executors(accumulate))
        count = TIER2_THRESHOLD + 10
        expected = count * (count - 1) + 3 * count
        self.assertEqual(accumulate(count, 0), expected)
        self.assertTrue(get_all_executors(accumulate))
        self.assertEqual(accumulate(count, 0.5), expected + 0.5)
        self.assertEqual(accumulate(count, 2**80), expected + 2**80)

    @disable_gc()
    def test_osr_guard_failure_resumes_with_correct_exception(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def divide(count, divisor):
            value = 0
            for _ in range(count):
                value = 100 // divisor
            return value

        self.enterContext(clear_executors(divide))
        self.assertEqual(divide(TIER2_THRESHOLD + 10, 2), 50)
        self.assertTrue(get_all_executors(divide))
        self.assertEqual(divide(100, 2.0), 50.0)
        try:
            divide(100, 0)
        except ZeroDivisionError as exc:
            tb = exc.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            self.assertIs(tb.tb_frame.f_code, divide.__code__)
        else:
            self.fail("OSR suppressed ZeroDivisionError")

    @unittest.skipUnless(Py_GIL_DISABLED, 'requires a free-threaded build')
    def test_suspended_jit_advances_cold_counters(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('def leaf(value):\n    return value + 1\n', namespace)
        leaf = namespace['leaf']
        ready = threading.Event()
        release = threading.Event()
        def worker():
            ready.set()
            release.wait()
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            self.assertFalse(sys._jit.is_enabled())
            count = 2 * TIER2_RESUME_THRESHOLD
            self.assertEqual(list(map(leaf, itertools.repeat(41, count))),
                             [42] * count)
            self.assertIsNone(get_first_executor(leaf))
            counter, = struct.unpack_from(
                '=H', leaf.__code__._co_code_adaptive, 2)
            # The low three bits retain the backoff, not the countdown.
            self.assertEqual(counter >> 3, 0)
        finally:
            release.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertTrue(sys._jit.is_enabled())
        self.assertEqual(leaf(41), 42)
        self.assertIsNotNone(get_first_executor(leaf))
        self.assertEqual(leaf(42), 43)

    @disable_gc()
    def test_entry_validity_survives_resume_check(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {'VALUE': 42}
        exec('def read():\n    return VALUE\n', namespace)
        read = namespace['read']
        results = list(itertools.starmap(read, itertools.repeat(
            (), TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results, [42] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(read.__code__, 0)
        names = get_opnames(executor)
        self.assertIn('_METHOD_EXIT', names)
        self.assertIn('_TIER2_RESUME_CHECK', names)
        self.assertNotIn('_CHECK_VALIDITY', names)
        namespace['VALUE'] = 43
        self.assertFalse(executor.is_valid())
        self.assertEqual(read(), 43)

    @disable_gc()
    def test_callback_invalidates_after_resume_check(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {'VALUE': 42}
        exec('def read(callback):\n'
             '    count = len(callback)\n'
             '    return VALUE + count\n', namespace)
        read = namespace['read']
        class Callback:
            replace = False
            def __len__(self):
                if self.replace:
                    namespace['VALUE'] = 99
                return 1
        callback = Callback()
        self.assertEqual(list(map(read, itertools.repeat(
            callback, TIER2_RESUME_THRESHOLD))),
            [43] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(read.__code__, 0)
        names = get_opnames(executor)
        self.assertIn('_TIER2_RESUME_CHECK', names)
        self.assertIn('_CHECK_VALIDITY', names)
        callback.replace = True
        self.assertEqual(read(callback), 100)
        self.assertFalse(executor.is_valid())

    @disable_gc()
    def test_reassignment_does_not_alias_previous_stack_value(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def drop(value):
            return None

        # Retain an owned value on the stack while overwriting its local.
        # A COPY of the new bool must not make the old value immortal.
        instructions = [
            ("RESUME", 0), ("LOAD_FAST", 0), ("LOAD_CONST", 0),
            ("STORE_FAST", 0), ("LOAD_FAST", 0), ("COPY", 1), ("TO_BOOL", 0),
            ("POP_TOP", 0), ("POP_TOP", 0), ("POP_TOP", 0),
            ("LOAD_CONST", 1), ("RETURN_VALUE", 0),
        ]
        code = bytearray()
        for name, arg in instructions:
            code.extend((dis.opmap[name], arg))
            code.extend(bytes(2 * dis._inline_cache_entries.get(name, 0)))
        drop.__code__ = drop.__code__.replace(
            co_code=bytes(code), co_consts=(True, None),
            co_stacksize=3, co_linetable=b"")
        destroyed = []

        class Value:
            def __del__(self):
                destroyed.append(None)

        count = TIER2_RESUME_THRESHOLD + 100
        # Keep object production in C; a shared generator-expression trace
        # could retain a different local Value type on each refleak iteration.
        values = itertools.starmap(Value, itertools.repeat((), count))
        self.assertEqual(list(map(drop, values)), [None] * count)
        self.assertEqual(len(destroyed), count)
        self.assertIn("_METHOD_EXIT", get_opnames(get_first_executor(drop)))

    @disable_gc()
    def test_borrowed_arithmetic_and_comparison_inputs(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for symbol, values, cleanup, expected in (
            ('+', (int('3000'), int('4000')), '_POP_TOP_INT', 7000),
            ('+', (float('3.25'), float('4.5')), '_POP_TOP_FLOAT', 7.75),
            ('==', (''.join(['ab', 'cd']), ''.join(['ab', 'cd'])),
             '_POP_TOP_UNICODE', True),
        ):
            with self.subTest(symbol=symbol, values=values):
                ns = {}
                exec(f'def calculate(a, b): return a {symbol} b', ns)
                calculate = ns['calculate']
                count = TIER2_RESUME_THRESHOLD
                self.assertEqual(list(itertools.starmap(calculate,
                                     itertools.repeat(values, count))),
                                 [expected] * count)
                ops = get_opnames(get_first_executor(calculate))
                self.assertIn('_METHOD_EXIT', ops)
                self.assertNotIn(cleanup, ops)
                refs = tuple(sys.getrefcount(value) for value in values)
                results = list(itertools.starmap(calculate,
                               itertools.repeat(values, count)))
                self.assertEqual(results, [expected] * count)
                del results
                self.assertEqual(tuple(sys.getrefcount(value) for value in values),
                                 refs)
                self.assertEqual(calculate(values[0], values[0]),
                                 values[0] + values[0] if symbol == '+' else True)
                if symbol == '+':
                    self.assertEqual(calculate('a', 'b'), 'ab')
                    with self.assertRaises(TypeError):
                        calculate(None, 1)

    @disable_gc()
    def test_boolean_cleanup_preserves_receiver_facts(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Record:
            __slots__ = ('special', 'text')
        def read(obj):
            return obj.special or obj.text != '0'
        record = Record()
        record.special = False
        record.text = '0'
        count = TIER2_RESUME_THRESHOLD
        self.assertEqual(list(map(read, itertools.repeat(record, count))),
                         [False] * count)
        ops = get_opnames(get_first_executor(read))
        self.assertIn('_METHOD_EXIT', ops)
        self.assertIn('_LOAD_CONST_INLINE_BORROW', ops)
        self.assertNotIn('_POP_TOP', ops)
        record.text = '1'
        self.assertIs(read(record), True)
        class Change:
            def __bool__(self):
                record.text = '0'
                return False
        record.special = Change()
        self.assertIs(read(record), False)
        record.special = True
        self.assertIs(read(record), True)
        class Replacement(Record):
            __slots__ = ()
            @property
            def text(self):
                return '1'
        class ChangeType:
            def __bool__(self):
                record.__class__ = Replacement
                return False
        record.special = ChangeType()
        self.assertIs(read(record), True)

    @disable_gc()
    def test_immortal_constant_code_replacement(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def compare(value):
            return value == '0'
        count = TIER2_RESUME_THRESHOLD
        self.assertEqual(list(map(compare, itertools.repeat('1', count))),
                         [False] * count)
        executor = get_first_executor(compare)
        self.assertIn('_LOAD_CONST_INLINE_BORROW', get_opnames(executor))
        self.assertTrue(sys._is_immortal('0'))
        alias = types.FunctionType(compare.__code__, compare.__globals__)
        constants = tuple('1' if value == '0' else value
                          for value in compare.__code__.co_consts)
        compare.__code__ = compare.__code__.replace(co_consts=constants)
        self.assertEqual(list(map(compare, itertools.repeat('1', count))),
                         [True] * count)
        self.assertIs(alias('0'), True)
        self.assertIs(alias('1'), False)
        self.assertIs(compare('1'), True)
        self.assertIs(compare('0'), False)


    @disable_gc()
    def test_large_method_keeps_caller_osr_cfg(self):
        source = ["def helper(value):", "    if value >= 0:",
                  "        return value + 1"]
        source.extend(["    value += 1"] * 40)
        source.append("    return value")
        source.extend(["def caller(count):", "    total = 0",
                       "    for value in range(count):",
                       "        total += helper(value)", "    return total"])
        namespace = {}
        exec("\n".join(source), namespace)
        helper, caller = namespace["helper"], namespace["caller"]
        for _ in range(100):
            self.assertEqual(helper(-100), -60)
        count = TIER2_THRESHOLD
        self.assertEqual(caller(count), count * (count + 1) // 2)
        loops = [executor for executor in get_all_executors(caller)
                 if "_METHOD_JUMP" in get_opnames(executor) and
                 "_PUSH_FRAME" in get_opnames(executor)]
        self.assertTrue(loops)
        count = TIER2_RESUME_THRESHOLD
        self.assertEqual(list(map(helper, itertools.repeat(1, count))), [2] * count)
        method = get_first_executor(helper)
        self.assertIn("_METHOD_EXIT", get_opnames(method))
        self.assertNotIn("_METHOD_PROFILE", get_opnames(method))
        self.assertTrue(all(executor.is_valid() for executor in loops))
        self.assertEqual(caller(5), 15)
        self.assertEqual(helper(-100), -60)

        def replacement(value):
            return value + 10
        helper.__code__ = replacement.__code__
        # The caller checks the callee's version at the call boundary. A
        # method which has not inlined its body need not be invalidated.
        self.assertEqual(caller(5), 60)


    @unittest.skipIf(Py_GIL_DISABLED, "Constant attribute fusion requires the GIL")
    def test_fused_store_method_fallback_makes_progress(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import dis
            import gc
            import itertools
            from test.test_capi.test_opt import (
                get_all_executors, TIER2_RESUME_THRESHOLD)

            gc.disable()
            seen = set()
            destroyed = []
            class Owner:
                __slots__ = ('value',)
            class Value:
                def __del__(self):
                    destroyed.append(None)
                    seen.update(get_all_executors(clear))

            def clear(obj):
                obj.value = None
                return 1

            def work(count):
                obj = Owner()
                total = 0
                for _ in range(count):
                    obj.value = Value()
                    total += clear(obj)
                return total

            obj = Owner()
            obj.value = None
            # Compile the entry independently of the caller's inlining.
            assert list(map(clear, itertools.repeat(
                obj, TIER2_RESUME_THRESHOLD))) == [1] * TIER2_RESUME_THRESHOLD
            seen.update(get_all_executors(clear))
            assert work(100_000) == 100_000
            assert len(destroyed) == 100_000
            # Repeated finalizers force the guarded store back to Tier 1.
            # No continuation executor may be attached inside the method.
            assert seen, 'The method entry never compiled'
            assert all(ex.get_opcode() in (dis.opmap['RESUME'],
                                          dis._all_opmap['RESUME_CHECK_JIT'])
                       for ex in seen)
        """))

    @disable_gc()
    def test_unpack_local_stores_preserve_finalizer_order(self):
        for sequence in (tuple, list):
            with self.subTest(sequence=sequence):
                def unpack(values, previous):
                    a, b, c = previous.pop()
                    a, b, c = values
                    return a, b, c

                reset_code(unpack)
                args = ((sequence((4, 5, 6)), [(1, 2, 3)])
                        for _ in range(TIER2_RESUME_THRESHOLD))
                self.assertEqual(list(itertools.starmap(unpack, args)),
                                 [(4, 5, 6)] * TIER2_RESUME_THRESHOLD)
                executors = get_all_executors(unpack)
                unpack_op = f"_UNPACK_{sequence.__name__.upper()}_TO_FAST"
                self.assertTrue(any(op.startswith(unpack_op)
                                    for ex in executors for op in get_opnames(ex)))

                events = []
                class Previous:
                    def __init__(self, name):
                        self.name = name
                    def __del__(self):
                        local = sys._getframe(1).f_locals
                        events.append((self.name, tuple(
                            isinstance(local[name], Previous) for name in "abc")))

                previous = [(Previous("a"), Previous("b"), Previous("c"))]
                self.assertEqual(unpack(sequence((7, 8, 9)), previous), (7, 8, 9))
                self.assertEqual(events, [("a", (False, True, True)),
                                          ("b", (False, False, True)),
                                          ("c", (False, False, False))])
                self.assertEqual(previous, [])
                # The same old object can be held by several locals. Its initial
                # refcount > 1 cannot move its finalizer past those stores.
                events.clear()
                shared = Previous("shared")
                previous = [(shared, shared, shared)]
                del shared
                self.assertEqual(unpack(sequence((7, 8, 9)), previous), (7, 8, 9))
                self.assertEqual(events, [("shared", (False, False, False))])
                with self.assertRaises(ValueError):
                    unpack(sequence((1, 2)), [(1, 2, 3)])
                with self.assertRaises(ValueError):
                    unpack(sequence((1, 2, 3, 4)), [(1, 2, 3)])
                objects = (object(), object(), object())
                self.assertEqual(unpack(sequence(objects), [(1, 2, 3)]), objects)
                # Identical stores may retain existing strong references,
                # including non-primitive objects.
                self.assertEqual(unpack(sequence(objects), [objects]), objects)

    @disable_gc()
    def test_unpack_local_stores_do_not_merge_repeated_target(self):
        def unpack(values):
            a, a, b = values
            return a, b

        for _ in range(TIER2_RESUME_THRESHOLD):
            self.assertEqual(unpack((1, 2, 3)), (2, 3))
        objects = [object(), object(), object()]
        self.assertEqual(unpack(objects), (objects[1], objects[2]))

    @disable_gc()
    def test_tuple_unpack_keeps_items_alive(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def pair(box):
            a, b = box.pop()
            return a, b

        def triple(box):
            a, b, c = box.pop()
            return a, b, c

        events = []

        class Item:
            def __init__(self, value):
                self.value = value

            def __del__(self):
                events.append(self.value)

        for unpack, count in ((pair, 2), (triple, 3)):
            with self.subTest(count=count), clear_executors(unpack):
                values = tuple(range(count))
                for _ in range(TIER2_RESUME_THRESHOLD):
                    self.assertEqual(unpack([values]), values)
                self.assertIsNotNone(get_first_executor(unpack))
                box = [tuple(Item(i) for i in range(count))]
                refs = [weakref.ref(item) for item in box[0]]
                result = unpack(box)
                self.assertEqual([item.value for item in result], list(values))
                self.assertEqual(events, [])
                self.assertTrue(all(ref() is not None for ref in refs))
                del result
                gc.collect()
                self.assertCountEqual(events, values)
                self.assertTrue(all(ref() is None for ref in refs))
                events.clear()
                with self.assertRaises(ValueError):
                    unpack([values[:-1]])
                with self.assertRaises(ValueError):
                    unpack([values + (None,)])

    @disable_gc()
    def test_short_method_unpack_fuses_local_stores(self):
        def unpack(rows, count):
            a = b = c = 0.0
            for index in range(count):
                a, b, c = rows[index & 1]
            return a, b, c

        rows = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        count = TIER2_THRESHOLD + 10
        self.assertEqual(unpack(rows, count), tuple(rows[(count - 1) & 1]))
        executor = get_first_executor(unpack)
        self.assertIsNotNone(executor)
        ops = get_opnames(executor)
        self.assertIn('_UNPACK_LIST_TO_FAST_3', ops)

    @unittest.skipIf(Py_GIL_DISABLED or sys.maxsize <= 2**32,
                     "Constant attribute regions require a 64-bit GIL build")
    @disable_gc()
    def test_constant_attribute_store_finalizer_and_layout(self):
        class Slot:
            __slots__ = ("flag", "other")

        class Managed:
            pass

        def set_flags(obj):
            obj.flag = True
            obj.other = None
            return obj

        for cls in (Slot, Managed):
            with self.subTest(cls=cls), clear_executors(set_flags):
                obj = cls()
                list(map(set_flags, itertools.repeat(obj, TIER2_RESUME_THRESHOLD)))
                ops = get_opnames(get_first_executor(set_flags))
                self.assertEqual(sum(op.startswith("_STORE_CONST_ATTRIBUTE_")
                                     for op in ops), 2)
                events = []

                class Finalizer:
                    def __del__(self):
                        events.append((obj.flag, sys._getframe(1).f_code.co_name))

                obj.flag = Finalizer()
                self.assertIs(set_flags(obj), obj)
                self.assertEqual(events, [(True, "set_flags")])
                del obj.other
                set_flags(obj)
                self.assertIsNone(obj.other)
                if cls is Managed:
                    obj.__dict__ = {"flag": False, "other": 42}
                    set_flags(obj)
                    self.assertEqual(obj.__dict__, {"flag": True, "other": None})

    @disable_gc()
    def test_borrowed_none_branch(self):
        def choose(value):
            if value is None:
                return 10
            return 20

        marker = object()
        self.assertEqual(list(map(choose, itertools.repeat(
            marker, TIER2_RESUME_THRESHOLD))), [20] * TIER2_RESUME_THRESHOLD)
        ops = get_opnames(get_first_executor(choose))
        self.assertIn("_IS_NONE_BORROW", ops)
        self.assertNotIn("_IS_NONE", ops)
        self.assertEqual(choose(None), 10)
        self.assertEqual(choose(marker), 20)

    @disable_gc()
    def test_owned_none_branch_releases_value(self):
        events = []

        class Value:
            def __del__(self):
                events.append("released")

        def choose(factory):
            if factory() is None:
                return False
            # The temporary must be released before executing this arm.
            return len(events)

        self.assertEqual(list(map(choose, itertools.repeat(
            Value, TIER2_RESUME_THRESHOLD))),
            list(range(1, TIER2_RESUME_THRESHOLD + 1)))
        ops = get_opnames(get_first_executor(choose))
        self.assertIn("_IS_NONE", ops)
        self.assertNotIn("_IS_NONE_BORROW", ops)
        self.assertFalse(choose(lambda: None))

    @disable_gc()
    def test_forward_branch_does_not_check_periodic(self):
        def choose(flag, value):
            if flag:
                result = value + 1
            else:
                result = value - 1
            # Keep a shared tail large enough that the bytecode optimizer
            # does not duplicate it into both arms.
            return ((result + 2) * 3 + 4) * 5

        args = [(flag, 10) for flag in (False, True)]
        self.assertEqual(list(itertools.starmap(choose, itertools.islice(
            itertools.cycle(args), TIER2_RESUME_THRESHOLD))),
            list(itertools.islice(itertools.cycle((185, 215)),
                                  TIER2_RESUME_THRESHOLD)))
        self.assertIn("JUMP_FORWARD", [i.opname for i in dis.get_instructions(choose)])
        ops = get_opnames(get_first_executor(choose))
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", ops)
        self.assertNotIn("_CHECK_PERIODIC", ops)
        self.assertIn("_TIER2_RESUME_CHECK", ops)

        def caller(function, flag, value):
            return function(flag, value) + 3

        self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
            (choose, True, 10), TIER2_RESUME_THRESHOLD))),
            [218] * TIER2_RESUME_THRESHOLD)
        ops = get_opnames(get_first_executor(caller))
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", ops)
        self.assertNotIn("_CHECK_PERIODIC", ops)
        self.assertEqual(caller(choose, False, 10), 188)

    def test_method_python_call_clears_receiver_facts(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import gc
            import itertools
            from _testinternalcapi import TIER2_RESUME_THRESHOLD
            from test.test_capi.test_opt import get_first_executor

            gc.disable()
            class Record:
                pass
            for padding in (0, 200):
                # Exercise both an inlined callee and a method call.
                source = 'def change(obj, mutate):\\n' + '    pass\\n' * padding
                source += ('    if mutate:\\n'
                           '        obj.__dict__ = {"a": 10, "b": 20}\\n'
                           '    return 42\\n')
                exec(source, globals())
                for _ in range(100):
                    change(Record(), True)
                def update(obj, mutate):
                    obj.a = 1
                    obj.b = change(obj, mutate)
                    return obj.b
                update.__code__ = update.__code__.replace()
                obj = Record()
                obj.a = obj.b = 0
                list(itertools.starmap(update, itertools.repeat(
                    (obj, False), TIER2_RESUME_THRESHOLD)))
                assert get_first_executor(update) is not None
                assert update(obj, True) == 42
                assert obj.__dict__ == {"a": 10, "b": 42}
        """))

    @disable_gc()
    def test_method_empty_set_call(self):
        namespace = {"factory": set}
        exec("def make(ignored): return factory()", namespace)
        make = namespace["make"]
        results = list(map(make, itertools.repeat(None, TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results, [set()] * TIER2_RESUME_THRESHOLD)
        self.assertIsNot(results[0], results[1])
        results[0].add(42)
        self.assertEqual(results[1], set())
        executor = get_first_executor(make)
        self.assertIsNotNone(executor)
        ops = get_opnames(executor)
        self.assertIn("_CALL_SET_EMPTY", ops)
        self.assertGreaterEqual(ops.count("_TIER2_RESUME_CHECK"), 2)
        events = []
        namespace["factory"] = lambda: events.append("called") or 99
        self.assertEqual(make(None), 99)
        self.assertEqual(events, ["called"])
        namespace["factory"] = set
        self.assertEqual(make(None), set())

        class Record:
            pass
        def construct(record):
            record.a = 1
            result = set()
            record.b = 2
            return result
        record = Record()
        list(map(construct, itertools.repeat(record, TIER2_RESUME_THRESHOLD)))
        ops = get_opnames(get_first_executor(construct))
        self.assertIn("_CALL_SET_EMPTY", ops)
        if not Py_GIL_DISABLED:
            self.assertEqual(sum(op in ("_GUARD_TYPE_VERSION", "_GUARD_TYPE_VERSION_LOCKED",
                                       "_STORE_CONST_ATTRIBUTE_1", "_STORE_CONST_ATTRIBUTE_3")
                                 for op in ops), 1)

    def test_method_empty_set_allocation_error_location(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import _opcode
            import _testcapi
            import dis
            import gc
            import itertools
            from _testinternalcapi import TIER2_RESUME_THRESHOLD

            def pack(value):
                return set()

            gc.disable()
            list(map(pack, itertools.repeat(None, TIER2_RESUME_THRESHOLD)))
            executor = _opcode.get_executor(pack.__code__, 0)
            assert any(op[0] == '_CALL_SET_EMPTY' for op in executor)
            held = [set() for _ in range(1000)]
            failed = False
            _testcapi.set_nomemory(0, 1)
            try:
                pack(None)
            except MemoryError as exc:
                _testcapi.remove_mem_hooks()
                failed = True
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                assert tb.tb_frame.f_code is pack.__code__
                assert dis.opname[pack.__code__.co_code[tb.tb_lasti]] == 'CALL'
            finally:
                _testcapi.remove_mem_hooks()
            assert failed
            assert pack(None) == set()
        """))

    @disable_gc()
    def test_method_empty_dict_preserves_receiver_facts(self):
        class Record:
            pass
        record = Record()
        def construct(record):
            record.a = 42
            result = {}
            record.b = 43
            return result
        results = list(map(construct, itertools.repeat(record, TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results, [{}] * TIER2_RESUME_THRESHOLD)
        self.assertIsNot(results[0], results[1])
        results[0]["changed"] = True
        self.assertEqual(results[1], {})
        executor = get_first_executor(construct)
        self.assertIsNotNone(executor)
        ops = get_opnames(executor)
        index = ops.index("_BUILD_EMPTY_MAP")
        self.assertNotEqual(ops[index + 1], "_CHECK_VALIDITY")
        if not Py_GIL_DISABLED:
            self.assertEqual(sum(op in ("_GUARD_TYPE_VERSION", "_GUARD_TYPE_VERSION_LOCKED",
                                       "_STORE_CONST_ATTRIBUTE_1", "_STORE_CONST_ATTRIBUTE_3")
                                 for op in ops), 1)

    def test_method_empty_dict_allocation_error_location(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import _opcode
            import _testcapi
            import dis
            import gc
            import itertools
            from _testinternalcapi import TIER2_RESUME_THRESHOLD

            def pack(value):
                return {}

            gc.disable()
            list(map(pack, itertools.repeat(None, TIER2_RESUME_THRESHOLD)))
            executor = _opcode.get_executor(pack.__code__, 0)
            assert any(op[0] == '_BUILD_EMPTY_MAP' for op in executor)
            held = [{} for _ in range(1000)]  # Drain the dictionary freelist.
            failed = False
            _testcapi.set_nomemory(0, 1)
            try:
                pack(None)
            except MemoryError as exc:
                _testcapi.remove_mem_hooks()
                failed = True
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                assert tb.tb_frame.f_code is pack.__code__
                assert dis.opname[pack.__code__.co_code[tb.tb_lasti]] == 'BUILD_MAP'
            finally:
                _testcapi.remove_mem_hooks()
            assert failed
            assert pack(None) == {}
        """))

    @disable_gc()
    def test_method_store_over_mutable_class_default(self):
        for has_get in (False, True):
            events = []
            class Default:
                pass
            if has_get:
                Default.__get__ = lambda *args: events.append("get")
            default = Default()
            class Record:
                value = default
            record = Record()
            @reset_code
            def store(record, value):
                record.value = value
            self.assertEqual(list(itertools.starmap(store, itertools.repeat(
                (record, 42), TIER2_RESUME_THRESHOLD))),
                [None] * TIER2_RESUME_THRESHOLD)
            executor = get_first_executor(store)
            self.assertIsNotNone(executor)
            if not Py_GIL_DISABLED:
                self.assertIn("_GUARD_STORE_ATTR_NONDATA_CACHED", get_opnames(executor))
            self.assertEqual(record.value, 42)
            self.assertEqual(events, [])
            Default.__set__ = lambda self, obj, value: events.append(value)
            store(record, 43)
            self.assertEqual(events, [43])
            del Default.__set__
            store(record, 44)
            self.assertEqual(record.value, 44)
            Default.__delete__ = lambda self, obj: None
            with self.assertRaises(AttributeError):
                store(record, 45)
            del Default.__delete__
            class Data:
                def __set__(self, obj, value):
                    events.append(value)
            default.__class__ = Data
            store(record, 46)
            self.assertEqual(events, [43, 46])
            # Drop the cached binding while retaining the compiled executor.
            Record.value = None
            del default
            store(record, 47)
            self.assertEqual(record.value, 47)
            namespace = vars(record)
            store(record, 48)
            self.assertEqual(namespace["value"], 48)
            record.__dict__ = {}
            store(record, 49)
            self.assertEqual(record.value, 49)

    @disable_gc()
    def test_method_stores_preserve_receiver_version(self):
        class Slot:
            __slots__ = ("a", "b")
        class Managed:
            pass
        class Default:
            pass
        class ManagedDefaults:
            a = Default()
            b = Default()
        for cls in (Slot, Managed, ManagedDefaults):
            obj = cls()
            obj.a = obj.b = 0
            @reset_code
            def update(obj, a, b):
                obj.a = a
                obj.b = b
                return obj.b
            results = list(itertools.starmap(update, itertools.repeat(
                (obj, 1, 2), TIER2_RESUME_THRESHOLD)))
            self.assertEqual(results, [2] * TIER2_RESUME_THRESHOLD)
            executor = get_first_executor(update)
            self.assertIsNotNone(executor)
            if not Py_GIL_DISABLED:
                self.assertEqual(sum(op in ("_GUARD_TYPE_VERSION", "_GUARD_TYPE_VERSION_LOCKED")
                                     for op in get_opnames(executor)), 1)
                ops = get_opnames(executor)
                self.assertNotIn("_LOCK_OBJECT", ops)
                if cls is not Slot:
                    self.assertEqual(ops.count("_GUARD_DORV_NO_DICT"), 1)
                    self.assertNotIn("_CHECK_MANAGED_OBJECT_HAS_VALUES", ops)
            if cls is not Slot:
                materialized = cls()
                materialized.b = 0
                snapshots = []
                class Materializer:
                    def __del__(self):
                        snapshots.append(vars(materialized).copy())
                materialized.a = Materializer()
                self.assertEqual(update(materialized, 3, 4), 4)
                self.assertEqual(snapshots, [{"b": 0, "a": 3}])
                self.assertEqual(vars(materialized), {"b": 4, "a": 3})
            events = []
            class Finalizer:
                def __del__(self):
                    cls.b = property(lambda self: 99,
                        lambda self, value: events.append(value))
            obj.a = Finalizer()
            self.assertEqual(update(obj, 3, 4), 99)
            self.assertEqual(obj.a, 3)
            self.assertEqual(events, [4])

    @disable_gc()
    def test_method_store_over_nondata_descriptor(self):
        events = []
        class Descriptor:
            def __get__(self, instance, owner):
                events.append("get")
                return 99
        import_helper.import_module("_testlimitedcapi").type_freeze(Descriptor)
        descriptors = (lambda self: 99, staticmethod(lambda: 99),
                       classmethod(lambda cls: 99), list.append,
                       vars(dict)["fromkeys"], Descriptor())
        for descriptor in descriptors:
            class Record:
                value = descriptor
            obj = Record()
            @reset_code
            def store(obj, value):
                obj.value = value
                return obj.value
            results = list(itertools.starmap(store, itertools.repeat(
                (obj, 42), TIER2_RESUME_THRESHOLD)))
            self.assertEqual(results, [42] * TIER2_RESUME_THRESHOLD)
            executor = get_first_executor(store)
            self.assertIsNotNone(executor)
            if not Py_GIL_DISABLED:
                self.assertIn("_STORE_ATTR_INSTANCE_VALUE_NOESCAPE", get_opnames(executor))
            self.assertEqual(events, [])
            self.assertIs(vars(Record)["value"], descriptor)
            del obj.value
            self.assertEqual(store(obj, 43), 43)
            obj.__dict__ = {}
            self.assertEqual(store(obj, 44), 44)
            Record.value = property(lambda self: 99,
                lambda self, value: events.append(value))
            self.assertEqual(store(obj, 45), 99)
            self.assertEqual(events, [45])
            events.clear()

    @disable_gc()
    def test_method_store_attribute_cleanup_and_aliases(self):
        class Slot:
            __slots__ = ("value",)
        class Managed:
            pass
        def store(obj, value):
            obj.value = value
            return obj.value
        for cls, opname in ((Slot, "_STORE_ATTR_SLOT_NOESCAPE"),
                            (Managed, "_STORE_ATTR_INSTANCE_VALUE_NOESCAPE")):
            obj = cls()
            with clear_executors(store):
                self.assertEqual(list(itertools.starmap(store, itertools.repeat(
                    (obj, 42), TIER2_RESUME_THRESHOLD))),
                    [42] * TIER2_RESUME_THRESHOLD)
                executor = _opcode.get_executor(store.__code__, 0)
                if not Py_GIL_DISABLED:
                    self.assertIn(opname, get_opnames(executor))
                events = []
                class Finalizer:
                    def __del__(self):
                        events.append((sys._getframe(1).f_code.co_name, obj.value))
                obj.value = Finalizer()
                self.assertEqual(store(obj, 43), 43)
                self.assertEqual(events, [("store", 43)])
                del obj.value
                self.assertEqual(store(obj, 44), 44)
                if cls is Managed:
                    obj.__dict__ = {}
                    self.assertEqual(store(obj, 45), 45)
                    self.assertEqual(obj.__dict__, {"value": 45})

        def alias(obj, value):
            first = value + 1.0
            obj.value = first
            return first + 1.0, obj.value
        obj = Managed()
        results = list(itertools.starmap(alias, itertools.repeat(
            (obj, 2.5), TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results, [(4.5, 3.5)] * TIER2_RESUME_THRESHOLD)
        self.assertIsNotNone(get_first_executor(alias))
        self.assertEqual(alias(obj, 4.25), (6.25, 5.25))

    @disable_gc()
    def test_method_list_slice_bounds_and_callbacks(self):
        def sliced(values, start, stop):
            return values[start:stop]

        values = [object() for _ in range(10)]
        results = list(itertools.starmap(sliced, itertools.repeat(
            (values, 1, -1), TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results[-1], values[1:-1])
        executor = get_first_executor(sliced)
        self.assertIsNotNone(executor)
        self.assertIn("_BINARY_SLICE", get_opnames(executor))
        bounds = [None, -100, -10, -1, 0, 1, 10, 100, -(1 << 100), 1 << 100]
        for start in bounds:
            for stop in bounds:
                self.assertEqual(sliced(values, start, stop),
                                 list.__getitem__(values, slice(start, stop)))
                self.assertEqual(sliced([], start, stop), [])
        self.assertIsNot(sliced(values, None, None), values)
        events = []
        class Start:
            def __index__(self):
                events.append("start")
                values[:] = [1, 2, 3]
                return 1
        class Stop:
            def __index__(self):
                events.append("stop")
                values.append(4)
                return 4
        self.assertEqual(sliced(values, Start(), Stop()), [2, 3, 4])
        self.assertEqual(events, ["start", "stop"])
        class Failure:
            def __index__(self):
                raise ValueError("slice bound failure")
        with self.assertRaisesRegex(ValueError, "slice bound failure"):
            sliced(values, Failure(), None)
        with self.assertRaises(TypeError):
            sliced(values, 1.5, None)
        class Sequence(list):
            def __getitem__(self, key):
                return key.start, key.stop, key.step
        self.assertEqual(sliced(Sequence(values), 1, 3), (1, 3, None))
        self.assertEqual(sliced((1, 2, 3), 1, None), (2, 3))
        self.assertEqual(sliced("abc", 1, None), "bc")

    @disable_gc()
    def test_method_uint64_bitwise(self):
        def operate(a, b):
            return (a ^ b) & (a | b)
        args = ((1 << 64) - 1, 1 << 63)
        expected = int.__xor__(*args)
        self.assertEqual(list(itertools.starmap(operate, itertools.repeat(
            args, TIER2_RESUME_THRESHOLD))), [expected] * TIER2_RESUME_THRESHOLD)
        executor = get_first_executor(operate)
        self.assertIsNotNone(executor)
        self.assertIn("_BINARY_OP_EXTEND", get_opnames(executor))
        boundaries = [0, 1, (1 << 30) - 1, 1 << 30, 1 << 60, 1 << 63,
                      (1 << 64) - 1, 1 << 64, -(1 << 64), 1 << 100]
        for a in boundaries:
            for b in boundaries:
                self.assertEqual(operate(a, b), int.__xor__(a, b))
        class Value(int):
            def __xor__(self, other):
                return 42
        self.assertEqual(operate(Value(1 << 63), (1 << 64) - 1), 42)
        with self.assertRaises(TypeError):
            operate(1 << 63, 1.0)

    @disable_gc()
    def test_method_zip_retained_list_pairs(self):
        def collect(left, right):
            result = []
            for pair in zip(left, right):
                result.append(pair)
            return result

        left, right = [1, 2, 3], [4, 5, 6]
        results = list(itertools.starmap(collect, itertools.repeat(
            (left, right), TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results[-1], [(1, 4), (2, 5), (3, 6)])
        executor = get_first_executor(collect)
        self.assertIsNotNone(executor)
        self.assertIn("_METHOD_ITER_NEXT_INLINE", get_opnames(executor))
        if not Py_GIL_DISABLED:
            self.assertFalse(gc.is_tracked(results[-1][1]))
        self.assertIsNot(results[-1][0], results[-1][1])
        self.assertEqual(collect([1, 2, 3], [4]), [(1, 4)])
        self.assertEqual(collect([], [1, 2]), [])
        shared = iter([1, 2, 3, 4])
        self.assertEqual(collect(shared, shared), [(1, 2), (3, 4)])
        self.assertEqual(collect(iter([1, 2]), iter([3, 4])), [(1, 3), (2, 4)])
        rows = collect([[], [], []], [[], [], []])
        self.assertTrue(gc.is_tracked(rows[1]))
        self.assertIsNot(rows[0][0], rows[1][0])
        events = []
        def raising():
            yield 4
            events.append("raise")
            raise ValueError("zip iterator failure")
        with self.assertRaisesRegex(ValueError, "zip iterator failure"):
            collect([1, 2, 3], raising())
        self.assertEqual(events, ["raise"])

    @disable_gc()
    def test_method_zip_recycled_list_pairs(self):
        def consume(left, right):
            count = 0
            for a, b in zip(left, right):
                count += 1
                # Release body references before the next tuple replacement.
                a = b = None
                if count == 1:
                    left[0] = None
                    right[0] = None
            return count

        results = list(itertools.starmap(consume, itertools.repeat(
            ([None, 1, 2], [None, 3, 4]), TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results[-1], 3)
        self.assertIsNotNone(get_first_executor(consume))
        self.assertEqual(consume([None, [], []], [None, [], []]), 3)
        events = []
        right = [0, 1, 2]
        class Finalizer:
            def __del__(self):
                events.append("released")
                right.clear()
        # Only the recycled result tuple still owns the first item when the
        # next iteration begins. Its finalizer empties the second list before
        # zip advances that iterator.
        self.assertEqual(consume([Finalizer(), 1, 2], right), 1)
        self.assertEqual(events, ["released"])
        events.clear()
        right = [None, 1, 2]
        value = Finalizer()
        left = [value, 1, 2]
        right[0] = value
        del value
        # Two tuple slots holding the same object are not independent owners.
        self.assertEqual(consume(left, right), 2)
        self.assertEqual(events, ["released"])

    @disable_gc()
    def test_method_zip_retained_list_pairs_strict(self):
        def collect(left, right):
            result = []
            for pair in zip(left, right, strict=True):
                result.append(pair)
            return result

        results = list(itertools.starmap(collect, itertools.repeat(
            ([1, 2, 3], [4, 5, 6]), TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results[-1], [(1, 4), (2, 5), (3, 6)])
        if not Py_GIL_DISABLED:
            self.assertFalse(gc.is_tracked(results[-1][1]))
        with self.assertRaisesRegex(ValueError, "shorter"):
            collect([1, 2, 3], [4, 5])
        with self.assertRaisesRegex(ValueError, "longer"):
            collect([1, 2], [3, 4, 5])
        self.assertEqual(collect([], []), [])
        shared = iter([1, 2, 3, 4])
        self.assertEqual(collect(shared, shared), [(1, 2), (3, 4)])

    @disable_gc()
    def test_method_delete_inline_instance_attribute(self):
        capi = import_helper.import_module("_testcapi")
        class Record:
            def value(self):
                return 99
        record = Record()
        namespace = record.__dict__
        def erase(value):
            record.value = value
            del record.value
        list(map(erase, itertools.repeat(42, TIER2_RESUME_THRESHOLD)))
        executor = get_first_executor(erase)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_DELETE_ATTR_INSTANCE_VALUE", get_opnames(executor))
        self.assertEqual(record.value(), 99)
        self.assertEqual(namespace, {})
        wid = capi.add_dict_watcher(0)
        try:
            capi.watch_dict(wid, namespace)
            erase(43)
            self.assertEqual(capi.get_dict_watcher_events(),
                             ["new:value:43", "del:value"])
        finally:
            capi.unwatch_dict(wid, namespace)
            capi.clear_dict_watcher(wid)
        record.__dict__ = {"new": True}
        erase(44)
        self.assertEqual(record.__dict__, {"new": True})
        events = []
        class Descriptor:
            def __set__(self, instance, value):
                events.append(value)
            def __delete__(self, instance):
                events.append("delete")
        Record.value = Descriptor()
        erase(45)
        self.assertEqual(events, [45, "delete"])

    @disable_gc()
    def test_method_list_construction_preserves_aliases(self):
        def construct(value):
            first = value + 1.0
            items = [first, first]
            return items, first + 1.0

        results = list(map(construct, itertools.repeat(2.5, TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results[-1], ([3.5, 3.5], 4.5))
        self.assertIs(results[-1][0][0], results[-1][0][1])
        executor = get_first_executor(construct)
        self.assertIsNotNone(executor)
        ops = get_opnames(executor)
        index = ops.index("_BUILD_LIST")
        self.assertNotEqual(ops[index + 1], "_CHECK_VALIDITY")
        self.assertEqual(construct(5.25), ([6.25, 6.25], 7.25))

    def test_method_list_allocation_error_location(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import _opcode
            import _testcapi
            import dis
            import gc
            import itertools
            from _testinternalcapi import TIER2_RESUME_THRESHOLD

            def pack(value):
                return [value, value]

            gc.disable()
            value = object()
            list(map(pack, itertools.repeat(value, TIER2_RESUME_THRESHOLD)))
            executor = _opcode.get_executor(pack.__code__, 0)
            assert any(op[0] == '_BUILD_LIST' for op in executor)
            failed = False
            _testcapi.set_nomemory(0, 1)
            try:
                pack(value)
            except MemoryError as exc:
                _testcapi.remove_mem_hooks()
                failed = True
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                assert tb.tb_frame.f_code is pack.__code__
                assert dis.opname[pack.__code__.co_code[tb.tb_lasti]] == 'BUILD_LIST'
            finally:
                _testcapi.remove_mem_hooks()
            assert failed
            result = pack(value)
            assert result[0] is result[1] is value
        """))

    @disable_gc()
    def test_method_store_over_class_default(self):
        class Base:
            value = None
        class Record(Base):
            pass
        record = Record()
        def store(value):
            record.value = value
        list(map(store, itertools.repeat(42, TIER2_RESUME_THRESHOLD)))
        executor = get_first_executor(store)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_STORE_ATTR_INSTANCE_VALUE_NOESCAPE", get_opnames(executor))
        self.assertIsNone(Base.value)
        del record.value
        store(43)
        self.assertEqual(record.value, 43)
        events = []
        Base.value = property(lambda self: 99,
                              lambda self, value: events.append(value))
        store(44)
        self.assertEqual(events, [44])
        self.assertEqual(record.value, 99)
        self.assertEqual(record.__dict__["value"], 43)

    @disable_gc()
    def test_method_materialized_inline_dict_store(self):
        capi = import_helper.import_module("_testcapi")
        class Record:
            pass

        record = Record()
        record.value = 0
        namespace = record.__dict__
        def store(value):
            record.value = value

        list(map(store, itertools.repeat(42, TIER2_RESUME_THRESHOLD)))
        executor = get_first_executor(store)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_STORE_ATTR_INLINE_WITH_DICT", get_opnames(executor))
        del namespace["value"]
        store(43)
        self.assertEqual(namespace, {"value": 43})
        wid = capi.add_dict_watcher(0)
        try:
            capi.watch_dict(wid, namespace)
            store(44)
            self.assertEqual(capi.get_dict_watcher_events(), ["mod:value:44"])
        finally:
            capi.unwatch_dict(wid, namespace)
            capi.clear_dict_watcher(wid)
        events = []
        class Previous:
            def __del__(self):
                events.append(record.value)
        record.value = Previous()
        store(45)
        self.assertEqual(events, [45])
        record.__dict__ = {"new": True}
        store(46)
        self.assertEqual(record.__dict__, {"new": True, "value": 46})
        Record.value = property(lambda self: 99)
        with self.assertRaises(AttributeError):
            store(47)

    @disable_gc()
    def test_method_cached_descriptor_binding(self):
        class Record:
            @staticmethod
            def callback(value):
                return value + 1

        record = Record()
        def call(record, value):
            return record.callback(value)

        self.assertEqual(list(itertools.starmap(call, itertools.repeat(
            (record, 2), TIER2_RESUME_THRESHOLD))),
            [3] * TIER2_RESUME_THRESHOLD)
        executor = get_first_executor(call)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_LOAD_ATTR_DESCRIPTOR", get_opnames(executor))
        descriptor = Record.__dict__["callback"]
        descriptor.__init__(lambda value: value + 10)
        self.assertEqual(call(record, 2), 12)
        record.callback = lambda value: value + 20
        self.assertEqual(call(record, 2), 22)
        del record.callback
        descriptor.__init__(None)
        with self.assertRaises(TypeError):
            call(record, 2)
        del Record.callback
        with self.assertRaises(AttributeError):
            call(record, 2)

    @disable_gc()
    def test_method_descriptor_getattr_fallback(self):
        type_freeze = import_helper.import_module("_testlimitedcapi").type_freeze
        calls = []

        class Descriptor:
            missing = False

            def __get__(self, instance, owner):
                calls.append("get")
                if self.missing:
                    raise AttributeError("descriptor unavailable")
                return 42

        type_freeze(Descriptor)
        descriptor = Descriptor()

        class Record:
            value = descriptor

            def __getattr__(self, name):
                calls.append(name)
                return 99

        def read(record):
            return record.value

        record = Record()
        self.assertEqual(list(map(read, itertools.repeat(
            record, TIER2_RESUME_THRESHOLD))), [42] * TIER2_RESUME_THRESHOLD)
        self.assertIsNotNone(get_first_executor(read))
        calls.clear()
        descriptor.missing = True
        self.assertEqual(read(record), 99)
        self.assertEqual(calls, ["get", "value"])

    @disable_gc()
    def test_method_mutable_descriptor_instance_override(self):
        class Descriptor:
            def __get__(self, instance, owner):
                return lambda value: value + 10

        class Record:
            callback = Descriptor()

        record = Record()
        record.__dict__["callback"] = lambda value: value + 1

        def call(record, value):
            return record.callback(value)

        self.assertEqual(list(itertools.starmap(call, itertools.repeat(
            (record, 2), TIER2_RESUME_THRESHOLD))),
            [3] * TIER2_RESUME_THRESHOLD)
        executor = get_first_executor(call)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_LOAD_ATTR_INSTANCE_VALUE_NONDATA",
                          get_opnames(executor))
        Descriptor.__set__ = lambda self, instance, value: None
        self.assertEqual(call(record, 2), 12)
        del Descriptor.__set__
        self.assertEqual(call(record, 2), 3)
        del record.callback
        self.assertEqual(call(record, 2), 12)
        record.callback = lambda value: value + 2
        self.assertEqual(call(record, 2), 4)
        previous = weakref.ref(Record.__dict__["callback"])
        Record.callback = property(lambda self: lambda value: value + 20)
        gc.collect()
        self.assertIsNone(previous())
        self.assertEqual(call(record, 2), 22)
        del Record.callback
        del record.callback
        with self.assertRaises(AttributeError):
            call(record, 2)

    @disable_gc()
    def test_method_resolves_conditional_null(self):
        class Record:
            pass

        record = Record()
        record.value = 42
        record.function = abs

        def read(record):
            return record.value

        def call(record, value):
            return record.function(value)

        self.assertEqual(list(map(read, itertools.repeat(
            record, TIER2_RESUME_THRESHOLD))), [42] * TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(call, itertools.repeat(
            (record, -42), TIER2_RESUME_THRESHOLD))),
            [42] * TIER2_RESUME_THRESHOLD)
        for function in (read, call):
            executor = get_first_executor(function)
            self.assertIsNotNone(executor)
            self.assertNotIn("_PUSH_NULL_CONDITIONAL", get_opnames(executor))
        self.assertIn("_PUSH_NULL", get_opnames(get_first_executor(call)))
        record.function = len
        self.assertEqual(call(record, [1, 2, 3]), 3)
        record.function = 42
        with self.assertRaises(TypeError):
            call(record, 0)
        del record.function
        with self.assertRaises(AttributeError):
            call(record, 0)

    @disable_gc()
    def test_method_instance_attribute_class_default(self):
        class Base:
            flag = False

        class Record(Base):
            pass

        def read(record):
            value = record.flag
            return value, sys._jit.is_active()

        record = Record()
        record.flag = True
        list(map(read, itertools.repeat(record, TIER2_RESUME_THRESHOLD)))
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_LOAD_ATTR_INSTANCE_VALUE_OR_DEFAULT",
                          get_opnames(executor))
        del record.flag
        for value in (False, 123, None):
            if value is not False:
                record.flag = value
            result, active = read(record)
            self.assertIs(result, value)
            if not Py_GIL_DISABLED:
                self.assertTrue(active)
        del record.flag
        Base.flag = 42
        self.assertEqual(read(record)[0], 42)

        Record.flag = property(lambda self: "descriptor")
        record.__dict__["flag"] = "shadowed"
        self.assertEqual(read(record)[0], "descriptor")
        del Record.flag
        self.assertEqual(read(record)[0], "shadowed")
        record.__dict__ = {}
        self.assertEqual(read(record)[0], 42)
        del Base.flag
        with self.assertRaises(AttributeError):
            read(record)
        Record.__getattr__ = lambda self, name: "missing"
        self.assertEqual(read(record)[0], "missing")

    @disable_gc()
    def test_method_proven_local_cleanup(self):
        def save(value):
            result = value
            return result

        token = object()
        self.assertEqual(list(map(save, itertools.repeat(
            token, TIER2_RESUME_THRESHOLD))), [token] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(get_first_executor(save))
        self.assertIn("_POP_TOP_NOP", names)
        self.assertNotIn("_POP_TOP", names)

        def replace_float(value, replacement):
            value = value + 0.5
            value = replacement
            return value

        self.assertEqual(list(itertools.starmap(replace_float, itertools.repeat(
            (0.5, token), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)
        names = [name for name in get_opnames(get_first_executor(replace_float))
                 if name not in ("_SPILL_OR_RELOAD", "_SET_IP", "_CHECK_VALIDITY")]
        self.assertIn(("_SWAP_FAST_0", "_POP_TOP_FLOAT"),
                      list(zip(names, names[1:])))

        events = []
        class Previous:
            def __del__(self):
                frame = sys._getframe(1)
                events.append((frame.f_code.co_name, frame.f_locals["value"]))

        def replace_after_call(callback, replacement):
            value = 1.5
            callback()
            value = replacement
            return value

        def noop():
            pass
        self.assertEqual(list(itertools.starmap(replace_after_call,
            itertools.repeat((noop, token), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)

        def mutate():
            sys._getframe(1).f_locals["value"] = Previous()

        # Writing through f_locals invalidates the facts before the store.
        # The replacement is installed before closing the previous value.
        self.assertIs(replace_after_call(mutate, token), token)
        self.assertEqual(events, [("replace_after_call", token)])

    @disable_gc()
    def test_partial_method_keeps_existing_osr_cfg(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        source = ('def helper(value):\n'
                  '    if value >= 0:\n'
                  '        return value + 1\n'
                  '    result = value\n')
        source += '    result += value + 1\n' * 200
        source += '    return result\n'
        source += ('def caller(n):\n'
                   '    if n < 0:\n'
                   '        from math import sqrt\n'
                   '        return sqrt(-n)\n'
                   '    total = 0\n'
                   '    for value in range(n):\n'
                   '        total += helper(value)\n'
                   '    return total\n')
        namespace = {}
        exec(source, namespace)
        caller = namespace['caller']
        count = TIER2_THRESHOLD
        self.assertEqual(caller(count), count * (count + 1) // 2)
        loops = [executor for executor in get_all_executors(caller)
                 if '_METHOD_JUMP' in get_opnames(executor) and
                 '_PUSH_FRAME' in get_opnames(executor)]
        self.assertTrue(loops)
        count = TIER2_RESUME_THRESHOLD * 2
        self.assertEqual(list(map(caller, itertools.repeat(5, count))),
                         [15] * count)
        entry = _opcode.get_executor(caller.__code__, 0)
        self.assertIn('_METHOD_EXIT', get_opnames(entry))
        self.assertIn('_METHOD_CALL', get_opnames(entry))
        self.assertTrue(all(executor.is_valid() for executor in loops))
        self.assertEqual(caller(-9), 3.0)
        self.assertEqual(caller(0), 0)
        # Calls must observe replacement code even when the caller's guarded
        # call boundary remains valid (the callee body was not inlined).
        def replacement(value):
            return value + 10
        namespace['helper'].__code__ = replacement.__code__
        self.assertEqual(caller(5), 60)
        # Invalidation permits another method compilation. Empty iterations
        # exercise its function entry without warming a loop backedge.
        self.assertEqual(list(map(caller, itertools.repeat(0, count))),
                         [0] * count)
        entry = _opcode.get_executor(caller.__code__, 0)
        self.assertIn('_METHOD_EXIT', get_opnames(entry))
        self.assertEqual(caller(5), 60)
        self.assertEqual(caller(-16), 4.0)
        _testinternalcapi.invalidate_executors(caller.__code__)
        exec('def outer(n):\n'
             '    total = 0\n'
             '    for _ in range(n):\n'
             '        total += caller(0)\n'
             '    return total\n', namespace)
        outer = namespace['outer']
        self.assertEqual(outer(TIER2_THRESHOLD + 10), 0)
        traced = get_first_executor(outer)
        self.assertIsNotNone(traced)
        self.assertIn('_PUSH_FRAME', get_opnames(traced))
        for executor in get_all_executors(caller):
            self.assertIn('_METHOD_EXIT', get_opnames(executor))

    @disable_gc()
    def test_method_keeps_existing_osr_cfg(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        source = ("def helper(value):\n"
                  "    if value >= 0:\n"
                  "        return value + 1\n"
                  "    result = value\n")
        source += "    result += value + 1\n" * 200
        source += "    return result\n"
        source += ("def caller(n):\n"
                   "    total = 0\n"
                   "    for value in range(n):\n"
                   "        total += helper(value)\n"
                   "    return total\n")
        exec(source, namespace)
        caller = namespace["caller"]
        count = TIER2_THRESHOLD
        self.assertEqual(caller(count), count * (count + 1) // 2)
        loops = [executor for executor in get_all_executors(caller)
                 if "_METHOD_JUMP" in get_opnames(executor) and
                 "_PUSH_FRAME" in get_opnames(executor)]
        self.assertTrue(loops)
        count = TIER2_RESUME_THRESHOLD * 2
        self.assertEqual(list(map(caller, itertools.repeat(5, count))),
                         [15] * count)
        entry = _opcode.get_executor(caller.__code__, 0)
        self.assertIn("_METHOD_CALL", get_opnames(entry))
        self.assertIn("_METHOD_EXIT", get_opnames(entry))
        self.assertTrue(all(executor.is_valid() for executor in loops))
        self.assertEqual(caller(0), 0)

    @disable_gc()
    def test_generator_calls_existing_method_entry(self):
        source = ["def factory(offset):", "    def callee(value):"]
        source.extend(["        value += offset"] * 40)
        source.extend(["        return value", "    return callee"])
        namespace = {}
        exec("\n".join(source), namespace)
        factory = namespace["factory"]

        # Generator suspension stays in Tier 1; ordinary callee entries can JIT.
        def caller(function, count):
            for value in range(count):
                yield function(value)

        function = factory(10)
        reset_code(caller)
        self.assertEqual(list(caller(function, TIER2_THRESHOLD)),
                         list(range(400, TIER2_THRESHOLD + 400)))
        self.assert_generator_entries(caller)
        self.assertIsNone(get_first_executor(function))
        self.assertEqual(list(map(function, itertools.repeat(
            2, TIER2_RESUME_THRESHOLD))), [402] * TIER2_RESUME_THRESHOLD)
        method = get_first_executor(function)
        self.assertIn("_METHOD_EXIT", get_opnames(method))
        self.assertTrue(method.is_valid())

        count = TIER2_THRESHOLD * 3
        self.assertEqual(list(caller(function, count)),
                         list(range(400, count + 400)))
        self.assert_generator_entries(caller)
        self.assertTrue(method.is_valid())
        self.assertEqual(list(caller(factory(20), 3)), [800, 801, 802])
        self.assertEqual(list(caller(lambda value: value * 2, 3)), [0, 2, 4])
        with self.assertRaises(TypeError):
            list(caller(factory("wrong type"), 3))

    @disable_gc()
    def test_generator_calls_method_with_large_attribute_caches(self):
        namespace = {}
        source = ["def callee(record, value):"]
        source.extend(["    value += record.increment"] * 12)
        source.append("    return value")
        exec("\n".join(source), namespace)
        function = namespace["callee"]
        # The caches make this exceed the old 128-code-unit limit, although
        # the actual instruction stream is short enough to inline as a CFG.
        self.assertGreater(len(function.__code__.co_code) // 2, 128)
        self.assertLess(len(list(dis.get_instructions(function))), 128)

        class Record:
            increment = 10

        record = Record()
        record.increment = 10

        def caller(function, record, count):
            for value in range(count):
                yield function(record, value)

        count = TIER2_THRESHOLD
        reset_code(caller)
        self.assertEqual(list(caller(function, record, count)),
                         list(range(120, count + 120)))
        self.assert_generator_entries(caller)
        self.assertIsNone(get_first_executor(function))
        self.assertEqual(list(itertools.starmap(function, itertools.repeat(
            (record, 2), TIER2_RESUME_THRESHOLD))),
            [122] * TIER2_RESUME_THRESHOLD)
        method = get_first_executor(function)
        self.assertIn("_METHOD_EXIT", get_opnames(method))

        # A fresh generator caller compiles its loop and suspends in Tier 1.
        reset_code(caller)
        self.assertEqual(list(caller(function, record, count * 3)),
                         list(range(120, count * 3 + 120)))
        self.assert_generator_entries(caller)
        self.assertTrue(method.is_valid())

        record.increment = 20
        self.assertEqual(list(caller(function, record, 3)), [240, 241, 242])
        record.increment = "wrong type"
        with self.assertRaises(TypeError):
            list(caller(function, record, 3))

    def test_jit_code_views_and_repeated_release(self):
        if _testinternalcapi.get_jit_backend() != "jit":
            self.skipTest("requires the native JIT backend")
        # Exercise native code views and allocation ownership across repeated
        # invalidation, collection, and recompilation in an isolated process.
        code = textwrap.dedent("""
            import gc, itertools, _opcode, _testinternalcapi
            from test.support import reset_code
            from _testinternalcapi import TIER2_RESUME_THRESHOLD
            for generation in range(3):
                functions = []
                for index in range(64):
                    namespace = {"offset": index}
                    exec("def read(value): return value + offset", namespace)
                    function = namespace["read"]
                    values = list(map(function, itertools.repeat(
                        7, TIER2_RESUME_THRESHOLD * 2)))
                    assert values == [7 + index] * len(values)
                    executor = _opcode.get_executor(function.__code__, 0)
                    image = executor.get_jit_code()
                    assert isinstance(image, bytes) and len(image) > 0
                    functions.append(function)
                ranges = _testinternalcapi.get_jit_code_ranges()
                assert ranges
                addresses = [address for start, end in ranges
                             for address in (start, end - 1)]
                assert _testinternalcapi.classify_stack_addresses(
                    addresses, True) == ["jit"] * len(addresses)
                for function in functions:
                    reset_code(function)
                del executor, function, functions, namespace, image
                gc.collect()
                _testinternalcapi.clear_executor_deletion_list()
        """)
        _, _, stderr = script_helper.assert_python_ok("-c", code, PYTHON_JIT="1")
        self.assertEqual(stderr, b"")


    @disable_gc()
    def test_property_caller_ip_after_extended_arg(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        seen = set()

        class Subject:
            @property
            def value(self):
                caller = sys._getframe(1)
                seen.add(dis.opname[caller.f_code.co_code[caller.f_lasti]])
                return 1

        namespace = {}
        exec('def read(subject, count):\n'
             '    if count < 0:\n' +
             ''.join(f'        subject.attr{i}\n' for i in range(130)) +
             '    total = 0\n'
             '    for _ in range(count):\n'
             '        total += subject.value\n'
             '    return total\n', namespace)
        read = namespace['read']
        self.enterContext(clear_executors(read))
        count = TIER2_THRESHOLD * 3
        self.assertEqual(read(Subject(), count), count)
        self.assertIsNotNone(get_first_executor(read))
        # f_lasti identifies the actual LOAD_ATTR, as it does in Tier 1.
        self.assertEqual(seen, {'LOAD_ATTR'})

    @disable_gc()
    def test_generator_iteration_extended_arg(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec("def consume(iterator):\n"
             "    total = 0\n"
             "    for value in iterator:\n" +
             "        pass\n" * 270 +
             "        total += value\n"
             "    return total\n", namespace)
        consume = namespace['consume']
        self.enterContext(clear_executors(consume))
        instructions = list(dis.get_instructions(consume))
        self.assertTrue(any(
            previous.opname == 'EXTENDED_ARG' and current.opname == 'FOR_ITER'
            for previous, current in itertools.pairwise(instructions)))

        def generate(count):
            for value in range(count):
                yield value

        count = TIER2_THRESHOLD * 2
        for _ in range(5):
            self.assertEqual(consume(generate(count)), count * (count - 1) // 2)
        # A different, cold generator also resumes through Tier 1 correctly.
        self.assertEqual(consume(value for value in range(10)), 45)
        self.assertEqual(consume(iter(())), 0)

    @disable_gc()
    def test_generator_resume_after_extended_loop_executor(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec("def generate(count):\n"
             "    for value in range(count):\n" +
             "        pass\n" * 270 +
             "        yield value\n", namespace)
        generate = namespace['generate']
        self.enterContext(clear_executors(generate))
        instructions = list(dis.get_instructions(generate))
        prefix = next(previous.offset for previous, current in
                      itertools.pairwise(instructions)
                      if previous.opname == 'EXTENDED_ARG' and
                      current.opname == 'JUMP_BACKWARD')
        resume = next(instruction.offset for instruction in instructions
                      if instruction.opname == 'RESUME' and instruction.arg != 0)
        # The loop becomes hot before the yield's resume. Its executor replaces
        # EXTENDED_ARG, which the later method compilation must reconstruct.
        count = TIER2_THRESHOLD * 2
        self.assertEqual(sum(generate(count)), count * (count - 1) // 2)
        self.assertIsNotNone(_opcode.get_executor(generate.__code__, prefix))
        count = TIER2_RESUME_THRESHOLD * 2
        self.assertEqual(sum(generate(count)), count * (count - 1) // 2)
        self.assertIn('_YIELD_VALUE', get_opnames(
            _opcode.get_executor(generate.__code__, resume)))



    @disable_gc()
    def test_method_closure_returns_to_compiled_caller(self):
        def factory(offset):
            def add(value):
                return value + offset
            return add

        def caller(function, value):
            result = function(value)
            return result, sys._jit.is_active()

        first = factory(10)
        list(map(first, itertools.repeat(2, TIER2_RESUME_THRESHOLD)))
        list(itertools.starmap(caller, itertools.repeat(
            (first, 2), TIER2_RESUME_THRESHOLD)))
        cell = first.__closure__[0]
        references = sys.getrefcount(cell)
        for _ in range(20):
            result, active = caller(first, 2)
            self.assertEqual(result, 12)
            self.assertTrue(active)
        if not Py_GIL_DISABLED:
            self.assertEqual(sys.getrefcount(cell), references)
        for offset in range(20):
            result, active = caller(factory(offset), 3)
            self.assertEqual(result, offset + 3)
            self.assertTrue(active)
        with self.assertRaises(TypeError):
            caller(factory("wrong type"), 3)

    @disable_gc()
    def test_method_call_shared_closure_code(self):
        def factory(offset):
            def add(value, scale=1):
                return (value + offset) * scale
            return add

        def call(function, value):
            return function(value)

        first = factory(10)
        self.assertEqual(list(itertools.starmap(call, itertools.repeat(
            (first, 2), TIER2_RESUME_THRESHOLD))),
            [12] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(call.__code__, 0)
        self.assertIn("_CHECK_FUNCTION_VERSION", get_opnames(executor))
        second = factory(20)
        second.__defaults__ = (3,)
        for _ in range(20):
            self.assertEqual(call(first, 2), 12)
            self.assertEqual(call(second, 2), 66)
        self.assertTrue(executor.is_valid())
        second.__defaults__ = None
        with self.assertRaises(TypeError):
            call(second, 2)

        def other_factory(offset):
            def subtract(value):
                return value - offset
            return subtract

        first.__code__ = other_factory(0).__code__
        self.assertEqual(call(first, 2), -8)
        self.assertEqual(call(lambda value: value * 4, 3), 12)
        with self.assertRaises(TypeError):
            call(None, 2)

    @disable_gc()
    def test_method_exact_call_shared_closure_code(self):
        def factory(offset):
            def add(value):
                return value + offset
            return add

        def call(function, value):
            return function(value)

        first = factory(10)
        self.assertEqual(list(itertools.starmap(call, itertools.repeat(
            (first, 2), TIER2_RESUME_THRESHOLD))),
            [12] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_CHECK_FUNCTION_VERSION", get_opnames(
            _opcode.get_executor(call.__code__, 0)))
        for offset in range(20):
            self.assertEqual(call(factory(offset), 3), offset + 3)
        first.__defaults__ = (100,)
        self.assertEqual(call(first, 2), 12)
        from _testcapi import function_setvectorcall
        function_setvectorcall(first)
        self.assertEqual(call(first, 2), "overridden")
        with self.assertRaises(TypeError):
            call(factory("wrong type"), 3)

    @disable_gc()
    def test_borrowed_truth_test_cleanup(self):
        class AlwaysTrue:
            pass

        for value, false_value in (([1], []), ("abc", ""),
                                   (12345, 0), (AlwaysTrue(), None)):
            with self.subTest(value=value):
                def choose(value):
                    if value:
                        return 42
                    return 17

                self.assertEqual(list(map(choose, itertools.repeat(
                    value, TIER2_RESUME_THRESHOLD))),
                    [42] * TIER2_RESUME_THRESHOLD)
                names = get_opnames(_opcode.get_executor(choose.__code__, 0))
                self.assertIn("_POP_TOP_NOP", names)
                self.assertNotIn("_POP_TOP", names)
                self.assertNotIn("_POP_TOP_INT", names)
                self.assertNotIn("_POP_TOP_UNICODE", names)
                self.assertEqual(choose(false_value), 17)
                if isinstance(value, AlwaysTrue):
                    AlwaysTrue.__bool__ = lambda self: False
                    self.assertEqual(choose(value), 17)

                class Broken:
                    def __bool__(self):
                        raise ValueError("truth test")

                with self.assertRaisesRegex(ValueError, "truth test"):
                    choose(Broken())
                reset_code(choose)

        events = []

        class Temporary:
            def __del__(self):
                events.append("closed")

        def choose_temporary(factory):
            if factory():
                events.append("body")
                return 42
            return 17

        self.assertEqual(list(map(choose_temporary, itertools.repeat(
            Temporary, TIER2_RESUME_THRESHOLD))),
            [42] * TIER2_RESUME_THRESHOLD)
        self.assertEqual(events, ["closed", "body"] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_POP_TOP", get_opnames(get_first_executor(choose_temporary)))

    @disable_gc()
    def test_guarded_scalar_local_store_cleanup(self):
        def replace(value):
            value = 42
            return 123

        self.assertEqual(list(map(replace,
            itertools.repeat(None, TIER2_RESUME_THRESHOLD))),
            [123] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED:
            self.assertIn("_STORE_FAST_NOESCAPE", get_opnames(
                _opcode.get_executor(replace.__code__, 0)))
        events = []
        class Previous:
            def __del__(self):
                frame = sys._getframe(1)
                events.append((frame.f_code.co_name, frame.f_locals.get("value")))

        # Sole ownership must take the ordinary store path. The finalizer
        # observes the replacement already installed in the real frame.
        self.assertEqual(replace(Previous()), 123)
        self.assertEqual(events, [("replace", 42)])
        shared = Previous()
        self.assertEqual(replace(shared), 123)
        self.assertEqual(len(events), 1)
        for previous in (None, True, 12345, 1.25, "text", b"bytes", 2**100):
            self.assertEqual(replace(previous), 123)

    @disable_gc()
    def test_validity_checks_across_method_branches(self):
        def choose(left, right):
            if left < right:
                return left + 1
            return right + 1

        arguments = itertools.cycle(((1, 3), (3, 1)))
        results = list(itertools.starmap(choose,
            itertools.islice(arguments, TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results, [2] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(choose.__code__, 0)
        self.assertLessEqual(count_ops(executor, "_CHECK_VALIDITY"), 2)

        calls = []
        class Compare:
            def __lt__(self, other):
                calls.append("compare")
                return True
            def __add__(self, other):
                return 42
        self.assertEqual(choose(Compare(), 3), 42)
        self.assertEqual(calls, ["compare"])

        namespace = {"VALUE": 10, "change": [False]}
        exec(textwrap.dedent("""
            def callback():
                global VALUE
                if change[0]:
                    VALUE = 20
            def branch(flag):
                if flag:
                    callback()
                return VALUE
        """), namespace)
        branch = namespace["branch"]
        flags = itertools.islice(itertools.cycle((False, True)),
                                 TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(map(branch, flags)), [10] * TIER2_RESUME_THRESHOLD)
        namespace["change"][0] = True
        self.assertEqual(branch(True), 20)
        self.assertEqual(branch(False), 20)

    @unittest.skipIf(Py_GIL_DISABLED, "attribute regions require the GIL")
    def test_attribute_region_allocation_error_location(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import _opcode
            import _testcapi
            import dis
            import gc
            import sys
            from _testinternalcapi import TIER2_RESUME_THRESHOLD

            class Value:
                pass
            def increment(obj):
                obj.value += 1
                return obj.value

            gc.disable()
            obj = Value()
            obj.value = 1000
            list(map(increment, [obj] * TIER2_RESUME_THRESHOLD))
            executor = _opcode.get_executor(increment.__code__, 0)
            assert any(op[0] == '_UPDATE_INT_ATTRIBUTE' for op in executor)
            # Crossing a digit boundary bypasses the single-digit freelist.
            obj.value = (1 << sys.int_info.bits_per_digit) - 1
            failed = False
            _testcapi.set_nomemory(0, 1)
            try:
                increment(obj)
            except MemoryError as exc:
                _testcapi.remove_mem_hooks()
                failed = True
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                assert tb.tb_frame.f_code is increment.__code__
                assert dis.opname[increment.__code__.co_code[tb.tb_lasti]] == 'BINARY_OP'
                assert obj.value == (1 << sys.int_info.bits_per_digit) - 1
            finally:
                _testcapi.remove_mem_hooks()
            assert failed

            def dot(obj):
                return obj.x * obj.x + obj.y * obj.y
            obj.x, obj.y = 1.5, 2.5
            list(map(dot, [obj] * TIER2_RESUME_THRESHOLD))
            executor = _opcode.get_executor(dot.__code__, 0)
            assert any(op[0].startswith('_FLOAT_ATTRIBUTE_SUM_PRODUCTS') for op in executor)
            # Keep enough floats alive to exhaust the float freelist.
            held = [float(i) for i in range(1000)]
            failed = False
            _testcapi.set_nomemory(0, 1)
            try:
                dot(obj)
            except MemoryError as exc:
                _testcapi.remove_mem_hooks()
                failed = True
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                assert tb.tb_frame.f_code is dot.__code__
                assert dis.opname[dot.__code__.co_code[tb.tb_lasti]] == 'BINARY_OP'
            finally:
                _testcapi.remove_mem_hooks()
            assert failed
        """))

    @disable_gc()
    def test_attribute_regions_in_loop_traces(self):
        class Value:
            def __init__(self, x, y, z):
                self.x, self.y, self.z = x, y, z
                self.count = 0
        def dot_loop(a, b, n, completed):
            result = 0.0
            try:
                for _ in range(n):
                    result += a.x * b.x + a.y * b.y + a.z * b.z
            finally:
                completed.append(True)
            return result
        def update_loop(a, n, completed):
            try:
                for _ in range(n):
                    a.count += 1
            finally:
                completed.append(True)
            return a.count

        a, b = Value(1.0, 2.0, 3.0), Value(4.0, 5.0, 6.0)
        completed = []
        n = TIER2_THRESHOLD * 32
        self.assertEqual(dot_loop(a, b, n, completed), 32.0 * n)
        self.assertEqual(update_loop(a, n, completed), n)
        self.assertEqual(completed, [True, True])
        for function, opcode in ((dot_loop, "_FLOAT_ATTRIBUTE_SUM_PRODUCTS"),
                                 (update_loop, "_UPDATE_INT_ATTRIBUTE")):
            executors = get_all_executors(function)
            self.assertTrue(executors)
            if not Py_GIL_DISABLED:
                self.assertTrue(any(op[0].startswith(opcode)
                                    for executor in executors for op in executor))
        del a.x
        with self.assertRaises(AttributeError):
            dot_loop(a, b, n, completed)
        self.assertEqual(completed, [True, True, True])

    @disable_gc()
    def test_integer_attribute_updates_and_fallbacks(self):
        class Slot:
            __slots__ = ("value",)
        class Managed:
            pass
        def increment(obj):
            obj.value += 1
            return obj.value
        def decrement(obj):
            obj.value -= 2
            return obj.value

        for cls in (Slot, Managed):
            for function, delta in ((increment, 1), (decrement, -2)):
                obj = cls()
                with clear_executors(function):
                    obj.value = 0
                    list(map(function, itertools.repeat(obj, TIER2_RESUME_THRESHOLD)))
                    executor = _opcode.get_executor(function.__code__, 0)
                    if not Py_GIL_DISABLED:
                        self.assertIn("_UPDATE_INT_ATTRIBUTE", get_opnames(executor))
                    for value in (0, -1, (1 << 30) - 1, -(1 << 30) + 1,
                                  1 << 100, -(1 << 100), True, 1.25):
                        obj.value = value
                        self.assertEqual(function(obj), value + delta)
                    del obj.value
                    with self.assertRaises(AttributeError):
                        function(obj)
                    if cls is Managed:
                        obj.__dict__ = {"value": 50}
                        self.assertEqual(function(obj), 50 + delta)

    @disable_gc()
    def test_integer_attribute_update_callback_changes_descriptor(self):
        class Item:
            pass
        def increment(obj):
            obj.value += 1
            return obj.value

        obj = Item()
        obj.value = 0
        list(map(increment, itertools.repeat(obj, TIER2_RESUME_THRESHOLD)))
        _opcode.get_executor(increment.__code__, 0)
        stored = []
        class Number(int):
            def __iadd__(self, value):
                Item.value = property(lambda self: 99,
                                      lambda self, value: stored.append(value))
                return int(self) + value
        obj.value = Number(41)
        self.assertEqual(increment(obj), 99)
        self.assertEqual(stored, [42])

    @disable_gc()
    def test_positional_default_frame_binding(self):
        token = object()
        def callee(a, /, b=token, c=42):
            return (a, b, c)
        def caller(function, value):
            return function(value)

        self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
            (callee, 1), TIER2_RESUME_THRESHOLD))),
            [(1, token, 42)] * TIER2_RESUME_THRESHOLD)
        _opcode.get_executor(caller.__code__, 0)
        callee.__defaults__ = (12, 34)
        self.assertEqual(caller(callee, 2), (2, 12, 34))
        callee.__defaults__ = None
        with self.assertRaises(TypeError):
            caller(callee, 2)

        # Defaults can own arbitrary objects, and their references must stay
        # alive in an escaped callee frame after the function defaults change.
        def retain(a, b=token):
            return sys._getframe()
        with clear_executors(caller):
            frames = list(itertools.starmap(caller, itertools.repeat(
                (retain, 1), TIER2_RESUME_THRESHOLD)))
            _opcode.get_executor(caller.__code__, 0)
            retain.__defaults__ = None
            for frame in frames:
                self.assertIs(frame.f_locals["b"], token)
                frame.clear()

    @disable_gc()
    def test_trivial_attribute_setter_and_fallbacks(self):
        capi = import_helper.import_module("_testcapi")
        class Slot:
            __slots__ = ("value",)
            def set(self, value):
                self.value = value
        class Managed:
            def set(self, value):
                self.value = value
        def caller(function, obj, value):
            return function(obj, value)

        for cls in (Slot, Managed):
            obj = cls()
            with clear_executors(caller):
                results = list(itertools.starmap(caller, itertools.repeat(
                    (cls.set, obj, 42), TIER2_RESUME_THRESHOLD)))
                self.assertEqual(results, [None] * TIER2_RESUME_THRESHOLD)
                executor = _opcode.get_executor(caller.__code__, 0)
                if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
                    self.assertIn("_CALL_STORE_ATTRIBUTE", get_opnames(executor))
                self.assertIsNone(caller(cls.set, obj, 43))
                self.assertEqual(obj.value, 43)
                del obj.value
                caller(cls.set, obj, 44)
                self.assertEqual(obj.value, 44)
                events = []
                class Finalizer:
                    def __del__(self):
                        events.append(sys._getframe(1).f_code.co_name)
                        events.append(obj.value)
                obj.value = Finalizer()
                caller(cls.set, obj, 45)
                self.assertEqual(events, ["set", 45])
                if cls is Managed:
                    namespace = obj.__dict__
                    wid = capi.add_dict_watcher(0)
                    try:
                        capi.watch_dict(wid, namespace)
                        caller(cls.set, obj, 46)
                        self.assertEqual(capi.get_dict_watcher_events(), ["mod:value:46"])
                    finally:
                        capi.unwatch_dict(wid, namespace)
                        capi.clear_dict_watcher(wid)
                    obj.__dict__ = {}
                    caller(cls.set, obj, 47)
                    self.assertEqual(obj.__dict__, {"value": 47})
                events.clear()
                def changed(instance, value):
                    events.append((sys._getframe(1).f_code.co_name, value))
                cls.value = property(lambda self: None, changed)
                caller(cls.set, obj, 48)
                self.assertEqual(events, [("set", 48)])

    @disable_gc()
    def test_trivial_bound_setter_monitoring(self):
        class Record:
            def set(self, value):
                self.value = value
        def caller(function, value):
            return function(value)
        obj = Record()
        bound = obj.set
        list(itertools.starmap(caller, itertools.repeat(
            (bound, 42), TIER2_RESUME_THRESHOLD)))
        executor = _opcode.get_executor(caller.__code__, 0)
        if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
            self.assertIn("_CALL_STORE_ATTRIBUTE", get_opnames(executor))
        caller(bound, 43)
        self.assertEqual(obj.value, 43)
        monitoring = sys.monitoring
        tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
        seen = []
        monitoring.use_tool_id(tool, "test setter call")
        try:
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                lambda code, offset, value: seen.append((code, value)))
            monitoring.set_local_events(tool, Record.set.__code__, monitoring.events.PY_RETURN)
            caller(bound, 44)
            self.assertEqual(obj.value, 44)
            self.assertEqual(seen, [(Record.set.__code__, None)])
        finally:
            monitoring.set_local_events(tool, Record.set.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @disable_gc()
    def test_trivial_setter_argument_order_and_code_change(self):
        class Record:
            pass
        def setter(value, record):
            record.value = value
        def caller(function, record, value):
            return function(value, record)
        obj = Record()
        list(itertools.starmap(caller, itertools.repeat(
            (setter, obj, 42), TIER2_RESUME_THRESHOLD)))
        executor = _opcode.get_executor(caller.__code__, 0)
        if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
            self.assertIn("_CALL_STORE_ATTRIBUTE", get_opnames(executor))
        self.assertIsNone(caller(setter, obj, 99))
        self.assertEqual(obj.value, 99)
        def replacement(value, record):
            record.changed = value
            return "changed"
        setter.__code__ = replacement.__code__
        self.assertEqual(caller(setter, obj, 100), "changed")
        self.assertEqual(obj.changed, 100)
        self.assertEqual(obj.value, 99)

    @disable_gc()
    def test_trivial_attribute_call_and_fallbacks(self):
        class Slot:
            __slots__ = ("value",)
            def get(self):
                return self.value
        class Managed:
            def get(self):
                return self.value
        def caller(function, obj):
            return function(obj)

        token = object()
        for cls in (Slot, Managed):
            obj = cls()
            obj.value = token
            with clear_executors(caller):
                self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
                    (cls.get, obj), TIER2_RESUME_THRESHOLD))),
                    [token] * TIER2_RESUME_THRESHOLD)
                if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
                    self.assertIn("_CALL_RETURN_ATTRIBUTE", get_opnames(
                        _opcode.get_executor(caller.__code__, 0)))
                obj.value = 42
                self.assertEqual(caller(cls.get, obj), 42)
                del obj.value
                with self.assertRaises(AttributeError):
                    caller(cls.get, obj)
                if cls is Managed:
                    obj.__dict__ = {"value": token}
                    self.assertIs(caller(cls.get, obj), token)
                cls.value = property(lambda self: sys._getframe().f_back.f_code.co_name)
                self.assertEqual(caller(cls.get, obj), "get")

    @disable_gc()
    def test_simple_constructor_fields_and_order(self):
        class Managed:
            def __init__(self, a, b, c):
                self.third = c
                self.first = a
                self.second = b
        class Slot:
            __slots__ = ("first", "second", "third")
            def __init__(self, a, b, c):
                self.third = c
                self.first = a
                self.second = b
        def make(cls, a, b, c):
            return cls(a, b, c)

        tokens = (object(), object(), object())
        for cls in (Managed, Slot):
            with clear_executors(make):
                objects = list(itertools.starmap(make, itertools.repeat(
                    (cls, *tokens), TIER2_RESUME_THRESHOLD)))
                executor = _opcode.get_executor(make.__code__, 0)
                if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
                    self.assertTrue(any(op[0].startswith("_METHOD_TRY_SIMPLE_INIT")
                                        for op in executor))
                for obj in objects:
                    self.assertIs(obj.first, tokens[0])
                    self.assertIs(obj.second, tokens[1])
                    self.assertIs(obj.third, tokens[2])
                if cls is Managed:
                    self.assertEqual(list(objects[-1].__dict__),
                                     ["third", "first", "second"])

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "GIL-only constructor fast path")
    def test_simple_constructor_gc_observes_initializer_frame(self):
        class Item:
            def __init__(self, value):
                self.value = value
        def make(cls, value):
            return cls(value)
        seen = []
        class Previous:
            def __del__(self):
                seen.append(("destroyed", sys._getframe(1).f_code.co_name))
        def callback(phase, info):
            frame = sys._getframe(1)
            if phase == "start" and frame.f_code is Item.__init__.__code__ and not seen:
                seen.append(("entered", frame.f_code.co_name))
                frame.f_locals["self"].value = Previous()

        list(itertools.starmap(make, itertools.repeat(
            (Item, 42), TIER2_RESUME_THRESHOLD)))
        _opcode.get_executor(make.__code__, 0)
        thresholds = gc.get_threshold()
        try:
            gc.callbacks.append(callback)
            gc.set_threshold(1, 1, 1)
            gc.enable()
            for _ in range(30):
                self.assertEqual(make(Item, 42).value, 42)
                if seen:
                    break
            self.assertEqual(seen, [("entered", "__init__"),
                                    ("destroyed", "__init__")])
        finally:
            gc.disable()
            gc.callbacks.remove(callback)
            gc.set_threshold(*thresholds)

    @disable_gc()
    def test_simple_constructor_local_monitoring(self):
        class Item:
            def __init__(self, value):
                self.value = value
        def make(cls, value):
            return cls(value)

        list(itertools.starmap(make, itertools.repeat(
            (Item, 1), TIER2_RESUME_THRESHOLD)))
        _opcode.get_executor(make.__code__, 0)
        monitoring = sys.monitoring
        tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
        seen = []
        monitoring.use_tool_id(tool, "test constructor monitoring")
        try:
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         lambda code, offset, value: seen.append(value))
            monitoring.set_local_events(tool, Item.__init__.__code__, monitoring.events.PY_RETURN)
            self.assertEqual(make(Item, 42).value, 42)
            self.assertEqual(seen, [None])
        finally:
            monitoring.set_local_events(tool, Item.__init__.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @disable_gc()
    def test_constructor_method_call_and_changes(self):
        class Item:
            def __init__(self, value):
                self.value = value

        def make(cls, value):
            return cls(value)

        instances = list(itertools.starmap(make, itertools.repeat(
            (Item, 42), TIER2_RESUME_THRESHOLD)))
        self.assertTrue(all(obj.value == 42 for obj in instances))
        executor = _opcode.get_executor(make.__code__, 0)
        self.assertTrue(any(op[0] == "_METHOD_CALL" and op[1] in (1, 2)
                            for op in executor))
        self.assertEqual(make(Item, 12).value, 12)

        def replacement(self, value):
            self.value = value + 1
        Item.__init__ = replacement
        self.assertEqual(make(Item, 12).value, 13)
        token = object()
        Item.__new__ = staticmethod(lambda cls, value: token)
        self.assertIs(make(Item, 12), token)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Constructor inlining requires the GIL")
    def test_constructor_inline_after_function_cache_eviction(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        exec('class Item:\n'
             '    def __init__(self, value):\n'
             '        self.value = value + 1\n'
             'def make(cls, value):\n'
             '    return cls(value)\n', namespace)
        Item = namespace['Item']
        make = namespace['make']
        self.enterContext(clear_executors(make))
        # Populate the constructor cache before evicting function versions.
        for _ in range(_testinternalcapi.SPECIALIZATION_THRESHOLD):
            self.assertEqual(make(Item, 10).value, 11)
        _testinternalcapi.clear_function_version_cache()
        count = TIER2_RESUME_THRESHOLD + 10
        instances = list(itertools.starmap(make, itertools.repeat((Item, 10), count)))
        self.assertTrue(all(obj.value == 11 for obj in instances))
        executor = get_first_executor(make)
        self.assertIsNotNone(executor)
        # A native initializer returns to its cleanup shim. Falling back to
        # the method entry would use _METHOD_CALL with oparg 1 instead.
        self.assertIn(2, [op[1] for op in executor if op[0] == '_METHOD_CALL'])
        self.assertNotIn(1, [op[1] for op in executor if op[0] == '_METHOD_CALL'])
        exec('def replacement(self, value):\n'
             '    self.value = value + 2\n', namespace)
        Item.__init__.__code__ = namespace['replacement'].__code__
        self.assertEqual(make(Item, 10).value, 12)

    @disable_gc()
    def test_constructor_nested_calls_and_recursion(self):
        class Item:
            def __init__(self, depth):
                if depth:
                    self.child = type(self)(depth - 1)
                self.depth = depth

        def make(cls, depth):
            return (cls(depth), cls(depth)).count(None)

        self.assertEqual(list(itertools.starmap(make, itertools.repeat(
            (Item, 2), TIER2_RESUME_THRESHOLD))),
            [0] * TIER2_RESUME_THRESHOLD)
        _opcode.get_executor(make.__code__, 0)
        with self.assertRaises(RecursionError):
            make(Item, sys.getrecursionlimit() * 2)
        self.assertEqual(make(Item, 2), 0)

    @disable_gc()
    def test_constructor_argument_binding(self):
        class Default:
            def __init__(self, value, extra=4):
                self.value = value + extra
        class Keywords:
            def __init__(self, value, *, extra=4):
                self.value = value + extra
        class Varargs:
            def __init__(self, *values):
                self.value = sum(values) + 4
        class Varkw:
            def __init__(self, value, **kwargs):
                self.value = value + kwargs.get("extra", 4)
        def make(cls, value):
            return cls(value).value

        for cls in (Default, Keywords, Varargs, Varkw):
            with clear_executors(make):
                self.assertEqual(list(itertools.starmap(make, itertools.repeat(
                    (cls, 3), TIER2_RESUME_THRESHOLD))),
                    [7] * TIER2_RESUME_THRESHOLD)
                _opcode.get_executor(make.__code__, 0)
                self.assertEqual(make(cls, 5), 9)

    @disable_gc()
    def test_constructor_errors_and_materialized_frame(self):
        class Item:
            def __init__(self, value):
                if value == 1:
                    return 42
                if value == 2:
                    raise ValueError("init failed")
                if value == 3:
                    self.frame = sys._getframe()
                self.value = value

        def make(cls, value):
            return cls(value)

        list(itertools.starmap(make, itertools.repeat(
            (Item, 0), TIER2_RESUME_THRESHOLD)))
        _opcode.get_executor(make.__code__, 0)
        with self.assertRaisesRegex(TypeError, "__init__.*should return None"):
            make(Item, 1)
        with self.assertRaisesRegex(ValueError, "init failed"):
            make(Item, 2)
        obj = make(Item, 3)
        self.assertIs(obj.frame.f_locals["self"], obj)
        self.assertEqual(obj.frame.f_locals["value"], 3)
        obj.frame.clear()
        self.assertEqual(make(Item, 4).value, 4)
        def needs_two(self, value, extra):
            self.value = value + extra
        Item.__init__.__code__ = needs_two.__code__
        with self.assertRaises(TypeError):
            make(Item, 1)

    @disable_gc()
    def test_compiled_c_vectorcall_frame_arguments(self):
        def target(a, b, c, d, e, f, g, h, i, inspect_frame=False):
            if inspect_frame:
                return sys._getframe()
            return a, b, c, d, e, f, g, h, i
        tokens = tuple(object() for _ in range(9))
        args = (*tokens, False)
        self.assertEqual(list(itertools.starmap(target, itertools.repeat(
            args, TIER2_RESUME_THRESHOLD))), [tokens] * TIER2_RESUME_THRESHOLD)
        _opcode.get_executor(target.__code__, 0)
        frame = next(itertools.starmap(target, [(*tokens, True)]))
        self.assertIs(frame.f_code, target.__code__)
        self.assertEqual(tuple(frame.f_locals[name] for name in "abcdefghi"), tokens)
        self.assertIs(frame.f_locals["inspect_frame"], True)
        frame.clear()
        self.assertEqual(target(*tokens), tokens)
        self.assertEqual(target(*tokens, inspect_frame=False), tokens)
        with self.assertRaises(TypeError):
            next(itertools.starmap(target, [tokens[:8]]))
        with self.assertRaises(TypeError):
            next(itertools.starmap(target, [(*tokens, False, None)]))

    @disable_gc()
    def test_compiled_c_vectorcall_closure(self):
        captured = object()
        def target(value, inspect_frame=False):
            if inspect_frame:
                return sys._getframe()
            return value, captured
        token = object()
        self.assertEqual(list(itertools.starmap(target, itertools.repeat(
            (token, False), TIER2_RESUME_THRESHOLD))),
            [(token, captured)] * TIER2_RESUME_THRESHOLD)
        self.assertIsNotNone(get_first_executor(target))
        frame = next(itertools.starmap(target, [(token, True)]))
        self.assertIs(frame.f_locals["value"], token)
        self.assertIs(frame.f_locals["captured"], captured)
        frame.clear()
        captured = object()
        self.assertEqual(next(itertools.starmap(target, [(token, False)])),
                         (token, captured))

    @disable_gc()
    def test_compiled_c_vectorcall_recursive_callback(self):
        def recurse(depth):
            if depth:
                return next(map(recurse, (depth - 1,)))
            return 42
        list(map(recurse, itertools.repeat(0, TIER2_RESUME_THRESHOLD)))
        self.assertIsNotNone(get_first_executor(recurse))
        self.assertEqual(next(map(recurse, [5])), 42)
        with self.assertRaises(RecursionError):
            next(map(recurse, [sys.getrecursionlimit() * 2]))
        self.assertEqual(next(map(recurse, [5])), 42)

    def test_c_vectorcall_without_resume(self):
        def target():
            return 42
        code = target.__code__
        instructions = list(dis.get_instructions(code))
        self.assertEqual(instructions[0].opname, "RESUME")
        target.__code__ = code.replace(co_code=code.co_code[instructions[1].offset:])
        self.assertEqual(next(itertools.starmap(target, [()])), 42)

    @disable_gc()
    def test_trivial_root_c_vectorcall_stays_warm(self):
        def identity(value):
            return value
        list(map(identity, itertools.repeat(42, TIER2_RESUME_THRESHOLD)))
        executor = _opcode.get_executor(identity.__code__, 0)
        _testinternalcapi.invalidate_cold_executors()
        self.assertTrue(executor.is_valid())
        self.assertEqual(list(map(identity, [42])), [42])
        _testinternalcapi.invalidate_cold_executors()
        self.assertTrue(executor.is_valid())
        # Without an intervening call it should still be collected normally.
        _testinternalcapi.invalidate_cold_executors()
        self.assertFalse(executor.is_valid())

    @disable_gc()
    def test_trivial_root_c_vectorcall(self):
        def identity(value, unused=None):
            return value
        def constant(value):
            return False
        token = object()
        for function, expected in ((identity, token), (constant, False)):
            args = (token, None) if function is identity else (token,)
            self.assertEqual(list(itertools.starmap(
                function, itertools.repeat(args, TIER2_RESUME_THRESHOLD))),
                [expected] * TIER2_RESUME_THRESHOLD)
            _opcode.get_executor(function.__code__, 0)
            self.assertIs(list(itertools.starmap(function, [args]))[0], expected)
            self.assertIs(function(value=token), expected)
            with self.assertRaises(TypeError):
                function()
            with self.assertRaises(TypeError):
                list(itertools.starmap(function, [(token, None, None)]))
        self.assertIs(identity(token), token)
        seen = []
        class Disposable:
            def __del__(self):
                seen.append(sys._getframe(1).f_code is identity.__code__)
        self.assertIs(list(itertools.starmap(identity, [(token, Disposable())]))[0], token)
        self.assertEqual(seen, [False])
        def replacement(value):
            return True
        constant.__code__ = replacement.__code__
        self.assertEqual(list(map(constant, [token])), [True])

    @disable_gc()
    def test_trivial_root_c_vectorcall_attribute_fallbacks(self):
        class Slot:
            __slots__ = ("value",)
        class Managed:
            pass
        for cls in (Slot, Managed):
            def getter(obj):
                return obj.value
            obj = cls()
            obj.value = token = object()
            self.assertEqual(list(map(getter, itertools.repeat(
                obj, TIER2_RESUME_THRESHOLD))), [token] * TIER2_RESUME_THRESHOLD)
            _opcode.get_executor(getter.__code__, 0)
            obj.value = other = object()
            self.assertEqual(list(map(getter, [obj])), [other])
            del obj.value
            with self.assertRaises(AttributeError):
                list(map(getter, [obj]))
            # The fallback must retain the getter's traceback frame.
            # assertRaises clears its traceback, so capture a separate call.
            try:
                list(map(getter, [obj]))
            except AttributeError as exc:
                self.assertIs(exc.__traceback__.tb_next.tb_frame.f_code, getter.__code__)
            if cls is Managed:
                obj.__dict__ = {"value": token}
                self.assertEqual(list(map(getter, [obj])), [token])
                obj.__dict__["value"] = other
                self.assertEqual(list(map(getter, [obj])), [other])
            frames = []
            def descriptor(self):
                frames.append(sys._getframe(1).f_code)
                return token
            cls.value = property(descriptor)
            self.assertEqual(list(map(getter, [obj])), [token])
            self.assertEqual(frames, [getter.__code__])

    @disable_gc()
    def test_trivial_attribute_item_calls(self):
        class Slot:
            __slots__ = ("data",)
        class Managed:
            pass
        for cls in (Slot, Managed):
            # MAKE_FUNCTION must initialize function versions on fresh code.
            # reset_code clears that version; FunctionType never assigns it.
            namespace = {}
            exec("def getter(obj, key): return obj.data[key]\n"
                 "def caller(obj, key): return getter(obj, key)\n", namespace)
            getter, caller = namespace["getter"], namespace["caller"]
            obj = cls()
            first, second = object(), object()
            obj.data = (first, second)
            self.assertEqual(list(itertools.starmap(getter, itertools.repeat(
                (obj, 0), TIER2_RESUME_THRESHOLD))), [first] * TIER2_RESUME_THRESHOLD)
            _opcode.get_executor(getter.__code__, 0)
            self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
                (obj, 0), TIER2_RESUME_THRESHOLD))), [first] * TIER2_RESUME_THRESHOLD)
            if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
                self.assertIn("_CALL_RETURN_ATTRIBUTE_ITEM", get_opnames(
                    _opcode.get_executor(caller.__code__, 0)))
            for function in (getter, caller):
                for sequence in ((first, second), [first, second]):
                    obj.data = sequence
                    for key, expected in ((0, first), (1, second), (-1, second), (-2, first)):
                        self.assertEqual(list(itertools.starmap(function, [(obj, key)])), [expected])
                    for key, error in ((2, IndexError), (-3, IndexError),
                                       (10**100, IndexError), ("x", TypeError)):
                        try:
                            list(itertools.starmap(function, [(obj, key)]))
                        except error as exc:
                            tb = exc.__traceback__
                            while tb.tb_next is not None:
                                tb = tb.tb_next
                            self.assertIs(tb.tb_frame.f_code, getter.__code__)
                        else:
                            self.fail("missing subscript error")
                frames = []
                class Key:
                    def __index__(self):
                        frames.append(sys._getframe(1).f_code)
                        return 1
                self.assertIs(function(obj, Key()), second)
                self.assertEqual(frames, [getter.__code__])
                class Sequence(list):
                    def __getitem__(self, key):
                        frames.append(sys._getframe(1).f_code)
                        return first
                obj.data = Sequence()
                self.assertIs(function(obj, 0), first)
                self.assertEqual(frames[-1], getter.__code__)
                obj.data = []
                with self.assertRaises(IndexError):
                    function(obj, 0)
            if cls is Managed:
                obj.__dict__ = {"data": [second]}
                self.assertIs(getter(obj, 0), second)
                self.assertIs(caller(obj, 0), second)
            cls.data = property(lambda self: [first])
            self.assertIs(getter(obj, 0), first)
            self.assertIs(caller(obj, 0), first)

    @disable_gc()
    def test_trivial_root_c_vectorcall_observers(self):
        def identity(value):
            return value
        list(map(identity, range(TIER2_RESUME_THRESHOLD)))
        _opcode.get_executor(identity.__code__, 0)
        seen = []
        def observer(frame, event, arg):
            if frame.f_code is identity.__code__:
                seen.append(event)
            return observer
        for install in (sys.settrace, sys.setprofile):
            seen.clear()
            install(observer)
            try:
                self.assertEqual(list(map(identity, [42])), [42])
            finally:
                install(None)
            self.assertIn("call", seen)
            self.assertIn("return", seen)
        list(map(identity, range(TIER2_RESUME_THRESHOLD)))
        monitoring = sys.monitoring
        tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
        monitoring.use_tool_id(tool, "trivial root vectorcall")
        seen.clear()
        try:
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         lambda code, offset, value: seen.append(value))
            monitoring.set_local_events(tool, identity.__code__, monitoring.events.PY_RETURN)
            self.assertEqual(list(map(identity, [43])), [43])
            self.assertEqual(seen, [43])
        finally:
            monitoring.set_local_events(tool, identity.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @disable_gc()
    def test_trivial_call_returns_and_code_changes(self):
        def identity(value):
            return value
        def constant(value):
            return False
        def replacement(value):
            return True
        def caller(function, value):
            return function(value)

        token = object()
        for function, expected, opcode in (
            (identity, token, "_CALL_RETURN_ARGUMENT"),
            (constant, False, "_CALL_RETURN_CONSTANT"),
        ):
            with clear_executors(caller):
                self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
                    (function, token), TIER2_RESUME_THRESHOLD))),
                    [expected] * TIER2_RESUME_THRESHOLD)
                names = get_opnames(_opcode.get_executor(caller.__code__, 0))
                if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
                    self.assertIn(opcode, names)
                    self.assertNotIn("_PUSH_FRAME", names)
                self.assertIs(caller(function, token), expected)
                if function is constant:
                    constant.__code__ = replacement.__code__
                    self.assertIs(caller(constant, token), True)

    @disable_gc()
    def test_trivial_bound_call_and_argument_lifetimes(self):
        class Receiver:
            def pick(self, value, unused):
                return value
            def identity(self):
                return self

        def caller(method, value, other):
            return method(value, other)
        def identity(obj):
            return obj.identity()

        obj = Receiver()
        token = object()
        self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
            (obj.pick, token, None), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(map(identity, itertools.repeat(
            obj, TIER2_RESUME_THRESHOLD))), [obj] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
            for function in (caller, identity):
                self.assertIn("_CALL_RETURN_ARGUMENT", get_opnames(
                    _opcode.get_executor(function.__code__, 0)))
        observations = []
        class Disposable:
            def __del__(self):
                observations.append(sys._getframe(1).f_code is Receiver.pick.__code__)
                gc.collect()
        self.assertIs(caller(obj.pick, token, Disposable()), token)
        self.assertEqual(observations, [False])

    @disable_gc()
    def test_trivial_call_local_monitoring_invalidates_caller(self):
        def callee(value):
            return False
        def caller(function, value):
            return function(value)

        self.assertEqual(list(itertools.starmap(caller, itertools.repeat(
            (callee, 1), TIER2_RESUME_THRESHOLD))),
            [False] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED and not sysconfig.get_config_var("WITH_DTRACE"):
            self.assertIn("_CALL_RETURN_CONSTANT", get_opnames(
                _opcode.get_executor(caller.__code__, 0)))
        monitoring = sys.monitoring
        tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
        seen = []
        monitoring.use_tool_id(tool, "test trivial call")
        try:
            monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                         lambda code, offset, value: seen.append((code, value)))
            monitoring.set_local_events(tool, callee.__code__, monitoring.events.PY_RETURN)
            self.assertIs(caller(callee, 2), False)
            self.assertEqual(seen, [(callee.__code__, False)])
        finally:
            monitoring.set_local_events(tool, callee.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Non-immortal namespace folding requires the GIL")
    def test_static_nonimmortal_global_binding_lifetime(self):
        namespace = {'unused': 0}
        observations = []
        def Token(tag):
            def function():
                return tag
            function.tag = tag
            return function
        def collected(ref):
            observations.append(namespace['read']().tag)
            gc.collect()
        namespace['value'] = Token('first')
        first = weakref.ref(namespace['value'], collected)
        exec('def read():\n    return value\n', namespace)
        read = namespace['read']
        self.enterContext(clear_executors(read))
        count = TIER2_RESUME_THRESHOLD + 10
        results = list(itertools.starmap(read, itertools.repeat((), count)))
        self.assertTrue(all(item is namespace['value'] for item in results))
        del results
        executor = _opcode.get_executor(read.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn('_GUARD_GLOBALS_VERSION_AND_IDENTITY', opnames)
        self.assertIn('_LOAD_CONST_INLINE', opnames)
        namespace['unused'] = 1
        self.assertTrue(executor.is_valid())
        clone = types.FunctionType(read.__code__, dict(namespace, value=Token('clone')))
        self.assertEqual(clone().tag, 'clone')
        namespace['value'] = Token('second')
        self.assertEqual(observations, ['second'])
        self.assertIsNone(first())
        self.assertFalse(executor.is_valid())
        self.assertEqual(read().tag, 'second')
        del namespace['value']
        with self.assertRaises(NameError):
            read()

    @disable_gc()
    def test_static_global_instance_class_change(self):
        class First:
            pass
        class Second:
            @property
            def answer(self):
                return 19
        value = First()
        value.answer = 7
        namespace = {'value': value}
        exec('def read():\n    return value.answer\n', namespace)
        read = namespace['read']
        self.enterContext(clear_executors(read))
        count = TIER2_RESUME_THRESHOLD + 10
        self.assertEqual(list(itertools.starmap(read, itertools.repeat((), count))),
                         [7] * count)
        self.assertIsNotNone(_opcode.get_executor(read.__code__, 0))
        value.__class__ = Second
        self.assertEqual(read(), 19)
        value.__class__ = First
        self.assertEqual(read(), 7)

    @disable_gc()
    @unittest.skipIf(Py_GIL_DISABLED, "Stored boolean predicate inlining requires the GIL")
    def test_stored_boolean_predicate_inlining(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for slots in (False, True):
            with self.subTest(slots=slots):
                namespace = {}
                exec('def predicate(self):\n'
                     '    return self.first or (not self.second and self.third)\n',
                     namespace)
                predicate = namespace['predicate']
                attrs = {'predicate': predicate}
                if slots:
                    attrs['__slots__'] = ('first', 'second', 'third')
                Base = type('Base', (), attrs)
                First = type('First', (Base,), {'__slots__': ()} if slots else {})
                Second = type('Second', (Base,), {'__slots__': ('padding',)} if slots else {})
                a, b = First(), Second()
                combinations = list(itertools.product((False, True), repeat=3))
                for _ in range(100):
                    for obj in (a, b):
                        for first, second, third in combinations:
                            obj.first, obj.second, obj.third = first, second, third
                            self.assertIs(obj.predicate(), first or (not second and third))
                def call(obj):
                    return obj.predicate()
                namespace = {'predicate': predicate}
                exec('def unbound(obj):\n    return predicate(obj)\n', namespace)
                unbound = namespace['unbound']
                count = TIER2_RESUME_THRESHOLD + 10
                for function in (call, unbound):
                    self.enterContext(clear_executors(function))
                    self.assertEqual(list(map(function, itertools.repeat(a, count))),
                                     [True] * count)
                    executor = _opcode.get_executor(function.__code__, 0)
                    self.assertIn('_CALL_BOOL_ATTRIBUTES', get_opnames(executor))
                for obj in (a, b):
                    for first, second, third in combinations:
                        obj.first, obj.second, obj.third = first, second, third
                        expected = first or (not second and third)
                        self.assertIs(call(obj), expected)
                        self.assertIs(unbound(obj), expected)
                token = object()
                a.first = token
                self.assertIs(call(a), token)
                events = []
                class Truth:
                    def __bool__(self):
                        events.append(sys._getframe(1).f_code.co_name)
                        return False
                a.first, a.second, a.third = Truth(), False, True
                self.assertIs(call(a), True)
                self.assertEqual(events, ['predicate'])
                a.first = True
                del a.second, a.third
                # Unread missing fields must not change short-circuit behavior.
                self.assertIs(call(a), True)
                a.first, a.second = False, False
                with self.assertRaises(AttributeError):
                    call(a)
                First.third = property(lambda self: False)
                self.assertIs(call(a), False)
                b.first, b.second, b.third = True, False, True
                events.clear()
                def profile(frame, event, arg):
                    if frame.f_code is predicate.__code__:
                        events.append(event)
                sys.setprofile(profile)
                try:
                    self.assertIs(call(b), True)
                finally:
                    sys.setprofile(None)
                self.assertEqual(events, ['call', 'return'])
                monitoring = sys.monitoring
                tool = monitoring.PROFILER_ID
                monitoring.use_tool_id(tool, 'boolean predicate inlining')
                events.clear()
                monitoring.register_callback(tool, monitoring.events.PY_START,
                                             lambda *args: events.append('start'))
                monitoring.register_callback(tool, monitoring.events.PY_RETURN,
                                             lambda *args: events.append('return'))
                try:
                    monitoring.set_local_events(tool, predicate.__code__,
                                                monitoring.events.PY_START |
                                                monitoring.events.PY_RETURN)
                    self.assertIs(call(b), True)
                    self.assertEqual(events, ['start', 'return'])
                finally:
                    monitoring.set_local_events(tool, predicate.__code__, 0)
                    monitoring.register_callback(tool, monitoring.events.PY_START, None)
                    monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
                    monitoring.free_tool_id(tool)
                def replacement(self):
                    return True
                predicate.__code__ = replacement.__code__
                self.assertIs(call(a), True)
                self.assertIs(unbound(a), True)

    @disable_gc()
    def test_small_method_return_cleanup(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for size in range(5):
            with self.subTest(locals=size):
                namespace = {}
                params = ', '.join(f'a{i}=None' for i in range(size))
                # The call in the bytecode keeps this outside the separate
                # frame-free trivial-return optimization.
                exec(f'def small({params}):\n    return len(())\n', namespace)
                small = namespace['small']
                count = TIER2_RESUME_THRESHOLD + 10
                self.assertEqual(list(itertools.starmap(
                    small, itertools.repeat((), count))), [0] * count)
                opnames = get_opnames(_opcode.get_executor(small.__code__, 0))
                self.assertIn(f'_METHOD_RETURN_VALUE_{size}', opnames)
                observations = []
                class Disposable:
                    def __init__(self, index):
                        self.index = index
                    def __del__(self):
                        observations.append((self.index, sys._getframe(1).f_code.co_name))
                        self_result = small()
                        observations.append(self_result)
                        gc.collect()
                namespace['Disposable'] = Disposable
                arguments = ', '.join(f'Disposable({i})' for i in range(size))
                exec(f'def run():\n    return small({arguments})\n', namespace)
                self.assertEqual(namespace['run'](), 0)
                expected = []
                for index in reversed(range(size)):
                    expected.extend([(index, 'run'), 0])
                self.assertEqual(observations, expected)

    @disable_gc()
    def test_return_keeps_materialized_frames(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def keep(value, frames):
            frames.append(sys._getframe())
            return value

        token = object()
        frames = []
        self.assertEqual(list(itertools.starmap(keep, itertools.repeat(
            (token, frames), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)
        _opcode.get_executor(keep.__code__, 0)
        self.assertEqual(len(frames), TIER2_RESUME_THRESHOLD)
        for frame in frames:
            self.assertIs(frame.f_code, keep.__code__)
            self.assertIs(frame.f_locals["value"], token)
            frame.clear()
        frames.clear()

    @disable_gc()
    def test_return_finalizer_reentry_and_collection(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def return_value(value, disposable):
            return value

        token = object()
        self.assertEqual(list(itertools.starmap(return_value, itertools.repeat(
            (token, None), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)
        _opcode.get_executor(return_value.__code__, 0)
        observations = []
        class Disposable:
            def __del__(self):
                caller = sys._getframe(1)
                observations.append(caller.f_code is return_value.__code__)
                observations.append(return_value(42, None))
                gc.collect()
        self.assertIs(return_value(token, Disposable()), token)
        self.assertEqual(observations, [False, 42])

    @disable_gc()
    def test_integer_sequence_containment(self):
        def contains(sequence, key):
            return key in sequence

        def excludes(sequence, key):
            return key not in sequence

        for function, expected in ((contains, True), (excludes, False)):
            self.assertEqual(list(itertools.starmap(function, itertools.repeat(
                (list(range(10)), 5), TIER2_RESUME_THRESHOLD))),
                [expected] * TIER2_RESUME_THRESHOLD)
            self.assertIn("_CONTAINS_OP", get_opnames(
                _opcode.get_executor(function.__code__, 0)))
        for sequence in ([], (), [1, 2, 3], (1, 2, 3), [2**100, 3],
                         [True, False], [1.0, None, 3]):
            for key in (-5, 0, 1, 3, 8, 2**100, True):
                self.assertEqual(contains(sequence, key), key in sequence)
                self.assertEqual(excludes(sequence, key), key not in sequence)

        calls = []
        class Equal:
            def __eq__(self, other):
                calls.append(other)
                sequence.clear()
                return False
        sequence = [1, 2, Equal(), 5]
        self.assertFalse(contains(sequence, 5))
        self.assertEqual(calls, [5])
        self.assertEqual(sequence, [])

        class Broken:
            def __eq__(self, other):
                raise ValueError("comparison")
        with self.assertRaisesRegex(ValueError, "comparison"):
            contains([1, 2, Broken()], 5)

        class CustomList(list):
            def __contains__(self, key):
                calls.append(key)
                return True
        self.assertTrue(contains(CustomList(), 42))
        self.assertEqual(calls, [5, 42])

    @disable_gc()
    def test_borrowed_subscript_container_cleanup(self):
        def read(sequence, index):
            return sequence[index]

        token = object()
        sequence = [token]
        self.assertEqual(list(itertools.starmap(read, itertools.repeat(
            (sequence, 0), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(_opcode.get_executor(read.__code__, 0))
        self.assertIn("_POP_TOP_NOP" if Py_GIL_DISABLED else
                      "_BINARY_OP_SUBSCR_BORROWED_0", names)
        self.assertNotIn("_POP_TOP", names)
        with self.assertRaises(IndexError):
            read(sequence, 3)
        self.assertIs(read(sequence, -1), token)

        def read_tuple(sequence, index):
            return sequence[index]
        sequence_tuple = (token,)
        self.assertEqual(list(itertools.starmap(read_tuple, itertools.repeat(
            (sequence_tuple, 0), TIER2_RESUME_THRESHOLD))),
            [token] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED:
            self.assertIn("_BINARY_OP_SUBSCR_BORROWED_1", get_opnames(
                _opcode.get_executor(read_tuple.__code__, 0)))
        self.assertIs(read_tuple(sequence_tuple, -1), token)
        with self.assertRaises(IndexError):
            read_tuple(sequence_tuple, 1)

        calls = []
        class Other:
            def __del__(self):
                calls.append("closed")
        def factory():
            return [token, Other()]
        def read_temporary(factory):
            return factory()[0]
        self.assertEqual(list(map(read_temporary, itertools.repeat(
            factory, TIER2_RESUME_THRESHOLD))), [token] * TIER2_RESUME_THRESHOLD)
        self.assertEqual(calls, ["closed"] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_POP_TOP", get_opnames(
            _opcode.get_executor(read_temporary.__code__, 0)))

    @disable_gc()
    def test_integer_attribute_comparisons(self):
        class Left:
            __slots__ = ("value",)
        class Right:
            pass

        left, right = Left(), Right()
        left.value, right.value = 3, 5
        for expression, arguments, expected in (
            ("left.value < right.value", (left, right), True),
            ("left.value == right", (left, 3), True),
            ("left > right.value", (10, right), True),
            ("left.value > 0", (left, right), True),
            ("-1 < right.value", (left, right), True),
        ):
            with self.subTest(expression=expression):
                namespace = {}
                exec(f"def compare(left, right):\n    return {expression}\n", namespace)
                compare = namespace["compare"]
                self.assertEqual(list(itertools.starmap(compare, itertools.repeat(
                    arguments, TIER2_RESUME_THRESHOLD))),
                    [expected] * TIER2_RESUME_THRESHOLD)
                if not Py_GIL_DISABLED and struct.calcsize("P") == 8:
                    self.assertTrue(any(name.startswith("_COMPARE_INT_INPUTS_")
                        for name in get_opnames(_opcode.get_executor(compare.__code__, 0))))

        def compare_later_local(a, b, c, d, e, f, g, h, obj):
            return obj.value == 3

        arguments = (None,) * 8 + (left,)
        self.assertEqual(list(itertools.starmap(compare_later_local,
            itertools.repeat(arguments, TIER2_RESUME_THRESHOLD))),
            [True] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED and struct.calcsize("P") == 8:
            self.assertTrue(any(name.startswith("_COMPARE_INT_INPUTS_")
                for name in get_opnames(_opcode.get_executor(compare_later_local.__code__, 0))))
        for value in (0, 3, -3, 2**100, True, 3.0):
            left.value = value
            self.assertEqual(compare_later_local(*arguments), value == 3)
        left.value = 3

        def compare(left, right):
            return left.value < right.value

        self.assertEqual(list(itertools.starmap(compare, itertools.repeat(
            (left, right), TIER2_RESUME_THRESHOLD))),
            [True] * TIER2_RESUME_THRESHOLD)
        for a, b in ((-5, 5), (5, -5), (0, 0), (2**100, 2**101),
                     (2**100, 0), (3.5, 4.5)):
            left.value, right.value = a, b
            self.assertEqual(compare(left, right), a < b)
        right.__dict__ = {"value": 10}
        self.assertTrue(compare(left, right))
        del left.value
        with self.assertRaises(AttributeError):
            compare(left, right)

        calls = []
        class Value:
            def __lt__(self, other):
                calls.append(other)
                return "custom result"
        left.value = Value()
        self.assertEqual(compare(left, right), "custom result")
        self.assertEqual(calls, [10])

    @disable_gc()
    def test_call_checks_use_guarded_function_metadata(self):
        def callee(left, right):
            return left + right

        def caller(function, value):
            return function(value, 2)

        args = itertools.repeat((callee, 40), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, args)),
                         [42] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(_opcode.get_executor(caller.__code__, 0))
        self.assertIn("_CHECK_FUNCTION_VERSION", names)
        self.assertIn("_CHECK_STACK_SPACE_OPERAND", names)
        self.assertNotIn("_CHECK_STACK_SPACE", names)
        self.assertNotIn("_CHECK_FUNCTION_EXACT_ARGS", names)
        self.assertNotIn("_CHECK_PEP_523", names)

        def replacement(left, right, extra):
            return left + right + extra

        callee.__code__ = replacement.__code__
        with self.assertRaises(TypeError):
            caller(callee, 40)
        callee.__defaults__ = (3,)
        self.assertEqual(caller(callee, 40), 45)

        # A larger replacement frame must use its own stack-space checks.
        namespace = {}
        exec("def larger(left, right):\n" +
             "".join(f"    local_{i} = left\n" for i in range(100)) +
             "    return local_99 + right\n", namespace)
        callee.__code__ = namespace["larger"].__code__
        self.assertEqual(caller(callee, 40), 42)

    @disable_gc()
    def test_borrowed_attribute_receiver_cleanup(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Holder:
            def __init__(self, value):
                self.value = value

        def read(obj):
            return obj.value

        token = object()
        holder = Holder(token)
        self.assertEqual(list(map(read, itertools.repeat(
            holder, TIER2_RESUME_THRESHOLD))), [token] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(_opcode.get_executor(read.__code__, 0))
        self.assertIn("_LOAD_ATTR_BORROWED_OWNER", names)
        self.assertNotIn("_POP_TOP", names)

        class Slot:
            __slots__ = ("value",)
        slot = Slot()
        slot.value = token
        def read_slot(obj):
            return obj.value
        self.assertEqual(list(map(read_slot, itertools.repeat(
            slot, TIER2_RESUME_THRESHOLD))), [token] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_LOAD_ATTR_BORROWED_OWNER", get_opnames(
            _opcode.get_executor(read_slot.__code__, 0)))
        class Value:
            pass

        for receiver, getter in ((holder, read), (slot, read_slot)):
            receiver.value = Value()
            reference = weakref.ref(receiver.value)
            result = getter(receiver)
            self.assertIs(result, reference())
            del receiver.value
            with self.assertRaises(AttributeError):
                getter(receiver)
            gc.collect()
            self.assertIs(result, reference())
            del result
            gc.collect()
            self.assertIsNone(reference())
            receiver.value = token
            self.assertIs(getter(receiver), token)

        holder.__dict__.clear()
        with self.assertRaises(AttributeError):
            read(holder)
        holder.value = token
        self.assertIs(read(holder), token)
        Slot.value = property(lambda self: "replacement")
        self.assertEqual(read_slot(slot), "replacement")

        calls = []
        class Temporary:
            def __init__(self):
                self.value = token
            def __del__(self):
                calls.append("closed")

        def read_temporary(factory):
            return factory().value

        def factory():
            return Temporary()

        self.assertEqual(list(map(read_temporary, itertools.repeat(
            factory, TIER2_RESUME_THRESHOLD))), [token] * TIER2_RESUME_THRESHOLD)
        self.assertEqual(calls, ["closed"] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_POP_TOP", get_opnames(
            _opcode.get_executor(read_temporary.__code__, 0)))

    @disable_gc()
    def test_float_attribute_products_mixed_integers(self):
        class Vector:
            pass

        def dot(left, right):
            return left.x * right.x + left.y * right.y + left.z * right.z

        left, right = Vector(), Vector()
        left.x, left.y, left.z = 2.0, 5, 4.0
        right.x, right.y, right.z = 3, 7.0, 2
        self.assertEqual(list(itertools.starmap(dot, itertools.repeat(
            (left, right), TIER2_RESUME_THRESHOLD))),
            [49.0] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED and struct.calcsize("P") == 8:
            self.assertIn("_FLOAT_ATTRIBUTE_SUM_PRODUCTS_1", get_opnames(
                _opcode.get_executor(dot.__code__, 0)))
        for values in ((2, 3, 4, 5, 6, 7),
                       (2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
                       (2**70, 3.0, 4.0, 5, 6.0, 7),
                       (2.0, 3, 4.0, 5, 6.0, 7),
                       (2, 3.0, 4, 5.0, 6, 7.0)):
            left.x, right.x, left.y, right.y, left.z, right.z = values
            expected = values[0] * values[1] + values[2] * values[3] + values[4] * values[5]
            result = dot(left, right)
            self.assertEqual(result, expected)
            self.assertIs(type(result), type(expected))
        left.x = 2**2000
        with self.assertRaises(OverflowError):
            dot(left, right)

    @disable_gc()
    def test_float_attribute_products(self):
        for slots in (False, True):
            for terms in (2, 3):
                with self.subTest(slots=slots, terms=terms):
                    namespace = {"__slots__": ("x", "y", "z")} if slots else {}
                    Vector = type("Vector", (), namespace)
                    left, right = Vector(), Vector()
                    left.x, left.y, left.z = 2.0, 3.0, 4.0
                    right.x, right.y, right.z = 5.0, 6.0, 7.0
                    expr = "left.x * right.x + left.y * right.y"
                    if terms == 3:
                        expr += " + left.z * right.z"
                    namespace = {}
                    exec(f"def dot(left, right):\n    return {expr}\n", namespace)
                    dot = namespace["dot"]
                    expected = 28.0 if terms == 2 else 56.0
                    self.assertEqual(list(itertools.starmap(dot, itertools.repeat(
                        (left, right), TIER2_RESUME_THRESHOLD))),
                        [expected] * TIER2_RESUME_THRESHOLD)
                    if not Py_GIL_DISABLED and struct.calcsize("P") == 8:
                        self.assertIn(f"_FLOAT_ATTRIBUTE_SUM_PRODUCTS_{terms - 2}",
                                      get_opnames(_opcode.get_executor(dot.__code__, 0)))

                    # Multiplication rounds before addition; contraction to
                    # FMA would produce a different answer for these inputs.
                    left.x, right.x = 1.0 + 2**-27, 1.0 - 2**-27
                    left.y, right.y = -1.0, 1.0
                    left.z, right.z = 0.0, 1.0
                    self.assertEqual(dot(left, right).hex(), "0x0.0p+0")
                    if terms == 3:
                        left.x, right.x = 1e16, 1.0
                        left.y, right.y = -1e16, 1.0
                        left.z, right.z = 1.0, 1.0
                        self.assertEqual(dot(left, right), 1.0)
                    left.x, right.x = float("inf"), 0.0
                    result = dot(left, right)
                    self.assertNotEqual(result, result)
                    left.x, right.x = -0.0, 1.0
                    left.y, right.y = -0.0, 1.0
                    left.z, right.z = -0.0, 1.0
                    self.assertEqual(dot(left, right).hex(), "-0x0.0p+0")

                    calls = []
                    class Number(float):
                        def __mul__(self, other):
                            calls.append(other)
                            left.y = 5.0
                            return 7.0
                    left.x = Number(2.0)
                    self.assertEqual(dot(left, right), 12.0)
                    self.assertEqual(calls, [1.0])
                    del left.y
                    left.x = 2.0
                    with self.assertRaises(AttributeError):
                        dot(left, right)
                    if not slots:
                        left.__dict__ = dict(x=2.0, y=3.0, z=4.0)
                        self.assertEqual(dot(left, right), 5.0 if terms == 2 else 9.0)

    @disable_gc()
    def test_enumerate_integer_tuple_scan(self):
        def find(rows, key):
            index, item = -1, None
            for index, item in enumerate(rows):
                if item[0] >= key:
                    return index, item
            return index, item

        rows = [(i, object()) for i in range(400)]
        self.assertEqual(list(itertools.starmap(find, itertools.repeat(
            (rows, 90), TIER2_RESUME_THRESHOLD))),
            [(90, rows[90])] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(find.__code__, 0)
        self.assertIn("_ENUM_LIST_INT_SCAN", get_opnames(executor))
        for key in (-1, 0, 1, 63, 64, 65, 254, 255, 256, 399, 400, 10**50):
            expected = min(max(key, 0), 399)
            self.assertEqual(find(rows, key), (expected, rows[expected]))
        self.assertEqual(find([], 10), (-1, None))
        self.assertEqual(find(rows[:3], 10), (2, rows[2]))
        self.assertEqual(find(tuple(rows), 80), (80, rows[80]))
        with self.assertRaises(IndexError):
            find(rows[:80] + [()], 100)
        with self.assertRaises(TypeError):
            find(rows[:80] + [(None,)], 100)

        calls = []
        class Key:
            def __ge__(self, other):
                calls.append(other)
                return True
        item = (Key(),)
        self.assertEqual(find(rows[:80] + [item], 100), (80, item))
        self.assertEqual(calls, [100])

        # A callback may replace elements already visited by the loop. It
        # must run at the original comparison, before any later iteration.
        class MutatingKey:
            def __ge__(self, other):
                mutable.clear()
                return False
        item = (MutatingKey(),)
        mutable = rows[:80] + [item] + rows[81:]
        self.assertEqual(find(mutable, 100), (80, item))
        self.assertEqual(mutable, [])

    @disable_gc()
    def test_enumerate_scan_index_and_local_lifetimes(self):
        def find(rows, key, start, index, item):
            for index, item in enumerate(rows, start):
                if item[0] >= key:
                    return index, item
            return index, item

        rows = [(i,) for i in range(100)]
        self.assertEqual(list(itertools.starmap(find, itertools.repeat(
            (rows, 90, 0, None, None), TIER2_RESUME_THRESHOLD))),
            [(90, rows[90])] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_ENUM_LIST_INT_SCAN", get_opnames(
            _opcode.get_executor(find.__code__, 0)))
        for start in (-10, -5, 0, 200, 255, 256, 10**50):
            self.assertEqual(find(rows, 90, start, None, None),
                             (start + 90, rows[90]))
            self.assertEqual(find(rows, 200, start, None, None),
                             (start + 99, rows[99]))
        calls = []
        class Previous:
            def __del__(self):
                calls.append("closed")
        self.assertEqual(find(rows, 90, 0, Previous(), Previous()),
                         (90, rows[90]))
        self.assertEqual(calls, ["closed", "closed"])

    @disable_gc()
    def test_enumerate_scan_comparison_direction(self):
        for compare in ("<", "<=", "==", "!=", ">", ">="):
            with self.subTest(compare=compare):
                namespace = {}
                exec(f"""
def find(rows, key):
    for index, item in enumerate(rows):
        if item[1] {compare} key:
            return index
    return -1
""", namespace)
                find = namespace["find"]
                rows = [(None, i) for i in range(80)]
                expected = next((i for i in range(80)
                                 if eval(f"i {compare} 40")), -1)
                self.assertEqual(list(itertools.starmap(find, itertools.repeat(
                    (rows, 40), TIER2_RESUME_THRESHOLD))),
                    [expected] * TIER2_RESUME_THRESHOLD)
                # Some directions return on the first iteration: still
                # exercise long runs after their entry has warmed up.
                for key in (-100, 0, 40, 100):
                    expected = next((i for i in range(80)
                                     if eval(f"i {compare} {key}")), -1)
                    self.assertEqual(find(rows, key), expected)

    @disable_gc()
    def test_cached_values_across_expression_join(self):
        def select(flag, left, right):
            return (10, left if flag else right, 20)

        args = itertools.cycle(((True, 3, 4.5), (False, 3, 4.5)))
        result = list(itertools.starmap(select, itertools.islice(
            args, TIER2_RESUME_THRESHOLD)))
        self.assertEqual(result, [(10, 3, 20), (10, 4.5, 20)] *
                         (TIER2_RESUME_THRESHOLD // 2))
        executor = _opcode.get_executor(select.__code__, 0)
        self.assertNotIn("_METHOD_LABEL", get_opnames(executor))
        token = object()
        self.assertEqual(select(True, token, None), (10, token, 20))

    @disable_gc()
    def test_cached_values_across_nested_loop_edges(self):
        def walk(rows):
            total = 0
            for row in rows:
                for value in row:
                    if value < 0:
                        continue
                    if value == 0:
                        break
                    total += value
            return total

        rows = [[1, 2, 0, 20], [-1, 3], [4]]
        self.assertEqual(list(map(walk, itertools.repeat(
            rows, TIER2_RESUME_THRESHOLD))), [10] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(walk.__code__, 0)
        self.assertIn("_METHOD_ITER_JUMP_LIST", get_opnames(executor))
        self.assertNotIn("_METHOD_LABEL", get_opnames(executor))
        self.assertEqual(walk([]), 0)
        self.assertEqual(walk([[], [2], []]), 2)
        self.assertEqual(walk([(1, 2), [3]]), 6)
        with self.assertRaises(TypeError):
            walk([[1], [None]])

    @disable_gc()
    def test_attribute_layout_across_scalar_stores_and_branch(self):
        class Value:
            def __init__(self):
                self.x = 2
                self.y = 3
        def read(value, branch):
            first = value.x
            marker = 1
            if branch:
                marker = 2
            return first + value.y + marker

        value = Value()
        args = itertools.cycle(((value, True), (value, False)))
        results = list(itertools.starmap(read, itertools.islice(
            args, TIER2_RESUME_THRESHOLD)))
        self.assertEqual(results, [7, 6] * (TIER2_RESUME_THRESHOLD // 2))
        executor = _opcode.get_executor(read.__code__, 0)
        self.assertEqual(get_opnames(executor).count("_GUARD_TYPE_VERSION"), 1)

    @disable_gc()
    def test_attribute_layout_cleared_by_store_finalizer(self):
        class Before:
            def __init__(self):
                self.x = 1
                self.y = 2
        class After:
            x = 1
            @property
            def y(self):
                return 10
        def read(value, previous):
            first = value.x
            previous = None
            return first + value.y

        value = Before()
        args = itertools.repeat((value, 0), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(read, args)),
                         [3] * TIER2_RESUME_THRESHOLD)
        _opcode.get_executor(read.__code__, 0)
        class Switch:
            def __del__(self):
                value.__class__ = After
        self.assertEqual(read(value, Switch()), 11)

    def test_list_subscript_length_comparison(self):
        def compare(items, index):
            result = False
            for _ in range(TIER2_THRESHOLD):
                result = len(items[index]) == 1
            return result

        self.assertTrue(compare([[1], []], 0))
        self.assertTrue(compare([[1], []], 0))
        names = [name for executor in get_all_executors(compare)
                 for name in get_opnames(executor)]
        if struct.calcsize("P") == 8:
            self.assertIn("_LEN_SUBSCR_LIST", names)
        self.assertFalse(compare([[1], []], -1))
        self.assertTrue(compare([[1], []], -2))
        with self.assertRaises(IndexError):
            compare([], 0)
        with self.assertRaises(TypeError):
            compare([None], 0)
        calls = []
        class Sized:
            def __len__(self):
                calls.append("len")
                return 1
        self.assertTrue(compare([Sized()], 0))
        self.assertEqual(calls, ["len"] * TIER2_THRESHOLD)
        class Items:
            def __getitem__(self, index):
                calls.append(index)
                return [1]
        calls.clear()
        self.assertTrue(compare(Items(), 0))
        self.assertEqual(calls, [0] * TIER2_THRESHOLD)

    def test_adjacent_list_pair_comparison(self):
        def compare(items, index, pair):
            result = False
            for _ in range(TIER2_THRESHOLD):
                result = (items[index], items[index + 1]) == pair
            return result

        self.assertTrue(compare([b"a", b"b"], 0, (b"a", b"b")))
        self.assertTrue(compare([b"a", b"b"], 0, (b"a", b"b")))
        names = [name for executor in get_all_executors(compare)
                 for name in get_opnames(executor)]
        self.assertIn("_COMPARE_LIST_PAIR_0", names)
        self.assertTrue(compare([b"a", b"b"], -2, (b"a", b"b")))
        self.assertTrue(compare([b"a", b"b"], -1, (b"b", b"a")))
        self.assertFalse(compare([b"a", b"b"], 0, (b"a", b"c")))
        # Check both subscriptions even when the first comparison is false.
        with self.assertRaises(IndexError):
            compare([b"a"], 0, (b"different", b"b"))
        nan = float("nan")
        self.assertTrue(compare([nan, 1.0], 0, (nan, 1.0)))
        calls = []
        class Element:
            def __eq__(self, other):
                calls.append(other)
                return True
        value = Element()
        self.assertTrue(compare([value, 1], 0, (None, 1)))
        self.assertEqual(len(calls), TIER2_THRESHOLD)
        calls.clear()
        self.assertFalse(compare([b"a", value], 0, (b"b", None)))
        self.assertEqual(calls, [])
        self.assertTrue(compare([b"a", value], 0, (b"a", None)))
        self.assertEqual(calls, [None] * TIER2_THRESHOLD)
        class Items:
            def __getitem__(self, index):
                calls.append(index)
                return index
        calls.clear()
        self.assertTrue(compare(Items(), 0, (0, 1)))
        self.assertEqual(calls, [0, 1] * TIER2_THRESHOLD)

    def test_bounded_integer_expression(self):
        def expression(a, b):
            return ((a + b) * (a + b + 1) // 2 + a + 1)

        arguments = itertools.repeat((17, 29), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(expression, arguments)),
                         [1099] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(expression.__code__, 0)
        if struct.calcsize("P") == 8:
            self.assertIn("_INT_REGION_START_0", get_opnames(executor))
        import operator as op
        for a, b in [(0, 0), (-7, 3), (7, -23), (2**27, 91),
                     (2**28, 0), (2**100, 2**80), (True, False), (1.5, 3.0)]:
            total = op.add(a, b)
            expected = op.add(op.add(op.floordiv(
                op.mul(total, op.add(total, 1)), 2), a), 1)
            self.assertEqual(expression(a, b), expected)

    def test_bounded_integer_float_division(self):
        def expression(a, b):
            return 1.0 / ((a + b) * (a + b + 1) // 2 + a + 1)

        arguments = itertools.repeat((17, 29), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(expression, arguments)),
                         [1.0 / 1099] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(expression.__code__, 0)
        if struct.calcsize("P") == 8:
            self.assertIn("_INT_REGION_DIVIDE", get_opnames(executor))
        import operator as op
        for a, b in [(0, 0), (-7, 3), (7, -23), (2**27, 91),
                     (2**28, 0), (2**100, 2**80), (True, False), (1.5, 3.0)]:
            total = op.add(a, b)
            denominator = op.add(op.add(op.floordiv(
                op.mul(total, op.add(total, 1)), 2), a), 1)
            if denominator == 0:
                with self.assertRaises(ZeroDivisionError):
                    expression(a, b)
            else:
                self.assertEqual(expression(a, b), op.truediv(1.0, denominator))
        with self.assertRaises(ZeroDivisionError):
            expression(-1, 1)

    def test_bounded_integer_expression_in_loop_trace(self):
        def loop(a, b):
            total = 0
            for _ in range(TIER2_THRESHOLD):
                total += ((a + b) * (a + b + 1) // 2 + a + 1)
            return total

        self.assertEqual(loop(17, 29), 1099 * TIER2_THRESHOLD)
        self.assertEqual(loop(17, 29), 1099 * TIER2_THRESHOLD)
        if struct.calcsize("P") == 8:
            opnames = [name for ex in get_all_executors(loop)
                       for name in get_opnames(ex)]
            self.assertIn("_INT_REGION_START_0", opnames)
        self.assertEqual(loop(-7, 3), 0)
        self.assertEqual(loop(2**100, 0),
                         ((2**100 * (2**100 + 1) // 2) + 2**100 + 1) * TIER2_THRESHOLD)

    def test_length_consumer_and_python_fallback(self):
        def compare(obj, index):
            return index < len(obj) - 1

        args = itertools.repeat(([1, 2, 3], 1), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(compare, args)),
                         [True] * TIER2_RESUME_THRESHOLD)
        if struct.calcsize("P") == 8:
            opname = ("_CALL_LEN_LEFT_COMPARE" if Py_GIL_DISABLED else
                      "_CALL_LEN_LEFT_COMPARE_CLEAN")
            self.assertIn(opname, get_opnames(
                _opcode.get_executor(compare.__code__, 0)))
        for obj in ([], (), b"abc", "abc", {1: 2}):
            for index in (-2**100, -1, 0, 1, 2**100):
                self.assertEqual(compare(obj, index), index < len(obj) - 1)

        calls = []
        class Sized:
            def __len__(self):
                calls.append("len")
                return 4
        self.assertTrue(compare(Sized(), 2))
        self.assertEqual(calls, ["len"])

    @disable_gc()
    def test_length_comparison_cleanup_fallback(self):
        def compare(factory, index):
            result = index < len(factory()) - 1
            events.append("compared")
            return result

        events = []
        class Element:
            def __del__(self):
                events.append("finalized")

        def factory():
            return [Element(), 2, 3]
        self.assertEqual(list(itertools.starmap(compare, itertools.repeat(
            (factory, 1), TIER2_RESUME_THRESHOLD))),
            [True] * TIER2_RESUME_THRESHOLD)
        executor = get_first_executor(compare)
        self.assertIsNotNone(executor)
        if struct.calcsize("P") == 8 and not Py_GIL_DISABLED:
            self.assertIn("_CALL_LEN_LEFT_COMPARE_CLEAN", get_opnames(executor))

        events.clear()
        self.assertTrue(compare(factory, 1))
        self.assertEqual(events, ["finalized", "compared"])
        events.clear()
        with self.assertRaises(TypeError):
            compare(factory, object())
        self.assertEqual(events, ["finalized"])

        class Sized:
            def __len__(self):
                events.append("len")
                raise RuntimeError("length")
        with self.assertRaisesRegex(RuntimeError, "length"):
            compare(Sized, 1)
        self.assertEqual(events, ["finalized", "len"])

    def test_tuple_pair_comparison_preserves_nan_identity(self):
        def compare(first, second, pair):
            return (first, second) == pair

        args = itertools.repeat((b"a", b"b", (b"a", b"b")),
                                TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(compare, args)),
                         [True] * TIER2_RESUME_THRESHOLD)
        if struct.calcsize("P") == 8:
            self.assertIn("_COMPARE_TUPLE_PAIR_0", get_opnames(
                _opcode.get_executor(compare.__code__, 0)))
        nan = float("nan")
        self.assertTrue(compare(nan, 1.0, (nan, 1.0)))
        self.assertFalse(compare(nan, 1.0, (float("nan"), 1.0)))
        self.assertTrue(compare(2**100, "abc", (2**100, "abc")))
        self.assertFalse(compare(b"a", b"b", (b"a", b"c")))
        self.assertTrue(compare(b"", b"\x00", (b"", b"\x00")))
        self.assertFalse(compare(b"\x00ab", b"x", (b"\x00ac", b"x")))
        self.assertFalse(compare(b"a", b"b", (b"a",)))
        calls = []
        class Item:
            def __eq__(self, other):
                calls.append(other)
                return True
        other = object()
        self.assertTrue(compare(Item(), 2, (other, 2)))
        self.assertEqual(calls, [other])
        calls.clear()
        self.assertFalse(compare(b"a", Item(), (b"b", other)))
        self.assertEqual(calls, [])
        self.assertTrue(compare(b"a", Item(), (b"a", other)))
        self.assertEqual(calls, [other])

    def test_reuses_unique_float_temporaries(self):
        def expression(a, b, c, d):
            return a * b + c * d

        args = itertools.repeat((2.0, 3.0, 5.0, 7.0), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(expression, args)),
                         [41.0] * TIER2_RESUME_THRESHOLD)
        opnames = get_opnames(_opcode.get_executor(expression.__code__, 0))
        self.assertIn("_BINARY_OP_ADD_FLOAT_INPLACE", opnames)
        self.assertEqual(expression(-2.0, 3.5, 5.5, -7.0), -45.5)

    def test_float_temporaries_across_borrowed_attribute_reads(self):
        class Point:
            def __init__(self, x, y):
                self.x, self.y = x, y

        def expression(a, b):
            # Keep this outside sum-of-products fusion so it still exercises
            # ownership tracking across individual attribute reads.
            return a.x * b.x + a.y + b.y

        a, b = Point(2.0, 5.0), Point(3.0, 7.0)
        args = itertools.repeat((a, b), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(expression, args)),
                         [18.0] * TIER2_RESUME_THRESHOLD)
        opnames = get_opnames(_opcode.get_executor(expression.__code__, 0))
        self.assertIn("_BINARY_OP_ADD_FLOAT_INPLACE", opnames)
        self.assertEqual((a.x, a.y, b.x, b.y), (2.0, 5.0, 3.0, 7.0))
        self.assertEqual(opnames.count("_GUARD_TYPE_VERSION"), 2)

    def test_attribute_layout_fact_cleared_at_callback(self):
        class Changed:
            @property
            def y(self):
                return 100

        class Point:
            def __init__(self):
                self.x, self.y = 2, 3
                self.change = False
                self.target = Changed

        def callback(obj):
            if obj.change:
                obj.__class__ = obj.target
            return 0

        def expression(obj, function):
            return obj.x + function(obj) + obj.y

        obj = Point()
        args = itertools.repeat((obj, callback), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(expression, args)),
                         [5] * TIER2_RESUME_THRESHOLD)
        self.assertIsNotNone(_opcode.get_executor(expression.__code__, 0))
        obj.change = True
        self.assertEqual(expression(obj, callback), 102)

    def test_float_temporary_alias_prevents_reuse(self):
        def expression(a, b):
            return (value := a * b) + value

        args = itertools.repeat((2.0, 3.0), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(expression, args)),
                         [12.0] * TIER2_RESUME_THRESHOLD)
        opnames = get_opnames(_opcode.get_executor(expression.__code__, 0))
        self.assertNotIn("_BINARY_OP_ADD_FLOAT_INPLACE", opnames)
        self.assertNotIn("_BINARY_OP_ADD_FLOAT_INPLACE_RIGHT", opnames)
        self.assertEqual(expression(3.0, 5.0), 30.0)

    def test_method_global_constant_mapping_and_rebinding(self):
        namespace = {"VALUE": 10, "noise": 0}
        exec("def function(unused):\n    return VALUE + 2\n", namespace)
        function = namespace["function"]
        self.assertEqual(list(map(function, [None] * TIER2_RESUME_THRESHOLD)),
                         [12] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(function.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_GUARD_GLOBALS_VERSION_AND_IDENTITY", opnames)
        self.assertNotIn("_LOAD_GLOBAL_MODULE", opnames)
        copied = namespace.copy()
        copied["VALUE"] = 90
        other = types.FunctionType(function.__code__, copied)
        self.assertEqual(other(None), 92)
        self.assertEqual(function(None), 12)
        namespace["VALUE"] = 30
        self.assertFalse(executor.is_valid())
        self.assertEqual(function(None), 32)

    def test_method_builtin_constant_checks_builtins_identity(self):
        import builtins
        namespace = {"__builtins__": builtins.__dict__}
        exec("def function(unused):\n    return Ellipsis\n", namespace)
        function = namespace["function"]
        self.assertEqual(list(map(function, [None] * TIER2_RESUME_THRESHOLD)),
                         [Ellipsis] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(function.__code__, 0)
        self.assertIn("_GUARD_BUILTINS_IDENTITY", get_opnames(executor))
        custom = builtins.__dict__.copy()
        custom["Ellipsis"] = 42
        namespace["__builtins__"] = custom
        other = types.FunctionType(function.__code__, namespace)
        namespace["__builtins__"] = builtins.__dict__
        self.assertEqual(other(None), 42)
        self.assertIs(function(None), Ellipsis)

    def test_method_reuses_mapping_identity_guards(self):
        import builtins
        namespace = {"__builtins__": builtins.__dict__}
        exec("def function(values):\n"
             "    first = list\n"
             "    len(values)\n"
             "    return list\n",
             namespace)
        function = namespace["function"]
        values = [1, 2]
        self.assertEqual(list(map(function, itertools.repeat(
            values, TIER2_RESUME_THRESHOLD))),
            [list] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(function.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_METHOD_EXIT", opnames)
        self.assertEqual(opnames.count("_GUARD_BUILTINS_IDENTITY"), 1)
        self.assertEqual(
            opnames.count("_GUARD_GLOBALS_VERSION_AND_IDENTITY"), 1)

        custom = dict(builtins.__dict__, list=42, len=lambda obj: 10)
        namespace["__builtins__"] = custom
        other = types.FunctionType(function.__code__, namespace)
        namespace["__builtins__"] = builtins.__dict__
        self.assertEqual(other(values), 42)
        self.assertIs(function(values), list)

        class Rebind:
            def __len__(obj):
                self.assertIs(sys._getframe(1).f_locals["first"], list)
                namespace["list"] = 42
                return 2

        self.assertTrue(executor.is_valid())
        self.assertEqual(function(Rebind()), 42)
        self.assertFalse(executor.is_valid())

    def test_compiles_both_sides_of_branch(self):
        def choose(flag):
            if flag:
                value = 10
            else:
                value = 20
            return value

        # Call from C so the function's own RESUME counter reaches the method
        # compilation threshold without a Python caller trace inlining it.
        self.assertEqual(
            list(map(choose, [True] * TIER2_RESUME_THRESHOLD)),
            [10] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(choose.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", opnames)
        # Adjacent single-predecessor edges need no jump or spill.
        self.assertIn("_METHOD_EXIT", opnames)
        self.assertGreater(count_return_ops(opnames), 0)

        # The false arm was not executed while warming, but it is part of the
        # compiled control-flow graph.
        self.assertEqual([choose(True), choose(False)], [10, 20])

    def test_compiles_range_loop(self):
        def range_sum(n):
            total = 0
            for value in range(n):
                total += value
            return total

        expected = sum(range(5))
        self.assertEqual(
            list(map(range_sum, [5] * TIER2_RESUME_THRESHOLD)),
            [expected] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(range_sum.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_METHOD_ITER_JUMP_RANGE", opnames)
        self.assertIn("_METHOD_JUMP", opnames)
        self.assertIn("_METHOD_EXIT", opnames)
        self.assertGreater(count_return_ops(opnames), 0)
        self.assertNotIn("_GUARD_TOS_INT", opnames)
        self.assertNotIn("_GUARD_NOS_INT", opnames)
        self.assertIn("_GUARD_NOS_OVERFLOWED", opnames)
        self.assertEqual(
            [range_sum(n) for n in range(12)],
            [sum(range(n)) for n in range(12)],
        )

    def test_merges_same_type_across_diamond(self):
        def diamond(flag):
            if flag:
                value = 10
            else:
                value = 20
            value += 1
            value *= 2
            value -= 3
            value *= 4
            return value

        self.assertEqual(
            list(map(diamond, [True] * TIER2_RESUME_THRESHOLD)),
            [76] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(diamond.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", opnames)
        self.assertNotIn("_GUARD_NOS_INT", opnames)
        self.assertIn("_GUARD_NOS_OVERFLOWED", opnames)
        self.assertEqual(diamond(False), 156)

    def test_merges_float_type_across_diamond(self):
        def diamond(flag):
            if flag:
                value = 1.25
            else:
                value = 2.5
            value += 0.5
            value *= 2.0
            return value

        self.assertEqual(
            list(map(diamond, [True] * TIER2_RESUME_THRESHOLD)),
            [3.5] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(diamond.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", opnames)
        self.assertNotIn("_GUARD_TOS_FLOAT", opnames)
        self.assertNotIn("_GUARD_NOS_FLOAT", opnames)
        self.assertEqual(diamond(False), 6.0)

    def test_mixed_type_diamond_keeps_guards(self):
        def diamond(flag):
            if flag:
                value = 10
            else:
                value = "a"
            value += value
            value += value
            value += value
            value += value
            return value

        self.assertEqual(
            list(map(diamond, [True] * TIER2_RESUME_THRESHOLD)),
            [160] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(diamond.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_GUARD_TOS_INT", opnames)
        # Both operands alias the same local. One exact-int guard is enough,
        # but a mixed-type join must not eliminate that guard as well.
        self.assertEqual(diamond(False), "a" * 16)

    def test_nested_loop_fixpoint(self):
        def nested_sum(n):
            total = 0
            for outer in range(n):
                for inner in range(outer):
                    total += inner
            return total

        expected = sum(sum(range(i)) for i in range(6))
        self.assertEqual(
            list(map(nested_sum, [6] * TIER2_RESUME_THRESHOLD)),
            [expected] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(nested_sum.__code__, 0)
        opnames = get_opnames(executor)
        self.assertEqual(opnames.count("_METHOD_ITER_JUMP_RANGE"), 2)
        self.assertGreaterEqual(opnames.count("_METHOD_JUMP"), 2)
        self.assertEqual(
            [nested_sum(n) for n in range(9)],
            [sum(sum(range(i)) for i in range(n)) for n in range(9)],
        )

    def test_straight_line_return_to_c_and_python(self):
        def leaf(value):
            return value + 1

        self.assertEqual(
            list(map(leaf, [4] * TIER2_RESUME_THRESHOLD)),
            [5] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(leaf.__code__, 0)
        opnames = get_opnames(executor)
        self.assertGreater(count_return_ops(opnames), 0)
        self.assertIn("_METHOD_EXIT", opnames)
        self.assertNotIn("_METHOD_DEOPT", opnames)

        def python_caller(value):
            return leaf(value) * 2

        self.assertEqual(python_caller(8), 18)

    def test_inlines_exact_python_call_and_invalidates(self):
        def callee(value):
            return value * 2

        def replacement(value):
            return value * 3

        def caller(function, value):
            return function(value) + 1

        arguments = itertools.repeat(
            (callee, 7), TIER2_RESUME_THRESHOLD)
        self.assertEqual(
            list(itertools.starmap(caller, arguments)),
            [15] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertEqual(opnames.count("_PUSH_FRAME"), 1)
        self.assertGreaterEqual(count_return_ops(opnames), 2)
        self.assertIn("_METHOD_EXIT", opnames)
        self.assertNotIn("_METHOD_DEOPT", opnames)
        self.assertEqual(caller(callee, 8), 17)
        with self.assertRaises(TypeError):
            caller(callee, "x")

        callee.__code__ = replacement.__code__
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(callee, 8), 25)

    def test_inlines_python_call_with_defaults(self):
        def callee(value, increment=3):
            return value + increment

        def caller(function, value):
            return function(value) * 2

        arguments = itertools.repeat((callee, 7), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [20] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_PY_FRAME_GENERAL", opnames)
        self.assertIn("_PUSH_FRAME", opnames)
        self.assertNotIn("_METHOD_DEOPT", opnames)
        self.assertEqual(caller(callee, 2**100), (2**100 + 3) * 2)

        callee.__defaults__ = (9,)
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(callee, 7), 32)
        callee.__defaults__ = None
        with self.assertRaises(TypeError):
            caller(callee, 7)

    @disable_gc()
    def test_method_code_budget_preserves_partial_cfg(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        lines = ["def large(value, events):",
                 "    if value < 0:",
                 "        return -value",
                 "    total = value"]
        for i in range(200):
            lines.append(f"    total += value + {i % 7}")
        lines.extend(["    events.append(total)", "    return total"])
        namespace = {}
        exec("\n".join(lines), namespace)
        large = namespace["large"]
        constant = sum(i % 7 for i in range(200))
        events = []
        expected = 201 + constant
        args = itertools.repeat((1, events), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(large, args)),
                         [expected] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(_opcode.get_executor(large.__code__, 0))
        self.assertIn("_METHOD_EXIT", names)
        self.assertIn("_METHOD_DEOPT", names)
        self.assertEqual(events, [expected] * TIER2_RESUME_THRESHOLD)
        events.clear()
        self.assertEqual(large(-3, events), 3)
        self.assertEqual(events, [])

        def short_path(n):
            total = 0
            for _ in range(n):
                total += large(-3, events)
            return total

        self.assertEqual(short_path(TIER2_THRESHOLD * 2),
                         TIER2_THRESHOLD * 6)
        traced = get_first_executor(short_path)
        self.assertIsNotNone(traced)
        self.assertIn("_METHOD_CALL", get_opnames(traced))
        for value in (0, 5, 2**60):
            expected = value * 201 + constant
            self.assertEqual(large(value, events), expected)
            self.assertEqual(events.pop(), expected)
            self.assertEqual(events, [])

        class BrokenEvents:
            def append(self, value):
                raise ValueError(value)
        # The call after the budget exit observes the full computed value
        # and propagates its error through the original function frame.
        with self.assertRaisesRegex(ValueError, str(5 * 201 + constant)):
            large(5, BrokenEvents())

    @disable_gc()
    def test_partial_method_resumes_hot_continuation_in_tier1(self):
        namespace = {}
        source = ("def large(value):\n    if value < 0:\n        return -value\n"
                  "    total = value\n")
        source += "    total += value + 1\n" * 200
        source += "    return total\n"
        exec(source, namespace)
        large = namespace["large"]
        # One in eight calls takes the incomplete path. It resumes in Tier 1
        # while the frequently used complete arm remains compiled.
        count = TIER2_RESUME_THRESHOLD * 8
        inputs = itertools.islice(itertools.cycle([-1] * 7 + [1]), count)
        self.assertEqual(list(map(large, inputs)), ([1] * 7 + [401]) * (count // 8))
        executor = _opcode.get_executor(large.__code__, 0)
        exits = [executor[op[2]] for op in executor
                 if op[0] == "_METHOD_DEOPT"]
        self.assertTrue(exits)
        for exit in exits:
            self.assertEqual(exit[0], "_EXIT_TRACE")
            self.assertGreater(exit[2], 0)
            self.assertLess(exit[2] * 2, len(large.__code__.co_code))
        self.assertEqual(get_all_executors(large), [executor])
        self.assertEqual(large(2**60), (2**60) * 201 + 200)
        with self.assertRaises(TypeError):
            large(None)

    @disable_gc()
    def test_partial_method_repeated_fallback_backs_off(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        source = "def large(value):\n    total = value\n"
        source += "    total += value + 1\n" * 200
        source += "    return total\n"
        exec(source, namespace)
        large = namespace["large"]
        count = TIER2_RESUME_THRESHOLD
        self.assertEqual(list(map(large, itertools.repeat(1, count))),
                         [401] * count)
        method = _opcode.get_executor(large.__code__, 0)
        self.assertIn("_METHOD_DEOPT", get_opnames(method))
        # The partial method is retired and its entry retries with backoff.
        # Recompilation, when it occurs, still uses the method frontend.
        self.assertEqual(list(map(large, itertools.repeat(1, count * 2))),
                         [401] * (count * 2))
        self.assertFalse(method.is_valid())
        for executor in get_all_executors(large):
            self.assertIn("_METHOD_DEOPT", get_opnames(executor))
        _testinternalcapi.invalidate_executors(large.__code__)
        self.assertEqual(list(map(large, itertools.repeat(1, count * 2))),
                         [401] * (count * 2))
        for executor in get_all_executors(large):
            self.assertIn("_METHOD_DEOPT", get_opnames(executor))
        self.assertEqual(large(2**60), (2**60) * 201 + 200)
        with self.assertRaises(TypeError):
            large(None)

    @disable_gc()
    def test_partial_method_backoff_retries_changed_code_and_hot_path(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        for respecialize in (False, True):
            with self.subTest(respecialize=respecialize):
                namespace = {}
                source = ("def large(value):\n"
                          "    if value < 0:\n"
                          "        return -value\n"
                          "    total = value\n")
                source += "    total += value + 1\n" * 200
                source += "    return total\n"
                exec(source, namespace)
                large = namespace["large"]
                count = TIER2_RESUME_THRESHOLD
                self.assertEqual(list(map(large, itertools.repeat(1, count))),
                                 [401] * count)
                method = _opcode.get_executor(large.__code__, 0)
                self.assertIn("_METHOD_DEOPT", get_opnames(method))
                self.assertEqual(list(map(large, itertools.repeat(1, 64))),
                                 [401] * 64)
                self.assertFalse(method.is_valid())
                # The bytecode remains specialized in the same way. Changing
                # only the branch history must not trigger another compile.
                self.assertEqual(list(map(large, itertools.repeat(-1, count * 2))),
                                 [1] * (count * 2))
                self.assertFalse(get_all_executors(large))
                value = -1.5 if respecialize else -1
                calls = count * (2 if respecialize else 16)
                self.assertEqual(list(map(large, itertools.repeat(value, calls))),
                                 [-value] * calls)
                # A changed specialization retries promptly. With unchanged
                # code, periodic retries still discover a newly useful path.
                replacement = _opcode.get_executor(large.__code__, 0)
                self.assertTrue(replacement.is_valid())
                self.assertIsNot(replacement, method)
                self.assertEqual(large(1), 401)
                with self.assertRaises(TypeError):
                    large(None)

    @disable_gc()
    def test_partial_method_repeated_guard_exits_preserve_method(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        namespace = {}
        source = ("def large(value):\n"
                  "    if value >= 0:\n"
                  "        return value + 1\n"
                  "    result = value\n")
        source += "    result += value + 1\n" * 200
        source += "    return result\n"
        exec(source, namespace)
        large = namespace["large"]
        count = TIER2_RESUME_THRESHOLD
        self.assertEqual(list(map(large, itertools.repeat(1, count))), [2] * count)
        method = _opcode.get_executor(large.__code__, 0)
        self.assertIn("_METHOD_PROFILE", get_opnames(method))
        self.assertIn("_METHOD_DEOPT", get_opnames(method))
        # The unsupported long path is never entered. Changing the argument
        # type repeatedly exits an integer guard in the short path.
        self.assertEqual(list(map(large, itertools.repeat(1.5, count * 2))),
                         [2.5] * (count * 2))
        self.assertTrue(method.is_valid())
        self.assertEqual(get_all_executors(large), [method])
        # The original integer fast path remains usable after polymorphic
        # calls; cold unsupported code is not a reason to discard it.
        self.assertEqual(list(map(large, itertools.repeat(1, count))), [2] * count)
        self.assertTrue(method.is_valid())
        self.assertEqual(large(2**60), 2**60 + 1)
        self.assertEqual(large(-1), -1)

    @disable_gc()
    def test_recursive_generator_setup_does_not_compile_empty_prefix(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Tree:
            def __init__(self, child):
                self.left = child
                self.right = child
                self.value = 1
            def __iter__(self):
                if self.left:
                    yield from self.left
                yield self.value
                if self.right:
                    yield from self.right
        def tree(values):
            if not values:
                return None
            middle = len(values) // 2
            child = Tree(None)
            child.left = tree(values[:middle])
            child.right = tree(values[middle+1:])
            return child
        def consume(loops):
            assert list(tree(range(10))) == [1] * 10
            iterations = range(loops)
            iterable = tree(range(100000))
            for _ in iterations:
                for item in iterable:
                    pass
            return item
        for function in (Tree.__init__, Tree.__iter__, tree, consume):
            reset_code(function)
        # Early attempts can stop before starting a child. Keep traversing
        # after their backoff to cover a prefix that also initializes one.
        for _ in range(10):
            self.assertEqual(consume(8), 1)
        executors = get_all_executors(consume)
        self.assertFalse(executors, [get_opnames(e) for e in executors])

    @disable_gc()
    def test_recursive_generators_resume_in_interpreter(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        def generate(values):
            for value in values:
                yield value + 1
        def delegate(iterator):
            yield from iterator
        def consume(iterator):
            result = 0
            for item in iterator:
                result += item
            return result
        for function in (generate, delegate, consume):
            reset_code(function)
        count = TIER2_THRESHOLD * 3
        iterator = delegate(delegate(generate(range(count))))
        self.assertEqual(consume(iterator), count * (count + 1) // 2)
        # The ordinary loop compiles, while yield-from frame transitions
        # and generator suspension remain in the interpreter.
        self.assert_generator_entries(generate)
        self.assertEqual(get_all_executors(delegate), [])
        self.assertEqual(consume(delegate(generate(range(10)))), 55)

    @disable_gc()
    def test_deep_generator_delegation_does_not_compile_empty_prefix(self):
        def delegate(iterator):
            yield from iterator

        def consume(iterator):
            for item in iterator:
                pass
            return item

        count = TIER2_THRESHOLD * 3
        iterator = iter(range(count))
        for _ in range(12):
            iterator = delegate(iterator)
        self.assertEqual(consume(iterator), count - 1)
        # The empty consumer cannot benefit from a native prefix before
        # returning to Tier 1 for each delegated generator resume.
        self.assertIsNone(get_first_executor(consume))

    @disable_gc()
    def test_method_empty_cell_uses_original_exception_handler(self):
        def factory(value):
            def read():
                try:
                    return value
                except NameError:
                    return "empty"
            return read

        read = factory(42)
        self.assertEqual(list(itertools.starmap(read, itertools.repeat(
            (), TIER2_RESUME_THRESHOLD))), [42] * TIER2_RESUME_THRESHOLD)
        if not Py_GIL_DISABLED:
            self.assertIn("_LOAD_DEREF_GUARDED", get_opnames(
                get_first_executor(read)))
        cell = read.__closure__[0]
        del cell.cell_contents
        self.assertEqual(read(), "empty")
        token = object()
        cell.cell_contents = token
        self.assertIs(read(), token)
        cell.cell_contents = None
        self.assertIsNone(read())

    @disable_gc()
    def test_method_closure_entry_and_cell_mutation(self):
        def factory(value):
            def read(delta):
                return value + delta
            def replace(new_value):
                nonlocal value
                value = new_value
            return read, replace

        read, replace = factory(40)
        other, _ = factory(100)
        entry = next(instruction.offset for instruction in
                     dis.get_instructions(read) if instruction.opname == "RESUME")
        self.assertGreater(entry, 0)
        self.assertEqual(list(map(read, itertools.repeat(
            2, TIER2_RESUME_THRESHOLD))), [42] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(_opcode.get_executor(read.__code__, entry))
        self.assertIn("_METHOD_EXIT", names)
        if not Py_GIL_DISABLED:
            self.assertIn("_LOAD_DEREF_GUARDED", names)
        self.assertIn("_BINARY_OP_ADD_INT", names)
        self.assertNotIn("_COPY_FREE_VARS", names)
        self.assertEqual(other(2), 102)
        replace(50)
        self.assertEqual(read(2), 52)
        self.assertEqual(other(2), 102)
        replace("a")
        self.assertEqual(read("b"), "ab")
        with self.assertRaises(TypeError):
            read(1)
        del read.__closure__[0].cell_contents
        with self.assertRaises(NameError):
            read(1)
        replace(70)
        self.assertEqual(read(2), 72)

    @disable_gc()
    def test_method_cell_initialization_runs_once(self):
        def make_reader(value):
            def read():
                return value
            return read

        entry = next(instruction.offset for instruction in
                     dis.get_instructions(make_reader)
                     if instruction.opname == "RESUME")
        self.assertGreater(entry, 0)
        readers = list(map(make_reader, range(TIER2_RESUME_THRESHOLD)))
        self.assertEqual([read() for read in readers],
                         list(range(TIER2_RESUME_THRESHOLD)))
        executor = _opcode.get_executor(make_reader.__code__, entry)
        names = get_opnames(executor)
        self.assertIn("_METHOD_EXIT", names)
        self.assertNotIn("_MAKE_CELL", names)
        # A later call must create its own cell before entering the executor.
        new_reader = make_reader("new")
        self.assertEqual(new_reader(), "new")
        self.assertIsNot(new_reader.__closure__[0], readers[-1].__closure__[0])
        self.assertEqual(readers[-1](), TIER2_RESUME_THRESHOLD - 1)

    @disable_gc()
    def test_method_protected_regions(self):
        def read(sequence, index, events):
            try:
                value = sequence[index]
            except IndexError:
                events.append(type(sys.exception()))
                return "missing"
            else:
                return value
            finally:
                events.append("finally")

        events = []
        args = itertools.repeat(([42], 0, events), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(read, args)),
                         [42] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(read.__code__, 0)
        names = get_opnames(executor)
        self.assertIn("_METHOD_EXIT", names)
        self.assertIn("_BINARY_OP_SUBSCR_LIST_INT" if Py_GIL_DISABLED else
                      "_BINARY_OP_SUBSCR_BORROWED_0", names)
        self.assertEqual(events, ["finally"] * TIER2_RESUME_THRESHOLD)
        events.clear()
        self.assertEqual(read([42], 1, events), "missing")
        self.assertEqual(events, [IndexError, "finally"])
        events.clear()

        class Broken:
            def __getitem__(self, index):
                raise ValueError("lookup")

        with self.assertRaisesRegex(ValueError, "lookup"):
            read(Broken(), 0, events)
        self.assertEqual(events, ["finally"])
        events.clear()
        # An exception active in the caller survives both normal execution
        # and an exception handled inside the compiled function.
        try:
            raise RuntimeError("outer")
        except RuntimeError as outer:
            self.assertEqual(read([42], 0, events), 42)
            self.assertIs(sys.exception(), outer)
            self.assertEqual(read([], 0, events), "missing")
            self.assertIs(sys.exception(), outer)

    @disable_gc()
    def test_method_error_enters_correct_handler(self):
        def divide(numerator, divisor, events):
            try:
                result = numerator / divisor
            except ZeroDivisionError:
                events.append("zero")
                result = -1.0
            try:
                return result + events[0]
            except TypeError:
                return result

        args = itertools.repeat((6.0, 2.0, [1.0]), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(divide, args)),
                         [4.0] * TIER2_RESUME_THRESHOLD)
        names = get_opnames(_opcode.get_executor(divide.__code__, 0))
        self.assertIn("_METHOD_EXIT", names)
        self.assertTrue(set(names) & {"_BINARY_OP_TRUEDIV_FLOAT",
                                      "_BINARY_OP_EXTEND", "_BINARY_OP"})
        # This error originates in compiled arithmetic, not a guard exit.
        events = [1.0]
        self.assertEqual(divide(6.0, 0.0, events), 0.0)
        self.assertEqual(events, [1.0, "zero"])
        self.assertEqual(divide(6.0, 2.0, ["other"]), 3.0)
        with self.assertRaises(IndexError):
            divide(6.0, 2.0, [])

    def test_calls_method_executor_and_propagates_exception(self):
        bias = 0

        def callee(n, *unused):
            total = 0
            for i in range(n):
                total += i
            # Variadic argument binding keeps this a nested method call,
            # including when the inliner supports small closure CFGs.
            try:
                if n < 0:
                    raise ValueError("negative")
            except ValueError:
                raise
            return total + bias

        def caller(function, n):
            return function(n) + 7

        self.assertEqual(list(map(callee, [8] * TIER2_RESUME_THRESHOLD)),
                         [28] * TIER2_RESUME_THRESHOLD)
        args = itertools.repeat((callee, 8), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, args)),
                         [35] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_METHOD_CALL", get_opnames(
            _opcode.get_executor(caller.__code__, 0)))
        self.assertEqual(caller(callee, 21), 217)
        with self.assertRaisesRegex(ValueError, "negative"):
            caller(callee, -1)
        self.assertEqual(caller(callee, 4), 13)

    def test_method_call_keeps_invalidated_caller_alive(self):
        def callee(obj):
            # Exceed the inline size limit while remaining compilable as a
            # method, so this exercises an actual nested executor entry.
            return (len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj) +
                    len(obj) + len(obj) + len(obj) + len(obj))

        def caller(function, obj):
            return function(obj) + 7

        def replacement(function, obj):
            return 900

        class Argument:
            invalidate = False

            def __len__(self):
                if self.invalidate:
                    caller.__code__ = replacement.__code__
                    gc.collect()
                return 1

        obj = Argument()
        list(map(callee, [obj] * TIER2_RESUME_THRESHOLD))
        args = itertools.repeat((callee, obj), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, args)),
                         [39] * TIER2_RESUME_THRESHOLD)
        # Do not retain an executor reference: the nested call must keep the
        # invalidated native return address alive by itself.
        self.assertIn("_METHOD_CALL", get_opnames(
            _opcode.get_executor(caller.__code__, 0)))
        obj.invalidate = True
        self.assertEqual(caller(callee, obj), 39)
        self.assertEqual(caller(callee, obj), 900)

    def test_recursive_method_calls(self):
        namespace = {}
        exec("def recurse(n):\n"
             "    if n:\n"
             "        return recurse(n - 1) + 1\n"
             "    return 0\n", namespace)
        recurse = namespace["recurse"]
        self.assertEqual(list(map(recurse, [8] * TIER2_RESUME_THRESHOLD)),
                         [8] * TIER2_RESUME_THRESHOLD)
        self.assertIn("_METHOD_CALL", get_opnames(
            _opcode.get_executor(recurse.__code__, 0)))
        self.assertEqual(recurse(300), 300)
        with self.assertRaises(RecursionError):
            recurse(sys.getrecursionlimit() + 1)
        previous_limit = sys.getrecursionlimit()
        try:
            # Exercise native stack fallback independently of the Python limit.
            sys.setrecursionlimit(100_000)
            self.assertEqual(recurse(20_000), 20_000)
        finally:
            sys.setrecursionlimit(previous_limit)

    def test_inlines_short_loop_with_periodic_check(self):
        def callee(n):
            total = 0
            while n > 0:
                n -= 1
                total += n
            return total

        def caller(function, n):
            return function(n) * 2

        list(map(callee, [8] * TIER2_RESUME_THRESHOLD))
        args = itertools.repeat((callee, 8), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, args)),
                         [56] * TIER2_RESUME_THRESHOLD)
        opnames = get_opnames(_opcode.get_executor(caller.__code__, 0))
        self.assertIn("_PUSH_FRAME", opnames)
        self.assertIn("_CHECK_PERIODIC", opnames)
        self.assertNotIn("_METHOD_CALL", opnames)
        for n in (0, -3, 21, 20000):
            self.assertEqual(caller(callee, n), max(n, 0) * max(n - 1, 0))

    def test_inlines_stored_bound_method(self):
        class Number:
            def __init__(self, value):
                self.value = value

            def add(self, increment):
                return self.value + increment

        def caller(method, value):
            return method(value) * 2

        first = Number(3)
        second = Number(9)
        arguments = itertools.repeat((first.add, 7), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [20] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_PUSH_FRAME", opnames)
        self.assertNotIn("_METHOD_DEOPT", opnames)
        self.assertEqual(caller(second.add, 7), 32)
        self.assertEqual(caller(lambda value: value - 1, 7), 12)
        with self.assertRaises(TypeError):
            caller(first.add, "x")

    def test_inlines_stored_bound_method_with_defaults(self):
        class Number:
            def __init__(self, value):
                self.value = value

            def add(self, increment=3):
                return self.value + increment

        def caller(method):
            return method() * 2

        obj = Number(7)
        self.assertEqual(list(map(caller, [obj.add] * TIER2_RESUME_THRESHOLD)),
                         [20] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_CHECK_METHOD_VERSION", opnames)
        self.assertIn("_PY_FRAME_GENERAL", opnames)
        self.assertNotIn("_METHOD_DEOPT", opnames)
        self.assertEqual(caller(Number(9).add), 24)
        Number.add.__defaults__ = (5,)
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(obj.add), 24)

    @disable_gc()
    def test_inlines_attribute_heavy_callee(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        class Record:
            __slots__ = tuple(f"field{i}" for i in range(12))

        record = Record()
        for index, name in enumerate(Record.__slots__):
            setattr(record, name, index)
        namespace = {}
        expression = " + ".join(f"record.{name}" for name in Record.__slots__)
        exec(f"def helper(record):\n    return {expression}\n"
             "def caller(record):\n    return helper(record) + 1\n", namespace)
        helper, caller = namespace["helper"], namespace["caller"]
        self.assertGreater(len(helper.__code__.co_code) // 2, 128)
        self.assertLess(len(list(dis.get_instructions(helper))), 128)
        count = TIER2_RESUME_THRESHOLD
        self.assertEqual(list(map(helper, itertools.repeat(record, count))),
                         [66] * count)
        self.assertEqual(list(map(caller, itertools.repeat(record, count))),
                         [67] * count)
        executor = get_first_executor(caller)
        names = get_opnames(executor)
        self.assertIn("_METHOD_EXIT", names)
        self.assertIn("_PUSH_FRAME", names)
        self.assertNotIn("_METHOD_CALL", names)
        record.field0 = 100
        self.assertEqual(caller(record), 167)

        def replacement(record):
            return record.field0

        helper.__code__ = replacement.__code__
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(record), 101)
        del record.field0
        with self.assertRaises(AttributeError):
            caller(record)

    def test_inlines_branching_callee_multiple_returns(self):
        def callee(flag, value):
            if flag:
                return value * 2
            return value + 3

        def caller(function, flag, value):
            return function(flag, value) + 1

        # Exercise both scalar arms before testing the complete inlined CFG.
        # Cold-arm specialization is covered separately.
        for _ in range(4):
            self.assertEqual(callee(True, 7), 14)
            self.assertEqual(callee(False, 7), 10)
        arguments = itertools.repeat((callee, True, 7), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [15] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertEqual(opnames.count("_PUSH_FRAME"), 1)
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", opnames)
        self.assertEqual(count_return_ops(opnames), 3)
        self.assertNotIn("_METHOD_DEOPT", opnames)
        self.assertEqual(caller(callee, False, 7), 11)
        self.assertEqual(caller(callee, True, 2**100), 2**101 + 1)
        self.assertEqual(caller(callee, False, 2**100), 2**100 + 4)
        self.assertEqual(caller(callee, True, 1.5), 4.0)

        try:
            caller(callee, False, "x")
        except TypeError as exc:
            tb = exc.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            self.assertIs(tb.tb_frame.f_code, callee.__code__)
            self.assertEqual(tb.tb_lineno, callee.__code__.co_firstlineno + 3)
        else:
            self.fail("TypeError not raised")

        def replacement(flag, value):
            return 42

        callee.__code__ = replacement.__code__
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(callee, False, 7), 43)

    def test_inlines_callee_with_cold_unsupported_arm(self):
        def callee(values, index):
            if index < 0:
                raise IndexError(index)
            return values[index]

        def caller(function, values, index):
            return function(values, index) + 1

        values = [10, 20]
        arguments = itertools.repeat((callee, values, 0), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [11] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_PUSH_FRAME", opnames)
        self.assertIn("_METHOD_DEOPT", opnames)
        self.assertNotIn("_METHOD_CALL", opnames)
        self.assertEqual(caller(callee, values, 1), 21)
        for index in (-1, 2):
            try:
                caller(callee, values, index)
            except IndexError as exc:
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                self.assertIs(tb.tb_frame.f_code, callee.__code__)
                self.assertEqual(tb.tb_lineno,
                                 callee.__code__.co_firstlineno +
                                 (2 if index < 0 else 3))
            else:
                self.fail("IndexError not raised")
        self.assertEqual(caller(callee, (3.5,), 0), 4.5)

        def replacement(values, index):
            return 42

        callee.__code__ = replacement.__code__
        self.assertFalse(executor.is_valid())
        self.assertEqual(caller(callee, values, -1), 43)

    def test_inlines_protected_callee_and_preserves_handlers(self):
        def callee(values, index, events):
            try:
                return values[index]
            except IndexError:
                return 40
            finally:
                events[0] += 1

        def caller(function, values, index, events):
            return function(values, index, events) + 1

        events = [0]
        arguments = itertools.repeat((callee, [10], 0, events),
                                     TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [11] * TIER2_RESUME_THRESHOLD)
        self.assertEqual(events, [TIER2_RESUME_THRESHOLD])
        executor = _opcode.get_executor(caller.__code__, 0)
        opnames = get_opnames(executor)
        self.assertIn("_PUSH_FRAME", opnames)
        self.assertNotIn("_METHOD_CALL", opnames)
        self.assertEqual(caller(callee, [10], 1, events), 41)
        self.assertEqual(caller(callee, (2.5,), 0, events), 3.5)
        try:
            caller(callee, None, 0, events)
        except TypeError as exc:
            tb = exc.__traceback__
            self.assertIs(tb.tb_next.tb_frame.f_code, caller.__code__)
            self.assertIs(tb.tb_next.tb_next.tb_frame.f_code, callee.__code__)
            self.assertEqual(tb.tb_next.tb_next.tb_lineno,
                             callee.__code__.co_firstlineno + 2)
        else:
            self.fail("TypeError not raised")
        self.assertEqual(events, [TIER2_RESUME_THRESHOLD + 3])
        self.assertEqual(caller(callee, [10], 0, events), 11)

    def test_inlined_callee_mixed_join(self):
        def callee(flag):
            if flag:
                value = 10
            else:
                value = "a"
            return value + value

        def caller(function, flag):
            return function(flag)

        for _ in range(4):
            self.assertEqual(callee(True), 20)
            self.assertEqual(callee(False), "aa")
        arguments = itertools.repeat((callee, True), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [20] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        self.assertIn("_PUSH_FRAME", get_opnames(executor))
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", get_opnames(executor))
        self.assertNotIn("_METHOD_DEOPT", get_opnames(executor))
        self.assertEqual(caller(callee, False), "aa")

    def test_cleanup_keeps_check_after_callback(self):
        def callee(flag):
            if flag:
                return 10
            return 20

        def replacement(flag):
            return 99

        class Argument:
            invalidate = False

            def __len__(self):
                if self.invalidate:
                    callee.__code__ = replacement.__code__
                return 1

        def caller(function, obj):
            count = len(obj)
            return function(True) + count

        obj = Argument()
        arguments = itertools.repeat((callee, obj), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [11] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        self.assertIn("_PUSH_FRAME", get_opnames(executor))
        obj.invalidate = True
        self.assertEqual(caller(callee, obj), 100)
        self.assertFalse(executor.is_valid())

    def test_cleanup_keeps_ip_for_each_call(self):
        def caller(a, b):
            first = len(a)
            second = len(b)
            return first + second

        arguments = itertools.repeat(([1], [2]), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(caller, arguments)),
                         [2] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        self.assertIn("_METHOD_EXIT", get_opnames(executor))
        for a, b, line in ((None, [], 1), ([], None, 2)):
            with self.subTest(line=line):
                try:
                    caller(a, b)
                except TypeError as exc:
                    tb = exc.__traceback__.tb_next
                    self.assertIs(tb.tb_frame.f_code, caller.__code__)
                    self.assertEqual(tb.tb_lineno,
                                     caller.__code__.co_firstlineno + line)
                else:
                    self.fail("TypeError not raised")

    def test_periodic_exit_after_completed_call(self):
        class Container:
            factory = dict

            def __init__(self):
                self.mapping = {"key": {}}

            def lookup(self, pairs):
                result = None
                for key, value in pairs:
                    result = self.mapping[key].get(value, self.factory())
                return result

        container = Container()
        pairs = [("key", "missing")]
        calls = TIER2_RESUME_THRESHOLD + TIER2_THRESHOLD
        results = list(map(container.lookup, itertools.repeat(pairs, calls)))
        self.assertEqual(results, [{}] * calls)

        executor = _opcode.get_executor(Container.lookup.__code__, 0)
        self.assertIn("_TIER2_RESUME_CHECK", get_opnames(executor))
        self.assertEqual(container.lookup(pairs), {})

    @disable_gc()
    def test_generic_iterator_error(self):
        # Collecting unrelated types can invalidate a just-created executor
        # through its dependency Bloom filter. Keep it alive for this assertion;
        # executor invalidation during callbacks is covered separately.
        class EmptyIterator:
            def __iter__(self):
                return self

            def __next__(self):
                raise StopIteration

        class BadIterator:
            def __iter__(self):
                return self

            def __next__(self):
                raise ValueError("iterator failed")

        def consume(iterator):
            total = 0
            for value in iterator:
                total += value
            return total

        empty = EmptyIterator()
        self.assertEqual(
            list(map(
                consume,
                itertools.repeat(empty, TIER2_RESUME_THRESHOLD),
            )),
            [0] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(consume.__code__, 0)
        self.assertIn("_METHOD_FOR_ITER", get_opnames(executor))
        with self.assertRaisesRegex(ValueError, "iterator failed"):
            consume(BadIterator())

    @disable_gc()
    def test_known_enumerate_iterator(self):
        def consume(values):
            result = 0
            for index, value in enumerate(values):
                result += index * value
            return result

        values = [2, 3, 4]
        self.assertEqual(list(map(consume, itertools.repeat(
            values, TIER2_RESUME_THRESHOLD))), [11] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(consume.__code__, 0)
        self.assertIn("_METHOD_ITER_NEXT_INLINE", get_opnames(executor))
        self.assertEqual(consume([]), 0)
        self.assertEqual(consume(iter(values)), 11)

        class BadIterator:
            def __iter__(self):
                return self
            def __next__(self):
                raise ValueError("iterator failed")

        with self.assertRaisesRegex(ValueError, "iterator failed"):
            consume(BadIterator())

    @disable_gc()
    def test_known_zip_iterator(self):
        def consume(first, second):
            result = 0
            for a, b in zip(first, second):
                result += a * b
            return result

        args = itertools.repeat(([1, 2], [3, 4]), TIER2_RESUME_THRESHOLD)
        self.assertEqual(list(itertools.starmap(consume, args)),
                         [11] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(consume.__code__, 0)
        self.assertIn("_METHOD_ITER_NEXT_INLINE", get_opnames(executor))
        self.assertEqual(consume([1, 2], [3]), 3)
        self.assertEqual(consume([], [3, 4]), 0)

    @disable_gc()
    def test_inlines_keyword_python_call(self):
        def callee(value, *, increment=2):
            return value + increment
        def caller(value, callee=callee):
            return callee(value, increment=3) * 2

        self.assertEqual(list(map(caller, itertools.repeat(
            5, TIER2_RESUME_THRESHOLD))), [16] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        self.assertIn("_PY_FRAME_KW", get_opnames(executor))
        self.assertNotIn("_METHOD_DEOPT", get_opnames(executor))
        def changed(value, *, increment):
            raise ValueError(increment)
        callee.__code__ = changed.__code__
        with self.assertRaisesRegex(ValueError, "3"):
            caller(5)

    @disable_gc()
    def test_keyword_bound_method_binding(self):
        class Value:
            def add(self, value, *, increment=2):
                return value + increment
        method = Value().add
        def caller(value, method=method):
            return method(value, increment=4)

        self.assertEqual(list(map(caller, itertools.repeat(
            5, TIER2_RESUME_THRESHOLD))), [9] * TIER2_RESUME_THRESHOLD)
        executor = _opcode.get_executor(caller.__code__, 0)
        self.assertIn("_EXPAND_METHOD_KW", get_opnames(executor))
        self.assertNotIn("_METHOD_DEOPT", get_opnames(executor))
        def changed(self, value):
            return value
        Value.add.__code__ = changed.__code__
        with self.assertRaisesRegex(TypeError, "unexpected keyword"):
            caller(5)



@requires_specialization
@requires_jit_enabled
class TestExecutorInvalidation(unittest.TestCase):
    @disable_gc()
    def test_reuse_detached_executor_slots(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)

        def leaf(value):
            return value + 1

        self.enterContext(clear_executors(leaf))
        previous = None
        count = TIER2_RESUME_THRESHOLD + 2
        for index in range(260):
            self.assertEqual(list(map(leaf, itertools.repeat(1, count))),
                             [2] * count)
            executor = get_first_executor(leaf)
            self.assertIsNotNone(executor, index)
            self.assertTrue(executor.is_valid())
            self.assertIsNot(executor, previous)
            if previous is not None:
                self.assertFalse(previous.is_valid())
            _testinternalcapi.invalidate_executors(leaf.__code__)
            self.assertFalse(executor.is_valid())
            previous = executor

    def test_loop_retry_after_invalidation(self):
        for padding in (0, 40):
            with self.subTest(padding=padding):
                ns = {}
                exec("def loop(n):\n    total = 0\n    for i in range(n):\n"
                     + "        total += i\n" * (padding + 1)
                     + "    return total\n", ns)
                loop = ns["loop"]
                backward = next(inst for inst in dis.get_instructions(loop)
                                if inst.opname == "JUMP_BACKWARD")
                self.assertEqual(backward.arg > 255, bool(padding))
                expected = (padding + 1) * sum(range(TIER2_THRESHOLD))
                self.assertEqual(loop(TIER2_THRESHOLD), expected)
                first = get_first_executor(loop)
                self.assertIsNotNone(first)
                # Compilation restarts the countdown with exponential backoff.
                # The actual jump cache follows any EXTENDED_ARG prefix.
                # The low three bits hold the backoff.
                counter, = struct.unpack_from(
                    "=H", loop.__code__._co_code_adaptive, backward.offset + 2)
                self.assertEqual(counter >> 3, 8190)
                _testinternalcapi.invalidate_executors(loop.__code__)
                self.assertFalse(first.is_valid())
                retry = (counter >> 3) + 2
                self.assertEqual(loop(retry), (padding + 1) * sum(range(retry)))
                second = get_first_executor(loop)
                self.assertIsNotNone(second)
                self.assertIsNot(second, first)
                self.assertTrue(second.is_valid())

    def test_resume_counter_after_compilation(self):
        ns = {}
        exec("def leaf(value):\n    return value + 1\n", ns)
        leaf = ns["leaf"]
        # Call from C so a caller trace cannot inline the function and avoid
        # executing its RESUME counter.
        self.assertEqual(list(map(leaf, [1] * TIER2_RESUME_THRESHOLD)),
                         [2] * TIER2_RESUME_THRESHOLD)
        self.assertIsNotNone(get_first_executor(leaf))
        counter, = struct.unpack_from("=H", leaf.__code__._co_code_adaptive, 2)
        self.assertEqual(counter >> 3, TIER2_RESUME_THRESHOLD - 2)

    @disable_gc()
    def test_inlined_callee_retains_resume_counter(self):
        ns = {}
        exec("def leaf(value):\n    return value + 1\n"
             "def caller(n):\n    total = 0\n    for i in range(n):\n"
             "        total += leaf(i)\n    return total\n", ns)
        n = TIER2_THRESHOLD
        self.assertEqual(ns["caller"](n), n * (n + 1) // 2)
        leaf = ns["leaf"]
        # Static inlining must not reset or wrap the callee's entry countdown.
        counter, = struct.unpack_from("=H", leaf.__code__._co_code_adaptive, 2)
        self.assertGreater(counter >> 3, 0)
        self.assertLess(counter >> 3, TIER2_RESUME_THRESHOLD - 1)
        count = (counter >> 3) + 2
        self.assertEqual(list(map(leaf, itertools.repeat(1, count))), [2] * count)
        self.assertIsNotNone(get_first_executor(leaf))

    def test_subinterpreter_creation_invalidates_owner_executors(self):
        # Bootstrapping a subinterpreter temporarily attaches another thread
        # state to the main interpreter while the subinterpreter is current.
        # In free-threaded builds this invalidates the main interpreter's JIT.
        code = """
            import _opcode
            import sys
            from test import support
            from test.support import Py_GIL_DISABLED
            from test.test_capi.test_opt import TIER2_RESUME_THRESHOLD

            def leaf(value):
                return value + 1

            assert list(map(leaf, [41] * TIER2_RESUME_THRESHOLD)) == (
                [42] * TIER2_RESUME_THRESHOLD)
            executor = _opcode.get_executor(leaf.__code__, 0)
            assert executor is not None and executor.is_valid()
            for _ in range(3):
                assert support.run_in_subinterp("pass") == 0
                assert leaf(41) == 42
            if Py_GIL_DISABLED:
                assert not executor.is_valid()
            assert sys._jit.is_enabled()
        """
        script_helper.assert_python_ok("-c", textwrap.dedent(code), PYTHON_JIT="1")

    @unittest.skipUnless(Py_GIL_DISABLED, "requires a free-threaded build")
    def test_jit_disabled_and_reenabled_for_second_thread(self):
        def loop(n):
            total = 0
            for i in range(n):
                total += i
            return total

        expected = sum(range(5))
        self.assertEqual(
            list(map(loop, [5] * TIER2_RESUME_THRESHOLD)),
            [expected] * TIER2_RESUME_THRESHOLD,
        )
        executor = _opcode.get_executor(loop.__code__, 0)
        self.assertIn("_METHOD_ITER_JUMP_RANGE", get_opnames(executor))

        ready = threading.Event()
        release = threading.Event()

        def worker():
            ready.set()
            release.wait()

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            self.assertFalse(sys._jit.is_enabled())
            self.assertFalse(executor.is_valid())
            self.assertEqual(loop(5), expected)
            self.assertIsNone(get_first_executor(loop))
        finally:
            release.set()
            thread.join()

        self.assertTrue(sys._jit.is_enabled())
        self.assertEqual(
            list(map(loop, [5] * TIER2_RESUME_THRESHOLD)),
            [expected] * TIER2_RESUME_THRESHOLD,
        )
        replacement = _opcode.get_executor(loop.__code__, 0)
        self.assertIsNot(replacement, executor)
        self.assertIn("_METHOD_ITER_JUMP_RANGE", get_opnames(replacement))

    def test_invalidate_object(self):
        # Generate a new set of functions at each call
        ns = {}
        func_src = "\n".join(
            f"""
            def f{n}():
                for _ in range({TIER2_THRESHOLD}):
                    pass
            """ for n in range(5)
        )
        exec(textwrap.dedent(func_src), ns, ns)
        funcs = [ ns[f'f{n}'] for n in range(5)]
        objects = [object() for _ in range(5)]

        for f in funcs:
            f()
        executors = [get_first_executor(f) for f in funcs]
        # Set things up so each executor depends on the objects
        # with an equal or lower index.
        for i, exe in enumerate(executors):
            self.assertTrue(exe.is_valid())
            for obj in objects[:i+1]:
                _testinternalcapi.add_executor_dependency(exe, obj)
            self.assertTrue(exe.is_valid())
        # Assert that the correct executors are invalidated
        # and check that nothing crashes when we invalidate
        # an executor multiple times.
        for i in (4,3,2,1,0):
            _testinternalcapi.invalidate_executors(objects[i])
            for exe in executors[i:]:
                self.assertFalse(exe.is_valid())
            for exe in executors[:i]:
                self.assertTrue(exe.is_valid())

    @unittest.skipIf(os.getenv("PYTHON_UOPS_OPTIMIZE") == "0", "Needs uop optimizer to run.")
    def test_uop_optimizer_invalidation(self):
        # Generate a new function at each call
        ns = {}
        exec(textwrap.dedent(f"""
            def f():
                for i in range({TIER2_THRESHOLD}):
                    pass
        """), ns, ns)
        f = ns['f']
        f()
        exe = get_first_executor(f)
        self.assertIsNotNone(exe)
        self.assertTrue(exe.is_valid())
        _testinternalcapi.invalidate_executors(f.__code__)
        self.assertFalse(exe.is_valid())

    def test_sys__clear_internal_caches(self):
        def f():
            for _ in range(TIER2_THRESHOLD):
                pass
        f()
        exe = get_first_executor(f)
        self.assertIsNotNone(exe)
        self.assertTrue(exe.is_valid())
        sys._clear_internal_caches()
        self.assertFalse(exe.is_valid())
        exe = get_first_executor(f)
        self.assertIsNone(exe)

    def test_prev_executor_freed_while_tracing(self):
        def f(start, end, way):
            for x in range(start, end):
                # For the first trace, create a bad branch on purpose to trace into.
                # A side exit will form from here on the second trace.
                y = way + way
                if x >= TIER2_THRESHOLD:
                    # Invalidate the first trace while tracing the second.
                    _testinternalcapi.invalidate_executors(f.__code__)
                    _testinternalcapi.clear_executor_deletion_list()
        f(0, TIER2_THRESHOLD, 1)
        f(1, TIER2_THRESHOLD + 1, 1.0)


def get_bool_guard_ops():
    delta = id(True) ^ id(False)
    for bit in range(4, 8):
        if delta & (1 << bit):
            if id(True) & (1 << bit):
                return f"_GUARD_BIT_IS_UNSET_POP_{bit}", f"_GUARD_BIT_IS_SET_POP_{bit}"
            else:
                return f"_GUARD_BIT_IS_SET_POP_{bit}", f"_GUARD_BIT_IS_UNSET_POP_{bit}"
    return "_GUARD_IS_FALSE_POP", "_GUARD_IS_TRUE_POP"


@requires_specialization
@requires_jit_enabled
@unittest.skipIf(os.getenv("PYTHON_UOPS_OPTIMIZE") == "0", "Needs uop optimizer to run.")
@isolation.runInSubprocess(timeout=SHORT_TIMEOUT)
class TestUops(unittest.TestCase):
    # Isolate specialization and executor lifetime from the test runner.

    def test_basic_loop(self):
        def testfunc(x):
            i = 0
            while i < x:
                i += 1

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_JUMP", uops)
        self.assertIn("_LOAD_FAST_BORROW_0", uops)

    def test_extended_arg(self):
        "Check EXTENDED_ARG handling in superblock creation"
        ns = {}
        exec(textwrap.dedent(f"""
            def many_vars():
                # 260 vars, so z9 should have index 259
                a0 = a1 = a2 = a3 = a4 = a5 = a6 = a7 = a8 = a9 = 42
                b0 = b1 = b2 = b3 = b4 = b5 = b6 = b7 = b8 = b9 = 42
                c0 = c1 = c2 = c3 = c4 = c5 = c6 = c7 = c8 = c9 = 42
                d0 = d1 = d2 = d3 = d4 = d5 = d6 = d7 = d8 = d9 = 42
                e0 = e1 = e2 = e3 = e4 = e5 = e6 = e7 = e8 = e9 = 42
                f0 = f1 = f2 = f3 = f4 = f5 = f6 = f7 = f8 = f9 = 42
                g0 = g1 = g2 = g3 = g4 = g5 = g6 = g7 = g8 = g9 = 42
                h0 = h1 = h2 = h3 = h4 = h5 = h6 = h7 = h8 = h9 = 42
                i0 = i1 = i2 = i3 = i4 = i5 = i6 = i7 = i8 = i9 = 42
                j0 = j1 = j2 = j3 = j4 = j5 = j6 = j7 = j8 = j9 = 42
                k0 = k1 = k2 = k3 = k4 = k5 = k6 = k7 = k8 = k9 = 42
                l0 = l1 = l2 = l3 = l4 = l5 = l6 = l7 = l8 = l9 = 42
                m0 = m1 = m2 = m3 = m4 = m5 = m6 = m7 = m8 = m9 = 42
                n0 = n1 = n2 = n3 = n4 = n5 = n6 = n7 = n8 = n9 = 42
                o0 = o1 = o2 = o3 = o4 = o5 = o6 = o7 = o8 = o9 = 42
                p0 = p1 = p2 = p3 = p4 = p5 = p6 = p7 = p8 = p9 = 42
                q0 = q1 = q2 = q3 = q4 = q5 = q6 = q7 = q8 = q9 = 42
                r0 = r1 = r2 = r3 = r4 = r5 = r6 = r7 = r8 = r9 = 42
                s0 = s1 = s2 = s3 = s4 = s5 = s6 = s7 = s8 = s9 = 42
                t0 = t1 = t2 = t3 = t4 = t5 = t6 = t7 = t8 = t9 = 42
                u0 = u1 = u2 = u3 = u4 = u5 = u6 = u7 = u8 = u9 = 42
                v0 = v1 = v2 = v3 = v4 = v5 = v6 = v7 = v8 = v9 = 42
                w0 = w1 = w2 = w3 = w4 = w5 = w6 = w7 = w8 = w9 = 42
                x0 = x1 = x2 = x3 = x4 = x5 = x6 = x7 = x8 = x9 = 42
                y0 = y1 = y2 = y3 = y4 = y5 = y6 = y7 = y8 = y9 = 42
                z0 = z1 = z2 = z3 = z4 = z5 = z6 = z7 = z8 = z9 = {TIER2_THRESHOLD}
                while z9 > 0:
                    z9 = z9 - 1
                    +z9
        """), ns, ns)
        many_vars = ns["many_vars"]

        ex = get_first_executor(many_vars)
        self.assertIsNone(ex)
        many_vars()

        ex = get_first_executor(many_vars)
        self.assertIsNotNone(ex)
        self.assertTrue(any((opcode, oparg, operand) == ("_LOAD_FAST_BORROW", 259, 0)
                            for opcode, oparg, _, operand in list(ex)))

    def test_jump_backward_extended_arg(self):
        # gh-152192: a JUMP_BACKWARD that needs an EXTENDED_ARG must record its
        # deopt target at the EXTENDED_ARG, not the JUMP_BACKWARD.
        ns = {}
        src = ("def f(n):\n"
               "    i = 0\n"
               "    while i < n:\n"
               "        i += 1\n"
               + "".join(f"        a = {j}\n" for j in range(140)))
        exec(src, ns)
        f = ns["f"]

        instrs = list(dis.get_instructions(f))
        ext, jb = next((p, i) for p, i in zip(instrs, instrs[1:])
                       if i.opname == "JUMP_BACKWARD" and p.opname == "EXTENDED_ARG")

        f(TIER2_THRESHOLD + 1)
        ex = _opcode.get_executor(f.__code__, ext.offset)
        # The entry guard deopts to the complete extended instruction. The
        # backward edge itself need not save an IP when no operation can fail.
        deopts = {t for op, _, t, _ in ex if op == "_DEOPT"}
        self.assertIn(ext.offset // 2, deopts)
        self.assertNotIn(jb.offset // 2, deopts)
        _testinternalcapi.invalidate_executors(f.__code__)
        f(10)

    def test_unspecialized_unpack(self):
        # An example of an unspecialized opcode
        def testfunc(x):
            i = 0
            while i < x:
                i += 1
                a, b = {1: 2, 3: 3}
            assert a == 1 and b == 3
            i = 0
            while i < x:
                i += 1

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_UNPACK_SEQUENCE", uops)

    def test_unspecialized_unpack_tuple(self):
        def unpack(values, count):
            for _ in range(count):
                a, b, c = values
            return a, b, c

        # Dict iteration keeps the recorded unpack generic. Reuse that code
        # for tuples, including subclasses whose iterator must be respected.
        count = TIER2_THRESHOLD + 10
        self.assertEqual(unpack({1: None, 2: None, 3: None}, count), (1, 2, 3))
        executor = get_first_executor(unpack)
        self.assertIsNotNone(executor)
        self.assertIn('_UNPACK_SEQUENCE', get_opnames(executor))
        values = (object(), object(), object())
        result = unpack(values, count)
        self.assertTrue(all(a is b for a, b in zip(result, values)))
        self.assertTrue(executor.is_valid())

        class TupleSubclass(tuple):
            def __iter__(self):
                return iter((7, 8, 9))

        self.assertEqual(unpack(TupleSubclass((1, 2, 3)), count), (7, 8, 9))
        with self.assertRaisesRegex(ValueError, 'not enough values to unpack'):
            unpack((1, 2), count)
        with self.assertRaisesRegex(ValueError, 'too many values to unpack'):
            unpack((1, 2, 3, 4), count)

    def test_pop_jump_if_false(self):
        def testfunc(n):
            i = 0
            while i < n:
                i += 1

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", uops)

    def test_pop_jump_if_none(self):
        def testfunc(a):
            for x in a:
                if x is None:
                    x = 0

        testfunc(range(TIER2_THRESHOLD))

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_IS_NONE_POP", uops)
        self.assertNotIn("_GUARD_IS_NOT_NONE_POP", uops)

    def test_pop_jump_if_not_none(self):
        def testfunc(a):
            for x in a:
                x = None
                if x is not None:
                    x = 0

        testfunc(range(TIER2_THRESHOLD))

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_IS_NONE_POP", uops)
        self.assertNotIn("_GUARD_IS_NOT_NONE_POP", uops)

    def test_pop_jump_if_true(self):
        def testfunc(n):
            i = 0
            while not i >= n:
                i += 1

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_POP_JUMP_IF_TRUE", uops)

    def test_jump_backward(self):
        def testfunc(n):
            i = 0
            while i < n:
                i += 1

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_JUMP", uops)

    def test_resume(self):
        def testfunc(x):
            if x <= 1:
                return 1
            return testfunc(x-1)

        for _ in range((TIER2_RESUME_THRESHOLD + 99)//100):
            testfunc(101)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # START_EXECUTOR validates the method before the entry periodic
        # check; a second validity check on this path is redundant.
        self.assertEqual(uops[:3], ["_START_EXECUTOR", "_MAKE_WARM",
                                    "_TIER2_RESUME_CHECK"])

    def test_jump_forward(self):
        def testfunc(n):
            a = 0
            while a < n:
                if a < 0:
                    a = -a
                else:
                    a = +a
                a += 1
            return a

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # Since there is no JUMP_FORWARD instruction,
        # look for indirect evidence: the += operator
        self.assertIn("_BINARY_OP_ADD_INT", uops)

    def test_get_iter_list(self):
        l = list(range(10))
        def testfunc(n):
            total = 0
            while n:
                n -= 1
                total += n
                for i in l:
                    break
            return total

        total = testfunc(TIER2_THRESHOLD)
        self.assertEqual(total, sum(range(TIER2_THRESHOLD)))
        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_TAGGED_ZERO", uops)
        self.assertNotIn("_GET_ITER", uops)
        self.assertNotIn("_GET_ITER_TRAD", uops)
        self.assertNotIn("_GET_ITER_VIRTUAL", uops)
        self.assertNotIn("_GET_ITER_SELF", uops)

    def test_get_iter_gen(self):
        def gen():
            while True:
                yield 1

        def testfunc(n):
            total = 0
            while n:
                n -= 1
                total += n
                for i in gen():
                    break
            return total

        total = testfunc(TIER2_THRESHOLD)
        self.assertEqual(total, sum(range(TIER2_THRESHOLD)))
        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_NULL", uops)
        self.assertNotIn("_GET_ITER", uops)
        self.assertNotIn("_GET_ITER_TRAD", uops)
        self.assertNotIn("_GET_ITER_VIRTUAL", uops)
        self.assertNotIn("_GET_ITER_SELF", uops)

    def test_get_iter_trad(self):
        d = {v:v for v in range(10)}
        def testfunc(n):
            total = 0
            while n:
                n -= 1
                total += n
                for i in d:
                    break
            return total

        total = testfunc(TIER2_THRESHOLD)
        self.assertEqual(total, sum(range(TIER2_THRESHOLD)))
        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The captured cell's current type is not a static CFG fact.
        self.assertIn("_GET_ITER", uops)
        self.assertNotIn("_GET_ITER_VIRTUAL", uops)
        self.assertNotIn("_GET_ITER_SELF", uops)


    def test_for_iter_range(self):
        def testfunc(n):
            total = 0
            for i in range(n):
                total += i
            return total

        total = testfunc(TIER2_THRESHOLD)
        self.assertEqual(total, sum(range(TIER2_THRESHOLD)))

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        # for i, (opname, oparg) in enumerate(ex):
        #     print(f"{i:4d}: {opname:<20s} {oparg:3d}")
        uops = get_opnames(ex)
        self.assertIn("_METHOD_ITER_JUMP_RANGE", uops)
        # Verification that the jump goes past END_FOR
        # is done by manual inspection of the output

    def test_for_iter_list(self):
        def testfunc(a):
            total = 0
            for i in a:
                total += i
            return total

        a = list(range(TIER2_THRESHOLD))
        total = testfunc(a)
        self.assertEqual(total, sum(a))

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        # for i, (opname, oparg) in enumerate(ex):
        #     print(f"{i:4d}: {opname:<20s} {oparg:3d}")
        uops = get_opnames(ex)
        self.assertIn("_METHOD_ITER_JUMP_LIST", uops)
        # Verification that the jump goes past END_FOR
        # is done by manual inspection of the output

    def test_for_iter_tuple(self):
        def testfunc(a):
            total = 0
            for i in a:
                total += i
            return total

        a = tuple(range(TIER2_THRESHOLD))
        total = testfunc(a)
        self.assertEqual(total, sum(a))

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        # for i, (opname, oparg) in enumerate(ex):
        #     print(f"{i:4d}: {opname:<20s} {oparg:3d}")
        uops = get_opnames(ex)
        self.assertIn("_METHOD_ITER_JUMP_TUPLE", uops)
        # Verification that the jump goes past END_FOR
        # is done by manual inspection of the output

    def test_list_edge_case(self):
        def testfunc(it):
            for x in it:
                pass

        a = [1, 2, 3]
        it = iter(a)
        testfunc(it)
        a.append(4)
        with self.assertRaises(StopIteration):
            next(it)

    def test_call_py_exact_args(self):
        def testfunc(n):
            def dummy(x):
                return x+1
            for i in range(n):
                dummy(i)

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertIn("_BINARY_OP_ADD_INT", uops)

    def test_call_py_ex(self):
        def testfunc(n):
            def ex_py(*args, **kwargs):
                return 1

            for _ in range(n):
                args = (1, 2, 3)
                kwargs = {}
                ex_py(*args, **kwargs)

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertIn("_PY_FRAME_EX", uops)

    def test_branch_taken(self):
        def testfunc(n):
            for i in range(n):
                if i < 0:
                    i = 0
                else:
                    i = 1

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_POP_JUMP_IF_FALSE", uops)

    def test_branch_coincident_targets(self):
        # test for gh-144681: https://github.com/python/cpython/issues/144681
        def testfunc(n):
            for _ in range(n):
                r = [x for x in range(10) if [].append(x) or True]
            return r

        res = testfunc(TIER2_THRESHOLD)
        ex = get_first_executor(testfunc)

        self.assertEqual(res, list(range(10)))
        self.assertIsNotNone(ex)

    def test_for_iter_tier_two(self):
        class MyIter:
            def __init__(self, n):
                self.n = n
            def __iter__(self):
                return self
            def __next__(self):
                self.n -= 1
                if self.n < 0:
                    raise StopIteration
                return self.n

        def testfunc(n, m):
            x = 0
            for i in range(m):
                for j in MyIter(n):
                    x += j
            return x

        x = testfunc(TIER2_THRESHOLD, 2)

        self.assertEqual(x, sum(range(TIER2_THRESHOLD)) * 2)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_ITER_NEXT_INLINE", uops)


@requires_specialization
@requires_jit_enabled
@unittest.skipIf(os.getenv("PYTHON_UOPS_OPTIMIZE") == "0", "Needs uop optimizer to run.")
class TestUopsOptimization(unittest.TestCase):

    def test_empty_set_call(self):
        def collect(count):
            result = []
            for _ in range(count):
                result.append(set())
            return result
        result = collect(TIER2_THRESHOLD)
        executor = get_first_executor(collect)
        self.assertIsNotNone(executor)
        self.assertIn("_CALL_SET_EMPTY", get_opnames(executor))
        self.assertEqual(result, [set()] * TIER2_THRESHOLD)
        result[0].add(42)
        self.assertEqual(result[1], set())

    def test_empty_dict_allocation(self):
        def collect(count):
            result = []
            for _ in range(count):
                result.append({})
            return result
        result = collect(TIER2_THRESHOLD)
        executor = get_first_executor(collect)
        self.assertIsNotNone(executor)
        self.assertIn("_BUILD_EMPTY_MAP", get_opnames(executor))
        self.assertEqual(result, [{}] * TIER2_THRESHOLD)
        result[0]["changed"] = True
        self.assertEqual(result[1], {})

    def test_store_mutable_default_descriptor_change(self):
        events = []
        class Default:
            pass
        class Record:
            value = Default()
        record = Record()
        def loop(count):
            for value in range(count):
                record.value = value
        loop(TIER2_THRESHOLD)
        executor = get_first_executor(loop)
        self.assertIsNotNone(executor)
        if not Py_GIL_DISABLED:
            self.assertIn("_GUARD_STORE_ATTR_NONDATA_CACHED", get_opnames(executor))
        self.assertEqual(record.value, TIER2_THRESHOLD - 1)
        Default.__set__ = lambda self, obj, value: events.append(value)
        loop(10)
        self.assertEqual(events, list(range(10)))
        self.assertEqual(record.value, TIER2_THRESHOLD - 1)

    def setUp(self):
        self.guard_is_false, self.guard_is_true = get_bool_guard_ops()

    def _run_with_optimizer(self, testfunc, arg):
        res = testfunc(arg)

        ex = get_first_executor(testfunc)
        return res, ex


    def test_int_type_propagation(self):
        def testfunc(loops):
            num = 0
            for i in range(loops):
                x = num + num
                a = x + 1
                num += 1
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        self.assertEqual(res, (TIER2_THRESHOLD - 1) * 2 + 1)
        binop_count = [opname for opname in iter_opnames(ex) if opname == "_BINARY_OP_ADD_INT"]
        guard_tos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_INT"]
        guard_nos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_INT"]
        self.assertGreaterEqual(len(binop_count), 3)
        self.assertLessEqual(len(guard_tos_int_count), 1)
        self.assertLessEqual(len(guard_nos_int_count), 1)

    def test_int_type_propagation_through_frame(self):
        def double(x):
            return x + x
        def testfunc(loops):
            num = 0
            for i in range(loops):
                x = num + num
                a = double(x)
                num += 1
            return a

        res = testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        self.assertEqual(res, (TIER2_THRESHOLD - 1) * 4)
        binop_count = [opname for opname in iter_opnames(ex) if opname == "_BINARY_OP_ADD_INT"]
        guard_tos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_INT"]
        guard_nos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_INT"]
        self.assertGreaterEqual(len(binop_count), 3)
        self.assertLessEqual(len(guard_tos_int_count), 1)
        self.assertLessEqual(len(guard_nos_int_count), 1)

    def test_int_type_propagation_from_frame(self):
        def double(x):
            return x + x
        def testfunc(loops):
            num = 0
            for i in range(loops):
                a = double(num)
                x = a + a
                num += 1
            return x

        res = testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        self.assertEqual(res, (TIER2_THRESHOLD - 1) * 4)
        binop_count = [opname for opname in iter_opnames(ex) if opname == "_BINARY_OP_ADD_INT"]
        guard_tos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_INT"]
        guard_nos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_INT"]
        self.assertGreaterEqual(len(binop_count), 3)
        self.assertLessEqual(len(guard_tos_int_count), 1)
        self.assertLessEqual(len(guard_nos_int_count), 1)

    def test_int_impure_region(self):
        def testfunc(loops):
            num = 0
            while num < loops:
                x = num + num
                y = 1
                x // 2
                a = x + y
                num += 1
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        binop_count = [opname for opname in iter_opnames(ex) if opname == "_BINARY_OP_ADD_INT"]
        self.assertGreaterEqual(len(binop_count), 3)

    def test_call_py_exact_args(self):
        def testfunc(n):
            def dummy(x):
                return x+1
            for i in range(n):
                dummy(i)

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertIn("_BINARY_OP_ADD_INT", uops)
        self.assertNotIn("_CHECK_PEP_523", uops)
        self.assertNotIn("_GUARD_CODE_VERSION__PUSH_FRAME", uops)
        self.assertNotIn("_GUARD_IP__PUSH_FRAME", uops)

    def test_int_type_propagate_through_range(self):
        def testfunc(n):

            for i in range(n):
                x = i + i
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, (TIER2_THRESHOLD - 1) * 2)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_TOS_INT", uops)
        self.assertNotIn("_GUARD_NOS_INT", uops)

    def test_int_value_numbering(self):
        def testfunc(n, y):
            for i in range(n):
                x = y
                z = x
                a = z
                b = a
                # Separate consumers exercise alias-based guard elimination
                # without forming one bounded arithmetic region.
                res = (x + z, a + b)
            return res

        res = testfunc(TIER2_THRESHOLD, 1)
        ex = get_first_executor(testfunc)
        self.assertEqual(res, (2, 2))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The input is unknown at OSR; aliases share its first integer guard.
        self.assertIn("_GUARD_TOS_INT", uops)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        guard_tos_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_INT"]
        self.assertEqual(len(guard_tos_count), 1)

    def test_comprehension(self):
        def testfunc(n):
            for _ in range(n):
                return [i for i in range(n)]

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, list(range(TIER2_THRESHOLD)))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_BINARY_OP_ADD_INT", uops)

    def test_call_py_exact_args_disappearing(self):
        def dummy(x):
            return x+1

        def testfunc(n):
            for i in range(n):
                dummy(i)

        # Trigger specialization
        testfunc(8)
        del dummy
        gc.collect()

        def dummy(x):
            return x + 2
        testfunc(32)

        ex = get_first_executor(testfunc)
        # Honestly as long as it doesn't crash it's fine.
        # Whether we get an executor or not is non-deterministic,
        # because it's decided by when the function is freed.
        # This test is a little implementation specific.

    def test_promote_globals_to_constants(self):

        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        import _testinternalcapi
        import opcode
        import _opcode

        def get_first_executor(func):
            code = func.__code__
            co_code = code.co_code
            for i in range(0, len(co_code), 2):
                try:
                    return _opcode.get_executor(code, i)
                except ValueError:
                    pass
            return None

        def get_opnames(ex):
            return {item[0] for item in ex}

        def testfunc(n):
            for i in range(n):
                x = range(i)
            return x

        testfunc(_testinternalcapi.TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        assert ex is not None
        uops = get_opnames(ex)
        assert "_LOAD_GLOBAL_BUILTINS" not in uops
        assert "_LOAD_CONST_INLINE_BORROW" in uops
        """), PYTHON_JIT="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_copied_builtins_value_change(self):
        import builtins

        namespace = {"__builtins__": vars(builtins).copy()}
        exec("def size(value):\n"
             "    return len(value)\n"
             "def run(value, n):\n"
             "    for _ in range(n):\n"
             "        result = size(value)\n"
             "    return result\n", namespace)
        self.assertEqual(namespace["run"]([1], TIER2_THRESHOLD), 1)
        namespace["__builtins__"]["len"] = lambda value: 42
        self.assertEqual(namespace["run"]([1], 8), 42)

    def test_builtin_identity_guard_reused_in_same_frame(self):
        import builtins

        namespace = {"__builtins__": vars(builtins)}
        exec("def run(value, n):\n"
             "    for _ in range(n):\n"
             "        result = (len(value), len(value), Ellipsis, NotImplemented)\n"
             "    return result\n", namespace)
        run = namespace["run"]
        self.assertEqual(run([1], TIER2_THRESHOLD),
                         (1, 1, Ellipsis, NotImplemented))
        executor = get_first_executor(run)
        self.assertIsNotNone(executor)
        self.assertEqual(get_opnames(executor).count("_GUARD_BUILTINS_IDENTITY"), 1)

        custom = vars(builtins).copy()
        custom.update(len=lambda value: 42, Ellipsis=17, NotImplemented=23)
        other = types.FunctionType(run.__code__, {"__builtins__": custom})
        self.assertEqual(other([1], 8), (42, 42, 17, 23))
        self.assertEqual(run([1], 8), (1, 1, Ellipsis, NotImplemented))

    def test_same_function_version_different_builtins(self):
        import builtins

        def make_size():
            def size(value):
                return len(value)
            return size

        def run(functions, value):
            result = None
            for function in functions:
                result = function(value)
            return result

        size = make_size()
        self.assertEqual(run([size] * TIER2_THRESHOLD, [1]), 1)
        namespace = {"__builtins__": vars(builtins).copy()}
        namespace["__builtins__"]["len"] = lambda value: 42
        custom_size = types.FunctionType(make_size.__code__, namespace)()
        self.assertEqual(run([size, custom_size], [1]), 42)

    def test_global_guard_copied_namespace(self):
        namespace = {"Box": make_global_constant}
        exec("stable = Box()\n"
             "stable.value = 7\n"
             "def read(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n"
             "        total += stable.value\n"
             "    return total\n", namespace)
        read = namespace["read"]
        self.assertEqual(read(TIER2_THRESHOLD), 7 * TIER2_THRESHOLD)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn("_LOAD_GLOBAL_MODULE" if Py_GIL_DISABLED else
                      "_GUARD_GLOBALS_VERSION_AND_IDENTITY",
                      get_opnames(executor))

        copied = namespace.copy()
        copied["stable"] = namespace["Box"]()
        copied["stable"].value = 19
        alias = types.FunctionType(read.__code__, copied)
        self.assertEqual(alias(8), 152)
        self.assertEqual(read(8), 56)

    def _warm_named_global(self, unrelated):
        namespace = {unrelated: 0, "Box": make_global_constant}
        exec("stable = Box()\n"
             "stable.value = 7\n"
             "def read(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n"
             "        total += stable.value\n"
             "    return total\n", namespace)
        read = namespace["read"]
        self.assertEqual(read(TIER2_THRESHOLD), 7 * TIER2_THRESHOLD)
        executor = get_first_executor(read)
        self.assertIsNotNone(executor)
        self.assertIn("_LOAD_GLOBAL_MODULE" if Py_GIL_DISABLED else
                      "_GUARD_GLOBALS_VERSION_AND_IDENTITY",
                      get_opnames(executor))
        return read, executor, namespace

    def test_named_global_ignores_unrelated_replacements(self):
        # Bloom collisions may conservatively invalidate an executor, so try
        # several independent names and require at least one precise result.
        retained = False
        for attempt in range(8):
            name = f"unrelated_{attempt}"
            read, executor, namespace = self._warm_named_global(name)
            namespace[name] = 1
            self.assertEqual(read(8), 56)
            retained |= executor.is_valid()

            replacement = namespace["Box"]()
            replacement.value = 11
            namespace["stable"] = replacement
            self.assertEqual(executor.is_valid(), Py_GIL_DISABLED)
            self.assertEqual(read(8), 88)
        self.assertTrue(retained)

    def test_named_global_miss_cache_new_dependency(self):
        read, executor, namespace = self._warm_named_global("unrelated")
        # Repeated replacements can cache a negative dependency lookup.
        for value in range(20):
            namespace["unrelated"] = value
        exec("def read_other(n):\n"
             "    total = 0\n"
             "    for _ in range(n):\n"
             "        total += unrelated\n"
             "    return total\n", namespace)
        other = namespace["read_other"]
        self.assertEqual(other(TIER2_THRESHOLD), 19 * TIER2_THRESHOLD)
        dependent = get_first_executor(other)
        self.assertIsNotNone(dependent)
        namespace["unrelated"] = 23
        self.assertFalse(dependent.is_valid())
        self.assertEqual(other(8), 184)
        self.assertEqual(read(8), 56)

    def test_named_global_miss_cache_extended_dependency(self):
        read, executor, namespace = self._warm_named_global("unrelated")
        for value in range(20):
            namespace["unrelated"] = value
        # A Bloom collision may already have invalidated this executor.
        if not executor.is_valid():
            read(TIER2_THRESHOLD)
            executor = get_first_executor(read)
        _testinternalcapi.add_executor_dependency(executor, namespace)
        namespace["unrelated"] = 23
        self.assertFalse(executor.is_valid())
        self.assertEqual(read(8), 56)

    def test_named_global_stops_folding_mutating_binding(self):
        read, executor, namespace = self._warm_named_global("unrelated")
        warmup = TIER2_RESUME_THRESHOLD * 2
        for value in range(1, 9):
            replacement = namespace["Box"]()
            replacement.value = value
            constant = "_LOAD_GLOBAL_MODULE" not in get_opnames(executor)
            namespace["stable"] = replacement
            self.assertEqual(executor.is_valid(), not constant)
            self.assertEqual(read(warmup), value * warmup)
            executor = get_first_executor(read)
            self.assertIsNotNone(executor)
            self.assertTrue(executor.is_valid())
        self.assertIn("_LOAD_GLOBAL_MODULE",
                      get_opnames(executor))

    def test_named_global_structure_change_invalidates(self):
        read, executor, namespace = self._warm_named_global("unrelated")
        namespace["new_global"] = 1
        self.assertFalse(executor.is_valid())
        self.assertEqual(read(8), 56)

    def test_global_guard_namespace_lifetime(self):
        read, executor, namespace = self._warm_named_global("unrelated")
        original = weakref.ref(namespace["stable"])
        copied = namespace.copy()
        del copied["read"]
        copied["stable"] = namespace["Box"]()
        copied["stable"].value = 19
        alias = types.FunctionType(read.__code__, copied)

        del read, namespace
        gc.collect()
        self.assertIsNone(original())
        self.assertFalse(executor.is_valid())
        self.assertEqual(alias(8), 152)

    def test_named_global_general_key_invalidates(self):
        read, executor, namespace = self._warm_named_global("unrelated")

        class Key:
            def __hash__(self):
                return hash("stable")

            def __eq__(self, other):
                return other == "stable"

        replacement = namespace["Box"]()
        replacement.value = 23
        namespace[Key()] = replacement
        self.assertFalse(executor.is_valid())
        self.assertEqual(read(8), 184)

    def test_float_add_constant_propagation(self):
        def testfunc(n):
            a = 1.0
            for _ in range(n):
                a = a + 0.25
                a = a + 0.25
                a = a + 0.25
                a = a + 0.25
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertAlmostEqual(res, TIER2_THRESHOLD + 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_FLOAT"]
        guard_nos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_FLOAT"]
        self.assertLessEqual(len(guard_tos_float_count), 1)
        self.assertLessEqual(len(guard_nos_float_count), 1)
        # TODO gh-115506: this assertion may change after propagating constants.
        # We'll also need to verify that propagation actually occurs.
        self.assertIn("_POP_TOP_NOP", uops)

    def test_float_subtract_constant_propagation(self):
        def testfunc(n):
            a = 1.0
            for _ in range(n):
                a = a - 0.25
                a = a - 0.25
                a = a - 0.25
                a = a - 0.25
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertAlmostEqual(res, -TIER2_THRESHOLD + 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_FLOAT"]
        guard_nos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_FLOAT"]
        self.assertLessEqual(len(guard_tos_float_count), 1)
        self.assertLessEqual(len(guard_nos_float_count), 1)
        # TODO gh-115506: this assertion may change after propagating constants.
        # We'll also need to verify that propagation actually occurs.
        self.assertIn("_POP_TOP_NOP", uops)

    def test_float_multiply_constant_propagation(self):
        def testfunc(n):
            a = 1.0
            for _ in range(n):
                a = a * 1.0
                a = a * 1.0
                a = a * 1.0
                a = a * 1.0
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertAlmostEqual(res, 1.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_FLOAT"]
        guard_nos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_FLOAT"]
        self.assertLessEqual(len(guard_tos_float_count), 1)
        self.assertLessEqual(len(guard_nos_float_count), 1)
        # TODO gh-115506: this assertion may change after propagating constants.
        # We'll also need to verify that propagation actually occurs.
        self.assertIn("_POP_TOP_NOP", uops)

    def test_add_unicode_propagation(self):
        def testfunc(n):
            a = ""
            for _ in range(n):
                a + a
                a + a
                a + a
                a + a
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, "")
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_unicode_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_UNICODE"]
        guard_nos_unicode_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_UNICODE"]
        self.assertLessEqual(len(guard_tos_unicode_count), 1)
        self.assertLessEqual(len(guard_nos_unicode_count), 1)
        self.assertIn("_BINARY_OP_ADD_UNICODE", uops)

    def test_compare_op_type_propagation_float(self):
        def testfunc(n):
            a = 1.0
            for _ in range(n):
                x = a == a
                x = a == a
                x = a == a
                x = a == a
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertTrue(res)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_FLOAT"]
        guard_nos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_FLOAT"]
        self.assertLessEqual(len(guard_tos_float_count), 1)
        self.assertLessEqual(len(guard_nos_float_count), 1)
        self.assertIn("_COMPARE_OP_FLOAT", uops)

    def test_compare_op_type_propagation_int(self):
        def testfunc(n):
            a = 1
            for _ in range(n):
                x = a == a
                x = a == a
                x = a == a
                x = a == a
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertTrue(res)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_INT"]
        guard_nos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_INT"]
        self.assertLessEqual(len(guard_tos_int_count), 1)
        self.assertLessEqual(len(guard_nos_int_count), 1)
        self.assertIn("_COMPARE_OP_INT", uops)

    def test_compare_op_type_propagation_int_partial(self):
        def testfunc(n):
            a = 1
            for _ in range(n):
                if a > 2:
                    x = 0
                if a < 2:
                    x = 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_nos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_INT"]
        guard_tos_int_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_INT"]
        self.assertLessEqual(len(guard_nos_int_count), 1)
        self.assertEqual(len(guard_tos_int_count), 0)
        self.assertIn("_COMPARE_OP_INT", uops)

    def test_compare_op_type_propagation_float_partial(self):
        def testfunc(n):
            a = 1.0
            for _ in range(n):
                if a > 2.0:
                    x = 0
                if a < 2.0:
                    x = 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_nos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_FLOAT"]
        guard_tos_float_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_FLOAT"]
        self.assertLessEqual(len(guard_nos_float_count), 1)
        self.assertEqual(len(guard_tos_float_count), 0)
        self.assertIn("_COMPARE_OP_FLOAT", uops)

    def test_compare_op_type_propagation_unicode(self):
        def testfunc(n):
            a = ""
            for _ in range(n):
                x = a == a
                x = a == a
                x = a == a
                x = a == a
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertTrue(res)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        guard_tos_unicode_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_TOS_UNICODE"]
        guard_nos_unicode_count = [opname for opname in iter_opnames(ex) if opname == "_GUARD_NOS_UNICODE"]
        self.assertLessEqual(len(guard_tos_unicode_count), 1)
        self.assertLessEqual(len(guard_nos_unicode_count), 1)
        self.assertIn("_COMPARE_OP_STR", uops)

    def test_compare_int_eq_method_branches(self):
        def f(n, value=None):
            def return_1():
                return 1

            hits = 0
            v = return_1() if value is None else value
            for _ in range(n):
                if v == 1:
                    if v == 1:
                        hits += 1
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # OSR values are not constants. Both comparison branches remain
        # native until edge-sensitive constant propagation is implemented.
        self.assertEqual(count_ops(ex, "_COMPARE_OP_INT"), 2)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(f(3, 2), 0)


    def test_compare_int_ne_method_branches(self):
        def f(n, value=None):
            def return_1():
                return 1

            hits = 0
            v = return_1() if value is None else value
            for _ in range(n):
                if v != 1:
                    hits += 1000
                else:
                    if v == 1:
                        hits += v + 1
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # OSR values are not constants. Both comparison branches remain
        # native until edge-sensitive constant propagation is implemented.
        self.assertEqual(count_ops(ex, "_COMPARE_OP_INT"), 2)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(f(3, 2), 3000)


    def test_compare_float_eq_method_branches(self):
        def f(n, value=None):
            def return_tenth():
                return 0.1

            hits = 0
            v = return_tenth() if value is None else value
            for _ in range(n):
                if v == 0.1:
                    if v == 0.1:
                        hits += 1
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # OSR values are not constants. Both comparison branches remain
        # native until edge-sensitive constant propagation is implemented.
        self.assertEqual(count_ops(ex, "_COMPARE_OP_FLOAT"), 2)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(f(3, 0.2), 0)


    def test_compare_float_ne_method_branches(self):
        def f(n, value=None):
            def return_tenth():
                return 0.1

            hits = 0
            v = return_tenth() if value is None else value
            for _ in range(n):
                if v != 0.1:
                    hits += 1000
                else:
                    if v == 0.1:
                        hits += 1
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # OSR values are not constants. Both comparison branches remain
        # native until edge-sensitive constant propagation is implemented.
        self.assertEqual(count_ops(ex, "_COMPARE_OP_FLOAT"), 2)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(f(3, 0.2), 3000)


    def test_combine_stack_space_checks_sequential(self):
        def dummy12(x):
            return x - 1
        def dummy13(y):
            z = y + 2
            return y, z
        def testfunc(n):
            a = 0
            for _ in range(n):
                b = dummy12(7)
                c, d = dummy13(9)
                a += b + c + d
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 26)
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 2)
        # Whole-method CFG includes the outer function return.
        self.assertEqual(count_return_ops(uop_names), 3)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE"), 0)
        # Each call gets its own _CHECK_STACK_SPACE_OPERAND
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 2)
        # Each _CHECK_STACK_SPACE_OPERAND has the framesize of its function
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy12.__code__)), uops_and_operands)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy13.__code__)), uops_and_operands)

    def test_combine_stack_space_checks_nested(self):
        def dummy12(x):
            return x + 3
        def dummy15(y):
            z = dummy12(y)
            return y, z
        def testfunc(n):
            a = 0
            for _ in range(n):
                b, c = dummy15(2)
                a += b + c
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 7)
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 2)
        # Whole-method CFG includes the outer function return.
        self.assertEqual(count_return_ops(uop_names), 3)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE"), 0)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 2)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy15.__code__)), uops_and_operands)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy12.__code__)), uops_and_operands)

    def test_combine_stack_space_checks_several_calls(self):
        def dummy12(x):
            return x + 3
        def dummy13(y):
            z = y + 2
            return y, z
        def dummy18(y):
            z = dummy12(y)
            x, w = dummy13(z)
            return z, x, w
        def testfunc(n):
            a = 0
            for _ in range(n):
                b = dummy12(5)
                c, d, e = dummy18(2)
                a += b + c + d + e
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 25)
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 4)
        # Whole-method CFG includes the outer function return.
        self.assertEqual(count_return_ops(uop_names), 5)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE"), 0)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 4)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy12.__code__)), uops_and_operands)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy13.__code__)), uops_and_operands)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy18.__code__)), uops_and_operands)

    def test_combine_stack_space_checks_several_calls_different_order(self):
        # same as `several_calls` but with top-level calls reversed
        def dummy12(x):
            return x + 3
        def dummy13(y):
            z = y + 2
            return y, z
        def dummy18(y):
            z = dummy12(y)
            x, w = dummy13(z)
            return z, x, w
        def testfunc(n):
            a = 0
            for _ in range(n):
                c, d, e = dummy18(2)
                b = dummy12(5)
                a += b + c + d + e
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 25)
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 4)
        # Whole-method CFG includes the outer function return.
        self.assertEqual(count_return_ops(uop_names), 5)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE"), 0)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 4)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy12.__code__)), uops_and_operands)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy13.__code__)), uops_and_operands)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND",
                       _testinternalcapi.get_co_framesize(dummy18.__code__)), uops_and_operands)

    @unittest.skip("reopen when we combine multiple stack space checks into one")
    def test_combine_stack_space_complex(self):
        def dummy0(x):
            return x
        def dummy1(x):
            return dummy0(x)
        def dummy2(x):
            return dummy1(x)
        def dummy3(x):
            return dummy0(x)
        def dummy4(x):
            y = dummy0(x)
            return dummy3(y)
        def dummy5(x):
            return dummy2(x)
        def dummy6(x):
            y = dummy5(x)
            z = dummy0(y)
            return dummy4(z)
        def testfunc(n):
            a = 0
            for _ in range(n):
                b = dummy5(1)
                c = dummy0(1)
                d = dummy6(1)
                a += b + c + d
            return a

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 3)
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 15)
        self.assertEqual(count_return_ops(uop_names), 15)

        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE"), 0)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 1)
        largest_stack = (
            _testinternalcapi.get_co_framesize(dummy6.__code__) +
            _testinternalcapi.get_co_framesize(dummy5.__code__) +
            _testinternalcapi.get_co_framesize(dummy2.__code__) +
            _testinternalcapi.get_co_framesize(dummy1.__code__) +
            _testinternalcapi.get_co_framesize(dummy0.__code__)
        )
        self.assertIn(
            ("_CHECK_STACK_SPACE_OPERAND", largest_stack), uops_and_operands
        )

    @unittest.skip("reopen when we combine multiple stack space checks into one")
    def test_combine_stack_space_checks_large_framesize(self):
        # Create a function with a large framesize. This ensures _CHECK_STACK_SPACE is
        # actually doing its job. Note that the resulting trace hits
        # UOP_MAX_TRACE_LENGTH, but since all _CHECK_STACK_SPACEs happen early, this
        # test is still meaningful.
        repetitions = 10000
        ns = {}
        header = """
            def dummy_large(a0):
        """
        body = "".join([f"""
                a{n+1} = a{n} + 1
        """ for n in range(repetitions)])
        return_ = f"""
                return a{repetitions-1}
        """
        exec(textwrap.dedent(header + body + return_), ns, ns)
        dummy_large = ns['dummy_large']

        # this is something like:
        #
        # def dummy_large(a0):
        #     a1 = a0 + 1
        #     a2 = a1 + 1
        #     ....
        #     a9999 = a9998 + 1
        #     return a9999

        def dummy15(z):
            y = dummy_large(z)
            return y + 3

        def testfunc(n):
            b = 0
            for _ in range(n):
                b += dummy15(7)
            return b

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * (repetitions + 9))
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 2)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 1)

        # this hits a different case during trace projection in refcount test runs only,
        # so we need to account for both possibilities
        self.assertIn(uop_names.count("_CHECK_STACK_SPACE"), [0, 1])
        if uop_names.count("_CHECK_STACK_SPACE") == 0:
            largest_stack = (
                _testinternalcapi.get_co_framesize(dummy15.__code__) +
                _testinternalcapi.get_co_framesize(dummy_large.__code__)
            )
        else:
            largest_stack = _testinternalcapi.get_co_framesize(dummy15.__code__)
        self.assertIn(
            ("_CHECK_STACK_SPACE_OPERAND", largest_stack), uops_and_operands
        )

    @unittest.skip("reopen when we combine multiple stack space checks into one")
    def test_combine_stack_space_checks_recursion(self):
        def dummy15(x):
            while x > 0:
                return dummy15(x - 1)
            return 42
        def testfunc(n):
            a = 0
            for _ in range(n):
                a += dummy15(n)
            return a

        recursion_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(TIER2_THRESHOLD + recursion_limit)
            res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        finally:
            sys.setrecursionlimit(recursion_limit)
        self.assertEqual(res, TIER2_THRESHOLD * 42)
        self.assertIsNotNone(ex)

        uops_and_operands = [(opcode, operand) for opcode, _, _, operand in ex]
        uop_names = [uop[0] for uop in uops_and_operands]
        self.assertEqual(uop_names.count("_PUSH_FRAME"), 2)
        self.assertEqual(count_return_ops(uop_names), 0)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE"), 1)
        self.assertEqual(uop_names.count("_CHECK_STACK_SPACE_OPERAND"), 1)
        largest_stack = _testinternalcapi.get_co_framesize(dummy15.__code__)
        self.assertIn(("_CHECK_STACK_SPACE_OPERAND", largest_stack), uops_and_operands)

    def test_many_nested(self):
        # overflow the trace_stack
        def dummy_a(x):
            return x
        def dummy_b(x):
            return dummy_a(x)
        def dummy_c(x):
            return dummy_b(x)
        def dummy_d(x):
            return dummy_c(x)
        def dummy_e(x):
            return dummy_d(x)
        def dummy_f(x):
            return dummy_e(x)
        def dummy_g(x):
            return dummy_f(x)
        def dummy_h(x):
            return dummy_g(x)
        def testfunc(n):
            a = 0
            for _ in range(n):
                a += dummy_h(n)
            return a

        res, ex = self._run_with_optimizer(testfunc, 32)
        self.assertEqual(res, 32 * 32)
        self.assertIsNone(ex)

    def test_return_generator(self):
        def gen():
            yield None
        def testfunc(n):
            for i in range(n):
                gen()
            return i
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD - 1)
        self.assertIsNotNone(ex)
        self.assertIn("_METHOD_CALL", get_opnames(ex))
        self.assertNotIn("_RETURN_GENERATOR", get_opnames(ex))
        self.assertEqual(list(gen()), [None])
        self.assertIsNone(get_first_executor(gen))

    def test_make_heap_safe_after_constant_return_call(self):
        def returns_immortal():
            return None
        def testfunc(n):
            a = 0
            for _ in range(n):
                a = returns_immortal()
            return a
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNone(res)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME" if Py_GIL_DISABLED else
                      "_CALL_RETURN_CONSTANT", uops)
        self.assertIn("_MAKE_HEAP_SAFE", uops)
        self.assertGreater(count_return_ops(uops), 0)

    def test_generator_yields_immortal_to_tier1_caller(self):
        def gen(n):
            for _ in range(n):
                yield 1
        def testfunc(n):
            total = 0
            for value in gen(n):
                total += value
            return total
        self.assertEqual(testfunc(TIER2_THRESHOLD * 2), TIER2_THRESHOLD * 2)
        # The compiled loop suspends and resumes its Tier 1 caller directly.
        self.assertIsNotNone(get_first_executor(gen))
        self.assertIn('_YIELD_VALUE', get_opnames(get_first_executor(gen)))
        self.assertIn('_METHOD_YIELD_EXIT', get_opnames(get_first_executor(gen)))

    def test_make_heap_safe_not_optimized_for_owned(self):
        def returns_owned(x):
            return x + 1
        def testfunc(n):
            a = 0
            for _ in range(n):
                a = returns_owned(a)
            return a
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_MAKE_HEAP_SAFE", uops)
        self.assertGreater(count_return_ops(uops), 0)

    def test_for_iter(self):
        def testfunc(n):
            t = 0
            for i in set(range(n)):
                t += i
            return t
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * (TIER2_THRESHOLD - 1) // 2)
        self.assertIsNotNone(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", get_opnames(ex))

    def test_for_iter_osr_dict_items(self):
        def testfunc(n):
            d = {i: i * 2 for i in range(10)}
            total = 0
            for _ in range(n):
                for k, v in d.items():
                    total += k + v
            return total

        expected = 0
        d = {i: i * 2 for i in range(10)}
        for _ in range(TIER2_THRESHOLD):
            for k, v in d.items():
                expected += k + v

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_for_iter_osr_dict_keys(self):
        def testfunc(n):
            d = {i: i for i in range(10)}
            total = 0
            for _ in range(n):
                for k in d.keys():
                    total += k
            return total

        expected = TIER2_THRESHOLD * sum(range(10))
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_for_iter_osr_dict_values(self):
        def testfunc(n):
            d = {i: i * 3 for i in range(10)}
            total = 0
            for _ in range(n):
                for v in d.values():
                    total += v
            return total

        expected = TIER2_THRESHOLD * sum(i * 3 for i in range(10))
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_for_iter_osr_set(self):
        def testfunc(n):
            s = set(range(10))
            total = 0
            for _ in range(n):
                for x in s:
                    total += x
            return total

        expected = TIER2_THRESHOLD * sum(range(10))
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_for_iter_osr_reversed(self):
        def testfunc(n):
            lst = list(range(10))
            total = 0
            for _ in range(n):
                for x in reversed(lst):
                    total += x
            return total

        expected = TIER2_THRESHOLD * sum(range(10))
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_for_iter_osr_enumerate(self):
        def testfunc(n):
            lst = list(range(10))
            total = 0
            for _ in range(n):
                for i, x in enumerate(lst):
                    total += i + x
            return total

        expected = TIER2_THRESHOLD * sum(i + x for i, x in enumerate(range(10)))
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_for_iter_osr_zip(self):
        def testfunc(n):
            a = list(range(10))
            b = list(range(10, 20))
            total = 0
            for _ in range(n):
                for x, y in zip(a, b):
                    total += x + y
            return total

        expected = TIER2_THRESHOLD * sum(x + y for x, y in zip(range(10), range(10, 20)))
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The live OSR iterator has no recorded type; use the generic path.
        self.assertIn("_METHOD_FOR_ITER", uops)
        self.assertNotIn("_FOR_ITER_TIER_TWO", uops)

    def test_modified_local_is_seen_by_optimized_code(self):
        l = sys._getframe().f_locals
        a = 1
        s = 0
        for j in range(1 << 10):
            a + a
            l["xa"[j >> 9]] = 1.0
            s += a
        self.assertIs(type(a), float)
        self.assertIs(type(s), float)
        self.assertEqual(s, 1024.0)

    def test_guard_type_version_removed(self):
        def thing(a):
            x = 0
            for _ in range(TIER2_THRESHOLD):
                x += a.attr
                x += a.attr
            return x

        class Foo:
            attr = 1

        res, ex = self._run_with_optimizer(thing, Foo())
        opnames = list(iter_opnames(ex))
        self.assertIsNotNone(ex)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        guard_type_version_count = opnames.count("_GUARD_TYPE_VERSION")
        self.assertEqual(guard_type_version_count, 1)

    def test_guard_type_version_removed_inlined(self):
        """
        Verify that the guard type version if we have an inlined function
        """

        def fn():
            pass

        def thing(a):
            x = 0
            for _ in range(TIER2_THRESHOLD):
                x += a.attr
                fn()
                x += a.attr
            return x

        class Foo:
            attr = 1

        res, ex = self._run_with_optimizer(thing, Foo())
        opnames = list(iter_opnames(ex))
        self.assertIsNotNone(ex)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        guard_type_version_count = opnames.count("_GUARD_TYPE_VERSION")
        self.assertEqual(guard_type_version_count, 2 if Py_GIL_DISABLED else 1)

    def test_guard_type_version_removed_invalidation(self):

        def thing(a):
            x = 0
            for i in range(TIER2_THRESHOLD + 1):
                x += a.attr
                # The first TIER2_THRESHOLD iterations we set the attribute on
                # this dummy class, which shouldn't trigger the type watcher.
                # Note that the code needs to be in this weird form so it's
                # optimized inline without any control flow:
                setattr((Bar, Foo)[i == TIER2_THRESHOLD + 1], "attr", 2)
                x += a.attr
            return x

        class Foo:
            attr = 1

        class Bar:
            pass

        res, ex = self._run_with_optimizer(thing, Foo())
        opnames = list(iter_opnames(ex))
        self.assertEqual(res, TIER2_THRESHOLD * 2 + 2)
        call = opnames.index("_CALL_BUILTIN_FAST")
        loads = [i for i, op in enumerate(opnames)
                 if op.startswith("_LOAD_ATTR_NONDESCRIPTOR_")]
        load_attr_top = next(i for i in loads if i < call)
        load_attr_bottom = next(i for i in loads if i > call)
        self.assertEqual(opnames[:load_attr_top].count("_GUARD_TYPE_VERSION"), 1)
        self.assertGreaterEqual(opnames[call:load_attr_bottom].count("_CHECK_VALIDITY"), 1)

    def test_guard_type_version_removed_escaping(self):

        def thing(a):
            x = 0
            for i in range(TIER2_THRESHOLD):
                x += a.attr
                # eval should be escaping
                eval("None")
                x += a.attr
            return x

        class Foo:
            attr = 1
        res, ex = self._run_with_optimizer(thing, Foo())
        opnames = list(iter_opnames(ex))
        self.assertIsNotNone(ex)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        call = opnames.index("_CALL_BUILTIN_FAST_WITH_KEYWORDS")
        loads = [i for i, op in enumerate(opnames)
                 if op.startswith("_LOAD_ATTR_NONDESCRIPTOR_")]
        load_attr_top = next(i for i in loads if i < call)
        load_attr_bottom = next(i for i in loads if i > call)
        self.assertEqual(opnames[:load_attr_top].count("_GUARD_TYPE_VERSION"), 1)
        self.assertGreaterEqual(opnames[call:load_attr_bottom].count("_CHECK_VALIDITY"), 1)

    def test_guard_type_version_executor_invalidated(self):
        """
        Verify that the executor is invalided on a type change.
        """

        def thing(a):
            x = 0
            for i in range(TIER2_THRESHOLD):
                x += a.attr
                x += a.attr
            return x

        class Foo:
            attr = 1

        res, ex = self._run_with_optimizer(thing, Foo())
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        self.assertIsNotNone(ex)
        self.assertEqual(list(iter_opnames(ex)).count("_GUARD_TYPE_VERSION"), 1)
        self.assertTrue(ex.is_valid())
        Foo.attr = 0
        self.assertFalse(ex.is_valid())

    def test_guard_type_version_locked_removed(self):
        """
        Verify that redundant _GUARD_TYPE_VERSION_LOCKED guards are
        eliminated for sequential STORE_ATTR_INSTANCE_VALUE in __init__.
        """

        class Foo:
            def __init__(self):
                self.a = 1
                self.b = 2
                self.c = 3

        def thing(n):
            for _ in range(n):
                value = Foo()
            return value

        res, ex = self._run_with_optimizer(thing, TIER2_THRESHOLD)
        self.assertEqual((res.a, res.b, res.c), (1, 2, 3))
        self.assertIsNotNone(ex)
        opnames = list(iter_opnames(ex))
        guard_locked_count = sum(op in ("_GUARD_TYPE_VERSION_LOCKED",
                                       "_STORE_CONST_ATTRIBUTE_1",
                                       "_STORE_CONST_ATTRIBUTE_3") for op in opnames)
        # Only the first store needs the guard; the rest should be NOPed.
        if Py_GIL_DISABLED:
            self.assertIn("_CREATE_INIT_FRAME", opnames)
        else:
            self.assertEqual(guard_locked_count, 1)

    def test_type_version_doesnt_segfault(self):
        """
        Tests that setting a type version doesn't cause a segfault when later looking at the stack.
        """

        # Minimized from mdp.py benchmark

        class A:
            def __init__(self):
                self.attr = {}

            def method(self, arg):
                self.attr[arg] = None

        def fn(a):
            for _ in range(100):
                (_ for _ in [])
                (_ for _ in [a.method(None)])

        fn(A())

    def test_init_resolves_callable(self):
        """
        _CHECK_AND_ALLOCATE_OBJECT should resolve __init__ to a constant,
        enabling the optimizer to propagate type information through the frame
        and eliminate redundant function version and arg count checks.
        """
        class MyPoint:
            def __init__(self, x, y):
                # If __init__ callable is propagated through, then
                # These will get promoted from globals to constants.
                self.x = range(1)
                self.y = range(1)

        def testfunc(n):
            for _ in range(n):
                p = MyPoint(1.0, 2.0)

        _, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The __init__ call should be traced through via _PUSH_FRAME
        self.assertIn("_PUSH_FRAME", uops)
        # __init__ resolution allows promotion of range to constant
        self.assertNotIn("_LOAD_GLOBAL_BUILTINS", uops)

    def test_init_frames_checked(self):
        class MyPoint:
            def __init__(self, x, y):
                return None

        def testfunc(n):
            point_local = MyPoint
            for _ in range(n):
                p = point_local(1.0, 2.0)
                p = point_local(1.0, 2.0)
            return p

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsInstance(res, MyPoint)
        self.assertIsNotNone(ex)
        # Both calls preserve their initializer frames.
        count = count_ops(ex, "_CREATE_INIT_FRAME")
        self.assertEqual(count, 2)
        self.assertGreaterEqual(count_ops(ex, "_CHECK_OBJECT"), 1)


    def test_init_frames_checked_global(self):

        def testfunc(n):
            for _ in range(n):
                p = MyGlobalPoint(1.0, 2.0)
                p = MyGlobalPoint(1.0, 2.0)
            return p

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsInstance(res, MyGlobalPoint)
        self.assertIsNotNone(ex)
        # Both calls preserve their initializer frames.
        count = count_ops(ex, "_CREATE_INIT_FRAME")
        self.assertEqual(count, 2)
        self.assertGreaterEqual(count_ops(ex, "_CHECK_OBJECT"), 1)


    def test_attribute_return_and_inlined_method_guards(self):
        class Item:
            def __init__(self, val):
                self.val = val

            def get(self):
                return self.val

            def get2(self):
                return self.val + 1

        def testfunc(n):
            item = Item(42)
            total = 0
            for _ in range(n):
                # Two method calls on the same object — the second
                # should benefit from type info set by the first.
                total += item.get() + item.get2()
            return total

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * (42 + 43))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertEqual(uops.count("_CALL_RETURN_ATTRIBUTE"),
                         0 if Py_GIL_DISABLED else 1)
        self.assertEqual(uops.count("_PUSH_FRAME"),
                         2 if Py_GIL_DISABLED else 1)
        # The attribute-return call does not propagate receiver facts.
        self.assertEqual(uops.count("_GUARD_TYPE_VERSION"),
                         4 if Py_GIL_DISABLED else 2)
        # Function checks cannot be eliminated for safety reasons.
        self.assertIn("_CHECK_FUNCTION_VERSION", uops)
        Item.get.__code__ = (lambda self: 10).__code__
        self.assertEqual(testfunc(3), 3 * (10 + 43))


    def test_method_chain_checks_returned_receiver(self):
        class Calc:
            def __init__(self, val):
                self.val = val

            def add(self, x):
                self.val += x
                return self

        def testfunc(n):
            c = Calc(0)
            for _ in range(n):
                c.add(1).add(2)
            return c.val

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # Both add() calls should be inlined
        push_count = uops.count("_PUSH_FRAME")
        self.assertEqual(push_count, 2)
        # The second receiver is a call result with unknown type.
        self.assertGreaterEqual(uops.count("_GUARD_TYPE_VERSION"), 2)


    def test_func_guards_removed_or_reduced(self):
        def testfunc(n):
            for i in range(n):
                # Only works on functions promoted to constants
                global_identity(i)

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME" if Py_GIL_DISABLED else
                      "_CALL_RETURN_ARGUMENT", uops)
        self.assertIn("_CHECK_FUNCTION_VERSION", uops)
        # Removed guard
        self.assertNotIn("_CHECK_FUNCTION_EXACT_ARGS", uops)

    def test_method_guards_removed_or_reduced(self):
        def testfunc(n):
            result = 0
            for i in range(n):
                result += test_bound_method(i)
            return result
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, sum(range(TIER2_THRESHOLD)))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        if Py_GIL_DISABLED:
            self.assertIn("_CHECK_METHOD_VERSION", uops)
        else:
            self.assertIn("_CHECK_FUNCTION_VERSION_INLINE", uops)
            self.assertNotIn("_CHECK_METHOD_VERSION", uops)


    def test_record_bound_method_general(self):
        class MyClass:
            def method(self, *args):
                return args[0] + 1

        def testfunc(n):
            obj = MyClass()
            bound = obj.method
            result = 0
            for i in range(n):
                result += bound(i)
            return result

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(
            res, sum(i + 1 for i in range(TIER2_THRESHOLD))
        )
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)

    def test_record_bound_method_exact_args(self):
        class MyClass:
            def method(self, x):
                return x + 1

        def testfunc(n):
            obj = MyClass()
            bound = obj.method
            result = 0
            for i in range(n):
                result += bound(i)
            return result

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(
            res, sum(i + 1 for i in range(TIER2_THRESHOLD))
        )
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertNotIn("_CHECK_FUNCTION_EXACT_ARGS", uops)

    def test_jit_error_pops(self):
        """
        Tests that the correct number of pops are inserted into the
        exit stub
        """
        items = 17 * [None] + [[]]
        with self.assertRaises(TypeError):
            {item for item in items}

    def test_power_type_depends_on_input_values(self):
        template = textwrap.dedent("""
            import _testinternalcapi

            L, R, X, Y = {l}, {r}, {x}, {y}

            def check(actual: complex, expected: complex) -> None:
                assert actual == expected, (actual, expected)
                assert type(actual) is type(expected), (actual, expected)

            def f(l: complex, r: complex) -> None:
                expected_local_local = pow(l, r) + pow(l, r)
                expected_const_local = pow(L, r) + pow(L, r)
                expected_local_const = pow(l, R) + pow(l, R)
                expected_const_const = pow(L, R) + pow(L, R)
                for _ in range(_testinternalcapi.TIER2_THRESHOLD):
                    # Narrow types:
                    l + l, r + r
                    # The powers produce results, and the addition is unguarded:
                    check(l ** r + l ** r, expected_local_local)
                    check(L ** r + L ** r, expected_const_local)
                    check(l ** R + l ** R, expected_local_const)
                    check(L ** R + L ** R, expected_const_const)

            # JIT for one pair of values...
            f(L, R)
            # ...then run with another:
            f(X, Y)
        """)
        interesting = [
            (1, 1),  # int ** int -> int
            (1, -1),  # int ** int -> float
            (1.0, 1),  # float ** int -> float
            (1, 1.0),  # int ** float -> float
            (-1, 0.5),  # int ** float -> complex
            (1.0, 1.0),  # float ** float -> float
            (-1.0, 0.5),  # float ** float -> complex
        ]
        for (l, r), (x, y) in itertools.product(interesting, repeat=2):
            s = template.format(l=l, r=r, x=x, y=y)
            with self.subTest(l=l, r=r, x=x, y=y):
                script_helper.assert_python_ok("-c", s)

    def test_symbols_flow_through_tuples(self):
        def testfunc(n):
            for _ in range(n):
                a = 1
                b = 2
                t = a, b
                x, y = t
                r = x + y
            return r

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_BINARY_OP_ADD_INT", uops)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        self.assertNotIn("_GUARD_TOS_INT", uops)

    def test_decref_escapes(self):
        class Convert9999ToNone:
            def __del__(self):
                ns = sys._getframe(1).f_locals
                if ns["i"] == _testinternalcapi.TIER2_THRESHOLD:
                    ns["i"] = None

        def crash_addition():
            try:
                for i in range(_testinternalcapi.TIER2_THRESHOLD + 1):
                    n = Convert9999ToNone()
                    i + i  # Remove guards for i.
                    n = None  # Change i.
                    i + i  # This crashed when we didn't treat DECREF as escaping (gh-124483)
            except TypeError:
                pass

        crash_addition()

    def test_bool_false_method_branches(self):
        def f(n):
            trace = []
            for i in range(n):
                # false is always False, but we can only prove that it's a bool:
                false = i == TIER2_THRESHOLD
                trace.append("A")
                if not false:
                    trace.append("B")
                    if not false:
                        trace.append("C")
                    trace.append("D")
                    if false:
                        trace.append("X")
                    trace.append("E")
                trace.append("F")
                if false:
                    trace.append("X")
                trace.append("G")
            return trace

        trace, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(trace, list("ABCDEFG") * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The unvisited branch is part of the static CFG as well.
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertGreaterEqual(uops.count("_CALL_LIST_APPEND"), len("ABCDEFG"))
        self.assertEqual(f(TIER2_THRESHOLD + 1),
                         list("ABCDEFG") * TIER2_THRESHOLD + list("AFXG"))


    def test_bool_true_method_branches(self):
        def f(n):
            trace = []
            for i in range(n):
                # true always True, but we can only prove that it's a bool:
                true = i != TIER2_THRESHOLD
                trace.append("A")
                if true:
                    trace.append("B")
                    if not true:
                        trace.append("X")
                    trace.append("C")
                    if true:
                        trace.append("D")
                    trace.append("E")
                trace.append("F")
                if not true:
                    trace.append("X")
                trace.append("G")
            return trace

        trace, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(trace, list("ABCDEFG") * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The unvisited branch is part of the static CFG as well.
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertGreaterEqual(uops.count("_CALL_LIST_APPEND"), len("ABCDEFG"))
        self.assertEqual(f(TIER2_THRESHOLD + 1),
                         list("ABCDEFG") * TIER2_THRESHOLD + list("AFXG"))


    def test_int_zero_method_branches(self):
        def f(n):
            trace = []
            for i in range(n):
                # zero is always (int) 0, but we can only prove that it's a integer:
                false = i == TIER2_THRESHOLD # this will always be false, while hopefully still fooling optimizer improvements
                zero = false + 0 # this should always set the variable zero equal to 0
                trace.append("A")
                if not zero:
                    trace.append("B")
                    if not zero:
                        trace.append("C")
                    trace.append("D")
                    if zero:
                        trace.append("X")
                    trace.append("E")
                trace.append("F")
                if zero:
                    trace.append("X")
                trace.append("G")
            return trace

        trace, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(trace, list("ABCDEFG") * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The unvisited branch is part of the static CFG as well.
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertGreaterEqual(uops.count("_CALL_LIST_APPEND"), len("ABCDEFG"))
        self.assertEqual(f(TIER2_THRESHOLD + 1),
                         list("ABCDEFG") * TIER2_THRESHOLD + list("AFXG"))


    def test_str_empty_method_branches(self):
        def f(n):
            trace = []
            for i in range(n):
                # Hopefully the optimizer can't guess what the value is.
                # empty is always "", but we can only prove that it's a string:
                false = i == TIER2_THRESHOLD
                empty = "X"[:false]
                trace.append("A")
                if not empty:
                    trace.append("B")
                    if not empty:
                        trace.append("C")
                    trace.append("D")
                    if empty:
                        trace.append("X")
                    trace.append("E")
                trace.append("F")
                if empty:
                    trace.append("X")
                trace.append("G")
            return trace

        trace, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(trace, list("ABCDEFG") * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The unvisited branch is part of the static CFG as well.
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertGreaterEqual(uops.count("_CALL_LIST_APPEND"), len("ABCDEFG"))
        self.assertEqual(f(TIER2_THRESHOLD + 1),
                         list("ABCDEFG") * TIER2_THRESHOLD + list("AFXG"))


    def test_unary_negative_pop_top_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for i in range(n):
                a = 1
                result = -a
                if result < 0:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_UNARY_NEGATIVE", uops)

    def test_unary_not_pop_top_load_const_inline_borrow(self):
        def testfunc(n):
                x = 0
                for i in range(n):
                    a = 42
                    result = not a
                    if result:
                        x += 1
                return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_UNARY_NOT", uops)
        # TODO (gh-143723): After refactoring TO_BOOL_INT to eliminate redundant
        # refcounts, 'not a' is now constant-folded and currently lowered to
        # _POP_TOP + _LOAD_CONST_INLINE_BORROW. Re-enable once constant folding
        # avoids emitting these.
        # self.assertNotIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_unary_invert_insert_1_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for i in range(n):
                a = 0
                result = ~a
                if result < 0:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_UNARY_INVERT", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_compare_op_pop_two_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                a = 10
                b = 10.0
                if a == b:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_COMPARE_OP", uops)

    def test_compare_op_int_insert_two_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                a = 10
                b = 10
                if a == b:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_COMPARE_OP_INT", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_compare_op_str_insert_two_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                a = "foo"
                b = "foo"
                if a == b:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_COMPARE_OP_STR", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_compare_op_float_insert_two_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                a = 1.0
                b = 1.0
                if a == b:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_COMPARE_OP_FLOAT", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_contains_op_pop_two_load_const_inline_borrow(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                a = "foo"
                s = "foo bar baz"
                if a in s:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CONTAINS_OP", uops)

    def test_to_bool_bool_contains_op_set(self):
        """
        Test that _TO_BOOL_BOOL is removed from code like:

        res = foo in some_set
        if res:
            ....

        """
        def testfunc(n):
            x = 0
            s = {1, 2, 3}
            for _ in range(n):
                a = 2
                in_set = a in s
                if in_set:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CONTAINS_OP_SET", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)

    def test_to_bool_bool_contains_op_dict(self):
        """
        Test that _TO_BOOL_BOOL is removed from code like:

        res = foo in some_dict
        if res:
            ....

        """
        def testfunc(n):
            x = 0
            s = {1: 1, 2: 2, 3: 3}
            for _ in range(n):
                a = 2
                in_dict = a in s
                if in_dict:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CONTAINS_OP_DICT", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)

    def test_remove_guard_for_known_type_str(self):
        def f(n):
            for i in range(n):
                false = i == TIER2_THRESHOLD
                empty = "X"[:false]
                if empty:
                    return 1
            return 0

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_TO_BOOL_STR", uops)
        self.assertNotIn("_GUARD_TOS_UNICODE", uops)

    def test_new_dict_subscript_guards(self):
        def f(n):
            x = 0
            for _ in range(n):
                d = {}
                d["Spam"] = 1
                x += d["Spam"]
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertEqual(uops.count("_GUARD_NOS_DICT_SUBSCRIPT"), 1)
        self.assertEqual(uops.count("_GUARD_NOS_DICT_STORE_SUBSCRIPT"), 1)
        self.assertEqual(uops.count("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH"), 1)

    def test_dict_subclass_subscr(self):
        import collections

        def f(n):
            x = 0
            d = collections.defaultdict(int)
            for _ in range(n):
                d["key"] = 1
                x += d["key"]
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertEqual(uops.count("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH"), 1)
        self.assertEqual(uops.count("_STORE_SUBSCR_DICT_KNOWN_HASH"), 1)
        self.assertEqual(uops.count("_GUARD_NOS_DICT_SUBSCRIPT"), 1)
        self.assertEqual(uops.count("_GUARD_NOS_DICT_STORE_SUBSCRIPT"), 1)
        self.assertNotIn("_GUARD_NOS_TYPE", uops)

    def test_dict_subclass_guards_receiver(self):
        class HashableDict(dict):
            __hash__ = object.__hash__

        key = HashableDict()
        receiver = HashableDict({key: 1})

        def read(n):
            for _ in range(n):
                value = receiver[key]
            return value

        def write(n):
            for _ in range(n):
                receiver[key] = 2

        for func, guard in ((read, "_GUARD_NOS_DICT_SUBSCRIPT"),
                            (write, "_GUARD_NOS_DICT_STORE_SUBSCRIPT")):
            _, ex = self._run_with_optimizer(func, TIER2_THRESHOLD)
            self.assertIsNotNone(ex)
            self.assertIn(guard, get_opnames(ex))

        # The key has the same type as the original receiver, but is not the receiver.
        # Guarding TOS would incorrectly admit a non-dict to the dict uop.
        stores = []
        class Other:
            def __getitem__(self, sub):
                assert sub is key
                return 42

            def __setitem__(self, sub, value):
                stores.append((sub, value))

        receiver = Other()
        self.assertEqual(read(8), 42)
        write(8)
        self.assertEqual(stores, [(key, 2)] * 8)

    def test_method_descriptor_subclass_calls(self):
        cases = (
            ("receiver.append(1)", "_CALL_METHOD_DESCRIPTOR_O"),
            ("receiver.copy()", "_CALL_METHOD_DESCRIPTOR_NOARGS"),
            ("receiver.count(1)", "_CALL_METHOD_DESCRIPTOR_O"),
            ("receiver.index(1)", "_CALL_METHOD_DESCRIPTOR_FAST"),
            ("receiver.sort()", "_CALL_METHOD_DESCRIPTOR_FAST_WITH_KEYWORDS"),
        )
        for expression, opcode in cases:
            for unbound in (False, True):
                with self.subTest(expression=expression, unbound=unbound):
                    class MyList(list):
                        pass
                    receiver = MyList([3, 1, 2])
                    call = expression
                    if unbound:
                        method_call = expression.removeprefix("receiver.")
                        name, args = method_call.split("(", 1)
                        separator = ", " if args != ")" else ""
                        call = f"list.{name}(receiver{separator}{args}"
                    namespace = {}
                    exec("def run(receiver, n):\n"
                         "    for _ in range(n):\n"
                         f"        result = {call}\n"
                         "    return result\n", namespace)
                    run = namespace["run"]
                    run(receiver, TIER2_THRESHOLD)
                    ex = get_first_executor(run)
                    self.assertIsNotNone(ex)
                    self.assertTrue(
                        any(
                            name == opcode or name == opcode + "_INLINE"
                            for name in get_opnames(ex)
                        ),
                        get_opnames(ex),
                    )
                    reference = MyList(receiver)
                    expected = eval(expression, {"receiver": reference})
                    self.assertEqual(run(receiver, 1), expected)
                    self.assertEqual(receiver, reference)

    def test_method_descriptor_subclass_override_and_error(self):
        class MyList(list):
            pass

        def copy(receiver, n):
            for _ in range(n):
                result = receiver.copy()
            return result

        copy(MyList([1]), TIER2_THRESHOLD)
        self.assertIn("_CALL_METHOD_DESCRIPTOR_NOARGS_INLINE" if Py_GIL_DISABLED else
                      "_CALL_METHOD_DESCRIPTOR_NOARGS",
                      get_opnames(get_first_executor(copy)))
        MyList.copy = lambda self: "overridden"
        self.assertEqual(copy(MyList([1]), 8), "overridden")

        def pop(receiver, n):
            for _ in range(n):
                result = list.pop(receiver)
            return result

        pop(MyList(range(TIER2_THRESHOLD)), TIER2_THRESHOLD)
        ex = get_first_executor(pop)
        self.assertIsNotNone(ex)
        self.assertTrue(any(name.startswith("_CALL_METHOD_DESCRIPTOR_FAST")
                            for name in get_opnames(ex)), get_opnames(ex))
        with self.assertRaises(TypeError):
            pop({}, 8)
        receiver = MyList([1])
        try:
            pop(receiver, 8)
        except IndexError as error:
            self.assertEqual(str(error), "pop from empty list")
            tb = error.__traceback__
            while tb.tb_frame.f_code is not pop.__code__:
                tb = tb.tb_next
            self.assertEqual(tb.tb_lineno, pop.__code__.co_firstlineno + 2)
        else:
            self.fail("empty-list error was skipped")
        self.assertEqual(receiver, [])

    def test_dict_subclass_subscr_with_override(self):
        class MyDict(dict):
            def __getitem__(self, key):
                return 42

        def f(n):
            d = MyDict()
            x = 0
            for _ in range(n):
                x += d["anything"]
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 42 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_METHOD_DEOPT" if Py_GIL_DISABLED else
                      "_BINARY_OP_SUBSCR_INIT_CALL", uops)

    def test_remove_guard_for_known_type_list(self):
        def f(n):
            x = 0
            for _ in range(n):
                l = [0]
                l[0] = 1  # unguarded!
                [a] = l  # ...unguarded!
                b = l[0]  # ...unguarded!
                if l:  # ...unguarded!
                    x += a + b
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 2 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertEqual(uops.count("_GUARD_NOS_LIST"), 0)
        self.assertEqual(uops.count("_STORE_SUBSCR_LIST_INT"), 1)
        self.assertEqual(uops.count("_GUARD_TOS_LIST"), 0)
        self.assertEqual(uops.count("_UNPACK_SEQUENCE_LIST"), 1)
        self.assertEqual(uops.count("_BINARY_OP_SUBSCR_LIST_CONST"), 1)
        self.assertEqual(uops.count("_TO_BOOL_LIST"), 1)

    def test_constant_list_index_checks_current_size(self):
        self.addCleanup(_testinternalcapi.clear_executor_deletion_list)
        marker = object()
        sequence = [marker, None, marker]

        def read(n):
            result = None
            for _ in range(n):
                result = sequence[2]
            return result

        self.enterContext(clear_executors(read))
        result, executor = self._run_with_optimizer(read, TIER2_THRESHOLD)
        self.assertIs(result, marker)
        self.assertIn("_BINARY_OP_SUBSCR_LIST_CONST", get_opnames(executor))
        sequence[2] = replacement = object()
        self.assertIs(read(10), replacement)
        sequence.pop()
        with self.assertRaises(IndexError):
            read(10)
        sequence.clear()
        with self.assertRaises(IndexError):
            read(10)
        sequence.extend([None, None, marker])
        self.assertIs(read(10), marker)

        class CustomList(list):
            def __getitem__(self, index):
                return index

        sequence = CustomList()
        self.assertEqual(read(10), 2)

    def test_returned_four_tuple_unpack(self):
        def f(n):
            def four_tuple(x):
                return (x, x, x, x)
            hits = 0
            for i in range(n):
                w, x, y, z = four_tuple(1)
                hits += w + x + y + z
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 4)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_TUPLE", uops)
        self.assertIn("_UNPACK_TUPLE_TO_FAST_4", uops)
        self.assertIn("_GUARD_TOS_TUPLE", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_TUPLE", uops)

    def test_non_unique_tuple_unpack(self):
        def f(n):
            def four_tuple(x):
                return (x, x, x, x)
            hits = 0
            for i in range(n):
                t = four_tuple(1)
                w, x, y, z = t
                hits += w + x + y + z
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 4)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_TUPLE", uops)
        self.assertIn("_UNPACK_TUPLE_TO_FAST_4", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_UNIQUE_TUPLE", uops)

    def test_returned_three_tuple_unpack(self):
        def f(n):
            def three_tuple(x):
                return (x, x, x)
            hits = 0
            for i in range(n):
                x, y, z = three_tuple(1)
                hits += x + y + z
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_TUPLE", uops)
        self.assertIn("_UNPACK_TUPLE_TO_FAST_3", uops)
        self.assertIn("_GUARD_TOS_TUPLE", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_TUPLE", uops)

    def test_stored_returned_three_tuple_unpack(self):
        def f(n):
            def three_tuple(x):
                return (x, x, x)
            hits = 0
            for i in range(n):
                t = three_tuple(1)
                x, y, z = t
                hits += x + y + z
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_TUPLE", uops)
        self.assertIn("_UNPACK_TUPLE_TO_FAST_3", uops)
        self.assertIn("_GUARD_TOS_TUPLE", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_UNIQUE_THREE_TUPLE", uops)

    def test_returned_two_tuple_unpack(self):
        def f(n):
            def two_tuple(x):
                return (x, x)
            hits = 0
            for i in range(n):
                x, y = two_tuple(1)
                hits += x + y
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_TUPLE", uops)
        self.assertIn("_UNPACK_SEQUENCE_TWO_TUPLE", uops)
        self.assertIn("_GUARD_TOS_TUPLE", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_TUPLE", uops)

    def test_non_unique_two_tuple_unpack(self):
        def f(n):
            def two_tuple(x):
                return (x, x)
            hits = 0
            for i in range(n):
                tt = two_tuple(1)
                x, y = tt
                hits += x + y
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_TUPLE", uops)
        self.assertIn("_UNPACK_SEQUENCE_TWO_TUPLE", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_TUPLE", uops)
        self.assertNotIn("_UNPACK_SEQUENCE_UNIQUE_TWO_TUPLE", uops)

    def test_remove_guard_for_known_type_set(self):
        def f(n):
            x = 0
            for _ in range(n):
                x += "Spam" in {"Spam"}  # Unguarded!
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_TOS_ANY_SET", uops)
        # _CONTAINS_OP_SET is constant-folded away for frozenset literals
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_remove_guard_for_known_type_tuple(self):
        def f(n):
            x = 0
            for _ in range(n):
                t = (1, 2, (3, (4,)))
                t_0, t_1, (t_2_0, t_2_1) = t  # Unguarded!
                t_2_1_0 = t_2_1[0]  # Unguarded!
                x += t_0 + t_1 + t_2_0 + t_2_1_0
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 10 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_TOS_TUPLE", uops)
        self.assertIn("_UNPACK_SEQUENCE_TUPLE", uops)
        self.assertIn("_UNPACK_SEQUENCE_TWO_TUPLE", uops)
        self.assertNotIn("_GUARD_NOS_TUPLE", uops)
        self.assertIn(("_BINARY_OP_SUBSCR_TUPLE_INT" if Py_GIL_DISABLED else
                       "_BINARY_OP_SUBSCR_BORROWED_1"), uops)

    def test_remove_guard_for_known_type_slice(self):
        def f(n):
            x = 0
            for _ in range(n):
                l = [1, 2, 3]
                slice_obj = slice(0, 1)
                x += l[slice_obj][0] # guarded
                x += l[slice_obj][0] # unguarded
            return x
        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        uops = get_opnames(ex)

        count = count_ops(ex, "_GUARD_TOS_SLICE")
        self.assertEqual(count, 1)
        self.assertIn("_BINARY_OP_SUBSCR_LIST_CONST", uops)

    def test_remove_guard_for_tuple_bounds_check(self):
        def f(n):
            x = 0
            for _ in range(n):
                t = (1, 2, 3)
                x += t[0]
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_BINARY_OP_SUBSCR_TUPLE_INT_BOUNDS", uops)
        self.assertIn(("_BINARY_OP_SUBSCR_TUPLE_INT" if Py_GIL_DISABLED else
                       "_BINARY_OP_SUBSCR_BORROWED_1"), uops)

    def test_binary_subcsr_str_int_narrows_to_str(self):
        def testfunc(n):
            x = []
            s = "foo"
            for _ in range(n):
                y = s[0]       # _BINARY_OP_SUBSCR_STR_INT
                z = "bar" + y  # (_GUARD_TOS_UNICODE) + _BINARY_OP_ADD_UNICODE
                x.append(z)
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, ["barf"] * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_STR_INT", uops)
        # _BINARY_OP_SUBSCR_STR_INT narrows the result to 'str' so
        # the unicode guard before _BINARY_OP_ADD_UNICODE is removed.
        self.assertNotIn("_GUARD_TOS_UNICODE", uops)
        self.assertIn("_BINARY_OP_ADD_UNICODE", uops)

    def test_binary_subcsr_ustr_int_narrows_to_str(self):
        def testfunc(n):
            x = []
            s = "바이트코f드_특수화"
            for _ in range(n):
                y = s[4]       # _BINARY_OP_SUBSCR_USTR_INT
                z = "bar" + y  # (_GUARD_TOS_UNICODE) + _BINARY_OP_ADD_UNICODE
                x.append(z)
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, ["barf"] * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_USTR_INT", uops)
        # _BINARY_OP_SUBSCR_USTR_INT narrows the result to 'str' so
        # the unicode guard before _BINARY_OP_ADD_UNICODE is removed.
        self.assertNotIn("_GUARD_TOS_UNICODE", uops)
        self.assertIn("_BINARY_OP_ADD_UNICODE", uops)

    def test_binary_op_subscr_str_int(self):
        def testfunc(n):
            x = 0
            s = "hello"
            for _ in range(n):
                c = s[1]  # _BINARY_OP_SUBSCR_STR_INT
                if c == 'e':
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_STR_INT", uops)
        self.assertIn("_COMPARE_OP_STR", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_binary_op_subscr_ustr_int(self):
        def testfunc(n):
            x = 0
            s = "hello바"
            for _ in range(n):
                c = s[1]  # _BINARY_OP_SUBSCR_USTR_INT
                if c == 'e':
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_USTR_INT", uops)
        self.assertIn("_COMPARE_OP_STR", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_binary_op_subscr_dict(self):
        def testfunc(n):
            x = 0
            d = {'a': 1, 'b': 2}
            for _ in range(n):
                v = d['a']  # _BINARY_OP_SUBSCR_DICT
                if v == 1:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_binary_op_subscr_dict_known_hash(self):
        # str, int, bytes, float, complex, tuple and any python object which has generic hash
        def testfunc(n):
            x = 0
            d = {'a': 1, 1: 2, b'b': 3, (1, 2): 4, _GENERIC_KEY: 5, 1.5: 6, 1+2j: 7}
            for _ in range(n):
                x += d['a'] + d[1] + d[b'b'] + d[(1, 2)] + d[_GENERIC_KEY] + d[1.5] + d[1+2j]
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 28 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH", uops)
        if Py_GIL_DISABLED:
            # The global _GENERIC_KEY is loaded, not embedded as a constant.
            self.assertIn("_BINARY_OP_SUBSCR_DICT", uops)
        else:
            self.assertNotIn("_BINARY_OP_SUBSCR_DICT", uops)

    def test_mutable_global_key_does_not_assume_constant_hash(self):
        class Key:
            pass
        key = Key()
        namespace = {'key': key}
        exec('def lookup(mapping, n):\n'
             '    total = 0\n'
             '    for _ in range(n):\n'
             '        total += mapping[key]\n'
             '    return total\n', namespace)
        lookup = namespace['lookup']
        self.enterContext(clear_executors(lookup))
        mapping = {key: 7}
        self.assertEqual(lookup(mapping, TIER2_THRESHOLD), 7 * TIER2_THRESHOLD)
        names = get_opnames(get_first_executor(lookup))
        self.assertIn('_BINARY_OP_SUBSCR_DICT', names)
        self.assertNotIn('_BINARY_OP_SUBSCR_DICT_KNOWN_HASH', names)
        class Changed:
            def __hash__(self):
                raise LookupError('changed hash')
        key.__class__ = Changed
        with self.assertRaisesRegex(LookupError, 'changed hash'):
            lookup(mapping, 1)

    def test_binary_op_subscr_defaultdict_known_hash(self):
        # str, int, bytes, float, complex, tuple and any python object which has generic hash
        import collections

        def testfunc(n):
            x = 0
            d = collections.defaultdict(lambda: 1)
            for _ in range(n):
                x += d['a'] + d[1] + d[b'b'] + d[(1, 2)] + d[_GENERIC_KEY] + d[1.5] + d[1+2j]
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 7 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH", uops)
        if Py_GIL_DISABLED:
            # The global _GENERIC_KEY is loaded, not embedded as a constant.
            self.assertIn("_BINARY_OP_SUBSCR_DICT", uops)
        else:
            self.assertNotIn("_BINARY_OP_SUBSCR_DICT", uops)

    def test_binary_op_subscr_constant_frozendict_known_hash(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                x += FROZEN_DICT_CONST['x']
            return x

        res, ex = self._run_with_optimizer(testfunc, 2 * TIER2_THRESHOLD)
        self.assertEqual(res, 2 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        if Py_GIL_DISABLED:
            self.assertIn("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH", uops)
        else:
            self.assertNotIn("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH", uops)
        self.assertNotIn("_BINARY_OP_SUBSCR_DICT", uops)

    def test_store_subscr_dict_known_hash(self):
        # str, int, bytes, float, complex, tuple and any python object which has generic hash
        def testfunc(n):
            d = {'a': 0, 1: 0, b'b': 0, (1, 2): 0, _GENERIC_KEY: 0, 1.5: 0, 1+2j: 0}
            for _ in range(n):
                d['a'] += 1
                d[1] += 2
                d[b'b'] += 3
                d[(1, 2)] += 4
                d[_GENERIC_KEY] += 5
                d[1.5] += 6
                d[1+2j] += 7
            return d['a'] + d[1] + d[b'b'] + d[(1, 2)] + d[_GENERIC_KEY] + d[1.5] + d[1+2j]

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 28 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_STORE_SUBSCR_DICT_KNOWN_HASH", uops)
        if Py_GIL_DISABLED:
            # The global _GENERIC_KEY is loaded, not embedded as a constant.
            self.assertIn("_STORE_SUBSCR_DICT", uops)
        else:
            self.assertNotIn("_STORE_SUBSCR_DICT", uops)

    def test_store_subscr_defaultdict_known_hash(self):
        import collections

        def testfunc(n):
            d = collections.defaultdict(lambda: 0)
            for _ in range(n):
                d['a'] += 1
                d[1] += 2
                d[b'b'] += 3
                d[(1, 2)] += 4
                d[_GENERIC_KEY] += 5
                d[1.5] += 6
                d[1+2j] += 7
            return d['a'] + d[1] + d[b'b'] + d[(1, 2)] + d[_GENERIC_KEY] + d[1.5] + d[1+2j]

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 28 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_STORE_SUBSCR_DICT_KNOWN_HASH", uops)
        if Py_GIL_DISABLED:
            # The global _GENERIC_KEY is loaded, not embedded as a constant.
            self.assertIn("_STORE_SUBSCR_DICT", uops)
        else:
            self.assertNotIn("_STORE_SUBSCR_DICT", uops)

    def test_contains_op(self):
        def testfunc(n):
            x = 0
            items = [1, 2, 3]
            for _ in range(n):
                if 2 in items:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CONTAINS_OP", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_contains_op_set(self):
        def testfunc(n):
            x = 0
            s = {1, 2, 3}
            for _ in range(n):
                if 2 in s:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CONTAINS_OP_SET", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_contains_op_dict(self):
        def testfunc(n):
            x = 0
            d = {'a': 1, 'b': 2}
            for _ in range(n):
                if 'a' in d:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CONTAINS_OP_DICT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_call_type_1_guards_removed(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                foo = eval('42')
                x += type(foo) is int
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_TYPE_1", uops)
        self.assertNotIn("_GUARD_NOS_NULL", uops)
        self.assertNotIn("_GUARD_CALLABLE_TYPE_1", uops)

    def test_call_type_1_known_type(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                x += type(42) is int
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # When the result of type(...) is known, _CALL_TYPE_1 is decomposed.
        self.assertNotIn("_CALL_TYPE_1", uops)
        # _CALL_TYPE_1 produces 2 _POP_TOP_NOP (callable and null)
        # type(42) is int produces 4 _POP_TOP_NOP
        self.assertGreaterEqual(count_ops(ex, "_POP_TOP_NOP"), 6)

    def test_call_type_1_result_is_const(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                t = type(42)
                if t is not None:  # guard is removed
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_IS_NOT_NONE_POP", uops)

    def test_call_type_1_pop_top(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                foo = eval('42')
                x += type(foo) is int
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_TYPE_1", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_call_tuple_1_pop_top(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                t = tuple(())
                x += len(t) == 0
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_TUPLE_1", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_call_str_1(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = str(42)
                if y == '42':
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_STR_1", uops)
        self.assertNotIn("_GUARD_NOS_NULL", uops)
        self.assertNotIn("_GUARD_CALLABLE_STR_1", uops)

    def test_call_str_1_pop_top(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                t = str("")
                x += 1 if len(t) == 0 else 0
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_STR_1", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_call_str_1_result_is_str(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = str(42) + 'foo'
                if y == '42foo':
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_STR_1", uops)
        self.assertIn("_BINARY_OP_ADD_UNICODE", uops)
        self.assertNotIn("_GUARD_NOS_UNICODE", uops)
        self.assertNotIn("_GUARD_TOS_UNICODE", uops)

    def test_call_str_1_result_is_const_for_str_input(self):
        # Test a special case where the argument of str(arg)
        # is known to be a string. The information about the
        # argument being a string should be propagated to the
        # result of str(arg).
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = str('foo')  # string argument
                if y:           # _TO_BOOL_STR + _GUARD_IS_TRUE_POP are removed
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_STR_1", uops)
        self.assertNotIn("_TO_BOOL_STR", uops)
        self.assertNotIn(self.guard_is_true, uops)

    def test_call_tuple_1(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = tuple([1, 2])  # _CALL_TUPLE_1
                if y == (1, 2):
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_TUPLE_1", uops)
        self.assertNotIn("_GUARD_NOS_NULL", uops)
        self.assertNotIn("_GUARD_CALLABLE_TUPLE_1", uops)

    def test_call_tuple_1_result_is_tuple(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = tuple([1, 2])  # _CALL_TUPLE_1
                if y[0] == 1:      # _BINARY_OP_SUBSCR_TUPLE_INT
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_TUPLE_1", uops)
        self.assertIn(("_BINARY_OP_SUBSCR_TUPLE_INT" if Py_GIL_DISABLED else
                       "_BINARY_OP_SUBSCR_BORROWED_1"), uops)
        self.assertNotIn("_GUARD_NOS_TUPLE", uops)

    def test_call_tuple_1_result_propagates_for_tuple_input(self):
        # Test a special case where the argument of tuple(arg)
        # is known to be a tuple. The information about the
        # argument being a tuple should be propagated to the
        # result of tuple(arg).
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = tuple((1, 2))  # tuple argument
                a, _ = y           # _UNPACK_SEQUENCE_TWO_TUPLE
                if a == 1:         # _COMPARE_OP_INT + _GUARD_IS_TRUE_POP are removed
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_TUPLE_1", uops)
        self.assertIn("_UNPACK_SEQUENCE_TWO_TUPLE", uops)
        self.assertNotIn("_COMPARE_OP_INT", uops)
        self.assertNotIn(self.guard_is_true, uops)

    def test_call_len(self):
        def testfunc(n):
            a = [1, 2, 3, 4]
            for _ in range(n):
                _ = len(a) - 1

        _, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_NOS_NULL", uops)
        self.assertNotIn("_GUARD_CALLABLE_LEN", uops)
        self.assertTrue("_CALL_LEN" in uops or "_CALL_LEN_CONSUMER" in uops)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        self.assertNotIn("_GUARD_TOS_INT", uops)
        if "_CALL_LEN" in uops:
            self.assertIn("_POP_TOP_NOP", uops)

    def test_check_is_not_py_callable(self):
        def testfunc(n):
            total = 0
            f = len
            xs = (1, 2, 3)
            for _ in range(n):
                total += f(xs)
            return total

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 3 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CHECK_IS_NOT_PY_CALLABLE", uops)

    def test_check_is_not_py_callable_ex(self):
        def testfunc(n):
            total = 0
            xs = (1, 2, 3)
            args = (xs,)
            for _ in range(n):
                total += len(*args)
            return total

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 3 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CHECK_IS_NOT_PY_CALLABLE_EX", uops)

    def test_check_is_not_py_callable_kw(self):
        def testfunc(n):
            total = 0
            xs = (3, 1, 2)
            for _ in range(n):
                total += sorted(xs, reverse=False)[0]
            return total

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CHECK_IS_NOT_PY_CALLABLE_KW", uops)

    def test_call_len_string_frozen_set_dict(self):
        def testfunc(n):
            for _ in range(n):
                _ = len("abc")
                d = ''
                _ = len(d)
                _ = len(b"def")
                _ = len(b"")
                _ = len(FROZEN_SET_CONST)
                _ = len(FROZEN_DICT_CONST)

        _, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CALL_LEN", uops)
        self.assertGreaterEqual(count_ops(ex, "_LOAD_CONST_INLINE_BORROW"), 10)

    def test_call_len_known_length_small_int(self):
        # Make sure that len(t) is optimized for a tuple of length 5.
        # See https://github.com/python/cpython/issues/139393.
        self.assertGreater(_PY_NSMALLPOSINTS, 5)

        def testfunc(n):
            x = 0
            for _ in range(n):
                t = (1, 2, 3, 4, 5)
                if len(t) == 5:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # When the length is < _PY_NSMALLPOSINTS, the len() call is replaced
        # with just an inline load.
        self.assertNotIn("_CALL_LEN", uops)

    def test_call_len_known_length(self):
        # Make sure that len(t) is not optimized for a tuple of length 2048.
        # See https://github.com/python/cpython/issues/139393.
        self.assertLess(_PY_NSMALLPOSINTS, 2048)

        def testfunc(n):
            class C:
                t = tuple(range(2048))

            x = 0
            for _ in range(n):
                if len(C.t) == 2048:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The method fuser combines len() and its comparison without
        # creating a small-integer constant for the length.
        self.assertIn("_CALL_LEN_CONSUMER", uops)
        self.assertNotIn("_COMPARE_OP_INT", uops)
        self.assertIn("_METHOD_POP_JUMP_IF_TRUE", uops)


    def test_call_builtin_class(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = int("42")
                x += y
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 42)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_BUILTIN_CLASS", uops)
        self.assertNotIn("_GUARD_CALLABLE_BUILTIN_CLASS", uops)

    def test_call_builtin_o(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = abs(1)
                x += y
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_BUILTIN_O", uops)
        self.assertNotIn("_GUARD_CALLABLE_BUILTIN_O", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 4)

    def test_call_builtin_fast(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = divmod(10, 3)
                x += y[0]
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_BUILTIN_FAST", uops)
        self.assertNotIn("_GUARD_CALLABLE_BUILTIN_FAST", uops)
        # divmod(10, 3) should have at least 3 _POP_TOP_NOP
        # The borrowed subscript fuses two of the three cleanups for y[0].
        self.assertGreaterEqual(count_ops(ex, "_POP_TOP_NOP"),
                                6 if Py_GIL_DISABLED else 4)

    def test_call_builtin_fast_with_keywords(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = sorted([3, 1, 2])
                x += y[0]
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_BUILTIN_FAST_WITH_KEYWORDS", uops)
        self.assertNotIn("_GUARD_CALLABLE_BUILTIN_FAST_WITH_KEYWORDS", uops)

    def test_call_method_descriptor_o(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = (1, 2, 3)
                z = y.count(2)
                x += z
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_METHOD_DESCRIPTOR_O_INLINE", uops)
        self.assertNotIn("_CALL_METHOD_DESCRIPTOR_O", uops)
        self.assertNotIn("_GUARD_CALLABLE_METHOD_DESCRIPTOR_O", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 4)

    def test_call_method_descriptor_noargs(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = "hello"
                z = y.upper()
                x += len(z)
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 5)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_CALL_METHOD_DESCRIPTOR_NOARGS_INLINE", uops)
        self.assertNotIn("_CALL_METHOD_DESCRIPTOR_NOARGS", uops)
        self.assertNotIn("_GUARD_CALLABLE_METHOD_DESCRIPTOR_NOARGS", uops)
        # The folded callable/receiver loads need no runtime decref.
        self.assertIn("_POP_TOP" if Py_GIL_DISABLED else "_POP_TOP_SHARED", uops)


    def test_call_method_descriptor_fast(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = (1, 2, 3)
                z = y.index(2)
                x += z
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_METHOD_DESCRIPTOR_FAST_INLINE", uops)
        self.assertNotIn("_CALL_METHOD_DESCRIPTOR_FAST", uops)
        self.assertNotIn("_GUARD_CALLABLE_METHOD_DESCRIPTOR_FAST", uops)

    def test_call_method_descriptor_fast_with_keywords(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = "hello world"
                a, b = y.split()
                x += len(a)
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 5)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_METHOD_DESCRIPTOR_FAST_WITH_KEYWORDS_INLINE", uops)
        self.assertNotIn("_CALL_METHOD_DESCRIPTOR_FAST_WITH_KEYWORDS", uops)
        self.assertNotIn("_GUARD_CALLABLE_METHOD_DESCRIPTOR_FAST_WITH_KEYWORDS", uops)

    def test_check_recursion_limit_deduplicated(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = "hello"
                a = y.upper()
                b = y.lower()
                x += len(a)
                x += len(b)
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 10)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_METHOD_DESCRIPTOR_NOARGS_INLINE", uops)
        self.assertEqual(count_ops(ex, "_CHECK_RECURSION_LIMIT"), 1)

    def test_call_intrinsic_1(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                +x
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        uops = get_opnames(ex)

        self.assertIn("_CALL_INTRINSIC_1", uops)
        self.assertEqual(count_ops(ex, "_POP_TOP_NOP"), 1)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_call_intrinsic_2(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                def test_testfunc[T](n):
                    pass
            return test_testfunc

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(tuple(p.__name__ for p in res.__type_params__), ("T",))
        self.assertIsNone(res(3))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # Type parameter construction happens in a separately called frame.
        self.assertIn("_METHOD_CALL", uops)
        self.assertIn("_MAKE_FUNCTION", uops)


    def test_get_len_with_const_tuple(self):
        def testfunc(n):
            x = 0.0
            for _ in range(n):
                match (1, 2, 3, 4):
                    case [_, _, _, _]:
                        x += 1.0
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(int(res), TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        self.assertIn("_GET_LEN", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_get_len_with_non_const_tuple(self):
        def testfunc(n):
            x = 0.0
            for _ in range(n):
                match object(), object():
                    case [_, _]:
                        x += 1.0
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(int(res), TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        self.assertIn("_GET_LEN", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_get_len_with_non_tuple(self):
        def testfunc(n):
            x = 0.0
            for _ in range(n):
                match [1, 2, 3, 4]:
                    case [_, _, _, _]:
                        x += 1.0
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(int(res), TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        self.assertIn("_GET_LEN", uops)

    def test_binary_op_subscr_tuple_int(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = (1, 2)
                if y[0] == 1:  # _COMPARE_OP_INT + _GUARD_IS_TRUE_POP are removed
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn(("_BINARY_OP_SUBSCR_TUPLE_INT" if Py_GIL_DISABLED else
                       "_BINARY_OP_SUBSCR_BORROWED_1"), uops)
        self.assertNotIn("_COMPARE_OP_INT", uops)
        self.assertNotIn(self.guard_is_true, uops)

    def test_call_isinstance_guards_removed(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = isinstance(42, int)
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_GUARD_THIRD_NULL", uops)
        self.assertNotIn("_GUARD_CALLABLE_ISINSTANCE", uops)

    def test_call_list_append(self):
        def testfunc(n):
            a = []
            for i in range(n):
                a.append(i)
            return sum(a)

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, sum(range(TIER2_THRESHOLD)))
        uops = get_opnames(ex)
        self.assertIn("_CALL_LIST_APPEND", uops)

    def test_call_list_append_pop_top(self):
        def testfunc(n):
            a = []
            for i in range(n):
                a.append(1)
            return sum(a)
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertIn("_CALL_LIST_APPEND", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_call_isinstance_is_true(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = isinstance(42, int)
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)
        self.assertNotIn(self.guard_is_true, uops)

    def test_call_isinstance_is_false(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = isinstance(42, str)
                if not y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)
        self.assertNotIn(self.guard_is_false, uops)

    def test_call_isinstance_subclass(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                y = isinstance(True, int)
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)
        self.assertNotIn(self.guard_is_true, uops)

    def test_call_isinstance_unknown_object(self):
        def testfunc(n, expression="42"):
            x = 0
            for _ in range(n):
                # The optimizer doesn't know the return type here:
                bar = eval(expression)
                # No recorded type is available to fold this call.
                y = isinstance(bar, int)
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(testfunc(8, "'text'"), 0)

    @unittest.skipIf(Py_GIL_DISABLED, "FT retains the lock-free cell getter")
    def test_method_cell_load_mutation_and_unbound(self):
        value = object()

        def read(count):
            for _ in range(count):
                result = value
            return result

        self.assertIs(read(TIER2_THRESHOLD), value)
        ops = get_opnames(get_first_executor(read))
        self.assertIn("_LOAD_DEREF_GUARDED", ops)
        self.assertNotIn("_LOAD_DEREF", ops)
        value = object()
        self.assertIs(read(TIER2_THRESHOLD), value)
        del value
        with self.assertRaisesRegex(NameError, "value"):
            read(TIER2_THRESHOLD)
        value = None
        self.assertIsNone(read(TIER2_THRESHOLD))

    def test_method_calls_all_arities(self):
        def zero():
            return 7

        def one(value):
            return value

        class Receiver:
            def method(self):
                return 3

        def calls(count, obj):
            result = 0
            for index in range(count):
                result += zero() + one(index) + obj.method()
                result += len(str())
            return result

        self.assertEqual(calls(TIER2_THRESHOLD, Receiver()),
                         10 * TIER2_THRESHOLD + sum(range(TIER2_THRESHOLD)))
        self.assertIsNotNone(get_first_executor(calls))

    def test_call_isinstance_unknown_type(self):
        def check(values):
            result = []
            for value in values:
                result.append(isinstance(value, int))
            return result

        values = [1000] * TIER2_THRESHOLD
        self.assertEqual(check(values), [True] * len(values))
        ops = get_opnames(get_first_executor(check))
        self.assertIn("_CALL_ISINSTANCE", ops)
        events = []

        class Pretender:
            @property
            def __class__(self):
                events.append("class")
                return int

        class Broken:
            @property
            def __class__(self):
                raise ValueError("class lookup")

        class Integer(int):
            pass

        self.assertEqual(check([1000, Integer(1), "text", Pretender()]),
                         [True, True, False, True])
        self.assertEqual(events, ["class"])
        with self.assertRaisesRegex(ValueError, "class lookup"):
            check([Broken()])
        self.assertEqual(check([1000]), [True])

    def test_call_isinstance_tuple_of_classes(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                # A tuple of classes is currently not optimized,
                # so this is only narrowed to bool:
                y = isinstance(42, (int, str))
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))

    def test_call_isinstance_metaclass(self):
        class EvenNumberMeta(type):
            def __instancecheck__(self, number):
                return number % 2 == 0

        class EvenNumber(metaclass=EvenNumberMeta):
            pass

        def testfunc(n):
            x = 0
            for _ in range(n):
                # Only narrowed to bool
                y = isinstance(42, EvenNumber)
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_CALL_ISINSTANCE", uops)
        self.assertNotIn("_TO_BOOL_BOOL", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))

    def test_set_type_version_sets_type(self):
        class C:
            A = 1

        def testfunc(n):
            x = 0
            c = C()
            for _ in range(n):
                x += c.A  # Guarded.
                x += type(c).A  # Unguarded!
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 2 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_GUARD_TYPE_VERSION", uops)
        self.assertNotIn("_CHECK_ATTR_CLASS", uops)

    def test_load_common_constant(self):
        def testfunc(n):
            for _ in range(n):
                x = list(i for i in ())
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, list(()))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BUILD_LIST", uops)
        self.assertNotIn("_LOAD_COMMON_CONSTANT", uops)

    def test_load_common_constant_new_literals(self):
        def testfunc(n):
            x = None
            s = ""
            t = True
            f = False
            m = -1
            for _ in range(n):
                x = None
                s = ""
                t = True
                f = False
                m = -1
            return x, s, t, f, m
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, (None, "", True, False, -1))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_LOAD_COMMON_CONSTANT", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_load_small_int(self):
        def testfunc(n):
            x = 0
            for i in range(n):
                x += 1
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_LOAD_SMALL_INT", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_cached_attributes(self):
        class C:
            A = 1
            def m(self):
                return 1
        class D:
            __slots__ = ()
            A = 1
            def m(self):
                return 1
        class E(Exception):
            def m(self):
                return 1
        def f(n):
            x = 0
            c = C()
            d = D()
            e = E()
            for _ in range(n):
                x += C.A  # _LOAD_ATTR_CLASS
                x += c.A  # _LOAD_ATTR_NONDESCRIPTOR_WITH_VALUES
                x += d.A  # _LOAD_ATTR_NONDESCRIPTOR_NO_DICT
                x += c.m()  # _LOAD_ATTR_METHOD_WITH_VALUES
                x += d.m()  # _LOAD_ATTR_METHOD_NO_DICT
                x += e.m()  # _LOAD_ATTR_METHOD_LAZY_DICT
            return x

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 6 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_LOAD_ATTR_CLASS", uops)
        self.assertIn("_LOAD_ATTR_NONDESCRIPTOR_WITH_VALUES", uops)
        self.assertIn("_LOAD_ATTR_NONDESCRIPTOR_NO_DICT", uops)
        self.assertNotIn("_LOAD_ATTR_METHOD_WITH_VALUES", uops)
        if Py_GIL_DISABLED:
            self.assertIn("_LOAD_ATTR_METHOD_NO_DICT", uops)
        else:
            self.assertNotIn("_LOAD_ATTR_METHOD_NO_DICT", uops)
        if Py_GIL_DISABLED:
            self.assertIn("_LOAD_ATTR_METHOD_LAZY_DICT", uops)
        else:
            self.assertNotIn("_LOAD_ATTR_METHOD_LAZY_DICT", uops)
        self.assertEqual(uops.count("_CALL_RETURN_CONSTANT"),
                         0 if Py_GIL_DISABLED else 3)
        C.A = 2
        self.assertEqual(f(5), 8 * 5)
        D.A = 3
        self.assertEqual(f(5), 10 * 5)
        C.m.__code__ = (lambda self: 4).__code__
        self.assertEqual(f(5), 13 * 5)


    def test_cached_attributes_fixed_version_tag(self):
        def f(n):
            c = 1
            x = 0
            for _ in range(n):
                x += c.bit_length()
            return x
        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertNotIn("_LOAD_ATTR_METHOD_NO_DICT", uops)
        self.assertIn("_LOAD_CONST_INLINE_BORROW", uops)

    def test_cached_load_special(self):
        class CM:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        def f(n):
            cm = CM()
            x = 0
            for _ in range(n):
                with cm:
                    x += 1
            return x
        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertIn("_LOAD_SPECIAL", uops)
        self.assertIn("_PUSH_FRAME" if Py_GIL_DISABLED else
                      "_CALL_RETURN_ARGUMENT", uops)
        events = []
        CM.__exit__ = lambda self, *args: events.append(args)
        self.assertEqual(f(3), 3)
        self.assertEqual(events, [(None, None, None)] * 3)


    def test_store_fast_callee_argument_cleanup(self):
        def foo(x):
            # Exact integer type is propagated, but identity is not.
            x = 2
            return x
        def testfunc(n):
            # The STORE_FAST for the range here needs a POP_TOP
            # (for now, until we do loop peeling).
            for _ in range(n):
                result = foo(1)
            return result

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 2)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_POP_TOP_INT", uops)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 1)

    def test_store_fast_refcount_elimination_when_uninitialized(self):
        def foo():
            # Since y is known to be
            # uninitialized (NULL) here,
            # The refcount is eliminated in the STORE_FAST.
            y = 2
            return y
        def testfunc(n):
            # The STORE_FAST for the range here needs a POP_TOP
            # (for now, until we do loop peeling).
            for _ in range(n):
                foo()

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 1)


    def test_float_op_refcount_elimination(self):
        def testfunc(args):
            a, b, n = args
            c = 0.0
            for _ in range(n):
                c += a + b
            return c

        res, ex = self._run_with_optimizer(testfunc, (0.1, 0.1, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * (0.1 + 0.1))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_float_add_inplace_unique_lhs(self):
        # a * b produces a unique float; adding c reuses it in place
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += a * b + c
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 4.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 10.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_ADD_FLOAT_INPLACE", uops)

    def test_float_add_inplace_unique_rhs(self):
        # a * b produces a unique float on the right side of +
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += c + a * b
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 4.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 10.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_ADD_FLOAT_INPLACE_RIGHT", uops)

    def test_float_add_no_inplace_non_unique(self):
        # Both operands of a + b are locals — neither is unique,
        # so the first add is regular. But total += (a+b) has a
        # unique RHS, so it uses _INPLACE_RIGHT.
        def testfunc(args):
            a, b, n = args
            total = 0.0
            for _ in range(n):
                total += a + b
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 5.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # a + b: both are locals, no inplace
        self.assertIn("_BINARY_OP_ADD_FLOAT", uops)
        # total += result: result is unique RHS
        self.assertIn("_BINARY_OP_ADD_FLOAT_INPLACE_RIGHT", uops)
        # No LHS inplace variant for the first add
        self.assertNotIn("_BINARY_OP_ADD_FLOAT_INPLACE", uops)

    def test_float_subtract_inplace_unique_lhs(self):
        # a * b produces a unique float; subtracting c reuses it
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += a * b - c
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 1.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 5.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBTRACT_FLOAT_INPLACE", uops)

    def test_float_subtract_inplace_unique_rhs(self):
        # a * b produces a unique float on the right of -;
        # result is c - (a * b), must get the sign correct
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += c - a * b
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 1.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * -5.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBTRACT_FLOAT_INPLACE_RIGHT", uops)

    def test_float_multiply_inplace_unique_lhs(self):
        # (a + b) produces a unique float; multiplying by c reuses it
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += (a + b) * c
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 4.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 20.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_MULTIPLY_FLOAT_INPLACE", uops)

    def test_float_multiply_inplace_unique_rhs(self):
        # (a + b) produces a unique float on the right side of *
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += c * (a + b)
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 4.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 20.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_MULTIPLY_FLOAT_INPLACE_RIGHT", uops)

    def test_float_inplace_chain_propagation(self):
        # a * b + c * d: both products are unique, the + reuses one;
        # result of + is also unique for the subsequent +=
        def testfunc(args):
            a, b, c, d, n = args
            total = 0.0
            for _ in range(n):
                total += a * b + c * d
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 4.0, 5.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 26.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The + between the two products should use an inplace variant
        inplace_add = (
            "_BINARY_OP_ADD_FLOAT_INPLACE" in uops
            or "_BINARY_OP_ADD_FLOAT_INPLACE_RIGHT" in uops
        )
        self.assertTrue(inplace_add,
            "Expected an inplace add for unique intermediate results")

    def test_float_negate_inplace_unique(self):
        # -(a * b): the product is unique, negate it in place
        def testfunc(args):
            a, b, n = args
            total = 0.0
            for _ in range(n):
                total += -(a * b)
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * -6.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_UNARY_NEGATIVE_FLOAT_INPLACE", uops)

    def test_float_negate_no_inplace_non_unique(self):
        # -a where a is a local — not unique, no inplace
        def testfunc(args):
            a, n = args
            total = 0.0
            for _ in range(n):
                total += -a
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * -2.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_UNARY_NEGATIVE_FLOAT_INPLACE", uops)

    def test_float_truediv_inplace_unique_lhs(self):
        # (a + b) / (c + d): LHS is unique float from add, RHS is unique
        # float from add. The division reuses the LHS in place.
        def testfunc(args):
            a, b, c, d, n = args
            total = 0.0
            for _ in range(n):
                total += (a + b) / (c + d)
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 1.0, 3.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 1.25)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_TRUEDIV_FLOAT_INPLACE", uops)

    def test_float_truediv_inplace_unique_rhs(self):
        # x = c + d stores to a local (not unique when reloaded).
        # (a + b) is unique. The division should use inplace on the RHS.
        def testfunc(args):
            a, b, c, d, n = args
            total = 0.0
            for _ in range(n):
                x = c + d
                total += x / (a + b)
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, 4.0, 5.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * (9.0 / 5.0))
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_TRUEDIV_FLOAT_INPLACE_RIGHT", uops)

    def test_unknown_float_operands_use_general_method_dispatch(self):
        # A static frontend cannot infer tuple elements from a live frame.
        # Generic arithmetic must retain all Python operand semantics. The
        # separate type-propagation tests cover statically proven floats.
        for operation in ('/', '%'):
            with self.subTest(operation=operation):
                namespace = {}
                exec(f"def testfunc(args):\n"
                     f"    a, b, n = args\n"
                     f"    total = 0.0\n"
                     f"    for _ in range(n):\n"
                     f"        total += a {operation} b\n"
                     f"    return total\n", namespace)
                testfunc = namespace['testfunc']
                expected = 10.0 / 3.0 if operation == '/' else 10.0 % 3.0
                res, executor = self._run_with_optimizer(
                    testfunc, (10.0, 3.0, TIER2_THRESHOLD))
                self.assertAlmostEqual(res, TIER2_THRESHOLD * expected)
                self.assertIsNotNone(executor)
                self.assertIn('_BINARY_OP', get_opnames(executor))
                with self.assertRaises(ZeroDivisionError):
                    testfunc((10.0, 0.0, 3))
                calls = []
                class Operand:
                    def __truediv__(self, other):
                        calls.append(('div', other))
                        return 7.0
                    def __mod__(self, other):
                        calls.append(('mod', other))
                        return 7.0
                self.assertEqual(testfunc((Operand(), 3.0, 4)), 28.0)
                self.assertEqual(calls, [('div' if operation == '/' else 'mod', 3.0)] * 4)

    def test_float_truediv_type_propagation(self):
        # Test the _BINARY_OP_TRUEDIV_FLOAT propagates type information
        def testfunc(args):
            a, b, n = args
            total = 0.0
            for _ in range(n):
                x = (a + b) # type of x will specialize to float
                total += x / x - x / x
            return total

        res, ex = self._run_with_optimizer(testfunc,
            (2.0, 3.0, TIER2_THRESHOLD))
        expected = TIER2_THRESHOLD * ((2.0 + 3.0) / (2.0 + 3.0) - (2.0 + 3.0) / (2.0 + 3.0))
        self.assertAlmostEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_TRUEDIV_FLOAT", uops)
        self.assertIn("_BINARY_OP_SUBTRACT_FLOAT_INPLACE", uops)

    def test_float_truediv_unique_result_enables_inplace(self):
        # (a+b) / (c+d) / (e+f): chained divisions where each result
        # is unique, enabling inplace for subsequent divisions.
        def testfunc(args):
            a, b, c, d, e, f, n = args
            total = 0.0
            for _ in range(n):
                total += (a + b) / (c + d) / (e + f)
            return total

        res, ex = self._run_with_optimizer(testfunc,
            (2.0, 3.0, 1.0, 1.0, 1.0, 1.0, TIER2_THRESHOLD))
        expected = TIER2_THRESHOLD * ((2.0 + 3.0) / (1.0 + 1.0) / (1.0 + 1.0))
        self.assertAlmostEqual(res, expected)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_TRUEDIV_FLOAT_INPLACE", uops)

    def test_float_add_chain_both_unique(self):
        # (a+b) + (c+d): both sub-additions produce unique floats.
        # The outer + should use inplace on one of them.
        def testfunc(args):
            a, b, c, d, n = args
            total = 0.0
            for _ in range(n):
                total += (a + b) + (c + d)
            return total

        res, ex = self._run_with_optimizer(testfunc, (1.0, 2.0, 3.0, 4.0, TIER2_THRESHOLD))
        self.assertAlmostEqual(res, TIER2_THRESHOLD * 10.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # The outer + should use inplace (at least one operand is unique)
        inplace = (
            "_BINARY_OP_ADD_FLOAT_INPLACE" in uops
            or "_BINARY_OP_ADD_FLOAT_INPLACE_RIGHT" in uops
        )
        self.assertTrue(inplace, "Expected inplace add for unique sub-results")

    def test_float_truediv_non_float_type_no_crash(self):
        # Fraction / Fraction goes through _BINARY_OP with NB_TRUE_DIVIDE
        # but returns Fraction, not float. The optimizer must not assume
        # the result is float for non-int/float operands. See gh-146306.
        from fractions import Fraction
        def testfunc(args):
            a, b, n = args
            total = Fraction(0)
            for _ in range(n):
                total += a / b
            return float(total)

        res, ex = self._run_with_optimizer(testfunc, (Fraction(10), Fraction(3), TIER2_THRESHOLD))
        expected = float(TIER2_THRESHOLD * Fraction(10, 3))
        self.assertAlmostEqual(res, expected)

    def test_float_truediv_mixed_float_fraction_no_crash(self):
        # float / Fraction: lhs is known float from a prior guard,
        # but rhs is Fraction. The guard insertion for rhs should
        # deopt cleanly at runtime, not crash.
        from fractions import Fraction
        def testfunc(args):
            a, b, c, n = args
            total = 0.0
            for _ in range(n):
                total += (a + b) / c  # (a+b) is float, c is Fraction
            return total

        res, ex = self._run_with_optimizer(testfunc, (2.0, 3.0, Fraction(4), TIER2_THRESHOLD))
        expected = TIER2_THRESHOLD * (5.0 / Fraction(4))
        self.assertAlmostEqual(res, float(expected))

    def test_float_truediv_partial_float_no_stack_underflow(self):
        import math

        # gh-149049: a speculative _GUARD_*_FLOAT for a partially-float
        # truediv/remainder must not drop the original _BINARY_OP.
        def truediv(args):
            n, = args
            nan = float("nan")
            def victim(a=0, b=nan, c=2):
                return (a + b) / c
            for _ in range(n):
                result = victim()
            return result

        def remainder(args):
            n, = args
            nan = float("nan")
            def victim(a=0, b=nan, c=2):
                return (a + b) % c
            for _ in range(n):
                result = victim()
            return result

        for testfunc in (truediv, remainder):
            with self.subTest(op=testfunc.__name__):
                # Iterations must be high enough that the compiled method
                # is not only built but executed (where it underflows).
                result, ex = self._run_with_optimizer(
                    testfunc, (TIER2_THRESHOLD * 10,))
                self.assertTrue(math.isnan(result))
                self.assertIsNotNone(ex)
                uops = get_opnames(ex)
                # Default arguments are unknown to the static analysis.
                # Both arithmetic operations must survive in the callee.
                self.assertIn("_PUSH_FRAME", uops)
                self.assertGreaterEqual(uops.count("_BINARY_OP"), 2)
    def test_int_add_inplace_unique_lhs(self):
        # a * b produces a unique compact int; adding c reuses it in place
        def testfunc(args):
            a, b, c, n = args
            total = 0
            for _ in range(n):
                total += a * b + c
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3, 4000, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 10000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_ADD_INT_INPLACE", uops)

    def test_int_add_inplace_unique_rhs(self):
        # a * b produces a unique compact int on the right side of +
        def testfunc(args):
            a, b, c, n = args
            total = 0
            for _ in range(n):
                total += c + a * b
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3, 4000, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 10000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_ADD_INT_INPLACE_RIGHT", uops)

    def test_int_add_no_inplace_non_unique(self):
        # Both operands of a + b are locals — neither is unique,
        # so the first add uses the regular op. But total += (a+b)
        # has a unique RHS (result of a+b), so it uses _INPLACE_RIGHT.
        def testfunc(args):
            a, b, n = args
            total = 0
            for _ in range(n):
                total += a + b
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3000, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 5000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # a + b: both are locals, no inplace
        self.assertIn("_BINARY_OP_ADD_INT", uops)
        # total += result: result is unique RHS
        self.assertIn("_BINARY_OP_ADD_INT_INPLACE_RIGHT", uops)
        # No LHS inplace variant for the first add
        self.assertNotIn("_BINARY_OP_ADD_INT_INPLACE", uops)

    def test_int_add_inplace_small_int_result(self):
        # When the result is a small int, the inplace path falls back
        # to _PyCompactLong_Add. Verify correctness (no singleton corruption).
        def testfunc(args):
            a, b, n = args
            total = 0
            for _ in range(n):
                total += a * b + 1  # a*b=6, +1=7, small int
            return total

        res, ex = self._run_with_optimizer(testfunc, (2, 3, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 7)
        # Verify small int singletons are not corrupted
        self.assertEqual(7, 3 + 4)

    def test_int_subtract_inplace_unique_lhs(self):
        # a * b produces a unique compact int; subtracting c reuses it
        def testfunc(args):
            a, b, c, n = args
            total = 0
            for _ in range(n):
                total += a * b - c
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3, 1000, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 5000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBTRACT_INT_INPLACE", uops)

    def test_int_subtract_inplace_unique_rhs(self):
        # a * b produces a unique compact int on the right of -
        def testfunc(args):
            a, b, c, n = args
            total = 0
            for _ in range(n):
                total += c - a * b
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3, 10000, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 4000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBTRACT_INT_INPLACE_RIGHT", uops)

    def test_int_multiply_inplace_unique_lhs(self):
        # (a + b) produces a unique compact int; multiplying by c reuses it
        def testfunc(args):
            a, b, c, n = args
            total = 0
            for _ in range(n):
                total += (a + b) * c
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3000, 4, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 20000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_MULTIPLY_INT_INPLACE", uops)

    def test_int_multiply_inplace_unique_rhs(self):
        # (a + b) produces a unique compact int on the right side of *
        def testfunc(args):
            a, b, c, n = args
            total = 0
            for _ in range(n):
                total += c * (a + b)
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3000, 4, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 20000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_MULTIPLY_INT_INPLACE_RIGHT", uops)

    def test_int_inplace_chain_propagation(self):
        # a * b + c * d: both products are unique, the + reuses one;
        # result of + is also unique for the subsequent +=
        def testfunc(args):
            a, b, c, d, n = args
            total = 0
            for _ in range(n):
                total += a * b + c * d
            return total

        res, ex = self._run_with_optimizer(testfunc, (2000, 3, 4000, 5, TIER2_THRESHOLD))
        self.assertEqual(res, TIER2_THRESHOLD * 26000)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        inplace_add = (
            "_BINARY_OP_ADD_INT_INPLACE" in uops
            or "_BINARY_OP_ADD_INT_INPLACE_RIGHT" in uops
        )
        unboxed = any(name.startswith("_INT_REGION_START") for name in uops)
        self.assertTrue(inplace_add or unboxed,
            "Expected unboxed arithmetic or an inplace add for unique results")

    def test_load_attr_instance_value(self):
        def testfunc(n):
            class C():
                pass
            c = C()
            c.x = n
            x = 0
            for _ in range(n):
                x = c.x
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_LOAD_ATTR_BORROWED_OWNER", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)
        self.assertNotIn("_POP_TOP_NOP", uops)

    def test_load_attr_module(self):
        def testfunc(n):
            import math
            x = 0
            for _ in range(n):
                y = math.pi
                if y:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn(("_LOAD_ATTR_MODULE", "_POP_TOP_NOP"), itertools.pairwise(uops))
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_load_attr_with_hint(self):
        def testfunc(n):
            class C:
                pass
            c = C()
            c.x = 42
            for i in range(_testinternalcapi.SHARED_KEYS_MAX_SIZE - 1):
                setattr(c, f"_{i}", None)
            x = 0
            for i in range(n):
                x += c.x
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 42 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_LOAD_ATTR_WITH_HINT", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_load_addr_slot(self):
        def testfunc(n):
            class C:
                __slots__ = ('x',)
            c = C()
            c.x = 42
            x = 0
            for _ in range(n):
                x += c.x
            return x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 42 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_LOAD_ATTR_BORROWED_OWNER", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_int_add_op_refcount_elimination(self):
        def testfunc(n):
            c = 1
            res = 0
            for _ in range(n):
                res = c + c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_ADD_INT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_int_sub_op_refcount_elimination(self):
        def testfunc(n):
            c = 1
            res = 0
            for _ in range(n):
                res = c - c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_SUBTRACT_INT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_int_mul_op_refcount_elimination(self):
        def testfunc(n):
            c = 1
            res = 0
            for _ in range(n):
                res = c * c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_MULTIPLY_INT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_int_cmp_op_refcount_elimination(self):
        def testfunc(n):
            c = 1
            res = 0
            for _ in range(n):
                res = c == c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_COMPARE_OP_INT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_float_cmp_op_refcount_elimination(self):
        def testfunc(n):
            c = 1.0
            res = False
            for _ in range(n):
                res = c == c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_COMPARE_OP_FLOAT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_str_cmp_op_refcount_elimination(self):
        def testfunc(n):
            c = "a"
            res = False
            for _ in range(n):
                res = c == c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_COMPARE_OP_STR", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_unicode_add_op_refcount_elimination(self):
        def testfunc(n):
            c = "a"
            res = ""
            for _ in range(n):
                res = c + c
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, "aa")
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_ADD_UNICODE", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_binary_op_refcount_elimination(self):
        class CustomAdder:
            def __init__(self, val):
                self.val = val
            def __add__(self, other):
                return CustomAdder(self.val + other.val)

        def testfunc(n):
            a = CustomAdder(1)
            b = CustomAdder(2)
            res = None
            for _ in range(n):
                res = a + b
            return res.val if res else 0

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_binary_op_extend_float_long_add_refcount_elimination(self):
        def testfunc(n):
            a = 1.5
            b = 2
            res = 0.0
            for _ in range(n):
                res = a + b
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 3.5)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_EXTEND", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_remove_guard_for_slice_list(self):
        def f(n):
            for i in range(n):
                false = i == TIER2_THRESHOLD
                sliced = [1, 2, 3][:false]
                if sliced:
                    return 1
            return 0

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_TO_BOOL_LIST", uops)
        self.assertNotIn("_GUARD_TOS_LIST", uops)

    def test_remove_guard_for_slice_tuple(self):
        def f(n):
            for i in range(n):
                false = i == TIER2_THRESHOLD
                a, b = (1, 2, 3)[: false + 2]

        _, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_UNPACK_SEQUENCE_TWO_TUPLE", uops)
        self.assertNotIn("_GUARD_TOS_TUPLE", uops)

    def test_binary_op_extend_float_result_enables_inplace_multiply(self):
        # (2 + x) * y with x, y floats: `2 + x` goes through _BINARY_OP_EXTEND
        # (int + float). The result_type/result_unique info should let the
        # subsequent float multiply use the inplace variant.
        def testfunc(n):
            x = 3.5
            y = 2.0
            res = 0.0
            for _ in range(n):
                res = (2 + x) * y
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 11.0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_EXTEND", uops)
        self.assertIn("_BINARY_OP_MULTIPLY_FLOAT_INPLACE", uops)
        self.assertNotIn("_BINARY_OP_MULTIPLY_FLOAT", uops)
        # NOS guard on the multiply is eliminated because _BINARY_OP_EXTEND
        # propagates PyFloat_Type.
        self.assertNotIn("_GUARD_NOS_FLOAT", uops)

    def test_binary_op_extend_list_concat_type_propagation(self):
        # list + list is specialized via BINARY_OP_EXTEND. The tier 2 optimizer
        # should learn that the result is a list and eliminate subsequent
        # list-type guards.
        def testfunc(n):
            a = [1, 2]
            b = [3, 4]
            x = True
            for _ in range(n):
                c = a + b
                if c[0]:
                    x = False
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, False)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_EXTEND", uops)
        # The c[0] subscript emits _GUARD_NOS_LIST before _BINARY_OP_SUBSCR_LIST_INT;
        # since _BINARY_OP_EXTEND now propagates PyList_Type, that guard is gone.
        self.assertIn("_BINARY_OP_SUBSCR_LIST_CONST", uops)
        self.assertNotIn("_GUARD_NOS_LIST", uops)

    def test_binary_op_extend_tuple_concat_type_propagation(self):
        # tuple + tuple is specialized via BINARY_OP_EXTEND. The tier 2 optimizer
        # should learn the result is a tuple and eliminate subsequent tuple guards.
        def testfunc(n):
            t1 = (1, 2)
            t2 = (3, 4)
            for _ in range(n):
                a, b, c, d = t1 + t2
            return a + b + c + d

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 10)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_EXTEND", uops)
        self.assertIn("_UNPACK_TUPLE_TO_FAST_4", uops)
        self.assertNotIn("_GUARD_TOS_TUPLE", uops)

    def test_binary_op_extend_guard_elimination(self):
        # When both operands have known types (e.g., from a prior
        # _BINARY_OP_EXTEND result), the _GUARD_BINARY_OP_EXTEND
        # should be eliminated.
        def testfunc(n):
            a = [1, 2]
            b = [3, 4]
            total = 0
            for _ in range(n):
                c = a + b    # operands are proven lists at the OSR entry
                d = c + c    # second: both operands are list -> guard eliminated
                total += d[0]
            return total

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # Both list additions use _BINARY_OP_EXTEND
        self.assertEqual(uops.count("_BINARY_OP_EXTEND"), 2)
        # The entry guards prove a and b are lists; the first result proves c.
        self.assertIn("_GUARD_OSR_LOCAL_TYPE", uops)
        self.assertNotIn("_GUARD_BINARY_OP_EXTEND", uops)

    def test_binary_op_extend_partial_guard_lhs_known(self):
        # When the lhs type is already known (from a prior _BINARY_OP_EXTEND
        # result) but the rhs type is not, the optimizer should emit
        # _GUARD_BINARY_OP_EXTEND_RHS (checking only the rhs) instead of
        # the full _GUARD_BINARY_OP_EXTEND.
        def testfunc(n, a, b):
            total = 0
            for _ in range(n):
                c = a + b    # result type is list (known)
                d = c + b    # lhs (c) is known list, rhs (b) is not -> _GUARD_BINARY_OP_EXTEND_RHS
                total += d[0]
            return total

        res = testfunc(TIER2_THRESHOLD, [1, 2], [3, 4])
        ex = get_first_executor(testfunc)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_EXTEND", uops)
        self.assertIn("_GUARD_BINARY_OP_EXTEND_RHS", uops)
        self.assertNotIn("_GUARD_BINARY_OP_EXTEND_LHS", uops)

    def test_binary_op_extend_partial_guard_rhs_known(self):
        # When the rhs type is already known (from a prior _BINARY_OP_EXTEND
        # result) but the lhs type is not, the optimizer should emit
        # _GUARD_BINARY_OP_EXTEND_LHS (checking only the lhs) instead of
        # the full _GUARD_BINARY_OP_EXTEND.
        def testfunc(n, a, b):
            total = 0
            for _ in range(n):
                c = a + b    # result type is list (known)
                d = b + c    # rhs (c) is known list, lhs (b) is not -> _GUARD_BINARY_OP_EXTEND_LHS
                total += d[2]
            return total

        res = testfunc(TIER2_THRESHOLD, [1, 2], [3, 4])
        ex = get_first_executor(testfunc)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_BINARY_OP_EXTEND", uops)
        self.assertIn("_GUARD_BINARY_OP_EXTEND_LHS", uops)
        self.assertNotIn("_GUARD_BINARY_OP_EXTEND_RHS", uops)

    def test_unary_invert_long_type(self):
        def testfunc(n):
            for _ in range(n):
                a = 9397
                x = ~a + ~a

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertNotIn("_GUARD_TOS_INT", uops)
        self.assertNotIn("_GUARD_NOS_INT", uops)

    def test_store_attr_preserves_float_alias(self):
        class Record:
            pass
        def loop(n, obj):
            value = 1.25
            for _ in range(n):
                first = value + 1.0
                obj.value = first
                value = first + 1.0
                if value - obj.value != 1.0:
                    raise AssertionError("attribute alias was mutated")
            return value
        obj = Record()
        result = loop(TIER2_THRESHOLD, obj)
        executor = get_first_executor(loop)
        self.assertEqual(result, 1.25 + 2 * TIER2_THRESHOLD)
        self.assertIsNotNone(executor)

    def test_store_attr_instance_value(self):
        def testfunc(n):
            class C:
                pass
            c = C()
            for i in range(n):
                c.a = i
            return c.a
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD - 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_STORE_ATTR_INSTANCE_VALUE" if Py_GIL_DISABLED else
                      "_STORE_ATTR_INSTANCE_VALUE_NOESCAPE", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 1)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_store_attr_with_hint(self):
        def testfunc(n):
            class C:
                pass
            c = C()
            for i in range(_testinternalcapi.SHARED_KEYS_MAX_SIZE - 1):
                setattr(c, f"_{i}", None)

            for i in range(n):
                c.x = i
            return c.x
        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD - 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_STORE_ATTR_WITH_HINT", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 1)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_store_subscr_int(self):
        def testfunc(n):
            l = [0, 0, 0, 0]
            for _ in range(n):
                l[0] = 1
                l[1] = 2
                l[2] = 3
                l[3] = 4
            return sum(l)

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 10)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_STORE_SUBSCR_LIST_INT", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 1)
        # The loop variable also has an integer cleanup. Check only the
        # store operands, whose constant references are borrowed.
        for index, op in enumerate(uops):
            if op == "_STORE_SUBSCR_LIST_INT":
                self.assertEqual(uops[index + 1:index + 3],
                                 ["_POP_TOP_NOP", "_POP_TOP_NOP"])
        self.assertIn("_POP_TOP_NOP", uops)

    def test_store_attr_slot(self):
        class C:
            __slots__ = ('x',)

        def testfunc(n):
            c = C()
            for _ in range(n):
                c.x = 42
                y = c.x
            return y

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 42)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        if Py_GIL_DISABLED:
            self.assertIn("_STORE_ATTR_SLOT", uops)
            self.assertIn("_POP_TOP_NOP", uops)
        else:
            self.assertTrue(any(op.startswith("_STORE_CONST_ATTRIBUTE_")
                                for op in uops))

    def test_store_subscr_dict(self):
        def testfunc(n):
            d = {}
            for _ in range(n):
                d['a'] = 1
                d['b'] = 2
                d['c'] = 3
                d['d'] = 4
            return sum(d.values())

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 10)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_STORE_SUBSCR_DICT_KNOWN_HASH", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 1)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_to_bool_str(self):
        def f(n):
            for i in range(n):
                false = i == TIER2_THRESHOLD
                empty = "X"[:false]
                if empty:
                    return 1
            return 0

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_TO_BOOL_STR", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 3)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_to_bool_int(self):
        def f(n):
            for i in range(n):
                truthy = (i == TIER2_THRESHOLD)
                x = 0 + truthy
                if x:
                    return 1
            return 0

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_TO_BOOL_INT", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 3)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_to_bool_noncompact_int(self):
        # gh-155486: non-compact exact integer should remain specialized
        # as _TO_BOOL_INT in Tier 2.
        def f(n, value=1 << 100):
            for _ in range(n):
                if not value:
                    return 0
                # The second check should reuse the exact-int type established by the first guard.
                if not value:
                    return 0
            return 1

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_TO_BOOL_INT", uops)
        self.assertLessEqual(count_ops(ex, "_GUARD_TOS_EXACT_INT"), 1)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertEqual(f(3, 0), 0)
        self.assertEqual(f(3, -(1 << 100)), 1)

    def test_to_bool_list(self):
        def f(n):
            for i in range(n):
                lst = [] if i != TIER2_THRESHOLD else [1]
                if lst:
                    return 1
            return 0

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, 0)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_TO_BOOL_LIST", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 3)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_to_bool_always_true(self):
        def testfunc(n):
            class A:
                pass

            a = A()
            for _ in range(n):
                if not a:
                    return 0
            return 1

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertNotIn("_REPLACE_WITH_TRUE", uops)

    def test_attr_promotion_failure(self):
        # We're not testing for any specific uops here, just
        # testing it doesn't crash.
        script_helper.assert_python_ok('-c', textwrap.dedent("""
        import _testinternalcapi
        import _opcode
        import email

        def get_first_executor(func):
            code = func.__code__
            co_code = code.co_code
            for i in range(0, len(co_code), 2):
                try:
                    return _opcode.get_executor(code, i)
                except ValueError:
                    pass
            return None

        def testfunc(n):
            for _ in range(n):
                email.jit_testing = None
                prompt = email.jit_testing
                del email.jit_testing


        testfunc(_testinternalcapi.TIER2_THRESHOLD)
        """))

    def test_discard_none_after_direct_argument_return(self):
        def testfunc(n):
            for _ in range(n):
                global_identity(None)

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_PUSH_FRAME" if Py_GIL_DISABLED else
                      "_CALL_RETURN_ARGUMENT", uops)
        self.assertIn("_POP_TOP", uops)


    def test_pop_top_specialize_int(self):
        def testfunc(n):
            for _ in range(n):
                global_identity(100000)

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # Constant immortalization depends on how the test code was loaded.
        # Borrowed immortal constants need no decref, in either frontend.
        constant, = testfunc.__code__.co_consts
        expected = "_POP_TOP_NOP" if sys._is_immortal(constant) else "_POP_TOP_INT"
        self.assertIn("_POP_TOP" if Py_GIL_DISABLED else expected, uops)

    def test_discard_float_after_direct_argument_return(self):
        def testfunc(n):
            for _ in range(n):
                global_identity(1e6)

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_PUSH_FRAME" if Py_GIL_DISABLED else
                      "_CALL_RETURN_ARGUMENT", uops)
        self.assertIn("_POP_TOP", uops)
        constant, = testfunc.__code__.co_consts
        references = sys.getrefcount(constant)
        testfunc(TIER2_THRESHOLD)
        self.assertEqual(sys.getrefcount(constant), references)


    def test_unary_negative_long_float_type(self):
        def testfunc(n):
            for _ in range(n):
                a = 9397
                f = 9397.0
                x = -a + -a
                y = -f + -f

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertNotIn("_GUARD_TOS_INT", uops)
        self.assertNotIn("_GUARD_NOS_INT", uops)
        self.assertNotIn("_GUARD_TOS_FLOAT", uops)
        self.assertNotIn("_GUARD_NOS_FLOAT", uops)

    def test_binary_op_constant_evaluate(self):
        def testfunc(n):
            for _ in range(n):
                2 ** 65

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        # For now... until we constant propagate it away.
        self.assertIn("_BINARY_OP", uops)

    def test_jitted_code_sees_changed_globals(self):
        "Issue 136154: Check that jitted code spots the change in the globals"

        def make_f():
            def f():
                return GLOBAL_136154
            return f

        make_f_with_bad_globals = types.FunctionType(make_f.__code__, {})

        def jitted(funcs):
            for func in funcs:
                func()

        # Make a "good" f:
        f = make_f()
        # Compile jitted for the "good" f:
        jitted([f] * TIER2_THRESHOLD)
        # This "bad" f has different globals, but the *same* code/function versions:
        f_with_bad_globals = make_f_with_bad_globals()
        # A "good" f to enter the JIT code, and a "bad" f to trigger the bug:
        with self.assertRaises(NameError):
            jitted([f, f_with_bad_globals])

    def test_reference_tracking_across_call_doesnt_crash(self):

        def f1():
            for _ in range(TIER2_THRESHOLD + 1):
                # Choose a value that won't occur elsewhere to avoid sharing
                str("value that won't occur elsewhere to avoid sharing")

        f1()

        def f2():
            for _ in range(TIER2_THRESHOLD + 1):
                # Choose a value that won't occur elsewhere to avoid sharing
                tuple((31, -17, 25, "won't occur elsewhere"))

        f2()

    def test_next_instr_for_exception_handler_set(self):
        # gh-140104: We just want the exception to be caught properly.
        def f():
            for i in range(TIER2_THRESHOLD + 3):
                try:
                    undefined_variable(i)
                except Exception:
                    pass

        f()

    def test_next_instr_for_exception_handler_set_lasts_instr(self):
        # gh-140104: We just want the exception to be caught properly.
        def f():
            a_list = []
            for _ in range(TIER2_THRESHOLD + 3):
                try:
                    a_list[""] = 0
                except Exception:
                    pass

        f()

    def test_interpreter_finalization_with_generator_alive(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import sys
            t = tuple(range(%d))
            def simple_for():
                for x in t:
                    x

            def gen():
                try:
                    yield
                except:
                    simple_for()

            sys.settrace(lambda *args: None)
            simple_for()
            g = gen()
            next(g)
        """ % _testinternalcapi.SPECIALIZATION_THRESHOLD))

    def test_nested_loop_osr_has_no_side_executors(self):
        def f(n, offset):
            for x in range(n):
                for y in range(n):
                    z = x + y + offset
            return z

        n = TIER2_THRESHOLD + 3
        self.assertEqual(f(n, 0), 2 * (n - 1))
        executors = get_all_executors(f)
        # The inner loop warms first, but its static CFG also contains the
        # outer loop. Both backedges stay inside this method executor.
        self.assertEqual(len(executors), 1)
        executor = executors[0]
        self.assertGreaterEqual(get_opnames(executor).count('_METHOD_JUMP'), 2)
        self.assertEqual(f(2, 1.5), 3.5)
        self.assertTrue(executor.is_valid())
        self.assertEqual(get_all_executors(f), executors)
        self.assertFalse(hasattr(_testinternalcapi, 'get_exit_executor'))
        _testinternalcapi.invalidate_executors(f.__code__)
        self.assertFalse(executor.is_valid())
        self.assertEqual(f(n, 0), 2 * (n - 1))
        self.assertEqual(len(get_all_executors(f)), 1)

    def test_jit_shutdown_after_nested_method_osr(self):
        script_helper.assert_python_ok("-c", textwrap.dedent(f"""
            def f():
                for x in range({TIER2_THRESHOLD + 3}):
                    for y in range({TIER2_THRESHOLD + 3}):
                        z = x + y

            f()
        """), PYTHON_JIT="1")

    def test_enter_executor_valid_op_arg(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import sys
            sys.setrecursionlimit(30) # reduce time of the run

            str_v1 = ''
            tuple_v2 = (None, None, None, None, None)
            small_int_v3 = 4

            def f1():

                for _ in range(10):
                    abs(0)

                tuple_v2[small_int_v3]
                tuple_v2[small_int_v3]
                tuple_v2[small_int_v3]

                def recursive_wrapper_4569():
                    str_v1 > str_v1
                    str_v1 > str_v1
                    str_v1 > str_v1
                    recursive_wrapper_4569()

                recursive_wrapper_4569()

            for i_f1 in range(19000):
                try:
                    f1()
                except RecursionError:
                    pass
        """))

    def test_attribute_changes_are_watched(self):
        # Just running to make sure it doesn't crash.
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            from concurrent.futures import ThreadPoolExecutor
            from unittest import TestCase
            NTHREADS = 6
            BOTTOM = 0
            TOP = 1250000
            class A:
                attr = 10**1000
            class TestType(TestCase):
                def read(id0):
                    for _ in range(BOTTOM, TOP):
                        A.attr
                def write(id0):
                    x = A.attr
                    x += 1
                    A.attr = x
                    with ThreadPoolExecutor(NTHREADS) as pool:
                        pool.submit(read, (1,))
                        pool.submit(write, (1,))
        """))

    def test_handling_of_tos_cache_with_side_exits(self):
        # https://github.com/python/cpython/issues/142718
        class EvilAttr:
            def __init__(self, d):
                self.d = d

            def __del__(self):
                try:
                    del self.d['attr']
                except Exception:
                    pass

        class Obj:
            pass

        obj = Obj()
        obj.__dict__ = {}

        for _ in range(TIER2_THRESHOLD+1):
            obj.attr = EvilAttr(obj.__dict__)

    def test_promoted_global_refcount_eliminated(self):
        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        import _testinternalcapi
        import opcode
        import _opcode

        def get_first_executor(func):
            code = func.__code__
            co_code = code.co_code
            for i in range(0, len(co_code), 2):
                try:
                    return _opcode.get_executor(code, i)
                except ValueError:
                    pass
            return None

        def get_opnames(ex):
            return {item[0] for item in ex}


        def testfunc(n):
            y = []
            for i in range(n):
                x = tuple(y)
            return x

        testfunc(_testinternalcapi.TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        assert ex is not None
        uops = get_opnames(ex)
        assert "_LOAD_GLOBAL_BUILTIN" not in uops
        assert "_LOAD_CONST_INLINE_BORROW" in uops
        assert "_POP_TOP_NOP" in uops
        pop_top_count = len([opname for opname in ex if opname == "_POP_TOP" ])
        assert pop_top_count <= 2
        """), PYTHON_JIT="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_constant_fold_tuple(self):
        def testfunc(n):
            for _ in range(n):
                t = (1,)
                p = len(t)

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertNotIn("_CALL_LEN", uops)

    def test_binary_subscr_list_int(self):
        def testfunc(n):
            l = [1]
            x = 0
            for _ in range(n):
                y = l[0]
                x += y
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BINARY_OP_SUBSCR_LIST_CONST", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_binary_subscr_tuple_int(self):
        def testfunc(n):
            t = (1,)
            x = 0
            for _ in range(n):
                y = t[0]
                x += y
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn(("_BINARY_OP_SUBSCR_TUPLE_INT" if Py_GIL_DISABLED else
                       "_BINARY_OP_SUBSCR_BORROWED_1"), uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_binary_subscr_frozendict_lowering(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                x += FROZEN_DICT_CONST['x']
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertGreaterEqual(count_ops(ex, "_LOAD_CONST_INLINE_BORROW"),
                                1 if Py_GIL_DISABLED else 2)
        self.assertNotIn("_BINARY_OP_SUBSCR_DICT", uops)

    def test_binary_subscr_frozendict_const_fold(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                if FROZEN_DICT_CONST['x'] == 1:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertGreaterEqual(count_ops(ex, "_LOAD_CONST_INLINE_BORROW"), 3)
        # lookup result is folded to constant 1, so comparison is optimized away
        if Py_GIL_DISABLED:
            self.assertIn("_BINARY_OP_SUBSCR_DICT_KNOWN_HASH", uops)
        else:
            self.assertNotIn("_COMPARE_OP_INT", uops)

    def test_contains_op_frozenset_const_fold(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                if 1 in FROZEN_SET_CONST:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertGreaterEqual(count_ops(ex, "_LOAD_CONST_INLINE_BORROW"),
                                2 if Py_GIL_DISABLED else 3)
        if Py_GIL_DISABLED:
            self.assertIn("_CONTAINS_OP_SET", uops)
        else:
            self.assertNotIn("_CONTAINS_OP_SET", uops)

    def test_contains_op_frozendict_const_fold(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                if 'x' in FROZEN_DICT_CONST:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertGreaterEqual(count_ops(ex, "_LOAD_CONST_INLINE_BORROW"),
                                2 if Py_GIL_DISABLED else 3)
        if Py_GIL_DISABLED:
            self.assertIn("_CONTAINS_OP_DICT", uops)
        else:
            self.assertNotIn("_CONTAINS_OP_DICT", uops)

    def test_not_contains_op_frozendict_const_fold(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                if 'z' not in FROZEN_DICT_CONST:
                    x += 1
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertGreaterEqual(count_ops(ex, "_LOAD_CONST_INLINE_BORROW"),
                                2 if Py_GIL_DISABLED else 3)
        if Py_GIL_DISABLED:
            self.assertIn("_CONTAINS_OP_DICT", uops)
        else:
            self.assertNotIn("_CONTAINS_OP_DICT", uops)

    def test_binary_subscr_list_slice(self):
        def testfunc(n):
            x = 0
            l = [1, 2, 3]
            for _ in range(n):
                x += l[0:1][0]
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)

        self.assertIn("_BINARY_OP_SUBSCR_LIST_SLICE", uops)
        self.assertNotIn("_GUARD_TOS_LIST", uops)
        # Cleanup also appears in the method's other basic blocks.
        self.assertIn("_POP_TOP_NOP", uops)

    def test_is_op(self):
        def test_is_false(n):
            a = object()
            b = object()
            for _ in range(n):
                res = a is b
            return res

        res, ex = self._run_with_optimizer(test_is_false, TIER2_THRESHOLD)
        self.assertEqual(res, False)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_IS_OP", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)


        def test_is_true(n):
            a = object()
            for _ in range(n):
                res = a is a
            return res

        res, ex = self._run_with_optimizer(test_is_true, TIER2_THRESHOLD)
        self.assertEqual(res, True)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_IS_OP", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)


        def test_is_not(n):
            a = object()
            b = object()
            for _ in range(n):
                res = a is not b
            return res

        res, ex = self._run_with_optimizer(test_is_not, TIER2_THRESHOLD)
        self.assertEqual(res, True)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_IS_OP", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)


        def test_is_none(n):
            a = None
            for _ in range(n):
                res = a is None
            return res

        res, ex = self._run_with_optimizer(test_is_none, TIER2_THRESHOLD)
        self.assertEqual(res, True)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_IS_OP", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_is_true_method_branches(self):
        def f(n, value=None):
            def return_true():
                return True

            hits = 0
            v = return_true() if value is None else value
            for i in range(n):
                if v is True:
                    hits += v + 1
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD * 2)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BINARY_OP", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(f(3, False), 0)


    def test_borrowed_none_test_in_method(self):
        def testfunc(n):
            value = None
            hits = 0
            for _ in range(n):
                if value is None:
                    hits += 1
            return hits

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertNotIn("_IS_NONE", uops)
        self.assertIn("_IS_NONE_BORROW", uops)
        self.assertIn("_METHOD_POP_JUMP_IF_TRUE", uops)
        self.assertIn("_POP_TOP_NOP", uops)

    def test_borrowed_none_test_both_branches(self):
        def count_none(values):
            hits = 0
            for value in values:
                if value is None:
                    hits += 1
            return hits

        marker = object()
        for common, rare, expected in (
            (marker, None, 1),
            (None, marker, TIER2_THRESHOLD),
        ):
            with self.subTest(common_is_none=common is None), clear_executors(count_none):
                values = [common] * TIER2_THRESHOLD + [rare]
                self.assertEqual(count_none(values), expected)
                ops = get_opnames(get_first_executor(count_none))
                self.assertIn("_IS_NONE_BORROW", ops)
                self.assertIn("_METHOD_POP_JUMP_IF_TRUE", ops)
                self.assertEqual(count_none(values), expected)

    @unittest.skipIf(Py_GIL_DISABLED, "Inline values can change concurrently")
    def test_repeated_inline_values_guard(self):
        class Record:
            pass

        record = Record()
        record.a, record.b = 10, 20

        def read(count, obj):
            result = 0
            for _ in range(count):
                result += obj.a + obj.b
            return result

        self.assertEqual(read(TIER2_THRESHOLD, record), 30 * TIER2_THRESHOLD)
        ops = get_opnames(get_first_executor(read))
        self.assertEqual(ops.count("_CHECK_MANAGED_OBJECT_HAS_VALUES"), 1)
        record.__dict__ = {"a": 40, "b": 50}
        self.assertEqual(read(TIER2_THRESHOLD, record), 90 * TIER2_THRESHOLD)

    @unittest.skipIf(Py_GIL_DISABLED, "Shared-reference optimization requires GIL")
    def test_discard_result_owned_by_local(self):
        events = []

        class Value:
            def __del__(self):
                events.append("released")

        def identity(value):
            return value

        def discard(count, value):
            for _ in range(count):
                identity(value)

        value = Value()
        discard(TIER2_THRESHOLD, value)
        ops = get_opnames(get_first_executor(discard))
        self.assertIn("_POP_TOP", ops)
        references = sys.getrefcount(value)
        discard(TIER2_THRESHOLD, value)
        self.assertEqual(sys.getrefcount(value), references)
        self.assertEqual(events, [])
        del value
        self.assertEqual(events, ["released"])

    @unittest.skipIf(Py_GIL_DISABLED, "Shared-reference optimization requires GIL")
    def test_discard_owner_embedded_in_executor(self):
        class Record:
            def __init__(self):
                self.value = 10

        namespace = {"record": Record()}
        exec("def read(count):\n"
             "    result = 0\n"
             "    for _ in range(count):\n"
             "        result += record.value\n"
             "    return result\n", namespace)
        read = namespace["read"]
        self.assertEqual(read(TIER2_THRESHOLD), 10 * TIER2_THRESHOLD)
        ops = get_opnames(get_first_executor(read))
        self.assertIn("_POP_TOP", ops)
        replacement = Record()
        replacement.value = 20
        namespace["record"] = replacement
        self.assertEqual(read(TIER2_THRESHOLD), 20 * TIER2_THRESHOLD)

    @unittest.skipIf(Py_GIL_DISABLED, "Attribute regions require GIL")
    def test_global_integer_attribute_update(self):
        class Record:
            def __init__(self):
                self.value = 0

        namespace = {"record": Record()}
        exec("def update(count):\n"
             "    for _ in range(count):\n"
             "        record.value += 1\n", namespace)
        update = namespace["update"]
        record = namespace["record"]
        update(TIER2_THRESHOLD)
        self.assertEqual(record.value, TIER2_THRESHOLD)
        ops = get_opnames(get_first_executor(update))
        self.assertIn("_UPDATE_INT_ATTRIBUTE_STACK", ops)
        for initial in (255, -6, 2**30 - 1, 2**60, -2**60, 1.5):
            with self.subTest(initial=initial):
                # A new integer permits reuse; the expected value stays
                # independently owned so mutation cannot hide a failure.
                record.value = type(initial)(str(initial))
                update(2)
                self.assertEqual(record.value, initial + 2)
        record.value = int("1000")
        alias = record.value
        update(2)
        self.assertEqual(alias, 1000)
        self.assertEqual(record.value, 1002)
        record.__dict__ = {"value": 40}
        update(2)
        self.assertEqual(record.value, 42)

    @unittest.skipIf(Py_GIL_DISABLED, "Attribute regions require GIL")
    def test_temporary_integer_attribute_update_lifetime(self):
        events = []

        class Record:
            def __init__(self):
                self.value = 0

            def __del__(self):
                events.append(self.value)

        def make():
            return Record()

        def update(count):
            for _ in range(count):
                make().value += 1

        update(TIER2_THRESHOLD)
        ops = get_opnames(get_first_executor(update))
        self.assertIn("_UPDATE_INT_ATTRIBUTE_STACK", ops)
        self.assertEqual(events, [1] * TIER2_THRESHOLD)
        update(3)
        self.assertEqual(events, [1] * (TIER2_THRESHOLD + 3))

    def test_inline_values_guard_after_callback(self):
        class Record:
            pass

        record = Record()
        record.a, record.b = 10, 20

        def read(count, obj, callback):
            result = 0
            for _ in range(count):
                first = obj.a
                callback()
                result += first + obj.b
            return result

        def changes():
            for _ in range(TIER2_THRESHOLD):
                yield
            while True:
                record.__dict__ = {"a": 40, "b": 50}
                yield

        callback = changes().__next__
        self.assertEqual(read(TIER2_THRESHOLD, record, callback),
                         30 * TIER2_THRESHOLD)
        self.assertEqual(read(2, record, callback), 60 + 90)

    def test_is_false_method_branches(self):
        def f(n, value=None):
            def return_false():
                return False

            hits = 0
            v = return_false() if value is None else value
            for i in range(n):
                if v is False:
                    hits += v + 1
            return hits

        res, ex = self._run_with_optimizer(f, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_BINARY_OP", uops)
        self.assertTrue(any(op.startswith("_METHOD_POP_JUMP_IF_") for op in uops))
        self.assertEqual(f(3, True), 0)


    def test_for_iter_generator_osr(self):
        def gen(n):
            for i in range(n):
                yield i + i
        def consume(n):
            total = 0
            for value in gen(n):
                total += value
            return total
        count = TIER2_THRESHOLD * 2
        self.assertEqual(consume(count), count * (count - 1))
        self.assertIsNotNone(get_first_executor(gen))

    def test_send_generator_tier1_fallback(self):
        def gen(n):
            for i in range(n):
                yield i + i
            return 'finished'
        completed = []
        def send_gen(n):
            completed.append((yield from gen(n)))
        def consume(n):
            total = 0
            for value in send_gen(n):
                total += value
            return total
        for _ in range(_testinternalcapi.SPECIALIZATION_THRESHOLD):
            self.assertEqual(consume(10), 90)
        completed.clear()
        count = TIER2_THRESHOLD * 2
        self.assertEqual(consume(count), count * (count - 1))
        self.assertEqual(completed, ['finished'])
        self.assertIsNotNone(get_first_executor(gen))
        self.assertIsNone(get_first_executor(send_gen))

    def test_send_list_tier1_fallback(self):
        def send_list(n):
            yield from list(range(n))
        def consume(n):
            total = 0
            for value in send_list(n):
                total += value
            return total
        for _ in range(_testinternalcapi.SPECIALIZATION_THRESHOLD):
            self.assertEqual(consume(10), 45)
        count = TIER2_THRESHOLD * 2
        self.assertEqual(consume(count), count * (count - 1) // 2)
        self.assertIsNone(get_first_executor(send_list))

    def test_binary_op_subscr_init_frame(self):
        class B:
            def __getitem__(self, other):
                return other + 1
        def testfunc(*args):
            n, b = args[0]
            for _ in range(n):
                y = b[2]
            return y

        res, ex = self._run_with_optimizer(testfunc, (TIER2_THRESHOLD, B()))
        self.assertEqual(res, 3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_METHOD_DEOPT" if Py_GIL_DISABLED else
                      "_BINARY_OP_SUBSCR_INIT_CALL", uops)
        if not Py_GIL_DISABLED:
            self.assertGreaterEqual(count_ops(ex, "_POP_TOP_NOP"), 1)

    def test_load_attr_property_uses_general_call(self):
        class B:
            @property
            def prop(self):
                return 3
        def testfunc(*args):
            n, b = args[0]
            for _ in range(n):
                y = b.prop + b.prop
            return y

        testfunc((3, B()))
        res, ex = self._run_with_optimizer(testfunc, (TIER2_THRESHOLD, B()))
        self.assertEqual(res, 6)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_LOAD_ATTR", uops)
        self.assertNotIn("_LOAD_ATTR_PROPERTY_FRAME", uops)

    def test_load_attr_getattribute_uses_general_call(self):
        class B:
            def __getattribute__(self, name):
                return len(name)

        def testfunc(n):
            b = B()
            y = 0
            for _ in range(n):
                y += b.x + b.y
            return y

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        self.assertEqual(res, 2 * TIER2_THRESHOLD)
        uops = get_opnames(ex)
        self.assertIn("_LOAD_ATTR", uops)
        B.__getattribute__ = lambda self, name: 10
        self.assertEqual(testfunc(5), 100)

    def test_load_attr_property_observes_code_change(self):
        class C:
            @property
            def val(self):
                return int(1)

        fget = C.val.fget

        def testfunc(*args):
            n, c = args[0]
            total = 0
            for _ in range(n):
                total += c.val
            return total

        testfunc((3, C()))
        res, ex = self._run_with_optimizer(testfunc, (TIER2_THRESHOLD, C()))
        self.assertEqual(res, TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        # Property calls leave the method and look up the current getter.
        self.assertIn("_LOAD_ATTR", uops)
        fget.__code__ = (lambda self: 2).__code__
        res = testfunc((TIER2_THRESHOLD, C()))
        self.assertEqual(res, TIER2_THRESHOLD * 2)

    def test_unary_negative(self):
        def testfunc(n):
            a = 3
            for _ in range(n):
                res = -a
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, -3)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_UNARY_NEGATIVE", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_unary_invert(self):
        def testfunc(n):
            a = 3
            for _ in range(n):
                res = ~a
            return res

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, -4)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)

        self.assertIn("_UNARY_INVERT", uops)
        self.assertIn("_POP_TOP_NOP", uops)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_make_function(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                func = lambda: 1
                x += func()
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)

        self.assertIn("_MAKE_FUNCTION", uops)
        self.assertEqual(uops.count("_POP_TOP_NOP"), 1 if Py_GIL_DISABLED else 2)

    def test_iter_check_list(self):
        def testfunc(n):
            x = 0
            for _ in range(n):
                l = [1]
                for num in l:
                    x += num
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)

        self.assertIn("_BUILD_LIST", uops)
        self.assertIn("_ITER_CHECK_LIST", uops)

    def test_match_class(self):
        def testfunc(n):
            class A:
                val = 1
            x = A()
            ret = 0
            for _ in range(n):
                match x:
                    case A():
                        ret += x.val
            return ret

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, TIER2_THRESHOLD)
        uops = get_opnames(ex)

        self.assertIn("_MATCH_CLASS", uops)
        self.assertEqual(count_ops(ex, "_POP_TOP_NOP"), 4)

    def test_dict_update(self):
        def testfunc(n):
            d = {1: 2, 3: 4}
            for _ in range(n):
                x = {**d}
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, {1: 2, 3: 4})
        uops = get_opnames(ex)

        self.assertIn("_DICT_UPDATE", uops)
        self.assertEqual(count_ops(ex, "_POP_TOP_NOP"), 1)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_set_update(self):
        def testfunc(n):
            s = {1, 2, 3}
            for _ in range(n):
                x = {*s}
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, {1, 2, 3})
        uops = get_opnames(ex)

        self.assertIn("_SET_UPDATE", uops)
        self.assertEqual(count_ops(ex, "_POP_TOP_NOP"), 1)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_dict_merge(self):
        def testfunc(n):
            d = {"a": 1, "b": 2}
            def f(**kwargs):
                return kwargs
            for _ in range(n):
                x = f(**d)
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, {"a": 1, "b": 2})
        uops = get_opnames(ex)

        self.assertIn("_DICT_MERGE", uops)
        self.assertEqual(count_ops(ex, "_POP_TOP_NOP"), 1)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_list_extend(self):
        def testfunc(n):
            a = [1, 2, 3]
            for _ in range(n):
                x = [*a]
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, [1, 2, 3])
        uops = get_opnames(ex)

        self.assertIn("_LIST_EXTEND", uops)
        self.assertGreaterEqual(count_ops(ex, "_POP_TOP_NOP"), 1)
        self.assertLessEqual(count_ops(ex, "_POP_TOP"), 2)

    def test_143026(self):
        # https://github.com/python/cpython/issues/143026

        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        import gc
        thresholds = gc.get_threshold()
        try:
            gc.set_threshold(1)

            def f1():
                for i in range(5000):
                    globals()[''] = i

            f1()
        finally:
            gc.set_threshold(*thresholds)
        """), PYTHON_JIT="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_143092(self):
        def f1():
            a = "a"
            for i in range(50):
                x = a[i % len(a)]

            s = ""
            for _ in range(10):
                s += ""

            class A: ...
            class B: ...

            match s:
                case int(): ...
                case str(): ...
                case dict(): ...

            (
                u0,
                *u1,
                u2,
                u4,
                u5,
                u6,
                u7,
                u8,
                u9, u10, u11,
                u12, u13, u14, u15, u16, u17, u18, u19, u20, u21, u22, u23, u24, u25, u26, u27, u28, u29,
            ) = [None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
                 None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
                 None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
                 None, None, None, None, None, None, None, None,]

            s = ""
            for _ in range(10):
                s += ""
                s += ""

        for i in range(TIER2_THRESHOLD * 10):
            f1()

    def test_143183(self):
        # https://github.com/python/cpython/issues/143183

        result = script_helper.run_python_until_end('-c', textwrap.dedent(f"""
        def f1():
            class AsyncIter:
                def __init__(self):
                    self.limit = 0
                    self.count = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if self.count >= self.limit:
                        ...
                    self.count += 1j

            class AsyncCtx:
                async def async_for_driver():
                    try:
                        for _ in range({TIER2_THRESHOLD}):
                            try:
                                async for _ in AsyncIter():
                                    ...
                            except TypeError:
                                ...
                    except Exception:
                        ...

                c = async_for_driver()
                while True:
                    try:
                        c.send(None)
                    except StopIteration:
                        break

        for _ in range({TIER2_THRESHOLD // 40}):
            f1()
        """), PYTHON_JIT="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_143358(self):
        # https://github.com/python/cpython/issues/143358

        result = script_helper.run_python_until_end('-c', textwrap.dedent(f"""
        def f1():

            class EvilIterator:

                def __init__(self):
                    self._items = [1, 2]
                    self._index = 1

                def __iter__(self):
                    return self

                def __next__(self):
                    if not len(self._items) % 13:
                        self._items.clear()

                    for i_loop_9279 in range(10):
                        self._items.extend([1, "", None])

                    if not len(self._items) % 11:
                        return 'unexpected_type_from_iterator'

                    if self._index >= len(self._items):
                        raise StopIteration

                    item = self._items[self._index]
                    self._index += 1
                    return item

            evil_iter = EvilIterator()

            large_num = 2**31
            for _ in range(400):
                try:
                    _ = [x + y for x in evil_iter for y in evil_iter if evil_iter._items.append(x) or large_num]
                except TypeError:
                    pass

        f1()
        """), PYTHON_JIT="1", PYTHON_JIT_STRESS="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_149335_trace_buffer_guard(self):
        # https://github.com/python/cpython/issues/149335

        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        import sys

        def f1():
            for i_3178 in 0, 2, 10:
                mv162 = 162

            mv3 = mv1 = mv_165 = mv16 = \
            mv167 = mv168 = \
            mv169 = \
                mv_1403_170 = \
                169

            mv_1403_170

            mv_172 = mv_3 = mv_4 = mv175 = mv176 = mv17 = mv178 = mv179 = mv0 = mv1 = mv182 = (
            mv3
            ) = mv4 = mv185 = mv186 = mv187 = mv18 = mv189 = mv0 = mv1 = mv192 = mv3 = mv4 = (
            mv195
            ) = mv196 = mv197 = mv_198 = mv19 = mv0 = mv1 = mv2 = mv3 = mv4 = mv05 = mv06 = (
            mv07
            ) = mv08 = mv09 = mv0 = mv1 = mv2 = mv3 = mv4 = mv15 = mv16 = mv17 = mv18 = mv19 = (
            mv0
            ) = mv1 = mv_2 = mv3 = mv4 = mv_25 = mv_26 = mv_27 = mv_28 = mv_29 = mv0 = mv1 = (
            mv2
            ) = mv_1403 = mv4 = mv35 = mv36 = mv37 = mv38 = mv39 = mv0 = -sys.maxsize / 3

            mv1 = mv_12 = mv3 = mv_14 = mv45 = sys.float_info.epsilon
            mv46 = sys.float_info.epsilon

        for i in range(15000):
            f1()
        """), PYTHON_JIT="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_144068_daemon_thread_jit_cleanup(self):
        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        import threading
        import time

        def hot_loop():
            end = time.time() + 5.0
            while time.time() < end:
                pass

        # Create a daemon thread that will be abandoned at shutdown
        t = threading.Thread(target=hot_loop, daemon=True)
        t.start()

        time.sleep(0.1)
        """), PYTHON_JIT="1", ASAN_OPTIONS="detect_leaks=1")
        self.assertEqual(result[0].rc, 0, result)
        stderr = result[0].err.decode('utf-8', errors='replace')
        self.assertNotIn('LeakSanitizer', stderr,
                         f"Memory leak detected by ASan:\n{stderr}")
        self.assertNotIn('_PyJit_TryInitializeTracing', stderr,
                         f"JIT tracer memory leak detected:\n{stderr}")

    def test_cold_exit_on_init_cleanup_frame(self):

        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        class A:
            __slots__ = ('x', 'y', 'z', 'w')
            def __init__(self):
                self.x = self.y = -1
                self.z = self.w = None

        class B(A):
            __slots__ = ('a', 'b', 'c', 'd', 'e')
            def __init__(self):
                super().__init__()
                self.a = self.b = None
                self.c = ""
                self.d = self.e = False

        class C(B):
            __slots__ = ('name', 'flag')
            def __init__(self, name):
                super().__init__()
                self.name = name
                self.flag = False

        funcs = []
        for n in range(20, 80):
            lines = [f"def f{n}(names, info):"]
            for j in range(n):
                lines.append(f"    v{j} = names[{j % 3}]")
                if j % 3 == 0:
                    lines.append(f"    if v{j} in info:")
                    lines.append(f"        v{j} = info[v{j}]")
                elif j % 5 == 0:
                    lines.append(f"    v{j} = len(v{j}) if isinstance(v{j}, str) else 0")
            lines.append("    return C(names[0])")
            ns = {'C': C}
            exec("\\n".join(lines), ns)
            funcs.append(ns[f"f{n}"])

        names = ['alpha', 'beta', 'gamma']
        info = {'alpha': 'x', 'beta': 'y', 'gamma': 'z'}

        for f in funcs:
            for _ in range(10):
                f(names, info)
        """), PYTHON_JIT="1", PYTHON_JIT_STRESS="1",
             PYTHON_JIT_SIDE_EXIT_INITIAL_VALUE="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_for_iter_gen_cleared_frame_does_not_crash(self):
        # See: https://github.com/python/cpython/issues/145197
        result = script_helper.run_python_until_end('-c', textwrap.dedent("""
        def g():
            yield 1
            yield 2

        for _ in range(4002):
            for _ in g():
                pass

        for i in range(4002):
            it = g()
            if (i & 7) == 0:
                next(it)
                it.close()
            for _ in it:
                pass
        """),
        PYTHON_JIT="1", PYTHON_JIT_STRESS="1")
        self.assertEqual(result[0].rc, 0, result)

    def test_call_kw(self):
        def func(a):
            return int(a) * 42

        def testfunc(n):
            x = 0
            for _ in range(n):
                x += func(a=1)
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 42 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertIn("_CHECK_FUNCTION_VERSION_KW", uops)
        # Check the optimizer has optmized through the function call
        # by promoting global `int` to a constant.
        self.assertNotIn("_LOAD_GLOBAL_BUILTINS", uops)
        self.assertIn("_CALL_BUILTIN_CLASS", uops)

    def test_call_kw_bound_method(self):
        class C:
            def method(self, a, b):
                return int(a) + int(b)

        def testfunc(n):
            obj = C()
            x = 0
            meth = obj.method
            for _ in range(n):
                x += meth(a=1, b=2)
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 3 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME", uops)
        self.assertIn("_CHECK_METHOD_VERSION_KW", uops)
        # Check the optimizer has optmized through the function call
        # by promoting global `int` to a constant.
        self.assertNotIn("_LOAD_GLOBAL_BUILTINS", uops)
        self.assertIn("_CALL_BUILTIN_CLASS", uops)

    def test_func_version_guarded_on_change(self):
        self.addCleanup(setattr, global_identity_code_will_be_modified,
                        "__code__", global_identity_code_will_be_modified.__code__)

        def testfunc(n):
            for i in range(n):
                # Only works on functions promoted to constants
                result = global_identity_code_will_be_modified(i)
            return result

        testfunc(TIER2_THRESHOLD)

        ex = get_first_executor(testfunc)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_PUSH_FRAME" if Py_GIL_DISABLED else
                      "_CALL_RETURN_ARGUMENT", uops)
        self.assertIn("_CHECK_FUNCTION_VERSION", uops)

        global_identity_code_will_be_modified.__code__ = (lambda a: 0xdeadead).__code__
        _testinternalcapi.clear_executor_deletion_list()
        ex = get_first_executor(testfunc)
        self.assertIsNone(ex)
        # The caller must observe the replacement code.
        self.assertEqual(testfunc(TIER2_THRESHOLD), 0xdeadead)

    def test_call_super(self):
        class A:
            def method1(self):
                return 42

            def method2(self):
                return 21

        class B(A):
            def method1(self):
                return super().method1()

            def method2(self):
                return super(B, self).method2()

        b = B()

        def testfunc(n):
            x = 0
            for _ in range(n):
                x += b.method1()
                x += b.method2()
            return x

        res, ex = self._run_with_optimizer(testfunc, TIER2_THRESHOLD)
        self.assertEqual(res, 63 * TIER2_THRESHOLD)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        self.assertIn("_LOAD_SUPER_ATTR_METHOD", uops)
        self.assertEqual(uops.count("_GUARD_LOAD_SUPER_ATTR_METHOD"), 2)
        self.assertTrue(ex.is_valid())
        # The dynamic super lookup observes the base class mutation.
        A.method1 = lambda self: 1
        # The caller may keep its dynamic lookup or compile again.
        res, ex = self._run_with_optimizer(testfunc, 4 * TIER2_THRESHOLD)
        self.assertEqual(res, 4 * 22 * TIER2_THRESHOLD)
        caller_entry = ex is not None
        if not caller_entry:
            ex = get_first_executor(B.method1)
        self.assertIsNotNone(ex)
        uops = get_opnames(ex)
        if caller_entry:
            self.assertIn("_LOAD_SUPER_ATTR_METHOD", uops)
        self.assertEqual(uops.count("_GUARD_LOAD_SUPER_ATTR_METHOD"), 2)
        A.method2 = lambda self: 2
        self.assertEqual(testfunc(10), 30)

    def test_settrace_then_polymorphic_call_does_not_crash(self):
        script_helper.assert_python_ok("-c", textwrap.dedent("""
            import sys
            sys.settrace(lambda *_: None)
            sys.settrace(None)

            class C:
                def __init__(self, x):
                    pass

            for i in 0, 1, 0, 1:
                C(0) if i else str(0)
        """))

    def test_load_special_type_guard_deopt(self):
        script_helper.assert_python_ok("-s", "-c", textwrap.dedent(f"""
            def f1():
                class Context:
                    def __enter__(self): ...
                    def __exit__(self, e, v, t): ...

                with Context():
                    pass

            for _ in range({TIER2_THRESHOLD + 5}):
                f1()
        """), PYTHON_JIT="1")

    @isolation.runInSubprocess(timeout=SHORT_TIMEOUT)
    def test_for_iter_kind_changes_after_warmup(self):
        def exhaust(iterator):
            for _ in iterator:
                pass

        values = range(TIER2_THRESHOLD)
        # Specialize and compile the loop with several iterator types.
        warmup_iterators = (
            iter(set(values)),
            iter(dict.fromkeys(values)),
            iter(values),
            enumerate(values),
            zip(values, values),
        )
        for iterator in warmup_iterators:
            exhaust(iterator)

        # A new iterator kind must still reach exhaustion.
        exhaust(map(bool, values))

def global_identity(x):
    return x

def global_identity_code_will_be_modified(x):
    return x

class TestObject:
    def test(self, *args, **kwargs):
        return args[0]

test_object = TestObject()
test_bound_method = TestObject.test.__get__(test_object)

class MyGlobalPoint:
    def __init__(self, x, y):
        return None

if __name__ == "__main__":
    unittest.main()
