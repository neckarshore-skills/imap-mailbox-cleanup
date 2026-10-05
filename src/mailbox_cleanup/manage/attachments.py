"""Attachments of one message: list them, and write one to a path the caller named.

Read-only towards the mailbox: nothing here marks, moves or changes a message. The only
write is one new local file. Where that file may land is bounded by `resolve_destination`,
because the path is chosen by an agent that has just read mail, and a mail can ask for
anything.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_UID_RE = re.compile(r"[0-9]+")  # same rule as read._UID_RE: the UID reaches IMAP as raw text
# A media type as it may appear outside the envelope: token "/" token, nothing else. A
# value that does not fit becomes "" instead of carrying whatever a hostile mail put there.
_CONTENT_TYPE_RE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,60}/[a-z0-9][a-z0-9.+-]{0,80}")


@dataclass(frozen=True)
class Attachment:
    index: int  # 1-based position in the message, the handle `save-attachment` takes
    filename: str  # mail-derived: only ever shown inside the envelope, never used as a path
    content_type: str
    size: int


class DestinationError(ValueError):
    """The requested output path is refused before any IMAP call."""


class NoSuchAttachmentError(LookupError):
    """The message exists but has no attachment at that index."""


def safe_content_type(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if _CONTENT_TYPE_RE.fullmatch(v) else ""


def list_attachments(msg) -> tuple[Attachment, ...]:
    return tuple(
        Attachment(
            index=i,
            filename=a.filename or "",
            content_type=safe_content_type(a.content_type),
            size=len(a.payload or b""),
        )
        for i, a in enumerate(msg.attachments or (), 1)
    )


def _allowed_roots() -> list[Path]:
    roots = [Path.home(), Path(tempfile.gettempdir()), Path("/tmp")]
    return [r.resolve() for r in roots]


def resolve_destination(out: str) -> Path:
    """Return the absolute path to create, or raise DestinationError.

    Rules, each one closing a way a mail could turn "save this" into more than a file:
    the parent directory must exist; the path must lie under the home directory or the
    temp directory; no component below that root may start with a dot (shell profiles,
    `.ssh`, `.claude`, `.git`); nothing under `~/Library` (launch agents); and the path must
    not exist yet, so nothing is ever overwritten.
    """
    p = Path(out).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if p.name in ("", ".", ".."):
        raise DestinationError("--out must name a file")
    parent = p.parent.resolve()
    if not parent.is_dir():
        raise DestinationError("the directory for --out does not exist")
    target = parent / p.name
    home = Path.home().resolve()
    root = next((r for r in _allowed_roots() if target.is_relative_to(r)), None)
    if root is None:
        raise DestinationError("--out must lie under the home directory or the temp directory")
    rel = target.relative_to(root).parts
    if any(part.startswith(".") for part in rel):
        raise DestinationError("--out must not contain a hidden (dot) file or directory")
    if root == home and rel[0] == "Library":
        raise DestinationError("--out must not lie under ~/Library")
    if target.exists() or target.is_symlink():
        raise DestinationError("--out already exists; nothing is overwritten")
    return target


def write_exclusive(target: Path, payload: bytes) -> str:
    """Create `target` (never overwrite, never follow a link), owner-only, not executable.
    Returns the SHA-256 of what was written."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    return hashlib.sha256(payload).hexdigest()


def fetch_attachment(
    mb, *, uid: str, index: int, folder: str = "INBOX"
) -> tuple[Attachment, bytes] | None:
    """Fetch one attachment's bytes without marking the message \\Seen.

    None when no message has that UID; NoSuchAttachmentError when the message has no
    attachment at `index`.
    """
    if not _UID_RE.fullmatch(uid):
        raise ValueError(f"uid must contain only ASCII digits, got {uid!r}")
    mb.folder.set(folder)
    msgs = list(mb.fetch(f"UID {uid}", mark_seen=False, limit=1))
    if not msgs:
        return None
    raw = list(msgs[0].attachments or ())
    if not 1 <= index <= len(raw):
        raise NoSuchAttachmentError(index)
    return list_attachments(msgs[0])[index - 1], raw[index - 1].payload or b""
