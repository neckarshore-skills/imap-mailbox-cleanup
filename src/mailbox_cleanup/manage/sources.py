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
    """A configured source cannot deliver ANY overlays: its folder does not exist.
    Callers report it and continue without that source. A single unreadable FILE inside
    an existing folder is a narrower failure — see `MarkdownFolderSource.warnings` — and
    does not raise this: the rest of the folder still loads (Task 9 R5)."""


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
        # Task 9 R5: files skipped by the LAST overlays() call, one warning per file,
        # naming the file only — never its content. Read by the playbook loader after a
        # successful call; a caller that never reads it loses nothing (it stays []).
        self.warnings: list[str] = []

    def overlays(self) -> list[Overlay]:
        if not self.path.is_dir():
            raise SourceMissingError(f"overlay folder not found: {self.path}")
        self.warnings = []
        out = []
        for md in sorted(self.path.rglob("*.md")):
            try:
                meta, body = split_frontmatter(md.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
                # OSError also catches a directory literally named "*.md" (rglob matches
                # it, read_text() raises IsADirectoryError) and a permission failure —
                # not just the YAML/Unicode cases this originally guarded against.
                self.warnings.append(f"overlay file unreadable: {md} ({type(e).__name__})")
                continue
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
