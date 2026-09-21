import sys
import textwrap
import unittest
from test import support
from test.support import import_helper, threading_helper
from test.support.script_helper import assert_python_failure

try:
    import _testcapi
    from _testcapi import PY_SSIZE_T_MIN, PY_SSIZE_T_MAX
except ImportError:
    _testcapi = None
try:
    import _testlimitedcapi
except ImportError:
    _testlimitedcapi = None
try:
    import _testinternalcapi
except ImportError:
    _testinternalcapi = None
try:
    import ctypes
except ImportError:
    ctypes = None


NULL = None

class Str(str):
    pass


@unittest.skipIf(_testcapi is None, 'need _testcapi module')
class UTF8StorageTests(unittest.TestCase):
    def make_string(self, text):
        return text.encode('utf-8', 'surrogatepass').decode('utf-8', 'surrogatepass')

    def test_subclass_primary_utf8(self):
        for text in ('', 'ascii\0text', 'éÿ', '日é', '😀日',
                     'x\ud800\udcff\0'):
            for cached in (False, True):
                source = self.make_string(text)
                if cached:
                    _testcapi.unicode_materialize_fsr(source)
                before = _testcapi.unicode_storage(source)
                value = Str(source)
                self.assertEqual(_testcapi.unicode_storage(source), before)
                encoded = text.encode('utf-8', 'surrogatepass')
                surrogate = any(0xd800 <= ord(c) <= 0xdfff for c in text)
                state = (int(not text.isascii()), 0, int(surrogate),
                         int(text.isascii()), len(encoded))
                self.assertEqual(_testcapi.unicode_storage(value), state)
                self.assertEqual(value, text)
                self.assertEqual(hash(value), hash(text))
                self.assertEqual(list(value), list(text))
                self.assertEqual(value.encode('utf-8', 'surrogatepass'), encoded)
                if surrogate:
                    with self.assertRaises(UnicodeEncodeError):
                        _testcapi.unicode_asutf8(value, 0)
                else:
                    self.assertEqual(_testcapi.unicode_asutf8(value, len(encoded) + 1),
                                     encoded + b'\0')
                self.assertEqual(_testcapi.unicode_storage(value), state)
                size = value.__sizeof__()
                _testcapi.unicode_materialize_fsr(value)
                self.assertEqual(_testcapi.unicode_storage(value)[3], 1)
                kind = 1 if max(map(ord, text), default=0) < 256 else (
                    2 if max(map(ord, text)) < 65536 else 4)
                extra = 0 if text.isascii() else (len(text) + 1) * kind
                self.assertEqual(value.__sizeof__(), size + extra)
                self.assertEqual(value, text)
                self.assertEqual(value.encode('utf-8', 'surrogatepass'), encoded)

    def test_subclass_from_writable_fsr(self):
        for ch in (ord('a'), ord('é'), ord('日'), ord('😀'), 0xd800):
            source = _testcapi.unicode_new(3, ch)
            value = Str(source)
            self.assertEqual(value, chr(ch) * 3)
            self.assertEqual(_testcapi.unicode_storage(value)[0], ch >= 128)
            self.assertEqual(_testcapi.unicode_storage(value)[3], ch < 128)

    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi')
    def test_subclass_from_overestimated_fsr(self):
        for text in ('a', 'é', '日', '\udcff'):
            source, _ = _testlimitedcapi.unicode_writechar('😀', 0, ord(text))
            value = Str(source)
            self.assertEqual(value, text)
            self.assertEqual(value.isascii(), text.isascii())
            self.assertIn(value, text)
            self.assertEqual(hash(value), hash(text))
            self.assertEqual(_testcapi.unicode_storage(value)[2], text == '\udcff')

    def test_widechar_cursor_conversion(self):
        api = import_helper.import_module('_testlimitedcapi')
        width = _testcapi.SIZEOF_WCHAR_T
        encoding = 'utf-16-le' if width == 2 else 'utf-32-le'
        for text in ('é日😀', 'a\0b', '\ud800x\udcff', 'éÿ'):
            encoded = text.encode(encoding, 'surrogatepass')
            units = len(encoded) // width
            for factory in (self.make_string, Str):
                for cached in (False, True):
                    value = factory(text)
                    if cached:
                        _testcapi.unicode_materialize_fsr(value)
                    before = _testcapi.unicode_storage(value)
                    self.assertEqual(api.unicode_aswidechar_null(value, 0), units + 1)
                    for capacity in range(units + 2):
                        expected = encoded[:capacity * width]
                        if capacity > units:
                            expected += bytes(width)
                        self.assertEqual(api.unicode_aswidechar(value, capacity),
                                         (expected.decode(encoding, 'surrogatepass'),
                                          min(capacity, units)))
                    self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_newline_decoder_without_fsr(self):
        import _io

        text = 'é\r\n日\r😀\n\ud800\udcff\0\r'
        for translate in (False, True):
            expected = text.replace('\r\n', '\n').replace('\r', '\n') if translate else text
            for factory in (self.make_string, Str):
                for split in range(len(text) + 1):
                    decoder = _io.IncrementalNewlineDecoder(None, translate)
                    chunks = [factory(text[:split]), factory(text[split:])]
                    before = [_testcapi.unicode_storage(s) for s in chunks]
                    result = decoder.decode(chunks[0], False)
                    result += decoder.decode(chunks[1], True)
                    self.assertEqual(result, expected)
                    self.assertEqual(decoder.newlines, ('\r', '\n', '\r\n'))
                    self.assertEqual([_testcapi.unicode_storage(s) for s in chunks], before)

    def test_charmap_replacement_without_fsr(self):
        import codecs

        mapping = {ord('é'): 1, ord('😀'): 2, ord('\udcff'): 3}
        for factory in (self.make_string, Str):
            replacement = factory('é😀\udcff')
            before = _testcapi.unicode_storage(replacement)
            def handler(exc):
                return replacement, exc.end
            codecs.register_error('test_utf8_charmap_replacement', handler)
            self.assertEqual(codecs.charmap_encode(
                '日', 'test_utf8_charmap_replacement', mapping),
                (b'\x01\x02\x03', 1))
            self.assertEqual(_testcapi.unicode_storage(replacement), before)
            with self.assertRaises(UnicodeEncodeError):
                codecs.charmap_encode('日', 'test_utf8_charmap_replacement', {})
            self.assertEqual(_testcapi.unicode_storage(replacement), before)

    def test_copy_utf8_storage(self):
        for text in ('é日😀', 'a\0b', 'x\ud800\udcff'):
            for factory in (self.make_string, Str):
                for cached in (False, True):
                    value = factory(text)
                    if cached:
                        _testcapi.unicode_materialize_fsr(value)
                    before = _testcapi.unicode_storage(value)
                    copy, = value.__getnewargs__()
                    self.assertEqual(copy, value)
                    self.assertIs(type(copy), str)
                    self.assertIsNot(copy, value)
                    self.assertEqual(_testcapi.unicode_storage(value), before)
                    if not copy.isascii():
                        self.assertEqual(_testcapi.unicode_storage(copy)[0], 1)
                        self.assertEqual(_testcapi.unicode_storage(copy)[3], 0)

    def test_translate_without_fsr(self):
        api = import_helper.import_module('_testlimitedcapi')
        mapping = {ord('é'): 'é日', ord('日'): None, ord('😀'): None,
                   ord('x'): 0x1f600, ord('y'): ''}
        for text in ('é日😀xy', 'a日z', '\ud800日\udcff', 'xy日'):
            for errors in ('strict', 'ignore', 'replace', 'backslashreplace'):
                for cached in (False, True):
                    with self.subTest(text=ascii(text), errors=errors, cached=cached):
                        value = self.make_string(text)
                        if cached:
                            _testcapi.unicode_materialize_fsr(value)
                        before = _testcapi.unicode_storage(value)
                        try:
                            expected = api.unicode_translate(Str(text), mapping, errors)
                        except UnicodeTranslateError:
                            with self.assertRaises(UnicodeTranslateError):
                                api.unicode_translate(value, mapping, errors)
                        else:
                            self.assertEqual(api.unicode_translate(value, mapping, errors),
                                             expected)
                        self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_translate_utf8_rewind(self):
        import codecs
        api = import_helper.import_module('_testlimitedcapi')
        for materialize in (False, True):
            value = self.make_string('é日😀z')
            calls = []
            def handler(exc):
                calls.append((exc.start, exc.end))
                if materialize:
                    _testcapi.unicode_materialize_fsr(value)
                return '<>', 0 if len(calls) == 1 else exc.end
            codecs.register_error('test_utf8_translate_rewind', handler)
            self.assertEqual(api.unicode_translate(
                value, {ord('日'): None, ord('😀'): None},
                'test_utf8_translate_rewind'), 'é<>é<>z')
            self.assertEqual(calls, [(1, 3), (1, 3)])
            self.assertEqual(_testcapi.unicode_storage(value)[3], materialize)

    def test_unicode_error_display_without_fsr(self):
        for char, escaped in (('é', r'\xe9'), ('日', r'\u65e5'),
                              ('😀', r'\U0001f600'), ('\udcff', r'\udcff')):
            for factory in (self.make_string, Str):
                value = factory('ab' + char + 'z')
                before = _testcapi.unicode_storage(value)
                encode = UnicodeEncodeError('ascii', value, 2, 3, 'reason')
                translate = UnicodeTranslateError(value, 2, 3, 'reason')
                self.assertEqual(str(encode),
                                 f"'ascii' codec can't encode character '{escaped}' "
                                 "in position 2: reason")
                self.assertEqual(str(translate),
                                 f"can't translate character '{escaped}' "
                                 "in position 2: reason")
                self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_utf8_surrogate_encoding_without_fsr(self):
        for text in ('é日😀', 'é\ud800\udcffz', '\udc80\udcff\ud800',
                     '\ud800' * 100, '😀\ud800日\udcff'):
            for errors in ('strict', 'replace', 'ignore', 'surrogatepass',
                           'surrogateescape', 'backslashreplace', 'xmlcharrefreplace'):
                for cached in (False, True):
                    with self.subTest(text=ascii(text), errors=errors, cached=cached):
                        value = self.make_string(text)
                        if cached:
                            _testcapi.unicode_materialize_fsr(value)
                        before = _testcapi.unicode_storage(value)
                        try:
                            expected = Str(text).encode('utf-8', errors)
                        except UnicodeEncodeError as exc:
                            with self.assertRaises(UnicodeEncodeError) as caught:
                                value.encode('utf-8', errors)
                            self.assertEqual((caught.exception.start, caught.exception.end),
                                             (exc.start, exc.end))
                        else:
                            self.assertEqual(value.encode('utf-8', errors), expected)
                        self.assertEqual(_testcapi.unicode_storage(value), before)
            if any(0xd800 <= ord(ch) <= 0xdfff for ch in text):
                value = self.make_string(text)
                before = _testcapi.unicode_storage(value)
                with self.assertRaises(UnicodeEncodeError):
                    _testcapi.unicode_asutf8(value, 0)
                self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_utf8_surrogate_encoding_rewind(self):
        import codecs

        for replacement in ('x', b'x'):
            for materialize in (False, True):
                value = self.make_string('é\ud800\udcff😀z')
                calls = []
                def handler(exc):
                    calls.append((exc.start, exc.end))
                    if materialize:
                        _testcapi.unicode_materialize_fsr(value)
                    return replacement, 0 if len(calls) == 1 else exc.end
                codecs.register_error('test_utf8_surrogate_rewind', handler)
                self.assertEqual(value.encode('utf-8', 'test_utf8_surrogate_rewind'),
                                 'éxéx😀z'.encode())
                self.assertEqual(calls, [(1, 3), (1, 3)])
                self.assertEqual(_testcapi.unicode_storage(value)[3], materialize)

    def test_utf16_utf32_encode_without_fsr(self):
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be',
                         'utf-32', 'utf-32-le', 'utf-32-be'):
            for text in ('éÿ', 'a日😀b', '\ud800日\udcff', '😀\0日'):
                for errors in ('strict', 'ignore', 'replace', 'backslashreplace',
                               'surrogatepass'):
                    for cached in (False, True):
                        with self.subTest(encoding=encoding, text=ascii(text),
                                          errors=errors, cached=cached):
                            value = self.make_string(text)
                            if cached:
                                _testcapi.unicode_materialize_fsr(value)
                            before = _testcapi.unicode_storage(value)
                            try:
                                expected = Str(text).encode(encoding, errors)
                            except UnicodeEncodeError:
                                with self.assertRaises(UnicodeEncodeError):
                                    value.encode(encoding, errors)
                            else:
                                self.assertEqual(value.encode(encoding, errors), expected)
                            self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_utf16_utf32_encode_utf8_rewind(self):
        import codecs

        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be',
                         'utf-32', 'utf-32-le', 'utf-32-be'):
            raw_encoding = encoding
            if encoding in ('utf-16', 'utf-32'):
                raw_encoding += '-le' if sys.byteorder == 'little' else '-be'
            for replacement in ('x', 'x'.encode(raw_encoding)):
                for materialize in (False, True):
                    value = self.make_string('日\ud800😀\udcff')
                    calls = []
                    def handler(exc):
                        calls.append((exc.start, exc.end))
                        if materialize:
                            _testcapi.unicode_materialize_fsr(value)
                        return replacement, 0 if len(calls) == 1 else exc.end
                    codecs.register_error('test_utf8_utf16_utf32_rewind', handler)
                    self.assertEqual(value.encode(encoding, 'test_utf8_utf16_utf32_rewind'),
                                     '日x日x😀x'.encode(encoding))
                    self.assertEqual(calls, [(1, 2), (1, 2), (3, 4)])
                    self.assertEqual(_testcapi.unicode_storage(value)[3], materialize)

    def test_utf16_rewind_nonbmp_capacity(self):
        import codecs

        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be'):
            for cached in (False, True):
                value = self.make_string('😀' * 1000 + '\ud800')
                if cached:
                    _testcapi.unicode_materialize_fsr(value)
                calls = []
                def handler(exc):
                    calls.append((exc.start, exc.end))
                    return 'x', 0 if len(calls) == 1 else exc.end
                codecs.register_error('test_utf16_nonbmp_capacity', handler)
                self.assertEqual(value.encode(encoding, 'test_utf16_nonbmp_capacity'),
                                 (('😀' * 1000 + 'x') * 2).encode(encoding))
                self.assertEqual(calls, [(1000, 1001), (1000, 1001)])

    def test_charmap_encode_without_fsr(self):
        import codecs

        table = ''.join(map(chr, range(256)))
        mappings = (codecs.charmap_build(table),
                    dict(zip(map(ord, table), range(256))))
        for mapping in mappings:
            for text in ('éÿ', 'a日😀b', '\ud800日é\udcff', '日' * 100):
                for errors in ('strict', 'ignore', 'replace', 'backslashreplace',
                               'xmlcharrefreplace'):
                    with self.subTest(text=ascii(text), errors=errors, mapping=type(mapping)):
                        value = self.make_string(text)
                        before = _testcapi.unicode_storage(value)
                        try:
                            expected = codecs.charmap_encode(Str(text), errors, mapping)
                        except UnicodeEncodeError:
                            with self.assertRaises(UnicodeEncodeError):
                                codecs.charmap_encode(value, errors, mapping)
                        else:
                            self.assertEqual(codecs.charmap_encode(value, errors, mapping),
                                             expected)
                        self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_charmap_encode_utf8_rewind(self):
        import codecs

        table = ''.join(map(chr, range(256)))
        mappings = (codecs.charmap_build(table),
                    dict(zip(map(ord, table), range(256))))
        for mapping in mappings:
            for replacement in ('é', b'!'):
                for materialize in (False, True):
                    value = self.make_string('é日😀z')
                    calls = []
                    def handler(exc):
                        calls.append((exc.start, exc.end))
                        if materialize:
                            _testcapi.unicode_materialize_fsr(value)
                        return replacement, 0 if len(calls) == 1 else exc.end
                    codecs.register_error('test_utf8_charmap_rewind', handler)
                    encoded = (replacement.encode('latin1')
                               if isinstance(replacement, str) else replacement)
                    self.assertEqual(codecs.charmap_encode(
                        value, 'test_utf8_charmap_rewind', mapping),
                        ((b'\xe9' + encoded) * 2 + b'z', 4))
                    self.assertEqual(calls, [(1, 3), (1, 3)])
                    self.assertEqual(_testcapi.unicode_storage(value)[3], materialize)

    def test_charmap_default_without_fsr(self):
        import codecs

        for text in ('éÿ', 'a日😀b', 'a\udc80\udcffz'):
            for errors in ('strict', 'replace', 'ignore', 'backslashreplace',
                           'xmlcharrefreplace', 'surrogateescape'):
                with self.subTest(text=ascii(text), errors=errors):
                    value = self.make_string(text)
                    before = _testcapi.unicode_storage(value)
                    try:
                        expected = text.encode('latin1', errors)
                    except UnicodeEncodeError:
                        with self.assertRaises(UnicodeEncodeError):
                            codecs.charmap_encode(value, errors, None)
                    else:
                        self.assertEqual(codecs.charmap_encode(value, errors, None),
                                         (expected, len(value)))
                    self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_ucs1_encode_without_fsr(self):
        import codecs

        for encoding in ('ascii', 'latin1'):
            for errors in ('replace', 'ignore', 'backslashreplace',
                           'xmlcharrefreplace', 'surrogateescape'):
                for text in ('éÿ', 'a日😀b日', 'a\udc80\udcffz', '\0日'):
                    value = self.make_string(text)
                    before = _testcapi.unicode_storage(value)
                    try:
                        expected = text.encode(encoding, errors)
                    except UnicodeEncodeError:
                        with self.assertRaises(UnicodeEncodeError):
                            value.encode(encoding, errors)
                    else:
                        self.assertEqual(value.encode(encoding, errors), expected)
                    self.assertEqual(_testcapi.unicode_storage(value), before)

        calls = []
        replacement = self.make_string('éÿ')
        def handler(exc):
            calls.append((exc.start, exc.end))
            return replacement, 0 if len(calls) == 1 else exc.end
        codecs.register_error('test_utf8_ucs1_rewind', handler)
        value = self.make_string('a日b')
        self.assertEqual(value.encode('latin1', 'test_utf8_ucs1_rewind'),
                         b'a\xe9\xffa\xe9\xffb')
        self.assertEqual(calls, [(1, 2), (1, 2)])
        self.assertEqual(_testcapi.unicode_storage(value)[3], 0)
        self.assertEqual(_testcapi.unicode_storage(replacement)[3], 0)

    def test_codec_replacement_utf8_output(self):
        import codecs

        for size in (0, 1, 5):
            exc = UnicodeTranslateError('日' * size, 0, size, 'test')
            result, end = codecs.replace_errors(exc)
            self.assertEqual(result, '\ufffd' * size)
            self.assertEqual(end, size)
            if size:
                self.assertEqual(_testcapi.unicode_storage(result)[0], 1)
                self.assertEqual(_testcapi.unicode_storage(result)[3], 0)
            exc = UnicodeEncodeError('ascii', '日' * size, 0, size, 'test')
            self.assertEqual(codecs.replace_errors(exc), ('?' * size, size))

    def test_whitespace_split_utf8_views(self):
        text = '\u2003é\t日\x85😀\r\n\udcff\u3000'
        words = ['é', '日', '😀', '\udcff']
        for factory in (self.make_string, Str):
            for cached in (False, True):
                value = factory(text)
                if cached:
                    _testcapi.unicode_materialize_fsr(value)
                before = _testcapi.unicode_storage(value)
                self.assertEqual(value.split(), words)
                self.assertEqual(value.rsplit(), words)
                self.assertEqual(value.split(None, 0), [text[1:]])
                self.assertEqual(value.rsplit(None, 0), [text[:-1]])
                self.assertEqual(value.split(None, 1), ['é', text[3:]])
                self.assertEqual(value.rsplit(None, 1), [text[:-4], '\udcff'])
                self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_splitlines_utf8_views(self):
        endings = ('\n', '\r', '\r\n', '\v', '\f', '\x1c', '\x1d',
                   '\x1e', '\x85', '\u2028', '\u2029')
        line = 'é日😀\udcff\0'
        text = ''.join(line + ending for ending in endings) + line
        for factory in (self.make_string, Str):
            for materialize in (False, True):
                value = factory(text)
                if materialize:
                    _testcapi.unicode_materialize_fsr(value)
                before = _testcapi.unicode_storage(value)
                self.assertEqual(value.splitlines(), [line] * (len(endings) + 1))
                self.assertEqual(value.splitlines(True),
                                 [line + end for end in endings] + [line])
                self.assertEqual(_testcapi.unicode_storage(value), before)
                for short_text, expected in (('', []), ('\r\n', ['']),
                                             ('\r\r\n', ['', '']),
                                             ('日', ['日'])):
                    self.assertEqual(factory(short_text).splitlines(), expected)

    def test_zfill_utf8(self):
        cases = [('', 1, '0'), ('+', 3, '+00'), ('-', 1, '-'),
                 ('-12', 5, '-0012'), ('+é日😀', 7, '+000é日😀'),
                 ('-\udcff', 4, '-00\udcff'), ('\ud800', 3, '00\ud800'),
                 ('\0+', 4, '00\0+'), ('−12', 5, '00−12')]
        for text, width, expected in cases:
            for factory in (self.make_string, Str):
                for materialize in (False, True):
                    with self.subTest(text=text, factory=factory,
                                      materialize=materialize):
                        value = factory(text)
                        if materialize:
                            _testcapi.unicode_materialize_fsr(value)
                        before = _testcapi.unicode_storage(value)
                        result = value.zfill(width)
                        self.assertEqual(result, expected)
                        self.assertIs(type(result), str)
                        self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_specialized_iteration_without_fsr(self):
        def collect(value, materialize):
            result = []
            for ch in value:
                result.append(ch)
                if materialize and len(result) == 1:
                    _testcapi.unicode_materialize_fsr(value)
            return result

        def delegate(value):
            yield from value

        for _ in range(100):
            collect('warmup', False)
            list(delegate('warmup'))
        for text in ('', 'a\0z', 'é日😀', '\ud800x\udcff'):
            expected = [text[i] for i in range(len(text))]
            for factory in (self.make_string, Str):
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                self.assertEqual(collect(value, False), expected)
                self.assertEqual(list(delegate(value)), expected)
                self.assertEqual(_testcapi.unicode_storage(value), before)
                self.assertEqual(collect(value, True), expected)
                self.assertEqual(collect(value, False), expected)
                self.assertEqual(list(delegate(value)), expected)

    def test_equal_utf8_fallback(self):
        api = import_helper.import_module('_testlimitedcapi')
        equal = api.unicode_equaltoutf8andsize
        for text in ('a\0é߿ࠀ日😀\U0010ffff', '\ud800', 'é\udcff'):
            for factory in (self.make_string, Str):
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                encoded = text.encode('utf-8', 'surrogatepass')
                valid = not any(0xd800 <= ord(ch) <= 0xdfff for ch in text)
                self.assertEqual(equal(value, encoded), valid)
                for i in range(len(encoded)):
                    self.assertEqual(equal(value, encoded[:i]), 0)
                    changed = encoded[:i] + bytes([encoded[i] ^ 0x80]) + encoded[i+1:]
                    self.assertEqual(equal(value, changed), 0)
                self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_ast_percent_format_without_fsr(self):
        import ast

        for text in ('日😀%s\udcff', '\ud800%% %r末'):
            value = self.make_string(text)
            tree = ast.parse("'template' % (x,)", mode='eval')
            tree.body.left.value = value
            before = _testcapi.unicode_storage(value)
            code = compile(tree, '<test>', 'eval')
            self.assertEqual(_testcapi.unicode_storage(value), before)
            self.assertEqual(eval(code, {'x': 'é😀'}), text % ('é😀',))

    def test_format_spec_without_fsr(self):
        cases = [('日', '😀>４', '😀😀😀日'),
                 (42, '\udcff>５d', '\udcff' * 3 + '42'),
                 (1.25, '>８.１f', '     1.2'),
                 (42, '０' * 10000 + '５d', '   42')]
        for value, text, expected in cases:
            for factory in (self.make_string, Str):
                spec = factory(text)
                before = _testcapi.unicode_storage(spec)
                self.assertEqual(format(value, spec), expected)
                self.assertEqual(_testcapi.unicode_storage(spec), before)
        for text in ('😀>４xx', '>１２.日f', '９' * 100):
            spec = self.make_string(text)
            before = _testcapi.unicode_storage(spec)
            with self.assertRaises(ValueError):
                format(42, spec)
            self.assertEqual(_testcapi.unicode_storage(spec), before)

    def test_marshal_without_fsr(self):
        import marshal

        for text in ('ascii', 'a' * 300, 'é日😀', 'a\0b', '\ud800\udcff'):
            for version in range(marshal.version + 1):
                with self.subTest(text=text, version=version):
                    value = self.make_string(text)
                    before = _testcapi.unicode_storage(value)
                    encoded = marshal.dumps(value, version)
                    self.assertEqual(marshal.loads(encoded), value)
                    self.assertEqual(_testcapi.unicode_storage(value), before)
                    if version == 0:
                        payload = text.encode('utf-8', 'surrogatepass')
                        self.assertEqual(encoded, b'u' +
                                         len(payload).to_bytes(4, 'little') + payload)

    def test_maketrans_without_fsr(self):
        for factory in (self.make_string, Str):
            with self.subTest(factory=factory):
                x = factory('é日😀\ud800é')
                y = factory('a語\udcff😀b')
                z = factory('日\ud800')
                before = [_testcapi.unicode_storage(v) for v in (x, y, z)]
                self.assertEqual(str.maketrans(x, y, z), {
                    ord('é'): ord('b'), ord('日'): None,
                    ord('😀'): ord('\udcff'), ord('\ud800'): None,
                })
                self.assertEqual([_testcapi.unicode_storage(v)
                                  for v in (x, y, z)], before)
        for text in ('日', '😀', '\ud800', '\udcff'):
            key = self.make_string(text)
            self.assertEqual(str.maketrans({key: 'value'}),
                             {ord(text): 'value'})
            self.assertEqual(_testcapi.unicode_storage(key)[3], 0)

    def test_numeric_input_without_fsr(self):
        for convert, text, expected in (
            (int, '\u2003-１２٣\u2002', -123),
            (float, '\u2003１２.٥\u2002', 12.5),
            (complex, '１２+٣j', 12+3j),
        ):
            for factory in (self.make_string, Str):
                with self.subTest(convert=convert, factory=factory):
                    value = factory(text)
                    before = _testcapi.unicode_storage(value)
                    self.assertEqual(convert(value), expected)
                    self.assertEqual(_testcapi.unicode_storage(value), before)
        for text in ('１２\ud800', '１２日', '１２\x7f'):
            value = self.make_string(text)
            with self.assertRaises(ValueError):
                int(value)
            self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    def test_syntaxerror_basename_without_fsr(self):
        import os
        for tail in ('file.py', '日😀\udcff.py', ''):
            for factory in (self.make_string, Str):
                with self.subTest(tail=ascii(tail), factory=factory):
                    filename = factory(os.sep.join(('日', '😀', tail)))
                    before = _testcapi.unicode_storage(filename)
                    error = SyntaxError('bad', (filename, 3, 1, 'x'))
                    self.assertEqual(str(error), f'bad ({tail}, line 3)')
                    self.assertEqual(_testcapi.unicode_storage(filename), before)

    def test_encode_and_ucs4_without_fsr(self):
        for text in ('café', '日😀', 'a\0b', 'a\ud800\udcffb'):
            for factory in (self.make_string, Str):
                for encoding in ('utf-7', 'unicode_escape', 'raw_unicode_escape'):
                    with self.subTest(text=ascii(text), factory=factory,
                                      encoding=encoding):
                        value = factory(text)
                        before = _testcapi.unicode_storage(value)
                        self.assertEqual(value.encode(encoding), text.encode(encoding))
                        self.assertEqual(_testcapi.unicode_storage(value), before)
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                self.assertEqual(_testcapi.unicode_asucs4copy(value), text + '\0')
                self.assertEqual(_testcapi.unicode_asucs4(value, len(text), 1),
                                 text + '\0')
                self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_fromhex_without_fsr(self):
        for cls in (bytes, bytearray):
            for factory in (self.make_string, Str):
                for char in ('é', '日', '😀', '\udcff'):
                    value = factory('00 12' + char + '34')
                    before = _testcapi.unicode_storage(value)
                    with self.assertRaisesRegex(ValueError, 'position 5'):
                        cls.fromhex(value)
                    self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_single_character_consumers_without_fsr(self):
        for text in ('日', '😀', '\ud800', '\udcff'):
            for factory in (self.make_string, Str):
                with self.subTest(text=ascii(text), factory=factory):
                    value = factory(text)
                    before = _testcapi.unicode_storage(value)
                    self.assertEqual(_testcapi.getargs_C(value), ord(text))
                    self.assertEqual('%c' % value, text)
                    self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_module_consumers_without_fsr(self):
        import datetime
        import operator
        import types

        for factory in (self.make_string, Str):
            for text in ('日.😀', '.日', '日.', '日..😀', '日.\udcff'):
                with self.subTest(text=ascii(text), factory=factory):
                    root = types.SimpleNamespace()
                    obj = root
                    parts = text.split('.')
                    for name in parts[:-1]:
                        child = types.SimpleNamespace()
                        setattr(obj, name, child)
                        obj = child
                    setattr(obj, parts[-1], 42)
                    value = factory(text)
                    before = _testcapi.unicode_storage(value)
                    self.assertEqual(operator.attrgetter(value)(root), 42)
                    self.assertEqual(_testcapi.unicode_storage(value)[:4], before[:4])
            for separator in ('日', '😀', '\ud800', '\udcff'):
                value = factory('2026-01-02' + separator + '03:04:05')
                before = _testcapi.unicode_storage(value)
                self.assertEqual(datetime.datetime.fromisoformat(value),
                                 datetime.datetime(2026, 1, 2, 3, 4, 5))
                self.assertEqual(_testcapi.unicode_storage(value)[:4], before[:4])

    def test_json_without_fsr(self):
        import json
        _json = import_helper.import_module('_json')
        scanner = _json.make_scanner(json.JSONDecoder())
        for factory in (self.make_string, Str):
            for text in ('café', '日😀', 'a\0\nb', '\ud800\udcff', '"\\日'):
                with self.subTest(factory=factory, text=ascii(text)):
                    value = factory(text)
                    before = _testcapi.unicode_storage(value)
                    for ascii_only, encode in (
                        (False, _json.encode_basestring),
                        (True, _json.encode_basestring_ascii),
                    ):
                        encoded = encode(value)
                        encode_python = (json.encoder.py_encode_basestring_ascii
                                         if ascii_only else
                                         json.encoder.py_encode_basestring)
                        expected = encode_python(text)
                        self.assertEqual(encoded, expected)
                        self.assertEqual(json.dumps(value, ensure_ascii=ascii_only),
                                         expected)
                        document = factory('日😀[' + encoded + ',12.5,true]')
                        doc_before = _testcapi.unicode_storage(document)
                        decoded = json.decoder.py_scanstring(expected, 1)[0]
                        self.assertEqual(scanner(document, 2),
                                         ([decoded, 12.5, True], len(document)))
                        self.assertEqual(_testcapi.unicode_storage(document),
                                         doc_before)
                    self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_json_escape_boundaries(self):
        import json
        _json = import_helper.import_module('_json')
        text = (''.join(map(chr, range(32))) + '"\\' +
                '\x7f\x80\u07ff\u0800\ud7ff\ud800\udfff\ue000\uffff'
                '\U00010000\U0010ffff')
        for repeat in (1, 31):
            value = self.make_string(text * repeat)
            for ascii_only, encode, reference in (
                (False, _json.encode_basestring,
                 json.encoder.py_encode_basestring),
                (True, _json.encode_basestring_ascii,
                 json.encoder.py_encode_basestring_ascii),
            ):
                with self.subTest(repeat=repeat, ascii_only=ascii_only):
                    expected = reference(text * repeat)
                    self.assertEqual(encode(value), expected)
                    self.assertEqual(
                        json.dumps([value, value], ensure_ascii=ascii_only),
                        '[' + expected + ', ' + expected + ']')
                    self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    def test_json_hooks_without_fsr(self):
        import json
        _json = import_helper.import_module('_json')
        for factory in (self.make_string, Str):
            value = factory('{"日":[12,1.5,NaN],"😀":"\udcff"}')
            before = _testcapi.unicode_storage(value)
            decoder = json.JSONDecoder(parse_int=str, parse_float=str,
                                       parse_constant=str,
                                       object_pairs_hook=tuple,
                                       array_hook=tuple)
            self.assertEqual(_json.make_scanner(decoder)(value, 0),
                             ((("日", ("12", "1.5", "NaN")),
                               ("😀", "\udcff")), len(value)))
            self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_json_character_offsets(self):
        import json
        _json = import_helper.import_module('_json')
        scanner = _json.make_scanner(json.JSONDecoder())
        for document, position in (
            ('["日😀",]', 5),
            ('{"日😀":0,}', 7),
            ('["日😀",?]', 6),
        ):
            value = self.make_string(document)
            try:
                scanner(value, 0)
            except json.JSONDecodeError as exc:
                self.assertEqual(exc.pos, position)
                self.assertIs(exc.doc, value)
            except StopIteration as exc:
                self.assertEqual(exc.value, position)
            else:
                self.fail('invalid JSON accepted')
            self.assertEqual(_testcapi.unicode_storage(value)[3], 0)
        value = self.make_string('日😀"a\\n語"tail')
        self.assertEqual(_json.scanstring(value, 3), ('a\n語', 8))
        self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    def test_json_invalid_escape_offsets(self):
        import json
        _json = import_helper.import_module('_json')
        for document, message, position in (
            ('"日\\u12語4"', 'Invalid \\uXXXX escape', 3),
            ('"日\\ud800\\u日"', 'Invalid \\uXXXX escape', 9),
            ('"日\n"', 'Invalid control character at', 2),
            ('"日\\q"', 'Invalid \\escape', 2),
            ('日😀', 'Unterminated string starting at', 0),
        ):
            with self.subTest(document=ascii(document)):
                value = self.make_string(document)
                with self.assertRaises(json.JSONDecodeError) as caught:
                    _json.scanstring(value, 1)
                self.assertEqual(caught.exception.msg, message)
                self.assertEqual(caught.exception.pos, position)
                self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    @unittest.skipIf(_testinternalcapi is None, 'need _testinternalcapi')
    def test_next_cursor(self):
        for text in ('', 'ascii', 'a\0é日😀\ud800\udcffz'):
            for factory in (self.make_string, Str):
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                pos = 0
                for ch in text:
                    saved = pos
                    result, pos = _testinternalcapi.unicode_next(value, pos)
                    self.assertEqual(result, ord(ch))
                    self.assertEqual(_testinternalcapi.unicode_next(value, saved),
                                     (result, pos))
                self.assertEqual(_testinternalcapi.unicode_next(value, pos),
                                 (None, pos))
                self.assertEqual(_testcapi.unicode_storage(value), before)
        value = self.make_string('日😀\udcff')
        self.assertEqual(_testinternalcapi.unicode_next(value, 0), (ord('日'), 3))
        self.assertEqual(_testinternalcapi.unicode_next(value, 3, True),
                         (ord('😀'), 7))
        self.assertEqual(_testinternalcapi.unicode_next(value, 7), (0xdcff, 10))
        self.assertEqual(_testinternalcapi.unicode_next(value, 10), (None, 10))

    @unittest.skipIf(_testinternalcapi is None, 'need _testinternalcapi')
    def test_utf8_view(self):
        for text in ('', 'ascii', 'é日😀\0\ud800\udcff'):
            for factory in (self.make_string, Str):
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                data, borrowed = _testinternalcapi.unicode_utf8_view(value)
                self.assertEqual(data, text.encode('utf-8', 'surrogatepass'))
                self.assertTrue(borrowed)
                self.assertEqual(_testcapi.unicode_storage(value), before)
                self.assertEqual(_testinternalcapi.unicode_utf8_view(value, True),
                                 (data, borrowed))

    @unittest.skipIf(_testinternalcapi is None, 'need _testinternalcapi')
    def test_utf8_view_writable_fsr(self):
        for ch in (ord('é'), ord('日'), ord('😀'), 0xd800):
            value = _testcapi.unicode_new(3, ch)
            before = _testcapi.unicode_storage(value)
            data, borrowed = _testinternalcapi.unicode_utf8_view(value)
            self.assertEqual(data, (chr(ch) * 3).encode('utf-8', 'surrogatepass'))
            self.assertFalse(borrowed)
            self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_codec_handlers_without_fsr(self):
        import codecs
        for handler in (codecs.namereplace_errors,
                        codecs.xmlcharrefreplace_errors,
                        codecs.backslashreplace_errors,
                        codecs.lookup_error('surrogatepass'),
                        codecs.lookup_error('surrogateescape')):
            for factory in (self.make_string, Str):
                value = factory('日😀\udc80\udcffz')
                before = _testcapi.unicode_storage(value)
                error = UnicodeEncodeError('utf-8', value, 2, 4, 'test')
                expected = handler(UnicodeEncodeError(
                    'utf-8', Str('日😀\udc80\udcffz'), 2, 4, 'test'))
                self.assertEqual(handler(error), expected)
                self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_csv_without_fsr(self):
        import csv
        import io
        for factory in (self.make_string, Str):
            for text in ('日😀', '日,"😀', '日\n😀', '日\0\udcff'):
                value = factory(text)
                ending = factory('終\r\n')
                before = [_testcapi.unicode_storage(v) for v in (value, ending)]
                output = io.StringIO()
                csv.writer(output, lineterminator=ending).writerow([value])
                expected = ('"' + text.replace('"', '""') + '"'
                            if any(c in text for c in ',"\n') else text)
                self.assertEqual(output.getvalue(), expected + ending)
                line = factory(expected + '\r\n')
                line_before = _testcapi.unicode_storage(line)
                self.assertEqual(list(csv.reader([line])), [[text]])
                self.assertEqual(_testcapi.unicode_storage(line), line_before)
                self.assertEqual([_testcapi.unicode_storage(v)
                                  for v in (value, ending)], before)

    def test_pickle_and_strftime_without_fsr(self):
        import pickle
        import time
        value = self.make_string('日😀\0\n\r\\\x1a\ud800\udcff')
        self.assertEqual(pickle.loads(pickle.dumps(value, protocol=0)), value)
        self.assertEqual(_testcapi.unicode_storage(value)[3], 0)
        for factory in (self.make_string, Str):
            value = factory('日%Y😀\0%m\udcff%%')
            before = _testcapi.unicode_storage(value)
            self.assertEqual(time.strftime(value, (2026, 9, 20, 1, 2, 3, 6, 263, 0)),
                             '日2026😀\0' '09\udcff%')
            self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_encoding_map_without_fsr(self):
        import codecs
        for first, last in (('\0', '日'), ('X', '日'), ('\0', '😀')):
            for factory in (self.make_string, Str):
                table = factory(first + ''.join(map(chr, range(1, 255))) + last)
                before = _testcapi.unicode_storage(table)
                mapping = codecs.charmap_build(table)
                self.assertEqual(codecs.charmap_encode(last, 'strict', mapping),
                                 (b'\xff', 1))
                self.assertEqual(_testcapi.unicode_storage(table), before)

    def test_expat_encoding_table_without_fsr(self):
        import codecs
        expat = import_helper.import_module('pyexpat')
        table = self.make_string(''.join(map(chr, range(128))) + '日' +
                                 ''.join(map(chr, range(129, 256))))
        def decode(data, errors='strict'):
            self.assertEqual(bytes(data), bytes(range(256)))
            return table, 256
        def search(name):
            if name == 'test_utf8_cursor_expat':
                return codecs.CodecInfo(name=name, encode=codecs.latin_1_encode,
                                        decode=decode)
        codecs.register(search)
        try:
            parser = expat.ParserCreate('test_utf8_cursor_expat')
            output = []
            parser.CharacterDataHandler = output.append
            parser.Parse(b'<x>\x80</x>', True)
            self.assertEqual(output, ['日'])
            self.assertEqual(_testcapi.unicode_storage(table)[3], 0)
        finally:
            codecs.unregister(search)

    def test_normalization_without_fsr(self):
        ud = import_helper.import_module('unicodedata')
        for database in (ud, ud.ucd_3_2_0):
            for text in ('日😀', 'a\u0315\u0300', '\uac01', '\ufdfa',
                         'x\ud800\udcff'):
                for form in ('NFC', 'NFD', 'NFKC', 'NFKD'):
                    expected = database.normalize(form, text)
                    for factory in (self.make_string, Str):
                        value = factory(text)
                        before = _testcapi.unicode_storage(value)
                        self.assertEqual(database.normalize(form, value), expected)
                        self.assertEqual(database.is_normalized(form, value),
                                         expected == text)
                        self.assertEqual(_testcapi.unicode_storage(value), before)
        for text, category in (('日', 'Lo'), ('😀', 'So'), ('\udcff', 'Cs')):
            value = self.make_string(text)
            self.assertEqual(ud.category(value), category)
            self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    def test_graphemes_without_fsr(self):
        ud = import_helper.import_module('unicodedata')
        pieces = ['a\u0301', '🇯🇵', '👩\u200d💻', '\r\n', '\udcff']
        for factory in (self.make_string, Str):
            value = factory(''.join(pieces))
            before = _testcapi.unicode_storage(value)
            self.assertEqual(list(map(str, ud.iter_graphemes(value))), pieces)
            self.assertEqual(list(map(str, ud.iter_graphemes(value, 2, -1))),
                             pieces[1:-1])
            self.assertEqual(list(ud.iter_graphemes(value, PY_SSIZE_T_MAX)), [])
            self.assertEqual(_testcapi.unicode_storage(value), before)
        value = self.make_string(''.join(pieces))
        iterator = ud.iter_graphemes(value)
        self.assertEqual(str(next(iterator)), pieces[0])
        _testcapi.unicode_materialize_fsr(value)
        self.assertEqual(list(map(str, iterator)), pieces[1:])

    def test_decimal_input_without_fsr(self):
        decimal = import_helper.import_module('_decimal')
        for factory in (self.make_string, Str):
            for text, expected in (('\u2003１２_٣.٥\u2002', '123.5'),
                                   ('１２_ ', '12'), ('_１２_', '12')):
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                self.assertEqual(decimal.Decimal(value), decimal.Decimal(expected))
                self.assertEqual(_testcapi.unicode_storage(value), before)
            for text in ('１２ _ ', '１２\u2003_', '１２\0', '１２\udcff'):
                value = factory(text)
                before = _testcapi.unicode_storage(value)
                with self.assertRaises(decimal.InvalidOperation):
                    decimal.Decimal(value)
                self.assertEqual(_testcapi.unicode_storage(value), before)
            value = factory('１２.٥')
            before = _testcapi.unicode_storage(value)
            self.assertEqual(decimal.Context().create_decimal(value),
                             decimal.Decimal('12.5'))
            self.assertEqual(_testcapi.unicode_storage(value), before)

    def test_lazy_fsr(self):
        for text in ('café', '日本語', 'a😀b', 'x\0é', 'a\ud800\udcffb',
                     '\ud800\udc00'):
            with self.subTest(text=ascii(text)):
                value = self.make_string(text)
                before = _testcapi.unicode_storage(value)
                self.assertEqual(before[:4], (1, 1, int(any(
                    0xd800 <= ord(c) <= 0xdfff for c in text)), 0))
                self.assertEqual(before[4], len(text.encode('utf-8', 'surrogatepass')))
                size = value.__sizeof__()
                self.assertEqual(value[1], text[1])
                self.assertEqual(_testcapi.unicode_storage(value)[3], 1)
                self.assertGreater(value.__sizeof__(), size)
                size = value.__sizeof__()
                self.assertEqual(value[-1], text[-1])
                self.assertEqual(value.__sizeof__(), size)

    def test_native_operations(self):
        for text in ('café', '日本語', 'a😀b', 'x\0é', '\ud800\udc00'):
            with self.subTest(text=ascii(text)):
                value = self.make_string(text)
                other = self.make_string(text)
                self.assertEqual(len(value), len(text))
                self.assertEqual(hash(value), hash(other))
                self.assertEqual(value, other)
                self.assertFalse(value < other)
                self.assertEqual(list(value), list(text))
                self.assertEqual([c for c in value], list(text))
                self.assertEqual(value + other, text + text)
                self.assertEqual({value: 42}[other], 42)
                self.assertEqual(_testcapi.unicode_storage(value)[3], 0)
                self.assertEqual(_testcapi.unicode_storage(other)[3], 0)

    def test_surrogate_boundaries(self):
        high = self.make_string('a\ud800')
        low = self.make_string('\udc00b')
        combined = high + low
        self.assertEqual(len(combined), 4)
        self.assertEqual(combined.encode('utf-8', 'surrogatepass'),
                         b'a\xed\xa0\x80\xed\xb0\x80b')
        self.assertRaises(UnicodeEncodeError, combined.encode, 'utf-8')
        self.assertRaises(UnicodeEncodeError, _testcapi.unicode_asutf8, combined, 0)
        raw = b'a\x80\xffb'
        value = raw.decode('utf-8', 'surrogateescape')
        self.assertEqual(_testcapi.unicode_storage(value)[2], 1)
        self.assertEqual(value.encode('utf-8', 'surrogateescape'), raw)

    def test_decoder_native_outputs(self):
        text = '日😀\udcff'
        cases = [(encoding, text.encode(encoding, 'surrogatepass'),
                  'surrogatepass', text)
                 for encoding in ('utf-8', 'utf-7', 'utf-16-le', 'utf-16-be',
                                  'utf-32-le', 'utf-32-be', 'unicode_escape',
                                  'raw_unicode_escape')]
        cases.extend((
            ('ascii', b'x\xff', 'surrogateescape', 'x\udcff'),
            ('utf-8', b'\xe6\x97\xa5\xff', 'replace', '日\ufffd'),
            ('euc_jis_2004', b'\xa4\xf7', 'strict', 'か\u309a'),
        ))
        for encoding, raw, errors, expected in cases:
            with self.subTest(encoding=encoding, errors=errors):
                result = raw.decode(encoding, errors)
                self.assertEqual(result, expected)
                state = _testcapi.unicode_storage(result)
                self.assertEqual((state[0], state[3]), (1, 0))
                self.assertEqual(state[2], int(any(
                    0xd800 <= ord(ch) <= 0xdfff for ch in expected)))

    def test_count_utf8(self):
        for text in ('', 'aaaa', 'ééaé', '日本日本語', '😀a😀',
                     'a\0日本\0', '\ud800\udc00\ud800', 'a\udcffb'):
            chars = list(text)
            for needle in ('', 'a', 'é', '日本', '😀', '\0', '\ud800',
                           '\ud800\udc00', '\udcff'):
                for start, end in ((0, sys.maxsize), (-4, -1), (1, 3),
                                   (0, 0), (50, 60), (3, 1), (-50, 50)):
                    with self.subTest(text=ascii(text), needle=ascii(needle),
                                      start=start, end=end):
                        value = self.make_string(text)
                        sub = self.make_string(needle)
                        before = [_testcapi.unicode_storage(s) for s in (value, sub)]
                        part = chars[start:end]
                        pattern = list(needle)
                        expected = 0
                        if not pattern:
                            expected = (len(part) + 1 if start <= len(chars)
                                        and max(start, 0) <= end else 0)
                            if start < 0 or end < 0:
                                lo, hi, _ = slice(start, end).indices(len(chars))
                                expected = max(hi - lo + 1, 0)
                        else:
                            pos = 0
                            while pos <= len(part) - len(pattern):
                                if part[pos:pos + len(pattern)] == pattern:
                                    expected += 1
                                    pos += len(pattern)
                                else:
                                    pos += 1
                        self.assertEqual(value.count(sub, start, end), expected)
                        self.assertEqual(
                            [_testcapi.unicode_storage(s) for s in (value, sub)], before)

    def test_replace_utf8(self):
        cases = (
            ('日本日本語', '日本', '😀', '😀😀語'),
            ('ééé', 'éé', '日本', '日本é'),
            ('a😀b', '', '日', '日a日😀日b日'),
            ('a\0日\0', '\0', '😀', 'a😀日😀'),
            ('\ud800\udc00', '\ud800', '', '\udc00'),
            ('\ud800x', 'x', '\udc00', '\ud800\udc00'),
            ('a\udcffb', '\udcff', 'x', 'axb'),
            ('a😀a', '😀', '', 'aa'),
            ('日本', '日本', 'é', 'é'),
            ('😀', '😀', '', ''),
            ('日本', 'missing', '😀', '日本'),
            ('', '', '日本', '日本'),
        )
        for text, old, new, expected in cases:
            for limit in (-1, 0, 1, 2, sys.maxsize):
                with self.subTest(text=ascii(text), old=ascii(old), limit=limit):
                    value, sub, replacement = map(self.make_string, (text, old, new))
                    operands = (value, sub, replacement)
                    before = [_testcapi.unicode_storage(s) for s in operands]
                    # Also exercise noncompact UTF-8 input.
                    reference = Str(text).replace(old, new, limit)
                    result = value.replace(sub, replacement, limit)
                    self.assertEqual(result, reference)
                    if limit < 0:
                        self.assertEqual(result, expected)
                    self.assertEqual([_testcapi.unicode_storage(s) for s in operands], before)
                    state = _testcapi.unicode_storage(result)
                    if state[0]:
                        self.assertEqual(state[2], any(
                            0xd800 <= ord(ch) <= 0xdfff for ch in result))
                        if len(result) > 1:
                            self.assertEqual(state[3], 0)
                    self.assertEqual(result.encode('utf-8', 'surrogatepass'),
                                     reference.encode('utf-8', 'surrogatepass'))

    def test_count_replace_mixed_storage(self):
        for ch in (0xe9, 0x65e5, 0xd800, 0x1f600):
            legacy = _testcapi.unicode_new(4, ch)
            compact = self.make_string(chr(ch) * 4)
            for value in (legacy, compact):
                for old in (legacy, compact):
                    self.assertEqual(value.count(old), 1)
                    self.assertEqual(value.replace(old, '日本'), '日本')
                    self.assertEqual(value.replace(old, legacy), compact)

    def test_utf8_search_bounds(self):
        for text in ('', 'abcabc', 'é日本😀日\0\ud800\udc00日', '\udcff日'):
            for needle in ('', '日', '日本', '😀', '\0', '\ud800',
                           '\ud800\udc00', '\udcff', 'absent'):
                for start, end in ((0, sys.maxsize), (-5, -1), (1, 4),
                                   (0, 0), (50, 60), (3, 1), (-50, 50)):
                    value, sub = map(self.make_string, (text, needle))
                    before = [_testcapi.unicode_storage(x) for x in (value, sub)]
                    for method in ('find', 'rfind', 'startswith', 'endswith'):
                        with self.subTest(method=method, text=ascii(text),
                                          needle=ascii(needle), start=start, end=end):
                            self.assertEqual(getattr(value, method)(sub, start, end),
                                             getattr(Str(text), method)(Str(needle), start, end))
                    self.assertEqual(sub in value, Str(needle) in Str(text))
                    self.assertEqual(
                        [_testcapi.unicode_storage(x) for x in (value, sub)], before)

    def test_cached_bounded_operations(self):
        bounds = (-20, -3, -1, 0, 1, 3, 20, sys.maxsize)
        for text in ('aééz', 'a日本z', 'a😀😀z', 'a\0\ud800\udcffz'):
            chars = list(text)
            for factory in (self.make_string, Str):
                value = factory(text)
                _testcapi.unicode_materialize_fsr(value)
                before = _testcapi.unicode_storage(value)
                for start in bounds:
                    for end in bounds:
                        with self.subTest(text=ascii(text), factory=factory,
                                          start=start, end=end):
                            self.assertEqual(value[start:end],
                                             ''.join(chars[start:end]))
                            lo = max(len(chars) + start, 0) if start < 0 else start
                            hi = (max(len(chars) + end, 0) if end < 0
                                  else min(end, len(chars)))
                            for text_sub in ('', 'a', text[1:3], 'z', '\0',
                                             '\ud800', '😀', 'missing'):
                                sub = self.make_string(text_sub)
                                sub_before = _testcapi.unicode_storage(sub)
                                pattern = list(text_sub)
                                fits = lo <= hi and len(pattern) <= hi - lo
                                self.assertEqual(value.startswith(sub, start, end),
                                    fits and chars[lo:lo + len(pattern)] == pattern)
                                self.assertEqual(value.endswith(sub, start, end),
                                    fits and chars[hi - len(pattern):hi] == pattern)
                                matches = [i for i in range(lo, hi - len(pattern) + 1)
                                           if chars[i:i + len(pattern)] == pattern]
                                self.assertEqual(value.find(sub, start, end),
                                                 matches[0] if matches else -1)
                                self.assertEqual(value.rfind(sub, start, end),
                                                 matches[-1] if matches else -1)
                                self.assertEqual(_testcapi.unicode_storage(sub),
                                                 sub_before)
                self.assertEqual(_testcapi.unicode_storage(value), before)

    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi')
    def test_cached_search_overestimated_width(self):
        for ch in ('a', 'é', '\udcff'):
            needle, _ = _testlimitedcapi.unicode_writechar('😀', 0, ord(ch))
            value = self.make_string(ch * 4)
            _testcapi.unicode_materialize_fsr(value)
            self.assertEqual(value.find(needle, 1), 1)
            self.assertEqual(value.rfind(needle, 0, 3), 2)
            self.assertTrue(value.startswith(needle, 1))
            self.assertTrue(value.endswith(needle, 0, 3))
            # A multi-character overestimated needle exercises conversion.
            needle, _ = _testlimitedcapi.unicode_writechar('b😀', 1, ord(ch))
            value = self.make_string(('b' + ch) * 2)
            _testcapi.unicode_materialize_fsr(value)
            self.assertEqual(value.find(needle, 1), 2)
            self.assertEqual(value.rfind(needle, 0, 3), 0)

    def test_cached_search_allocation_failure(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            value = b'a\xf0\x9f\x98\x80bcabc'.decode()
            _testcapi.unicode_materialize_fsr(value)
            remove_hooks = _testcapi.remove_mem_hooks
            for operation in (value.find, value.rfind):
                for fail_at in range(5):
                    try:
                        _testcapi.set_nomemory(fail_at, fail_at + 1)
                        operation('bc', 1)
                    except MemoryError:
                        pass
                    finally:
                        remove_hooks()
                    assert operation('bc', 1) == (2 if operation == value.find else 5)
        """))

    def test_unified_operations_mixed_storage(self):
        # Check each operand independently: views may borrow primary storage
        # or own a temporary encoding, including surrogatepass sequences.
        for source_type in (self.make_string, Str):
            for needle_type in (self.make_string, Str):
                for replacement_type in (self.make_string, Str):
                    s = source_type('a日\udcff日\tZ')
                    needle = needle_type('日')
                    replacement = replacement_type('😀')
                    before = [_testcapi.unicode_storage(x)
                              for x in (s, needle, replacement)]
                    self.assertIn(needle, s)
                    self.assertEqual(s.find(needle), 1)
                    self.assertEqual(s.rfind(needle), 3)
                    self.assertEqual(s.count(needle), 2)
                    self.assertTrue(s.startswith(needle, 1))
                    self.assertTrue(s.endswith(needle, 0, 4))
                    self.assertEqual(s.replace(needle, replacement),
                                     'a😀\udcff😀\tZ')
                    self.assertEqual(s.split(needle), ['a', '\udcff', '\tZ'])
                    self.assertEqual(s.rsplit(needle, 1), ['a日\udcff', '\tZ'])
                    self.assertEqual(s.partition(needle), ('a', '日', '\udcff日\tZ'))
                    self.assertEqual(s.rpartition(needle), ('a日\udcff', '日', '\tZ'))
                    self.assertEqual(s.expandtabs(4), 'a日\udcff日    Z')
                    self.assertEqual(s.upper(), 'A日\udcff日\tZ')
                    self.assertEqual(s.lower(), 'a日\udcff日\tz')
                    self.assertEqual(s.title(), 'A日\udcff日\tZ')
                    self.assertEqual(s.capitalize(), 'A日\udcff日\tz')
                    self.assertEqual(s.swapcase(), 'A日\udcff日\tz')
                    self.assertEqual(s.casefold(), 'a日\udcff日\tz')
                    self.assertEqual([_testcapi.unicode_storage(x)
                                      for x in (s, needle, replacement)], before)
                    self.assertRaises(UnicodeEncodeError,
                                      _testcapi.unicode_asutf8, s, 0)

    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_unified_operations_overestimated_width(self):
        # C writes can leave FSR-primary strings with an overestimated kind.
        needle, _ = _testlimitedcapi.unicode_writechar('😀', 0, ord('a'))
        self.assertIn(needle, 'abc')
        self.assertEqual('abc'.find(needle), 0)
        self.assertEqual('abc'.count(needle), 1)
        self.assertEqual('abc'.split(needle), ['', 'bc'])
        self.assertEqual('abc'.replace(needle, 'X'), 'Xbc')
        value, _ = _testlimitedcapi.unicode_writechar('\t😀', 1, ord('a'))
        self.assertEqual(value.expandtabs(2), '  a')
        self.assertEqual(value.upper(), '\tA')

    def test_copy_operations_overestimated_width(self):
        for text in ('a', 'é', '\udcff'):
            value, _ = _testlimitedcapi.unicode_writechar('😀', 0, ord(text))
            for operation in (lambda x: x * 3,
                              lambda x: x.join(['a', 'b']),
                              lambda x: ''.join([x, x]),
                              lambda x: x.center(5, ' '),
                              lambda x: x.strip('a'), repr):
                with self.subTest(text=ascii(text), operation=operation):
                    actual = operation(value)
                    expected = operation(text)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual.encode('utf-8', 'surrogatepass'),
                                     expected.encode('utf-8', 'surrogatepass'))
                    self.assertEqual(actual.isascii(), expected.isascii())
                    if '\udcff' in actual:
                        self.assertRaises(UnicodeEncodeError, actual.encode)

    def test_compare_storage_combinations(self):
        values = ('', 'a', 'é', '日', '\ud7ff', '\ud800', '\udcff',
                  '\ue000', '😀', '日\0', '日日')
        for a in values:
            for b in values:
                expected = (list(map(ord, a)) > list(map(ord, b))) - (
                    list(map(ord, a)) < list(map(ord, b)))
                for left in (self.make_string(a), Str(a)):
                    for right in (self.make_string(b), Str(b)):
                        self.assertEqual((left > right) - (left < right), expected)

    def test_utf8_view_allocation_failures(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            class Str(str): pass
            source, needle, replacement = map(Str, ('AΣ日\udcff\t日', '日', '😀'))
            operations = (
                lambda: needle in source,
                lambda: source.find(needle), lambda: source.rfind(needle),
                lambda: source.count(needle), lambda: source.startswith(needle),
                lambda: source.endswith(needle),
                lambda: source.replace(needle, replacement),
                lambda: source.split(needle), lambda: source.rsplit(needle),
                lambda: source.partition(needle), lambda: source.rpartition(needle),
                lambda: source.expandtabs(4), source.lower, source.upper,
                source.title, source.capitalize, source.swapcase, source.casefold,
                lambda: repr(source), lambda: source.strip(needle),
                lambda: source.join([source, replacement]),
                lambda: source * 3, lambda: source.center(25, '😀'),
            )
            raw = source.encode('utf-8', 'surrogatepass')
            remove_hooks = _testcapi.remove_mem_hooks
            for operation in operations:
                expected = operation()
                for fail_at in range(12):
                    try:
                        _testcapi.set_nomemory(fail_at, fail_at + 1)
                        operation()
                    except MemoryError:
                        pass
                    finally:
                        remove_hooks()
                    assert source.encode('utf-8', 'surrogatepass') == raw
                    assert operation() == expected
        """))

    def test_utf8_copy_and_scan_methods(self):
        operations = {
            'repr': repr,
            'split': lambda s: s.split('日', 2),
            'rsplit': lambda s: s.rsplit('日', 2),
            'split_ws': lambda s: s.split(None, 2),
            'rsplit_ws': lambda s: s.rsplit(None, 2),
            'split_zero': lambda s: s.split(None, 0),
            'rsplit_zero': lambda s: s.rsplit(None, 0),
            'splitlines': lambda s: s.splitlines(),
            'splitlines_keep': lambda s: s.splitlines(True),
            'partition': lambda s: s.partition('日'),
            'rpartition': lambda s: s.rpartition('日'),
            'strip': lambda s: s.strip(),
            'lstrip': lambda s: s.lstrip(),
            'rstrip': lambda s: s.rstrip(),
            'strip_chars': lambda s: s.strip('日😀\udcff'),
            'removeprefix': lambda s: s.removeprefix('日'),
            'removesuffix': lambda s: s.removesuffix('日'),
            'slice': lambda s: s[1:-1],
            'join': lambda s: s.join([s, '😀', s]),
            'repeat': lambda s: s * 3,
            'ljust': lambda s: s.ljust(30, '😀'),
            'rjust': lambda s: s.rjust(30, '\udcff'),
            'center': lambda s: s.center(30, '日'),
            'zfill': lambda s: s.zfill(30),
            'expandtabs': lambda s: s.expandtabs(4),
        }
        for name in ('islower', 'isupper', 'istitle', 'isspace', 'isalpha',
                     'isalnum', 'isdecimal', 'isdigit', 'isnumeric',
                     'isidentifier', 'isprintable', 'upper', 'lower', 'title',
                     'capitalize', 'swapcase', 'casefold'):
            operations[name] = getattr(str, name)
        for text in ('日日本😀\udcff日', '\u3000é\t日\r\n😀\x85日\u2028\u3000',
                     '\ud800x\udc00', '-日本😀', '+\udcff', 'Éabc\0日', 'éé'):
            for name, operation in operations.items():
                with self.subTest(method=name, text=ascii(text)):
                    value = self.make_string(text)
                    self.assertEqual(operation(value), operation(Str(text)))
                    self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    def test_utf8_case_context(self):
        for text in ('AΣ', 'AΣA', 'A\u0345Σ\u0301', 'AΣ\u0345A',
                     'Σ\u0301', 'ßİﬃǅ', '\U00010400\U00010428',
                     'AΣ\udcffΣ\ud800', 'AΣ\0ΣA'):
            for name in ('upper', 'lower', 'title', 'capitalize', 'swapcase',
                         'casefold'):
                with self.subTest(text=ascii(text), method=name):
                    value = self.make_string(text)
                    self.assertEqual(getattr(value, name)(),
                                     getattr(Str(text), name)())
                    self.assertEqual(_testcapi.unicode_storage(value)[3], 0)

    def test_utf8_native_allocation_failures(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            raw = ' 日\t本😀日\n '.encode()
            remove_hooks = _testcapi.remove_mem_hooks
            operations = (
                lambda s: s.split('日'), lambda s: s.rsplit(None, 1),
                lambda s: s.partition('日'), lambda s: s.rpartition('日'),
                lambda s: s.splitlines(), lambda s: s.strip(),
                lambda s: s[1:-1], lambda s: s.join([s, s]),
                lambda s: s * 3, lambda s: s.center(20, '😀'),
                lambda s: s.expandtabs(4), lambda s: s.zfill(20),
                str.upper, str.lower, str.title, str.capitalize,
                str.swapcase, str.casefold,
            )
            for operation in operations:
                for fail_at in range(10):
                    s = raw.decode()
                    try:
                        _testcapi.set_nomemory(fail_at, fail_at + 1)
                        operation(s)
                    except MemoryError:
                        pass
                    finally:
                        remove_hooks()
                    assert s.encode() == raw
                    assert _testcapi.unicode_storage(s)[3] == 0
                    operation(s)
        """))

    def test_utf8_replace_allocation_failure(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            s = '日本日本'.encode().decode()
            old = '日本'.encode().decode()
            new = '😀😀'.encode().decode()
            replace = s.replace
            count = s.count
            remove_hooks = _testcapi.remove_mem_hooks
            try:
                _testcapi.set_nomemory(0, 1)
                n = count(old)
            finally:
                remove_hooks()
            assert n == 2
            failed = False
            try:
                _testcapi.set_nomemory(0, 1)
                replace(old, new)
            except MemoryError:
                failed = True
            finally:
                remove_hooks()
            assert failed
            for value in (s, old, new):
                assert _testcapi.unicode_storage(value)[3] == 0
            assert replace(old, new) == '😀😀😀😀'
        """))

    def test_readonly_writer_preserves_lazy_fsr(self):
        value = self.make_string('日本😀')
        result = '{}'.format(value)
        self.assertEqual(result, value)
        self.assertEqual(_testcapi.unicode_storage(value)[3], 0)
        self.assertEqual(_testcapi.unicode_storage(result)[3], 0)

    @threading_helper.requires_working_threading()
    def test_concurrent_fsr_publication(self):
        value = self.make_string('a日本語😀' * 100)
        self.assertEqual(_testcapi.unicode_storage(value)[3], 0)
        before = value.__sizeof__()

        def read():
            for _ in range(50):
                self.assertTrue(value.isprintable())
                self.assertEqual(value.find('日'), 1)
                self.assertEqual(value.find('日本', 5), 6)
                self.assertTrue(value.startswith('日本', 6))
                self.assertTrue(value.endswith('日本', 0, 8))
                self.assertEqual(value[6:8], '日本')
                _testcapi.unicode_materialize_fsr(value)
                self.assertEqual(value[1], '日')
                self.assertEqual(value[-1], '😀')

        threading_helper.run_concurrently(read, nthreads=8)
        self.assertEqual(value.__sizeof__() - before, 4 * (len(value) + 1))

    @unittest.skipIf(_testinternalcapi is None, 'need _testinternalcapi')
    def test_hash_caches_fsr_utf8(self):
        for ch in (0xa1, 0x100, 0xd800, 0xdcff, 0x10000):
            for pre_cached in (False, True):
                if pre_cached and 0xd800 <= ch <= 0xdfff:
                    continue
                with self.subTest(ch=ch, pre_cached=pre_cached):
                    value = _testcapi.unicode_new(3, ch)
                    expected = chr(ch) * 3
                    encoded = expected.encode('utf-8', 'surrogatepass')
                    if pre_cached:
                        _testcapi.unicode_asutf8(value, 0)
                    before = value.__sizeof__()
                    self.assertEqual(hash(value), hash(expected))
                    size = value.__sizeof__()
                    self.assertEqual(size - before,
                                     0 if pre_cached else len(encoded) + 1)
                    self.assertEqual(_testinternalcapi.unicode_utf8_view(value),
                                     (encoded, True))
                    self.assertEqual(hash(value), hash(expected))
                    if 0xd800 <= ch <= 0xdfff:
                        for _ in range(2):
                            with self.assertRaises(UnicodeEncodeError):
                                _testcapi.unicode_asutf8(value, 0)
                            with self.assertRaises(UnicodeEncodeError):
                                value.encode('utf-8')
                        self.assertEqual(value.encode('utf-8', 'surrogatepass'),
                                         encoded)
                        self.assertEqual(value.encode('utf-8', 'ignore'), b'')
                    else:
                        self.assertEqual(_testcapi.unicode_asutf8(value, len(encoded) + 1),
                                         encoded + b'\0')
                    self.assertEqual(value.__sizeof__(), size)
                    self.assertEqual(value, expected)

    @unittest.skipIf(_testlimitedcapi is None or _testinternalcapi is None,
                     'need C API test modules')
    def test_hash_caches_promoted_fsr_utf8(self):
        for ch in (ord('a'), ord('é'), 0xd800):
            value, _ = _testlimitedcapi.unicode_writechar('😀', 0, ch)
            expected = chr(ch)
            encoded = expected.encode('utf-8', 'surrogatepass')
            self.assertEqual(hash(value), hash(expected))
            self.assertEqual(_testinternalcapi.unicode_utf8_view(value),
                             (encoded, True))
            if ch == 0xd800:
                with self.assertRaises(UnicodeEncodeError):
                    _testcapi.unicode_asutf8(value, 0)
            else:
                self.assertEqual(_testcapi.unicode_asutf8(value, len(encoded) + 1),
                                 encoded + b'\0')

    def test_hash_utf8_cache_allocation_failure(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            import _testinternalcapi
            remove_hooks = _testcapi.remove_mem_hooks
            for fail_at in (0, 1):
                value = _testcapi.unicode_new(3, 0xd800)
                before = value.__sizeof__()
                failed = False
                try:
                    _testcapi.set_nomemory(fail_at, fail_at + 1)
                    hash(value)
                except MemoryError:
                    failed = True
                finally:
                    remove_hooks()
                assert failed
                assert value.__sizeof__() == before
                assert hash(value) == hash('\ud800' * 3)
                assert _testinternalcapi.unicode_utf8_view(value) == (
                    b'\xed\xa0\x80' * 3, True)
        """))

    def test_legacy_fsr_equality(self):
        for ch in (0xa1, 0x100, 0xd800, 0x10000):
            with self.subTest(ch=ch):
                legacy = _testcapi.unicode_new(3, ch)
                compact = self.make_string(chr(ch) * 3)
                self.assertEqual(_testcapi.unicode_storage(legacy)[0], 0)
                self.assertEqual(legacy, compact)
                self.assertEqual(hash(legacy), hash(compact))
                self.assertEqual({legacy: 42}[compact], 42)
                self.assertEqual(legacy + compact, compact + legacy)

    def test_operation_allocation_failures(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            operations = (str.upper, str.lower, str.strip, str.__repr__)
            raw = ' a日本😀z '.encode()
            remove_hooks = _testcapi.remove_mem_hooks
            for operation in operations:
                s = raw.decode()
                failed = False
                try:
                    _testcapi.set_nomemory(0, 1)
                    operation(s)
                except MemoryError:
                    failed = True
                finally:
                    remove_hooks()
                assert failed
                assert _testcapi.unicode_storage(s)[3] == 0
                assert s.encode() == raw
                operation(s)
                assert _testcapi.unicode_storage(s)[3] == 0
        """))

    def test_fsr_failure_retry(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            s = b'caf\xc3\xa9'.decode()
            failed = False
            materialize = _testcapi.unicode_materialize_fsr
            remove_hooks = _testcapi.remove_mem_hooks
            try:
                _testcapi.set_nomemory(0, 1)
                materialize(s)
            except MemoryError:
                failed = True
            finally:
                remove_hooks()
            assert failed
            assert _testcapi.unicode_storage(s)[3] == 0
            materialize(s)
            assert _testcapi.unicode_storage(s)[3] == 1
            assert s[3] == 'é'
        """))


class CAPITest(unittest.TestCase):

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_new(self):
        """Test PyUnicode_New()"""
        from _testcapi import unicode_new as new

        for maxchar in 0, 0x61, 0xa1, 0x4f60, 0x1f600, 0x10ffff:
            self.assertEqual(new(0, maxchar), '')
            self.assertEqual(new(5, maxchar), chr(maxchar)*5)
            self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX, maxchar)
        self.assertEqual(new(0, 0x110000), '')
        self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX//2, 0x4f60)
        self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX//2+1, 0x4f60)
        self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX//2, 0x1f600)
        self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX//2+1, 0x1f600)
        self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX//4, 0x1f600)
        self.assertRaises(MemoryError, new, PY_SSIZE_T_MAX//4+1, 0x1f600)
        self.assertRaises(SystemError, new, 5, 0x110000)
        self.assertRaises(SystemError, new, -1, 0)
        self.assertRaises(SystemError, new, PY_SSIZE_T_MIN, 0)

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_fill(self):
        """Test PyUnicode_Fill()"""
        from _testcapi import unicode_fill as fill

        strings = [
            # all strings have exactly 5 characters
            'abcde', '\xa1\xa2\xa3\xa4\xa5',
            '\u4f60\u597d\u4e16\u754c\uff01',
            '\U0001f600\U0001f601\U0001f602\U0001f603\U0001f604'
        ]
        chars = [0x78, 0xa9, 0x20ac, 0x1f638]

        for idx, fill_char in enumerate(chars):
            # wide -> narrow: exceed maxchar limitation
            for to in strings[:idx]:
                self.assertRaises(ValueError, fill, to, 0, 0, fill_char)
            for to in strings[idx:]:
                for start in [*range(7), PY_SSIZE_T_MAX]:
                    for length in [*range(-1, 7 - start), PY_SSIZE_T_MIN, PY_SSIZE_T_MAX]:
                        filled = max(min(length, 5 - start), 0)
                        if filled == 5 and to != strings[idx]:
                            # narrow -> wide
                            # Tests omitted since this creates invalid strings.
                            continue
                        expected = to[:start] + chr(fill_char) * filled + to[start + filled:]
                        self.assertEqual(fill(to, start, length, fill_char),
                                        (expected, filled))

        s = strings[0]
        self.assertRaises(IndexError, fill, s, -1, 0, 0x78)
        self.assertRaises(IndexError, fill, s, PY_SSIZE_T_MIN, 0, 0x78)
        self.assertRaises(ValueError, fill, s, 0, 0, 0x110000)
        self.assertRaises(SystemError, fill, b'abc', 0, 0, 0x78)
        self.assertRaises(SystemError, fill, [], 0, 0, 0x78)
        # CRASHES fill(s, 0, NULL, 0, 0)
        # CRASHES fill(NULL, 0, 0, 0x78)
        # TODO: Test PyUnicode_Fill() with non-modifiable unicode.

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_writechar(self):
        """Test PyUnicode_WriteChar()"""
        from _testlimitedcapi import unicode_writechar as writechar

        strings = [
            # one string for every kind
            'abc', '\xa1\xa2\xa3', '\u4f60\u597d\u4e16',
            '\U0001f600\U0001f601\U0001f602'
        ]
        # one character for every kind + out of range code
        chars = [0x78, 0xa9, 0x20ac, 0x1f638, 0x110000]
        for i, s in enumerate(strings):
            for j, c in enumerate(chars):
                if j <= i:
                    self.assertEqual(writechar(s, 1, c),
                                     (s[:1] + chr(c) + s[2:], 0))
                else:
                    self.assertRaises(ValueError, writechar, s, 1, c)

        self.assertRaises(IndexError, writechar, 'abc', 3, 0x78)
        self.assertRaises(IndexError, writechar, 'abc', -1, 0x78)
        self.assertRaises(IndexError, writechar, 'abc', PY_SSIZE_T_MAX, 0x78)
        self.assertRaises(IndexError, writechar, 'abc', PY_SSIZE_T_MIN, 0x78)
        self.assertRaises(TypeError, writechar, b'abc', 0, 0x78)
        self.assertRaises(TypeError, writechar, [], 0, 0x78)
        # CRASHES writechar(NULL, 0, 0x78)
        # TODO: Test PyUnicode_WriteChar() with non-modifiable and legacy
        # unicode.

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_resize(self):
        """Test PyUnicode_Resize()"""
        from _testlimitedcapi import unicode_resize as resize

        strings = [
            # all strings have exactly 3 characters
            'abc', '\xa1\xa2\xa3', '\u4f60\u597d\u4e16',
            '\U0001f600\U0001f601\U0001f602'
        ]
        for s in strings:
            self.assertEqual(resize(s, 3), (s, 0))
            self.assertEqual(resize(s, 2), (s[:2], 0))
            self.assertEqual(resize(s, 4), (s + '\0', 0))
            self.assertEqual(resize(s, 10), (s + '\0'*7, 0))
            self.assertEqual(resize(s, 0), ('', 0))
            self.assertRaises(MemoryError, resize, s, PY_SSIZE_T_MAX)
            self.assertRaises(SystemError, resize, s, -1)
            self.assertRaises(SystemError, resize, s, PY_SSIZE_T_MIN)
        self.assertRaises(SystemError, resize, b'abc', 0)
        self.assertRaises(SystemError, resize, [], 0)
        self.assertRaises(SystemError, resize, NULL, 0)
        # TODO: Test PyUnicode_Resize() with non-modifiable and legacy unicode
        # and with NULL as the address.

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_append(self):
        """Test PyUnicode_Append()"""
        from _testlimitedcapi import unicode_append as append

        strings = [
            'abc', '\xa1\xa2\xa3', '\u4f60\u597d\u4e16',
            '\U0001f600\U0001f601\U0001f602'
        ]
        for left in strings:
            left = left[::-1]
            for right in strings:
                expected = left + right
                self.assertEqual(append(left, right), expected)

        self.assertRaises(SystemError, append, 'abc', b'abc')
        self.assertRaises(SystemError, append, b'abc', 'abc')
        self.assertRaises(SystemError, append, b'abc', b'abc')
        self.assertRaises(SystemError, append, 'abc', [])
        self.assertRaises(SystemError, append, [], 'abc')
        self.assertRaises(SystemError, append, [], [])
        self.assertRaises(SystemError, append, NULL, 'abc')
        self.assertRaises(SystemError, append, 'abc', NULL)
        # TODO: Test PyUnicode_Append() with modifiable unicode
        # and with NULL as the address.
        # TODO: Check reference counts.

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_appendanddel(self):
        """Test PyUnicode_AppendAndDel()"""
        from _testlimitedcapi import unicode_appendanddel as appendanddel

        strings = [
            'abc', '\xa1\xa2\xa3', '\u4f60\u597d\u4e16',
            '\U0001f600\U0001f601\U0001f602'
        ]
        for left in strings:
            left = left[::-1]
            for right in strings:
                self.assertEqual(appendanddel(left, right), left + right)

        self.assertRaises(SystemError, appendanddel, 'abc', b'abc')
        self.assertRaises(SystemError, appendanddel, b'abc', 'abc')
        self.assertRaises(SystemError, appendanddel, b'abc', b'abc')
        self.assertRaises(SystemError, appendanddel, 'abc', [])
        self.assertRaises(SystemError, appendanddel, [], 'abc')
        self.assertRaises(SystemError, appendanddel, [], [])
        self.assertRaises(SystemError, appendanddel, NULL, 'abc')
        self.assertRaises(SystemError, appendanddel, 'abc', NULL)
        # TODO: Test PyUnicode_AppendAndDel() with modifiable unicode
        # and with NULL as the address.
        # TODO: Check reference counts.

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_fromstringandsize(self):
        """Test PyUnicode_FromStringAndSize()"""
        from _testlimitedcapi import unicode_fromstringandsize as fromstringandsize

        self.assertEqual(fromstringandsize(b'abc'), 'abc')
        self.assertEqual(fromstringandsize(b'abc', 2), 'ab')
        self.assertEqual(fromstringandsize(b'abc\0def'), 'abc\0def')
        self.assertEqual(fromstringandsize(b'\xc2\xa1\xc2\xa2'), '\xa1\xa2')
        self.assertEqual(fromstringandsize(b'\xe4\xbd\xa0'), '\u4f60')
        self.assertEqual(fromstringandsize(b'\xf0\x9f\x98\x80'), '\U0001f600')
        self.assertRaises(UnicodeDecodeError, fromstringandsize, b'\xc2\xa1', 1)
        self.assertRaises(UnicodeDecodeError, fromstringandsize, b'\xa1', 1)
        self.assertEqual(fromstringandsize(b'', 0), '')
        self.assertEqual(fromstringandsize(NULL, 0), '')

        self.assertRaises(MemoryError, fromstringandsize, b'abc', PY_SSIZE_T_MAX)
        self.assertRaises(SystemError, fromstringandsize, b'abc', -1)
        self.assertRaises(SystemError, fromstringandsize, b'abc', PY_SSIZE_T_MIN)
        self.assertRaises(SystemError, fromstringandsize, NULL, -1)
        self.assertRaises(SystemError, fromstringandsize, NULL, PY_SSIZE_T_MIN)
        self.assertRaises(SystemError, fromstringandsize, NULL, 3)
        self.assertRaises(SystemError, fromstringandsize, NULL, PY_SSIZE_T_MAX)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_fromstring(self):
        """Test PyUnicode_FromString()"""
        from _testlimitedcapi import unicode_fromstring as fromstring

        self.assertEqual(fromstring(b'abc'), 'abc')
        self.assertEqual(fromstring(b'\xc2\xa1\xc2\xa2'), '\xa1\xa2')
        self.assertEqual(fromstring(b'\xe4\xbd\xa0'), '\u4f60')
        self.assertEqual(fromstring(b'\xf0\x9f\x98\x80'), '\U0001f600')
        self.assertRaises(UnicodeDecodeError, fromstring, b'\xc2')
        self.assertRaises(UnicodeDecodeError, fromstring, b'\xa1')
        self.assertEqual(fromstring(b''), '')

        # CRASHES fromstring(NULL)

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_fromkindanddata(self):
        """Test PyUnicode_FromKindAndData()"""
        from _testcapi import unicode_fromkindanddata as fromkindanddata

        strings = [
            'abcde', '\xa1\xa2\xa3\xa4\xa5',
            '\u4f60\u597d\u4e16\u754c\uff01',
            '\U0001f600\U0001f601\U0001f602\U0001f603\U0001f604'
        ]
        enc1 = 'latin1'
        for s in strings[:2]:
            self.assertEqual(fromkindanddata(1, s.encode(enc1)), s)
        enc2 = 'utf-16le' if sys.byteorder == 'little' else 'utf-16be'
        for s in strings[:3]:
            self.assertEqual(fromkindanddata(2, s.encode(enc2)), s)
        enc4 = 'utf-32le' if sys.byteorder == 'little' else 'utf-32be'
        for s in strings:
            self.assertEqual(fromkindanddata(4, s.encode(enc4)), s)
        self.assertEqual(fromkindanddata(2, '\U0001f600'.encode(enc2)),
                         '\ud83d\ude00')
        for kind, strings in (
            (1, ('a\0éÿ', 'é' * 100)),
            (2, ('日', '\ud800', 'a\0é日', '\ud800\udc00', '\ud800x\udcff')),
            (4, ('😀', '\udcff', 'a\0é日😀', '\ud800\udc00', '\ud800x\udcff')),
        ):
            for s in strings:
                with self.subTest(kind=kind, s=ascii(s)):
                    data = b''.join(ord(ch).to_bytes(kind, sys.byteorder)
                                    for ch in s)
                    result = fromkindanddata(kind, data)
                    self.assertEqual(result, s)
                    self.assertEqual(_testcapi.unicode_storage(result)[3], 0)
        for value in (0x110000, 0xffffffff):
            data = b'\0' * 4 + value.to_bytes(4, sys.byteorder)
            self.assertRaises(SystemError, fromkindanddata, 4, data)

        for kind in 1, 2, 4:
            self.assertEqual(fromkindanddata(kind, b''), '')
            self.assertEqual(fromkindanddata(kind, b'\0'*kind), '\0')
            self.assertEqual(fromkindanddata(kind, NULL, 0), '')

        for kind in -1, 0, 3, 5, 8:
            self.assertRaises(SystemError, fromkindanddata, kind, b'')
        self.assertRaises(ValueError, fromkindanddata, 1, b'abc', -1)
        self.assertRaises(ValueError, fromkindanddata, 1, b'abc', PY_SSIZE_T_MIN)
        self.assertRaises(ValueError, fromkindanddata, 1, NULL, -1)
        self.assertRaises(ValueError, fromkindanddata, 1, NULL, PY_SSIZE_T_MIN)
        # CRASHES fromkindanddata(1, NULL, 1)
        # CRASHES fromkindanddata(4, b'\xff\xff\xff\xff')

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_substring(self):
        """Test PyUnicode_Substring()"""
        from _testlimitedcapi import unicode_substring as substring

        strings = [
            'ab', 'ab\xa1\xa2',
            'ab\xa1\xa2\u4f60\u597d',
            'ab\xa1\xa2\u4f60\u597d\U0001f600\U0001f601'
        ]
        for s in strings:
            for start in [*range(0, len(s) + 2), PY_SSIZE_T_MAX]:
                for end in [*range(max(start-1, 0), len(s) + 2), PY_SSIZE_T_MAX]:
                    self.assertEqual(substring(s, start, end), s[start:end])

        self.assertRaises(IndexError, substring, 'abc', -1, 0)
        self.assertRaises(IndexError, substring, 'abc', PY_SSIZE_T_MIN, 0)
        self.assertRaises(IndexError, substring, 'abc', 0, -1)
        self.assertRaises(IndexError, substring, 'abc', 0, PY_SSIZE_T_MIN)
        # CRASHES substring(b'abc', 0, 0)
        # CRASHES substring([], 0, 0)
        # CRASHES substring(NULL, 0, 0)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_getlength(self):
        """Test PyUnicode_GetLength()"""
        from _testlimitedcapi import unicode_getlength as getlength

        for s in ['abc', '\xa1\xa2', '\u4f60\u597d', 'a\U0001f600',
                  'a\ud800b\udfffc', '\ud834\udd1e']:
            self.assertEqual(getlength(s), len(s))

        self.assertRaises(TypeError, getlength, b'abc')
        self.assertRaises(TypeError, getlength, [])
        # CRASHES getlength(NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_readchar(self):
        """Test PyUnicode_ReadChar()"""
        from _testlimitedcapi import unicode_readchar as readchar

        for s in ['abc', '\xa1\xa2', '\u4f60\u597d', 'a\U0001f600',
                  'a\ud800b\udfffc', '\ud834\udd1e']:
            for i, c in enumerate(s):
                self.assertEqual(readchar(s, i), ord(c))
            self.assertRaises(IndexError, readchar, s, len(s))
            self.assertRaises(IndexError, readchar, s, PY_SSIZE_T_MAX)
            self.assertRaises(IndexError, readchar, s, -1)
            self.assertRaises(IndexError, readchar, s, PY_SSIZE_T_MIN)

        self.assertRaises(TypeError, readchar, b'abc', 0)
        self.assertRaises(TypeError, readchar, [], 0)
        # CRASHES readchar(NULL, 0)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_fromobject(self):
        """Test PyUnicode_FromObject()"""
        from _testlimitedcapi import unicode_fromobject as fromobject

        for s in ['abc', '\xa1\xa2', '\u4f60\u597d', 'a\U0001f600',
                  'a\ud800b\udfffc', '\ud834\udd1e']:
            self.assertEqual(fromobject(s), s)
            o = Str(s)
            s2 = fromobject(o)
            self.assertEqual(s2, s)
            self.assertIs(type(s2), str)
            self.assertIsNot(s2, s)

        self.assertRaises(TypeError, fromobject, b'abc')
        self.assertRaises(TypeError, fromobject, [])
        # CRASHES fromobject(NULL)

    @unittest.skipIf(ctypes is None, 'need ctypes')
    def test_from_format(self):
        """Test PyUnicode_FromFormat()"""
        # Length modifiers "j" and "t" are not tested here because ctypes does
        # not expose types for intmax_t and ptrdiff_t.
        # _testlimitedcapi.test_string_from_format() has a wider coverage of all
        # formats.
        from ctypes import (
            c_char_p,
            pythonapi, py_object, sizeof,
            c_int, c_long, c_longlong, c_ssize_t,
            c_uint, c_ulong, c_ulonglong, c_size_t, c_void_p,
            c_wchar, c_wchar_p)
        name = "PyUnicode_FromFormat"
        _PyUnicode_FromFormat = getattr(pythonapi, name)
        _PyUnicode_FromFormat.argtypes = (c_char_p,)
        _PyUnicode_FromFormat.restype = py_object

        def PyUnicode_FromFormat(format, *args):
            cargs = tuple(
                py_object(arg) if isinstance(arg, str) else arg
                for arg in args)
            return _PyUnicode_FromFormat(format, *cargs)

        def check_format(expected, format, *args):
            text = PyUnicode_FromFormat(format, *args)
            self.assertEqual(expected, text)

        # ascii format, non-ascii argument
        check_format('ascii\x7f=unicode\xe9',
                     b'ascii\x7f=%U', 'unicode\xe9')

        # non-ascii format, ascii argument: ensure that PyUnicode_FromFormatV()
        # raises an error
        self.assertRaisesRegex(ValueError,
            r'^PyUnicode_FromFormatV\(\) expects an ASCII-encoded format '
            'string, got a non-ASCII byte: 0xe9$',
            PyUnicode_FromFormat, b'unicode\xe9=%s', 'ascii')

        # test "%c"
        check_format('\uabcd',
                     b'%c', c_int(0xabcd))
        check_format('\U0010ffff',
                     b'%c', c_int(0x10ffff))
        with self.assertRaises(OverflowError):
            PyUnicode_FromFormat(b'%c', c_int(0x110000))
        # Issue #18183
        check_format('\U00010000\U00100000',
                     b'%c%c', c_int(0x10000), c_int(0x100000))

        # test "%"
        check_format('%',
                     b'%%')
        check_format('%s',
                     b'%%s')
        check_format('[%]',
                     b'[%%]')
        check_format('%abc',
                     b'%%%s', b'abc')

        # truncated string
        check_format('abc',
                     b'%.3s', b'abcdef')
        check_format('abc[',
                     b'%.6s', 'abc[\u20ac]'.encode('utf8'))
        check_format('abc[\u20ac',
                     b'%.7s', 'abc[\u20ac]'.encode('utf8'))
        check_format('abc[\ufffd',
                     b'%.5s', b'abc[\xff]')
        check_format('abc[',
                     b'%.6s', b'abc[\xe2\x82]')
        check_format('abc[\ufffd]',
                     b'%.7s', b'abc[\xe2\x82]')
        check_format('abc[\ufffd',
                     b'%.7s', b'abc[\xe2\x82\0')
        check_format('      abc[',
                     b'%10.6s', 'abc[\u20ac]'.encode('utf8'))
        check_format('     abc[\u20ac',
                     b'%10.7s', 'abc[\u20ac]'.encode('utf8'))
        check_format('     abc[\ufffd',
                     b'%10.5s', b'abc[\xff]')
        check_format('      abc[',
                     b'%10.6s', b'abc[\xe2\x82]')
        check_format('    abc[\ufffd]',
                     b'%10.7s', b'abc[\xe2\x82]')

        check_format("'\\u20acABC'",
                     b'%A', '\u20acABC')
        check_format("'\\u20",
                     b'%.5A', '\u20acABCDEF')
        check_format("'\u20acABC'",
                     b'%R', '\u20acABC')
        check_format("'\u20acA",
                     b'%.3R', '\u20acABCDEF')
        check_format('\u20acAB',
                     b'%.3S', '\u20acABCDEF')
        check_format('\u20acAB',
                     b'%.3U', '\u20acABCDEF')

        check_format('\u20acAB',
                     b'%.3V', '\u20acABCDEF', None)
        check_format('abc[',
                     b'%.6V', None, 'abc[\u20ac]'.encode('utf8'))
        check_format('abc[\u20ac',
                     b'%.7V', None, 'abc[\u20ac]'.encode('utf8'))
        check_format('abc[\ufffd',
                     b'%.5V', None, b'abc[\xff]')
        check_format('abc[',
                     b'%.6V', None, b'abc[\xe2\x82]')
        check_format('abc[\ufffd]',
                     b'%.7V', None, b'abc[\xe2\x82]')
        check_format('      abc[',
                     b'%10.6V', None, 'abc[\u20ac]'.encode('utf8'))
        check_format('     abc[\u20ac',
                     b'%10.7V', None, 'abc[\u20ac]'.encode('utf8'))
        check_format('     abc[\ufffd',
                     b'%10.5V', None, b'abc[\xff]')
        check_format('      abc[',
                     b'%10.6V', None, b'abc[\xe2\x82]')
        check_format('    abc[\ufffd]',
                     b'%10.7V', None, b'abc[\xe2\x82]')
        check_format('     abc[\ufffd',
                     b'%10.7V', None, b'abc[\xe2\x82\0')

        # following tests comes from #7330
        # test width modifier and precision modifier with %S
        check_format("repr=  abc",
                     b'repr=%5S', 'abc')
        check_format("repr=ab",
                     b'repr=%.2S', 'abc')
        check_format("repr=   ab",
                     b'repr=%5.2S', 'abc')

        # test width modifier and precision modifier with %R
        check_format("repr=   'abc'",
                     b'repr=%8R', 'abc')
        check_format("repr='ab",
                     b'repr=%.3R', 'abc')
        check_format("repr=  'ab",
                     b'repr=%5.3R', 'abc')

        # test width modifier and precision modifier with %A
        check_format("repr=   'abc'",
                     b'repr=%8A', 'abc')
        check_format("repr='ab",
                     b'repr=%.3A', 'abc')
        check_format("repr=  'ab",
                     b'repr=%5.3A', 'abc')

        # test width modifier and precision modifier with %s
        check_format("repr=  abc",
                     b'repr=%5s', b'abc')
        check_format("repr=ab",
                     b'repr=%.2s', b'abc')
        check_format("repr=   ab",
                     b'repr=%5.2s', b'abc')

        # test width modifier and precision modifier with %U
        check_format("repr=  abc",
                     b'repr=%5U', 'abc')
        check_format("repr=ab",
                     b'repr=%.2U', 'abc')
        check_format("repr=   ab",
                     b'repr=%5.2U', 'abc')

        # test width modifier and precision modifier with %V
        check_format("repr=  abc",
                     b'repr=%5V', 'abc', b'123')
        check_format("repr=ab",
                     b'repr=%.2V', 'abc', b'123')
        check_format("repr=   ab",
                     b'repr=%5.2V', 'abc', b'123')
        check_format("repr=  123",
                     b'repr=%5V', None, b'123')
        check_format("repr=12",
                     b'repr=%.2V', None, b'123')
        check_format("repr=   12",
                     b'repr=%5.2V', None, b'123')

        # test integer formats (%i, %d, %u, %o, %x, %X)
        check_format('010',
                     b'%03i', c_int(10))
        check_format('0010',
                     b'%0.4i', c_int(10))
        for conv, signed, value, expected in [
            (b'i', True, -123, '-123'),
            (b'd', True, -123, '-123'),
            (b'u', False, 123, '123'),
            (b'o', False, 0o123, '123'),
            (b'x', False, 0xabc, 'abc'),
            (b'X', False, 0xabc, 'ABC'),
        ]:
            for mod, ctype in [
                (b'', c_int if signed else c_uint),
                (b'l', c_long if signed else c_ulong),
                (b'll', c_longlong if signed else c_ulonglong),
                (b'z', c_ssize_t if signed else c_size_t),
            ]:
                with self.subTest(format=b'%' + mod + conv):
                    check_format(expected,
                                 b'%' + mod + conv, ctype(value))

        # test long output
        min_longlong = -(2 ** (8 * sizeof(c_longlong) - 1))
        max_longlong = -min_longlong - 1
        check_format(str(min_longlong),
                     b'%lld', c_longlong(min_longlong))
        check_format(str(max_longlong),
                     b'%lld', c_longlong(max_longlong))
        max_ulonglong = 2 ** (8 * sizeof(c_ulonglong)) - 1
        check_format(str(max_ulonglong),
                     b'%llu', c_ulonglong(max_ulonglong))
        PyUnicode_FromFormat(b'%p', c_void_p(-1))

        # test padding (width and/or precision)
        check_format('123',        b'%2i', c_int(123))
        check_format('       123', b'%10i', c_int(123))
        check_format('0000000123', b'%010i', c_int(123))
        check_format('123       ', b'%-10i', c_int(123))
        check_format('123       ', b'%-010i', c_int(123))
        check_format('123',        b'%.2i', c_int(123))
        check_format('0000123',    b'%.7i', c_int(123))
        check_format('       123', b'%10.2i', c_int(123))
        check_format('   0000123', b'%10.7i', c_int(123))
        check_format('0000000123', b'%010.7i', c_int(123))
        check_format('0000123   ', b'%-10.7i', c_int(123))
        check_format('0000123   ', b'%-010.7i', c_int(123))

        check_format('-123',       b'%2i', c_int(-123))
        check_format('      -123', b'%10i', c_int(-123))
        check_format('-000000123', b'%010i', c_int(-123))
        check_format('-123      ', b'%-10i', c_int(-123))
        check_format('-123      ', b'%-010i', c_int(-123))
        check_format('-123',       b'%.2i', c_int(-123))
        check_format('-0000123',   b'%.7i', c_int(-123))
        check_format('      -123', b'%10.2i', c_int(-123))
        check_format('  -0000123', b'%10.7i', c_int(-123))
        check_format('-000000123', b'%010.7i', c_int(-123))
        check_format('-0000123  ', b'%-10.7i', c_int(-123))
        check_format('-0000123  ', b'%-010.7i', c_int(-123))

        check_format('123',        b'%2u', c_uint(123))
        check_format('       123', b'%10u', c_uint(123))
        check_format('0000000123', b'%010u', c_uint(123))
        check_format('123       ', b'%-10u', c_uint(123))
        check_format('123       ', b'%-010u', c_uint(123))
        check_format('123',        b'%.2u', c_uint(123))
        check_format('0000123',    b'%.7u', c_uint(123))
        check_format('       123', b'%10.2u', c_uint(123))
        check_format('   0000123', b'%10.7u', c_uint(123))
        check_format('0000000123', b'%010.7u', c_uint(123))
        check_format('0000123   ', b'%-10.7u', c_uint(123))
        check_format('0000123   ', b'%-010.7u', c_uint(123))

        check_format('123',        b'%2o', c_uint(0o123))
        check_format('       123', b'%10o', c_uint(0o123))
        check_format('0000000123', b'%010o', c_uint(0o123))
        check_format('123       ', b'%-10o', c_uint(0o123))
        check_format('123       ', b'%-010o', c_uint(0o123))
        check_format('123',        b'%.2o', c_uint(0o123))
        check_format('0000123',    b'%.7o', c_uint(0o123))
        check_format('       123', b'%10.2o', c_uint(0o123))
        check_format('   0000123', b'%10.7o', c_uint(0o123))
        check_format('0000000123', b'%010.7o', c_uint(0o123))
        check_format('0000123   ', b'%-10.7o', c_uint(0o123))
        check_format('0000123   ', b'%-010.7o', c_uint(0o123))

        check_format('abc',        b'%2x', c_uint(0xabc))
        check_format('       abc', b'%10x', c_uint(0xabc))
        check_format('0000000abc', b'%010x', c_uint(0xabc))
        check_format('abc       ', b'%-10x', c_uint(0xabc))
        check_format('abc       ', b'%-010x', c_uint(0xabc))
        check_format('abc',        b'%.2x', c_uint(0xabc))
        check_format('0000abc',    b'%.7x', c_uint(0xabc))
        check_format('       abc', b'%10.2x', c_uint(0xabc))
        check_format('   0000abc', b'%10.7x', c_uint(0xabc))
        check_format('0000000abc', b'%010.7x', c_uint(0xabc))
        check_format('0000abc   ', b'%-10.7x', c_uint(0xabc))
        check_format('0000abc   ', b'%-010.7x', c_uint(0xabc))

        check_format('ABC',        b'%2X', c_uint(0xabc))
        check_format('       ABC', b'%10X', c_uint(0xabc))
        check_format('0000000ABC', b'%010X', c_uint(0xabc))
        check_format('ABC       ', b'%-10X', c_uint(0xabc))
        check_format('ABC       ', b'%-010X', c_uint(0xabc))
        check_format('ABC',        b'%.2X', c_uint(0xabc))
        check_format('0000ABC',    b'%.7X', c_uint(0xabc))
        check_format('       ABC', b'%10.2X', c_uint(0xabc))
        check_format('   0000ABC', b'%10.7X', c_uint(0xabc))
        check_format('0000000ABC', b'%010.7X', c_uint(0xabc))
        check_format('0000ABC   ', b'%-10.7X', c_uint(0xabc))
        check_format('0000ABC   ', b'%-010.7X', c_uint(0xabc))

        # test %A
        check_format(r"%A:'abc\xe9\uabcd\U0010ffff'",
                     b'%%A:%A', 'abc\xe9\uabcd\U0010ffff')

        # test %V
        check_format('abc',
                     b'%V', 'abc', b'xyz')
        check_format('xyz',
                     b'%V', None, b'xyz')

        # test %ls
        check_format('abc', b'%ls', c_wchar_p('abc'))
        check_format('\u4eba\u6c11', b'%ls', c_wchar_p('\u4eba\u6c11'))
        check_format('\U0001f4bb+\U0001f40d',
                     b'%ls', c_wchar_p('\U0001f4bb+\U0001f40d'))
        check_format('   ab', b'%5.2ls', c_wchar_p('abc'))
        check_format('   \u4eba\u6c11', b'%5ls', c_wchar_p('\u4eba\u6c11'))
        check_format('  \U0001f4bb+\U0001f40d',
                     b'%5ls', c_wchar_p('\U0001f4bb+\U0001f40d'))
        check_format('\u4eba', b'%.1ls', c_wchar_p('\u4eba\u6c11'))
        check_format('\U0001f4bb' if sizeof(c_wchar) > 2 else '\ud83d',
                     b'%.1ls', c_wchar_p('\U0001f4bb+\U0001f40d'))
        check_format('\U0001f4bb+' if sizeof(c_wchar) > 2 else '\U0001f4bb',
                     b'%.2ls', c_wchar_p('\U0001f4bb+\U0001f40d'))

        # test %lV
        check_format('abc',
                     b'%lV', 'abc', c_wchar_p('xyz'))
        check_format('xyz',
                     b'%lV', None, c_wchar_p('xyz'))
        check_format('\u4eba\u6c11',
                     b'%lV', None, c_wchar_p('\u4eba\u6c11'))
        check_format('\U0001f4bb+\U0001f40d',
                     b'%lV', None, c_wchar_p('\U0001f4bb+\U0001f40d'))
        check_format('   ab',
                     b'%5.2lV', None, c_wchar_p('abc'))
        check_format('   \u4eba\u6c11',
                     b'%5lV', None, c_wchar_p('\u4eba\u6c11'))
        check_format('  \U0001f4bb+\U0001f40d',
                     b'%5lV', None, c_wchar_p('\U0001f4bb+\U0001f40d'))
        check_format('\u4eba',
                     b'%.1lV', None, c_wchar_p('\u4eba\u6c11'))
        check_format('\U0001f4bb' if sizeof(c_wchar) > 2 else '\ud83d',
                     b'%.1lV', None, c_wchar_p('\U0001f4bb+\U0001f40d'))
        check_format('\U0001f4bb+' if sizeof(c_wchar) > 2 else '\U0001f4bb',
                     b'%.2lV', None, c_wchar_p('\U0001f4bb+\U0001f40d'))

        # test %T
        check_format('type: str',
                     b'type: %T', py_object("abc"))
        check_format(f'type: st',
                     b'type: %.2T', py_object("abc"))
        check_format(f'type:        str',
                     b'type: %10T', py_object("abc"))

        class LocalType:
            pass
        obj = LocalType()
        fullname = f'{__name__}.{LocalType.__qualname__}'
        check_format(f'type: {fullname}',
                     b'type: %T', py_object(obj))
        fullname_alt = f'{__name__}:{LocalType.__qualname__}'
        check_format(f'type: {fullname_alt}',
                     b'type: %#T', py_object(obj))

        # test %N
        check_format('type: str',
                     b'type: %N', py_object(str))
        check_format(f'type: st',
                     b'type: %.2N', py_object(str))
        check_format(f'type:        str',
                     b'type: %10N', py_object(str))

        check_format(f'type: {fullname}',
                     b'type: %N', py_object(type(obj)))
        check_format(f'type: {fullname_alt}',
                     b'type: %#N', py_object(type(obj)))
        with self.assertRaisesRegex(TypeError, "%N argument must be a type"):
            check_format('type: str',
                         b'type: %N', py_object("abc"))

        # test variable width and precision
        check_format('  abc', b'%*s', c_int(5), b'abc')
        check_format('ab', b'%.*s', c_int(2), b'abc')
        check_format('   ab', b'%*.*s', c_int(5), c_int(2), b'abc')
        check_format('  abc', b'%*U', c_int(5), 'abc')
        check_format('ab', b'%.*U', c_int(2), 'abc')
        check_format('   ab', b'%*.*U', c_int(5), c_int(2), 'abc')
        check_format('   ab', b'%*.*V', c_int(5), c_int(2), None, b'abc')
        check_format('   ab', b'%*.*lV', c_int(5), c_int(2),
                     None, c_wchar_p('abc'))
        check_format('     123', b'%*i', c_int(8), c_int(123))
        check_format('00123', b'%.*i', c_int(5), c_int(123))
        check_format('   00123', b'%*.*i', c_int(8), c_int(5), c_int(123))

        # test %p
        # We cannot test the exact result,
        # because it returns a hex representation of a C pointer,
        # which is going to be different each time. But, we can test the format.
        p_format_regex = r'^0x[a-zA-Z0-9]{3,}$'
        p_format1 = PyUnicode_FromFormat(b'%p', 'abc')
        self.assertIsInstance(p_format1, str)
        self.assertRegex(p_format1, p_format_regex)

        p_format2 = PyUnicode_FromFormat(b'%p %p', '123456', b'xyz')
        self.assertIsInstance(p_format2, str)
        self.assertRegex(p_format2,
                         r'0x[a-zA-Z0-9]{3,} 0x[a-zA-Z0-9]{3,}')

        # Extra args are ignored:
        p_format3 = PyUnicode_FromFormat(b'%p', '123456', None, b'xyz')
        self.assertIsInstance(p_format3, str)
        self.assertRegex(p_format3, p_format_regex)

        # Test string decode from parameter of %s using utf-8.
        # b'\xe4\xba\xba\xe6\xb0\x91' is utf-8 encoded byte sequence of
        # '\u4eba\u6c11'
        check_format('repr=\u4eba\u6c11',
                     b'repr=%V', None, b'\xe4\xba\xba\xe6\xb0\x91')

        #Test replace error handler.
        check_format('repr=abc\ufffd',
                     b'repr=%V', None, b'abc\xff')

        # Issue #33817: empty strings
        check_format('',
                     b'')
        check_format('',
                     b'%s', b'')

        # test invalid format strings. these tests are just here
        # to check for crashes and should not be considered as specifications
        for fmt in (b'%', b'%0', b'%01', b'%.', b'%.1',
                    b'%0%s', b'%1%s', b'%.%s', b'%.1%s', b'%1abc',
                    b'%l', b'%ll', b'%z', b'%lls', b'%zs'):
            with self.subTest(fmt=fmt):
                self.assertRaisesRegex(SystemError, 'invalid format string',
                    PyUnicode_FromFormat, fmt, b'abc')
        self.assertRaisesRegex(SystemError, 'invalid format string',
            PyUnicode_FromFormat, b'%+i', c_int(10))

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_interninplace(self):
        """Test PyUnicode_InternInPlace()"""
        from _testlimitedcapi import unicode_interninplace as interninplace

        s = b'abc'.decode()
        r = interninplace(s)
        self.assertEqual(r, 'abc')

        # CRASHES interninplace(b'abc')
        # CRASHES interninplace(NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_internfromstring(self):
        """Test PyUnicode_InternFromString()"""
        from _testlimitedcapi import unicode_internfromstring as internfromstring

        self.assertEqual(internfromstring(b'abc'), 'abc')
        self.assertEqual(internfromstring(b'\xf0\x9f\x98\x80'), '\U0001f600')
        self.assertRaises(UnicodeDecodeError, internfromstring, b'\xc2')
        self.assertRaises(UnicodeDecodeError, internfromstring, b'\xa1')
        self.assertEqual(internfromstring(b''), '')

        # CRASHES internfromstring(NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_fromwidechar(self):
        """Test PyUnicode_FromWideChar()"""
        from _testlimitedcapi import unicode_fromwidechar as fromwidechar
        from _testcapi import SIZEOF_WCHAR_T

        if SIZEOF_WCHAR_T == 2:
            encoding = 'utf-16le' if sys.byteorder == 'little' else 'utf-16be'
        elif SIZEOF_WCHAR_T == 4:
            encoding = 'utf-32le' if sys.byteorder == 'little' else 'utf-32be'

        for s in '', 'abc', '\xa1\xa2', '\u4f60', '\U0001f600':
            b = s.encode(encoding)
            self.assertEqual(fromwidechar(b), s)
            self.assertEqual(fromwidechar(b + b'\0'*SIZEOF_WCHAR_T, -1), s)
        for s in '\ud83d', '\ude00':
            b = s.encode(encoding, 'surrogatepass')
            self.assertEqual(fromwidechar(b), s)
            self.assertEqual(fromwidechar(b + b'\0'*SIZEOF_WCHAR_T, -1), s)

        for s in ('a\0é日😀', '\ud800\udc00', '\ud800x\udcff'):
            data = s.encode(encoding, 'surrogatepass')
            self.assertEqual(fromwidechar(data),
                             data.decode(encoding, 'surrogatepass'))
        if SIZEOF_WCHAR_T == 4:
            for value in (0x110000, 0xffffffff):
                with self.assertRaises(ValueError):
                    fromwidechar(value.to_bytes(4, sys.byteorder))

        self.assertEqual(fromwidechar('abc'.encode(encoding), 2), 'ab')
        if SIZEOF_WCHAR_T == 2:
            self.assertEqual(fromwidechar('a\U0001f600'.encode(encoding), 2), 'a\ud83d')

        self.assertRaises(SystemError, fromwidechar, b'\0'*SIZEOF_WCHAR_T, -2)
        self.assertEqual(fromwidechar(NULL, 0), '')
        self.assertRaises(SystemError, fromwidechar, NULL, 1)
        self.assertRaises(SystemError, fromwidechar, NULL, PY_SSIZE_T_MAX)
        self.assertRaises(SystemError, fromwidechar, NULL, -1)
        self.assertRaises(SystemError, fromwidechar, NULL, -2)
        self.assertRaises(SystemError, fromwidechar, NULL, PY_SSIZE_T_MIN)

        # The following tests are skipped since they rely on undefined behavior
        #self.assertRaises(MemoryError, fromwidechar, b'', PY_SSIZE_T_MAX)
        #self.assertRaises(SystemError, fromwidechar, b'\0'*SIZEOF_WCHAR_T, PY_SSIZE_T_MIN)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_aswidechar(self):
        """Test PyUnicode_AsWideChar()"""
        from _testlimitedcapi import unicode_aswidechar
        from _testlimitedcapi import unicode_aswidechar_null
        from _testcapi import SIZEOF_WCHAR_T

        wchar, size = unicode_aswidechar('abcdef', 2)
        self.assertEqual(size, 2)
        self.assertEqual(wchar, 'ab')

        wchar, size = unicode_aswidechar('abc', 3)
        self.assertEqual(size, 3)
        self.assertEqual(wchar, 'abc')
        self.assertEqual(unicode_aswidechar_null('abc', 10), 4)
        self.assertEqual(unicode_aswidechar_null('abc', 0), 4)

        wchar, size = unicode_aswidechar('abc', 4)
        self.assertEqual(size, 3)
        self.assertEqual(wchar, 'abc\0')

        wchar, size = unicode_aswidechar('abc', 10)
        self.assertEqual(size, 3)
        self.assertEqual(wchar, 'abc\0')

        wchar, size = unicode_aswidechar('abc\0def', 20)
        self.assertEqual(size, 7)
        self.assertEqual(wchar, 'abc\0def\0')
        self.assertEqual(unicode_aswidechar_null('abc\0def', 20), 8)

        nonbmp = chr(0x10ffff)
        if SIZEOF_WCHAR_T == 2:
            nchar = 2
        else: # SIZEOF_WCHAR_T == 4
            nchar = 1
        wchar, size = unicode_aswidechar(nonbmp, 10)
        self.assertEqual(size, nchar)
        self.assertEqual(wchar, nonbmp + '\0')
        self.assertEqual(unicode_aswidechar_null(nonbmp, 10), nchar + 1)

        self.assertRaises(TypeError, unicode_aswidechar, b'abc', 10)
        self.assertRaises(TypeError, unicode_aswidechar, [], 10)
        self.assertRaises(SystemError, unicode_aswidechar, NULL, 10)
        self.assertRaises(TypeError, unicode_aswidechar_null, b'abc', 10)
        self.assertRaises(TypeError, unicode_aswidechar_null, [], 10)
        self.assertRaises(SystemError, unicode_aswidechar_null, NULL, 10)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_aswidecharstring(self):
        """Test PyUnicode_AsWideCharString()"""
        from _testlimitedcapi import unicode_aswidecharstring
        from _testlimitedcapi import unicode_aswidecharstring_null
        from _testcapi import SIZEOF_WCHAR_T

        wchar, size = unicode_aswidecharstring('abc')
        self.assertEqual(size, 3)
        self.assertEqual(wchar, 'abc\0')
        self.assertEqual(unicode_aswidecharstring_null('abc'), 'abc')

        wchar, size = unicode_aswidecharstring('abc\0def')
        self.assertEqual(size, 7)
        self.assertEqual(wchar, 'abc\0def\0')
        self.assertRaises(ValueError, unicode_aswidecharstring_null, 'abc\0def')

        nonbmp = chr(0x10ffff)
        if SIZEOF_WCHAR_T == 2:
            nchar = 2
        else: # SIZEOF_WCHAR_T == 4
            nchar = 1
        wchar, size = unicode_aswidecharstring(nonbmp)
        self.assertEqual(size, nchar)
        self.assertEqual(wchar, nonbmp + '\0')
        self.assertEqual(unicode_aswidecharstring_null(nonbmp), nonbmp)

        self.assertRaises(TypeError, unicode_aswidecharstring, b'abc')
        self.assertRaises(TypeError, unicode_aswidecharstring, [])
        self.assertRaises(SystemError, unicode_aswidecharstring, NULL)
        self.assertRaises(TypeError, unicode_aswidecharstring_null, b'abc')
        self.assertRaises(TypeError, unicode_aswidecharstring_null, [])
        self.assertRaises(SystemError, unicode_aswidecharstring_null, NULL)

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_asucs4(self):
        """Test PyUnicode_AsUCS4()"""
        from _testcapi import unicode_asucs4

        for s in ['abc', '\xa1\xa2', '\u4f60\u597d', 'a\U0001f600',
                  'a\ud800b\udfffc', '\ud834\udd1e']:
            l = len(s)
            self.assertEqual(unicode_asucs4(s, l, 1), s+'\0')
            self.assertEqual(unicode_asucs4(s, l, 0), s+'\uffff')
            self.assertEqual(unicode_asucs4(s, l+1, 1), s+'\0\uffff')
            self.assertEqual(unicode_asucs4(s, l+1, 0), s+'\0\uffff')
            self.assertRaises(SystemError, unicode_asucs4, s, l-1, 1)
            self.assertRaises(SystemError, unicode_asucs4, s, l-2, 0)
            s = '\0'.join([s, s])
            self.assertEqual(unicode_asucs4(s, len(s), 1), s+'\0')
            self.assertEqual(unicode_asucs4(s, len(s), 0), s+'\uffff')

        # CRASHES unicode_asucs4(b'abc', 1, 0)
        # CRASHES unicode_asucs4(b'abc', 1, 1)
        # CRASHES unicode_asucs4([], 1, 1)
        # CRASHES unicode_asucs4(NULL, 1, 0)
        # CRASHES unicode_asucs4(NULL, 1, 1)

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_asucs4copy(self):
        """Test PyUnicode_AsUCS4Copy()"""
        from _testcapi import unicode_asucs4copy as asucs4copy

        for s in ['abc', '\xa1\xa2', '\u4f60\u597d', 'a\U0001f600',
                  'a\ud800b\udfffc', '\ud834\udd1e']:
            self.assertEqual(asucs4copy(s), s+'\0')
            s = '\0'.join([s, s])
            self.assertEqual(asucs4copy(s), s+'\0')

        # CRASHES asucs4copy(b'abc')
        # CRASHES asucs4copy([])
        # CRASHES asucs4copy(NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_fromordinal(self):
        """Test PyUnicode_FromOrdinal()"""
        from _testlimitedcapi import unicode_fromordinal as fromordinal

        self.assertEqual(fromordinal(0x61), 'a')
        self.assertEqual(fromordinal(0x20ac), '\u20ac')
        self.assertEqual(fromordinal(0x1f600), '\U0001f600')

        self.assertRaises(ValueError, fromordinal, 0x110000)
        self.assertRaises(ValueError, fromordinal, -1)

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_asutf8(self):
        """Test PyUnicode_AsUTF8()"""
        from _testcapi import unicode_asutf8

        self.assertEqual(unicode_asutf8('abc', 4), b'abc\0')
        self.assertEqual(unicode_asutf8('абв', 7), b'\xd0\xb0\xd0\xb1\xd0\xb2\0')
        self.assertEqual(unicode_asutf8('\U0001f600', 5), b'\xf0\x9f\x98\x80\0')
        self.assertEqual(unicode_asutf8('abc\0def', 8), b'abc\0def\0')

        self.assertRaises(UnicodeEncodeError, unicode_asutf8, '\ud8ff', 0)
        self.assertRaises(TypeError, unicode_asutf8, b'abc', 0)
        self.assertRaises(TypeError, unicode_asutf8, [], 0)
        # CRASHES unicode_asutf8(NULL, 0)

    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    @threading_helper.requires_working_threading()
    def test_asutf8_race(self):
        """Test that there's no race condition in PyUnicode_AsUTF8()"""
        unicode_asutf8 = _testcapi.unicode_asutf8
        from threading import Thread

        data = "😊"

        def worker():
            for _ in range(1000):
                self.assertEqual(unicode_asutf8(data, 5), b'\xf0\x9f\x98\x8a\0')

        threads = [Thread(target=worker) for _ in range(10)]
        with threading_helper.start_threads(threads):
            pass


    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_asutf8andsize(self):
        """Test PyUnicode_AsUTF8AndSize()"""
        from _testlimitedcapi import unicode_asutf8andsize
        from _testlimitedcapi import unicode_asutf8andsize_null

        self.assertEqual(unicode_asutf8andsize('abc', 4), (b'abc\0', 3))
        self.assertEqual(unicode_asutf8andsize('абв', 7), (b'\xd0\xb0\xd0\xb1\xd0\xb2\0', 6))
        self.assertEqual(unicode_asutf8andsize('\U0001f600', 5), (b'\xf0\x9f\x98\x80\0', 4))
        self.assertEqual(unicode_asutf8andsize('abc\0def', 8), (b'abc\0def\0', 7))
        self.assertEqual(unicode_asutf8andsize_null('abc', 4), b'abc\0')
        self.assertEqual(unicode_asutf8andsize_null('abc\0def', 8), b'abc\0def\0')

        self.assertRaises(UnicodeEncodeError, unicode_asutf8andsize, '\ud8ff', 0)
        self.assertRaises(TypeError, unicode_asutf8andsize, b'abc', 0)
        self.assertRaises(TypeError, unicode_asutf8andsize, [], 0)
        self.assertRaises(UnicodeEncodeError, unicode_asutf8andsize_null, '\ud8ff', 0)
        self.assertRaises(TypeError, unicode_asutf8andsize_null, b'abc', 0)
        self.assertRaises(TypeError, unicode_asutf8andsize_null, [], 0)
        # CRASHES unicode_asutf8andsize(NULL, 0)
        # CRASHES unicode_asutf8andsize_null(NULL, 0)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_getdefaultencoding(self):
        """Test PyUnicode_GetDefaultEncoding()"""
        from _testlimitedcapi import unicode_getdefaultencoding as getdefaultencoding

        self.assertEqual(getdefaultencoding(), b'utf-8')

    @support.cpython_only
    @unittest.skipIf(_testinternalcapi is None, 'need _testinternalcapi module')
    def test_transform_decimal_and_space(self):
        """Test _PyUnicode_TransformDecimalAndSpaceToASCII()"""
        from _testinternalcapi import _PyUnicode_TransformDecimalAndSpaceToASCII as transform_decimal

        self.assertEqual(transform_decimal('123'),
                         '123')
        self.assertEqual(transform_decimal('\u0663.\u0661\u0664'),
                         '3.14')
        self.assertEqual(transform_decimal("\N{EM SPACE}3.14\N{EN SPACE}"),
                         " 3.14 ")
        self.assertEqual(transform_decimal('12\u20ac3'),
                         '12?')
        self.assertEqual(transform_decimal(''), '')

        self.assertRaises(SystemError, transform_decimal, b'123')
        self.assertRaises(SystemError, transform_decimal, [])
        # CRASHES transform_decimal(NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_concat(self):
        """Test PyUnicode_Concat()"""
        from _testlimitedcapi import unicode_concat as concat

        self.assertEqual(concat('abc', 'def'), 'abcdef')
        self.assertEqual(concat('abc', 'где'), 'abcгде')
        self.assertEqual(concat('абв', 'def'), 'абвdef')
        self.assertEqual(concat('абв', 'где'), 'абвгде')
        self.assertEqual(concat('a\0b', 'c\0d'), 'a\0bc\0d')

        self.assertRaises(TypeError, concat, b'abc', 'def')
        self.assertRaises(TypeError, concat, 'abc', b'def')
        self.assertRaises(TypeError, concat, b'abc', b'def')
        self.assertRaises(TypeError, concat, [], 'def')
        self.assertRaises(TypeError, concat, 'abc', [])
        self.assertRaises(TypeError, concat, [], [])
        # CRASHES concat(NULL, 'def')
        # CRASHES concat('abc', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_split(self):
        """Test PyUnicode_Split()"""
        from _testlimitedcapi import unicode_split as split

        self.assertEqual(split('a|b|c|d', '|'), ['a', 'b', 'c', 'd'])
        self.assertEqual(split('a|b|c|d', '|', 2), ['a', 'b', 'c|d'])
        self.assertEqual(split('a|b|c|d', '|', PY_SSIZE_T_MAX),
                         ['a', 'b', 'c', 'd'])
        self.assertEqual(split('a|b|c|d', '|', -1), ['a', 'b', 'c', 'd'])
        self.assertEqual(split('a|b|c|d', '|', PY_SSIZE_T_MIN),
                         ['a', 'b', 'c', 'd'])
        self.assertEqual(split('a|b|c|d', '\u20ac'), ['a|b|c|d'])
        self.assertEqual(split('a||b|c||d', '||'), ['a', 'b|c', 'd'])
        self.assertEqual(split('а|б|в|г', '|'), ['а', 'б', 'в', 'г'])
        self.assertEqual(split('абабагаламага', 'а'),
                         ['', 'б', 'б', 'г', 'л', 'м', 'г', ''])
        self.assertEqual(split(' a\tb\nc\rd\ve\f', NULL),
                         ['a', 'b', 'c', 'd', 'e'])
        self.assertEqual(split('a\x85b\xa0c\u1680d\u2000e', NULL),
                         ['a', 'b', 'c', 'd', 'e'])

        self.assertRaises(ValueError, split, 'a|b|c|d', '')
        self.assertRaises(TypeError, split, 'a|b|c|d', ord('|'))
        self.assertRaises(TypeError, split, [], '|')
        # CRASHES split(NULL, '|')

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_rsplit(self):
        """Test PyUnicode_RSplit()"""
        from _testlimitedcapi import unicode_rsplit as rsplit

        self.assertEqual(rsplit('a|b|c|d', '|'), ['a', 'b', 'c', 'd'])
        self.assertEqual(rsplit('a|b|c|d', '|', 2), ['a|b', 'c', 'd'])
        self.assertEqual(rsplit('a|b|c|d', '|', PY_SSIZE_T_MAX),
                         ['a', 'b', 'c', 'd'])
        self.assertEqual(rsplit('a|b|c|d', '|', -1), ['a', 'b', 'c', 'd'])
        self.assertEqual(rsplit('a|b|c|d', '|', PY_SSIZE_T_MIN),
                         ['a', 'b', 'c', 'd'])
        self.assertEqual(rsplit('a|b|c|d', '\u20ac'), ['a|b|c|d'])
        self.assertEqual(rsplit('a||b|c||d', '||'), ['a', 'b|c', 'd'])
        self.assertEqual(rsplit('а|б|в|г', '|'), ['а', 'б', 'в', 'г'])
        self.assertEqual(rsplit('абабагаламага', 'а'),
                         ['', 'б', 'б', 'г', 'л', 'м', 'г', ''])
        self.assertEqual(rsplit('aжbжcжd', 'ж'), ['a', 'b', 'c', 'd'])
        self.assertEqual(rsplit(' a\tb\nc\rd\ve\f', NULL),
                         ['a', 'b', 'c', 'd', 'e'])
        self.assertEqual(rsplit('a\x85b\xa0c\u1680d\u2000e', NULL),
                         ['a', 'b', 'c', 'd', 'e'])

        self.assertRaises(ValueError, rsplit, 'a|b|c|d', '')
        self.assertRaises(TypeError, rsplit, 'a|b|c|d', ord('|'))
        self.assertRaises(TypeError, rsplit, [], '|')
        # CRASHES rsplit(NULL, '|')

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_partition(self):
        """Test PyUnicode_Partition()"""
        from _testlimitedcapi import unicode_partition as partition

        self.assertEqual(partition('a|b|c', '|'), ('a', '|', 'b|c'))
        self.assertEqual(partition('a||b||c', '||'), ('a', '||', 'b||c'))
        self.assertEqual(partition('а|б|в', '|'), ('а', '|', 'б|в'))
        self.assertEqual(partition('кабан', 'а'), ('к', 'а', 'бан'))
        self.assertEqual(partition('aжbжc', 'ж'), ('a', 'ж', 'bжc'))

        self.assertRaises(ValueError, partition, 'a|b|c', '')
        self.assertRaises(TypeError, partition, b'a|b|c', '|')
        self.assertRaises(TypeError, partition, 'a|b|c', b'|')
        self.assertRaises(TypeError, partition, 'a|b|c', ord('|'))
        self.assertRaises(TypeError, partition, [], '|')
        # CRASHES partition(NULL, '|')
        # CRASHES partition('a|b|c', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_rpartition(self):
        """Test PyUnicode_RPartition()"""
        from _testlimitedcapi import unicode_rpartition as rpartition

        self.assertEqual(rpartition('a|b|c', '|'), ('a|b', '|', 'c'))
        self.assertEqual(rpartition('a||b||c', '||'), ('a||b', '||', 'c'))
        self.assertEqual(rpartition('а|б|в', '|'), ('а|б', '|', 'в'))
        self.assertEqual(rpartition('кабан', 'а'), ('каб', 'а', 'н'))
        self.assertEqual(rpartition('aжbжc', 'ж'), ('aжb', 'ж', 'c'))

        self.assertRaises(ValueError, rpartition, 'a|b|c', '')
        self.assertRaises(TypeError, rpartition, b'a|b|c', '|')
        self.assertRaises(TypeError, rpartition, 'a|b|c', b'|')
        self.assertRaises(TypeError, rpartition, 'a|b|c', ord('|'))
        self.assertRaises(TypeError, rpartition, [], '|')
        # CRASHES rpartition(NULL, '|')
        # CRASHES rpartition('a|b|c', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_splitlines(self):
        """Test PyUnicode_SplitLines()"""
        from _testlimitedcapi import unicode_splitlines as splitlines

        self.assertEqual(splitlines('a\nb\rc\r\nd'), ['a', 'b', 'c', 'd'])
        self.assertEqual(splitlines('a\nb\rc\r\nd', True),
                         ['a\n', 'b\r', 'c\r\n', 'd'])
        self.assertEqual(splitlines('a\x85b\u2028c\u2029d'),
                         ['a', 'b', 'c', 'd'])
        self.assertEqual(splitlines('a\x85b\u2028c\u2029d', True),
                         ['a\x85', 'b\u2028', 'c\u2029', 'd'])
        self.assertEqual(splitlines('а\nб\rв\r\nг'), ['а', 'б', 'в', 'г'])

        self.assertRaises(TypeError, splitlines, b'a\nb\rc\r\nd')
        # CRASHES splitlines(NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_translate(self):
        """Test PyUnicode_Translate()"""
        from _testlimitedcapi import unicode_translate as translate

        self.assertEqual(translate('abcd', {ord('a'): 'A', ord('b'): ord('B'), ord('c'): '<>'}), 'AB<>d')
        self.assertEqual(translate('абвг', {ord('а'): 'А', ord('б'): ord('Б'), ord('в'): '<>'}), 'АБ<>г')
        self.assertEqual(translate('abc', {}), 'abc')
        self.assertEqual(translate('abc', []), 'abc')
        self.assertRaises(UnicodeTranslateError, translate, 'abc', {ord('b'): None})
        self.assertRaises(UnicodeTranslateError, translate, 'abc', {ord('b'): None}, 'strict')
        self.assertRaises(LookupError, translate, 'abc', {ord('b'): None}, 'foo')
        self.assertEqual(translate('abc', {ord('b'): None}, 'ignore'), 'ac')
        self.assertEqual(translate('abc', {ord('b'): None}, 'replace'), 'a\ufffdc')
        self.assertEqual(translate('abc', {ord('b'): None}, 'backslashreplace'), r'a\x62c')
        # XXX Other error handlers do not support UnicodeTranslateError
        self.assertRaises(TypeError, translate, b'abc', [])
        self.assertRaises(TypeError, translate, 123, [])
        self.assertRaises(TypeError, translate, 'abc', {ord('a'): b'A'})
        self.assertRaises(TypeError, translate, 'abc', 123)
        self.assertRaises(TypeError, translate, 'abc', NULL)
        self.assertRaises(LookupError, translate, 'abc', {ord('b'): None}, 'foo')
        # CRASHES translate(NULL, [])

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_join(self):
        """Test PyUnicode_Join()"""
        from _testlimitedcapi import unicode_join as join
        self.assertEqual(join('|', ['a', 'b', 'c']), 'a|b|c')
        self.assertEqual(join('|', ['a', '', 'c']), 'a||c')
        self.assertEqual(join('', ['a', 'b', 'c']), 'abc')
        self.assertEqual(join(NULL, ['a', 'b', 'c']), 'a b c')
        self.assertEqual(join('|', ['а', 'б', 'в']), 'а|б|в')
        self.assertEqual(join('ж', ['а', 'б', 'в']), 'ажбжв')
        self.assertRaises(TypeError, join, b'|', ['a', 'b', 'c'])
        self.assertRaises(TypeError, join, '|', [b'a', b'b', b'c'])
        self.assertRaises(TypeError, join, NULL, [b'a', b'b', b'c'])
        self.assertRaises(TypeError, join, '|', b'123')
        self.assertRaises(TypeError, join, '|', 123)
        self.assertRaises(SystemError, join, '|', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_count(self):
        """Test PyUnicode_Count()"""
        from _testlimitedcapi import unicode_count

        for str in "\xa1", "\u8000\u8080", "\ud800\udc02", "\U0001f100\U0001f1f1":
            for i, ch in enumerate(str):
                self.assertEqual(unicode_count(str, ch, 0, len(str)), 1)

        str = "!>_<!"
        self.assertEqual(unicode_count(str, 'z', 0, len(str)), 0)
        self.assertEqual(unicode_count(str, '', 0, len(str)), len(str)+1)
        # start < end
        self.assertEqual(unicode_count(str, '!', 1, len(str)+1), 1)
        self.assertEqual(unicode_count(str, '!', 1, PY_SSIZE_T_MAX), 1)
        # start >= end
        self.assertEqual(unicode_count(str, '!', 0, 0), 0)
        self.assertEqual(unicode_count(str, '!', len(str), 0), 0)
        # negative
        self.assertEqual(unicode_count(str, '!', -len(str), -1), 1)
        self.assertEqual(unicode_count(str, '!', -len(str)-1, -1), 1)
        self.assertEqual(unicode_count(str, '!', PY_SSIZE_T_MIN, -1), 1)
        # bad arguments
        self.assertRaises(TypeError, unicode_count, str, b'!', 0, len(str))
        self.assertRaises(TypeError, unicode_count, b"!>_<!", '!', 0, len(str))
        self.assertRaises(TypeError, unicode_count, str, ord('!'), 0, len(str))
        self.assertRaises(TypeError, unicode_count, [], '!', 0, len(str), 1)
        # CRASHES unicode_count(NULL, '!', 0, len(str))
        # CRASHES unicode_count(str, NULL, 0, len(str))

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_tailmatch(self):
        """Test PyUnicode_Tailmatch()"""
        from _testlimitedcapi import unicode_tailmatch as tailmatch

        str = 'ababahalamaha'
        self.assertEqual(tailmatch(str, 'aba', 0, len(str), -1), 1)
        self.assertEqual(tailmatch(str, 'aha', 0, len(str), 1), 1)

        self.assertEqual(tailmatch(str, 'aba', 0, PY_SSIZE_T_MAX, -1), 1)
        self.assertEqual(tailmatch(str, 'aba', -len(str), PY_SSIZE_T_MAX, -1), 1)
        self.assertEqual(tailmatch(str, 'aba', PY_SSIZE_T_MIN, len(str), -1), 1)
        self.assertEqual(tailmatch(str, 'aha', 0, PY_SSIZE_T_MAX, 1), 1)
        self.assertEqual(tailmatch(str, 'aha', PY_SSIZE_T_MIN, len(str), 1), 1)

        self.assertEqual(tailmatch(str, 'z', 0, len(str), 1), 0)
        self.assertEqual(tailmatch(str, 'z', 0, len(str), -1), 0)
        self.assertEqual(tailmatch(str, '', 0, len(str), 1), 1)
        self.assertEqual(tailmatch(str, '', 0, len(str), -1), 1)

        self.assertEqual(tailmatch(str, 'ba', 0, len(str)-1, -1), 0)
        self.assertEqual(tailmatch(str, 'ba', 1, len(str)-1, -1), 1)
        self.assertEqual(tailmatch(str, 'aba', 1, len(str)-1, -1), 0)
        self.assertEqual(tailmatch(str, 'ba', -len(str)+1, -1, -1), 1)
        self.assertEqual(tailmatch(str, 'ah', 0, len(str), 1), 0)
        self.assertEqual(tailmatch(str, 'ah', 0, len(str)-1, 1), 1)
        self.assertEqual(tailmatch(str, 'ah', -len(str), -1, 1), 1)

        # bad arguments
        self.assertRaises(TypeError, tailmatch, str, ('aba', 'aha'), 0, len(str), -1)
        self.assertRaises(TypeError, tailmatch, str, ('aba', 'aha'), 0, len(str), 1)
        # CRASHES tailmatch(NULL, 'aba', 0, len(str), -1)
        # CRASHES tailmatch(str, NULL, 0, len(str), -1)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_find(self):
        """Test PyUnicode_Find()"""
        from _testlimitedcapi import unicode_find as find

        for str in "\xa1", "\u8000\u8080", "\ud800\udc02", "\U0001f100\U0001f1f1":
            for i, ch in enumerate(str):
                self.assertEqual(find(str, ch, 0, len(str), 1), i)
                self.assertEqual(find(str, ch, 0, len(str), -1), i)

        str = "!>_<!"
        self.assertEqual(find(str, 'z', 0, len(str), 1), -1)
        self.assertEqual(find(str, 'z', 0, len(str), -1), -1)
        self.assertEqual(find(str, '', 0, len(str), 1), 0)
        self.assertEqual(find(str, '', 0, len(str), -1), len(str))
        # start < end
        self.assertEqual(find(str, '!', 1, len(str)+1, 1), 4)
        self.assertEqual(find(str, '!', 1, PY_SSIZE_T_MAX, 1), 4)
        self.assertEqual(find(str, '!', 0, len(str)+1, -1), 4)
        self.assertEqual(find(str, '!', 0, PY_SSIZE_T_MAX, -1), 4)
        # start >= end
        self.assertEqual(find(str, '!', 0, 0, 1), -1)
        self.assertEqual(find(str, '!', 0, 0, -1), -1)
        self.assertEqual(find(str, '!', len(str), 0, 1), -1)
        self.assertEqual(find(str, '!', len(str), 0, -1), -1)
        # negative
        self.assertEqual(find(str, '!', -len(str), -1, 1), 0)
        self.assertEqual(find(str, '!', -len(str), -1, -1), 0)
        self.assertEqual(find(str, '!', PY_SSIZE_T_MIN, -1, 1), 0)
        self.assertEqual(find(str, '!', PY_SSIZE_T_MIN, -1, -1), 0)
        self.assertEqual(find(str, '!', PY_SSIZE_T_MIN, PY_SSIZE_T_MAX, 1), 0)
        self.assertEqual(find(str, '!', PY_SSIZE_T_MIN, PY_SSIZE_T_MAX, -1), 4)
        # bad arguments
        self.assertRaises(TypeError, find, str, b'!', 0, len(str), 1)
        self.assertRaises(TypeError, find, b"!>_<!", '!', 0, len(str), 1)
        self.assertRaises(TypeError, find, str, ord('!'), 0, len(str), 1)
        self.assertRaises(TypeError, find, [], '!', 0, len(str), 1)
        # CRASHES find(NULL, '!', 0, len(str), 1)
        # CRASHES find(str, NULL, 0, len(str), 1)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_findchar(self):
        """Test PyUnicode_FindChar()"""
        from _testlimitedcapi import unicode_findchar

        for str in "\xa1", "\u8000\u8080", "\ud800\udc02", "\U0001f100\U0001f1f1":
            for i, ch in enumerate(str):
                self.assertEqual(unicode_findchar(str, ord(ch), 0, len(str), 1), i)
                self.assertEqual(unicode_findchar(str, ord(ch), 0, len(str), -1), i)

        str = "!>_<!"
        self.assertEqual(unicode_findchar(str, 0x110000, 0, len(str), 1), -1)
        self.assertEqual(unicode_findchar(str, 0x110000, 0, len(str), -1), -1)
        # start < end
        self.assertEqual(unicode_findchar(str, ord('!'), 1, len(str)+1, 1), 4)
        self.assertEqual(unicode_findchar(str, ord('!'), 1, PY_SSIZE_T_MAX, 1), 4)
        self.assertEqual(unicode_findchar(str, ord('!'), 0, len(str)+1, -1), 4)
        self.assertEqual(unicode_findchar(str, ord('!'), 0, PY_SSIZE_T_MAX, -1), 4)
        # start >= end
        self.assertEqual(unicode_findchar(str, ord('!'), 0, 0, 1), -1)
        self.assertEqual(unicode_findchar(str, ord('!'), 0, 0, -1), -1)
        self.assertEqual(unicode_findchar(str, ord('!'), len(str), 0, 1), -1)
        self.assertEqual(unicode_findchar(str, ord('!'), len(str), 0, -1), -1)
        # negative
        self.assertEqual(unicode_findchar(str, ord('!'), -len(str), -1, 1), 0)
        self.assertEqual(unicode_findchar(str, ord('!'), -len(str), -1, -1), 0)
        self.assertEqual(unicode_findchar(str, ord('!'), PY_SSIZE_T_MIN, -1, 1), 0)
        self.assertEqual(unicode_findchar(str, ord('!'), PY_SSIZE_T_MIN, -1, -1), 0)
        self.assertEqual(unicode_findchar(str, ord('!'), PY_SSIZE_T_MIN, PY_SSIZE_T_MAX, 1), 0)
        self.assertEqual(unicode_findchar(str, ord('!'), PY_SSIZE_T_MIN, PY_SSIZE_T_MAX, -1), 4)
        # bad arguments
        # CRASHES unicode_findchar(b"!>_<!", ord('!'), 0, len(str), 1)
        # CRASHES unicode_findchar([], ord('!'), 0, len(str), 1)
        # CRASHES unicode_findchar(NULL, ord('!'), 0, len(str), 1), 1)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_replace(self):
        """Test PyUnicode_Replace()"""
        from _testlimitedcapi import unicode_replace as replace

        str = 'abracadabra'
        self.assertEqual(replace(str, 'a', '='), '=br=c=d=br=')
        self.assertEqual(replace(str, 'a', '<>'), '<>br<>c<>d<>br<>')
        self.assertEqual(replace(str, 'abra', '='), '=cad=')
        self.assertEqual(replace(str, 'a', '=', 2), '=br=cadabra')
        self.assertEqual(replace(str, 'a', '=', 0), str)
        self.assertEqual(replace(str, 'a', '=', PY_SSIZE_T_MAX), '=br=c=d=br=')
        self.assertEqual(replace(str, 'a', '=', -1), '=br=c=d=br=')
        self.assertEqual(replace(str, 'a', '=', PY_SSIZE_T_MIN), '=br=c=d=br=')
        self.assertEqual(replace(str, 'z', '='), str)
        self.assertEqual(replace(str, '', '='), '=a=b=r=a=c=a=d=a=b=r=a=')
        self.assertEqual(replace(str, 'a', 'ж'), 'жbrжcжdжbrж')
        self.assertEqual(replace('абабагаламага', 'а', '='), '=б=б=г=л=м=г=')
        self.assertEqual(replace('Баден-Баден', 'Баден', 'Baden'), 'Baden-Baden')
        # bad arguments
        self.assertRaises(TypeError, replace, 'a', 'a', b'=')
        self.assertRaises(TypeError, replace, 'a', b'a', '=')
        self.assertRaises(TypeError, replace, b'a', 'a', '=')
        self.assertRaises(TypeError, replace, 'a', 'a', ord('='))
        self.assertRaises(TypeError, replace, 'a', ord('a'), '=')
        self.assertRaises(TypeError, replace, [], 'a', '=')
        # CRASHES replace('a', 'a', NULL)
        # CRASHES replace('a', NULL, '=')
        # CRASHES replace(NULL, 'a', '=')

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_compare(self):
        """Test PyUnicode_Compare()"""
        from _testlimitedcapi import unicode_compare as compare

        self.assertEqual(compare('abc', 'abc'), 0)
        self.assertEqual(compare('abc', 'def'), -1)
        self.assertEqual(compare('def', 'abc'), 1)
        self.assertEqual(compare('abc', 'abc\0def'), -1)
        self.assertEqual(compare('abc\0def', 'abc\0def'), 0)
        self.assertEqual(compare('абв', 'abc'), 1)

        self.assertRaises(TypeError, compare, b'abc', 'abc')
        self.assertRaises(TypeError, compare, 'abc', b'abc')
        self.assertRaises(TypeError, compare, b'abc', b'abc')
        self.assertRaises(TypeError, compare, [], 'abc')
        self.assertRaises(TypeError, compare, 'abc', [])
        self.assertRaises(TypeError, compare, [], [])
        # CRASHES compare(NULL, 'abc')
        # CRASHES compare('abc', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_comparewithasciistring(self):
        """Test PyUnicode_CompareWithASCIIString()"""
        from _testlimitedcapi import unicode_comparewithasciistring as comparewithasciistring

        self.assertEqual(comparewithasciistring('abc', b'abc'), 0)
        self.assertEqual(comparewithasciistring('abc', b'def'), -1)
        self.assertEqual(comparewithasciistring('def', b'abc'), 1)
        self.assertEqual(comparewithasciistring('abc', b'abc\0def'), 0)
        self.assertEqual(comparewithasciistring('abc\0def', b'abc\0def'), 1)
        self.assertEqual(comparewithasciistring('абв', b'abc'), 1)

        # CRASHES comparewithasciistring(b'abc', b'abc')
        # CRASHES comparewithasciistring([], b'abc')
        # CRASHES comparewithasciistring(NULL, b'abc')

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_equaltoutf8(self):
        # Test PyUnicode_EqualToUTF8()
        from _testlimitedcapi import unicode_equaltoutf8 as equaltoutf8
        from _testlimitedcapi import unicode_asutf8andsize as asutf8andsize

        strings = [
            'abc', '\xa1\xa2\xa3', '\u4f60\u597d\u4e16',
            '\U0001f600\U0001f601\U0001f602',
            '\U0010ffff',
        ]
        for s in strings:
            # Call PyUnicode_AsUTF8AndSize() which creates the UTF-8
            # encoded string cached in the Unicode object.
            asutf8andsize(s, 0)
            b = s.encode()
            self.assertEqual(equaltoutf8(s, b), 1)  # Use the UTF-8 cache.
            s2 = b.decode()  # New Unicode object without the UTF-8 cache.
            self.assertEqual(equaltoutf8(s2, b), 1)
            self.assertEqual(equaltoutf8(s + 'x', b + b'x'), 1)
            self.assertEqual(equaltoutf8(s + 'x', b + b'y'), 0)
            self.assertEqual(equaltoutf8(s, b + b'\0'), 1)
            self.assertEqual(equaltoutf8(s2, b + b'\0'), 1)
            self.assertEqual(equaltoutf8(s + '\0', b + b'\0'), 0)
            self.assertEqual(equaltoutf8(s + '\0', b), 0)
            self.assertEqual(equaltoutf8(s2, b + b'x'), 0)
            self.assertEqual(equaltoutf8(s2, b[:-1]), 0)
            self.assertEqual(equaltoutf8(s2, b[:-1] + b'x'), 0)

        self.assertEqual(equaltoutf8('', b''), 1)
        self.assertEqual(equaltoutf8('', b'\0'), 1)

        # embedded null chars/bytes
        self.assertEqual(equaltoutf8('abc', b'abc\0def\0'), 1)
        self.assertEqual(equaltoutf8('a\0bc', b'abc'), 0)
        self.assertEqual(equaltoutf8('abc', b'a\0bc'), 0)

        # Surrogate characters are always treated as not equal
        self.assertEqual(equaltoutf8('\udcfe',
                            '\udcfe'.encode("utf8", "surrogateescape")), 0)
        self.assertEqual(equaltoutf8('\udcfe',
                            '\udcfe'.encode("utf8", "surrogatepass")), 0)
        self.assertEqual(equaltoutf8('\ud801',
                            '\ud801'.encode("utf8", "surrogatepass")), 0)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_equaltoutf8andsize(self):
        # Test PyUnicode_EqualToUTF8AndSize()
        from _testlimitedcapi import unicode_equaltoutf8andsize as equaltoutf8andsize
        from _testlimitedcapi import unicode_asutf8andsize as asutf8andsize

        strings = [
            'abc', '\xa1\xa2\xa3', '\u4f60\u597d\u4e16',
            '\U0001f600\U0001f601\U0001f602',
            '\U0010ffff',
        ]
        for s in strings:
            # Call PyUnicode_AsUTF8AndSize() which creates the UTF-8
            # encoded string cached in the Unicode object.
            asutf8andsize(s, 0)
            b = s.encode()
            self.assertEqual(equaltoutf8andsize(s, b), 1)  # Use the UTF-8 cache.
            s2 = b.decode()  # New Unicode object without the UTF-8 cache.
            self.assertEqual(equaltoutf8andsize(s2, b), 1)
            self.assertEqual(equaltoutf8andsize(s + 'x', b + b'x'), 1)
            self.assertEqual(equaltoutf8andsize(s + 'x', b + b'y'), 0)
            self.assertEqual(equaltoutf8andsize(s, b + b'\0'), 0)
            self.assertEqual(equaltoutf8andsize(s2, b + b'\0'), 0)
            self.assertEqual(equaltoutf8andsize(s + '\0', b + b'\0'), 1)
            self.assertEqual(equaltoutf8andsize(s + '\0', b), 0)
            self.assertEqual(equaltoutf8andsize(s2, b + b'x'), 0)
            self.assertEqual(equaltoutf8andsize(s2, b[:-1]), 0)
            self.assertEqual(equaltoutf8andsize(s2, b[:-1] + b'x'), 0)
            # Not null-terminated,
            self.assertEqual(equaltoutf8andsize(s, b + b'x', len(b)), 1)
            self.assertEqual(equaltoutf8andsize(s2, b + b'x', len(b)), 1)
            self.assertEqual(equaltoutf8andsize(s + '\0', b + b'\0x', len(b) + 1), 1)
            self.assertEqual(equaltoutf8andsize(s2, b, len(b) - 1), 0)
            self.assertEqual(equaltoutf8andsize(s, b, -1), 0)
            self.assertEqual(equaltoutf8andsize(s, b, PY_SSIZE_T_MAX), 0)
            self.assertEqual(equaltoutf8andsize(s, b, PY_SSIZE_T_MIN), 0)

        self.assertEqual(equaltoutf8andsize('', b''), 1)
        self.assertEqual(equaltoutf8andsize('', b'\0'), 0)
        self.assertEqual(equaltoutf8andsize('', b'x', 0), 1)

        # embedded null chars/bytes
        self.assertEqual(equaltoutf8andsize('abc\0def', b'abc\0def'), 1)
        self.assertEqual(equaltoutf8andsize('abc\0def\0', b'abc\0def\0'), 1)

        # Surrogate characters are always treated as not equal
        self.assertEqual(equaltoutf8andsize('\udcfe',
                            '\udcfe'.encode("utf8", "surrogateescape")), 0)
        self.assertEqual(equaltoutf8andsize('\udcfe',
                            '\udcfe'.encode("utf8", "surrogatepass")), 0)
        self.assertEqual(equaltoutf8andsize('\ud801',
                            '\ud801'.encode("utf8", "surrogatepass")), 0)

        def check_not_equal_encoding(text, encoding):
            self.assertEqual(equaltoutf8andsize(text, text.encode(encoding)), 0)
            self.assertNotEqual(text.encode(encoding), text.encode("utf8"))

        # Strings encoded to other encodings are not equal to expected UTF8-encoding string
        check_not_equal_encoding('Stéphane', 'latin1')
        check_not_equal_encoding('Stéphane', 'utf-16-le')  # embedded null characters
        check_not_equal_encoding('北京市', 'gbk')

        # CRASHES equaltoutf8andsize('abc', b'abc', -1)
        # CRASHES equaltoutf8andsize(b'abc', b'abc')
        # CRASHES equaltoutf8andsize([], b'abc')
        # CRASHES equaltoutf8andsize(NULL, b'abc')
        # CRASHES equaltoutf8andsize('abc', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_richcompare(self):
        """Test PyUnicode_RichCompare()"""
        from _testlimitedcapi import unicode_richcompare as richcompare

        LT, LE, EQ, NE, GT, GE = range(6)
        strings = ('abc', 'абв', '\U0001f600', 'abc\0')
        for s1 in strings:
            for s2 in strings:
                self.assertIs(richcompare(s1, s2, LT), s1 < s2)
                self.assertIs(richcompare(s1, s2, LE), s1 <= s2)
                self.assertIs(richcompare(s1, s2, EQ), s1 == s2)
                self.assertIs(richcompare(s1, s2, NE), s1 != s2)
                self.assertIs(richcompare(s1, s2, GT), s1 > s2)
                self.assertIs(richcompare(s1, s2, GE), s1 >= s2)

        for op in LT, LE, EQ, NE, GT, GE:
            self.assertIs(richcompare(b'abc', 'abc', op), NotImplemented)
            self.assertIs(richcompare('abc', b'abc', op), NotImplemented)
            self.assertIs(richcompare(b'abc', b'abc', op), NotImplemented)
            self.assertIs(richcompare([], 'abc', op), NotImplemented)
            self.assertIs(richcompare('abc', [], op), NotImplemented)
            self.assertIs(richcompare([], [], op), NotImplemented)

            # CRASHES richcompare(NULL, 'abc', op)
            # CRASHES richcompare('abc', NULL, op)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_format(self):
        """Test PyUnicode_Format()"""
        from _testlimitedcapi import unicode_format as format

        self.assertEqual(format('x=%d!', 42), 'x=42!')
        self.assertEqual(format('x=%d!', (42,)), 'x=42!')
        self.assertEqual(format('x=%d y=%s!', (42, [])), 'x=42 y=[]!')

        self.assertRaises(SystemError, format, 'x=%d!', NULL)
        self.assertRaises(SystemError, format, NULL, 42)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_contains(self):
        """Test PyUnicode_Contains()"""
        from _testlimitedcapi import unicode_contains as contains

        self.assertEqual(contains('abcd', ''), 1)
        self.assertEqual(contains('abcd', 'b'), 1)
        self.assertEqual(contains('abcd', 'x'), 0)
        self.assertEqual(contains('abcd', 'ж'), 0)
        self.assertEqual(contains('abcd', '\0'), 0)
        self.assertEqual(contains('abc\0def', '\0'), 1)
        self.assertEqual(contains('abcd', 'bc'), 1)

        self.assertRaises(TypeError, contains, b'abcd', 'b')
        self.assertRaises(TypeError, contains, 'abcd', b'b')
        self.assertRaises(TypeError, contains, b'abcd', b'b')
        self.assertRaises(TypeError, contains, [], 'b')
        self.assertRaises(TypeError, contains, 'abcd', ord('b'))
        # CRASHES contains(NULL, 'b')
        # CRASHES contains('abcd', NULL)

    @support.cpython_only
    @unittest.skipIf(_testlimitedcapi is None, 'need _testlimitedcapi module')
    def test_isidentifier(self):
        """Test PyUnicode_IsIdentifier()"""
        from _testlimitedcapi import unicode_isidentifier as isidentifier

        self.assertEqual(isidentifier("a"), 1)
        self.assertEqual(isidentifier("b0"), 1)
        self.assertEqual(isidentifier("µ"), 1)
        self.assertEqual(isidentifier("𝔘𝔫𝔦𝔠𝔬𝔡𝔢"), 1)

        self.assertEqual(isidentifier(""), 0)
        self.assertEqual(isidentifier(" "), 0)
        self.assertEqual(isidentifier("["), 0)
        self.assertEqual(isidentifier("©"), 0)
        self.assertEqual(isidentifier("0"), 0)
        self.assertEqual(isidentifier("32M"), 0)

        # CRASHES isidentifier(b"a")
        # CRASHES isidentifier([])
        # CRASHES isidentifier(NULL)

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_copycharacters(self):
        """Test PyUnicode_CopyCharacters()"""
        from _testcapi import unicode_copycharacters

        strings = [
            # all strings have exactly 5 characters
            'abcde', '\xa1\xa2\xa3\xa4\xa5',
            '\u4f60\u597d\u4e16\u754c\uff01',
            '\U0001f600\U0001f601\U0001f602\U0001f603\U0001f604'
        ]

        for idx, from_ in enumerate(strings):
            # wide -> narrow: exceed maxchar limitation
            for to in strings[:idx]:
                self.assertRaises(
                    SystemError,
                    unicode_copycharacters, to, 0, from_, 0, 5
                )
            # same kind
            for from_start in range(5):
                self.assertEqual(
                    unicode_copycharacters(from_, 0, from_, from_start, 5),
                    (from_[from_start:from_start+5].ljust(5, '\0'),
                     5-from_start)
                )
            for to_start in range(5):
                self.assertEqual(
                    unicode_copycharacters(from_, to_start, from_, to_start, 5),
                    (from_[to_start:to_start+5].rjust(5, '\0'),
                     5-to_start)
                )
            # narrow -> wide
            # Tests omitted since this creates invalid strings.

        s = strings[0]
        self.assertRaises(IndexError, unicode_copycharacters, s, 6, s, 0, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, PY_SSIZE_T_MAX, s, 0, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, -1, s, 0, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, PY_SSIZE_T_MIN, s, 0, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, 0, s, 6, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, 0, s, PY_SSIZE_T_MAX, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, 0, s, -1, 5)
        self.assertRaises(IndexError, unicode_copycharacters, s, 0, s, PY_SSIZE_T_MIN, 5)
        self.assertRaises(SystemError, unicode_copycharacters, s, 1, s, 0, 5)
        self.assertRaises(SystemError, unicode_copycharacters, s, 1, s, 0, PY_SSIZE_T_MAX)
        self.assertRaises(SystemError, unicode_copycharacters, s, 0, s, 0, -1)
        self.assertRaises(SystemError, unicode_copycharacters, s, 0, s, 0, PY_SSIZE_T_MIN)
        self.assertRaises(SystemError, unicode_copycharacters, s, 0, b'', 0, 0)
        self.assertRaises(SystemError, unicode_copycharacters, s, 0, [], 0, 0)
        # CRASHES unicode_copycharacters(s, 0, NULL, 0, 0)
        # TODO: Test PyUnicode_CopyCharacters() with non-unicode and
        # non-modifiable unicode as "to".

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_pep393_utf8_caching_bug(self):
        # Issue #25709: Problem with string concatenation and utf-8 cache
        from _testcapi import getargs_s_hash
        for k in 0x24, 0xa4, 0x20ac, 0x1f40d:
            s = ''
            for i in range(5):
                # Due to CPython specific optimization the 's' string can be
                # resized in-place.
                s += chr(k)
                # Parsing with the "s#" format code calls indirectly
                # PyUnicode_AsUTF8AndSize() which creates the UTF-8
                # encoded string cached in the Unicode object.
                self.assertEqual(getargs_s_hash(s), chr(k).encode() * (i + 1))
                # Check that the second call returns the same result
                self.assertEqual(getargs_s_hash(s), chr(k).encode() * (i + 1))

    @support.cpython_only
    @unittest.skipIf(_testcapi is None, 'need _testcapi module')
    def test_GET_CACHED_HASH(self):
        from _testcapi import unicode_GET_CACHED_HASH
        content_bytes = b'some new string'
        # avoid parser interning & constant folding
        obj = str(content_bytes, 'ascii')
        # impl detail: fresh strings do not have cached hash
        self.assertEqual(unicode_GET_CACHED_HASH(obj), -1)
        # impl detail: adding string to a dict caches its hash
        {obj: obj}
        # impl detail: ASCII string hashes are equal to bytes ones
        self.assertEqual(unicode_GET_CACHED_HASH(obj), hash(content_bytes))


class PyUnicodeWriterTest(unittest.TestCase):
    def test_utf8_storage(self):
        writer = self.create_writer(0)
        text = '日😀\udcff\0'
        writer.write_str(text)
        self.assertEqual(writer.storage(), (4, 11))
        writer.write_ascii(b'abc', 3)
        writer.write_char(ord('é'))
        writer.write_substring('x日本y', 1, 3)
        expected = text + 'abcé日本'
        self.assertEqual(writer.storage(),
                         (len(expected), len(expected.encode('utf-8', 'surrogatepass'))))
        self.assertEqual(writer.finish(), expected)

    def test_utf8_integer_writes(self):
        for number in (0, -12345, 2**2048, -(10**200)):
            writer = self.create_writer(0)
            writer.write_str('日\udcff:')
            writer.write_str(number)
            writer.write_ascii(b'/', 1)
            writer.write_repr(number)
            self.assertEqual(writer.storage(),
                             (len(f'日\udcff:{number}/{number}'),
                              len(f'日\udcff:{number}/{number}'.encode('utf-8', 'surrogatepass'))))
            self.assertEqual(writer.finish(), f'日\udcff:{number}/{number}')

    def test_utf8_writer_allocation_failures(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import _testcapi
            remove_hooks = _testcapi.remove_mem_hooks
            value = '日😀\udcff' * 20
            for fail_at in range(10):
                writer = _testcapi.PyUnicodeWriter(0)
                writer.write_str('é')
                failed = False
                try:
                    _testcapi.set_nomemory(fail_at, fail_at + 1)
                    writer.write_str(value)
                except MemoryError:
                    failed = True
                finally:
                    remove_hooks()
                writer.write_char(ord('!'))
                assert writer.finish() == 'é' + ('' if failed else value) + '!'
        """))

    def create_writer(self, size):
        return _testcapi.PyUnicodeWriter(size)

    def test_basic(self):
        writer = self.create_writer(100)

        # test PyUnicodeWriter_WriteUTF8()
        writer.write_utf8(b'var', -1)

        # test PyUnicodeWriter_WriteChar()
        writer.write_char(ord('='))

        # test PyUnicodeWriter_WriteSubstring()
        writer.write_substring("[long]", 1, 5)
        # CRASHES writer.write_substring(NULL, 0, 0)

        # test PyUnicodeWriter_WriteStr()
        writer.write_str(" value ")
        # CRASHES writer.write_str(NULL)

        # test PyUnicodeWriter_WriteRepr()
        writer.write_repr("repr")

        self.assertEqual(writer.finish(),
                         "var=long value 'repr'")

    def test_repr_null(self):
        writer = self.create_writer(0)
        writer.write_utf8(b'var=', -1)
        writer.write_repr(NULL)
        self.assertEqual(writer.finish(),
                         "var=<NULL>")

    def test_write_char(self):
        writer = self.create_writer(0)
        writer.write_char(0)
        writer.write_char(ord('$'))
        writer.write_char(0x20ac)
        writer.write_char(0x10_ffff)
        self.assertRaises(ValueError, writer.write_char, 0x11_0000)
        self.assertRaises(ValueError, writer.write_char, 0xFFFF_FFFF)
        self.assertEqual(writer.finish(),
                         "\0$\u20AC\U0010FFFF")

    def test_utf8(self):
        writer = self.create_writer(0)
        writer.write_utf8(b"ascii", -1)
        writer.write_char(ord('-'))
        writer.write_utf8(b"latin1=\xC3\xA9", -1)
        writer.write_char(ord('-'))
        writer.write_utf8(b"euro=\xE2\x82\xAC", -1)
        writer.write_char(ord('.'))
        writer.write_utf8(NULL, 0)
        # CRASHES writer.write_utf8(NULL, 1)
        # CRASHES writer.write_utf8(NULL, -1)
        self.assertEqual(writer.finish(),
                         "ascii-latin1=\xE9-euro=\u20AC.")

    def test_ascii(self):
        writer = self.create_writer(0)
        writer.write_ascii(b"Hello ", -1)
        writer.write_ascii(b"", 0)
        writer.write_ascii(NULL, 0)
        # CRASHES writer.write_ascii(NULL, 1)
        # CRASHES writer.write_ascii(NULL, -1)
        writer.write_ascii(b"Python! <truncated>", 6)
        self.assertEqual(writer.finish(), "Hello Python")

    def test_invalid_utf8(self):
        writer = self.create_writer(0)
        with self.assertRaises(UnicodeDecodeError):
            writer.write_utf8(b"invalid=\xFF", -1)

    def test_recover_utf8_error(self):
        # test recovering from PyUnicodeWriter_WriteUTF8() error
        writer = self.create_writer(0)
        writer.write_utf8(b"value=", -1)

        # write fails with an invalid string
        with self.assertRaises(UnicodeDecodeError):
            writer.write_utf8(b"invalid\xFF", -1)
        with self.assertRaises(UnicodeDecodeError):
            s = "truncated\u20AC".encode()
            writer.write_utf8(s, len(s) - 1)

        # retry write with a valid string
        writer.write_utf8(b"valid", -1)

        self.assertEqual(writer.finish(),
                         "value=valid")

    def test_decode_utf8(self):
        # test PyUnicodeWriter_DecodeUTF8Stateful()
        writer = self.create_writer(0)
        writer.decodeutf8stateful(b"ign\xFFore", -1, b"ignore")
        writer.write_char(ord('-'))
        writer.decodeutf8stateful(b"replace\xFF", -1, b"replace")
        writer.write_char(ord('-'))

        # incomplete trailing UTF-8 sequence
        writer.decodeutf8stateful(b"incomplete\xC3", -1, b"replace")

        writer.decodeutf8stateful(NULL, 0, b"replace")
        # CRASHES writer.decodeutf8stateful(NULL, 1, b"replace")
        # CRASHES writer.decodeutf8stateful(NULL, -1, b"replace")
        with self.assertRaises(UnicodeDecodeError):
            writer.decodeutf8stateful(b"default\xFF", -1, NULL)

        self.assertEqual(writer.finish(),
                         "ignore-replace\uFFFD-incomplete\uFFFD")

    def test_decode_utf8_consumed(self):
        # test PyUnicodeWriter_DecodeUTF8Stateful() with consumed
        writer = self.create_writer(0)

        # valid string
        consumed = writer.decodeutf8stateful(b"text", -1, b"strict", True)
        self.assertEqual(consumed, 4)
        writer.write_char(ord('-'))

        # non-ASCII
        consumed = writer.decodeutf8stateful(b"\xC3\xA9-\xE2\x82\xAC", 6, b"strict", True)
        self.assertEqual(consumed, 6)
        writer.write_char(ord('-'))

        # invalid UTF-8 (consumed is 0 on error)
        with self.assertRaises(UnicodeDecodeError):
            writer.decodeutf8stateful(b"invalid\xFF", -1, b"strict", True)

        # ignore error handler
        consumed = writer.decodeutf8stateful(b"more\xFF", -1, b"ignore", True)
        self.assertEqual(consumed, 5)
        writer.write_char(ord('-'))

        # incomplete trailing UTF-8 sequence
        consumed = writer.decodeutf8stateful(b"incomplete\xC3", -1, b"ignore", True)
        self.assertEqual(consumed, 10)
        writer.write_char(ord('-'))

        consumed = writer.decodeutf8stateful(NULL, 0, b"replace", True)
        self.assertEqual(consumed, 0)
        # CRASHES writer.decodeutf8stateful(NULL, 1, b"replace", True)
        # CRASHES writer.decodeutf8stateful(NULL, -1, b"replace", True)
        consumed = writer.decodeutf8stateful(b"default\xC3", -1, NULL, True)
        self.assertEqual(consumed, 7)

        self.assertEqual(writer.finish(), "text-\xE9-\u20AC-more-incomplete-default")

    def test_widechar(self):
        from _testcapi import SIZEOF_WCHAR_T

        if SIZEOF_WCHAR_T == 2:
            encoding = 'utf-16le' if sys.byteorder == 'little' else 'utf-16be'
        elif SIZEOF_WCHAR_T == 4:
            encoding = 'utf-32le' if sys.byteorder == 'little' else 'utf-32be'

        writer = self.create_writer(0)
        writer.write_widechar("latin1=\xE9".encode(encoding))
        writer.write_char(ord("-"))
        writer.write_widechar("euro=\u20AC".encode(encoding))
        writer.write_char(ord("-"))
        writer.write_widechar("max=\U0010ffff".encode(encoding))
        writer.write_char(ord("-"))
        writer.write_widechar("zeroes=".encode(encoding).ljust(SIZEOF_WCHAR_T * 10, b'\0'),
                              10)
        writer.write_char(ord('.'))

        if SIZEOF_WCHAR_T == 4:
            invalid = (b'\x00\x00\x11\x00' if sys.byteorder == 'little' else
                       b'\x00\x11\x00\x00')
            with self.assertRaises(ValueError):
                writer.write_widechar("invalid=".encode(encoding) + invalid)
        writer.write_widechar(b'', -5)
        writer.write_widechar(NULL, 0)
        # CRASHES writer.write_widechar(NULL, 1)
        # CRASHES writer.write_widechar(NULL, -1)

        self.assertEqual(writer.finish(),
                         "latin1=\xE9-euro=\u20AC-max=\U0010ffff-zeroes=\0\0\0.")

    def test_ucs4(self):
        encoding = 'utf-32le' if sys.byteorder == 'little' else 'utf-32be'

        writer = self.create_writer(0)
        writer.write_ucs4("ascii IGNORED".encode(encoding), 5)
        writer.write_char(ord("-"))
        writer.write_ucs4("latin1=\xe9".encode(encoding))
        writer.write_char(ord("-"))
        writer.write_ucs4("euro=\u20ac".encode(encoding))
        writer.write_char(ord("-"))
        writer.write_ucs4("max=\U0010ffff".encode(encoding))
        writer.write_char(ord("."))
        self.assertEqual(writer.finish(),
                         "ascii-latin1=\xE9-euro=\u20AC-max=\U0010ffff.")

        # Test some special characters
        writer = self.create_writer(0)
        # Lone surrogate character
        writer.write_ucs4("lone\uDC80".encode(encoding, 'surrogatepass'))
        writer.write_char(ord("-"))
        # Surrogate pair
        writer.write_ucs4("pair\uD83D\uDC0D".encode(encoding, 'surrogatepass'))
        writer.write_char(ord("-"))
        writer.write_ucs4("null[\0]".encode(encoding), 7)
        invalid = (b'\x00\x00\x11\x00' if sys.byteorder == 'little' else
                   b'\x00\x11\x00\x00')
        with self.assertRaises(ValueError):
            writer.write_ucs4("invalid".encode(encoding) + invalid)
        writer.write_ucs4(NULL, 0)
        # CRASHES writer.write_ucs4(NULL, 1)
        self.assertEqual(writer.finish(),
                         "lone\udc80-pair\ud83d\udc0d-null[\x00]")

        # invalid size
        writer = self.create_writer(0)
        with self.assertRaises(ValueError):
            writer.write_ucs4("text".encode(encoding), -1)
        self.assertRaises(ValueError, writer.write_ucs4, b'', -1)
        self.assertRaises(ValueError, writer.write_ucs4, NULL, -1)

    def test_substring_empty(self):
        writer = self.create_writer(0)
        writer.write_substring("abc", 1, 1)
        self.assertEqual(writer.finish(), '')

    def test_singletons(self):
        writer = self.create_writer(5)
        self.assertIs(writer.finish(), '')

        for ch in range(256):
            with self.subTest(ch=ch):
                ch = chr(ch)
                writer = self.create_writer(0)
                writer.write_substring(ch + 'xxx', 0, 1)
                self.assertIs(writer.finish(), ch)

    @unittest.skipUnless(support.Py_DEBUG, 'need debug build (Py_DEBUG)')
    def test_detect_overflow(self):
        # Test detection of buffer overflow
        code = textwrap.dedent('''
            from test.support import SuppressCrashReport
            import _testinternalcapi

            SuppressCrashReport().__enter__()
            _testinternalcapi.unicodewriter_overflow()
        ''')
        proc = assert_python_failure('-c', code)
        self.assertIn(b'Buffer overflow detected in PyUnicodeWriter', proc.err)
        # Do not test the position value since it depends on the overallocation
        # strategy which depends on the operating system
        self.assertIn(f'at position '.encode(), proc.err)


@unittest.skipIf(ctypes is None, 'need ctypes')
class PyUnicodeWriterFormatTest(unittest.TestCase):
    def test_readonly_utf8_append(self):
        text = '日\udcff😀'.encode('utf-8', 'surrogatepass').decode('utf-8', 'surrogatepass')
        writer = self.create_writer(0)
        writer.set_overallocate(False)
        writer.write_str(text)
        self.assertIs(writer.finish(), text)
        writer = self.create_writer(0)
        writer.set_overallocate(False)
        writer.write_str(text)
        writer.write_str(123)
        writer.write_str('abc')
        self.assertEqual(writer.storage(), (9, 16))
        self.assertEqual(writer.finish(), text + '123abc')

    def test_utf8_reserve_allocation_failure(self):
        from test.support.script_helper import assert_python_ok
        assert_python_ok('-c', textwrap.dedent(r"""
            import ctypes
            import _testcapi
            prepare_utf8 = ctypes.pythonapi._PyUnicodeWriter_PrepareUTF8
            prepare_utf8.argtypes = (ctypes.c_void_p, ctypes.c_ssize_t)
            prepare_utf8.restype = ctypes.c_int
            remove_hooks = _testcapi.remove_mem_hooks
            for fail_at in range(16):
                writer = _testcapi.PyUnicodeWriter(0)
                writer.set_overallocate(False)
                writer.write_str('日\udcff😀')
                pointer = writer.get_pointer()
                try:
                    _testcapi.set_nomemory(fail_at, fail_at + 1)
                    prepare_utf8(pointer, 100)
                except (MemoryError, ctypes.ArgumentError):
                    # ctypes can wrap allocation failure in argument conversion.
                    pass
                finally:
                    remove_hooks()
                prepare_utf8(pointer, 100)
                assert writer.storage() == (3, 10)
                writer.write_str(123)
                assert writer.finish() == '日\udcff😀123'
        """))

    def test_utf8_numeric_format(self):
        from ctypes import c_int, c_uint
        writer = self.create_writer(0)
        writer.write_str('日\udcff:')
        self.writer_format(writer, b'%08d/%08x/%-6d',
                           c_int(-123), c_uint(42), c_int(7))
        self.assertEqual(writer.storage()[1] - writer.storage()[0], 4)
        self.assertEqual(writer.finish(), '日\udcff:-0000123/0000002a/7     ')

    def test_utf8_format_rollback(self):
        writer = self.create_writer(0)
        writer.write_str('日\udcff')
        with self.assertRaises(ValueError):
            self.writer_format(writer, b'%s\xff', '😀'.encode())
        writer.write_str('é')
        self.assertEqual(writer.finish(), '日\udcffé')

    def create_writer(self, size):
        return _testcapi.PyUnicodeWriter(size)

    def writer_format(self, writer, *args):
        from ctypes import c_char_p, pythonapi, c_int, c_void_p
        _PyUnicodeWriter_Format = getattr(pythonapi, "PyUnicodeWriter_Format")
        _PyUnicodeWriter_Format.argtypes = (c_void_p, c_char_p,)
        _PyUnicodeWriter_Format.restype = c_int

        if _PyUnicodeWriter_Format(writer.get_pointer(), *args) < 0:
            raise ValueError("PyUnicodeWriter_Format failed")

    def test_format(self):
        from ctypes import c_int
        writer = self.create_writer(0)
        self.writer_format(writer, b'%s %i', b'abc', c_int(123))
        writer.write_char(ord('.'))
        self.assertEqual(writer.finish(), 'abc 123.')

    def test_recover_error(self):
        # test recovering from PyUnicodeWriter_Format() error
        writer = self.create_writer(0)
        self.writer_format(writer, b"%s ", b"Hello")

        # PyUnicodeWriter_Format() fails with an invalid format string
        with self.assertRaises(ValueError):
            self.writer_format(writer, b"%s\xff", b"World")

        # Retry PyUnicodeWriter_Format() with a valid format string
        self.writer_format(writer, b"%s.", b"World")

        self.assertEqual(writer.finish(), 'Hello World.')

    def test_unicode_equal(self):
        unicode_equal = _testlimitedcapi.unicode_equal

        def copy(text):
            return text.encode().decode()

        self.assertTrue(unicode_equal("", ""))
        self.assertTrue(unicode_equal("abc", "abc"))
        self.assertTrue(unicode_equal("abc", copy("abc")))
        self.assertTrue(unicode_equal("\u20ac", copy("\u20ac")))
        self.assertTrue(unicode_equal("\U0010ffff", copy("\U0010ffff")))

        self.assertFalse(unicode_equal("abc", "abcd"))
        self.assertFalse(unicode_equal("\u20ac", "\u20ad"))
        self.assertFalse(unicode_equal("\U0010ffff", "\U0010fffe"))

        # str subclass
        self.assertTrue(unicode_equal("abc", Str("abc")))
        self.assertTrue(unicode_equal(Str("abc"), "abc"))
        self.assertFalse(unicode_equal("abc", Str("abcd")))
        self.assertFalse(unicode_equal(Str("abc"), "abcd"))

        # invalid type
        for invalid_type in (b'bytes', 123, ("tuple",)):
            with self.subTest(invalid_type=invalid_type):
                with self.assertRaises(TypeError):
                    unicode_equal("abc", invalid_type)
                with self.assertRaises(TypeError):
                    unicode_equal(invalid_type, "abc")

        # CRASHES unicode_equal("abc", NULL)
        # CRASHES unicode_equal(NULL, "abc")


if __name__ == "__main__":
    unittest.main()
