"""End-to-end tests for Agent Ledger. Standard library only:

    python3 -m unittest discover -s tests -v

Every test runs ledger.py in a throwaway home folder, so nothing on your machine is touched.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "ledger.py"
sys.path.insert(0, str(REPO))
import ledger  # noqa: E402

TODAY = str(dt.date.today())


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="agent-ledger-test-"))
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="t@example.com")
        for k in ("XDG_CONFIG_HOME", "AGENT_LEDGER_HOME", "CLAUDE_PROJECT_DIR"):
            self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_cli(self, *args, script=SCRIPT, cwd=None, stdin="", ok=True):
        r = subprocess.run([sys.executable, str(script), *args], cwd=str(cwd or self.home),
                           env=self.env, input=stdin, capture_output=True, text=True, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, f"{args} failed:\n{r.stdout}\n{r.stderr}")
        return r

    def git_repo(self, name):
        repo = self.home / name
        repo.mkdir()
        for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", f"start {name}"]):
            subprocess.run(["git", *cmd], cwd=repo, env=self.env, check=True)
        return repo

    @property
    def gl(self):
        return self.home / "agent-ledger"


class TestBasics(LedgerTestCase):
    def test_version(self):
        self.assertIn(ledger.__version__, self.run_cli("--version").stdout)

    def test_unknown_command_and_option_fail_clearly(self):
        r = self.run_cli("weeks", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("update", r.stderr)
        r = self.run_cli("today", "--opne", ok=False)
        self.assertIn("Unknown option", r.stderr)

    def test_output_cut_short_is_quiet(self):
        # `| head -1` closes the pipe early; that must not print a traceback.
        for args in (["--help"], ["init", "--global", "--no-hook"]):
            r = subprocess.run(f"{sys.executable} {SCRIPT} {' '.join(args)} | head -1", shell=True,
                               env=self.env, cwd=str(self.home), capture_output=True, text=True, timeout=60)
            self.assertNotIn("Traceback", r.stderr)
            self.assertNotIn("BrokenPipeError", r.stderr)

    def test_help(self):
        self.assertIn("ledger.py log", self.run_cli("--help").stdout)


class TestGlobalMode(LedgerTestCase):
    def setUp(self):
        super().setUp()
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
        self.run_cli("init", "--global")

    def test_init_writes_rules_and_keeps_settings(self):
        self.assertIn("agent-ledger:start", (self.home / ".claude" / "CLAUDE.md").read_text())
        self.assertIn("agent-ledger:start", (self.home / ".codex" / "AGENTS.md").read_text())
        data = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertEqual(data["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(len(data["hooks"]["Stop"]), 1)

    def test_init_is_idempotent(self):
        self.run_cli("init", "--global")
        self.assertEqual((self.home / ".claude" / "CLAUDE.md").read_text().count("agent-ledger:start"), 1)
        data = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertEqual(len(data["hooks"]["Stop"]), 1)

    def test_log_today_and_status(self):
        repo = self.git_repo("client-app")
        script = self.gl / "ledger.py"
        self.run_cli("log", "--agent", "Codex", "--task", "Build  login\nscreen", "--files", "Login.kt",
                     script=script, cwd=repo)
        self.run_cli("log", "--agent", "claude", "--task", "Payments", "--status", "blocked",
                     "--follow-up", "Ask for keys", script=script, cwd=repo)
        text = (self.gl / TODAY / "codex.md").read_text()
        self.assertIn("· client-app · DONE", text)
        self.assertIn("- Task: Build login screen", text)
        self.assertIn("- Repo: ~/client-app", text)

        out = self.run_cli("today", script=script).stdout
        self.assertIn("2 tasks", out)
        self.assertIn("1 blocked", out)
        self.assertIn("Ask for keys", out)
        self.assertIn("start client-app", out)          # the repo's commit is picked up

        status = self.run_cli("status", script=script).stdout
        self.assertIn("hook on", status)
        self.assertIn(ledger.__version__, status)

    def test_bad_status_value_is_rejected(self):
        r = self.run_cli("log", "--agent", "x", "--task", "y", "--status", "nope",
                         script=self.gl / "ledger.py", ok=False)
        self.assertNotEqual(r.returncode, 0)


class TestHook(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        self.script = self.gl / "ledger.py"

    def transcript(self, *steps):
        path = self.home / "t.jsonl"
        lines = []
        for name, value in steps:
            inp = {"command": value} if name == "Bash" else {"file_path": value}
            lines.append(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": name, "input": inp}]}}))
        path.write_text("\n".join(lines) + "\n")
        return path

    def hook(self, payload):
        return self.run_cli("hook", "claude", script=self.script, stdin=payload).stdout

    def test_reminds_after_unlogged_edit(self):
        t = self.transcript(("Edit", str(self.home / "app.kt")))
        self.assertIn('"decision": "block"', self.hook(json.dumps({"transcript_path": str(t)})))

    def test_silent_after_logging(self):
        t = self.transcript(("Edit", str(self.home / "app.kt")),
                            ("Bash", 'python3 ~/agent-ledger/ledger.py log --agent claude --task "x"'))
        self.assertEqual(self.hook(json.dumps({"transcript_path": str(t)})), "")
        t = self.transcript(("Edit", str(self.home / "app.kt")),
                            ("Write", str(self.gl / TODAY / "claude.md")))
        self.assertEqual(self.hook(json.dumps({"transcript_path": str(t)})), "")

    def test_never_loops_or_crashes(self):
        t = self.transcript(("Edit", str(self.home / "app.kt")))
        self.assertEqual(self.hook(json.dumps({"transcript_path": str(t), "stop_hook_active": True})), "")
        self.assertEqual(self.hook("not json"), "")
        self.assertEqual(self.hook(json.dumps({"transcript_path": "/nope"})), "")


class TestReports(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        yesterday = str(dt.date.today() - dt.timedelta(days=1))
        old = str(dt.date.today() - dt.timedelta(days=30))
        for day, agent, body in [
            (yesterday, "claude", "## 10:00 · app-a · DONE\n- Task: Mailed dev@example.com\n"
                                  "- Files: /Users/someone/app-a/Main.kt\n"),
            (TODAY, "codex", "## 09:00 · app-b · BLOCKED\n- Task: Key sk_live_abcdefghijklmnop123 failed\n"
                             "- Follow-up: New keys\n"),
            (old, "codex", "## 09:00 · app-a · DONE\n- Task: Old work\n"),
        ]:
            (self.gl / day).mkdir(parents=True, exist_ok=True)
            (self.gl / day / f"{agent}.md").write_text(body)
        self.script = self.gl / "ledger.py"

    def test_week_covers_last_seven_days_only(self):
        out = self.run_cli("week", "--print", script=self.script).stdout
        self.assertIn("2 tasks", out)
        self.assertNotIn("Old work", out)

    def test_filters(self):
        out = self.run_cli("report", "--from", "yesterday", "--project", "APP-A", "--print",
                           script=self.script).stdout
        self.assertIn("1 task", out)
        self.assertNotIn("app-b", out.split("Projects:")[1].split("\n")[0])
        out = self.run_cli("report", "--agent", "codex", "--print", script=self.script).stdout
        self.assertIn("1 task", out)

    def test_redact_hides_private_details_in_md_and_html(self):
        self.run_cli("week", "--redact", "--html", script=self.script)
        reports = list((self.gl / "reports").glob("*"))
        self.assertEqual({p.suffix for p in reports}, {".md", ".html"})
        for p in reports:
            text = p.read_text()
            self.assertNotIn("dev@example.com", text)
            self.assertNotIn("sk_live_", text)
            self.assertNotIn("/Users/someone", text)
            self.assertIn("[email]", text)

    def test_digest_html(self):
        self.run_cli("today", "--html", script=self.script)
        page = (self.gl / TODAY / "DIGEST.html").read_text()
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("Daily Digest", page)

    def test_html_charts(self):
        self.run_cli("week", "--html", script=self.script)
        page = next((self.gl / "reports").glob("*.html")).read_text()
        self.assertIn("Tasks per day", page)
        self.assertEqual(page.count("class='col'"), 7)                    # one column per day, empty days too
        self.assertIn("Tasks per agent", page)                             # claude and codex both logged
        self.assertIn("data-tip='claude: 1 task'", page)
        self.run_cli("today", "--html", script=self.script)
        digest = (self.gl / TODAY / "DIGEST.html").read_text()
        self.assertNotIn("Tasks per day", digest)                          # one day: no timeline

    def test_bad_range(self):
        r = self.run_cli("report", "--from", "today", "--to", "yesterday", script=self.script, ok=False)
        self.assertNotEqual(r.returncode, 0)


class TestProjectMode(LedgerTestCase):
    def test_private_setup_leaves_git_clean(self):
        repo = self.git_repo("app")
        self.run_cli("init", "--project", str(repo), "--private")
        self.run_cli("log", "--agent", "claude", "--task", "x", script=repo / "ledger" / "ledger.py", cwd=repo)
        self.run_cli("today", "--html", script=repo / "ledger" / "ledger.py", cwd=repo)
        status = subprocess.run(["git", "status", "--short"], cwd=repo, env=self.env,
                                capture_output=True, text=True).stdout
        self.assertEqual(status, "")
        settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
        self.assertIn("$CLAUDE_PROJECT_DIR", settings["hooks"]["Stop"][0]["hooks"][0]["command"])


class TestUpdate(LedgerTestCase):
    def test_update_refreshes_an_old_copy(self):
        self.run_cli("init", "--global")
        installed = self.gl / "ledger.py"
        old = installed.read_text().replace(f'__version__ = "{ledger.__version__}"', '__version__ = "0.0.1"')
        installed.write_text(old + "\n# old copy\n")
        out = self.run_cli("update").stdout
        self.assertIn(f"0.0.1 → {ledger.__version__}", out)
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        self.assertIn("already up to date", self.run_cli("update").stdout)


class TestMcp(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        self.repo = self.git_repo("client-app")

    def rpc(self, *messages):
        lines = "".join(json.dumps(m) + "\n" for m in messages)
        out = self.run_cli("mcp", script=self.gl / "ledger.py", cwd=self.repo, stdin=lines).stdout
        return {r["id"]: r for r in map(json.loads, out.splitlines())}

    def test_handshake_and_tools(self):
        r = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "test", "version": "1"}}},
                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                     {"jsonrpc": "2.0", "id": 3, "method": "ping"})
        self.assertEqual(r[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r[1]["result"]["serverInfo"]["name"], "agent-ledger")
        names = {t["name"] for t in r[2]["result"]["tools"]}
        self.assertEqual(names, {"log_work", "daily_digest", "work_report", "standup", "ledger_status"})
        self.assertEqual(r[3]["result"], {})
        self.assertEqual(len(r), 3)                     # no reply to the notification

    def test_log_work_then_digest(self):
        r = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                          "name": "log_work", "arguments": {"agent": "Cursor", "task": "Wired up MCP",
                                                            "files": "ledger.py", "follow_up": "Docs"}}},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "daily_digest", "arguments": {}}})
        self.assertFalse(r[1]["result"]["isError"])
        self.assertIn("cursor.md", r[1]["result"]["content"][0]["text"])
        digest = r[2]["result"]["content"][0]["text"]
        self.assertIn("1 task", digest)
        self.assertIn("client-app", digest)           # project taken from the server's repo
        self.assertIn("Docs", digest)

    def test_errors_are_reported_not_fatal(self):
        r = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "log_work", "arguments": {"agent": "x", "task": "y", "status": "nope"}}},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope"}},
                     {"jsonrpc": "2.0", "id": 3, "method": "nope"},
                     {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "work_report", "arguments": {"from": "yesterday"}}})
        self.assertTrue(r[1]["result"]["isError"])
        self.assertEqual(r[2]["error"]["code"], -32602)
        self.assertEqual(r[3]["error"]["code"], -32601)
        self.assertIn("Work Report", r[4]["result"]["content"][0]["text"])

    def test_mcp_install_merges_existing_configs(self):
        cursor = self.home / ".cursor" / "mcp.json"
        cursor.parent.mkdir(parents=True)
        cursor.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        codex = self.home / ".codex" / "config.toml"
        codex.write_text('model = "o4"\n')
        self.run_cli("mcp-install", script=self.gl / "ledger.py")
        self.run_cli("mcp-install", script=self.gl / "ledger.py")      # safe to repeat
        servers = json.loads(cursor.read_text())["mcpServers"]
        self.assertIn("other", servers)
        self.assertEqual(servers["agent-ledger"]["args"][-1], "mcp")
        text = codex.read_text()
        self.assertTrue(text.startswith('model = "o4"'))
        self.assertEqual(text.count("[mcp_servers.agent-ledger]"), 1)


class TestCommitSafetyNet(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        self.script = self.gl / "ledger.py"
        self.repo = self.git_repo("client-app")
        self.hook = self.repo / ".git" / "hooks" / "post-commit"
        self.hook.write_text("#!/bin/sh\necho mine\n")
        self.hook.chmod(0o755)
        self.run_cli("git-hook", "install", script=self.script, cwd=self.repo)

    def commit(self, name):
        (self.repo / name).write_text("x")
        for cmd in (["add", name], ["commit", "-q", "-m", f"add {name}"]):
            subprocess.run(["git", *cmd], cwd=self.repo, env=self.env, check=True, capture_output=True)

    def git_entries(self):
        f = self.gl / TODAY / "git.md"
        return f.read_text() if f.exists() else ""

    def test_unlogged_commit_is_logged(self):
        self.commit("a.kt")
        text = self.git_entries()
        self.assertIn("Commit: add a.kt", text)
        self.assertIn("- Files: a.kt", text)
        self.assertIn("- Repo: ~/client-app", text)

    def test_commit_after_agent_logged_is_skipped(self):
        self.run_cli("log", "--agent", "codex", "--task", "Built a", script=self.script, cwd=self.repo)
        self.commit("b.kt")
        self.assertEqual(self.git_entries(), "")

    def test_existing_hook_is_kept_and_uninstall_is_clean(self):
        self.run_cli("git-hook", "install", script=self.script, cwd=self.repo)     # idempotent
        text = self.hook.read_text()
        self.assertIn("echo mine", text)
        self.assertEqual(text.count("agent-ledger >>>"), 1)
        self.run_cli("git-hook", "uninstall", str(self.repo), script=self.script)
        self.assertEqual(self.hook.read_text().strip(), "#!/bin/sh\necho mine")

    def test_status_shows_it(self):
        self.assertIn("on for client-app", self.run_cli("status", script=self.script, cwd=self.repo).stdout)


class TestRecover(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        self.script = self.gl / "ledger.py"
        self.repo = self.git_repo("app")
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.ts = now.isoformat().replace("+00:00", "Z")
        folder = self.home / ".codex" / "sessions" / dt.date.today().strftime("%Y/%m/%d")
        folder.mkdir(parents=True)
        self.codex_dir = folder

    def codex(self, name, *calls, summary="Added the settings screen."):
        recs = [{"timestamp": self.ts, "type": "session_meta", "payload": {"cwd": str(self.repo)}},
                {"timestamp": self.ts, "type": "response_item", "payload": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": "do it"}]}}]
        recs += [{"timestamp": self.ts, "type": "response_item",
                  "payload": {"type": "custom_tool_call", "name": "exec", "input": c}} for c in calls]
        recs.append({"timestamp": self.ts, "type": "event_msg",
                     "payload": {"type": "task_complete", "last_agent_message": summary}})
        path = self.codex_dir / f"rollout-x-{name:0>36}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    def claude(self, *tool_uses, summary=None):
        folder = self.home / ".claude" / "projects" / "-app"
        folder.mkdir(parents=True, exist_ok=True)
        recs = [{"type": "user", "timestamp": self.ts, "cwd": str(self.repo),
                 "message": {"role": "user", "content": "Fix the login crash"}}]
        recs += [{"type": "assistant", "timestamp": self.ts, "cwd": str(self.repo), "message": {
            "role": "assistant", "content": [{"type": "tool_use", "name": n, "input": i}]}} for n, i in tool_uses]
        if summary:
            recs.append({"type": "summary", "summary": summary})
        (folder / "claude-session-1.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    def test_finds_unlogged_sessions_and_skips_logged_ones(self):
        self.codex("a", 'await tools.apply_patch(`*** Begin Patch\n*** Update File: app/Settings.kt\n@@`)')
        self.codex("b", 'await tools.exec_command({cmd: "sed -i s/a/b/ x.kt"})', summary="Renamed x.")
        self.codex("c", 'await tools.exec_command({cmd: "git status"})', summary="Just looked around.")
        self.codex("d", 'await tools.apply_patch(`*** Update File: y.kt`)',
                   'await tools.exec_command({cmd: "python3 ledger/ledger.py log --agent codex --task y"})')
        self.claude(("Edit", {"file_path": str(self.repo / "Login.kt")}), summary="Fixed login crash")
        out = self.run_cli("recover", script=self.script).stdout
        self.assertIn("3 sessions", out)
        self.assertIn("Added the settings screen.", out)
        self.assertIn("Settings.kt", out)
        self.assertIn("Renamed x.", out)
        self.assertIn("claude — Fixed login crash", out)
        self.assertNotIn("Just looked around", out)        # read-only session
        self.assertIn("preview", out)
        self.assertFalse((self.gl / TODAY / "codex.md").exists())

    def test_apply_writes_once(self):
        self.codex("a", 'await tools.apply_patch(`*** Update File: app/Settings.kt\n`)')
        self.run_cli("recover", "--apply", script=self.script)
        text = (self.gl / TODAY / "codex.md").read_text()
        self.assertIn("- Task: Added the settings screen.", text)
        self.assertIn("recovered from codex session", text)
        self.assertIn("- Repo: ~/app", text)
        self.assertIn("Nothing to recover", self.run_cli("recover", script=self.script).stdout)

    def test_hand_written_ledger_entry_counts_as_logged(self):
        self.codex("e", 'await tools.exec_command({cmd: "echo x > a.kt"})',
                   f'await tools.exec_command({{cmd: "cat >> ~/agent-ledger/{TODAY}/codex.md"}})')
        self.assertIn("Nothing to recover", self.run_cli("recover", script=self.script).stdout)


class TestStandup(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        self.script = self.gl / "ledger.py"
        self.prev = str(dt.date.today() - dt.timedelta(days=3))      # e.g. a Friday before a weekend
        for day, agent, body in [
            (self.prev, "codex", "## 10:00 · app · DONE\n- Task: Built settings, mailed a@b.io\n"
                                 "## 15:00 · app · PARTIAL\n- Task: Auth screens\n- Follow-up: Signup validation\n"
                                 "## 16:00 · pay · BLOCKED\n- Task: Payments\n- Follow-up: keys\n"),
            (TODAY, "claude", "## 09:00 · app · DONE\n- Task: Profile editor\n"),
        ]:
            (self.gl / day).mkdir(parents=True, exist_ok=True)
            (self.gl / day / f"{agent}.md").write_text(body)

    def test_sections(self):
        out = self.run_cli("standup", script=self.script).stdout
        last, today, blockers = out.split("\n\n")[1:4]
        self.assertIn("Last working day", last)
        self.assertIn("Built settings", last)
        self.assertIn("Auth screens, in progress", last)
        self.assertIn("Done: Profile editor", today)
        self.assertIn("Signup validation", today)
        self.assertIn("Continue: Auth screens", today)
        self.assertNotIn("keys (pay)", today)                 # blocker follow-ups stay in Blockers
        self.assertIn("Payments (needs: keys) (pay)", blockers)

    def test_filters_and_redact(self):
        out = self.run_cli("standup", "--project", "pay", "--redact", script=self.script).stdout
        self.assertNotIn("Built settings", out)
        self.assertIn("Payments", out)
        out = self.run_cli("standup", "--redact", script=self.script).stdout
        self.assertNotIn("a@b.io", out)

    def test_empty(self):
        out = self.run_cli("standup", "--date", "2020-01-01", script=self.script).stdout
        self.assertIn("Nothing logged", out)
        self.assertIn("None", out)


class TestClientTime(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init", "--global")
        self.script = self.gl / "ledger.py"
        (self.gl / TODAY).mkdir(parents=True, exist_ok=True)
        (self.gl / TODAY / "claude.md").write_text(
            "## 09:00 · client-app · DONE\n- Task: CI\n\n"
            "## 10:10 · client-app · DONE\n- Task: Auth\n\n"
            "## 11:00 · client-app · BLOCKED\n- Task: Payments\n- Time: 45m\n\n"
            "## 16:00 · client-app · DONE\n- Task: Release fix\n")

    def test_estimates_and_logged_time(self):
        out = self.run_cli("report", "--from", "today", "--print", script=self.script).stdout
        self.assertIn("Auth (~1h 10m)", out)            # gap since the previous entry
        self.assertIn("Payments (45m)", out)            # logged time wins over the estimate
        self.assertNotIn("Release fix (", out)          # 5h gap is over the cap: no estimate
        self.assertNotIn("CI (", out)                   # first entry of the day: no estimate
        self.assertIn("**Total: 1h 55m** (45m logged, 1h 10m estimated)", out)

    def test_client_mapping_and_filter(self):
        self.run_cli("client", "client-app", "Acme Corp", script=self.script)
        self.assertIn("Acme Corp", self.run_cli("client", script=self.script).stdout)
        repo = self.git_repo("other")
        self.run_cli("log", "--agent", "codex", "--task", "Other work", "--client", "Beta", "--time", "1.5h",
                     script=self.script, cwd=repo)
        out = self.run_cli("report", "--from", "today", "--client", "acme corp", "--print", script=self.script).stdout
        self.assertIn("Client: acme corp", out)
        self.assertIn("4 tasks", out)
        self.assertNotIn("Other work", out)
        out = self.run_cli("report", "--from", "today", "--client", "beta", "--print", "--html",
                           script=self.script).stdout
        self.assertIn("Other work (1h 30m)", out)
        page = next((self.gl / "reports").glob("*_beta.html")).read_text()
        self.assertIn("1h 30m", page)
        self.run_cli("client", "client-app", "--remove", script=self.script)
        self.assertIn("No clients yet", self.run_cli("client", script=self.script).stdout)

    def test_bad_time_is_rejected(self):
        r = self.run_cli("log", "--agent", "x", "--task", "y", "--time", "soon", script=self.script, ok=False)
        self.assertIn("can't read time", r.stderr)


class TestUnits(unittest.TestCase):
    def test_redact(self):
        r = ledger.redact
        self.assertEqual(r("mail a.b@x.io now"), "mail [email] now")
        self.assertEqual(r("key sk-abcdefghijklmnopqrstu"), "key [secret]")
        self.assertEqual(r("ghp_" + "a" * 30), "[secret]")
        self.assertEqual(r("/Users/naveed/code/a.kt"), "~/code/a.kt")
        self.assertEqual(r("src/main/java/com/example/app/settings/SettingsScreen.kt"),
                         "src/main/java/com/example/app/settings/SettingsScreen.kt")

    def test_parse_log_is_forgiving(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            f = tmp / "codex.md"
            f.write_text("## 9:05 - my-app - blocked\n- Task: A\n## free heading\n- Notes: n\n")
            e = ledger.parse_log(f)
            self.assertEqual((e[0]["time"], e[0]["project"], e[0]["status"]), ("09:05", "my-app", "BLOCKED"))
            self.assertEqual(e[1]["task"], "free heading")
        finally:
            shutil.rmtree(tmp)

    def test_time_parsing(self):
        p = ledger.parse_minutes
        self.assertEqual([p("45"), p("45m"), p("1h30m"), p("1h 30m"), p("1.5h"), p("2 hours"), p("soon")],
                         [45, 45, 90, 90, 90, 120, None])
        self.assertEqual(ledger.fmt_minutes(95), "1h 35m")

    def test_versions(self):
        self.assertGreater(ledger.vtuple("0.10.0"), ledger.vtuple("0.9.9"))


if __name__ == "__main__":
    unittest.main()
