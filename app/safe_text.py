"""ReportLab-safe text helper.

ReportLab Paragraph interprets a subset of XML-like markup (<b>, <i>, <font>,
<a href>, <img>, entities, etc). Any user-controlled value rendered into a
Paragraph or PDF metadata field MUST pass through safe_text() first so hostile
input can never inject active markup, control characters, or unbounded strings.

Guarantees:
  * Converts any input to str safely (no TypeError on None/int/bytes).
  * Strips C0/C1 control characters except \\n and \\t.
  * Escapes &, <, > via xml.sax.saxutils.escape.
  * Escapes single and double quotes.
  * Preserves ordinary Unicode (emoji, CJK, RTL, accented letters).
  * Imposes a max_len display limit (default 10 000 chars).
  * Never returns active ReportLab markup from hostile input.
"""
from xml.sax.saxutils import escape as _xml_escape

# Control characters to remove (everything in C0 + C1 except \t=0x09, \n=0x0A).
# \r is also removed; ReportLab does not need it and it can be used for header
# smuggling in some contexts.
# Bidi formatting controls (U+202A-U+202E, U+2066-U+2069) are also stripped
# because they can reorder text in misleading ways and serve no purpose in
# an evidence report.
import re

_UNSAFE_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0B\x0C\x0D\x0E-\x1F\x7F\x80-\x9F\u202A-\u202E\u2066-\u2069]"
)


def safe_text(value, max_len=10000):
    """Return a ReportLab-safe string representation of value.

    - value: any input (str, int, float, None, bytes, list, dict, ...).
    - max_len: hard ceiling on returned length (default 10 000).
    """
    # 1. Convert to string safely.
    if value is None:
        text = ""
    elif isinstance(value, bytes):
        try:
            text = value.decode("utf-8", errors="replace")
        except Exception:
            text = value.decode("latin-1", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = str(value)
        except Exception:
            text = ""

    # 2. Remove unsafe control characters (keep \n and \t).
    text = _UNSAFE_CONTROL_RE.sub("", text)

    # 3. Escape XML/ReportLab-significant characters.
    #    xml.sax.saxutils.escape handles &, <, >. We also escape quotes so
    #    the result is safe inside attribute-like contexts.
    text = _xml_escape(text)
    text = text.replace('"', "&quot;").replace("'", "&#39;")

    # 4. Impose max_len display limit.
    if max_len is not None and max_len > 0 and len(text) > max_len:
        text = text[:max_len]

    return text
