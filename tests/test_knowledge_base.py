from src.knowledge_base import load_knowledge_base


def test_knowledge_base_loads():
    kb = load_knowledge_base()
    assert kb.raw["meta"]["version"]
    assert "collagen_hydrolysate" in kb.definitions
    assert "native_collagen" in kb.definitions
    assert kb.plant_claim["scientific_fact"].startswith("Коллаген")


def test_misleading_practice_ids_are_unique():
    kb = load_knowledge_base()
    ids = [p["id"] for p in kb.misleading_practices]
    assert len(ids) == len(set(ids))


def test_key_practice_ids_present():
    kb = load_knowledge_base()
    ids = {p["id"] for p in kb.misleading_practices}
    required = {
        "HYDROLYSATE_AS_COLLAGEN",
        "PLANT_COLLAGEN",
        "GELATIN_AS_NATIVE_COLLAGEN",
    }
    assert required.issubset(ids)


def test_hydrolysate_marked_as_not_collagen():
    kb = load_knowledge_base()
    note = kb.definitions["collagen_hydrolysate"]["important_note"]
    assert "НЕ сам коллаген" in note


def test_native_collagen_mw_range():
    kb = load_knowledge_base()
    mw = kb.definitions["native_collagen"]["molecular_weight_kda"]
    assert mw[0] >= 250 and mw[1] <= 350
