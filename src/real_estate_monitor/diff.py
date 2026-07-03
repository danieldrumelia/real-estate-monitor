from __future__ import annotations

from real_estate_monitor.models import ChangeType, ListingChange, ListingSnapshot


def detect_changes(
    previous: list[ListingSnapshot],
    current: list[ListingSnapshot],
) -> list[ListingChange]:
    previous_by_id = {item.external_id: item for item in previous}
    current_by_id = {item.external_id: item for item in current}
    changes: list[ListingChange] = []

    for external_id, listing in current_by_id.items():
        old = previous_by_id.get(external_id)
        if old is None:
            changes.append(ListingChange(ChangeType.NEW, listing))
            continue
        if old.price != listing.price:
            changes.append(ListingChange(ChangeType.PRICE_CHANGED, listing, old))

    for external_id, listing in previous_by_id.items():
        if external_id not in current_by_id:
            changes.append(ListingChange(ChangeType.REMOVED, listing))

    return changes
