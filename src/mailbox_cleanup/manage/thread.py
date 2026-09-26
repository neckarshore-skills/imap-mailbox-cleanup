"""`manage thread`: the thread around one message (spec §3 layer 3). Never marks \\Seen."""

from __future__ import annotations

import datetime

from imap_tools import AND, H

from ..folders import resolve_folder
from .ids import SAFE_MSGID_RE as _SAFE_MSGID_RE
from .read import Message, read_message, to_message

# Every Message-ID used as an IMAP HEADER search value comes from the mail itself
# (References / In-Reply-To / Message-ID headers), i.e. it is attacker input (R4). Only
# values matching this strict allowlist reach the server — see manage/ids.py, the single
# shared definition reused by cli.py (M3) and draft.py (Task 7 dispatch ruling R1) too.

# Cap on distinct Message-IDs searched per thread() call, so a hostile References header
# cannot fan out into an unbounded number of IMAP commands. The most recent ids (the tail
# of References, plus In-Reply-To and the start message's own id) are kept; a very long
# thread may lose its oldest ancestors — acceptable, see docstring below.
_MAX_IDS = 50

_MIN_DATE = datetime.datetime.min.replace(tzinfo=datetime.UTC)


def _safe_ids(ids: list[str]) -> list[str]:
    return [i for i in ids if _SAFE_MSGID_RE.fullmatch(i)]


def _dedupe_key(m: Message) -> str:
    """One key format everywhere (R3): a mail without a Message-ID is identified by
    folder+uid, never by uid alone (a bare `uid:{uid}` can collide across folders and let
    the start message appear twice)."""
    return m.message_id or f"uid:{m.folder}:{m.uid}"


def _parse_date(date_str: str) -> datetime.datetime:
    """Parse `Message.date` (an ISO string) back into a timezone-aware datetime for
    sorting (R3): comparing the ISO strings directly mis-orders mixed UTC offsets, e.g.
    "...+09:00" sorts after "...+02:00" although its instant is earlier. Missing or
    unparseable dates sort first."""
    if not date_str:
        return _MIN_DATE
    try:
        d = datetime.datetime.fromisoformat(date_str)
    except ValueError:
        return _MIN_DATE
    return d if d.tzinfo else d.replace(tzinfo=datetime.UTC)


def _by_header(mb, folder: str, header: str, value: str, *, exact: bool = False) -> list[Message]:
    """IMAP HEADER search is a substring match (M1): a hostile mail whose own Message-ID
    header is e.g. `<x@evil> <s1@example.com>` would otherwise match a Message-ID search
    for `<s1@example.com>` even though it is not that message. `exact=True` (used for the
    Message-ID search) keeps only results whose OWN message_id equals `value`. The
    References search intentionally stays substring — a reply's References header
    legitimately CONTAINS the ancestor id among others, that is how threads are found."""
    mb.folder.set(folder)
    msgs = [to_message(m, folder) for m in mb.fetch(AND(header=H(header, value)), mark_seen=False)]
    return [m for m in msgs if not exact or m.message_id == value]


def thread(mb, *, uid: str, folder: str = "INBOX") -> list[Message]:
    """The thread around one message: ancestors via References/In-Reply-To, and
    descendants whose References name the root. Searches `folder` and the resolved Sent
    folder (R6); if there is no Sent folder, only `folder` is searched — no error. Date
    order, deduplicated by Message-ID (or folder+uid when a mail has none). Never marks
    \\Seen.

    HEADER search was measured against GreenMail 2.1.0 (Task 6): `AND(header=H(name,
    value))` works as-is for both "Message-ID" and "References" — no raw-command
    workaround needed.
    """
    start = read_message(mb, uid=uid, folder=folder)
    if start is None:
        return []
    folders = [folder]
    sent = resolve_folder(mb, "sent")
    if sent and sent != folder:
        folders.append(sent)

    all_ids = [*start.references, start.in_reply_to, start.message_id]
    wanted = list(dict.fromkeys(i for i in all_ids if i))
    wanted = _safe_ids(wanted)[-_MAX_IDS:]  # keep the most recent (tail) under the cap
    root = wanted[0] if wanted else ""

    found: dict[str, Message] = {_dedupe_key(start): start}
    for f in folders:
        for mid in wanted:
            for m in _by_header(mb, f, "Message-ID", mid, exact=True):
                found.setdefault(_dedupe_key(m), m)
        if root:
            for m in _by_header(mb, f, "References", root):
                found.setdefault(_dedupe_key(m), m)
    return sorted(found.values(), key=lambda m: (_parse_date(m.date), _dedupe_key(m)))
