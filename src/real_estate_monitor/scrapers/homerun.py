from __future__ import annotations

from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper


class HomerunScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="homerun",
                start_url="https://www.homerunmarbella.com/properties",
                detail_url_patterns=(r"/properties/.*/HRB-\d+P/?(?:$|[?#])",),
                reference_patterns=(r"HRB-\d+P",),
                headless=headless,
                timeout_ms=timeout_ms,
                max_pages=max_pages,
                retries=retries,
            )
        )
