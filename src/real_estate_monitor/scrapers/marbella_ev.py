from __future__ import annotations

from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper


class MarbellaEVScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="marbella_ev",
                start_url="https://www.marbella-ev.com/propiedades",
                detail_url_patterns=(r"/propiedades/.*/W-[\w\d]+/?(?:$|[?#])",),
                reference_patterns=(r"W-[\w\d]+",),
                headless=headless,
                timeout_ms=timeout_ms,
                max_pages=max_pages,
                retries=retries,
            )
        )
