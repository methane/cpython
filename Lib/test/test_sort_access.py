"""Access to stored elements and callback results during list sorting."""

import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class SortAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_foreign_elements(self):
        class Number(float):
            pass

        def worker(box, results, mode):
            values = box.claim()
            calls = []

            def key(value):
                calls.append(1)
                return 0 if mode == 'constant' else value

            try:
                if mode == 'plain':
                    values.sort()
                else:
                    values.sort(key=key, reverse=True)
            except IllegalThreadAccessException:
                results.put(('denied', len(calls)))
            else:
                results.put(('allowed', len(calls)))
            # Return the shallow contents to their owner for verification.
            results.put(values)

        left, right = Number(2), Number(1)
        cases = (
            [left, right],
            [(left,), (right,)],
            [(0, left), (0, right)],
            [((left,),), ((right,),)],
            [0, 1.0, left],  # Type analysis stops before the foreign key.
        )
        for values in cases:
            for mode in ('plain', 'identity', 'constant'):
                with self.subTest(values=values, mode=mode):
                    results = threading.Channel()
                    thread = threading.Thread(
                        target=worker,
                        args=(threading.TransferBox(values), results, mode),
                        group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    status, calls = results.get()
                    # A constant key need not acquire an accessible tuple's
                    # contents. Passing a foreign scalar to key is forbidden.
                    if mode == 'constant' and isinstance(values[0], tuple):
                        self.assertEqual(status, 'allowed')
                        self.assertEqual(calls, len(values))
                    else:
                        self.assertEqual(status, 'denied')
                    if mode != 'plain' and values[0] is left:
                        self.assertEqual(calls, 0)
                    self.assertCountEqual(
                        [id(value) for value in results.get()],
                        [id(value) for value in values])

    def test_unprotected_elements(self):
        for factory in (threading.Lock, threading.RLock):
            lock = factory()
            with lock:
                value = lock.protect([])
                cases = ([value, value], [(value,), (value,)],
                         [(0, value), (0, value)])
            for values in cases:
                with lock:
                    expected_ids = [id(item) for item in values]
                for reverse in (False, True):
                    with self.subTest(lock=factory, reverse=reverse):
                        with self.assertRaises(UnprotectedAccessException):
                            values.sort(reverse=reverse)
                        with lock:
                            self.assertEqual([id(item) for item in values],
                                             expected_ids)

    def test_c_api_stored_element_access(self):
        capi = import_module('_testlimitedcapi')
        lock = threading.Lock()
        with lock:
            value = lock.protect([])
            values = [value, value]
        with self.assertRaises(UnprotectedAccessException):
            capi.list_sort(values)
        with lock:
            self.assertEqual(len(values), 2)
            self.assertIs(values[0], value)
            self.assertIs(values[1], value)

    def test_native_comparison_result(self):
        capi = import_module('_testcapi')
        lock = threading.Lock()
        with lock:
            result = lock.protect([42])
            values = [capi.NativeRichCompareResult((result,)) for _ in range(2)]
        with self.assertRaises(UnprotectedAccessException):
            values.sort()
        with lock:
            self.assertEqual(len(values), 2)
            self.assertIs(values[0][0], result)
            self.assertIs(values[1][0], result)


if __name__ == '__main__':
    unittest.main()
