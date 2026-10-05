# IONOS Smoke Test

**Goal:** Verify CLI works end-to-end against the real IONOS mailbox using read-only operations only.

**Pre-conditions:**
- `mailbox-autopilot` installed (`uv tool install --editable .`); `mailbox-cleanup` remains an alias of the same CLI
- Network access to `imap.ionos.de:993`

## Steps

1. **Set credentials**

   ```bash
   mailbox-autopilot auth set --email you@example.com --server imap.ionos.de
   ```
   At the password prompt, enter the IONOS mailbox password.

2. **Test connection**

   ```bash
   mailbox-autopilot auth test --email you@example.com --json | jq '.ok, .folders[]'
   ```
   Expected: `true` followed by folder names (INBOX, Sent, Papierkorb, ...).

3. **Scan INBOX (read-only)**

   ```bash
   mailbox-autopilot scan --email you@example.com --json | jq '.total_messages, .size_total_mb'
   ```
   Expected: integer count and MB total.

4. **Top senders**

   ```bash
   mailbox-autopilot senders --email you@example.com --top 10 --json | jq '.senders'
   ```
   Expected: list of 10 sender objects.

5. **Find large attachments (read-only)**

   ```bash
   mailbox-autopilot attachments --email you@example.com --size-gt 10mb --json | jq '.candidate_count'
   ```

6. **Dry-run delete (no --apply!)**

   ```bash
   mailbox-autopilot delete --email you@example.com --sender notifications@example.com --json | jq '.dry_run, .affected_count'
   ```
   Expected: `true` and a count. Mailbox is unchanged.

## Pass criteria

- All 6 steps complete without errors
- No `--apply` flag used anywhere — mailbox state unchanged
- Audit log empty (no operations performed)
