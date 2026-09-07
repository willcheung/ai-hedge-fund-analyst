"""Strict path selection for the audited offline subset; no I/O or mkdir.

Unset variables retain legacy defaults. Explicit values must be absolute and
nonblank, even when nonexistent. Never search an old root for missing inputs.
Configure before importing clients (their existing constants bind at import).
"""
import os
from pathlib import Path


def _root(variable: str, default) -> Path:
    if variable not in os.environ:
        return default()
    value = os.environ[variable]
    if not value.strip() or not Path(value).is_absolute():
        raise ValueError(f'{variable} must be a nonblank absolute path')
    return Path(value)


def hermes_home() -> Path:
    return _root('ANALYST_HERMES_HOME', lambda: Path.home() / '.hermes')


def _child(root: Path, name: str) -> Path:
    if not name or name in ('.', '..') or Path(name).name != name:
        raise ValueError('Expected a single filename without traversal')
    return root / name


def state_path(name: str) -> Path:
    return _child(_root('ANALYST_STATE_DIR', lambda: hermes_home() / 'state'), name)


def secret_path(name: str) -> Path:
    return _child(_root('ANALYST_SECRETS_DIR', hermes_home), name)


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
