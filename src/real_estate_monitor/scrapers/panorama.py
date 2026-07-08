from __future__ import annotations

import logging
import re

from playwright.async_api import Browser, Page

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper

logger = logging.getLogger(__name__)


class PanoramaScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="panorama",
                start_url="https://www.panoramamarbella.com/properties",
                detail_url_patterns=(r"/properties/.*/PANR-\d+/?(?:$|[?#])",),
                reference_patterns=(r"PANR-\d+",),
                headless=headless,
                timeout_ms=timeout_ms,
                max_pages=max_pages,
                retries=retries,
            )
        )

    async def _scrape_with_browser(self, browser: Browser) -> list[ListingSnapshot]:
        page = await self._new_page(browser)
        try:
            await page.goto(self.config.start_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await self._dismiss_cookie_banner(page)

            listings: dict[str, ListingSnapshot] = {}
            total_pages = await self._detect_total_pages(page)
            if self.config.max_pages > 0:
                total_pages = min(total_pages, self.config.max_pages)

            for page_number in range(1, total_pages + 1):
                current_url = (
                    self.config.start_url
                    if page_number == 1
                    else f"{self.config.start_url}?ipage={page_number}"
                )
                logger.info("Scraping panorama page %s/%s: %s", page_number, total_pages, current_url)
                snapshots = await self._scrape_page_with_retries(page, current_url)
                new_count = 0
                for snapshot in snapshots:
                    if snapshot.external_id not in listings:
                        new_count += 1
                    listings[snapshot.external_id] = snapshot
                logger.info(
                    "panorama page %s produced %s listings (%s new, %s total)",
                    page_number,
                    len(snapshots),
                    new_count,
                    len(listings),
                )
                self._emit_progress(page_number, total_pages, len(listings))

            return list(listings.values())
        finally:
            await page.close()

    async def _detect_total_pages(self, page: Page) -> int:
        text = await page.locator("body").inner_text()
        page_match = re.search(r"Displaying\s+\d+\s+of\s+(\d+)\s+Pages", text, re.I)
        if page_match:
            return max(1, int(page_match.group(1)))

        numbers = await page.locator("button, a").evaluate_all(
            """nodes => nodes
                .map((node) => (node.textContent || '').trim())
                .filter((text) => /^\\d+$/.test(text))
                .map((text) => Number(text))"""
        )
        numeric_pages = [int(value) for value in numbers if int(value) > 0]
        return max(numeric_pages) if numeric_pages else 1
