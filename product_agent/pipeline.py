"""Discovery pipeline definition: the DAG of nodes and how to order them.

The pipeline turns one ``idea`` into a package of seven artifacts. Node order
below is the canonical discovery order requested for this agent; it is also a
valid topological order — every node's required inputs are produced by an
earlier node (``idea`` is the always-available pipeline input).

    1. brief-writing       → brief            (idea)
    2. market-research     → market           (brief)            [web search]
    3. persona-generation  → personas         (brief)
    4. lean-canvas         → lean_canvas       (brief, market?, personas?)
    5. user-story-mapping  → story_map         (brief, personas?)
    6. wireframe-spec      → wireframes        (story_map)
    7. persona-interview   → interview_report  (personas, brief)
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The pseudo-artifact that seeds the pipeline; always available to every node.
IDEA = "idea"


@dataclass(frozen=True)
class NodeSpec:
    """One node of the discovery pipeline."""

    slug: str  # skill folder slug (must exist in the skill library)
    artifact_id: str  # id of the artifact this node produces
    title: str  # human title of the produced artifact
    required_inputs: tuple[str, ...] = ()  # artifacts the node cannot run without
    optional_inputs: tuple[str, ...] = ()  # artifacts that enrich but are not required
    needs_web_search: bool = False

    @property
    def all_inputs(self) -> tuple[str, ...]:
        return self.required_inputs + self.optional_inputs


# Canonical pipeline, in execution order.
PIPELINE: tuple[NodeSpec, ...] = (
    NodeSpec(
        slug="brief-writing",
        artifact_id="brief",
        title="Бриф",
        required_inputs=(),
    ),
    NodeSpec(
        slug="market-research",
        artifact_id="market",
        title="Market Research",
        required_inputs=("brief",),
        needs_web_search=True,
    ),
    NodeSpec(
        slug="persona-generation",
        artifact_id="personas",
        title="Персоны",
        required_inputs=("brief",),
    ),
    NodeSpec(
        slug="lean-canvas",
        artifact_id="lean_canvas",
        title="Lean Canvas",
        required_inputs=("brief",),
        optional_inputs=("market", "personas"),
    ),
    NodeSpec(
        slug="user-story-mapping",
        artifact_id="story_map",
        title="User Story Map",
        required_inputs=("brief",),
        optional_inputs=("personas",),
    ),
    NodeSpec(
        slug="wireframe-spec",
        artifact_id="wireframes",
        title="Вайрфреймы",
        required_inputs=("story_map",),
    ),
    NodeSpec(
        slug="persona-interview",
        artifact_id="interview_report",
        title="Отчёт custdev-интервью",
        required_inputs=("personas", "brief"),
    ),
)

# The three-node starter pipeline recommended by the source WORKFLOW.
MINIMAL_SLUGS: tuple[str, ...] = (
    "brief-writing",
    "user-story-mapping",
    "wireframe-spec",
)


def _by_slug() -> dict[str, NodeSpec]:
    return {n.slug: n for n in PIPELINE}


def _producer_of() -> dict[str, NodeSpec]:
    return {n.artifact_id: n for n in PIPELINE}


def node_for_slug(slug: str) -> NodeSpec:
    try:
        return _by_slug()[slug]
    except KeyError as exc:
        raise KeyError(
            f"Нода '{slug}' не входит в конвейер. Доступны: {[n.slug for n in PIPELINE]}"
        ) from exc


def validate_pipeline() -> None:
    """Assert the declared order is a valid topological order.

    Raises ValueError if any node references an input that no earlier node
    (or the idea) produces, or if artifact ids / slugs are not unique.
    """
    slugs = [n.slug for n in PIPELINE]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Дублирующиеся slug нод в конвейере")
    ids = [n.artifact_id for n in PIPELINE]
    if len(ids) != len(set(ids)):
        raise ValueError("Дублирующиеся artifact_id в конвейере")

    available = {IDEA}
    for node in PIPELINE:
        for dep in node.all_inputs:
            if dep not in available:
                raise ValueError(
                    f"Нода '{node.slug}' требует '{dep}', который ещё не произведён "
                    f"на этом шаге. Доступно: {sorted(available)}"
                )
        available.add(node.artifact_id)


def resolve_nodes(selected_slugs: list[str] | tuple[str, ...] | None = None) -> list[NodeSpec]:
    """Return the nodes to run, in pipeline order.

    - ``None`` runs the full pipeline.
    - A subset is expanded to include the transitive producers of every
      *required* input, so the run is always self-consistent. Optional inputs
      are wired in only when their producer is already part of the run.
    - Raises ValueError if a required input cannot be produced within the run
      (i.e. its producer is not in the pipeline at all).
    """
    if selected_slugs is None:
        return list(PIPELINE)

    by_slug = _by_slug()
    producer = _producer_of()

    wanted: set[str] = set()

    def include(slug: str) -> None:
        if slug in wanted:
            return
        if slug not in by_slug:
            raise ValueError(
                f"Нода '{slug}' не входит в конвейер. "
                f"Доступны: {[n.slug for n in PIPELINE]}"
            )
        wanted.add(slug)
        node = by_slug[slug]
        for dep in node.required_inputs:
            if dep == IDEA:
                continue
            if dep not in producer:
                raise ValueError(
                    f"Нода '{slug}' требует артефакт '{dep}', но его никто не производит."
                )
            include(producer[dep].slug)

    for slug in selected_slugs:
        include(slug)

    return [n for n in PIPELINE if n.slug in wanted]


def inputs_present(node: NodeSpec, available_ids: set[str]) -> list[str]:
    """Which of the node's declared inputs are actually available now."""
    return [dep for dep in node.all_inputs if dep in available_ids]


def missing_required(node: NodeSpec, available_ids: set[str]) -> list[str]:
    """Required inputs (other than the idea) that are not yet available."""
    return [
        dep
        for dep in node.required_inputs
        if dep != IDEA and dep not in available_ids
    ]
