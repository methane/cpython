"""Synchronized namespace storage for threads and threading primitives."""

import gc
import threading
import unittest
import weakref

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


threading_helper.requires_working_threading(module=True)


class ThreadSharingTests(unittest.TestCase):
    def test_synchronized_weak_reference(self):
        shared = threading.Event()
        reference = weakref.ref(shared)
        self.assertIs(reference.__shareable__, threading.Shareable.SYNCHRONIZED)
        class Reference(weakref.ref):
            pass
        self.assertIs(Reference(shared).__shareable__, threading.Shareable.LOCAL)
        class Local:
            pass
        local = Local()
        self.assertIs(weakref.ref(local).__shareable__, threading.Shareable.LOCAL)
        results = threading.Channel()
        def worker():
            assert reference() is shared
            results.put(True)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    def test_registry_weak_lifetime(self):
        registry = threading._ThreadRegistry()
        self.assert_shared(registry)
        value = threading.Event()
        reference = weakref.ref(value)
        registry.add(value)
        registry.add(value)
        self.assertEqual(len(registry), 1)
        self.assertEqual(list(registry), [value])
        copy = registry.copy()
        self.assertEqual(copy, registry)
        self.assertIsNot(copy, registry)
        del value
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(len(registry), 0)
        self.assertEqual(len(copy), 0)

    def test_weak_reference_rechecks_target_state(self):
        import types
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        getter = capi.pyweakref_getref
        object_getter = capi.pyweakref_getobject
        internal.object_declare_synchronized(getter)
        internal.object_declare_synchronized(object_getter)
        def target():
            return 42
        reference = weakref.ref(target)
        self.assertIs(reference.__shareable__, threading.Shareable.SYNCHRONIZED)
        with self.assertWarns(DeprecationWarning):
            capi.function_set_closure(target, (types.CellType(1),))
        self.assertIs(target.__shareable__, threading.Shareable.LOCAL)
        results = threading.Channel()
        def worker():
            for read in (reference, lambda: getter(reference),
                         lambda: object_getter(reference)):
                for _ in range(100):
                    try:
                        read()
                    except IllegalThreadAccessException:
                        pass
                    else:
                        results.put(False)
                        return
            results.put(True)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(reference(), target)
        del target
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(getter(reference), 0)

    def test_registry_registration_and_collection_between_groups(self):
        registry = threading._ThreadRegistry()
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker():
            values = [threading.Event() for _ in range(100)]
            for value in values:
                registry.add(value)
            barrier.wait(SHORT_TIMEOUT)
            assert len(list(registry)) == 400
            barrier.wait(SHORT_TIMEOUT)
            values.clear()
            del value
            results.put(True)
        threads = [threading.Thread(target=worker, group=threading.ThreadGroup())
                   for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertTrue(all(results.get() for _ in threads))
        gc.collect()
        self.assertEqual(len(registry), 0)

    def test_construct_primitives_in_worker(self):
        results = threading.Channel()
        def worker():
            for factory in (threading._PyRLock, threading.Condition,
                            threading.Semaphore, threading.BoundedSemaphore):
                primitive = factory()
                assert primitive.__shareable__ is threading.Shareable.SYNCHRONIZED
                assert type(primitive.__dict__) is SynchronizedDict
                with primitive:
                    pass
            event = threading.Event()
            event.set()
            assert event.wait(0)
            event.clear()
            assert not event.is_set()
            barrier = threading.Barrier(1)
            assert barrier.wait(SHORT_TIMEOUT) == 0
            results.put(True)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())

    def test_primitive_states(self):
        for factory in (threading._PyRLock, threading.Condition, threading.Event,
                        threading.Semaphore, threading.BoundedSemaphore,
                        lambda: threading.Barrier(2)):
            with self.subTest(factory=factory):
                primitive = factory()
                self.assert_shared(primitive)
                if isinstance(primitive, threading.Condition):
                    self.assertIs(type(primitive._waiters), SynchronizedList)

    def test_recursive_condition_between_groups(self):
        for factory in (threading.RLock, threading._PyRLock):
            with self.subTest(factory=factory):
                self.check_recursive_condition(factory)

    def check_recursive_condition(self, factory):
        lock = factory()
        condition = threading.Condition(lock)
        ready = threading.Event()
        finished = threading.Event()
        results = threading.Channel()
        def worker():
            with condition:
                condition.acquire()
                try:
                    ready.set()
                    assert condition.wait_for(finished.is_set, SHORT_TIMEOUT)
                    assert lock._recursion_count() == 2
                    results.put(True)
                finally:
                    condition.release()
        self.assertIs(worker.__shareable__, threading.Shareable.SYNCHRONIZED)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            with condition:
                finished.set()
                condition.notify()
        self.assertTrue(results.get())

    def test_semaphore_between_groups(self):
        for factory in (threading.Semaphore, threading.BoundedSemaphore):
            with self.subTest(factory=factory):
                self.check_semaphore(factory)

    def check_semaphore(self, factory):
        semaphore = factory()
        semaphore.acquire()
        ready = threading.Event()
        results = threading.Channel()
        def worker():
            ready.set()
            assert semaphore.acquire(timeout=SHORT_TIMEOUT)
            semaphore.release()
            results.put(True)
        self.assertIs(worker.__shareable__, threading.Shareable.SYNCHRONIZED)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            semaphore.release()
        self.assertTrue(results.get())

    def assert_shared(self, thread):
        internal = import_module('_testinternalcapi')
        self.assertIs(thread.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertEqual(internal.object_owner_id(thread), 0)
        self.assertIs(type(thread.__dict__), SynchronizedDict)
        self.assertEqual(internal.object_owner_id(thread.__dict__), 0)
        self.assertIs(internal.object_check_access(thread), thread)
        self.assertIs(threading.TransferBox(thread).claim(), thread)

    def test_thread_lifecycle(self):
        self.assert_shared(threading.main_thread())
        results = threading.Channel()
        def target():
            current = threading.current_thread()
            assert current.__shareable__ is threading.Shareable.SYNCHRONIZED
            assert type(current.__dict__) is SynchronizedDict
            results.put(current)
        thread = threading.Thread(target=target, group=threading.ThreadGroup())
        self.assert_shared(thread)
        with threading_helper.start_threads([thread]):
            pass
        self.assertIs(results.get(), thread)
        self.assert_shared(thread)
        self.assertFalse(thread.is_alive())

    def test_dummy_thread(self):
        import _thread
        results = threading.Channel()
        def target():
            results.put(threading.current_thread())
        with threading_helper.wait_threads_exit():
            handle = _thread.start_joinable_thread(target, group=threading.ThreadGroup())
            handle.join(SHORT_TIMEOUT)
        dummy = results.get()
        self.assertIsInstance(dummy, threading._DummyThread)
        self.assert_shared(dummy)

    def test_subclass_and_weakrefs(self):
        class Worker(threading.Thread):
            __slots__ = ('extra',)
            def run(self):
                self.completed = True
        thread = Worker(group=threading.ThreadGroup())
        thread.extra = 42
        ref = weakref.ref(thread)
        self.assert_shared(thread)
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(thread.completed)
        self.assertEqual(thread.extra, 42)
        self.assertIs(ref(), thread)
        self.assertIs(thread.__weakref__, ref)

    def test_namespace_replacement(self):
        capi = import_module('_testcapi')
        for setter in (lambda obj, value: setattr(obj, '__dict__', value),
                       capi.function_set_dict):
            thread = threading.Thread()
            namespace = dict(thread.__dict__)
            namespace['extra'] = 42
            setter(thread, namespace)
            self.assertIs(thread.__dict__, namespace)
            self.assertIs(type(namespace), SynchronizedDict)
            self.assertEqual(thread.extra, 42)
            self.assertFalse(thread.is_alive())
            with self.assertRaises(TypeError):
                setter(thread, None)
            self.assertIs(thread.__dict__, namespace)

    def test_reject_immutable_namespace_replacement(self):
        internal = import_module('_testinternalcapi')
        capi = import_module('_testcapi')
        for setter in (lambda obj, value: setattr(obj, '__dict__', value),
                       capi.function_set_dict):
            thread = threading.Thread()
            namespace = thread.__dict__
            internal.object_declare_immutable(thread)
            with self.assertRaises(TypeError):
                setter(thread, {})
            self.assertIs(thread.__dict__, namespace)

    def test_namespace_payload_ownership(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        internal.object_declare_synchronized(check_access)
        thread = threading.Thread()
        thread.payload = []
        owner = internal.object_owner_id(thread.payload)
        results = threading.Channel()
        def worker():
            check_access(thread)
            check_access(thread.__dict__)
            try:
                check_access(thread.payload)
            except IllegalThreadAccessException:
                results.put(True)
        other = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([other]):
            pass
        self.assertTrue(results.get())
        self.assertEqual(internal.object_owner_id(thread.payload), owner)

    def test_parallel_attribute_writes(self):
        thread = threading.Thread()
        namespace = thread.__dict__
        barrier = threading.Barrier(4)
        results = threading.Channel()
        def worker(number):
            barrier.wait(timeout=SHORT_TIMEOUT)
            for index in range(200):
                setattr(thread, f'field_{number}_{index}', index)
            results.put(True)
        others = [threading.Thread(target=worker, args=(number,),
                                   group=threading.ThreadGroup())
                  for number in range(4)]
        with threading_helper.start_threads(others):
            pass
        for _ in others:
            self.assertTrue(results.get())
        for number in range(4):
            for index in range(200):
                self.assertEqual(namespace[f'field_{number}_{index}'], index)
        self.assertIs(thread.__dict__, namespace)

    def test_native_subclass_storage_is_local(self):
        capi = import_module('_testcapi')
        opaque = capi.make_type_with_extra(threading.Thread)
        class Derived(opaque):
            pass
        for cls in (opaque, Derived):
            self.assertIs(cls().__shareable__, threading.Shareable.LOCAL)
        transparent = capi.make_type_with_base(threading.Thread)
        self.assert_shared(transparent())

    def test_native_local_isolation(self):
        internal = import_module('_testinternalcapi')
        check_access = internal.object_check_access
        owner_id = internal.object_owner_id
        internal.object_declare_synchronized(check_access)
        internal.object_declare_synchronized(owner_id)
        local = threading.local()
        local.value = 'main'
        owner = internal.object_owner_id(local.__dict__)
        self.assertIs(local.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertIs(local.__dict__.__shareable__, threading.Shareable.LOCAL)
        results = threading.Channel()
        def worker():
            check_access(local)
            assert not hasattr(local, 'value')
            local.value = 'worker'
            assert local.__dict__.__shareable__ is threading.Shareable.LOCAL
            results.put(owner_id(local.__dict__))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertNotEqual(results.get(), owner)
        self.assertEqual(local.value, 'main')
        class LocalSubclass(threading.local):
            pass
        self.assertIs(LocalSubclass().__shareable__, threading.Shareable.LOCAL)

    def test_cycles_collected(self):
        thread = threading.Thread()
        thread.cycle = thread
        namespace = thread.__dict__
        ref = weakref.ref(thread)
        del thread, namespace
        gc.collect()
        self.assertIsNone(ref())


if __name__ == '__main__':
    unittest.main()
