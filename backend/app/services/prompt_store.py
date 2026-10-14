"""Prompt versioning.

Prompts live in the DB (not code), versioned per name, with one active version.
This lets you edit/rollback a prompt without redeploying, and every /v1/ask call
logs which version it used (so eval can A/B two versions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class PromptTemplate:
    name: str
    version: int
    body: str

    @property
    def variables(self) -> list[str]:
        return sorted(set(_VAR_RE.findall(self.body)))

    def render(self, **kwargs: str) -> str:
        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            if key not in kwargs:
                raise KeyError(f"missing prompt variable '{key}'")
            return kwargs[key]

        return _VAR_RE.sub(repl, self.body)


class PromptStore(Protocol):
    async def add(self, *, name: str, body: str, created_by: str = "system") -> PromptTemplate: ...
    async def get(self, *, name: str, version: int | None = None) -> PromptTemplate | None: ...
    async def set_active(self, *, name: str, version: int) -> bool: ...
    async def list_versions(self, *, name: str) -> list[int]: ...


DEFAULT_RAG_PROMPT = (
    "You are a precise assistant. Answer the question using ONLY the provided context.\n"
    "If the context is insufficient, say you don't know. Cite sources by their [n] markers.\n\n"
    "Context:\n{{context}}\n\nQuestion: {{question}}\n\nAnswer:"
)


class InMemoryPromptStore:
    def __init__(self, seed_default: bool = True) -> None:
        # name -> {version: template}, plus active pointer
        self._by_name: dict[str, dict[int, PromptTemplate]] = {}
        self._active: dict[str, int] = {}
        if seed_default:
            tpl = PromptTemplate(name="rag_default", version=1, body=DEFAULT_RAG_PROMPT)
            self._by_name["rag_default"] = {1: tpl}
            self._active["rag_default"] = 1

    async def add(self, *, name: str, body: str, created_by: str = "system") -> PromptTemplate:
        versions = self._by_name.setdefault(name, {})
        version = (max(versions) + 1) if versions else 1
        tpl = PromptTemplate(name=name, version=version, body=body)
        versions[version] = tpl
        self._active.setdefault(name, version)
        return tpl

    async def get(self, *, name: str, version: int | None = None) -> PromptTemplate | None:
        versions = self._by_name.get(name)
        if not versions:
            return None
        v = version if version is not None else self._active.get(name)
        return versions.get(v) if v is not None else None

    async def set_active(self, *, name: str, version: int) -> bool:
        if name in self._by_name and version in self._by_name[name]:
            self._active[name] = version
            return True
        return False

    async def list_versions(self, *, name: str) -> list[int]:
        return sorted(self._by_name.get(name, {}))
