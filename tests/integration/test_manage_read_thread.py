import json

import pytest
from click.testing import CliRunner

from mailbox_cleanup.folders import SENT_FALLBACKS, resolve_folder
from mailbox_cleanup.manage.read import read_message
from mailbox_cleanup.manage.search import search
from mailbox_cleanup.manage.thread import thread

pytestmark = pytest.mark.integration

# A References header carrying a quote-breaking id (no internal whitespace, so it SURVIVES
# read.parse_message_ids' loose extraction `<[^<>\s]+>` and actually reaches thread._safe_ids)
# next to the real one (R4). thread._safe_ids' strict allowlist rejects it before it is ever
# used as an IMAP search value — defense in depth on top of imap_tools' own HEADER-search
# quoting, which would likely have neutralized it anyway.
HOSTILE_REF = (
    b"From: buero@example.com\r\nTo: test@localhost\r\n"
    b"Subject: Re: Elternabend (hostile)\r\n"
    b"Date: Thu, 24 Sep 2026 08:00:00 +0200\r\n"
    b"Message-ID: <s4@example.com>\r\n"
    b'References: <s1@example.com> <a"OR"ALL@x.example>\r\n'
    b"In-Reply-To: <s1@example.com>\r\n\r\n"
    b"hostile ref\r\n"
)


def _uid_by_subject(mb, sender, subject):
    """Pick a candidate by an EXACT subject match (R2): SUBJECT is a substring search
    (F3), so "Elternabend" also matches "Re: Elternabend" — `search()[0]` is not enough
    once the mailbox holds both."""
    hits = [h for h in search(mb, sender=sender) if h.subject == subject]
    assert len(hits) == 1, [h.subject for h in search(mb, sender=sender)]
    return hits[0].uid


def _uid(mb, sender):
    return search(mb, sender=sender)[0].uid


def test_read_html_only_mail_returns_text(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        uid = _uid_by_subject(mb, "buero@example.com", "Elternabend")
        m = read_message(mb, uid=uid)
    assert "Donnerstag" in m.text and "<b>" not in m.text


def test_read_decodes_encoded_word_subject(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        m = read_message(mb, uid=_uid(mb, "mira@example.org"))
    assert m.subject == "Position als Architekt – Rückfrage"
    assert m.message_id == "<r1@example.org>"


def test_read_rejects_non_digit_uid(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        with pytest.raises(ValueError):
            read_message(mb, uid="7 OR 1")


def test_read_does_not_mark_seen(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        uid = _uid_by_subject(mb, "buero@example.com", "Elternabend")
        read_message(mb, uid=uid)
        mb.folder.set("INBOX")
        (after,) = list(mb.fetch(f"UID {uid}", mark_seen=False, limit=1))
    assert "\\Seen" not in after.flags


def test_thread_follows_in_reply_to(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        reply_uid = _uid_by_subject(mb, "buero@example.com", "Re: Elternabend")
        msgs = thread(mb, uid=reply_uid)
    assert [m.message_id for m in msgs] == ["<s1@example.com>", "<s2@example.com>"]


def test_thread_does_not_mark_seen(manage_mailbox, open_mb):
    with open_mb(manage_mailbox) as mb:
        reply_uid = _uid_by_subject(mb, "buero@example.com", "Re: Elternabend")
        thread(mb, uid=reply_uid)
        mb.folder.set("INBOX")
        msgs = list(mb.fetch("ALL", mark_seen=False))
    assert msgs  # sanity: the mailbox is not empty
    assert all("\\Seen" not in m.flags for m in msgs)


def test_thread_ignores_a_quote_breaking_reference_id(manage_mailbox, open_mb, seed_raw):
    seed_raw(HOSTILE_REF)
    with open_mb(manage_mailbox) as mb:
        uid = _uid_by_subject(mb, "buero@example.com", "Re: Elternabend (hostile)")
        msgs = thread(mb, uid=uid)
    ids = {m.message_id for m in msgs}
    # <s1>, <s2> (03-school-reply.eml) and <s4> (this test's own reply) are the real
    # thread members; the quote-breaking id must not fan the search out to unrelated mail.
    assert ids == {"<s1@example.com>", "<s2@example.com>", "<s4@example.com>"}
    assert "mira@example.org" not in {m.sender for m in msgs}  # did not fan out


def _delete_folder_if_present(mb, name):
    try:
        mb.folder.delete(name)
    except Exception:  # noqa: BLE001 — "no such folder" is the expected common case
        pass


def test_thread_has_no_sent_folder_on_greenmail_and_still_works(manage_mailbox, open_mb):
    """R6: measured on GreenMail 2.1.0 — `CREATE Sent (USE (\\Sent))` fails BAD (no
    CREATE-SPECIAL-USE support), and a plain `CREATE Sent` folder carries no flags, so
    SPECIAL-USE alone never finds a Sent folder here. `folders.SENT_FALLBACKS` (added in
    this fix round) now also looks for a literal folder named "Sent" etc. — so this test
    defensively removes any such leftover folder first (a previous test creates one; see
    `test_thread_crosses_into_a_manually_created_sent_folder` below) to demonstrate the
    genuinely-no-Sent-folder case: `resolve_folder` returns None and thread() still works
    correctly, searching only the start folder, no error."""
    with open_mb(manage_mailbox) as mb:
        for name in SENT_FALLBACKS:
            _delete_folder_if_present(mb, name)
        assert resolve_folder(mb, "sent") is None
        reply_uid = _uid_by_subject(mb, "buero@example.com", "Re: Elternabend")
        msgs = thread(mb, uid=reply_uid)
    assert [m.message_id for m in msgs] == ["<s1@example.com>", "<s2@example.com>"]


def test_thread_crosses_into_a_manually_created_sent_folder(manage_mailbox, open_mb):
    """R6 + SENT FALLBACK: GreenMail 2.1.0 has no CREATE-SPECIAL-USE support (see the test
    above), but a PLAIN folder literally named "Sent" (no \\Sent flag) is now found via
    `folders.SENT_FALLBACKS`, so thread() can search it. Test setup creates the folder and
    appends into it directly with `mb.append` — test code may append; `src/` must not
    (Global Constraint 5 guard) — and removes the folder again afterwards so it does not
    leak into other tests or future runs of this long-lived GreenMail container."""
    sent_reply = (
        b"From: test@localhost\r\nTo: buero@example.com\r\n"
        b"Subject: Re: Elternabend (sent copy)\r\n"
        b"Date: Fri, 25 Sep 2026 08:00:00 +0200\r\n"
        b"Message-ID: <sent1@example.com>\r\nIn-Reply-To: <s1@example.com>\r\n"
        b"References: <s1@example.com>\r\n\r\nsent reply\r\n"
    )
    with open_mb(manage_mailbox) as mb:
        _delete_folder_if_present(mb, "Sent")
        mb.folder.create("Sent")
        try:
            mb.append(sent_reply, folder="Sent")
            assert resolve_folder(mb, "sent") == "Sent"
            reply_uid = _uid_by_subject(mb, "buero@example.com", "Re: Elternabend")
            msgs = thread(mb, uid=reply_uid)
        finally:
            _delete_folder_if_present(mb, "Sent")
    ids = {m.message_id for m in msgs}
    assert ids == {"<s1@example.com>", "<s2@example.com>", "<sent1@example.com>"}


def test_cli_read_escapes_a_hostile_body(manage_mailbox, open_mb, patch_account):
    from mailbox_cleanup.cli import cli

    patch_account(manage_mailbox)
    with open_mb(manage_mailbox) as mb:
        uid = _uid(mb, "mira@example.org")
    res = CliRunner().invoke(cli, ["manage", "read", "--uid", uid, "--json"])
    assert res.exit_code == 0, res.output
    mail = json.loads(res.output)["message"]["mail"]
    assert mail.startswith("<mail-content>\n")
    assert mail.count("</mail-content>") == 1  # the fixture's own closing tag is escaped


def test_cli_thread_envelopes_every_message(manage_mailbox, open_mb, patch_account):
    from mailbox_cleanup.cli import cli

    patch_account(manage_mailbox)
    with open_mb(manage_mailbox) as mb:
        reply_uid = _uid_by_subject(mb, "buero@example.com", "Re: Elternabend")
    res = CliRunner().invoke(cli, ["manage", "thread", "--uid", reply_uid, "--json"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["subcommand"] == "manage.thread"
    ids = {m["message_id"] for m in out["messages"]}
    assert ids == {"<s1@example.com>", "<s2@example.com>"}
    for m in out["messages"]:
        assert m["mail"].startswith("<mail-content>\n")
