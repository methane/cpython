
#ifndef Py_INTERNAL_DICT_H
#define Py_INTERNAL_DICT_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif


/* runtime lifecycle */

extern void _PyDict_Fini(PyInterpreterState *interp);


/* other API */

#ifndef WITH_FREELISTS
// without freelists
#  define PyDict_MAXFREELIST 0
#endif

#ifndef PyDict_MAXFREELIST
#  define PyDict_MAXFREELIST 80
#endif

struct _Py_dict_state {
#if PyDict_MAXFREELIST > 0
    /* Dictionary reuse scheme to save calls to malloc and free */
    PyDictObject *free_list[PyDict_MAXFREELIST];
    int numfree;
    PyDictKeysObject *keys_free_list[PyDict_MAXFREELIST];
    int keys_numfree;
#endif
};

typedef struct {
    /* Cached hash code of me_key. */
    Py_hash_t me_hash;
    PyObject *me_key;
    PyObject *me_value; /* This field is only meaningful for combined tables */
} PyDictKeyEntry;

/* _Py_dict_lookup() returns index of entry which can be used like DK_ENTRIES(dk)[index].
 * -1 when no entry found, -3 when compare raises error.
 */
Py_ssize_t _Py_dict_lookup(PyDictObject *mp, PyObject *key, Py_hash_t hash, PyObject **value_addr);

/* Consumes references to key and value */
int _PyDict_SetItem_Take2(PyDictObject *op, PyObject *key, PyObject *value);

#define DKIX_EMPTY (-1)
#define DKIX_ERROR (-3)

typedef enum {
    DICT_KEYS_GENERAL = 0,
    DICT_KEYS_UNICODE = 1,
    DICT_KEYS_SPLIT = 2
} DictKeysKind;

// Currently, we support only 8-wide.
// But it is possible to use 16-wide when SSE2 is available, but NEON can not optimize it.
#define GROUP_WIDTH (8)

typedef union {
    char c[GROUP_WIDTH];
    uint64_t u64;
} group_control;

typedef struct {
    group_control control;
    uint8_t index[GROUP_WIDTH];
} group8; // 16byte

typedef struct {
    group_control control;
    uint16_t index[GROUP_WIDTH];
} group16; // 24byte

typedef struct {
    group_control control;
    uint32_t index[GROUP_WIDTH];
} group32; // 40byte

typedef struct {
    group_control control;
    uint64_t index[GROUP_WIDTH];
} group64; // 72byte

// todo: group64 can use uint8_t index[7*GROUP_WIDTH] instead.
// Then sizeof(group64) become 64byte. It is friendly to cache line.


/* See dictobject.c for actual layout of DictKeysObject */
struct _dictkeysobject {
    Py_ssize_t dk_refcnt;

    /* Size of the hash table (dk_indices). It must be a power of 2. */
    uint8_t dk_log2_size;

    /* Kind of keys */
    uint8_t dk_kind;

    /* Version number -- Reset to 0 by any modification to keys */
    uint32_t dk_version;

    /* Number of usable entries in dk_entries. */
    Py_ssize_t dk_usable;

    /* Number of used entries in dk_entries. */
    Py_ssize_t dk_nentries;

    unsigned char dk_groups[];  /* char is required to avoid strict aliasing. */

    /* "PyDictKeyEntry dk_entries[dk_usable];" array follows:
       see the DK_ENTRIES() macro */
};

/* This must be no more than 250, for the prefix size to fit in one byte. */
#define SHARED_KEYS_MAX_SIZE 30
#define NEXT_LOG2_SHARED_KEYS_MAX_SIZE 6

/* Layout of dict values:
 *
 * The PyObject *values are preceded by an array of bytes holding
 * the insertion order and size.
 * [-1] = prefix size. [-2] = used size. size[-2-n...] = insertion order.
 */
struct _dictvalues {
    PyObject *values[1];
};

#define DK_LOG_SIZE(dk)  ((dk)->dk_log2_size+3)

#define DK_SIZE(dk)      (((int64_t)1)<<DK_LOG_SIZE(dk))
#define DK_GROUPS(dk)    (((int64_t)1)<<((dk)->dk_log2_size))

#define DK_GROUP_SIZE(dk)                    \
    (DK_LOG_SIZE(dk) <= 8 ? sizeof(group8)    \
     : DK_LOG_SIZE(dk) <= 16 ? sizeof(group16) \
     : DK_LOG_SIZE(dk) <= 32 ? sizeof(group32) \
     : sizeof(group64))

#define DK_ENTRIES(dk) \
    ((PyDictKeyEntry*)(&((dk)->dk_groups)[DK_GROUP_SIZE(dk) << ((dk)->dk_log2_size)]))

extern uint64_t _pydict_global_version;

#define DICT_NEXT_VERSION() (++_pydict_global_version)

PyObject *_PyObject_MakeDictFromInstanceAttributes(PyObject *obj, PyDictValues *values);

static inline void
_PyDictValues_AddToInsertionOrder(PyDictValues *values, Py_ssize_t ix)
{
    assert(ix < SHARED_KEYS_MAX_SIZE);
    uint8_t *size_ptr = ((uint8_t *)values)-2;
    int size = *size_ptr;
    assert(size+2 < ((uint8_t *)values)[-1]);
    size++;
    size_ptr[-size] = (uint8_t)ix;
    *size_ptr = size;
}

#ifdef __cplusplus
}
#endif
#endif   /* !Py_INTERNAL_DICT_H */
