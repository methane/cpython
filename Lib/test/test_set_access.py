"""Access checks at the public set C API boundaries."""

import sys
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class SetAccessTests(unittest.TestCase):
    @staticmethod
    def native_invoker():
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        import_module('_testinternalcapi').object_declare_synchronized(invoke)
        return invoke

    @threading_helper.requires_working_threading()
    def test_foreign_set_container(self):
        capi = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = self.native_invoker()
        apis = (
            (capi.set_size, ()),
            (capi.set_contains, (1,)),
            (capi.set_add, (2,)),
            (capi.set_discard, (1,)),
            (capi.set_pop, ()),
            (capi.set_clear, ()),
        )
        for api, unused in apis:
            internal.object_declare_synchronized(api)

        foreign = {1}
        results = threading.Channel()

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                args = tuple((payload[0],) + extra for _, extra in apis)
            denied = 0
            for (api, _), call_args in zip(apis, args):
                try:
                    invoke(api, call_args)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), len(apis))

    @threading_helper.requires_working_threading()
    def test_iterator_result_access(self):
        shared = {object()}.synchronize()
        results = threading.Channel()

        def worker(mapping):
            with sys.monitoring.StopTheWorld:
                foreign = next(iter(mapping))
                local = {foreign}
            denied = 0
            for value in (mapping, local):
                try:
                    next(iter(value))
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        thread = threading.Thread(target=worker, args=(shared,),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 2)


if __name__ == '__main__':
    unittest.main()
