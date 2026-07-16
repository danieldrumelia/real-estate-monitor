from __future__ import annotations

from real_estate_monitor.scrapers.generic_agency import AgencyScraperConfig, GenericAgencyScraper


class DMPropertiesScraper(GenericAgencyScraper):
    def __init__(self, *, headless: bool, timeout_ms: int, max_pages: int, retries: int) -> None:
        super().__init__(
            AgencyScraperConfig(
                site_name="dmproperties",
                start_url="https://www.dmproperties.com/property",
                detail_url_patterns=(r"/property/.*/(?:DMCO|DMD|DM)\d[\w-]*/?(?:$|[?#])",),
                reference_patterns=(r"(?:DMCO|DMD|DM)\d[\w-]*",),
                headless=headless,
                timeout_ms=timeout_ms,
                max_pages=max_pages,
                retries=retries,
                prefer_card_title_for_price_rows=True,
            )
        )
