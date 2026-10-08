# mailbox-autopilot — Design: draft a new mail (`manage compose`)

**Status:** Draft, for Sensei (requirements) and Founder review
**Author:** Obi, with three Founder decisions of 2026-10-08, 09:17 CEST (§2)
**Date:** 2026-10-08
**Topic:** Add a way to put a NEW outbound mail into the Drafts folder. Today the manage skill can only draft a reply to an existing mail. It still never sends.

Roles as in the [base design](2026-09-24-mailbox-autopilot-design.md): **Obi** builds, **Sensei** owns requirements and accepts, the Founder merges. This document contains no real mail content, names or addresses; every example is invented.

---

## 1. Goal and non-goals

**Goal:** when the owner says "write a mail to X about Y", the agent writes the text, shows it, and puts a finished draft into the Drafts folder. The owner sends it from their own mail client.

**Why:** `manage draft` requires `--uid`, the mail being answered. A mail that answers nothing has no path, so the owner copies the agent's text into the mail client by hand. This was observed twice in one week. Which mails those were is not recorded in this document and was not measured for it.

**Non-goals for the first version:**

1. **Sending.** Unchanged. The package contains no code that sends mail.
2. **Attachments.** Which local file may leave the machine is its own risk class and needs its own design.
3. **Bcc.** A hidden recipient is exactly what a reviewing human overlooks in a draft.
4. **Forwarding** an existing mail. It copies mail content to a new recipient by construction; see §4.

---

## 2. Decisions

| # | Decision | Decided by | Rationale |
|---|----------|------------|-----------|
| 1 | First version carries To and Cc only. No attachments, no Bcc | Founder, 2026-10-08 | Small enough to build and review in one pass |
| 2 | A recipient named by name may be looked up in the mailbox, and the address is shown to the owner for confirmation before the draft is written | Founder, 2026-10-08 | Nobody types addresses; a strict "typed only" rule would be worked around within a week |
| 3 | The capability goes through a Sensei ticket; this document is its design | Founder, 2026-10-08 | Sensei is the product manager |
| 4 | A separate subcommand, `manage compose`, instead of making `--uid` optional on `manage draft` | Obi (design) | In `manage draft` the recipient is computed from the answered mail and can never be typed. That property stays structural only if the reply path does not grow a recipient option |
| 5 | The audit record keeps today's shape: argument keys only, no recipient address, no subject | Obi (design) | Same rule as every other manage record; an address is personal data |

---

## 3. The command

```bash
mailbox-autopilot manage compose \
  --to alex@example.org --cc sam@example.org \
  --subject "Offer for the workshop" \
  --body-file /tmp/reply.txt --json
```

| # | Option | Rule |
|---|--------|------|
| 1 | `--to` | Required, repeatable. Each value must be a bare address that passes the strict address check `manage draft` already uses. No display names |
| 2 | `--cc` | Optional, repeatable, same check |
| 3 | `--subject` | Required. Control characters and whitespace runs collapse to one space, as for a reply subject |
| 4 | `--body-file` | Required. Same handling as in `manage draft`: opened once, regular UTF-8 text file only |
| 5 | `--account` | As everywhere. The From address is the account's own address |

To and Cc together are capped at 10 addresses. More than that fails with `bad_args`.

The result is appended to the resolved Drafts folder with the `\Draft` flag, with a fresh `Message-ID` and `Date` and no threading headers. If no Drafts folder is found the command stops with `no_drafts_folder`; it never creates one.

The JSON response returns `drafts_folder`, the subject and **every recipient address**, so the skill can show the owner what was actually written.

**Shared code, not copied code:** the strict address check and the header cleaning move from `draft.py` into one place that both `build_reply` and the new builder import.

### Looking up a recipient

`manage search` gets one new filter, `--recipient`, which matches the To header. It exists so the lookup can ask "whom has the owner written to before":

1. Search the Sent folder with `--recipient <name>`. An address the owner has already sent mail to is the strongest evidence that it is the right one.
2. Only when Sent has no match, search received mail with `--sender <name>`. An address found this way is shown with a warning: it comes from an incoming mail, and a sender can choose any display name.
3. One match or several, the owner sees the bare address (never only the display name) and says yes or picks. The skill never picks silently.

---

## 4. Safety

Until now a draft could only go to the sender of the mail being answered. A free recipient changes that. Two things can go wrong when a mail has deceived the agent:

1. **Wrong recipient.** The draft is addressed to someone the owner did not mean.
2. **Wrong content.** Text from the owner's mailbox ends up in a mail to an outsider. This is the larger risk: a reply has one natural source to quote from, a new mail has none.

Rules for the skill text:

1. **The recipient comes from the owner's words.** Never from the body of a mail, and never from a sentence in a mail that says where something should be sent. A looked-up address is confirmed by the owner (§3).
2. **Quoting rule, extended.** Any text copied from any mail into a new mail needs the owner's explicit yes that names the message (sender and date), asked before the draft is written. Mail read for context or tone is never copied.
3. **Show before write.** The skill shows recipients, subject and body, and writes the draft only after the owner's yes.
4. **Show after write.** The skill repeats the recipients from the command's response.

What stays true: the tool cannot send. The worst case is a bad draft that the owner sees in their mail client before sending. The rules above are instructions to an agent, not a mechanism; the only enforced parts are the address check, the recipient cap and the absence of send code.

---

## 5. Skill changes (`skills/manage/SKILL.md`)

1. Description gains the triggers "write a mail to X", "draft a new mail", "schreib eine Mail an X".
2. A new section "A new mail" with the flow: recipient (lookup and confirmation), tone from sent mail (unchanged step), write the text to a temporary file, show, `manage compose`, hand over.
3. The quoting rule gains the paragraph from §4 rule 2.
4. Playbooks are written for replies. A new mail uses `generic` plus the tone step.

---

## 6. Testing

1. **Unit:** the builder with hostile input: CR/LF and control characters in subject and addresses, display names, a second `@`, an empty recipient list, 11 recipients.
2. **Integration:** against the existing GreenMail server. Asserted: the draft lands in the Drafts folder, carries `\Draft`, has the given To, Cc and subject, and no `In-Reply-To`.
3. **Search:** `--recipient` matches the To header and nothing else.
4. **Unchanged, and named so a reviewer can check they still pass untouched:** `tests/test_no_send.py`, `tests/test_manage_no_destructive.py`, `tests/test_block_send_hook.py`.
5. **Not covered by any test:** the skill rules in §4. They are checked in an acceptance run on real mail with the owner present.

---

## 7. Out of scope, for later designs

1. Attachments on outbound drafts.
2. Forwarding.
3. Playbooks for outbound mail types.
4. A persistent address book. The lookup in §3 reads the mailbox each time and stores nothing.

## 8. Amendments from the build (2026-10-08)

The build and its two security reviews changed four things against the sections above. Each is listed with its cause.

| # | Section | Amendment | Cause |
|---|---------|-----------|-------|
| 1 | §3 row 4 | `--body-file` of `manage compose` AND of `manage draft` must be a file directly in the tool's own folder `~/.mailbox-cleanup/outbox/` (private to the user, located from the user database and not from any environment variable), at most 1 MB, no symlink. New command `manage outbox` creates the folder and prints its path | Two Founder decisions of 2026-10-08 after two review rounds. Round 1: a free recipient plus a free file read lets one command stage any readable local file as a draft. The first answer, "temp directory only", failed round 2: the temp directory comes from `TMPDIR`, which the constrained caller sets, and it is shared with other programs. Round 2 also showed that `manage draft` has the same read, and its recipient is the sender of the answered mail, who in the attack case is the attacker. The rule removes the one-command path and does not stop a file that was first copied into the outbox |
| 2 | §3 rows 1 and 2 | The address check is an allowlist (atoms and letter-digit-hyphen labels), an RFC 2047 encoded-word is refused, addresses are written as address objects, and the header is read back and compared with the input. The response reports the addresses read back from the message | Review finding, measured on Python 3.11: under the earlier denylist one accepted value was stored as two recipients |
| 3 | §3 "Looking up a recipient" | Search candidates carry the To header, inside the envelope | A Sent-folder hit otherwise shows only the owner's own From line, and the address to confirm would need `manage read`, which returns a body |
| 4 | §1 non-goals 2 to 4 | `--bcc`, `--attach`, `--attachment`, `--forward` and `--uid` exist as hidden options that refuse with `out_of_scope` | Ticket criterion 5 asks for a refusal that points to the scope; an unknown option would be answered with "No such option" |

**Not covered by any test:** a lookup by name (`--recipient Alex`). The test mail server matches address headers only against the full address, so only the full-address path is tested. The acceptance run on real mail covers it.

**Version:** the build ships as 0.4.0.
