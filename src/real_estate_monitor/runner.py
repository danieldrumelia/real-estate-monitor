from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from real_estate_monitor.config import Settings
from real_estate_monitor.diff import detect_changes
from real_estate_monitor.notify import EmailNotifier, TelegramNotifier, WhatsAppNotifier
from real_estate_monitor.report import build_html_email_report, build_markdown_report, write_report
from real_estate_monitor.repository import ListingRepository
from real_estate_monitor.scrapers.base import PropertyScraper
from real_estate_monitor.models import ListingChange

logger = logging.getLogger(__name__)


async def run_scrape(
    scraper: PropertyScraper,
    settings: Settings,
    session_factory: sessionmaker,
    send_notifications: bool = True,
) -> tuple[int, int]:
    run_id, changes = await run_scrape_details(
        scraper,
        settings,
        session_factory,
        send_notifications=send_notifications,
    )
    return run_id, len(changes)


async def run_scrape_details(
    scraper: PropertyScraper,
    settings: Settings,
    session_factory: sessionmaker,
    send_notifications: bool = True,
) -> tuple[int, list[ListingChange]]:
    logger.info("Starting scrape for %s", scraper.site_name)
    listings = await scraper.scrape()
    logger.info("Scraped %s listings for %s", len(listings), scraper.site_name)

    with session_factory() as session:
        repository = ListingRepository(session)
        previous = repository.latest_snapshots(scraper.site_name)
        changes = detect_changes(previous, listings)
        run_id = repository.save_run(scraper.site_name, listings)

    markdown = build_markdown_report(scraper.site_name, run_id, changes)
    html = build_html_email_report(scraper.site_name, run_id, changes)
    report_path = write_report(settings.report_dir, scraper.site_name, run_id, markdown)
    logger.info("Wrote report to %s", report_path)

    if send_notifications:
        subject = f"{_site_display_name(scraper.site_name)} Report"
        await EmailNotifier(settings).send(
            subject,
            markdown,
            html=html,
        )
    if send_notifications and changes:
        await TelegramNotifier(settings).send(markdown)
        await WhatsAppNotifier(settings).send(markdown)

    return run_id, changes


def _site_display_name(site_name: str) -> str:
    names = {
        "dmproperties": "DM Properties",
        "marbella_ev": "Marbella EV",
    }
    return names.get(site_name, site_name.replace("_", " ").title())
