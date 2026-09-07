from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Any
import yaml

DEFAULT_CONFIG = files("trading_execution").joinpath("resources/staging.yaml")


def state_root() -> Path:
    """Set the override before importing state-store modules."""
    selected = os.environ.get("TRADING_EXECUTION_STATE_DIR")
    if selected is not None:
        return Path(selected).expanduser()
    return Path.home() / ".local/state/trading-execution"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    selected = path or os.environ.get("TRADING_EXECUTION_CONFIG")
    resource = Path(selected) if selected else DEFAULT_CONFIG
    config = yaml.safe_load(resource.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("trading configuration must be a mapping")
    paths = config.setdefault("paths", {})
    paths.setdefault("audit_log", str(state_root() / "audit.jsonl"))
    paths.setdefault("journal_dir", str(state_root() / "journal"))
    return config

def configured_text(template: str) -> str:
    """Resolve explicit operational inputs; never infer a deployed location."""
    import re
    def replace(match):
        variable = match.group(1)
        value = os.environ.get(variable, '')
        if not value.strip():
            raise ValueError(f'{variable} is required for this optional legacy operation')
        return value
    return re.sub(r'\$\{(ANALYST_[A-Z0-9_]+)\}', replace, template)
