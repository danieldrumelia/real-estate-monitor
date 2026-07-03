from real_estate_monitor.scrapers.dmproperties import DMPropertiesScraper
from real_estate_monitor.scrapers.generic_agency import _extract_price


def test_dmproperties_accepts_dmco_references() -> None:
    scraper = DMPropertiesScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    external_id = scraper._external_id(
        "https://www.dmproperties.com/property/marbella-all/puerto-banus/apartments/DMCO2953",
        "",
    )

    assert external_id == "DMCO2953"


def test_price_parser_stops_before_bedroom_count() -> None:
    assert _extract_price("€375,000 2 beds · 2 baths · 100 m2 built") == 375000


def test_dmproperties_can_parse_reference_with_missing_title() -> None:
    scraper = DMPropertiesScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshot = scraper._parse_item(
        {
            "url": "https://www.dmproperties.com/property/marbella-all/villas/DM5450",
            "title": "",
            "cleanTitle": "",
            "text": "€2,500,000 DM5450 Save",
            "image": None,
        }
    )

    assert snapshot is not None
    assert snapshot.external_id == "DM5450"
    assert snapshot.title == "DM5450"
