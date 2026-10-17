import json

from app.contracts import CONTRACTS_VERSION, all_contract_models
from app.contracts.export import OUTPUT, render


def test_committed_schema_matches_code():
    assert OUTPUT.exists(), "run `npm run contracts` and commit docs/api/contracts.json"
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "contracts changed: run `npm run contracts` and commit docs/api/contracts.json"
    )


def test_schema_lists_every_contract_and_the_version():
    schema = json.loads(render())
    assert schema["version"] == CONTRACTS_VERSION
    assert set(all_contract_models()) <= set(schema["$defs"])


def test_money_amount_is_a_string_in_the_schema():
    money = json.loads(render())["$defs"]["Money"]
    assert money["properties"]["amount"]["type"] == "string"
