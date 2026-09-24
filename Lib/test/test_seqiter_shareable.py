"""Synchronized cursors in generic sequence iterators."""

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


def synchronize(sequence):
    # Model a native sequence with immutable metadata and synchronized callbacks.
    import_module('_testinternalcapi').object_declare_synchronized(sequence)
    return sequence


class SequenceIteratorSharingTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_parallel_consumers(self):
        for factory in (iter, enumerate):
            with self.subTest(factory=factory):
                self.check_parallel_consumers(factory)

    def check_parallel_consumers(self, factory):
        barrier = threading.Barrier(4)
        iterator = factory(synchronize(Sequence(40, barrier)))
        self.assertIs(iterator.__shareable__, threading.Shareable.SYNCHRONIZED)
        results = SynchronizedList()
        def worker():
            try:
                # A fixed number of calls keeps the barrier balanced when
                # a broken iterator repeats positions.
                results.append(tuple(next(iterator) for _ in range(10)))
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        threads = [threading.Thread(target=worker, group=threading.ThreadGroup())
                   for _ in range(4)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(len(results), 4)
        values = [value for batch in results for value in batch]
        if factory is enumerate:
            self.assertEqual(sorted(index for index, value in values),
                             list(range(40)))
            values = [value for index, value in values]
        self.assertEqual(sorted(values), list(range(40)))
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_reentrant_next(self):
        class ReentrantSequence(Sequence):
            callback = None
            def __getitem__(self, index):
                if self.callback is not None:
                    callback, self.callback = self.callback, None
                    callback()
                return super().__getitem__(index)
        sequence = synchronize(ReentrantSequence(3))
        iterator = iter(sequence)
        observed = []
        sequence.callback = lambda: observed.append(next(iterator))
        self.assertEqual(next(iterator), 0)
        self.assertEqual(observed, [1])
        self.assertEqual(list(iterator), [2])

    def test_exception_retry_and_exhaustion(self):
        class FailingSequence(Sequence):
            exception = None
            def __getitem__(self, index):
                if self.exception is not None:
                    exception, self.exception = self.exception, None
                    raise exception('sequence failure')
                return super().__getitem__(index)
        for exception in (ValueError, IndexError, StopIteration):
            with self.subTest(exception=exception):
                sequence = synchronize(FailingSequence(3))
                sequence.exception = exception
                iterator = iter(sequence)
                if exception is ValueError:
                    with self.assertRaises(ValueError):
                        next(iterator)
                    self.assertEqual(iterator.__reduce__()[2], 0)
                    self.assertEqual(list(iterator), [0, 1, 2])
                else:
                    with self.assertRaises(StopIteration):
                        next(iterator)
                    iterator.__setstate__(0)
                    self.assertEqual(list(iterator), [])

    @threading_helper.requires_working_threading()
    def test_failed_callback_preserves_later_progress(self):
        @freeze
        class DelayedFailure(Sequence):
            def __getitem__(self, index):
                if index == 0:
                    self.entered.set()
                    if not self.finished.wait(timeout=SHORT_TIMEOUT):
                        raise TimeoutError('second consumer did not finish')
                    raise ValueError('first item failed')
                self.finished.set()
                return super().__getitem__(index)
        sequence = DelayedFailure(3)
        entered = sequence.entered = threading.Event()
        sequence.finished = threading.Event()
        iterator = iter(synchronize(sequence))
        results = SynchronizedList()
        def first():
            try:
                results.append(next(iterator))
            except ValueError:
                results.append('failed')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        def second():
            try:
                assert entered.wait(timeout=SHORT_TIMEOUT)
                results.append(next(iterator))
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))
        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (first, second)]
        with threading_helper.start_threads(threads):
            pass
        self.assertCountEqual(list(results), ['failed', 1])
        self.assertEqual(list(iterator), [2])

    def test_reentrant_exhaustion_stays_exhausted(self):
        class ReentrantSequence(Sequence):
            callback = None
            def __getitem__(self, index):
                if self.callback is not None:
                    callback, self.callback = self.callback, None
                    callback()
                return super().__getitem__(index)
        sequence = synchronize(ReentrantSequence(3))
        iterator = iter(sequence)
        observed = []
        sequence.callback = lambda: observed.extend(iterator)
        self.assertEqual(next(iterator), 0)
        self.assertEqual(observed, [1, 2])
        iterator.__setstate__(0)
        self.assertEqual(list(iterator), [])

    def test_copy_and_overflow(self):
        iterator = iter(synchronize(Sequence(3)))
        self.assertEqual(next(iterator), 0)
        clone = copy.copy(iterator)
        self.assertIs(clone.__shareable__, threading.Shareable.SYNCHRONIZED)
        self.assertEqual(list(clone), [1, 2])
        self.assertEqual(iterator.__length_hint__(), 2)
        iterator.__setstate__(sys.maxsize)
        for _ in range(2):
            with self.assertRaises(OverflowError):
                next(iterator)
            self.assertEqual(iterator.__reduce__()[2], sys.maxsize)
        iterator.__setstate__(-1)
        self.assertEqual(list(iterator), [0, 1, 2])
        iterator.__setstate__(0)
        self.assertEqual(list(iterator), [])
        self.assertEqual(iterator.__length_hint__(), 0)


if __name__ == '__main__':
    unittest.main()
