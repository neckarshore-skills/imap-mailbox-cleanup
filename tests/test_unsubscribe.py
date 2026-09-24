import json
import socket
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mailbox_cleanup import cli as cli_mod
from mailbox_cleanup.auth import Credentials
from mailbox_cleanup.config import Account
from mailbox_cleanup.operations.unsubscribe import (
    EgressBlocked,
    UnsubAction,
    parse_list_unsubscribe,
    perform_unsubscribe,
    validate_egress_url,
)


def _addrinfo(ip: str, port: int = 443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


def test_parse_https_only():
    actions = parse_list_unsubscribe(
        list_unsubscribe="<https://example.com/unsub?t=abc>",
        list_unsubscribe_post=None,
    )
    assert any(a.kind == "https" and a.target == "https://example.com/unsub?t=abc" for a in actions)


def test_parse_mailto_only():
    actions = parse_list_unsubscribe(
        list_unsubscribe="<mailto:unsub@example.com?subject=unsubscribe>",
        list_unsubscribe_post=None,
    )
    assert any(a.kind == "mailto" and a.target == "unsub@example.com" for a in actions)


def test_parse_both_https_preferred():
    actions = parse_list_unsubscribe(
        list_unsubscribe="<mailto:u@example.com>, <https://example.com/unsub>",
        list_unsubscribe_post="List-Unsubscribe=One-Click",
    )
    https = [a for a in actions if a.kind == "https"][0]
    assert https.one_click is True


def test_perform_https_one_click_uses_post():
    action = UnsubAction(kind="https", target="https://example.com/unsub", one_click=True)
    with (
        patch("mailbox_cleanup.operations.unsubscribe.requests") as r,
        patch("mailbox_cleanup.operations.unsubscribe.socket.getaddrinfo") as gai,
    ):
        gai.return_value = _addrinfo("93.184.216.34")  # public host
        r.post.return_value = MagicMock(status_code=200)
        ok, info = perform_unsubscribe(action)
    assert ok is True
    r.post.assert_called_once()
    assert "List-Unsubscribe=One-Click" in r.post.call_args.kwargs["data"]


def test_perform_https_get_when_no_one_click():
    action = UnsubAction(kind="https", target="https://example.com/unsub", one_click=False)
    with (
        patch("mailbox_cleanup.operations.unsubscribe.requests") as r,
        patch("mailbox_cleanup.operations.unsubscribe.socket.getaddrinfo") as gai,
    ):
        gai.return_value = _addrinfo("93.184.216.34")  # public host
        r.get.return_value = MagicMock(status_code=200)
        ok, info = perform_unsubscribe(action)
    assert ok is True
    r.get.assert_called_once()


def test_perform_mailto_sends_nothing_and_reports_manual():
    action = UnsubAction(kind="mailto", target="unsub@example.com", one_click=False)
    ok, info = perform_unsubscribe(action)
    assert ok is False
    assert info.startswith("manual:")


def test_parse_mailto_only_still_listed():
    actions = parse_list_unsubscribe(
        list_unsubscribe="<mailto:unsub@example.com?subject=unsubscribe>",
        list_unsubscribe_post=None,
    )
    assert [(a.kind, a.target) for a in actions] == [("mailto", "unsub@example.com")]


# --- SSRF egress guard (fail-closed) ---------------------------------------


def test_validate_egress_refuses_cloud_metadata_ip():
    # AWS/GCP link-local metadata endpoint — the canonical SSRF target.
    with pytest.raises(EgressBlocked):
        validate_egress_url("http://169.254.169.254/latest/meta-data/")


def test_validate_egress_refuses_non_http_scheme():
    with pytest.raises(EgressBlocked):
        validate_egress_url("file:///etc/passwd")


def test_validate_egress_allows_public_host():
    with patch("mailbox_cleanup.operations.unsubscribe.socket.getaddrinfo") as gai:
        gai.return_value = _addrinfo("93.184.216.34")
        # Must not raise.
        validate_egress_url("https://newsletter.example.com/unsub?t=abc")


def test_perform_https_refuses_loopback_literal():
    action = UnsubAction(kind="https", target="http://127.0.0.1/admin", one_click=False)
    with patch("mailbox_cleanup.operations.unsubscribe.requests") as r:
        ok, info = perform_unsubscribe(action)
    assert ok is False
    assert "blocked" in info.lower()
    r.get.assert_not_called()
    r.post.assert_not_called()


def test_perform_https_refuses_private_range_literal():
    action = UnsubAction(kind="https", target="http://192.168.1.1/", one_click=False)
    with patch("mailbox_cleanup.operations.unsubscribe.requests") as r:
        ok, info = perform_unsubscribe(action)
    assert ok is False
    r.get.assert_not_called()


def test_perform_https_refuses_metadata_ip():
    action = UnsubAction(
        kind="https", target="http://169.254.169.254/latest/meta-data/", one_click=True
    )
    with patch("mailbox_cleanup.operations.unsubscribe.requests") as r:
        ok, info = perform_unsubscribe(action)
    assert ok is False
    r.post.assert_not_called()


def test_perform_https_refuses_dns_rebind_to_private():
    # Hostname looks public but resolves to loopback → must be refused.
    action = UnsubAction(kind="https", target="https://evil.example.com/unsub", one_click=False)
    with (
        patch("mailbox_cleanup.operations.unsubscribe.requests") as r,
        patch("mailbox_cleanup.operations.unsubscribe.socket.getaddrinfo") as gai,
    ):
        gai.return_value = _addrinfo("127.0.0.1")
        ok, info = perform_unsubscribe(action)
    assert ok is False
    r.get.assert_not_called()


def test_perform_https_disables_redirects():
    action = UnsubAction(kind="https", target="https://example.com/unsub", one_click=False)
    with (
        patch("mailbox_cleanup.operations.unsubscribe.requests") as r,
        patch("mailbox_cleanup.operations.unsubscribe.socket.getaddrinfo") as gai,
    ):
        gai.return_value = _addrinfo("93.184.216.34")
        r.get.return_value = MagicMock(status_code=200)
        perform_unsubscribe(action)
    assert r.get.call_args.kwargs.get("allow_redirects") is False


# --- CLI `unsubscribe --apply` (Review Focus 1) -----------------------------


def _run_apply(monkeypatch, actions):
    """Run `unsubscribe --apply` against a fake mailbox; return (payload, moves, audit)."""
    moved = []
    audit = []

    class _MB:
        def move(self, uids, folder):
            moved.append((tuple(uids), folder))

    @contextmanager
    def _fake_connect(creds, port=993):
        yield _MB()

    monkeypatch.setattr(
        cli_mod,
        "resolve_account_and_credentials",
        lambda **kw: (
            Account(alias="t", email="t@example.com", server="imap.example.com"),
            Credentials(email="t@example.com", password="x", server="imap.example.com"),
        ),
    )
    monkeypatch.setattr(cli_mod, "imap_connect", _fake_connect)
    monkeypatch.setattr(
        cli_mod,
        "collect_unsub_targets",
        lambda mb, sender, folder: {"uids": ["7"], "actions": actions},
    )
    monkeypatch.setattr(cli_mod, "resolve_folder", lambda mb, kind: "Trash")
    monkeypatch.setattr(cli_mod, "log_action", lambda **kw: audit.append(kw))
    res = CliRunner().invoke(
        cli_mod.cli, ["unsubscribe", "--sender", "news@example.com", "--apply", "--json"]
    )
    assert res.exit_code == 0, res.output
    return json.loads(res.output), moved, audit


def test_apply_mailto_only_keeps_mail_and_lists_manual(monkeypatch):
    payload, moved, audit = _run_apply(
        monkeypatch, [{"kind": "mailto", "target": "unsub@example.com", "one_click": False}]
    )
    assert payload["manual_unsubscribe"] == ["unsub@example.com"]
    assert moved == []
    # Review Focus 1: the audit result is not "success", and no mail counts as affected.
    assert [(a["result"], a["affected_uids"]) for a in audit] == [("manual", [])]


def test_apply_https_and_mailto_runs_https_trashes_and_lists_nothing(monkeypatch):
    monkeypatch.setattr(cli_mod, "perform_unsubscribe", lambda a: (True, "HTTP 200"))
    payload, moved, audit = _run_apply(
        monkeypatch,
        [
            {"kind": "https", "target": "https://example.com/u", "one_click": True},
            {"kind": "mailto", "target": "unsub@example.com", "one_click": False},
        ],
    )
    assert payload["manual_unsubscribe"] == []
    assert moved == [(("7",), "Trash")]
    assert [a["result"] for a in audit] == ["success"]


def test_apply_without_list_unsubscribe_header_still_trashes(monkeypatch):
    payload, moved, audit = _run_apply(monkeypatch, [])
    assert payload["manual_unsubscribe"] == []
    assert moved == [(("7",), "Trash")]
    assert [a["result"] for a in audit] == ["success"]
