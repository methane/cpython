"""Thread-owned invocation state across PEP 805 ThreadGroups."""

import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper


threading_helper.requires_working_threading(module=True)


class ThreadInvocationTests(unittest.TestCase):
    def start_and_join(self, thread):
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())

    def capture_errors(self):
        results = threading.Channel()

        def hook(args, results=results):
            results.put((args.exc_type.__name__, str(args.exc_value)))

        original = threading.excepthook
        threading.excepthook = hook
        self.addCleanup(setattr, threading, 'excepthook', original)
        return results

    def test_default_arguments_in_another_group(self):
        results = threading.Channel()

        def worker(results=results):
            results.put(42)

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        self.start_and_join(thread)
        self.assertEqual(results.get(), 42)

    def test_shared_keyword_container(self):
        results = threading.Channel()

        def worker(results, *, value):
            results.put(value)

        thread = threading.Thread(target=worker, args=(results,),
                                  kwargs=SynchronizedDict(value=42),
                                  group=threading.ThreadGroup())
        self.start_and_join(thread)
        self.assertEqual(results.get(), 42)

    def test_parallel_arguments_are_shallow_snapshots_at_start(self):
        results = threading.Channel()
        gate = threading.Event()
        args = [results, gate]
        kwargs = {'value': 1}

        def worker(results, gate, *, value):
            gate.wait(SHORT_TIMEOUT)
            results.put(value)

        thread = threading.Thread(target=worker, args=args, kwargs=kwargs,
                                  group=threading.ThreadGroup())
        kwargs['value'] = 42
        thread.start()
        try:
            args.clear()
            kwargs['value'] = 99
        finally:
            gate.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results.get(), 42)
        self.assertIs(args.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(kwargs.__shareable__, threading.Shareable.LOCAL)
        self.assertEqual(kwargs, {'value': 99})

    def test_same_group_keeps_supplied_dictionary(self):
        results = []
        kwargs = {'value': 1}

        def worker(*, value):
            results.append(value)

        thread = threading.Thread(target=worker, kwargs=kwargs,
                                  group=threading.current_thread().group)
        kwargs['value'] = 42
        self.start_and_join(thread)
        self.assertEqual(results, [42])

    def test_shared_exception_hook(self):
        errors = self.capture_errors()

        def worker():
            raise ValueError('worker failure')

        self.start_and_join(threading.Thread(target=worker,
                                            group=threading.ThreadGroup()))
        self.assertEqual(errors.get(), ('ValueError', 'worker failure'))

    def test_unused_local_saved_hook_does_not_block_current_hook(self):
        original = threading.excepthook
        self.addCleanup(setattr, threading, 'excepthook', original)
        local_calls = []

        def local_hook(args):
            local_calls.append(args)

        def worker():
            raise LookupError('use current hook')

        threading.excepthook = local_hook
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        errors = self.capture_errors()
        self.start_and_join(thread)
        self.assertEqual(errors.get(), ('LookupError', 'use current hook'))
        self.assertEqual(local_calls, [])

    def test_local_target_is_rejected_and_reported(self):
        errors = self.capture_errors()
        count = 0

        def worker():
            nonlocal count
            count += 1

        self.start_and_join(threading.Thread(target=worker,
                                            group=threading.ThreadGroup()))
        name, message = errors.get()
        self.assertEqual(name, 'IllegalThreadAccessException')
        self.assertIn('cannot be accessed', message)
        self.assertEqual(count, 0)

    def test_local_arguments_are_not_implicitly_shared(self):
        errors = self.capture_errors()
        entered = threading.Channel()

        def worker(value=None, entered=entered):
            entered.put(True)

        for args, kwargs in (
            (([],), None),
            ((), {'value': []}),
            ((), SynchronizedDict(value=[])),
        ):
            with self.subTest(args=args, kwargs=kwargs):
                self.start_and_join(threading.Thread(
                    target=worker, args=args, kwargs=kwargs,
                    group=threading.ThreadGroup(),
                ))
                name, message = errors.get()
                self.assertEqual(name, 'IllegalThreadAccessException')
                self.assertIn('cannot be accessed', message)
                with self.assertRaises(IndexError):
                    entered.get()


if __name__ == '__main__':
    unittest.main()
