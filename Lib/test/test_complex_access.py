"""Access checks at the public complex C API boundaries."""

import sys
import threading
import unittest
import warnings

from test.support import swap_attr, threading_helper
from test.support.import_helper import import_module


class ComplexAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_conversion_result_after_warning(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        results = threading.Channel()

        def worker():
            class LocalComplex(complex):
                pass
            results.put((LocalComplex(2, 3),))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        holder = results.get()

        class Number:
            def __complex__(self):
                return holder[0]

        receiver = Number()
        invoke = capi.call_cfunction_raw_return_in_tuple
        for api, expected in (
            (limited.complex_realasdouble, 2.0),
            (limited.complex_imagasdouble, 3.0),
            (capi.complex_asccomplex, 2 + 3j),
        ):
            with self.subTest(api=api.__name__, access='allowed'):
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter('always', DeprecationWarning)
                    with sys.monitoring.StopTheWorld:
                        self.assertEqual(invoke(api, (receiver,)), (expected,))
                    self.assertEqual(len(recorded), 1)
            for raises in (False, True):
                with self.subTest(api=api.__name__, warning_raises=raises):
                    calls = []

                    def showwarning(*args, **kwargs):
                        calls.append(True)
                        sys.monitoring.StopTheWorld.__exit__(None, None, None)
                        if raises:
                            raise LookupError('complex conversion warning error')

                    with warnings.catch_warnings(), swap_attr(
                            warnings, 'showwarning', showwarning):
                        warnings.simplefilter('always', DeprecationWarning)
                        sys.monitoring.StopTheWorld.__enter__()
                        try:
                            error = (LookupError if raises
                                     else IllegalThreadAccessException)
                            with self.assertRaises(error):
                                invoke(api, (receiver,))
                        finally:
                            if not calls:
                                sys.monitoring.StopTheWorld.__exit__(
                                    None, None, None)
                        self.assertEqual(calls, [True])

    @threading_helper.requires_working_threading()
    def test_foreign_complex(self):
        capi = import_module('_testcapi')
        limited = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class LocalComplex(complex):
            pass

        value = LocalComplex(1, 2)
        apis = (
            (limited.complex_realasdouble, (value,)),
            (limited.complex_imagasdouble, (value,)),
            (capi.complex_asccomplex, (value,)),
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
