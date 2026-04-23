import httpx
import click
import subprocess
from typing import Callable, Any, Optional

from .vault import backup_value, get_backup_value, store, get
from .providers import get_provider, RotationResult, BaseProvider
from .stores import get_store, BaseStore

Event = dict[str, Any]
EmitFn = Callable[[Event], None]


def _terminal_emit(event: Event) -> None:
    t = event.get("type", "info")
    msg = event.get("msg", "")
    if t == "error":
        click.secho(f"  [FAIL] {msg}", fg="red", err=True)
        _desktop_notify("Key Rotator — FAILED", msg, urgency="critical")
    elif t == "warn":
        click.secho(f"  [WARN] {msg}", fg="yellow")
    elif t == "success":
        click.secho(f"  [OK] {msg}", fg="green")
        _desktop_notify("Key Rotator", f"✓ {msg}")
    else:
        click.echo(f"  {msg}")


def _desktop_notify(title: str, body: str, urgency: str = "normal") -> None:
    try:
        subprocess.run(["notify-send", "-u", urgency, title, body], check=False)
    except FileNotFoundError:
        pass


def rotate_key(
    key_config: dict,
    dry_run: bool = False,
    emit: EmitFn = None,
    interactive: bool = True,
) -> dict:
    """
    Rotate a single key.

    Returns:
        {"success": bool, "key_id": str, "pending": Optional[dict]}

    pending is populated when health check fails. It contains everything needed
    for the caller to offer fix options (force-write, revoke-new, dismiss).
    """
    if emit is None:
        emit = _terminal_emit

    key_id = key_config["id"]
    provider_cfg = key_config["provider"]
    stores_cfg = key_config.get("stores", [])
    health_cfg = key_config.get("health_check")

    emit({"type": "info", "msg": f"Rotating: {key_id}"})

    if dry_run:
        emit({"type": "info", "msg": f"[DRY RUN] provider={provider_cfg['type']} stores={[s['type'] for s in stores_cfg]}"})
        return {"success": True, "key_id": key_id, "pending": None}

    provider = get_provider(provider_cfg["type"])
    stores: list[tuple[BaseStore, dict]] = [(get_store(s["type"]), s) for s in stores_cfg]

    # Read current values from stores (for rollback)
    old_values: list[Optional[str]] = []
    for store_obj, store_cfg in stores:
        old_values.append(store_obj.read(store_cfg))

    vault_backup = get_backup_value(key_id)
    representative_old = next((v for v in old_values if v), vault_backup)
    old_key_id = get(key_id, "current_key_id")

    # Generate new key
    try:
        result = provider.generate(provider_cfg, key_id)
    except Exception as e:
        emit({"type": "error", "msg": f"Generate failed: {e}"})
        return {"success": False, "key_id": key_id, "pending": None}

    # Backup old value to vault before writing new key
    if representative_old:
        backup_value(key_id, representative_old)

    # Write new key to all stores, track which succeeded for rollback
    written: list[tuple[int, BaseStore, dict]] = []
    for i, (store_obj, store_cfg) in enumerate(stores):
        try:
            store_obj.write(store_cfg, result.new_key_value)
            written.append((i, store_obj, store_cfg))
            emit({"type": "info", "msg": f"Written → {store_obj.label(store_cfg)}"})
        except Exception as e:
            emit({"type": "warn", "msg": f"Store write failed ({store_obj.label(store_cfg)}): {e}"})

    # Health check
    if health_cfg:
        emit({"type": "info", "msg": "Running health check..."})
        if not _health_check(health_cfg, result.new_key_value):
            emit({"type": "warn", "msg": "Health check failed — restoring old key..."})
            _restore(written, old_values, emit)

            pending = {
                "new_key_value": result.new_key_value,
                "new_key_id": result.new_key_id,
                "old_key_id": old_key_id,
                "provider_cfg": provider_cfg,
                "stores_cfg": stores_cfg,
                "old_values": old_values,
                "written_indices": [i for i, _, _ in written],
            }

            emit({"type": "error", "msg": "Health check failed — old key restored"})

            if interactive:
                _offer_fix_options_terminal(key_id, result, provider, provider_cfg, health_cfg, written, old_values)

            return {"success": False, "key_id": key_id, "pending": pending}

        emit({"type": "info", "msg": "Health check passed."})

    # Revoke old key
    if result.new_key_id:
        store(key_id, "current_key_id", result.new_key_id)

    try:
        provider.revoke(provider_cfg, key_id, old_key_id)
        if old_key_id:
            emit({"type": "info", "msg": f"Old key revoked ({old_key_id})"})
    except Exception as e:
        emit({"type": "warn", "msg": f"Old key revocation failed: {e}. Revoke manually."})

    emit({"type": "success", "msg": f"{key_id} rotated successfully"})
    return {"success": True, "key_id": key_id, "pending": None}


def _health_check(config: dict, new_value: str) -> bool:
    url = config["url"]
    method = config.get("method", "GET").upper()
    expected_status = config.get("expected_status", 200)
    header_name = config.get("auth_header", "Authorization")
    header_template = config.get("auth_header_value", "Bearer {key}")
    headers = {header_name: header_template.format(key=new_value)}
    try:
        resp = httpx.request(method, url, headers=headers, timeout=10)
        return resp.status_code == expected_status
    except Exception:
        return False


def _restore(written: list[tuple[int, BaseStore, dict]], old_values: list[Optional[str]], emit: EmitFn) -> None:
    for i, store_obj, store_cfg in written:
        old = old_values[i]
        if old:
            try:
                store_obj.write(store_cfg, old)
                emit({"type": "info", "msg": f"Restored → {store_obj.label(store_cfg)}"})
            except Exception as e:
                emit({"type": "warn", "msg": f"Restore failed ({store_obj.label(store_cfg)}): {e}"})
        else:
            emit({"type": "warn", "msg": f"No backup for {store_obj.label(store_cfg)} — could not restore"})


def _offer_fix_options_terminal(
    key_id, result, provider, provider_cfg, health_cfg, written, old_values
) -> None:
    click.echo()
    click.secho("What would you like to do?", bold=True)
    click.echo("  [1] Retry health check  (re-writes new key to stores, checks again)")
    click.echo("  [2] Force new key into stores  (skip health check, revoke old when ready)")
    click.echo("  [3] Revoke new key, keep old key active")
    click.echo("  [4] Do nothing  (investigate manually)")
    if result.new_key_id:
        click.echo(f"\n  New key ID (still active): {result.new_key_id}")
    click.echo(f"  Old key backup in vault — restore with: key-rotator restore {key_id}")
    click.echo()

    choice = click.prompt("Choice", type=click.Choice(["1", "2", "3", "4"]), default="4")

    if choice == "1":
        for _, store_obj, store_cfg in written:
            try:
                store_obj.write(store_cfg, result.new_key_value)
            except Exception as e:
                click.secho(f"  Re-write failed ({store_obj.label(store_cfg)}): {e}", fg="red")
        if _health_check(health_cfg, result.new_key_value):
            click.secho("  Health check passed.", fg="green")
            old_key_id = get(key_id, "current_key_id")
            if result.new_key_id:
                store(key_id, "current_key_id", result.new_key_id)
            try:
                provider.revoke(provider_cfg, key_id, old_key_id)
            except Exception as e:
                click.secho(f"  Revoke failed: {e}", fg="red")
            click.secho(f"  [OK] {key_id} rotated successfully", fg="green")
        else:
            click.secho("  Health check failed again. Restoring old key.", fg="red")
            _restore(written, old_values, _terminal_emit)

    elif choice == "2":
        for _, store_obj, store_cfg in written:
            try:
                store_obj.write(store_cfg, result.new_key_value)
                click.secho(f"  Written → {store_obj.label(store_cfg)}", fg="green")
            except Exception as e:
                click.secho(f"  Write failed: {e}", fg="red")
        click.secho("  New key in stores. Old key still active.", fg="yellow")
        if result.new_key_id:
            click.echo(f"  Revoke command: key-rotator revoke {key_id} {result.new_key_id}")

    elif choice == "3":
        try:
            provider.revoke(provider_cfg, key_id, result.new_key_id)
            click.secho("  New key revoked. Old key remains active.", fg="green")
        except Exception as e:
            click.secho(f"  Revoke failed: {e}", fg="red")

    else:
        click.echo(f"  Restore: key-rotator restore {key_id}")
        if result.new_key_id:
            click.echo(f"  Revoke:  key-rotator revoke {key_id} {result.new_key_id}")
