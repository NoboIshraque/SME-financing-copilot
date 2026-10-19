"""Response cache keyed by the hash of the anonymised prompt (WP-10 milestone 1; PLAN §6).

The key is `<provider model id>:<prompt hash>`: the same anonymised prompt sent to the same
model returns the stored answer without spending free-tier quota. Different models never
share an entry, so two voters cannot "agree" through the cache. Prompts are anonymised before
hashing (labels such as "Customer 1", relative dates), so an entry holds nothing that was not
already allowed to leave the server, and labels are restored per caller afterwards.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class CachedAnswer:
    text: str
    stored_at: datetime
    tokens_in: int = 0
    tokens_out: int = 0


def cache_key(model_id: str, prompt_hash: str) -> str:
    return f"{model_id}:{prompt_hash}"


class ResponseCache(Protocol):
    def get(self, key: str, now: datetime) -> CachedAnswer | None: ...

    def put(self, key: str, answer: CachedAnswer) -> None: ...


class MemoryCache:
    """Least-recently-used, with a time-to-live: market prices and balances change daily."""

    def __init__(self, max_entries: int = 2048, ttl: timedelta = timedelta(hours=12)) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self.ttl = ttl
        self._entries: OrderedDict[str, CachedAnswer] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, now: datetime) -> CachedAnswer | None:
        with self._lock:
            answer = self._entries.get(key)
            if answer is None:
                return None
            if now - answer.stored_at >= self.ttl:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return answer

    def put(self, key: str, answer: CachedAnswer) -> None:
        with self._lock:
            self._entries[key] = answer
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
