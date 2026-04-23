# Key Rotator

Automated API key rotation with a local PWA dashboard. Works on Linux, macOS, and Windows.

## How it works

1. **Rotate** — generates a new key via the service's API (or a script you write)
2. **Write** — pushes the new key to every place it's stored (.env files, Vercel env vars, etc.)
3. **Verify** — runs a health check with the new key before touching the old one
4. **Revoke** — deletes the old key only after the health check passes
5. **Rollback** — if the health check fails, restores the old key automatically

All credentials are stored in your OS keychain (GNOME Keyring / macOS Keychain / Windows Credential Manager) — never in plaintext files.

## Download

**No installation required** — grab the binary for your platform from the [latest release](https://github.com/AppZ3/key-rotator/releases/latest):

| Platform | File |
|----------|------|
| Windows | `key-rotator-windows.exe` |
| macOS | `key-rotator-mac` |
| Linux | `key-rotator-linux` |

Double-click (Windows) or run from terminal (Mac/Linux) — the PWA opens in your browser automatically.

## Supported services

| Service | Rotation | Notes |
|---------|----------|-------|
| Resend | Automatic | Creates/revokes API keys via Resend API |
| Stripe | Automatic | Creates/revokes restricted keys via Stripe API |
| GitHub | Automatic | Creates/revokes fine-grained PATs via `gh` CLI |
| Anthropic | Manual | No management API — paste new key in PWA |
| Supabase | Manual | Reset in dashboard, paste in PWA |
| Vercel | Manual | Create token in dashboard, paste in PWA |
| Any service | Script | Write a shell script that outputs the new key |

## Setup (from source)

```bash
git clone https://github.com/AppZ3/key-rotator
cd key-rotator
uv sync
key-rotator install        # sets up background services for your platform
key-rotator serve --show-token  # get your browser URL
```

Requires [uv](https://docs.astral.sh/uv/).

## Configuration

Copy the example config and edit it:

```bash
cp config.example.yaml ~/.config/key-rotator/config.yaml
```

Then store your management credentials in the keychain:

```bash
key-rotator set-secret resend_main mgmt.admin_key   # prompts for value
key-rotator set-secret stripe_main mgmt.admin_key
```

See `config.example.yaml` for full documentation of all options.

## Extending

Key Rotator is designed to be extended. See `CLAUDE.md` for a full developer guide — including how to add new providers and stores in ~20 lines of Python each.

## License

MIT
