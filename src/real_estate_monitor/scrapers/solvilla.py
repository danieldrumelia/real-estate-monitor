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
                detail_url_patterns=(r"/properties/.*/(?:pv|sv|sd)\d+/?(?:$|[?#])",),
                reference_patterns=(r"(?:PV|SV|SD)\d+",),
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
                try:
                    snapshots = await self._extract_next_page(page, page_number, listings.keys())
                except ScrapeIncompleteError:
                    if _has_safe_listing_count(len(listings), total_properties):
                        logger.warning(
                            "Solvilla page %s could not be loaded, but %s listings were already collected; "
                            "treating this as the end of pagination",
                            page_number,
                            len(listings),
                        )
                        break
                    raise
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

    async def _extract_loaded_page(self, page: Page) -> list[ListingSnapshot]:
        await self._wait_for_listing_links(page)
        snapshots = await super()._extract_loaded_page(page)
        if snapshots:
            return snapshots

        logger.warning("Solvilla generic extraction returned 0 listings; trying Solvilla fallback extraction")
        raw_items = await page.evaluate(_SOLVILLA_FALLBACK_EXTRACTION_SCRIPT)
        fallback_snapshots = [self._parse_item(item) for item in raw_items]
        return [snapshot for snapshot in fallback_snapshots if snapshot is not None]

    async def _wait_for_listing_links(self, page: Page) -> None:
        try:
            await page.wait_for_function(
                """() => [...document.querySelectorAll('a[href]')].some((anchor) => {
                    const href = new URL(anchor.getAttribute('href'), location.href).href;
                    return /\\/properties\\/.*\\/(?:pv|sv|sd)\\d+\\/?(?:$|[?#])/i.test(href);
                })""",
                timeout=min(self.config.timeout_ms, 10_000),
            )
        except Exception:
            logger.debug("Timed out waiting for Solvilla listing links; continuing with current DOM", exc_info=True)

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

    async def _extract_next_page(
        self,
        page: Page,
        page_number: int,
        known_external_ids: Iterable[str],
    ) -> list[ListingSnapshot]:
        if page_number == 1:
            return await self._extract_loaded_page(page)

        snapshots = await self._click_next_page(page, page_number, known_external_ids)
        if snapshots:
            return snapshots

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

    async def _click_next_page(
        self,
        page: Page,
        page_number: int,
        known_external_ids: Iterable[str],
    ) -> list[ListingSnapshot]:
        next_button = page.get_by_role("button", name=re.compile(r"^Next page$", re.I)).last
        try:
            await next_button.click(timeout=2500)
            await page.wait_for_timeout(1200)
            snapshots = await self._extract_loaded_page(page)
            if _has_new_listing(snapshots, known_external_ids):
                return snapshots
            logger.warning("Solvilla next-page click produced no new listings for page %s", page_number)
        except Exception:
            logger.debug("Solvilla next-page click failed for page %s", page_number, exc_info=True)
        return []

    def _validate_expected_total(self, listing_count: int, total_properties: int | None) -> None:
        if _has_safe_listing_count(listing_count, total_properties):
            return
        minimum_count = int((total_properties or 0) * MIN_EXPECTED_LISTING_RATIO)
        raise ScrapeIncompleteError(
            f"Solvilla scrape found {listing_count} listings, but the site says there are "
            f"{total_properties}. The safety minimum is {minimum_count}, so this run was not saved."
        )


def _has_new_listing(snapshots: list[ListingSnapshot], known_external_ids: Iterable[str]) -> bool:
    known_ids = set(known_external_ids)
    return any(snapshot.external_id not in known_ids for snapshot in snapshots)


def _has_safe_listing_count(listing_count: int, total_properties: int | None) -> bool:
    if not total_properties:
        return True
    return listing_count >= int(total_properties * MIN_EXPECTED_LISTING_RATIO)


_SOLVILLA_FALLBACK_EXTRACTION_SCRIPT = r"""
() => {
  const refPattern = /\b(?:PV|SV|SD)\d+\b/i;
  const detailPattern = /\/properties\/.*\/(?:pv|sv|sd)\d+\/?(?:$|[?#])/i;
  const anchors = [...document.querySelectorAll('a[href]')].filter((anchor) => {
    const href = new URL(anchor.getAttribute('href'), location.href).href;
    return detailPattern.test(href);
  });

  function titleFrom(text, fallback) {
    const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
    const refIndex = lines.findIndex((line) => /^#?(?:PV|SV|SD)\d+\b/i.test(line));
    if (refIndex < 0) return fallback;

    for (const line of lines.slice(refIndex + 1)) {
      if (/^(exclusive|development|sold|beds?:|baths?:|built:|plot:|from\s+\d|view property|view development|save property|save development)$/i.test(line)) {
        continue;
      }
      if (/^\d/.test(line) || /€$/.test(line)) {
        continue;
      }
      if (line.length > 5) return line;
    }
    return fallback;
  }

  function imageFor(anchor) {
    for (const image of [...anchor.querySelectorAll('img')]) {
      const url = image.currentSrc || image.src || image.getAttribute('data-src') || image.getAttribute('data-lazy-src');
      if (url && !String(url).startsWith('data:')) return new URL(url, location.href).href;
    }
    return null;
  }

  const byRef = new Map();
  for (const anchor of anchors) {
    const href = new URL(anchor.getAttribute('href'), location.href).href;
    const text = (anchor.innerText || anchor.textContent || '').trim();
    const ref = (href.match(refPattern) || text.match(refPattern))?.[0]?.toUpperCase();
    if (!ref || byRef.has(ref)) continue;
    byRef.set(ref, {
      title: titleFrom(text, ref),
      cleanTitle: titleFrom(text, ref),
      url: href,
      text,
      image: imageFor(anchor),
    });
  }
  return [...byRef.values()];
}
"""
