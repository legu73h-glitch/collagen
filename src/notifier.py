"""Generator of formal compliance notification letters to companies."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from anthropic import Anthropic

from .knowledge_base import KnowledgeBase, load_knowledge_base
from .models import ComplianceLetter, VerificationReport

DEFAULT_MODEL = os.environ.get("COLLAGEN_AGENT_MODEL", "claude-opus-4-7")

SYSTEM_PROMPT = """Ты — специалист по защите прав потребителей, составляющий официальные \
уведомления компаниям о необходимости привести маркировку продукции в соответствие \
с научно установленными фактами о коллагене.

Требования к письму:
1. Деловой, уважительный, но строгий тон.
2. Чёткая структура: приветствие → предмет обращения → научные основания → \
перечисление конкретных нарушений с дословными цитатами → требуемые действия → сроки → \
правовые основания → подпись.
3. Правовые основания (используй релевантные, не выдумывай):
   - Россия: ФЗ № 2300-1 "О защите прав потребителей", ст. 8, 10; ТР ТС 022/2011.
   - ЕС: Regulation (EU) No 1169/2011 о предоставлении информации о продуктах питания.
   - США: FTC Act Section 5; FDA 21 CFR 101.
4. Указать разумный срок исправления (обычно 30 календарных дней).
5. Не угрожать, но чётко обозначить возможность обращения в надзорные органы при \
отсутствии реакции.
6. Язык — русский, если явно не запрошен другой.

Вызови инструмент submit_compliance_letter ровно один раз."""

SUBMIT_LETTER_TOOL: dict[str, Any] = {
    "name": "submit_compliance_letter",
    "description": "Формирует итоговое требование к компании об исправлении маркировки.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Тема письма (не длиннее 120 символов).",
            },
            "body": {
                "type": "string",
                "description": (
                    "Полный текст письма в формате plain text (допустим markdown). "
                    "Должен включать все структурные блоки из системного промпта."
                ),
            },
        },
        "required": ["subject", "body"],
    },
}


class LetterGenerator:
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

    def generate(self, report: VerificationReport) -> ComplianceLetter:
        if report.verdict != "misleading":
            raise ValueError(
                "Письмо формируется только для продуктов с verdict='misleading'. "
                f"Текущий verdict={report.verdict}."
            )

        user_message = (
            "Сформируй официальное уведомление компании на основании отчёта верификации.\n\n"
            f"<today>{date.today().isoformat()}</today>\n\n"
            "<verification_report>\n"
            + report.model_dump_json(indent=2)
            + "\n</verification_report>\n\n"
            "<sources_reference>\n"
            + json.dumps(self.kb.sources, ensure_ascii=False, indent=2)
            + "\n</sources_reference>\n\n"
            "Вызови submit_compliance_letter."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
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
            ],
            tools=[SUBMIT_LETTER_TOOL],
            tool_choice={"type": "tool", "name": "submit_compliance_letter"},
            messages=[{"role": "user", "content": user_message}],
        )

        tool_input = _extract_tool_input(response, "submit_compliance_letter")
        return ComplianceLetter(
            recipient_company=report.product.company,
            recipient_email=report.product.contact_email,
            recipient_address=report.product.contact_address,
            subject=tool_input["subject"],
            body=tool_input["body"],
        )


def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RuntimeError(
        f"Ожидался tool_use '{tool_name}', но модель его не вызвала. "
        f"stop_reason={getattr(response, 'stop_reason', None)}"
    )
