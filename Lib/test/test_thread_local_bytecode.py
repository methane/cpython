"""Tests for thread-local bytecode."""
import textwrap
import unittest

from test import support
from test.support import cpython_only, import_helper, requires_specialization
from test.support.script_helper import assert_python_ok
from test.support.threading_helper import requires_working_threading

# Skip this test if the _testinternalcapi module isn't available
_testinternalcapi = import_helper.import_module("_testinternalcapi")


@cpython_only
@requires_working_threading()
class TLBCTests(unittest.TestCase):
    @requires_specialization
    def test_new_threads_start_with_unspecialized_code(self):
        code = textwrap.dedent("""
        import dis
        import queue
        import threading

        from _testinternalcapi import get_tlbc

        def all_opnames(bc):
            return {i.opname for i in dis._get_instructions_bytes(bc)}

        def f(a, b, q=None):
            if q is not None:
                q.put(get_tlbc(f))
            return a + b

        for _ in range(100):
            # specialize
            f(1, 2)

        q = queue.Queue()
        t = threading.Thread(target=f, args=('a', 'b', q))
        t.start()
        t.join()

        assert "BINARY_OP_ADD_INT" in all_opnames(get_tlbc(f))
        assert "BINARY_OP_ADD_INT" not in all_opnames(q.get())
        """)
        assert_python_ok("-X", "tlbc=1", "-c", code)

    @requires_specialization
    def test_threads_specialize_independently(self):
        code = textwrap.dedent("""
        import dis
        import queue
        import threading

        from _testinternalcapi import get_tlbc

        def all_opnames(bc):
            return {i.opname for i in dis._get_instructions_bytes(bc)}

        def f(a, b):
            return a + b

        def g(a, b, q=None):
            for _ in range(100):
                f(a, b)
            if q is not None:
                q.put(get_tlbc(f))

        # specialize in main thread
        g(1, 2)

        # specialize in other thread
        q = queue.Queue()
        t = threading.Thread(target=g, args=('a', 'b', q))
        t.start()
        t.join()

        assert "BINARY_OP_ADD_INT" in all_opnames(get_tlbc(f))
        t_opnames = all_opnames(q.get())
        assert "BINARY_OP_ADD_INT" not in t_opnames
        assert "BINARY_OP_ADD_UNICODE" in t_opnames
        """)
        assert_python_ok("-X", "tlbc=1", "-c", code)

    def test_reuse_tlbc_across_threads_different_lifetimes(self):
        code = textwrap.dedent("""
        import queue
        import threading

        from _testinternalcapi import get_tlbc_id

        def f(a, b, q=None):
            if q is not None:
                q.put(get_tlbc_id(f))
            return a + b

        q = queue.Queue()
        tlbc_ids = []
        for _ in range(3):
            t = threading.Thread(target=f, args=('a', 'b', q))
            t.start()
            t.join()
            tlbc_ids.append(q.get())

        assert tlbc_ids[0] == tlbc_ids[1]
        assert tlbc_ids[1] == tlbc_ids[2]
        """)
        assert_python_ok("-X", "tlbc=1", "-c", code)

    def test_growing_tlbc_array(self):
        code = textwrap.dedent("""
        import queue
        import threading

        from _testinternalcapi import get_tlbc_id

        count = 32
        barrier = threading.Barrier(count + 1)
        results = queue.Queue()
        errors = queue.Queue()

        def add(a, b):
            return a + b

        def worker():
            try:
                assert add(1, 2) == 3
                results.put(get_tlbc_id(add))
                # Keep all indices reserved until the table has grown.
                barrier.wait()
                assert add('a', 'b') == 'ab'
            except BaseException as exc:
                errors.put(repr(exc))
                barrier.abort()

        assert add(1, 2) == 3
        main_id = get_tlbc_id(add)
        threads = [threading.Thread(target=worker) for _ in range(count)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        assert errors.empty(), errors.get_nowait()
        ids = [results.get_nowait() for _ in threads]
        assert None not in ids
        assert len(set(ids)) == count
        assert main_id not in ids
        assert add(1, 2) == 3
        """)
        assert_python_ok("-X", "tlbc=1", "-c", code)

    def test_frames_outlive_thread(self):
        code = textwrap.dedent("""
        import gc
        import queue
        import sys
        import threading

        kind, freeze, inspect = sys.argv[1:]
        results = queue.Queue()

        class Awaitable:
            def __await__(self):
                yield 10
                return 20

        def generator():
            try:
                yield 10
            except ValueError:
                yield 20

        async def coroutine():
            return await Awaitable()

        async def async_generator():
            yield 10
            yield 20

        def retained_frame():
            return sys._getframe()

        def worker():
            if kind == 'generator':
                value = generator()
                assert next(value) == 10
            elif kind == 'coroutine':
                value = coroutine()
                assert value.send(None) == 10
            elif kind == 'async_generator':
                value = async_generator()
                try:
                    value.__anext__().send(None)
                except StopIteration as exc:
                    assert exc.value == 10
                else:
                    raise AssertionError('async generator did not yield')
            else:
                value = retained_frame()
            results.put(value)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        value = results.get_nowait()
        if inspect == '1':
            if kind == 'generator':
                frame = value.gi_frame
            elif kind == 'coroutine':
                frame = value.cr_frame
            elif kind == 'async_generator':
                frame = value.ag_frame
            else:
                frame = value
            lasti, lineno = frame.f_lasti, frame.f_lineno
            assert 0 <= lasti < len(frame.f_code.co_code)
        if freeze == '1':
            gc.freeze()
        sys._clear_internal_caches()
        if inspect == '1':
            assert frame.f_lasti == lasti, (frame.f_lasti, lasti)
            assert frame.f_lineno == lineno, (frame.f_lineno, lineno)

        if kind == 'generator':
            assert value.throw(ValueError) == 20
            value.close()
        elif kind == 'coroutine':
            try:
                value.send(None)
            except StopIteration as exc:
                assert exc.value == 20
            else:
                raise AssertionError('coroutine did not return')
        elif kind == 'async_generator':
            try:
                value.__anext__().send(None)
            except StopIteration as exc:
                assert exc.value == 20
            else:
                raise AssertionError('async generator did not yield')
            try:
                value.aclose().send(None)
            except StopIteration:
                pass
        gc.unfreeze()
        """)
        for kind in ('generator', 'coroutine', 'async_generator', 'frame'):
            for freeze in ('0', '1'):
                for inspect in (('1',) if kind == 'frame' else ('0', '1')):
                    with self.subTest(kind=kind, freeze=freeze, inspect=inspect):
                        assert_python_ok("-X", "tlbc=1", "-c", code,
                                         kind, freeze, inspect)

    def test_no_copies_if_tlbc_disabled(self):
        code = textwrap.dedent("""
        import queue
        import threading

        from _testinternalcapi import get_tlbc_id

        def f(a, b, q=None):
            if q is not None:
                q.put(get_tlbc_id(f))
            return a + b

        q = queue.Queue()
        threads = []
        for _ in range(3):
            t = threading.Thread(target=f, args=('a', 'b', q))
            t.start()
            threads.append(t)

        tlbc_ids = []
        for t in threads:
            t.join()
            tlbc_ids.append(q.get())

        main_tlbc_id = get_tlbc_id(f)
        assert main_tlbc_id is not None
        assert tlbc_ids[0] == main_tlbc_id
        assert tlbc_ids[1] == main_tlbc_id
        assert tlbc_ids[2] == main_tlbc_id
        """)
        assert_python_ok("-X", "tlbc=0", "-c", code)

    def test_no_specialization_if_tlbc_disabled(self):
        code = textwrap.dedent("""
        import dis
        import queue
        import threading

        from _testinternalcapi import get_tlbc

        def all_opnames(f):
            bc = get_tlbc(f)
            return {i.opname for i in dis._get_instructions_bytes(bc)}

        def f(a, b):
            return a + b

        for _ in range(100):
            f(1, 2)

        assert "BINARY_OP_ADD_INT" not in all_opnames(f)
        assert "RESUME_CHECK" not in all_opnames(f)
        """)
        assert_python_ok("-X", "tlbc=0", "-c", code)

    def test_audit_hook_if_tlbc_disabled(self):
        code = textwrap.dedent("""
        import sys

        events = []
        def hook(event, args):
            if event == 'test.tlbc':
                events.append(args)

        sys.addaudithook(hook)
        for i in range(10):
            sys.audit('test.tlbc', i)
        assert events == [(i,) for i in range(10)]
        """)
        assert_python_ok("-X", "tlbc=0", "-c", code)

    def test_specialization_requirement_respects_tlbc(self):
        code = textwrap.dedent("""
        import _opcode
        import sys
        from test.support import requires_specialization

        @requires_specialization
        def test():
            pass

        enabled = _opcode.ENABLE_SPECIALIZATION and int(sys.argv[1])
        assert getattr(test, '__unittest_skip__', False) == (not enabled)
        """)
        for enabled in ('0', '1'):
            with self.subTest(enabled=enabled):
                assert_python_ok("-X", f"tlbc={enabled}", "-c", code, enabled)

    def test_monitoring_if_tlbc_disabled(self):
        code = textwrap.dedent("""
        import dis
        import sys
        from _testinternalcapi import get_tlbc

        def f(a, b):
            c = a + b
            return abs(c)

        calls = []
        mode = sys.argv[1]
        def callback(*args):
            calls.append(None)
            return callback

        if mode in ('trace', 'profile'):
            setter = sys.settrace if mode == 'trace' else sys.setprofile
            setter(callback)
        else:
            monitoring = sys.monitoring
            tool = monitoring.PROFILER_ID
            monitoring.use_tool_id(tool, 'test tlbc')
            event = getattr(monitoring.events, mode)
            def monitor(*args):
                calls.append(None)
                if sys.argv[2] == 'disable':
                    return monitoring.DISABLE
            monitoring.register_callback(tool, event, monitor)
            monitoring.set_local_events(tool, f.__code__, event)

        for _ in range(100):
            assert f(1, 2) == 3
        assert calls
        if mode in ('trace', 'profile'):
            setter(None)
        else:
            monitoring.set_local_events(tool, f.__code__, 0)
            monitoring.free_tool_id(tool)
        for _ in range(100):
            assert f(1, 2) == 3
        opnames = {i.opname for i in
                   dis._get_instructions_bytes(get_tlbc(f))}
        assert not opnames.intersection(dis._specialized_opmap), opnames
        """)
        for mode in ('trace', 'profile', 'PY_START', 'LINE', 'INSTRUCTION', 'CALL'):
            actions = (('keep',) if mode in ('trace', 'profile')
                       else ('keep', 'disable'))
            for action in actions:
                with self.subTest(mode=mode, action=action):
                    assert_python_ok("-X", "tlbc=0", "-c", code, mode, action)

    def test_generator_throw(self):
        code = textwrap.dedent("""
        import queue
        import threading

        from _testinternalcapi import get_tlbc_id

        def g():
            try:
                yield
            except:
                yield get_tlbc_id(g)

        def f(q):
            gen = g()
            next(gen)
            q.put(gen.throw(ValueError))

        q = queue.Queue()
        t = threading.Thread(target=f, args=(q,))
        t.start()
        t.join()

        gen = g()
        next(gen)
        main_id = gen.throw(ValueError)
        assert main_id != q.get()
        """)
        assert_python_ok("-X", "tlbc=1", "-c", code)


if __name__ == "__main__":
    unittest.main()
