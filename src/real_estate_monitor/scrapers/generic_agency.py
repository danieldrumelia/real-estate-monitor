from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Browser, Page, async_playwright
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.base import ProgressCallback, PropertyScraper

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgencyScraperConfig:
    site_name: str
    start_url: str
    detail_url_patterns: tuple[str, ...]
    reference_patterns: tuple[str, ...]
    page_url_template: str | None = None
    generated_page_limit: int = 200
    headless: bool = True
    timeout_ms: int = 30_000
    max_pages: int = 0
    retries: int = 3


class GenericAgencyScraper(PropertyScraper):
    def __init__(self, config: AgencyScraperConfig) -> None:
        self.config = config
        self.site_name = config.site_name
        self.progress_callback: ProgressCallback | None = None

    async def scrape(self) -> list[ListingSnapshot]:
        async with async_playwright() as playwright:
            launch_options: dict[str, object] = {"headless": self.config.headless}
            executable_path = _chrome_for_testing_executable()
            if self.config.headless:
                launch_options["args"] = [
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--no-sandbox",
                ]
            if executable_path and self.config.headless:
                launch_options["executable_path"] = executable_path
            browser = await playwright.chromium.launch(**launch_options)
            try:
                return await self._scrape_with_browser(browser)
            finally:
                await browser.close()

    async def _scrape_with_browser(self, browser: Browser) -> list[ListingSnapshot]:
        page = await self._new_page(browser)
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
                logger.info("Scraping %s page %s: %s", self.site_name, page_number, current_url)
                snapshots = await self._scrape_page_with_retries(page, current_url)
                new_count = 0
                for snapshot in snapshots:
                    if snapshot.external_id not in listings:
                        new_count += 1
                    listings[snapshot.external_id] = snapshot
                logger.info(
                    "%s page %s produced %s listings (%s new, %s total)",
                    self.site_name,
                    page_number,
                    len(snapshots),
                    new_count,
                    len(listings),
                )
                self._emit_progress(page_number, self._estimated_total_pages(page_number, snapshots), len(listings))
                if self.config.page_url_template and page_number >= self.config.generated_page_limit:
                    logger.warning(
                        "Stopping %s pagination at generated page limit %s",
                        self.site_name,
                        self.config.generated_page_limit,
                    )
                    break
                if page_number > 1:
                    if self.config.page_url_template and not snapshots:
                        logger.info("Stopping %s pagination because page %s had no listings", self.site_name, page_number)
                        break
                    if not self.config.page_url_template and new_count == 0:
                        logger.info(
                            "Stopping %s pagination because page %s had no new listings",
                            self.site_name,
                            page_number,
                        )
                        break
                next_url = None
                if self.config.page_url_template and snapshots:
                    next_url = self.config.page_url_template.format(page=page_number + 1)
                if not next_url:
                    next_url = await self._next_page_url(page, seen_pages)
                if not next_url:
                    break
                current_url = next_url
                page_number += 1
            return list(listings.values())
        finally:
            await page.close()

    async def _new_page(self, browser: Browser) -> Page:
        page = await browser.new_page()
        page.set_default_timeout(self.config.timeout_ms)
        await page.route(
            "**/*",
            lambda route: (
                route.abort()
                if route.request.resource_type in {"image", "media", "font", "stylesheet"}
                else route.continue_()
            ),
        )
        return page

    def _emit_progress(self, current_page: int | None, total_pages: int | None, listing_count: int) -> None:
        if self.progress_callback:
            self.progress_callback(self.site_name, current_page, total_pages, listing_count)

    def _estimated_total_pages(self, page_number: int, snapshots: list[ListingSnapshot]) -> int | None:
        if self.config.max_pages > 0:
            return self.config.max_pages
        if self.config.page_url_template and snapshots:
            return self.config.generated_page_limit
        return None

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
            logger.debug("Timed out waiting for %s network idle; continuing", self.site_name)
        await self._dismiss_cookie_banner(page)
        return await self._extract_loaded_page(page)

    async def _extract_loaded_page(self, page: Page) -> list[ListingSnapshot]:
        raw_items = await page.evaluate(
            _DOM_EXTRACTION_SCRIPT,
            {
                "detailUrlPatterns": list(self.config.detail_url_patterns),
                "referencePatterns": list(self.config.reference_patterns),
            },
        )
        snapshots = [self._parse_item(item) for item in raw_items]
        return [snapshot for snapshot in snapshots if snapshot is not None]

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        for label in (
            "Reject",
            "Reject all",
            "Accept and continue",
            "Accept",
            "Accept all",
            "Allow all",
            "I agree",
            "Rechazar",
            "Aceptar",
            "Aceptar todo",
        ):
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
            if text.isdigit() and href not in seen_pages and self._looks_like_listing_page(href):
                page_links.append((int(text), href))
        if page_links:
            return min(page_links, key=lambda item: item[0])[1]

        for item in candidates:
            text = f"{item.get('text', '')} {item.get('rel', '')} {item.get('aria', '')}".lower()
            href = str(item.get("href") or "")
            if (
                href not in seen_pages
                and self._looks_like_listing_page(href)
                and any(word in text for word in ("next", "siguiente", "›", "»"))
            ):
                return href
        return None

    def _looks_like_listing_page(self, href: str) -> bool:
        if any(re.search(pattern, href, re.I) for pattern in self.config.detail_url_patterns):
            return False
        return any(part in href for part in ("/properties", "/property", "/propiedades", "/venta-viviendas"))

    def _parse_item(self, item: dict[str, str | None]) -> ListingSnapshot | None:
        text = _normalize_space(item.get("text") or "")
        url = urljoin(self.config.start_url, item.get("url") or "")
        external_id = self._external_id(url, text)
        title = _clean_title(item.get("cleanTitle") or item.get("title") or external_id or "")
        if not title or not external_id:
            return None

        price = None if _is_price_on_application(text) else _extract_price(text)
        return ListingSnapshot(
            site=self.site_name,
            external_id=external_id,
            url=url,
            title=title,
            location=_extract_location(text, title, external_id),
            price=price,
            currency="EUR",
            beds=_extract_float(text, r"(\d+(?:[.,]\d+)?)\s*(?:Beds?|Bedrooms?|Dorms?|Dormitorios?)\b"),
            baths=_extract_float(text, r"(\d+(?:[.,]\d+)?)\s*(?:Baths?|Bathrooms?|Baños?)\b"),
            built_area_m2=_extract_float(text, r"(\d+(?:[.,]\d+)?)\s*m(?:²|2)?\s*(?:Built|Interior|Construido|built|interior)?"),
            raw={
                "source_text": text,
                "image": item.get("image"),
            },
            scraped_at=datetime.now(timezone.utc),
        )

    def _external_id(self, url: str, text: str) -> str | None:
        for value in (url, text):
            for pattern in self.config.reference_patterns:
                match = re.search(pattern, value, re.I)
                if match:
                    return match.group(0).upper()
        return None


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_title(value: str) -> str:
    title = _normalize_space(value)
    title = re.sub(r"^(Image:\s*)", "", title, flags=re.I)
    return title


def _chrome_for_testing_executable() -> str | None:
    home = Path.home()
    patterns = (
        "Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ".cache/ms-playwright/chromium-*/chrome-linux/chrome",
        "AppData/Local/ms-playwright/chromium-*/chrome-win/chrome.exe",
    )
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in home.glob(pattern) if path.exists())
    if not matches:
        return None
    return str(sorted(matches)[-1])


def _is_price_on_application(text: str) -> bool:
    return bool(re.search(r"Price on Application|Precio a consultar|Precio bajo petición", text, re.I))


def _extract_price(text: str) -> int | None:
    patterns = (
        r"€\s*(\d{1,3}(?:[.,\s\u00a0]\d{3})+|\d+)",
        r"(\d{1,3}(?:[.,\s\u00a0]\d{3})+|\d+)\s*€",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = _parse_int(match.group(1))
            if value and value >= 100_000:
                return value
    return None


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _extract_location(text: str, title: str, external_id: str) -> str | None:
    before_title = text.split(title, 1)[0]
    before_title = before_title.replace(external_id, "")
    before_title = re.sub(r"Previous|Next|Anterior|Siguiente|For sale|En venta|New Listing|Exclusive", "", before_title, flags=re.I)
    parts = [part.strip(" -|·") for part in before_title.splitlines() if part.strip()]
    if parts:
        return _normalize_space(parts[-1]) or None
    return None


_DOM_EXTRACTION_SCRIPT = """
(config) => {
  const detailPatterns = config.detailUrlPatterns.map((pattern) => new RegExp(pattern, 'i'));
  const referencePatterns = config.referencePatterns.map((pattern) => new RegExp(pattern, 'i'));
  const isDetailUrl = (href) => detailPatterns.some((pattern) => pattern.test(href));
  const anchorLabel = (anchor) => (
    anchor.textContent ||
    anchor.getAttribute('aria-label') ||
    anchor.getAttribute('title') ||
    anchor.querySelector('img')?.getAttribute('alt') ||
    ''
  ).trim();
  const referenceFrom = (value) => {
    for (const pattern of referencePatterns) {
      const match = value.match(pattern);
      if (match) return match[0].toUpperCase();
    }
    return null;
  };

  const anchors = [...document.querySelectorAll('a[href]')].filter((anchor) => {
    const href = new URL(anchor.getAttribute('href'), location.href).href;
    const text = anchorLabel(anchor);
    return isDetailUrl(href) && (text.length > 0 || referenceFrom(href));
  });

  function cardFor(anchor) {
    let node = anchor;
    for (let i = 0; i < 9 && node; i += 1) {
      const text = (node.innerText || node.textContent || '').trim();
      if ((/€|Price on Application|Precio/i.test(text) || referenceFrom(text)) && text.length > 40) {
        let card = node;
        for (let j = 0; j < 7 && card; j += 1) {
          if (card.querySelector('img, picture, source')) {
            return card;
          }
          card = card.parentElement;
        }
        return node;
      }
      node = node.parentElement;
    }
    return anchor;
  }

  function cleanTitleFor(card, anchor) {
    const spans = [...card.querySelectorAll('span')];
    const span = spans.find((node) => {
      const text = (node.textContent || '').trim();
      const className = String(node.getAttribute('class') || '');
      return (
        text.length > 8 &&
        className.includes('font-normal') &&
        (className.includes('before:content') || className.includes('leading-10'))
      );
    });
    return (span?.textContent || anchorLabel(anchor)).trim();
  }

  function firstSrcsetUrl(value) {
    if (!value) return null;
    return String(value).split(',')[0]?.trim().split(/\\s+/)[0] || null;
  }

  function absoluteUrl(value) {
    if (!value || String(value).startsWith('data:')) return null;
    try {
      return new URL(value, location.href).href;
    } catch {
      return null;
    }
  }

  function imageFromElement(element) {
    if (!element) return null;
    const attributes = [
      'currentSrc',
      'src',
      'data-src',
      'data-lazy-src',
      'data-original',
      'data-image',
      'data-bg',
      'data-background',
    ];
    for (const attribute of attributes) {
      const value = attribute === 'currentSrc' ? element.currentSrc : element.getAttribute(attribute);
      const url = absoluteUrl(value);
      if (url) return url;
    }
    for (const attribute of ['srcset', 'data-srcset', 'data-lazy-srcset']) {
      const url = absoluteUrl(firstSrcsetUrl(element.getAttribute(attribute)));
      if (url) return url;
    }
    return null;
  }

  function imageFor(card, anchor) {
    const containers = [card, anchor, card.parentElement, card.closest('article, li, section, div')].filter(Boolean);
    for (const container of containers) {
      for (const image of [...container.querySelectorAll('img')]) {
        const url = imageFromElement(image);
        if (url) return url;
      }
      for (const source of [...container.querySelectorAll('source')]) {
        const url = absoluteUrl(firstSrcsetUrl(source.getAttribute('srcset') || source.getAttribute('data-srcset')));
        if (url) return url;
      }
      const background = String(container.getAttribute('style') || '').match(/background-image:\s*url\(["']?([^"')]+)["']?\)/i);
      const backgroundUrl = absoluteUrl(background?.[1]);
      if (backgroundUrl) return backgroundUrl;
    }
    return null;
  }

  const byRef = new Map();
  for (const anchor of anchors) {
    const href = new URL(anchor.getAttribute('href'), location.href).href;
    const card = cardFor(anchor);
    const text = (card.innerText || card.textContent || '').trim();
    const ref = referenceFrom(href) || referenceFrom(text);
    if (!ref || byRef.has(ref)) {
      continue;
    }
    const image = imageFor(card, anchor);
    byRef.set(ref, {
      title: anchorLabel(anchor),
      cleanTitle: cleanTitleFor(card, anchor),
      url: href,
      text,
      image,
    });
  }
  return [...byRef.values()];
}
"""
