#!/usr/bin/env python3
"""Render the shortlist decision system as a blog-ready PNG + SVG-like source data."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from textwrap import shorten

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "public/wiki-data.json"
DEFAULT_OUTPUT = ROOT / "artifacts/shortlist-decision-system.png"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BG_TOP = (4, 12, 27)
BG_BOTTOM = (8, 24, 42)
WHITE = (241, 245, 249)
TEXT = (203, 213, 225)
MUTED = (132, 153, 180)
CYAN = (56, 189, 248)
GREEN = (74, 222, 128)
AMBER = (250, 204, 21)
RED = (248, 113, 113)
PURPLE = (196, 181, 253)
BORDER = (42, 62, 86)
PANEL = (11, 25, 45)

STAGE_META = [
    ("discovery", "SIGNAL SCOUTS", CYAN),
    ("research", "RESEARCH", PURPLE),
    ("proof", "BUSINESS PROOF", GREEN),
    ("market", "MARKET CONTEXT", CYAN),
    ("portfolio", "PORTFOLIO FIT", PURPLE),
    ("delivery", "VALIDATE + PUBLISH", GREEN),
]

BUCKET_META = [
    ("Research Memory / Not Live Action", "RESEARCH MEMORY", PURPLE, "Interesting; not live capital"),
    ("Wait for Trigger", "WAIT FOR TRIGGER", AMBER, "Proof, price, or freshness pending"),
    ("Buy / Scout Now", "BUY / SCOUT", GREEN, "Every gate clears; bounded starter"),
    ("Add After Proof", "ADD AFTER PROOF", GREEN, "Scale only after business proof"),
    ("Kill / Do Not Average", "KILL GUARDRAIL", RED, "Not a candidate; do not average"),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def gradient(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), BG_TOP)
    px = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(round(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        for x in range(width):
            px[x, y] = color
    return image


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int], outline: tuple[int, int, int], radius: int = 24, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 3) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=face) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    consumed = " ".join(lines)
    if len(consumed) < len(text.strip()) and lines:
        lines[-1] = shorten(lines[-1] + "…", width=max(6, len(lines[-1])), placeholder="…")
    return lines


def text_block(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, face: ImageFont.FreeTypeFont, color: tuple[int, int, int], max_width: int, line_gap: int = 8, max_lines: int = 3) -> int:
    x, y = xy
    for line in wrap(draw, text, face, max_width, max_lines):
        draw.text((x, y), line, font=face, fill=color)
        y += face.size + line_gap
    return y


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int] = CYAN, width: int = 5) -> None:
    draw.line([start, end], fill=color, width=width)
    ex, ey = end
    if end[0] >= start[0]:
        draw.polygon([(ex, ey), (ex - 15, ey - 10), (ex - 15, ey + 10)], fill=color)
    else:
        draw.polygon([(ex, ey), (ex + 15, ey - 10), (ex + 15, ey + 10)], fill=color)


def load_data(path: Path) -> tuple[dict, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    shortlist = payload.get("currentAsymmetricShortlist") or {}
    workflow = shortlist.get("membershipWorkflow") or {}
    if not shortlist.get("rows") or not workflow.get("nodes"):
        raise SystemExit("currentAsymmetricShortlist rows/workflow are missing")
    return shortlist, workflow


def render(input_path: Path, output_path: Path) -> None:
    shortlist, workflow = load_data(input_path)
    rows = shortlist["rows"]
    bucket_counts = Counter(row.get("bucket") for row in rows)
    jobs = [node for node in workflow.get("nodes", []) if node.get("kind") == "job"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for node in jobs:
        stage = str(node.get("stage") or "other")
        if stage in {"gate", "delivery"}:
            stage = "delivery"
        groups[stage].append(node)

    width, height = 2400, 1350
    image = gradient(width, height)
    draw = ImageDraw.Draw(image)
    margin = 90

    draw.text((margin, 58), "HOW THE SHORTLIST CHANGES", font=font(54, True), fill=WHITE)
    draw.text((margin, 126), "Signals can nominate. Reviewed decisions promote. Gates can only block.", font=font(28), fill=TEXT)
    status_color = AMBER if workflow.get("status") == "degraded" else GREEN if workflow.get("status") == "pass" else RED
    rounded(draw, (1900, 66, 2310, 132), PANEL, status_color, 30, 2)
    draw.ellipse((1930, 87, 1950, 107), fill=status_color)
    draw.text((1970, 81), f"{len(jobs)} SCHEDULED FEEDERS", font=font(22, True), fill=WHITE)

    stage_y, stage_h, gap = 220, 310, 18
    stage_w = (width - 2 * margin - gap * (len(STAGE_META) - 1)) // len(STAGE_META)
    for index, (stage, title, accent) in enumerate(STAGE_META):
        x = margin + index * (stage_w + gap)
        nodes = sorted(groups.get(stage, []), key=lambda node: str(node.get("label") or ""))
        rounded(draw, (x, stage_y, x + stage_w, stage_y + stage_h), PANEL, tuple(int(c * 0.6) for c in accent), 22, 2)
        draw.text((x + 22, stage_y + 20), title, font=font(19, True), fill=accent)
        draw.text((x + stage_w - 66, stage_y + 18), str(len(nodes)), font=font(28, True), fill=WHITE)
        y = stage_y + 64
        face = font(16)
        for node in nodes[:9]:
            label = shorten(str(node.get("label") or "Unnamed job"), width=34, placeholder="…")
            dot = GREEN if node.get("status") == "pass" else AMBER if node.get("status") == "degraded" else RED
            draw.ellipse((x + 22, y + 6, x + 32, y + 16), fill=dot)
            draw.text((x + 44, y), label, font=face, fill=TEXT)
            y += 25
        if len(nodes) > 9:
            draw.text((x + 44, y), f"+ {len(nodes) - 9} more", font=face, fill=MUTED)
        draw.line((x + stage_w // 2, stage_y + stage_h, x + stage_w // 2, 575), fill=BORDER, width=3)

    draw.text((margin, 555), "EVIDENCE FAN-IN", font=font(18, True), fill=CYAN)
    draw.line((margin + 190, 566, width - margin, 566), fill=BORDER, width=3)

    central_y, central_h = 620, 170
    central_gap = 95
    central_w = (width - 2 * margin - central_gap * 2) // 3
    central = [
        ("1", "REVIEWED MEMBERSHIP", "An agent or PM changes the one decision list.\nNo price or social signal can auto-promote.", PURPLE),
        ("2", "ELIGIBILITY GATE", "Research + proof + freshness + entry + portfolio fit.\nA failed dependency forces Wait.", AMBER),
        ("3", "ONE DECISION UNIVERSE", f"{len(rows)} names. Each ticker occupies exactly one bucket.\nNo duplicate watchlist.", CYAN),
    ]
    for index, (num, title, description, accent) in enumerate(central):
        x = margin + index * (central_w + central_gap)
        rounded(draw, (x, central_y, x + central_w, central_y + central_h), (13, 28, 49), accent, 26, 3)
        draw.ellipse((x + 24, central_y + 24, x + 68, central_y + 68), fill=tuple(int(c * 0.25) for c in accent), outline=accent, width=2)
        draw.text((x + 39, central_y + 31), num, font=font(18, True), fill=accent)
        draw.text((x + 88, central_y + 27), title, font=font(24, True), fill=WHITE)
        y = central_y + 83
        for line in description.split("\n"):
            draw.text((x + 24, y), line, font=font(18), fill=TEXT)
            y += 31
        if index < 2:
            arrow(draw, (x + central_w + 18, central_y + central_h // 2), (x + central_w + central_gap - 18, central_y + central_h // 2), CYAN, 5)

    bucket_y, bucket_h, bucket_gap = 870, 200, 16
    bucket_w = (width - 2 * margin - bucket_gap * 4) // 5
    draw.text((margin, 824), "CURRENT OUTPUT BUCKETS", font=font(18, True), fill=CYAN)
    for index, (bucket, title, accent, description) in enumerate(BUCKET_META):
        x = margin + index * (bucket_w + bucket_gap)
        rounded(draw, (x, bucket_y, x + bucket_w, bucket_y + bucket_h), (12, 25, 44), tuple(int(c * 0.65) for c in accent), 22, 2)
        draw.text((x + 20, bucket_y + 18), title, font=font(18, True), fill=accent)
        draw.text((x + 20, bucket_y + 57), str(bucket_counts.get(bucket, 0)), font=font(52, True), fill=WHITE)
        draw.text((x + 20, bucket_y + 119), "names", font=font(17, True), fill=MUTED)
        text_block(draw, (x + 20, bucket_y + 150), description, font(16), TEXT, bucket_w - 40, 4, 2)

    demotion_y = 1135
    rounded(draw, (margin, demotion_y, width - margin, 1262), (18, 24, 39), (103, 78, 24), 24, 2)
    draw.text((margin + 24, demotion_y + 18), "FAIL-CLOSED PATHS", font=font(18, True), fill=AMBER)
    rules = [
        "ABOVE ENTRY → WAIT / NO CHASE",
        "BELOW ENTRY → RE-UNDERWRITE",
        "STALE INPUT → WAIT",
        "THESIS BREAK → KILL / DO NOT AVERAGE",
    ]
    rule_w = (width - 2 * margin - 48) // 4
    for index, rule in enumerate(rules):
        x = margin + 24 + index * rule_w
        draw.text((x, demotion_y + 66), rule, font=font(17, True), fill=WHITE)

    generated = str(workflow.get("generatedAt") or shortlist.get("generatedAt") or "")
    try:
        generated = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except ValueError:
        pass
    draw.text((margin, 1302), f"WILL MARKET DASHBOARD  •  SYSTEM VIEW AS OF {generated}", font=font(16, True), fill=MUTED)
    draw.text((width - margin, 1302), "KILL = ACTIVE RISK MEMORY, NOT A BUY CANDIDATE", font=font(16, True), fill=RED, anchor="ra")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    print(json.dumps({"output": str(output_path), "width": width, "height": height, "jobCount": len(jobs), "bucketCounts": dict(bucket_counts)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.input, args.output)


if __name__ == "__main__":
    main()
