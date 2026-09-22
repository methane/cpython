"""PEP 805 native compound lock contexts."""

import _thread
import signal
import sys
import threading
import unittest

from test import test_stop_the_world
from test.support import SHORT_TIMEOUT


class CompoundLockTests(unittest.TestCase):
    run_native = test_stop_the_world.StopTheWorldTests.run_native

    def test_protection_and_flattening(self):
        first = threading.Lock()
        second = threading.RLock()
        third = threading.Lock()
        combined = (third + first) + (second + first)
        self.assertIs(combined.__shareable__, threading.Shareable.SYNCHRONIZED)
        with combined as entered:
            self.assertIs(entered, combined)
            values = first.protect([])
            mapping = second.protect({})
            members = third.protect(set())
            values.append(1)
            mapping['answer'] = 42
            members.add(2)
            self.assertEqual(second._recursion_count(), 1)
        with self.assertRaises(UnprotectedAccessException):
            values
        with self.assertRaises(UnprotectedAccessException):
            mapping
        with self.assertRaises(UnprotectedAccessException):
            members
        with second + third + first:
            self.assertEqual(values, [1])
            self.assertEqual(mapping, {'answer': 42})
            self.assertEqual(members, {2})
        for lock in (first, second, third):
            self.assertFalse(lock.locked())

    def test_duplicates_and_reentry(self):
        first = threading.RLock()
        second = threading.RLock()
        combined = (first + second) + (second + first)
        with combined:
            with combined:
                values = first.protect([])
                self.assertEqual(first._recursion_count(), 2)
                self.assertEqual(second._recursion_count(), 2)
            values.append(1)
            with first + first:
                self.assertEqual(first._recursion_count(), 2)
            self.assertEqual(first._recursion_count(), 1)
        with self.assertRaises(UnprotectedAccessException):
            values
        primitive = threading.Lock()
        with primitive + primitive:
            self.assertTrue(primitive.locked())
        self.assertFalse(primitive.locked())

    def test_exception_unwind(self):
        first = threading.Lock()
        second = threading.RLock()
        combined = second + first
        with self.assertRaises(LookupError):
            with combined:
                values = first.protect([])
                raise LookupError
        self.assertFalse(first.locked())
        self.assertFalse(second.locked())
        with self.assertRaises(UnprotectedAccessException):
            values
        with combined:
            values.append(1)

    def test_context_owner(self):
        first = threading.Lock()
        second = threading.RLock()
        combined = first + second
        with self.assertRaises(RuntimeError):
            combined.__exit__(None, None, None)

        def foreign_exit(combined):
            try:
                combined.__exit__(None, None, None)
            except RuntimeError:
                return True
            return False

        with combined:
            self.assertTrue(self.run_native(foreign_exit, combined))
            self.assertTrue(first.locked())
            self.assertTrue(second.locked())
        with self.assertRaises(RuntimeError):
            combined.__exit__(None, None, None)

    def test_invalidated_member_does_not_release_replacement(self):
        first = threading.Lock()
        second = threading.Lock()
        combined = first + second

        def replace(first):
            first.release()
            first.acquire()

        with self.assertRaises(RuntimeError):
            with combined:
                self.run_native(replace, first)
        self.assertTrue(first.locked())
        self.assertFalse(second.locked())
        first.release()
        with combined:
            self.assertTrue(first.locked())

    def test_same_group_foreign_exit(self):
        combined = threading.Lock() + threading.RLock()
        results = threading.Channel()

        def entry(context=combined, results=results):
            try:
                context.__exit__(None, None, None)
            except RuntimeError:
                results.put(True)
            else:
                results.put(False)

        with combined:
            handle = _thread.start_joinable_thread(entry, group=sys.main_thread_group)
            handle.join(SHORT_TIMEOUT)
            self.assertTrue(handle.is_done())
            self.assertTrue(results.get())
        with combined:
            pass

    def test_addition_operands(self):
        lock = threading.Lock()
        combined = lock + lock
        for operand in (0, None, object(), 'lock'):
            with self.assertRaises(TypeError):
                lock + operand
            with self.assertRaises(TypeError):
                operand + lock
            with self.assertRaises(TypeError):
                combined + operand
        with self.assertRaises(TypeError):
            type(combined)()
        class CustomLock(_thread.RLock):
            pass
        with self.assertRaises(TypeError):
            lock + CustomLock()
        with self.assertRaises(TypeError):
            CustomLock() + lock

    def test_parallel_opposite_orders(self):
        first = threading.Lock()
        second = threading.RLock()
        forwards = first + second
        backwards = second + first
        shared = SynchronizedDict()
        with forwards:
            shared['values'] = first.protect([])
            shared['other'] = second.protect([])
        results = threading.Channel()

        def worker(context, shared, results):
            try:
                for _ in range(100):
                    with context:
                        values = shared['values']
                        other = shared['other']
                        values.append(len(values))
                        other.append(len(other))
            except BaseException as exc:
                results.put(str(exc))
            else:
                results.put(None)

        handles = []
        try:
            for context in (forwards, backwards, forwards, backwards):
                def entry(context=context, shared=shared, results=results, worker=worker):
                    worker(context, shared, results)
                handles.append(_thread.start_joinable_thread(
                    entry, group=threading.ThreadGroup()))
        finally:
            for handle in handles:
                handle.join(SHORT_TIMEOUT)
        for handle in handles:
            self.assertTrue(handle.is_done(), 'compound acquisition deadlocked')
        for _ in handles:
            self.assertIsNone(results.get())
        with backwards:
            self.assertEqual(shared['values'], list(range(400)))
            self.assertEqual(shared['other'], list(range(400)))

    @unittest.skipUnless(hasattr(signal, 'setitimer'), 'requires interval timers')
    def test_interrupted_acquisition_rolls_back(self):
        first = threading.Lock()
        second = threading.Lock()
        combined = second + first
        with first:
            values = first.protect([])

        def interrupted(signum, frame):
            self.assertTrue(first.locked(), 'compound did not acquire the earlier lock first')
            raise LookupError('interrupted compound acquisition')

        old_handler = signal.signal(signal.SIGALRM, interrupted)
        second.acquire()
        try:
            signal.setitimer(signal.ITIMER_REAL, 0.05)
            with self.assertRaisesRegex(LookupError, 'interrupted compound'):
                with combined:
                    self.fail('acquired an already locked nonrecursive mutex')
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            second.release()
        self.assertFalse(first.locked())
        with self.assertRaises(UnprotectedAccessException):
            values
        with self.assertRaises(RuntimeError):
            combined.__exit__(None, None, None)
        with combined:
            values.append(1)

    @unittest.skipUnless(hasattr(signal, 'setitimer'), 'requires interval timers')
    def test_interrupted_recursive_acquisition_preserves_outer_context(self):
        first = threading.RLock()
        second = threading.Lock()
        combined = second + first

        def interrupted(signum, frame):
            self.assertEqual(first._recursion_count(), 2)
            raise LookupError('interrupted recursive acquisition')

        with first:
            values = first.protect([])
            old_handler = signal.signal(signal.SIGALRM, interrupted)
            second.acquire()
            try:
                signal.setitimer(signal.ITIMER_REAL, 0.05)
                with self.assertRaisesRegex(LookupError, 'interrupted recursive'):
                    with combined:
                        self.fail('acquired an already locked nonrecursive mutex')
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old_handler)
                second.release()
            self.assertEqual(first._recursion_count(), 1)
            values.append(1)
        with self.assertRaises(UnprotectedAccessException):
            values


if __name__ == '__main__':
    unittest.main()
