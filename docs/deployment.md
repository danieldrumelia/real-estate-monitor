# Cloud Email Deployment

This setup runs the daily Market Report email in the cloud, so it keeps working while your computer is off.

The website/dashboard can be deployed later. For now, the cloud setup is email-only.

## What Runs In The Cloud

- One always-on worker: `real-estate-monitor scheduler`
- One PostgreSQL database to remember previous scrapes
- One daily Market Report email after the scrape finishes
- Docker-based Playwright browser support

The worker uses:

```bash
SCRAPE_SCHEDULE_TIME=09:00
SCRAPE_SCHEDULE_TIMEZONE=Europe/Madrid
```

You can change `SCRAPE_SCHEDULE_TIME` later when you choose the final morning time.

## Render Blueprint

The included `render.yaml` creates:

- `real-estate-monitor-email-worker`
- `real-estate-monitor-db`

When Render asks for private values, fill in:

```bash
EMAIL_USERNAME=danieldrumelia@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_FROM=danieldrumelia@gmail.com
EMAIL_TO=danieldrumelia@gmail.com
```

Later, add the team by changing `EMAIL_TO`:

```bash
EMAIL_TO=danieldrumelia@gmail.com,person2@drumelia.com,person3@drumelia.com
```

## Required Environment Variables

Most are already in `render.yaml`. These private values must be added in Render:

```bash
EMAIL_USERNAME=
EMAIL_PASSWORD=
EMAIL_FROM=
EMAIL_TO=
```

The database is connected automatically by the blueprint.

## Useful Commands

Run one full scrape and send one combined Market Report:

```bash
real-estate-monitor scheduled-scrape
```

Run the daily cloud worker:

```bash
real-estate-monitor scheduler
```

Check safe settings:

```bash
real-estate-monitor check-config
```

## Notes

- Keep Gmail app passwords private.
- `EMAIL_TO` accepts multiple addresses separated by commas.
- Use PostgreSQL in the cloud so the scraper can compare each run with previous runs.
- The dashboard/web login work is intentionally left for later.
