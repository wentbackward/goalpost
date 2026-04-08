from abc import ABC, abstractmethod
from typing import Optional

from ..models import Post


class ProviderError(Exception):
    def __init__(self, platform: str, post_id: str | None = None, message: str = ""):
        self.platform = platform
        self.post_id = post_id
        super().__init__(f"[{platform}] post={post_id}: {message}" if post_id else f"[{platform}]: {message}")


class BaseProvider(ABC):
    platform: str

    @abstractmethod
    async def is_configured(self) -> bool:
        """Return True if all required env vars are present."""
        ...

    @abstractmethod
    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        """
        Fetch current engagement metrics for a single post.
        Return a dict matching post_metrics columns, or None if unavailable.
        Raise ProviderError on hard failures.
        """
        ...
