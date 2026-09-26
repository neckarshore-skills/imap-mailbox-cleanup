"""`manage` subcommands (spec §3 layer 3). Read and draft only."""

from __future__ import annotations

import datetime
import json
import os
import sys
from collections.abc import Iterable

import click
from click.core import ParameterSource

from .. import SCHEMA_VERSION
from ..audit import log_manage_action
from ..auth import AuthMissingError
from ..cli_helpers import AccountFlagsError, resolve_account_and_credentials
from ..config import Account
from ..imap_client import imap_connect
from .args import unsafe_arg_keys
from .draft import NoDraftsFolderError, build_reply, save_draft
from .envelope import wrap
from .ids import safe_message_id
from .read import _UID_RE, Message, read_message
from .search import search
from .thread import thread


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
        # Never str(e): server text can echo search values or mail content.
        _fail_audited(
            **fail,
            code="operation_error",
            message=f"IMAP operation failed ({type(e).__name__})",
            exit_code=2,
        )
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


# `message_id` sits outside the envelope alongside `uid`/`folder` because Task 7 threads
# replies off it, but unlike those it is mail-derived (R9/M3): it comes straight off the
# Message-ID header. `_safe_message_id` is `ids.safe_message_id` (Task 7 dispatch ruling
# R1: one shared definition, reused here and by draft.py, not copied) — validated against
# the SAME strict allowlist used before a Message-ID reaches IMAP as a search value, not
# the looser extraction shape `read._MSGID_RE`, plus a length cap. A value that fails
# either check becomes an empty string instead of leaking whatever a hostile mail put
# there.
_safe_message_id = safe_message_id


def _message_json(m: Message) -> dict:
    head = f"From: {m.sender}\nTo: {', '.join(m.to)}\nSubject: {m.subject}\nDate: {m.date}"
    return {
        "uid": m.uid,
        "folder": m.folder,
        "message_id": _safe_message_id(m.message_id),
        "mail": wrap(f"{head}\n\n{m.text}"),
    }


@manage.command("read")
@click.option("--account", "account_flag", default=None)
@click.option("--folder", default="INBOX", show_default=True)
@click.option("--uid", required=True)
@click.option("--json", "json_mode", is_flag=True, help="Accepted for symmetry; output is JSON.")
def read_cmd(account_flag, folder, uid, json_mode):
    account, creds = _resolve(account_flag)
    fail = dict(subcommand="manage.read", account=account, folder=folder, arg_keys=["uid"])
    _reject_control_chars(fail, folder=folder)
    if not _UID_RE.fullmatch(uid):
        _fail_audited(
            **fail, code="bad_args", message="--uid must contain only ASCII digits", exit_code=4
        )
    try:
        with imap_connect(creds, port=account.port) as mb:
            m = read_message(mb, uid=uid, folder=folder)
    except Exception as e:  # never str(e): server text can echo mail content
        _fail_audited(
            **fail,
            code="operation_error",
            message=f"IMAP operation failed ({type(e).__name__})",
            exit_code=2,
        )
    if m is None:
        _fail_audited(
            **fail, code="not_found", message=f"no message with UID {uid} in {folder}", exit_code=1
        )
    log_manage_action(
        subcommand="manage.read",
        account=account.alias,
        folder=folder,
        uids=[uid],
        result="success",
        arg_keys=["uid"],
    )
    _out({"ok": True, "subcommand": "manage.read", "message": _message_json(m)})


@manage.command("thread")
@click.option("--account", "account_flag", default=None)
@click.option("--folder", default="INBOX", show_default=True)
@click.option("--uid", required=True)
@click.option("--json", "json_mode", is_flag=True, help="Accepted for symmetry; output is JSON.")
def thread_cmd(account_flag, folder, uid, json_mode):
    account, creds = _resolve(account_flag)
    fail = dict(subcommand="manage.thread", account=account, folder=folder, arg_keys=["uid"])
    _reject_control_chars(fail, folder=folder)
    if not _UID_RE.fullmatch(uid):
        _fail_audited(
            **fail, code="bad_args", message="--uid must contain only ASCII digits", exit_code=4
        )
    try:
        with imap_connect(creds, port=account.port) as mb:
            msgs = thread(mb, uid=uid, folder=folder)
    except Exception as e:  # never str(e): server text can echo mail content
        _fail_audited(
            **fail,
            code="operation_error",
            message=f"IMAP operation failed ({type(e).__name__})",
            exit_code=2,
        )
    if not msgs:
        # thread() returns [] ONLY when the start UID does not exist (read_message finds
        # nothing): whenever a start message IS found, it is always included in the
        # result, so an empty list is an unambiguous not_found signal here (M5).
        _fail_audited(
            **fail, code="not_found", message=f"no message with UID {uid} in {folder}", exit_code=1
        )
    log_manage_action(
        subcommand="manage.thread",
        account=account.alias,
        folder=folder,
        uids=[m.uid for m in msgs],
        result="success",
        arg_keys=["uid"],
    )
    _out(
        {
            "ok": True,
            "subcommand": "manage.thread",
            "messages": [_message_json(m) for m in msgs],
        }
    )


@manage.command("draft")
@click.option("--account", "account_flag", default=None)
@click.option("--folder", default="INBOX", show_default=True)
@click.option("--uid", required=True, help="UID of the mail being answered")
@click.option("--body-file", required=True)  # plain str (Important 1 — see below)
@click.option("--json", "json_mode", is_flag=True, help="Accepted for symmetry; output is JSON.")
def draft_cmd(account_flag, folder, uid, body_file, json_mode):
    account, creds = _resolve(account_flag)
    arg_keys = ["uid", "body_file"]
    # R4: "folder" joins arg_keys only when the user actually passed --folder, not for
    # its default — unlike search/read/thread, which never track it at all.
    ctx = click.get_current_context()
    if ctx.get_parameter_source("folder") == ParameterSource.COMMANDLINE:
        arg_keys.append("folder")
    fail = dict(subcommand="manage.draft", account=account, folder=folder, arg_keys=arg_keys)
    _reject_control_chars(fail, folder=folder)
    if not _UID_RE.fullmatch(uid):
        _fail_audited(
            **fail, code="bad_args", message="--uid must contain only ASCII digits", exit_code=4
        )
    # Important 1: --body-file is a plain str, not click.Path(...). Measured empirically:
    # click.Path(exists=True, dir_okay=False) rejects a missing/unreadable file itself
    # (exit 2, click usage text, no JSON, no audit) before this function ever runs — the
    # violation this fixes. The seemingly obvious repair, click.Path(dir_okay=False,
    # exists=False, readable=False), does NOT fully fix it either: its dir_okay=False
    # check runs unconditionally whenever os.stat() succeeds (i.e. whenever the path
    # exists at all, regardless of `exists=`), so a directory path is still rejected by
    # Click itself, not by us. A plain str defers ALL of missing/unreadable/directory to
    # our own open() below, uniformly audited bad_args.
    #
    # Fix round 2 fold-in: a FIFO (named pipe) given as --body-file passes every check
    # above but makes a bare open() block forever waiting for a writer, hanging the whole
    # command. os.path.isfile() (stat-based, not an open) rejects it before we ever touch
    # the file — same audited bad_args, exit 4, as missing/directory/unreadable.
    if not os.path.isfile(body_file):
        _fail_audited(
            **fail,
            code="bad_args",
            message="--body-file must be a readable regular file",
            exit_code=4,
        )
    try:
        with open(body_file, encoding="utf-8") as f:
            body = f.read()
    except (OSError, UnicodeDecodeError):
        _fail_audited(
            **fail,
            code="bad_args",
            message="--body-file could not be read as UTF-8 text",
            exit_code=4,
        )
    not_found = False
    try:
        with imap_connect(creds, port=account.port) as mb:
            orig = read_message(mb, uid=uid, folder=folder)
            if orig is None:
                not_found = True
            else:
                msg, warnings = build_reply(orig, from_addr=account.email, body=body)
                drafts = save_draft(mb, msg)
    except NoDraftsFolderError:  # Minor 1: never str(e) — a literal message, per R4
        _fail_audited(
            **fail, code="no_drafts_folder", message="no Drafts folder found", exit_code=5
        )
    except Exception as e:  # never str(e): server text can echo mail content
        _fail_audited(
            **fail,
            code="operation_error",
            message=f"IMAP operation failed ({type(e).__name__})",
            exit_code=2,
        )
    if not_found:
        _fail_audited(
            **fail, code="not_found", message=f"no message with UID {uid} in {folder}", exit_code=1
        )
    log_manage_action(
        subcommand="manage.draft",
        account=account.alias,
        folder=folder,
        uids=[uid],
        result="success",
        arg_keys=arg_keys,
    )
    _out(
        {
            "ok": True,
            "subcommand": "manage.draft",
            "drafts_folder": drafts,
            "warnings": warnings,
            "subject": wrap(msg["Subject"]),
            # msg["To"] can be None (Minor 2+3: no usable sender address) — a warning
            # already covers that case, this just avoids wrap() crashing on None.
            "to": wrap(msg["To"] or ""),
        }
    )
