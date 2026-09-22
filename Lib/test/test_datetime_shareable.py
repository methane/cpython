"""Sharing of datetime's process-wide static objects."""

import unittest

from test.support.script_helper import assert_python_ok


class DateTimeSharingTests(unittest.TestCase):
    def test_static_objects_across_interpreters(self):
        # Use a fresh process so Main performs the first attribute acquisitions.
        assert_python_ok('-c', '''if True:
            import datetime
            import _interpreters

            names = ('date', 'datetime', 'time', 'timedelta', 'timezone', 'tzinfo')
            for name in names:
                getattr(datetime, name)
            assert datetime.UTC.utcoffset(None) == datetime.timedelta(0)
            for _ in range(2):
                interpid = _interpreters.create()
                try:
                    result = _interpreters.run_string(interpid, """
import datetime
from threading import Shareable
for name in ('date', 'datetime', 'time', 'timedelta', 'timezone', 'tzinfo'):
    cls = getattr(datetime, name)
    assert cls.__shareable__ is Shareable.IMMUTABLE
assert datetime.UTC is datetime.timezone.utc
assert datetime.UTC.__shareable__ is Shareable.IMMUTABLE
offset = datetime.UTC.utcoffset(None)
assert offset == datetime.timedelta(0)
assert offset.__shareable__ is Shareable.IMMUTABLE
assert hash(offset) == hash(datetime.timedelta(0))
assert datetime.date(2026, 1, 2).isoformat() == '2026-01-02'
""")
                    assert result is None, result
                finally:
                    _interpreters.destroy(interpid)
            assert datetime.UTC.utcoffset(None) == datetime.timedelta(0)
        ''')


if __name__ == '__main__':
    unittest.main()
