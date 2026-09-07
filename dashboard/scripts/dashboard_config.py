"""Explicit local path overrides; unset integrations have no external defaults.

No filesystem reads or credential loading occur at import time.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configured_path(name: str, default: Path | str) -> Path:
    value = os.environ.get(name)
    if value is not None and not value.strip():
        raise ValueError(f"{name} must not be empty")
    return Path(value if value is not None else default).expanduser()


WIKI_ROOT = configured_path("MARKETWIKI_WIKI_ROOT", ROOT / ".disabled/wiki")
CRON_ROOT = configured_path("MARKETWIKI_CRON_ROOT", ROOT / ".disabled/cron")
CACHE_ROOT = configured_path("MARKETWIKI_CACHE_ROOT", ROOT / ".cache")
STATE_ROOT = configured_path("MARKETWIKI_STATE_ROOT", ROOT / ".local-state")
ENV_FILE = configured_path("MARKETWIKI_ENV_FILE", ROOT / ".disabled/credentials")


def require_wiki(root: Path) -> Path:
    if not root.is_dir():
        raise FileNotFoundError(f"Configured wiki root does not exist or is not a directory: {root}; no fallback attempted")
    return root
