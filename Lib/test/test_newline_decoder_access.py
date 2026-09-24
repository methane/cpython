"""Checked decoder acquisition in native newline translation."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class NewlineDecoderAccessTests(unittest.TestCase):
    PRELUDE = '''
import io
import threading

class Decoder:
    def decode(self, data, final=False): return data.decode('utf-8')
    def getstate(self): return b'', 0
    def setstate(self, state): pass
    def reset(self): pass
'''

    def run_script(self, script):
        script = self.PRELUDE + textwrap.dedent(script)
        assert_python_ok('-c', 'from test.support import SuppressCrashReport\n'
                         'with SuppressCrashReport():\n' +
                         textwrap.indent(script, '    '))

    def test_protected_stored_decoder(self):
        for operation in ("wrapper.decode(b'x')", 'wrapper.getstate()',
                          "wrapper.setstate((b'', 0))", 'wrapper.reset()'):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    lock = threading.Lock()
                    with lock:
                        decoder = lock.protect(Decoder())
                        wrapper = io.IncrementalNewlineDecoder(decoder, True)
                        assert wrapper.decode(b'\\n\\r') == '\\n'
                        assert wrapper.getstate() == (b'', 1)
                        assert wrapper.newlines == '\\n'
                    try:
                        {operation}
                    except UnprotectedAccessException:
                        pass
                    else:
                        raise AssertionError('unprotected decoder used')
                    with lock:
                        assert wrapper.getstate() == (b'', 1)
                        assert wrapper.newlines == '\\n'
                        assert wrapper.decode(b'\\n', True) == '\\n'
                        wrapper.reset()
                        assert wrapper.getstate() == (b'', 0)
                        assert wrapper.newlines is None
                ''')

    @threading_helper.requires_working_threading()
    def test_foreign_stored_decoder(self):
        for operation in ("wrapper.decode(b'x')", 'wrapper.getstate()',
                          "wrapper.setstate((b'', 0))", 'wrapper.reset()'):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    import _testinternalcapi
                    from test.support import threading_helper

                    wrapper = io.IncrementalNewlineDecoder(Decoder(), True)
                    _testinternalcapi.object_declare_synchronized(wrapper)
                    results = SynchronizedList()
                    def worker():
                        try:
                            {operation}
                        except BaseException as exc:
                            results.append(type(exc).__name__)
                        else:
                            results.append('foreign decoder used')
                    thread = threading.Thread(target=worker,
                                              group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    assert list(results) == ['IllegalThreadAccessException'], results
                ''')

    def test_protected_state_elements(self):
        for operation in ('getstate', 'setstate'):
            for element in ('buffer', 'flag'):
                with self.subTest(operation=operation, element=element):
                    self.run_script(f'''
                        class Flag:
                            def __index__(self): return 0
                        lock = threading.Lock()
                        with lock:
                            protected = lock.protect({"Flag()" if element == 'flag' else "[]"})
                            state = {"(b'', protected)" if element == 'flag' else "(protected, 0)"}
                        class StateDecoder(Decoder):
                            def getstate(self): return state
                        wrapper = io.IncrementalNewlineDecoder(StateDecoder(), True)
                        try:
                            wrapper.{operation}({'state' if operation == 'setstate' else ''})
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected state element used')
                        with lock:
                            wrapper.{operation}({'state' if operation == 'setstate' else ''})
                    ''')

    def test_decoder_reference_balance(self):
        self.run_script('''
            import sys
            from test.support import gc_collect

            lock = threading.Lock()
            with lock:
                decoder = lock.protect(Decoder())
                wrapper = io.IncrementalNewlineDecoder(decoder, True)
                before = sys.getrefcount(decoder)
                for _ in range(100):
                    assert wrapper.decode(b'x') == 'x'
                    assert wrapper.getstate() == (b'', 0)
                    wrapper.setstate((b'', 0))
                    wrapper.reset()
                gc_collect()
                assert sys.getrefcount(decoder) == before
            for _ in range(100):
                for operation in ('decode', 'getstate', 'setstate', 'reset'):
                    try:
                        if operation == 'decode':
                            wrapper.decode(b'x')
                        elif operation == 'setstate':
                            wrapper.setstate((b'', 0))
                        else:
                            getattr(wrapper, operation)()
                    except UnprotectedAccessException:
                        pass
                    else:
                        raise AssertionError('unprotected decoder used')
            with lock:
                gc_collect()
                assert sys.getrefcount(decoder) == before
        ''')

    def test_initializer_publishes_before_releasing_old_errors(self):
        self.run_script('''
            from test.support import gc_collect

            seen = []
            class OldErrors:
                def __del__(self):
                    try:
                        seen.append(wrapper.decode('\\r\\n', True))
                    except BaseException as exc:
                        seen.append((type(exc).__name__, str(exc)))

            wrapper = io.IncrementalNewlineDecoder(Decoder(), True, OldErrors())
            assert wrapper.decode(b'\\r') == ''
            wrapper.__init__(None, False)
            gc_collect()
            assert seen == ['\\r\\n'], seen
            assert wrapper.decode('\\n', True) == '\\n'
        ''')

    def test_decoder_survives_method_lookup_reinitialization(self):
        for operation, result in (("decode(b'x')", 'x'),
                                  ('getstate()', (b'', 0)),
                                  ("setstate((b'', 0))", None),
                                  ('reset()', None)):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    import weakref
                    from test.support import gc_collect

                    class RetiringDecoder(Decoder):
                        def __getattribute__(self, name):
                            reference = weakref.ref(self)
                            wrapper.__init__(None, True)
                            def call(*args):
                                gc_collect()
                                assert reference() is not None, 'decoder released during call'
                                return {result!r}
                            return call

                    wrapper = io.IncrementalNewlineDecoder(RetiringDecoder(), True)
                    assert wrapper.{operation} == {result!r}
                ''')

    def test_stringio_closed_by_decoder(self):
        self.run_script('''
            import gc

            stream = io.StringIO(newline=None)
            decoder = next(obj for obj in gc.get_referents(stream)
                           if isinstance(obj, io.IncrementalNewlineDecoder))
            class ClosingDecoder:
                def decode(self, text, final):
                    stream.close()
                    return text
            decoder.__init__(ClosingDecoder(), True)
            try:
                stream.write('text')
            except ValueError:
                pass
            else:
                raise AssertionError('wrote after decoder closed the stream')
            assert stream.closed
        ''')

    @threading_helper.requires_working_threading()
    def test_stringio_stored_decoder(self):
        for newline in (None, ''):
            with self.subTest(newline=newline):
                self.run_script(f'''
                    import _testinternalcapi
                    from test.support import threading_helper

                    stream = io.StringIO(newline={newline!r})
                    _testinternalcapi.object_declare_synchronized(stream)
                    results = SynchronizedList()
                    def worker():
                        try:
                            stream.write('text\\r\\n')
                        except BaseException as exc:
                            results.append(type(exc).__name__)
                        else:
                            results.append('foreign decoder used')
                    thread = threading.Thread(target=worker,
                                              group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    stream.close()
                    assert list(results) == ['IllegalThreadAccessException'], results
                ''')

    @threading_helper.requires_working_threading()
    def test_text_stored_decoder(self):
        for operation in ('stream.read()', 'stream.read(1)'):
            with self.subTest(operation=operation):
                self.run_script(f'''
                    import _testinternalcapi
                    from test.support import threading_helper

                    class Buffer(io.BytesIO):
                        def seekable(self): return False
                    raw = Buffer(b'text\\r\\n')
                    stream = io.TextIOWrapper(raw, encoding='utf-8')
                    _testinternalcapi.object_declare_synchronized(raw)
                    _testinternalcapi.object_declare_synchronized(stream)
                    results = SynchronizedList()
                    def worker():
                        try:
                            {operation}
                        except BaseException as exc:
                            results.append(type(exc).__name__)
                        else:
                            results.append('foreign decoder used')
                    thread = threading.Thread(target=worker,
                                              group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    stream.close()
                    assert list(results) == ['IllegalThreadAccessException'], results
                ''')


if __name__ == '__main__':
    unittest.main()
