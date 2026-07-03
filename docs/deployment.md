# Cloud Email Deployment

This setup runs the daily Market Report email in the cloud, so it keeps working while your computer is off.

The website/dashboard can be deployed later. For now, the cloud setup is email-only.

## What Runs In The Cloud

- One Render cron job: `real-estate-monitor scheduled-scrape`
- One PostgreSQL database to remember previous scrapes
- One combined Market Report email after the scrape finishes
- Docker-based Playwright browser support

The cron job is scheduled in UTC:

```yaml
schedule: "0 7 * * *"
```

That is 09:00 in Madrid during summer time. If you later want a different delivery time, update the cron schedule in `render.yaml`.

## Render Blueprint

The included `render.yaml` creates:

- `real-estate-monitor-market-report`
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

Check safe settings:

```bash
real-estate-monitor check-config
```

## Notes

- Keep Gmail app passwords private.
- `EMAIL_TO` accepts multiple addresses separated by commas.
- Use PostgreSQL in the cloud so the scraper can compare each run with previous runs.
- Render cron jobs are cheaper than an always-on worker for one daily email.
- The dashboard/web login work is intentionally left for later.
