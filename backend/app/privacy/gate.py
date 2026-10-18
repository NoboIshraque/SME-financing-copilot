"""Fail-closed privacy gate (WP-03 milestone 4).

`assert_safe(payload)` raises `PrivacyViolation` if any detector fires on the serialised
payload. The LLM gateway (WP-10) must call it on every request, after `anonymise()`.
The exception names only the kinds of data found and how many, never the values, so logs and
error messages cannot leak what they are protecting.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from typing import Any

from app.privacy.detectors import Kind, detect


class PrivacyViolation(ValueError):
    def __init__(self, counts: Counter[Kind]) -> None:
        self.kinds = tuple(sorted(counts, key=lambda k: k.value))
        summary = ", ".join(f"{k.value} x{counts[k]}" for k in self.kinds)
        super().__init__(f"payload blocked: contains {summary}")


def serialise(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def assert_safe(payload: Any, *, party_names: Iterable[str] = (),
                shop_names: Iterable[str] = ()) -> None:
    found = detect(serialise(payload), party_names=party_names, shop_names=shop_names)
    if found:
        raise PrivacyViolation(Counter(d.kind for d in found))


def is_safe(payload: Any, **kwargs: Iterable[str]) -> bool:
    try:
        assert_safe(payload, **kwargs)
    except PrivacyViolation:
        return False
    return True
