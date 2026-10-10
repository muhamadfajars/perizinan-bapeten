"""Unit tests for BAPETEN regulatory compliance validation rules."""

from datetime import date
from src.validation.rules import (
    ValidationSeverity,
    check_mandatory_documents,
    check_license_validity,
    check_practice_location_compliance,
    check_equipment_compliance,
    check_ppr_compliance,
    evaluate_application_compliance,
    parse_date_safe,
)
from src.schema.entities import (
    ApplicationEntity,
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayEquipmentEntity,
    XRayTubeEntity,
)
from src.schema.evidence import ExtractedField


def test_parse_date_safe():
    assert parse_date_safe("15/08/2026") == date(2026, 8, 15)
    assert parse_date_safe("31-12-2027") == date(2027, 12, 31)
    assert parse_date_safe("2028-05-20") == date(2028, 5, 20)
    assert parse_date_safe("3 Agustus 2026") == date(2026, 8, 3)
    assert parse_date_safe("invalid-date") is None


def test_check_mandatory_documents():
    # Incomplete upload: only formulir uploaded
    issues = check_mandatory_documents(["formulir"])
    crit_issues = [i for i in issues if i.severity == ValidationSeverity.CRITICAL]
    crit_keys = {i.affected_entity for i in crit_issues}
    assert "ppkr" in crit_keys
    assert "sib" in crit_keys
    assert "sip" in crit_keys

    # Complete mandatory upload
    complete_upload = ["formulir", "ppkr", "sib", "sip"]
    issues_complete = check_mandatory_documents(complete_upload)
    crit_complete = [i for i in issues_complete if i.severity == ValidationSeverity.CRITICAL]
    assert len(crit_complete) == 0


def test_check_license_validity():
    ref_date = date(2026, 10, 1)

    # Active valid license (valid until 2027)
    issue_valid = check_license_validity("31/12/2027", "Dr. Budi", license_type="SIP", reference_date=ref_date)
    assert issue_valid is None

    # Expiring soon (within 20 days of ref_date: 2026-10-20)
    issue_soon = check_license_validity("20/10/2026", "Dr. Budi", license_type="SIP", reference_date=ref_date)
    assert issue_soon is not None
    assert issue_soon.severity == ValidationSeverity.WARNING
    assert "SEGERA BERAKHIR" in issue_soon.description

    # Expired license (expired in 2025)
    issue_expired = check_license_validity("15/01/2025", "Dr. Budi", license_type="SIP", reference_date=ref_date)
    assert issue_expired is not None
    assert issue_expired.severity == ValidationSeverity.CRITICAL
    assert "KEDALUWARSA" in issue_expired.description


def test_check_practice_location_compliance():
    facility = FacilityEntity(
        id="fac_1",
        project_name=ExtractedField(value="RS Harapan Sehat"),
    )

    # Aligned practice location
    p_aligned = PersonnelEntity(
        id="p1",
        name=ExtractedField(value="Dr. Andi"),
        profession=ExtractedField(value="Dokter"),
        practice_location=ExtractedField(value="Rumah Sakit Harapan Sehat"),
    )
    assert check_practice_location_compliance(p_aligned, facility) is None

    # Mismatched practice location
    p_mismatched = PersonnelEntity(
        id="p2",
        name=ExtractedField(value="Dr. Andi"),
        profession=ExtractedField(value="Dokter"),
        practice_location=ExtractedField(value="RS Medika Pratama"),
    )
    issue = check_practice_location_compliance(p_mismatched, facility)
    assert issue is not None
    assert issue.severity == ValidationSeverity.WARNING
    assert "berbeda" in issue.description


def test_check_equipment_compliance():
    # Unit missing serial number
    eq_no_sn = [
        XRayEquipmentEntity(
            id="unit_1",
            unit_brand=ExtractedField(value="SHIMADZU"),
            unit_type=ExtractedField(value="RADspeed"),
            unit_serial_number=ExtractedField(value=""),
        )
    ]
    issues = check_equipment_compliance(eq_no_sn)
    crit = [i for i in issues if i.severity == ValidationSeverity.CRITICAL]
    assert len(crit) == 1
    assert "nomor seri" in crit[0].description.lower()

    # Unit with no tube attached
    warn = [i for i in issues if i.severity == ValidationSeverity.WARNING]
    assert any("tabung" in w.description.lower() for w in warn)


def test_check_ppr_compliance():
    # Empty PPR list
    issues_empty = check_ppr_compliance([])
    assert len(issues_empty) == 1
    assert issues_empty[0].severity == ValidationSeverity.CRITICAL

    # PPR with active SIB
    ppr_ok = [
        PPREntity(
            id="ppr_1",
            name=ExtractedField(value="Bambang"),
            valid_until=ExtractedField(value="31/12/2028"),
        )
    ]
    issues_ok = check_ppr_compliance(ppr_ok, reference_date=date(2026, 10, 1))
    assert len(issues_ok) == 0


def test_evaluate_application_compliance_overall():
    ref_date = date(2026, 10, 1)
    facility = FacilityEntity(
        id="fac_1",
        project_name=ExtractedField(value="RS Sehat Bugar"),
    )
    ppr1 = PPREntity(
        id="ppr_1",
        name=ExtractedField(value="Ahmad"),
        valid_until=ExtractedField(value="31/12/2028"),
    )
    p1 = PersonnelEntity(
        id="p_1",
        name=ExtractedField(value="Dr. Budi"),
        profession=ExtractedField(value="Dokter"),
        valid_until=ExtractedField(value="31/12/2028"),
        practice_location=ExtractedField(value="RS Sehat Bugar"),
    )
    eq1 = XRayEquipmentEntity(
        id="unit_1",
        unit_brand=ExtractedField(value="SHIMADZU"),
        unit_type=ExtractedField(value="RADspeed"),
        unit_serial_number=ExtractedField(value="SN-123456"),
        tube=XRayTubeEntity(
            id="tube_1",
            tube_brand=ExtractedField(value="CANON"),
            tube_type=ExtractedField(value="Circlex"),
            tube_serial_number=ExtractedField(value="TB-987"),
        ),
    )

    app = ApplicationEntity(
        application_id="REG-001",
        facility=facility,
        personnel=[p1],
        ppr=[ppr1],
        xray_equipment=[eq1],
    )

    # All mandatory uploaded & valid licenses -> is_compliant is True
    uploaded = ["formulir", "ppkr", "sib", "sip"]
    report = evaluate_application_compliance(app, uploaded, reference_date=ref_date)
    assert report.is_compliant is True
    assert report.critical_count == 0
