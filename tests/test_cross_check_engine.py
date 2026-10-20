"""Unit tests for the Multi-Entity Cross-Check Engine."""

from src.matching.cross_check_engine import (
    compare_two_values,
    evaluate_field_sources,
    generate_cross_check_report,
    cross_check_facility,
)
from src.schema import (
    MatchingStatus,
    SourceEvidence,
    ApplicationEntity,
    FacilityEntity,
    PersonnelEntity,
    PPREntity,
    XRayEquipmentEntity,
    XRayTubeEntity,
    ExtractedField,
)


def test_compare_two_values_serial():
    # Identical serials
    score, status, _ = compare_two_values("SB2002000027WK", "SB2002000027WK", mode="serial")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # OCR normalized identical serials (O vs 0)
    score, status, _ = compare_two_values("SB20020OOO27WK", "SB2002000027WK", mode="serial")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # Minor typo (high similarity, needs review)
    score, status, _ = compare_two_values("SB2002000027WK", "SB2002000027WA", mode="serial")
    assert status == MatchingStatus.PERLU_REVIEW

    # Completely different serials
    score, status, _ = compare_two_values("SB2002000027WK", "SN-9988776655", mode="serial")
    assert status == MatchingStatus.TIDAK_SESUAI


def test_compare_two_values_brand():
    # Canonical brand alias matching
    score, status, _ = compare_two_values("SHIMADZU CORPORATION", "SHIMADZU", mode="brand")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    score, status, _ = compare_two_values("GE HEALTHCARE", "GENERAL ELECTRIC", mode="brand")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # Different brands
    score, status, _ = compare_two_values("SHIMADZU", "SIEMENS", mode="brand")
    assert status == MatchingStatus.TIDAK_SESUAI


def test_compare_two_values_facility_name():
    # RSJ vs Rumah Sakit Jiwa
    score, status, _ = compare_two_values("Rumah Sakit Jiwa Aceh", "RSJ. Aceh", mode="facility_name")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # OCR glued spacing (JIWAACEH vs JIWA ACEH)
    score, status, _ = compare_two_values("Rumah Sakit Jiwa Aceh", "RUMAH SAKIT JIWAACEH", mode="facility_name")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # Suffix equipment name tolerance
    score, status, _ = compare_two_values("Rumah Sakit Jiwa Aceh", "RS Jiwa Aceh Equipment Name", mode="facility_name")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0


def test_compare_two_values_name_with_titles():
    # Name with doctor and specialist titles
    score, status, _ = compare_two_values(
        "Dr. Andi Wijaya, Sp.Rad", "dr. Andi Wijaya", mode="fuzzy_name"
    )
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # Different names
    score, status, _ = compare_two_values("Dr. Andi Wijaya", "Budi Santoso", mode="fuzzy_name")
    assert status == MatchingStatus.TIDAK_SESUAI


def test_evaluate_field_sources():
    # Single document source
    single_source = [
        SourceEvidence(
            document_type="formulir",
            document_name="Formulir.pdf",
            page=1,
            value="RS Sehat Bugar",
        )
    ]
    res_single = evaluate_field_sources("project_name", "Nama Fasilitas", single_source)
    assert res_single.status == MatchingStatus.TIDAK_DITEMUKAN
    assert len(res_single.sources) == 1

    # Multiple matching sources (with abbreviation RS vs Rumah Sakit)
    multi_sources = [
        SourceEvidence(document_type="formulir", document_name="Formulir.pdf", page=1, value="RS Sehat Bugar"),
        SourceEvidence(document_type="ppkr", document_name="PPKR.pdf", page=2, value="RS Sehat Bugar"),
        SourceEvidence(document_type="sprint", document_name="Sprint.pdf", page=1, value="Rumah Sakit Sehat Bugar"),
    ]
    res_multi = evaluate_field_sources("project_name", "Nama Fasilitas", multi_sources, mode="facility_name")
    assert res_multi.status == MatchingStatus.SESUAI
    assert len(res_multi.sources) == 3

    # Conflicting serial sources
    conflicting_sources = [
        SourceEvidence(document_type="formulir", document_name="Formulir.pdf", page=3, value="SB2002000027WK"),
        SourceEvidence(document_type="label_unit", document_name="Label.jpg", page=1, value="DIFFERENT-SN-999"),
    ]
    res_conflict = evaluate_field_sources("unit_serial_number", "No Seri Unit", conflicting_sources, mode="serial")
    assert res_conflict.status == MatchingStatus.TIDAK_SESUAI
    assert len(res_conflict.discrepancies) > 0


def test_generate_cross_check_report():
    """Verify end-to-end multi-entity report generation."""
    facility = FacilityEntity(
        id="fac_1",
        project_name=ExtractedField(value="RS Harapan Bangsa"),
        project_address=ExtractedField(value="Jl. Sudirman No. 10"),
    )

    person1 = PersonnelEntity(
        id="person_1",
        name=ExtractedField.from_value(
            value="Dr. Budi Santoso, Sp.Rad",
            document_type="formulir",
            file_name="Form.pdf",
        ),
        profession=ExtractedField(value="Dokter Spesialis Radiologi"),
    )

    ppr1 = PPREntity(
        id="ppr_1",
        name=ExtractedField.from_value(
            value="Siti Aminah",
            document_type="formulir",
            file_name="Form.pdf",
        ),
    )

    unit1 = XRayEquipmentEntity(
        id="unit_1",
        unit_brand=ExtractedField.from_value(
            value="SHIMADZU",
            document_type="formulir",
            file_name="Form.pdf",
        ),
        unit_type=ExtractedField.from_value(
            value="RADspeed Pro",
            document_type="formulir",
            file_name="Form.pdf",
        ),
        unit_serial_number=ExtractedField.from_value(
            value="SB2002000027WK",
            document_type="formulir",
            file_name="Form.pdf",
        ),
        tube=XRayTubeEntity(
            id="tube_1",
            tube_brand=ExtractedField(value="CANON"),
            tube_type=ExtractedField(value="Circlex"),
            tube_serial_number=ExtractedField(value="TB-9988"),
        ),
    )

    app = ApplicationEntity(
        application_id="APP-TEST-001",
        facility=facility,
        personnel=[person1],
        ppr=[ppr1],
        xray_equipment=[unit1],
    )

    extractions = {
        "formulir": [
            {
                "file_name": "Form.pdf",
                "fields": {
                    "hospital_name": {"value": "RS Harapan Bangsa", "page": 1},
                    "hospital_address": {"value": "Jl. Sudirman No. 10", "page": 1},
                },
            }
        ],
        "sip": [
            {
                "file_name": "SIP_Budi.pdf",
                "fields": {
                    "person_name": {"value": "dr. Budi Santoso", "page": 1},
                    "profession": {"value": "Dokter Spesialis Radiologi", "page": 1},
                },
            }
        ],
        "sib": [
            {
                "file_name": "SIB_Siti.pdf",
                "fields": {
                    "ppr_name": {"value": "Siti Aminah", "page": 1},
                    "valid_until": {"value": "31/12/2027", "page": 1},
                },
            }
        ],
        "label_unit": [
            {
                "file_name": "Label_Shimadzu.jpg",
                "fields": {
                    "unit_brand": {"value": "SHIMADZU CORPORATION", "method": "ocr"},
                    "unit_type": {"value": "RADspeed Pro", "method": "ocr"},
                    "unit_serial_number": {"value": "SB2002000027WK", "method": "ocr"},
                },
            }
        ],
    }

    report = generate_cross_check_report(app, extractions, run_id="run_test_123")

    assert report.run_id == "run_test_123"
    assert report.application_id == "APP-TEST-001"
    assert len(report.personnel) == 1
    p0 = report.personnel[0]
    assert p0.fields["person_name"].status == MatchingStatus.SESUAI
    assert len(p0.fields["person_name"].sources) == 2
    assert "profession" in p0.fields
    assert "ppr_name" in p0.fields
    assert "valid_until" in p0.fields
    assert "practice_location" in p0.fields

    assert len(report.ppr) == 1
    assert report.ppr[0].fields["ppr_name"].status == MatchingStatus.SESUAI

    assert len(report.xray_equipment) == 1
    eq0 = report.xray_equipment[0]
    assert eq0.fields["unit_serial_number"].status == MatchingStatus.SESUAI
    assert eq0.fields["unit_brand"].status == MatchingStatus.SESUAI
    assert "unit_type" in eq0.fields

    # Section 4: Tabung Sinar-X
    assert len(report.xray_tubes) == 1
    tb0 = report.xray_tubes[0]
    assert "tube_brand" in tb0.fields
    assert "tube_type" in tb0.fields
    assert "tube_serial_number" in tb0.fields

    # Section 1: Identitas Fasilitas
    assert report.facility is not None
    assert "project_name" in report.facility.fields
    assert "project_address" in report.facility.fields

    assert report.summary.total_fields_checked > 0
    assert report.summary.sesuai > 0
    assert report.summary.tidak_sesuai == 0


def test_evaluate_practice_location_against_facility():
    from src.matching.cross_check_engine import evaluate_practice_location_against_facility

    fac_name = "Rumkit Tentara Tk IV 01.07.04 Pekanbaru"
    fac_addr = "Rumkit Tentara Tk IV 01.07.04 Pekanbaru, Jl. Kesehatan No. 2 Kampung"

    # User case: SIP practice location has hospital name + street address
    loc_val = "RS Tk. IV Pekanbaru, Jl. Kesehatan No. 2 Desa/Kel. Kampung"
    score, status, _ = evaluate_practice_location_against_facility(fac_name, fac_addr, loc_val)
    assert status == MatchingStatus.SESUAI
    assert score >= 85.0

    # Only hospital name
    score, status, _ = evaluate_practice_location_against_facility(fac_name, fac_addr, "RS Tk. IV Pekanbaru")
    assert status == MatchingStatus.SESUAI
    assert score == 100.0

    # Only address
    score, status, _ = evaluate_practice_location_against_facility(fac_name, fac_addr, "Jl. Kesehatan No. 2 Pekanbaru")
    assert status == MatchingStatus.SESUAI
    assert score >= 85.0

    # Completely different location
    score, status, _ = evaluate_practice_location_against_facility(fac_name, fac_addr, "RS Siloam Lippo Karawaci Tangerang")
    assert status == MatchingStatus.TIDAK_SESUAI
    assert score < 60.0


def test_cross_check_facility_labels_and_formulir_instansi():
    from src.matching.cross_check_engine import cross_check_facility
    from src.extraction.form_parser import extract_form_data, build_application_from_form

    # Simulate Formulir text with Instansi, Alamat Instansi, Nama Proyek, Alamat Proyek
    pages_text = [
        "Instansi : Rumkit Tentara Tk IV 01.07.04 Pekanbaru\n"
        "Alamat Instansi : Rumkit Tentara Tk IV 01.07.04 Pekanbaru, Jl. Kesehatan No. 2 Kampung\n"
        "Nama Proyek : Aktivitas Rumah Sakit Pemerintah\n"
        "Alamat Proyek : RS Tk. IV Pekanbaru, Jl. Kesehatan No. 2 , Kota Pekanbaru Riau"
    ]
    parsed = extract_form_data([], pages_text)
    # Facility name must come from Alamat Proyek prefix (e.g. RS Tk. IV Pekanbaru)
    assert parsed["hospital_name"]["value"] == "RS Tk. IV Pekanbaru"
    # Facility address must come from Alamat Proyek suffix (e.g. Jl. Kesehatan No. 2 , Kota Pekanbaru Riau)
    assert parsed["hospital_address"]["value"] == "Jl. Kesehatan No. 2 , Kota Pekanbaru Riau"

    app = build_application_from_form(parsed)
    assert app.facility.project_name.value == "RS Tk. IV Pekanbaru"
    assert app.facility.project_address.value == "Jl. Kesehatan No. 2 , Kota Pekanbaru Riau"
    assert app.facility.institution_name.value == "Rumkit Tentara Tk IV 01.07.04 Pekanbaru"

    # Cross check facility and check field labels
    extractions = {
        "formulir": [{
            "file_name": "formulir.pdf",
            "fields": {
                "hospital_name": parsed["hospital_name"],
                "hospital_address": parsed["hospital_address"],
            }
        }],
        "sistem_manajemen": [{
            "file_name": "sistem_manajemen.pdf",
            "fields": {
                "hospital_name": {"value": "RS TK IV PEKANBARU", "page": 1},
                "hospital_address": {"value": "Jl.Kesehatan no 2 Pekanbaru Riau", "page": 2},
            }
        }],
    }

    fac_check = cross_check_facility(app.facility, extractions)
    assert fac_check.fields["project_name"].field_label == "Nama instansi"
    assert fac_check.fields["project_address"].field_label == "Alamat instansi"
    assert fac_check.fields["project_name"].status == MatchingStatus.SESUAI
    assert fac_check.fields["project_address"].status == MatchingStatus.SESUAI


def test_address_matching_tolerance_for_9_documents():
    """Verifies that the 9 documents from real BAPETEN evaluation all match as SESUAI
    despite variations in granularity, abbreviations, and formatting.
    """
    doc_address_pairs = [
        ("formulir", "formulir_1.pdf", "Rumkit Tentara Tk IV 01.07.04 Pekanbaru, Jl. Kesehatan No. 2 Kampung"),
        ("sprint", "sprint_1.pdf", "JL Kesehatan No.2 - Pekanbaru"),
        ("tld", "tld_1.pdf", "Jl. Kesehatan No. 2"),
        ("sistem_manajemen", "sistem_manajemen_1.pdf", "Jl.Kesehatanno2PekanbaruRiau"),
        ("program_perawatan", "program_perawatan_1.pdf", "Jl.Kesehatanno2PekanbaruRiau"),
        ("ppkr", "ppkr_1.pdf", "Jl.Kesehatanno.02"),
        ("paparan_radiasi", "paparan_radiasi_1.pdf", "Jl. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau"),
        ("uji_fungsi", "uji_fungsi_1.pdf", "Jl. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau"),
        ("uji_kesesuaian", "uji_kesesuaian_1.pdf", "Jl. Kesehatan No.2, RT.01/RW.06, Kp. Bandar, Senapelan, Kota Pekanbaru, Riau"),
    ]

    extractions = {}
    for doc_type, file_name, addr_val in doc_address_pairs:
        extractions[doc_type] = [{
            "file_name": file_name,
            "fields": {
                "hospital_name": {"value": "Rumkit Tentara Tk IV 01.07.04 Pekanbaru", "page": 1},
                "hospital_address": {"value": addr_val, "page": 1},
            }
        }]

    facility = FacilityEntity(
        id="fac_1",
        project_name=ExtractedField(value="Rumkit Tentara Tk IV 01.07.04 Pekanbaru"),
        project_address=ExtractedField(value=doc_address_pairs[0][2]),
    )

    fac_check = cross_check_facility(facility, extractions)
    addr_check = fac_check.fields["project_address"]

    assert addr_check.status == MatchingStatus.SESUAI
    assert addr_check.score >= 95.0
    assert len(addr_check.sources) == 9
    assert fac_check.status == MatchingStatus.SESUAI


def test_address_mismatch_and_conflicting_numbers():
    """Conflicting street numbers or completely different locations must NOT match as SESUAI."""
    # Differing street number on the same street
    score, status, exp = compare_two_values(
        "Jl. Kesehatan No. 2 Pekanbaru",
        "Jl. Kesehatan No. 8 Pekanbaru",
        mode="fuzzy_address",
    )
    assert status == MatchingStatus.PERLU_REVIEW
    assert "Nomor alamat berbeda" in exp

    # Completely different cities/streets
    score, status, exp = compare_two_values(
        "Jl. Kesehatan No. 2 Pekanbaru",
        "Jl. Sudirman No. 10 Jakarta",
        mode="fuzzy_address",
    )
    assert status == MatchingStatus.TIDAK_SESUAI


def test_cross_check_tubes_insert_housing_and_brand_tolerance():
    """Verify that:
    1. Canon brand is evaluated as SESUAI even if functional test recorded system brand GE.
    2. E7894 vs E7894X is evaluated as SESUAI without being polluted by serial numbers.
    3. Insert serial (0F1376) matching label and uji kesesuaian evaluates as PERLU_REVIEW
       (not TIDAK_SESUAI) when secondary docs record housing serial (20G225).
    4. Documents for different unit serials do not pollute tube cross check.
    """
    from src.matching.cross_check_engine import cross_check_tubes

    unit = XRayEquipmentEntity(
        id="unit_1",
        unit_brand=ExtractedField(value="GE"),
        unit_type=ExtractedField(value="Optima XR200amx"),
        unit_serial_number=ExtractedField(value="SB2002000027WK"),
        tube=XRayTubeEntity(
            id="tube_1",
            tube_brand=ExtractedField(value="Canon"),
            tube_type=ExtractedField(value="E7894"),
            tube_serial_number=ExtractedField(value="0F1376"),
        ),
    )

    extractions = {
        "ppkr": [{
            "file_name": "ppkr_1.pdf",
            "fields": {
                "unit_serial_number": {"value": "SB2002000027WK"},
                "tube_brand": {"value": "CANON"},
                "tube_type": {"value": "E7894X"},
            },
        }],
        "label_tabung": [{
            "file_name": "label_tabung_1.jpeg",
            "fields": {
                "tube_brand": {"value": "CANDN ELECTRON TUBES & DEVICES CO., LTD."},
                "tube_type": {"value": "E7894"},
                "tube_serial_number": {"value": "0F1376"},
            },
        }],
        "uji_kesesuaian": [{
            "file_name": "uji_kesesuaian_1.pdf",
            "fields": {
                "unit_serial_number": {"value": "SB2002000027WK"},
                "tube_brand": {"value": "CANON"},
                "tube_type": {"value": "E7894"},
                "tube_serial_number": {"value": "0F1376"},
            },
        }],
        "paparan_radiasi": [{
            "file_name": "paparan_radiasi_1.pdf",
            "fields": {
                "unit_serial_number": {"value": "SB2002000027WK"},
                "tube_brand": {"value": "CANON"},
                "tube_type": {"value": "E7894X"},
                "tube_serial_number": {"value": "20G225"},
            },
        }],
        "uji_fungsi": [{
            "file_name": "uji_fungsi_1.pdf",
            "fields": {
                "unit_serial_number": {"value": "SB2002000027WK"},
                "tube_brand": {"value": "GE"},  # system brand fallback
                "tube_type": {"value": "E7894"},
                "tube_serial_number": {"value": "20G225"},
            },
        }],
        "persetujuan_import": [{
            "file_name": "persetujuan_import_1.pdf",
            "fields": {
                # Different unit serial number -> should be ignored for this unit's tube!
                "unit_serial_number": {"value": "System SB2002000019WK"},
                "tube_type_serial": {"value": "20G130"},
                "tube_serial_number": {"value": "20G130"},
            },
        }],
    }

    tube_checks = cross_check_tubes([unit], extractions)
    assert len(tube_checks) == 1
    tc = tube_checks[0]

    # Overall should be PERLU_REVIEW (not fatal TIDAK_SESUAI)
    assert tc.status == MatchingStatus.PERLU_REVIEW

    # Tube Brand: SESUAI (100%)
    b_chk = tc.fields["tube_brand"]
    assert b_chk.status == MatchingStatus.SESUAI
    assert b_chk.score == 100.0

    # Tube Type: SESUAI (90+%)
    t_chk = tc.fields["tube_type"]
    assert t_chk.status == MatchingStatus.SESUAI
    assert t_chk.score >= 90.0

    # Tube Serial: PERLU_REVIEW (with 85% review score)
    s_chk = tc.fields["tube_serial_number"]
    assert s_chk.status == MatchingStatus.PERLU_REVIEW
    assert s_chk.score >= 85.0
    assert "0F1376" in s_chk.reason

def test_multi_equipment_consolidation_and_cross_check():
    """Verify that multiple equipment units from formulir are properly consolidated
    and evaluated independently without cross-contaminating other units."""
    extractions = {
        "formulir": [
            {
                "file_name": "Formulir_Permohonan.pdf",
                "fields": {
                    "hospital_name": {"value": "Medika Loka Kepanjen", "page": 1},
                    "hospital_address": {"value": "Kepanjen, Malang", "page": 1},
                    "all_xray_rows": [
                        {
                            "unit_brand": "United Imaging Healthcare",
                            "unit_type": "uDR 566i-A",
                            "unit_serial_number": "294248",
                            "tube_brand": "Canon",
                            "tube_type": "E7876",
                            "tube_serial_number": "25D1063",
                            "page": 2,
                        },
                        {
                            "unit_brand": "United Imaging Healthcare",
                            "unit_type": "uDR 380i",
                            "unit_serial_number": "422867",
                            "tube_brand": "Canon",
                            "tube_type": "XRR-3332",
                            "tube_serial_number": "4K0493",
                            "page": 2,
                        },
                    ],
                },
            }
        ],
        "uji_kesesuaian": [
            {
                "file_name": "uji_kesesuaian_unit1.pdf",
                "fields": {
                    "unit_brand": {"value": "United Imaging Healthcare", "page": 1},
                    "unit_type": {"value": "uDR 566i-A", "page": 1},
                    "unit_serial_number": {"value": "294248", "page": 1},
                    "tube_brand": {"value": "Canon", "page": 1},
                    "tube_type": {"value": "E7876", "page": 1},
                    "tube_serial_number": {"value": "25D1063", "page": 1},
                },
            }
        ],
    }

    from src.extraction.entity_builder import consolidate_application
    app = consolidate_application(extractions)

    assert len(app.xray_equipment) == 2
    assert app.xray_equipment[0].unit_serial_number.value == "294248"
    assert app.xray_equipment[0].tube.tube_serial_number.value == "25D1063"
    assert app.xray_equipment[1].unit_serial_number.value == "422867"
    assert app.xray_equipment[1].tube.tube_serial_number.value == "4K0493"

    report = generate_cross_check_report(app, extractions, run_id="multi_eq_run")
    assert len(report.xray_equipment) == 2
    assert len(report.xray_tubes) == 2

    # Unit 1 matches with uji_kesesuaian
    assert report.xray_equipment[0].fields["unit_serial_number"].status == MatchingStatus.SESUAI
    assert len(report.xray_equipment[0].fields["unit_serial_number"].sources) == 2

    # Unit 2 does NOT get contaminated with Unit 1's certificate
    assert len(report.xray_equipment[1].fields["unit_serial_number"].sources) == 1
    assert report.xray_equipment[1].fields["unit_serial_number"].sources[0].value == "422867"
    assert len(report.xray_tubes[1].fields["tube_serial_number"].sources) == 1
    assert report.xray_tubes[1].fields["tube_serial_number"].sources[0].value == "4K0493"


def test_cross_check_with_laporan_dosis_and_gedung_penahan_radiasi():
    extractions = {
        "formulir": [
            {
                "file_name": "formulir.pdf",
                "fields": {
                    "hospital_name": {"value": "RS. Hermina Kepanjen", "page": 1},
                    "hospital_address": {"value": "Jalan Raya Mojosari, RT 02/RW 01, Kel. Mojosari, Kec. Kepanjen, Kab. Malang", "page": 1},
                    "header": {
                        "Alamat Proyek": "RS. Hermina Kepanjen, Jalan Raya Mojosari, RT 02/RW 01, Kel. Mojosari, Kec. Kepanjen, Kab. Malang",
                    },
                    "personnel_data": {
                        "value": [
                            {"name": "dr. Dhanti Erma Widiasi, Sp.Rad", "profession": "Dokter Spesialis Radiologi"},
                            {"name": "Siti Azizah", "profession": "Radiografer"},
                        ]
                    },
                },
            }
        ],
        "laporan_dosis_awal": [
            {
                "file_name": "laporan_osl.pdf",
                "fields": {
                    "hospital_name": {"value": "Rumah Sakit Hermina Kepanjen", "page": 1},
                    "hospital_address": {"value": "Jalan Raya Mojosari, RT. 02/ RW. 01, Kec. Kepanjen, Kab. Malang", "page": 1},
                    "usage_period": {"value": "Oktober - Desember 2026", "page": 1},
                    "person_name": {"value": "dr. Dhanti Erma Widiasi", "page": 1},
                    "all_personnel": ["dr. Dhanti Erma Widiasi", "Siti Azizah", "Shofayana Wardatul Jamilah"],
                },
            }
        ],
        "gedung_penahan_radiasi": [
            {
                "file_name": "rencana_teknis.pdf",
                "fields": {
                    "hospital_name": {"value": "RS HERMINA KEPANJEN", "page": 2},
                    "hospital_address": {"value": "Jl. Raya Mojosari RT 02/01, Kecamatan Kepanjen Kabupaten Malang", "page": 2},
                },
            }
        ],
    }

    from src.extraction.entity_builder import consolidate_application
    app = consolidate_application(extractions)

    report = generate_cross_check_report(app, extractions, run_id="hermina_batch")

    fac_name_sources = [s.document_type for s in report.facility.fields["project_name"].sources]
    assert "formulir" in fac_name_sources
    assert "laporan_dosis_awal" in fac_name_sources
    assert "gedung_penahan_radiasi" in fac_name_sources
    assert report.facility.fields["project_name"].status in (MatchingStatus.SESUAI, MatchingStatus.PERLU_REVIEW)

    assert len(report.personnel) >= 1
    doc_sources = [s.document_type for s in report.personnel[0].fields["person_name"].sources]
    assert "laporan_dosis_awal" in doc_sources


def test_dual_role_personnel_separation():
    """Test that a person listed in both clinical personnel (e.g. Radiografer) and PPR

    maintains their distinct identity in both sections without being erroneously merged
    or filtered out.
    """
    from src.extraction.entity_builder import consolidate_application

    extractions = {
        "formulir": [
            {
                "file_name": "formulir.pdf",
                "fields": {
                    "hospital_name": {"value": "RS Medika Utama", "page": 1},
                    "personnel_data": {
                        "value": [
                            {"name": "dr. SpRad Senior", "profession": "Dokter Spesialis Radiologi", "role": "Dokter Spesialis Radiologi"},
                            {"name": "Budi Santoso", "profession": "Radiografer", "role": "Radiografer"},
                            {"name": "Budi Santoso", "profession": "PPR Medik Tk. 2", "role": "PPR Medik Tk. 2"},
                        ]
                    },
                },
            }
        ],
        "sib": [
            {
                "file_name": "sib_budi.pdf",
                "fields": {
                    "person_name": {"value": "Budi Santoso", "page": 1},
                    "certificate_number": {"value": "SIB-12345", "page": 1},
                },
            }
        ],
        "sprint": [
            {
                "file_name": "sprint_budi.pdf",
                "fields": {
                    "person_name": {"value": "Budi Santoso", "page": 1},
                    "document_number": {"value": "SPRINT/001/2026", "page": 1},
                },
            }
        ],
    }

    app = consolidate_application(extractions)

    # 3 total entries in personnel list, 1 in PPR
    assert len(app.personnel) == 3
    assert len(app.ppr) == 1
    assert app.ppr[0].name.value == "Budi Santoso"

    report = generate_cross_check_report(app, extractions, run_id="dual_role_run")

    # Ensure report has 3 personnel records and 1 PPR record
    assert len(report.personnel) == 3
    assert len(report.ppr) == 1

    # Find the Radiografer record for Budi Santoso
    radiographer_entry = next(
        p for p in report.personnel
        if p.fields["person_name"].sources
        and p.fields["person_name"].sources[0].value == "Budi Santoso"
        and any("Radiografer" in s.value for s in p.fields["profession"].sources)
    )
    assert radiographer_entry is not None

    # Find the PPR entry
    ppr_entry = report.ppr[0]
    assert ppr_entry.fields["ppr_name"].sources[0].value == "Budi Santoso"
    ppr_doc_types = [s.document_type for s in ppr_entry.fields["ppr_name"].sources]
    assert "sib" in ppr_doc_types
    assert "sprint" in ppr_doc_types

    # Ensure radiographer entry does NOT get PPR SIB/Sprint sources contaminated
    rad_doc_types = [s.document_type for s in radiographer_entry.fields["person_name"].sources]
    assert "sib" not in rad_doc_types
    assert "sprint" not in rad_doc_types


def test_split_project_address_and_formulir_identity():
    """Validates that Alamat Proyek is split into facility name prefix and address suffix
    as required for BAPETEN permit evaluation.
    """
    from src.extraction.form_parser import split_project_address, extract_form_data, build_application_from_form

    # 1. Hermina Kepanjen
    raw_hermina = (
        "RS. Hermina Kepanjen, Jalan Raya Mojosari , RT 02/RW 01, Kel. Mojosari,\n"
        "Kec. Kepanjen , Kab. Malang, Jawa Timur"
    )
    name_h, addr_h = split_project_address(raw_hermina)
    assert name_h == "RS. Hermina Kepanjen"
    assert "Jalan Raya Mojosari" in addr_h
    assert "Kec. Kepanjen" in addr_h

    # 2. Rumah Sakit Jiwa Aceh
    raw_aceh = (
        "Rumah Sakit Jiwa Aceh, Jl. Dr. T. Syarief Thayeb No. 25 , Kota Banda Aceh "
        "Aceh 23126, Telp.0651-32010, 0651-32020, Fax.0651-25857"
    )
    name_a, addr_a = split_project_address(raw_aceh)
    assert name_a == "Rumah Sakit Jiwa Aceh"
    assert addr_a.startswith("Jl. Dr. T. Syarief Thayeb No. 25")

    # 3. Klinik Insan Utama Balikpapan
    raw_balikpapan = (
        "Klinik Insan Utama Balikpapan, Jl. Mayor TNI AD Ahmad Saili , Kota "
        "Balikpapan Kalimantan Timur 76124, Telp.0857-5232-3293"
    )
    name_b, addr_b = split_project_address(raw_balikpapan)
    assert name_b == "Klinik Insan Utama Balikpapan"
    assert addr_b.startswith("Jl. Mayor TNI AD Ahmad Saili")

    # 4. RS Tk. IV Pekanbaru
    raw_pekanbaru = "RS Tk. IV Pekanbaru, Jl. Kesehatan No. 2 , Kota Pekanbaru Riau"
    name_p, addr_p = split_project_address(raw_pekanbaru)
    assert name_p == "RS Tk. IV Pekanbaru"
    assert addr_p == "Jl. Kesehatan No. 2 , Kota Pekanbaru Riau"

    # 5. Full extraction test verifying that formulir sets hospital_name to prefix and hospital_address to suffix
    form_text = [
        "Instansi : Medika Loka Kepanjen\n"
        "Alamat Instansi : Medika Loka Kepanjen, Jalan Raya Mojosari , RT 02/RW 01, Kel. Mojosari, Kec. Kepanjen\n"
        "Nama Proyek : Aktivitas Rumah Sakit Swasta\n"
        "Alamat Proyek : RS. Hermina Kepanjen, Jalan Raya Mojosari , RT 02/RW 01, Kel. Mojosari,\n"
        "Kec. Kepanjen , Kab. Malang, Jawa Timur\n"
        "A. Kelengkapan Administrasi\n"
    ]
    parsed = extract_form_data([], form_text)
    assert parsed["hospital_name"]["value"] == "RS. Hermina Kepanjen"
    assert "Jalan Raya Mojosari" in parsed["hospital_address"]["value"]
    assert "Kec. Kepanjen" in parsed["hospital_address"]["value"]

    # Verify build_application_from_form preserves legal holding company in institution_name
    app = build_application_from_form(parsed)
    assert app.facility.project_name.value == "RS. Hermina Kepanjen"
    assert "Jalan Raya Mojosari" in app.facility.project_address.value
    assert app.facility.institution_name.value == "Medika Loka Kepanjen"


def test_cross_check_homonym_personnel_with_ppr_and_radiographer():
    """Test that two personnel with identical names (e.g. Siti Azizah as Radiografer

    and Siti Azizah as PPR Medik Tk. 2) do not cross-contaminate SIP vs SIB credentials,
    preventing false-positive critical discrepancies.
    """
    from src.extraction.entity_builder import consolidate_application

    extractions = {
        "formulir": [
            {
                "file_name": "formulir.pdf",
                "fields": {
                    "hospital_name": {"value": "RS Hermina Kepanjen", "page": 1},
                    "personnel_data": {
                        "value": [
                            {"name": "dr. Dhanti Erma Widiasi, Sp.Rad", "profession": "Dokter Spesialis Radiologi", "role": "Dokter Spesialis Radiologi"},
                            {"name": "Siti Azizah", "profession": "Radiografer", "role": "Radiografer"},
                            {"name": "Shofayana Wardatul Jamilah", "profession": "Radiografer", "role": "Radiografer"},
                            {"name": "Siti Azizah", "profession": "PPR Medik Tk. 2", "role": "PPR Medik Tk. 2"},
                        ]
                    },
                },
            }
        ],
        "sip": [
            {
                "file_name": "sip_siti_azizah.pdf",
                "fields": {
                    "person_name": {"value": "Siti Azizah", "page": 1},
                    "profession": {"value": "Radiografer Level 5", "page": 1},
                    "practice_location": {"value": "RS Hermina Kepanjen", "page": 1},
                },
            }
        ],
        "sib": [
            {
                "file_name": "sib_siti_azizah.pdf",
                "fields": {
                    "ppr_name": {"value": "Siti Azizah", "page": 1},
                    "profession": {"value": "PPR Medik Tk. 2", "page": 1},
                    "valid_until": {"value": "2028-12-31", "page": 1},
                },
            }
        ],
        "sprint": [
            {
                "file_name": "sprint_siti_azizah.pdf",
                "fields": {
                    "ppr_name": {"value": "Siti Azizah", "page": 1},
                },
            }
        ],
    }

    app = consolidate_application(extractions)
    assert len(app.personnel) == 4
    assert len(app.ppr) == 1

    report = generate_cross_check_report(app, extractions, run_id="hermina_siti_azizah_run")

    # Personel #2 (Radiografer)
    p2 = report.personnel[1]
    assert p2.fields["person_name"].sources[0].value == "Siti Azizah"
    assert p2.fields["profession"].status in (MatchingStatus.SESUAI, MatchingStatus.PERLU_REVIEW)

    # Personel #4 (PPR Medik Tk. 2)
    p4 = report.personnel[3]
    assert p4.fields["person_name"].sources[0].value == "Siti Azizah"
    # Crucial: p4 should NOT have failed against "Radiografer Level 5" from SIP
    assert p4.fields["profession"].status != MatchingStatus.TIDAK_SESUAI
    assert p4.fields["profession"].status in (MatchingStatus.SESUAI, MatchingStatus.PERLU_REVIEW)


def test_no_phantom_units_when_formulir_has_two_units():
    """Formulir declares 2 equipment units. Uploading tube plates named 'label_unit_1.jpeg'

    must NOT create a phantom 3rd equipment unit, and must match tube cross-checks.
    """
    from src.extraction.entity_builder import consolidate_application
    from src.matching.cross_check_engine import generate_cross_check_report

    extractions = {
        "formulir": [
            {
                "file_name": "formulir_hermina.pdf",
                "fields": {
                    "hospital_name": {"value": "RS Hermina Kepanjen"},
                    "all_xray_rows": [
                        {
                            "unit_brand": "United Imaging Healthcare",
                            "unit_type": "uDR 566i-A",
                            "unit_serial_number": "294248",
                            "tube_brand": "Canon",
                            "tube_type": "E7876",
                            "tube_serial_number": "25D1063",
                        },
                        {
                            "unit_brand": "United Imaging Healthcare",
                            "unit_type": "uDR 380i",
                            "unit_serial_number": "422867",
                            "tube_brand": "Canon",
                            "tube_type": "XRR-3332",
                            "tube_serial_number": "4K0493",
                        },
                    ],
                },
            }
        ],
        "label_unit": [
            {
                "file_name": "label_unit_1.jpeg",
                "fields": {
                    "unit_brand": {"value": "CANON ELECTRON TUBES"},
                    "unit_type": {"value": "25D1063"},
                    "unit_serial_number": {"value": "25D1063"},
                },
            },
            {
                "file_name": "label_unit_2.jpeg",
                "fields": {
                    "unit_brand": {"value": "Shanghai United Imaging Healthcare Co.,Ltd."},
                    "unit_type": {"value": "uDR 566i-A"},
                    "unit_serial_number": {"value": "294248"},
                },
            },
        ],
        "label_tabung": [
            {
                "file_name": "label_unit_1.jpeg",
                "fields": {
                    "tube_brand": {"value": "CANON ELECTRON TUBES"},
                    "tube_type": {"value": "E7876"},
                    "tube_unit_model": {"value": "E7876X"},
                    "tube_insert_model": {"value": "E7876"},
                    "tube_serial_number": {"value": "25D1063"},
                    "tube_housing_serial": {"value": "25D1063"},
                    "tube_insert_serial": {"value": "25D0610"},
                },
            }
        ],
    }

    app = consolidate_application(extractions)
    # Must have EXACTLY 2 equipment units, NEVER a 3rd phantom unit
    assert len(app.xray_equipment) == 2
    assert app.xray_equipment[0].unit_serial_number.value == "294248"
    assert app.xray_equipment[1].unit_serial_number.value == "422867"

    report = generate_cross_check_report(app, extractions, run_id="hermina_2_units_test")
    assert len(report.xray_equipment) == 2
    assert len(report.xray_tubes) == 2

    # Unit 1 should match label_unit_2.jpeg
    eq1_brand_sources = [s.document_name for s in report.xray_equipment[0].fields["unit_brand"].sources]
    assert "label_unit_2.jpeg" in eq1_brand_sources
    assert "label_unit_1.jpeg" not in eq1_brand_sources

    # Tube 1 should match label_unit_1.jpeg
    tb1_serial_sources = [s.document_name for s in report.xray_tubes[0].fields["tube_serial_number"].sources]
    assert "label_unit_1.jpeg" in tb1_serial_sources









