"""Public price points for market watch (WP-09).

`MarketPrice` is the `PricePoint` contract with one difference: its `source` may also be "wfp"
(WFP's Bangladesh market monitoring), which the contract's `PriceSource` does not list yet.
The JSON shape is the same; a contract change is requested in WP-09.md (Questions).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Literal

from app.contracts import PricePoint

PUBLIC_SOURCES = ("tcb", "wfp", "nbs", "xinfadi")


class MarketPrice(PricePoint):
    source: Literal["tcb", "wfp", "nbs", "xinfadi"]  # type: ignore[assignment]


def digest(value: object, parameters: Mapping[str, str], refs: Iterable[str] = ()) -> str:
    """A short content hash for figure ids: the same id always means the same figure, so a
    figure recorded earlier with other inputs (a new price list, a new rule) never collides."""
    payload = json.dumps([str(value), dict(sorted(parameters.items())), sorted(refs)])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
