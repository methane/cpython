"""Ownership of extension types with a zero-initialized object header."""

import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


_testcapi = import_module('_testcapi')
_testinternalcapi = import_module('_testinternalcapi')


class StaticTypeAccessTests(unittest.TestCase):
    def test_main_group_owns_zero_initialized_type(self):
        cls = _testcapi.RecursingInfinitelyError
        self.assertIs(cls.__shareable__, threading.Shareable.LOCAL)
        self.assertEqual(_testinternalcapi.object_owner_id(cls),
                         _testinternalcapi.object_owner_id(object()))
        self.assertTrue(issubclass(cls, Exception))

    @threading_helper.requires_working_threading()
    def test_foreign_group_cannot_acquire_type(self):
        shared = SynchronizedDict(cls=_testcapi.RecursingInfinitelyError)
        results = threading.Channel()

        def worker(shared, results):
            try:
                shared['cls']
            except IllegalThreadAccessException:
                results.put('denied')
            else:
                results.put('acquired')

        thread = threading.Thread(target=worker, args=(shared, results),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results.get(), 'denied')


if __name__ == '__main__':
    unittest.main()
