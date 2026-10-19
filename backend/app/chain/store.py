"""A database-backed offline anchorer (WP-08 milestone 8).

`OfflineAnchorer` keeps anchors in memory, so a verify after a restart would fail. This one
records each digest in `chain_offline_anchors` instead. Receipts say `offline` everywhere they
appear: nothing here touches a chain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.chain.anchor import payload_for
from app.chain.models import OfflineAnchorRow
from app.contracts import AnchorChain, AnchorReceipt


class StoredOfflineAnchorer:
    def __init__(self, session: Session) -> None:
        self.session = session

    def anchor(self, digest: str, now: datetime) -> AnchorReceipt:
        payload_for(digest)
        if self.session.get(OfflineAnchorRow, digest) is None:
            self.session.add(OfflineAnchorRow(digest=digest, anchored_at=now))
            self.session.flush()
        return AnchorReceipt(chain=AnchorChain.offline, digest=digest, anchored_at=now)

    def onchain_digest(self, receipt: AnchorReceipt) -> str | None:
        if receipt.chain is not AnchorChain.offline:
            return None
        found = self.session.get(OfflineAnchorRow, receipt.digest)
        return found.digest if found is not None else None
