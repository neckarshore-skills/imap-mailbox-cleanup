#!/usr/bin/env python3
"""PreToolUse hook: deny Bash commands that match a known mail-send route (spec §5).

Partial by design: an obfuscated command can get past it. The first lock is that
the package contains no send code. Segments starting with git (except send-email),
grep or rg are skipped so commit messages and searches that NAME smtplib pass.
"""

import json
import re
import sys

_SPLIT = re.compile(r"\|\||&&|[;|\n]")
_SKIP_FIRST = ("grep", "rg", "egrep", "fgrep")

# Checked on the whole command before git segments are skipped.
_GIT_SEND_EMAIL = (re.compile(r"\bgit\s+send-email\b"), "git send-email")
# Checked on the whole command as well: osascript quoting can span segment separators.
_MAIL_APP_SEND = (
    re.compile(r"osascript\b.*\bapplication\s+\\?\"?Mail\\?\"?.*\bsend\b", re.I | re.S),
    "Mail.app send",
)
_RULES = [
    (re.compile(r"\bsmtplib\b"), "smtplib"),
    (re.compile(r"\bsendmail\b"), "sendmail"),
    (re.compile(r"\bsmtps?://", re.I), "SMTP URL"),
    (re.compile(r"\b(swaks|msmtp|ssmtp|mailx|sendemail)\b"), "mail-send binary"),
    _GIT_SEND_EMAIL,
    _MAIL_APP_SEND,
    (re.compile(r"\b(openssl\s+s_client|nc|ncat|telnet)\b.*[:\s](25|465|587)\b"), "raw SMTP"),
]


def decide(command: str) -> str | None:
    rule, name = _GIT_SEND_EMAIL
    if rule.search(command):
        return name
    for seg in _SPLIT.split(command):
        words = seg.strip().split()
        if not words:
            continue
        if words[0] == "git" or words[0] in _SKIP_FIRST:
            continue
        for rule, name in _RULES:
            if rule.search(seg):
                return name
    rule, name = _MAIL_APP_SEND
    if rule.search(command):
        return name
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    reason = decide((payload.get("tool_input") or {}).get("command") or "")
    if reason:
        why = f"mailbox-autopilot never sends mail ({reason} blocked)"
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": why,
            }
        }
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
