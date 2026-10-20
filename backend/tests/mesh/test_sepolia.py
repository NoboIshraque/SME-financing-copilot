"""SepoliaAnchorer against a fake web3 object: no node, no network."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.chain.anchor import (
    SEPOLIA_CHAIN_ID,
    AnchorError,
    FallbackAnchorer,
    OfflineAnchorer,
    SepoliaAnchorer,
)
from app.contracts import AnchorChain
from app.security.jobs import anchorer_for
from app.settings import Settings

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


def test_a_failing_testnet_falls_back_to_an_offline_anchor_that_says_so():
    """Out of test ETH, node down or no block in time: the approval still completes."""
    anchorer, _ = make(status=0)
    receipt = FallbackAnchorer(anchorer, OfflineAnchorer()).anchor(DIGEST, NOW)
    assert receipt.chain is AnchorChain.offline and receipt.tx_hash is None
    assert receipt.digest == DIGEST


def test_a_working_testnet_is_used_and_read_back_through_the_fallback():
    anchorer, _ = make()
    both = FallbackAnchorer(anchorer, OfflineAnchorer())
    receipt = both.anchor(DIGEST, NOW)
    assert receipt.chain is AnchorChain.sepolia
    assert both.onchain_digest(receipt) == DIGEST


def test_the_wait_for_a_block_is_bounded_for_web_requests():
    eth = FakeEth()
    seen = {}
    eth.wait_for_transaction_receipt = lambda tx_hash, timeout: seen.setdefault("t", timeout) and {
        "status": 1, "blockNumber": 1}
    SepoliaAnchorer(SimpleNamespace(eth=eth), KEY, receipt_timeout=60).anchor(DIGEST, NOW)
    assert seen["t"] == 60


def test_a_malformed_key_keeps_the_audit_anchor_offline():
    settings = Settings(_env_file=None, chain_mode="sepolia", sepolia_rpc_url="http://127.0.0.1:9",
                        sepolia_private_key="not-a-key")
    assert isinstance(anchorer_for(settings), OfflineAnchorer)
