"""`manage.draft` pure functions — no server. Threading, subject sanitization, and the
strict Message-ID allowlist (R1-R3, R6, R7 of the Task 7 dispatch ruling)."""

import pytest

import mailbox_cleanup.manage.draft as draft_mod
from mailbox_cleanup.manage.draft import NoDraftsFolderError, build_reply, save_draft
from mailbox_cleanup.manage.read import Message


def _orig(**kw):
    base = dict(
        uid="1",
        folder="INBOX",
        message_id="<r1@example.org>",
        in_reply_to="",
        references=(),
        sender="mira@example.org",
        reply_to="",
        to=("me@example.com",),
        subject="Position als Architekt – Rückfrage",
        date="",
        text="Hallo",
    )
    base.update(kw)
    return Message(**base)


def test_reply_threads_and_prefixes_subject_once():
    msg, warnings = build_reply(_orig(), from_addr="me@example.com", body="Danke!")
    assert msg["Subject"] == "Re: Position als Architekt – Rückfrage"
    assert msg["In-Reply-To"] == "<r1@example.org>"
    assert msg["References"] == "<r1@example.org>"
    assert msg["To"] == "mira@example.org"
    assert warnings == []
    raw = msg.as_bytes()
    assert b"=?utf-8?" in raw.lower()  # non-ASCII subject is encoded on the wire


def test_existing_re_prefix_not_doubled():
    msg, _ = build_reply(_orig(subject="RE: Termin"), from_addr="me@example.com", body="x")
    assert msg["Subject"] == "RE: Termin"


def test_reply_to_header_wins():
    msg, _ = build_reply(_orig(reply_to="jobs@example.org"), from_addr="me@example.com", body="x")
    assert msg["To"] == "jobs@example.org"


def test_missing_message_id_still_drafts_with_warning():
    msg, warnings = build_reply(_orig(message_id=""), from_addr="me@example.com", body="x")
    assert msg["In-Reply-To"] is None and msg["References"] is None
    assert warnings == ["original has no Message-ID; draft is not threaded"]


def test_references_chain_kept_and_extended():
    o = _orig(references=("<a@example.org>", "<b@example.org>"))
    msg, _ = build_reply(o, from_addr="me@example.com", body="x")
    assert msg["References"] == "<a@example.org> <b@example.org> <r1@example.org>"


# --- R1: Message-IDs inside build_reply are untrusted, same allowlist as thread.py -----


def test_malformed_message_id_is_rejected_with_distinct_warning():
    # Survives read._MSGID_RE's loose extraction (no internal `<`, `>` or whitespace) but
    # fails thread._SAFE_MSGID_RE's strict allowlist because of the embedded `"`. Built
    # directly via Message() (as the dispatch ruling requires for the R2 corruption probe)
    # rather than round-tripped through a real header.
    hostile = '<a"b@x.example>'
    msg, warnings = build_reply(_orig(message_id=hostile), from_addr="me@example.com", body="x")
    assert msg["In-Reply-To"] is None and msg["References"] is None
    assert warnings == ["original Message-ID is malformed; draft is not threaded"]


def test_malformed_references_entries_are_dropped_with_count_only():
    hostile = '<a"b@x.example>'
    o = _orig(references=("<a@example.org>", hostile, "<b@example.org>"))
    msg, warnings = build_reply(o, from_addr="me@example.com", body="x")
    assert msg["References"] == "<a@example.org> <b@example.org> <r1@example.org>"
    assert warnings == ["dropped 1 malformed References entry"]
    assert hostile not in msg["References"]  # never leaked into the outgoing header


def test_references_chain_is_capped_to_the_tail_of_20_ids():
    refs = tuple(f"<r{i}@example.org>" for i in range(25))  # r0..r24, no overlap with mid
    o = _orig(message_id="<orig@example.org>", references=refs)
    msg, warnings = build_reply(o, from_addr="me@example.com", body="x")
    ids = msg["References"].split()
    assert len(ids) == 20
    assert ids[0] == "<r6@example.org>"  # oldest kept: the tail of the 25-long chain
    assert ids[-1] == "<orig@example.org>"  # the original's own id always kept, last
    assert warnings == ["References chain trimmed to the last 20 IDs"]


# --- R3: control characters and whitespace runs are collapsed before header assignment --


def test_hostile_subject_with_embedded_crlf_still_drafts():
    # EmailMessage() (default policy) raises ValueError on a raw CR/LF in a header value;
    # a hostile decoded Subject must still produce a draft, not crash the whole command.
    o = _orig(subject="Hallo\r\nX-Injected: evil")
    msg, _ = build_reply(o, from_addr="me@example.com", body="x")
    assert "\r" not in msg["Subject"] and "\n" not in msg["Subject"]
    assert msg.as_bytes()  # serializes without raising


# --- R7: the draft's text part is exactly the given body, nothing quoted or appended ----


def test_draft_body_is_exactly_the_given_text():
    msg, _ = build_reply(_orig(), from_addr="me@example.com", body="Danke!")
    # email.message.EmailMessage.set_content always appends one trailing newline to a
    # text/plain part — standard library behavior, not appended thread content.
    assert msg.get_content() == "Danke!\n"


# --- R6: "no Drafts folder" needs no Docker — moved here out of the integration file ----


def test_no_drafts_folder_stops_and_appends_nothing(monkeypatch):
    appended = []

    class _MB:
        def append(self, *a, **kw):
            appended.append(a)

    monkeypatch.setattr(draft_mod, "resolve_folder", lambda mb, kind: None)
    msg, _ = build_reply(_orig(message_id=""), from_addr="me@example.com", body="x")
    with pytest.raises(NoDraftsFolderError):
        save_draft(_MB(), msg)
    assert appended == []
