import _codecs
import codecs
import io
import unittest
import sys
from io import StringIO

from test import support

NotDefined = object()

# A dispatch table all 8 combinations of providing
# sep, end, and file.
# I use this machinery so that I'm not just passing default
# values to print, I'm either passing or not passing in the
# arguments.
dispatch = {
    (False, False, False):
        lambda args, sep, end, file: print(*args),
    (False, False, True):
        lambda args, sep, end, file: print(file=file, *args),
    (False, True,  False):
        lambda args, sep, end, file: print(end=end, *args),
    (False, True,  True):
        lambda args, sep, end, file: print(end=end, file=file, *args),
    (True,  False, False):
        lambda args, sep, end, file: print(sep=sep, *args),
    (True,  False, True):
        lambda args, sep, end, file: print(sep=sep, file=file, *args),
    (True,  True,  False):
        lambda args, sep, end, file: print(sep=sep, end=end, *args),
    (True,  True,  True):
        lambda args, sep, end, file: print(sep=sep, end=end, file=file, *args),
}


# Class used to test __str__ and print
class ClassWith__str__:
    def __init__(self, x):
        self.x = x

    def __str__(self):
        return self.x


class TestPrint(unittest.TestCase):
    """Test correct operation of the print function."""

    def check(self, expected, args,
              sep=NotDefined, end=NotDefined, file=NotDefined):
        # Capture sys.stdout in a StringIO.  Call print with args,
        # and with sep, end, and file, if they're defined.  Result
        # must match expected.

        # Look up the actual function to call, based on if sep, end,
        # and file are defined.
        fn = dispatch[(sep is not NotDefined,
                       end is not NotDefined,
                       file is not NotDefined)]

        with support.captured_stdout() as t:
            fn(args, sep, end, file)

        self.assertEqual(t.getvalue(), expected)

    def test_print(self):
        def x(expected, args, sep=NotDefined, end=NotDefined):
            # Run the test 2 ways: not using file, and using
            # file directed to a StringIO.

            self.check(expected, args, sep=sep, end=end)

            # When writing to a file, stdout is expected to be empty
            o = StringIO()
            self.check('', args, sep=sep, end=end, file=o)

            # And o will contain the expected output
            self.assertEqual(o.getvalue(), expected)

        x('\n', ())
        x('a\n', ('a',))
        x('None\n', (None,))
        x('1 2\n', (1, 2))
        x('1   2\n', (1, ' ', 2))
        x('1*2\n', (1, 2), sep='*')
        x('1 s', (1, 's'), end='')
        x('a\nb\n', ('a', 'b'), sep='\n')
        x('1.01', (1.0, 1), sep='', end='')
        x('1*a*1.3+', (1, 'a', 1.3), sep='*', end='+')
        x('a\n\nb\n', ('a\n', 'b'), sep='\n')
        x('\0+ +\0\n', ('\0', ' ', '\0'), sep='+')

        x('a\n b\n', ('a\n', 'b'))
        x('a\n b\n', ('a\n', 'b'), sep=None)
        x('a\n b\n', ('a\n', 'b'), end=None)
        x('a\n b\n', ('a\n', 'b'), sep=None, end=None)

        x('*\n', (ClassWith__str__('*'),))
        x('abc 1\n', (ClassWith__str__('abc'), 1))

        # errors
        self.assertRaises(TypeError, print, '', sep=3)
        self.assertRaises(TypeError, print, '', end=3)
        self.assertRaises(AttributeError, print, '', file='')

    def test_print_flush(self):
        # operation of the flush flag
        class filelike:
            def __init__(self):
                self.written = ''
                self.flushed = 0

            def write(self, str):
                self.written += str

            def flush(self):
                self.flushed += 1

        f = filelike()
        print(1, file=f, end='', flush=True)
        print(2, file=f, end='', flush=True)
        print(3, file=f, flush=False)
        self.assertEqual(f.written, '123\n')
        self.assertEqual(f.flushed, 2)

        # ensure exceptions from flush are passed through
        class noflush:
            def write(self, str):
                pass

            def flush(self):
                raise RuntimeError
        self.assertRaises(RuntimeError, print, 1, file=noflush(), flush=True)

    def test_gh130163(self):
        class X:
            def __str__(self):
                sys.stdout = StringIO()
                support.gc_collect()
                return 'foo'

        with support.swap_attr(sys, 'stdout', None):
            sys.stdout = StringIO()  # the only reference
            print(X())  # should not crash

    def test_single_write(self):
        class Stream:
            def __init__(self):
                self.events = []

            def write(self, text):
                self.events.append(('write', text))

            def flush(self):
                self.events.append(('flush',))

        cases = [
            ((), {}, '\n'),
            ((), {'end': ''}, ''),
            (('a', 'b'), {}, 'a b\n'),
            ((1, None, 2.5), {}, '1 None 2.5\n'),
            (('a', '\u00e9', '\u65e5', '\U0001f40d', '\0'),
             {'sep': '|', 'end': '!'}, 'a|\u00e9|\u65e5|\U0001f40d|\0!'),
        ]
        for args, kwargs, expected in cases:
            with self.subTest(args=args, kwargs=kwargs):
                stream = Stream()
                print(*args, file=stream, flush=True, **kwargs)
                self.assertEqual(stream.events,
                                 [('write', expected), ('flush',)])

    def test_string_subclass_conversion(self):
        class Separator(str):
            def __str__(self):
                calls.append('sep')
                return str(len(calls))

        class Ending(str):
            def __str__(self):
                calls.append('end')
                return '!'

        class Value(str):
            def __str__(self):
                calls.append('value')
                return 'X'

        calls = []
        stream = StringIO()
        print(Value('ignored'), 'b', 'c', sep=Separator('ignored'),
              end=Ending('ignored'), file=stream)
        self.assertEqual(calls, ['value', 'sep', 'sep', 'end'])
        self.assertEqual(stream.getvalue(), 'X2b3c!')

    def test_conversion_error_before_write(self):
        class BadValue:
            def __str__(self):
                raise ValueError('conversion failed')

        stream = StringIO()
        with self.assertRaisesRegex(ValueError, 'conversion failed'):
            print('prefix', BadValue(), file=stream)
        self.assertEqual(stream.getvalue(), '')

    def test_write_error_does_not_flush(self):
        class Stream:
            def write(self, text):
                raise OSError('write failed')

            def flush(self):
                raise AssertionError('flush called after a failed write')

        stream = Stream()
        with self.assertRaisesRegex(OSError, 'write failed'):
            print('a', 'b', file=stream, flush=True)


class TestTextIOPrint(unittest.TestCase):
    def test_encoding_and_newlines(self):
        for encoding, word in [('ascii', 'hello'), ('latin-1', 'café'),
                               ('utf-8', '日本語🐍'), ('utf-16', '日本語'),
                               ('utf-32', '日本語'), ('iso2022_jp', '日本語')]:
            for newline in [None, '', '\n', '\r', '\r\n']:
                with self.subTest(encoding=encoding, newline=newline):
                    output = io.BytesIO()
                    expected = io.BytesIO()
                    with (io.TextIOWrapper(output, encoding=encoding,
                                           newline=newline) as stream,
                          io.TextIOWrapper(expected, encoding=encoding,
                                           newline=newline) as reference):
                        # Mix scalar pending bytes, fragment lists and reads.
                        stream.write('prefix:')
                        reference.write('prefix:')
                        for _ in range(3):
                            print(word, 42, sep='\n', end='\r\n', file=stream)
                            reference.write(word + '\n42\r\n')
                        print(file=stream, end='')
                        stream.write('suffix')
                        reference.write('suffix')
                        stream.flush()
                        reference.flush()
                        self.assertEqual(output.getvalue(), expected.getvalue())
                        stream.seek(0)
                        reference.seek(0)
                        self.assertEqual(stream.read(), reference.read())

    def test_buffering(self):
        class Buffer(io.BytesIO):
            def write(self, data):
                events.append(('write', data))
                return super().write(data)

            def flush(self):
                events.append(('flush',))
                return super().flush()

        for line_buffering, write_through, ending, flush in [
            (False, False, '\n', False),
            (False, False, '\n', True),
            (False, True, '', False),
            (True, False, '\n', False),
            (True, False, '\r', False),
            (True, False, '', False),
        ]:
            with self.subTest(line_buffering=line_buffering,
                              write_through=write_through,
                              ending=ending, flush=flush):
                events = []
                with io.TextIOWrapper(Buffer(), encoding='utf-8',
                                      line_buffering=line_buffering,
                                      write_through=write_through) as stream:
                    print('a', 'b', end=ending, file=stream, flush=flush)
                    needflush = flush or (line_buffering and bool(ending))
                    expected = []
                    if needflush or write_through:
                        expected.append(('write', ('a b' + ending).encode()))
                    if needflush:
                        expected.append(('flush',))
                    self.assertEqual(events, expected)

    def test_large_output(self):
        for word in ['x' * 65536, '日' * 65536]:
            with self.subTest(word=word[:1]):
                output = io.BytesIO()
                with io.TextIOWrapper(output, encoding='utf-8') as stream:
                    stream.write('before')
                    print(word, word, file=stream)
                    stream.write('after')
                    stream.flush()
                    self.assertEqual(output.getvalue(),
                                     ('before' + word + ' ' + word + '\nafter')
                                     .encode())

    def test_write_overrides(self):
        class Stream(io.TextIOWrapper):
            def write(self, text):
                writes.append(text)

        for cls in [Stream, io.TextIOWrapper]:
            with self.subTest(cls=cls):
                writes = []
                output = io.BytesIO()
                with cls(output, encoding='utf-8') as stream:
                    if cls is io.TextIOWrapper:
                        stream.write = writes.append
                    print('a', 'b', file=stream)
                    stream.flush()
                    self.assertEqual(writes, ['a b\n'])
                    self.assertEqual(output.getvalue(), b'')

    def test_conversion_changes_stream(self):
        class Value:
            def __str__(self):
                change()
                return 'é'

        for action in ['close', 'detach', 'reconfigure']:
            with self.subTest(action=action):
                output = io.BytesIO()
                stream = io.TextIOWrapper(output, encoding='utf-8')
                if action == 'reconfigure':
                    change = lambda: stream.reconfigure(encoding='latin-1')
                    with stream:
                        print('prefix', Value(), file=stream)
                        stream.flush()
                        self.assertEqual(output.getvalue(), b'prefix \xe9\n')
                else:
                    change = getattr(stream, action)
                    with self.assertRaises(ValueError):
                        print('prefix', Value(), file=stream)
                    if action == 'detach':
                        self.assertEqual(output.getvalue(), b'')

    def test_invalid_streams(self):
        uninitialized = io.TextIOWrapper.__new__(io.TextIOWrapper)
        with self.assertRaises(ValueError):
            print('a', 'b', file=uninitialized)
        with open(__file__, encoding='utf-8') as readonly:
            with self.assertRaises(io.UnsupportedOperation):
                print('a', 'b', file=readonly)

    def test_encoding_error(self):
        for encoding, bad in [('ascii', 'é'), ('latin-1', '日'),
                              ('utf-8', '\ud800')]:
            with self.subTest(encoding=encoding):
                output = io.BytesIO()
                with io.TextIOWrapper(output, encoding=encoding) as stream:
                    with self.assertRaises(UnicodeEncodeError) as caught:
                        print('prefix', bad, file=stream)
                    self.assertEqual(caught.exception.object,
                                     'prefix ' + bad + '\n')
                    self.assertEqual(caught.exception.start, 7)
                    stream.flush()
                    self.assertEqual(output.getvalue(), b'')

    def test_encoding_error_handler(self):
        seen = []

        def handler(exc):
            seen.append(exc.object)
            return '?', exc.end

        codecs.register_error('test_print_fragments', handler)
        self.addCleanup(_codecs._unregister_error, 'test_print_fragments')
        output = io.BytesIO()
        with io.TextIOWrapper(output, encoding='ascii',
                              errors='test_print_fragments') as stream:
            print('prefix', 'é', file=stream)
            stream.flush()
            self.assertEqual(seen, ['prefix é\n'])
            self.assertEqual(output.getvalue(), b'prefix ?\n')

    def test_custom_encoder(self):
        seen = []

        class Encoder(codecs.IncrementalEncoder):
            def encode(self, text, final=False):
                seen.append(text)
                return text.encode('utf-8')

        def search(name):
            if name == 'test_print_codec':
                utf8 = codecs.lookup('utf-8')
                return codecs.CodecInfo(
                    name=name, encode=utf8.encode, decode=utf8.decode,
                    incrementalencoder=Encoder,
                    incrementaldecoder=utf8.incrementaldecoder)

        codecs.register(search)
        self.addCleanup(codecs.unregister, search)
        output = io.BytesIO()
        with io.TextIOWrapper(output, encoding='test_print_codec') as stream:
            print('a', 'b', file=stream)
            stream.flush()
            self.assertEqual(seen, ['a b\n'])
            self.assertEqual(output.getvalue(), b'a b\n')

    def test_conversion_order_and_error(self):
        seen = []

        class Value(str):
            def __str__(self):
                seen.append(self)
                return str(len(seen))

        class BadValue:
            def __str__(self):
                raise RuntimeError('conversion failed')

        output = io.BytesIO()
        with io.TextIOWrapper(output, encoding='utf-8') as stream:
            print(Value('value'), 'b', 'c', sep=Value('sep'),
                  end=Value('end'), file=stream)
            self.assertEqual(seen, ['value', 'sep', 'sep', 'end'])
            stream.flush()
            self.assertEqual(output.getvalue(), b'12b3c4')
            with self.assertRaisesRegex(RuntimeError, 'conversion failed'):
                print('prefix', BadValue(), file=stream)
            stream.flush()
            self.assertEqual(output.getvalue(), b'12b3c4')

    def test_read_then_print(self):
        output = io.BytesIO(b'first\nsecond\n')
        with io.TextIOWrapper(output, encoding='utf-8') as stream:
            self.assertEqual(stream.readline(), 'first\n')
            print('a', 'b', file=stream)
            stream.seek(0)
            self.assertEqual(stream.read(), 'first\nsecond\na b\n')


class TestPy2MigrationHint(unittest.TestCase):
    """Test that correct hint is produced analogous to Python3 syntax,
    if print statement is executed as in Python 2.
    """

    def test_normal_string(self):
        python2_print_str = 'print "Hello World"'
        with self.assertRaises(SyntaxError) as context:
            exec(python2_print_str)

        self.assertIn("Missing parentheses in call to 'print'. Did you mean print(...)",
                str(context.exception))

    def test_string_with_soft_space(self):
        python2_print_str = 'print "Hello World",'
        with self.assertRaises(SyntaxError) as context:
            exec(python2_print_str)

        self.assertIn("Missing parentheses in call to 'print'. Did you mean print(...)",
                str(context.exception))

    def test_string_with_excessive_whitespace(self):
        python2_print_str = 'print  "Hello World", '
        with self.assertRaises(SyntaxError) as context:
            exec(python2_print_str)

        self.assertIn("Missing parentheses in call to 'print'. Did you mean print(...)",
                str(context.exception))

    def test_string_with_leading_whitespace(self):
        python2_print_str = '''if 1:
            print "Hello World"
        '''
        with self.assertRaises(SyntaxError) as context:
            exec(python2_print_str)

        self.assertIn("Missing parentheses in call to 'print'. Did you mean print(...)",
                str(context.exception))

    # bpo-32685: Suggestions for print statement should be proper when
    # it is in the same line as the header of a compound statement
    # and/or followed by a semicolon
    def test_string_with_semicolon(self):
        python2_print_str = 'print p;'
        with self.assertRaises(SyntaxError) as context:
            exec(python2_print_str)

        self.assertIn("Missing parentheses in call to 'print'. Did you mean print(...)",
                str(context.exception))

    def test_string_in_loop_on_same_line(self):
        python2_print_str = 'for i in s: print i'
        with self.assertRaises(SyntaxError) as context:
            exec(python2_print_str)

        self.assertIn("Missing parentheses in call to 'print'. Did you mean print(...)",
                str(context.exception))


if __name__ == "__main__":
    unittest.main()
