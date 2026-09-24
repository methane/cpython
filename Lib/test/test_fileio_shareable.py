"""Native FileIO state needed by shared standard streams."""

import errno
import io
import os
import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module
from test.support.os_helper import TESTFN, unlink


class FileIOStateTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(unlink, TESTFN)
        with io.FileIO(TESTFN, 'w') as file:
            file.write(b'contents')

    def make_file(self, mode='r'):
        file = io.FileIO(TESTFN, mode)
        self.addCleanup(file.close)
        return file

    def close_fd(self, fd):
        try:
            os.close(fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise

    def assert_fd_closed(self, fd):
        with self.assertRaises(OSError) as caught:
            os.fstat(fd)
        self.assertEqual(caught.exception.errno, errno.EBADF)

    def close_unowned_fd(self, file, fd):
        if file.closed or file.fileno() != fd:
            self.close_fd(fd)

    def test_reinitialize_mode(self):
        file = self.make_file('a+')
        file.__init__(TESTFN, 'r')
        self.assertEqual(file.mode, 'rb')
        self.assertTrue(file.readable())
        self.assertFalse(file.writable())
        self.assertEqual(file.read(), b'contents')
        file.__init__(TESTFN, 'w')
        self.assertEqual(file.mode, 'wb')
        self.assertFalse(file.readable())
        self.assertTrue(file.writable())

    def test_reentrant_opener_replaces_descriptor(self):
        file = self.make_file()
        inner_fds = []

        def opener(name, flags):
            file.__init__(TESTFN, 'r')
            inner_fd = file.fileno()
            inner_fds.append(inner_fd)
            self.addCleanup(self.close_unowned_fd, file, inner_fd)
            return os.open(name, flags)

        file.__init__(TESTFN, 'w', opener=opener)
        self.assert_fd_closed(inner_fds[0])
        self.assertEqual(file.mode, 'wb')
        self.assertFalse(file.readable())
        self.assertEqual(file.write(b'new'), 3)

    def test_failed_opener_preserves_reentrant_initialization(self):
        file = self.make_file()

        def opener(name, flags):
            file.__init__(TESTFN, 'r')
            self.addCleanup(self.close_unowned_fd, file, file.fileno())
            raise RuntimeError('opener failed')

        with self.assertRaisesRegex(RuntimeError, 'opener failed'):
            file.__init__(TESTFN, 'w', opener=opener)
        self.assertFalse(file.closed)
        self.assertEqual(file.mode, 'rb')
        self.assertEqual(file.read(), b'contents')

    def test_name_setter_failure_preserves_reentrant_initialization(self):
        class File(io.FileIO):
            callback = None

            def __setattr__(self, name, value):
                if name == 'name' and self.callback is not None:
                    callback, self.callback = self.callback, None
                    callback()
                    raise RuntimeError('setting name failed')
                super().__setattr__(name, value)

        file = File(TESTFN, 'r')
        self.addCleanup(file.close)
        opened_fds = []

        def opener(name, flags):
            fd = os.open(name, flags)
            opened_fds.append(fd)
            self.addCleanup(self.close_unowned_fd, file, fd)
            return fd

        file.callback = lambda: file.__init__(TESTFN, 'r')
        with self.assertRaisesRegex(RuntimeError, 'setting name failed'):
            file.__init__(TESTFN, 'r', opener=opener)
        self.assert_fd_closed(opened_fds[0])
        self.assertEqual(file.read(), b'contents')

    def test_seek_preserves_reinitialized_cache(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(self.close_fd, read_fd)
        self.addCleanup(self.close_fd, write_fd)
        file = io.FileIO(read_fd, 'r', closefd=False)
        self.addCleanup(file.close)

        class Position:
            def __index__(self):
                file.__init__(TESTFN, 'r')
                return 0

        # The old pipe is still open, so its failed seek must not set the
        # cache for the regular file installed by __index__.
        with self.assertRaises(OSError) as caught:
            file.seek(Position())
        self.assertEqual(caught.exception.errno, errno.ESPIPE)
        self.assertTrue(file.seekable())
        self.assertEqual(file.read(), b'contents')

    @unittest.skipUnless(hasattr(os.stat_result, 'st_blksize'),
                         'requires stat.st_blksize')
    def test_truncate_preserves_reinitialized_stat(self):
        other_name = TESTFN + 'other'
        self.addCleanup(unlink, other_name)
        with io.FileIO(other_name, 'w') as other:
            other.write(b'other contents')
        fd = os.open(TESTFN, os.O_RDWR)
        self.addCleanup(self.close_fd, fd)
        file = io.FileIO(fd, 'r+', closefd=False)
        self.addCleanup(file.close)

        class Size:
            def __index__(self):
                file.__init__(other_name, 'r')
                return 0

        size = Size()
        self.assertIs(file.truncate(size), size)
        self.assertEqual(os.fstat(fd).st_size, 0)
        self.assertEqual(file._blksize, os.fstat(file.fileno()).st_blksize)
        self.assertEqual(file.read(), b'other contents')

    @threading_helper.requires_working_threading()
    def test_interleaved_initializers(self):
        file = self.make_file()
        import_module('_testinternalcapi').object_declare_synchronized(file)
        entered = threading.Event()
        resume = threading.Event()
        results = SynchronizedList()

        def opener(name, flags):
            entered.set()
            if not resume.wait(timeout=SHORT_TIMEOUT):
                raise TimeoutError('initializer did not resume')
            return os.open(name, flags)

        def worker():
            try:
                file.__init__(TESTFN, 'w', opener=opener)
                results.append('initialized')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread], unlock=resume.set):
            self.assertTrue(entered.wait(timeout=SHORT_TIMEOUT))
            self.assertTrue(file.closed)
            file.__init__(TESTFN, 'r')
            inner_fd = file.fileno()
            self.addCleanup(self.close_unowned_fd, file, inner_fd)
            self.assertEqual(file.mode, 'rb')
            self.assertEqual(file.read(), b'contents')
            resume.set()
        self.assertEqual(list(results), ['initialized'])
        self.assert_fd_closed(inner_fd)
        self.assertEqual(file.mode, 'wb')
        self.assertFalse(file.readable())
        self.assertEqual(file.write(b'new'), 3)

    @threading_helper.requires_working_threading()
    def test_parallel_native_operations(self):
        file = self.make_file('a+')
        import_module('_testinternalcapi').object_declare_synchronized(file)
        barrier = threading.Barrier(4)
        results = SynchronizedList()

        def worker(value):
            try:
                barrier.wait(timeout=SHORT_TIMEOUT)
                for _ in range(50):
                    assert file.write(value) == len(value)
                    assert file.readable() and file.writable()
                    assert file.seekable()
                    assert not file.isatty()
                    assert not file._isatty_open_only()
                    assert not file.closed and file.closefd
                    assert file.mode == 'ab+'
                    assert file._blksize > 0
                    assert 'mode=' in repr(file)
                    assert file.fileno() >= 0
                    assert file.tell() >= len(b'contents')
                results.append('written')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))

        values = (b'A\n', b'B\n', b'C\n', b'D\n')
        threads = [threading.Thread(target=worker, args=(value,),
                                    group=threading.ThreadGroup())
                   for value in values]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(list(results), ['written'] * 4)
        file.seek(0)
        self.assertEqual(file.read(8), b'contents')
        self.assertCountEqual(file.readall().splitlines(),
                              [value[:1] for value in values] * 50)
        file.seek(0)
        destination = bytearray(8)
        self.assertEqual(file.readinto(destination), 8)
        self.assertEqual(destination, b'contents')

    @threading_helper.requires_working_threading()
    def test_parallel_reinitialization_and_metadata(self):
        file = self.make_file()
        import_module('_testinternalcapi').object_declare_synchronized(file)
        barrier = threading.Barrier(3)
        results = SynchronizedList()

        def initialize():
            try:
                barrier.wait(timeout=SHORT_TIMEOUT)
                for _ in range(200):
                    file.__init__(TESTFN, 'r')
                    file.close()
                results.append('initialized')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))

        def read_metadata():
            try:
                barrier.wait(timeout=SHORT_TIMEOUT)
                for _ in range(1000):
                    assert file._blksize > 0
                    assert file.mode == 'rb'
                    assert isinstance(file.closed, bool)
                    repr(file)
                    try:
                        assert not file._isatty_open_only()
                        assert isinstance(file.seekable(), bool)
                        assert isinstance(file.readall(), bytes)
                    except ValueError:
                        pass  # The initializer has closed the FileIO object.
                    except OSError as exc:
                        if exc.errno != errno.EBADF:
                            raise
                results.append('read')
            except BaseException as exc:
                results.append((type(exc).__name__, str(exc)))

        threads = [threading.Thread(target=target, group=threading.ThreadGroup())
                   for target in (initialize, read_metadata, read_metadata)]
        with threading_helper.start_threads(threads):
            pass
        self.assertCountEqual(list(results), ['initialized', 'read', 'read'])


if __name__ == '__main__':
    unittest.main()
