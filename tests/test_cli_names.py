"""Both CLI names resolve to one entry point, and the names that must not move stay put
(plan Task 12, Global Constraint 6)."""

import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import mailbox_cleanup
from mailbox_cleanup.auth import SERVICE_NAME

PYPROJECT = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
ENTRY = "mailbox_cleanup.cli:cli"


def test_both_cli_names_point_to_the_same_entry():
    scripts = PYPROJECT["project"]["scripts"]
    assert PYPROJECT["project"]["name"] == "mailbox-autopilot"
    assert scripts["mailbox-autopilot"] == scripts["mailbox-cleanup"] == ENTRY


def test_installed_distribution_ships_both_names():
    # pyproject.toml is the source; this reads what the installed environment actually
    # carries, which is what `uv run --frozen` in the plugin launcher resolves against.
    installed = {
        ep.name: ep.value for ep in entry_points(group="console_scripts") if ep.value == ENTRY
    }
    assert installed == {"mailbox-autopilot": ENTRY, "mailbox-cleanup": ENTRY}


def test_package_version_matches_pyproject():
    assert mailbox_cleanup.__version__ == PYPROJECT["project"]["version"]


def test_keychain_service_name_unchanged():
    assert SERVICE_NAME == "mailbox-cleanup"
