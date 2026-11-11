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
        add --html to also save DIGEST.html, --open to open it in your browser,
        --redact to hide emails, keys and home-folder paths
  python3 ledger.py status                 Check the setup / why nothing was logged
  python3 ledger.py log --agent NAME --task "..." [--files ...] [--status PARTIAL|BLOCKED]
                        [--client NAME] [--time 1h30m]
                                            Add an entry to today's log (used by agents)
  python3 ledger.py report [--from DATE] [--to DATE] [--project NAME] [--agent NAME] [--redact]
                                            Work report for a date range (default: last 7 days)
  python3 ledger.py standup [--project NAME] [--agent NAME] [--redact]
                                            Yesterday / Today / Blockers, ready to paste
  python3 ledger.py client [PROJECT CLIENT]  Link a project to a client (no args: list them)
  python3 ledger.py week [--project NAME] [--redact]
                                            Report for the last 7 days
        reports also take --html (formatted page) and --open (open it in your browser)

  python3 ledger.py update                  Refresh installed copies after you upgrade
  python3 ledger.py mcp                     Run as an MCP server (agents log through MCP tools)
  python3 ledger.py mcp-install             Add the MCP server to Cursor and Codex
  python3 ledger.py git-hook install [REPO] Log commits that no agent logged (safety net)
  python3 ledger.py git-hook uninstall [REPO]
  python3 ledger.py recover [--date DATE] [--apply]
                                            Find Claude Code / Codex work nobody logged (--apply adds it)
  python3 ledger.py --version               Show the version

DATE is YYYY-MM-DD, 'today' or 'yesterday'.
Installed with pipx or pip? Type `agent-ledger` instead of `python3 ledger.py`. No dependencies. Python 3.8+.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

__version__ = "0.4.2"

PROJECT_DIR_NAME = "ledger"
GLOBAL_MARKER = ".agent-ledger-global"
SOURCE_MARKER = ".agent-ledger-source"   # where an installed copy was copied from
MARK_START = "<!-- agent-ledger:start -->"
MARK_END = "<!-- agent-ledger:end -->"
STATUSES = ("DONE", "PARTIAL", "BLOCKED")

HEADING_RE = re.compile(r"^##\s+(\d{1,2}:\d{2})\s*[·\-|]\s*(.*?)\s*[·\-|]\s*([A-Za-z]+)\s*$")
FIELD_RE = re.compile(r"^-\s*(Task|Files|Notes|Follow-up|Repo|Client|Time)\s*:\s*(.*)$", re.IGNORECASE)
GAP_CAP_MIN = 120          # an estimated task never counts for more than this


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
- If you have the Agent Ledger MCP tool `log_work`, you can call it instead (same fields).

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
    blank = {"task": "", "files": "", "notes": "", "follow-up": "", "repo": "", "client": "", "time_spent": ""}
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
            key = f.group(1).lower()
            current["time_spent" if key == "time" else key] = f.group(2).strip()
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
    if "--redact" in args:                       # same as the HTML page and reports: nothing private
        digest = redact(digest)
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


def parse_minutes(text):
    """'90', '90m', '1h30m', '1h 30m', '1.5h' -> minutes, or None."""
    m = re.fullmatch(r"\s*(?:(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?\s*", str(text or ""))
    if m and (m.group(1) or m.group(2)):
        return int(round(float(m.group(1) or 0) * 60)) + int(m.group(2) or 0)
    if re.fullmatch(r"\s*\d+\s*", str(text or "")):
        return int(text)
    return None


def fmt_minutes(m):
    if m is None:
        return ""
    h, mm = divmod(int(round(m)), 60)
    return f"{h}h {mm:02d}m" if h else f"{mm}m"


def clients_file(logs: Path) -> Path:
    return logs / "clients.json"


def client_map(logs: Path) -> dict:
    try:
        data = json.loads(clients_file(logs).read_text(encoding="utf-8"))
        return {str(k).lower(): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def add_time_and_clients(entries, logs: Path):
    """Each entry gets client (its own tag, else the project's client) and minutes:
    the logged time, else the gap since the same agent's previous entry that day (capped)."""
    clients = client_map(logs)
    last = {}
    for e in sorted(entries, key=lambda e: (e["day"], e["agent"], e["time"])):
        e["client"] = e.get("client") or clients.get(e["project"].lower(), "")
        logged = parse_minutes(e.get("time_spent"))
        e["minutes"], e["estimated"] = (logged, False) if logged is not None else (None, False)
        key = (e["day"], e["agent"])
        if e["time"] != "--:--":
            h, m = map(int, e["time"].split(":"))
            now = h * 60 + m
            if e["minutes"] is None and key in last and 0 < now - last[key] <= GAP_CAP_MIN:
                e["minutes"], e["estimated"] = now - last[key], True
            last[key] = now
    return entries


def collect(logs: Path, since: str, until: str, project_filter=None, agent_filter=None, client_filter=None):
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
    add_time_and_clients(entries, logs)
    if client_filter:
        entries = [e for e in entries if e["client"].lower() == client_filter.lower()]
    if project_filter:
        entries = [e for e in entries if e["project"].lower() == project_filter.lower()]
    if agent_filter:
        entries = [e for e in entries if e["agent"].lower() == agent_filter.lower()]
    return sorted(entries, key=lambda e: (e["day"], e["time"]))


def report_data(mode, logs, project, since, until, project_filter=None, agent_filter=None, hide=False,
                client_filter=None):
    """Everything a report needs, already filtered and (optionally) redacted."""
    entries = collect(logs, since, until, project_filter, agent_filter, client_filter)
    commits = commits_for(mode, project, entries, since, until)
    if mode == "global" and (project_filter or client_filter):
        repos = {Path(e["repo"]).expanduser().name for e in entries if e.get("repo")}
        commits = [c for c in commits if c["repo"] in repos]
    if agent_filter:
        commits = []                       # commits can't be tied to one agent
    if hide:
        for e in entries:
            for k in ("task", "files", "notes", "follow-up", "project", "client"):
                e[k] = redact(e[k])
        for c in commits:
            c["msg"] = redact(c["msg"])
    return {
        "mode": mode, "since": since, "until": until, "hide": hide,
        "project_filter": project_filter, "agent_filter": agent_filter, "client_filter": client_filter,
        "entries": entries, "commits": commits, "time": time_summary(entries),
        "count": {s_: sum(e["status"] == s_ for e in entries) for s_ in STATUSES},
        "projects": sorted({e["project"] for e in entries}, key=str.lower),
        "agents": sorted({e["agent"] for e in entries}),
        "days": sorted({e["day"] for e in entries}),
        "generated": f"{dt.datetime.now():%Y-%m-%d %H:%M}",
    }


def time_summary(entries):
    """Logged and estimated minutes, per (client, project) and in total."""
    rows = {}
    for e in entries:
        if e.get("minutes") is None:
            continue
        r = rows.setdefault((e.get("client", ""), e["project"]), {"tasks": 0, "logged": 0, "estimated": 0})
        r["tasks"] += 1
        r["estimated" if e["estimated"] else "logged"] += e["minutes"]
    total = {"logged": sum(r["logged"] for r in rows.values()),
             "estimated": sum(r["estimated"] for r in rows.values())}
    return {"rows": sorted(rows.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1].lower())), "total": total}


def time_label(e):
    if e.get("minutes") is None:
        return ""
    return ("~" if e["estimated"] else "") + fmt_minutes(e["minutes"])


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def nice_day(day):
    return dt.date.fromisoformat(day).strftime("%a %d %b %Y")


def build_report(mode, logs, project, since, until, project_filter=None, agent_filter=None, hide=False,
                 client_filter=None):
    d = report_data(mode, logs, project, since, until, project_filter, agent_filter, hide, client_filter)
    entries, commits, count = d["entries"], d["commits"], d["count"]
    icon = {"DONE": "✅", "PARTIAL": "🟡", "BLOCKED": "🔴"}

    title = f"Work Report — {since} → {until}" if since != until else f"Work Report — {since}"
    out = [f"# {title}", ""]
    scope = [f"Client: {client_filter}" if client_filter else "",
             f"Project: {project_filter}" if project_filter else "",
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
                spent = f" ({time_label(e)})" if time_label(e) else ""
                out.append(f"- {icon[e['status']]} **{e['time']}** · _{e['agent']}_ — {e['task']}{spent}{files}")
            out.append("")

    t = d["time"]
    if t["rows"]:
        out += ["## ⏱️ Time", "", "| Client | Project | Tasks | Logged | Estimated | Total |",
                "|---|---|---:|---:|---:|---:|"]
        for (client, proj), r in t["rows"]:
            out.append(f"| {client or '—'} | {proj} | {r['tasks']} | {fmt_minutes(r['logged']) if r['logged'] else '—'} | "
                       f"{fmt_minutes(r['estimated']) if r['estimated'] else '—'} | **{fmt_minutes(r['logged'] + r['estimated'])}** |")
        tot = t["total"]
        out += ["", f"**Total: {fmt_minutes(tot['logged'] + tot['estimated'])}** "
                    f"({fmt_minutes(tot['logged']) or '0m'} logged, {fmt_minutes(tot['estimated']) or '0m'} estimated)  ",
                "_Estimated = time since the same agent's previous entry that day, up to 2h. "
                "Log exact time with `--time`._", ""]

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
    ap.add_argument("--client", help="only this client")
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
    report = build_report(mode, logs, project, since, until, a.project, a.agent, a.redact, a.client)
    if a.out:
        out = Path(a.out).expanduser()
    else:
        slug = "".join(f"_{re.sub(r'[^A-Za-z0-9-]+', '-', x).strip('-').lower()}"
                       for x in (a.client, a.project, a.agent) if x)
        out = logs / "reports" / f"report_{since}_to_{until}{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if a.show:
        print(report)
    print(f"Wrote {short(out)}")
    if a.html or a.open:
        data = report_data(mode, logs, project, since, until, a.project, a.agent, a.redact, a.client)
        page = out.with_suffix(".html")
        page.write_text(build_html(data), encoding="utf-8")
        print(f"Wrote {short(page)}")
        if a.open:
            open_file(page)


# ---------------------------------------------------------------- clients

def cmd_client(args) -> None:
    check_args(args, flags=("--remove",), positional=2, cmd="client")
    mode, logs, project = locate()
    data = client_map(logs)
    names = [a for a in args if not a.startswith("-")]
    if not names:
        if not data:
            print("No clients yet. Link one with:  ledger.py client PROJECT CLIENT")
        for proj, client in sorted(data.items()):
            print(f"  {proj:<28} → {client}")
        return
    proj = names[0].lower()
    if "--remove" in args:
        data.pop(proj, None)
        print(f"{names[0]} is no longer linked to a client.")
    elif len(names) == 2:
        data[proj] = names[1]
        print(f"{names[0]} → {names[1]}. Reports can now use --client {names[1]}.")
    else:
        sys.exit("Usage: ledger.py client PROJECT CLIENT   (or: client PROJECT --remove)")
    clients_file(logs).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- standup

def build_standup(mode, logs, project, day: str, project_filter=None, agent_filter=None, hide=False,
                  limit=8) -> str:
    """Yesterday (last working day) / Today / Blockers as plain text that pastes anywhere."""
    today = dt.date.fromisoformat(day)
    clean = redact if hide else (lambda x: x)
    prev_day, prev = None, []
    for back in range(1, 15):                          # the last day that has entries
        d = str(today - dt.timedelta(days=back))
        prev = collect(logs, d, d, project_filter, agent_filter)
        if prev:
            prev_day = d
            break
    now = collect(logs, day, day, project_filter, agent_filter)

    def item(text, e):
        return f"• {clean(text)} ({clean(e['project'])})"

    def section(title, items):
        items = list(dict.fromkeys(items))            # no duplicates, keep order
        body = items[:limit] + ([f"• …and {len(items) - limit} more"] if len(items) > limit else [])
        return [title] + (body or ["• Nothing logged"]) + [""]

    if prev_day:
        gap = (today - dt.date.fromisoformat(prev_day)).days
        when = "Yesterday" if gap == 1 else f"Last working day ({dt.date.fromisoformat(prev_day):%a %d %b})"
    else:
        when = "Yesterday"
    out = [f"Standup · {today:%a %d %b %Y}", ""]
    out += section(when, [item(e["task"], e) for e in prev if e["status"] == "DONE"]
                   + [item(e["task"] + ", in progress", e) for e in prev if e["status"] == "PARTIAL"])

    done_today = [item(e["task"], e) for e in now if e["status"] == "DONE"]
    finished = {e["task"].lower() for e in now if e["status"] == "DONE"}
    carried = [item(e["follow-up"], e) for e in prev + now if e["follow-up"] and e["status"] != "BLOCKED"
               and e["follow-up"].lower() not in finished]
    carried += [item("Continue: " + e["task"], e) for e in prev + now
                if e["status"] == "PARTIAL" and e["task"].lower() not in finished]
    today_items = [f"{x[:2]}Done: {x[2:]}" for x in done_today] + carried
    out += section("Today", today_items)

    blocked = [item(e["task"] + (f" (needs: {e['follow-up']})" if e["follow-up"] else ""), e)
               for e in prev + now if e["status"] == "BLOCKED"]
    out += ["Blockers"] + ((blocked[:limit]) or ["• None"]) + [""]
    return "\n".join(out).rstrip() + "\n"


def cmd_standup(args) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="ledger.py standup", description="Yesterday / Today / Blockers.")
    ap.add_argument("--date", default="today", help="the standup day (default: today)")
    ap.add_argument("--project", help="only this project")
    ap.add_argument("--agent", help="only this agent")
    ap.add_argument("--redact", action="store_true", help="hide emails, keys and home paths")
    a = ap.parse_args(args)
    mode, logs, project = locate()
    print(build_standup(mode, logs, project, to_day(a.date), a.project, a.agent, a.redact), end="")


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
.charts{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:28px}
.charts.one{grid-template-columns:minmax(0,1fr)}
.charts h3{margin:0 0 10px}
.cols{display:flex;align-items:flex-end;gap:4px;height:140px;border-bottom:1px solid var(--line);position:relative}
.cols .ymax{position:absolute;top:-4px;left:0;font-size:11px;color:var(--ink3)}
.cols .grid{position:absolute;left:0;right:0;top:0;border-top:1px dashed var(--line)}
.col{flex:1;min-width:4px;height:100%;display:flex;flex-direction:column-reverse;gap:2px;position:relative;z-index:1}
.col{align-items:center}
.col span{display:block;width:min(100%,36px)}
.col span:last-child{border-radius:4px 4px 0 0}
.col:hover span{filter:brightness(1.08)}
.xl{display:flex;gap:4px;margin-top:6px}
.xl span{flex:1;min-width:4px;text-align:center;font-size:11px;color:var(--ink3);white-space:nowrap;overflow:visible}
.hb{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:10px 12px;align-items:center;font-size:13px}
.hb .track{height:10px;border-radius:0 4px 4px 0;background:var(--chip)}
.hb .fill{height:10px;border-radius:0 4px 4px 0;background:var(--series)}
.hb b{font-variant-numeric:tabular-nums;font-weight:600}
:root{--series:#5b6b82}
@media (prefers-color-scheme:dark){:root{--series:#9aa9c2}}
@media (max-width:640px){.charts{grid-template-columns:minmax(0,1fr)}}
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
    for label, val in (("Client", d.get("client_filter")), ("Project", d["project_filter"]),
                       ("Agent", d["agent_filter"])):
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
    tt = d["time"]["total"]
    if tt["logged"] + tt["estimated"]:
        tiles.append(("Time" + (" (est.)" if tt["estimated"] and not tt["logged"] else ""),
                      fmt_minutes(tt["logged"] + tt["estimated"]), None))
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

        h.append(charts_html(d, esc))
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
                         + (f"<span class='agent' title='{'estimated' if e['estimated'] else 'logged'} time'>"
                            f"{esc(time_label(e))}</span>" if time_label(e) else "")
                         + f"<span class='agent'>{esc(e['agent'])}</span>{extra}</div></li>")
            h.append("</ul></div>")
        h.append("</section>")

    if d["time"]["rows"]:
        tt = d["time"]["total"]
        h.append(f"<section><h2>Time<small>{fmt_minutes(tt['logged'] + tt['estimated'])} total</small></h2>"
                 "<div class='tbl'><table><tr><th>Client</th><th>Project</th><th class='num'>Tasks</th>"
                 "<th class='num'>Logged</th><th class='num'>Estimated</th><th class='num'>Total</th></tr>")
        for (client, proj), r in d["time"]["rows"]:
            h.append(f"<tr><td>{esc(client) or '—'}</td><td>{esc(proj)}</td><td class='num'>{r['tasks']}</td>"
                     f"<td class='num'>{fmt_minutes(r['logged']) if r['logged'] else '—'}</td>"
                     f"<td class='num'>{fmt_minutes(r['estimated']) if r['estimated'] else '—'}</td>"
                     f"<td class='num'><b>{fmt_minutes(r['logged'] + r['estimated'])}</b></td></tr>")
        h.append("</table></div><p class='note'>Estimated time is the gap since the same agent's previous "
                 "entry that day, up to 2 hours. Log exact time with <code>--time</code>.</p></section>")

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


def charts_html(d, esc) -> str:
    """Tasks per day (stacked by status) and tasks per agent. Empty days stay visible."""
    entries = d["entries"]
    start, end = dt.date.fromisoformat(d["since"]), dt.date.fromisoformat(d["until"])
    n_days = (end - start).days + 1
    per_agent = {}
    for e in entries:
        per_agent[e["agent"]] = per_agent.get(e["agent"], 0) + 1
    show_days = 1 < n_days <= 62
    show_agents = len(per_agent) > 1
    if not (show_days or show_agents):
        return ""
    h = [f"<section><h2>Activity</h2><div class='charts{'' if show_days and show_agents else ' one'}'>"]
    if show_days:
        days = [start + dt.timedelta(days=i) for i in range(n_days)]
        counts = {str(x): {s_: 0 for s_ in STATUSES} for x in days}
        for e in entries:
            counts[e["day"]][e["status"]] += 1
        top = max([sum(c.values()) for c in counts.values()] + [1])
        h.append(f"<div><h3>Tasks per day</h3><div class='cols' role='img' aria-label='Tasks per day by status'>"
                 f"<span class='grid'></span><span class='ymax'>{top}</span>")
        for x in days:
            c = counts[str(x)]
            total = sum(c.values())
            parts = ", ".join(f"{c[s_]} {STATUS_UI[s_][0].lower()}" for s_ in STATUSES if c[s_])
            tip = f"{x:%a %d %b}: {plural(total, 'task')}" + (f" ({parts})" if parts else "")
            segs = "".join(f"<span style='height:{100 * c[s_] / top:.2f}%;background:{STATUS_UI[s_][1]}'></span>"
                           for s_ in STATUSES if c[s_])
            h.append(f"<div class='col' data-tip='{esc(tip)}'>{segs}</div>")
        step = 1 if n_days <= 10 else (2 if n_days <= 20 else 7)
        h.append("</div><div class='xl' aria-hidden='true'>")
        for i, x in enumerate(days):
            label = (f"{x:%a}"[:2] + f" {x.day}") if n_days <= 10 else str(x.day)
            h.append(f"<span>{label if i % step == 0 else ''}</span>")
        h.append("</div></div>")
    if show_agents:
        top = max(per_agent.values())
        h.append("<div><h3>Tasks per agent</h3><div class='hb'>")
        for agent, n in sorted(per_agent.items(), key=lambda kv: (-kv[1], kv[0])):
            h.append(f"<span>{esc(agent)}</span><div class='track' data-tip='{esc(agent)}: {plural(n, 'task')}'>"
                     f"<div class='fill' style='width:{100 * n / top:.1f}%'></div></div><b>{n}</b>")
        h.append("</div></div>")
    h.append("</div></section>")
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


def add_entry(agent, task, status="DONE", files="", project_name=None, notes="", follow_up="", repo=None,
              when=None, client="", time_spent=""):
    """Append one entry to the log for `agent` (today, or the day of `when`). Returns the file's path."""
    mode, logs, project = locate()
    now = when or dt.datetime.now()
    status = str(status or "DONE").upper()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if not one_line(task):
        raise ValueError("task can't be empty")
    minutes = parse_minutes(time_spent) if time_spent else None
    if time_spent and minutes is None:
        raise ValueError(f"can't read time '{time_spent}' (try 45m, 1h30m or 1.5h)")
    repo = Path(repo).expanduser().resolve() if repo else git_root(Path.cwd())
    name = project_name or (repo.name if repo else (project.name if project else Path.cwd().name))
    agent = re.sub(r"[^a-z0-9_-]", "", str(agent).lower()) or "agent"

    lines = [f"## {now:%H:%M} · {one_line(name)} · {status}", f"- Task: {one_line(task)}"]
    if files:
        lines.append(f"- Files: {one_line(files)}")
    if mode == "global" and repo:
        lines.append(f"- Repo: {short(repo)}")
    if client:
        lines.append(f"- Client: {one_line(client)}")
    if minutes is not None:
        lines.append(f"- Time: {fmt_minutes(minutes)}")
    if notes:
        lines.append(f"- Notes: {one_line(notes)}")
    if follow_up:
        lines.append(f"- Follow-up: {one_line(follow_up)}")

    path = logs / f"{now:%Y-%m-%d}" / f"{agent}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    gap = "\n" if path.exists() and path.stat().st_size else ""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(gap + "\n".join(lines) + "\n")
    return path


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
    ap.add_argument("--client", default="", help="client this work is for")
    ap.add_argument("--time", default="", help="time spent, e.g. 45m, 1h30m, 1.5h")
    a = ap.parse_args(args)
    try:
        path = add_entry(a.agent, a.task, a.status, a.files, a.project, a.notes, a.follow_up, a.repo,
                         client=a.client, time_spent=a.time)
    except ValueError as e:
        sys.exit(str(e))
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


# ---------------------------------------------------------------- commit safety net

HOOK_BEGIN = "# >>> agent-ledger >>>"
HOOK_END = "# <<< agent-ledger <<<"
GIT_AGENT = "git"


def git_out(repo: Path, *args) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def post_commit_hook(repo: Path) -> Path:
    hooks = Path(git_out(repo, "rev-parse", "--git-path", "hooks") or ".git/hooks")
    return (hooks if hooks.is_absolute() else repo / hooks) / "post-commit"


def cmd_git_hook(args) -> None:
    check_args(args, positional=2, cmd="git-hook")
    action = args[0] if args else ""
    if action not in ("install", "uninstall"):
        sys.exit("Usage: ledger.py git-hook install|uninstall [REPO]")
    locate()                                            # fail early if Agent Ledger isn't set up
    repo = git_root(Path(args[1]).expanduser() if len(args) > 1 else Path.cwd())
    if not repo:
        sys.exit("Not inside a git repo. Run this in your project, or pass its path.")
    hook = post_commit_hook(repo)
    text = hook.read_text(encoding="utf-8") if hook.exists() else ""
    if HOOK_BEGIN in text:                              # drop our old block, keep everything else
        before, _, rest = text.partition(HOOK_BEGIN)
        text = before.rstrip("\n") + rest.partition(HOOK_END)[2]
    if action == "uninstall":
        if text.strip() in ("", "#!/bin/sh"):
            if hook.exists():
                hook.unlink()
        else:
            hook.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        print(f"Commit safety net removed from {repo.name}.")
        return
    script = str(Path(__file__).resolve())
    block = (f"{HOOK_BEGIN}\n# Logs commits that no AI agent logged. Remove with: ledger.py git-hook uninstall\n"
             f'python3 "{script}" commit-log >/dev/null 2>&1 || true\n{HOOK_END}\n')
    if not text.strip():
        text = "#!/bin/sh\n"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | 0o111)
    print(f"Commit safety net on for {repo.name} ({short(hook)}).")
    print("If you commit and no agent logged that work in the last 30 minutes, the commit is logged for you.")


def recently_logged(logs: Path, repo: Path, minutes: int) -> bool:
    now = dt.datetime.now()
    since = now - dt.timedelta(minutes=minutes)
    for e in collect(logs, str(since.date()), str(now.date())):
        if e["agent"] == GIT_AGENT or e["time"] == "--:--":
            continue
        when = dt.datetime.fromisoformat(f"{e['day']}T{e['time']}")
        same_repo = (e.get("repo") and Path(e["repo"]).expanduser().resolve() == repo.resolve()) \
            or e["project"].lower() == repo.name.lower()
        if same_repo and when >= since.replace(second=0, microsecond=0):
            return True
    return False


def cmd_commit_log(args) -> None:
    """Internal, run by the post-commit hook: log the commit if no agent logged recent work here."""
    try:
        repo = git_root(Path.cwd())
        if not repo:
            return
        mode, logs, project = locate()
        info = git_out(repo, "log", "-1", "--format=%h%x09%P%x09%s").split("\t")
        if len(info) < 3 or len(info[1].split()) > 1:   # skip merge commits
            return
        minutes = int(os.environ.get("AGENT_LEDGER_COMMIT_WINDOW", "30"))
        if recently_logged(logs, repo, minutes):
            return
        files = [f for f in git_out(repo, "show", "--name-only", "--format=", "HEAD").splitlines() if f]
        shown = ", ".join(files[:5]) + (f" (+{len(files) - 5} more)" if len(files) > 5 else "")
        add_entry(GIT_AGENT, f"Commit: {info[2]}", "DONE", shown, None,
                  f"commit {info[0]}, logged by the git hook because no agent logged this work", "", str(repo))
    except (Exception, SystemExit):
        return                                          # a hook must never get in the way of a commit


# ---------------------------------------------------------------- recover from session files

PATCH_FILE_RE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: ([^\n\\`'\"]+)")
# Shell commands that change files: in-place edits, copies/moves, redirects into a file, commits.
WRITE_CMD_RE = re.compile(r"(?:\bsed\s+-i|\bperl\s+-pi|\btee\s|\bmv\s|\bcp\s|\brm\s|\bmkdir\s|\btouch\s|"
                          r"\bgit\s+(?:commit|apply|am)\b|\bapply_patch\b|(?<![=\-<>&2])>>?\s*(?!/dev/null|&)[\w./~\"'-])")
LEDGER_FILE_RE = re.compile(r"ledger/\d{4}-\d{2}-\d{2}/[\w-]+\.md")
CLAUDE_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def local_time(ts):
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def first_line(text, limit=110):
    for line in str(text or "").splitlines():
        line = re.sub(r"[*_`#>]+", "", line).strip(" -•")
        if line and not line.startswith("<"):
            return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"
    return ""


def is_log_call(name, text):
    """A log command, the MCP tool, or a hand-written append to a ledger file."""
    text = str(text or "")
    return ("log_work" in str(name or "") or bool(re.search(r"ledger\.py\S*\s+log\b", text))
            or bool(LEDGER_FILE_RE.search(text)))


def read_jsonl(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def codex_sessions(day: dt.date):
    """Sessions from Codex rollout files: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl."""
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    for d in (day - dt.timedelta(days=1), day):          # a session can start before midnight
        folder = root / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"
        for f in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
            s = {"agent": "codex", "id": f.stem[-36:], "cwd": None, "edits": [], "files": [],
                 "logged": False, "summary": "", "prompt": ""}
            for r in read_jsonl(f):
                p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
                kind, sub, when = r.get("type"), p.get("type"), local_time(r.get("timestamp"))
                if kind in ("session_meta", "turn_context") and p.get("cwd"):
                    s["cwd"] = p["cwd"]
                elif sub in ("custom_tool_call", "function_call"):
                    text = p.get("input") or p.get("arguments") or ""
                    text = text if isinstance(text, str) else json.dumps(text)
                    if is_log_call(p.get("name"), text):
                        s["logged"] = True
                    paths = PATCH_FILE_RE.findall(text)
                    if paths and when:
                        s["edits"].append(when)
                        s["files"] += [x.strip() for x in paths]
                    elif when and WRITE_CMD_RE.search(text):
                        s["edits"].append(when)
                elif sub == "task_complete" and p.get("last_agent_message"):
                    s["summary"] = p["last_agent_message"]
                elif sub == "message" and p.get("role") == "user" and not s["prompt"]:
                    for c in p.get("content") or []:
                        if isinstance(c, dict) and first_line(c.get("text")):
                            s["prompt"] = c.get("text")
                            break
            yield s


def claude_sessions(day: dt.date):
    """Sessions from Claude Code transcripts: ~/.claude/projects/<project>/<session>.jsonl."""
    roots = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = [Path(r) for r in roots.split(",")] if roots else [Path.home() / ".claude"]
    for root in roots:
        projects = root / "projects"
        for f in sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []:
            if dt.date.fromtimestamp(f.stat().st_mtime) < day:
                continue                                 # untouched since before that day
            s = {"agent": "claude", "id": f.stem, "cwd": None, "edits": [], "files": [],
                 "logged": False, "summary": "", "prompt": ""}
            for r in read_jsonl(f):
                if r.get("cwd"):
                    s["cwd"] = r["cwd"]
                if r.get("type") == "summary" and r.get("summary"):
                    s["summary"] = r["summary"]
                msg = r.get("message") if isinstance(r.get("message"), dict) else {}
                content, when = msg.get("content"), local_time(r.get("timestamp"))
                if r.get("type") == "user" and not s["prompt"]:
                    if isinstance(content, str):
                        s["prompt"] = content
                    elif isinstance(content, list):
                        s["prompt"] = next((c.get("text") for c in content if isinstance(c, dict)
                                            and c.get("type") == "text"), "") or ""
                for c in content if isinstance(content, list) else []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    name, inp = c.get("name"), c.get("input") or {}
                    if is_log_call(name, inp.get("command")) or is_log_call("", inp.get("file_path")):
                        s["logged"] = True
                    elif name == "Bash" and when and WRITE_CMD_RE.search(str(inp.get("command", ""))):
                        s["edits"].append(when)
                    elif name in CLAUDE_EDIT_TOOLS and when:
                        target = inp.get("file_path") or inp.get("notebook_path")
                        if target:
                            s["edits"].append(when)
                            s["files"].append(str(target))
            yield s


def find_unlogged(day: dt.date, logs: Path):
    """Sessions with file edits on `day` that no agent logged, and that weren't recovered already."""
    already = ""
    day_dir = logs / str(day)
    if day_dir.is_dir():
        already = "".join(f.read_text(encoding="utf-8", errors="ignore") for f in day_dir.glob("*.md"))
    logs_str = str(logs.resolve())
    found = []
    for s in list(codex_sessions(day)) + list(claude_sessions(day)):
        cwd = Path(s["cwd"]).expanduser() if s["cwd"] else None
        edits = [w for w in s["edits"] if w.date() == day]
        files = []
        for f in s["files"]:
            full = (cwd / f) if cwd and not Path(f).is_absolute() else Path(f)
            if not str(full).startswith(logs_str) and Path(f).name not in files:
                files.append(Path(f).name)
        if s["logged"] or not edits or f"session {s['id'][:8]}" in already:
            continue
        repo = git_root(cwd) if cwd and cwd.is_dir() else None
        if not files and repo:                      # changed through the shell: ask git what changed
            since = min(edits) - dt.timedelta(minutes=5)
            until = max(edits) + dt.timedelta(minutes=30)
            out = git_out(repo, "log", f"--since={since:%Y-%m-%d %H:%M}", f"--until={until:%Y-%m-%d %H:%M}",
                          "--name-only", "--format=")
            for f in out.splitlines():
                if f and Path(f).name not in files:
                    files.append(Path(f).name)
        task = (first_line(s["summary"]) or first_line(s["prompt"])
                or ("Changes in " + ", ".join(files[:3]) if files else "Work in " + (cwd.name if cwd else "a session")))
        found.append({"agent": s["agent"], "id": s["id"], "when": max(edits), "task": task,
                      "files": files, "repo": repo or cwd,
                      "project": (repo or cwd).name if (repo or cwd) else "-"})
    return sorted(found, key=lambda x: x["when"])


def cmd_recover(args) -> None:
    check_args(args, flags=("--apply",), value_flags=("--date",), cmd="recover")
    mode, logs, project = locate()
    day = dt.date.fromisoformat(parse_date(args))
    found = find_unlogged(day, logs)
    if not found:
        print(f"Nothing to recover for {day}: every Claude Code and Codex session with edits was logged.")
        return
    print(f"{plural(len(found), 'session')} on {day} changed files but weren't logged:\n")
    for x in found:
        files = ", ".join(x["files"][:5]) + (f" (+{len(x['files']) - 5} more)" if len(x["files"]) > 5 else "")
        print(f"  {x['when']:%H:%M} · {x['project']} · {x['agent']} — {x['task']}")
        if files:
            print(f"           {files}")
    if "--apply" not in args:
        print("\nThis was a preview. Add --apply to put these in your ledger.")
        return
    for x in found:
        files = ", ".join(x["files"][:5]) + (f" (+{len(x['files']) - 5} more)" if len(x["files"]) > 5 else "")
        add_entry(x["agent"], x["task"], "DONE", files, x["project"],
                  f"recovered from {x['agent']} session {x['id'][:8]} (not logged at the time)", "",
                  str(x["repo"]) if x["repo"] else None, when=x["when"])
    print(f"\nAdded {plural(len(found), 'entry')} to your ledger.".replace("entrys", "entries"))


# ---------------------------------------------------------------- MCP server

MCP_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
_DATE = {"type": "string", "description": "YYYY-MM-DD, 'today' or 'yesterday'"}
MCP_TOOLS = [
    {"name": "log_work",
     "description": "Record a task in today's Agent Ledger work log. Call this after you finish any "
                    "task (or when it's blocked or only partly done). Keep it to one line: the outcome.",
     "inputSchema": {"type": "object", "required": ["agent", "task"], "properties": {
         "agent": {"type": "string", "description": "Your name in lowercase: claude, codex, cursor, gemini, ..."},
         "task": {"type": "string", "description": "One line: what was done"},
         "status": {"type": "string", "enum": list(STATUSES), "default": "DONE"},
         "files": {"type": "string", "description": "Main files touched, comma separated"},
         "follow_up": {"type": "string", "description": "What's left to do, if anything"},
         "notes": {"type": "string", "description": "Optional one-line note"},
         "project": {"type": "string", "description": "Project name (default: the git repo's name)"},
         "repo": {"type": "string", "description": "Absolute path of the git repo you worked in"},
         "client": {"type": "string", "description": "Client this work is for, if any"},
         "time": {"type": "string", "description": "Time spent, if known: 45m, 1h30m, 1.5h"}}}},
    {"name": "daily_digest",
     "description": "The Agent Ledger digest for one day: tasks done, partial or blocked, follow-ups "
                    "and git commits. Use it when the user asks what was done today.",
     "inputSchema": {"type": "object", "properties": {
         "date": _DATE,
         "redact": {"type": "boolean", "description": "Hide emails, keys and home paths", "default": False}}}},
    {"name": "work_report",
     "description": "An Agent Ledger work report for a date range (default: the last 7 days), "
                    "grouped by project and day.",
     "inputSchema": {"type": "object", "properties": {
         "from": _DATE, "to": _DATE,
         "project": {"type": "string", "description": "Only this project"},
         "agent": {"type": "string", "description": "Only this agent"},
         "client": {"type": "string", "description": "Only this client"},
         "redact": {"type": "boolean", "description": "Hide emails, keys and home paths", "default": False}}}},
    {"name": "standup",
     "description": "A standup update from the Agent Ledger: what was done on the last working day, "
                    "what's next today, and blockers. Plain text, ready to paste.",
     "inputSchema": {"type": "object", "properties": {
         "date": _DATE, "project": {"type": "string"}, "agent": {"type": "string"},
         "redact": {"type": "boolean", "default": False}}}},
    {"name": "ledger_status",
     "description": "Check the Agent Ledger setup: where logs go, which agent rules are in place, "
                    "and who has logged today.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def mcp_call(name: str, a: dict) -> str:
    import contextlib
    import io
    mode, logs, project = locate()
    if name == "log_work":
        path = add_entry(a.get("agent", ""), a.get("task", ""), a.get("status") or "DONE", a.get("files", ""),
                         a.get("project"), a.get("notes", ""), a.get("follow_up", ""), a.get("repo"),
                         client=a.get("client", ""), time_spent=a.get("time", ""))
        return f"Logged to {short(path)}"
    if name == "daily_digest":
        digest = build_digest(mode, logs, project, to_day(a.get("date") or "today"))
        return redact(digest) if a.get("redact") else digest
    if name == "work_report":
        until = to_day(a.get("to") or "today")
        since = to_day(a["from"]) if a.get("from") else str(dt.date.fromisoformat(until) - dt.timedelta(days=6))
        return build_report(mode, logs, project, since, until, a.get("project"), a.get("agent"),
                            bool(a.get("redact")), a.get("client"))
    if name == "standup":
        return build_standup(mode, logs, project, to_day(a.get("date") or "today"), a.get("project"),
                             a.get("agent"), bool(a.get("redact")))
    if name == "ledger_status":
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_status([])
        return buf.getvalue()
    raise KeyError(name)


def cmd_mcp(args) -> None:
    """A tiny MCP server over stdio (newline-delimited JSON-RPC 2.0). No dependencies."""
    out = sys.stdout

    def send(msg):
        out.write(json.dumps(msg) + "\n")
        out.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if not isinstance(req, dict) or "id" not in req:
            continue                                   # notifications need no reply
        rid, method, params = req["id"], req.get("method"), req.get("params") or {}
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                result = {"protocolVersion": asked if asked in MCP_PROTOCOLS else MCP_PROTOCOLS[0],
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "agent-ledger", "version": __version__},
                          "instructions": "Call log_work after you finish each task, so the user can see "
                                          "what their AI agents did today."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": MCP_TOOLS}
            elif method == "tools/call":
                try:
                    text = mcp_call(params.get("name"), params.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": text}], "isError": False}
                except KeyError:
                    send({"jsonrpc": "2.0", "id": rid,
                          "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}})
                    continue
                except (ValueError, SystemExit) as e:
                    result = {"content": [{"type": "text", "text": f"Agent Ledger: {e}"}], "isError": True}
            else:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}})
                continue
            send({"jsonrpc": "2.0", "id": rid, "result": result})
        except Exception as e:                         # never let one bad request kill the server
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}})


def cmd_mcp_install(args) -> None:
    """Register the MCP server with Cursor and Codex, and show the Claude Code command."""
    check_args(args, cmd="mcp-install")
    locate()                                           # fail early if Agent Ledger isn't set up
    script = str(Path(__file__).resolve())
    print("Agent Ledger MCP server\n")

    cursor = Path.home() / ".cursor" / "mcp.json"
    try:
        data = json.loads(cursor.read_text(encoding="utf-8")) if cursor.exists() else {}
        if not isinstance(data, dict) or not isinstance(data.setdefault("mcpServers", {}), dict):
            raise ValueError
        state = "updated" if "agent-ledger" in data["mcpServers"] else "added"
        data["mcpServers"]["agent-ledger"] = {"command": "python3", "args": [script, "mcp"]}
        cursor.parent.mkdir(parents=True, exist_ok=True)
        cursor.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"  Cursor       {short(cursor):<28} {state}")
    except (OSError, ValueError):
        print(f"  Cursor       {short(cursor):<28} skipped (couldn't read it; add the server by hand)")

    codex = Path.home() / ".codex" / "config.toml"
    block = f'\n[mcp_servers.agent-ledger]\ncommand = "python3"\nargs = [{json.dumps(script)}, "mcp"]\n'
    try:
        text = codex.read_text(encoding="utf-8") if codex.exists() else ""
        if "[mcp_servers.agent-ledger]" in text:
            print(f"  Codex        {short(codex):<28} already there")
        else:
            codex.parent.mkdir(parents=True, exist_ok=True)
            codex.write_text(text + ("\n" if text and not text.endswith("\n") else "") + block, encoding="utf-8")
            print(f"  Codex        {short(codex):<28} added")
    except OSError:
        print(f"  Codex        {short(codex):<28} skipped (couldn't write it)")

    print(f"\n  Claude Code: run this once:")
    print(f'    claude mcp add --scope user agent-ledger -- python3 "{script}" mcp')
    print("\nRestart your agents, then they can call the log_work tool.")


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
    here_repo = git_root(Path.cwd())
    if here_repo:
        net = post_commit_hook(here_repo)
        on = net.exists() and HOOK_BEGIN in net.read_text(encoding="utf-8", errors="ignore")
        print(f"    {ok if on else '·  '} {'Commit net':<15} "
              f"{'on for ' + here_repo.name if on else 'off for ' + here_repo.name + ' (optional: git-hook install)'}")
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

def _main() -> None:
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
    elif cmd == "standup":
        cmd_standup(rest)
    elif cmd == "client":
        cmd_client(rest)
    elif cmd == "hook":
        cmd_hook(rest)
    elif cmd == "update":
        cmd_update(rest)
    elif cmd == "mcp":
        cmd_mcp(rest)
    elif cmd == "git-hook":
        cmd_git_hook(rest)
    elif cmd == "recover":
        cmd_recover(rest)
    elif cmd == "commit-log":
        cmd_commit_log(rest)
    elif cmd == "mcp-install":
        cmd_mcp_install(rest)
    elif cmd == "_refresh":
        cmd_refresh(rest)
    else:
        sys.exit(f"Unknown command: {cmd}\nRun `ledger.py --help` to see the commands. "
                 "(If it's a newer command, your copy may be out of date: run `ledger.py update`.)")


def main() -> None:
    """Entry point. Exits quietly when output is cut short (`| head`) or on Ctrl+C."""
    try:
        _main()
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader went away. Point stdout at devnull so Python's own flush at exit can't fail too.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        sys.exit(1)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
