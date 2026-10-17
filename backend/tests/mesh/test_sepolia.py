"""SepoliaAnchorer against a fake web3 object: no node, no network."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.chain.anchor import SEPOLIA_CHAIN_ID, AnchorError, SepoliaAnchorer
from app.contracts import AnchorChain

DIGEST = "ab" * 32
TX_HASH = bytes.fromhex("cd" * 32)
KEY = "0x" + "11" * 32  # a throwaway test key, never funded
NOW = datetime(2026, 10, 1, tzinfo=UTC)


class FakeEth:
    def __init__(self, status: int = 1) -> None:
        self.sent: list[dict] = []
        self.status = status
        self.account = SimpleNamespace(
            from_key=lambda key: SimpleNamespace(address="0x" + "ab" * 20),
            sign_transaction=self._sign,
        )
        self.gas_price = 1_500_000_000

    def _sign(self, tx, key):
        self.sent.append(tx)
        return SimpleNamespace(raw_transaction=b"signed")

    def get_transaction_count(self, address):
        return 7

    def send_raw_transaction(self, raw):
        assert raw == b"signed"
        return TX_HASH

    def wait_for_transaction_receipt(self, tx_hash, timeout):
        return {"status": self.status, "blockNumber": 6_543_210}

    def get_transaction(self, tx_hash):
        return {"input": bytes.fromhex(self.sent[-1]["data"][2:])}


def make(status: int = 1):
    eth = FakeEth(status)
    return SepoliaAnchorer(SimpleNamespace(eth=eth), KEY), eth


def test_transaction_is_a_zero_value_self_transfer_carrying_only_the_digest():
    anchorer, eth = make()
    anchorer.anchor(DIGEST, NOW)
    tx = eth.sent[0]
    assert tx["to"] == anchorer.account.address and tx["value"] == 0
    assert tx["data"] == "0x" + DIGEST
    assert tx["chainId"] == SEPOLIA_CHAIN_ID and tx["nonce"] == 7


def test_receipt_has_tx_hash_block_and_explorer_link():
    anchorer, _ = make()
    receipt = anchorer.anchor(DIGEST, NOW)
    assert receipt.chain is AnchorChain.sepolia
    assert receipt.tx_hash == "0x" + "cd" * 32
    assert receipt.block_number == 6_543_210
    assert receipt.explorer_url.endswith(receipt.tx_hash)


def test_a_failed_transaction_raises():
    anchorer, _ = make(status=0)
    with pytest.raises(AnchorError, match="failed"):
        anchorer.anchor(DIGEST, NOW)


def test_reads_the_digest_back_from_chain():
    anchorer, _ = make()
    receipt = anchorer.anchor(DIGEST, NOW)
    assert anchorer.onchain_digest(receipt) == DIGEST
