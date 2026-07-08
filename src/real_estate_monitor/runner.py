from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from real_estate_monitor.config import Settings
from real_estate_monitor.diff import detect_changes
from real_estate_monitor.notify import EmailNotifier, TelegramNotifier, WhatsAppNotifier
from real_estate_monitor.report import build_html_email_report, build_markdown_report, write_report
from real_estate_monitor.repository import ListingRepository
from real_estate_monitor.scrapers.base import PropertyScraper, ScrapeIncompleteError
from real_estate_monitor.models import ChangeType, ListingChange

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
        _validate_listing_count(
            scraper.site_name,
            current_count=len(listings),
            previous_count=len(previous),
            minimum_ratio=settings.scraper_min_listing_ratio,
        )
        changes = detect_changes(previous, listings)
        _validate_removal_count(
            scraper.site_name,
            changes=changes,
            max_removals=settings.scraper_max_removals_per_run,
        )
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


def _validate_listing_count(
    site_name: str,
    *,
    current_count: int,
    previous_count: int,
    minimum_ratio: float,
) -> None:
    if previous_count <= 0:
        return
    minimum_count = int(previous_count * minimum_ratio)
    if current_count >= minimum_count:
        return
    raise ScrapeIncompleteError(
        f"Rejected {site_name} scrape because it only found {current_count} listings. "
        f"The previous successful run had {previous_count}, and the safety minimum is {minimum_count}. "
        "This looks like an incomplete scrape, so it was not saved."
    )


def _validate_removal_count(
    site_name: str,
    *,
    changes: list[ListingChange],
    max_removals: int,
) -> None:
    if max_removals <= 0:
        return
    removed = [change for change in changes if change.change_type == ChangeType.REMOVED]
    if len(removed) <= max_removals:
        return
    references = ", ".join(change.listing.external_id for change in removed[:5])
    if len(removed) > 5:
        references = f"{references}, ..."
    raise ScrapeIncompleteError(
        f"Rejected {site_name} scrape because it detected {len(removed)} removed listings "
        f"and the safety maximum is {max_removals}. This looks like an incomplete scrape, "
        f"so it was not saved. First missing references: {references}"
    )
