"""Node runner: turn one NodeSpec into an Artifact via a single Claude call.

Each node uses its bundled SKILL.md body as the (cached) system prompt and
receives the idea plus every already-produced upstream artifact in the user
message. The market-research node additionally gets the server-side web search
tool, with graceful fallback when the tool is unavailable.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from anthropic import Anthropic

from .models import Artifact, DiscoveryPackage, Idea
from .pipeline import NodeSpec, inputs_present, missing_required
from .skills import Skill, SkillLibrary, load_skill_library

DEFAULT_MODEL = os.environ.get("PRODUCT_AGENT_MODEL", "claude-opus-4-7")

# Server-side web search tool (Anthropic). Only attached to nodes that need it.
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 8,
}

# Reinforces the pipeline rules from the source WORKFLOW on top of each skill.
PIPELINE_PREAMBLE = """Ты работаешь как автономная нода discovery-конвейера, а не в чате.

Правила ноды:
1. Не задавай вопросов. Пробелы во входе закрывай обоснованным допущением с меткой [assumption].
2. Строгий выход: верни ТОЛЬКО целевой артефакт по шаблону скилла — без вступлений, \
пояснений и текста после артефакта.
3. Единый предмет: название продукта и проблему бери из входных артефактов без искажений.
4. Язык — русский.

Ниже — полная инструкция скилла этой ноды. Следуй ей."""


# Human-readable headers for artifacts injected into the user message.
_ARTIFACT_HEADERS = {
    "idea": "idea (идея продукта)",
    "brief": "brief (продуктовый бриф)",
    "market": "market (рыночный срез)",
    "personas": "personas (персоны)",
    "lean_canvas": "lean_canvas (Lean Canvas)",
    "story_map": "story_map (User Story Map)",
    "wireframes": "wireframes (вайрфреймы)",
    "interview_report": "interview_report (отчёт custdev)",
}


def _is_web_search_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = ("web_search", "web search", "not enabled", "not supported", "tool")
    return any(m in text for m in markers)


class NodeRunner:
    """Runs a single pipeline node against the Anthropic API."""

    def __init__(
        self,
        client: Anthropic | None = None,
        library: SkillLibrary | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
        enable_web_search: bool = True,
    ) -> None:
        self.client = client or Anthropic()
        self.library = library or load_skill_library()
        self.model = model
        self.max_tokens = max_tokens
        self.enable_web_search = enable_web_search

    # -- message building ---------------------------------------------------

    def _build_system(self, skill: Skill) -> list[dict[str, Any]]:
        # Small stable preamble, then the (large, stable) skill body cached so
        # batch runs over many ideas reuse the prompt prefix.
        return [
            {"type": "text", "text": PIPELINE_PREAMBLE},
            {
                "type": "text",
                "text": skill.as_system_prompt(),
                "cache_control": {"type": "ephemeral"},
            },
        ]

    def _build_user_message(
        self, node: NodeSpec, idea: Idea, package: DiscoveryPackage
    ) -> str:
        available = {a.id for a in package.artifacts}
        present = inputs_present(node, available)

        blocks = [
            "Произведи артефакт по инструкции скилла.\n",
            f"Целевой артефакт: {node.artifact_id} — {node.title}.\n",
            "<idea>",
            idea.as_prompt_block(),
            "</idea>",
            "",
        ]

        for dep in present:
            artifact = package.get(dep)
            if artifact is None:
                continue
            header = _ARTIFACT_HEADERS.get(dep, dep)
            blocks.append(f"<{dep}>")
            blocks.append(f"<!-- {header} -->")
            blocks.append(artifact.content.strip())
            blocks.append(f"</{dep}>")
            blocks.append("")

        missing = missing_required(node, available)
        if missing:
            blocks.append(
                "Недоступные входные артефакты (восстанови нужное допущениями "
                f"[assumption]): {', '.join(missing)}."
            )
            blocks.append("")

        blocks.append(
            f"Верни ТОЛЬКО артефакт {node.artifact_id} по шаблону скилла, без лишнего текста."
        )
        return "\n".join(blocks)

    # -- execution ----------------------------------------------------------

    def _tools(self, node: NodeSpec) -> list[dict[str, Any]] | None:
        if node.needs_web_search and self.enable_web_search:
            return [WEB_SEARCH_TOOL]
        return None

    def run(
        self, node: NodeSpec, idea: Idea, package: DiscoveryPackage
    ) -> Artifact:
        skill = self.library.get(node.slug)
        system = self._build_system(skill)
        user = self._build_user_message(node, idea, package)
        tools = self._tools(node)

        used_web_search = False
        if tools is not None:
            try:
                response = self._create(system, user, tools=tools)
                used_web_search = True
            except Exception as exc:  # noqa: BLE001 - graceful web-search fallback
                if not _is_web_search_error(exc):
                    raise
                # Web search unavailable — the skill knows to degrade and flag it.
                response = self._create(system, user, tools=None)
        else:
            response = self._create(system, user, tools=None)

        content = _extract_text(response)
        if not content:
            raise RuntimeError(
                f"Нода '{node.slug}' вернула пустой ответ "
                f"(stop_reason={getattr(response, 'stop_reason', None)})."
            )

        return Artifact(
            id=node.artifact_id,
            node=node.slug,
            title=node.title,
            content=content,
            model=self.model,
            used_web_search=used_web_search,
        )

    def _create(
        self,
        system: list[dict[str, Any]],
        user: str,
        tools: list[dict[str, Any]] | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if tools:
            kwargs["tools"] = tools
        return self.client.messages.create(**kwargs)


def _extract_text(response: Any) -> str:
    """Concatenate the assistant's text blocks, skipping tool-use / search blocks."""
    chunks: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


# Optional progress callback type: called with the node about to run.
ProgressCallback = Callable[[NodeSpec], None]
