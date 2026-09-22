"""Experimental native protective locks."""

import _thread
import functools
import gc
import weakref
import sys
import threading
import unittest
from threading import Shareable
from test import test_stop_the_world
from test.support import SHORT_TIMEOUT, sleeping_retry


class ProtectiveLockTests(unittest.TestCase):
    lock_type = staticmethod(threading.Lock)
    run_native = test_stop_the_world.StopTheWorldTests.run_native

    def test_native_state_outlives_wrapper(self):
        import _testinternalcapi as internal
        lock = self.lock_type()
        with lock:
            value = lock.protect([])
            owner = internal.object_owner_id(value)
            self.assertTrue(internal.protective_mutex_exists(owner))
            # Repeated protection must not publish duplicate registry links.
            second = lock.protect([])
            self.assertEqual(internal.object_owner_id(second), owner)
        ref = weakref.ref(lock)
        del lock
        gc.collect()
        self.assertIsNone(ref())
        self.assertTrue(internal.protective_mutex_exists(owner))
        self.assertFalse(internal.threadgroup_owner_exists(owner))
        self.assertFalse(internal.protective_mutex_exists(0))
        self.assertFalse(internal.protective_mutex_exists(
            internal.object_owner_id([])))
        with self.assertRaises(UnprotectedAccessException):
            value

    def test_native_state_is_interpreter_local(self):
        from test.support.import_helper import import_module
        internal = import_module('_testinternalcapi')
        interpreters = import_module('_interpreters')
        lock = self.lock_type()
        with lock:
            value = lock.protect([])
            owner = internal.object_owner_id(value)
        interp = interpreters.create()
        try:
            result = interpreters.run_string(interp, f"""
import threading
import _testinternalcapi as internal
assert not internal.protective_mutex_exists({owner})
for factory in (threading.Lock, threading.RLock):
    lock = factory()
    with lock:
        value = lock.protect([])
        assert internal.protective_mutex_exists(internal.object_owner_id(value))
""")
            self.assertIsNone(result, result)
        finally:
            interpreters.destroy(interp)
        self.assertTrue(internal.protective_mutex_exists(owner))

    def test_scope_and_methods(self):
        lock = self.lock_type()
        with lock:
            value = lock.protect([])
            value.append(1)
            append = value.append
            self.assertIs(value.__shareable__, Shareable.PROTECTED)
            self.assertIs(append.__shareable__, Shareable.PROTECTED)
        with self.assertRaises(UnprotectedAccessException):
            value
        with self.assertRaises(UnprotectedAccessException):
            append(2)
        with lock:
            append(2)
            self.assertEqual(value, [1, 2])
        methods = [lock.acquire, lock.release]
        for name in ('acquire_lock', 'release_lock'):
            if hasattr(lock, name):
                methods.append(getattr(lock, name))
        for method in methods:
            with self.assertRaises(RuntimeError):
                method()
        if hasattr(lock, '_at_fork_reinit'):
            with self.assertRaises(RuntimeError):
                lock._at_fork_reinit()

    def test_input_and_context(self):
        lock = self.lock_type()
        with self.assertRaises(UnprotectedAccessException):
            lock.protect([])
        lock.acquire()
        try:
            with self.assertRaises(UnprotectedAccessException):
                lock.protect([])
        finally:
            lock.release()
        original = []
        alias = original
        with lock:
            with self.assertRaises(TypeError):
                lock.protect(original)
            with self.assertRaises(TypeError):
                lock.protect(42)
            values = lock.protect({'answer': 42})
            members = lock.protect({1, 2})
            self.assertEqual(values['answer'], 42)
            members.add(3)
        with lock:
            self.assertEqual(members, {1, 2, 3})
        self.assertEqual(original, [])

    def test_borrowed_alias_rejected(self):
        lock = self.lock_type()
        original = []
        with lock:
            with self.assertRaises(TypeError):
                lock.protect(original)
        self.assertEqual(original, [])

    def test_call_paths(self):
        lock = self.lock_type()
        original = []

        def direct(lock):
            value = []
            try:
                lock.protect(value)
            except TypeError:
                return value == []
            return False

        def bound(protect):
            value = []
            try:
                protect(value)
            except TypeError:
                return value == []
            return False

        with lock:
            protect = lock.protect
            partial = functools.partial(protect)
            retained = functools.partial(protect, original)
            # Warm both descriptor and bound-function specializations, and
            # exercise native forwarding without losing the borrowing check.
            for _ in range(100):
                self.assertEqual(lock.protect([]), [])
                self.assertEqual(protect({}), {})
                self.assertEqual(partial(set()), set())
                for call, args in (
                    (partial, (original,)),
                    (retained, ()),
                ):
                    with self.assertRaises(TypeError):
                        call(*args)
                # Each helper creates its own singly referenced local, so
                # rejection cannot be explained by a retained argument tuple.
                self.assertTrue(direct(lock))
                self.assertTrue(bound(protect))
                self.assertTrue(bound(partial))
        self.assertEqual(original, [])

    def test_worker_and_same_group_denial(self):
        lock = self.lock_type()
        shared = SynchronizedDict()
        with lock:
            shared['value'] = lock.protect([])
        def work(lock, shared):
            denied = 0
            try:
                shared['value']
            except UnprotectedAccessException:
                denied += 1
            for i in range(50):
                with lock:
                    value = shared['value']
                    value.append(i)
            try:
                value
            except UnprotectedAccessException:
                denied += 1
            return denied
        self.assertEqual(self.run_native(work, lock, shared), 2)
        with lock:
            self.assertEqual(shared['value'], list(range(50)))
            results = threading.Channel()
            def probe(shared=shared, results=results):
                try:
                    shared['value']
                except UnprotectedAccessException:
                    results.put(True)
                else:
                    results.put(False)
            handle = _thread.start_joinable_thread(probe, group=sys.main_thread_group)
            handle.join()
            self.assertTrue(results.get())

    def test_exception_and_ordinary_release(self):
        lock = self.lock_type()
        with self.assertRaises(LookupError):
            with lock:
                value = lock.protect([])
                raise LookupError
        with lock:
            self.assertEqual(value, [])
        ordinary = threading.Lock()
        ordinary.acquire()
        self.run_native(lambda lock: lock.release(), ordinary)
        self.assertFalse(ordinary.locked())

    def test_context_invalidated_by_foreign_release(self):
        lock = self.lock_type()

        def replace_owner(lock):
            lock.release()
            lock.acquire()

        with lock:
            self.run_native(replace_owner, lock)
            with self.assertRaises(UnprotectedAccessException):
                lock.protect([])
        # A failed protect() did not convert the ordinary lock.
        self.assertTrue(lock.acquire(False))
        lock.release()

    def test_contended_contexts(self):
        lock = self.lock_type()
        shared = SynchronizedDict()
        ready = threading.Channel()
        results = threading.Channel()

        def worker(lock=lock, shared=shared, ready=ready, results=results):
            ready.put(None)
            try:
                for _ in range(100):
                    with lock:
                        values = shared['values']
                        values.append(len(values))
            except BaseException as exc:
                results.put(str(exc))
            else:
                results.put(None)

        handles = []
        try:
            with lock:
                shared['values'] = lock.protect([])
                for _ in range(4):
                    handles.append(_thread.start_joinable_thread(
                        worker, group=threading.ThreadGroup()))
                for _ in handles:
                    for _ in sleeping_retry(SHORT_TIMEOUT):
                        try:
                            ready.get()
                        except IndexError:
                            continue
                        break
        finally:
            for handle in handles:
                handle.join(SHORT_TIMEOUT)
        for handle in handles:
            self.assertTrue(handle.is_done())
        for _ in handles:
            self.assertIsNone(results.get())
        with lock:
            self.assertEqual(shared['values'], list(range(400)))


class ProtectiveRLockTests(unittest.TestCase):
    lock_type = staticmethod(threading.RLock)
    run_native = ProtectiveLockTests.run_native
    test_native_state_outlives_wrapper = ProtectiveLockTests.test_native_state_outlives_wrapper
    test_native_state_is_interpreter_local = ProtectiveLockTests.test_native_state_is_interpreter_local
    test_scope_and_methods = ProtectiveLockTests.test_scope_and_methods
    test_input_and_context = ProtectiveLockTests.test_input_and_context
    test_borrowed_alias_rejected = ProtectiveLockTests.test_borrowed_alias_rejected
    test_call_paths = ProtectiveLockTests.test_call_paths
    test_worker_and_same_group_denial = ProtectiveLockTests.test_worker_and_same_group_denial
    test_exception_and_ordinary_release = ProtectiveLockTests.test_exception_and_ordinary_release
    test_contended_contexts = ProtectiveLockTests.test_contended_contexts

    def test_nested_transition(self):
        lock = threading.RLock()
        with lock:
            with lock:
                values = lock.protect([])
                values.append(1)
                self.assertEqual(lock._recursion_count(), 2)
            self.assertEqual(lock._recursion_count(), 1)
            values.append(2)
            with lock:
                values.append(3)
            self.assertEqual(values, [1, 2, 3])
        with self.assertRaises(UnprotectedAccessException):
            values
        with lock:
            self.assertEqual(values, [1, 2, 3])
        self.assertFalse(lock.locked())

    def test_nested_exception(self):
        lock = threading.RLock()
        with lock:
            values = lock.protect([])
            with self.assertRaises(LookupError):
                with lock:
                    values.append(1)
                    raise LookupError
            self.assertEqual(lock._recursion_count(), 1)
            values.append(2)
        with self.assertRaises(UnprotectedAccessException):
            values
        with lock:
            self.assertEqual(values, [1, 2])

    def test_private_bypasses(self):
        lock = threading.RLock()
        with lock:
            values = lock.protect([])
            for method, args in (
                (lock.acquire, ()),
                (lock.release, ()),
                (lock._release_save, ()),
                (lock._acquire_restore, ((1, _thread.get_ident()),)),
            ):
                with self.assertRaises(RuntimeError):
                    method(*args)
                self.assertEqual(lock._recursion_count(), 1)
                values.append(1)
            if hasattr(lock, '_at_fork_reinit'):
                with self.assertRaises(RuntimeError):
                    lock._at_fork_reinit()
            condition = threading.Condition(lock)
            with self.assertRaises(RuntimeError):
                condition.wait(0)
            self.assertEqual(lock._recursion_count(), 1)
            self.assertEqual(values, [1, 1, 1, 1])

        def foreign_exit(lock):
            try:
                lock.__exit__(None, None, None)
            except RuntimeError:
                return True
            return False

        with lock:
            self.assertTrue(self.run_native(foreign_exit, lock))
            self.assertEqual(lock._recursion_count(), 1)
        with self.assertRaises(RuntimeError):
            lock._acquire_restore((1, _thread.get_ident()))
        self.assertFalse(lock.locked())

    def test_manual_recursion_cannot_be_adopted(self):
        lock = threading.RLock()
        lock.acquire()
        try:
            with lock:
                with self.assertRaises(UnprotectedAccessException):
                    lock.protect([])
        finally:
            lock.release()
        with lock:
            values = lock.protect([])
            self.assertEqual(values, [])

    def test_interleaved_locks_and_multiple_values(self):
        first = threading.RLock()
        second = threading.RLock()
        with first:
            values = first.protect([])
            more = first.protect({})
            with second:
                other = second.protect([])
                with first:
                    values.append(1)
                    other.append(2)
                    more['answer'] = 42
                self.assertEqual(values, [1])
                self.assertEqual(other, [2])
            with self.assertRaises(UnprotectedAccessException):
                other
            self.assertEqual(more, {'answer': 42})
        with self.assertRaises(UnprotectedAccessException):
            values
        with self.assertRaises(UnprotectedAccessException):
            more
        with second:
            self.assertEqual(other, [2])



if __name__ == '__main__':
    unittest.main()
