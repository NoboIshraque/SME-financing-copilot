"""Settlement record, receipts and tamper-evident sealing (WP-08 milestones 4 and 6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.chain.anchor import Anchorer
from app.chain.digest import canonical, commit
from app.contracts import (
    MeshObligation,
    Money,
    NettingRound,
    ObligationStatus,
    RoundStatus,
)

ROUND_KIND = "netting_round"
# Fields that are not part of the sealed record: the anchor is added after sealing.
_UNSEALED = {"anchor"}


class SettlementError(ValueError):
    pass


@dataclass(frozen=True)
class Receipt:
    """What one participant sees after a round settles."""

    round_id: str
    tenant: str
    pays: tuple[tuple[str, Money], ...]
    receives: tuple[tuple[str, Money], ...]
    obligations_discharged: tuple[str, ...]
    debts_cleared: Money  # gross debts of this tenant that the round discharged
    cash_out: Money  # what the tenant actually pays

    @property
    def cash_saved(self) -> Money:
        return self.debts_cleared - self.cash_out


def round_digest(round_: NettingRound, salt: str) -> str:
    return commit(ROUND_KIND, salt, canonical(round_, exclude=_UNSEALED))


def settle(
    round_: NettingRound,
    obligations: dict[str, MeshObligation],
    *,
    now: datetime,
) -> tuple[NettingRound, tuple[MeshObligation, ...], tuple[Receipt, ...]]:
    """Mark an approved round settled, discharge its obligations and issue receipts."""
    if round_.status is not RoundStatus.approved:
        raise SettlementError(f"round {round_.id} is {round_.status.value}; it must be approved")
    if now >= round_.expires_at:
        raise SettlementError(f"round {round_.id} expired before settlement")
    missing = [oid for oid in round_.obligation_ids if oid not in obligations]
    if missing:
        raise SettlementError(f"unknown obligations: {missing}")
    for oid in round_.obligation_ids:
        if obligations[oid].status is not ObligationStatus.open:
            raise SettlementError(f"obligation {oid} is no longer open")

    settled = round_.model_copy(update={"status": RoundStatus.settled})
    discharged = tuple(
        obligations[oid].model_copy(update={"status": ObligationStatus.settled})
        for oid in round_.obligation_ids
    )
    receipts = []
    for tenant in round_.participants:
        pays = tuple((s.payee_tenant, s.amount) for s in round_.settlements
                     if s.payer_tenant == tenant)
        receives = tuple((s.payer_tenant, s.amount) for s in round_.settlements
                         if s.payee_tenant == tenant)
        own = tuple(o.id for o in discharged if tenant in (o.debtor_tenant, o.creditor_tenant))
        cleared = sum((o.amount for o in discharged if o.debtor_tenant == tenant), Money.zero())
        cash_out = sum((amount for _, amount in pays), Money.zero())
        receipts.append(Receipt(round_.id, tenant, pays, receives, own, cleared, cash_out))
    return settled, discharged, tuple(receipts)


def seal_and_anchor(
    round_: NettingRound, salt: str, anchorer: Anchorer, *, now: datetime
) -> NettingRound:
    """Anchor the digest of a settled round and attach the receipt."""
    if round_.status is not RoundStatus.settled:
        raise SettlementError("only settled rounds are anchored")
    receipt = anchorer.anchor(round_digest(round_, salt), now)
    return round_.model_copy(update={"anchor": receipt})


@dataclass(frozen=True)
class Verification:
    valid: bool
    recomputed: str
    anchored: str | None
    reason: str


def verify(round_: NettingRound, salt: str, anchorer: Anchorer) -> Verification:
    """Recompute the digest from the record and compare it with what is on chain."""
    recomputed = round_digest(round_, salt)
    if round_.anchor is None:
        return Verification(False, recomputed, None, "round has not been anchored")
    onchain = anchorer.onchain_digest(round_.anchor)
    if onchain is None:
        return Verification(False, recomputed, None, "anchor not found on chain")
    if onchain != round_.anchor.digest:
        return Verification(False, recomputed, onchain, "receipt digest differs from chain")
    if recomputed != onchain:
        return Verification(False, recomputed, onchain, "record was changed after anchoring")
    return Verification(True, recomputed, onchain, "record matches the anchored digest")
