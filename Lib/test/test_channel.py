"""PEP 805 FIFO ownership transfer between ThreadGroups."""

import threading
from time import monotonic, sleep
import unittest
import weakref

from test.support import SHORT_TIMEOUT, gc_collect, nomemtest, threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


capi = import_module('_testinternalcapi')
Channel = threading.Channel


class ChannelTests(unittest.TestCase):
    def test_fifo_and_empty(self):
        channel = Channel()
        for repeat in range(3):
            with self.assertRaises(IndexError):
                channel.get()
            for value in (None, 1, 'two'):
                self.assertIsNone(channel.put(value))
            self.assertEqual([channel.get() for _ in range(3)], [None, 1, 'two'])
        with self.assertRaises(IndexError):
            channel.get()

    def test_frozen_wrapper(self):
        channel = Channel()
        self.assertIs(channel.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(Channel.__shareable__, threading.Shareable.IMMUTABLE)
        self.assertIs(freeze(channel), channel)
        with self.assertRaises(TypeError):
            channel._queue = None
        with self.assertRaises(TypeError):
            del channel._queue
        with self.assertRaises(TypeError):
            channel.__init__()
        channel.put(42)
        self.assertEqual(channel.get(), 42)

    def test_arguments(self):
        with self.assertRaises(TypeError):
            Channel(1)
        channel = Channel()
        with self.assertRaises(TypeError):
            channel.put()
        with self.assertRaises(TypeError):
            channel.get(1)
        channel.put(obj=42)
        self.assertEqual(channel.get(), 42)

    def test_shallow_copy(self):
        child = []
        source = [child]
        channel = Channel()
        channel.put(source)
        source.append(42)
        result = channel.get()
        self.assertIsNot(result, source)
        self.assertEqual(result, [child])
        self.assertIs(result[0], child)
        self.assertIs(capi.object_check_access(result), result)

    def test_shareable_identity(self):
        channel = Channel()
        for value in (None, ([],), frozendict(a=[]), Channel(),
                      threading.TransferBox([])):
            channel.put(value)
            self.assertIs(channel.get(), value)

    def test_copy_error_preserves_queue(self):
        class BadCopy:
            def __copy__(self):
                raise RuntimeError('copy failed')

        channel = Channel()
        channel.put('before')
        with self.assertRaisesRegex(RuntimeError, 'copy failed'):
            channel.put(BadCopy())
        channel.put('after')
        self.assertEqual((channel.get(), channel.get()), ('before', 'after'))
        with self.assertRaises(IndexError):
            channel.get()

    def test_reentrant_copy(self):
        channel = Channel()
        channel.put('first')

        class ReentrantCopy:
            def __copy__(self):
                value = channel.get()
                channel.put('nested')
                return [value]

        channel.put(ReentrantCopy())
        self.assertEqual(channel.get(), 'nested')
        self.assertEqual(channel.get(), ['first'])

    @nomemtest
    def test_allocation_failure_preserves_queue(self):
        import_module('_testcapi')
        assert_python_ok('-c', '''if True:
            import copy
            import _testcapi
            import threading

            failures = 0
            for start in range(20):
                channel = threading.Channel()
                channel.put('before')
                source = [42]
                failed = False
                _testcapi.set_nomemory(start, start + 1)
                try:
                    channel.put(source)
                except MemoryError:
                    failed = True
                finally:
                    _testcapi.remove_mem_hooks()
                assert channel.get() == 'before'
                assert source == [42]
                if failed:
                    failures += 1
                else:
                    result = channel.get()
                    assert result == source and result is not source
                try:
                    channel.get()
                except IndexError:
                    pass
                else:
                    raise AssertionError('unexpected queue entry')
                channel.put('after')
                assert channel.get() == 'after'
            assert failures > 0
        ''')

    def test_unconsumed_cycle_is_collected(self):
        class Child:
            pass

        channel = Channel()
        child = Child()
        child.channel = channel
        ref = weakref.ref(child)
        channel.put([child])
        del channel, child
        gc_collect()
        self.assertIsNone(ref())

    @threading_helper.requires_working_threading()
    def test_cross_group_shallow_ownership(self):
        check_access = capi.object_check_access
        capi.object_declare_synchronized(check_access)
        source = [[]]
        channel, results = Channel(), Channel()
        channel.put(source)

        def work():
            value = channel.get()
            results.put(check_access(value) is value)
            try:
                check_access(value[0])
            except IllegalThreadAccessException:
                results.put('child remains foreign')

        worker = threading.Thread(group=threading.ThreadGroup(), target=work)
        with threading_helper.start_threads([worker]):
            pass
        self.assertIs(results.get(), True)
        self.assertEqual(results.get(), 'child remains foreign')
        self.assertIs(capi.object_check_access(source), source)

    @threading_helper.requires_working_threading()
    def test_foreign_input_rejected(self):
        source = []
        channel, results = Channel(), Channel()

        def work():
            try:
                channel.put(source)
            except IllegalThreadAccessException:
                results.put('denied')

        worker = threading.Thread(group=threading.ThreadGroup(), target=work)
        with threading_helper.start_threads([worker]):
            pass
        self.assertEqual(results.get(), 'denied')
        with self.assertRaises(IndexError):
            channel.get()

    @threading_helper.requires_working_threading()
    def test_parallel_producers_and_consumers(self):
        check_access = capi.object_check_access
        capi.object_declare_synchronized(check_access)
        channel, results = Channel(), Channel()
        count = 50
        workers = 4

        def produce(producer):
            for sequence in range(count):
                channel.put([producer, sequence])

        def consume():
            deadline = monotonic() + SHORT_TIMEOUT
            while monotonic() < deadline:
                try:
                    value = channel.get()
                except IndexError:
                    sleep(0)
                    continue
                if value is None:
                    return
                check_access(value)
                results.put(tuple(value))
            results.put(('timeout',))

        producers = [threading.Thread(group=threading.ThreadGroup(),
                                      target=produce, args=(i,))
                     for i in range(workers)]
        consumers = [threading.Thread(group=threading.ThreadGroup(),
                                      target=consume)
                     for _ in range(workers)]
        with threading_helper.start_threads(consumers):
            with threading_helper.start_threads(producers):
                pass
            for _ in consumers:
                channel.put(None)
        received = []
        while True:
            try:
                received.append(results.get())
            except IndexError:
                break
        self.assertCountEqual(received, [(i, j) for i in range(workers)
                                        for j in range(count)])
        with self.assertRaises(IndexError):
            channel.get()


if __name__ == '__main__':
    unittest.main()
