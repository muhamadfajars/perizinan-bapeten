import pytest
from src.extraction.document_parser import (
    extract_uji_fungsi_data,
    extract_uji_kesesuaian_data,
    extract_paparan_radiasi_data,
    parse_document,
)
from src.extraction.generic_parser import (
    extract_facility_name,
    extract_facility_address,
    extract_generic_fields,
)
from src.extraction.llm_extractor import build_extraction_prompt


def test_context_guided_uji_fungsi_disambiguation():
    # Document text containing vendor letterhead (PT Fujifilm Casablanca Jakarta)
    # as well as customer facility (RSJ Aceh)
    pages = [
        """
        PT FUJIFILM INDONESIA
        Office 88 Kasablanka Building Tower A 38th Floor
        Jl. Casablanca Kav. 88 Jakarta Selatan 12870
        SERVICE REPORT
        Customer: RSJ. Aceh
        Address: Jl. Dr. Zainoel Abidin No. 1, Banda Aceh
        Model: FDR nano C35
        Serial Number: SB88231
        Tube Model: E7239X
        Tube S/N: 20G9912
        Status: PASS
        """
    ]

    context = {
        "hospital_name": "Rumah Sakit Jiwa Aceh",
        "hospital_address": "Jl. Dr. Zainoel Abidin No. 1, Banda Aceh",
        "unit_brand": "Fujifilm",
        "unit_type": "FDR nano C35",
        "unit_serial_number": "SB88231",
        "tube_brand": "Canon",
        "tube_type": "E7239X",
        "tube_serial_number": "20G9912",
    }

    res = extract_uji_fungsi_data(pages, context=context)

    assert res["hospital_name"]["value"] == "RSJ. Aceh"
    assert "Banda Aceh" in res["hospital_address"]["value"]
    assert "Casablanca" not in res["hospital_address"]["value"]
    assert res["unit_serial_number"]["value"] == "SB88231"
    assert res["tube_serial_number"]["value"] == "20G9912"
    assert res["unit_brand"]["value"] == "Fujifilm"


def test_context_guided_audit_guardrail_different_hospital():
    # Safety test: if the uploaded document is legitimately for a DIFFERENT hospital,
    # it must NOT blindly hallucinate or copy the context hospital.
    pages = [
        """
        BERITA ACARA UJI FUNGSI
        Rumah Sakit: RSUD Dr. Soetomo
        Alamat: Jl. Mayjen Prof. Dr. Moestopo No. 6-8, Surabaya
        Model: Somatom go.Top
        Nomor Seri: 109283
        """
    ]

    # Context belongs to RS Jiwa Aceh
    context = {
        "hospital_name": "RS Jiwa Aceh",
        "hospital_address": "Jl. Dr. Zainoel Abidin No. 1, Banda Aceh",
        "unit_serial_number": "SB88231",
    }

    res = extract_uji_fungsi_data(pages, context=context)

    # It must extract what is genuinely on this document
    assert "Soetomo" in res["hospital_name"]["value"]
    assert "Surabaya" in res["hospital_address"]["value"]
    assert res["unit_serial_number"]["value"] == "109283"


def test_context_guided_generic_fields_equipment_confirmation():
    pages = [
        """
        SISTEM MANAJEMEN FASILITAS RADIOLOGI
        RUMAH SAKIT JIWAACEH
        Jl. Dr. Zainoel Abidin No. 1 Banda Aceh
        Pesawat sinar-X yang digunakan bermerk Fujifilm tipe FDR nano C35 dengan no seri SB88231.
        """
    ]

    context = {
        "hospital_name": "Rumah Sakit Jiwa Aceh",
        "hospital_address": "Jl. Dr. Zainoel Abidin No. 1, Banda Aceh",
        "unit_brand": "Fujifilm",
        "unit_type": "FDR nano C35",
        "unit_serial_number": "SB88231",
    }

    res = extract_generic_fields(
        pages,
        ["hospital_name", "hospital_address", "unit_brand", "unit_type", "unit_serial_number"],
        context=context,
    )

    assert "JIWAACEH" in res["hospital_name"]["value"].upper()
    assert "Banda Aceh" in res["hospital_address"]["value"]
    assert res["unit_brand"]["value"] == "Fujifilm"
    assert res["unit_type"]["value"] == "FDR nano C35"
    assert res["unit_serial_number"]["value"] == "SB88231"


def test_context_guided_llm_prompt_building():
    context = {
        "hospital_name": "RS Jiwa Aceh",
        "hospital_address": "Jl. Dr. Zainoel Abidin No. 1, Banda Aceh",
        "unit_serial_number": "SB88231",
        "unit_brand": "Fujifilm",
    }

    prompt = build_extraction_prompt(
        doc_type="uji_fungsi",
        text="Sample text content",
        target_fields=["hospital_name", "unit_serial_number"],
        context=context,
    )

    assert "DATA ACUAN DARI FORMULIR PERMOHONAN" in prompt
    assert "RS Jiwa Aceh" in prompt
    assert "SB88231" in prompt
    assert "ATURAN UTAMA: Ekstrak nilai HANYA jika informasi tersebut memang terdapat" in prompt
