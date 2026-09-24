import json
from pathlib import Path

import pytest

from mailbox_cleanup.manage.frontmatter import split_frontmatter
from mailbox_cleanup.manage.sources import (
    MarkdownFolderSource,
    SourceMissingError,
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
