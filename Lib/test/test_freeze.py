"""Tests for the PEP 805 freezing protocol."""

import sys
import threading
import unittest
import weakref

from test.support import gc_collect, nomemtest, swap_attr, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


class FreezeTests(unittest.TestCase):
    def test_freeze_sentinel(self):
        value = sentinel('missing', repr='<missing>')
        self.assertIs(value.__shareable__, threading.Shareable.LOCAL)
        value.__module__ = 'before'
        self.assertIs(freeze(value), value)
        self.assertIs(freeze(value), value)
        self.assertIs(value.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertEqual(repr(value), '<missing>')
        for setter in (lambda: setattr(value, '__module__', 'after'),
                       lambda: delattr(value, '__module__'),
                       lambda: sentinel.__dict__['__module__'].__set__(value, 'after')):
            with self.assertRaises(TypeError):
                setter()
        self.assertEqual(value.__module__, 'before')

    @threading_helper.requires_working_threading()
    def test_shared_sentinel(self):
        class Name(str):
            pass
        shared = freeze(sentinel('missing'))
        foreign_name = freeze(sentinel(Name('foreign')))
        foreign_repr = freeze(sentinel('foreign', repr=Name('repr')))
        results = threading.Channel()
        def worker():
            assert repr(shared) == 'missing'
            assert shared.__reduce__() == 'missing'
            assert freeze(shared) is shared
            denied = 0
            for read in (lambda: repr(foreign_name),
                         foreign_name.__reduce__,
                         lambda: repr(foreign_repr)):
                try:
                    read()
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 3)

    def test_audit_hook_freezes_class_during_assignment(self):
        assert_python_ok('-c', '''
import sys
import threading

armed = False
def hook(event, args):
    global armed
    if armed and event == 'object.__setattr__' and args[0] is C:
        armed = False
        freeze(C)
sys.addaudithook(hook)

class Base: pass
class Other: pass
for synchronized in (False, True):
    for direct in (False, True):
        for name, value in (
            ('__name__', 'changed'),
            ('__qualname__', 'changed'),
            ('__module__', 'changed'),
            ('__doc__', 'changed'),
            ('__bases__', (Other,)),
            ('__type_params__', (int,)),
        ):
            class C(Base): pass
            if synchronized:
                C.synchronize()
            original = getattr(C, name)
            armed = True
            try:
                if direct:
                    type.__dict__[name].__set__(C, value)
                else:
                    setattr(C, name, value)
            except TypeError:
                pass
            else:
                raise AssertionError((synchronized, direct, name))
            assert not armed, name
            assert getattr(C, name) == original, name
            assert C.__shareable__ is threading.Shareable.IMMUTABLE
''')

    def test_class_decorator(self):
        @freeze
        class C:
            value = []

            def method(self):
                return 42

        self.assertIs(C.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(type(C.__dict__), frozendict)
        self.assertIs(vars(C), C.__dict__)
        self.assertIs(freeze(C), C)
        self.assertEqual(C().method(), 42)
        obj = C()
        obj.x = 1
        self.assertIs(obj.__shareable__, threading.Shareable.LOCAL)
        C.value.append(1)
        self.assertEqual(C.value, [1])
        for write in (lambda: setattr(C, 'x', 1),
                      lambda: delattr(C, 'value'),
                      lambda: type.__setattr__(C, 'x', 1),
                      lambda: type.__delattr__(C, 'value'),
                      lambda: type.__dict__['__name__'].__set__(C, 'Other'),
                      lambda: type.__dict__['__bases__'].__set__(C, (object,)),
                      lambda: type.__dict__['__annotations__'].__set__(C, {})):
            with self.subTest(write=write), self.assertRaisesRegex(TypeError, 'frozen'):
                write()

    def test_class_freezing_is_shallow(self):
        class Base:
            def method(self):
                return 1

        @freeze
        class C(Base):
            def call_super(self):
                return super().method()

        obj = C()
        for _ in range(1000):
            self.assertEqual(obj.method(), 1)
        Base.method = lambda self: 2
        self.assertEqual(obj.method(), 2)
        self.assertEqual(obj.call_super(), 2)
        self.assertIs(Base.__shareable__, threading.Shareable.LOCAL)

    def test_frozen_class_can_be_subclassed(self):
        @freeze
        class Base:
            def __len__(self):
                return 3

        class C(Base):
            pass

        self.assertEqual(len(C()), 3)
        C.x = 4
        self.assertIs(C.__shareable__, threading.Shareable.LOCAL)
        self.assertIn('x', dir(C))

    def test_frozen_subclass_slot_updates(self):
        class Base:
            def __len__(self):
                return 1

        @freeze
        class Inherited(Base):
            pass

        @freeze
        class Overridden(Base):
            def __len__(self):
                return 3

        Base.__len__ = lambda self: 2
        self.assertEqual(len(Inherited()), 2)
        self.assertEqual(len(Overridden()), 3)

    def test_frozen_class_and_instance(self):
        @freeze
        class C:
            def __init__(self):
                self.x = 42
                self.__freeze__()

        obj = C()
        self.assertEqual(obj.x, 42)
        self.assertIs(obj.__shareable__, threading.Shareable.IMMUTABLE)
        with self.assertRaisesRegex(TypeError, 'frozen'):
            obj.x = 43

    def test_class_with_python_metaclass(self):
        class Meta(type):
            pass

        @freeze
        class C(metaclass=Meta):
            pass

        self.assertIs(C.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(Meta.__shareable__, threading.Shareable.LOCAL)
        with self.assertRaisesRegex(TypeError, 'frozen'):
            C.x = 1

    def test_class_dictionary_identity(self):
        capi = import_module('_testinternalcapi')
        # Obtain the real namespace through the C API, not a mappingproxy.
        class C:
            x = 1

        namespace = capi.type_get_dict(C)
        proxy = C.__dict__
        keys = proxy.keys()
        iterator = iter(proxy)
        original_keys = list(proxy)
        for _ in range(1000):
            self.assertEqual(C.x, 1)
        freeze(C)
        self.assertIs(type(capi.type_get_dict(C)), frozendict)
        self.assertIs(capi.type_get_dict(C), namespace)
        self.assertIs(C.__dict__, namespace)
        self.assertEqual(list(keys), original_keys)
        self.assertEqual(list(iterator), original_keys)
        self.assertEqual(proxy['x'], 1)
        with self.assertRaises(TypeError):
            namespace['x'] = 2
        self.assertEqual(C.x, 1)

    def test_class_freeze_during_annotations(self):
        class C:
            pass

        def annotate(format):
            freeze(C)
            return {'self': C}

        C.__annotate__ = annotate
        annotations = C.__annotations__
        self.assertEqual(annotations, {'self': C})
        self.assertIs(C.__annotations__, annotations)

    def test_class_namespace_watcher(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        class C:
            x = 1

        namespace = internal.type_get_dict(C)
        watcher = capi.add_dict_watcher(0)
        try:
            capi.watch_dict(watcher, namespace)
            freeze(C)
            freeze(C)
            self.assertEqual(capi.get_dict_watcher_events(), ['freeze'])
        finally:
            capi.unwatch_dict(watcher, namespace)
            capi.clear_dict_watcher(watcher)

    def test_class_annotations_during_freeze_notification(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        class C:
            x: int = 1

        namespace = internal.type_get_dict(C)
        results = []

        def hook(unraisable):
            # The watcher error runs this callback during the transition,
            # after the dictionary freezes but before the class is published.
            results.append(C.__annotations__)
            for operation in (lambda: setattr(C, 'x', 2), lambda: freeze(C)):
                try:
                    operation()
                except Exception as exc:
                    results.append(type(exc))

        watcher = capi.add_dict_watcher(1)
        try:
            capi.watch_dict(watcher, namespace)
            with swap_attr(sys, 'unraisablehook', hook):
                freeze(C)
            self.assertEqual(results, [{'x': int}, TypeError, TypeError])
            self.assertIs(C.__annotations__, results[0])
            self.assertEqual(C.x, 1)
        finally:
            capi.unwatch_dict(watcher, namespace)
            capi.clear_dict_watcher(watcher)

    def test_frozen_class_annotations_remain_lazy(self):
        @freeze
        class C:
            x: C

        annotations = C.__annotations__
        self.assertEqual(annotations, {'x': C})
        self.assertIs(C.__annotations__, annotations)

        @freeze
        class Empty:
            pass

        self.assertIsNone(Empty.__annotate__)
        self.assertEqual(Empty.__annotations__, {})
        self.assertIs(Empty.__annotations__, Empty.__annotations__)

    def test_frozen_class_cycle(self):
        class C:
            pass

        C.self = C
        ref = weakref.ref(C)
        freeze(C)
        self.assertIs(C.self, C)
        del C
        gc_collect()
        self.assertIsNone(ref())

    def test_frozen_class_annotation_cache_cycle(self):
        @freeze
        class C:
            x: C

        self.assertIs(C.__annotations__['x'], C)
        ref = weakref.ref(C)
        del C
        gc_collect()
        self.assertIsNone(ref())

    @nomemtest
    def test_class_allocation_failure_rolls_back(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi
            from threading import Shareable

            failures = 0
            for start in range(40):
                class C:
                    x = 1
                failed = False
                _testcapi.set_nomemory(start, start + 1)
                try:
                    freeze(C)
                except MemoryError:
                    failed = True
                finally:
                    _testcapi.remove_mem_hooks()
                assert C.x == 1
                if failed:
                    failures += 1
                    assert C.__shareable__ is Shareable.LOCAL
                    C.x = 2
                    assert C.x == 2
                else:
                    assert C.__shareable__ is Shareable.IMMUTABLE
            assert failures > 0
        ''')

    def test_immutable_builtin_subclasses(self):
        for base, value in ((int, 42), (float, 1.5), (complex, 2j),
                            (str, 'abc'), (bytes, b'abc'), (tuple, (1, 2)),
                            (frozenset, {1, 2}), (frozendict, {'a': 1})):
            with self.subTest(base=base):
                class C(base):
                    pass

                obj = C(value)
                obj.extra = []
                alias = obj.__dict__
                self.assertIs(obj.__shareable__, threading.Shareable.LOCAL)
                self.assertIs(freeze(obj), obj)
                self.assertEqual(obj, value)
                self.assertIs(obj.__shareable__, threading.Shareable.IMMUTABLE)
                self.assertIs(type(obj.__dict__), frozendict)
                with self.assertRaisesRegex(TypeError, 'frozen'):
                    obj.extra = None
                self.assertIs(obj.__dict__, alias)
                with self.assertRaises(TypeError):
                    alias['extra'] = None
                self.assertEqual(obj.extra, [])
                obj.extra.append(1)
                self.assertEqual(obj.extra, [1])

    def test_immutable_builtin_subclass_slots(self):
        class C(str):
            __slots__ = ('extra',)

        obj = C('abc')
        obj.extra = 1
        freeze(obj)
        self.assertEqual(obj, 'abc')
        self.assertEqual(obj.extra, 1)
        with self.assertRaisesRegex(TypeError, 'frozen'):
            C.extra.__set__(obj, 2)

    def test_immutable_builtin_subclass_cycles(self):
        for base, value in ((int, 42), (float, 1.5), (complex, 2j),
                            (str, 'abc'), (bytes, b'abc'), (tuple, (1, 2)),
                            (frozenset, {1, 2}), (frozendict, {'a': 1})):
            with self.subTest(base=base):
                finalized = []

                class C(base):
                    def __del__(self):
                        finalized.append(True)

                obj = C(value)
                obj.ref = obj
                freeze(obj)
                del obj
                gc_collect()
                self.assertEqual(finalized, [True])

    def test_mutable_native_bases_require_freezing_support(self):
        capi = import_module('_testcapi')
        for base in (list, dict, set, bytearray, capi.HeapGcCType):
            with self.subTest(base=base):
                class C(base):
                    pass

                obj = C()
                obj.extra = 1
                with self.assertRaisesRegex(TypeError, 'cannot freeze'):
                    freeze(obj)
                self.assertIs(obj.__shareable__, threading.Shareable.LOCAL)
                obj.extra = 2
                self.assertEqual(obj.extra, 2)

    def test_instance_dictionary(self):
        class C:
            pass

        child = []
        obj = C()
        obj.child = child
        old_dict = obj.__dict__
        self.assertIs(freeze(obj), obj)
        self.assertIs(type(obj.__dict__), frozendict)
        self.assertIs(obj.__dict__, old_dict)
        self.assertIs(obj.child, child)
        self.assertIn('child', dir(obj))
        self.assertIs(obj.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(freeze(obj), obj)
        with self.assertRaises(TypeError):
            obj.__dict__['child'] = None
        with self.assertRaises(TypeError):
            old_dict['child'] = None
        self.assertIs(obj.child, child)
        child.append(1)
        self.assertEqual(obj.child, [1])
        for write in (lambda: setattr(obj, 'child', None),
                      lambda: delattr(obj, 'child'),
                      lambda: object.__setattr__(obj, 'child', None),
                      lambda: object.__delattr__(obj, 'child'),
                      lambda: setattr(obj, '__dict__', {}),
                      lambda: delattr(obj, '__dict__'),
                      lambda: C.__dict__['__dict__'].__set__(obj, {}),
                      lambda: object.__dict__['__class__'].__set__(obj, C)):
            with self.subTest(write=write), self.assertRaisesRegex(TypeError, 'frozen'):
                write()

    def test_empty_dictionary(self):
        class C:
            pass

        obj = freeze(C())
        self.assertEqual(obj.__dict__, frozendict())
        self.assertIs(type(obj.__dict__), frozendict)

    def test_c_api_attribute_writes(self):
        capi = import_module('_testlimitedcapi')

        class C:
            pass

        obj = freeze(C())
        with self.assertRaisesRegex(TypeError, 'frozen'):
            capi.object_setattr(obj, 'x', 1)
        with self.assertRaisesRegex(TypeError, 'frozen'):
            capi.object_setattrstring(obj, b'x', 1)

    def test_cycle_collection(self):
        class C:
            pass

        obj = C()
        obj.self = obj
        ref = weakref.ref(obj)
        freeze(obj)
        self.assertIs(obj.self, obj)
        del obj
        gc_collect()
        self.assertIsNone(ref())

    @nomemtest
    def test_allocation_failure_rolls_back(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import _testcapi
            from threading import Shareable

            class C:
                pass

            failures = 0
            for materialize in (False, True):
                for start in range(40):
                    obj = C()
                    obj.x = 1
                    if materialize:
                        obj.__dict__
                    failed = False
                    _testcapi.set_nomemory(start, start + 1)
                    try:
                        freeze(obj)
                    except MemoryError:
                        failed = True
                    finally:
                        _testcapi.remove_mem_hooks()
                    assert obj.x == 1
                    if failed:
                        failures += 1
                        assert obj.__shareable__ is Shareable.LOCAL
                        obj.x = 2
                        assert obj.x == 2
                    else:
                        assert obj.__shareable__ is Shareable.IMMUTABLE
            assert failures > 0
        ''')

    def test_slots(self):
        class Base:
            __slots__ = ('x',)

        class C(Base):
            __slots__ = ('y',)

        obj = C()
        obj.x, obj.y = 1, 2
        descriptor = Base.x
        freeze(obj)
        self.assertEqual((obj.x, obj.y), (1, 2))
        for write in (lambda: setattr(obj, 'x', 3),
                      lambda: setattr(obj, 'y', 3),
                      lambda: delattr(obj, 'x'),
                      lambda: descriptor.__set__(obj, 3),
                      lambda: descriptor.__delete__(obj)):
            with self.subTest(write=write), self.assertRaisesRegex(TypeError, 'frozen'):
                write()

    def test_shared_instance_namespace(self):
        class C:
            pass

        obj, alias = C(), C()
        obj.x = 1
        alias.__dict__ = obj.__dict__
        namespace = obj.__dict__
        keys = namespace.keys()
        iterator = iter(namespace)

        def write(value):
            value.x = 2

        for _ in range(200):
            write(alias)
        freeze(obj)
        self.assertIs(obj.__dict__, namespace)
        self.assertIs(alias.__dict__, namespace)
        self.assertEqual(list(keys), ['x'])
        self.assertEqual(list(iterator), ['x'])
        self.assertEqual(alias.x, 2)
        with self.assertRaises(TypeError):
            write(alias)
        # Freezing a shared namespace does not freeze its other owners.
        self.assertIs(alias.__shareable__, threading.Shareable.LOCAL)
        alias.__dict__ = {'x': 3}
        self.assertEqual(alias.x, 3)
        self.assertEqual(obj.x, 2)

    def test_split_namespace_is_detached(self):
        class C:
            pass

        obj, peer = C(), C()
        obj.x = peer.x = 1
        namespace = obj.__dict__
        freeze(obj)
        peer.x = 2
        peer.y = 3
        self.assertIs(obj.__dict__, namespace)
        self.assertEqual(namespace, {'x': 1})
        self.assertEqual(peer.__dict__, {'x': 2, 'y': 3})

    def test_already_frozen_instance_namespace(self):
        class C:
            pass

        obj = C()
        obj.x = 1
        namespace = freeze(obj.__dict__)
        self.assertIs(freeze(obj).__dict__, namespace)
        self.assertEqual(obj.x, 1)

    def test_dictionary_subclass_callbacks_not_called(self):
        class D(dict):
            def __iter__(self):
                raise AssertionError('iteration override must not be called')

            def keys(self):
                raise AssertionError('keys override called')

            def __getitem__(self, key):
                raise AssertionError('getitem override called')

        class C:
            pass

        obj = C()
        obj.__dict__ = D(x=1)
        freeze(obj)
        self.assertEqual(obj.x, 1)
        self.assertIs(type(obj.__dict__), frozendict)

    def test_overridden_setattr(self):
        calls = []

        class C:
            def __setattr__(self, name, value):
                calls.append(name)
                object.__setattr__(self, name, value)

        obj = freeze(C())
        with self.assertRaisesRegex(TypeError, 'frozen'):
            obj.x = 1
        self.assertEqual(calls, [])

    def test_specialized_attribute_writes(self):
        class Inline:
            pass

        class Slotted:
            __slots__ = ('x',)

        for cls, materialize in ((Inline, False), (Inline, True), (Slotted, False)):
            with self.subTest(cls=cls, materialize=materialize):
                obj = cls()
                obj.x = 0
                if materialize:
                    obj.__dict__ = {'x': 0}

                def write(value):
                    obj.x = value

                def read():
                    return obj.x

                for i in range(1000):
                    write(i)
                    self.assertEqual(read(), i)
                freeze(obj)
                for i in range(100):
                    with self.assertRaisesRegex(TypeError, 'frozen'):
                        write(i)
                    self.assertEqual(read(), 999)

    def test_immutable_identity(self):
        child = []
        for obj in (None, True, 42, 1.5, 2j, 'text', b'bytes', (child,),
                    frozenset({1}), frozendict(a=child), range(3),
                    Ellipsis, NotImplemented):
            with self.subTest(type=type(obj)):
                self.assertIs(freeze(obj), obj)
                self.assertIs(obj.__freeze__(), obj)
                self.assertIs(obj.__shareable__, threading.Shareable.IMMUTABLE)
        # Freezing does not recurse into the objects referenced by a value.
        self.assertIs(child.__shareable__, threading.Shareable.LOCAL)
        child.append(1)

    def test_immutable_builtin_class(self):
        self.assertIs(freeze(int), int)

    def test_plain_object(self):
        obj = object()
        self.assertIs(obj.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(freeze(obj), obj)
        self.assertIs(obj.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(freeze(obj), obj)

    def test_special_method_lookup(self):
        calls = []

        class C:
            def __freeze__(self):
                calls.append(self)
                return self

        obj = C()
        obj.__freeze__ = lambda: self.fail('instance override was used')
        self.assertIs(freeze(obj), obj)
        self.assertEqual(calls, [obj])

    def test_decorator(self):
        calls = []

        class Meta(type):
            def __freeze__(cls):
                calls.append(cls)
                return cls

        @freeze
        class C(metaclass=Meta):
            pass

        self.assertEqual(calls, [C])

    def test_exception_propagation(self):
        class C:
            def __freeze__(self):
                raise ValueError('freeze failed')

        with self.assertRaisesRegex(ValueError, 'freeze failed'):
            freeze(C())

        class Descriptor:
            def __get__(self, instance, owner):
                raise RuntimeError('lookup failed')

        class D:
            __freeze__ = Descriptor()

        with self.assertRaisesRegex(RuntimeError, 'lookup failed'):
            freeze(D())

    def test_unsupported_extension(self):
        # No immutability promise is inferred for extension instances.
        obj = bytearray(b'abc')
        with self.assertRaisesRegex(TypeError, 'cannot freeze'):
            freeze(obj)
        self.assertIs(obj.__shareable__, threading.Shareable.LOCAL)
        obj.append(100)

    def test_arguments(self):
        with self.assertRaises(TypeError):
            freeze()
        with self.assertRaises(TypeError):
            freeze(1, 2)
        with self.assertRaises(TypeError):
            freeze(obj=1)

    @threading_helper.requires_working_threading()
    def test_foreign_owner_rejected_before_callback(self):
        internal = import_module('_testinternalcapi')
        operation = internal.object_operation_from_tuple
        internal.object_declare_synchronized(operation)
        calls = SynchronizedList()
        errors = SynchronizedList()

        class C:
            def __freeze__(self):
                calls.append(self)
                return self

        obj = C()

        def work(holder):
            try:
                operation(holder, "freeze")
            except IllegalThreadAccessException:
                errors.append('denied')

        thread = threading.Thread(group=threading.ThreadGroup(), target=work,
                                  args=((obj,),))
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(list(calls), [])
        self.assertEqual(list(errors), ['denied'])


if __name__ == '__main__':
    unittest.main()
