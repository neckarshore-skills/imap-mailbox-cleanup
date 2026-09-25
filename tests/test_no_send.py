# tests/test_no_send.py
"""The package contains no code that sends mail (spec §5). Scope: src/ only;
tests/conftest.py seeds GreenMail over SMTP and is not shipped."""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
FORBIDDEN = [
    re.compile(r"^\s*(import|from)\s+smtplib\b", re.M),
    re.compile(r"\bsmtplib\b"),
    re.compile(r"\bsendmail\s*\("),
    re.compile(r"\bsend_message\s*\("),
    re.compile(r"\bsmtps?://", re.I),
]


def test_no_send_code_in_src():
    offenders = []
    scanned = 0
    for py in SRC.rglob("*.py"):
        scanned += 1
        text = py.read_text(encoding="utf-8")
        for rx in FORBIDDEN:
            if rx.search(text):
                offenders.append(f"{py.relative_to(SRC)}: {rx.pattern}")
    assert scanned > 0, f"no .py files found under {SRC} — the guard is vacuous"
    assert offenders == [], offenders
