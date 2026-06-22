import base64
import json
import os
import runpy
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


ACCX = runpy.run_path(Path(__file__).parents[1] / "accx")


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class CodexUsageTests(unittest.TestCase):
    def test_fetch_usage_sends_account_header(self):
        request = Mock(return_value={"rate_limit": {}})
        ACCX["http_get_json"] = request
        fetch_usage = ACCX["fetch_usage"]
        fetch_usage.__globals__["http_get_json"] = request

        result = fetch_usage(
            ACCX["Provider"]("codex"),
            {"tokens": {"access_token": "access", "account_id": "account-123"}},
        )

        self.assertEqual(result, {"rate_limit": {}})
        request.assert_called_once_with(
            "https://chatgpt.com/backend-api/wham/usage",
            {
                "Authorization": "Bearer access",
                "User-Agent": "codex-cli",
                "ChatGPT-Account-Id": "account-123",
            },
        )

    def test_account_id_falls_back_to_jwt_claim(self):
        token = jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "account-456"}})

        self.assertEqual(
            ACCX["codex_account_id"]({"tokens": {"access_token": token}}),
            "account-456",
        )

    def test_business_plan_name_is_shortened(self):
        token = jwt({
            "https://api.openai.com/auth": {
                "chatgpt_plan_type": "self_serve_business_usage_based"
            }
        })

        metadata = ACCX["codex_metadata"](
            ACCX["Provider"]("codex"), {"tokens": {"access_token": token}}
        )

        self.assertEqual(metadata["identity"]["plan"], "business")

    def test_refresh_codex_credential_rotates_tokens(self):
        request = Mock(
            return_value={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "id_token": "new-id",
            }
        )
        refresh = ACCX["refresh_codex_credential"]
        refresh.__globals__["http_post_form_json"] = request
        credential = {
            "tokens": {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "id_token": "old-id",
            }
        }

        self.assertTrue(refresh(credential))
        self.assertEqual(
            credential["tokens"],
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "id_token": "new-id",
            },
        )
        request.assert_called_once_with(
            ACCX["CODEX_TOKEN_URL"],
            {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh",
                "client_id": ACCX["CODEX_CLIENT_ID"],
            },
        )

    def test_expired_codex_token_needs_refresh(self):
        token = jwt({"exp": int(time.time()) - 60})

        self.assertTrue(ACCX["codex_token_needs_refresh"]({"tokens": {"access_token": token}}))


class DashboardDataTests(unittest.TestCase):
    def test_monthly_renewal_preserves_end_of_month_anchor(self):
        advance = ACCX["advance_monthly_renewal"]

        self.assertEqual(advance("2026-01-31", 31, today=date(2026, 3, 1)), "2026-03-31")
        self.assertEqual(advance("2028-01-31", 31, today=date(2028, 2, 1)), "2028-02-29")

    def test_billing_validates_and_formats_amount(self):
        normalize = ACCX["normalize_billing_input"]

        result = normalize(
            {"renewal_date": "2026-06-30", "amount": "20", "currency": "usd", "note": "GitHub Student üzerinden aldım"},
            today=date(2026, 6, 20),
        )

        self.assertEqual(result["amount"], "20.00")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["anchor_day"], 30)
        self.assertEqual(result["note"], "GitHub Student üzerinden aldım")
        with self.assertRaisesRegex(ValueError, "two decimal"):
            normalize(
                {"renewal_date": "2026-06-30", "amount": "1.234", "currency": "USD"},
                today=date(2026, 6, 20),
            )

    def test_wake_schedule_calculates_daily_and_one_time_windows(self):
        local = timezone(timedelta(hours=3))
        now = datetime(2026, 6, 20, 10, 0, tzinfo=local)
        daily = ACCX["normalize_wake_input"]({
            "enabled": True, "recurrence": "daily", "time": "09:00", "prompt": "hello",
            "last_run_at": now.isoformat(),
        })
        once = ACCX["normalize_wake_input"]({
            "enabled": True, "recurrence": "once", "date": "2026-06-21", "time": "12:30", "prompt": "hello",
        })

        self.assertEqual(ACCX["wake_candidate"](daily, now).isoformat(), "2026-06-21T09:00:00+03:00")
        preview = ACCX["wake_public_data"](once, now)
        self.assertEqual(preview["next_run_at"], "2026-06-21T12:30:00+03:00")
        self.assertEqual(preview["expected_reset_at"], "2026-06-21T17:30:00+03:00")

    def test_due_one_time_wake_starts_and_disables_itself(self):
        now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ACCX_HOME": temp}):
            profile_dir = Path(temp) / "claude" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "access"}}))
            (profile_dir / "meta.json").write_text(json.dumps({"identity": {}, "credential": {}}))
            (profile_dir / "settings.json").write_text(json.dumps({"wake": {
                "enabled": True, "recurrence": "once", "date": "2026-06-20", "time": "11:00", "prompt": "hello"
            }}))
            process = ACCX["process_due_wakes"]
            with patch.dict(process.__globals__, {"start_wake": Mock(return_value="started")}):
                results = process(now)
            saved = json.loads((profile_dir / "settings.json").read_text())["wake"]

        self.assertEqual(results, [{"provider": "claude", "profile": "work", "result": "started"}])
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["last_result"], "started")

    def test_failed_one_time_wake_remains_enabled_for_retry(self):
        now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ACCX_HOME": temp}):
            profile_dir = Path(temp) / "claude" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text("{}")
            (profile_dir / "settings.json").write_text(json.dumps({"wake": {
                "enabled": True, "recurrence": "once", "date": "2026-06-20",
                "time": "11:00", "prompt": "hello"
            }}))
            process = ACCX["process_due_wakes"]
            with patch.dict(process.__globals__, {"start_wake": Mock(return_value="failed: command not found")}):
                process(now)
            saved = json.loads((profile_dir / "settings.json").read_text())["wake"]

        self.assertTrue(saved["enabled"])
        self.assertIsNone(saved["last_run_at"])
        self.assertEqual(saved["last_result"], "failed: command not found")

    def test_wake_commands_are_non_interactive(self):
        self.assertEqual(
            ACCX["wake_command"](ACCX["Provider"]("claude"), "ping"),
            ["claude", "-p", "ping", "--model", "haiku"],
        )
        self.assertEqual(
            ACCX["wake_command"](ACCX["Provider"]("codex"), "ping"),
            [
                "codex", "exec", "--skip-git-repo-check", "--model",
                "gpt-5.1-codex-mini", "ping",
            ],
        )

    def test_wake_uses_isolated_profile_credentials(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ACCX_HOME": temp}):
            profile_dir = Path(temp) / "codex" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text('{"tokens":{"access_token":"secret"}}')
            with patch("shutil.which", return_value="/usr/bin/codex"), patch("subprocess.Popen") as popen:
                result = ACCX["start_wake"](
                    ACCX["Provider"]("codex"), "work", {"prompt": "ping"}
                )

            runtime = profile_dir / ".wake-runtime"
            self.assertEqual(result, "started")
            self.assertTrue((runtime / "auth.json").exists())
            self.assertEqual(popen.call_args.kwargs["env"]["CODEX_HOME"], str(runtime))
            self.assertEqual(popen.call_args.kwargs["stderr"], ACCX["subprocess"].STDOUT)
            events = [json.loads(line) for line in (Path(temp) / "wake.log").read_text().splitlines()]
            self.assertEqual(events[-1]["event"], "wake_started")
            self.assertEqual(events[-1]["provider"], "codex")

    def test_wake_monitor_returns_plans_events_and_output_without_credentials(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ACCX_HOME": temp}):
            profile_dir = Path(temp) / "claude" / "work"
            runtime_dir = profile_dir / ".wake-runtime"
            runtime_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text('{"secret":"token"}')
            (profile_dir / "settings.json").write_text(json.dumps({"wake": {
                "enabled": True, "recurrence": "daily", "time": "08:15", "prompt": "ping"
            }}))
            (runtime_dir / "wake.log").write_text("first line\nlast line\n")
            (Path(temp) / "wake.log").write_text(
                json.dumps({"timestamp": "2026-06-20T08:00:00Z", "event": "wake_due"}) + "\n" +
                json.dumps({"timestamp": "2026-06-20T08:01:00Z", "event": "wake_completed", "exit_code": 0}) + "\n"
            )

            data = ACCX["wake_monitor_data"]()

        self.assertEqual(data["plans"][0]["model"], "haiku")
        self.assertEqual(data["plans"][0]["output"], "first line\nlast line")
        self.assertEqual(data["events"][0]["event"], "wake_completed")
        self.assertNotIn("token", json.dumps(data))


class DashboardHttpTests(unittest.TestCase):
    def test_disconnected_client_does_not_raise_while_sending(self):
        handler = object.__new__(ACCX["DashboardHandler"])
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError
        handler.close_connection = False

        handler.send_bytes(200, b"{}", "application/json")

        self.assertTrue(handler.close_connection)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "ACCX_HOME": self.temp.name,
                "CLAUDE_CONFIG_DIR": str(Path(self.temp.name) / "live-claude"),
                "CODEX_HOME": str(Path(self.temp.name) / "live-codex"),
            },
        )
        self.env.start()
        profile_dir = Path(self.temp.name) / "claude" / "work"
        profile_dir.mkdir(parents=True)
        (profile_dir / "credential.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "access", "refreshToken": "refresh"}}))
        (profile_dir / "meta.json").write_text(json.dumps({"identity": {"email": "work@example.com", "plan": "pro"}, "credential": {}}))

        state = ACCX["DashboardState"]()
        handler_base = ACCX["DashboardHandler"]

        class Handler(handler_base):
            pass

        Handler.state = state
        Handler.asset_root = Path(__file__).parents[1] / "web"
        self.state = state
        self.server = ACCX["ThreadingHTTPServer"](("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.env.stop()
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, token=None):
        headers = {}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-ACCX-Token"] = token
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data=body, method=method, headers=headers))

    def test_dashboard_lists_profiles_without_credentials(self):
        with self.request("/api/dashboard") as response:
            data = json.load(response)

        self.assertEqual(data["profiles"][0]["email"], "work@example.com")
        self.assertNotIn("credential", data["profiles"][0])
        self.assertNotIn("refreshToken", json.dumps(data))

    def test_wake_page_and_monitor_api_are_available(self):
        with self.request("/wake.html") as response:
            page = response.read().decode()
        with self.request("/api/wakes") as response:
            data = json.load(response)

        self.assertIn("Uyandırma planları", page)
        self.assertEqual(data["plans"], [])
        self.assertIn("events", data)

    def test_billing_mutation_requires_token_and_persists(self):
        payload = {"renewal_date": "2026-06-30", "amount": "18.50", "currency": "EUR", "note": "İş hesabı"}
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request("/api/profiles/claude/work/billing", method="PUT", data=payload)
        self.assertEqual(denied.exception.code, 403)

        with self.request("/api/profiles/claude/work/billing", method="PUT", data=payload, token=self.state.token) as response:
            data = json.load(response)

        self.assertEqual(data["billing"]["amount"], "18.50")
        saved = json.loads((Path(self.temp.name) / "claude" / "work" / "settings.json").read_text())
        self.assertEqual(saved["billing"]["currency"], "EUR")
        self.assertEqual(saved["billing"]["note"], "İş hesabı")

    def test_wake_mutation_persists_per_profile(self):
        payload = {"enabled": True, "recurrence": "daily", "time": "08:15", "prompt": "Say hello"}
        with self.request("/api/profiles/claude/work/wake", method="PUT", data=payload, token=self.state.token) as response:
            data = json.load(response)

        self.assertEqual(data["wake"]["recurrence"], "daily")
        self.assertEqual(data["dashboard"]["profiles"][0]["wake"]["prompt"], "Say hello")
        saved = json.loads((Path(self.temp.name) / "claude" / "work" / "settings.json").read_text())
        self.assertEqual(saved["wake"]["time"], "08:15")


if __name__ == "__main__":
    unittest.main()
