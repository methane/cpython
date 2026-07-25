# AGENTS.md

This repository is **CPython** — the reference implementation of the Python
programming language (currently `3.15.0a8+`). It is a C interpreter plus the
Python standard library (`Lib/`) and documentation (`Doc/`). There are **no
runtime services, databases, or web servers**: "running the app" means building
the `./python` interpreter, and "end-to-end testing" means running the
regression test suite under `Lib/test/`.

Canonical developer instructions live in `README.rst` (section "Build
Instructions") and `.devcontainer/devcontainer.json`. Prefer those; the notes
below only capture non-obvious, durable context for working in the Cursor Cloud
environment.

## Cursor Cloud specific instructions

- **Build output location:** A successful `make` produces the interpreter at the
  repo root as `./python` (note: no `.exe` on Linux; only macOS produces
  `./python.exe`). Always invoke the freshly built interpreter as `./python`,
  never the system `python3` (which is 3.12 and unrelated to your changes).
- **Dev build flags:** Use a debug build for development:
  `./configure --config-cache --with-pydebug && make -s -j$(nproc)`. The update
  script already runs this on startup, so on a fresh VM `./python` is normally
  already built. After editing C sources, re-run `make -s -j$(nproc)`
  (incremental, fast). Editing pure-Python files under `Lib/` needs no rebuild.
- **`_decimal` module is expected to be missing** in this environment
  (`libmpdec` dev headers are not available from apt). The build still succeeds
  and `_decimal`/`test_decimal` simply won't be available. This is not an error.
- **System build dependencies** (installed once into the VM snapshot, not by the
  update script since they need `sudo`): `build-essential gdb pkg-config
  libbz2-dev libffi-dev libgdbm-dev libgdbm-compat-dev liblzma-dev
  libncurses5-dev libreadline6-dev libsqlite3-dev libssl-dev tk-dev uuid-dev
  zlib1g-dev libzstd-dev`. If a stdlib C-extension module is unexpectedly
  missing, install its `-dev` package and re-run `./configure` + `make`.
- **Running tests:** `./python -m test [names]` (add `-j$(nproc)` for
  parallelism, `-v` for verbose). `make test` runs the full suite and is slow;
  prefer naming specific test modules, e.g.
  `./python -m test -j4 test_grammar test_os test_json`. Tests for optional
  modules whose libs are absent are skipped, not failed.
- **Linting** uses `ruff` (pinned to the version in `.pre-commit-config.yaml`).
  It is installed via `pip --user`, so it lives at `~/.local/bin/ruff`; ensure
  `~/.local/bin` is on `PATH`. Ruff only targets specific subtrees
  (`Lib/test/`, `Doc/`, `Tools/*`, `Platforms/*`) as configured in
  `.pre-commit-config.yaml`, not the whole repo. A `warning: Support for Python
  3.15 is under development` line from ruff is expected and harmless.
- **Docs** (optional) build with `make --directory Doc venv html`; not required
  for interpreter development.
