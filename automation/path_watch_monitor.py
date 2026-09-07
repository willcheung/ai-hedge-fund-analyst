#!/usr/bin/env python3
"""Stable change detector for the PATH War Room monitor.

Prints only decision-band and source identity state. The scheduler hashes stdout;
unchanged output suppresses the agent run entirely.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Hermes PATH monitor research@example.com"}


def get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def price_state() -> str:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/PATH?range=5d&interval=5m&includePrePost=true"
    data = json.loads(get(url))
    result = data["chart"]["result"][0]
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        quotes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        price = next((value for value in reversed(quotes) if value is not None), None)
    if price is None:
        return "PRICE_STATE=SOURCE_ERROR"
    p = float(price)
    if p >= 17.40:
        band = "NO_CHASE_ABOVE_17_40"
    elif p >= 16.80:
        band = "PROOF_RECLAIM_16_80_17_40"
    elif p > 14.25:
        band = "WAIT_14_25_16_80"
    elif p >= 13.25:
        band = "SCOUT_REVIEW_13_25_14_25"
    elif p >= 12.50:
        band = "RESET_TRANSITION_12_50_13_25"
    elif p >= 11.75:
        band = "DEEP_RESET_11_75_12_50"
    elif p >= 10.75:
        band = "FULL_REUNDERWRITE_10_75_11_75"
    else:
        band = "TECHNICAL_INVALIDATION_BELOW_10_75"
    return f"PRICE_STATE={band}"


def sec_state() -> list[str]:
    data = json.loads(get("https://data.sec.gov/submissions/CIK0001734722.json"))
    recent = data["filings"]["recent"]
    watched = {"10-K", "10-Q", "8-K", "4", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "SC TO-T", "SC TO-T/A", "S-3", "DEF 14A"}
    rows = []
    for acc, form, date, doc in zip(
        recent["accessionNumber"], recent["form"], recent["filingDate"], recent["primaryDocument"]
    ):
        if form in watched:
            rows.append(f"SEC={date}|{form}|{acc}|{doc}")
        if len(rows) >= 6:
            break
    return rows


def ir_state() -> list[str]:
    html = get("https://ir.uipath.com/news").decode("utf-8", "ignore")
    found = []
    seen = set()
    pattern = re.compile(r'href=["\']([^"\']*/news/detail/(\d+)/[^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
    for href, detail_id, raw_title in pattern.findall(html):
        if detail_id in seen:
            continue
        seen.add(detail_id)
        title = re.sub(r"<[^>]+>", " ", raw_title)
        title = re.sub(r"\s+", " ", title).strip()
        if href.startswith("/"):
            href = "https://ir.uipath.com" + href
        found.append(f"IR={detail_id}|{title[:180]}|{href}")
        if len(found) >= 5:
            break
    return found or ["IR=SOURCE_EMPTY"]


def news_state() -> list[str]:
    query = urllib.parse.quote('UiPath PATH stock OR UiPath acquisition OR UiPath earnings')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    root = ET.fromstring(get(url))
    rows = []
    for item in root.findall(".//item")[:6]:
        title = re.sub(r"\s+", " ", item.findtext("title") or "").strip()
        guid = re.sub(r"\s+", "", item.findtext("guid") or item.findtext("link") or "")
        rows.append(f"NEWS={guid}|{title[:200]}")
    return rows or ["NEWS=SOURCE_EMPTY"]


def main() -> None:
    output = []
    for name, fn in (("PRICE", price_state), ("SEC", sec_state), ("IR", ir_state), ("NEWS", news_state)):
        try:
            value = fn()
            output.extend(value if isinstance(value, list) else [value])
        except Exception as exc:
            output.append(f"{name}=SOURCE_ERROR:{type(exc).__name__}")
    print("\n".join(output))


if __name__ == "__main__":
    main()
