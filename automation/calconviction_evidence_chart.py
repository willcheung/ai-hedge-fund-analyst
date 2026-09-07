#!/usr/bin/env python3
"""Render a compact, source-labeled CalConviction evidence chart."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

PRIVATE_PATTERNS = (
    "account value",
    "account_value",
    "account number",
    "account_number",
    "main taxable",
    "buying power",
    "dry powder",
    "net worth",
    "portfolio value",
    "access token",
    "refresh token",
    "api key",
    "password",
)
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    clean = " ".join(value.split())
    if len(clean) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    lower = clean.lower()
    if any(pattern in lower for pattern in PRIVATE_PATTERNS):
        raise ValueError(f"{field} contains private or credential language")
    return clean


def validate_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    periods = payload.get("periods")
    values = payload.get("values")
    if not isinstance(periods, list) or not isinstance(values, list):
        raise ValueError("periods and values must be arrays")
    if not 2 <= len(periods) <= 8:
        raise ValueError("chart requires 2-8 points")
    if len(periods) != len(values):
        raise ValueError("periods and values must have equal length")

    clean_periods = [_text(value, "period", 18) for value in periods]
    clean_values = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("values must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("values must be finite")
        clean_values.append(numeric)

    highlight = payload.get("highlight_index", len(values) - 1)
    if isinstance(highlight, bool) or not isinstance(highlight, int) or not 0 <= highlight < len(values):
        raise ValueError("highlight_index is outside the series")

    accent = payload.get("accent", "#F59E0B")
    if not isinstance(accent, str) or not HEX_COLOR.fullmatch(accent):
        raise ValueError("accent must be a six-digit hex color")

    return {
        "ticker": _text(payload.get("ticker"), "ticker", 10).upper(),
        "title": _text(payload.get("title"), "title", 72),
        "subtitle": _text(payload.get("subtitle"), "subtitle", 82),
        "periods": clean_periods,
        "values": clean_values,
        "source": _text(payload.get("source"), "source", 100),
        "as_of": _text(payload.get("as_of"), "as_of", 20),
        "highlight_index": highlight,
        "accent": accent.upper(),
    }


def _number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1000:
        return f"{value:,.0f}"
    if absolute >= 100:
        return f"{value:,.1f}".rstrip("0").rstrip(".")
    if absolute >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def render(payload: dict, output_path: Path) -> Path:
    clean = validate_payload(payload)
    from PIL import Image, ImageDraw, ImageFont

    background = "#08111F"
    panel = "#0E1B2E"
    text = "#F8FAFC"
    muted = "#94A3B8"
    grid = "#26364D"
    base_bar = "#3B82F6"
    accent = clean["accent"]
    regular_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    image = Image.new("RGB", (1600, 900), background)
    draw = ImageDraw.Draw(image)
    fonts = {
        "ticker": ImageFont.truetype(bold_path, 30),
        "title": ImageFont.truetype(bold_path, 48),
        "subtitle": ImageFont.truetype(regular_path, 27),
        "axis": ImageFont.truetype(regular_path, 20),
        "value": ImageFont.truetype(bold_path, 23),
        "footer": ImageFont.truetype(regular_path, 19),
    }

    left, top, right, bottom = 120, 300, 1510, 730
    draw.rounded_rectangle((left, top, right, bottom), radius=18, fill=panel)
    plot_left, plot_top, plot_right, plot_bottom = left + 65, top + 35, right - 35, bottom - 70

    low = min(clean["values"] + [0.0])
    high = max(clean["values"] + [0.0])
    raw_span = max(high - low, max(abs(high), abs(low), 1.0))
    rough_step = raw_span / 5
    magnitude = 10 ** math.floor(math.log10(rough_step))
    normalized_step = rough_step / magnitude
    if normalized_step <= 1:
        step = magnitude
    elif normalized_step <= 2:
        step = 2 * magnitude
    elif normalized_step <= 5:
        step = 5 * magnitude
    else:
        step = 10 * magnitude
    y_min = math.floor(low / step) * step if low < 0 else 0.0
    y_max = math.ceil(high / step) * step
    if y_max <= y_min:
        y_max = y_min + step

    def y_for(value: float) -> float:
        ratio = (value - y_min) / (y_max - y_min)
        return plot_bottom - ratio * (plot_bottom - plot_top)

    tick_count = max(1, int(round((y_max - y_min) / step)))
    for tick_index in range(tick_count + 1):
        value = y_min + tick_index * step
        y = y_for(value)
        draw.line((plot_left, y, plot_right, y), fill=grid, width=2)
        label = _number(value)
        box = draw.textbbox((0, 0), label, font=fonts["axis"])
        draw.text((plot_left - 18 - (box[2] - box[0]), y - 11), label, fill=muted, font=fonts["axis"])

    zero_y = y_for(0.0)
    draw.line((plot_left, zero_y, plot_right, zero_y), fill=muted, width=2)
    count = len(clean["values"])
    slot = (plot_right - plot_left) / count
    bar_width = slot * 0.58
    for index, (period, value) in enumerate(zip(clean["periods"], clean["values"])):
        center = plot_left + slot * (index + 0.5)
        value_y = y_for(value)
        x1, x2 = center - bar_width / 2, center + bar_width / 2
        y1, y2 = sorted((zero_y, value_y))
        if abs(y2 - y1) < 2:
            y1 = y2 - 2
        color = accent if index == clean["highlight_index"] else base_bar
        draw.rounded_rectangle((x1, y1, x2, y2), radius=8, fill=color)

        period_box = draw.textbbox((0, 0), period, font=fonts["axis"])
        draw.text((center - (period_box[2] - period_box[0]) / 2, plot_bottom + 20), period, fill=text, font=fonts["axis"])
        number = _number(value)
        number_box = draw.textbbox((0, 0), number, font=fonts["value"])
        number_y = value_y - 38 if value >= 0 else value_y + 10
        draw.text(
            (center - (number_box[2] - number_box[0]) / 2, number_y),
            number,
            fill=color if index == clean["highlight_index"] else text,
            font=fonts["value"],
        )

    draw.text((120, 55), f"${clean['ticker']}", fill=accent, font=fonts["ticker"])
    title_font = fonts["title"]
    while draw.textbbox((0, 0), clean["title"], font=title_font)[2] > 1390 and title_font.size > 34:
        title_font = ImageFont.truetype(bold_path, title_font.size - 2)
    draw.text((120, 105), clean["title"], fill=text, font=title_font)
    draw.text((120, 175), clean["subtitle"], fill=muted, font=fonts["subtitle"])
    draw.text((120, 825), f"Source: {clean['source']}  •  As of {clean['as_of']}", fill=muted, font=fonts["footer"])
    brand = "@CalConviction"
    brand_box = draw.textbbox((0, 0), brand, font=fonts["footer"])
    draw.text((1510 - (brand_box[2] - brand_box[0]), 825), brand, fill=muted, font=fonts["footer"])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    output_path.with_suffix(".json").write_text(
        json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_png", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    output = render(payload, args.output_png)
    print(json.dumps({"status": "ok", "output": str(output), "sidecar": str(output.with_suffix('.json'))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
