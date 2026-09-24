"""Private playbook overlays from local Markdown folders (spec §4). A GitHub-API
source is a later KnowledgeSource implementation; nothing here needs replacing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from .frontmatter import split_frontmatter

SOURCES_PATH_ENV = "MAILBOX_CLEANUP_SOURCES"
DEFAULT_SOURCES_PATH = Path.home() / ".mailbox-cleanup" / "sources.json"


class SourceMissingError(Exception):
    """A configured source cannot deliver overlays: the folder is missing, or one of its
    files cannot be read. Callers report it and continue without that source."""


class SourcesConfigError(ValueError):
    """sources.json does not have the documented shape. Refused rather than guessed: a
    string where a list belongs used to become one source per character, "/" included."""


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
            try:
                meta, body = split_frontmatter(md.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, yaml.YAMLError) as e:
                raise SourceMissingError(
                    f"overlay file unreadable: {md} ({type(e).__name__})"
                ) from e
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
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SourcesConfigError(f"{p}: sources.json is not valid JSON ({e.msg})") from e
    folders = data.get("folders", []) if isinstance(data, dict) else None
    if not isinstance(folders, list):
        raise SourcesConfigError(f'{p}: sources.json needs "folders" as a list of paths')
    paths = []
    for f in folders:
        if not isinstance(f, str) or not f.strip():
            raise SourcesConfigError(f"{p}: sources.json folder entries must be paths")
        path = Path(f).expanduser()
        if not path.is_absolute():
            raise SourcesConfigError(f"{p}: sources.json folder must be absolute: {f}")
        paths.append(path)
    return [MarkdownFolderSource(path) for path in paths]
