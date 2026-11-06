#!/usr/bin/env python3
"""Agent Ledger - one daily log for all your AI coding agents.

Usage:
  python3 ledger.py init                    Set up (asks: global or this project)
  python3 ledger.py init --global           One ledger for all projects, no repo files
  python3 ledger.py init --project [DIR]    Ledger inside a project (default: current folder)
        add --private to keep ledger/ out of git (local only)
  python3 ledger.py today  [--date DATE]    Build the digest and print it
  python3 ledger.py compile [--date DATE]   Build the digest (saves DIGEST.md)
  python3 ledger.py status                  Check the setup / why nothing was logged

DATE is YYYY-MM-DD or 'yesterday'. No dependencies. Python 3.8+.
"""

import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR_NAME = "ledger"
GLOBAL_MARKER = ".agent-ledger-global"
MARK_START = "<!-- agent-ledger:start -->"
MARK_END = "<!-- agent-ledger:end -->"
STATUSES = ("DONE", "PARTIAL", "BLOCKED")

HEADING_RE = re.compile(r"^##\s+(\d{1,2}:\d{2})\s*[·\-|]\s*(.*?)\s*[·\-|]\s*([A-Za-z]+)\s*$")
FIELD_RE = re.compile(r"^-\s*(Task|Files|Notes|Follow-up|Repo)\s*:\s*(.*)$", re.IGNORECASE)


def global_home() -> Path:
    return Path(os.environ.get("AGENT_LEDGER_HOME", Path.home() / "agent-ledger")).expanduser()


# ---------------------------------------------------------------- rules text

def agent_rules(log_dir: str, script: str, with_repo: bool) -> str:
    repo_line = "\n    - Repo: <absolute path of the git repo you worked in>" if with_repo else ""
    return f"""{MARK_START}
## Agent Ledger (work logging)

After you finish any task, add an entry to the END of:

    {log_dir}/<YYYY-MM-DD>/<agent>.md

- `<YYYY-MM-DD>` is today's local date (run `date +%F` if unsure).
- `<agent>` is your name in lowercase: `claude`, `codex`, `cursor`, `gemini`, ...
- Create the folder and file if they don't exist.
- Only ever write to YOUR file. Never edit another agent's file or DIGEST.md.

Use exactly this format:

    ## HH:MM · <project> · DONE | PARTIAL | BLOCKED
    - Task: <one line: what was done>
    - Files: <main files touched>{repo_line}
    - Notes: <optional, one line>
    - Follow-up: <optional, what's left>

Keep it short: outcomes, not a play-by-play.

When the user asks for a digest / daily summary / "what did we do today":
1. Run `python3 {script} compile`
2. Read `{log_dir}/<today>/DIGEST.md` and give the user a short summary of it.
{MARK_END}
"""


def digest_command(script: str) -> str:
    return f"""---
description: Compile today's Agent Ledger digest and summarize it
---
1. Run `python3 {script} compile $ARGUMENTS`
2. Read the DIGEST.md it created.
3. Reply with a short summary: what got done, what's blocked, and open follow-ups.
"""


def add_rules(path: Path, rules: str) -> str:
    """Add (or refresh) the Agent Ledger block in an instructions file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MARK_START in text and MARK_END in text:
            before = text.split(MARK_START)[0]
            after = text.split(MARK_END, 1)[1]
            path.write_text(before + rules.strip() + after, encoding="utf-8")
            return "updated"
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + rules, encoding="utf-8")
        return "appended"
    path.write_text(rules, encoding="utf-8")
    return "created"


def copy_self(target: Path) -> None:
    if Path(__file__).resolve() != target.resolve():
        shutil.copy2(__file__, target)


def short(path: Path) -> str:
    """Show paths under the home folder as ~/..."""
    try:
        return "~/" + str(path.resolve().relative_to(Path.home().resolve()))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- init

def init_global() -> None:
    home = global_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / GLOBAL_MARKER).write_text("Agent Ledger global home\n", encoding="utf-8")
    copy_self(home / "ledger.py")

    log_dir, script = short(home), short(home / "ledger.py")
    rules = agent_rules(log_dir, script, with_repo=True)

    print(f"Agent Ledger set up in GLOBAL mode: {log_dir}\n")
    print(f"  {script:<34} copied")
    for f in (Path.home() / ".claude" / "CLAUDE.md", Path.home() / ".codex" / "AGENTS.md"):
        print(f"  {short(f):<34} {add_rules(f, rules)}")
    cmd = Path.home() / ".claude" / "commands" / "digest.md"
    cmd.parent.mkdir(parents=True, exist_ok=True)
    cmd.write_text(digest_command(script), encoding="utf-8")
    print(f"  {short(cmd):<34} created (/digest in Claude Code)")

    cursor_rule = home / "CURSOR_RULE.md"
    cursor_rule.write_text(rules, encoding="utf-8")
    print(f"\nCursor: open Settings → Rules → User Rules and paste the contents of")
    print(f"  {short(cursor_rule)}")
    print(f"\nNo files were added to any project. Next:")
    print(f"  1. Restart any open agent sessions (agents read the rules when a session starts)")
    print(f"  2. Give an agent a task, then run:  python3 {script} today")
    print(f"  Something not logging?  python3 {script} status")


def init_project(project: Path, private: bool) -> None:
    project = project.resolve()
    if not project.is_dir():
        sys.exit(f"Not a folder: {project}")
    ledger = project / PROJECT_DIR_NAME
    ledger.mkdir(exist_ok=True)
    copy_self(ledger / "ledger.py")

    rules = agent_rules(PROJECT_DIR_NAME, f"{PROJECT_DIR_NAME}/ledger.py", with_repo=False)
    print(f"Agent Ledger set up in PROJECT mode: {project}\n")
    print(f"  {'ledger/ledger.py':<28} copied")
    hide = [f"/{PROJECT_DIR_NAME}/", "/.claude/commands/digest.md"]
    tracked_edits = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        result = add_rules(project / name, rules)
        print(f"  {name:<28} {result}")
        if result == "created" or not is_tracked(project, name):
            hide.append(f"/{name}")
        else:
            tracked_edits.append(name)
    cmd = project / ".claude" / "commands" / "digest.md"
    cmd.parent.mkdir(parents=True, exist_ok=True)
    cmd.write_text(digest_command(f"{PROJECT_DIR_NAME}/ledger.py"), encoding="utf-8")
    print(f"  {'.claude/commands/digest.md':<28} created (/digest in Claude Code)")

    if private:
        if (project / ".git").is_dir():
            add_git_exclude(project, hide)
            print(f"  {'.git/info/exclude':<28} Agent Ledger files hidden from git (local only)")
            for name in tracked_edits:
                print(f"\n  Note: {name} is already tracked by git, so the added rule will show")
                print(f"  in `git diff`. To keep repos fully clean, use:  init --global")
        else:
            print("  (not a git repo, --private skipped)")

    print("\nDone. Next:")
    print("  1. Restart any open agent sessions (agents read the rules when a session starts)")
    print("  2. Give an agent a task, then run:  python3 ledger/ledger.py today")
    print("  Something not logging?  python3 ledger/ledger.py status")


def is_tracked(project: Path, name: str) -> bool:
    try:
        out = subprocess.run(["git", "ls-files", "--error-unmatch", name], cwd=project,
                             capture_output=True, text=True, timeout=10)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def add_git_exclude(project: Path, patterns) -> None:
    exclude = project / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    existing = set(text.split())
    new = [p for p in patterns if p not in existing]
    if new:
        if text and not text.endswith("\n"):
            text += "\n"
        exclude.write_text(text + "\n".join(new) + "\n", encoding="utf-8")


def ask_mode() -> str:
    if not sys.stdin.isatty():
        sys.exit("Choose a mode: init --global  or  init --project [DIR]")
    print("Where should Agent Ledger keep your logs?\n")
    print("  1) Global   one ledger for ALL projects, nothing added to your repos")
    print("              (best for freelancers and client work)")
    print("  2) Project  a ledger/ folder inside this project")
    print("              (best for teams who want shared logs in the repo)\n")
    choice = input("Choose 1 or 2 [1]: ").strip() or "1"
    if choice not in ("1", "2"):
        sys.exit("Please choose 1 or 2.")
    return "global" if choice == "1" else "project"


def ask_yes(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")


def cmd_init(args) -> None:
    flags = [a for a in args if a.startswith("--")]
    paths = [a for a in args if not a.startswith("--")]
    private = "--private" in flags

    if "--global" in flags:
        mode = "global"
    elif "--project" in flags or paths:   # `init DIR` still means project mode
        mode = "project"
    else:
        mode = ask_mode()

    if mode == "global":
        init_global()
    else:
        if "--project" not in flags and not paths and not private:
            private = ask_yes("Keep the ledger/ folder out of git (local only)?")
        init_project(Path(paths[0]) if paths else Path.cwd(), private)


# ---------------------------------------------------------------- compile

def locate():
    """Work out the mode. Returns (mode, logs_dir, project_root_or_None)."""
    here = Path(__file__).resolve().parent
    if (here / GLOBAL_MARKER).exists():
        return "global", here, None
    if here.name == PROJECT_DIR_NAME:
        return "project", here, here.parent
    if (Path.cwd() / PROJECT_DIR_NAME).is_dir():
        return "project", Path.cwd() / PROJECT_DIR_NAME, Path.cwd()
    if (global_home() / GLOBAL_MARKER).exists():
        return "global", global_home(), None
    sys.exit("No ledger found. Run:  python3 ledger.py init")


def parse_log(path: Path):
    """Read one agent's log file into a list of entries."""
    agent = path.stem
    entries, current = [], None
    blank = {"task": "", "files": "", "notes": "", "follow-up": "", "repo": ""}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = HEADING_RE.match(line)
        if m:
            status = m.group(3).upper()
            current = {"agent": agent, "time": m.group(1).zfill(5),
                       "project": m.group(2).strip() or "-",
                       "status": status if status in STATUSES else "DONE", **blank}
            entries.append(current)
            continue
        if line.startswith("## "):  # non-standard heading: keep it anyway
            current = {"agent": agent, "time": "--:--", "project": "-", "status": "DONE",
                       **blank, "task": line[3:].strip()}
            entries.append(current)
            continue
        f = FIELD_RE.match(line)
        if f and current is not None:
            current[f.group(1).lower()] = f.group(2).strip()
    for e in entries:
        if not e["task"]:
            e["task"] = e["notes"] or "(no description)"
    return entries


def git_commits(repo: Path, day: str):
    try:
        out = subprocess.run(
            ["git", "log", "--all", f"--since={day} 00:00", f"--until={day} 23:59:59",
             "--pretty=format:%h %ad %s", "--date=format:%H:%M"],
            cwd=repo, capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return []
        return [l for l in out.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def build_digest(mode: str, logs: Path, project, day: str) -> str:
    day_dir = logs / day
    files = sorted(p for p in day_dir.glob("*.md") if p.name != "DIGEST.md") if day_dir.is_dir() else []
    entries = sorted((e for f in files for e in parse_log(f)), key=lambda e: e["time"])

    # Commits: the project repo, or every repo mentioned in today's global entries.
    commits = []
    if mode == "project":
        commits = git_commits(project, day)
    else:
        seen = set()
        for e in entries:
            repo = Path(e["repo"]).expanduser() if e["repo"] else None
            if repo and repo.is_dir() and repo.resolve() not in seen:
                seen.add(repo.resolve())
                commits += [f"{c.split(' ', 1)[0]} [{repo.name}] {c.split(' ', 1)[1]}"
                            for c in git_commits(repo, day) if " " in c]

    count = {s: sum(e["status"] == s for e in entries) for s in STATUSES}
    agents = ", ".join(f.stem for f in files) or "none"
    projects = sorted({e["project"] for e in entries if e["project"] != "-"})

    def line(e):
        touched = f"  \n  `{e['files']}`" if e["files"] else ""
        return f"- **{e['time']}** · {e['project']} · _{e['agent']}_ — {e['task']}{touched}"

    n = len(commits)
    out = [f"# Daily Digest — {day}", ""]
    out.append(f"**{len(entries)} tasks** · ✅ {count['DONE']} done · 🟡 {count['PARTIAL']} partial "
               f"· 🔴 {count['BLOCKED']} blocked · {n} commit{'' if n == 1 else 's'}  ")
    out.append(f"Agents: {agents}" + (f"  \nProjects: {', '.join(projects)}" if projects else ""))
    out.append("")

    if not entries and commits:
        out.append("> ⚠️ Commits found but no agent logged anything today. "
                   "Run `ledger.py status` to see why.")
        out.append("")

    out.append("## ✅ Done")
    out += [line(e) for e in entries if e["status"] == "DONE"] or ["_Nothing logged._"]
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

    out.append(f"_Generated by Agent Ledger ({mode} mode) at {dt.datetime.now():%Y-%m-%d %H:%M}_")
    return "\n".join(out) + "\n"


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
    mode, logs, project = locate()
    day = parse_date(args)
    day_dir = logs / day
    day_dir.mkdir(parents=True, exist_ok=True)
    digest = build_digest(mode, logs, project, day)
    (day_dir / "DIGEST.md").write_text(digest, encoding="utf-8")
    print(digest if show else f"Wrote {day_dir / 'DIGEST.md'}")


# ---------------------------------------------------------------- status

def has_rules(path: Path) -> bool:
    return path.exists() and MARK_START in path.read_text(encoding="utf-8", errors="ignore")


def cmd_status(args) -> None:
    mode, logs, project = locate()
    day = parse_date(args)
    ok, warn = "✅", "⚠️ "
    problems = []

    print(f"Agent Ledger status — {day}\n")
    print(f"  Mode:   {mode}")
    print(f"  Logs:   {short(logs / day)}/")

    # 1. Are the rules where the agents will read them?
    if mode == "project":
        checks = [("Codex / Cursor", project / "AGENTS.md"), ("Claude Code", project / "CLAUDE.md")]
    else:
        checks = [("Claude Code", Path.home() / ".claude" / "CLAUDE.md"),
                  ("Codex", Path.home() / ".codex" / "AGENTS.md")]
    print("\n  Rules")
    for agent, path in checks:
        found = has_rules(path)
        print(f"    {ok if found else warn} {agent:<15} {short(path)}")
        if not found:
            problems.append(f"Rule missing for {agent}. Run `init` again.")
    if mode == "global":
        print(f"    ·  {'Cursor':<15} paste {short(logs / 'CURSOR_RULE.md')} into Settings → Rules → User Rules")

    # 2. Did anyone log today?
    day_dir = logs / day
    files = sorted(p for p in day_dir.glob("*.md") if p.name != "DIGEST.md") if day_dir.is_dir() else []
    entries = [e for f in files for e in parse_log(f)]
    print("\n  Today")
    for f in files:
        n = len(parse_log(f))
        print(f"    {ok} {f.stem:<15} {n} entr{'y' if n == 1 else 'ies'}")
    if not files:
        print(f"    {warn} no agent has logged yet")

    if mode == "project":
        commits = git_commits(project, day)
        print(f"    ·  {len(commits)} commit{'' if len(commits) == 1 else 's'} in this repo")
        if commits and not entries:
            print(f"    {warn} work was committed today, but no agent logged it")

    if mode == "global" and (Path.cwd() / ".git").is_dir() and has_rules(Path.cwd() / "AGENTS.md"):
        print(f"\n    {warn} This repo also has a project-mode rule in AGENTS.md; agents here")
        print(f"       will log to ./ledger/ instead of {short(logs)}.")

    if not entries:
        problems += [
            "Agents read the rules when a session STARTS. Restart sessions that were open during `init`.",
            "Check you're in the right place: each project needs its own `init --project`, "
            "or use `init --global` to cover every project.",
            "Remind the agent once: \"log what you just did in the ledger\".",
        ]

    if problems:
        print("\n  If nothing is being logged:")
        for i, p in enumerate(dict.fromkeys(problems), 1):
            print(f"    {i}. {p}")
    else:
        print("\n  All good.")


# ---------------------------------------------------------------- main

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    if cmd == "init":
        cmd_init(rest)
    elif cmd == "compile":
        cmd_compile(rest)
    elif cmd == "today":
        cmd_compile(rest, show=True)
    elif cmd == "status":
        cmd_status(rest)
    else:
        sys.exit(f"Unknown command: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
