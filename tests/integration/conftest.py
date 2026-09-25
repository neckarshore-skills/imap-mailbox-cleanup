"""Shared fixtures for the manage-layer integration tests (GreenMail)."""

import smtplib  # test-only seeding; see Global Constraint 4 (scope is src/)
import time
from pathlib import Path

import pytest
from imap_tools import MailBoxUnencrypted

from mailbox_cleanup.auth import Credentials
from mailbox_cleanup.config import Account
from mailbox_cleanup.manage import cli as mcli

MANAGE_FIX = Path(__file__).parent.parent / "fixtures" / "manage"


def _send(raw_mails: list[bytes]) -> None:
    s = smtplib.SMTP("127.0.0.1", 3025)
    for raw in raw_mails:
        s.sendmail("seed@example.com", ["test@localhost"], raw)
    s.quit()
    time.sleep(0.5)


@pytest.fixture
def seed_raw():
    """Seed extra synthetic mails into INBOX, in call order (so UID order = call order)."""

    def _seed(*raw_mails: bytes) -> None:
        _send(list(raw_mails))

    return _seed


@pytest.fixture
def manage_mailbox(fresh_mailbox):
    """INBOX holding the tests/fixtures/manage/*.eml files, seeded in file-name order."""
    emls = sorted(MANAGE_FIX.glob("*.eml"))
    assert emls, f"no manage fixtures under {MANAGE_FIX}"
    _send([eml.read_bytes() for eml in emls])
    yield fresh_mailbox


@pytest.fixture
def open_mb():
    def _open(g):
        return MailBoxUnencrypted(g["host"], port=g["port"]).login(g["user"], g["password"])

    return _open


@pytest.fixture
def patch_account(monkeypatch, tmp_path):
    """Point the manage CLI at GreenMail; audit log goes to tmp_path/audit.log."""

    def _patch(g):
        monkeypatch.setenv("MAILBOX_CLEANUP_AUDIT_LOG", str(tmp_path / "audit.log"))
        monkeypatch.setattr(
            mcli,
            "resolve_account_and_credentials",
            lambda **kw: (
                Account(alias="t", email="test@localhost", server=g["host"], port=g["port"]),
                Credentials(email=g["user"], password=g["password"], server=g["host"]),
            ),
        )
        return tmp_path / "audit.log"

    return _patch
