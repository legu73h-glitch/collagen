"""Loader for the scientifically verified collagen knowledge base."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_KB_PATH = Path(__file__).resolve().parent.parent / "data" / "collagen_knowledge_base.json"


@dataclass(frozen=True)
class KnowledgeBase:
    """Structured access to the collagen knowledge base."""

    raw: dict[str, Any]
    path: Path

    @property
    def definitions(self) -> dict[str, Any]:
        return self.raw["definitions"]

    @property
    def collagen_types(self) -> dict[str, Any]:
        return self.raw["collagen_types"]

    @property
    def plant_claim(self) -> dict[str, Any]:
        return self.raw["plant_based_collagen_claim"]

    @property
    def misleading_practices(self) -> list[dict[str, Any]]:
        return self.raw["common_misleading_practices"]

    @property
    def verification_rubric(self) -> dict[str, Any]:
        return self.raw["verification_rubric"]

    @property
    def sources(self) -> list[str]:
        return self.raw["meta"]["sources"]

    def as_system_prompt_section(self) -> str:
        """Render the KB as a compact section suitable for a system prompt."""
        return json.dumps(self.raw, ensure_ascii=False, indent=2)


@lru_cache(maxsize=4)
def load_knowledge_base(path: str | Path | None = None) -> KnowledgeBase:
    kb_path = Path(path) if path else DEFAULT_KB_PATH
    with kb_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return KnowledgeBase(raw=data, path=kb_path)
