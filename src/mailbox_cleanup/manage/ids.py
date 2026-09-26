"""Shared Message-ID safety check (Task 7 dispatch ruling R1).

`Message.message_id` / `Message.references` are mail-derived, untrusted input — a
hostile mail can put arbitrary junk in its own Message-ID/References headers. The
same strict allowlist and length cap gate a Message-ID everywhere it is used as
something other than opaque display text: before it reaches IMAP as a HEADER search
value (thread.py), before it is emitted as a bare JSON string outside the
<mail-content> envelope (cli.py), and before it is copied into an outgoing reply's
In-Reply-To/References (draft.py). One definition, reused by all three.
"""

from __future__ import annotations

import re

# `<...>` with no `"`, `\`, `(`, `)`, `*`, space or control character inside — nothing
# that could break out of imap_tools' quoting (which only escapes `\` and `"`).
SAFE_MSGID_RE = re.compile(r"<[A-Za-z0-9!#$%&'+/=?^_`{|}~.@\[\]:-]+>")

# A mail can put arbitrary-length junk in its Message-ID header; this bounds it before
# the value is emitted as a bare JSON string or copied into an outgoing header.
MAX_MESSAGE_ID_LEN = 250


def safe_message_id(mid: str) -> str:
    """Return `mid` unchanged if it is a clean Message-ID (matches the strict
    allowlist and is not oversized), else "" — a value that fails either check is
    treated as absent rather than leaking whatever a hostile mail put there."""
    if not mid or len(mid) > MAX_MESSAGE_ID_LEN:
        return ""
    return mid if SAFE_MSGID_RE.fullmatch(mid) else ""
