import os
import types
import unittest
from unittest.mock import patch

import ft_jit_hook as hook


class RuntimeHookTests(unittest.TestCase):
    def runtime(self, *, ft, enabled, allow=False, requested=True):
        self.enterContext(patch.dict(os.environ, {
            "PYPERF_EXPECT_FT": str(int(ft)),
            "PYTHON_JIT": str(int(requested)),
            "PYPERF_ALLOW_JIT_SUSPENSION": str(int(allow)),
        }))
        self.enterContext(patch.object(hook.sysconfig, "get_config_var", return_value=ft))
        self.enterContext(patch.object(hook.sys, "_is_gil_enabled", return_value=not ft, create=True))
        return self.enterContext(patch.object(hook.sys, "_jit", types.SimpleNamespace(
            is_enabled=lambda: enabled), create=True))

    def test_thread_suspension_is_recorded_as_disabled(self):
        jit = self.runtime(ft=True, enabled=True, allow=True)
        check = hook.CheckRuntime()
        jit.is_enabled = lambda: False
        metadata = {}
        check.teardown(metadata)
        self.assertEqual(metadata["jit_enabled"], 0)
        self.assertEqual(metadata["jit_enabled_at_start"], 1)
        self.assertEqual(metadata["jit_suspension_observed"], 1)

    def test_unexpected_suspension_is_an_error(self):
        self.runtime(ft=True, enabled=False)
        with self.assertRaisesRegex(hook.HookError, "disabled"):
            hook.CheckRuntime()

    def test_gil_build_cannot_opt_out(self):
        self.runtime(ft=False, enabled=False, allow=True)
        with self.assertRaisesRegex(hook.HookError, "disabled"):
            hook.CheckRuntime()

    def test_jit_off_is_not_suspension(self):
        self.runtime(ft=True, enabled=False, allow=True, requested=False)
        with self.assertRaisesRegex(hook.HookError, "request"):
            hook.CheckRuntime()
