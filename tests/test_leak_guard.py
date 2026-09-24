import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "leak_guard", Path(__file__).parent.parent / "scripts" / "leak_guard.py"
)
lg = importlib.util.module_from_spec(_SPEC)
sys.modules["leak_guard"] = lg  # dataclasses need the module registered
_SPEC.loader.exec_module(lg)


def _scan(text, private=(), allow=(), path="a.py"):
    entries = [(path, n, line) for n, line in enumerate(text.splitlines(), start=1)]
    return lg.scan_lines(entries, list(private), list(allow))


def test_example_domains_and_non_addresses_pass():
    text = (
        "x = 'anna@example.com'\n"
        "y = 'bot@example.org'\n"
        "z = 'test@localhost'\n"
        "w = '<a@x.example>'\n"
        "- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        "t = 'u@x'\n"
        "/plugin install mailbox-autopilot@neckarshore-ai\n"
    )
    assert _scan(text) == []


def test_real_looking_address_hits():
    hits = _scan("x = 'jane.doe@some-company.test'\n")
    assert [(h.line, h.kind, h.label) for h in hits] == [(1, "public", "email")]


def test_valid_iban_hits_invalid_does_not():
    hits = _scan("ok DE89 3704 0044 0532 0130 00\nnot DE00 1234 5678 9012 3456 78\n")
    assert [(h.line, h.label) for h in hits] == [(1, "iban")]


def test_international_phone_hits():
    hits = _scan("call +49 711 1234567 now\nversion 1.2.3456789\n")
    assert [(h.line, h.label) for h in hits] == [(1, "phone")]


def test_private_hit_never_reveals_pattern_or_text(capsys):
    hits = _scan("hello Zwergenhausen\n", private=[r"zwergenhausen"], path="a.md")
    assert [(h.kind, h.label) for h in hits] == [("private", "private-list hit")]
    lg.report(hits)
    out = capsys.readouterr().out
    assert "a.md:1: private-list hit" in out
    assert "wergenhausen" not in out.lower()


def test_allowlist_exempts_with_reason():
    allow = lg.parse_allow("pyproject.toml:^authors = # package metadata author line\n")
    line = 'authors = [{name = "X", email = "x@owner.test"}]\n'
    assert _scan(line, allow=allow, path="pyproject.toml") == []


def test_allowlist_entry_without_reason_is_rejected():
    with pytest.raises(ValueError):
        lg.parse_allow("pyproject.toml:^authors = \n")


def test_added_lines_parses_unified_zero_context_diff():
    diff = (
        "diff --git a/n.md b/n.md\n"
        "--- a/n.md\n"
        "+++ b/n.md\n"
        "@@ -3,0 +4,2 @@\n"
        "+first\n"
        "+second\n"
        "diff --git a/gone.md b/gone.md\n"
        "--- a/gone.md\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-removed\n"
    )
    assert lg.added_lines(diff) == [("n.md", 4, "first"), ("n.md", 5, "second")]


def test_scan_files_skips_binary(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\x00\x00jane@some-company.test")
    assert lg.scan_files([p], [], []) == []


# --- Fix round 1: fail-open findings from review -------------------------------


def test_quoted_non_ascii_path_is_unquoted_and_scanned():
    # core.quotepath default: git writes non-ASCII names as a quoted C-style string
    # with octal byte escapes ("t\303\244st.md" == "täst.md" UTF-8-encoded).
    diff = (
        'diff --git "a/t\\303\\244st.md" "b/t\\303\\244st.md"\n'
        '--- "a/t\\303\\244st.md"\n'
        '+++ "b/t\\303\\244st.md"\n'
        "@@ -0,0 +1 @@\n"
        "+hello\n"
    )
    assert lg.added_lines(diff) == [("täst.md", 1, "hello")]


def test_unrecognized_diff_target_fails_closed():
    diff = "diff --git a/x.md b/x.md\n--- a/x.md\n+++ garbage\n@@ -0,0 +1 @@\n+hello\n"
    with pytest.raises(lg.LeakGuardError):
        lg.added_lines(diff)


def test_added_content_line_starting_with_plusplusplus_is_not_read_as_a_header():
    # An added line whose TEXT is "++ harmless" becomes, under a '+' diff prefix,
    # the raw diff line "+++ harmless" -- indistinguishable from a file header by
    # prefix alone. Only the hunk's declared line count may end the hunk.
    diff = (
        "diff --git a/x.md b/x.md\n"
        "--- a/x.md\n"
        "+++ b/x.md\n"
        "@@ -1,0 +2,2 @@\n"
        "+++ harmless\n"
        "+jane.doe@some-company.test\n"
    )
    assert lg.added_lines(diff) == [
        ("x.md", 2, "++ harmless"),
        ("x.md", 3, "jane.doe@some-company.test"),
    ]


def test_binary_hit_paths_extracts_new_side_path():
    diff = (
        "diff --git a/note.md b/note.md\n"
        "index 3b18e51..2c95405 100644\n"
        "Binary files a/note.md and b/note.md differ\n"
    )
    assert lg.binary_hit_paths(diff) == ["note.md"]


def test_binary_hit_paths_ignores_pure_deletions():
    diff = (
        "diff --git a/note.md b/note.md\n"
        "index 3b18e51..0000000 100644\n"
        "Binary files a/note.md and /dev/null differ\n"
    )
    assert lg.binary_hit_paths(diff) == []


def test_binary_hit_paths_extracts_path_for_git_binary_patch_block():
    diff = (
        "diff --git a/img.png b/img.png\n"
        "index 3b18e51..2c95405 100644\n"
        "GIT binary patch\n"
        "literal 12\n"
        "Qc$@)?000\n"
    )
    assert lg.binary_hit_paths(diff) == ["img.png"]


def test_path_allowed_checks_path_only_not_content():
    allow = lg.parse_allow("assets/logo.png:. # design asset, reviewed by hand\n")
    assert lg.path_allowed("assets/logo.png", allow) is True
    assert lg.path_allowed("other/logo.png", allow) is False


def test_private_list_entries_are_stripped_of_whitespace():
    raw = "  zwergenhausen  \r\nfoo\r\n\n   \n"
    assert lg._parse_private_list(raw) == ["zwergenhausen", "foo"]


def test_allowlist_entry_with_empty_regex_is_rejected():
    with pytest.raises(ValueError):
        lg.parse_allow("x.md: # r\n")
