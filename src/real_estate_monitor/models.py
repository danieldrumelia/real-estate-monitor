from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ChangeType(str, Enum):
    NEW = "new"
    REMOVED = "removed"
    PRICE_CHANGED = "price_changed"
    STATUS_CHANGED = "status_changed"


@dataclass(frozen=True)
class ListingSnapshot:
    site: str
    external_id: str
    url: str
    title: str
    location: str | None = None
    price: int | None = None
    currency: str = "EUR"
    status: str | None = None
    beds: float | None = None
    baths: float | None = None
    built_area_m2: float | None = None
    plot_area_m2: float | None = None
    raw: dict[str, str | int | float | None] = field(default_factory=dict)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ListingChange:
    change_type: ChangeType
    listing: ListingSnapshot
    previous: ListingSnapshot | None = None
