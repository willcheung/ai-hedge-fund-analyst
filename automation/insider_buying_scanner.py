#!/usr/bin/env python3
"""
SEC Form 4 Insider Buying Scanner
Checks EDGAR for recent Form 4 filings on sub-$2B wiki tickers.
Flags C-suite open market purchases (not option exercises).

Uses SEC EDGAR submissions API with CIK lookup for reliability.
"""
from automation_paths import configured_text

import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

WIKI_TICKERS_PATH = Path(configured_text("${ANALYST_WIKI_ROOT}")) / "tickers"
DAYS_BACK = 7  # Check filings from last N days

HEADERS = {
    'User-Agent': 'MarketResearchBot contact@example.com',
    'Accept': 'text/html',
}

# Cache for CIK lookups (loaded once per run)
_CIK_CACHE = None


def load_cik_map():
    """Load the full SEC company_tickers.json mapping."""
    global _CIK_CACHE
    if _CIK_CACHE is not None:
        return _CIK_CACHE

    url = 'https://www.sec.gov/files/company_tickers.json'
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        _CIK_CACHE = {info['ticker']: str(info['cik_str']).zfill(10) for info in data.values()}
        return _CIK_CACHE
    except Exception as e:
        print(f"Warning: Could not load CIK map from SEC: {e}", file=sys.stderr)
        _CIK_CACHE = {}
        return _CIK_CACHE


def get_sub_2b_tickers():
    """Get all wiki tickers with market cap < $2B from yfinance."""
    import yfinance as yf

    tickers = []
    for f in WIKI_TICKERS_PATH.glob("*.md"):
        sym = f.stem
        try:
            mc = yf.Ticker(sym).fast_info.market_cap
            if mc and mc < 2_000_000_000:
                tickers.append(sym)
        except Exception:
            pass
    return sorted(tickers)


def get_form4_filings(cik, days_back=DAYS_BACK):
    """Check for recent Form 4 filings using EDGAR submissions JSON API."""
    try:
        url = f'https://data.sec.gov/submissions/CIK{cik}.json'
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())

        filings = data.get('filings', {}).get('recent', {})
        forms = filings.get('form', [])
        dates = filings.get('filingDate', [])
        acc_nums = filings.get('accessionNumber', [])

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime('%Y-%m-%d')

        results = []
        for i, form in enumerate(forms):
            if form == '4' and dates[i] >= cutoff:
                acc = acc_nums[i]
                results.append({
                    'date': dates[i],
                    'url': f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-","")}/{acc}-index.htm',
                    'acc_num': acc,
                })
        return results
    except Exception as e:
        print(f"    Submissions API error: {e}", file=sys.stderr)
        return []


def parse_form4_xml(filing_url):
    """Fetch the XML from a Form 4 filing and extract purchase transactions."""
    try:
        req = urllib.request.Request(filing_url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode('utf-8', errors='replace')

        # Look for the primary document XML
        xml_match = re.search(r'href="([^"]*\.xml)"', html)
        if not xml_match:
            return []

        xml_url = f'https://www.sec.gov{xml_match.group(1)}'
        req2 = urllib.request.Request(xml_url, headers=HEADERS)
        resp2 = urllib.request.urlopen(req2, timeout=10)
        xml = resp2.read().decode('utf-8', errors='replace')

        transactions = []

        # Get reporter info
        reporter = re.search(r'<rptOwnerName>([^<]+)</rptOwnerName>', xml)
        reporter_name = reporter.group(1).strip() if reporter else "Unknown"

        title = re.search(r'<rptOwnerTitle>([^<]+)</rptOwnerTitle>', xml)
        reporter_title = title.group(1).strip() if title else ""

        is_director = '<isDirector>true</isDirector>' in xml
        is_officer = '<isOfficer>true</isOfficer>' in xml
        is_ten_pct = '<isTenPercentOwner>true</isTenPercentOwner>' in xml

        # Parse non-derivative transaction blocks
        tx_blocks = re.findall(
            r'<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>',
            xml, re.DOTALL
        )

        for block in tx_blocks:
            code = re.search(r'<transactionCode>(\w)</transactionCode>', block)
            shares = re.search(r'<transactionShares>([\d,.]+)</transactionShares>', block)
            price = re.search(r'<transactionPricePerShare>([\d,.]+)</transactionPricePerShare>', block)
            date = re.search(r'<transactionDate><value>(\d{4}-\d{2}-\d{2})</value>', block)

            if not code or not shares:
                continue

            code_val = code.group(1)
            shares_val = float(shares.group(1).replace(',', ''))
            price_val = float(price.group(1).replace(',', '')) if price else 0
            date_val = date.group(1) if date else ''

            transactions.append({
                'reporter': reporter_name,
                'title': reporter_title,
                'is_officer': is_officer,
                'is_director': is_director,
                'is_ten_pct': is_ten_pct,
                'code': code_val,
                'shares': shares_val,
                'price': price_val,
                'total_value': shares_val * price_val,
                'date': date_val,
            })

        return transactions
    except Exception as e:
        print(f"    Error parsing Form 4: {e}", file=sys.stderr)
        return []


def scan_all_tickers(tickers, days_back=DAYS_BACK):
    """Scan all sub-$2B tickers for insider buying."""
    cik_map = load_cik_map()
    results = []

    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] Checking ${ticker}...", flush=True)

        cik = cik_map.get(ticker)
        if not cik:
            print(f"    No CIK found for ${ticker}, skipping")
            continue

        filings = get_form4_filings(cik, days_back)

        if not filings:
            continue

        print(f"    {len(filings)} Form 4 filing(s) found", flush=True)

        for filing in filings[:5]:  # Check latest 5 filings max
            transactions = parse_form4_xml(filing['url'])

            for tx in transactions:
                # Only flag open market purchases by officers/directors/10% owners
                if tx['code'] == 'P' and (tx['is_officer'] or tx['is_director'] or tx['is_ten_pct']):
                    # Skip small purchases (< $10K)
                    if tx['total_value'] < 10000:
                        continue

                    results.append({
                        'ticker': ticker,
                        'reporter': tx['reporter'],
                        'title': tx['title'],
                        'shares': tx['shares'],
                        'price': tx['price'],
                        'total_value': tx['total_value'],
                        'date': tx['date'] or filing.get('date', '?'),
                        'url': filing.get('url', ''),
                    })
                    role = tx['title'] or ('Officer' if tx['is_officer'] else 'Director' if tx['is_director'] else '10% Owner')
                    print(f"    🟢 BUY: {tx['reporter']} ({role}) - {tx['shares']:,.0f} shares @ ${tx['price']:.2f} = ${tx['total_value']:,.0f}")

    return results


def format_results(results):
    """Format results for output."""
    if not results:
        return "No insider buying found in the last 7 days across sub-$2B watchlist tickers."

    # Sort by total value descending
    results.sort(key=lambda x: x['total_value'], reverse=True)

    lines = [f"INSIDER BUYING — Last {DAYS_BACK} days\n"]
    lines.append(f"{'='*60}")

    for r in results:
        value_str = f"${r['total_value']:,.0f}"
        role = r['title'] or ('Officer' if r.get('is_officer') else 'Director' if r.get('is_director') else '10% Owner')
        lines.append(f"\n${r['ticker']} | {role}")
        lines.append(f"  {r['reporter']} bought {r['shares']:,.0f} shares @ ${r['price']:.2f}")
        lines.append(f"  Total: {value_str} | Date: {r['date']}")

    lines.append(f"\n{'='*60}")
    lines.append(f"Total signals: {len(results)}")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SEC Form 4 Insider Buying Scanner")
    parser.add_argument("--days", type=int, default=DAYS_BACK, help=f"Days to look back (default: {DAYS_BACK})")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker list (default: auto-detect sub-$2B)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = get_sub_2b_tickers()

    print(f"Scanning {len(tickers)} sub-$2B tickers for insider buying (last {args.days} days)...", flush=True)
    results = scan_all_tickers(tickers, args.days)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_results(results))
