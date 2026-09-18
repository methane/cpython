"""Checks for measurement validity and bounded failures, without benchmark runs."""

import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import pyperformance_compare as compare


class ComparisonTests(unittest.TestCase):
    def tearDown(self):
        compare.select_profile("ft")

    def test_gil_pgo_lto_requires_all_requested_settings(self):
        compare.select_profile("gil-pgo-lto")
        identity = {"jit": True, "gil": True, "config": {
            "Py_GIL_DISABLED": 0, "Py_DEBUG": 0,
            "CONFIG_ARGS": "--enable-optimizations --with-lto=full",
            "CFLAGS": "-O3 -fno-omit-frame-pointer -flto -fprofile-use"}}
        compare.validate_build(identity)
        for flag in ("-flto", "-fprofile-use"):
            bad = copy.deepcopy(identity)
            bad["config"]["CFLAGS"] = bad["config"]["CFLAGS"].replace(flag, "")
            with self.subTest(flag=flag), self.assertRaises(AssertionError):
                compare.validate_build(bad)
        for field, value in (("jit", False), ("gil", False)):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                compare.validate_build(dict(identity, **{field: value}))
        env = compare.environment(Path("/tmp/compare"))
        self.assertEqual(env["PYTHON_GIL"], "1")
        self.assertEqual(env["PYPERF_EXPECT_FT"], "0")

    def test_command_results_accept_startup_and_reject_wrong_binary(self):
        compare.select_profile("gil-pgo-lto")
        python = Path("/tmp/venv with space/bin/python")
        metadata = {"ft_build": 0, "gil_enabled": 1, "jit_enabled": 1,
                    "command": f"'{python}' -S -c pass --hook ft_jit"}
        run = types.SimpleNamespace(values=[1, 3], get_metadata=lambda: metadata)
        bench = types.SimpleNamespace(get_runs=lambda: [run], get_name=lambda: "startup")
        pyperf = types.SimpleNamespace(BenchmarkSuite=types.SimpleNamespace(load=lambda _: [bench]))
        with patch.dict(sys.modules, pyperf=pyperf):
            self.assertEqual(compare.load_means("unused", python), {"startup": 2})
            metadata["command"] = "/tmp/wrong/bin/python -S -c pass"
            with self.assertRaises(AssertionError):
                compare.load_means("unused", python)
            metadata["command"] = f"'{python}' -c pass"
            metadata["gil_enabled"] = 0
            with self.assertRaises(AssertionError):
                compare.load_means("unused", python)

    def test_build_rejects_wrong_runtime_or_optimization(self):
        identity = {"jit": True, "gil": False, "config": {
            "Py_GIL_DISABLED": 1, "Py_DEBUG": 0,
            "CONFIG_ARGS": "--disable-optimizations --without-lto",
            "CFLAGS": "-O3 -fno-omit-frame-pointer"}}
        compare.validate_build(identity)
        implicit_defaults = copy.deepcopy(identity)
        implicit_defaults["config"]["CONFIG_ARGS"] = "--disable-gil --enable-experimental-jit=yes"
        compare.validate_build(implicit_defaults)
        for field, value in (("Py_GIL_DISABLED", 0), ("Py_DEBUG", 1),
                             ("CFLAGS", "-O3 -fno-omit-frame-pointer -flto"),
                             ("CFLAGS", "-O3 -fno-omit-frame-pointer -fprofile-use")):
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(identity)
                bad["config"][field] = value
                with self.assertRaises(AssertionError):
                    compare.validate_build(bad)
        for field, value in (("jit", False), ("gil", True)):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                compare.validate_build(dict(identity, **{field: value}))

    def test_environment_does_not_inherit_experimental_settings(self):
        with patch.dict(os.environ, {"PYTHON_TIER3_JIT": "stale", "PYTHONPATH": "/bad",
                                     "PYTHON_GIL": "1", "CFLAGS": "-flto"}):
            env = compare.environment(Path("/tmp/compare"))
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHON_TIER3_JIT", env)
        self.assertEqual(env["PYTHON_GIL"], "0")
        self.assertNotIn("-flto", env["CFLAGS"])

    def test_hash_ignores_pyc_but_detects_source_and_native_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "module.py").write_text("x = 1\n")
            initial = compare.tree_hash(root)
            (root / "__pycache__").mkdir()
            (root / "__pycache__/module.pyc").write_bytes(b"cache")
            self.assertEqual(initial, compare.tree_hash(root))
            (root / "module.so").write_bytes(b"native")
            self.assertNotEqual(initial, compare.tree_hash(root))

    def test_timeout_kills_grandchild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile = root / "child.pid"
            code = ("import pathlib, subprocess, sys, time; "
                    "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                    f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)")
            result = compare.command([sys.executable, "-c", code], root / "timeout.log",
                                     os.environ.copy(), timeout=1)
            self.assertEqual(result["returncode"], 124)
            stat = Path(f"/proc/{pidfile.read_text()}/stat")
            # SIGKILL delivery to a grandchild need not precede the parent's reap.
            for attempt in range(100):
                if not stat.exists() or stat.read_text().split(") ")[1].split()[0] in ("Z", "X"):
                    break
                time.sleep(0.01)
            else:
                self.fail("grandchild survived process-group timeout")

    def test_result_checks_each_worker_and_weights_processes_equally(self):
        python = Path("/tmp/venv/bin/python")
        metadata = {"ft_build": 1, "gil_enabled": 0, "jit_enabled": 1,
                    "python_executable": str(python)}
        def run(values, meta=None):
            return types.SimpleNamespace(values=values, get_metadata=lambda: meta or metadata)
        runs = [run([]), run([1, 3]), run([10])]
        bench = types.SimpleNamespace(get_runs=lambda: runs, get_name=lambda: "result")
        pyperf = types.SimpleNamespace(BenchmarkSuite=types.SimpleNamespace(load=lambda _: [bench]))
        with patch.dict(sys.modules, pyperf=pyperf):
            self.assertEqual(compare.load_means("unused", python), {"result": 6})
            runs.append(run([2], dict(metadata, gil_enabled=1)))
            with self.assertRaises(AssertionError):
                compare.load_means("unused", python)
            runs[:] = [run([2], dict(metadata, python_executable="/tmp/wrong-venv/bin/python"))]
            with self.assertRaises(AssertionError):
                compare.load_means("unused", python)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "real/bin").mkdir(parents=True)
                (root / "alias").symlink_to(root / "real", target_is_directory=True)
                runs[:] = [run([2], dict(metadata, python_executable=str(root / "real/bin/python")))]
                self.assertEqual(compare.load_means("unused", root / "alias/bin/python"), {"result": 2})

    def test_missing_and_dependency_failures_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            compare.save(work / "state.json", {"protocol": {"blocks": 2}, "runs": {}})
            suite = {"selection": "all", "unavailable_for_python": ["old_python"],
                     "benchmarks": {"missing": {"group": "ok"}, "unbuilt": {"group": "bad"}},
                     "groups": {"ok": {"returncode": 0},
                                "bad": {"returncode": 1, "log": "dependency.log"}}}
            with patch.dict(sys.modules, pyperf=types.SimpleNamespace()):
                self.assertEqual(compare.report(work, suite), 1)
            report = (work / "compare.md").read_text()
            self.assertIn("missing: missing", report)
            self.assertIn("unbuilt: dependency preparation failed", report)
            self.assertIn("old_python", report)
            self.assertIn("比較result: 0", report)

    def test_ft_fallback_requires_explicit_observed_metadata(self):
        python = Path("/tmp/venv/bin/python")
        meta = {"ft_build": 1, "gil_enabled": 0, "jit_enabled": 0,
                "jit_requested": 1, "jit_suspension_allowed": 1,
                "jit_suspension_observed": 1, "python_executable": str(python)}
        run = types.SimpleNamespace(values=[1], get_metadata=lambda: meta)
        bench = types.SimpleNamespace(get_runs=lambda: [run], get_name=lambda: "threaded")
        pyperf = types.SimpleNamespace(BenchmarkSuite=types.SimpleNamespace(load=lambda _: [bench]))
        with patch.dict(sys.modules, pyperf=pyperf):
            self.assertEqual(compare.load_means("unused", python), {"threaded": 1})
            for field in ("jit_requested", "jit_suspension_allowed", "jit_suspension_observed"):
                with patch.dict(meta, {field: 0}), self.assertRaises(AssertionError):
                    compare.load_means("unused", python)
            compare.select_profile("gil-pgo-lto")
            meta.update(ft_build=0, gil_enabled=1)
            with self.assertRaises(AssertionError):
                compare.load_means("unused", python)

    @unittest.skipUnless(importlib.util.find_spec("pyperf"), "requires pyperf")
    def test_real_pyperf_multi_result_roundtrip(self):
        import pyperf
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            suite = {"selection": "test", "unavailable_for_python": [],
                     "benchmarks": {"multi": {"group": "ok"}},
                     "groups": {"ok": {"returncode": 0}}}
            state = {"protocol": {"blocks": 2}, "runs": {},
                     "identities_verified_after": True}
            for block in range(2):
                for side, scale in (("main", 1), ("candidate", 0.8)):
                    python = work / side / "bin/python"
                    metadata = {"ft_build": 1, "gil_enabled": 0, "jit_enabled": 1,
                                "python_executable": str(python), "loops": 1}
                    batch = pyperf.BenchmarkSuite([
                        pyperf.Benchmark([pyperf.Run([scale, scale, 10 * scale],
                                                    metadata=dict(metadata, name=name))])
                        for name in ("first", "second")])
                    target = work / f"{block}-{side}.json"
                    batch.dump(str(target))
                    state["runs"][f"{block}:multi:{side}"] = {
                        "returncode": 0, "side": side, "output": str(target),
                        "sha256": compare.sha(target), "means": compare.load_means(target, python)}
            compare.save(work / "state.json", state)
            with patch.object(compare, "command", return_value={"returncode": 0}):
                self.assertEqual(compare.report(work, suite), 0)
            self.assertIn("0.8000", (work / "compare.md").read_text())
            self.assertEqual(pyperf.BenchmarkSuite.load(str(work / "main.json")).get_benchmark_names(),
                             ["first", "second"])
            target.write_text("corrupted")
            with self.assertRaisesRegex(RuntimeError, "Result changed"):
                compare.report(work, suite)


if __name__ == "__main__":
    unittest.main()
