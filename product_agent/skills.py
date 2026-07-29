"""Loader for the bundled discovery skills.

Each skill lives in ``skills/<slug>/SKILL.md`` and starts with a YAML
frontmatter block (name, description, inputs, outputs, metadata.tools) followed
by the markdown body. The body is fed to Claude as the system prompt for that
node, so the skill file — not code — is the source of behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class Skill:
    """A parsed SKILL.md file."""

    slug: str
    name: str
    description: str
    inputs: list[str]
    outputs: list[str]
    tools: list[str]
    metadata: dict[str, Any]
    body: str
    path: Path

    def as_system_prompt(self) -> str:
        """The skill body used verbatim as the system instruction of the node."""
        return self.body.strip()


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a ``---`` delimited YAML frontmatter from the markdown body."""
    stripped = text.lstrip("﻿")
    if not stripped.startswith("---"):
        return {}, text
    # Frontmatter is between the first and the second '---' line.
    parts = stripped.split("\n")
    if parts[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    front_raw = "\n".join(parts[1:end])
    body = "\n".join(parts[end + 1 :])
    front = yaml.safe_load(front_raw) or {}
    if not isinstance(front, dict):
        front = {}
    return front, body


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def load_skill(slug: str, skills_dir: Path | None = None) -> Skill:
    base = skills_dir or DEFAULT_SKILLS_DIR
    path = base / slug / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    front, body = _split_frontmatter(text)
    metadata = front.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return Skill(
        slug=slug,
        name=str(front.get("name", slug)),
        description=str(front.get("description", "")).strip(),
        inputs=_as_list(front.get("inputs")),
        outputs=_as_list(front.get("outputs")),
        tools=_as_list(metadata.get("tools")),
        metadata=metadata,
        body=body,
        path=path,
    )


@dataclass(frozen=True)
class SkillLibrary:
    """In-memory registry of discovery skills keyed by slug."""

    skills: dict[str, Skill] = field(default_factory=dict)
    skills_dir: Path = DEFAULT_SKILLS_DIR

    def get(self, slug: str) -> Skill:
        try:
            return self.skills[slug]
        except KeyError as exc:
            raise KeyError(
                f"Скилл '{slug}' не найден. Доступны: {sorted(self.skills)}"
            ) from exc

    def __contains__(self, slug: object) -> bool:
        return slug in self.skills

    def __iter__(self):
        return iter(self.skills.values())


@lru_cache(maxsize=4)
def load_skill_library(skills_dir: str | Path | None = None) -> SkillLibrary:
    base = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
    skills: dict[str, Skill] = {}
    for child in sorted(base.iterdir()):
        skill_file = child / "SKILL.md"
        if child.is_dir() and skill_file.exists():
            skills[child.name] = load_skill(child.name, skills_dir=base)
    return SkillLibrary(skills=skills, skills_dir=base)
