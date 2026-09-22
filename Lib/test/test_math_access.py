"""Access checks at math iterator C API boundaries."""

import math
import sys
import threading
import unittest

from test.support import threading_helper


@freeze
class ForeignIterator:
    def __init__(self, value):
        self.value = value
        self.used = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.used:
            raise StopIteration
        self.used = True
        return self.value


class MathAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_sumprod_iterator_result_access(self):
        value = object()
        results = threading.Channel()

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                left = ForeignIterator(payload[0])
                right = ForeignIterator(1)
            try:
                math.sumprod(left, right)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, args=((value,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())


if __name__ == '__main__':
    unittest.main()
