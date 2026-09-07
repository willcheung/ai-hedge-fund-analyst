#!/usr/bin/env python3
"""
Market data fetcher — Yahoo Finance v8 chart API.
Adds retry with exponential backoff and longer delays to avoid 429s.
"""
import json
import urllib.request
import urllib.parse
import time
import sys
import random

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

def fetch_ticker(symbol, max_retries=3, base_delay=2.0):
    """Fetch chart data with retry logic."""
    url = f"{BASE_URL}/{urllib.parse.quote(symbol)}?range=5d&interval=1d&includePrePost=false"
    req = urllib.request.Request(url, headers=HEADERS)
    
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
                continue
            return {"error": f"HTTP {e.code}", "symbol": symbol}
        except Exception as e:
            return {"error": str(e), "symbol": symbol}
    return {"error": "Max retries exceeded", "symbol": symbol}

def extract_quote(chart_data):
    """Extract key quote data from chart response."""
    if "error" in chart_data:
        return chart_data
    
    result = chart_data.get("chart", {}).get("result", [{}])[0]
    meta = result.get("meta", {})
    
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose")
    
    change_pct = None
    if price and prev_close and prev_close != 0:
        change_pct = ((price - prev_close) / prev_close) * 100
    
    return {
        "symbol": meta.get("symbol", "UNKNOWN"),
        "price": price,
        "prev_close": prev_close,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
        "avg_volume": meta.get("averageDailyVolume3Month"),
        "fifty_day_avg": meta.get("fiftyDayAverage"),
        "two_hundred_avg": meta.get("twoHundredDayAverage"),
        "52w_high": meta.get("fiftyTwoWeekHigh"),
        "52w_low": meta.get("fiftyTwoWeekLow"),
        "market_cap": meta.get("circulatingMarketCap") or meta.get("marketCap"),
    }

def fetch_holdings():
    """Fetch explicitly configured holdings. Unconfigured holdings are empty."""
    from private_config import load_holdings
    tickers = load_holdings()

    results = {}
    for i, sym in enumerate(tickers):
        if i > 0:
            time.sleep(3 + random.uniform(0, 2))  # 3-5s delay to avoid rate limit
        
        data = fetch_ticker(sym)
        quote = extract_quote(data)
        results[sym] = quote
        
        status = "✓" if "error" not in quote else "✗"
        print(f"  {status} {sym}", file=sys.stderr)
    
    # Output JSON to stdout
    print(json.dumps(results, default=str))

if __name__ == "__main__":
    fetch_holdings()
