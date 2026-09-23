"""Access checks for locals which can outlive a with statement's protection."""

import dis
import sys
import textwrap
import threading
import unittest

from test import test_stop_the_world


class WithLocalAccessTests(unittest.TestCase):
    run_native = test_stop_the_world.StopTheWorldTests.run_native

    def make_work(self, body):
        namespace = {'sys': sys}
        exec('def work(shared):\n' + textwrap.indent(textwrap.dedent(body), '    '),
             namespace)
        return namespace['work']

    def assert_denied(self, body, *, opcode='LOAD_FAST_MAYBE_UNPROTECTED'):
        work = self.make_work(body)
        opcodes = {opcode}
        if opcode == 'LOAD_FAST_MAYBE_UNPROTECTED':
            opcodes.add('LOAD_FAST_BORROW_MAYBE_UNPROTECTED')
        checked = [i for i in dis.get_instructions(work) if i.opname in opcodes]
        self.assertTrue(checked)
        self.assertTrue(any(i.argval == 'value' for i in checked))
        self.assertRegex(dis.Bytecode(work).dis(),
                         rf"(?:{'|'.join(sorted(opcodes))})\s+\d+\s+\(value\)")
        value = []
        shared = SynchronizedDict(value=value)
        self.assertEqual(self.run_native(work, shared), 'denied')
        self.assertEqual(value, [42])

    def test_retained_local(self):
        self.assert_denied('''
            with sys.monitoring.StopTheWorld:
                value = shared['value']
                value.append(42)
            try:
                return value
            except IllegalThreadAccessException:
                return 'denied'
        ''')

    def test_nested_with(self):
        self.assert_denied('''
            with sys.monitoring.StopTheWorld:
                with sys.monitoring.StopTheWorld:
                    value = shared['value']
                value.append(42)
            try:
                return value
            except IllegalThreadAccessException:
                return 'denied'
        ''')

    def test_exception_exit(self):
        self.assert_denied('''
            try:
                with sys.monitoring.StopTheWorld:
                    value = shared['value']
                    value.append(42)
                    raise LookupError
            except LookupError:
                pass
            try:
                return value
            except IllegalThreadAccessException:
                return 'denied'
        ''')

    def test_loop_and_branch(self):
        self.assert_denied('''
            for attempt in range(2):
                if attempt:
                    with sys.monitoring.StopTheWorld:
                        value = shared['value']
                        value.append(42)
                    break
            try:
                return value
            except IllegalThreadAccessException:
                return 'denied'
        ''')

    def test_many_locals(self):
        padding = '\n'.join(f'local_{i} = {i}' for i in range(270))
        body = padding + '\n' + textwrap.dedent('''
            with sys.monitoring.StopTheWorld:
                value = shared['value']
                value.append(42)
            try:
                return value
            except IllegalThreadAccessException:
                return 'denied'
        ''')
        self.assert_denied(body)
        work = self.make_work(body)
        self.assertGreater(work.__code__.co_varnames.index('value'), 255)

    def test_comprehension_save(self):
        # The comprehension saves the previous value before shadowing it.
        # This load must not leak an unchecked reference onto the value stack.
        self.assert_denied('''
            with sys.monitoring.StopTheWorld:
                value = shared['value']
                value.append(42)
            try:
                [value for value in ()]
            except IllegalThreadAccessException:
                with sys.monitoring.StopTheWorld:
                    if value is not shared['value']:
                        return 'lost local'
                return 'denied'
            return 'unchecked'
        ''', opcode='LOAD_FAST_AND_CLEAR_CHECK')

    def test_with_target(self):
        self.assert_denied('''
            class Context:
                def __enter__(self):
                    sys.monitoring.StopTheWorld.__enter__()
                    return self.shared['value']
                def __exit__(self, *exc):
                    return sys.monitoring.StopTheWorld.__exit__(*exc)
            context = Context()
            context.shared = shared
            with context as value:
                value.append(42)
            try:
                return value
            except IllegalThreadAccessException:
                return 'denied'
        ''')

    def test_async_with(self):
        namespace = {'sys': sys}
        exec(textwrap.dedent('''
            class Context:
                async def __aenter__(self):
                    sys.monitoring.StopTheWorld.__enter__()
                async def __aexit__(self, *exc):
                    return sys.monitoring.StopTheWorld.__exit__(*exc)
            async def read(shared, context):
                async with context:
                    value = shared['value']
                    value.append(42)
                try:
                    return value
                except IllegalThreadAccessException:
                    return 'denied'
        '''), namespace)
        context_type = freeze(namespace['Context'])
        read = namespace['read']
        self.assertTrue(any(i.opname in (
            'LOAD_FAST_MAYBE_UNPROTECTED',
            'LOAD_FAST_BORROW_MAYBE_UNPROTECTED',
        ) for i in dis.get_instructions(read)))
        def work(shared, read, context_type):
            coroutine = read(shared, context_type())
            try:
                coroutine.send(None)
            except StopIteration as exc:
                return exc.value
            finally:
                coroutine.close()
        value = []
        self.assertEqual(self.run_native(work, SynchronizedDict(value=value),
                                         read, context_type), 'denied')
        self.assertEqual(value, [42])

    def test_unbound_and_reassignment(self):
        def read(flag):
            if flag:
                with sys.monitoring.StopTheWorld:
                    value = 42
            return value
        with self.assertRaises(UnboundLocalError):
            read(False)
        self.assertEqual(read(True), 42)

        def shadow(flag):
            if flag:
                with sys.monitoring.StopTheWorld:
                    value = 42
            result = [value for value in (1, 2)]
            if not flag:
                value = 99
            return result, value
        self.assertEqual(shadow(False), ([1, 2], 99))
        self.assertEqual(shadow(True), ([1, 2], 42))

    def test_borrowed_access_and_local_lifetime(self):
        self.assert_denied('''
            with sys.monitoring.StopTheWorld:
                value = shared['value']
                value.append(42)
            try:
                value.append(99)
            except IllegalThreadAccessException:
                return 'denied'
        ''', opcode='LOAD_FAST_BORROW_MAYBE_UNPROTECTED')

        def replace():
            with sys.monitoring.StopTheWorld:
                value = [42]
            return value, (value := [99])

        # A reference whose supporting local is overwritten before use must
        # remain owned, even though its access check succeeds.
        self.assertEqual(replace(), ([42], [99]))
        loads = [i for i in dis.get_instructions(replace)
                 if i.argval == 'value' and i.opname.startswith('LOAD_FAST')]
        self.assertEqual([i.opname for i in loads],
                         ['LOAD_FAST_MAYBE_UNPROTECTED'])

    def test_without_with_unchanged(self):
        def function(value):
            return value
        self.assertFalse(any(i.opname.endswith('_CHECK') or
                             i.opname in ('LOAD_FAST_MAYBE_UNPROTECTED',
                                          'LOAD_FAST_BORROW_MAYBE_UNPROTECTED')
                             for i in dis.get_instructions(function)))

    def test_generator_closes_protection_in_another_frame(self):
        # None of these loads is lexically inside a with statement. Each
        # generator.close() invalidates an earlier, valid local acquisition.
        bodies = (
            'return value',
            'return value[0]',
            'index = 0\nreturn value[index]',
            'index = 0; return value',
            '[value for value in ()]',
        )
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()

            def source():
                with lock:
                    yield lock.protect([42])

            for body in bodies:
                namespace = {}
                exec('def work(source):\n'
                     '    generator = source()\n'
                     '    value = next(generator)\n'
                     '    assert value[0] == 42\n'
                     '    generator.close()\n'
                     + textwrap.indent(body, '    '), namespace)
                work = namespace['work']
                with self.subTest(lock=lock_type, body=body):
                    # Exercise cold and specialized instructions.
                    for _ in range(100):
                        with self.assertRaises(UnprotectedAccessException):
                            work(source)

            def maybe_bound(source, initialized):
                generator = source()
                if initialized:
                    value = next(generator)
                generator.close()
                return value

            with self.assertRaises(UnprotectedAccessException):
                maybe_bound(source, True)
            with self.assertRaises(UnboundLocalError):
                maybe_bound(source, False)

    def test_generator_closes_debugger_access_in_another_frame(self):
        def work(shared):
            def source():
                with sys.monitoring.StopTheWorld:
                    yield shared['value']

            generator = source()
            value = next(generator)
            value.append(42)
            generator.close()
            try:
                return value[0]
            except IllegalThreadAccessException:
                return 'denied'

        value = []
        self.assertEqual(self.run_native(work, SynchronizedDict(value=value)),
                         'denied')
        self.assertEqual(value, [42])

    def test_call_revokes_earlier_expression_operand(self):
        bodies = (
            'return value[generator.close() or 0]',
            'value[generator.close() or 0] = 99',
            'del value[generator.close() or 0]',
            'return value[close() or 0]',
            'value[close() or 0] = 99',
        )
        for lock_type in (threading.Lock, threading.RLock):
            lock = lock_type()

            def source():
                with lock:
                    yield lock.protect([42])

            for body in bodies:
                namespace = {}
                exec('def work(source):\n'
                     '    generator = source()\n'
                     '    value = next(generator)\n'
                     '    def close():\n'
                     '        generator.close()\n'
                     + textwrap.indent(body, '    '), namespace)
                with self.subTest(lock=lock_type, body=body):
                    for _ in range(100):
                        with self.assertRaises(UnprotectedAccessException):
                            namespace['work'](source)

    def test_generator_can_catch_invalid_local_load(self):
        lock = threading.Lock()

        def source():
            with lock:
                yield lock.protect([42])

        def consume(value):
            try:
                yield value
            except UnprotectedAccessException:
                yield 'denied'

        generator = source()
        consumer = consume(next(generator))
        generator.close()
        self.assertEqual(next(consumer), 'denied')
        consumer.close()


if __name__ == '__main__':
    unittest.main()
