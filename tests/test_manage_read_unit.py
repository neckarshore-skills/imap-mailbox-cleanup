"""`manage.read` pure functions and `manage.thread` folder/id-safety logic — no server."""

from types import SimpleNamespace

import mailbox_cleanup.manage.thread as thread_mod
from mailbox_cleanup.manage.read import Message, html_to_text, parse_message_ids
from mailbox_cleanup.manage.thread import _MAX_IDS, _safe_ids, thread


def test_html_to_text_keeps_words_drops_tags():
    out = html_to_text("<p>Der Elternabend ist am <b>Donnerstag</b>.</p><script>x()</script>")
    assert "Der Elternabend ist am Donnerstag." in out
    assert "<" not in out and "x()" not in out


def test_html_to_text_flushes_trailing_text_that_looks_like_an_unfinished_entity():
    """Without HTMLParser.close(), trailing text ending in something that LOOKS like the
    start of a character reference (e.g. "AT&T", "&amp" with no trailing ";") is held back
    in the parser's internal buffer and never reaches handle_data — losing not just the
    tail but the WHOLE text, since feed() alone never flushes it."""
    assert "AT&T" in html_to_text("<p>Gruss von AT&T")
    assert "Ende" in html_to_text("Ende &amp")


def test_parse_message_ids_tolerates_junk():
    assert parse_message_ids("<a@x.example> junk <b@y.example>\n\t<c@z.example>") == (
        "<a@x.example>",
        "<b@y.example>",
        "<c@z.example>",
    )
    assert parse_message_ids("") == ()
    assert parse_message_ids("no brackets at all") == ()


# --- R4: header search values are attacker input, filtered by a strict allowlist -------


def test_safe_ids_drops_quote_breaking_ids():
    ids = ["<a@x.example>", '<a"OR ALL"@x.example>', "<b c@x.example>", "<ok-id.+/=@x.y-z>"]
    assert _safe_ids(ids) == ["<a@x.example>", "<ok-id.+/=@x.y-z>"]


def test_safe_ids_itself_does_not_cap():
    ids = [f"<{i}@x.example>" for i in range(_MAX_IDS + 10)]
    assert len(_safe_ids(ids)) == _MAX_IDS + 10  # capping happens in thread(), see below


# --- R3: dedupe key is one format everywhere; sort by parsed date, not the ISO string ---


def test_dedupe_key_uses_message_id_when_present():
    m = _msg("5", "INBOX", "<a@x.example>")
    assert thread_mod._dedupe_key(m) == "<a@x.example>"


def test_dedupe_key_falls_back_to_folder_and_uid_when_no_message_id():
    m = _msg("5", "Sent", "")
    assert thread_mod._dedupe_key(m) == "uid:Sent:5"


def test_parse_date_sorts_by_instant_not_string():
    # Chosen so the two orderings DISAGREE (verified: string "01:00:00+01:00" > "00:30:00-01:00",
    # while the instant 00:00Z < 01:30Z) — a naive string sort would rank `late` first.
    early = "2026-09-01T01:00:00+01:00"  # == 2026-09-01T00:00:00Z
    late = "2026-09-01T00:30:00-01:00"  # == 2026-09-01T01:30:00Z
    assert early > late  # confirms the strings alone disagree with the instant order
    assert thread_mod._parse_date(early) < thread_mod._parse_date(late)


def test_parse_date_missing_or_invalid_sorts_first():
    floor = thread_mod._parse_date("")
    assert thread_mod._parse_date("not a date") == floor
    assert floor < thread_mod._parse_date("2026-01-01T00:00:00+00:00")


# --- R6: thread searches the start folder and the resolved Sent folder -----------------


def _msg(uid, folder, message_id, date="2026-09-01T00:00:00+00:00", **kw):
    base = dict(
        uid=uid,
        folder=folder,
        message_id=message_id,
        in_reply_to="",
        references=(),
        sender="s@example.com",
        reply_to="",
        to=(),
        subject="s",
        date=date,
        text="t",
    )
    base.update(kw)
    return Message(**base)


class _FakeMb:
    """Loose fake: a header search returns every message in the current fake folder,
    which is enough to test folder selection, capping and dedupe without a real server.
    Also records every criteria object passed to fetch() (as `str(criteria)`), so a test
    can assert on exactly which values were searched."""

    def __init__(self, by_folder):
        self._by_folder = by_folder  # {folder: {uid: Message}}
        self.folder = SimpleNamespace(set=self._set)
        self.current = None
        self.searched_folders: list[str] = []
        self.searched_values: list[str] = []

    def _set(self, name):
        self.current = name

    def fetch(self, criteria, mark_seen=False, limit=None):
        assert mark_seen is False  # R10: never mark as read
        self.searched_folders.append(self.current)
        folder_msgs = self._by_folder.get(self.current, {})
        if isinstance(criteria, str) and criteria.startswith("UID "):
            uid = criteria.split()[1]
            m = folder_msgs.get(uid)
            return [m] if m else []
        self.searched_values.append(str(criteria))
        return list(folder_msgs.values())


class _HeaderAwareFakeMb:
    """Fake that distinguishes WHICH header a search targets and returns exactly the
    configured hits for it — needed to test that a Message-ID substring match does not
    leak in while a References substring match legitimately does (M1); the loose _FakeMb
    above returns everything for every header and cannot tell the two apart."""

    def __init__(self, start, message_id_hits=(), references_hits=()):
        self.folder = SimpleNamespace(set=self._set)
        self.current = None
        self._start = start
        self._message_id_hits = list(message_id_hits)
        self._references_hits = list(references_hits)

    def _set(self, name):
        self.current = name

    def fetch(self, criteria, mark_seen=False, limit=None):
        assert mark_seen is False  # R10: never mark as read
        if isinstance(criteria, str) and criteria.startswith("UID "):
            uid = criteria.split()[1]
            return [self._start] if uid == self._start.uid else []
        text = str(criteria)
        if "Message-ID" in text:
            return list(self._message_id_hits)
        if "References" in text:
            return list(self._references_hits)
        return []


def test_thread_searches_start_folder_and_resolved_sent_folder(monkeypatch):
    start = _msg("1", "INBOX", "<a@x.example>")
    sent_reply = _msg("9", "Sent", "<b@x.example>", in_reply_to="<a@x.example>")
    mb = _FakeMb({"INBOX": {"1": start}, "Sent": {"9": sent_reply}})
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: "Sent")
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(
        thread_mod, "to_message", lambda m, folder: m
    )  # fake already yields Message

    result = thread(mb, uid="1", folder="INBOX")

    assert "INBOX" in mb.searched_folders and "Sent" in mb.searched_folders
    assert {m.message_id for m in result} == {"<a@x.example>", "<b@x.example>"}


def test_thread_searches_only_start_folder_when_no_sent_folder(monkeypatch):
    start = _msg("1", "INBOX", "<a@x.example>")
    mb = _FakeMb({"INBOX": {"1": start}})
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: None)
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(thread_mod, "to_message", lambda m, folder: m)

    result = thread(mb, uid="1", folder="INBOX")

    assert set(mb.searched_folders) == {"INBOX"}
    assert [m.message_id for m in result] == ["<a@x.example>"]


def test_thread_caps_ids_searched_to_max_ids(monkeypatch):
    many_refs = tuple(f"<r{i}@x.example>" for i in range(60))
    start = _msg("1", "INBOX", "<start@x.example>", references=many_refs)
    mb = _FakeMb({"INBOX": {"1": start}})
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: None)
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(thread_mod, "to_message", lambda m, folder: m)

    thread(mb, uid="1", folder="INBOX")

    # one Message-ID search per wanted id (capped) + one References search for the root
    assert len(mb.searched_folders) <= _MAX_IDS + 1
    searched = " ".join(mb.searched_values)
    assert "<start@x.example>" in searched  # the start's own id: always kept
    assert "<r59@x.example>" in searched  # the most recent (tail) reference: kept
    assert "<r0@x.example>" not in searched  # the oldest reference: dropped by the cap


# --- M1: Message-ID search is exact, References search stays substring by design -------


def test_thread_message_id_search_is_exact_not_substring(monkeypatch):
    start = _msg("1", "INBOX", "<a@x.example>")
    # A different mail whose Message-ID header a NAIVE substring HEADER search for
    # "<a@x.example>" would also match, but it is not the message we searched for.
    decoy = _msg("2", "INBOX", "<a@x.example.org>")
    mb = _HeaderAwareFakeMb(start, message_id_hits=[start, decoy], references_hits=[])
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: None)
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(thread_mod, "to_message", lambda m, folder: m)

    result = thread(mb, uid="1", folder="INBOX")

    assert {m.message_id for m in result} == {"<a@x.example>"}


# --- M6: thread()-level ordering and dedupe (not just the _parse_date/_dedupe_key units) -


def test_thread_orders_mixed_timezone_offsets_by_instant(monkeypatch):
    # Same discriminating pair as test_parse_date_sorts_by_instant_not_string: `start`'s
    # date string is lexicographically GREATER than `reply`'s, but its instant is earlier
    # (00:00Z vs 01:30Z) — a naive string sort would (wrongly) put `reply` first.
    start = _msg("1", "INBOX", "<a@x.example>", date="2026-09-01T01:00:00+01:00")
    reply = _msg("2", "INBOX", "<b@x.example>", date="2026-09-01T00:30:00-01:00")
    assert start.date > reply.date  # confirms the strings alone disagree with the instant order
    mb = _HeaderAwareFakeMb(start, message_id_hits=[start], references_hits=[reply])
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: None)
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(thread_mod, "to_message", lambda m, folder: m)

    result = thread(mb, uid="1", folder="INBOX")

    assert [m.uid for m in result] == ["1", "2"]  # start's instant (00:00Z) < reply's (01:30Z)


def test_thread_start_without_message_id_appears_once(monkeypatch):
    start = _msg("1", "INBOX", "", in_reply_to="<root@x.example>", references=("<root@x.example>",))
    # The References search for the root legitimately re-finds the start message itself
    # (its own References header contains the root) — it must collapse into ONE entry,
    # not duplicate under a different dedupe-key format (R3).
    mb = _HeaderAwareFakeMb(start, message_id_hits=[], references_hits=[start])
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: None)
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(thread_mod, "to_message", lambda m, folder: m)

    result = thread(mb, uid="1", folder="INBOX")

    assert [m.uid for m in result] == ["1"]


# --- R4 corruption probe: thread() must actually call _safe_ids, not merely define it ---


def test_thread_never_searches_a_quote_breaking_id(monkeypatch):
    """Proves thread() itself relies on _safe_ids — a hostile id that SURVIVES
    read.parse_message_ids' loose extraction (`<[^<>\\s]+>`, i.e. no internal `<`, `>` or
    whitespace) because it contains no space, but that _safe_ids' stricter allowlist
    still rejects because of its embedded quotes, must never reach an IMAP search."""
    hostile = '<a"OR"ALL@x.example>'  # no whitespace: survives parse_message_ids
    assert thread_mod._SAFE_MSGID_RE.fullmatch(hostile) is None  # ...but not _safe_ids
    # A quote-free suffix of `hostile`: imap_tools' H()/AND() backslash-escapes the `"`
    # characters (`<a\"OR\"ALL@x.example>`), so a raw substring check on `hostile` itself
    # would silently never match even when the id DID reach the search — checked directly:
    # `str(AND(header=H("Message-ID", hostile)))` contains `ALL@x.example>` but not `hostile`.
    hostile_marker = "ALL@x.example>"
    start = _msg("1", "INBOX", "<start@x.example>", references=(hostile,))
    mb = _FakeMb({"INBOX": {"1": start}})
    monkeypatch.setattr(thread_mod, "resolve_folder", lambda mb, kind: None)
    monkeypatch.setattr(thread_mod, "read_message", lambda mb, *, uid, folder: start)
    monkeypatch.setattr(thread_mod, "to_message", lambda m, folder: m)

    thread(mb, uid="1", folder="INBOX")

    assert not any(hostile_marker in v for v in mb.searched_values)
