import unittest


_dstring_prefixes = "d db df dt dr drb drf drt".split()
_dstring_prefixes += [p.upper() for p in _dstring_prefixes]


def d(s):
    # Helper function to evaluate d-strings.
    if '"""' in s:
        return eval(f"d'''{s}'''")
    else:
        return eval(f'd"""{s}"""')


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

    def test_dedent(self):
        # Basic dedent - remove common leading whitespace
        result = d("""
    hello
    world
    """)
        self.assertEqual(result, "hello\nworld\n")

        # Dedent with varying indentation
        result = d("""
     line1
       line2
    line3
      """)
        self.assertEqual(result, " line1\n   line2\nline3\n  ")

        # Dedent with tabs
        result = d("""
\thello
\tworld
\t""")
        self.assertEqual(result, "hello\nworld\n")

        # Mixed spaces and tabs (using common leading whitespace)
        result = d("""
\t\t    hello
\t\t    world
\t\t  """)
        self.assertEqual(result, "  hello\n  world\n")

        # Empty lines do not affect the calculation of common leading whitespace
        result = d("""
    hello

    world
    """)
        self.assertEqual(result, "hello\n\nworld\n")

        # Lines with only whitespace also have their indentation removed.
        result = d("""
    hello
  \n\
      \n\
    world
    """)
        self.assertEqual(result, "hello\n\n  \nworld\n")


if __name__ == '__main__':
    unittest.main()
