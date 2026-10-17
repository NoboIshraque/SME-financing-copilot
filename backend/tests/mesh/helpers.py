from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.contracts import DataMode, MeshObligation, Money, ObligationStatus

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def ob(oid: str, debtor: str, creditor: str, amount, *, status=ObligationStatus.open,
       due_days: int = 10) -> MeshObligation:
    return MeshObligation(
        id=oid,
        debtor_tenant=debtor,
        creditor_tenant=creditor,
        amount=Money.of(Decimal(str(amount))),
        due_date=(NOW + timedelta(days=due_days)).date(),
        status=status,
        data_mode=DataMode.synthetic,
    )


def ring(*edges) -> list[MeshObligation]:
    """edges: (debtor, creditor, amount) triples -> obligations with ids o1, o2, ..."""
    return [ob(f"o{i}", d, c, a) for i, (d, c, a) in enumerate(edges, start=1)]
