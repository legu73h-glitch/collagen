"""Pydantic models for product input and verification output."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Product(BaseModel):
    """Product under verification."""

    company: str = Field(description="Название компании-производителя")
    brand: str | None = Field(default=None, description="Торговая марка")
    product_name: str = Field(description="Название продукта как на упаковке")
    country: str | None = Field(default=None, description="Страна регистрации/продажи")
    declared_ingredients: str = Field(
        description="Состав как указано на этикетке (исходный текст)"
    )
    marketing_claims: list[str] = Field(
        default_factory=list,
        description="Ключевые маркетинговые утверждения с упаковки/сайта",
    )
    url: str | None = Field(default=None, description="Ссылка на источник данных")
    contact_email: str | None = Field(
        default=None, description="Email компании для направления уведомления"
    )
    contact_address: str | None = Field(
        default=None, description="Почтовый адрес компании"
    )


class Discrepancy(BaseModel):
    practice_id: str = Field(
        description="ID нарушения из knowledge_base.common_misleading_practices"
    )
    severity: Severity
    evidence_quote: str = Field(
        description="Точная цитата с упаковки/маркетинга, содержащая нарушение"
    )
    scientific_basis: str = Field(
        description="Краткое научное обоснование, почему это вводит в заблуждение"
    )
    required_fix: str = Field(description="Конкретное действие, которое должна предпринять компания")


class VerificationReport(BaseModel):
    product: Product
    verdict: Literal["compliant", "misleading", "insufficient_data"]
    overall_severity: Severity
    summary: str = Field(description="Краткое резюме верификации (2-4 предложения)")
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    references: list[str] = Field(
        default_factory=list,
        description="Ссылки на источники из knowledge_base.meta.sources",
    )


class ComplianceLetter(BaseModel):
    recipient_company: str
    recipient_email: str | None
    recipient_address: str | None
    subject: str
    body: str
    attachments: list[str] = Field(default_factory=list)
