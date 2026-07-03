from real_estate_monitor.scrapers.idealista import IdealistaScraper


def test_idealista_accepts_english_listing_urls() -> None:
    scraper = IdealistaScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    assert scraper._external_id("https://www.idealista.com/en/inmueble/111076229/", "") == "111076229"
    assert scraper._looks_like_listing_page(
        "https://www.idealista.com/en/multi/venta-viviendas/example/pagina-2.htm"
    )
    assert not scraper._looks_like_listing_page("https://www.idealista.com/en/inmueble/111076229/")


def test_idealista_parses_listing_card_data() -> None:
    scraper = IdealistaScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshot = scraper._parse_item(
        {
            "externalId": "111076229",
            "url": "https://www.idealista.com/en/inmueble/111076229/",
            "title": "Terraced house in Dali-ur Atalaya Rio Verde, Marbella",
            "text": "Terraced house in Dali-ur Atalaya Rio Verde, Marbella 1,250,000€ 3 bed. 283 m²",
            "image": None,
            "agency": "Engel & Völkers Puerto Banus",
        }
    )

    assert snapshot is not None
    assert snapshot.external_id == "111076229"
    assert snapshot.price == 1250000
    assert snapshot.beds == 3
    assert snapshot.built_area_m2 == 283


def test_idealista_parses_listing_html_card() -> None:
    scraper = IdealistaScraper(headless=True, timeout_ms=30000, max_pages=0, retries=1)

    snapshots = scraper._parse_html(
        """
        <article class="item" data-element-id="111076229">
          <a class="item-link" href="/en/inmueble/111076229/">
            Terraced house in Dali-ur Atalaya Rio Verde, Marbella
          </a>
          <span class="item-price">1,250,000€</span>
          <span>3 bed.</span>
          <span>283 m²</span>
        </article>
        """
    )

    assert len(snapshots) == 1
    assert snapshots[0].external_id == "111076229"
    assert snapshots[0].price == 1250000
