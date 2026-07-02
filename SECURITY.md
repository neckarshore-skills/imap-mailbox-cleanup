# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest `main` | Yes |

This is a solo-maintained open-source tool. Only the current `main` receives
security fixes; there is no back-port of older tags.

## Data Handling

`imap-mailbox-cleanup` connects to an IMAP mailbox to triage and delete messages.
Two points worth distinguishing:

**Credentials stay on your machine.** The tool reads IMAP host, username, and
password from your local environment/config. Credentials are used only to open
the IMAP connection you configured; they are never logged, transmitted to any
third party, or committed. Verify with `grep -rn 'requests\|http\|urllib' src/`
— the only network egress is the IMAP connection you point it at.

**No telemetry.** No analytics, error reporting, or auto-update calls are made.

For a mailbox you would not want a local script to read (privileged corporate
mail, legal, medical), apply your own judgement: the tool acts on whatever
mailbox you give it credentials for.

## Scope

The tool operates only on the IMAP account and folders you configure. It does not
read the local filesystem beyond its own config, and makes no outbound calls other
than to the IMAP server you specify.

## Reporting a Vulnerability

Report security issues **privately** via GitHub's private vulnerability reporting:
the **Security** tab → **Report a vulnerability** on
<https://github.com/neckarshore-skills/imap-mailbox-cleanup/security/advisories>.
This keeps the report confidential until a fix ships.

Include:

1. **What you found** — describe the vulnerability
2. **How to reproduce** — steps to trigger the issue
3. **Impact** — what could go wrong if exploited

**Response time:** Best-effort. This is a solo-maintained open-source project, not
a commercial service with an SLA.
