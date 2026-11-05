# 📒 Agent Ledger

**One daily log for all your AI coding agents.**

You ask Claude, Codex and Cursor to do the work, and by evening you can't remember what got done. Agent Ledger fixes that: each agent writes a short note when it finishes a task, and one command turns those notes into a clean daily digest.

- ✅ Works with **Claude Code, Codex, Cursor**, and any agent that reads `AGENTS.md`
- 📄 Plain Markdown files in your repo. No server, no account, no tracking
- 🐍 One Python file, zero dependencies

---

## How it works

```
your-project/
  AGENTS.md            ← tells every agent to log its work
  CLAUDE.md            ← same rule for Claude Code
  ledger/
    ledger.py
    2026-11-05/
      claude.md        ← each agent writes only its own file
      codex.md
      cursor.md
      DIGEST.md        ← compiled summary of the day
```

1. **Agents log.** After each task, an agent adds a short entry to `ledger/<today>/<agent>.md`.
2. **You compile.** Run one command (or ask any agent) and get `DIGEST.md`: what's done, what's blocked, follow-ups, and today's git commits.

---

## Quick start

**1. Get it**

```bash
git clone https://github.com/naveedali/Agent-Ledger.git
```

**2. Set it up in your project**

```bash
python3 Agent-Ledger/ledger.py init path/to/your-project
```

This adds the logging rules to `AGENTS.md` and `CLAUDE.md` (your existing content is kept), creates the `ledger/` folder, and adds a `/digest` command for Claude Code. Running it again is safe.

**3. Work as usual.** Give your agents tasks. They log as they go.

**4. See your day**

```bash
python3 ledger/ledger.py today
```

Or just ask any agent: *"give me today's digest"*. In Claude Code, type `/digest`.

---

## What an entry looks like

Agents write this. You don't have to.

```markdown
## 14:32 · Atfal Compass · DONE
- Task: Add onboarding screen with skip flow
- Files: OnboardingScreen.kt, NavGraph.kt
- Follow-up: Needs analytics event
```

Status is `DONE`, `PARTIAL` or `BLOCKED`.

## What the digest looks like

```markdown
# Daily Digest — 2026-11-05

**3 tasks** · ✅ 1 done · 🟡 1 partial · 🔴 1 blocked · 1 commit
Agents: claude, codex

## ✅ Done
- **14:32** · Atfal Compass · _codex_ — Add onboarding screen with skip flow

## 🟡 Partial / 🔴 Blocked
- 🟡 **09:10** · Agent Ledger · _claude_ — Write README
- 🔴 **16:00** · Foodie · _claude_ — Fix payment crash

## 📌 Follow-ups
- [ ] Needs analytics event _(Atfal Compass, codex)_

## 🔀 Commits
- `610cfdf` 18:52 feat: onboarding screen
```

---

## Commands

| Command | What it does |
|---|---|
| `python3 ledger.py init [folder]` | Set up Agent Ledger in a project |
| `python3 ledger/ledger.py today` | Build today's digest and print it |
| `python3 ledger/ledger.py compile` | Build today's digest (saves `DIGEST.md`) |
| `python3 ledger/ledger.py compile --date yesterday` | Digest for another day (`yesterday` or `YYYY-MM-DD`) |

## Auto-compile at the end of the day (optional)

Add a cron job (`crontab -e`) to build the digest every night at 11 PM:

```bash
0 23 * * * cd /path/to/your-project && python3 ledger/ledger.py compile
```

---

## FAQ

**An agent forgot to log. What now?**
It happens. The digest also lists the day's git commits, so work still shows up. You can also remind the agent: *"log what you just did in the ledger"*.

**Should I commit the `ledger/` folder?**
Your choice. Commit it to keep a shared history, or add `ledger/20*/` to `.gitignore` to keep it private.

**Can I use another agent, like Gemini or Copilot?**
Yes. Any agent that reads `AGENTS.md` follows the same rule and logs to its own file.

---

## Related tools

Agent Ledger is deliberately small. If you need more, these are worth a look:
[SpecStory](https://specstory.com) (captures full AI chat history) and
[vibe-log](https://github.com/vibe-log/vibe-log-cli) (session analytics and standups).

## Contributing

Ideas, issues and PRs are welcome. Keep it simple: one file, no dependencies.

## License

[MIT](LICENSE) © 2026 Naveed Ali
