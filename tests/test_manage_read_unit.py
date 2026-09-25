"""`manage.read` pure functions and `manage.thread` folder/id-safety logic — no server."""

from types import SimpleNamespace

import mailbox_cleanup.manage.thread as thread_mod
from mailbox_cleanup.manage.read import Message, html_to_text, parse_message_ids
from mailbox_cleanup.manage.thread import _MAX_IDS, _safe_ids, thread


def test_html_to_text_keeps_words_drops_tags():
    out = html_to_text("<p>Der Elternabend ist am <b>Donnerstag</b>.</p><script>x()</script>")
    assert "Der Elternabend ist am Donnerstag." in out
    assert "<" not in out and "x()" not in out


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
    # "+09:00" sorts AFTER "+02:00" as a string, although the UTC instant is earlier.
    early = "2026-09-01T08:00:00+09:00"  # == 2026-08-31T23:00:00Z
    late = "2026-09-01T23:00:00+02:00"  # == 2026-09-01T21:00:00Z
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
    which is enough to test folder selection, capping and dedupe without a real server."""

    def __init__(self, by_folder):
        self._by_folder = by_folder  # {folder: {uid: Message}}
        self.folder = SimpleNamespace(set=self._set)
        self.current = None
        self.searched_folders: list[str] = []

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
        return list(folder_msgs.values())


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
