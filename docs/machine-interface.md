# Local machine interface

Run `accx machine` as a persistent child process on the desktop. It uses the existing `ACCX_HOME` account store and opens no port. Keep stdin open and read stdout as UTF-8 JSON Lines. Each request gets one response. Background work emits no unsolicited messages. Reject or reconnect on protocol errors.

```json
{"version":1,"id":"req-1","method":"snapshot","params":{}}
```

Every response has `version`, `id`, and exactly one of `result` or `error`. An error contains a fixed `code` and no raw diagnostic. The ID is null if the request ID could not be parsed. A request is at most 64 KiB including its newline.

| Method | Parameters | Result |
|---|---|---|
| `snapshot` | Empty object | `generated_at`, `auto_refresh_seconds`, `profiles`, `monthly_totals` |
| `refresh` | Optional pair `provider` and `profile_id`; optional boolean `force` defaults to true | `profiles` array with `provider`, `profile_id` and `status` per attempt |
| `billing.save` | `provider`, `profile_id`, `billing` | `status: "saved"` |
| `wake.save` | `provider`, `profile_id`, `wake` | `status: "saved"` |
| `wake.now` | `provider`, `profile_id`; uses the saved prompt | `status: "started"` |
| `switch` | `provider`, `profile_id` | `status: "switched"` |
| `runtime.prepare` | `provider`, `profile_id` | `path`, `status: "ready"` |

Providers are `claude` and `codex`. A profile ID stays stable while its local name and provider stay the same. The display `label` can be an alias when the name is unsuitable for display. For login and profile creation, list local names with `accx claude list` or `accx codex list` and use the provider's existing accx CLI commands. OpenCode remains available via its CLI and the local web panel.

Profile snapshots carry `provider`, `profile_id`, `label`, `active`, `plan`, `login_needed`, `usage`, `billing`, and `wake`. Usage carries `fetched_at`, `last_attempt_at`, `refresh_status`, `stale`, and `windows`. Each window carries `key`, `label`, `used_percent`, `resets_at`, and `window_seconds`. Last good measurements remain available on refresh failure. Refresh results use `refreshed`, `cached`, `unavailable`, or `login_needed`. Times carry offsets. Missing values are null.

Billing takes `amount` (decimal string), `currency`, `renewal_date` (YYYY-MM-DD), optional `anchor_day` (1–31), and optional `note` (up to 500 characters). Billing snapshots add `interval` and group monthly totals by currency. Wakes take `enabled`, `recurrence` (`once` or `daily`), `date` for one-time wakes, `time` (HH:MM in desktop local time), and `prompt` (up to 4,000 characters). Wake snapshots add `next_run_at`, `last_run_at`, and `last_result`. Starting a manual wake does not consume a future scheduled occurrence.

Request errors include `invalid_request`, `request_too_large`, `unsupported_version`, `unknown_method`, `invalid_params`, and `profile_not_found`. Operation errors include `active_sessions`, `configuration_conflict`, `login_needed`, `wake_not_configured`, `wake_running`, `wake_failed`, and `operation_failed`. If the child dies after accepting a mutation, or returns `operation_failed`, reconcile the result without repeating the mutation. A wake launch can report `unknown` if the owning process stops before recording the exit.

Updated web and machine processes in the same store elect one wake scheduler using an OS file lock. The scheduler skips occurrences before ownership or during a long pause. It records an occurrence before launching it. Both processes may check usage every 15 minutes, with a shared lock and per-profile attempt timestamps preventing duplicate automatic refreshes. The installed web service must pick up this code before running both processes on one store.

`runtime.prepare` returns `path`, `status: "ready"` and `shared`. For a profile that is not the terminal's active one it creates or refreshes the profile's single persistent runtime directory (`<store>/<provider>/<profile>/.agent-runtime`) and returns its path; the caller points `CLAUDE_CONFIG_DIR` (Claude) or `CODEX_HOME` (Codex) at it. Wake uses the same directory (only its state and log stay in `.wake-runtime`). For the terminal's active profile it makes no copy and answers `path: null, shared: true`: the job must leave the config directory variable unset and share the terminal's config, because a second copy could rotate the refresh token and log the terminal out.

All copies are reconciled under the store lock shared with refresh and switch: the copy with the latest access expiry among live (active profile only), stored and runtime wins, and older copies are updated, never the reverse. `switch` first reconciles the target profile (its runtime copy may be newer than the stored one) and the profile being switched away from; automatic saves before a switch or login never replace a newer stored or runtime credential. Only an explicit `accx <provider> save` overwrites with the live file. Errors: `profile_not_found`, `login_needed`.
