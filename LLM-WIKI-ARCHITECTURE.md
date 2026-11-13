# LLM Wiki — deployment architecture

This document records **one specific installation**: the user's vault, this fork of
obsidian-second-brain, and the two agents that read the vault. It is not the skill's own
architecture — that is [`architecture.md`](architecture.md) in this repo's root. This is the
deployment record, written so a future agent can understand the current state, change it
without breaking the invariants, and know which options were considered and rejected.

Last reviewed against:
- fork `644f41c` — docs: record the LLM Wiki deployment architecture
- vault `fe29472` — config: name both global instruction files in the vault charter

---

## 1. The three layers

| Layer | Path | Role |
|---|---|---|
| **Knowledge** | `/Users/jens/Projects/LLM_Wiki` | The vault. Plain markdown, git-versioned, local-only. The long-term memory. |
| **Tooling** | `/Users/jens/Projects/obsidian-second-brain` | The fork. Source of truth for commands, prompts, scripts and references. |
| **Agents** | Pi (primary) and Claude Code (reader) | Two surfaces onto the same vault. |

**The invariant everything else follows from:** code lives in project repos under
`~/Projects`; knowledge lives in the vault. A repo gets code, the vault gets what was
learned. A repo never receives vault notes, and the vault never receives code.

---

## 2. The vault

### 2.1 Path and git

`/Users/jens/Projects/LLM_Wiki` — a git repo with **no remote** (local only, 6 commits).

The vault was moved here from `~/Documents/obsidian/LLM_Wiki` for three reasons:
`~/Projects` is already the repo tree (uniform "everything here is a git repo" rule), it is
outside macOS TCC-protected `~/Documents` (so scheduled or headless runs do not need a Full
Disk Access grant), and the old location shared a parent folder with a second, populated
vault.

A **second vault** lives at `~/Documents/obsidian/Vault` (526 notes, cybersecurity / IT /
photography content, not git). It is deliberately **not** part of this architecture. The
user intends to ingest selected documents from it by hand. Do not merge it, symlink it, or
point any tool at it without an explicit instruction.

### 2.2 Layout

Builder preset, wiki style. `wiki/{daily,projects,entities,logs,architecture,debugging,concepts,tasks}`,
plus `boards/`, `templates/`, `Bases/`, `Inbox/`, `_trash/`. The `wiki/*` folders are the
typed storage; `Inbox/` is the capture tier (see §2.5).

### 2.3 Instruction files — the part that matters

Four files, each with one job. Confusing them is the most likely way to break this setup.

| File | Lines | Loads when | Job |
|---|---|---|---|
| `<vault>/_CLAUDE.md` | ~120 | **never automatically** | The vault's operating manual: folder map, naming, kanban format, propagation rules, Inbox/MCP contract. |
| `<vault>/AGENTS.md` | ~45 | cwd is the vault or below | The housekeeping charter: session role, skill update procedure, vault git discipline. |
| `<vault>/.claude/CLAUDE.md` | ~7 | Claude Code only, in the vault | Imports `_CLAUDE.md` via `@../_CLAUDE.md`. Gitignored. |
| `<vault>/.vault-config.json` | — | read by the scripts | `exclude-dirs: [".pi", ".claude", ".venv"]`. |

**Why `_CLAUDE.md` is never auto-loaded:** it starts with an underscore, so it is not a
context-file name for either agent. That is intentional — it is a *document* the agent is
told to read, not an always-on instruction file. The housekeeping charter (`AGENTS.md`)
points at it; the Claude Code hook injects it; the Pi global `AGENTS.md` tells coding
sessions to read it before writing.

### 2.4 `<vault>/.pi` is a real directory with symlinked children

```
/Users/jens/Projects/LLM_Wiki/.pi/          real directory
  prompts -> ../../obsidian-second-brain/dist/pi/.pi/prompts
  skills  -> ../../obsidian-second-brain/dist/pi/.pi/skills
  subagents/                               real; pi-subagents schedule store
```

This is the single most surprising piece of the deployment. It exists because the Pi
adapter's design is "copy the built `.pi/` tree into your vault so Pi discovers prompts and
skill from the project root", while this deployment installs the skill as a **Pi package**
(§3.3) — so the vault's copy is redundant for discovery. It is kept because a session whose
cwd *is* the vault resolves the commands' relative `.pi/skills/...` paths natively against
it. Symlinking the children at the build makes them follow `dist/` instead of drifting
from it.

**Why the directory itself is real, not a symlink.** `.pi` used to be a single symlink to
`dist/pi/.pi`. That made every `<vault>/.pi/<x>` path resolve into the fork's build tree,
which pi-subagents rejects: its schedule store is unconditionally at
`<project>/.pi/subagents/schedules`, and `assertScheduleRoot` walks up from there to the
first existing component, takes its realpath, and refuses to write project state that
lands outside the real project. Without the check it would have created `subagents/`
inside `dist/` — runtime state in a build artifact. The real `.pi` gives extensions a
legitimate in-vault home under `.pi/` while `prompts` and `skills` still follow the build.

Two consequences to remember:
- `.gitignore` lists `.pi` **without a trailing slash**. A trailing slash matches only a
  real directory; git treats a symlink as a file — which mattered when `.pi` was one
  (`762dca8` fixed exactly this). The pattern now covers the real directory and everything
  under it, including `subagents/`.
- A `git clean -fdx` in the fork deletes `dist/`, which dangles the two child symlinks.
  Rebuild with `bash scripts/build.sh --platform pi` and they resolve again.

### 2.5 The Inbox capture tier

`Inbox/` holds three kinds of input: files the user drops in for manual ingest, web
clippings, and raw writes from the MCP server. The server's `save_note` defaults here
(`_NOTES_DIR = "Inbox"` in `vault_ops.py`). It is explicitly **not** a destination — a
maintenance session promotes notes from `Inbox/` into `wiki/` and does the full
`/obsidian-save` distribution there.

MCP-written notes carry `source: mcp` in the frontmatter so they stay distinguishable from
hand-authored ones.

### 2.6 `.gitignore`

Agent tooling is ignored and regenerable: `.pi`, `.claude`, `.claude-memory/`,
`.claude-runs/`, `.crew.lock`, `.crew-readers/`, `_export/`, `_trash/`, plus Obsidian's
churn files (`.obsidian/workspace.json`, `.obsidian/cache`,
`.obsidian/plugins/*/data.json`). `.obsidian/app.json` **is** tracked — that is the settings
that matter.

---

## 3. The fork, the build, and the two installs

### 3.1 The fork

`/Users/jens/Projects/obsidian-second-brain`, `origin = git@github.com:weberjh/obsidian-second-brain.git`.
Upstream is `eugeniughelbur/obsidian-second-brain`.

The fork is the source of truth. Local changes are committed here; upstream changes are
merged in. Nothing in this deployment is edited inside `dist/` or inside an install — those
are build artifacts and get overwritten.

### 3.2 The build

`scripts/build.sh` compiles the neutral `commands/` source through the `adapters/` layer.
`dist/` is gitignored.

```bash
bash scripts/build.sh --platform pi            # -> dist/pi/
bash scripts/build.sh --platform claude-code   # -> dist/claude-code/
```

The two builds are **not** the same shape:
- `dist/pi/` is a Pi package: `.pi/prompts/` (48 prompts) + `.pi/skills/obsidian-second-brain/`.
  The prompts reference `.pi/skills/...`.
- `dist/claude-code/` is a Claude Code plugin tree: `commands/` (49 commands, including
  `/obsidian-calendar`), `SKILL.md`, `references/`, `scripts/`, `hooks/`, `integrations/`.
  The commands reference bare relative paths (`references/ai-first-rules.md`).

That difference is why the two agents need different instruction surfaces (§5).

### 3.3 The Pi install — option C

`pi install ./dist/pi` registers the local path in `~/.pi/agent/settings.json` under
`packages`. The package's own `pi.prompts` and `pi.skills` supply the commands and the skill.
This was chosen over copying `.pi/` into the vault (§7.1) and over registering the build
directly as global resources (§7.2) because it is the documented canonical path and leaves
the vault containing only knowledge.

Per-session cost is small: the skill's *description* (~84 tokens) plus the global `AGENTS.md`
(~860 tokens). The 48 prompt templates cost **zero** in the system prompt — they are `/`
commands and appear only in the completion menu.

### 3.4 The Claude Code install — classic, not the plugin

```bash
ln -sfn ~/Projects/obsidian-second-brain/dist/claude-code ~/.claude/skills/obsidian-second-brain
ln -sfn ~/Projects/obsidian-second-brain/dist/claude-code/commands/*.md ~/.claude/commands/
```

49 commands land as bare names in `~/.claude/commands/`, matching the Pi install's naming.
The plugin path (`/plugin marketplace add`) was rejected (§7.3) because it pulls from GitHub,
so local fork commits would have to be pushed before taking effect.

The SessionStart hook is wired **by hand** in `~/.claude/settings.json` as a second
`SessionStart` entry beside the user's own `herdr-agent-state.sh`:

```json
{"matcher": "", "hooks": [{"type": "command",
  "command": "/Users/jens/.claude/skills/obsidian-second-brain/hooks/load_vault_context.sh"}]}
```

The hook is what makes the Claude Code commands work: it injects the skill root, and — when
cwd is inside the vault — the vault manual. `setup.sh` would wire this plus a PostCompact
background agent and a PostToolUse validator; neither was installed, by choice (§5.4, §7.9).

---

## 4. The MCP server

### 4.1 The server and its two registrations

`integrations/obsidian-mcp-server/server.py` is the connector: 12 tools — `obsidian_search`,
`obsidian_read_note`, `obsidian_save_note`, `obsidian_capture`, `obsidian_update_note`,
`obsidian_replace_text`, `obsidian_move_note`, `obsidian_validate_note`,
`obsidian_backlinks`, `obsidian_vault_health`, `obsidian_list_skills`, `obsidian_get_skill`.
`vault_ops.py` beside it is the standalone engine — it cannot import from `scripts/`, so its
exclusion literal is duplicated and pinned by a test (§6.5).

Both agents register the **same source file**, with different names and transports:

| Agent | Config | Name | Exposure |
|---|---|---|---|
| Pi | `~/.pi/agent/mcp.json` | `obsidian` | `codemode`, 12 tools |
| Claude Code | `~/.claude.json` → `mcpServers` | `obsidian-second-brain` | stdio, 12 tools |

Both pass `OBSIDIAN_VAULT_PATH=/Users/jens/Projects/LLM_Wiki`.

**Why the source file and not the build's:** neither build ships `server.py`. The adapter's
`copy_vault_ops` copies only `vault_ops.py`, so the plugin manifest's
`${CLAUDE_PLUGIN_ROOT}/integrations/obsidian-mcp-server/server.py` and the classic install's
`setup.sh` command both point at a file that does not exist in `dist/`. Pointing at the
source is the working workaround; the real fix is two lines in `adapters/lib.sh` (§9.1).

### 4.2 The write contract

MCP writes are **raw**: the server validates the note, appends an `index.md` entry and an
operation-log line, and runs `OBSIDIAN_POST_WRITE_CMD` if set. It does **not** run the
`/obsidian-save` distribution — no people stubs, no project note, no board card, no decision
section. That is why the split in §5.5 exists: coding sessions capture, vault sessions
maintain.

`OBSIDIAN_POST_WRITE_CMD` is **unset**, so MCP writes land uncommitted. Deliberate for now
(§7.7).

---

## 5. The instruction surfaces

### 5.1 Pi global — `~/.pi/agent/AGENTS.md` (~72 lines, ~860 tokens/session)

Loads in **every** working directory. The coding-session contract: vault path, the
code/knowledge split, "read `_CLAUDE.md` before writing", the skill's Skill root
(`.../dist/pi/.pi/skills/obsidian-second-brain`) with the override instruction for the
prompts' `.pi/skills/...` paths, the MCP tool list and raw-write contract, the AI-first
rules, repo linkage, and a two-line pointer to the vault's git discipline.

### 5.2 Claude Code global — `~/.claude/CLAUDE.md` (~57 lines, ~730 tokens/session)

The same contract, minus the Skill-root section. It is omitted because the SessionStart hook
already injects the skill root into every Claude Code session, so repeating it would be
duplicate context. It names the `obsidian-second-brain` MCP server and the
`~/.claude/skills/obsidian-second-brain` skill root instead.

### 5.3 Vault charter — `<vault>/AGENTS.md` (~45 lines)

Loads **only** when cwd is the vault or below — structurally, by cwd, with no configuration.
It opens by superseding the global file: "the global agent instructions describe how *coding*
sessions use the vault... this session is the opposite. You are the vault maintainer. Use the
full skill and its `/obsidian-*` commands, not the MCP tools." Then the skill update
procedure, the vault git discipline, and the housekeeping cadence.

### 5.4 Claude Code SessionStart hook — `load_vault_context.sh`

Injects the skill root always, and the vault manual only when cwd is inside the vault. This is
the mechanism that replaces the convention the Pi prompts need. The PostCompact background
agent and the PostToolUse `validate-ai-first.sh` are **not** wired — the first by instruction,
the second because Claude Code is a reader here.

### 5.5 The split, end to end

| Session | cwd | Loads | Writes via |
|---|---|---|---|
| Pi coding | `~/Projects/<repo>` | Pi global only | `obsidian` MCP server |
| Pi vault | `/Users/jens/Projects/LLM_Wiki` | Pi global + vault charter | full skill, `/obsidian-*` |
| Claude Code coding | `~/Projects/<repo>` | Claude global + hook's skill root | `obsidian-second-brain` MCP |
| Claude Code vault | `/Users/jens/Projects/LLM_Wiki` | Claude global + vault charter + hook's manual | commands (reader convention) |

### 5.6 The update procedure

```bash
cd ~/Projects/obsidian-second-brain
git pull                      # merge upstream into the fork
bash scripts/build.sh --platform pi
bash scripts/build.sh --platform claude-code
pi install ./dist/pi          # refresh the Pi package
/reload                       # in Pi
```

The vault's `.pi` child symlinks need nothing — they follow `dist/pi/.pi`. The Claude Code
commands need nothing — they follow `dist/claude-code`. **Only the Pi package needs an
explicit reinstall**, because `pi install` copies rather than links. That asymmetry is the one
maintenance step to remember.

---

## 6. Decisions and why

### 6.1 The vault moved to `~/Projects/LLM_Wiki`
`~/Documents` is TCC-protected on macOS; interactive shells can read it but scheduled or
headless runs often cannot without Full Disk Access. `~/Projects` is already the repo tree, so
"everything here is a git repo" is one rule instead of two. Obsidian was not running and its
registry only ever listed the old `Vault`, so the move cost nothing. A symlink remains at the
old path for anything still pointing there.

### 6.2 Pi installed as a package (option C)
Canonical per the docs, and the only option where the vault contains no tooling. Options A
and B are in §7.1 and §7.2.

### 6.3 The housekeeping charter lives at `<vault>/AGENTS.md`, not `<vault>/.pi/AGENTS.md`
The user's first instinct was `.pi/AGENTS.md`. That **does not work**: Pi's context loader
walks directories and checks five filenames (`AGENTS.override.md`, `AGENTS.md`, `AGENTS.MD`,
`CLAUDE.md`, `CLAUDE.MD`) at each directory's *root*; it never descends into `.pi/`. A file
there would be silently ignored — worse than the status quo, because the housekeeping
instructions would vanish from the session that needs them. The vault root achieves the same
exclusion *structurally*: a coding session's cwd is a repo, so the vault is not an ancestor
and the file never loads. No gitignore entry, no search exclusion, no configuration.

### 6.4 `<vault>/.pi` is a real directory whose children symlink the build
The duplicate copy drifts. Child symlinks mean one build feeds both the package and the
vault's native path, while the real directory keeps project state (`subagents/`) inside the
vault. It was a single symlink until pi-subagents' schedule-store check refused to bind in
vault sessions (§2.4). Caveats in §2.4. Considered and rejected: deleting it entirely and
putting the Skill-root override in the vault charter instead — that works, but then the
vault session needs a convention where it could have had a mechanism.

### 6.5 `.pi` is excluded from vault scanning
Before the fix, a search for a topic returned a command's prompt text before the real note —
`.pi/prompts/x-pulse.md` matched "agentic coding". The patch touches three files and is
pinned by a test so a future upstream merge cannot quietly erase it:
- `scripts/vault_scan.py` → `.pi` in `BASE_EXCLUDE_DIRS`. All five scanning tools
  (`vault_health`, `link_graph`, `export_okf`, `vault_stats`, `freshness_lint`) derive from it.
- `integrations/obsidian-mcp-server/vault_ops.py` → `.pi` in `_SKIP_DIRS`. This is the
  standalone literal used by `vault_search` **and** the MCP server, so it fixes both.
- `tests/test_exclude_policy.py` → `.pi` asserted in the base.

Verified: `agentic coding` now returns 2 results, both real vault files.

### 6.6 MCP is the coding-session access path
The skill ships its own connector and its README calls it "the doorway to *use* your vault
without the vault becoming the agent's behavioral memory" — exactly this case. It also costs
less context than 48 prompts and enforces the vault's write conventions server-side. The Pi
MCP uses `codemode` exposure, so the 12 tool docstrings are **not** in the system prompt;
only a one-line server description is. Roughly 60 tokens, not 960.

### 6.7 The Inbox tier exists
The server's `save_note` defaults to `Inbox/`, and the builder preset's folder map had no such
folder — so an MCP save would land in a folder the manual does not describe. Adding `Inbox/`
as the documented capture tier resolved that, and gave web clippings and manual drops a home.

### 6.8 Claude Code is a reader
The user's choice. Wired to the point where it can search, read and run commands, but without
the machinery that makes a first-class maintainer: no PostToolUse write validator, no
background agent. Housekeeping stays in Pi.

### 6.9 The Claude Code classic install, not the plugin
The plugin pulls from GitHub; the fork is local. The classic install symlinks `dist/`, so fork
commits take effect on the next `/reload` without a push.

### 6.10 The server stays in the source repo
Rather than patching `adapters/lib.sh` to ship `server.py` in both builds. Chosen for now to
keep the fork's diff against upstream small. Cost: both agents' configs point outside their
install trees (§9.1).

### 6.11 One global file per agent, not one shared file
They differ deliberately: Pi's needs the Skill-root block because Pi has no hook; Claude
Code's omits it because its hook injects it. Symlinking one to the other would force the
larger, wrong-for-one-agent text on both.

---

## 7. Roads not taken

### 7.1 Copy the built `.pi/` into the vault (option A)
The adapter's documented alternative. Rejected because it leaves tooling in the knowledge
repo, needs the `.pi` search exclusion permanently, and requires the vault copy to be
refreshed by `update-vault-integration.sh` — a second update path beside the package install.
It also drops `package.json` and `INSTALL.md` into the vault root.

### 7.2 Register `dist/pi` as global resources (option B)
`resources.prompts` + `resources.skills` pointing at the build. Rejected in favour of the
package: both leave the vault clean, but B puts a local-path declaration in `settings.json`
while C uses the documented install path. B's only advantage — no reinstall step after a
rebuild — was not worth diverging from the canonical route.

### 7.3 The Claude Code plugin install
Ships all 49 commands, the hook, the background agent and the MCP server in one step. Rejected
because it resolves from GitHub: local fork changes would need pushing first, and the plugin's
commands are namespaced (`/obsidian-second-brain:obsidian-save`) rather than bare.

### 7.4 A symlink for the Pi Skill-root override
Tempting and wrong. The override exists because the prompt bodies use a **cwd-relative** path
(`./.pi/skills/...`), and a repo's cwd has no `.pi/` child. A symlink only helps if it replaces
the directory being looked up, so the working version would be `<repo>/.pi -> <vault>/.pi` in
every repo. That collides with each repo's own `.pi/` project config (settings, `mcp.json`,
skills, prompts), is a per-repo setup step, puts a local absolute path into each repo's git
history (symlinks are tracked), dangles if the vault moves, and would re-register the vault's
48 prompts in every repo session — defeating the reason option C was chosen. The convention
costs five lines and works.

### 7.5 Patch `adapters/lib.sh` to ship `server.py`
The correct long-term fix (§9.1). Deferred to keep the fork's diff small. Two lines in
`copy_vault_ops` would make both builds self-contained.

### 7.6 `disable-model-invocation: true` on the skill
Would hide the skill from automatic model selection, cutting its system-prompt cost to ~0. Not
done: ~84 tokens is not worth losing automatic routing. Revisit if the skills listing becomes
distracting.

### 7.7 `OBSIDIAN_POST_WRITE_CMD`
Would let every MCP write commit itself to git. Left unset so captures land uncommitted and
the maintenance session reviews them in a batch. Setting it would make captures durable but
noisy.

### 7.8 Unattended `rewrite_policy`
The skill's `ai-first-rules.md` allows a vault to opt into unattended rewrites, on the
condition that review happens elsewhere — git history or a nightly health scan. Not adopted:
git history is not reviewed reliably enough yet, and the `confirm` gate is the only thing
preventing an external source from rewriting notes unreviewed. Revisit once a health scan is
routine.

### 7.9 First-class Claude Code
Would add a maintained `~/.claude/CLAUDE.md` plus tracked vault instructions plus the
PostToolUse validator. Rejected for now: more surfaces to keep in sync for a second agent that
is not doing housekeeping. Revisit if vault writes from Claude Code become routine.

### 7.10 The domain spine
`wiki/electronics/`, `wiki/cyber/`, `wiki/agentic/` were considered and dropped. The vault uses
a **type** layout, not a **topic** layout; adding topic folders would fork the convention and
`/obsidian-health` would object. Topics are handled by `tags:` plus per-domain MOCs when usage
justifies them. Deferred until real content shows the actual categories.

### 7.11 Merging `~/Documents/obsidian/Vault`
The second vault is closer to the user's stated domains (cybersecurity, IT) than the empty new
one. Rejected as a bulk migration: the user will ingest selected documents by hand. The skill's
First-Brain wiki variant supports human sources in a `First-Brain/` folder if that changes.

### 7.12 Wiring the PostCompact background agent and PostToolUse validator
Both exist in the build's `hooks.json`. Neither is wired on Claude Code: PostCompact by
instruction (it is an opt-in background agent and Claude Code is a reader), PostToolUse because
it validates AI-first writes and this deployment does not intend Claude Code to write.
`setup.sh` would wire both — do not run it unexamined.

---

## 8. How to change things

### 8.1 Update the skill from upstream
```bash
cd ~/Projects/obsidian-second-brain
git pull                                  # merge upstream into the fork
bash scripts/build.sh --platform pi
bash scripts/build.sh --platform claude-code
pi install ./dist/pi
```
Then `/reload` in Pi and restart Claude Code. The vault's `.pi` child symlinks and the
Claude Code command symlinks need nothing. The Pi package is the only surface that needs
a reinstall.
If the upstream merge touches `scripts/vault_scan.py`, `vault_ops.py` or
`test_exclude_policy.py`, re-run `uv run pytest tests/test_exclude_policy.py -q` — the `.pi`
exclusion is pinned there.

### 8.2 Change the vault path
Five places, and missing one leaves a stale pointer:
1. `~/.config/obsidian-second-brain/.env` — `OBSIDIAN_VAULT_PATH`
2. `~/.pi/agent/mcp.json` — the `obsidian` server's `env`
3. `~/.claude.json` — the `obsidian-second-brain` server's `env`
4. `~/.claude/settings.json` — `env.OBSIDIAN_VAULT_PATH`
5. The vault path in **both** global instruction files: `~/.pi/agent/AGENTS.md` and
   `~/.claude/CLAUDE.md`, plus the vault's own `AGENTS.md` if it names itself.
Then move the vault and re-point `<vault>/.pi` at the fork's `dist/pi/.pi`.

### 8.3 Add a third agent
Check three things in order: (a) does it read `AGENTS.md`, `CLAUDE.md`, or its own name —
and "in place of" or "in addition to"? (b) does it have a hook mechanism to inject the skill
root? (c) does its build ship prompts as commands or as skills? Then install the matching
build, register the source `server.py` as an MCP server, and add a global instruction file.
Do not copy an existing global file verbatim — the Skill-root section is agent-specific.

### 8.4 Remove or rename the vault charter
If `<vault>/AGENTS.md` goes away, the housekeeping instructions have nowhere to load: `_CLAUDE.md`
is not auto-discovered and the Claude Code hook only fires in Claude Code. A Pi vault session
would then get only the coding-session global file. Re-home the content before deleting it.

### 8.5 Rebuild the vault's `.pi`
The directory itself is real; only its `prompts` and `skills` children are symlinks into
`dist/pi/.pi`. If they dangle after a `git clean -fdx` in the fork, `bash scripts/build.sh --platform pi`
recreates `dist/pi/.pi` and they resolve again. Do **not** run `update-vault-integration.sh`
against the vault — it would drop a full copied `.pi/` tree over the real directory,
burying `subagents/` and reintroducing drift.

---

## 9. Known gaps

### 9.1 Neither build ships `server.py`
`copy_vault_ops` in `adapters/lib.sh` copies only `vault_ops.py`. So `dist/pi/` and
`dist/claude-code/` have `integrations/obsidian-mcp-server/vault_ops.py` but no `server.py`,
while the Claude Code plugin manifest and `setup.sh` both reference `server.py` inside the
build. Both agents work only because their MCP configs point at the source repo. **If the fork
moves, both MCP servers break.** Fix: copy `server.py` beside `vault_ops.py` in
`copy_vault_ops`, rebuild, re-register both servers against the build.

### 9.2 Two global instruction files to keep in sync
`~/.pi/agent/AGENTS.md` and `~/.claude/CLAUDE.md` overlap. The vault path appears in both, so a
move means editing two files. They cannot be symlinked as-is because they differ deliberately
(§6.11). If the duplication becomes a burden, make the Pi file agent-neutral and symlink — but
then the Skill-root section has to move out of it, because Claude Code's hook already injects it.

### 9.3 Claude Code reads `AGENTS.md` only when `CLAUDE.md` is absent
Verified against the Claude Code docs and version 2.1.323 (support landed in 2.1.277). The
vault has no root `CLAUDE.md` — only `.claude/CLAUDE.md` — so `<vault>/AGENTS.md` is read. If a
root `CLAUDE.md` is ever added to the vault, the charter stops loading unless it is imported
with `@AGENTS.md` or the "Project instructions" setting is changed to read both. Check with
`/context`.

### 9.4 The vault charter's key-file list outruns reality
The Claude Code hook injects `index.md` and `log.md` as "use these directly, no discovery
needed". Neither exists until `/obsidian-init` runs. Harmless but misleading until then.

### 9.5 The Claude Code write path is ungated
"Reader" is a usage convention, not an enforcement. The write commands are installed and will
run; nothing stops `/obsidian-save` or `obsidian_save_note` in a Claude Code session. The only
mechanical gate Pi has and Claude Code lacks is `validate-ai-first.sh`. Add the PostToolUse
hook if that changes.

### 9.6 The Pi adapter's `--platform pi` build copies `package.json` and `INSTALL.md`
Not present in the vault today because the original install copied only `.pi/`. If
`update-vault-integration.sh` is ever run against the vault, both land in the vault root and
are not gitignored. Either ignore them or skip the copy.

---

## 10. Quick reference

```
vault              /Users/jens/Projects/LLM_Wiki          git, no remote
  _CLAUDE.md       operating manual, not auto-loaded
  AGENTS.md        housekeeping charter, loads at cwd==vault
  .pi/             real dir; prompts+skills -> fork dist/pi/.pi; subagents/ real
  Inbox/           capture tier; MCP save_note default

fork               /Users/jens/Projects/obsidian-second-brain
  origin           git@github.com:weberjh/obsidian-second-brain.git
  commands/        neutral source (49)
  dist/pi/         Pi package    -> pi install ./dist/pi
  dist/claude-code/ Claude build -> ~/.claude/skills + ~/.claude/commands

MCP server         <fork>/integrations/obsidian-mcp-server/server.py  (source, not build)
  Pi               ~/.pi/agent/mcp.json            name: obsidian
  Claude Code      ~/.claude.json -> mcpServers    name: obsidian-second-brain

instruction files  ~/.pi/agent/AGENTS.md     coding sessions, all cwds
                   ~/.claude/CLAUDE.md       coding sessions, all cwds
                   <vault>/AGENTS.md         housekeeping, cwd==vault only
                   <vault>/_CLAUDE.md        manual, read on demand
                   <vault>/.claude/CLAUDE.md imports _CLAUDE.md (gitignored)

env                ~/.config/obsidian-second-brain/.env
                   ~/.pi/agent/mcp.json, ~/.claude.json, ~/.claude/settings.json (env)
```
