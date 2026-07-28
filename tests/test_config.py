from real_estate_monitor.config import parse_email_recipients


def test_parse_email_recipients_accepts_common_separators() -> None:
    value = "daniel@drumelia.com; Artur <artur@drumelia.com>,\n s.fluchaire@aionics.ai"

    assert parse_email_recipients(value) == [
        "daniel@drumelia.com",
        "artur@drumelia.com",
        "s.fluchaire@aionics.ai",
    ]
