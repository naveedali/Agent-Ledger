# 📒 Agent Ledger

[![Tests](https://github.com/naveedali/Agent-Ledger/actions/workflows/tests.yml/badge.svg)](https://github.com/naveedali/Agent-Ledger/actions/workflows/tests.yml)

**One daily log for all your AI coding agents.**

You ask Claude, Codex and Cursor to do the work, and by evening you can't remember what got done. Agent Ledger fixes that: each agent writes a short note when it finishes a task, and one command turns those notes into a clean daily digest.

- ✅ Works with **Claude Code, Codex, Cursor**, and any agent that reads `AGENTS.md`
- 📄 Plain Markdown files. No server, no account, no tracking
- 🐍 One Python file, zero dependencies

---

## How it works

1. **Agents log.** After each task, an agent adds a short entry to its own file for the day (`claude.md`, `codex.md`, ...).
2. **You compile.** Run one command (or ask any agent) and get `DIGEST.md`: what's done, what's blocked, follow-ups, and the day's git commits.

## Pick a mode

| | 🌍 **Global** (recommended) | 📁 **Project** |
|---|---|---|
| Where logs live | `~/agent-ledger/` | `ledger/` inside the project |
| Files added to your repos | **None** | `ledger/`, `AGENTS.md`, `CLAUDE.md` |
| Covers | All your projects in one digest | One project |
| Best for | Freelancers, client work, side projects | Teams who want shared logs in the repo |

Not sure? Choose **Global**. You can use both at the same time.

```
Global mode                          Project mode
~/agent-ledger/                      your-project/
  2026-11-05/                          ledger/
    claude.md                            2026-11-05/
    codex.md                               claude.md
    DIGEST.md                              DIGEST.md
```

---

## Quick start

**1. Get it**

```bash
pipx install ai-agent-ledger      # or: pip install ai-agent-ledger
```

That gives you the `agent-ledger` command. Prefer no install? Clone the repo and use `python3 Agent-Ledger/ledger.py` wherever this README says `agent-ledger`:

```bash
git clone https://github.com/naveedali/Agent-Ledger.git
```

**2. Set it up**

```bash
agent-ledger init
```

It asks which mode you want. Or skip the question:

```bash
agent-ledger init --global                            # one ledger for everything
agent-ledger init --project path/to/project           # ledger inside a project
agent-ledger init --project path/to/project --private # same, hidden from git
```

> 💡 In project mode, point `--project` at **the project your agents work in**, not the Agent-Ledger folder. `.` means the folder you're in right now.

What `init` does:

- **Global:** adds the logging rule to your *personal* agent settings (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`) and adds `/digest` to Claude Code. For **Cursor**, paste the rule from `~/agent-ledger/CURSOR_RULE.md` into *Settings → Rules → User Rules*.
- **Project:** adds the rule to the project's `AGENTS.md` and `CLAUDE.md` and creates `ledger/`. With `--private`, everything Agent Ledger creates is hidden from git on your machine only. (If `AGENTS.md` was already in git, the added rule still shows in `git diff`; use global mode to avoid that.)

- **Both:** in Claude Code, adds a small **log reminder hook**. If Claude changed files but didn't log the work, it's asked to log before it finishes. Skip it with `--no-hook`.

Your existing content is always kept, and running `init` again is safe.

**3. Restart your agents.** Agents read their rules when a session starts, so close and reopen any Claude Code, Codex or Cursor session that was already open.

**4. Work as usual.** Give your agents tasks. They log as they go.

**5. See your day**

```bash
python3 ~/agent-ledger/ledger.py today    # global mode
python3 ledger/ledger.py today            # project mode
```

Or just ask any agent: *"give me today's digest"*. In Claude Code, type `/digest`.

---

## What an entry looks like

Agents log with one command, so the date, time and format are always right:

```bash
python3 ~/agent-ledger/ledger.py log --agent codex --task "Add onboarding screen with skip flow" \
  --files "OnboardingScreen.kt, NavGraph.kt" --follow-up "Needs analytics event"
```

That adds this to today's `codex.md` (the project name comes from the git repo you're in):

```markdown
## 14:32 · Atfal Compass · DONE
- Task: Add onboarding screen with skip flow
- Files: OnboardingScreen.kt, NavGraph.kt
- Repo: ~/code/atfal-compass
- Follow-up: Needs analytics event
```

Status is `DONE` (default), `PARTIAL` or `BLOCKED`. The `Repo:` line is used in global mode so the digest can include that repo's commits. Agents that can't run commands write the same entry by hand.

## What the digest looks like

```markdown
# Daily Digest — 2026-11-05

**3 tasks** · ✅ 1 done · 🟡 1 partial · 🔴 1 blocked · 2 commits
Agents: claude, codex
Projects: Atfal Compass, Client App

## ✅ Done
- **14:32** · Atfal Compass · _codex_ — Add onboarding screen with skip flow

## 🟡 Partial / 🔴 Blocked
- 🟡 **09:10** · Client App · _claude_ — Write README
- 🔴 **16:00** · Client App · _claude_ — Fix payment crash

## 📌 Follow-ups
- [ ] Needs analytics event _(Atfal Compass, codex)_

## 🔀 Commits
- `610cfdf` [atfal-compass] 14:40 feat: onboarding screen
- `a91c2e4` [client-app] 16:20 docs: add README
```

## Use it as an MCP server (optional)

Agents that support [MCP](https://modelcontextprotocol.io) can log through a real tool instead of a shell command. It's more reliable, and works even where an agent can't run commands. No extra install: the server is built into `ledger.py`.

```bash
agent-ledger mcp-install
```

This adds the server to **Cursor** (`~/.cursor/mcp.json`) and **Codex** (`~/.codex/config.toml`), keeping what's already there, and prints the one command to add it to **Claude Code**:

```bash
claude mcp add --scope user agent-ledger -- python3 "/path/to/ledger.py" mcp
```

Restart your agents and they get five tools:

| Tool | What it does |
|---|---|
| `log_work` | Add an entry to today's log (same fields as `ledger.py log`) |
| `daily_digest` | Today's (or any day's) digest, with a `redact` option |
| `work_report` | A report for a date range, with `project`, `agent` and `redact` options |
| `standup` | Yesterday / Today / Blockers |
| `ledger_status` | Check the setup |

So you can also just ask an agent *"what did we do this week?"* and it answers from the ledger.

## Commit safety net (optional)

Turn it on in any repo, and a commit nobody logged still makes it into your ledger:

```bash
cd your-project
agent-ledger git-hook install        # agent-ledger git-hook uninstall to remove
```

After each commit, if no agent logged work for that repo in the last 30 minutes, an entry is added for agent `git` with the commit message and files. It never blocks or slows a commit, keeps any `post-commit` hook you already have, and skips merge commits. Set `AGENT_LEDGER_COMMIT_WINDOW` (minutes) to change the window.

## Recover work nobody logged

Claude Code and Codex keep a record of every session on your machine. `recover` reads those records and finds sessions that changed files but never made it into your ledger:

```bash
agent-ledger recover                   # preview today's missing work
agent-ledger recover --date yesterday  # or any day
agent-ledger recover --apply           # add it to your ledger
```

Each recovered entry uses the agent's own end-of-task summary, the files it changed (or the files in commits made during the session), and a note that it was recovered. Sessions that already logged, read-only sessions, and anything recovered before are skipped, so it's safe to run any time. Nothing leaves your machine.

It reads `~/.codex/sessions` and `~/.claude/projects` (or `CODEX_HOME` and `CLAUDE_CONFIG_DIR` if you set them). Both formats belong to those tools and can change between versions, so treat this as a best-effort backup to logging, not a replacement.

## Standup in one command

```bash
agent-ledger standup
```

```
Standup · Mon 09 Nov 2026

Last working day (Fri 06 Nov)
• Added a Contact & Support section to Settings (project-xyz)
• Migrate auth screens to Compose, in progress (client-app)

Today
• Done: Committed the profile editor with change notes (project-xyz)
• Finish signup validation (client-app)
• Continue: Migrate auth screens to Compose (client-app)

Blockers
• Payment integration (needs: production keys) (client-app)
```

Plain text, so it pastes cleanly into Slack, Teams or a meeting chat. "Yesterday" is your last day with logged work, so Monday shows Friday. **Today** collects what's already done today, plus follow-ups and unfinished work carried over. Filter with `--project` or `--agent`, add `--redact` before sharing, and use `--date` for another day. MCP agents get it as the `standup` tool.

## Reports for any date range

For a weekly review, a client update or an invoice, build a report across several days:

```bash
python3 ~/agent-ledger/ledger.py week                                    # last 7 days
python3 ~/agent-ledger/ledger.py report --from 2026-11-01 --to 2026-11-15
python3 ~/agent-ledger/ledger.py report --from 2026-11-01 --project client-app --redact
```

The report groups work by project and day, with a summary table, follow-ups and commits. It's saved in `reports/` inside your ledger (add `--print` to also show it, or `--out file.md` to save it elsewhere).

- `--project NAME` / `--agent NAME`: only that project or agent
- `--redact`: hides emails, API keys and tokens, and home-folder paths. Use it before sending a report to anyone.

## Clients and time (for freelancers)

Tag work with a client, and get the time spent per client and project, ready for a client update or an invoice.

```bash
agent-ledger client client-app "Acme Corp"      # link a project to a client once
agent-ledger report --from 2026-11-01 --client "acme corp" --redact --open
```

- **Time:** an entry logged with `--time 1h30m` (or `45m`, `1.5h`) uses that. Otherwise the time is **estimated** from the gap since the same agent's previous entry that day, up to 2 hours, and marked with `~`. The first entry of a day gets no estimate.
- **Clients:** an entry's own `--client` wins; otherwise the project's linked client is used. `agent-ledger client` lists the links; `client PROJECT --remove` drops one.
- Reports show time per task and a **Time** table (client, project, logged, estimated, total). The HTML view adds a total-time tile.

Estimates are a guide, not a timesheet: when you bill by the hour, log real time with `--time`.

## View it as a web page

Add `--html` to any digest or report to also get a clean, formatted page, or `--open` to open it in your browser straight away:

```bash
python3 ~/agent-ledger/ledger.py today --open                 # today's digest
python3 ~/agent-ledger/ledger.py week --redact --open         # last 7 days
```

The page has summary tiles, a status bar, an **Activity** chart (tasks per day by status, and tasks per agent; hover a bar for the numbers), every project's work grouped by day, follow-ups and commits. You can filter by status or search tasks, files and agents. It's a single file with no internet needed, works in light and dark mode, and prints cleanly, so *Print → Save as PDF* gives you a report to attach to an email or invoice.

---

## Commands

| Command | What it does |
|---|---|
| `ledger.py init` | Set up (asks which mode) |
| `ledger.py init --global` | Global mode |
| `ledger.py init --project [folder] [--private]` | Project mode |
| `ledger.py init ... --no-hook` | Set up without the Claude Code log reminder |
| `ledger.py log --agent NAME --task "..."` | Add an entry (agents run this). Options: `--files`, `--status`, `--follow-up`, `--notes`, `--project`, `--client`, `--time` |
| `ledger.py today` | Build today's digest and print it. Add `--redact` before pasting it anywhere |
| `ledger.py compile` | Build today's digest (saves `DIGEST.md`) |
| `ledger.py compile --date yesterday` | Another day (`yesterday` or `YYYY-MM-DD`) |
| `ledger.py today --open` | Today's digest as a web page (`--html` saves it without opening) |
| `ledger.py standup` | Yesterday / Today / Blockers, ready to paste. Options: `--project`, `--agent`, `--redact`, `--date` |
| `ledger.py client [PROJECT CLIENT]` | Link a project to a client (no arguments: list links) |
| `ledger.py week` | Report for the last 7 days |
| `ledger.py report --from DATE --to DATE` | Report for any date range. Options: `--client`, `--project`, `--agent`, `--redact`, `--html`, `--open`, `--print`, `--out` |
| `ledger.py status` | Check the setup and see why nothing was logged |
| `ledger.py update` | Refresh installed copies and rules after upgrading |
| `ledger.py mcp-install` | Add the MCP server to Cursor and Codex (prints the Claude Code command) |
| `ledger.py mcp` | Run the MCP server (your agent starts this for you) |
| `ledger.py git-hook install [repo]` | Log commits no agent logged (`uninstall` to remove) |
| `ledger.py recover [--date DATE] [--apply]` | Find Claude Code / Codex sessions nobody logged; `--apply` adds them |
| `ledger.py --version` | Show the version |

## Updating

`init` puts a copy of `ledger.py` in your ledger (`~/agent-ledger/` or a project's `ledger/`), so pulling new code doesn't change those copies. After you upgrade, refresh them in one step:

```bash
pipx upgrade ai-agent-ledger                # if you installed with pipx
agent-ledger update                          # updates every copy it knows about
agent-ledger update path/to/project          # or name a project explicitly
```

Using a clone instead? `git pull`, then `python3 ledger.py update`.

`update` also refreshes the agent rules, the `/digest` command and the Claude Code hook, and keeps your logs and settings. `status` tells you when your copy is out of date, and `ledger.py --version` shows which version you're running.

## Auto-compile at the end of the day (optional)

Add a cron job (`crontab -e`) to build the digest every night at 11 PM:

```bash
0 23 * * * python3 ~/agent-ledger/ledger.py compile                      # global
0 23 * * * cd /path/to/project && python3 ledger/ledger.py compile      # project
```

---

## Troubleshooting: "my agent did work but nothing was logged"

Run this first. It checks the setup and tells you what's wrong:

```bash
python3 ledger/ledger.py status            # project mode
python3 ~/agent-ledger/ledger.py status    # global mode
```

The usual causes:

1. **The session was already open.** Agents read the rules when a session starts. Restart the agent and try again.
2. **That project isn't set up.** Project mode covers one project only. Run `init --project` in each project, or use `init --global` to cover all of them.
3. **The agent skipped it.** It happens now and then. Remind it once: *"log what you just did in the ledger"*. The day's git commits still show up in the digest either way. In Claude Code, the log reminder hook catches this for you; `status` shows whether it's on.

---

## FAQ

**It says "Unknown command" for a command in this README.**
You're running an older copy. Run `agent-ledger update` (after `pipx upgrade ai-agent-ledger`), or `python3 ledger.py update` from your clone after `git pull`.

**Can I change where the global ledger lives?**
Yes. Set `AGENT_LEDGER_HOME` (for example to a synced folder) before running `init --global`.

**Can I use another agent, like Gemini or Copilot?**
Yes. Any agent that reads `AGENTS.md` follows the same rule and logs to its own file.

---

## Related tools

Agent Ledger is deliberately small. If you need more, these are worth a look:
[SpecStory](https://specstory.com) (captures full AI chat history) and
[vibe-log](https://github.com/vibe-log/vibe-log-cli) (session analytics and standups).

## Contributing

Ideas, issues and PRs are welcome. Keep it simple: one file, no dependencies.

Run the tests before opening a PR (standard library only, nothing to install):

```bash
python3 -m unittest discover -s tests -v
```

## License

[MIT](LICENSE) © 2026 Naveed Ali
