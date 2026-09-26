from mailbox_cleanup.manage.playbooks import load_playbooks, public_playbooks
from mailbox_cleanup.manage.sources import MarkdownFolderSource, Overlay, SourceMissingError

PUB = {
    "school": "---\nid: school\nrecognition: [Elternabend, Klasse]\ntone: freundlich\n---\nText\n",
    "generic": "---\nid: generic\nrecognition: []\ntone: neutral\n---\nGenerisch\n",
}


class _Src:
    def __init__(self, name, overlays=None, missing=False):
        self.name, self._o, self._missing = name, overlays or [], missing

    def overlays(self):
        if self._missing:
            raise SourceMissingError(f"overlay folder not found: {self.name}")
        return self._o


def test_first_source_wins_and_second_warns():
    a = _Src("A", [Overlay("school", "from A", "A/x.md")])
    b = _Src("B", [Overlay("school", "from B", "B/y.md")])
    r = load_playbooks(PUB, [a, b])
    assert r.playbooks["school"].overlay.body == "from A"
    assert any("school" in w and "A" in w and "B" in w for w in r.warnings)


def test_missing_source_warns_and_continues():
    r = load_playbooks(PUB, [_Src("gone", missing=True)])
    assert set(r.playbooks) == {"school", "generic"}
    assert r.warnings == ["overlay folder not found: gone"]


def test_overlay_for_unknown_playbook_warns():
    r = load_playbooks(PUB, [_Src("A", [Overlay("pension", "x", "A/p.md")])])
    assert any("pension" in w for w in r.warnings)


def test_shipped_playbooks_parse_and_include_generic():
    pub = public_playbooks()
    assert {"generic", "recruiter", "school", "bank", "insurance"} <= set(pub)
    r = load_playbooks(pub, [])
    assert r.warnings == []


# --- R2: a missing overlay source disables only ITS overlays, not other playbooks ------


def test_missing_source_leaves_other_sources_and_playbooks_intact():
    """R2's reading: "generic" means the public playbooks without the missing source's
    overlays, never just the id "generic" — a second, working source must still apply,
    and playbooks with no overlay at all must still be present and usable."""
    working = _Src("ok", [Overlay("school", "from ok", "ok/school.md")])
    r = load_playbooks(PUB, [_Src("gone", missing=True), working])
    assert set(r.playbooks) == {"school", "generic"}
    assert r.playbooks["school"].overlay.body == "from ok"
    assert r.playbooks["generic"].overlay is None
    assert any("gone" in w for w in r.warnings)


# --- R4: recognition frontmatter type validation ----------------------------------------


def test_recognition_as_plain_string_becomes_one_element_not_split_into_characters():
    """Without the fix, tuple("Elternabend") would split into 11 single-character
    elements ('E', 'l', 't', ...) instead of the one recognition hint intended."""
    pub = {"school": ("---\nid: school\nrecognition: Elternabend\ntone: freundlich\n---\nText\n")}
    r = load_playbooks(pub, [])
    assert r.playbooks["school"].recognition == ("Elternabend",)


def test_recognition_drops_non_string_items_silently():
    pub = {"school": "---\nid: school\nrecognition: [Elternabend, 3, null]\n---\nText\n"}
    r = load_playbooks(pub, [])
    assert r.playbooks["school"].recognition == ("Elternabend",)
    assert r.warnings == []


def test_recognition_of_wrong_type_becomes_empty_tuple_with_named_warning():
    pub = {"school": "---\nid: school\nrecognition: 42\n---\nText\n"}
    r = load_playbooks(pub, [])
    assert r.playbooks["school"].recognition == ()
    assert any("school" in w and "recognition" in w for w in r.warnings)


def test_missing_id_falls_back_to_file_stem():
    pub = {"custom": "---\ntone: neutral\n---\nText\n"}
    r = load_playbooks(pub, [])
    assert set(r.playbooks) == {"custom"}
    assert r.playbooks["custom"].id == "custom"


# --- R5: one broken overlay file does not drop the rest of its own folder --------------


def test_broken_overlay_file_warns_but_sibling_overlay_still_applies(tmp_path):
    """End-to-end through the loader (not just MarkdownFolderSource in isolation): a
    folder with one broken file and one good file yields the good overlay AND a warning
    naming the broken file, not a dropped source and not a crash."""
    (tmp_path / "bad.md").write_bytes(b"---\nextends: [unclosed\n---\nbody\n")
    (tmp_path / "good.md").write_text("---\nextends: school\n---\nKlasse 4b\n", encoding="utf-8")
    r = load_playbooks(PUB, [MarkdownFolderSource(tmp_path)])
    assert r.playbooks["school"].overlay.body.strip() == "Klasse 4b"
    assert any("bad.md" in w for w in r.warnings)


# --- R6: shipped playbooks are real German, not ASCII transliteration ------------------


def test_shipped_playbook_body_has_non_ascii_and_round_trips():
    pub = public_playbooks()
    for stem, text in pub.items():
        assert any(ord(ch) > 127 for ch in text), f"{stem}.md has no non-ASCII character"
    # round-trip: the same bytes read back through split_frontmatter keep the umlaut
    from mailbox_cleanup.manage.frontmatter import split_frontmatter

    _, body = split_frontmatter(pub["school"])
    assert "ä" in body or "ü" in body or "ö" in body or "ß" in body
