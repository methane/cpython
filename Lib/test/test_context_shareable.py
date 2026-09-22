"""Context sharing between PEP 805 thread groups."""

import _contextvars
import contextvars
import threading
import unittest

from _contextvars import Context, ContextVar, Token, copy_context
from test.support import threading_helper


threading_helper.requires_working_threading(module=True)


class ContextSharingTests(unittest.TestCase):
    def run_worker(self, worker, *args):
        results = threading.Channel()
        def entry(worker, args, results):
            try:
                worker(*args)
            except BaseException as exc:
                results.put(str(exc))
            else:
                results.put('ok')
        thread = threading.Thread(target=entry,
                                  args=(worker, args, results),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 'ok')

    def test_states(self):
        shared = threading.Shareable.SYNCHRONIZED
        immutable = threading.Shareable.IMMUTABLE
        self.assertIs(_contextvars.__shareable__, shared)
        self.assertIs(contextvars.__shareable__, shared)
        self.assertIs(copy_context.__shareable__, shared)
        self.assertIs(Context().__shareable__, shared)
        self.assertIs(ContextVar('v').__shareable__, immutable)
        self.assertIs(Token.MISSING.__shareable__, immutable)
        for cls in (Context, ContextVar, Token):
            self.assertIs(cls.__shareable__, immutable)
        ctx = Context()
        var = ContextVar('token')
        token = ctx.run(var.set, 1)
        self.assertIs(token.__shareable__, threading.Shareable.LOCAL)
        self.assertIs(token.old_value, Token.MISSING)

    def test_foreign_name_repr(self):
        calls = SynchronizedList()
        class Name(str):
            def __repr__(self):
                calls.append(True)
                return super().__repr__()
        var = ContextVar(Name('value'))
        def worker(var):
            try:
                repr(var)
            except IllegalThreadAccessException:
                pass
            else:
                raise AssertionError('foreign name accepted')
        self.run_worker(worker, var)
        self.assertEqual(list(calls), [])

    def test_concurrent_entry_rejected(self):
        ctx = Context()
        entered = threading.Event()
        release = threading.Event()
        def worker(ctx, entered, release):
            def hold():
                entered.set()
                assert release.wait(10)
            ctx.run(hold)
        thread = threading.Thread(target=worker, args=(ctx, entered, release),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaises(RuntimeError):
                    ctx.run(lambda: None)
                self.assertEqual(len(ctx.copy()), 0)
            finally:
                release.set()
        self.assertEqual(ctx.run(lambda: 42), 42)

    def test_worker_starts_child(self):
        def worker():
            results = threading.Channel()
            def child():
                results.put(42)
            for group in (None, threading.ThreadGroup()):
                thread = threading.Thread(target=child, group=group)
                thread.start()
                thread.join()
                assert results.get() == 42
        self.run_worker(worker)

    def test_foreign_values(self):
        var = ContextVar('value')
        foreign = []
        default_var = ContextVar('default', default=foreign)
        ctx = Context()
        ctx.run(var.set, foreign)
        other = Context()
        other.run(var.set, [])

        def worker(ctx, other, var, default_var):
            def entered():
                for read in (var.get, default_var.get,
                             lambda: ctx[var], lambda: ctx.get(var),
                             lambda: repr(default_var),
                             lambda: ctx == other):
                    for _ in range(100):
                        try:
                            read()
                        except IllegalThreadAccessException:
                            pass
                        else:
                            raise AssertionError('foreign value accepted')
                token = var.set(42)
                try:
                    token.old_value
                except IllegalThreadAccessException:
                    pass
                else:
                    raise AssertionError('foreign token value accepted')
                assert var.get() == ctx[var] == ctx.get(var) == 42
                assert default_var.get(43) == 43
                var.reset(token)
            ctx.run(entered)
        self.run_worker(worker, ctx, other, var, default_var)
        self.assertIs(ctx[var], foreign)

    def test_shared_context_enter(self):
        ctx = Context()
        var = ContextVar('value')
        ctx.run(var.set, 42)
        def worker(ctx, var):
            assert ctx[var] == 42
            assert ctx.run(var.get) == 42
            def entered():
                try:
                    ctx.run(var.get)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('context entered twice')
            ctx.run(entered)
        self.run_worker(worker, ctx, var)

    def test_parallel_context_snapshots(self):
        ctx = Context()
        var = ContextVar('counter')
        ctx.run(var.set, 0)
        ready = threading.Barrier(2)
        done = threading.Event()
        results = threading.Channel()

        def writer():
            def body():
                ready.wait()
                value = 0
                while not done.is_set():
                    var.set(value)
                    value += 1
            try:
                ctx.run(body)
            except BaseException as exc:
                results.put(str(exc))
            else:
                results.put('ok')

        def reader():
            try:
                ready.wait()
                for _ in range(200):
                    snapshot = ctx.copy()
                    assert snapshot[var] >= 0
                    assert len(snapshot) == 1
                    assert next(iter(snapshot)) is var
                    assert next(iter(snapshot.values())) >= 0
                    assert ctx.get(var) >= 0
            except BaseException as exc:
                results.put(str(exc))
            else:
                results.put('ok')
            finally:
                done.set()

        threads = [threading.Thread(target=target,
                                    group=threading.ThreadGroup())
                   for target in (writer, reader)]
        with threading_helper.start_threads(threads):
            pass
        self.assertEqual(results.get(), 'ok')
        self.assertEqual(results.get(), 'ok')


if __name__ == '__main__':
    unittest.main()
