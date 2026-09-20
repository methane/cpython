"""pyperf hook: record the actual worker runtime outside timed regions."""

import faulthandler
import os
import sys
import sysconfig

from pyperf._hooks import HookBase, HookError


class CheckRuntime(HookBase):
    def __init__(self):
        self.enabled_at_start = self.check()
        self.decimal_metadata = self.check_decimal()

    @staticmethod
    def check_decimal():
        if os.environ.get("PYPERF_REQUIRE_C_DECIMAL") != "1":
            return {}
        try:
            import decimal
            import _decimal
        except ImportError as exc:
            raise HookError("C decimal backend required") from exc
        if decimal.Decimal is not _decimal.Decimal:
            raise HookError("decimal is using the Python backend")
        return {"decimal_c_backend": 1,
                "decimal_extension": _decimal.__file__,
                "libmpdec_version": _decimal.__libmpdec_version__}

    @staticmethod
    def check():
        expected_ft = int(os.environ.get("PYPERF_EXPECT_FT", "1"))
        if bool(sysconfig.get_config_var("Py_GIL_DISABLED")) != bool(expected_ft):
            raise HookError("worker has the wrong GIL build configuration")
        if sys._is_gil_enabled() != (not expected_ft):
            raise HookError("worker has the wrong GIL runtime state")
        enabled = sys._jit.is_enabled()
        # The experimental FT JIT deliberately suspends compilation/execution
        # while another thread exists. Opt in only for known threaded workloads;
        # preserve the actual state instead of labelling fallback as enabled.
        suspended_allowed = (expected_ft and
                             os.environ.get("PYPERF_ALLOW_JIT_SUSPENSION") == "1")
        if os.environ.get("PYTHON_JIT") != "1":
            raise HookError("worker did not request the JIT")
        if not enabled and not suspended_allowed:
            raise HookError("worker has disabled the JIT")
        return int(enabled)

    def __enter__(self):
        pass

    def __exit__(self, *exc):
        pass

    def teardown(self, metadata):
        enabled_at_end = self.check()
        if self.check_decimal() != self.decimal_metadata:
            raise HookError("decimal backend changed during the benchmark")
        metadata.update(self.decimal_metadata)
        metadata["ft_build"] = int(bool(sysconfig.get_config_var("Py_GIL_DISABLED")))
        metadata["gil_enabled"] = int(sys._is_gil_enabled())
        metadata["jit_enabled"] = enabled_at_end
        metadata["jit_requested"] = 1
        metadata["jit_enabled_at_start"] = self.enabled_at_start
        metadata["jit_suspension_allowed"] = int(
            os.environ.get("PYPERF_ALLOW_JIT_SUSPENSION") == "1")
        metadata["jit_suspension_observed"] = int(
            not self.enabled_at_start or not enabled_at_end)
        metadata["faulthandler_enabled"] = int(faulthandler.is_enabled())
        metadata["performance_version"] = "1.14.0"
