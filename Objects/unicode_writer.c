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
#include "pycore_unicodeobject.h" // _PyUnicode_GetPrimaryUTF8()


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
    if (size > PY_SSIZE_T_MAX - writer->utf8_pos - 1) {
        PyErr_NoMemory();
        return -1;
    }
    Py_ssize_t needed = writer->utf8_pos + size;
    if (needed <= writer->utf8_size && writer->readonly == NULL) {
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
    if (writer->readonly != NULL) {
        Py_ssize_t size;
        const char *source = _PyUnicode_GetPrimaryUTF8(writer->readonly, &size);
        assert(source != NULL && writer->utf8_pos <= size);
        memcpy(data, source, writer->utf8_pos);
        Py_CLEAR(writer->readonly);
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
    return unicode_writer_reserve(writer, size);
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
    const char *data = writer->utf8;
    if (writer->readonly != NULL) {
        Py_ssize_t size;
        data = _PyUnicode_GetPrimaryUTF8(writer->readonly, &size);
    }
    while (writer->pos > pos) {
        do {
            writer->utf8_pos--;
        } while ((data[writer->utf8_pos] & 0xc0) == 0x80);
        writer->pos--;
    }
}

void
_PyUnicodeWriter_Init(_PyUnicodeWriter *writer)
{
    memset(writer, 0, sizeof(*writer));
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


int
_PyUnicodeWriter_WriteChar(_PyUnicodeWriter *writer, Py_UCS4 ch)
{
    unsigned char bytes[4];
    Py_ssize_t size = _PyUnicode_WriteUTF8Char(bytes, ch) - bytes;
    return _PyUnicodeWriter_WriteUTF8(writer, (const char *)bytes, size, 1);
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
    Py_ssize_t length = PyUnicode_GET_LENGTH(str);
    if (length == 0)
        return 0;
    Py_ssize_t size;
    const char *data = _PyUnicode_GetPrimaryUTF8(str, &size);
    if (data != NULL && writer->pos == 0 && !writer->overallocate &&
        PyUnicode_CheckExact(str)) {
        /* Preserve identity when the entire result is one existing string. */
        PyMem_Free(writer->utf8);
        writer->utf8 = NULL;
        writer->utf8_size = 0;
        Py_XSETREF(writer->readonly, Py_NewRef(str));
        writer->pos = length;
        writer->utf8_pos = size;
        return 0;
    }
    PyObject *owner = NULL;
    if (data == NULL) {
        owner = _PyUnicode_AsUTF8String(str, "surrogatepass");
        if (owner == NULL)
            return -1;
        data = PyBytes_AS_STRING(owner);
        size = PyBytes_GET_SIZE(owner);
    }
    int res = _PyUnicodeWriter_WriteUTF8(writer, data, size, length);
    Py_XDECREF(owner);
    return res;
}


/* UCS-4 preserves individual surrogates; a 16-bit wchar_t input combines
   valid pairs, as required by PyUnicode_FromWideChar(). */
static Py_UCS4
unicode_writer_read_wide(const void *data, int kind, Py_ssize_t size,
                         Py_ssize_t *index, int join_surrogates)
{
    Py_UCS4 ch = PyUnicode_READ(kind, data, (*index)++);
    if (join_surrogates && Py_UNICODE_IS_HIGH_SURROGATE(ch) && *index < size) {
        Py_UCS4 low = PyUnicode_READ(kind, data, *index);
        if (Py_UNICODE_IS_LOW_SURROGATE(low)) {
            (*index)++;
            ch = Py_UNICODE_JOIN_SURROGATES(ch, low);
        }
    }
    return ch;
}

static int
unicode_writer_write_wide(_PyUnicodeWriter *writer, const void *data,
                          int kind, Py_ssize_t size, int join_surrogates)
{
    Py_ssize_t bytes = 0, length = 0;
    for (Py_ssize_t i = 0; i < size; length++) {
        Py_UCS4 ch = unicode_writer_read_wide(data, kind, size, &i, join_surrogates);
        if (ch > _Py_MAX_UNICODE) {
            PyErr_Format(PyExc_ValueError,
                         "character U+%x is not in range [U+0000; U+%x]",
                         ch, _Py_MAX_UNICODE);
            return -1;
        }
        int width = ch < 0x80 ? 1 : ch < 0x800 ? 2 : ch < 0x10000 ? 3 : 4;
        if (bytes > PY_SSIZE_T_MAX - width) {
            PyErr_NoMemory();
            return -1;
        }
        bytes += width;
    }
    if (bytes == 0)
        return 0;
    if (_PyUnicodeWriter_PrepareUTF8(writer, bytes) < 0)
        return -1;
    unsigned char *out = (unsigned char *)_PyUnicodeWriter_UTF8Data(writer);
    for (Py_ssize_t i = 0; i < size; ) {
        Py_UCS4 ch = unicode_writer_read_wide(data, kind, size, &i, join_surrogates);
        out = _PyUnicode_WriteUTF8Char(out, ch);
    }
    _PyUnicodeWriter_AdvanceUTF8(writer, bytes, length);
    return 0;
}

int
PyUnicodeWriter_WriteWideChar(PyUnicodeWriter *writer, const wchar_t *str,
                              Py_ssize_t size)
{
    if (size < 0)
        size = wcslen(str);
    return unicode_writer_write_wide((_PyUnicodeWriter *)writer, str,
                                     sizeof(wchar_t), size, sizeof(wchar_t) == 2);
}

int
PyUnicodeWriter_WriteUCS4(PyUnicodeWriter *writer, const Py_UCS4 *str,
                          Py_ssize_t size)
{
    if (size < 0) {
        PyErr_SetString(PyExc_ValueError, "size must be positive");
        return -1;
    }
    return unicode_writer_write_wide((_PyUnicodeWriter *)writer, str,
                                     PyUnicode_4BYTE_KIND, size, 0);
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

    Py_ssize_t size;
    const char *data = _PyUnicode_GetPrimaryUTF8(str, &size);
    PyObject *owner = NULL;
    if (data == NULL) {
        owner = _PyUnicode_AsUTF8String(str, "surrogatepass");
        if (owner == NULL)
            return -1;
        data = PyBytes_AS_STRING(owner);
        size = PyBytes_GET_SIZE(owner);
    }
    Py_ssize_t begin = start, stop = end;
    if (size != PyUnicode_GET_LENGTH(str)) {
        stop = 0;
        for (Py_ssize_t i = 0; i < end; i++) {
            if (i == start)
                begin = stop;
            unsigned char lead = (unsigned char)data[stop];
            stop += lead < 0x80 ? 1 : lead < 0xe0 ? 2 : lead < 0xf0 ? 3 : 4;
        }
    }
    int res = _PyUnicodeWriter_WriteUTF8(writer, data + begin, stop - begin, len);
    Py_XDECREF(owner);
    return res;
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
    return _PyUnicodeWriter_WriteUTF8(writer, ascii, len, len);
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
    if (len == 0)
        return 0;
    if (len > PY_SSIZE_T_MAX / 2) {
        PyErr_NoMemory();
        return -1;
    }
    if (_PyUnicodeWriter_PrepareUTF8(writer, len * 2) < 0)
        return -1;
    unsigned char *start = (unsigned char *)_PyUnicodeWriter_UTF8Data(writer);
    unsigned char *out = start;
    for (Py_ssize_t i = 0; i < len; i++)
        out = _PyUnicode_WriteUTF8Char(out, (unsigned char)str[i]);
    _PyUnicodeWriter_AdvanceUTF8(writer, out - start, len);
    return 0;
}


PyObject *
_PyUnicodeWriter_Finish(_PyUnicodeWriter *writer)
{
    PyObject *str;
    if (writer->readonly != NULL) {
        str = writer->readonly;
        writer->readonly = NULL;
        if (writer->pos != PyUnicode_GET_LENGTH(str)) {
            PyObject *part = PyUnicode_Substring(str, 0, writer->pos);
            Py_DECREF(str);
            str = part;
        }
    }
    else {
#ifdef Py_DEBUG
        if (writer->utf8 != NULL && writer->utf8[writer->utf8_size] != 0) {
            _Py_FatalErrorFormat(__func__,
                "Buffer overflow detected in PyUnicodeWriter %p at position %zd",
                writer, writer->utf8_size);
        }
#endif
        str = PyUnicode_DecodeUTF8(writer->utf8 ? writer->utf8 : "",
                                   writer->utf8_pos, "surrogatepass");
        assert(str == NULL || PyUnicode_GET_LENGTH(str) == writer->pos);
    }
    PyMem_Free(writer->utf8);
    writer->utf8 = NULL;
    writer->utf8_pos = writer->utf8_size = writer->pos = 0;
    return str;
}


PyObject*
PyUnicodeWriter_Finish(PyUnicodeWriter *writer)
{
    PyObject *str = _PyUnicodeWriter_Finish((_PyUnicodeWriter*)writer);
    assert(((_PyUnicodeWriter*)writer)->readonly == NULL);
    _Py_FREELIST_FREE(unicode_writers, writer, PyMem_Free);
    return str;
}


void
_PyUnicodeWriter_Dealloc(_PyUnicodeWriter *writer)
{
    Py_CLEAR(writer->readonly);
    PyMem_Free(writer->utf8);
    writer->utf8 = NULL;
}
