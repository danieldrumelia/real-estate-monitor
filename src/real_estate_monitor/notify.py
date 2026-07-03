from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx

from real_estate_monitor.config import Settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.telegram_enabled
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    async def send(self, text: str) -> None:
        if not self.enabled:
            logger.info("Telegram notifications disabled")
            return
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram is enabled but token or chat id is missing")
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text[:3900],
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()


class EmailNotifier:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.email_enabled
        self.smtp_host = settings.email_smtp_host
        self.smtp_port = settings.email_smtp_port
        self.username = settings.email_username
        self.password = settings.email_password
        self.sender = settings.email_from or settings.email_username
        self.recipients = settings.email_recipients
        self.use_tls = settings.email_use_tls

    async def send(
        self,
        subject: str,
        text: str,
        html: str | None = None,
        attachment_name: str = "report.md",
    ) -> None:
        if not self.enabled:
            logger.info("Email notifications disabled")
            return
        if not self.smtp_host or not self.sender or not self.recipients:
            logger.warning("Email is enabled but SMTP host, sender, or recipients are missing")
            return

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        message.add_attachment(
            text.encode("utf-8"),
            maintype="text",
            subtype="markdown",
            filename=attachment_name,
        )
        await asyncio.to_thread(self._send_message, message)

    def _send_message(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username and self.password:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


class WhatsAppNotifier:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.whatsapp_enabled
        self.access_token = settings.whatsapp_access_token
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.recipient = settings.whatsapp_recipient
        self.graph_api_version = settings.whatsapp_graph_api_version

    async def send(self, text: str) -> None:
        if not self.enabled:
            logger.info("WhatsApp notifications disabled")
            return
        if not self.access_token or not self.phone_number_id or not self.recipient:
            logger.warning("WhatsApp is enabled but token, phone number id, or recipient is missing")
            return

        url = f"https://graph.facebook.com/{self.graph_api_version}/{self.phone_number_id}/messages"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": self.recipient,
                    "type": "text",
                    "text": {
                        "preview_url": False,
                        "body": text[:3900],
                    },
                },
            )
            response.raise_for_status()


def _split_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
