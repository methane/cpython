"""PEP 805 function classification follows shared closure bindings.

These tests deliberately use public Thread.start(), without changing callback
sharing states or using StopTheWorld to bypass access checks.
"""

import gc
import sys
import threading
import types
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
from test.support.import_helper import import_module


threading_helper.requires_working_threading(module=True)


class ReadonlyClosureTests(unittest.TestCase):
    def assert_shared(self, function):
        self.assertIs(function.__shareable__, threading.Shareable.SYNCHRONIZED)

    def assert_local(self, function):
        self.assertIs(function.__shareable__, threading.Shareable.LOCAL)

    def run_reader(self, reader):
        results = threading.Channel()

        def worker(reader, results):
            try:
                value = reader()
            except IllegalThreadAccessException as exc:
                tb = exc.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                results.put(('denied', tb.tb_frame.f_code.co_name))
            else:
                results.put(('value', value))

        thread = threading.Thread(target=worker, args=(reader, results),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        return results.get()

    def test_readonly_immutable_value(self):
        value = 42

        def reader():
            return value

        self.assert_shared(reader)
        self.assertEqual(self.run_reader(reader), ('value', 42))

    def test_readonly_shared_value(self):
        value = threading.Channel()

        def reader():
            return value

        self.assert_shared(reader)
        status, result = self.run_reader(reader)
        self.assertEqual(status, 'value')
        self.assertIs(result, value)

    def test_readonly_local_value_is_checked_at_load(self):
        value = []

        def reader():
            return value

        # The binding is read-only; sharing the function must not share value.
        self.assert_shared(reader)
        self.assertEqual(self.run_reader(reader), ('denied', 'reader'))
        self.assertIs(reader(), value)
        self.assertIs(value.__shareable__, threading.Shareable.LOCAL)

    def test_sibling_writer_keeps_reader_local(self):
        value = 0

        def reader():
            return value

        def writer():
            nonlocal value
            value += 1

        self.assert_local(reader)
        self.assert_local(writer)
        writer()
        self.assertEqual(reader(), 1)

    def test_readonly_transitive_closure(self):
        value = 42

        def middle():
            def reader():
                return value
            return reader

        self.assert_shared(middle)
        reader = middle()
        self.assert_shared(reader)
        self.assertEqual(self.run_reader(reader), ('value', 42))

    def test_attaching_writer_reclassifies_existing_reader(self):
        def make_reader():
            value = 0

            def reader():
                return value

            return reader

        def make_writer():
            value = 0

            def writer():
                nonlocal value
                value += 1

            return writer

        reader = make_reader()
        unrelated = make_reader()
        self.assert_shared(reader)
        self.assert_shared(unrelated)
        writer = types.FunctionType(make_writer().__code__, globals(),
                                    closure=reader.__closure__)
        self.assert_local(writer)
        self.assert_local(reader)
        self.assert_shared(unrelated)
        writer()
        self.assertEqual(reader(), 1)

    def test_code_replacement_reclassifies_sibling_reader(self):
        def make_readers():
            value = 0

            def first():
                return value

            def second():
                return value

            return first, second

        def make_writer():
            value = 0

            def writer():
                nonlocal value
                value += 1

            return writer

        first, second = make_readers()
        self.assert_shared(first)
        self.assert_shared(second)
        with self.assertWarns(DeprecationWarning):
            first.__code__ = make_writer().__code__
        self.assert_local(first)
        self.assert_local(second)
        first()
        self.assertEqual(second(), 1)

    def test_parent_rebinding_reclassifies_reader(self):
        value = 1

        def reader():
            return value

        self.assert_shared(reader)
        self.assertEqual(self.run_reader(reader), ('value', 1))
        value = 2
        self.assert_local(reader)
        self.assertEqual(reader(), 2)

    def test_reflective_rebinding_reclassifies_reader(self):
        for operation in ('attribute', 'frame'):
            with self.subTest(operation=operation):
                def factory():
                    value = 1

                    def reader():
                        return value

                    return reader, sys._getframe().f_locals

                reader, namespace = factory()
                self.assert_shared(reader)
                if operation == 'attribute':
                    reader.__closure__[0].cell_contents = 2
                else:
                    namespace['value'] = 2
                self.assert_local(reader)
                self.assertEqual(reader(), 2)

    def test_capi_rebinding_reclassifies_reader(self):
        capi = import_module('_testcapi')
        for setter in (capi.cell_set, capi.cell_set_raw):
            with self.subTest(setter=setter.__name__):
                def factory():
                    value = 1

                    def reader():
                        return value

                    return reader

                reader = factory()
                self.assert_shared(reader)
                setter(reader.__closure__[0], 2)
                self.assert_local(reader)
                self.assertEqual(reader(), 2)

    def test_rebinding_rejects_warmed_parallel_call(self):
        value = 1

        def reader():
            return value

        self.assert_shared(reader)
        ready = threading.Event()
        resume = threading.Event()
        results = threading.Channel()

        def worker(reader, ready, resume, results):
            for _ in range(200):
                assert reader() == 1
            ready.set()
            assert resume.wait(SHORT_TIMEOUT)
            try:
                reader()
            except IllegalThreadAccessException:
                results.put('denied')
            else:
                results.put('acquired')

        thread = threading.Thread(target=worker,
                                  args=(reader, ready, resume, results),
                                  group=threading.ThreadGroup())
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            value = 2
            self.assert_local(reader)
        finally:
            resume.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results.get(), 'denied')

    def test_capi_closure_replacement_reclassifies_reader(self):
        capi = import_module('_testcapi')

        def make_reader():
            value = 1

            def reader():
                return value

            return reader

        def make_writer():
            value = 0

            def writer():
                nonlocal value
                value += 1

            return writer

        reader = make_reader()
        writer = make_writer()
        self.assert_shared(reader)
        with self.assertWarns(DeprecationWarning):
            capi.function_set_closure(writer, reader.__closure__)
        self.assert_local(reader)
        writer()
        self.assertEqual(reader(), 2)

    def test_foreign_mutable_closure_cannot_be_reowned(self):
        def factory(results):
            value = 1

            def reader():
                return value

            def writer():
                nonlocal value
                value = 2

            results.put((reader.__code__, reader.__closure__))

        def worker(code, function_type, results):
            local_factory = function_type(code, {})
            local_factory(results)

        results = threading.Channel()
        thread = threading.Thread(target=worker,
                                  args=(factory.__code__, types.FunctionType,
                                        results),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        code, closure = results.get()
        with self.assertRaises(IllegalThreadAccessException):
            types.FunctionType(code, {}, closure=closure)

    def test_conflicting_mutable_cell_owners(self):
        value = 1
        results = threading.Channel()
        ready = threading.Event()
        resume = threading.Event()

        def middle():
            other = 1

            def reader():
                return value + other

            results.put(reader)
            ready.set()
            assert resume.wait(SHORT_TIMEOUT)
            other = 2

        thread = threading.Thread(target=middle, group=threading.ThreadGroup())
        thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            reader = results.get()
            value = 2
            self.assert_local(reader)
            self.assertEqual(reader(), 3)
        finally:
            resume.set()
            thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        with self.assertRaises(IllegalThreadAccessException):
            reader()

    def test_many_readers_are_reclassified(self):
        value = 1

        def reader():
            return value

        readers = [types.FunctionType(reader.__code__, {},
                                      closure=reader.__closure__)
                   for _ in range(300)]
        for function in readers:
            self.assert_shared(function)
        reader.__closure__[0].cell_contents = 2
        for function in readers:
            self.assert_local(function)
            self.assertEqual(function(), 2)

    def test_gc_frozen_reader_is_reclassified(self):
        value = 1

        def reader():
            return value

        self.assert_shared(reader)
        gc.freeze()
        try:
            value = 2
            self.assert_local(reader)
            self.assertEqual(reader(), 2)
        finally:
            gc.unfreeze()


if __name__ == '__main__':
    unittest.main()
