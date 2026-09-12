"""Experimental x86-64 backend for two integer reduction traces.

This is intentionally a sidecar: it consumes a real CPython executor trace and
returns a guarded callable.  Unsupported traces and failed guards execute the
original function, so enabling the experiment never changes Python semantics.
"""

from __future__ import annotations

import builtins
import ctypes
import mmap
import os
import platform
from dataclasses import dataclass
from typing import Callable


_MAX_RANGE = 4_294_967_296
_MAX_SQUARES = 3_024_617


def _range_shape(n):
    total = 0
    for i in range(n):
        total += i
    return total


def _squares_shape(n):
    total = 0
    for i in range(n):
        total += i * i
    return total


_SUM_RANGE_UOPS = (
    "_START_EXECUTOR", "_MAKE_WARM", "_SET_IP", "_CHECK_PERIODIC",
    "_CHECK_VALIDITY", "_ITER_CHECK_RANGE", "_GUARD_NOT_EXHAUSTED_RANGE",
    "_ITER_NEXT_RANGE", "_SET_IP", "_SWAP_FAST_2", "_SPILL_OR_RELOAD",
    "_POP_TOP", "_CHECK_VALIDITY", "_LOAD_FAST_BORROW_1",
    "_LOAD_FAST_BORROW_2", "_GUARD_TOS_OVERFLOWED", "_GUARD_NOS_INT",
    "_BINARY_OP_ADD_INT", "_POP_TOP_NOP", "_POP_TOP_NOP", "_SWAP_FAST_1",
    "_POP_TOP_INT", "_JUMP_TO_TOP", "_DEOPT", "_ERROR_POP_N", "_DEOPT",
    "_EXIT_TRACE", "_EXIT_TRACE", "_ERROR_POP_N", "_DEOPT", "_EXIT_TRACE",
)

_SUM_SQUARES_UOPS = (
    "_START_EXECUTOR", "_MAKE_WARM", "_SET_IP", "_CHECK_PERIODIC",
    "_CHECK_VALIDITY", "_ITER_CHECK_RANGE", "_GUARD_NOT_EXHAUSTED_RANGE",
    "_ITER_NEXT_RANGE", "_SET_IP", "_SWAP_FAST_2", "_SPILL_OR_RELOAD",
    "_POP_TOP", "_CHECK_VALIDITY", "_LOAD_FAST_BORROW_1",
    "_LOAD_FAST_BORROW_2", "_LOAD_FAST_BORROW_2", "_GUARD_TOS_OVERFLOWED",
    "_SPILL_OR_RELOAD", "_BINARY_OP_MULTIPLY_INT", "_POP_TOP_NOP",
    "_POP_TOP_NOP", "_GUARD_NOS_INT", "_BINARY_OP_ADD_INT_INPLACE_RIGHT",
    "_POP_TOP_INT", "_POP_TOP_NOP", "_SWAP_FAST_1", "_POP_TOP_INT",
    "_JUMP_TO_TOP", "_DEOPT", "_ERROR_POP_N", "_DEOPT", "_EXIT_TRACE",
    "_EXIT_TRACE", "_ERROR_POP_N", "_DEOPT", "_EXIT_TRACE", "_EXIT_TRACE",
    "_EXIT_TRACE", "_EXIT_TRACE",
)


@dataclass(frozen=True, slots=True)
class NativeCode:
    name: str
    ir: str
    code: bytes


_SUM_RANGE = NativeCode(
    "sum_range",
    """v0 = arg0
guard_exact_int v0
v1 = unbox_int v0
v2 = const_i64 0
v3 = const_i64 0
loop:
v4 = phi v2, v7
v5 = phi v3, v6
v6 = add_i64 v5, v4
v7 = add_i64 v4, 1
branch_lt v7, v1, loop, exit
exit:
v8 = box_int v6
return v8""",
    bytes.fromhex(
        "48 31 c0 48 31 c9 48 85 ff 7e 0b 48 01 c1 48 ff c0 "
        "48 39 c7 7f f5 48 89 c8 c3"
    ),
)

_SUM_SQUARES = NativeCode(
    "sum_squares",
    """v0 = arg0
guard_exact_int v0
v1 = unbox_int v0
v2 = const_i64 0
v3 = const_i64 0
loop:
v4 = phi v2, v9
v5 = phi v3, v8
v6 = mul_i64 v4, v4
v8 = add_i64 v5, v6
v9 = add_i64 v4, 1
branch_lt v9, v1, loop, exit
exit:
v10 = box_int v8
return v10""",
    bytes.fromhex(
        "48 31 c0 48 31 c9 48 85 ff 7e 12 48 89 c2 48 0f af d0 "
        "48 01 d1 48 ff c0 48 39 c7 7f ee 48 89 c8 c3"
    ),
)


def _trace_names(executor: object) -> tuple[str, ...]:
    return tuple(item[0] for item in executor)  # type: ignore[union-attr]


def select(executor: object) -> NativeCode | None:
    """Select a native loop only after inspecting a current CPython uop trace."""
    names = _trace_names(executor)
    if names == _SUM_SQUARES_UOPS:
        return _SUM_SQUARES
    if names == _SUM_RANGE_UOPS:
        return _SUM_RANGE
    return None


def find_executor(function: Callable[..., object]) -> object | None:
    """Find an executor installed at any bytecode offset of *function*."""
    try:
        import _opcode
    except ImportError:
        return None
    for offset in range(0, len(function.__code__.co_code), 2):
        try:
            return _opcode.get_executor(function.__code__, offset)
        except (ValueError, RuntimeError):
            pass
    return None


class CompiledLoop:
    def __init__(self, original, executor, native):
        self.original = original
        self.executor = executor
        self.native = native
        self._memory = mmap.mmap(
            -1,
            len(native.code),
            prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC,
        )
        self._memory.write(native.code)
        address = ctypes.addressof(ctypes.c_char.from_buffer(self._memory))
        self._entry = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_int64)(address)

    def __call__(self, argument: object) -> int:
        limit = _MAX_RANGE if self.native is _SUM_RANGE else _MAX_SQUARES
        executor_valid = getattr(self.executor, "is_valid", lambda: True)()
        function_builtins = self.original.__builtins__
        if not isinstance(function_builtins, dict):
            function_builtins = vars(function_builtins)
        range_valid = (
            "range" not in self.original.__globals__
            and function_builtins.get("range") is builtins.range
        )
        if (
            type(argument) is not int
            or not -2**63 <= argument <= limit
            or not executor_valid
            or not range_valid
        ):
            return self.original(argument)  # type: ignore[arg-type]
        return self._entry(argument)

    def dump(self, path: str) -> None:
        with open(path, "wb") as output:
            output.write(self.native.code)


def compile(
    function: Callable[[int], int], executor: object | None = None
) -> Callable[[int], int]:
    """Compile a supported hot trace, or return *function* unchanged."""
    if os.environ.get("PYTHON_TIER3_JIT") != "1":
        return function
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        return function
    if executor is None:
        executor = find_executor(function)
    if executor is None:
        return function
    native = select(executor)
    if native is None:
        return function
    reference = _SUM_RANGE if native is _SUM_RANGE else _SUM_SQUARES
    shape = _range_shape if reference is _SUM_RANGE else _squares_shape
    if (
        function.__code__.co_code != shape.__code__.co_code
        or function.__code__.co_consts != shape.__code__.co_consts
        or function.__code__.co_names != shape.__code__.co_names
        or "range" in function.__globals__
    ):
        return function
    return CompiledLoop(function, executor, native)
