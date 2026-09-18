// Macros and other things needed by ceval.c, and bytecodes.c

#include "pycore_enumobject.h"

/* Computed GOTOs, or
       the-optimization-commonly-but-improperly-known-as-"threaded code"
   using gcc's labels-as-values extension
   (http://gcc.gnu.org/onlinedocs/gcc/Labels-as-Values.html).

   The traditional bytecode evaluation loop uses a "switch" statement, which
   decent compilers will optimize as a single indirect branch instruction
   combined with a lookup table of jump addresses. However, since the
   indirect jump instruction is shared by all opcodes, the CPU will have a
   hard time making the right prediction for where to jump next (actually,
   it will be always wrong except in the uncommon case of a sequence of
   several identical opcodes).

   "Threaded code" in contrast, uses an explicit jump table and an explicit
   indirect jump instruction at the end of each opcode. Since the jump
   instruction is at a different address for each opcode, the CPU will make a
   separate prediction for each of these instructions, which is equivalent to
   predicting the second opcode of each opcode pair. These predictions have
   a much better chance to turn out valid, especially in small bytecode loops.

   A mispredicted branch on a modern CPU flushes the whole pipeline and
   can cost several CPU cycles (depending on the pipeline depth),
   and potentially many more instructions (depending on the pipeline width).
   A correctly predicted branch, however, is nearly free.

   At the time of this writing, the "threaded code" version is up to 15-20%
   faster than the normal "switch" version, depending on the compiler and the
   CPU architecture.

   NOTE: care must be taken that the compiler doesn't try to "optimize" the
   indirect jumps by sharing them between all opcodes. Such optimizations
   can be disabled on gcc by using the -fno-gcse flag (or possibly
   -fno-crossjumping).
*/

/* Use macros rather than inline functions, to make it as clear as possible
 * to the C compiler that the tracing check is a simple test then branch.
 * We want to be sure that the compiler knows this before it generates
 * the CFG.
 */

#ifdef WITH_DTRACE
#define OR_DTRACE_LINE | (PyDTrace_LINE_ENABLED() ? 255 : 0)
#else
#define OR_DTRACE_LINE
#endif

#ifdef HAVE_COMPUTED_GOTOS
    #ifndef USE_COMPUTED_GOTOS
    #define USE_COMPUTED_GOTOS 1
    #endif
#else
    #if defined(USE_COMPUTED_GOTOS) && USE_COMPUTED_GOTOS
    #error "Computed gotos are not supported on this compiler."
    #endif
    #undef USE_COMPUTED_GOTOS
    #define USE_COMPUTED_GOTOS 0
#endif

#ifdef Py_STATS
#define INSTRUCTION_STATS(op) \
    do { \
        PyStats *s = _PyStats_GET(); \
        OPCODE_EXE_INC(op); \
        if (s) s->opcode_stats[lastopcode].pair_count[op]++; \
        lastopcode = op; \
    } while (0)
#else
#define INSTRUCTION_STATS(op) ((void)0)
#endif

#ifdef Py_STATS
#   define TAIL_CALL_PARAMS _PyInterpreterFrame *frame, _PyStackRef *stack_pointer, PyThreadState *tstate, _Py_CODEUNIT *next_instr, const void *instruction_funcptr_table, int oparg, int lastopcode
#   define TAIL_CALL_ARGS frame, stack_pointer, tstate, next_instr, instruction_funcptr_table, oparg, lastopcode
#else
#   define TAIL_CALL_PARAMS _PyInterpreterFrame *frame, _PyStackRef *stack_pointer, PyThreadState *tstate, _Py_CODEUNIT *next_instr, const void *instruction_funcptr_table, int oparg
#   define TAIL_CALL_ARGS frame, stack_pointer, tstate, next_instr, instruction_funcptr_table, oparg
#endif

#if _Py_TAIL_CALL_INTERP
#   if defined(__clang__) || defined(__GNUC__)
#       if !_Py__has_attribute(preserve_none) || !_Py__has_attribute(musttail)
#           error "This compiler does not have support for efficient tail calling."
#       endif
#   elif defined(_MSC_VER) && (_MSC_VER < 1950)
#       error "You need at least VS 2026 / PlatformToolset v145 for tail calling."
#   endif
#   if defined(_MSC_VER) && !defined(__clang__)
#      define Py_MUSTTAIL [[msvc::musttail]]
#      define Py_PRESERVE_NONE_CC __preserve_none
#   else
#       define Py_MUSTTAIL __attribute__((musttail))
#       define Py_PRESERVE_NONE_CC __attribute__((preserve_none))
#   endif
    typedef PyObject *(Py_PRESERVE_NONE_CC *py_tail_call_funcptr)(TAIL_CALL_PARAMS);

#   define DISPATCH_TABLE_VAR instruction_funcptr_table
#   define DISPATCH_TABLE instruction_funcptr_handler_table
#   define TRACING_DISPATCH_TABLE instruction_funcptr_tracing_table
#   define TARGET(op) Py_NO_INLINE PyObject *Py_PRESERVE_NONE_CC _TAIL_CALL_##op(TAIL_CALL_PARAMS)

#   define DISPATCH_GOTO() \
        do { \
            Py_MUSTTAIL return (((py_tail_call_funcptr *)instruction_funcptr_table)[opcode])(TAIL_CALL_ARGS); \
        } while (0)
#   define DISPATCH_GOTO_NON_TRACING() \
        do { \
            Py_MUSTTAIL return (((py_tail_call_funcptr *)DISPATCH_TABLE)[opcode])(TAIL_CALL_ARGS); \
        } while (0)
#   define JUMP_TO_LABEL(name) \
        do { \
            Py_MUSTTAIL return (_TAIL_CALL_##name)(TAIL_CALL_ARGS); \
        } while (0)
#   ifdef Py_STATS
#       define JUMP_TO_PREDICTED(name) \
            do { \
                Py_MUSTTAIL return (_TAIL_CALL_##name)(frame, stack_pointer, tstate, this_instr, instruction_funcptr_table, oparg, lastopcode); \
            } while (0)
#   else
#       define JUMP_TO_PREDICTED(name) \
            do { \
                Py_MUSTTAIL return (_TAIL_CALL_##name)(frame, stack_pointer, tstate, this_instr, instruction_funcptr_table, oparg); \
            } while (0)
#   endif
#    define LABEL(name) TARGET(name)
#elif USE_COMPUTED_GOTOS
#  define DISPATCH_TABLE_VAR opcode_targets
#  define DISPATCH_TABLE opcode_targets_table
#  define TRACING_DISPATCH_TABLE opcode_tracing_targets_table
#  define TARGET(op) TARGET_##op:
#  define DISPATCH_GOTO() goto *opcode_targets[opcode]
#  define DISPATCH_GOTO_NON_TRACING() goto *DISPATCH_TABLE[opcode];
#  define JUMP_TO_LABEL(name) goto name;
#  define JUMP_TO_PREDICTED(name) goto PREDICTED_##name;
#  define LABEL(name) name:
#else
#  define TARGET(op) case op: TARGET_##op:
#  define DISPATCH_GOTO() dispatch_code = opcode | tracing_mode ; goto dispatch_opcode
#  define DISPATCH_GOTO_NON_TRACING() dispatch_code = opcode; goto dispatch_opcode
#  define JUMP_TO_LABEL(name) goto name;
#  define JUMP_TO_PREDICTED(name) goto PREDICTED_##name;
#  define LABEL(name) name:
#endif

#if (_Py_TAIL_CALL_INTERP || USE_COMPUTED_GOTOS) && _Py_TIER2
#  define IS_JIT_TRACING() (DISPATCH_TABLE_VAR == TRACING_DISPATCH_TABLE)
#  define ENTER_TRACING() \
    DISPATCH_TABLE_VAR = TRACING_DISPATCH_TABLE;
#  define LEAVE_TRACING() \
    DISPATCH_TABLE_VAR = DISPATCH_TABLE;
#else
#  define IS_JIT_TRACING() (tracing_mode != 0)
#  define ENTER_TRACING() tracing_mode = 255
#  define LEAVE_TRACING() tracing_mode = 0
#endif

#if _Py_TIER2
#define STOP_TRACING() \
    do { \
        if (IS_JIT_TRACING()) { \
            LEAVE_TRACING(); \
            _PyJit_FinalizeTracing(tstate, 0); \
        } \
    } while (0);
#else
#define STOP_TRACING() ((void)(0));
#endif

/* PRE_DISPATCH_GOTO() does lltrace if enabled. Normally a no-op */
#ifdef Py_DEBUG
#define PRE_DISPATCH_GOTO() if (frame->lltrace >= 5) { \
    lltrace_instruction(frame, stack_pointer, next_instr, opcode, oparg); }
#else
#define PRE_DISPATCH_GOTO() ((void)0)
#endif

#ifdef Py_DEBUG
#define LLTRACE_RESUME_FRAME() \
do { \
    _PyFrame_SetStackPointer(frame, stack_pointer); \
    int lltrace = maybe_lltrace_resume_frame(frame, GLOBALS()); \
    stack_pointer = _PyFrame_GetStackPointer(frame); \
    frame->lltrace = lltrace; \
} while (0)
#else
#define LLTRACE_RESUME_FRAME() ((void)0)
#endif

#ifdef Py_GIL_DISABLED
#define QSBR_QUIESCENT_STATE(tstate) _Py_qsbr_quiescent_state(((_PyThreadStateImpl *)tstate)->qsbr)
#else
#define QSBR_QUIESCENT_STATE(tstate)
#endif


/* Do interpreter dispatch accounting for tracing and instrumentation */
#define DISPATCH() \
    { \
        _PyFrame_StackAssertInvalid(frame); \
        NEXTOPARG(); \
        PRE_DISPATCH_GOTO(); \
        DISPATCH_GOTO(); \
    }

#define DISPATCH_NON_TRACING() \
    { \
        _PyFrame_StackAssertInvalid(frame); \
        NEXTOPARG(); \
        PRE_DISPATCH_GOTO(); \
        DISPATCH_GOTO_NON_TRACING(); \
    }

#define DISPATCH_SAME_OPARG() \
    { \
        opcode = next_instr->op.code; \
        PRE_DISPATCH_GOTO(); \
        DISPATCH_GOTO_NON_TRACING(); \
    }

#define DISPATCH_INLINED(NEW_FRAME)                              \
    do {                                                         \
        assert(!IS_PEP523_HOOKED(tstate));                       \
        _PyFrame_SetStackPointer(frame, stack_pointer);          \
        _PyFrame_StackPointerValidate(frame);                    \
        assert((NEW_FRAME)->previous == frame);                  \
        frame = tstate->current_frame = (NEW_FRAME);             \
        CALL_STAT_INC(inlined_py_calls);                         \
        JUMP_TO_LABEL(start_frame);                              \
    } while (0)

/* Tuple access macros */

#ifndef Py_DEBUG
#define GETITEM(v, i) PyTuple_GET_ITEM((v), (i))
#else
static inline PyObject *
GETITEM(PyObject *v, Py_ssize_t i) {
    assert(PyTuple_Check(v));
    assert(i >= 0);
    assert(i < PyTuple_GET_SIZE(v));
    return PyTuple_GET_ITEM(v, i);
}
#endif

/* Code access macros */

/* The integer overflow is checked by an assertion below. */
#define INSTR_OFFSET() ((int)(next_instr - _PyFrame_GetBytecode(frame)))
#define NEXTOPARG()  do { \
        _Py_CODEUNIT word  = {.cache = FT_ATOMIC_LOAD_UINT16_RELAXED(*(uint16_t*)next_instr)}; \
        opcode = word.op.code; \
        oparg = word.op.arg; \
    } while (0)

/* JUMPBY makes the generator identify the instruction as a jump. SKIP_OVER is
 * for advancing to the next instruction, taking into account cache entries
 * and skipped instructions.
 */
#define JUMPBY(x)       (next_instr += (x))
#define SKIP_OVER(x)    (next_instr += (x))

#define STACK_LEVEL()     ((int)(stack_pointer - _PyFrame_Stackbase(frame)))
#define STACK_SIZE()      (_PyFrame_GetCode(frame)->co_stacksize)

#define WITHIN_STACK_BOUNDS() \
   (frame->owner == FRAME_OWNED_BY_INTERPRETER || (STACK_LEVEL() >= 0 && STACK_LEVEL() <= STACK_SIZE()))

#if defined(Py_DEBUG) && !defined(_Py_JIT)
// This allows temporary stack "overflows", provided it's all in the cache at any point of time.
#define ASSERT_WITHIN_STACK_BOUNDS_IGNORING_CACHE(F, L) \
   assert(frame->owner == FRAME_OWNED_BY_INTERPRETER || (STACK_LEVEL() >= 0 && (STACK_LEVEL()) <= STACK_SIZE()))
#else
#define ASSERT_WITHIN_STACK_BOUNDS_IGNORING_CACHE ASSERT_WITHIN_STACK_BOUNDS
#endif

/* Data access macros */
#define FRAME_CO_CONSTS (_PyFrame_GetCode(frame)->co_consts)
#define FRAME_CO_NAMES  (_PyFrame_GetCode(frame)->co_names)

/* Local variable macros */

#define LOCALS_ARRAY    (frame->localsplus)
#define GETLOCAL(i)     (frame->localsplus[i])


#ifdef Py_STATS
#define UPDATE_MISS_STATS(INSTNAME)                              \
    do {                                                         \
        STAT_INC(opcode, miss);                                  \
        STAT_INC((INSTNAME), miss);                              \
        /* The counter is always the first cache entry: */       \
        if (ADAPTIVE_COUNTER_TRIGGERS(next_instr->cache)) {      \
            STAT_INC((INSTNAME), deopt);                         \
        }                                                        \
    } while (0)
#else
#define UPDATE_MISS_STATS(INSTNAME) ((void)0)
#endif


// Try to lock an object in the free threading build, if it's not already
// locked. Use with a DEOPT_IF() to deopt if the object is already locked.
// These are no-ops in the default GIL build. The general pattern is:
//
// DEOPT_IF(!LOCK_OBJECT(op));
// if (/* condition fails */) {
//     UNLOCK_OBJECT(op);
//     DEOPT_IF(true);
//  }
//  ...
//  UNLOCK_OBJECT(op);
//
// NOTE: The object must be unlocked on every exit code path and you should
// avoid any potentially escaping calls (like PyStackRef_CLOSE) while the
// object is locked.
#ifdef Py_GIL_DISABLED
#  define LOCK_OBJECT(op) PyMutex_LockFast(&(_PyObject_CAST(op))->ob_mutex)
#  define UNLOCK_OBJECT(op) PyMutex_Unlock(&(_PyObject_CAST(op))->ob_mutex)
#else
#  define LOCK_OBJECT(op) (1)
#  define UNLOCK_OBJECT(op) ((void)0)
#endif

#define GLOBALS() frame->f_globals
#define BUILTINS() frame->f_builtins
#define LOCALS() frame->f_locals
#define CONSTS() _PyFrame_GetCode(frame)->co_consts
#define NAMES() _PyFrame_GetCode(frame)->co_names

#if defined(WITH_DTRACE) && !defined(Py_BUILD_CORE_MODULE)
static void dtrace_function_entry(_PyInterpreterFrame *);
static void dtrace_function_return(_PyInterpreterFrame *);

#define DTRACE_FUNCTION_ENTRY()  \
    if (PyDTrace_FUNCTION_ENTRY_ENABLED()) { \
        dtrace_function_entry(frame); \
    }

#define DTRACE_FUNCTION_RETURN() \
    if (PyDTrace_FUNCTION_RETURN_ENABLED()) { \
        dtrace_function_return(frame); \
    }
#else
#define DTRACE_FUNCTION_ENTRY() ((void)0)
#define DTRACE_FUNCTION_RETURN() ((void)0)
#endif

/* This takes a uint16_t instead of a _Py_BackoffCounter,
 * because it is used directly on the cache entry in generated code,
 * which is always an integral type. */
// Force re-specialization when tracing a side exit to get good side exits.
#define ADAPTIVE_COUNTER_TRIGGERS(COUNTER) \
    backoff_counter_triggers(forge_backoff_counter((COUNTER)))

#ifdef Py_GIL_DISABLED
/* Counters are unreachable when thread-local bytecode is disabled,
 * so there is no need to update them. */
#define ADVANCE_ADAPTIVE_COUNTER(COUNTER) \
    do { \
        _Py_BackoffCounter cnt = (COUNTER); \
        if (!backoff_counter_is_unreachable(cnt)) { \
            (COUNTER) = advance_backoff_counter(cnt); \
        } \
    } while (0);

#define PAUSE_ADAPTIVE_COUNTER(COUNTER) \
    do { \
        _Py_BackoffCounter cnt = (COUNTER); \
        if (!backoff_counter_is_unreachable(cnt)) { \
            (COUNTER) = pause_backoff_counter(cnt); \
        } \
    } while (0);
#else
#define ADVANCE_ADAPTIVE_COUNTER(COUNTER) \
    do { \
        (COUNTER) = advance_backoff_counter((COUNTER)); \
    } while (0);

#define PAUSE_ADAPTIVE_COUNTER(COUNTER) \
    do { \
        (COUNTER) = pause_backoff_counter((COUNTER)); \
    } while (0);
#endif

#ifdef ENABLE_SPECIALIZATION
/* Multiple threads may execute these concurrently if thread-local bytecode is
 * disabled and they all execute the main copy of the bytecode. Specialization
 * is disabled in that case so the value is unused, but the RMW cycle should be
 * free of data races.
 */
#define RECORD_BRANCH_TAKEN(bitset, flag) \
    FT_ATOMIC_STORE_UINT16_RELAXED(       \
        bitset, (FT_ATOMIC_LOAD_UINT16_RELAXED(bitset) << 1) | (flag))
#else
#define RECORD_BRANCH_TAKEN(bitset, flag)
#endif

#define UNBOUNDLOCAL_ERROR_MSG \
    "cannot access local variable '%s' where it is not associated with a value"
#define UNBOUNDFREE_ERROR_MSG \
    "cannot access free variable '%s' where it is not associated with a value" \
    " in enclosing scope"
#define NAME_ERROR_MSG "name '%.200s' is not defined"

// If a trace function sets a new f_lineno and
// *then* raises, we use the destination when searching
// for an exception handler, displaying the traceback, and so on
#define INSTRUMENTED_JUMP(src, dest, event) \
do { \
    _Py_CODEUNIT *_dest = (dest); \
    if (tstate->tracing) {\
        next_instr = _dest; \
    } else { \
        _PyFrame_SetStackPointer(frame, stack_pointer); \
        next_instr = _Py_call_instrumentation_jump(this_instr, tstate, event, frame, src, _dest); \
        stack_pointer = _PyFrame_GetStackPointer(frame); \
        if (next_instr == NULL) { \
            next_instr = _dest + 1; \
            JUMP_TO_LABEL(error); \
        } \
    } \
} while (0);


static inline int _Py_EnterRecursivePy(PyThreadState *tstate) {
    return (tstate->py_recursion_remaining-- <= 0) &&
        _Py_CheckRecursiveCallPy(tstate);
}

static inline void _Py_LeaveRecursiveCallPy(PyThreadState *tstate)  {
    tstate->py_recursion_remaining++;
}

/* Implementation of "macros" that modify the instruction pointer,
 * stack pointer, or frame pointer.
 * These need to treated differently by tier 1 and 2.
 * The Tier 1 version is here; Tier 2 is inlined in ceval.c. */

#define LOAD_IP(OFFSET) do { \
        next_instr = frame->instr_ptr + (OFFSET); \
    } while (0)

/* There's no STORE_IP(), it's inlined by the code generator. */

#define LOAD_SP() \
stack_pointer = _PyFrame_GetStackPointer(frame)

#define SAVE_SP() \
_PyFrame_SetStackPointer(frame, stack_pointer)

/* Tier-switching macros. */

#define TIER1_TO_TIER2(EXECUTOR)                        \
do {                                                   \
    OPT_STAT_INC(traces_executed);                     \
    next_instr = _Py_jit_entry((EXECUTOR), frame, stack_pointer, tstate); \
    frame = tstate->current_frame;                     \
    stack_pointer = _PyFrame_GetStackPointer(frame);   \
    int keep_tracing_bit = (uintptr_t)next_instr & 1;   \
    next_instr = (_Py_CODEUNIT *)(((uintptr_t)next_instr) & (~1)); \
    if (next_instr == NULL) {                          \
        /* gh-140104: The exception handler expects frame->instr_ptr
            to after this_instr, not this_instr! */ \
        next_instr = frame->instr_ptr + 1;                 \
        JUMP_TO_LABEL(error);                          \
    }                                                  \
    if (keep_tracing_bit) { \
        assert(uop_buffer_length(&((_PyThreadStateImpl *)tstate)->jit_tracer_state->code_buffer)); \
        ENTER_TRACING(); \
        DISPATCH_NON_TRACING(); \
    } \
    DISPATCH();                                        \
} while (0)

#define TIER2_TO_TIER2(EXECUTOR) \
do {                                                   \
    OPT_STAT_INC(traces_executed);                     \
    current_executor = (EXECUTOR);                     \
    goto tier2_start;                                  \
} while (0)

#define GOTO_TIER_ONE_SETUP \
    tstate->current_executor = NULL;                              \
    OPT_HIST(trace_uop_execution_counter, trace_run_length_hist); \
    _PyFrame_SetStackPointer(frame, stack_pointer);

#define GOTO_TIER_ONE(TARGET) \
    do \
    { \
        GOTO_TIER_ONE_SETUP \
        return (_Py_CODEUNIT *)(TARGET); \
    } while (0)

#define GOTO_TIER_ONE_CONTINUE_TRACING(TARGET) \
    do \
    { \
        GOTO_TIER_ONE_SETUP \
        return (_Py_CODEUNIT *)(((uintptr_t)(TARGET))| 1); \
    } while (0)

#define CURRENT_OPARG()    (next_uop[-1].oparg)
#define CURRENT_OPERAND0_64() (next_uop[-1].operand0)
#define CURRENT_OPERAND1_64() (next_uop[-1].operand1)
#define CURRENT_OPERAND0_32() (next_uop[-1].operand0)
#define CURRENT_OPERAND1_32() (next_uop[-1].operand1)
#define CURRENT_OPERAND0_16() (next_uop[-1].operand0)
#define CURRENT_OPERAND1_16() (next_uop[-1].operand1)
#define OPERAND0_FIELD(VALUE, SHIFT, WIDTH) \
    (((uint64_t)(uintptr_t)(VALUE) >> (SHIFT)) & (UINT64_MAX >> (64 - (WIDTH))))
#define OPERAND1_FIELD(VALUE, SHIFT, WIDTH) OPERAND0_FIELD(VALUE, SHIFT, WIDTH)
#define CURRENT_TARGET()   (next_uop[-1].target)

#define JUMP_TO_JUMP_TARGET() goto jump_to_jump_target
#define JUMP_TO_ERROR() goto jump_to_error_target

/* Stackref macros */

/* How much scratch space to give stackref to PyObject* conversion. */
#define MAX_STACKREF_SCRATCH 10

#define STACKREFS_TO_PYOBJECTS(ARGS, ARG_COUNT, NAME) \
    /* +1 because vectorcall might use -1 to write self */ \
    PyObject *NAME##_temp[MAX_STACKREF_SCRATCH+1]; \
    PyObject **NAME = _PyObjectArray_FromStackRefArray(ARGS, ARG_COUNT, NAME##_temp);

#define STACKREFS_TO_PYOBJECTS_CLEANUP(NAME) \
    /* +1 because we +1 previously */ \
    _PyObjectArray_Free(NAME - 1, NAME##_temp);

#define CONVERSION_FAILED(NAME) ((NAME) == NULL)

#if defined(Py_DEBUG) && !defined(_Py_JIT)
#define SET_CURRENT_CACHED_VALUES(N) current_cached_values = (N)
#define CHECK_CURRENT_CACHED_VALUES(N) assert(current_cached_values == (N))
#else
#define SET_CURRENT_CACHED_VALUES(N) ((void)0)
#define CHECK_CURRENT_CACHED_VALUES(N) ((void)0)
#endif

#define IS_PEP523_HOOKED(tstate) (tstate->interp->eval_frame != NULL)

static inline int
check_periodics(PyThreadState *tstate) {
    _Py_CHECK_EMSCRIPTEN_SIGNALS_PERIODICALLY();
    QSBR_QUIESCENT_STATE(tstate);
    if (_Py_atomic_load_uintptr_relaxed(&tstate->eval_breaker) & _PY_EVAL_EVENTS_MASK) {
        return _Py_HandlePending(tstate);
    }
    return 0;
}

static inline int
check_periodics_at_end(PyThreadState *tstate, _PyInterpreterFrame *frame) {
    _Py_CHECK_EMSCRIPTEN_SIGNALS_PERIODICALLY();
    QSBR_QUIESCENT_STATE(tstate);
    if (_Py_atomic_load_uintptr_relaxed(&tstate->eval_breaker) & _PY_EVAL_EVENTS_MASK) {
        // Do not handle pending interrupts if the previous instruction was LOAD_SPECIAL
        // This may also not handle interrupts if a cache looks like LOAD_SPECIAL,
        // but this is benign as we won't skip periodic checks indefinitely.
        if (frame->instr_ptr[-1].op.code == LOAD_SPECIAL) {
            return 0;
        }
        return _Py_HandlePending(tstate);
    }
    return 0;
}

// Mark the generator as executing. Returns true if the state was changed,
// false if it was already executing or finished.
static inline bool
gen_try_set_executing(PyGenObject *gen)
{
#ifdef Py_GIL_DISABLED
    if (!_PyObject_IsUniquelyReferenced((PyObject *)gen)) {
        int8_t frame_state = _Py_atomic_load_int8_relaxed(&gen->gi_frame_state);
        while (frame_state < FRAME_SUSPENDED_YIELD_FROM_LOCKED) {
            if (_Py_atomic_compare_exchange_int8(&gen->gi_frame_state,
                                                 &frame_state,
                                                 FRAME_EXECUTING)) {
                return true;
            }
        }
        // NB: We return false for FRAME_SUSPENDED_YIELD_FROM_LOCKED as well.
        // That case is rare enough that we can just handle it in the deopt.
        return false;
    }
#endif
    // Use faster non-atomic modifications in the GIL-enabled build and when
    // the object is uniquely referenced in the free-threaded build.
    if (gen->gi_frame_state < FRAME_EXECUTING) {
        assert(gen->gi_frame_state != FRAME_SUSPENDED_YIELD_FROM_LOCKED);
        gen->gi_frame_state = FRAME_EXECUTING;
        return true;
    }
    return false;
}

// Macro for inplace float binary ops (tier 2 only).
// Mutates the uniquely-referenced TARGET operand in place.
// TARGET must be either left or right.
#define FLOAT_INPLACE_OP(left, right, TARGET, OP)                        \
    do {                                                                 \
        PyObject *left_o = PyStackRef_AsPyObjectBorrow(left);            \
        PyObject *right_o = PyStackRef_AsPyObjectBorrow(right);          \
        assert(PyFloat_CheckExact(left_o));                              \
        assert(PyFloat_CheckExact(right_o));                             \
        assert(_PyObject_IsUniquelyReferenced(                           \
            PyStackRef_AsPyObjectBorrow(TARGET)));                       \
        STAT_INC(BINARY_OP, hit);                                        \
        double _dres =                                                   \
            ((PyFloatObject *)left_o)->ob_fval                           \
            OP ((PyFloatObject *)right_o)->ob_fval;                      \
        ((PyFloatObject *)PyStackRef_AsPyObjectBorrow(TARGET))           \
            ->ob_fval = _dres;                                           \
    } while (0)

// Inplace float true division. Sets _divop_err to 1 on zero division.
// Caller must check _divop_err and call ERROR_NO_POP() if set.
#define FLOAT_INPLACE_DIVOP(left, right, TARGET)                         \
    int _divop_err = 0;                                                  \
    do {                                                                 \
        PyObject *left_o = PyStackRef_AsPyObjectBorrow(left);            \
        PyObject *right_o = PyStackRef_AsPyObjectBorrow(right);          \
        assert(PyFloat_CheckExact(left_o));                              \
        assert(PyFloat_CheckExact(right_o));                             \
        assert(_PyObject_IsUniquelyReferenced(                           \
            PyStackRef_AsPyObjectBorrow(TARGET)));                       \
        STAT_INC(BINARY_OP, hit);                                        \
        double _divisor = ((PyFloatObject *)right_o)->ob_fval;           \
        if (_divisor == 0.0) {                                           \
            PyErr_SetString(PyExc_ZeroDivisionError,                     \
                            "float division by zero");                   \
            _divop_err = 1;                                              \
            break;                                                       \
        }                                                                \
        double _dres = ((PyFloatObject *)left_o)->ob_fval / _divisor;    \
        ((PyFloatObject *)PyStackRef_AsPyObjectBorrow(TARGET))           \
            ->ob_fval = _dres;                                           \
    } while (0)

// Inplace compact int operation. TARGET is expected to be uniquely
// referenced at the optimizer level, but at runtime it may be a
// cached small int singleton. We check _Py_IsImmortal on TARGET
// to decide whether inplace mutation is safe.
//
// After the macro, _int_inplace_res holds the result (may be NULL
// on allocation failure). On success, TARGET was mutated in place
// and _int_inplace_res is a DUP'd reference to it. On fallback
// (small int target, small int result, or overflow), _int_inplace_res
// is from FUNC (_PyCompactLong_Add etc.).
// FUNC is the fallback function (_PyCompactLong_Add etc.)
#define INT_INPLACE_OP(left, right, TARGET, OP, FUNC)                    \
    _PyStackRef _int_inplace_res = PyStackRef_NULL;                      \
    do {                                                                 \
        PyObject *target_o = PyStackRef_AsPyObjectBorrow(TARGET);        \
        if (_Py_IsImmortal(target_o)) {                                  \
            break;                                                       \
        }                                                                \
        assert(_PyObject_IsUniquelyReferenced(target_o));                \
        Py_ssize_t left_val = _PyLong_CompactValue(                      \
            (PyLongObject *)PyStackRef_AsPyObjectBorrow(left));          \
        Py_ssize_t right_val = _PyLong_CompactValue(                     \
            (PyLongObject *)PyStackRef_AsPyObjectBorrow(right));         \
        Py_ssize_t result = left_val OP right_val;                       \
        if (!_PY_IS_SMALL_INT(result)                                    \
            && ((twodigits)((stwodigits)result) + PyLong_MASK            \
                < (twodigits)PyLong_MASK + PyLong_BASE))                 \
        {                                                                \
            _PyLong_SetSignAndDigitCount(                                \
                (PyLongObject *)target_o, result < 0 ? -1 : 1, 1);       \
            ((PyLongObject *)target_o)->long_value.ob_digit[0] =         \
                (digit)(result < 0 ? -result : result);                  \
            _int_inplace_res = PyStackRef_DUP(TARGET);                   \
            break;                                                       \
        }                                                                \
    } while (0);                                                         \
    if (PyStackRef_IsNull(_int_inplace_res)) {                           \
        _int_inplace_res = FUNC(                                         \
            (PyLongObject *)PyStackRef_AsPyObjectBorrow(left),           \
            (PyLongObject *)PyStackRef_AsPyObjectBorrow(right));         \
    }

#define CALL_TP_ITERITEM_NO_ESCAPE(ITER, INDEX) \
    Py_TYPE(ITER)->_tp_iteritem((ITER), (INDEX))

#if defined(_Py_TIER2) || defined(_Py_JIT)

static inline void
_PyJit_UnreachableDealloc(PyObject *op)
{
    Py_FatalError("JIT released the last reference to a shared object");
}

/* Declining this fast path leaves every input owned by the caller and does
 * not set an exception. Successful frame setup cannot call Python or GC. */
static inline _PyInterpreterFrame *
_PyJit_PushSimpleFrame(PyThreadState *tstate, _PyStackRef callable,
                       const _PyStackRef *args, int nargs,
                       _PyInterpreterFrame *previous)
{
#ifdef Py_GIL_DISABLED
    return NULL;
#else
    PyFunctionObject *function = (PyFunctionObject *)PyStackRef_AsPyObjectBorrow(callable);
    PyCodeObject *code = (PyCodeObject *)function->func_code;
    if (!(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS)) ||
        code->co_kwonlyargcount != 0 || nargs > code->co_argcount ||
        !_PyThreadState_HasStackSpace(tstate, code->co_framesize))
    {
        return NULL;
    }
    PyObject *defaults = function->func_defaults;
    int missing = code->co_argcount - nargs;
    Py_ssize_t ndefaults = defaults == NULL ? 0 : PyTuple_GET_SIZE(defaults);
    if (missing > ndefaults) {
        return NULL;
    }
    _PyInterpreterFrame *result = _PyFrame_PushUnchecked(
        tstate, callable, code->co_argcount, previous);
    for (int i = 0; i < nargs; i++) {
        result->localsplus[i] = args[i];
    }
    for (int i = 0; i < missing; i++) {
        result->localsplus[nargs + i] = PyStackRef_FromPyObjectNew(
            PyTuple_GET_ITEM(defaults, ndefaults - missing + i));
    }
    return result;
#endif
}

static inline bool
_PyJit_CanBindInitExactly(PyThreadState *tstate, PyCodeObject *code, int nargs)
{
#ifdef Py_GIL_DISABLED
    return false;
#else
    /* Allocation can run GC callbacks that replace the initializer's code,
     * so recheck its frame size after allocating the instance and shim. */
    return code->co_argcount == nargs && code->co_kwonlyargcount == 0 &&
           !(code->co_flags & (CO_VARARGS | CO_VARKEYWORDS)) &&
           _PyThreadState_HasStackSpace(tstate, code->co_framesize);
#endif
}

static inline Py_ALWAYS_INLINE void
_PyJit_FrameClearAndPop(PyThreadState *tstate, _PyInterpreterFrame *dying)
{
#ifndef Py_GIL_DISABLED
    PyObject **base = (PyObject **)dying;
    if (dying->owner == FRAME_OWNED_BY_THREAD &&
        dying->frame_obj == NULL && dying->f_locals == NULL &&
        base != &tstate->datastack_chunk->data[0])
    {
        /* Match the ordinary clear order, with the frame already unlinked.
         * Destructors may re-enter Python while this frame's stack storage
         * remains reserved. Release that storage only after all references. */
        assert(tstate->current_frame != dying);
        assert(base + _PyFrame_GetCode(dying)->co_framesize ==
               tstate->datastack_top);
        _PyThreadState_UpdateLastProfiledFrame(tstate, dying, tstate->current_frame);
        _PyStackRef *sp = dying->stackpointer;
        _PyStackRef *locals = dying->localsplus;
        assert(sp != NULL);
        dying->stackpointer = locals;
        while (sp > locals) {
            sp--;
            PyStackRef_XCLOSE(*sp);
        }
        PyStackRef_CLEAR(dying->f_funcobj);
        PyStackRef_CLEAR(dying->f_executable);
        tstate->datastack_top = base;
        return;
    }
#endif
    _PyEval_FrameClearAndPop(tstate, dying);
}

/* Return -1 without setting an exception when ordinary containment is needed.
 * A skipped prefix contains only exact compact integers, so restarting the
 * generic search cannot duplicate a comparison callback. */
static inline int
_PyRegion_SequenceContainsInt(PyObject *sequence, PyObject *key)
{
#ifdef Py_GIL_DISABLED
    return -1;
#else
    if (!PyLong_CheckExact(key) || !_PyLong_IsCompact((PyLongObject *)key)) {
        return -1;
    }
    PyObject **items;
    Py_ssize_t size;
    if (PyList_CheckExact(sequence)) {
        items = ((PyListObject *)sequence)->ob_item;
        size = PyList_GET_SIZE(sequence);
    }
    else if (PyTuple_CheckExact(sequence)) {
        items = ((PyTupleObject *)sequence)->ob_item;
        size = PyTuple_GET_SIZE(sequence);
    }
    else {
        return -1;
    }
    Py_ssize_t integer = _PyLong_CompactValue((PyLongObject *)key);
    for (Py_ssize_t i = 0; i < size; i++) {
        PyObject *item = items[i];
        if (item == key) {
            return 1;
        }
        if (!PyLong_CheckExact(item) || !_PyLong_IsCompact((PyLongObject *)item)) {
            return -1;
        }
        if (_PyLong_CompactValue((PyLongObject *)item) == integer) {
            return 1;
        }
    }
    return 0;
#endif
}

static inline bool
_PyRegion_IntInput(_PyInterpreterFrame *frame, unsigned int kind,
                   uint8_t local, uint16_t offset, uint32_t version,
                   bool managed, int32_t constant, Py_ssize_t *integer)
{
    if (kind == 2) {
        *integer = constant;
        return true;
    }
    _PyStackRef ref = frame->localsplus[local];
    if (PyStackRef_IsNull(ref)) {
        return false;
    }
    PyObject *value = PyStackRef_AsPyObjectBorrow(ref);
    if (kind == 0) {
        if (Py_TYPE(value)->tp_version_tag != version ||
            (managed && !_PyObject_InlineValues(value)->valid))
        {
            return false;
        }
        value = *(PyObject **)((char *)value + offset);
    }
    if (value == NULL || !PyLong_CheckExact(value) ||
        !_PyLong_IsCompact((PyLongObject *)value))
    {
        return false;
    }
    *integer = _PyLong_CompactValue((PyLongObject *)value);
    return true;
}

/* Common list slices have exact compact integer bounds or None. Avoid the
 * generic __index__ conversion and step handling, retaining the ordinary
 * path for callbacks, wide integers, and free-threaded list locking. */
static inline PyObject *
_PyJit_ListBinarySlice(PyObject *container, PyObject *start, PyObject *stop)
{
#ifndef Py_GIL_DISABLED
    if ((start == Py_None || (PyLong_CheckExact(start) &&
                             _PyLong_IsCompact((PyLongObject *)start))) &&
        (stop == Py_None || (PyLong_CheckExact(stop) &&
                            _PyLong_IsCompact((PyLongObject *)stop))))
    {
        Py_ssize_t low = start == Py_None ? 0 :
            _PyLong_CompactValue((PyLongObject *)start);
        Py_ssize_t high = stop == Py_None ? PY_SSIZE_T_MAX :
            _PyLong_CompactValue((PyLongObject *)stop);
        Py_ssize_t length = PyList_GET_SIZE(container);
        if (low < 0) {
            low += length;
        }
        if (high < 0) {
            high += length;
        }
        // GetSlice clips both bounds to the valid range. Adding a negative
        // compact integer to the nonnegative length cannot overflow.
        return PyList_GetSlice(container, low, high);
    }
#endif
    return _PyList_BinarySlice(container, start, stop);
}

static inline bool
_PyJit_CanDecRefNoEscape(PyObject *obj)
{
#ifdef Py_GIL_DISABLED
    return false;
#else
    return Py_REFCNT(obj) > 1 || PyLong_CheckExact(obj) ||
        PyFloat_CheckExact(obj) || PyUnicode_CheckExact(obj) ||
        PyBytes_CheckExact(obj);
#endif
}

static inline PyObject *
_PyJit_NewEmptySet(void)
{
    // Unlike general set construction, this cannot invoke an iterator.
    return PySet_New(NULL);
}

/* Reassigning an identical owned reference has no observable effect. Borrowed
 * mortal references still need the original conversion to an owning reference. */
static inline bool
_PyJit_UnpackLocalsUnchanged(_PyStackRef *locals, PyObject **items, int count)
{
    for (int i = 0; i < count; i++) {
        _PyStackRef previous = locals[i];
        if (PyStackRef_IsNull(previous) ||
            PyStackRef_AsPyObjectBorrow(previous) != items[i] ||
            (!PyStackRef_RefcountOnObject(previous) && !_Py_IsImmortal(items[i])))
        {
            return false;
        }
    }
    return true;
}

static inline bool
_PyJit_CanClosePrimitive(_PyStackRef value)
{
    if (PyStackRef_IsNull(value) || !PyStackRef_RefcountOnObject(value)) {
        return true;
    }
    PyObject *obj = PyStackRef_AsPyObjectBorrow(value);
    return PyLong_CheckExact(obj) || PyFloat_CheckExact(obj) ||
        PyUnicode_CheckExact(obj) || PyBytes_CheckExact(obj);
}

static inline bool
_PyJit_CanCloseNoEscape(_PyStackRef value)
{
    if (PyStackRef_IsNull(value) || !PyStackRef_RefcountOnObject(value)) {
        return true;
    }
#ifdef Py_GIL_DISABLED
    /* A shared reference count is not a no-finalizer proof in FT. */
    return _PyJit_CanClosePrimitive(value);
#else
    return _PyJit_CanDecRefNoEscape(PyStackRef_AsPyObjectBorrow(value));
#endif
}

/* All guards precede reference transfer. On failure the ordinary store still
 * owns both stack inputs and can run an old-value finalizer in its frame. */
static inline bool
_PyJit_StoreAttributeNoEscape(PyObject *owner, _PyStackRef value,
                             Py_ssize_t offset, bool managed)
{
#ifdef Py_GIL_DISABLED
    return false;
#else
    PyObject **slot = (PyObject **)((char *)owner + offset);
    PyObject *old = *slot;
    if (old != NULL && !_PyJit_CanDecRefNoEscape(old)) {
        return false;
    }
    *slot = PyStackRef_AsPyObjectSteal(value);
    if (managed && old == NULL) {
        PyDictValues *values = _PyObject_InlineValues(owner);
        _PyDictValues_AddToInsertionOrder(values, slot - values->values);
    }
    Py_XDECREF(old);
    return true;
#endif
}

static inline void
_PyJit_CloseNoEscape(_PyStackRef value)
{
    assert(_PyJit_CanCloseNoEscape(value));
    PyStackRef_XCLOSE(value);
}

static inline PyObject *
_PyRegion_NumberAttribute(PyObject *owner, Py_ssize_t offset)
{
    PyObject *value = *(PyObject **)((char *)owner + offset);
    if (value != NULL && (PyFloat_CheckExact(value) ||
        (PyLong_CheckExact(value) && _PyLong_IsCompact((PyLongObject *)value))))
    {
        return value;
    }
    return NULL;
}

static inline double
_PyRegion_NumberAsDouble(PyObject *value)
{
    return PyFloat_CheckExact(value) ? PyFloat_AS_DOUBLE(value)
        : (double)_PyLong_CompactValue((PyLongObject *)value);
}

static inline bool
_PyRegion_BoundedInput(_PyStackRef ref, intptr_t *value)
{
    if (PyStackRef_IsNull(ref)) {
        return false;
    }
    PyObject *obj = PyStackRef_AsPyObjectBorrow(ref);
    if (!PyLong_CheckExact(obj) || !_PyLong_IsCompact((PyLongObject *)obj)) {
        return false;
    }
    *value = _PyLong_CompactValue((PyLongObject *)obj);
    return *value >= -_PY_INT_REGION_INPUT_MAX &&
           *value <= _PY_INT_REGION_INPUT_MAX;
}

static inline bool
_PyRegion_AsInt64(_PyStackRef ref, int64_t *value)
{
    if (PyStackRef_IsNull(ref)) {
        return false;
    }
    PyObject *obj = PyStackRef_AsPyObjectBorrow(ref);
    if (!PyLong_CheckExact(obj)) {
        return false;
    }
    if (_PyLong_IsCompact((PyLongObject *)obj)) {
        *value = _PyLong_CompactValue((PyLongObject *)obj);
        return true;
    }
    int overflow;
    *value = PyLong_AsLongLongAndOverflow(obj, &overflow);
    return overflow == 0;
}

static inline bool
_PyRegion_Length(_PyStackRef ref, Py_ssize_t *size)
{
    PyObject *obj = PyStackRef_AsPyObjectBorrow(ref);
    /* Closing the original receiver must not run a finalizer before the
     * consumer. Another strong reference also suffices under the GIL. */
    if (PyStackRef_RefcountOnObject(ref) &&
        !_Py_IsImmortal(obj) && Py_REFCNT(obj) <= 1) {
        return false;
    }
    if (PyUnicode_CheckExact(obj)) {
        *size = PyUnicode_GET_LENGTH(obj);
    }
    else if (PyBytes_CheckExact(obj)) {
        *size = PyBytes_GET_SIZE(obj);
    }
    else if (PyTuple_CheckExact(obj)) {
        *size = PyTuple_GET_SIZE(obj);
    }
    else if (PyList_CheckExact(obj)) {
        *size = PyList_GET_SIZE(obj);
    }
    else if (PyDict_CheckExact(obj)) {
        *size = PyDict_GET_SIZE(obj);
    }
    else {
        return false;
    }
    return true;
}

static inline bool
_PyRegion_EqualityType(PyTypeObject *type)
{
    return type == &PyBytes_Type || type == &PyUnicode_Type ||
           type == &PyLong_Type || type == &PyFloat_Type;
}

/* Both operands have the same exact immutable builtin type. These equality
 * operations cannot call Python, issue BytesWarning, or allocate a result.
 * Preserve tuple comparison's identity shortcut, particularly for NaNs. */
static inline bool
_PyRegion_ImmutableEqual(PyObject *left, PyObject *right)
{
    assert(Py_TYPE(left) == Py_TYPE(right));
    assert(_PyRegion_EqualityType(Py_TYPE(left)));
    if (left == right) {
        return true;
    }
    if (PyBytes_CheckExact(left)) {
        Py_ssize_t size = PyBytes_GET_SIZE(left);
        return size == PyBytes_GET_SIZE(right) &&
               PyBytes_AS_STRING(left)[0] == PyBytes_AS_STRING(right)[0] &&
               (size <= 1 ||
                memcmp(PyBytes_AS_STRING(left), PyBytes_AS_STRING(right), size) == 0);
    }
    if (PyUnicode_CheckExact(left)) {
        return _PyUnicode_Equal(left, right);
    }
    if (PyFloat_CheckExact(left)) {
        return PyFloat_AS_DOUBLE(left) == PyFloat_AS_DOUBLE(right);
    }
    if (_PyLong_BothAreCompact((PyLongObject *)left, (PyLongObject *)right)) {
        return _PyLong_CompactValue((PyLongObject *)left) ==
               _PyLong_CompactValue((PyLongObject *)right);
    }
    PyLongObject *a = (PyLongObject *)left;
    PyLongObject *b = (PyLongObject *)right;
    Py_ssize_t digits = _PyLong_DigitCount(a);
    return _PyLong_SameSign(a, b) && digits == _PyLong_DigitCount(b) &&
           memcmp(a->long_value.ob_digit, b->long_value.ob_digit,
                  (size_t)digits * sizeof(digit)) == 0;
}

/* A fixed pair of checked operations, not a runtime IR interpreter. The
 * selector is a stencil immediate: 0 = add, 1 = subtract, 2 = multiply. */
static inline bool
_PyRegion_Arithmetic(int64_t left, int64_t right, int op, int64_t *result)
{
#if defined(__GNUC__) || defined(__clang__)
    switch (op) {
        case 0: return !__builtin_add_overflow(left, right, result);
        case 1: return !__builtin_sub_overflow(left, right, result);
        case 2: return !__builtin_mul_overflow(left, right, result);
        default: Py_UNREACHABLE();
    }
#else
    /* The experimental matcher is disabled without checked arithmetic. */
    return false;
#endif
}

#endif
