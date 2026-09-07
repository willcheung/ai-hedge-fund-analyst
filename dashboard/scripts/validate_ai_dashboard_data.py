#!/usr/bin/env python3
"""Validate deterministic AI projection / War Room dashboard data contracts.

This is a local, source-of-truth audit: it checks the generated dashboard payload
against the upstream wiki-market artifacts and verifies key finance formulas.
It intentionally reports extreme pre-revenue margin outliers instead of hiding
or rewriting them.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from dashboard_config import WIKI_ROOT, require_wiki
WIKI = WIKI_ROOT
PROJECTION_SRC = WIKI / 'data/automation/ai_projection_exhibits_latest.json'
WAR_ROOM_SRC = WIKI / 'data/automation/ai_war_room_complete_data_latest.json'
DASHBOARD_JSON = ROOT / 'public/wiki-data.json'
EXTREME_MARGIN_ABS_CUTOFF = 500.0


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f'Missing required file: {path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise SystemExit(f'Expected JSON object: {path}')
    return data


def num(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def approx_equal(a: float, b: float, *, tol_abs: float = 0.15, tol_rel: float = 0.002) -> bool:
    return abs(a - b) <= max(tol_abs, abs(b) * tol_rel)


def verify_war_room_formulas(war_room: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for row in war_room.get('rows', []):
        if not isinstance(row, dict):
            continue
        sym = str(row.get('symbol') or '')
        fv = row.get('fundamentalValuation') if isinstance(row.get('fundamentalValuation'), dict) else {}
        ev = num(fv.get('enterpriseValue'))
        ltm_rev = num(fv.get('ltmRevenue'))
        ntm_rev = num(fv.get('ntmRevenueEstimate'))
        price = num((row.get('tape') or {}).get('price') if isinstance(row.get('tape'), dict) else None)
        eps_ntm = num(fv.get('epsNtm'))
        fcf = num(fv.get('freeCashFlow'))
        fcf_margin = num(fv.get('fcfMarginPct'))
        ev_rev = num(fv.get('evRevenue'))
        ev_ntm_rev = num(fv.get('evNtmRevenue'))
        pe_ntm = num(fv.get('peNtm'))

        if fcf is not None and ltm_rev not in (None, 0) and fcf_margin is not None:
            expected = fcf / ltm_rev * 100.0
            if not approx_equal(fcf_margin, expected):
                errors.append(f'{sym}: fcfMarginPct {fcf_margin:.3f} != freeCashFlow/ltmRevenue {expected:.3f}')
            if abs(expected) > EXTREME_MARGIN_ABS_CUTOFF:
                warnings.append(f'{sym}: extreme FCF margin {expected:.1f}% from FCF {fcf:,.0f} / LTM revenue {ltm_rev:,.0f}; chart-excluded, table-visible')
        if ev is not None and ltm_rev not in (None, 0) and ev_rev is not None:
            expected = ev / ltm_rev
            if not approx_equal(ev_rev, expected, tol_abs=0.02, tol_rel=0.002):
                errors.append(f'{sym}: evRevenue {ev_rev:.3f} != EV/LTM revenue {expected:.3f}')
        if ev is not None and ntm_rev not in (None, 0) and ev_ntm_rev is not None:
            expected = ev / ntm_rev
            if not approx_equal(ev_ntm_rev, expected, tol_abs=0.02, tol_rel=0.002):
                errors.append(f'{sym}: evNtmRevenue {ev_ntm_rev:.3f} != EV/NTM revenue {expected:.3f}')
        if price is not None and eps_ntm not in (None, 0) and pe_ntm is not None:
            expected = price / eps_ntm
            if not approx_equal(pe_ntm, expected, tol_abs=0.03, tol_rel=0.003):
                errors.append(f'{sym}: peNtm {pe_ntm:.3f} != price/epsNtm {expected:.3f}')
    return errors, warnings


def verify_projection_chart_contract(projection: dict[str, Any], dashboard: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = [r for r in projection.get('rows', []) if isinstance(r, dict)]
    chart_data = projection.get('chartData') if isinstance(projection.get('chartData'), dict) else {}
    complete_symbols = sorted(
        str(r.get('symbol') or '') for r in rows
        if all((((r.get('projection') or {}).get(case) or {}).get('impliedPrice') is not None) for case in ('bear', 'base', 'bull'))
    )
    football_symbols = sorted(str(r.get('symbol') or '') for r in chart_data.get('projection_football_field', []) if isinstance(r, dict))
    if football_symbols != complete_symbols:
        errors.append(f'projection football field symbols {football_symbols} != complete projection symbols {complete_symbols}')

    dash_proj = dashboard.get('aiProjectionExhibits') if isinstance(dashboard.get('aiProjectionExhibits'), dict) else {}
    dash_chart = dash_proj.get('chartData') if isinstance(dash_proj.get('chartData'), dict) else {}
    dash_football_symbols = sorted(str(r.get('symbol') or '') for r in dash_chart.get('projection_football_field', []) if isinstance(r, dict))
    if dash_football_symbols != football_symbols:
        errors.append(f'dashboard football symbols {dash_football_symbols} != source football symbols {football_symbols}')

    for key, required_field in [('base_implied_upside_bar', 'baseUpsidePct'), ('bull_implied_upside_bar', 'bullUpsidePct')]:
        source_symbols = sorted(str(r.get('symbol') or '') for r in chart_data.get(key, []) if isinstance(r, dict) and num(r.get(required_field)) is not None)
        expected_symbols = sorted(
            str(r.get('symbol') or '') for r in rows
            if num(((r.get('projection') or {}).get('base' if key.startswith('base') else 'bull') or {}).get('upsidePct')) is not None
        )
        if source_symbols != expected_symbols:
            errors.append(f'{key} symbols {source_symbols} != expected symbols {expected_symbols}')
    return errors


def main() -> int:
    projection = load(PROJECTION_SRC)
    war_room = load(WAR_ROOM_SRC)
    dashboard = load(DASHBOARD_JSON)

    errors, warnings = verify_war_room_formulas(war_room)
    errors.extend(verify_projection_chart_contract(projection, dashboard))

    projection_rows = len(projection.get('rows', []))
    football_rows = len((projection.get('chartData') or {}).get('projection_football_field', []))
    war_rows = len(war_room.get('rows', []))
    print(f'Projection rows: {projection_rows}; football-field rows: {football_rows}')
    print(f'War Room rows: {war_rows}; formula warnings: {len(warnings)}')
    for warning in warnings[:20]:
        print(f'WARN {warning}')
    if errors:
        for error in errors:
            print(f'ERROR {error}')
        return 1
    print('AI dashboard data validation passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
