from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from real_estate_monitor.config import Settings
from real_estate_monitor.database import create_db_engine, create_session_factory
from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.repository import ListingRepository
from real_estate_monitor.runner import run_scrape_details
from real_estate_monitor.scrapers.base import PropertyScraper, ScrapeIncompleteError


class FakeScraper(PropertyScraper):
    site_name = "solvilla"

    def __init__(self, listings: list[ListingSnapshot]) -> None:
        self._listings = listings

    async def scrape(self) -> list[ListingSnapshot]:
        return self._listings


def listing(number: int) -> ListingSnapshot:
    return ListingSnapshot(
        site="solvilla",
        external_id=f"SV{number:04d}",
        url=f"https://www.solvilla.es/properties/example/SV{number:04d}",
        title=f"Listing {number}",
        price=1_000_000 + number,
    )


def test_rejects_large_listing_count_drop_before_saving(tmp_path: Path) -> None:
    engine = create_db_engine("sqlite:///:memory:")
    session_factory = create_session_factory(engine)
    settings = _settings(tmp_path)

    asyncio.run(
        run_scrape_details(
            FakeScraper([listing(number) for number in range(10)]),
            settings,
            session_factory,
            send_notifications=False,
        )
    )

    with pytest.raises(ScrapeIncompleteError):
        asyncio.run(
            run_scrape_details(
                FakeScraper([listing(number) for number in range(7)]),
                settings,
                session_factory,
                send_notifications=False,
            )
        )

    with session_factory() as session:
        latest = ListingRepository(session).latest_snapshots("solvilla")

    assert len(latest) == 10


def _settings(report_dir: Path) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        report_dir=report_dir,
        log_level="INFO",
        scraper_headless=True,
        scraper_timeout_ms=30_000,
        scraper_max_pages=0,
        scraper_retries=3,
        scraper_min_listing_ratio=0.85,
        telegram_enabled=False,
        telegram_bot_token=None,
        telegram_chat_id=None,
        whatsapp_enabled=False,
        whatsapp_access_token=None,
        whatsapp_phone_number_id=None,
        whatsapp_recipient=None,
        whatsapp_graph_api_version="v20.0",
        email_enabled=False,
        email_smtp_host=None,
        email_smtp_port=587,
        email_username=None,
        email_password=None,
        email_from=None,
        email_to=None,
        email_use_tls=True,
        scrape_schedule_time="09:00",
        scrape_schedule_timezone="Europe/Madrid",
        web_auth_enabled=False,
        web_username=None,
        web_password=None,
    )
