"""`manage draft`: build an RFC 5322 reply and IMAP-APPEND it to Drafts (spec §7).

Nothing is ever sent — see tests/test_no_send.py, which forbids any send-mail call in
`src/`. A draft is appended with the \\Draft flag; the manage layer never creates a
Drafts folder on a guess (spec §7.2) and never deletes, moves or flags-as-deleted
(tests/test_manage_no_destructive.py).
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from imap_tools import MailMessageFlags

from ..folders import resolve_folder
from .ids import safe_message_id
from .read import Message

_RE_PREFIX = re.compile(r"^\s*(re|aw|antw)\s*:", re.IGNORECASE)

# R3: EmailMessage() (default policy) raises ValueError on a raw CR/LF in a header
# value; a hostile decoded Subject/To must still produce a draft. Control characters and
# whitespace runs (including CR/LF) collapse to a single space before a header is set.
_CONTROL_OR_WS_RUN_RE = re.compile(r"[\x00-\x1f\x7f]+|\s+")

# R1: cap the outgoing References chain at the tail of this many IDs (the most recent
# ancestors plus the original's own Message-ID, always last) — the same "keep the tail"
# shape as thread._MAX_IDS. A very long legitimate thread loses its oldest ancestors in
# the header, never its most recent ones — harmless for threading, which keys on
# In-Reply-To and the last IDs.
_MAX_REFERENCES = 20


class NoDraftsFolderError(Exception):
    """No \\Drafts folder was found. Spec §7.2: stop; never create one on a guess."""


def _clean_header_value(value: str) -> str:
    return _CONTROL_OR_WS_RUN_RE.sub(" ", value).strip()


def build_reply(original: Message, *, from_addr: str, body: str) -> tuple[EmailMessage, list[str]]:
    """Build an in-memory RFC 5322 reply. Never touches the network.

    Threading (In-Reply-To/References) is attempted only when `original.message_id` is
    present and passes the same strict allowlist used before a Message-ID reaches IMAP
    as a search value (R1 of the Task 7 dispatch ruling) — a mail's own References
    header is likewise untrusted, so each entry is checked the same way before it is
    copied into the outgoing header, and the chain is capped to its most recent
    `_MAX_REFERENCES` ids. The returned warnings are for the human, not the audit log.
    """
    warnings: list[str] = []
    msg = EmailMessage()

    subject = _clean_header_value(original.subject or "")
    msg["Subject"] = subject if _RE_PREFIX.match(subject) else f"Re: {subject}".strip()
    msg["From"] = from_addr
    msg["To"] = _clean_header_value(original.reply_to or original.sender)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] or None)

    mid = original.message_id
    if not mid:
        warnings.append("original has no Message-ID; draft is not threaded")
    elif safe_message_id(mid) != mid:
        warnings.append("original Message-ID is malformed; draft is not threaded")
    else:
        msg["In-Reply-To"] = mid
        clean_refs = [r for r in original.references if safe_message_id(r) == r]
        dropped = len(original.references) - len(clean_refs)
        if dropped:
            suffix = "y" if dropped == 1 else "ies"
            warnings.append(f"dropped {dropped} malformed References entr{suffix}")
        chain = [r for r in clean_refs if r != mid]
        full_chain = [*chain, mid]
        if len(full_chain) > _MAX_REFERENCES:
            full_chain = full_chain[-_MAX_REFERENCES:]
            warnings.append(f"References chain trimmed to the last {_MAX_REFERENCES} IDs")
        msg["References"] = " ".join(full_chain)

    msg.set_content(body)
    return msg, warnings


def save_draft(mb, msg: EmailMessage) -> str:
    """IMAP-APPEND `msg` into the resolved Drafts folder with the \\Draft flag.

    Raises NoDraftsFolderError instead of creating one (spec §7.2) — never appends
    anything when no Drafts folder is found.
    """
    folder = resolve_folder(mb, "drafts")
    if folder is None:
        raise NoDraftsFolderError("No \\Drafts folder found; create it in your mail client")
    mb.append(msg.as_bytes(), folder, flag_set=[MailMessageFlags.DRAFT])
    return folder
