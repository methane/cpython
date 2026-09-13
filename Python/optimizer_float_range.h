/* Opt-in short range reductions over a bounded integer polynomial.
 * Coefficients use the integer-valued basis 1, j, j*(j-1)/2.  Each node is
 * lowered to a copy-and-patch uop; there is no runtime expression evaluator.
 * The unchanged trace remains the fallback; a successful chunk takes the
 * original loop-exhaustion exit with the same stack and local values.
 */

#include "optimizer_poly_scalar.h"

static int
float_range_next(_PyUOpInstruction *buffer, int pc, int length)
{
    while (pc < length && (buffer[pc].opcode == _NOP ||
                          buffer[pc].opcode == _SET_IP ||
                          buffer[pc].opcode == _CHECK_VALIDITY)) {
        pc++;
    }
    return pc;
}

static int
float_range_reject(int length, int line)
{
    const char *dump = Py_GETENV("PYTHON_TIER2_FLOAT_RANGE_DUMP");
    if (dump && strcmp(dump, "2") == 0) {
        fprintf(stderr, "float-range reject line=%d\n", line);
    }
    return length;
}

static int
mark_float_range(_PyUOpInstruction *buffer, int length, int available)
{
#if defined(__SIZEOF_INT128__) && SIZEOF_VOID_P == 8 && \
    !defined(Py_GIL_DISABLED) && !defined(WITH_DTRACE) && !defined(__EMSCRIPTEN__)
    const char *setting = Py_GETENV("PYTHON_TIER2_FLOAT_RANGE");
    if (setting == NULL || strcmp(setting, "1") != 0) {
        return length;
    }
    int pc = 0;
    int insertion, target, induction, accumulator;
    _PyUOpInstruction exhausted;
    int args[4], nargs = 0;
    PyObject *function, *numerator;
    _PyUOpInstruction prefix[96];
    int used = 0;
    /* Header effects stay in place, including the periodic check. */
    const int header[] = {_START_EXECUTOR, _MAKE_WARM, _CHECK_PERIODIC,
                         _ITER_CHECK_RANGE, _GUARD_NOT_EXHAUSTED_RANGE};
    for (size_t i = 0; i < Py_ARRAY_LENGTH(header); i++) {
        pc = float_range_next(buffer, pc, length);
        if (pc >= length || buffer[pc].opcode != header[i]) {
            return float_range_reject(length, __LINE__);
        }
        if (header[i] == _GUARD_NOT_EXHAUSTED_RANGE) {
            exhausted = buffer[pc];
        }
        pc++;
    }
    pc = float_range_next(buffer, pc, length);
    if (pc >= length || buffer[pc].opcode != _ITER_NEXT_RANGE) {
        return float_range_reject(length, __LINE__);
    }
    insertion = pc;
    target = buffer[pc++].target;

#define FR_NEXT() (pc = float_range_next(buffer, pc, length), \
                  pc < length ? normalize_tier3_opcode(buffer[pc].opcode) : -1)
#define FR_EXPECT(OP) do { \
    if (FR_NEXT() != (OP)) return float_range_reject(length, __LINE__); \
    pc++; \
} while (0)
#define FR_EMIT(OP, ARG, A, B) do { \
    if (used == (int)Py_ARRAY_LENGTH(prefix)) return float_range_reject(length, __LINE__); \
    prefix[used++] = (_PyUOpInstruction){.opcode = (OP), .oparg = (ARG), \
        .target = target, .operand0 = (uint64_t)(A), .operand1 = (uint64_t)(B)}; \
} while (0)

    if (FR_NEXT() != _SWAP_FAST) {
        return float_range_reject(length, __LINE__);
    }
    induction = buffer[pc++].oparg;
    int op = FR_NEXT();
    if (op != _POP_TOP && op != _POP_TOP_INT && op != _POP_TOP_NOP) {
        return float_range_reject(length, __LINE__);
    }
    pc++;
    if (FR_NEXT() != _LOAD_FAST_BORROW) {
        return float_range_reject(length, __LINE__);
    }
    accumulator = buffer[pc++].oparg;
    if (induction > 255 || accumulator > 255 || induction == accumulator) {
        return float_range_reject(length, __LINE__);
    }
    if (FR_NEXT() == _GUARD_GLOBALS_VERSION) {
        prefix[used++] = buffer[pc++];
        prefix[used - 1].target = target;
    }
    op = FR_NEXT();
    if (op != _LOAD_CONST_INLINE && op != _LOAD_CONST_INLINE_BORROW) {
        return float_range_reject(length, __LINE__);
    }
    function = (PyObject *)buffer[pc++].operand0;
    if (!PyFunction_Check(function)) {
        return float_range_reject(length, __LINE__);
    }
    FR_EXPECT(_PUSH_NULL);
    while (FR_NEXT() == _LOAD_FAST_BORROW) {
        if (nargs == 4 || buffer[pc].oparg > 255 ||
            buffer[pc].oparg == accumulator) {
            return float_range_reject(length, __LINE__);
        }
        args[nargs++] = buffer[pc++].oparg;
    }
    if (FR_NEXT() != _CHECK_FUNCTION_VERSION || buffer[pc].oparg != nargs) {
        return float_range_reject(length, __LINE__);
    }
    FR_EMIT(_CHECK_FUNCTION_VERSION_INLINE, 0, buffer[pc].operand0,
            (uintptr_t)function);
    pc++;
    if (FR_NEXT() != _CHECK_STACK_SPACE_OPERAND) {
        return float_range_reject(length, __LINE__);
    }
    prefix[used++] = buffer[pc++];
    prefix[used - 1].target = target;
    FR_EXPECT(_CHECK_RECURSION_REMAINING);
    FR_EMIT(_CHECK_RECURSION_REMAINING, 0, 0, 0);
    op = FR_NEXT();
    if (op != _INIT_CALL_PY_EXACT_ARGS + nargs + 1 ||
        buffer[pc].oparg != nargs || nargs == 0) {
        return float_range_reject(length, __LINE__);
    }
    pc++;
    FR_EXPECT(_SAVE_RETURN_OFFSET);
    FR_EXPECT(_PUSH_FRAME);
    FR_EXPECT(_TIER2_RESUME_CHECK);
    if (FR_NEXT() != _LOAD_CONST_INLINE_BORROW) {
        return float_range_reject(length, __LINE__);
    }
    numerator = (PyObject *)buffer[pc++].operand0;
    /* The retained function and its version guard keep this code constant
     * alive throughout the chunk; no callback occurs before it is used. */
    if (!PyFloat_CheckExact(numerator)) {
        return float_range_reject(length, __LINE__);
    }
    uint64_t config = accumulator | ((uint64_t)induction << 8) |
                      ((uint64_t)nargs << 48);
    for (int i = 0; i < nargs; i++) {
        config |= (uint64_t)args[i] << (16 + 8*i);
    }
    FR_EMIT(_FLOAT_RANGE_GUARD, 0, config, (uintptr_t)function);

    int degrees[4], depth = 0, operations = 0;
    bool started = false;
    while (true) {
        op = FR_NEXT();
        if (op == _LOAD_FAST_BORROW || op == _INT_REGION_LOCAL) {
            int local = buffer[pc++].oparg;
            if (local >= nargs || depth == 4) {
                return float_range_reject(length, __LINE__);
            }
            bool is_induction = args[local] == induction;
            degrees[depth++] = is_induction ? 1 : 0;
            FR_EMIT(is_induction ? _POLY_INDUCTION : _POLY_LOCAL,
                    args[local], depth - 1, 0);
        }
        else if (op == _INT_REGION_GUARD_FLOAT) {
            if (started || depth != 2) {
                return float_range_reject(length, __LINE__);
            }
            pc++;
        }
        else if (op >= _INT_REGION_START_0 && op <= _INT_REGION_START_4) {
            if (started || depth != 2) {
                return float_range_reject(length, __LINE__);
            }
            started = true;
            pc++;
        }
        else if (op == _INT_REGION_CONST && started && depth < 4) {
            degrees[depth++] = 0;
            FR_EMIT(_POLY_CONST, buffer[pc++].oparg, depth - 1, 0);
        }
        else if (op == _INT_REGION_DUP && started && depth > 0 && depth < 4) {
            degrees[depth] = degrees[depth - 1];
            depth++;
            FR_EMIT(_POLY_DUP, depth - 2, 0, 0);
            pc++;
        }
        else if (started && depth >= 2 &&
                 ((op >= _INT_REGION_BINARY_0 && op <= _INT_REGION_BINARY_3) ||
                  op == _INT_REGION_RSHIFT)) {
            int operation = op == _INT_REGION_RSHIFT ? 3 : buffer[pc].oparg;
            int a = degrees[depth - 2], b = degrees[depth - 1];
            int degree = operation == 2 ? a + b : Py_MAX(a, b);
            /* A division's nonconstant coefficients must divide exactly;
             * the coefficient stencil checks that before any loop effects. */
            if (degree > 2 || (operation == 3 && b != 0) || ++operations > 8) {
                return float_range_reject(length, __LINE__);
            }
            depth--;
            degrees[depth - 1] = degree;
            if (op == _INT_REGION_RSHIFT) {
                /* This constant is consumed only by the shift. Its value is
                 * already embedded in the original integer-region uop. */
                if (prefix[used - 1].opcode == _POLY_CONST &&
                    prefix[used - 1].operand0 == (uint64_t)depth) {
                    used--;
                }
                FR_EMIT(_POLY_RSHIFT, buffer[pc].oparg, depth - 1, 0);
            }
            else {
                FR_EMIT(_POLY_BINARY_0 + operation, operation, depth - 1, 0);
            }
            pc++;
        }
        else {
            break;
        }
    }
    if (!started || depth != 1 || operations < 3) {
        return float_range_reject(length, __LINE__);
    }
    FR_EXPECT(_INT_REGION_DIVIDE);
    FR_EXPECT(_MAKE_HEAP_SAFE);
    FR_EXPECT(_RETURN_VALUE);
    if (FR_NEXT() == _GUARD_NOS_FLOAT) {
        pc++;
    }
    op = FR_NEXT();
    if (op != _BINARY_OP_ADD_FLOAT_INPLACE &&
        op != _BINARY_OP_ADD_FLOAT_INPLACE_RIGHT && op != _BINARY_OP_ADD_FLOAT) {
        return float_range_reject(length, __LINE__);
    }
    pc++;
    for (int i = 0; i < 2; i++) {
        op = FR_NEXT();
        if (op != _POP_TOP_FLOAT && op != _POP_TOP_NOP) {
            return float_range_reject(length, __LINE__);
        }
        pc++;
    }
    if (FR_NEXT() != _SWAP_FAST || buffer[pc++].oparg != accumulator) {
        return float_range_reject(length, __LINE__);
    }
    op = FR_NEXT();
    if (op != _POP_TOP_FLOAT && op != _POP_TOP_NOP) {
        return float_range_reject(length, __LINE__);
    }
    pc++;
    FR_EXPECT(_JUMP_TO_TOP);
    FR_EMIT(_FLOAT_RANGE_REDUCE, (accumulator << 8) | induction,
            (uintptr_t)numerator, 0);
    used = simplify_poly_setup(prefix, used, available);
    if (used + 2 > (int)Py_ARRAY_LENGTH(prefix)) {
        return float_range_reject(length, __LINE__);
    }
    _PyUOpInstruction reduce = prefix[--used];
    int narrow = (int)reduce.operand1;
    FR_EMIT(_FLOAT_RANGE_PREPARE_0 + narrow, narrow, 0, 0);
    reduce.operand1 = 0;
    prefix[used++] = reduce;
    /* A successful chunk consumes the iterator. Use its original exhaustion
     * exit, which resumes after END_FOR with iter/index still on the stack. */
    prefix[used++] = exhausted;
    bool in_setup = false;
    for (int i = 0; i < used - 2; i++) {
        if (prefix[i].opcode == _FLOAT_RANGE_GUARD) {
            in_setup = true;
        }
        else if (in_setup) {
            assert(!(_PyUop_Flags[prefix[i].opcode] &
                     (HAS_EXIT_FLAG | HAS_DEOPT_FLAG | HAS_ERROR_FLAG | HAS_ESCAPES_FLAG)));
        }
    }
    if (length + 2*used >= UOP_MAX_TRACE_LENGTH) {
        return float_range_reject(length, __LINE__);
    }
    if (Py_GETENV("PYTHON_TIER2_FLOAT_RANGE_DUMP")) {
        fprintf(stderr, "float-range degree=%d ops=%d uops=%d acc=%d index=%d\n",
                degrees[0], operations, used, accumulator, induction);
    }
    memmove(buffer + insertion + used, buffer + insertion,
            (length - insertion) * sizeof(*buffer));
    memcpy(buffer + insertion, prefix, used * sizeof(*buffer));
    return length + used;
#undef FR_EMIT
#undef FR_EXPECT
#undef FR_NEXT
#else
    return length;
#endif
}
