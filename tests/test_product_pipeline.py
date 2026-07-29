"""Tests for the discovery pipeline DAG: validation, ordering, subset resolution."""
import pytest

from product_agent.pipeline import (
    IDEA,
    MINIMAL_SLUGS,
    PIPELINE,
    inputs_present,
    missing_required,
    node_for_slug,
    resolve_nodes,
    validate_pipeline,
)


def test_pipeline_is_a_valid_topological_order():
    # Must not raise: every node's inputs are produced earlier (or are the idea).
    validate_pipeline()


def test_pipeline_has_seven_nodes_in_requested_order():
    slugs = [n.slug for n in PIPELINE]
    assert slugs == [
        "brief-writing",
        "market-research",
        "persona-generation",
        "lean-canvas",
        "user-story-mapping",
        "wireframe-spec",
        "persona-interview",
    ]


def test_artifact_ids_are_unique_and_expected():
    ids = [n.artifact_id for n in PIPELINE]
    assert ids == [
        "brief",
        "market",
        "personas",
        "lean_canvas",
        "story_map",
        "wireframes",
        "interview_report",
    ]
    assert len(ids) == len(set(ids))


def test_only_market_needs_web_search():
    web = [n.slug for n in PIPELINE if n.needs_web_search]
    assert web == ["market-research"]


def test_resolve_full_pipeline():
    nodes = resolve_nodes(None)
    assert [n.slug for n in nodes] == [n.slug for n in PIPELINE]


def test_resolve_minimal_pipeline():
    nodes = resolve_nodes(list(MINIMAL_SLUGS))
    # brief is a required input of user-story-mapping and gets pulled in; personas
    # is only optional for story_map so it stays out of the minimal run.
    assert [n.slug for n in nodes] == [
        "brief-writing",
        "user-story-mapping",
        "wireframe-spec",
    ]


def test_subset_pulls_required_dependencies_in_order():
    # Asking only for lean-canvas must pull its required 'brief' producer, and
    # the result is returned in canonical pipeline order.
    nodes = resolve_nodes(["lean-canvas"])
    slugs = [n.slug for n in nodes]
    assert "brief-writing" in slugs
    assert "lean-canvas" in slugs
    assert slugs.index("brief-writing") < slugs.index("lean-canvas")
    # Optional inputs (market, personas) are NOT force-included.
    assert "market-research" not in slugs
    assert "persona-generation" not in slugs


def test_subset_wireframes_pulls_story_map_and_brief():
    nodes = resolve_nodes(["wireframe-spec"])
    slugs = [n.slug for n in nodes]
    assert slugs == ["brief-writing", "user-story-mapping", "wireframe-spec"]


def test_interview_pulls_personas_and_brief():
    nodes = resolve_nodes(["persona-interview"])
    slugs = [n.slug for n in nodes]
    assert set(slugs) == {"brief-writing", "persona-generation", "persona-interview"}
    assert slugs.index("brief-writing") < slugs.index("persona-generation")
    assert slugs.index("persona-generation") < slugs.index("persona-interview")


def test_unknown_slug_raises():
    with pytest.raises(ValueError):
        resolve_nodes(["nope"])


def test_node_for_slug_roundtrip():
    node = node_for_slug("market-research")
    assert node.artifact_id == "market"
    with pytest.raises(KeyError):
        node_for_slug("nope")


def test_inputs_present_and_missing_required():
    lean = node_for_slug("lean-canvas")
    # Only brief available.
    assert inputs_present(lean, {"brief"}) == ["brief"]
    assert missing_required(lean, {"brief"}) == []
    # Nothing available -> brief is a missing required input.
    assert missing_required(lean, set()) == ["brief"]

    market = node_for_slug("market-research")
    assert missing_required(market, set()) == ["brief"]
    assert missing_required(market, {"brief"}) == []


def test_idea_is_never_a_missing_required_input():
    brief = node_for_slug("brief-writing")
    # brief-writing consumes the idea, which is always available.
    assert missing_required(brief, set()) == []
    assert IDEA == "idea"
