from src.schema.fields import DOCUMENT_TYPES, DOCUMENT_FIELDS


def test_master_schema_has_15_document_types():
    assert len(DOCUMENT_TYPES) == 15
    assert set(DOCUMENT_TYPES) == set(DOCUMENT_FIELDS)
    assert "sertifikat_mutu" not in DOCUMENT_TYPES


def test_required_label_fields_are_present():
    assert DOCUMENT_FIELDS["label_tabung"] == [
        "tube_unit_model", "tube_insert_model", "tube_serial_number", "tube_brand"
    ]
    assert DOCUMENT_FIELDS["label_unit"] == [
        "unit_brand", "unit_serial_number", "unit_type"
    ]


def test_schema_fields_for_uji_kesesuaian_import_paparan():
    assert DOCUMENT_FIELDS["uji_kesesuaian"] == [
        "hospital_name", "hospital_address", "unit_brand", "unit_type_serial", "tube_brand", "tube_type"
    ]
    assert DOCUMENT_FIELDS["persetujuan_import"] == [
        "unit_brand", "unit_type_serial", "tube_brand", "tube_type_serial"
    ]
    assert DOCUMENT_FIELDS["paparan_radiasi"] == [
        "hospital_name", "hospital_address", "unit_brand", "unit_type_serial", "tube_brand", "tube_type_serial"
    ]
    assert DOCUMENT_FIELDS["uji_fungsi"] == [
        "hospital_name", "hospital_address", "unit_brand", "unit_type_serial", "tube_brand", "tube_type_serial"
    ]
    assert "radiation_exposure_acceptance" not in DOCUMENT_FIELDS["paparan_radiasi"]
    assert "xray_data" not in DOCUMENT_FIELDS["paparan_radiasi"]
    assert "xray_data" not in DOCUMENT_FIELDS["uji_fungsi"]
