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

    def test_versions(self):
        self.assertGreater(ledger.vtuple("0.10.0"), ledger.vtuple("0.9.9"))


if __name__ == "__main__":
    unittest.main()
