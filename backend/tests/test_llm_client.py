import json

import httpx
import pytest

from app.config import Settings
from app.llm.client import LLMUnavailable, build_payload, chat_json, check

KEY = "test-secret-key-123"


def settings(**kw) -> Settings:
    base = {"groq_api_key": KEY, "llm_enabled": True, "llm_model": "openai/gpt-oss-120b",
            "llm_fallback_model": "openai/gpt-oss-20b"}
    base.update(kw)
    return Settings(_env_file=None, **base)


def ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_success_and_request_shape():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return ok('{"a": 1}')

    result = await chat_json("sys", "usr", settings=settings(), transport=httpx.MockTransport(handler))
    assert result == {"a": 1}
    body = json.loads(seen[0].content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert "temperature" not in body
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_non_reasoning_model_uses_temperature():
    body = build_payload("some/other-model", "s", "u", 100, 0.3)
    assert body["temperature"] == 0.3 and "reasoning_effort" not in body


async def test_code_fenced_json_is_accepted():
    t = httpx.MockTransport(lambda r: ok('```json\n{"a": 2}\n```'))
    assert await chat_json("s", "u", settings=settings(), transport=t) == {"a": 2}


@pytest.mark.parametrize("content", ["not json", "[1, 2]", "", None])
async def test_bad_answers_raise(content):
    t = httpx.MockTransport(lambda r: ok(content))
    with pytest.raises(LLMUnavailable):
        await chat_json("s", "u", settings=settings(), transport=t)


async def test_fallback_model_used_when_main_model_missing():
    models = []

    def handler(req):
        model = json.loads(req.content)["model"]
        models.append(model)
        return httpx.Response(404) if model == "openai/gpt-oss-120b" else ok('{"x": true}')

    result = await chat_json("s", "u", settings=settings(), transport=httpx.MockTransport(handler))
    assert result == {"x": True}
    assert models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


async def test_rate_limit_on_both_models_gives_up():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(LLMUnavailable, match="429"):
        await chat_json("s", "u", settings=settings(), transport=httpx.MockTransport(handler))
    assert len(calls) == 2


async def test_bad_key_fails_fast_with_helpful_message():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(LLMUnavailable, match="GROQ_API_KEY"):
        await chat_json("s", "u", settings=settings(), transport=httpx.MockTransport(handler))
    assert len(calls) == 1


async def test_timeout_and_network_errors():
    def slow(req):
        raise httpx.ReadTimeout("slow")

    def down(req):
        raise httpx.ConnectError("down")

    with pytest.raises(LLMUnavailable, match="timed out"):
        await chat_json("s", "u", settings=settings(), transport=httpx.MockTransport(slow))
    with pytest.raises(LLMUnavailable, match="network"):
        await chat_json("s", "u", settings=settings(), transport=httpx.MockTransport(down))


async def test_disabled_and_missing_key():
    with pytest.raises(LLMUnavailable, match="disabled"):
        await chat_json("s", "u", settings=settings(llm_enabled=False))
    with pytest.raises(LLMUnavailable, match="GROQ_API_KEY"):
        await chat_json("s", "u", settings=settings(groq_api_key=""))


async def test_check_reports_status_and_never_leaks_the_key():
    good = await check(settings(), httpx.MockTransport(lambda r: ok('{"ok": true}')))
    assert good["ok"] is True and good["model_used"] == "openai/gpt-oss-120b"
    bad = await check(settings(), httpx.MockTransport(lambda r: httpx.Response(401)))
    assert bad["ok"] is False
    missing = await check(settings(groq_api_key=""))
    assert missing["ok"] is False and missing["key_configured"] is False
    for info in (good, bad, missing):
        assert KEY not in json.dumps(info)
