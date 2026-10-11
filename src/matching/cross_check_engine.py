"""Multi-Entity Cross-Check and Document Matching Engine.

Executes hierarchical cross-checks across multiple entities:
- Facility identity (Name & Address across all supporting documents)
- Personnel (Individual evaluations for each Personel + SIP + TLD)
- PPR (Individual evaluations for each PPR + SIB + Sprint)
- X-Ray Equipment (Individual evaluations for each Unit + Label + Tube + Specs)
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from rapidfuzz import fuzz

from src.matching.normalizer import (
    normalize,
    normalize_serial,
    normalize_date,
    normalize_person_name,
    normalize_address,
    normalize_brand,
    normalize_facility_name,
)
from src.schema.evidence import ExtractedField
from src.schema.entities import (
    ApplicationEntity,
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayEquipmentEntity,
    XRayTubeEntity,
)
from src.schema.matching import (
    MatchingStatus,
    SourceEvidence,
    FieldCrossCheck,
    EntityCrossCheck,
    MatchSummary,
    CrossCheckReport,
)

# Threshold settings
MATCH_THRESHOLD = 85.0
REVIEW_THRESHOLD = 60.0
SERIAL_STRICT_THRESHOLD = 92.0
ADDRESS_MATCH_THRESHOLD = 85.0


def extract_street_number(addr: str) -> Optional[str]:
    """Extracts explicit street number (e.g. NO 2 from 'JL KESEHATAN NO 2')."""
    if not addr:
        return None
    m = re.search(r"\bNO\s*([0-9]+[A-Za-z]?)\b", addr)
    return m.group(1) if m else None


def compare_two_values(left: str, right: str, mode: str = "fuzzy_text") -> Tuple[Optional[float], MatchingStatus, str]:
    """Compares two values with specified matching mode, returning (score, status, explanation)."""
    l_str = str(left or "").strip()
    r_str = str(right or "").strip()

    if not l_str or not r_str or l_str in ("-", "—") or r_str in ("-", "—"):
        return None, MatchingStatus.TIDAK_DITEMUKAN, "Salah satu nilai kosong"

    if mode == "serial":
        l_norm = normalize_serial(l_str)
        r_norm = normalize_serial(r_str)
        if l_norm == r_norm:
            return 100.0, MatchingStatus.SESUAI, "Nomor seri identik"
        score = fuzz.ratio(l_norm, r_norm)
        if score >= SERIAL_STRICT_THRESHOLD:
            return score, MatchingStatus.PERLU_REVIEW, f"Nomor seri mirip ({score:.1f}%), potensi perbedaan karakter atau OCR"
        return score, MatchingStatus.TIDAK_SESUAI, f"Nomor seri berbeda ({score:.1f}%): '{l_str}' vs '{r_str}'"

    if mode == "brand":
        l_canon = normalize_brand(l_str)
        r_canon = normalize_brand(r_str)
        if l_canon == r_canon or l_canon in r_canon or r_canon in l_canon:
            return 100.0, MatchingStatus.SESUAI, f"Merk sesuai ({l_canon})"
        score = fuzz.token_sort_ratio(l_canon, r_canon)
        if score >= 75.0:
            return score, MatchingStatus.PERLU_REVIEW, f"Merk mirip ({score:.1f}%), perlu review evaluator"
        return score, MatchingStatus.TIDAK_SESUAI, f"Merk berbeda: '{l_str}' vs '{r_str}'"

    if mode == "fuzzy_name":
        l_name = normalize_person_name(l_str)
        r_name = normalize_person_name(r_str)
        if l_name == r_name:
            return 100.0, MatchingStatus.SESUAI, "Nama personel sesuai"
        score = fuzz.token_sort_ratio(l_name, r_name)
        if score >= MATCH_THRESHOLD:
            return score, MatchingStatus.SESUAI, f"Nama sesuai dengan variasi penulisan ({score:.1f}%)"
        if score >= REVIEW_THRESHOLD:
            return score, MatchingStatus.PERLU_REVIEW, f"Nama mirip ({score:.1f}%), memerlukan konfirmasi evaluator"
        return score, MatchingStatus.TIDAK_SESUAI, f"Nama berbeda ({score:.1f}%): '{l_str}' vs '{r_str}'"

    if mode == "facility_name":
        l_fac = normalize_facility_name(l_str)
        r_fac = normalize_facility_name(r_str)
        if l_fac == r_fac:
            return 100.0, MatchingStatus.SESUAI, "Nama fasilitas sesuai"
        score = max(fuzz.token_sort_ratio(l_fac, r_fac), fuzz.token_set_ratio(l_fac, r_fac))
        # High tolerance for regional / detachment variations or core facility name match
        if fuzz.token_set_ratio(l_fac, r_fac) >= 80.0:
            return 100.0, MatchingStatus.SESUAI, f"Nama fasilitas sesuai ({score:.1f}%)"
        if score >= MATCH_THRESHOLD:
            return score, MatchingStatus.SESUAI, f"Nama fasilitas sesuai ({score:.1f}%)"
        if score >= REVIEW_THRESHOLD:
            return score, MatchingStatus.PERLU_REVIEW, f"Nama fasilitas memiliki variasi ({score:.1f}%), perlu review"
        return score, MatchingStatus.TIDAK_SESUAI, f"Nama fasilitas berbeda: '{l_str}' vs '{r_str}'"

    if mode == "fuzzy_address":
        l_addr = normalize_address(l_str)
        r_addr = normalize_address(r_str)
        if l_addr == r_addr:
            return 100.0, MatchingStatus.SESUAI, "Alamat sesuai sempurna"

        score = max(
            fuzz.token_sort_ratio(l_addr, r_addr),
            fuzz.partial_ratio(l_addr, r_addr),
            fuzz.token_set_ratio(l_addr, r_addr),
        )

        # 1. Below review threshold is completely different street/city
        if score < REVIEW_THRESHOLD:
            return score, MatchingStatus.TIDAK_SESUAI, f"Alamat tidak sesuai: '{l_str}' vs '{r_str}'"

        # 2. Check if both have conflicting explicit street numbers on an otherwise similar address
        num_l = extract_street_number(l_addr)
        num_r = extract_street_number(r_addr)
        if num_l and num_r and num_l != num_r:
            return score, MatchingStatus.PERLU_REVIEW, f"Nomor alamat berbeda: No. {num_l} vs No. {num_r}"

        # 3. High tolerance for address hierarchy variations (e.g. short street address vs full administrative breakdown)
        if max(fuzz.token_set_ratio(l_addr, r_addr), fuzz.partial_ratio(l_addr, r_addr)) >= 75.0:
            return 100.0, MatchingStatus.SESUAI, f"Alamat sesuai ({score:.1f}%)"

        if score >= 75.0 or score >= ADDRESS_MATCH_THRESHOLD:
            return score, MatchingStatus.SESUAI, f"Alamat sesuai ({score:.1f}%)"
        return score, MatchingStatus.PERLU_REVIEW, f"Alamat memiliki variasi ({score:.1f}%), perlu review"

    # Default fuzzy text
    l_norm = normalize(l_str)
    r_norm = normalize(r_str)
    if l_norm == r_norm:
        return 100.0, MatchingStatus.SESUAI, "Nilai sesuai"
    score = fuzz.token_sort_ratio(l_norm, r_norm)
    if score >= MATCH_THRESHOLD:
        return score, MatchingStatus.SESUAI, f"Nilai sesuai ({score:.1f}%)"
    if score >= REVIEW_THRESHOLD:
        return score, MatchingStatus.PERLU_REVIEW, f"Terdapat variasi teks ({score:.1f}%), perlu review"
    return score, MatchingStatus.TIDAK_SESUAI, f"Nilai tidak sesuai: '{l_str}' vs '{r_str}'"


def evaluate_practice_location_against_facility(
    fac_name: str,
    fac_addr: str,
    loc_val: str,
) -> Tuple[float, MatchingStatus, str]:
    """Smartly matches SIP practice location (which often combines hospital name + street address)
    against the applicant facility name and address.
    """
    if not loc_val or (not fac_name and not fac_addr):
        return 100.0, MatchingStatus.SESUAI, f"Tempat praktik tertera: {loc_val}"

    scores: List[float] = []

    # 1. Direct comparison against facility name
    l_fac = normalize_facility_name(fac_name)
    r_fac = normalize_facility_name(loc_val)
    if l_fac and r_fac:
        scores.append(float(max(fuzz.token_sort_ratio(l_fac, r_fac), fuzz.token_set_ratio(l_fac, r_fac))))

    # 2. If loc_val contains a comma or Jl./Jalan, split into hospital part and address part
    hosp_part = loc_val
    addr_part = ""
    if "," in loc_val:
        parts = [p.strip() for p in loc_val.split(",") if p.strip()]
        hosp_part = parts[0]
        addr_part = ", ".join(parts[1:])
    elif re.search(r"\b(?:Jl\.?|Jalan)\b", loc_val, re.IGNORECASE):
        m = re.search(r"^(.*?)\b((?:Jl\.?|Jalan)\b.*)$", loc_val, re.IGNORECASE)
        if m:
            hosp_part = m.group(1).strip(" ,")
            addr_part = m.group(2).strip(" ,")

    if hosp_part and hosp_part != loc_val and fac_name:
        l_h = normalize_facility_name(fac_name)
        r_h = normalize_facility_name(hosp_part)
        scores.append(float(max(fuzz.token_sort_ratio(l_h, r_h), fuzz.token_set_ratio(l_h, r_h))))

    if addr_part and fac_addr:
        l_a = normalize_address(fac_addr)
        r_a = normalize_address(addr_part)
        scores.append(float(max(fuzz.token_sort_ratio(l_a, r_a), fuzz.token_set_ratio(l_a, r_a), fuzz.partial_ratio(l_a, r_a))))

    # 3. Combined comparison (facility name + address vs practice location)
    if fac_name or fac_addr:
        combined_fac = f"{fac_name} {fac_addr}".strip()
        l_c = normalize_facility_name(combined_fac)
        r_c = normalize_facility_name(loc_val)
        scores.append(float(max(fuzz.token_sort_ratio(l_c, r_c), fuzz.token_set_ratio(l_c, r_c))))

    best_score = round(max(scores) if scores else 0.0, 1)

    if best_score >= MATCH_THRESHOLD:
        return best_score, MatchingStatus.SESUAI, f"Tempat praktik pada izin sesuai fasilitas pemohon: '{loc_val}'"
    elif best_score >= REVIEW_THRESHOLD:
        return best_score, MatchingStatus.PERLU_REVIEW, f"Tempat praktik pada izin memiliki variasi ({best_score:.1f}%), perlu review: '{loc_val}'"
    else:
        return best_score, MatchingStatus.TIDAK_SESUAI, f"Tempat praktik pada izin berbeda: '{loc_val}' vs '{fac_name}'"



def evaluate_field_sources(
    field_key: str,
    field_label: str,
    sources: List[SourceEvidence],
    mode: str = "fuzzy_text",
) -> FieldCrossCheck:
    """Evaluates cross-check status for a field across all its source documents."""
    # Deduplicate sources with exact same doc, page, and value
    unique_sources: List[SourceEvidence] = []
    seen = set()
    for s in sources:
        key = (s.document_type, s.document_name, s.page, s.value)
        if key not in seen and s.value.strip() and s.value.strip() not in ("-", "—"):
            seen.add(key)
            unique_sources.append(s)

    if not unique_sources:
        return FieldCrossCheck(
            field_key=field_key,
            field_label=field_label,
            status=MatchingStatus.TIDAK_DITEMUKAN,
            score=None,
            reason="Data tidak ditemukan pada dokumen mana pun",
            sources=[],
        )

    if len(unique_sources) == 1:
        return FieldCrossCheck(
            field_key=field_key,
            field_label=field_label,
            status=MatchingStatus.TIDAK_DITEMUKAN,
            score=100.0,
            reason=f"Data hanya ditemukan pada 1 dokumen ({unique_sources[0].document_type}), belum ada dokumen pembanding",
            sources=unique_sources,
        )

    # Reference is the first source (e.g. Formulir or anchor document)
    ref = unique_sources[0]
    comparisons = []
    worst_status = MatchingStatus.SESUAI
    discrepancies = []
    total_score = 0.0

    for other in unique_sources[1:]:
        score, status, exp = compare_two_values(ref.value, other.value, mode=mode)
        comparisons.append((score, status, exp))
        if score is not None:
            total_score += score
        if status == MatchingStatus.TIDAK_SESUAI:
            worst_status = MatchingStatus.TIDAK_SESUAI
            discrepancies.append(f"{ref.document_type} ('{ref.value}') vs {other.document_type} ('{other.value}'): {exp}")
        elif status == MatchingStatus.PERLU_REVIEW and worst_status != MatchingStatus.TIDAK_SESUAI:
            worst_status = MatchingStatus.PERLU_REVIEW
            discrepancies.append(f"{other.document_type}: {exp}")

    avg_score = round(total_score / len(unique_sources[1:]), 1)

    if worst_status == MatchingStatus.SESUAI:
        reason = f"Sesuai di {len(unique_sources)} dokumen"
    elif worst_status == MatchingStatus.PERLU_REVIEW:
        reason = f"Potensi ketidaksesuaian di {len(unique_sources)} dokumen: {'; '.join(discrepancies)}"
    else:
        reason = f"Ketidaksesuaian terdeteksi: {'; '.join(discrepancies)}"

    return FieldCrossCheck(
        field_key=field_key,
        field_label=field_label,
        status=worst_status,
        score=avg_score,
        reason=reason,
        sources=unique_sources,
        discrepancies=discrepancies,
    )


def _collect_field_sources(
    extractions: Dict[str, List[Dict[str, Any]]],
    doc_types: List[str],
    field_name: str,
) -> List[SourceEvidence]:
    """Collects SourceEvidence for a specific field across specified document types."""
    results: List[SourceEvidence] = []
    for doc_type in doc_types:
        for doc in extractions.get(doc_type, []):
            fields = doc.get("fields", {})
            file_name = doc.get("file_name", "")
            field_data = fields.get(field_name, {})
            val = ""
            page = None
            raw_text = None
            conf = 1.0

            if isinstance(field_data, dict):
                val = str(field_data.get("value") or "").strip()
                page = field_data.get("page")
                raw_text = field_data.get("raw_text")
                conf = float(field_data.get("confidence") or 1.0)
            elif field_data:
                val = str(field_data).strip()

            if val and val not in ("-", "—"):
                results.append(
                    SourceEvidence(
                        document_type=doc_type,
                        document_name=file_name,
                        page=page,
                        value=val,
                        raw_text=raw_text,
                        confidence=conf,
                    )
                )
    return results


def cross_check_facility(
    facility: FacilityEntity,
    extractions: Dict[str, List[Dict[str, Any]]],
) -> EntityCrossCheck:
    """Evaluates cross-check for Facility identity (Project Name and Address)."""
    facility_docs = [
        "formulir", "sprint", "tld", "sistem_manajemen",
        "program_perawatan", "ppkr", "paparan_radiasi",
        "uji_fungsi", "uji_kesesuaian",
    ]

    name_sources = _collect_field_sources(extractions, facility_docs, "hospital_name")
    addr_sources = _collect_field_sources(extractions, facility_docs, "hospital_address")

    name_check = evaluate_field_sources(
        field_key="project_name",
        field_label="Nama instansi",
        sources=name_sources,
        mode="facility_name",
    )
    addr_check = evaluate_field_sources(
        field_key="project_address",
        field_label="Alamat instansi",
        sources=addr_sources,
        mode="fuzzy_address",
    )

    fields_map = {"project_name": name_check, "project_address": addr_check}
    overall = MatchingStatus.SESUAI
    if any(f.status == MatchingStatus.TIDAK_SESUAI for f in fields_map.values()):
        overall = MatchingStatus.TIDAK_SESUAI
    elif any(f.status == MatchingStatus.PERLU_REVIEW for f in fields_map.values()):
        overall = MatchingStatus.PERLU_REVIEW
    elif any(f.status == MatchingStatus.TIDAK_DITEMUKAN for f in fields_map.values()):
        overall = MatchingStatus.PERLU_REVIEW

    return EntityCrossCheck(
        category="facility",
        entity_id=facility.id if facility else "facility_1",
        entity_label=f"1. Identitas Fasilitas: {facility.project_name.value or 'Nama Tidak Ditemukan'}" if facility else "1. Identitas Fasilitas",
        status=overall,
        fields=fields_map,
    )


def cross_check_personnel(
    personnel_list: List[PersonnelEntity],
    extractions: Dict[str, List[Dict[str, Any]]],
    facility: Optional[FacilityEntity] = None,
    ppr_list: Optional[List[PPREntity]] = None,
) -> List[EntityCrossCheck]:
    """Evaluates cross-check for Personnel across the 5 canonical fields:
    1. Nama (person_name)
    2. Profesi/Keahlian (profession)
    3. Nama PPR (ppr_name)
    4. Masa berlaku (valid_until)
    5. Tempat praktik (practice_location)
    """
    personnel_checks = []

    # Name and address of the facility for practice location check
    fac_name = facility.project_name.value if facility and facility.project_name else ""
    fac_addr = facility.project_address.value if facility and facility.project_address else ""

    # Known PPR names across documents for reference
    all_ppr_sources = []
    for doc in extractions.get("sprint", []) + extractions.get("sib", []):
        f = doc.get("fields", {})
        val = str(f.get("ppr_name", {}).get("value") or "").strip()
        if val and val not in all_ppr_sources:
            all_ppr_sources.append(val)
    if ppr_list:
        for ppr in ppr_list:
            if ppr.name.value and ppr.name.value not in all_ppr_sources:
                all_ppr_sources.append(ppr.name.value)

    for idx, person in enumerate(personnel_list or [], start=1):
        target_name = person.name.value or ""
        prof_val = person.profession.value or ""
        norm_target = normalize_person_name(target_name)

        is_ppr = "PPR" in prof_val.upper() or any(
            fuzz.token_sort_ratio(norm_target, normalize_person_name(p.name.value or "")) >= 75
            for p in (ppr_list or [])
        )

        p_sources = []
        prof_sources = []
        ppr_sources = []
        valid_sources = []
        loc_sources = []

        # 1. Formulir sources
        if person.name.evidence:
            p_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name=person.name.evidence.file_name,
                    page=person.name.evidence.page,
                    value=target_name,
                    confidence=person.name.evidence.confidence,
                )
            )
        if person.profession.value:
            prof_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name=person.profession.evidence.file_name if person.profession.evidence else "Formulir",
                    page=person.profession.evidence.page if person.profession.evidence else None,
                    value=person.profession.value,
                )
            )
        if is_ppr and target_name:
            ppr_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name="Formulir Permohonan",
                    page=person.name.evidence.page if person.name.evidence else None,
                    value=target_name,
                )
            )

        # 2. Check matching SIP documents
        for doc in extractions.get("sip", []):
            f = doc.get("fields", {})
            sip_name = str(f.get("person_name", {}).get("value") or "").strip()
            score, _, _ = compare_two_values(target_name, sip_name, mode="fuzzy_name")
            if score and score >= 75.0:
                p_sources.append(
                    SourceEvidence(
                        document_type="sip",
                        document_name=doc.get("file_name", "SIP.pdf"),
                        page=f.get("person_name", {}).get("page"),
                        value=sip_name,
                    )
                )
                sip_prof = str(f.get("profession", {}).get("value") or "").strip()
                if sip_prof:
                    prof_sources.append(
                        SourceEvidence(
                            document_type="sip",
                            document_name=doc.get("file_name", "SIP.pdf"),
                            page=f.get("profession", {}).get("page"),
                            value=sip_prof,
                        )
                    )
                sip_valid = str(f.get("valid_until", {}).get("value") or "").strip()
                if sip_valid:
                    valid_sources.append(
                        SourceEvidence(
                            document_type="sip",
                            document_name=doc.get("file_name", "SIP.pdf"),
                            page=f.get("valid_until", {}).get("page"),
                            value=sip_valid,
                        )
                    )
                sip_loc = str(f.get("practice_location", {}).get("value") or "").strip()
                if sip_loc:
                    loc_sources.append(
                        SourceEvidence(
                            document_type="sip",
                            document_name=doc.get("file_name", "SIP.pdf"),
                            page=f.get("practice_location", {}).get("page"),
                            value=sip_loc,
                        )
                    )

        # 3. Check matching SIB documents (PPR)
        for doc in extractions.get("sib", []):
            f = doc.get("fields", {})
            sib_name = str(f.get("ppr_name", {}).get("value") or "").strip()
            score, _, _ = compare_two_values(target_name, sib_name, mode="fuzzy_name")
            if (score and score >= 75.0) or (is_ppr and not p_sources and sib_name):
                p_sources.append(
                    SourceEvidence(
                        document_type="sib",
                        document_name=doc.get("file_name", "SIB.pdf"),
                        page=f.get("ppr_name", {}).get("page"),
                        value=sib_name,
                    )
                )
                ppr_sources.append(
                    SourceEvidence(
                        document_type="sib",
                        document_name=doc.get("file_name", "SIB.pdf"),
                        page=f.get("ppr_name", {}).get("page"),
                        value=sib_name,
                    )
                )
                sib_prof = str(f.get("profession", {}).get("value") or "").strip()
                if sib_prof:
                    prof_sources.append(
                        SourceEvidence(
                            document_type="sib",
                            document_name=doc.get("file_name", "SIB.pdf"),
                            page=f.get("profession", {}).get("page"),
                            value=sib_prof,
                        )
                    )
                sib_valid = str(f.get("valid_until", {}).get("value") or "").strip()
                if sib_valid:
                    valid_sources.append(
                        SourceEvidence(
                            document_type="sib",
                            document_name=doc.get("file_name", "SIB.pdf"),
                            page=f.get("valid_until", {}).get("page"),
                            value=sib_valid,
                        )
                    )

        # 4. Check matching Sprint documents (PPR)
        for doc in extractions.get("sprint", []):
            f = doc.get("fields", {})
            sp_name = str(f.get("ppr_name", {}).get("value") or "").strip()
            score, _, _ = compare_two_values(target_name, sp_name, mode="fuzzy_name")
            if (score and score >= 75.0) or (is_ppr and sp_name):
                ppr_sources.append(
                    SourceEvidence(
                        document_type="sprint",
                        document_name=doc.get("file_name", "Sprint.pdf"),
                        page=f.get("ppr_name", {}).get("page"),
                        value=sp_name,
                    )
                )
                p_sources.append(
                    SourceEvidence(
                        document_type="sprint",
                        document_name=doc.get("file_name", "Sprint.pdf"),
                        page=f.get("ppr_name", {}).get("page"),
                        value=sp_name,
                    )
                )

        # 5. Check matching TLD documents
        for doc in extractions.get("tld", []):
            f = doc.get("fields", {})
            tld_name = str(f.get("person_name", {}).get("value") or "").strip()
            score, _, _ = compare_two_values(target_name, tld_name, mode="fuzzy_name")
            if score and score >= 75.0:
                p_sources.append(
                    SourceEvidence(
                        document_type="tld",
                        document_name=doc.get("file_name", "TLD.pdf"),
                        page=f.get("person_name", {}).get("page"),
                        value=tld_name,
                    )
                )

        # 6. Check matching PPKR documents
        for doc in extractions.get("ppkr", []):
            f = doc.get("fields", {})
            ppkr_p_name = str(f.get("person_name", {}).get("value") or "").strip()
            if ppkr_p_name:
                score, _, _ = compare_two_values(target_name, ppkr_p_name, mode="fuzzy_name")
                if score and score >= 75.0:
                    p_sources.append(
                        SourceEvidence(
                            document_type="ppkr",
                            document_name=doc.get("file_name", "PPKR.pdf"),
                            page=f.get("person_name", {}).get("page"),
                            value=ppkr_p_name,
                        )
                    )
                    if is_ppr:
                        ppr_sources.append(
                            SourceEvidence(
                                document_type="ppkr",
                                document_name=doc.get("file_name", "PPKR.pdf"),
                                page=f.get("person_name", {}).get("page"),
                                value=ppkr_p_name,
                            )
                        )

        # Existing person entity fields if present
        if person.valid_until and person.valid_until.value and not valid_sources:
            valid_sources.append(
                SourceEvidence(
                    document_type=person.valid_until.evidence.document_type if person.valid_until.evidence else "sip",
                    document_name=person.valid_until.evidence.file_name if person.valid_until.evidence else "",
                    page=person.valid_until.evidence.page if person.valid_until.evidence else None,
                    value=person.valid_until.value,
                )
            )
        if person.practice_location and person.practice_location.value and not loc_sources:
            loc_sources.append(
                SourceEvidence(
                    document_type=person.practice_location.evidence.document_type if person.practice_location.evidence else "sip",
                    document_name=person.practice_location.evidence.file_name if person.practice_location.evidence else "",
                    page=person.practice_location.evidence.page if person.practice_location.evidence else None,
                    value=person.practice_location.value,
                )
            )

        # Field 1: Nama
        name_check = evaluate_field_sources("person_name", "Nama", p_sources, mode="fuzzy_name")

        # Field 2: Profesi/Keahlian
        prof_check = evaluate_field_sources("profession", "Profesi/Keahlian", prof_sources, mode="fuzzy_text")

        # Field 3: Nama PPR
        if is_ppr:
            ppr_check = evaluate_field_sources("ppr_name", "Nama PPR", ppr_sources, mode="fuzzy_name")
        else:
            ref_ppr = all_ppr_sources[0] if all_ppr_sources else "PPR Terdaftar"
            ppr_check = FieldCrossCheck(
                field_key="ppr_name",
                field_label="Nama PPR",
                status=MatchingStatus.SESUAI,
                score=100.0,
                reason=f"Bukan Petugas Proteksi Radiasi ({prof_val or 'Staf Medis'}). PPR Faskes: {ref_ppr}",
                sources=[],
            )

        # Field 4: Masa berlaku
        if valid_sources:
            v_val = valid_sources[0].value
            valid_check = FieldCrossCheck(
                field_key="valid_until",
                field_label="Masa berlaku",
                status=MatchingStatus.SESUAI,
                score=100.0,
                reason=f"Masa berlaku izin terdaftar: {v_val}",
                sources=valid_sources,
            )
        else:
            valid_check = FieldCrossCheck(
                field_key="valid_until",
                field_label="Masa berlaku",
                status=MatchingStatus.TIDAK_DITEMUKAN,
                score=None,
                reason="Masa berlaku izin tidak ditemukan / berkas izin (SIP/SIB) belum diunggah",
                sources=[],
            )

        # Field 5: Tempat praktik
        if loc_sources:
            loc_val = loc_sources[0].value
            if fac_name or fac_addr:
                score, status, reason_msg = evaluate_practice_location_against_facility(fac_name, fac_addr, loc_val)
                loc_check = FieldCrossCheck(
                    field_key="practice_location",
                    field_label="Tempat praktik",
                    status=status,
                    score=score,
                    reason=reason_msg,
                    sources=loc_sources,
                    discrepancies=[f"SIP: '{loc_val}' vs Faskes: '{fac_name}'"] if status != MatchingStatus.SESUAI else [],
                )
            else:
                loc_check = FieldCrossCheck(
                    field_key="practice_location",
                    field_label="Tempat praktik",
                    status=MatchingStatus.SESUAI,
                    score=100.0,
                    reason=f"Tempat praktik tertera: {loc_val}",
                    sources=loc_sources,
                )
        else:
            loc_check = FieldCrossCheck(
                field_key="practice_location",
                field_label="Tempat praktik",
                status=MatchingStatus.TIDAK_DITEMUKAN,
                score=None,
                reason="Tempat praktik tidak ditemukan / SIP belum diunggah",
                sources=[],
            )

        fields_map = {
            "person_name": name_check,
            "profession": prof_check,
            "ppr_name": ppr_check,
            "valid_until": valid_check,
            "practice_location": loc_check,
        }

        overall = MatchingStatus.SESUAI
        if any(f.status == MatchingStatus.TIDAK_SESUAI for f in fields_map.values()):
            overall = MatchingStatus.TIDAK_SESUAI
        elif any(f.status == MatchingStatus.PERLU_REVIEW for f in fields_map.values()):
            overall = MatchingStatus.PERLU_REVIEW

        personnel_checks.append(
            EntityCrossCheck(
                category="personnel",
                entity_id=person.id,
                entity_label=f"Personel #{idx}: {target_name} ({prof_val or 'Staf'})",
                status=overall,
                fields=fields_map,
            )
        )

    return personnel_checks


def cross_check_ppr(
    ppr_list: List[PPREntity],
    extractions: Dict[str, List[Dict[str, Any]]],
) -> List[EntityCrossCheck]:
    """Evaluates cross-check for each individual PPR (maintained for backward compatibility)."""
    ppr_checks = []

    for idx, ppr in enumerate(ppr_list, start=1):
        target_name = ppr.name.value or ""
        ppr_sources = []

        if ppr.name.evidence:
            ppr_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name=ppr.name.evidence.file_name,
                    page=ppr.name.evidence.page,
                    value=target_name,
                )
            )

        # Check SIB
        for doc in extractions.get("sib", []):
            f = doc.get("fields", {})
            sib_name = str(f.get("ppr_name", {}).get("value") or "").strip()
            score, _, _ = compare_two_values(target_name, sib_name, mode="fuzzy_name")
            if score and score >= 75.0:
                ppr_sources.append(
                    SourceEvidence(
                        document_type="sib",
                        document_name=doc.get("file_name", "SIB.pdf"),
                        page=f.get("ppr_name", {}).get("page"),
                        value=sib_name,
                    )
                )

        # Check Sprint
        for doc in extractions.get("sprint", []):
            f = doc.get("fields", {})
            sp_name = str(f.get("ppr_name", {}).get("value") or "").strip()
            score, _, _ = compare_two_values(target_name, sp_name, mode="fuzzy_name")
            if score and score >= 75.0:
                ppr_sources.append(
                    SourceEvidence(
                        document_type="sprint",
                        document_name=doc.get("file_name", "Sprint.pdf"),
                        page=f.get("ppr_name", {}).get("page"),
                        value=sp_name,
                    )
                )

        name_check = evaluate_field_sources("ppr_name", "Nama PPR", ppr_sources, mode="fuzzy_name")
        fields_map = {"ppr_name": name_check}

        if ppr.valid_until and ppr.valid_until.value:
            fields_map["valid_until"] = FieldCrossCheck(
                field_key="valid_until",
                field_label="Masa Berlaku SIB",
                status=MatchingStatus.SESUAI,
                score=100.0,
                reason=f"Masa berlaku SIB: {ppr.valid_until.value}",
                sources=[
                    SourceEvidence(
                        document_type="sib",
                        document_name=ppr.valid_until.evidence.file_name if ppr.valid_until.evidence else "SIB.pdf",
                        page=ppr.valid_until.evidence.page if ppr.valid_until.evidence else None,
                        value=ppr.valid_until.value,
                    )
                ],
            )

        overall = MatchingStatus.SESUAI
        if any(f.status == MatchingStatus.TIDAK_SESUAI for f in fields_map.values()):
            overall = MatchingStatus.TIDAK_SESUAI
        elif any(f.status == MatchingStatus.PERLU_REVIEW for f in fields_map.values()):
            overall = MatchingStatus.PERLU_REVIEW

        ppr_checks.append(
            EntityCrossCheck(
                category="ppr",
                entity_id=ppr.id,
                entity_label=f"PPR #{idx}: {target_name}",
                status=overall,
                fields=fields_map,
            )
        )

    return ppr_checks


def cross_check_equipment(
    equipment_list: List[XRayEquipmentEntity],
    extractions: Dict[str, List[Dict[str, Any]]],
) -> List[EntityCrossCheck]:
    """Evaluates Section 3: Pesawat Sinar-X across 3 fields:
    1. Merk unit (unit_brand)
    2. Tipe unit (unit_type)
    3. Nomor seri unit (unit_serial_number)
    """
    equipment_checks = []

    for idx, eq in enumerate(equipment_list, start=1):
        unit_brand = eq.unit_brand.value or ""
        unit_type = eq.unit_type.value or ""
        unit_serial = eq.unit_serial_number.value or ""

        brand_sources = []
        type_sources = []
        serial_sources = []

        # 1. Formulir evidence
        if eq.unit_brand.evidence:
            brand_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name=eq.unit_brand.evidence.file_name,
                    page=eq.unit_brand.evidence.page,
                    value=unit_brand,
                )
            )
        if eq.unit_type.evidence:
            type_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name=eq.unit_type.evidence.file_name,
                    page=eq.unit_type.evidence.page,
                    value=unit_type,
                )
            )
        if eq.unit_serial_number.evidence:
            serial_sources.append(
                SourceEvidence(
                    document_type="formulir",
                    document_name=eq.unit_serial_number.evidence.file_name,
                    page=eq.unit_serial_number.evidence.page,
                    value=unit_serial,
                )
            )

        # 2. Match with PPKR
        for doc in extractions.get("ppkr", []):
            f = doc.get("fields", {})
            file_name = doc.get("file_name", "PPKR.pdf")
            p_brand = str(f.get("unit_brand", {}).get("value") or "").strip()
            p_type = str(f.get("unit_type", {}).get("value") or "").strip()
            p_serial = str(f.get("unit_serial_number", {}).get("value") or "").strip()

            is_match = False
            if unit_serial and p_serial and normalize_serial(unit_serial) == normalize_serial(p_serial):
                is_match = True
            elif not unit_serial or not p_serial:
                if unit_brand and p_brand and normalize_brand(unit_brand) == normalize_brand(p_brand):
                    is_match = True

            if is_match or len(equipment_list) == 1:
                if p_brand:
                    brand_sources.append(SourceEvidence(document_type="ppkr", document_name=file_name, value=p_brand, page=f.get("unit_brand", {}).get("page")))
                if p_type:
                    type_sources.append(SourceEvidence(document_type="ppkr", document_name=file_name, value=p_type, page=f.get("unit_type", {}).get("page")))
                if p_serial:
                    serial_sources.append(SourceEvidence(document_type="ppkr", document_name=file_name, value=p_serial, page=f.get("unit_serial_number", {}).get("page")))

        # 3. Match with Unit Label images
        for doc in extractions.get("label_unit", []):
            f = doc.get("fields", {})
            file_name = doc.get("file_name", "Label_Unit.jpg")
            l_brand = str(f.get("unit_brand", {}).get("value") or "").strip()
            l_type = str(f.get("unit_type", {}).get("value") or "").strip()
            l_serial = str(f.get("unit_serial_number", {}).get("value") or "").strip()

            is_match = False
            if unit_serial and l_serial and normalize_serial(unit_serial) == normalize_serial(l_serial):
                is_match = True
            elif not unit_serial and (unit_brand and l_brand and normalize_brand(unit_brand) == normalize_brand(l_brand)):
                is_match = True

            if is_match or len(equipment_list) == 1:
                if l_brand:
                    brand_sources.append(SourceEvidence(document_type="label_unit", document_name=file_name, value=l_brand, page=1))
                if l_type:
                    type_sources.append(SourceEvidence(document_type="label_unit", document_name=file_name, value=l_type, page=1))
                if l_serial:
                    serial_sources.append(SourceEvidence(document_type="label_unit", document_name=file_name, value=l_serial, page=1))

        # 4. Match with Spesifikasi Pesawat / Persetujuan Import / Uji Kesesuaian / Paparan Radiasi / Uji Fungsi
        for doc_type in ["spesifikasi_pesawat", "persetujuan_import", "uji_kesesuaian", "paparan_radiasi", "uji_fungsi"]:
            for doc in extractions.get(doc_type, []):
                f = doc.get("fields", {})
                file_name = doc.get("file_name", f"{doc_type}.pdf")
                s_brand = str(f.get("unit_brand", {}).get("value") or "").strip()
                s_type = str(f.get("unit_type", {}).get("value") or "").strip()
                s_serial = str(f.get("unit_serial_number", {}).get("value") or "").strip()
                if not s_type and f.get("unit_type_serial", {}).get("value"):
                    raw_uts = str(f.get("unit_type_serial", {}).get("value"))
                    if "/" in raw_uts:
                        parts = raw_uts.split("/", 1)
                        s_type = parts[0].strip()
                        if not s_serial:
                            s_serial = parts[1].strip()
                    else:
                        s_type = raw_uts.strip()
                is_match = False
                if unit_serial and s_serial and (normalize_serial(unit_serial) == normalize_serial(s_serial) or normalize_serial(unit_serial) in normalize_serial(s_serial) or normalize_serial(s_serial) in normalize_serial(unit_serial)):
                    is_match = True
                elif unit_type and s_type and (normalize(unit_type) in normalize(s_type) or normalize(s_type) in normalize(unit_type)):
                    is_match = True
                elif not unit_serial and not s_serial and unit_brand and s_brand and normalize_brand(unit_brand) == normalize_brand(s_brand):
                    is_match = True

                if is_match or len(equipment_list) == 1:
                    if s_brand:
                        brand_sources.append(SourceEvidence(document_type=doc_type, document_name=file_name, value=s_brand, page=f.get("unit_brand", {}).get("page")))
                    if s_type:
                        type_sources.append(SourceEvidence(document_type=doc_type, document_name=file_name, value=s_type, page=f.get("unit_type", {}).get("page") or f.get("unit_type_serial", {}).get("page")))
                    if s_serial:
                        serial_sources.append(SourceEvidence(document_type=doc_type, document_name=file_name, value=s_serial, page=f.get("unit_serial_number", {}).get("page") or f.get("unit_type_serial", {}).get("page")))

        brand_check = evaluate_field_sources("unit_brand", "Merk unit", brand_sources, mode="brand")
        type_check = evaluate_field_sources("unit_type", "Tipe unit", type_sources, mode="fuzzy_text")
        serial_check = evaluate_field_sources("unit_serial_number", "Nomor seri unit", serial_sources, mode="serial")

        unit_fields = {
            "unit_brand": brand_check,
            "unit_type": type_check,
            "unit_serial_number": serial_check,
        }

        overall = MatchingStatus.SESUAI
        if any(f.status == MatchingStatus.TIDAK_SESUAI for f in unit_fields.values()):
            overall = MatchingStatus.TIDAK_SESUAI
        elif any(f.status == MatchingStatus.PERLU_REVIEW for f in unit_fields.values()):
            overall = MatchingStatus.PERLU_REVIEW

        equipment_checks.append(
            EntityCrossCheck(
                category="xray_equipment",
                entity_id=eq.id,
                entity_label=f"Pesawat Sinar-X Unit #{idx}: {unit_brand} {unit_type} ({unit_serial or 'No Seri'})",
                status=overall,
                fields=unit_fields,
            )
        )

    return equipment_checks


def cross_check_tubes(
    equipment_list: List[XRayEquipmentEntity],
    extractions: Dict[str, List[Dict[str, Any]]],
) -> List[EntityCrossCheck]:
    """Evaluates Section 4: Tabung Sinar-X across 3 fields:
    1. Merk tabung (tube_brand)
    2. Tipe/model tabung (tube_type)
    3. Nomor seri tabung (tube_serial_number)
    """
    tube_checks = []

    # Gather tubes from equipment or from label_tabung / uji_kesesuaian
    tubes_to_check = []
    for idx, eq in enumerate(equipment_list, start=1):
        if eq.tube:
            tubes_to_check.append((idx, eq.tube, eq))

    # If no tubes paired to equipment, inspect label_tabung and uji_kesesuaian extractions directly
    if not tubes_to_check:
        for idx, doc in enumerate(extractions.get("label_tabung", []), start=1):
            f = doc.get("fields", {})
            b = str(f.get("tube_brand", {}).get("value") or "")
            m = str(f.get("tube_unit_model", {}).get("value") or f.get("tube_insert_model", {}).get("value") or "")
            s = str(f.get("tube_serial_number", {}).get("value") or "")
            t = XRayTubeEntity(
                id=f"tube_{idx}",
                tube_brand=ExtractedField(value=b),
                tube_type=ExtractedField(value=m),
                tube_model=ExtractedField(value=m),
                tube_serial_number=ExtractedField(value=s),
            )
            tubes_to_check.append((idx, t, None))

    for idx, tube, eq in tubes_to_check:
        t_brand = tube.tube_brand.value or ""
        t_type = tube.tube_type.value or tube.tube_model.value or ""
        t_serial = tube.tube_serial_number.value or ""

        brand_sources = []
        type_sources = []
        serial_sources = []

        # 1. Formulir sources
        if eq and eq.tube:
            if t_brand:
                brand_sources.append(SourceEvidence(document_type="formulir", document_name="Formulir Permohonan", value=t_brand))
            if t_type:
                type_sources.append(SourceEvidence(document_type="formulir", document_name="Formulir Permohonan", value=t_type))
            if t_serial:
                serial_sources.append(SourceEvidence(document_type="formulir", document_name="Formulir Permohonan", value=t_serial))

        # 2. PPKR sources
        for doc in extractions.get("ppkr", []):
            f = doc.get("fields", {})
            file_name = doc.get("file_name", "PPKR.pdf")
            p_brand = str(f.get("tube_brand", {}).get("value") or "").strip()
            p_type = str(f.get("tube_type", {}).get("value") or "").strip()
            p_serial = str(f.get("tube_serial_number", {}).get("value") or "").strip()
            if len(equipment_list) > 1:
                ppkr_unit_sn = str(f.get("unit_serial_number", {}).get("value") or "").strip()
                if eq and eq.unit_serial_number and eq.unit_serial_number.value and ppkr_unit_sn:
                    if normalize_serial(ppkr_unit_sn) != normalize_serial(eq.unit_serial_number.value):
                        continue
                if t_serial and p_serial and normalize_serial(t_serial) != normalize_serial(p_serial):
                    continue
            if p_brand:
                brand_sources.append(SourceEvidence(document_type="ppkr", document_name=file_name, value=p_brand, page=f.get("tube_brand", {}).get("page")))
            if p_type:
                type_sources.append(SourceEvidence(document_type="ppkr", document_name=file_name, value=p_type, page=f.get("tube_type", {}).get("page")))
            if p_serial:
                serial_sources.append(SourceEvidence(document_type="ppkr", document_name=file_name, value=p_serial, page=f.get("tube_serial_number", {}).get("page")))

        # 3. Match with Tube Label images
        for doc in extractions.get("label_tabung", []):
            f = doc.get("fields", {})
            file_name = doc.get("file_name", "Label_Tabung.jpg")
            lt_brand = str(f.get("tube_brand", {}).get("value") or "").strip()
            ins_model = str(f.get("tube_insert_model", {}).get("value") or "").strip()
            unit_model = str(f.get("tube_unit_model", {}).get("value") or "").strip()
            if t_type and ins_model and (normalize(t_type) == normalize(ins_model) or normalize(ins_model) in normalize(t_type)):
                lt_type = ins_model
            elif t_type and unit_model and (normalize(t_type) == normalize(unit_model) or normalize(unit_model) in normalize(t_type)):
                lt_type = unit_model
            else:
                lt_type = unit_model or ins_model
            lt_serial = str(f.get("tube_serial_number", {}).get("value") or "").strip()

            is_match = False
            if t_serial and lt_serial and normalize_serial(t_serial) == normalize_serial(lt_serial):
                is_match = True
            elif not t_serial:
                is_match = True

            if is_match:
                if lt_brand:
                    brand_sources.append(SourceEvidence(document_type="label_tabung", document_name=file_name, value=lt_brand, page=1))
                if lt_type:
                    type_sources.append(SourceEvidence(document_type="label_tabung", document_name=file_name, value=lt_type, page=1))
                if lt_serial:
                    serial_sources.append(SourceEvidence(document_type="label_tabung", document_name=file_name, value=lt_serial, page=1))

        # 4. Match with Uji Kesesuaian / Persetujuan Import / Paparan Radiasi / Uji Fungsi
        for doc_type in ["uji_kesesuaian", "persetujuan_import", "paparan_radiasi", "uji_fungsi"]:
            for doc in extractions.get(doc_type, []):
                f = doc.get("fields", {})
                file_name = doc.get("file_name", f"{doc_type}.pdf")

                # Verify unit serial matching: If the document specifies a unit serial number
                # that contradicts this equipment's serial number, skip it so tubes from different units
                # do not contaminate this equipment's tube cross-check.
                doc_unit_sn = str(f.get("unit_serial_number", {}).get("value") or "").strip()
                if not doc_unit_sn and f.get("unit_type_serial", {}).get("value"):
                    uts = str(f.get("unit_type_serial", {}).get("value"))
                    if "/" in uts:
                        doc_unit_sn = uts.split("/", 1)[1].strip()
                    elif "S/N:" in uts:
                        doc_unit_sn = uts.split("S/N:", 1)[1].strip()

                if eq and eq.unit_serial_number and eq.unit_serial_number.value and doc_unit_sn:
                    if normalize_serial(doc_unit_sn) != normalize_serial(eq.unit_serial_number.value):
                        continue

                tb_b = str(f.get("tube_brand", {}).get("value") or "").strip()
                tb_m = str(f.get("tube_type", {}).get("value") or f.get("tube_model", {}).get("value") or "").strip()
                tb_s = str(f.get("tube_serial_number", {}).get("value") or "").strip()
                if not tb_m and f.get("tube_type_serial", {}).get("value"):
                    raw_tts = str(f.get("tube_type_serial", {}).get("value")).strip()
                    if "/" in raw_tts:
                        parts = raw_tts.split("/", 1)
                        tb_m = parts[0].strip()
                        if not tb_s:
                            tb_s = parts[1].strip()
                    else:
                        is_serial_like = bool(re.match(r"^[0-9]{2,}[A-Za-z]+[0-9]+$", raw_tts) or re.match(r"^[0-9A-Za-z]{6,}$", raw_tts))
                        if not tb_s and is_serial_like:
                            tb_s = raw_tts
                        elif not is_serial_like and (not tb_s or raw_tts != tb_s):
                            tb_m = raw_tts

                if len(equipment_list) > 1 and not doc_unit_sn and t_serial and tb_s:
                    if normalize_serial(t_serial) != normalize_serial(tb_s):
                        continue

                if tb_b:
                    brand_sources.append(SourceEvidence(document_type=doc_type, document_name=file_name, value=tb_b, page=f.get("tube_brand", {}).get("page")))
                if tb_m:
                    type_sources.append(SourceEvidence(document_type=doc_type, document_name=file_name, value=tb_m, page=f.get("tube_type", {}).get("page") or f.get("tube_type_serial", {}).get("page") or f.get("tube_model", {}).get("page")))
                if tb_s:
                    serial_sources.append(SourceEvidence(document_type=doc_type, document_name=file_name, value=tb_s, page=f.get("tube_serial_number", {}).get("page") or f.get("tube_type_serial", {}).get("page")))

        tb_brand_chk = evaluate_field_sources("tube_brand", "Merk tabung", brand_sources, mode="brand")
        tb_type_chk = evaluate_field_sources("tube_type", "Tipe/model tabung", type_sources, mode="fuzzy_text")
        tb_serial_chk = evaluate_field_sources("tube_serial_number", "Nomor seri tabung", serial_sources, mode="serial")

        # Tolerant evaluation for Tube Brand:
        # If the reference tube brand matches primary evidence (label_tabung, uji_kesesuaian, ppkr),
        # but a document (e.g. uji_fungsi) recorded the unit/system manufacturer brand (e.g. GE for Canon tube),
        # classify as SESUAI rather than fatal TIDAK_SESUAI.
        if tb_brand_chk.status == MatchingStatus.TIDAK_SESUAI:
            ref_brand = brand_sources[0].value if brand_sources else ""
            primary_brand_matches = [
                s for s in brand_sources[1:]
                if s.document_type in {"label_tabung", "uji_kesesuaian", "ppkr"}
                and compare_two_values(ref_brand, s.value, mode="brand")[1] == MatchingStatus.SESUAI
            ]
            if primary_brand_matches:
                unit_b = (eq.unit_brand.value or "") if eq else ""
                brand_discrepancies = [
                    s for s in brand_sources[1:]
                    if compare_two_values(ref_brand, s.value, mode="brand")[1] != MatchingStatus.SESUAI
                ]
                is_unit_brand_fallback = all(
                    unit_b and compare_two_values(unit_b, s.value, mode="brand")[1] == MatchingStatus.SESUAI
                    for s in brand_discrepancies
                )
                if is_unit_brand_fallback:
                    tb_brand_chk.status = MatchingStatus.SESUAI
                    tb_brand_chk.score = 100.0
                    tb_brand_chk.reason = (
                        f"Merk tabung sesuai bukti utama ('{ref_brand}'). "
                        f"Dokumen pendukung mencatat merk sistem unit ('{unit_b}')."
                    )
                else:
                    tb_brand_chk.status = MatchingStatus.PERLU_REVIEW
                    tb_brand_chk.score = max(tb_brand_chk.score or 0.0, 85.0)

        # Tolerant evaluation for X-Ray Tube Serial Number (Insert S/N vs Housing S/N):
        # In medical X-ray equipment, tube insert serial (e.g. 0F1376) and tube housing serial (e.g. 20G225)
        # coexist. If the reference serial matches primary physical evidence (label_tabung) and/or
        # the official calibration/conformity certificate (uji_kesesuaian), but secondary operational
        # documents (uji_fungsi, paparan_radiasi) recorded the tube housing serial number,
        # classify as PERLU_REVIEW with an informative message instead of fatal TIDAK_SESUAI.
        if tb_serial_chk.status == MatchingStatus.TIDAK_SESUAI:
            ref_val = serial_sources[0].value if serial_sources else ""
            primary_matches = [
                s for s in serial_sources[1:]
                if s.document_type in {"label_tabung", "uji_kesesuaian"}
                and normalize_serial(s.value) == normalize_serial(ref_val)
            ]
            if primary_matches:
                sec_discrepancies = [
                    s for s in serial_sources[1:]
                    if normalize_serial(s.value) != normalize_serial(ref_val)
                ]
                if sec_discrepancies:
                    tb_serial_chk.status = MatchingStatus.PERLU_REVIEW
                    sec_doc_info = ", ".join(f"'{s.value}' ({s.document_type})" for s in sec_discrepancies)
                    tb_serial_chk.reason = (
                        f"Nomor seri insert sesuai bukti utama label fisik & uji kesesuaian ('{ref_val}'). "
                        f"Terdeteksi nomor seri housing/dokumen sekunder {sec_doc_info}, perlu konfirmasi evaluator."
                    )
                    tb_serial_chk.score = max(tb_serial_chk.score or 0.0, 85.0)

        tube_fields = {
            "tube_brand": tb_brand_chk,
            "tube_type": tb_type_chk,
            "tube_serial_number": tb_serial_chk,
        }

        tube_overall = MatchingStatus.SESUAI
        if any(f.status == MatchingStatus.TIDAK_SESUAI for f in tube_fields.values()):
            tube_overall = MatchingStatus.TIDAK_SESUAI
        elif any(f.status == MatchingStatus.PERLU_REVIEW for f in tube_fields.values()):
            tube_overall = MatchingStatus.PERLU_REVIEW

        tube_checks.append(
            EntityCrossCheck(
                category="tube",
                entity_id=tube.id,
                entity_label=f"Tabung Sinar-X #{idx}: {t_brand} {t_type} ({t_serial or 'No Serial'})",
                status=tube_overall,
                fields=tube_fields,
            )
        )

    return tube_checks


def generate_cross_check_report(
    application: ApplicationEntity,
    extractions: Dict[str, List[Dict[str, Any]]],
    run_id: str,
) -> CrossCheckReport:
    """Orchestrates comprehensive multi-entity cross-check across the 4 BAPETEN sections:
    1. Identitas Fasilitas (Nama instansi, Alamat instansi)
    2. Personel (Nama, Profesi/Keahlian, Nama PPR, Masa berlaku, Tempat praktik)
    3. Pesawat Sinar-X (Merk unit, Tipe unit, Nomor seri unit)
    4. Tabung Sinar-X (Merk tabung, Tipe/model tabung, Nomor seri tabung)
    """
    facility_check = cross_check_facility(application.facility, extractions)
    personnel_checks = cross_check_personnel(
        application.personnel,
        extractions,
        facility=application.facility,
        ppr_list=application.ppr,
    )
    ppr_checks = cross_check_ppr(application.ppr, extractions)
    xray_checks = cross_check_equipment(application.xray_equipment, extractions)
    tube_checks = cross_check_tubes(application.xray_equipment, extractions)

    # Calculate summary statistics across all 4 sections
    all_fields: List[FieldCrossCheck] = []
    if facility_check:
        all_fields.extend(facility_check.fields.values())
    for p in personnel_checks:
        all_fields.extend(p.fields.values())
    for eq in xray_checks:
        all_fields.extend(eq.fields.values())
    for tb in tube_checks:
        all_fields.extend(tb.fields.values())

    summary = MatchSummary(
        total_fields_checked=len(all_fields),
        sesuai=sum(1 for f in all_fields if f.status == MatchingStatus.SESUAI),
        perlu_review=sum(1 for f in all_fields if f.status == MatchingStatus.PERLU_REVIEW),
        tidak_sesuai=sum(1 for f in all_fields if f.status == MatchingStatus.TIDAK_SESUAI),
        tidak_ditemukan=sum(1 for f in all_fields if f.status == MatchingStatus.TIDAK_DITEMUKAN),
        warning=sum(1 for f in all_fields if f.status == MatchingStatus.WARNING),
    )

    return CrossCheckReport(
        run_id=run_id,
        application_id=application.application_id,
        facility=facility_check,
        personnel=personnel_checks,
        ppr=ppr_checks,
        xray_equipment=xray_checks,
        xray_tubes=tube_checks,
        summary=summary,
        metadata={
            "total_personnel": len(personnel_checks),
            "total_ppr": len(ppr_checks),
            "total_xray_units": len(xray_checks),
            "total_xray_tubes": len(tube_checks),
        },
    )
