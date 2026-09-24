"""Attribute acquisition through interpreter and specialized instructions."""

import _thread
import dis
import sys
import threading
import unittest
import weakref
from types import FunctionType, ModuleType

from test.support import gc_collect, requires_specialization, SHORT_TIMEOUT
from test.support.import_helper import import_module


def _read_super(cls, obj):
    super(cls, obj).value
    return 42


def _call_super(cls, obj):
    return super(cls, obj).value()


def _read_super_slot(cls, obj):
    return super.__getattribute__(super(cls, obj), 'value')


class AttributeVMAccessTests(unittest.TestCase):
    def test_builtin_subclass_in_worker(self):
        def work():
            class Error(Exception):
                def __str__(self):
                    return super().__str__()

            class List(list):
                def __len__(self):
                    return super().__len__()

            class Int(int):
                def bit_length(self):
                    return super().bit_length()

            error = Error('worker error')
            sequence = List((1, 2, 3))
            number = Int(42)
            for _ in range(100):
                assert str(error) == 'worker error'
                assert len(sequence) == 3
                assert number.bit_length() == 6
            assert Error.__shareable__ is threading.Shareable.LOCAL
            assert error.__shareable__ is threading.Shareable.LOCAL
            return 'ok'

        self.assertEqual(self.run_native(work), 'ok')

    @requires_specialization
    def test_super_attribute(self):
        calls = SynchronizedList()
        class Callable:
            def __call__(self):
                calls.append(True)
                return 42
        class ForeignDescriptor:
            def __get__(self, obj, cls):
                calls.append(True)
                return 42
        def factory(value):
            def method(self):
                nonlocal value
                # Keep this fixture LOCAL: read-only closures are shareable.
                value = value
                value.append(True)
                return 42
            return method
        getter = self.bytecode_getter()
        def work(payload, getter, call, descriptor):
            class Base:
                pass
            class Child(Base):
                pass
            obj = Child()
            template = _call_super if call else _read_super
            access = FunctionType(template.__code__.replace(), {})
            def wrap(value):
                if not descriptor:
                    return value
                def get(self, obj, cls, value=value):
                    return value
                class Descriptor:
                    pass
                Descriptor.__get__ = get
                return Descriptor()
            with sys.monitoring.StopTheWorld:
                Base.value = wrap(payload[0])
            try:
                access(Child, obj)
            except IllegalThreadAccessException:
                pass
            else:
                raise AssertionError('cold super lookup allowed access')
            # Exercise the super slot directly, without PyObject_GetAttr.
            if not call:
                try:
                    _read_super_slot(Child, obj)
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('super slot allowed access')
            def local(self):
                return 42
            def unbound():
                return 42
            good = (unbound if descriptor else local) if call else 42
            Base.value = wrap(good)
            for _ in range(100):
                assert access(Child, obj) == 42
            code = getter(access) if getter else access.__code__._co_code_adaptive
            with sys.monitoring.StopTheWorld:
                Base.value = wrap(payload[0])
            denied = 0
            for _ in range(100):
                try:
                    access(Child, obj)
                except IllegalThreadAccessException:
                    denied += 1
            Base.value = wrap(good if call else 43)
            assert access(Child, obj) == 42
            if not call:
                assert _read_super_slot(Child, obj) == 43
            return code, denied
        for kind in ('attribute', 'callable', 'method',
                     'descriptor_attribute', 'descriptor_callable',
                     'foreign_descriptor_attribute'):
            with self.subTest(kind=kind):
                if kind == 'method':
                    foreign = factory(calls)
                elif kind == 'foreign_descriptor_attribute':
                    foreign = ForeignDescriptor()
                else:
                    foreign = Callable()
                reference = weakref.ref(foreign)
                call = not kind.endswith('attribute')
                descriptor = kind.startswith('descriptor_')
                code, denied = self.run_native(work, (foreign,), getter, call, descriptor)
                self.assertEqual(denied, 100)
                opname = 'LOAD_SUPER_ATTR_METHOD' if call else 'LOAD_SUPER_ATTR_ATTR'
                self.assertIn(dis._all_opmap[opname],
                              [op for _, _, op, _ in dis._unpack_opargs(code)])
                del foreign
                gc_collect()
                self.assertIsNone(reference())
        self.assertEqual(list(calls), [])

    def test_deferred_class_attribute_lifetime(self):
        def factory(value):
            def local():
                nonlocal value
                value += 0
                return value
            return local
        foreign = factory(42)
        self.assertIs(foreign.__shareable__, threading.Shareable.LOCAL)
        reference = weakref.ref(foreign)
        def work(payload):
            class Holder:
                pass
            with sys.monitoring.StopTheWorld:
                Holder.value = payload[0]
            denied = 0
            for _ in range(100):
                try:
                    Holder.value
                except IllegalThreadAccessException:
                    denied += 1
            return denied
        self.assertEqual(self.run_native(work, (foreign,)), 100)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @requires_specialization
    def test_attribute_call(self):
        calls = SynchronizedList()
        class Callable:
            def __call__(self):
                calls.append(True)
                return 42
        foreign = Callable()
        def work(payload, getter):
            class Holder:
                pass
            holder = Holder()
            def local():
                return 42
            holder.value = local
            def call(obj):
                return obj.value()
            for _ in range(100):
                assert call(holder) == 42
            code = getter(call) if getter else call.__code__._co_code_adaptive
            with sys.monitoring.StopTheWorld:
                holder.value = payload[0]
            denied = 0
            for _ in range(100):
                try:
                    call(holder)
                except IllegalThreadAccessException:
                    denied += 1
            return code, denied
        code, denied = self.run_native(work, (foreign,), self.bytecode_getter())
        self.assertEqual(denied, 100)
        self.assertEqual(list(calls), [])
        self.assertIn(dis._all_opmap['LOAD_ATTR_INSTANCE_VALUE'],
                      [op for _, _, op, _ in dis._unpack_opargs(code)])

    def run_native(self, work, *args):
        results = threading.Channel()
        # No captured cells or shared Thread callback fields: this exercises
        # the VM boundary independently of threading's callback integration.
        def entry(work=work, args=args, results=results):
            try:
                result = work(*args)
            except BaseException as exc:
                trace = []
                tb = exc.__traceback__
                while tb is not None:
                    trace.append((tb.tb_frame.f_code.co_name, tb.tb_lineno))
                    tb = tb.tb_next
                results.put(('error', (str(exc), tuple(trace))))
            else:
                results.put(('ok', result))
        handle = _thread.start_joinable_thread(
            entry, group=threading.ThreadGroup())
        handle.join(SHORT_TIMEOUT)
        status, value = results.get()
        self.assertEqual(status, 'ok', value)
        return value

    def bytecode_getter(self):
        internal = import_module('_testinternalcapi')
        getter = getattr(internal, 'get_tlbc', None)
        if getter is not None:
            internal.object_declare_synchronized(getter)
        return getter

    @requires_specialization
    def test_stored_attribute(self):
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)
        getter = self.bytecode_getter()

        def work(payload, getter, kind):
            class Instance:
                pass
            class Slot:
                __slots__ = ('value',)
            if kind == 'instance':
                carrier = Instance()
            elif kind == 'slot':
                carrier = Slot()
            elif kind == 'module':
                carrier = ModuleType('attribute_vm_fixture')
            else:
                carrier = Instance
            def template(obj):
                # POP_TOP leaves no foreign result for an outer return check.
                obj.value
                return 42
            read = FunctionType(template.__code__.replace(), {})
            with sys.monitoring.StopTheWorld:
                carrier.value = payload[0]
            if kind in ('instance', 'slot'):
                try:
                    object.__getattribute__(carrier, 'value')
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('generic C getter allowed access')
            try:
                read(carrier)
            except IllegalThreadAccessException:
                pass
            else:
                raise AssertionError('cold attribute read allowed access')
            carrier.value = 42
            for _ in range(100):
                assert read(carrier) == 42
            code = getter(read) if getter else read.__code__._co_code_adaptive
            with sys.monitoring.StopTheWorld:
                carrier.value = payload[0]
            denied = 0
            for _ in range(100):
                try:
                    read(carrier)
                except IllegalThreadAccessException:
                    denied += 1
            carrier.value = 43
            assert read(carrier) == 42
            assert carrier.value == 43
            return code, denied

        for kind, opname in (('instance', 'LOAD_ATTR_INSTANCE_VALUE'),
                             ('slot', 'LOAD_ATTR_SLOT'),
                             ('module', 'LOAD_ATTR_MODULE'),
                             ('class', 'LOAD_ATTR_CLASS')):
            with self.subTest(kind=kind):
                code, denied = self.run_native(work, (foreign,), getter, kind)
                self.assertEqual(denied, 100)
                self.assertIn(dis._all_opmap[opname],
                              [op for _, _, op, _ in dis._unpack_opargs(code)])
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @requires_specialization
    def test_inlined_attribute_return_after_cleanup(self):
        for kind, opname in (('property', 'LOAD_ATTR_PROPERTY'),
                             ('getattribute', 'LOAD_ATTR_GETATTRIBUTE_OVERRIDDEN')):
            with self.subTest(kind=kind):
                self.check_inlined_return(kind, opname)

    def check_inlined_return(self, kind, opname):
        lock = threading.Lock()
        release = [False]
        class Cleanup:
            def __del__(self):
                if release[0]:
                    lock.__exit__(None, None, None)
        @freeze
        class Property:
            @property
            def value(self):
                cleanup = Cleanup()
                return self
        @freeze
        class Getattribute:
            def __getattribute__(self, name):
                if name != 'value':
                    return object.__getattribute__(self, name)
                cleanup = Cleanup()
                return self
        def template(obj):
            # Discard the attribute result so this frame's return check
            # cannot mask a missing check after the getter cleanup.
            obj.value
            return 42
        read = FunctionType(template.__code__.replace(), {})
        getter = self.bytecode_getter()
        lock.__enter__()
        try:
            carrier = lock.protect(
                Property() if kind == 'property' else Getattribute())
            for _ in range(100):
                self.assertEqual(read(carrier), 42)
            code = getter(read) if getter else read.__code__._co_code_adaptive
            self.assertIn(dis._all_opmap[opname],
                          [op for _, _, op, _ in dis._unpack_opargs(code)])
            release[0] = True
            with self.assertRaises(UnprotectedAccessException):
                read(carrier)
            self.assertFalse(lock.locked())
        finally:
            if lock.locked():
                lock.__exit__(None, None, None)

    @requires_specialization
    def test_specialized_accessor_native_receiver(self):
        @freeze
        class Property:
            @property
            def value(self):
                return self
        @freeze
        class Getattribute:
            def __getattribute__(self, name):
                return self
        getter = self.bytecode_getter()
        internal = import_module('_testinternalcapi')
        invoke = import_module('_testcapi').pyobject_vectorcall
        internal.object_declare_synchronized(invoke)
        def work(cls, payload, getter):
            def template(obj):
                return obj.value
            read = FunctionType(template.__code__.replace(), {})
            local = cls()
            for _ in range(100):
                assert read(local) is local
            code = getter(read) if getter else read.__code__._co_code_adaptive
            denied = 0
            for _ in range(100):
                try:
                    # Enter through C; the receiver may be rejected by
                    # LOAD_FAST before the specialized attribute instruction.
                    invoke(read, payload, None)
                except IllegalThreadAccessException:
                    denied += 1
            assert read(local) is local
            return code, denied
        for cls, opname in ((Property, 'LOAD_ATTR_PROPERTY'),
                            (Getattribute, 'LOAD_ATTR_GETATTRIBUTE_OVERRIDDEN')):
            with self.subTest(cls=cls):
                foreign = cls()
                reference = weakref.ref(foreign)
                code, denied = self.run_native(work, cls, (foreign,), getter)
                self.assertEqual(denied, 100)
                self.assertIn(dis._all_opmap[opname],
                              [op for _, _, op, _ in dis._unpack_opargs(code)])
                del foreign
                gc_collect()
                self.assertIsNone(reference())


if __name__ == '__main__':
    unittest.main()
