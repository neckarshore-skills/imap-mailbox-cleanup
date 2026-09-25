"""Cleanup commands refuse control characters in values that reach IMAP.

imap_tools quotes a value by escaping only `\\` and `"`; a CR/LF inside --sender, --folder
or --to ends the IMAP command line and lets the rest run as a new command. For the
cleanup commands that means a crafted value could smuggle a DELETE or MOVE. Same class
as the manage-layer fix in Task 5 (#41), same helper.
"""

import pytest
from click.testing import CliRunner

from mailbox_cleanup import cli as cli_mod
from mailbox_cleanup.auth import Credentials
from mailbox_cleanup.config import Account
from mailbox_cleanup.operations.filters import build_imap_search

BAD = "x\r\nZ1 DELETE INBOX"

CASES = [
    ["scan", "--folder", BAD],
    ["senders", "--folder", BAD],
    ["delete", "--folder", BAD, "--older-than", "30d"],
    ["delete", "--sender", BAD],
    ["delete", "--subject-contains", BAD],
    ["move", "--to", "Archive", "--folder", BAD, "--older-than", "30d"],
    ["move", "--to", BAD, "--older-than", "30d"],
    ["move", "--to", "Archive", "--sender", BAD],
    ["move", "--to", "Archive", "--subject-contains", BAD],
    ["archive", "--folder", BAD, "--older-than", "12m"],
    ["dedupe", "--folder", BAD],
    ["attachments", "--folder", BAD],
    ["unsubscribe", "--sender", BAD],
    ["unsubscribe", "--sender", "news@example.com", "--folder", BAD],
    ["bounces", "--folder", BAD],
    ["delete", "--sender", "a\x00b@example.com"],
]


@pytest.mark.parametrize("args", CASES, ids=lambda a: " ".join(a[:2]) + "…")
def test_control_characters_are_refused_before_any_connection(monkeypatch, args):
    def _no_connect(*a, **kw):
        raise AssertionError("imap_connect must not be reached")

    monkeypatch.setattr(
        cli_mod,
        "resolve_account_and_credentials",
        lambda **kw: (
            Account(alias="t", email="t@example.com", server="imap.example.com"),
            Credentials(email="t@example.com", password="x", server="imap.example.com"),
        ),
    )
    monkeypatch.setattr(cli_mod, "imap_connect", _no_connect)
    res = CliRunner().invoke(cli_mod.cli, args)
    assert res.exit_code == 2, res.output
    assert "control character" in res.output
    assert "Z1 DELETE" not in res.output


@pytest.mark.parametrize("field", ["sender", "subject_contains"])
def test_build_imap_search_refuses_control_characters(field):
    with pytest.raises(ValueError, match="control character"):
        build_imap_search(**{field: "x\r\nZ1 NOOP"})


def test_ordinary_values_still_pass():
    assert build_imap_search(sender="news@example.com", subject_contains="Größe")
