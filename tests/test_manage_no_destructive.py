"""Global Constraint 5: the manage layer never deletes, moves or flags-as-deleted."""

import re
from pathlib import Path

MANAGE = Path(__file__).parent.parent / "src" / "mailbox_cleanup" / "manage"
FORBIDDEN = [
    r"\.move\(",
    r"\.delete\(",
    r"\.expunge\(",
    r"\.flag\(",  # imap_tools MailBox.flag() can set \Deleted
    r"\\Deleted",
    r"DELETED",  # MailMessageFlags.DELETED
    r"operations\.(delete|move|archive|dedupe|attachments|bounces)",
    # raw IMAP commands passed as strings, e.g. client.uid("MOVE", ...) or a wrapper
    r"""["'](?i:move|store|expunge)["']""",
    r"(?i)[+-]FLAGS",
]


def test_manage_layer_has_no_destructive_calls():
    files = sorted(MANAGE.rglob("*.py"))
    assert files, f"guard scanned no files under {MANAGE}"  # no vacuous pass
    offenders = [
        f"{p.name}: {rx}"
        for p in files
        for rx in FORBIDDEN
        if re.search(rx, p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders
