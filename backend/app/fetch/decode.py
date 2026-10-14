"""Turning bytes into text.

Chinese novel sites are the reason this module exists. Plenty of them serve
GBK or GB18030 and declare it only in a ``<meta>`` tag, so trusting the HTTP
header alone gives a page of mojibake.
"""

from __future__ import annotations

import re

from charset_normalizer import from_bytes

_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""",
    re.IGNORECASE,
)

# Sites declaring "gb2312" routinely include characters outside it. GB18030 is
# a superset, so decoding as the wider charset avoids needless failures.
_WIDEN = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "iso-8859-1": "utf-8",  # the default when a server sets no charset at all
}


def _normalise(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = name.strip().strip("\"'").lower()
    if not cleaned or cleaned == "none":
        return None
    return _WIDEN.get(cleaned, cleaned)


def charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type or "charset=" not in content_type.lower():
        return None
    return _normalise(content_type.lower().split("charset=", 1)[1].split(";")[0])


def charset_from_meta(content: bytes) -> str | None:
    # Only the head matters, and scanning the whole body of a long chapter is
    # wasted work.
    match = _META_CHARSET.search(content[:4096])
    if match is None:
        return None
    return _normalise(match.group(1).decode("ascii", errors="ignore"))


def decode(
    content: bytes,
    *,
    content_type: str | None = None,
    override: str | None = None,
) -> tuple[str, str]:
    """Decode ``content``, returning ``(text, encoding_used)``.

    Order of trust: explicit override, the ``<meta>`` tag, the HTTP header,
    then statistical detection. The meta tag outranks the header because
    misconfigured servers are more common than wrong markup on these sites.
    """
    if not content:
        return "", override or "utf-8"

    candidates = [
        _normalise(override),
        charset_from_meta(content),
        charset_from_content_type(content_type),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return content.decode(candidate), candidate
        except (UnicodeDecodeError, LookupError):
            continue

    best = from_bytes(content).best()
    if best is not None:
        return str(best), (best.encoding or "utf-8")

    # Give the caller something to work with rather than raising.
    return content.decode("utf-8", errors="replace"), "utf-8"
