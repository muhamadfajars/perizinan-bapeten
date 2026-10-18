"""LLM-based entity extractor and fallback engine using local Ollama (Qwen 2.5 7B).

This module provides structured JSON extraction for high-variance or complex
licensing documents (such as Uji Fungsi, Persetujuan Impor, Spesifikasi Pesawat,
Paparan Radiasi, and Uji Kesesuaian) while seamlessly merging with deterministic
rule-based parsers.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

import requests

from config import (
    HIGH_VARIANCE_DOCS,
    LLM_TIMEOUT_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    USE_LLM_EXTRACTION,
)
from src.schema.fields import DOCUMENT_FIELDS

logger = logging.getLogger(__name__)

# Field definitions and guidance for Qwen 2.5
FIELD_DESCRIPTIONS: Dict[str, str] = {
    "hospital_name": "Nama lengkap rumah sakit, klinik, atau fasilitas pemohon/pelanggan (contoh: RSUD Dr. Soetomo, PT Medika Jaya Sentosa)",
    "hospital_address": "Alamat lengkap rumah sakit atau fasilitas pemohon/pelanggan (contoh: Jl. Panglima Sudirman No. 120, Madiun)",
    "unit_brand": "Merk atau pabrikan pesawat sinar-X / unit radiologi (contoh: Shimadzu, GE Healthcare, Philips, Siemens, United Imaging)",
    "unit_type": "Tipe atau model pesawat sinar-X / unit (contoh: Optima XR220amx, RADspeed Fit, MobileArt Evolution, uDR 592)",
    "unit_serial_number": "Nomor seri (Serial Number / S/N / No Seri) khusus UNIT pesawat rontgen / generator",
    "tube_brand": "Merk atau pabrikan tabung sinar-X (X-Ray Tube) (contoh: Shimadzu, Varex, Canon, Toshiba, Maxiray)",
    "tube_type": "Tipe atau model tabung sinar-X / insert model / housing model (contoh: 0.6/1.2 P 18 DE, E7239X, Maxiray 75)",
    "tube_serial_number": "Nomor seri khusus TABUNG sinar-X (Tube Serial Number / S/N Tabung)",
    "person_name": "Nama lengkap personel / dokter spesialis radiologi / fisikawan medik / radiografer",
    "ppr_name": "Nama Petugas Proteksi Radiasi (PPR) yang ditunjuk",
    "profession": "Profesi atau jabatan keahlian (contoh: Petugas Proteksi Radiasi Medik Tingkat 1, Spesialis Radiologi)",
    "valid_until": "Tanggal batas akhir masa berlaku izin / sertifikat / SIP (format: YYYY-MM-DD)",
    "practice_location": "Alamat atau nama fasilitas tempat praktik",
    "usage_period": "Periode pemakaian alat ukur radiasi / TLD (contoh: Triwulan I 2024 atau Januari - Maret 2024)",
    "conformity_test_clause": "Klausul, bab, atau kalimat mengenai kewajiban pelaksanaan uji kesesuaian berkala",
    "radiation_exposure_acceptance": "Status atau kesimpulan keberterimaan hasil paparan radiasi (contoh: Memenuhi Syarat, Diterima, Aman)",
    "approval": "Pengesahan tanda tangan dan stempel (contoh: Ada tanda tangan dan stempel basah)",
}

# Alias mappings for common variant keys that LLMs might return
KEY_ALIASES: Dict[str, str] = {
    "nama_rumah_sakit": "hospital_name",
    "nama_rs": "hospital_name",
    "nama_instansi": "hospital_name",
    "pelanggan": "hospital_name",
    "customer": "hospital_name",
    "customer_name": "hospital_name",
    "alamat_rumah_sakit": "hospital_address",
    "alamat_rs": "hospital_address",
    "alamat": "hospital_address",
    "customer_address": "hospital_address",
    "merk_unit": "unit_brand",
    "merk_pesawat": "unit_brand",
    "brand_unit": "unit_brand",
    "tipe_unit": "unit_type",
    "tipe_pesawat": "unit_type",
    "model_unit": "unit_type",
    "model_pesawat": "unit_type",
    "no_seri_unit": "unit_serial_number",
    "nomor_seri_unit": "unit_serial_number",
    "serial_number_unit": "unit_serial_number",
    "unit_sn": "unit_serial_number",
    "merk_tabung": "tube_brand",
    "tipe_tabung": "tube_type",
    "model_tabung": "tube_type",
    "tube_model": "tube_type",
    "no_seri_tabung": "tube_serial_number",
    "nomor_seri_tabung": "tube_serial_number",
    "tube_sn": "tube_serial_number",
    "nama_petugas": "person_name",
    "nama_dokter": "person_name",
    "nama_ppr": "ppr_name",
    "masa_berlaku": "valid_until",
    "berlaku_sampai": "valid_until",
    "periode_pemakaian": "usage_period",
    "status_paparan": "radiation_exposure_acceptance",
    "keberterimaan": "radiation_exposure_acceptance",
}


def is_ollama_available(base_url: str = OLLAMA_BASE_URL, timeout: float = 1.5) -> bool:
    """Check if the local Ollama daemon is running and has the target model."""
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(OLLAMA_MODEL in m for m in models) or len(models) > 0
    except Exception as exc:
        logger.debug("Ollama is not available: %s", exc)
    return False


def clean_json_output(raw_text: str) -> Dict[str, Any]:
    """Parse JSON response from LLM, stripping markdown wrappers and fixing anomalies."""
    if not raw_text or not raw_text.strip():
        return {}

    text = raw_text.strip()
    # Strip markdown ```json ... ``` blocks
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # If wrapped in single outer key like {"data": {...}} or {"extraction": {...}}
            if len(data) == 1:
                single_val = next(iter(data.values()))
                if isinstance(single_val, dict):
                    return single_val
            return data
    except Exception:
        # Fallback: extract the outermost {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                candidate = text[start : end + 1]
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Failed to parse extracted JSON candidate: %s", e)

    return {}


def build_extraction_prompt(
    doc_type: str,
    text: str,
    target_fields: Optional[List[str]] = None,
) -> str:
    """Build a precise structured extraction prompt in Indonesian for Qwen 2.5."""
    fields_to_extract = target_fields or DOCUMENT_FIELDS.get(doc_type, [])
    # Filter out complex multi-entity arrays handled natively
    filtered_fields = [
        f for f in fields_to_extract if f not in ("personnel_data", "administrative_documents", "table_of_contents")
    ]

    field_instructions = []
    for f in filtered_fields:
        desc = FIELD_DESCRIPTIONS.get(f, f"Nilai untuk {f}")
        field_instructions.append(f'- "{f}": {desc}')

    instructions_str = "\n".join(field_instructions)

    prompt = f"""Anda adalah sistem AI pakar ekstraksi dokumen perizinan ketenaganukliran BAPETEN.
Tugas Anda adalah mengekstrak field data berikut secara akurat dari teks dokumen berjenis "{doc_type}":

Field yang wajib diekstrak dalam format JSON:
{instructions_str}

ATURAN PENTING:
1. Kembalikan HANYA objek JSON murni (valid JSON) tanpa teks pengantar, markdown penjelasan, atau komentar.
2. Jangan menukar antara nomor seri unit pesawat ("unit_serial_number") dan nomor seri tabung rontgen ("tube_serial_number").
3. Jika informasi suatu field TIDAK ditemukan dalam teks, berikan nilai string kosong "".
4. Bersihkan prefiks label seperti "S/N:", "No. Seri:", "Merk:" dari nilai hasil ekstraksi.
5. Gunakan nilai eksak seperti yang tertulis dalam dokumen.

Teks Dokumen:
\"\"\"
{text}
\"\"\"
"""
    return prompt


def extract_with_llm(
    doc_type: str,
    text: str,
    target_fields: Optional[List[str]] = None,
    timeout: float = LLM_TIMEOUT_SECONDS,
    base_url: str = OLLAMA_BASE_URL,
    model: str = OLLAMA_MODEL,
) -> Dict[str, Dict[str, Any]]:
    """Query local Ollama Qwen 2.5 to extract structured fields from document text."""
    if not text or not text.strip():
        return {}

    # Truncate text to avoid excessive prompt evaluation time (first ~7500 chars usually contains headers & specs)
    truncated_text = text[:7500].strip()

    prompt = build_extraction_prompt(doc_type, truncated_text, target_fields)
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": 4096,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code != 200:
            logger.error("Ollama API returned status %s: %s", resp.status_code, resp.text)
            return {}

        resp_json = resp.json()
        raw_response = resp_json.get("response", "")
        extracted_dict = clean_json_output(raw_response)
        if not extracted_dict:
            return {}

        # Normalize keys and map to standard field dicts
        result: Dict[str, Dict[str, Any]] = {}
        for k, v in extracted_dict.items():
            canonical_key = KEY_ALIASES.get(k.lower().strip(), k.lower().strip())
            str_val = str(v).strip() if v is not None else ""
            if str_val and str_val not in ("-", "—", "null", "None"):
                result[canonical_key] = {
                    "value": str_val,
                    "page": None,
                    "method": "llm_qwen2.5",
                    "confidence": 0.95,
                }

        return result

    except Exception as exc:
        logger.warning("Error during LLM extraction for doc_type '%s': %s", doc_type, exc)
        return {}


def is_field_empty(field_entry: Any) -> bool:
    """Check if a field value in parsed dictionary is empty or not found."""
    if not field_entry:
        return True
    if isinstance(field_entry, dict):
        val = field_entry.get("value")
        return val in ("", "-", "—", None, [], {})
    return field_entry in ("", "-", "—", None, [], {})


def merge_with_llm_fallback(
    doc_type: str,
    parsed_fields: Dict[str, Any],
    pages_text: List[str],
    force_llm: bool = False,
    timeout: float = LLM_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Inspect parsed fields from rule-based parser. If expected fields are missing,

    or if document type is high-variance, query local Ollama LLM as fallback.
    """
    import os
    if not USE_LLM_EXTRACTION or ("PYTEST_CURRENT_TEST" in os.environ and not force_llm):
        return parsed_fields

    expected = DOCUMENT_FIELDS.get(doc_type, [])
    if not expected or not pages_text:
        return parsed_fields

    # Identify missing fields
    missing_fields = [f for f in expected if f not in ("personnel_data", "administrative_documents", "table_of_contents") and is_field_empty(parsed_fields.get(f))]

    # Criteria to invoke LLM:
    # 1. force_llm is True, OR
    # 2. Document is in HIGH_VARIANCE_DOCS and at least one field is missing, OR
    # 3. Critical equipment fields (unit_serial_number, tube_serial_number, unit_brand, unit_type) are missing
    critical_missing = any(
        f in missing_fields
        for f in ("unit_serial_number", "tube_serial_number", "unit_brand", "unit_type", "hospital_name")
    )
    should_invoke = (
        force_llm
        or (doc_type in HIGH_VARIANCE_DOCS and len(missing_fields) > 0)
        or (critical_missing and len(missing_fields) > 0)
    )

    if not should_invoke:
        return parsed_fields

    # Check Ollama availability before making request
    if not is_ollama_available():
        logger.debug("Ollama is not running. Skipping LLM fallback for %s.", doc_type)
        return parsed_fields

    logger.info(
        "Invoking LLM extraction for '%s' (missing fields: %s)",
        doc_type,
        missing_fields,
    )

    combined_text = "\n".join(pages_text)
    llm_extracted = extract_with_llm(
        doc_type=doc_type,
        text=combined_text,
        target_fields=missing_fields,
        timeout=timeout,
    )

    if not llm_extracted:
        return parsed_fields

    merged = dict(parsed_fields)
    for field_name, llm_item in llm_extracted.items():
        if field_name in expected and is_field_empty(merged.get(field_name)):
            merged[field_name] = llm_item

    return merged
