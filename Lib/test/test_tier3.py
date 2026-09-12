import textwrap
import unittest
import _opcode

from test.support import script_helper


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
class Tier3RangeTests(unittest.TestCase):
    SCRIPT = textwrap.dedent("""
        import _opcode

        def executor(function):
            for offset in range(0, len(function.__code__.co_code), 2):
                try:
                    candidate = _opcode.get_executor(function.__code__, offset)
                except ValueError:
                    continue
                if candidate.get_tier3_stats()["entries"]:
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
        chunk = names.index('_TIER3_RANGE_CHUNK')
        assert names[chunk + 2] == '_JUMP_TO_TOP', names
        before = active.get_tier3_stats()
        assert alias(100, -5) == -5 + sum(range(100))
        after = active.get_tier3_stats()
        assert after["entries"] > before["entries"], (before, after)
        assert after["iterations"] > before["iterations"], (before, after)
        assert alias(100, 2**63 - 10) == 2**63 - 10 + sum(range(100))
        assert alias(-1, True) is True
        assert alias(0, 12345678901234567890) == 12345678901234567890
        assert alias(count=23, initial=17) == 17 + sum(range(23))
        stats = executor(renamed).get_tier3_stats()
        assert stats["entries"] > 0, stats
        assert stats["iterations"] >= stats["entries"], stats
        if int(__import__('os').environ['PYTHON_TIER3_BUDGET']) < 39:
            assert stats["budget_exits"] > 0, stats

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
        assert executor(sum_and_last).get_tier3_stats()["entries"] > 0
    """)

    def test_range_osr_and_materialization(self):
        for budget in (1, 2, 7, 64):
            with self.subTest(budget=budget):
                script_helper.assert_python_ok(
                    "-c",
                    self.SCRIPT,
                    PYTHON_TIER3_JIT="1",
                    PYTHON_TIER3_BUDGET=str(budget),
                    PYTHON_JIT_STRESS="1",
                )

    def test_disabled(self):
        source = textwrap.dedent("""
                import _opcode
                def f(n):
                    s = 0
                    for i in range(n):
                        s += i
                    return s
                for _ in range(2000):
                    f(40)
                for offset in range(0, len(f.__code__.co_code), 2):
                    try:
                        executor = _opcode.get_executor(f.__code__, offset)
                    except ValueError:
                        continue
                    assert all(item[0] != '_TIER3_RANGE_CHUNK' for item in executor)
                    assert executor.get_tier3_stats()['entries'] == 0
            """)
        for setting in (None, "0"):
            with self.subTest(setting=setting):
                env = {"PYTHON_JIT_STRESS": "1", "__cleanenv": True}
                if setting is not None:
                    env["PYTHON_TIER3_JIT"] = setting
                script_helper.assert_python_ok("-c", source, **env)

    def test_unsafe_loops_are_rejected(self):
        script_helper.assert_python_ok(
            "-c",
            textwrap.dedent("""
                import _opcode
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
                                       (extra, (20,)), (effect, (20,)),
                                       (branch, (20, 10))):
                    for _ in range(2000): function(*args)
                    saw_executor = False
                    for offset in range(0, len(function.__code__.co_code), 2):
                        try: executor = _opcode.get_executor(function.__code__, offset)
                        except ValueError: continue
                        saw_executor = True
                        assert all(item[0] != '_TIER3_RANGE_CHUNK'
                                   for item in executor), function.__name__
                    assert saw_executor, function.__name__
                assert seen == list(range(20)) * 2000
            """),
            PYTHON_TIER3_JIT="1",
            PYTHON_JIT_STRESS="1",
        )


if __name__ == "__main__":
    unittest.main()
