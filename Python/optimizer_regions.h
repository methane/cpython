/* Bounded, opt-in straight-line lowering before abstract interpretation.
 * All exits retain the entry stack. Only local reads and the explicitly
 * recognized arithmetic/call cleanup may be removed. No stores, calls,
 * periodic checks, or frame transitions may occur inside a region. */

static bool
region_enabled(const char *name)
{
#if (defined(__GNUC__) || defined(__clang__)) && \
    !defined(Py_GIL_DISABLED) && SIZEOF_VOID_P == 8
    const char *value = Py_GETENV(name);
    return value != NULL && strcmp(value, "1") == 0;
#else
    return false;
#endif
}

static int
region_opcode(const _PyUOpInstruction *inst)
{
    int op = inst->opcode;
    if (op >= _LOAD_FAST_0 && op <= _LOAD_FAST_7) {
        return _LOAD_FAST;
    }
    if (op >= _LOAD_FAST_BORROW_0 && op <= _LOAD_FAST_BORROW_7) {
        return _LOAD_FAST_BORROW;
    }
    return op;
}

static int
region_skip(const _PyUOpInstruction *buffer, int pc, int end)
{
    while (pc < end && (buffer[pc].opcode == _NOP ||
                       buffer[pc].opcode == _SET_IP ||
                       buffer[pc].opcode == _CHECK_VALIDITY)) {
        pc++;
    }
    return pc;
}

static int
region_arithmetic(int opcode)
{
    switch (opcode) {
        case _BINARY_OP_ADD_INT: return 0;
        case _BINARY_OP_SUBTRACT_INT: return 1;
        case _BINARY_OP_MULTIPLY_INT: return 2;
        default: return -1;
    }
}

/* Match one specialized operation, including its two guards and cleanup.
 * The caller has not yet established any compact-int facts. */
static int
region_int_operation(const _PyUOpInstruction *buffer, int pc, int end,
                     bool compare, int *operation)
{
    pc = region_skip(buffer, pc, end);
    if (pc + 4 >= end || buffer[pc].opcode != _GUARD_TOS_INT ||
        buffer[pc + 1].opcode != _GUARD_NOS_INT ||
        buffer[pc + 3].opcode != _POP_TOP_INT ||
        buffer[pc + 4].opcode != _POP_TOP_INT) {
        return -1;
    }
    int op = compare ? (buffer[pc + 2].opcode == _COMPARE_OP_INT
                        ? buffer[pc + 2].oparg & 15 : -1)
                     : region_arithmetic(buffer[pc + 2].opcode);
    if (op < 0) {
        return -1;
    }
    *operation = op;
    return pc + 5;
}

static int
region_local(const _PyUOpInstruction *buffer, int pc, int end, int *local)
{
    pc = region_skip(buffer, pc, end);
    if (pc >= end) {
        return -1;
    }
    int op = region_opcode(&buffer[pc]);
    if (op != _LOAD_FAST && op != _LOAD_FAST_BORROW) {
        return -1;
    }
    *local = buffer[pc].oparg;
    return pc + 1;
}

static void
lower_int_regions(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_INT_REGIONS")) {
        return;
    }
    const char *range_mode = Py_GETENV("PYTHON_TIER3_JIT");
    if (range_mode != NULL &&
        (strcmp(range_mode, "1") == 0 || strcmp(range_mode, "2") == 0 ||
         strcmp(range_mode, "3") == 0 || strcmp(range_mode, "native") == 0 ||
         strcmp(range_mode, "resident") == 0)) {
        /* The optional whole-range pass runs after abstract interpretation.
         * Preserve its input when both experiments are requested. */
        for (int i = 0; i < length; i++) {
            if (buffer[i].opcode == _ITER_CHECK_RANGE) {
                return;
            }
        }
    }
    for (int pc = 0; pc < length; pc++) {
        if (buffer[pc].opcode != _GUARD_TOS_INT) {
            continue;
        }
        /* Two arithmetic operations, at most four live-ins, one live-out.
         * Bound scanning too, independently of the overall trace limit. */
        int end = Py_MIN(length, pc + 32);
        int first, second, local, limit, comparison;
        int next = region_int_operation(buffer, pc, end, false, &first);
        if (next < 0 ||
            (next = region_local(buffer, next, end, &local)) < 0 ||
            (next = region_int_operation(buffer, next, end, false, &second)) < 0) {
            continue;
        }
        int opcode = _INT_REGION;
        uint64_t config = local;
        int compare = region_local(buffer, next, end, &limit);
        if (compare >= 0 &&
            (compare = region_int_operation(buffer, compare, end, true,
                                            &comparison)) >= 0) {
            opcode = _INT_REGION_COMPARE;
            config |= (uint64_t)limit << 16 | (uint64_t)comparison << 32;
            next = compare;
        }
        buffer[pc].opcode = opcode;
        buffer[pc].oparg = first + second * 3;
        buffer[pc].operand0 = config;
        for (int i = pc + 1; i < next - 2; i++) {
            buffer[i].opcode = _NOP;
        }
        /* The two original live-in refs are closed after the fused result.
         * Local live-ins are read in place, never pushed or transferred. */
        pc = next - 1;
    }
}

static void
lower_len_regions(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    for (int pc = 0; pc + 2 < length; pc++) {
        if (buffer[pc].opcode != _CALL_LEN ||
            buffer[pc + 1].opcode != _POP_TOP ||
            buffer[pc + 2].opcode != _POP_TOP) {
            continue;
        }
        int end = Py_MIN(length, pc + 20);
        int local, op;
        int next = region_local(buffer, pc + 3, end, &local);
        if (next < 0) {
            continue;
        }
        int stop = region_int_operation(buffer, next, end, true, &op);
        if (stop >= 0) {
            op |= 16;
        }
        else {
            stop = region_int_operation(buffer, next, end, false, &op);
            if (stop < 0 || op == 2) {
                continue;
            }
        }
        buffer[pc].opcode = _CALL_LEN_CONSUMER;
        buffer[pc].oparg = op;
        buffer[pc].operand0 = local;
        for (int i = pc + 1; i < stop - 2; i++) {
            buffer[i].opcode = _NOP;
        }
        /* Preserve the call's original arg/callable cleanup, not the
         * removed integer consumer's operands. */
        buffer[stop - 2].opcode = _POP_TOP;
        buffer[stop - 1].opcode = _POP_TOP;
        pc = stop - 1;
    }
}
