#!/usr/bin/env python3
"""Compare four existing JIT builds, reusing cached wheels without rebuilding.

Each profile gets fresh dependency venvs and a separate immutable result set.
Pure Python wheels and workloads are shared across profiles; native wheels use
the corresponding main ABI. Full measurements are sequential, with reversed
main/candidate order in the second block within each build profile.
"""

import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pyperformance_compare as compare
import pyperformance_compat as compat


ROOT = compare.ROOT
ARTIFACTS = ROOT / "jit-artifacts"
CACHES = {name: ARTIFACTS / f"pyperformance-{name}-20260917"
          for name in ("ft", "gil-pgo-lto")}
CANDIDATES = {
    "ft": (ROOT / "build-method-ft-jit", ROOT),
    "gil-pgo-lto": (ARTIFACTS / "pyperformance-fixes-20260917/committed-final-pgo-build",
                    ARTIFACTS / "pyperformance-fixes-20260917/committed-final-pgo-src"),
}
CANDIDATE_PROVENANCE = ARTIFACTS / "pyperformance-fixes-20260917/committed-final-pgo-build.json"
CANDIDATE_FT_PROVENANCE = ARTIFACTS / "pyperformance-fixes-20260917/committed-final-ft-build.json"
SCRIPT = Path(__file__).resolve()
WRAPPER = ROOT / "benchmarks/run_pyperformance_four_way.sh"


def read(path):
    return json.loads(path.read_text())


def frozen_json(path, value):
    if path.exists():
        if read(path) != value:
            raise RuntimeError(f"Preparation inputs changed: {path}; use a new directory")
    else:
        compare.save(path, value)


def link(path, target):
    target = target.resolve(strict=True)
    if path.is_symlink() or path.exists():
        if path.resolve() != target:
            raise RuntimeError(f"Existing path points to a different input: {path}")
    else:
        path.symlink_to(target, target_is_directory=True)


def wheel_inputs(profile, names, canonical, cached):
    """Use identical pure wheels, replacing native wheels with the matching ABI."""
    from packaging.utils import parse_wheel_filename

    key = canonical["benchmarks"][names[0]]["group"]
    group = canonical["groups"][key]
    inputs = {}
    for filename, digest in group["wheels"].items():
        package, version, _, tags = parse_wheel_filename(filename)
        cache, wheel_key = CACHES["gil-pgo-lto"], key
        if profile == "ft" and not all(tag.abi == "none" and tag.platform == "any" for tag in tags):
            # All specifications sharing a canonical group must also use the
            # same FT dependency environment; don't silently select one version.
            keys = {cached["benchmarks"][name]["group"] for name in names}
            if len(keys) != 1:
                raise RuntimeError(f"Inconsistent FT dependency groups: {names}")
            wheel_key = keys.pop()
            matches = [name for name in cached["groups"][wheel_key].get("wheels", {})
                       if parse_wheel_filename(name)[:2] == (package, version)]
            if len(matches) != 1:
                raise RuntimeError(f"Missing or ambiguous FT wheel: {package}=={version}")
            filename = matches[0]
            digest = cached["groups"][wheel_key]["wheels"][filename]
            cache = CACHES["ft"]
        path = cache / "dependencies" / wheel_key / "wheels" / filename
        if compare.sha(path) != digest:
            raise RuntimeError(f"Cached wheel changed: {path}")
        inputs[str(path)] = digest
    return inputs


def sqlalchemy_inputs(profile, name, canonical, cached):
    """The two synchronous SQLite benchmarks do not need greenlet's async API."""
    from packaging.utils import parse_wheel_filename

    spec = canonical["benchmarks"][name]
    requirements = set(Path(spec["requirements"]).read_text().splitlines())
    if requirements != {"greenlet==3.2.4", "sqlalchemy==1.4.19"}:
        raise RuntimeError(f"Review changed SQLAlchemy requirements: {requirements}")
    # Standard runner dependencies plus the previously built main-ABI wheel.
    # --no-deps below intentionally bypasses greenlet's declared dependency.
    inputs = wheel_inputs(profile, ["richards_super"], canonical, cached)
    key = cached["benchmarks"][name]["group"]
    downloads = CACHES[profile] / "dependencies" / key / "downloads"
    wheels = [p for p in downloads.glob("*.whl")
              if str(parse_wheel_filename(p.name)[0]) == "sqlalchemy"
              and str(parse_wheel_filename(p.name)[1]) == "1.4.19"]
    if len(wheels) != 1:
        raise RuntimeError(f"Missing or ambiguous cached SQLAlchemy wheel: {downloads}")
    inputs[str(wheels[0])] = compare.sha(wheels[0])
    return inputs


def build_files(build):
    extensions = build / (build / "pybuilddir.txt").read_text().strip()
    paths = [build / "python", build / "Makefile", build / "pyconfig.h",
             *sorted(extensions.glob("*.so"))]
    return {str(path.relative_to(build)): compare.sha(path) for path in paths}


def candidate_provenance():
    provenance = read(CANDIDATE_PROVENANCE)
    ft_provenance = read(CANDIDATE_FT_PROVENANCE)
    for profile, label, manifest in (("gil-pgo-lto", "PGO", provenance),
                                     ("ft", "FT", ft_provenance)):
        files = build_files(CANDIDATES[profile][0])
        if manifest.get("sha256") != files["python"] or manifest.get("files") != files:
            raise RuntimeError(f"Candidate {label} build is incomplete or differs from its provenance")
    if (provenance["base_commit"] != ft_provenance["base_commit"] or
            provenance["changed"] != ft_provenance["changed"] or
            provenance.get("source_files") != ft_provenance.get("source_files")):
        raise RuntimeError("Candidate sources differ between FT and PGO build records")
    if not provenance.get("source_files"):
        raise RuntimeError("Candidate source file provenance is missing")
    for profile, (_, source) in CANDIDATES.items():
        for relative, digest in provenance["source_files"].items():
            if compare.sha(source / relative) != digest:
                raise RuntimeError(f"Candidate sources differ from {profile} build record: {relative}")
    return dict(provenance, ft_build=ft_provenance)


def prepare(args, work, env):
    provenance = candidate_provenance()
    profile = args.profile
    cache = CACHES[profile]
    for side, (build, source) in {
        "main": (cache / "main-build", cache / "main-src"),
        "candidate": CANDIDATES[profile],
    }.items():
        link(work / f"{side}-build", build)
        link(work / f"{side}-src", source)
    link(work / "controller", cache / "controller")

    suite_path = work / "suite.json"
    if suite_path.exists() and (work / "identities.json").exists():
        suite = read(suite_path)
        if suite["selection"] != args.benchmarks:
            raise RuntimeError("Selection changed; use a new directory")
        compare.verify(work, suite, env)
        print(f"PREPARE {profile}: reuse verified environments", flush=True)
        return suite

    canonical = read(CACHES["gil-pgo-lto"] / "suite.json")
    cached = read(cache / "suite.json")
    names = set(canonical["benchmarks"]) if args.benchmarks == "all" else set(args.benchmarks.split(","))
    if not names or names - canonical["benchmarks"].keys():
        raise RuntimeError(f"Unknown benchmark specifications: {sorted(names - canonical['benchmarks'].keys())}")
    suite = {"selection": args.benchmarks, "python": canonical["python"],
             "unavailable_for_python": canonical["unavailable_for_python"] if args.benchmarks == "all" else [],
             "benchmarks": {name: canonical["benchmarks"][name] for name in sorted(names)},
             "groups": {}}
    import pyperformance
    # The shared scripts live in the GIL controller. Both controllers install
    # the same pyperformance version, but only this directory is executed.
    original_workloads = CACHES["gil-pgo-lto"] / "controller/lib/python3.16/site-packages/pyperformance/data-files"
    if not original_workloads.is_dir():
        raise RuntimeError("Missing canonical pyperformance workloads")
    private_workloads = work / "workloads"
    if private_workloads.exists():
        raise RuntimeError("Incomplete preparation: preserve it and use a new directory")
    shutil.copytree(original_workloads, private_workloads,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    workload_patches = compat.workloads(private_workloads)
    suite["workloads_directory"] = str(private_workloads)
    for spec in suite["benchmarks"].values():
        for field in ("script", "requirements"):
            spec[field] = str(private_workloads / Path(spec[field]).relative_to(original_workloads))
    inputs = {"profile": profile, "selection": args.benchmarks,
              "main_provenance": read(cache / "build-plan.json"),
              "candidate_source_and_gil_build_provenance": provenance,
              "candidate_note": f"Committed benchmark fixes: {provenance['base_commit']}; see source file and binary hashes in the build records.",
              "builds": {}, "wheels": {}, "dependency_overrides": {},
              "pyperformance": pyperformance.__version__,
              "compatibility_patches": {"workloads": workload_patches},
              "harness": {str(p): compare.sha(p) for p in (SCRIPT, WRAPPER, Path(compare.__file__), Path(compat.__file__), compare.HERE / "ft_jit_hook.py")}}
    # The reused cache was built for an older comparison. Its candidate is
    # unrelated to the current candidate, so don't carry that commit label over.
    inputs["main_provenance"]["commits"].pop("candidate", None)
    for side in ("main", "candidate"):
        python = work / f"{side}-build/python"
        identity = json.loads(compare.output([python, "-c", compare.PROBE], env))
        compare.validate_build(identity)
        identity.update(path=str(python.resolve()), sha256=compare.sha(python))
        inputs["builds"][side] = identity
        print(f"{profile} {side}: {identity['path']} SHA256={identity['sha256']}", flush=True)
    for key in sorted({spec["group"] for spec in suite["benchmarks"].values()}):
        group = copy.deepcopy(canonical["groups"][key])
        group_names = [name for name in sorted(names) if suite["benchmarks"][name]["group"] == key]
        suite["groups"][key] = group
        if set(group_names) <= {"sqlalchemy_declarative", "sqlalchemy_imperative"}:
            inputs["wheels"][key] = sqlalchemy_inputs(profile, group_names[0], canonical, cached)
            override = "Omit greenlet==3.2.4 for synchronous SQLite benchmarks; SQLAlchemy remains pinned to 1.4.19."
            inputs["dependency_overrides"][key] = override
            group.update(original_preparation=copy.deepcopy(group), returncode=0,
                         skipped_dependencies=["greenlet==3.2.4"], dependency_override=override)
            continue
        if group["returncode"]:
            print(f"UNAVAILABLE {profile}: {', '.join(group_names)} (cached dependency failure)", flush=True)
            continue
        inputs["wheels"][key] = wheel_inputs(profile, group_names, canonical, cached)
    for key, sources in inputs["wheels"].items():
        group = work / "dependencies" / key
        wheels = group / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        for source, digest in sources.items():
            target = wheels / Path(source).name
            if target.exists():
                if compare.sha(target) != digest:
                    raise RuntimeError(f"Prepared wheel changed: {target}")
            else:
                shutil.copy2(source, target)
        print(f"PREPARE {profile}: {key}", flush=True)
        for side in ("main", "candidate"):
            venv = group / side
            compare.checked([work / f"{side}-build/python", "-m", "venv", "--without-pip", venv],
                            group / f"{side}-create.log", env)
            python = venv / "bin/python"
            compare.checked([sys.executable, "-m", "pip", "--python", python, "install",
                             "--no-index", "--no-deps", *sorted(wheels / Path(p).name for p in sources)],
                            group / f"{side}-install.log", env, timeout=args.install_timeout)
            site = compare.site_dir(python, env)
            inputs["compatibility_patches"][f"{key}/{side}"] = compat.dependencies(site)
            compare.install_hook(site)
            compare.validate_build(json.loads(compare.output([python, "-c", compare.PROBE], env)))
            if "2to3" in names and suite["benchmarks"]["2to3"]["group"] == key:
                compare.checked([python, "-c", "import lib2to3.pygram"], group / f"{side}-grammar.log", env)
            if key in inputs["dependency_overrides"]:
                compare.checked([python, "-c", "import importlib.util, sqlalchemy; "
                                 "from sqlalchemy.util import concurrency; "
                                 "assert importlib.util.find_spec('greenlet') is None; "
                                 "assert not concurrency.have_greenlet; "
                                 "assert sqlalchemy.__version__ == '1.4.19'; "
                                 "import sqlalchemy.cprocessors; "
                                 "print(sqlalchemy.__version__, sqlalchemy.cprocessors.__file__, 'greenlet absent')"],
                                group / f"{side}-sqlalchemy.log", env)
        suite["groups"][key]["wheels"] = {Path(p).name: digest for p, digest in sources.items()}
        suite["groups"][key]["reused_from"] = list(sources)
    suite["prepared"] = True
    frozen_json(work / "preparation.json", inputs)
    suite["identity_files"] = [str(p) for p in (suite_path, work / "preparation.json", SCRIPT, WRAPPER, Path(compat.__file__))]
    compare.save(suite_path, suite)
    compare.save(work / "identities.json", compare.identities(work, suite, env))
    return suite


def profile_main(args):
    compare.select_profile(args.profile)
    work = args.directory.resolve() / args.profile
    work.mkdir(parents=True, exist_ok=True)
    with (work / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = compare.environment(work)
        if args.phase == "prepare":
            prepare(args, work, env)
            return 0
        suite = read(work / "suite.json")
        if args.benchmarks != suite["selection"] or not suite.get("prepared"):
            raise RuntimeError("Missing preparation or changed selection")
        compare.verify(work, suite, env)
        if args.phase == "verify":
            return 0
        if args.phase == "report":
            return compare.report(work, suite)
        return compare.run_suite(args, work, suite, env)


def child(argv, profile, phase):
    compare.select_profile(profile)
    env = compare.environment(CACHES[profile])
    python = CACHES[profile] / "controller/bin/python"
    return subprocess.call([str(python), str(SCRIPT), *argv, "--profile", profile, "--phase", phase], env=env)


def run_profiles(args, argv):
    """Prepare both configurations before timing; retain failures and continue."""
    work = args.directory.resolve()
    results = {}
    if not args.report_only:
        for profile in CACHES:
            rc = child(argv, profile, "verify" if args.run_only else "prepare")
            if rc:
                raise RuntimeError(f"Preparation/verification failed for {profile} (exit {rc})")
    if args.prepare_only:
        command = [str(WRAPPER), *(arg for arg in argv if arg != "--prepare-only"), "--run-only"]
        print(f"Ready: {shlex.join(command)}", flush=True)
        return 0
    for profile in CACHES:
        results[profile] = child(argv, profile, "report" if args.report_only else "run")
        compare.save(work / "status.json", results)
    lines = ["# main / method-jit: four existing interpreters", "",
             "All four interpreters request PYTHON_JIT=1. The frozen main FT build does not compile executors, despite reporting JIT enabled; its baseline runs in Tier 1. Each profile has its own balanced main/candidate comparison.",
             "The profiles run sequentially; GIL versus FT is not a balanced causal comparison.", "",
             "| Profile | Exit status | Results |", "|---|---:|---|"]
    for profile, rc in results.items():
        lines.append(f"| {profile} | {rc} | [comparison]({profile}/compare.md) |")
    lines += ["", "Exit status 1 means incomplete benchmark specifications; see each profile's report and logs.",
              "All raw JSON, failures, identities and the run protocol are retained in the profile directories."]
    (work / "compare.md").write_text("\n".join(lines) + "\n")
    print(f"Reports: {work / 'compare.md'}", flush=True)
    return int(any(results.values()))


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    mode = parser.add_mutually_exclusive_group()
    for name in ("prepare-only", "run-only", "report-only"):
        mode.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--benchmarks", default="all", help="all or comma-separated specification names")
    parser.add_argument("--cpu", default="2")
    parser.add_argument("--parallel-cpus")
    for name, default in (("blocks", 2), ("processes", 6), ("values", 5), ("warmups", 5),
                          ("timeout", 60), ("networkx-timeout", 15), ("spec-timeout", 600),
                          ("networkx-spec-timeout", 180), ("install-timeout", 600)):
        parser.add_argument(f"--{name}", type=int, default=default)
    parser.add_argument("--profile", choices=tuple(CACHES), help=argparse.SUPPRESS)
    parser.add_argument("--phase", choices=("prepare", "verify", "run", "report"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    for key in ("blocks", "processes", "values", "warmups", "timeout", "networkx_timeout",
                "spec_timeout", "networkx_spec_timeout", "install_timeout"):
        if getattr(args, key) < 1:
            parser.error(f"--{key.replace('_', '-')} must be positive")
    for option in (args.cpu, args.parallel_cpus):
        if option is None:
            continue
        try:
            cpus = set()
            for part in option.split(","):
                bounds = list(map(int, part.split("-")))
                if len(bounds) == 1:
                    cpus.add(bounds[0])
                elif len(bounds) == 2 and bounds[0] <= bounds[1]:
                    cpus.update(range(bounds[0], bounds[1] + 1))
                else:
                    raise ValueError
            if not cpus or not cpus <= os.sched_getaffinity(0):
                raise ValueError
        except ValueError:
            parser.error(f"Invalid or unavailable CPU affinity: {option}")
    return args


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    if args.profile:
        return profile_main(args)
    work = args.directory.resolve()
    work.mkdir(parents=True, exist_ok=True)
    with (work / ".four-way.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_profiles(args, argv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (RuntimeError, AssertionError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
