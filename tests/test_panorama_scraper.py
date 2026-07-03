from real_estate_monitor.scrapers.panorama import PanoramaScraper


def test_panorama_accepts_panr_references() -> None:
    scraper = PanoramaScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    external_id = scraper._external_id(
        "https://www.panoramamarbella.com/properties/marbella/apartments/PANR-16531",
        "",
    )

    assert external_id == "PANR-16531"


def test_panorama_listing_page_detection_excludes_detail_pages() -> None:
    scraper = PanoramaScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    assert scraper._looks_like_listing_page("https://www.panoramamarbella.com/properties?page=2")
    assert not scraper._looks_like_listing_page(
        "https://www.panoramamarbella.com/properties/marbella/apartments/PANR-16531"
    )
