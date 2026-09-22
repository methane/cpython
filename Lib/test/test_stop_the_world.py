"""Debugger world pauses across ThreadGroups."""

import _thread
import gc
import os
import sys
import threading
import time
import unittest
import warnings

from test.support import SHORT_TIMEOUT
from test.support.import_helper import import_module


class StopTheWorldTests(unittest.TestCase):
    def run_native(self, work, *args):
        results = threading.Channel()
        def entry(work=work, args=args, results=results):
            try:
                result = work(*args)
            except BaseException as exc:
                trace = []
                tb = exc.__traceback__
                while tb is not None:
                    trace.append((tb.tb_frame.f_code.co_name, tb.tb_lineno))
                    tb = tb.tb_next
                results.put(('error', (str(exc), tuple(trace))))
            else:
                results.put(('ok', result))
        handle = _thread.start_joinable_thread(entry, group=threading.ThreadGroup())
        handle.join(SHORT_TIMEOUT)
        status, result = results.get()
        self.assertEqual(status, 'ok', result)
        return result

    def test_nesting_gc_and_exception(self):
        context = sys.monitoring.StopTheWorld
        with self.assertRaisesRegex(RuntimeError, 'no debugger world pause'):
            context.__exit__(None, None, None)
        def function(value=0):
            return value
        with self.assertRaisesRegex(LookupError, 'resume'):
            with context as entered:
                self.assertIs(entered, context)
                with context:
                    gc.collect()
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', DeprecationWarning)
                        function.__defaults__ = (42,)
                    self.assertEqual(function(), 42)
                    self.assertEqual(freeze({'answer': 42})['answer'], 42)
                raise LookupError('resume')
        with context:
            gc.collect()
        self.assertEqual(self.run_native(lambda: 42), 42)

    def test_foreign_access_is_scoped(self):
        value = []
        cell = (lambda: value).__closure__[0]
        shared = SynchronizedDict(value=value, cell=cell)
        def work(shared):
            denied = 0
            try:
                shared['value']
            except IllegalThreadAccessException:
                denied += 1
            with sys.monitoring.StopTheWorld:
                shared['value'].append(42)
                with sys.monitoring.StopTheWorld:
                    shared['cell'].cell_contents = 43
                    gc.collect()
            try:
                shared['value']
            except IllegalThreadAccessException:
                denied += 1
            return denied
        self.assertEqual(self.run_native(work, shared), 2)
        self.assertEqual(shared['value'], [42])
        self.assertEqual(cell.cell_contents, 43)

    def test_threads_pause_across_detach(self):
        for group in (sys.main_thread_group, threading.ThreadGroup()):
            with self.subTest(group=group):
                state = SynchronizedDict(count=0, stop=False, child=False)
                def worker(state=state):
                    while not state['stop']:
                        state['count'] += 1
                def child(state=state):
                    state['child'] = True
                handle = _thread.start_joinable_thread(worker, group=group)
                child_handle = None
                try:
                    deadline = time.monotonic() + SHORT_TIMEOUT
                    while state['count'] == 0:
                        if time.monotonic() > deadline:
                            self.fail('worker did not start')
                        time.sleep(0.001)
                    with sys.monitoring.StopTheWorld:
                        count = state['count']
                        child_handle = _thread.start_joinable_thread(child, group=group)
                        time.sleep(0.03)
                        self.assertEqual(state['count'], count)
                        self.assertFalse(state['child'])
                        with sys.monitoring.StopTheWorld:
                            gc.collect()
                    deadline = time.monotonic() + SHORT_TIMEOUT
                    while state['count'] == count:
                        if time.monotonic() > deadline:
                            self.fail('worker did not resume')
                        time.sleep(0.001)
                finally:
                    state['stop'] = True
                    handle.join(SHORT_TIMEOUT)
                    if child_handle is not None:
                        child_handle.join(SHORT_TIMEOUT)
                self.assertTrue(state['child'])

    def test_competing_pauses(self):
        results = SynchronizedList()
        def worker(results=results):
            for i in range(30):
                with sys.monitoring.StopTheWorld:
                    with sys.monitoring.StopTheWorld:
                        results.append(i)
        handles = [_thread.start_joinable_thread(worker, group=threading.ThreadGroup())
                   for _ in range(2)]
        for handle in handles:
            handle.join(SHORT_TIMEOUT)
        self.assertEqual(len(results), 60)

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires fork')
    def test_fork_rejected(self):
        with sys.monitoring.StopTheWorld:
            with self.assertRaisesRegex(RuntimeError, 'debugger world pause'):
                os.fork()

    def test_interpreter_creation_rejected(self):
        interpreters = import_module('_interpreters')
        with sys.monitoring.StopTheWorld:
            with self.assertRaises(interpreters.InterpreterError) as caught:
                interpreters.create()
            self.assertIn('debugger world pause', str(caught.exception.__context__))

    def test_interpreter_switching_rejected(self):
        interpreters = import_module('_interpreters')
        interp = interpreters.create()
        try:
            with sys.monitoring.StopTheWorld:
                with self.assertRaisesRegex(RuntimeError, 'debugger world pause'):
                    interpreters.exec(interp, 'pass')
                with self.assertRaisesRegex(RuntimeError, 'debugger world pause'):
                    interpreters.destroy(interp)
                with self.assertRaisesRegex(RuntimeError, 'debugger world pause'):
                    interpreters.decref(interp)
            interpreters.exec(interp, 'pass')
        finally:
            interpreters.destroy(interp)


if __name__ == '__main__':
    unittest.main()
