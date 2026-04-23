"""
Cross-platform service installation for the scheduler and web server daemons.

Linux  → systemd user services
macOS  → launchd user agents (~/Library/LaunchAgents/)
Windows → Task Scheduler entries (via schtasks)
"""
import shutil
import subprocess
import sys
from pathlib import Path


def _rotator_bin() -> str:
    """Resolve the key-rotator executable path."""
    p = shutil.which("key-rotator")
    if p:
        return p
    # Fall back to the venv next to this file
    venv = Path(__file__).parent.parent / ".venv"
    if sys.platform == "win32":
        candidate = venv / "Scripts" / "key-rotator.exe"
    else:
        candidate = venv / "bin" / "key-rotator"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("key-rotator binary not found. Make sure it's installed and on PATH.")


# ── Linux ─────────────────────────────────────────────────────────────────────

_SYSTEMD_SCHEDULER = """\
[Unit]
Description=API Key Rotator — APScheduler daemon
After=network-online.target graphical-session.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={bin} run-scheduler
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""

_SYSTEMD_WEB = """\
[Unit]
Description=Key Rotator PWA server
After=network.target key-rotator.service

[Service]
Type=simple
ExecStart={bin} serve
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""


def install_linux(bin_path: str) -> None:
    svc_dir = Path.home() / ".config" / "systemd" / "user"
    svc_dir.mkdir(parents=True, exist_ok=True)

    (svc_dir / "key-rotator.service").write_text(_SYSTEMD_SCHEDULER.format(bin=bin_path))
    (svc_dir / "key-rotator-web.service").write_text(_SYSTEMD_WEB.format(bin=bin_path))

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    for svc in ["key-rotator.service", "key-rotator-web.service"]:
        subprocess.run(["systemctl", "--user", "enable", "--now", svc], check=True)

    print("Installed systemd user services:")
    print("  key-rotator.service       (scheduler)")
    print("  key-rotator-web.service   (PWA at http://127.0.0.1:7821)")


# ── macOS ─────────────────────────────────────────────────────────────────────

_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bin}</string>
        {args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""


def install_macos(bin_path: str) -> None:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / "Library" / "Logs" / "key-rotator"
    log_dir.mkdir(parents=True, exist_ok=True)

    services = [
        ("com.keyrotator.scheduler", "run-scheduler", log_dir / "scheduler.log"),
        ("com.keyrotator.web", "serve", log_dir / "web.log"),
    ]

    for label, cmd, log in services:
        plist_path = agents_dir / f"{label}.plist"
        plist_path.write_text(_PLIST.format(
            label=label,
            bin=bin_path,
            args=f"<string>{cmd}</string>",
            log=str(log),
        ))
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)

    print("Installed launchd agents:")
    print("  com.keyrotator.scheduler  (scheduler)")
    print("  com.keyrotator.web        (PWA at http://127.0.0.1:7821)")
    print(f"\nLogs: {log_dir}/")


def uninstall_macos() -> None:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    for label in ["com.keyrotator.scheduler", "com.keyrotator.web"]:
        plist = agents_dir / f"{label}.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            plist.unlink()
    print("Removed launchd agents.")


# ── Windows ───────────────────────────────────────────────────────────────────

def install_windows(bin_path: str) -> None:
    tasks = [
        ("KeyRotatorScheduler", f'"{bin_path}" run-scheduler', "Key Rotator scheduler daemon"),
        ("KeyRotatorWeb", f'"{bin_path}" serve', "Key Rotator PWA server"),
    ]
    for name, cmd, desc in tasks:
        # Delete existing task if present
        subprocess.run(
            ["schtasks", "/Delete", "/TN", name, "/F"],
            capture_output=True,
        )
        # Create task: run at logon, run whether user is logged in or not
        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", name,
                "/TR", cmd,
                "/SC", "ONLOGON",
                "/RL", "HIGHEST",
                "/F",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  Warning: could not create task {name}: {result.stderr.strip()}")
        else:
            # Start immediately
            subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True)

    print("Installed Task Scheduler entries:")
    print("  KeyRotatorScheduler  (scheduler)")
    print("  KeyRotatorWeb        (PWA at http://127.0.0.1:7821)")
    print("\nTo manage: open Task Scheduler and look for 'KeyRotator*'")


def uninstall_windows() -> None:
    for name in ["KeyRotatorScheduler", "KeyRotatorWeb"]:
        subprocess.run(["schtasks", "/End", "/TN", name], capture_output=True)
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
    print("Removed Task Scheduler entries.")


# ── Uninstall Linux ───────────────────────────────────────────────────────────

def uninstall_linux() -> None:
    for svc in ["key-rotator.service", "key-rotator-web.service"]:
        subprocess.run(["systemctl", "--user", "disable", "--now", svc], capture_output=True)
        p = Path.home() / ".config" / "systemd" / "user" / svc
        if p.exists():
            p.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("Removed systemd user services.")


# ── Dispatcher ────────────────────────────────────────────────────────────────

def install() -> None:
    bin_path = _rotator_bin()
    if sys.platform == "linux":
        install_linux(bin_path)
    elif sys.platform == "darwin":
        install_macos(bin_path)
    elif sys.platform == "win32":
        install_windows(bin_path)
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def uninstall() -> None:
    if sys.platform == "linux":
        uninstall_linux()
    elif sys.platform == "darwin":
        uninstall_macos()
    elif sys.platform == "win32":
        uninstall_windows()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
