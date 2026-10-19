"""The database side of the mesh (WP-08 milestone 8): obligations and netting rounds.

Not engine code: the API uses it; the engine modules never import it.

- Obligations are stored once both parties have opted in. Until an opt-in flow exists, the only
  obligations are the synthetic demo ring, seeded on first use (`ensure_demo_ring`) and labelled
  `synthetic` like everything else in the universe.
- Rounds are stored with their salt, which never leaves this module's callers on the server.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import MeshObligation, NettingRound, ObligationStatus, RoundStatus
from app.engines.mesh.consent import expire_if_due
from app.engines.mesh.models import MeshObligationRow, NettingRoundRow


@dataclass(frozen=True)
class StoredRound:
    round: NettingRound
    salt: str


class MeshStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ----------------------------------------------------------------- obligations

    def obligations(self) -> list[MeshObligation]:
        rows = self.session.scalars(select(MeshObligationRow).order_by(MeshObligationRow.id))
        return [MeshObligation.model_validate_json(row.payload) for row in rows]

    def put_obligations(self, obligations: Iterable[MeshObligation]) -> None:
        for obligation in obligations:
            row = self.session.get(MeshObligationRow, obligation.id)
            if row is None:
                row = MeshObligationRow(id=obligation.id)
                self.session.add(row)
            row.debtor_tenant = obligation.debtor_tenant
            row.creditor_tenant = obligation.creditor_tenant
            row.status = obligation.status.value
            row.payload = obligation.model_dump_json()
        self.session.flush()

    def ensure_demo_ring(self) -> None:
        """Seed the synthetic universe's debt ring once (idempotent)."""
        if self.session.scalar(select(MeshObligationRow.id).limit(1)) is not None:
            return
        from app.synthetic import load_universe

        self.put_obligations(load_universe().mesh_obligations)

    def mark(self, obligation_ids: Iterable[str], status: ObligationStatus) -> None:
        current = {o.id: o for o in self.obligations()}
        self.put_obligations(current[oid].model_copy(update={"status": status})
                             for oid in obligation_ids)

    # ----------------------------------------------------------------- rounds

    def save_round(self, round_: NettingRound, salt: str | None = None) -> None:
        row = self.session.get(NettingRoundRow, round_.id)
        if row is None:
            if salt is None:
                raise ValueError(f"a new round needs its salt: {round_.id}")
            row = NettingRoundRow(id=round_.id, salt=salt, created_at=round_.created_at)
            self.session.add(row)
        row.status = round_.status.value
        row.participants = " ".join(round_.participants)
        row.payload = round_.model_dump_json()
        self.session.flush()

    def get_round(self, round_id: str, now: datetime) -> StoredRound | None:
        row = self.session.get(NettingRoundRow, round_id)
        if row is None:
            return None
        return StoredRound(self._expired(row, now), row.salt)

    def rounds_for(self, tenant: str, now: datetime) -> list[NettingRound]:
        rows = self.session.scalars(select(NettingRoundRow)
                                    .order_by(NettingRoundRow.created_at.desc(),
                                              NettingRoundRow.id))
        return [self._expired(row, now) for row in rows if tenant in row.participants.split()]

    def open_round_with(self, obligation_ids: Iterable[str], now: datetime) -> NettingRound | None:
        """A proposed (or approved, not yet settled) round already covering any of these."""
        wanted = set(obligation_ids)
        live = (RoundStatus.proposed, RoundStatus.approved)
        for row in self.session.scalars(select(NettingRoundRow)
                                        .where(NettingRoundRow.status.in_([s.value for s in live]))
                                        .order_by(NettingRoundRow.created_at, NettingRoundRow.id)):
            round_ = self._expired(row, now)
            if round_.status in live and wanted & set(round_.obligation_ids):
                return round_
        return None

    def _expired(self, row: NettingRoundRow, now: datetime) -> NettingRound:
        round_ = NettingRound.model_validate_json(row.payload)
        expired = expire_if_due(round_, now)
        if expired is not round_:
            self.save_round(expired)
        return expired
