import json

import pytest

from mailbox_cleanup.audit import AUDIT_LOG_PATH_ENV, log_action, log_manage_action


@pytest.fixture
def tmp_audit(tmp_path, monkeypatch):
    log_path = tmp_path / "audit.log"
    monkeypatch.setenv(AUDIT_LOG_PATH_ENV, str(log_path))
    yield log_path


def test_log_action_appends_jsonl(tmp_audit):
    log_action(
        subcommand="delete",
        account="work",
        args={"sender": "x@y.com", "older_than": "6m"},
        folder="INBOX",
        affected_uids=["1", "2", "3"],
        result="success",
    )
    log_action(
        subcommand="archive",
        account="private",
        args={"older_than": "12m"},
        folder="INBOX",
        affected_uids=["4"],
        result="success",
    )
    lines = tmp_audit.read_text().strip().split("\n")
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    assert rec1["subcommand"] == "delete"
    assert rec1["account"] == "work"
    assert rec1["folder"] == "INBOX"
    assert rec1["affected_uids"] == ["1", "2", "3"]
    assert rec1["result"] == "success"
    assert "timestamp" in rec1
    rec2 = json.loads(lines[1])
    assert rec2["subcommand"] == "archive"
    assert rec2["account"] == "private"


def test_log_action_records_failure(tmp_audit):
    log_action(
        subcommand="delete",
        account="work",
        args={"sender": "x@y.com"},
        folder="INBOX",
        affected_uids=[],
        result="failure",
        error="connection lost",
    )
    rec = json.loads(tmp_audit.read_text().strip())
    assert rec["result"] == "failure"
    assert rec["error"] == "connection lost"
    assert rec["account"] == "work"


def test_log_action_creates_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "audit.log"
    monkeypatch.setenv(AUDIT_LOG_PATH_ENV, str(nested))
    log_action(
        subcommand="x",
        account="any",
        args={},
        folder="INBOX",
        affected_uids=[],
        result="success",
    )
    assert nested.exists()


def test_log_action_account_field_position(tmp_audit):
    """`account` field must be present in the JSON record (next to subcommand)."""
    log_action(
        subcommand="bounces",
        account="work",
        args={},
        folder="INBOX",
        affected_uids=["1"],
        result="success",
    )
    rec = json.loads(tmp_audit.read_text().strip())
    assert rec["account"] == "work"
    assert rec["subcommand"] == "bounces"


def test_manage_record_has_no_args(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setenv("MAILBOX_CLEANUP_AUDIT_LOG", str(log))
    log_manage_action(
        subcommand="manage.search",
        account="t",
        folder="INBOX",
        uids=["1", "2"],
        result="success",
        arg_keys=["sender", "subject"],
    )
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert "args" not in rec
    assert rec["arg_keys"] == ["sender", "subject"]
    assert rec["affected_uids"] == ["1", "2"]
