"""Tests for the bundled skill library and its consistency with the pipeline."""
from product_agent.pipeline import PIPELINE
from product_agent.skills import _split_frontmatter, load_skill_library


def test_all_pipeline_skills_are_bundled():
    library = load_skill_library()
    for node in PIPELINE:
        skill = library.get(node.slug)
        assert skill.slug == node.slug
        assert skill.body.strip(), f"У скилла {node.slug} пустое тело"


def test_frontmatter_is_parsed():
    library = load_skill_library()
    brief = library.get("brief-writing")
    assert brief.name == "brief-writing"
    assert brief.description
    assert brief.inputs == ["idea"]
    assert brief.outputs == ["brief"]
    assert brief.metadata.get("role")


def test_only_market_declares_web_search_tool():
    library = load_skill_library()
    for node in PIPELINE:
        skill = library.get(node.slug)
        if node.slug == "market-research":
            assert "web_search" in skill.tools
        else:
            assert "web_search" not in skill.tools


def test_skill_outputs_match_pipeline_artifact_ids():
    library = load_skill_library()
    for node in PIPELINE:
        skill = library.get(node.slug)
        assert node.artifact_id in skill.outputs, (
            f"artifact_id '{node.artifact_id}' ноды {node.slug} "
            f"не совпадает с outputs скилла {skill.outputs}"
        )


def test_skill_declared_inputs_cover_node_inputs():
    # Every artifact the node reads (required or optional, excluding the idea)
    # must be declared as an input of the skill frontmatter.
    library = load_skill_library()
    for node in PIPELINE:
        skill = library.get(node.slug)
        declared = set(skill.inputs)
        for dep in node.all_inputs:
            assert dep in declared, (
                f"Нода {node.slug} читает '{dep}', но скилл заявляет inputs={skill.inputs}"
            )


def test_body_excludes_frontmatter():
    library = load_skill_library()
    market = library.get("market-research")
    assert not market.body.lstrip().startswith("---")
    assert "Market Research" in market.body


def test_split_frontmatter_handles_plain_markdown():
    front, body = _split_frontmatter("# no frontmatter\n\ntext")
    assert front == {}
    assert body == "# no frontmatter\n\ntext"


def test_split_frontmatter_parses_yaml_block():
    text = "---\nname: demo\ninputs: [a, b]\n---\n# Body\ntext"
    front, body = _split_frontmatter(text)
    assert front["name"] == "demo"
    assert front["inputs"] == ["a", "b"]
    assert body.strip().startswith("# Body")
