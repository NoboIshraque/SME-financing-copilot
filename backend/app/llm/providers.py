"""Model providers, roles and fallback chains (WP-10 milestone 1; PLAN §6).

Every provider speaks the OpenAI chat-completions API, so one client serves all of them and
only the base URL, key and model id change. Each provider is a *slot*: a model on an endpoint,
with its own free-tier limits. Model families matter: the critic (N11) and the voters (N9)
must not share a family with the brain that wrote the answer.

    brain   Gemini Flash                                  -> deterministic planner
    voter   gpt-oss-120b, Qwen; fallback gpt-oss-20b, Gemma -> deterministic
    critic  same pool as the voters, minus the brain's family
    private Ollama on our own machine (nothing leaves it)  -> deterministic

The deterministic planner is the last link of every chain and never fails for the tasks it
knows (plan, vote, critique, narrate): the app works with no model at all.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from app.settings import LLMMode, Settings


class Role(StrEnum):
    brain = "brain"  # planning, tool choice, explanations, drafts
    voter = "voter"  # agreement on judgements (N9)
    critic = "critic"  # case against (N11)


class KeyName(StrEnum):
    gemini = "gemini_api_key"
    groq = "groq_api_key"
    none = ""  # local providers need no key


@dataclass(frozen=True)
class Provider:
    slot: str  # stable id used in fixtures, usage counters and votes, e.g. "groq_qwen"
    model: str
    family: str  # who trained it: google | openai | alibaba | rules
    base_url: str
    key: KeyName
    rpm: int  # requests per minute we allow ourselves (at or below the free tier)
    rpd: int  # requests per rolling 24 hours
    local: bool = False  # True: the request never leaves our machine

    @property
    def model_id(self) -> str:
        """Provider-qualified id, as recorded in votes: 'groq_qwen:qwen/qwen3-32b'."""
        return f"{self.slot}:{self.model}"

    @property
    def deterministic(self) -> bool:
        return self.slot == DETERMINISTIC.slot


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_URL = "https://api.groq.com/openai/v1"

# Limits are deliberately at or under the published free tiers (confirm in each console);
# the gateway stops calling a slot before the provider starts refusing.
GEMINI_FLASH = Provider("gemini_flash", "gemini-2.5-flash", "google", GEMINI_URL,
                        KeyName.gemini, rpm=10, rpd=250)
GROQ_GPT_OSS_120B = Provider("groq_gpt_oss_120b", "openai/gpt-oss-120b", "openai", GROQ_URL,
                             KeyName.groq, rpm=30, rpd=1000)
GROQ_QWEN = Provider("groq_qwen", "qwen/qwen3-32b", "alibaba", GROQ_URL,
                     KeyName.groq, rpm=30, rpd=1000)
GROQ_GPT_OSS_20B = Provider("groq_gpt_oss_20b", "openai/gpt-oss-20b", "openai", GROQ_URL,
                            KeyName.groq, rpm=30, rpd=1000)
GEMMA = Provider("gemma", "gemma-3-27b-it", "google", GEMINI_URL,
                 KeyName.gemini, rpm=30, rpd=14000)
OLLAMA_QWEN = Provider("ollama_qwen", "qwen2.5:3b", "alibaba", "http://localhost:11434/v1",
                       KeyName.none, rpm=60, rpd=100_000, local=True)
DETERMINISTIC = Provider("deterministic", "rules-v1", "rules", "", KeyName.none,
                         rpm=1_000_000, rpd=1_000_000_000, local=True)

PROVIDERS: dict[str, Provider] = {p.slot: p for p in (
    GEMINI_FLASH, GROQ_GPT_OSS_120B, GROQ_QWEN, GROQ_GPT_OSS_20B, GEMMA, OLLAMA_QWEN,
    DETERMINISTIC)}

# Order is the fallback order. Voters are drawn from the front of the voter pool, one per
# family where possible (see `voter_slots`).
CHAINS: dict[Role, tuple[str, ...]] = {
    Role.brain: ("gemini_flash",),
    Role.voter: ("groq_gpt_oss_120b", "groq_qwen", "groq_gpt_oss_20b", "gemma"),
    Role.critic: ("groq_qwen", "groq_gpt_oss_120b", "groq_gpt_oss_20b", "gemma"),
}
PRIVATE_CHAIN = ("ollama_qwen",)


def configured(settings: Settings, models: dict[str, str] | None = None) -> dict[str, Provider]:
    """The provider table for this deployment: Ollama's URL from settings, and optional model
    overrides by slot (e.g. when a provider renames a model; see `live_check --model`)."""
    table = dict(PROVIDERS)
    table["ollama_qwen"] = replace(table["ollama_qwen"], base_url=settings.ollama_base_url)
    for slot, model in (models or {}).items():
        if slot not in table or table[slot].deterministic:
            raise ValueError(f"unknown model slot: {slot}")
        table[slot] = replace(table[slot], model=model)
    return table


def chain(role: Role, mode: LLMMode, *, private: bool = False,
          exclude_families: Iterable[str] = (),
          table: dict[str, Provider] = PROVIDERS) -> tuple[Provider, ...]:
    """Providers to try, in order, ending with the deterministic planner.

    `deterministic` mode skips every model. Private mode uses only the local model.
    `exclude_families` removes providers of those families (a critic must not be the brain's
    family); if that empties the model list, only the deterministic planner remains.
    """
    excluded = set(exclude_families)
    if mode is LLMMode.deterministic:
        slots: tuple[str, ...] = ()
    elif private:
        slots = PRIVATE_CHAIN
    else:
        slots = CHAINS[role]
    models = tuple(table[s] for s in slots if table[s].family not in excluded)
    return (*models, table[DETERMINISTIC.slot])
