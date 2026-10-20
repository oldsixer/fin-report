from __future__ import annotations

import argparse
import json

from .discovery import CNINFO_CATEGORIES, CninfoDiscovery


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe original A-share disclosures for a research question")
    parser.add_argument("--ticker", required=True, help="Exact A-share code with exchange suffix, e.g. 688825.SH")
    parser.add_argument("--as-of", required=True, help="Asia/Shanghai calendar date YYYY-MM-DD, inclusive")
    parser.add_argument("--start-date", required=True, help="Beginning of the question's disclosure search window")
    parser.add_argument("--category", choices=sorted(CNINFO_CATEGORIES), default="", help="Disclosure category")
    parser.add_argument("--keyword", default="", help="Question-derived search term")
    parser.add_argument("--max-pages", type=int, default=3, help="Maximum announcement result pages; truncation is reported")
    args = parser.parse_args()
    result = CninfoDiscovery().search(
        ticker=args.ticker, start_date=args.start_date, as_of=args.as_of,
        keyword=args.keyword, category=args.category, max_pages=args.max_pages,
    )
    print(json.dumps({
        "ticker": args.ticker, "as_of": args.as_of, "start_date": args.start_date,
        "category": args.category, "keyword": args.keyword,
        "total_hits": result.total_hits, "pages_read": result.pages_read,
        "truncated": result.truncated, "unusable_hits": result.unusable_hits,
        "sources": result.sources,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
