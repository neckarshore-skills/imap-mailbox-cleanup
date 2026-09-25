"""Filter parsing and IMAP search-criteria construction."""

import re
from datetime import UTC, datetime, timedelta

from imap_tools import AND

from ..manage.args import unsafe_arg_keys

_AGE_RE = re.compile(r"^(\d+)([dwmy])$")
_AGE_DELTA = {
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(weeks=n),
    "m": lambda n: timedelta(days=30 * n),
    "y": lambda n: timedelta(days=365 * n),
}


def parse_age(spec: str) -> timedelta:
    """Parse '30d' / '2w' / '3m' / '1y' into a timedelta."""
    m = _AGE_RE.match(spec.strip())
    if not m:
        raise ValueError(f"Bad --older-than spec: {spec!r}; expected NNd/w/m/y")
    n, unit = int(m.group(1)), m.group(2)
    return _AGE_DELTA[unit](n)


def build_imap_search(
    *,
    sender: str | None = None,
    subject_contains: str | None = None,
    older_than: str | None = None,
    now: datetime | None = None,
):
    """Build an imap-tools AND() search criteria from the given filters."""
    bad = unsafe_arg_keys(sender=sender, subject_contains=subject_contains)
    if bad:
        raise ValueError(f"control character in {', '.join(bad)} (refused before IMAP)")
    if not any([sender, subject_contains, older_than]):
        raise ValueError("At least one filter (sender, subject_contains, older_than) required")
    kwargs: dict = {}
    if sender:
        kwargs["from_"] = sender
    if subject_contains:
        kwargs["subject"] = subject_contains
    if older_than:
        if now is None:
            now = datetime.now(UTC)
        cutoff = (now - parse_age(older_than)).date()
        kwargs["date_lt"] = cutoff
    return AND(**kwargs)
