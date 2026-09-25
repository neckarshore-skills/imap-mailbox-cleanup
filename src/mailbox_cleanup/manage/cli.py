"""`manage` subcommands (spec §3 layer 3). Read and draft only."""

from __future__ import annotations

import datetime
import json
import sys
from collections.abc import Iterable

import click

from .. import SCHEMA_VERSION
from ..audit import log_manage_action
from ..auth import AuthMissingError
from ..cli_helpers import AccountFlagsError, resolve_account_and_credentials
from ..config import Account
from ..imap_client import imap_connect
from .args import unsafe_arg_keys
from .envelope import wrap
from .search import search


def _out(payload: dict) -> None:
    payload.setdefault("schema_version", SCHEMA_VERSION)
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(code: str, message: str, exit_code: int) -> None:
    _out({"ok": False, "error_code": code, "message": message})
    sys.exit(exit_code)


def _fail_audited(
    *,
    subcommand: str,
    account: Account,
    folder: str,
    arg_keys: Iterable[str],
    code: str,
    message: str,
    exit_code: int,
) -> None:
    """Fail after the account is resolved: the audit record carries the error CODE only,
    never the message, which can echo search values or mail content."""
    log_manage_action(
        subcommand=subcommand,
        account=account.alias,
        folder=folder,
        uids=[],
        result="error",
        arg_keys=arg_keys,
        error=code,
    )
    _fail(code, message, exit_code)


def _resolve(account_flag):
    """Resolution failures are not audited: no account is known and no mailbox is touched."""
    try:
        return resolve_account_and_credentials(account_flag=account_flag, email_flag=None)
    except AccountFlagsError as e:
        _fail(e.error_code, str(e), 4)
    except AuthMissingError as e:
        _fail("auth_missing", str(e), 3)


def _reject_control_chars(fail: dict, **values: str | None) -> None:
    """Audited `bad_args` before any IMAP call when a value carries a control character.
    The message names the fields, never the values."""
    bad = unsafe_arg_keys(**values)
    if bad:
        fields = ", ".join(f"--{k}" for k in bad)
        _fail_audited(
            **{**fail, "folder": "" if "folder" in bad else fail["folder"]},
            code="bad_args",
            message=f"control characters are not allowed in {fields}",
            exit_code=4,
        )


def _arg_keys(**given) -> list[str]:
    return [k for k, v in given.items() if v]


@click.group("manage")
def manage():
    """Search, read, follow threads and draft replies. Never sends, deletes or moves."""


@manage.command("search")
@click.option("--account", "account_flag", default=None)
@click.option("--folder", default="INBOX", show_default=True)
@click.option("--sender", default=None)
@click.option("--subject", default=None)
@click.option("--text", default=None)
@click.option("--since", default=None, help="YYYY-MM-DD, compared with the Date header")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(min=1))
@click.option("--json", "json_mode", is_flag=True, help="Accepted for symmetry; output is JSON.")
def search_cmd(account_flag, folder, sender, subject, text, since, limit, json_mode):
    account, creds = _resolve(account_flag)
    keys = _arg_keys(sender=sender, subject=subject, text=text, since=since)
    fail = dict(subcommand="manage.search", account=account, folder=folder, arg_keys=keys)
    _reject_control_chars(fail, folder=folder, sender=sender, subject=subject, text=text)
    try:
        since_d = datetime.date.fromisoformat(since) if since else None
    except ValueError:
        _fail_audited(**fail, code="bad_args", message="--since must be YYYY-MM-DD", exit_code=4)
    try:
        with imap_connect(creds, port=account.port) as mb:
            hits = search(
                mb,
                folder=folder,
                sender=sender,
                subject=subject,
                text=text,
                since=since_d,
                limit=limit,
            )
    except Exception as e:  # surfaced as a structured error; the audit keeps the code only
        _fail_audited(**fail, code="operation_error", message=str(e), exit_code=2)
    log_manage_action(
        subcommand="manage.search",
        account=account.alias,
        folder=folder,
        uids=[h.uid for h in hits],
        result="success",
        arg_keys=keys,
    )
    _out(
        {
            "ok": True,
            "subcommand": "manage.search",
            "folder": folder,
            "candidates": [
                {
                    "uid": h.uid,
                    "date": h.date,
                    "mail": wrap(f"From: {h.sender}\nSubject: {h.subject}"),
                }
                for h in hits
            ],
        }
    )
