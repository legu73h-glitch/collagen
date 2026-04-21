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
