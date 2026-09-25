"""`manage search` without a server: ordering key, UID sets, capability refresh, scaling."""

import datetime
import re
from types import SimpleNamespace

import pytest

from mailbox_cleanup.manage.search import _Row, _sort_key, search, uid_set

UTC = datetime.UTC
ARRIVED = datetime.datetime(2026, 9, 25, 7, 0, tzinfo=UTC)


def _row(uid, date_header, arrived=ARRIVED):
    hdr = f"Date: {date_header}\r\n\r\n".encode() if date_header is not None else b""
    return _Row(uid=uid, arrived=arrived, header=hdr)


def _order(rows):
    return [r.uid for r in sorted(rows, key=_sort_key, reverse=True)]


# --- ordering key (RFC 5256: Date header, else INTERNALDATE; UID breaks ties) ---------


def test_key_uses_date_header_and_reads_naive_as_utc():
    rows = [
        _row("1", "Mon, 21 Sep 2026 09:00:00 +0200"),  # 07:00 UTC
        _row("2", "Mon, 21 Sep 2026 08:00:00"),  # naive, read as 08:00 UTC
    ]
    assert _order(rows) == ["2", "1"]


def test_missing_or_garbled_date_falls_back_to_arrival():
    rows = [
        _row("1", "Sun, 20 Sep 2026 10:00:00 +0000"),
        _row("2", None, arrived=datetime.datetime(2026, 9, 24, tzinfo=UTC)),
        _row("3", "not a date at all", arrived=datetime.datetime(2026, 9, 23, tzinfo=UTC)),
        _row("4", "Wed, 01 Jan 2020 10:00:00 +0000"),
    ]
    assert _order(rows) == ["2", "3", "1", "4"]


def test_no_date_and_no_arrival_sorts_last():
    rows = [_row("7", None, arrived=None), _row("1", "Wed, 01 Jan 2020 10:00:00 +0000")]
    assert _order(rows) == ["1", "7"]


def test_equal_dates_break_ties_by_numeric_uid():
    d = "Mon, 21 Sep 2026 09:00:00 +0000"
    assert _order([_row("9", d), _row("10", d), _row("2", d)]) == ["10", "9", "2"]


# --- UID set collapse ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("uids", "expected"),
    [
        (["1", "2", "3", "5", "7", "8"], "1:3,5,7:8"),
        (["8", "7", "3", "1", "2", "3"], "1:3,7:8"),  # unsorted, duplicate
        (["42"], "42"),
        ([str(u) for u in range(1, 50_001)], "1:50000"),
    ],
)
def test_uid_set_collapses_ranges(uids, expected):
    assert uid_set(uids) == expected


# --- fake server -----------------------------------------------------------------------

BASE = datetime.datetime(2026, 9, 1, tzinfo=UTC)


def _expand(uidset: str) -> list[int]:
    out = []
    for part in uidset.split(","):
        a, _, b = part.partition(":")
        out.extend(range(int(a), int(b or a) + 1))
    return out


class _FakeClient:
    """UID n carries Date = BASE - n minutes, so the NEWEST mail has the LOWEST UID."""

    def __init__(self, n, caps_pre=("IMAP4REV1",), caps_post=b"IMAP4rev1 SORT"):
        self.n = n
        self.capabilities = caps_pre
        self._caps_post = caps_post
        self.literal = None
        self.lines: list[str] = []
        self.full_header_uids: list[int] = []

    def capability(self):
        return "OK", [self._caps_post]

    def uid(self, command, *args):
        line = " ".join(a.decode() if isinstance(a, bytes) else a for a in args)
        self.lines.append(f"UID {command} {line}")
        command = command.upper()
        if command == "SORT":
            return "OK", [" ".join(str(u) for u in range(1, self.n + 1)).encode()]
        if command == "SEARCH":
            return "OK", [" ".join(str(u) for u in range(self.n, 0, -1)).encode()]
        assert command == "FETCH", command
        uids = _expand(args[0])
        if "BODY.PEEK[HEADER]" in args[1]:
            self.full_header_uids.extend(uids)
        data = []
        for u in uids:
            date = (BASE - datetime.timedelta(minutes=u)).strftime("%a, %d %b %Y %H:%M:%S +0000")
            hdr = f"Date: {date}\r\nFrom: u{u}@example.com\r\nSubject: s{u}\r\n\r\n".encode()
            meta = f'{u} (UID {u} INTERNALDATE "25-Sep-2026 07:00:46 +0000" BODY[] {{{len(hdr)}}}'
            data += [(meta.encode(), hdr), b")"]
        return "OK", data


def _fake_mb(client):
    return SimpleNamespace(client=client, folder=SimpleNamespace(set=lambda name: None))


def test_sort_capability_is_read_after_login():
    """Dovecot advertises SORT only post-login; the pre-login list must not decide."""
    client = _FakeClient(3, caps_pre=("IMAP4REV1",), caps_post=b"IMAP4rev1 SORT")
    search(_fake_mb(client), limit=2)
    assert any(line.startswith("UID SORT") for line in client.lines)


def test_no_sort_after_login_means_no_sort_command():
    client = _FakeClient(3, caps_pre=("IMAP4REV1", "SORT"), caps_post=b"IMAP4rev1")
    search(_fake_mb(client), limit=2)
    assert not any(line.startswith("UID SORT") for line in client.lines)


@pytest.mark.parametrize("post", [b"IMAP4rev1", b"IMAP4rev1 SORT"])
def test_both_paths_scale_short_lines_and_full_headers_only_for_the_top(post):
    client = _FakeClient(50_000, caps_post=post)
    hits = search(_fake_mb(client), limit=5)
    assert [h.uid for h in hits] == ["1", "2", "3", "4", "5"]
    assert [h.sender for h in hits] == [f"u{u}@example.com" for u in range(1, 6)]
    assert max(len(line) for line in client.lines) < 8 * 1024
    assert sorted(client.full_header_uids) == [1, 2, 3, 4, 5]
    assert all(re.fullmatch(r"[\x20-\x7e]*", line) for line in client.lines)
