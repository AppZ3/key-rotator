"""
Stripe provider — creates and revokes Restricted API Keys via the Stripe API.

Note: Only restricted keys can be rotated programmatically. Main secret keys
require the Stripe dashboard. Create a restricted key with the needed permissions
and use that instead.

Required vault credential: mgmt.admin_key (a Stripe secret key with rak_* write access)

Example config:
  provider:
    type: stripe
    name: "my-service-rotated"
    permissions:
      - "charges:read"
      - "customers:write"
"""
import httpx
from .base import BaseProvider, RotationResult
from ..vault import get_mgmt_cred

_BASE = "https://api.stripe.com/v1"


class StripeProvider(BaseProvider):
    def generate(self, config: dict, key_id: str) -> RotationResult:
        admin_key = get_mgmt_cred(key_id, "admin_key")
        if not admin_key:
            raise RuntimeError(f"No vault credential 'mgmt.admin_key' for {key_id}. Run: key-rotator set-secret {key_id} mgmt.admin_key")

        name = config.get("name", f"rotated-{key_id}")
        permissions = config.get("permissions", [])

        data: dict = {"type": "restricted", "name": name}
        for p in permissions:
            data.setdefault("permissions[]", []).append(p)

        resp = httpx.post(f"{_BASE}/v2/api_keys", auth=(admin_key, ""), data=data, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        return RotationResult(new_key_value=body["secret"], new_key_id=body["id"])

    def revoke(self, config: dict, key_id: str, old_key_id) -> None:
        if not old_key_id:
            return
        admin_key = get_mgmt_cred(key_id, "admin_key")
        resp = httpx.post(f"{_BASE}/v2/api_keys/{old_key_id}/expire", auth=(admin_key, ""), timeout=15)
        resp.raise_for_status()
