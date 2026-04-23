"""
Generic provider that delegates to user-defined shell scripts.

Generate script: must print the new key value to stdout (nothing else).
  Env vars available: KEY_ROTATOR_KEY_ID

Revoke script: optional, called after successful health check.
  Env vars available: KEY_ROTATOR_KEY_ID, OLD_KEY_ID

Example config:
  provider:
    type: script
    generate_script: /home/z/.config/key-rotator/scripts/gen-anthropic.sh
    revoke_script: /home/z/.config/key-rotator/scripts/revoke-anthropic.sh
"""
import os
import sys
import subprocess
from .base import BaseProvider, RotationResult


def _run_script(script: str, extra_env: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, **extra_env}
    if sys.platform == "win32":
        # On Windows, wrap .ps1 scripts automatically; plain strings run via cmd
        if script.strip().lower().endswith(".ps1"):
            args = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script]
            return subprocess.run(args, capture_output=True, text=True, env=env)
    return subprocess.run(script, shell=True, capture_output=True, text=True, env=env)


class ScriptProvider(BaseProvider):
    """
    Generic provider using user-defined scripts.

    Linux/macOS: any shell script (bash, python, etc.)
    Windows: cmd string, or a .ps1 path (auto-wrapped with powershell)

    Generate script must print ONLY the new key value on stdout.
    Revoke script is optional; receives OLD_KEY_ID env var.
    """

    def generate(self, config: dict, key_id: str) -> RotationResult:
        script = config["generate_script"]
        result = _run_script(script, {"KEY_ROTATOR_KEY_ID": key_id})
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Script exited {result.returncode}")
        new_value = result.stdout.strip()
        if not new_value:
            raise RuntimeError("Generate script produced no output")
        return RotationResult(new_key_value=new_value)

    def revoke(self, config: dict, key_id: str, old_key_id) -> None:
        script = config.get("revoke_script")
        if not script:
            return
        _run_script(script, {"KEY_ROTATOR_KEY_ID": key_id, "OLD_KEY_ID": old_key_id or ""})
