import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import Mock, patch


SOURCE = Path(__file__).parents[1] / "accx"
ACCX = runpy.run_path(SOURCE)
MODULE = ACCX["machine_response"].__globals__


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.home = Path(self.temp) / "store"
        self.enterContext(patch.dict(os.environ, {
            "ACCX_HOME": str(self.home), "CODEX_HOME": str(Path(self.temp) / "codex"),
            "CLAUDE_CONFIG_DIR": str(Path(self.temp) / "claude"), "ACCX_DESKTOP_NOTIFY": "0",
        }))
        self.provider = ACCX["Provider"]("claude")
        self.path = self.provider.profile_dir("work")
        self.path.mkdir(parents=True)
        (self.path / "credential.json").write_text(json.dumps({
            "claudeAiOauth": {"accessToken": "secret-access", "refreshToken": "secret-refresh"}
        }))
        (self.path / "meta.json").write_text(json.dumps({
            "identity": {"email": "person@example.test", "display_name": "Secret Person", "account_id": "secret-id", "plan": "max"},
            "credential": {"refresh_sha256": "secret-hash"},
        }))
        self.target = {"provider": "claude", "profile_id": ACCX["machine_profile_id"](self.provider, "work")}

    def call(self, method, params=None):
        request = {"version": 1, "id": "probe-1", "method": method, "params": params or {}}
        return ACCX["machine_response"](json.dumps(request).encode())

    def test_snapshot_projects_only_allowed_data_and_keeps_failed_cache(self):
        cached = {"fetched_at": ACCX["now_iso"](), "raw": {
            "five_hour": {"utilization": 21, "resets_at": "2032-01-02T03:04:00Z", "token": "secret-provider"},
            "new_model": {"utilization": None, "resets_at": "2032-01-02T03:04:00Z"},
            "untrusted": {"utilization": {"token": "secret-nested"}},
            "oversized": {"utilization": 10 ** 1000},
            "limits": [{"kind": [], "scope": "malformed", "percent": 30}],
        }}
        self.provider.stored_cache_path("work").write_text(json.dumps(cached))
        opencode = ACCX["Provider"]("opencode").profile_dir("excluded")
        opencode.mkdir(parents=True)
        with patch.dict(MODULE, {"fetch_usage": Mock(return_value=None)}):
            result = self.call("refresh", self.target)["result"]
        self.assertEqual(result["profiles"][0]["status"], "unavailable")
        response = self.call("snapshot")
        profiles = response["result"]["profiles"]
        self.assertEqual(len(profiles), 1)
        item = profiles[0]
        self.assertEqual(item["profile_id"], self.target["profile_id"])
        self.assertFalse(item["login_needed"])
        self.assertTrue(item["usage"]["stale"])
        self.assertEqual(item["usage"]["fetched_at"], cached["fetched_at"].replace("Z", "+00:00"))
        self.assertEqual([w["used_percent"] for w in item["usage"]["windows"]], [21, None, None, None, 30])
        self.assertNotIn("secret-", json.dumps(response))
        self.assertNotIn("person@example.test", json.dumps(response))
        self.assertNotIn("Secret Person", json.dumps(response))
        self.assertNotIn("opencode", json.dumps(response))

    def test_profile_ids_do_not_expose_email_named_profiles(self):
        private_name = "person@example.test"
        hidden = self.provider.profile_dir(private_name)
        hidden.mkdir()
        with redirect_stderr(StringIO()):
            response = self.call("snapshot")
        self.assertNotIn(private_name, json.dumps(response))
        item = next(p for p in response["result"]["profiles"] if p["login_needed"])
        self.assertTrue(item["label"].startswith("Claude Code "))
        self.assertEqual(item["profile_id"], ACCX["machine_profile_id"](self.provider, private_name))

    def test_mutations_and_switch_safety(self):
        billing = {"amount": "12.50", "currency": "USD", "renewal_date": "2031-02-03", "note": "user note"}
        wake = {"enabled": True, "recurrence": "daily", "time": "21:00", "prompt": "user prompt"}
        self.assertEqual(self.call("billing.save", self.target | {"billing": billing})["result"]["status"], "saved")
        self.assertEqual(self.call("wake.save", self.target | {"wake": wake})["result"]["status"], "saved")
        snapshot = self.call("snapshot")["result"]
        self.assertEqual(snapshot["monthly_totals"], {"USD": "12.50"})
        self.assertEqual(snapshot["profiles"][0]["billing"]["note"], "user note")
        self.assertEqual(snapshot["profiles"][0]["wake"]["prompt"], "user prompt")

        switch = Mock()
        with patch.dict(MODULE, {
            "env_overrides": Mock(return_value=[]), "find_active_sessions": Mock(return_value=[{"pid": 3, "command": "secret-command"}]),
            "perform_switch_profile": switch,
        }):
            self.assertEqual(self.call("switch", self.target)["error"], {"code": "active_sessions"})
            self.assertEqual(self.call("switch", self.target | {"kill_sessions": True})["error"], {"code": "invalid_params"})
        switch.assert_not_called()
        with patch.dict(MODULE, {
            "env_overrides": Mock(return_value=[]), "find_active_sessions": Mock(return_value=[]),
            "perform_switch_profile": switch, "start_wake": Mock(return_value="started"),
        }):
            self.assertEqual(self.call("switch", self.target)["result"]["status"], "switched")
            self.assertEqual(self.call("wake.now", self.target)["result"]["status"], "started")
        self.assertEqual(switch.call_args.kwargs, {"kill_sessions": False, "interactive": False})

    def test_protocol_flushes_one_response_and_drops_oversized_input(self):
        probe = {"version": 1, "id": "probe", "method": "snapshot", "params": {}}
        requests = b"{" + b"x" * ACCX["MACHINE_LINE_LIMIT"] + b"}\n"
        requests += b"{invalid json}\n" + json.dumps(probe).encode() + b"\n"
        # Use an empty store to prevent background refresh from reaching the provider.
        env = os.environ | {"ACCX_HOME": str(Path(self.temp) / "empty")}
        result = subprocess.run([sys.executable, str(SOURCE), "machine"], input=requests, env=env,
                                capture_output=True, timeout=5, check=True)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(result.stderr, b"")
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["error"], {"code": "request_too_large"})
        self.assertEqual(responses[1]["error"], {"code": "invalid_request"})
        self.assertEqual(responses[2]["id"], "probe")
        self.assertEqual(responses[2]["result"]["profiles"], [])

    def test_scheduler_skips_missed_occurrences_and_claims_once(self):
        now = datetime(2031, 2, 3, 12, 0, tzinfo=timezone.utc)
        settings = self.provider.stored_settings_path("work")
        settings.write_text(json.dumps({"wake": {"enabled": True, "recurrence": "once", "date": "2031-02-03",
                                                 "time": "11:59", "prompt": "wake"}}))
        process = ACCX["process_due_wakes"]
        start = Mock(return_value="failed: secret-error")
        with patch.dict(MODULE, {"start_wake": start}):
            self.assertEqual(process(now, now - timedelta(seconds=15)), [])
            self.assertEqual(len(process(now, now - timedelta(minutes=2))), 1)
            self.assertEqual(process(now, now - timedelta(minutes=2)), [])
        start.assert_called_once()
        state = self.call("snapshot")["result"]["profiles"][0]["wake"]
        self.assertEqual(state["last_result"], "failed")

    def test_file_lock_refuses_second_process(self):
        script = (
            "import runpy,sys; "
            "m=runpy.run_path(sys.argv[1]); "
            "lock=m['file_lock']('.wake-scheduler.lock', blocking=False); "
            "print(lock.__enter__())"
        )
        def try_other():
            return subprocess.check_output([sys.executable, "-c", script, str(SOURCE)], env=os.environ, timeout=5).strip()

        with ACCX["file_lock"](".wake-scheduler.lock", blocking=False) as owner:
            self.assertTrue(owner)
            self.assertEqual(try_other(), b"False")
        self.assertEqual(try_other(), b"True")

    def test_wake_treats_leading_hyphen_prompt_as_positional(self):
        for name in ("claude", "codex"):
            cmd = ACCX["wake_command"](ACCX["Provider"](name), "--sample-option")
            self.assertEqual(cmd[-2:], ["--", "--sample-option"])

    def test_actual_wake_completion_updates_corresponding_execution(self):
        release = threading.Event()
        popen = Mock(pid=os.getpid())
        popen.wait.side_effect = lambda: 0 if release.wait(2) else 1
        wake = {"prompt": "wake"}
        with patch("shutil.which", return_value="/bin/claude"), patch("subprocess.Popen", return_value=popen):
            self.assertEqual(ACCX["start_wake"](self.provider, "work", wake, notify=False), "started")
            self.assertEqual(ACCX["start_wake"](self.provider, "work", wake, notify=False), "already_running")
            release.set()
            worker = next(t for t in threading.enumerate() if t.name == f"accx-wake-{os.getpid()}")
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        state = ACCX["wake_runtime_state"](self.provider, "work")
        self.assertEqual(state["last_result"], "succeeded")
