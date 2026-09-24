"""Every mail-derived string handed to the agent sits in this envelope (spec §5).

The envelope is an intention, not a mechanism: it tells the agent the content is data.
What bounds the damage is that the tool cannot send, delete or move.
"""

import re

_TAG_RE = re.compile(r"<\s*(/?)\s*mail-content\b[^>]*>", re.IGNORECASE)


def escape(text: str) -> str:
    return _TAG_RE.sub(lambda m: f"&lt;{m.group(1)}mail-content&gt;", text)


def wrap(text: str) -> str:
    return f"<mail-content>\n{escape(text)}\n</mail-content>"
