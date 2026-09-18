#!/usr/bin/env python3
"""Prepare and run a frozen main/candidate JIT pyperformance comparison.

Only preparation runs here when --prepare-only is given. The full benchmark run
is deliberately a separate user-invoked step. No git checkout, push or system
tuning is performed. pyperformance's pinned metadata selects unmodified scripts.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PINS = ["pyperformance==1.14.0", "pyperf==2.10.0"]
FLAGS = "-O3 -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer"
CONFIGURE = ["--disable-gil", "--enable-experimental-jit=yes",
             "--disable-optimizations", "--without-lto", "--without-pydebug"]
RUNTIME = {"PYTHON_JIT": "1", "PYTHON_GIL": "0", "PYTHONHASHSEED": "0",
           "PYTHONNOUSERSITE": "1", "PYTHONFAULTHANDLER": "1"}
PARALLEL = {"concurrent_imap", "dask", "fastapi"}
THREADED = PARALLEL | {"tornado_http", "asyncio_websockets"}
BUILD_PROFILE = "ft"


def select_profile(name):
    global BUILD_PROFILE, CONFIGURE, RUNTIME
    BUILD_PROFILE = name
    optimized = name == "gil-pgo-lto"
    CONFIGURE = ["--enable-gil" if optimized else "--disable-gil",
                 "--enable-experimental-jit=yes",
                 "--enable-optimizations" if optimized else "--disable-optimizations",
                 "--with-lto=full" if optimized else "--without-lto", "--without-pydebug"]
    RUNTIME = {"PYTHON_JIT": "1", "PYTHON_GIL": "1" if optimized else "0",
               "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1",
               "PYTHONFAULTHANDLER": "1",
               "PYPERF_EXPECT_FT": "0" if optimized else "1"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def environment(work):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "PYPERF")) and key not in (
               "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CFLAGS_NODIST",
               "LDFLAGS_NODIST", "CONFIG_SITE", "MAKEFLAGS", "PROFILE_TASK",
               "GCOV_PREFIX", "GCOV_PREFIX_STRIP", "LLVM_PROFILE_FILE")}
    env.update(RUNTIME)
    env.update(CFLAGS=FLAGS, CXXFLAGS=FLAGS, PIP_CACHE_DIR=str(work / "pip-cache"),
               PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    return env


def command(argv, log, env, *, cwd=None, timeout=None):
    """Bound the entire process group, including pyperf grandchildren."""
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        index = 1
        while log.with_name(f"{log.name}.previous-{index}").exists():
            index += 1
        log.rename(log.with_name(f"{log.name}.previous-{index}"))
    start = time.monotonic()
    with log.open("w") as stream:
        stream.write(shlex.join(map(str, argv)) + "\n")
        stream.flush()
        proc = subprocess.Popen(list(map(str, argv)), cwd=cwd, env=env,
                                stdout=stream, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            if isinstance(exc, KeyboardInterrupt):
                raise
            rc = 124
    return {"command": list(map(str, argv)), "returncode": rc,
            "seconds": time.monotonic() - start, "log": str(log)}


def checked(argv, log, env, **kwargs):
    result = command(argv, log, env, **kwargs)
    if result["returncode"]:
        raise RuntimeError(f"Command failed ({result['returncode']}): {log}\n"
                           + log.read_text(errors="replace")[-2500:])
    return result


def output(argv, env=None):
    return subprocess.check_output(list(map(str, argv)), env=env, text=True).strip()


def bootstrap(args, work):
    """Build committed sources in private directories, then re-exec in a venv."""
    env = environment(work)
    build_env = env.copy()
    # make invokes a non-FT bootstrap Python (e.g. python3.13 for stencils).
    build_env.pop("PYTHON_GIL", None)
    build_env["PYTHON_JIT"] = "0"
    config_path = work / "build-plan.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        if args.run_only or args.report_only:
            raise RuntimeError("Run --prepare-only first")
        config = {"commits": {"main": output(["git", "-C", ROOT, "rev-parse", args.main_ref]),
                              "candidate": output(["git", "-C", ROOT, "rev-parse", args.candidate_ref])},
                  "configure": CONFIGURE, "cflags": FLAGS, "cc": shutil.which("gcc"),
                  "pins": PINS, "baseline_patch_sha256": sha(HERE / "main-llvm21.patch"),
                  "build_profile": BUILD_PROFILE,
                  "pgo_training": "JIT off, fixed seed 0, cold private pycache, standard --pgo suite"
                  if BUILD_PROFILE == "gil-pgo-lto" else None,
                  "host": platform.platform()}
        save(config_path, config)
    if config["configure"] != CONFIGURE or config["cflags"] != FLAGS or config["pins"] != PINS:
        raise RuntimeError("Preparation settings changed; use a new output directory")
    if config["baseline_patch_sha256"] != sha(HERE / "main-llvm21.patch"):
        raise RuntimeError("Baseline patch changed; use a new output directory")
    env["CC"] = config["cc"]
    build_env["CC"] = config["cc"]
    if not (args.run_only or args.report_only):
        for side in ("main", "candidate"):
            commit = config["commits"][side]
            source, build = work / f"{side}-src", work / f"{side}-build"
            marker = build / "build-complete.json"
            if marker.exists():
                print(f"BUILD {side}: reuse frozen {commit[:12]}", flush=True)
                continue
            print(f"BUILD {side}: {commit[:12]} ({BUILD_PROFILE})", flush=True)
            if not source.exists():
                archive = work / f"{side}-source.tar"
                checked(["git", "-C", ROOT, "archive", "-o", archive, commit],
                        work / f"{side}-archive.log", build_env)
                source.mkdir()
                with tarfile.open(archive) as tar:
                    tar.extractall(source, filter="data")
                archive.unlink()
                if side == "main":
                    # LLVM 21 emits local references otherwise deleted by main.
                    checked(["patch", "--batch", "--forward", "-p1", "-i",
                             HERE / "main-llvm21.patch"], work / "main-patch.log",
                            build_env, cwd=source)
                    shutil.copy2(HERE / "main-llvm21.patch", work / "main-applied.patch")
            build.mkdir(exist_ok=True)
            if side == "main":
                checked(["patch", "--batch", "--dry-run", "--reverse", "-p1", "-i",
                         HERE / "main-llvm21.patch"], work / "main-patch-check.log", build_env, cwd=source)
            if not (build / "Makefile").exists():
                checked([source / "configure", *CONFIGURE], work / f"{side}-configure.log",
                        build_env, cwd=build)
            # The locally installed 3.13 occasionally fails to reap asyncio
            # LLVM children; use the system Python already validated here.
            make = ["make", f"-j{args.jobs}", "PYTHON_FOR_REGEN=/usr/bin/python3.12"]
            if BUILD_PROFILE == "gil-pgo-lto":
                training = (f"-B -X pycache_prefix={shlex.quote(str(build / 'pgo-pycache'))} "
                            "-m test --pgo --timeout=1200 --randseed=0")
                make += [f"PROFILE_TASK={training}"]
                if not (build / "profile-run-stamp").exists():
                    checked([*make, "profile-gen-stamp"], work / f"{side}-pgo-generate.log",
                            build_env, cwd=build)
                    # Isolate bootstrap profiles and any failed training attempt.
                    # Neither may accumulate into the actual training corpus.
                    previous = work / f"{side}-pgo-before-training-{time.time_ns()}"
                    for profile in build.rglob("*.gcda"):
                        target = previous / profile.relative_to(build)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        profile.rename(target)
                    checked([*make, "profile-run-stamp"], work / f"{side}-pgo-training.log",
                            build_env, cwd=build)
            checked(make,
                    work / f"{side}-build.log", build_env, cwd=build)
            probe = output([build / "python", "-c", PROBE], env)
            identity = json.loads(probe)
            validate_build(identity)
            identity["sha256"] = sha(build / "python")
            if BUILD_PROFILE == "gil-pgo-lto":
                profiles = {str(p.relative_to(build)): sha(p) for p in sorted(build.rglob("*.gcda"))}
                assert profiles and (build / "profile-run-stamp").exists(), "Missing PGO training data"
                save(work / f"{side}-pgo.json", {
                    "task": training, "jit": 0, "hashseed": 0,
                    "profiles": profiles, "test_source_sha256": tree_hash(source / "Lib/test"),
                    "log": str(work / f"{side}-pgo-training.log")})
            save(marker, identity)
        controller = work / "controller"
        if not (controller / "ready.json").exists():
            checked([work / "main-build/python", "-m", "venv", controller],
                    work / "controller-create.log", env)
            checked([controller / "bin/python", "-m", "pip", "install", *PINS],
                    work / "controller-install.log", env, timeout=600)
            save(controller / "ready.json", {"pins": PINS})
    python = work / "controller/bin/python"
    if not python.exists():
        raise RuntimeError("Missing controller; run --prepare-only first")
    os.execve(python, [str(python), str(Path(__file__).resolve()), *sys.argv[1:],
                       "--controller"], env)


PROBE = """
import json, sys, sysconfig
keys = ('Py_GIL_DISABLED', 'Py_DEBUG', 'CONFIG_ARGS', 'CFLAGS', 'PY_CFLAGS',
        'PY_CFLAGS_NODIST', 'LDFLAGS', 'PY_LDFLAGS', 'PY_LDFLAGS_NODIST', 'SOABI')
print(json.dumps(dict(executable=sys.executable, version=sys.version,
    jit=sys._jit.is_enabled(), gil=sys._is_gil_enabled(),
    config={k:sysconfig.get_config_var(k) for k in keys})))
"""


def validate_build(identity):
    config = identity["config"]
    optimized = BUILD_PROFILE == "gil-pgo-lto"
    assert bool(config["Py_GIL_DISABLED"]) == (not optimized) and not config["Py_DEBUG"], identity
    assert identity["jit"] and bool(identity["gil"]) == optimized, identity
    flags = " ".join(str(value) for value in config.values())
    assert "-O3" in flags and "-fno-omit-frame-pointer" in flags, flags
    assert "-fprofile-generate" not in flags, flags
    if optimized:
        assert "-flto" in flags and "-fprofile-use" in flags, flags
        assert "--enable-optimizations" in flags and "--with-lto=full" in flags, flags
    else:
        assert not any(flag in flags for flag in ("-flto", "-fprofile-use")), flags
        # Both options default to off. Existing builds need not have spelled
        # out --disable-optimizations/--without-lto at configure time.
        options = shlex.split(config["CONFIG_ARGS"])
        assert not any(option in ("--enable-optimizations", "--enable-optimizations=yes", "--with-lto")
                       or option.startswith("--with-lto=") and option != "--with-lto=no"
                       for option in options), flags


def tree_hash(path):
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
            digest.update(str(file.relative_to(path)).encode() + b"\0")
            digest.update(bytes.fromhex(sha(file)))
    return digest.hexdigest()


def site_dir(python, env):
    return Path(output([python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], env))


def install_hook(site):
    shutil.copy2(HERE / "ft_jit_hook.py", site / "ft_jit_hook.py")
    info = site / "ft_jit_hook-1.0.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: ft-jit-hook\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text("[pyperf.hook]\nft_jit = ft_jit_hook:CheckRuntime\n")


def prepare(args, work, env):
    from packaging.utils import parse_wheel_filename
    from pyperformance._manifest import load_manifest
    from pyperformance.cli import _select_benchmarks
    manifest = load_manifest(None)
    all_specs = {bench.name: bench for bench in manifest.benchmarks}
    selected = {bench.name: bench for bench in _select_benchmarks(args.benchmarks, manifest)}
    if not selected:
        raise RuntimeError("No benchmarks selected")
    suite = {"selection": args.benchmarks, "python": platform.python_version(),
             "unavailable_for_python": sorted(set(all_specs) - set(selected))
             if args.benchmarks == "all" else [], "benchmarks": {}, "groups": {}}
    path = work / "suite.json"
    if path.exists():
        suite = json.loads(path.read_text())
        if suite["selection"] != args.benchmarks:
            raise RuntimeError("Selection changed; use a new output directory")
        if suite.get("prepared"):
            verify(work, suite, env)
            print("PREPARE: reuse frozen suite", flush=True)
            return suite
    for index, (name, bench) in enumerate(sorted(selected.items()), 1):
        lock = Path(bench.requirements_lockfile)
        # Include resolved lockfile paths: some requirements contain local paths.
        requirements = lock.read_text().strip() if lock.exists() else ""
        # Install the benchmark's vendored lib2to3 before timing, without
        # allowing the benchmark to mutate a frozen dependency environment.
        vendor = Path(bench.runscript).parent / "vendor" if name == "2to3" else None
        key = hashlib.sha256((str(lock) + requirements + str(vendor)).encode()).hexdigest()[:16] if requirements or vendor else "stdlib"
        row = {"script": bench.runscript, "extra_opts": bench.extra_opts or [],
               "group": key, "requirements": str(lock)}
        suite["benchmarks"][name] = row
        if key in suite["groups"]:
            continue
        print(f"PREPARE {index}/{len(selected)} {name}", flush=True)
        group = work / "dependencies" / key
        group.mkdir(parents=True, exist_ok=True)
        wheels = group / "wheels"
        wheels.mkdir(exist_ok=True)
        downloads = group / "downloads"
        downloads.mkdir(exist_ok=True)
        # Reuse pure-Python wheels. Rebuilding their legacy packaging metadata
        # adds avoidable failures and cannot affect native frame pointers.
        argv = [sys.executable, "-m", "pip", "wheel", "--wheel-dir", downloads, *PINS,
                "setuptools==80.9.0"]  # distutils for legacy benchmark dependencies
        if lock.exists():
            argv += ["-r", lock]
        if vendor:
            argv.append(vendor)
        result = command(argv, group / "wheel.log", env, timeout=args.install_timeout)
        suite["groups"][key] = result
        if not result["returncode"]:
            result["native_builds"] = []
            deadline = time.monotonic() + max(0, args.install_timeout - result["seconds"])
            for wheel in sorted(downloads.glob("*.whl")):
                package, version, _, tags = parse_wheel_filename(wheel.name)
                if all(tag.abi == "none" and tag.platform == "any" for tag in tags):
                    shutil.copy2(wheel, wheels / wheel.name)
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    result["returncode"] = 124
                    result["preparation_error"] = "dependency preparation time budget exceeded"
                    break
                native = command([sys.executable, "-m", "pip", "wheel", "--verbose",
                                  "--no-binary=:all:", "--no-deps", "--wheel-dir", wheels,
                                  f"{package}=={version}"], group / f"native-{package}.log",
                                 env, timeout=remaining)
                result["native_builds"].append(native)
                if native["returncode"]:
                    result["returncode"] = native["returncode"]
                    result["failure_log"] = native["log"]
                    break
        if not result["returncode"]:
            for side in ("main", "candidate"):
                venv = group / side
                checked([work / f"{side}-build/python", "-m", "venv", "--without-pip", venv],
                        group / f"{side}-create.log", env)
                python = venv / "bin/python"
                checked([sys.executable, "-m", "pip", "--python", python, "install",
                         "--no-index", "--no-deps", *sorted(wheels.glob("*.whl"))],
                        group / f"{side}-install.log", env, timeout=args.install_timeout)
                install_hook(site_dir(python, env))
                validate_build(json.loads(output([python, "-c", PROBE], env)))
                if vendor:
                    checked([python, "-c", "import lib2to3.pygram"],
                            group / f"{side}-grammar.log", env)
            result["wheels"] = {p.name: sha(p) for p in sorted(wheels.glob("*.whl"))}
            result["packages"] = output([sys.executable, "-m", "pip", "--python",
                                         group / "main/bin/python", "freeze", "--all"], env).splitlines()
        else:
            print(f"  unavailable: dependency build/install failed; {result.get('failure_log', result['log'])}", flush=True)
        save(path, suite)
    save(work / "identities.json", identities(work, suite, env))
    suite["prepared"] = True
    save(path, suite)
    return suite


def identities(work, suite, env):
    import pyperformance
    identities = {"builds": {}, "dependencies": {}, "harness": {}}
    for side in ("main", "candidate"):
        build = work / f"{side}-build"
        validate_build(json.loads(output([build / "python", "-c", PROBE], env)))
        extensions = build / (build / "pybuilddir.txt").read_text().strip()
        identities["builds"][side] = {
            "files": {str(p.relative_to(build)): sha(p) for p in
                      [build / "python", build / "Makefile", build / "pyconfig.h", *sorted(extensions.glob("*.so"))]},
            "stdlib_sha256": tree_hash(work / f"{side}-src/Lib")}
    for key, group in suite["groups"].items():
        if group["returncode"]:
            continue
        hashes = {}
        for side in ("main", "candidate"):
            python = work / f"dependencies/{key}/{side}/bin/python"
            binary_sha = sha(python)
            if binary_sha != identities["builds"][side]["files"]["python"]:
                raise RuntimeError(f"Dependency venv points to the wrong binary: {python}")
            hashes[side] = {"site_sha256": tree_hash(site_dir(python, env)),
                            "python_sha256": binary_sha}
        # pip RECORD/direct_url.json have venv-dependent paths. Hash each tree,
        # and verify identical wheel inputs instead of claiming byte equality.
        identities["dependencies"][key] = hashes
    identities["workloads_sha256"] = tree_hash(Path(suite.get("workloads_directory", pyperformance.DATA_DIR)))
    identities["harness"] = {p.name: sha(p) for p in
                             [Path(__file__), HERE / "ft_jit_hook.py", HERE / "main-llvm21.patch"]}
    if suite.get("identity_files"):
        identities["extra_files"] = {path: sha(path) for path in suite["identity_files"]}
    return identities


def verify(work, suite, env):
    expected = json.loads((work / "identities.json").read_text())
    if identities(work, suite, env) != expected:
        raise RuntimeError("Build/dependency/workload/runner identity changed; use a new preparation directory")


def load_means(path, python):
    import pyperf
    result = {}
    for bench in pyperf.BenchmarkSuite.load(str(path)):
        process_means = []
        for run in bench.get_runs():
            if not run.values:
                continue
            meta = run.get_metadata()
            optimized = BUILD_PROFILE == "gil-pgo-lto"
            assert meta["ft_build"] == int(not optimized) and meta["gil_enabled"] == int(optimized), meta
            if meta["jit_enabled"] != 1:
                assert not optimized and meta["jit_enabled"] == 0, meta
                assert meta.get("jit_requested") == 1, meta
                assert meta.get("jit_suspension_allowed") == 1, meta
                assert meta.get("jit_suspension_observed") == 1, meta
            if "python_executable" in meta:
                executable = meta["python_executable"]
            else:
                # bench_command (startup, 2to3) records command instead.
                # The hook checks its measuring Python, not the spawned child.
                executable = shlex.split(meta["command"])[0]
            actual = Path(executable).absolute()
            # pyperf normalizes directory symlinks. Preserve the venv identity
            # instead of resolving the executable symlink to its base binary.
            assert actual.parent.resolve() == python.absolute().parent.resolve(), meta
            assert actual.name == python.name, meta
            process_means.append(statistics.mean(run.values))
        assert process_means, bench.get_name()
        result[bench.get_name()] = statistics.mean(process_means)
    assert result, path
    return result


def run_suite(args, work, suite, env):
    verify(work, suite, env)
    affinity = args.cpu or str(min(os.sched_getaffinity(0)))
    parallel = args.parallel_cpus or ",".join(map(str, sorted(os.sched_getaffinity(0))))
    protocol = {"cpu": affinity, "parallel_cpus": parallel, "blocks": args.blocks,
                "processes": args.processes, "values": args.values, "warmups": args.warmups,
                "worker_timeout": args.timeout, "networkx_timeout": args.networkx_timeout,
                "spec_timeout": args.spec_timeout, "networkx_spec_timeout": args.networkx_spec_timeout,
                "environment": RUNTIME, "ft_thread_suspension": sorted(THREADED),
                "loop_calibration": "independent, normalized by pyperf"}
    path = work / "state.json"
    if path.exists():
        state = json.loads(path.read_text())
        if state["protocol"] != protocol:
            raise RuntimeError("Run settings changed; use a new output directory")
        for row in state["runs"].values():
            if row.get("sha256") and sha(row["output"]) != row["sha256"]:
                raise RuntimeError(f"Previous result changed: {row['output']}")
    else:
        state = {"protocol": protocol, "host": platform.platform(), "runs": {},
                 "cpu_topology": output(["lscpu", "-e=CPU,CORE,SOCKET,MAXMHZ"])}
        save(path, state)
    names = sorted(suite["benchmarks"])
    for block in range(args.blocks):
        for index, name in enumerate(names):
            spec = suite["benchmarks"][name]
            group = suite["groups"][spec["group"]]
            if group["returncode"]:
                continue
            order = ("main", "candidate") if (block + index) % 2 == 0 else ("candidate", "main")
            for side in order:
                key = f"{block}:{name}:{side}"
                if key in state["runs"]:
                    continue  # Failures are retained too; never retry to select faster runs.
                target = work / "results" / f"{block}-{name}-{side}.json"
                target.parent.mkdir(exist_ok=True)
                if target.exists():
                    raise RuntimeError(f"Unrecorded partial output: {target}; preserve it and use a new output directory")
                python = work / f"dependencies/{spec['group']}/{side}/bin/python"
                networkx = name.startswith("networkx")
                cpus = parallel if name in PARALLEL else affinity
                run_env = dict(env, PYPERF_ALLOW_JIT_SUSPENSION=str(int(
                    BUILD_PROFILE == "ft" and name in THREADED)))
                cmd = [python, spec["script"], *spec["extra_opts"], "--output", target,
                       f"--affinity={cpus}", f"--processes={args.processes}",
                       f"--values={args.values}", f"--warmups={args.warmups}",
                       "--min-time=0.1", f"--timeout={args.networkx_timeout if networkx else args.timeout}",
                       "--hook=ft_jit", "--inherit-environ=" + ",".join([*RUNTIME, "PYPERF_ALLOW_JIT_SUSPENSION"])]
                print(f"RUN block {block + 1}/{args.blocks} {index + 1}/{len(names)} {name} {side}", flush=True)
                result = command(cmd, target.with_suffix(".log"), run_env, cwd=work,
                                 timeout=args.networkx_spec_timeout if networkx else args.spec_timeout)
                result.update(block=block, name=name, side=side, output=str(target), affinity=cpus)
                if target.exists():
                    result["sha256"] = sha(target)
                if not result["returncode"]:
                    try:
                        result["means"] = load_means(target, python)
                    except (AssertionError, KeyError, ValueError) as exc:
                        result["returncode"] = 1
                        result["validation_error"] = repr(exc)
                state["runs"][key] = result
                save(path, state)
                print(f"  rc={result['returncode']} elapsed={result['seconds']:.1f}s", flush=True)
    verify(work, suite, env)
    state["identities_verified_after"] = True
    state["finished"] = True
    save(path, state)
    return report(work, suite)


def report(work, suite):
    import pyperf
    state = json.loads((work / "state.json").read_text())
    for row in state["runs"].values():
        if row.get("sha256") and sha(row["output"]) != row["sha256"]:
            raise RuntimeError(f"Result changed: {row['output']}")
    conditions = ("GIL有効、JIT要求、-O3、PGO/full LTOあり" if BUILD_PROFILE == "gil-pgo-lto"
                  else "GIL無効、JIT要求、-O3、PGO/LTOなし")
    lines = ["# JIT: main / candidate", "",
             "candidate/mainの実行時間比。各workerの全測定値の平均を等重みで集計し、",
             "各ブロックの比を幾何平均する。校正・warmupは集計対象外。",
             "固定ビルドでの比較であり、再ビルド・別CPUへの一般化はしていない。", "",
             f"Python条件: {conditions}。選択: `{suite['selection']}`。",
             f"計測後の同一性検証: {state.get('identities_verified_after', False)}。", "",
             "| Specification / result | candidate/main | 時間短縮 | ブロック比 |",
             "|---|---:|---:|---|"]
    ratios, failures, suspensions = [], [], set()
    aggregates = {"main": None, "candidate": None}
    for name, spec in sorted(suite["benchmarks"].items()):
        group = suite["groups"][spec["group"]]
        if group["returncode"]:
            failures.append(f"{name}: dependency preparation failed (see {group.get('failure_log', group['log'])})")
            continue
        rows = [state["runs"].get(f"{block}:{name}:{side}")
                for block in range(state["protocol"]["blocks"]) for side in ("main", "candidate")]
        if any(not row or row["returncode"] for row in rows):
            details = ["missing" if not row else f"block={row['block']} {row['side']} rc={row['returncode']}"
                       for row in rows if not row or row["returncode"]]
            failures.append(f"{name}: " + "; ".join(details))
            continue
        result_names = set(rows[0]["means"])
        if any(set(row["means"]) != result_names for row in rows):
            failures.append(f"{name}: result-name mismatch")
            continue
        for result_name in sorted(result_names):
            pairs = [rows[i + 1]["means"][result_name] / rows[i]["means"][result_name]
                     for i in range(0, len(rows), 2)]
            ratio = statistics.geometric_mean(pairs)
            ratios.append(ratio)
            lines.append(f"| {name} / {result_name} | {ratio:.4f} | {100 * (1-ratio):.2f}% | "
                         + ", ".join(f"{r:.4f}" for r in pairs) + " |")
        for row in rows:
            batch = pyperf.BenchmarkSuite.load(row["output"])
            side = row["side"]
            for benchmark in batch:
                if any(run.get_metadata().get("jit_suspension_observed")
                       for run in benchmark.get_runs() if run.values):
                    suspensions.add(f"{name}/{benchmark.get_name()} ({side})")
            if aggregates[side] is None:
                aggregates[side] = batch
            else:
                aggregates[side].add_runs(batch)
    if suspensions:
        lines += ["", "FTのスレッド共存中のJIT停止を観測した項目（Tier 1へのfallbackを含む）:",
                  *[f"- {name}" for name in sorted(suspensions)],
                  "", "これらはJITを要求した設定での性能であり、常時JIT有効・並列JIT実行の測定ではない。",
                  "開始・終了時の検査なので、測定中すべての状態遷移を観測したものではない。"]
    lines += ["", f"選択したspecification: {len(suite['benchmarks'])}、"
              f"両側全ブロック完了: {len(suite['benchmarks']) - len(failures)}、比較result: {len(ratios)}。"]
    if ratios:
        lines += [f"完了resultのみの幾何平均: {statistics.geometric_mean(ratios):.4f}。"
                  "欠落項目を含むsuite全体の性能値ではない。"]
    lines += ["", "## 失敗・未対応", ""] + [f"- {failure}" for failure in failures]
    lines += [f"- Pythonバージョン制約で対象外: {', '.join(suite['unavailable_for_python']) or 'なし'}"]
    (work / "compare.md").write_text("\n".join(lines) + "\n")
    for side, batch in aggregates.items():
        if batch is not None:
            target = work / f"{side}.json"
            if target.exists():
                target.unlink()  # Derived aggregate only; raw process files are immutable.
            batch.dump(str(target))
            command([sys.executable, "-m", "pyperf", "check", target],
                    work / f"check-{side}.log", environment(work))
    print(f"Report: {work / 'compare.md'}; incomplete specifications: {len(failures)}", flush=True)
    return int(bool(failures) or not state.get("identities_verified_after"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="new or previously prepared experiment directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--run-only", action="store_true")
    mode.add_argument("--report-only", action="store_true")
    parser.add_argument("--main-ref", default="main")
    parser.add_argument("--candidate-ref", default="HEAD")
    parser.add_argument("--build-profile", choices=("ft", "gil-pgo-lto"), default="ft")
    parser.add_argument("--benchmarks", default="all")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--cpu", default="2")
    parser.add_argument("--parallel-cpus")
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--processes", type=int, default=6)
    parser.add_argument("--values", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--networkx-timeout", type=int, default=15)
    parser.add_argument("--spec-timeout", type=int, default=600)
    parser.add_argument("--networkx-spec-timeout", type=int, default=180)
    parser.add_argument("--install-timeout", type=int, default=600)
    parser.add_argument("--controller", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    select_profile(args.build_profile)
    for key in ("jobs", "blocks", "processes", "values", "warmups", "timeout",
                "networkx_timeout", "spec_timeout", "networkx_spec_timeout", "install_timeout"):
        if getattr(args, key) < 1:
            parser.error(f"--{key.replace('_', '-')} must be positive")
    work = args.directory.resolve()
    work.mkdir(parents=True, exist_ok=True)
    for option in (args.cpu, args.parallel_cpus):
        if option is None:
            continue
        cpus = set()
        try:
            for part in option.split(","):
                bounds = list(map(int, part.split("-")))
                if len(bounds) == 1:
                    cpus.add(bounds[0])
                elif len(bounds) == 2 and bounds[0] <= bounds[1]:
                    cpus.update(range(bounds[0], bounds[1] + 1))
                else:
                    raise ValueError
        except ValueError:
            parser.error(f"Invalid CPU affinity: {option}")
        if not cpus or not cpus <= os.sched_getaffinity(0):
            parser.error(f"CPU affinity {option} is outside the allowed CPU set")
    # The descriptor closes across bootstrap's exec; the controller reacquires it.
    lock = (work / ".runner.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError(f"Another runner is using {work}") from None
    if not args.controller:
        bootstrap(args, work)
    env = environment(work)
    if args.run_only or args.report_only:
        suite = json.loads((work / "suite.json").read_text())
        if not suite.get("prepared"):
            raise RuntimeError("Preparation is incomplete")
    else:
        suite = prepare(args, work, env)
    if args.prepare_only:
        print(f"Preparation complete. Run: {ROOT / 'benchmarks/run_pyperformance_compare.sh'} "
              f"--build-profile {BUILD_PROFILE} --run-only {work}")
        return 0
    if args.report_only:
        return report(work, suite)
    return run_suite(args, work, suite, env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, AssertionError) as exc:
        sys.exit(str(exc))
