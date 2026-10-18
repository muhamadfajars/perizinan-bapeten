from collections import defaultdict

from rapidfuzz import fuzz

from config import BRAND_ALIASES, BRAND_FULL_NAMES, MATCH_THRESHOLD, REVIEW_THRESHOLD, BRAND_FUZZY_THRESHOLD, ADDRESS_MATCH_THRESHOLD
from src.matching.normalizer import (
    normalize,
    normalize_serial,
    normalize_address,
    normalize_facility_name,
    normalize_person_name,
)
from src.schema.fields import CROSS_CHECK_RULES

STATUS_OK = "SESUAI"
STATUS_WARNING = "WARNING"
STATUS_MISMATCH = "TIDAK SESUAI"
STATUS_REVIEW = "PERLU REVIEW"
STATUS_MISSING = "TIDAK DITEMUKAN"


def compare_values(left, right, mode="fuzzy_text"):
    left = str(left or "").strip()
    right = str(right or "").strip()
    if not left or not right:
        return None, STATUS_MISSING

    if mode == "serial":
        l_norm = normalize_serial(left)
        r_norm = normalize_serial(right)
        if l_norm == r_norm:
            return 100.0, STATUS_OK
        score = fuzz.ratio(l_norm, r_norm)
        # Serial fields are stricter: a close OCR result is a review, not auto-acceptance.
        if score >= 92:
            return score, STATUS_WARNING
        if score >= REVIEW_THRESHOLD:
            return score, STATUS_REVIEW
        return score, STATUS_MISMATCH

    l_norm = normalize(left)
    r_norm = normalize(right)

    if l_norm == r_norm:
        return 100.0, STATUS_OK

    if mode == "brand":
        aliases = {l_norm, r_norm}
        left_aliases = {normalize(x) for x in BRAND_ALIASES.get(l_norm, [])}
        right_aliases = {normalize(x) for x in BRAND_ALIASES.get(r_norm, [])}
        if aliases & (left_aliases | right_aliases):
            return 100.0, STATUS_OK
        for canonical, names in BRAND_FULL_NAMES.items():
            all_names = {normalize(canonical), *(normalize(n) for n in names)}
            if l_norm in all_names and r_norm in all_names:
                return 100.0, STATUS_OK
        score = fuzz.partial_ratio(l_norm, r_norm)
        if score >= BRAND_FUZZY_THRESHOLD:
            return score, STATUS_WARNING
        if score >= REVIEW_THRESHOLD:
            return score, STATUS_REVIEW
        return score, STATUS_MISMATCH

    if mode == "facility_name":
        l_fac = normalize_facility_name(left)
        r_fac = normalize_facility_name(right)
        if l_fac == r_fac or l_fac.replace(" ", "") == r_fac.replace(" ", ""):
            return 100.0, STATUS_OK
        l_nospace = l_fac.replace(" ", "")
        r_nospace = r_fac.replace(" ", "")
        score = max(
            fuzz.token_sort_ratio(l_fac, r_fac),
            fuzz.token_set_ratio(l_fac, r_fac),
            fuzz.ratio(l_fac, r_fac),
            fuzz.ratio(l_nospace, r_nospace),
        )
        if (
            fuzz.token_set_ratio(l_fac, r_fac) >= 80.0
            or fuzz.ratio(l_fac, r_fac) >= 80.0
            or fuzz.ratio(l_nospace, r_nospace) >= 80.0
            or score >= MATCH_THRESHOLD
        ):
            return score, STATUS_OK
        if score >= REVIEW_THRESHOLD:
            return score, STATUS_REVIEW
        return score, STATUS_MISMATCH

    if mode == "fuzzy_name":
        l_name = normalize_person_name(left)
        r_name = normalize_person_name(right)
        if l_name == r_name:
            return 100.0, STATUS_OK
        score = fuzz.token_sort_ratio(l_name, r_name)
        if score >= MATCH_THRESHOLD:
            return score, STATUS_OK
        if score >= REVIEW_THRESHOLD:
            return score, STATUS_REVIEW
        return score, STATUS_MISMATCH

    score = fuzz.token_sort_ratio(l_norm, r_norm)

    if mode == "fuzzy_address":
        l_addr = normalize_address(left)
        r_addr = normalize_address(right)
        if l_addr == r_addr:
            return 100.0, STATUS_OK
        score = max(
            fuzz.token_sort_ratio(l_addr, r_addr),
            fuzz.partial_ratio(l_addr, r_addr),
            fuzz.token_set_ratio(l_addr, r_addr),
        )
        if max(fuzz.token_set_ratio(l_addr, r_addr), fuzz.partial_ratio(l_addr, r_addr)) >= 75.0:
            return 100.0, STATUS_OK
        if score >= 75.0 or score >= ADDRESS_MATCH_THRESHOLD:
            return score, STATUS_OK
        if score >= REVIEW_THRESHOLD:
            return score, STATUS_REVIEW
        return score, STATUS_MISMATCH

    if score >= MATCH_THRESHOLD:
        return score, STATUS_OK
    if score >= REVIEW_THRESHOLD:
        return score, STATUS_REVIEW
    return score, STATUS_MISMATCH


def _field_values(document_result, field):
    """Return all values for a canonical field, including source-defined group fields."""
    fields = document_result.get("fields", {})
    direct = fields.get(field, {})
    values = []
    if isinstance(direct, dict):
        value = direct.get("value", "")
    else:
        value = direct or ""
    if value not in ("", [], None):
        values.append({"value": value, "page": direct.get("page") if isinstance(direct, dict) else None})

    people = fields.get("personnel_data", {})
    if field in {"person_name", "ppr_name", "profession"} and isinstance(people, dict):
        for person in people.get("value", []) if isinstance(people.get("value"), list) else []:
            if field == "person_name" and person.get("name"):
                values.append({"value": person["name"], "page": people.get("page")})
            elif field == "profession" and person.get("role"):
                values.append({"value": person["role"], "page": people.get("page")})
            elif field == "ppr_name" and person.get("name") and "PPR" in str(person.get("role", "")).upper():
                values.append({"value": person["name"], "page": people.get("page")})

    # Remove exact duplicates while preserving source order.
    unique = []
    seen = set()
    for item in values:
        marker = (str(item.get("value")), item.get("page"))
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def cross_check(extractions, rules=None):
    rules = rules or CROSS_CHECK_RULES
    rows = []
    for rule in rules:
        available = []
        for doc_type in rule["documents"]:
            for item in extractions.get(doc_type, []):
                for field_value in _field_values(item, rule["field"]):
                    available.append({
                        "document_type": doc_type,
                        "file_name": item.get("file_name", ""),
                        "value": field_value["value"],
                        "page": field_value.get("page"),
                    })

        if len(available) < 2:
            rows.append({
                "rule_id": rule["rule_id"],
                "field": rule["field"],
                "reference": available[0]["value"] if available else "",
                "compared_document": "",
                "compared_value": "",
                "score": None,
                "status": STATUS_MISSING,
                "evidence": available,
            })
            continue

        reference = available[0]
        for other in available[1:]:
            score, status = compare_values(reference["value"], other["value"], rule["mode"])
            rows.append({
                "rule_id": rule["rule_id"],
                "field": rule["field"],
                "reference_document": reference["document_type"],
                "reference_value": reference["value"],
                "compared_document": other["document_type"],
                "compared_value": other["value"],
                "score": round(score, 2) if score is not None else None,
                "status": status,
                "evidence": [reference, other],
            })

    return rows


def build_status_summary(cross_checks, extraction_items=None, presence=None):
    summary = defaultdict(int)
    for row in cross_checks:
        summary[row["status"]] += 1
    return dict(summary)
