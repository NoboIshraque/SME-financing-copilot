import json
from datetime import date, timedelta

import pytest

from app.llm.cache import CachedAnswer, MemoryCache
from app.llm.gateway import LLMGateway, NoProviderAvailable, parse_json_object, prepare_messages
from app.llm.messages import LLMRequest, Message, Outcome, Task
from app.llm.prompts import critique_request, narrate_request, plan_request, vote_request
from app.llm.providers import Role
from app.llm.transport import FixtureStore, FixtureTransport, RecordingTransport
from app.privacy import PrivacyViolation, TokenVault
from app.settings import LLMMode
from tests.agents.helpers import Scripted

PLAN_JSON = json.dumps({"intents": ["cash_outlook"], "tools": ["cash.forecast", "cash.gaps"],
                        "language": "en"})
VOTE_JSON = '{"choice": "opt_a", "rationale": "cheapest"}'


def gateway(settings, transport, clock, **kw):
    return LLMGateway(settings, transport=transport, clock=clock, **kw)


def vote(question="Which option?"):
    return vote_request(question, [{"id": "opt_a", "summary": "a"},
                                   {"id": "opt_b", "summary": "b"}], default="opt_b")


def slots(response):
    return [(a.slot, a.outcome) for a in response.attempts]


# --- privacy gate (fail closed) ------------------------------------------------------------

@pytest.mark.parametrize(("text", "context", "kind"), [
    ("Call me on 01712-345678", {}, "PHONE"),
    ("My NID is 1987654321", {}, "NID"),
    ("write to owner@example.com", {}, "EMAIL"),
    ("ফোন ০১৭১২৩৪৫৬৭৮ নম্বরে", {}, "PHONE"),
    ("How much does Customer 1 owe?", {"question": "How much does Babul owe?"}, "PERSON"),
])
def test_unsafe_payload_is_refused_before_any_provider(settings, clock, text, context, kind):
    transport = Scripted({"gemini_flash": [PLAN_JSON]})
    gw = gateway(settings, transport, clock)
    request = LLMRequest(Role.brain, Task.plan, (Message("user", text),), context=context)
    with pytest.raises(PrivacyViolation) as caught:
        gw.complete(request)
    assert kind in {k.value for k in caught.value.kinds}
    assert transport.calls == []
    assert gw.usage()["refused_by_privacy_gate"] == 1


def test_refusal_names_the_kind_never_the_value(settings, clock):
    gw = gateway(settings, Scripted(), clock)
    with pytest.raises(PrivacyViolation) as caught:
        gw.complete(plan_request("pay 01812345678 today"))
    assert "01812345678" not in str(caught.value)
    assert "PHONE" in str(caught.value)


def test_registry_names_passed_by_the_caller_are_also_blocked(settings, clock):
    gw = gateway(settings, Scripted({"gemini_flash": [PLAN_JSON]}), clock)
    request = plan_request("Will Moyna Traders pay?", shop_names=("Moyna Traders",))
    with pytest.raises(PrivacyViolation):
        gw.complete(request)


def test_prepared_messages_share_labels_pass_the_gate_and_restore(settings, clock):
    vault = TokenVault(b"0123456789abcdef0123456789abcdef")
    raw = (Message("system", "You help a shop."),
           Message("user", "Karim (01712-345678) owes Tk 4,500 since 2026-09-14."),
           Message("user", "Should I remind Karim?"))
    safe, anon = prepare_messages(raw, vault=vault, tenant="sme_grocery",
                                  anchor=date(2026, 9, 30))
    assert safe[1].content == "Person 1 (Contact 1) owes Tk 4,500 since day t-16."
    assert safe[2].content == "Should I remind Person 1?"
    transport = Scripted({"gemini_flash": ['{"text": "Remind Person 1 today."}']})
    reply = gateway(settings, transport, clock).complete(
        LLMRequest(Role.brain, Task.narrate, safe))
    assert anon.restore(reply.data["text"]).startswith("Remind PERSON_")


# --- fallback chains ----------------------------------------------------------------------

@pytest.mark.parametrize(("mode", "role", "private", "exclude", "expected"), [
    (LLMMode.live, Role.brain, False, (), ["gemini_flash", "deterministic"]),
    (LLMMode.live, Role.voter, False, (),
     ["groq_gpt_oss_120b", "groq_qwen", "groq_gpt_oss_20b", "gemma", "deterministic"]),
    (LLMMode.live, Role.critic, False, ("google",),
     ["groq_qwen", "groq_gpt_oss_120b", "groq_gpt_oss_20b", "deterministic"]),
    (LLMMode.live, Role.critic, False, ("openai", "alibaba"), ["gemma", "deterministic"]),
    (LLMMode.live, Role.brain, True, (), ["ollama_qwen", "deterministic"]),
    (LLMMode.live, Role.critic, True, ("alibaba",), ["deterministic"]),
    (LLMMode.fixtures, Role.brain, False, (), ["gemini_flash", "deterministic"]),
    (LLMMode.deterministic, Role.voter, False, (), ["deterministic"]),
])
def test_chain_order(settings, clock, mode, role, private, exclude, expected):
    gw = gateway(settings.model_copy(update={"llm_mode": mode}), Scripted(), clock)
    request = LLMRequest(role, Task.vote, (), private=private, exclude_families=exclude)
    assert [p.slot for p in gw.chain_for(request)] == expected


def test_failures_walk_the_chain_in_order(live_settings, clock):
    transport = Scripted({"groq_gpt_oss_120b": [Outcome.timeout],
                          "groq_qwen": [Outcome.server_error],
                          "groq_gpt_oss_20b": [VOTE_JSON]})
    reply = gateway(live_settings, transport, clock).complete(vote())
    assert slots(reply) == [("groq_gpt_oss_120b", Outcome.timeout),
                            ("groq_qwen", Outcome.server_error),
                            ("groq_gpt_oss_20b", Outcome.ok)]
    assert reply.slot == "groq_gpt_oss_20b" and reply.family == "openai"
    assert reply.degraded and not reply.deterministic


def test_brain_down_degrades_to_the_deterministic_planner(live_settings, clock):
    transport = Scripted({"gemini_flash": [Outcome.rate_limited]})
    reply = gateway(live_settings, transport, clock).complete(
        plan_request("Will I run out of cash?"))
    assert reply.deterministic and reply.degraded
    assert reply.data["tools"] == ["cash.forecast", "cash.gaps"]


def test_invalid_json_counts_as_a_failure_and_moves_on(live_settings, clock):
    transport = Scripted({"groq_gpt_oss_120b": ["Sure! The best option is A."],
                          "groq_qwen": [VOTE_JSON]})
    reply = gateway(live_settings, transport, clock).complete(vote())
    assert slots(reply)[0] == ("groq_gpt_oss_120b", Outcome.bad_response)
    assert reply.data == {"choice": "opt_a", "rationale": "cheapest"}


def test_pinned_slot_without_rules_fallback_raises_when_it_fails(live_settings, clock):
    gw = gateway(live_settings, Scripted({"groq_qwen": [Outcome.rate_limited]}), clock)
    with pytest.raises(NoProviderAvailable) as caught:
        gw.complete(vote(), slots=["groq_qwen"], rules_fallback=False)
    assert [(a.slot, a.outcome) for a in caught.value.attempts] == [
        ("groq_qwen", Outcome.rate_limited)]


def test_private_mode_never_calls_a_remote_model(live_settings, clock):
    transport = Scripted({"gemini_flash": [VOTE_JSON], "ollama_qwen": [VOTE_JSON]})
    request = vote_request("Which?", [{"id": "opt_a", "summary": "a"}], private=True)
    reply = gateway(live_settings, transport, clock).complete(
        request, slots=["gemini_flash", "ollama_qwen"])
    assert transport.calls == ["ollama_qwen"]
    assert reply.slot == "ollama_qwen"


def test_free_chat_has_no_rule_based_answer(settings, clock):
    gw = gateway(settings.model_copy(update={"llm_mode": LLMMode.deterministic}),
                 Scripted(), clock)
    with pytest.raises(NoProviderAvailable) as caught:
        gw.complete(LLMRequest(Role.brain, Task.chat, (Message("user", "hello"),)))
    assert [(a.slot, a.outcome) for a in caught.value.attempts] == [
        ("deterministic", Outcome.unsupported)]


# --- graceful degradation: cooldowns and budgets ------------------------------------------

def test_rate_limited_slot_cools_down_then_is_tried_again(live_settings, clock):
    transport = Scripted({"gemini_flash": [Outcome.rate_limited, PLAN_JSON]})
    gw = gateway(live_settings, transport, clock)
    gw.complete(plan_request("cash next week?"))
    clock.advance(seconds=59)
    second = gw.complete(plan_request("cash next month?"))
    assert slots(second)[0] == ("gemini_flash", Outcome.cooling_down)
    assert transport.calls == ["gemini_flash"]
    clock.advance(seconds=2)
    third = gw.complete(plan_request("cash in two months?"))
    assert third.slot == "gemini_flash" and transport.calls == ["gemini_flash"] * 2


def test_cooldown_doubles_with_consecutive_failures(live_settings, clock):
    transport = Scripted({"gemini_flash": [Outcome.server_error]})
    gw = gateway(live_settings, transport, clock)
    gw.complete(plan_request("cash?"))  # 1st failure: 30 s
    clock.advance(seconds=31)
    gw.complete(plan_request("cash again?"))  # 2nd failure: 60 s
    clock.advance(seconds=59)
    assert slots(gw.complete(plan_request("cash now?")))[0][1] is Outcome.cooling_down
    clock.advance(seconds=2)
    gw.complete(plan_request("and now?"))
    assert transport.calls == ["gemini_flash"] * 3


def test_per_minute_budget_degrades_before_the_provider_refuses(live_settings, clock):
    transport = Scripted({"gemini_flash": [PLAN_JSON]})
    gw = gateway(live_settings, transport, clock)
    for n in range(10):  # Gemini Flash: 10 requests per minute
        assert gw.complete(plan_request(f"cash question {n}?")).slot == "gemini_flash"
    over = gw.complete(plan_request("cash question 10?"))
    assert slots(over)[0] == ("gemini_flash", Outcome.over_budget) and over.deterministic
    clock.advance(minutes=1)
    assert gw.complete(plan_request("cash question 11?")).slot == "gemini_flash"
    assert len(transport.calls) == 11


def test_budgets_bind_live_calls_but_not_fixture_replay(settings, live_settings, clock):
    assert gateway(live_settings, Scripted(), clock).enforce_budgets is True
    assert gateway(settings, Scripted(), clock).enforce_budgets is False


def test_missing_key_skips_the_provider_without_a_request(live_settings, clock):
    transport = Scripted({"gemini_flash": [PLAN_JSON]}, keys=False)
    reply = gateway(live_settings, transport, clock).complete(plan_request("cash?"))
    assert slots(reply) == [("gemini_flash", Outcome.no_key), ("deterministic", Outcome.ok)]
    assert transport.calls == []


def test_usage_counters_per_provider(live_settings, clock):
    transport = Scripted({"groq_gpt_oss_120b": [Outcome.rate_limited],
                          "groq_qwen": [VOTE_JSON]})
    gw = gateway(live_settings, transport, clock)
    gw.complete(vote())
    gw.complete(vote())  # cache hit on qwen; 120b is cooling down
    usage = gw.usage()["slots"]
    assert usage["groq_gpt_oss_120b"]["failures"] == {"rate_limited": 1}
    assert usage["groq_gpt_oss_120b"]["skipped"] == {"cooling_down": 1}
    assert (usage["groq_qwen"]["successes"], usage["groq_qwen"]["cache_hits"]) == (1, 1)
    assert (usage["groq_qwen"]["tokens_in"], usage["groq_qwen"]["tokens_out"]) == (12, 7)


# --- cache --------------------------------------------------------------------------------

def test_same_anonymised_prompt_is_served_from_the_cache(live_settings, clock):
    transport = Scripted({"gemini_flash": [PLAN_JSON]})
    gw = gateway(live_settings, transport, clock)
    first = gw.complete(plan_request("Will I run out of cash?"))
    second = gw.complete(plan_request("Will I run out of cash?"))
    assert transport.calls == ["gemini_flash"]
    assert not first.cached and second.cached
    assert second.data == first.data and second.prompt_hash == first.prompt_hash


def test_cache_is_per_prompt_and_per_model(live_settings, clock):
    transport = Scripted({"groq_gpt_oss_120b": [VOTE_JSON], "groq_qwen": [VOTE_JSON]})
    gw = gateway(live_settings, transport, clock)
    gw.complete(vote("Which option?"), slots=["groq_gpt_oss_120b"])
    gw.complete(vote("Which option now?"), slots=["groq_gpt_oss_120b"])
    gw.complete(vote("Which option?"), slots=["groq_qwen"])
    assert transport.calls == ["groq_gpt_oss_120b", "groq_gpt_oss_120b", "groq_qwen"]


def test_memory_cache_expires_and_evicts_least_recently_used(clock):
    cache = MemoryCache(max_entries=2, ttl=timedelta(hours=1))
    cache.put("a", CachedAnswer("A", clock()))
    cache.put("b", CachedAnswer("B", clock()))
    assert cache.get("a", clock()).text == "A"  # a is now the most recent
    cache.put("c", CachedAnswer("C", clock()))
    assert cache.get("b", clock()) is None and len(cache) == 2
    assert cache.get("a", clock() + timedelta(hours=1)) is None


# --- fixtures -----------------------------------------------------------------------------

def test_recorded_fixture_replays_without_network(settings, clock):
    gw = gateway(settings, FixtureTransport(), clock)
    reply = gw.complete(plan_request("Will I run out of cash next month?"))
    assert (reply.slot, reply.deterministic) == ("gemini_flash", False)
    assert reply.data == {"intents": ["cash_outlook"], "language": "en",
                          "tools": ["cash.forecast", "cash.gaps"]}


def test_missing_fixture_falls_back_to_the_rules(settings, clock):
    reply = gateway(settings, FixtureTransport(), clock).complete(
        plan_request("Should I negotiate with Supplier 2?"))
    assert slots(reply) == [("gemini_flash", Outcome.fixture_missing),
                            ("deterministic", Outcome.ok)]
    assert reply.data["intents"] == ["negotiate"]


def test_recording_then_replay_round_trip(tmp_path, live_settings, settings, clock):
    store = FixtureStore(tmp_path)
    recorder = RecordingTransport(Scripted({"groq_qwen": [VOTE_JSON]}), store, clock)
    live = gateway(live_settings, recorder, clock)
    recorded = live.complete(vote(), slots=["groq_qwen"], rules_fallback=False)
    [path] = recorder.recorded
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert (saved["source"], saved["prompt_hash"]) == ("live", recorded.prompt_hash)
    replayed = gateway(settings, FixtureTransport(store), clock).complete(
        vote(), slots=["groq_qwen"], rules_fallback=False)
    assert replayed.text == recorded.text and replayed.slot == "groq_qwen"


# --- parsing and prompts ------------------------------------------------------------------

@pytest.mark.parametrize(("text", "expected"), [
    ('{"choice": "a"}', {"choice": "a"}),
    ('```json\n{"choice": "a"}\n```', {"choice": "a"}),
    ('<think>compare a and b</think>\n{"choice": "b"}', {"choice": "b"}),
    ('["a", "b"]', None),
    ("The answer is a.", None),
])
def test_parse_json_object(text, expected):
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("request_", [
    plan_request("Will I run out of cash?"),
    vote(),
    critique_request("Take the overdraft.", ["gap of Tk 80000 from day t+12"]),
    narrate_request(["Cash falls below zero on day t+12."], language="bn"),
], ids=["plan", "vote", "critique", "narrate"])
def test_every_prompt_passes_the_gate_and_forbids_model_arithmetic(settings, clock, request_):
    reply = gateway(settings.model_copy(update={"llm_mode": LLMMode.deterministic}),
                    Scripted(), clock).complete(request_)
    assert reply.deterministic and reply.data is not None
    system = request_.messages[0].content
    assert "Never calculate or state a number" in system
    assert "<data>" in request_.messages[1].content
