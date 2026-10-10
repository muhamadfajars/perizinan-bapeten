"""BAPETEN Regulatory Compliance and Document Validation Rules.

Validates:
1. Mandatory document completeness (Formulir, PPKR, SIB, SIP, Label, dll.)
2. Expiration and validity of licenses (SIP dokter/radiografer, SIB PPR)
3. Practice location compliance (Tempat praktik SIP vs Fasilitas pemohon)
4. Equipment integrity (Kelengkapan nomor seri pesawat & tabung)
5. PPR personnel presence (Keharusan adanya Petugas Proteksi Radiasi)
"""

import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from src.matching.normalizer import normalize_date, normalize_facility_name
from src.schema.entities import ApplicationEntity, FacilityEntity, PersonnelEntity, PPREntity, XRayEquipmentEntity

VALID_STATUSES = {
    "SESUAI",
    "WARNING",
    "PERLU REVIEW",
    "TIDAK SESUAI",
    "TIDAK DITEMUKAN",
}

# Mandatory documents for BAPETEN diagnostic radiology permits
MANDATORY_DOCUMENTS = {
    "formulir": "Formulir Permohonan Izin",
    "ppkr": "Program Proteksi dan Keselamatan Radiasi (PPKR)",
    "sib": "Surat Izin Bekerja (SIB) PPR",
    "sip": "Surat Izin Praktik (SIP) Dokter Spesialis / Personel",
}

RECOMMENDED_DOCUMENTS = {
    "sprint": "Surat Perintah / Penunjukan PPR",
    "label_unit": "Foto Label Pesawat Sinar-X",
    "label_tabung": "Foto Label Tabung Sinar-X",
    "uji_fungsi": "Hasil Uji Fungsi Pesawat",
    "uji_kesesuaian": "Laporan Uji Kesesuaian Pesawat & Tabung",
}


class ValidationSeverity(str, Enum):
    CRITICAL = "CRITICAL"  # Berpotensi menyebabkan permohonan ditolak / berkas belum lengkap
    WARNING = "WARNING"    # Memerlukan perhatian khusus / review evaluator
    INFO = "INFO"          # Informasi tambahan


class ValidationIssue(BaseModel):
    """Deskripsi temuan pelanggaran aturan atau kekurangan dokumen."""
    rule_id: str = Field(..., description="ID aturan, e.g. RULE-DOC-01")
    rule_name: str = Field(..., description="Nama aturan bisnis")
    category: str = Field(..., description="Kategori: dokumen_wajib | masa_berlaku | tempat_praktik | peralatan | ppr")
    severity: ValidationSeverity = Field(..., description="Tingkat keparahan temuan")
    description: str = Field(..., description="Uraian temuan")
    affected_entity: Optional[str] = Field(default=None, description="Nama entitas atau nomor seri terkait")
    recommendation: Optional[str] = Field(default=None, description="Rekomendasi tindakan untuk evaluator / pemohon")


class ValidationReport(BaseModel):
    """Laporan hasil evaluasi aturan bisnis dan kelengkapan permohonan."""
    is_compliant: bool = Field(default=True, description="True jika tidak ada temuan CRITICAL")
    total_rules_evaluated: int = Field(default=0, description="Jumlah aturan yang diuji")
    total_issues: int = Field(default=0, description="Total temuan masalah")
    critical_count: int = Field(default=0, description="Jumlah temuan kritis (blocking)")
    warning_count: int = Field(default=0, description="Jumlah temuan peringatan")
    info_count: int = Field(default=0, description="Jumlah informasi")
    issues: List[ValidationIssue] = Field(default_factory=list, description="Daftar temuan")


def parse_date_safe(date_str: Optional[str]) -> Optional[date]:
    """Safely parses dates in various formats (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, Indonesian text)."""
    if not date_str:
        return None
    normalized = normalize_date(date_str)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def validate_cross_checks(rows: List[Dict[str, Any]]) -> None:
    """Legacy validation function ensuring cross check statuses are valid."""
    invalid = {row.get("status") for row in rows if row.get("status") not in VALID_STATUSES}
    if invalid:
        raise ValueError(f"Unknown cross-check statuses: {sorted(invalid)}")


def document_presence(uploaded_doc_types: Any, document_types: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generates document presence checklist for uploaded documents."""
    is_map = isinstance(uploaded_doc_types, (dict, Mapping))
    if is_map:
        return [
            {
                "document_type": key,
                "document_name": data.get("name", key),
                "uploaded": bool(uploaded_doc_types.get(key)),
            }
            for key, data in document_types.items()
        ]

    uploaded_set = set(uploaded_doc_types or [])
    return [
        {
            "document_type": key,
            "document_name": data.get("name", key),
            "uploaded": key in uploaded_set,
        }
        for key, data in document_types.items()
    ]


def check_mandatory_documents(uploaded_doc_types: List[str]) -> List[ValidationIssue]:
    """Rule DOC-01: Verifies presence of all mandatory licensing documents."""
    issues = []
    uploaded_set = set(uploaded_doc_types or [])

    for doc_key, doc_name in MANDATORY_DOCUMENTS.items():
        if doc_key not in uploaded_set:
            issues.append(
                ValidationIssue(
                    rule_id="RULE-DOC-MANDATORY",
                    rule_name="Kelengkapan Dokumen Wajib",
                    category="dokumen_wajib",
                    severity=ValidationSeverity.CRITICAL,
                    description=f"Dokumen wajib '{doc_name}' ({doc_key}) belum diunggah atau tidak ditemukan.",
                    affected_entity=doc_key,
                    recommendation=f"Pemohon wajib mengunggah dokumen {doc_name}.",
                )
            )

    for doc_key, doc_name in RECOMMENDED_DOCUMENTS.items():
        if doc_key not in uploaded_set:
            issues.append(
                ValidationIssue(
                    rule_id="RULE-DOC-RECOMMENDED",
                    rule_name="Dokumen Pendukung Rekomendasi",
                    category="dokumen_wajib",
                    severity=ValidationSeverity.WARNING,
                    description=f"Dokumen pendukung '{doc_name}' ({doc_key}) tidak ditemukan.",
                    affected_entity=doc_key,
                    recommendation=f"Disarankan mengunggah {doc_name} untuk memperkuat cross-check.",
                )
            )

    return issues


def check_license_validity(
    valid_until_str: Optional[str],
    entity_name: str,
    license_type: str = "SIP",
    reference_date: Optional[date] = None,
) -> Optional[ValidationIssue]:
    """Rule VAL-01: Verifies whether license (SIP/SIB) validity is active, expiring soon, or expired."""
    ref_date = reference_date or date.today()

    if not valid_until_str:
        return ValidationIssue(
            rule_id=f"RULE-{license_type}-EXPIRATION",
            rule_name=f"Masa Berlaku {license_type}",
            category="masa_berlaku",
            severity=ValidationSeverity.WARNING,
            description=f"Masa berlaku {license_type} untuk '{entity_name}' tidak terdeteksi atau kosong.",
            affected_entity=entity_name,
            recommendation=f"Periksa dokumen fisik {license_type} untuk memastikan tanggal masa berlaku.",
        )

    parsed_date = parse_date_safe(valid_until_str)
    if not parsed_date:
        return ValidationIssue(
            rule_id=f"RULE-{license_type}-FORMAT",
            rule_name=f"Format Tanggal {license_type}",
            category="masa_berlaku",
            severity=ValidationSeverity.WARNING,
            description=f"Format masa berlaku {license_type} '{valid_until_str}' untuk '{entity_name}' tidak dapat diverifikasi secara otomatis.",
            affected_entity=entity_name,
            recommendation="Lakukan pengecekan manual pada dokumen perizinan terkait.",
        )

    days_remaining = (parsed_date - ref_date).days

    if days_remaining < 0:
        return ValidationIssue(
            rule_id=f"RULE-{license_type}-EXPIRED",
            rule_name=f"{license_type} Kedaluwarsa",
            category="masa_berlaku",
            severity=ValidationSeverity.CRITICAL,
            description=(
                f"{license_type} milik '{entity_name}' telah KEDALUWARSA pada tanggal "
                f"{parsed_date.strftime('%d/%m/%Y')} (lewat {abs(days_remaining)} hari)."
            ),
            affected_entity=entity_name,
            recommendation=f"Permohonan tidak dapat disetujui sampai {license_type} diperpanjang.",
        )

    if days_remaining <= 30:
        return ValidationIssue(
            rule_id=f"RULE-{license_type}-EXPIRING-SOON",
            rule_name=f"{license_type} Segera Berakhir",
            category="masa_berlaku",
            severity=ValidationSeverity.WARNING,
            description=(
                f"{license_type} milik '{entity_name}' akan SEGERA BERAKHIR pada "
                f"{parsed_date.strftime('%d/%m/%Y')} (tersisa {days_remaining} hari)."
            ),
            affected_entity=entity_name,
            recommendation=f"Ingatkan pemohon untuk segera memproses perpanjangan {license_type}.",
        )

    return None


def check_practice_location_compliance(
    person: PersonnelEntity,
    facility: FacilityEntity,
) -> Optional[ValidationIssue]:
    """Rule LOC-01: Verifies that SIP practice location aligns with the applicant facility."""
    sip_loc = person.practice_location.value if person.practice_location else ""
    fac_name = facility.project_name.value if facility.project_name else ""

    if not sip_loc or not fac_name:
        return None

    norm_sip = normalize_facility_name(sip_loc)
    norm_fac = normalize_facility_name(fac_name)

    # Check match ratio
    score = max(fuzz.token_sort_ratio(norm_sip, norm_fac), fuzz.token_set_ratio(norm_sip, norm_fac))
    if "," in sip_loc:
        parts = [p.strip() for p in sip_loc.split(",") if p.strip()]
        if parts:
            score = max(score, fuzz.token_set_ratio(norm_fac, normalize_facility_name(parts[0])))

    if score < 60.0 and norm_fac not in norm_sip and norm_sip not in norm_fac:
        return ValidationIssue(
            rule_id="RULE-SIP-LOCATION-MISMATCH",
            rule_name="Kesesuaian Tempat Praktik SIP",
            category="tempat_praktik",
            severity=ValidationSeverity.WARNING,
            description=(
                f"Tempat praktik pada SIP '{person.name.value}' tercantum '{sip_loc}', "
                f"berbeda dengan fasilitas pemohon '{fac_name}' (kemiripan {score:.1f}%)."
            ),
            affected_entity=person.name.value,
            recommendation="Evaluator perlu memastikan dokter/radiografer memiliki SIP aktif di fasilitas ini.",
        )
    return None


def check_equipment_compliance(equipment_list: List[XRayEquipmentEntity]) -> List[ValidationIssue]:
    """Rule EQ-01: Verifies that every X-Ray machine has valid serial numbers and paired tubes."""
    issues = []
    if not equipment_list:
        issues.append(
            ValidationIssue(
                rule_id="RULE-EQ-EMPTY",
                rule_name="Daftar Pesawat Sinar-X",
                category="peralatan",
                severity=ValidationSeverity.CRITICAL,
                description="Tidak ada unit pesawat sinar-X yang terdaftar dalam permohonan.",
                recommendation="Pastikan data pesawat sinar-X terisi dalam formulir permohonan.",
            )
        )
        return issues

    for idx, eq in enumerate(equipment_list, start=1):
        sn = eq.unit_serial_number.value if eq.unit_serial_number else ""
        brand = eq.unit_brand.value if eq.unit_brand else "Merk Tidak Diketahui"
        unit_label = f"Unit #{idx} ({brand})"

        if not sn:
            issues.append(
                ValidationIssue(
                    rule_id="RULE-EQ-MISSING-SN",
                    rule_name="Nomor Seri Pesawat Wajib",
                    category="peralatan",
                    severity=ValidationSeverity.CRITICAL,
                    description=f"{unit_label} tidak memiliki nomor seri pesawat yang teridentifikasi.",
                    affected_entity=eq.id,
                    recommendation="Nomor seri pesawat wajib dicantumkan dan diverifikasi terhadap foto label unit.",
                )
            )

        # Check tube
        if not eq.tube:
            issues.append(
                ValidationIssue(
                    rule_id="RULE-EQ-NO-TUBE",
                    rule_name="Tabung Sinar-X Terpasang",
                    category="peralatan",
                    severity=ValidationSeverity.WARNING,
                    description=f"{unit_label} tidak memiliki data tabung sinar-X yang terpasang.",
                    affected_entity=eq.id,
                    recommendation="Pastikan data tabung sinar-X (merk, tipe, dan nomor seri tabung) telah diunggah.",
                )
            )
        else:
            tube_sn = eq.tube.tube_serial_number.value if eq.tube.tube_serial_number else ""
            if not tube_sn:
                issues.append(
                    ValidationIssue(
                        rule_id="RULE-TUBE-MISSING-SN",
                        rule_name="Nomor Seri Tabung Sinar-X",
                        category="peralatan",
                        severity=ValidationSeverity.WARNING,
                        description=f"Tabung sinar-X pada {unit_label} tidak memiliki nomor seri.",
                        affected_entity=eq.tube.id,
                        recommendation="Verifikasi nomor seri tabung terhadap foto label tabung sinar-X.",
                    )
                )

    return issues


def check_ppr_compliance(ppr_list: List[PPREntity], reference_date: Optional[date] = None) -> List[ValidationIssue]:
    """Rule PPR-01: Verifies that the facility has designated at least one PPR with an active SIB."""
    issues = []
    if not ppr_list:
        issues.append(
            ValidationIssue(
                rule_id="RULE-PPR-MANDATORY",
                rule_name="Keharusan Petugas Proteksi Radiasi (PPR)",
                category="ppr",
                severity=ValidationSeverity.CRITICAL,
                description="Permohonan izin radiologi wajib memiliki minimal satu Petugas Proteksi Radiasi (PPR).",
                recommendation="Daftarkan PPR dan lampirkan SIB serta Surat Keputusan Penunjukan PPR (Sprint).",
            )
        )
        return issues

    for ppr in ppr_list:
        name = ppr.name.value or "PPR Tanpa Nama"
        valid_until = ppr.valid_until.value if ppr.valid_until else None
        issue = check_license_validity(valid_until, name, license_type="SIB", reference_date=reference_date)
        if issue:
            issues.append(issue)

    return issues


def evaluate_application_compliance(
    application: ApplicationEntity,
    uploaded_doc_types: List[str],
    reference_date: Optional[date] = None,
) -> ValidationReport:
    """Executes all BAPETEN regulatory rules and compiles a comprehensive ValidationReport."""
    issues: List[ValidationIssue] = []

    # 1. Mandatory Document Check
    issues.extend(check_mandatory_documents(uploaded_doc_types))

    # 2. PPR Compliance
    issues.extend(check_ppr_compliance(application.ppr, reference_date=reference_date))

    # 3. Personnel Compliance (SIP validity & Practice Location for non-PPR medical staff)
    for person in application.personnel:
        prof_text = (person.profession.value if person.profession else "").upper()
        if "PPR" in prof_text or "PROTEKSI" in prof_text:
            continue  # PPR compliance is evaluated via SIB & Sprint in check_ppr_compliance

        p_name = person.name.value or "Personel Tanpa Nama"
        valid_str = person.valid_until.value if person.valid_until else None
        valid_issue = check_license_validity(valid_str, p_name, license_type="SIP", reference_date=reference_date)
        if valid_issue:
            issues.append(valid_issue)

        loc_issue = check_practice_location_compliance(person, application.facility)
        if loc_issue:
            issues.append(loc_issue)

    # 4. Equipment Compliance
    issues.extend(check_equipment_compliance(application.xray_equipment))

    critical_count = sum(1 for i in issues if i.severity == ValidationSeverity.CRITICAL)
    warning_count = sum(1 for i in issues if i.severity == ValidationSeverity.WARNING)
    info_count = sum(1 for i in issues if i.severity == ValidationSeverity.INFO)

    return ValidationReport(
        is_compliant=(critical_count == 0),
        total_rules_evaluated=5,
        total_issues=len(issues),
        critical_count=critical_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=issues,
    )
