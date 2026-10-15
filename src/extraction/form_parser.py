"""Parser for BAPETEN Formulir Permohonan documents.

Extracts header, administrative requirements, personnel table (multiple radiation workers),
and equipment generator table (multiple X-ray units & tubes) with page attribution.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from config import FORM_GENERATOR_TABLE_INDEX
from src.extraction.generic_parser import extract_generic_fields, clean_value
from src.schema.evidence import ExtractedField, EvidenceSource
from src.schema.entities import (
    ApplicationEntity,
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayEquipmentEntity,
    XRayTubeEntity,
    AdministrativeDocument,
)

FORM_HEADER_LABELS = [
    "Nomor Registrasi", "Tanggal Registrasi", "Lingkup Kegiatan",
    "Instansi", "Alamat Instansi", "Nama Proyek", "Alamat Proyek",
]


def normalize_form_table_cell(value: Any) -> str:
    if not isinstance(value, str):
        return str(value or "")
    return re.sub(r"\s*\n\s*", " ", value).strip()


def split_type_and_serial(type_serial_raw: str) -> Tuple[str, str]:
    """Split compound 'Tipe / No. Seri' cell value into (type_name, serial_number).

    Handles patterns such as:
    - 'RADspeed Pro / SB2002000027WK'
    - 'RADspeed Pro\\nSN: SB2002000027WK'
    - 'Optima XR646 (SN-998877)'
    """
    if not type_serial_raw:
        return "", ""
    text = type_serial_raw.strip()

    # Pattern: Model (SN: 123) or Model (123)
    paren_match = re.search(
        r"^(.+?)\s*\(\s*(?:(?:SN|S/N|NO\.?|SER(?:IAL)?)\s*[:\s]\s*)?([^)]+)\)$",
        text,
        re.IGNORECASE,
    )
    if paren_match:
        return paren_match.group(1).strip(), paren_match.group(2).strip()

    # Check for slash, newline, semicolon, or explicit SN keyword
    parts = re.split(
        r"\s*(?:/|\n|;\s*|\bSN\s*[:\-]?\s*|\bS/N\s*[:\-]?\s*|\bSER(?:IAL)?(?:\s+(?:NO|NUMBER))?\.?\s*[:\-]?\s*)\s*",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if len(parts) == 2:
        return parts[0].strip(" ()"), parts[1].strip(" ()")

    return text, ""


def split_project_address(raw_alamat_proyek: str) -> Tuple[str, str]:
    """Splits raw Alamat Proyek from BAPETEN Formulir Permohonan into (nama_instansi, alamat_instansi).

    In BAPETEN Formulir Permohonan:
    - The facility / hospital name is the leading prefix of 'Alamat Proyek' (before street address).
    - The facility address is the remaining part (street, RT/RW, subdistrict, city, etc.).

    Examples:
    - 'RS. Hermina Kepanjen, Jalan Raya Mojosari , RT 02/RW 01, Kel. Mojosari, Kec. Kepanjen , Kab. Malang, Jawa Timur'
      -> ('RS. Hermina Kepanjen', 'Jalan Raya Mojosari , RT 02/RW 01, Kel. Mojosari, Kec. Kepanjen , Kab. Malang, Jawa Timur')
    - 'Rumah Sakit Jiwa Aceh, Jl. Dr. T. Syarief Thayeb No. 25 , Kota Banda Aceh Aceh 23126, Telp.0651-32010...'
      -> ('Rumah Sakit Jiwa Aceh', 'Jl. Dr. T. Syarief Thayeb No. 25 , Kota Banda Aceh Aceh 23126, Telp.0651-32010...')
    - 'Klinik Insan Utama Balikpapan, Jl. Mayor TNI AD Ahmad Saili , Kota Balikpapan Kalimantan Timur 76124...'
      -> ('Klinik Insan Utama Balikpapan', 'Jl. Mayor TNI AD Ahmad Saili , Kota Balikpapan Kalimantan Timur 76124...')
    - 'RS Tk. IV Pekanbaru, Jl. Kesehatan No. 2 , Kota Pekanbaru Riau'
      -> ('RS Tk. IV Pekanbaru', 'Jl. Kesehatan No. 2 , Kota Pekanbaru Riau')
    """
    if not raw_alamat_proyek:
        return "", ""

    text = clean_value(str(raw_alamat_proyek))
    if not text:
        return "", ""

    street_indicators = r"^(?:Jl\.?|Jalan|Dusun|Desa|Komplek|Kav\.?|Gedung|Blok|RT\b|RW\b|No\.)\b"

    # Strategy 1: Split on first comma if text contains comma
    if "," in text:
        parts = text.split(",", 1)
        cand_name = parts[0].strip()
        cand_addr = parts[1].strip()
        if cand_name and not re.match(street_indicators, cand_name, re.IGNORECASE):
            return cand_name, cand_addr
        return "", text

    # Strategy 2: If no comma, check if a street indicator keyword separates name and address
    m = re.search(
        r"^(.*?)\s+(?=(?:Jl\.?|Jalan|Dusun|Desa|Komplek|Kav\.?|Gedung|Blok|RT\s*\d|RW\s*\d)\b)(.+)$",
        text,
        re.IGNORECASE,
    )
    if m:
        cand_name = m.group(1).strip().rstrip(",")
        cand_addr = m.group(2).strip()
        if cand_name and not re.match(street_indicators, cand_name, re.IGNORECASE):
            return cand_name, cand_addr

    return "", text



def resolve_generator_columns(table: list) -> Dict[str, Any]:
    """Dynamically identifies column indices from table header row(s).

    Inspects header text so column order and single/multi-level headers
    can vary freely without breaking extraction.
    """
    if not table or not table[0]:
        return {}

    row0 = [str(c or "").strip().upper() for c in table[0]]
    row1 = [str(c or "").strip().upper() for c in table[1]] if len(table) > 1 else []

    is_two_level = (
        any("PESAWAT" in c or "TABUNG" in c for c in row0)
        and any("MERK" in c or "TIPE" in c for c in row1)
    )

    combined_headers = []
    if is_two_level:
        current_section = ""
        for i in range(max(len(row0), len(row1))):
            h0 = row0[i] if i < len(row0) else ""
            if h0:
                current_section = h0
            h1 = row1[i] if i < len(row1) else ""
            combined_headers.append(f"{current_section} {h1}".strip())
    else:
        combined_headers = row0

    def find_col(include_all: List[str], exclude_any: Optional[List[str]] = None) -> Optional[int]:
        for idx, col_text in enumerate(combined_headers):
            if all(inc in col_text for inc in include_all):
                if exclude_any and any(exc in col_text for exc in exclude_any):
                    continue
                return idx
        return None

    # Dynamic resolution for unit (pesawat) columns
    u_brand = find_col(["MERK"], exclude_any=["TABUNG"])
    u_ts = find_col(["TIPE", "SERI"], exclude_any=["TABUNG"])
    u_t = find_col(["TIPE"], exclude_any=["TABUNG", "SERI"])
    u_s = find_col(["SERI"], exclude_any=["TABUNG", "TIPE"])

    # Dynamic resolution for tube (tabung) columns
    t_brand = find_col(["TABUNG", "MERK"]) or find_col(["MERK", "TABUNG"])
    t_ts = find_col(["TABUNG", "TIPE", "SERI"]) or find_col(["TABUNG", "SERI"])
    t_t = find_col(["TABUNG", "TIPE"], exclude_any=["SERI"])
    t_s = find_col(["TABUNG", "SERI"], exclude_any=["TIPE"])

    max_c = (
        find_col(["KONDISI"])
        or find_col(["KV"])
        or find_col(["MA"])
        or find_col(["TEGANGAN"])
    )

    # Fallback to positional columns if table has no identifiable text headers
    if u_brand is None and u_ts is None and u_t is None:
        u_brand = 1
        u_ts = 2
        t_brand = 3
        t_ts = 4
        max_c = 5

    return {
        "unit_brand": u_brand,
        "unit_type_serial": u_ts,
        "unit_type": u_t,
        "unit_serial": u_s,
        "tube_brand": t_brand,
        "tube_type_serial": t_ts,
        "tube_type": t_t,
        "tube_serial": t_s,
        "max_condition": max_c,
        "start_row": 2 if is_two_level else 1,
    }


def parse_all_generator_rows(tables: List[Tuple[int, list]]) -> List[Dict[str, Any]]:
    """Locates and parses all rows from generator tables across all pages dynamically."""
    rows_found = []
    if not tables:
        return rows_found

    for page_idx, table in tables:
        if not table or len(table) < 2:
            continue
        header_text = " ".join(str(c or "") for c in table[0]).upper()
        if any(kw in header_text for kw in ["GENERATOR", "PESAWAT", "TABUNG", "MERK", "TABUNG SINAR"]):
            col_map = resolve_generator_columns(table)
            start_row = col_map.get("start_row", 1)

            for row in table[start_row:]:
                if not row or not any(row):
                    continue
                row_str = " ".join(str(c or "") for c in row).upper()
                if "MERK" in row_str and "TIPE" in row_str:
                    continue

                def cell(idx: Optional[int]) -> str:
                    if idx is not None and idx < len(row) and row[idx]:
                        return normalize_form_table_cell(row[idx])
                    return ""

                unit_brand = cell(col_map.get("unit_brand"))
                u_ts = cell(col_map.get("unit_type_serial"))
                u_t = cell(col_map.get("unit_type"))
                u_s = cell(col_map.get("unit_serial"))

                if not u_t and not u_s and u_ts:
                    u_t, u_s = split_type_and_serial(u_ts)

                tube_brand = cell(col_map.get("tube_brand"))
                t_ts = cell(col_map.get("tube_type_serial"))
                t_t = cell(col_map.get("tube_type"))
                t_s = cell(col_map.get("tube_serial"))

                if not t_t and not t_s and t_ts:
                    t_t, t_s = split_type_and_serial(t_ts)

                max_condition = cell(col_map.get("max_condition"))

                if not any([unit_brand, u_ts, u_t, u_s, tube_brand, t_ts, t_t, t_s]):
                    continue

                rows_found.append({
                    "unit_index": len(rows_found) + 1,
                    "unit_brand": unit_brand,
                    "unit_type_serial": u_ts or f"{u_t} / {u_s}".strip(" /"),
                    "unit_type": u_t,
                    "unit_serial_number": u_s,
                    "tube_brand": tube_brand,
                    "tube_type_serial": t_ts or f"{t_t} / {t_s}".strip(" /"),
                    "tube_type": t_t,
                    "tube_serial_number": t_s,
                    "page": page_idx + 1 if page_idx is not None else None,
                })

    return rows_found


def parse_generator_table(tables: List[Tuple[int, list]], table_index: int = FORM_GENERATOR_TABLE_INDEX) -> Dict[str, Any]:
    """Backward-compatible single generator extractor, returning primary generator row."""
    all_rows = parse_all_generator_rows(tables)
    if all_rows:
        return all_rows[0]

    if not tables:
        return {
            "unit_brand": "", "unit_type_serial": "", "unit_type": "", "unit_serial_number": "",
            "tube_brand": "", "tube_type_serial": "", "tube_type": "", "tube_serial_number": "",
            "page": None,
        }

    try:
        page_idx, target_table = tables[table_index]
        data_row = target_table[1]
    except (IndexError, TypeError, KeyError):
        return {
            "unit_brand": "", "unit_type_serial": "", "unit_type": "", "unit_serial_number": "",
            "tube_brand": "", "tube_type_serial": "", "tube_type": "", "tube_serial_number": "",
            "page": None,
        }

    u_ts = normalize_form_table_cell(data_row[2]) if len(data_row) > 2 else ""
    t_ts = normalize_form_table_cell(data_row[4]) if len(data_row) > 4 else ""
    u_type, u_serial = split_type_and_serial(u_ts)
    t_type, t_serial = split_type_and_serial(t_ts)

    return {
        "unit_brand": normalize_form_table_cell(data_row[1]) if len(data_row) > 1 else "",
        "unit_type_serial": u_ts,
        "unit_type": u_type,
        "unit_serial_number": u_serial,
        "tube_brand": normalize_form_table_cell(data_row[3]) if len(data_row) > 3 else "",
        "tube_type_serial": t_ts,
        "tube_type": t_type,
        "tube_serial_number": t_serial,
        "page": page_idx + 1 if page_idx is not None else None,
    }


def _table_to_people(table: list, page_num: Optional[int] = None) -> List[Dict[str, Any]]:
    if not table or not table[0]:
        return []
    header = [(h or "").strip().upper() for h in table[0]]

    def idx(*patterns):
        for i, h in enumerate(header):
            if any(p in h for p in patterns):
                return i
        return None

    name_idx = idx("NAMA")
    role_idx = idx("JABATAN", "KLASIFIKASI", "KEAHLIAN", "PROFESI", "ROLE", "POSISI")

    people = []
    for row in table[1:]:
        if not row:
            continue
        def cell(i):
            return clean_value(row[i]) if i is not None and i < len(row) and row[i] else ""
        name = cell(name_idx)
        role = cell(role_idx)
        if name and not re.search(r"^(?:Nomor|NRP|NIK|STR|SIP|Masa|Tanggal|Halaman)\b", name, re.I):
            people.append({
                "name": name,
                "role": role,
                "page": page_num,
            })
    return people


def parse_people_tables(tables: List[Tuple[int, list]]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for page_idx, table in tables:
        if not table or not table[0]:
            continue
        full_table_text = " ".join(str(c or "") for row in table for c in row).upper()
        if "NAMA" not in full_table_text and "NPR" not in full_table_text and "KLASIFIKASI" not in full_table_text and "PROFESI" not in full_table_text and "JABATAN" not in full_table_text:
            continue
        page_num = page_idx + 1 if page_idx is not None else None

        # Check if table is a vertical key-value list (e.g. PPKR page 8)
        if "NAMA :" in full_table_text or "NAMAPEMEGANGIZIN" in full_table_text or "NAMA PEMEGANG" in full_table_text:
            current_role = ""
            for row in table:
                row_str = " ".join(clean_value(c) for c in row if c).strip()
                if not row_str:
                    continue
                m_role = re.match(r"^(?:\d+\.?\s*)?(Dokter\s*spesialis[^\n\r:]*|Petugas\s*Proteksi\s*Radiasi|Radiografer|Fisikawan\s*Medik|PPR)\b", row_str, re.I)
                if m_role:
                    current_role = clean_value(m_role.group(1))
                    continue
                m_pemegang = re.search(r"Nama\s*Pemegang\s*Izin\s*:\s*([A-Za-z .,\'\-]+)", row_str, re.I)
                if m_pemegang:
                    cand = clean_value(m_pemegang.group(1))
                    if len(cand) >= 3 and (cand, "Pemegang Izin") not in seen:
                        seen.add((cand, "Pemegang Izin"))
                        result.append({"name": cand, "role": "Pemegang Izin", "page": page_num})
                    continue
                m_nama = re.search(r"\bNama\s*:\s*([A-Za-z .,\'\-]+)", row_str, re.I)
                if m_nama:
                    cand = clean_value(m_nama.group(1))
                    if len(cand) >= 3 and not re.search(r"^(?:Petugas|Dokter|Radiografer|Rumah)\b", cand, re.I):
                        if (cand, current_role) not in seen:
                            seen.add((cand, current_role))
                            result.append({"name": cand, "role": current_role, "page": page_num})
            continue

        for person in _table_to_people(table, page_num=page_num):
            key = (person.get("name", ""), person.get("role", ""))
            if key not in seen and person.get("name"):
                seen.add(key)
                result.append(person)
    return result


def extract_admin_documents(tables: List[Tuple[int, list]]) -> List[Dict[str, Any]]:
    """Administrative documents on formulir are not extracted per user requirements."""
    return []


def extract_form_data(tables: List[Tuple[int, list]], pages_text_or_full_text: Any) -> Dict[str, Any]:
    pages_text = pages_text_or_full_text if isinstance(pages_text_or_full_text, list) else [pages_text_or_full_text]

    generic = extract_generic_fields(
        pages_text,
        ["hospital_name", "hospital_address"],
    )

    header_aliases = {
        "registration_number": [r"Nomor Registrasi\s*:\s*(.+)"],
        "registration_date": [r"Tanggal Registrasi\s*:\s*(.+)"],
        "scope": [r"Lingkup Kegiatan\s*:\s*(.+)"],
        "institution_name": [r"Instansi\s*:\s*(.+)"],
        "institution_address": [
            r"Alamat Instansi\s*:\s*([\s\S]+?)(?=\n\s*(?:Nama Proyek|[A-Z]\.|\Z))",
            r"Alamat Instansi\s*:\s*(.+)",
        ],
        "project_name": [r"Nama Proyek\s*:\s*(.+)"],
        "project_address": [
            r"Alamat Proyek\s*:\s*([\s\S]+?)(?=\n\s*(?:[A-Z]\.\s*Kelengkapan|[A-Z]\.|\bNomor Registrasi\b|\Z))",
            r"Alamat Proyek\s*:\s*(.+)",
        ],
    }
    header = {}
    for key, patterns in header_aliases.items():
        value = ""
        page = None
        for page_index, page_text in enumerate(pages_text, start=1):
            for pattern in patterns:
                m = re.search(pattern, page_text, re.IGNORECASE)
                if m:
                    value = clean_value(m.group(1))
                    page = page_index
                    break
            if value:
                break
        header[key] = {"value": value, "page": page, "method": "native_text_regex"}

    all_generator_rows = parse_all_generator_rows(tables)
    primary_generator = all_generator_rows[0] if all_generator_rows else parse_generator_table(tables)

    # For facility on formulir:
    # Nama instansi dan Alamat instansi acuan diambil dari Alamat Proyek:
    # - Awalan Alamat Proyek -> Nama Instansi / Fasilitas (hospital_name)
    # - Sisanya -> Alamat Instansi / Fasilitas (hospital_address)
    proj_addr_obj = header.get("project_address", {})
    proj_addr_val = proj_addr_obj.get("value", "")
    proj_addr_page = proj_addr_obj.get("page", 1)

    split_name, split_addr = split_project_address(proj_addr_val)

    if split_name:
        form_hospital_name = {
            "value": split_name,
            "page": proj_addr_page,
            "line": None,
            "method": "project_address_prefix",
            "confidence": 1.0,
        }
    elif header.get("institution_name", {}).get("value"):
        inst_name_obj = header["institution_name"]
        form_hospital_name = {
            "value": inst_name_obj["value"],
            "page": inst_name_obj.get("page", 1),
            "line": None,
            "method": "header_institution_name",
            "confidence": 1.0,
        }
    elif header.get("project_name", {}).get("value"):
        proj_name_obj = header["project_name"]
        form_hospital_name = {
            "value": proj_name_obj["value"],
            "page": proj_name_obj.get("page", 1),
            "line": None,
            "method": "header_project_name",
            "confidence": 1.0,
        }
    else:
        form_hospital_name = generic["hospital_name"]

    if split_addr:
        form_hospital_address = {
            "value": split_addr,
            "page": proj_addr_page,
            "line": None,
            "method": "project_address_suffix",
            "confidence": 1.0,
        }
    elif proj_addr_val:
        form_hospital_address = {
            "value": proj_addr_val,
            "page": proj_addr_page,
            "line": None,
            "method": "header_project_address",
            "confidence": 1.0,
        }
    elif header.get("institution_address", {}).get("value"):
        inst_addr_obj = header["institution_address"]
        form_hospital_address = {
            "value": inst_addr_obj["value"],
            "page": inst_addr_obj.get("page", 1),
            "line": None,
            "method": "header_institution_address",
            "confidence": 1.0,
        }
    else:
        form_hospital_address = generic["hospital_address"]

    return {
        "header": header,
        "hospital_name": form_hospital_name,
        "hospital_address": form_hospital_address,
        "administrative_documents": [],
        "personnel_data": parse_people_tables(tables),
        "xray_data": primary_generator,
        "all_xray_rows": all_generator_rows,
        "ppkr_reference": {},
    }


def build_application_from_form(
    parsed_form: Dict[str, Any],
    file_name: str = "Formulir_Permohonan.pdf",
) -> ApplicationEntity:
    """Constructs a typed ApplicationEntity from parsed form dictionary."""
    header = parsed_form.get("header", {})
    reg_num = header.get("registration_number", {}).get("value")
    reg_date = header.get("registration_date", {}).get("value")
    scope = header.get("scope", {}).get("value")

    # Facility: Nama instansi dan alamat instansi diambil dari Alamat Proyek (project_address)
    # Prefix Alamat Proyek -> Nama Instansi / Fasilitas (project_name)
    # Sisanya -> Alamat Fasilitas (project_address)
    h_name_val = parsed_form.get("hospital_name", {}).get("value") if isinstance(parsed_form.get("hospital_name"), dict) else parsed_form.get("hospital_name")
    h_name_page = parsed_form.get("hospital_name", {}).get("page") if isinstance(parsed_form.get("hospital_name"), dict) else 1

    h_addr_val = parsed_form.get("hospital_address", {}).get("value") if isinstance(parsed_form.get("hospital_address"), dict) else parsed_form.get("hospital_address")
    h_addr_page = parsed_form.get("hospital_address", {}).get("page") if isinstance(parsed_form.get("hospital_address"), dict) else 1

    if not h_name_val:
        proj_addr_val = header.get("project_address", {}).get("value", "")
        split_n, _ = split_project_address(proj_addr_val)
        h_name_val = split_n or header.get("institution_name", {}).get("value") or header.get("project_name", {}).get("value") or ""
        h_name_page = header.get("project_address", {}).get("page") or 1

    if not h_addr_val:
        proj_addr_val = header.get("project_address", {}).get("value", "")
        _, split_a = split_project_address(proj_addr_val)
        h_addr_val = split_a or proj_addr_val or header.get("institution_address", {}).get("value") or ""
        h_addr_page = header.get("project_address", {}).get("page") or 1

    facility = FacilityEntity(
        id="facility_1",
        project_name=ExtractedField[str].from_value(
            value=h_name_val,
            document_type="formulir",
            file_name=file_name,
            page=h_name_page,
            extraction_method="project_address_prefix",
        ),
        project_address=ExtractedField[str].from_value(
            value=h_addr_val,
            document_type="formulir",
            file_name=file_name,
            page=h_addr_page,
            extraction_method="project_address_suffix",
        ),
        institution_name=ExtractedField[str].from_value(
            value=header.get("institution_name", {}).get("value"),
            document_type="formulir",
            file_name=file_name,
            page=header.get("institution_name", {}).get("page"),
            extraction_method="native_text_regex",
        ) if header.get("institution_name", {}).get("value") else None,
        institution_address=ExtractedField[str].from_value(
            value=header.get("institution_address", {}).get("value"),
            document_type="formulir",
            file_name=file_name,
            page=header.get("institution_address", {}).get("page"),
            extraction_method="native_text_regex",
        ) if header.get("institution_address", {}).get("value") else None,
    )

    # Personnel and PPR
    personnel_list: List[PersonnelEntity] = []
    ppr_list: List[PPREntity] = []

    for idx, p in enumerate(parsed_form.get("personnel_data", []), start=1):
        name = p.get("name", "")
        role = p.get("role", "")
        npr = p.get("npr", "")
        page = p.get("page")

        person = PersonnelEntity(
            id=f"person_{idx}",
            name=ExtractedField[str].from_value(
                value=name,
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ),
            profession=ExtractedField[str].from_value(
                value=role,
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ),
            npr=ExtractedField[str].from_value(
                value=npr,
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ) if npr else None,
        )
        personnel_list.append(person)

        if "PPR" in role.upper():
            ppr = PPREntity(
                id=f"ppr_{len(ppr_list) + 1}",
                name=ExtractedField[str].from_value(
                    value=name,
                    document_type="formulir",
                    file_name=file_name,
                    page=page,
                    extraction_method="table_cell",
                ),
            )
            ppr_list.append(ppr)

    # X-Ray Equipment
    equipment_list: List[XRayEquipmentEntity] = []
    all_rows = parsed_form.get("all_xray_rows", [])
    if isinstance(all_rows, dict) and "value" in all_rows:
        all_rows = all_rows["value"]
    if not all_rows:
        xr = parsed_form.get("xray_data", {})
        if isinstance(xr, dict) and "value" in xr and isinstance(xr["value"], dict):
            xr = xr["value"]
        all_rows = [xr] if xr else []

    for idx, row in enumerate(all_rows, start=1):
        if not isinstance(row, dict) or not any(row.values()):
            continue
        page = row.get("page")

        # Tube
        tube = None
        if any([row.get("tube_brand"), row.get("tube_type"), row.get("tube_serial_number")]):
            tube = XRayTubeEntity(
                id=f"tube_{idx}",
                tube_brand=ExtractedField[str].from_value(
                    value=row.get("tube_brand"),
                    document_type="formulir",
                    file_name=file_name,
                    page=page,
                    extraction_method="table_cell",
                ),
                tube_type=ExtractedField[str].from_value(
                    value=row.get("tube_type") or row.get("tube_type_serial"),
                    document_type="formulir",
                    file_name=file_name,
                    page=page,
                    extraction_method="table_cell",
                ),
                tube_model=ExtractedField[str].from_value(
                    value=row.get("tube_type"),
                    document_type="formulir",
                    file_name=file_name,
                    page=page,
                    extraction_method="table_cell",
                ),
                tube_serial_number=ExtractedField[str].from_value(
                    value=row.get("tube_serial_number"),
                    document_type="formulir",
                    file_name=file_name,
                    page=page,
                    extraction_method="table_cell",
                ),
            )

        eq = XRayEquipmentEntity(
            id=f"unit_{idx}",
            unit_brand=ExtractedField[str].from_value(
                value=row.get("unit_brand"),
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ),
            unit_type=ExtractedField[str].from_value(
                value=row.get("unit_type") or row.get("unit_type_serial"),
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ),
            unit_serial_number=ExtractedField[str].from_value(
                value=row.get("unit_serial_number"),
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ),
            max_condition=ExtractedField[str].from_value(
                value=row.get("max_condition"),
                document_type="formulir",
                file_name=file_name,
                page=page,
                extraction_method="table_cell",
            ) if row.get("max_condition") else None,
            tube=tube,
        )
        equipment_list.append(eq)

    # Administrative documents
    admin_docs = [
        AdministrativeDocument(
            requirement=doc.get("requirement", ""),
            document_number=doc.get("document_number"),
            document_date=doc.get("document_date"),
        )
        for doc in parsed_form.get("administrative_documents", [])
    ]

    return ApplicationEntity(
        application_id=reg_num or "APP-DRAFT",
        registration_number=reg_num,
        registration_date=reg_date,
        scope=scope,
        facility=facility,
        personnel=personnel_list,
        ppr=ppr_list,
        xray_equipment=equipment_list,
        administrative_documents=admin_docs,
    )
