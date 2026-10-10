import re
import pandas as pd
from rapidfuzz import fuzz

FIELD_MAP = [
    {"field": "unit_brand", "form_key": "unit_brand", "label_key": "unit_manufacturer"},
    {"field": "unit_type_serial", "form_key": "unit_type_serial", "label_key": "unit_desc_serial"},
    {"field": "tube_brand", "form_key": "tube_brand", "label_key": "tube_manufacturer"},
    {"field": "tube_type_serial", "form_key": "tube_type_serial", "label_key": "tube_insert_serial"},
    {"field": "max_kv", "form_key": "max_kv", "label_key": "max_voltage"},
    {"field": "max_ma", "form_key": "max_ma", "label_key": "max_current"},
]

SERIAL_FIELDS = {"unit_type_serial", "tube_type_serial"}
BRAND_FIELDS = {"unit_brand", "tube_brand"}

BRAND_ALIASES = {
    "GE": ["GENERAL ELECTRIC", "GE HEALTHCARE", "GE MEDICAL"],
    "CANON": ["CANON"],
}
BRAND_FULL_NAMES = {
    "GE": ["General Electric Company"],
    "CANON": ["Canon Electron Tubes & Devices Co., Ltd."],
}

SOURCE_PRIORITY = ("original", "preprocessed")
PREFER_LONGEST = {"unit_manufacturer", "tube_manufacturer"}
REQUIRED_FIELDS = [
    "unit_manufacturer",
    "unit_desc_serial",
    "tube_manufacturer",
    "tube_insert_serial",
    "max_voltage",
]


def normalize(value):
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def normalize_serial(value):
    return normalize(value).replace("O", "0").replace("I", "1")


def sort_by_y(ocr_lines):
    return sorted(ocr_lines, key=lambda l: l["y"])


def join_text(ocr_lines):
    return "\n".join(l["text"] for l in sort_by_y(ocr_lines))


def find_line(ocr_lines, pattern):
    for line in sort_by_y(ocr_lines):
        if re.search(pattern, line["text"], re.IGNORECASE):
            return line["text"].strip()
    return ""


def value_after_key(ocr_lines, key_pattern, y_tolerance=40):
    lines = sort_by_y(ocr_lines)
    for line in lines:
        m = re.search(key_pattern + r"\s*[:\-]?\s*(.*)$", line["text"], re.IGNORECASE)
        if m:
            inline_value = m.group(1).strip()
            if inline_value:
                return inline_value
            candidates = [
                c
                for c in lines
                if c is not line
                and c["x"] > line["x"]
                and abs(c["y"] - line["y"]) <= y_tolerance
            ]
            if candidates:
                return min(candidates, key=lambda c: c["x"])["text"].strip()
    return ""


def extract_number(text, unit):
    m = re.search(
        r"(\d+(?:\.\d+)?)[ \t]*" + unit + r"(?![A-Za-z])",
        text,
        re.IGNORECASE,
    )
    return f"{m.group(1)} {unit}" if m else ""


def extract_tube_model_serial(ocr_lines_sorted):
    texts = [l["text"] if isinstance(l, dict) else l for l in ocr_lines_sorted]
    model_lines = [t for t in texts if "MODEL" in t.upper()]
    serial_lines = [t for t in texts if re.search(r"SER\.?\s*NO", t, re.IGNORECASE)]

    def extract_value(line):
        if ":" in line:
            return line.split(":", 1)[-1].strip()
        parts = line.split()
        return parts[-1] if parts else ""

    pairs = {}
    if len(model_lines) >= 1:
        pairs["unit_model"] = extract_value(model_lines[0])
    if len(model_lines) >= 2:
        pairs["insert_model"] = extract_value(model_lines[1])
    if len(serial_lines) >= 1:
        pairs["unit_serial"] = extract_value(serial_lines[0])
    if len(serial_lines) >= 2:
        pairs["insert_serial"] = extract_value(serial_lines[1])
    return pairs


def extract_label_fields(tube_lines, unit_lines):
    tube_pairs = extract_tube_model_serial(sort_by_y(tube_lines))
    unit_desc = value_after_key(unit_lines, r"\bDESC\b")
    unit_sn = value_after_key(unit_lines, r"\bS\s*/\s*N\b")
    return {
        "unit_manufacturer": find_line(unit_lines, r"\b(COMPANY|LTD|INC|CORP|GMBH)\b"),
        "unit_desc_serial": f"{unit_desc} {unit_sn}".strip(),
        "tube_manufacturer": find_line(tube_lines, r"\b(COMPANY|LTD|INC|CORP|GMBH)\b"),
        "tube_insert_serial": f"{tube_pairs.get('insert_model', '')} {tube_pairs.get('insert_serial', '')}".strip(),
        "max_voltage": extract_number(value_after_key(tube_lines, r"MAX\.?\s*VOLTAGE"), "kV"),
        "max_current": extract_number(join_text(tube_lines) + "\n" + join_text(unit_lines), "mA"),
    }


def merge_candidates(candidates):
    merged = {}
    if not candidates:
        return merged
    keys = set()
    for source in candidates.values():
        keys.update(source.keys())
    for key in keys:
        values = [
            candidates[source].get(key, "")
            for source in SOURCE_PRIORITY
            if source in candidates and candidates[source].get(key, "")
        ]
        if not values:
            merged[key] = ""
        elif key in PREFER_LONGEST:
            merged[key] = max(values, key=len)
        else:
            merged[key] = values[0]
    return merged


def match_field(
    form_value,
    label_value,
    field="",
    match_threshold=90,
    review_threshold=60,
    brand_fuzzy_threshold=80,
):
    if not label_value or not str(label_value).strip():
        return None, "TIDAK ADA DI LABEL"

    norm = normalize_serial if field in SERIAL_FIELDS else normalize
    form_norm = norm(form_value)
    label_norm = norm(label_value)

    if field in BRAND_FIELDS:
        aliases = [form_norm] + [normalize(a) for a in BRAND_ALIASES.get(form_norm, [])]
        if any(len(a) >= 4 and a in label_norm for a in aliases):
            return 100, "SESUAI"
        best_partial = max(
            (fuzz.partial_ratio(a, label_norm) for a in aliases if len(a) >= 4),
            default=0,
        )
        if best_partial >= brand_fuzzy_threshold:
            return best_partial, "SESUAI"
        full_names = [normalize(n) for n in BRAND_FULL_NAMES.get(form_norm, [])]
        if len(label_norm) >= 8 and any(label_norm in n for n in full_names):
            return None, "PERLU VERIFIKASI"
    elif (
        form_norm
        and label_norm
        and min(len(form_norm), len(label_norm)) >= 4
        and (form_norm in label_norm or label_norm in form_norm)
    ):
        return 100, "SESUAI"

    score = fuzz.token_sort_ratio(form_norm, label_norm)
    if score >= match_threshold:
        status = "SESUAI"
    elif score >= review_threshold:
        status = "PERLU VERIFIKASI"
    else:
        status = "TIDAK SESUAI"
    return score, status


def run_matching(form_data, label_data, field_map=None):
    field_map = field_map or FIELD_MAP
    results = []
    for m in field_map:
        form_value = form_data.get(m["form_key"], "")
        label_value = label_data.get(m["label_key"], "")
        score, status = match_field(form_value, label_value, field=m["field"])
        results.append(
            {
                "field": m["field"],
                "form_value": form_value,
                "label_value": label_value,
                "score": score,
                "status": status,
            }
        )
    return pd.DataFrame(results)
