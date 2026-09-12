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
                before = active.get_tier3_stats()
                assert sum_from(1000, initial) == initial + sum(range(1000))
                assert sum_from(100_000, initial) == initial + sum(range(100_000))
                after = active.get_tier3_stats()
                assert after['resident_entries'] > before['resident_entries']
                assert after['resident_iterations'] > before['resident_iterations']

                # Each entry revalidates the accumulator rather than reusing
                # the exact-int observation from training.
                class ObservableInt(int):
                    calls = 0
                    def __add__(self, other):
                        type(self).calls += 1
                        return type(self)(int(self) + other)
                    def __radd__(self, other):
                        type(self).calls += 1
                        return type(self)(other + int(self))

                value = ObservableInt(7)
                assert sum_from(3, value) == 10
                assert ObservableInt.calls > 0
                assert sum_from(0, value) is value
                assert sum_from(1, True) == 1
                assert sum_from(2, -(2**80)) == -(2**80) + 1
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

                cases = (
                    (add, '_TIER3_RANGE_CHUNK_RESIDENT'),
                    (squares, '_TIER3_RANGE_CHUNK_RESIDENT_SQUARES'),
                )
                for function, resident in cases:
                    for _ in range(2000):
                        function(40, 0)
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
                for function, args in ((constant, (20,)), (twice, (20,)),
                                       (extra, (20,)), (scaled, (20,)),
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
                    if function is constant: assert expected == 20
                    elif function is twice: assert expected == 1 << 20
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
