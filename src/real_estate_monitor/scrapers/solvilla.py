from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable

from playwright.async_api import Browser, Page

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.base import ScrapeIncompleteError
from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper

logger = logging.getLogger(__name__)

MIN_EXPECTED_LISTING_RATIO = 0.85


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
        page = await self._new_page(browser)
        try:
            await page.goto(self.config.start_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await self._dismiss_cookie_banner(page)

            listings: dict[str, ListingSnapshot] = {}
            total_properties = await self._detect_total_properties(page)
            total_pages = await self._detect_total_pages(page, total_properties=total_properties)
            if self.config.max_pages > 0:
                total_pages = min(total_pages, self.config.max_pages)
            logger.info(
                "Solvilla expects %s properties across %s page(s)",
                total_properties or "an unknown number of",
                total_pages,
            )

            for page_number in range(1, total_pages + 1):
                snapshots = await self._extract_page_number(page, page_number, listings.keys())
                previous_count = len(listings)
                for snapshot in snapshots:
                    listings[snapshot.external_id] = snapshot
                new_count = len(listings) - previous_count
                logger.info(
                    "Solvilla page %s produced %s listings (%s new, %s total)",
                    page_number,
                    len(snapshots),
                    new_count,
                    len(listings),
                )
                self._emit_progress(page_number, total_pages, len(listings))

                if page_number < total_pages and (not snapshots or new_count == 0):
                    raise ScrapeIncompleteError(
                        f"Solvilla scrape stopped early on page {page_number}. "
                        f"Collected {len(listings)} listings, but expected about {total_properties or 'unknown'}."
                    )

            self._validate_expected_total(len(listings), total_properties)
            return list(listings.values())
        finally:
            await page.close()

    async def _detect_total_properties(self, page: Page) -> int | None:
        text = await page.locator("body").inner_text()
        count_match = re.search(r"(\d[\d.,]*)\s+properties\s+found", text, re.I)
        if count_match:
            return int(re.sub(r"\D", "", count_match.group(1)))
        return None

    async def _detect_total_pages(self, page: Page, *, total_properties: int | None) -> int:
        numbers = await page.locator("button, a").evaluate_all(
            """nodes => nodes
                .map((node) => (node.textContent || '').trim())
                .filter((text) => /^\\d+$/.test(text))
                .map((text) => Number(text))"""
        )
        numeric_pages = [int(value) for value in numbers if int(value) > 0]
        paginator_pages = max(numeric_pages) if numeric_pages else 1
        if total_properties:
            detected_page_size = max(1, len(await self._extract_loaded_page(page)))
            count_pages = max(1, math.ceil(total_properties / detected_page_size))
            return max(paginator_pages, count_pages)
        return paginator_pages

    async def _extract_page_number(
        self,
        page: Page,
        page_number: int,
        known_external_ids: Iterable[str],
    ) -> list[ListingSnapshot]:
        if page_number == 1:
            return await self._extract_loaded_page(page)

        if await self._go_to_page(page, page_number):
            snapshots = await self._extract_loaded_page(page)
            if _has_new_listing(snapshots, known_external_ids):
                return snapshots
            logger.warning("Solvilla page %s click produced no new listings; trying direct URLs", page_number)

        snapshots = await self._extract_direct_page(page, page_number, known_external_ids)
        if snapshots:
            return snapshots
        raise ScrapeIncompleteError(f"Solvilla could not load page {page_number}.")

    async def _extract_direct_page(
        self,
        page: Page,
        page_number: int,
        known_external_ids: Iterable[str],
    ) -> list[ListingSnapshot]:
        for url in self._direct_page_urls(page_number):
            logger.info("Trying Solvilla direct page URL: %s", url)
            try:
                await page.goto(url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                await self._dismiss_cookie_banner(page)
                snapshots = await self._extract_loaded_page(page)
                if _has_new_listing(snapshots, known_external_ids):
                    return snapshots
            except Exception:
                logger.debug("Solvilla direct page URL failed: %s", url, exc_info=True)
        return []

    def _direct_page_urls(self, page_number: int) -> tuple[str, str]:
        base_url = self.config.start_url.rstrip("/")
        return (
            f"{base_url}/?page={page_number}",
            f"{base_url}/page/{page_number}/",
        )

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

    def _validate_expected_total(self, listing_count: int, total_properties: int | None) -> None:
        if not total_properties:
            return
        minimum_count = int(total_properties * MIN_EXPECTED_LISTING_RATIO)
        if listing_count >= minimum_count:
            return
        raise ScrapeIncompleteError(
            f"Solvilla scrape found {listing_count} listings, but the site says there are "
            f"{total_properties}. The safety minimum is {minimum_count}, so this run was not saved."
        )


def _has_new_listing(snapshots: list[ListingSnapshot], known_external_ids: Iterable[str]) -> bool:
    known_ids = set(known_external_ids)
    return any(snapshot.external_id not in known_ids for snapshot in snapshots)
