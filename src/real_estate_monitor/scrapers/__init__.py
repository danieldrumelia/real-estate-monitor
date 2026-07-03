from __future__ import annotations

from real_estate_monitor.config import Settings
from real_estate_monitor.scrapers.base import PropertyScraper
from real_estate_monitor.scrapers.dmproperties import DMPropertiesScraper
from real_estate_monitor.scrapers.homerun import HomerunScraper
from real_estate_monitor.scrapers.marbella_ev import MarbellaEVScraper
from real_estate_monitor.scrapers.panorama import PanoramaScraper
from real_estate_monitor.scrapers.solvilla import SolvillaScraper


def available_sites() -> tuple[str, ...]:
    return (
        "solvilla",
        "homerun",
        "dmproperties",
        "panorama",
        "marbella_ev",
    )


def build_scraper(site: str, settings: Settings, max_pages: int | None = None) -> PropertyScraper:
    normalized = site.lower().strip()
    common = {
        "headless": settings.scraper_headless,
        "timeout_ms": settings.scraper_timeout_ms,
        "max_pages": max_pages if max_pages is not None else settings.scraper_max_pages,
        "retries": settings.scraper_retries,
    }
    if normalized == "solvilla":
        return SolvillaScraper(**common)
    if normalized == "homerun":
        return HomerunScraper(**common)
    if normalized == "dmproperties":
        return DMPropertiesScraper(**common)
    if normalized == "panorama":
        return PanoramaScraper(**common)
    if normalized == "marbella_ev":
        return MarbellaEVScraper(**common)
    raise ValueError(f"Unknown site: {site}")
