"""Bounces operation — find bounce / auto-reply messages, optionally move to Trash."""

from dataclasses import dataclass

from ..classify import is_bounce
from ..folders import resolve_folder
from .batching import move_in_batches


@dataclass
class BouncesResult:
    dry_run: bool
    folder: str
    target_folder: str | None
    affected_uids: list[str]
    sample: list[dict]


def run_bounces(mb, *, folder: str = "INBOX", apply: bool = False) -> BouncesResult:
    target = resolve_folder(mb, "trash")
    mb.folder.set(folder)
    msgs = list(mb.fetch(headers_only=True, mark_seen=False, bulk=True))
    matched = [
        m
        for m in msgs
        if is_bounce(from_addr=(m.from_ or ""), subject=(m.subject or ""), headers={})
    ]
    uids = [m.uid for m in matched if m.uid]
    sample = [{"uid": m.uid, "from": m.from_, "subject": m.subject} for m in matched[:5]]
    if apply and uids:
        if not target:
            raise RuntimeError("Could not resolve Trash folder.")
        move_in_batches(mb, uids, target)
    return BouncesResult(
        dry_run=not apply,
        folder=folder,
        target_folder=target,
        affected_uids=uids,
        sample=sample,
    )
