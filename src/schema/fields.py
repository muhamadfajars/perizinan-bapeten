"""Master schema for the BAPETEN document cross-check application.

The field list follows the user-provided document:
"Identifikasi Field dan Validasi Cross-Check Dokumen Perizinan".
Fields not explicitly specified there are not added as requirements.
"""

DOCUMENT_TYPES = {
    "formulir": {
        "name": "Formulir Permohonan",
        "kind": "pdf",
    },
    "sip": {
        "name": "Surat Izin Praktik (SIP)",
        "kind": "pdf",
    },
    "sprint": {
        "name": "Surat Perintah (Sprint)",
        "kind": "pdf",
    },
    "sib": {
        "name": "SIB",
        "kind": "pdf",
    },
    "spesifikasi_pesawat": {
        "name": "Spesifikasi Pesawat Sinar-X",
        "kind": "pdf",
    },
    "tld": {
        "name": "Surat Pengiriman/Penyerahan TLD",
        "kind": "pdf",
    },
    "sistem_manajemen": {
        "name": "Dokumen Sistem Manajemen Fasilitas Radiologi Diagnostik dan Intervensional",
        "kind": "pdf",
    },
    "program_perawatan": {
        "name": "Dokumen Program Perawatan Pesawat Sinar-X Radiologi Diagnostik dan Intervensional",
        "kind": "pdf",
    },
    "ppkr": {
        "name": "Dokumen Program Proteksi dan Keselamatan Radiasi",
        "kind": "pdf",
    },
    "label_tabung": {
        "name": "Foto Label Tabung",
        "kind": "image",
    },
    "label_unit": {
        "name": "Foto Label Unit",
        "kind": "image",
    },
    "paparan_radiasi": {
        "name": "Hasil Pengukuran Paparan Radiasi",
        "kind": "pdf",
    },
    "uji_fungsi": {
        "name": "Hasil Uji Fungsi",
        "kind": "pdf",
    },
    "persetujuan_import": {
        "name": "Persetujuan Import",
        "kind": "pdf",
    },
    "uji_kesesuaian": {
        "name": "Uji Kesesuaian",
        "kind": "pdf",
    },
}

FIELD_DEFINITIONS = {
    "hospital_name": {"label": "Nama rumah sakit", "group": "facility"},
    "hospital_address": {"label": "Alamat rumah sakit", "group": "facility"},
    "administrative_documents": {"label": "Dokumen kelengkapan administrasi", "group": "administration"},
    "personnel_data": {"label": "Data petugas", "group": "personnel"},
    "profession": {"label": "Profesi/keahlian", "group": "personnel"},
    "valid_until": {"label": "Masa berlaku", "group": "validity", "type": "date"},
    "practice_location": {"label": "Alamat praktik", "group": "facility"},
    "ppr_name": {"label": "Nama PPR", "group": "ppr"},
    "approval": {"label": "Pengesahan (Tanda tangan dan stempel)", "group": "approval"},
    "kepada": {"label": "Kepada (Nama PPR)", "group": "ppr"},
    "pengesahan": {"label": "Pengesahan (Tanda tangan dan stempel)", "group": "approval"},
    "unit_brand": {"label": "Merk Unit", "group": "equipment"},
    "unit_type": {"label": "Tipe unit", "group": "equipment"},
    "person_name": {"label": "Nama", "group": "personnel"},
    "usage_period": {"label": "Periode pemakaian", "group": "validity"},
    "conformity_test_clause": {"label": "Klausul uji kesesuaian", "group": "document_content"},
    "unit_serial_number": {"label": "No Seri unit", "group": "equipment", "type": "serial"},
    "tube_brand": {"label": "Merk Tabung", "group": "equipment"},
    "tube_type": {"label": "Tipe tabung", "group": "equipment"},
    "tube_unit_model": {"label": "Unit model", "group": "equipment", "type": "model"},
    "tube_insert_model": {"label": "Insert model", "group": "equipment", "type": "model"},
    "tube_serial_number": {"label": "No. Seri Tabung", "group": "equipment", "type": "serial"},
    "radiation_exposure_acceptance": {"label": "Keberterimaan paparan radiasi", "group": "radiation"},
    "unit_type_serial": {"label": "Tipe/no. seri unit", "group": "equipment"},
    "tube_model": {"label": "Model tabung", "group": "equipment", "type": "model"},
    "tube_type_serial": {"label": "Tipe/no. seri tabung", "group": "equipment"},
}

# Canonical groups keep the same underlying entity together across document types.
CANONICAL_GROUPS = {
    "facility_name": "hospital_name",
    "facility_address": "hospital_address",
    "person_name": "person_name",
    "ppr_name": "ppr_name",
    "unit_brand": "unit_brand",
    "unit_type": "unit_type",
    "unit_serial_number": "unit_serial_number",
    "unit_type_serial": "unit_type_serial",
    "tube_brand": "tube_brand",
    "tube_type": "tube_type",
    "tube_serial_number": "tube_serial_number",
    "tube_type_serial": "tube_type_serial",
}

# Cross-check rules describe which source documents can be compared.
# These are comparison relationships, not permit acceptance rules.
CROSS_CHECK_RULES = [
    {
        "rule_id": "CC-01",
        "field": "hospital_name",
        "documents": ["formulir", "sprint", "tld", "sistem_manajemen", "program_perawatan", "ppkr", "paparan_radiasi", "uji_fungsi", "uji_kesesuaian"],
        "mode": "fuzzy_name",
    },
    {
        "rule_id": "CC-02",
        "field": "hospital_address",
        "documents": ["formulir", "sprint", "tld", "sistem_manajemen", "program_perawatan", "ppkr", "paparan_radiasi", "uji_fungsi", "uji_kesesuaian"],
        "mode": "fuzzy_address",
    },
    {
        "rule_id": "CC-03",
        "field": "person_name",
        "documents": ["formulir", "sip", "sprint", "tld", "ppkr"],
        "mode": "fuzzy_name",
    },
    {
        "rule_id": "CC-04",
        "field": "profession",
        "documents": ["formulir", "sip", "sib"],
        "mode": "fuzzy_text",
    },
    {
        "rule_id": "CC-05",
        "field": "ppr_name",
        "documents": ["formulir", "sprint", "sib", "ppkr"],
        "mode": "fuzzy_name",
    },
    {
        "rule_id": "CC-06",
        "field": "unit_brand",
        "documents": ["formulir", "spesifikasi_pesawat", "ppkr", "label_unit", "persetujuan_import", "uji_kesesuaian", "paparan_radiasi", "uji_fungsi"],
        "mode": "brand",
    },
    {
        "rule_id": "CC-07",
        "field": "unit_type",
        "documents": ["formulir", "spesifikasi_pesawat", "ppkr", "label_unit", "persetujuan_import", "uji_kesesuaian", "paparan_radiasi", "uji_fungsi"],
        "mode": "fuzzy_text",
    },
    {
        "rule_id": "CC-08",
        "field": "unit_serial_number",
        "documents": ["formulir", "ppkr", "label_unit", "persetujuan_import", "uji_kesesuaian", "paparan_radiasi", "uji_fungsi"],
        "mode": "serial",
    },
    {
        "rule_id": "CC-09",
        "field": "tube_brand",
        "documents": ["formulir", "ppkr", "label_tabung", "uji_kesesuaian", "persetujuan_import", "paparan_radiasi", "uji_fungsi"],
        "mode": "brand",
    },
    {
        "rule_id": "CC-10",
        "field": "tube_type",
        "documents": ["formulir", "ppkr", "label_tabung", "uji_kesesuaian", "persetujuan_import", "paparan_radiasi", "uji_fungsi"],
        "mode": "fuzzy_text",
    },
    {
        "rule_id": "CC-11",
        "field": "tube_serial_number",
        "documents": ["formulir", "ppkr", "label_tabung", "uji_kesesuaian", "persetujuan_import", "paparan_radiasi", "uji_fungsi"],
        "mode": "serial",
    },
]

# Explicit field assignment per document. This is the authoritative extraction scope.
DOCUMENT_FIELDS = {
    "formulir": [
        "hospital_name",
        "hospital_address",
        "personnel_data",
        "unit_brand",
        "unit_type",
        "unit_serial_number",
        "tube_brand",
        "tube_type",
        "tube_serial_number",
    ],
    "sip": [
        "person_name",
        "profession",
        "valid_until",
        "practice_location",
    ],
    "sprint": [
        "hospital_name",
        "hospital_address",
        "ppr_name",
        "approval",
    ],
    "sib": [
        "ppr_name",
        "profession",
        "valid_until",
    ],
    "spesifikasi_pesawat": [
        "unit_brand",
        "unit_type",
    ],
    "tld": [
        "hospital_name",
        "hospital_address",
        "person_name",
        "usage_period",
    ],
    "sistem_manajemen": [
        "hospital_name",
        "hospital_address",
    ],
    "program_perawatan": [
        "hospital_name",
        "hospital_address",
        "conformity_test_clause",
    ],
    "ppkr": [
        "hospital_name",
        "hospital_address",
        "personnel_data",
        "unit_brand",
        "unit_type",
        "unit_serial_number",
        "tube_brand",
        "tube_type",
        "tube_serial_number",
    ],
    "label_tabung": [
        "tube_brand",
        "tube_type",
        "tube_serial_number",
        "tube_unit_model",
        "tube_insert_model",
    ],
    "label_unit": [
        "unit_brand",
        "unit_type",
        "unit_serial_number",
    ],
    "paparan_radiasi": [
        "hospital_name",
        "hospital_address",
        "unit_brand",
        "unit_type",
        "unit_serial_number",
        "tube_brand",
        "tube_type",
        "tube_serial_number",
        "radiation_exposure_acceptance",
    ],
    "uji_fungsi": [
        "hospital_name",
        "hospital_address",
        "unit_brand",
        "unit_type",
        "unit_serial_number",
        "tube_brand",
        "tube_type",
        "tube_serial_number",
    ],
    "persetujuan_import": [
        "unit_brand",
        "unit_type",
        "unit_serial_number",
        "tube_brand",
        "tube_type",
        "tube_serial_number",
    ],
    "uji_kesesuaian": [
        "hospital_name",
        "hospital_address",
        "unit_brand",
        "unit_type",
        "unit_serial_number",
        "tube_brand",
        "tube_type",
        "tube_serial_number",
    ],
}
