#!/usr/bin/env python3
"""PreToolUse hook: deny Bash commands that match a known mail-send route (spec §5).

Partial by design: an obfuscated command can get past it. The first lock is that
the package contains no send code. Segments starting with git (except send-email),
grep or rg are skipped so commit messages and searches that NAME smtplib pass.

Not covered (new families or obfuscation, out of scope per §5): perl/ruby/node mail
libraries, mail/mutt/neomutt/s-nail, string-built imports, AppleScript files. Note that
/usr/bin/mail ships on every Mac.

Runs under whatever `python3` is on PATH, outside the venv: macOS ships 3.9, so this file
must stay 3.9-compatible and must never crash (a crashing hook blocks nothing).
"""

from __future__ import annotations

import json
import re
import sys

_SEPARATORS = ("||", "&&", ";", "|", "&", "\n")
_SKIP_FIRST = ("grep", "rg", "egrep", "fgrep")

# Checked on the whole command before git segments are skipped.
_GIT_SEND_EMAIL = (re.compile(r"\bgit(?:\s+-c\s+\S+)*\s+send-email\b"), "git send-email")
# Checked on the whole command as well: osascript quoting can span segment separators.
_MAIL_APP_SEND = (
    re.compile(
        r"osascript\b.*\bapp(?:lication)?\s+(?:id\s+)?\\?\"?(?:Mail|com\.apple\.mail)\\?\"?"
        r".*\bsend\b",
        re.I | re.S,
    ),
    "Mail.app send",
)
_RULES = [
    (re.compile(r"\bsmtplib\b"), "smtplib"),
    (re.compile(r"\bsendmail\b"), "sendmail"),
    (re.compile(r"\bsmtps?://", re.I), "SMTP URL"),
    (re.compile(r"\b(swaks|msmtp|ssmtp|mailx|sendemail)\b"), "mail-send binary"),
    (re.compile(r"\bcurl\b.*--mail-(?:rcpt|from)\b"), "curl SMTP"),
    _GIT_SEND_EMAIL,
    _MAIL_APP_SEND,
    (re.compile(r"\b(openssl\s+s_client|nc|ncat|telnet)\b.*[:\s](25|465|587)\b"), "raw SMTP"),
]


def _segments(command: str) -> list[str]:
    """Split on shell separators outside quotes, so a multi-line commit message stays in
    its git segment. Unbalanced quotes fall back to splitting everywhere (stricter)."""
    segments, current, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if ch == "\\" and quote != "'" and i + 1 < len(command):
            current.append(command[i : i + 2])  # escaped char never opens/closes a quote
            i += 2
            continue
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            continue
        sep = next((s for s in _SEPARATORS if command.startswith(s, i)), None)
        if sep:
            segments.append("".join(current))
            current = []
            i += len(sep)
            continue
        current.append(ch)
        i += 1
    if quote:
        return re.split(r"\|\||&&|[;|&\n]", command)
    segments.append("".join(current))
    return segments


def decide(command: str) -> str | None:
    rule, name = _GIT_SEND_EMAIL
    if rule.search(command):
        return name
    for seg in _segments(command):
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
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    reason = decide(command)
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
