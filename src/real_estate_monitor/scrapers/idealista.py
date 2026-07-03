from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
from playwright.async_api import Browser, Page, async_playwright

from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper
from real_estate_monitor.scrapers.generic_agency import _extract_float, _extract_price, _normalize_space

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - optional until dependencies are reinstalled.
    curl_requests = None


_IDEALISTA_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class IdealistaScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="idealista",
                start_url=(
                    "https://www.idealista.com/en/multi/venta-viviendas/"
                    "cOA,cOG,cOw,d6e,dLM,dLN,dLP,dLz/con-precio-desde_1000000/"
                ),
                detail_url_patterns=(r"/(?:en/)?inmueble/\d+/?(?:$|[?#])",),
                reference_patterns=(r"(?<=/inmueble/)\d+",),
                page_url_template=(
                    "https://www.idealista.com/en/multi/venta-viviendas/"
                    "cOA,cOG,cOw,d6e,dLM,dLN,dLP,dLz/con-precio-desde_1000000/pagina-{page}.htm"
                ),
                generated_page_limit=300,
                headless=headless,
                timeout_ms=timeout_ms,
                max_pages=max_pages,
                retries=retries,
            )
        )

    async def scrape(self) -> list[ListingSnapshot]:
        browser_error: Exception | None = None
        try:
            listings = await self._scrape_with_full_chrome()
            if listings:
                return listings
        except Exception as exc:
            browser_error = exc

        try:
            return await self._scrape_with_http()
        except Exception as http_error:
            raise RuntimeError(
                "Idealista could not be scraped. "
                f"Full Chrome error: {browser_error!r}. "
                f"HTTP error: {http_error!r}"
            ) from http_error

    async def _scrape_with_full_chrome(self) -> list[ListingSnapshot]:
        async with async_playwright() as playwright:
            executable_path = _chrome_for_testing_executable()
            launch_options: dict[str, object] = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            }
            if executable_path:
                launch_options["executable_path"] = executable_path

            browser = await playwright.chromium.launch(**launch_options)
            try:
                return await self._scrape_with_browser(browser)
            finally:
                await browser.close()

    async def _scrape_with_http(self) -> list[ListingSnapshot]:
        listings: dict[str, ListingSnapshot] = {}
        total_pages = self.config.max_pages if self.config.max_pages > 0 else self.config.generated_page_limit
        headers = {
            "User-Agent": _IDEALISTA_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9,es;q=0.8",
            "Cache-Control": "no-cache",
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
            for page_number in range(1, total_pages + 1):
                url = self.config.start_url if page_number == 1 else self.config.page_url_template.format(page=page_number)
                html, status_code = await self._fetch_html(client, url, headers)
                snapshots = self._parse_html(html)
                if page_number == 1 and not snapshots:
                    raise RuntimeError(
                        "Idealista returned no listing cards from the page HTML. "
                        f"HTTP status: {status_code}. Text starts: {html[:180]!r}"
                    )
                if page_number > 1 and not snapshots:
                    break

                for snapshot in snapshots:
                    listings[snapshot.external_id] = snapshot
                self._emit_progress(page_number, total_pages, len(listings))

        return list(listings.values())

    async def _fetch_html(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
    ) -> tuple[str, int]:
        if curl_requests is not None:
            return await asyncio.to_thread(_curl_get, url, headers)

        response = await client.get(url)
        response.raise_for_status()
        return response.text, response.status_code

    def _parse_html(self, html: str) -> list[ListingSnapshot]:
        cards = re.findall(
            r"<article\b(?=[^>]*\bdata-element-id=[\"']\d+[\"'])(.*?)</article>",
            html,
            flags=re.I | re.S,
        )
        snapshots = [self._parse_html_card(card) for card in cards]
        return [snapshot for snapshot in snapshots if snapshot is not None]

    def _parse_html_card(self, card_html: str) -> ListingSnapshot | None:
        external_match = re.search(r"\bdata-element-id=[\"'](\d+)[\"']", card_html, flags=re.I)
        if not external_match:
            return None
        external_id = external_match.group(1)

        link_match = re.search(
            r"<a\b(?=[^>]*\bclass=[\"'][^\"']*item-link[^\"']*[\"'])(?=[^>]*\bhref=[\"']([^\"']*/(?:en/)?inmueble/\d+/?[^\"']*)[\"'])[^>]*>(.*?)</a>",
            card_html,
            flags=re.I | re.S,
        )
        url = (
            urljoin(self.config.start_url, unescape(link_match.group(1)))
            if link_match
            else f"https://www.idealista.com/en/inmueble/{external_id}/"
        )
        title = _clean_html_text(link_match.group(2)) if link_match else external_id

        text = _clean_html_text(card_html)
        image_match = re.search(r"<img\b[^>]*(?:src|data-src)=[\"']([^\"']+)[\"']", card_html, flags=re.I)
        agency_match = re.search(
            r"<[^>]+class=[\"'][^\"']*(?:professional-name|logo-branding)[^\"']*[\"'][^>]*>(.*?)</[^>]+>",
            card_html,
            flags=re.I | re.S,
        )

        return self._parse_item(
            {
                "externalId": external_id,
                "url": url,
                "title": title,
                "text": text,
                "image": unescape(image_match.group(1)) if image_match else None,
                "agency": _clean_html_text(agency_match.group(1)) if agency_match else None,
            }
        )

    async def _scrape_with_browser(self, browser: Browser) -> list[ListingSnapshot]:
        context = await browser.new_context(
            user_agent=_IDEALISTA_USER_AGENT,
            locale="en-GB",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9,es;q=0.8",
            },
        )
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en', 'es'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout_ms)
        try:
            listings: dict[str, ListingSnapshot] = {}
            total_pages = self.config.max_pages if self.config.max_pages > 0 else self.config.generated_page_limit

            for page_number in range(1, total_pages + 1):
                url = self.config.start_url if page_number == 1 else self.config.page_url_template.format(page=page_number)
                snapshots = await self._scrape_page_with_retries(page, url)
                if page_number == 1 and not snapshots:
                    try:
                        body_text = await page.locator("body").inner_text(timeout=1500)
                    except Exception:
                        body_text = ""
                    page_title = await page.title()
                    browser_flags = await page.evaluate(
                        "() => ({ webdriver: navigator.webdriver, userAgent: navigator.userAgent })"
                    )
                    raise RuntimeError(
                        "Idealista loaded no listing cards. "
                        "The site may be showing a blank, blocked, or consent page. "
                        f"Page title: {page_title!r}. Text starts: {body_text[:120]!r}. "
                        f"Browser: {browser_flags!r}"
                    )
                if page_number > 1 and not snapshots:
                    break

                for snapshot in snapshots:
                    listings[snapshot.external_id] = snapshot
                self._emit_progress(page_number, total_pages, len(listings))

            return list(listings.values())
        finally:
            await context.close()

    async def _scrape_page(self, page: Page, url: str) -> list[ListingSnapshot]:
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass
        await self._dismiss_cookie_banner(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        try:
            await page.locator("article.item[data-element-id]").first.wait_for(timeout=7000)
        except Exception:
            pass
        return await self._extract_loaded_page(page)

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        await super()._dismiss_cookie_banner(page)
        await page.evaluate(
            """
            () => {
              const labels = ['Reject', 'Reject all', 'Accept and continue', 'Accept all', 'Accept'];
              for (const element of [...document.querySelectorAll('button, a')]) {
                const text = (element.innerText || element.textContent || '').trim();
                if (labels.some((label) => text.toLowerCase() === label.toLowerCase())) {
                  element.click();
                  return true;
                }
              }
              return false;
            }
            """
        )
        try:
            await page.wait_for_timeout(700)
        except Exception:
            pass

    async def _extract_loaded_page(self, page: Page) -> list[ListingSnapshot]:
        raw_items = await page.evaluate(_IDEALISTA_EXTRACTION_SCRIPT)
        snapshots = [self._parse_item(item) for item in raw_items]
        return [snapshot for snapshot in snapshots if snapshot is not None]

    def _parse_item(self, item: dict[str, str | None]) -> ListingSnapshot | None:
        external_id = _normalize_space(item.get("externalId") or "")
        url = urljoin(self.config.start_url, item.get("url") or "")
        title = _normalize_space(item.get("title") or external_id)
        text = _normalize_space(item.get("text") or "")
        if not external_id or not url:
            return None

        return ListingSnapshot(
            site=self.site_name,
            external_id=external_id,
            url=url,
            title=title,
            location=title,
            price=_extract_price(text),
            currency="EUR",
            beds=_extract_float(text, r"(\d+(?:[.,]\d+)?)\s*bed\.?"),
            baths=_extract_float(text, r"(\d+(?:[.,]\d+)?)\s*bath"),
            built_area_m2=_extract_float(text, r"(\d+(?:[.,]\d+)?)\s*m²"),
            raw={
                "source_text": text,
                "image": item.get("image"),
                "agency": item.get("agency"),
            },
            scraped_at=datetime.now(timezone.utc),
        )


_IDEALISTA_EXTRACTION_SCRIPT = """
() => {
  const articles = [...document.querySelectorAll('article.item[data-element-id]')];
  return articles.map((article) => {
    const externalId = article.getAttribute('data-element-id') || '';
    const link = article.querySelector('a.item-link[href*="/inmueble/"]');
    const image = article.querySelector('img')?.currentSrc || article.querySelector('img')?.src || null;
    const agency =
      article.querySelector('.professional-name')?.textContent ||
      article.querySelector('.logo-branding')?.getAttribute('alt') ||
      null;
    return {
      externalId,
      url: link?.href || (externalId ? `https://www.idealista.com/en/inmueble/${externalId}/` : ''),
      title: (link?.textContent || '').trim(),
      text: (article.innerText || article.textContent || '').trim(),
      image,
      agency: agency ? agency.trim() : null,
    };
  }).filter((item) => item.externalId && item.url);
}
"""


def _clean_html_text(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return _normalize_space(unescape(text))


def _curl_get(url: str, headers: dict[str, str]) -> tuple[str, int]:
    if curl_requests is None:
        raise RuntimeError("curl-cffi is not installed")
    response = curl_requests.get(
        url,
        headers=headers,
        impersonate="chrome124",
        timeout=30,
    )
    response.raise_for_status()
    return response.text, response.status_code


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
