"""`npm run eval` end to end, offline: the logs are deliverable 06, so their shape is tested."""

import json

import pytest

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.api import cash as cash_api
from eval import run as cli

TASKS = ("F.mesh.netting", "F.abstain.off_topic", "A.change_bank_details.zh.1",
         "A.role_play_jailbreak.bl.0")


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()
    out = tmp_path_factory.mktemp("eval")
    argv = ["--out", str(out)] + [arg for task in TASKS for arg in ("--only", task)]
    assert cli.main(argv) == 0
    return out


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_each_task_log_runs_from_input_through_steps_to_score(out):
    logs = sorted(p.stem for p in (out / "tasks").glob("*.jsonl"))
    assert logs == sorted(TASKS)
    for task in TASKS:
        events = lines(out / "tasks" / f"{task}.jsonl")
        assert [e["seq"] for e in events] == list(range(len(events)))
        assert events[0]["event"] == "task" and events[0]["data_mode"] == "synthetic"
        assert events[0]["mode"] == "offline"
        assert events[1] == {**events[1], "event": "step", "step": "guard"}
        assert events[-2]["event"] in ("answer", "abstain")
        assert events[-1]["event"] == "score" and events[-1]["passed"] is True
    netting = lines(out / "tasks" / "F.mesh.netting.jsonl")
    tool = next(e for e in netting if e["event"] == "step" and e["step"] == "tool")
    assert tool["name"] == "mesh.propose" and tool["figures"]
    assert all(f["formula"] and isinstance(f["value"], str) for f in tool["figures"])
    attack = lines(out / "tasks" / "A.change_bank_details.zh.1.jsonl")
    assert [e["event"] for e in attack] == ["task", "step", "abstain", "score"]


def test_summary_agrees_with_the_per_task_results(out):
    results = lines(out / "results.jsonl")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert [r["task"] for r in results] == list(TASKS)
    assert summary["tasks"] == {"total": 4, "passed": sum(r["passed"] for r in results),
                                "rate": "1.000"}
    assert summary["functional"]["total"] == 2 and summary["adversarial"]["total"] == 2
    assert summary["attacks_caught"]["by_language"] == {
        "bl": {"total": 1, "passed": 1, "rate": "1.000"},
        "zh": {"total": 1, "passed": 1, "rate": "1.000"}}
    assert summary["abstention"]["should_abstain"] == 1
    assert summary["abstention"]["with_the_right_reason"] == 1
    assert summary["models"]["mode"] == "fixtures"


def test_unknown_task_ids_are_refused_before_anything_runs():
    with pytest.raises(SystemExit, match="F.nope"):
        cli.main(["--only", "F.nope"])
