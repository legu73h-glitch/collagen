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
# Discovery artifacts are long multi-section Russian documents (tables, story
# maps, wireframes) — give them plenty of room and fail loudly on truncation.
DEFAULT_MAX_TOKENS = int(os.environ.get("PRODUCT_AGENT_MAX_TOKENS", "8192"))

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
    # Narrow on purpose: only fall back when the error is clearly about the web
    # search tool, so genuine failures (rate limits, auth, overload) still surface.
    text = str(exc).lower()
    return "web_search" in text or "web search" in text


class NodeRunner:
    """Runs a single pipeline node against the Anthropic API."""

    def __init__(
        self,
        client: Anthropic | None = None,
        library: SkillLibrary | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
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

    # Bound on server-tool continuation rounds when resuming a paused turn.
    MAX_PAUSE_CONTINUATIONS = 4

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
                response, used_web_search = self._run_turn(system, user, tools=tools)
            except Exception as exc:  # noqa: BLE001 - graceful web-search fallback
                if not _is_web_search_error(exc):
                    raise
                # Web search unavailable — the skill knows to degrade and flag it.
                response, _ = self._run_turn(system, user, tools=None)
                used_web_search = False
        else:
            response, _ = self._run_turn(system, user, tools=None)

        if getattr(response, "stop_reason", None) == "max_tokens":
            raise RuntimeError(
                f"Нода '{node.slug}': ответ обрезан лимитом max_tokens={self.max_tokens}. "
                f"Увеличьте PRODUCT_AGENT_MAX_TOKENS и повторите."
            )

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

    def _run_turn(
        self,
        system: list[dict[str, Any]],
        user: str,
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, bool]:
        """Run one node turn, resuming the server-tool loop on `pause_turn`.

        Returns the final response and whether web search was actually invoked
        in any round of the turn.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        response = self._create(system, messages, tools)
        searched = _used_web_search(response)
        rounds = 0
        while (
            getattr(response, "stop_reason", None) == "pause_turn"
            and rounds < self.MAX_PAUSE_CONTINUATIONS
        ):
            messages.append({"role": "assistant", "content": response.content})
            response = self._create(system, messages, tools)
            searched = searched or _used_web_search(response)
            rounds += 1
        return response, searched

    def _create(
        self,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
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


def _used_web_search(response: Any) -> bool:
    """Whether the model actually invoked web search in this response.

    Attaching the tool does not mean the model used it — the server-side tool is
    called at the model's discretion. Detect real usage from the response's tool
    blocks (or, failing that, the usage counters).
    """
    for block in getattr(response, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "web_search_tool_result":
            return True
        if btype == "server_tool_use" and getattr(block, "name", None) == "web_search":
            return True
    usage = getattr(response, "usage", None)
    server = getattr(usage, "server_tool_use", None) if usage is not None else None
    requests = getattr(server, "web_search_requests", 0) if server is not None else 0
    try:
        return bool(requests) and requests > 0
    except TypeError:
        return False


# Optional progress callback type: called with the node about to run.
ProgressCallback = Callable[[NodeSpec], None]
