from real_estate_monitor.diff import detect_changes
from real_estate_monitor.models import ChangeType, ListingSnapshot


def listing(external_id: str, price: int = 100, status: str = "New Listing") -> ListingSnapshot:
    return ListingSnapshot(
        site="test",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=f"Listing {external_id}",
        price=price,
        status=status,
    )


def test_detects_new_removed_and_price_changes() -> None:
    changes = detect_changes(
        previous=[listing("A"), listing("B"), listing("C", status="Available")],
        current=[listing("A", price=120), listing("C", status="Reserved"), listing("D")],
    )

    assert [change.change_type for change in changes] == [
        ChangeType.PRICE_CHANGED,
        ChangeType.NEW,
        ChangeType.REMOVED,
    ]
