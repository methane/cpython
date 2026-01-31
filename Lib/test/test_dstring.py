import unittest


_dstring_prefixes = "d db df dt dr drb drf drt".split()
_dstring_prefixes += [p.upper() for p in _dstring_prefixes]


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

def fd(s, globals=None):
    """Helper function to evaluate fd-strings."""
    if '"""' in s:
        return eval(f"fd'''{s}'''", globals=globals)
    else:
        return eval(f'fd"""{s}"""', globals=globals)



class DStringTestCase(unittest.TestCase):
    def assertAllRaise(self, exception_type, regex, error_strings):
        for str in error_strings:
            with self.subTest(str=str):
                with self.assertRaisesRegex(exception_type, regex) as cm:
                    eval(str)

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
            expr = f"{prefix}'''\n'''"
            expr2 = f'{prefix}"""\n"""'
            with self.subTest(expr=expr):
                v = eval(expr)
                v2 = eval(expr2)
                if 't' in prefix.lower():
                    self.assertEqual(v.strings, ("",))
                    self.assertEqual(v2.strings, ("",))
                elif 'b' in prefix.lower():
                    self.assertEqual(v, b"")
                    self.assertEqual(v2, b"")
                else:
                    self.assertEqual(v, "")
                    self.assertEqual(v2, "")

    def check_dbstring(self, s, expected):
        self.assertEqual(d(s), expected)
        self.assertEqual(db(s), expected.encode())

    def test_dbstring(self):
        # Basic dedent - remove common leading whitespace
        source = """
            hello
            world
            """
        self.check_dbstring(source, "hello\nworld\n")

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
        self.check_dbstring(source, " line1\n   line2\nline3\n  ")

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

        # Lines with only whitespace also have their indentation removed.
        source = """
....hello
..
......
....world
....""".replace('.', ' ')
        self.check_dbstring(source, "hello\n\n  \nworld\n")

        # Line continuation with backslash works as usual.
        # But you cannot put a backslash right after the opening quotes.
        source = r"""
            Hello \
            World!\
            """
        self.check_dbstring(source, "Hello World!")

    def test_fdstring(self):
        g = {"world": 42}

        source = r"""
            Hello
              {world}
            """
        self.assertEqual(fd(source, globals=g), "Hello\n  42\n")

        source = r"""
            Hello
          {world}
            """
        self.assertEqual(fd(source, globals=g), "  Hello\n42\n  ")

        source = r"""
            Hello {world} Lorum
            ipsum dolor sit amet,
            """
        self.assertEqual(fd(source, globals=g), "Hello 42 Lorum\nipsum dolor sit amet,\n")

if __name__ == '__main__':
    unittest.main()
