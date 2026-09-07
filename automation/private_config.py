"""Explicit private inputs. No fallback to live homes or repository account data."""
import json
import os
from pathlib import Path
import re


def required_value(variable):
    value = os.environ.get(variable, '')
    if not value.strip():
        raise ValueError(f'{variable} is required')
    return value


def load_private_json(variable, *, path=None, optional=False):
    value = path if path is not None else os.environ.get(variable)
    if value is None and optional:
        return {}
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{variable} requires an external JSON path')
    checkout = Path(__file__).resolve().parents[1]
    try:
        selected = Path(value).expanduser()
        if not selected.is_absolute():
            raise ValueError('relative input')
        # Reject both checkout symlinks to external files and external symlinks
        # into source. Private input must not be attached through the checkout.
        lexical = Path(os.path.abspath(selected))
        selected = selected.resolve(strict=True)
        if lexical.is_relative_to(checkout) or selected.is_relative_to(checkout):
            raise ValueError('checkout input')
        if not selected.is_file():
            raise ValueError('not a regular file')
        def object_pairs(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError('duplicate JSON key')
                result[key] = item
            return result
        def reject_constant(_):
            raise ValueError('non-finite JSON number')
        payload = json.loads(selected.read_text(encoding='utf-8'),
                             object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except (OSError, ValueError, RuntimeError):
        raise ValueError(f'{variable} could not be loaded') from None
    if not isinstance(payload, dict):
        raise ValueError(f'{variable} must contain a JSON object')
    return payload


def load_holdings():
    payload = load_private_json('ANALYST_HOLDINGS_FILE', optional=True)
    holdings = payload.get('holdings', [])
    if not isinstance(holdings, list) or any(not isinstance(s, str) or not re.fullmatch(r'[A-Z][A-Z0-9.^=-]{0,19}', s) for s in holdings):
        raise ValueError('ANALYST_HOLDINGS_FILE holdings must be a list of symbols')
    return list(dict.fromkeys(holdings))
