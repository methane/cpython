import itertools
import unittest
import warnings

from test.test_string._support import TStringBaseCase


def _prefix_variants(prefix):
    variants = set()
    for permutation in itertools.permutations(prefix):
        for letters in itertools.product(
            *((c.lower(), c.upper()) for c in permutation)
        ):
            variants.add("".join(letters))
    return sorted(variants)


_dstring_prefixes = []
for _prefix in "d db df dt dr drb drf drt".split():
    _dstring_prefixes.extend(_prefix_variants(_prefix))


# Helper functions to evaluate d-strings.
# Use these helper functions to evaluate d-strings in cases where
# you want to test for SyntaxError or special indentation.

def d(s):
    """Helper function to evaluate d-strings."""
    if '"""' in s:
        return eval(f"d'''{s}'''")
    else:
        return eval(f'd"""{s}"""')

def db(s):
    """Helper function to evaluate db-strings."""
    if '"""' in s:
        return eval(f"db'''{s}'''")
    else:
        return eval(f'db"""{s}"""')

def df(s, globals=None):
    """Helper function to evaluate df-strings."""
    if '"""' in s:
        return eval(f"df'''{s}'''", globals=globals)
    else:
        return eval(f'df"""{s}"""', globals=globals)

def dt(s, globals=None):
    """Helper function to evaluate dt-strings."""
    if '"""' in s:
        return eval(f"dt'''{s}'''", globals=globals)
    else:
        return eval(f'dt"""{s}"""', globals=globals)


class AllRaisesMixin:
    def assertAllRaise(self, exception_type, regex, exprs):
        """Assert that all strings in exprs raise exception_type with regex."""
        for expr in exprs:
            with self.subTest(expr=expr):
                with self.assertRaisesRegex(exception_type, regex):
                    eval(expr)


class DStringTestCase(AllRaisesMixin, unittest.TestCase):

    def test_single_quote(self):
        exprs = [
            f"{p}'hello, world'" for p in _dstring_prefixes
        ] + [
            f'{p}"hello, world"' for p in _dstring_prefixes
        ]
        self.assertAllRaise(SyntaxError, "d-string must be triple-quoted", exprs)

    def test_empty_dstring(self):
        exprs = [
            f"{p}''''''" for p in _dstring_prefixes
        ] + [
            f'{p}""""""' for p in _dstring_prefixes
        ]
        self.assertAllRaise(SyntaxError, "d-string must start with a newline", exprs)

        for prefix in _dstring_prefixes:
            for expr in [f"{prefix}'''\n'''", f'{prefix}"""\n"""']:
                with self.subTest(expr=expr):
                    v = eval(expr)
                    if 't' in prefix.lower():
                        self.assertEqual(v.strings, ("",))
                    elif 'b' in prefix.lower():
                        self.assertEqual(v, b"")
                    else:
                        self.assertEqual(v, "")

    def test_missing_newline_in_plain_and_raw_prefixes(self):
        exprs = [
            'd"""x"""',
            'dr"""x"""',
            'db"""x"""',
            'drb"""x"""',
            'd"""x\n"""',
            'd"""\\\n"""',
        ]
        self.assertAllRaise(SyntaxError, "d-string must start with a newline", exprs)

    def test_backslash_after_opening_quotes(self):
        exprs = [
            f'{p}"""\\\nhello\n"""' for p in _dstring_prefixes
        ]
        self.assertAllRaise(SyntaxError, "d-string must start with a newline", exprs)

    def test_u_prefix_is_rejected(self):
        exprs = [
            f'{p}"""\nhello\n"""' for p in _prefix_variants("du")
        ]
        self.assertAllRaise(SyntaxError, "'u' and 'd' prefixes are incompatible", exprs)

    def check_dbstring(self, s, expected):
        # check both d- and db-strings with expected and expected.encode()
        self.assertEqual(d(s), expected)
        self.assertEqual(df(s), expected)
        self.assertEqual(db(s), expected.encode())

    def test_dbstring(self):
        # Basic dedent - remove common leading whitespace
        source = """
            hello
            world
            """
        self.check_dbstring(source, "hello\nworld\n")

        # Whitespace before the closing quotes is a blank final line, even
        # when it is longer than the common indentation.
        source = """
          foo
          bar
            """
        self.check_dbstring(source, "foo\nbar\n")

        # closing quote on same line as last content line
        source = """
            hello
            world"""
        self.check_dbstring(source, "hello\nworld")

        # Dedent with varying indentation
        source = """
            .line1
            ...line2

            line3
            ..""".replace('.', ' ')
        self.check_dbstring(source, " line1\n   line2\n\nline3\n")

        # Dedent with tabs
        source = """
\thello
\tworld
\t"""
        self.check_dbstring(source, "hello\nworld\n")

        # Mixed spaces and tabs (using common leading whitespace)
        source = """
\t\t    hello
\t\t    world
\t\t  """
        self.check_dbstring(source, "  hello\n  world\n")

        # Empty lines do not affect the calculation of common leading whitespace
        source = """
    hello

    world
    """
        self.check_dbstring(source, "hello\n\nworld\n")

        # Blank lines are normalized to single newlines, even when they
        # are longer than the common indentation.
        source = """
....hello
..
......
....world
....""".replace('.', ' ')
        self.check_dbstring(source, "hello\n\n\nworld\n")

        # A blank line that does not match the common indentation is not
        # an error; it is just normalized to an empty line.
        source = """
....hello
\t
....world
....""".replace('.', ' ')
        self.check_dbstring(source, "hello\n\nworld\n")

        # Blank lines are normalized even when there is no common
        # indentation.
        source = """
hello
..
world
""".replace('.', ' ')
        self.check_dbstring(source, "hello\n\nworld\n")

        # Line continuation with backslash works as usual.
        # But you cannot put a backslash right after the opening quotes.
        source = r"""
            Hello \
            World!\
            """
        self.check_dbstring(source, "Hello World!")

    def test_raw_dstring(self):
        source = r"""
            path\\to\\file
            keep\\n
            """
        self.check_dbstring(source, "path\\to\\file\nkeep\\n\n")

    def test_dbstring_non_ascii_error(self):
        with self.assertRaisesRegex(SyntaxError, "bytes can only contain ASCII literal characters"):
            db('\n  \u00e9\n  ')

    def test_dbstring_non_ascii_error_precedes_invalid_escape_warning(self):
        source = "db'''\n  \u00e9\\z\n  '''"
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            with self.assertRaisesRegex(
                SyntaxError, "bytes can only contain ASCII literal characters"
            ):
                eval(source)

    def test_concat_bytes_and_nonbytes_error(self):
        exprs = [
            'd"""\n    x\n    """ db"""\n    y\n    """',
            'db"""\n    x\n    """ d"""\n    y\n    """',
        ]
        self.assertAllRaise(SyntaxError, "cannot mix bytes and nonbytes literals", exprs)


class DFStringTestCase(AllRaisesMixin, unittest.TestCase):

    def test_missing_newline_in_f_variants(self):
        exprs = [
            'df"""x"""',
            'drf"""x"""',
        ]
        self.assertAllRaise(SyntaxError, "d-string must start with a newline", exprs)

    def test_dfstring(self):
        world = 42

        s = df"""
            Hello
              {world}
            """
        self.assertEqual(s, "Hello\n  42\n")

        # '{' is taken into account when calculating the common indentation
        s = df"""
            Hello
          {world}
            """
        self.assertEqual(s, "  Hello\n42\n")

        # spaces after '}' is not taken into account
        s = df"""
            Hello {world} Lorum
            ipsum dolor sit amet,
            """
        self.assertEqual(s, "Hello 42 Lorum\nipsum dolor sit amet,\n")

        # The expression between '{' and '}' is taken into account
        s = df"""
              Hello {
            world } Lorum
              ipsum"""
        self.assertEqual(s, "  Hello 42 Lorum\n  ipsum")

    def test_dfstring_conversion_and_format(self):
        x = 3.1415
        name = "Alice"

        s = df"""
            {x:.2f} {name!r}
            """
        self.assertEqual(s, "3.14 'Alice'\n")

        s = df"""
            {x=}
            """
        self.assertEqual(s, "x=3.1415\n")

    def test_concat_with_fstring(self):
        s = d"""
            hello
            """ f"world"
        self.assertEqual(s, "hello\nworld")

    def test_closing_quote_on_content_line(self):
        value = "Python"
        s = df"""
            hello {value}
              world"""
        self.assertEqual(s, "hello Python\n  world")

    def test_blank_line_normalization(self):
        # Blank lines are normalized to single newlines, even when their
        # whitespace doesn't match the common indentation.
        self.assertEqual(df('\n    foo\n\t\n    bar {1}\n    '), "foo\n\nbar 1\n")
        self.assertEqual(df('\n  foo\n  {1}\n    '), "foo\n1\n")

    def test_multiline_format_spec(self):
        class Spec:
            def __format__(self, spec):
                return spec
        s = Spec()

        # Lines inside a multi-line format spec are dedented too.
        self.assertEqual(df'''
            {s:>6
            }
            ''', ">6\n\n")

        # Nested replacement fields in the format spec keep working.
        self.assertEqual(df'''
            {s:{"a"}b
            c}
            ''', "ab\nc\n")

    def test_multiline_debug_text(self):
        # The static text of a debug expression spanning multiple lines
        # is dedented too.
        self.assertEqual(df'''
            {1 +
            1=}
            ''', "1 +\n1=2\n")

        self.assertEqual(df'''
              {24 *
              3=}
            ''', "  24 *\n  3=72\n")

    def test_nested_string_lines_affect_indent(self):
        # Physical lines inside nested string literals in replacement
        # fields are not excluded from the common indentation calculation.
        # todo: strip indentation from inner string literal.
        self.assertEqual(df"""
        {0 or '''
    foo'''}
        bar
        """, "    \n    foo\n    bar\n")

    def test_nested_dstring_inside_dfstring(self):
        # A nested d-string literal in a replacement field is dedented
        # independently when the expression is evaluated.
        s = df"""
    outer line
        {d"""
        nested
        line
        """}
    """
        self.assertEqual(s, "outer line\n    nested\nline\n\n")

        # Unlike a regular triple-quoted string, the nested d-string
        # content is dedented rather than preserving indentation from the
        # surrounding source.
        s = df"""
    {d"""
        foo
        bar
        """}
    outer
    """
        self.assertEqual(s, "foo\nbar\n\nouter\n")

        # Nested df-strings also work and interpolate normally.
        s = df"""
    prefix {df"""
    value {42}
    """} suffix
    """
        self.assertEqual(s, "prefix value 42\n suffix\n")

        # Nested raw d-strings keep backslashes.
        s = df"""
    {dr"""
    path\\to\\file
    """}
    """
        self.assertEqual(s, r"path\\to\\file" + "\n\n")

        # Nested d-strings must still start with a newline.
        expr = 'df"""\n    {d"""x"""}\n    """'
        with self.assertRaisesRegex(SyntaxError, "d-string must start with a newline"):
            eval(expr)


class DTStringTestCase(AllRaisesMixin, TStringBaseCase, unittest.TestCase):

    def test_missing_newline_in_t_variants(self):
        exprs = [
            'dt"""x"""',
            'drt"""x"""',
        ]
        self.assertAllRaise(SyntaxError, "d-string must start with a newline", exprs)

    def test_dtstring_basic(self):
        name = "Python"
        t = eval('dt"""\n    Hello, {name}\n    """', {"name": name})
        self.assertTStringEqual(t, ("Hello, ", "\n"), [(name, "name")])

    def test_blank_final_line_normalization(self):
        t = dt('\n  foo\n  {1}\n    ')
        self.assertTStringEqual(t, ("foo\n", "\n"), [(1, "1")])

    def test_closing_quote_on_content_line(self):
        value = "Python"
        t = dt(r"""
            Hello, {value}
              goodbye""", globals={"value": value})
        self.assertTStringEqual(t, ("Hello, ", "\n  goodbye"), [(value, "value")])

    def test_drtstring_raw_content(self):
        t = eval('drt"""\n    keep\\n\n    """')
        self.assertTStringEqual(t, ("keep\\n\n",), ())

    def test_multiline_expression_text(self):
        # The captured expression text of a multi-line interpolation is
        # dedented too.
        t = eval('dt"""\n    {1 +\n    1}\n    """')
        self.assertTStringEqual(t, ("", "\n"), [(2, "1 +\n1")])

    def test_multiline_expression_affects_indent(self):
        # A line starting inside a replacement field also takes part in
        # the common indentation calculation.
        t = eval('dt"""\n    Hello {1 +\n   2}\n    """')
        self.assertTStringEqual(t, (" Hello ", "\n"), [(3, "1 +\n2")])

    def test_multiline_format_spec(self):
        # Lines inside a multi-line format spec are dedented too.
        # t = eval('dt"""\n    {1:>6\n    }\n    """')
        t = dt"""
            {1:>6
            }
            """
        self.assertEqual(t.interpolations[0].format_spec, ">6\n")

    def test_concat_with_tstring_is_rejected(self):
        exprs = [
            'd"""\n    x\n    """ t"hello"',
            't"hello" d"""\n    x\n    """',
            'db"""\n    x\n    """ t"hello"',
            't"hello" db"""\n    x\n    """',
        ]
        self.assertAllRaise(
            SyntaxError,
            "cannot mix t-string literals with string or bytes literals",
            exprs,
        )



if __name__ == '__main__':
    unittest.main()
