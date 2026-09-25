# tests/test_block_send_hook.py
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "hooks" / "block_send.py"
_spec = importlib.util.spec_from_file_location("block_send", HOOK)
bs = importlib.util.module_from_spec(_spec)
sys.modules["block_send"] = bs
_spec.loader.exec_module(bs)

BLOCK = [
    "python -c 'import smtplib; smtplib.SMTP(\"h\").sendmail(a,b,c)'",
    'python3 send.py && python -c "from smtplib import SMTP"',
    "osascript -e 'tell application \"Mail\" to send newMessage'",
    "curl --url smtps://smtp.example.com:465 --mail-from a@example.com",
    "curl smtp://mail.example.com",
    "echo hi | sendmail someone@example.com",
    "git send-email --to=x@example.com 0001.patch",
    "swaks --to x@example.com --server smtp.example.com",
    "openssl s_client -connect smtp.example.com:587 -starttls smtp",
]
ALLOW = [
    "git status",
    "git commit -m 'remove smtplib from unsubscribe'",
    "grep -rn smtplib src/",
    "uv run python -m pytest -v",
    "mailbox-autopilot manage search --sender a@example.com --json",
    "ls -la ~/Mail",
    "osascript -e 'tell application \"Finder\" to activate'",
]


@pytest.mark.parametrize("cmd", BLOCK)
def test_blocks_send_routes(cmd):
    assert bs.decide(cmd) is not None


@pytest.mark.parametrize("cmd", ALLOW)
def test_allows_ordinary_commands(cmd):
    assert bs.decide(cmd) is None


def test_script_emits_deny_json():
    payload = {"tool_name": "Bash", "tool_input": {"command": "curl smtp://x.example.com"}}
    res = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True
    )
    out = json.loads(res.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_script_silent_on_allow_and_on_garbage():
    for stdin in (
        json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}}),
        "not json",
    ):
        res = subprocess.run(
            [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True
        )
        assert res.returncode == 0 and res.stdout == ""


# --- Beyond the plan -----------------------------------------------------------------------

EXTRA_BLOCK = [
    "git status && python3 -c 'import smtplib'",
    "bash -c \"python3 -c 'import smtplib'\"",
    "uv run python -c 'import smtplib as s'",
    "nc smtp.example.com 25",
]


@pytest.mark.parametrize("cmd", EXTRA_BLOCK)
def test_blocks_send_routes_after_a_skipped_segment_or_wrapped(cmd):
    assert bs.decide(cmd) is not None


def test_gh_bodies_naming_smtplib_are_blocked_by_design():
    """Pre-flight A9: `gh` is deliberately NOT skipped. Over-blocking a PR body that names
    smtplib is cheaper than an exemption a wrapper could ride on. Documented friction."""
    assert bs.decide('gh pr create --body "removes smtplib"') is not None
