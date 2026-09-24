"""Sharing state and synchronized storage of enumerate and reversed."""

import copy
import sys
import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


@freeze
class Sequence:
    def __init__(self, size, barrier=None):
        self.size = size
        self.barrier = barrier

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        if not 0 <= index < self.size:
            raise IndexError
        if self.barrier is not None:
            self.barrier.wait(timeout=SHORT_TIMEOUT)
        return index


class EnumSharingTests(unittest.TestCase):
    def synchronized_sequence(self, size, barrier=None):
        sequence = Sequence(size, barrier)
        # Model an explicitly synchronized native sequence: its metadata is
        # read-only here, and the optional barrier supports concurrent use.
        import_module('_testinternalcapi').object_declare_synchronized(sequence)
        return sequence

    def test_states_and_copy(self):
        for source in ([10, 11], (10, 11), SynchronizedList((10, 11))):
            expected = (threading.Shareable.SYNCHRONIZED
                        if type(source) is SynchronizedList
                        else threading.Shareable.LOCAL)
            for start in (0, sys.maxsize - 1, sys.maxsize + 1):
                with self.subTest(source=type(source), start=start):
                    iterator = enumerate(source, start)
                    self.assertIs(iterator.__shareable__, expected)
                    self.assertEqual(next(iterator), (start, 10))
                    clone = copy.copy(iterator)
                    self.assertIs(clone.__shareable__, expected)
                    self.assertEqual(next(clone), (start + 1, 11))
                    self.assertIs(iterator.__shareable__, expected)

        for source in (Sequence(3), (0, 1, 2), self.synchronized_sequence(3)):
            expected = (threading.Shareable.SYNCHRONIZED
                        if source.__shareable__ is threading.Shareable.SYNCHRONIZED
                        else threading.Shareable.LOCAL)
            with self.subTest(source=type(source), state=source.__shareable__):
                iterator = reversed(source)
                self.assertIs(iterator.__shareable__, expected)
                self.assertEqual(next(iterator), 2)
                clone = copy.copy(iterator)
                self.assertIs(clone.__shareable__, expected)
                self.assertEqual(list(clone), [1, 0])

    def test_protected_states(self):
        internal = import_module('_testinternalcapi')
        lock = threading.Lock()
        with lock:
            values = lock.protect([10, 11])
            sequence = lock.protect(Sequence(2))
            enum = enumerate(values)
            reverse = reversed(sequence)
            for iterator, source in ((enum, values), (reverse, sequence)):
                self.assertIs(iterator.__shareable__, threading.Shareable.PROTECTED)
                self.assertEqual(internal.object_owner_id(iterator),
                                 internal.object_owner_id(source))
            nested = enumerate(enum)
            self.assertIs(nested.__shareable__, threading.Shareable.PROTECTED)
            self.assertEqual(next(nested), (0, (0, 10)))
            self.assertEqual(next(reverse), 1)
        with self.assertRaises(UnprotectedAccessException):
            next(enum)
        with self.assertRaises(UnprotectedAccessException):
            next(reverse)
        with lock:
            self.assertEqual(next(enum), (1, 11))
            self.assertEqual(next(reverse), 0)

    def test_subclass_namespaces(self):
        class Enumeration(enumerate):
            pass
        class Reverse(reversed):
            pass
        for iterator in (Enumeration(SynchronizedList((1, 2))),
                         Reverse(self.synchronized_sequence(2))):
            with self.subTest(type=type(iterator)):
                self.assertIs(iterator.__shareable__, threading.Shareable.SYNCHRONIZED)
                iterator.description = 'shared'
                self.assertIs(type(iterator.__dict__), SynchronizedDict)
                namespace = {'description': 'replacement'}
                iterator.__dict__ = namespace
                self.assertIs(iterator.__dict__, namespace)
                self.assertIs(type(namespace), SynchronizedDict)
                self.assertEqual(iterator.description, 'replacement')

        lock = threading.Lock()
        with lock:
            enum = Enumeration(lock.protect([1, 2]))
            reverse = Reverse(lock.protect(Sequence(2)))
            for iterator in (enum, reverse):
                iterator.description = 'protected'
                self.assertIs(iterator.__dict__.__shareable__,
                              threading.Shareable.PROTECTED)
                internal = import_module('_testinternalcapi')
                self.assertEqual(internal.object_owner_id(iterator.__dict__),
                                 internal.object_owner_id(iterator))

    @threading_helper.requires_working_threading()
    def test_subclass_namespaces_in_worker(self):
        @freeze
        class Enumeration(enumerate):
            pass
        @freeze
        class Reverse(reversed):
            pass
        iterators = (Enumeration(SynchronizedList((1, 2))),
                     Reverse(self.synchronized_sequence(2)))
        results = SynchronizedList()
        def worker():
            try:
                for iterator in iterators:
                    assert type(iterator.__dict__) is SynchronizedDict
                    iterator.description = 'shared'
                    namespace = {'description': 'replacement'}
                    iterator.__dict__ = namespace
                    assert iterator.__dict__ is namespace
                    assert type(namespace) is SynchronizedDict
                    assert iterator.description == 'replacement'
                results.append('done')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(list(results), ['done'])
        for iterator in iterators:
            self.assertEqual(iterator.description, 'replacement')

    def test_reverse_exception_exhaustion(self):
        class FailingSequence(Sequence):
            def __getitem__(self, index):
                raise self.exception('sequence failure')
        internal = import_module('_testinternalcapi')
        for exception in (IndexError, StopIteration, ValueError):
            with self.subTest(exception=exception):
                sequence = FailingSequence(3)
                sequence.exception = exception
                internal.object_declare_synchronized(sequence)
                iterator = reversed(sequence)
                expected = (ValueError if exception is ValueError
                            else StopIteration)
                with self.assertRaises(expected):
                    next(iterator)
                with self.assertRaises(StopIteration):
                    next(iterator)
                self.assertEqual(iterator.__length_hint__(), 0)
                iterator.__setstate__(2)
                self.assertEqual(list(iterator), [])

    def test_reverse_setstate_reentrant_exhaustion(self):
        class ReentrantSequence(Sequence):
            callback = None
            def __len__(self):
                if self.callback is not None:
                    callback, self.callback = self.callback, None
                    callback()
                return self.size
        sequence = ReentrantSequence(3)
        import_module('_testinternalcapi').object_declare_synchronized(sequence)
        iterator = reversed(sequence)
        def exhaust():
            for _ in iterator:
                pass
        sequence.callback = exhaust
        iterator.__setstate__(1)
        self.assertEqual(list(iterator), [])

    @threading_helper.requires_working_threading()
    def test_protected_iteration_in_worker(self):
        lock = threading.Lock()
        with lock:
            enum = enumerate(lock.protect([10, 11]))
            reverse = reversed(lock.protect(Sequence(3)))
        results = SynchronizedList()
        def worker():
            try:
                with lock:
                    assert tuple(enum) == ((0, 10), (1, 11))
                    assert tuple(reverse) == (2, 1, 0)
                results.append('done')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(list(results), ['done'])

    @threading_helper.requires_working_threading()
    def test_enumerate_parallel_consumers(self):
        for start in (0, sys.maxsize - 10, sys.maxsize + 1):
            with self.subTest(start=start):
                iterator = enumerate(SynchronizedList(range(1000)), start)
                self.assertIs(iterator.__shareable__, threading.Shareable.SYNCHRONIZED)
                barrier = threading.Barrier(4)
                results = SynchronizedList()
                def worker(iterator=iterator, barrier=barrier, results=results):
                    try:
                        barrier.wait(timeout=SHORT_TIMEOUT)
                        results.append(tuple(iterator))
                    except BaseException as exc:
                        results.append((type(exc).__name__, str(exc)))
                threads = [threading.Thread(target=worker, group=threading.ThreadGroup())
                           for _ in range(4)]
                with threading_helper.start_threads(threads):
                    pass
                self.assertEqual(len(results), 4)
                pairs = [pair for batch in results for pair in batch]
                self.assertEqual(sorted(index for index, value in pairs),
                                 list(range(start, start + 1000)))
                self.assertEqual(sorted(value for index, value in pairs),
                                 list(range(1000)))
                self.assertEqual(list(iterator), [])
                self.assertIs(threading.TransferBox(iterator).claim(), iterator)

    @threading_helper.requires_working_threading()
    def test_reverse_parallel_consumers(self):
        barrier = threading.Barrier(4)
        iterator = reversed(self.synchronized_sequence(40, barrier))
        self.assertIs(iterator.__shareable__, threading.Shareable.SYNCHRONIZED)
        results = SynchronizedList()
        def worker():
            try:
                results.append(tuple(iterator))
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        threads = [threading.Thread(target=worker, group=threading.ThreadGroup())
                   for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(len(results), 4)
        self.assertEqual(sorted(value for batch in results for value in batch),
                         list(range(40)))
        self.assertEqual(iterator.__length_hint__(), 0)
        self.assertIs(threading.TransferBox(iterator).claim(), iterator)

    @threading_helper.requires_working_threading()
    def test_enumerate_parallel_reduce(self):
        start = sys.maxsize - 50
        iterator = enumerate(SynchronizedList(range(1000)), start)
        self.assertIs(iterator.__shareable__, threading.Shareable.SYNCHRONIZED)
        barrier = threading.Barrier(2)
        results = SynchronizedList()
        def consume():
            try:
                barrier.wait(timeout=SHORT_TIMEOUT)
                results.append(tuple(iterator))
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        def snapshot():
            try:
                barrier.wait(timeout=SHORT_TIMEOUT)
                for _ in range(1000):
                    constructor, args = iterator.__reduce__()
                    assert constructor is enumerate
                    assert start <= args[1] <= start + 1000
                results.append('snapshots')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (consume, snapshot)]
        with threading_helper.start_threads(threads):
            pass
        self.assertIn('snapshots', results)
        batches = [value for value in results if type(value) is tuple]
        self.assertEqual(batches, [tuple((start + value, value)
                                       for value in range(1000))])


if __name__ == '__main__':
    unittest.main()
