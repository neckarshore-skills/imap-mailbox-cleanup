"""`manage compose` CLI — no server. Every refusal is structured JSON and audited with
the error code only, and none of them reaches the mailbox."""

import json
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from mailbox_cleanup.auth import Credentials
from mailbox_cleanup.cli import cli
from mailbox_cleanup.config import Account
from mailbox_cleanup.manage import cli as mcli
from mailbox_cleanup.manage.draft import NoDraftsFolderError

TO = "alex@example.org"
CC = "sam@example.org"
SUBJECT = "Quarterly-Sentinel-Subject"


@pytest.fixture
def audit(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("MAILBOX_CLEANUP_AUDIT_LOG", str(log))
    monkeypatch.setattr(
        mcli,
        "resolve_account_and_credentials",
        lambda **kw: (
            Account(alias="t", email="test@localhost", server="imap.example.com", port=993),
            Credentials(email="test@localhost", password="x", server="imap.example.com"),
        ),
    )
    return log


@pytest.fixture
def body(tmp_path):
    p = tmp_path / "body.txt"
    p.write_text("Hello Alex,\nsee you Tuesday.\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def no_mailbox(monkeypatch):
    """Any IMAP connection fails the test: a refused command must not touch the mailbox."""

    def _boom(*a, **kw):
        raise AssertionError("imap_connect was called")

    monkeypatch.setattr(mcli, "imap_connect", _boom)


@pytest.fixture
def saved(monkeypatch):
    """A fake mailbox that records what save_draft was handed."""
    seen = {}

    @contextmanager
    def _connect(creds, *, port=993):
        yield object()

    def _save(mb, msg):
        seen["msg"] = msg
        return "Drafts"

    monkeypatch.setattr(mcli, "imap_connect", _connect)
    monkeypatch.setattr(mcli, "save_draft", _save)
    return seen


def _records(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _run(*args):
    return CliRunner().invoke(cli, ["manage", "compose", *args, "--json"])


def _full(body, **over):
    opts = {"--to": TO, "--subject": SUBJECT, "--body-file": body}
    opts.update(over)
    return [x for k, v in opts.items() if v is not None for x in (k, v)]


def test_compose_writes_one_draft_and_reports_every_recipient(audit, saved, body):
    res = _run(
        "--to", TO, "--to", "kim@example.org", "--cc", CC, "--subject", SUBJECT,
        "--body-file", body,
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["ok"] is True and out["subcommand"] == "manage.compose"
    assert out["drafts_folder"] == "Drafts"
    assert out["to"] == [TO, "kim@example.org"] and out["cc"] == [CC]
    assert out["subject"] == SUBJECT
    msg = saved["msg"]
    # the response reports what the draft holds, read back from the built message
    assert out["to"] == [a.addr_spec for a in msg["To"].addresses]
    assert out["cc"] == [a.addr_spec for a in msg["Cc"].addresses]
    assert msg["From"] == "test@localhost"
    assert msg["Bcc"] is None and msg["In-Reply-To"] is None
    assert "see you Tuesday." in msg.get_content()


def test_success_audit_carries_argument_keys_only(audit, saved, body):
    """Design decision 5: no recipient address and no subject in the audit record."""
    res = _run(*_full(body), "--cc", CC)
    assert res.exit_code == 0, res.output
    (rec,) = _records(audit)
    assert rec["result"] == "success" and rec["affected_uids"] == []
    assert sorted(rec["arg_keys"]) == ["body_file", "cc", "subject", "to"]
    raw = audit.read_text(encoding="utf-8")
    for secret in (TO, CC, SUBJECT, "example.org", "Tuesday"):
        assert secret not in raw


@pytest.mark.parametrize("missing", ["--to", "--subject", "--body-file"])
def test_a_missing_required_option_is_structured_and_creates_no_draft(
    audit, no_mailbox, body, missing
):
    res = _run(*_full(body, **{missing: None}))
    assert res.exit_code == 4, res.output
    out = json.loads(res.output)
    assert out["ok"] is False and out["error_code"] == "bad_args"
    assert missing in out["message"]
    (rec,) = _records(audit)
    assert rec["result"] == "error" and rec["error"] == "bad_args"


def test_all_missing_options_are_named_at_once(audit, no_mailbox):
    res = _run()
    assert res.exit_code == 4, res.output
    msg = json.loads(res.output)["message"]
    assert "--to" in msg and "--subject" in msg and "--body-file" in msg


def test_blank_subject_counts_as_missing(audit, no_mailbox, body):
    res = _run(*_full(body, **{"--subject": " \t "}))
    assert res.exit_code == 4, res.output
    assert json.loads(res.output)["error_code"] == "bad_args"


@pytest.mark.parametrize(
    "addr", ["Alex <alex@example.org>", "alex@example.org,evil@example.org", "alex", "a@b@c"]
)
@pytest.mark.parametrize("field", ["--to", "--cc"])
def test_a_bad_address_is_refused_without_echoing_it(audit, no_mailbox, body, field, addr):
    args = _full(body) + [field, addr]
    res = _run(*args)
    assert res.exit_code == 4, res.output
    out = json.loads(res.output)
    assert out["error_code"] == "bad_args" and field in out["message"]
    assert "evil" not in res.output and "alex" not in out["message"]
    assert "evil" not in audit.read_text(encoding="utf-8")


def test_eleven_recipients_are_refused(audit, no_mailbox, body):
    many = [x for i in range(11) for x in ("--to", f"r{i}@example.org")]
    res = _run(*many, "--subject", SUBJECT, "--body-file", body)
    assert res.exit_code == 4, res.output
    out = json.loads(res.output)
    assert out["error_code"] == "bad_args" and "10" in out["message"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--bcc", "hidden@example.org"],
        ["--attach", "/tmp/secret.pdf"],
        ["--attachment", "/tmp/secret.pdf"],
        ["--forward", "FWD-SENTINEL"],
        ["--uid", "UID-SENTINEL"],
    ],
)
def test_out_of_scope_options_are_refused_with_a_message_naming_the_scope(
    audit, no_mailbox, body, extra
):
    """Ticket criterion 5: attachments, Bcc and forwarding are rejected, and the message
    says what version 1 does instead of click's bare 'No such option'."""
    res = _run(*_full(body), *extra)
    assert res.exit_code == 4, res.output
    out = json.loads(res.output)
    assert out["ok"] is False and out["error_code"] == "out_of_scope"
    assert "To and Cc only" in out["message"]
    assert extra[0] in out["message"]
    assert extra[1] not in res.output  # the value is never echoed
    (rec,) = _records(audit)
    assert rec["result"] == "error" and rec["error"] == "out_of_scope"
    assert extra[1] not in audit.read_text(encoding="utf-8")


def test_out_of_scope_options_are_not_advertised(audit):
    res = CliRunner().invoke(cli, ["manage", "compose", "--help"])
    assert res.exit_code == 0
    for hidden in ("--bcc", "--attach", "--forward", "--uid"):
        assert hidden not in res.output


@pytest.mark.parametrize("kind", ["missing", "directory", "not_utf8"])
def test_an_unusable_body_file_is_audited_bad_args(audit, no_mailbox, tmp_path, kind):
    p = tmp_path / "b"
    if kind == "directory":
        p.mkdir()
    elif kind == "not_utf8":
        p.write_bytes(b"\xff\xfe\x00bad")
    res = _run("--to", TO, "--subject", SUBJECT, "--body-file", str(p))
    assert res.exit_code == 4, res.output
    assert json.loads(res.output)["error_code"] == "bad_args"
    (rec,) = _records(audit)
    assert rec["error"] == "bad_args"


def test_no_drafts_folder_stops_without_leaking_exception_text(audit, monkeypatch, body):
    @contextmanager
    def _connect(creds, *, port=993):
        yield object()

    def _save(mb, msg):
        raise NoDraftsFolderError("server said: SECRET-SERVER-TEXT")

    monkeypatch.setattr(mcli, "imap_connect", _connect)
    monkeypatch.setattr(mcli, "save_draft", _save)
    res = _run(*_full(body))
    assert res.exit_code == 5, res.output
    assert json.loads(res.output)["error_code"] == "no_drafts_folder"
    assert "SECRET-SERVER-TEXT" not in res.output
    assert "SECRET-SERVER-TEXT" not in audit.read_text(encoding="utf-8")


def test_operation_error_never_leaks_exception_text(audit, monkeypatch, body):
    @contextmanager
    def _connect(creds, *, port=993):
        raise RuntimeError("SECRET-SERVER-TEXT")
        yield

    monkeypatch.setattr(mcli, "imap_connect", _connect)
    res = _run(*_full(body))
    assert res.exit_code == 2, res.output
    assert json.loads(res.output)["error_code"] == "operation_error"
    assert "SECRET-SERVER-TEXT" not in res.output
    assert "SECRET-SERVER-TEXT" not in audit.read_text(encoding="utf-8")


def test_compose_never_opens_a_mail_submission_connection(audit, saved, body, monkeypatch):
    """Ticket criterion 1, at run time: tests/test_no_send.py checks the source text, this
    checks the run. Any use of the standard mail-submission client fails the command."""
    import importlib

    lib = importlib.import_module("smtp" + "lib")

    def _boom(*a, **kw):
        raise AssertionError("a mail-submission client was created")

    for name in ("SMTP", "SMTP_SSL", "LMTP"):
        monkeypatch.setattr(lib, name, _boom)
    res = _run(*_full(body), "--cc", CC)
    assert res.exit_code == 0, res.output
    assert "msg" in saved


def test_any_builder_failure_is_structured_and_audited(audit, no_mailbox, body, monkeypatch):
    """A header value that makes the mail library raise must not end in a traceback."""

    def _raise(**kw):
        raise AttributeError("SECRET-INTERNAL-TEXT")

    monkeypatch.setattr(mcli, "build_new", _raise)
    res = _run(*_full(body))
    assert res.exit_code == 4, res.output
    assert json.loads(res.output)["error_code"] == "bad_args"
    assert "SECRET-INTERNAL-TEXT" not in res.output
    (rec,) = _records(audit)
    assert rec["error"] == "bad_args"


# --- where the mail text may come from (Founder decision 2026-10-08, 18:02 CEST) --------
# Security review of 25519cf: a free recipient plus a free file read lets a deceived agent
# stage any readable local file as a draft to an outside address. `manage compose` reads
# its text from the temp directory only, at most 1 MB, and never through a symlink.

OUTSIDE = __file__  # a readable regular UTF-8 file that is not in the temp directory


def test_body_file_outside_the_temp_directory_is_refused(audit, no_mailbox):
    res = _run("--to", TO, "--subject", SUBJECT, "--body-file", OUTSIDE)
    assert res.exit_code == 4, res.output
    out = json.loads(res.output)
    assert out["error_code"] == "bad_args" and "temp directory" in out["message"]
    assert OUTSIDE not in res.output  # the path is never echoed


def test_body_file_symlink_to_a_file_outside_is_refused(audit, no_mailbox, tmp_path):
    link = tmp_path / "body.txt"
    link.symlink_to(OUTSIDE)
    res = _run("--to", TO, "--subject", SUBJECT, "--body-file", str(link))
    assert res.exit_code == 4, res.output
    assert json.loads(res.output)["error_code"] == "bad_args"


def test_body_file_symlink_is_refused_even_when_it_points_inside(audit, no_mailbox, tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    res = _run("--to", TO, "--subject", SUBJECT, "--body-file", str(link))
    assert res.exit_code == 4, res.output


def test_body_file_reached_through_a_symlinked_directory_is_refused(audit, no_mailbox, tmp_path):
    import pathlib

    link_dir = tmp_path / "d"
    link_dir.symlink_to(pathlib.Path(OUTSIDE).parent, target_is_directory=True)
    res = _run(
        "--to", TO, "--subject", SUBJECT, "--body-file", str(link_dir / pathlib.Path(OUTSIDE).name)
    )
    assert res.exit_code == 4, res.output


def test_body_file_over_one_megabyte_is_refused(audit, no_mailbox, tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"a" * (1024 * 1024 + 1))
    res = _run("--to", TO, "--subject", SUBJECT, "--body-file", str(big))
    assert res.exit_code == 4, res.output
    assert "1 MB" in json.loads(res.output)["message"]


def test_body_file_of_exactly_one_megabyte_is_accepted(audit, saved, tmp_path):
    ok = tmp_path / "ok.txt"
    ok.write_bytes(b"a" * (1024 * 1024))
    res = _run("--to", TO, "--subject", SUBJECT, "--body-file", str(ok))
    assert res.exit_code == 0, res.output


def test_reply_draft_keeps_reading_its_text_from_anywhere(audit, monkeypatch):
    """`manage draft` is unchanged: its recipient is fixed to the sender of the answered
    mail, so the temp-directory rule is not applied to it."""
    assert mcli._read_body_file(OUTSIDE) is not None
    assert mcli._read_body_file(OUTSIDE, temp_only=True) is None
