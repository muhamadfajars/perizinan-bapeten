from src.schema.fields import DOCUMENT_TYPES, DOCUMENT_FIELDS, FIELD_DEFINITIONS


def test_master_schema_has_15_document_types():
    assert len(DOCUMENT_TYPES) == 15
    assert set(DOCUMENT_TYPES) == set(DOCUMENT_FIELDS)
    assert "sertifikat_mutu" not in DOCUMENT_TYPES


def test_required_label_fields_are_present():
    assert DOCUMENT_FIELDS["label_tabung"] == [
        "tube_brand", "tube_type", "tube_serial_number", "tube_unit_model", "tube_insert_model"
    ]
    assert DOCUMENT_FIELDS["label_unit"] == [
        "unit_brand", "unit_type", "unit_serial_number"
    ]


def test_schema_fields_for_uji_kesesuaian_import_paparan():
    assert DOCUMENT_FIELDS["uji_kesesuaian"] == [
        "hospital_name", "hospital_address", "unit_brand", "unit_type", "unit_serial_number", "tube_brand", "tube_type", "tube_serial_number"
    ]
    assert DOCUMENT_FIELDS["persetujuan_import"] == [
        "unit_brand", "unit_type", "unit_serial_number", "tube_brand", "tube_type", "tube_serial_number"
    ]
    assert DOCUMENT_FIELDS["paparan_radiasi"] == [
        "hospital_name", "hospital_address", "unit_brand", "unit_type", "unit_serial_number", "tube_brand", "tube_type", "tube_serial_number", "radiation_exposure_acceptance"
    ]
    assert DOCUMENT_FIELDS["uji_fungsi"] == [
        "hospital_name", "hospital_address", "unit_brand", "unit_type", "unit_serial_number", "tube_brand", "tube_type", "tube_serial_number"
    ]
    assert "radiation_exposure_acceptance" in DOCUMENT_FIELDS["paparan_radiasi"]
    assert "xray_data" not in DOCUMENT_FIELDS["paparan_radiasi"]
    assert "xray_data" not in DOCUMENT_FIELDS["uji_fungsi"]
    assert "xray_data" not in DOCUMENT_FIELDS["formulir"]
    assert "xray_data" not in FIELD_DEFINITIONS
