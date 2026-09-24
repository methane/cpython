"""Access and lifetime of codecs stored by TextIOWrapper."""

import textwrap
import unittest

from test.support import threading_helper
from test.support.script_helper import assert_python_ok


class TextCodecAccessTests(unittest.TestCase):
    PRELUDE = '''
import codecs
import io
import threading

class Encoder:
    def __init__(self, errors='strict'): pass
    def encode(self, text, final=False): return text.encode('latin-1')
    def reset(self): pass
    def setstate(self, state): pass

class Decoder:
    newlines = None
    def __init__(self, errors='strict'): pass
    def decode(self, data, final=False): return bytes(data).decode('latin-1')
    def getstate(self): return b'', 0
    def reset(self): pass
    def setstate(self, state): pass

encoder_factory = Encoder
decoder_factory = Decoder
def search(name):
    if name == 'pep805_text':
        return codecs.CodecInfo(
            name=name,
            encode=lambda text, errors='strict': (text.encode('latin-1'), len(text)),
            decode=lambda data, errors='strict': (bytes(data).decode('latin-1'), len(data)),
            incrementalencoder=lambda errors: encoder_factory(errors),
            incrementaldecoder=lambda errors: decoder_factory(errors))
codecs.register(search)
'''

    def run_script(self, script):
        script = self.PRELUDE + textwrap.dedent(script)
        assert_python_ok('-c', 'from test.support import SuppressCrashReport\n'
                         'with SuppressCrashReport():\n' +
                         textwrap.indent(script, '    '))

    def test_protected_codecs(self):
        for kind, prepare, operations in (
            ('Encoder', '', ("stream.write('x')", 'stream.seek(0)',
                             'stream.seek(1)', 'stream.seek(0, 2)')),
            ('Decoder', '', ('stream.read(1)', 'stream.read()',
                             "stream.write('x')", 'stream.seek(0)',
                             'stream.seek(1)', 'stream.seek(0, 2)',
                             'stream.newlines')),
            ('Decoder', 'stream.read(1)', ('stream.tell()',)),
        ):
            for operation in operations:
                with self.subTest(kind=kind, prepare=prepare, operation=operation):
                    self.run_script(f'''
                        lock = threading.Lock()
                        with lock:
                            codec = lock.protect({kind}())
                            {kind.lower()}_factory = lambda errors: codec
                            raw = io.BytesIO(b'abcdefgh')
                            stream = io.TextIOWrapper(raw, encoding='pep805_text', newline='\\n')
                            {prepare or 'pass'}
                        try:
                            {operation}
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected codec used')
                        with lock:
                            stream.close()
                    ''')

    @threading_helper.requires_working_threading()
    def test_foreign_fast_encoding_errors(self):
        for encoding in ('ascii', 'latin1', 'utf-8', 'utf-16', 'utf-16-be',
                         'utf-16-le', 'utf-32', 'utf-32-be', 'utf-32-le'):
            with self.subTest(encoding=encoding):
                self.run_script(f'''
                    import sys
                    from test.support import threading_helper
                    channel = threading.Channel()
                    def producer():
                        class Errors(str): pass
                        channel.put((Errors('ignore'),))
                    thread = threading.Thread(target=producer,
                                              group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    payload = channel.get()
                    with sys.monitoring.StopTheWorld:
                        raw = io.BytesIO()
                        stream = io.TextIOWrapper(raw, encoding={encoding!r}, errors=payload[0])
                    try:
                        stream.write('é')
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign error setting used')
                    with sys.monitoring.StopTheWorld:
                        assert stream.write('é') == 1
                        stream.close()
                ''')

    def test_fast_encoding_retains_errors_during_handler(self):
        self.run_script('''
            import weakref
            from test.support import gc_collect

            class Errors(str): pass
            observed = []
            def handler(exc):
                stream.__init__(io.BytesIO(), encoding='ascii')
                gc_collect()
                observed.append(reference() is not None)
                return '?', exc.end
            codecs.register_error('pep805_error_handler', handler)
            stream = io.TextIOWrapper(io.BytesIO(), encoding='ascii',
                                      errors=Errors('pep805_error_handler'))
            reference = weakref.ref(stream.errors)
            assert stream.write('é') == 1
            assert observed == [True], observed
            stream.close()
        ''')

    def test_codec_reference_balance(self):
        self.run_script('''
            import sys
            from test.support import gc_collect

            failing = False
            class FailingDecoder(Decoder):
                def getstate(self):
                    if failing:
                        raise LookupError('decoder state unavailable')
                    return super().getstate()
            encoder = Encoder()
            decoder = FailingDecoder()
            encoder_factory = lambda errors: encoder
            decoder_factory = lambda errors: decoder
            stream = io.TextIOWrapper(io.BytesIO(b'abcdef'), encoding='pep805_text', newline='\\n')
            before = (sys.getrefcount(encoder), sys.getrefcount(decoder))
            for _ in range(100):
                stream.seek(0)
                assert stream.read(1) == 'a'
                cookie = stream.tell()
                stream.seek(cookie)
                assert stream.write('x') == 1
                stream.flush()
                assert stream.newlines is None
            stream.seek(0)
            assert stream.read(1) == 'a'
            failing = True
            for _ in range(100):
                try:
                    stream.tell()
                except LookupError:
                    pass
                else:
                    raise AssertionError('decoder error ignored')
            gc_collect()
            assert (sys.getrefcount(encoder), sys.getrefcount(decoder)) == before
            stream.close()
        ''')

    @threading_helper.requires_working_threading()
    def test_foreign_inherited_settings(self):
        for setting, operation in (
            ('encoding', "stream.reconfigure(newline='')"),
            ('errors', "stream.reconfigure(newline='')"),
            ('encoding', 'repr(stream)'),
            ('errors', 'stream.errors'),
        ):
            with self.subTest(setting=setting, operation=operation):
                self.run_script(f'''
                    import sys
                    from test.support import threading_helper
                    channel = threading.Channel()
                    def producer():
                        class Setting(str): pass
                        channel.put((Setting({'latin-1' if setting == 'encoding' else 'ignore'!r}),))
                    thread = threading.Thread(target=producer,
                                              group=threading.ThreadGroup())
                    with threading_helper.start_threads([thread]):
                        pass
                    payload = channel.get()
                    raw = io.BytesIO()
                    stream = io.TextIOWrapper(raw, encoding='latin-1')
                    with sys.monitoring.StopTheWorld:
                        stream.reconfigure({setting}=payload[0])
                    try:
                        {operation}
                    except IllegalThreadAccessException:
                        pass
                    else:
                        raise AssertionError('foreign setting used')
                    with sys.monitoring.StopTheWorld:
                        stream.close()
                ''')

    def test_codec_survives_method_lookup(self):
        for kind, method, prepare, operation, result in (
            ('Encoder', 'encode', '', "stream.write('x')", b'x'),
            ('Encoder', 'reset', '', 'stream.seek(0)', None),
            ('Encoder', 'setstate', '', 'stream.seek(1)', None),
            ('Decoder', 'reset', '', "stream.write('x')", None),
            ('Decoder', 'getstate', '', 'stream.read(1)', (b'', 0)),
            ('Decoder', 'getstate', 'stream.read(1)', 'stream.tell()', (b'', 0)),
            ('Decoder', 'setstate', '', 'stream.seek(1)', None),
        ):
            with self.subTest(kind=kind, method=method, operation=operation):
                self.run_script(f'''
                    import weakref
                    from test.support import gc_collect
                    armed = False
                    observed = []
                    class RetiringCodec({kind}):
                        def __getattribute__(self, name):
                            global armed
                            if name != {method!r} or not armed:
                                return super().__getattribute__(name)
                            armed = False
                            reference = weakref.ref(self)
                            stream.__init__(io.BytesIO(b'new'), encoding='latin-1')
                            def call(*args):
                                gc_collect()
                                observed.append(reference() is not None)
                                return {result!r}
                            return call
                    {kind.lower()}_factory = RetiringCodec
                    raw = io.BytesIO(b'abcdefgh')
                    stream = io.TextIOWrapper(raw, encoding='pep805_text', newline='\\n')
                    {prepare or 'pass'}
                    armed = True
                    {operation}
                    assert observed == [True], observed
                    stream.close()
                ''')

    def test_seek_retains_input_during_decoder_lookup(self):
        self.run_script('''
            armed = False
            released = []
            class Bytes(bytes):
                def __del__(self): released.append(True)
            class Buffer(io.BytesIO):
                def read(self, size=-1): return Bytes(super().read(size))
            class RetiringDecoder(codecs.getincrementaldecoder('utf-7')):
                def __getattribute__(self, name):
                    global armed
                    method = super().__getattribute__(name)
                    if name != 'decode' or not armed:
                        return method
                    armed = False
                    stream.__init__(io.BytesIO(b'new'), encoding='latin-1')
                    assert not released, 'seek input released during method lookup'
                    return method
            decoder_factory = RetiringDecoder
            raw = Buffer('日本'.encode('utf-7'))
            stream = io.TextIOWrapper(raw, encoding='pep805_text', newline='\\n')
            assert stream.read(1) == '日'
            cookie = stream.tell()
            armed = True
            stream.seek(cookie)
            assert not armed
            stream.close()
        ''')

    def test_protected_decoder_state(self):
        for operation in ('read', 'tell'):
            for element in ('buffer', 'flag'):
                with self.subTest(operation=operation, element=element):
                    self.run_script(f'''
                        class Flag:
                            def __index__(self): return 0
                        lock = threading.Lock()
                        with lock:
                            value = lock.protect({"[]" if element == 'buffer' else 'Flag()'})
                            bad_state = {"(value, 0)" if element == 'buffer' else "(b'', value)"}
                        armed = False
                        class StateDecoder(Decoder):
                            def getstate(self):
                                return bad_state if armed else (b'', 0)
                        decoder_factory = StateDecoder
                        raw = io.BytesIO(b'abcdefgh')
                        stream = io.TextIOWrapper(raw, encoding='pep805_text', newline='\\n')
                        if {operation!r} == 'tell':
                            assert stream.read(1) == 'a'
                        armed = True
                        try:
                            stream.{operation}({1 if operation == 'read' else ''})
                        except UnprotectedAccessException:
                            pass
                        else:
                            raise AssertionError('unprotected decoder state used')
                        with lock:
                            stream.close()
                    ''')


if __name__ == '__main__':
    unittest.main()
