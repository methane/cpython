"""Access checks at public type metadata C API boundaries."""

import sys
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class TypeAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_foreign_type(self):
        limited = import_module('_testlimitedcapi')
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class LocalType:
            pass

        apis = (
            (limited.get_type_name, (LocalType,)),
            (limited.get_type_qualname, (LocalType,)),
            (limited.get_type_module_name, (LocalType,)),
            (limited.type_getflags, (LocalType,)),
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

        thread = threading.Thread(target=worker, args=((LocalType,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), len(apis))


if __name__ == '__main__':
    unittest.main()
