"""Access checks at the public Unicode C API boundaries."""

import sys
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class UnicodeAccessTests(unittest.TestCase):
    def foreign_string(self):
        results = threading.Channel()

        def worker():
            class LocalStr(str):
                pass
            results.put((LocalStr('foreign'),))

        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        return results.get()

    @threading_helper.requires_working_threading()
    def test_join_checks_stored_strings(self):
        capi = import_module('_testlimitedcapi')
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        holder = self.foreign_string()
        for prefix, suffix in (((), ()), (('first',), ()),
                               ((), ('last',)), (('first',), ('last',))):
            values = prefix + holder + suffix
            for factory in (tuple, list, SynchronizedList):
                with sys.monitoring.StopTheWorld:
                    items = factory(values)
                    expected = '|'.join(values)
                for native in (False, True):
                    with self.subTest(prefix=prefix, suffix=suffix,
                                      container=factory.__name__, native=native):
                        with self.assertRaises(IllegalThreadAccessException):
                            if native:
                                invoke(capi.unicode_join, ('|', items))
                            else:
                                '|'.join(items)
                        with sys.monitoring.StopTheWorld:
                            self.assertEqual('|'.join(items), expected)
                            self.assertEqual(invoke(capi.unicode_join,
                                                    ('|', items)), (expected,))

    @threading_helper.requires_working_threading()
    def test_join_rechecks_separator_after_iteration(self):
        capi = import_module('_testlimitedcapi')
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        holder = self.foreign_string()
        for raises in (False, True):
            with self.subTest(iteration_raises=raises):
                calls = []

                class Items:
                    def __iter__(self):
                        calls.append(True)
                        sys.monitoring.StopTheWorld.__exit__(None, None, None)
                        if raises:
                            raise LookupError('join iteration error')
                        return iter(('first', 'last'))

                sys.monitoring.StopTheWorld.__enter__()
                try:
                    args = (holder[0], Items())
                    error = LookupError if raises else IllegalThreadAccessException
                    with self.assertRaises(error):
                        invoke(capi.unicode_join, args)
                finally:
                    if not calls:
                        sys.monitoring.StopTheWorld.__exit__(None, None, None)
                self.assertEqual(calls, [True])

    @threading_helper.requires_working_threading()
    def test_foreign_unicode_operands(self):
        limited = import_module('_testlimitedcapi')
        internal = import_module('_testinternalcapi')
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class LocalStr(str):
            pass

        value = LocalStr('foreign')
        foreign_bytes = bytearray(b'foreign')
        apis = (
            (limited.unicode_getlength, (value,)),
            (limited.unicode_readchar, (value, 0)),
            (limited.unicode_substring, (value, 0, 3)),
            (limited.unicode_fromobject, (value,)),
            (limited.unicode_aswidechar, (value, 8)),
            (limited.unicode_aswidechar_null, (value, 8)),
            (limited.unicode_aswidecharstring, (value,)),
            (limited.unicode_aswidecharstring_null, (value,)),
            (limited.unicode_asutf8andsize, (value, 8)),
            (limited.unicode_asutf8andsize_null, (value, 8)),
            (limited.unicode_asutf8string, (value,)),
            (limited.unicode_concat, (value, 'x')),
            (limited.unicode_count, (value, 'f', 0, 7)),
            (limited.unicode_find, (value, 'f', 0, 7, 1)),
            (limited.unicode_findchar, (value, ord('f'), 0, 7, 1)),
            (limited.unicode_join, (value, ('x', 'y'))),
            (limited.unicode_fromencodedobject, (foreign_bytes, 'utf-8')),
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

        thread = threading.Thread(target=worker, args=((value, foreign_bytes),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), len(apis))


if __name__ == '__main__':
    unittest.main()
