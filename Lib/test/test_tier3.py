import textwrap
import unittest
import _opcode

from test import support
from test.support import script_helper
from test.support import os_helper


def executors_available():
    def probe():
        pass

    try:
        _opcode.get_executor(probe.__code__, 0)
    except ValueError:
        return True
    except RuntimeError:
        return False
    return True


@unittest.skipUnless(executors_available(), "requires tier 2")
@support.requires_gil_enabled("Tier-3 range chunks require the GIL")
class Tier3RangeTests(unittest.TestCase):
    EXPERIMENTAL_UOPS = (
        "_TIER3_RANGE_CHUNK",
        "_TIER3_RANGE_CHUNK_NATIVE",
        "_TIER3_RANGE_CHUNK_RESIDENT",
        "_TIER3_RANGE_CHUNK_RESIDENT_SQUARES",
        "_TIER3_RANGE_CHUNK_RESIDENT_AFFINE",
    )
    MODE_COUNTERS = (
        "entries",
        "iterations",
        "budget_exits",
        "overflow_exits",
        "native_entries",
        "native_iterations",
        "native_budget_exits",
        "native_overflow_exits",
        "native_materialization_exits",
        "resident_entries",
        "resident_iterations",
        "resident_polls",
        "resident_pending_polls",
        "resident_overflow_exits",
        "resident_normal_materializations",
        "resident_deopt_materializations",
    )

    SCRIPT = textwrap.dedent("""
        import _opcode
        import os

        MODE = os.environ["PYTHON_TIER3_JIT"]
        DIRECT = MODE in {"2", "direct"}
        RESIDENT = MODE in {"3", "resident"}
        PREFIX = "resident_" if RESIDENT else ("native_" if DIRECT else "")

        def executor(function):
            for offset in range(0, len(function.__code__.co_code), 2):
                try:
                    candidate = _opcode.get_executor(function.__code__, offset)
                except ValueError:
                    continue
                if candidate.get_tier3_stats()[PREFIX + "entries"]:
                    return candidate
            raise AssertionError("the integrated Tier-3 path was not entered")

        def renamed(count, initial=0):
            accumulator = initial
            for current in range(count):
                accumulator += current
            return accumulator

        alias = renamed
        for _ in range(2000):
            alias(40, 10)
        active = executor(renamed)
        names = [item[0] for item in active]
        chunk_name = ('_TIER3_RANGE_CHUNK_RESIDENT' if RESIDENT else
                      ('_TIER3_RANGE_CHUNK_NATIVE' if DIRECT else
                       '_TIER3_RANGE_CHUNK'))
        chunk = names.index(chunk_name)
        assert names[chunk + 1] == '_ITER_NEXT_RANGE', names
        assert names.index('_JUMP_TO_TOP') > chunk, names
        before = active.get_tier3_stats()
        assert alias(100, -5) == -5 + sum(range(100))
        after = active.get_tier3_stats()
        assert after[PREFIX + "entries"] > before[PREFIX + "entries"], (before, after)
        assert after[PREFIX + "iterations"] > before[PREFIX + "iterations"], (before, after)
        before = executor(renamed).get_tier3_stats()
        assert alias(1000, 2**40) == 2**40 + sum(range(1000))
        after = executor(renamed).get_tier3_stats()
        assert after[PREFIX + 'iterations'] > before[PREFIX + 'iterations'], (before, after)

        before = executor(renamed).get_tier3_stats()
        assert alias(100, 2**63 - 10) == 2**63 - 10 + sum(range(100))
        after = executor(renamed).get_tier3_stats()
        assert after[PREFIX + 'iterations'] > before[PREFIX + 'iterations'], (before, after)
        if int(__import__('os').environ['PYTHON_TIER3_BUDGET']) >= 7:
            assert after[PREFIX + 'overflow_exits'] > before[PREFIX + 'overflow_exits'], (before, after)
        assert alias(-1, True) is True
        assert alias(0, 12345678901234567890) == 12345678901234567890
        assert alias(count=23, initial=17) == 17 + sum(range(23))
        for count in (0, 1, 2):
            assert alias(count, 11) == 11 + sum(range(count))
        stats = executor(renamed).get_tier3_stats()
        assert stats[PREFIX + "entries"] > 0, stats
        assert stats[PREFIX + "iterations"] >= stats[PREFIX + "entries"], stats
        if not RESIDENT and int(__import__('os').environ['PYTHON_TIER3_BUDGET']) < 39:
            assert stats[PREFIX + "budget_exits"] > 0, stats

        def sum_and_last(n, initial):
            total = initial
            item = -1
            for item in range(n):
                total += item
            return total, item

        for _ in range(2000):
            assert sum_and_last(40, 3) == (3 + sum(range(40)), 39)
        assert sum_and_last(0, 3) == (3, -1)
        assert sum_and_last(17, 9) == (9 + sum(range(17)), 16)
        active = executor(sum_and_last)
        before = active.get_tier3_stats()
        boundary = sum_and_last(100, 2**63 - 10)
        after = active.get_tier3_stats()
        assert boundary == (2**63 - 10 + sum(range(100)), 99), boundary
        assert after[PREFIX + "iterations"] > before[PREFIX + "iterations"], (before, after)
        if int(__import__('os').environ['PYTHON_TIER3_BUDGET']) >= 7:
            assert after[PREFIX + "overflow_exits"] > before[PREFIX + "overflow_exits"], (before, after)
    """)

    def test_range_osr_and_materialization(self):
        for mode in ("1", "direct", "resident"):
            for budget in (1, 2, 7, 64, 4096):
                with self.subTest(mode=mode, budget=budget):
                    script_helper.assert_python_ok(
                        "-c",
                        self.SCRIPT,
                        PYTHON_TIER3_JIT=mode,
                        PYTHON_TIER3_BUDGET=str(budget),
                        PYTHON_JIT_STRESS="1",
                    )

    def test_resident_sum_squares(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode

                def executor(function):
                    for offset in range(0, len(function.__code__.co_code), 2):
                        try:
                            candidate = _opcode.get_executor(function.__code__, offset)
                        except ValueError:
                            continue
                        if any(op[0] == '_TIER3_RANGE_CHUNK_RESIDENT_SQUARES'
                               for op in candidate):
                            return candidate
                    raise AssertionError('sum-squares region was not installed')

                def squares(n, initial):
                    total = initial
                    item = -1
                    for item in range(n):
                        total += item * item
                    return total, item

                def expected(n, initial):
                    return initial + sum(item * item for item in range(n))

                for _ in range(2000):
                    squares(40, 0)
                active = executor(squares)
                for n in (0, 1, 2, 1000, 100_000):
                    for initial in (0, -7, 2**40):
                        assert squares(n, initial) == (
                            expected(n, initial), n - 1 if n else -1)
                before = active.get_tier3_stats()
                result = squares(100, 2**63 - 10)
                after = active.get_tier3_stats()
                assert result == (expected(100, 2**63 - 10), 99), result
                assert after['resident_iterations'] > before['resident_iterations']
                assert after['resident_overflow_exits'] > before['resident_overflow_exits']

                class MyInt(int): pass
                assert squares(20, MyInt(0)) == (expected(20, 0), 19)
                assert squares(20, False) == (expected(20, 0), 19)
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_JIT_STRESS="1",
        )

    def test_parameterized_integer_reductions(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode

                def executor(function, opname):
                    for offset in range(0, len(function.__code__.co_code), 2):
                        try:
                            candidate = _opcode.get_executor(function.__code__, offset)
                        except ValueError:
                            continue
                        if any(op[0] == opname for op in candidate):
                            return candidate
                    raise AssertionError((function.__name__, opname))

                def add_range(start, stop, step, initial):
                    total = initial
                    item = None
                    for item in range(start, stop, step):
                        total += item
                    return total, item

                def constant(start, stop, step, initial, increment):
                    total = initial
                    item = None
                    for item in range(start, stop, step):
                        total += increment
                    return total, item

                def literal(start, stop, step, initial):
                    total = initial
                    item = None
                    for item in range(start, stop, step):
                        total += -7
                    return total, item

                def affine(start, stop, step, initial, scale, bias):
                    total = initial
                    item = None
                    for item in range(start, stop, step):
                        total += scale * item + bias
                    return total, item

                cases = (
                    (add_range, (0, 1000, 1, 2**40),
                     '_TIER3_RANGE_CHUNK_RESIDENT'),
                    (add_range, (7, 2007, 2, -7),
                     '_TIER3_RANGE_CHUNK_RESIDENT'),
                    (add_range, (1000, -1000, -3, 0),
                     '_TIER3_RANGE_CHUNK_RESIDENT'),
                    (constant, (7, 2007, 2, 2**40, -11),
                     '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE'),
                    (literal, (1000, -1000, -3, -7),
                     '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE'),
                    (affine, (7, 2007, 2, 2**40, -3, 11),
                     '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE'),
                    (affine, (1000, -1000, -3, 0, 0, -5),
                     '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE'),
                )
                for function, args, opname in cases:
                    expected_items = list(range(*args[:3]))
                    if function is add_range:
                        expected = args[3] + sum(expected_items)
                    elif function is constant:
                        expected = args[3] + len(expected_items) * args[4]
                    elif function is literal:
                        expected = args[3] - 7 * len(expected_items)
                    else:
                        expected = args[3] + sum(args[4] * i + args[5]
                                                 for i in expected_items)
                    answer = (expected, expected_items[-1] if expected_items else None)
                    for _ in range(100):
                        assert function(*args) == answer
                    active = executor(function, opname)
                    before = active.get_tier3_stats()
                    assert function(*args) == answer
                    after = active.get_tier3_stats()
                    assert after['resident_entries'] > before['resident_entries'], (args, before, after)
                    assert after['resident_iterations'] > before['resident_iterations'], (args, before, after)

                # Invariant locals are revalidated on every entry.
                assert affine(7, 2007, 2, 5, 4, -9) == (
                    5 + sum(4 * i - 9 for i in range(7, 2007, 2)), 2005)

                import random
                random.seed(8675309)
                optimized = 0
                for _ in range(300):
                    start = random.randrange(-1000, 1000)
                    step = random.choice((-17, -3, -1, 1, 2, 19))
                    count = random.randrange(4, 80)
                    stop = start + step * count
                    initial = random.choice((0, -7, 2**40))
                    scale = random.randrange(-50, 51)
                    bias = random.randrange(-50, 51)
                    before = executor(affine, '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE').get_tier3_stats()
                    got = affine(start, stop, step, initial, scale, bias)
                    after = executor(affine, '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE').get_tier3_stats()
                    items = range(start, stop, step)
                    assert got == (initial + sum(scale * i + bias for i in items),
                                   start + step * (count - 1))
                    optimized += after['resident_iterations'] > before['resident_iterations']
                assert optimized == 300, optimized

                class ObservableInt(int):
                    events = []
                    def __mul__(self, other):
                        self.events.append(('mul', int(self), other))
                        return ObservableInt(int(self) * other)
                    def __add__(self, other):
                        self.events.append(('add', int(self), other))
                        return ObservableInt(int(self) + other)
                scale = ObservableInt(2)
                result, last = affine(1, 5, 1, 0, scale, 3)
                assert (result, last) == (32, 4)
                assert scale.events == [event for i in range(1, 5) for event in
                    (('mul', 2, i), ('add', 2 * i, 3))], scale.events
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_TIER3_BUDGET="4096",
            PYTHON_JIT_STRESS="1",
        )

    def test_resident_sum_same_noncompact_training(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode

                def sum_from(n, initial):
                    total = initial
                    for item in range(n):
                        total += item
                    return total

                initial = 2**40
                for _ in range(2000):
                    assert sum_from(1000, initial) == initial + sum(range(1000))
                active = None
                for offset in range(0, len(sum_from.__code__.co_code), 2):
                    try:
                        candidate = _opcode.get_executor(sum_from.__code__, offset)
                    except ValueError:
                        continue
                    if any(item[0] == '_TIER3_RANGE_CHUNK_RESIDENT'
                           for item in candidate):
                        active = candidate
                        break
                assert active is not None
                for n in (1000, 100_000):
                    before = active.get_tier3_stats()
                    assert sum_from(n, initial) == initial + sum(range(n))
                    after = active.get_tier3_stats()
                    assert after['resident_entries'] > before['resident_entries']
                    assert after['resident_iterations'] > before['resident_iterations']

                # Each entry revalidates the accumulator rather than reusing
                # the exact-int observation from training.
                class ObservableInt(int):
                    calls = []
                    def __add__(self, other):
                        type(self).calls.append(('add', other))
                        return type(self)(int(self) + other)
                    def __radd__(self, other):
                        type(self).calls.append(('radd', other))
                        return type(self)(other + int(self))

                value = ObservableInt(7)
                result = sum_from(3, value)
                assert result == 10 and type(result) is ObservableInt
                assert ObservableInt.calls == [('add', 0), ('add', 1), ('add', 2)]
                assert sum_from(0, value) is value
                assert sum_from(1, True) == 1
                assert sum_from(2, -(2**80)) == -(2**80) + 1
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_JIT_STRESS="1",
        )

    def test_resident_squares_same_noncompact_training(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode

                def squares_from(n, initial):
                    total = initial
                    item = -1
                    for item in range(n):
                        total += item * item
                    return total, item

                def expected(n, initial):
                    return initial + sum(item * item for item in range(n))

                initial = 2**40
                for _ in range(2000):
                    assert squares_from(1000, initial) == (expected(1000, initial), 999)
                active = None
                for offset in range(0, len(squares_from.__code__.co_code), 2):
                    try:
                        candidate = _opcode.get_executor(squares_from.__code__, offset)
                    except ValueError:
                        continue
                    if any(item[0] == '_TIER3_RANGE_CHUNK_RESIDENT_SQUARES'
                           for item in candidate):
                        active = candidate
                        break
                assert active is not None
                for n in (1000, 100_000):
                    before = active.get_tier3_stats()
                    assert squares_from(n, initial) == (expected(n, initial), n - 1)
                    after = active.get_tier3_stats()
                    assert after['resident_entries'] > before['resident_entries']
                    assert after['resident_iterations'] > before['resident_iterations']

                # Addition overflow occurs after a successful square; the
                # ordinary body must execute the reserved iteration once.
                before = active.get_tier3_stats()
                result = squares_from(100, 2**63 - 10)
                after = active.get_tier3_stats()
                assert result == (expected(100, 2**63 - 10), 99)
                assert after['resident_overflow_exits'] > before['resident_overflow_exits']
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_JIT_STRESS="1",
        )

    def test_resident_prepared_exit_targets(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode

                def find(function, name):
                    for offset in range(0, len(function.__code__.co_code), 2):
                        try:
                            executor = _opcode.get_executor(function.__code__, offset)
                        except ValueError:
                            continue
                        if any(instruction[0] == name for instruction in executor):
                            return list(executor)
                    raise AssertionError(name)

                def add(n, initial):
                    total = initial
                    for item in range(n):
                        total += item
                    return total

                def squares(n, initial):
                    total = initial
                    for item in range(n):
                        total += item * item
                    return total

                def affine(n, initial, scale, bias):
                    total = initial
                    for item in range(n):
                        total += scale * item + bias
                    return total

                cases = (
                    (add, '_TIER3_RANGE_CHUNK_RESIDENT'),
                    (squares, '_TIER3_RANGE_CHUNK_RESIDENT_SQUARES'),
                    (affine, '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE'),
                )
                for function, resident in cases:
                    for _ in range(2000):
                        function(40, 0, 2, 3) if function is affine else function(40, 0)
                    instructions = find(function, resident)
                    chunk = next(item for item in instructions if item[0] == resident)
                    pending = [item for item in instructions
                               if item[0] == '_HANDLE_PENDING_AND_DEOPT']
                    errors = [item for item in instructions
                              if item[0] == '_ERROR_POP_N']
                    materialization_error = chunk[3]
                    periodic = pending[0][2]
                    assert periodic != materialization_error, (pending, chunk)
                    assert any(item[3] == materialization_error for item in errors), errors
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_JIT_STRESS="1",
        )

    @unittest.skipUnless(support.Py_DEBUG, "requires debug reconstruction injection")
    def test_resident_reconstruction_allocation_failures(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode
                import dis
                import os

                def add(n, initial):
                    events = ['pre']
                    total = initial
                    item = -7
                    try:
                        for item in range(7, n):
                            total += item
                    except MemoryError as exc:
                        tb = exc.__traceback__
                        events.append(('except', total, item,
                                       tb.tb_lasti, tb.tb_lineno))
                    finally:
                        events.append(('finally', total, item))
                    return total, item, events

                def body_only(n, initial):
                    total = initial
                    caught = None
                    for item in range(7, n):
                        try:
                            total += item
                        except MemoryError as exc:
                            tb = exc.__traceback__
                            caught = (total, item, tb.tb_lasti, tb.tb_lineno)
                            break
                    return total, item, caught

                def squares(n, initial):
                    events = ['pre']
                    total = initial
                    item = -7
                    try:
                        for item in range(7, n):
                            total += item * item
                    except MemoryError as exc:
                        tb = exc.__traceback__
                        events.append(('except', total, item,
                                       tb.tb_lasti, tb.tb_lineno))
                    finally:
                        events.append(('finally', total, item))
                    return total, item, events

                def affine(n, initial, scale=3, bias=-11):
                    events = ['pre']
                    total = initial
                    item = -7
                    try:
                        for item in range(7, n):
                            total += scale * item + bias
                    except MemoryError as exc:
                        tb = exc.__traceback__
                        events.append(('except', total, item,
                                       tb.tb_lasti, tb.tb_lineno))
                    finally:
                        events.append(('finally', total, item))
                    return total, item, events

                def expected(kind, item, initial):
                    terms = range(7, item + 1)
                    if kind == 'squares':
                        return initial + sum(i * i for i in terms)
                    if kind == 'affine':
                        return initial + sum(3 * i - 11 for i in terms)
                    return initial + sum(terms)

                def executor(function, opname):
                    for offset in range(0, len(function.__code__.co_code), 2):
                        try:
                            candidate = _opcode.get_executor(function.__code__, offset)
                        except ValueError:
                            continue
                        if any(instruction[0] == opname for instruction in candidate):
                            return candidate
                    raise AssertionError(opname)

                cases = (
                    ('add', add, '_TIER3_RANGE_CHUNK_RESIDENT'),
                    ('squares', squares, '_TIER3_RANGE_CHUNK_RESIDENT_SQUARES'),
                    ('affine', affine, '_TIER3_RANGE_CHUNK_RESIDENT_AFFINE'),
                )
                initial = 2**40
                for kind, function, opname in cases:
                    addition = next(
                        instruction for instruction in dis.get_instructions(function)
                        if instruction.opname == 'BINARY_OP' and
                           instruction.argrepr == '+='
                    )
                    for _ in range(2000):
                        function(40, initial)
                    active = executor(function, opname)
                    for site in ('1', '2'):
                        before = active.get_tier3_stats()
                        try:
                            os.environ['PYTHON_TIER3_FAIL_RECONSTRUCTION'] = site
                            total, item, events = function(1000, initial)
                        finally:
                            os.environ.pop('PYTHON_TIER3_FAIL_RECONSTRUCTION', None)
                        # The first interpreted iteration committed item 7.
                        # Failed reconstruction leaves that nonzero entry
                        # snapshot visible to the handler in the optimized
                        # frame, and attributes the error to its addition.
                        entry_term = (49 if kind == 'squares' else
                                      10 if kind == 'affine' else 7)
                        entry_total = initial + entry_term
                        assert (total, item) == (entry_total, 7), (total, item)
                        assert events[0] == 'pre'
                        caught = events[1]
                        assert caught[:3] == ('except', entry_total, 7), caught
                        assert caught[3:] == (
                            addition.offset, addition.positions.lineno), caught
                        assert events[2] == ('finally', entry_total, 7), events
                        after = active.get_tier3_stats()
                        assert after['resident_polls'] > before['resident_polls'], (before, after)
                        assert function(1000, initial)[0] == expected(kind, 999, initial)

                # A handler covering only the arithmetic has a different
                # exception boundary from the entire-loop cases above.
                for _ in range(2000):
                    body_only(40, initial)
                active = executor(body_only, '_TIER3_RANGE_CHUNK_RESIDENT')
                addition = next(
                    instruction for instruction in dis.get_instructions(body_only)
                    if instruction.opname == 'BINARY_OP' and
                       instruction.argrepr == '+='
                )
                before = active.get_tier3_stats()
                try:
                    os.environ['PYTHON_TIER3_FAIL_RECONSTRUCTION'] = '1'
                    total, item, caught = body_only(1000, initial)
                finally:
                    os.environ.pop('PYTHON_TIER3_FAIL_RECONSTRUCTION', None)
                assert (total, item) == (initial + 7, 7)
                assert caught == (initial + 7, 7, addition.offset,
                                   addition.positions.lineno), caught
                after = active.get_tier3_stats()
                assert after['resident_polls'] > before['resident_polls']
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_TIER3_BUDGET="100000",
            PYTHON_JIT_STRESS="1",
        )

    @unittest.skipUnless(
        hasattr(__import__("signal"), "setitimer"), "needs setitimer"
    )
    def test_resident_pending_exit_reloads_mutated_local(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode
                import signal

                delta = 10**12
                observations = []

                def handler(signum, frame):
                    if frame.f_code is total.__code__ and not observations:
                        before = (frame.f_locals['result'],
                                  frame.f_locals['item'])
                        frame.f_locals['result'] = before[0] + delta
                        observations.append(before)

                def total(n):
                    result = 2**40
                    for item in range(n):
                        result += item
                    return result

                for _ in range(2000):
                    total(1000)
                active = None
                for offset in range(0, len(total.__code__.co_code), 2):
                    try:
                        candidate = _opcode.get_executor(total.__code__, offset)
                    except ValueError:
                        continue
                    if candidate.get_tier3_stats()['resident_entries']:
                        active = candidate
                        break
                assert active is not None
                signal.signal(signal.SIGALRM, handler)
                n = 10_000_000
                before = active.get_tier3_stats()
                for _ in range(5):
                    observations.clear()
                    signal.setitimer(signal.ITIMER_REAL, 0.001)
                    result = total(n)
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    after = active.get_tier3_stats()
                    if (observations and
                            after['resident_pending_polls'] >
                            before['resident_pending_polls'] and
                            after['resident_deopt_materializations'] >
                            before['resident_deopt_materializations']):
                        break
                else:
                    raise AssertionError((before, after, observations))
                assert result == 2**40 + sum(range(n)) + delta
                observed_total, item = observations[0]
                assert observed_total == 2**40 + sum(range(item + 1))
                assert item < n - 1
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_TIER3_BUDGET="4096",
            PYTHON_JIT_STRESS="1",
        )

    def test_real_trace_region_dump(self):
        _, _, stderr = script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                def add(n, initial):
                    total = initial
                    for item in range(n):
                        total += item
                    return total

                def squares(n, initial):
                    total = initial
                    for item in range(n):
                        total += item * item
                    return total

                for function in (add, squares):
                    for _ in range(2000):
                        function(40, 0)
                    function(100, 0)
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_TIER3_DUMP="1",
            PYTHON_JIT_STRESS="1",
        )
        dump = stderr.decode()
        self.assertIn("result=add(acc,induction)", dump)
        self.assertIn("lowering=_TIER3_RANGE_CHUNK_RESIDENT ", dump)
        self.assertIn("result=add(acc,mul(induction,induction))", dump)
        self.assertIn("lowering=_TIER3_RANGE_CHUNK_RESIDENT_SQUARES ", dump)
        self.assertIn("node=0 op=live-in type=object compact=none inputs=(-1,-1)", dump)
        self.assertIn(
            "node=3 op=checked-add type=i64 compact=checked-operation inputs=(2,1)",
            dump,
        )
        self.assertIn(
            "node=3 op=checked-mul type=i64 compact=checked-operation inputs=(1,1)",
            dump,
        )
        self.assertIn(
            "node=4 op=checked-add type=i64 compact=checked-operation inputs=(2,3)",
            dump,
        )

    def test_sum_squares_mode_compatibility(self):
        source = textwrap.dedent(f"""
            import _opcode
            import os
            EXPERIMENTAL_UOPS = {self.EXPERIMENTAL_UOPS!r}
            assert os.environ.get('PYTHON_TIER3_JIT') == MODE, os.environ.get('PYTHON_TIER3_JIT')

            def executors(function):
                for offset in range(0, len(function.__code__.co_code), 2):
                    try:
                        yield _opcode.get_executor(function.__code__, offset)
                    except ValueError:
                        pass

            def squares(n, initial):
                total = initial
                for item in range(n):
                    total += item * item
                return total

            def squares_and_last(n, initial):
                total = initial
                item = -1
                for item in range(n):
                    total += item * item
                return total, item

            for function in (squares, squares_and_last):
                for _ in range(2000):
                    function(40, 0)
                expected = 328350 if function is squares else (328350, 99)
                assert function(100, 0) == expected
                active = list(executors(function))
                assert active
                names = {{op[0] for executor in active for op in executor}}
                if MODE in ('resident', '3'):
                    assert '_TIER3_RANGE_CHUNK_RESIDENT_SQUARES' in names, names
                    assert any(executor.get_tier3_stats()['resident_entries']
                               for executor in active)
                else:
                    assert not names.intersection(EXPERIMENTAL_UOPS), names
        """)
        for mode in (None, "0", "helper", "1", "direct", "2", "resident", "3"):
            with self.subTest(mode=mode):
                env = {"PYTHON_JIT_STRESS": "1"}
                if mode is not None:
                    env["PYTHON_TIER3_JIT"] = mode
                with os_helper.EnvironmentVarGuard() as environ:
                    if mode is None:
                        environ.unset("PYTHON_TIER3_JIT")
                    script_helper.assert_python_ok(
                        "-c", f"MODE = {mode!r}\n" + source, **env
                    )

    def test_disabled(self):
        source = textwrap.dedent(f"""
                import _opcode
                EXPERIMENTAL_UOPS = {self.EXPERIMENTAL_UOPS!r}
                MODE_COUNTERS = {self.MODE_COUNTERS!r}

                def assert_inactive(instructions, stats):
                    assert not set(EXPERIMENTAL_UOPS) & set(instructions), instructions
                    assert all(stats[name] == 0 for name in MODE_COUNTERS), stats

                # Guard the assertions themselves against omissions when another
                # experimental mode is added.
                for name in EXPERIMENTAL_UOPS:
                    try:
                        assert_inactive((name,), {{key: 0 for key in MODE_COUNTERS}})
                    except AssertionError:
                        pass
                    else:
                        raise AssertionError(name)
                for name in MODE_COUNTERS:
                    stats = {{key: 0 for key in MODE_COUNTERS}}
                    stats[name] = 1
                    try:
                        assert_inactive((), stats)
                    except AssertionError:
                        pass
                    else:
                        raise AssertionError(name)

                def f(n):
                    s = 0
                    for i in range(n):
                        s += i
                    return s
                for _ in range(2000):
                    f(40)
                saw_executor = False
                for offset in range(0, len(f.__code__.co_code), 2):
                    try:
                        executor = _opcode.get_executor(f.__code__, offset)
                    except ValueError:
                        continue
                    saw_executor = True
                    assert_inactive(
                        tuple(item[0] for item in executor),
                        executor.get_tier3_stats(),
                    )
                assert saw_executor
                assert f(100) == sum(range(100))
            """)
        for setting in (None, "0"):
            with self.subTest(setting=setting):
                env = {"PYTHON_JIT_STRESS": "1", "__cleanenv": True}
                if setting is not None:
                    env["PYTHON_TIER3_JIT"] = setting
                script_helper.assert_python_ok("-c", source, **env)

    def test_unsafe_loops_are_rejected(self):
        source = textwrap.dedent(f"""
                import _opcode
                EXPERIMENTAL_UOPS = {self.EXPERIMENTAL_UOPS!r}
                MODE_COUNTERS = {self.MODE_COUNTERS!r}

                def assert_rejected(instructions, stats):
                    assert not set(EXPERIMENTAL_UOPS) & set(instructions), instructions
                    assert all(stats[name] == 0 for name in MODE_COUNTERS), stats

                for name in EXPERIMENTAL_UOPS:
                    try:
                        assert_rejected((name,), {{key: 0 for key in MODE_COUNTERS}})
                    except AssertionError:
                        pass
                    else:
                        raise AssertionError(name)

                seen = []
                def constant(n):
                    s = 0
                    for i in range(n): s += 1
                    return s
                def twice(n):
                    s = 1
                    for i in range(n): s += s
                    return s
                def accumulator_as_increment(n):
                    s = 1
                    for i in range(n): s += s
                    return s
                def accumulator_as_scale(n, bias):
                    s = 1
                    for i in range(n): s += s * i + bias
                    return s
                def accumulator_as_bias(n, scale):
                    s = 1
                    for i in range(n): s += scale * i + s
                    return s
                def over_capacity(n, a, b, c):
                    s = 0
                    for i in range(n): s += a * i + (b * i + c)
                    return s
                def extra(n):
                    s = 0
                    for i in range(n):
                        s += i
                        s += 1
                    return s
                def scaled(n):
                    s = 0
                    for i in range(n): s += i * 2
                    return s
                def effect(n):
                    s = 0
                    for i in range(n):
                        seen.append(i)
                        s += i
                    return s
                def branch(n, stop):
                    s = 0
                    for i in range(n):
                        if i == stop: break
                        s += i
                    return s
                for function, args in ((twice, (20,)),
                                       (accumulator_as_increment, (20,)),
                                       (accumulator_as_scale, (20, 3)),
                                       (accumulator_as_bias, (20, 3)),
                                       (over_capacity, (20, 2, 3, 4)),
                                       (extra, (20,)),
                                       (effect, (20,)),
                                       (branch, (20, 10))):
                    for _ in range(2000): function(*args)
                    saw_executor = False
                    for offset in range(0, len(function.__code__.co_code), 2):
                        try: executor = _opcode.get_executor(function.__code__, offset)
                        except ValueError: continue
                        saw_executor = True
                        assert_rejected(
                            tuple(item[0] for item in executor),
                            executor.get_tier3_stats(),
                        )
                    assert saw_executor, function.__name__
                    expected = function(*args)
                    if function in (twice, accumulator_as_increment):
                        assert expected == 1 << 20
                    elif function is accumulator_as_scale:
                        reference = 1
                        for i in range(20): reference += reference * i + 3
                        assert expected == reference
                    elif function is accumulator_as_bias:
                        reference = 1
                        for i in range(20): reference += 3 * i + reference
                        assert expected == reference
                    elif function is over_capacity:
                        assert expected == sum(2 * i + (3 * i + 4) for i in range(20))
                    elif function is extra: assert expected == sum(range(20)) + 20
                    elif function is scaled: assert expected == 2 * sum(range(20))
                    elif function is effect: assert expected == sum(range(20))
                    else: assert expected == sum(range(10))
                assert seen == list(range(20)) * 2001
            """)
        for mode in ("helper", "direct", "resident"):
            with self.subTest(mode=mode):
                script_helper.assert_python_ok(
                    "-c",
                    source,
                    PYTHON_TIER3_JIT=mode,
                    PYTHON_JIT_STRESS="1",
                )

    @unittest.skipUnless(
        hasattr(__import__("signal"), "setitimer"), "needs setitimer"
    )
    def test_periodic_signal_check(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode
                import signal
                observations = []
                def handler(signum, frame):
                    if frame.f_code is total.__code__:
                        observations.append((frame.f_locals.get('result'),
                                             frame.f_locals.get('item')))
                def total(n):
                    result = 0
                    for item in range(n):
                        result += item
                    return result
                for _ in range(2000):
                    total(1000)
                active = None
                for offset in range(0, len(total.__code__.co_code), 2):
                    try:
                        candidate = _opcode.get_executor(total.__code__, offset)
                    except ValueError:
                        continue
                    if candidate.get_tier3_stats()['resident_entries']:
                        active = candidate
                        break
                assert active is not None
                signal.signal(signal.SIGALRM, handler)
                n = 10_000_000
                before = active.get_tier3_stats()
                for _ in range(5):
                    signal.setitimer(signal.ITIMER_REAL, 0.001)
                    assert total(n) == sum(range(n))
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    after = active.get_tier3_stats()
                    if (after['resident_pending_polls'] >
                            before['resident_pending_polls'] and
                            after['resident_deopt_materializations'] >
                            before['resident_deopt_materializations']):
                        break
                else:
                    raise AssertionError((before, after, observations))
                assert after['resident_iterations'] > before['resident_iterations']
                assert observations, "signal was not serviced in the target frame"
                result, item = observations[-1]
                assert result is not None and item is not None, observations
                assert result == sum(range(item + 1)), observations
                assert item < n - 1, observations
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_TIER3_BUDGET="4096",
            PYTHON_JIT_STRESS="1",
        )

    def test_monitoring_invalidates_resident_executor(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode
                import sys

                def total(n):
                    result = 0
                    for item in range(n):
                        result += item
                    return result

                for _ in range(2000):
                    total(100)
                active = None
                for offset in range(0, len(total.__code__.co_code), 2):
                    try:
                        candidate = _opcode.get_executor(total.__code__, offset)
                    except ValueError:
                        continue
                    if candidate.get_tier3_stats()["resident_entries"]:
                        active = candidate
                        break
                assert active is not None
                before = active.get_tier3_stats()
                lines = []
                def trace(frame, event, arg):
                    if frame.f_code is total.__code__ and event == "line":
                        lines.append(frame.f_lineno)
                    return trace
                sys.settrace(trace)
                try:
                    assert total(100) == sum(range(100))
                finally:
                    sys.settrace(None)
                after = active.get_tier3_stats()
                assert lines, "instrumented execution did not produce line events"
                assert after["resident_iterations"] == before["resident_iterations"], (
                    before, after)
            """),
            PYTHON_TIER3_JIT="resident",
            PYTHON_JIT_STRESS="1",
        )


if __name__ == "__main__":
    unittest.main()
