"""Every contract round-trips through JSON unchanged, and every contract has an example."""

import pytest
from pydantic import ValidationError

from app.contracts import all_contract_models
from app.contracts.examples import examples

EXAMPLES = examples()
MODELS = all_contract_models()


def test_every_contract_has_an_example():
    assert sorted(MODELS) == sorted(EXAMPLES)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_json_round_trip_preserves_value(name):
    instance = EXAMPLES[name]
    restored = MODELS[name].model_validate_json(instance.model_dump_json())
    assert restored == instance


@pytest.mark.parametrize("name", ["Money", "Transaction", "Recommendation", "NettingRound"])
def test_contracts_reject_unknown_fields(name):
    data = EXAMPLES[name].model_dump(mode="json")
    data["surprise_field"] = 1
    with pytest.raises(ValidationError, match="surprise_field"):
        MODELS[name].model_validate(data)


def test_money_serialises_as_exact_string_not_float():
    payload = EXAMPLES["Money"].model_dump(mode="json")
    assert payload == {"amount": "1250.50", "currency": "BDT"}
