"""Bangladesh festival calendar for the cash forecaster (WP-04).

Festival dates live in `data/public/calendar/bd_festivals.yaml` (Eid dates are +/- 1 day).
`load_festivals` is the only function here that reads a file; engines take the festivals as an
argument so they stay pure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
FESTIVAL_FILE = REPO_ROOT / "data" / "public" / "calendar" / "bd_festivals.yaml"
RUN_UP_DAYS = 10  # shops sell more in the ten days before Eid
AFTER_DAYS = 3  # and close or slow down for a few days after


@dataclass(frozen=True)
class Festival:
    name: str
    day: date


def load_festivals(path: Path = FESTIVAL_FILE) -> tuple[Festival, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for row in data["festivals"]:
        raw = row["date"]
        out.append(Festival(str(row["name"]),
                            raw if isinstance(raw, date) else date.fromisoformat(str(raw))))
    return tuple(sorted(out, key=lambda f: f.day))


def festival_offsets(day: date, festivals: Sequence[Festival]) -> list[tuple[str, int]]:
    """(festival name, days from the festival) for every festival window containing `day`."""
    found = []
    for festival in festivals:
        offset = (day - festival.day).days
        if -RUN_UP_DAYS <= offset <= AFTER_DAYS:
            found.append((festival.name, offset))
    return found
