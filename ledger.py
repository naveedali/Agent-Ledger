#!/usr/bin/env python3
"""Agent Ledger - one daily log for all your AI coding agents.

Usage:
  python3 ledger.py init                    Set up (asks: global or this project)
  python3 ledger.py init --global           One ledger for all projects, no repo files
  python3 ledger.py init --project [DIR]    Ledger inside a project (default: current folder)
        add --private to keep ledger/ out of git (local only)
        add --no-hook to skip the Claude Code log reminder
  python3 ledger.py today  [--date DATE]    Build the digest and print it
  python3 ledger.py compile [--date DATE]   Build the digest (saves DIGEST.md)
        add --html to also save DIGEST.html, --open to open it in your browser
  python3 ledger.py status                  Check the setup / why nothing was logged
  python3 ledger.py log --agent NAME --task "..." [--files ...] [--status PARTIAL|BLOCKED]
                                            Add an entry to today's log (used by agents)
  python3 ledger.py report [--from DATE] [--to DATE] [--project NAME] [--agent NAME] [--redact]
                                            Work report for a date range (default: last 7 days)
  python3 ledger.py week [--project NAME] [--redact]
                                            Report for the last 7 days
        reports also take --html (formatted page) and --open (open it in your browser)

  python3 ledger.py update                  Refresh installed copies after you upgrade
  python3 ledger.py --version               Show the version

DATE is YYYY-MM-DD, 'today' or 'yesterday'. No dependencies. Python 3.8+.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

__version__ = "0.3.0"

PROJECT_DIR_NAME = "ledger"
GLOBAL_MARKER = ".agent-ledger-global"
SOURCE_MARKER = ".agent-ledger-source"   # where an installed copy was copied from
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

After you finish any task, log it with ONE command:

    python3 {script} log --agent <agent> --task "<one line: what was done>" --files "<main files>"

- `<agent>` is your name in lowercase: `claude`, `codex`, `cursor`, `gemini`, ...
- Optional: `--status PARTIAL` or `--status BLOCKED`, `--follow-up "<what's left>"`,
  `--notes "<one line>"`, `--project "<name>"` (defaults to the git repo name).
- Keep it short: outcomes, not a play-by-play.

If you can't run commands, add the entry by hand to the END of
`{log_dir}/<YYYY-MM-DD>/<agent>.md` (today's local date; create it if missing):

    ## HH:MM · <project> · DONE | PARTIAL | BLOCKED
    - Task: <one line: what was done>
    - Files: <main files touched>{repo_line}
    - Notes: <optional, one line>
    - Follow-up: <optional, what's left>

Only ever write to YOUR file. Never edit another agent's file or DIGEST.md.

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
    """Install this script at target, remember where it came from, and register the install."""
    me = Path(__file__).resolve()
    if me != target.resolve():
        shutil.copy2(me, target)
        (target.parent / SOURCE_MARKER).write_text(str(me) + "\n", encoding="utf-8")
    register_install(target)


def registry_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-ledger" / "installs.json"


def registered_installs():
    try:
        return [Path(p) for p in json.loads(registry_file().read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def register_install(script: Path) -> None:
    try:
        paths = {str(p) for p in registered_installs() if p.exists()}
        paths.add(str(script.resolve()))
        registry_file().parent.mkdir(parents=True, exist_ok=True)
        registry_file().write_text(json.dumps(sorted(paths), indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass                                    # tracking installs is a convenience, never a blocker


def version_of(script: Path) -> str:
    try:
        m = re.search(r'^__version__ = "([^"]+)"', script.read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else "0.0.0"
    except OSError:
        return "0.0.0"


def vtuple(v: str):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.+-]", v)[:3])


def recorded_source(install_dir: Path):
    try:
        src = Path((install_dir / SOURCE_MARKER).read_text(encoding="utf-8").strip())
        return src if src.is_file() else None
    except OSError:
        return None


def check_args(args, flags=(), value_flags=(), positional=0, cmd=""):
    """Fail clearly on options this version doesn't know, instead of ignoring them."""
    i, seen = 0, 0
    while i < len(args):
        a = args[i]
        if a in value_flags:
            if i + 1 >= len(args):
                sys.exit(f"{a} needs a value")
            i += 2
            continue
        if a.startswith("-") and a not in flags:
            sys.exit(f"Unknown option for `{cmd}`: {a}\nRun `ledger.py --help` to see the options. "
                     "(If it's a newer option, your copy may be out of date: run `ledger.py update`.)")
        if not a.startswith("-"):
            seen += 1
            if seen > positional:
                sys.exit(f"Unexpected argument for `{cmd}`: {a}\nRun `ledger.py --help` to see the options.")
        i += 1


def short(path: Path) -> str:
    """Show paths under the home folder as ~/..."""
    try:
        return "~/" + str(path.resolve().relative_to(Path.home().resolve()))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- Claude Code hook

HOOK_MARK = "hook claude"


def install_claude_hook(settings: Path, command: str) -> str:
    """Add (or refresh) the Agent Ledger Stop hook in a Claude Code settings file."""
    data = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8") or "{}")
        except ValueError:
            return "skipped (settings file isn't valid JSON, add the hook by hand)"
    if not isinstance(data, dict) or not isinstance(data.setdefault("hooks", {}), dict) \
            or not isinstance(data["hooks"].setdefault("Stop", []), list):
        return "skipped (unexpected settings format, add the hook by hand)"
    status = "added"
    for group in data["hooks"]["Stop"]:
        for h in (group.get("hooks", []) if isinstance(group, dict) else []):
            if isinstance(h, dict) and "ledger.py" in str(h.get("command", "")) \
                    and HOOK_MARK in str(h.get("command", "")):
                h["command"], status = command, "updated"
    if status == "added":
        data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": command}]})
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return status


def has_claude_hook(*settings_files: Path) -> bool:
    for f in settings_files:
        try:
            if f.exists() and "ledger.py" in f.read_text(encoding="utf-8") and \
                    HOOK_MARK in f.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
    return False


# ---------------------------------------------------------------- init

def init_global(hook: bool = True) -> None:
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
    if hook:
        settings = Path.home() / ".claude" / "settings.json"
        command = f'python3 "{(home / "ledger.py").resolve()}" {HOOK_MARK}'
        print(f"  {short(settings):<34} log reminder hook {install_claude_hook(settings, command)}")

    cursor_rule = home / "CURSOR_RULE.md"
    cursor_rule.write_text(rules, encoding="utf-8")
    print(f"\nCursor: open Settings → Rules → User Rules and paste the contents of")
    print(f"  {short(cursor_rule)}")
    print(f"\nNo files were added to any project. Next:")
    print(f"  1. Restart any open agent sessions (agents read the rules when a session starts)")
    print(f"  2. Give an agent a task, then run:  python3 {script} today")
    print(f"  Something not logging?  python3 {script} status")


def init_project(project: Path, private: bool, hook: bool = True) -> None:
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
    if hook:
        # Private setups use settings.local.json, which Claude Code keeps out of git.
        name = "settings.local.json" if private else "settings.json"
        command = f'python3 "$CLAUDE_PROJECT_DIR/{PROJECT_DIR_NAME}/ledger.py" {HOOK_MARK}'
        result = install_claude_hook(project / ".claude" / name, command)
        print(f"  {'.claude/' + name:<28} log reminder hook {result}")
        if private:
            hide.append(f"/.claude/{name}")

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
    check_args(args, flags=("--global", "--project", "--private", "--no-hook"), positional=1, cmd="init")
    flags = [a for a in args if a.startswith("--")]
    paths = [a for a in args if not a.startswith("--")]
    private = "--private" in flags
    hook = "--no-hook" not in flags

    if "--global" in flags:
        mode = "global"
    elif "--project" in flags or paths:   # `init DIR` still means project mode
        mode = "project"
    else:
        mode = ask_mode()

    if mode == "global":
        init_global(hook)
    else:
        if "--project" not in flags and not paths and not private:
            private = ask_yes("Keep the ledger/ folder out of git (local only)?")
        init_project(Path(paths[0]) if paths else Path.cwd(), private, hook)


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


def git_commits(repo: Path, since: str, until: str = None):
    """Commits in a repo between two days (inclusive), as dicts."""
    until = until or since
    try:
        out = subprocess.run(
            ["git", "log", "--all", f"--since={since} 00:00", f"--until={until} 23:59:59",
             "--pretty=format:%h\t%ad\t%s", "--date=format:%Y-%m-%d %H:%M"],
            cwd=repo, capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return []
    except (OSError, subprocess.SubprocessError):
        return []
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            day, _, time = parts[1].partition(" ")
            commits.append({"hash": parts[0], "day": day, "time": time, "msg": parts[2],
                            "repo": Path(repo).name})
    return sorted(commits, key=lambda c: (c["day"], c["time"]))


def commits_for(mode: str, project, entries, since: str, until: str):
    """Project mode: the project's repo. Global mode: every repo named in the entries."""
    if mode == "project":
        return git_commits(project, since, until)
    commits, seen = [], set()
    for e in entries:
        repo = Path(e["repo"]).expanduser() if e.get("repo") else None
        if repo and repo.is_dir() and repo.resolve() not in seen:
            seen.add(repo.resolve())
            commits += git_commits(repo, since, until)
    return sorted(commits, key=lambda c: (c["day"], c["time"]))


def build_digest(mode: str, logs: Path, project, day: str) -> str:
    day_dir = logs / day
    files = sorted(p for p in day_dir.glob("*.md") if p.name != "DIGEST.md") if day_dir.is_dir() else []
    entries = sorted((e for f in files for e in parse_log(f)), key=lambda e: e["time"])

    commits = commits_for(mode, project, entries, day, day)

    count = {s: sum(e["status"] == s for e in entries) for s in STATUSES}
    agents = ", ".join(f.stem for f in files) or "none"
    projects = sorted({e["project"] for e in entries if e["project"] != "-"})

    def line(e):
        touched = f"  \n  `{e['files']}`" if e["files"] else ""
        return f"- **{e['time']}** · {e['project']} · _{e['agent']}_ — {e['task']}{touched}"

    n = len(commits)
    out = [f"# Daily Digest — {day}", ""]
    out.append(f"**{len(entries)} task{'' if len(entries) == 1 else 's'}** · ✅ {count['DONE']} done · 🟡 {count['PARTIAL']} partial "
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
        tag = (lambda c: f"[{c['repo']}] ") if mode == "global" else (lambda c: "")
        out += [f"- `{c['hash']}` {tag(c)}{c['time']} {c['msg']}" for c in commits]
        out.append("")

    if files:
        out.append("## 📂 Raw logs")
        out += [f"- [{f.stem}]({f.name})" for f in files]
        out.append("")

    out.append(f"_Generated by Agent Ledger ({mode} mode) at {dt.datetime.now():%Y-%m-%d %H:%M}_")
    return "\n".join(out) + "\n"


def to_day(value: str) -> str:
    v = value.strip().lower()
    if v == "today":
        return str(dt.date.today())
    if v == "yesterday":
        return str(dt.date.today() - dt.timedelta(days=1))
    try:
        return str(dt.date.fromisoformat(v))
    except ValueError:
        sys.exit(f"Bad date: {value} (use YYYY-MM-DD, 'today' or 'yesterday')")


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
    check_args(args, flags=("--html", "--open", "--redact"), value_flags=("--date",),
               cmd="today" if show else "compile")
    mode, logs, project = locate()
    day = parse_date(args)
    day_dir = logs / day
    day_dir.mkdir(parents=True, exist_ok=True)
    digest = build_digest(mode, logs, project, day)
    (day_dir / "DIGEST.md").write_text(digest, encoding="utf-8")
    print(digest if show else f"Wrote {short(day_dir / 'DIGEST.md')}")
    if "--html" in args or "--open" in args:
        page = day_dir / "DIGEST.html"
        data = report_data(mode, logs, project, day, day, hide="--redact" in args)
        page.write_text(build_html(data, daily=True), encoding="utf-8")
        print(f"{'─' * 60}\nHTML page: {short(page)}" if show else f"Wrote {short(page)}")
        if "--open" in args:
            print("Opening it in your browser…")
            open_file(page)


# ---------------------------------------------------------------- report

SECRET_RES = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),                     # emails
    re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"),                               # API keys
    re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}"),                 # GitHub
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                                     # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                               # AWS
    re.compile(r"\b[A-Za-z0-9_-]{40,}\b"),                                           # long tokens
]
HOME_RE = re.compile(r"(?:/Users|/home)/[^/\s]+")


def redact(text: str) -> str:
    """Hide emails, keys/tokens and home-folder paths before sharing a report."""
    text = HOME_RE.sub("~", text)
    for i, rx in enumerate(SECRET_RES):
        text = rx.sub("[email]" if i == 0 else "[secret]", text)
    return text


def collect(logs: Path, since: str, until: str, project_filter=None, agent_filter=None):
    """All entries between two days (inclusive), oldest first, each tagged with its day."""
    start, end = dt.date.fromisoformat(since), dt.date.fromisoformat(until)
    entries, day = [], start
    while day <= end:
        day_dir = logs / str(day)
        if day_dir.is_dir():
            for f in sorted(day_dir.glob("*.md")):
                if f.name == "DIGEST.md":
                    continue
                for e in parse_log(f):
                    e["day"] = str(day)
                    entries.append(e)
        day += dt.timedelta(days=1)
    if project_filter:
        entries = [e for e in entries if e["project"].lower() == project_filter.lower()]
    if agent_filter:
        entries = [e for e in entries if e["agent"].lower() == agent_filter.lower()]
    return sorted(entries, key=lambda e: (e["day"], e["time"]))


def report_data(mode, logs, project, since, until, project_filter=None, agent_filter=None, hide=False):
    """Everything a report needs, already filtered and (optionally) redacted."""
    entries = collect(logs, since, until, project_filter, agent_filter)
    commits = commits_for(mode, project, entries, since, until)
    if mode == "global" and project_filter:
        repos = {Path(e["repo"]).expanduser().name for e in entries if e.get("repo")}
        commits = [c for c in commits if c["repo"] in repos]
    if agent_filter:
        commits = []                       # commits can't be tied to one agent
    if hide:
        for e in entries:
            for k in ("task", "files", "notes", "follow-up", "project"):
                e[k] = redact(e[k])
        for c in commits:
            c["msg"] = redact(c["msg"])
    return {
        "mode": mode, "since": since, "until": until, "hide": hide,
        "project_filter": project_filter, "agent_filter": agent_filter,
        "entries": entries, "commits": commits,
        "count": {s_: sum(e["status"] == s_ for e in entries) for s_ in STATUSES},
        "projects": sorted({e["project"] for e in entries}, key=str.lower),
        "agents": sorted({e["agent"] for e in entries}),
        "days": sorted({e["day"] for e in entries}),
        "generated": f"{dt.datetime.now():%Y-%m-%d %H:%M}",
    }


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def nice_day(day):
    return dt.date.fromisoformat(day).strftime("%a %d %b %Y")


def build_report(mode, logs, project, since, until, project_filter=None, agent_filter=None, hide=False):
    d = report_data(mode, logs, project, since, until, project_filter, agent_filter, hide)
    entries, commits, count = d["entries"], d["commits"], d["count"]
    icon = {"DONE": "✅", "PARTIAL": "🟡", "BLOCKED": "🔴"}

    title = f"Work Report — {since} → {until}" if since != until else f"Work Report — {since}"
    out = [f"# {title}", ""]
    scope = [f"Project: {project_filter}" if project_filter else "",
             f"Agent: {agent_filter}" if agent_filter else ""]
    if any(scope):
        out += ["_" + " · ".join(x for x in scope if x) + "_", ""]
    out.append(f"**{plural(len(entries), 'task')}** · ✅ {count['DONE']} done · 🟡 {count['PARTIAL']} partial "
               f"· 🔴 {count['BLOCKED']} blocked · {plural(len(commits), 'commit')} "
               f"· {plural(len(d['days']), 'active day')}  ")
    out.append(f"Agents: {', '.join(d['agents']) or 'none'}  ")
    out.append(f"Projects: {', '.join(d['projects']) or 'none'}")
    out.append("")

    if not entries:
        out += ["_Nothing logged in this period._", ""]

    if len(d["projects"]) > 1:
        out += ["## Summary", "", "| Project | Tasks | Done | Partial | Blocked |", "|---|---:|---:|---:|---:|"]
        for p in d["projects"]:
            pe = [e for e in entries if e["project"] == p]
            out.append(f"| {p} | {len(pe)} | " + " | ".join(
                str(sum(e["status"] == s_ for e in pe)) for s_ in STATUSES) + " |")
        out.append("")

    for p in d["projects"]:
        out += [f"## {p}", ""]
        pe = [e for e in entries if e["project"] == p]
        for day in sorted({e["day"] for e in pe}):
            out += [f"### {nice_day(day)}", ""]
            for e in (e for e in pe if e["day"] == day):
                files = f"  \n  `{e['files']}`" if e["files"] else ""
                out.append(f"- {icon[e['status']]} **{e['time']}** · _{e['agent']}_ — {e['task']}{files}")
            out.append("")

    follow = [e for e in entries if e["follow-up"]]
    if follow:
        out += ["## 📌 Follow-ups", ""]
        out += [f"- [ ] {e['follow-up']} _({e['project']}, {e['day']})_" for e in follow]
        out.append("")

    if commits:
        out += ["## 🔀 Commits", ""]
        for c in commits:
            tag = f"[{c['repo']}] " if mode == "global" else ""
            out.append(f"- {c['day']} {c['time']} `{c['hash']}` {tag}{c['msg']}")
        out.append("")

    stamp = f"_Generated by Agent Ledger at {d['generated']}"
    out.append(stamp + (" · private details hidden_" if hide else "_"))
    return "\n".join(out) + "\n"


def cmd_report(args, week=False) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="ledger.py " + ("week" if week else "report"),
                                 description="Work report for a date range.")
    if not week:
        ap.add_argument("--from", dest="since", help="first day (default: 6 days before --to)")
        ap.add_argument("--to", dest="until", default="today", help="last day (default: today)")
    ap.add_argument("--project", help="only this project")
    ap.add_argument("--agent", help="only this agent")
    ap.add_argument("--redact", action="store_true", help="hide emails, keys and home paths")
    ap.add_argument("--out", help="output file (default: <ledger>/reports/...)")
    ap.add_argument("--print", dest="show", action="store_true", help="also print the report")
    ap.add_argument("--html", action="store_true", help="also save a formatted HTML page")
    ap.add_argument("--open", action="store_true", help="open the HTML page in your browser (implies --html)")
    a = ap.parse_args(args)

    until = to_day("today" if week else a.until)
    since = to_day(a.since) if not week and a.since else \
        str(dt.date.fromisoformat(until) - dt.timedelta(days=6))
    if since > until:
        sys.exit(f"--from ({since}) is after --to ({until})")

    mode, logs, project = locate()
    report = build_report(mode, logs, project, since, until, a.project, a.agent, a.redact)
    if a.out:
        out = Path(a.out).expanduser()
    else:
        slug = "".join(f"_{re.sub(r'[^A-Za-z0-9-]+', '-', x).strip('-').lower()}"
                       for x in (a.project, a.agent) if x)
        out = logs / "reports" / f"report_{since}_to_{until}{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if a.show:
        print(report)
    print(f"Wrote {short(out)}")
    if a.html or a.open:
        data = report_data(mode, logs, project, since, until, a.project, a.agent, a.redact)
        page = out.with_suffix(".html")
        page.write_text(build_html(data), encoding="utf-8")
        print(f"Wrote {short(page)}")
        if a.open:
            open_file(page)


# ---------------------------------------------------------------- html

HTML_CSS = """
:root{color-scheme:light;--bg:#f4f4f1;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--ink3:#76756f;
--line:#e1e0d9;--chip:#efeee9;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--accent:#b7791f;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--ink:#f0efec;
--ink2:#c3c2b7;--ink3:#97968e;--line:#2c2c2a;--chip:#252523;--accent:#f5b942}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:40px 24px 64px}
.brand{display:flex;align-items:center;gap:8px;color:var(--ink2);font-weight:600;font-size:14px}
h1{font-size:32px;line-height:1.2;margin:14px 0 4px;letter-spacing:-.01em}
.sub{color:var(--ink2);margin:0}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.chip{background:var(--chip);color:var(--ink2);border-radius:999px;padding:3px 12px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:28px 0 16px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .n{font-size:28px;font-weight:700;line-height:1.1}
.tile .l{color:var(--ink2);font-size:13px;display:flex;align-items:center;gap:6px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
.bar{display:flex;gap:2px;height:12px;margin:4px 0 8px}
.bar span{border-radius:4px;min-width:4px;cursor:default}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--ink2);font-size:13px;margin-bottom:8px}
.legend b{color:var(--ink);font-weight:600}
.tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:28px 0 8px}
.tools button{font:inherit;font-size:13px;background:var(--surface);color:var(--ink2);border:1px solid var(--line);
border-radius:999px;padding:5px 14px;cursor:pointer}
.tools button[aria-pressed=true]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.tools input{font:inherit;font-size:14px;flex:1;min-width:180px;background:var(--surface);color:var(--ink);
border:1px solid var(--line);border-radius:999px;padding:6px 14px}
section{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-top:16px}
h2{font-size:19px;margin:0 0 4px;display:flex;justify-content:space-between;gap:12px;align-items:baseline}
h2 small{color:var(--ink3);font-weight:500;font-size:13px}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3);margin:18px 0 6px}
ul{list-style:none;margin:0;padding:0}
.e{display:grid;grid-template-columns:96px 52px 1fr;gap:10px;padding:9px 0;border-top:1px solid var(--line)}
.day .e:first-of-type{border-top:0}
.pill{font-size:12px;font-weight:600;border-radius:6px;padding:2px 8px;height:fit-content;width:fit-content;white-space:nowrap}
.DONE .pill{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.PARTIAL .pill{background:var(--warn);color:#0b0b0b}
.BLOCKED .pill{background:color-mix(in srgb,var(--crit) 15%,transparent);color:var(--crit)}
.t{color:var(--ink2);font-variant-numeric:tabular-nums;padding-top:1px}
.task{font-weight:500}
.agent{display:inline-block;background:var(--chip);color:var(--ink2);border-radius:6px;padding:0 7px;font-size:12px;margin-left:6px;font-weight:500}
.files,.note{color:var(--ink3);font-size:13px;margin-top:2px}
.files{font-family:var(--mono);font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th{text-align:left;color:var(--ink3);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
th,td{padding:8px 10px 8px 0;border-top:1px solid var(--line)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
code{font-family:var(--mono);font-size:12.5px;color:var(--accent)}
.fu li{padding:6px 0;border-top:1px solid var(--line)}
.fu li:first-child{border-top:0}
.empty{color:var(--ink2);text-align:center;padding:40px}
footer{color:var(--ink3);font-size:13px;margin-top:28px;text-align:center}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);font-size:12px;padding:4px 8px;border-radius:6px;opacity:0;transition:opacity .1s}
.hidden{display:none!important}
.half{display:inline-block;width:9px;height:9px;border-radius:50%;border:1.5px solid currentColor;
background:linear-gradient(90deg,currentColor 50%,transparent 50%);vertical-align:-1px;margin-right:4px}
.tbl{overflow-x:auto}
@media (max-width:640px){.e{grid-template-columns:84px 1fr}.e .t{display:none}}
@media print{body{background:#fff}.tools,#tip{display:none}section,.tile{break-inside:avoid;border-color:#ddd}
.wrap{padding:0}}
"""

HTML_JS = """
const q=document.getElementById('q'),btns=[...document.querySelectorAll('.tools button')];let st='ALL';
function apply(){const t=q.value.toLowerCase();
 document.querySelectorAll('.e').forEach(li=>{li.classList.toggle('hidden',
  (st!=='ALL'&&!li.classList.contains(st))||(t&&!li.textContent.toLowerCase().includes(t)))});
 document.querySelectorAll('.day').forEach(d=>d.classList.toggle('hidden',!d.querySelector('.e:not(.hidden)')));
 document.querySelectorAll('section.proj').forEach(s=>s.classList.toggle('hidden',!s.querySelector('.e:not(.hidden)')));}
btns.forEach(b=>b.onclick=()=>{st=b.dataset.s;btns.forEach(x=>x.setAttribute('aria-pressed',x===b));apply()});
q.oninput=apply;
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.onmousemove=e=>{tip.textContent=el.dataset.tip;tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';tip.style.opacity=1};
 el.onmouseleave=()=>tip.style.opacity=0;});
"""

ICON_SVG = ('<svg width="18" height="22" viewBox="0 0 18 22" aria-hidden="true">'
            '<rect width="18" height="22" rx="3" fill="#f5b942"/><rect x="3" width="2" height="22" fill="#c48c1e"/>'
            '<rect x="8" y="7" width="7" height="1.6" rx=".8" fill="#78500a"/>'
            '<rect x="8" y="10.5" width="7" height="1.6" rx=".8" fill="#78500a"/>'
            '<rect x="8" y="14" width="7" height="1.6" rx=".8" fill="#78500a"/></svg>')

STATUS_UI = {"DONE": ("Done", "var(--good)", "✓ "), "PARTIAL": ("Partial", "var(--warn)", "<i class='half'></i>"),
             "BLOCKED": ("Blocked", "var(--crit)", "✕ ")}


def build_html(d, title=None, daily=False) -> str:
    from html import escape as esc
    entries, commits, count = d["entries"], d["commits"], d["count"]
    since, until = d["since"], d["until"]
    heading = "Daily Digest" if daily else "Work Report"
    title = title or (f"{heading} · {since} → {until}" if since != until else f"{heading} · {since}")
    period = nice_day(since) if since == until else f"{nice_day(since)} – {nice_day(until)}"

    h = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{esc(title)}</title><style>{HTML_CSS}</style></head><body><div class='wrap'>",
         f"<div class='brand'>{ICON_SVG}Agent Ledger</div>",
         f"<h1>{heading}</h1><p class='sub'>{esc(period)}</p><div class='chips'>"]
    for label, val in (("Project", d["project_filter"]), ("Agent", d["agent_filter"])):
        if val:
            h.append(f"<span class='chip'>{label}: {esc(val)}</span>")
    if d["agents"]:
        h.append(f"<span class='chip'>Agents: {esc(', '.join(d['agents']))}</span>")
    if d["projects"] and not d["project_filter"]:
        h.append(f"<span class='chip'>{plural(len(d['projects']), 'project')}</span>")
    if d["hide"]:
        h.append("<span class='chip'>Private details hidden</span>")
    h.append("</div>")

    # stat tiles
    tiles = [("Tasks", len(entries), None), ("Done", count["DONE"], "var(--good)"),
             ("Partial", count["PARTIAL"], "var(--warn)"), ("Blocked", count["BLOCKED"], "var(--crit)"),
             ("Commits", len(commits), None)] + ([] if daily else [("Active days", len(d["days"]), None)])
    h.append("<div class='tiles'>")
    for label, n, color in tiles:
        dot = f"<span class='dot' style='background:{color}'></span>" if color else ""
        h.append(f"<div class='tile'><div class='n'>{n}</div><div class='l'>{dot}{label}</div></div>")
    h.append("</div>")

    # status bar (single stacked bar, with legend + hover)
    if entries:
        h.append("<div class='bar' role='img' aria-label='Tasks by status'>")
        for s_ in STATUSES:
            if count[s_]:
                pct = 100 * count[s_] / len(entries)
                label = STATUS_UI[s_][0]
                h.append(f"<span style='flex:{count[s_]};background:{STATUS_UI[s_][1]}' "
                         f"data-tip='{label}: {count[s_]} of {len(entries)} ({pct:.0f}%)'></span>")
        h.append("</div><div class='legend'>")
        for s_ in STATUSES:
            h.append(f"<span><span class='dot' style='background:{STATUS_UI[s_][1]}'></span> "
                     f"{STATUS_UI[s_][0]} <b>{count[s_]}</b></span>")
        h.append("</div>")

        h.append("<div class='tools'><button data-s='ALL' aria-pressed='true'>All</button>"
                 "<button data-s='DONE' aria-pressed='false'>Done</button>"
                 "<button data-s='PARTIAL' aria-pressed='false'>Partial</button>"
                 "<button data-s='BLOCKED' aria-pressed='false'>Blocked</button>"
                 "<input id='q' type='search' placeholder='Search tasks, files, agents…'></div>")
    else:
        h.append("<section class='empty'>Nothing logged in this period.</section>")

    # summary table
    if len(d["projects"]) > 1:
        h.append("<section><h2>Summary</h2><table><tr><th>Project</th><th class='num'>Tasks</th>"
                 "<th class='num'>Done</th><th class='num'>Partial</th><th class='num'>Blocked</th></tr>")
        for p in d["projects"]:
            pe = [e for e in entries if e["project"] == p]
            cells = "".join(f"<td class='num'>{sum(e['status'] == s_ for e in pe)}</td>" for s_ in STATUSES)
            h.append(f"<tr><td>{esc(p)}</td><td class='num'>{len(pe)}</td>{cells}</tr>")
        h.append("</table></section>")

    # per project timeline
    for p in d["projects"]:
        pe = [e for e in entries if e["project"] == p]
        done = sum(e["status"] == "DONE" for e in pe)
        h.append(f"<section class='proj'><h2>{esc(p)}<small>{done} of {plural(len(pe), 'task')} done</small></h2>")
        for day in sorted({e["day"] for e in pe}):
            h.append(f"<div class='day'><h3>{esc(nice_day(day))}</h3><ul>")
            for e in (e for e in pe if e["day"] == day):
                extra = ""
                if e["files"]:
                    extra += f"<div class='files'>{esc(e['files'])}</div>"
                for k, lab in (("notes", "Note"), ("follow-up", "Follow-up")):
                    if e[k]:
                        extra += f"<div class='note'>{lab}: {esc(e[k])}</div>"
                h.append(f"<li class='e {e['status']}'><span class='pill'>{STATUS_UI[e['status']][2]}{STATUS_UI[e['status']][0]}</span>"
                         f"<span class='t'>{esc(e['time'])}</span><div><span class='task'>{esc(e['task'])}</span>"
                         f"<span class='agent'>{esc(e['agent'])}</span>{extra}</div></li>")
            h.append("</ul></div>")
        h.append("</section>")

    follow = [e for e in entries if e["follow-up"]]
    if follow:
        h.append("<section><h2>Follow-ups</h2><ul class='fu'>")
        h += [f"<li>☐ {esc(e['follow-up'])} <span class='agent'>{esc(e['project'])}</span></li>" for e in follow]
        h.append("</ul></section>")

    if commits:
        h.append(f"<section><h2>Commits<small>{len(commits)}</small></h2><div class='tbl'><table>"
                 "<tr><th>Date</th><th>Commit</th>" + ("<th>Repo</th>" if d["mode"] == "global" else "")
                 + "<th>Message</th></tr>")
        for c in commits:
            repo = f"<td>{esc(c['repo'])}</td>" if d["mode"] == "global" else ""
            h.append(f"<tr><td style='white-space:nowrap'>{esc(c['day'])} {esc(c['time'])}</td>"
                     f"<td><code>{esc(c['hash'])}</code></td>{repo}<td style='min-width:220px'>{esc(c['msg'])}</td></tr>")
        h.append("</table></div></section>")

    h.append(f"<footer>Generated by Agent Ledger · {esc(d['generated'])}"
             + (" · private details hidden" if d["hide"] else "") + "</footer>")
    h.append(f"</div><div id='tip'></div><script>{HTML_JS if entries else ''}</script></body></html>")
    return "".join(h)


def open_file(path: Path) -> None:
    import webbrowser
    webbrowser.open(path.resolve().as_uri())


# ---------------------------------------------------------------- log

def git_root(path: Path):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path,
                             capture_output=True, text=True, timeout=10)
        return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def one_line(s: str) -> str:
    return " ".join(str(s).split())


def cmd_log(args) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="ledger.py log", description="Add one entry to today's log.")
    ap.add_argument("--agent", required=True, help="your name: claude, codex, cursor, ...")
    ap.add_argument("--task", required=True, help="one line: what was done")
    ap.add_argument("--status", default="DONE", type=str.upper, choices=STATUSES)
    ap.add_argument("--files", default="", help="main files touched")
    ap.add_argument("--project", help="project name (default: git repo name)")
    ap.add_argument("--notes", default="")
    ap.add_argument("--follow-up", dest="follow_up", default="", help="what's left to do")
    ap.add_argument("--repo", help="repo path (default: the git repo you're in)")
    a = ap.parse_args(args)

    mode, logs, project = locate()
    now = dt.datetime.now()
    repo = Path(a.repo).expanduser().resolve() if a.repo else git_root(Path.cwd())
    name = a.project or (repo.name if repo else (project.name if project else Path.cwd().name))
    agent = re.sub(r"[^a-z0-9_-]", "", a.agent.lower()) or "agent"

    lines = [f"## {now:%H:%M} · {one_line(name)} · {a.status}", f"- Task: {one_line(a.task)}"]
    if a.files:
        lines.append(f"- Files: {one_line(a.files)}")
    if mode == "global" and repo:
        lines.append(f"- Repo: {short(repo)}")
    if a.notes:
        lines.append(f"- Notes: {one_line(a.notes)}")
    if a.follow_up:
        lines.append(f"- Follow-up: {one_line(a.follow_up)}")

    path = logs / f"{now:%Y-%m-%d}" / f"{agent}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    gap = "\n" if path.exists() and path.stat().st_size else ""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(gap + "\n".join(lines) + "\n")
    print(f"Logged to {short(path)}")


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def cmd_hook(args) -> None:
    """Claude Code Stop hook: if files were changed but nothing was logged, ask Claude to log.

    Never fails loudly: any problem means "do nothing", so it can't break a session.
    """
    try:
        if not args or args[0] != "claude":
            return
        data = json.load(sys.stdin)
        if data.get("stop_hook_active"):          # we already reminded once; let it stop
            return
        transcript = Path(str(data.get("transcript_path", ""))).expanduser()
        if not transcript.is_file():
            return
        mode, logs, _ = locate()
        logs_str = str(logs.resolve())

        step, last_edit, last_log = 0, -1, -1
        with open(transcript, encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                try:
                    content = (json.loads(raw).get("message") or {}).get("content")
                except (ValueError, AttributeError):
                    continue
                for c in content if isinstance(content, list) else []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    step += 1
                    name, inp = c.get("name"), c.get("input") or {}
                    if name == "Bash":
                        cmd = str(inp.get("command", ""))
                        if "ledger.py" in cmd and re.search(r"\blog\b", cmd):
                            last_log = step
                    elif name in EDIT_TOOLS:
                        target = str(inp.get("file_path") or inp.get("notebook_path") or "")
                        if target and str(Path(target).expanduser().resolve()).startswith(logs_str):
                            last_log = step               # wrote the log by hand
                        elif target:
                            last_edit = step

        if last_edit > last_log:
            script = short(Path(__file__).resolve()) if mode == "global" else f"{PROJECT_DIR_NAME}/ledger.py"
            print(json.dumps({"decision": "block", "reason": (
                "Agent Ledger: you changed files but haven't logged this work yet. "
                f'If the task is finished (or blocked), run: python3 {script} log --agent claude '
                '--task "<one line: what was done>" --files "<main files>" '
                '(add --status PARTIAL/BLOCKED or --follow-up "..." if needed). '
                "If you're still mid-task, just continue.")}))
    except (Exception, SystemExit):
        return


# ---------------------------------------------------------------- update

def cmd_refresh(args) -> None:
    """Internal: after an update, rewrite this install's rules and helpers with the new text.

    Only touches files that already have Agent Ledger in them, so the user's choices stay.
    """
    mode, logs, project = locate()
    if mode == "global":
        script = short(logs / "ledger.py")
        rules = agent_rules(short(logs), script, with_repo=True)
        rule_files = [Path.home() / ".claude" / "CLAUDE.md", Path.home() / ".codex" / "AGENTS.md"]
        cmd_file = Path.home() / ".claude" / "commands" / "digest.md"
        hooks = [(Path.home() / ".claude" / "settings.json",
                  f'python3 "{(logs / "ledger.py").resolve()}" {HOOK_MARK}')]
        (logs / "CURSOR_RULE.md").write_text(rules, encoding="utf-8")
    else:
        script = f"{PROJECT_DIR_NAME}/ledger.py"
        rules = agent_rules(PROJECT_DIR_NAME, script, with_repo=False)
        rule_files = [project / "AGENTS.md", project / "CLAUDE.md"]
        cmd_file = project / ".claude" / "commands" / "digest.md"
        command = f'python3 "$CLAUDE_PROJECT_DIR/{PROJECT_DIR_NAME}/ledger.py" {HOOK_MARK}'
        hooks = [(project / ".claude" / n, command) for n in ("settings.json", "settings.local.json")]
    for f in rule_files:
        if has_rules(f):
            add_rules(f, rules)
    if cmd_file.exists():
        cmd_file.write_text(digest_command(script), encoding="utf-8")
    for settings, command in hooks:
        if has_claude_hook(settings):
            install_claude_hook(settings, command)


def cmd_update(args) -> None:
    """Refresh installed copies of ledger.py (and their rules) from a newer copy.

    Run it from the repo or pip install after upgrading (updates every copy it knows about),
    or from an installed copy (pulls from the copy it was installed from).
    """
    me = Path(__file__).resolve()
    here = me.parent
    installed = (here / GLOBAL_MARKER).exists() or here.name == PROJECT_DIR_NAME

    if installed:
        source = recorded_source(here)
        if not source:
            sys.exit("This copy doesn't know where it was installed from.\n"
                     "Run update from your Agent-Ledger folder instead (after `git pull`):\n"
                     "  python3 /path/to/Agent-Ledger/ledger.py update")
        targets = [me]
    else:
        source = me
        candidates = registered_installs() + [global_home() / "ledger.py", Path.cwd() / PROJECT_DIR_NAME / "ledger.py"]
        candidates += [Path(a).expanduser() / PROJECT_DIR_NAME / "ledger.py" for a in args if not a.startswith("-")]
        targets, seen = [], set()
        for c in candidates:
            if c.is_file() and c.resolve() != me and c.resolve() not in seen:
                seen.add(c.resolve())
                targets.append(c.resolve())

    if not targets:
        print("No installed copies found. Set one up with:  python3 ledger.py init")
        return

    new = version_of(source)
    print(f"Updating from {short(source)} (version {new})\n")
    for t in targets:
        old = version_of(t)
        if t.read_bytes() == source.read_bytes():
            print(f"  {short(t):<44} already up to date ({new})")
            continue
        shutil.copy2(source, t)
        (t.parent / SOURCE_MARKER).write_text(str(source) + "\n", encoding="utf-8")
        register_install(t)
        refreshed = subprocess.run([sys.executable, str(t), "_refresh"], capture_output=True, text=True)
        note = "" if refreshed.returncode == 0 else "  (rules not refreshed; run init again)"
        print(f"  {short(t):<44} {old} → {new}{note}")
    print("\nDone. Restart open agent sessions so they pick up any rule changes.")


# ---------------------------------------------------------------- status

def has_rules(path: Path) -> bool:
    return path.exists() and MARK_START in path.read_text(encoding="utf-8", errors="ignore")


def cmd_status(args) -> None:
    mode, logs, project = locate()
    day = parse_date(args)
    ok, warn = "✅", "⚠️ "
    problems = []

    check_args(args, value_flags=("--date",), cmd="status")
    print(f"Agent Ledger status — {day}\n")
    print(f"  Mode:     {mode}")
    print(f"  Logs:     {short(logs / day)}/")
    print(f"  Version:  {__version__}")
    src = recorded_source(Path(__file__).resolve().parent)
    if src and vtuple(version_of(src)) > vtuple(__version__):
        print(f"  {warn}A newer version ({version_of(src)}) is available at {short(src)}")
        print(f"      Run:  python3 {short(Path(__file__).resolve())} update")

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
    if mode == "project":
        hook_files = [project / ".claude" / "settings.json", project / ".claude" / "settings.local.json"]
    else:
        hook_files = [Path.home() / ".claude" / "settings.json"]
    hooked = has_claude_hook(*hook_files)
    print(f"    {ok if hooked else '·  '} {'Claude reminder':<15} "
          f"{'hook on (asks Claude to log if it forgets)' if hooked else 'hook off (optional, run init again)'}")
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
    if args[0] in ("--version", "-V", "version"):
        print(f"agent-ledger {__version__}")
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
    elif cmd == "log":
        cmd_log(rest)
    elif cmd == "report":
        cmd_report(rest)
    elif cmd == "week":
        cmd_report(rest, week=True)
    elif cmd == "hook":
        cmd_hook(rest)
    elif cmd == "update":
        cmd_update(rest)
    elif cmd == "_refresh":
        cmd_refresh(rest)
    else:
        sys.exit(f"Unknown command: {cmd}\nRun `ledger.py --help` to see the commands. "
                 "(If it's a newer command, your copy may be out of date: run `ledger.py update`.)")


if __name__ == "__main__":
    main()
