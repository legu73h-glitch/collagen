"""Pydantic models for the discovery pipeline: idea in, artifact package out."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Idea(BaseModel):
    """Raw product idea — the single input of the whole discovery pipeline."""

    summary: str = Field(
        description="Идея продукта в 1-2 предложениях: что это и какую проблему решает"
    )
    name: str | None = Field(
        default=None, description="Рабочее название продукта/инициативы (если есть)"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Жёсткие ограничения: бюджет, сроки, команда, регуляторка, гео",
    )
    audience: str | None = Field(
        default=None, description="Подсказка по целевой аудитории (если известна)"
    )
    notes: str | None = Field(
        default=None, description="Любой дополнительный контекст для агента"
    )

    def display_name(self) -> str:
        return self.name or self.summary[:60].strip()

    def as_prompt_block(self) -> str:
        """Render the idea as the `idea` artifact fed to every node."""
        lines: list[str] = []
        if self.name:
            lines.append(f"Название: {self.name}")
        lines.append(f"Идея: {self.summary}")
        if self.audience:
            lines.append(f"Аудитория (подсказка): {self.audience}")
        if self.constraints:
            lines.append("Ограничения:")
            lines.extend(f"  - {c}" for c in self.constraints)
        if self.notes:
            lines.append(f"Заметки: {self.notes}")
        return "\n".join(lines)


class Artifact(BaseModel):
    """A single discovery artifact produced by one pipeline node."""

    id: str = Field(description="Идентификатор артефакта, напр. brief, market, personas")
    node: str = Field(description="Slug ноды-производителя, напр. brief-writing")
    title: str = Field(description="Человекочитаемое название артефакта")
    content: str = Field(description="Текст артефакта (markdown по шаблону скилла)")
    model: str = Field(description="Модель, сгенерировавшая артефакт")
    used_web_search: bool = Field(
        default=False, description="Использовался ли веб-поиск при генерации"
    )


class DiscoveryPackage(BaseModel):
    """Ordered collection of artifacts produced for one idea."""

    idea: Idea
    artifacts: list[Artifact] = Field(default_factory=list)

    def get(self, artifact_id: str) -> Artifact | None:
        for a in self.artifacts:
            if a.id == artifact_id:
                return a
        return None

    def has(self, artifact_id: str) -> bool:
        return self.get(artifact_id) is not None

    def add(self, artifact: Artifact) -> None:
        # Last write wins: a re-run of a node replaces its previous artifact.
        self.artifacts = [a for a in self.artifacts if a.id != artifact.id]
        self.artifacts.append(artifact)

    def as_markdown(self) -> str:
        """Assemble every artifact into one discovery package document."""
        parts = [
            f"# Discovery Package: {self.idea.display_name()}",
            "",
            "> Пакет артефактов discovery, собранный из одной идеи продукта.",
            "",
            "## Идея",
            "",
            "```",
            self.idea.as_prompt_block(),
            "```",
            "",
        ]
        for a in self.artifacts:
            ws = " · 🌐 web search" if a.used_web_search else ""
            parts.append("---")
            parts.append("")
            parts.append(f"<!-- artifact: {a.id} · node: {a.node}{ws} -->")
            parts.append("")
            parts.append(a.content.strip())
            parts.append("")
        return "\n".join(parts)
