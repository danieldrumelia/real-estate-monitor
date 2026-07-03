from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from real_estate_monitor.config import Settings
from real_estate_monitor.database import create_db_engine, create_session_factory
from real_estate_monitor.logging_config import configure_logging
from real_estate_monitor.models import ChangeType, ListingChange, ListingSnapshot
from real_estate_monitor.notify import EmailNotifier
from real_estate_monitor.report import (
    SiteReportSection,
    build_combined_html_email_report,
    build_combined_markdown_report,
)
from real_estate_monitor.runner import run_scrape
from real_estate_monitor.scheduler import run_all_sites_once, run_daily_scheduler
from real_estate_monitor.scrapers import available_sites, build_scraper
from real_estate_monitor.web import serve_dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="real-estate-monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Scrape a registered real estate website")
    scrape.add_argument("site", choices=(*available_sites(), "all"))
    scrape.add_argument("--max-pages", type=int, default=None)
    scrape.add_argument("--notifications", dest="notifications", action="store_true", default=True)
    scrape.add_argument("--no-notifications", dest="notifications", action="store_false")
    scrape.add_argument("--telegram", dest="notifications", action="store_true")
    scrape.add_argument("--no-telegram", dest="notifications", action="store_false")

    subparsers.add_parser("list-sites", help="Show registered scraper sites")

    web = subparsers.add_parser("web", help="Start the internal web dashboard")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)

    test_email = subparsers.add_parser("test-email", help="Send a test email using .env SMTP settings")
    test_email.add_argument("--subject", default="Market Report")

    subparsers.add_parser(
        "scheduled-scrape",
        help="Run every active scraper once and email reports. Use this from a cloud cron job.",
    )

    subparsers.add_parser(
        "scheduler",
        help="Keep running and scrape every day at SCRAPE_SCHEDULE_TIME.",
    )

    subparsers.add_parser(
        "check-config",
        help="Print safe configuration details for deployment checks.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    if args.command == "list-sites":
        for site in available_sites():
            print(site)
        return 0

    if args.command == "test-email":
        sections = _example_report_sections()
        markdown = build_combined_markdown_report(sections)
        html = build_combined_html_email_report(sections)
        await EmailNotifier(settings).send(
            args.subject,
            markdown,
            html=html,
            attachment_name="market-report-preview.md",
        )
        print("Test email command finished. Check the inbox and spam folder.")
        return 0

    if args.command == "check-config":
        _print_safe_config(settings)
        return 0

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    if args.command == "web":
        serve_dashboard(session_factory, settings, host=args.host, port=args.port)
        return 0

    if args.command == "scheduled-scrape":
        results = await run_all_sites_once(settings, session_factory, send_notifications=True)
        for result in results:
            if result.ok:
                print(f"{result.site}: run {result.run_id} complete. Detected {result.change_count} change(s).")
            else:
                print(f"{result.site}: failed. {result.error}")
        return 0 if all(result.ok for result in results) else 1

    if args.command == "scheduler":
        await run_daily_scheduler(settings, session_factory)
        return 0

    if args.site == "all":
        if args.max_pages is None:
            results = await run_all_sites_once(settings, session_factory, send_notifications=args.notifications)
            for result in results:
                if result.ok:
                    print(f"{result.site}: run {result.run_id} complete. Detected {result.change_count} change(s).")
                else:
                    print(f"{result.site}: failed. {result.error}")
            return 0 if all(result.ok for result in results) else 1

        failed = False
        for site in available_sites():
            try:
                scraper = build_scraper(site, settings, max_pages=args.max_pages)
                run_id, change_count = await run_scrape(
                    scraper,
                    settings,
                    session_factory,
                    send_notifications=args.notifications,
                )
                print(f"{site}: run {run_id} complete. Detected {change_count} change(s).")
            except Exception as exc:
                failed = True
                print(f"{site}: failed. {exc}")
        return 1 if failed else 0

    scraper = build_scraper(args.site, settings, max_pages=args.max_pages)
    run_id, change_count = await run_scrape(scraper, settings, session_factory, send_notifications=args.notifications)
    print(f"{args.site}: run {run_id} complete. Detected {change_count} change(s).")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


def _print_safe_config(settings: Settings) -> None:
    database_type = "postgresql" if "postgres" in settings.database_url else "sqlite"
    print(f"Database: {database_type}")
    print(f"Reports folder: {settings.report_dir}")
    print(f"Email enabled: {settings.email_enabled}")
    print(f"Email recipients: {', '.join(settings.email_recipients) or 'none'}")
    print(f"Schedule: {settings.scrape_schedule_time} {settings.scrape_schedule_timezone}")
    print(f"Dashboard login enabled: {settings.web_auth_enabled}")
    print(f"Dashboard username set: {bool(settings.web_username)}")
    print(f"Dashboard password set: {bool(settings.web_password)}")


def _example_report_sections() -> list[SiteReportSection]:
    now = datetime.now(timezone.utc)
    solvilla_new = ListingSnapshot(
        site="solvilla",
        external_id="SV2257",
        url="https://www.solvilla.es/properties/example-sv2257",
        title="Contemporary Villa in Nueva Andalucia",
        price=4_950_000,
        scraped_at=now,
    )
    dm_current = ListingSnapshot(
        site="dmproperties",
        external_id="DM5021",
        url="https://www.dmproperties.com/property/example-dm5021",
        title="Penthouse with Sea Views",
        price=2_750_000,
        scraped_at=now,
    )
    dm_previous = ListingSnapshot(
        site="dmproperties",
        external_id="DM5021",
        url=dm_current.url,
        title=dm_current.title,
        price=2_950_000,
        scraped_at=now,
    )
    panorama_removed = ListingSnapshot(
        site="panorama",
        external_id="PANR-15123",
        url="https://www.panoramamarbella.com/properties/example-panr-15123",
        title="Apartment Near Marbella Club",
        price=1_250_000,
        scraped_at=now,
    )
    return [
        SiteReportSection(
            site="solvilla",
            run_id=101,
            changes=[ListingChange(ChangeType.NEW, solvilla_new)],
        ),
        SiteReportSection(
            site="dmproperties",
            run_id=102,
            changes=[ListingChange(ChangeType.PRICE_CHANGED, dm_current, previous=dm_previous)],
        ),
        SiteReportSection(
            site="panorama",
            run_id=103,
            changes=[ListingChange(ChangeType.REMOVED, panorama_removed)],
        ),
        SiteReportSection(site="homerun", run_id=104, changes=[]),
    ]
