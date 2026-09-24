"""Native buffered stream lifecycle during callbacks and parallel calls."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class BufferedStateTests(unittest.TestCase):
    PRELUDE = '''
import io

class Raw:
    closed = False
    name = 'raw'
    def readable(self): return True
    def writable(self): return True
    def seekable(self): return True
    def tell(self): return 0
    def seek(self, *args): return 0
    def readinto(self, target): return 0
    def write(self, source): return len(source)
    def flush(self): pass
    def close(self): self.closed = True
'''

    def run_script(self, script):
        script = self.PRELUDE + textwrap.dedent(script)
        assert_python_ok('-c', 'from test.support import SuppressCrashReport\n'
                         'with SuppressCrashReport():\n' +
                         textwrap.indent(script, '    '))

    def test_reinitialize_during_read(self):
        for factory in ('io.BufferedReader', 'io.BufferedRandom'):
            for size in (2, 0):
                with self.subTest(factory=factory, size=size):
                    self.run_script(f'''
                        class ReadingRaw(Raw):
                            def readinto(self, target):
                                try:
                                    stream.__init__(Raw(), {size})
                                except RuntimeError as exc:
                                    assert 'reentrant' in str(exc)
                                else:
                                    raise AssertionError('active buffer replaced')
                                assert stream.raw is self
                                target[0] = ord('A')
                                return 1

                        original = ReadingRaw()
                        stream = {factory}(original, 8)
                        assert stream.read(1) == b'A'
                        assert stream.raw is original
                        stream.__init__(Raw(), 2)
                        assert stream.read(1) == b''
                        stream.close()
                    ''')

    def test_detach_during_read(self):
        for factory in ('io.BufferedReader', 'io.BufferedRandom'):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    class ReadingRaw(Raw):
                        def readinto(self, target):
                            try:
                                stream.detach()
                            except RuntimeError as exc:
                                assert 'reentrant' in str(exc)
                            else:
                                raise AssertionError('active raw stream detached')
                            assert stream.raw is self
                            target[0] = ord('A')
                            return 1

                    original = ReadingRaw()
                    stream = {factory}(original, 8)
                    assert stream.read(1) == b'A'
                    assert stream.raw is original
                    assert stream.detach() is original
                    original.close()
                ''')

    def test_reinitialize_during_write(self):
        for factory in ('io.BufferedWriter', 'io.BufferedRandom'):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    written = []
                    class WritingRaw(Raw):
                        def write(self, source):
                            try:
                                stream.__init__(Raw(), 2)
                            except RuntimeError as exc:
                                assert 'reentrant' in str(exc)
                            else:
                                raise AssertionError('active buffer replaced')
                            assert stream.raw is self
                            written.append(bytes(source))
                            return len(source)

                    original = WritingRaw()
                    stream = {factory}(original, 8)
                    assert stream.write(b'abc') == 3
                    stream.flush()
                    assert written == [b'abc'], written
                    stream.__init__(Raw(), 2)
                    assert stream.write(b'next') == 4
                    stream.close()
                ''')

    def test_reinitialize_during_constructor_callbacks(self):
        for factory, callbacks in (
            ('io.BufferedReader', ('readable', 'tell')),
            ('io.BufferedWriter', ('writable', 'tell')),
            ('io.BufferedRandom', ('seekable', 'readable', 'writable', 'tell')),
        ):
            for callback in callbacks:
                with self.subTest(factory=factory, callback=callback):
                    self.run_script(f'''
                        attempted = []
                        class InitializingRaw(Raw):
                            def {callback}(self):
                                attempted.append(True)
                                try:
                                    stream.__init__(Raw(), 2)
                                except RuntimeError as exc:
                                    assert 'reentrant' in str(exc)
                                else:
                                    raise AssertionError('recursive init succeeded')
                                return {0 if callback == 'tell' else True!r}

                        stream = {factory}(Raw(), 8)
                        replacement = InitializingRaw()
                        stream.__init__(replacement, 4)
                        assert attempted == [True], attempted
                        assert stream.raw is replacement
                        stream.close()
                    ''')

    def test_failed_initializer_releases_lock(self):
        for factory, callbacks in (
            ('io.BufferedReader', ('readable', 'tell')),
            ('io.BufferedWriter', ('writable', 'tell')),
            ('io.BufferedRandom', ('seekable', 'readable', 'writable', 'tell')),
        ):
            for callback in callbacks:
                with self.subTest(factory=factory, callback=callback):
                    self.run_script(f'''
                        class FailingRaw(Raw):
                            def {callback}(self):
                                raise UnprotectedAccessException('denied initialization')

                        stream = {factory}(Raw(), 8)
                        try:
                            stream.__init__(FailingRaw(), 4)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('initialization unexpectedly succeeded')
                        replacement = Raw()
                        stream.__init__(replacement, 4)
                        assert stream.raw is replacement
                        stream.close()
                    ''')

    def test_reinitialize_discards_cached_position(self):
        for factory in ('io.BufferedReader', 'io.BufferedRandom'):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    class FailingTell(io.BytesIO):
                        fail = True
                        def tell(self):
                            if self.fail:
                                self.fail = False
                                raise OSError('initial position unavailable')
                            return super().tell()

                    first = io.BytesIO(b'old data')
                    first.seek(5)
                    stream = {factory}(first, 8)
                    stream.__init__(FailingTell(b'abcdefgh'), 8)
                    assert stream.read(1) == b'a'
                    assert stream.seek(5) == 5
                    assert stream.read(1) == b'f'
                    stream.close()
                ''')

    def test_reinitialize_during_position_query(self):
        for operation in ('tell', 'seek'):
            for callback in ('tell', 'index'):
                with self.subTest(operation=operation, callback=callback):
                    self.run_script(f'''
                        attempted = []
                        def reinitialize():
                            attempted.append(True)
                            try:
                                stream.__init__(io.BytesIO(b'replaced'), 2)
                            except RuntimeError as exc:
                                assert 'reentrant' in str(exc)
                            else:
                                raise AssertionError('active position query replaced')

                        class Position:
                            def __init__(self, value): self.value = value
                            def __index__(self):
                                reinitialize()
                                return self.value

                        class QueryRaw(io.BytesIO):
                            querying = False
                            def tell(self):
                                if not self.querying:
                                    # Force seek to query an unknown raw position.
                                    raise OSError('initial position unavailable')
                                value = super().tell()
                                if {callback!r} == 'index':
                                    return Position(value)
                                reinitialize()
                                return value

                        original = QueryRaw(b'abcdefgh')
                        stream = io.BufferedReader(original, 8)
                        assert stream.read(1) == b'a'
                        original.querying = True
                        result = stream.{operation}({2 if operation == 'seek' else ''})
                        assert result == {2 if operation == 'seek' else 1}, result
                        assert attempted == [True], attempted
                        assert stream.raw is original
                        assert stream.read(1) == {b'c' if operation == 'seek' else b'b'!r}
                        stream.close()
                    ''')

    def test_closed_callback_reinitialization(self):
        for factory, operation, error, message in (
            ('io.BufferedReader', 'stream.read(0)', 'ValueError', 'uninitialized'),
            ('io.BufferedWriter', "stream.write(b'')", 'RuntimeError', 'reentrant'),
            ('io.BufferedRandom', 'stream.read(0)', 'ValueError', 'uninitialized'),
        ):
            with self.subTest(factory=factory):
                self.run_script(f'''
                    class ClosingRaw(Raw):
                        @property
                        def closed(self):
                            try:
                                stream.__init__(Raw(), 0)
                            except ValueError:
                                pass
                            return False

                    stream = {factory}(ClosingRaw(), 8)
                    try:
                        {operation}
                    except {error} as exc:
                        assert {message!r} in str(exc)
                    else:
                        raise AssertionError('used an uninitialized stream')
                    stream.__init__(Raw(), 8)
                    stream.close()
                ''')

    def test_seek_callbacks_invalidate_initialization(self):
        for callback in ('seekable', 'index'):
            with self.subTest(callback=callback):
                self.run_script(f'''
                    def invalidate():
                        try:
                            stream.__init__(Raw(), 0)
                        except ValueError:
                            pass

                    class SeekingRaw(Raw):
                        def seekable(self):
                            if {callback!r} == 'seekable':
                                invalidate()
                            return True
                    class Position:
                        def __index__(self):
                            if {callback!r} == 'index':
                                invalidate()
                            return 0

                    stream = io.BufferedReader(SeekingRaw(), 8)
                    try:
                        stream.seek(Position())
                    except ValueError as exc:
                        assert 'uninitialized' in str(exc)
                    else:
                        raise AssertionError('sought an uninitialized stream')
                    stream.__init__(Raw(), 8)
                    stream.close()
                ''')

    @threading_helper.requires_working_threading()
    def test_reinitialize_waits_for_read(self):
        self.run_script('''
            import os
            import threading
            import _testinternalcapi
            from test.support import SHORT_TIMEOUT, threading_helper

            entered = threading.Event()
            resume = threading.Event()
            initializing = threading.Event()
            initialized = threading.Event()
            results = SynchronizedList()

            @freeze
            class WaitingFile(io.FileIO):
                def readinto(self, target):
                    entered.set()
                    if not resume.wait(timeout=SHORT_TIMEOUT):
                        raise TimeoutError('read did not resume')
                    return super().readinto(target)

            read_fd, write_fd = os.pipe()
            try:
                raw = WaitingFile(read_fd, 'r', closefd=False)
                replacement = io.FileIO(os.devnull, 'r')
                stream = io.BufferedReader(raw, 8)
                for obj in (raw, replacement, stream):
                    _testinternalcapi.object_declare_synchronized(obj)
                os.write(write_fd, b'A')

                def read():
                    try:
                        results.append(stream.read(1))
                    except BaseException as exc:
                        results.append((type(exc).__name__, str(exc)))

                def initialize():
                    try:
                        initializing.set()
                        stream.__init__(replacement, 2)
                        initialized.set()
                        results.append('initialized')
                    except BaseException as exc:
                        results.append((type(exc).__name__, str(exc)))

                threads = [threading.Thread(target=target,
                                             group=threading.ThreadGroup())
                           for target in (read, initialize)]
                with threading_helper.start_threads(threads[:1], unlock=resume.set):
                    assert entered.wait(timeout=SHORT_TIMEOUT)
                    with threading_helper.start_threads(threads[1:], unlock=resume.set):
                        assert initializing.wait(timeout=SHORT_TIMEOUT)
                        assert not initialized.wait(timeout=0.1)
                        resume.set()
                expected = sorted([b'A', 'initialized'], key=repr)
                assert sorted(results, key=repr) == expected, results
                assert initialized.is_set()
                assert stream.raw is replacement
                assert stream.read() == b''
                stream.close()
                raw.close()
            finally:
                os.close(read_fd)
                os.close(write_fd)
        ''')

    @threading_helper.requires_working_threading()
    def test_waiting_readline_reloads_buffer(self):
        self.run_script('''
            import threading
            import time
            from test.support import SHORT_TIMEOUT, threading_helper

            entered = threading.Event()
            resume = threading.Event()
            initializing = threading.Event()
            waiting = threading.Event()
            results = SynchronizedList()

            class WaitingSeek(io.BytesIO):
                def seek(self, *args):
                    entered.set()
                    if not resume.wait(timeout=SHORT_TIMEOUT):
                        raise TimeoutError('seek did not resume')
                    return super().seek(*args)

            stream = io.BufferedReader(WaitingSeek(b'abcdefgh'), 8)
            assert stream.read(1) == b'a'

            def seek():
                try:
                    results.append(stream.seek(0, 2))
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))

            def initialize():
                initializing.set()
                try:
                    stream.__init__(io.BytesIO(b'Z\\n'), 2)
                    results.append('initialized')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))

            def readline():
                waiting.set()
                try:
                    results.append(stream.readline())
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))

            threads = [threading.Thread(target=target)
                       for target in (seek, initialize, readline)]
            with threading_helper.start_threads(threads[:1], unlock=resume.set):
                assert entered.wait(timeout=SHORT_TIMEOUT)
                with threading_helper.start_threads(threads[1:2], unlock=resume.set):
                    assert initializing.wait(timeout=SHORT_TIMEOUT)
                    time.sleep(0.05)
                    with threading_helper.start_threads(threads[2:], unlock=resume.set):
                        assert waiting.wait(timeout=SHORT_TIMEOUT)
                        time.sleep(0.05)
                        resume.set()
            expected = [8, 'initialized', b'Z\\n']
            assert sorted(results, key=repr) == sorted(expected, key=repr), results
            stream.close()
        ''')

    @threading_helper.requires_working_threading()
    def test_waiting_read_checks_failed_initialization(self):
        self.run_script('''
            import threading
            import time
            from test.support import SHORT_TIMEOUT, threading_helper

            entered = threading.Event()
            resume = threading.Event()
            initializing = threading.Event()
            waiting = threading.Event()
            results = SynchronizedList()

            class WaitingRaw(Raw):
                def readinto(self, target):
                    entered.set()
                    if not resume.wait(timeout=SHORT_TIMEOUT):
                        raise TimeoutError('read did not resume')
                    target[0] = ord('A')
                    return 1

            stream = io.BufferedReader(WaitingRaw(), 8)
            def first_read():
                try:
                    results.append(stream.read1(1))
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))

            def initialize():
                initializing.set()
                try:
                    stream.__init__(Raw(), 0)
                except ValueError:
                    results.append('invalid initialization')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))

            def second_read():
                waiting.set()
                try:
                    results.append(stream.read1(1))
                except ValueError:
                    results.append('uninitialized read')
                except BaseException as exc:
                    results.append((type(exc).__name__, str(exc)))

            threads = [threading.Thread(target=target)
                       for target in (first_read, initialize, second_read)]
            with threading_helper.start_threads(threads[:1], unlock=resume.set):
                assert entered.wait(timeout=SHORT_TIMEOUT)
                with threading_helper.start_threads(threads[1:2], unlock=resume.set):
                    assert initializing.wait(timeout=SHORT_TIMEOUT)
                    # Queue the initializer before the second reader. Both
                    # must wait for the first reader's native buffer lock.
                    time.sleep(0.05)
                    with threading_helper.start_threads(threads[2:], unlock=resume.set):
                        assert waiting.wait(timeout=SHORT_TIMEOUT)
                        time.sleep(0.05)
                        resume.set()
            expected = [b'A', 'invalid initialization', 'uninitialized read']
            assert sorted(results, key=repr) == sorted(expected, key=repr), results
            stream.__init__(Raw(), 8)
            stream.close()
        ''')


if __name__ == '__main__':
    unittest.main()
