"""FETCH response handling at byte level: real imaplib parses scripted server bytes.

Covers unsolicited FETCH records (another client changing flags), records split over
several responses, missing header items, and UID spoofing via quoted strings or
look-alike items (X-GM-UID)."""

import imaplib
import socket
import threading
from types import SimpleNamespace

from mailbox_cleanup.manage.search import _parse_fetch, search

INTERNAL = b'INTERNALDATE "25-Sep-2026 07:00:46 +0000"'


def _lit(b: bytes) -> bytes:
    return b"{%d}\r\n" % len(b) + b


def _hdr(sender: str, subject: str, date: str = "Fri, 25 Sep 2026 10:00:00 +0000") -> bytes:
    return f"From: {sender}\r\nSubject: {subject}\r\nDate: {date}\r\n\r\n".encode()


def _imaplib_data(untagged: bytes, command=("FETCH", "5", "(UID INTERNALDATE BODY.PEEK[HEADER])")):
    """Send `untagged` as the server's reply to one UID command; return imaplib's data."""
    srv, cli = socket.socketpair()

    def server():
        f = srv.makefile("rwb")
        f.write(b"* OK IMAP4rev1 ready\r\n")
        f.flush()
        while line := f.readline():
            tag = line.split(b" ")[0]
            if b" CAPABILITY" in line:
                f.write(b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n")
            elif b" LOGIN " in line or b" SELECT " in line:
                f.write(b"* 20 EXISTS\r\n" + tag + b" OK done\r\n")
            else:
                f.write(untagged + tag + b" OK done\r\n")
            f.flush()

    threading.Thread(target=server, daemon=True).start()

    class _Client(imaplib.IMAP4):
        def open(self, host="", port=0, timeout=None):
            self.host, self.port = host, port
            self.sock = cli
            self.file = cli.makefile("rb")

    c = _Client()
    c.login("user", "pw")
    c.select("INBOX")
    typ, data = c.uid(*command)
    c.shutdown()
    srv.close()
    assert typ == "OK"
    return data


class _Client:
    """SEARCH yields UID 5; FETCH replies come from `respond(uids, is_key_pass)` bytes,
    parsed by real imaplib."""

    def __init__(self, respond):
        self.respond = respond
        self.literal = None

    def capability(self):
        return "OK", [b"IMAP4rev1"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"5"]
        assert command == "FETCH"
        key_pass = "HEADER.FIELDS" in args[1]
        return "OK", _imaplib_data(self.respond(args[0], key_pass), ("FETCH", args[0], args[1]))


def _mb(respond):
    return SimpleNamespace(client=_Client(respond), folder=SimpleNamespace(set=lambda f: None))


MATCH = _hdr("match@example.org", "MATCH")


def _normal(uid: bytes = b"5", header: bytes = MATCH) -> bytes:
    return b"* 1 FETCH (UID " + uid + b" " + INTERNAL + b" BODY[HEADER] " + _lit(header) + b")\r\n"


def test_unsolicited_fetch_for_a_foreign_uid_is_ignored():
    """Another client marks mail 777 read while we fetch: 777 must not become a hit."""

    def respond(uids, key_pass):
        return _normal() + b"* 9 FETCH (UID 777 FLAGS (\\Seen))\r\n"

    hits = search(_mb(respond), subject="MATCH")
    assert [h.uid for h in hits] == ["5"]


def test_flags_only_record_for_same_uid_does_not_blank_the_candidate():
    def respond(uids, key_pass):
        return _normal() + b"* 1 FETCH (UID 5 FLAGS (\\Seen))\r\n"

    (hit,) = search(_mb(respond), subject="MATCH")
    assert (hit.sender, hit.subject) == ("match@example.org", "MATCH")
    assert hit.date == "2026-09-25T10:00:00+00:00"


def test_one_message_split_over_two_fetch_responses_is_one_candidate():
    def respond(uids, key_pass):
        return (
            b"* 1 FETCH (UID 5 " + INTERNAL + b")\r\n"
            b"* 1 FETCH (UID 5 BODY[HEADER] " + _lit(MATCH) + b")\r\n"
        )

    hits = search(_mb(respond), subject="MATCH")
    assert [(h.uid, h.sender) for h in hits] == [("5", "match@example.org")]


def test_uid_whose_header_never_arrives_is_dropped_not_returned_blank():
    def respond(uids, key_pass):
        if key_pass:
            return _normal()
        return b"* 1 FETCH (UID 5 " + INTERNAL + b" FLAGS (\\Seen))\r\n"

    assert search(_mb(respond), subject="MATCH") == []


def test_quoted_string_cannot_supply_the_uid():
    data = _imaplib_data(b'* 1 FETCH (BODY[HEADER] "X: UID 42" UID 5)\r\n')
    assert [r.uid for r in _parse_fetch(data, {"5", "42"})] == ["5"]


def test_lookalike_item_cannot_supply_the_uid():
    data = _imaplib_data(b"* 1 FETCH (X-GM-UID 9 UID 5 BODY[HEADER] " + _lit(MATCH) + b")\r\n")
    assert [r.uid for r in _parse_fetch(data, {"5", "9"})] == ["5"]


def test_parse_fetch_drops_records_for_uids_not_requested():
    """Isolates the requested-UID filter. The end-to-end unsolicited-FETCH test above also
    passes without it, because the full-header pass later drops a UID whose header never
    arrives; this test pins the filter itself (defence in depth, not a duplicate)."""
    data = [
        (
            b'1 (UID 5 INTERNALDATE "25-Sep-2026 10:00:00 +0000" BODY[HEADER.FIELDS (DATE)] {4}',
            b"\r\n\r\n",
        ),
        b")",
        (
            b'9 (UID 777 INTERNALDATE "25-Sep-2026 11:00:00 +0000" BODY[HEADER.FIELDS (DATE)] {4}',
            b"\r\n\r\n",
        ),
        b")",
    ]
    assert [r.uid for r in _parse_fetch(data, {"5"})] == ["5"]
