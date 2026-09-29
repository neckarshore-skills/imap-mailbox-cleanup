"""Filter parsing and IMAP search-criteria construction."""

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from imap_tools import AND, OR

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
    sender: str | Sequence[str] | None = None,
    subject_contains: str | None = None,
    older_than: str | None = None,
    recipient: str | None = None,
    category: str | None = None,
    now: datetime | None = None,
):
    """Build an imap-tools AND() search criteria from the given filters.

    Several senders become one OR. `category` is filtered client-side after the fetch
    (see selection.py); it counts as a filter here so a category-only call searches ALL.
    """
    senders = (sender,) if isinstance(sender, str) else tuple(sender or ())
    senders = tuple(s for s in senders if s)
    values = {f"sender[{i}]": s for i, s in enumerate(senders)}
    bad = unsafe_arg_keys(**values, subject_contains=subject_contains, recipient=recipient)
    if bad:
        raise ValueError(f"control character in {', '.join(bad)} (refused before IMAP)")
    if not any([senders, subject_contains, older_than, recipient, category]):
        raise ValueError(
            "At least one filter (sender, subject_contains, older_than, recipient, "
            "category) required"
        )
    positional = []
    kwargs: dict = {}
    if len(senders) == 1:
        kwargs["from_"] = senders[0]
    elif senders:
        positional.append(OR(from_=list(senders)))
    if subject_contains:
        kwargs["subject"] = subject_contains
    if recipient:
        kwargs["to"] = recipient
    if older_than:
        if now is None:
            now = datetime.now(UTC)
        cutoff = (now - parse_age(older_than)).date()
        kwargs["date_lt"] = cutoff
    if not positional and not kwargs:
        kwargs["all"] = True
    return AND(*positional, **kwargs)
