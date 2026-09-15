/* Shared compile-time interval proof for signed tagged integers. */

#ifndef Py_OPTIMIZER_REGION_BOUNDS_H
#define Py_OPTIMIZER_REGION_BOUNDS_H

#define REGION_VALUE_MAX (INT64_MAX >> Py_TAGGED_SHIFT)
#define REGION_VALUE_MIN (-REGION_VALUE_MAX - 1)
typedef struct {
    int64_t low;
    int64_t high;
} RegionBounds;

static bool
region_bounds(RegionBounds a, RegionBounds b, int operation, RegionBounds *out)
{
#if defined(__GNUC__) || defined(__clang__)
    int64_t values[4];
    if (operation == 0) {
        if (__builtin_add_overflow(a.low, b.low, &out->low) ||
            __builtin_add_overflow(a.high, b.high, &out->high)) {
            return false;
        }
    }
    else if (operation == 1) {
        if (__builtin_sub_overflow(a.low, b.high, &out->low) ||
            __builtin_sub_overflow(a.high, b.low, &out->high)) {
            return false;
        }
    }
    else if (operation == 2) {
        if (__builtin_mul_overflow(a.low, b.low, &values[0]) ||
            __builtin_mul_overflow(a.low, b.high, &values[1]) ||
            __builtin_mul_overflow(a.high, b.low, &values[2]) ||
            __builtin_mul_overflow(a.high, b.high, &values[3])) {
            return false;
        }
        out->low = out->high = values[0];
        for (int i = 1; i < 4; i++) {
            out->low = Py_MIN(out->low, values[i]);
            out->high = Py_MAX(out->high, values[i]);
        }
    }
    else {
        assert(operation == 3);
        if (b.low != b.high || b.low == 0) {
            return false;
        }
        int64_t divisor = b.low;
        int64_t low = divisor > 0 ? a.low : a.high;
        int64_t high = divisor > 0 ? a.high : a.low;
        /* Inputs are strictly inside int64, including for divisor -1. */
        out->low = low / divisor - ((low % divisor != 0) &&
                                    ((low < 0) != (divisor < 0)));
        out->high = high / divisor - ((high % divisor != 0) &&
                                      ((high < 0) != (divisor < 0)));
    }
    return out->low >= REGION_VALUE_MIN && out->high <= REGION_VALUE_MAX;
#else
    return false;
#endif
}

#endif
