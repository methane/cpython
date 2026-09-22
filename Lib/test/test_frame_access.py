"""C frame accessors must validate receivers acquired by native code."""

import sys
import threading
import unittest

from test.support import (
    SHORT_TIMEOUT, import_helper, script_helper, threading_helper,
)


_testcapi = import_helper.import_module('_testcapi')
threading_helper.requires_working_threading(module=True)


def make_frame(results):
    try:
        raise RuntimeError
    except RuntimeError as error:
        results.put((error.__traceback__.tb_frame,))


def make_function_with_local_namespace(results):
    def invoke(getframe, probe, operation):
        return probe((getframe(),), operation)

    namespace = {'__builtins__': {}}
    results.put(type(invoke)(invoke.__code__, namespace))


def make_name(results):
    class Name(str):
        pass

    results.put((Name('results'),))


def wait_for_frame_inspection(ready, finish, results):
    ready.set()
    finish.wait()
    try:
        raise RuntimeError
    except RuntimeError as error:
        try:
            frame = error.__traceback__.tb_frame
            results.put(frame.f_code.co_name)
        except IllegalThreadAccessException:
            results.put('wrong owner')


def wait_for_generator_inspection(ready, finish, results):
    def generate():
        yield 0

    generator = generate()
    results.put((generator,))
    ready.set()
    finish.wait()
    try:
        results.put(generator.gi_frame.f_code.co_name)
    except IllegalThreadAccessException:
        results.put('wrong owner')
    finally:
        generator.close()


class FrameAccessTests(unittest.TestCase):
    def test_threadstate_frame_allocation_failure(self):
        script_helper.assert_python_ok('-c', '''
import _testcapi
def fresh_frame():
    _testcapi.frame_get_nomemory(None)
fresh_frame()
''')

    def test_threadstate_remote_frame_allocation_failure(self):
        script_helper.assert_python_ok('-c', '''
import _testcapi
import threading
from test.support import SHORT_TIMEOUT

ready = threading.Event()
finish = threading.Event()
results = []
def worker():
    results.append(_testcapi.threadstate_as_capsule())
    ready.set()
    finish.wait()
    results.append('resumed')

thread = threading.Thread(target=worker)
thread.start()
try:
    assert ready.wait(SHORT_TIMEOUT)
    _testcapi.frame_get_nomemory(results[0])
finally:
    finish.set()
    thread.join(SHORT_TIMEOUT)
assert not thread.is_alive()
assert results[-1] == 'resumed'
''')

    def test_threadstate_get_current_frame(self):
        holder = _testcapi.threadstate_as_capsule()
        frame, = _testcapi.threadstate_frame_from_tuple(holder)
        try:
            self.assertIs(frame, sys._getframe())
        finally:
            del frame

    def test_threadstate_get_remote_frame(self):
        publish = _testcapi.threadstate_as_capsule
        internal = import_helper.import_module('_testinternalcapi')
        internal.object_declare_synchronized(publish)

        def worker(publish, ready, finish, results):
            results.put(publish())
            ready.set()
            finish.wait()

        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                ready = threading.Event()
                finish = threading.Event()
                results = threading.Channel()
                group = threading.ThreadGroup() if foreign else None
                thread = threading.Thread(target=worker, group=group,
                                          args=(publish, ready, finish, results))
                thread.start()
                try:
                    self.assertTrue(ready.wait(SHORT_TIMEOUT))
                    holder = results.get()
                    if foreign:
                        with self.assertRaises(IllegalThreadAccessException):
                            _testcapi.threadstate_frame_from_tuple(holder)
                        with sys.monitoring.StopTheWorld:
                            inspected = _testcapi.threadstate_frame_from_tuple(holder)
                            self.assertIsNotNone(inspected)
                            self.assertIsInstance(inspected[0], type(sys._getframe()))
                        with self.assertRaises(IllegalThreadAccessException):
                            inspected[0]
                    else:
                        frame, = _testcapi.threadstate_frame_from_tuple(holder)
                        try:
                            while frame.f_back is not None:
                                if frame.f_code is worker.__code__:
                                    break
                                frame = frame.f_back
                            self.assertIs(frame.f_code, worker.__code__)
                        finally:
                            del frame
                finally:
                    finish.set()
                    thread.join(SHORT_TIMEOUT)
                self.assertFalse(thread.is_alive())

    def test_cross_group_generator_frame_materialization(self):
        ready = threading.Event()
        finish = threading.Event()
        results = threading.Channel()
        thread = threading.Thread(target=wait_for_generator_inspection,
                                  args=(ready, finish, results),
                                  group=threading.ThreadGroup())
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            holder = results.get()
            with sys.monitoring.StopTheWorld:
                inspected = (holder[0].gi_frame,)
            with self.subTest(access='inspector'):
                with self.assertRaises(IllegalThreadAccessException):
                    inspected[0]
        finally:
            finish.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        with self.subTest(access='worker'):
            self.assertEqual(results.get(), 'generate')

    def test_cross_group_frame_materialization(self):
        ready = threading.Event()
        finish = threading.Event()
        results = threading.Channel()
        thread = threading.Thread(target=wait_for_frame_inspection,
                                  args=(ready, finish, results),
                                  group=threading.ThreadGroup())
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            with sys.monitoring.StopTheWorld:
                frames = sys._current_frames()
                frame = frames[thread.ident]
                while frame.f_code is not wait_for_frame_inspection.__code__:
                    frame = frame.f_back
                inspected = (frame,)
            with self.subTest(access='inspector'):
                with self.assertRaises(IllegalThreadAccessException):
                    inspected[0]
        finally:
            finish.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        with self.subTest(access='worker'):
            self.assertEqual(results.get(), 'wait_for_frame_inspection')
        with self.subTest(access='after exit'):
            with self.assertRaises(IllegalThreadAccessException):
                inspected[0]

    def test_foreign_variable_name(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_name, args=(results,),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        name = results.get()
        frame = sys._getframe()
        try:
            with self.assertRaises(IllegalThreadAccessException):
                _testcapi.frame_get_from_tuple((frame,), 'var', name)
        finally:
            del frame

    def test_unprotected_variable_value(self):
        lock = threading.Lock()
        with lock:
            results = lock.protect([])
        frame = sys._getframe()
        try:
            for operation in ('var', 'varstring'):
                with self.subTest(operation=operation):
                    with self.assertRaises(UnprotectedAccessException):
                        _testcapi.frame_get_from_tuple((frame,), operation)
        finally:
            del frame

    def test_unprotected_closure_value(self):
        lock = threading.Lock()
        with lock:
            results = lock.protect([])

        def probe(operation):
            if operation is None:
                return results
            return _testcapi.frame_get_from_tuple((sys._getframe(),), operation)

        def generate():
            yield results

        for operation in ('var', 'varstring'):
            with self.subTest(operation=operation, state='running'):
                with self.assertRaises(UnprotectedAccessException):
                    probe(operation)
            # Access before COPY_FREE_VARS has run also initializes the cells.
            generator = generate()
            try:
                with self.subTest(operation=operation, state='unstarted'):
                    with self.assertRaises(UnprotectedAccessException):
                        _testcapi.frame_get_from_tuple((generator.gi_frame,),
                                                      operation)
            finally:
                generator.close()

    def test_foreign_frame_namespace(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_function_with_local_namespace,
                                  args=(results,), group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        invoke = results.get()
        for operation in ('globals', 'builtins'):
            with self.subTest(operation=operation):
                with self.assertRaises(IllegalThreadAccessException):
                    invoke(sys._getframe, _testcapi.frame_get_from_tuple,
                           operation)

    def test_foreign_receiver(self):
        results = threading.Channel()
        thread = threading.Thread(target=make_frame, args=(results,),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        holder = results.get()
        for operation in ('code', 'back', 'locals', 'globals', 'builtins',
                          'generator', 'var', 'varstring', 'lineno', 'lasti'):
            with self.subTest(operation=operation):
                with self.assertRaises(IllegalThreadAccessException):
                    _testcapi.frame_get_from_tuple(holder, operation)

    def test_local_receiver(self):
        results = None
        frame = sys._getframe()
        try:
            self.assertIs(_testcapi.frame_get_from_tuple((frame,), 'code'),
                          frame.f_code)
            self.assertIs(_testcapi.frame_get_from_tuple((frame,), 'back'),
                          frame.f_back is not None)
            for operation in ('lineno', 'lasti'):
                with self.subTest(operation=operation):
                    self.assertGreaterEqual(
                        _testcapi.frame_get_from_tuple((frame,), operation), 0)
            for operation in ('locals', 'globals', 'builtins', 'generator',
                              'var', 'varstring'):
                with self.subTest(operation=operation):
                    self.assertTrue(
                        _testcapi.frame_get_from_tuple((frame,), operation))
        finally:
            del frame

    def test_unknown_line_number(self):
        def generate():
            yield 0

        code = generate.__code__.replace(co_linetable=b'')
        generator = type(generate)(code, {})()
        try:
            frame = generator.gi_frame
            self.assertEqual(_testcapi.frame_get_from_tuple((frame,), 'lineno'),
                             -1)
            self.assertIsNone(frame.f_lineno)
            self.assertIn('line -1', repr(frame))
        finally:
            generator.close()


if __name__ == '__main__':
    unittest.main()
