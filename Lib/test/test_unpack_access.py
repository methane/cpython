"""Access checks when unpacking references stored in shared containers."""

import dis
import types
import unittest

from test import test_stop_the_world


def unpack_two(seq):
    a, b = seq
    return a, b


def unpack_four(seq):
    a, b, c, d = seq
    return a, b, c, d


def unpack_star(seq):
    a, *middle, b, c = seq
    return a, middle, b, c


class UnpackAccessTests(unittest.TestCase):
    run_native = test_stop_the_world.StopTheWorldTests.run_native

    def test_sequence(self):
        for template, size in ((unpack_two, 2), (unpack_four, 4)):
            for kind in (tuple, list):
                for index in range(size):
                    with self.subTest(size=size, kind=kind, index=index):
                        function = types.FunctionType(template.__code__.replace(), globals())
                        safe = tuple(range(size))
                        for _ in range(100):
                            self.assertEqual(function(kind(safe)), safe)
                        expected = ('UNPACK_SEQUENCE_LIST' if kind is list else
                                    'UNPACK_SEQUENCE_TWO_TUPLE' if size == 2 else
                                    'UNPACK_SEQUENCE_TUPLE')
                        self.assertIn(expected, [i.opname for i in
                                                dis.get_instructions(function, adaptive=True)])
                        foreign = []
                        payload = tuple(foreign if i == index else i
                                        for i in range(size))
                        def work(function, payload, kind):
                            seq = kind(payload)
                            denied = 0
                            for _ in range(100):
                                try:
                                    function(seq)
                                except IllegalThreadAccessException:
                                    denied += 1
                            return denied
                        self.assertEqual(self.run_native(work, function, payload, kind), 100)
                        self.assertEqual(function(kind(safe)), safe)
                        self.assertEqual(foreign, [])

    def test_generic_and_star(self):
        for template, size in ((unpack_two, 2), (unpack_four, 4), (unpack_star, 5)):
            for index in (0, size - 2, size - 1):
                with self.subTest(template=template.__name__, index=index):
                    function = types.FunctionType(template.__code__.replace(), globals())
                    foreign = []
                    payload = tuple(foreign if i == index else i for i in range(size))
                    def work(function, payload):
                        try:
                            function(payload)
                        except IllegalThreadAccessException:
                            return True
                        return False
                    self.assertTrue(self.run_native(work, function, payload))

    def test_starred_container_remains_shallow(self):
        foreign = []
        payload = (0, foreign, 2, 3)
        def work(payload):
            first, middle, before_last, last = unpack_star(payload)
            if (first, before_last, last, len(middle)) != (0, 2, 3, 1):
                return False
            try:
                middle[0]
            except IllegalThreadAccessException:
                return True
            return False
        self.assertTrue(self.run_native(work, payload))
        self.assertEqual(foreign, [])

    def test_arity_and_allowed(self):
        self.assertEqual(unpack_two((1, 2)), (1, 2))
        self.assertEqual(unpack_star(range(5)), (0, [1, 2], 3, 4))
        for seq in ((), (1,), (1, 2, 3)):
            with self.assertRaises(ValueError):
                unpack_two(seq)
        with self.assertRaises(ValueError):
            unpack_star((1, 2))


if __name__ == '__main__':
    unittest.main()
