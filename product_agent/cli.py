"""Command-line interface for the product discovery pipeline agent.

Usage:
    python -m product_agent run --idea idea.json --out discovery/
    python -m product_agent run --summary "..." --name "MyApp"
    python -m product_agent run --idea idea.json --minimal
    python -m product_agent run --idea idea.json --only brief-writing,lean-canvas
    python -m product_agent skills
    python -m product_agent graph
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

from .agent import DiscoveryAgent, DiscoveryResult
from .models import Idea
from .nodes import DEFAULT_MODEL
from .pipeline import (
    MINIMAL_SLUGS,
    PIPELINE,
    NodeSpec,
    resolve_nodes,
)
from .skills import load_skill_library

console = Console()


# -- idea loading -----------------------------------------------------------


def _load_idea(args: argparse.Namespace) -> Idea:
    if args.idea:
        path = Path(args.idea)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            console.print(f"[red]Не удалось прочитать идею из {path}:[/red] {exc}")
            sys.exit(2)
        # Allow either a bare idea object or a list (take the first).
        if isinstance(data, list):
            if not data:
                console.print("[red]Файл идеи пуст.[/red]")
                sys.exit(2)
            data = data[0]
        try:
            return Idea(**data)
        except ValidationError as exc:
            console.print(f"[red]Ошибка валидации идеи:[/red] {exc}")
            sys.exit(2)

    if args.summary:
        return Idea(
            summary=args.summary,
            name=args.name,
            constraints=list(args.constraint or []),
            audience=args.audience,
        )

    console.print("[red]Укажите идею: --idea <json> или --summary \"...\".[/red]")
    sys.exit(2)


def _selected_slugs(args: argparse.Namespace) -> list[str] | None:
    if args.minimal:
        return list(MINIMAL_SLUGS)
    if args.only:
        return [s.strip() for s in args.only.split(",") if s.strip()]
    return None


# -- rendering --------------------------------------------------------------


def _render_result(result: DiscoveryResult) -> None:
    idea = result.idea
    console.print(
        Panel.fit(
            f"[bold]{idea.display_name()}[/bold]\n{idea.summary}",
            title="Discovery Package",
            border_style="cyan",
        )
    )

    table = Table(title="Произведённые артефакты", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Артефакт", style="bold")
    table.add_column("Нода")
    table.add_column("Символов", justify="right")
    table.add_column("web", justify="center")
    for i, artifact in enumerate(result.package.artifacts, start=1):
        table.add_row(
            str(i),
            artifact.id,
            artifact.node,
            str(len(artifact.content)),
            "🌐" if artifact.used_web_search else "",
        )
    console.print(table)

    if result.run_dir is not None:
        console.print(
            f"\nПакет сохранён в: [cyan]{result.run_dir}[/cyan]  "
            f"(артефактов: [bold]{len(result.package.artifacts)}[/bold])"
        )
        console.print(f"Сводный документ: [cyan]{result.run_dir / 'discovery_package.md'}[/cyan]")


# -- commands ---------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    idea = _load_idea(args)
    slugs = _selected_slugs(args)
    try:
        specs = resolve_nodes(slugs)
    except ValueError as exc:
        console.print(f"[red]Не удалось собрать конвейер:[/red] {exc}")
        return 2

    console.print(
        f"Запуск конвейера · нод: [bold]{len(specs)}[/bold] · "
        f"модель: [cyan]{args.model}[/cyan] · "
        f"web search: {'вкл' if not args.no_web_search else 'выкл'}"
    )

    def on_start(spec: NodeSpec) -> None:
        console.print(f"  ▶ [bold]{spec.slug}[/bold] → {spec.artifact_id} …")

    def on_done(spec: NodeSpec) -> None:
        console.print(f"  [green]✓[/green] {spec.artifact_id}")

    try:
        agent = DiscoveryAgent(
            model=args.model,
            out_dir=args.out,
            enable_web_search=not args.no_web_search,
        )
        result = agent.run(
            idea,
            nodes=slugs,
            save=not args.no_save,
            on_node_start=on_start,
            on_node_done=on_done,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        console.print(f"[red]Ошибка выполнения конвейера:[/red] {exc}")
        return 1

    console.rule()
    _render_result(result)
    return 0


def cmd_skills(_: argparse.Namespace) -> int:
    library = load_skill_library()
    by_slug = {n.slug: n for n in PIPELINE}

    table = Table(title="Скиллы discovery-конвейера", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Скилл", style="bold")
    table.add_column("Входы → Выход")
    table.add_column("Инструменты")
    table.add_column("Роль", overflow="fold")

    for i, node in enumerate(PIPELINE, start=1):
        skill = library.get(node.slug)
        inputs = ", ".join(skill.inputs) or "idea"
        outputs = ", ".join(skill.outputs) or node.artifact_id
        tools = ", ".join(skill.tools) or "—"
        role = str(skill.metadata.get("role", ""))
        table.add_row(str(i), node.slug, f"{inputs} → {outputs}", tools, role)
    console.print(table)

    # Any bundled skills that are not part of the core pipeline.
    extra = [s.slug for s in library if s.slug not in by_slug]
    if extra:
        console.print(f"\n[dim]Также в библиотеке:[/dim] {', '.join(sorted(extra))}")
    return 0


def cmd_graph(_: argparse.Namespace) -> int:
    console.print(Panel.fit("Discovery-конвейер: idea → пакет артефактов", border_style="cyan"))

    table = Table(show_lines=False)
    table.add_column("Шаг", justify="right", style="dim")
    table.add_column("Нода", style="bold")
    table.add_column("Требует")
    table.add_column("Опц.")
    table.add_column("→ Артефакт")
    table.add_column("web", justify="center")
    for i, node in enumerate(PIPELINE, start=1):
        table.add_row(
            str(i),
            node.slug,
            ", ".join(node.required_inputs) or "idea",
            ", ".join(node.optional_inputs) or "",
            node.artifact_id,
            "🌐" if node.needs_web_search else "",
        )
    console.print(table)

    console.print(
        "\n[dim]Порядок:[/dim] "
        + " → ".join(n.artifact_id for n in PIPELINE)
    )
    console.print(
        "[dim]Минимальный конвейер (--minimal):[/dim] " + " → ".join(MINIMAL_SLUGS)
    )
    return 0


# -- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="product-agent",
        description="ИИ-агент продакта: discovery-конвейер из одной идеи в пакет артефактов.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Прогнать идею через конвейер")
    p_run.add_argument("--idea", help="Путь к JSON с идеей продукта")
    p_run.add_argument("--summary", help="Идея одной строкой (вместо --idea)")
    p_run.add_argument("--name", help="Название продукта (с --summary)")
    p_run.add_argument("--audience", help="Подсказка по аудитории (с --summary)")
    p_run.add_argument(
        "--constraint",
        action="append",
        help="Ограничение (можно повторять; с --summary)",
    )
    p_run.add_argument("--out", default="discovery", help="Каталог для пакета артефактов")
    p_run.add_argument("--model", default=DEFAULT_MODEL, help="Модель Anthropic")
    p_run.add_argument(
        "--minimal",
        action="store_true",
        help="Минимальный конвейер: brief → story_map → wireframes",
    )
    p_run.add_argument(
        "--only",
        help="Запустить подмножество нод (slug'и через запятую); зависимости добираются автоматически",
    )
    p_run.add_argument(
        "--no-web-search",
        action="store_true",
        help="Отключить веб-поиск на ноде market-research",
    )
    p_run.add_argument("--no-save", action="store_true", help="Не сохранять файлы")
    p_run.set_defaults(func=cmd_run)

    p_skills = sub.add_parser("skills", help="Показать скиллы конвейера")
    p_skills.set_defaults(func=cmd_skills)

    p_graph = sub.add_parser("graph", help="Показать граф/порядок конвейера")
    p_graph.set_defaults(func=cmd_graph)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
