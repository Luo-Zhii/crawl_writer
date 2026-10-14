"""Source adapters, one per site.

Importing this package registers every adapter, so the registry is populated
by the time anything calls :func:`app.sources.registry.resolve`.
"""

# Adapters must be imported for their @register decorator to run; the imports
# are kept below the shared definitions they depend on.
from app.sources import (  # noqa: F401  (side effect: registration)
    czbooks,
    qidian,
    truyendich,
    truyenhoan,
    uukanshu,
)
from app.sources.base import (
    ChapterLocked,
    ChapterRef,
    NovelInfo,
    NovelRef,
    Source,
    SourceError,
)
from app.sources.registry import (
    UnsupportedSite,
    all_sources,
    find_for_url,
    get_by_key,
    register,
    resolve,
)

__all__ = [
    "ChapterLocked",
    "ChapterRef",
    "NovelInfo",
    "NovelRef",
    "Source",
    "SourceError",
    "UnsupportedSite",
    "all_sources",
    "find_for_url",
    "get_by_key",
    "register",
    "resolve",
]
