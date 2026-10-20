import re
from typing import List, Dict, Any, Optional

from src.schema.fields import DOCUMENT_FIELDS
from src.extraction.generic_parser import (
    extract_facility_name,
    extract_facility_address,
    extract_generic_fields,
    extract_raw_blocks,
    clean_value,
    VENDOR_HEADER_ADDR_RE,
    _score_facility_cand,
    _score_addr_cand,
)
from src.extraction.form_parser import extract_form_data, parse_people_tables, split_type_and_serial
from src.matching.normalizer import normalize_date
from src.extraction.llm_extractor import merge_with_llm_fallback


def _empty(value="-"):
    return {"value": value, "page": None, "method": "not_found", "confidence": None}


def _first_match(pages_text, patterns):
    for page_index, page_text in enumerate(pages_text or [], start=1):
        if not page_text:
            continue
        for pattern in patterns:
            match = re.search(pattern, str(page_text), re.IGNORECASE)
            if match:
                value = clean_value(match.group(1))
                if value:
                    return {"value": value, "page": page_index, "method": "native_text_regex", "confidence": 1.0}
    return _empty()


def _merge(base, updates):
    result = dict(base)
    for key, value in updates.items():
        if value and value.get("value") not in ("", [], None, "-", "—"):
            result[key] = value
        elif key not in result:
            result[key] = value
    return result


def _finalize_document_fields(doc_type: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    expected = DOCUMENT_FIELDS.get(doc_type, [])

    # 1. Synthesize individual fields if missing/empty but compound exists
    if "unit_type" in expected or "unit_serial_number" in expected:
        uts = fields.get("unit_type_serial", {}).get("value") if isinstance(fields.get("unit_type_serial"), dict) else fields.get("unit_type_serial")
        if uts and uts not in ("-", "—"):
            ut = fields.get("unit_type", {}).get("value") if isinstance(fields.get("unit_type"), dict) else fields.get("unit_type")
            us = fields.get("unit_serial_number", {}).get("value") if isinstance(fields.get("unit_serial_number"), dict) else fields.get("unit_serial_number")
            if not ut or ut in ("-", "—") or not us or us in ("-", "—"):
                s_ut, s_us = split_type_and_serial(uts)
                p = fields.get("unit_type_serial", {}).get("page")
                if "unit_type" in expected and (not ut or ut in ("-", "—")) and s_ut:
                    fields["unit_type"] = {"value": s_ut, "page": p, "method": "split", "confidence": 1.0}
                if "unit_serial_number" in expected and (not us or us in ("-", "—")) and s_us:
                    fields["unit_serial_number"] = {"value": s_us, "page": p, "method": "split", "confidence": 1.0}

    if "tube_type" in expected or "tube_serial_number" in expected:
        tts = fields.get("tube_type_serial", {}).get("value") if isinstance(fields.get("tube_type_serial"), dict) else fields.get("tube_type_serial")
        if tts and tts not in ("-", "—"):
            tt = fields.get("tube_type", {}).get("value") if isinstance(fields.get("tube_type"), dict) else fields.get("tube_type")
            ts = fields.get("tube_serial_number", {}).get("value") if isinstance(fields.get("tube_serial_number"), dict) else fields.get("tube_serial_number")
            if not tt or tt in ("-", "—") or not ts or ts in ("-", "—"):
                s_tt, s_ts = split_type_and_serial(tts)
                p = fields.get("tube_type_serial", {}).get("page")
                if "tube_type" in expected and (not tt or tt in ("-", "—")) and s_tt:
                    fields["tube_type"] = {"value": s_tt, "page": p, "method": "split", "confidence": 1.0}
                if "tube_serial_number" in expected and (not ts or ts in ("-", "—")) and s_ts:
                    fields["tube_serial_number"] = {"value": s_ts, "page": p, "method": "split", "confidence": 1.0}

    if "tube_type" in expected:
        tt = fields.get("tube_type", {}).get("value") if isinstance(fields.get("tube_type"), dict) else fields.get("tube_type")
        if not tt or tt in ("-", "—"):
            cand = fields.get("tube_insert_model", {}).get("value") or fields.get("tube_unit_model", {}).get("value")
            if cand and cand not in ("-", "—"):
                p_cand = fields.get("tube_insert_model", {}).get("page") or fields.get("tube_unit_model", {}).get("page")
                fields["tube_type"] = {"value": cand, "page": p_cand, "method": "ocr", "confidence": 1.0}

    # Also synthesize compound fields if expected
    if "unit_type_serial" in expected:
        cur_uts = fields.get("unit_type_serial", {}).get("value") if isinstance(fields.get("unit_type_serial"), dict) else fields.get("unit_type_serial")
        if not cur_uts or cur_uts in ("-", "—"):
            ut = fields.get("unit_type", {}).get("value") if isinstance(fields.get("unit_type"), dict) else fields.get("unit_type")
            us = fields.get("unit_serial_number", {}).get("value") if isinstance(fields.get("unit_serial_number"), dict) else fields.get("unit_serial_number")
            ut_str = ut if ut and ut not in ("-", "—") else ""
            us_str = us if us and us not in ("-", "—") else ""
            if ut_str or us_str:
                p = fields.get("unit_type", {}).get("page") or fields.get("unit_serial_number", {}).get("page")
                fields["unit_type_serial"] = {"value": f"{ut_str} / {us_str}".strip(" /"), "page": p, "method": "composite", "confidence": 1.0}

    if "tube_type_serial" in expected:
        cur_tts = fields.get("tube_type_serial", {}).get("value") if isinstance(fields.get("tube_type_serial"), dict) else fields.get("tube_type_serial")
        if not cur_tts or cur_tts in ("-", "—"):
            tt = fields.get("tube_type", {}).get("value") or fields.get("tube_insert_model", {}).get("value") or fields.get("tube_unit_model", {}).get("value")
            ts = fields.get("tube_serial_number", {}).get("value")
            tt_str = tt if tt and tt not in ("-", "—") else ""
            ts_str = ts if ts and ts not in ("-", "—") else ""
            if tt_str or ts_str:
                p = fields.get("tube_type", {}).get("page") or fields.get("tube_serial_number", {}).get("page")
                fields["tube_type_serial"] = {"value": f"{tt_str} / {ts_str}".strip(" /"), "page": p, "method": "composite", "confidence": 1.0}

    # 2. Ensure every expected field is present, and set value to '-' if not present or empty
    for k in expected:
        if k not in fields or fields[k] is None:
            fields[k] = {"value": "-", "page": None, "method": "not_found", "confidence": None}
        else:
            item = fields[k]
            if isinstance(item, dict):
                v = item.get("value")
                if v in ("", None, [], {}):
                    item["value"] = "-"
                    item["confidence"] = None
                elif isinstance(v, str) and not v.strip():
                    item["value"] = "-"
                    item["confidence"] = None
                elif isinstance(v, dict):
                    if not any(val and str(val).strip() not in ("-", "—") for val in v.values()):
                        item["value"] = "-"
                        item["confidence"] = None
                elif isinstance(v, list):
                    if len(v) == 0:
                        item["value"] = "-"
                        item["confidence"] = None
            else:
                if item in ("", None, [], {}):
                    fields[k] = {"value": "-", "page": None, "method": "not_found", "confidence": None}
                else:
                    fields[k] = {"value": str(item), "page": None, "method": "extracted", "confidence": 1.0}

    return fields


def _rx(label_group):
    return rf"(?:{label_group})[ \t]*:[ \t]*(.+)"


def _rx_optional_colon(label_group):
    return rf"\b(?:{label_group})\b[ \t]*:?[ \t]*(.+)"


# Multilingual & multi-format synonym patterns for X-ray tube components
RX_INSERT_SERIAL = (
    r"(?:No\.?\s*Seri(?:\s+Insert(?:\s+Tabung)?|\s+Tabung\s+Sisipan|\s+Sisipan|\s+Insersi(?:\s+Tabung)?)"
    r"|Nomor\s+Seri(?:\s+Insert(?:\s+Tabung)?|\s+Tabung\s+Sisipan|\s+Sisipan|\s+Tabung\s+Insert|\s+Insersi(?:\s+Tabung)?)"
    r"|Nomor\s*seriinsersi"
    r"|Insert(?:\s+Tube|\s+Tabung)?\s*(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?)"
    r"|Insersi(?:\s+Tube|\s+Tabung)?\s*(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?)"
    r"|Tube\s+Insert\s*(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?)"
    r"|X-?Ray\s+Tube\s+Insert\s*(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?)"
    r")\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)"
)

RX_HOUSING_SERIAL = (
    r"(?:No\.?\s*Seri(?:\s+Housing|\s+Wadah(?:\s+Tabung)?|\s+Tabung|\s+Casing)"
    r"|Nomor\s+Seri(?:\s+Housing|\s+Wadah(?:\s+Tabung)?|\s+Tabung|\s+Casing)"
    r"|(?:Tube\s+Housing|Housing\s+Tube|Housing|Wadah\s+Tabung|Tube)\s*(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?)"
    r"|Serial\s+No\.?\s*(?:Tube|Housing|Wadah)"
    r")\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)"
)

RX_INSERT_MODEL = (
    r"(?:No\.?\s*Model\s*Insert|Model\s*Insert|Insert\s*Model|Tipe\s*Insert|Insert\s*Type"
    r"|Model(?:\s+Tabung)?\s+Sisipan|Tipe(?:\s+Tabung)?\s+Sisipan"
    r")\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)"
)

RX_HOUSING_MODEL = (
    r"(?:No\.?\s*Model(?:\s+Tabung|\s+Housing|\s+Wadah)"
    r"|Model(?:\s+Tabung|\s+Housing|\s+Wadah)"
    r"|Tipe(?:\s+Tabung|\s+Housing|\s+Wadah)"
    r"|(?:Tube\s+Housing|Housing\s+Tube|Housing)\s*Model"
    r")\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)"
)


def _normalize_ocr_serial(val: str) -> str:
    """Correct frequent OCR character misrecognitions in serial numbers (e.g. OF1376 -> 0F1376)."""
    if not val:
        return ""
    # Letter 'O' misrecognized as digit '0' when followed by 'F' and digits (Canon tube format 0Fxxxx)
    return re.sub(r"^OF(?=\d+)", "0F", val, flags=re.I)


def _extract_tube_insert_model(all_text: str) -> str:
    """Extract tube insert model, robust to OCR column interleaving and bullet numbers."""
    m_line = re.search(
        r"(?:No\.?\s*Model\s*Insert|Model\s*Insert|Insert\s*Model|Tipe\s*Insert|Insert\s*Type"
        r"|Model(?:\s+Tabung)?\s+Sisipan|Tipe(?:\s+Tabung)?\s+Sisipan)[^\n\r]*",
        all_text,
        re.I,
    )
    if m_line:
        line_text = m_line.group(0)
        # Check if line contains a standard tube model code (e.g. E7894, MRC 200, ATHLON)
        m_code = re.search(r"\b(E[0-9]{4}[A-Za-z0-9]*|MRC[ \t]*[0-9]+|ATHLON[ \t]*[A-Za-z]+)\b", line_text, re.I)
        if m_code:
            return m_code.group(1).strip()
        # Check for explicit colon / equals delimiter
        m_col = re.search(r"[:=\-–]\s*([A-Za-z0-9\-_]+)", line_text)
        if m_col and not (m_col.group(1).isdigit() and len(m_col.group(1)) <= 2):
            return m_col.group(1).strip()
        # Fallback to tokens on line after keyword, skipping bullet numbers and keywords
        tokens = line_text.split()
        for tok in tokens[2:]:
            tok_clean = tok.strip(" :;-,")
            if (
                tok_clean
                and not (tok_clean.isdigit() and len(tok_clean) <= 2)
                and tok_clean.lower() not in ("no", "seri", "model", "tabung", "insert", "tipe", "sisipan")
            ):
                return tok_clean
    # Fallback to regex pattern match
    m = re.search(RX_INSERT_MODEL, all_text, re.I)
    if m:
        val = clean_value(m.group(1)).strip(" :;-,")
        if not (val.isdigit() and len(val) <= 2):
            return val
    return ""



def extract_ppkr_data(pages_text, tables, context=None):
    """Parses PPKR document text and structured personnel tables with context guidance."""
    fields = extract_generic_fields(
        pages_text,
        [
            "hospital_name", "hospital_address",
            "person_name", "unit_brand", "unit_type",
            "unit_serial_number", "tube_brand", "tube_type",
            "tube_serial_number",
        ],
        context=context,
    )
    # Prioritize Tube Insert Serial Number (e.g. 'Nomor seriinsersi 0F1376') over Housing S/N
    for p_idx, page_text in enumerate(pages_text, start=1):
        m_ins = re.search(
            r"(?:Nomor\s*seri\s*insersi|No\.?\s*seri\s*insersi|Nomor\s*seriinsersi|seriinsersi|seri\s*insert|insert\s*s/?n|insersi\s*tabung)\s*[:=\-–]?\s*([0-9][A-Za-z0-9]{4,})",
            str(page_text or ""),
            re.IGNORECASE,
        )
        if m_ins:
            insert_sn = _normalize_ocr_serial(m_ins.group(1).strip())
            fields["tube_serial_number"] = {
                "value": insert_sn,
                "page": p_idx,
                "line": None,
                "method": "native_text_regex",
                "confidence": 1.0,
            }
            break

    # Synthesize unit_type_serial and tube_type_serial
    ut = fields.get("unit_type", {}).get("value", "")
    us = fields.get("unit_serial_number", {}).get("value", "")
    uts = f"{ut} / {us}".strip(" /") if (ut or us) else ""
    fields["unit_type_serial"] = {
        "value": uts,
        "page": fields.get("unit_type", {}).get("page") or fields.get("unit_serial_number", {}).get("page"),
        "method": "composite",
        "confidence": 1.0 if uts else None,
    }

    tt = fields.get("tube_type", {}).get("value", "")
    ts = fields.get("tube_serial_number", {}).get("value", "")
    tts = f"{tt} / {ts}".strip(" /") if (tt or ts) else ""
    fields["tube_type_serial"] = {
        "value": tts,
        "page": fields.get("tube_type", {}).get("page") or fields.get("tube_serial_number", {}).get("page"),
        "method": "composite",
        "confidence": 1.0 if tts else None,
    }

    # PPKR has an explicitly named "data petugas" table group in the scope
    people = parse_people_tables(tables)
    fields["personnel_data"] = {
        "value": people,
        "page": None,
        "method": "native_text_table",
        "confidence": 1.0 if people else None,
    }
    # Enrich person_name with full doctor name from personnel table if available
    doctor_entry = next((p for p in people if re.search(r"\bdr\b\.?", p.get("name", ""), re.I)), None)
    if doctor_entry and doctor_entry.get("name"):
        doc_name = doctor_entry["name"]
        if len(doc_name) >= len(fields.get("person_name", {}).get("value", "")):
            fields["person_name"] = {
                "value": doc_name,
                "page": doctor_entry.get("page") or fields.get("person_name", {}).get("page"),
                "method": "native_text_table",
                "confidence": 1.0,
            }
    for k, item in fields.items():
        if isinstance(item, dict) and item.get("value") not in ("", None, [], "-", "—"):
            if item.get("confidence") is None:
                item["confidence"] = 1.0
    return fields


def extract_sib_data(pages_text):
    """Robustly extracts PPR name, profession, and expiration date from SIB certificate."""
    ppr_name = ""
    name_page = None
    profession = ""
    prof_page = None
    valid_until = ""
    valid_page = None

    for p_idx, page in enumerate(pages_text, start=1):
        lines = [l.strip() for l in str(page or "").splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            # 1. ppr_name
            if not ppr_name:
                # 1a. Explicit same-line with colon/separator: e.g. 'Nama : Siti Azizah', 'Diberikan kepada: John Doe'
                m_colon = re.search(
                    r"(?:Diberikan\s+kepada|Nama\s+(?:Lengkap|PPR|Pemegang(?:\s+SIB)?)?|Nama\s*/\s*Name|Kepada)\s*[:=\-–]\s*([A-Za-z .,'\-]+?)(?:\s+(?:a\.?n\.?|p\.?p\.?|Direktur|Director|Kepala|BAPETEN|Nomor|NIK|No\.|Berlaku|Valid\b)|$)",
                    line,
                    re.IGNORECASE,
                )
                if m_colon:
                    cand = clean_value(m_colon.group(1)).strip(" :;-,")
                    if len(cand) >= 3 and not re.search(r"^(?:Petugas|BAPETEN|Surat|Keputusan|Izin|Name|a\.?n\.?|p\.?p\.?|u\.?b\.?|d\.?a\.?)(?:\b|\s|$)", cand, re.I):
                        ppr_name = cand
                        name_page = p_idx

                # 1b. Multi-line or card layout: line contains 'Nama / Name' or 'Nama' as header label
                if not ppr_name and re.search(r"(?:^|\b)(?:Diberikan\s+kepada|Nama\s+(?:Lengkap|PPR|Pemegang(?:\s+SIB)?)?|Nama\s*/\s*Name|Kepada)(?:\b|\s*[:=\-–]|$)", line, re.I):
                    for cand_line in lines[idx + 1 : idx + 5]:
                        cand_split = re.split(
                            r"\b(?:Direktur|Director|Kepala|BAPETEN|a\.?n\.?|p\.?p\.?|NIP|Jakarta|Nomor|Berlaku|Valid)\b",
                            cand_line,
                            flags=re.I,
                        )[0]
                        cand = clean_value(cand_split).strip(" :;-,")
                        if len(cand) >= 3 and not re.search(
                            r"^(?:Petugas|BAPETEN|Surat|Keputusan|Nomor|NIK|No\.|Direktur|Director|Kepala|Perizinan|Licensing|Radioactive|PPR|Masa|Berlaku|Valid|Tanggal|Date|a\.?n\.?|p\.?p\.?|u\.?b\.?|d\.?a\.?)(?:\b|\s|$)",
                            cand,
                            re.I,
                        ):
                            ppr_name = cand
                            name_page = p_idx
                            break

            # 2. profession
            if not profession:
                m_prof = re.search(
                    r"(?:Sebagai|Kualifikasi|Klasifikasi(?:/Classification)?|Profesi|Keahlian|Jabatan|Jenis\s+SIB)\s*[:=\-–]?\s*([^\n\r]*)$",
                    line,
                    re.IGNORECASE,
                )
                if m_prof:
                    cand_prof = clean_value(m_prof.group(1)).strip(" :;-,")
                    if not cand_prof and idx + 1 < len(lines):
                        cand_prof = clean_value(lines[idx + 1]).strip(" :;-,")
                    if cand_prof and not re.search(r"^(?:Nama|Nomor|Nilai|Ujian|Date|Tanggal)\b", cand_prof, re.I):
                        profession = cand_prof
                        prof_page = p_idx
                elif re.match(r"^(?:Petugas\s+Proteksi\s+Radiasi|PPR)\b", line, re.I):
                    cand_prof = clean_value(line).strip(" :;-,")
                    if idx + 1 < len(lines):
                        next_l = clean_value(lines[idx + 1]).strip(" :;-,")
                        if (re.search(r"(?:dan(?:\s+atau|/atau)?|or|and|/|-)$", cand_prof, re.I) or
                            re.match(r"^(?:Intervensional|Medik|Industri|Tingkat|Gauging|Radiografi)\b", next_l, re.I)):
                            if not re.search(r"^(?:Nama|Nomor|No\.|NIK|Berlaku|Valid)\b", next_l, re.I):
                                cand_prof = f"{cand_prof} {next_l}"
                    profession = cand_prof
                    prof_page = p_idx

            # 3. valid_until
            if not valid_until:
                m_range = re.search(
                    r"(?:s/?d|s\.d\.|sampai(?:\s+dengan)?|hingga)\s*[:=\-–]?\s*([0-9]{1,2}[ \t]+[A-Za-z]+[ \t]+[0-9]{4}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}|[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2})",
                    line,
                    re.IGNORECASE,
                )
                if m_range:
                    valid_until = normalize_date(clean_value(m_range.group(1)))
                    valid_page = p_idx
                else:
                    m_exp = re.search(
                        r"(?:masa\s+berlaku(?:\s+izin)?|berlaku\s+(?:sampai|hingga|s/?d)?|tanggal\s+berakhir)\s*[:=\-–]?\s*([0-9]{1,2}[ \t]+[A-Za-z]+[ \t]+[0-9]{4}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}|[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2})",
                        line,
                        re.IGNORECASE,
                    )
                    if m_exp:
                        valid_until = normalize_date(clean_value(m_exp.group(1)))
                        valid_page = p_idx
                    elif re.search(r"(?:berlaku\s+s\.?d\.?|masa\s+berlaku|valid\s+until)\b", line, re.I):
                        for cand_line in lines[idx + 1 : idx + 4]:
                            m_next = re.search(
                                r"([0-9]{1,2}[ \t]+[A-Za-z]+[ \t]+[0-9]{4}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}|[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2})",
                                cand_line,
                            )
                            if m_next:
                                valid_until = normalize_date(clean_value(m_next.group(1)))
                                valid_page = p_idx
                                break

        full_p_txt = "\n".join(lines)
        if not profession:
            m_ppr = re.search(r"\b(Petugas\s+Proteksi\s+Radiasi[^\n\r,;|]*|PPR\s+[^\n\r,;|]*)", full_p_txt, re.I)
            if m_ppr:
                cand = clean_value(m_ppr.group(1)).strip(" :;-,")
                after_lines = [l.strip() for l in full_p_txt[m_ppr.end():].splitlines() if l.strip()]
                if after_lines:
                    next_l = clean_value(after_lines[0]).strip(" :;-,")
                    if (re.search(r"(?:dan(?:\s+atau|/atau)?|or|and|/|-)$", cand, re.I) or
                        re.match(r"^(?:Intervensional|Medik|Industri|Tingkat|Gauging|Radiografi)\b", next_l, re.I)):
                        if not re.search(r"^(?:Nama|Nomor|No\.|NIK|Berlaku|Valid)\b", next_l, re.I):
                            cand = f"{cand} {next_l}"
                profession = cand
                prof_page = p_idx

        if not valid_until:
            m_any_date = re.search(r"(?:s/?d|s\.d\.|sampai(?:\s+dengan)?|valid\s+until)\s*[:=\-–/]*\s*([0-9]{1,2}[ \t]+[A-Za-z]+[ \t]+[0-9]{4}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4})", full_p_txt, re.I)
            if m_any_date:
                valid_until = normalize_date(clean_value(m_any_date.group(1)))
                valid_page = p_idx

    return {
        "ppr_name": {"value": ppr_name, "page": name_page, "method": "native_text_regex" if ppr_name else "not_found", "confidence": 1.0 if ppr_name else None},
        "profession": {"value": profession, "page": prof_page, "method": "native_text_regex" if profession else "not_found", "confidence": 1.0 if profession else None},
        "valid_until": {"value": valid_until, "page": valid_page, "method": "native_text_regex" if valid_until else "not_found", "confidence": 1.0 if valid_until else None},
    }


def extract_sip_data(pages_text: List[str]) -> Dict[str, Any]:
    """Robustly extracts person name, profession, valid_until, and practice location
    from Surat Izin Praktik (SIP) or Surat Izin Kerja Radiografer (SIKR).
    """
    all_text = "\n".join(pages_text or [])

    # 1. person_name
    person_name = ""
    name_page = None
    for p_idx, page in enumerate(pages_text or [], start=1):
        lines = [l.strip() for l in str(page or "").splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            # 1a. Nama : KHAIRUNNISA
            m_name = re.search(r"^\s*Nama\s*(?:Lengkap)?\s*[:=\-–]\s*([A-Za-z .,'\-]+)$", line, re.I)
            if m_name:
                cand = clean_value(m_name.group(1)).strip(" :;-,")
                if len(cand) >= 3 and not re.search(r"^(?:Dokter|Radiografer|Dinas|Pemerintah)\b", cand, re.I):
                    person_name = cand
                    name_page = p_idx
                    break
            # 1b. SIKR layout: line is '...memberikan izin Kerja kepada:' and candidate is next line
            if re.search(r"memberikan\s+izin\s+(?:Kerja|Praktik|Praktek)\s+kepada\s*[:=\-–]?$", line, re.I):
                if idx + 1 < len(lines):
                    cand = clean_value(lines[idx + 1]).strip(" :;-,")
                    if len(cand) >= 3 and not re.search(r"^(?:Tempat|Alamat|Nomor|Untuk)\b", cand, re.I):
                        person_name = cand
                        name_page = p_idx
                        break
        if person_name:
            break

    # 2. profession
    profession = ""
    prof_page = None
    m_prof = re.search(r"(?:Profesi|Keahlian|Jabatan)\s*[:=\-–]\s*([^\n\r]+)", all_text, re.I)
    if m_prof:
        profession = clean_value(m_prof.group(1)).strip(" :;-,")
        prof_page = _find_page_containing(pages_text, re.escape(profession))
    else:
        m_role = re.search(r"(?:sebagai|pekerjaan\s+sebagai)\s*[:=\-–]?\s*(Radiografer|Dokter\s+Spesialis\s+Radiologi|Fisikawan\s+Medik|Dokter)", all_text, re.I)
        if m_role:
            profession = clean_value(m_role.group(1)).strip(" :;-,")
            prof_page = _find_page_containing(pages_text, re.escape(profession))
        elif re.search(r"\b(?:SIKR|Surat\s+Izin\s+Kerja\s+Radiografer)\b", all_text, re.I):
            profession = "Radiografer"
            prof_page = 1

    # 3. valid_until
    valid_until = ""
    valid_page = None
    m_valid = re.search(
        r"(?:berlaku\s+sampai(?:\s+dengan)?(?:\s+tanggal)?|masa\s+berlaku)\s*[:=\-–]?\s*([0-9]{1,2}[ \t]+[A-Za-z]+[ \t]+[0-9]{4}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4})",
        all_text,
        re.I,
    )
    if m_valid:
        valid_until = normalize_date(clean_value(m_valid.group(1)).strip(" :;-,."))
        valid_page = _find_page_containing(pages_text, re.escape(m_valid.group(1).strip()))

    # 4. practice_location
    practice_location = ""
    loc_page = None
    m_loc = re.search(r"(?:Alamat\s+Praktik|Alamat\s+Praktek|Tempat\s+Praktik|Tempat\s+Praktek)\s*[:=\-–]\s*([^\n\r]+)", all_text, re.I)
    if m_loc:
        practice_location = clean_value(m_loc.group(1)).strip(" :;-,")
        loc_page = _find_page_containing(pages_text, re.escape(practice_location))
    else:
        m_at = re.search(r"(?:sebagai\s+Radiografer\s+di\s+|di\s+)(RS\.?\s+[A-Za-z0-9 .,/'-]+|Rumah\s+Sakit\s+[A-Za-z0-9 .,/'-]+|Puskesmas\s+[A-Za-z0-9 .,/'-]+|Klinik\s+[A-Za-z0-9 .,/'-]+)", all_text, re.I)
        if m_at:
            practice_location = clean_value(m_at.group(1)).strip(" :;-,")
            loc_page = _find_page_containing(pages_text, re.escape(practice_location))

    return {
        "person_name": {"value": person_name, "page": name_page, "method": "native_text_regex" if person_name else "not_found", "confidence": 1.0 if person_name else None},
        "profession": {"value": profession, "page": prof_page, "method": "native_text_regex" if profession else "not_found", "confidence": 1.0 if profession else None},
        "valid_until": {"value": valid_until, "page": valid_page, "method": "native_text_regex" if valid_until else "not_found", "confidence": 1.0 if valid_until else None},
        "practice_location": {"value": practice_location, "page": loc_page, "method": "native_text_regex" if practice_location else "not_found", "confidence": 1.0 if practice_location else None},
    }


def extract_sprint_data(pages_text: List[str]) -> Dict[str, Any]:
    """Robustly extracts PPR name and Approval/Signer from Surat Perintah (Sprint) / SK Penunjukan PPR."""
    ppr_name = ""
    name_page = None
    approval = ""
    appr_page = None

    NAME_NOISE = {
        "pasien", "pelayanan", "mutu", "keselamatan", "instalasi", "radiologi",
        "peraturan", "undang", "pedoman", "kebijakan", "menimbang", "mengingat",
        "memutuskan", "menetapkan", "rumah sakit", "rs", "pt", "tbk", "nomor",
        "surat", "keputusan", "direktur", "perjanjian", "konsultan", "kesehatan",
        "pemerintah", "republik", "indonesia"
    }

    def _is_valid_person(text: str) -> bool:
        t = text.lower().strip()
        if len(t) < 3 or len(t) > 60:
            return False
        words = set(re.findall(r"\b[a-z]{3,}\b", t))
        if words.intersection(NAME_NOISE):
            return False
        return bool(re.search(r"[a-zA-Z]{3,}", text))

    def _clean_person(text: str) -> str:
        s = clean_value(text).strip(" :;-,.")
        s = re.sub(r"^(?:Sdr/?i\.?|Saudara/?i\.?|Saudara|Sdri|Sdr|Bpk/?Ibu|Bapak|Ibu)\s+", "", s, flags=re.I).strip(" :;-,.")
        return s

    # 1. Search for PPR Name (Kepada / Petugas yang ditunjuk)
    for p_idx, page in enumerate(pages_text, start=1):
        lines = [l.strip() for l in str(page or "").splitlines() if l.strip()]
        full_page = "\n".join(lines)
        sk_patterns = [
            r"(?:PENUNJUK[K]?AN\s+(?:DAN\s+)?PENGANGKATAN|PENUNJUK[K]?AN)\s*\n*?\s*(?:SDR/?I\.?\s+|SAUDARA/?I\.?\s+|BAPAK/IBU\s+)?([A-Za-z .,'\-]+?)\s*\n*?\s*SEBAGAI\s*\n*?\s*PETUGAS\s+PROTEKSI\s+RADIASI",
            r"(?:PENUNJUK[K]?AN\s+(?:DAN\s+)?PENGANGKATAN|PENGANGKATAN)\s+(?:SDR/?I\.?\s+|SAUDARA/?I\.?\s+)?([A-Za-z .,'\-]+?)\s+SEBAGAI\s+PETUGAS\s+PROTEKSI\s+RADIASI",
            r"TENTANG\s+PENUNJUK[K]?AN[^\n\r]*?\s*(?:SDR/?I\.?\s+|SAUDARA/?I\.?\s+)?([A-Za-z .,'\-]+?)\s+SEBAGAI\s+PETUGAS\s+PROTEKSI\s+RADIASI",
            r"bahwa\s+(?:Sdr/?i\.?\s+|Saudara/?i\.?\s+)?([A-Za-z .,'\-]+?)\s+dinilai\s+mampu\s+dan\s+cakap\s+sebagai\s+Petugas\s+Proteksi",
            r"DIPERINTAHKAN\s*\n+\s*Kepada\s*[:\-–]?\s*([A-Za-z .,'\-]+)",
            r"(?:menugaskan\s+kepada|menugaskan)\s*[:\-–]?\s*\n*(?:Nama\s*(?:Lengkap)?\s*[:\-–]?\s*)?([A-Za-z .,'\-]+)",
        ]

        for pat in sk_patterns:
            m = re.search(pat, full_page, re.I | re.M)
            if m:
                cand = _clean_person(m.group(1))
                if _is_valid_person(cand):
                    ppr_name = cand
                    name_page = p_idx
                    break
        if ppr_name:
            break

        for line in lines:
            m_line = re.search(r"^\s*Kepada\s*[:\-–]\s*(?:Nama\s*[:\-–]?\s*)?([A-Za-z .,'\-]+)$", line, re.I)
            if not m_line:
                m_line = re.search(r"(?:Nama\s+PPR|Nama\s+Petugas)\s*[:\-–]\s*([A-Za-z .,'\-]+)$", line, re.I)
            if m_line:
                cand = _clean_person(m_line.group(1))
                if _is_valid_person(cand):
                    ppr_name = cand
                    name_page = p_idx
                    break
        if ppr_name:
            break

    # 2. Search for Approval / Signer (Direktur / Kepala RS / Karumkit)
    for p_idx, page in enumerate(pages_text, start=1):
        lines = [l.strip() for l in str(page or "").splitlines() if l.strip()]
        full_page = "\n".join(lines)
        appr_patterns = [
            r"(?:DIREKTUR|KEPALA\s+RUMAH\s+SAKIT|KOMANDAN|KARUMKIT)[^\n\r]*?,?\s*\n+([^\n\r]*?dr\.?\s+[A-Za-z .,'\-]+?(?:Sp\.[A-Za-z]+|MARS|M\.Kes|M\.Ked|M\.Biomed|PhD)?)(?:\s*\n|$)",
            r"(?:DIREKTUR|KEPALA\s+RUMAH\s+SAKIT|KOMANDAN|KARUMKIT)[^\n\r]*?,?\s*\n+([A-Z][A-Za-z .,'\-]+?(?:Sp\.[A-Za-z]+|MARS|M\.Kes)?)(?:\s*\n|$)",
            r"(?:Pengesahan|Disahkan\s+oleh|Mengetahui)[ \t]*[:\-–][ \t]*([^\n\r]+)",
            r"\b(dr\.?\s*[A-Za-z .,'\-]+?(?:Sp\.[A-Za-z]+|M\.Kes|MARS)?)(?:\s+(?:Kepala|Mayor|Letkol|Kapten|Kolonel|NIP|NRP)|\s*$)",
        ]
        for pat in appr_patterns:
            m = re.search(pat, full_page, re.I | re.M)
            if m:
                cand = clean_value(m.group(1)).strip(" :;-,.")
                cand = re.sub(r"^(?:DIREKTUR|KEPALA\s+RUMAH\s+SAKIT|KOMANDAN)[,\s]*", "", cand, flags=re.I).strip(" :;-,.")
                words = set(re.findall(r"\b[a-z]{3,}\b", cand.lower()))
                if not words.intersection({"peraturan", "undang", "pedoman", "kebijakan", "menimbang", "mengingat", "menteri", "perusahaan", "konsultan"}):
                    if len(cand) >= 3 and not re.search(r"^(?:Rumah\s+Sakit|PT\s+|Instalasi)\b", cand, re.I):
                        approval = cand
                        appr_page = p_idx
                        break
        if approval and (appr_page >= 2 or len(pages_text) == 1):
            break

    ppr_res = {"value": ppr_name, "page": name_page, "method": "native_text_regex" if ppr_name else "not_found", "confidence": 1.0 if ppr_name else None}
    appr_res = {"value": approval, "page": appr_page, "method": "native_text_regex" if approval else "not_found", "confidence": 1.0 if approval else None}

    return {
        "ppr_name": ppr_res,
        "approval": appr_res,
        "kepada": ppr_res,
        "pengesahan": appr_res,
    }


def extract_uji_kesesuaian_data(pages_text, tables=None, context=None):
    all_text = "\n".join(pages_text)

    # 1. hospital_name
    m_name = re.search(
        r"(?:Data\s+Pemohon\s+uji[\s\S]*?Nama\s+Instansi|Nama\s+Instansi|Nama\s+Rumah\s+Sakit|Nama\s+Fasilitas)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    hospital_name = clean_value(m_name.group(1)).strip(" :;-,") if m_name else ""
    if not hospital_name:
        fac_n, _ = extract_facility_name(pages_text, context=context)
        if fac_n:
            hospital_name = fac_n

    # 2. hospital_address
    m_addr = re.search(
        r"(?:Data\s+Pemohon\s+uji[\s\S]*?Alamat|Alamat\s+Instansi|Alamat\s+Rumah\s+Sakit|Alamat)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    hospital_address = clean_value(m_addr.group(1)).strip(" :;-,") if m_addr else ""
    if not hospital_address:
        fac_a, _ = extract_facility_address(pages_text, context=context)
        if fac_a:
            hospital_address = fac_a

    # 3. Generator section (unit_brand, unit_type, unit_serial_number, unit_type_serial)
    gen_block = ""
    m_gen = re.search(r"(?:A\.\s*Generator|Generator\s+dan\s+panel\s+Kendali[^\n]*)[^\n]*\n((?:[^\n]*\n?){1,10})", all_text, re.I)
    if m_gen:
        gen_block = m_gen.group(1)

    m_ub = re.search(r"(?:Pabrikan\s*/\s*Merk|Merk\s+Unit|Pabrikan)\s*[:=\-–]?\s*([^\n\r]+)", gen_block or all_text, re.I)
    unit_brand = clean_value(m_ub.group(1)).strip(" :;-,") if m_ub else ""
    if not unit_brand:
        m_ub_any = re.search(r"\b(GE|PHILIPS|SIEMENS|SHIMADZU|TOSHIBA|HITACHI|CARESTREAM|FUJIFILM)\b", all_text, re.I)
        if m_ub_any:
            unit_brand = m_ub_any.group(1).title()

    m_ut = re.search(r"(?:Model\s*/\s*Tipe(?!\s+Tabung)|Model\s+Unit|Model|Tipe(?!\s+Tabung))\s*[:=\-–]?\s*([^\n\r]+)", gen_block, re.I) if gen_block else None
    if not m_ut:
        m_ut = re.search(r"(?:Model\s*/\s*Tipe(?!\s+Tabung)|Model\s+Unit)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    unit_type = clean_value(m_ut.group(1)).strip(" :;-,") if m_ut else ""

    m_us = re.search(r"(?:Nomor\s+Seri(?!\s+Tabung)|No\.?\s*Seri(?!\s+Tabung))\s*[:=\-–]?\s*([^\n\r]+)", gen_block, re.I) if gen_block else None
    if not m_us:
        m_us = re.search(r"(?:Nomor\s+Seri(?!\s+Tabung)|No\.?\s*Seri(?!\s+Tabung))\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    unit_serial = clean_value(m_us.group(1)).strip(" :;-,") if m_us else ""

    # 4. Tube section (tube_brand, tube_type, tube_serial_number)
    m_tb = re.search(r"(?:Merek\s+Tabung|Merk\s+Tabung)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    if not m_tb:
        m_tb = re.search(r"B\.\s*Wadah\s+Tabung[^\n]*\n(?:[^\n]*\n){0,4}?[0-9]\.\s*Pabrikan/Merk\s+([^\n\r]+)", all_text, re.I)
    tube_brand = clean_value(m_tb.group(1)).strip(" :;-,") if m_tb else ""

    tube_type = _extract_tube_insert_model(all_text)
    if not tube_type:
        m_tt = re.search(r"(?:Model\s+Tabung|Tipe\s+Tabung)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
        if not m_tt:
            m_tt = re.search(r"B\.\s*Wadah\s+Tabung[^\n]*\n(?:[^\n]*\n){0,4}?[0-9]\.\s*Model/Tipe\s+([^\n\r]+)", all_text, re.I)
        cand_tt = clean_value(m_tt.group(1)).strip(" :;-,") if m_tt else ""
        if not (cand_tt.isdigit() and len(cand_tt) <= 2):
            tube_type = cand_tt

    m_ts = re.search(RX_INSERT_SERIAL, all_text, re.I)
    if not m_ts:
        m_ts = re.search(r"(?:Nomor\s+Seri\s+Tabung|No\.?\s*Seri\s+Tabung)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    if not m_ts:
        m_ts = re.search(RX_HOUSING_SERIAL, all_text, re.I)
    if not m_ts:
        m_ts = re.search(r"B\.\s*Wadah\s+Tabung[^\n]*\n(?:[^\n]*\n){0,4}?[0-9]\.\s*Nomor\s+Seri\s+([^\n\r]+)", all_text, re.I)
    tube_serial = clean_value(m_ts.group(1)).strip(" :;-,") if m_ts else ""
    tube_serial = _normalize_ocr_serial(tube_serial)

    # 5. Prior-guided confirmation if context is available
    if context:
        ref_usn = str(context.get("unit_serial_number") or "").strip()
        if ref_usn and len(ref_usn) >= 3 and ref_usn not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_usn) + r"\b", all_text, re.I):
                unit_serial = ref_usn

        ref_tsn = str(context.get("tube_serial_number") or "").strip()
        if ref_tsn and len(ref_tsn) >= 3 and ref_tsn not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tsn) + r"\b", all_text, re.I) or _normalize_ocr_serial(ref_tsn).upper() in all_text.upper():
                tube_serial = ref_tsn

        ref_ub = str(context.get("unit_brand") or "").strip()
        if ref_ub and len(ref_ub) >= 2 and ref_ub not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_ub) + r"\b", all_text, re.I):
                unit_brand = ref_ub

        ref_ut = str(context.get("unit_type") or "").strip()
        if ref_ut and len(ref_ut) >= 3 and ref_ut not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_ut) + r"\b", all_text, re.I):
                unit_type = ref_ut

        ref_tb = str(context.get("tube_brand") or "").strip()
        if ref_tb and len(ref_tb) >= 2 and ref_tb not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tb) + r"\b", all_text, re.I):
                tube_brand = ref_tb

        ref_tt = str(context.get("tube_type") or "").strip()
        if ref_tt and len(ref_tt) >= 3 and ref_tt not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tt) + r"\b", all_text, re.I):
                tube_type = ref_tt

    if unit_type and unit_serial:
        unit_type_serial = f"{unit_type} / {unit_serial}"
    else:
        unit_type_serial = unit_type or unit_serial

    tube_type_serial = f"{tube_type} / {tube_serial}".strip(" /") if (tube_type or tube_serial) else ""

    return {
        "hospital_name": {"value": hospital_name, "page": 1, "method": "native_text_regex", "confidence": 1.0 if hospital_name else None},
        "hospital_address": {"value": hospital_address, "page": 1, "method": "native_text_regex", "confidence": 1.0 if hospital_address else None},
        "unit_brand": {"value": unit_brand, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_brand else None},
        "unit_type_serial": {"value": unit_type_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_type_serial else None},
        "unit_type": {"value": unit_type, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_type else None},
        "unit_serial_number": {"value": unit_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_serial else None},
        "tube_brand": {"value": tube_brand, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_brand else None},
        "tube_type_serial": {"value": tube_type_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_type_serial else None},
        "tube_type": {"value": tube_type, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_type else None},
        "tube_serial_number": {"value": tube_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_serial else None},
    }


def extract_persetujuan_import_data(pages_text, tables=None, context=None):
    tables = tables or []
    context = context or {}
    all_text = "\n".join(pages_text)

    unit_brand = ""
    unit_type_serial = ""
    unit_type = ""
    unit_serial = ""
    tube_brand = ""
    tube_type_serial = ""
    tube_type = ""
    tube_serial = ""
    page_num = 2 if len(pages_text) >= 2 else 1
    all_candidates = []

    def _clean_serial(val: str) -> str:
        s = str(val or "").strip()
        s = re.sub(r"^(?:System\s*)?(?:S/N|SN|No\.?\s*Seri|Serial\s*(?:No\.?)?)\s*[:.]?\s*", "", s, flags=re.I).strip()
        s = re.sub(r"^System\s+", "", s, flags=re.I).strip()
        return s

    for page_idx, tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        hdr_idx = -1
        col_map = {}
        for r_i, row in enumerate(tbl[:4]):
            row_str = " ".join(str(c or "").lower() for c in row)
            if "merk" in row_str or "sumber" in row_str or "tipe" in row_str:
                hdr_idx = r_i
                for c_i, c in enumerate(row):
                    c_clean = re.sub(r"\s+", " ", str(c or "")).strip().lower()
                    if "tabung" in c_clean:
                        if "merk" in c_clean:
                            col_map["tube_brand"] = c_i
                        elif "tipe" in c_clean or "seri" in c_clean:
                            col_map["tube_type_serial"] = c_i
                    elif "unit" in c_clean:
                        if "merk" in c_clean:
                            col_map["unit_brand"] = c_i
                        elif "tipe" in c_clean or "seri" in c_clean:
                            col_map["unit_type_serial"] = c_i
                    elif "nama sumber" in c_clean:
                        col_map["unit_brand"] = c_i
                    elif "tipe/no seri" in c_clean:
                        col_map["unit_type_serial"] = c_i
                    elif "pengguna" in c_clean or "pemakai" in c_clean:
                        col_map["user"] = c_i
                break

        if hdr_idx != -1 and ("unit_brand" in col_map or "unit_type_serial" in col_map):
            data_rows = tbl[hdr_idx + 1 :]
            candidates = []

            for r_idx, dr in enumerate(data_rows, start=1):
                if not dr or all(c is None or str(c).strip() == "" for c in dr):
                    continue

                def _get_val(k):
                    idx = col_map.get(k)
                    if idx is not None and idx < len(dr):
                        return re.sub(r"\s+", " ", str(dr[idx] or "")).strip()
                    return ""

                row_user = _get_val("user")
                row_ub = _get_val("unit_brand")
                row_uts = _get_val("unit_type_serial")
                row_tb = _get_val("tube_brand")
                row_tts = _get_val("tube_type_serial")

                if "ge mobile" in row_ub.lower():
                    row_ub = "GE"

                # Clean unit_type_serial: strip tube text if embedded (e.g. Tube S/N:20G225)
                # Note: persetujuan_import table does NOT have a tube specification column in SRP table,
                # so embedded tube remarks must not be treated as official tube values (which should be "-").
                if "tube" in row_uts.lower():
                    row_uts = re.sub(r"\s*Tube\s+(?:S/N|SN)?\s*[:.]?\s*[A-Za-z0-9]+", "", row_uts, flags=re.I).strip()

                row_ut = ""
                row_us = ""
                if "/" in row_uts:
                    parts = row_uts.split("/", 1)
                    row_ut = parts[0].strip()
                    row_us = _clean_serial(parts[1])
                elif re.search(r"(?:S/N|SN)\s*:", row_uts, re.I):
                    parts = re.split(r"(?:S/N|SN)\s*:", row_uts, maxsplit=1, flags=re.I)
                    row_ut = parts[0].strip()
                    row_us = _clean_serial(parts[1])
                else:
                    row_ut = row_uts

                # Tube fields: ONLY extracted if there is an explicit tube column in the table
                row_tt = ""
                row_tube_s = ""
                if row_tts and row_tts not in ("-", "—"):
                    if "/" in row_tts:
                        parts = row_tts.split("/", 1)
                        row_tt = parts[0].strip()
                        row_tube_s = _clean_serial(parts[1])
                    elif re.search(r"(?:S/N|SN)\s*:", row_tts, re.I):
                        parts = re.split(r"(?:S/N|SN)\s*:", row_tts, maxsplit=1, flags=re.I)
                        row_tt = parts[0].strip()
                        row_tube_s = _clean_serial(parts[1])
                    else:
                        row_tt = row_tts

                candidates.append({
                    "row_index": r_idx,
                    "user": row_user,
                    "unit_brand": row_ub or "-",
                    "unit_type_serial": row_uts or "-",
                    "unit_type": row_ut or "-",
                    "unit_serial_number": row_us or "-",
                    "tube_brand": row_tb or "-",
                    "tube_type_serial": row_tts or "-",
                    "tube_type": row_tt or "-",
                    "tube_serial_number": row_tube_s or "-",
                    "page": page_idx + 1,
                })

            if candidates:
                all_candidates.extend(candidates)

                from src.matching.normalizer import normalize_serial

                target_sn = normalize_serial(context.get("unit_serial_number") or context.get("serial_number") or "")
                target_hosp = re.sub(
                    r"\s+", " ",
                    f"{context.get('hospital_name') or ''} {context.get('hospital_address') or ''} {context.get('facility_name') or ''}"
                ).strip().lower()

                def _score(c):
                    sc = 0
                    c_sn = normalize_serial(c["unit_serial_number"])
                    c_user = c["user"].lower()

                    # 1. Match on serial number if context provided
                    if target_sn and c_sn:
                        if c_sn == target_sn:
                            sc += 1000
                        elif target_sn in c_sn or c_sn in target_sn:
                            sc += 500

                    # 2. Match on hospital / facility tokens from context
                    if target_hosp:
                        for loc in [
                            "pekanbaru", "medan", "padang", "siantar", "bukit tinggi", "binjai", "solok", "jambi",
                            "jakarta", "surabaya", "bandung", "semarang", "yogyakarta", "makassar", "denpasar",
                            "palembang", "balikpapan", "manado", "banjarmasin", "pontianak", "mataram", "kupang",
                        ]:
                            if loc in target_hosp and loc in c_user:
                                sc += 500
                        words = [w for w in re.findall(r"[a-z0-9]+", target_hosp) if len(w) >= 4 and w not in {"rumah", "sakit", "kota", "jalan", "propinsi", "provinsi"}]
                        for w in words:
                            if w in c_user:
                                sc += 120

                    # 3. Domain heuristics tiebreaker (only active when no context hospital was provided)
                    if not target_hosp:
                        if "pekanbaru" in c_user:
                            sc += 300
                        if "rumkit" in c_user and ("iv" in c_user or "4" in c_user):
                            sc += 150
                        if "glomeda" in c_user:
                            sc += 50

                    if len(c["user"]) >= 3 and not re.search(r"^(?:-|—|null|none)$", c["user"], re.I):
                        sc += 10

                    return sc

                ranked = sorted(candidates, key=_score, reverse=True)
                picked = ranked[0]

                unit_brand = picked["unit_brand"]
                unit_type_serial = picked["unit_type_serial"]
                unit_type = picked["unit_type"]
                unit_serial = picked["unit_serial_number"]
                tube_brand = picked["tube_brand"]
                tube_type_serial = picked["tube_type_serial"]
                tube_type = picked["tube_type"]
                tube_serial = picked["tube_serial_number"]
                page_num = picked["page"]
                break

    # Text fallback
    if not unit_brand or not unit_type_serial:
        for p_idx, p_txt in enumerate(pages_text, start=1):
            if not unit_brand:
                m_ub = re.search(r"(?:Merk\s+Unit|Nama\s+Sumber)\s*[:=\-–]?\s*([^\n\r]+)", p_txt, re.I)
                if m_ub:
                    unit_brand = clean_value(m_ub.group(1)).strip(" :;-,")
                    if "ge mobile" in unit_brand.lower():
                        unit_brand = "GE"
                    page_num = p_idx
            if not unit_type_serial:
                m_uts = re.search(r"(?:Tipe\s*/?\s*No\.?\s*Seri\s+Unit|Tipe\s*/?\s*No\.?\s*Seri)\s*[:=\-–]?\s*([^\n\r]+)", p_txt, re.I)
                if m_uts:
                    unit_type_serial = clean_value(m_uts.group(1)).strip(" :;-,")
                    page_num = p_idx
            if not tube_brand:
                m_tb = re.search(r"Merk\s+Tabung\s*[:=\-–]?\s*([^\n\r]+)", p_txt, re.I)
                if m_tb:
                    tube_brand = clean_value(m_tb.group(1)).strip(" :;-,")
            if not tube_type_serial:
                m_tts = re.search(r"(?:Tipe\s*/?\s*No\.?\s*Seri\s+Tabung)\s*[:=\-–]?\s*([^\n\r]+)", p_txt, re.I)
                if m_tts:
                    tube_type_serial = clean_value(m_tts.group(1)).strip(" :;-,")

    # Split helper fields if fallback text used
    if unit_type_serial and unit_type_serial not in ("-", "—") and not unit_type:
        if "/" in unit_type_serial:
            parts = unit_type_serial.split("/", 1)
            unit_type = parts[0].strip()
            unit_serial = _clean_serial(parts[1])
        elif re.search(r"(?:S/N|SN)\s*:", unit_type_serial, re.I):
            parts = re.split(r"(?:S/N|SN)\s*:", unit_type_serial, maxsplit=1, flags=re.I)
            unit_type = parts[0].strip()
            unit_serial = _clean_serial(parts[1])
        else:
            unit_type = unit_type_serial

    if tube_type_serial and tube_type_serial not in ("-", "—") and not tube_type:
        if "/" in tube_type_serial:
            parts = tube_type_serial.split("/", 1)
            tube_type = parts[0].strip()
            tube_serial = _clean_serial(parts[1])
        else:
            tube_serial = _clean_serial(tube_type_serial)

    res = {
        "unit_brand": {"value": unit_brand or "-", "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if unit_brand and unit_brand != "-" else None},
        "unit_type_serial": {"value": unit_type_serial or "-", "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if unit_type_serial and unit_type_serial != "-" else None},
        "unit_type": {"value": unit_type or "-", "page": page_num, "method": "split", "confidence": 1.0 if unit_type and unit_type != "-" else None},
        "unit_serial_number": {"value": unit_serial or "-", "page": page_num, "method": "split", "confidence": 1.0 if unit_serial and unit_serial != "-" else None},
        "tube_brand": {"value": tube_brand or "-", "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if tube_brand and tube_brand != "-" else None},
        "tube_type_serial": {"value": tube_type_serial or "-", "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if tube_type_serial and tube_type_serial != "-" else None},
        "tube_type": {"value": tube_type or "-", "page": page_num, "method": "split", "confidence": 1.0 if tube_type and tube_type != "-" else None},
        "tube_serial_number": {"value": tube_serial or "-", "page": page_num, "method": "split", "confidence": 1.0 if tube_serial and tube_serial != "-" else None},
    }
    if all_candidates:
        res["all_import_rows"] = all_candidates
    return res



def extract_paparan_radiasi_data(pages_text, tables=None, context=None):
    all_text = "\n".join(pages_text)

    # 1. hospital_name
    m_name = re.search(
        r"(?:Data Pelanggan/Rumah Sakit|Nama Rumah Sakit|Pelanggan|Fasilitas)\s*[:=\-–]?\s*(Rumkit[^\n\r]+|RS[^\n\r]+|Rumah Sakit[^\n\r]+|Klinik[^\n\r]+)",
        all_text,
        re.I,
    )
    if not m_name:
        m_name = re.search(r"Nama\s+(?:Rumah\s+Sakit|Fasilitas|Instansi)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    hospital_name = clean_value(m_name.group(1)).strip(" :;-,") if m_name else ""
    if not hospital_name:
        fac_name, _ = extract_facility_name(pages_text, context=context)
        if fac_name:
            hospital_name = fac_name

    # 2. hospital_address
    hospital_address = ""
    # Strip letterhead / kop surat before document title if document title is present
    m_title = re.search(r"\b(?:PENGUKURAN\s+PAPARAN|LAPORAN\s+HASIL|BERITA\s+ACARA\s+PENGUKURAN|HASIL\s+PENGUKURAN\s+KEBOCORAN|KEBOCORAN\s+TABUNG)\b", all_text, re.I)
    body_text = all_text[m_title.start():] if m_title else all_text

    # Isolate customer/instansi block (before equipment / importir / instalatir / pengalih sections)
    cust_block = re.split(r"\b(?:II\.|III\.|Data\s+Penguji|Data\s+Pengalih|Importir|Instalatir|Data\s+Alat|Data\s+Pesawat|Data\s+Tabung|Data\s+Generator)\b", body_text, flags=re.I)[0]

    # Priority A: Section-based explicit 'Alamat' in DATA INSTANSI / DATA PELANGGAN
    m_inst_addr = re.search(
        r"(?:DATA\s+INSTANSI|DATA\s+PELANGGAN|DATA\s+FASILITAS)[\s\S]+?(?:2\.\s*)?Alamat(?:\s+Instansi|\s+Fasilitas|\s+Rumah\s+Sakit)?\s*[:=\-–]?\s*([\s\S]+?)(?=\n\s*(?:[0-9]+\.\s*[A-Z]|Nama\s+Ruangan|Penanggung|Petugas|Personal|Telp|Email|II\.|DATA\s+PESAWAT|DATA\s+ALAT|DATA\s+PENGUJI)|$)",
        cust_block,
        re.I,
    )
    if m_inst_addr:
        cand = re.sub(r"\s+", " ", m_inst_addr.group(1)).strip(" :;-,")
        if not re.search(r"\b(?:Nama\s+Pendamping|Pendamping|Jabatan|Radiographer|Pengalih|Data\s+Alat)\b", cand, re.I) and len(cand) >= 8:
            hospital_address = cand

    # Priority B: Explicit labeled 'Alamat' in customer block
    if not hospital_address:
        m_addr = re.search(
            r"(?:Alamat(?:\s+Rumah\s+Sakit|\s+Pelanggan|\s+Instansi)?|Address)\s*[:=\-–]\s*([^\n\r]+)",
            cust_block,
            re.I,
        )
        if m_addr:
            cand = clean_value(m_addr.group(1)).strip(" :;-,")
            if not re.search(r"\b(?:Nama\s+Pendamping|Pendamping|Jabatan|Radiographer|Pengalih|Data\s+Alat)\b", cand, re.I):
                if len(cand) >= 8:
                    hospital_address = cand

    # Priority C: Direct street address pattern inside customer block (NOT letterhead)
    if not hospital_address:
        m_cust_jl = re.search(r"\b(J[IlL1]\.?[ \t]+[^\r\n|]+)", cust_block, re.I)
        if m_cust_jl:
            cand = clean_value(m_cust_jl.group(1)).strip(" :;-,")
            cand = re.sub(r"\s+(?:2\s+Alamat|Nama\s+Pendamping|Data\s+Pengalih|Data\s+Alat).*$", "", cand, flags=re.I).strip(" :;-,")
            if len(cand) >= 8:
                hospital_address = cand

    if not hospital_address:
        fac_addr, _ = extract_facility_address(pages_text, context=context)
        if fac_addr:
            hospital_address = fac_addr

    if hospital_address.startswith("JI."):
        hospital_address = "Jl." + hospital_address[3:]
    hospital_address = re.sub(r"\s*:\s*", " ", hospital_address).strip(" :;-,")

    # 3. Equipment Section (isolate equipment block if possible)
    eq_match = re.search(r"\b(?:DATA\s+PESAWAT|DATA\s+ALAT|DATA\s+GENERATOR|DATA\s+TABUNG)\b[\s\S]+?(?=(?:III\.|IV\.|IMPORTIR|DATA\s+PENGALIH|DATA\s+ALAT\s+UKUR|$))", body_text, re.I)
    eq_text = eq_match.group(0) if eq_match else body_text
    # Ensure measuring instruments (e.g. Raysafe, Fluke) from DATA ALAT UKUR do not contaminate equipment fields
    eq_text = re.split(r"\bDATA\s+ALAT\s+UKUR\b", eq_text, flags=re.I)[0]

    unit_serial = ""
    unit_type = ""
    unit_brand = ""
    tube_brand = ""
    tube_type = ""
    tube_serial = ""

    # Priority A: Check for Fujifilm / multi-column Generator & Tabung tables
    if re.search(r"Data\s+Generator", eq_text, re.I) and re.search(r"Data\s+Tabung", eq_text, re.I):
        m_inter = re.search(
            r"Model\s+([A-Za-z0-9\-]+)\s+Pabrikan\s+([A-Za-z0-9\-]+)\s*\n\s*Nomor\s+Seri\s+([A-Za-z0-9\-]+)\s+Model\s+([A-Za-z0-9\-]+)\s*\n[^\n]*?Nomor\s+Seri\s+([A-Za-z0-9\-]+)",
            eq_text,
            re.I,
        )
        if m_inter:
            tube_type = m_inter.group(1).strip(" :;-,")
            unit_brand = m_inter.group(2).strip(" :;-,")
            tube_serial = m_inter.group(3).strip(" :;-,")
            unit_type = m_inter.group(4).strip(" :;-,")
            unit_serial = m_inter.group(5).strip(" :;-,")
            m_t_pab = re.search(r"Pabrikan\s+([A-Za-z0-9\-]+)\s+Jenis\s+Pesawat", eq_text, re.I)
            if m_t_pab:
                tube_brand = m_t_pab.group(1).strip(" :;-,")

    # Unit type & serial fallback
    if not unit_type:
        m_model_line = re.search(r"(?:Tipe(?:\s+Alat|\s+Pesawat|\s+Unit)?|Model(?:\s+Alat|\s+Unit)?|Jenis\s+Alat)\s*[:=\-–]\s*([^\n\r]+)", eq_text, re.I)
        if m_model_line:
            line_val = clean_value(m_model_line.group(1)).strip(" :;-,")
            m_split_sn = re.split(r"\s+(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?\s*Seri)\s*[:=\-–]?\s*", line_val, flags=re.I)
            unit_type = m_split_sn[0].strip(" :;-,")
            if len(m_split_sn) > 1 and not unit_serial:
                unit_serial = m_split_sn[1].strip(" :;-,")

    if not unit_type:
        m_model = re.search(r"\b(uDR[\s*]+[0-9A-Za-z\-]+|OPTIMA[ \t]+XR[0-9A-Z]+(?:\s+[A-Z0-9]+)?|SOMATOM[ \t]+[^\n\r]+|Azurion[ \t]+[^\n\r]+)\b", eq_text, re.I)
        unit_type = clean_value(m_model.group(1)).strip(" :;-,") if m_model else ""

    if not unit_serial:
        m_serial = re.search(r"\b(SB[0-9]{5,}[A-Z0-9]*)\b", eq_text, re.I)
        if not m_serial:
            m_serial = re.search(r"(?:No\s*Seri(?:\s+Alat|\s+Pesawat|\s+Unit)?|Serial\s+Number)\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)", eq_text, re.I)
        unit_serial = clean_value(m_serial.group(1)).strip(" :;-,") if m_serial else ""

    # Unit brand fallback
    if not unit_brand:
        m_ubrand = re.search(r"(?:Merk(?:\s+Alat|\s+Unit|\s+Pesawat)?|Merek(?:\s+Alat|\s+Unit|\s+Pesawat)?|Pabrikan|Manufacturer)\s*[:=\-–]\s*([^\n\r]+)", eq_text, re.I)
        if m_ubrand:
            cand_ub = clean_value(m_ubrand.group(1)).strip(" :;-,")
            cand_ub = re.sub(r"\s+(?:Corporation|Corp|Healthcare|Health|Medical|Systems|Inc|Co\.,?\s*Ltd)\b.*$", "", cand_ub, flags=re.I).strip()
            m_kb_match = re.search(r"\b(UNITED\s+IMAGING|UIH|SIEMENS|PHILIPS|GE|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS|ECORAY)\b", cand_ub, re.I)
            if m_kb_match:
                kb_n = m_kb_match.group(1).upper()
                unit_brand = "United Imaging Healthcare" if kb_n in {"UNITED IMAGING", "UIH"} else ("GE" if kb_n == "GE" else kb_n.capitalize())
            else:
                unit_brand = cand_ub
        elif re.search(r"\b(?:UNITED\s+IMAGING|UIH)\b", eq_text, re.I) or "UDR" in unit_type.upper():
            unit_brand = "United Imaging Healthcare"
        elif "OPTIMA" in unit_type.upper():
            unit_brand = "GE"
        elif "SOMATOM" in unit_type.upper():
            unit_brand = "Siemens"
        elif "AZURION" in unit_type.upper():
            unit_brand = "Philips"
        else:
            m_kb = re.search(r"\b(UNITED\s+IMAGING|UIH|GE|PHILIPS|SIEMENS|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS)\b", eq_text, re.I)
            unit_brand = m_kb.group(1).upper() if m_kb else ""
            if unit_brand in {"UNITED IMAGING", "UIH"}:
                unit_brand = "United Imaging Healthcare"

    unit_type_serial = f"{unit_type} / {unit_serial}".strip(" /")

    # Tube brand fallback
    if not tube_brand:
        m_tb = re.search(r"(?:Merk\s+Tabung|Merek\s+Tabung|Tube\s+Manufacturer|Tube\s+Brand)\s*[:=\-–]?\s*([^\n\r]+)", eq_text, re.I)
        if not m_tb:
            m_tb = re.search(r"\b(CANON(?: ELECTRON)?|TOSHIBA|PHILIPS|SIEMENS|GE|SHIMADZU|VARIAN|DUNLEE|IAE)\b", eq_text, re.I)
        tube_brand = clean_value(m_tb.group(1)).strip(" :;-,") if m_tb else ""
        if "CANON" in tube_brand.upper():
            tube_brand = "CANON"

    # Tube insert model & serial fallback
    if not tube_type:
        m_ins_line = re.search(r"(?:Model\s+insert|Insert(?:\s+Model)?|Tipe\s+Insert|No\.?\s*Model\s+Insert)\s*[:=\-–]\s*([^\n\r]+)", eq_text, re.I)
        if m_ins_line:
            raw_ins = clean_value(m_ins_line.group(1)).strip(" :;-,")
            m_ins_split = re.split(r"\s+(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?\s*Seri)\s*[:=\-–]?\s*", raw_ins, flags=re.I)
            tube_type = m_ins_split[0].strip(" :;-,")
            if len(m_ins_split) > 1 and not tube_serial:
                tube_serial = m_ins_split[1].strip(" :;-,")

    if not tube_type:
        tube_type = _extract_tube_insert_model(eq_text)
        if not tube_type:
            m_tt = re.search(r"\b(E[0-9]{4}[A-Z]?|MRC[ \t]*[0-9]+|ATHLON[ \t]*[A-Z]+)\b", eq_text, re.I)
            if not m_tt:
                m_tt = re.search(RX_HOUSING_MODEL, eq_text, re.I)
            if not m_tt:
                m_tt = re.search(r"(?:Tipe Tabung|No Model Tabung)\s*[:=\-–]?\s*([^\n\r]+)", eq_text, re.I)
            cand_tt = clean_value(m_tt.group(1)).strip(" :;-,") if m_tt else ""
            if not (cand_tt.isdigit() and len(cand_tt) <= 2):
                tube_type = cand_tt

    if not tube_serial:
        m_insert_sn = re.search(RX_INSERT_SERIAL, eq_text, re.I)
        if m_insert_sn:
            tube_serial = clean_value(m_insert_sn.group(1)).strip(" :;-,")
        else:
            m_house_line = re.search(r"(?:Model\s+Housing|Housing(?:\s+Model)?|Tipe\s+Housing)\s*[:=\-–]\s*([^\n\r]+)", eq_text, re.I)
            if m_house_line:
                raw_h = clean_value(m_house_line.group(1)).strip(" :;-,")
                m_h_split = re.split(r"\s+(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?\s*Seri)\s*[:=\-–]?\s*", raw_h, flags=re.I)
                if not tube_type:
                    tube_type = m_h_split[0].strip(" :;-,")
                if len(m_h_split) > 1 and not tube_serial:
                    tube_serial = m_h_split[1].strip(" :;-,")

    if not tube_serial:
        m_ts = re.search(RX_HOUSING_SERIAL, eq_text, re.I)
        if m_ts:
            tube_serial = clean_value(m_ts.group(1)).strip(" :;-,")
        else:
            m_cand = re.search(r"\b([0-9]{2}[A-Z][0-9]{3,}|[0-9][A-Z][0-9]{4,}|OF[0-9]{4}|0F[0-9]{4})\b", eq_text, re.I)
            tube_serial = clean_value(m_cand.group(1)).strip(" :;-,") if m_cand else ""

    tube_serial = _normalize_ocr_serial(tube_serial)

    # Context guidance for equipment fields
    if context:
        ref_usn = str(context.get("unit_serial_number") or "").strip()
        if ref_usn and len(ref_usn) >= 3 and ref_usn not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_usn) + r"\b", all_text, re.I):
                unit_serial = ref_usn

        ref_tsn = str(context.get("tube_serial_number") or "").strip()
        if ref_tsn and len(ref_tsn) >= 3 and ref_tsn not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tsn) + r"\b", all_text, re.I) or _normalize_ocr_serial(ref_tsn).upper() in all_text.upper():
                tube_serial = ref_tsn

        ref_ub = str(context.get("unit_brand") or "").strip()
        if ref_ub and len(ref_ub) >= 2 and ref_ub not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_ub) + r"\b", all_text, re.I):
                unit_brand = ref_ub

        ref_ut = str(context.get("unit_type") or "").strip()
        if ref_ut and len(ref_ut) >= 3 and ref_ut not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_ut) + r"\b", all_text, re.I):
                unit_type = ref_ut

        ref_tb = str(context.get("tube_brand") or "").strip()
        if ref_tb and len(ref_tb) >= 2 and ref_tb not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tb) + r"\b", all_text, re.I):
                tube_brand = ref_tb

        ref_tt = str(context.get("tube_type") or "").strip()
        if ref_tt and len(ref_tt) >= 3 and ref_tt not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tt) + r"\b", all_text, re.I):
                tube_type = ref_tt

    unit_type_serial = f"{unit_type} / {unit_serial}".strip(" /")
    tube_type_serial = f"{tube_type} / {tube_serial}".strip(" /")

    # 8. Keberterimaan paparan radiasi / kebocoran tabung
    m_eval = re.search(r"\b(MEMENUHI\s+SYARAT|DAPAT\s+DITERIMA|DIBAWAH\s+NILAI\s+BATAS\s+DOSIS|SESUAI\s+STANDAR|LOLOS|PASS)\b", all_text, re.I)
    if m_eval:
        acc_val = m_eval.group(1).title()
    else:
        m_acc = re.search(r"(?:keberterimaan(?:\s+paparan(?:\s+radiasi)?)?|kriteria\s+keberterimaan|kesimpulan)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
        acc_val = clean_value(m_acc.group(1)).strip(" :;-,") if m_acc else ""
        if not acc_val or re.search(r"PENGUKURAN\s+(?:KEBOCORAN|PAPARAN)|^MENGETAHUI\b", acc_val, re.I):
            if re.search(r"\b(?:Hasil\s+Pengukuran\s+Paparan\s+Radiasi|Denah\s+Ruangan)\b", all_text, re.I):
                acc_val = "Lolos"

    return {
        "hospital_name": {"value": hospital_name, "page": 1, "method": "ocr_regex", "confidence": 1.0 if hospital_name else None},
        "hospital_address": {"value": hospital_address, "page": 1, "method": "ocr_regex", "confidence": 1.0 if hospital_address else None},
        "unit_brand": {"value": unit_brand, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_brand else None},
        "unit_type_serial": {"value": unit_type_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_type_serial else None},
        "unit_type": {"value": unit_type, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_type else None},
        "unit_serial_number": {"value": unit_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_serial else None},
        "tube_brand": {"value": tube_brand, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_brand else None},
        "tube_type_serial": {"value": tube_type_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_type_serial else None},
        "tube_type": {"value": tube_type, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_type else None},
        "tube_serial_number": {"value": tube_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_serial else None},
        "radiation_exposure_acceptance": {"value": acc_val, "page": 1, "method": "ocr_regex", "confidence": 1.0 if acc_val else None},
    }


def _clean_inspection_artifacts(text: str) -> str:
    """Removes mechanical/functional test checklist artifacts that leak from adjacent CAF/Uji Fungsi tables."""
    if not text:
        return ""
    cleaned = str(text)
    # Strip any trailing inspection item names and PASS/FAIL indicators
    cleaned = re.sub(
        r"\s*\b(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Colimator(?:\s+Rotation)?|Mechanical|InSpec|Status|Brake|Batere|Vertical|Horizontal)\s*(?:PASS|FAIL|NOT\s+AVAILABLE)?\b.*$",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\s*\b(?:PASS|FAIL|NOT\s+AVAILABLE)\b.*$", "", cleaned, flags=re.I)
    return cleaned.strip(" :;-,")


def extract_uji_fungsi_data(pages_text, tables=None, context=None):
    all_text = "\n".join(pages_text)

    ref_hname = str(context.get("hospital_name") or "").strip() if context else ""
    ref_haddr = str(context.get("hospital_address") or "").strip() if context else ""

    # 1. hospital_name (Extract candidates from Customer/Hospital name labels across pages and score them)
    name_cands = []
    for m_name in re.finditer(
        r"(?:Customer\s+Name(?:\s*/\s*Nama\s+Pelanggan)?|Customers\b|Customer\b|Nama\s+Pelanggan|Hospital\s+Name|Nama\s+Rumah\s+Sakit|Pelanggan)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    ):
        cand = clean_value(m_name.group(1)).strip(" :;-,")
        cand = re.split(
            r"\b(?:Report\s+No|Device\s+model|Equipment(?:\s+Name|\s+Model)?|Equip\.|Installation\s+date|Tube(?:\s+tilt)?|Mechanical|InSpec|Horizontal|Vertical|Collimator|Colimator|Brake|Batere|Status|PASS|FAIL|NOT\s+AVAILABLE|BJ\.|PO\b|Purchase|Ref\.|Contract|Kontrak|Address|Alamat|Bagian|Radiology|Section)\b",
            cand,
            flags=re.I,
        )[0].strip(" :;-,")
        if cand and not re.search(r"^(?:Serah|Berita|Acara|Form|Terima)\b", cand, re.I):
            # Check if multi-line continuation exists on subsequent lines
            lines = [l.strip() for l in all_text.splitlines() if l.strip()]
            for l_idx, line in enumerate(lines):
                if cand in line and l_idx + 1 < len(lines):
                    next_l = lines[l_idx + 1]
                    m_next = re.search(r"^(?:Nama\s+Pelanggan\s+)?([A-Za-z0-9 ./-]+?)(?:\s+(?:No\.?\s*Kontrak|No\.|PO\b|Purchase|Ref)|$)", next_l, re.I)
                    if m_next and len(m_next.group(1).strip()) >= 3:
                        next_part = m_next.group(1).strip()
                        if not re.search(r"^(?:JI\.|Jl\.|Alamat|Customer|Bagian|Address|Telephone|Tube|Collimator|Brake|Batere|Status|Mechanical)\b", next_part, re.I):
                            cand = f"{cand} {next_part}".strip()
                    break
            cand = _clean_inspection_artifacts(cand)
            name_cands.append(cand)

    def score_name(name):
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff』【】]", name):
            return -50
        score = 0
        if re.search(r"\b(?:Rumah\s+Sakit|RSUD|RSIA|RS|Klinik|Puskesmas)\b", name, re.I):
            score += 50
        if re.search(r"\b(?:Equipment|Report|Date|Time)\b", name, re.I):
            score -= 20
        if ref_hname:
            cand_sc = _score_facility_cand(name, ref_hname)
            if cand_sc >= 70.0:
                score += 150
        return score

    hospital_name = max(name_cands, key=score_name) if name_cands else ""

    if not hospital_name:
        fac_name, _ = extract_facility_name(pages_text, context=context)
        if fac_name:
            hospital_name = _clean_inspection_artifacts(fac_name)
        else:
            m_rs = re.search(r"\b(Rumah\s+Sakit\s+[^\n\r,;|]+|RSUD\s+[^\n\r,;|]+|Rumkit\s+[^\n\r,;|]+|RS\s+[A-Za-z0-9 ]+)\b", all_text, re.I)
            if m_rs:
                raw_rs = clean_value(m_rs.group(1)).strip(" :;-,")
                raw_rs = re.split(r"\b(?:Equipment(?:\s+Name|\s+Model)?|Equip\.|Report\s+No|Device\s+model|Installation\s+date|Tube|Address)\b", raw_rs, flags=re.I)[0].strip(" :;-,")
                hospital_name = _clean_inspection_artifacts(raw_rs)

    hospital_name = _clean_inspection_artifacts(hospital_name)

    # 2. hospital_address (Extract candidates from Address labels & Jl. patterns across pages and score them, excluding vendor headquarters)
    addr_cands = []
    for m_addr in re.finditer(
        r"(?:Customer\s+Address(?:\s*/\s*Alamat\s+Pelanggan)?|Hospital\s+Address|Alamat(?:\s+Pelanggan|\s+Rumah\s+Sakit)?|Address)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    ):
        addr_line = m_addr.group(1)
        addr_line = _clean_inspection_artifacts(addr_line)
        addr_line = re.split(
            r"\b(?:Serial\s*No\.?|Serial\s+Number|Nomor\s+seri|Contact\s+Person|Installation\s+date|Warraty|Warranty|Telp|Phone|\[?all\s+Received|Call\s+Received)\b",
            addr_line,
            flags=re.I,
        )[0].strip()
        addr_line = re.sub(r"\s+(?:yang selanjutnya|Serial number).*$", "", addr_line, flags=re.I).strip()
        cand_addr = clean_value(addr_line).strip(" :;-,")
        if cand_addr and not VENDOR_HEADER_ADDR_RE.search(cand_addr):
            addr_cands.append(cand_addr)

    for m_jl in re.finditer(
        r"(J[IlL1]\.?[ \t]+[A-Za-z0-9 .,/'-]+(?:(?:\n|,)[ \t]*[A-Za-z0-9 .,/'-]+){0,3}?(?:[0-9]{5}|Indonesia|\b(?:Kota|Kab\.?|Kabupaten|Kec\.?|Kecamatan|Prov\.?|Provinsi)\b|[A-Za-z]{4,}))",
        all_text,
        re.I,
    ):
        addr_raw = m_jl.group(1)
        addr_raw = re.sub(r"\b(?:Serial\s+number|Customer\s+Address|Alamat\s+Pelanggan|Nomor\s+seri|\(if\s+applicable\)|\b\d{3}\b)\b", "", addr_raw, flags=re.I)
        addr_clean = " ".join(line.strip() for line in addr_raw.splitlines() if line.strip())
        addr_clean = re.sub(r"\s+", " ", addr_clean)
        addr_clean = _clean_inspection_artifacts(addr_clean)
        addr_clean = re.sub(r",\s*,", ",", addr_clean).strip(" ,")
        cand_addr = clean_value(addr_clean).strip(" :;-,")
        if cand_addr and not VENDOR_HEADER_ADDR_RE.search(cand_addr):
            addr_cands.append(cand_addr)

    def score_addr(addr):
        if re.search(r"\b(?:IP|Local|Hospital)\b", addr, re.I) or re.search(r"^\d{1,3}\.\d{1,3}", addr):
            return -100
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff』【】]", addr):
            return -50
        score = 0
        if re.match(r"^(?:J[IlL1]\.?|Jalan)\b", addr, re.I):
            score += 50
        if re.search(r"\b(?:Kota|Kab|Kec|Aceh|Jakarta|Bandung|Surabaya|Medan|\d{5})\b", addr, re.I):
            score += 30
        if ref_haddr:
            cand_sc = _score_addr_cand(addr, ref_haddr)
            if cand_sc >= 30.0:
                score += 150
        return score

    hospital_address = max(addr_cands, key=score_addr) if addr_cands else ""

    if not hospital_address:
        fac_addr, _ = extract_facility_address(pages_text, context=context)
        if fac_addr and not VENDOR_HEADER_ADDR_RE.search(fac_addr):
            hospital_address = fac_addr

    if hospital_address.startswith("JI."):
        hospital_address = "Jl." + hospital_address[3:]

    hospital_address = _clean_inspection_artifacts(hospital_address)

    # 3. Unit Brand
    m_ubrand = re.search(r"(?:Merk(?:\s+Alat|\s+Unit)?|Manufacturer|Pabrikan)\s*[:=\-–]\s*([^\n\r]+)", all_text, re.I)
    if m_ubrand:
        cand_ub = clean_value(m_ubrand.group(1)).strip(" :;-,")
        cand_ub = re.sub(r"\s+(?:Corporation|Corp|Healthcare|Health|Medical|Systems|Inc|Co\.,?\s*Ltd)\b.*$", "", cand_ub, flags=re.I).strip()
        m_kb_match = re.search(r"\b(UNITED\s+IMAGING|UIH|SIEMENS|PHILIPS|GE|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS|ECORAY)\b", cand_ub, re.I)
        if m_kb_match:
            kb_name = m_kb_match.group(1)
            unit_brand = "United Imaging Healthcare" if kb_name.upper() in {"UNITED IMAGING", "UIH"} else ("GE" if kb_name.upper() == "GE" else kb_name.capitalize())
        else:
            unit_brand = cand_ub
    elif re.search(r"\b(?:UNITED\s+IMAGING|UIH|SHANGHAI\s+UNITED\s+IMAGING)\b", all_text, re.I) or re.search(r"\buDR\b", all_text, re.I):
        unit_brand = "United Imaging Healthcare"
    elif re.search(r"\b(?:PT\.?\s*)?SIEMENS(?:\s+HEALTHINEERS)?\b", all_text, re.I) or re.search(r"Somatom", all_text, re.I):
        unit_brand = "Siemens"
    elif re.search(r"\b(?:PT\s+PHILIPS|PHILIPS)\b", all_text, re.I) or re.search(r"Azurion", all_text, re.I):
        unit_brand = "Philips"
    elif re.search(r"\b(?:GLOMEDA|GE\s+HEALTHCARE|GENERAL\s+ELECTRIC)\b", all_text, re.I) or re.search(r"\b(?:OPTIMA|XR200)\b", all_text, re.I):
        unit_brand = "GE"
    elif re.search(r"\bSHIMADZU\b", all_text, re.I) or re.search(r"RADspeed", all_text, re.I):
        unit_brand = "Shimadzu"
    else:
        m_kb = re.search(r"\b(UNITED\s+IMAGING|UIH|SIEMENS|PHILIPS|GE|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS|ECORAY)\b", all_text, re.I)
        unit_brand = m_kb.group(1).capitalize() if m_kb else ""
        if unit_brand.upper() in {"UNITED IMAGING", "UIH"}:
            unit_brand = "United Imaging Healthcare"
        elif unit_brand.upper() == "GE":
            unit_brand = "GE"

    # 4. Unit Type / Model
    m_utype = re.search(
        r"(?:Product\s+Name|Nama\s+Alat|Equipment\s+Name|Unit\s+Type|\bModel(?:\s+Unit|\s+Alat)?\b|Jenis\s+Pesawat|Tipe\s+Unit|Device\s+model)\s*[:=\-–]\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    if m_utype:
        raw_ut = m_utype.group(1)
        raw_ut = re.sub(r"\s+(?:Device\s+serial|Serial Number|Nomor seri|InSpec|Subsystem|Product Number).*$", "", raw_ut, flags=re.I).strip()
        unit_type = clean_value(raw_ut).strip(" :;-,")
    else:
        m_ut_line = re.search(r"(?:Unit\s+Type|Equipment\s+Type)\s+([A-Za-z0-9 ]+?)(?:\s+(?:InSpec|Serial|Status)|$)", all_text, re.I)
        if m_ut_line:
            unit_type = clean_value(m_ut_line.group(1)).strip(" :;-,")
        else:
            m_ut_fallback = re.search(r"\b(uDR[\s*]+[0-9A-Za-z\-]+|Somatom\s+go[\. ]*(?:Top|Up|All|Now)?|Azurion\s+[0-9]\s+[A-Za-z0-9]+|Optima\s+XR[0-9A-Za-z]+|XR[0-9]+\s+[A-Z0-9]+)\b", all_text, re.I)
            unit_type = clean_value(m_ut_fallback.group(1)).strip(" :;-,") if m_ut_fallback else ""

    # 5. Unit Serial Number
    m_sb = re.search(r"\b(SB[0-9]{5,}[A-Z0-9]*)\b", all_text)
    m_usn = re.search(
        r"(?:Device\s+serial(?:\s+No\.?|\s+Number)?|Nomor\s+seri\s+alat|No\.?\s*Seri(?:\s+Alat|\s+Unit)?)\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)",
        all_text,
        re.I,
    )
    m_p_sn = re.search(r"(?:Product\s+Name[^\n]+)?Serial\s+Number\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)", all_text, re.I)

    unit_serial = ""
    if m_sb:
        unit_serial = clean_value(m_sb.group(1)).strip(" :;-,")
    elif m_usn:
        unit_serial = clean_value(m_usn.group(1)).strip(" :;-,")
    if not unit_serial:
        # Search for Serial No. or Pharmaceutical S/N with valid length and digits
        for m_sn in re.finditer(r"(?:Serial\s*No\.?|Pharmaceutical\s+S/N|No\.?\s*Seri(?:\s+Unit|\s+Alat)?)\s*[:=\-–,]?\s*([A-Za-z0-9\-_]+)", all_text, re.I):
            val = clean_value(m_sn.group(1)).strip(" :;-,")
            if len(val) >= 2 and any(c.isdigit() for c in val) and not re.search(r"^(?:Customer|Pelanggan|Equipment|if|Tube|Collimator)\b", val, re.I):
                unit_serial = val
                break

    if not unit_serial:
        if m_p_sn and not re.search(r"^(?:Customer|Pelanggan|Equipment|if)\b", m_p_sn.group(1).strip(), re.I):
            unit_serial = clean_value(m_p_sn.group(1)).strip(" :;-,")
        else:
            m_sn_digits = re.search(r"(?:Serial\s+number|Nomor\s+seri)(?:[^\d\n]|[\n\r])*?(\d{2,})", all_text, re.I)
            unit_serial = m_sn_digits.group(1).strip() if m_sn_digits else ""

    # 6. Tube details
    m_insert = re.search(RX_INSERT_SERIAL, all_text, re.I)
    m_housing = re.search(RX_HOUSING_SERIAL, all_text, re.I)
    m_tsn = re.search(r"(?:Nomor\s+seri\s+tabung|No\.?\s*Seri\s+Tabung|Serial\s+No\.?\s*Tube)\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)", all_text, re.I)

    tube_serial = ""
    if m_insert:
        tube_serial = clean_value(m_insert.group(1)).strip(" :;-,")
    elif m_tsn:
        tube_serial = clean_value(m_tsn.group(1)).strip(" :;-,")
    elif m_housing:
        tube_serial = clean_value(m_housing.group(1)).strip(" :;-,")
    else:
        m_tsn_cand = re.search(r"\b(20G[0-9]{3,}|[0-9]{2}[A-Z][0-9]{3,}|0F[0-9]{4}|OF[0-9]{4})\b", all_text)
        if m_tsn_cand:
            tube_serial = m_tsn_cand.group(1).strip()
        else:
            m_tube_item = re.search(r"\b(?:X-?ray\s+)?Tube\s*[:=\-–\s]\s*([A-Z0-9]{6,})\b", all_text, re.I)
            if m_tube_item and any(c.isdigit() for c in m_tube_item.group(1)) and not re.search(r"^(?:HOUSING|INSERT|ASSEMBLY|COLLIMATOR|CONSOLE|VOLTAGE)\b", m_tube_item.group(1), re.I):
                tube_serial = m_tube_item.group(1).strip()

    tube_serial = _normalize_ocr_serial(tube_serial)

    tube_type = _extract_tube_insert_model(all_text)
    if not tube_type:
        m_ttype = re.search(r"(?:Tipe\s+Tabung|Type\s+Tabung|Model\s+Tabung|Tube\s+Type|Tube\s+Model)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
        if not m_ttype:
            m_ttype = re.search(r"\bTube\s*[:|\-–]?\s*(E[0-9]{4}[A-Za-z0-9]*)\b", all_text, re.I)
        cand_tt = clean_value(m_ttype.group(1)).strip(" :;-,") if m_ttype else ""
        if not (cand_tt.isdigit() and len(cand_tt) <= 2):
            tube_type = cand_tt

    m_tbrand = re.search(r"(?:Merk\s+Tabung|Merek\s+Tabung|Tube\s+Manufacturer|Tube\s+Brand)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    tube_brand = clean_value(m_tbrand.group(1)).strip(" :;-,") if m_tbrand else ""
    if not tube_brand and (tube_type or tube_serial):
        m_tb_explicit = re.search(r"\b(?:Tube|Tabung)[^\n\r]{0,30}?\b(CANON|TOSHIBA|PHILIPS|SIEMENS|VARIAN|DUNLEE|IAE)\b", all_text, re.I)
        if m_tb_explicit:
            tube_brand = m_tb_explicit.group(1).upper()
        elif "CANON" in all_text.upper() or "CANDN" in all_text.upper():
            tube_brand = "CANON"
        elif "TOSHIBA" in all_text.upper():
            tube_brand = "TOSHIBA"
        elif "SIEMENS" in all_text.upper() and ("SOMATOM" in all_text.upper() or "HEALTHINEERS" in all_text.upper()):
            tube_brand = "Siemens"

    # Context guidance for equipment fields
    if context:
        ref_usn = str(context.get("unit_serial_number") or "").strip()
        if ref_usn and len(ref_usn) >= 3 and ref_usn not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_usn) + r"\b", all_text, re.I):
                unit_serial = ref_usn

        ref_tsn = str(context.get("tube_serial_number") or "").strip()
        if ref_tsn and len(ref_tsn) >= 3 and ref_tsn not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tsn) + r"\b", all_text, re.I) or _normalize_ocr_serial(ref_tsn).upper() in all_text.upper():
                tube_serial = ref_tsn

        ref_ub = str(context.get("unit_brand") or "").strip()
        if ref_ub and len(ref_ub) >= 2 and ref_ub not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_ub) + r"\b", all_text, re.I):
                unit_brand = ref_ub

        ref_ut = str(context.get("unit_type") or "").strip()
        if ref_ut and len(ref_ut) >= 3 and ref_ut not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_ut) + r"\b", all_text, re.I):
                unit_type = ref_ut

        ref_tb = str(context.get("tube_brand") or "").strip()
        if ref_tb and len(ref_tb) >= 2 and ref_tb not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tb) + r"\b", all_text, re.I):
                tube_brand = ref_tb

        ref_tt = str(context.get("tube_type") or "").strip()
        if ref_tt and len(ref_tt) >= 3 and ref_tt not in ("-", "—"):
            if re.search(r"\b" + re.escape(ref_tt) + r"\b", all_text, re.I):
                tube_type = ref_tt

    unit_type_serial = f"{unit_type} / {unit_serial}".strip(" /")
    tube_type_serial = f"{tube_type} / {tube_serial}".strip(" /")

    return {
        "hospital_name": {"value": hospital_name, "page": 1, "method": "ocr_regex", "confidence": 1.0 if hospital_name else None},
        "hospital_address": {"value": hospital_address, "page": 1, "method": "ocr_regex", "confidence": 1.0 if hospital_address else None},
        "unit_brand": {"value": unit_brand, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_brand else None},
        "unit_type_serial": {"value": unit_type_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_type_serial else None},
        "unit_type": {"value": unit_type, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_type else None},
        "unit_serial_number": {"value": unit_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if unit_serial else None},
        "tube_brand": {"value": tube_brand, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_brand else None},
        "tube_type_serial": {"value": tube_type_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_type_serial else None},
        "tube_type": {"value": tube_type, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_type else None},
        "tube_serial_number": {"value": tube_serial, "page": 1, "method": "ocr_regex", "confidence": 1.0 if tube_serial else None},
    }


def extract_laporan_dosis_awal_data(pages_text, tables=None, context=None):
    all_text = "\n".join(pages_text or [])

    # 1. hospital_name
    hospital_name = ""
    m_name = re.search(r"Instansi\s*[:=\-–]?\s*([^\n\r]+?)(?:\s+Tanggal|\s+No\.|\s*$)", all_text, re.I)
    if m_name:
        hospital_name = clean_value(m_name.group(1)).strip(" :;-,")
    if not hospital_name:
        fac_name, _ = extract_facility_name(pages_text)
        if fac_name:
            hospital_name = fac_name

    # 2. hospital_address
    hospital_address = ""
    m_addr = re.search(r"Alamat(?:\s+Instansi)?\s*[:=\-–]?\s*([\s\S]+?)(?:\n\s*(?:Tanggal|Untuk|No\.|Catatan)|$)", all_text, re.I)
    if m_addr:
        raw_addr = m_addr.group(1)
        raw_addr = re.sub(r"\s+", " ", raw_addr).strip(" :;-,")
        raw_addr = re.split(r"\b(?:Tanggal\s+Evaluasi|Tanggal\s+Pelaporan|Untuk\s+Rencana)\b", raw_addr, flags=re.I)[0].strip(" :;-,")
        hospital_address = raw_addr
    if not hospital_address:
        fac_addr, _ = extract_facility_address(pages_text)
        if fac_addr:
            hospital_address = fac_addr

    # 3. usage_period
    m_period = re.search(r"(?:Untuk\s+Rencana\s+Periode\s+Pemakaian|Periode\s+Pemakaian|Rencana\s+Periode)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    usage_period = clean_value(m_period.group(1)).strip(" :;-,") if m_period else ""
    if not usage_period or usage_period in ("-", "—"):
        m_alt_period = re.search(r"(?:Tanggal\s+Pelaksanaan|Tanggal\s+Uji)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
        if m_alt_period:
            usage_period = clean_value(m_alt_period.group(1)).strip(" :;-,")


    # 4. person_name / personnel list
    personnel_names = []
    if tables:
        for tbl_item in tables:
            tbl = tbl_item[1] if isinstance(tbl_item, (tuple, list)) and len(tbl_item) == 2 and isinstance(tbl_item[0], int) else tbl_item
            if not tbl or len(tbl) < 2:
                continue
            hdr = [str(c or "").lower() for c in tbl[0]]
            name_col = -1
            for c_i, h in enumerate(hdr):
                if "nama" in h or "pengguna" in h:
                    name_col = c_i
                    break
            if name_col != -1:
                for row in tbl[1:]:
                    if name_col < len(row) and row[name_col]:
                        val = str(row[name_col]).strip()
                        if val and not re.search(r"\b(?:kontrol|control|nama|pengguna)\b", val, re.I) and len(val) >= 3:
                            personnel_names.append(clean_value(val))
                if personnel_names:
                    break

    if not personnel_names:
        for line in all_text.splitlines():
            m_row = re.search(r"(?:XA[0-9A-Za-z]+|\b\d+\b)\s+([A-Za-z][A-Za-z\s.,'\-]+?)\s+(?:0[,.]000|[0-9]+[,.][0-9]+)", line)
            if m_row:
                cand = m_row.group(1).strip()
                if not re.search(r"\b(?:kontrol|control|dosis|badan|kulit)\b", cand, re.I) and len(cand) >= 3:
                    personnel_names.append(clean_value(cand))

    selected_person = ""
    if personnel_names:
        if context and (context.get("person_name") or context.get("applicant_name")):
            from rapidfuzz import fuzz
            from src.matching.normalizer import normalize_person_name
            target_name = context.get("person_name") or context.get("applicant_name")
            target_norm = normalize_person_name(target_name)
            best_match = max(personnel_names, key=lambda n: fuzz.token_sort_ratio(normalize_person_name(n), target_norm))
            if fuzz.token_sort_ratio(normalize_person_name(best_match), target_norm) >= 60:
                selected_person = best_match
        if not selected_person:
            doc = next((n for n in personnel_names if re.search(r"\b(?:dr\b|drg\b|dokter|sp\.rad)\b", n, re.I)), None)
            selected_person = doc or personnel_names[0]

    return {
        "hospital_name": {"value": hospital_name or "-", "page": 1, "method": "native_text_regex", "confidence": 1.0 if hospital_name else None},
        "hospital_address": {"value": hospital_address or "-", "page": 1, "method": "native_text_regex", "confidence": 1.0 if hospital_address else None},
        "usage_period": {"value": usage_period or "-", "page": 1, "method": "native_text_regex", "confidence": 1.0 if usage_period else None},
        "person_name": {"value": selected_person or "-", "page": 1, "method": "native_text_regex", "confidence": 1.0 if selected_person else None},
        "all_personnel": personnel_names,
    }


def extract_gedung_penahan_radiasi_data(pages_text, tables=None):
    all_text = "\n".join(pages_text or [])

    # 1. hospital_name
    hospital_name = ""
    m_quote = re.search(r"[\"“'‘`\ufffd\(\[]\s*(RUMAH\s+SAKIT\s+[^\r\n\"”'’`\ufffd\)\]]+|RS\s+[^\r\n\"”'’`\ufffd\)\]]+|KLINIK\s+[^\r\n\"”'’`\ufffd\)\]]+)[\"”'’`\ufffd\)\]]", all_text, re.I)
    if m_quote:
        hospital_name = clean_value(m_quote.group(1)).strip(" :;-,")
    if not hospital_name and pages_text:
        m_cov = re.search(r"\b(RUMAH\s+SAKIT\s+[^\r\n]+|RS\s+[^\r\n]+|KLINIK\s+[^\r\n]+)\b", pages_text[0], re.I)
        if m_cov:
            hospital_name = clean_value(m_cov.group(1)).strip(" :;-,")
    if not hospital_name:
        fac_name, _ = extract_facility_name(pages_text)
        if fac_name:
            hospital_name = fac_name

    # 2. hospital_address
    hospital_address = ""
    target_page = pages_text[1] if len(pages_text or []) > 1 else all_text
    m_addr = re.search(r"\b((?:J[IlL1]\.?|Jalan)\s+[^\r\n]+(?:\r?\n[ \t]*(?:RT|RW|Kelurahan|Kecamatan|Kabupaten|Kota|[A-Z][a-z]+)[^\r\n]+){1,3})", target_page, re.I)
    if m_addr:
        raw_block = m_addr.group(1)
        cleaned_lines = []
        for line in raw_block.splitlines():
            line = re.sub(r"\s+(?:Tanggal|Hal|No\.?\s*Dokumen)\s*:?.*$", "", line, flags=re.I).strip(" :;-,")
            if line and not re.search(r"^(?:LEMBAR|DAFTAR|BAB|Nama|Jabatan|Hal|No\.?)\b", line, re.I):
                cleaned_lines.append(line)
        if cleaned_lines:
            hospital_address = ", ".join(cleaned_lines)
    if not hospital_address:
        m_gen_jl = re.search(r"\b(J[IlL1]\.?[ \t]+[^\r\n|]+(?:\r?\n[^\r\n|]+){1,2})", target_page, re.I)
        if m_gen_jl:
            raw_addr = re.sub(r"\s+", " ", m_gen_jl.group(1)).strip(" :;-,")
            raw_addr = re.split(r"\b(?:No\.?\s*Dokumen|Tanggal\s*:|Hal\s*:)\b", raw_addr, flags=re.I)[0].strip(" :;-,")
            if len(raw_addr) >= 10:
                hospital_address = raw_addr
    if not hospital_address:
        fac_addr, _ = extract_facility_address(pages_text)
        if fac_addr:
            hospital_address = fac_addr

    p_num = 2 if len(pages_text or []) >= 2 else 1
    return {
        "hospital_name": {"value": hospital_name or "-", "page": p_num, "method": "native_text_regex", "confidence": 1.0 if hospital_name else None},
        "hospital_address": {"value": hospital_address or "-", "page": p_num, "method": "native_text_regex", "confidence": 1.0 if hospital_address else None},
    }


def parse_document(doc_type, pages_text, tables=None, context=None):
    tables = tables or []
    fields = DOCUMENT_FIELDS[doc_type]

    if doc_type == "formulir":
        parsed = extract_form_data(tables, pages_text)
        generator = parsed["xray_data"]
        xray = dict(generator)
        u_b = xray.get("unit_brand", "")
        u_t = xray.get("unit_type", "")
        u_s = xray.get("unit_serial_number", "")
        t_b = xray.get("tube_brand", "")
        t_t = xray.get("tube_type", "")
        t_s = xray.get("tube_serial_number", "")
        u_ts = xray.get("unit_type_serial", "") or f"{u_t} / {u_s}".strip(" /")
        t_ts = xray.get("tube_type_serial", "") or f"{t_t} / {t_s}".strip(" /")
        p_num = generator.get("page")

        clean_xray = {
            "unit_brand": u_b,
            "unit_type": u_t,
            "unit_serial_number": u_s,
            "tube_brand": t_b,
            "tube_type": t_t,
            "tube_serial_number": t_s,
            "page": p_num,
        }
        clean_all_rows = []
        for r in parsed.get("all_xray_rows", []):
            clean_r = {k: v for k, v in r.items() if k not in ("unit_type_serial", "tube_type_serial")}
            clean_all_rows.append(clean_r)

        fields_dict = {
            "header": parsed.get("header", {}),
            "hospital_name": {**parsed["hospital_name"], "confidence": 1.0 if parsed["hospital_name"].get("value") else None},
            "hospital_address": {**parsed["hospital_address"], "confidence": 1.0 if parsed["hospital_address"].get("value") else None},
            "unit_brand": {"value": u_b, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_b else None},
            "unit_type": {"value": u_t, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_t else None},
            "unit_serial_number": {"value": u_s, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_s else None},
            "unit_type_serial": {"value": u_ts, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_ts else None},
            "tube_brand": {"value": t_b, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_b else None},
            "tube_type": {"value": t_t, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_t else None},
            "tube_serial_number": {"value": t_s, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_s else None},
            "tube_type_serial": {"value": t_ts, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_ts else None},
            "personnel_data": {"value": parsed["personnel_data"], "page": None, "method": "native_text_table", "confidence": 1.0 if parsed["personnel_data"] else None},
            "all_xray_rows": clean_all_rows or parsed.get("all_xray_rows", []),
        }

        # If multiple equipment units exist, also add unit-indexed fields for multi-entity visibility
        if len(clean_all_rows) > 1:
            for idx, r in enumerate(clean_all_rows, 1):
                p_r = r.get("page", p_num)
                fields_dict[f"unit_brand_{idx}"] = {"value": r.get("unit_brand", ""), "page": p_r, "method": "native_text_table", "confidence": 1.0 if r.get("unit_brand") else None}
                fields_dict[f"unit_type_{idx}"] = {"value": r.get("unit_type", ""), "page": p_r, "method": "native_text_table", "confidence": 1.0 if r.get("unit_type") else None}
                fields_dict[f"unit_serial_number_{idx}"] = {"value": r.get("unit_serial_number", ""), "page": p_r, "method": "native_text_table", "confidence": 1.0 if r.get("unit_serial_number") else None}
                fields_dict[f"tube_brand_{idx}"] = {"value": r.get("tube_brand", ""), "page": p_r, "method": "native_text_table", "confidence": 1.0 if r.get("tube_brand") else None}
                fields_dict[f"tube_type_{idx}"] = {"value": r.get("tube_type", ""), "page": p_r, "method": "native_text_table", "confidence": 1.0 if r.get("tube_type") else None}
                fields_dict[f"tube_serial_number_{idx}"] = {"value": r.get("tube_serial_number", ""), "page": p_r, "method": "native_text_table", "confidence": 1.0 if r.get("tube_serial_number") else None}

        return {
            "document_type": doc_type,
            "fields": _finalize_document_fields(doc_type, fields_dict),
        }

    force_llm = bool(context and context.get("force_llm"))

    if doc_type == "ppkr":
        data = extract_ppkr_data(pages_text, tables, context=context)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    if doc_type == "uji_kesesuaian":
        data = extract_uji_kesesuaian_data(pages_text, tables, context=context)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    if doc_type == "persetujuan_import":
        data = extract_persetujuan_import_data(pages_text, tables, context=context)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    if doc_type == "paparan_radiasi":
        data = extract_paparan_radiasi_data(pages_text, tables, context=context)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    if doc_type == "uji_fungsi":
        data = extract_uji_fungsi_data(pages_text, tables, context=context)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    if doc_type == "laporan_dosis_awal":
        data = extract_laporan_dosis_awal_data(pages_text, tables, context=context)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    if doc_type == "gedung_penahan_radiasi":
        data = extract_gedung_penahan_radiasi_data(pages_text, tables)
        data = merge_with_llm_fallback(doc_type, data, pages_text, force_llm=force_llm, context=context)
        return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, data)}

    generic_fields = [f for f in fields if f not in {"administrative_documents", "personnel_data", "table_of_contents"}]
    generic = extract_generic_fields(pages_text, generic_fields, context=context)
    special = {}

    if doc_type == "sip":
        special = extract_sip_data(pages_text)
    elif doc_type == "sprint":
        special = extract_sprint_data(pages_text)
    elif doc_type == "sib":
        special = extract_sib_data(pages_text)
    elif doc_type == "spesifikasi_pesawat":
        unit_brand_field = _first_match(pages_text, [_rx_optional_colon("Merk|Merek|Manufacturer")])
        unit_type_field = _first_match(pages_text, [r"\b(?:Tipe|Type|Model)\b(?!\s*/\s*No\s*Seri)[ \t]*:?[ \t]*(.+)"])

        # Fallback for manufacturer brochure layouts (e.g. GE Healthcare, Shimadzu, Philips, etc.)
        if not unit_brand_field.get("value") or unit_brand_field.get("value") in ("-", "—"):
            known_brands = [
                "GE Healthcare", "General Electric", "GE Medical", "GE",
                "Shimadzu", "Philips", "Siemens Healthineers", "Siemens",
                "United Imaging Healthcare", "Shanghai United Imaging Healthcare", "United Imaging", "UIH",
                "GE Healthcare", "General Electric", "GE Medical", "GE",
                "Shimadzu", "Philips", "Siemens Healthineers", "Siemens",
                "Canon Medical", "Canon", "Toshiba", "Carestream",
                "Fujifilm", "Mindray", "Hitachi", "Wandong"
            ]
            for p_idx, p_txt in enumerate(pages_text[:2], start=1):
                lines = [l.strip() for l in p_txt.splitlines() if l.strip()]
                for l_idx, l in enumerate(lines):
                    for kb in known_brands:
                        if re.search(rf"\b{re.escape(kb)}\b", l, re.I):
                            brand_val = "United Imaging Healthcare" if "united imaging" in kb.lower() or kb == "UIH" else kb
                            unit_brand_field = {"value": brand_val, "page": p_idx, "method": "brochure_header"}
                            if (not unit_type_field.get("value") or unit_type_field.get("value") in ("-", "—")) and l_idx + 1 < len(lines):
                                cand_model = lines[l_idx + 1].strip("* •-")
                                if cand_model and not re.search(r"^(?:imagination|system|solution|hospital|healthcare|medical)\b", cand_model, re.I):
                                    unit_type_field = {"value": cand_model, "page": p_idx, "method": "brochure_title"}
                            break
                    if unit_brand_field.get("value") and unit_brand_field.get("value") not in ("-", "—"):
                        break
                if unit_brand_field.get("value") and unit_brand_field.get("value") not in ("-", "—"):
                    break

        if not unit_type_field.get("value") or unit_type_field.get("value") in ("-", "—"):
            for p_idx, p_txt in enumerate(pages_text[:2], start=1):
                m_model = re.search(
                    r"\b(uDR[\s*]+[A-Za-z0-9\-]+|Optima[\s*]+[A-Za-z0-9\-]+|Definium[\s*]+[A-Za-z0-9\-]+|Brivo[\s*]+[A-Za-z0-9\-]+|RADspeed[\s*]+[A-Za-z0-9\-\s]+|MobileDaRt[\s*]+[A-Za-z0-9\-\s]+|MobileArt[\s*]+[A-Za-z0-9\-\s]+|Multix[\s*]+[A-Za-z0-9\-\s]+|Mobilett[\s*]+[A-Za-z0-9\-\s]+|DigitalDiagnost[\s*]+[A-Za-z0-9\-\s]+|DRX[\s*\-]+[A-Za-z0-9\-]+|MobiEye[\s*]+[A-Za-z0-9\-]+|DigiEye[\s*]+[A-Za-z0-9\-]+)\b",
                    p_txt,
                    re.I,
                )
                if m_model:
                    unit_type_field = {"value": re.sub(r"[*]", "", m_model.group(1)).strip(), "page": p_idx, "method": "brochure_pattern"}
                    break

        special = {
            "unit_brand": unit_brand_field,
            "unit_type": unit_type_field,
        }
    elif doc_type == "tld":
        special = {
            "usage_period": _first_match(pages_text, [
                r"(?:pemakaian(?: bulan)?|periode)\s*[:\-–]?\s*([A-Za-z0-9 ./-]+(?:s\.?d\.?|-|sampai)[A-Za-z0-9 ./-]+)",
                _rx("Periode Pemakaian|Periode Penggunaan|Periode"),
            ]),
        }
        if not generic.get("person_name", {}).get("value") or generic.get("person_name", {}).get("value") in ("-", "—"):
            all_txt = "\n".join(pages_text)
            names = [
                n.strip() for n in re.findall(r"^\s*\d+\.\s+([A-Za-z][A-Za-z '\.]+?)(?:\s+\(|$|\s+\d)", all_txt, re.M)
                if not re.search(r"kontrol|control", n, re.I)
            ]
            if names:
                doctor_candidate = None
                if context and (context.get("person_name") or context.get("applicant_name")):
                    from rapidfuzz import fuzz
                    from src.matching.normalizer import normalize_person_name
                    target_name = context.get("person_name") or context.get("applicant_name")
                    target_norm = normalize_person_name(target_name)
                    best_match = max(names, key=lambda n: fuzz.token_sort_ratio(normalize_person_name(n), target_norm))
                    if fuzz.token_sort_ratio(normalize_person_name(best_match), target_norm) >= 60:
                        doctor_candidate = best_match
                if not doctor_candidate:
                    doctor_candidate = next((n for n in names if re.search(r"\b(?:dr\b|drg\b|prof\b|dokter|sp\.rad)\b", n, re.I)), None)
                if not doctor_candidate:
                    doctor_candidate = next((n for n in names if re.search(r"adimas|dr\.", n, re.I)), names[0])
                special["person_name"] = {"value": doctor_candidate, "page": 1, "method": "native_text_regex"}
    elif doc_type == "sistem_manajemen":
        special = {}
    elif doc_type == "program_perawatan":
        special = {
            "conformity_test_clause": _first_match(pages_text, [
                r"((?:klausul|clause).{0,120}uji[ \t]+kesesuaian[^\n]*)",
                r"(uji[ \t]+kesesuaian[^\n]*)",
            ]),
        }

    merged = _merge(generic, special)
    merged = merge_with_llm_fallback(doc_type, merged, pages_text, force_llm=force_llm, context=context)
    for date_key in ("valid_until",):
        item = merged.get(date_key)
        if isinstance(item, dict) and item.get("value") and item.get("value") not in ("-", "—"):
            item["value"] = normalize_date(item["value"])

    for k, item in merged.items():
        if isinstance(item, dict):
            if item.get("value") not in ("", None, [], "-", "—"):
                if item.get("confidence") is None:
                    item["confidence"] = 1.0
            else:
                item["confidence"] = None

    return {"document_type": doc_type, "fields": _finalize_document_fields(doc_type, merged)}


def _find_page_containing(pages_text, needle_or_pattern):
    for idx, text in enumerate(pages_text or [], start=1):
        if text and re.search(needle_or_pattern, str(text), re.IGNORECASE):
            return idx
    return None


def _extract_toc(pages_text):
    page = _find_page_containing(pages_text, r"DAFTAR\s*ISI")
    if page is None or not pages_text or page - 1 >= len(pages_text) or not pages_text[page - 1]:
        return ""
    lines = [line.strip() for line in str(pages_text[page - 1]).splitlines() if line.strip()]
    values, started = [], False
    for line in lines:
        if re.search(r"DAFTAR\s*ISI", line, re.IGNORECASE):
            started = True
            continue
        if started:
            if re.search(r"^(?:Nomor|Halaman|Tanggal|Revisi|RSTK)\b", line, re.IGNORECASE):
                continue
            if len(values) >= 40:
                break
            values.append(line)
    return " | ".join(values)
