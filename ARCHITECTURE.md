# System Architecture — BAPETEN Document Matching System

Dokumentasi arsitektur perangkat lunak untuk sistem ekstraksi dan verifikasi silang dokumen perizinan fasilitas radiasi BAPETEN.

---

## 🏗️ Diagram Alur Data & Komponen Sistem

```text
+-----------------------------------------------------------------------------------+
|                            STREAMLIT WEB INTERFACE (app.py)                       |
|  - Batch Upload (Unggah massal berkas permohonan)                                 |
|  - Visualisasi Parameter Card & Evaluasi Silang                                   |
|  - Tabel Komparasi Nilai Tertera vs Berkas Fisik & Nomor Halaman                  |
|  - Cuplikan Tanda Tangan Digital Sprint & Manajemen Riwayat Run                   |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                     WORKFLOW ORCHESTRATOR (src/services/run_service.py)           |
|  - Alokasi Run ID & Pengurutan Prioritas Dokumen (Formulir -> PPKR -> ... -> Impor)|
|  - Pengumpulan Konteks Berjalan (Hospital Name, Alamat, Serial Number)            |
+-----------------------------------------+-----------------------------------------+
                                          |
        +---------------------------------+---------------------------------+
        |                                                                   |
        v                                                                   v
+-----------------------------------+             +---------------------------------+
|  DOCUMENT CLASSIFIER              |             |  HYBRID EXTRACTION ENGINE       |
|  (src/extraction/classifier.py)   |             |  (src/extraction/)              |
|  - Keyword & Content Patterns     |             |  - pdf_extractor.py:            |
|  - Auto-mapping 15 Tipe Berkas    |             |    * Native PDF text/table      |
+-----------------------------------+             |    * Selektif OCR fallback      |
                                                  |  - document_parser.py           |
                                                  |  - form_parser.py (multi-tabel) |
                                                  |  - label_parser.py (OCR plat)   |
                                                  |  - signature_cropper.py (Sprint)|
                                                  +----------------+----------------+
                                                                   |
                                                                   v
+-----------------------------------------------------------------------------------+
|                  DOMAIN ENTITY BUILDER (src/extraction/entity_builder.py)         |
|  Konsolidasi dictionary hasil ekstraksi menjadi Pydantic Domain Entities:         |
|  - FacilityEntity (Nama Instansi & Alamat Faskes)                                 |
|  - XRayEquipmentEntity (Merk, Tipe, & Nomor Seri Unit)                            |
|  - XRayTubeEntity (Merk, Insert Model, & Nomor Seri Tabung)                       |
|  - PersonnelEntity (Petugas Lainnya: Radiolog, Fisikawan Medik, Radiografer)      |
|  - PPREntity (Petugas Proteksi Radiasi, No. SIB, Masa Berlaku)                    |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                   NORMALIZATION LAYER (src/matching/normalizer.py)                |
|  - normalize_serial(): Pembersihan nomor seri unit & tabung                       |
|  - normalize_personnel_name(): Penghapusan gelar profesi & variasi spasi/tanda    |
|  - normalize_facility_name(): Normalisasi singkatan RS/Rumkit/Klinik              |
|  - normalize_address(): Standarisasi hierarki jalan, kelurahan, dan kota          |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|               CROSS-CHECK ENGINE (src/matching/cross_check_engine.py)             |
|  - evaluate_field_sources(): Fuzzy ratio & token matching                         |
|  - cross_check_facility(): Verifikasi silang nama instansi & alamat               |
|  - cross_check_equipment(): Verifikasi silang unit pesawat sinar-X                |
|  - cross_check_tubes(): Verifikasi silang tabung (Merk, Insert Model, S/N)        |
|  - cross_check_personnel(): Verifikasi petugas lainnya vs SIP / Sprint            |
|  - cross_check_ppr(): Verifikasi PPR vs Surat Perintah & SIB BAPETEN              |
|  - Smart Domain Heuristics:                                                       |
|    * Multi-row table selection pada Persetujuan Impor (pencocokan RS pemohon)     |
|    * Pembedaan tube insert S/N vs housing/system S/N                              |
|    * Toleransi tempat praktik SIP (kombinasi nama RS + alamat)                    |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                 RULE VALIDATION & COMPLIANCE (src/validation/rules.py)            |
|  - Evaluasi kelengkapan dokumen wajib sesuai jenis permohonan                     |
|  - Penentuan status kepatuhan (COMPLIANT, REVIEW_NEEDED, NON_COMPLIANT)           |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                 PERSISTENCE & REPORT GENERATOR                                    |
|  - generate_cross_check_report(): Membentuk objek CrossCheckReport                |
|  - Result JSON (data/output/results/{run_id}.json)                                |
|  - SQLite Database (data/output/bapeten_matching.sqlite3)                         |
+-----------------------------------------------------------------------------------+
```

---

## 🏛️ Penjelasan Lapisan Arsitektur

### 1. Ingestion & Auto-Classification
- **Batch Ingestion**: Pengguna dapat mengunggah berkas terpisah berdasarkan kategori atau menggunakan fitur unggah massal (*Batch Upload*).
- **Content-Based Classification** (`classifier.py`): Membaca teks halaman pertama/kedua dan mencocokkan pola regex khas (*CONTENT_PATTERNS*) untuk mengklasifikasikan 15 jenis dokumen perizinan BAPETEN secara otomatis.

### 2. Hybrid Extraction & CV Engine
- **Digital First**: Memprioritaskan ekstraksi teks digital langsung dari PDF menggunakan `pdfplumber` dan `pypdfium2` untuk menjamin akurasi 100% dan kecepatan tinggi.
- **Selective OCR**: Menjalankan OCR hanya pada dokumen berbasis pemindaian/gambar (misal plat label fisik atau dokumen yang tidak memuat *text stream* digital).
- **Signature Cropper** (`signature_cropper.py`): Menggunakan segmentasi visual dan deteksi kontur untuk menemukan area tanda tangan pimpinan pada lembar pengesahan Sprint, lalu menyimpannya dalam format Base64 dan berkas citra PNG di `data/output/crops/`.

### 3. Domain Entity Consolidation
- `entity_builder.py` mengubah data ekstraksi mentah menjadi model domain yang terstruktur menggunakan Pydantic v2:
  - `FacilityEntity`: Identitas pemohon.
  - `XRayEquipmentEntity`: Spesifikasi unit pesawat sinar-X.
  - `XRayTubeEntity`: Spesifikasi tabung sinar-X.
  - `PersonnelEntity`: Petugas yang menangani radiasi (selain PPR).
  - `PPREntity`: Petugas Proteksi Radiasi.

### 4. Normalization & Matching
- Menghindari *false-negative* akibat variasi penulisan administratif tanpa mengorbankan integritas data perizinan:
  - **Serial Number**: Menghilangkan spasi, tanda hubung, dan pembeda *case-insensitive*.
  - **Nama Personel**: Menghilangkan gelar depan/belakang (*dr.*, *Sp.Rad*, *S.Tr.Rad*, *A.Md.Rad*, *M.Kes*, dll).
  - **Nama Instansi**: Menyamakan format singkatan instansi (*RS*, *RSUD*, *Rumkit*, *Rumah Sakit*).
  - **Alamat**: Menoleransi perbedaan hierarki penulisan alamat jalan vs alamat administratif lengkap.

### 5. Multi-Row & Domain Logic Persetujuan Impor
- Surat Persetujuan Impor BAPETEN sering kali memuat tabel izin impor multi-unit untuk beberapa rumah sakit yang berbeda.
- `extract_persetujuan_import_data()` menerapkan heuristik penilaian baris (*row scoring*) berdasarkan kesamaan nama faskes/kota pemohon dan nomor seri unit.
- Kolom *Tipe/No Seri* pada izin impor GE yang memuat catatan nomor seri housing dibersihkan sehingga nomor seri unit diekstraksi secara tepat, sedangkan kolom tabung diset `-` jika dokumen izin impor tersebut memang tidak memiliki kolom data tabung resmi.

### 6. Persistensi & Pelaporan
- Seluruh detail perbandingan disimpan secara terstruktur ke dalam file JSON (`data/output/results/{run_id}.json`) dan dicatat ke dalam database SQLite (`bapeten_matching.sqlite3`).
- Streamlit UI menampilkan data tersebut dalam bentuk *parameter cards* dengan badge status interaktif (`SESUAI`, `PERLU REVIEW`, `TIDAK SESUAI`, `TIDAK DITEMUKAN`).
