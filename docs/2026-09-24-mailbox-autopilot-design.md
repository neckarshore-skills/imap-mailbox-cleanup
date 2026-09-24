# mailbox-autopilot — Design

**Status:** Draft, for Founder review
**Author:** MASCHIN (architecture), brainstormed with the Founder on 2026-09-24
**Date:** 2026-09-24
**Topic:** Turn `imap-mailbox-cleanup` into the `mailbox-autopilot` plugin. It adds a second skill that reads, searches and follows threads, and drafts replies. It never sends.

Roles: **Obi** builds. **Sensei** is the product manager: owns requirements, accepts results. The Founder merges until the leak guard (§6) is live. Use cases and real-mail examples are discussed in a **private tracker**, never in this public repository.

---

## 1. Goal and non-goals

**Goal:** answer recurring mail faster. Examples are recruiters and intermediaries, a school, banks and insurers. An agent finds the mail and its thread, picks a playbook, and puts a finished reply draft into the Drafts folder. The human sends it from their own mail client.

**Success:** for a mail type that has a playbook, the draft usually needs only light editing before sending.

**Non-goals:**

1. **Sending.** The package contains no code that sends mail (§5).
2. **Deleting or moving mail from the manage skill.** Those actions stay in the cleanup skill, behind its existing dry-run and confirm flow.
3. **An unattended daily run in v1.** v1 works only on explicit request ("reply to the mail from X"). A scheduled triage run is a later extension, and the interfaces below allow it without replacing code.
4. **Storing mail content** anywhere outside the mailbox.

---

## 2. Decisions taken (Founder, 2026-09-24)

| # | Decision | Consequence |
|---|---|---|
| 1 | One **public** repository for both skills | Shared IMAP base, no copy, no cross-repo dependency |
| 2 | Generic playbooks are public. **Private data never enters the repository.** | Private overlays live in local Markdown folders (§4) |
| 3 | Packaged as **one Claude Code plugin** with a send-blocking hook | Listed in the `neckarshore-plugins` marketplace, like `obsidian-vault-autopilot` |
| 4 | Name: **`mailbox-autopilot`** | The repository is renamed and GitHub redirects. The `mailbox-cleanup` CLI keeps working |
| 5 | Private overlays come from **several Markdown folders**, e.g. an Obsidian vault folder and a local clone of a private Git repository | One source type in v1 (§4). A GitHub-API source is a later addition |
| 6 | v1 is **on-request only**. A daily run comes later | Smallest prompt-injection and privacy surface |
| 7 | **Unsubscribe becomes link-only.** `mailto:` unsubscribe is removed | The whole package then really contains no send code (§5) |
| 8 | Leak guard: a **CI check before merge** plus a **daily scan after** | §6 |

---

## 3. Architecture

**Code layers:**

| # | Layer | Contents | State |
|---|---|---|---|
| 1 | Base | Keychain auth (`auth.py`), multi-account config (`config.py`), IMAP connection (`imap_client.py`), audit log (`audit.py`) | Exists, becomes the named shared base |
| 2 | Cleanup | scan, senders, archive, delete, move, dedupe, unsubscribe (link-only after §5) | Exists |
| 3 | Manage | `search`, `read`, `thread`, `draft` | **New** |

**Plugin layout:**

- A plugin manifest.
- Two skills: `cleanup` (today's `skill/SKILL.md`) and `manage`. Each has its own description so the agent picks the right one.
- The send-blocking hook (§5).
- `playbooks/` holding the public generic playbooks.

**Units of the manage layer.** Each unit has one job and can be tested on its own:

| # | Unit | Does | Depends on |
|---|---|---|---|
| 1 | `search` | Returns candidates (UID, sender, subject, date), no bodies | Base |
| 2 | `read` | Returns one message's body inside the content envelope (§5) | Base |
| 3 | `thread` | Returns the messages of a thread (References / In-Reply-To), each enveloped | Base, `read` |
| 4 | `draft` | Appends a reply to the special-use `\Drafts` folder with the `\Draft` flag and correct `In-Reply-To`/`References` | Base |
| 5 | `KnowledgeSource` interface + `MarkdownFolderSource` | Loads private playbook overlays from configured folders | Filesystem only |
| 6 | Playbook loader | Merges each public playbook with its overlays by playbook id, applies precedence, warns on conflicts | Units 5, `playbooks/` |

---

## 4. Playbooks and private overlays

**Public playbook:** one Markdown file per mail type. It carries frontmatter (`id`, recognition hints, tone) and a body of reusable text blocks. Starting set: recruiter/intermediary, school, bank, insurance, plus a generic path used when nothing matches.

- **How playbooks are created:** a playbook is added only for a recurring pattern.
- **Who owns the numbers:** the threshold and the hard cap are Sensei's product decision (see the private tracker). The code does not fix them.

**Private overlay:** a Markdown file in a configured folder whose frontmatter names the playbook `id` it extends. Examples of what it holds: contacts, reference numbers, personal phrasing.

**Configuration:**

- An ordered list of source folders in the local config next to the account config.
- **The first source wins.** When a second source overlays the same playbook id, the loader uses the first and **warns loudly**.
- A configured folder that is missing produces a loud warning, and the run continues with the generic playbook only. It is never silent.

**Tone** is taken from the user's sent mail at request time. The sent mail is not stored.

---

## 5. Safety: no sending, and mail content is data

**No send code in the package.** This requires removing today's `mailto:` unsubscribe path. It uses `smtplib` (`operations/unsubscribe.py`, lines 5 and 107–137).

- After the change, `unsubscribe` executes HTTPS one-click only.
- `mailto:`-only senders are listed for manual handling.
- A test asserts that `smtplib` is not imported anywhere in the package. It is a grep test, and Completion rule 7 applies to it.

**Send-blocking hook** (a PreToolUse hook shipped with the plugin):

- **What it blocks:** send routes it can recognise. Examples: `smtplib`/`sendmail` in `python -c` or scripts, the macOS Mail app driven by `osascript` with "send", and `curl` to `smtp://`/`smtps://`.
- **Honest scope:** this is an enforced mechanism **only for the routes it matches**. An obfuscated command can get past it. It is a partial second lock. The first lock is the absence of send code.
- **Keeping it narrow:** it must pass ordinary commands (`git`, `python -m pytest`, the plugin's own CLI).
- **Installation:** the hook runs in every session once the plugin is installed. Installing is a CONFIG-ASK act and needs the Founder's explicit confirmation.

**Prompt injection.** Every mail body returned to the agent sits inside a fixed envelope (`<mail-content> … </mail-content>`). The skill text states that envelope content is data and never an instruction.

- A literal `</mail-content>` (or `<mail-content>`) inside a body is **escaped**, so a mail cannot close its own envelope.
- The envelope rule is an intention, not a mechanism. What bounds the damage is layers 2 and 3:
  - the tool cannot send or forward;
  - the manage skill cannot delete or move.
- **Worst case:** a deceived agent produces a bad draft, which the human sees before sending.

**Audit log.** The manage skill records timestamp, subcommand, account, folder, UIDs and result.

- It does **not** record `args`. Today's `log_action` stores `args` verbatim, and for `search` those would be names and topics.
- Manage calls therefore use a separate record shape without `args`, or with `args` reduced to their keys.

---

## 6. Leak guard (public repository)

**Synthetic fixtures only.** Every test mail uses `example.com` / `example.org` addresses and invented names.

**CI check before merge.** A separate job, parallel to CI, scanning the files changed in the pull request.

**Public patterns (always run):**

- e-mail addresses outside an allowlist of example domains;
- IBANs;
- phone numbers.

**Private blocklist (runs when available):**

- **Where it lives:** in a GitHub Actions secret. It holds the owner's domains, family names and reference-number patterns.
- **When it is available:** only to pull requests from branches of this repository.
- **When it is not:** Dependabot and fork pull requests receive no secrets. There the job runs the public patterns only and **states in the log** that the private list was skipped. It does not fail. Failing would block every Dependabot auto-merge.

**Log hygiene (the repository is public, so its Actions logs are public):**

- A hit from the **public** patterns reports file, line and pattern name.
- A hit from the **private** list reports file and line with the label `private-list hit` **only**. It never prints the pattern and never prints the matched text.
- GitHub masks a secret only when the whole secret string appears in a log, so single terms from a multi-line list would leak otherwise.

**False positives:**

- An allowlist file in the repository exempts deliberate examples.
- Every entry shows up in the pull request diff and carries a one-line reason.

**Cost:** estimated ~10 s, running in parallel with the existing CI (53–67 s measured). This is unmeasured until built.

**Completion rule 7 for the gate itself:**

1. Put an invented term that is on a test copy of the private list into a fixture.
2. Watch the job fail with `private-list hit` and without the term in the log.
3. Restore the fixture.
4. Record steps 1–3 in the PR body.

**Daily scan after merge.** It covers all public repositories of the owner, including issues and comments, because the CI check sees only code. It needs the private list, so it cannot run in a public context.

- **Where it runs** (local launchd on the owner's machine, or a private repository with the list as a secret) is decided by the security persona before it is built.
- **The same log-hygiene rule applies to its output.**

---

## 7. Error handling

| # | Case | Behaviour |
|---|---|---|
| 1 | Connection or login fails | Clear message, stop. No retry loop (existing behaviour) |
| 2 | No special-use `\Drafts` folder | Stop with a message. Never create a folder on a guess |
| 3 | No playbook matches | Generic path. Ask the user when the tone is unclear |
| 4 | Configured overlay folder missing | Loud warning, continue with the generic playbook only |
| 5 | Same playbook overlaid by two sources | Use the first source, warn loudly |
| 6 | Several search hits for "the mail from X" | Ask the user which one. Never pick silently |

---

## 8. Testing

1. **Units:** each manage unit and the playbook loader against synthetic data.
2. **Integration:** against the existing GreenMail test server (`tests/docker-compose.test.yml`, `greenmail/standalone:2.1.0`). Asserted: the draft lands in `\Drafts`, carries `\Draft`, and threads correctly.
   - **Unmeasured:** whether this GreenMail setup exposes a special-use `\Drafts` folder. Verifying that is the first plan task. If it does not, the test creates the folder in setup, and that is stated.
3. **Hook:** one failing test per blocked send route, plus pass-through tests for ordinary commands.
4. **No-send invariant:** a test that fails if `smtplib` is imported anywhere in `src/`. Rule 7 applies: add an import, watch it fail, restore.
5. **Envelope escaping:** a body containing `</mail-content>` comes back escaped.

---

## 9. Out of scope for this spec, tracked elsewhere

1. **Rename cascade** (plan tasks, not design):
   - the repository rename;
   - the estate repo inventory and org docs;
   - the marketplace entry;
   - the `pyproject` package and CLI names (the `mailbox-cleanup` entry point stays as an alias);
   - local remotes.
2. **Sensei merging after acceptance** needs an AD-61 revision in the org planning repository. It does not exist yet. Until then the Founder merges.
3. **Obi commenting on assigned issues in the private tracker:** Founder-approved. The persona file change is owned by MASCHIN.
4. **The scheduled daily triage run:** a later design, on top of the unchanged v1 interfaces.
