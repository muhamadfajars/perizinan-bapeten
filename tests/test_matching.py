from src.matching.fuzzy_matcher import compare_values


def test_exact_brand():
    score, status = compare_values("GE", "GENERAL ELECTRIC COMPANY", mode="brand")
    assert score == 100
    assert status == "SESUAI"


def test_serial_exact_after_ocr_normalization():
    score, status = compare_values("E7894/OI37", "E7894/0I37", mode="serial")
    assert score == 100
    assert status == "SESUAI"


def test_name_variation_becomes_warning_or_review():
    score, status = compare_values(
        "dr. Adimas Okto Nugroho, Sp.Rad",
        "dr.AdimasOktoAnugrahSp.Rad",
        mode="fuzzy_name",
    )
    assert score is not None
    assert status in {"WARNING", "PERLU REVIEW", "TIDAK SESUAI"}
