import re

from src.schema.fields import DOCUMENT_FIELDS
from src.extraction.generic_parser import (
    extract_facility_name,
    extract_facility_address,
    extract_generic_fields,
    extract_raw_blocks,
    clean_value,
)
from src.extraction.form_parser import extract_form_data, parse_people_tables
from src.matching.normalizer import normalize_date


def _empty(value=""):
    return {"value": value, "page": None, "method": "not_found", "confidence": None}


def _first_match(pages_text, patterns):
    for page_index, page_text in enumerate(pages_text, start=1):
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                value = clean_value(match.group(1))
                if value:
                    return {"value": value, "page": page_index, "method": "native_text_regex", "confidence": 1.0}
    return _empty()


def _merge(base, updates):
    result = dict(base)
    for key, value in updates.items():
        if value and value.get("value") not in ("", [], None):
            result[key] = value
    return result


def _rx(label_group):
    return rf"(?:{label_group})[ \t]*:[ \t]*(.+)"


def _rx_optional_colon(label_group):
    return rf"\b(?:{label_group})\b[ \t]*:?[ \t]*(.+)"


# Multilingual & multi-format synonym patterns for X-ray tube components
RX_INSERT_SERIAL = (
    r"(?:No\.?\s*Seri(?:\s+Insert(?:\s+Tabung)?|\s+Tabung\s+Sisipan|\s+Sisipan)"
    r"|Nomor\s+Seri(?:\s+Insert(?:\s+Tabung)?|\s+Tabung\s+Sisipan|\s+Sisipan|\s+Tabung\s+Insert)"
    r"|Insert(?:\s+Tube|\s+Tabung)?\s*(?:S/?N|Serial(?:\s+No|\s+Number)?|No\.?)"
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



def extract_ppkr_data(pages_text, tables):
    """Parses PPKR document text and structured personnel tables."""
    fields = extract_generic_fields(
        pages_text,
        [
            "hospital_name", "hospital_address",
            "person_name", "unit_brand", "unit_type",
            "unit_serial_number", "tube_brand", "tube_type",
        ],
    )
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
        if isinstance(item, dict) and item.get("value") not in ("", None, []):
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
                m_name = re.search(
                    r"(?:Diberikan\s+kepada|Nama\s+(?:Lengkap|PPR|Pemegang(?:\s+SIB)?)?|Nama\s*/\s*Name|Kepada)\s*[:=\-–]?\s*([A-Za-z .,'\-]+)$",
                    line,
                    re.IGNORECASE,
                )
                if m_name:
                    cand = clean_value(m_name.group(1)).strip(" :;-,")
                    if len(cand) >= 3 and not re.search(r"^(?:Petugas|BAPETEN|Surat|Keputusan|Izin|Name)\b", cand, re.I):
                        ppr_name = cand
                        name_page = p_idx
                elif re.search(r"^(?:Diberikan\s+kepada|Nama(?:\s+(?:Lengkap|PPR|Pemegang))?(?:\s*/\s*Name)?|Kepada)\s*[:=\-–]?$", line, re.I):
                    for cand_line in lines[idx + 1 : idx + 4]:
                        cand = clean_value(cand_line).strip(" :;-,")
                        if len(cand) >= 3 and not re.search(r"^(?:Petugas|BAPETEN|Surat|Keputusan|Nomor|NIK|No\.|Direktur|Director|Kepala|Perizinan|Licensing|Radioactive)\b", cand, re.I):
                            ppr_name = cand
                            name_page = p_idx
                            break

            # 2. profession
            if not profession:
                m_prof = re.search(
                    r"(?:Sebagai|Kualifikasi|Klasifikasi|Profesi|Keahlian|Jabatan|Jenis\s+SIB)\s*[:=\-–]?\s*([^\n\r]+)$",
                    line,
                    re.IGNORECASE,
                )
                if m_prof:
                    cand_prof = clean_value(m_prof.group(1)).strip(" :;-,")
                    if cand_prof:
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


def extract_uji_kesesuaian_data(pages_text, tables=None):
    all_text = "\n".join(pages_text)

    # 1. hospital_name
    m_name = re.search(
        r"(?:Data\s+Pemohon\s+uji[\s\S]*?Nama\s+Instansi|Nama\s+Instansi|Nama\s+Rumah\s+Sakit|Nama\s+Fasilitas)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    hospital_name = clean_value(m_name.group(1)).strip(" :;-,") if m_name else ""

    # 2. hospital_address
    m_addr = re.search(
        r"(?:Data\s+Pemohon\s+uji[\s\S]*?Alamat|Alamat\s+Instansi|Alamat\s+Rumah\s+Sakit|Alamat)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    hospital_address = clean_value(m_addr.group(1)).strip(" :;-,") if m_addr else ""

    # 3. Generator section (unit_brand, unit_type, unit_serial_number, unit_type_serial)
    gen_block = ""
    m_gen = re.search(r"A\.\s*Generator[^\n]*\n((?:[^\n]*\n){1,10})", all_text, re.I)
    if m_gen:
        gen_block = m_gen.group(1)

    m_ub = re.search(r"(?:Pabrikan\s*/\s*Merk|Merk\s+Unit|Pabrikan)\s*[:=\-–]?\s*([^\n\r]+)", gen_block or all_text, re.I)
    unit_brand = clean_value(m_ub.group(1)).strip(" :;-,") if m_ub else ""
    if not unit_brand:
        m_ub_any = re.search(r"\b(GE|PHILIPS|SIEMENS|SHIMADZU|TOSHIBA|HITACHI|CARESTREAM)\b", all_text, re.I)
        if m_ub_any:
            unit_brand = m_ub_any.group(1).upper()

    m_ut = re.search(r"(?:Model\s*/\s*Tipe|Model\s+Unit|Model|Tipe)\s*[:=\-–]?\s*([^\n\r]+)", gen_block or all_text, re.I)
    unit_type = clean_value(m_ut.group(1)).strip(" :;-,") if m_ut else ""

    m_us = re.search(r"(?:Nomor\s+Seri|No\.?\s*Seri)\s*[:=\-–]?\s*([^\n\r]+)", gen_block or all_text, re.I)
    unit_serial = clean_value(m_us.group(1)).strip(" :;-,") if m_us else ""

    if unit_type and unit_serial:
        unit_type_serial = f"{unit_type} / {unit_serial}"
    else:
        unit_type_serial = unit_type or unit_serial

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

    return {
        "hospital_name": {"value": hospital_name, "page": 1, "method": "native_text_regex", "confidence": 1.0 if hospital_name else None},
        "hospital_address": {"value": hospital_address, "page": 1, "method": "native_text_regex", "confidence": 1.0 if hospital_address else None},
        "unit_brand": {"value": unit_brand, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_brand else None},
        "unit_type_serial": {"value": unit_type_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_type_serial else None},
        "unit_type": {"value": unit_type, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_type else None},
        "unit_serial_number": {"value": unit_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if unit_serial else None},
        "tube_brand": {"value": tube_brand, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_brand else None},
        "tube_type": {"value": tube_type, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_type else None},
        "tube_serial_number": {"value": tube_serial, "page": 1, "method": "native_text_regex", "confidence": 1.0 if tube_serial else None},
    }


def extract_persetujuan_import_data(pages_text, tables=None):
    tables = tables or []
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
            picked_row = None
            if "user" in col_map:
                for dr in data_rows:
                    user_val = str(dr[col_map["user"]] or "").strip()
                    if len(user_val) >= 3 and not re.search(r"^(?:-|—|null|none)$", user_val, re.I):
                        picked_row = dr
                        break
            if not picked_row and data_rows:
                picked_row = data_rows[0]

            if picked_row:
                def get_c(key):
                    idx = col_map.get(key)
                    if idx is not None and idx < len(picked_row):
                        return re.sub(r"\s+", " ", str(picked_row[idx] or "")).strip()
                    return ""

                unit_brand = get_c("unit_brand")
                unit_type_serial = get_c("unit_type_serial")
                tube_brand = get_c("tube_brand")
                tube_type_serial = get_c("tube_type_serial")
                page_num = page_idx + 1

                if not tube_type_serial and "tube" in unit_type_serial.lower():
                    m_tube = re.search(r"Tube\s+S/N\s*:\s*([A-Za-z0-9]+)", unit_type_serial, re.I)
                    if m_tube:
                        tube_type_serial = m_tube.group(1).strip()
                        tube_serial = tube_type_serial
                        unit_type_serial = re.sub(r"\s*Tube\s+S/N\s*:\s*[A-Za-z0-9]+", "", unit_type_serial, flags=re.I).strip()
                if not tube_brand and re.search(r"\bcanon\b", all_text, re.I):
                    tube_brand = "CANON"
                if "ge mobile" in unit_brand.lower():
                    unit_brand = "GE"
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

    # Split helper fields
    if unit_type_serial and not unit_type:
        if "/" in unit_type_serial:
            parts = unit_type_serial.split("/", 1)
            unit_type = parts[0].replace("S/N:", "").strip()
            unit_serial = parts[1].replace("S/N:", "").strip()
        elif "S/N:" in unit_type_serial:
            parts = unit_type_serial.split("S/N:", 1)
            unit_type = parts[0].strip()
            unit_serial = parts[1].strip()
        else:
            unit_type = unit_type_serial

    if tube_type_serial and not tube_type:
        if "/" in tube_type_serial:
            parts = tube_type_serial.split("/", 1)
            tube_type = parts[0].replace("S/N:", "").strip()
            tube_serial = parts[1].replace("S/N:", "").strip()
        else:
            tube_serial = tube_type_serial

    return {
        "unit_brand": {"value": unit_brand, "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if unit_brand else None},
        "unit_type_serial": {"value": unit_type_serial, "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if unit_type_serial else None},
        "unit_type": {"value": unit_type, "page": page_num, "method": "split", "confidence": 1.0 if unit_type else None},
        "unit_serial_number": {"value": unit_serial, "page": page_num, "method": "split", "confidence": 1.0 if unit_serial else None},
        "tube_brand": {"value": tube_brand, "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if tube_brand else None},
        "tube_type_serial": {"value": tube_type_serial, "page": page_num, "method": "native_text_table" if tables else "native_text_regex", "confidence": 1.0 if tube_type_serial else None},
        "tube_type": {"value": tube_type, "page": page_num, "method": "split", "confidence": 1.0 if tube_type else None},
        "tube_serial_number": {"value": tube_serial, "page": page_num, "method": "split", "confidence": 1.0 if tube_serial else None},
    }


def extract_paparan_radiasi_data(pages_text, tables=None):
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
        fac_name, _ = extract_facility_name(pages_text)
        if fac_name:
            hospital_name = fac_name

    # 2. hospital_address
    hospital_address = ""
    cust_block = re.split(r"\b(?:Data\s+Pengalih|Data\s+Alat|Data\s+Pesawat)\b", all_text, flags=re.I)[0]

    # Check for direct Jl./Jalan pattern in the customer block first
    m_cust_jl = re.search(r"\b(J[IlL1]\.?[ \t]+[^\r\n|]+)", cust_block, re.I)
    if m_cust_jl:
        cand_addr = clean_value(m_cust_jl.group(1)).strip(" :;-,")
        cand_addr = re.sub(r"\s+(?:2\s+Alamat|Nama\s+Pendamping|Data\s+Pengalih|Data\s+Alat).*$", "", cand_addr, flags=re.I).strip(" :;-,")
        if len(cand_addr) >= 8:
            hospital_address = cand_addr

    if not hospital_address:
        m_addr = re.search(
            r"(?:Alamat(?:\s+Rumah\s+Sakit|\s+Pelanggan)?|Address)\s*[:=\-–]?\s*([^\n\r]+)",
            cust_block,
            re.I,
        )
        if m_addr:
            cand_addr = clean_value(m_addr.group(1)).strip(" :;-,")
            if not re.search(r"\b(?:Nama\s+Pendamping|Pendamping|Jabatan|Radiographer|Pengalih|Data\s+Alat)\b", cand_addr, re.I):
                if len(cand_addr) >= 8:
                    hospital_address = cand_addr

    if not hospital_address:
        m_jl = re.search(r"\b(J[IlL1]\.?[ \t]+[^\r\n|]+)", all_text, re.I)
        if m_jl:
            hospital_address = clean_value(m_jl.group(1)).strip(" :;-,")

    if not hospital_address:
        fac_addr, _ = extract_facility_address(pages_text)
        if fac_addr:
            hospital_address = fac_addr

    if hospital_address.startswith("JI."):
        hospital_address = "Jl." + hospital_address[3:]

    # 3. Unit model & serial
    m_model = re.search(r"\b(OPTIMA[ \t]+XR[0-9A-Z]+(?:\s+[A-Z0-9]+)?|SOMATOM[ \t]+[^\n\r]+|Azurion[ \t]+[^\n\r]+)\b", all_text, re.I)
    if not m_model:
        m_model = re.search(r"(?:Model Alat|Jenis Alat)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    unit_type = clean_value(m_model.group(1)).strip(" :;-,") if m_model else ""

    m_serial = re.search(r"\b(SB[0-9]{5,}[A-Z0-9]*)\b", all_text, re.I)
    if not m_serial:
        m_serial = re.search(r"(?:No Seri Alat|No\.?\s*Seri Alat)\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)", all_text, re.I)
    unit_serial = clean_value(m_serial.group(1)).strip(" :;-,") if m_serial else ""

    # 4. Unit brand
    m_ubrand = re.search(r"(?:Merk Alat|Merek Alat|Pabrikan Alat|Manufacturer)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
    if m_ubrand:
        cand_ub = clean_value(m_ubrand.group(1)).strip(" :;-,")
        cand_ub = re.sub(r"\s+(?:Corporation|Corp|Healthcare|Health|Medical|Systems|Inc|Co\.,?\s*Ltd)\b.*$", "", cand_ub, flags=re.I).strip()
        m_kb_match = re.search(r"\b(SIEMENS|PHILIPS|GE|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS|ECORAY)\b", cand_ub, re.I)
        unit_brand = m_kb_match.group(1).upper() if m_kb_match else cand_ub
    elif "OPTIMA" in unit_type.upper():
        unit_brand = "GE"
    elif "SOMATOM" in unit_type.upper():
        unit_brand = "Siemens"
    elif "AZURION" in unit_type.upper():
        unit_brand = "Philips"
    else:
        m_kb = re.search(r"\b(GE|PHILIPS|SIEMENS|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS)\b", all_text, re.I)
        unit_brand = m_kb.group(1).upper() if m_kb else ""

    unit_type_serial = f"{unit_type} / {unit_serial}".strip(" /")

    # 5. Tube brand
    m_tb = re.search(r"\b(CANON(?: ELECTRON)?|TOSHIBA|PHILIPS|SIEMENS|GE|SHIMADZU|VARIAN|DUNLEE|IAE)\b", all_text, re.I)
    tube_brand = clean_value(m_tb.group(1)).strip(" :;-,") if m_tb else ""
    if "CANON" in tube_brand.upper():
        tube_brand = "CANON"

    # 6. Tube type (prioritize Insert Model if present, fallback to Tube/Housing model)
    tube_type = _extract_tube_insert_model(all_text)
    if not tube_type:
        m_tt = re.search(r"\b(E[0-9]{4}[A-Z]?|MRC[ \t]*[0-9]+|ATHLON[ \t]*[A-Z]+)\b", all_text, re.I)
        if not m_tt:
            m_tt = re.search(RX_HOUSING_MODEL, all_text, re.I)
        if not m_tt:
            m_tt = re.search(r"(?:Tipe Tabung|No Model Tabung)\s*[:=\-–]?\s*([^\n\r]+)", all_text, re.I)
        cand_tt = clean_value(m_tt.group(1)).strip(" :;-,") if m_tt else ""
        if not (cand_tt.isdigit() and len(cand_tt) <= 2):
            tube_type = cand_tt

    # 7. Tube serial (Prioritize Insert S/N over Housing S/N per BAPETEN standard)
    m_insert_sn = re.search(RX_INSERT_SERIAL, all_text, re.I)
    if m_insert_sn:
        tube_serial = clean_value(m_insert_sn.group(1)).strip(" :;-,")
    else:
        m_ts = re.search(RX_HOUSING_SERIAL, all_text, re.I)
        if m_ts:
            tube_serial = clean_value(m_ts.group(1)).strip(" :;-,")
        else:
            m_cand = re.search(r"\b([0-9]{2}[A-Z][0-9]{3,}|[0-9][A-Z][0-9]{4,}|OF[0-9]{4}|0F[0-9]{4})\b", all_text, re.I)
            tube_serial = clean_value(m_cand.group(1)).strip(" :;-,") if m_cand else ""

    tube_serial = _normalize_ocr_serial(tube_serial)
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


def extract_uji_fungsi_data(pages_text, tables=None):
    all_text = "\n".join(pages_text)

    # 1. hospital_name (Generic extractor handling single-line, multi-line, and side-by-side CAF tables)
    hospital_name = ""
    m_name = re.search(
        r"(?:Customer\s+Name(?:\s*/\s*Nama\s+Pelanggan)?|Nama\s+Pelanggan|Hospital\s+Name|Nama\s+Rumah\s+Sakit|Pelanggan)\s*[:=\-–]?\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    if m_name:
        cand = clean_value(m_name.group(1)).strip(" :;-,")
        # Strip adjacent table columns on the same line (PO number, Contract, Address, Mechanical test items, etc.)
        cand = re.split(
            r"\b(?:Tube(?:\s+tilt)?|Mechanical|InSpec|Horizontal|Vertical|Collimator|Colimator|Brake|Batere|Status|PASS|FAIL|NOT\s+AVAILABLE|BJ\.|PO\b|Purchase|Ref\.|Contract|Kontrak|Address|Alamat|Bagian|Radiology|Section)\b",
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
            hospital_name = re.sub(
                r"\s+(?:Tube\s+tilt|Tube|Collimator|Colimator|Brake|Batere|InSpec|Status|PASS|FAIL|Mechanical).*$",
                "",
                cand,
                flags=re.I,
            ).strip(" :;-,")

    if not hospital_name:
        fac_name, _ = extract_facility_name(pages_text)
        if fac_name:
            hospital_name = re.sub(
                r"\s+(?:Tube\s+tilt|Tube|Collimator|Colimator|Brake|Batere|InSpec|Status|PASS|FAIL|Mechanical).*$",
                "",
                fac_name,
                flags=re.I,
            ).strip(" :;-,")
        else:
            m_rs = re.search(r"\b(Rumah\s+Sakit\s+[^\n\r,;|]+|RSUD\s+[^\n\r,;|]+|Rumkit\s+[^\n\r,;|]+|RS\s+[A-Za-z0-9 ]+)\b", all_text, re.I)
            if m_rs:
                hospital_name = clean_value(m_rs.group(1)).strip(" :;-,")
                hospital_name = re.sub(
                    r"\s+(?:Tube\s+tilt|Tube|Collimator|Colimator|Brake|Batere|InSpec|Status|PASS|FAIL|Mechanical).*$",
                    "",
                    hospital_name,
                    flags=re.I,
                ).strip(" :;-,")

    # 2. hospital_address
    hospital_address = ""
    m_addr = re.search(
        r"(?:Customer\s+Address(?:\s*/\s*Alamat\s+Pelanggan)?|Hospital\s+Address|Alamat(?:\s+Pelanggan|\s+Rumah\s+Sakit)?|Address)\s*[:=\-–]\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    if m_addr:
        addr_line = m_addr.group(1)
        addr_line = re.sub(r"\s+(?:Collimator|Tube|Brake|Batere|yang selanjutnya|Serial number).*$", "", addr_line, flags=re.I).strip()
        hospital_address = clean_value(addr_line).strip(" :;-,")
    else:
        m_jl = re.search(
            r"(J[IlL1]\.?[ \t]+[A-Za-z0-9 .,/'-]+(?:(?:\n|,)[ \t]*[A-Za-z0-9 .,/'-]+){0,3}?(?:[0-9]{5}|Indonesia|\b(?:Kota|Kab\.?|Kabupaten|Kec\.?|Kecamatan|Prov\.?|Provinsi)\b|[A-Za-z]{4,}))",
            all_text,
            re.I,
        )
        if m_jl:
            addr_raw = m_jl.group(1)
            addr_raw = re.sub(r"\b(?:Serial\s+number|Customer\s+Address|Alamat\s+Pelanggan|Nomor\s+seri|\(if\s+applicable\)|\b\d{3}\b)\b", "", addr_raw, flags=re.I)
            addr_clean = " ".join(line.strip() for line in addr_raw.splitlines() if line.strip())
            addr_clean = re.sub(r"\s+", " ", addr_clean)
            addr_clean = re.sub(r",\s*,", ",", addr_clean).strip(" ,")
            hospital_address = clean_value(addr_clean).strip(" :;-,")

    if not hospital_address:
        fac_addr, _ = extract_facility_address(pages_text)
        if fac_addr:
            hospital_address = fac_addr

    if hospital_address.startswith("JI."):
        hospital_address = "Jl." + hospital_address[3:]

    # 3. Unit Brand
    m_ubrand = re.search(r"(?:Merk(?:\s+Alat|\s+Unit)?|Manufacturer|Pabrikan)\s*[:=\-–]\s*([^\n\r]+)", all_text, re.I)
    if m_ubrand:
        cand_ub = clean_value(m_ubrand.group(1)).strip(" :;-,")
        cand_ub = re.sub(r"\s+(?:Corporation|Corp|Healthcare|Health|Medical|Systems|Inc|Co\.,?\s*Ltd)\b.*$", "", cand_ub, flags=re.I).strip()
        m_kb_match = re.search(r"\b(SIEMENS|PHILIPS|GE|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS|ECORAY)\b", cand_ub, re.I)
        if m_kb_match:
            kb_name = m_kb_match.group(1).capitalize()
            unit_brand = "GE" if kb_name.upper() == "GE" else kb_name
        else:
            unit_brand = cand_ub
    elif re.search(r"\b(?:PT\.?\s*)?SIEMENS(?:\s+HEALTHINEERS)?\b", all_text, re.I) or re.search(r"Somatom", all_text, re.I):
        unit_brand = "Siemens"
    elif re.search(r"\b(?:PT\s+PHILIPS|PHILIPS)\b", all_text, re.I) or re.search(r"Azurion", all_text, re.I):
        unit_brand = "Philips"
    elif re.search(r"\b(?:GLOMEDA|GE\s+HEALTHCARE|GENERAL\s+ELECTRIC)\b", all_text, re.I) or re.search(r"\b(?:OPTIMA|XR200)\b", all_text, re.I):
        unit_brand = "GE"
    elif re.search(r"\bSHIMADZU\b", all_text, re.I) or re.search(r"RADspeed", all_text, re.I):
        unit_brand = "Shimadzu"
    else:
        m_kb = re.search(r"\b(SIEMENS|PHILIPS|GE|SHIMADZU|TOSHIBA|HITACHI|CANON|CARESTREAM|FUJIFILM|MINDRAY|ALLENGERS|ECORAY)\b", all_text, re.I)
        unit_brand = m_kb.group(1).capitalize() if m_kb else ""
        if unit_brand.upper() == "GE":
            unit_brand = "GE"

    # 4. Unit Type / Model
    m_utype = re.search(
        r"(?:Product\s+Name|Nama\s+Alat|Equipment\s+Name|Unit\s+Type|Model(?:\s+Unit|\s+Alat)?|Jenis\s+Pesawat|Tipe\s+Unit)\s*[:=\-–]\s*([^\n\r]+)",
        all_text,
        re.I,
    )
    if m_utype:
        raw_ut = m_utype.group(1)
        raw_ut = re.sub(r"\s+(?:Serial Number|Nomor seri|InSpec|Subsystem|Product Number).*$", "", raw_ut, flags=re.I).strip()
        unit_type = clean_value(raw_ut).strip(" :;-,")
    else:
        m_ut_line = re.search(r"(?:Unit\s+Type|Equipment\s+Type)\s+([A-Za-z0-9 ]+?)(?:\s+(?:InSpec|Serial|Status)|$)", all_text, re.I)
        if m_ut_line:
            unit_type = clean_value(m_ut_line.group(1)).strip(" :;-,")
        else:
            m_ut_fallback = re.search(r"\b(Somatom\s+go[\. ]*(?:Top|Up|All|Now)?|Azurion\s+[0-9]\s+[A-Za-z0-9]+|Optima\s+XR[0-9A-Za-z]+|XR[0-9]+\s+[A-Z0-9]+)\b", all_text, re.I)
            unit_type = clean_value(m_ut_fallback.group(1)).strip(" :;-,") if m_ut_fallback else ""

    # 5. Unit Serial Number
    m_sb = re.search(r"\b(SB[0-9]{5,}[A-Z0-9]*)\b", all_text)
    m_usn = re.search(
        r"(?:Nomor\s+seri\s+alat|No\.?\s*Seri(?:\s+Alat|\s+Unit)?)\s*[:=\-–]\s*([A-Za-z0-9\-_]+)",
        all_text,
        re.I,
    )
    m_p_sn = re.search(r"(?:Product\s+Name[^\n]+)?Serial\s+Number\s*[:=\-–]?\s*([A-Za-z0-9\-_]+)", all_text, re.I)
    
    if m_sb:
        unit_serial = clean_value(m_sb.group(1)).strip(" :;-,")
    elif m_usn:
        unit_serial = clean_value(m_usn.group(1)).strip(" :;-,")
    elif m_p_sn and not re.search(r"^(?:Customer|Pelanggan|Equipment|if)\b", m_p_sn.group(1).strip(), re.I):
        unit_serial = clean_value(m_p_sn.group(1)).strip(" :;-,")
    else:
        m_sn_digits = re.search(r"(?:Serial\s+number|Nomor\s+seri)(?:[^\d\n]|[\n\r])*?(\d{2,})", all_text, re.I)
        unit_serial = m_sn_digits.group(1).strip() if m_sn_digits else ""

    unit_type_serial = f"{unit_type} / {unit_serial}".strip(" /")

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


def parse_document(doc_type, pages_text, tables=None):
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

        return {
            "document_type": doc_type,
            "fields": {
                "header": parsed.get("header", {}),
                "hospital_name": {**parsed["hospital_name"], "confidence": 1.0 if parsed["hospital_name"].get("value") else None},
                "hospital_address": {**parsed["hospital_address"], "confidence": 1.0 if parsed["hospital_address"].get("value") else None},
                "unit_brand": {"value": u_b, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_b else None},
                "unit_type": {"value": u_t, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_t else None},
                "unit_serial_number": {"value": u_s, "page": p_num, "method": "native_text_table", "confidence": 1.0 if u_s else None},
                "tube_brand": {"value": t_b, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_b else None},
                "tube_type": {"value": t_t, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_t else None},
                "tube_serial_number": {"value": t_s, "page": p_num, "method": "native_text_table", "confidence": 1.0 if t_s else None},
                "personnel_data": {"value": parsed["personnel_data"], "page": None, "method": "native_text_table", "confidence": 1.0 if parsed["personnel_data"] else None},
                "xray_data": {"value": clean_xray, "page": p_num, "method": "native_text_table", "confidence": 1.0 if any(clean_xray.values()) else None},
                "all_xray_rows": clean_all_rows or parsed.get("all_xray_rows", []),
            },
        }

    if doc_type == "ppkr":
        return {"document_type": doc_type, "fields": extract_ppkr_data(pages_text, tables)}

    if doc_type == "uji_kesesuaian":
        return {"document_type": doc_type, "fields": extract_uji_kesesuaian_data(pages_text, tables)}

    if doc_type == "persetujuan_import":
        return {"document_type": doc_type, "fields": extract_persetujuan_import_data(pages_text, tables)}

    if doc_type == "paparan_radiasi":
        return {"document_type": doc_type, "fields": extract_paparan_radiasi_data(pages_text, tables)}

    if doc_type == "uji_fungsi":
        return {"document_type": doc_type, "fields": extract_uji_fungsi_data(pages_text, tables)}

    generic_fields = [f for f in fields if f not in {"administrative_documents", "personnel_data", "xray_data", "table_of_contents"}]
    generic = extract_generic_fields(pages_text, generic_fields)
    special = {}

    if doc_type == "sip":
        special = {
            "person_name": _first_match(pages_text, [_rx("Nama")]),
            "profession": _first_match(pages_text, [_rx("Profesi|Keahlian")]),
            "valid_until": _first_match(pages_text, [r"(?:berlaku sampai(?: dengan)?|masa berlaku)[ \t]*:?([ \t]*)(.+)".replace("([ \\t]*)", "")]),
            "practice_location": _first_match(pages_text, [_rx("Alamat Praktik|Alamat Praktek|Tempat Praktik|Tempat Praktek")]),
        }
    elif doc_type == "sprint":
        kepada_match = _first_match(pages_text, [
            r"Kepada\s*[:\-–]?\s*(?:Nama\s*[:\-–]?\s*)?([^\n\r]+)",
            r"DIPERINTAHKAN\s*\n+\s*Kepada\s*[:\-–]?\s*([^\n\r]+)",
            _rx_optional_colon("Kepada|Nama PPR"),
        ])
        approval_match = _first_match(pages_text, [
            r"(?:Pengesahan|Disahkan|Pengesah|Tanda\s+Tangan(?:\s+dan\s+Stempel)?)[ \t]*:?[ \t]*(.+)",
            r"\b(dr\.?\s*[A-Za-z .,]+?(?:Sp\.[A-Za-z]+|M\.Kes|MARS)?)(?:\s+(?:Kepala|Mayor|NIP)|$)",
            r"(?:Kepala\s+Rumah\s+Sakit|Direktur)[^\n\r]*\n+([^\n\r]+)",
            _rx_optional_colon("Pengesahan|Disahkan|Pengesah|Tanda Tangan dan Stempel|Tanda Tangan|Stempel"),
        ])
        special = {
            "ppr_name": kepada_match,
            "approval": approval_match,
            "kepada": kepada_match,
            "pengesahan": approval_match,
        }
    elif doc_type == "sib":
        special = extract_sib_data(pages_text)
    elif doc_type == "spesifikasi_pesawat":
        unit_brand_field = _first_match(pages_text, [_rx_optional_colon("Merk|Merek|Manufacturer")])
        unit_type_field = _first_match(pages_text, [r"\b(?:Tipe|Type|Model)\b(?!\s*/\s*No\s*Seri)[ \t]*:?[ \t]*(.+)"])

        # Fallback for manufacturer brochure layouts (e.g. GE Healthcare, Shimadzu, Philips, etc.)
        if not unit_brand_field.get("value"):
            known_brands = [
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
                            unit_brand_field = {"value": kb, "page": p_idx, "method": "brochure_header"}
                            if not unit_type_field.get("value") and l_idx + 1 < len(lines):
                                cand_model = lines[l_idx + 1].strip("* •-")
                                if cand_model and not re.search(r"^(?:imagination|system|solution|hospital|healthcare|medical)\b", cand_model, re.I):
                                    unit_type_field = {"value": cand_model, "page": p_idx, "method": "brochure_title"}
                            break
                    if unit_brand_field.get("value"):
                        break
                if unit_brand_field.get("value"):
                    break

        if not unit_type_field.get("value"):
            for p_idx, p_txt in enumerate(pages_text[:2], start=1):
                m_model = re.search(r"\b(Optima[\s*]+[A-Za-z0-9]+|RADspeed[\s*]+[A-Za-z0-9]+|MobileDaRt[\s*]+[A-Za-z0-9]+|Definium[\s*]+[A-Za-z0-9]+|Multix[\s*]+[A-Za-z0-9]+|DigitalDiagnost[\s*]+[A-Za-z0-9]+)\b", p_txt, re.I)
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
        if not generic.get("person_name", {}).get("value"):
            all_txt = "\n".join(pages_text)
            names = [
                n.strip() for n in re.findall(r"^\s*\d+\.\s+([A-Za-z][A-Za-z '\.]+?)(?:\s+\(|$|\s+\d)", all_txt, re.M)
                if not re.search(r"kontrol|control", n, re.I)
            ]
            if names:
                doctor_candidate = next((n for n in names if re.search(r"adimas|dr\.", n, re.I)), names[0])
                special["person_name"] = {"value": doctor_candidate, "page": 1, "method": "native_text_regex"}
    elif doc_type == "sistem_manajemen":
        toc_page = _find_page_containing(pages_text, r"DAFTAR\s*ISI")
        special = {}
        generic["table_of_contents"] = {
            "value": _extract_toc(pages_text),
            "page": toc_page,
            "method": "native_text_section",
            "confidence": 1.0 if toc_page else None,
        }
    elif doc_type == "program_perawatan":
        special = {
            "conformity_test_clause": _first_match(pages_text, [
                r"((?:klausul|clause).{0,120}uji[ \t]+kesesuaian[^\n]*)",
                r"(uji[ \t]+kesesuaian[^\n]*)",
            ]),
        }

    merged = _merge(generic, special)
    for date_key in ("valid_until", "document_date"):
        item = merged.get(date_key)
        if isinstance(item, dict) and item.get("value"):
            item["value"] = normalize_date(item["value"])

    for k, item in merged.items():
        if isinstance(item, dict):
            if item.get("value") not in ("", None, []):
                if item.get("confidence") is None:
                    item["confidence"] = 1.0
            else:
                item["confidence"] = None

    return {"document_type": doc_type, "fields": merged}


def _find_page_containing(pages_text, needle_or_pattern):
    for idx, text in enumerate(pages_text, start=1):
        if re.search(needle_or_pattern, text, re.IGNORECASE):
            return idx
    return None


def _extract_toc(pages_text):
    page = _find_page_containing(pages_text, r"DAFTAR\s*ISI")
    if page is None:
        return ""
    lines = [line.strip() for line in pages_text[page - 1].splitlines() if line.strip()]
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
