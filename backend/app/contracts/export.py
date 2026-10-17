"""Export every contract as JSON Schema to docs/api/contracts.json.

Run: `npm run contracts` (or `uv run python -m app.contracts.export` in backend/).
A test fails if the committed file drifts from the code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

from app.contracts import CONTRACTS_VERSION, all_contract_models

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT = REPO_ROOT / "docs" / "api" / "contracts.json"


def build_schema() -> dict[str, object]:
    models = list(all_contract_models().values())
    _, top = models_json_schema(
        [(model, "serialization") for model in models],
        title="Hishab contracts",
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Hishab contracts",
        "version": CONTRACTS_VERSION,
        "$defs": dict(sorted(top["$defs"].items())),
    }


def render() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(all_contract_models())} contracts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
