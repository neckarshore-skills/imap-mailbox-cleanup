import os
import time
from contextlib import contextmanager

from imap_tools import MailBox, MailBoxUnencrypted

from .auth import Credentials

SSL_ENV = "MAILBOX_CLEANUP_SSL"  # set to "0" to disable SSL (used by Greenmail tests)


class IMAPConnectionError(Exception):
    pass


@contextmanager
def imap_connect(
    creds: Credentials,
    *,
    port: int = 993,
    ssl: bool | None = None,
    max_retries: int = 2,
):
    """Connect to IMAP with single retry on transient failures.

    Production: ssl=True (port 993, IMAPS). Tests: env MAILBOX_CLEANUP_SSL=0 → plain.
    Backoff: 2s, 4s. After max_retries exhausted, raises IMAPConnectionError.
    """
    if ssl is None:
        ssl = os.environ.get(SSL_ENV, "1") != "0"
    Cls = MailBox if ssl else MailBoxUnencrypted
    # Only connect + login are retried. The body runs once: an exception from it must
    # reach the caller unchanged, never be caught here and "retried" by yielding again.
    for attempt in range(max_retries + 1):
        try:
            mb = Cls(creds.server, port=port).login(creds.email, creds.password)
            break
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise IMAPConnectionError(
                f"Failed to connect to {creds.server}:{port} as {creds.email}: {e}"
            ) from e
    try:
        yield mb
    finally:
        mb.logout()
