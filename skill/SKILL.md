---
name: mailbox-cleanup
description: Discover and clean up an IONOS IMAP mailbox via the `mailbox-cleanup` CLI. Use when the user wants to triage, scan, delete, archive, or unsubscribe from messages in their mail account. Always shows dry-run preview before any destructive operation. Multi-account capable.
---

# mailbox-cleanup

Conversational orchestrator over the `mailbox-cleanup` CLI. Wraps discovery → preview → apply loops with safety checks. Multi-account capable: every CLI call resolves to one account via `--account=<alias|email>` or the configured default.

## Required CLI version

Schema version 1. The CLI emits `"schema_version": 1` in every JSON response — if it doesn't match, abort and tell the user to update the CLI.

## Setup state — detect first, every session

Before anything else, find out which accounts are configured:

```bash
mailbox-cleanup config list --json
```

Read the `accounts` array from the response. Three states:

1. **Empty / file missing** — no accounts yet. Run the setup-time decision tree below.
2. **One account** — use it implicitly. No `--account` flag needed.
3. **Multiple accounts** — pick one (see "Picking an account" below) and pass `--account=<alias>` to every subsequent CLI call.

### Setup-time decision tree

```
if config.json missing AND user has v0.1 keychain entry:
  run any subcommand with --email=<their email> → triggers auto-bootstrap
  OR run `config init --import-email=<email>` explicitly
if config.json missing AND no v0.1 entry:
  ask user for alias + email, then guide them to run in a real terminal:
    mailbox-cleanup auth set --alias=<alias> --email=<email>
  (auth set needs a TTY for getpass — Claude Code cannot run it interactively)
if config.json exists:
  use accounts as listed; ask user which one if ambiguous
```

## Picking an account

Once `config list --json` returns a non-empty `accounts` array:

1. **One account** — use it. Don't ask. Don't pass `--account` (the CLI resolves the single account automatically).
2. **Multiple accounts, default set** — assume the default unless the user says otherwise. You may briefly note it: "Ich nutze den Default-Account `<alias>`. Anderer Account?"
3. **Multiple accounts, no default** — ask: "Welcher Account: `work`, `private`, ...?" Then pass `--account=<chosen>` to every subsequent command in the session.

Store the chosen alias in your working memory for the session. Substitute `<ACCOUNT>` in the commands below with the chosen alias (or omit `--account=<ACCOUNT>` entirely when there is exactly one configured account).

## Auth check (run after picking the account)

```bash
mailbox-cleanup auth test --account=<ACCOUNT> --json
```

- Exit 0 with `"ok": true`: continue.
- Exit 3 (`auth_missing`): tell the user to run `mailbox-cleanup auth set --alias=<ACCOUNT> --email=<their email>` in a real terminal (Terminal.app / iTerm — `getpass` requires a TTY). Do not proceed.
- Exit 4 (`no_account_selected` / `unknown_account`): re-check the account list; you may have a stale alias.
- Exit 2 (connection): show the message; do not retry blindly.

## Standard flow

1. Run `mailbox-cleanup scan --account=<ACCOUNT> --json`.
2. Validate `schema_version == 1`. Otherwise abort.
3. Render a German Markdown summary:

   ```
   Mailbox: <total_messages> Nachrichten, <size_total_mb> MB

   Kategorien:
     1. Newsletter: <count> (Top-Sender: ...)
     2. Automatisierte Notifications: <count>
     3. Bounces / Auto-Replies: <count>
     4. Große Anhänge (>10 MB): <count> Nachrichten, <size_mb> MB
     5. Alte Nachrichten: <older_than_12m> älter als 12 Monate
     6. Duplikate: <count>

   Empfehlungen:
     [1] <recommendations[0]>
     [2] <recommendations[1]>
     ...
   ```

4. Ask: **"Welche Kategorie / Empfehlung willst du angehen?"**
5. When the user picks an operation:
   - Always run the CLI **without `--apply`** first (dry-run)
   - Render the preview: count + first 5 sample messages
   - Ask: **"Apply?"**
   - Only on explicit confirmation, run again with `--apply`
6. After `--apply`, show the result count and tell the user the audit log is at `~/.mailbox-cleanup/audit.log`.
7. Loop back to step 4 for the next category.

## Subcommand cheat sheet

Replace `<ACCOUNT>` with the chosen alias (or omit the `--account` flag when only one account is configured).

| User intent | Command |
|-------------|---------|
| "Welche Accounts?" | `mailbox-cleanup config list --json` |
| "Scan" / "Was ist drin?" | `mailbox-cleanup scan --account=<ACCOUNT> --json` |
| "Wer schickt am meisten?" | `mailbox-cleanup senders --account=<ACCOUNT> --top 20 --json` |
| "Lösch alles von X" | `mailbox-cleanup delete --account=<ACCOUNT> --sender X --json` (then `--apply`) |
| "Alles älter als 1 Jahr archivieren" | `mailbox-cleanup archive --account=<ACCOUNT> --older-than 12m --json` |
| "Vom Newsletter X abmelden" | `mailbox-cleanup unsubscribe --account=<ACCOUNT> --sender X --json` (HTTPS one-click only; `mailto:`-only senders come back under `manual_unsubscribe` for the user to unsubscribe by hand, their mail is kept) |
| "Bounces wegräumen" | `mailbox-cleanup bounces --account=<ACCOUNT> --json` |
| "Duplikate finden" | `mailbox-cleanup dedupe --account=<ACCOUNT> --json` |
| "Große Anhänge zeigen" | `mailbox-cleanup attachments --account=<ACCOUNT> --size-gt 10mb --json` |

## Exit codes

| Code | Meaning | What to do |
|------|---------|------------|
| 0 | Success | Continue |
| 2 | Connection error | Show stderr, do not retry blindly |
| 3 | Auth missing | Tell user to run `auth set` in a real terminal |
| 4 | Bad arguments / account resolution (`no_account_selected`, `unknown_account`, `duplicate_alias`, `duplicate_email`, `bootstrap_failed`) | Show stderr; re-check `config list --json` if needed |
| 5 | Partial failure / config error (`no_config`, `config_corrupt`, `schema_version_unsupported`) | Show audit log path, summarize successes/failures |

## Audit log

Path: `~/.mailbox-cleanup/audit.log`. Append-only JSONL, one record per `--apply` action. Each record now includes an `account` field identifying which alias performed the action. Treat `account` as **optional** for backward compatibility — v0.1 entries pre-date the multi-account schema and may not have it.

## When the CLI isn't enough — ad-hoc Python

Some operations are beyond the CLI subcommands: creating folders, cross-folder bulk scans, date-range deletions across all folders, or subject-keyword classification. Use `uv run python3 -` from the project directory (system Python lacks `keyring`):

```python
from imap_tools import MailBox, A
import keyring, json
from pathlib import Path
from datetime import date

cfg = json.loads(Path("~/.mailbox-cleanup/config.json".replace("~", str(Path.home()))).read_text())
acct = next(a for a in cfg["accounts"] if a["alias"] == "<ALIAS>")
pw = keyring.get_password("mailbox-cleanup", acct["email"])

with MailBox(acct["server"]).login(acct["email"], pw) as mb:
    # create a folder
    mb.folder.create("Archiv vor 2025/Neuanmeldungen")

    # switch folder and search
    mb.folder.set("INBOX")
    uids = mb.uids(A(date_lt=date(2023, 1, 1)))

    # move in batches of 500 (required for >500 UIDs — see Batching below)
    for i in range(0, len(uids), 500):
        mb.move(uids[i:i+500], "Papierkorb")
```

**Always do a count-only run first** (no `mb.move`), show the number to the user, ask for confirmation, then apply. This is the ad-hoc equivalent of the CLI dry-run rule.

### IMAP Search Umlaut trap

`A(subject="Verlängerung")` → `UnicodeEncodeError: 'ascii' codec can't encode character`. IMAP SEARCH is ASCII-only. Workarounds:

- Use the ASCII transliteration: `"Verlaengerung"`
- Use the English equivalent from bilingual subjects: `"Renewal"`, `"Extension"`, `"Signup"`
- Combine multiple keyword searches and union the UID sets

### Batching for large moves

`mb.move(uids, folder)` times out or errors on large UID lists. Always batch at 500:

```python
for i in range(0, len(uids), 500):
    mb.move(uids[i:i+500], target_folder)
```

### Cross-folder scan pattern

```python
SKIP = {"Papierkorb", "Entwürfe", "Spam"}
for folder in [f.name for f in mb.folder.list() if f.name not in SKIP]:
    mb.folder.set(folder)
    uids = mb.uids(A(from_="facebookmail.com"))
    if uids:
        mb.move(uids, "Papierkorb")
```

## Hard rules

1. **Never call any subcommand with `--apply` without showing a dry-run preview first and getting explicit "ja" / "yes" / "apply" from the user.**
2. **Never invent UID lists or counts.** Always use the JSON returned by the CLI.
3. **Never edit the audit log.** It is append-only forensics.
4. **All destructive operations move to Trash.** v1 has no hard-delete; if the user asks "wirklich löschen", explain that v1 only soft-deletes and Trash is purged by IONOS retention.
5. **Never mix accounts in a single dry-run/apply pair.** If the user switches account mid-session, re-run the preview against the new account before any `--apply`.
