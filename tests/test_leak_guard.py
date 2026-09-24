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
