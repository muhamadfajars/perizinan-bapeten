import re
from typing import Iterable, List, Optional, Tuple

from src.matching.normalizer import normalize_date

FIELD_LABELS = {
    "hospital_name": ["Nama Rumah Sakit", "Nama RS", "Instansi", "Nama Fasilitas"],
    "hospital_address": ["Alamat Rumah Sakit", "Alamat RS", "Alamat Instansi", "Alamat Fasilitas"],
    "person_name": ["Nama Petugas", "Nama Personel", "Nama Pekerja", "Nama"],
    "profession": ["Profesi", "Keahlian", "Jenis Keahlian", "Klasifikasi"],
    "valid_until": ["Berlaku Sampai", "Berlaku Hingga", "Masa Berlaku", "Berlaku Sampai Dengan"],
    "practice_location": ["Tempat Praktik", "Alamat Praktik", "Tempat Praktek", "Alamat Praktek"],
    "ppr_name": ["Nama PPR", "Kepada", "Petugas Proteksi Radiasi"],
    "approval": ["Pengesahan", "Disahkan", "Pengesah"],
    "unit_brand": ["Merk pesawat sinar-X", "Merk Unit", "Merek Unit", "Merk Pesawat", "Merek Pesawat", "Manufacturer"],
    "unit_type": ["Tipe/model pesawat sinar-X", "Tipe Unit", "Type Unit", "Tipe Pesawat", "Model Unit", "Model Pesawat"],
    "unit_serial_number": ["No. Seri pesawat sinar-X", "No. Seri Pesawat", "Nomor Seri", "No. Seri", "Serial Number", "S/N", "SN"],
    "tube_brand": ["Merk Tabung", "Merek Tabung", "Tube Manufacturer"],
    "tube_type": ["Tipe Tabung", "Type Tabung", "Model Tabung", "Tipe / Model Tabung", "Tipe/Model Tabung", "Tube Model"],
    "tube_model": ["Model Tabung", "Tube Model"],
    "tube_serial_number": ["Nomor seri insersi tabung sinar X", "Nomor seri insersi", "Nomor Seri Tabung", "No. Seri Tabung", "No Seri Tabung", "Serial Number Tabung", "S/N Tabung", "Seri Tabung"],
    "usage_period": ["Periode Pemakaian", "Periode Penggunaan", "Periode"],
    "radiation_exposure_acceptance": ["Keberterimaan Paparan Radiasi", "Keberterimaan", "Kesimpulan", "Hasil Pengukuran"],
    "conformity_test_clause": ["Klausul Uji Kesesuaian", "Uji Kesesuaian", "Klausul"],
    "table_of_contents": ["Daftar Isi"],
}


def clean_value(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" :;-\t")
    return value


def despace_value(val: str) -> str:
    """Collapses spaces in artificially spaced characters (e.g. 'E7 8 7 6' -> 'E7876', '2 5 D0 6 1 0' -> '25D0610')."""
    s = str(val or "").strip()
    if not s or s in ("-", "—"):
        return s
    tokens = [t for t in re.split(r"\s+", s) if t]
    if len(tokens) >= 2 and all(len(t) <= 4 for t in tokens):
        if "-" in s:
            s_clean = re.sub(r"\s*-\s*", "-", s)
            sub_toks = s_clean.split()
            if all(len(t) <= 4 for t in sub_toks):
                collapsed = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[A-Za-z0-9])", "", s_clean)
                m = re.match(r"^(uDR|DR|Optima|XRR|Canon|GE)(\d.*)$", collapsed, re.I)
                if m:
                    return f"{m.group(1)} {m.group(2)}"
                return collapsed
        collapsed = "".join(tokens)
        m = re.match(r"^(uDR|DR|Optima|XRR)(\d.*)$", collapsed, re.I)
        if m:
            return f"{m.group(1)} {m.group(2)}"
        return collapsed
    return s


def _label_pattern(label: str) -> str:
    """Builds a regex pattern supporting wide-spaced kerning (e.g. 'T i p e   t a b u n g')."""
    parts = []
    for word in label.strip().split():
        chars = []
        for c in word:
            if c == ".":
                chars.append(r"\.?")
            elif c == "/":
                chars.append(r"[ \t]*/[ \t]*")
            else:
                chars.append(re.escape(c))
        parts.append(r"[ \t]*".join(chars))
    return r"[ \t]*".join(parts)


def find_labeled_value(text: str, labels: Iterable[str]) -> Tuple[str, Optional[int]]:
    lines = [line.strip() for line in str(text or "").splitlines()]
    for idx, line in enumerate(lines):
        for label in labels:
            pattern = _label_pattern(label)
            is_single = len(label.split()) == 1
            delim = r"[:\-–=]" if is_single else r"[:\-–=]?"
            m = re.search(rf"(?:^|\b){pattern}(?:\b|(?=[ \t:\-–=]))[ \t]*{delim}[ \t]*(.+)$", line, re.IGNORECASE)
            if not m:
                continue
            value = clean_value(m.group(1))
            if value and not re.match(r"^(?:kami|adalah|terkait|dalam|untuk|sesuai|yang|pada|bahwa|merupakan)\b", value, re.IGNORECASE):
                return value, idx
            if idx + 1 < len(lines):
                next_value = clean_value(lines[idx + 1])
                if next_value and not re.match(r"^(?:kami|adalah|terkait|dalam|untuk|sesuai|yang|pada|bahwa|merupakan)\b", next_value, re.IGNORECASE):
                    return next_value, idx + 1
    return "", None


BLACKLIST_FACILITY_FOLLOWING = {
    "kami", "adalah", "terkait", "dalam", "untuk", "sesuai", "yang", "pada",
    "bahwa", "merupakan", "kegiatan", "pelayanan", "mutu", "kebijakan", "pedoman",
    "sistem", "ruang", "kewajiban", "pelaporan", "mengenai", "dapat", "wajib",
    "harus", "ini", "tersebut", "secara", "akan", "telah", "dengan", "sebagai",
    "karena", "maupun", "serta", "oleh", "kepada", "terhadap", "bagi", "dan",
    "atau", "ke", "di", "dari", "juga", "masih", "belum", "bukan", "hanya",
    "bisa", "lebih", "sangat", "agar", "supaya", "tentang", "mengatur",
    "meliputi", "menjamin", "memastikan", "melakukan", "menyelenggarakan", "memiliki",
}


def _is_valid_facility_candidate(cand: str) -> bool:
    if not cand or len(cand) < 4:
        return False
    words = cand.split()
    if not words:
        return False
    prefix_len = 2 if words[0].lower() == "rumah" and len(words) > 1 and words[1].lower() == "sakit" else 1
    name_words = words[prefix_len:]
    if not name_words:
        return False
    if all(w.isdigit() for w in name_words):
        return False
    if name_words[0].lower() in BLACKLIST_FACILITY_FOLLOWING:
        return False
    return True


def extract_facility_name(pages_text: List[str]) -> Tuple[str, Optional[int]]:
    """Robustly extracts hospital / facility name from text pages.

    1. Matches explicit labels with delimiter (e.g. 'Nama Rumah Sakit : XYZ', 'Instansi : XYZ').
    2. Searches header block, cover page, and Kop Surat on first 2 pages.
    3. Searches recipient blocks (e.g. 'Kepada: ... RS ...') on early pages only.
    """
    # Pass 1: Explicit labels with delimiter
    for p_idx, page in enumerate(pages_text or [], start=1):
        lines = [l.strip() for l in str(page or "").splitlines() if l.strip()]
        for line in lines:
            m = re.search(
                r"^(?:Nama\s+)?(?:Rumah\s+Sakit|RS|Rumkit|Fasilitas|Faskes|Instansi|Institusi|Pemohon|Pelanggan|Customer)\s*[:=\-–]\s*([^\n\r]+)$",
                line,
                re.IGNORECASE,
            )
            if m:
                val = clean_value(m.group(1))
                val = re.split(r"\||Alamat|Telp|Email|Tanggal|Hal\b|Tube|PASS|FAIL|Mechanical|Collimator", val, flags=re.IGNORECASE)[0].strip(" :;-,")
                val = re.sub(r"\s+\d+$", "", val).strip(" :;-,")
                if _is_valid_facility_candidate(val):
                    return val, p_idx

    # Pass 2: Header box / prominent lines on first 2 pages
    for p_idx in range(min(2, len(pages_text or []))):
        page_str = str(pages_text[p_idx] or "")
        lines = [l.strip() for l in page_str.splitlines() if l.strip()]
        for line in lines[:25]:
            if re.search(r"^(?:SISTEM|PROGRAM|LEMBAR|BAB|DAFTAR|No\.?|Tanggal|Revisi|Halaman|Jl\.?|Jalan|Telp|Website)\b", line, re.I):
                continue
            m_dir = re.search(r"Direktur\s+((?:RS|RUMAH\s+SAKIT|RSUD|RSUP|KLINIK|RUMKIT)\s+[A-Za-z0-9\s\.\-–]+)$", line, re.I)
            if m_dir:
                cand = clean_value(m_dir.group(1)).strip(" :;-,")
                if _is_valid_facility_candidate(cand):
                    return cand, p_idx + 1
            m = re.match(r"^(?:(?:RUMAH\s+SAKIT|RS|RUMKIT|RSUD|RSUP|KLINIK)\s+[A-Za-z0-9\s\.\-–]+)$", line, re.I)
            if m:
                cand = clean_value(m.group(0)).strip(" :;-,")
                cand = re.sub(r"\s+(?:Provinsi|Kabupaten|Kota)\b.*$", "", cand, flags=re.I).strip(" :;-,")
                cand = re.sub(r"\s+\d+$", "", cand).strip(" :;-,")
                if _is_valid_facility_candidate(cand):
                    return cand, p_idx + 1

    # Pass 3: General regex on early pages (skipping table of contents & generic context)
    for p_idx in range(min(2, len(pages_text or []))):
        page_str = str(pages_text[p_idx] or "")
        if re.search(r"\bDAFTAR\s+ISI\b", page_str, re.I) and not re.search(r"\bLEMBAR\s+PENGESAHAN\b", page_str, re.I):
            continue
        lines = [l.strip() for l in page_str.splitlines() if l.strip()]
        for line in lines:
            if re.match(r"^(?:Direktur|Kepala|Wakil|Staff|Staf|Kebijakan|Pedoman|Integrasi|Sistem|Menimbang|Mengingat|Dasar|Untuk|Kepada|Bab\b|[0-9IVX]+\.)\b", line, re.I):
                continue
            if re.search(r"\b(?:di|pada|oleh|bagi|ke|antara|pimpinan|tata\s+kelola|akreditasi|mutu|kebijakan)\s+(?:rumah\s+sakit|rs)\b", line, re.I):
                continue
            m = re.search(r"\b((?:RUMAH\s+SAKIT|RUMKIT|RSUD|RSUP|RS\b|KLINIK\b)[ \t]+[A-Za-z0-9\.\-–]+(?:\s+[A-Za-z0-9\.\-–]+)*)", line, re.I)
            if m:
                cand = clean_value(m.group(1))
                cand = re.sub(r"\s+(?:Provinsi|Kabupaten|Kota)\b.*$", "", cand, flags=re.I).strip(" :;-,")
                cand = re.sub(r"\s+\d+$", "", cand).strip(" :;-,")
                if _is_valid_facility_candidate(cand):
                    return cand, p_idx + 1

    # Pass 4: Recipient blocks (only on first 2 pages)
    for p_idx in range(min(2, len(pages_text or []))):
        lines = [l.strip() for l in str(pages_text[p_idx] or "").splitlines() if l.strip()]
        for idx, line in enumerate(lines[:15]):
            if re.search(r"^Kepada(?:\s+Yth\.?)?\b", line, re.IGNORECASE):
                for next_line in lines[idx + 1: idx + 4]:
                    if re.match(r"^(?:Kepala|Direktur|Mayor|dr\.)\b", next_line, re.IGNORECASE):
                        continue
                    m_rs = re.search(r"\b((?:RS|RUMAH\s+SAKIT|RSUD|RSUP|RUMKIT|KLINIK)\s+[A-Za-z0-9\.\-–]+(?:\s+[A-Za-z0-9\.\-–]+)*)", next_line, re.IGNORECASE)
                    if m_rs:
                        val = clean_value(m_rs.group(1)).strip(" :;-,")
                        val = re.sub(r"\s+\d+$", "", val).strip(" :;-,")
                        if _is_valid_facility_candidate(val):
                            return val, p_idx + 1

    return "", None


def extract_facility_address(pages_text: List[str]) -> Tuple[str, Optional[int]]:
    """Extracts hospital / facility address from text pages with multi-line administrative continuation."""
    label_patterns = [
        r"(?:Alamat(?:\s+Rumah\s+Sakit|\s+RS|\s+Instansi|\s+Fasilitas)?)\s*[:=\-–]\s*([^\n\r]+)",
    ]
    for p_idx, page in enumerate(pages_text or [], start=1):
        for pat in label_patterns:
            for m in re.finditer(pat, page, re.IGNORECASE):
                val = clean_value(m.group(1))
                val = re.split(r"[\r\n]|\||Telp|Email|Fax|Tanggal", val, flags=re.IGNORECASE)[0].strip(" :;-,")
                val = re.split(
                    r"\b(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Mechanical|InSpec|Status|Brake|Batere|PASS|FAIL)\b",
                    val,
                    flags=re.I,
                )[0].strip(" :;-,")
                if len(val) >= 6:
                    return val, p_idx

    # Look for Jl. or Jalan in first 3 pages
    for p_idx in range(min(3, len(pages_text or []))):
        lines = [l.strip() for l in str(pages_text[p_idx] or "").splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            m = re.search(r"\b((?:Jl\.?|Jalan)\s*[^\r\n|]+)", line, re.I)
            if m:
                cand = clean_value(m.group(1))
                cand = re.split(
                    r"\||Telp|Email|Fax|Kode\s*Pos|website|Halaman|\b08\d{2}[-\s]?\d{3,4}|\b\d{4}[-\s]\d{4}|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                    cand,
                    flags=re.I,
                )[0].strip(" :;-,")
                cand = re.split(
                    r"\b(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Mechanical|InSpec|Status|Brake|Batere|PASS|FAIL)\b",
                    cand,
                    flags=re.I,
                )[0].strip(" :;-,")
                if len(cand) >= 8 and not re.search(r"^(?:Jl\.?|Jalan)\s*$", cand, re.I):
                    parts = [cand]
                    for next_l in lines[idx + 1: idx + 4]:
                        if re.search(r"^(?:Telp|Website|Email|Fax|LEMBAR|BAB|DAFTAR)\b", next_l, re.I):
                            break
                        if re.search(r"^(?:Halaman|Revisi|No\.?|Tanggal)\b", next_l, re.I):
                            continue
                        if re.search(r"\b(?:Kecamatan|Kec\.|Kelurahan|Kel\.|Kabupaten|Kab\.|Kota|Provinsi|RT|RW|\d{5})\b", next_l, re.I):
                            clean_next = clean_value(re.split(r"\||Telp|Email|Fax|website|Halaman", next_l, flags=re.I)[0]).strip(" :;-,")
                            if clean_next:
                                parts.append(clean_next)
                    full_addr = ", ".join(parts)
                    full_addr = re.sub(r",\s*,", ",", full_addr)
                    return full_addr, p_idx + 1

    return "", None


def find_document_number(text: str) -> str:
    """Finds document number with strict boundary checks to avoid street address numbers or DIAGNOSTIK."""
    lines = [l.strip() for l in str(text or "").splitlines() if l.strip()]
    for line in lines:
        if re.search(r"(?:^|\b)(?:Jl\.?|Jalan|Kampung|Kav|Blok)\b", line, re.IGNORECASE):
            continue
        patterns = [
            r"(?:^|[\t|;])\s*(?:Nomor|No\.?)\s*(?:Dokumen|Doc(?:ument)?)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_ -]{2,})",
            r"\b(?:DOC(?:UMENT)?\s*NO\.?|DOCUMENT\s*NUMBER)\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_ -]{2,})",
            r"\b(?:Nomor|No\.?)\s*[:\-]\s*([A-Z0-9][A-Z0-9./_ -]{2,})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                val = clean_value(match.group(1))
                val = re.split(r"[\r\n]|Tanggal|Revisi|Hal\b|Lamp\b", val, flags=re.IGNORECASE)[0].strip(" :;-")
                if ("/" in val or "-" in val or re.search(r"[A-Za-z]+.*\d|\d+.*[A-Za-z]", val)) and len(val) >= 4:
                    return val
    return ""



def extract_person_name(pages_text: List[str]) -> Tuple[str, Optional[int]]:
    """Extracts doctor, specialist, or officer name while avoiding table header strings."""
    # Pass 1: Look for doctor title patterns
    for p_idx in range(min(3, len(pages_text or []))):
        lines = [l.strip() for l in str(pages_text[p_idx] or "").splitlines() if l.strip()]
        for line in lines:
            m = re.search(
                r"\b(dr\.?\s*[A-Za-z .,]+?(?:Sp\.[A-Za-z]+|M\.Kes|A\.Md\.[A-Za-z]+)?)(?:\s+(?:Kepala|Mayor|NIP|Jabatan)|$)",
                line,
                re.IGNORECASE,
            )
            if m:
                cand = clean_value(m.group(1)).strip(" ,")
                if len(cand) >= 5 and not re.search(r"Jabatan|Tanggal|Tanda", cand, re.IGNORECASE):
                    return cand, p_idx + 1

    # Pass 2: Look for labeled person names, rejecting table headers
    for p_idx in range(min(3, len(pages_text or []))):
        lines = [l.strip() for l in str(pages_text[p_idx] or "").splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            if re.search(r"^(?:No\.?|Nama)\s+(?:Jabatan|Tanda\s*Tangan|Tanggal|Keterangan)\b", line, re.IGNORECASE):
                continue
            m = re.search(r"\b(?:Nama\s+Petugas|Nama\s+Personel|Nama\s+Pekerja|Kepada|Nama)\s*[:=\-–]\s*([^\n\r]+)", line, re.IGNORECASE)
            if m:
                cand = clean_value(m.group(1)).strip(" ,")
                if not re.search(r"\b(?:Jabatan|Tanda\s*Tangan|Tanggal|Status|Keterangan)\b", cand, re.IGNORECASE):
                    if len(cand) >= 3:
                        return cand, p_idx + 1

    return "", None


def extract_numbered_list_or_block(text: str, heading_labels: Iterable[str], stop_labels: Iterable[str] = ()) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    for idx, line in enumerate(lines):
        if any(re.search(_label_pattern(label), line, re.IGNORECASE) for label in heading_labels):
            collected = []
            first = clean_value(re.sub(r"^.*?(?:[:\-])\s*", "", line))
            if first and not any(first.lower() == label.lower() for label in heading_labels):
                collected.append(first)
            for next_line in lines[idx + 1:]:
                if stop_labels and any(re.search(_label_pattern(label), next_line, re.IGNORECASE) for label in stop_labels):
                    break
                value = clean_value(next_line)
                if value:
                    collected.append(value)
                if len(collected) >= 40:
                    break
            return " ".join(collected).strip()
    return ""


def extract_generic_fields(pages_text: List[str], field_keys: List[str]) -> dict:
    """Rule-based extraction from PDF text pages.

    Uses specialized robust extractors for facility name, address, document number,
    and person name, avoiding common Indonesian administrative OCR / table collisions.
    """
    result = {key: {"value": "", "page": None, "method": "native_text", "confidence": None} for key in field_keys}

    if "hospital_name" in field_keys:
        h_val, h_page = extract_facility_name(pages_text)
        if h_val:
            result["hospital_name"] = {
                "value": h_val,
                "page": h_page,
                "line": None,
                "method": "native_text_regex",
                "confidence": 1.0,
            }

    if "hospital_address" in field_keys:
        a_val, a_page = extract_facility_address(pages_text)
        if a_val:
            result["hospital_address"] = {
                "value": a_val,
                "page": a_page,
                "line": None,
                "method": "native_text_regex",
                "confidence": 1.0,
            }

    if "person_name" in field_keys:
        p_val, p_page = extract_person_name(pages_text)
        if p_val:
            result["person_name"] = {
                "value": p_val,
                "page": p_page,
                "line": None,
                "method": "native_text_regex",
                "confidence": 1.0,
            }

    for page_index, page_text in enumerate(pages_text, start=1):
        for key in field_keys:
            if result[key]["value"]:
                continue

            if key in {"hospital_name", "hospital_address", "person_name"}:
                continue
            elif key in FIELD_LABELS:
                value, line_index = find_labeled_value(page_text, FIELD_LABELS[key])
            else:
                value, line_index = "", None

            if value:
                if key in {"unit_type", "unit_serial_number", "tube_type", "tube_model", "tube_serial_number"}:
                    value = despace_value(value)
                if key == "valid_until":
                    value = normalize_date(value)
                result[key] = {
                    "value": value,
                    "page": page_index,
                    "line": line_index,
                    "method": "native_text_regex",
                    "confidence": 1.0,
                }

    return result


def extract_raw_blocks(pages_text: List[str], field_keys: List[str]) -> dict:
    """Best-effort block extraction for source fields intentionally defined as groups."""
    result = {key: {"value": "", "page": None, "method": "native_text_block", "confidence": None} for key in field_keys}

    for page_index, page_text in enumerate(pages_text, start=1):
        if not page_text:
            continue
        upper = page_text.upper()
        for key in field_keys:
            if result[key]["value"]:
                continue
            labels = FIELD_LABELS.get(key, [])
            for label in labels:
                pos = upper.find(label.upper())
                if pos < 0:
                    continue
                tail = page_text[pos + len(label):]
                tail = re.sub(r"^[\s:：-]+", "", tail)
                lines = [clean_value(x) for x in tail.splitlines()[:12] if clean_value(x)]
                value = " ".join(lines)
                if value:
                    result[key] = {
                        "value": value,
                        "page": page_index,
                        "method": "native_text_block",
                        "confidence": 1.0,
                    }
                    break

    return result
