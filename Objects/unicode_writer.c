/*

Unicode implementation based on original code by Fredrik Lundh,
modified by Marc-Andre Lemburg <mal@lemburg.com>.

Major speed upgrades to the method implementations at the Reykjavik
NeedForSpeed sprint, by Fredrik Lundh and Andrew Dalke.

Copyright (c) Corporation for National Research Initiatives.

--------------------------------------------------------------------
The original string type implementation is:

  Copyright (c) 1999 by Secret Labs AB
  Copyright (c) 1999 by Fredrik Lundh

By obtaining, using, and/or copying this software and/or its
associated documentation, you agree that you have read, understood,
and will comply with the following terms and conditions:

Permission to use, copy, modify, and distribute this software and its
associated documentation for any purpose and without fee is hereby
granted, provided that the above copyright notice appears in all
copies, and that both that copyright notice and this permission notice
appear in supporting documentation, and that the name of Secret Labs
AB or the author not be used in advertising or publicity pertaining to
distribution of the software without specific, written prior
permission.

SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO
THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS.  IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR BE LIABLE FOR
ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
--------------------------------------------------------------------

*/

#include "Python.h"
#include "pycore_bytesobject.h" // _PyBytes_RepeatBuffer()
#include "pycore_long.h"        // _PyLong_FormatWriter()
#include "pycore_freelist.h"      // _Py_FREELIST_FREE()
#include "pycore_unicodeobject.h" // _PyUnicode_Result()


#ifdef MS_WINDOWS
   /* On Windows, overallocate by 50% is the best factor */
#  define OVERALLOCATE_FACTOR 2
#else
   /* On Linux, overallocate by 25% is the best factor */
#  define OVERALLOCATE_FACTOR 4
#endif


/* Reserve bytes, keeping one extra byte as an overflow sentinel. */
static int
unicode_writer_reserve(_PyUnicodeWriter *writer, Py_ssize_t size)
{
    assert(writer->utf8_mode);
    if (size > PY_SSIZE_T_MAX - writer->utf8_pos - 1) {
        PyErr_NoMemory();
        return -1;
    }
    Py_ssize_t needed = writer->utf8_pos + size;
    if (needed <= writer->utf8_size) {
        return 0;
    }
    needed = Py_MAX(needed, writer->min_length);
    if (needed == PY_SSIZE_T_MAX) {
        PyErr_NoMemory();
        return -1;
    }
    if (writer->overallocate &&
        needed <= PY_SSIZE_T_MAX - 1 - needed / OVERALLOCATE_FACTOR) {
        needed += needed / OVERALLOCATE_FACTOR;
    }
    char *data = PyMem_Realloc(writer->utf8, needed + 1);
    if (data == NULL) {
        PyErr_NoMemory();
        return -1;
    }
    writer->utf8 = data;
    writer->utf8_size = needed;
    data[needed] = 0;
    return 0;
}

int
_PyUnicodeWriter_PrepareUTF8(_PyUnicodeWriter *writer, Py_ssize_t size)
{
    assert(size >= 0);
    if (writer->utf8_mode) {
        return unicode_writer_reserve(writer, size);
    }
    /* Prepare the replacement before releasing the old direct-write buffer:
       on allocation failure the logical contents are unchanged. */
    _PyUnicodeWriter replacement;
    _PyUnicodeWriter_Init(&replacement);
    replacement.overallocate = 1;
    replacement.min_length = writer->min_length;
    if ((writer->pos != 0 &&
         _PyUnicodeWriter_WriteSubstring(&replacement, writer->buffer,
                                          0, writer->pos) < 0) ||
        unicode_writer_reserve(&replacement, size) < 0) {
        _PyUnicodeWriter_Dealloc(&replacement);
        return -1;
    }
    Py_CLEAR(writer->buffer);
    writer->data = NULL;
    writer->kind = writer->maxchar = writer->size = writer->readonly = 0;
    writer->utf8_mode = 1;
    writer->utf8 = replacement.utf8;
    writer->utf8_pos = replacement.utf8_pos;
    writer->utf8_size = replacement.utf8_size;
    return 0;
}

int
_PyUnicodeWriter_RepeatUTF8(_PyUnicodeWriter *writer, const char *data,
                           Py_ssize_t size, Py_ssize_t length, Py_ssize_t count)
{
    assert(count >= 0 && size >= length && length >= 0);
    if (size == 0 || count == 0) {
        return 0;
    }
    if (count > PY_SSIZE_T_MAX / size) {
        PyErr_NoMemory();
        return -1;
    }
    Py_ssize_t total = count * size;
    if (_PyUnicodeWriter_PrepareUTF8(writer, total) < 0) {
        return -1;
    }
    _PyBytes_RepeatBuffer(_PyUnicodeWriter_UTF8Data(writer), total, data, size);
    _PyUnicodeWriter_AdvanceUTF8(writer, total, count * length);
    return 0;
}

int
_PyUnicodeWriter_WriteFill(_PyUnicodeWriter *writer, Py_UCS4 ch, Py_ssize_t count)
{
    unsigned char bytes[4];
    Py_ssize_t size = _PyUnicode_WriteUTF8Char(bytes, ch) - bytes;
    return _PyUnicodeWriter_RepeatUTF8(writer, (const char *)bytes, size, 1, count);
}

/* The caller supplies validated UTF-8/surrogatepass bytes and their length
   in code points. No public strict UTF-8 cache is populated. */
int
_PyUnicodeWriter_WriteUTF8(_PyUnicodeWriter *writer, const char *data,
                           Py_ssize_t size, Py_ssize_t length)
{
    assert(writer->utf8_mode);
    assert(size >= length && length >= 0);
    if (length > PY_SSIZE_T_MAX - writer->pos ||
        unicode_writer_reserve(writer, size) < 0) {
        if (!PyErr_Occurred()) {
            PyErr_NoMemory();
        }
        return -1;
    }
    if (size != 0) {
        memcpy(writer->utf8 + writer->utf8_pos, data, size);
    }
    _PyUnicodeWriter_AdvanceUTF8(writer, size, length);
    return 0;
}

void
_PyUnicodeWriter_Truncate(_PyUnicodeWriter *writer, Py_ssize_t pos)
{
    assert(0 <= pos && pos <= writer->pos);
    if (writer->utf8_mode) {
        while (writer->pos > pos) {
            do {
                writer->utf8_pos--;
            } while ((writer->utf8[writer->utf8_pos] & 0xc0) == 0x80);
            writer->pos--;
        }
    }
    else {
        writer->pos = pos;
    }
}

/* Direct-write clients still use character offsets and kind-specific
   pointers. Convert at that boundary; PrepareUTF8 can switch back to UTF-8. */
static int
unicode_writer_materialize(_PyUnicodeWriter *writer)
{
    if (writer->utf8_pos != 0) {
        PyObject *str = PyUnicode_DecodeUTF8(writer->utf8, writer->utf8_pos,
                                            "surrogatepass");
        if (str == NULL) {
            return -1;
        }
        writer->buffer = str;
        writer->readonly = 1;
        writer->maxchar = PyUnicode_MAX_CHAR_VALUE(str);
    }
    PyMem_Free(writer->utf8);
    writer->utf8 = NULL;
    writer->utf8_pos = writer->utf8_size = 0;
    writer->utf8_mode = 0;
    return 0;
}

/* Compilation of templated routines */

#define STRINGLIB_GET_EMPTY() _PyUnicode_GetEmpty()

#include "stringlib/ucs1lib.h"
#include "stringlib/find_max_char.h"
#include "stringlib/undef.h"


/* Copy an ASCII or latin1 char* string into a Python Unicode string.

   WARNING: The function doesn't copy the terminating null character and
   doesn't check the maximum character (may write a latin1 character in an
   ASCII string). */
static void
unicode_write_cstr(PyObject *unicode, Py_ssize_t index,
                   const char *str, Py_ssize_t len)
{
    int kind = PyUnicode_KIND(unicode);
    const void *data = PyUnicode_DATA(unicode);
    const char *end = str + len;

    assert(index + len <= PyUnicode_GET_LENGTH(unicode));
    switch (kind) {
    case PyUnicode_1BYTE_KIND: {
#ifdef Py_DEBUG
        if (PyUnicode_IS_ASCII(unicode)) {
            Py_UCS4 maxchar = ucs1lib_find_max_char(
                (const Py_UCS1*)str,
                (const Py_UCS1*)str + len);
            assert(maxchar < 128);
        }
#endif
        memcpy((char *) data + index, str, len);
        break;
    }
    case PyUnicode_2BYTE_KIND: {
        Py_UCS2 *start = (Py_UCS2 *)data + index;
        Py_UCS2 *ucs2 = start;

        for (; str < end; ++ucs2, ++str)
            *ucs2 = (Py_UCS2)*str;

        assert((ucs2 - start) <= PyUnicode_GET_LENGTH(unicode));
        break;
    }
    case PyUnicode_4BYTE_KIND: {
        Py_UCS4 *start = (Py_UCS4 *)data + index;
        Py_UCS4 *ucs4 = start;

        for (; str < end; ++ucs4, ++str)
            *ucs4 = (Py_UCS4)*str;

        assert((ucs4 - start) <= PyUnicode_GET_LENGTH(unicode));
        break;
    }
    default:
        Py_UNREACHABLE();
    }
}


static inline void
_PyUnicodeWriter_Update(_PyUnicodeWriter *writer)
{
    writer->maxchar = PyUnicode_MAX_CHAR_VALUE(writer->buffer);
    writer->data = writer->readonly ? NULL : PyUnicode_DATA(writer->buffer);

    if (!writer->readonly) {
        writer->kind = PyUnicode_KIND(writer->buffer);
        writer->size = PyUnicode_GET_LENGTH(writer->buffer);
    }
    else {
        /* use a value smaller than PyUnicode_1BYTE_KIND() so
           _PyUnicodeWriter_PrepareKind() will copy the buffer. */
        writer->kind = 0;
        assert(writer->kind <= PyUnicode_1BYTE_KIND);

        /* Copy-on-write mode: set buffer size to 0 so
         * _PyUnicodeWriter_Prepare() will copy (and enlarge) the buffer on
         * next write. */
        writer->size = 0;
    }
}


void
_PyUnicodeWriter_Init(_PyUnicodeWriter *writer)
{
    memset(writer, 0, sizeof(*writer));

    /* ASCII is the bare minimum */
    writer->min_char = 127;
    writer->utf8_mode = 1;

    /* use a kind value smaller than PyUnicode_1BYTE_KIND so
       _PyUnicodeWriter_PrepareKind() will copy the buffer. */
    assert(writer->kind == 0);
    assert(writer->kind < PyUnicode_1BYTE_KIND);
}


PyUnicodeWriter*
PyUnicodeWriter_Create(Py_ssize_t length)
{
    if (length < 0) {
        PyErr_SetString(PyExc_ValueError,
                        "length must be positive");
        return NULL;
    }

    const size_t size = sizeof(_PyUnicodeWriter);
    PyUnicodeWriter *pub_writer;
    pub_writer = _Py_FREELIST_POP_MEM(unicode_writers);
    if (pub_writer == NULL) {
        pub_writer = (PyUnicodeWriter *)PyMem_Malloc(size);
        if (pub_writer == NULL) {
            return (PyUnicodeWriter *)PyErr_NoMemory();
        }
    }
    _PyUnicodeWriter *writer = (_PyUnicodeWriter *)pub_writer;

    _PyUnicodeWriter_Init(writer);
    if (unicode_writer_reserve(writer, length) < 0) {
        PyUnicodeWriter_Discard(pub_writer);
        return NULL;
    }
    writer->overallocate = 1;

    return pub_writer;
}


void PyUnicodeWriter_Discard(PyUnicodeWriter *writer)
{
    if (writer == NULL) {
        return;
    }
    _PyUnicodeWriter_Dealloc((_PyUnicodeWriter*)writer);
    _Py_FREELIST_FREE(unicode_writers, writer, PyMem_Free);
}


// Initialize _PyUnicodeWriter with initial buffer
void
_PyUnicodeWriter_InitWithBuffer(_PyUnicodeWriter *writer, PyObject *buffer)
{
    memset(writer, 0, sizeof(*writer));
    writer->buffer = buffer;
    _PyUnicodeWriter_Update(writer);
    writer->min_length = writer->size;
}


int
_PyUnicodeWriter_PrepareInternal(_PyUnicodeWriter *writer,
                                 Py_ssize_t length, Py_UCS4 maxchar)
{
    Py_ssize_t newlen;
    PyObject *newbuffer;

    assert(length >= 0);
    assert(maxchar <= _Py_MAX_UNICODE);

    if (writer->utf8_mode && unicode_writer_materialize(writer) < 0) {
        return -1;
    }

    if (length > PY_SSIZE_T_MAX - writer->pos) {
        PyErr_NoMemory();
        return -1;
    }
    newlen = writer->pos + length;

    maxchar = Py_MAX(maxchar, writer->min_char);

    if (writer->buffer == NULL) {
        assert(!writer->readonly);
        if (writer->overallocate
            && newlen <= (PY_SSIZE_T_MAX - newlen / OVERALLOCATE_FACTOR)) {
            /* overallocate to limit the number of realloc() */
            newlen += newlen / OVERALLOCATE_FACTOR;
        }
        if (newlen < writer->min_length)
            newlen = writer->min_length;

        writer->buffer = PyUnicode_New(newlen, maxchar);
        if (writer->buffer == NULL)
            return -1;
    }
    else if (newlen > writer->size) {
        if (writer->overallocate
            && newlen <= (PY_SSIZE_T_MAX - newlen / OVERALLOCATE_FACTOR)) {
            /* overallocate to limit the number of realloc() */
            newlen += newlen / OVERALLOCATE_FACTOR;
        }
        if (newlen < writer->min_length)
            newlen = writer->min_length;

        if (maxchar > writer->maxchar || writer->readonly) {
            /* resize + widen */
            maxchar = Py_MAX(maxchar, writer->maxchar);
            newbuffer = PyUnicode_New(newlen, maxchar);
            if (newbuffer == NULL)
                return -1;
            _PyUnicode_FastCopyCharacters(newbuffer, 0,
                                          writer->buffer, 0, writer->pos);
            Py_DECREF(writer->buffer);
            writer->readonly = 0;
        }
        else {
            newbuffer = _PyUnicode_ResizeCompact(writer->buffer, newlen);
            if (newbuffer == NULL)
                return -1;
        }
        writer->buffer = newbuffer;
    }
    else if (maxchar > writer->maxchar) {
        assert(!writer->readonly);
        newbuffer = PyUnicode_New(writer->size, maxchar);
        if (newbuffer == NULL)
            return -1;
        _PyUnicode_FastCopyCharacters(newbuffer, 0,
                                      writer->buffer, 0, writer->pos);
        Py_SETREF(writer->buffer, newbuffer);
    }
    _PyUnicodeWriter_Update(writer);
    return 0;

#undef OVERALLOCATE_FACTOR
}

int
_PyUnicodeWriter_PrepareKindInternal(_PyUnicodeWriter *writer,
                                     int kind)
{
    Py_UCS4 maxchar;

    /* ensure that the _PyUnicodeWriter_PrepareKind macro was used */
    assert(writer->kind < kind);

    switch (kind)
    {
    case PyUnicode_1BYTE_KIND: maxchar = 0xff; break;
    case PyUnicode_2BYTE_KIND: maxchar = 0xffff; break;
    case PyUnicode_4BYTE_KIND: maxchar = _Py_MAX_UNICODE; break;
    default:
        Py_UNREACHABLE();
    }

    return _PyUnicodeWriter_PrepareInternal(writer, 0, maxchar);
}


int
_PyUnicodeWriter_WriteChar(_PyUnicodeWriter *writer, Py_UCS4 ch)
{
    if (writer->utf8_mode) {
        unsigned char bytes[4];
        Py_ssize_t size = _PyUnicode_WriteUTF8Char(bytes, ch) - bytes;
        return _PyUnicodeWriter_WriteUTF8(writer, (const char *)bytes, size, 1);
    }
    return _PyUnicodeWriter_WriteCharInline(writer, ch);
}


int
PyUnicodeWriter_WriteChar(PyUnicodeWriter *writer, Py_UCS4 ch)
{
    if (ch > _Py_MAX_UNICODE) {
        PyErr_SetString(PyExc_ValueError,
                        "character must be in range(0x110000)");
        return -1;
    }

    return _PyUnicodeWriter_WriteChar((_PyUnicodeWriter*)writer, ch);
}


int
_PyUnicodeWriter_WriteStr(_PyUnicodeWriter *writer, PyObject *str)
{
    assert(PyUnicode_Check(str));
    /* Preserve the existing identity optimization for a sole whole string. */
    if (writer->utf8_mode && writer->pos == 0 && !writer->overallocate &&
        PyUnicode_GET_LENGTH(str) != 0) {
        PyMem_Free(writer->utf8);
        writer->utf8 = NULL;
        writer->utf8_pos = writer->utf8_size = 0;
        writer->utf8_mode = 0;
    }
    if (writer->utf8_mode) {
        Py_ssize_t size;
        const char *data = _PyUnicode_GetPrimaryUTF8(str, &size);
        PyObject *owner = NULL;
        if (data == NULL) {
            owner = _PyUnicode_AsUTF8String(str, "surrogatepass");
            if (owner == NULL) {
                return -1;
            }
            data = PyBytes_AS_STRING(owner);
            size = PyBytes_GET_SIZE(owner);
        }
        int res = _PyUnicodeWriter_WriteUTF8(writer, data, size,
                                            PyUnicode_GET_LENGTH(str));
        Py_XDECREF(owner);
        return res;
    }

    Py_UCS4 maxchar;
    Py_ssize_t len;

    len = PyUnicode_GET_LENGTH(str);
    if (len == 0)
        return 0;
    maxchar = PyUnicode_MAX_CHAR_VALUE(str);
    if (maxchar > writer->maxchar || len > writer->size - writer->pos) {
        if (writer->buffer == NULL && !writer->overallocate) {
            assert(_PyUnicode_CheckConsistency(str, 1));
            writer->readonly = 1;
            writer->buffer = Py_NewRef(str);
            _PyUnicodeWriter_Update(writer);
            writer->pos += len;
            return 0;
        }
        if (_PyUnicodeWriter_PrepareInternal(writer, len, maxchar) == -1)
            return -1;
    }

    assert(_PyUnicodeWriter_CanWrite(writer));
    _PyUnicode_FastCopyCharacters(writer->buffer, writer->pos,
                                  str, 0, len);
    writer->pos += len;
    return 0;
}


int
PyUnicodeWriter_WriteStr(PyUnicodeWriter *writer, PyObject *obj)
{
    PyTypeObject *type = Py_TYPE(obj);
    if (type == &PyUnicode_Type) {
        return _PyUnicodeWriter_WriteStr((_PyUnicodeWriter*)writer, obj);
    }

    if (type == &PyLong_Type) {
        return _PyLong_FormatWriter((_PyUnicodeWriter *)writer, obj, 10, 0);
    }

    PyObject *str = PyObject_Str(obj);
    if (str == NULL) {
        return -1;
    }

    int res = _PyUnicodeWriter_WriteStr((_PyUnicodeWriter*)writer, str);
    Py_DECREF(str);
    return res;
}


int
PyUnicodeWriter_WriteRepr(PyUnicodeWriter *writer, PyObject *obj)
{
    if (obj == NULL) {
        return _PyUnicodeWriter_WriteASCIIString((_PyUnicodeWriter*)writer, "<NULL>", 6);
    }

    if (Py_TYPE(obj) == &PyLong_Type) {
        return _PyLong_FormatWriter((_PyUnicodeWriter *)writer, obj, 10, 0);
    }

    PyObject *repr = PyObject_Repr(obj);
    if (repr == NULL) {
        return -1;
    }

    int res = _PyUnicodeWriter_WriteStr((_PyUnicodeWriter*)writer, repr);
    Py_DECREF(repr);
    return res;
}


int
_PyUnicodeWriter_WriteSubstring(_PyUnicodeWriter *writer, PyObject *str,
                                Py_ssize_t start, Py_ssize_t end)
{
    assert(0 <= start);
    assert(end <= PyUnicode_GET_LENGTH(str));
    assert(start <= end);

    if (start == 0 && end == PyUnicode_GET_LENGTH(str))
        return _PyUnicodeWriter_WriteStr(writer, str);

    Py_ssize_t len = end - start;
    if (len == 0) {
        return 0;
    }

    if (writer->utf8_mode) {
        PyObject *part = PyUnicode_Substring(str, start, end);
        if (part == NULL) {
            return -1;
        }
        int res = _PyUnicodeWriter_WriteStr(writer, part);
        Py_DECREF(part);
        return res;
    }

    Py_UCS4 maxchar;
    if (PyUnicode_MAX_CHAR_VALUE(str) > writer->maxchar) {
        maxchar = _PyUnicode_FindMaxChar(str, start, end);
    }
    else {
        maxchar = writer->maxchar;
    }
    if (_PyUnicodeWriter_Prepare(writer, len, maxchar) < 0) {
        return -1;
    }
    assert(_PyUnicodeWriter_CanWrite(writer));

    _PyUnicode_FastCopyCharacters(writer->buffer, writer->pos,
                                  str, start, len);
    writer->pos += len;
    return 0;
}


int
PyUnicodeWriter_WriteSubstring(PyUnicodeWriter *writer, PyObject *str,
                               Py_ssize_t start, Py_ssize_t end)
{
    if (!PyUnicode_Check(str)) {
        PyErr_Format(PyExc_TypeError, "expect str, not %T", str);
        return -1;
    }
    if (start < 0 || start > end) {
        PyErr_Format(PyExc_ValueError, "invalid start argument");
        return -1;
    }
    if (end > PyUnicode_GET_LENGTH(str)) {
        PyErr_Format(PyExc_ValueError, "invalid end argument");
        return -1;
    }

    return _PyUnicodeWriter_WriteSubstring((_PyUnicodeWriter*)writer, str,
                                           start, end);
}


int
_PyUnicodeWriter_WriteASCIIString(_PyUnicodeWriter *writer,
                                  const char *ascii, Py_ssize_t len)
{
    if (len == -1)
        len = strlen(ascii);

    if (len == 0) {
        return 0;
    }

    assert(ucs1lib_find_max_char((const Py_UCS1*)ascii, (const Py_UCS1*)ascii + len) < 128);

    if (writer->utf8_mode) {
        return _PyUnicodeWriter_WriteUTF8(writer, ascii, len, len);
    }

    if (writer->buffer == NULL && !writer->overallocate) {
        PyObject *str;

        str = _PyUnicode_FromASCII(ascii, len);
        if (str == NULL)
            return -1;

        writer->readonly = 1;
        writer->buffer = str;
        _PyUnicodeWriter_Update(writer);
        writer->pos += len;
        return 0;
    }

    if (_PyUnicodeWriter_Prepare(writer, len, 127) == -1) {
        return -1;
    }
    assert(_PyUnicodeWriter_CanWrite(writer));

    switch (writer->kind)
    {
    case PyUnicode_1BYTE_KIND:
    {
        const Py_UCS1 *str = (const Py_UCS1 *)ascii;
        Py_UCS1 *data = writer->data;

        memcpy(data + writer->pos, str, len);
        break;
    }
    case PyUnicode_2BYTE_KIND:
    {
        _PyUnicode_CONVERT_BYTES(
            Py_UCS1, Py_UCS2,
            ascii, ascii + len,
            (Py_UCS2 *)writer->data + writer->pos);
        break;
    }
    case PyUnicode_4BYTE_KIND:
    {
        _PyUnicode_CONVERT_BYTES(
            Py_UCS1, Py_UCS4,
            ascii, ascii + len,
            (Py_UCS4 *)writer->data + writer->pos);
        break;
    }
    default:
        Py_UNREACHABLE();
    }

    writer->pos += len;
    return 0;
}


int
PyUnicodeWriter_WriteASCII(PyUnicodeWriter *writer,
                           const char *str,
                           Py_ssize_t size)
{
    assert(writer != NULL);
    _Py_AssertHoldsTstate();

    _PyUnicodeWriter *priv_writer = (_PyUnicodeWriter*)writer;
    return _PyUnicodeWriter_WriteASCIIString(priv_writer, str, size);
}


int
PyUnicodeWriter_WriteUTF8(PyUnicodeWriter *writer,
                          const char *str,
                          Py_ssize_t size)
{
    if (size < 0) {
        size = strlen(str);
    }

    PyObject *decoded = PyUnicode_DecodeUTF8(str, size, "strict");
    if (decoded == NULL) {
        return -1;
    }
    int res = _PyUnicodeWriter_WriteStr((_PyUnicodeWriter *)writer, decoded);
    Py_DECREF(decoded);
    return res;
}


int
PyUnicodeWriter_DecodeUTF8Stateful(PyUnicodeWriter *writer,
                                   const char *string,
                                   Py_ssize_t length,
                                   const char *errors,
                                   Py_ssize_t *consumed)
{
    if (length < 0) {
        length = strlen(string);
    }

    PyObject *decoded = PyUnicode_DecodeUTF8Stateful(string, length, errors, consumed);
    int res = -1;
    if (decoded != NULL) {
        res = _PyUnicodeWriter_WriteStr((_PyUnicodeWriter *)writer, decoded);
        Py_DECREF(decoded);
    }
    if (res < 0 && consumed != NULL) {
        *consumed = 0;
    }
    return res;
}


int
_PyUnicodeWriter_WriteLatin1String(_PyUnicodeWriter *writer,
                                   const char *str, Py_ssize_t len)
{
    if (len == 0) {
        return 0;
    }
    if (writer->utf8_mode) {
        /* Reserve the worst-case size before changing the logical position. */
        if (len > PY_SSIZE_T_MAX / 2 ||
            unicode_writer_reserve(writer, len * 2) < 0) {
            if (!PyErr_Occurred()) {
                PyErr_NoMemory();
            }
            return -1;
        }
        unsigned char *out = (unsigned char *)writer->utf8 + writer->utf8_pos;
        for (Py_ssize_t i = 0; i < len; i++) {
            out = _PyUnicode_WriteUTF8Char(out, (unsigned char)str[i]);
        }
        writer->utf8_pos = out - (unsigned char *)writer->utf8;
        writer->pos += len;
        return 0;
    }
    Py_UCS4 maxchar;

    maxchar = ucs1lib_find_max_char((const Py_UCS1*)str, (const Py_UCS1*)str + len);
    if (_PyUnicodeWriter_Prepare(writer, len, maxchar) == -1)
        return -1;
    assert(_PyUnicodeWriter_CanWrite(writer));
    unicode_write_cstr(writer->buffer, writer->pos, str, len);
    writer->pos += len;
    return 0;
}


PyObject *
_PyUnicodeWriter_Finish(_PyUnicodeWriter *writer)
{
    PyObject *str;
    if (writer->utf8_mode) {
#ifdef Py_DEBUG
        if (writer->utf8 != NULL && writer->utf8[writer->utf8_size] != 0) {
            _Py_FatalErrorFormat(__func__,
                "Buffer overflow detected in PyUnicodeWriter %p at position %zd",
                writer, writer->utf8_size);
        }
#endif
        str = PyUnicode_DecodeUTF8(writer->utf8 ? writer->utf8 : "",
                                   writer->utf8_pos, "surrogatepass");
        PyMem_Free(writer->utf8);
        writer->utf8 = NULL;
        writer->utf8_pos = writer->utf8_size = writer->pos = 0;
        return str;
    }

#ifdef Py_DEBUG
    // Check for buffer overflow
    if (writer->buffer != NULL) {
        Py_ssize_t pos = PyUnicode_GET_LENGTH(writer->buffer);
        Py_UCS4 ch = _PyUnicode_ReadCharNoAlloc(writer->buffer, pos);
        if (ch != 0) {
            _Py_FatalErrorFormat(__func__,
                                 "Buffer overflow detected in "
                                 "PyUnicodeWriter %p at position %zd",
                                 writer, pos);
        }
    }
#endif

    if (writer->pos == 0) {
        Py_CLEAR(writer->buffer);
        return _PyUnicode_GetEmpty();
    }

    str = writer->buffer;
    writer->buffer = NULL;

    if (writer->readonly) {
        assert(PyUnicode_GET_LENGTH(str) == writer->pos);
        assert(_PyUnicode_CheckConsistency(str, 1));
        return _PyUnicode_Result(str);
    }

    if (PyUnicode_GET_LENGTH(str) != writer->pos) {
        PyObject *str2;
        str2 = _PyUnicode_ResizeCompact(str, writer->pos);
        if (str2 == NULL) {
            Py_DECREF(str);
            return NULL;
        }
        str = str2;
    }

    assert(_PyUnicode_CheckConsistency(str, 1));
    return _PyUnicode_Result(str);
}


PyObject*
PyUnicodeWriter_Finish(PyUnicodeWriter *writer)
{
    PyObject *str = _PyUnicodeWriter_Finish((_PyUnicodeWriter*)writer);
    assert(((_PyUnicodeWriter*)writer)->buffer == NULL);
    _Py_FREELIST_FREE(unicode_writers, writer, PyMem_Free);
    return str;
}


void
_PyUnicodeWriter_Dealloc(_PyUnicodeWriter *writer)
{
    Py_CLEAR(writer->buffer);
    PyMem_Free(writer->utf8);
    writer->utf8 = NULL;
}
