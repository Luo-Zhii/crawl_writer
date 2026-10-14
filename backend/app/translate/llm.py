"""Translation through an LLM.

Costs money but reads far better than machine translation: it keeps tone,
handles cultivation jargon, and follows a glossary when told to. All three
providers take the same shape of request, so only the endpoint, auth header
and response path differ.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.translate.base import ProviderUnavailable, TranslateProvider, TranslationError

log = get_logger(__name__)

_LANG_NAMES = {
    "zh": "Chinese",
    "vi": "Vietnamese",
    "en": "English",
}

_SYSTEM_PROMPT = """You are translating a web novel from {source} to {target}.

Rules:
- Translate the whole passage. Do not summarise, explain, or add notes.
- Keep the paragraph breaks exactly as they are in the input.
- Keep the author's tone, including dialogue punctuation.
- Leave text that is already in {target} untouched.
- Return only the translation, with no preamble.
"""

_GLOSSARY_NOTE = """
Always use these exact renderings for names and terms:
{pairs}
"""


def _language(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def build_prompt(
    text: str, *, source_lang: str, target_lang: str, glossary: dict[str, str] | None
) -> tuple[str, str]:
    """Return (system prompt, user content)."""
    system = _SYSTEM_PROMPT.format(source=_language(source_lang), target=_language(target_lang))
    if glossary:
        pairs = "\n".join(f"- {source} = {target}" for source, target in glossary.items())
        system += _GLOSSARY_NOTE.format(pairs=pairs)
    return system, text


class LlmProvider(TranslateProvider):
    """Shared behaviour for the hosted LLM APIs."""

    metered = True
    # Larger than Google's: fewer calls means better context and less overhead,
    # but a chunk that is too big invites truncation.
    chunk_limit = 3500

    #: Default model, overridable from settings.
    model: str = ""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self.model = model or self.model
        self._owns_client = client is None
        # LLM calls are slow; the timeout is deliberately generous.
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _require_key(self) -> None:
        if not self._api_key:
            raise ProviderUnavailable(
                f"no API key saved for {self.name}; add one in Settings",
                provider=self.key,
            )

    async def translate(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,
    ) -> str:
        if not text.strip():
            return text
        self._require_key()

        system, user = build_prompt(
            text, source_lang=source_lang, target_lang=target_lang, glossary=glossary
        )

        try:
            response = await self._client.post(
                self._url(), headers=self._headers(), json=self._payload(system, user)
            )
        except httpx.HTTPError as exc:
            raise TranslationError(
                f"request failed: {type(exc).__name__}", provider=self.key
            ) from exc

        if response.status_code in (401, 403):
            raise ProviderUnavailable("API key was rejected", provider=self.key)
        if response.status_code == 429:
            raise TranslationError("rate limited", provider=self.key)
        if response.status_code >= 400:
            raise TranslationError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                provider=self.key,
                retryable=response.status_code >= 500,
            )

        try:
            result = self._extract(response.json())
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TranslationError("unexpected response shape", provider=self.key) from exc

        if not result.strip():
            raise TranslationError("empty translation", provider=self.key)
        return result.strip()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- per-provider ------------------------------------------------------

    def _url(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        raise NotImplementedError

    def _extract(self, data: dict[str, Any]) -> str:
        raise NotImplementedError


class GeminiProvider(LlmProvider):
    key = "gemini"
    name = "Gemini"
    model = "gemini-2.0-flash"

    def _url(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            # Low temperature: this is translation, not creative writing.
            "generationConfig": {"temperature": 0.2},
        }

    def _extract(self, data: dict[str, Any]) -> str:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)


class OpenAiProvider(LlmProvider):
    key = "openai"
    name = "OpenAI"
    model = "gpt-4o-mini"

    def _url(self) -> str:
        return "https://api.openai.com/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    def _extract(self, data: dict[str, Any]) -> str:
        return data["choices"][0]["message"]["content"]


class AnthropicProvider(LlmProvider):
    key = "anthropic"
    name = "Claude"
    model = "claude-sonnet-4-5"

    def _url(self) -> str:
        return "https://api.anthropic.com/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": 8192,
            "temperature": 0.2,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

    def _extract(self, data: dict[str, Any]) -> str:
        return "".join(
            block.get("text", "") for block in data["content"] if block.get("type") == "text"
        )


LLM_PROVIDERS: dict[str, type[LlmProvider]] = {
    GeminiProvider.key: GeminiProvider,
    OpenAiProvider.key: OpenAiProvider,
    AnthropicProvider.key: AnthropicProvider,
}
