"""Every mail-derived string handed to the agent sits in this envelope (spec §5).

The envelope is an intention, not a mechanism: it tells the agent the content is data.
What bounds the damage is that the tool cannot send, delete or move.
"""

import re

# Escape the `<` that starts anything a reader could take for an envelope tag, closed or
# not. Matching only complete tags (`<...>`) let an unterminated `<mail-content` through,
# which then swallowed the envelope's real closing tag.
_TAG_START_RE = re.compile(r"<(?=\s*/?\s*mail-content\b)", re.IGNORECASE)


def escape(text: str) -> str:
    return _TAG_START_RE.sub("&lt;", text)


def wrap(text: str) -> str:
    return f"<mail-content>\n{escape(text)}\n</mail-content>"
