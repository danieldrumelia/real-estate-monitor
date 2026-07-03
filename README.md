# real-estate-monitor

Python project for monitoring real estate listing websites.

Each website scraper implements the same interface, so portals can be added without changing the persistence, diffing, reporting, dashboard, or notification layers.

## Features

- Playwright-based scraping.
- One scraper module per website.
- SQLite storage with SQLAlchemy.
- Run-to-run detection for new listings, removed listings, and price changes.
- Markdown reports.
- Optional email, Telegram, and WhatsApp notifications.
- Daily cloud cron job for automatic morning scrapes.
- Comma-separated team email recipients.
- Optional dashboard login for hosted/private access.
- `.env` configuration, logging, retries, type hints, and dataclass models.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
```

## Run

```bash
real-estate-monitor scrape solvilla
real-estate-monitor scrape all
real-estate-monitor scheduled-scrape
real-estate-monitor check-config
```

Useful options:

```bash
real-estate-monitor scrape solvilla --max-pages 3
real-estate-monitor scrape solvilla --no-notifications
real-estate-monitor list-sites
real-estate-monitor check-config
```

Reports are written to the configured `REPORT_DIR`.

By default, scrapers follow pagination until there are no more pages. `SCRAPER_MAX_PAGES=0` means all pages.

`scheduled-scrape` is the command to use from a cloud cron job. It scrapes every active site once, sends email reports, continues if one site fails, and emails a failure summary if needed.

For a server that stays online all day, use:

```bash
real-estate-monitor scheduler
```

Set the daily time with:

```bash
SCRAPE_SCHEDULE_TIME=09:00
SCRAPE_SCHEDULE_TIMEZONE=Europe/Madrid
```

Registered sites:

- `solvilla`
- `homerun`
- `dmproperties`
- `panorama`
- `marbella_ev`

## Web Dashboard

Start the internal dashboard:

```bash
real-estate-monitor web
```

Then open:

```text
http://127.0.0.1:8000
```

The dashboard shows all monitored sites, latest scrape counts, and the latest detected changes per site.

For a hosted dashboard, enable login:

```bash
WEB_AUTH_ENABLED=true
WEB_USERNAME=drumelia
WEB_PASSWORD=your_private_password
```

## WhatsApp Notifications

Reports can be sent through Meta WhatsApp Cloud API. Add these values to `.env`:

```bash
WHATSAPP_ENABLED=true
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_whatsapp_phone_number_id
WHATSAPP_RECIPIENT=recipient_number_in_international_format
WHATSAPP_GRAPH_API_VERSION=v20.0
```

Example recipient format:

```bash
WHATSAPP_RECIPIENT=34600111222
```

Run the scraper normally:

```bash
real-estate-monitor scrape solvilla
```

Notifications are only sent when changes are detected.

## Email Notifications

Reports can be sent through any SMTP provider. Add these values to `.env`:

```bash
EMAIL_ENABLED=true
EMAIL_SMTP_HOST=smtp.office365.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=daniel@drumelia.com
EMAIL_PASSWORD=your_outlook_password_or_app_password
EMAIL_FROM=daniel@drumelia.com
EMAIL_TO=daniel@drumelia.com,person2@drumelia.com,person3@drumelia.com
EMAIL_USE_TLS=true
```

For Microsoft 365/Outlook, use `smtp.office365.com`, port `587`, and TLS enabled. Some work accounts require SMTP AUTH to be enabled by the Microsoft 365 administrator.
Multiple recipients can be separated with commas:

```bash
EMAIL_TO=one@example.com,two@example.com
```

The report is sent after every scrape as a formatted HTML email.

## Running While Your Computer Is Off

To run while your Mac is off, deploy the project to a cloud service with:

- a daily cron job for the Market Report email,
- a hosted PostgreSQL database,
- the included Dockerfile for Playwright browser support.

See `docs/deployment.md` for the production email setup.

The included `render.yaml` can be used as a Render blueprint for the hosted email cron job and PostgreSQL database.

## Add Another Website

Create a module under `src/real_estate_monitor/scrapers/` and implement `PropertyScraper`.

```python
from real_estate_monitor.models import ListingSnapshot
from real_estate_monitor.scrapers.base import PropertyScraper

class ExampleScraper(PropertyScraper):
    site_name = "example"

    async def scrape(self) -> list[ListingSnapshot]:
        ...
```

Then register it in `src/real_estate_monitor/scrapers/__init__.py`.
