"""Offline tests for analyzer plumbing (no real API calls)."""
from unittest.mock import MagicMock

from src.analyzer import SUBMIT_REPORT_TOOL, CollagenAnalyzer, _extract_tool_input
from src.models import Product


def _fake_response(tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_verification_report"
    block.input = tool_input
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "tool_use"
    return resp


def test_extract_tool_input_returns_dict():
    resp = _fake_response({"verdict": "compliant", "overall_severity": "none"})
    out = _extract_tool_input(resp, "submit_verification_report")
    assert out == {"verdict": "compliant", "overall_severity": "none"}


def test_tool_schema_has_required_fields():
    props = SUBMIT_REPORT_TOOL["input_schema"]["properties"]
    assert "verdict" in props
    assert "overall_severity" in props
    assert "discrepancies" in props
    assert set(SUBMIT_REPORT_TOOL["input_schema"]["required"]) == {
        "verdict",
        "overall_severity",
        "summary",
        "discrepancies",
    }


def test_analyzer_parses_structured_output():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {
            "verdict": "misleading",
            "overall_severity": "high",
            "summary": "Гидролизат выдаётся за нативный коллаген.",
            "discrepancies": [
                {
                    "practice_id": "HYDROLYSATE_AS_COLLAGEN",
                    "severity": "high",
                    "evidence_quote": "100% чистый коллаген",
                    "scientific_basis": "Продукт содержит только гидролизат.",
                    "required_fix": "Заменить 'коллаген' на 'гидролизат коллагена'.",
                }
            ],
            "references": ["León-López 2019"],
        }
    )

    analyzer = CollagenAnalyzer(client=client)
    product = Product(
        company="Test",
        product_name="X",
        declared_ingredients="Гидролизат коллагена",
        marketing_claims=["100% чистый коллаген"],
    )
    report = analyzer.analyze(product)

    assert report.verdict == "misleading"
    assert report.overall_severity.value == "high"
    assert len(report.discrepancies) == 1
    assert report.discrepancies[0].practice_id == "HYDROLYSATE_AS_COLLAGEN"

    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {
        "type": "tool",
        "name": "submit_verification_report",
    }
    # Cache control must be set on the KB block for prompt caching.
    system_blocks = call_kwargs["system"]
    assert any("cache_control" in b for b in system_blocks)
