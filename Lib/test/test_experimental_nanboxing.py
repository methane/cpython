import sysconfig
import unittest

from test import test_experimental_tracing_gc as tracing_tests


@unittest.skipUnless(sysconfig.get_config_var("Py_EXPERIMENTAL_NANBOX"),
                     "requires --with-experimental-nanboxing")
class ExperimentalNaNBoxingTests(unittest.TestCase):
    run_python = tracing_tests.ExperimentalTracingGCTests.run_python

    def test_integer_arithmetic_does_not_allocate(self):
        self.run_python("""
            import gc, itertools, sys
            def hot(n):
                value = 10000
                for _ in itertools.repeat(None, n):
                    value += 1
                return value
            hot(20000)
            gc.collect()
            gc.disable()
            before = sys.getallocatedblocks()
            result = hot(100000)
            allocated = sys.getallocatedblocks() - before
            assert result == 110000, result
            assert allocated < 100, allocated
        """)

    def test_specialized_class_attribute(self):
        self.run_python("""
            import _opcode, gc, sys
            from _testinternalcapi import (
                get_jit_backend, make_tracing_gc_boxed_float,
                make_tracing_gc_boxed_int)

            def hot(value, n):
                for _ in range(n):
                    cls = value.__class__
                return cls
            for boxed, immediate in (
                (make_tracing_gc_boxed_float(1.25), 1.25),
                (make_tracing_gc_boxed_int(10000), 10000),
            ):
                # Both representations have the same type version. A slot
                # cache populated by a boxed value must accept immediates.
                assert hot(boxed, 20000) is type(boxed)
                assert hot(immediate, 20000) is type(immediate)
                gc.collect()
                assert hot(boxed, 100) is type(boxed)
                assert hot(immediate, 100) is type(immediate)
            if sys._jit.is_enabled():
                executors = []
                for offset in range(0, len(hot.__code__.co_code), 2):
                    try:
                        executors.append(_opcode.get_executor(hot.__code__, offset))
                    except ValueError:
                        pass
                assert executors
                if get_jit_backend() == 'jit':
                    assert any(ex.get_jit_code() for ex in executors)
            for value in (None, True, False, 0, [], {}, float('nan')):
                assert hot(value, 1000) is type(value)
        """)

    def test_integer_subscripts(self):
        self.run_python("""
            import _opcode, gc, sys
            from _testinternalcapi import get_jit_backend

            def hot(sequence, index, n):
                for _ in range(n):
                    value = sequence[index]
                return value
            for sequence in (list(range(16384)), tuple(range(16384)),
                             'abcd' * 4096, 'ab\u00e9d' * 4096):
                for index in (0, 1, 1024, 1025, 10000, 16383, -1, -10000):
                    expected = type(sequence).__getitem__(sequence, index)
                    assert hot(sequence, index, 12000) == expected
                    gc.collect()
                    assert hot(sequence, index, 10) == expected
                if sys._jit.is_enabled():
                    executors = []
                    for offset in range(0, len(hot.__code__.co_code), 2):
                        try:
                            executors.append(_opcode.get_executor(
                                hot.__code__, offset))
                        except ValueError:
                            pass
                    assert executors
                    if get_jit_backend() == 'jit':
                        assert any(ex.get_jit_code() for ex in executors)
                for index in (16384, -16385, 2**30-1, 2**30, -(2**30)):
                    try:
                        hot(sequence, index, 1)
                    except IndexError:
                        pass
                    else:
                        raise AssertionError(index)
        """)

    def test_integer_boundaries_and_serialization(self):
        self.run_python("""
            import gc, json, pickle, sys
            from _testinternalcapi import get_tracing_gc_refstate
            bits = sys.int_info.bits_per_digit
            limit = (1 << bits) - 1
            texts = ['-1073741825', '-1073741824', '-1073741823',
                     '-10000', '-6', '-5', '0', '1', '1024', '1025',
                     '10000', '1073741823', '1073741824', '1073741825',
                     '123456789012345678901234567890']
            class Sub(int):
                pass
            for text in texts:
                value = int(text)
                assert str(value) == text
                if not -5 <= value <= 1024:
                    assert (get_tracing_gc_refstate(value) is None) == (
                        -limit <= value <= limit), value
                boxed = Sub(text)
                assert type(boxed) is Sub and boxed == value
                assert get_tracing_gc_refstate(boxed) is not None
                assert hash(boxed) == hash(value)
                for other in (-limit-1, -10000, -1, 0, 1, 10000, limit+1):
                    b = Sub(other)
                    for operation in ('__add__', '__sub__', '__mul__',
                                      '__and__', '__or__', '__xor__',
                                      '__lt__', '__eq__'):
                        op = getattr(int, operation)
                        assert op(value, other) == op(boxed, b)
                    if other:
                        assert divmod(value, other) == divmod(boxed, b)
                        assert value / other == boxed / b
                for shift in (0, 1, bits-1, bits, bits+1, 100):
                    assert value << shift == boxed << shift
                    assert value >> shift == boxed >> shift
                assert value.bit_count() == boxed.bit_count()
                assert value.bit_length() == boxed.bit_length()
                for order in ('little', 'big'):
                    raw = value.to_bytes(16, order, signed=True)
                    assert int.from_bytes(raw, order, signed=True) == value
                root = {value: (value, [value, None, True, False])}
                for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                    assert pickle.loads(pickle.dumps(root, protocol)) == root
                assert json.loads(json.dumps(value)) == value
                gc.collect()
                assert root[value][0] == value and str(value) == text
            assert type(True) is bool and type(1) is int
            assert True + 10000 == 10001 and False + 10000 == 10000
            assert {True: 'bool'}[1] == 'bool'
        """)

    def test_integer_free_threaded_roots(self):
        self.run_python("""
            import gc, threading
            from _testinternalcapi import check_critical_sections_objects
            roots = [None] * 4
            errors = []
            gate = threading.Barrier(5)
            def worker(index):
                try:
                    gate.wait()
                    for i in range(10000, 20000):
                        value = i * 7 + index
                        roots[index] = {value: [value, -value, True, None]}
                        assert roots[index][value] == [value, -value, True, None]
                        if i % 1000 == 0:
                            check_critical_sections_objects(value, roots[index])
                            check_critical_sections_objects(-value, value)
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            gate.wait()
            for _ in range(20):
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
            for index, root in enumerate(roots):
                value = 19999 * 7 + index
                assert root[value] == [value, -value, True, None]
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_bit_exact_roundtrips(self):
        self.run_python("""
            import gc, math, struct
            from _testinternalcapi import get_tracing_gc_refstate
            patterns = [0, 1, 2, 3, 0x8000000000000000,
                        0x000fffffffffffff, 0x0010000000000000,
                        0x7fefffffffffffff, 0xffefffffffffffff,
                        0x7ff0000000000000, 0xfff0000000000000,
                        0x7ff0000000000001, 0xfff0000000000001,
                        0x7ff8000000000042, 0xfff8000000000042,
                        0xdddddddddddddddd, 0xcdcdcdcdcdcdcdcd]
            patterns.extend(i * 9773457380014963 % (1 << 64)
                            for i in range(20000))
            def identity(value):
                return value
            for i, bits in enumerate(patterns):
                data = struct.pack('Q', bits)
                value = struct.unpack('d', data)[0]
                assert struct.pack('d', value) == data
                copied = identity({'value': [value]}['value'][0])
                assert struct.pack('d', copied) == data
                assert (get_tracing_gc_refstate(value) is None) == (not math.isnan(value))
                if i % 1000 == 0:
                    gc.collect()
        """)

    def test_float_arithmetic_does_not_allocate(self):
        self.run_python("""
            import gc, sys
            from itertools import repeat
            def hot(n):
                x = float('0.5')
                y = float('1.5')
                for _ in repeat(None, n):
                    a = x + y
                    b = x - y
                    c = x * y
                    d = x / y
                return a, b, c, d
            hot(5000)
            gc.collect()
            gc.disable()
            before = sys.getallocatedblocks()
            result = hot(100000)
            allocated = sys.getallocatedblocks() - before
            assert result == (2.0, -1.0, 0.75, 1.0 / 3.0)
            assert allocated < 100, allocated
        """, env_vars={"PYTHON_JIT": "0"})

    def test_nan_payloads_and_identity(self):
        self.run_python("""
            import gc, math, struct
            from _testinternalcapi import get_tracing_gc_refstate
            for bits in (0x7ff8000000000042, 0xfff8000000000042):
                raw = struct.pack('Q', bits)
                a = struct.unpack('d', raw)[0]
                b = struct.unpack('d', raw)[0]
                assert a is not b and a != b
                assert get_tracing_gc_refstate(a) is not None
                mapping = {a: 'a', b: 'b'}
                gc.collect()
                assert len(mapping) == 2
                assert mapping[a] == 'a' and mapping[b] == 'b'
                assert struct.pack('d', a) == raw
            def hot(n):
                infinity = float('inf')
                for i in range(n):
                    value = (i + 0.25) * infinity
                    value = value - value
                return value
            assert math.isnan(hot(20000))
            assert get_tracing_gc_refstate(hot(100)) is not None
        """)

    def test_containers_and_serialization(self):
        self.run_python("""
            import gc, json, pickle, struct
            values = [i / 7.0 for i in range(-1000, 1000)]
            expected = [struct.pack('d', v) for v in values]
            root = {'items': values, 'tuple': tuple(values),
                    'mapping': dict(enumerate(values)), 'set': set(values)}
            for _ in range(10):
                gc.collect()
                for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                    copied = pickle.loads(pickle.dumps(root, protocol))
                    assert copied == root
                    assert [struct.pack('d', v) for v in copied['items']] == expected
                assert json.loads(json.dumps(values)) == values
        """)

    def test_boxed_float_and_subclass(self):
        self.run_python("""
            import gc, math
            from _testinternalcapi import (
                get_tracing_gc_refstate, make_tracing_gc_boxed_float,
                test_tracing_gc_tryref_alias)
            class Sub(float):
                pass
            for value in (0.0, -0.0, 1.25, -3.125, float('inf')):
                boxed = make_tracing_gc_boxed_float(value)
                subclass = Sub(value)
                subclass.extra = value
                assert get_tracing_gc_refstate(boxed) is not None
                assert get_tracing_gc_refstate(subclass) is not None
                assert boxed.hex() == subclass.hex() == value.hex()
                assert float(subclass).hex() == value.hex()
                assert subclass.extra.hex() == value.hex()
                assert boxed + 0.5 == value + 0.5
                gc.collect()
                assert boxed.hex() == value.hex()
            test_tracing_gc_tryref_alias()
        """)

    def test_free_threaded_roots(self):
        self.run_python("""
            import gc, threading
            roots = [None] * 4
            ready = threading.Barrier(5)
            errors = []
            def worker(index):
                try:
                    ready.wait()
                    for i in range(10000):
                        value = (i + 0.125) / 7.0
                        roots[index] = {'value': value, 'pair': (value, -value)}
                        snapshot = roots[index]
                        assert snapshot['pair'] == (value, -value)
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            ready.wait()
            for _ in range(30):
                gc.collect()
            for thread in threads:
                thread.join()
            assert not errors, errors
            assert all(root['value'] == (9999 + 0.125) / 7.0 for root in roots)
        """, args=("-X", "gil=0", "-X", "tlbc=1"),
            env_vars={"PYTHON_JIT": "0"})

    def test_jit_arithmetic_and_gc(self):
        self.run_python("""
            import _opcode, _testinternalcapi, gc, sys
            def hot(n):
                for i in range(n):
                    value = ((i + 0.25) * 0.5 - 0.125) / 4.0
                    value = -value
                return value
            expected = -9999 / 8.0
            for _ in range(10):
                assert hot(10000) == expected
                gc.collect()
            if sys._jit.is_enabled() and sys._jit.is_available():
                executors = []
                for offset in range(0, len(hot.__code__.co_code), 2):
                    try:
                        executors.append(_opcode.get_executor(hot.__code__, offset))
                    except ValueError:
                        pass
                assert executors
                if _testinternalcapi.get_jit_backend() == 'jit':
                    assert any(executor.get_jit_code() for executor in executors)
        """)

    def test_critical_sections(self):
        self.run_python("""
            from _testinternalcapi import check_critical_sections_objects
            values = [float('1.25'), float('-3.5'), float('nan'), {}, []]
            for a in values:
                for b in values:
                    check_critical_sections_objects(a, b)
        """)

    def test_specialized_float_comparisons(self):
        self.run_python("""
            from _testinternalcapi import make_tracing_gc_boxed_float
            def hot(a, b):
                return a < b, a <= b, a == b, a != b, a > b, a >= b
            low = float('1.25')
            high = float('1.5')
            for a in (low, make_tracing_gc_boxed_float(low)):
                for b in (high, make_tracing_gc_boxed_float(high)):
                    for _ in range(10000):
                        assert hot(a, b) == (True, True, False, True, False, False)
                        assert hot(b, a) == (False, False, False, True, True, True)
        """)

    def test_hot_arithmetic_matches_float_slots(self):
        self.run_python("""
            import gc, math, struct
            from _testinternalcapi import (
                get_tracing_gc_refstate, make_tracing_gc_boxed_float)
            def hot(a, b, n):
                for _ in range(n):
                    added = a + b
                    subtracted = a - b
                    multiplied = a * b
                    divided = a / b
                    negated = -a
                return added, subtracted, multiplied, divided, negated
            hot(float('1.25'), float('0.5'), 20000)
            patterns = [0, 1, 2, 3, 0x8000000000000000,
                        0x000fffffffffffff, 0x0010000000000000,
                        0x3ff0000000000001, 0x7fefffffffffffff,
                        0xffefffffffffffff, 0x7ff0000000000000,
                        0xfff0000000000000, 0x7ff8000000000042,
                        0xfff8000000000042, 0xdddddddddddddddd]
            patterns += [i * 9773457380014963 % (1 << 64)
                         for i in range(1000)]
            values = [struct.unpack('d', struct.pack('Q', bits))[0]
                      for bits in patterns]
            for index, a in enumerate(values):
                b = values[-index - 1]
                if b == 0.0:
                    b = float('0.5')
                if index % 2:
                    a = make_tracing_gc_boxed_float(a)
                if index % 3:
                    b = make_tracing_gc_boxed_float(b)
                original = struct.pack('d', a), struct.pack('d', b)
                # Explicit slots exercise the C float implementation, not
                # the specialized bytecode/JIT stack-reference decoder.
                expected = (float.__add__(a, b), float.__sub__(a, b),
                            float.__mul__(a, b), float.__truediv__(a, b),
                            float.__neg__(a))
                actual = hot(a, b, 64)
                for value, reference in zip(actual, expected):
                    if math.isnan(reference):
                        assert math.isnan(value)
                        assert get_tracing_gc_refstate(value) is not None
                    else:
                        assert struct.pack('d', value) == struct.pack('d', reference)
                assert original == (struct.pack('d', a), struct.pack('d', b))
                if index % 100 == 0:
                    gc.collect()
        """)

    def test_hot_division_zero_and_nan(self):
        self.run_python("""
            import gc, math
            from _testinternalcapi import (
                get_tracing_gc_refstate, make_tracing_gc_boxed_float)
            def hot(a, b, n):
                for _ in range(n):
                    value = (a + 0.0) / b
                return value
            hot(float('1.25'), float('0.5'), 20000)
            for zero in (0.0, -0.0, make_tracing_gc_boxed_float(0.0),
                         make_tracing_gc_boxed_float(-0.0)):
                try:
                    hot(1.25, zero, 10)
                except ZeroDivisionError:
                    pass
                else:
                    raise AssertionError('division by zero did not fail')
            for _ in range(100):
                value = hot(float('inf'), float('inf'), 100)
                assert math.isnan(value)
                assert get_tracing_gc_refstate(value) is not None
                gc.collect()
                assert hot(1.25, 0.5, 100) == 2.5
        """)


if __name__ == "__main__":
    unittest.main()
