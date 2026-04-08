from .base import BaseProvider, ProviderError
from .facebook import FacebookProvider
from .instagram import InstagramProvider
from .linkedin import LinkedInProvider
from .twitter import TwitterProvider
from .youtube import YouTubeProvider

PROVIDER_REGISTRY: list[type[BaseProvider]] = [
    TwitterProvider,
    LinkedInProvider,
    InstagramProvider,
    FacebookProvider,
    YouTubeProvider,
]


async def get_configured_providers() -> list[BaseProvider]:
    providers = []
    for cls in PROVIDER_REGISTRY:
        provider = cls()
        if await provider.is_configured():
            providers.append(provider)
    return providers


async def get_all_providers() -> list[BaseProvider]:
    return [cls() for cls in PROVIDER_REGISTRY]


__all__ = [
    "BaseProvider",
    "ProviderError",
    "PROVIDER_REGISTRY",
    "get_configured_providers",
    "get_all_providers",
]
