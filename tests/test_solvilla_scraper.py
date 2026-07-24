from real_estate_monitor.scrapers.solvilla import (
    SolvillaScraper,
    _has_safe_listing_count,
    _parse_solvilla_html_items,
)


def test_solvilla_accepts_pv_references() -> None:
    scraper = SolvillaScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    external_id = scraper._external_id(
        "https://www.solvilla.es/properties/san-pedro-de-alcantara/apartments/pv2638/",
        "",
    )

    assert external_id == "PV2638"


def test_solvilla_accepts_missing_overestimated_page_when_count_is_safe() -> None:
    assert _has_safe_listing_count(345, 358)


def test_solvilla_rejects_missing_page_when_count_is_too_low() -> None:
    assert not _has_safe_listing_count(250, 358)


def test_solvilla_html_fallback_parses_static_listing_cards() -> None:
    html = """
    <a href="/properties/san-pedro-de-alcantara/apartments/pv2638/">
      <span>#PV2638</span>
      <span>The Grove - Iconic Residences in San Pedro</span>
      <span>1.134.000 €</span>
    </a>
    """

    items = _parse_solvilla_html_items(html, base_url="https://www.solvilla.es/properties/")

    assert items == [
        {
            "title": "The Grove - Iconic Residences in San Pedro",
            "cleanTitle": "The Grove - Iconic Residences in San Pedro",
            "url": "https://www.solvilla.es/properties/san-pedro-de-alcantara/apartments/pv2638/",
            "text": "#PV2638\nThe Grove - Iconic Residences in San Pedro\n1.134.000 €",
            "image": None,
        }
    ]
