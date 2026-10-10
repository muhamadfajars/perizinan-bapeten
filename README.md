# BAPETEN — Document Extraction & Cross-check

Aplikasi internal baseline untuk membantu evaluator melakukan **ekstraksi field** dan **cross-check konsistensi antar-dokumen** pada proses evaluasi perizinan.

## Acuan field

Scope extraction mengikuti dokumen pengguna **"Identifikasi Field dan Validasi Cross-Check Dokumen Perizinan"**. Dokumen tersebut mencantumkan 16 kelompok dokumen/berkas:

1. Formulir Permohonan
2. Surat Izin Praktik (SIP)
3. Surat Perintah (Sprint)
4. SIB
5. Spesifikasi Pesawat Sinar-X
6. Surat Pengiriman/Penyerahan TLD
7. Dokumen Sistem Manajemen
8. Dokumen Program Perawatan
9. Dokumen Program Proteksi dan Keselamatan Radiasi (PPKR)
10. Foto Label Tabung
11. Foto Label Unit
12. Hasil Pengukuran Paparan Radiasi
13. Hasil Uji Fungsi
14. Persetujuan Import
15. Sertifikat Mutu
16. Uji Kesesuaian

Schema lengkap ada di `src/schema/fields.py`.

## Prinsip penting

- Dokumen yang tidak tersedia tidak dibuat-buat sebagai hasil extraction.
- Perbedaan penulisan nama/alamat dapat menghasilkan `WARNING`/`PERLU REVIEW`, bukan otomatis dianggap gagal.
- Cross-check hanya menghasilkan temuan untuk ditinjau evaluator.
- Setiap field hasil extraction menyimpan evidence dasar seperti halaman dan metode extraction bila tersedia.
- Beberapa format sumber dapat berbeda. Parser dibuat rule-based sebagai baseline; pattern perlu dikembangkan setelah contoh dokumen nyata yang bervariasi dikumpulkan.

## Jalankan

```powershell
.\\.venv\\Scripts\\Activate.ps1
python -m streamlit run app.py
```

Upload file pada kategori dokumen yang sesuai. Tidak semua kategori wajib diisi dalam satu run.

## Struktur inti

```text
src/
├── schema/
│   ├── fields.py
│   ├── evidence.py
│   ├── entities.py
│   └── matching.py
├── extraction/
│   ├── classifier.py       # Klasifikasi tipe dokumen otomatis (Batch Upload)
│   ├── document_parser.py   # Parser sentral seluruh dokumen PDF BAPETEN (termasuk PPKR)
│   ├── form_parser.py       # Parser multi-tabel formulir permohonan dinamis
│   ├── label_parser.py      # Parser foto plat label unit & tabung sinar-X
│   ├── generic_parser.py    # Ekstraksi field teks umum berbasis regex
│   ├── pdf_extractor.py     # Ekstraksi teks hybrid & selektif OCR halaman
│   └── entity_builder.py    # Konsolidasi dictionary ke Pydantic Domain Entities
├── matching/
│   ├── normalizer.py        # Normalisasi teks, nomor seri, gelar dokter, alamat
│   ├── fuzzy_matcher.py     # Fuzzy string & score evaluator
│   └── cross_check_engine.py# Engine verifikasi silang hierarkis & smart matching
├── validation/
│   └── rules.py             # Validasi kepatuhan aturan perizinan BAPETEN
├── storage/
│   └── database.py          # Penyimpanan riwayat run SQLite
└── services/
    └── run_service.py       # Pipeline orkestrasi permohonan end-to-end
```

## Batasan baseline

Field seperti `data petugas`, `data pesawat sinar-X`, dan daftar isi pada format yang sangat bervariasi belum diperlakukan sebagai struktur final universal. Untuk tahap berikutnya, parser dapat diperkuat memakai contoh dokumen nyata per jenis/varian.
