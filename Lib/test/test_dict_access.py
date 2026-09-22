"""Access checks at the public dictionary C API boundaries."""

import sys
import threading
import unittest

from test.support import threading_helper
from test.support.import_helper import import_module


class DictAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_foreign_dict(self):
        limited = import_module('_testlimitedcapi')
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class LocalDict(dict):
            pass

        value = LocalDict(key='value')
        apis = (
            (limited.dict_size, (value,)),
            (limited.dict_getitem, (value, 'key')),
            (limited.dict_getitemwitherror, (value, 'key')),
            (limited.dict_contains, (value, 'key')),
            (limited.dict_setitem, (value, 'new', 'value')),
            (limited.dict_delitem, (value, 'key')),
            (limited.dict_clear, (value,)),
            (limited.dict_keys, (value,)),
            (limited.dict_values, (value,)),
            (limited.dict_items, (value,)),
            (limited.dict_next, (value, 0)),
            (limited.dict_copy, (value,)),
            (capi.dict_getitemref, (value, 'key')),
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
        self.assertEqual(value, {'key': 'value'})


if __name__ == '__main__':
    unittest.main()
