"""The copilot's suggested questions can never come back as "I won't guess" (Session A).

The web offers each role a few questions (`copilot.suggest.<role>.<n>` in the locale files).
Every one, in every language, must plan to an intent the copilot has tools for; in English
each must also be answered on the grocery shop the demo accountant and staff belong to,
through the real orchestrator on the deterministic planner (what the hosted demo runs).
"""

import json
from pathlib import Path

import pytest

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.agents.orchestrator import Orchestrator
from app.agents.tools import ToolContext
from app.api import cash as cash_api
from app.contracts import Role
from app.llm import LLMGateway, deterministic
from app.settings import LLMMode
from tests.agents.helpers import NOW, seeded_store

LOCALES = Path(__file__).resolve().parents[3] / "web" / "src" / "i18n" / "locales"
ASKING_ROLES = {"owner": Role.owner, "accountant": Role.accountant, "staff": Role.staff}


def suggestions(language: str) -> list[tuple[str, str, str]]:
    """(role, n, question) for every suggested question in one locale file."""
    found = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
    return [(role, n, text) for role, items in found["copilot"]["suggest"].items()
            for n, text in items.items()]


ALL = [(lang, *row) for lang in ("en", "bn", "zh") for row in suggestions(lang)]


def test_every_asking_role_has_suggestions_and_only_asking_roles_do():
    assert {role for role, _, _ in suggestions("en")} == set(ASKING_ROLES)


@pytest.mark.parametrize(("language", "role", "n", "question"), ALL,
                         ids=[f"{lang}-{role}-{n}" for lang, role, n, _ in ALL])
def test_suggestion_plans_to_an_intent_with_tools(language, role, n, question):
    plan = deterministic.plan(question)
    assert plan["intents"][0] in deterministic.INTENT_TOOLS, plan
    assert plan["tools"]
    assert plan["language"] == language


@pytest.fixture(scope="module")
def grocery(universe):
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()
    engine, session, store = seeded_store(universe, ("sme_grocery",))
    yield store
    session.close()
    engine.dispose()
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()


EN = suggestions("en")


@pytest.mark.parametrize(("role", "n", "question"), EN, ids=[f"{r}-{n}" for r, n, _ in EN])
def test_english_suggestion_is_answered_for_its_role(settings, grocery, role, n, question):
    gateway = LLMGateway(settings.model_copy(update={"llm_mode": LLMMode.deterministic}))
    rec = Orchestrator(gateway).ask(ToolContext(grocery, "sme_grocery", NOW), question,
                                    role=ASKING_ROLES[role]).recommendation
    assert rec.abstention is None, rec.abstention
    assert rec.claims and rec.answer_text
