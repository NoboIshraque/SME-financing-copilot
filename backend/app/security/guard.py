"""Prompt-injection guard (WP-11 milestone 5; FEATURES P5).

Runs on every user message, uploaded text and tool output before any language model sees it:

    verdict = screen(db, tenant_id, actor, text, Source.user_message, now)
    if not verdict.allowed: ...           # quarantined and audited; do not send to the LLM

Two layers. The rules layer (`guard_rules`, EN/BN/Banglish/ZH) runs first. A classifier from
WP-17 (`InjectionClassifier`) runs second when one is installed; until then the guard is
rules-only and says so (`classifier_score` is None). A hit is quarantined (kept server-side
for the owner to review or release) and logged to the audit chain with the rule ids and the
text's SHA-256, never the text.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.security.audit import AuditLog
from app.security.guard_rules import RULES, SQUASHED
from app.security.models import QuarantineRow

MAX_TEXT = 20_000  # characters inspected; longer text is refused outright


class Source(StrEnum):
    user_message = "user_message"
    uploaded_text = "uploaded_text"
    tool_output = "tool_output"


class InjectionClassifier(Protocol):
    """WP-17's model behind a two-member interface: probability of injection, and the
    decision threshold chosen on held-out families (never on the test split)."""

    name: str
    threshold: float

    def score(self, text: str) -> float: ...


_INVISIBLE = dict.fromkeys(
    [*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), 0xFEFF, 0x00AD],
    None)
_LOOKALIKES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s",
    "ј": "j", "ԁ": "d", "ɡ": "g", "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v",
    "τ": "t", "ρ": "p", "0": "0",
})
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_SPACES = re.compile(r"\s+")
_NON_LETTERS = re.compile(r"[\W\d_]+")


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).casefold()
    folded = folded.translate(_LOOKALIKES).translate(_BANGLA_DIGITS)
    return _SPACES.sub(" ", folded).strip()


def squash(normalised: str) -> str:
    return _NON_LETTERS.sub("", normalised)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    source: Source
    rule_ids: tuple[str, ...]
    families: tuple[str, ...]
    classifier: str | None
    classifier_score: float | None
    text_sha256: str
    quarantine_id: str | None = None


class InjectionGuard:
    def __init__(self, classifier: InjectionClassifier | None = None) -> None:
        self.classifier = classifier

    def inspect(self, text: str, source: Source) -> Verdict:
        digest = hashlib.sha256(text.encode()).hexdigest()
        if len(text) > MAX_TEXT:
            return Verdict(False, source, ("size.too_long",), ("oversized",), None, None, digest)
        normalised = normalise(text)
        squashed = squash(normalised)
        hits = [rule for rule in RULES if rule.pattern.search(normalised)]
        rule_ids = [rule.id for rule in hits]
        families = {rule.family for rule in hits}
        for rule_id, phrase in SQUASHED:
            if phrase in squashed:
                rule_ids.append(rule_id)
                families.add(rule_id.split(".", 1)[0])
        score = None
        name = None
        if self.classifier is not None:
            name = self.classifier.name
            score = float(self.classifier.score(text))
            if score >= self.classifier.threshold:
                rule_ids.append(f"classifier.{name}")
                families.add("classifier")
        return Verdict(not rule_ids, source, tuple(sorted(rule_ids)), tuple(sorted(families)),
                       name, score, digest)


_default_guard = InjectionGuard()


def set_classifier(classifier: InjectionClassifier | None) -> InjectionClassifier | None:
    """Install WP-17's classifier for every screen() call. Returns the previous one."""
    previous = _default_guard.classifier
    _default_guard.classifier = classifier
    return previous


def screen(db: Session, tenant_id: str, actor: str, text: str, source: Source, now: datetime,
           guard: InjectionGuard | None = None) -> Verdict:
    verdict = (guard or _default_guard).inspect(text, source)
    if verdict.allowed:
        return verdict
    row = QuarantineRow(id="q-" + secrets.token_hex(8), tenant_id=tenant_id, source=source.value,
                        actor=actor, text=text[:MAX_TEXT], text_sha256=verdict.text_sha256,
                        rule_ids=json.dumps(verdict.rule_ids), score=verdict.classifier_score,
                        created_at=now)
    db.add(row)
    db.flush()
    AuditLog(db).append(tenant_id, actor=actor, action="guard.quarantined", now=now,
                        target=row.id, details={
                            "source": source.value, "rule_ids": list(verdict.rule_ids),
                            "families": list(verdict.families),
                            "classifier_score": verdict.classifier_score,
                            "text_sha256": verdict.text_sha256})
    return Verdict(False, verdict.source, verdict.rule_ids, verdict.families, verdict.classifier,
                   verdict.classifier_score, verdict.text_sha256, quarantine_id=row.id)


def quarantined(db: Session, tenant_id: str, *, include_released: bool = False
                ) -> list[QuarantineRow]:
    query = select(QuarantineRow).where(QuarantineRow.tenant_id == tenant_id)
    if not include_released:
        query = query.where(QuarantineRow.released_at.is_(None))
    return list(db.scalars(query.order_by(QuarantineRow.created_at.desc())))


def release(db: Session, tenant_id: str, quarantine_id: str, by: str, now: datetime
            ) -> QuarantineRow | None:
    """The owner marks a quarantined text as a false positive. The release is audited."""
    row = db.get(QuarantineRow, quarantine_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    if row.released_at is None:
        row.released_at, row.released_by = now, by
        db.flush()
        AuditLog(db).append(tenant_id, actor=by, action="guard.released", now=now,
                            target=row.id, details={"text_sha256": row.text_sha256})
    return row


class OnnxInjectionClassifier:
    """WP-17's exported model (notebook 03: ONNX int8 + tokenizer.json + hishab_threshold.json).

    Needs `onnxruntime` and `tokenizers`, which are not in the default install (they are
    large); `load_classifier` returns None without them and the guard stays rules-only.
    """

    def __init__(self, model_dir: Path, onnxruntime: Any, tokenizers: Any) -> None:
        self.name = "wp17_onnx"
        meta = json.loads((model_dir / "hishab_threshold.json").read_text(encoding="utf-8"))
        self.threshold = float(meta["threshold"])
        self._tokenizer = tokenizers.Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=128)
        self._session = onnxruntime.InferenceSession(str(model_dir / "model.onnx"),
                                                     providers=["CPUExecutionProvider"])

    def score(self, text: str) -> float:
        import numpy as np

        encoding = self._tokenizer.encode(text)
        feeds = {"input_ids": np.array([encoding.ids], dtype=np.int64),
                 "attention_mask": np.array([encoding.attention_mask], dtype=np.int64)}
        logits = self._session.run(None, feeds)[0][0]
        exp = np.exp(logits - logits.max())
        return float(exp[1] / exp.sum())


def load_classifier(model_dir: str | None) -> InjectionClassifier | None:
    """The WP-17 classifier if its files and runtime are present, else None (rules only)."""
    if not model_dir or not (Path(model_dir) / "model.onnx").exists():
        return None
    try:
        import onnxruntime
        import tokenizers
    except ImportError:
        return None
    return OnnxInjectionClassifier(Path(model_dir), onnxruntime, tokenizers)
