"""The live OpenAI-compatible transport, driven through an in-process mock HTTP transport
(no socket is opened, so the network guard stays satisfied)."""

import json

import httpx2
import openai
import pytest
from pydantic import SecretStr

from app.llm.gateway import LLMGateway
from app.llm.live_check import PROBES, run
from app.llm.messages import Outcome
from app.llm.prompts import plan_request, vote_request
from app.llm.providers import GEMINI_FLASH, GROQ_QWEN, OLLAMA_QWEN
from app.llm.transport import FixtureStore, OpenAICompatTransport, ProviderError
from tests.agents.helpers import Scripted

GROQ_KEY = "gsk_test_not_a_real_key_0000"


def completion(content: str) -> dict:
    return {"id": "c1", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49}}


def mock_client(handler) -> openai.DefaultHttpxClient:
    return openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler))


@pytest.fixture
def keyed(live_settings):
    return live_settings.model_copy(update={"groq_api_key": SecretStr(GROQ_KEY)})


def test_request_goes_to_the_provider_endpoint_with_json_mode(keyed):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json=completion('{"choice": "opt_a"}'))

    transport = OpenAICompatTransport(keyed, http_client=mock_client(handler))
    result = transport.send(GROQ_QWEN, vote_request("Which?", [{"id": "opt_a", "summary": "a"}]))
    [request] = seen
    body = json.loads(request.content)
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {GROQ_KEY}"
    assert body["model"] == "qwen/qwen3-32b"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert (result.text, result.tokens_in, result.tokens_out) == ('{"choice": "opt_a"}', 40, 9)


def test_keys_come_from_settings_and_local_models_need_none(keyed):
    transport = OpenAICompatTransport(keyed)
    assert transport.has_key(GROQ_QWEN) is True
    assert transport.has_key(GEMINI_FLASH) is False  # no Gemini key configured
    assert transport.has_key(OLLAMA_QWEN) is True


@pytest.mark.parametrize(("status", "outcome"), [
    (429, Outcome.rate_limited),
    (503, Outcome.server_error),
    (404, Outcome.bad_request),  # e.g. a renamed model
    (401, Outcome.bad_request),
])
def test_http_errors_map_to_outcomes(keyed, status, outcome):
    client = mock_client(lambda r: httpx2.Response(status, json={"error": {"message": "x"}}))
    transport = OpenAICompatTransport(keyed, http_client=client)
    with pytest.raises(ProviderError) as caught:
        transport.send(GROQ_QWEN, plan_request("cash?"))
    assert caught.value.outcome is outcome


@pytest.mark.parametrize(("error", "outcome"), [
    (httpx2.ReadTimeout("slow"), Outcome.timeout),
    (httpx2.ConnectError("refused"), Outcome.unreachable),
])
def test_transport_errors_map_to_outcomes(keyed, error, outcome):
    def handler(request):
        raise error

    transport = OpenAICompatTransport(keyed, http_client=mock_client(handler))
    with pytest.raises(ProviderError) as caught:
        transport.send(GROQ_QWEN, plan_request("cash?"))
    assert caught.value.outcome is outcome


def test_empty_completion_is_a_bad_response(keyed):
    body = completion("x")
    body["choices"][0]["message"]["content"] = None
    client = mock_client(lambda r: httpx2.Response(200, json=body))
    with pytest.raises(ProviderError) as caught:
        OpenAICompatTransport(keyed, http_client=client).send(GROQ_QWEN, plan_request("cash?"))
    assert caught.value.outcome is Outcome.bad_response


def test_live_gateway_without_a_gemini_key_never_calls_gemini(keyed, clock):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx2.Response(200, json=completion("{}"))

    gw = LLMGateway(keyed, transport=OpenAICompatTransport(keyed, http_client=mock_client(handler)),
                    clock=clock)
    reply = gw.complete(plan_request("Will I run out of cash?"))
    assert calls == [] and reply.deterministic
    assert [(a.slot, a.outcome) for a in reply.attempts][0] == ("gemini_flash", Outcome.no_key)


def test_usage_report_never_contains_keys_or_prompts(keyed, clock):
    client = mock_client(lambda r: httpx2.Response(200, json=completion('{"choice": "opt_a"}')))
    gw = LLMGateway(keyed, transport=OpenAICompatTransport(keyed, http_client=client),
                    clock=clock)
    gw.complete(vote_request("Secret-ish question about Supplier 4?",
                             [{"id": "opt_a", "summary": "a"}]))
    report = json.dumps(gw.usage())
    assert GROQ_KEY not in report and "Supplier 4" not in report
    assert gw.usage()["slots"]["groq_gpt_oss_120b"]["successes"] == 1


def test_live_check_records_fixtures_and_a_trace_per_call(tmp_path, live_settings, clock):
    answers = {"plan": '{"intents": ["cash_outlook"], "tools": [], "language": "en"}',
               "vote": '{"choice": "opt_overdraft", "rationale": "cheapest"}',
               "critique": '{"objection": "approval is slower than the gap", "severity": "high"}'}
    scripted = Scripted({"groq_qwen": [answers[task] for task, _ in PROBES]})
    code = run(live_settings, ["groq_qwen", "groq_gpt_oss_20b"], {}, FixtureStore(tmp_path),
               tmp_path / "traces", transport=scripted, clock=clock)
    [trace] = (tmp_path / "traces").glob("live-*.jsonl")
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [(r["slot"], r["task"], r["outcome"]) for r in rows] == [
        ("groq_qwen", "plan", "ok"), ("groq_qwen", "vote", "ok"), ("groq_qwen", "critique", "ok"),
        ("groq_gpt_oss_20b", "plan", "unreachable"), ("groq_gpt_oss_20b", "vote", "cooling_down"),
        ("groq_gpt_oss_20b", "critique", "cooling_down")]
    assert code == 1  # one slot failed
    assert len(list((tmp_path / "groq_qwen").glob("*.json"))) == 3
    assert not (tmp_path / "groq_gpt_oss_20b").exists()
