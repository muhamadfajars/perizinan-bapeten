"""Unit tests for document extraction engine, multi-row form parsing, label parsing, and entity consolidation."""

from src.extraction.form_parser import (
    split_type_and_serial,
    parse_all_generator_rows,
    parse_people_tables,
    extract_form_data,
    build_application_from_form,
)
from src.extraction.label_parser import (
    parse_label_unit,
    parse_label_tube,
    build_label_unit_entity,
    build_label_tube_entity,
)
from src.extraction.entity_builder import (
    find_best_person_match,
    find_best_equipment_match,
    consolidate_application,
)
from src.schema.entities import PersonnelEntity, XRayEquipmentEntity
from src.schema.evidence import ExtractedField


def test_split_type_and_serial():
    # Slash pattern
    t, s = split_type_and_serial("RADspeed Pro / SB2002000027WK")
    assert t == "RADspeed Pro"
    assert s == "SB2002000027WK"

    # Newline pattern
    t, s = split_type_and_serial("Multix Impact\nSN: 123456")
    assert t == "Multix Impact"
    assert s == "123456"

    # Parentheses pattern
    t, s = split_type_and_serial("Optima XR646 (SN-998877)")
    assert t == "Optima XR646"
    assert s == "SN-998877"

    # Single value without serial
    t, s = split_type_and_serial("Fluoroscopy")
    assert t == "Fluoroscopy"
    assert s == ""


def test_parse_multi_unit_generator_table():
    # Simulated table on page 3 (index 2)
    fake_tables = [
        (
            2,
            [
                ["No", "Merk", "Tipe / No. Seri", "Merk Tabung", "Tipe / No. Seri Tabung", "Kondisi Max"],
                ["1", "SHIMADZU", "RADspeed Pro / SB2002000027WK", "CANON", "Circlex / TB-112233", "150 kV 500 mA"],
                ["2", "SIEMENS", "Multix Impact / SN-SIEM-99", "SIEMENS", "Optitop / TB-SIEM-88", "125 kV 400 mA"],
            ],
        )
    ]

    rows = parse_all_generator_rows(fake_tables)
    assert len(rows) == 2
    assert rows[0]["unit_brand"] == "SHIMADZU"
    assert rows[0]["unit_type"] == "RADspeed Pro"
    assert rows[0]["unit_serial_number"] == "SB2002000027WK"
    assert rows[0]["tube_brand"] == "CANON"
    assert rows[0]["tube_serial_number"] == "TB-112233"
    assert rows[0]["page"] == 3

    assert rows[1]["unit_brand"] == "SIEMENS"
    assert rows[1]["unit_serial_number"] == "SN-SIEM-99"


def test_build_application_from_multi_entity_form():
    fake_tables = [
        (
            0,
            [
                ["No", "Persyaratan Administrasi", "Keterangan"],
                ["1", "Dokumen Program Proteksi", "No. Dokumen: 001/PPKR/2026 tanggal 10 Januari 2026"],
            ],
        ),
        (
            1,
            [
                ["No", "NPR", "Nama Petugas", "Klasifikasi / Keahlian"],
                ["1", "NPR-001", "Dr. Andi Wijaya, Sp.Rad", "Dokter Spesialis Radiologi"],
                ["2", "NPR-002", "Bambang Santoso", "Petugas Proteksi Radiasi (PPR)"],
            ],
        ),
        (
            2,
            [
                ["No", "Merk", "Tipe / No. Seri", "Merk Tabung", "Tipe / No. Seri Tabung", "Kondisi Max"],
                ["1", "SHIMADZU", "RADspeed Pro / SB2002000027WK", "CANON", "Circlex / TB-112233", "150 kV 500 mA"],
            ],
        ),
    ]

    fake_pages = [
        "Nomor Registrasi: REG/2026/001\nNama Proyek: RS Harapan Sehat\nAlamat Proyek: Jakarta",
        "Daftar Ketenagaan Personel",
        "Spesifikasi Alat Pesawat Sinar-X",
    ]

    parsed = extract_form_data(fake_tables, fake_pages)
    app = build_application_from_form(parsed, file_name="Formulir.pdf")

    assert app.registration_number == "REG/2026/001"
    assert app.facility.project_name.value == "RS Harapan Sehat"
    assert len(app.personnel) == 2
    assert len(app.ppr) == 1
    assert app.ppr[0].name.value == "Bambang Santoso"
    assert len(app.xray_equipment) == 1
    assert app.xray_equipment[0].unit_brand.value == "SHIMADZU"
    assert app.xray_equipment[0].unit_serial_number.value == "SB2002000027WK"
    assert app.xray_equipment[0].tube.tube_brand.value == "CANON"


def test_label_parsers_and_entities():
    fake_unit_lines = [
        {"text": "MANUFACTURER: SHIMADZU CORPORATION", "conf": 0.98, "x": 10, "y": 20, "w": 200, "h": 20},
        {"text": "MODEL: RADspeed Pro", "conf": 0.95, "x": 10, "y": 50, "w": 150, "h": 20},
        {"text": "SER NO. SB2002000027WK", "conf": 0.99, "x": 10, "y": 80, "w": 180, "h": 20},
    ]

    eq_entity = build_label_unit_entity(fake_unit_lines, file_name="foto_unit.jpg")
    assert eq_entity.unit_brand.value == "SHIMADZU CORPORATION"
    assert eq_entity.unit_type.value == "RADspeed Pro"
    assert eq_entity.unit_serial_number.value == "SB2002000027WK"
    assert eq_entity.unit_serial_number.evidence.confidence == 0.99

    # Test GE Healthcare label layout with adjacent bounding boxes
    ge_unit_lines = [
        {"text": "GENERAL ELECTRIC COMPANY", "conf": 0.99, "x": 1211, "y": 630},
        {"text": "MODEL", "conf": 0.99, "x": 1173, "y": 813},
        {"text": "5555000-4", "conf": 0.99, "x": 1461, "y": 765},
        {"text": "S/N", "conf": 0.99, "x": 1172, "y": 869},
        {"text": "SB2002000027WK", "conf": 0.99, "x": 1452, "y": 830},
        {"text": "DESC", "conf": 0.99, "x": 1173, "y": 992},
        {"text": "OPTIMA XR200AMX 30KW", "conf": 0.99, "x": 1448, "y": 966},
        {"text": "MODEL NUMBER", "conf": 0.99, "x": 1243, "y": 2171},
        {"text": "SER NO 20G225", "conf": 0.91, "x": 508, "y": 1822},
    ]
    ge_entity = build_label_unit_entity(ge_unit_lines, file_name="label_ge.jpg")
    assert "GENERAL ELECTRIC" in ge_entity.unit_brand.value
    assert ge_entity.unit_type.value == "OPTIMA XR200AMX"
    assert ge_entity.unit_serial_number.value == "SB2002000027WK"


    fake_tube_lines = [
        {"text": "CANON ELECTRON TUBES & DEVICES CO., LTD.", "conf": 0.97, "x": 10, "y": 15, "w": 250, "h": 20},
        {"text": "HOUSING MODEL: Circlex-01", "conf": 0.93, "x": 10, "y": 45, "w": 160, "h": 20},
        {"text": "SER. NO. TB-112233", "conf": 0.96, "x": 10, "y": 75, "w": 140, "h": 20},
    ]

    tube_entity = build_label_tube_entity(fake_tube_lines, file_name="foto_tabung.jpg")
    assert "CANON" in tube_entity.tube_brand.value
    assert tube_entity.tube_serial_number.value == "TB-112233"


def test_consolidate_application_multi_document():
    extractions = {
        "formulir": [
            {
                "file_name": "Formulir_RS.pdf",
                "fields": {
                    "hospital_name": {"value": "RS Harapan Sehat", "page": 1},
                    "hospital_address": {"value": "Jl. Gatot Subroto Kav. 12", "page": 1},
                    "personnel_data": {
                        "value": [
                            {"npr": "NPR-01", "name": "Dr. Andi Wijaya, Sp.Rad", "role": "Dokter Spesialis Radiologi", "page": 2},
                            {"npr": "NPR-02", "name": "Bambang Santoso", "role": "Petugas Proteksi Radiasi (PPR)", "page": 2},
                        ]
                    },
                    "all_xray_rows": [
                        {
                            "unit_brand": "SHIMADZU",
                            "unit_type": "RADspeed Pro",
                            "unit_serial_number": "SB2002000027WK",
                            "tube_brand": "CANON",
                            "tube_type": "Circlex",
                            "tube_serial_number": "TB-112233",
                            "max_condition": "150 kV 500 mA",
                            "page": 3,
                        }
                    ],
                },
            }
        ],
        "sip": [
            {
                "file_name": "SIP_dr_Andi.pdf",
                "fields": {
                    "person_name": {"value": "dr. Andi Wijaya Sp. Rad", "page": 1},
                    "profession": {"value": "Dokter Spesialis Radiologi", "page": 1},
                    "valid_until": {"value": "31/12/2028", "page": 1},
                    "practice_location": {"value": "RS Harapan Sehat", "page": 1},
                },
            }
        ],
        "sib": [
            {
                "file_name": "SIB_Bambang.pdf",
                "fields": {
                    "ppr_name": {"value": "Bambang Santoso", "page": 1},
                    "valid_until": {"value": "15/08/2027", "page": 1},
                },
            }
        ],
        "label_unit": [
            {
                "file_name": "foto_label_unit.jpg",
                "fields": {
                    "unit_brand": {"value": "SHIMADZU", "method": "ocr"},
                    "unit_type": {"value": "RADspeed Pro", "method": "ocr"},
                    "unit_serial_number": {"value": "SB2002000027WK", "method": "ocr"},
                },
            }
        ],
    }

    app = consolidate_application(extractions)

    assert app.facility.project_name.value == "RS Harapan Sehat"
    assert len(app.personnel) == 2
    # Verify SIP enrichment onto the matched person
    p1 = app.personnel[0]
    assert p1.name.value == "Dr. Andi Wijaya, Sp.Rad"
    assert p1.valid_until is not None
    assert p1.valid_until.value == "31/12/2028"
    assert p1.valid_until.evidence.document_type == "sip"

    # Verify SIB enrichment onto the matched PPR
    assert len(app.ppr) == 1
    ppr1 = app.ppr[0]
    assert ppr1.valid_until is not None
    assert ppr1.valid_until.value == "15/08/2027"
    assert ppr1.valid_until.evidence.document_type == "sib"

    # Verify equipment
    assert len(app.xray_equipment) == 1
    assert app.xray_equipment[0].unit_serial_number.value == "SB2002000027WK"


def test_dynamic_shuffled_table_columns():
    """Verify that tables with completely rearranged/shuffled columns are resolved dynamically from headers."""
    # Shuffled order: No, Kondisi Max, Tabung Merk, Tabung Seri, Pesawat Merk, Pesawat Tipe, Pesawat No Seri
    shuffled_tables = [
        (
            0,
            [
                ["No", "Kondisi Operasional", "Merk Tabung", "No. Seri Tabung", "Merk Pesawat", "Tipe Pesawat", "Nomor Seri Pesawat"],
                ["1", "125 kV / 320 mA", "DUNLEE", "DL-998811", "CARESTREAM", "DRX-Compass", "CS-2026-X1"],
            ],
        )
    ]

    rows = parse_all_generator_rows(shuffled_tables)
    assert len(rows) == 1
    assert rows[0]["unit_brand"] == "CARESTREAM"
    assert rows[0]["unit_type"] == "DRX-Compass"
    assert rows[0]["unit_serial_number"] == "CS-2026-X1"
    assert rows[0]["tube_brand"] == "DUNLEE"
    assert rows[0]["tube_serial_number"] == "DL-998811"
    assert "max_condition" not in rows[0]


def test_dynamic_unseen_brand_label():
    """Verify that labels from previously unseen/unlisted brands are recognized dynamically."""
    unseen_lines = [
        {"text": "VATECH CO., LTD.", "conf": 0.97, "x": 10, "y": 10, "w": 200, "h": 20},
        {"text": "TYPE: PaX-i3D Smart", "conf": 0.95, "x": 10, "y": 40, "w": 180, "h": 20},
        {"text": "SER NO: VT-887722", "conf": 0.99, "x": 10, "y": 70, "w": 160, "h": 20},
    ]

    unit = build_label_unit_entity(unseen_lines, file_name="foto_vatech.jpg")
    assert unit.unit_brand.value == "VATECH CO., LTD."
    assert unit.unit_type.value == "PaX-i3D Smart"
    assert unit.unit_serial_number.value == "VT-887722"


def test_parse_real_bapeten_documents():
    """Verify parsing of real-world BAPETEN documents (Sprint, TLD, Sistem Manajemen, Program Perawatan)."""
    from src.extraction.document_parser import parse_document
    from src.schema.fields import DOCUMENT_FIELDS

    # 1. Sprint
    sprint_text = [
        "KESEHATAN DAERAH MILITER XIX / TUANKU TAMBUSAI\n"
        "RUMAH SAKIT TK IV PEKANBARU\n"
        "Jl. Kesehatan No.2 - Pekanbaru | 0812-6948-7627 | rst_pekanbaru\n"
        "SURAT PERINTAH\n"
        "Nomor : sprin/ 03/VIII/2026\n"
        "DIPERINTAHKAN\n"
        "Kepada : Neza fuad alfarid damanik\n"
        "Untuk : Seterimanya surat perintah ini ditugaskan sebagai petugas proteksi radiasi...\n"
        "Pekanbaru, 19 agustus 2026\n"
        "Kepala Rumah Sakit TK IV 01.07.04\n"
        "dr. Adimas Okto Nugroho, Sp.Rad\n"
        "Mayor Ckm 11100002031082"
    ]
    sprint_res = parse_document("sprint", sprint_text)
    assert sprint_res["fields"]["hospital_name"]["value"] == "RUMAH SAKIT TK IV PEKANBARU"
    assert sprint_res["fields"]["hospital_address"]["value"] == "Jl. Kesehatan No.2 - Pekanbaru"
    assert sprint_res["fields"]["ppr_name"]["value"] == "Neza fuad alfarid damanik"
    assert sprint_res["fields"]["kepada"]["value"] == "Neza fuad alfarid damanik"
    assert sprint_res["fields"]["approval"]["value"] == "dr. Adimas Okto Nugroho, Sp.Rad"
    assert sprint_res["fields"]["pengesahan"]["value"] == "dr. Adimas Okto Nugroho, Sp.Rad"

    # 2. TLD
    tld_text = [
        "NuklindoLab\n"
        "KOPERASI JASA KESELAMATAN RADIASI DAN LINGKUNGAN\n"
        "Nomor : 8965/JKRL-SPM/IX/2026\n"
        "Kepada,\n"
        "Petugas Proteksi Radiasi\n"
        "RS TENTARA TK IV 01.07.04 PEKANBARU\n"
        "Jl. Kesehatan No. 2 Kampung Bandar Senapelan Pekanbaru - Riau 28155\n"
        "1. Violita Yani Putri\n"
        "2. Neza Fuad Alfarid Damanik\n"
        "3. Sry Wulandari\n"
        "4. Adimas Okto Nugroho\n"
        "Untuk pemakaian bulan Oktober 2026 s.d. Desember 2026 periode Terakhir"
    ]
    tld_res = parse_document("tld", tld_text)
    assert tld_res["fields"]["hospital_name"]["value"] == "RS TENTARA TK IV 01.07.04 PEKANBARU"
    assert "Jl. Kesehatan No. 2" in tld_res["fields"]["hospital_address"]["value"]
    assert "Oktober 2026" in tld_res["fields"]["usage_period"]["value"]
    assert tld_res["fields"]["person_name"]["value"] == "Adimas Okto Nugroho"

    # 3. Sistem Manajemen
    sm_p1 = "SISTEM MANAJEMEN\nFASILITAS RADIOLOGI DIAGNOSTIK DAN INTERVENSIONAL\nRS TK IV PEKANBARU\nPROVINSI RIAU\n2026"
    sm_p2 = (
        "SISTEM MANAJEMEN FASILITAS RADIOLOGI DIAGNOSTIK DAN INTERVENSIONAL\n"
        "RS TK IV Pekanbaru\n"
        "Jl. Kesehatan no 2 Pekanbaru Riau\n"
        "Nomor 036/01.00/RSTKIVPKU/VI/2026\n"
        "Tanggal 3 Agustus 2026\n"
        "LEMBAR PENGESAHAN\n"
        "Disiapkan oleh\n"
        "Nama Jabatan Tanda Tangan Tanggal\n"
        "Neza fuad alfarid damanik PPR 3 Agustus 2026\n"
        "Disahkan oleh\n"
        "dr.Adimas Okto Anugrah Sp.Rad Kepala Rumah Sakit 3 Agustus 2026"
    )
    sm_res = parse_document("sistem_manajemen", [sm_p1, sm_p2])
    assert sm_res["fields"]["hospital_name"]["value"] == "RS TK IV PEKANBARU"
    assert sm_res["fields"]["hospital_address"]["value"] == "Jl. Kesehatan no 2 Pekanbaru Riau"
    assert "person_name" not in DOCUMENT_FIELDS["sistem_manajemen"]
    assert "document_number" not in sm_res["fields"]
    assert "document_date" not in sm_res["fields"]

    # 4. Program Perawatan
    pp_p1 = "PROGRAM PERAWATAN PESAWAT SINAR-X\nRS TK IV PEKANBARU\nPROVINSI RIAU"
    pp_p2 = sm_p2
    pp_p24 = "Komunikasi juga mencakup laporan eksternal kepada BAPETEN atau instansi terkait sesuai kewajiban pelaporan regulasi."
    pp_res = parse_document("program_perawatan", [pp_p1, pp_p2, pp_p24])
    assert pp_res["fields"]["hospital_name"]["value"] == "RS TK IV PEKANBARU"
    assert pp_res["fields"]["hospital_address"]["value"] == "Jl. Kesehatan no 2 Pekanbaru Riau"
    assert "person_name" not in DOCUMENT_FIELDS["program_perawatan"]
    assert "conformity_test_clause" in pp_res["fields"]
    assert "document_number" not in pp_res["fields"]
    assert "document_date" not in pp_res["fields"]
    assert "terkait sesuai kewajiban" not in pp_res["fields"]["hospital_name"]["value"]


def test_parse_document_formulir_xray_separation():
    from src.extraction.document_parser import parse_document

    fake_tables = [
        (
            1,
            [
                ["No", "Merk Unit", "Tipe / No Seri", "Merk Tabung", "Tipe / No. Seri Tabung", "Kondisi Maksimal"],
                ["1", "GE", "Optima XR200amx / SB2002000027WK", "Canon", "E7894/ 0F1376", "150 kV / 500 mA"],
            ],
        )
    ]
    fake_pages = ["Formulir Permohonan\nInstansi: RS Pekanbaru\nAlamat: Jl. Sudirman"]

    res = parse_document("formulir", fake_pages, tables=fake_tables)
    f = res["fields"]

    assert f["unit_brand"]["value"] == "GE"
    assert f["unit_type"]["value"] == "Optima XR200amx"
    assert f["unit_serial_number"]["value"] == "SB2002000027WK"
    assert f["tube_brand"]["value"] == "Canon"
    assert f["tube_type"]["value"] == "E7894"
    assert f["tube_serial_number"]["value"] == "0F1376"
    assert "xray_data" not in f


def test_sprint_hospital_address_extraction():
    from src.extraction.document_parser import parse_document
    sprint_text = (
        "KESEHATAN DAERAH MILITER XIX / TUANKU TAMBUSAI\n"
        "RUMAH SAKIT TK IV PEKANBARU\n"
        "JL Kesehatan No.2 - Pekanbaru website.rswirabima.com 0812-6848-7627 rumkitpku@gmall.com\n"
        "SURAT PERINTAH\n"
        "Nomor : sprin/ 03/VIII/2026\n"
        "DIPERINTAHKAN\n"
        "Kepada : Neza fuad alfarid damanik\n"
        "dr. Adimas Okto Nugroho, Sp.Rad\n"
    )
    res = parse_document("sprint", [sprint_text])
    assert res["fields"]["hospital_name"]["value"] == "RUMAH SAKIT TK IV PEKANBARU"
    assert res["fields"]["hospital_address"]["value"] == "JL Kesehatan No.2 - Pekanbaru"
    assert res["fields"]["ppr_name"]["value"] == "Neza fuad alfarid damanik"


def test_sib_extraction_variations():
    from src.extraction.document_parser import parse_document
    sib_text = (
        "BADAN PENGAWAS TENAGA NUKLIR\n"
        "SURAT IZIN BEKERJA\n"
        "Nomor: 2026-SIB-001\n"
        "Diberikan kepada : Neza Fuad Alfarid Damanik\n"
        "Sebagai : Petugas Proteksi Radiasi Medik Tingkat 2\n"
        "Masa berlaku : 10 Januari 2024 s/d 10 Januari 2027\n"
    )
    res = parse_document("sib", [sib_text])
    assert res["fields"]["ppr_name"]["value"] == "Neza Fuad Alfarid Damanik"
    assert res["fields"]["ppr_name"]["confidence"] == 1.0
    assert res["fields"]["profession"]["value"] == "Petugas Proteksi Radiasi Medik Tingkat 2"
    assert res["fields"]["profession"]["confidence"] == 1.0
    assert res["fields"]["valid_until"]["value"] == "10/01/2027"
    assert res["fields"]["valid_until"]["confidence"] == 1.0


def test_sib_card_layout_extraction():
    from src.extraction.document_parser import parse_document
    sib_card = (
        "BADAN PENGAWAS TENAGA NUKLIR\n"
        "NUCLEAR ENERGY REGULATORY AGENCY\n"
        "Izin Bekerja Petugas Fasilitas Radiasi dan Zat Radioaktif\n"
        "Working Permit of Officer of Radiation Facilities and Radioactive Materials\n"
        "No. SIB / Working Permit Number\n"
        "448615.223.20.260126\n"
        "PPR Radiologi Diagnostik dan atau\n"
        "Intervensional\n"
        "Nama / Name\n"
        "Neza Fuad Alfarid Damanik\n"
        "Nomor Sertifikat Kompetensi/ Competency Certificate Number\n"
        "448615.223.10.260126\n"
        "Berlaku s.d / Valid Until\n"
        "25 Januari 2031 / 25th January 2031\n"
        "Jakarta, 26 Januari 2026 / 26th January 2026\n"
    )
    res = parse_document("sib", [sib_card])
    assert res["fields"]["ppr_name"]["value"] == "Neza Fuad Alfarid Damanik"
    assert res["fields"]["ppr_name"]["confidence"] == 1.0
    assert res["fields"]["profession"]["value"] == "PPR Radiologi Diagnostik dan atau Intervensional"
    assert res["fields"]["profession"]["confidence"] == 1.0
    assert res["fields"]["valid_until"]["value"] == "25/01/2031"
    assert res["fields"]["valid_until"]["confidence"] == 1.0


def test_sib_two_column_dual_language_extraction():
    from src.extraction.document_parser import parse_document
    sib_twocol = (
        "BADAN PENGAWAS TENAGA NUKLIR\n"
        "NUCLEAR ENERGY REGULATORY AGENCY\n"
        "Izin Bekerja Petugas Fasilitas Radiasi dan Zat Radioaktif\n"
        "Working Permit of Officer of Radiation Facilities and Radioactive Materials\n"
        "No. SIB / Working Permit Number\n"
        "352403.224.02.101123\n"
        "PPR Medik Tk. 2\n"
        "Jakarta, 10 November 2023 / 10th November 2023\n"
        "Nama / Name a.n. KEPALA BAPETEN / p.p. Chairman of BAPETEN\n"
        "Siti Azizah Direktur Perizinan Fasilitas Radiasi dan Zat Radioaktif\n"
        "Berlaku s.d / Valid Until Director of Licensing for Radiation Facilities and Radioactive\n"
        "27 Agustus 2027 / 27th August 2027 Materials\n"
        "#\n"
        "Ishak\n"
        "NIP.197009102000121002\n"
    )
    res = parse_document("sib", [sib_twocol])
    assert res["fields"]["ppr_name"]["value"] == "Siti Azizah"
    assert res["fields"]["ppr_name"]["confidence"] == 1.0
    assert res["fields"]["profession"]["value"] == "PPR Medik Tk. 2"
    assert res["fields"]["profession"]["confidence"] == 1.0
    assert res["fields"]["valid_until"]["value"] == "27/08/2027"
    assert res["fields"]["valid_until"]["confidence"] == 1.0


def test_spesifikasi_pesawat_brochure_extraction():
    from src.extraction.document_parser import parse_document
    brochure_p1 = (
        "GE Healthcare\n"
        "Optima XR200amx\n"
        "*\n"
        "Mobile Digital-Ready Radiographic System\n"
        "imagination at work\n"
    )
    brochure_p2 = (
        "The Optima XR200amx is a self-contained battery operated mobile X-ray imaging system\n"
    )
    res = parse_document("spesifikasi_pesawat", [brochure_p1, brochure_p2])
    assert res["fields"]["unit_brand"]["value"] in ("GE Healthcare", "GE")
    assert "Optima XR200amx" in res["fields"]["unit_type"]["value"]


def test_spesifikasi_pesawat_united_imaging_brochure_extraction():
    from src.extraction.document_parser import parse_document
    ui_p1 = (
        "Shanghai United Imaging Healthcare Co., Ltd.\n"
        "uDR 566i-A\n"
        "uDR 566i-B\n"
        "Motorized floor-mounted DR\n"
        "Clarity. Experience.\n"
    )
    ui_p2 = (
        "uDR 566i-A\n"
        "uDR 566i-B\n"
        "Ease of Use\n"
    )
    res = parse_document("spesifikasi_pesawat", [ui_p1, ui_p2])
    assert res["fields"]["unit_brand"]["value"] == "United Imaging Healthcare"
    assert res["fields"]["unit_type"]["value"] == "uDR 566i-A"
    assert res["fields"]["unit_brand"]["confidence"] == 1.0
    assert res["fields"]["unit_type"]["confidence"] == 1.0


def test_formulir_omits_administrative_documents_and_npr():
    from src.extraction.document_parser import parse_document
    from src.schema.fields import DOCUMENT_FIELDS
    assert "administrative_documents" not in DOCUMENT_FIELDS["formulir"]

    fake_tables = [
        (
            0,
            [
                ["No", "NPR", "Nama Petugas", "Klasifikasi / Keahlian"],
                ["1", "412237", "dr. Adimas Okto Nugroho, Sp.Rad", "Dokter Spesialis Radiologi"],
                ["2", "448615", "Neza Fuad Alfarid Damanik", "PPR Radiologi Diagnostik"],
            ],
        ),
        (
            1,
            [
                ["No", "Merk", "Tipe / No Seri", "Merk Tabung", "Tipe / No Seri Tabung", "Kondisi Max"],
                ["1", "GE", "Optima XR200amx / SB2002000027WK", "Canon", "E7894/ 0F1376", "150 kV / 500 mA"],
            ],
        ),
    ]
    fake_pages = ["Formulir Permohonan\nInstansi: RS Pekanbaru\nAlamat: Jl. Kesehatan"]
    res = parse_document("formulir", fake_pages, tables=fake_tables)
    assert "administrative_documents" not in res["fields"]
    # Check people don't have npr
    for p in res["fields"]["personnel_data"]["value"]:
        assert "npr" not in p
        assert "name" in p
        assert "role" in p


def test_sistem_manajemen_pp_ppkr_updated_fields():
    from src.extraction.document_parser import parse_document
    from src.schema.fields import DOCUMENT_FIELDS

    # Verify schema omissions
    for dt in ["sistem_manajemen", "program_perawatan", "ppkr"]:
        assert "document_number" not in DOCUMENT_FIELDS[dt]
        assert "document_date" not in DOCUMENT_FIELDS[dt]

    # Verify PPKR personnel role extraction and doctor enrichment
    fake_ppkr_tables = [
        (
            1,
            [
                ["Disiapkan oleh", "Nama", "Jabatan", "Tanda Tangan", "Tanggal"],
                ["", "Neza Fuad Alfarid Damanik", "PPR Radiologi Diagnostik", "", "3 Agustus 2026"],
                ["", "dr. Adimas Okto Anugrah Sp.Rad", "Kepala Rumah Sakit", "", "3 Agustus 2026"],
            ],
        ),
    ]
    ppkr_pages = [
        "PROGRAM PROTEKSI DAN KESELAMATAN RADIASI\nRS TK IV PEKANBARU",
        "Jl.Kesehatanno.02 Pekanbaru Riau\nDisahkan oleh dr.Adimas Okto Anugrah Sp.Rad",
    ]
    res_ppkr = parse_document("ppkr", ppkr_pages, tables=fake_ppkr_tables)
    assert res_ppkr["fields"]["hospital_address"]["value"] == "Jl.Kesehatanno.02 Pekanbaru Riau"
    assert res_ppkr["fields"]["person_name"]["value"] == "dr. Adimas Okto Anugrah Sp.Rad"
    assert "document_number" not in res_ppkr["fields"]
    assert "document_date" not in res_ppkr["fields"]

    people = res_ppkr["fields"]["personnel_data"]["value"]
    assert len(people) == 2
    for p in people:
        assert p["name"]
        assert p["role"]
        assert p["role"] in ["PPR Radiologi Diagnostik", "Kepala Rumah Sakit"]


def test_uji_kesesuaian_extraction():
    from src.extraction.document_parser import parse_document
    p1 = (
        "FORM PERMOHONAN HASIL UJI\n"
        "Data Pemohon uji\n"
        "Nama Instansi : Rumah Sakit Tentara Tingkat IV Pekanbaru\n"
        "Alamat : Jl. Kesehatan No.2, RT.01/RW.06, Kp. Bandar, Senapelan, Kota Pekanbaru, Riau\n"
        "Data Pesawat\n"
        "Jenis Pesawat : RADIOGRAFI UMUM [Mobile]\n"
        "Merek Tabung : CANON\n"
        "Model Tabung : E7894\n"
        "Nomor Seri Tabung : 0F1376\n"
        "A. Generator dan panel Kendali Sinar-X\n"
        "1. Pabrikan/Merk GE\n"
        "2. Model/Tipe OPTIMA XR200AMX\n"
        "3. Nomor Seri SB2002000027WK\n"
        "B. Wadah Tabung Sinar-X (Tube Housing)\n"
        "1. Pabrikan/Merk CANON\n"
        "2. Model/Tipe E7894X\n"
        "3. Nomor Seri 20G225\n"
    )
    res = parse_document("uji_kesesuaian", [p1])
    f = res["fields"]
    assert f["hospital_name"]["value"] == "Rumah Sakit Tentara Tingkat IV Pekanbaru"
    assert "Jl. Kesehatan No.2" in f["hospital_address"]["value"]
    assert f["unit_brand"]["value"] == "GE"
    assert "OPTIMA XR200AMX" in f["unit_type_serial"]["value"]
    assert "SB2002000027WK" in f["unit_type_serial"]["value"]
    assert f["tube_brand"]["value"] == "CANON"
    assert f["tube_type"]["value"] == "E7894"


def test_persetujuan_import_extraction():
    from src.extraction.document_parser import parse_document
    fake_tables = [
        (
            1,
            [
                ["No.", "Kode Sumber", "Merk Unit", "Tipe/No Seri Unit", "Merk Tabung", "Tipe/No Seri Tabung", "Pengguna"],
                ["1", "0190107", "Philips", "Azurion 5 M20/340", "Philips", "MRC 200 0407 / 414822", "RSUD Ir. Soekarno"],
            ],
        )
    ]
    res = parse_document("persetujuan_import", ["Lampiran Import", "Tabel Teknis"], tables=fake_tables)
    f = res["fields"]
    assert f["unit_brand"]["value"] == "Philips"
    assert f["unit_type_serial"]["value"] == "Azurion 5 M20/340"
    assert f["tube_brand"]["value"] == "Philips"
    assert f["tube_type_serial"]["value"] == "MRC 200 0407 / 414822"


def test_persetujuan_import_multi_row_pekanbaru_selection():
    from src.extraction.document_parser import parse_document
    fake_tables = [
        (
            1,
            [
                ["No. Izin: 090049.035.11.281019", None, None, None, None, None],
                ["No", "Nama Sumber", "Tipe/No Seri", "HS", "Jumlah", "Pemakai"],
                ["1", "GE Mobile", "Optima XR200amx/System S/N:SB2002000019WK Tube S/N:20G130", "90221400", "1", "PT. Glomeda-Rumkit Tk. II / Putri Hijau Medan"],
                ["2", "GE Mobile", "Optima XR200amx/System S/N:SB2002000020WK Tube S/N:20G228", "90221400", "1", "PT. Glomeda-Rumkit Tk. III / dr. Reksodiwiryo Padang"],
                ["6", "GE Mobile", "Optima XR200amx/System S/N:SB2002000027WK Tube S/N:20G225", "90221400", "1", "PT. Glomeda-Rumkit Tk. IV / Pekanbaru"],
                ["7", "GE Mobile", "Optima XR200amx/System S/N:SB2002000029WK Tube S/N:20G1005", "90221400", "1", "PT. Glomeda-Rumkit Tk. IV / Binjai"],
            ],
        )
    ]
    # Test 1: With context specifying Pekanbaru
    ctx = {"hospital_name": "Rumkit Tentara Tk IV 01.07.04 Pekanbaru", "unit_serial_number": "SB2002000027WK"}
    res = parse_document("persetujuan_import", ["Page 1", "Page 2"], tables=fake_tables, context=ctx)
    f = res["fields"]
    assert f["unit_brand"]["value"] == "GE"
    assert f["unit_type"]["value"] == "Optima XR200amx"
    assert f["unit_serial_number"]["value"] == "SB2002000027WK"
    assert f["tube_type"]["value"] == "-"
    assert f["tube_serial_number"]["value"] == "-"

    # Test 2: Without context (domain heuristic matches Pekanbaru over Medan)
    res2 = parse_document("persetujuan_import", ["Page 1", "Page 2"], tables=fake_tables)
    f2 = res2["fields"]
    assert f2["unit_serial_number"]["value"] == "SB2002000027WK"
    assert f2["tube_type"]["value"] == "-"
    assert f2["tube_serial_number"]["value"] == "-"


def test_paparan_radiasi_extraction():
    from src.extraction.document_parser import parse_document
    p1_ocr = (
        "BERITA ACARA PENGUKURAN PAPARAN RADIASI\n"
        "Data Pelanggan/Rumah Sakit Rumkit Tk. IV Pekanbaru\n"
        "Nama Rumah Sakit JI. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau\n"
        "8 Jenis Alat OPTIMA XR200 AMX\n"
        "10 No Model SB2002000027WK\n"
        "15 Tipe Tabung 2 CANON ELECTRON\n"
        "18 No Model Tabung E7894X\n"
        "19 No Seri Tabung 20G225\n"
    )
    res = parse_document("paparan_radiasi", [p1_ocr])
    f = res["fields"]
    assert f["hospital_name"]["value"] == "Rumkit Tk. IV Pekanbaru"
    assert "Kesehatan No.2" in f["hospital_address"]["value"]
    assert f["unit_brand"]["value"] == "GE"
    assert "OPTIMA XR200 AMX" in f["unit_type_serial"]["value"]
    assert "SB2002000027WK" in f["unit_type_serial"]["value"]
    assert f["tube_brand"]["value"] == "CANON"
    assert "E7894X" in f["tube_type_serial"]["value"]
    assert "20G225" in f["tube_type_serial"]["value"]
    assert "radiation_exposure_acceptance" in f
    assert f["radiation_exposure_acceptance"]["value"] == "-"


def test_paparan_radiasi_insert_sn_priority():
    from src.extraction.document_parser import parse_document
    p1_full_ocr = (
        "BERITA ACARA PENGUKURAN PAPARAN RADIASI\n"
        "Data Pelanggan/Rumah Sakit Rumkit Tk. IV Pekanbaru\n"
        "Nama Rumah Sakit JI. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau\n"
        "8 Jenis Alat OPTIMA XR200 AMX\n"
        "10 No Model SB2002000027WK\n"
        "15 Tipe Tabung 2 CANON ELECTRON\n"
        "18 No Model Tabung E7894X\n"
        "19 No Seri Tabung 20G225\n"
        "20 No Model Insert E7894\n"
        "21 No Seri Insert 0F1376\n"
    )
    res = parse_document("paparan_radiasi", [p1_full_ocr])
    f = res["fields"]
    assert f["tube_serial_number"]["value"] == "0F1376"
    assert f["tube_type"]["value"] == "E7894"
    assert "0F1376" in f["tube_type_serial"]["value"]


def test_paparan_radiasi_ocr_interleaved_and_letter_o_normalization():
    from src.extraction.document_parser import parse_document
    # Reproduce actual OCR quirks from scanned PDF:
    # 1. Row 20 and Row 19 interleaved by OCR reading order: "20 No Model Insert 19 No Seri Tabung E7894 0.9 mm Al"
    # 2. Letter 'O' instead of digit '0' in serial number: "OF1376"
    p1_scanned_ocr = (
        "BERITA ACARA PENGUKURAN PAPARAN RADIASI\n"
        "Data Pelanggan/Rumah Sakit Rumkit Tk. IV Pekanbaru\n"
        "Nama Rumah Sakit JI. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau\n"
        "8 Jenis Alat OPTIMA XR200 AMX\n"
        "10 No Model SB2002000027WK\n"
        "15 Tipe Tabung 2 CANON ELECTRON 1.2 mm x 1.2 mm\n"
        "17 Tahun Pembuatan E7894X 0.6 mm x 0.6 mm\n"
        "18 No Model Tabung 20G225 27 Filter Inhirent :\n"
        "20 No Model Insert 19 No Seri Tabung E7894 0.9 mm Al pada 75 kV\n"
        "21 No Seri Insert OF1376 Tambahan: pada 70 kV\n"
    )
    res = parse_document("paparan_radiasi", [p1_scanned_ocr])
    f = res["fields"]
    # tube_type should extract 'E7894' and NOT bullet number '19'
    assert f["tube_type"]["value"] == "E7894"
    # tube_serial_number should normalize 'OF1376' (letter O) to '0F1376' (digit 0)
    assert f["tube_serial_number"]["value"] == "0F1376"
    assert f["tube_type_serial"]["value"] == "E7894 / 0F1376"


def test_uji_fungsi_extraction():
    from src.extraction.document_parser import parse_document

    # 1. Test Siemens / Hermina format
    hermina_text = (
        "BERITA ACARA UJI FUNGSI\n"
        "Pelanggan :RS Hermina Ciputat\n"
        "Alamat :Jl. Kertamukti No.2, Ciputat, Tangerang Selatan\n"
        "PT. SIEMENS HEALTHINEERS INDONESIA\n"
        "Nama Alat : Somatom go Top\n"
        "Nomor seri alat :209141\n"
        "Nomor seri housing tabung1 : 133212682\n"
        "Nomor seri insert tabung :672152671\n"
    )
    res_h = parse_document("uji_fungsi", [hermina_text])
    fh = res_h["fields"]
    assert fh["hospital_name"]["value"] == "RS Hermina Ciputat"
    assert "Kertamukti No.2" in fh["hospital_address"]["value"]
    assert fh["unit_brand"]["value"] == "Siemens"
    assert "Somatom go Top" in fh["unit_type_serial"]["value"]
    assert "209141" in fh["unit_type_serial"]["value"]
    assert fh["unit_serial_number"]["value"] == "209141"
    assert fh["tube_brand"]["value"] == "Siemens"
    assert "672152671" in fh["tube_type_serial"]["value"]

    # 2. Test Glomeda / GE Pekanbaru format
    pekanbaru_text = (
        "GLOMEDA Functional Test Report Installation Mechanical\n"
        "Hospital Name : Rumkit Tk. IV Pekanbaru\n"
        "Address : Jl. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau\n"
        "Unit Type XR200 AMX\n"
        "Main Unit 5555000-4 SB2002000027WK\n"
        "Colimator 5129498 192162HL6 20G225 Collimator PASS\n"
        "Tube E7894 Tube Voltage (kV) Accuracy PASS\n"
        "The system unit meet GE specification\n"
    )
    res_p = parse_document("uji_fungsi", [pekanbaru_text])
    fp = res_p["fields"]
    assert fp["hospital_name"]["value"] == "Rumkit Tk. IV Pekanbaru"
    assert "Kesehatan No.2" in fp["hospital_address"]["value"]
    assert fp["unit_brand"]["value"] == "GE"
    assert "XR200 AMX" in fp["unit_type_serial"]["value"]
    assert "SB2002000027WK" in fp["unit_type_serial"]["value"]
    assert fp["unit_serial_number"]["value"] == "SB2002000027WK"
    assert fp["tube_brand"]["value"] == "-"
    assert "E7894" in fp["tube_type_serial"]["value"]
    assert "20G225" in fp["tube_type_serial"]["value"]

    # 3. Test Philips / RSUD Ir. Soekarno CAF format (without tube details)
    soekarno_text = (
        "Customer Acceptance Form\n"
        "Ref. No: 0090/CAF/SIHREN/VII/2026\n"
        "Customer Name Rumah Sakit Umum Daerah Ir. BJ.01.01/D.VII.12/139/2025\n"
        "Nama Pelanggan Soekarno No. Kontrak\n"
        "JI. Dr. Muwardi No.71, Bulusari, Serial number\n"
        "Customer Address Gayam, Kec. Sukoharjo, (if applicable) 340\n"
        "Alamat Pelanggan Tengah Kabupaten Sukoharjo, Jawa Nomor seri (jika ada)\n"
        "Equipment ID # Azurion 5 M20 (722232)\n"
        "PHILIPS PT PHILIPS INDONESIA COMMERCIAL\n"
    )
    res_s = parse_document("uji_fungsi", [soekarno_text])
    fs = res_s["fields"]
    assert fs["hospital_name"]["value"] == "Rumah Sakit Umum Daerah Ir. Soekarno"
    assert "Muwardi No.71" in fs["hospital_address"]["value"]
    assert fs["unit_brand"]["value"] == "Philips"
    assert "Azurion 5 M20" in fs["unit_type_serial"]["value"]
    assert "340" in fs["unit_type_serial"]["value"]
    assert fs["unit_serial_number"]["value"] == "340"
    # Tube details in Philips CAF are absent/empty without causing error
    assert fs["tube_brand"]["value"] == "-"
    assert fs["tube_type"]["value"] == "-"
    assert fs["tube_serial_number"]["value"] == "-"


def test_generalization_unseen_hospital_and_provinces():
    """Verify parser robustness against completely new hospitals, cities, and regions across Indonesia."""
    from src.extraction.document_parser import parse_document

    # 1. New hospital in Bali with Shimadzu unit
    bali_text = (
        "BERITA ACARA UJI FUNGSI\n"
        "Pelanggan : RSUD Mangusada Badung\n"
        "Alamat : Jl. Raya Kapal, Mengwi, Kabupaten Badung, Bali 80351\n"
        "Manufacturer : SHIMADZU CORPORATION\n"
        "Model Alat : RADspeed Pro Edge\n"
        "Nomor seri alat : SH-998877\n"
        "Model Tabung : Circlex 0.6/1.2\n"
        "No. Seri Tabung : TB-776655\n"
    )
    res_b = parse_document("uji_fungsi", [bali_text])
    fb = res_b["fields"]
    assert fb["hospital_name"]["value"] == "RSUD Mangusada Badung"
    assert "Jl. Raya Kapal" in fb["hospital_address"]["value"]
    assert "Bali" in fb["hospital_address"]["value"]
    assert fb["unit_brand"]["value"] == "Shimadzu"
    assert "RADspeed Pro Edge" in fb["unit_type_serial"]["value"]
    assert fb["unit_serial_number"]["value"] == "SH-998877"
    assert fb["tube_serial_number"]["value"] == "TB-776655"

    # 2. New hospital in Papua with Paparan Radiasi
    papua_text = (
        "LAPORAN PENGUKURAN PAPARAN RADIASI\n"
        "Nama Rumah Sakit : RSUP Jayapura\n"
        "Alamat Rumah Sakit : Jl. Kesehatan No. 1 Dok II, Kota Jayapura, Papua 99112\n"
        "Merk Alat : CARESTREAM HEALTH\n"
        "Model Alat : DRX-Evolution Plus\n"
        "No Seri Alat : CS-334455\n"
        "Tipe Tabung : VARIAN RAD-60\n"
        "No Seri Tabung : VR-112233\n"
    )
    res_p = parse_document("paparan_radiasi", [papua_text])
    fp = res_p["fields"]
    assert fp["hospital_name"]["value"] == "RSUP Jayapura"
    assert "Jl. Kesehatan No. 1" in fp["hospital_address"]["value"]
    assert "Jayapura" in fp["hospital_address"]["value"]
    assert fp["unit_brand"]["value"] == "CARESTREAM"
    assert "DRX-Evolution Plus" in fp["unit_type_serial"]["value"]
    assert fp["unit_serial_number"]["value"] == "CS-334455"


def test_smart_hybrid_ocr_and_merge_for_scanned_tables():
    """Verify that a document with a digital header but raster image table is accurately parsed
    when digital text and OCR text are merged together."""
    from src.extraction.document_parser import parse_document

    # Simulate Glomeda where header is digital text, but table was only in OCR content
    digital_header = (
        "GLOMEDA Functional Test Report\n"
        "Report Ref Number : 110/INSTALASI/GMD/11.11.2026\n"
        "Hospital Information\n"
        "Hospital Name : Rumkit Tk. IV Pekanbaru\n"
        "Address : Jl. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau\n"
        "Unit Information\n"
        "Unit Type : XR200 AMX\n"
    )
    ocr_scanned_table = (
        "Subsystem Model No Serial No\n"
        "Main Unit 5555000-4 SB2002000027WK\n"
        "Colimator 5129498 192162HL6\n"
        "Tube E7894 20G225\n"
        "Generator 5555000-4 SB2002000027WK\n"
        "The system unit meet GE specification\n"
    )

    merged_page_text = f"{digital_header}\n\n--- OCR EXTRACTED CONTENT ---\n{ocr_scanned_table}"

    res = parse_document("uji_fungsi", [merged_page_text])
    fields = res["fields"]

    # Verify header came from digital text cleanly
    assert fields["hospital_name"]["value"] == "Rumkit Tk. IV Pekanbaru"
    assert "Kesehatan No.2" in fields["hospital_address"]["value"]
    assert fields["unit_brand"]["value"] == "GE"
    assert "XR200 AMX" in fields["unit_type_serial"]["value"]

    # Verify equipment & tube specs came from OCR scanned table seamlessly
    assert fields["unit_serial_number"]["value"] == "SB2002000027WK"
    assert "SB2002000027WK" in fields["unit_type_serial"]["value"]
    assert fields["tube_serial_number"]["value"] == "20G225"
    assert "20G225" in fields["tube_type_serial"]["value"]
    assert "E7894" in fields["tube_type_serial"]["value"]
    assert fields["tube_brand"]["value"] == "-"


def test_uji_fungsi_and_paparan_radiasi_address_name_boundary_fixes():
    """Verify that Uji Fungsi strips adjacent table text ('Tube tilt PASS') from hospital_name
    and Paparan Radiasi correctly extracts street address while ignoring adjacent person names."""
    from src.extraction.document_parser import parse_document

    # 1. Uji Fungsi with horizontal mechanical table text on the same line
    uf_text = (
        "GLOMEDA Functional Test Report Installation Mechanical\n"
        "Report Ref Number 110/INSTALASI/GMD/11.11.2026 Horizontal tube arm rotation PASS\n"
        "Hospital Information Vertical columm Rotation PASS\n"
        "Hospital Name : Rumkit Tk. IV Pekanbaru Tube tilt PASS\n"
        "Address : Jl. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau Collimator Rotation PASS\n"
        "Unit Type XR200 AMX\n"
        "Main Unit 5555000-4 SB2002000027WK\n"
    )
    p_uf = parse_document("uji_fungsi", [uf_text])
    assert p_uf["fields"]["hospital_name"]["value"] == "Rumkit Tk. IV Pekanbaru"
    assert "Tube tilt" not in p_uf["fields"]["hospital_name"]["value"]
    assert "PASS" not in p_uf["fields"]["hospital_name"]["value"]
    assert "Kesehatan No.2" in p_uf["fields"]["hospital_address"]["value"]
    assert "Collimator" not in p_uf["fields"]["hospital_address"]["value"]

    # 2. Paparan Radiasi with companion name on adjacent row
    pr_text = (
        "BERITA ACARA PENGUKURAN PAPARAN RADIASI GLOMEDA\n"
        "No Dokumen 110 INSTALASI 1 11.01.2026\n"
        "Data Pelanggan/Rumah Sakit Rumkit Tk. IV Pekanbaru\n"
        "Nama Rumah Sakit JI. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau\n"
        "2 Alamat Rumah Sakit Nama Pendamping Pengukuran sry wulandari\n"
        "3 Jabatan Pendamping Pengukuran Radiographer\n"
        "Data Pengalih 5 Nama Pengalih PT. Global Medik Persada\n"
        "6 Alamat Pengalih JI. Raya Kb. Jeruk No.26, RW.2, Kb. Jeruk, Jakarta Barat\n"
        "Data Alat Mobile Xray OPTIMA XR200 AMX 555000-4 SB2002000027WK\n"
    )
    p_pr = parse_document("paparan_radiasi", [pr_text])
    assert p_pr["fields"]["hospital_name"]["value"] == "Rumkit Tk. IV Pekanbaru"
    assert "Kesehatan No.2" in p_pr["fields"]["hospital_address"]["value"]
    assert "sry wulandari" not in p_pr["fields"]["hospital_address"]["value"]
    assert "Nama Pendamping" not in p_pr["fields"]["hospital_address"]["value"]


def test_multilingual_tube_synonym_variations():
    from src.extraction.document_parser import parse_document

    # 1. English format test (Tube Insert S/N, Housing S/N)
    eng_text = (
        "Customer Acceptance Report / Functional Test\n"
        "Hospital Name: RS Sehat Sejahtera\n"
        "Address: Jl. Sudirman No. 10 Jakarta\n"
        "Model: Optima XR200\n"
        "Unit S/N: SB999888\n"
        "Tube Manufacturer: CANON\n"
        "Housing Model: E7894X\n"
        "Housing S/N: 20G999\n"
        "Tube Insert Model: E7894\n"
        "Tube Insert S/N: 0F9999\n"
    )
    res_eng = parse_document("paparan_radiasi", [eng_text])
    f_eng = res_eng["fields"]
    assert f_eng["tube_serial_number"]["value"] == "0F9999"
    assert f_eng["tube_type"]["value"] == "E7894"

    # 2. Indonesian formal format test (Tabung Sisipan / Wadah Tabung)
    id_text = (
        "BERITA ACARA UJI KESESUAIAN\n"
        "Nama Fasilitas: RS Permata Bunda\n"
        "Alamat Fasilitas: Jl. Pemuda No. 45 Bandung\n"
        "Pabrikan Unit: GE\n"
        "Model Unit: XR200\n"
        "Nomor Seri: SB111222\n"
        "Merek Tabung: CANON\n"
        "Tipe Tabung Sisipan: E7894\n"
        "Nomor Seri Tabung Sisipan: 0F8888\n"
        "Nomor Seri Wadah Tabung: 20G888\n"
    )
    res_id = parse_document("uji_kesesuaian", [id_text])
    f_id = res_id["fields"]
    assert f_id["tube_serial_number"]["value"] == "0F8888"
    assert f_id["tube_type"]["value"] == "E7894"


def test_parse_sprint_sk_decree_format():
    """Verify parsing of SK decree format for Surat Perintah (Sprint),
    preventing false matches on preamble legal text and correctly extracting
    PPR person and director signer."""
    from src.extraction.document_parser import parse_document

    page1_text = (
        "PT MEDIKA LOKA KEPANJEN\n"
        "RUMAH SAKIT HERMINA KEPANJEN\n"
        "Jalan Raya Mojosari RT 02/RW 01, Kelurahan Mojosari, Kecamatan Kepanjen, Malang\n"
        "KEPUTUSAN DIREKTUR RUMAH SAKIT HERMINA KEPANJEN\n"
        "NOMOR 016/KEP-DIR/RSHKPN/VI/2026\n"
        "TENTANG\n"
        "PENUNJUKKAN DAN PENGANGKATAN\n"
        "SDR/I SITI AZIZAH\n"
        "SEBAGAI\n"
        "PETUGAS PROTEKSI RADIASI (PPR)\n"
        "RUMAH SAKIT HERMINA KEPANJEN\n"
        "DIREKTUR RUMAH SAKIT HERMINA KEPANJEN,\n"
        "Menimbang : a. bahwa dalam upaya meningkatkan mutu pelayanan kesehatan kepada pasien, "
        "maka diperlukan adanya seorang Petugas Proteksi Radiasi di Instalasi Radiologi;\n"
        "b. bahwa Sdr/i Siti Azizah dinilai mampu dan cakap sebagai Petugas Proteksi Radiasi (PPR);\n"
        "Mengingat : 5. Tentang Pengesahan Peraturan Perusahaan PT Medikaloka Hermina Tbk;\n"
    )

    page2_text = (
        "MEMUTUSKAN :\n"
        "Menetapkan : KEPUTUSAN DIREKTUR TENTANG PENUNJUKAN DAN PENGANGKATAN SDR/I SITI AZIZAH SEBAGAI PPR.\n"
        "Ditetapkan di Kepanjen\n"
        "Pada tanggal 09 Juni 2026\n"
        "DIREKTUR,\n"
        "\n"
        "dr. DEDE SETYADI, MARS\n"
    )

    res = parse_document("sprint", [page1_text, page2_text])
    f = res["fields"]

    # PPR Name should be SITI AZIZAH, NOT 'pasien'
    assert f["ppr_name"]["value"] == "SITI AZIZAH"
    assert f["ppr_name"]["page"] == 1

    # Approval should be dr. DEDE SETYADI, MARS, NOT 'Peraturan Perusahaan...'
    assert f["approval"]["value"] == "dr. DEDE SETYADI, MARS"
    assert f["approval"]["page"] == 2


def test_ppkr_tube_insert_serial_priority():
    from src.extraction.document_parser import parse_document

    p14_text = (
        "III.1.1. Spesifikasi Teknis Pesawat General Radiografi\n"
        "Nama ruangan : Radiologi\n"
        "Data pesawat\n"
        "Merk pesawat sinar-X : GE\n"
        "Tipe/model pesawat sinar-X : OPTIMA XR200AMX\n"
        "No. Seri pesawat sinar-X : SB2002000027WK\n"
        "Data tabung\n"
        "Merk tabung : CANON\n"
        "Tipe tabung : E7894X\n"
        "No. Seri tabung : 20G225\n"
        "Nomor seriinsersi 0F1376\n"
        "tabung sinar X\n"
    )

    res = parse_document("ppkr", [p14_text])
    f = res["fields"]

    assert f["unit_brand"]["value"] == "GE"
    assert f["unit_type"]["value"] == "OPTIMA XR200AMX"
    assert f["unit_serial_number"]["value"] == "SB2002000027WK"
    assert f["tube_brand"]["value"] == "CANON"
    assert f["tube_type"]["value"] == "E7894X"
    assert f["tube_serial_number"]["value"] == "0F1376"
    assert f["tube_type_serial"]["value"] == "E7894X / 0F1376"










