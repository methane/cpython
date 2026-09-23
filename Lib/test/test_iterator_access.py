"""Access validation at iterator C API boundaries."""

import dis
import sys
import threading
import types
from types import FunctionType
import unittest
import weakref

from test.support import gc_collect, requires_specialization, threading_helper
from test.support.import_helper import import_module


class IteratorAccessTests(unittest.TestCase):
    @threading_helper.requires_working_threading()
    def test_anext_foreign_references(self):
        class Awaitable:
            calls = 0
            def __await__(self):
                self.calls += 1
                return iter(())
        class ForeignIterator:
            calls = 0
            def __anext__(self):
                self.calls += 1
                raise AssertionError('foreign iterator was advanced')
        foreign = Awaitable()
        foreign_iterator = ForeignIterator()
        reference = weakref.ref(foreign)
        results = threading.Channel()

        invoke = import_module('_testcapi').pyobject_vectorcall
        import_module('_testinternalcapi').object_declare_synchronized(invoke)

        def worker(payload):
            class Iterator:
                def __anext__(self):
                    return self.value
            class Empty:
                async def __anext__(self):
                    raise StopAsyncIteration
            iterator = Iterator()
            with sys.monitoring.StopTheWorld:
                iterator.value = payload[0]
                arguments = ((iterator,), (iterator, 42),
                             (payload[1],), (payload[1], 42))
            denied = 0
            for _ in range(100):
                for case in range(4):
                    try:
                        # anext is implemented in Python. Enter through C
                        # so foreign receiver arguments reach its body.
                        invoke(anext, arguments[case], None)
                    except IllegalThreadAccessException:
                        denied += 1
                with sys.monitoring.StopTheWorld:
                    awaitable = anext(Empty(), payload[0])
                try:
                    awaitable.send(None)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)

        thread = threading.Thread(target=worker,
                                  args=((foreign, foreign_iterator),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual(results.get(), 500)
        self.assertEqual(foreign.calls, 0)
        self.assertEqual(foreign_iterator.calls, 0)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_anext_in_worker(self):
        results = threading.Channel()
        def worker():
            class Iterator:
                async def __anext__(self):
                    return 42
            class Empty:
                async def __anext__(self):
                    raise StopAsyncIteration
            for awaitable in (anext(Iterator()), anext(Iterator(), 43),
                              anext(Empty(), 44)):
                try:
                    awaitable.send(None)
                except StopIteration as exc:
                    results.put(exc.value)
        thread = threading.Thread(target=worker, group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get() for _ in range(3)], [42, 42, 44])

    def test_await_access_errors(self):
        for error in (IllegalThreadAccessException, UnprotectedAccessException, ValueError):
            with self.subTest(error=error):
                class Awaitable:
                    def __await__(self):
                        raise error('blocked')
                class AsyncIterator:
                    def __aiter__(self):
                        return self
                    def __anext__(self):
                        return Awaitable()
                async def consume():
                    async for value in AsyncIterator():
                        pass
                coro = consume()
                if error is ValueError:
                    with self.assertRaises(TypeError) as caught:
                        coro.send(None)
                    self.assertIsInstance(caught.exception.__cause__, ValueError)
                else:
                    with self.assertRaisesRegex(error, 'blocked') as caught:
                        coro.send(None)
                    self.assertIsNone(caught.exception.__cause__)

    @threading_helper.requires_working_threading()
    def test_await_iterator_access(self):
        @freeze
        class Iterator:
            calls = 0
            def __iter__(self):
                return self
            def __next__(self):
                self.calls += 1
                raise StopIteration(42)
        @freeze
        class Awaitable:
            calls = 0
            def __init__(self, iterator):
                self.iterator = iterator
            def __await__(self):
                self.calls += 1
                return self.iterator
        @freeze
        class AsyncIterator:
            def __init__(self, awaitable):
                self.awaitable = awaitable
            def __aiter__(self):
                return self
            def __anext__(self):
                return self.awaitable
        async def consume(awaitable):
            try:
                return await awaitable
            except IllegalThreadAccessException:
                return 'denied'
        async def loop(iterator):
            try:
                async for value in iterator:
                    return value
            except IllegalThreadAccessException:
                return 'denied'
        def finish(coro):
            try:
                coro.send(None)
            except StopIteration as exc:
                return exc.value
            raise AssertionError('unexpected suspension')

        foreign = Iterator()
        foreign_awaitable = Awaitable(foreign)
        iterator_ref = weakref.ref(foreign)
        awaitable_ref = weakref.ref(foreign_awaitable)
        results = threading.Channel()
        def worker(payload):
            for _ in range(100):
                local = Iterator()
                assert finish(consume(Awaitable(local))) == 42
                assert local.calls == 1
                assert finish(loop(AsyncIterator(Awaitable(Iterator())))) == 42
                with sys.monitoring.StopTheWorld:
                    coroutines = (
                        consume(Awaitable(payload[0])),
                        consume(payload[1]),
                        loop(AsyncIterator(Awaitable(payload[0]))),
                        loop(AsyncIterator(payload[1])),
                    )
                for coro in coroutines:
                    assert finish(coro) == 'denied'
            results.put(True)
        thread = threading.Thread(target=worker, args=((foreign, foreign_awaitable),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertEqual(foreign.calls, 0)
        self.assertEqual(foreign_awaitable.calls, 0)
        del foreign_awaitable, foreign
        gc_collect()
        self.assertIsNone(iterator_ref())
        self.assertIsNone(awaitable_ref())

    @threading_helper.requires_working_threading()
    def test_await_coroutine_access(self):
        async def native():
            return 42
        @types.coroutine
        def legacy():
            if False:
                yield
            return 42
        @freeze
        class Manager:
            def __init__(self, entry, exit):
                self.entry = entry
                self.exit = exit
            def __aenter__(self):
                return self.entry
            def __aexit__(self, *exc):
                return self.exit
        async def consume(value, mode):
            try:
                if mode == 'await':
                    return await value
                async with value:
                    return 42
            except IllegalThreadAccessException:
                return 'denied'
        def worker(payload, mode, results):
            with sys.monitoring.StopTheWorld:
                if mode == 'await':
                    value = payload[0]
                elif mode == 'enter':
                    value = Manager(payload[0], legacy())
                else:
                    value = Manager(legacy(), payload[0])
                coro = consume(value, mode)
            try:
                coro.send(None)
            except StopIteration as exc:
                results.put(exc.value)

        for factory in (native, legacy):
            for mode in ('await', 'enter', 'exit'):
                with self.subTest(factory=factory, mode=mode):
                    foreign = factory()
                    results = threading.Channel()
                    try:
                        thread = threading.Thread(target=worker,
                                                  args=((foreign,), mode, results),
                                                  group=threading.ThreadGroup())
                        with threading_helper.start_threads([thread]):
                            pass
                        self.assertEqual(results.get(), 'denied')
                        frame = foreign.cr_frame if factory is native else foreign.gi_frame
                        self.assertIsNotNone(frame)
                    finally:
                        foreign.close()

    @threading_helper.requires_working_threading()
    def test_get_iterator_access(self):
        self.check_get_iterator_access(iter, aiter)

    @threading_helper.requires_working_threading()
    def test_capi_get_iterator_access(self):
        capi = import_module('_testcapi')
        self.check_get_iterator_access(capi.PyObject_GetIter, capi.PyObject_GetAIter,
                                       native=True)

    def check_get_iterator_access(self, getiter, getaiter, *, native=False):
        internal = import_module('_testinternalcapi')
        internal.object_declare_synchronized(getiter)
        internal.object_declare_synchronized(getaiter)
        invoke = import_module('_testcapi').call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)
        @freeze
        class Iterator:
            def __iter__(self):
                return self
            def __next__(self):
                raise AssertionError('foreign iterator was advanced')
            def __aiter__(self):
                return self
            def __anext__(self):
                raise AssertionError('foreign async iterator was advanced')

        foreign = Iterator()
        reference = weakref.ref(foreign)
        @freeze
        class Factory:
            def __init__(self, value):
                self.value = value
            def __iter__(self):
                return self.value
            def __aiter__(self):
                return self.value

        self.assertIs(getiter(Factory(foreign)), foreign)
        self.assertIs(getaiter(Factory(foreign)), foreign)
        results = threading.Channel()
        def worker(payload):
            with sys.monitoring.StopTheWorld:
                carrier = Factory(payload[0])
            for index in range(2):
                getter = getaiter if index else getiter
                local = Iterator()
                assert getter(local) is local
                for _ in range(100):
                    try:
                        if native:
                            # Wrap the result in C, avoiding a VM result
                            # check that could hide a missing API check.
                            invoke(getter, (carrier,))
                        else:
                            getter(carrier)
                    except IllegalThreadAccessException:
                        pass
                    else:
                        results.put(False)
                        return
            results.put(True)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(reference(), foreign)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_loop_get_iterator_access(self):
        @freeze
        class Iterator:
            def __next__(self):
                raise AssertionError('foreign iterator was advanced')
            def __anext__(self):
                raise AssertionError('foreign async iterator was advanced')
        foreign = Iterator()
        @freeze
        class Factory:
            def __init__(self, value):
                self.value = value
            def __iter__(self):
                return self.value
            def __aiter__(self):
                return self.value
        results = threading.Channel()
        def consume(factory):
            try:
                for value in factory:
                    pass
            except IllegalThreadAccessException:
                return True
            return False
        async def aconsume(factory):
            try:
                async for value in factory:
                    pass
            except IllegalThreadAccessException:
                return True
            return False
        def worker(payload):
            with sys.monitoring.StopTheWorld:
                carrier = Factory(payload[0])
            results.put(consume(carrier))
            coro = aconsume(carrier)
            try:
                coro.send(None)
            except StopIteration as exc:
                results.put(exc.value)
        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertTrue(results.get())

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_inlined_generator_yield_access(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)

        def producer(value):
            # A debugger-created foreign local is rejected when loaded,
            # before the generator can suspend at the yield instruction.
            yield value
            yield 42

        def loop(gen):
            try:
                for value in gen:
                    pass
            except IllegalThreadAccessException:
                return 'denied'
            return 42

        def delegate(gen):
            try:
                yield from gen
            except IllegalThreadAccessException:
                yield 'denied'

        def worker(payload, mode, results):
            template = loop if mode == 'loop' else delegate
            consume = FunctionType(template.__code__.replace(), {})
            def run(gen):
                if mode == 'loop':
                    return consume(gen)
                values = list(consume(gen))
                return values[-1]
            for _ in range(100):
                assert run(producer(42)) == 42
            bytecode = (get_tlbc(consume) if get_tlbc is not None
                        else consume.__code__._co_code_adaptive)
            results.put(bytecode)
            for _ in range(100):
                with sys.monitoring.StopTheWorld:
                    gen = producer(payload[0])
                assert run(gen) == 'denied'
                assert gen.gi_frame is None
                assert next(gen, None) is None
            results.put(run(producer(42)) == 42)

        for mode in ('loop', 'delegate'):
            with self.subTest(mode=mode):
                results = threading.Channel()
                thread = threading.Thread(
                    target=worker, args=((foreign,), mode, results),
                    group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
                name = 'FOR_ITER_GEN' if mode == 'loop' else 'SEND_GEN'
                self.assertIn(dis._all_opmap[name],
                              [op for _, _, op, _ in dis._unpack_opargs(results.get())])
                self.assertTrue(results.get())
        self.assertIs(reference(), foreign)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_inlined_generator_return_access(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)
        results = threading.Channel()

        def producer(value):
            if False:
                yield
            return value

        def template(gen):
            try:
                value = yield from gen
            except IllegalThreadAccessException:
                yield 'denied'
            else:
                yield value

        delegate = FunctionType(template.__code__.replace(), SynchronizedDict())
        def worker(payload):
            for _ in range(100):
                assert list(delegate(producer(42))) == [42]
            bytecode = (get_tlbc(delegate)
                        if get_tlbc is not None
                        else delegate.__code__._co_code_adaptive)
            results.put(bytecode)
            for _ in range(100):
                with sys.monitoring.StopTheWorld:
                    gen = producer(payload[0])
                assert list(delegate(gen)) == ['denied']
                assert gen.gi_frame is None
            results.put(list(delegate(producer(42))) == [42])

        def monitored_worker(payload):
            with sys.monitoring.StopTheWorld:
                gen = producer(payload[0])
            assert list(delegate(producer(42))) == [42]
            assert list(delegate(gen)) == ['denied']
            results.put(True)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertIn(dis._all_opmap['SEND_GEN'],
                      [op for _, _, op, _ in dis._unpack_opargs(results.get())])
        self.assertTrue(results.get())
        seen = SynchronizedList()
        events = SynchronizedList()
        def on_stop(code, offset, exception):
            # Record entry before reading the value: a rejected value read
            # must not hide delivery of an invalid event.
            events.append(True)
            seen.append(exception.value)
        monitoring = sys.monitoring
        tool = 2
        monitoring.use_tool_id(tool, 'generator return access test')
        try:
            monitoring.register_callback(tool, monitoring.events.STOP_ITERATION,
                                         on_stop)
            monitoring.set_local_events(tool, delegate.__code__,
                                        monitoring.events.STOP_ITERATION)
            thread = threading.Thread(target=monitored_worker, args=((foreign,),),
                                      group=threading.ThreadGroup())
            with threading_helper.start_threads([thread]):
                pass
            self.assertTrue(results.get())
            self.assertEqual(len(events), 1,
                             'monitor received an inaccessible return event')
            self.assertEqual(list(seen), [42])
        finally:
            monitoring.set_local_events(tool, delegate.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.STOP_ITERATION, None)
            monitoring.free_tool_id(tool)
        self.assertIs(reference(), foreign)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_inlined_for_return_access(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)
        results = threading.Channel()

        def producer(value):
            if False:
                yield
            return value

        def template(gen):
            try:
                for value in gen:
                    pass
            except IllegalThreadAccessException:
                return 'denied'
            else:
                return 42

        consume = FunctionType(template.__code__.replace(), SynchronizedDict())
        self.assertEqual(consume(producer(foreign)), 42)
        def worker(payload):
            for _ in range(100):
                assert consume(producer(42)) == 42
            bytecode = (get_tlbc(consume)
                        if get_tlbc is not None
                        else consume.__code__._co_code_adaptive)
            results.put(bytecode)
            for _ in range(100):
                with sys.monitoring.StopTheWorld:
                    gen = producer(payload[0])
                assert consume(gen) == 'denied'
                assert gen.gi_frame is None
            results.put(consume(producer(42)) == 42)

        def monitored_worker(payload):
            with sys.monitoring.StopTheWorld:
                gen = producer(payload[0])
            assert consume(producer(42)) == 42
            assert consume(gen) == 'denied'
            results.put(True)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertIn(dis._all_opmap['FOR_ITER_GEN'],
                      [op for _, _, op, _ in dis._unpack_opargs(results.get())])
        self.assertTrue(results.get())
        seen = SynchronizedList()
        events = SynchronizedList()
        def on_stop(code, offset, exception):
            # Record entry before reading the value: a rejected value read
            # must not hide delivery of an invalid event.
            events.append(True)
            seen.append(exception.value)
        monitoring = sys.monitoring
        tool = 2
        monitoring.use_tool_id(tool, 'generator return access test')
        try:
            monitoring.register_callback(tool, monitoring.events.STOP_ITERATION,
                                         on_stop)
            monitoring.set_local_events(tool, consume.__code__,
                                        monitoring.events.STOP_ITERATION)
            thread = threading.Thread(target=monitored_worker, args=((foreign,),),
                                      group=threading.ThreadGroup())
            with threading_helper.start_threads([thread]):
                pass
            self.assertTrue(results.get())
            self.assertEqual(len(events), 1,
                             'monitor received an inaccessible return event')
            self.assertEqual(list(seen), [42])
        finally:
            monitoring.set_local_events(tool, consume.__code__, 0)
            monitoring.register_callback(tool, monitoring.events.STOP_ITERATION, None)
            monitoring.free_tool_id(tool)
        self.assertIs(reference(), foreign)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_inlined_coroutine_return_access(self):
        foreign = []
        results = threading.Channel()
        async def producer(value):
            return value
        async def delegate(coro):
            try:
                return await coro
            except IllegalThreadAccessException:
                return 'denied'

        def worker(payload):
            for index in range(2):
                expected = 'denied' if index else 42
                with sys.monitoring.StopTheWorld:
                    coro = producer(payload[0] if index else 42)
                try:
                    delegate(coro).send(None)
                except StopIteration as exc:
                    results.put(exc.value == expected and coro.cr_frame is None)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get(), results.get()], [True, True])

    @threading_helper.requires_working_threading()
    def test_generator_method_results(self):
        class Payload:
            pass
        foreign = Payload()
        reference = weakref.ref(foreign)
        results = threading.Channel()

        def producer(mode, foreign):
            if mode == 'return':
                return foreign
            try:
                if mode == 'yield':
                    yield foreign
                else:
                    yield 0
            except ValueError:
                if mode == 'throw-return':
                    return foreign
                yield foreign
            except GeneratorExit:
                return foreign
            yield 42

        def worker(payload):
            for mode, method in (('yield', 'send'), ('yield', '__next__'),
                                 ('return', 'send'), ('return', '__next__'),
                                 ('throw-yield', 'throw'), ('throw-return', 'throw'),
                                 ('close', 'close')):
                with sys.monitoring.StopTheWorld:
                    gen = producer(mode, payload[0])
                if mode not in ('yield', 'return'):
                    assert next(gen) == 0
                try:
                    if method == 'send':
                        gen.send(None)
                    elif method == '__next__':
                        gen.__next__()
                    elif method == 'throw':
                        gen.throw(ValueError())
                    else:
                        gen.close()
                except IllegalThreadAccessException:
                    results.put(True)
                except StopIteration:
                    results.put(False)
                else:
                    results.put(False)
                # The foreign local load fails inside the producer in every
                # mode, so it must unwind rather than suspend at yield.
                results.put(gen.gi_frame is None)
                assert next(gen, None) is None

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get() for _ in range(14)], [True] * 14)
        self.assertIs(reference(), foreign)
        del foreign
        gc_collect()
        self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_async_generator_unwrapped_result(self):
        foreign = []
        results = threading.Channel()
        async def producer(foreign):
            yield foreign
            yield 42

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                gen = producer(payload[0])
            try:
                gen.__anext__().send(None)
            except IllegalThreadAccessException:
                results.put(True)
            except StopIteration:
                results.put(False)
            else:
                results.put(False)
            try:
                gen.__anext__().send(None)
            except StopAsyncIteration:
                results.put(gen.ag_frame is None)
            else:
                results.put(False)
            try:
                gen.aclose().send(None)
            except StopIteration:
                pass

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get(), results.get()], [True, True])

    @threading_helper.requires_working_threading()
    def test_coroutine_return_access(self):
        foreign = []
        results = threading.Channel()
        async def coroutine(foreign):
            return foreign

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                coro = coroutine(payload[0])
            try:
                coro.send(None)
            except IllegalThreadAccessException:
                results.put(True)
            except StopIteration:
                results.put(False)
            else:
                results.put(False)
            results.put(coro.cr_frame is None)

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get(), results.get()], [True, True])

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_specialized_yield_from_access(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        class Payload:
            pass

        def worker(payload, factory, results):
            def template(items):
                try:
                    yield from items
                except IllegalThreadAccessException:
                    yield 'denied'
            delegate = FunctionType(template.__code__.replace(), {})
            for _ in range(100):
                assert list(delegate(factory([42]))) == [42]
            bytecode = (get_tlbc(delegate) if get_tlbc is not None
                        else delegate.__code__._co_code_adaptive)
            results.put(bytecode)
            for _ in range(100):
                with sys.monitoring.StopTheWorld:
                    items = factory([payload[0]])
                # Catch inside the delegate: SEND must reject the item
                # before the outer consumer receives it.
                assert list(delegate(items)) == ['denied']
            results.put(list(delegate(factory([42]))) == [42])

        for factory in (list, tuple):
            with self.subTest(factory=factory):
                value = Payload()
                reference = weakref.ref(value)
                results = threading.Channel()
                thread = threading.Thread(
                    target=worker, args=((value,), factory, results),
                    group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
                self.assertIn(dis._all_opmap['SEND_VIRTUAL'],
                              [op for _, _, op, _ in dis._unpack_opargs(results.get())])
                self.assertTrue(results.get())
                self.assertIs(reference(), value)
                del value
                gc_collect()
                self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_foreign_default(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class Payload:
            pass

        value = Payload()
        reference = weakref.ref(value)
        results = threading.Channel()

        def worker(payload):
            with sys.monitoring.StopTheWorld:
                args = (iter(()), payload[0])
            try:
                invoke(next, args)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)

        thread = threading.Thread(target=worker, args=((value,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertTrue(results.get())
        self.assertIs(reference(), value)
        del value
        gc_collect()
        self.assertIsNone(reference())

    @requires_specialization
    @threading_helper.requires_working_threading()
    def test_for_loop_foreign_results(self):
        internal = import_module('_testinternalcapi')
        get_tlbc = getattr(internal, 'get_tlbc', None)
        if get_tlbc is not None:
            internal.object_declare_synchronized(get_tlbc)
        class Payload:
            pass

        cases = (
            (lambda value: [value], 'FOR_ITER_LIST'),
            (lambda value: (value,), 'FOR_ITER_TUPLE'),
            (lambda value: SynchronizedList([value]), None),
            (lambda value: iter([value]), None),
            (lambda value: iter((value,)), None),
            (lambda value: dict(value=value).values(), None),
            (lambda value: {value}, None),
        )
        def worker(payload, factory, opname, results):
            def template(iterable):
                # Discard acquired items: the outer return check must not
                # mask a missing FOR_ITER acquisition check.
                for value in iterable:
                    pass
                return 42
            # Fresh counters for each case, including the cold read.
            read = FunctionType(template.__code__.replace(), {})
            with sys.monitoring.StopTheWorld:
                container = factory(payload[0])
            try:
                read(container)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
            for _ in range(100):
                assert read(factory(42)) == 42
            if opname is not None:
                bytecode = (get_tlbc(read) if get_tlbc is not None
                            else read.__code__._co_code_adaptive)
                results.put(bytecode)
            else:
                results.put(True)
            denied = 0
            for _ in range(100):
                with sys.monitoring.StopTheWorld:
                    container = factory(payload[0])
                try:
                    read(container)
                except IllegalThreadAccessException:
                    denied += 1
            results.put(denied)
            results.put(read(factory(42)))

        for factory, opname in cases:
            with self.subTest(factory=factory, opname=opname):
                value = Payload()
                reference = weakref.ref(value)
                results = threading.Channel()
                thread = threading.Thread(
                    target=worker, args=((value,), factory, opname, results),
                    group=threading.ThreadGroup())
                with threading_helper.start_threads([thread]):
                    pass
                self.assertTrue(results.get(), 'unspecialized loop allowed access')
                if opname is not None:
                    self.assertIn(dis._all_opmap[opname],
                                  [op for _, _, op, _ in dis._unpack_opargs(results.get())])
                else:
                    self.assertTrue(results.get())
                self.assertEqual(results.get(), 100)
                self.assertEqual(results.get(), 42)
                self.assertIs(reference(), value)
                del value
                gc_collect()
                self.assertIsNone(reference())

    @threading_helper.requires_working_threading()
    def test_send_foreign_results(self):
        send = import_module('_testcapi').PyIter_Send
        import_module('_testinternalcapi').object_declare_synchronized(send)
        class Payload:
            pass

        def generator(value, returns):
            if not returns:
                yield value
            return value

        @freeze
        class Fallback:
            def __init__(self, value, returns):
                self.value = value
                self.returns = returns
            def __iter__(self):
                return self
            def __next__(self):
                return self.send(None)
            def send(self, arg):
                if self.returns:
                    raise StopIteration(self.value)
                return self.value

        def worker(payload, factory, returns, arg, results):
            with sys.monitoring.StopTheWorld:
                iterator = factory(payload[0], returns)
            try:
                # The C wrapper returns (status, result); a VM result check
                # cannot inspect and reject the nested result on its behalf.
                send(iterator, arg)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
            results.put(send(factory(42, returns), arg))

        for factory, arg in ((generator, None), (Fallback, None), (Fallback, 42)):
            for returns in (False, True):
                with self.subTest(factory=factory, arg=arg, returns=returns):
                    value = Payload()
                    reference = weakref.ref(value)
                    status, result = send(factory(value, returns), arg)
                    self.assertEqual(status, 0 if returns else 1)
                    self.assertIs(result, value)
                    del result
                    results = threading.Channel()

                    thread = threading.Thread(
                        target=worker,
                        args=((value,), factory, returns, arg, results),
                        group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    self.assertTrue(results.get())
                    self.assertEqual(results.get(), (0 if returns else 1, 42))
                    self.assertIs(reference(), value)
                    del value
                    gc_collect()
                    self.assertIsNone(reference())

    def test_send_errors_and_exhaustion(self):
        send = import_module('_testcapi').PyIter_Send
        class Broken:
            def send(self, arg):
                raise ValueError('send failed')

        with self.assertRaisesRegex(ValueError, '^send failed$'):
            send(Broken(), 42)
        self.assertEqual(send(iter(()), None), (0, None))
        self.assertEqual(send(iter([42]), None), (1, 42))

    @threading_helper.requires_working_threading()
    def test_yield_from_fallback_checks_results(self):
        foreign = []
        results = threading.Channel()

        @freeze
        class Fallback:
            def __init__(self, returns, value):
                self.value = value
                self.returns = returns
            def __iter__(self):
                return self
            def __next__(self):
                if self.returns:
                    raise StopIteration(self.value)
                return self.value

        def delegate(iterator):
            try:
                yield from iterator
            except IllegalThreadAccessException:
                yield 42
            else:
                raise AssertionError('inaccessible result reached delegate')

        def worker(payload):
            for returns in (False, True):
                # The delegate must see the error at SEND, before the outer
                # next() can inspect a yielded item or a returned value.
                with sys.monitoring.StopTheWorld:
                    iterator = Fallback(returns, payload[0])
                results.put(next(delegate(iterator)))

        thread = threading.Thread(target=worker, args=((foreign,),),
                                  group=threading.ThreadGroup())
        with threading_helper.start_threads([thread]):
            pass
        self.assertEqual([results.get(), results.get()], [42, 42])

    @threading_helper.requires_working_threading()
    def test_foreign_results(self):
        capi = import_module('_testcapi')
        internal = import_module('_testinternalcapi')
        internal.object_declare_synchronized(capi.PyIter_Next)
        internal.object_declare_synchronized(capi.PyIter_NextItem)

        invoke = capi.call_cfunction_raw_return_in_tuple
        internal.object_declare_synchronized(invoke)

        class Payload:
            pass

        @freeze
        class PythonIterator:
            def __init__(self, value):
                self.value = value
                self.index = 0
            def __iter__(self):
                return self
            def __next__(self):
                self.index += 1
                if self.index == 1:
                    return self.value
                if self.index == 2:
                    return 42
                raise StopIteration

        def generator(value):
            yield value
            yield 42

        def next_without_default(iterator):
            try:
                return next(iterator)
            except StopIteration:
                return None

        factories = (
            lambda value: iter([value, 42]),
            lambda value: iter((value, 42)),
            lambda value: iter(dict(a=value, b=42).values()),
            generator,
            PythonIterator,
        )
        def worker(payload, getter, factory, native, results):
            with sys.monitoring.StopTheWorld:
                iterator = factory(payload[0])
            try:
                if native:
                    invoke(getter, (iterator,))
                else:
                    getter(iterator)
            except IllegalThreadAccessException:
                results.put(True)
            else:
                results.put(False)
            results.put(getter(iterator))
            results.put(getter(iterator) is None)

        for getter in (capi.PyIter_Next, capi.PyIter_NextItem,
                       next_without_default, lambda it: next(it, None)):
            for factory in factories:
                with self.subTest(getter=getter, factory=factory):
                    value = Payload()
                    reference = weakref.ref(value)
                    results = threading.Channel()

                    thread = threading.Thread(
                        target=worker,
                        args=((value,), getter, factory,
                              isinstance(getter, types.BuiltinFunctionType), results),
                        group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    self.assertTrue(results.get())
                    # A generator executes a checked local load and unwinds
                    # on failure. Native iterators reject the acquired element
                    # after advancing and can continue to their next element.
                    expected = None if factory is generator else 42
                    self.assertEqual(results.get(), expected)
                    self.assertTrue(results.get())
                    self.assertIs(reference(), value)
                    del value
                    gc_collect()
                    self.assertIsNone(reference())

    def test_errors_and_exhaustion(self):
        capi = import_module('_testcapi')
        class Broken:
            def __iter__(self):
                return self
            def __next__(self):
                raise ValueError('iterator failed')

        for getter in (capi.PyIter_Next, capi.PyIter_NextItem):
            with self.subTest(getter=getter):
                self.assertIsNone(getter(iter(())))
                with self.assertRaisesRegex(ValueError, '^iterator failed$'):
                    getter(Broken())
                value = []
                self.assertIs(getter(iter([value])), value)


if __name__ == '__main__':
    unittest.main()
