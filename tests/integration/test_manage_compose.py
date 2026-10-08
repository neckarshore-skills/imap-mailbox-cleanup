"""`manage compose`: a NEW mail lands in Drafts with the \\Draft flag and no threading
(compose design §6.2). Nothing is sent: the only server contact is IMAP."""

import json

import pytest
from click.testing import CliRunner
from imap_tools import AND

from mailbox_cleanup.cli import cli
from mailbox_cleanup.folders import resolve_folder

pytestmark = pytest.mark.integration


def _drafts(mb):
    folder = resolve_folder(mb, "drafts")
    mb.folder.set(folder)
    return folder, list(mb.fetch(AND(all=True), mark_seen=False))


def test_cli_compose_lands_in_drafts_with_flag_and_no_threading(
    drafts_ready, patch_account, tmp_path, open_mb
):
    audit = patch_account(drafts_ready)
    with open_mb(drafts_ready) as mb:
        mb.folder.set("INBOX")
        inbox_before = len(list(mb.fetch(AND(all=True), mark_seen=False)))
    body = tmp_path / "body.txt"
    body.write_text("Hallo Alex,\nGrüße aus dem Test.\n", encoding="utf-8")
    res = CliRunner().invoke(
        cli,
        [
            "manage", "compose",
            "--to", "alex@example.org", "--to", "kim@example.org",
            "--cc", "sam@example.org",
            "--subject", "Angebot für den Workshop",
            "--body-file", str(body), "--json",
        ],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["ok"] is True and out["subcommand"] == "manage.compose"
    assert out["to"] == ["alex@example.org", "kim@example.org"]
    assert out["cc"] == ["sam@example.org"]
    with open_mb(drafts_ready) as mb:
        folder, drafts = _drafts(mb)
        assert out["drafts_folder"] == folder
        (d,) = drafts
        assert "\\Draft" in d.flags
        assert d.to == ("alex@example.org", "kim@example.org")
        assert d.cc == ("sam@example.org",)
        assert d.bcc == ()
        assert d.from_ == "test@localhost"
        assert d.subject == "Angebot für den Workshop"
        assert "in-reply-to" not in d.headers and "references" not in d.headers
        assert "Grüße aus dem Test." in d.text
        # nothing was delivered anywhere: a sent mail to a local user would arrive in INBOX
        mb.folder.set("INBOX")
        assert len(list(mb.fetch(AND(all=True), mark_seen=False))) == inbox_before
    raw = audit.read_text(encoding="utf-8")
    assert "example.org" not in raw and "Workshop" not in raw


def test_cli_compose_refuses_before_writing_when_an_address_is_bad(
    drafts_ready, patch_account, tmp_path, open_mb
):
    patch_account(drafts_ready)
    body = tmp_path / "body.txt"
    body.write_text("x", encoding="utf-8")
    res = CliRunner().invoke(
        cli,
        ["manage", "compose", "--to", "Alex <alex@example.org>", "--subject", "s",
         "--body-file", str(body), "--json"],
    )  # fmt: skip
    assert res.exit_code == 4, res.output
    assert json.loads(res.output)["error_code"] == "bad_args"
    with open_mb(drafts_ready) as mb:
        _, drafts = _drafts(mb)
        assert drafts == []
