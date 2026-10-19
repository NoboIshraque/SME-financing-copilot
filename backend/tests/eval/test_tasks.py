import json

from eval.scoring import DEEP
from eval.tasks import CORPUS, FUNCTIONAL, adversarial, all_tasks


def corpus_rows():
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines()]


def test_adversarial_suite_is_exactly_the_held_out_attacks():
    rows = corpus_rows()
    held_out = {r["id"] for r in rows if r["split"] == "test" and r["label"] == "attack"}
    tasks = adversarial()
    used = {t.tags["corpus_id"] for t in tasks}
    assert used == held_out
    train = {r["id"] for r in rows if r["split"] == "train"}
    assert not used & train  # the guard may have been tuned on train: never score on it
    assert {t.tags["lang"] for t in tasks} == {"en", "bn", "bl", "zh"}
    assert {t.tags["paraphrase"] for t in tasks} == {"0", "1"}
    texts = {r["id"]: r["text"] for r in rows}
    assert all(t.question == texts[t.tags["corpus_id"]] for t in tasks)
    assert all(t.expect.calls == () and "quarantined" in t.expect.deep for t in tasks)


def test_functional_tasks_cover_every_main_feature_with_known_checks():
    ids = [t.id for t in all_tasks()]
    assert len(ids) == len(set(ids))
    features = {t.feature for t in FUNCTIONAL}
    # cash gap, financing match, analysis, what-if, mesh netting, multi-agent, abstention,
    # tool budget, permission tiers, anonymisation
    assert {"Q3", "Q1", "P1", "C", "N12", "N14", "N8", "N17", "P13", "P2", "N18"} <= features
    assert {n for t in FUNCTIONAL for n in t.expect.deep} <= set(DEEP)
    abstaining = [t for t in FUNCTIONAL if t.expect.abstain is not None]
    assert abstaining and all(t.expect.calls is not None for t in abstaining)
