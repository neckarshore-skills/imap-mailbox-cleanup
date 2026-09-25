"""Control characters never reach the IMAP wire (command injection guard)."""

import pytest

from mailbox_cleanup.manage.args import unsafe_arg_keys
from mailbox_cleanup.manage.search import search


def test_unsafe_arg_keys_names_every_offending_field():
    assert unsafe_arg_keys(sender="a\r\nb", subject="ok", text="c\x00", folder="INBOX") == [
        "sender",
        "text",
    ]


def test_unsafe_arg_keys_accepts_plain_and_non_ascii_values():
    assert unsafe_arg_keys(sender="Jürgen", subject="Größe – Frage", text=None, folder="") == []


@pytest.mark.parametrize("ch", ["\r", "\n", "\x00", "\t", "\x1b", "\x7f"])
def test_every_control_character_is_unsafe(ch):
    assert unsafe_arg_keys(subject=f"a{ch}b") == ["subject"]


class _RecordingMailbox:
    """Any attribute access is a would-be IMAP call and is recorded."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"IMAP touched: {name}")


def test_search_refuses_control_characters_without_touching_the_server():
    mb = _RecordingMailbox()
    with pytest.raises(ValueError, match="sender"):
        search(mb, sender="x\r\nZ1 NOOP")
    assert mb.calls == []
