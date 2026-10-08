"""`manage compose`: build a NEW RFC 5322 mail for the Drafts folder (compose design,
docs/2026-10-08-compose-design.md).

Nothing is ever sent; the message built here is handed to `draft.save_draft`, which
appends it to Drafts. Unlike a reply, a new mail has no original to take the recipient
from: every address is caller input. So the address rule is stricter than the reply's —
a value that is not exactly one bare ASCII address is refused instead of dropped with a
warning, because a draft that silently lost a recipient reads like a finished one.
"""

from __future__ import annotations

from collections.abc import Sequence
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .headers import STRICT_ADDR_RE, clean_header_value

# To and Cc together. A mail that deceived the agent into addressing a crowd is stopped
# here, not by a human counting recipients in a draft.
MAX_RECIPIENTS = 10


class ComposeError(ValueError):
    """A refused header value. The message names the option and the rule, never the
    value: it ends up in the command's output next to mail-derived text."""


def _check_addresses(option: str, values: Sequence[str]) -> list[str]:
    for value in values:
        # isascii(): EmailMessage writes a non-ASCII address as an encoded-word inside
        # the addr-spec (measured on Python 3.11: `=?utf-8?q?m=C3=BCller?=@example.org`),
        # which no mail client reads as the address that was typed.
        if not (value.isascii() and STRICT_ADDR_RE.fullmatch(value)):
            raise ComposeError(
                f"{option} takes one bare ASCII address per use (name@example.org), "
                "without a display name; repeat the option for more recipients"
            )
    return list(values)


def build_new(
    *,
    from_addr: str,
    to: Sequence[str],
    cc: Sequence[str] = (),
    subject: str,
    body: str,
) -> EmailMessage:
    """Build an in-memory RFC 5322 mail with To, Cc and Subject. Never touches the network.

    No Bcc, no attachment and no threading header is ever set: this builder has no
    parameter for them (design §1, non-goals 2 to 4).
    """
    to_addrs = _check_addresses("--to", to)
    cc_addrs = _check_addresses("--cc", cc)
    if not to_addrs:
        raise ComposeError("--to is required: a draft needs at least one recipient")
    if len(to_addrs) + len(cc_addrs) > MAX_RECIPIENTS:
        raise ComposeError(f"--to and --cc together take at most {MAX_RECIPIENTS} addresses")
    clean_subject = clean_header_value(subject)
    if not clean_subject:
        raise ComposeError("--subject is required and must not be blank")

    msg = EmailMessage()
    msg["Subject"] = clean_subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] or None)
    msg.set_content(body)
    return msg
