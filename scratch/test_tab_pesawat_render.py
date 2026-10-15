import sys
sys.path.insert(0, ".")
import app

docs_map = {
    "formulir": ["Formulir_Permohonan.pdf"],
    "label_unit": ["Label_Unit.jpg"],
    "uji_kesesuaian": ["Laporan_Uji_Kesesuaian.pdf"],
}

# 1. Test unit parameter cards
fv_brand = {
    "status": "SESUAI",
    "field_key": "unit_brand",
    "sources": [
        {"document_type": "formulir", "document_name": "Formulir_Permohonan.pdf", "value": "GE Healthcare", "page": 2},
        {"document_type": "label_unit", "document_name": "Label_Unit.jpg", "value": "GE Medical Systems", "page": 1},
        {"document_type": "uji_kesesuaian", "document_name": "Laporan_Uji_Kesesuaian.pdf", "value": "GE", "page": 1},
    ]
}

fv_serial = {
    "status": "SESUAI",
    "field_key": "unit_serial_number",
    "sources": [
        {"document_type": "formulir", "document_name": "Formulir_Permohonan.pdf", "value": "SN-987654-X", "page": 2},
        {"document_type": "label_unit", "document_name": "Label_Unit.jpg", "value": "SN987654X", "page": 1},
        {"document_type": "uji_kesesuaian", "document_name": "Laporan_Uji_Kesesuaian.pdf", "value": "SN-987654-X", "page": 1},
    ]
}

captured = []
app.render_html = lambda h: captured.append(h)

app._render_parameter_card("Parameter Unit Pesawat #1", "Merk Pesawat Sinar-X (Brand)", fv_brand, docs_map, expected_docs=app.XRAY_UNIT_BRAND_EXPECTED_DOCS)
app._render_parameter_card("Parameter Unit Pesawat #1", "Nomor Seri Pesawat Sinar-X (Serial Number)", fv_serial, docs_map, expected_docs=app.XRAY_UNIT_SERIAL_EXPECTED_DOCS)

# 2. Test tube parameter cards with missing values
app._render_parameter_card("Parameter Tabung Sinar-X #1", "Nomor Seri Tabung Sinar-X (Tube Serial Number)", {"sources": [], "field_key": "tube_serial_number"}, docs_map, expected_docs=app.XRAY_TUBE_SERIAL_EXPECTED_DOCS)

print(f"Captured {len(captured)} cards rendered successfully!")
for idx, html in enumerate(captured):
    assert "matrix-table" in html
    print(f"Card {idx+1} contains matrix-table (HTML len: {len(html)})")

print("ALL TAB PESAWAT RENDER TESTS PASSED!")
