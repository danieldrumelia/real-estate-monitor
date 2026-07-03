from __future__ import annotations

import re

from playwright.async_api import Browser, Page

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper


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
        page = await browser.new_page()
        page.set_default_timeout(self.config.timeout_ms)
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

            seen_pages: set[str] = {page.url}
            for page_number in range(1, total_pages + 1):
                if page_number > 1:
                    current_url = f"{self.config.start_url}?ipage={page_number}"
                    if current_url in seen_pages:
                        break
                    seen_pages.add(current_url)
                    await page.goto(current_url, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass

                snapshots = await self._extract_loaded_page(page)
                for snapshot in snapshots:
                    listings[snapshot.external_id] = snapshot
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
