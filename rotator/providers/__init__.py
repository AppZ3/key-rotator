from .base import BaseProvider, RotationResult
from .script import ScriptProvider
from .stripe import StripeProvider
from .resend import ResendProvider

REGISTRY: dict[str, type[BaseProvider]] = {
    "script": ScriptProvider,
    "stripe": StripeProvider,
    "resend": ResendProvider,
}


def get_provider(provider_type: str) -> BaseProvider:
    cls = REGISTRY.get(provider_type)
    if not cls:
        available = ", ".join(REGISTRY)
        raise ValueError(f"Unknown provider '{provider_type}'. Available: {available}")
    return cls()


def register_provider(name: str, cls: type[BaseProvider]) -> None:
    """Register a custom provider at runtime."""
    REGISTRY[name] = cls
