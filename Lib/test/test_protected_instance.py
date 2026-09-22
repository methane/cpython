"""Protected Python instances, namespaces and bound methods."""

import threading
import unittest

from test import test_stop_the_world


@freeze
class Counter:
    def __init__(self):
        self.value = 0
        self.child = []

    def increment(self):
        self.value += 1
        return self.value


@freeze
class SlottedCounter:
    __slots__ = ('value',)

    def __init__(self):
        self.value = 0

    def increment(self):
        self.value += 1
        return self.value


class ProtectedInstanceTests(unittest.TestCase):
    run_native = test_stop_the_world.StopTheWorldTests.run_native

    def test_scope_slots_and_bound_methods(self):
        for factory in (threading.Lock, threading.RLock):
            for cls in (Counter, SlottedCounter):
                with self.subTest(lock=factory, cls=cls):
                    lock = factory()
                    with lock:
                        value = lock.protect(cls())
                        method = value.increment
                        self.assertIs(value.__shareable__, threading.Shareable.PROTECTED)
                        self.assertIs(method.__shareable__, threading.Shareable.PROTECTED)
                        self.assertEqual(method(), 1)
                    with self.assertRaises(UnprotectedAccessException):
                        value
                    with self.assertRaises(UnprotectedAccessException):
                        method()
                    with lock:
                        self.assertEqual(value.increment(), 2)

    def test_parallel_use_and_shallow_contents(self):
        for cls in (Counter, SlottedCounter):
            lock = threading.Lock()
            shared = SynchronizedDict()
            with lock:
                shared['value'] = lock.protect(cls())

            def worker(lock, shared):
                with lock:
                    value = shared['value']
                    for _ in range(100):
                        value.increment()
                    if type(value) is Counter:
                        namespace = value.__dict__
                        namespace['value'] += 1
                        try:
                            value.child
                        except IllegalThreadAccessException:
                            return value.value
                        raise AssertionError('protection unexpectedly became deep')
                    return value.value

            expected = 101 if cls is Counter else 100
            self.assertEqual(self.run_native(worker, lock, shared), expected)
            with lock:
                self.assertEqual(shared['value'].value, expected)

    def test_namespace_copy_and_escape(self):
        originals = []

        class SharesNamespace:
            def __init__(self):
                self.value = 1

            def __copy__(self):
                other = object.__new__(type(self))
                other.__dict__ = self.__dict__
                originals.append(self.__dict__)
                return other

        lock = threading.Lock()
        with lock:
            value = lock.protect(SharesNamespace())
            namespace = value.__dict__
            self.assertIs(namespace.__shareable__, threading.Shareable.PROTECTED)
            self.assertIsNot(namespace, originals[0])
            originals[0]['value'] = 99
            self.assertEqual(value.value, 1)
        with self.assertRaises(UnprotectedAccessException):
            namespace
        self.assertEqual(originals[0], {'value': 99})

    def test_created_in_parallel_group(self):
        lock = threading.Lock()
        shared = SynchronizedDict()

        def worker(lock, shared):
            with lock:
                shared['value'] = lock.protect(Counter())
                shared['value'].increment()

        self.run_native(worker, lock, shared)
        with lock:
            self.assertEqual(shared['value'].value, 1)

    def test_namespace_replacement(self):
        lock = threading.Lock()
        other = threading.Lock()
        with lock + other:
            value = lock.protect(Counter())
            namespace = lock.protect({'value': 42})
            value.__dict__ = namespace
            self.assertIs(value.__dict__, namespace)
            self.assertEqual(value.value, 42)
            with self.assertRaises(TypeError):
                value.__dict__ = {}
            with self.assertRaises(TypeError):
                value.__dict__ = other.protect({})
            with self.assertRaises(TypeError):
                del value.__dict__
            self.assertEqual(value.value, 42)

    def test_copy_rejects_self_and_aliases(self):
        aliases = []

        class ReturnsSelf:
            def __copy__(self):
                return self

        class PublishesCopy:
            def __copy__(self):
                value = type(self)()
                aliases.append(value)
                return value

        class WrongType:
            def __copy__(self):
                return []

        for cls in (ReturnsSelf, PublishesCopy, WrongType):
            lock = threading.Lock()
            with lock:
                with self.assertRaises(TypeError):
                    lock.protect(cls())
            self.assertTrue(lock.acquire(False))
            lock.release()
        self.assertIs(aliases[0].__shareable__, threading.Shareable.LOCAL)

    def test_copy_loses_lock_context(self):
        for factory in (threading.Lock, threading.RLock):
            lock = factory()

            class ReleasesLock:
                def __copy__(self):
                    lock.__exit__(None, None, None)
                    return type(self)()

            lock.__enter__()
            try:
                with self.assertRaises(UnprotectedAccessException):
                    lock.protect(ReleasesLock())
            finally:
                if lock.locked():
                    lock.__exit__(None, None, None)
            self.assertTrue(lock.acquire(False))
            lock.release()


if __name__ == '__main__':
    unittest.main()
