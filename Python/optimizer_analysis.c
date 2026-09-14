#ifdef _Py_TIER2

/*
 * This file contains the support code for CPython's uops optimizer.
 * It also performs some simple optimizations.
 * It performs a traditional data-flow analysis[1] over the trace of uops.
 * Using the information gained, it chooses to emit, or skip certain instructions
 * if possible.
 *
 * [1] For information on data-flow analysis, please see
 * https://clang.llvm.org/docs/DataFlowAnalysisIntro.html
 *
 * */
#include "Python.h"
#include "opcode.h"
#include "pycore_dict.h"
#include "pycore_interp.h"
#include "pycore_opcode_metadata.h"
#include "pycore_opcode_utils.h"
#include "pycore_pystate.h"       // _PyInterpreterState_GET()
#include "pycore_pyatomic_ft_wrappers.h" // FT_ATOMIC_*
#include "pycore_tstate.h"        // _PyThreadStateImpl
#include "pycore_uop_metadata.h"
#include "pycore_long.h"
#include "pycore_interpframe.h"  // _PyFrame_GetCode
#include "pycore_optimizer.h"
#include "pycore_object.h"
#include "pycore_function.h"
#include "pycore_uop_ids.h"
#include "pycore_range.h"
#include "pycore_unicodeobject.h"
#include "pycore_ceval.h"
#include "pycore_floatobject.h"
#include "pycore_setobject.h"
#include "pycore_typeobject.h"

#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#include "optimizer_regions.h"

#ifdef Py_DEBUG
    extern const char *_PyUOpName(int index);
    extern void _PyUOpPrint(const _PyUOpInstruction *uop);
    extern void _PyUOpSymPrint(JitOptRef ref);
    static const char *const DEBUG_ENV = "PYTHON_OPT_DEBUG";
    static inline int get_lltrace(void) {
        char *uop_debug = Py_GETENV(DEBUG_ENV);
        int lltrace = 0;
        if (uop_debug != NULL && *uop_debug >= '0') {
            lltrace = *uop_debug - '0';  // TODO: Parse an int and all that
        }
        return lltrace;
    }
    #define DPRINTF(level, ...) \
    if (get_lltrace() >= (level)) { printf(__VA_ARGS__); }

static void
dump_abstract_stack(_Py_UOpsAbstractFrame *frame, JitOptRef *stack_pointer)
{
    printf("    locals=[");
    for (int i = 0 ; i < frame->locals_len; i++) {
        if (i > 0) {
            printf(", ");
        }
        _PyUOpSymPrint(frame->locals[i]);
    }
    printf("]\n");
    if (stack_pointer < frame->stack) {
        printf("    stack=%d\n", (int)(stack_pointer - frame->stack));
    }
    else {
        printf("    stack=[");
        for (JitOptRef *ptr = frame->stack; ptr < stack_pointer; ptr++) {
            if (ptr != frame->stack) {
                printf(", ");
            }
            _PyUOpSymPrint(*ptr);
        }
        printf("]\n");
    }
    fflush(stdout);
}

static void
dump_uop(JitOptContext *ctx, const char *label, int index,
              const _PyUOpInstruction *instr, JitOptRef *stack_pointer)
{
    if (get_lltrace() >= 3) {
        printf("%4d %s: ", index, label);
        _PyUOpPrint(instr);
        printf("\n");
        if (get_lltrace() >= 5 && ctx->frame->code != ((PyCodeObject *)&_Py_InitCleanup)) {
            dump_abstract_stack(ctx->frame, stack_pointer);
        }
    }
}

static void
dump_uops(JitOptContext *ctx, const char *label,
          _PyUOpInstruction *start, JitOptRef *stack_pointer)
{
    int current_len = uop_buffer_length(&ctx->out_buffer);
    int added_count = (int)(ctx->out_buffer.next - start);
    for (int j = 0; j < added_count; j++) {
        dump_uop(ctx, label, current_len - added_count + j, &start[j], stack_pointer);
    }
}

#define DUMP_UOP dump_uop
#define DUMP_UOPS dump_uops

#else
    #define DPRINTF(level, ...)
    #define DUMP_UOP(ctx, label, index, instr, stack_pointer)
    #define DUMP_UOPS(ctx, label, start, stack_pointer)
#endif

static int
get_mutations(PyObject* dict) {
    assert(PyDict_CheckExact(dict));
    PyDictObject *d = (PyDictObject *)dict;
    uint64_t tag = FT_ATOMIC_LOAD_UINT64_RELAXED(d->_ma_watcher_tag);
    return (tag >> DICT_MAX_WATCHERS) & ((1 << DICT_WATCHED_MUTATION_BITS) - 1);
}

static void
increment_mutations(PyObject* dict) {
    assert(PyDict_CheckExact(dict));
    PyDictObject *d = (PyDictObject *)dict;
    FT_ATOMIC_ADD_UINT64(d->_ma_watcher_tag, 1ULL << DICT_MAX_WATCHERS);
}

/* The first two dict watcher IDs are reserved for CPython,
 * so we don't need to check that they haven't been used */
#define BUILTINS_WATCHER_ID 0
#define GLOBALS_WATCHER_ID  1
#define TYPE_WATCHER_ID  0

static int
globals_watcher_callback(PyDict_WatchEvent event, PyObject* dict,
                         PyObject* key, PyObject* new_value)
{
    RARE_EVENT_STAT_INC(watched_globals_modification);
    assert(get_mutations(dict) < _Py_MAX_ALLOWED_GLOBALS_MODIFICATIONS);
    _Py_Executors_InvalidateDependency(_PyInterpreterState_GET(), dict, 1);
    increment_mutations(dict);
    PyDict_Unwatch(GLOBALS_WATCHER_ID, dict);
    return 0;
}

static int
type_watcher_callback(PyTypeObject* type)
{
    _Py_Executors_InvalidateDependency(_PyInterpreterState_GET(), type, 1);
    PyType_Unwatch(TYPE_WATCHER_ID, (PyObject *)type);
    return 0;
}

static int
_setup_optimizer_watchers(void *Py_UNUSED(arg))
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    FT_ATOMIC_STORE_PTR_RELEASE(
        interp->dict_state.watchers[GLOBALS_WATCHER_ID],
        globals_watcher_callback);
    interp->type_watchers[TYPE_WATCHER_ID] = type_watcher_callback;
    return 0;
}

static void
watch_type(PyTypeObject *type, _PyBloomFilter *filter)
{
    if (_Py_IsImmortal(type) && (type->tp_flags & Py_TPFLAGS_IMMUTABLETYPE)) {
        return;
    }
    PyType_Watch(TYPE_WATCHER_ID, (PyObject *)type);
    _Py_BloomFilter_Add(filter, type);
}

static PyObject *
convert_global_to_const(_PyUOpInstruction *inst, PyObject *obj)
{
    assert(inst->opcode == _LOAD_GLOBAL_MODULE || inst->opcode == _LOAD_GLOBAL_BUILTINS || inst->opcode == _LOAD_ATTR_MODULE);
    assert(PyDict_CheckExact(obj));
    PyDictObject *dict = (PyDictObject *)obj;
    assert(dict->ma_keys->dk_kind == DICT_KEYS_UNICODE);
    PyDictUnicodeEntry *entries = DK_UNICODE_ENTRIES(dict->ma_keys);
    int64_t index = inst->operand1;
    assert(index <= UINT16_MAX);
    if ((int)index >= dict->ma_keys->dk_nentries) {
        return NULL;
    }
    PyDictKeysObject *keys = dict->ma_keys;
    if (keys->dk_version != inst->operand0) {
        return NULL;
    }
    PyObject *res = entries[index].me_value;
    if (res == NULL) {
        return NULL;
    }
    if (_Py_IsImmortal(res)) {
        inst->opcode = _LOAD_CONST_INLINE_BORROW;
    } else {
        inst->opcode = _LOAD_CONST_INLINE;
    }
    inst->operand0 = (uint64_t)res;
    return res;
}

static bool
incorrect_keys(PyObject *obj, uint32_t version)
{
    if (!PyDict_CheckExact(obj)) {
        return true;
    }
    PyDictObject *dict = (PyDictObject *)obj;
    return dict->ma_keys->dk_version != version;
}


#define STACK_LEVEL()     ((int)(stack_pointer - ctx->frame->stack))
#define STACK_SIZE()      ((int)(ctx->frame->stack_len))

static inline int
is_terminator_uop(const _PyUOpInstruction *uop)
{
    int opcode = uop->opcode;
    return (
        opcode == _EXIT_TRACE ||
        opcode == _JUMP_TO_TOP ||
        opcode == _DYNAMIC_EXIT ||
        opcode == _DEOPT
    );
}

#define CURRENT_FRAME_IS_INIT_SHIM() (ctx->frame->code == ((PyCodeObject *)&_Py_InitCleanup))

#define GETLOCAL(idx)          ((ctx->frame->locals[idx]))

#define REPLACE_OP(INST, OP, ARG, OPERAND)    \
    (INST)->opcode = OP;            \
    (INST)->oparg = ARG;            \
    (INST)->operand0 = OPERAND;

#define ADD_OP(OP, ARG, OPERAND) add_op(ctx, this_instr, (OP), (ARG), (OPERAND))

static inline void
add_op(JitOptContext *ctx, _PyUOpInstruction *this_instr,
       uint16_t opcode, uint16_t oparg, uintptr_t operand0)
{
    _PyUOpInstruction *out = ctx->out_buffer.next;
    assert(out < ctx->out_buffer.end);
    out->opcode = (opcode);
    out->format = this_instr->format;
    out->oparg = (oparg);
    out->target = this_instr->target;
    out->operand0 = (operand0);
    out->operand1 = this_instr->operand1;
#ifdef Py_STATS
    out->fitness = this_instr->fitness;
#endif
    ctx->out_buffer.next++;
}

/* Shortened forms for convenience, used in optimizer_bytecodes.c */
#define sym_is_not_null _Py_uop_sym_is_not_null
#define sym_is_const _Py_uop_sym_is_const
#define sym_is_safe_const _Py_uop_sym_is_safe_const
#define sym_is_not_container _Py_uop_sym_is_not_container
#define sym_get_const _Py_uop_sym_get_const
#define sym_new_const_steal _Py_uop_sym_new_const_steal
#define sym_get_const_as_stackref _Py_uop_sym_get_const_as_stackref
#define sym_new_unknown _Py_uop_sym_new_unknown
#define sym_new_not_null _Py_uop_sym_new_not_null
#define sym_new_type _Py_uop_sym_new_type
#define sym_is_null _Py_uop_sym_is_null
#define sym_new_const _Py_uop_sym_new_const
#define sym_new_null _Py_uop_sym_new_null
#define sym_has_type _Py_uop_sym_has_type
#define sym_get_type _Py_uop_sym_get_type
#define sym_get_probable_type _Py_uop_sym_get_probable_type
#define sym_matches_type _Py_uop_sym_matches_type
#define sym_matches_type_version _Py_uop_sym_matches_type_version
#define sym_get_type_version _Py_uop_sym_get_type_version
#define sym_set_null(SYM) _Py_uop_sym_set_null(ctx, SYM)
#define sym_set_non_null(SYM) _Py_uop_sym_set_non_null(ctx, SYM)
#define sym_set_type(SYM, TYPE) _Py_uop_sym_set_type(ctx, SYM, TYPE)
#define sym_set_type_version(SYM, VERSION) _Py_uop_sym_set_type_version(ctx, SYM, VERSION)
#define sym_set_const(SYM, CNST) _Py_uop_sym_set_const(ctx, SYM, CNST)
#define sym_set_compact_int(SYM) _Py_uop_sym_set_compact_int(ctx, SYM)
#define sym_is_bottom _Py_uop_sym_is_bottom
#define sym_truthiness _Py_uop_sym_truthiness
#define frame_new _Py_uop_frame_new
#define frame_new_from_symbol _Py_uop_frame_new_from_symbol
#define frame_pop _Py_uop_frame_pop
#define sym_new_tuple _Py_uop_sym_new_tuple
#define sym_tuple_getitem _Py_uop_sym_tuple_getitem
#define sym_tuple_length _Py_uop_sym_tuple_length
#define sym_is_immortal _Py_uop_symbol_is_immortal
#define sym_is_compact_int _Py_uop_sym_is_compact_int
#define sym_new_compact_int _Py_uop_sym_new_compact_int
#define sym_new_truthiness _Py_uop_sym_new_truthiness
#define sym_new_predicate _Py_uop_sym_new_predicate
#define sym_apply_predicate_narrowing _Py_uop_sym_apply_predicate_narrowing
#define sym_set_recorded_type(SYM, TYPE) _Py_uop_sym_set_recorded_type(ctx, SYM, TYPE)
#define sym_set_recorded_value(SYM, VAL) _Py_uop_sym_set_recorded_value(ctx, SYM, VAL)
#define sym_set_recorded_gen_func(SYM, VAL) _Py_uop_sym_set_recorded_gen_func(ctx, SYM, VAL)
#define sym_get_probable_func_code _Py_uop_sym_get_probable_func_code
#define sym_get_probable_value _Py_uop_sym_get_probable_value
#define sym_set_stack_depth(DEPTH, SP) _Py_uop_sym_set_stack_depth(ctx, DEPTH, SP)

/* Comparison oparg masks */
#define COMPARE_LT_MASK 2
#define COMPARE_GT_MASK 4
#define COMPARE_EQ_MASK 8

#define JUMP_TO_LABEL(label) goto label;

static int
check_stack_bounds(JitOptContext *ctx, JitOptRef *stack_pointer, int offset, int opcode)
{
    int stack_level = (int)(stack_pointer + (offset) - ctx->frame->stack);
    int should_check = !CURRENT_FRAME_IS_INIT_SHIM() ||
        (opcode == _RETURN_VALUE) ||
        (opcode == _RETURN_GENERATOR) ||
        (opcode == _YIELD_VALUE);
    if (should_check && (stack_level < 0 || stack_level > STACK_SIZE() + MAX_CACHED_REGISTER)) {
        ctx->contradiction = true;
        ctx->done = true;
        return 1;
    }
    return 0;
}

#define CHECK_STACK_BOUNDS(offset) \
    if (check_stack_bounds(ctx, stack_pointer, offset, opcode)) { \
        break; \
    } \

static int
optimize_to_bool(
    _PyUOpInstruction *this_instr,
    JitOptContext *ctx,
    JitOptRef value,
    JitOptRef *result_ptr,
    uint16_t prefix, uint16_t suffix)
{
    if (sym_matches_type(value, &PyBool_Type)) {
        ADD_OP(_NOP, 0, 0);
        *result_ptr = value;
        return 1;
    }
    int truthiness = sym_truthiness(ctx, value);
    if (truthiness >= 0) {
        PyObject *load = truthiness ? Py_True : Py_False;
        if (prefix != _NOP) {
            ADD_OP(prefix, 0, 0);
        }
        ADD_OP(_LOAD_CONST_INLINE_BORROW, 0, (uintptr_t)load);
        if (suffix != _NOP) {
            ADD_OP(suffix, 2, 0);
        }
        *result_ptr = sym_new_const(ctx, load);
        return 1;
    }
    return 0;
}

static void
optimize_dict_known_hash(
    JitOptContext *ctx, _PyBloomFilter *dependencies, _PyUOpInstruction *this_instr,
    PyObject *sub, uint16_t opcode)
{
    if (PyUnicode_CheckExact(sub) || PyLong_CheckExact(sub) || PyBytes_CheckExact(sub)
            || PyFloat_CheckExact(sub) || PyComplex_CheckExact(sub)) {
        // PyObject_Hash can't fail on these types
        ADD_OP(opcode, 0, PyObject_Hash(sub));
    }
    else if (PyTuple_CheckExact(sub)) {
        // only use known hash variant when hash of tuple is already computed
        // since computing it can call arbitrary code
        Py_hash_t hash = ((PyTupleObject *)sub)->ob_hash;
        if (hash != -1) {
            ADD_OP(opcode, 0, hash);
        }
    }
    else if (Py_TYPE(sub)->tp_hash == PyBaseObject_Type.tp_hash) {
        // for user-defined objects which don't override tp_hash
        Py_hash_t hash = PyObject_Hash(sub);
        ADD_OP(opcode, 0, hash);
        watch_type(Py_TYPE(sub), dependencies);
    }
}

static void
eliminate_pop_guard(_PyUOpInstruction *this_instr, JitOptContext *ctx, bool exit)
{
    ADD_OP(_POP_TOP, 0, 0);
    if (exit) {
        REPLACE_OP((this_instr+1), _EXIT_TRACE, 0, 0);
        this_instr[1].target = this_instr->target;
    }
}

static JitOptRef
lookup_attr(JitOptContext *ctx, _PyBloomFilter *dependencies, _PyUOpInstruction *this_instr,
            PyTypeObject *type, PyObject *name,
            uint16_t prefix, uint16_t suffix)
{
    // The cached value may be dead, so we need to do the lookup again... :(
    if (type && PyType_Check(type)) {
        PyObject *lookup = _PyType_Lookup(type, name);
        if (lookup) {
            bool immortal = _Py_IsImmortal(lookup) || (type->tp_flags & Py_TPFLAGS_IMMUTABLETYPE);
            if (prefix != _NOP) {
                ADD_OP(prefix, 0, 0);
            }
            ADD_OP(immortal ? _LOAD_CONST_INLINE_BORROW : _LOAD_CONST_INLINE,
                   0, (uintptr_t)lookup);
            if (suffix != _NOP) {
                ADD_OP(suffix, 2, 0);
            }
            if ((type->tp_flags & Py_TPFLAGS_IMMUTABLETYPE) == 0) {
                watch_type(type, dependencies);
            }
            return sym_new_const(ctx, lookup);
        }
    }
    return sym_new_not_null(ctx);
}

static void
optimize_pop_top(JitOptContext *ctx, _PyUOpInstruction *this_instr, JitOptRef value)
{
    PyTypeObject *typ = sym_get_type(value);
    if (PyJitRef_IsBorrowed(value) ||
        sym_is_immortal(PyJitRef_Unwrap(value)) ||
        sym_is_null(value)) {
        ADD_OP(_POP_TOP_NOP, 0, 0);
    }
    else if (typ == &PyLong_Type) {
        ADD_OP(_POP_TOP_INT, 0, 0);
    }
    else if (typ == &PyFloat_Type) {
        ADD_OP(_POP_TOP_FLOAT, 0, 0);
    }
    else if (typ == &PyUnicode_Type) {
        ADD_OP(_POP_TOP_UNICODE, 0, 0);
    }
    else {
        ADD_OP(_POP_TOP, 0, 0);
    }
}

/* Look up name via super (normal case from supercheck where
   su_obj_type = Py_TYPE(obj)). */
static JitOptRef
lookup_super_attr(JitOptContext *ctx, _PyBloomFilter *dependencies,
                  _PyUOpInstruction *this_instr,
                  PyTypeObject *su_type, PyTypeObject *obj_type,
                  PyObject *name,
                  uint16_t immortal, uint16_t mortal, uint16_t suffix)
{
    if (su_type == NULL || obj_type == NULL) {
        return sym_new_not_null(ctx);
    }
    /* Normal case: obj_type must be a subtype of su_type */
    if (!PyType_IsSubtype(obj_type, su_type)) {
        return sym_new_not_null(ctx);
    }
    PyObject *lookup = _PySuper_LookupDescr(su_type, obj_type, name);
    if (lookup == NULL) {
        if (PyErr_Occurred()) {
            PyErr_Clear();
        }
        return sym_new_not_null(ctx);
    }
    if ((Py_TYPE(lookup)->tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR) == 0) {
        Py_DECREF(lookup);
        return sym_new_not_null(ctx);
    }
    int opcode = mortal;
    if (_Py_IsImmortal(lookup) || (obj_type->tp_flags & Py_TPFLAGS_IMMUTABLETYPE)) {
        opcode = immortal;
    }
    ADD_OP(_SWAP, 3, 0);
    ADD_OP(_POP_TOP, 0, 0);
    ADD_OP(_POP_TOP, 0, 0);
    ADD_OP(opcode, 0, (uintptr_t)lookup);
    if (suffix != _NOP) {
        ADD_OP(suffix, 2, 0);
    }
    // if obj_type is immutable, then all its superclasses are immutable
    if ((obj_type->tp_flags & Py_TPFLAGS_IMMUTABLETYPE) == 0) {
        watch_type(su_type, dependencies);
        watch_type(obj_type, dependencies);
    }
    return sym_new_const_steal(ctx, lookup);
}

static
PyCodeObject *
get_current_code_object(JitOptContext *ctx)
{
    return (PyCodeObject *)ctx->frame->code;
}

static PyObject *
get_co_name(JitOptContext *ctx, int index)
{
    return PyTuple_GET_ITEM(get_current_code_object(ctx)->co_names, index);
}

static int
get_test_bit_for_bools(void) {
#ifdef Py_STACKREF_DEBUG
    uintptr_t false_bits = _Py_STACKREF_FALSE_INDEX;
    uintptr_t true_bits = _Py_STACKREF_TRUE_INDEX;
#else
    uintptr_t false_bits = (uintptr_t)&_Py_FalseStruct;
    uintptr_t true_bits = (uintptr_t)&_Py_TrueStruct;
#endif
    for (int i = 4; i < 8; i++) {
        if ((true_bits ^ false_bits) & (uintptr_t)(1 << i)) {
            return i;
        }
    }
    return 0;
}

static int
test_bit_set_in_true(int bit) {
#ifdef Py_STACKREF_DEBUG
    uintptr_t true_bits = _Py_STACKREF_TRUE_INDEX;
#else
    uintptr_t true_bits = (uintptr_t)&_Py_TrueStruct;
#endif
    assert((true_bits ^ ((uintptr_t)&_Py_FalseStruct)) & (uintptr_t)(1 << bit));
    return true_bits & (uintptr_t)(1 << bit);
}

#ifdef Py_DEBUG
void
_Py_opt_assert_within_stack_bounds(
    _Py_UOpsAbstractFrame *frame, JitOptRef *stack_pointer,
    const char *filename, int lineno
) {
    if (frame->code == ((PyCodeObject *)&_Py_InitCleanup)) {
        return;
    }
    int level = (int)(stack_pointer - frame->stack);
    if (level < 0) {
        printf("Stack underflow (depth = %d) at %s:%d\n", level, filename, lineno);
        fflush(stdout);
        abort();
    }
    int size = (int)(frame->stack_len) + MAX_CACHED_REGISTER;
    if (level > size) {
        printf("Stack overflow (depth = %d) at %s:%d\n", level, filename, lineno);
        fflush(stdout);
        abort();
    }
}
#endif

#ifdef Py_DEBUG
#define ASSERT_WITHIN_STACK_BOUNDS(F, L) _Py_opt_assert_within_stack_bounds(ctx->frame, stack_pointer, (F), (L))
#else
#define ASSERT_WITHIN_STACK_BOUNDS(F, L) (void)0
#endif

/* >0 (length) for success, 0 for not ready, clears all possible errors. */
static int
optimize_uops(
    _PyThreadStateImpl *tstate,
    _PyUOpInstruction *trace,
    int trace_len,
    int curr_stacklen,
    _PyUOpInstruction *output,
    _PyBloomFilter *dependencies
)
{
    assert(!PyErr_Occurred());
    assert(tstate->jit_tracer_state != NULL);
    PyFunctionObject *func = tstate->jit_tracer_state->initial_state.func;

    JitOptContext *ctx = &tstate->jit_tracer_state->opt_context;
    uint32_t opcode = UINT16_MAX;

    uop_buffer_init(&ctx->out_buffer, output, UOP_MAX_TRACE_LENGTH);

    // Make sure that watchers are set up
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PyOnceFlag_CallOnce(&interp->dict_state.watcher_setup_once,
                         _setup_optimizer_watchers, NULL);

    _Py_uop_abstractcontext_init(ctx, dependencies);
    _Py_UOpsAbstractFrame *frame = _Py_uop_frame_new(ctx, (PyCodeObject *)func->func_code, NULL, 0);
    if (frame == NULL) {
        return 0;
    }
    frame->func = func;
    ctx->curr_frame_depth++;
    ctx->frame = frame;
    _Py_uop_sym_set_stack_depth(ctx, curr_stacklen, frame->stack_pointer);

    _PyUOpInstruction *this_instr = NULL;
    JitOptRef *stack_pointer = ctx->frame->stack_pointer;

    for (int i = 0; i < trace_len; i++) {
        this_instr = &trace[i];
        if (ctx->done) {
            // Don't do any more optimization, but
            // we still need to reach a terminator for corrctness.
            *(ctx->out_buffer.next++) = *this_instr;
            if (is_terminator_uop(this_instr)) {
                break;
            }
            continue;
        }

        int oparg = this_instr->oparg;
        opcode = this_instr->opcode;

        if (!CURRENT_FRAME_IS_INIT_SHIM()) {
            stack_pointer = ctx->frame->stack_pointer;
        }

        DUMP_UOP(ctx, "abs", (int)(this_instr - trace), this_instr, stack_pointer);

        _PyUOpInstruction *out_ptr = ctx->out_buffer.next;

        switch (opcode) {

#include "optimizer_cases.c.h"

            default:
                DPRINTF(1, "\nUnknown opcode in abstract interpreter\n");
                Py_UNREACHABLE();
        }
        // If no ADD_OP was called during this iteration, copy the original instruction
        if (ctx->out_buffer.next == out_ptr) {
            *(ctx->out_buffer.next++) = *this_instr;
        }
        assert(ctx->frame != NULL);
        DUMP_UOPS(ctx, "out", out_ptr, stack_pointer);
        if (!CURRENT_FRAME_IS_INIT_SHIM() && !ctx->done) {
            DPRINTF(3, " stack_level %d\n", STACK_LEVEL());
            ctx->frame->stack_pointer = stack_pointer;
            assert(STACK_LEVEL() >= 0);
        }
    }
    if (ctx->out_of_space) {
        DPRINTF(3, "\n");
        DPRINTF(1, "Out of space in abstract interpreter\n");
    }
    if (ctx->contradiction) {
        // Attempted to push a "bottom" (contradiction) symbol onto the stack.
        // This means that the abstract interpreter has optimized to trace
        // to an unreachable estate.
        // We *could* generate an _EXIT_TRACE or _FATAL_ERROR here, but hitting
        // bottom usually indicates an optimizer bug, so we are probably better off
        // retrying later.
        DPRINTF(3, "\n");
        DPRINTF(1, "Hit bottom in abstract interpreter\n");
        _Py_uop_abstractcontext_fini(ctx);
        OPT_STAT_INC(optimizer_contradiction);
        return 0;
    }

    /* Either reached the end or cannot optimize further, but there
     * would be no benefit in retrying later */
    _Py_uop_abstractcontext_fini(ctx);
    // Check that the trace ends with a proper terminator
    if (uop_buffer_length(&ctx->out_buffer) > 0) {
        assert(is_terminator_uop(uop_buffer_last(&ctx->out_buffer)));
    }

    return uop_buffer_length(&ctx->out_buffer);

error:
    DPRINTF(3, "\n");
    DPRINTF(1, "Encountered error in abstract interpreter\n");
    if (opcode <= MAX_UOP_ID) {
        OPT_ERROR_IN_OPCODE(opcode);
    }
    _Py_uop_abstractcontext_fini(ctx);

    assert(PyErr_Occurred());
    PyErr_Clear();

    return 0;

}

const uint16_t op_without_push[MAX_UOP_ID + 1] = {
    [_COPY] = _NOP,
    [_LOAD_CONST_INLINE] = _NOP,
    [_LOAD_CONST_INLINE_BORROW] = _NOP,
    [_LOAD_FAST] = _NOP,
    [_LOAD_FAST_BORROW] = _NOP,
    [_LOAD_SMALL_INT] = _NOP,
    [_PUSH_NULL] = _NOP,
};

const bool op_skip[MAX_UOP_ID + 1] = {
    [_NOP] = true,
    [_CHECK_VALIDITY] = true,
    [_CHECK_PERIODIC] = true,
    [_SET_IP] = true,
};

const uint16_t op_without_pop[MAX_UOP_ID + 1] = {
    [_POP_TOP] = _NOP,
    [_POP_TOP_NOP] = _NOP,
    [_POP_TOP_INT] = _NOP,
    [_POP_TOP_FLOAT] = _NOP,
    [_POP_TOP_UNICODE] = _NOP,
};


static int
remove_unneeded_uops(_PyUOpInstruction *buffer, int buffer_size)
{
    /* Remove _SET_IP and _CHECK_VALIDITY where possible.
     * _SET_IP is needed if the following instruction escapes or
     * could error. _CHECK_VALIDITY is needed if the previous
     * instruction could have escaped. */
    int last_set_ip = -1;
    bool may_have_escaped = true;
    for (int pc = 0; pc < buffer_size; pc++) {
        int opcode = buffer[pc].opcode;
        switch (opcode) {
            case _START_EXECUTOR:
                may_have_escaped = false;
                break;
            case _SET_IP:
                buffer[pc].opcode = _NOP;
                last_set_ip = pc;
                break;
            case _CHECK_VALIDITY:
                if (may_have_escaped) {
                    may_have_escaped = false;
                }
                else {
                    buffer[pc].opcode = _NOP;
                }
                break;
            case _EXIT_TRACE:
            default:
            {
                // Cancel out pushes and pops, repeatedly. So:
                //     _LOAD_FAST + _POP_TOP + _POP_TOP + _LOAD_CONST_INLINE_BORROW + _POP_TOP
                // ...becomes:
                //     _NOP + _NOP + _POP_TOP + _NOP + _NOP
                while (op_without_pop[opcode]) {
                    _PyUOpInstruction *last = &buffer[pc - 1];
                    while (op_skip[last->opcode]) {
                        last--;
                    }
                    if (op_without_push[last->opcode] && op_without_pop[opcode]) {
                        last->opcode = op_without_push[last->opcode];
                        opcode = buffer[pc].opcode = op_without_pop[opcode];
                        if (op_without_pop[last->opcode]) {
                            opcode = last->opcode;
                            pc = (int)(last - buffer);
                        }
                    }
                    else {
                        break;
                    }
                }
                /* _PUSH_FRAME doesn't escape or error, but it
                 * does need the IP for the return address */
                bool needs_ip = (opcode == _PUSH_FRAME || opcode == _YIELD_VALUE || opcode == _DYNAMIC_EXIT || opcode == _EXIT_TRACE);
                if (_PyUop_Flags[opcode] & HAS_ESCAPES_FLAG) {
                    needs_ip = true;
                    may_have_escaped = true;
                }
                if (needs_ip && last_set_ip >= 0) {
                    assert(buffer[last_set_ip].opcode == _NOP);
                    buffer[last_set_ip].opcode = _SET_IP;
                    last_set_ip = -1;
                }
                if (opcode == _EXIT_TRACE) {
                    return pc + 1;
                }
                break;
            }
            case _JUMP_TO_TOP:
            case _DYNAMIC_EXIT:
            case _DEOPT:
                return pc + 1;
        }
    }
    Py_UNREACHABLE();
}

static void
fuse_float_product_updates(_PyUOpInstruction *buffer, int length)
{
    const char *enabled = Py_GETENV("PYTHON_TIER2_FLOAT_FUSION");
    if (enabled == NULL || strcmp(enabled, "1") != 0) {
        return;
    }
    for (int pc = 0; pc + 5 < length; pc++) {
        if (buffer[pc].opcode != _BINARY_OP_MULTIPLY_FLOAT ||
            (buffer[pc + 1].opcode != _POP_TOP_NOP &&
             buffer[pc + 1].opcode != _POP_TOP_FLOAT) ||
            (buffer[pc + 2].opcode != _POP_TOP_NOP &&
             buffer[pc + 2].opcode != _POP_TOP_FLOAT))
        {
            continue;
        }
        bool owned_factors = buffer[pc + 1].opcode == _POP_TOP_FLOAT ||
                             buffer[pc + 2].opcode == _POP_TOP_FLOAT;
        int add = pc + 3;
        bool skipped_accumulator_guard = false;
        while (add < length &&
               (buffer[add].opcode == _NOP ||
                buffer[add].opcode == _GUARD_NOS_FLOAT)) {
            skipped_accumulator_guard |= buffer[add].opcode == _GUARD_NOS_FLOAT;
            add++;
        }
        if (add + 2 >= length) {
            continue;
        }
        int update = buffer[add].opcode;
        bool unique_left =
            update == _BINARY_OP_ADD_FLOAT_INPLACE ||
            update == _BINARY_OP_SUBTRACT_FLOAT_INPLACE;
        bool unique_right =
            update == _BINARY_OP_ADD_FLOAT_INPLACE_RIGHT ||
            update == _BINARY_OP_SUBTRACT_FLOAT_INPLACE_RIGHT;
        if ((!unique_left && !unique_right) ||
            (owned_factors && !unique_left) ||
            (skipped_accumulator_guard && !unique_right) ||
            buffer[add + 1].opcode != (unique_left ? _POP_TOP_FLOAT : _POP_TOP_NOP) ||
            buffer[add + 2].opcode != _POP_TOP_NOP) {
            continue;
        }
        bool subtract =
            update == _BINARY_OP_SUBTRACT_FLOAT_INPLACE ||
            update == _BINARY_OP_SUBTRACT_FLOAT_INPLACE_RIGHT;
        if (owned_factors) {
            buffer[pc].opcode = subtract ? _BINARY_OP_MULTIPLY_SUBTRACT_FLOAT_OWNED
                                        : _BINARY_OP_MULTIPLY_ADD_FLOAT_OWNED;
        }
        else {
            buffer[pc].opcode = unique_left
                ? (subtract ? _BINARY_OP_MULTIPLY_SUBTRACT_FLOAT_INPLACE
                            : _BINARY_OP_MULTIPLY_ADD_FLOAT_INPLACE)
                : (subtract ? _BINARY_OP_MULTIPLY_SUBTRACT_FLOAT_SHARED
                            : _BINARY_OP_MULTIPLY_ADD_FLOAT_SHARED);
        }
        for (int i = pc + 1; i <= add + 2; i++) {
            if (owned_factors && i <= pc + 2) {
                /* The new uop returns both original factor references for
                 * these exact-float cleanup operations, in their old order. */
                continue;
            }
            assert(buffer[i].opcode == _NOP ||
                   buffer[i].opcode == _POP_TOP_NOP ||
                   buffer[i].opcode == _POP_TOP_FLOAT ||
                   buffer[i].opcode == _GUARD_NOS_FLOAT ||
                   buffer[i].opcode == _BINARY_OP_ADD_FLOAT_INPLACE ||
                   buffer[i].opcode == _BINARY_OP_SUBTRACT_FLOAT_INPLACE ||
                   buffer[i].opcode == _BINARY_OP_ADD_FLOAT_INPLACE_RIGHT ||
                   buffer[i].opcode == _BINARY_OP_SUBTRACT_FLOAT_INPLACE_RIGHT);
            buffer[i].opcode = _NOP;
        }
    }
}

static inline int
trivial_call_skip(const _PyUOpInstruction *buffer, int pc, int end)
{
    while (pc < end) {
        int next = region_skip(buffer, pc, end);
        if (next < end && (_PyUop_Flags[buffer[next].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            pc = next + 1;
        }
        else {
            return next;
        }
    }
    return pc;
}

static int
trivial_attribute_load(_PyUOpInstruction *buffer, int pc, int end,
                       int nargs, uint64_t *descriptor)
{
    pc = trivial_call_skip(buffer, pc, end);
    if (pc >= end || (region_opcode(&buffer[pc]) != _LOAD_FAST &&
                     region_opcode(&buffer[pc]) != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg > nargs) {
        return -1;
    }
    int arg = buffer[pc++].oparg;
    pc = trivial_call_skip(buffer, pc, end);
    if (pc < end && buffer[pc].opcode == _GUARD_TYPE_VERSION) {
        pc = trivial_call_skip(buffer, pc + 1, end);
    }
    if (pc < end && buffer[pc].opcode == _CHECK_MANAGED_OBJECT_HAS_VALUES) {
        pc = trivial_call_skip(buffer, pc + 1, end);
    }
    if (pc >= end || (buffer[pc].opcode != _LOAD_ATTR_SLOT &&
                      buffer[pc].opcode != _LOAD_ATTR_INSTANCE_VALUE) ||
        !buffer[pc].operand1 || buffer[pc].operand0 > UINT16_MAX) {
        return -1;
    }
    uint64_t version = buffer[pc].operand1 & UINT32_MAX;
    uint64_t managed = buffer[pc].operand1 >> 32;
    *descriptor = arg | (buffer[pc].operand0 << 3) | (version << 19) | (managed << 51);
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc >= end || (buffer[pc].opcode != _POP_TOP && buffer[pc].opcode != _POP_TOP_NOP)) {
        return -1;
    }
    return trivial_call_skip(buffer, pc + 1, end);
}

static void
eliminate_trivial_frames(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) {
        return;
    }
    /* Abstract interpretation has already proved the call and return match.
     * Admit an argument, immortal constant, cached attribute, or a predicate
     * over such attributes. Preserve the caller's version, argument,
     * recursion, and stack-space checks. The replacement checks the callee's
     * eval breaker before consuming anything, at the original CALL boundary.
     * No callee frame can escape in this interval. */
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS ||
            buffer[start].oparg > 4) {
            continue;
        }
        int end = Py_MIN(length, start + 64);
        int pc = trivial_call_skip(buffer, start + 1, end);
        if (pc >= end || buffer[pc++].opcode != _SAVE_RETURN_OFFSET) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc++].opcode != _PUSH_FRAME) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc++].opcode != _TIER2_RESUME_CHECK) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end) {
            continue;
        }
        uintptr_t source;
        uint64_t config = 0, descriptor;
        int after_attribute = trivial_attribute_load(
            buffer, pc, end, buffer[start].oparg, &descriptor);
        int opcode = region_opcode(&buffer[pc]);
        if (after_attribute >= 0) {
            int mode = 0;
            pc = after_attribute;
            if (pc < end && buffer[pc].opcode == _LOAD_CONST_INLINE_BORROW &&
                buffer[pc].operand0 == (uintptr_t)Py_None) {
                pc = trivial_call_skip(buffer, pc + 1, end);
                if (pc >= end || buffer[pc].opcode != _IS_OP) {
                    continue;
                }
                mode = buffer[pc++].oparg ? 2 : 1;
                for (int i = 0; i < 2; i++) {
                    pc = trivial_call_skip(buffer, pc, end);
                    if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                                      buffer[pc].opcode != _POP_TOP_NOP)) {
                        pc = end;
                        break;
                    }
                    pc++;
                }
            }
            else if (pc < end && (region_opcode(&buffer[pc]) == _LOAD_FAST ||
                                  region_opcode(&buffer[pc]) == _LOAD_FAST_BORROW)) {
                pc = trivial_attribute_load(buffer, pc, end, buffer[start].oparg, &config);
                if (pc < 0) {
                    continue;
                }
                while (pc < end && (buffer[pc].opcode == _GUARD_TOS_INT ||
                                    buffer[pc].opcode == _GUARD_NOS_INT)) {
                    pc = trivial_call_skip(buffer, pc + 1, end);
                }
                if (pc >= end || buffer[pc].opcode != _COMPARE_OP_INT) {
                    continue;
                }
                mode = 3;
                config |= (uint64_t)(buffer[pc++].oparg & 15) << 52;
                for (int i = 0; i < 2; i++) {
                    pc = trivial_call_skip(buffer, pc, end);
                    if (pc >= end || (buffer[pc].opcode != _POP_TOP_INT &&
                                      buffer[pc].opcode != _POP_TOP_NOP)) {
                        pc = end;
                        break;
                    }
                    pc++;
                }
            }
            source = ((descriptor | ((uint64_t)mode << 52)) << 2) | 2;
            pc = trivial_call_skip(buffer, pc, end);
        }
        else if (opcode == _LOAD_FAST || opcode == _LOAD_FAST_BORROW) {
            if (buffer[pc].oparg > buffer[start].oparg) {
                continue;
            }
            /* Odd operands identify argument slots; constants are aligned. */
            source = ((uintptr_t)buffer[pc].oparg << 1) | 1;
            pc = trivial_call_skip(buffer, pc + 1, end);
        }
        else if (opcode == _LOAD_CONST_INLINE_BORROW &&
                 _Py_IsImmortal((PyObject *)buffer[pc].operand0)) {
            source = buffer[pc].operand0;
            pc = trivial_call_skip(buffer, pc + 1, end);
        }
        else {
            continue;
        }
        if (pc < end && buffer[pc].opcode == _MAKE_HEAP_SAFE) {
            pc = trivial_call_skip(buffer, pc + 1, end);
        }
        if (pc >= end || buffer[pc].opcode != _RETURN_VALUE) {
            continue;
        }
        buffer[start].opcode = (source & 3) == 2 ? _CALL_PY_ATTRIBUTE : _CALL_PY_TRIVIAL;
        buffer[start].operand0 = source;
        buffer[start].operand1 = config;
        for (int i = start + 1; i <= pc; i++) {
            /* Leave recorded references for the normal tracer cleanup. */
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc;
    }
#endif
}

/* A cached attribute followed by exact list indexing, optionally consumed by
 * a constant length predicate. Guard failures resume at the original CALL. */
static void
inline_list_attribute_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        int nargs = buffer[start].oparg;
        if (buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS || nargs > 4) {
            continue;
        }
        int end = Py_MIN(length, start + 96);
        int pc = start + 1;
#define LIST_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                     pc < end ? region_opcode(&buffer[pc]) : 0)
#define LIST_EXPECT(OP) do { if (LIST_NEXT() != (OP)) goto next_list_call; pc++; } while (0)
        if (LIST_NEXT() != _SAVE_RETURN_OFFSET || buffer[pc].oparg > 255) {
            continue;
        }
        uint64_t config = (uint64_t)buffer[pc++].oparg << 56;
        LIST_EXPECT(_PUSH_FRAME);
        LIST_EXPECT(_TIER2_RESUME_CHECK);
        uint32_t globals_version = 0;
        if (LIST_NEXT() == _GUARD_GLOBALS_VERSION) {
            globals_version = (uint32_t)buffer[pc++].operand0;
            if (globals_version == 0) {
                continue;
            }
        }
        if (LIST_NEXT() == _GUARD_BUILTINS_IDENTITY) {
            pc++;
        }
        bool length_predicate = LIST_NEXT() == _LOAD_CONST_INLINE ||
                                LIST_NEXT() == _LOAD_CONST_INLINE_BORROW;
        if (length_predicate) {
            if (buffer[pc++].operand0 !=
                (uintptr_t)_PyInterpreterState_GET()->callable_cache.len) {
                continue;
            }
            LIST_EXPECT(_PUSH_NULL);
            config |= 8 | ((uint64_t)globals_version << 24);
        }
        else if (globals_version != 0) {
            continue;
        }
        uint64_t descriptor;
        pc = trivial_attribute_load(buffer, pc, end, nargs, &descriptor);
        if (pc < 0 || LIST_NEXT() != _LOAD_FAST_BORROW || buffer[pc].oparg > nargs) {
            continue;
        }
        config |= buffer[pc++].oparg;
        int op;
        while ((op = LIST_NEXT()) == _GUARD_TOS_INT || op == _GUARD_NOS_LIST) {
            pc++;
        }
        LIST_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        for (int i = 0; i < 2; i++) {
            op = LIST_NEXT();
            if (op != _POP_TOP && op != _POP_TOP_NOP) {
                goto next_list_call;
            }
            pc++;
        }
        if (length_predicate) {
            if (LIST_NEXT() != _CALL_LEN_CONSUMER ||
                (buffer[pc].oparg & 48) != 48 || buffer[pc].operand0 > UINT16_MAX) {
                continue;
            }
            config |= ((uint64_t)(buffer[pc].oparg & 15) << 4) |
                      (buffer[pc].operand0 << 8);
            pc++;
            for (int i = 0; i < 2; i++) {
                op = LIST_NEXT();
                if (op != _POP_TOP && op != _POP_TOP_NOP) {
                    goto next_list_call;
                }
                pc++;
            }
        }
        if (LIST_NEXT() == _MAKE_HEAP_SAFE) {
            pc++;
        }
        LIST_EXPECT(_RETURN_VALUE);
        buffer[start].opcode = _CALL_PY_LIST;
        buffer[start].operand0 = descriptor;
        buffer[start].operand1 = config;
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_list_call:
        ;
#undef LIST_EXPECT
#undef LIST_NEXT
    }
#endif
}

/* Match a complete class call whose initializer stores each argument once.
 * Keep allocation identity, and retain a materialization path for pending work
 * after allocation. No arbitrary initializer bytecode is executed by the uop. */
static void
inline_attribute_initializers(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        int nargs = buffer[start].oparg;
        if (buffer[start].opcode != _ALLOCATE_OBJECT || nargs < 1 || nargs > 4) {
            continue;
        }
        int end = Py_MIN(length, start + 96);
        int pc = start + 1;
        uint64_t fields = 0;
        uint32_t type_version = 0;
        unsigned int arguments = 0;
        unsigned int offsets[4];
#define INIT_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                     pc < end ? region_opcode(&buffer[pc]) : 0)
#define INIT_EXPECT(OP) do { if (INIT_NEXT() != (OP)) goto next_init; pc++; } while (0)
        if (INIT_NEXT() != _CREATE_INIT_FRAME || buffer[pc].operand0 == 0) {
            continue;
        }
        uint64_t func_version = buffer[pc++].operand0;
        INIT_EXPECT(_PUSH_FRAME);
        INIT_EXPECT(_TIER2_RESUME_CHECK);
        for (int i = 0; i < nargs; i++) {
            if (INIT_NEXT() != _LOAD_FAST_BORROW ||
                buffer[pc].oparg < 1 || buffer[pc].oparg > nargs) {
                goto next_init;
            }
            unsigned int arg = buffer[pc++].oparg - 1;
            if (arguments & (1U << arg)) {
                goto next_init;
            }
            arguments |= 1U << arg;
            if (INIT_NEXT() != _LOAD_FAST_BORROW || buffer[pc++].oparg != 0) {
                goto next_init;
            }
            INIT_EXPECT(_LOCK_OBJECT);
            if (INIT_NEXT() == _GUARD_TYPE_VERSION_LOCKED) {
                uint32_t version = (uint32_t)buffer[pc++].operand0;
                if (version == 0 || (type_version && type_version != version)) {
                    goto next_init;
                }
                type_version = version;
            }
            INIT_EXPECT(_GUARD_DORV_NO_DICT);
            if (INIT_NEXT() != _STORE_ATTR_INSTANCE_VALUE ||
                buffer[pc].operand0 > 2040 || (buffer[pc].operand0 & 7)) {
                goto next_init;
            }
            unsigned int offset = (unsigned int)buffer[pc++].operand0 / 8;
            for (int j = 0; j < i; j++) {
                if (offset == offsets[j]) {
                    goto next_init;
                }
            }
            offsets[i] = offset;
            fields |= (uint64_t)(offset | (arg << 8)) << (10 * i);
            INIT_EXPECT(_POP_TOP_NOP);
        }
        if (type_version == 0 || INIT_NEXT() != _LOAD_CONST_INLINE_BORROW ||
            buffer[pc++].operand0 != (uintptr_t)Py_None) {
            continue;
        }
        INIT_EXPECT(_RETURN_VALUE);
        INIT_EXPECT(_EXIT_INIT_CHECK);
        if (INIT_NEXT() == _MAKE_HEAP_SAFE) {
            pc++;
        }
        bool dynamic_return = INIT_NEXT() == _DEOPT && buffer[pc].target == 1 &&
            buffer[pc].operand0 == (uintptr_t)(_PyCode_CODE(&_Py_InitCleanup) + 1);
        if (!dynamic_return) {
            INIT_EXPECT(_RETURN_VALUE);
        }
        buffer[start].opcode = _CALL_CLASS_ATTRIBUTES;
        buffer[start].operand0 = func_version | ((uint64_t)type_version << 32);
        buffer[start].operand1 = fields | ((uint64_t)dynamic_return << 63);
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        if (dynamic_return) {
            /* The original trace stops at the cleanup trampoline's RETURN.
             * The fused call has already returned to its real caller. */
            buffer[pc].opcode = _DYNAMIC_EXIT;
            buffer[pc].target = 0;
            buffer[pc].operand0 = 0;
        }
        start = pc - 1;
next_init:
        ;
#undef INIT_EXPECT
#undef INIT_NEXT
    }
#endif
}

static void
fuse_list_pair_comparisons(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        if (region_opcode(&buffer[start]) != _LOAD_FAST_BORROW) {
            continue;
        }
        int list_local = buffer[start].oparg;
        int end = Py_MIN(start + 64, length);
        int pc = start + 1;
#define PAIR_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                    pc < end ? region_opcode(&buffer[pc]) : -1)
#define PAIR_EXPECT(OP) do { \
    if (PAIR_NEXT() != (OP)) goto next_pair; \
    pc++; \
} while (0)
#define PAIR_GUARDS() do { \
    int op; \
    while ((op = PAIR_NEXT()) == _GUARD_TOS_INT || \
           op == _GUARD_NOS_INT || op == _GUARD_NOS_LIST) { pc++; } \
} while (0)
        if (PAIR_NEXT() != _LOAD_FAST_BORROW) {
            continue;
        }
        int index_local = buffer[pc++].oparg;
        PAIR_GUARDS();
        int first = pc;
        PAIR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        if (PAIR_NEXT() != _POP_TOP_NOP) {
            continue;
        }
        int index_cleanup = pc++;
        if (PAIR_NEXT() != _POP_TOP_NOP) {
            continue;
        }
        int list_cleanup = pc++;
        if (PAIR_NEXT() != _LOAD_FAST_BORROW || buffer[pc++].oparg != list_local ||
            PAIR_NEXT() != _LOAD_FAST_BORROW || buffer[pc++].oparg != index_local) {
            continue;
        }
        int constant = PAIR_NEXT();
        if (constant == _LOAD_SMALL_INT && buffer[pc].oparg == 1) {
            pc++;
        }
        else if (constant == _LOAD_CONST_INLINE_BORROW &&
                 (PyObject *)buffer[pc].operand0 == _PyLong_GetOne()) {
            pc++;
        }
        else {
            continue;
        }
        PAIR_GUARDS();
        PAIR_EXPECT(_BINARY_OP_ADD_INT);
        PAIR_EXPECT(_POP_TOP_NOP);
        PAIR_EXPECT(_POP_TOP_NOP);
        PAIR_GUARDS();
        PAIR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        int cleanup = PAIR_NEXT();
        if (cleanup != _POP_TOP_INT && cleanup != _POP_TOP_NOP) {
            continue;
        }
        pc++;
        PAIR_EXPECT(_POP_TOP_NOP);
        int compare = PAIR_NEXT();
        if (compare != _COMPARE_TUPLE_PAIR && compare != _COMPARE_TUPLE_PAIR_0 &&
            compare != _COMPARE_TUPLE_PAIR_1) {
            continue;
        }
        int operation = buffer[pc].oparg;
        uint64_t tuple_local = buffer[pc++].operand0;
        for (int i = 0; i < 2; i++) {
            int pop = PAIR_NEXT();
            if (pop != _POP_TOP && pop != _POP_TOP_NOP) {
                goto next_pair;
            }
            pc++;
        }
        /* Both list/index reads remain borrowed locals. No effects or stores
         * occur between the first subscript and the final tuple cleanup. The
         * replacement checks both indices before comparison, including when
         * the first elements differ, and exits at the original first lookup. */
        buffer[first].opcode = _COMPARE_LIST_PAIR;
        buffer[first].oparg = operation;
        buffer[first].operand0 = tuple_local;
        for (int i = first + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[index_cleanup].opcode = _POP_TOP_NOP;
        buffer[list_cleanup].opcode = _POP_TOP_NOP;
        start = pc - 1;
next_pair:
        ;
#undef PAIR_GUARDS
#undef PAIR_EXPECT
#undef PAIR_NEXT
    }
}

/* Read original bytecode operations, including an attached executor's saved
 * instruction. Offsets and cache sizes are in code units. */
static bool
pair_scan_instruction(PyCodeObject *code, int *pc, int *opcode, int *oparg)
{
    unsigned int arg = 0;
    int units = (int)Py_SIZE(code);
    for (int n = 0; n < 4 && *pc < units && *pc >= 0; n++) {
        _Py_CODEUNIT inst = _PyCode_CODE(code)[(*pc)++];
        int op = inst.op.code;
        unsigned int low = inst.op.arg;
        if (op == ENTER_EXECUTOR) {
            _PyExecutorObject *ex = code->co_executors->executors[low];
            op = ex->vm_data.opcode;
            low = ex->vm_data.oparg;
        }
        arg = (arg << 8) | low;
        if (op == EXTENDED_ARG) {
            continue;
        }
        op = _PyOpcode_Deopt[op];
        *pc += _PyOpcode_Caches[op];
        if (*pc > units || arg > INT_MAX) {
            return false;
        }
        *opcode = op;
        *oparg = (int)arg;
        return true;
    }
    return false;
}

/* Side traces can start after the header. Prove that their backedge repeats
 * exactly `index < global_name(source) - 1`, followed by this same pair read.
 * The uop checks that global_name still resolves to the canonical len. */
static int
pair_scan_len_name(PyCodeObject *code, int edge, int body,
                   int index_local, int list_local)
{
    int pc = edge, opcode, arg;
#define HEADER_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &opcode, &arg) || opcode != (OP)) return -1; \
} while (0)
    HEADER_READ(JUMP_BACKWARD);
    pc -= arg;
    HEADER_READ(LOAD_FAST_BORROW);
    if (arg != index_local) return -1;
    HEADER_READ(LOAD_GLOBAL);
    if (!(arg & 1)) return -1;
    int name = arg >> 1;
    HEADER_READ(LOAD_FAST_BORROW);
    if (arg != list_local) return -1;
    HEADER_READ(CALL);
    if (arg != 1) return -1;
    HEADER_READ(LOAD_SMALL_INT);
    if (arg != 1) return -1;
    HEADER_READ(BINARY_OP);
    if (arg != NB_SUBTRACT) return -1;
    HEADER_READ(COMPARE_OP);
    if (arg != ((Py_LT << 5) | 16 | 2)) return -1;
    HEADER_READ(POP_JUMP_IF_FALSE);
    if (pc < body) {
        HEADER_READ(NOT_TAKEN);
    }
    return pc == body ? name : -1;
#undef HEADER_READ
}

static void
inline_list_pair_append_scan(_PyThreadStateImpl *tstate,
                             _PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    PyCodeObject *code = (PyCodeObject *)tstate->jit_tracer_state->initial_state.func->func_code;
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode == _PUSH_FRAME || buffer[start].opcode == _RETURN_VALUE) {
            /* All instruction offsets below must belong to the root frame. */
            return;
        }
        if (region_opcode(&buffer[start]) != _LOAD_FAST_BORROW) {
            continue;
        }
        int list_local = buffer[start].oparg;
        int end = Py_MIN(start + 96, length);
        int pc = start + 1;
#define APPEND_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                       pc < end ? region_opcode(&buffer[pc]) : -1)
#define APPEND_EXPECT(OP) do { \
    if (APPEND_NEXT() != (OP)) goto next_append_scan; \
    pc++; \
} while (0)
#define APPEND_LOCAL(LOCAL) do { \
    if (APPEND_NEXT() != _LOAD_FAST_BORROW || buffer[pc++].oparg != (LOCAL)) \
        goto next_append_scan; \
} while (0)
        if (APPEND_NEXT() != _LOAD_FAST_BORROW) continue;
        int index_local = buffer[pc++].oparg;
        if (APPEND_NEXT() == _GUARD_TOS_INT) pc++;
        int scan = pc;
        APPEND_EXPECT(_GUARD_NOS_LIST);
        if (APPEND_NEXT() != _COMPARE_LIST_PAIR || buffer[pc].oparg != 0) continue;
        int pair_local = (int)buffer[pc++].operand0;
        APPEND_EXPECT(_POP_TOP_NOP);
        APPEND_EXPECT(_POP_TOP_NOP);
        int op = APPEND_NEXT();
        if (pc >= end) continue;
        if (op != _GUARD_IS_FALSE_POP) {
            int bit = buffer[pc].oparg;
            if ((op != _GUARD_BIT_IS_SET_POP && op != _GUARD_BIT_IS_UNSET_POP) ||
                bit != get_test_bit_for_bools() ||
                ((test_bit_set_in_true(bit) != 0) == (op == _GUARD_BIT_IS_SET_POP))) {
                continue;
            }
        }
        pc++;
        if (APPEND_NEXT() != _LOAD_FAST_BORROW) continue;
        int output_local = buffer[pc++].oparg;
        APPEND_EXPECT(_GUARD_TYPE_VERSION);
        if (APPEND_NEXT() != _LOAD_CONST_INLINE_BORROW ||
            buffer[pc++].operand0 != (uintptr_t)tstate->base.interp->callable_cache.list_append ||
            APPEND_NEXT() != _SWAP || buffer[pc++].oparg != 2) {
            continue;
        }
        APPEND_LOCAL(list_local);
        APPEND_LOCAL(index_local);
        if (APPEND_NEXT() == _GUARD_TOS_INT) pc++;
        if (APPEND_NEXT() == _GUARD_NOS_LIST) pc++;
        APPEND_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        APPEND_EXPECT(_POP_TOP_NOP);
        APPEND_EXPECT(_POP_TOP_NOP);
        if (APPEND_NEXT() != _CALL_LIST_APPEND || buffer[pc++].oparg != 1) continue;
        APPEND_EXPECT(_POP_TOP_NOP);
        APPEND_EXPECT(_POP_TOP);
        APPEND_EXPECT(_POP_TOP_NOP);
        APPEND_LOCAL(index_local);
        op = APPEND_NEXT();
        if (op == _LOAD_SMALL_INT && buffer[pc].oparg == 1) pc++;
        else if (op == _LOAD_CONST_INLINE_BORROW &&
                 buffer[pc].operand0 == (uintptr_t)_PyLong_GetOne()) pc++;
        else continue;
        if (APPEND_NEXT() == _GUARD_TOS_INT) pc++;
        if (APPEND_NEXT() == _GUARD_NOS_INT) pc++;
        APPEND_EXPECT(_BINARY_OP_ADD_INT);
        APPEND_EXPECT(_POP_TOP_NOP);
        APPEND_EXPECT(_POP_TOP_NOP);
        if (APPEND_NEXT() != _SWAP_FAST || buffer[pc++].oparg != index_local) continue;
        op = APPEND_NEXT();
        if (op != _POP_TOP_INT && op != _POP_TOP_NOP) continue;
        pc++;
        op = APPEND_NEXT();
        if (op != _EXIT_TRACE && op != _JUMP_TO_TOP) continue;
        int edge = op == _EXIT_TRACE ? buffer[pc].target : buffer[0].target;
        int name = pair_scan_len_name(code, edge, buffer[start].target,
                                      index_local, list_local);
        int locals[] = {index_local, list_local, output_local, pair_local};
        if (name < 0 || name >= PyTuple_GET_SIZE(code->co_names) ||
            !PyUnicode_CheckExact(PyTuple_GET_ITEM(code->co_names, name))) continue;
        for (int i = 0; i < 4; i++) {
            if (locals[i] < 0 || locals[i] > 255) goto next_append_scan;
            for (int j = 0; j < i; j++) {
                if (locals[i] == locals[j]) goto next_append_scan;
            }
        }
        buffer[scan].opcode = _LIST_PAIR_APPEND_SCAN;
        buffer[scan].oparg = 0;
        buffer[scan].operand0 = index_local | ((uint64_t)list_local << 8) |
            ((uint64_t)output_local << 16) | ((uint64_t)pair_local << 24);
        buffer[scan].operand1 = name;
        start = pc;
next_append_scan:
        ;
#undef APPEND_LOCAL
#undef APPEND_EXPECT
#undef APPEND_NEXT
    }
}

static void
fuse_list_length_predicates(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _BINARY_OP_SUBSCR_LIST_INT) {
            continue;
        }
        int end = Py_MIN(length, start + 32);
        int pc = start + 1;
        for (int i = 0; i < 2; i++) {
            pc = trivial_call_skip(buffer, pc, end);
            if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                              buffer[pc].opcode != _POP_TOP_NOP)) {
                goto next_list_length;
            }
            pc++;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _CALL_LEN_CONSUMER ||
            !(buffer[pc].oparg & 16)) {
            continue;
        }
        int comparison = buffer[pc].oparg;
        uint64_t right = buffer[pc++].operand0;
        for (int i = 0; i < 2; i++) {
            pc = trivial_call_skip(buffer, pc, end);
            if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                              buffer[pc].opcode != _POP_TOP_NOP)) {
                goto next_list_length;
            }
            pc++;
        }
        buffer[start].opcode = _LEN_SUBSCR_LIST;
        buffer[start].oparg = comparison;
        buffer[start].operand0 = right;
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_list_length:
        ;
    }
}

static void
fuse_dict_pair_increments(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _BINARY_OP_SUBSCR_DICT) {
            continue;
        }
        /* A side trace starting at a failed subscription must retain ordinary
         * lookup instead of immediately repeating this guard. Require the
         * original augmented assignment's two operand copies in this trace. */
        int copies = 0;
        for (int p = start - 1; p >= 0 && p >= start - 12; p--) {
            int op = region_opcode(&buffer[p]);
            if (op == _NOP || op == _SET_IP || op == _CHECK_VALIDITY ||
                op == _GUARD_NOS_TYPE || op == _GUARD_NOS_DICT_SUBSCRIPT ||
                (_PyUop_Flags[buffer[p].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                continue;
            }
            if (op != _COPY || buffer[p].oparg != 2) {
                break;
            }
            if (++copies == 2) {
                break;
            }
        }
        if (copies != 2) {
            continue;
        }
        int end = Py_MIN(length, start + 40);
        int pc = start + 1;
#define DICT_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                     pc < end ? region_opcode(&buffer[pc]) : 0)
        for (int i = 0; i < 2; i++) {
            int op = DICT_NEXT();
            if (op != _POP_TOP && op != _POP_TOP_NOP) {
                goto next_dict_pair;
            }
            pc++;
        }
        int op = DICT_NEXT();
        unsigned int addend;
        if (op == _LOAD_SMALL_INT) {
            addend = buffer[pc++].oparg;
        }
        else if (op == _LOAD_CONST_INLINE_BORROW) {
            PyObject *value = (PyObject *)buffer[pc++].operand0;
            if (!PyLong_CheckExact(value) || !_PyLong_IsCompact((PyLongObject *)value)) {
                continue;
            }
            addend = (unsigned int)_PyLong_CompactValue((PyLongObject *)value);
        }
        else {
            continue;
        }
        if (addend > UINT16_MAX) {
            continue;
        }
        while ((op = DICT_NEXT()) == _GUARD_TOS_INT || op == _GUARD_NOS_INT) {
            pc++;
        }
        if (DICT_NEXT() != _BINARY_OP_ADD_INT) {
            continue;
        }
        uint32_t add_target = buffer[pc++].target;
        for (int i = 0; i < 2; i++) {
            op = DICT_NEXT();
            if (op != _POP_TOP_INT && op != _POP_TOP_NOP) {
                goto next_dict_pair;
            }
            pc++;
        }
        if (DICT_NEXT() != _SWAP || buffer[pc++].oparg != 3 ||
            DICT_NEXT() != _SWAP || buffer[pc++].oparg != 2) {
            continue;
        }
        if (DICT_NEXT() != _STORE_SUBSCR_DICT_INHERITED || buffer[pc].operand0 == 0) {
            continue;
        }
        uint32_t store_target = buffer[pc].target;
        uint32_t first_target = buffer[start].target;
        if (add_target < first_target || store_target < add_target ||
            store_target - first_target > UINT16_MAX) {
            continue;
        }
        buffer[start].opcode = _DICT_PAIR_INCREMENT;
        buffer[start].oparg = addend;
        buffer[start].operand0 = buffer[pc].operand0 |
            ((uint64_t)(add_target - first_target) << 32) |
            ((uint64_t)(store_target - first_target) << 48);
        for (int i = start + 1; i <= pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc;
next_dict_pair:
        ;
#undef DICT_NEXT
    }
}

static void
inline_enumerate_list(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    for (int pc = 0; pc < length; pc++) {
        if (buffer[pc].opcode != _GUARD_TYPE_ITER ||
            buffer[pc].operand0 != (uintptr_t)&PyEnum_Type) {
            continue;
        }
        int end = Py_MIN(pc + 8, length);
        int next = region_skip(buffer, pc + 1, end);
        if (next >= end || buffer[next].opcode != _ITER_NEXT_INLINE ||
            buffer[next].operand0 != (uintptr_t)PyEnum_Type.tp_iternext) {
            continue;
        }
        /* The guard exits at FOR_ITER. The original next uop instead exits
         * after END_FOR; an unsupported inner iterator must not use that exit. */
        buffer[pc].opcode = _GUARD_ENUM_LIST;
        buffer[next].opcode = _ITER_NEXT_ENUM_LIST;
        /* Normal exhaustion keeps next's after-END_FOR target; exceptions
         * need the original FOR_ITER location instead. */
        buffer[next].operand0 = buffer[pc].target;
    }
}

/* Skip a bounded sequence of iterations that only unpack enumerate, read an
 * integer tuple field, and compare it with an unchanged local. Keep the
 * original iteration for the first different branch or unsupported value. */
static void
inline_enumerate_int_scan(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    int end = Py_MIN(length, 64);
    int pc = 0;
#define SCAN_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                    pc < end ? region_opcode(&buffer[pc]) : -1)
#define SCAN_EXPECT(OP) do { \
    if (SCAN_NEXT() != (OP)) return; \
    pc++; \
} while (0)
    SCAN_EXPECT(_START_EXECUTOR);
    SCAN_EXPECT(_MAKE_WARM);
    SCAN_EXPECT(_CHECK_PERIODIC);
    if (SCAN_NEXT() != _GUARD_ENUM_LIST) {
        return;
    }
    int start = pc++;
    SCAN_EXPECT(_ITER_NEXT_ENUM_LIST);
    if (SCAN_NEXT() != _GUARD_TOS_TUPLE || buffer[pc++].oparg != 2) {
        return;
    }
    SCAN_EXPECT(_UNPACK_SEQUENCE_TWO_TUPLE);
    if (SCAN_NEXT() != _SWAP_FAST) {
        return;
    }
    int index_local = buffer[pc++].oparg;
    SCAN_EXPECT(_POP_TOP);
    if (SCAN_NEXT() != _SWAP_FAST) {
        return;
    }
    int item_local = buffer[pc++].oparg;
    SCAN_EXPECT(_POP_TOP);
    if (SCAN_NEXT() != _LOAD_FAST_BORROW ||
        buffer[pc++].oparg != item_local) {
        return;
    }
    int field;
    int op = SCAN_NEXT();
    if (op == _LOAD_SMALL_INT) {
        field = buffer[pc++].oparg;
    }
    else if (op == _LOAD_CONST_INLINE_BORROW) {
        PyObject *constant = (PyObject *)buffer[pc++].operand0;
        if (!PyLong_CheckExact(constant) || !_PyLong_IsCompact((PyLongObject *)constant)) {
            return;
        }
        Py_ssize_t value = _PyLong_CompactValue((PyLongObject *)constant);
        if (value < 0 || value > UINT16_MAX) {
            return;
        }
        field = (int)value;
    }
    else {
        return;
    }
    SCAN_EXPECT(_GUARD_NOS_TUPLE);
    SCAN_EXPECT(_GUARD_BINARY_OP_SUBSCR_TUPLE_INT_BOUNDS);
    SCAN_EXPECT(_BINARY_OP_SUBSCR_TUPLE_INT);
    SCAN_EXPECT(_POP_TOP_NOP);
    SCAN_EXPECT(_POP_TOP_NOP);
    if (SCAN_NEXT() != _LOAD_FAST_BORROW) {
        return;
    }
    int key_local = buffer[pc++].oparg;
    while ((op = SCAN_NEXT()) == _GUARD_TOS_INT || op == _GUARD_NOS_INT) {
        pc++;
    }
    if (SCAN_NEXT() != _COMPARE_OP_INT) {
        return;
    }
    int mask = buffer[pc++].oparg & 14;
    SCAN_EXPECT(_POP_TOP_NOP);
    SCAN_EXPECT(_POP_TOP_INT);
    op = SCAN_NEXT();
    bool on_true;
    if (op == _GUARD_IS_TRUE_POP || op == _GUARD_IS_FALSE_POP) {
        on_true = op == _GUARD_IS_TRUE_POP;
    }
    else if (op == _GUARD_BIT_IS_SET_POP || op == _GUARD_BIT_IS_UNSET_POP) {
        int bit = buffer[pc].oparg;
        if (bit != get_test_bit_for_bools()) {
            return;
        }
        on_true = (test_bit_set_in_true(bit) != 0) == (op == _GUARD_BIT_IS_SET_POP);
    }
    else {
        return;
    }
    pc++;
    SCAN_EXPECT(_JUMP_TO_TOP);
    if (index_local > 255 || item_local > 255 || key_local > 255 ||
        index_local == item_local || key_local == index_local || key_local == item_local) {
        return;
    }
    mask = on_true ? mask : mask ^ 14;
    int comparison;
    switch (mask) {
        case 2: comparison = Py_LT; break;
        case 10: comparison = Py_LE; break;
        case 8: comparison = Py_EQ; break;
        case 6: comparison = Py_NE; break;
        case 4: comparison = Py_GT; break;
        case 12: comparison = Py_GE; break;
        default: return;
    }
    buffer[start].opcode = _ENUM_LIST_INT_SCAN;
    buffer[start].oparg = comparison;
    buffer[start].operand0 = key_local | ((uint64_t)index_local << 8) |
                            ((uint64_t)item_local << 16);
    buffer[start].operand1 = field;
#undef SCAN_EXPECT
#undef SCAN_NEXT
}

//  0 - failure, no error raised, just fall back to Tier 1
// -1 - failure, and raise error
//  > 0 - length of optimized trace
int
_Py_uop_analyze_and_optimize(
    _PyThreadStateImpl *tstate,
    _PyUOpInstruction *buffer,
    int length,
    int curr_stacklen,
    _PyUOpInstruction *output,
    _PyBloomFilter *dependencies
)
{
    OPT_STAT_INC(optimizer_attempts);

    annotate_attribute_versions(buffer, length);
    lower_bounded_int_regions(buffer, length);
    lower_int_regions(buffer, length);
    lower_len_regions(buffer, length);
    lower_tuple_comparisons(buffer, length);
    length = optimize_uops(
        tstate, buffer, length, curr_stacklen, output, dependencies);

    if (length == 0) {
        return length;
    }

    assert(length > 0);

    eliminate_trivial_frames(output, length);
    inline_list_attribute_calls(output, length);
    inline_attribute_initializers(output, length);
    fuse_list_pair_comparisons(output, length);
    inline_list_pair_append_scan(tstate, output, length);
    fuse_list_length_predicates(output, length);
    fuse_dict_pair_increments(output, length);
    inline_enumerate_list(output, length);
    inline_enumerate_int_scan(output, length);
    length = remove_unneeded_uops(output, length);
    assert(length > 0);
    fuse_float_product_updates(output, length);

    OPT_STAT_INC(optimizer_successes);
    return length;
}

#endif /* _Py_TIER2 */
