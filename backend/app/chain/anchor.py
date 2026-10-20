"""Anchor a digest on Ethereum Sepolia, or offline for tests and demos without keys.

The transaction is a zero-value self-transfer whose data field is exactly the 32-byte digest.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Protocol

from app.contracts import AnchorChain, AnchorReceipt

SEPOLIA_CHAIN_ID = 11155111
EXPLORER = "https://sepolia.etherscan.io/tx/"
log = logging.getLogger(__name__)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class AnchorError(RuntimeError):
    pass


def payload_for(digest: str) -> bytes:
    """The only bytes that go on chain."""
    if not _DIGEST.match(digest):
        raise AnchorError("only a lowercase SHA-256 hex digest can be anchored")
    return bytes.fromhex(digest)


class Anchorer(Protocol):
    def anchor(self, digest: str, now: datetime) -> AnchorReceipt: ...

    def onchain_digest(self, receipt: AnchorReceipt) -> str | None: ...


class OfflineAnchorer:
    """Keeps anchors in memory. Labelled `offline` everywhere it appears."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def anchor(self, digest: str, now: datetime) -> AnchorReceipt:
        payload_for(digest)
        self._store[digest] = now.isoformat()
        return AnchorReceipt(chain=AnchorChain.offline, digest=digest, anchored_at=now)

    def onchain_digest(self, receipt: AnchorReceipt) -> str | None:
        return receipt.digest if receipt.digest in self._store else None


class SepoliaAnchorer:
    """Writes digests to Sepolia with web3.py. `w3` is injectable so tests never touch a node."""

    def __init__(self, w3: Any, private_key: str, *, gas_limit: int = 30_000,
                 receipt_timeout: int = 180) -> None:
        self.w3 = w3
        self._key = private_key
        self.account = w3.eth.account.from_key(private_key)
        self.gas_limit = gas_limit
        self.receipt_timeout = receipt_timeout

    @classmethod
    def from_settings(cls, rpc_url: str, private_key: str,
                      receipt_timeout: int = 180) -> SepoliaAnchorer:
        from web3 import Web3  # imported lazily: only the server needs it

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        return cls(w3, private_key, receipt_timeout=receipt_timeout)

    def build_transaction(self, digest: str) -> dict[str, Any]:
        address = self.account.address
        return {
            "to": address,
            "value": 0,
            "data": "0x" + payload_for(digest).hex(),
            "nonce": self.w3.eth.get_transaction_count(address),
            "gas": self.gas_limit,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": SEPOLIA_CHAIN_ID,
        }

    def anchor(self, digest: str, now: datetime) -> AnchorReceipt:
        tx = self.build_transaction(digest)
        signed = self.w3.eth.account.sign_transaction(tx, self._key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.receipt_timeout)
        if receipt["status"] != 1:
            raise AnchorError("anchor transaction failed on chain")
        hex_hash = tx_hash.hex() if isinstance(tx_hash, bytes) else str(tx_hash)
        hex_hash = hex_hash if hex_hash.startswith("0x") else "0x" + hex_hash
        return AnchorReceipt(
            chain=AnchorChain.sepolia,
            digest=digest,
            tx_hash=hex_hash.lower(),
            block_number=int(receipt["blockNumber"]),
            anchored_at=now,
            explorer_url=EXPLORER + hex_hash.lower(),
        )

    def onchain_digest(self, receipt: AnchorReceipt) -> str | None:
        if receipt.tx_hash is None:
            return None
        tx = self.w3.eth.get_transaction(receipt.tx_hash)
        data = tx["input"]
        raw = bytes(data) if not isinstance(data, str) else bytes.fromhex(data.removeprefix("0x"))
        return raw.hex() if len(raw) == 32 else None


class FallbackAnchorer:
    """Anchors on the primary chain and, if that fails (node down, wallet out of test ETH, no
    block in time), anchors offline instead, so an owner's approval never fails because of the
    testnet. The receipt says which chain was used; nothing pretends to be on-chain."""

    def __init__(self, primary: Anchorer, fallback: Anchorer) -> None:
        self.primary = primary
        self.fallback = fallback

    def anchor(self, digest: str, now: datetime) -> AnchorReceipt:
        try:
            return self.primary.anchor(digest, now)
        except Exception as exc:  # any node, wallet or timeout failure: record offline instead
            log.warning("primary anchor failed, anchoring offline: %s", type(exc).__name__)
            return self.fallback.anchor(digest, now)

    def onchain_digest(self, receipt: AnchorReceipt) -> str | None:
        reader = self.primary if receipt.chain is AnchorChain.sepolia else self.fallback
        return reader.onchain_digest(receipt)
