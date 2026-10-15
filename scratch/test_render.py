import sys
sys.path.insert(0, ".")
import app

docs_map = {"formulir": ["Formulir_RS.pdf"], "sip": ["SIP_Dhanti.pdf"], "laporan_dosis_awal": ["Evaluasi_Dosis.pdf"]}
fv_name = {
    "status": "SESUAI",
    "field_key": "person_name",
    "reason": "Nama sesuai di 2 dokumen",
    "sources": [
        {"document_type": "formulir", "document_name": "Formulir_RS.pdf", "value": "dr. Dhanti Erma Widiasi, Sp.Rad", "page": 3},
        {"document_type": "sip", "document_name": "SIP_Dhanti.pdf", "value": "dr. Dhanti Erma Widiasi", "page": 1}
    ]
}

captured = []
app.render_html = lambda h: captured.append(h)
app._render_parameter_card("Field Identitas Personel #1", "Nama Personel", fv_name, docs_map, expected_docs=app.PERSONNEL_NAME_EXPECTED_DOCS)

with open("scratch/rendered_table_preview.html", "w", encoding="utf-8") as f:
    f.write(captured[0])

print("Written to scratch/rendered_table_preview.html successfully!")
