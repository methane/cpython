"""Concurrent method execution, publication, invalidation, and TLBC lifetime."""
import gc
import sys
import threading
import unittest

from test import support
from test.support import import_helper, isolation, threading_helper

_testinternalcapi = import_helper.import_module('_testinternalcapi')
_opcode = import_helper.import_module('_opcode')


def kernel(n, probe):
    total = 0
    i = 0
    while i < n:
        total += i
        i += 1
    return total, probe()


def executor_for(function):
    for offset in range(0, len(function.__code__.co_code), 2):
        try:
            return _opcode.get_executor(function.__code__, offset)
        except ValueError:
            pass
    return None


@unittest.skipUnless(support.Py_GIL_DISABLED, 'requires a free-threaded build')
@support.requires_jit_enabled
@threading_helper.requires_working_threading()
@isolation.runInSubprocess(timeout=support.SHORT_TIMEOUT)
class TestConcurrentMethodJit(unittest.TestCase):
    def run_threads(self, *functions):
        threads = [threading.Thread(target=f) for f in functions]
        with threading_helper.catch_threading_exception() as caught:
            with threading_helper.start_threads(threads):
                pass
            if caught.exc_value is not None:
                raise caught.exc_value

    def test_shared_code_has_thread_local_executors(self):
        barrier = threading.Barrier(4, timeout=support.SHORT_TIMEOUT)
        executors = []
        bytecodes = []

        def worker():
            barrier.wait()
            for _ in range(100):
                value, active = kernel(1000, sys._jit.is_active)
                self.assertEqual(value, 499500)
            self.assertTrue(active)
            self.assertTrue(sys._jit.is_enabled())
            self.assertFalse(sys._is_gil_enabled())
            executor = executor_for(kernel)
            self.assertIsNotNone(executor)
            executors.append(executor)
            bytecodes.append(_testinternalcapi.get_tlbc_id(kernel))
            # All four owners remain live while their executors are checked.
            barrier.wait()
            self.assertTrue(executor.is_valid())
            self.assertTrue(kernel(1000, sys._jit.is_active)[1])
            barrier.wait()

        self.run_threads(*([worker] * 4))
        self.assertEqual(len({id(e) for e in executors}), 4)
        self.assertEqual(len(set(bytecodes)), 4)

    def test_lookup_does_not_return_another_threads_executor(self):
        def leaf(value):
            return value + 1
        ready = threading.Event()
        warmed = threading.Event()
        def observer():
            ready.set()
            self.assertTrue(warmed.wait(support.SHORT_TIMEOUT))
            self.assertIsNone(_testinternalcapi.get_tlbc_id(leaf))
            self.assertIsNone(executor_for(leaf))

        with threading_helper.catch_threading_exception() as caught:
            with threading_helper.start_threads([threading.Thread(target=observer)]):
                self.assertTrue(ready.wait(support.SHORT_TIMEOUT))
                try:
                    for _ in range(_testinternalcapi.TIER2_RESUME_THRESHOLD + 2):
                        self.assertEqual(leaf(41), 42)
                    self.assertIsNotNone(executor_for(leaf))
                finally:
                    warmed.set()
            if caught.exc_value is not None:
                raise caught.exc_value

    def test_invalidate_and_collect_while_running(self):
        barrier = threading.Barrier(3, timeout=support.SHORT_TIMEOUT)
        done = threading.Event()

        def worker():
            for _ in range(100):
                kernel(1000, sys._jit.is_active)
            self.assertTrue(kernel(1000, sys._jit.is_active)[1])
            barrier.wait()
            while not done.is_set():
                self.assertEqual(kernel(1000, sys._jit.is_active)[0], 499500)

        def invalidate():
            barrier.wait()
            try:
                for _ in range(50):
                    _testinternalcapi.invalidate_executors(kernel.__code__)
                    _testinternalcapi.invalidate_cold_executors()
                    gc.collect()
                    _testinternalcapi.clear_executor_deletion_list()
            finally:
                done.set()

        self.run_threads(worker, worker, invalidate)

    def test_shared_mutable_loads_and_calls(self):
        namespace = {'value': 1}
        exec('def read(callback, obj):\n'
             '    return value, obj.value, callback()\n', namespace)
        read = namespace['read']
        class Record:
            value = 1
        record = Record()
        def first():
            return 1
        def second():
            return 'changed'
        barrier = threading.Barrier(3, timeout=support.SHORT_TIMEOUT)

        def reader():
            barrier.wait()
            for _ in range(1000):
                values = read(first, record)
                for value in values:
                    self.assertIn(value, (1, 'changed'))

        def writer():
            barrier.wait()
            for i in range(1000):
                value = 1 if i % 2 else 'changed'
                namespace['value'] = value
                Record.value = value
                first.__code__ = second.__code__ if i % 2 else original

        original = first.__code__
        self.run_threads(reader, reader, writer)
        namespace['value'] = Record.value = 'changed'
        first.__code__ = second.__code__
        self.assertEqual(read(first, record), ('changed',) * 3)

    def test_monitoring_while_workers_run(self):
        monitor = sys.monitoring
        tool = monitor.PROFILER_ID
        monitor.use_tool_id(tool, 'method-jit-test')
        self.addCleanup(monitor.free_tool_id, tool)
        events = []
        monitor.register_callback(tool, monitor.events.LINE,
                                  lambda code, line: events.append(line))
        self.addCleanup(monitor.register_callback, tool, monitor.events.LINE, None)
        self.addCleanup(monitor.set_local_events, tool, kernel.__code__, 0)
        barrier = threading.Barrier(3, timeout=support.SHORT_TIMEOUT)

        def worker():
            for _ in range(100):
                kernel(1000, sys._jit.is_active)
            barrier.wait()
            for _ in range(10):
                barrier.wait()
                self.assertEqual(kernel(1000, sys._jit.is_active)[0], 499500)
                barrier.wait()

        def instrument():
            barrier.wait()
            for i in range(10):
                monitor.set_local_events(tool, kernel.__code__,
                                         monitor.events.LINE if i % 2 else 0)
                barrier.wait()
                barrier.wait()

        self.run_threads(worker, worker, instrument)
        self.assertTrue(events)

    def test_thread_reuse_and_retired_bytecode(self):
        retained = []
        def worker():
            for _ in range(100):
                kernel(1000, sys._jit.is_active)
            self.assertTrue(kernel(1000, sys._jit.is_active)[1])
            retained.append(executor_for(kernel))

        for _ in range(5):
            self.run_threads(worker, worker)
            sys._clear_internal_caches()
            gc.collect()
            _testinternalcapi.clear_executor_deletion_list()
            self.assertTrue(all(not e.is_valid() for e in retained))
        retained.clear()
        _testinternalcapi.clear_executor_deletion_list()

    def test_generator_moves_between_threads(self):
        def generate():
            i = 0
            while True:
                i += 1
                yield i
        generator = generate()
        result = []
        count = _testinternalcapi.TIER2_RESUME_THRESHOLD + 2
        ready = threading.Event()
        finished = threading.Event()
        def first_owner():
            for _ in range(count):
                result.append(next(generator))
            ready.set()
            self.assertIsNotNone(executor_for(generate))
            self.assertTrue(finished.wait(support.SHORT_TIMEOUT))
        def second_owner():
            self.assertTrue(ready.wait(support.SHORT_TIMEOUT))
            try:
                for _ in range(count):
                    result.append(next(generator))
            finally:
                finished.set()
        # Keep the old owner alive so the second thread cannot reuse its index.
        self.run_threads(first_owner, second_owner)
        self.assertEqual(result, list(range(1, 2 * count + 1)))
        generator.close()

    def test_tlbc_disabled(self):
        from test.support import script_helper
        script_helper.assert_python_ok(
            '-X', 'tlbc=0', '-c',
            'import sys; assert not sys._jit.is_enabled()', PYTHON_JIT='1')


if __name__ == '__main__':
    unittest.main()
