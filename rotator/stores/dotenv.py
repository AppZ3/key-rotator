"""
Store adapter for .env files.

Example config:
  stores:
    - type: dotenv
      path: /home/z/Projects/outreach-tool/.env
      var: STRIPE_SECRET_KEY
"""
import re
from pathlib import Path
from typing import Optional
from .base import BaseStore


class DotenvStore(BaseStore):
    def label(self, config: dict) -> str:
        return f"dotenv:{config['path']}:{config['var']}"

    def read(self, config: dict) -> Optional[str]:
        path = Path(config["path"])
        var = config["var"]
        if not path.exists():
            return None
        for line in path.read_text().splitlines():
            m = re.match(rf"^{re.escape(var)}\s*=\s*(.+)$", line.strip())
            if m:
                return m.group(1).strip().strip('"').strip("'")
        return None

    def write(self, config: dict, value: str) -> None:
        path = Path(config["path"])
        var = config["var"]
        content = path.read_text() if path.exists() else ""
        new_line = f'{var}="{value}"'
        pattern = rf"^{re.escape(var)}\s*=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + f"\n{new_line}\n"
        path.write_text(content)
