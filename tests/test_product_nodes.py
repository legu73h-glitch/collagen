"""Offline tests for the node runner and agent orchestration (no real API calls)."""
from types import SimpleNamespace

import pytest

from product_agent.agent import DiscoveryAgent
from product_agent.models import Artifact, DiscoveryPackage, Idea
from product_agent.nodes import NodeRunner, _extract_text
from product_agent.pipeline import MINIMAL_SLUGS, node_for_slug


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str) -> SimpleNamespace:
    return SimpleNamespace(type="server_tool_use", name=name, input={})


def _fake_response(*blocks) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason="end_turn")


class _FakeMessages:
    """Records calls and returns canned text responses in sequence."""

    def __init__(self, texts):
        self.calls: list[dict] = []
        self._texts = texts
        self._i = 0

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if callable(self._texts):
            text = self._texts(kwargs, self._i)
        else:
            text = self._texts[self._i]
        self._i += 1
        return _fake_response(_text_block(text))


class _FakeClient:
    def __init__(self, texts):
        self.messages = _FakeMessages(texts)


def _idea() -> Idea:
    return Idea(summary="Приложение для обмена сменами", name="ShiftSwap")


# -- text extraction --------------------------------------------------------


def test_extract_text_skips_non_text_blocks():
    resp = _fake_response(
        _tool_block("web_search"),
        _text_block("итоговый отчёт"),
    )
    assert _extract_text(resp) == "итоговый отчёт"


def test_extract_text_joins_multiple_text_blocks():
    resp = _fake_response(_text_block("часть 1"), _text_block("часть 2"))
    assert _extract_text(resp) == "часть 1\nчасть 2"


# -- system / user message building -----------------------------------------


def test_system_has_cached_skill_body():
    client = _FakeClient(["<бриф>"])
    runner = NodeRunner(client=client)
    runner.run(node_for_slug("brief-writing"), _idea(), DiscoveryPackage(idea=_idea()))

    system = client.messages.calls[0]["system"]
    assert len(system) == 2
    # Preamble first (no cache), skill body second (cached for batch reuse).
    assert "cache_control" not in system[0]
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert "Brief Writing" in system[1]["text"]


def test_user_message_includes_upstream_artifacts():
    client = _FakeClient(["story map text"])
    runner = NodeRunner(client=client)
    package = DiscoveryPackage(idea=_idea())
    package.add(
        Artifact(
            id="brief",
            node="brief-writing",
            title="Бриф",
            content="СОДЕРЖИМОЕ-БРИФА",
            model="test",
        )
    )
    runner.run(node_for_slug("user-story-mapping"), _idea(), package)

    user = client.messages.calls[0]["messages"][0]["content"]
    assert "<idea>" in user
    assert "ShiftSwap" in user
    assert "<brief>" in user
    assert "СОДЕРЖИМОЕ-БРИФА" in user
    assert "story_map" in user


def test_missing_required_input_is_flagged_in_user_message():
    client = _FakeClient(["report"])
    runner = NodeRunner(client=client)
    # persona-interview requires personas + brief; provide neither.
    runner.run(node_for_slug("persona-interview"), _idea(), DiscoveryPackage(idea=_idea()))
    user = client.messages.calls[0]["messages"][0]["content"]
    assert "assumption" in user.lower()
    assert "personas" in user
    assert "brief" in user


# -- web search wiring ------------------------------------------------------


def test_web_search_tool_attached_only_to_market():
    client = _FakeClient(["market", "brief"])
    runner = NodeRunner(client=client, enable_web_search=True)

    runner.run(node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea()))
    tools = client.messages.calls[0].get("tools")
    assert tools and tools[0]["type"] == "web_search_20250305"

    runner.run(node_for_slug("brief-writing"), _idea(), DiscoveryPackage(idea=_idea()))
    assert "tools" not in client.messages.calls[1]


def test_used_web_search_true_only_when_model_searches():
    # Model actually invoked the tool: response carries a server_tool_use block.
    searched = SimpleNamespace(
        content=[_tool_block("web_search"), _text_block("отчёт с поиском")],
        stop_reason="end_turn",
    )
    not_searched = _fake_response(_text_block("отчёт без поиска"))

    class _Msgs:
        def __init__(self, resp):
            self.resp = resp

        def create(self, **kwargs):
            return self.resp

    runner_yes = NodeRunner(client=SimpleNamespace(messages=_Msgs(searched)))
    art_yes = runner_yes.run(
        node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea())
    )
    assert art_yes.used_web_search is True

    runner_no = NodeRunner(client=SimpleNamespace(messages=_Msgs(not_searched)))
    art_no = runner_no.run(
        node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea())
    )
    # Tool was offered but never used -> must not over-report.
    assert art_no.used_web_search is False


def test_pause_turn_is_resumed():
    class _Pauser:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    content=[_tool_block("web_search")], stop_reason="pause_turn"
                )
            return _fake_response(_text_block("финальный отчёт"))

    client = SimpleNamespace(messages=_Pauser())
    runner = NodeRunner(client=client)
    art = runner.run(
        node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea())
    )
    # Paused turn was resumed by re-sending the assistant content.
    assert len(client.messages.calls) == 2
    second_messages = client.messages.calls[1]["messages"]
    assert second_messages[-1]["role"] == "assistant"
    assert art.content == "финальный отчёт"
    # Web search happened in the first (paused) round -> still reported.
    assert art.used_web_search is True


def test_max_tokens_truncation_raises():
    truncated = SimpleNamespace(
        content=[_text_block("частичный ответ…")], stop_reason="max_tokens"
    )

    class _Msgs:
        def create(self, **kwargs):
            return truncated

    runner = NodeRunner(client=SimpleNamespace(messages=_Msgs()))
    with pytest.raises(RuntimeError, match="max_tokens"):
        runner.run(node_for_slug("brief-writing"), _idea(), DiscoveryPackage(idea=_idea()))


def test_web_search_disabled_attaches_no_tools():
    client = _FakeClient(["market"])
    runner = NodeRunner(client=client, enable_web_search=False)
    art = runner.run(
        node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea())
    )
    assert "tools" not in client.messages.calls[0]
    assert art.used_web_search is False


def test_web_search_fallback_on_tool_unavailable():
    class _Flaky:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if "tools" in kwargs:
                raise RuntimeError("web_search tool is not enabled for this account")
            return _fake_response(_text_block("отчёт без веб-поиска"))

    client = SimpleNamespace(messages=_Flaky())
    runner = NodeRunner(client=client, enable_web_search=True)
    art = runner.run(
        node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea())
    )
    # First (with tools) failed, second (no tools) succeeded.
    assert len(client.messages.calls) == 2
    assert art.used_web_search is False
    assert "без веб-поиска" in art.content


def test_non_web_search_error_propagates():
    class _Boom:
        def create(self, **kwargs):
            raise RuntimeError("rate limit exceeded")

    client = SimpleNamespace(messages=_Boom())
    runner = NodeRunner(client=client, enable_web_search=True)
    with pytest.raises(RuntimeError, match="rate limit"):
        runner.run(node_for_slug("market-research"), _idea(), DiscoveryPackage(idea=_idea()))


def test_empty_response_raises():
    client = _FakeClient([""])
    runner = NodeRunner(client=client)
    with pytest.raises(RuntimeError, match="пустой ответ"):
        runner.run(node_for_slug("brief-writing"), _idea(), DiscoveryPackage(idea=_idea()))


# -- agent orchestration ----------------------------------------------------


def test_agent_runs_minimal_pipeline_in_order(tmp_path):
    # Return artifact content that encodes the call index so we can assert threading.
    def texts(kwargs, i):
        return f"ARTIFACT-{i}"

    client = _FakeClient(texts)
    agent = DiscoveryAgent(client=client, out_dir=tmp_path)
    result = agent.run(_idea(), nodes=list(MINIMAL_SLUGS), save=True)

    assert result.order == ["brief-writing", "user-story-mapping", "wireframe-spec"]
    assert [a.id for a in result.package.artifacts] == ["brief", "story_map", "wireframes"]

    # The story_map call (2nd) must have received the brief artifact (ARTIFACT-0).
    story_user = client.messages.calls[1]["messages"][0]["content"]
    assert "ARTIFACT-0" in story_user

    # Persistence produced files.
    assert result.run_dir is not None
    assert (result.run_dir / "discovery_package.md").exists()
    assert (result.run_dir / "package.json").exists()
    assert (result.run_dir / "01_brief.md").exists()


def test_agent_full_pipeline_produces_seven_artifacts(tmp_path):
    client = _FakeClient(lambda kwargs, i: f"art-{i}")
    agent = DiscoveryAgent(client=client, out_dir=tmp_path)
    result = agent.run(_idea(), save=False)
    assert len(result.package.artifacts) == 7
    assert result.order[0] == "brief-writing"
    assert result.order[-1] == "persona-interview"
    # lean-canvas (4th call) must see brief, market, personas already produced.
    lean_user = client.messages.calls[3]["messages"][0]["content"]
    for tag in ("<brief>", "<market>", "<personas>"):
        assert tag in lean_user
