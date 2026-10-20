import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

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


def _score_facility_cand(cand: str, ref_name: str) -> float:
    if not cand or not ref_name:
        return 0.0
    c_norm = re.sub(r"[^A-Z0-9]", "", cand.upper())
    r_norm = re.sub(r"[^A-Z0-9]", "", ref_name.upper())
    if c_norm == r_norm or c_norm in r_norm or r_norm in c_norm:
        return 100.0
    from rapidfuzz import fuzz
    tsr = fuzz.token_set_ratio(cand.upper(), ref_name.upper())
    c_words = {w for w in re.findall(r"[A-Z0-9]+", cand.upper()) if w not in {"RS", "RSUD", "RSUP", "RSJ", "RSIA", "RUMAH", "SAKIT", "KLINIK", "DR", "DOKTER"}}
    r_words = {w for w in re.findall(r"[A-Z0-9]+", ref_name.upper()) if w not in {"RS", "RSUD", "RSUP", "RSJ", "RSIA", "RUMAH", "SAKIT", "KLINIK", "DR", "DOKTER"}}
    if c_words and r_words and c_words.intersection(r_words):
        return max(float(tsr), 85.0)
    return float(tsr)


def _score_addr_cand(cand: str, ref_addr: str) -> float:
    if not cand or not ref_addr:
        return 0.0
    c_words = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", cand) if len(w) >= 3 and w.lower() not in {"jalan", "jl", "nomor", "no", "rt", "rw", "kelurahan", "kel", "kecamatan", "kec", "kota", "kabupaten", "kab", "provinsi", "prov"}}
    r_words = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", ref_addr) if len(w) >= 3 and w.lower() not in {"jalan", "jl", "nomor", "no", "rt", "rw", "kelurahan", "kel", "kecamatan", "kec", "kota", "kabupaten", "kab", "provinsi", "prov"}}
    if not r_words or not c_words:
        return 0.0
    common = c_words.intersection(r_words)
    overlap = len(common) / len(r_words)
    return overlap * 100.0


def extract_facility_name(pages_text: List[str], context: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[int]]:
    """Robustly extracts hospital / facility name from text pages.

    1. Matches explicit labels with delimiter (e.g. 'Nama Rumah Sakit : XYZ', 'Instansi : XYZ').
    2. Searches header block, cover page, and Kop Surat on first 2 pages.
    3. Searches recipient blocks (e.g. 'Kepada: ... RS ...') on early pages only.
    4. When context (e.g. from Formulir Permohonan) is provided, candidate scoring prioritizes matching facility names.
    """
    candidates: List[Tuple[str, int, int]] = []  # (candidate_string, page_num, pass_priority)

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
                    candidates.append((val, p_idx, 1))

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
                    candidates.append((cand, p_idx + 1, 2))
            m = re.match(r"^(?:(?:RUMAH\s+SAKIT|RS|RUMKIT|RSUD|RSUP|KLINIK)\s+[A-Za-z0-9\s\.\-–]+)$", line, re.I)
            if m:
                cand = clean_value(m.group(0)).strip(" :;-,")
                cand = re.sub(r"\s+(?:Provinsi|Kabupaten|Kota)\b.*$", "", cand, flags=re.I).strip(" :;-,")
                cand = re.sub(r"\s+\d+$", "", cand).strip(" :;-,")
                if _is_valid_facility_candidate(cand):
                    candidates.append((cand, p_idx + 1, 2))

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
                    candidates.append((cand, p_idx + 1, 3))

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
                            candidates.append((val, p_idx + 1, 4))

    # Evaluate candidates with context guidance if reference hospital name is available
    ref_name = (context.get("hospital_name") or "").strip() if context else ""
    if ref_name and candidates:
        best_cand = max(candidates, key=lambda c: (_score_facility_cand(c[0], ref_name), -c[2]))
        if _score_facility_cand(best_cand[0], ref_name) >= 70.0:
            return best_cand[0], best_cand[1]

    # Search early pages for lines containing reference hospital keywords if candidates missed
    if ref_name:
        sig_words = [w for w in re.findall(r"[A-Za-z0-9]+", ref_name.upper()) if w not in {"RS", "RSUD", "RSUP", "RSJ", "RSIA", "RUMAH", "SAKIT", "KLINIK", "DR", "DOKTER"} and len(w) >= 3]
        if sig_words:
            for p_idx in range(min(3, len(pages_text or []))):
                for line in str(pages_text[p_idx] or "").splitlines():
                    line_u = line.upper()
                    if any(w in line_u for w in sig_words) and re.search(r"\b(?:RS|RUMAH\s+SAKIT|RSUD|RSJ|RSIA|KLINIK|RUMKIT)\b", line_u):
                        m_f = re.search(r"\b((?:RS|RUMAH\s+SAKIT|RSUD|RSJ|RSIA|KLINIK|RUMKIT)[ \t]+[A-Za-z0-9\.\-–]+(?:\s+[A-Za-z0-9\.\-–]+)*)", line, re.I)
                        if m_f:
                            cand = clean_value(m_f.group(1)).strip(" :;-,")
                            if _is_valid_facility_candidate(cand):
                                return cand, p_idx + 1

    if candidates:
        # Return first candidate by order of pass priority
        candidates.sort(key=lambda c: c[2])
        return candidates[0][0], candidates[0][1]

    return "", None


VENDOR_HEADER_ADDR_RE = re.compile(
    r"\b(?:Casablanca|Kasablanka|Office\s*88|Kav\.?\s*88|Tower\s+[A-Z]|(?:3[0-9]|2[0-9]|[1-9])th\s+Floor|Mega\s+Kuningan|Rasuna\s+Said|Sudirman\s+Central|SCBD|Gedung\s+Graha|World\s+Trade\s+Center|WTC|Menara\s+Kadin|PT\.?\s*(?:FUJIFILM|SIEMENS|PHILIPS|GE|SHIMADZU))\b",
    re.I,
)


def extract_facility_address(pages_text: List[str], context: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[int]]:
    """Extracts hospital / facility address from text pages with multi-line administrative continuation."""
    ref_addr = (context.get("hospital_address") or "").strip() if context else ""
    addr_candidates: List[Tuple[str, int]] = []

    label_patterns = [
        r"(?:Customer\s+Address|Hospital\s+Address|Alamat(?:\s+Rumah\s+Sakit|\s+RS|\s+Instansi|\s+Fasilitas|\s+Pelanggan)?|Address)\s*[:=\-–]?\s*([^\n\r]+)",
    ]
    for p_idx, page in enumerate(pages_text or [], start=1):
        for pat in label_patterns:
            for m in re.finditer(pat, page, re.IGNORECASE):
                val = clean_value(m.group(1))
                val = re.split(r"[\r\n]|\||Telp|Email|Fax|Tanggal", val, flags=re.IGNORECASE)[0].strip(" :;-,")
                val = re.split(
                    r"\b(?:Serial\s*No\.?|Serial\s+Number|Contact\s+Person|Installation\s+date|Warraty|Warranty|Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Mechanical|InSpec|Status|Brake|Batere|PASS|FAIL)\b",
                    val,
                    flags=re.I,
                )[0].strip(" :;-,")
                if len(val) >= 6 and not VENDOR_HEADER_ADDR_RE.search(val):
                    addr_candidates.append((val, p_idx))

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
                    r"\b(?:Serial\s*No\.?|Serial\s+Number|Contact\s+Person|Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Mechanical|InSpec|Status|Brake|Batere|PASS|FAIL)\b",
                    cand,
                    flags=re.I,
                )[0].strip(" :;-,")
                if len(cand) >= 8 and not re.search(r"^(?:Jl\.?|Jalan)\s*$", cand, re.I) and not VENDOR_HEADER_ADDR_RE.search(cand):
                    parts = [cand]
                    for next_l in lines[idx + 1: idx + 4]:
                        if re.search(r"^(?:Telp|Website|Email|Fax|LEMBAR|BAB|DAFTAR)\b", next_l, re.I):
                            break
                        if re.search(r"^(?:Halaman|Revisi|No\.?|Tanggal)\b", next_l, re.I):
                            continue
                        if re.search(r"\b(?:Kecamatan|Kec\.|Kelurahan|Kel\.|Kabupaten|Kab\.|Kota|Provinsi|RT|RW|\d{5})\b", next_l, re.I):
                            clean_next = clean_value(re.split(r"\||Telp|Email|Fax|website|Halaman", next_l, flags=re.I)[0]).strip(" :;-,")
                            if clean_next and not VENDOR_HEADER_ADDR_RE.search(clean_next):
                                parts.append(clean_next)
                    full_addr = ", ".join(parts)
                    full_addr = re.sub(r",\s*,", ",", full_addr)
                    if not VENDOR_HEADER_ADDR_RE.search(full_addr):
                        addr_candidates.append((full_addr, p_idx + 1))

    if ref_addr and addr_candidates:
        best_addr = max(addr_candidates, key=lambda a: _score_addr_cand(a[0], ref_addr))
        if _score_addr_cand(best_addr[0], ref_addr) >= 30.0:
            return best_addr[0], best_addr[1]

    if addr_candidates:
        return addr_candidates[0][0], addr_candidates[0][1]

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



def extract_person_name(pages_text: List[str], context: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[int]]:
    """Extracts doctor, specialist, or officer name while avoiding table header strings."""
    ref_names = []
    if context:
        for k in ("person_name", "ppr_name"):
            val = str(context.get(k) or "").strip()
            if val and val not in ("-", "—"):
                ref_names.append(val)

    person_candidates: List[Tuple[str, int]] = []

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
                    person_candidates.append((cand, p_idx + 1))

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
                        person_candidates.append((cand, p_idx + 1))

    if ref_names and person_candidates:
        from rapidfuzz import fuzz
        for cand, p_num in person_candidates:
            for rn in ref_names:
                if fuzz.token_set_ratio(cand.upper(), rn.upper()) >= 75:
                    return cand, p_num

    if person_candidates:
        return person_candidates[0][0], person_candidates[0][1]

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


def extract_generic_fields(pages_text: List[str], field_keys: List[str], context: Optional[Dict[str, Any]] = None) -> dict:
    """Rule-based extraction from PDF text pages.

    Uses specialized robust extractors for facility name, address, document number,
    and person name, avoiding common Indonesian administrative OCR / table collisions.
    When context is supplied, uses ground truth entities to guide extraction and resolve ambiguities.
    """
    result = {key: {"value": "", "page": None, "method": "native_text", "confidence": None} for key in field_keys}

    if "hospital_name" in field_keys:
        h_val, h_page = extract_facility_name(pages_text, context=context)
        if h_val:
            result["hospital_name"] = {
                "value": h_val,
                "page": h_page,
                "line": None,
                "method": "native_text_regex",
                "confidence": 1.0,
            }

    if "hospital_address" in field_keys:
        a_val, a_page = extract_facility_address(pages_text, context=context)
        if a_val:
            result["hospital_address"] = {
                "value": a_val,
                "page": a_page,
                "line": None,
                "method": "native_text_regex",
                "confidence": 1.0,
            }

    if "person_name" in field_keys:
        p_val, p_page = extract_person_name(pages_text, context=context)
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
                    value = despace_value(value).strip(" :;-,.")
                if key == "valid_until":
                    value = normalize_date(value)
                result[key] = {
                    "value": value,
                    "page": page_index,
                    "line": line_index,
                    "method": "native_text_regex",
                    "confidence": 1.0,
                }

    # Context-guided confirmation: if critical equipment fields are missing, check if context serials/types appear in text
    if context:
        equipment_guidance = [
            ("unit_serial_number", context.get("unit_serial_number")),
            ("tube_serial_number", context.get("tube_serial_number")),
            ("unit_brand", context.get("unit_brand")),
            ("unit_type", context.get("unit_type")),
            ("tube_brand", context.get("tube_brand")),
            ("tube_type", context.get("tube_type")),
        ]
        for field_k, ref_v in equipment_guidance:
            if field_k in field_keys and (not result[field_k]["value"] or result[field_k]["value"] in ("-", "—")):
                ref_str = str(ref_v or "").strip()
                if ref_str and ref_str not in ("-", "—") and len(ref_str) >= 3:
                    for p_idx, p_text in enumerate(pages_text, start=1):
                        p_str = str(p_text or "")
                        if re.search(r"\b" + re.escape(ref_str) + r"\b", p_str, re.I):
                            result[field_k] = {
                                "value": ref_str,
                                "page": p_idx,
                                "line": None,
                                "method": "context_guided_regex",
                                "confidence": 1.0,
                            }
                            break

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
