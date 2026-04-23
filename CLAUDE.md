# Key Rotator — Claude Code Guide

Automated API key rotation with a PWA dashboard. Keys are generated via provider
APIs or shell scripts, written to configured stores, health-checked, then the old
key is revoked. Everything runs locally — no cloud dependency.

## Quick start

```bash
uv sync                        # install deps
key-rotator serve              # start PWA server at http://127.0.0.1:7821
key-rotator serve --show-token # get the browser URL with auth token
key-rotator status             # list configured keys
key-rotator rotate <id>        # rotate one key manually
key-rotator rotate --dry-run   # preview without changes
```

## Architecture

```
rotator/
├── cli.py            # Click CLI — all user-facing commands
├── core.py           # Orchestration: generate → write stores → health check → revoke
├── server.py         # FastAPI app — REST API + WebSocket for the PWA
├── scheduler.py      # APScheduler daemon (runs cron-scheduled rotations)
├── vault.py          # Keyring wrapper — all secrets stored here, never in files
├── notify.py         # Desktop notifications (cross-platform)
├── platform_setup.py # Service install/uninstall for Linux/macOS/Windows
├── providers/        # HOW to generate a new key for a service
│   ├── base.py       # BaseProvider ABC — implement generate() and revoke()
│   ├── script.py     # Generic: run a shell/PowerShell script
│   ├── stripe.py     # Stripe restricted keys via Stripe API
│   └── resend.py     # Resend API keys via Resend API
└── stores/           # WHERE a key lives
    ├── base.py       # BaseStore ABC — implement read() and write()
    ├── dotenv.py     # .env files
    ├── vercel.py     # Vercel project env vars via Vercel CLI
    └── system_env.py # Shell export file (Linux/macOS) or PS1 (Windows)

rotator/static/       # PWA frontend — single index.html, no build step
├── index.html        # All CSS + JS inline. Talks to FastAPI via fetch/WebSocket.
├── manifest.json     # PWA manifest
├── sw.js             # Service worker (network-first, enables installability)
└── icon.svg          # App icon

key_rotator_entry.py  # PyInstaller entry point — double-click opens browser
key-rotator.spec      # PyInstaller build config
```

## Adding a new provider

Create `rotator/providers/yourservice.py`:

```python
from .base import BaseProvider, RotationResult
from ..vault import get_mgmt_cred

class YourServiceProvider(BaseProvider):
    def generate(self, config: dict, key_id: str) -> RotationResult:
        admin_key = get_mgmt_cred(key_id, "admin_key")
        # Call your service's API to create a new key
        # Return RotationResult(new_key_value="...", new_key_id="...")
        ...

    def revoke(self, config: dict, key_id: str, old_key_id) -> None:
        # Call your service's API to delete the old key
        # old_key_id is whatever you put in RotationResult.new_key_id
        ...
```

Register it in `rotator/providers/__init__.py`:

```python
from .yourservice import YourServiceProvider
REGISTRY["yourservice"] = YourServiceProvider
```

Add management credentials to the keyring:

```bash
key-rotator set-secret my_key_id mgmt.admin_key
```

## Adding a new store

Create `rotator/stores/yourstore.py`:

```python
from .base import BaseStore
from typing import Optional

class YourStore(BaseStore):
    def label(self, config: dict) -> str:
        return f"yourstore:{config['some_field']}"

    def read(self, config: dict) -> Optional[str]:
        # Return current key value, or None if unreadable
        ...

    def write(self, config: dict, value: str) -> None:
        # Write the new key value
        ...
```

Register in `rotator/stores/__init__.py`:

```python
from .yourstore import YourStore
REGISTRY["yourstore"] = YourStore
```

## Key rotation flow (core.py)

1. Read current value from each store → back up to vault
2. Call `provider.generate()` → new key value
3. Write new value to all stores (track which succeed for rollback)
4. If `health_check` configured: hit the URL with new key
   - Pass → call `provider.revoke()` with old key ID → done
   - Fail → restore old value to all written stores → offer fix options
5. Fix options (terminal: interactive prompt / PWA: buttons):
   - Retry health check
   - Force-write new key anyway
   - Revoke new key, keep old
   - Do nothing

## PWA ↔ server communication

- `GET  /api/keys`                      → list all keys + status
- `POST /api/keys/{id}/set-value`       → manually push a key value to all stores
- `POST /api/keys/{id}/restore`         → restore vault backup to all stores
- `POST /api/keys/{id}/revoke`          → revoke a provider-side key by ID
- `GET  /api/keys/{id}/backup`          → get masked old key + full value for copy
- `DELETE /api/keys/{id}/backup`        → clear vault backup
- `POST /api/keys/{id}/pending/resolve` → resolve a health-check failure
- `POST /api/parse-stack`               → detect services from free-text description
- `POST /api/apply-config`              → merge suggested entries into config.yaml
- `GET  /api/scheduler`                 → systemd/launchd/Task Scheduler status
- `WS   /ws/rotate/{id}`               → stream rotation log events in real time

All REST endpoints require `Authorization: Bearer <token>`.
WebSocket uses `?token=<token>` query param.
Token is stored in GNOME Keyring / macOS Keychain / Windows Credential Manager.

## Config file

Lives at `~/.config/key-rotator/config.yaml`. Never committed — in `.gitignore`.
Copy `config.example.yaml` to get started.

```yaml
keys:
  - id: resend_main              # unique identifier, used in CLI commands
    provider:
      type: resend               # matches REGISTRY key in providers/__init__.py
      name: "my-app-rotated"
    stores:
      - type: dotenv             # matches REGISTRY key in stores/__init__.py
        path: /path/to/.env
        var: RESEND_API_KEY
      - type: vercel
        project: my-vercel-project
        var: RESEND_API_KEY
        env: production
    health_check:
      url: https://api.resend.com/domains
      method: GET
      expected_status: 200
      auth_header: Authorization
      auth_header_value: "Bearer {key}"   # {key} is replaced with the new value
    schedule: "0 3 1 * *"        # cron — omit for manual-only keys
```

## Vault (keyring)

All secrets use `keyring` — GNOME Keyring on Linux, Keychain on macOS,
Windows Credential Manager on Windows. Service name is always `"key-rotator"`.

Key naming convention:
- `{key_id}.mgmt.admin_key`   — management credential for a provider
- `{key_id}.backup_value`     — old key value saved before last rotation
- `{key_id}.current_key_id`   — provider-side ID of the current key (for revocation)
- `__server__.api_token`      — PWA auth token

```python
from rotator.vault import store, get, get_backup_value
store("my_key", "mgmt.admin_key", "sk-...")
get("my_key", "mgmt.admin_key")
```

## PWA frontend

Single file: `rotator/static/index.html`. No build step, no framework.
All CSS and JS are inline. Edit it directly and restart the server to see changes.

The `emit` callback in `core.py` is how the server streams log lines to the browser
over WebSocket. Each event is a dict: `{"type": "info|warn|error|success", "msg": "..."}`.

## Background services

Installed by `key-rotator install`, removed by `key-rotator uninstall`.

| Platform | Scheduler | Web server |
|----------|-----------|------------|
| Linux | `~/.config/systemd/user/key-rotator.service` | `key-rotator-web.service` |
| macOS | `~/Library/LaunchAgents/com.keyrotator.scheduler.plist` | `com.keyrotator.web.plist` |
| Windows | Task Scheduler: `KeyRotatorScheduler` | `KeyRotatorWeb` |

## Building a release binary

```bash
uv sync --all-groups
uv run pyinstaller key-rotator.spec --clean
# → dist/key-rotator  (or dist/key-rotator.exe on Windows)
```

GitHub Actions builds all three platforms automatically on any `v*` tag push:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

Binaries appear at: https://github.com/AppZ3/key-rotator/releases/latest
