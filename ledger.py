#!/usr/bin/env python3
"""Agent Ledger - one daily log for all your AI coding agents.

Usage:
  python3 ledger.py init [PROJECT_DIR]     Set up Agent Ledger in a project
  python3 ledger.py compile [--date DATE]  Build ledger/DATE/DIGEST.md (default: today)
  python3 ledger.py today                  Print today's digest to the terminal

No dependencies. Python 3.8+.
"""

import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

LEDGER_DIR = "ledger"
MARK_START = "<!-- agent-ledger:start -->"
MARK_END = "<!-- agent-ledger:end -->"
STATUSES = ("DONE", "PARTIAL", "BLOCKED")

AGENT_RULES = f"""{MARK_START}
## Agent Ledger (work logging)

After you finish any task, add an entry to the END of:

    ledger/<YYYY-MM-DD>/<agent>.md

- `<YYYY-MM-DD>` is today's local date (run `date +%F` if unsure).
- `<agent>` is your name in lowercase: `claude`, `codex`, `cursor`, `gemini`, ...
- Create the folder and file if they don't exist.
- Only ever write to YOUR file. Never edit another agent's file or DIGEST.md.

Use exactly this format:

    ## HH:MM · <project> · DONE | PARTIAL | BLOCKED
    - Task: <one line: what was done>
    - Files: <main files touched>
    - Notes: <optional, one line>
    - Follow-up: <optional, what's left>

Keep it short: outcomes, not a play-by-play.

When the user asks for a digest / daily summary / "what did we do today":
1. Run `python3 ledger/ledger.py compile`
2. Read `ledger/<today>/DIGEST.md` and give the user a short summary of it.
{MARK_END}
"""

CLAUDE_COMMAND = """---
description: Compile today's Agent Ledger digest and summarize it
---
1. Run `python3 ledger/ledger.py compile $ARGUMENTS`
2. Read the DIGEST.md it created.
3. Reply with a short summary: what got done, what's blocked, and open follow-ups.
"""

HEADING_RE = re.compile(r"^##\s+(\d{1,2}:\d{2})\s*[·\-|]\s*(.*?)\s*[·\-|]\s*([A-Za-z]+)\s*$")
FIELD_RE = re.compile(r"^-\s*(Task|Files|Notes|Follow-up)\s*:\s*(.*)$", re.IGNORECASE)


# ---------------------------------------------------------------- init

def add_rules(path: Path) -> str:
    """Add (or refresh) the Agent Ledger block in an instructions file."""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MARK_START in text and MARK_END in text:
            before = text.split(MARK_START)[0]
            after = text.split(MARK_END, 1)[1]
            path.write_text(before + AGENT_RULES.strip() + after, encoding="utf-8")
            return "updated"
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + AGENT_RULES, encoding="utf-8")
        return "appended"
    path.write_text(AGENT_RULES, encoding="utf-8")
    return "created"


def cmd_init(project: Path) -> None:
    project = project.resolve()
    if not project.is_dir():
        sys.exit(f"Not a folder: {project}")

    ledger = project / LEDGER_DIR
    ledger.mkdir(exist_ok=True)

    # Copy this script into the project so every agent can run it.
    target = ledger / "ledger.py"
    if Path(__file__).resolve() != target.resolve():
        shutil.copy2(__file__, target)

    print(f"Agent Ledger set up in {project}\n")
    print(f"  ledger/ledger.py     copied")
    for name in ("AGENTS.md", "CLAUDE.md"):
        print(f"  {name:<20} {add_rules(project / name)}")

    cmd_dir = project / ".claude" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / "digest.md").write_text(CLAUDE_COMMAND, encoding="utf-8")
    print(f"  .claude/commands/digest.md  created (/digest in Claude Code)")

    print("\nDone. Give an agent a task, then run:  python3 ledger/ledger.py today")


# ---------------------------------------------------------------- compile

def parse_log(path: Path):
    """Read one agent's log file into a list of entries."""
    agent = path.stem
    entries, current = [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = HEADING_RE.match(line)
        if m:
            status = m.group(3).upper()
            current = {
                "agent": agent,
                "time": m.group(1).zfill(5),
                "project": m.group(2).strip() or "-",
                "status": status if status in STATUSES else "DONE",
                "task": "", "files": "", "notes": "", "follow-up": "",
            }
            entries.append(current)
            continue
        if line.startswith("## "):  # heading in a non-standard format: keep it anyway
            current = {"agent": agent, "time": "--:--", "project": "-", "status": "DONE",
                       "task": line[3:].strip(), "files": "", "notes": "", "follow-up": ""}
            entries.append(current)
            continue
        f = FIELD_RE.match(line)
        if f and current is not None:
            current[f.group(1).lower()] = f.group(2).strip()
    for e in entries:
        if not e["task"]:
            e["task"] = e["notes"] or "(no description)"
    return entries


def git_commits(project: Path, day: str):
    try:
        out = subprocess.run(
            ["git", "log", "--all", f"--since={day} 00:00", f"--until={day} 23:59:59",
             "--pretty=format:%h %ad %s", "--date=format:%H:%M"],
            cwd=project, capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return []
        return [l for l in out.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def build_digest(project: Path, day: str) -> str:
    day_dir = project / LEDGER_DIR / day
    files = sorted(p for p in day_dir.glob("*.md") if p.name != "DIGEST.md") if day_dir.is_dir() else []
    entries = sorted((e for f in files for e in parse_log(f)), key=lambda e: e["time"])
    commits = git_commits(project, day)

    count = {s: sum(e["status"] == s for e in entries) for s in STATUSES}
    agents = ", ".join(f.stem for f in files) or "none"

    def line(e):
        files = f"  \n  `{e['files']}`" if e["files"] else ""
        return f"- **{e['time']}** · {e['project']} · _{e['agent']}_ — {e['task']}{files}"

    out = [f"# Daily Digest — {day}", ""]
    out.append(f"**{len(entries)} tasks** · ✅ {count['DONE']} done · 🟡 {count['PARTIAL']} partial "
               f"· 🔴 {count['BLOCKED']} blocked · {len(commits)} commit{'' if len(commits) == 1 else 's'}  ")
    out.append(f"Agents: {agents}")
    out.append("")

    out.append("## ✅ Done")
    done = [e for e in entries if e["status"] == "DONE"]
    out += [line(e) for e in done] or ["_Nothing logged._"]
    out.append("")

    open_items = [e for e in entries if e["status"] != "DONE"]
    if open_items:
        out.append("## 🟡 Partial / 🔴 Blocked")
        out += [line(e).replace("- **", f"- {'🔴' if e['status'] == 'BLOCKED' else '🟡'} **", 1)
                for e in open_items]
        out.append("")

    follow = [e for e in entries if e["follow-up"]]
    if follow:
        out.append("## 📌 Follow-ups")
        out += [f"- [ ] {e['follow-up']} _({e['project']}, {e['agent']})_" for e in follow]
        out.append("")

    if commits:
        out.append("## 🔀 Commits")
        out += [f"- `{c.split(' ', 1)[0]}` {c.split(' ', 1)[1] if ' ' in c else ''}" for c in commits]
        out.append("")

    if files:
        out.append("## 📂 Raw logs")
        out += [f"- [{f.stem}]({f.name})" for f in files]
        out.append("")

    out.append(f"_Generated by Agent Ledger at {dt.datetime.now():%Y-%m-%d %H:%M}_")
    return "\n".join(out) + "\n"


def find_project() -> Path:
    """The project is the folder that contains ledger/ (works from ledger/ too)."""
    here = Path(__file__).resolve().parent
    if here.name == LEDGER_DIR:
        return here.parent
    return Path.cwd()


def parse_date(args) -> str:
    if "--date" in args:
        i = args.index("--date")
        if i + 1 >= len(args):
            sys.exit("--date needs a value like 2026-11-05")
        value = args[i + 1]
        if value == "yesterday":
            return str(dt.date.today() - dt.timedelta(days=1))
        try:
            return str(dt.date.fromisoformat(value))
        except ValueError:
            sys.exit(f"Bad date: {value} (use YYYY-MM-DD or 'yesterday')")
    return str(dt.date.today())


def cmd_compile(args, show=False) -> None:
    project = find_project()
    day = parse_date(args)
    day_dir = project / LEDGER_DIR / day
    day_dir.mkdir(parents=True, exist_ok=True)
    digest = build_digest(project, day)
    (day_dir / "DIGEST.md").write_text(digest, encoding="utf-8")
    if show:
        print(digest)
    else:
        print(f"Wrote {day_dir / 'DIGEST.md'}")


# ---------------------------------------------------------------- main

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "init":
        cmd_init(Path(args[1]) if len(args) > 1 else Path.cwd())
    elif cmd == "compile":
        cmd_compile(args[1:])
    elif cmd == "today":
        cmd_compile(args[1:], show=True)
    else:
        sys.exit(f"Unknown command: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
