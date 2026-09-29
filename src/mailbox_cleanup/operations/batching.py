"""Move UIDs in batches. A single MOVE with thousands of UIDs times out on IONOS."""

from collections.abc import Sequence

BATCH_SIZE = 500


class PartialMoveError(RuntimeError):
    """Some batches moved, then one failed. `moved` is what actually left the folder."""

    def __init__(self, moved: list[str], remaining: list[str], cause: Exception):
        self.moved = moved
        self.remaining = remaining
        self.cause = cause
        super().__init__(
            f"moved {len(moved)} of {len(moved) + len(remaining)} messages, then failed: "
            f"{type(cause).__name__}"
        )


def move_in_batches(mb, uids: Sequence[str], target: str, size: int = BATCH_SIZE) -> list[str]:
    """Move `uids` to `target`, `size` at a time. Raises PartialMoveError on a failed batch."""
    uids = list(uids)
    moved: list[str] = []
    for i in range(0, len(uids), size):
        batch = uids[i : i + size]
        try:
            mb.move(batch, target)
        except Exception as e:
            raise PartialMoveError(moved, uids[i:], e) from e
        moved.extend(batch)
    return moved
