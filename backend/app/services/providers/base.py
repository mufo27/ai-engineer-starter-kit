"""Shared provider contract + data types.

A provider is any object exposing `name`, `available()`, and an async
`complete()`. Adding a new vendor = implement this protocol and register it in
the ProviderRegistry — the router never needs to change (Open/Closed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelSpec:
    """A routable model + its pricing. `provider` must match a registered provider name."""

    provider: str
    model: str
    input_price_per_m: float   # USD per 1M input tokens
    output_price_per_m: float  # USD per 1M output tokens
    max_output_tokens: int = 1024
    tier: int = 1              # 1=cheap, 2=balanced, 3=smart


@dataclass
class ProviderResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    raw: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this provider is configured (has a key/client) and usable."""
        ...

    async def complete(
        self, messages: list[ChatMessage], *, model: str, max_output_tokens: int = 1024
    ) -> ProviderResult:
        ...


def compute_cost(spec: ModelSpec, prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * spec.input_price_per_m
        + completion_tokens / 1_000_000 * spec.output_price_per_m
    )


def estimate_tokens(text: str) -> int:
    """Cheap token estimate when tiktoken is unavailable (chars/4)."""
    return max(1, len(text) // 4)
