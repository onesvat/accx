# accx

Switch between Claude Code and Codex CLI accounts instantly. One script, no dependencies beyond `bash`, `jq`, `curl`.

## Why

Claude Code and Codex CLI store OAuth tokens in plain files on disk. `accx` saves those files under a name, then restores them to switch accounts — no browser login, no OAuth dance. Under 100ms.

## Install

```bash
git clone https://github.com/onurnesvat/accx.git ~/Code/accx
ln -sf ~/Code/accx/accx ~/.local/bin/accx
```

Requirements: `bash 5+`, `jq`, `curl`.

## Usage

```
accx claude|codex <command> [--api]
```

### Commands

| Command | Description |
|---------|-------------|
| `list [--api]` | Table of saved accounts with usage percentages and reset times |
| `save <name>` | Save current account under a name |
| `switch <name>` | Switch to a saved account |
| `identity [--api]` | Show active account details, plan type, subscription info |

### Examples

```bash
# Save current Claude account
accx claude save work

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

Both must be swapped together, otherwise stale identity cache causes wrong account name display.

**Codex CLI** stores auth in one file:
- `~/.codex/auth.json`

`accx` saves these files to `~/.accx/<provider>/<name>/` and restores them on switch.

## Vault layout

```
~/.accx/
├── claude/
│   ├── work/
│   │   ├── .credentials.json
│   │   ├── .claude.json
│   │   └── .usage-cache.json    # API response cache
│   └── personal/
│       └── ...
└── codex/
    └── work/
        ├── auth.json
        └── .usage-cache.json
```

## License

MIT
