/* Compile-time scalar expressions for polynomial coefficients. All runtime
 * arithmetic is emitted as ordinary tagged-integer uops, with no evaluator.
 * Failure leaves the existing, checked coefficient setup in place. */

#include "optimizer_region_bounds.h"

#define POLY_SCALAR_NODES 96
#define POLY_SCALAR_UOPS 96

enum { PS_CONST, PS_LOCAL, PS_ADD, PS_SUB, PS_MUL, PS_DIV, PS_EXACT_DIV };

typedef struct {
    int kind, left, right;
    int64_t value;
    RegionBounds bounds;
} PolyScalarNode;

typedef struct {
    PolyScalarNode nodes[POLY_SCALAR_NODES];
    int count;
    bool failed;
    _PyUOpInstruction output[POLY_SCALAR_UOPS];
    int used, depth, peak, target;
} PolyScalar;

static int
poly_scalar_node(PolyScalar *ps, int kind, int a, int b, int64_t value,
                 RegionBounds bounds)
{
    for (int i = 0; i < ps->count; i++) {
        PolyScalarNode *n = &ps->nodes[i];
        if (n->kind == kind && n->left == a && n->right == b && n->value == value) {
            return i;
        }
    }
    if (ps->count == POLY_SCALAR_NODES) {
        ps->failed = true;
        return 0;
    }
    ps->nodes[ps->count] = (PolyScalarNode){kind, a, b, value, bounds};
    return ps->count++;
}

static int
poly_scalar_const(PolyScalar *ps, int64_t value)
{
    if (value < REGION_VALUE_MIN || value > REGION_VALUE_MAX) {
        ps->failed = true;
        return 0;
    }
    return poly_scalar_node(ps, PS_CONST, 0, 0, value, (RegionBounds){value, value});
}

static int
poly_scalar_binary(PolyScalar *ps, int kind, int a, int b)
{
    if (ps->failed) {
        return 0;
    }
    PolyScalarNode x = ps->nodes[a], y = ps->nodes[b];
    /* Keep constants on the right of commutative operations. */
    if ((kind == PS_ADD || kind == PS_MUL) && x.kind == PS_CONST && y.kind != PS_CONST) {
        return poly_scalar_binary(ps, kind, b, a);
    }
    if (y.kind == PS_CONST) {
        if (y.value == 0 && (kind == PS_ADD || kind == PS_SUB)) {
            return a;
        }
        if (kind == PS_MUL && y.value == 0) {
            return b;
        }
        if (kind == PS_MUL && y.value == 1) {
            return a;
        }
    }
    if (kind == PS_SUB && a == b) {
        return poly_scalar_const(ps, 0);
    }
    if (kind == PS_ADD && a == b) {
        return poly_scalar_binary(ps, PS_MUL, a, poly_scalar_const(ps, 2));
    }
    /* Associate constants, exposing terms such as a+(a+1)+1 == 2*a+2. */
    if (kind == PS_ADD && y.kind == PS_ADD && ps->nodes[y.right].kind == PS_CONST) {
        int sum = poly_scalar_binary(ps, PS_ADD, a, y.left);
        return poly_scalar_binary(ps, PS_ADD, sum, y.right);
    }
    if (kind == PS_ADD && x.kind == PS_ADD && ps->nodes[x.right].kind == PS_CONST) {
        if (y.kind == PS_CONST) {
            int sum = poly_scalar_binary(ps, PS_ADD, x.right, b);
            return poly_scalar_binary(ps, PS_ADD, x.left, sum);
        }
        int sum = poly_scalar_binary(ps, PS_ADD, x.left, b);
        return poly_scalar_binary(ps, PS_ADD, sum, x.right);
    }
    RegionBounds bounds;
    if (!region_bounds(x.bounds, y.bounds, kind - PS_ADD, &bounds)) {
        ps->failed = true;
        return 0;
    }
    if (x.kind == PS_CONST && y.kind == PS_CONST) {
        assert(bounds.low == bounds.high);
        return poly_scalar_const(ps, bounds.low);
    }
    return poly_scalar_node(ps, kind, a, b, 0, bounds);
}

/* Return -1 unless divisibility follows structurally. This transformation
 * uses exact integer division, never distribution of rounded floor division. */
static int
poly_scalar_factor(PolyScalar *ps, int a, int64_t divisor)
{
    if (ps->failed) {
        return -1;
    }
    PolyScalarNode n = ps->nodes[a];
    if (divisor == 1) {
        return a;
    }
    if (n.kind == PS_CONST && n.value % divisor == 0) {
        return poly_scalar_const(ps, n.value / divisor);
    }
    if (n.kind == PS_MUL && ps->nodes[n.right].kind == PS_CONST &&
        ps->nodes[n.right].value % divisor == 0) {
        int factor = poly_scalar_const(ps, ps->nodes[n.right].value / divisor);
        return poly_scalar_binary(ps, PS_MUL, n.left, factor);
    }
    if (n.kind == PS_ADD || n.kind == PS_SUB) {
        int left = poly_scalar_factor(ps, n.left, divisor);
        int right = poly_scalar_factor(ps, n.right, divisor);
        if (left >= 0 && right >= 0) {
            return poly_scalar_binary(ps, n.kind, left, right);
        }
    }
    return -1;
}

static int
poly_scalar_divide(PolyScalar *ps, int a, int b, bool exact)
{
    PolyScalarNode divisor = ps->nodes[b];
    if (ps->failed || divisor.kind != PS_CONST || divisor.value == 0) {
        ps->failed = true;
        return 0;
    }
    int factored = poly_scalar_factor(ps, a, divisor.value);
    if (factored >= 0) {
        return factored;
    }
    if (!exact) {
        return poly_scalar_binary(ps, PS_DIV, a, b);
    }
    RegionBounds bounds;
    if (!region_bounds(ps->nodes[a].bounds, divisor.bounds, 3, &bounds)) {
        ps->failed = true;
        return 0;
    }
    return poly_scalar_node(ps, PS_EXACT_DIV, a, b, 0, bounds);
}

static void
poly_scalar_emit(PolyScalar *ps, int opcode, int arg, int64_t operand, int effect)
{
    if (ps->failed || ps->used == POLY_SCALAR_UOPS) {
        ps->failed = true;
        return;
    }
    ps->output[ps->used++] = (_PyUOpInstruction){.opcode = opcode, .oparg = arg,
        .operand0 = (uint64_t)operand, .target = ps->target};
    ps->depth += effect;
    ps->peak = Py_MAX(ps->peak, ps->depth);
    assert(ps->depth >= 0);
}

static void
poly_scalar_expression(PolyScalar *ps, int root)
{
    if (ps->failed) {
        return;
    }
    PolyScalarNode n = ps->nodes[root];
    if (n.kind == PS_CONST || n.kind == PS_LOCAL) {
        poly_scalar_emit(ps, n.kind == PS_CONST ? _POLY_SCALAR_CONST : _INT_REGION_LOCAL,
                         n.kind == PS_LOCAL ? (int)n.value : 0, n.value, 1);
        return;
    }
    poly_scalar_expression(ps, n.left);
    if (n.kind == PS_DIV || n.kind == PS_EXACT_DIV) {
        int64_t divisor = ps->nodes[n.right].value;
        bool exact = n.kind == PS_EXACT_DIV;
        if (divisor > 0 && ((uint64_t)divisor & ((uint64_t)divisor - 1)) == 0) {
            int shift = 0;
            while ((UINT64_C(1) << shift) != (uint64_t)divisor) {
                shift++;
            }
            poly_scalar_emit(ps, _POLY_SCALAR_RSHIFT, shift | (exact << 6), 0, 0);
        }
        else {
            poly_scalar_emit(ps, _POLY_SCALAR_DIVIDE, exact, divisor, 0);
        }
        return;
    }
    if (n.left == n.right) {
        poly_scalar_emit(ps, _INT_REGION_DUP, 0, 0, 1);
    }
    else {
        poly_scalar_expression(ps, n.right);
    }
    int operation = n.kind - PS_ADD;
    poly_scalar_emit(ps, _INT_REGION_BINARY_0 + operation, operation, 0, -1);
}

static int
simplify_poly_setup(_PyUOpInstruction *prefix, int used, int available)
{
    PolyScalar ps = {0};
    int poly[4][3] = {{0}};
    int zero = poly_scalar_const(&ps, 0), one = poly_scalar_const(&ps, 1);
    int begin = 0;
    while (begin < used && prefix[begin].opcode != _FLOAT_RANGE_GUARD) {
        begin++;
    }
    begin++;
    if (begin >= used) {
        return used;
    }
    ps.target = prefix[begin].target;
    for (int pc = begin; pc < used - 1; pc++) {
        _PyUOpInstruction *inst = &prefix[pc];
        int op = inst->opcode, slot = (int)inst->operand0;
        if (op == _POLY_LOCAL || op == _POLY_CONST || op == _POLY_INDUCTION) {
            int value = zero;
            if (op == _POLY_LOCAL) {
                value = poly_scalar_node(&ps, PS_LOCAL, 0, 0, inst->oparg,
                    (RegionBounds){-_PY_INT_REGION_INPUT_MAX, _PY_INT_REGION_INPUT_MAX});
            }
            else if (op == _POLY_CONST) {
                value = poly_scalar_const(&ps, inst->oparg);
            }
            poly[slot][0] = value;
            poly[slot][1] = op == _POLY_INDUCTION ? one : zero;
            poly[slot][2] = zero;
        }
        else if (op == _POLY_DUP) {
            memcpy(poly[inst->oparg + 1], poly[inst->oparg], sizeof(poly[0]));
        }
        else if (op == _POLY_RSHIFT || op == _POLY_BINARY_3) {
            int divisor;
            if (op == _POLY_RSHIFT) {
                divisor = poly_scalar_const(&ps, INT64_C(1) << inst->oparg);
            }
            else {
                if (poly[slot + 1][1] != zero || poly[slot + 1][2] != zero) {
                    return used;
                }
                divisor = poly[slot + 1][0];
            }
            for (int i = 0; i < 3; i++) {
                poly[slot][i] = poly_scalar_divide(&ps, poly[slot][i], divisor, i != 0);
            }
        }
        else if (op == _POLY_BINARY_0 || op == _POLY_BINARY_1) {
            for (int i = 0; i < 3; i++) {
                poly[slot][i] = poly_scalar_binary(&ps, PS_ADD + inst->oparg,
                                                  poly[slot][i], poly[slot + 1][i]);
            }
        }
        else if (op == _POLY_BINARY_2) {
            int *a = poly[slot], *b = poly[slot + 1];
            int c0 = poly_scalar_binary(&ps, PS_MUL, a[0], b[0]);
            int c1 = poly_scalar_binary(&ps, PS_ADD,
                poly_scalar_binary(&ps, PS_MUL, a[0], b[1]),
                poly_scalar_binary(&ps, PS_MUL, a[1], b[0]));
            int cross = poly_scalar_binary(&ps, PS_MUL, a[1], b[1]);
            c1 = poly_scalar_binary(&ps, PS_ADD, c1, cross);
            int c2 = poly_scalar_binary(&ps, PS_ADD,
                poly_scalar_binary(&ps, PS_MUL, a[0], b[2]),
                poly_scalar_binary(&ps, PS_MUL, a[2], b[0]));
            c2 = poly_scalar_binary(&ps, PS_ADD, c2,
                poly_scalar_binary(&ps, PS_MUL, cross, poly_scalar_const(&ps, 2)));
            a[0] = c0;
            a[1] = c1;
            a[2] = c2;
        }
        else {
            return used;
        }
        if (ps.failed) {
            return used;
        }
    }
    /* Exactness checks remain required even if a later simplification drops
     * their value. Store temporary results before writing the final triple. */
    for (int i = 0; i < ps.count; i++) {
        if (ps.nodes[i].kind == PS_EXACT_DIV) {
            poly_scalar_expression(&ps, i);
            poly_scalar_emit(&ps, _POLY_STORE_0, 0, 0, -1);
        }
    }
    for (int i = 0; i < 3; i++) {
        poly_scalar_expression(&ps, poly[0][i]);
        poly_scalar_emit(&ps, _POLY_STORE_0 + i, i, 0, -1);
    }
    assert(ps.failed || ps.depth == 0);
    if (ps.failed || ps.peak > available || begin + ps.used + 1 > POLY_SCALAR_UOPS) {
        return used;
    }
    _PyUOpInstruction reduce = prefix[used - 1];
    memcpy(prefix + begin, ps.output, ps.used * sizeof(*prefix));
    prefix[begin + ps.used] = reduce;
    return begin + ps.used + 1;
}
