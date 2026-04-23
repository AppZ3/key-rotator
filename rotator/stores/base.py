from abc import ABC, abstractmethod
from typing import Optional


class BaseStore(ABC):
    @abstractmethod
    def read(self, config: dict) -> Optional[str]:
        """Read the current key value. Returns None if not found or unreadable."""
        ...

    @abstractmethod
    def write(self, config: dict, value: str) -> None:
        """Write a new key value to the store."""
        ...

    def label(self, config: dict) -> str:
        """Human-readable label for this store instance, used in logs."""
        return repr(config)
