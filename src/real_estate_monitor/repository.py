from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from real_estate_monitor.database import PropertyListing, ScrapeRun
from real_estate_monitor.models import ListingSnapshot


def _to_snapshot(row: PropertyListing) -> ListingSnapshot:
    return ListingSnapshot(
        site=row.site,
        external_id=row.external_id,
        url=row.url,
        title=row.title,
        location=row.location,
        price=row.price,
        currency=row.currency,
        status=row.status,
        beds=row.beds,
        baths=row.baths,
        built_area_m2=row.built_area_m2,
        plot_area_m2=row.plot_area_m2,
        raw=json.loads(row.raw_json or "{}"),
        scraped_at=row.scraped_at,
    )


class ListingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_run_id(self, site: str) -> int | None:
        return self.session.scalar(
            select(ScrapeRun.id)
            .where(ScrapeRun.site == site, ScrapeRun.finished_at.is_not(None))
            .order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
            .limit(1)
        )

    def latest_snapshots(self, site: str) -> list[ListingSnapshot]:
        run_id = self.latest_run_id(site)
        if run_id is None:
            return []
        rows = self.session.scalars(
            select(PropertyListing).where(PropertyListing.site == site, PropertyListing.run_id == run_id)
        ).all()
        return [_to_snapshot(row) for row in rows]

    def save_run(self, site: str, listings: list[ListingSnapshot]) -> int:
        run = ScrapeRun(site=site)
        self.session.add(run)
        self.session.flush()
        for listing in listings:
            self.session.add(
                PropertyListing(
                    run_id=run.id,
                    site=listing.site,
                    external_id=listing.external_id,
                    url=listing.url,
                    title=listing.title,
                    location=listing.location,
                    price=listing.price,
                    currency=listing.currency,
                    status=listing.status,
                    beds=listing.beds,
                    baths=listing.baths,
                    built_area_m2=listing.built_area_m2,
                    plot_area_m2=listing.plot_area_m2,
                    raw_json=json.dumps(listing.raw, ensure_ascii=False, sort_keys=True),
                    scraped_at=listing.scraped_at,
                )
            )
        run.finished_at = datetime.now(timezone.utc)
        self.session.commit()
        return run.id
