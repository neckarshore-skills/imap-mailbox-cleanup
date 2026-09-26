import json
from pathlib import Path

import pytest

from mailbox_cleanup.manage.frontmatter import split_frontmatter
from mailbox_cleanup.manage.sources import (
    MarkdownFolderSource,
    SourceMissingError,
    SourcesConfigError,
    load_sources,
    sources_path,
)


def test_split_frontmatter():
    meta, body = split_frontmatter("---\nextends: school\n---\nText\n")
    assert meta == {"extends": "school"} and body == "Text\n"
    assert split_frontmatter("no frontmatter") == ({}, "no frontmatter")


def test_folder_source_reads_overlays_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("---\nextends: school\n---\nKlasse 4b\n", encoding="utf-8")
    (tmp_path / "sub" / "b.md").write_text("---\nextends: bank\n---\nKonto\n", encoding="utf-8")
    (tmp_path / "note.md").write_text("no frontmatter, ignored\n", encoding="utf-8")
    got = sorted((o.playbook_id, o.body.strip()) for o in MarkdownFolderSource(tmp_path).overlays())
    assert got == [("bank", "Konto"), ("school", "Klasse 4b")]


def test_missing_folder_raises(tmp_path):
    with pytest.raises(SourceMissingError):
        MarkdownFolderSource(tmp_path / "nope").overlays()


def test_sources_file_order_kept(tmp_path, monkeypatch):
    f = tmp_path / "sources.json"
    f.write_text(
        json.dumps({"schema_version": 1, "folders": [str(tmp_path / "x"), str(tmp_path / "y")]})
    )
    monkeypatch.setenv("MAILBOX_CLEANUP_SOURCES", str(f))
    assert [s.name for s in load_sources()] == [str(tmp_path / "x"), str(tmp_path / "y")]


def test_sources_survive_account_config_rewrite(tmp_path, monkeypatch):
    """Review Focus 2: config set-default rewrites config.json; sources.json is untouched
    and load_sources() still returns the configured folder afterwards."""
    from click.testing import CliRunner

    from mailbox_cleanup.cli import cli
    from mailbox_cleanup.config import Account, Config, save_config

    monkeypatch.setenv("MAILBOX_CLEANUP_CONFIG", str(tmp_path / "config.json"))
    overlays = tmp_path / "overlays"
    src = tmp_path / "sources.json"
    src.write_text(json.dumps({"schema_version": 1, "folders": [str(overlays)]}))
    monkeypatch.setenv("MAILBOX_CLEANUP_SOURCES", str(src))
    save_config(
        Config(
            default="a",
            accounts=(
                Account(alias="a", email="a@example.com", server="imap.example.com"),
                Account(alias="b", email="b@example.com", server="imap.example.com"),
            ),
        )
    )
    res = CliRunner().invoke(cli, ["config", "set-default", "b"])
    assert res.exit_code == 0, res.output
    assert json.loads(src.read_text())["folders"] == [str(overlays)]
    assert [s.name for s in load_sources()] == [str(overlays)]


def test_missing_sources_file_means_no_sources():
    assert load_sources() == []


def test_tests_never_see_the_real_sources_file():
    assert sources_path() != Path.home() / ".mailbox-cleanup" / "sources.json"


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version": 1, "folders": "/somewhere/vault"}',
        '{"schema_version": 1, "folders": [""]}',
        '{"schema_version": 1, "folders": ["relative/path"]}',
        '{"schema_version": 1, "folders": [1]}',
        '{"schema_version": 1, "folders": null}',
        '["/a"]',
        "{not json",
    ],
)
def test_malformed_sources_file_is_rejected_loudly(tmp_path, monkeypatch, content):
    """A string instead of a list used to be iterated per character, so "/" became a source
    that would scan the whole disk. Anything but a list of absolute paths is refused."""
    f = tmp_path / "sources.json"
    f.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MAILBOX_CLEANUP_SOURCES", str(f))
    with pytest.raises(SourcesConfigError, match="sources.json"):
        load_sources()


@pytest.mark.parametrize(
    "raw",
    [b"---\nextends: [unclosed\n---\nbody\n", b"---\nextends: generic\n---\n\xff\xfe bad\n"],
)
def test_unreadable_overlay_file_is_skipped_not_crashed(tmp_path, raw):
    """Task 9 R5: one broken note must not escape as a raw YAML or Unicode error, AND must
    not drop the rest of the folder either — it is skipped, named in `.warnings` (never
    its content), while a good file alongside it still loads."""
    (tmp_path / "bad.md").write_bytes(raw)
    (tmp_path / "good.md").write_text("---\nextends: school\n---\nKlasse 4b\n", encoding="utf-8")
    src = MarkdownFolderSource(tmp_path)
    overlays = src.overlays()
    assert [(o.playbook_id, o.body.strip()) for o in overlays] == [("school", "Klasse 4b")]
    joined = " ".join(src.warnings)
    assert "bad.md" in joined
    assert "unclosed" not in joined and "\xff" not in joined


def test_folder_with_only_a_broken_file_returns_no_overlays_not_an_exception(tmp_path):
    """The narrower case: nothing else in the folder to salvage — still no exception, just
    an empty overlay list plus the named warning."""
    (tmp_path / "bad.md").write_bytes(b"---\nextends: [unclosed\n---\nbody\n")
    src = MarkdownFolderSource(tmp_path)
    assert src.overlays() == []
    assert any("bad.md" in w for w in src.warnings)


def test_warnings_do_not_survive_a_later_call_whose_folder_is_now_missing(tmp_path):
    """Fix round 1 M6: reset self.warnings BEFORE the folder-exists check, not after — a
    stale warning list from an earlier successful call must not outlive a later call that
    finds the folder gone."""
    (tmp_path / "bad.md").write_bytes(b"---\nextends: [unclosed\n---\nbody\n")
    src = MarkdownFolderSource(tmp_path)
    src.overlays()
    assert src.warnings != []  # sanity: the first call did warn
    for p in tmp_path.iterdir():
        p.unlink()
    tmp_path.rmdir()
    with pytest.raises(SourceMissingError):
        src.overlays()
    assert src.warnings == []
