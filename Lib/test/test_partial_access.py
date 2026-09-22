"""Access checks when partial retrieves captured call references."""

import functools
import operator
import threading
import unittest

from test.support import import_helper


class PartialAccessTests(unittest.TestCase):
    def test_captured_target_and_arguments(self):
        entered = []

        def consume(value, ignored):
            entered.append(True)

        def keyword_consume(ignored, *, value):
            entered.append(True)

        class Fallback:
            def __call__(self, value, ignored):
                entered.append(True)

        cases = (
            (lambda value: functools.partial(value.append), ()),
            (lambda value: functools.partial(operator.setitem, value, 0), ()),
            (lambda value: functools.partial(operator.setitem, value), (0,)),
            (lambda value: functools.partial(consume, value), ()),
            (lambda value: functools.partial(keyword_consume, value=value), ()),
            (lambda value: functools.partial(consume, functools.Placeholder, value), ()),
            (lambda value: functools.partial(Fallback(), value), ()),
        )
        for index, (factory, prefix) in enumerate(cases):
            with self.subTest(case=index):
                lock = threading.Lock()
                with lock:
                    value = lock.protect([0])
                    indirect = factory(value)

                def unlock():
                    lock.__exit__(None, None, None)
                    return 42

                for _ in range(100):
                    denied = False
                    with self.assertRaisesRegex(RuntimeError, 'owning context'):
                        with lock:
                            try:
                                if prefix:
                                    indirect(prefix[0], unlock())
                                else:
                                    indirect(unlock())
                            except UnprotectedAccessException:
                                denied = True
                    self.assertTrue(denied)
                    with lock:
                        self.assertEqual(value, [0])
                self.assertEqual(entered, [])

    def test_no_arguments_fast_path(self):
        lock = threading.Lock()
        with lock:
            value = lock.protect([])
            indirect = functools.partial(value.append, 42)
        denied = False
        with self.assertRaisesRegex(RuntimeError, 'owning context'):
            with lock:
                lock.__exit__(None, None, None)
                try:
                    indirect()
                except UnprotectedAccessException:
                    denied = True
        self.assertTrue(denied)
        with lock:
            self.assertEqual(value, [])

    def test_keyword_merge_releases_lock(self):
        lock = threading.Lock()
        entered = []
        release = [False]

        class Key(str):
            __hash__ = str.__hash__

            def __eq__(self, other):
                if release[0]:
                    release[0] = False
                    lock.__exit__(None, None, None)
                return str.__eq__(self, other)

        def consume(value, **kwargs):
            entered.append(True)

        with lock:
            value = lock.protect([])
            indirect = functools.partial(consume, value, **{Key('option'): 0})
        denied = False
        with self.assertRaisesRegex(RuntimeError, 'owning context'):
            with lock:
                release[0] = True
                try:
                    indirect(option=1)
                except UnprotectedAccessException:
                    denied = True
        self.assertTrue(denied)
        self.assertFalse(release[0], 'keyword comparison did not run')
        self.assertEqual(entered, [])

    def test_captured_target_cleanup_checks_result(self):
        lock = threading.Lock()

        class Target(list):
            def __del__(self):
                lock.__exit__(None, None, None)

        class Index:
            def __index__(self):
                indirect.__setstate__((int, (), {}, None))
                return 0

        with lock:
            value = lock.protect([])
            indirect = functools.partial(Target([value]).pop)
        denied = False
        with self.assertRaisesRegex(RuntimeError, 'owning context'):
            with lock:
                try:
                    # The vectorcall snapshot retains the native bound method
                    # until list.pop has returned its protected result. map
                    # calls partial from C, and the outer list would hide a
                    # missing result check from the VM's call-result check.
                    list(map(indirect, (Index(),)))
                except UnprotectedAccessException:
                    denied = True
        self.assertTrue(denied)

    def test_overridden_keyword_does_not_acquire_old_value(self):
        lock = threading.Lock()

        def function(*, value):
            return value

        class Fallback:
            def __call__(self, *, value):
                return value

        for target in (function, Fallback()):
            with lock:
                value = lock.protect([])
                indirect = functools.partial(target, value=value)
            self.assertEqual(indirect(value=42), 42)

    def test_fallback_accepts_dict_subclass(self):
        _testcapi = import_helper.import_module('_testcapi')

        class Keywords(dict):
            pass

        class Fallback:
            def __call__(self, *args, **kwargs):
                return args, kwargs

        indirect = functools.partial(Fallback())
        self.assertEqual(
            _testcapi.pyobject_fastcalldict(indirect, (42,), Keywords(option=1)),
            ((42,), {'option': 1}),
        )


if __name__ == '__main__':
    unittest.main()
