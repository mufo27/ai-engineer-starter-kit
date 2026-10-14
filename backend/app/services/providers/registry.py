"""Provider registry — maps provider name -> LLMProvider instance.

The router looks providers up here; availability + health live on the provider.
"""
from __future__ import annotations

from app.services.providers.base import LLMProvider


class ProviderRegistry:
    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        self._providers: dict[str, LLMProvider] = {}
        for p in providers or []:
            self.register(p)

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    def is_available(self, name: str) -> bool:
        p = self._providers.get(name)
        return bool(p and p.available())

    def available_names(self) -> set[str]:
        return {n for n, p in self._providers.items() if p.available()}

    def names(self) -> list[str]:
        return list(self._providers)
