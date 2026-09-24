"""Access checks at the public bytes and bytearray C API boundaries."""

import operator
import sys
import textwrap
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module
from test.support.script_helper import assert_python_ok


class BytesAccessTests(unittest.TestCase):
    def test_concat_preserves_buffer_access_errors(self):
        concat = import_module('_testlimitedcapi').bytearray_concat

        for error_type in (IllegalThreadAccessException,
                           UnprotectedAccessException):
            class Exporter:
                def __buffer__(self, flags):
                    raise error_type('buffer access denied')

            exporter = Exporter()
            target = bytearray(b'original')
            for operation, args in (
                (concat, (exporter, b'')),
                (concat, (b'', exporter)),
                (operator.add, (target, exporter)),
                (operator.iadd, (target, exporter)),
            ):
                with self.subTest(error=error_type, operation=operation,
                                  exporter_first=args[0] is exporter):
                    with self.assertRaisesRegex(error_type, 'buffer access denied'):
                        operation(*args)
                    self.assertEqual(target, b'original')

    def test_concat_releases_buffer_on_access_error(self):
        concat = import_module('_testlimitedcapi').bytearray_concat
        released = []

        class FirstExporter:
            def __buffer__(self, flags):
                return memoryview(b'first')

            def __release_buffer__(self, view):
                released.append(True)

        class SecondExporter:
            def __buffer__(self, flags):
                raise IllegalThreadAccessException('buffer access denied')

        with self.assertRaisesRegex(IllegalThreadAccessException,
                                    'buffer access denied'):
            concat(FirstExporter(), SecondExporter())
        self.assertEqual(released, [True])

    @threading_helper.requires_working_threading()
    def test_join_checks_stored_buffers(self):
        assert_python_ok('-c', textwrap.dedent('''
            import threading
            from test.support import SHORT_TIMEOUT

            class LocalBytes(bytes):
                pass

            def worker(payload, results):
                class Exporter:
                    def __buffer__(self, flags):
                        return payload[-1]
                for separator in (b'|', bytearray(b'|')):
                    for items in (payload, [Exporter()]):
                        try:
                            separator.join(items)
                        except BaseException as exc:
                            results.put(type(exc).__name__)
                        else:
                            results.put('allowed')

            for value in (LocalBytes(b'x'), bytearray(b'x'), memoryview(b'x')):
                for prefix in ((), (b'first',)):
                    results = threading.Channel()
                    thread = threading.Thread(
                        target=worker, args=(prefix + (value,), results),
                        group=threading.ThreadGroup())
                    thread.start()
                    thread.join(SHORT_TIMEOUT)
                    assert not thread.is_alive()
                    observed = [results.get() for _ in range(4)]
                    assert observed == ['IllegalThreadAccessException'] * 4, observed
        '''))

    @threading_helper.requires_working_threading()
    def test_foreign_bytes_and_bytearray_operands(self):
        capi = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class LocalBytes(bytes):
            pass

        bytes_value = LocalBytes(b"foreign")
        bytearray_value = bytearray(b"foreign")
        apis = (
            (capi.bytes_size, (bytes_value,)),
            (capi.bytes_asstring, (bytes_value, 1)),
            (capi.bytes_asstringandsize, (bytes_value, 1)),
            (capi.bytes_repr, (bytes_value, 0)),
            (capi.bytes_fromobject, (bytes_value,)),
            (capi.bytes_concat, (bytes_value, b"x")),
            (capi.bytearray_fromobject, (bytearray_value,)),
            (capi.bytearray_size, (bytearray_value,)),
            (capi.bytearray_asstring, (bytearray_value, 1)),
            (capi.bytearray_concat, (bytearray_value, b"x")),
            (capi.bytearray_resize, (bytearray_value, 0)),
        )
        for api, unused in apis:
            internal.object_declare_synchronized(api)

        results = threading.Channel()

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                args = tuple(extra for _, extra in apis)
            denied = 0
            for (api, _), call_args in zip(apis, args):
                try:
                    invoke(api, call_args)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        thread = threading.Thread(
            target=worker, args=((bytes_value, bytearray_value),),
            group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), len(apis))


if __name__ == '__main__':
    unittest.main()
