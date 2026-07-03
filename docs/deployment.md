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
schedule: "12 10 * * *"
```

That is 12:12 in Madrid during summer time. If you later want a different delivery time, update the cron schedule in `render.yaml`.

## Render Blueprint

The included `render.yaml` creates:

- `real-estate-monitor-market-report`
- `real-estate-monitor-db` on the `basic-256mb` Postgres plan

When Render asks for private values, fill in:

```bash
EMAIL_USERNAME=daniel@drumelia.com
EMAIL_PASSWORD=your_outlook_password_or_app_password
EMAIL_FROM=daniel@drumelia.com
EMAIL_TO=daniel@drumelia.com
```

Later, add the team by changing `EMAIL_TO`:

```bash
EMAIL_TO=daniel@drumelia.com,person2@drumelia.com,person3@drumelia.com
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

- For Microsoft 365/Outlook sending, use `smtp.office365.com`, port `587`, and TLS enabled.
- Some Microsoft 365 accounts require SMTP AUTH to be enabled by the administrator.
- Keep email passwords and app passwords private.
- `EMAIL_TO` accepts multiple addresses separated by commas.
- Use PostgreSQL in the cloud so the scraper can compare each run with previous runs.
- Render cron jobs are cheaper than an always-on worker for one daily email.
- The cron job uses the `standard` plan because Playwright/Chromium can exceed the 512 MB starter limit.
- Render's old `starter` Postgres plan is no longer available for new databases.
- The dashboard/web login work is intentionally left for later.
