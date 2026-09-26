"""Public playbooks (generic German reply text, shipped inside the package) merged with
the owner's private overlays (Task 8's `sources.KnowledgeSource`). Spec §4."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources

from .frontmatter import split_frontmatter
from .sources import KnowledgeSource, Overlay, SourceMissingError


@dataclass(frozen=True)
class Playbook:
    id: str
    recognition: tuple[str, ...]
    tone: str
    body: str
    overlay: Overlay | None = None


@dataclass
class LoadResult:
    playbooks: dict[str, Playbook]
    warnings: list[str] = field(default_factory=list)


def public_playbooks() -> dict[str, str]:
    """Filename stem -> Markdown text, for every ``*.md`` file shipped inside the
    package's own ``playbooks/`` folder. `importlib.resources` so this works from an
    installed wheel too, not just a source checkout (spec §3).

    Fix round 1 M1/M4: `Path.iterdir()` order depends on the filesystem, which would
    make both `manage playbooks`' listing order and "which file wins on a duplicate id"
    (M4) non-deterministic. Sorted by filename here, once, at the source."""
    root = resources.files("mailbox_cleanup.manage").joinpath("playbooks")
    names = sorted(p.name for p in root.iterdir() if p.name.endswith(".md"))
    return {name[:-3]: root.joinpath(name).read_text(encoding="utf-8") for name in names}


def _parse_recognition(value: object, name: str, warnings: list[str]) -> tuple[str, ...]:
    """R4: a plain string used to become a tuple of its individual characters through
    ``tuple(...)``. A string is accepted as a one-element list; non-string items inside a
    list are dropped silently; anything else (not a list, not a string, not absent)
    becomes an empty tuple plus a loud warning naming the playbook, never a silent
    character-split."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(v for v in value if isinstance(v, str))
    warnings.append(f"{name}: recognition must be a list of strings; ignoring")
    return ()


def _parse_tone(value: object, name: str, warnings: list[str]) -> str:
    """Fix round 1 M3: `str(["a", "b"])` used to produce the literal `"['a', 'b']"`. A
    list of strings is now joined with ", "; a plain string passes through unchanged;
    anything else (a list with a non-string item, a number, a mapping, ...) becomes an
    empty tone plus a warning naming the playbook, never a silently-wrong rendering."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return ", ".join(value)
    warnings.append(f"{name}: tone must be a string or a list of strings; ignoring")
    return ""


def load_playbooks(public: dict[str, str], sources: Sequence[KnowledgeSource]) -> LoadResult:
    """Parse the public playbooks, then apply at most one private overlay per playbook id
    (first configured source wins; every later claim on the same id becomes a warning,
    never a silent overwrite). A source whose folder is missing entirely is skipped with a
    warning; the public playbooks and any other configured source still load (R2: "the
    generic playbook only" means the public set without that source's overlays, not just
    the id "generic"). A single unreadable FILE inside an otherwise-readable folder does
    NOT drop that whole source (R5): `MarkdownFolderSource` skips just that file and this
    loader folds its per-file warning in alongside its own."""
    warnings: list[str] = []
    books: dict[str, Playbook] = {}
    book_stems: dict[str, str] = {}  # M4: pid -> the stem that first claimed it
    for stem, text in public.items():
        meta, body = split_frontmatter(text)
        raw_id = meta.get("id")
        pid = raw_id if isinstance(raw_id, str) and raw_id else stem
        if pid in books:
            warnings.append(
                f"playbook id {pid!r} declared by both {book_stems[pid]!r} and {stem!r}; "
                f"keeping {book_stems[pid]!r}"
            )
            continue
        recognition = _parse_recognition(meta.get("recognition"), pid, warnings)
        tone = _parse_tone(meta.get("tone"), pid, warnings)
        books[pid] = Playbook(pid, recognition, tone, body)
        book_stems[pid] = stem

    chosen: dict[str, tuple[str, Overlay]] = {}
    for src in sources:
        try:
            overlays = src.overlays()
        except SourceMissingError as e:
            warnings.append(str(e))
            continue
        # R5: a source MAY skip individual unreadable files rather than failing outright
        # (MarkdownFolderSource does); those per-file warnings surface here too. A source
        # without this attribute (e.g. a future non-file-based KnowledgeSource) is
        # unaffected — getattr defaults to no extra warnings.
        warnings.extend(getattr(src, "warnings", ()))
        for ov in overlays:
            if ov.playbook_id not in books:
                warnings.append(f"overlay {ov.origin} extends unknown playbook {ov.playbook_id!r}")
                continue
            if ov.playbook_id in chosen:
                first_src, first_ov = chosen[ov.playbook_id]
                if first_src == src.name:
                    # M2: both overlays came from the SAME folder — naming the source
                    # twice ("overlaid by /x and /x") says nothing; name the two files.
                    warnings.append(
                        f"playbook {ov.playbook_id!r} overlaid twice within {src.name} "
                        f"({first_ov.origin} and {ov.origin}); using {first_ov.origin}"
                    )
                else:
                    warnings.append(
                        f"playbook {ov.playbook_id!r} overlaid by {first_src} and {src.name}; "
                        f"using {first_src}"
                    )
                continue
            chosen[ov.playbook_id] = (src.name, ov)

    for pid, (_, ov) in chosen.items():
        b = books[pid]
        books[pid] = Playbook(b.id, b.recognition, b.tone, b.body, ov)

    return LoadResult(books, warnings)
