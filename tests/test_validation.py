from src.validation.rules import validate_cross_checks, document_presence
from src.schema.fields import DOCUMENT_TYPES


def test_validate_cross_checks():
    validate_cross_checks([
        {"status": "SESUAI"},
        {"status": "WARNING"},
        {"status": "TIDAK DITEMUKAN"},
    ])


def test_document_presence():
    rows = document_presence({"formulir": [{"file_name": "a.pdf"}]}, DOCUMENT_TYPES)
    assert rows[0]["document_type"] == "formulir"
    assert rows[0]["uploaded"] is True
    assert rows[1]["uploaded"] is False

    # Test with dict_keys object
    keys = {"formulir": []}.keys()
    rows_keys = document_presence(keys, DOCUMENT_TYPES)
    assert rows_keys[0]["uploaded"] is True

    # Test with list of document types
    rows_list = document_presence(["formulir"], DOCUMENT_TYPES)
    assert rows_list[0]["uploaded"] is True
