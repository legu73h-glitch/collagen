"""CLI-level tests for idea loading and pipeline selection (no API calls)."""
import json
from types import SimpleNamespace

import pytest

from product_agent.cli import _load_idea, _selected_slugs
from product_agent.pipeline import MINIMAL_SLUGS


def _args(**kw):
    base = dict(idea=None, summary=None, name=None, audience=None, constraint=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_load_idea_from_summary():
    idea = _load_idea(_args(summary="обмен сменами", name="ShiftSwap", constraint=["3 мес"]))
    assert idea.name == "ShiftSwap"
    assert idea.constraints == ["3 мес"]


def test_load_idea_from_file(tmp_path):
    path = tmp_path / "idea.json"
    path.write_text(json.dumps({"summary": "идея", "name": "P"}), encoding="utf-8")
    idea = _load_idea(_args(idea=str(path)))
    assert idea.name == "P"


def test_load_idea_from_list_takes_first(tmp_path):
    path = tmp_path / "ideas.json"
    path.write_text(json.dumps([{"summary": "первая"}, {"summary": "вторая"}]), encoding="utf-8")
    idea = _load_idea(_args(idea=str(path)))
    assert idea.summary == "первая"


def test_load_idea_scalar_json_exits_cleanly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("42", encoding="utf-8")  # top-level scalar, not an object
    with pytest.raises(SystemExit) as exc:
        _load_idea(_args(idea=str(path)))
    assert exc.value.code == 2


def test_load_idea_null_json_exits_cleanly(tmp_path):
    path = tmp_path / "null.json"
    path.write_text("null", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _load_idea(_args(idea=str(path)))
    assert exc.value.code == 2


def test_load_idea_list_of_scalars_exits_cleanly(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps(["just a string"]), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _load_idea(_args(idea=str(path)))
    assert exc.value.code == 2


def test_load_idea_missing_source_exits_cleanly():
    with pytest.raises(SystemExit) as exc:
        _load_idea(_args())  # neither --idea nor --summary
    assert exc.value.code == 2


def test_selected_slugs_minimal_and_only():
    assert _selected_slugs(_args_run(minimal=True, only=None)) == list(MINIMAL_SLUGS)
    assert _selected_slugs(_args_run(minimal=False, only="brief-writing, lean-canvas")) == [
        "brief-writing",
        "lean-canvas",
    ]
    assert _selected_slugs(_args_run(minimal=False, only=None)) is None


def _args_run(**kw):
    return SimpleNamespace(**kw)
