"""Orchestration layer: verification + letter generation + persistence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic

from .analyzer import CollagenAnalyzer
from .knowledge_base import KnowledgeBase, load_knowledge_base
from .models import ComplianceLetter, Product, VerificationReport
from .notifier import LetterGenerator


@dataclass
class AgentResult:
    product: Product
    report: VerificationReport
    letter: ComplianceLetter | None


class CollagenAgent:
    """End-to-end agent: verify a product and, if needed, draft a compliance letter."""

    def __init__(
        self,
        client: Anthropic | None = None,
        kb: KnowledgeBase | None = None,
        reports_dir: str | Path = "reports",
    ) -> None:
        self.client = client or Anthropic()
        self.kb = kb or load_knowledge_base()
        self.analyzer = CollagenAnalyzer(client=self.client, kb=self.kb)
        self.letter_generator = LetterGenerator(client=self.client, kb=self.kb)
        self.reports_dir = Path(reports_dir)

    def process(self, product: Product, save: bool = True) -> AgentResult:
        report = self.analyzer.analyze(product)
        letter = None
        if report.verdict == "misleading" and report.discrepancies:
            letter = self.letter_generator.generate(report)

        result = AgentResult(product=product, report=report, letter=letter)
        if save:
            self._persist(result)
        return result

    def process_batch(self, products: list[Product], save: bool = True) -> list[AgentResult]:
        return [self.process(p, save=save) for p in products]

    def _persist(self, result: AgentResult) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        slug = _slugify(f"{result.product.company}-{result.product.product_name}")
        base = self.reports_dir / f"{timestamp}_{slug}"

        with (base.with_suffix(".report.json")).open("w", encoding="utf-8") as fh:
            json.dump(
                result.report.model_dump(mode="json"),
                fh,
                ensure_ascii=False,
                indent=2,
            )
        if result.letter is not None:
            with (base.with_suffix(".letter.json")).open("w", encoding="utf-8") as fh:
                json.dump(
                    result.letter.model_dump(mode="json"),
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )
            with (base.with_suffix(".letter.md")).open("w", encoding="utf-8") as fh:
                fh.write(f"# {result.letter.subject}\n\n")
                fh.write(f"**Получатель:** {result.letter.recipient_company}\n\n")
                if result.letter.recipient_email:
                    fh.write(f"**Email:** {result.letter.recipient_email}\n\n")
                if result.letter.recipient_address:
                    fh.write(f"**Адрес:** {result.letter.recipient_address}\n\n")
                fh.write("---\n\n")
                fh.write(result.letter.body)


def _slugify(text: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in text.lower())
    return safe[:80].strip("_")
