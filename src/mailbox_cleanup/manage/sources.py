"""Private playbook overlays from local Markdown folders (spec §4). A GitHub-API
source is a later KnowledgeSource implementation; nothing here needs replacing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .frontmatter import split_frontmatter

SOURCES_PATH_ENV = "MAILBOX_CLEANUP_SOURCES"
DEFAULT_SOURCES_PATH = Path.home() / ".mailbox-cleanup" / "sources.json"


class SourceMissingError(Exception):
    pass


@dataclass(frozen=True)
class Overlay:
    playbook_id: str
    body: str
    origin: str


class KnowledgeSource(Protocol):
    name: str

    def overlays(self) -> list[Overlay]: ...


class MarkdownFolderSource:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        self.name = str(self.path)

    def overlays(self) -> list[Overlay]:
        if not self.path.is_dir():
            raise SourceMissingError(f"overlay folder not found: {self.path}")
        out = []
        for md in sorted(self.path.rglob("*.md")):
            meta, body = split_frontmatter(md.read_text(encoding="utf-8"))
            pid = meta.get("extends")
            if isinstance(pid, str) and pid:
                out.append(Overlay(playbook_id=pid, body=body, origin=str(md)))
        return out


def sources_path() -> Path:
    override = os.environ.get(SOURCES_PATH_ENV)
    return Path(override) if override else DEFAULT_SOURCES_PATH


def load_sources() -> list[KnowledgeSource]:
    p = sources_path()
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [MarkdownFolderSource(Path(f)) for f in data.get("folders", [])]
