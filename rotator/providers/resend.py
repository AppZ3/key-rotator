"""
Resend provider — creates and revokes API keys via the Resend API.

Required vault credential: mgmt.admin_key (a Resend API key with full_access)

Example config:
  provider:
    type: resend
    name: "outreach-tool-rotated"
    permission: "full_access"   # or "sending_access"
    domain_id: "abc123"         # optional, restrict to a domain
"""
import httpx
from .base import BaseProvider, RotationResult
from ..vault import get_mgmt_cred

_BASE = "https://api.resend.com"


class ResendProvider(BaseProvider):
    def generate(self, config: dict, key_id: str) -> RotationResult:
        admin_key = get_mgmt_cred(key_id, "admin_key")
        if not admin_key:
            raise RuntimeError(f"No vault credential 'mgmt.admin_key' for {key_id}.")

        payload: dict = {
            "name": config.get("name", f"rotated-{key_id}"),
            "permission": config.get("permission", "full_access"),
        }
        if "domain_id" in config:
            payload["domain_id"] = config["domain_id"]

        resp = httpx.post(
            f"{_BASE}/api-keys",
            headers={"Authorization": f"Bearer {admin_key}"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        return RotationResult(new_key_value=body["token"], new_key_id=str(body["id"]))

    def revoke(self, config: dict, key_id: str, old_key_id) -> None:
        if not old_key_id:
            return
        admin_key = get_mgmt_cred(key_id, "admin_key")
        resp = httpx.delete(
            f"{_BASE}/api-keys/{old_key_id}",
            headers={"Authorization": f"Bearer {admin_key}"},
            timeout=15,
        )
        resp.raise_for_status()
