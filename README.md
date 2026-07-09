# mailbox-cleanup

<p align="center">
  <img src=".github/social-preview.jpg" alt="mailbox-cleanup — Mailbox Triage. Dry-run first." width="100%"/>
</p>

Hybrid CLI + Claude Code Skill for triaging and cleaning up an IONOS IMAP mailbox. Dry-run by default, audit-logged, soft-delete-only. Multi-account capable.

[![CI](https://github.com/neckarshore-ai/imap-mailbox-cleanup/actions/workflows/ci.yml/badge.svg)](https://github.com/neckarshore-ai/imap-mailbox-cleanup/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## What it does

Battle-tested in one production session: 7.982 → 690 messages (-91%) on a real IONOS mailbox.

Two pieces:

1. **CLI** (Python, [`click`](https://click.palletsprojects.com), [`imap-tools`](https://github.com/ikvk/imap_tools)) — atomic subcommands with JSON output. Stateless. Testable.
2. **Claude Code Skill** — conversational orchestrator that wraps the CLI in a discovery → preview → apply loop. Asks before every destructive action.

The CLI is useful on its own. The Skill turns it into a guided triage workflow.

## Why hybrid

- **Pure CLI** would force you to memorize subcommands and read JSON.
- **Pure Skill** would push IMAP logic into Markdown / tool calls — fragile, slow, untestable.
- **Hybrid** keeps the engine testable (`pytest` against a real IMAP server in Docker) and the UX conversational.

## Architecture

```
Claude Code Session
  ↓ /mailbox-cleanup or natural request
Claude Skill (Markdown, orchestrator)
  ↓ subprocess + JSON
CLI: mailbox-cleanup <subcommand> [--account=<alias>] [--apply | --json]
  ↓ imap-tools
IONOS IMAP
```

State files (per user):

| Path | Purpose | Mode |
|------|---------|------|
| `~/.mailbox-cleanup/config.json` | Identity + connection settings per account (source of truth) | 0600 |
| macOS Keychain (service `mailbox-cleanup`) | Passwords only — one entry per email | OS-managed |
| `~/.mailbox-cleanup/audit.log` | Append-only JSONL forensics, includes `account` field per record | 0644 |

## Safety model

| Layer | Mechanism |
|-------|-----------|
| **Default** | Every destructive subcommand is dry-run. `--apply` is required to actually do anything. |
| **Soft-delete** | `delete` moves to `Papierkorb` / `Trash` (resolved via RFC 6154 SPECIAL-USE flag with literal fallbacks). No `EXPUNGE` in v1. |
| **Skill flow** | Always shows a preview from a dry-run before re-running with `--apply`. Asks for explicit confirmation. |
| **Audit log** | Every `--apply` action appends one JSON-line to `~/.mailbox-cleanup/audit.log` with timestamp, account, args, folder, affected UIDs, and result. |
| **Credentials** | macOS Keychain via [`keyring`](https://github.com/jaraco/keyring). No `.env`, no plaintext. |
| **Final step** | True deletion is manual — empty `Papierkorb` in IONOS Webmail. |

## Install

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
git clone https://github.com/neckarshore-ai/imap-mailbox-cleanup.git
cd imap-mailbox-cleanup
uv tool install --editable .
```

This puts `mailbox-cleanup` on your `PATH` (typically `~/.local/bin/mailbox-cleanup`). The CLI binary keeps the short name `mailbox-cleanup`; only the GitHub repo is `imap-mailbox-cleanup`.

## Setup

`auth set` requires a real terminal (Terminal.app / iTerm — `getpass` requires a TTY).

### First-time setup (one account)

```bash
mailbox-cleanup auth set --alias=work --email=you@example.com
mailbox-cleanup auth test --account=work
```

`auth set` writes the account record to `~/.mailbox-cleanup/config.json` and stores the password in the macOS Keychain (service `mailbox-cleanup`, account = email).

### Adding a second account

```bash
mailbox-cleanup auth set --alias=private --email=other@example.com
mailbox-cleanup config list
mailbox-cleanup config set-default work
```

### Migrating from v0.1

> Existing v0.1 users: run any subcommand once with `--email=<your-email>` and the CLI auto-creates `~/.mailbox-cleanup/config.json` with a derived alias. After that, `--account=<alias>` is the preferred flag.

### Optional: install the Claude Code Skill

```bash
mkdir -p ~/.claude/skills/mailbox-cleanup
cp skill/SKILL.md ~/.claude/skills/mailbox-cleanup/
```

Claude Code auto-discovers skills under `~/.claude/skills/`. Invoke via `/mailbox-cleanup` in any session.

## Multi-account

Once two or more accounts are configured, every subcommand picks an account via this resolution order:

1. Explicit `--account=<alias>` or `--account=<email>`
2. Environment variable `MAILBOX_CLEANUP_ACCOUNT`
3. Configured default (`config set-default <alias>`)
4. The single account, if only one is configured
5. Otherwise: error `no_account_selected` (exit 4)

```bash
# Operate on the default account
mailbox-cleanup scan

# Operate on a specific account
mailbox-cleanup scan --account=private
mailbox-cleanup scan --account=other@example.com   # email also works

# Override via env var (useful for scripts/Marvin cron)
MAILBOX_CLEANUP_ACCOUNT=private mailbox-cleanup scan

# Manage accounts
mailbox-cleanup config list                # tabular
mailbox-cleanup config list --json         # machine-readable
mailbox-cleanup config show work
mailbox-cleanup config rename work office
mailbox-cleanup config set-default office
mailbox-cleanup config remove private      # also deletes Keychain password
```

## Usage

### From Claude Code

```
/mailbox-cleanup
```

The Skill runs `auth test`, then `scan`, presents a German-language category summary, and prompts for action per category. Always shows a dry-run preview before any `--apply`.

### Standalone CLI

```bash
# Discovery
mailbox-cleanup scan --account=work --json
mailbox-cleanup senders --account=work --top 50

# Dry-run delete (preview only)
mailbox-cleanup delete --account=work --sender "newsletter@x.com"

# Apply
mailbox-cleanup delete --account=work --sender "newsletter@x.com" --apply

# Combine filters (AND)
mailbox-cleanup delete \
  --account=work \
  --sender "noreply@github.com" \
  --older-than 6m \
  --apply

# Move (e.g. invoices to a tax folder)
mailbox-cleanup move \
  --account=work \
  --sender "noreply@ionos.de" \
  --to "STEUER Rechnungen Finanzamt" \
  --apply

# Bulk archive
mailbox-cleanup archive --account=work --older-than 12m --apply

# Unsubscribe (RFC 2369 / RFC 8058 one-click)
mailbox-cleanup unsubscribe --account=work --sender "newsletter@x.com" --apply

# Dedupe by Message-ID (keeps oldest)
mailbox-cleanup dedupe --account=work --apply

# Find bounce / auto-reply
mailbox-cleanup bounces --account=work --apply

# List large attachments (strip = v2)
mailbox-cleanup attachments --account=work --size-gt 10mb
```

If only one account is configured, `--account` can be omitted.

## Subcommands

| Subcommand | Purpose | Required args | Dry-run by default |
|------------|---------|---------------|---------------------|
| `auth set` | Create/update account in config.json + write password to Keychain | `--alias=`, `--email=` (interactive password) | n/a |
| `auth test` | Connect, list folders, disconnect | — (uses default/`--account`) | n/a |
| `auth delete` | Remove credentials from Keychain | `--account=` | n/a |
| `config list` | List configured accounts | — | n/a (read-only) |
| `config show` | Show one account's connection settings | `<alias>` | n/a (read-only) |
| `config rename` | Rename an alias | `<old>`, `<new>` | n/a |
| `config set-default` | Mark an account as default | `<alias>` | n/a |
| `config remove` | Delete account from config + remove Keychain password | `<alias>` | n/a |
| `scan` | Discovery — classify INBOX, return JSON report | `--folder=INBOX` (default) | n/a (read-only) |
| `senders` | List top-N senders by count | `--top=50` | n/a (read-only) |
| `delete` | Soft-delete (move to Trash) by filter | one of `--sender=` / `--subject-contains=` / `--older-than=` | yes |
| `move` | Move by filter to target folder | `--from-filter=...`, `--to=Folder` | yes |
| `archive` | Bulk-move messages older than N → `Archive/YYYY` | `--older-than=12m` | yes |
| `unsubscribe` | Parse `List-Unsubscribe` header, execute (HTTPS POST or `mailto:` SMTP) | `--sender=` | yes |
| `dedupe` | Drop Message-ID duplicates, keep oldest | `--folder=` | yes |
| `attachments` | List large messages (v1) — strip is v2 | `--size-gt=10mb` | n/a (read-only v1) |
| `bounces` | Find bounce / auto-reply messages | `--folder=INBOX` | yes |

**Common flags:** `--account=<alias|email>` (account selector), `--json` (structured output), `--apply` (execute, default off), `--folder=` (target IMAP folder), `--limit=N` (cap operation size).

**Time syntax for `--older-than`:** `Nd` / `Nw` / `Nm` / `Ny` (days / weeks / months / years).

**Filter combinability:** `delete --account=work --sender=X --older-than=3m --apply` (AND across filters).

## Discovery report (`scan --json`)

The contract between CLI and Skill — `scan` always emits this shape:

```json
{
  "schema_version": 1,
  "scanned_at": "2026-05-04T...",
  "folder": "INBOX",
  "total_messages": 7982,
  "size_total_mb": 65.5,
  "categories": {
    "newsletters": {"count": 5649, "top_senders": []},
    "automated_notifications": {"count": 652, "top_senders": []},
    "bounces_and_autoreplies": {"count": 1, "samples": []},
    "large_attachments": {"count": 0, "size_mb": 0, "top_offenders": []},
    "duplicates": {"count": 18, "groups": []},
    "old_messages": {"older_than_12m": 196},
    "by_year": {"2024": 73, "2025": 887, "2026": 7022}
  },
  "recommendations": ["...", "..."]
}
```

`schema_version` is checked by the Skill — version mismatch means update one side before continuing.

### Classification rules

| Category | Rule |
|----------|------|
| **newsletter** | `List-Unsubscribe` header present **OR** sender local-part matches `newsletter`, `noreply`, `no-reply`, `news`, `marketing` |
| **automated** | sender local-part matches `notifications`, `bot`, `service`, `alerts`, `system`, `daemon`, `automation` |
| **bounce** | sender is `MAILER-DAEMON` / `postmaster` **OR** subject starts with `Undelivered`, `Returned`, `Mail Delivery`, `Auto-Reply`, `Out of Office`, `Abwesenheits` |
| **duplicate** | identical `Message-ID` header (true dupe; fuzzy dedupe deferred to v2) |
| **large_attachment** | message size > 10 MB |

A message can fall into multiple categories.

## Audit log

Path: `~/.mailbox-cleanup/audit.log` (override with `MAILBOX_CLEANUP_AUDIT_LOG`).

Format: one JSON object per line. The `account` field identifies which alias performed the action (optional for backward compatibility with v0.1 entries that pre-date multi-account). Example:

```json
{"timestamp":"2026-05-04T09:27:45.504Z","account":"work","subcommand":"delete","args":{"sender":"service@paypal.de","older_than":"2m"},"folder":"INBOX","affected_uids":["655773","672257"],"result":"success"}
```

Inspect with `jq`:

```bash
# Group by account + subcommand
jq -s 'group_by(.account + "/" + .subcommand) | map({op: (.[0].account + "/" + .[0].subcommand), count: (map(.affected_uids|length)|add)})' ~/.mailbox-cleanup/audit.log
```

## Exit codes and error codes

The CLI exits with a numeric code; structured errors include a stable `error` string in the JSON payload (when `--json` is used).

| Code | Meaning | Exit |
|------|---------|------|
| `auth_missing` | No password in Keychain for the resolved account | 3 |
| `connection_error` | IMAP connection / TLS / network failure | 2 |
| `no_account_selected` | Multiple accounts; no default; no `--account` or env var | 4 |
| `unknown_account` | `--account=foo` matched neither alias nor email | 4 |
| `duplicate_alias` | `auth set --alias=X` but X exists | 4 |
| `duplicate_email` | `auth set --email=X` but X exists | 4 |
| `bootstrap_failed` | Auto-migration from v0.1 failed | 4 |
| `no_config` | No config file and no v0.1 fallback | 5 |
| `config_corrupt` | Existing JSON parse failure | 5 |
| `schema_version_unsupported` | Config from a future version | 5 |

Generic exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Connection error |
| 3 | Auth missing |
| 4 | Bad arguments / account resolution |
| 5 | Partial failure / config error |

## Repo layout

```
mailbox-cleanup/
├── README.md                              ← you are here
├── pyproject.toml                         ← Python 3.11+, click, imap-tools, keyring, requests, pytest, ruff
├── src/mailbox_cleanup/
│   ├── __init__.py                        ← __version__, SCHEMA_VERSION
│   ├── cli.py                             ← click entry point
│   ├── auth.py                            ← Keychain
│   ├── config.py                          ← config.json schema + I/O
│   ├── imap_client.py                     ← imap-tools wrapper, retry, SSL toggle
│   ├── classify.py                        ← pure-function classification rules
│   ├── scan.py                            ← discovery → JSON report
│   ├── folders.py                         ← SPECIAL-USE folder resolver
│   ├── audit.py                           ← JSONL audit log writer (account-aware)
│   └── operations/
│       ├── filters.py
│       ├── delete.py
│       ├── move.py
│       ├── archive.py
│       ├── unsubscribe.py
│       ├── dedupe.py
│       ├── attachments.py
│       └── bounces.py
├── tests/                                 ← unit + integration via Greenmail Docker
├── docs/
│   ├── 2026-05-04-design.md                       ← v0.1 spec
│   ├── 2026-05-04-implementation-plan.md           ← v0.1 TDD plan
│   ├── 2026-05-04-multi-account-design.md          ← v0.2 spec
│   ├── 2026-05-04-multi-account-implementation-plan.md  ← v0.2 TDD plan
│   └── smoke-test.md                               ← read-only IONOS smoke test
├── skill/SKILL.md                         ← versioned Claude Code skill copy
└── .github/workflows/ci.yml               ← GitHub Actions
```

## Tests

```bash
uv sync --extra dev
uv run pytest -v               # Greenmail Docker auto-starts via conftest
uv run ruff check .
uv run ruff format --check .
```

CI runs the same on every push. Greenmail starts on port 3143 (plain IMAP) + 3025 (SMTP).

## Estate test-scope stats

This repo is a **producer** for the neckarshore.ai estate test-count. On every `push:main`, CI counts the two gated pytest suites (unit + the live-Greenmail integration suite) from pytest's own `--collect-only` reporter — never grep — and publishes a contract-valid `stats.json` to the dedicated [`stats-data`](../../tree/stats-data/stats.json) branch: a single-file data branch, **not** `main`. `main` is a protected branch (a bot cannot push to it without weakening its protection), so the machine artifact lives on its own unprotected branch instead. The neckarshore.ai aggregator fetches it via `contents/stats.json?ref=stats-data`. Contract: [`stats-json-contract.md`](https://github.com/neckarshore-ai/neckarshore-planning/blob/main/docs/reference/stats-json-contract.md).

## Limitations (v0.2)

1. IONOS only — no provider abstraction (Gmail API, Office365 = v0.3+)
2. Strict dedupe — only by exact `Message-ID`; fuzzy hash = v2
3. Attachment listing only — in-place strip = v2
4. No hard-delete — final step is manual `Papierkorb leeren` in IONOS Webmail
5. Rule-based classification only — no ML / LLM in CLI (Skill can layer it on)
6. `auth set` requires a real TTY — no `--password-stdin` yet (v2)

## v0.3+ backlog

- Provider abstraction (Gmail API / OAuth)
- Fuzzy duplicate detection
- Attachment strip (append stripped + delete original)
- Marvin cron integration for autonomous background cleanup
- Web UI / TUI
- `--password-stdin` for non-TTY setup
- `purge-trash` hard-delete subcommand

## References

- IMAP RFC 3501, RFC 6154 (SPECIAL-USE), RFC 2369 (List-Unsubscribe), RFC 8058 (One-Click POST)
- [imap-tools](https://github.com/ikvk/imap_tools)
- [click](https://click.palletsprojects.com)
- [keyring](https://github.com/jaraco/keyring)
- [Greenmail](https://greenmail-mail-test.github.io/greenmail/) — test IMAP server

## License

[MIT](LICENSE) — feel free to fork, modify, redistribute. No warranty; built primarily for the author's own IONOS mailbox.

## Author

German Rauhut · `german@rauhut.com`
