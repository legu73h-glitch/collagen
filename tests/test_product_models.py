"""Tests for discovery pipeline models."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from product_agent.models import Artifact, DiscoveryPackage, Idea


def test_idea_requires_summary():
    with pytest.raises(ValidationError):
        Idea()  # type: ignore[call-arg]


def test_idea_display_name_prefers_name():
    assert Idea(summary="какая-то длинная идея", name="X").display_name() == "X"
    # Falls back to a truncated summary when no name.
    idea = Idea(summary="а" * 100)
    assert len(idea.display_name()) <= 60


def test_idea_prompt_block_contains_fields():
    idea = Idea(
        summary="обмен сменами",
        name="ShiftSwap",
        constraints=["бюджет $40k", "3 месяца"],
        audience="сменные сотрудники",
        notes="важная заметка",
    )
    block = idea.as_prompt_block()
    assert "ShiftSwap" in block
    assert "обмен сменами" in block
    assert "бюджет $40k" in block
    assert "сменные сотрудники" in block
    assert "важная заметка" in block


def test_package_add_is_last_write_wins():
    package = DiscoveryPackage(idea=Idea(summary="x"))
    package.add(Artifact(id="brief", node="brief-writing", title="Бриф", content="v1", model="m"))
    package.add(Artifact(id="brief", node="brief-writing", title="Бриф", content="v2", model="m"))
    assert len(package.artifacts) == 1
    assert package.get("brief").content == "v2"


def test_package_has_and_get():
    package = DiscoveryPackage(idea=Idea(summary="x"))
    assert not package.has("brief")
    package.add(Artifact(id="brief", node="brief-writing", title="Бриф", content="c", model="m"))
    assert package.has("brief")
    assert package.get("market") is None


def test_package_as_markdown_includes_all_artifacts():
    package = DiscoveryPackage(idea=Idea(summary="идея", name="P"))
    package.add(Artifact(id="brief", node="brief-writing", title="Бриф", content="# Бриф\ntext", model="m"))
    package.add(
        Artifact(
            id="market",
            node="market-research",
            title="Market",
            content="# Market\ntext",
            model="m",
            used_web_search=True,
        )
    )
    md = package.as_markdown()
    assert "# Discovery Package: P" in md
    assert "artifact: brief" in md
    assert "artifact: market" in md
    assert "web search" in md


def test_example_ideas_file_is_valid():
    path = Path(__file__).resolve().parent.parent / "data" / "example_ideas.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    ideas = [Idea(**item) for item in data]
    assert len(ideas) >= 1
    assert ideas[0].name == "ShiftSwap"
    assert ideas[0].constraints
