import re
import pandas as pd
from rapidfuzz import fuzz
from src.matching.label_matcher import normalize

INDONESIAN_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5,
    "juni": 6, "juli": 7, "agustus": 8, "september": 9,
    "oktober": 10, "november": 11, "desember": 12,
}


def normalize_date(text):
    text = text or ""
    m = re.search(r"(\d{1,2})\s*([A-Za-z]+)\s*(\d{4})", text)
    if m:
        day, month_name, year = m.groups()
        month = INDONESIAN_MONTHS.get(month_name.lower())
        if month:
            return f"{int(day):02d}/{month:02d}/{year}"
    m2 = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text)
    if m2:
        d, mo, y = m2.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    return text.strip()


def match_institution(check, exact_threshold=90, partial_threshold=70):
    form_value, other_value = check["form_value"], check["other_value"]
    if not form_value or not other_value:
        return None, "TIDAK ADA DI DOKUMEN"
    f_norm, o_norm = normalize(form_value), normalize(other_value)
    if check["compare"] == "exact":
        score, threshold = fuzz.ratio(f_norm, o_norm), exact_threshold
    else:
        score, threshold = fuzz.partial_ratio(f_norm, o_norm), partial_threshold
    if score >= threshold:
        status = "SESUAI"
    elif score >= threshold - 20:
        status = "PERLU VERIFIKASI"
    else:
        status = "TIDAK SESUAI"
    return score, status


def match_personnel(form_people, ppkr_people, exact_threshold=90, review_threshold=70):
    results = []
    for fp in form_people:
        form_norm = normalize(fp["name"])
        if not ppkr_people:
            results.append({
                "form_npr": fp.get("npr", ""), "form_name": fp["name"], "form_role": fp["role"],
                "ppkr_name": "", "ppkr_role": "", "score": None,
                "status": "TIDAK ADA DI DOKUMEN",
            })
            continue
        best = max(ppkr_people, key=lambda p: fuzz.partial_ratio(form_norm, normalize(p["name"])))
        score = fuzz.partial_ratio(form_norm, normalize(best["name"]))
        status = "SESUAI" if score >= exact_threshold else "PERLU VERIFIKASI" if score >= review_threshold else "TIDAK SESUAI"
        results.append({
            "form_npr": fp.get("npr", ""), "form_name": fp["name"], "form_role": fp["role"],
            "ppkr_name": best["name"], "ppkr_role": best["role_title"],
            "score": score, "status": status,
        })
    return pd.DataFrame(results)
