from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.async_api import Browser, Page, async_playwright
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.base import PropertyScraper

logger = logging.getLogger(__name__)

DRUMELIA_URL = "https://www.drumelia.com/properties"
DRUMELIA_REF_PATTERN = r"\bD\d[\w-]*\b"


@dataclass(frozen=True)
class DrumeliaScraperConfig:
    start_url: str = DRUMELIA_URL
    headless: bool = True
    timeout_ms: int = 30_000
    max_pages: int = 0
    retries: int = 3


class DrumeliaScraper(PropertyScraper):
    site_name = "drumelia"

    def __init__(self, config: DrumeliaScraperConfig | None = None) -> None:
        self.config = config or DrumeliaScraperConfig()

    async def scrape(self) -> list[ListingSnapshot]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.config.headless)
            try:
                return await self._scrape_with_browser(browser)
            finally:
                await browser.close()

    async def _scrape_with_browser(self, browser: Browser) -> list[ListingSnapshot]:
        page = await browser.new_page()
        page.set_default_timeout(self.config.timeout_ms)
        try:
            listings: dict[str, ListingSnapshot] = {}
            current_url = self.config.start_url
            seen_pages: set[str] = set()
            page_number = 1
            while True:
                if self.config.max_pages > 0 and page_number > self.config.max_pages:
                    break
                if current_url in seen_pages:
                    logger.warning("Stopping pagination because page was already visited: %s", current_url)
                    break
                seen_pages.add(current_url)
                logger.info("Scraping Drumelia page %s: %s", page_number, current_url)
                snapshots = await self._scrape_page_with_retries(page, current_url)
                for snapshot in snapshots:
                    listings[snapshot.external_id] = snapshot
                next_url = await self._next_page_url(page, seen_pages)
                if not next_url:
                    break
                current_url = next_url
                page_number += 1
            return list(listings.values())
        finally:
            await page.close()

    async def _scrape_page_with_retries(self, page: Page, url: str) -> list[ListingSnapshot]:
        async for attempt in AsyncRetrying(
            wait=wait_exponential(multiplier=1, min=1, max=10),
            stop=stop_after_attempt(self.config.retries),
            reraise=True,
        ):
            with attempt:
                return await self._scrape_page(page, url)
        return []

    async def _scrape_page(self, page: Page, url: str) -> list[ListingSnapshot]:
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            logger.debug("Timed out waiting for Drumelia network idle; continuing with loaded DOM")
        await self._dismiss_cookie_banner(page)
        raw_items = await page.evaluate(_DOM_EXTRACTION_SCRIPT)
        snapshots = [self._parse_item(item) for item in raw_items]
        return [snapshot for snapshot in snapshots if snapshot is not None]

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        for label in ("Accept", "Accept all", "I agree", "Allow all"):
            button = page.get_by_role("button", name=re.compile(label, re.I))
            if await button.count():
                try:
                    await button.first.click(timeout=1500)
                    return
                except Exception:
                    logger.debug("Cookie button click failed for label %s", label, exc_info=True)

    async def _next_page_url(self, page: Page, seen_pages: set[str]) -> str | None:
        candidates = await page.locator("a[href]").evaluate_all(
            """anchors => anchors.map(a => ({
                href: a.href,
                text: (a.textContent || '').trim(),
                rel: a.getAttribute('rel') || '',
                aria: a.getAttribute('aria-label') || ''
            }))"""
        )
        page_links: list[tuple[int, str]] = []
        for item in candidates:
            text = str(item.get("text") or "").strip()
            href = str(item.get("href") or "")
            if (
                text.isdigit()
                and "/properties" in href
                and href not in seen_pages
                and not re.search(DRUMELIA_REF_PATTERN, href)
            ):
                page_links.append((int(text), href))
        if page_links:
            return min(page_links, key=lambda item: item[0])[1]

        for item in candidates:
            text = f"{item.get('text', '')} {item.get('rel', '')} {item.get('aria', '')}".lower()
            href = str(item.get("href") or "")
            if (
                "next" in text
                and "/properties" in href
                and href not in seen_pages
                and not re.search(DRUMELIA_REF_PATTERN, href)
            ):
                return str(item["href"])
        return None

    def _parse_item(self, item: dict[str, str | None]) -> ListingSnapshot | None:
        text = _normalize_space(item.get("text") or "")
        url = urljoin(self.config.start_url, item.get("url") or "")
        title = _normalize_space(item.get("title") or "")
        ref_match = re.search(DRUMELIA_REF_PATTERN, url) or re.search(DRUMELIA_REF_PATTERN, text)
        if not title or not ref_match:
            return None

        external_id = ref_match.group(0)
        location = _extract_location(text, external_id)
        prices = [] if re.search(r"Price on Application", text, re.I) else [
            _parse_int(value) for value in re.findall(r"€\s*[\d.,]+", text)
        ]
        status = _extract_status(text)

        raw = {
            "source_text": text,
            "image": item.get("image"),
            "previous_price": prices[1] if len(prices) > 1 else None,
        }
        return ListingSnapshot(
            site=self.site_name,
            external_id=external_id,
            url=url,
            title=title,
            location=location,
            price=prices[0] if prices else None,
            currency="EUR",
            status=status,
            beds=_extract_float(text, r"Beds\s+([\d.]+)"),
            baths=_extract_float(text, r"Baths\s+([\d.]+)"),
            built_area_m2=_extract_float(text, r"Built\s+([\d.,]+)\s*m"),
            plot_area_m2=_extract_float(text, r"Plot\s+([\d.,]+)\s*m"),
            raw=raw,
            scraped_at=datetime.now(timezone.utc),
        )


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_int(value: str) -> int:
    return int(re.sub(r"[^\d]", "", value))


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _extract_location(text: str, external_id: str) -> str | None:
    match = re.search(rf"([^·]+?)\s*·\s*{re.escape(external_id)}", text)
    if not match:
        return None
    location = _normalize_space(match.group(1))
    for label in _STATUS_LABELS:
        location = location.replace(label, "")
    return _normalize_space(location) or None


def _extract_status(text: str) -> str | None:
    statuses = [label for label in _STATUS_LABELS if re.search(rf"\b{re.escape(label)}\b", text, re.I)]
    return ", ".join(dict.fromkeys(statuses)) or None


_STATUS_LABELS = (
    "Newly Built",
    "New Listing",
    "Exclusive Agency",
    "Sold",
    "Reserved",
    "Under Offer",
)

_DOM_EXTRACTION_SCRIPT = """
() => {
  const anchors = [...document.querySelectorAll('a[href]')].filter((anchor) => {
    const href = new URL(anchor.href, location.href).href;
    const text = (anchor.textContent || '').trim();
    return href.includes('/properties/') && /\/D\\d[\\w-]*(?:$|[?#])/.test(href) && text.length > 12;
  });

  function cardFor(anchor) {
    let node = anchor;
    for (let i = 0; i < 8 && node; i += 1) {
      const text = (node.innerText || node.textContent || '').trim();
      if (/\\bD\\d[\\w-]*\\b/.test(text)) {
        return node;
      }
      node = node.parentElement;
    }
    return anchor;
  }

  const byRef = new Map();
  for (const anchor of anchors) {
    const card = cardFor(anchor);
    const text = (card.innerText || card.textContent || '').trim();
    const refMatch = new URL(anchor.href, location.href).href.match(/\\bD\\d[\\w-]*\\b/) || text.match(/\\bD\\d[\\w-]*\\b/);
    if (!refMatch || byRef.has(refMatch[0])) {
      continue;
    }
    const image = card.querySelector('img')?.currentSrc || card.querySelector('img')?.src || null;
    byRef.set(refMatch[0], {
      title: (anchor.textContent || '').trim(),
      url: new URL(anchor.getAttribute('href'), location.href).href,
      text,
      image,
    });
  }
  return [...byRef.values()];
}
"""
