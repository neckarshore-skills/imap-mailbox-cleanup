"""Classification rules — pure functions over message metadata."""

from collections.abc import Mapping
from enum import StrEnum

LARGE_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB

# "noreply" / "no-reply" are deliberately absent: they say the sender takes no replies,
# not what the mail is. Login alerts, invoices and tickets come from such addresses.
# A noreply sender still counts as a newsletter when it carries List-Unsubscribe.
NEWSLETTER_LOCAL_PARTS = {"newsletter", "news", "marketing"}
AUTOMATED_LOCAL_PARTS = {
    "notifications",
    "notification",
    "bot",
    "service",
    "alerts",
    "system",
    "daemon",
    "automation",
}
BOUNCE_SENDER_LOCAL_PARTS = {"mailer-daemon", "postmaster"}
BOUNCE_SUBJECT_PREFIXES = (
    "undelivered",
    "returned mail",
    "mail delivery",
    "delivery status notification",
    "auto-reply",
    "out of office",
    "abwesenheits",
)


class Category(StrEnum):
    NEWSLETTER = "newsletter"
    AUTOMATED = "automated"
    BOUNCE = "bounce"
    LARGE_ATTACHMENT = "large_attachment"


def _local_part(addr: str) -> str:
    return addr.split("@", 1)[0].lower().strip("<>")


def _has_unsubscribe(headers: Mapping[str, str]) -> bool:
    return any(k.lower() == "list-unsubscribe" for k in headers.keys())


def is_newsletter(*, from_addr: str, subject: str, headers: Mapping[str, str]) -> bool:
    if _has_unsubscribe(headers):
        return True
    return _local_part(from_addr) in NEWSLETTER_LOCAL_PARTS


def is_automated(*, from_addr: str, subject: str, headers: Mapping[str, str]) -> bool:
    return _local_part(from_addr) in AUTOMATED_LOCAL_PARTS


def is_bounce(*, from_addr: str, subject: str, headers: Mapping[str, str]) -> bool:
    if _local_part(from_addr) in BOUNCE_SENDER_LOCAL_PARTS:
        return True
    s = subject.lower().lstrip()
    return any(s.startswith(p) for p in BOUNCE_SUBJECT_PREFIXES)


def is_large_attachment(*, size_bytes: int) -> bool:
    return size_bytes > LARGE_ATTACHMENT_BYTES


def classify(
    *,
    from_addr: str,
    subject: str,
    headers: Mapping[str, str],
    size_bytes: int,
) -> set[Category]:
    """Return all categories that apply to the message."""
    cats: set[Category] = set()
    if is_newsletter(from_addr=from_addr, subject=subject, headers=headers):
        cats.add(Category.NEWSLETTER)
    if is_automated(from_addr=from_addr, subject=subject, headers=headers):
        cats.add(Category.AUTOMATED)
    if is_bounce(from_addr=from_addr, subject=subject, headers=headers):
        cats.add(Category.BOUNCE)
    if is_large_attachment(size_bytes=size_bytes):
        cats.add(Category.LARGE_ATTACHMENT)
    return cats
