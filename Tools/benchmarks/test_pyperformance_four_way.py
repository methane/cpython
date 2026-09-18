"""Check four-build orchestration and ABI-safe reuse without full measurements."""

from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import pyperformance_four_way as four


class FourWayTests(unittest.TestCase):
    def test_candidate_pair_rejects_incomplete_or_different_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.c"
            source.write_text("original")
            candidates = {}
            manifests = {}
            records = {}
            for profile in four.CANDIDATES:
                build = root / profile
                build.mkdir()
                (build / "lib").mkdir()
                (build / "pybuilddir.txt").write_text("lib")
                for name in ("python", "Makefile", "pyconfig.h", "lib/example.so"):
                    (build / name).write_text(profile + name)
                sources = build / "src"
                sources.mkdir()
                (sources / source.name).write_text("original")
                candidates[profile] = (build, sources)
                records[profile] = {
                    "base_commit": "same-commit",
                    "sha256": four.compare.sha(build / "python"),
                    "files": four.build_files(build),
                    "changed": {},
                    "source_files": {source.name: four.compare.sha(source)},
                }
                manifests[profile] = build / "build.json"
                four.compare.save(manifests[profile], records[profile])
            with patch.object(four, "CANDIDATES", candidates), \
                    patch.object(four, "CANDIDATE_PROVENANCE", manifests["gil-pgo-lto"]), \
                    patch.object(four, "CANDIDATE_FT_PROVENANCE", manifests["ft"]):
                expected = dict(records["gil-pgo-lto"], ft_build=records["ft"])
                self.assertEqual(four.candidate_provenance(), expected)
                for profile in candidates:
                    copied = candidates[profile][1] / source.name
                    copied.write_text("changed after commit")
                    with self.assertRaisesRegex(RuntimeError, "sources differ"):
                        four.candidate_provenance()
                    copied.write_text("original")
                for record in records.values():
                    record["source_files"] = {}
                for profile in records:
                    four.compare.save(manifests[profile], records[profile])
                with self.assertRaisesRegex(RuntimeError, "source file provenance is missing"):
                    four.candidate_provenance()
                for profile in records:
                    records[profile]["source_files"] = {source.name: four.compare.sha(source)}
                    four.compare.save(manifests[profile], records[profile])
                extension = candidates["ft"][0] / "lib/example.so"
                extension.write_text("stale extension with unchanged core")
                with self.assertRaisesRegex(RuntimeError, "FT build is incomplete"):
                    four.candidate_provenance()
                extension.write_text("ftlib/example.so")
                records["ft"]["base_commit"] = "different-commit"
                four.compare.save(manifests["ft"], records["ft"])
                with self.assertRaisesRegex(RuntimeError, "sources differ"):
                    four.candidate_provenance()
                records["ft"]["base_commit"] = "same-commit"
                four.compare.save(manifests["ft"], records["ft"])
                (candidates["gil-pgo-lto"][0] / "python").write_text("unfinished rebuild")
                with self.assertRaisesRegex(RuntimeError, "PGO build is incomplete"):
                    four.candidate_provenance()

    def test_failed_ft_benchmarks_do_not_skip_gil(self):
        with tempfile.TemporaryDirectory() as directory:
            args = types.SimpleNamespace(directory=Path(directory), report_only=False,
                                         prepare_only=False, run_only=False)
            with patch.object(four, "child", side_effect=[0, 0, 1, 0]) as child:
                self.assertEqual(four.run_profiles(args, []), 1)
            self.assertEqual([call.args[1:] for call in child.call_args_list],
                             [("ft", "prepare"), ("gil-pgo-lto", "prepare"),
                              ("ft", "run"), ("gil-pgo-lto", "run")])
            self.assertEqual(four.read(args.directory / "status.json"), {"ft": 1, "gil-pgo-lto": 0})

    def test_prepare_only_does_not_measure_and_run_only_verifies_both(self):
        with tempfile.TemporaryDirectory() as directory:
            args = types.SimpleNamespace(directory=Path(directory), report_only=False,
                                         prepare_only=True, run_only=False)
            with patch.object(four, "child", return_value=0) as child:
                self.assertEqual(four.run_profiles(args, []), 0)
                self.assertEqual([call.args[2] for call in child.call_args_list], ["prepare", "prepare"])
            args.prepare_only = False
            args.run_only = True
            with patch.object(four, "child", side_effect=[0, 2]) as child:
                with self.assertRaises(RuntimeError):
                    four.run_profiles(args, [])
                self.assertEqual([call.args[2] for call in child.call_args_list], ["verify", "verify"])

    def test_inputs_cannot_change_when_resuming(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            four.frozen_json(path, {"binary": "one"})
            four.frozen_json(path, {"binary": "one"})
            with self.assertRaises(RuntimeError):
                four.frozen_json(path, {"binary": "two"})
            self.assertEqual(four.read(path), {"binary": "one"})

    def test_wheels_share_pure_packages_but_not_native_abis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            caches = {profile: root / profile for profile in four.CACHES}
            pure = "sample-1.0-py3-none-any.whl"
            gil = "native-1.0-cp316-cp316-linux_x86_64.whl"
            ft = "native-1.0-cp316-cp316t-linux_x86_64.whl"
            suites = {}
            for profile, files in (("gil-pgo-lto", [pure, gil]), ("ft", [ft])):
                wheels = caches[profile] / "dependencies/group/wheels"
                wheels.mkdir(parents=True)
                hashes = {}
                for filename in files:
                    path = wheels / filename
                    path.write_text(filename)
                    hashes[filename] = four.compare.sha(path)
                suites[profile] = {"benchmarks": {"sample": {"group": "group"}},
                                   "groups": {"group": {"wheels": hashes}}}
            with patch.object(four, "CACHES", caches):
                inputs = four.wheel_inputs("ft", ["sample"], suites["gil-pgo-lto"], suites["ft"])
                self.assertEqual({Path(path).name for path in inputs}, {pure, ft})
                (caches["ft"] / "dependencies/group/wheels" / ft).write_text("changed")
                with self.assertRaisesRegex(RuntimeError, "Cached wheel changed"):
                    four.wheel_inputs("ft", ["sample"], suites["gil-pgo-lto"], suites["ft"])

    def test_sqlalchemy_override_only_omits_greenlet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "requirements.txt"
            lock.write_text("greenlet==3.2.4\nsqlalchemy==1.4.19\n")
            downloads = root / "dependencies/group/downloads"
            downloads.mkdir(parents=True)
            wheel = downloads / "sqlalchemy-1.4.19-cp316-cp316t-linux_x86_64.whl"
            wheel.write_text("SQLAlchemy")
            suite = {"benchmarks": {"sqlalchemy_declarative": {"group": "group", "requirements": str(lock)}}}
            with patch.object(four, "CACHES", {"ft": root}), patch.object(four, "wheel_inputs", return_value={}):
                inputs = four.sqlalchemy_inputs("ft", "sqlalchemy_declarative", suite, suite)
                self.assertEqual(inputs, {str(wheel): four.compare.sha(wheel)})
                lock.write_text("greenlet==3.2.4\nsqlalchemy==2.0.0\n")
                with self.assertRaisesRegex(RuntimeError, "Review changed SQLAlchemy requirements"):
                    four.sqlalchemy_inputs("ft", "sqlalchemy_declarative", suite, suite)


if __name__ == "__main__":
    unittest.main()
