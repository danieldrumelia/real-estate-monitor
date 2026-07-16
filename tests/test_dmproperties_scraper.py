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


def test_dmproperties_development_unit_uses_unit_price_and_parent_title() -> None:
    scraper = DMPropertiesScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshot = scraper._parse_item(
        {
            "url": "https://www.dmproperties.com/property/san-pedro-de-alcantara/cortijo-blanco/villas/DMD1606-03",
            "title": "€4,139,500 4 beds · 5 baths · 792 m2 built ›",
            "cleanTitle": "Cortijo Blanco, Exclusive villas just steps from the sea and Puerto Banús",
            "text": "€4,139,500\n4 beds · 5 baths · 792 m2 built\n›\nDMD1606-03",
            "image": None,
        }
    )

    assert snapshot is not None
    assert snapshot.external_id == "DMD1606-03"
    assert snapshot.title == "Cortijo Blanco, Exclusive villas just steps from the sea and Puerto Banús"
    assert snapshot.price == 4_139_500
    assert snapshot.beds == 4
    assert snapshot.baths == 5
    assert snapshot.built_area_m2 == 792


def test_dmproperties_development_unit_does_not_inherit_first_unit_price() -> None:
    scraper = DMPropertiesScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshot = scraper._parse_item(
        {
            "url": "https://www.dmproperties.com/property/marbella-all/villas/DMD1641-02",
            "title": "€3,150,000 4 beds · 4 baths · 325 m2 built ›",
            "cleanTitle": "New villas in a gated Marbella development",
            "text": "€3,150,000\n4 beds · 4 baths · 325 m2 built\n›\nDMD1641-02",
            "image": None,
        }
    )

    assert snapshot is not None
    assert snapshot.external_id == "DMD1641-02"
    assert snapshot.title == "New villas in a gated Marbella development"
    assert snapshot.price == 3_150_000


def test_dmproperties_price_row_title_falls_back_to_reference() -> None:
    scraper = DMPropertiesScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshot = scraper._parse_item(
        {
            "url": "https://www.dmproperties.com/property/marbella-all/villas/DMD1586-03",
            "title": "€1,493,000 4 beds · 2 baths · 183 m2 built ›",
            "cleanTitle": "",
            "text": "€1,493,000\n4 beds · 2 baths · 183 m2 built\n›\nDMD1586-03",
            "image": None,
        }
    )

    assert snapshot is not None
    assert snapshot.title == "DMD1586-03"
    assert snapshot.price == 1_493_000


def test_dmproperties_sold_unit_uses_parent_development_title() -> None:
    scraper = DMPropertiesScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshot = scraper._parse_item(
        {
            "url": "https://www.dmproperties.com/property/san-pedro-de-alcantara/s-pedro-centro/apartments/DMD1552-01",
            "title": "Sold 3 beds · 2 baths · 172 m2 built ›",
            "cleanTitle": "S. Pedro Centro, Thirty five modern apartments in the heart of San Pedro",
            "text": "Sold\n3 beds · 2 baths · 172 m2 built\n›\nDMD1552-01",
            "image": None,
        }
    )

    assert snapshot is not None
    assert snapshot.external_id == "DMD1552-01"
    assert snapshot.title == "S. Pedro Centro, Thirty five modern apartments in the heart of San Pedro"
