from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.orm import sessionmaker

from real_estate_monitor.config import Settings
from real_estate_monitor.models import ListingChange
from real_estate_monitor.notify import EmailNotifier
from real_estate_monitor.report import (
    SiteReportSection,
    build_combined_html_email_report,
    build_combined_markdown_report,
)
from real_estate_monitor.runner import run_scrape_details
from real_estate_monitor.scrapers import available_sites, build_scraper

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteRunResult:
    site: str
    run_id: int | None
    change_count: int | None
    changes: list[ListingChange]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


async def run_all_sites_once(
    settings: Settings,
    session_factory: sessionmaker,
    *,
    send_notifications: bool = True,
) -> list[SiteRunResult]:
    results: list[SiteRunResult] = []
    for site in available_sites():
        try:
            scraper = build_scraper(site, settings)
            run_id, changes = await run_scrape_details(
                scraper,
                settings,
                session_factory,
                send_notifications=False,
            )
            results.append(SiteRunResult(site=site, run_id=run_id, change_count=len(changes), changes=changes))
        except Exception as exc:
            logger.exception("Scrape failed for %s", site)
            results.append(SiteRunResult(site=site, run_id=None, change_count=None, changes=[], error=str(exc)))

    if send_notifications:
        sections = [
            SiteReportSection(
                site=result.site,
                run_id=result.run_id,
                changes=result.changes,
                error=result.error,
            )
            for result in results
        ]
        markdown = build_combined_markdown_report(sections)
        html = build_combined_html_email_report(sections)
        await EmailNotifier(settings).send(
            "Market Report",
            markdown,
            html=html,
        )
    return results


async def run_daily_scheduler(settings: Settings, session_factory: sessionmaker) -> None:
    timezone = ZoneInfo(settings.scrape_schedule_timezone)
    logger.info(
        "Daily scheduler started for %s %s",
        settings.scrape_schedule_time,
        settings.scrape_schedule_timezone,
    )
    while True:
        next_run = _next_run_at(settings.scrape_schedule_time, timezone)
        wait_seconds = max(0.0, (next_run - datetime.now(timezone)).total_seconds())
        logger.info("Next scrape is scheduled for %s", next_run.isoformat())
        await asyncio.sleep(wait_seconds)
        await run_all_sites_once(settings, session_factory, send_notifications=True)


def _next_run_at(time_value: str, timezone: ZoneInfo) -> datetime:
    hour, minute = _parse_time(time_value)
    now = datetime.now(timezone)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _parse_time(time_value: str) -> tuple[int, int]:
    parts = time_value.split(":", 1)
    if len(parts) != 2:
        raise ValueError("SCRAPE_SCHEDULE_TIME must use HH:MM format, for example 09:00")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("SCRAPE_SCHEDULE_TIME must be a valid 24-hour time")
    return hour, minute


def _failure_text(results: list[SiteRunResult]) -> str:
    lines = ["# Real Estate Monitor Failures", ""]
    for result in results:
        if result.ok:
            continue
        lines.append(f"- {result.site}: {result.error}")
    lines.append("")
    return "\n".join(lines)


def _failure_html(results: list[SiteRunResult]) -> str:
    rows = "\n".join(
        f"<tr><td style='padding:10px;border-bottom:1px solid #e5e7eb;'>{escape(result.site)}</td>"
        f"<td style='padding:10px;border-bottom:1px solid #e5e7eb;'>{escape(result.error or '')}</td></tr>"
        for result in results
        if not result.ok
    )
    return f"""<!doctype html>
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <h1>Real Estate Monitor Failures</h1>
    <p>One or more scheduled scrapes failed.</p>
    <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;">
      <thead>
        <tr style="background:#f8fafc;">
          <th align="left" style="padding:10px;border-bottom:1px solid #e5e7eb;">Site</th>
          <th align="left" style="padding:10px;border-bottom:1px solid #e5e7eb;">Error</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </body>
</html>"""
