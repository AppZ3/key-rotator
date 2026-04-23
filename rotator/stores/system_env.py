"""
Store adapter for a shell-sourceable env file (Linux/macOS) or
a PowerShell profile script (Windows).

Linux/macOS: writes `export VAR='value'` lines.
  Add to ~/.bashrc or ~/.zshrc: source ~/.config/key-rotator/env.sh

Windows: writes `$env:VAR = 'value'` lines to a .ps1 file.
  Add to your PowerShell profile: . "$env:USERPROFILE\\.config\\key-rotator\\env.ps1"

Example config:
  stores:
    - type: system_env
      var: STRIPE_SECRET_KEY
      # path is optional — defaults per platform shown above
"""
import re
import sys
from pathlib import Path
from typing import Optional
from .base import BaseStore


def _default_path() -> Path:
    if sys.platform == "win32":
        return Path.home() / ".config" / "key-rotator" / "env.ps1"
    return Path.home() / ".config" / "key-rotator" / "env.sh"


class SystemEnvStore(BaseStore):
    def label(self, config: dict) -> str:
        path = config.get("path", str(_default_path()))
        return f"system_env:{path}:{config['var']}"

    def read(self, config: dict) -> Optional[str]:
        path = Path(config.get("path", _default_path())).expanduser()
        var = config["var"]
        if not path.exists():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            if sys.platform == "win32":
                m = re.match(rf'^\$env:{re.escape(var)}\s*=\s*["\'](.+?)["\']', line)
            else:
                m = re.match(rf"^export\s+{re.escape(var)}\s*=\s*['\"]?(.+?)['\"]?\s*$", line)
            if m:
                return m.group(1)
        return None

    def write(self, config: dict, value: str) -> None:
        path = Path(config.get("path", _default_path())).expanduser()
        var = config["var"]
        path.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_text(encoding="utf-8") if path.exists() else ""

        if sys.platform == "win32":
            new_line = f'$env:{var} = \'{value}\''
            pattern = rf'^\$env:{re.escape(var)}\s*=.*$'
        else:
            new_line = f"export {var}='{value}'"
            pattern = rf"^export\s+{re.escape(var)}\s*=.*$"

        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + f"\n{new_line}\n"

        path.write_text(content, encoding="utf-8")
