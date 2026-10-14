"""Turning a chapter's HTML into clean reading text.

Novel sites bury the prose in ad slots, "read more at ..." footers and stray
``<br>`` soup. This module strips that away and emits plain paragraphs, which
is what both the reader and the EPUB exporter want.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

# Tags that never carry chapter prose.
_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "ins",
    "button",
    "form",
    "svg",
    "video",
    "audio",
)

# Substrings in class/id that mark an injected block rather than content.
_DROP_HINTS = (
    "ads",
    "advert",
    "quangcao",
    "banner",
    "sponsor",
    "google",
    "adsbygoogle",
    "share",
    "social",
    "comment",
    "related",
    "nav",
    "breadcrumb",
    "toolbar",
    "report",
)

# Whole lines that are site furniture, not story. Matched case-insensitively
# against the stripped line.
_JUNK_LINE_PATTERNS = (
    r"^nguồn\s*[:：]",
    r"^converter\s*[:：]",
    r"^dịch\s*[:：]",
    r"^biên tập\s*[:：]",
    r"^truyện\s+được\s+đăng",
    r"^đọc\s+truyện\s+(?:tại|ở|online)",
    r"^vui lòng\s+(?:đọc|truy cập)",
    r"^bạn\s+đang\s+đọc\s+truyện",
    r"^(?:nhấn|bấm|click)\s+(?:vào|để)",
    r"^quảng cáo$",
    r"^bình luận",
    r"^chương\s+trước\s*[|·-]?\s*chương\s+(?:tiếp|sau)",
    r"^\s*[-=*_~]{3,}\s*$",
    # Bare domain or "site.com" credit lines.
    r"^[\w.-]+\.(?:com|net|vn|org|info|tv|top|cc|me)\b[^\s]{0,30}$",
)

_JUNK_LINE_RE = re.compile("|".join(_JUNK_LINE_PATTERNS), re.IGNORECASE)

# Zero-width and other invisible characters some sites inject to break scrapers.
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]")

_WS_RE = re.compile(r"[ \t\u00a0\u3000]+")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _should_drop(tag: Tag) -> bool:
    if tag.name in _DROP_TAGS:
        return True
    tokens = " ".join(tag.get("class") or []).lower() + " " + (tag.get("id") or "").lower()
    return any(hint in tokens for hint in _DROP_HINTS)


def clean_container(container: Tag) -> str:
    """Extract reading text from a chapter container element."""
    # Work on a copy: callers may still want the original tree.
    node = BeautifulSoup(str(container), "lxml")

    for tag in list(node.find_all(True)):
        # Dropping a container takes its children with it, and a decomposed
        # tag has no attrs left to inspect, so skip anything already gone.
        if tag.decomposed:
            continue
        if _should_drop(tag):
            tag.decompose()

    # <br> is the usual paragraph separator on these sites.
    for br in node.find_all("br"):
        br.replace_with(NavigableString("\n"))

    # Block elements should not run together once tags are gone.
    for tag in node.find_all(["p", "div", "h1", "h2", "h3", "h4", "li", "blockquote"]):
        tag.insert_before(NavigableString("\n"))
        tag.insert_after(NavigableString("\n"))

    return normalise(node.get_text())


def normalise(text: str) -> str:
    """Collapse whitespace, drop junk lines, and leave blank-line paragraphs."""
    text = _INVISIBLE_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    for raw in text.split("\n"):
        line = _WS_RE.sub(" ", raw).strip()
        if not line:
            lines.append("")
            continue
        if _JUNK_LINE_RE.search(line):
            continue
        lines.append(line)

    # Paragraphs separated by exactly one blank line.
    joined = "\n".join(lines)
    joined = _BLANK_RUN_RE.sub("\n\n", joined)
    return joined.strip()


def looks_like_content(text: str, *, minimum: int = 200) -> bool:
    """Cheap sanity check before a chapter is stored.

    Guards against saving an error page or an empty container as a chapter.
    """
    return len(text.strip()) >= minimum


def clean_title(raw: str) -> str:
    """Tidy a chapter heading.

    Site markup often splits the label, giving things like "Chương  12" or a
    title repeated with the novel name.
    """
    title = _INVISIBLE_RE.sub("", raw)
    title = _WS_RE.sub(" ", title.replace("\n", " ")).strip(" -–—:|")
    # "Chương12" happens when a <span> boundary swallowed the space.
    title = re.sub(r"(?i)\bch(?:ương|uong)\s*(\d+)", r"Chương \1", title)
    return title.strip()
