"""Ownership of extension types with a zero-initialized object header."""

import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


_testcapi = import_module('_testcapi')
_testinternalcapi = import_module('_testinternalcapi')


class StaticTypeAccessTests(unittest.TestCase):
    def test_immutable_extension_types_start_local(self):
        with self.assertWarns(DeprecationWarning):
            heap_type = _testcapi.make_immutable_type_with_base(object)
        for cls in (_testcapi.matmulType, _testcapi.Generic, heap_type):
            with self.subTest(cls=cls):
                self.assertIs(cls.__shareable__, threading.Shareable.LOCAL)
                self.assertEqual(_testinternalcapi.object_owner_id(cls),
                                 _testinternalcapi.object_owner_id(object()))

    @threading_helper.requires_working_threading()
    def test_extension_type_requires_explicit_declaration(self):
        with self.assertWarns(DeprecationWarning):
            cls = _testcapi.make_immutable_type_with_base(object)
        holder = SynchronizedDict(cls=cls)
        results = threading.Channel()

        def worker(holder, results):
            try:
                cls = holder['cls']
            except IllegalThreadAccessException:
                results.put('denied')
            else:
                assert cls.__dict__['__doc__'] is None
                assert cls().__shareable__ is threading.Shareable.LOCAL
                results.put('shared')

        for expected in ('denied', 'shared'):
            if expected == 'shared':
                _testinternalcapi.object_declare_immutable(cls)
            thread = threading.Thread(target=worker, args=(holder, results),
                                      group=threading.ThreadGroup())
            thread.start()
            thread.join(SHORT_TIMEOUT)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results.get(), expected)

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
