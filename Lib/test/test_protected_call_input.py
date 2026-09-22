"""Revalidate call inputs after later arguments release their protection."""

import functools
import operator
import sys
import threading
import unittest


class ProtectedCallInputTests(unittest.TestCase):
    def exercise(self, call, factory, expected, *, warm=False, after_warm=None):
        lock = threading.Lock()
        with lock:
            value = lock.protect(factory())

        def unlock():
            lock.__exit__(None, None, None)
            return 42

        if warm:
            with lock:
                for _ in range(100):
                    call(value, lambda: 42)
                if isinstance(value, list):
                    value[:] = expected
                else:
                    value.clear()
                    value.update(expected)
            if after_warm is not None:
                after_warm()

        for iteration in range(100):
            with self.subTest(call=call.__name__, iteration=iteration):
                denied = False
                with self.assertRaisesRegex(RuntimeError, 'owning context'):
                    with lock:
                        try:
                            call(value, unlock)
                        except UnprotectedAccessException:
                            denied = True
                self.assertTrue(denied, 'call used an input after its mutex was released')
                with lock:
                    self.assertEqual(value, expected)

    def test_native_receivers_and_arguments(self):
        def method(value, unlock):
            value.append(unlock())

        def bound(value, unlock):
            append = value.append
            append(unlock())

        def builtin(value, unlock):
            operator.setitem(value, 0, unlock())

        def general(value, unlock):
            functools.partial(operator.setitem)(value, 0, unlock())

        def keywords(value, unlock):
            value.update(changed=unlock())

        def star_args(value, unlock):
            value.append(*(unlock(),))

        def star_keywords(value, unlock):
            value.update(**{'changed': unlock()})

        for call in (method, bound, star_args):
            self.exercise(call, list, [], warm=True)
        for call in (builtin, general):
            self.exercise(call, lambda: [0], [0], warm=True)
        for call in (keywords, star_keywords):
            self.exercise(call, dict, {}, warm=True)

    def test_python_arguments_before_entry(self):
        entered = []

        def consume(value, ignored):
            entered.append(True)

        def direct(value, unlock):
            consume(value, unlock())

        def keywords(value, unlock):
            consume(value=value, ignored=unlock())

        def star_args(value, unlock):
            consume(*(value, unlock()))

        def star_keywords(value, unlock):
            consume(**{'value': value, 'ignored': unlock()})

        for call in (direct, keywords, star_args, star_keywords):
            self.exercise(call, list, [])
            self.exercise(call, list, [], warm=True, after_warm=entered.clear)
        self.assertEqual(entered, [], 'the callee must not run before input validation')

    def test_argument_iterator_releases_lock(self):
        lock = threading.Lock()
        with lock:
            value = lock.protect([])
        entered = []

        def consume(value):
            entered.append(True)

        class Arguments:
            def __iter__(self):
                yield value
                lock.__exit__(None, None, None)

        with self.assertRaisesRegex(RuntimeError, 'owning context'):
            with lock:
                with self.assertRaises(UnprotectedAccessException):
                    consume(*Arguments())
        self.assertEqual(entered, [])

    def test_protected_callable(self):
        entered = []

        class Callable:
            def __call__(self, ignored):
                entered.append(True)

        lock = threading.Lock()
        with lock:
            target = lock.protect(Callable())

        def unlock():
            lock.__exit__(None, None, None)
            return 42

        with self.assertRaisesRegex(RuntimeError, 'owning context'):
            with lock:
                with self.assertRaises(UnprotectedAccessException):
                    target(unlock())
        self.assertEqual(entered, [])

    def test_monitor_callback_releases_lock(self):
        lock = threading.Lock()
        with lock:
            value = lock.protect([])

        def positional(value):
            value.append(42)

        def keywords(value):
            consume(value=value, ignored=42)

        def expanded(value):
            consume(*(value, 42))

        entered = []

        def consume(value, ignored):
            entered.append(True)

        monitoring = sys.monitoring
        tool = 2
        monitoring.use_tool_id(tool, 'protected call input test')
        try:
            def callback(code, offset, callable, arg):
                lock.__exit__(None, None, None)

            monitoring.register_callback(tool, monitoring.events.CALL, callback)
            for call in (positional, keywords, expanded):
                monitoring.set_local_events(tool, call.__code__, monitoring.events.CALL)
                try:
                    with self.assertRaisesRegex(RuntimeError, 'owning context'):
                        with lock:
                            with self.assertRaises(UnprotectedAccessException):
                                call(value)
                finally:
                    monitoring.set_local_events(tool, call.__code__, 0)
                with lock:
                    self.assertEqual(value, [])
            self.assertEqual(entered, [])
        finally:
            monitoring.register_callback(tool, monitoring.events.CALL, None)
            monitoring.free_tool_id(tool)


if __name__ == '__main__':
    unittest.main()
