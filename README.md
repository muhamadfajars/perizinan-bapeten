# BAPETEN — Document Extraction & Cross-Check System

Sistem cerdas untuk membantu evaluator BAPETEN melakukan **klasifikasi otomatis**, **ekstraksi data teknis/administratif**, dan **verifikasi silang (cross-check) konsistensi antar-dokumen** pada proses evaluasi perizinan pemanfaatan tenaga nuklir (pesawat sinar-X diagnostik dan intervensional).

---

## 📋 Cakupan Dokumen (15 Berkas Aktif)

Sistem mengidentifikasi dan memverifikasi silang 15 kelompok dokumen perizinan:

1. **Formulir Permohonan** (Data instansi, unit, tabung, personel & PPR)
2. **Surat Izin Praktik (SIP)** (Kualifikasi dokter spesialis radiologi & lokasi praktik)
3. **Surat Perintah (Sprint)** (Penugasan personel dan bukti tanda tangan pimpinan)
4. **Surat Izin Bekerja (SIB)** (Sertifikasi PPR aktif BAPETEN)
5. **Spesifikasi Pesawat Sinar-X** (Brosur / dokumen teknis pabrikan)
6. **Surat Pengiriman/Penyerahan TLD** (Pemantauan dosis radiasi personel)
7. **Dokumen Sistem Manajemen** (Struktur kendali mutu & keselamatan)
8. **Dokumen Program Perawatan** (Jadwal & prosedur maintenance unit)
9. **Dokumen Program Proteksi & Keselamatan Radiasi (PPKR)**
10. **Foto Label Tabung** (Plat fisik tabung sinar-X: Merk, Insert Model, S/N)
11. **Foto Label Unit** (Plat fisik unit pesawat: Merk, Tipe, S/N)
12. **Hasil Pengukuran Paparan Radiasi** (Uji kebocoran dan laju paparan)
13. **Hasil Uji Fungsi** (Pengujian operasional peralatan)
14. **Persetujuan Impor** (Izin impor SRP BAPETEN multi-unit)
15. **Uji Kesesuaian** (Sertifikat kelayakan operasi pesawat sinar-X)

---

## ✨ Fitur Unggulan

- ⚡ **Batch Upload & Auto-Classification**: Evaluator dapat mengunggah berkas secara massal; sistem secara otomatis mengenali jenis berkas berdasarkan kata kunci dan pola konten (`classifier.py`).
- 🔍 **Ekstraksi Hybrid & Multi-Engine**: Kombinasi teks digital presisi tinggi (PDF text & tabular extractor via `pdfplumber`/`pypdfium2`) dengan OCR cerdas (*image preprocessing* & engine OCR).
- ✍️ **Deteksi & Crop Tanda Tangan Digital**: Otomatis mendeteksi, memotong (*crop*), dan menampilkan cuplikan tanda tangan pejabat pengesahan pada berkas Surat Perintah (Sprint).
- 👥 **Pemisahan Kategori Personel Radiasi**: Memisahkan secara terstruktur antara *Data Petugas Lainnya yang Menangani SRP* (Dokter Spesialis Radiologi, Fisikawan Medik, Radiografer) dengan *Data Petugas Proteksi Radiasi (PPR)* beserta nomor SIB dan masa berlakunya.
- 🎯 **Smart Cross-Check & Heuristik Domain**:
  - Pencocokan multi-baris (*multi-row matching*) pada Persetujuan Impor berdasarkan rumah sakit pemohon dan nomor seri unit.
  - Toleransi cerdas variasi penulisan nama fasilitas, singkatan rumah sakit (RS / Rumkit), serta hierarki alamat.
  - Normalisasi gelar akademik/profesi (*dr.*, *Sp.Rad*, *S.Tr.Rad*).
  - Pembedaan akurat antara nomor seri *tube insert* fisik dengan nomor seri *housing/system*.
- 📊 **UI Interaktif & Manajemen Riwayat**: Antarmuka visual Streamlit dengan kartu status parameter (*Sesuai*, *Perlu Review*, *Tidak Sesuai*), rincian berkas sumber, serta riwayat evaluasi tersimpan di SQLite (`bapeten_matching.sqlite3`).

---

## 🚀 Panduan Instalasi & Menjalankan

### 1. Prasyarat
- Python 3.10 atau lebih baru (disarankan Python 3.12)
- PowerShell (Windows) atau Terminal Bash

### 2. Setup Virtual Environment & Dependensi
```powershell
# Buat dan aktifkan virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instal dependensi
pip install -r requirements.txt
```

### 3. Menjalankan Aplikasi
```powershell
python -m streamlit run app.py
```
Akses aplikasi melalui browser di `http://localhost:8501`.

---

## 🧪 Pengujian (Unit Tests)

Sistem dilengkapi dengan 80 pengujian otomatis (*unit tests*) untuk memastikan akurasi ekstraksi dan verifikasi silang:

```powershell
pytest
```

---

## 📁 Struktur Direktori

```text
bapeten_document_matching_system/
├── app.py                      # Antarmuka web utama (Streamlit UI)
├── config.py                   # Konfigurasi threshold, path direktori, dan alias merk
├── requirements.txt            # Daftar dependensi Python
├── pytest.ini                  # Konfigurasi test suite pytest
├── data/
│   ├── input/                  # Folder dokumen input & label
│   └── output/                 # Hasil run, crop tanda tangan, dan database SQLite
├── src/
│   ├── schema/                 # Definisi skema Pydantic, field, dan domain entities
│   │   ├── fields.py           # Definisi daftar 15 dokumen dan field acuan
│   │   ├── entities.py         # Pydantic Domain Entities (Fasilitas, Unit, Tabung, Personel, PPR)
│   │   ├── evidence.py         # Skema SourceEvidence dan pembuktian berkas fisik
│   │   └── matching.py         # Skema CrossCheckReport, MatchingStatus, EntityCrossCheck
│   ├── extraction/             # Modul ekstraksi dokumen & parser
│   │   ├── classifier.py       # Klasifikasi tipe dokumen otomatis (Batch Upload)
│   │   ├── document_parser.py  # Parser sentral dokumen PDF BAPETEN
│   │   ├── form_parser.py      # Parser formulir permohonan dinamis
│   │   ├── label_parser.py     # Parser plat label fisik unit & tabung
│   │   ├── pdf_extractor.py    # Ekstraktor teks & tabel PDF hybrid
│   │   ├── signature_cropper.py# Deteksi dan crop tanda tangan dokumen Sprint
│   │   └── entity_builder.py   # Konsolidasi dictionary hasil ekstraksi ke Domain Entities
│   ├── matching/               # Mesin verifikasi silang (Cross-Check Engine)
│   │   ├── normalizer.py       # Normalisasi teks, nomor seri, gelar profesi, dan alamat
│   │   ├── fuzzy_matcher.py    # Fuzzy string matching & evaluator kemiripan
│   │   └── cross_check_engine.py # Evaluator cross-check hierarkis & heuristik domain
│   ├── ocr/                    # Preprocessing citra & OCR engine
│   │   ├── preprocess.py       # Peningkatan kontras & binarisasi citra label
│   │   └── engine.py           # Eksekusi OCR teks plat label
│   ├── validation/             # Rule engine validasi kepatuhan perizinan BAPETEN
│   │   └── rules.py            # Evaluasi kelengkapan dokumen & kepatuhan izin
│   └── services/               # Pipeline orkestrasi permohonan end-to-end
│       └── run_service.py      # Orkestrasi alur pemrosesan berkas hingga pelaporan
└── tests/                      # Suite pengujian otomatis (pytest: 80 test cases)
```

---

## 📌 Catatan Evaluator

- **Bantuan Keputusan (Bukan Pengganti Evaluator)**: Sistem dirancang sebagai alat bantu penapisan otomatis (*screening tool*). Status otomatis membantu menandai perbedaan nilai antar-dokumen, dan keputusan akhir tetap berada pada evaluator perizinan BAPETEN.
- **Toleransi Penulisan**: Sistem menerapkan ambang batas kemiripan (*similarity threshold*) sehingga variasi penulisan minor (seperti singkatan nama jalan atau variasi tipe/model) akan diklasifikasikan sebagai `PERLU REVIEW` atau `SESUAI` dengan penjelasan transparan pada kartu parameter.
