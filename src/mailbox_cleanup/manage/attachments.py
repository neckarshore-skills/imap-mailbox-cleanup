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

from .ids import UID_RE

# A media type: token "/" token, nothing else. A value that does not fit becomes "" instead
# of carrying whatever a hostile mail put there. The shape check is a floor, not a proof: a
# sentence written with dots and hyphens fits it. The CLI therefore envelopes the value.
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


# File names that an agent, Python or make loads by name from whatever directory they lie
# in. Compared case-folded. This list is a floor: it names the known cases and cannot name
# the unknown ones. What carries the rule is the skill: save only to the path the user named.
_AUTOLOADED_NAMES = frozenset(
    {
        "agents.md",
        "claude.local.md",
        "claude.md",
        "conftest.py",
        "gemini.md",
        "gnumakefile",
        "makefile",
        "sitecustomize.py",
        "skill.md",
        "usercustomize.py",
        "__init__.py",
    }
)
_AUTOLOADED_SUFFIXES = (".pth",)


def _is_autoloaded(name: str) -> bool:
    n = name.casefold()
    return n in _AUTOLOADED_NAMES or n.endswith(_AUTOLOADED_SUFFIXES)


def _allowed_roots() -> list[Path]:
    roots = [Path.home(), Path(tempfile.gettempdir()), Path("/tmp")]
    return [r.resolve() for r in roots]


def resolve_destination(out: str) -> Path:
    """Return the absolute path to create, or raise DestinationError.

    Rules, each one closing a way a mail could turn "save this" into more than a file:
    the parent directory must exist; the path must lie under the home directory or the
    temp directory; no component below that root may start with a dot (shell profiles,
    `.ssh`, `.claude`, `.git`); nothing under `~/Library` (launch agents); no file name that
    is loaded by name (`CLAUDE.md`, `conftest.py`, `Makefile`, `*.pth`); and the path must
    not exist yet, so nothing is ever overwritten.

    A git working tree is not refused as such: a menu belongs in a website repository and a
    note in a vault that is under git.
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
    if root == home and _is_library(home, rel[0]):
        raise DestinationError("--out must not lie under ~/Library")
    if _is_autoloaded(target.name):
        raise DestinationError(
            "--out must not be a file name that is loaded automatically "
            "(agent instructions, Python start-up files, make files)"
        )
    if target.exists() or target.is_symlink():
        raise DestinationError("--out already exists; nothing is overwritten")
    return target


def _is_library(home: Path, first: str) -> bool:
    """True when `first` names ~/Library. macOS file systems are usually case-insensitive,
    so `~/library` IS `~/Library`: compare the spelling case-folded and, where both exist,
    by file identity."""
    if first.casefold() == "library":
        return True
    try:
        return os.path.samefile(home / first, home / "Library")
    except OSError:
        return False


def write_exclusive(target: Path, payload: bytes) -> str:
    """Create `target` (never overwrite, never follow a link), owner-only, not executable.
    Returns the SHA-256 of what was written.

    The file is created relative to an open handle on its directory, and that handle is
    compared with the path `resolve_destination` approved. A directory swapped for a link
    between the check and the write is therefore refused instead of followed.
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    parent = target.parent
    dfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    try:
        approved = os.stat(parent.resolve())
        if parent.resolve() != parent or not os.path.samestat(os.fstat(dfd), approved):
            raise OSError("destination directory changed after it was checked")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
        fd = os.open(target.name, flags, 0o600, dir_fd=dfd)
    finally:
        os.close(dfd)
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
    if not UID_RE.fullmatch(uid):
        raise ValueError(f"uid must contain only ASCII digits, got {uid!r}")
    mb.folder.set(folder)
    msgs = list(mb.fetch(f"UID {uid}", mark_seen=False, limit=1))
    if not msgs:
        return None
    raw = list(msgs[0].attachments or ())
    if not 1 <= index <= len(raw):
        raise NoSuchAttachmentError(index)
    return list_attachments(msgs[0])[index - 1], raw[index - 1].payload or b""
