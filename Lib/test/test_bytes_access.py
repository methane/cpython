"""Access checks at the public bytes and bytearray C API boundaries."""

import sys
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class BytesAccessTests(unittest.TestCase):
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
