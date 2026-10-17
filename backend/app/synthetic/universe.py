"""Load the synthetic SME universe as typed contracts (owned by WP-00).

A dev/test convenience so every engine can run on realistic data without waiting for ingest
(WP-02). Counterparties get deterministic placeholder tokens `PARTY_<10 hex>`; the real token
vault (WP-03) replaces these in the product path.

    from app.synthetic import load_universe
    uni = load_universe()
    grocery = uni.smes["sme_grocery"]
    grocery.transactions, grocery.invoices, grocery.bills, grocery.obligations
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from app.contracts import (
    Bill,
    Channel,
    DataMode,
    Direction,
    DocumentStatus,
    Frequency,
    Invoice,
    MeshObligation,
    Money,
    ObligationKind,
    Party,
    PartyRole,
    RecurringObligation,
    Transaction,
    TxCategory,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UNIVERSE_DIR = REPO_ROOT / "data" / "synthetic" / "universe"
DHAKA = ZoneInfo("Asia/Dhaka")
SME_IDS = ("sme_grocery", "sme_pharmacy", "sme_fabric", "sme_garment", "sme_hardware")
SYNTHETIC = DataMode.synthetic


def party_token(tenant_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}|{name}".encode()).hexdigest()
    return f"PARTY_{digest[:10]}"


@dataclass(frozen=True)
class SME:
    id: str
    profile: dict[str, object]
    transactions: tuple[Transaction, ...]
    invoices: tuple[Invoice, ...]
    bills: tuple[Bill, ...]
    obligations: tuple[RecurringObligation, ...]
    parties: tuple[Party, ...]
    opening_balances: dict[str, Money] = field(default_factory=dict)

    @property
    def opening_total(self) -> Money:
        total = Money.zero()
        for value in self.opening_balances.values():
            total = total + value
        return total

    def balance_on(self, day: date) -> Money:
        """Total balance across all channels at the end of `day`."""
        total = self.opening_total
        for txn in self.transactions:
            if txn.day > day:
                break
            total = total + txn.signed_amount
        return total


@dataclass(frozen=True)
class Universe:
    as_of: date
    start: date
    seed: int
    smes: dict[str, SME]
    mesh_obligations: tuple[MeshObligation, ...]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _status(raw: str) -> DocumentStatus:
    return DocumentStatus(raw)


def _documents(sme_id: str, path: Path, cls: type[Invoice] | type[Bill], parties: dict) -> tuple:
    out = []
    role = PartyRole.customer if cls is Invoice else PartyRole.supplier
    for line, row in enumerate(_read(path), start=2):
        token = party_token(sme_id, row["party"])
        parties.setdefault(token, (row["party"], role))
        out.append(
            cls(
                id=f"{sme_id}:{row['number']}",
                tenant_id=sme_id,
                counterparty_token=token,
                issue_date=date.fromisoformat(row["issue_date"]),
                due_date=date.fromisoformat(row["due_date"]),
                amount=Money.of(row["amount"]),
                amount_paid=Money.of(row["amount_paid"]),
                status=_status(row["status"]),
                paid_date=date.fromisoformat(row["paid_date"]) if row["paid_date"] else None,
                source_ref=f"{path.name}#L{line}",
                data_mode=SYNTHETIC,
            )
        )
    return tuple(out)


_CATEGORY_ROLE = {
    "sales": PartyRole.customer,
    "collection": PartyRole.customer,
    "supplier_payment": PartyRole.supplier,
    "rent": PartyRole.landlord,
    "salary": PartyRole.employee,
    "loan_repayment": PartyRole.lender,
    "utility": PartyRole.utility,
    "owner_draw": PartyRole.self_,
    "transfer": PartyRole.self_,
}


def load_sme(sme_id: str, root: Path = UNIVERSE_DIR) -> SME:
    folder = root / sme_id
    profile = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    parties: dict[str, tuple[str, PartyRole]] = {}

    transactions = []
    truth = folder / "transactions_truth.csv"
    for line, row in enumerate(_read(truth), start=2):
        category = TxCategory(row["category"])
        token = party_token(sme_id, row["counterparty"])
        parties.setdefault(token, (row["counterparty"], _CATEGORY_ROLE.get(row["category"],
                                                                           PartyRole.other)))
        occurred = datetime.fromisoformat(row["occurred_at"]).replace(tzinfo=DHAKA)
        transactions.append(
            Transaction(
                id=row["id"],
                tenant_id=sme_id,
                occurred_at=occurred,
                amount=Money.of(row["amount"]),
                direction=Direction(row["direction"]),
                channel=Channel(row["channel"]),
                category=category,
                counterparty_token=token,
                reference=row["reference"] or None,
                invoice_id=f"{sme_id}:{row['reference']}" if category is TxCategory.collection
                else None,
                source_ref=f"{truth.name}#L{line}",
                data_mode=SYNTHETIC,
            )
        )

    invoices = _documents(sme_id, folder / "baki_register.csv", Invoice, parties)
    bills = _documents(sme_id, folder / "bills_register.csv", Bill, parties)

    obligations = []
    for line, row in enumerate(_read(folder / "obligations.csv"), start=2):
        token = party_token(sme_id, row["counterparty"])
        parties.setdefault(token, (row["counterparty"], PartyRole.other))
        obligations.append(
            RecurringObligation(
                id=f"{sme_id}:OBL-{line - 1}",
                tenant_id=sme_id,
                kind=ObligationKind(row["kind"]),
                counterparty_token=token,
                amount=Money.of(row["amount"]),
                frequency=Frequency(row["frequency"]),
                day_of_period=int(row["day_of_period"]),
                start_date=date.fromisoformat(row["start_date"]),
                source_ref=f"obligations.csv#L{line}",
                data_mode=SYNTHETIC,
            )
        )

    party_rows = []
    counters: dict[PartyRole, int] = {}
    for token, (_name, role) in sorted(parties.items()):
        counters[role] = counters.get(role, 0) + 1
        party_rows.append(
            Party(
                id=f"{sme_id}:{token}",
                tenant_id=sme_id,
                token=token,
                role=role,
                display_label=f"{role.value.replace('_', ' ').title()} {counters[role]}",
                is_tenant=_name in _TENANT_NAMES,
                data_mode=SYNTHETIC,
            )
        )

    opening = {k: Money.of(v) for k, v in profile["opening_balances"].items()}
    return SME(
        id=sme_id,
        profile=profile,
        transactions=tuple(transactions),
        invoices=invoices,
        bills=bills,
        obligations=tuple(obligations),
        parties=tuple(party_rows),
        opening_balances=opening,
    )


_TENANT_NAMES = {
    "Mirpur Mudi Store",
    "Dhanmondi Care Pharmacy",
    "Islampur Fabric House",
    "Ashulia Stitch Works",
    "Nawabpur Hardware Traders",
}


@lru_cache(maxsize=2)
def load_universe(root: Path = UNIVERSE_DIR) -> Universe:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    smes = {sme_id: load_sme(sme_id, root) for sme_id in SME_IDS}
    mesh = []
    for row in _read(root / "mesh_obligations.csv"):
        mesh.append(
            MeshObligation(
                id=row["ref"],
                debtor_tenant=row["debtor"],
                creditor_tenant=row["creditor"],
                amount=Money.of(row["amount"]),
                due_date=date.fromisoformat(row["due_date"]),
                invoice_ref=row["ref"],
                data_mode=SYNTHETIC,
            )
        )
    return Universe(
        as_of=date.fromisoformat(manifest["as_of"]),
        start=date.fromisoformat(manifest["start"]),
        seed=int(manifest["seed"]),
        smes=smes,
        mesh_obligations=tuple(mesh),
    )
