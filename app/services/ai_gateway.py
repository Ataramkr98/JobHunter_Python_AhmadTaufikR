"""Thin OpenAI-compatible client for the shared AI gateway.

Standard library only, so enabling this adds no runtime dependency. Keeps the
same request shape, timeout and error wording as the other services in this
workspace. The API key is read from the Flask config and never logged.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from flask import current_app


class AiGatewayError(RuntimeError):
    """Raised when the gateway cannot be reached or returns an error."""


def is_configured() -> bool:
    """True only when an operator supplied both an endpoint and a credential.

    Both halves are required: an endpoint with no key cannot authenticate, and a
    key with no endpoint has nowhere to go. Shipping the project with neither
    set is the supported default, which keeps the app fully offline.
    """
    return bool(
        str(current_app.config.get("AI_BASE_URL", "")).strip()
        and str(current_app.config.get("AI_API_KEY", "")).strip()
    )


def resolve_model(feature: str) -> str:
    """Per-feature model override wins, then AI_MODEL_CHAT, then AI_MODEL_DEFAULT.

    There is no built-in fallback model name on purpose — the gateway is
    operator-supplied and only it knows which models it serves.
    """
    for key in (f"AI_MODEL_{feature.upper()}", "AI_MODEL_CHAT", "AI_MODEL_DEFAULT"):
        value = str(current_app.config.get(key, "") or "").strip()
        if value:
            return value
    raise AiGatewayError(
        "No AI model configured. Set AI_MODEL_DEFAULT (and AI_MODEL_CHAT) in the "
        "environment, or leave AI_EXPLAIN_MATCHES disabled."
    )


def _redact(value: str) -> str:
    return re.sub(r"(sk-[A-Za-z0-9_-]{6})[A-Za-z0-9_-]+", r"\1...", str(value))


def chat_json(
    messages: list[dict[str, str]],
    *,
    feature: str = "CHAT",
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> dict:
    """POST /chat/completions with JSON output. Returns the decoded object."""
    api_key = current_app.config.get("AI_API_KEY")
    base_url = str(current_app.config.get("AI_BASE_URL", "")).rstrip("/")
    if not api_key or not base_url:
        raise AiGatewayError("AI_BASE_URL and AI_API_KEY must both be configured")

    timeout = float(current_app.config.get("AI_TIMEOUT_SECONDS", 60))
    model = resolve_model(feature)

    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": messages,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # The upstream body is not forwarded: it can echo request headers.
        raise AiGatewayError(f"AI gateway returned {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise AiGatewayError(f"AI gateway request failed: {_redact(error)}") from None

    content = body.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise AiGatewayError("AI gateway returned invalid JSON") from None
