"""PEP 805 object metadata and C access-control primitives."""

import gc
import _thread
import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


_testinternalcapi = import_module('_testinternalcapi')

# These native test entry points deliberately inspect or declare object state.
# Share the entry points so a worker reaches the object check being tested.
_object_operation_from_tuple = _testinternalcapi.object_operation_from_tuple
_object_check_access = _testinternalcapi.object_check_access
_object_owner_id = _testinternalcapi.object_owner_id
_object_declare_immutable = _testinternalcapi.object_declare_immutable
_object_declare_synchronized = _testinternalcapi.object_declare_synchronized
_get_static_local_object = _testinternalcapi.get_static_local_object
for _helper in (_object_operation_from_tuple, _object_check_access,
                _object_owner_id, _object_declare_immutable,
                _object_declare_synchronized, _get_static_local_object):
    _object_declare_synchronized(_helper)
del _helper
Shareable = threading.Shareable


class ShareableTests(unittest.TestCase):
    def test_state_before_importing_threading(self):
        from test.support import script_helper
        script_helper.assert_python_ok('-S', '-c', '''
import sys
assert 'threading' not in sys.modules
local = object().__shareable__
immutable = (42).__shareable__
import threading
assert local is threading.Shareable.LOCAL
assert immutable is threading.Shareable.IMMUTABLE
''')

    @threading_helper.requires_working_threading()
    def test_builtin_constructor_entry_points(self):
        constructors = (tuple.__new__, list.__new__, dict.__new__)
        for constructor in constructors:
            self.assertIs(constructor.__shareable__, Shareable.SYNCHRONIZED)
        results = threading.Channel()
        def worker():
            for constructor in constructors:
                value = constructor(constructor.__self__)
                expected = Shareable.IMMUTABLE if isinstance(value, tuple) else Shareable.LOCAL
                assert value.__shareable__ is expected
                results.put(type(value).__name__)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get() for _ in constructors], ['tuple', 'list', 'dict'])

    @threading_helper.requires_working_threading()
    def test_state_singletons_in_worker(self):
        self.assertIs(Shareable.__shareable__, Shareable.IMMUTABLE)
        results = threading.Channel()
        def worker():
            local = []
            shared = threading.Lock()
            for _ in range(100):
                assert local.__shareable__ is Shareable.LOCAL
                assert shared.__shareable__ is Shareable.SYNCHRONIZED
                assert (42).__shareable__ is Shareable.IMMUTABLE
                assert Shareable.LOCAL.name == 'LOCAL'
                assert Shareable.LOCAL.value == 0
            results.put(True)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    @threading_helper.requires_working_threading()
    def test_native_descriptors_are_immutable(self):
        class Slotted:
            __slots__ = ('value',)

        descriptors = (list.append, dict.__dict__['fromkeys'], Slotted.value,
                       type.__dict__['__name__'], object.__str__)
        for descriptor in descriptors:
            self.assertIs(descriptor.__shareable__, Shareable.IMMUTABLE)
            self.assertEqual(_object_owner_id(descriptor), 0)
        results = threading.Channel()
        def worker():
            for descriptor in descriptors:
                _object_check_access(descriptor)
                assert isinstance(descriptor.__qualname__, str)
            # Creating a class looks up object.__init_subclass__ through
            # the checked dictionary API in super's descriptor lookup.
            class CreatedHere:
                pass
            results.put(CreatedHere.__shareable__ is Shareable.LOCAL)
            results.put(_object_owner_id(CreatedHere) ==
                        _object_owner_id([]))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get(), results.get()], [True, True])

    @threading_helper.requires_working_threading()
    def test_runtime_shared_namespaces(self):
        import builtins
        import copy

        for module in (builtins, threading, copy):
            self.assertIs(module.__shareable__, Shareable.SYNCHRONIZED)
            self.assertIs(type(module.__dict__), SynchronizedDict)
        for function in (builtins.__import__, len, print, id):
            self.assertIs(function.__shareable__, Shareable.SYNCHRONIZED)
        results = threading.Channel()
        def worker():
            # __shareable__ and Channel.put() import threading/copy through
            # the public C API, using this frame's builtin namespace.
            results.put([[].__shareable__.value])
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), [Shareable.LOCAL.value])

    def test_state_members_are_immutable(self):
        for name in ('name', 'value'):
            descriptor = Shareable.__dict__[name]
            self.assertIs(descriptor.__shareable__, Shareable.IMMUTABLE)
            with self.assertRaises(AttributeError):
                getattr(Shareable, name)
        for state in Shareable:
            self.assertIs(state.__shareable__, Shareable.IMMUTABLE)
            self.assertEqual(_object_owner_id(state), 0)
            self.assertIs(type(state.__dict__), frozendict)
            with self.assertRaises(TypeError):
                state.extra = 1

    def test_immutable_builtin_values(self):
        values = (None, True, False, Ellipsis, NotImplemented, 42,
                  10**100, 1.25, 1j, 'text', b'bytes', (), ([],),
                  frozenset(), frozenset({1}), frozendict(), range(5),
                  int, dict, RuntimeError,
                  self.test_immutable_builtin_values.__code__)
        for value in values:
            with self.subTest(type=type(value)):
                self.assertIs(value.__shareable__, Shareable.IMMUTABLE)
                self.assertEqual(_object_owner_id(value), 0)
                self.assertIs(_object_check_access(value), value)

    def test_local_values(self):
        class C:
            pass

        class IntSubclass(int):
            pass

        class TupleSubclass(tuple):
            pass

        values = (object(), [], {}, set(), bytearray(), C(), C,
                  IntSubclass(1), TupleSubclass())
        owner = _object_owner_id(values[0])
        self.assertGreater(owner, 0)
        for value in values:
            with self.subTest(type=type(value)):
                self.assertIs(value.__shareable__, Shareable.LOCAL)
                self.assertEqual(_object_owner_id(value), owner)
                self.assertIs(_object_check_access(value), value)

    def test_readonly_state(self):
        class C:
            pass

        for value in (C(), [], 1, object()):
            with self.subTest(type=type(value)):
                with self.assertRaisesRegex(TypeError, 'cannot assign to __shareable__'):
                    value.__shareable__ = Shareable.IMMUTABLE
                with self.assertRaisesRegex(TypeError, 'cannot assign to __shareable__'):
                    del value.__shareable__

    def test_extension_declarations(self):
        obj = object()
        _object_declare_synchronized(obj)
        self.assertIs(obj.__shareable__, Shareable.SYNCHRONIZED)
        self.assertEqual(_object_owner_id(obj), 0)
        _object_declare_synchronized(obj)
        _object_declare_immutable(obj)
        self.assertIs(obj.__shareable__, Shareable.IMMUTABLE)
        _object_declare_immutable(obj)
        with self.assertRaises(TypeError):
            _object_declare_synchronized(obj)

    def test_group_objects_are_immutable(self):
        self.assertIs(threading.ThreadGroup().__shareable__, Shareable.IMMUTABLE)

    def test_native_lock_is_synchronized(self):
        lock = threading.Lock()
        self.assertIs(lock.__shareable__, Shareable.SYNCHRONIZED)
        self.assertEqual(_object_owner_id(lock), 0)
        self.assertIs(threading.TransferBox(lock).claim(), lock)

    def test_native_rlock_is_synchronized(self):
        lock = threading.RLock()
        self.assertIs(lock.__shareable__, Shareable.SYNCHRONIZED)
        self.assertEqual(_object_owner_id(lock), 0)
        self.assertIs(threading.TransferBox(lock).claim(), lock)

        class Sublock(_thread.RLock):
            pass
        subclass = Sublock()
        self.assertIs(subclass.__shareable__, Shareable.LOCAL)
        subclass.value = []
        with subclass:
            with subclass:
                self.assertEqual(subclass._recursion_count(), 2)

    @threading_helper.requires_working_threading()
    def test_native_rlock_group_handoff(self):
        lock = threading.RLock()
        lock.acquire()
        lock.acquire()
        ready = threading.Lock()
        ready.acquire()
        results = threading.Channel()

        def worker():
            shared = _object_check_access(lock)
            denied = False
            try:
                shared.release()
            except RuntimeError:
                denied = True
            results.put((denied, shared.acquire(False), shared._recursion_count()))
            ready.release()
            with shared:
                with shared:
                    results.put(shared._recursion_count())

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            try:
                self.assertTrue(ready.acquire(timeout=SHORT_TIMEOUT))
                self.assertEqual(results.get(), (True, False, 0))
            finally:
                lock.release()
                lock.release()
        self.assertEqual(results.get(), 2)
        self.assertFalse(lock.locked())

    @threading_helper.requires_working_threading()
    def test_rlock_parallel_repr(self):
        lock = threading.RLock()
        barrier = threading.Barrier(2)
        results = threading.Channel()

        def worker():
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(2000):
                with lock:
                    with lock:
                        state = lock._release_save()
                        lock._acquire_restore(state)
            results.put(True)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            barrier.wait(timeout=SHORT_TIMEOUT)
            for _ in range(2000):
                self.assertIn('RLock object owner=', repr(lock))
                self.assertEqual(lock._recursion_count(), 0)
        self.assertTrue(results.get())
        self.assertFalse(lock.locked())

    @threading_helper.requires_working_threading()
    def test_native_lock_cross_group_access(self):
        lock = threading.Lock()
        lock.acquire()
        results = threading.Channel()

        def worker():
            shared = _object_check_access(lock)
            shared.release()
            results.put(shared is lock)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertFalse(lock.locked())

    def test_static_extension_objects_are_not_implicitly_immutable(self):
        obj = _get_static_local_object()
        self.assertIs(obj.__shareable__, Shareable.LOCAL)
        self.assertEqual(_object_owner_id(obj),
                         _object_owner_id(object()))

    @threading_helper.requires_working_threading()
    def test_cross_group_check(self):
        foreign = []
        shared = object()
        _object_declare_synchronized(shared)
        results = SynchronizedList()
        holder = (foreign,)

        def work():
            try:
                _object_operation_from_tuple(holder, "check")
            except IllegalThreadAccessException:
                results.append('denied')
            local = []
            results.append(_object_check_access(local) is local)
            results.append(_object_check_access(shared) is shared)
            results.append(_object_check_access(42) == 42)

        thread = threading.Thread(group=threading.ThreadGroup(), target=work)
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results, ['denied', True, True, True])

    @threading_helper.requires_working_threading()
    def test_same_group_access(self):
        obj = []
        results = []
        thread = threading.Thread(group=threading.current_thread().group,
                                  target=lambda: results.append(
                                      _object_check_access(obj) is obj))
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results, [True])

    @threading_helper.requires_working_threading()
    def test_foreign_declaration_is_rejected(self):
        obj = object()
        results = SynchronizedList()
        holder = (obj,)

        def work():
            for operation in ("immutable", "synchronized"):
                try:
                    _object_operation_from_tuple(holder, operation)
                except IllegalThreadAccessException:
                    results.append('denied')

        thread = threading.Thread(group=threading.ThreadGroup(), target=work)
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results, ['denied', 'denied'])
        self.assertIs(obj.__shareable__, Shareable.LOCAL)

    @threading_helper.requires_working_threading()
    def test_owner_ids_are_not_reused(self):
        ids = SynchronizedList()

        def work():
            ids.append(_object_owner_id([]))

        for _ in range(8):
            thread = threading.Thread(group=threading.ThreadGroup(), target=work)
            with threading_helper.start_threads([thread]):
                pass
            del thread
            gc.collect()
        self.assertEqual(len(set(ids)), 8)
        self.assertTrue(all(owner > 0 for owner in ids))


if __name__ == '__main__':
    unittest.main()
