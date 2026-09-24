"""Leak guard for a public repository (spec §6). Not shipped in the package.

CI mode scans only the lines a pull request ADDS (`--diff`); file mode scans whole files
and is used for the one-time local run over the full tree.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# RFC 2606 reserved names plus localhost; subdomains of these are allowed too
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "example", "localhost")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}|localhost)\b")
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?)\b")
PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+|00)\d{1,3}"  # + or 00, country code
    r"[ /-]?\(?\d{2,5}\)?[ /-]?\d{3,}(?:[ /-]?\d+)*"  # area code, number
)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    kind: str  # "public" | "private"
    label: str  # "email" | "iban" | "phone" | "private-list hit"


@dataclass(frozen=True)
class AllowEntry:
    path: str
    line_re: re.Pattern


def parse_allow(text: str) -> list[AllowEntry]:
    """Lines: `<path>:<line regex> # <reason>`. A missing reason is an error."""
    entries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        spec, sep, reason = line.partition(" # ")
        if not sep or not reason.strip():
            raise ValueError(f"allowlist entry needs ' # <reason>': {line!r}")
        path, _, rx = spec.partition(":")
        entries.append(AllowEntry(path=path.strip(), line_re=re.compile(rx)))
    return entries


def added_lines(diff_text: str) -> list[tuple[str, int, str]]:
    """(path, new line number, text) for every '+' line of a `git diff -U0`."""
    out: list[tuple[str, int, str]] = []
    path: str | None = None
    n = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None
            continue
        m = _HUNK_RE.match(line)
        if m:
            n = int(m.group(1))
            continue
        if path and line.startswith("+"):
            out.append((path, n, line[1:]))
            n += 1
    return out


def _iban_valid(candidate: str) -> bool:
    s = candidate.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(digits) % 97 == 1


def _allowed(path: str, text: str, allow: list[AllowEntry]) -> bool:
    name = Path(path).name
    return any(a.path in (path, name) and a.line_re.search(text) for a in allow)


def _email_allowed(domain: str) -> bool:
    d = domain.lower()
    return any(d == a or d.endswith("." + a) for a in ALLOWED_EMAIL_DOMAINS)


def scan_lines(entries, private_patterns, allow) -> list[Hit]:
    private = [re.compile(p, re.IGNORECASE) for p in private_patterns if p.strip()]
    hits: list[Hit] = []
    for path, n, line in entries:
        if _allowed(path, line, allow):
            continue
        if any(not _email_allowed(m.group(1)) for m in EMAIL_RE.finditer(line)):
            hits.append(Hit(path, n, "public", "email"))
        if any(_iban_valid(m.group(1)) for m in IBAN_RE.finditer(line)):
            hits.append(Hit(path, n, "public", "iban"))
        # digit groups inside an IBAN ("... 0044 0532 ...") must not read as a phone number
        if PHONE_RE.search(IBAN_RE.sub(" ", line)):
            hits.append(Hit(path, n, "public", "phone"))
        if any(rx.search(line) for rx in private):
            hits.append(Hit(path, n, "private", "private-list hit"))
    return hits


def scan_files(paths, private_patterns, allow) -> list[Hit]:
    entries = []
    for p in map(Path, paths):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        entries += [(str(p), n, line) for n, line in enumerate(text.splitlines(), start=1)]
    return scan_lines(entries, private_patterns, allow)


def report(hits: list[Hit]) -> None:
    for h in hits:
        if h.kind == "private":
            print(f"{h.path}:{h.line}: private-list hit")  # never the pattern or the text
        else:
            print(f"{h.path}:{h.line}: {h.label}")


def main(argv: list[str]) -> int:
    raw = os.environ.get("LEAK_GUARD_PRIVATE_LIST", "")
    private = [ln for ln in raw.splitlines() if ln.strip()]
    if not private:
        print("leak-guard: private list not available in this context; public patterns only")
    allow_file = Path(".leak-guard-allow")
    allow = parse_allow(allow_file.read_text(encoding="utf-8")) if allow_file.exists() else []
    if argv[:1] == ["--diff"]:
        entries = added_lines(Path(argv[1]).read_text(encoding="utf-8"))
        hits = scan_lines(entries, private, allow)
        scope = f"{len(entries)} added line(s)"
    else:
        hits = scan_files(argv, private, allow)
        scope = f"{len(argv)} file(s)"
    report(hits)
    print(f"leak-guard: {scope} scanned, {len(hits)} hit(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
