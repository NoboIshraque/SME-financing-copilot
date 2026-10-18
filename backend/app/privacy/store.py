"""Database-backed entries for TokenVault, so tokens survive restarts (WP-03)."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.privacy.models import VaultEntry


class SqlVaultEntries(MutableMapping[tuple[str, str], tuple[bytes, bytes]]):
    """Drop-in for TokenVault._entries: `TokenVault(key, entries=SqlVaultEntries(session))`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __getitem__(self, key: tuple[str, str]) -> tuple[bytes, bytes]:
        row = self.session.get(VaultEntry, key)
        if row is None:
            raise KeyError(key)
        return row.nonce, row.ciphertext

    def __setitem__(self, key: tuple[str, str], value: tuple[bytes, bytes]) -> None:
        tenant, token = key
        row = self.session.get(VaultEntry, key)
        if row is None:
            self.session.add(VaultEntry(tenant_id=tenant, token=token, nonce=value[0],
                                        ciphertext=value[1]))
        else:
            row.nonce, row.ciphertext = value
        self.session.flush()

    def __delitem__(self, key: tuple[str, str]) -> None:
        row = self.session.get(VaultEntry, key)
        if row is None:
            raise KeyError(key)
        self.session.delete(row)

    def __iter__(self) -> Iterator[tuple[str, str]]:
        for row in self.session.scalars(select(VaultEntry)):
            yield row.tenant_id, row.token

    def __len__(self) -> int:
        return sum(1 for _ in self)
