"""Thread exception reporting must not access a foreign stderr object."""

import io
import os
import sys
import tempfile
import textwrap
import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.script_helper import assert_python_ok


threading_helper.requires_working_threading(module=True)


class ThreadErrorOutputTests(unittest.TestCase):
    PRELUDE = '''
import sys
import threading

def worker():
    raise ValueError('parallel worker failure')

def start():
    thread = threading.Thread(target=worker, group=threading.ThreadGroup())
    thread.start()
    thread.join(10)
    assert not thread.is_alive()

original = sys.stderr
calls = []
class LocalStream:
    def write(self, text):
        calls.append(text)
    def flush(self):
        pass
'''

    def run_script(self, body):
        return assert_python_ok('-c', self.PRELUDE + textwrap.dedent(body))[2]

    def assert_reported(self, stderr):
        self.assertIn(b'Exception in thread ', stderr)
        self.assertIn(b'ValueError: parallel worker failure', stderr)
        self.assertNotIn(b'IllegalThreadAccessException', stderr)
        self.assertNotIn(b'UnprotectedAccessException', stderr)

    def test_native_fallback_lifetime(self):
        def worker():
            raise ValueError('in-process worker failure')

        original_stderr = sys.stderr
        original_hook = threading.excepthook
        saved_fd = os.dup(2)
        try:
            with tempfile.TemporaryFile() as output:
                try:
                    os.dup2(output.fileno(), 2)
                    sys.stderr = io.StringIO()
                    threading.excepthook = threading.__excepthook__
                    for _ in range(4):
                        thread = threading.Thread(target=worker,
                                                  group=threading.ThreadGroup())
                        thread.start()
                        thread.join(SHORT_TIMEOUT)
                        self.assertFalse(thread.is_alive())
                finally:
                    sys.stderr = original_stderr
                    threading.excepthook = original_hook
                    os.dup2(saved_fd, 2)
                output.seek(0)
                text = output.read()
                message = b'ValueError: in-process worker failure'
                self.assertEqual(text.count(message), 4)
                self.assertEqual(text.count(b'Exception in thread '), 4)
        finally:
            os.close(saved_fd)

    def test_default_stderr(self):
        self.assert_reported(self.run_script('start()'))

    def test_worker_creates_children_with_foreign_stderr(self):
        stderr = self.run_script('''
            completed = threading.Channel()
            stream = LocalStream()
            sys.stderr = stream
            def parent():
                for group in (None, threading.ThreadGroup()):
                    child = threading.Thread(target=worker, group=group)
                    child.start()
                    child.join(10)
                    assert not child.is_alive()
                completed.put('ok')
            try:
                thread = threading.Thread(target=parent,
                                          group=threading.ThreadGroup())
                thread.start()
                thread.join(10)
                assert not thread.is_alive()
                assert completed.get() == 'ok'
            finally:
                sys.stderr = original
            assert stream.__shareable__ is threading.Shareable.LOCAL
            # The Main-group child can use this stream. The foreign-group
            # child must report through the native fallback instead.
            assert 'ValueError: parallel worker failure' in ''.join(calls)
        ''')
        self.assert_reported(stderr)
        self.assertEqual(stderr.count(b'ValueError: parallel worker failure'), 1)

    def test_saved_constructor_fallback(self):
        stderr = self.run_script('''
            children = threading.Channel()
            stream = LocalStream()
            sys.stderr = stream
            def parent():
                children.put(threading.Thread(target=worker,
                                              group=threading.ThreadGroup()))
            try:
                thread = threading.Thread(target=parent,
                                          group=threading.ThreadGroup())
                thread.start()
                thread.join(10)
                assert not thread.is_alive()
                child = children.get()
                sys.stderr = None
                child.start()
                child.join(10)
                assert not child.is_alive()
            finally:
                sys.stderr = original
            assert calls == []
        ''')
        self.assert_reported(stderr)

    def test_constructor_without_stream_lock(self):
        stderr = self.run_script('''
            lock = threading.Lock()
            with lock:
                stream = lock.protect(LocalStream())
                sys.stderr = stream
            try:
                thread = threading.Thread(target=worker,
                                          group=threading.ThreadGroup())
                sys.stderr = None
                thread.start()
                thread.join(10)
                assert not thread.is_alive()
            finally:
                sys.stderr = original
            assert calls == []
        ''')
        self.assert_reported(stderr)

    def test_local_stream_is_not_used_or_promoted(self):
        stderr = self.run_script('''
            stream = LocalStream()
            sys.stderr = stream
            try:
                start()
            finally:
                sys.stderr = original
            assert calls == []
            assert stream.__shareable__ is threading.Shareable.LOCAL
        ''')
        self.assert_reported(stderr)

    def test_protected_stream_without_its_lock(self):
        stderr = self.run_script('''
            lock = threading.Lock()
            with lock:
                stream = lock.protect(LocalStream())
                sys.stderr = stream
                thread = threading.Thread(target=worker,
                                          group=threading.ThreadGroup())
            try:
                thread.start()
                thread.join(10)
                assert not thread.is_alive()
            finally:
                sys.stderr = original
            assert calls == []
            with lock:
                assert stream.__shareable__ is threading.Shareable.PROTECTED
        ''')
        self.assert_reported(stderr)

    def test_saved_local_stream(self):
        stderr = self.run_script('''
            stream = LocalStream()
            sys.stderr = stream
            thread = threading.Thread(target=worker, group=threading.ThreadGroup())
            sys.stderr = None
            try:
                thread.start()
                thread.join(10)
                assert not thread.is_alive()
            finally:
                sys.stderr = original
            assert calls == []
        ''')
        self.assert_reported(stderr)

    def test_accessible_stream_is_used(self):
        stderr = self.run_script('''
            messages = threading.Channel()
            class SharedStream:
                def write(self, text):
                    messages.put(text)
                def flush(self):
                    pass
            sys.stderr = freeze(SharedStream())
            try:
                start()
            finally:
                sys.stderr = original
            parts = []
            while True:
                try:
                    parts.append(messages.get())
                except IndexError:
                    break
            assert 'ValueError: parallel worker failure' in ''.join(parts)
        ''')
        self.assertEqual(stderr, b'')

    def test_none_streams_suppress_output(self):
        stderr = self.run_script('''
            sys.stderr = None
            try:
                start()
            finally:
                sys.stderr = original
        ''')
        self.assertEqual(stderr, b'')


if __name__ == '__main__':
    unittest.main()
