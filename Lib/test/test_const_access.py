"""Access checks for objects stored in code constants."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


@threading_helper.requires_working_threading()
class ConstantAccessTests(unittest.TestCase):
    def test_foreign_constants(self):
        assert_python_ok('-c', textwrap.dedent('''
            import sys
            import threading
            from test.support import SHORT_TIMEOUT

            def subscript(index):
                return 'constant placeholder'[index]

            def identity(other):
                return ... is other

            def make_function(template, value):
                constants = tuple(
                    value if item is Ellipsis or item == 'constant placeholder'
                    else item
                    for item in template.__code__.co_consts)
                code = template.__code__.replace(co_consts=constants)
                return type(template)(code, template.__globals__)

            def worker(function, warmup, results):
                try:
                    # Specialize in the receiving thread too: free-threading
                    # has thread-local bytecode. Access is valid during STW.
                    with sys.monitoring.StopTheWorld:
                        for _ in range(warmup):
                            function(0)
                    denied = 0
                    for _ in range(100):
                        try:
                            function(0)
                        except IllegalThreadAccessException:
                            denied += 1
                    results.put(denied)
                except BaseException as exc:
                    results.put(type(exc).__name__)

            value = [42]
            for template in (subscript, identity):
                for warmup in (0, 100):
                    function = make_function(template, value)
                    for _ in range(warmup):
                        function(0)
                    results = threading.Channel()
                    thread = threading.Thread(
                        target=worker, args=(function, warmup, results),
                        group=threading.ThreadGroup())
                    thread.start()
                    thread.join(SHORT_TIMEOUT)
                    assert not thread.is_alive()
                    observed = results.get()
                    assert observed == 100, observed
        '''))

    def test_protected_constants(self):
        assert_python_ok('-c', textwrap.dedent('''
            import threading

            def subscript(index):
                return 'constant placeholder'[index]

            def identity(other):
                return ... is other

            for template in (subscript, identity):
                for warmup in (0, 100):
                    lock = threading.Lock()
                    with lock:
                        value = lock.protect([42])
                        constants = tuple(
                            value if item is Ellipsis or item == 'constant placeholder'
                            else item
                            for item in template.__code__.co_consts)
                        code = template.__code__.replace(co_consts=constants)
                        function = type(template)(code, template.__globals__)
                        for _ in range(warmup):
                            function(0)
                    for _ in range(100):
                        try:
                            function(0)
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected constant acquired')
                    with lock:
                        expected = 42 if template is subscript else False
                        assert function(0) == expected
        '''))

    def test_shallow_immutable_constant(self):
        assert_python_ok('-c', textwrap.dedent('''
            import threading
            from test.support import SHORT_TIMEOUT

            def template():
                return 'constant placeholder'

            value = ([42],)
            constants = tuple(
                value if item == 'constant placeholder' else item
                for item in template.__code__.co_consts)
            code = template.__code__.replace(co_consts=constants)
            function = type(template)(code, template.__globals__)
            results = threading.Channel()

            def worker(function, value, results):
                try:
                    result = function()
                    assert result is value
                    try:
                        result[0]
                    except IllegalThreadAccessException:
                        results.put('ok')
                    else:
                        results.put('foreign element acquired')
                except BaseException as exc:
                    results.put(type(exc).__name__)

            thread = threading.Thread(
                target=worker, args=(function, value, results),
                group=threading.ThreadGroup())
            thread.start()
            thread.join(SHORT_TIMEOUT)
            assert not thread.is_alive()
            observed = results.get()
            assert observed == 'ok', observed
        '''))


if __name__ == '__main__':
    unittest.main()
