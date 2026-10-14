"""Translation providers, with the network mocked.

The LLM providers cannot be exercised for real without paid keys, so their
request shape and response parsing are pinned here instead.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.translate.base import ProviderUnavailable, TranslationError
from app.translate.google import ENDPOINT, GoogleTranslateProvider
from app.translate.llm import (
    AnthropicProvider,
    GeminiProvider,
    OpenAiProvider,
    build_prompt,
)

# What Google's endpoint actually returns: one entry per sentence.
GOOGLE_OK = [[["Tiêu Viêm bước vào.", "萧炎走了进来。", None, None, 10]], None, "zh-CN"]


def google_body(*sentences: str) -> str:
    return json.dumps([[[s, "", None, None, 1] for s in sentences], None, "zh-CN"])


# --- google ----------------------------------------------------------------


@respx.mock
async def test_google_translates():
    respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=GOOGLE_OK))
    provider = GoogleTranslateProvider()

    result = await provider.translate("萧炎走了进来。", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert result == "Tiêu Viêm bước vào."


@respx.mock
async def test_google_joins_sentence_pieces_in_order():
    """The endpoint splits long text; the pieces must be concatenated, not picked."""
    respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, text=google_body("Câu một. ", "Câu hai."))
    )
    provider = GoogleTranslateProvider()

    result = await provider.translate("句一。句二。", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert result == "Câu một. Câu hai."


@respx.mock
async def test_google_sends_the_language_pair():
    route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=GOOGLE_OK))
    provider = GoogleTranslateProvider()

    await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    request = route.calls.last.request
    assert request.url.params["sl"] == "zh"
    assert request.url.params["tl"] == "vi"
    assert request.url.params["q"] == "文本"
    assert "Mozilla" in request.headers["user-agent"], "the endpoint refuses scripts"


async def test_google_returns_blank_text_untouched():
    provider = GoogleTranslateProvider()

    assert await provider.translate("   ", source_lang="zh", target_lang="vi") == "   "
    await provider.aclose()


@respx.mock
async def test_google_rate_limit_is_retryable():
    respx.get(ENDPOINT).mock(return_value=httpx.Response(429))
    provider = GoogleTranslateProvider()

    with pytest.raises(TranslationError) as exc:
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert exc.value.retryable is True


@respx.mock
async def test_google_bad_request_is_not_retryable():
    """A 400 here means the chunk was too long; retrying sends the same chunk."""
    respx.get(ENDPOINT).mock(return_value=httpx.Response(400))
    provider = GoogleTranslateProvider()

    with pytest.raises(TranslationError) as exc:
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert exc.value.retryable is False


@respx.mock
@pytest.mark.parametrize("payload", ["not json", "{}", "[]", '[[]]', '[[[]]]'])
async def test_google_unusable_responses_are_errors(payload: str):
    """Never return junk as if it were a translation."""
    respx.get(ENDPOINT).mock(return_value=httpx.Response(200, text=payload))
    provider = GoogleTranslateProvider()

    with pytest.raises(TranslationError):
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()


@respx.mock
async def test_google_network_failure_is_reported():
    respx.get(ENDPOINT).mock(side_effect=httpx.ConnectError("down"))
    provider = GoogleTranslateProvider()

    with pytest.raises(TranslationError, match="request failed"):
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()


# --- prompt ----------------------------------------------------------------


def test_prompt_names_both_languages():
    system, user = build_prompt("文本", source_lang="zh", target_lang="vi", glossary=None)

    assert "Chinese" in system and "Vietnamese" in system
    assert user == "文本"


def test_prompt_carries_the_glossary():
    system, _ = build_prompt(
        "文本", source_lang="zh", target_lang="vi", glossary={"萧炎": "Tiêu Viêm"}
    )

    assert "萧炎 = Tiêu Viêm" in system


def test_prompt_forbids_summarising():
    """An LLM asked to translate a chapter will otherwise sometimes summarise it."""
    system, _ = build_prompt("文本", source_lang="zh", target_lang="vi", glossary=None)

    assert "summarise" in system.lower()
    assert "paragraph breaks" in system.lower()


# --- llm providers ---------------------------------------------------------


async def test_llm_without_a_key_is_unavailable():
    """Must be distinguishable from a failure, so the chain can skip it."""
    provider = GeminiProvider(None)

    assert provider.configured is False
    with pytest.raises(ProviderUnavailable):
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()


@respx.mock
async def test_gemini_request_and_response():
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Bản dịch"}]}}]},
        )
    )
    provider = GeminiProvider("test-key")

    result = await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert result == "Bản dịch"
    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["generationConfig"]["temperature"] == 0.2


@respx.mock
async def test_openai_request_and_response():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "Bản dịch"}}]}
        )
    )
    provider = OpenAiProvider("sk-test")

    result = await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert result == "Bản dịch"
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


@respx.mock
async def test_anthropic_request_and_response():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Bản dịch"}]},
        )
    )
    provider = AnthropicProvider("sk-ant-test")

    result = await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert result == "Bản dịch"
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sk-ant-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["system"], "the prompt belongs in the system field for Claude"


@respx.mock
async def test_anthropic_ignores_non_text_blocks():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": "..."},
                    {"type": "text", "text": "Bản dịch"},
                ]
            },
        )
    )
    provider = AnthropicProvider("sk-ant-test")

    assert await provider.translate("文本", source_lang="zh", target_lang="vi") == "Bản dịch"
    await provider.aclose()


@respx.mock
async def test_rejected_key_is_permanent_not_retryable():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    provider = OpenAiProvider("sk-wrong")

    with pytest.raises(ProviderUnavailable) as exc:
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert exc.value.retryable is False


@respx.mock
async def test_server_error_is_retryable():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(503, text="overloaded")
    )
    provider = OpenAiProvider("sk-test")

    with pytest.raises(TranslationError) as exc:
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()

    assert exc.value.retryable is True


@respx.mock
async def test_empty_llm_output_is_an_error():
    """Returning "" would silently wipe the chapter."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})
    )
    provider = OpenAiProvider("sk-test")

    with pytest.raises(TranslationError, match="empty translation"):
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()


@respx.mock
async def test_unexpected_llm_shape_is_an_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )
    provider = OpenAiProvider("sk-test")

    with pytest.raises(TranslationError, match="unexpected response shape"):
        await provider.translate("文本", source_lang="zh", target_lang="vi")
    await provider.aclose()
