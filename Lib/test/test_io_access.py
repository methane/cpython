"""Access to streams retained by native I/O wrappers."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class IOAccessTests(unittest.TestCase):
    PRELUDE = '''
import io
import threading
from test.support import SuppressCrashReport

class Raw:
    closed = False
    name = 'raw'
    mode = 'r+b'
    def readable(self): return True
    def writable(self): return True
    def seekable(self): return True
    def tell(self): return 0
    def seek(self, *args): return 0
    def truncate(self, *args): return 0
    def read(self, *args): return b''
    def read1(self, *args): return b''
    def readall(self): return b''
    def readinto(self, target): return 0
    def write(self, data): return len(data)
    def flush(self): pass
    def close(self): self.closed = True
    def fileno(self): return 0
    def isatty(self): return False

lock = threading.Lock()
'''

    def run_script(self, script):
        assert_python_ok('-c', self.PRELUDE + textwrap.dedent(script))

    def test_buffered_stored_raw(self):
        for factory, operations in (
            ('io.BufferedReader', (
                'stream.closed', 'stream.name', 'stream.mode', 'stream.raw',
                'stream.readable()', 'stream.seekable()', 'stream.fileno()',
                'stream.isatty()', 'stream.tell()', 'stream.seek(0)',
                'stream.read()', 'stream.read1(1)', 'stream.peek()',
                'stream.readinto(bytearray(1))', 'stream.readline()',
                'stream.flush()', 'stream.detach()', 'stream.close()',
            )),
            ('io.BufferedWriter', (
                'stream.writable()', "stream.write(b'x')", 'stream.flush()',
                'stream.truncate()', 'stream.detach()', 'stream.close()',
            )),
            ('io.BufferedRandom', ('stream.read()', "stream.write(b'x')")),
        ):
            for operation in operations:
                with self.subTest(factory=factory, operation=operation):
                    self.run_script(f'''
                        with lock:
                            raw = lock.protect(Raw())
                            stream = {factory}(raw)
                        try:
                            with SuppressCrashReport():
                                try:
                                    {operation}
                                except UnprotectedAccessException:
                                    pass
                                else:
                                    raise AssertionError('unprotected raw used')
                        finally:
                            with lock:
                                assert stream.raw is raw
                                stream.close()
                                del stream
                    ''')

    def test_text_stored_buffer(self):
        for operation in (
            'stream.closed', 'stream.name', 'stream.buffer',
            'stream.fileno()', 'stream.isatty()', 'stream.flush()',
            'stream.detach()', 'stream.close()', 'stream.read()',
            "stream.write('text')", 'stream.seek(0)', 'stream.tell()',
            'stream.truncate()', 'stream.reconfigure(write_through=True)',
        ):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    with lock:
                        raw = lock.protect(Raw())
                        stream = io.TextIOWrapper(raw, encoding='utf-8')
                    try:
                        with SuppressCrashReport():
                            try:
                                {operation}
                            except UnprotectedAccessException:
                                pass
                            else:
                                raise AssertionError('unprotected buffer used')
                    finally:
                        with lock:
                            assert stream.buffer is raw
                            stream.close()
                            del stream
                ''')

    @threading_helper.requires_working_threading()
    def test_foreign_fileio_fast_closed_checks(self):
        for factory, operation in (
            ('io.BufferedReader(raw)', 'stream.read(1)'),
            ('io.BufferedWriter(raw)', "stream.write(b'x')"),
            ('io.BufferedRandom(raw)', 'stream.read(1)'),
            ("io.TextIOWrapper(io.BufferedRandom(raw), encoding='utf-8')",
             "stream.write('x')"),
        ):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    import os
                    import _testinternalcapi
                    from test.support import threading_helper
                    raw = io.FileIO(os.devnull, 'r+')
                    stream = {factory}
                    _testinternalcapi.object_declare_synchronized(stream)
                    results = SynchronizedList()
                    def worker():
                        try:
                            {operation}
                        except BaseException as exc:
                            results.append(type(exc).__name__)
                        else:
                            results.append('foreign raw used')
                    with SuppressCrashReport():
                        thread = threading.Thread(target=worker,
                                                  group=threading.ThreadGroup())
                        with threading_helper.start_threads([thread]):
                            pass
                    stream.close()
                    assert list(results) == ['IllegalThreadAccessException'], results
                ''')

    @threading_helper.requires_working_threading()
    def test_rwpair_stored_streams(self):
        for operation in (
            'stream.readable()', 'stream.writable()', 'stream.closed',
            'stream.read(1)', 'stream.peek()', 'stream.read1(1)',
            'stream.readinto(bytearray(1))', 'stream.readinto1(bytearray(1))',
            "stream.write(b'x')", 'stream.flush()', 'stream.isatty()',
            'stream.close()',
        ):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    import _testinternalcapi
                    from test.support import threading_helper
                    stream = io.BufferedRWPair(Raw(), Raw())
                    _testinternalcapi.object_declare_synchronized(stream)
                    results = SynchronizedList()
                    def worker():
                        try:
                            {operation}
                        except BaseException as exc:
                            results.append(type(exc).__name__)
                        else:
                            results.append('foreign child stream used')
                    with SuppressCrashReport():
                        thread = threading.Thread(target=worker,
                                                  group=threading.ThreadGroup())
                        with threading_helper.start_threads([thread]):
                            pass
                    stream.close()
                    assert list(results) == ['IllegalThreadAccessException'], results
                ''')

    def test_buffered_preserves_access_errors(self):
        for error in ('IllegalThreadAccessException', 'UnprotectedAccessException'):
            for kind in ('reader_init', 'writer_init', 'random_init',
                         'truncate', 'readinto', 'write'):
                with self.subTest(error=error, kind=kind):
                    self.run_script(f'''
                        class Count:
                            def __index__(self):
                                raise {error}('denied count')

                        class FailingRaw(Raw):
                            fail = False
                            def tell(self):
                                if self.fail and {kind!r} not in ('readinto', 'write'):
                                    raise {error}('denied position')
                                return 0
                            def readinto(self, target):
                                return Count() if self.fail else 0
                            def write(self, data):
                                return Count() if self.fail else len(data)

                        raw = FailingRaw()
                        stream = None
                        if {kind!r} == 'truncate':
                            stream = io.BufferedRandom(raw)
                        elif {kind!r} == 'readinto':
                            stream = io.BufferedReader(raw, 1)
                        elif {kind!r} == 'write':
                            stream = io.BufferedWriter(raw, 1)
                        raw.fail = True
                        try:
                            try:
                                if {kind!r} == 'reader_init':
                                    stream = io.BufferedReader(raw)
                                elif {kind!r} == 'writer_init':
                                    stream = io.BufferedWriter(raw)
                                elif {kind!r} == 'random_init':
                                    stream = io.BufferedRandom(raw)
                                elif {kind!r} == 'truncate':
                                    stream.truncate(0)
                                elif {kind!r} == 'readinto':
                                    stream.read1(1)
                                else:
                                    stream.write(b'xx')
                            except {error}:
                                pass
                            else:
                                raise AssertionError('access error was suppressed')
                        finally:
                            raw.fail = False
                            if stream is not None:
                                stream.close()
                    ''')

    def test_stream_reference_cleanup(self):
        self.run_script('''
            import sys
            with lock:
                raw = lock.protect(Raw())
                reader = io.BufferedReader(raw)
                text = io.TextIOWrapper(raw, encoding='utf-8')
                before = sys.getrefcount(raw)
                for _ in range(50):
                    assert reader.name == text.name == 'raw'
                    assert not reader.closed and not text.closed
                    assert reader.fileno() == text.fileno() == 0
                    assert reader.raw is text.buffer is raw
                    reader.flush()
                    text.flush()
                assert sys.getrefcount(raw) == before
            for _ in range(50):
                for stream in (reader, text):
                    try:
                        stream.name
                    except UnprotectedAccessException:
                        pass
                    else:
                        raise AssertionError('unprotected stream accessed')
            del stream
            with lock:
                assert sys.getrefcount(raw) == before
                assert reader.detach() is raw
                assert text.detach() is raw
                del reader, text
                raw.close()
        ''')


if __name__ == '__main__':
    unittest.main()
