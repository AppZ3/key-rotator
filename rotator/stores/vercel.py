"""
Store adapter for Vercel project environment variables (via Vercel CLI).

Requires `vercel` CLI to be installed and authenticated.
Vercel does not expose env values via CLI for security, so this store
cannot read back values — it relies on the vault backup instead.

Example config:
  stores:
    - type: vercel
      project: outreach-tool-navy
      var: STRIPE_SECRET_KEY
      env: production          # optional, default: production
      git_branch: main         # optional, for preview envs
"""
import subprocess
from typing import Optional
from .base import BaseStore


class VercelStore(BaseStore):
    def label(self, config: dict) -> str:
        return f"vercel:{config['project']}:{config['var']}"

    def read(self, config: dict) -> Optional[str]:
        # Vercel CLI doesn't expose env values — vault backup is used instead
        return None

    def write(self, config: dict, value: str) -> None:
        project = config["project"]
        var = config["var"]
        env = config.get("env", "production")

        # Remove existing value (ignore error if it doesn't exist)
        subprocess.run(
            ["vercel", "env", "rm", var, env, "--yes", "--project", project],
            capture_output=True,
            check=False,
        )

        # Add new value via stdin to avoid shell history exposure
        args = ["vercel", "env", "add", var, env]
        if "git_branch" in config:
            args += ["--git-branch", config["git_branch"]]
        args += ["--project", project]

        result = subprocess.run(args, input=value, text=True, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"vercel env add failed (exit {result.returncode})")
