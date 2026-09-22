"""Ownership at cell mutation and comparison boundaries."""

import _thread
import sys
import threading
from types import CellType, FunctionType
import unittest
from weakref import ref

from test.support import SHORT_TIMEOUT, gc_collect
from test.support.import_helper import import_module


class CellMutationTests(unittest.TestCase):
    def run_native(self, work, *args):
        results = threading.Channel()
        def entry(work=work, args=args, results=results):
            try:
                result = work(*args)
            except BaseException as exc:
                trace = []
                tb = exc.__traceback__
                while tb is not None:
                    trace.append((tb.tb_frame.f_code.co_name, tb.tb_lineno))
                    tb = tb.tb_next
                results.put(('error', (str(exc), tuple(trace))))
            else:
                results.put(('ok', result))
        handle = _thread.start_joinable_thread(entry, group=threading.ThreadGroup())
        handle.join(SHORT_TIMEOUT)
        status, result = results.get()
        self.assertEqual(status, 'ok', result)
        return result

    def test_cell_setters(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        setter = capi.cell_mutate_from_tuple
        internal.object_declare_synchronized(setter)
        cell = CellType(42)
        def work(holder, setter):
            denied = 0
            for _ in range(100):
                for operation in ('assign', 'delete', 'c_assign', 'c_delete'):
                    try:
                        if operation == 'assign':
                            setter(holder, "attribute", 43)
                        elif operation == 'delete':
                            setter(holder, "attribute")
                        elif operation == 'c_assign':
                            setter(holder, "native", 43)
                        else:
                            setter(holder, "native")
                    except IllegalThreadAccessException:
                        denied += 1
            own = CellType(0)
            own.cell_contents = 41
            assert own.cell_contents == 41
            setter((own,), "native", 42)
            assert own.cell_contents == 42
            setter((own,), "native")
            try:
                own.cell_contents
            except ValueError:
                pass
            else:
                raise AssertionError('cell was not cleared')
            return denied
        self.assertEqual(self.run_native(work, (cell,), setter), 400)
        self.assertEqual(cell.cell_contents, 42)

    def test_deref_and_frame_writes(self):
        value = 42
        def write(new):
            nonlocal value
            yield
            value = new
        def delete():
            nonlocal value
            yield
            del value
        def frame_locals():
            yield sys._getframe().f_locals
            return value
        cell = write.__closure__[0]
        def work(holder, write_code, delete_code, frame_code):
            class Value:
                pass
            new = Value()
            reference = ref(new)
            denied = 0
            for _ in range(100):
                # Prepare active frames while debugger access is allowed.
                # The actual writes run after that exemption has ended.
                with sys.monitoring.StopTheWorld:
                    write = FunctionType(write_code, globals(), closure=holder)
                    delete = FunctionType(delete_code, globals(), closure=holder)
                    frame = FunctionType(frame_code, globals(), closure=holder)
                    writer = write(new)
                    deleter = delete()
                    gen = frame()
                    next(writer)
                    next(deleter)
                    proxy = next(gen)
                try:
                    for operation in ('write', 'delete', 'frame'):
                        try:
                            if operation == 'write':
                                next(writer)
                            elif operation == 'delete':
                                next(deleter)
                            else:
                                proxy['value'] = new
                        except IllegalThreadAccessException as exc:
                            tb = exc.__traceback__
                            while tb.tb_next is not None:
                                tb = tb.tb_next
                            expected = operation if operation != 'frame' else 'work'
                            assert tb.tb_frame.f_code.co_name == expected
                            denied += 1
                finally:
                    writer.close()
                    deleter.close()
                    gen.close()
            del new
            assert reference() is None
            own = CellType(0)
            local_write = FunctionType(write_code, {}, closure=(own,))
            local_delete = FunctionType(delete_code, {}, closure=(own,))
            assert list(local_write(43)) == [None]
            assert own.cell_contents == 43
            assert list(local_delete()) == [None]
            try:
                own.cell_contents
            except ValueError:
                pass
            else:
                raise AssertionError('cell was not deleted')
            return denied
        self.assertEqual(self.run_native(work, (cell,), write.__code__,
                                         delete.__code__, frame_locals.__code__), 300)
        self.assertEqual(cell.cell_contents, 42)

    def test_class_cells(self):
        cell = CellType(42)
        def work(holder):
            denied = 0
            for name in ('__classcell__', '__classdictcell__'):
                with sys.monitoring.StopTheWorld:
                    namespace = {name: holder[0]}
                try:
                    type('ForeignCell', (), namespace)
                except IllegalThreadAccessException:
                    denied += 1
                own = CellType()
                cls = type('OwnedCell', (), {name: own, 'marker': 42})
                if name == '__classcell__':
                    assert own.cell_contents is cls
                else:
                    assert own.cell_contents['marker'] == 42
            return denied
        self.assertEqual(self.run_native(work, (cell,)), 2)
        self.assertEqual(cell.cell_contents, 42)

    def test_comparison_checks_contents(self):
        calls = SynchronizedList()
        class Value:
            def __eq__(self, other):
                calls.append(True)
                return True
        foreign = Value()
        reference = ref(foreign)
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        setter = capi.cell_set_from_tuple
        internal.object_declare_synchronized(setter)
        def work(holder, setter):
            left = CellType()
            setter(left, holder)
            right = CellType(42)
            denied = 0
            for _ in range(100):
                for reverse in (False, True):
                    try:
                        if reverse:
                            right == left
                        else:
                            left == right
                    except IllegalThreadAccessException:
                        denied += 1
            left.cell_contents = 42
            assert left == right
            del left.cell_contents
            assert left < right
            del right.cell_contents
            assert left == right
            return denied
        self.assertEqual(self.run_native(work, (foreign,), setter), 200)
        self.assertEqual(list(calls), [])
        del foreign
        gc_collect()
        self.assertIsNone(reference())


if __name__ == '__main__':
    unittest.main()
