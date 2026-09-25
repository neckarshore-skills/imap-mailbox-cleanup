import datetime
import json
import time

import pytest
from click.testing import CliRunner

from mailbox_cleanup.cli import cli
from mailbox_cleanup.manage import search as search_mod
from mailbox_cleanup.manage.search import search

pytestmark = pytest.mark.integration

# Arrives LAST (highest UID) but carries the OLDEST Date: UID order and date order differ.
LATE_ARRIVAL_OLD_DATE = (
    b"From: Archiv Beispiel <archiv@example.com>\r\n"
    b"To: test@localhost\r\n"
    b"Subject: Alte Rundmail\r\n"
    b"Date: Tue, 01 Sep 2026 08:00:00 +0200\r\n"
    b"Message-ID: <old1@example.com>\r\n"
    b"\r\n"
    b"Nachgereicht.\r\n"
)


@pytest.fixture(params=["server_sort", "client_sort"])
def sort_mode(request, monkeypatch):
    """Run ordering tests on both paths: IMAP SORT (GreenMail advertises it) and the
    client-side fallback used when a server does not advertise SORT."""
    if request.param == "client_sort":
        monkeypatch.setattr(search_mod, "_has_sort", lambda mb: False)
    return request.param


def _apply_mode(mb, mode):
    assert search_mod._has_sort(mb) is (mode == "server_sort")


def test_search_by_sender_returns_headers_only(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        hits = search(mb, sender="mira@example.org")
    assert len(hits) == 1
    assert hits[0].sender == "mira@example.org"
    assert "Rückfrage" in hits[0].subject


def test_search_non_ascii_subject(manage_mailbox, open_mb, sort_mode):
    with open_mb(manage_mailbox) as mb:
        _apply_mode(mb, sort_mode)
        hits = search(mb, subject="Rückfrage")
    assert [h.sender for h in hits] == ["mira@example.org"]


def test_search_without_filter_returns_newest_first(manage_mailbox, open_mb, sort_mode):
    with open_mb(manage_mailbox) as mb:
        _apply_mode(mb, sort_mode)
        hits = search(mb, limit=10)
    dates = [datetime.datetime.fromisoformat(h.date) for h in hits]
    assert dates == sorted(dates, reverse=True)
    senders = [h.sender for h in hits]
    assert senders.index("buero@example.com") < senders.index("mira@example.org")


def test_newest_first_means_message_date_not_uid(manage_mailbox, open_mb, seed_raw, sort_mode):
    seed_raw(LATE_ARRIVAL_OLD_DATE)
    with open_mb(manage_mailbox) as mb:
        _apply_mode(mb, sort_mode)
        hits = search(mb, limit=10)
        top = search(mb, limit=1)
    uids = [int(h.uid) for h in hits]
    assert hits[-1].sender == "archiv@example.com"  # oldest Date, although highest UID
    assert max(uids) == int(hits[-1].uid)
    assert [h.sender for h in top] == ["buero@example.com"]  # limit cuts by date, not UID


def test_search_since_filters_older_mail(manage_mailbox, open_mb, seed_raw):
    seed_raw(LATE_ARRIVAL_OLD_DATE)
    with open_mb(manage_mailbox) as mb:
        hits = search(mb, since=datetime.date(2026, 9, 20))
    assert "archiv@example.com" not in [h.sender for h in hits]
    assert {"mira@example.org", "buero@example.com"} <= {h.sender for h in hits}


def test_cli_search_envelopes_every_candidate(manage_mailbox, patch_account):
    audit = patch_account(manage_mailbox)
    res = CliRunner().invoke(cli, ["manage", "search", "--sender", "mira@example.org", "--json"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["subcommand"] == "manage.search"
    (c,) = out["candidates"]
    assert c["mail"].startswith("<mail-content>\n") and "mira@example.org" in c["mail"]
    rec = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["result"] == "success" and rec["arg_keys"] == ["sender"]
    assert "mira@example.org" not in audit.read_text(encoding="utf-8")


def _mail(sender: str, subject: str, date: str | None) -> bytes:
    head = f"From: {sender}\r\nTo: test@localhost\r\nSubject: {subject}\r\n"
    if date is not None:
        head += f"Date: {date}\r\n"
    return (head + "\r\nx\r\n").encode()


def test_undated_and_garbled_mail_sort_by_arrival_on_both_paths(
    fresh_mailbox, open_mb, seed_raw, monkeypatch
):
    """RFC 5256: a missing or unparseable Date sorts by INTERNALDATE (arrival). Both
    paths must return the same list for every limit."""
    seed_raw(_mail("new@example.com", "neu", "Sun, 20 Sep 2026 10:00:00 +0000"))
    seed_raw(_mail("old@example.com", "alt", "Wed, 01 Jan 2020 10:00:00 +0000"))
    time.sleep(1.1)  # INTERNALDATE has one-second resolution: keep arrivals distinct
    seed_raw(_mail("nodate@example.com", "ohne Datum", None))
    time.sleep(1.1)
    seed_raw(_mail("garbled@example.com", "kaputt", "not a date at all"))
    expected = ["garbled@example.com", "nodate@example.com", "new@example.com", "old@example.com"]
    for limit in (1, 2, 4):
        with open_mb(fresh_mailbox) as mb:
            assert search_mod._has_sort(mb)
            server = [h.sender for h in search(mb, limit=limit)]
        with monkeypatch.context() as m:
            m.setattr(search_mod, "_has_sort", lambda mb: False)
            with open_mb(fresh_mailbox) as mb:
                client = [h.sender for h in search(mb, limit=limit)]
        assert server == client == expected[:limit], (limit, server, client)


def test_two_non_ascii_filters_intersect(fresh_mailbox, open_mb, seed_raw):
    """Subject AND body text, both non-ASCII: one literal SEARCH each, intersected.
    (Not FROM: GreenMail 2.1.0 matches FROM only against the full address.)"""

    def _m(subject_qp: bytes, body: str, hour: int) -> bytes:
        return (
            b"From: juergen@example.org\r\nTo: test@localhost\r\n"
            b"Subject: =?utf-8?q?" + subject_qp + b"?=\r\n"
            b"Date: Mon, 21 Sep 2026 %02d:00:00 +0200\r\n"
            % hour
            + b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + body.encode("utf-8")
            + b"\r\n"
        )

    seed_raw(
        _m(b"Gr=C3=B6=C3=9Fe_der_Lieferung", "Übergabe am Montag", 9),
        _m(b"Gr=C3=B6=C3=9Fe_der_Lieferung", "Abholung am Montag", 10),
        _m(b"R=C3=BCckfrage", "Übergabe am Dienstag", 11),
    )
    with open_mb(fresh_mailbox) as mb:
        both = search(mb, subject="Größe", text="Übergabe")
        subject_only = search(mb, subject="Größe")
    assert len(subject_only) == 2
    assert [(h.subject, h.date[:13]) for h in both] == [("Größe der Lieferung", "2026-09-21T09")]
