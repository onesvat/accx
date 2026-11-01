# accx

Switch between Claude Code and Codex CLI accounts instantly. One Python script, no third-party dependencies.

## Why

Claude Code and Codex CLI store local auth state for one active account at a time. `accx` saves those credentials under a profile name, then restores them to switch accounts without repeating the browser login flow.

## Install

```bash
git clone https://github.com/onurnesvat/accx.git ~/Code/accx
ln -sf ~/Code/accx/accx ~/.local/bin/accx
```

Requirements: Python 3.10+.

## Web dashboard

Launch the local dashboard and open it in your browser:

```bash
accx web
```

The dashboard combines saved Claude and Codex profiles. It shows current 5-hour and 7-day usage, stores monthly renewal dates, prices, and plan notes, and switches the active CLI profile. Usage is refreshed every 15 minutes while the server is running; use **Refresh usage** for an immediate API refresh.

Each profile can also have an automatic wake schedule. Choose a one-time date or a daily time, enter the prompt, and review the expected five-hour reset window before saving. The scheduler runs in the `accx web` process, so the browser may be closed, but stopping `accx web` also stops scheduled wakes. A wake starts Claude with `haiku` or Codex with `gpt-5.1-codex-mini` in the background using an isolated copy of that profile's credentials, without changing the active terminal account.

Scheduler and launch events are written as JSON lines to `~/.accx/wake.log`. Command output is written to `~/.accx/<provider>/<profile>/.wake-runtime/wake.log` for troubleshooting failed automatic wakes.

Open the **Uyandırma** page in the dashboard (or `/wake.html`) to review every saved schedule, its next run, recent scheduler events, and the captured CLI output.

The server binds to `127.0.0.1` by default. Use `accx web --no-open` to skip opening the browser, `accx web --port 9000` to choose another local port, or `accx web --bind 0.0.0.0` to listen on all interfaces.

## Usage

```
accx claude|codex <command> [--api]
accx web [--port PORT] [--bind ADDRESS] [--no-open]
```

### Commands

| Command | Description |
|---------|-------------|
| `list [--api]` | Table of saved accounts with usage percentages and reset times |
| `add [--kill-active] <name> [opts]` | Add a new account without logging out of the current one |
| `save <name>` | Save current account under a name |
| `switch [--kill-active] <name>` | Switch to a saved account |
| `identity [--api]` | Show active account details, plan type, subscription info |
| `paths` | Show live auth paths and environment variables that may override them |

### Examples

```bash
# Save current Claude account
accx claude save work

# Add another Claude account without calling logout
accx claude add personal --email me@example.com

# Add another Codex account without calling logout
accx codex add work --device-auth

# Switch between saved accounts
accx claude switch work
accx claude switch personal

# List all saved claude accounts with usage data
accx claude list --api

# Same for Codex
accx codex save personal
accx codex list --api

# Show active account identity
accx claude identity
```

### Adding another account

Claude Code and Codex CLI only keep one live OAuth session. `accx <provider> add <name>` works around that without calling logout:

1. saves the current active profile if it can identify it,
2. backs up the live auth file under `~/.accx/.backups/`,
3. temporarily hides the live credential file so the CLI prompts for login,
4. runs `claude auth login` or `codex login`,
5. saves the newly logged-in account as `~/.accx/<provider>/<name>/`.

Pass login options after the profile name:

```bash
accx claude add personal --email me@example.com
accx claude add work-sso --sso
accx codex add work --device-auth
```

To refresh an existing saved Claude profile, switch to it, authenticate again, then save it:

```bash
accx claude switch personal
claude auth login
accx claude save personal
```

Claude access tokens expire frequently. That is normal when a refresh token is present; Claude Code should refresh the access token on the next authenticated run.

### Active sessions

A running CLI process keeps its OAuth token in memory and may write it back when it refreshes. Switching the auth file underneath it can therefore be overwritten. Before `switch` and `add`, `accx` looks for running Claude Code or Codex CLI processes that use the same auth file.

- In a terminal it lists the PIDs and asks before stopping them.
- In a non-interactive shell it refuses and exits with an error.
- `--kill-active` gives consent up front:

```bash
accx claude switch --kill-active work
accx claude add --kill-active personal --email me@example.com
accx codex switch --kill-active work
```

The web dashboard asks for confirmation when a switch hits an active session. Background helpers such as Claude's Chrome native host and Codex's `app-server` daemon are not treated as sessions and are never stopped.

Do not run `switch` or `add` from inside the CLI session whose account you are changing: `accx` detects that it is running under that session and refuses, because stopping it would also stop `accx`.

### API mode

By default `list` and `identity` use cached data. Add `--api` to fetch live usage:

```bash
accx claude list            # cached (instant)
accx claude list --api      # live usage from Anthropic API

accx codex identity --api   # live usage from ChatGPT API
```

**Note:** API mode calls undocumented vendor endpoints. Use at your own risk. Without `--api`, the script only touches local files — no external network requests.

## How it works

**Claude Code** stores auth in two files:
- `~/.claude/.credentials.json` — OAuth tokens (access + refresh)
- `~/.claude.json` — cached identity (`oauthAccount`) + settings

`accx` stores and restores only the credential file. It stores `oauthAccount` separately as metadata and updates only that field on switch, preserving unrelated Claude settings such as MCP servers, plugins, project state, and UI preferences. If `CLAUDE_CONFIG_DIR` is set, both files are read from that directory instead of the home directory.

Background token refreshes for an active Codex profile are skipped while a Codex session is running, so `accx` does not overwrite the live `auth.json` under a running process.

**Codex CLI** stores auth in one file:
- `~/.codex/auth.json`

`accx` saves credentials and metadata to `~/.accx/<provider>/<name>/` and restores the credential on switch.

## Vault layout

```
~/.accx/
├── claude/
│   ├── work/
│   │   ├── credential.json
│   │   ├── meta.json
│   │   ├── settings.json         # billing and automatic wake settings
│   │   └── .usage-cache.json     # latest API response
│   └── personal/
│       └── ...
└── codex/
    └── work/
        ├── credential.json
        ├── meta.json
        └── .usage-cache.json
```

Older vault entries using `.credentials.json`, `.claude.json`, or `auth.json` are still readable.

## License

MIT
