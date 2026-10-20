"""Question-targeted discovery of issuer disclosures on CNINFO.

The public CNINFO search endpoint is a source *locator*, not evidence.  A result
becomes evidence only after its original PDF has been retrieved and inspected.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from .graph import ms_to_shanghai
from .sources import SourceError


CNINFO_CATEGORIES = {
    "annual_report": "category_ndbg_szsh",
    "half_year_report": "category_bndbg_szsh",
    "first_quarter_report": "category_yjdbg_szsh",
    "third_quarter_report": "category_sjdbg_szsh",
    "earnings_forecast": "category_yjygjxz_szsh",
    "daily_operations": "category_rcjy_szsh",
    "governance": "category_gszl_szsh",
    "risk_notice": "category_fxts_szsh",
    "correction": "category_bcgz_szsh",
}

_PDF_PATH = re.compile(r"^finalpage/(20\d\d-\d\d-\d\d)/([0-9]+)\.PDF$", re.IGNORECASE)
_STOCK_CODE = re.compile(r"^\d{6}(?:\.(?:SH|SZ|BJ))?$", re.IGNORECASE)


@dataclass(frozen=True)
class DiscoveryResult:
    sources: list[dict[str, str]]
    total_hits: int
    pages_read: int
    truncated: bool
    unusable_hits: dict[str, int]


class CninfoDiscovery:
    """A-share announcement lookup using CNINFO's public website interface."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self._organizations: dict[str, str] | None = None

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceError(f"CNINFO discovery unavailable: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise SourceError("CNINFO returned a non-object response")
        return body

    def _org_id(self, code: str) -> str:
        if self._organizations is None:
            body = self._request_json("GET", "https://www.cninfo.com.cn/new/data/szse_stock.json")
            stocks = body.get("stockList")
            if not isinstance(stocks, list):
                raise SourceError("CNINFO stock directory has an unexpected shape")
            self._organizations = {
                str(item["code"]): str(item["orgId"])
                for item in stocks
                if isinstance(item, dict) and item.get("code") and item.get("orgId")
            }
        if code not in self._organizations:
            raise SourceError(f"CNINFO has no organization ID for {code}")
        return self._organizations[code]

    def search(
        self, *, ticker: str, start_date: str, as_of: str,
        keyword: str = "", category: str = "", max_pages: int = 3,
    ) -> DiscoveryResult:
        """Find original PDFs for a particular research question and date window.

        ``category`` is a key in CNINFO_CATEGORIES or empty for all categories.
        A truncated result must not be interpreted as exhaustive coverage.
        """
        if not _STOCK_CODE.fullmatch(ticker):
            raise ValueError("CNINFO discovery requires an exact six-digit A-share ticker")
        code = ticker[:6]
        if not isinstance(keyword, str) or len(keyword) > 100:
            raise ValueError("CNINFO keyword must be at most 100 characters")
        if category and category not in CNINFO_CATEGORIES:
            raise ValueError(f"Unknown CNINFO category: {category}")
        first, last = date.fromisoformat(start_date), date.fromisoformat(as_of)
        if first > last or max_pages < 1:
            raise ValueError("Invalid CNINFO search window or page limit")
        org_id = self._org_id(code)
        payload = {
            "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
            "plate": "", "stock": f"{code},{org_id}", "searchkey": keyword,
            "secid": "", "category": CNINFO_CATEGORIES.get(category, ""),
            "trade": "", "seDate": f"{first.isoformat()}~{last.isoformat()}",
            "sortName": "", "sortType": "", "isHLtitle": "false",
        }
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        unusable: Counter[str] = Counter()
        total_hits: int | None = None
        pages_read = 0
        while pages_read < max_pages:
            payload["pageNum"] = str(pages_read + 1)
            body = self._request_json(
                "POST", "https://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload,
                headers={"Referer": "https://www.cninfo.com.cn/"},
            )
            try:
                reported_total = int(body["totalAnnouncement"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError("CNINFO totalAnnouncement is missing or invalid") from exc
            hits = body.get("announcements")
            if hits is None and reported_total == 0:
                hits = []
            if not isinstance(hits, list) or reported_total < 0:
                raise SourceError("CNINFO announcements response has an unexpected shape")
            if total_hits is None:
                total_hits = reported_total
            elif reported_total != total_hits:
                raise SourceError("CNINFO result count changed during pagination")
            pages_read += 1
            for item in hits:
                if not isinstance(item, dict) or str(item.get("secCode")) != code or str(item.get("orgId")) != org_id:
                    unusable["identity_mismatch"] += 1
                    continue
                path = str(item.get("adjunctUrl") or "")
                match = _PDF_PATH.fullmatch(path)
                if not match:
                    unusable["unsupported_pdf_path"] += 1
                    continue
                if str(item.get("announcementId")) != match.group(2):
                    unusable["announcement_id_mismatch"] += 1
                    continue
                try:
                    disclosed = ms_to_shanghai(item["announcementTime"]).date()
                except (KeyError, TypeError, ValueError, OSError):
                    unusable["invalid_publication_time"] += 1
                    continue
                if disclosed.isoformat() != match.group(1) or not first <= disclosed <= last:
                    unusable["publication_date_mismatch"] += 1
                    continue
                url = "https://static.cninfo.com.cn/" + path
                if url in seen_urls:
                    continue
                if not item.get("announcementTitle"):
                    unusable["missing_title"] += 1
                    continue
                seen_urls.add(url)
                sources.append({
                    "url": url,
                    "title": str(item["announcementTitle"]),
                    "publisher": "巨潮资讯网（公司原始披露）",
                    "security_code": code,
                    "security_name": str(item.get("secName") or ""),
                    "organization_id": org_id,
                    "published_at": disclosed.isoformat(),
                    "date_basis": "cninfo_api_announcementTime_and_pdf_path",
                    "source_role": "issuer_disclosure",
                    "announcement_id": match.group(2),
                })
            if pages_read * 30 >= total_hits or not hits:
                break
        return DiscoveryResult(sources, total_hits or 0, pages_read, pages_read * 30 < (total_hits or 0), dict(unusable))
