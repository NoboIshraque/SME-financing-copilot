"""Write the hand-authored LLM fixtures (source "authored").

    uv --directory backend run python tests/fixtures/llm/author.py

Live recordings (source "live") come from `python -m app.llm.live_check` instead. Authored
fixtures stand in for a model in the offline tests: each is a plausible answer to one prompt
built by `app.llm.prompts`, so the file name is that prompt's hash. Re-run after changing a
prompt; `tests/agents/test_fixtures.py` fails when a fixture no longer matches any prompt.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.llm.messages import LLMRequest  # noqa: E402
from app.llm.prompts import plan_request  # noqa: E402
from app.llm.providers import PROVIDERS  # noqa: E402
from app.llm.transport import Completion, FixtureStore  # noqa: E402

AUTHORED_AT = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)


def authored() -> list[tuple[str, LLMRequest, dict[str, object]]]:
    """(slot, request, answer) for every authored fixture."""
    return [
        ("gemini_flash", plan_request("Will I run out of cash next month?"),
         {"intents": ["cash_outlook"], "tools": ["cash.forecast", "cash.gaps"],
          "language": "en"}),
        ("gemini_flash", plan_request("আগামী মাসে কি লোন নেওয়া দরকার?"),
         {"intents": ["find_financing", "cash_outlook"],
          "tools": ["cash.gaps", "financing.match", "cash.forecast"], "language": "bn"}),
    ]


def main() -> None:
    store = FixtureStore(Path(__file__).resolve().parent)
    for slot, request, answer in authored():
        text = json.dumps(answer, ensure_ascii=False, sort_keys=True)
        path = store.record(PROVIDERS[slot], request, Completion(text, 0, 0),
                            source="authored", recorded_at=AUTHORED_AT)
        print(path.relative_to(BACKEND))


if __name__ == "__main__":
    main()
