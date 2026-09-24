"""Resolve logical folder names (trash, archive) to actual IMAP folder paths.

RFC 6154 SPECIAL-USE flags are preferred. Falls back to literal names per IONOS
German default UI.
"""

TRASH_FALLBACKS = ("Papierkorb", "Trash", "Deleted Messages", "Deleted Items")
ARCHIVE_FALLBACKS = ("Archive", "Archiv")
DRAFTS_FALLBACKS = ("Drafts", "Entwürfe", "Entwuerfe")

_SPECIAL_USE_FLAGS = {
    "trash": "\\Trash",
    "archive": "\\Archive",
    "sent": "\\Sent",
    "drafts": "\\Drafts",
    "junk": "\\Junk",
}

_FALLBACKS = {
    "trash": TRASH_FALLBACKS,
    "archive": ARCHIVE_FALLBACKS,
    "drafts": DRAFTS_FALLBACKS,
}


def resolve_folder(mailbox, kind: str) -> str | None:
    """Return the actual folder path for a logical kind, or None if not found.

    Looks first for a folder with the SPECIAL-USE flag matching `kind`,
    then for a folder whose name matches one of the literal fallbacks.
    """
    folders = list(mailbox.folder.list())
    target_flag = _SPECIAL_USE_FLAGS.get(kind)
    if target_flag:
        for f in folders:
            if target_flag in (f.flags or ()):
                return f.name
    for fallback in _FALLBACKS.get(kind, ()):
        for f in folders:
            if f.name == fallback:
                return f.name
    return None
