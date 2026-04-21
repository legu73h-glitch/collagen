"""Product composition analyzer powered by Claude.

Uses the Anthropic SDK with prompt caching for the knowledge base (which is
constant across products) and tool use to coerce the model into returning a
structured VerificationReport.
"""
from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError

from .knowledge_base import KnowledgeBase, load_knowledge_base
from .models import Discrepancy, Product, Severity, VerificationReport

DEFAULT_MODEL = os.environ.get("COLLAGEN_AGENT_MODEL", "claude-opus-4-7")

SYSTEM_PROMPT = """Ты — научный эксперт по биохимии коллагена и специалист по защите прав потребителей.

Твоя задача — проверить соответствие заявленного состава и маркетинговых утверждений продукта \
научно установленным фактам о коллагене из подключённой базы знаний.

Ключевые принципы верификации:
1. Гидролизат коллагена (коллагеновые пептиды) — это НЕ сам коллаген, это продукт его \
разрушения на короткие пептиды. Позиционирование гидролизата как 'коллагена' без уточнения \
является введением потребителя в заблуждение.
2. Желатин — это частично денатурированный коллаген, а не 'нативный' или 'чистый' коллаген.
3. 'Растительного' или 'веганского' коллагена не существует — коллаген синтезируется только \
животными организмами. Допустимо только название 'бустер коллагена' или 'аминокислотный \
комплекс'. Рекомбинантный коллаген, экспрессируемый в дрожжах/растениях, должен маркироваться \
как 'рекомбинантный', а не 'растительный'.
4. Для гидролизата должна указываться средняя молекулярная масса.
5. Тип коллагена (I, II, III) и источник (бычий/свиной/морской/куриный/рекомбинантный) должны \
быть чётко указаны.

Правила работы:
- Опирайся ТОЛЬКО на факты из knowledge_base. Не додумывай и не используй внешние данные.
- Каждое обнаруженное расхождение должно ссылаться на practice_id из \
knowledge_base.common_misleading_practices.
- Severity уровни: none (соответствует), low, medium, high.
- Если данных о продукте недостаточно — возвращай verdict='insufficient_data'.
- Цитаты в evidence_quote должны быть ДОСЛОВНО взяты из declared_ingredients или \
marketing_claims. Не перефразируй.
- Все ответы — на русском языке.

Вызови инструмент submit_verification_report ровно один раз."""


SUBMIT_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_verification_report",
    "description": (
        "Отправляет итоговый отчёт верификации продукта. Вызывается ровно один раз "
        "после полного анализа состава и маркетинга."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["compliant", "misleading", "insufficient_data"],
                "description": (
                    "compliant — состав и маркетинг соответствуют научным фактам; "
                    "misleading — обнаружены вводящие в заблуждение заявления; "
                    "insufficient_data — недостаточно информации для проверки."
                ),
            },
            "overall_severity": {
                "type": "string",
                "enum": ["none", "low", "medium", "high"],
                "description": "Максимальная серьёзность из обнаруженных нарушений.",
            },
            "summary": {
                "type": "string",
                "description": "Краткое резюме верификации (2-4 предложения, на русском).",
            },
            "discrepancies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "practice_id": {
                            "type": "string",
                            "description": "ID из common_misleading_practices.",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["none", "low", "medium", "high"],
                        },
                        "evidence_quote": {
                            "type": "string",
                            "description": "Дословная цитата из состава или маркетинга.",
                        },
                        "scientific_basis": {
                            "type": "string",
                            "description": "Научное обоснование (на основе knowledge_base).",
                        },
                        "required_fix": {
                            "type": "string",
                            "description": "Что должна сделать компания для исправления.",
                        },
                    },
                    "required": [
                        "practice_id",
                        "severity",
                        "evidence_quote",
                        "scientific_basis",
                        "required_fix",
                    ],
                },
            },
            "references": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Цитаты из knowledge_base.meta.sources, подкрепляющие вывод.",
            },
        },
        "required": ["verdict", "overall_severity", "summary", "discrepancies"],
    },
}


class CollagenAnalyzer:
    """Thin wrapper around the Anthropic client that verifies product composition."""

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        kb: KnowledgeBase | None = None,
        max_tokens: int = 2048,
    ) -> None:
        self.client = client or Anthropic()
        self.model = model
        self.kb = kb or load_knowledge_base()
        self.max_tokens = max_tokens

    def _build_system(self) -> list[dict[str, Any]]:
        # Put the large, stable KB in a cached system block to benefit from
        # prompt caching across many product verifications.
        return [
            {"type": "text", "text": SYSTEM_PROMPT},
            {
                "type": "text",
                "text": (
                    "<knowledge_base>\n"
                    + self.kb.as_system_prompt_section()
                    + "\n</knowledge_base>"
                ),
                "cache_control": {"type": "ephemeral"},
            },
        ]

    def _build_user_message(self, product: Product) -> str:
        payload = {
            "company": product.company,
            "brand": product.brand,
            "product_name": product.product_name,
            "country": product.country,
            "declared_ingredients": product.declared_ingredients,
            "marketing_claims": product.marketing_claims,
            "url": product.url,
        }
        return (
            "Проанализируй следующий продукт на предмет расхождений между заявленным "
            "составом/маркетингом и научными фактами из knowledge_base.\n\n"
            "<product>\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n</product>\n\n"
            "Вызови submit_verification_report."
        )

    def analyze(self, product: Product) -> VerificationReport:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self._build_system(),
            tools=[SUBMIT_REPORT_TOOL],
            tool_choice={"type": "tool", "name": "submit_verification_report"},
            messages=[{"role": "user", "content": self._build_user_message(product)}],
        )

        tool_input = _extract_tool_input(response, "submit_verification_report")
        tool_input.setdefault("references", [])

        try:
            discrepancies = [Discrepancy(**d) for d in tool_input.get("discrepancies", [])]
            return VerificationReport(
                product=product,
                verdict=tool_input["verdict"],
                overall_severity=Severity(tool_input["overall_severity"]),
                summary=tool_input["summary"],
                discrepancies=discrepancies,
                references=tool_input.get("references", []),
            )
        except (KeyError, ValidationError) as exc:
            raise RuntimeError(
                f"Модель вернула некорректный отчёт: {exc}. Сырой ответ: {tool_input!r}"
            ) from exc


def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RuntimeError(
        f"Ожидался tool_use '{tool_name}', но модель его не вызвала. "
        f"stop_reason={getattr(response, 'stop_reason', None)}"
    )
