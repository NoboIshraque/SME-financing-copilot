"""Tool budget per run (WP-10 milestone 3; FEATURES P13).

A run may call at most `max_tool_calls` engine tools and `max_llm_calls` models, and spend at
most `max_tokens` model tokens (the cost cap: free tiers count tokens). When the tool budget
runs out the remaining tools are not run, which ends in an abstention naming them; when the
model budget runs out the deterministic planner answers instead. Thread-safe: sub-agents
share one budget.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Budget:
    max_tool_calls: int = 8
    max_llm_calls: int = 12
    max_tokens: int = 60_000
    tool_calls: int = 0
    llm_calls: int = 0
    tokens: int = 0
    refused: list[str] = field(default_factory=list)  # what was not run, in order
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def take_tool(self, name: str) -> bool:
        with self._lock:
            if self.tool_calls >= self.max_tool_calls:
                self.refused.append(name)
                return False
            self.tool_calls += 1
            return True

    def take_llm(self, what: str) -> bool:
        with self._lock:
            if self.llm_calls >= self.max_llm_calls or self.tokens >= self.max_tokens:
                self.refused.append(f"llm:{what}")
                return False
            self.llm_calls += 1
            return True

    def spend_tokens(self, tokens: int) -> None:
        with self._lock:
            self.tokens += tokens

    @property
    def tools_exhausted(self) -> bool:
        return any(not r.startswith("llm:") for r in self.refused)

    def report(self) -> dict[str, object]:
        with self._lock:
            return {"tool_calls": self.tool_calls, "max_tool_calls": self.max_tool_calls,
                    "llm_calls": self.llm_calls, "max_llm_calls": self.max_llm_calls,
                    "tokens": self.tokens, "max_tokens": self.max_tokens,
                    "refused": list(self.refused)}
