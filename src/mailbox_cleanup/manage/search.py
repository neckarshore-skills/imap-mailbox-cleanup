"""`manage search`: candidates only (UID, sender, subject, date), never bodies (spec §3)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from imap_tools import AND

from .args import unsafe_arg_keys

# imap_tools' default for an unparseable Date header; treated as "no date".
_UNPARSED = datetime.datetime(1900, 1, 1)
_NO_DATE = datetime.datetime.min.replace(tzinfo=datetime.UTC)


@dataclass(frozen=True)
class Candidate:
    uid: str
    sender: str
    subject: str
    date: str


def _sent_at(msg) -> datetime.datetime | None:
    """The message's Date header as an aware datetime, or None if missing/unparseable."""
    if not msg.date_str:
        return None
    d = msg.date
    if d is None or d == _UNPARSED:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.UTC)


def _newest_first(msgs) -> list:
    """Newest by message Date first; UID (numeric) breaks ties; undated mail sorts last."""
    return sorted(
        msgs,
        key=lambda m: (_sent_at(m) or _NO_DATE, int(m.uid or 0)),
        reverse=True,
    )


def _criteria(sender, subject, text, since) -> tuple[str, list[tuple[str, str]]]:
    """Split filters into an ASCII criteria string and non-ASCII (key, value) pairs.

    Non-ASCII values go to the server as IMAP literals (RFC 3501 does not allow 8-bit
    data in quoted strings; GreenMail 2.1.0 silently matches nothing for them)."""
    ascii_crit: dict = {}
    literals: list[tuple[str, str]] = []
    for key, imap_key, value in (
        ("from_", "FROM", sender),
        ("subject", "SUBJECT", subject),
        ("text", "TEXT", text),
    ):
        if not value:
            continue
        if value.isascii():
            ascii_crit[key] = value
        else:
            literals.append((imap_key, value))
    if since:
        ascii_crit["sent_date_gte"] = since
    return (str(AND(**ascii_crit)) if ascii_crit else "ALL"), literals


def _uids_with_literals(mb, base: str, literals: list[tuple[str, str]]) -> list[str]:
    """One SEARCH per non-ASCII value (imaplib sends one literal per command); the
    result is the intersection, in ascending UID order."""
    found: set[str] | None = None
    for imap_key, value in literals:
        mb.client.literal = value.encode("utf-8")
        typ, data = mb.client.uid("SEARCH", "CHARSET", "UTF-8", f"{base} {imap_key}")
        if typ != "OK":
            raise RuntimeError(f"IMAP SEARCH failed: {typ}")
        uids = set(data[0].decode().split()) if data and data[0] else set()
        found = uids if found is None else found & uids
    return sorted(found or (), key=int)


def _fetch_headers(mb, uids: list[str]) -> list:
    if not uids:
        return []
    # A bare `UID <set>` key: GreenMail 2.1.0 rejects the parenthesised `(UID <set>)`
    # that imap_tools' AND(uid=...) produces ("Search command not supported").
    return list(mb.fetch(f"UID {','.join(uids)}", headers_only=True, mark_seen=False, bulk=500))


def search(
    mb,
    *,
    folder: str = "INBOX",
    sender: str | None = None,
    subject: str | None = None,
    text: str | None = None,
    since: datetime.date | None = None,
    limit: int = 20,
) -> list[Candidate]:
    """Candidates only — never bodies (spec §3 unit 1). Newest first by message Date.

    `since` compares against the Date header (IMAP SENTSINCE), like the ordering."""
    bad = unsafe_arg_keys(folder=folder, sender=sender, subject=subject, text=text)
    if bad:
        raise ValueError(f"control characters in: {', '.join(bad)}")
    mb.folder.set(folder)
    base, literals = _criteria(sender, subject, text, since)
    if not literals and "SORT" in mb.client.capabilities:
        # The server orders by Date (RFC 5256); only the first `limit` headers are fetched.
        window = mb.uids(base, "UTF-8", sort="REVERSE DATE")[: max(limit, 0)]
        msgs = _fetch_headers(mb, window)
    else:
        # No SORT (or a non-ASCII filter, whose SORT GreenMail cannot evaluate): fetch the
        # headers of every match and order them here.
        uids = _uids_with_literals(mb, base, literals) if literals else mb.uids(base)
        msgs = _fetch_headers(mb, uids)
    ordered = _newest_first(msgs)[: max(limit, 0)]
    return [
        Candidate(
            uid=m.uid or "",
            sender=m.from_ or "",
            subject=m.subject or "",
            date=d.isoformat() if (d := _sent_at(m)) else "",
        )
        for m in ordered
    ]
