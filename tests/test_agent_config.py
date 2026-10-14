import json

import httpx
import pytest

from app.agent.llm import LLM, ModelError, Settings, function
from test_agent import context, identity  # shared API setup fixtures

KEY = "test-credential-do-not-expose-9384"
TOOLS = [function("get_project", "Get project", {})]


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.delenv("BUGFLOW_LLM_THINKING", raising=False)
    monkeypatch.setenv("BUGFLOW_LLM_API_KEY", KEY)
    monkeypatch.setenv("BUGFLOW_LLM_MODEL", "compatible-model")
    monkeypatch.setenv("BUGFLOW_LLM_BASE_URL", "https://compatible.example/v1")


@pytest.fixture
def transport(monkeypatch):
    original = httpx.Client
    def install(handler):
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs))
    return install


def reply(message):
    return httpx.Response(200, json={"choices": [{"message": message}]})


def probe_reply():
    return reply({"tool_calls": [{"id": "probe1", "type": "function", "function": {
        "name": "capability_probe", "arguments": "{}"}}]})


@pytest.mark.parametrize("variable", ["BUGFLOW_LLM_API_KEY", "BUGFLOW_LLM_MODEL"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_config(variable, value, monkeypatch):
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)
    with pytest.raises(ModelError) as error:
        LLM().complete([], TOOLS)
    assert error.value.code == "llm_not_configured"


def test_deepseek_nonthinking_is_explicit(monkeypatch, transport):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return reply({"content": "hello"})
    transport(handler)
    LLM().complete([], [])
    assert "thinking" not in requests[-1]
    monkeypatch.setenv("BUGFLOW_LLM_THINKING", "disabled")
    LLM().complete([], [])
    assert requests[-1]["thinking"] == {"type": "disabled"}
    monkeypatch.setenv("BUGFLOW_LLM_THINKING", "enabled")
    with pytest.raises(ModelError) as error:
        LLM().complete([], [])
    assert error.value.code == "llm_invalid_config"


@pytest.mark.parametrize("base", ["", "http://localhost:8000/v1", "https://", "https://user:pass@example.com/v1",
    "https://example.com/v1?key=123", "https://example.com/v1#x", "https://example.com:bad/v1",
    "https://exa mple.com/v1", "https://example.com/v1/chat/completions"])
def test_invalid_base_url(base, monkeypatch):
    monkeypatch.setenv("BUGFLOW_LLM_BASE_URL", base)
    with pytest.raises(ModelError) as error:
        LLM().complete([], TOOLS)
    assert error.value.code == "llm_invalid_config"
    assert KEY not in str(error.value)


def test_switch_configuration_and_probe_cache(monkeypatch, transport):
    requests = []
    def handler(request):
        data = json.loads(request.content)
        requests.append((str(request.url), request.headers['Authorization'], data))
        assert KEY not in request.content.decode()
        assert "replacement-credential" not in request.content.decode()
        return probe_reply() if data.get("tool_choice") == "required" else reply({"content": "Hello"})
    transport(handler)
    llm = LLM()
    assert llm.complete([], TOOLS)["content"] == "Hello"
    llm.complete([], TOOLS)
    assert len(requests) == 3
    monkeypatch.setenv("BUGFLOW_LLM_BASE_URL", "https://other.example/api/")
    monkeypatch.setenv("BUGFLOW_LLM_MODEL", "other-model")
    monkeypatch.setenv("BUGFLOW_LLM_API_KEY", "replacement-credential")
    llm.complete([], TOOLS)
    assert len(requests) == 5
    assert requests[-1][0] == "https://other.example/api/chat/completions"
    assert requests[-1][1] == "Bearer replacement-credential"
    assert requests[-1][2]["model"] == "other-model"
    assert KEY not in repr(Settings.load())


def test_ignored_tools_fail_before_business_data_sent(transport):
    def handler(request):
        assert "PRIVATE ISSUE" not in request.content.decode()
        return reply({"content": "Tool calling is not supported"})
    transport(handler)
    with pytest.raises(ModelError) as error:
        LLM().complete([{"role": "user", "content": "PRIVATE ISSUE"}], TOOLS)
    assert error.value.code == "llm_tools_unsupported"


@pytest.mark.parametrize("status,body,code", [
    (401, {"error": {"message": KEY}}, "llm_auth_failed"),
    (404, {}, "llm_model_or_endpoint_not_found"),
    (400, {"error": {"param": "tools", "message": KEY}}, "llm_tools_unsupported"),
    (422, {"error": {"code": "tool_calling_not_supported"}}, "llm_tools_unsupported"),
    (400, {}, "llm_request_rejected"),
])
def test_safe_classified_provider_errors(transport, status, body, code):
    transport(lambda request: httpx.Response(status, json=body))
    with pytest.raises(ModelError) as error:
        LLM().complete([], TOOLS)
    assert error.value.code == code
    assert KEY not in str(error.value)


@pytest.mark.parametrize("message", [{"content": KEY}, {"tool_calls": [{
    "id": "x", "type": "function", "function": {"name": KEY, "arguments": "{}"}}]}])
def test_credential_echo_is_blocked(transport, message):
    transport(lambda request: reply(message))
    with pytest.raises(ModelError) as error:
        LLM().complete([], [])
    assert error.value.code == "llm_secret_echo"


def test_escaped_argument_credential_is_blocked(transport):
    encoded = ''.join('\\u%04x' % ord(char) for char in KEY)
    message = {"tool_calls": [{"id": "one", "type": "function", "function": {
        "name": "get_project", "arguments": '{"leak":"' + encoded + '"}'}}]}
    transport(lambda request: reply(message))
    with pytest.raises(ModelError) as error:
        LLM().complete([], [])
    assert error.value.code == "llm_secret_echo"


@pytest.mark.parametrize("calls", ["wrong type", [{"id": "one"}],
    [{"id": "one", "type": "function", "function": {"name": "capability_probe", "arguments": "not json"}}]])
def test_malformed_tool_response(transport, calls):
    transport(lambda request: reply({"tool_calls": calls}))
    with pytest.raises(ModelError) as error:
        LLM().complete([], TOOLS)
    assert error.value.code == "llm_invalid_response"


@pytest.mark.parametrize("mode,code,status", [
    ("missing", "llm_not_configured", 503), ("auth", "llm_auth_failed", 502),
    ("unsupported", "llm_tools_unsupported", 502), ("echo", "llm_secret_echo", 502)])
def test_real_adapter_api_trace_do_not_expose_key(client, context, transport, monkeypatch, mode, code, status):
    _, headers, project = context
    if mode == "missing":
        monkeypatch.delenv("BUGFLOW_LLM_API_KEY")
    def handler(request):
        assert KEY not in request.content.decode()
        if mode == "auth":
            return httpx.Response(401, json={"error": {"message": KEY}})
        if mode == "unsupported":
            return reply({"content": "No tool support"})
        data = json.loads(request.content)
        return probe_reply() if data.get("tool_choice") == "required" else reply({"content": KEY})
    transport(handler)
    response = client.post("/agent/chat", json={"project_id": project["id"], "message": "hello"}, headers=headers)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    trace = client.get("/agent/traces/" + response.json()["detail"]["trace_id"], headers=headers)
    assert trace.status_code == 200
    assert trace.json()["events"][-1] == {"error_code": code}
    assert KEY not in response.text + trace.text
