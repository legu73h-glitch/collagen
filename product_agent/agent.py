"""Orchestration: run the discovery pipeline end-to-end and persist the package."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic

from .models import Artifact, DiscoveryPackage, Idea
from .nodes import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, NodeRunner, ProgressCallback
from .pipeline import NodeSpec, resolve_nodes, validate_pipeline
from .skills import SkillLibrary, load_skill_library


@dataclass
class DiscoveryResult:
    idea: Idea
    package: DiscoveryPackage
    order: list[str] = field(default_factory=list)  # node slugs executed, in order
    run_dir: Path | None = None


class DiscoveryAgent:
    """End-to-end discovery agent: idea in, package of artifacts out."""

    def __init__(
        self,
        client: Anthropic | None = None,
        library: SkillLibrary | None = None,
        model: str = DEFAULT_MODEL,
        out_dir: str | Path = "discovery",
        enable_web_search: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        validate_pipeline()
        self.client = client or Anthropic()
        self.library = library or load_skill_library()
        self.model = model
        self.out_dir = Path(out_dir)
        self.runner = NodeRunner(
            client=self.client,
            library=self.library,
            model=model,
            max_tokens=max_tokens,
            enable_web_search=enable_web_search,
        )

    def run(
        self,
        idea: Idea,
        nodes: list[str] | None = None,
        save: bool = True,
        on_node_start: ProgressCallback | None = None,
        on_node_done: ProgressCallback | None = None,
    ) -> DiscoveryResult:
        specs = resolve_nodes(nodes)
        package = DiscoveryPackage(idea=idea, artifacts=[])
        order: list[str] = []

        for spec in specs:
            if on_node_start is not None:
                on_node_start(spec)
            artifact = self.runner.run(spec, idea, package)
            package.add(artifact)
            order.append(spec.slug)
            if on_node_done is not None:
                on_node_done(spec)

        result = DiscoveryResult(idea=idea, package=package, order=order)
        if save:
            result.run_dir = self._persist(result, specs)
        return result

    # -- persistence --------------------------------------------------------

    def _persist(self, result: DiscoveryResult, specs: list[NodeSpec]) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        slug = _slugify(result.idea.display_name())
        run_dir = self.out_dir / f"{timestamp}_{slug}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Individual artifacts, numbered in execution order.
        order_index = {spec.slug: i for i, spec in enumerate(specs, start=1)}
        for artifact in result.package.artifacts:
            idx = order_index.get(artifact.node, 0)
            fname = f"{idx:02d}_{artifact.id}.md"
            (run_dir / fname).write_text(
                _artifact_markdown(artifact), encoding="utf-8"
            )

        # Combined human-readable package.
        (run_dir / "discovery_package.md").write_text(
            result.package.as_markdown(), encoding="utf-8"
        )

        # Structured package for downstream tooling.
        (run_dir / "package.json").write_text(
            json.dumps(result.package.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return run_dir


def _artifact_markdown(artifact: Artifact) -> str:
    ws = " · веб-поиск" if artifact.used_web_search else ""
    header = (
        f"<!-- artifact: {artifact.id} · node: {artifact.node} · "
        f"model: {artifact.model}{ws} -->\n\n"
    )
    return header + artifact.content.strip() + "\n"


def _slugify(text: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in text.lower())
    return safe[:80].strip("_") or "idea"
