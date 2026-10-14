"""Prompt versioning store."""
from __future__ import annotations

import pytest

from app.services.prompt_store import InMemoryPromptStore, PromptTemplate


def test_template_render_and_variables():
    tpl = PromptTemplate(name="x", version=1, body="Hello {{name}}, context: {{context}}")
    assert tpl.variables == ["context", "name"]
    assert tpl.render(name="Ann", context="ctx") == "Hello Ann, context: ctx"


def test_template_missing_variable_raises():
    tpl = PromptTemplate(name="x", version=1, body="{{a}} {{b}}")
    with pytest.raises(KeyError):
        tpl.render(a="1")


@pytest.mark.asyncio
async def test_versions_increment_and_active_default():
    store = InMemoryPromptStore(seed_default=False)
    v1 = await store.add(name="p", body="one")
    v2 = await store.add(name="p", body="two")
    assert (v1.version, v2.version) == (1, 2)
    active = await store.get(name="p")  # defaults to first-active (v1)
    assert active.version == 1
    assert await store.list_versions(name="p") == [1, 2]


@pytest.mark.asyncio
async def test_set_active_and_rollback():
    store = InMemoryPromptStore(seed_default=False)
    await store.add(name="p", body="one")
    await store.add(name="p", body="two")
    assert await store.set_active(name="p", version=2) is True
    assert (await store.get(name="p")).version == 2
    assert await store.set_active(name="p", version=99) is False  # unknown


@pytest.mark.asyncio
async def test_default_prompt_seeded():
    store = InMemoryPromptStore()
    tpl = await store.get(name="rag_default")
    assert tpl is not None and tpl.version == 1
    assert "{{context}}" in tpl.body and "{{question}}" in tpl.body
