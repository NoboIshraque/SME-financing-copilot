"""Every committed LLM fixture is safe to publish and still matches a prompt we send."""

import json
import re
from pathlib import Path

import pytest

from app.llm.gateway import parse_json_object
from app.llm.messages import Message
from app.llm.providers import PROVIDERS
from app.llm.transport import FIXTURES_DIR
from app.privacy import is_safe
from tests.fixtures.llm.author import authored

FILES = sorted(p for p in FIXTURES_DIR.glob("*/*.json"))


def test_there_are_fixtures_to_replay():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_fixture_is_consistent_and_anonymised(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["slot"] == path.parent.name and record["slot"] in PROVIDERS
    assert re.fullmatch(r"[0-9a-f]{64}", record["prompt_hash"])
    assert path.stem == record["prompt_hash"][:16]
    assert record["source"] in ("live", "authored")
    messages = [Message(m["role"], m["content"]) for m in record["messages"]]
    assert is_safe([m.as_dict() for m in messages])
    assert is_safe(record["response"]["text"])
    assert parse_json_object(record["response"]["text"]) is not None


def test_authored_fixtures_match_the_current_prompts():
    """Fails when a prompt changed and `tests/fixtures/llm/author.py` was not re-run."""
    for slot, request, answer in authored():
        path = FIXTURES_DIR / slot / f"{request.prompt_hash()[:16]}.json"
        assert path.is_file(), f"stale authored fixture for {slot}: re-run author.py"
        record = json.loads(path.read_text(encoding="utf-8"))
        assert json.loads(record["response"]["text"]) == answer
