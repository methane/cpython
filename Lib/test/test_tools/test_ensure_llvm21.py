import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test import support


SCRIPT = Path(support.REPO_ROOT) / "Tools" / "jit" / "ensure_llvm21.sh"
TOOLS = ("clang", "llvm-readobj", "llvm-objdump", "llvm-dwarfdump")


@support.requires_subprocess()
@unittest.skipUnless(os.name == "posix", "requires a POSIX shell")
@unittest.skipUnless(shutil.which("git"), "requires git")
@unittest.skipUnless(SCRIPT.is_file(), "requires a source checkout")
class EnsureLLVM21Tests(unittest.TestCase):
    def run_preflight(self, versions, *, broken=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(
                ["git", "init", "--quiet"], cwd=root, check=True
            )
            prefix = root / "llvm"
            bindir = prefix / "bin"
            bindir.mkdir(parents=True)
            for tool, version in zip(TOOLS, versions, strict=True):
                status = 127 if tool in broken else 0
                executable = bindir / tool
                executable.write_text(
                    f"#!/bin/sh\necho '{tool} version {version}'\nexit {status}\n"
                )
                executable.chmod(0o755)
            env = dict(os.environ, LLVM_TOOLS_INSTALL_DIR=str(prefix))
            completed = subprocess.run(
                [SCRIPT], cwd=root, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            env_file = root / ".llvm21-env"
            contents = env_file.read_text() if env_file.exists() else None
            return completed, contents

    def test_accepts_running_llvm_21_prefix_atomically(self):
        completed, contents = self.run_preflight(["21.1.8"] * len(TOOLS))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("LLVM_TOOLS_INSTALL_DIR=", contents)

    def test_rejects_wrong_major(self):
        completed, contents = self.run_preflight(["20.1.0"] * len(TOOLS))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(contents)
        self.assertIn("incompatible LLVM prefix", completed.stderr)

    def test_rejects_mixed_major(self):
        completed, contents = self.run_preflight(
            ["21.1.8", "21.1.8", "20.1.0", "21.1.8"]
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(contents)

    def test_rejects_non_running_tool(self):
        completed, contents = self.run_preflight(
            ["21.1.8"] * len(TOOLS), broken={"llvm-readobj"}
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(contents)
        self.assertIn("--version failed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
