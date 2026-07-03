from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Optional

from real_estate_monitor.models import ListingSnapshot

ProgressCallback = Callable[[str, Optional[int], Optional[int], int], None]


class PropertyScraper(ABC):
    site_name: str
    progress_callback: ProgressCallback | None = None

    @abstractmethod
    async def scrape(self) -> list[ListingSnapshot]:
        """Return the current listing snapshots for this website."""
