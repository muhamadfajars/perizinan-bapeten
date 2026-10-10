from src.extraction.classifier import classify_by_filename, classify_document


def test_classify_by_filename():
    assert classify_by_filename("formulir_1.pdf") == "formulir"
    assert classify_by_filename("surat_izin_praktik_dokter.pdf") == "sip"
    assert classify_by_filename("sprint_ppr_2026.pdf") == "sprint"
    assert classify_by_filename("surat_tugas_ppr.pdf") == "sprint"
    assert classify_by_filename("sib_petugas.pdf") == "sib"
    assert classify_by_filename("tld_nuklindolab.pdf") == "tld"
    assert classify_by_filename("sistem_manajemen_radiologi.pdf") == "sistem_manajemen"
    assert classify_by_filename("program_perawatan_alat.pdf") == "program_perawatan"
    assert classify_by_filename("ppkr_radiasi.pdf") == "ppkr"
    assert classify_by_filename("label_tabung_1.jpeg") == "label_tabung"
    assert classify_by_filename("label_unit_1.jpeg") == "label_unit"
    assert classify_by_filename("paparan_radiasi_1.pdf") == "paparan_radiasi"
    assert classify_by_filename("Hasil Pengukuran Paparan Radiasi+Kebocoran Tabung RS Tk4 Pku.pdf") == "paparan_radiasi"
    assert classify_by_filename("20260908081104-Dokumen Program Perawatan Pesawat Sinar-X Radiologi Diagnostik dan Intervensional RSTKIVPKU.pdf") == "program_perawatan"
    assert classify_by_filename("20260824104643-Spesifikasi Optima XR200amx (1).pdf") == "spesifikasi_pesawat"
    assert classify_by_filename("Foto label unit.jpeg") == "label_unit"
    assert classify_by_filename("Foto label tabung.jpeg") == "label_tabung"
    assert classify_by_filename("Foto keseluruhan pesawat.jpeg") == "label_unit"
    assert classify_by_filename("uji_fungsi_pesawat.pdf") == "uji_fungsi"
    assert classify_by_filename("laporan_uji_kesesuaian.pdf") == "uji_kesesuaian"
    # Additional robust filename variations
    assert classify_by_filename("bauf_pesawat.pdf") == "uji_fungsi"
    assert classify_by_filename("bast_alat.pdf") == "uji_fungsi"
    assert classify_by_filename("lhu_rontgen_2026.pdf") == "uji_kesesuaian"
    assert classify_by_filename("surat_persetujuan_impor_bapeten.pdf") == "persetujuan_import"
    assert classify_by_filename("brosur_teknis_optima.pdf") == "spesifikasi_pesawat"
    assert classify_by_filename("datasheet_ge_xr200.pdf") == "spesifikasi_pesawat"
    assert classify_by_filename("kartu_sib_bapeten.pdf") == "sib"
    assert classify_by_filename("denah_ruangan_radiasi.pdf") == "paparan_radiasi"
    assert classify_by_filename("tube_housing_plate.jpg") == "label_tabung"


def test_classify_document():
    doc_type, reason = classify_document("formulir_1.pdf")
    assert doc_type == "formulir"
    assert reason == "Nama Berkas"

    doc_type_img, reason_img = classify_document("foto_plat_mesin.jpg")
    assert doc_type_img == "label_unit"
    assert "Gambar" in reason_img or "Plat" in reason_img


def test_classify_document_by_content_simulation(monkeypatch):
    # Simulate digital PDF text with generic filename scan001.pdf
    from src.extraction import classifier

    orig_classify_content = classifier.classify_by_content

    # Mock content detection
    monkeypatch.setattr(classifier, "classify_by_content", lambda data: ("sib", "Teks Digital Dokumen"))
    doc_type, reason = classifier.classify_document("scan001.pdf", b"fake_bytes")
    assert doc_type == "sib"
    assert reason == "Teks Digital Dokumen"
