import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit
import httpx


ERRORS = {
    "llm_not_configured": "Set BUGFLOW_LLM_API_KEY and BUGFLOW_LLM_MODEL on the backend.",
    "llm_invalid_config": "Check LLM configuration: HTTPS base URL without credentials/query; valid key and model required.",
    "llm_auth_failed": "Provider authentication rejected; check the backend API key and permissions.",
    "llm_model_or_endpoint_not_found": "Check BUGFLOW_LLM_MODEL and BUGFLOW_LLM_BASE_URL.",
    "llm_tools_unsupported": "Provider did not honor required tool calling; choose a compatible model and endpoint.",
    "llm_request_rejected": "Provider rejected the request; check model and Chat Completions compatibility.",
    "llm_rate_limited": "Provider rate limit reached; retry later.",
    "llm_unavailable": "Provider unavailable after bounded retries.",
    "llm_timeout": "Provider request timed out.",
    "llm_invalid_response": "Provider returned an invalid or oversized response.",
    "llm_secret_echo": "Provider response blocked because it contained the configured credential.",
    "llm_failed": "Agent model failed.",
}


class ModelError(RuntimeError):
    def __init__(self, code="llm_failed"):
        self.code = code if code in ERRORS else "llm_failed"
        super().__init__(ERRORS[self.code])


def contains_credential(value, key):
    if isinstance(value, str):
        return key in value
    if isinstance(value, dict):
        return any(contains_credential(k, key) or contains_credential(v, key) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_credential(item, key) for item in value)
    return False


@dataclass(frozen=True)
class Settings:
    key: str = field(repr=False)
    model: str
    base: str
    thinking: str | None = None

    @classmethod
    def load(cls):
        key = os.getenv("BUGFLOW_LLM_API_KEY", "").strip()
        model = os.getenv("BUGFLOW_LLM_MODEL", "").strip()
        base = os.getenv("BUGFLOW_LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        thinking = os.getenv("BUGFLOW_LLM_THINKING", "").strip() or None
        if thinking not in (None, "disabled"):
            raise ModelError("llm_invalid_config")
        if not key or not model:
            raise ModelError("llm_not_configured")
        try:
            url = urlsplit(base)
            _ = url.port
            if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment
                or any(c.isspace() or ord(c) < 32 for c in base) or "\\" in base
                or base.endswith("/chat/completions")
                or any(ord(c) < 32 or ord(c) > 126 for c in key)
                or any(c.isspace() for c in key) or any(ord(c) < 32 for c in model)):
                raise ValueError()
        except ValueError:
            raise ModelError("llm_invalid_config") from None
        return cls(key, model, base, thinking)


class LLM:
    """Real Chat Completions tool calling; no fallback answers."""
    def __init__(self):
        self._verified = None

    def complete(self, messages, tools):
        settings = Settings.load()
        if tools and self._verified != settings:
            probe = self._request(settings,
                [{"role": "user", "content": "Call capability_probe with no arguments."}],
                [function("capability_probe", "Harmless capability check; no execution", {})], "required")
            calls = probe.get("tool_calls") or []
            if (len(calls) != 1 or calls[0]["function"]["name"] != "capability_probe"
                or json.loads(calls[0]["function"]["arguments"]) != {}):
                raise ModelError("llm_tools_unsupported")
            self._verified = settings
        return self._request(settings, messages, tools, "auto")

    def _request(self, settings, messages, tools, choice):
        payload = {"model": settings.model, "messages": messages, "max_tokens": 2000}
        if settings.thinking is not None:
            payload["thinking"] = {"type": settings.thinking}
        if tools:
            payload.update(tools=tools, tool_choice=choice)
        for attempt in range(2):
            try:
                with httpx.Client(timeout=30, trust_env=False) as client:
                    with client.stream("POST", settings.base + "/chat/completions",
                        headers={"Authorization": f"Bearer {settings.key}"}, json=payload) as response:
                        body = bytearray()
                        deadline = time.monotonic() + 30
                        for chunk in response.iter_bytes():
                            if time.monotonic() > deadline:
                                raise ModelError("llm_timeout")
                            body.extend(chunk)
                            if len(body) > 128_000:
                                raise ModelError("llm_invalid_response")
                        response.raise_for_status()
                message = json.loads(body)["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise ValueError()
                if contains_credential(message, settings.key):
                    raise ModelError("llm_secret_echo")
                content = message.get("content")
                if content is not None and not isinstance(content, str):
                    raise ValueError()
                calls = message.get("tool_calls")
                if calls is not None:
                    if not isinstance(calls, list):
                        raise ValueError()
                    ids = set()
                    for call in calls:
                        if (not isinstance(call, dict) or call.get("type") != "function"
                            or not isinstance(call.get("id"), str) or not call["id"]
                            or call["id"] in ids or not isinstance(call.get("function"), dict)):
                            raise ValueError()
                        ids.add(call["id"])
                        fn = call["function"]
                        if (not isinstance(fn.get("name"), str) or not fn["name"]
                            or not isinstance(fn.get("arguments"), str)
                            or not isinstance(json.loads(fn["arguments"]), dict)):
                            raise ValueError()
                        if contains_credential(json.loads(fn["arguments"]), settings.key):
                            raise ModelError("llm_secret_echo")
                return message
            except httpx.HTTPStatusError as error:
                if attempt == 0 and (error.response.status_code == 429 or error.response.status_code >= 500):
                    time.sleep(0.2)
                    continue
                status = error.response.status_code
                try:
                    provider_error = json.loads(body).get("error", {})
                    unsupported = isinstance(provider_error, dict) and (
                        provider_error.get("param") in ("tools", "tool_choice")
                        or provider_error.get("code") in ("unsupported_tools", "tool_calling_not_supported"))
                except (ValueError, AttributeError):
                    unsupported = False
                if status in (400, 422) and unsupported:
                    raise ModelError("llm_tools_unsupported") from None
                code = {401: "llm_auth_failed", 403: "llm_auth_failed",
                        404: "llm_model_or_endpoint_not_found", 429: "llm_rate_limited"}.get(status)
                # Do not expose or persist arbitrary provider error bodies.
                raise ModelError(code or ("llm_unavailable" if status >= 500 else "llm_request_rejected")) from None
            except httpx.TransportError as error:
                if attempt == 0:
                    continue
                raise ModelError("llm_timeout" if isinstance(error, httpx.TimeoutException) else "llm_unavailable") from None
            except (ValueError, KeyError, IndexError, TypeError):
                raise ModelError("llm_invalid_response") from None


def function(name, description, properties, required=None):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required if required is not None else list(properties),
                       "additionalProperties": False}}}
