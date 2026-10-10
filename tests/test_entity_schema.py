"""Unit tests for entity schemas, multi-entity cardinality, and cross-check report structures."""

import json
from src.schema import (
    EvidenceSource,
    ExtractedField,
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayTubeEntity,
    XRayEquipmentEntity,
    ApplicationEntity,
    MatchingStatus,
    SourceEvidence,
    FieldCrossCheck,
    EntityCrossCheck,
    MatchSummary,
    CrossCheckReport,
)


def test_extracted_field_with_evidence():
    field = ExtractedField[str].from_value(
        value="SB2002000027WK",
        document_type="label_unit",
        file_name="foto_label.jpg",
        page=1,
        confidence=0.98,
        extraction_method="ocr_paddle",
    )
    assert field.is_present is True
    assert field.value == "SB2002000027WK"
    assert field.evidence.document_type == "label_unit"
    assert field.evidence.confidence == 0.98


def test_multi_entity_application():
    """Verify that 1 Application can hold multiple Personnel and multiple X-Ray units."""
    facility = FacilityEntity(
        id="fac_01",
        project_name=ExtractedField(value="RS Sehat Bugar"),
        project_address=ExtractedField(value="Jl. Kesehatan No. 10 Jakarta"),
    )

    person1 = PersonnelEntity(
        id="person_1",
        name=ExtractedField(value="Dr. Budi Santoso, Sp.Rad"),
        profession=ExtractedField(value="Dokter Spesialis Radiologi"),
        sip_number=ExtractedField(value="SIP/123/2024"),
    )
    person2 = PersonnelEntity(
        id="person_2",
        name=ExtractedField(value="Siti Rahma, A.Md.Rad"),
        profession=ExtractedField(value="Radiografer"),
    )

    ppr1 = PPREntity(
        id="ppr_1",
        name=ExtractedField(value="Ahmad Fauzi"),
        sib_number=ExtractedField(value="SIB-PPR-987"),
    )

    unit1 = XRayEquipmentEntity(
        id="unit_1",
        unit_brand=ExtractedField(value="SHIMADZU"),
        unit_type=ExtractedField(value="RADspeed Pro"),
        unit_serial_number=ExtractedField(value="SN-SHIM-001"),
        tube=XRayTubeEntity(
            id="tube_1",
            tube_brand=ExtractedField(value="CANON"),
            tube_type=ExtractedField(value="Circlex"),
            tube_model=ExtractedField(value="CX-123"),
            tube_serial_number=ExtractedField(value="TB-CANON-999"),
        ),
    )

    unit2 = XRayEquipmentEntity(
        id="unit_2",
        unit_brand=ExtractedField(value="SIEMENS"),
        unit_type=ExtractedField(value="Multix Impact"),
        unit_serial_number=ExtractedField(value="SN-SIEM-002"),
    )

    app = ApplicationEntity(
        application_id="REG-2026-BAPETEN-001",
        facility=facility,
        personnel=[person1, person2],
        ppr=[ppr1],
        xray_equipment=[unit1, unit2],
    )

    assert len(app.personnel) == 2
    assert len(app.xray_equipment) == 2
    assert app.xray_equipment[0].tube.tube_brand.value == "CANON"
    assert app.xray_equipment[1].tube is None

    # Test JSON serialization roundtrip
    json_data = app.model_dump_json()
    reloaded = ApplicationEntity.model_validate_json(json_data)
    assert reloaded.application_id == "REG-2026-BAPETEN-001"
    assert len(reloaded.personnel) == 2


def test_cross_check_report_structure():
    """Verify that CrossCheckReport correctly structures evidence per field and summary."""
    field_check = FieldCrossCheck(
        field_key="unit_serial_number",
        field_label="Nomor Seri Unit",
        status=MatchingStatus.SESUAI,
        score=100.0,
        reason="Nilai identik pada seluruh dokumen",
        sources=[
            SourceEvidence(
                document_type="formulir",
                document_name="Formulir.pdf",
                page=2,
                value="SB2002000027WK",
            ),
            SourceEvidence(
                document_type="label_unit",
                document_name="label.jpg",
                page=1,
                value="SB2002000027WK",
                confidence=0.96,
            ),
        ],
    )

    xray_check = EntityCrossCheck(
        category="xray_equipment",
        entity_id="unit_1",
        entity_label="Pesawat Sinar-X Unit #1 (SHIMADZU / SB2002000027WK)",
        status=MatchingStatus.SESUAI,
        fields={"unit_serial_number": field_check},
    )

    report = CrossCheckReport(
        run_id="run_abc123",
        application_id="REG-001",
        xray_equipment=[xray_check],
        summary=MatchSummary(
            total_fields_checked=1,
            sesuai=1,
            perlu_review=0,
            tidak_sesuai=0,
            tidak_ditemukan=0,
        ),
    )

    report_dict = report.model_dump()
    assert report_dict["run_id"] == "run_abc123"
    assert report_dict["summary"]["sesuai"] == 1
    assert len(report_dict["xray_equipment"][0]["fields"]["unit_serial_number"]["sources"]) == 2
