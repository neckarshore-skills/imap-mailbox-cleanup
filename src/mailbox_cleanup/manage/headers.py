"""Header values for outgoing drafts: one definition, used by the reply builder
(`draft.py`) and the new-mail builder (`compose.py`).

Both builders write values that did not originate in this program — a reply takes them
from the mail being answered, a new mail from the command line — so both pass through
the same two checks before a header is set.
"""

from __future__ import annotations

import re

# EmailMessage() (default policy) raises ValueError on a raw CR/LF in a header value; a
# hostile Subject must still produce a draft. Control characters (C0 `\x00-\x1f`, DEL
# `\x7f`, and C1 `\x80-\x9f` — e.g. U+0085 NEL, which some decoders treat as a line
# break) and whitespace runs collapse to a single space before a header is set.
_CONTROL_OR_WS_RUN_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+|\s+")

# A strict addr-spec — exactly one '@', a non-empty local part and domain, no whitespace,
# angle bracket, comma, quote or control character. `@` itself is excluded from both
# sides too, so "exactly one '@'" is structural, not just a side-effect of `fullmatch` —
# a second '@' anywhere fails the whole match.
STRICT_ADDR_RE = re.compile(r'^[^\s<>,"@\x00-\x1f\x7f-\x9f]+@[^\s<>,"@\x00-\x1f\x7f-\x9f]+$')


def clean_header_value(value: str) -> str:
    return _CONTROL_OR_WS_RUN_RE.sub(" ", value).strip()
