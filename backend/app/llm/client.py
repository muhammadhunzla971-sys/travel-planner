"""Groq chat client (OpenAI-compatible HTTP API). Hosted only - nothing runs locally.

Rules:
  * The key comes from the environment (GROQ_API_KEY) and is never logged or returned.
  * Every failure becomes `LLMUnavailable`; callers fall back to rule-based logic.
  * If the main model errors or is rate-limited, one fallback model is tried.
"""
import json
import logging
import time
from typing import Any

import httpx

from app.config import Settings, get_settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
log = logging.getLogger(__name__)

# statuses where trying the fallback model can help (bad/removed model, rate limit, overload)
_RETRY_WITH_FALLBACK = {400, 404, 429, 503}


class LLMUnavailable(Exception):
    """The LLM could not give a usable answer (disabled, no key, error, bad JSON)."""


def _is_reasoning_model(model: str) -> bool:
    return model.startswith("openai/gpt-oss")


def build_payload(model: str, system: str, user: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max_tokens,
    }
    if _is_reasoning_model(model):
        body["reasoning_effort"] = "low"      # fast; reasoning text is not needed
        body["include_reasoning"] = False
    else:
        body["temperature"] = temperature
    return body


def _extract_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        data = json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LLMUnavailable("LLM returned an unusable answer (not valid JSON)") from exc
    if not isinstance(data, dict):
        raise LLMUnavailable("LLM returned JSON that is not an object")
    return data


async def _call(system: str, user: str, *, max_tokens: int, temperature: float,
                settings: Settings | None, transport: httpx.AsyncBaseTransport | None
                ) -> tuple[dict[str, Any], str]:
    s = settings or get_settings()
    if not s.llm_enabled:
        raise LLMUnavailable("LLM is disabled (LLM_ENABLED=false)")
    if not s.groq_api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set")

    models = [s.llm_model]
    if s.llm_fallback_model and s.llm_fallback_model != s.llm_model:
        models.append(s.llm_fallback_model)

    last_error = "no model tried"
    headers = {"Authorization": f"Bearer {s.groq_api_key}"}
    async with httpx.AsyncClient(timeout=s.llm_timeout_s, transport=transport) as client:
        for index, model in enumerate(models):
            is_last = index == len(models) - 1
            try:
                resp = await client.post(
                    GROQ_URL, headers=headers,
                    json=build_payload(model, system, user, max_tokens, temperature))
            except httpx.TimeoutException as exc:
                raise LLMUnavailable("LLM timed out") from exc
            except httpx.HTTPError as exc:
                raise LLMUnavailable(f"LLM network error ({type(exc).__name__})") from exc

            if resp.status_code == 200:
                return _extract_json(resp), model
            last_error = f"LLM HTTP {resp.status_code} from {model}"
            if resp.status_code == 401:
                raise LLMUnavailable("LLM HTTP 401 - the API key was rejected (check GROQ_API_KEY)")
            if resp.status_code in _RETRY_WITH_FALLBACK and not is_last:
                log.warning("%s; trying fallback model", last_error)
                continue
            raise LLMUnavailable(last_error)
    raise LLMUnavailable(last_error)


async def chat_json(system: str, user: str, *, max_tokens: int = 1200, temperature: float = 0.2,
                    settings: Settings | None = None,
                    transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Ask the LLM for a JSON object. Raises LLMUnavailable on any problem."""
    data, _model = await _call(system, user, max_tokens=max_tokens, temperature=temperature,
                               settings=settings, transport=transport)
    return data


async def check(settings: Settings | None = None,
                transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Safe diagnostics for GET /api/llm/check. Never includes the key itself."""
    s = settings or get_settings()
    info: dict[str, Any] = {
        "enabled": s.llm_enabled,
        "key_configured": bool(s.groq_api_key),
        "model": s.llm_model,
        "fallback_model": s.llm_fallback_model,
    }
    started = time.monotonic()
    try:
        data, used = await _call('Reply with this JSON object: {"ok": true}', "ping",
                                 max_tokens=200, temperature=0.0, settings=s, transport=transport)
        info.update(ok=bool(data), model_used=used,
                    latency_ms=int((time.monotonic() - started) * 1000))
    except LLMUnavailable as exc:
        info.update(ok=False, error=str(exc))
    return info
