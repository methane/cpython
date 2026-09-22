"""Access checks at public type metadata C API boundaries."""

import sys
import threading
import unittest

from test.support import SHORT_TIMEOUT, threading_helper
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
            (limited.get_type_fullyqualname, (LocalType,)),
            (limited.get_type_name, (LocalType,)),
            (limited.get_type_qualname, (LocalType,)),
            (limited.get_type_module_name, (LocalType,)),
            (limited.type_getflags, (LocalType,)),
            (internal.type_get_dict, (LocalType,)),
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

    @threading_helper.requires_working_threading()
    def test_name_results(self):
        """Name accessors must check values stored by a synchronized type."""
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)
        apis = (limited.get_type_name, limited.get_type_qualname)
        for api in apis:
            internal.object_declare_synchronized(api)

        class LocalType:
            pass

        LocalType.synchronize()
        ready = threading.Event()
        finish = threading.Event()

        def producer():
            class ForeignName(str):
                pass

            with sys.monitoring.StopTheWorld:
                LocalType.__name__ = ForeignName('foreign_name')
                LocalType.__qualname__ = ForeignName('foreign_qualname')
            ready.set()
            finish.wait()

        producer_thread = threading.Thread(
            target=producer, group=threading.ThreadGroup())
        producer_thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            result = threading.Channel()

            def consumer():
                denied = 0
                for api in apis:
                    try:
                        invoke(api, (LocalType,))
                    except IllegalThreadAccessException:
                        denied += 1
                result.put(denied)

            consumer_thread = threading.Thread(
                target=consumer, group=threading.ThreadGroup())
            consumer_thread.start()
            consumer_thread.join(SHORT_TIMEOUT)
            self.assertFalse(consumer_thread.is_alive())
            self.assertEqual(result.get(), len(apis))
        finally:
            finish.set()
            producer_thread.join(SHORT_TIMEOUT)
            self.assertFalse(producer_thread.is_alive())

    @threading_helper.requires_working_threading()
    def test_module_name_result(self):
        """PyType_GetModuleName must check an arbitrary __module__ value."""
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)
        internal.object_declare_synchronized(limited.get_type_module_name)

        class LocalType:
            pass

        # Make the type and its namespace available to the other group.  The
        # value stored in __module__ remains owned by the producer group.
        LocalType.synchronize()
        holder = SynchronizedDict()
        ready = threading.Event()
        finish = threading.Event()

        def producer():
            holder['value'] = object()
            ready.set()
            finish.wait()

        producer_thread = threading.Thread(
            target=producer, group=threading.ThreadGroup())
        producer_thread.start()
        try:
            self.assertTrue(ready.wait(SHORT_TIMEOUT))
            with sys.monitoring.StopTheWorld:
                LocalType.__module__ = holder['value']

            result = threading.Channel()

            def consumer():
                try:
                    invoke(limited.get_type_module_name, (LocalType,))
                except IllegalThreadAccessException:
                    result.put(True)
                else:
                    result.put(False)

            consumer_thread = threading.Thread(
                target=consumer, group=threading.ThreadGroup())
            consumer_thread.start()
            consumer_thread.join(SHORT_TIMEOUT)
            self.assertFalse(consumer_thread.is_alive())
            self.assertTrue(result.get())
        finally:
            finish.set()
            producer_thread.join(SHORT_TIMEOUT)
            self.assertFalse(producer_thread.is_alive())


if __name__ == '__main__':
    unittest.main()
