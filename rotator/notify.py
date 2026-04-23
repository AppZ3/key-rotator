import subprocess
import sys
import click


def _desktop(title: str, body: str, urgency: str = "normal") -> None:
    try:
        if sys.platform == "linux":
            subprocess.run(["notify-send", "-u", urgency, title, body], check=False)
        elif sys.platform == "darwin":
            script = f'display notification "{body}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=False)
        elif sys.platform == "win32":
            # Windows Toast via PowerShell (no extra deps)
            ps = (
                f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;'
                f'$t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02;'
                f'$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($t);'
                f'$x.GetElementsByTagName("text")[0].AppendChild($x.CreateTextNode("{title}")) | Out-Null;'
                f'$x.GetElementsByTagName("text")[1].AppendChild($x.CreateTextNode("{body}")) | Out-Null;'
                f'$n = [Windows.UI.Notifications.ToastNotification]::new($x);'
                f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Key Rotator").Show($n);'
            )
            subprocess.run(["powershell", "-Command", ps], check=False, capture_output=True)
    except (FileNotFoundError, OSError):
        pass


def success(key_id: str) -> None:
    click.secho(f"  [OK] {key_id} rotated successfully", fg="green")
    _desktop("Key Rotator", f"✓ {key_id} rotated")


def failure(key_id: str, error: str) -> None:
    click.secho(f"  [FAIL] {key_id}: {error}", fg="red", err=True)
    _desktop("Key Rotator — FAILED", f"{key_id}: {error}", urgency="critical")


def warn(msg: str) -> None:
    click.secho(f"  [WARN] {msg}", fg="yellow")


def info(msg: str) -> None:
    click.echo(f"  {msg}")
