from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class RotationResult:
    new_key_value: str
    new_key_id: Optional[str] = None  # provider-specific ID used for revocation


class BaseProvider(ABC):
    @abstractmethod
    def generate(self, config: dict, key_id: str) -> RotationResult:
        """Generate a new key. Must NOT revoke the old one — that happens after health check."""
        ...

    @abstractmethod
    def revoke(self, config: dict, key_id: str, old_key_id: Optional[str]) -> None:
        """Revoke the old key after a successful health check."""
        ...
