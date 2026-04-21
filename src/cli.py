"""Command-line interface for the collagen verification agent.

Usage:
    python -m src.cli verify --product path/to/product.json
    python -m src.cli verify --batch data/example_products.json
    python -m src.cli kb
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agent import AgentResult, CollagenAgent
from .knowledge_base import load_knowledge_base
from .models import Product

console = Console()


def _load_products(path: Path) -> list[Product]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else [data]
    try:
        return [Product(**item) for item in items]
    except ValidationError as exc:
        console.print(f"[red]Ошибка валидации продукта:[/red] {exc}")
        sys.exit(2)


def _render_result(result: AgentResult) -> None:
    report = result.report
    severity_colors = {"none": "green", "low": "yellow", "medium": "orange1", "high": "red"}
    color = severity_colors.get(report.overall_severity.value, "white")

    console.print(
        Panel.fit(
            f"[bold]{report.product.company}[/bold] — {report.product.product_name}\n"
            f"Verdict: [{color}]{report.verdict.upper()}[/{color}]  "
            f"Severity: [{color}]{report.overall_severity.value}[/{color}]\n\n"
            f"{report.summary}",
            title="Результат верификации",
        )
    )

    if report.discrepancies:
        table = Table(title="Обнаруженные расхождения", show_lines=True)
        table.add_column("Practice ID", style="bold")
        table.add_column("Severity")
        table.add_column("Цитата")
        table.add_column("Требуемое исправление")
        for d in report.discrepancies:
            table.add_row(
                d.practice_id,
                d.severity.value,
                d.evidence_quote,
                d.required_fix,
            )
        console.print(table)

    if result.letter:
        console.print(
            Panel(
                f"[bold]Тема:[/bold] {result.letter.subject}\n\n{result.letter.body}",
                title=f"Требование компании {result.letter.recipient_company}",
                border_style="red",
            )
        )


def cmd_verify(args: argparse.Namespace) -> int:
    source = Path(args.product or args.batch)
    products = _load_products(source)

    agent = CollagenAgent(reports_dir=args.out)
    results = agent.process_batch(products, save=not args.no_save)

    for r in results:
        _render_result(r)
        console.rule()

    misleading = sum(1 for r in results if r.report.verdict == "misleading")
    console.print(
        f"\nПроверено: [bold]{len(results)}[/bold]  "
        f"Требуют исправления: [red]{misleading}[/red]  "
        f"Отчёты сохранены в: [cyan]{args.out}[/cyan]"
        if not args.no_save
        else f"\nПроверено: [bold]{len(results)}[/bold]  Требуют исправления: [red]{misleading}[/red]"
    )
    return 0 if misleading == 0 else 1


def cmd_kb(_: argparse.Namespace) -> int:
    kb = load_knowledge_base()
    console.print(Panel.fit(f"Путь: {kb.path}\nВерсия: {kb.raw['meta']['version']}"))

    table = Table(title="Типы коллагеновых форм в базе")
    table.add_column("ID")
    table.add_column("Название")
    table.add_column("MW (kDa)")
    table.add_column("Структура")
    for key, item in kb.definitions.items():
        mw = item.get("molecular_weight_kda", ["-", "-"])
        table.add_row(
            key,
            item.get("name_ru", ""),
            f"{mw[0]}–{mw[1]}" if isinstance(mw, list) else str(mw),
            item.get("structure", "-"),
        )
    console.print(table)

    table2 = Table(title="Типовые нарушения")
    table2.add_column("ID")
    table2.add_column("Severity")
    table2.add_column("Описание", overflow="fold")
    for p in kb.misleading_practices:
        table2.add_row(p["id"], p["severity"], p["description"])
    console.print(table2)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collagen-agent",
        description="ИИ-агент верификации состава коллагеновой продукции.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="Проверить один или несколько продуктов")
    group = p_verify.add_mutually_exclusive_group(required=True)
    group.add_argument("--product", help="Путь к JSON с одним продуктом")
    group.add_argument("--batch", help="Путь к JSON-массиву продуктов")
    p_verify.add_argument("--out", default="reports", help="Каталог для сохранения отчётов")
    p_verify.add_argument("--no-save", action="store_true", help="Не сохранять файлы")
    p_verify.set_defaults(func=cmd_verify)

    p_kb = sub.add_parser("kb", help="Показать содержимое базы знаний")
    p_kb.set_defaults(func=cmd_kb)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
