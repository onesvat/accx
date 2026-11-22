import base64
import io
import json
import os
import runpy
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


ACCX = runpy.run_path(Path(__file__).parents[1] / "accx")


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class UsageWindowTests(unittest.TestCase):
    def test_claude_new_model_window_preserves_reset(self):
        raw = {"seven_day_fable": {"utilization": 42, "resets_at": "2030-01-08T09:30:00Z"}, "seven_day_opus": None}
        snapshot = ACCX["usage_snapshot"](ACCX["Provider"]("claude"), raw)
        self.assertEqual(len(snapshot["windows"]), 1)
        window = snapshot["windows"][0]
        self.assertEqual(window["key"], "seven_day_fable")
        self.assertEqual(window["used_percent"], 42)
        self.assertEqual(window["resets_at"], "2030-01-08T09:30:00Z")

    def test_claude_limits_array_includes_fable_without_duplicate_totals(self):
        raw = {
            "seven_day": {"utilization": 36, "resets_at": None},
            "limits": [
                {"kind": "weekly_all", "percent": 36, "resets_at": None},
                {"kind": "weekly_scoped", "group": "weekly", "percent": 56,
                 "scope": {"model": {"display_name": "Fable", "id": None}},
                 "resets_at": "2030-01-08T09:30:00Z"},
            ],
        }
        windows = ACCX["usage_windows"](ACCX["Provider"]("claude"), raw)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[1]["label"], "Fable · 7 gün")
        self.assertEqual(windows[1]["used_percent"], 56)
        self.assertEqual(windows[1]["resets_at"], "2030-01-08T09:30:00Z")

    def test_codex_additional_limits_and_code_review(self):
        raw = {
            "code_review_rate_limit": {"primary_window": {"used_percent": 12, "reset_at": 1893585600}},
            "additional_rate_limits": [{"limit_name": "model", "rate_limit": {"secondary_window": {"used_percent": 35, "reset_at": 1893585600}}}],
        }
        windows = ACCX["usage_windows"](ACCX["Provider"]("codex"), raw)
        self.assertEqual([w["used_percent"] for w in windows], [12, 35])
        self.assertTrue(all(w["resets_at"] for w in windows))


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


class ListUsageTests(unittest.TestCase):
    def test_usage_percent_colors_reflect_remaining_capacity(self):
        self.assertIn("format_usage_percent", ACCX)
        with patch("sys.stdout.isatty", return_value=True), patch.dict(
            os.environ, {"NO_COLOR": ""}
        ):
            self.assertEqual(ACCX["Colors"]().strike, "\033[9m")

        colors = type(
            "TestColors",
            (),
            {
                "red": "<red>",
                "green": "<green>",
                "yellow": "<yellow>",
                "dim": "<gray>",
                "strike": "<strike>",
                "off": "<off>",
            },
        )()
        formatter = ACCX["format_usage_percent"]
        with patch.dict(formatter.__globals__, {"C": colors}):
            self.assertEqual(formatter("0"), "      <gray>0%<off>")
            self.assertEqual(formatter("1"), "      1%")
            self.assertEqual(formatter("59"), "     59%")
            self.assertEqual(formatter("60"), "     <yellow>60%<off>")
            self.assertEqual(formatter("79"), "     <yellow>79%<off>")
            self.assertEqual(formatter("80"), "     <red>80%<off>")
            self.assertEqual(formatter("99"), "     <red>99%<off>")
            self.assertEqual(
                formatter("100"),
                "    <red><strike>100%<off>",
            )
            self.assertEqual(formatter("?"), "      <gray>?%<off>")

    def test_reset_times_are_formatted_in_local_time(self):
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 6, 28, 18, 0, 30, tzinfo=local_tz)
        same_day = datetime(2026, 6, 28, 20, 15, tzinfo=local_tz)
        next_day = datetime(2026, 6, 29, 1, 0, tzinfo=local_tz)
        past = datetime(2026, 6, 28, 17, 0, tzinfo=local_tz)
        epoch_reset = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        epoch = int(epoch_reset.timestamp())

        self.assertEqual(
            ACCX["format_reset_time"](same_day.isoformat(), now=now),
            "20:15 (2h 15m)",
        )
        self.assertEqual(
            ACCX["format_reset_time"](next_day.isoformat(), now=now),
            "2026-06-29 01:00",
        )
        self.assertEqual(
            ACCX["format_reset_time"](past.isoformat(), now=now),
            "17:00",
        )
        self.assertEqual(
            ACCX["format_reset_time"](epoch, now=now),
            epoch_reset.astimezone().strftime("%Y-%m-%d %H:%M"),
        )
        self.assertEqual(ACCX["format_reset_time"]("invalid", now=now), "?")
        self.assertEqual(ACCX["format_reset_time"](None, now=now), "?")

    def test_usage_cache_formats_claude_and_codex_reset_times(self):
        five_reset = "2030-01-01T12:00:00Z"
        seven_reset = 1893585600
        expected = (
            ACCX["format_reset_time"](five_reset),
            ACCX["format_reset_time"](seven_reset),
        )
        cases = {
            "claude": {
                "five_hour": {"utilization": 10, "resets_at": five_reset},
                "seven_day": {"utilization": 20, "resets_at": seven_reset},
            },
            "codex": {
                "rate_limit": {
                    "primary_window": {"used_percent": 10, "reset_at": five_reset},
                    "secondary_window": {"used_percent": 20, "reset_at": seven_reset},
                }
            },
        }

        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"ACCX_HOME": temp}
        ):
            for provider_name, raw in cases.items():
                with self.subTest(provider=provider_name):
                    provider = ACCX["Provider"](provider_name)
                    profile_dir = provider.profile_dir("work")
                    profile_dir.mkdir(parents=True)
                    provider.stored_cache_path("work").write_text(
                        json.dumps({"raw": raw})
                    )

                    values = ACCX["usage_cache_values"](
                        provider, "work", False, {}
                    )

                    self.assertEqual(values[2:], expected)

    def test_api_list_prints_reset_columns_and_values(self):
        five_reset = "2030-01-01T12:00:00Z"
        seven_reset = "2030-01-08T09:30:00Z"
        expected_five = ACCX["format_reset_time"](five_reset)
        expected_seven = ACCX["format_reset_time"](seven_reset)
        raw = {
            "five_hour": {"utilization": 10, "resets_at": five_reset},
            "seven_day": {"utilization": 20, "resets_at": seven_reset},
        }
        colors = type(
            "TestColors",
            (),
            {
                "red": "<red>",
                "green": "<green>",
                "yellow": "<yellow>",
                "bold": "<bold>",
                "dim": "<gray>",
                "strike": "<strike>",
                "off": "<off>",
            },
        )()

        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"ACCX_HOME": temp}
        ):
            profile_dir = Path(temp) / "claude" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "access"}})
            )
            (profile_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "identity": {
                            "email": "work@example.com",
                            "plan": "pro",
                        },
                        "credential": {},
                    }
                )
            )
            output = io.StringIO()
            with redirect_stdout(output), patch.dict(
                ACCX["list_command"].__globals__,
                {
                    "detect_active_profile": Mock(return_value=None),
                    "fetch_usage": Mock(return_value=raw),
                    "C": colors,
                },
            ):
                ACCX["list_command"](ACCX["Provider"]("claude"), True)

        rendered = output.getvalue()
        self.assertNotIn("<green>", rendered)
        self.assertIn("     10%", rendered)
        self.assertIn("     20%", rendered)
        self.assertIn("5H USED%", rendered)
        self.assertIn("7D USED%", rendered)
        self.assertIn("5H RESET", rendered)
        self.assertIn("7D RESET", rendered)
        self.assertIn(expected_five, rendered)
        self.assertIn(expected_seven, rendered)


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
                results = process(now, now - timedelta(hours=2))
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
                process(now, now - timedelta(hours=2))
            saved = json.loads((profile_dir / "settings.json").read_text())["wake"]

        self.assertTrue(saved["enabled"])
        self.assertIsNone(saved["last_run_at"])
        self.assertEqual(saved["last_result"], "failed: command not found")

    def test_wake_commands_are_non_interactive(self):
        self.assertEqual(
            ACCX["wake_command"](ACCX["Provider"]("claude"), "ping"),
            ["claude", "-p", "--model", "haiku", "--", "ping"],
        )
        self.assertEqual(
            ACCX["wake_command"](ACCX["Provider"]("codex"), "ping"),
            [
                "codex", "exec", "--skip-git-repo-check", "--model",
                "gpt-5.1-codex-mini", "--", "ping",
            ],
        )

    def test_wake_uses_isolated_profile_credentials(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ACCX_HOME": temp, "CODEX_HOME": str(Path(temp) / "live")}):
            profile_dir = Path(temp) / "codex" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text('{"tokens":{"access_token":"secret"}}')
            with patch("shutil.which", return_value="/usr/bin/codex"), patch("subprocess.Popen") as popen:
                result = ACCX["start_wake"](
                    ACCX["Provider"]("codex"),
                    "work",
                    {"prompt": "ping"},
                    notify=False,
                )

            runtime = profile_dir / ".agent-runtime"
            self.assertEqual(result, "started")
            self.assertTrue((runtime / "auth.json").exists())
            self.assertFalse((profile_dir / ".wake-runtime" / "auth.json").exists())
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


class SessionGuardTests(unittest.TestCase):
    def test_claude_config_dir_controls_metadata_path(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": temp}
        ):
            provider = ACCX["Provider"]("claude")
            self.assertEqual(provider.live_metadata_path(), Path(temp) / ".claude.json")

    def test_switch_updates_metadata_in_config_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            home.mkdir()
            cfg = Path(temp) / "cfg"
            cfg.mkdir()
            vault = Path(temp) / "vault"
            profile_dir = vault / "claude" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / "credential.json").write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "a", "refreshToken": "r"}})
            )
            (profile_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "identity": {},
                        "credential": {},
                        "claude": {"oauthAccount": {"emailAddress": "work@example.com"}},
                    }
                )
            )
            (cfg / ".claude.json").write_text(
                json.dumps(
                    {
                        "userID": "user-1",
                        "oauthAccount": {"emailAddress": "old@example.com"},
                    }
                )
            )
            with patch.dict(
                os.environ,
                {
                    "ACCX_HOME": str(vault),
                    "CLAUDE_CONFIG_DIR": str(cfg),
                    "HOME": str(home),
                },
            ):
                ACCX["perform_switch_profile"](
                    ACCX["Provider"]("claude"), "work", check_sessions=False
                )

            saved = json.loads((cfg / ".claude.json").read_text())
            self.assertEqual(saved["oauthAccount"]["emailAddress"], "work@example.com")
            self.assertEqual(saved["userID"], "user-1")
            self.assertFalse((home / ".claude.json").exists())

    def test_background_helpers_are_not_active_sessions(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"HOME": temp}, clear=True
        ):
            is_process = ACCX["_is_provider_process"]
            claude = ACCX["Provider"]("claude")
            codex = ACCX["Provider"]("codex")

            self.assertTrue(
                is_process(claude, ["claude"], "/opt/claude", {"HOME": temp})
            )
            self.assertFalse(
                is_process(
                    claude,
                    ["claude", "--chrome-native-host"],
                    "/opt/claude",
                    {"HOME": temp},
                )
            )
            self.assertFalse(
                is_process(
                    claude, ["claude", "mcp"], "/opt/claude", {"HOME": temp}
                )
            )
            self.assertTrue(
                is_process(codex, ["codex", "exec", "hello"], "/opt/codex", {"HOME": temp})
            )
            self.assertFalse(
                is_process(
                    codex,
                    ["codex", "app-server", "--listen", "unix://"],
                    "/opt/codex",
                    {"HOME": temp},
                )
            )

    def test_active_session_blocks_switch_without_killing(self):
        session = {
            "pid": 1234,
            "command": "claude",
            "ancestor": False,
            "start_time": 1,
        }
        guard = ACCX["ensure_no_active_sessions"]
        with patch.dict(
            guard.__globals__, {"find_active_sessions": Mock(return_value=[session])}
        ):
            with self.assertRaises(ACCX["ActiveSessionsError"]) as denied:
                guard(ACCX["Provider"]("claude"), "switch", interactive=False)
        self.assertEqual(denied.exception.sessions, [session])

    def test_interactive_confirmation_can_stop_sessions(self):
        session = {
            "pid": 1234,
            "command": "claude",
            "ancestor": False,
            "start_time": 1,
        }
        guard = ACCX["ensure_no_active_sessions"]
        terminate = Mock()
        with patch.dict(
            guard.__globals__,
            {
                "find_active_sessions": Mock(return_value=[session]),
                "_terminate_sessions": terminate,
            },
        ), patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="y"
        ), redirect_stderr(io.StringIO()):
            guard(ACCX["Provider"]("claude"), "switch", interactive=True)

        terminate.assert_called_once_with([session])

    def test_ancestor_session_is_never_killed(self):
        session = {
            "pid": 1234,
            "command": "claude",
            "ancestor": True,
            "start_time": 1,
        }
        guard = ACCX["ensure_no_active_sessions"]
        terminate = Mock()
        with patch.dict(
            guard.__globals__,
            {
                "find_active_sessions": Mock(return_value=[session]),
                "_terminate_sessions": terminate,
            },
        ):
            with self.assertRaises(ACCX["ActiveSessionsError"]):
                guard(
                    ACCX["Provider"]("claude"),
                    "switch",
                    kill_active=True,
                    interactive=False,
                )
        terminate.assert_not_called()

    def test_codex_usage_refresh_does_not_rotate_live_token_during_session(self):
        expired = jwt({"exp": int(time.time()) - 60})
        session = {
            "pid": 1234,
            "command": "codex",
            "ancestor": False,
            "start_time": 1,
        }
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "ACCX_HOME": str(Path(temp) / "vault"),
                "CODEX_HOME": str(Path(temp) / "live-codex"),
            },
        ):
            profile_dir = Path(temp) / "vault" / "codex" / "work"
            profile_dir.mkdir(parents=True)
            credential = {"tokens": {"access_token": expired, "refresh_token": "refresh"}}
            (profile_dir / "credential.json").write_text(json.dumps(credential))
            live = Path(temp) / "live-codex" / "auth.json"
            live.parent.mkdir(parents=True)
            live.write_text(json.dumps(credential))

            values = ACCX["usage_cache_values"]
            refresh = Mock()
            with patch.dict(
                values.__globals__,
                {
                    "find_active_sessions": Mock(return_value=[session]),
                    "refresh_codex_credential": refresh,
                    "fetch_usage": Mock(return_value={"rate_limit": {}}),
                },
            ):
                values(ACCX["Provider"]("codex"), "work", True, credential, active=True)

            refresh.assert_not_called()
            self.assertEqual(json.loads(live.read_text()), credential)

    def test_kill_active_flag_is_parsed_before_add_login_args(self):
        parser = ACCX["build_parser"]()
        switch_args = parser.parse_args(["claude", "switch", "work", "--kill-active"])
        add_args = parser.parse_args(
            ["claude", "add", "--kill-active", "personal", "--email", "me@example.com"]
        )

        self.assertTrue(switch_args.kill_active)
        self.assertTrue(add_args.kill_active)
        self.assertEqual(add_args.login_args, ["--email", "me@example.com"])


class DesktopNotificationTests(unittest.TestCase):
    def test_desktop_notify_uses_notify_send(self):
        with patch("shutil.which", return_value="/usr/bin/notify-send"), patch(
            "subprocess.run"
        ) as run, patch.dict(os.environ, {"ACCX_DESKTOP_NOTIFY": "1"}):
            self.assertTrue(ACCX["desktop_notify"]("Başlık", "Gövde"))

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/notify-send")
        self.assertIn("-a", command)
        self.assertIn("accx", command)
        self.assertEqual(command[-2:], ["Başlık", "Gövde"])

    def test_desktop_notify_can_be_disabled(self):
        with patch("shutil.which", return_value="/usr/bin/notify-send"), patch(
            "subprocess.run"
        ) as run, patch.dict(os.environ, {"ACCX_DESKTOP_NOTIFY": "0"}):
            self.assertFalse(ACCX["desktop_notify"]("Başlık", "Gövde"))

        run.assert_not_called()

    def test_full_limit_reset_sends_one_desktop_notification(self):
        now = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)
        reset = now - timedelta(minutes=5)
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"ACCX_HOME": temp}
        ):
            profile_dir = Path(temp) / "claude" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".usage-cache.json").write_text(
                json.dumps(
                    {
                        "fetched_at": now.isoformat(),
                        "raw": {
                            "five_hour": {
                                "utilization": 100,
                                "resets_at": reset.isoformat(),
                            },
                            "seven_day": {
                                "utilization": 50,
                                "resets_at": reset.isoformat(),
                            },
                        },
                    }
                )
            )
            notify = Mock(return_value=True)
            process = ACCX["process_due_notifications"]
            with patch.dict(process.__globals__, {"desktop_notify": notify}):
                first = process(now=now)
                second = process(now=now)

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])
            self.assertEqual(notify.call_count, 1)
            self.assertIn("5 saatlik", notify.call_args.args[0])
            state = json.loads((Path(temp) / "notify-state.json").read_text())
            self.assertEqual(len(state["sent"]), 1)
            self.assertEqual(state["pending"], {})

    def test_pending_reset_survives_cache_refresh(self):
        now = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)
        old_reset = now + timedelta(minutes=5)
        new_reset = now + timedelta(hours=5)
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"ACCX_HOME": temp}
        ):
            profile_dir = Path(temp) / "claude" / "work"
            profile_dir.mkdir(parents=True)
            cache = profile_dir / ".usage-cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "raw": {
                            "five_hour": {
                                "utilization": 100,
                                "resets_at": old_reset.isoformat(),
                            }
                        }
                    }
                )
            )
            notify = Mock(return_value=True)
            process = ACCX["process_due_notifications"]
            with patch.dict(process.__globals__, {"desktop_notify": notify}):
                before = process(now=now)
                self.assertEqual(before, [])
                self.assertEqual(notify.call_count, 0)

                cache.write_text(
                    json.dumps(
                        {
                            "raw": {
                                "five_hour": {
                                    "utilization": 0,
                                    "resets_at": new_reset.isoformat(),
                                }
                            }
                        }
                    )
                )
                after = process(now=old_reset + timedelta(minutes=1))

            self.assertEqual(len(after), 1)
            self.assertEqual(notify.call_count, 1)

    def test_old_reset_is_ignored_without_notification(self):
        now = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)
        reset = now - timedelta(hours=2)
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"ACCX_HOME": temp}
        ):
            profile_dir = Path(temp) / "claude" / "work"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".usage-cache.json").write_text(
                json.dumps(
                    {
                        "raw": {
                            "five_hour": {
                                "utilization": 100,
                                "resets_at": reset.isoformat(),
                            }
                        }
                    }
                )
            )
            notify = Mock(return_value=True)
            process = ACCX["process_due_notifications"]
            with patch.dict(process.__globals__, {"desktop_notify": notify}):
                results = process(now=now)

            self.assertEqual(results, [])
            notify.assert_not_called()


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
        Handler.bind_host = "127.0.0.1"
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

    def test_switch_conflict_returns_active_sessions(self):
        session = {
            "pid": 1234,
            "command": "claude",
            "ancestor": False,
            "start_time": 1,
        }
        switch = ACCX["perform_switch_profile"]
        with patch.dict(
            switch.__globals__, {"find_active_sessions": Mock(return_value=[session])}
        ):
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.request(
                    "/api/profiles/claude/work/switch",
                    method="POST",
                    data={},
                    token=self.state.token,
                )
            self.assertEqual(denied.exception.code, 409)
            payload = json.load(denied.exception)

        self.assertEqual(payload["active_sessions"][0]["pid"], 1234)
        self.assertTrue(payload["can_kill"])

    def test_mutation_allowed_for_lan_host_when_bound_to_all(self):
        handler = object.__new__(ACCX["DashboardHandler"])
        handler.bind_host = "0.0.0.0"
        handler.state = Mock(token="secret")
        handler.headers = {
            "Host": "192.168.1.10:8765",
            "X-ACCX-Token": "secret",
            "Content-Type": "application/json",
        }

        self.assertTrue(handler.mutation_allowed())


if __name__ == "__main__":
    unittest.main()
