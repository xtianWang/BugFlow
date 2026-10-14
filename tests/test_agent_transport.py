import httpx
import pytest
from app.agent.llm import LLM, ModelError


def test_missing_key_does_not_fake_answer(monkeypatch):
    monkeypatch.delenv("BUGFLOW_LLM_API_KEY", raising=False)
    with pytest.raises(ModelError):
        LLM().complete([], [])


def test_real_transport_contract_and_retry(monkeypatch):
    monkeypatch.setenv("BUGFLOW_LLM_API_KEY", "test-key")
    monkeypatch.setenv("BUGFLOW_LLM_MODEL", "test-model")
    client_type = httpx.Client
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-key"
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    assert LLM().complete([{"role": "user", "content": "question"}], [])["content"] == "answer"
    assert len(requests) == 2


def test_provider_error_redacted(monkeypatch):
    monkeypatch.setenv("BUGFLOW_LLM_API_KEY", "test-key")
    monkeypatch.setenv("BUGFLOW_LLM_MODEL", "test-model")
    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, text="private provider body")), **kwargs))
    with pytest.raises(ModelError, match="rejected") as result:
        LLM().complete([], [])
    assert "private" not in str(result.value)
