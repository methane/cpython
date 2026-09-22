import gc
import sys
import textwrap
import threading
import unittest
import weakref

from test import support
from test.support import import_helper, threading_helper


_testinternalcapi = import_helper.import_module('_testinternalcapi')


@unittest.skipUnless(support.Py_GIL_DISABLED, 'requires a free-threaded build')
class MimallocTests(unittest.TestCase):
    def test_qsbr_full_page(self):
        _testinternalcapi.test_mimalloc_qsbr()

    @threading_helper.requires_working_threading()
    def test_interpreter_teardown(self):
        code = textwrap.dedent('''
            import gc
            import threading
            class Node:
                pass
            def allocate():
                for _ in range(1000):
                    obj = Node()
                    obj.cycle = obj
            thread = threading.Thread(target=allocate)
            thread.start()
            thread.join()
            gc.collect()
        ''')
        for _ in range(5):
            self.assertEqual(support.run_in_subinterp_with_config(
                code, own_gil=True, use_main_obmalloc=False,
                allow_fork=False, allow_exec=False, allow_threads=True,
                allow_daemon_threads=False, check_multi_interp_extensions=True,
            ), 0)

    @threading_helper.requires_working_threading()
    def test_collect_from_other_thread(self):
        class Node:
            pass

        objects = [Node() for _ in range(1000)]

        def collect():
            objects.clear()
            gc.collect()

        with threading_helper.start_threads([threading.Thread(target=collect)]):
            pass

    @threading_helper.requires_working_threading()
    def test_abandoned_allocated_blocks(self):
        # getallocatedblocks() visits areas without visiting individual blocks.
        # It must collect cross-thread frees before reading an area's used count.
        objects = []
        count = 20000

        def allocate():
            objects.extend(bytes(1000) for _ in range(count))

        with threading_helper.start_threads([threading.Thread(target=allocate)]):
            pass
        before = sys.getallocatedblocks()
        objects.clear()
        after = sys.getallocatedblocks()
        self.assertGreaterEqual(before - after, count)

    @threading_helper.requires_working_threading()
    def test_abandoned_cycles(self):
        # Objects from a terminated thread must remain visible to the GC,
        # including objects with a preheader and objects in singleton pages.
        class Node:
            pass

        class LargeNode:
            __slots__ = ('cycle', '__weakref__') + tuple(
                f'field_{i}' for i in range(10000))

        refs = []

        def allocate():
            for cls in (Node, LargeNode):
                for _ in range(20):
                    obj = cls()
                    obj.cycle = obj
                    refs.append(weakref.ref(obj))

        was_enabled = gc.isenabled()
        gc.disable()
        try:
            with threading_helper.start_threads([threading.Thread(target=allocate)]):
                pass
            self.assertTrue(all(ref() is not None for ref in refs))
            gc.collect()
            self.assertTrue(all(ref() is None for ref in refs))
        finally:
            if was_enabled:
                gc.enable()


if __name__ == '__main__':
    unittest.main()
