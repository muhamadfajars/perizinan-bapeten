import re

INDONESIAN_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
}


def normalize(value):
    if value is None or str(value).strip() in ("-", "—"):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def normalize_serial(value):
    # Conservative OCR normalization used only for serial-like fields.
    return normalize(value).replace("O", "0").replace("I", "1")


def normalize_date(text):
    text = str(text or "").strip()
    if not text or text in ("-", "—"):
        return "-"
    m = re.search(r"(\d{1,2})\s*([A-Za-z]+)\s*(\d{4})", text)
    if m:
        day, month_name, year = m.groups()
        month = INDONESIAN_MONTHS.get(month_name.lower())
        if month:
            return f"{int(day):02d}/{month:02d}/{year}"

    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"

    m = re.search(r"(\d{1,2})\s*[-.]\s*(\d{1,2})\s*[-.]\s*(\d{4})", text)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"

    m = re.search(r"(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", text)
    if m:
        y, mo, d = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"

    return text


# Common academic, professional, and medical titles in Indonesia
TITLE_PATTERNS = [
    r"\b(?:DR|DRG|PROF|DOKTER)\b\.?",
    r"\bSP\.?\s*[A-Z]+(?:\s*\([A-Za-z0-9]+\))?\.?",
    r"\bA\.?MD\.?\s*(?:RAD|KES|AK)?\b\.?",
    r"\bS\.?TR\.?\s*(?:KES|RAD)?\b\.?",
    r"\bS\.?SI\b\.?",
    r"\bM\.?SI\b\.?",
    r"\bM\.?\s*KES\b\.?",
    r"\bS\.?KM\b\.?",
    r"\bS\.?KEP\b\.?",
    r"\bNERS\b\.?",
    r"\bST\b\.?",
]

ADDRESS_REPLACEMENTS = [
    (r"\bJALAN\b", "JL"),
    (r"\bNOMOR\b", "NO"),
    (r"\bKELURAHAN\b", "KEL"),
    (r"\bKECAMATAN\b", "KEC"),
    (r"\bKABUPATEN\b", "KAB"),
    (r"\bPROVINSI\b", "PROV"),
    (r"\bKOMPLEK\b", "KOMP"),
    (r"\bKAVELING\b", "KAV"),
    (r"\bGEDUNG\b", "GDG"),
    (r"\bKAMPUNG\b", "KP"),
    (r"\bKOTA\b", ""),
]

BRAND_CANONICAL_MAP = {
    "SHIMADZU": ["SHIMADZU", "SHIMADZU CORPORATION", "SHIMADZU CORP"],
    "GE": ["GE", "GENERAL ELECTRIC", "GENERAL ELECTRIC COMPANY", "GE HEALTHCARE", "GE MEDICAL"],
    "SIEMENS": ["SIEMENS", "SIEMENS HEALTHCARE", "SIEMENS HEALTHINEERS", "SIEMENS AG"],
    "PHILIPS": ["PHILIPS", "PHILIPS HEALTHCARE", "PHILIPS MEDICAL SYSTEMS", "KONINKLIJKE PHILIPS"],
    "CANON": ["CANON", "CANDN", "CANON MEDICAL", "CANON MEDICAL SYSTEMS", "CANON ELECTRON TUBES & DEVICES", "CANON ELECTRON TUBES & DEVICES CO., LTD."],
    "TOSHIBA": ["TOSHIBA", "TOSHIBA MEDICAL", "TOSHIBA MEDICAL SYSTEMS"],
    "HITACHI": ["HITACHI", "HITACHI MEDICAL"],
    "CARESTREAM": ["CARESTREAM", "CARESTREAM HEALTH"],
    "FUJIFILM": ["FUJIFILM", "FUJI", "FUJI MEDICAL"],
    "HOLOGIC": ["HOLOGIC", "HOLOGIC INC"],
    "VATECH": ["VATECH", "VATECH CO., LTD.", "VATECH GLOBAL"],
    "VARIAN": ["VARIAN", "VARIAN MEDICAL SYSTEMS"],
    "DUNLEE": ["DUNLEE", "DUNLEE HEALTHCARE"],
    "ALLENGERS": ["ALLENGERS", "ALLENGERS MEDICAL SYSTEMS"],
    "UNITED IMAGING": ["UNITED IMAGING", "UNITED IMAGING HEALTHCARE", "SHANGHAI UNITED IMAGING HEALTHCARE", "SHANGHAI UNITED IMAGING HEALTHCARE CO., LTD.", "SHANGHAI UNITED IMAGING HEALTHCARE CO., LTD", "SHANGHAI UNITED IMAGING HEALTHCARE CO LTD", "UIH"],
}


def normalize_person_name(name: str) -> str:
    """Removes medical and academic titles to compare base names accurately."""
    if not name:
        return ""
    text = f" {name} "
    for pattern in TITLE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    # Remove remaining punctuation, parentheses, and digits
    cleaned = re.sub(r"[^A-Za-z\s]", " ", text).upper()
    return " ".join(cleaned.split())


def normalize_address(address: str) -> str:
    """Normalizes road, block, administrative abbreviations, and spacing in addresses."""
    if not address:
        return ""
    text = str(address).strip()

    # Strip test inspection checklist tokens (e.g. Collimator Rotation PASS, Tube tilt PASS)
    text = re.sub(r"\s*\b(?:COLLIMATOR(?:\s+ROTATION)?|TUBE(?:\s+TILT)?|MECHANICAL|INSPEC|BRAKE|BATERE|STATUS)\s*(?:PASS|FAIL)?\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\b(?:PASS|FAIL)\b.*$", "", text, flags=re.IGNORECASE)

    # 1. Strip facility prefix if address starts with hospital/facility name before comma or street marker
    # e.g. 'Rumkit Tentara Tk IV 01.07.04 Pekanbaru, Jl. Kesehatan No. 2 Kampung'
    p_fac = r"^(?:RUMAH\s+SAKIT|RUMKIT|RSU|RSUD|RSUP|RSIA|RS|KLINIK|PUSKESMAS|BALAI|PT|CV)\b.*?(?:[,;\-]|\b(?=JL|JALAN\b))\s*"
    text = re.sub(p_fac, "", text, flags=re.IGNORECASE).strip()

    # Unglue OCR typo where 'no' or 'n' or 'nn' is glued with 0, dots, or digits e.g. Kesehatann0.02 -> Kesehatan NO 2
    text = re.sub(r"([A-Za-z]+?)nn0*\.?0*([1-9]\d*)\b", r"\1n NO \2", text, flags=re.IGNORECASE)

    # 2. Unglue punctuation between alphanumerics (e.g. Jl.Kesehatan -> Jl . Kesehatan, no.02 -> no . 02)
    text = re.sub(r"([A-Za-z0-9])([.,/-])([A-Za-z0-9])", r"\1 \2 \3", text)

    # 3. Unglue camelCase (e.g. PekanbaruRiau -> Pekanbaru Riau)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)

    # 4. Unglue word ending with 'no' or 'nomor' before digits or punctuation (e.g. Kesehatanno2 -> Kesehatan no 2)
    text = re.sub(r"([A-Za-z]{3,})(no|nomor)(\s*[\d.]|\b)", r"\1 \2 \3", text, flags=re.IGNORECASE)

    # 5. Unglue letters and digits (e.g. no2 -> no 2, RT01 -> RT 01)
    text = re.sub(r"([A-Za-z])(\d)", r"\1 \2", text)
    text = re.sub(r"(\d)([A-Za-z])", r"\1 \2", text)

    text = text.upper()
    for pattern, repl in ADDRESS_REPLACEMENTS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    # Remove non-alphanumeric punctuation
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", text)
    cleaned = " ".join(cleaned.split())

    # 6. Normalize leading zeros in administrative / street numbers (e.g. NO 02 -> NO 2, RT 01 -> RT 1)
    cleaned = re.sub(r"\bNO\s*0+([1-9]\d*)\b", r"NO \1", cleaned)
    cleaned = re.sub(r"\bRT\s*0+([1-9]\d*)\b", r"RT \1", cleaned)
    cleaned = re.sub(r"\bRW\s*0+([1-9]\d*)\b", r"RW \1", cleaned)

    return cleaned


def normalize_brand(brand: str) -> str:
    """Maps vendor/brand variations to canonical brand name."""
    if not brand:
        return ""
    norm = normalize(brand)
    for canonical, aliases in BRAND_CANONICAL_MAP.items():
        for alias in aliases:
            if norm == normalize(alias) or normalize(alias) in norm:
                return canonical
    return norm


def normalize_facility_name(name: str) -> str:
    """Normalizes hospital / facility name abbreviations (e.g. Rumah Sakit / Rumkit -> RS, Tingkat -> TK)."""
    if not name:
        return ""
    text = str(name).upper()
    # Strip test inspection checklist tokens (e.g. Tube tilt PASS, Collimator Rotation PASS)
    text = re.sub(r"\b(?:TUBE(?:\s+TILT)?|COLLIMATOR(?:\s+ROTATION)?|COLIMATOR|MECHANICAL|INSPEC|BRAKE|BATERE|STATUS)\s*(?:PASS|FAIL)?\b.*$", "", text)
    text = re.sub(r"\b(?:PASS|FAIL)\b.*$", "", text)
    # Strip military unit / detachment codes e.g. 01.07.04 or 01 07 04
    text = re.sub(r"\b\d{2}[\s.]\d{2}[\s.]\d{2}\b", "", text)
    text = re.sub(r"\bRUMAH\s+SAKIT\b|\bRUMKIT\b", "RS", text)
    text = re.sub(r"\bRSU\b|\bRSUD\b|\bRSUP\b|\bRSIA\b", "RS", text)
    text = re.sub(r"\bTINGKAT\b", "TK", text)
    # Normalize military hospital descriptor
    text = re.sub(r"\bRS\s+TENTARA\b", "RS", text)
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", text)
    return " ".join(cleaned.split())
