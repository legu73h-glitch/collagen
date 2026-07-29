# Collagen Verification Agent

ИИ-агент для защиты прав потребителей: сверяет состав и маркетинговые утверждения
продуктов с коллагеном со **научно обоснованной базой знаний** и, при обнаружении
расхождений, автоматически формирует официальное требование производителю об
исправлении маркировки.

Ключевая проверяемая проблема: **маркетинговое смешивание гидролизата коллагена
(коллагеновых пептидов) с нативным коллагеном**, а также позиционирование желатина
или аминокислотных смесей как «коллагена».

## Что проверяет агент

| ID нарушения | Описание |
|---|---|
| `HYDROLYSATE_AS_COLLAGEN` | Гидролизат коллагена подаётся как «коллаген» / «нативный коллаген» без уточнения |
| `PLANT_COLLAGEN` | «Растительный / веганский коллаген» — научно некорректное заявление |
| `GELATIN_AS_NATIVE_COLLAGEN` | Желатин позиционируется как «чистый» / «нативный» коллаген |
| `MISSING_TYPE_AND_SOURCE` | Не указан тип (I/II/III) и/или источник (бычий/морской/...) |
| `MW_NOT_DISCLOSED` | Для гидролизата не указана средняя молекулярная масса |
| `UNSUPPORTED_HEALTH_CLAIMS` | Неподтверждённые заявления («напрямую восстанавливает коллаген в коже» и т.п.) |

Полные определения, диапазоны молекулярных масс, списки синонимов и научные источники
лежат в [`data/collagen_knowledge_base.json`](data/collagen_knowledge_base.json).

> 📦 В репозитории **два независимых ИИ-агента**: Collagen Verification Agent (описан ниже)
> и **[ИИ-агент продакта — discovery-конвейер](#ии-агент-продакта--discovery-конвейер)**,
> который из одной идеи продукта собирает пакет из 7 discovery-артефактов.

## Архитектура

```
┌──────────────────────┐     ┌─────────────────────────┐     ┌────────────────────┐
│ Product (JSON)       │ ──▶ │ CollagenAnalyzer         │ ──▶ │ VerificationReport │
│ состав + маркетинг   │     │ Claude + KB (cached)     │     │ discrepancies[]    │
└──────────────────────┘     └─────────────────────────┘     └─────────┬──────────┘
                                                                        │ verdict == misleading
                                                                        ▼
                                                           ┌────────────────────────┐
                                                           │ LetterGenerator         │
                                                           │ Claude → ComplianceLetter│
                                                           └────────────┬───────────┘
                                                                        ▼
                                                               reports/*.letter.md
```

Компоненты:

- `src/knowledge_base.py` — загрузчик JSON-базы знаний.
- `src/analyzer.py` — анализатор состава, использующий Claude с принудительным
  `tool_use` для структурированного отчёта. База знаний кэшируется в system prompt
  через `cache_control`.
- `src/notifier.py` — генератор официальных писем-требований с правовыми ссылками
  (ФЗ «О защите прав потребителей», ТР ТС 022/2011, EU 1169/2011, FTC Act §5).
- `src/agent.py` — оркестрация end-to-end и сохранение отчётов/писем на диск.
- `src/cli.py` — CLI на `rich` для интерактивного запуска.

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env
# Вставьте свой ANTHROPIC_API_KEY в .env
export ANTHROPIC_API_KEY=sk-ant-...
```

По умолчанию используется модель `claude-opus-4-7`. Переопределить:

```bash
export COLLAGEN_AGENT_MODEL=claude-sonnet-4-6
```

## Использование

### Посмотреть базу знаний (API-ключ не нужен):

```bash
python -m src kb
```

### Проверить один продукт:

```bash
python -m src verify --product my_product.json
```

### Проверить партию:

```bash
python -m src verify --batch data/example_products.json --out reports/
```

Формат продукта:

```json
{
  "company": "ООО «Пример»",
  "brand": "BrandX",
  "product_name": "Чистый Коллаген Premium",
  "country": "Россия",
  "declared_ingredients": "Гидролизат коллагена (рыбный), витамин C...",
  "marketing_claims": ["100% чистый коллаген", "Нативный морской коллаген"],
  "url": "https://example.com/product",
  "contact_email": "info@example.com"
}
```

### Использование из Python:

```python
from src.agent import CollagenAgent
from src.models import Product

agent = CollagenAgent()
result = agent.process(Product(
    company="ООО «Пример»",
    product_name="Коллаген X",
    declared_ingredients="Гидролизат коллагена (рыбный)",
    marketing_claims=["100% чистый коллаген"],
))

print(result.report.verdict)           # 'misleading'
print(result.report.overall_severity)  # Severity.HIGH
if result.letter:
    print(result.letter.body)          # Готовое письмо-требование
```

## Выходные артефакты

После `agent.process()` в каталоге `reports/` появляются:

- `<timestamp>_<slug>.report.json` — структурированный отчёт верификации.
- `<timestamp>_<slug>.letter.json` — письмо в структурированном виде.
- `<timestamp>_<slug>.letter.md` — письмо в markdown для отправки.

Агент **не** отправляет письма автоматически — это намеренное решение. Отправка
остаётся за оператором, чтобы исключить массовые необоснованные обращения.

## Научная основа

База знаний опирается на рецензируемые источники, перечисленные в
`data/collagen_knowledge_base.json` → `meta.sources`:

- Shoulders & Raines (2009). Collagen structure and stability. *Annu. Rev. Biochem.*
- Ricard-Blum (2011). The collagen family. *Cold Spring Harb. Perspect. Biol.*
- León-López et al. (2019). Hydrolyzed Collagen — Sources and Applications. *Molecules*.
- Sorushanova et al. (2019). The Collagen Suprafamily. *Adv. Mater.*
- Avila Rodríguez et al. (2018). Collagen: sources and cosmetic applications.
- EFSA scientific opinions on collagen peptide health claims.

## Тесты

```bash
pytest tests/ -v
```

Тесты покрывают:
- целостность и инварианты базы знаний,
- валидацию моделей `Product` / `VerificationReport`,
- плёнку вокруг Anthropic SDK через моки (без реальных API-вызовов).

## Ограничения и этика

- Агент анализирует **только те данные, которые вы ему передали**. Он не парсит
  сайты и магазины самостоятельно — источник информации о составе должен быть
  проверен вами.
- Итоговое требование — это **проект письма**, не юридическое заключение. Перед
  отправкой перечитайте и при необходимости согласуйте с юристом.
- Severity определяется моделью на основании KB; при спорных случаях проверяйте
  `discrepancies[].evidence_quote` вручную.

---

# ИИ-агент продакта — discovery-конвейер

Из **одной идеи продукта** — пакет из семи discovery-артефактов. Агент прогоняет идею через
конвейер из семи нод; каждая нода — это отдельный продуктовый скилл ([`skills/`](skills/)),
чья инструкция `SKILL.md` подаётся модели как системный промпт. Артефакты передаются по
цепочке зависимостей, и на выходе получается собранный «пакет discovery».

Скиллы взяты из набора **Product Skills** (Academy of Yandex AI Studio) и лежат в
[`skills/`](skills/) вместе с исходными [`SOURCE_README.md`](skills/SOURCE_README.md) и
[`SOURCE_WORKFLOW.md`](skills/SOURCE_WORKFLOW.md).

## Ноды конвейера

| # | Скилл (нода) | Требует | На выходе | Инструмент |
|---|---|---|---|---|
| 1 | `brief-writing` | idea | `brief` — бриф | — |
| 2 | `market-research` | brief | `market` — рыночный срез | 🌐 web search |
| 3 | `persona-generation` | brief | `personas` — персоны | — |
| 4 | `lean-canvas` | brief (+market, +personas) | `lean_canvas` — Lean Canvas | — |
| 5 | `user-story-mapping` | brief (+personas) | `story_map` — User Story Map | — |
| 6 | `wireframe-spec` | story_map | `wireframes` — вайрфреймы | — |
| 7 | `persona-interview` | personas, brief | `interview_report` — отчёт custdev | — |

Порядок исполнения — валидная топологическая сортировка зависимостей: каждая нода получает
на вход только те артефакты, которые уже произведены ранее.

```
idea
  └─(1 brief-writing)──────────────▶ brief
         ├─(2 market-research)🌐───▶ market ─────┐
         ├─(3 persona-generation)──▶ personas ───┤
         ├─(4 lean-canvas)◀──────── brief + market + personas
         ├─(5 user-story-mapping)◀─ brief + personas
         │        └─(6 wireframe-spec)──────────▶ wireframes
         └─(7 persona-interview)◀── personas + brief ──▶ interview_report
```

## Архитектура

```
┌──────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│ Idea (JSON)  │──▶ │ DiscoveryAgent   │──▶ │ DiscoveryPackage    │
│ summary +    │    │ resolve DAG →    │    │ 7 артефактов (.md)  │
│ constraints  │    │ NodeRunner×N     │    │ + discovery_package │
└──────────────┘    └────────┬─────────┘    └─────────────────────┘
                             │ на каждую ноду
                             ▼
                    ┌────────────────────┐
                    │ skills/<slug>/     │  SKILL.md → system prompt (cached)
                    │ Claude + web_search│  upstream-артефакты → user message
                    └────────────────────┘
```

Компоненты:

- `product_agent/skills.py` — загрузчик скиллов: парсит YAML-frontmatter и тело `SKILL.md`.
- `product_agent/pipeline.py` — определение DAG (`PIPELINE`), топо-валидация и разрешение
  подмножеств с автодобором обязательных зависимостей.
- `product_agent/nodes.py` — `NodeRunner`: собирает системный промпт (скилл, кэшируется) и
  пользовательское сообщение (идея + upstream-артефакты), вызывает Claude, при необходимости
  подключает серверный `web_search` с graceful-фолбэком.
- `product_agent/agent.py` — `DiscoveryAgent`: оркестрация конвейера и сохранение пакета.
- `product_agent/cli.py` — CLI на `rich`: `run` / `skills` / `graph`.

## Установка

Та же, что и для основного агента (см. выше): `pip install -r requirements.txt`, ключ
`ANTHROPIC_API_KEY` в `.env`. Модель по умолчанию — `claude-opus-4-7`, переопределяется через
`PRODUCT_AGENT_MODEL`.

## Использование

### Посмотреть конвейер (API-ключ не нужен):

```bash
python -m product_agent graph     # граф и порядок нод
python -m product_agent skills     # скиллы, их входы/выходы и инструменты
```

### Прогнать идею через весь конвейер:

```bash
python -m product_agent run --idea data/example_ideas.json --out discovery/
```

Идею можно задать и одной строкой:

```bash
python -m product_agent run \
  --summary "Приложение для обмена сменами между сотрудниками" \
  --name ShiftSwap --constraint "бюджет $40k" --constraint "3 месяца"
```

### Минимальный конвейер (3 ноды) и подмножества:

```bash
python -m product_agent run --idea idea.json --minimal          # brief → story_map → wireframes
python -m product_agent run --idea idea.json --only lean-canvas  # добьёт обязательный brief сам
python -m product_agent run --idea idea.json --no-web-search     # без веб-поиска на market
```

Формат идеи (`data/example_ideas.json` — массив таких объектов):

```json
{
  "name": "ShiftSwap",
  "summary": "Приложение, которое помогает сотрудникам меняться сменами без менеджера.",
  "audience": "Линейные сотрудники и сменные менеджеры",
  "constraints": ["MVP-бюджет до $40k", "Запуск за 3 месяца"],
  "notes": "Ключевая гипотеза — менеджеры тратят часы на закрытие больничных."
}
```

### Использование из Python:

```python
from product_agent.agent import DiscoveryAgent
from product_agent.models import Idea

agent = DiscoveryAgent(out_dir="discovery")
result = agent.run(Idea(
    summary="Приложение для обмена сменами между сотрудниками",
    name="ShiftSwap",
    constraints=["бюджет $40k", "3 месяца"],
))

print(result.order)                          # порядок исполненных нод
print(result.package.get("brief").content)   # markdown-бриф
print(result.package.as_markdown())          # весь пакет одним документом
```

## Выходные артефакты

После `agent.run()` в каталоге `discovery/<timestamp>_<slug>/` появляются:

- `01_brief.md … 07_interview_report.md` — каждый артефакт отдельным файлом (в порядке нод).
- `discovery_package.md` — сводный документ: идея + все артефакты.
- `package.json` — структурированный пакет (идея + артефакты с метаданными).

## Веб-поиск

Нода `market-research` подключает серверный инструмент Anthropic `web_search_20250305`. Если
инструмент недоступен для аккаунта, нода автоматически повторяет вызов без него, а скилл
помечает отчёт как «без верификации источниками» 🔴. Отключить принудительно: `--no-web-search`.

## Тесты

```bash
pytest tests/ -v
```

Тесты агента-продакта (офлайн, без реальных API-вызовов) покрывают:
- валидность DAG и топологического порядка, разрешение `--minimal` и `--only` с автодобором
  обязательных зависимостей;
- загрузку всех семи скиллов и согласованность их frontmatter с конвейером;
- сборку системного/пользовательского сообщений, кэш скилла, подключение `web_search` только
  к `market` и graceful-фолбэк, сшивку артефактов по цепочке;
- сериализацию моделей и формат итогового пакета.

## Ограничения

- Артефакты — это **черновики гипотез** discovery, а не факты. Персоны, рынок и канвас
  требуют проверки на реальных пользователях и данных.
- Симулированное интервью (`persona-interview`) — игра модели за персону, не голос рынка.
- Агент работает автономно (без вопросов): пробелы во входе он закрывает обоснованными
  допущениями с меткой `[assumption]` — перечитывайте их перед использованием.
