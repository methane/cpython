#include <Python.h>
#include "pycore_bytesobject.h"   // _PyBytes_DecodeEscape()
#include "pycore_unicodeobject.h" // _PyUnicode_DecodeUnicodeEscapeInternal()

#include "lexer/state.h"
#include "pegen.h"
#include "string_parser.h"

#include <stdbool.h>

//// STRING HANDLING FUNCTIONS ////

static int
warn_invalid_escape_sequence(Parser *p, const char* buffer, const char *first_invalid_escape, Token *t)
{
    if (p->call_invalid_rules) {
        // Do not report warnings if we are in the second pass of the parser
        // to avoid showing the warning twice.
        return 0;
    }
    unsigned char c = (unsigned char)*first_invalid_escape;
    if ((t->type == FSTRING_MIDDLE || t->type == FSTRING_END || t->type == TSTRING_MIDDLE || t->type == TSTRING_END)
            && (c == '{' || c == '}')) {
        // in this case the tokenizer has already emitted a warning,
        // see Parser/tokenizer/helpers.c:warn_invalid_escape_sequence
        return 0;
    }

    int octal = ('4' <= c && c <= '7');
    PyObject *msg =
        octal
        ? PyUnicode_FromFormat(
              "\"\\%.3s\" is an invalid octal escape sequence. "
              "Such sequences will not work in the future. "
              "Did you mean \"\\\\%.3s\"? A raw string is also an option.",
              first_invalid_escape, first_invalid_escape)
        : PyUnicode_FromFormat(
              "\"\\%c\" is an invalid escape sequence. "
              "Such sequences will not work in the future. "
              "Did you mean \"\\\\%c\"? A raw string is also an option.",
              c, c);
    if (msg == NULL) {
        return -1;
    }
    PyObject *category;
    if (p->feature_version >= 12) {
        category = PyExc_SyntaxWarning;
    }
    else {
        category = PyExc_DeprecationWarning;
    }

    // Calculate the lineno and the col_offset of the invalid escape sequence
    const char *start = buffer;
    const char *end = first_invalid_escape;
    int lineno = t->lineno;
    int col_offset = t->col_offset;
    while (start < end) {
        if (*start == '\n') {
            lineno++;
            col_offset = 0;
        }
        else {
            col_offset++;
        }
        start++;
    }

    // Count the number of quotes in the token
    char first_quote = 0;
    if (lineno == t->lineno) {
        int quote_count = 0;
        char* tok = PyBytes_AsString(t->bytes);
        for (int i = 0; i < PyBytes_Size(t->bytes); i++) {
            if (tok[i] == '\'' || tok[i] == '\"') {
                if (quote_count == 0) {
                    first_quote = tok[i];
                }
                if (tok[i] == first_quote) {
                    quote_count++;
                }
            } else {
                break;
            }
        }

        col_offset += quote_count;
    }

    if (PyErr_WarnExplicitObject(category, msg, p->tok->filename,
                                 lineno, p->tok->module, NULL) < 0) {
        if (PyErr_ExceptionMatches(category)) {
            /* Replace the Syntax/DeprecationWarning exception with a SyntaxError
               to get a more accurate error report */
            PyErr_Clear();

            /* This is needed, in order for the SyntaxError to point to the token t,
               since _PyPegen_raise_error uses p->tokens[p->fill - 1] for the
               error location, if p->known_err_token is not set. */
            p->known_err_token = t;
            if (octal) {
                RAISE_ERROR_KNOWN_LOCATION(p, PyExc_SyntaxError, lineno, col_offset-1, lineno, col_offset+1,
                    "\"\\%.3s\" is an invalid octal escape sequence. "
                    "Did you mean \"\\\\%.3s\"? A raw string is also an option.",
                    first_invalid_escape, first_invalid_escape);
            }
            else {
                RAISE_ERROR_KNOWN_LOCATION(p, PyExc_SyntaxError, lineno, col_offset-1, lineno, col_offset+1,
                    "\"\\%c\" is an invalid escape sequence. "
                    "Did you mean \"\\\\%c\"? A raw string is also an option.",
                    c, c);
            }
        }
        Py_DECREF(msg);
        return -1;
    }
    Py_DECREF(msg);
    return 0;
}

static PyObject *
decode_utf8(const char **sPtr, const char *end)
{
    const char *s;
    const char *t;
    t = s = *sPtr;
    while (s < end && (*s & 0x80)) {
        s++;
    }
    *sPtr = s;
    return PyUnicode_DecodeUTF8(t, s - t, NULL);
}

static PyObject *
decode_unicode_with_escapes(Parser *parser, const char *s, size_t len, Token *t)
{
    PyObject *v;
    PyObject *u;
    char *buf;
    char *p;
    const char *end;

    /* check for integer overflow */
    if (len > (size_t)PY_SSIZE_T_MAX / 6) {
        return NULL;
    }
    /* "ä" (2 bytes) may become "\U000000E4" (10 bytes), or 1:5
       "\ä" (3 bytes) may become "\u005c\U000000E4" (16 bytes), or ~1:6 */
    u = PyBytes_FromStringAndSize((char *)NULL, (Py_ssize_t)len * 6);
    if (u == NULL) {
        return NULL;
    }
    p = buf = PyBytes_AsString(u);
    if (p == NULL) {
        return NULL;
    }
    end = s + len;
    while (s < end) {
        if (*s == '\\') {
            *p++ = *s++;
            if (s >= end || *s & 0x80) {
                strcpy(p, "u005c");
                p += 5;
                if (s >= end) {
                    break;
                }
            }
        }
        if (*s & 0x80) {
            PyObject *w;
            int kind;
            const void *data;
            Py_ssize_t w_len;
            Py_ssize_t i;
            w = decode_utf8(&s, end);
            if (w == NULL) {
                Py_DECREF(u);
                return NULL;
            }
            kind = PyUnicode_KIND(w);
            data = PyUnicode_DATA(w);
            w_len = PyUnicode_GET_LENGTH(w);
            for (i = 0; i < w_len; i++) {
                Py_UCS4 chr = PyUnicode_READ(kind, data, i);
                sprintf(p, "\\U%08x", chr);
                p += 10;
            }
            /* Should be impossible to overflow */
            assert(p - buf <= PyBytes_GET_SIZE(u));
            Py_DECREF(w);
        }
        else {
            *p++ = *s++;
        }
    }
    len = (size_t)(p - buf);
    s = buf;

    int first_invalid_escape_char;
    const char *first_invalid_escape_ptr;
    v = _PyUnicode_DecodeUnicodeEscapeInternal2(s, (Py_ssize_t)len, NULL, NULL,
                                                &first_invalid_escape_char,
                                                &first_invalid_escape_ptr);

    // HACK: later we can simply pass the line no, since we don't preserve the tokens
    // when we are decoding the string but we preserve the line numbers.
    if (v != NULL && first_invalid_escape_ptr != NULL && t != NULL) {
        if (warn_invalid_escape_sequence(parser, s, first_invalid_escape_ptr, t) < 0) {
            /* We have not decref u before because first_invalid_escape_ptr
               points inside u. */
            Py_XDECREF(u);
            Py_DECREF(v);
            return NULL;
        }
    }
    Py_XDECREF(u);
    return v;
}

static PyObject *
decode_bytes_with_escapes(Parser *p, const char *s, Py_ssize_t len, Token *t)
{
    int first_invalid_escape_char;
    const char *first_invalid_escape_ptr;
    PyObject *result = _PyBytes_DecodeEscape2(s, len, NULL,
                                              &first_invalid_escape_char,
                                              &first_invalid_escape_ptr);
    if (result == NULL) {
        return NULL;
    }

    if (first_invalid_escape_ptr != NULL) {
        if (warn_invalid_escape_sequence(p, s, first_invalid_escape_ptr, t) < 0) {
            Py_DECREF(result);
            return NULL;
        }
    }
    return result;
}

PyObject *
_PyPegen_decode_string(Parser *p, int raw, const char *s, size_t len, Token *t)
{
    if (raw) {
        return PyUnicode_DecodeUTF8Stateful(s, (Py_ssize_t)len, NULL, NULL);
    }
    return decode_unicode_with_escapes(p, s, len, t);
}

// Dedent d-string and return result as a bytes.
static PyObject*
_PyPegen_dedent_string(Parser *p, const char *s, Py_ssize_t len,
                       const char *indent, Py_ssize_t indent_len)
{
    PyBytesWriter *w = PyBytesWriter_Create(0);
    if (w == NULL) {
        return NULL;
    }

    const char *end = s + len;
    while (s < end) {
        // A blank line (whitespace-only line with a newline) is normalized
        // to a single newline. Whitespace before the closing quotes is also
        // blank, but its preceding newline has already been written.
        const char *q = s;
        while (q < end && (*q == ' ' || *q == '\t')) {
            q++;
        }
        if (q == end) {
            break;
        }
        if (q < end && *q == '\n') {
            if (PyBytesWriter_WriteBytes(w, "\n", 1) < 0) {
                PyBytesWriter_Discard(w);
                return NULL;
            }
            s = q + 1;
            continue;
        }

        // A non-blank line. The common indent was computed from all lines
        // including the closing quotes line, so it is always a prefix of
        // the leading whitespace of this line.
        assert(q - s >= indent_len);
        assert(memcmp(s, indent, (size_t)indent_len) == 0);
        s += indent_len;
        const char *line_end = memchr(s, '\n', end - s);
        if (line_end == NULL) {
            line_end = end; // last line without newline
        }
        else {
            line_end++; // include the newline in the line
        }

        if (PyBytesWriter_WriteBytes(w, s, line_end - s) < 0) {
            PyBytesWriter_Discard(w);
            return NULL;
        }
        s = line_end;
    }
    return PyBytesWriter_Finish(w);
}

/* s must include the bracketing quote characters, and r, b &/or f prefixes
    (if any), and embedded escape sequences (if any). (f-strings are handled by the parser)
   _PyPegen_parse_string parses it, and returns the decoded Python string object. */
PyObject *
_PyPegen_parse_string(Parser *p, Token *t)
{
    const char *s = PyBytes_AsString(t->bytes);
    if (s == NULL) {
        return NULL;
    }

    size_t len;
    int quote = Py_CHARMASK(*s);
    int bytesmode = 0;
    int rawmode = 0;
    int dedentmode = 0;

    if (Py_ISALPHA(quote)) {
        while (!bytesmode || !rawmode || !dedentmode) {
            if (quote == 'b' || quote == 'B') {
                quote =(unsigned char)*++s;
                bytesmode = 1;
            }
            else if (quote == 'u' || quote == 'U') {
                quote = (unsigned char)*++s;
            }
            else if (quote == 'r' || quote == 'R') {
                quote = (unsigned char)*++s;
                rawmode = 1;
            }
            else if (quote == 'd' || quote == 'D') {
                quote =(unsigned char)*++s;
                dedentmode = 1;
            }
            else {
                break;
            }
        }
    }

    if (quote != '\'' && quote != '\"') {
        PyErr_BadInternalCall();
        return NULL;
    }

    /* Skip the leading quote char. */
    s++;
    len = strlen(s);
    // gh-120155: 's' contains at least the trailing quote,
    // so the code '--len' below is safe.
    assert(len >= 1);

    if (len > INT_MAX) {
        PyErr_SetString(PyExc_OverflowError, "string to parse is too long");
        return NULL;
    }
    if (s[--len] != quote) {
        /* Last quote char must match the first. */
        PyErr_BadInternalCall();
        return NULL;
    }
    if (len >= 4 && s[0] == quote && s[1] == quote) {
        /* A triple quoted string. We've already skipped one quote at
           the start and one at the end of the string. Now skip the
           two at the start. */
        s += 2;
        len -= 2;
        /* And check that the last two match. */
        if (s[--len] != quote || s[--len] != quote) {
            PyErr_BadInternalCall();
            return NULL;
        }
    }
    else if (dedentmode) {
        RAISE_SYNTAX_ERROR_KNOWN_LOCATION(t, "d-string must be triple-quoted");
        return NULL;
    }

    /* Avoid invoking escape decoding routines if possible. */
    rawmode = rawmode || strchr(s, '\\') == NULL;

    int _prev_call_invald = p->call_invalid_rules;

    PyObject *dedent_bytes = NULL;
    if (dedentmode) {
        if (len == 0 || s[0] != '\n') {
            RAISE_SYNTAX_ERROR_KNOWN_LOCATION(t, "d-string must start with a newline");
            return NULL;
        }

        if (bytesmode) {
            for (const char *ch = s; ch < s + len; ch++) {
                if (Py_CHARMASK(*ch) >= 0x80) {
                    RAISE_SYNTAX_ERROR_KNOWN_LOCATION(
                        t, "bytes can only contain ASCII literal characters");
                    return NULL;
                }
            }
        }

        // _PyPegen_decode_string() and decode_bytes_with_escapes() emit
        // a warning for invalid escape sequences.
        // We need to call it before dedenting since it shifts the positions.
        if (!_prev_call_invald && !rawmode) {
            PyObject *temp;
            if (bytesmode) {
                temp = decode_bytes_with_escapes(p, s, len, t);
            }
            else {
                temp = _PyPegen_decode_string(p, 0, s, len, t);
            }
            if (temp == NULL) {
                return NULL;
            }
            Py_DECREF(temp);
        }

        // We find common indent from [s, end+1) because we want to include the last line
        // for indent calculation.
        const char *end = s + len;
        assert(*end == '"' || *end == '\''); // end[0:3] is the trailing quotes
        const char *indent = "";
        Py_ssize_t indent_len = _Py_search_longest_common_leading_whitespace(s+1, end+1, &indent);

        s++; len--; // skip the first newline
        // Dedent even when indent_len == 0: blank lines must still be
        // normalized to single newlines.
        dedent_bytes = _PyPegen_dedent_string(p, s, len, indent, indent_len);
        if (dedent_bytes == NULL) {
            return NULL;
        }
        char *dedent_str;
        Py_ssize_t dedent_len;
        if (PyBytes_AsStringAndSize(dedent_bytes, &dedent_str, &dedent_len) < 0) {
            Py_DECREF(dedent_bytes);
            return NULL;
        }
        s = dedent_str;
        len = dedent_len;

        p->call_invalid_rules = 1;
    }

    PyObject *result;
    if (bytesmode) {
        /* Disallow non-ASCII characters. */
        const char *ch;
        for (ch = s; *ch; ch++) {
            if (Py_CHARMASK(*ch) >= 0x80) {
                RAISE_SYNTAX_ERROR_KNOWN_LOCATION(
                                   t,
                                   "bytes can only contain ASCII "
                                   "literal characters");
                Py_XDECREF(dedent_bytes);
                p->call_invalid_rules = _prev_call_invald;
                return NULL;
            }
        }
        if (rawmode) {
            result = PyBytes_FromStringAndSize(s, (Py_ssize_t)len);
        }
        else {
            result = decode_bytes_with_escapes(p, s, (Py_ssize_t)len, t);
        }
    }
    else {
        result = _PyPegen_decode_string(p, rawmode, s, len, t);
    }
    Py_XDECREF(dedent_bytes);
    p->call_invalid_rules = _prev_call_invald;
    return result;
}

