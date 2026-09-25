"""Validation of user-supplied values before they reach IMAP.

imap_tools quotes a value by escaping only `\\` and `"`; a CR/LF inside a value ends
the IMAP command line and lets the rest run as a new command. Every value that reaches
the server (search filters, folder names, UIDs) passes through `unsafe_arg_keys` first.
"""

import re

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def unsafe_arg_keys(**values: str | None) -> list[str]:
    """Names of the given values that contain a control character (ord < 32 or 127)."""
    return sorted(k for k, v in values.items() if v and _CONTROL_RE.search(v))
