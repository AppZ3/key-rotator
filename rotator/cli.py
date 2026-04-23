import sys
import yaml
import click
from pathlib import Path
from .core import rotate_key, _restore
from .stores import get_store
from .providers import get_provider
from .vault import store, get, get_backup_value

DEFAULT_CONFIG = Path.home() / ".config" / "key-rotator" / "config.yaml"


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        click.secho(f"Config not found: {config_path}", fg="red")
        click.echo("Create one from the example: cp config.example.yaml ~/.config/key-rotator/config.yaml")
        sys.exit(1)
    return yaml.safe_load(config_path.read_text())


def _find_key(config: dict, key_id: str) -> dict:
    for k in config.get("keys", []):
        if k["id"] == key_id:
            return k
    click.secho(f"No key with id '{key_id}' in config.", fg="red")
    sys.exit(1)


@click.group()
@click.option("--config", "-c", default=str(DEFAULT_CONFIG), show_default=True, help="Path to config.yaml")
@click.pass_context
def cli(ctx, config):
    """Automated API key rotation with rollback and health checks."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config)


@cli.command()
@click.argument("key_id", required=False)
@click.option("--dry-run", is_flag=True, help="Show what would happen without making changes")
@click.pass_context
def rotate(ctx, key_id, dry_run):
    """Rotate one key (KEY_ID) or all keys if none specified."""
    config = _load_config(ctx.obj["config_path"])
    keys = config.get("keys", [])

    if key_id:
        keys = [_find_key(config, key_id)]

    if not keys:
        click.secho("No keys configured.", fg="yellow")
        return

    failed = [k["id"] for k in keys if not rotate_key(k, dry_run=dry_run)]

    if failed:
        click.secho(f"\nFailed: {', '.join(failed)}", fg="red")
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """List all configured keys, their schedule, and store targets."""
    config = _load_config(ctx.obj["config_path"])
    keys = config.get("keys", [])
    if not keys:
        click.echo("No keys configured.")
        return

    click.secho(f"{'ID':<35} {'PROVIDER':<12} {'SCHEDULE':<20} STORES", bold=True)
    click.echo("─" * 90)
    for k in keys:
        stores = ", ".join(s["type"] for s in k.get("stores", []))
        schedule = k.get("schedule", "—")
        provider = k.get("provider", {}).get("type", "—")
        click.echo(f"{k['id']:<35} {provider:<12} {schedule:<20} {stores}")


@cli.command("set-secret")
@click.argument("key_id")
@click.argument("field")
@click.pass_context
def set_secret(ctx, key_id, field):
    """Store a secret in the keyring (value is prompted, never echoed).

    \b
    Examples:
      key-rotator set-secret stripe_live mgmt.admin_key
      key-rotator set-secret resend_main mgmt.admin_key
    """
    value = click.prompt(f"Value for {key_id}.{field}", hide_input=True, confirmation_prompt=True)
    store(key_id, field, value)
    click.secho(f"Stored {key_id}.{field} in GNOME Keyring.", fg="green")


@cli.command()
@click.argument("key_id")
@click.pass_context
def restore(ctx, key_id):
    """Restore the vault-backed pre-rotation value for KEY_ID to all its stores."""
    config = _load_config(ctx.obj["config_path"])
    key_cfg = _find_key(config, key_id)

    backup = get_backup_value(key_id)
    if not backup:
        click.secho(f"No backup value in vault for {key_id}.", fg="red")
        sys.exit(1)

    stores_cfg = key_cfg.get("stores", [])
    click.echo(f"Restoring {key_id} to {len(stores_cfg)} store(s)...")
    for s_cfg in stores_cfg:
        store_obj = get_store(s_cfg["type"])
        try:
            store_obj.write(s_cfg, backup)
            click.secho(f"  Restored → {store_obj.label(s_cfg)}", fg="green")
        except Exception as e:
            click.secho(f"  Failed ({store_obj.label(s_cfg)}): {e}", fg="red")


@cli.command()
@click.argument("key_id")
@click.argument("provider_key_id")
@click.pass_context
def revoke(ctx, key_id, provider_key_id):
    """Manually revoke a provider-side key by its provider ID (e.g. after a failed rotation)."""
    config = _load_config(ctx.obj["config_path"])
    key_cfg = _find_key(config, key_id)
    provider_cfg = key_cfg["provider"]
    provider = get_provider(provider_cfg["type"])

    click.echo(f"Revoking {provider_key_id} via {provider_cfg['type']}...")
    try:
        provider.revoke(provider_cfg, key_id, provider_key_id)
        click.secho("Done.", fg="green")
    except Exception as e:
        click.secho(f"Failed: {e}", fg="red")
        sys.exit(1)


@cli.command("run-scheduler")
@click.pass_context
def run_scheduler(ctx):
    """Start the APScheduler daemon (used by the systemd service)."""
    from .scheduler import run
    run(ctx.obj["config_path"])


@cli.command()
@click.confirmation_option(prompt="This will remove the Key Rotator background services. Continue?")
def uninstall():
    """Remove background services (scheduler + web server)."""
    from .platform_setup import uninstall as _uninstall
    try:
        _uninstall()
    except Exception as e:
        click.secho(f"Error: {e}", fg="red")
        sys.exit(1)


@cli.command("install")
def install_services():
    """Install background services (scheduler + web server) for your platform.

    \b
    Linux  → systemd user services (auto-start on login)
    macOS  → launchd agents        (auto-start on login)
    Windows → Task Scheduler       (run at logon)
    """
    from .platform_setup import install as _install
    try:
        _install()
    except Exception as e:
        click.secho(f"Error: {e}", fg="red")
        sys.exit(1)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=7821, show_default=True)
@click.option("--show-token", is_flag=True, help="Print the auth token and URL, then exit")
def serve(host, port, show_token):
    """Start the PWA web server (binds to localhost only)."""
    from .server import get_or_create_token
    token = get_or_create_token()

    url = f"http://{host}:{port}/?token={token}"

    if show_token:
        click.echo(f"\nToken: {token}")
        click.echo(f"URL:   {url}\n")
        return

    click.secho(f"\nKey Rotator PWA", bold=True)
    click.echo(f"Open in browser (token auto-sets): {url}")
    click.echo(f"Ctrl+C to stop\n")

    import uvicorn
    from .server import app
    uvicorn.run(app, host=host, port=port, log_level="warning")
