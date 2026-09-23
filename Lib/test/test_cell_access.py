"""Access checks when cell contents become Python references."""

import threading
import types
import unittest
import weakref

from test.support import SHORT_TIMEOUT, gc_collect, threading_helper
from test.support.import_helper import import_module


def make_cells(results):
    value = 42
    filled = (lambda: value).__closure__[0]
    empty_value = 0
    empty = (lambda: empty_value).__closure__[0]
    del empty.cell_contents
    results.put((filled,))
    results.put((empty,))


class CellReceiverTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_foreign_receiver(self):
        capi = import_module('_testcapi')
        results = threading.Channel()
        thread = threading.Thread(target=make_cells, args=(results,),
                                  group=threading.ThreadGroup())
        thread.start()
        thread.join(SHORT_TIMEOUT)
        self.assertFalse(thread.is_alive())
        for state in ('filled', 'empty'):
            holder = results.get()
            with self.subTest(state=state):
                with self.assertRaises(IllegalThreadAccessException):
                    capi.cell_get_from_tuple(holder)

    def test_local_receiver(self):
        capi = import_module('_testcapi')
        value = object()
        cell = (lambda: value).__closure__[0]
        self.assertIs(capi.cell_get_from_tuple((cell,)), value)
        del cell.cell_contents
        self.assertIsNone(capi.cell_get_from_tuple((cell,)))


class CellAccessTests(unittest.TestCase):
    def test_protected_contents(self):
        capi = import_module('_testcapi')
        for factory in (threading.Lock, threading.RLock):
            for construct in (False, True):
                with self.subTest(lock=factory, construct=construct):
                    lock = factory()
                    with lock:
                        value = lock.protect([])
                        if construct:
                            cell = types.CellType(value)
                        else:
                            cell = types.CellType()
                            capi.cell_set(cell, value)
                    with self.assertRaises(UnprotectedAccessException):
                        capi.cell_get(cell)
                    with lock:
                        self.assertIs(capi.cell_get(cell), value)
                    capi.cell_set(cell)
                    self.assertIsNone(capi.cell_get(cell))

    @threading_helper.requires_working_threading()
    def test_cell_reads(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        getter = capi.cell_get
        setter = capi.cell_set_from_tuple
        internal.object_declare_synchronized(getter)
        internal.object_declare_synchronized(setter)

        class Value:
            pass
        foreign = Value()
        reference = weakref.ref(foreign)
        results = threading.Channel()

        def worker(holder, getter, setter):
            def make_reader(value):
                def reader():
                    return value
                return reader

            def make_annotation(value):
                class C:
                    x: value
                return C.__annotate__

            try:
                reader = make_reader(None)
                cell = reader.__closure__[0]
                annotate = make_annotation(None)
                annotation_cell = annotate.__closure__[
                    annotate.__code__.co_freevars.index('value')]
                # Populate through C so argument checks do not reject the
                # foreign value before the cell-read operations under test.
                setter(cell, holder)
                setter(annotation_cell, holder)
                reads = (reader, lambda: cell.cell_contents,
                         lambda: getter(cell), lambda: annotate(1))
                for read in reads:
                    for _ in range(100):
                        try:
                            read()
                        except IllegalThreadAccessException:
                            pass
                        else:
                            results.put('foreign cell contents exposed')
                            return
                local = []
                cell.cell_contents = annotation_cell.cell_contents = local
                assert reader() is local
                assert cell.cell_contents is local
                assert getter(cell) is local
                assert annotate(1)['x'] is local
                cell.cell_contents = annotation_cell.cell_contents = 42
                assert reader() == cell.cell_contents == getter(cell) == 42
                assert annotate(1)['x'] == 42
                del cell.cell_contents
                del annotation_cell.cell_contents
                assert getter(cell) is None
                for read, error in ((reader, NameError),
                                    (lambda: cell.cell_contents, ValueError),
                                    (lambda: annotate(1), NameError)):
                    try:
                        read()
                    except error:
                        pass
                    else:
                        results.put('empty cell accepted')
                        return
                results.put('ok')
            except BaseException as exc:
                results.put(str(exc))

        thread = threading.Thread(target=worker, args=((foreign,), getter, setter),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'ok')
        del foreign
        gc_collect()
        self.assertIsNone(reference())


if __name__ == '__main__':
    unittest.main()
