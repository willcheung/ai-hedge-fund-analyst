from __future__ import annotations

import json
from pathlib import Path
from importlib.resources import files
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = files("trading_execution").joinpath("resources/trade_intent.schema.json")


def load_trade_intent_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_trade_intent_payload(payload: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
