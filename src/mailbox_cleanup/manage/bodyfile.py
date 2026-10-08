"""Where the text of a draft is read from: the tool's own outbox folder, nothing else.

`manage draft` and `manage compose` take their text from `--body-file`. The caller is an
agent that has just read mail, and a mail can ask for anything. A free file read next to
a recipient (free in `compose`; in `draft` the sender of the answered mail, who in the
attack case is the attacker) would let ONE command stage any readable local file as a
draft. So the file must lie directly in one private folder that only this tool uses.

What this does and does not do: it removes the one-command path. It does not stop an
agent that first copies a file into the folder; the skill text forbids that, and that is
an instruction, not a mechanism.

Why a folder of our own and not the temp directory (the first attempt): the temp
directory is taken from TMPDIR, which the constrained caller sets, it is shared with
every other program, and `/tmp` is world-writable.
"""

from __future__ import annotations

import os
import pwd
import stat

MAX_BODY_BYTES = 1024 * 1024

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)


def _default_outbox() -> str:
    """`~/.mailbox-cleanup/outbox`, with the home directory from the user database. Not
    from HOME or any other variable: the caller this rule constrains controls the
    environment of the command it builds."""
    home = pwd.getpwuid(os.getuid()).pw_dir
    return os.path.join(home, ".mailbox-cleanup", "outbox")


def outbox_dir() -> str:
    return _default_outbox()


def _open_outbox() -> int | None:
    """A descriptor of the outbox, or None unless it is a real directory (not a symlink)
    that belongs to this user and that nobody else can enter or list."""
    try:
        fd = os.open(outbox_dir(), _DIR_FLAGS)
    except OSError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        os.close(fd)
        return None
    return fd


def ensure_outbox() -> str | None:
    """Create the outbox (mode 0700) when it is missing and return its path, or None when
    what is there is not usable. An existing folder is never changed."""
    path = outbox_dir()
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError:
        return None
    fd = _open_outbox()
    if fd is None:
        return None
    os.close(fd)
    return path


def read_body_file(body_file: str) -> str | None:
    """The text of `body_file`, or None unless it is a regular UTF-8 file of at most
    MAX_BODY_BYTES that lies directly in the outbox, belongs to this user and has no second
    name (hard link).

    The path only names the file. It is not opened by path: the outbox is opened first and
    the file is opened by name relative to that descriptor, without following a symlink,
    so nothing on the way can be swapped between a check and the open. A FIFO would make a
    blocking open wait forever for a writer, so the open is non-blocking and the type is
    checked on the descriptor that is then read. The size cap is enforced on the bytes
    read, not on the size the file system reports."""
    absolute = os.path.abspath(body_file)
    parent, name = os.path.split(absolute)
    if name in ("", ".", "..") or body_file != absolute:
        return None  # a bare or relative name depends on the working directory
    if os.path.realpath(parent) != os.path.realpath(outbox_dir()):
        return None
    box = _open_outbox()
    if box is None:
        return None
    try:
        try:
            fd = os.open(name, _FILE_FLAGS, dir_fd=box)
        except OSError:
            return None
    finally:
        os.close(box)
    try:
        st = os.fstat(fd)
        # One name only: a hard link to an existing file is a regular file and no symlink,
        # and linking copies nothing. A file written fresh for a draft has one name.
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
            return None
        with os.fdopen(os.dup(fd), "rb") as f:
            raw = f.read(MAX_BODY_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(raw) > MAX_BODY_BYTES:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
