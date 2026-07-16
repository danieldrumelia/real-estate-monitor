from real_estate_monitor.scrapers.solvilla import _has_safe_listing_count


def test_solvilla_accepts_missing_overestimated_page_when_count_is_safe() -> None:
    assert _has_safe_listing_count(345, 358)


def test_solvilla_rejects_missing_page_when_count_is_too_low() -> None:
    assert not _has_safe_listing_count(250, 358)
