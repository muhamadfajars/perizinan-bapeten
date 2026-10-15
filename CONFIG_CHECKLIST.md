# BAPETEN Configuration & Evaluator Validation Checklist

Dokumen ini berisi daftar parameter konfigurasi teknis, aturan bisnis (*business rules*), serta daftar periksa (*checklist*) validasi bersama evaluator DPFRZR BAPETEN.

---

## ⚙️ 1. Parameter Konfigurasi Teknis (`config.py`)

| Parameter | Nilai Default | Keterangan & Tujuan | Status Validasi |
| :--- | :---: | :--- | :---: |
| `MATCH_THRESHOLD` | `90` | Ambang batas kemiripan teks untuk status **SESUAI** | ✅ Teruji |
| `REVIEW_THRESHOLD` | `60` | Batas bawah kemiripan sebelum dianggap **TIDAK SESUAI** (60–89 memicu **PERLU REVIEW**) | ✅ Teruji |
| `BRAND_FUZZY_THRESHOLD` | `80` | Toleransi kemiripan nama merk/pabrikan peralatan | ✅ Teruji |
| `ADDRESS_MATCH_THRESHOLD` | `85.0` | Ambang batas pencocokan alamat instansi fasilitas | ✅ Teruji |
| `DOC_PAGE_LIMITS['ppkr']` | `20` | Batas maksimum halaman pembacaan dokumen PPKR tebal | ✅ Teruji |
| `DOC_PAGE_LIMITS['program_perawatan']` | `18` | Batas maksimum halaman dokumen program perawatan | ✅ Teruji |
| `DOC_PAGE_LIMITS['sistem_manajemen']` | `12` | Batas maksimum halaman dokumen sistem manajemen | ✅ Teruji |

---

## 🏷️ 2. Kamus Alias & Nama Merk Peralatan

Sistem menggunakan kamus alias (`BRAND_ALIASES` dan `BRAND_FULL_NAMES`) untuk mencegah *false-negative* saat suatu dokumen mencantumkan nama pabrikan lengkap sedangkan dokumen lain menuliskan singkatannya:

- **GE**: `General Electric`, `GE Healthcare`, `GE Medical`, `General Electric Company`
- **CANON**: `Canon`, `Canon Electron Tubes & Devices Co., Ltd.`, `Toshiba/Canon`
- **UNITED IMAGING**: `UIH`, `Shanghai United Imaging Healthcare`, `United Imaging Healthcare Co., Ltd.`
- **PHILIPS**: `Philips Medical Systems`, `Philips Healthcare`
- **SIEMENS**: `Siemens Healthineers`, `Siemens AG`

> **Rekomendasi Evaluator**: Perbarui kamus ini jika terdapat merk baru dari vendor perizinan yang belum terdaftar.

---

## 📋 3. Aturan Bisnis & Logika Domain Perizinan BAPETEN (17 Berkas Aktif)

### A. Identitas Fasilitas Pemohon
- [x] **Nama Instansi**: Menoleransi variasi singkatan (*RS*, *RSUD*, *Rumkit*, *Rumah Sakit*) dan nama yayasan/badan hukum pemohon.
- [x] **Alamat Instansi**: Menoleransi perbedaan penulisan nomor, singkatan jalan (*Jl.* / *Jalan*), dan rincian kelurahan/kecamatan/provinsi.

### B. Spesifikasi Pesawat Sinar-X (Unit)
- [x] **Nomor Seri Unit**: Wajib konsisten di seluruh berkas fisik (Label Unit, Formulir, PPKR, Uji Kesesuaian, Paparan Radiasi, Uji Fungsi, Persetujuan Impor).
- [x] **Persetujuan Impor Multi-Unit**: Sistem otomatis menyeleksi baris izin impor yang sesuai dengan nama faskes pemohon dan nomor seri unit yang diajukan.

### C. Spesifikasi Tabung Sinar-X (Tube)
- [x] **Tipe/Model Tabung**: Mengacu pada *Tube Insert Model* pada plat label tabung (misal: `E7894`).
- [x] **Nomor Seri Tabung**: Mengacu pada nomor seri *insert* tabung fisik (misal: `0F1376`).
- [x] **Pemisahan Housing vs Insert**: Jika dokumen operasional atau persetujuan impor mencatat nomor seri housing sistem (misal: `20G225`), sistem memberikan status yang toleran dan tidak memicu penolakan fatal.
- [x] **Dokumen Tanpa Kolom Tabung**: Pada Surat Persetujuan Impor SRP yang tabelnya hanya memuat unit pesawat tanpa spesifikasi tabung, field tabung bernilai `-` dan diabaikan dari komparasi tabung klinis.

### D. Data Ketenagaan / Personel Radiasi
- [x] **Pemisahan Kategori**:
  1. *Data Petugas Lainnya yang Menangani SRP* (Dokter Spesialis Radiologi, Fisikawan Medik, Radiografer).
  2. *Data Petugas Proteksi Radiasi (PPR)* (Petugas tersertifikasi pemegang SIB BAPETEN).
- [x] **Normalisasi Nama**: Menghapus gelar akademik/profesi (*dr.*, *Sp.Rad*, *S.Tr.Rad*, *M.Kes*, dll) sebelum pencocokan nama antar-dokumen.
- [x] **Surat Izin Praktik (SIP)**: Lokasi praktik pada SIP dievaluasi terhadap gabungan nama instansi dan alamat instansi pemohon.
- [x] **Surat Perintah (Sprint)**: Deteksi otomatis nama petugas yang ditugaskan serta cuplikan tanda tangan pejabat penandatangan surat perintah.
- [x] **Surat Izin Bekerja (SIB)**: Verifikasi nomor SIB PPR dan validitas masa berlaku sertifikat.

---

## 🔍 4. Checklist Pengujian & Validasi Rilis Baru

Sebelum merilis penyesuaian aturan ke sistem produksi, pastikan:

1. [ ] Seluruh unit test suite lolos pengujian tanpa kegagalan:
   ```powershell
   pytest
   ```
2. [ ] Pengujian manual dilakukan pada sampel berkas permohonan nyata:
   - Sampel 1: Permohonan unit baru impor (GE / Canon / Siemens / Philips).
   - Sampel 2: Permohonan perpanjangan izin dengan variasi SIP dokter.
   - Sampel 3: Berkas dengan tanda tangan digital pada dokumen Sprint.
3. [ ] Konfirmasi hasil temuan *warning* atau *perlu review* dengan evaluator DPFRZR BAPETEN.
