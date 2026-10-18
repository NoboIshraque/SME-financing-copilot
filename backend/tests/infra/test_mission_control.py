import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "mission_control.py"
spec = importlib.util.spec_from_file_location("mission_control", SCRIPT)
mc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mc
spec.loader.exec_module(mc)

NOW = (REPO / "docs/NOW.md").read_text(encoding="utf-8")
TEAM = mc.load_team((REPO / ".github/team.yml").read_text(encoding="utf-8"))


def test_now_has_one_section_per_team_member():
    assert set(mc.split_sections(NOW)) == set(TEAM) == {"nobo", "amdad", "labib"}


def test_every_section_names_its_owner_with_their_github_handle():
    for key, text in mc.split_sections(NOW).items():
        assert f"@{TEAM[key]}" in text.splitlines()[0]


def test_status_board_is_extracted_from_the_plan():
    board = mc.status_board((REPO / "docs/PLAN.md").read_text(encoding="utf-8"))
    assert board.startswith("| WP |") and "| WP-00 |" in board


def test_state_marker_round_trips_through_the_body():
    sections = mc.split_sections(NOW)
    state = {k: mc.digest(v) for k, v in sections.items()}
    body = mc.build_body("o/r", NOW, "", TEAM, [], "ok", "ok", "up", sections, state)
    parsed = mc.json.loads(mc.STATE_RE.search(body).group(1))
    assert parsed == state


def test_only_the_changed_section_gets_a_new_digest():
    sections = mc.split_sections(NOW)
    edited = {**sections, "amdad": sections["amdad"] + "\n- [ ] new task"}
    before = {k: mc.digest(v) for k, v in sections.items()}
    after = {k: mc.digest(v) for k, v in edited.items()}
    assert [k for k in after if after[k] != before[k]] == ["amdad"]
