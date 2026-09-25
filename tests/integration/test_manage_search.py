import datetime
import json

import pytest
from click.testing import CliRunner

from mailbox_cleanup.cli import cli
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
def sort_mode(request):
    """Run ordering tests on both paths: IMAP SORT (GreenMail advertises it) and the
    client-side fallback used when a server does not advertise SORT."""
    return request.param


def _apply_mode(mb, mode):
    if mode == "client_sort":
        mb.client.capabilities = tuple(c for c in mb.client.capabilities if c != "SORT")
    else:
        assert "SORT" in mb.client.capabilities


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
