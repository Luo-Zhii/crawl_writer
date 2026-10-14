"""Google Translate through its public web endpoint.

The default provider: no key, no cost, and good enough to follow a plot. Its
weaknesses are consistency with proper nouns (hence the glossary) and a fairly
small limit per request.
"""

from __future__ import annotations

import json

import httpx

from app.core.logging import get_logger
from app.translate.base import TranslateProvider, TranslationError

log = get_logger(__name__)

ENDPOINT = "https://translate.googleapis.com/translate_a/single"


class GoogleTranslateProvider(TranslateProvider):
    key = "google"
    name = "Google Translate"
    # The endpoint starts returning errors well before its hard limit.
    chunk_limit = 1800
    metered = False

    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 30.0) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={
                # Without a browser-ish UA the endpoint refuses outright.
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
            },
        )

    async def translate(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,  # noqa: ARG002 - applied by the caller
    ) -> str:
        if not text.strip():
            return text

        params = {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }

        try:
            response = await self._client.get(ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise TranslationError(
                f"request failed: {type(exc).__name__}", provider=self.key
            ) from exc

        if response.status_code == 429:
            raise TranslationError("rate limited", provider=self.key)
        if response.status_code >= 400:
            # 400 here usually means the chunk was too long.
            raise TranslationError(
                f"HTTP {response.status_code}",
                provider=self.key,
                retryable=response.status_code >= 500,
            )

        return _extract(response.text, provider=self.key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _extract(payload: str, *, provider: str) -> str:
    """Pull the translated text out of Google's nested array response.

    The shape is ``[[[translated, original, ...], ...], ...]`` with one entry
    per sentence, so the pieces have to be concatenated in order.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TranslationError("response was not JSON", provider=provider) from exc

    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise TranslationError("unexpected response shape", provider=provider)

    pieces: list[str] = []
    for sentence in data[0]:
        if isinstance(sentence, list) and sentence and isinstance(sentence[0], str):
            pieces.append(sentence[0])

    if not pieces:
        raise TranslationError("response contained no text", provider=provider)

    return "".join(pieces)
