from __future__ import annotations

from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper


class DrumeliaScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="drumelia",
                start_url="https://www.drumelia.com/properties",
                detail_url_patterns=(r"/properties/.*/D\d[\w-]*/?(?:$|[?#])",),
                reference_patterns=(r"D\d[\w-]*",),
                headless=headless,
                timeout_ms=timeout_ms,
                max_pages=max_pages,
                retries=retries,
            )
        )
