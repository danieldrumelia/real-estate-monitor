from __future__ import annotations

import asyncio
from types import SimpleNamespace

from real_estate_monitor.notify import EmailNotifier


def test_email_notifier_sends_one_message_per_recipient(monkeypatch) -> None:
    sent_to: list[list[str]] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def starttls(self) -> None:
            pass

        def login(self, username: str, password: str) -> None:
            pass

        def send_message(self, message, *, from_addr: str, to_addrs: list[str]):
            sent_to.append(to_addrs)
            return {}

    monkeypatch.setattr("real_estate_monitor.notify.smtplib.SMTP", FakeSMTP)
    settings = SimpleNamespace(
        email_enabled=True,
        email_smtp_host="smtp.example.com",
        email_smtp_port=587,
        email_username="sender@example.com",
        email_password="password",
        email_from="sender@example.com",
        email_recipients=["one@example.com", "two@example.com"],
        email_use_tls=True,
    )

    asyncio.run(EmailNotifier(settings).send("Subject", "Text", html="<p>Text</p>"))

    assert sent_to == [["one@example.com"], ["two@example.com"]]
