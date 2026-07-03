from __future__ import annotations

import math
import re

from playwright.async_api import Browser, Page

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper


class SolvillaScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="solvilla",
                start_url="https://www.solvilla.es/properties/",
                detail_url_patterns=(r"/properties/.*/(?:sv|sd)\d+/?(?:$|[?#])",),
                reference_patterns=(r"(?:SV|SD)\d+",),
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

            for page_number in range(1, total_pages + 1):
                if page_number > 1:
                    clicked = await self._go_to_page(page, page_number)
                    if not clicked:
                        break
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass

                snapshots = await self._extract_loaded_page(page)
                for snapshot in snapshots:
                    listings[snapshot.external_id] = snapshot
                self._emit_progress(page_number, total_pages, len(listings))
                if page_number > 1 and not snapshots:
                    break

            return list(listings.values())
        finally:
            await page.close()

    async def _detect_total_pages(self, page: Page) -> int:
        text = await page.locator("body").inner_text()
        count_match = re.search(r"(\d[\d.,]*)\s+properties\s+found", text, re.I)
        if count_match:
            total_properties = int(re.sub(r"\D", "", count_match.group(1)))
            return max(1, math.ceil(total_properties / 16))

        numbers = await page.locator("button, a").evaluate_all(
            """nodes => nodes
                .map((node) => (node.textContent || '').trim())
                .filter((text) => /^\\d+$/.test(text))
                .map((text) => Number(text))"""
        )
        numeric_pages = [int(value) for value in numbers if int(value) > 0]
        return max(numeric_pages) if numeric_pages else 1

    async def _go_to_page(self, page: Page, page_number: int) -> bool:
        page_button = page.get_by_text(str(page_number), exact=True).last
        try:
            await page_button.click(timeout=2500)
            await page.wait_for_timeout(900)
            return True
        except Exception:
            next_button = page.get_by_text(re.compile(r"next|siguiente|›|»", re.I)).last
            try:
                await next_button.click(timeout=2500)
                await page.wait_for_timeout(900)
                return True
            except Exception:
                return False
