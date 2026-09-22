"""Access checks for locals which can outlive a with statement's protection."""

import dis
import sys
import textwrap
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


if __name__ == '__main__':
    unittest.main()
