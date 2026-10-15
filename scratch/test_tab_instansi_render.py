import sys
sys.path.insert(0, ".")
import app

docs_map = {
    "formulir": ["Formulir_RS.pdf"],
    "sprint": ["Sprint_PPR.pdf"],
    "ppkr": ["Dokumen_PPKR.pdf"],
    "uji_kesesuaian": ["Uji_Kesesuaian.pdf"],
}

fv_hname = {
    "status": "SESUAI",
    "field_key": "project_name",
    "sources": [
        {"document_type": "formulir", "document_name": "Formulir_RS.pdf", "value": "RS Hermina Kemayoran", "page": 1},
        {"document_type": "sprint", "document_name": "Sprint_PPR.pdf", "value": "Rumah Sakit Hermina Kemayoran", "page": 1},
        {"document_type": "ppkr", "document_name": "Dokumen_PPKR.pdf", "value": "RS Hermina Kemayoran", "page": 2},
    ]
}

fv_haddr = {
    "status": "SESUAI",
    "field_key": "project_address",
    "sources": [
        {"document_type": "formulir", "document_name": "Formulir_RS.pdf", "value": "Jl. Selangit B-10 Kav. 4, Kemayoran, Jakarta Pusat", "page": 1},
        {"document_type": "uji_kesesuaian", "document_name": "Uji_Kesesuaian.pdf", "value": "Jl. Selangit B-10 Kav. 4, Kemayoran", "page": 1},
    ]
}

captured = []
app.render_html = lambda h: captured.append(h)

app._render_parameter_card(
    "Parameter Identitas Pemohon",
    "Nama Rumah Sakit / Instansi Pemohon",
    fv_hname,
    docs_map,
    expected_docs=app.FACILITY_NAME_EXPECTED_DOCS,
)

app._render_parameter_card(
    "Parameter Lokasi Fasilitas",
    "Alamat Rumah Sakit / Lokasi Fasilitas",
    fv_haddr,
    docs_map,
    expected_docs=app.FACILITY_ADDRESS_EXPECTED_DOCS,
)

print(f"Captured {len(captured)} cards rendered successfully!")
for idx, html in enumerate(captured):
    assert "matrix-table" in html
    assert "✓ Sesuai" in html or "✓ Terdaftar" in html
    print(f"Card {idx+1} contains matrix-table (HTML len: {len(html)})")

print("ALL TAB INSTANSI RENDER TESTS PASSED!")
