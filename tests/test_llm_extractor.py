"""Tests for the local Ollama LLM extractor module (llm_extractor.py)."""

from unittest.mock import MagicMock, patch
import pytest

from src.extraction.llm_extractor import (
    clean_json_output,
    build_extraction_prompt,
    extract_with_llm,
    is_field_empty,
    is_ollama_available,
    merge_with_llm_fallback,
)


def test_clean_json_output_standard():
    raw = '{"unit_brand": "Shimadzu", "unit_type": "RADspeed"}'
    parsed = clean_json_output(raw)
    assert parsed == {"unit_brand": "Shimadzu", "unit_type": "RADspeed"}


def test_clean_json_output_with_markdown_fence():
    raw = """
Berikut data yang diekstrak:
```json
{
  "hospital_name": "RSUD Dr. Soetomo",
  "unit_serial_number": "SN-12345"
}
```
Semoga membantu.
"""
    parsed = clean_json_output(raw)
    assert parsed["hospital_name"] == "RSUD Dr. Soetomo"
    assert parsed["unit_serial_number"] == "SN-12345"


def test_clean_json_output_wrapped_outer_key():
    raw = '{"result": {"hospital_name": "RS Siloam", "unit_brand": "GE Healthcare"}}'
    parsed = clean_json_output(raw)
    assert parsed == {"hospital_name": "RS Siloam", "unit_brand": "GE Healthcare"}


def test_clean_json_output_malformed_graceful():
    assert clean_json_output("") == {}
    assert clean_json_output("Bukan format JSON sama sekali") == {}


def test_build_extraction_prompt():
    prompt = build_extraction_prompt(
        doc_type="uji_fungsi",
        text="Teks sampel",
        target_fields=["unit_brand", "unit_serial_number", "tube_serial_number"],
    )
    assert "uji_fungsi" in prompt
    assert "unit_brand" in prompt
    assert "unit_serial_number" in prompt
    assert "tube_serial_number" in prompt
    assert "Jangan menukar" in prompt


def test_is_field_empty():
    assert is_field_empty(None) is True
    assert is_field_empty("") is True
    assert is_field_empty("-") is True
    assert is_field_empty("—") is True
    assert is_field_empty({"value": "-"}) is True
    assert is_field_empty({"value": ""}) is True
    assert is_field_empty({"value": "Valid Data"}) is False
    assert is_field_empty("Valid String") is False


@patch("requests.get")
def test_is_ollama_available_mock(mock_get):
    # Success scenario
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    mock_get.return_value = mock_resp

    assert is_ollama_available() is True

    # Failure scenario
    mock_get.side_effect = Exception("Connection refused")
    assert is_ollama_available() is False


@patch("requests.post")
def test_extract_with_llm_mock(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": '{"merk_unit": "Shimadzu", "tipe_unit": "RADspeed Fit", "no_seri_unit": "SH-9988"}'
    }
    mock_post.return_value = mock_resp

    res = extract_with_llm(
        doc_type="uji_fungsi",
        text="Pesawat Rontgen Merk Shimadzu tipe RADspeed Fit S/N SH-9988",
    )

    assert "unit_brand" in res
    assert res["unit_brand"]["value"] == "Shimadzu"
    assert res["unit_brand"]["method"] == "llm_qwen2.5"
    assert res["unit_brand"]["confidence"] == 0.95
    assert res["unit_type"]["value"] == "RADspeed Fit"
    assert res["unit_serial_number"]["value"] == "SH-9988"


@patch("src.extraction.llm_extractor.extract_with_llm")
@patch("src.extraction.llm_extractor.is_ollama_available", return_value=True)
def test_merge_with_llm_fallback(mock_avail, mock_extract):
    mock_extract.return_value = {
        "unit_serial_number": {"value": "SN-LLM-001", "page": None, "method": "llm_qwen2.5", "confidence": 0.95},
        "tube_serial_number": {"value": "TB-LLM-999", "page": None, "method": "llm_qwen2.5", "confidence": 0.95},
    }

    initial_fields = {
        "hospital_name": {"value": "RS Sehat", "page": 1, "method": "regex"},
        "unit_brand": {"value": "GE Healthcare", "page": 1, "method": "regex"},
        "unit_type": {"value": "Optima", "page": 1, "method": "regex"},
        "unit_serial_number": {"value": "-", "page": None, "method": "not_found"},  # missing
        "tube_serial_number": {"value": "", "page": None, "method": "not_found"},   # missing
    }

    merged = merge_with_llm_fallback(
        doc_type="uji_fungsi",
        parsed_fields=initial_fields,
        pages_text=["Laporan Uji Fungsi RS Sehat GE Healthcare Optima"],
        force_llm=True,
    )

    # Existing valid values must be preserved
    assert merged["hospital_name"]["value"] == "RS Sehat"
    assert merged["unit_brand"]["value"] == "GE Healthcare"

    # Missing values must be populated by LLM
    assert merged["unit_serial_number"]["value"] == "SN-LLM-001"
    assert merged["unit_serial_number"]["method"] == "llm_qwen2.5"
    assert merged["tube_serial_number"]["value"] == "TB-LLM-999"
