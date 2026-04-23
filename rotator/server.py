"""
Local-only FastAPI server for the PWA frontend.
Binds to 127.0.0.1 only. Auth via bearer token stored in GNOME Keyring.
"""
import asyncio
import json
import re
import secrets
import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .core import rotate_key
from .vault import get, store
from .stores import get_store
from .providers import get_provider
from .vault import get_backup_value

app = FastAPI(title="Key Rotator")
_static = Path(__file__).parent / "static"

# ── Auth ──────────────────────────────────────────────────────────────────────

_VAULT_ID = "__server__"
_TOKEN_FIELD = "api_token"
_bearer = HTTPBearer()


def get_or_create_token() -> str:
    token = get(_VAULT_ID, _TOKEN_FIELD)
    if not token:
        token = secrets.token_urlsafe(32)
        store(_VAULT_ID, _TOKEN_FIELD, token)
    return token


def _check_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    if credentials.credentials != get_or_create_token():
        raise HTTPException(status_code=401, detail="Invalid token")


def _check_token_qs(token: str = ""):
    """For WebSocket connections which can't use headers."""
    if token != get_or_create_token():
        raise ValueError("Unauthorized")


# ── Config ────────────────────────────────────────────────────────────────────

_config_path: Path = Path.home() / ".config" / "key-rotator" / "config.yaml"


def _load_config() -> dict:
    if not _config_path.exists():
        return {"keys": []}
    return yaml.safe_load(_config_path.read_text()) or {"keys": []}


def _find_key(key_id: str) -> dict:
    config = _load_config()
    key = next((k for k in config.get("keys", []) if k["id"] == key_id), None)
    if not key:
        raise HTTPException(404, f"Key not found: {key_id}")
    return key


# ── Pending failure state ─────────────────────────────────────────────────────

_pending: dict[str, dict] = {}  # key_id → pending dict from rotate_key


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
async def index(token: str = ""):
    return FileResponse(_static / "index.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(_static / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def sw():
    return FileResponse(_static / "sw.js", media_type="application/javascript")


@app.get("/icon.svg")
async def icon():
    return FileResponse(_static / "icon.svg", media_type="image/svg+xml")


# ── Stack parser ─────────────────────────────────────────────────────────────

# Known services and their rotation support
_SERVICE_DB = {
    "resend": {
        "can_automate": True,
        "provider": {"type": "resend", "name": "rotated", "permission": "full_access"},
        "health_check": {"url": "https://api.resend.com/domains", "method": "GET", "expected_status": 200, "auth_header": "Authorization", "auth_header_value": "Bearer {key}"},
        "schedule": "0 3 1 * *",
        "setup_note": "Run: key-rotator set-secret {id} mgmt.admin_key  (paste your current Resend API key)",
        "env_vars": ["RESEND_API_KEY"],
        "console_url": "https://resend.com/api-keys",
    },
    "stripe": {
        "can_automate": True,
        "provider": {"type": "stripe", "name": "rotated", "permissions": ["customers:write", "payment_intents:write", "prices:read", "products:read", "subscriptions:write", "checkout.sessions:write"]},
        "health_check": {"url": "https://api.stripe.com/v1/customers?limit=1", "method": "GET", "expected_status": 200, "auth_header": "Authorization", "auth_header_value": "Bearer {key}"},
        "schedule": "0 3 15 * *",
        "setup_note": "Run: key-rotator set-secret {id} mgmt.admin_key  (paste your current Stripe secret key)",
        "env_vars": ["STRIPE_SECRET_KEY"],
        "console_url": "https://dashboard.stripe.com/apikeys",
    },
    "anthropic": {
        "can_automate": False,
        "provider": {"type": "script", "generate_script": "~/.config/key-rotator/scripts/anthropic-prompt.sh"},
        "health_check": {"url": "https://api.anthropic.com/v1/models", "method": "GET", "expected_status": 200, "auth_header": "x-api-key", "auth_header_value": "{key}"},
        "setup_note": "No management API — rotate manually at console.anthropic.com, then run: key-rotator rotate {id}",
        "env_vars": ["ANTHROPIC_API_KEY"],
        "console_url": "https://console.anthropic.com/settings/keys",
    },
    "github": {
        "can_automate": True,
        "provider": {"type": "script", "generate_script": "~/.config/key-rotator/scripts/github-gen.sh", "revoke_script": "~/.config/key-rotator/scripts/github-revoke.sh"},
        "health_check": {"url": "https://api.github.com/user", "method": "GET", "expected_status": 200, "auth_header": "Authorization", "auth_header_value": "Bearer {key}"},
        "schedule": "0 3 1 */3 *",
        "setup_note": "Run: gh auth login  (one-time setup)",
        "env_vars": ["GITHUB_TOKEN"],
        "console_url": "https://github.com/settings/tokens",
    },
    "openai": {
        "can_automate": False,
        "can_manage_manually": True,
        "manual_note": "Create a new key at platform.openai.com/api-keys, then use 'Set new key' in the PWA to push it to all your stores.",
        "provider": {"type": "script", "generate_script": "~/.config/key-rotator/scripts/openai-prompt.sh"},
        "health_check": {"url": "https://api.openai.com/v1/models", "method": "GET", "expected_status": 200, "auth_header": "Authorization", "auth_header_value": "Bearer {key}"},
        "env_vars": ["OPENAI_API_KEY"],
        "console_url": "https://platform.openai.com/api-keys",
    },
    "supabase": {
        "can_automate": False,
        "can_manage_manually": True,
        "manual_note": "Reset your service role key in the Supabase dashboard, then use 'Set new key' in the PWA to push it everywhere. Don't rotate the JWT secret — that invalidates all keys at once.",
        "provider": {"type": "script", "generate_script": ""},
        "health_check": {"url": "https://{{project_ref}}.supabase.co/rest/v1/", "method": "GET", "expected_status": 200, "auth_header": "apikey", "auth_header_value": "{key}"},
        "env_vars": ["SUPABASE_SERVICE_ROLE_KEY"],
        "console_url": "https://supabase.com/dashboard/project/_/settings/api",
    },
    "vercel": {
        "can_automate": False,
        "can_manage_manually": True,
        "manual_note": "Create a new token at vercel.com/account/tokens, then use 'Set new key' in the PWA to update your .env files. Note: can't write back to Vercel env vars using the token being rotated.",
        "provider": {"type": "script", "generate_script": ""},
        "env_vars": ["VERCEL_TOKEN"],
        "console_url": "https://vercel.com/account/tokens",
    },
    "aws": {
        "can_automate": True,
        "provider": {"type": "script", "generate_script": "~/.config/key-rotator/scripts/aws-gen.sh", "revoke_script": "~/.config/key-rotator/scripts/aws-revoke.sh"},
        "health_check": {"url": "https://sts.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15", "method": "GET", "expected_status": 200},
        "schedule": "0 3 1 * *",
        "setup_note": "Requires aws CLI configured. Script creates/deletes IAM access keys.",
        "env_vars": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    },
    "twilio": {
        "can_automate": False,
        "reason": "Twilio Auth Tokens can't be rotated via API.",
        "env_vars": ["TWILIO_AUTH_TOKEN"],
    },
    "sendgrid": {
        "can_automate": True,
        "provider": {"type": "script", "generate_script": "~/.config/key-rotator/scripts/sendgrid-gen.sh"},
        "health_check": {"url": "https://api.sendgrid.com/v3/scopes", "method": "GET", "expected_status": 200, "auth_header": "Authorization", "auth_header_value": "Bearer {key}"},
        "schedule": "0 3 1 * *",
        "setup_note": "Run: key-rotator set-secret {id} mgmt.admin_key  (paste your SendGrid admin API key)",
        "env_vars": ["SENDGRID_API_KEY"],
    },
}

# Keyword → service name mapping
_KEYWORDS = {
    "resend": "resend",
    "stripe": "stripe",
    "anthropic": "anthropic", "claude": "anthropic", "anthropic console": "anthropic",
    "github": "github", "gh": "github",
    "openai": "openai", "chatgpt": "openai", "gpt": "openai",
    "supabase": "supabase",
    "vercel": "vercel",
    "aws": "aws", "amazon": "aws", "s3": "aws", "lambda": "aws",
    "twilio": "twilio",
    "sendgrid": "sendgrid",
}


def _detect_services(text: str) -> list[str]:
    """Detect service names from free-text stack description."""
    text_lower = text.lower()
    found = []
    for keyword, service in _KEYWORDS.items():
        if keyword in text_lower and service not in found:
            found.append(service)
    return found


def _detect_vercel_projects(text: str) -> list[str]:
    """Try to extract Vercel project names from the text."""
    projects = []
    # Look for patterns like "project: foo-bar" or "foo.vercel.app" or known project names
    matches = re.findall(r'([a-z][a-z0-9-]+)\.vercel\.app', text.lower())
    projects.extend(matches)
    return list(set(projects))


def _detect_env_paths(text: str) -> list[str]:
    """Extract .env file paths from the text."""
    return re.findall(r'[~/][^\s]+\.env', text)


def _build_suggested_config(services: list[str], vercel_projects: list[str], env_paths: list[str]) -> dict:
    """Build a suggested config dict from detected services."""
    keys = []
    manual_keys = []

    for service in services:
        info = _SERVICE_DB.get(service)
        if not info:
            continue

        key_id = f"{service}_main"
        env_var = info["env_vars"][0]

        stores = []
        for path in env_paths:
            stores.append({"type": "dotenv", "path": path, "var": env_var})
        for project in vercel_projects:
            stores.append({"type": "vercel", "project": project, "var": env_var, "env": "production"})

        entry = {
            "id": key_id,
            "provider": info["provider"],
            "stores": stores,
        }
        if "health_check" in info:
            entry["health_check"] = info["health_check"]
        if "schedule" in info:
            entry["schedule"] = info["schedule"]

        if info.get("can_automate"):
            keys.append({
                "config": entry,
                "setup_note": info.get("setup_note", "").replace("{id}", key_id),
                "can_automate": True,
            })
        elif info.get("can_manage_manually"):
            manual_keys.append({
                "config": entry,
                "manual_note": info.get("manual_note", ""),
                "console_url": info.get("console_url", ""),
                "can_automate": False,
            })
        # else: truly unmanageable — omit entirely

    return {"keys": keys, "manual_keys": manual_keys}


@app.post("/api/parse-stack", dependencies=[Depends(_check_token)])
async def parse_stack(body: dict):
    """Parse a free-text stack description and return suggested config entries."""
    text = body.get("text", "")
    if not text.strip():
        raise HTTPException(400, "text is required")

    services = _detect_services(text)
    vercel_projects = _detect_vercel_projects(text)
    env_paths = _detect_env_paths(text)

    suggestion = _build_suggested_config(services, vercel_projects, env_paths)

    return {
        "detected_services": services,
        "suggestion": suggestion,
    }


@app.post("/api/apply-config", dependencies=[Depends(_check_token)])
async def apply_config(body: dict):
    """Merge suggested key entries into the live config file."""
    new_keys = body.get("keys", [])
    if not new_keys:
        raise HTTPException(400, "keys is required")

    config = _load_config()
    existing_ids = {k["id"] for k in config.get("keys", [])}

    added = []
    skipped = []
    for key in new_keys:
        if key["id"] in existing_ids:
            skipped.append(key["id"])
        else:
            config.setdefault("keys", []).append(key)
            added.append(key["id"])

    _config_path.write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))
    return {"added": added, "skipped": skipped}


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/keys", dependencies=[Depends(_check_token)])
async def list_keys():
    config = _load_config()
    return [
        {
            "id": k["id"],
            "provider": k.get("provider", {}).get("type"),
            "schedule": k.get("schedule"),
            "stores": [s["type"] for s in k.get("stores", [])],
            "has_health_check": "health_check" in k,
            "pending_failure": k["id"] in _pending,
            "is_manual": k.get("provider", {}).get("type") == "script" and not k.get("schedule"),
            "has_backup": bool(get_backup_value(k["id"])),
        }
        for k in config.get("keys", [])
    ]


@app.post("/api/keys/{key_id}/set-value", dependencies=[Depends(_check_token)])
async def set_value(key_id: str, body: dict):
    """
    Write a user-supplied key value to all configured stores.
    Backs up the old value first. Optionally runs health check.
    """
    new_value = body.get("value", "").strip()
    if not new_value:
        raise HTTPException(400, "value is required")
    run_health_check = body.get("run_health_check", True)

    key_cfg = _find_key(key_id)
    stores_cfg = key_cfg.get("stores", [])
    health_cfg = key_cfg.get("health_check") if run_health_check else None

    # Backup current value from first readable store or existing vault backup
    old_value = None
    for s_cfg in stores_cfg:
        store_obj = get_store(s_cfg["type"])
        old_value = store_obj.read(s_cfg)
        if old_value:
            break
    if not old_value:
        old_value = get_backup_value(key_id)

    if old_value:
        from .vault import backup_value
        backup_value(key_id, old_value)

    # Health check against new value before writing
    if health_cfg:
        from .core import _health_check
        if not _health_check(health_cfg, new_value):
            raise HTTPException(400, "Health check failed — new key not written to stores. Check the value and try again.")

    # Write to all stores
    results = []
    for s_cfg in stores_cfg:
        store_obj = get_store(s_cfg["type"])
        try:
            store_obj.write(s_cfg, new_value)
            results.append({"store": store_obj.label(s_cfg), "ok": True})
        except Exception as e:
            results.append({"store": store_obj.label(s_cfg), "ok": False, "error": str(e)})

    return {
        "ok": True,
        "had_old_value": bool(old_value),
        "results": results,
    }


@app.get("/api/keys/{key_id}/backup", dependencies=[Depends(_check_token)])
async def get_backup(key_id: str):
    """Return info about the backed-up old key value (masked — never returns full value)."""
    _find_key(key_id)  # 404 if not found
    backup = get_backup_value(key_id)
    if not backup:
        return {"has_backup": False}

    # Mask: show first 8 chars and last 4, rest as bullets
    visible_start = min(8, len(backup))
    visible_end = min(4, len(backup) - visible_start)
    if visible_end > 0:
        preview = backup[:visible_start] + "•" * max(0, len(backup) - visible_start - visible_end) + backup[-visible_end:]
    else:
        preview = backup[:visible_start] + "•" * max(0, len(backup) - visible_start)

    return {
        "has_backup": True,
        "preview": preview,
        "full_value": backup,  # sent to client so user can copy — stays in memory, never logged
    }


@app.delete("/api/keys/{key_id}/backup", dependencies=[Depends(_check_token)])
async def clear_backup(key_id: str):
    """Remove the backed-up old key value from the vault."""
    _find_key(key_id)
    from .vault import delete
    delete(key_id, "backup_value")
    return {"ok": True}


@app.get("/api/scheduler", dependencies=[Depends(_check_token)])
async def scheduler_status():
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "key-rotator.service"],
            capture_output=True, text=True, timeout=5,
        )
        return {"status": r.stdout.strip()}
    except Exception:
        return {"status": "unknown"}


@app.post("/api/keys/{key_id}/restore", dependencies=[Depends(_check_token)])
async def restore_key(key_id: str):
    key_cfg = _find_key(key_id)
    backup = get_backup_value(key_id)
    if not backup:
        raise HTTPException(400, "No backup value in vault for this key")

    results = []
    for s_cfg in key_cfg.get("stores", []):
        store_obj = get_store(s_cfg["type"])
        try:
            store_obj.write(s_cfg, backup)
            results.append({"store": store_obj.label(s_cfg), "ok": True})
        except Exception as e:
            results.append({"store": store_obj.label(s_cfg), "ok": False, "error": str(e)})
    return {"results": results}


@app.post("/api/keys/{key_id}/revoke", dependencies=[Depends(_check_token)])
async def revoke_key(key_id: str, body: dict):
    key_cfg = _find_key(key_id)
    provider_key_id = body.get("provider_key_id")
    if not provider_key_id:
        raise HTTPException(400, "provider_key_id required")
    provider = get_provider(key_cfg["provider"]["type"])
    try:
        provider.revoke(key_cfg["provider"], key_id, provider_key_id)
        _pending.pop(key_id, None)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/keys/{key_id}/pending/resolve", dependencies=[Depends(_check_token)])
async def resolve_pending(key_id: str, body: dict):
    """
    Resolve a pending health-check failure.
    action: "force_write" | "revoke_new" | "dismiss"
    """
    pending = _pending.get(key_id)
    if not pending:
        raise HTTPException(400, "No pending failure for this key")

    action = body.get("action")
    key_cfg = _find_key(key_id)
    provider = get_provider(pending["provider_cfg"]["type"])
    stores = [(get_store(s["type"]), s) for s in key_cfg.get("stores", [])]

    if action == "force_write":
        results = []
        for store_obj, s_cfg in stores:
            try:
                store_obj.write(s_cfg, pending["new_key_value"])
                results.append({"store": store_obj.label(s_cfg), "ok": True})
            except Exception as e:
                results.append({"store": store_obj.label(s_cfg), "ok": False, "error": str(e)})
        _pending.pop(key_id, None)
        return {"action": "force_write", "results": results}

    elif action == "revoke_new":
        try:
            provider.revoke(pending["provider_cfg"], key_id, pending["new_key_id"])
            _pending.pop(key_id, None)
            return {"action": "revoke_new", "ok": True}
        except Exception as e:
            raise HTTPException(500, str(e))

    elif action == "dismiss":
        _pending.pop(key_id, None)
        return {"action": "dismiss"}

    else:
        raise HTTPException(400, f"Unknown action: {action}")


# ── WebSocket rotation ────────────────────────────────────────────────────────

@app.websocket("/ws/rotate/{key_id}")
async def ws_rotate(websocket: WebSocket, key_id: str, token: str = ""):
    await websocket.accept()

    if token != get_or_create_token():
        await websocket.send_json({"type": "error", "msg": "Unauthorized"})
        await websocket.close(code=1008)
        return

    try:
        init = await asyncio.wait_for(websocket.receive_json(), timeout=3.0)
        dry_run = init.get("dry_run", False)
    except (asyncio.TimeoutError, Exception):
        dry_run = False

    try:
        key_cfg = _find_key(key_id)
    except HTTPException:
        await websocket.send_json({"type": "error", "msg": f"Key not found: {key_id}"})
        await websocket.close()
        return

    queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def emit(event: dict) -> None:
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def run() -> None:
        try:
            result = rotate_key(key_cfg, dry_run=dry_run, emit=emit, interactive=False)
            if not result["success"] and result.get("pending"):
                _pending[key_id] = result["pending"]
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "done", "success": result["success"], "has_pending": bool(result.get("pending"))}),
                loop,
            )
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "error", "msg": str(e)}),
                loop,
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    threading.Thread(target=run, daemon=True).start()

    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
