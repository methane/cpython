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
#include "pycore_intrinsics.h"
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
    bool value_only = event == PyDict_EVENT_MODIFIED && key != NULL && PyUnicode_CheckExact(key);
    Py_hash_t hash = value_only ? PyObject_Hash(key) : 0;
    assert(!value_only || hash != -1);
    bool keep_watch = _Py_Executors_InvalidateGlobalDependency(
        _PyInterpreterState_GET(), dict, hash, value_only);
    if (get_mutations(dict) < _Py_MAX_ALLOWED_GLOBALS_MODIFICATIONS) {
        increment_mutations(dict);
    }
    if (!keep_watch) {
        PyDict_Unwatch(GLOBALS_WATCHER_ID, dict);
    }
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
get_exact_python_subtract(bool enabled, PyTypeObject *lhs_type,
                          PyTypeObject *rhs_type,
                          _PyBloomFilter *dependencies)
{
    if (!enabled || lhs_type == NULL || lhs_type != rhs_type ||
        lhs_type->tp_version_tag == 0 ||
        !_PyType_HasSlotNbSubtract(lhs_type)) {
        return NULL;
    }
    PyObject *method = PyDict_GetItemWithError(
        _PyType_GetDict(lhs_type), &_Py_ID(__sub__));
    if (method == NULL) {
        PyErr_Clear();
        return NULL;
    }
    if (!PyFunction_Check(method)) {
        return NULL;
    }
    PyFunctionObject *func = (PyFunctionObject *)method;
    PyCodeObject *code = (PyCodeObject *)func->func_code;
    if (!_PyFunction_IsVersionValid(func->func_version) ||
        code->co_argcount != 2 || code->co_kwonlyargcount != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return NULL;
    }
    watch_type(lhs_type, dependencies);
    _Py_BloomFilter_Add(dependencies, method);
    return method;
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

static bool
code_stores_global(PyCodeObject *code)
{
    int units = (int)Py_SIZE(code);
    for (int pc = 0; pc < units;) {
        _Py_CODEUNIT inst = _Py_GetBaseCodeUnit(code, pc);
        int opcode = inst.op.code;
        pc += 1 + _PyOpcode_Caches[opcode];
        if (opcode == STORE_GLOBAL) {
            return true;
        }
    }
    return false;
}

static bool
namespace_has_global_writer(PyObject *globals)
{
    assert(PyDict_CheckExact(globals));
    Py_ssize_t pos = 0;
    PyObject *key, *value;
    while (PyDict_Next(globals, &pos, &key, &value)) {
        if (PyFunction_Check(value)) {
            PyFunctionObject *function = (PyFunctionObject *)value;
            if (function->func_globals == globals &&
                code_stores_global((PyCodeObject *)function->func_code))
            {
                return true;
            }
        }
        if (!PyType_Check(value)) {
            continue;
        }
        PyObject *type_dict = _PyType_GetDict((PyTypeObject *)value);
        Py_ssize_t type_pos = 0;
        PyObject *member_name, *member;
        while (PyDict_Next(type_dict, &type_pos, &member_name, &member)) {
            if (PyFunction_Check(member)) {
                PyFunctionObject *function = (PyFunctionObject *)member;
                if (function->func_globals == globals &&
                    code_stores_global((PyCodeObject *)function->func_code))
                {
                    return true;
                }
            }
        }
    }
    return false;
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
trivial_attribute_load_with_type(_PyUOpInstruction *buffer, int pc, int end,
                                 int nargs, uint64_t *descriptor,
                                 PyTypeObject **recorded_type)
{
    if (recorded_type != NULL) {
        *recorded_type = NULL;
    }
    pc = trivial_call_skip(buffer, pc, end);
    if (pc >= end || (region_opcode(&buffer[pc]) != _LOAD_FAST &&
                     region_opcode(&buffer[pc]) != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg > nargs) {
        return -1;
    }
    int arg = buffer[pc++].oparg;
    while (pc < end) {
        int next = region_skip(buffer, pc, end);
        if (next >= end ||
            !(_PyUop_Flags[buffer[next].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            pc = next;
            break;
        }
        if (recorded_type != NULL) {
            if (buffer[next].opcode == _RECORD_TOS_TYPE) {
                *recorded_type = (PyTypeObject *)buffer[next].operand0;
            }
            else if (buffer[next].opcode == _RECORD_TOS &&
                     buffer[next].operand0 != 0) {
                *recorded_type = Py_TYPE((PyObject *)buffer[next].operand0);
            }
        }
        pc = next + 1;
    }
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

static int
trivial_attribute_load(_PyUOpInstruction *buffer, int pc, int end,
                       int nargs, uint64_t *descriptor)
{
    return trivial_attribute_load_with_type(
        buffer, pc, end, nargs, descriptor, NULL);
}

/* Keep the callee frame and replace only the straight-line arithmetic.
 * A single guarded layout covers both owners and all six attribute loads.
 * No calls, stores, periodic checks, or frame transitions may be skipped. */
static void
fuse_float_attribute_products(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_FLOAT_FUSION")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        int opcode = region_opcode(&buffer[start]);
        if (opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) {
            continue;
        }
        int end = Py_MIN(length, start + 128);
        int pc = start;
        uint64_t fields = 0;
        uint64_t common = 0;
        unsigned int owners[2] = {0, 0};
        uint32_t add_target = 0;
#define FLOAT_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                      pc < end ? buffer[pc].opcode : 0)
        for (int product = 0; product < 3; product++) {
            for (int side = 0; side < 2; side++) {
                uint64_t descriptor;
                pc = trivial_attribute_load(buffer, pc, end, 7, &descriptor);
                if (pc < 0) {
                    goto next_float_attributes;
                }
                uint64_t offset = (descriptor >> 3) & UINT16_MAX;
                if (offset % sizeof(PyObject *) || offset / sizeof(PyObject *) > UINT8_MAX) {
                    goto next_float_attributes;
                }
                if (product == 0) {
                    owners[side] = descriptor & 7;
                    if (side == 0) {
                        common = descriptor >> 19;
                    }
                }
                if ((descriptor >> 19) != common || (descriptor & 7) != owners[side]) {
                    goto next_float_attributes;
                }
                fields |= (offset / sizeof(PyObject *)) << (8 * (2 * product + side));
            }
            int op;
            while ((op = FLOAT_NEXT()) == _GUARD_TOS_FLOAT || op == _GUARD_NOS_FLOAT) {
                pc++;
            }
            if (FLOAT_NEXT() != _BINARY_OP_MULTIPLY_FLOAT) {
                goto next_float_attributes;
            }
            pc++;
            for (int i = 0; i < 2; i++) {
                op = FLOAT_NEXT();
                if (op != _POP_TOP_FLOAT && op != _POP_TOP_NOP) {
                    goto next_float_attributes;
                }
                pc++;
            }
            if (product != 0) {
                while ((op = FLOAT_NEXT()) == _GUARD_NOS_FLOAT) {
                    pc++;
                }
                if (FLOAT_NEXT() != _BINARY_OP_ADD_FLOAT_INPLACE) {
                    goto next_float_attributes;
                }
                add_target = buffer[pc++].target;
                if (FLOAT_NEXT() != _POP_TOP_FLOAT) {
                    goto next_float_attributes;
                }
                pc++;
                if (FLOAT_NEXT() != _POP_TOP_NOP) {
                    goto next_float_attributes;
                }
                pc++;
            }
        }
        if (!common || add_target > UINT16_MAX || add_target < buffer[start].target) {
            continue;
        }
        buffer[start].opcode = _FLOAT_ATTRIBUTE_SUM_PRODUCTS;
        buffer[start].oparg = 0;
        buffer[start].operand0 = fields;
        /* Use an absolute code-unit offset: the original LOAD_FAST did not
         * need a SET_IP, so frame->instr_ptr may precede the region entry. */
        buffer[start].operand1 = owners[0] | ((uint64_t)owners[1] << 3) |
                                (common << 6) | ((uint64_t)add_target << 39);
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_float_attributes:
        ;
#undef FLOAT_NEXT
    }
}

/* Unlike the general call matcher, this peephole must not cross a validity
 * guard: that guard's exit still expects the original intermediate stack. */
static int
folded_constant_skip(const _PyUOpInstruction *buffer, int pc, int end)
{
    while (pc < end && (buffer[pc].opcode == _NOP || buffer[pc].opcode == _SET_IP ||
            (_PyUop_Flags[buffer[pc].opcode] & HAS_RECORDS_VALUE_FLAG))) {
        pc++;
    }
    return pc;
}

static int
remove_folded_constant_traffic(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS") &&
        !region_enabled("PYTHON_TIER2_INT_REGIONS") &&
        !region_enabled("PYTHON_TIER2_CALL_REGIONS")) {
        return length;
    }
    length = remove_unneeded_uops(buffer, length);
    /* The general push/pop table does not include the short-local replicas.
     * Closing the just-loaded reference cannot finalize a still-owned local;
     * no callback, store, guard, or periodic check can intervene here. */
    for (int start = 0; start < length; start++) {
        int op = region_opcode(&buffer[start]);
        if (op != _LOAD_FAST && op != _LOAD_FAST_BORROW) {
            continue;
        }
        int pop = folded_constant_skip(buffer, start + 1, length);
        if (pop < length && op_without_pop[buffer[pop].opcode]) {
            buffer[start].opcode = buffer[pop].opcode = _NOP;
        }
    }
    length = remove_unneeded_uops(buffer, length);
    int loads[3];
    int count = 0;
    for (int pc = 0; pc < length; pc++) {
        pc = folded_constant_skip(buffer, pc, length);
        if (pc == length) break;
        int op = buffer[pc].opcode;
        if (op == _LOAD_CONST_INLINE || op == _LOAD_CONST_INLINE_BORROW ||
            op == _LOAD_SMALL_INT) {
            if (count == 3) {
                loads[0] = loads[1];
                loads[1] = loads[2];
                count--;
            }
            loads[count++] = pc;
            continue;
        }
        if (op == _RROT_3 && count == 3) {
            int first_pop = folded_constant_skip(buffer, pc + 1, length);
            int second_pop = folded_constant_skip(buffer, first_pop + 1, length);
            bool valid = second_pop < length &&
                op_without_pop[buffer[first_pop].opcode] &&
                op_without_pop[buffer[second_pop].opcode];
            for (int i = 0; i < 2 && valid; i++) {
                _PyUOpInstruction *load = &buffer[loads[i]];
                valid = load->opcode == _LOAD_SMALL_INT ||
                        _Py_IsImmortal((PyObject *)load->operand0);
            }
            if (valid) {
                /* Folding left the result above its two old operands. The
                 * operands are immortal, so only the result load is needed. */
                buffer[loads[0]].opcode = buffer[loads[1]].opcode = _NOP;
                buffer[pc].opcode = _NOP;
                buffer[first_pop].opcode = buffer[second_pop].opcode = _NOP;
                loads[0] = loads[2];
                count = 1;
                pc = second_pop;
                continue;
            }
        }
        count = 0;
    }
    return length;
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

/* Fuse the complete recorded path of a conditional attribute return. Every
 * failure resumes at the original CALL, before argument ownership changes. */
static void
inline_conditional_attribute_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS || buffer[start].oparg > 4) {
            continue;
        }
        /* Retain the code-version guard. MAKE_FUNCTION can give distinct
         * functions the same version, so a folded globals guard also needs
         * an explicit check of the actual callee's namespace. */
        int guard = start - 1;
        while (guard >= 0 && (buffer[guard].opcode == _NOP ||
               buffer[guard].opcode == _CHECK_RECURSION_REMAINING ||
               buffer[guard].opcode == _CHECK_STACK_SPACE_OPERAND)) {
            guard--;
        }
        if (guard < 0 || buffer[guard].opcode != _CHECK_FUNCTION_VERSION ||
            buffer[guard].operand0 == 0) {
            continue;
        }
        int end = Py_MIN(length, start + 96);
        int pc = start + 1;
#define CONDITIONAL_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                            pc < end ? region_opcode(&buffer[pc]) : -1)
#define CONDITIONAL_EXPECT(OP) do { \
    if (CONDITIONAL_NEXT() != (OP)) goto next_conditional; \
    pc++; \
} while (0)
        if (CONDITIONAL_NEXT() != _SAVE_RETURN_OFFSET) {
            continue;
        }
        int call_slot = pc++;
        CONDITIONAL_EXPECT(_PUSH_FRAME);
        CONDITIONAL_EXPECT(_TIER2_RESUME_CHECK);
        uint64_t selector, result;
        pc = trivial_attribute_load(buffer, pc, end, buffer[start].oparg, &selector);
        if (pc < 0) {
            continue;
        }
        PyObject *namespace = NULL;
        int op = CONDITIONAL_NEXT();
        if (op == _GUARD_GLOBALS_VERSION_AND_IDENTITY) {
            namespace = (PyObject *)buffer[pc].operand1;
            if (namespace == NULL) {
                continue;
            }
            pc++;
            op = CONDITIONAL_NEXT();
        }
        /* Folding a class attribute can leave its watched owner load/pop.
         * No escaping operation occurs between them. Retain all previously
         * registered dict/type dependencies protecting the folded value. */
        if (op == _LOAD_CONST_INLINE && PyType_Check((PyObject *)buffer[pc].operand0)) {
            pc++;
            CONDITIONAL_EXPECT(_POP_TOP);
            op = CONDITIONAL_NEXT();
        }
        Py_ssize_t constant;
        if (op == _LOAD_SMALL_INT) {
            constant = buffer[pc++].oparg;
        }
        else if (op == _LOAD_CONST_INLINE_BORROW) {
            PyObject *value = (PyObject *)buffer[pc++].operand0;
            if (!PyLong_CheckExact(value) || !_Py_IsImmortal(value) ||
                !_PyLong_IsCompact((PyLongObject *)value)) {
                continue;
            }
            constant = _PyLong_CompactValue((PyLongObject *)value);
        }
        else {
            continue;
        }
        if (constant < INT8_MIN || constant > INT8_MAX) {
            continue;
        }
        while ((op = CONDITIONAL_NEXT()) == _GUARD_NOS_INT || op == _GUARD_TOS_INT) {
            pc++;
        }
        if (CONDITIONAL_NEXT() != _COMPARE_OP_INT) {
            continue;
        }
        int mask = buffer[pc++].oparg & 14;
        for (int i = 0; i < 2; i++) {
            op = CONDITIONAL_NEXT();
            if (op != _POP_TOP_INT && op != _POP_TOP_NOP) {
                goto next_conditional;
            }
            pc++;
        }
        op = CONDITIONAL_NEXT();
        bool on_true;
        if (op == _GUARD_IS_TRUE_POP || op == _GUARD_IS_FALSE_POP) {
            on_true = op == _GUARD_IS_TRUE_POP;
        }
        else if (op == _GUARD_BIT_IS_SET_POP || op == _GUARD_BIT_IS_UNSET_POP) {
            int bit = buffer[pc].oparg;
            if (bit != get_test_bit_for_bools()) {
                continue;
            }
            on_true = (test_bit_set_in_true(bit) != 0) == (op == _GUARD_BIT_IS_SET_POP);
        }
        else {
            continue;
        }
        pc++;
        mask = on_true ? mask : mask ^ 14;
        pc = trivial_attribute_load(buffer, pc, end, buffer[start].oparg, &result);
        if (pc < 0) {
            continue;
        }
        if (CONDITIONAL_NEXT() == _MAKE_HEAP_SAFE) {
            pc++;
        }
        if (CONDITIONAL_NEXT() != _RETURN_VALUE) {
            continue;
        }
        _PyUOpInstruction call = buffer[start];
        call.opcode = _CALL_PY_ATTRIBUTE_IF;
        call.operand0 = selector | ((uint64_t)(uint8_t)constant << 52) |
                        ((uint64_t)mask << 60);
        call.operand1 = result;
        for (int i = start + 1; i <= pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        if (namespace != NULL) {
            buffer[start].opcode = _GUARD_CALL_GLOBALS_IDENTITY;
            buffer[start].operand0 = (uintptr_t)namespace;
            buffer[start].operand1 = 0;
            buffer[call_slot] = call;
        }
        else {
            buffer[start] = call;
        }
        start = pc;
next_conditional:
        ;
#undef CONDITIONAL_EXPECT
#undef CONDITIONAL_NEXT
    }
#endif
}

static int
equality_scan_expect(const _PyUOpInstruction *buffer, int pc, int end,
                     int expected)
{
    pc = trivial_call_skip(buffer, pc, end);
    if (pc >= end || region_opcode(&buffer[pc]) != expected) {
        return -1;
    }
    return pc + 1;
}

static PyTypeObject *
equality_scan_recorded_type(const _PyUOpInstruction *buffer, int start,
                            int end)
{
    PyTypeObject *result = NULL;
    for (int pc = start; pc < end; pc++) {
        if (buffer[pc].opcode != _RECORD_TOS_TYPE) {
            continue;
        }
        PyObject *recorded = (PyObject *)buffer[pc].operand0;
        if (!PyType_Check(recorded) ||
            (result != NULL && result != (PyTypeObject *)recorded)) {
            return NULL;
        }
        result = (PyTypeObject *)recorded;
    }
    return result;
}

/* The method's unique MRO key proves which instance-dict name can shadow the
 * cached function. Aliases are rejected because the optimized trace no longer
 * retains the original LOAD_ATTR name. */
static bool
equality_scan_method(PyTypeObject *type, PyObject *obj, const char *name)
{
    if (!PyFunction_Check(obj) ||
        type->tp_getattro != PyObject_GenericGetAttr ||
        !PyTuple_CheckExact(type->tp_mro)) {
        return false;
    }
    int matches = 0;
    bool named = false;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(type->tp_mro); i++) {
        PyTypeObject *base =
            (PyTypeObject *)PyTuple_GET_ITEM(type->tp_mro, i);
        PyObject *dict = base->tp_dict;
        if (dict == NULL) {
            continue;
        }
        Py_ssize_t position = 0;
        PyObject *key;
        PyObject *value;
        while (PyDict_Next(dict, &position, &key, &value)) {
            if (value == obj) {
                matches++;
                named = PyUnicode_CheckExact(key) &&
                    _PyUnicode_EqualToASCIIString(key, name);
            }
        }
    }
    return matches == 1 && named;
}

/* Match one already-fused self.input() or self.output() call. The preceding
 * function-version and globals guards remain in the trace and protect a
 * following scan until the next operation that can re-enter Python. */
static int
equality_scan_conditional_call(
    const _PyUOpInstruction *buffer,
    int pc,
    int end,
    uint32_t constraint_version,
    PyTypeObject *constraint_type,
    const char *name,
    uint64_t *selector,
    uint64_t *result)
{
    pc = trivial_call_skip(buffer, pc, end);
    if (pc >= end ||
        (region_opcode(&buffer[pc]) != _LOAD_FAST &&
         region_opcode(&buffer[pc]) != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != 0) {
        return -1;
    }
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc < end && buffer[pc].opcode == _GUARD_TYPE_VERSION) {
        if (buffer[pc].operand0 != constraint_version) {
            return -1;
        }
        pc = trivial_call_skip(buffer, pc + 1, end);
    }
    if (pc >= end ||
        buffer[pc].opcode != _CHECK_MANAGED_OBJECT_HAS_VALUES) {
        return -1;
    }
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc >= end ||
        (buffer[pc].opcode != _LOAD_CONST_INLINE &&
         buffer[pc].opcode != _LOAD_CONST_INLINE_BORROW)) {
        return -1;
    }
    PyObject *callable = (PyObject *)buffer[pc].operand0;
    if (!equality_scan_method(constraint_type, callable, name)) {
        return -1;
    }
    uint32_t function_version =
        ((PyFunctionObject *)callable)->func_version;
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc >= end || buffer[pc].opcode != _SWAP ||
        buffer[pc].oparg != 2) {
        return -1;
    }
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc >= end || buffer[pc].opcode != _CHECK_FUNCTION_VERSION ||
        function_version == 0 ||
        buffer[pc].operand0 != function_version) {
        return -1;
    }
    pc = equality_scan_expect(
        buffer, pc + 1, end, _CHECK_STACK_SPACE_OPERAND);
    if (pc < 0) {
        return -1;
    }
    pc = equality_scan_expect(
        buffer, pc, end, _CHECK_RECURSION_REMAINING);
    if (pc < 0) {
        return -1;
    }
    pc = trivial_call_skip(buffer, pc, end);
    if (pc < end && buffer[pc].opcode == _GUARD_CALL_GLOBALS_IDENTITY) {
        if (buffer[pc].operand0 == 0) {
            return -1;
        }
        pc = trivial_call_skip(buffer, pc + 1, end);
    }
    if (pc >= end || buffer[pc].opcode != _CALL_PY_ATTRIBUTE_IF ||
        buffer[pc].oparg != 0) {
        return -1;
    }
    *selector = buffer[pc].operand0;
    *result = buffer[pc].operand1;
    return pc + 1;
}

static bool
equality_scan_layout_slot(uint64_t descriptor, uint32_t version,
                          bool conditional, uint8_t *slot)
{
    uint64_t offset = (descriptor >> 3) & UINT16_MAX;
    if ((descriptor & 7) != 0 ||
        ((descriptor >> 19) & UINT32_MAX) != version ||
        ((descriptor >> 51) & 1) == 0 ||
        (!conditional && (descriptor >> 52) != 0) ||
        (offset & 7) != 0 || offset / 8 > UINT8_MAX) {
        return false;
    }
    *slot = (uint8_t)(offset / 8);
    return true;
}

/* After one complete equality-style method call, consume a bounded prefix of
 * the same exact-list iterator. This matcher keeps every guard used by the
 * normal iteration and accepts only the complete pattern
 *
 *     self.output().value = self.input().value
 *
 * with the same conditional branch in input() and output(). The scan leaves
 * the first unsupported item and the final list item for the ordinary loop. */
static void
inline_list_equality_scan(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _GUARD_TYPE_ITER ||
            buffer[start].operand0 != (uintptr_t)&PyListIter_Type) {
            continue;
        }
        int end = Py_MIN(length, start + 256);
        int pc = equality_scan_expect(
            buffer, start + 1, end, _ITER_NEXT_INLINE);
        if (pc < 0 ||
            buffer[trivial_call_skip(buffer, start + 1, end)].operand0 !=
                (uintptr_t)PyListIter_Type.tp_iternext) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _SWAP_FAST ||
            buffer[pc].oparg > UINT8_MAX) {
            continue;
        }
        uint8_t local = (uint8_t)buffer[pc].oparg;
        pc = equality_scan_expect(buffer, pc + 1, end, _POP_TOP);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end ||
            (region_opcode(&buffer[pc]) != _LOAD_FAST &&
             region_opcode(&buffer[pc]) != _LOAD_FAST_BORROW) ||
            buffer[pc].oparg != local) {
            continue;
        }
        int record_start = pc + 1;
        pc = trivial_call_skip(buffer, record_start, end);
        if (pc >= end || buffer[pc].opcode != _GUARD_TYPE_VERSION ||
            buffer[pc].operand0 == 0 || buffer[pc].operand0 > UINT32_MAX) {
            continue;
        }
        uint32_t constraint_version = (uint32_t)buffer[pc].operand0;
        PyTypeObject *constraint_type = equality_scan_recorded_type(
            buffer, record_start, pc);
        if (constraint_type == NULL ||
            constraint_type->tp_version_tag != constraint_version) {
            continue;
        }
        pc = equality_scan_expect(
            buffer, pc + 1, end, _CHECK_MANAGED_OBJECT_HAS_VALUES);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end ||
            (buffer[pc].opcode != _LOAD_CONST_INLINE &&
             buffer[pc].opcode != _LOAD_CONST_INLINE_BORROW) ||
            !equality_scan_method(
                constraint_type, (PyObject *)buffer[pc].operand0,
                "execute")) {
            continue;
        }
        PyFunctionObject *execute =
            (PyFunctionObject *)buffer[pc].operand0;
        pc = equality_scan_expect(buffer, pc + 1, end, _SWAP);
        if (pc < 0 || buffer[trivial_call_skip(buffer, pc - 1, end)].oparg != 2) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _CHECK_FUNCTION_VERSION ||
            execute->func_version == 0 ||
            buffer[pc].operand0 != execute->func_version) {
            continue;
        }
        pc = equality_scan_expect(
            buffer, pc + 1, end, _CHECK_STACK_SPACE_OPERAND);
        if (pc < 0) {
            continue;
        }
        pc = equality_scan_expect(
            buffer, pc, end, _CHECK_RECURSION_REMAINING);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _INIT_CALL_PY_EXACT_ARGS ||
            buffer[pc].oparg != 0) {
            continue;
        }
        pc = equality_scan_expect(
            buffer, pc + 1, end, _SAVE_RETURN_OFFSET);
        if (pc < 0) {
            continue;
        }
        pc = equality_scan_expect(buffer, pc, end, _PUSH_FRAME);
        if (pc < 0) {
            continue;
        }
        pc = equality_scan_expect(buffer, pc, end, _TIER2_RESUME_CHECK);
        if (pc < 0) {
            continue;
        }

        uint64_t input_selector, input_result;
        pc = equality_scan_conditional_call(
            buffer, pc, end, constraint_version, constraint_type, "input",
            &input_selector, &input_result);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _GUARD_TYPE_VERSION ||
            buffer[pc].operand0 == 0 || buffer[pc].operand0 > UINT32_MAX) {
            continue;
        }
        uint32_t value_version = (uint32_t)buffer[pc].operand0;
        pc = equality_scan_expect(
            buffer, pc + 1, end, _CHECK_MANAGED_OBJECT_HAS_VALUES);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end ||
            buffer[pc].opcode != _LOAD_ATTR_INSTANCE_VALUE ||
            (buffer[pc].operand1 & UINT32_MAX) != value_version ||
            (buffer[pc].operand1 >> 32) != 1 ||
            (buffer[pc].operand0 & 7) != 0 ||
            buffer[pc].operand0 / 8 > UINT8_MAX) {
            continue;
        }
        uint8_t value_slot = (uint8_t)(buffer[pc].operand0 / 8);
        pc = equality_scan_expect(buffer, pc + 1, end, _POP_TOP);
        if (pc < 0) {
            continue;
        }

        uint64_t output_selector, output_result;
        pc = equality_scan_conditional_call(
            buffer, pc, end, constraint_version, constraint_type, "output",
            &output_selector, &output_result);
        if (pc < 0 || output_selector != input_selector) {
            continue;
        }
        pc = equality_scan_expect(buffer, pc, end, _LOCK_OBJECT);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end ||
            buffer[pc].opcode != _GUARD_TYPE_VERSION_LOCKED ||
            buffer[pc].operand0 != value_version) {
            continue;
        }
        pc = equality_scan_expect(
            buffer, pc + 1, end, _GUARD_DORV_NO_DICT);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end ||
            buffer[pc].opcode != _STORE_ATTR_INSTANCE_VALUE ||
            buffer[pc].operand0 != (uint64_t)value_slot * 8) {
            continue;
        }
        pc = equality_scan_expect(buffer, pc + 1, end, _POP_TOP);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end ||
            buffer[pc].opcode != _LOAD_CONST_INLINE_BORROW ||
            (PyObject *)buffer[pc].operand0 != Py_None) {
            continue;
        }
        pc = equality_scan_expect(buffer, pc + 1, end, _RETURN_VALUE);
        if (pc < 0) {
            continue;
        }
        pc = trivial_call_skip(buffer, pc, end);
        if (pc >= end || buffer[pc].opcode != _POP_TOP_NOP) {
            continue;
        }
        int insertion = pc;
        if (equality_scan_expect(buffer, pc + 1, end, _JUMP_TO_TOP) < 0) {
            continue;
        }

        uint8_t selector_slot, input_slot, output_slot;
        if (input_selector >> 60 == 0 ||
            !equality_scan_layout_slot(
                input_selector, constraint_version, true, &selector_slot) ||
            !equality_scan_layout_slot(
                input_result, constraint_version, false, &input_slot) ||
            !equality_scan_layout_slot(
                output_result, constraint_version, false, &output_slot)) {
            continue;
        }
        uint64_t fields = local |
            ((uint64_t)selector_slot << 8) |
            ((uint64_t)input_slot << 16) |
            ((uint64_t)output_slot << 24) |
            ((uint64_t)value_slot << 32) |
            (((input_selector >> 52) & UINT8_MAX) << 40) |
            (((input_selector >> 60) & 15) << 48);
        buffer[insertion].opcode = _LIST_EQUALITY_SCAN;
        buffer[insertion].oparg = 0;
        buffer[insertion].operand0 = constraint_version |
            ((uint64_t)value_version << 32);
        buffer[insertion].operand1 = fields;
        start = insertion;
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
        if (LIST_NEXT() == _GUARD_GLOBALS_VERSION ||
            LIST_NEXT() == _GUARD_GLOBALS_VERSION_AND_IDENTITY) {
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
        if (pc < 0) {
            continue;
        }
        int op = LIST_NEXT();
        bool direct_length = length_predicate &&
            (op == _CALL_LEN || op == _CALL_LEN_CONSUMER);
        if (!direct_length) {
            if (LIST_NEXT() != _LOAD_FAST_BORROW || buffer[pc].oparg > nargs) {
                continue;
            }
            config |= buffer[pc++].oparg;
            while ((op = LIST_NEXT()) == _GUARD_TOS_INT || op == _GUARD_NOS_LIST) {
                pc++;
            }
            LIST_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
            for (int i = 0; i < 2; i++) {
                op = LIST_NEXT();
                if (op != _POP_TOP && op != _POP_TOP_NOP) goto next_list_call;
                pc++;
            }
        }
        if (length_predicate) {
            if (direct_length && LIST_NEXT() == _CALL_LEN) {
                pc++;
                for (int i = 0; i < 2; i++) {
                    op = LIST_NEXT();
                    if (op != _POP_TOP && op != _POP_TOP_NOP) goto next_list_call;
                    pc++;
                }
                op = LIST_NEXT();
                Py_ssize_t value;
                if (op == _LOAD_SMALL_INT) {
                    value = buffer[pc++].oparg;
                }
                else if (op == _LOAD_CONST_INLINE_BORROW || op == _LOAD_CONST_INLINE) {
                    PyObject *constant = (PyObject *)buffer[pc++].operand0;
                    if (!PyLong_CheckExact(constant) || !_PyLong_IsCompact((PyLongObject *)constant)) {
                        continue;
                    }
                    value = _PyLong_CompactValue((PyLongObject *)constant);
                }
                else continue;
                if (value < 0 || value > UINT16_MAX) continue;
                while ((op = LIST_NEXT()) == _GUARD_TOS_INT || op == _GUARD_NOS_INT ||
                       op == _GUARD_NOS_OVERFLOWED) {
                    pc++;
                }
                if (LIST_NEXT() != _COMPARE_OP_INT) continue;
                config |= ((uint64_t)(buffer[pc++].oparg & 15) << 4) |
                          ((uint64_t)value << 8);
                for (int i = 0; i < 2; i++) {
                    op = LIST_NEXT();
                    if (op != _POP_TOP_INT && op != _POP_TOP_NOP) goto next_list_call;
                    pc++;
                }
            }
            else {
                if (LIST_NEXT() != _CALL_LEN_CONSUMER ||
                    (buffer[pc].oparg & 48) != 48 || buffer[pc].operand0 > UINT16_MAX) {
                    continue;
                }
                config |= ((uint64_t)(buffer[pc].oparg & 15) << 4) |
                          (buffer[pc].operand0 << 8);
                pc++;
                for (int i = 0; i < 2; i++) {
                    op = LIST_NEXT();
                    if (op != _POP_TOP && op != _POP_TOP_NOP) goto next_list_call;
                    pc++;
                }
            }
        }
        if (LIST_NEXT() == _MAKE_HEAP_SAFE) {
            pc++;
        }
        LIST_EXPECT(_RETURN_VALUE);
        buffer[start].opcode = _CALL_PY_LIST;
        /* Separate stencils keep the direct-length branch out of indexed
         * calls. The low five replicas retain the original argument counts. */
        buffer[start].oparg = nargs + (direct_length ? 5 : 0);
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

static bool
identity_guard_body(PyCodeObject *code)
{
    if (code->co_argcount != 1 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 1 || code->co_nlocalsplus != 1 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define GUARD_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define GUARD_ARG(OP, ARG) do { GUARD_READ(OP); if (arg != (ARG)) return false; } while (0)
    GUARD_ARG(RESUME, 0);
    GUARD_ARG(LOAD_FAST_BORROW, 0);
    GUARD_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef GUARD_ARG
#undef GUARD_READ
}

/* Prove every path of the deliberately narrow vector-dot body. The call
 * fusion can then rely on the optimizer's type/function dependencies while
 * omitting both frames. */
static bool
float_dot_body(PyCodeObject *code, uint16_t *final_add)
{
    if (code->co_argcount != 2 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 2 || code->co_nlocalsplus != 2 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        Py_SIZE(code) > UINT16_MAX ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define DOT_READ_BODY(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define DOT_ARG_BODY(OP, ARG) do { \
    DOT_READ_BODY(OP); \
    if (arg != (ARG)) return false; \
} while (0)
    DOT_ARG_BODY(RESUME, 0);
    DOT_ARG_BODY(LOAD_FAST_BORROW, 1);
    DOT_READ_BODY(LOAD_ATTR);
    if (!(arg & 1) || (arg >> 1) >= PyTuple_GET_SIZE(code->co_names) ||
        !PyUnicode_CheckExact(PyTuple_GET_ITEM(code->co_names, arg >> 1))) {
        return false;
    }
    DOT_ARG_BODY(CALL, 0);
    DOT_ARG_BODY(POP_TOP, 0);
    for (int product = 0; product < 3; product++) {
        DOT_ARG_BODY(LOAD_FAST_BORROW, 0);
        DOT_READ_BODY(LOAD_ATTR);
        if ((arg & 1) || (arg >> 1) >= PyTuple_GET_SIZE(code->co_names)) {
            return false;
        }
        int attribute = arg;
        DOT_ARG_BODY(LOAD_FAST_BORROW, 1);
        DOT_ARG_BODY(LOAD_ATTR, attribute);
        DOT_ARG_BODY(BINARY_OP, NB_MULTIPLY);
        if (product != 0) {
            int add = pc;
            DOT_ARG_BODY(BINARY_OP, NB_ADD);
            *final_add = (uint16_t)add;
        }
    }
    DOT_ARG_BODY(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef DOT_ARG_BODY
#undef DOT_READ_BODY
}

static void
inline_float_dot_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS") ||
        !region_enabled("PYTHON_TIER2_FLOAT_FUSION")) {
        return;
    }
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_1) ||
            buffer[start].oparg != 1) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 16; i--) {
            int op = buffer[i].opcode;
            if (op == _RECORD_CALLABLE || op == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
        }
        uint16_t body_add;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !float_dot_body((PyCodeObject *)func->func_code, &body_add)) {
            continue;
        }
        int end = Py_MIN(length, start + 192);
        int pc = start + 1;
#define DOT_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                    pc < end ? region_opcode(&buffer[pc]) : 0)
#define DOT_EXPECT(OP) do { if (DOT_NEXT() != (OP)) goto next_dot; pc++; } while (0)
        if (DOT_NEXT() != _SAVE_RETURN_OFFSET || buffer[pc].oparg == 0) {
            continue;
        }
        uint16_t return_offset = buffer[pc++].oparg;
        DOT_EXPECT(_PUSH_FRAME);
        DOT_EXPECT(_TIER2_RESUME_CHECK);
        if (DOT_NEXT() != _LOAD_FAST_BORROW || buffer[pc].oparg != 1) {
            continue;
        }
        pc++;
        uint32_t method_type_version = 0;
        if (DOT_NEXT() == _GUARD_TYPE_VERSION) {
            if (buffer[pc].operand0 == 0 || buffer[pc].operand0 > UINT32_MAX) {
                continue;
            }
            method_type_version = (uint32_t)buffer[pc++].operand0;
        }
        DOT_EXPECT(_CHECK_MANAGED_OBJECT_HAS_VALUES);
        int op = DOT_NEXT();
        if (op != _LOAD_CONST_INLINE && op != _LOAD_CONST_INLINE_BORROW) {
            continue;
        }
        PyObject *guard_obj = (PyObject *)buffer[pc++].operand0;
        if (guard_obj == NULL || !PyFunction_Check(guard_obj)) {
            continue;
        }
        PyFunctionObject *guard = (PyFunctionObject *)guard_obj;
        PyCodeObject *guard_code = (PyCodeObject *)guard->func_code;
        if (!_PyFunction_IsVersionValid(guard->func_version) ||
            !identity_guard_body(guard_code) || guard_code->co_framesize <= 0 ||
            guard_code->co_framesize > UINT16_MAX) {
            continue;
        }
        op = DOT_NEXT();
        if ((op != _SWAP_2 && op != _SWAP) || buffer[pc].oparg != 2) {
            continue;
        }
        pc++;
        if (DOT_NEXT() != _CHECK_FUNCTION_VERSION || buffer[pc].oparg != 0 ||
            buffer[pc].operand0 != guard->func_version) {
            continue;
        }
        pc++;
        DOT_EXPECT(_CHECK_STACK_SPACE_OPERAND);
        DOT_EXPECT(_CHECK_RECURSION_REMAINING);
        op = DOT_NEXT();
        if ((op != _CALL_PY_TRIVIAL && op != _CALL_PY_TRIVIAL_0) ||
            buffer[pc].oparg != 0 || buffer[pc].operand0 != 1) {
            continue;
        }
        pc++;
        DOT_EXPECT(_POP_TOP);
        if (DOT_NEXT() != _FLOAT_ATTRIBUTE_SUM_PRODUCTS) {
            continue;
        }
        uint64_t fields = buffer[pc].operand0;
        uint64_t layout = buffer[pc].operand1;
        uint32_t type_version = (uint32_t)(layout >> 6);
        uint16_t trace_add = (uint16_t)(layout >> 39);
        if ((fields >> 48) != 0 || (layout & 7) != 0 ||
            ((layout >> 3) & 7) != 1 || ((layout >> 38) & 1) == 0 ||
            (layout >> 55) != 0 || type_version == 0 ||
            trace_add != body_add ||
            (method_type_version != 0 && method_type_version != type_version)) {
            continue;
        }
        pc++;
        DOT_EXPECT(_MAKE_HEAP_SAFE);
        DOT_EXPECT(_RETURN_VALUE);
        buffer[start].opcode = _CALL_PY_FLOAT_DOT;
        buffer[start].oparg = return_offset;
        buffer[start].operand0 = fields |
            ((uint64_t)guard_code->co_framesize << 48);
        buffer[start].operand1 = layout;
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_dot:
        ;
#undef DOT_EXPECT
#undef DOT_NEXT
    }
#endif
}

/* Prove a generator expression which yields 1 or 0 for exact membership:
 *     (1 if key in item else 0 for item in iterable)
 * The runtime path additionally requires the just-created generator's
 * iterable and every item to be exact lists of compact exact integers. */
bool
_Py_SumListIntContainsBody(PyCodeObject *code)
{
    if (code->co_argcount != 1 || code->co_kwonlyargcount ||
        code->co_nlocals != 2 || code->co_nlocalsplus != 3 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 1 ||
        !(code->co_flags & CO_GENERATOR) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_COROUTINE |
                           CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define SUM_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define SUM_ARG(OP, ARG) do { SUM_READ(OP); if (arg != (ARG)) return false; } while (0)
    SUM_ARG(COPY_FREE_VARS, 1);
    SUM_ARG(RESUME, RESUME_AT_GEN_EXPR_START);
    SUM_ARG(LOAD_FAST, 0);
    SUM_ARG(GET_ITER, 0);
    SUM_ARG(RETURN_GENERATOR, 0);
    SUM_ARG(POP_TOP, 0);
    SUM_ARG(RESUME, RESUME_AT_FUNC_START);
    int loop = pc;
    SUM_READ(FOR_ITER);
    int exhausted = pc + arg;
    SUM_ARG(STORE_FAST, 1);
    SUM_ARG(LOAD_DEREF, 2);
    SUM_ARG(LOAD_FAST_BORROW, 1);
    SUM_ARG(CONTAINS_OP, 0);
    SUM_READ(POP_JUMP_IF_FALSE);
    int missing = pc + arg;
    SUM_ARG(NOT_TAKEN, 0);
    SUM_ARG(LOAD_SMALL_INT, 1);
    SUM_READ(JUMP_FORWARD);
    int joined = pc + arg;
    if (pc != missing) {
        return false;
    }
    SUM_ARG(LOAD_SMALL_INT, 0);
    if (pc != joined) {
        return false;
    }
    SUM_ARG(YIELD_VALUE, 0);
    SUM_ARG(RESUME, RESUME_AFTER_YIELD | RESUME_OPARG_DEPTH1_MASK);
    SUM_ARG(POP_TOP, 0);
    SUM_READ(JUMP_BACKWARD);
    if (pc - arg != loop || pc != exhausted) {
        return false;
    }
    SUM_ARG(END_FOR, 0);
    SUM_ARG(POP_ITER, 0);
    SUM_ARG(LOAD_COMMON_CONSTANT, CONSTANT_NONE);
    SUM_ARG(RETURN_VALUE, 0);
    SUM_ARG(CALL_INTRINSIC_1, INTRINSIC_STOPITERATION_ERROR);
    SUM_ARG(RERAISE, 1);
    return pc == Py_SIZE(code);
#undef SUM_ARG
#undef SUM_READ
}

/* Prove the side-effect-free key function used by the max(dict, key=...)
 * specialization:
 *
 *     lambda key: mapping[key]
 *
 * Runtime guards additionally require that the closure contains the mapping
 * argument and that all keys and values can be inspected without callbacks. */
bool
_Py_MaxDictIntKeyBody(PyCodeObject *code)
{
    if (code->co_argcount != 1 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 1 || code->co_nlocalsplus != 2 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 1 ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define MAX_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define MAX_ARG(OP, ARG) do { MAX_READ(OP); if (arg != (ARG)) return false; } while (0)
    MAX_ARG(COPY_FREE_VARS, 1);
    MAX_ARG(RESUME, 0);
    MAX_ARG(LOAD_DEREF, 1);
    MAX_ARG(LOAD_FAST_BORROW, 0);
    MAX_ARG(BINARY_OP, NB_SUBSCR);
    MAX_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef MAX_ARG
#undef MAX_READ
}

static void
inline_sum_list_int_contains(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    PyObject *builtin_sum = _PyInterpreterState_GET()->callable_cache.sum;
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _CALL_BUILTIN_FAST_WITH_KEYWORDS ||
            buffer[start].oparg != 1) {
            continue;
        }
        int lower = Py_MAX(0, start - 96);
        int return_generator = -1;
        int make_function = -1;
        int code_load = -1;
        PyCodeObject *code = NULL;
        for (int pc = start - 1; pc >= lower; pc--) {
            int opcode = region_opcode(&buffer[pc]);
            if (return_generator < 0) {
                if (opcode == _RETURN_GENERATOR) {
                    return_generator = pc;
                }
                continue;
            }
            if (make_function < 0) {
                if (opcode == _MAKE_FUNCTION) {
                    make_function = pc;
                }
                continue;
            }
            if ((opcode == _LOAD_CONST_INLINE ||
                 opcode == _LOAD_CONST_INLINE_BORROW) &&
                PyCode_Check((PyObject *)buffer[pc].operand0)) {
                code_load = pc;
                code = (PyCodeObject *)buffer[pc].operand0;
                break;
            }
        }
        if (code == NULL || code->co_version == 0 ||
            !_Py_SumListIntContainsBody(code)) {
            continue;
        }
        bool loaded_sum = false;
        for (int pc = code_load - 1; pc >= lower; pc--) {
            int opcode = region_opcode(&buffer[pc]);
            if ((opcode == _LOAD_CONST_INLINE ||
                 opcode == _LOAD_CONST_INLINE_BORROW) &&
                (PyObject *)buffer[pc].operand0 == builtin_sum) {
                loaded_sum = true;
                break;
            }
            if (opcode == _CALL_BUILTIN_FAST_WITH_KEYWORDS ||
                opcode == _RETURN_GENERATOR) {
                break;
            }
        }
        if (!loaded_sum) {
            continue;
        }
        assert(code_load < make_function &&
               make_function < return_generator && return_generator < start);
        buffer[start].opcode = _CALL_SUM_LIST_INT_CONTAINS;
        buffer[start].oparg = 0;
        buffer[start].operand0 = code->co_version;
        buffer[start].operand1 = 0;
    }
#endif
}

/* Prove both exits of a small, effect-free positional search. Names are
 * resolved in the callee at execution time; no benchmark names are special. */
static bool
attribute_search_body(PyCodeObject *code, uint64_t *options, uint64_t *fields)
{
    if (code->co_argcount != 2 || code->co_kwonlyargcount ||
        code->co_nlocalsplus != 4 || PyBytes_GET_SIZE(code->co_exceptiontable) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                          CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define SEARCH_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define SEARCH_ARG(OP, ARG) do { SEARCH_READ(OP); if (arg != (ARG)) return false; } while (0)
    SEARCH_ARG(RESUME, 0);
    SEARCH_READ(LOAD_GLOBAL);
    if (!(arg & 1) || (arg >> 1) > UINT8_MAX) return false;
    *options = (uint64_t)(arg >> 1) << 32;
    SEARCH_ARG(LOAD_FAST_BORROW, 0);
    SEARCH_READ(LOAD_ATTR);
    if (arg & 1) return false;
    int attribute = arg;
    SEARCH_ARG(CALL, 1);
    SEARCH_ARG(GET_ITER, 0);
    int loop = pc;
    SEARCH_READ(FOR_ITER);
    int exhausted = pc + arg;
    SEARCH_ARG(UNPACK_SEQUENCE, 2);
    SEARCH_ARG(STORE_FAST_STORE_FAST, 0x23);
    SEARCH_ARG(LOAD_FAST_BORROW, 3);
    SEARCH_READ(LOAD_SMALL_INT);
    if (arg > 31) return false;
    *fields = (uint64_t)arg << 52;
    SEARCH_ARG(BINARY_OP, NB_SUBSCR);
    SEARCH_ARG(LOAD_FAST_BORROW, 1);
    SEARCH_READ(COMPARE_OP);
    unsigned int mask = arg & 15;
    static const unsigned int masks[] = {2, 10, 8, 7, 4, 12};
    if (!(arg & 16) || (arg >> 5) > Py_GE || mask != masks[arg >> 5]) return false;
    *fields |= (uint64_t)(arg >> 5) << 57;
    SEARCH_READ(POP_JUMP_IF_TRUE);
    int matched = pc + arg;
    SEARCH_READ(NOT_TAKEN);
    SEARCH_READ(JUMP_BACKWARD);
    if (pc - arg != loop || pc != matched) return false;
    SEARCH_ARG(LOAD_FAST_BORROW, 2);
    SEARCH_ARG(SWAP, 3);
    SEARCH_READ(POP_TOP);
    SEARCH_READ(POP_TOP);
    SEARCH_READ(RETURN_VALUE);
    if (pc != exhausted) return false;
    SEARCH_READ(END_FOR);
    SEARCH_READ(POP_ITER);
    SEARCH_READ(LOAD_GLOBAL);
    if (!(arg & 1) || (arg >> 1) > UINT8_MAX) return false;
    *options |= (uint64_t)(arg >> 1) << 40;
    SEARCH_ARG(LOAD_FAST_BORROW, 0);
    SEARCH_ARG(LOAD_ATTR, attribute);
    SEARCH_ARG(CALL, 1);
    SEARCH_READ(RETURN_VALUE);
    return pc == Py_SIZE(code);
#undef SEARCH_ARG
#undef SEARCH_READ
}

static void
inline_attribute_search_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        int nargs = buffer[start].oparg;
        if (buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS ||
            nargs < 1 || nargs > 2) continue;
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 16; i--) {
            int op = buffer[i].opcode;
            if (op == _RECORD_CALLABLE || op == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) obj = PyMethod_GET_FUNCTION(obj);
                if (obj != NULL && PyFunction_Check(obj)) func = (PyFunctionObject *)obj;
                break;
            }
        }
        uint64_t options, fields;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !attribute_search_body((PyCodeObject *)func->func_code, &options, &fields)) {
            continue;
        }
        int end = Py_MIN(length, start + 64);
        int pc = start + 1;
#define SEARCH_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                       pc < end ? region_opcode(&buffer[pc]) : 0)
#define SEARCH_EXPECT(OP) do { if (SEARCH_NEXT() != (OP)) goto next_search; pc++; } while (0)
        if (SEARCH_NEXT() != _SAVE_RETURN_OFFSET || buffer[pc].oparg > UINT16_MAX) continue;
        options |= (uint64_t)buffer[pc++].oparg << 48;
        SEARCH_EXPECT(_PUSH_FRAME);
        SEARCH_EXPECT(_TIER2_RESUME_CHECK);
        if (SEARCH_NEXT() == _GUARD_GLOBALS_VERSION ||
            SEARCH_NEXT() == _GUARD_GLOBALS_VERSION_AND_IDENTITY) pc++;
        if (SEARCH_NEXT() == _GUARD_BUILTINS_IDENTITY) pc++;
        int op = SEARCH_NEXT();
        if ((op != _LOAD_CONST_INLINE && op != _LOAD_CONST_INLINE_BORROW) ||
            buffer[pc++].operand0 != (uintptr_t)&PyEnum_Type) continue;
        SEARCH_EXPECT(_PUSH_NULL);
        uint64_t descriptor;
        if (trivial_attribute_load(buffer, pc, end, 1, &descriptor) < 0 ||
            (descriptor & 7) != 0) continue;
        buffer[start].opcode = _CALL_PY_ATTRIBUTE_SEARCH;
        buffer[start].oparg = 6 * (nargs - 1) + (fields >> 57);
        buffer[start].operand0 = descriptor | fields;
        buffer[start].operand1 = options | func->func_version;
        /* The full body proof covers returns not present on this trace.
         * Resume the real caller after CALL, with the one result on its stack.
         * Retain recorded references for the normal tracer cleanup. */
        for (int i = start + 1; i < length; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[length - 1].opcode = _DYNAMIC_EXIT;
        buffer[length - 1].oparg = 0;
        buffer[length - 1].target = 0;
        buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
        return;
next_search:
        ;
#undef SEARCH_EXPECT
#undef SEARCH_NEXT
    }
#endif
}

/* Prove the complete, read-only reference-chain body:
 *
 *     reference = self.reference
 *     if reference.position != self.position:
 *         reference = reference.find(update)
 *         if update:
 *             self.reference = reference
 *     return reference
 *
 * The optimized call only accepts update=False. Attribute names and layouts
 * are obtained from the code and recorded trace; function names are not
 * special. */
static bool
reference_root_body(PyCodeObject *code, uint8_t *method_name,
                    uint16_t *return_offset)
{
    if (code->co_argcount != 2 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 3 || code->co_nlocalsplus != 3 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define ROOT_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define ROOT_ARG(OP, ARG) do { ROOT_READ(OP); if (arg != (ARG)) return false; } while (0)
    ROOT_ARG(RESUME, 0);
    ROOT_ARG(LOAD_FAST_BORROW, 0);
    ROOT_READ(LOAD_ATTR);
    if (arg & 1) return false;
    int reference = arg;
    ROOT_ARG(STORE_FAST, 2);
    ROOT_ARG(LOAD_FAST_BORROW, 2);
    ROOT_READ(LOAD_ATTR);
    if (arg & 1) return false;
    int position = arg;
    ROOT_ARG(LOAD_FAST_BORROW, 0);
    ROOT_ARG(LOAD_ATTR, position);
    ROOT_READ(COMPARE_OP);
    if (!(arg & 16) || (arg >> 5) != Py_NE) return false;
    ROOT_READ(POP_JUMP_IF_FALSE);
    int already_root = pc + arg;
    ROOT_ARG(NOT_TAKEN, 0);
    ROOT_ARG(LOAD_FAST_BORROW, 2);
    ROOT_READ(LOAD_ATTR);
    if (!(arg & 1) || (arg >> 1) > UINT8_MAX) return false;
    *method_name = (uint8_t)(arg >> 1);
    ROOT_ARG(LOAD_FAST_BORROW, 1);
    ROOT_ARG(CALL, 1);
    ROOT_ARG(STORE_FAST, 2);
    ROOT_ARG(LOAD_FAST_BORROW, 1);
    ROOT_ARG(TO_BOOL, 0);
    ROOT_READ(POP_JUMP_IF_FALSE);
    int no_update = pc + arg;
    ROOT_ARG(NOT_TAKEN, 0);
    ROOT_ARG(LOAD_FAST_BORROW_LOAD_FAST_BORROW, 0x20);
    ROOT_ARG(STORE_ATTR, reference);
    if (pc != already_root || pc != no_update) return false;
    ROOT_ARG(LOAD_FAST_BORROW, 2);
    if (pc > UINT16_MAX) return false;
    *return_offset = (uint16_t)pc;
    ROOT_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef ROOT_ARG
#undef ROOT_READ
}

static int
reference_root_method_slot(PyTypeObject *type, uint32_t type_version,
                           PyFunctionObject *func, uint8_t method_name)
{
    PyCodeObject *code = (PyCodeObject *)func->func_code;
    if (type == NULL || type->tp_version_tag != type_version ||
        !(type->tp_flags & Py_TPFLAGS_HEAPTYPE) ||
        !(type->tp_flags & Py_TPFLAGS_INLINE_VALUES) ||
        method_name >= PyTuple_GET_SIZE(code->co_names)) {
        return DKIX_ERROR;
    }
    PyObject *name = PyTuple_GET_ITEM(code->co_names, method_name);
    unsigned int method_version = 0;
    PyObject *class_method = _PyType_LookupRefAndVersion(
        type, name, &method_version);
    bool valid = method_version == type_version &&
        class_method == (PyObject *)func;
    Py_XDECREF(class_method);
    if (!valid) {
        return DKIX_ERROR;
    }
    PyDictKeysObject *keys = ((PyHeapTypeObject *)type)->ht_cached_keys;
    if (keys == NULL) {
        return DKIX_ERROR;
    }
    Py_ssize_t slot = _PyDictKeys_StringLookupSplit(keys, name);
    if (slot < DKIX_EMPTY || slot > UINT8_MAX - 1) {
        return DKIX_ERROR;
    }
    return (int)slot;
}

/* Apply the same complete root lookup when the optional boolean argument is
 * supplied by the function's default.  CALL_PY_GENERAL would otherwise
 * allocate a real frame before the recursive call can be recognized. */
static void
inline_reference_root_default_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if (buffer[start].opcode != _PY_FRAME_GENERAL ||
            buffer[start].oparg != 0) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 24; i--) {
            int op = buffer[i].opcode;
            if (op == _RECORD_CALLABLE || op == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
        }
        uint8_t method_name;
        uint16_t callee_return_offset;
        PyObject *defaults = func == NULL ? NULL : func->func_defaults;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            defaults == NULL || !PyTuple_CheckExact(defaults) ||
            PyTuple_GET_SIZE(defaults) != 1 ||
            PyTuple_GET_ITEM(defaults, 0) != Py_False ||
            !reference_root_body((PyCodeObject *)func->func_code, &method_name,
                                 &callee_return_offset)) {
            continue;
        }
        int end = Py_MIN(length, start + 512);
        int pc = start + 1;
#define ROOT_DEFAULT_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                             pc < end ? region_opcode(&buffer[pc]) : 0)
#define ROOT_DEFAULT_EXPECT(OP) do { \
    if (ROOT_DEFAULT_NEXT() != (OP)) { \
        goto next_root_default; \
    } \
    pc++; \
} while (0)
        if (ROOT_DEFAULT_NEXT() != _SAVE_RETURN_OFFSET ||
            buffer[pc].oparg > UINT8_MAX) {
            continue;
        }
        uint16_t return_offset = (uint16_t)buffer[pc++].oparg;
        ROOT_DEFAULT_EXPECT(_PUSH_FRAME);
        ROOT_DEFAULT_EXPECT(_TIER2_RESUME_CHECK);
        uint64_t reference, position, other_position;
        PyTypeObject *recorded_type;
        pc = trivial_attribute_load_with_type(
            buffer, pc, end, 2, &reference, &recorded_type);
        if (pc < 0) continue;
        int op = ROOT_DEFAULT_NEXT();
        if ((op != _SWAP_FAST && op != _SWAP_FAST_2) ||
            buffer[pc].oparg != 2) {
            continue;
        }
        pc++;
        op = ROOT_DEFAULT_NEXT();
        if (op != _POP_TOP && op != _POP_TOP_NOP) continue;
        pc++;
        pc = trivial_attribute_load(buffer, pc, end, 2, &position);
        if (pc < 0) continue;
        pc = trivial_attribute_load(buffer, pc, end, 2, &other_position);
        if (pc < 0 || (position & ~UINT64_C(7)) !=
                      (other_position & ~UINT64_C(7))) {
            continue;
        }
        uint32_t type_version = (uint32_t)(reference >> 19);
        if (type_version == 0 || type_version != (uint32_t)(position >> 19)) {
            continue;
        }
        int method_slot = reference_root_method_slot(
            recorded_type, type_version, func, method_name);
        if (method_slot == DKIX_ERROR) {
            continue;
        }
        uint16_t reference_offset = (uint16_t)(reference >> 3);
        uint16_t position_offset = (uint16_t)(position >> 3);
        buffer[start].opcode = _CALL_PY_REFERENCE_ROOT_DEFAULT;
        buffer[start].oparg = return_offset |
            ((uint16_t)(method_slot + 1) << 8);
        buffer[start].operand0 = (uintptr_t)func;
        buffer[start].operand1 = type_version |
            ((uint64_t)reference_offset << 32) |
            ((uint64_t)position_offset << 48);
        for (int i = start + 1; i < length; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[length - 1].opcode = _DYNAMIC_EXIT;
        buffer[length - 1].oparg = 0;
        buffer[length - 1].target = 0;
        buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
        return;
next_root_default:
        ;
#undef ROOT_DEFAULT_EXPECT
#undef ROOT_DEFAULT_NEXT
    }
#endif
}

static void
inline_reference_root_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_1) ||
            buffer[start].oparg != 1) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 16; i--) {
            int op = buffer[i].opcode;
            if (op == _RECORD_CALLABLE || op == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
        }
        uint8_t method_name;
        uint16_t callee_return_offset;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !reference_root_body((PyCodeObject *)func->func_code, &method_name,
                                 &callee_return_offset)) {
            continue;
        }
        int end = Py_MIN(length, start + 512);
        int pc = start + 1;
#define ROOT_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                     pc < end ? region_opcode(&buffer[pc]) : 0)
#define ROOT_EXPECT(OP) do { if (ROOT_NEXT() != (OP)) goto next_root; pc++; } while (0)
        if (ROOT_NEXT() != _SAVE_RETURN_OFFSET || buffer[pc].oparg > UINT8_MAX) {
            continue;
        }
        uint16_t return_offset = (uint16_t)buffer[pc++].oparg;
        ROOT_EXPECT(_PUSH_FRAME);
        ROOT_EXPECT(_TIER2_RESUME_CHECK);
        uint64_t reference, position, other_position;
        PyTypeObject *recorded_type;
        pc = trivial_attribute_load_with_type(
            buffer, pc, end, 2, &reference, &recorded_type);
        if (pc < 0) continue;
        int op = ROOT_NEXT();
        if ((op != _SWAP_FAST && op != _SWAP_FAST_2) || buffer[pc].oparg != 2) {
            continue;
        }
        pc++;
        op = ROOT_NEXT();
        if (op != _POP_TOP && op != _POP_TOP_NOP) continue;
        pc++;
        pc = trivial_attribute_load(buffer, pc, end, 2, &position);
        if (pc < 0) continue;
        pc = trivial_attribute_load(buffer, pc, end, 2, &other_position);
        if (pc < 0 || (position & ~UINT64_C(7)) !=
                      (other_position & ~UINT64_C(7))) {
            continue;
        }
        uint32_t type_version = (uint32_t)(reference >> 19);
        if (type_version == 0 || type_version != (uint32_t)(position >> 19)) {
            continue;
        }
        int method_slot = reference_root_method_slot(
            recorded_type, type_version, func, method_name);
        if (method_slot == DKIX_ERROR) {
            continue;
        }
        uint16_t reference_offset = (uint16_t)(reference >> 3);
        uint16_t position_offset = (uint16_t)(position >> 3);
        uint64_t options = type_version |
            ((uint64_t)reference_offset << 32) |
            ((uint64_t)position_offset << 48);

        buffer[start].opcode = _CALL_PY_REFERENCE_ROOT;
        buffer[start].oparg = return_offset |
            ((uint16_t)(method_slot + 1) << 8);
        buffer[start].operand0 = (uintptr_t)func;
        buffer[start].operand1 = options;
        /* The complete body proof permits returning directly to the real
         * caller. Leave this trace immediately so later uops cannot depend
         * on the elided recursive frame's stack or locals. */
        for (int i = start + 1; i < length; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[length - 1].opcode = _DYNAMIC_EXIT;
        buffer[length - 1].oparg = 0;
        buffer[length - 1].target = 0;
        buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
        return;
next_root:
        ;
#undef ROOT_EXPECT
#undef ROOT_NEXT
    }
#endif
}

/* Collapse the same read-only chain from an executor attached to the callee.
 * The actual frame remains live and performs its original RETURN_VALUE. */
static void
inline_local_reference_root(_PyThreadStateImpl *tstate,
                            _PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    const _PyJitTracerState *tracer = tstate->jit_tracer_state;
    PyCodeObject *code = tracer->initial_state.code;
    PyFunctionObject *func = tracer->initial_state.func;
    uint8_t method_name;
    uint16_t return_offset;
    if (tracer->initial_state.start_instr != _PyCode_CODE(code) ||
        tracer->initial_state.stack_depth != 0 ||
        func == NULL || (PyCodeObject *)func->func_code != code ||
        !reference_root_body(code, &method_name, &return_offset)) {
        return;
    }
    int pc = 0;
    if (length < 4 || buffer[pc++].opcode != _START_EXECUTOR) return;
    if (buffer[pc].opcode == _MAKE_WARM) pc++;
    pc = trivial_call_skip(buffer, pc, length);
    if (pc >= length || buffer[pc++].opcode != _TIER2_RESUME_CHECK) return;
    pc = trivial_call_skip(buffer, pc, length);
    int start = pc;
    uint64_t reference, position, other_position;
    PyTypeObject *recorded_type;
    pc = trivial_attribute_load_with_type(
        buffer, pc, length, 2, &reference, &recorded_type);
    if (pc < 0) return;
    int op = pc < length ? region_opcode(&buffer[pc]) : 0;
    if ((op != _SWAP_FAST && op != _SWAP_FAST_2) ||
        buffer[pc].oparg != 2) {
        return;
    }
    pc = trivial_call_skip(buffer, pc + 1, length);
    if (pc >= length || (buffer[pc].opcode != _POP_TOP &&
                         buffer[pc].opcode != _POP_TOP_NOP)) {
        return;
    }
    pc = trivial_call_skip(buffer, pc + 1, length);
    pc = trivial_attribute_load(buffer, pc, length, 2, &position);
    if (pc < 0) return;
    pc = trivial_attribute_load(buffer, pc, length, 2, &other_position);
    if (pc < 0 || (position & ~UINT64_C(7)) !=
                  (other_position & ~UINT64_C(7))) {
        return;
    }
    uint32_t type_version = (uint32_t)(reference >> 19);
    if (type_version == 0 || type_version != (uint32_t)(position >> 19)) {
        return;
    }
    int method_slot = reference_root_method_slot(
        recorded_type, type_version, func, method_name);
    if (method_slot == DKIX_ERROR) {
        return;
    }
    uint16_t reference_offset = (uint16_t)(reference >> 3);
    uint16_t position_offset = (uint16_t)(position >> 3);
    buffer[start].opcode = _REFERENCE_ROOT_LOCAL;
    buffer[start].oparg = 0;
    buffer[start].operand0 = type_version |
        ((uint64_t)reference_offset << 32) |
        ((uint64_t)position_offset << 48);
    buffer[start].operand1 = return_offset |
        ((uint64_t)(method_slot + 1) << 16);
    for (int i = start + 1; i < length; i++) {
        if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            buffer[i].opcode = _NOP;
        }
    }
    buffer[length - 1].opcode = _DYNAMIC_EXIT;
    buffer[length - 1].oparg = 0;
    buffer[length - 1].target = 0;
    buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
#endif
}

/* Prove the complete two-list update body:
 *
 *     self.first[i] = value
 *     self.second[value] = i
 *
 * Runtime specialization further requires exact lists and compact exact-int
 * arguments and elements, so both writes are callback-free after validation. */
static bool
list_set_pair_body(PyCodeObject *code)
{
    if (code->co_argcount != 3 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 3 || code->co_nlocalsplus != 3 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define SET_PAIR_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define SET_PAIR_ARG(OP, ARG) do { \
    SET_PAIR_READ(OP); if (arg != (ARG)) return false; \
} while (0)
    SET_PAIR_ARG(RESUME, 0);
    SET_PAIR_ARG(LOAD_FAST_BORROW_LOAD_FAST_BORROW, 0x20);
    SET_PAIR_READ(LOAD_ATTR);
    if (arg & 1) return false;
    SET_PAIR_ARG(LOAD_FAST_BORROW, 1);
    SET_PAIR_ARG(STORE_SUBSCR, 0);
    SET_PAIR_ARG(LOAD_FAST_BORROW_LOAD_FAST_BORROW, 0x10);
    SET_PAIR_READ(LOAD_ATTR);
    if (arg & 1) return false;
    SET_PAIR_ARG(LOAD_FAST_BORROW, 2);
    SET_PAIR_ARG(STORE_SUBSCR, 0);
    SET_PAIR_ARG(LOAD_COMMON_CONSTANT, CONSTANT_NONE);
    SET_PAIR_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef SET_PAIR_ARG
#undef SET_PAIR_READ
}

static void
inline_list_set_pair_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_2) ||
            buffer[start].oparg != 2) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 64; i--) {
            int opcode = buffer[i].opcode;
            if (opcode == _RECORD_CALLABLE || opcode == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
            if (opcode == _LOAD_CONST_INLINE ||
                opcode == _LOAD_CONST_INLINE_BORROW) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                    break;
                }
            }
        }
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !list_set_pair_body((PyCodeObject *)func->func_code)) {
            continue;
        }
        int end = Py_MIN(length, start + 96);
        int pc = start + 1;
#define SET_PAIR_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                         pc < end ? region_opcode(&buffer[pc]) : 0)
#define SET_PAIR_EXPECT(OP) do { \
    if (SET_PAIR_NEXT() != (OP)) { goto next_set_pair; } pc++; \
} while (0)
        if (SET_PAIR_NEXT() != _SAVE_RETURN_OFFSET) continue;
        pc++;
        SET_PAIR_EXPECT(_PUSH_FRAME);
        SET_PAIR_EXPECT(_TIER2_RESUME_CHECK);
        int opcode = SET_PAIR_NEXT();
        if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
            buffer[pc].oparg != 2) continue;
        pc++;
        uint64_t first, second;
        pc = trivial_attribute_load(buffer, pc, end, 2, &first);
        if (pc < 0 || (first & 7) != 0) {
            continue;
        }
        opcode = SET_PAIR_NEXT();
        if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
            buffer[pc].oparg != 1) continue;
        pc++;
        while ((opcode = SET_PAIR_NEXT()) == _GUARD_TOS_INT ||
               opcode == _GUARD_TOS_OVERFLOWED ||
               opcode == _GUARD_NOS_LIST) {
            pc++;
        }
        SET_PAIR_EXPECT(_STORE_SUBSCR_LIST_INT);
        for (int i = 0; i < 2; i++) {
            opcode = SET_PAIR_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
                opcode != _POP_TOP_INT) {
                goto next_set_pair;
            }
            pc++;
        }
        opcode = SET_PAIR_NEXT();
        if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
            buffer[pc].oparg != 1) continue;
        pc++;
        pc = trivial_attribute_load(buffer, pc, end, 2, &second);
        if (pc < 0 || (second & 7) != 0) {
            continue;
        }
        opcode = SET_PAIR_NEXT();
        if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
            buffer[pc].oparg != 2) continue;
        pc++;
        while ((opcode = SET_PAIR_NEXT()) == _GUARD_TOS_INT ||
               opcode == _GUARD_TOS_OVERFLOWED ||
               opcode == _GUARD_NOS_LIST) {
            pc++;
        }
        SET_PAIR_EXPECT(_STORE_SUBSCR_LIST_INT);
        for (int i = 0; i < 2; i++) {
            opcode = SET_PAIR_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
                opcode != _POP_TOP_INT) {
                goto next_set_pair;
            }
            pc++;
        }
        opcode = SET_PAIR_NEXT();
        if ((opcode != _LOAD_CONST_INLINE &&
             opcode != _LOAD_CONST_INLINE_BORROW) ||
            (PyObject *)buffer[pc].operand0 != Py_None) {
            continue;
        }
        pc++;
        SET_PAIR_EXPECT(_RETURN_VALUE);
        uint32_t type_version = (uint32_t)(first >> 19);
        if (type_version == 0 || type_version != (uint32_t)(second >> 19)) {
            continue;
        }
        uint16_t first_offset = (uint16_t)(first >> 3);
        uint16_t second_offset = (uint16_t)(second >> 3);
        buffer[start].opcode = _CALL_PY_LIST_SET_PAIR;
        buffer[start].oparg = 0;
        buffer[start].operand0 = (uintptr_t)func;
        buffer[start].operand1 = type_version |
            ((uint64_t)first_offset << 32) |
            ((uint64_t)second_offset << 48);
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_set_pair:
        ;
#undef SET_PAIR_EXPECT
#undef SET_PAIR_NEXT
    }
#endif
}

/* Replace the two stores in an executor attached to the callee while keeping
 * its real frame and return sequence. */
static void
inline_local_list_set_pair(_PyThreadStateImpl *tstate,
                           _PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    const _PyJitTracerState *tracer = tstate->jit_tracer_state;
    PyCodeObject *code = tracer->initial_state.code;
    if (tracer->initial_state.start_instr != _PyCode_CODE(code) ||
        tracer->initial_state.stack_depth != 0 ||
        !list_set_pair_body(code)) {
        return;
    }
    int pc = 0;
    if (length < 4 || buffer[pc++].opcode != _START_EXECUTOR) return;
    if (buffer[pc].opcode == _MAKE_WARM) pc++;
    pc = trivial_call_skip(buffer, pc, length);
    if (pc >= length || buffer[pc++].opcode != _TIER2_RESUME_CHECK) return;
    pc = trivial_call_skip(buffer, pc, length);
    int start = pc;
#define LOCAL_SET_NEXT() (pc = trivial_call_skip(buffer, pc, length), \
                          pc < length ? region_opcode(&buffer[pc]) : 0)
#define LOCAL_SET_EXPECT(OP) do { \
    if (LOCAL_SET_NEXT() != (OP)) { return; } pc++; \
} while (0)
    int opcode = LOCAL_SET_NEXT();
    if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != 2) return;
    pc++;
    uint64_t first, second;
    pc = trivial_attribute_load(buffer, pc, length, 2, &first);
    if (pc < 0 || (first & 7) != 0) return;
    opcode = LOCAL_SET_NEXT();
    if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != 1) return;
    pc++;
    while ((opcode = LOCAL_SET_NEXT()) == _GUARD_TOS_INT ||
           opcode == _GUARD_TOS_OVERFLOWED ||
           opcode == _GUARD_NOS_LIST) {
        pc++;
    }
    LOCAL_SET_EXPECT(_STORE_SUBSCR_LIST_INT);
    for (int i = 0; i < 2; i++) {
        opcode = LOCAL_SET_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
            opcode != _POP_TOP_INT) return;
        pc++;
    }
    opcode = LOCAL_SET_NEXT();
    if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != 1) return;
    pc++;
    pc = trivial_attribute_load(buffer, pc, length, 2, &second);
    if (pc < 0 || (second & 7) != 0) return;
    opcode = LOCAL_SET_NEXT();
    if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != 2) return;
    pc++;
    while ((opcode = LOCAL_SET_NEXT()) == _GUARD_TOS_INT ||
           opcode == _GUARD_TOS_OVERFLOWED ||
           opcode == _GUARD_NOS_LIST) {
        pc++;
    }
    LOCAL_SET_EXPECT(_STORE_SUBSCR_LIST_INT);
    for (int i = 0; i < 2; i++) {
        opcode = LOCAL_SET_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
            opcode != _POP_TOP_INT) return;
        pc++;
    }
    int body_end = pc;
    opcode = LOCAL_SET_NEXT();
    if ((opcode != _LOAD_CONST_INLINE &&
         opcode != _LOAD_CONST_INLINE_BORROW) ||
        (PyObject *)buffer[pc].operand0 != Py_None) return;
    pc++;
    LOCAL_SET_EXPECT(_RETURN_VALUE);
    uint32_t type_version = (uint32_t)(first >> 19);
    if (type_version == 0 || type_version != (uint32_t)(second >> 19)) {
        return;
    }
    buffer[start].opcode = _LIST_SET_PAIR_LOCAL;
    buffer[start].oparg = 0;
    buffer[start].operand0 = type_version |
        ((uint64_t)(uint16_t)(first >> 3) << 32) |
        ((uint64_t)(uint16_t)(second >> 3) << 48);
    buffer[start].operand1 = 0;
    for (int i = start + 1; i < body_end; i++) {
        if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            buffer[i].opcode = _NOP;
        }
    }
#undef LOCAL_SET_EXPECT
#undef LOCAL_SET_NEXT
#endif
}

/* Match a cached inline-value attribute load from one exact local. The COPY
 * form leaves the owner below its value for a following STORE_ATTR. */
static int
xor_attribute_load(_PyUOpInstruction *buffer, int pc, int end,
                   int local, bool copy, uint64_t *descriptor)
{
    pc = trivial_call_skip(buffer, pc, end);
    if (pc >= end || (region_opcode(&buffer[pc]) != _LOAD_FAST &&
                      region_opcode(&buffer[pc]) != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != local) {
        return -1;
    }
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (copy) {
        if (pc >= end ||
            (buffer[pc].opcode != _COPY_1 &&
             (buffer[pc].opcode != _COPY || buffer[pc].oparg != 1))) {
            return -1;
        }
        pc = trivial_call_skip(buffer, pc + 1, end);
    }
    if (pc < end && buffer[pc].opcode == _GUARD_TYPE_VERSION) {
        pc = trivial_call_skip(buffer, pc + 1, end);
    }
    if (pc >= end || buffer[pc].opcode != _CHECK_MANAGED_OBJECT_HAS_VALUES) {
        return -1;
    }
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc >= end || buffer[pc].opcode != _LOAD_ATTR_INSTANCE_VALUE ||
        !buffer[pc].operand1 || buffer[pc].operand0 > UINT16_MAX) {
        return -1;
    }
    uint64_t version = buffer[pc].operand1 & UINT32_MAX;
    uint64_t managed = buffer[pc].operand1 >> 32;
    *descriptor = local | (buffer[pc].operand0 << 3) |
        (version << 19) | (managed << 51);
    pc = trivial_call_skip(buffer, pc + 1, end);
    if (pc >= end || (buffer[pc].opcode != _POP_TOP &&
                      buffer[pc].opcode != _POP_TOP_NOP)) {
        return -1;
    }
    return trivial_call_skip(buffer, pc + 1, end);
}

/* Prove the complete body:
 *
 *     self.value ^= item.values[item.index]
 *     self.value ^= item.values[index]
 *
 * Attribute names must agree across both statements. The runtime matcher
 * further restricts every access to guarded inline values and exact lists and
 * integers. */
static bool
xor_attr_list_pair_body(PyCodeObject *code, uint16_t *first_error_offset,
                        uint16_t *second_error_offset)
{
    if (code->co_argcount != 3 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 3 || code->co_nlocalsplus != 3 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        Py_SIZE(code) > UINT16_MAX ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
    int value_name, values_name, item_index_name;
#define XOR_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define XOR_ARG(OP, ARG) do { XOR_READ(OP); if (arg != (ARG)) return false; } while (0)
    XOR_ARG(RESUME, 0);
    XOR_ARG(LOAD_FAST_BORROW, 0);
    XOR_ARG(COPY, 1);
    XOR_READ(LOAD_ATTR);
    if (arg & 1) return false;
    value_name = arg >> 1;
    XOR_ARG(LOAD_FAST_BORROW, 1);
    XOR_READ(LOAD_ATTR);
    if (arg & 1) return false;
    values_name = arg;
    XOR_ARG(LOAD_FAST_BORROW, 1);
    XOR_READ(LOAD_ATTR);
    if (arg & 1) return false;
    item_index_name = arg;
    XOR_ARG(BINARY_OP, NB_SUBSCR);
    *first_error_offset = (uint16_t)pc;
    XOR_ARG(BINARY_OP, NB_INPLACE_XOR);
    XOR_ARG(SWAP, 2);
    XOR_ARG(STORE_ATTR, value_name);
    XOR_ARG(LOAD_FAST_BORROW, 0);
    XOR_ARG(COPY, 1);
    XOR_READ(LOAD_ATTR);
    if ((arg & 1) || (arg >> 1) != value_name) return false;
    XOR_ARG(LOAD_FAST_BORROW, 1);
    XOR_READ(LOAD_ATTR);
    if (arg != values_name) return false;
    XOR_ARG(LOAD_FAST_BORROW, 2);
    XOR_ARG(BINARY_OP, NB_SUBSCR);
    *second_error_offset = (uint16_t)pc;
    XOR_ARG(BINARY_OP, NB_INPLACE_XOR);
    XOR_ARG(SWAP, 2);
    XOR_ARG(STORE_ATTR, value_name);
    XOR_ARG(LOAD_COMMON_CONSTANT, CONSTANT_NONE);
    XOR_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code) && item_index_name != values_name;
#undef XOR_ARG
#undef XOR_READ
}

static void
inline_xor_attr_list_pair_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_2) ||
            buffer[start].oparg != 2) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 64; i--) {
            int opcode = buffer[i].opcode;
            if (opcode == _RECORD_CALLABLE || opcode == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
            if (opcode == _LOAD_CONST_INLINE ||
                opcode == _LOAD_CONST_INLINE_BORROW) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                    break;
                }
            }
        }
        uint16_t first_error_offset, error_offset;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !xor_attr_list_pair_body(
                (PyCodeObject *)func->func_code, &first_error_offset,
                &error_offset)) {
            continue;
        }
        int end = Py_MIN(length, start + 192);
        int pc = start + 1;
#define XOR_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                    pc < end ? region_opcode(&buffer[pc]) : 0)
#define XOR_EXPECT(OP) do { \
    if (XOR_NEXT() != (OP)) { goto next_xor; } pc++; \
} while (0)
        if (XOR_NEXT() != _SAVE_RETURN_OFFSET || buffer[pc].oparg == 0) {
            continue;
        }
        uint16_t return_offset = (uint16_t)buffer[pc++].oparg;
        XOR_EXPECT(_PUSH_FRAME);
        XOR_EXPECT(_TIER2_RESUME_CHECK);
        uint64_t owner_value, first_values, first_index;
        uint64_t second_owner_value, second_values;
        pc = xor_attribute_load(buffer, pc, end, 0, true, &owner_value);
        if (pc < 0) goto next_xor;
        pc = xor_attribute_load(buffer, pc, end, 1, false, &first_values);
        if (pc < 0) goto next_xor;
        pc = xor_attribute_load(buffer, pc, end, 1, false, &first_index);
        if (pc < 0) goto next_xor;
        int opcode;
        while ((opcode = XOR_NEXT()) == _GUARD_TOS_INT ||
               opcode == _GUARD_TOS_OVERFLOWED ||
               opcode == _GUARD_NOS_LIST) {
            pc++;
        }
        XOR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        for (int i = 0; i < 2; i++) {
            opcode = XOR_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
                opcode != _POP_TOP_INT) goto next_xor;
            pc++;
        }
        if (XOR_NEXT() != _BINARY_OP || buffer[pc].oparg != NB_INPLACE_XOR) {
            goto next_xor;
        }
        pc++;
        for (int i = 0; i < 2; i++) {
            opcode = XOR_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
                opcode != _POP_TOP_INT) goto next_xor;
            pc++;
        }
        opcode = XOR_NEXT();
        if ((opcode != _SWAP_2 && opcode != _SWAP) || buffer[pc].oparg != 2) {
            goto next_xor;
        }
        pc++;
        XOR_EXPECT(_LOCK_OBJECT);
        XOR_EXPECT(_GUARD_DORV_NO_DICT);
        if (XOR_NEXT() != _STORE_ATTR_INSTANCE_VALUE ||
            buffer[pc].operand0 != (owner_value >> 3 & UINT16_MAX)) {
            goto next_xor;
        }
        pc++;
        opcode = XOR_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP) goto next_xor;
        pc++;

        pc = xor_attribute_load(
            buffer, pc, end, 0, true, &second_owner_value);
        if (pc < 0) goto next_xor;
        pc = xor_attribute_load(buffer, pc, end, 1, false, &second_values);
        if (pc < 0) goto next_xor;
        opcode = XOR_NEXT();
        if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
            buffer[pc].oparg != 2) goto next_xor;
        pc++;
        while ((opcode = XOR_NEXT()) == _GUARD_TOS_INT ||
               opcode == _GUARD_TOS_OVERFLOWED ||
               opcode == _GUARD_NOS_LIST) {
            pc++;
        }
        XOR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
        for (int i = 0; i < 2; i++) {
            opcode = XOR_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
                opcode != _POP_TOP_INT) goto next_xor;
            pc++;
        }
        if (XOR_NEXT() != _BINARY_OP || buffer[pc].oparg != NB_INPLACE_XOR) {
            goto next_xor;
        }
        pc++;
        for (int i = 0; i < 2; i++) {
            opcode = XOR_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
                opcode != _POP_TOP_INT) goto next_xor;
            pc++;
        }
        opcode = XOR_NEXT();
        if ((opcode != _SWAP_2 && opcode != _SWAP) || buffer[pc].oparg != 2) {
            goto next_xor;
        }
        pc++;
        XOR_EXPECT(_LOCK_OBJECT);
        XOR_EXPECT(_GUARD_DORV_NO_DICT);
        if (XOR_NEXT() != _STORE_ATTR_INSTANCE_VALUE ||
            buffer[pc].operand0 != (owner_value >> 3 & UINT16_MAX)) {
            goto next_xor;
        }
        pc++;
        opcode = XOR_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP) goto next_xor;
        pc++;
        opcode = XOR_NEXT();
        if ((opcode != _LOAD_CONST_INLINE &&
             opcode != _LOAD_CONST_INLINE_BORROW) ||
            (PyObject *)buffer[pc].operand0 != Py_None) goto next_xor;
        pc++;
        XOR_EXPECT(_RETURN_VALUE);

        uint32_t owner_version = (uint32_t)(owner_value >> 19);
        uint32_t item_version = (uint32_t)(first_values >> 19);
        if (owner_version == 0 || item_version == 0 ||
            (owner_value & ~UINT64_C(7)) !=
                (second_owner_value & ~UINT64_C(7)) ||
            (first_values & ~UINT64_C(7)) !=
                (second_values & ~UINT64_C(7)) ||
            item_version != (uint32_t)(first_index >> 19)) {
            goto next_xor;
        }
        buffer[start].opcode = _CALL_PY_XOR_ATTR_LIST_PAIR;
        buffer[start].oparg = (uint16_t)(owner_value >> 3);
        buffer[start].operand0 = owner_version |
            ((uint64_t)item_version << 32);
        buffer[start].operand1 = (uint16_t)(first_values >> 3) |
            ((uint64_t)(uint16_t)(first_index >> 3) << 16) |
            ((uint64_t)error_offset << 32) |
            ((uint64_t)return_offset << 48);
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_xor:
        ;
#undef XOR_EXPECT
#undef XOR_NEXT
    }
#endif
}

/* Apply the same XOR specialization to an executor attached to the callee.
 * Keep its real frame and RETURN_VALUE; only replace the two straight-line
 * update statements. */
static void
inline_local_xor_attr_list_pair(_PyThreadStateImpl *tstate,
                                _PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    const _PyJitTracerState *tracer = tstate->jit_tracer_state;
    PyCodeObject *code = tracer->initial_state.code;
    uint16_t first_error_offset, second_error_offset;
    if (tracer->initial_state.start_instr != _PyCode_CODE(code) ||
        tracer->initial_state.stack_depth != 0 ||
        !xor_attr_list_pair_body(code, &first_error_offset,
                                 &second_error_offset)) {
        return;
    }
    int pc = 0;
    if (length < 4 || buffer[pc++].opcode != _START_EXECUTOR) return;
    if (buffer[pc].opcode == _MAKE_WARM) pc++;
    pc = trivial_call_skip(buffer, pc, length);
    if (pc >= length || buffer[pc++].opcode != _TIER2_RESUME_CHECK) return;
    pc = trivial_call_skip(buffer, pc, length);
    int start = pc;
#define LXOR_NEXT() (pc = trivial_call_skip(buffer, pc, length), \
                     pc < length ? region_opcode(&buffer[pc]) : 0)
#define LXOR_EXPECT(OP) do { \
    if (LXOR_NEXT() != (OP)) { return; } pc++; \
} while (0)
    uint64_t owner_value, first_values, first_index;
    uint64_t second_owner_value, second_values;
    pc = xor_attribute_load(buffer, pc, length, 0, true, &owner_value);
    if (pc < 0) return;
    pc = xor_attribute_load(buffer, pc, length, 1, false, &first_values);
    if (pc < 0) return;
    pc = xor_attribute_load(buffer, pc, length, 1, false, &first_index);
    if (pc < 0) return;
    int opcode;
    while ((opcode = LXOR_NEXT()) == _GUARD_TOS_INT ||
           opcode == _GUARD_TOS_OVERFLOWED ||
           opcode == _GUARD_NOS_LIST) {
        pc++;
    }
    LXOR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
    for (int i = 0; i < 2; i++) {
        opcode = LXOR_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
            opcode != _POP_TOP_INT) return;
        pc++;
    }
    if (LXOR_NEXT() != _BINARY_OP || buffer[pc].oparg != NB_INPLACE_XOR) {
        return;
    }
    pc++;
    for (int i = 0; i < 2; i++) {
        opcode = LXOR_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
            opcode != _POP_TOP_INT) return;
        pc++;
    }
    opcode = LXOR_NEXT();
    if ((opcode != _SWAP_2 && opcode != _SWAP) || buffer[pc].oparg != 2) {
        return;
    }
    pc++;
    LXOR_EXPECT(_LOCK_OBJECT);
    LXOR_EXPECT(_GUARD_DORV_NO_DICT);
    if (LXOR_NEXT() != _STORE_ATTR_INSTANCE_VALUE ||
        buffer[pc].operand0 != (owner_value >> 3 & UINT16_MAX)) {
        return;
    }
    pc++;
    opcode = LXOR_NEXT();
    if (opcode != _POP_TOP && opcode != _POP_TOP_NOP) return;
    pc++;

    pc = xor_attribute_load(buffer, pc, length, 0, true,
                            &second_owner_value);
    if (pc < 0) return;
    pc = xor_attribute_load(buffer, pc, length, 1, false, &second_values);
    if (pc < 0) return;
    opcode = LXOR_NEXT();
    if ((opcode != _LOAD_FAST && opcode != _LOAD_FAST_BORROW) ||
        buffer[pc].oparg != 2) return;
    pc++;
    while ((opcode = LXOR_NEXT()) == _GUARD_TOS_INT ||
           opcode == _GUARD_TOS_OVERFLOWED ||
           opcode == _GUARD_NOS_LIST) {
        pc++;
    }
    LXOR_EXPECT(_BINARY_OP_SUBSCR_LIST_INT);
    for (int i = 0; i < 2; i++) {
        opcode = LXOR_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
            opcode != _POP_TOP_INT) return;
        pc++;
    }
    if (LXOR_NEXT() != _BINARY_OP || buffer[pc].oparg != NB_INPLACE_XOR) {
        return;
    }
    pc++;
    for (int i = 0; i < 2; i++) {
        opcode = LXOR_NEXT();
        if (opcode != _POP_TOP && opcode != _POP_TOP_NOP &&
            opcode != _POP_TOP_INT) return;
        pc++;
    }
    opcode = LXOR_NEXT();
    if ((opcode != _SWAP_2 && opcode != _SWAP) || buffer[pc].oparg != 2) {
        return;
    }
    pc++;
    LXOR_EXPECT(_LOCK_OBJECT);
    LXOR_EXPECT(_GUARD_DORV_NO_DICT);
    if (LXOR_NEXT() != _STORE_ATTR_INSTANCE_VALUE ||
        buffer[pc].operand0 != (owner_value >> 3 & UINT16_MAX)) {
        return;
    }
    pc++;
    opcode = LXOR_NEXT();
    if (opcode != _POP_TOP && opcode != _POP_TOP_NOP) return;
    pc++;
    int body_end = pc;
    opcode = LXOR_NEXT();
    if ((opcode != _LOAD_CONST_INLINE &&
         opcode != _LOAD_CONST_INLINE_BORROW) ||
        (PyObject *)buffer[pc].operand0 != Py_None) return;
    pc++;
    LXOR_EXPECT(_RETURN_VALUE);

    uint32_t owner_version = (uint32_t)(owner_value >> 19);
    uint32_t item_version = (uint32_t)(first_values >> 19);
    if (owner_version == 0 || item_version == 0 ||
        (owner_value & ~UINT64_C(7)) !=
            (second_owner_value & ~UINT64_C(7)) ||
        (first_values & ~UINT64_C(7)) !=
            (second_values & ~UINT64_C(7)) ||
        item_version != (uint32_t)(first_index >> 19)) {
        return;
    }
    buffer[start].opcode = _XOR_ATTR_LIST_PAIR_LOCAL;
    buffer[start].oparg = (uint16_t)(owner_value >> 3);
    buffer[start].operand0 = owner_version |
        ((uint64_t)item_version << 32);
    buffer[start].operand1 = (uint16_t)(first_values >> 3) |
        ((uint64_t)(uint16_t)(first_index >> 3) << 16) |
        ((uint64_t)first_error_offset << 32);
    for (int i = start + 1; i < body_end; i++) {
        if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            buffer[i].opcode = _NOP;
        }
    }
#undef LXOR_EXPECT
#undef LXOR_NEXT
#endif
}

/* Prove the complete, read-only membership body:
 *
 *     return self.key in self.values
 *
 * Runtime specialization accepts an exact int key and exact set. The lookup
 * deopts rather than invoking equality for a colliding non-int set member. */
static bool
set_contains_body(PyCodeObject *code)
{
    if (code->co_argcount != 1 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 1 || code->co_nlocalsplus != 1 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define SET_CONTAINS_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define SET_CONTAINS_ARG(OP, ARG) do { \
    SET_CONTAINS_READ(OP); if (arg != (ARG)) return false; \
} while (0)
    SET_CONTAINS_ARG(RESUME, 0);
    SET_CONTAINS_ARG(LOAD_FAST_BORROW, 0);
    SET_CONTAINS_READ(LOAD_ATTR);
    if (arg & 1) return false;
    SET_CONTAINS_ARG(LOAD_FAST_BORROW, 0);
    SET_CONTAINS_READ(LOAD_ATTR);
    if (arg & 1) return false;
    SET_CONTAINS_ARG(CONTAINS_OP, 0);
    SET_CONTAINS_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef SET_CONTAINS_ARG
#undef SET_CONTAINS_READ
}

static void
inline_set_contains_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_0) ||
            buffer[start].oparg != 0) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 64; i--) {
            int opcode = buffer[i].opcode;
            if (opcode == _RECORD_CALLABLE || opcode == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
            if (opcode == _LOAD_CONST_INLINE ||
                opcode == _LOAD_CONST_INLINE_BORROW) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                    break;
                }
            }
        }
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !set_contains_body((PyCodeObject *)func->func_code)) {
            continue;
        }
        int end = Py_MIN(length, start + 64);
        int pc = start + 1;
#define SET_CONTAINS_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                             pc < end ? region_opcode(&buffer[pc]) : 0)
#define SET_CONTAINS_EXPECT(OP) do { \
    if (SET_CONTAINS_NEXT() != (OP)) { goto next_set_contains; } pc++; \
} while (0)
        if (SET_CONTAINS_NEXT() != _SAVE_RETURN_OFFSET) continue;
        pc++;
        SET_CONTAINS_EXPECT(_PUSH_FRAME);
        SET_CONTAINS_EXPECT(_TIER2_RESUME_CHECK);
        uint64_t key, set;
        pc = trivial_attribute_load(buffer, pc, end, 0, &key);
        if (pc < 0 || (key & 7) != 0) continue;
        pc = trivial_attribute_load(buffer, pc, end, 0, &set);
        if (pc < 0 || (set & 7) != 0) continue;
        SET_CONTAINS_EXPECT(_GUARD_TOS_ANY_SET);
        SET_CONTAINS_EXPECT(_CONTAINS_OP_SET);
        for (int i = 0; i < 2; i++) {
            int opcode = SET_CONTAINS_NEXT();
            if (opcode != _POP_TOP && opcode != _POP_TOP_NOP) {
                goto next_set_contains;
            }
            pc++;
        }
        SET_CONTAINS_EXPECT(_RETURN_VALUE);
        uint32_t type_version = (uint32_t)(key >> 19);
        if (type_version == 0 || type_version != (uint32_t)(set >> 19)) {
            continue;
        }
        buffer[start].opcode = _CALL_PY_SET_CONTAINS;
        buffer[start].oparg = 0;
        buffer[start].operand0 = (uintptr_t)func;
        buffer[start].operand1 = type_version |
            ((uint64_t)(uint16_t)(key >> 3) << 32) |
            ((uint64_t)(uint16_t)(set >> 3) << 48);
        for (int i = start + 1; i < pc; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = pc - 1;
next_set_contains:
        ;
#undef SET_CONTAINS_EXPECT
#undef SET_CONTAINS_NEXT
    }
#endif
}

/* Prove the complete, read-only body:
 *
 *     if not item.used:
 *         for member in item.members:
 *             if member.value == GLOBAL:
 *                 return True
 *     return False
 *
 * Attribute and global names are obtained from bytecode; no application names
 * are special. The runtime specialization only accepts callback-free values. */
static bool
list_any_attr_body(PyCodeObject *code, uint8_t *global_name,
                   uint32_t *return_offsets, uint16_t *loop_offset)
{
    if (code->co_argcount != 2 || code->co_kwonlyargcount != 0 ||
        code->co_nlocals != 3 || code->co_nlocalsplus != 3 ||
        code->co_ncellvars != 0 || code->co_nfreevars != 0 ||
        PyBytes_GET_SIZE(code->co_exceptiontable) != 0 ||
        !(code->co_flags & CO_OPTIMIZED) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                           CO_COROUTINE | CO_ASYNC_GENERATOR))) {
        return false;
    }
    int pc = 0, op, arg;
#define ANY_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define ANY_ARG(OP, ARG) do { ANY_READ(OP); if (arg != (ARG)) return false; } while (0)
    ANY_ARG(RESUME, 0);
    ANY_ARG(LOAD_FAST_BORROW, 1);
    ANY_READ(LOAD_ATTR);
    if (arg & 1) return false;
    ANY_ARG(TO_BOOL, 0);
    ANY_READ(POP_JUMP_IF_TRUE);
    int false_return = pc + arg;
    ANY_ARG(NOT_TAKEN, 0);
    ANY_ARG(LOAD_FAST_BORROW, 1);
    ANY_READ(LOAD_ATTR);
    if (arg & 1) return false;
    ANY_ARG(GET_ITER, 0);
    int loop = pc;
    ANY_READ(FOR_ITER);
    int exhausted = pc + arg;
    ANY_ARG(STORE_FAST, 2);
    ANY_ARG(LOAD_FAST_BORROW, 2);
    ANY_READ(LOAD_ATTR);
    if (arg & 1) return false;
    ANY_READ(LOAD_GLOBAL);
    if ((arg & 1) || (arg >> 1) > UINT8_MAX) return false;
    *global_name = (uint8_t)(arg >> 1);
    ANY_READ(COMPARE_OP);
    if (!(arg & 16) || (arg >> 5) != Py_EQ) return false;
    ANY_READ(POP_JUMP_IF_TRUE);
    int true_return = pc + arg;
    ANY_ARG(NOT_TAKEN, 0);
    if (pc > UINT16_MAX) return false;
    *loop_offset = (uint16_t)pc;
    ANY_READ(JUMP_BACKWARD);
    if (pc - arg != loop || pc != true_return) return false;
    ANY_ARG(POP_TOP, 0);
    ANY_ARG(POP_TOP, 0);
    ANY_ARG(LOAD_COMMON_CONSTANT, CONSTANT_TRUE);
    if (pc > UINT16_MAX) return false;
    *return_offsets = (uint16_t)pc;
    ANY_ARG(RETURN_VALUE, 0);
    if (pc != exhausted) return false;
    ANY_ARG(END_FOR, 0);
    ANY_ARG(POP_ITER, 0);
    if (pc != false_return) return false;
    ANY_ARG(LOAD_COMMON_CONSTANT, CONSTANT_FALSE);
    if (pc > UINT16_MAX) return false;
    *return_offsets |= (uint32_t)(uint16_t)pc << 16;
    ANY_ARG(RETURN_VALUE, 0);
    return pc == Py_SIZE(code);
#undef ANY_ARG
#undef ANY_READ
}

static void
inline_list_any_attr_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_1) ||
            buffer[start].oparg != 1) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 64; i--) {
            int opcode = buffer[i].opcode;
            if (opcode == _RECORD_CALLABLE || opcode == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
            if (opcode == _LOAD_CONST_INLINE ||
                opcode == _LOAD_CONST_INLINE_BORROW) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                    break;
                }
            }
        }
        uint8_t global_name;
        uint32_t return_offsets;
        uint16_t loop_offset;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !list_any_attr_body((PyCodeObject *)func->func_code, &global_name,
                                &return_offsets, &loop_offset)) {
            continue;
        }
        (void)loop_offset;
        int end = Py_MIN(length, start + 192);
        int pc = start + 1;
#define ANY_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                    pc < end ? region_opcode(&buffer[pc]) : 0)
#define ANY_EXPECT(OP) do { \
    if (ANY_NEXT() != (OP)) { goto next_any; } pc++; \
} while (0)
        ANY_EXPECT(_SAVE_RETURN_OFFSET);
        ANY_EXPECT(_PUSH_FRAME);
        ANY_EXPECT(_TIER2_RESUME_CHECK);
        uint64_t used, members, value;
        pc = trivial_attribute_load(buffer, pc, end, 1, &used);
        if (pc < 0) goto next_any;
        if (ANY_NEXT() != _TO_BOOL_BOOL) goto next_any;
        pc++;
        int opcode = ANY_NEXT();
        if (opcode != _GUARD_BIT_IS_SET_POP &&
            opcode != _GUARD_BIT_IS_UNSET_POP) goto next_any;
        pc++;
        pc = trivial_attribute_load(buffer, pc, end, 1, &members);
        if (pc < 0) goto next_any;

        bool got_value = false;
        for (int scan = pc; scan < end; scan++) {
            opcode = region_opcode(&buffer[scan]);
            if (opcode == _PUSH_FRAME || opcode == _RETURN_VALUE ||
                opcode == _DYNAMIC_EXIT || opcode == _EXIT_TRACE ||
                opcode == _DEOPT || opcode == _JUMP_TO_TOP) {
                break;
            }
            int after = trivial_attribute_load(buffer, scan, end, 2, &value);
            if (after >= 0) {
                pc = after;
                got_value = true;
                break;
            }
        }
        if (!got_value) goto next_any;

        int returned = -1;
        int recorded_result = -1;
        for (int scan = pc; scan < end; scan++) {
            opcode = region_opcode(&buffer[scan]);
            if ((opcode == _LOAD_CONST_INLINE ||
                 opcode == _LOAD_CONST_INLINE_BORROW) &&
                ((PyObject *)buffer[scan].operand0 == Py_True ||
                 (PyObject *)buffer[scan].operand0 == Py_False)) {
                recorded_result =
                    (PyObject *)buffer[scan].operand0 == Py_True;
            }
            if (opcode == _RETURN_VALUE) {
                returned = scan + 1;
                break;
            }
            if (opcode == _PUSH_FRAME || opcode == _DYNAMIC_EXIT ||
                opcode == _EXIT_TRACE || opcode == _DEOPT ||
                opcode == _JUMP_TO_TOP) {
                break;
            }
        }
        uint32_t item_version = (uint32_t)(used >> 19);
        uint32_t member_version = (uint32_t)(value >> 19);
        uint64_t used_offset = (used >> 3) & UINT16_MAX;
        uint64_t members_offset = (members >> 3) & UINT16_MAX;
        uint64_t value_offset = (value >> 3) & UINT16_MAX;
        if (returned < 0 || recorded_result < 0 ||
            item_version == 0 || member_version == 0 ||
            item_version != (uint32_t)(members >> 19) ||
            used_offset % sizeof(PyObject *) ||
            members_offset % sizeof(PyObject *) ||
            value_offset % sizeof(PyObject *) ||
            used_offset / sizeof(PyObject *) > UINT8_MAX ||
            members_offset / sizeof(PyObject *) > UINT8_MAX ||
            value_offset / sizeof(PyObject *) > UINT8_MAX) {
            goto next_any;
        }
        buffer[start].opcode = _CALL_PY_LIST_ANY_ATTR;
        buffer[start].oparg = 0;
        buffer[start].operand0 = item_version |
            ((uint64_t)member_version << 32);
        buffer[start].operand1 = used_offset / sizeof(PyObject *) |
            ((members_offset / sizeof(PyObject *)) << 8) |
            ((value_offset / sizeof(PyObject *)) << 16) |
            ((uint64_t)global_name << 24) |
            ((uint64_t)recorded_result << 32);
        for (int i = start + 1; i < returned; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        start = returned - 1;
next_any:
        ;
#undef ANY_EXPECT
#undef ANY_NEXT
    }
#endif
}

/* Keep the real callee frame when a call trace ends in the list loop.  The
 * complete bytecode proof supplies both return offsets, so the specialized
 * uop can scan the list and leave Tier 1 to execute the matching
 * RETURN_VALUE. */
static void
inline_local_list_any_attr_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        if ((buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS &&
             buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS_1) ||
            buffer[start].oparg != 1) {
            continue;
        }
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 64; i--) {
            int opcode = buffer[i].opcode;
            if (opcode == _RECORD_CALLABLE || opcode == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) {
                    obj = PyMethod_GET_FUNCTION(obj);
                }
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                }
                break;
            }
            if (opcode == _LOAD_CONST_INLINE ||
                opcode == _LOAD_CONST_INLINE_BORROW) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyFunction_Check(obj)) {
                    func = (PyFunctionObject *)obj;
                    break;
                }
            }
        }
        uint8_t global_name;
        uint32_t return_offsets;
        uint16_t loop_offset;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !list_any_attr_body((PyCodeObject *)func->func_code, &global_name,
                                &return_offsets, &loop_offset)) {
            continue;
        }
        (void)loop_offset;
        int end = Py_MIN(length, start + 192);
        int pc = start + 1;
#define LOCAL_ANY_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                          pc < end ? region_opcode(&buffer[pc]) : 0)
#define LOCAL_ANY_EXPECT(OP) do { \
    if (LOCAL_ANY_NEXT() != (OP)) { goto next_local_any; } pc++; \
} while (0)
        LOCAL_ANY_EXPECT(_SAVE_RETURN_OFFSET);
        LOCAL_ANY_EXPECT(_PUSH_FRAME);
        LOCAL_ANY_EXPECT(_TIER2_RESUME_CHECK);
        int body_start = trivial_call_skip(buffer, pc, end);
        pc = body_start;
        uint64_t used, members, value;
        pc = trivial_attribute_load(buffer, pc, end, 1, &used);
        if (pc < 0) goto next_local_any;
        if (LOCAL_ANY_NEXT() != _TO_BOOL_BOOL) goto next_local_any;
        pc++;
        int opcode = LOCAL_ANY_NEXT();
        if (opcode != _GUARD_BIT_IS_SET_POP &&
            opcode != _GUARD_BIT_IS_UNSET_POP) {
            goto next_local_any;
        }
        pc++;
        pc = trivial_attribute_load(buffer, pc, end, 1, &members);
        if (pc < 0) goto next_local_any;

        bool got_value = false;
        for (int scan = pc; scan < end; scan++) {
            opcode = region_opcode(&buffer[scan]);
            if (opcode == _PUSH_FRAME || opcode == _RETURN_VALUE ||
                opcode == _DYNAMIC_EXIT || opcode == _EXIT_TRACE ||
                opcode == _DEOPT || opcode == _JUMP_TO_TOP) {
                break;
            }
            int after = trivial_attribute_load(buffer, scan, end, 2, &value);
            if (after >= 0) {
                got_value = true;
                break;
            }
        }
        if (!got_value) goto next_local_any;

        uint32_t item_version = (uint32_t)(used >> 19);
        uint32_t member_version = (uint32_t)(value >> 19);
        uint64_t used_offset = (used >> 3) & UINT16_MAX;
        uint64_t members_offset = (members >> 3) & UINT16_MAX;
        uint64_t value_offset = (value >> 3) & UINT16_MAX;
        if (body_start >= length - 1 || item_version == 0 ||
            member_version == 0 ||
            item_version != (uint32_t)(members >> 19) ||
            used_offset % sizeof(PyObject *) ||
            members_offset % sizeof(PyObject *) ||
            value_offset % sizeof(PyObject *) ||
            used_offset / sizeof(PyObject *) > UINT8_MAX ||
            members_offset / sizeof(PyObject *) > UINT8_MAX ||
            value_offset / sizeof(PyObject *) > UINT8_MAX) {
            goto next_local_any;
        }
        buffer[body_start].opcode = _LIST_ANY_ATTR_LOCAL;
        buffer[body_start].oparg = 0;
        buffer[body_start].operand0 = item_version |
            ((uint64_t)member_version << 32);
        buffer[body_start].operand1 = used_offset / sizeof(PyObject *) |
            ((members_offset / sizeof(PyObject *)) << 8) |
            ((value_offset / sizeof(PyObject *)) << 16) |
            ((uint64_t)global_name << 24) |
            ((uint64_t)return_offsets << 32);
        for (int i = body_start + 1; i < length; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[length - 1].opcode = _DYNAMIC_EXIT;
        buffer[length - 1].oparg = 0;
        buffer[length - 1].target = 0;
        buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
        return;
next_local_any:
        ;
#undef LOCAL_ANY_EXPECT
#undef LOCAL_ANY_NEXT
    }
#endif
}

/* Finish a proven list scan from an executor attached to its FOR_ITER.  The
 * iterator and tagged index already on the frame stack identify the remaining
 * suffix, so this avoids one executor trip per member. */
static void
inline_local_list_any_attr_loop(_PyThreadStateImpl *tstate,
                                _PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__) || defined(Py_GIL_DISABLED)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    const _PyJitTracerState *tracer = tstate->jit_tracer_state;
    PyCodeObject *code = tracer->initial_state.code;
    uint8_t global_name;
    uint32_t return_offsets;
    uint16_t loop_offset;
    if (!list_any_attr_body(code, &global_name, &return_offsets,
                            &loop_offset) ||
        tracer->initial_state.start_instr != _PyCode_CODE(code) + loop_offset ||
        tracer->initial_state.stack_depth != 2) {
        return;
    }
    int pc = 0;
    if (length < 8 || buffer[pc++].opcode != _START_EXECUTOR) return;
    if (buffer[pc].opcode == _MAKE_WARM) pc++;
    pc = trivial_call_skip(buffer, pc, length);
    if (pc < length && buffer[pc].opcode == _CHECK_PERIODIC) pc++;
    pc = trivial_call_skip(buffer, pc, length);
    int start = pc;
    if (pc >= length || buffer[pc++].opcode != _ITER_CHECK_LIST) return;
    pc = trivial_call_skip(buffer, pc, length);
    if (pc >= length || buffer[pc++].opcode != _GUARD_NOT_EXHAUSTED_LIST) {
        return;
    }
    pc = trivial_call_skip(buffer, pc, length);
    if (pc >= length || buffer[pc++].opcode != _ITER_NEXT_LIST_TIER_TWO) {
        return;
    }
    uint64_t value = 0;
    bool got_value = false;
    for (int scan = pc; scan < length; scan++) {
        int opcode = region_opcode(&buffer[scan]);
        if (opcode == _PUSH_FRAME || opcode == _RETURN_VALUE ||
            opcode == _DYNAMIC_EXIT || opcode == _EXIT_TRACE ||
            opcode == _DEOPT || opcode == _JUMP_TO_TOP) {
            break;
        }
        if (trivial_attribute_load(buffer, scan, length, 2, &value) >= 0) {
            got_value = true;
            break;
        }
    }
    uint32_t member_version = (uint32_t)(value >> 19);
    uint64_t value_offset = (value >> 3) & UINT16_MAX;
    if (!got_value || start >= length - 1 || member_version == 0 ||
        value_offset % sizeof(PyObject *) ||
        value_offset / sizeof(PyObject *) > UINT8_MAX) {
        return;
    }
    buffer[start].opcode = _LIST_ANY_ATTR_ITER_LOCAL;
    buffer[start].oparg = 0;
    buffer[start].operand0 = member_version;
    buffer[start].operand1 = value_offset / sizeof(PyObject *) |
        ((uint64_t)global_name << 8) |
        ((uint64_t)return_offsets << 16);
    for (int i = start + 1; i < length; i++) {
        if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            buffer[i].opcode = _NOP;
        }
    }
    buffer[length - 1].opcode = _DYNAMIC_EXIT;
    buffer[length - 1].oparg = 0;
    buffer[length - 1].target = 0;
    buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
#endif
}

/* A complete conditional removal body. Prove both branches before omitting
 * the callee, including that the mutating method is exactly list.remove. */
static bool
list_remove_body(PyCodeObject *code, uint64_t *returns)
{
    if (code->co_argcount != 3 || code->co_kwonlyargcount ||
        Py_SIZE(code) > UINT16_MAX || code->co_nlocalsplus != 3 || PyBytes_GET_SIZE(code->co_exceptiontable) ||
        (code->co_flags & (CO_VARARGS | CO_VARKEYWORDS | CO_GENERATOR |
                          CO_COROUTINE | CO_ASYNC_GENERATOR))) return false;
    int pc = 0, op, arg;
#define REMOVE_READ(OP) do { \
    if (!pair_scan_instruction(code, &pc, &op, &arg) || op != (OP)) return false; \
} while (0)
#define REMOVE_ARG(OP, ARG) do { REMOVE_READ(OP); if (arg != (ARG)) return false; } while (0)
    REMOVE_ARG(RESUME, 0);
    REMOVE_ARG(LOAD_FAST_BORROW_LOAD_FAST_BORROW, 0x20);
    REMOVE_READ(LOAD_ATTR);
    if (arg & 1) return false;
    int attribute = arg;
    REMOVE_ARG(LOAD_FAST_BORROW, 1);
    REMOVE_ARG(BINARY_OP, NB_SUBSCR);
    REMOVE_ARG(CONTAINS_OP, 0);
    REMOVE_READ(POP_JUMP_IF_FALSE);
    int missing = pc + arg;
    REMOVE_READ(NOT_TAKEN);
    REMOVE_ARG(LOAD_FAST_BORROW, 0);
    REMOVE_ARG(LOAD_ATTR, attribute);
    REMOVE_ARG(LOAD_FAST_BORROW, 1);
    REMOVE_ARG(BINARY_OP, NB_SUBSCR);
    REMOVE_READ(LOAD_ATTR);
    if (!(arg & 1) || (arg >> 1) >= PyTuple_GET_SIZE(code->co_names) ||
        !PyUnicode_CheckExact(PyTuple_GET_ITEM(code->co_names, arg >> 1)) ||
        PyUnicode_CompareWithASCIIString(PyTuple_GET_ITEM(code->co_names, arg >> 1),
                                       "remove") != 0) return false;
    REMOVE_ARG(LOAD_FAST_BORROW, 2);
    REMOVE_ARG(CALL, 1);
    REMOVE_READ(POP_TOP);
    REMOVE_ARG(LOAD_COMMON_CONSTANT, CONSTANT_TRUE);
    *returns = (uint64_t)pc << 16;
    REMOVE_READ(RETURN_VALUE);
    if (pc != missing) return false;
    REMOVE_ARG(LOAD_COMMON_CONSTANT, CONSTANT_FALSE);
    *returns |= pc;
    REMOVE_READ(RETURN_VALUE);
    return pc == Py_SIZE(code);
#undef REMOVE_ARG
#undef REMOVE_READ
}

static void
inline_list_remove_calls(_PyUOpInstruction *buffer, int length)
{
#if defined(WITH_DTRACE) || defined(__EMSCRIPTEN__)
    return;
#else
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    for (int start = 0; start < length; start++) {
        int nargs = buffer[start].oparg;
        if (buffer[start].opcode != _INIT_CALL_PY_EXACT_ARGS ||
            nargs < 2 || nargs > 3) continue;
        PyFunctionObject *func = NULL;
        for (int i = start - 1; i >= 0 && i >= start - 16; i--) {
            int op = buffer[i].opcode;
            if (op == _RECORD_CALLABLE || op == _RECORD_BOUND_METHOD) {
                PyObject *obj = (PyObject *)buffer[i].operand0;
                if (obj != NULL && PyMethod_Check(obj)) obj = PyMethod_GET_FUNCTION(obj);
                if (obj != NULL && PyFunction_Check(obj)) func = (PyFunctionObject *)obj;
                break;
            }
        }
        uint64_t returns;
        if (func == NULL || !_PyFunction_IsVersionValid(func->func_version) ||
            !list_remove_body((PyCodeObject *)func->func_code, &returns)) continue;
        int end = Py_MIN(length, start + 64);
        int pc = start + 1;
#define REMOVE_NEXT() (pc = trivial_call_skip(buffer, pc, end), \
                       pc < end ? region_opcode(&buffer[pc]) : 0)
#define REMOVE_EXPECT(OP) do { if (REMOVE_NEXT() != (OP)) goto next_remove; pc++; } while (0)
        if (REMOVE_NEXT() != _SAVE_RETURN_OFFSET) continue;
        uint64_t options = (uint64_t)buffer[pc++].oparg << 48;
        REMOVE_EXPECT(_PUSH_FRAME);
        REMOVE_EXPECT(_TIER2_RESUME_CHECK);
        int op = REMOVE_NEXT();
        if ((op != _LOAD_FAST && op != _LOAD_FAST_BORROW) || buffer[pc++].oparg != 2) continue;
        uint64_t descriptor;
        if (trivial_attribute_load(buffer, pc, end, 2, &descriptor) < 0 ||
            (descriptor & 7) != 0) continue;
        buffer[start].opcode = _CALL_PY_LIST_REMOVE;
        buffer[start].oparg = nargs - 2;
        buffer[start].operand0 = descriptor;
        buffer[start].operand1 = options | func->func_version;
        /* Both original returns are proved. The mutation completes before
         * leaving this trace at the instruction following the caller's CALL. */
        for (int i = start + 1; i < length; i++) {
            if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
                buffer[i].opcode = _NOP;
            }
        }
        buffer[length - 1].opcode = _DYNAMIC_EXIT;
        buffer[length - 1].oparg = 0;
        buffer[length - 1].target = 0;
        buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
        return;
next_remove:
        ;
#undef REMOVE_EXPECT
#undef REMOVE_NEXT
    }
#endif
}

static void
inline_local_list_remove(_PyThreadStateImpl *tstate, _PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_CALL_REGIONS")) return;
    const _PyJitTracerState *tracer = tstate->jit_tracer_state;
    PyCodeObject *code = tracer->initial_state.code;
    uint64_t returns;
    if (tracer->initial_state.start_instr != _PyCode_CODE(code) ||
        tracer->initial_state.stack_depth != 0 ||
        !list_remove_body(code, &returns)) return;
    int pc = 0;
    if (length < 4 || buffer[pc++].opcode != _START_EXECUTOR) return;
    if (buffer[pc].opcode == _MAKE_WARM) pc++;
    pc = trivial_call_skip(buffer, pc, length);
    if (pc >= length || buffer[pc++].opcode != _TIER2_RESUME_CHECK) return;
    pc = trivial_call_skip(buffer, pc, length);
    int start = pc;
    if (pc >= length || (region_opcode(&buffer[pc]) != _LOAD_FAST_BORROW &&
                         region_opcode(&buffer[pc]) != _LOAD_FAST) ||
        buffer[pc++].oparg != 2) return;
    uint64_t descriptor;
    if (trivial_attribute_load(buffer, pc, length, 2, &descriptor) < 0 ||
        (descriptor & 7) != 0) return;
    buffer[start].opcode = _LIST_REMOVE_LOCAL;
    buffer[start].oparg = 0;
    buffer[start].operand0 = descriptor;
    buffer[start].operand1 = returns;
    for (int i = start + 1; i < length; i++) {
        if (!(_PyUop_Flags[buffer[i].opcode] & HAS_RECORDS_VALUE_FLAG)) {
            buffer[i].opcode = _NOP;
        }
    }
    buffer[length - 1].opcode = _DYNAMIC_EXIT;
    buffer[length - 1].oparg = 0;
    buffer[length - 1].target = 0;
    buffer[length - 1].operand0 = buffer[length - 1].operand1 = 0;
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

static void
inline_zip_list_pairs(_PyUOpInstruction *buffer, int length)
{
    if (!region_enabled("PYTHON_TIER2_BUILTIN_REGIONS")) {
        return;
    }
    for (int pc = 0; pc < length; pc++) {
        if (buffer[pc].opcode != _GUARD_TYPE_ITER ||
            buffer[pc].operand0 != (uintptr_t)&PyZip_Type) {
            continue;
        }
        int end = Py_MIN(pc + 8, length);
        int next = region_skip(buffer, pc + 1, end);
        if (next < end && buffer[next].opcode == _ITER_NEXT_INLINE &&
            buffer[next].operand0 == (uintptr_t)PyZip_Type.tp_iternext) {
            buffer[next].opcode = _ITER_NEXT_ZIP_LIST_PAIR;
            /* Keep exhaustion's after-END_FOR target. Errors still belong
             * to the original FOR_ITER instruction, before any cleanup. */
            buffer[next].operand0 = buffer[pc].target;
        }
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

    length = remove_folded_constant_traffic(output, length);
    eliminate_trivial_frames(output, length);
    inline_conditional_attribute_calls(output, length);
    inline_list_equality_scan(output, length);
    inline_list_attribute_calls(output, length);
    inline_attribute_search_calls(output, length);
    inline_reference_root_default_calls(output, length);
    inline_reference_root_calls(output, length);
    inline_local_reference_root(tstate, output, length);
    inline_list_set_pair_calls(output, length);
    inline_local_list_set_pair(tstate, output, length);
    inline_xor_attr_list_pair_calls(output, length);
    inline_local_xor_attr_list_pair(tstate, output, length);
    inline_list_any_attr_calls(output, length);
    inline_local_list_any_attr_calls(output, length);
    inline_local_list_any_attr_loop(tstate, output, length);
    inline_set_contains_calls(output, length);
    inline_list_remove_calls(output, length);
    inline_local_list_remove(tstate, output, length);
    inline_attribute_initializers(output, length);
    fuse_list_pair_comparisons(output, length);
    inline_list_pair_append_scan(tstate, output, length);
    fuse_list_length_predicates(output, length);
    fuse_dict_pair_increments(output, length);
    inline_sum_list_int_contains(output, length);
    inline_enumerate_list(output, length);
    inline_zip_list_pairs(output, length);
    inline_enumerate_int_scan(output, length);
    length = remove_unneeded_uops(output, length);
    assert(length > 0);
    fuse_float_attribute_products(output, length);
    inline_float_dot_calls(output, length);
    fuse_float_product_updates(output, length);

    OPT_STAT_INC(optimizer_successes);
    return length;
}

/* Try the callback-free equivalent of
 *
 *     max(mapping, key=lambda key: mapping[key])
 *
 * The caller has already checked the max callable, positional layout, and
 * opt-in. A successful return is a new reference. NULL means that the caller
 * must execute the ordinary vectorcall; this helper never sets an exception. */
PyObject *
_Py_TryMaxDictIntKey(
    PyThreadState *tstate,
    _PyInterpreterFrame *frame,
    PyObject *mapping,
    PyObject *key_callable,
    PyObject *kwnames,
    Py_ssize_t *checked)
{
    *checked = 0;
    if (!PyTuple_CheckExact(kwnames) || PyTuple_GET_SIZE(kwnames) != 1 ||
        PyTuple_GET_ITEM(kwnames, 0) != &_Py_ID(key)) {
        return NULL;
    }

    PyTypeObject *mapping_type = Py_TYPE(mapping);
    if (!PyDict_Check(mapping) || mapping_type->tp_iter != PyDict_Type.tp_iter ||
        mapping_type->tp_as_mapping == NULL ||
        mapping_type->tp_as_mapping->mp_subscript !=
            PyDict_Type.tp_as_mapping->mp_subscript ||
        !Py_IS_TYPE(key_callable, &PyFunction_Type)) {
        return NULL;
    }

    PyFunctionObject *func = (PyFunctionObject *)key_callable;
    PyCodeObject *key_code = (PyCodeObject *)func->func_code;
    PyObject *closure = func->func_closure;
    if (func->vectorcall != _PyFunction_Vectorcall ||
        key_code->co_version == 0 || !_Py_MaxDictIntKeyBody(key_code) ||
        closure == NULL || !PyTuple_CheckExact(closure) ||
        PyTuple_GET_SIZE(closure) != 1) {
        return NULL;
    }
    PyObject *cell = PyTuple_GET_ITEM(closure, 0);
    if (!PyCell_Check(cell) || PyCell_GET(cell) != mapping ||
        tstate->interp->eval_frame != NULL ||
        tstate->py_recursion_remaining <= 1) {
        return NULL;
    }

    PyCodeObject *caller_code = _PyFrame_GetCode(frame);
    uintptr_t instrumentation_version =
        FT_ATOMIC_LOAD_UINTPTR_ACQUIRE(key_code->_co_instrumentation_version);
    if (_Py_atomic_load_uintptr_relaxed(&tstate->eval_breaker) !=
            instrumentation_version ||
        FT_ATOMIC_LOAD_UINTPTR_ACQUIRE(
            caller_code->_co_instrumentation_version) !=
            instrumentation_version) {
        return NULL;
    }
    for (int which = 0; which < 2; which++) {
        PyCodeObject *code = which == 0 ? caller_code : key_code;
        _PyCoMonitoringData *monitoring = code->_co_monitoring;
        for (int event = 0; event < _PY_MONITORING_UNGROUPED_EVENTS; event++) {
            uint8_t tools = monitoring != NULL
                ? monitoring->active_monitors.tools[event]
                : tstate->interp->monitors.tools[event];
            if (tools != 0) {
                return NULL;
            }
        }
    }

    PyObject *best_key = NULL;
    Py_ssize_t best_value = 0;
    Py_ssize_t position = 0;
    PyObject *dict_key;
    PyObject *dict_value;
    while (PyDict_Next(mapping, &position, &dict_key, &dict_value)) {
        if (_Py_atomic_load_uintptr_relaxed(&tstate->eval_breaker) !=
                instrumentation_version) {
            return NULL;
        }
        (*checked)++;
        if (!PyTuple_CheckExact(dict_key) ||
            PyTuple_GET_SIZE(dict_key) != 2 ||
            !PyBytes_CheckExact(PyTuple_GET_ITEM(dict_key, 0)) ||
            !PyBytes_CheckExact(PyTuple_GET_ITEM(dict_key, 1)) ||
            !PyLong_CheckExact(dict_value) ||
            !_PyLong_IsCompact((PyLongObject *)dict_value)) {
            return NULL;
        }
        Py_ssize_t value = _PyLong_CompactValue((PyLongObject *)dict_value);
        if (best_key == NULL || value > best_value) {
            best_key = dict_key;
            best_value = value;
        }
    }
    return best_key == NULL ? NULL : Py_NewRef(best_key);
}

#endif /* _Py_TIER2 */
