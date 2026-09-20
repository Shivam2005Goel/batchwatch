"""Finding the monthly NSQ alert PDFs on cdsco.gov.in.

The site reorganises periodically and does not publish a machine-readable
index, so this is a scraper and is expected to need maintenance. Everything it
finds is recorded by URL hash in the SOURCE#CDSCO partition, which makes
re-running it cheap and idempotent.

Run scripts/download_cdsco.py locally first: having the corpus on disk is a
day-one necessity, and automating the fetch is a day-three nicety.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

# Pages that have carried the monthly drug alert listings.
LISTING_PAGES = (
    "https://cdsco.gov.in/opencms/opencms/en/Drugs/Drug-Alerts/",
    "https://cdsco.gov.in/opencms/opencms/en/Notifications/Alerts/",
    "https://cdsco.gov.in/opencms/opencms/en/Consumer/Drug-Alert/",
)

USER_AGENT = (
    "BatchWatch/1.0 (public-health recall lookup; contact via project repository)"
)

_PDF_HREF_RE = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.IGNORECASE)
_LINK_TEXT_RE = re.compile(
    r'href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)

_MONTH_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-_,]*((?:19|20)\d{2})",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ALERT_HINT_RE = re.compile(
    r"(alert|nsq|not\s*of\s*standard|standard\s*quality|spurious)", re.IGNORECASE
)


def guess_alert_month(*texts: str) -> str:
    """Pull a YYYY-MM out of a link label or filename."""
    for text in texts:
        if not text:
            continue
        m = _MONTH_RE.search(text)
        if m:
            return f"{int(m.group(2)):04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}"
        m = re.search(r"((?:19|20)\d{2})[\-_]?(0[1-9]|1[0-2])", text)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return ""


def _strip_tags(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


def find_pdf_links(html: str, base_url: str, alerts_only: bool = True) -> list[dict]:
    """Extract candidate alert PDFs from a listing page."""
    found: dict[str, dict] = {}

    for href, label_html in _LINK_TEXT_RE.findall(html or ""):
        label = _strip_tags(label_html)
        url = urljoin(base_url, href)
        if alerts_only and not (_ALERT_HINT_RE.search(label) or _ALERT_HINT_RE.search(url)):
            continue
        found[url] = {
            "url": url,
            "label": label[:200],
            "alert_month": guess_alert_month(label, href),
        }

    # Some listings render links without readable text.
    for href in _PDF_HREF_RE.findall(html or ""):
        url = urljoin(base_url, href)
        if url in found:
            continue
        if alerts_only and not _ALERT_HINT_RE.search(url):
            continue
        found[url] = {"url": url, "label": "", "alert_month": guess_alert_month(href)}

    return sorted(found.values(), key=lambda d: (d["alert_month"] or "", d["url"]), reverse=True)


def fetch(url: str, timeout: int = 60) -> bytes:
    """HTTP GET with a descriptive user agent."""
    import requests

    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def discover(pages: tuple[str, ...] = LISTING_PAGES, alerts_only: bool = True) -> list[dict]:
    """Walk the known listing pages and return every alert PDF found."""
    out: dict[str, dict] = {}
    for page in pages:
        try:
            html = fetch(page).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - one dead page must not stop the rest
            print(f"listing page failed {page}: {type(exc).__name__}: {exc}")
            continue
        for link in find_pdf_links(html, page, alerts_only=alerts_only):
            out.setdefault(link["url"], link)
    return sorted(out.values(), key=lambda d: (d["alert_month"] or "", d["url"]), reverse=True)
