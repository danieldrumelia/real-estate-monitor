from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    report_dir: Path
    log_level: str
    scraper_headless: bool
    scraper_timeout_ms: int
    scraper_max_pages: int
    scraper_retries: int
    scraper_min_listing_ratio: float
    scraper_max_removals_per_run: int
    telegram_enabled: bool
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    whatsapp_enabled: bool
    whatsapp_access_token: str | None
    whatsapp_phone_number_id: str | None
    whatsapp_recipient: str | None
    whatsapp_graph_api_version: str
    email_enabled: bool
    email_smtp_host: str | None
    email_smtp_port: int
    email_username: str | None
    email_password: str | None
    email_from: str | None
    email_to: str | None
    email_use_tls: bool
    scrape_schedule_time: str
    scrape_schedule_timezone: str
    web_auth_enabled: bool
    web_username: str | None
    web_password: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/real_estate_monitor.db"),
            report_dir=Path(os.getenv("REPORT_DIR", "reports")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            scraper_headless=_bool(os.getenv("SCRAPER_HEADLESS"), True),
            scraper_timeout_ms=int(os.getenv("SCRAPER_TIMEOUT_MS", "30000")),
            scraper_max_pages=int(os.getenv("SCRAPER_MAX_PAGES", "0")),
            scraper_retries=int(os.getenv("SCRAPER_RETRIES", "3")),
            scraper_min_listing_ratio=float(os.getenv("SCRAPER_MIN_LISTING_RATIO", "0.85")),
            scraper_max_removals_per_run=int(os.getenv("SCRAPER_MAX_REMOVALS_PER_RUN", "10")),
            telegram_enabled=_bool(os.getenv("TELEGRAM_ENABLED"), False),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            whatsapp_enabled=_bool(os.getenv("WHATSAPP_ENABLED"), False),
            whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN") or None,
            whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID") or None,
            whatsapp_recipient=os.getenv("WHATSAPP_RECIPIENT") or None,
            whatsapp_graph_api_version=os.getenv("WHATSAPP_GRAPH_API_VERSION", "v20.0"),
            email_enabled=_bool(os.getenv("EMAIL_ENABLED"), False),
            email_smtp_host=os.getenv("EMAIL_SMTP_HOST") or None,
            email_smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "587")),
            email_username=os.getenv("EMAIL_USERNAME") or None,
            email_password=os.getenv("EMAIL_PASSWORD") or None,
            email_from=os.getenv("EMAIL_FROM") or None,
            email_to=os.getenv("EMAIL_TO") or None,
            email_use_tls=_bool(os.getenv("EMAIL_USE_TLS"), True),
            scrape_schedule_time=os.getenv("SCRAPE_SCHEDULE_TIME", "09:00"),
            scrape_schedule_timezone=os.getenv("SCRAPE_SCHEDULE_TIMEZONE", "Europe/Madrid"),
            web_auth_enabled=_bool(os.getenv("WEB_AUTH_ENABLED"), False),
            web_username=os.getenv("WEB_USERNAME") or None,
            web_password=os.getenv("WEB_PASSWORD") or None,
        )

    @property
    def email_recipients(self) -> List[str]:
        if not self.email_to:
            return []
        return [item.strip() for item in self.email_to.split(",") if item.strip()]

    def valid_web_credentials(self, username: str, password: str) -> bool:
        if not self.web_auth_enabled:
            return True
        if not self.web_username or not self.web_password:
            return False
        return secrets.compare_digest(username, self.web_username) and secrets.compare_digest(
            password,
            self.web_password,
        )
