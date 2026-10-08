"""Attachments against GreenMail: listed by `read`, written by `save-attachment`, and the
mailbox is left exactly as it was."""

import hashlib
import json
from email.message import EmailMessage

import pytest
from click.testing import CliRunner

from mailbox_cleanup.cli import cli
from mailbox_cleanup.manage.search import search

pytestmark = pytest.mark.integration

ODT = "application/vnd.oasis.opendocument.text"
PAYLOAD = b"PK\x03\x04" + bytes(range(256)) * 8  # binary on purpose: must survive base64


def _mail_with_odt() -> bytes:
    m = EmailMessage()
    m["From"] = "kitchen@example.com"
    m["To"] = "test@localhost"
    m["Subject"] = "Wochenkarte"
    m["Message-ID"] = "<menu1@example.com>"
    m["Date"] = "Mon, 05 Oct 2026 09:00:00 +0200"
    m.set_content("Die Karte liegt bei.")
    m.add_attachment(
        PAYLOAD,
        maintype="application",
        subtype="vnd.oasis.opendocument.text",
        filename="wochenkarte.odt",
    )
    return m.as_bytes()


def _state(mb):
    mb.folder.set("INBOX")
    return [(m.uid, tuple(sorted(m.flags))) for m in mb.fetch("ALL", mark_seen=False)]


def test_read_lists_and_save_writes_identical_bytes_mailbox_untouched(
    manage_mailbox, open_mb, seed_raw, patch_account, tmp_path
):
    seed_raw(_mail_with_odt())
    audit = patch_account(manage_mailbox)
    with open_mb(manage_mailbox) as mb:
        (hit,) = [h for h in search(mb, sender="kitchen@example.com")]
        before = _state(mb)

    r = CliRunner().invoke(cli, ["manage", "read", "--uid", hit.uid])
    assert r.exit_code == 0, r.output
    (a,) = json.loads(r.output)["message"]["attachments"]
    assert (a["index"], a["size_bytes"]) == (1, len(PAYLOAD))
    assert a["content_type"] == f"<mail-content>\n{ODT}\n</mail-content>"
    assert "wochenkarte.odt" in a["filename"]

    out = tmp_path / "karte.odt"
    r = CliRunner().invoke(
        cli, ["manage", "save-attachment", "--uid", hit.uid, "--index", "1", "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    assert out.read_bytes() == PAYLOAD
    assert json.loads(r.output)["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()

    with open_mb(manage_mailbox) as mb:
        assert _state(mb) == before  # same messages, same flags: nothing marked \Seen
    assert all("\\Seen" not in flags for _, flags in before)
    subs = [json.loads(ln)["subcommand"] for ln in audit.read_text().splitlines()]
    assert subs == ["manage.read", "manage.save-attachment"]


def test_a_mail_without_attachments_lists_none_and_save_says_so(
    manage_mailbox, open_mb, patch_account, tmp_path
):
    patch_account(manage_mailbox)
    with open_mb(manage_mailbox) as mb:
        uid = search(mb, sender="mira@example.org")[0].uid
    r = CliRunner().invoke(cli, ["manage", "read", "--uid", uid])
    assert json.loads(r.output)["message"]["attachments"] == []
    out = tmp_path / "none.odt"
    r = CliRunner().invoke(
        cli, ["manage", "save-attachment", "--uid", uid, "--index", "1", "--out", str(out)]
    )
    assert r.exit_code == 1 and json.loads(r.output)["error_code"] == "no_such_attachment"
    assert not out.exists()
