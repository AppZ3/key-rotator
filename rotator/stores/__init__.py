from .base import BaseStore
from .dotenv import DotenvStore
from .vercel import VercelStore
from .system_env import SystemEnvStore

REGISTRY: dict[str, type[BaseStore]] = {
    "dotenv": DotenvStore,
    "vercel": VercelStore,
    "system_env": SystemEnvStore,
}


def get_store(store_type: str) -> BaseStore:
    cls = REGISTRY.get(store_type)
    if not cls:
        available = ", ".join(REGISTRY)
        raise ValueError(f"Unknown store '{store_type}'. Available: {available}")
    return cls()


def register_store(name: str, cls: type[BaseStore]) -> None:
    """Register a custom store at runtime."""
    REGISTRY[name] = cls
