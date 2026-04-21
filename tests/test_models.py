import json
from pathlib import Path

from src.models import Product, Severity


def test_example_products_are_valid():
    path = Path(__file__).resolve().parent.parent / "data" / "example_products.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    products = [Product(**item) for item in data]
    assert len(products) == 4
    assert products[0].company == "ООО «ПримерБьюти»"
    assert "коллаген" in products[0].declared_ingredients.lower()


def test_severity_enum():
    assert Severity("high") is Severity.HIGH
    assert Severity.NONE.value == "none"


def test_product_requires_company_and_ingredients():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Product(product_name="x", declared_ingredients="y")  # type: ignore[call-arg]
