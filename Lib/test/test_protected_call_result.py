"""Access must be checked after call argument cleanup runs finalizers."""

import threading
import unittest
import functools
import collections
import sys


class ProtectedCallResultTests(unittest.TestCase):
    def test_source_finalizer_releases_protecting_lock(self):
        lock = threading.Lock()

        class Example:
            __slots__ = ('release_on_delete',)

            def __init__(self):
                self.release_on_delete = True

            def __copy__(self):
                other = type(self)()
                other.release_on_delete = False
                return other

            def __del__(self):
                if self.release_on_delete:
                    lock.__exit__(None, None, None)

        denied = False
        with self.assertRaisesRegex(RuntimeError, 'owning context'):
            with lock:
                try:
                    lock.protect(Example()).release_on_delete
                except UnprotectedAccessException:
                    denied = True
                self.assertFalse(lock.locked())
        self.assertTrue(denied, 'used a protected call result after argument cleanup unlocked it')

    def test_native_call_cleanup_paths(self):
        def descriptor(mapping, release):
            return mapping.get('value', release()).__class__

        def bound(mapping, release):
            method = mapping.get
            return method('value', release()).__class__

        def star_args(mapping, release):
            return mapping.get(*('value', release())).__class__

        def general(mapping, release):
            return functools.partial(mapping.get, 'value')(release()).__class__

        def keywords(mapping, release):
            return min([mapping['value']], default=release()).__class__

        def star_keywords(mapping, release):
            return min(*([mapping['value']],), **{'default': release()}).__class__

        def one_argument(mapping, release):
            return [mapping['value']].__getitem__(release()).__class__

        def no_arguments(mapping, release):
            return collections.deque([release(), mapping['value']]).pop().__class__

        for call in (descriptor, bound, star_args, general, keywords,
                     star_keywords, one_argument, no_arguments):
            lock = threading.Lock()

            class Release:
                def __index__(self):
                    return 0

                def __del__(self):
                    lock.__exit__(None, None, None)

            with lock:
                mapping = {'value': lock.protect([])}
            # Exercise cold calls, specialization and warmed execution using
            # the same function code while each temporary argument is fresh.
            for iteration in range(100):
                with self.subTest(call=call.__name__, iteration=iteration):
                    denied = False
                    with self.assertRaisesRegex(RuntimeError, 'owning context'):
                        with lock:
                            try:
                                call(mapping, Release)
                            except UnprotectedAccessException:
                                denied = True
                            self.assertFalse(lock.locked())
                    self.assertTrue(denied)

    def test_python_frame_cleanup(self):
        def return_value(value, unused):
            return value

        def direct(value, release):
            return return_value(value, release()).__class__

        def keywords(value, release):
            return return_value(value=value, unused=release()).__class__

        def star_args(value, release):
            return return_value(*(value, release())).__class__

        def local_finalizer(value, release):
            unused = release()
            return value

        def native_forwarder(value, release):
            # functools.partial enters Python through a C API entry frame.
            return functools.partial(local_finalizer, value)(release).__class__

        for call in (direct, keywords, star_args, native_forwarder):
            lock = threading.Lock()

            class Release:
                def __del__(self):
                    lock.__exit__(None, None, None)

            with lock:
                value = lock.protect([])
            for iteration in range(100):
                with self.subTest(call=call.__name__, iteration=iteration):
                    denied = False
                    with self.assertRaisesRegex(RuntimeError, 'owning context'):
                        with lock:
                            try:
                                call(value, Release)
                            except UnprotectedAccessException:
                                denied = True
                            self.assertFalse(lock.locked())
                    self.assertTrue(denied)

    def test_instrumented_call_and_return(self):
        lock = threading.Lock()

        class Release:
            def __del__(self):
                lock.__exit__(None, None, None)

        def native(mapping):
            return mapping.get('value', Release()).__class__

        def python_return(value):
            unused = Release()
            return value

        with lock:
            mapping = {'value': lock.protect([])}
        monitoring = sys.monitoring
        tool = 2
        seen = []

        def callback(*args):
            seen.append(args[0])

        monitoring.use_tool_id(tool, 'protected call result access test')
        try:
            monitoring.register_callback(tool, monitoring.events.CALL, callback)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, callback)
            monitoring.set_local_events(tool, native.__code__, monitoring.events.CALL)
            monitoring.set_local_events(tool, python_return.__code__, monitoring.events.PY_RETURN)
            for call in (native, python_return):
                denied = False
                with self.assertRaisesRegex(RuntimeError, 'owning context'):
                    with lock:
                        try:
                            if call is native:
                                call(mapping)
                            else:
                                call(mapping['value']).__class__
                        except UnprotectedAccessException:
                            denied = True
                self.assertTrue(denied)
            self.assertIn(native.__code__, seen)
            self.assertIn(python_return.__code__, seen)
        finally:
            monitoring.set_local_events(tool, native.__code__, 0)
            monitoring.set_local_events(tool, python_return.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.CALL, None)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(tool)


if __name__ == '__main__':
    unittest.main()
