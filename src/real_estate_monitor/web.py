from __future__ import annotations

import asyncio
import base64
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, sessionmaker

from real_estate_monitor.config import Settings
from real_estate_monitor.database import PropertyListing, ScrapeRun
from real_estate_monitor.diff import detect_changes
from real_estate_monitor.models import ChangeType, ListingChange, ListingSnapshot
from real_estate_monitor.runner import run_scrape
from real_estate_monitor.scrapers import available_sites, build_scraper

MADRID_TZ = timezone(timedelta(hours=2), "UTC+2")


@dataclass(frozen=True)
class SiteSummary:
    site: str
    latest_run_id: int | None
    latest_run_at: datetime | None
    listing_count: int
    change_count: int
    new_count: int
    removed_count: int
    price_count: int


@dataclass
class ScrapeJob:
    site: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    run_id: int | None = None
    change_count: int | None = None
    current_page: int | None = None
    total_pages: int | None = None
    listing_count: int = 0
    error: str | None = None


_JOBS: dict[str, ScrapeJob] = {}
_JOBS_LOCK = threading.Lock()


def serve_dashboard(
    session_factory: sessionmaker,
    settings: Settings,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    handler = _make_handler(session_factory, settings)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


def _make_handler(session_factory: sessionmaker, settings: Settings) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._send_json({"ok": True})
                return
            if not self._is_authorized():
                self._request_auth()
                return
            if path in {"", "/"}:
                self._send_html(_dashboard_page(session_factory))
                return
            if path == "/api/jobs":
                self._send_json(_jobs_payload())
                return
            if path.startswith("/sites/"):
                site = unquote(path.removeprefix("/sites/")).strip("/")
                query = parse_qs(urlparse(self.path).query)
                run_id = _int_or_none(query.get("run", [None])[0])
                self._send_html(_site_page(session_factory, site, run_id=run_id))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

        def do_POST(self) -> None:
            if not self._is_authorized():
                self._request_auth()
                return
            path = urlparse(self.path).path
            if path.startswith("/api/scrape/"):
                site = unquote(path.removeprefix("/api/scrape/")).strip("/")
                if site == "all":
                    for site_name in available_sites():
                        _start_scrape_job(site_name, settings, session_factory)
                    self._send_json({"ok": True, "site": "all"})
                    return
                if site not in available_sites():
                    self.send_error(HTTPStatus.NOT_FOUND, "Unknown site")
                    return
                started = _start_scrape_job(site, settings, session_factory)
                self._send_json({"ok": True, "site": site, "started": started})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, html: str) -> None:
            payload = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, data: object) -> None:
            payload = json.dumps(data).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _is_authorized(self) -> bool:
            if not settings.web_auth_enabled:
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                decoded = base64.b64decode(header.removeprefix("Basic ").strip()).decode("utf-8")
                username, password = decoded.split(":", 1)
            except Exception:
                return False
            return settings.valid_web_credentials(username, password)

        def _request_auth(self) -> None:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="Real Estate Monitor"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Login required")

    return DashboardHandler


def _dashboard_page(session_factory: sessionmaker) -> str:
    with session_factory() as session:
        summaries = _site_summaries(session)
    rows = "\n".join(_site_summary_row(summary) for summary in summaries)
    if not rows:
        rows = """
        <tr>
          <td colspan="8" class="empty">No scrape data yet. Run a scraper first.</td>
        </tr>
        """

    return _page(
        title="Dashboard",
        active_site=None,
        content=f"""
        <section class="page-head">
          <div>
            <p class="eyebrow">Real Estate Monitor</p>
            <h1>Market Intelligence Dashboard</h1>
          </div>
          <button class="button" type="button" data-scrape="all">Run All Scrapers</button>
        </section>

        <section class="job-strip" id="job-strip" hidden></section>

        <section class="panel">
          <div class="panel-head">
            <h2>Monitored Sites</h2>
            <span>{len(summaries)} site{'' if len(summaries) == 1 else 's'}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Site</th>
                  <th>Latest Scrape</th>
                  <th>Listings</th>
                  <th>Total Changes</th>
                  <th>New</th>
                  <th>Removed</th>
                  <th>Price</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {rows}
              </tbody>
            </table>
          </div>
        </section>
        """,
    )


def _site_page(session_factory: sessionmaker, site: str, run_id: int | None = None) -> str:
    with session_factory() as session:
        runs = _latest_runs(session, site, limit=5)
        selected_run = _selected_run(runs, run_id)
        summary = _site_summary(session, site, selected_run=selected_run)
        changes = _changes_for_run(session, site, selected_run)
    if selected_run is None:
        change_rows = '<tr><td colspan="4" class="empty">No runs found for this site.</td></tr>'
    elif not changes:
        change_rows = '<tr><td colspan="4" class="empty">No changes detected in the latest run.</td></tr>'
    else:
        change_rows = "\n".join(_change_row(change) for change in changes)
    run_buttons = _run_history_links(site, runs, selected_run)
    scrape_action = _scrape_action(site, primary=True)

    return _page(
        title=f"{site.title()} Changes",
        active_site=site,
        content=f"""
        <section class="page-head">
          <div>
            <p class="eyebrow">Latest Changes</p>
            <h1>{escape(_site_display_name(site))}</h1>
          </div>
          <div class="actions">
            {scrape_action}
            <a class="button secondary" href="/">All Sites</a>
          </div>
        </section>

        <section class="job-strip" id="job-strip" hidden></section>

        <section class="metrics">
          {_metric("Listings", summary.listing_count)}
          {_metric("Total Changes", summary.change_count)}
          {_metric("New", summary.new_count)}
          {_metric("Removed", summary.removed_count)}
          {_metric("Price Change", summary.price_count)}
        </section>

        <section class="history">
          <span>Previous runs</span>
          <div>{run_buttons}</div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>Latest Scrape</h2>
            <span>{_format_datetime(summary.latest_run_at)}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Change</th>
                  <th>Listing</th>
                  <th>Price</th>
                  <th>Previous</th>
                </tr>
              </thead>
              <tbody>
                {change_rows}
              </tbody>
            </table>
          </div>
        </section>
        """,
    )


def _site_summaries(session: Session) -> list[SiteSummary]:
    registered = set(available_sites())
    scraped = set(session.scalars(select(distinct(ScrapeRun.site))).all())
    return [_site_summary(session, site) for site in sorted(registered | scraped)]


def _site_summary(session: Session, site: str, selected_run: ScrapeRun | None = None) -> SiteSummary:
    if selected_run is None:
        latest = _latest_runs(session, site, limit=1)
        selected_run = latest[0] if latest else None
    changes = _changes_for_run(session, site, selected_run)
    counts = _change_counts(changes)
    listing_count = 0
    if selected_run:
        listing_count = session.scalar(
            select(func.count(PropertyListing.id)).where(PropertyListing.run_id == selected_run.id)
        ) or 0
    return SiteSummary(
        site=site,
        latest_run_id=selected_run.id if selected_run else None,
        latest_run_at=selected_run.finished_at if selected_run else None,
        listing_count=listing_count,
        change_count=len(changes),
        new_count=counts[ChangeType.NEW],
        removed_count=counts[ChangeType.REMOVED],
        price_count=counts[ChangeType.PRICE_CHANGED],
    )


def _latest_changes(session: Session, site: str) -> list[ListingChange]:
    runs = _latest_runs(session, site, limit=2)
    if not runs:
        return []
    return _changes_for_run(session, site, runs[0])


def _changes_for_run(session: Session, site: str, run: ScrapeRun | None) -> list[ListingChange]:
    if run is None:
        return []
    previous_run = session.scalar(
        select(ScrapeRun)
        .where(
            ScrapeRun.site == site,
            ScrapeRun.finished_at.is_not(None),
            ScrapeRun.id < run.id,
        )
        .order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )
    current = _snapshots_for_run(session, run.id)
    previous = _snapshots_for_run(session, previous_run.id) if previous_run else []
    return detect_changes(previous, current)


def _latest_runs(session: Session, site: str, limit: int) -> list[ScrapeRun]:
    return list(
        session.scalars(
            select(ScrapeRun)
            .where(ScrapeRun.site == site, ScrapeRun.finished_at.is_not(None))
            .order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
            .limit(limit)
        ).all()
    )


def _snapshots_for_run(session: Session, run_id: int) -> list[ListingSnapshot]:
    rows = session.scalars(select(PropertyListing).where(PropertyListing.run_id == run_id)).all()
    return [
        ListingSnapshot(
            site=row.site,
            external_id=row.external_id,
            url=row.url,
            title=row.title,
            location=row.location,
            price=row.price,
            currency=row.currency,
            beds=row.beds,
            baths=row.baths,
            built_area_m2=row.built_area_m2,
            plot_area_m2=row.plot_area_m2,
            scraped_at=row.scraped_at,
        )
        for row in rows
    ]


def _change_counts(changes: list[ListingChange]) -> dict[ChangeType, int]:
    return {
        ChangeType.NEW: sum(1 for change in changes if change.change_type == ChangeType.NEW),
        ChangeType.REMOVED: sum(1 for change in changes if change.change_type == ChangeType.REMOVED),
        ChangeType.PRICE_CHANGED: sum(1 for change in changes if change.change_type == ChangeType.PRICE_CHANGED),
    }


def _site_summary_row(summary: SiteSummary) -> str:
    action = _scrape_action(summary.site, primary=False)
    return f"""
    <tr>
      <td><a class="site-link" href="/sites/{escape(summary.site)}">{escape(_site_display_name(summary.site))}</a></td>
      <td>{escape(_format_datetime(summary.latest_run_at))}</td>
      <td>{summary.listing_count:,}</td>
      <td><strong>{summary.change_count:,}</strong></td>
      <td>{summary.new_count:,}</td>
      <td>{summary.removed_count:,}</td>
      <td>{summary.price_count:,}</td>
      <td>{action}</td>
    </tr>
    """


def _scrape_action(site: str, primary: bool) -> str:
    if site not in available_sites():
        return '<span class="muted">Unavailable</span>'
    class_name = "button" if primary else "table-action"
    label = "Run Scrape" if primary else "Run"
    return f'<button class="{class_name}" type="button" data-scrape="{escape(site)}">{label}</button>'


def _run_history_links(site: str, runs: list[ScrapeRun], selected_run: ScrapeRun | None) -> str:
    if not runs:
        return '<span class="muted">No previous runs yet</span>'
    selected_id = selected_run.id if selected_run else None
    return "\n".join(
        f'<a class="run-chip {"active" if run.id == selected_id else ""}" href="/sites/{escape(site)}?run={run.id}">{escape(_format_datetime(run.finished_at))}</a>'
        for run in runs
    )


def _change_row(change: ListingChange) -> str:
    listing = change.listing
    previous = change.previous
    current_price = _money(listing.price, listing.currency)
    previous_price = _money(previous.price, listing.currency) if previous else ""
    if change.change_type == ChangeType.REMOVED:
        current_price = ""
        previous_price = _money(listing.price, listing.currency)
    return f"""
    <tr>
      <td><span class="badge badge-{escape(change.change_type.value)}">{escape(_change_label(change.change_type))}</span></td>
      <td>
        <a class="listing-link" href="{escape(listing.url)}" target="_blank" rel="noreferrer">{escape(listing.external_id)}</a>
      </td>
      <td>{escape(current_price)}</td>
      <td>{escape(previous_price)}</td>
    </tr>
    """


def _page(title: str, active_site: str | None, content: str) -> str:
    nav_sites = "\n".join(
        f'<a class="{ "active" if site == active_site else "" }" href="/sites/{escape(site)}">{escape(_site_display_name(site))}</a>'
        for site in available_sites()
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)} · Drumelia Monitor</title>
    <style>{_CSS}</style>
  </head>
  <body>
    <aside class="sidebar">
      <a class="brand" href="/" aria-label="Dashboard home">
        <span class="brand-mark">D</span>
        <span>
          <strong>DRUMELIA</strong>
          <small>REAL ESTATE</small>
        </span>
      </a>
      <nav>
        <a class="{ "active" if active_site is None else "" }" href="/">Dashboard</a>
        {nav_sites}
      </nav>
    </aside>
    <main>
      {content}
    </main>
    <script>{_JS}</script>
  </body>
</html>"""


def _metric(label: str, value: int) -> str:
    return f"""
    <div class="metric">
      <span>{escape(label)}</span>
      <strong>{value:,}</strong>
    </div>
    """


def _money(value: int | None, currency: str) -> str:
    if value is None:
        return "POA"
    symbol = "€" if currency == "EUR" else currency
    return f"{symbol}{value:,}"


def _format_datetime(finished_at: datetime | None) -> str:
    if finished_at is None:
        return "No runs yet"
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return finished_at.astimezone(MADRID_TZ).strftime("%d %b %Y, %H:%M")


def _selected_run(runs: list[ScrapeRun], run_id: int | None) -> ScrapeRun | None:
    if not runs:
        return None
    if run_id is None:
        return runs[0]
    return next((run for run in runs if run.id == run_id), runs[0])


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _change_label(change_type: ChangeType) -> str:
    if change_type == ChangeType.PRICE_CHANGED:
        return "Price Change"
    return change_type.value.replace("_", " ").title()


def _location_suffix(location: str | None) -> str:
    if not location:
        return ""
    return f" · {escape(location)}"


def _site_display_name(site: str) -> str:
    names = {
        "dmproperties": "DM Properties",
        "marbella_ev": "Marbella EV",
    }
    return names.get(site, site.replace("_", " ").title())


def _start_scrape_job(site: str, settings: Settings, session_factory: sessionmaker) -> bool:
    with _JOBS_LOCK:
        existing = _JOBS.get(site)
        if existing and existing.status == "running":
            return False
        _JOBS[site] = ScrapeJob(site=site, status="running", started_at=datetime.now(timezone.utc))

    thread = threading.Thread(
        target=_run_scrape_job,
        args=(site, settings, session_factory),
        daemon=True,
    )
    thread.start()
    return True


def _run_scrape_job(site: str, settings: Settings, session_factory: sessionmaker) -> None:
    try:
        scraper = build_scraper(site, settings)
        scraper.progress_callback = _update_job_progress
        run_id, change_count = asyncio.run(
            run_scrape(scraper, settings, session_factory, send_notifications=True)
        )
        with _JOBS_LOCK:
            _JOBS[site] = ScrapeJob(
                site=site,
                status="done",
                started_at=_JOBS[site].started_at,
                finished_at=datetime.now(timezone.utc),
                run_id=run_id,
                change_count=change_count,
                current_page=_JOBS[site].current_page,
                total_pages=_JOBS[site].total_pages,
                listing_count=_JOBS[site].listing_count,
            )
    except Exception as exc:
        with _JOBS_LOCK:
            _JOBS[site] = ScrapeJob(
                site=site,
                status="error",
                started_at=_JOBS.get(site, ScrapeJob(site, "error", datetime.now(timezone.utc))).started_at,
                finished_at=datetime.now(timezone.utc),
                error=str(exc),
            )


def _update_job_progress(site: str, current_page: int | None, total_pages: int | None, listing_count: int) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(site)
        if not job:
            return
        job.current_page = current_page
        job.total_pages = total_pages
        job.listing_count = listing_count


def _jobs_payload() -> dict[str, object]:
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    return {
        "jobs": [
            {
                "site": job.site,
                "siteName": _site_display_name(job.site),
                "status": job.status,
                "startedAt": _format_datetime(job.started_at),
                "finishedAt": _format_datetime(job.finished_at),
                "runId": job.run_id,
                "changeCount": job.change_count,
                "currentPage": job.current_page,
                "totalPages": job.total_pages,
                "listingCount": job.listing_count,
                "percent": _job_percent(job),
                "error": job.error,
            }
            for job in jobs
        ]
    }


def _job_percent(job: ScrapeJob) -> int | None:
    if not job.current_page or not job.total_pages:
        return None
    return max(0, min(100, round((job.current_page / job.total_pages) * 100)))


_CSS = """
:root {
  --space-gray: #181818;
  --beige: #C7AF87;
  --terracotta: #84442E;
  --dark-terracotta: #773B26;
  --dark-gray: #8A857F;
  --hover-gray: #E2E2E2;
  --light-gray: #F9F9F9;
  --secondary-gray: #F7F7F7;
  --white: #FFFFFF;
  --line: #E7E1D8;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-height: 100vh;
  display: grid;
  grid-template-columns: 248px 1fr;
  background: var(--light-gray);
  color: var(--space-gray);
  font-family: "Futura PT", Futura, "Avenir Next", Arial, sans-serif;
}

.sidebar {
  min-height: 100vh;
  background: var(--space-gray);
  color: var(--white);
  padding: 28px 22px;
  position: sticky;
  top: 0;
}

.brand {
  color: var(--white);
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 38px;
}

.brand-mark {
  width: 40px;
  height: 40px;
  border: 1px solid var(--beige);
  display: grid;
  place-items: center;
  color: var(--beige);
  font-size: 19px;
}

.brand strong {
  display: block;
  font-size: 15px;
  letter-spacing: .18em;
}

.brand small {
  display: block;
  margin-top: 3px;
  color: var(--beige);
  font-size: 10px;
  letter-spacing: .22em;
}

nav {
  display: grid;
  gap: 4px;
}

nav a {
  color: #d9d2c7;
  text-decoration: none;
  padding: 11px 12px;
  font-size: 13px;
  letter-spacing: .07em;
  text-transform: uppercase;
  border-left: 2px solid transparent;
}

nav a:hover,
nav a.active {
  color: var(--white);
  background: rgba(199, 175, 135, .09);
  border-left-color: var(--beige);
}

main {
  padding: 34px;
  min-width: 0;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 20px;
  margin-bottom: 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--dark-gray);
  font-size: 12px;
  letter-spacing: .15em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.1;
  font-weight: 500;
}

h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 500;
}

.button {
  background: transparent;
  color: var(--space-gray);
  text-decoration: none;
  border: 1px solid var(--space-gray);
  padding: 10px 14px;
  font-size: 12px;
  letter-spacing: .11em;
  text-transform: uppercase;
  cursor: pointer;
  font: inherit;
}

.button:hover {
  background: var(--space-gray);
  color: var(--white);
}

.button.secondary {
  border-color: var(--line);
  color: var(--dark-gray);
}

.button[disabled],
.table-action[disabled] {
  opacity: .55;
  cursor: wait;
}

.actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.table-action {
  background: var(--space-gray);
  color: var(--white);
  border: 1px solid var(--space-gray);
  padding: 7px 10px;
  font-size: 11px;
  letter-spacing: .1em;
  text-transform: uppercase;
  cursor: pointer;
}

.table-action:hover {
  background: var(--terracotta);
  border-color: var(--terracotta);
}

.job-strip {
  display: grid;
  gap: 10px;
  margin-bottom: 22px;
}

.job-strip[hidden] {
  display: none;
}

.job-card {
  background: var(--white);
  border: 1px solid var(--line);
  padding: 14px 16px;
}

.job-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}

.job-title {
  font-size: 13px;
  letter-spacing: .11em;
  text-transform: uppercase;
}

.job-detail {
  margin-top: 4px;
  color: var(--dark-gray);
  font-size: 12px;
}

.progress {
  height: 3px;
  overflow: hidden;
  background: var(--hover-gray);
  margin-top: 12px;
}

.progress span {
  display: block;
  width: var(--progress-width, 34%);
  height: 100%;
  background: var(--beige);
}

.progress.indeterminate span {
  animation: loading 1.1s ease-in-out infinite;
}

@keyframes loading {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(300%); }
}

.history {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 22px;
  padding: 14px 16px;
  background: var(--white);
  border: 1px solid var(--line);
}

.history > span {
  color: var(--dark-gray);
  font-size: 12px;
  letter-spacing: .12em;
  text-transform: uppercase;
  white-space: nowrap;
}

.history > div {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.run-chip {
  color: var(--space-gray);
  text-decoration: none;
  border: 1px solid var(--line);
  padding: 7px 10px;
  font-size: 12px;
}

.run-chip:hover,
.run-chip.active {
  border-color: var(--beige);
  background: #fbf7ef;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 22px;
}

.metric,
.panel {
  background: var(--white);
  border: 1px solid var(--line);
}

.metric {
  padding: 16px;
}

.metric span {
  display: block;
  color: var(--dark-gray);
  font-size: 12px;
  letter-spacing: .11em;
  text-transform: uppercase;
}

.metric strong {
  display: block;
  margin-top: 8px;
  font-size: 26px;
  font-weight: 500;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--line);
}

.panel-head span {
  color: var(--dark-gray);
  font-size: 13px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th {
  text-align: left;
  background: var(--secondary-gray);
  color: var(--dark-gray);
  font-size: 11px;
  letter-spacing: .12em;
  text-transform: uppercase;
  font-weight: 500;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

td {
  padding: 14px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  font-size: 14px;
}

tr:hover td {
  background: #fcfbf8;
}

.site-link,
.listing-link {
  color: var(--space-gray);
  text-decoration: none;
}

.site-link:hover,
.listing-link:hover {
  color: var(--terracotta);
}

.muted {
  margin-top: 5px;
  color: var(--dark-gray);
  font-size: 12px;
}

.empty {
  color: var(--dark-gray);
  padding: 28px 14px;
}

.badge {
  display: inline-block;
  min-width: 70px;
  text-align: center;
  padding: 5px 8px;
  border: 1px solid var(--line);
  font-size: 11px;
  letter-spacing: .09em;
  text-transform: uppercase;
  color: var(--space-gray);
  background: var(--white);
}

.badge-new {
  border-color: var(--beige);
  background: #fbf7ef;
}

.badge-removed {
  border-color: #d8c2b8;
  background: #fbf3ef;
  color: var(--dark-terracotta);
}

.badge-price_changed {
  border-color: var(--dark-gray);
  background: #f2f2f2;
}

@media (max-width: 900px) {
  body {
    grid-template-columns: 1fr;
  }

  .sidebar {
    min-height: auto;
    position: static;
  }

  nav {
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  }

  main {
    padding: 22px;
  }

  .page-head {
    align-items: start;
    flex-direction: column;
  }

  .metrics {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
"""


_JS = """
const jobStrip = document.getElementById('job-strip');
let pollTimer = null;

function setButtonsDisabled(disabled) {
  document.querySelectorAll('[data-scrape]').forEach((button) => {
    button.disabled = disabled && button.dataset.scrape !== undefined;
  });
}

function jobMarkup(job) {
  const running = job.status === 'running';
  const done = job.status === 'done';
  const hasPercent = Number.isFinite(job.percent);
  const progressText = running && job.currentPage && job.totalPages
    ? `Page ${job.currentPage} of ${job.totalPages} · ${job.listingCount || 0} listings found`
    : running
      ? `${job.listingCount || 0} listings found`
      : '';
  const statusText = running
    ? `Scraping in progress${progressText ? ` · ${progressText}` : ''}`
    : done
      ? `Finished. ${job.changeCount ?? 0} changes detected.`
      : `Failed: ${job.error || 'Unknown error'}`;
  const progressStyle = hasPercent ? `style="--progress-width:${job.percent}%"` : '';
  return `
    <div class="job-card">
      <div class="job-row">
        <div>
          <div class="job-title">${job.siteName}</div>
          <div class="job-detail">${statusText}</div>
        </div>
        <div class="job-detail">${running ? job.startedAt : job.finishedAt}</div>
      </div>
      ${running ? `<div class="progress ${hasPercent ? '' : 'indeterminate'}" ${progressStyle}><span></span></div>` : ''}
    </div>
  `;
}

async function refreshJobs() {
  const response = await fetch('/api/jobs');
  const data = await response.json();
  const activeJobs = data.jobs.filter((job) => job.status === 'running');
  const visibleJobs = data.jobs.filter((job) => job.status === 'running' || job.status === 'error');
  if (visibleJobs.length) {
    jobStrip.hidden = false;
    jobStrip.innerHTML = visibleJobs.map(jobMarkup).join('');
  } else {
    jobStrip.hidden = true;
    jobStrip.innerHTML = '';
  }
  setButtonsDisabled(activeJobs.length > 0);
  if (!activeJobs.length && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
    window.location.reload();
  }
}

async function startScrape(site) {
  setButtonsDisabled(true);
  jobStrip.hidden = false;
  jobStrip.innerHTML = `
    <div class="job-card">
      <div class="job-title">Starting scrape</div>
      <div class="job-detail">Preparing ${site}...</div>
      <div class="progress indeterminate"><span></span></div>
    </div>
  `;
  await fetch(`/api/scrape/${encodeURIComponent(site)}`, { method: 'POST' });
  await refreshJobs();
  if (!pollTimer) {
    pollTimer = setInterval(refreshJobs, 2000);
  }
}

document.querySelectorAll('[data-scrape]').forEach((button) => {
  button.addEventListener('click', () => startScrape(button.dataset.scrape));
});

refreshJobs();
"""
