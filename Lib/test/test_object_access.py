"""Access checks at generic object hash/truth C API boundaries."""

import sys
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class ObjectAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_foreign_object(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class LocalObject:
            def __getitem__(self, key):
                return key

        value = LocalObject()
        apis = (
            (capi.object_hash, (value,)),
            (capi.object_is_true, (value,)),
            (capi.object_richcomparebool, (value, value, 2)),
            (limited.object_repr, (value,)),
            (limited.object_getitem, (value, 0)),
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

        thread = threading.Thread(target=worker, args=((value,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), len(apis))


if __name__ == '__main__':
    unittest.main()
