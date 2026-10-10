from pathlib import Path
import json
import re
import tempfile

import pandas as pd
import streamlit as st

from config import DB_PATH, DOCUMENT_TYPES, DOCUMENT_FIELDS, FIELD_DEFINITIONS
from src.pipeline import execute_run
from src.storage.database import Database
from src.extraction.classifier import classify_document
from src.matching.normalizer import normalize_person_name
from src.extraction.signature_cropper import get_sprint_signature_preview
from rapidfuzz import fuzz

st.set_page_config(page_title="BAPETEN Document Cross-check", layout="wide")
st.title("BAPETEN — Document Extraction & Cross-check")
st.caption("Ekstraksi field dan validasi konsistensi antar-dokumen untuk membantu evaluator. Sistem tidak mengambil keputusan izin. (Engine v2.3 - Auto-Classification Batch Upload & Smart Matching)")

db = Database(DB_PATH)
past_runs = db.list_runs(limit=25)
run_lookup = {r[0]: f"{r[0]} ({r[1]} - {r[2]} berkas)" for r in past_runs}

# Auto-restore latest run from database on page load/refresh
if past_runs:
    try:
        newest_run = db.get_run(past_runs[0][0])
        if "latest_result" not in st.session_state:
            st.session_state["latest_result"] = newest_run
        elif st.session_state.get("latest_result", {}).get("run_id") == past_runs[0][0]:
            st.session_state["latest_result"] = newest_run
    except Exception:
        pass


@st.cache_data(show_spinner=False)
def _cached_classify_document(filename: str, file_size: int, head_bytes: bytes, file_bytes: bytes):
    return classify_document(filename, file_bytes)


def save_uploaded(uploaded_file, directory, doc_type, index):
    suffix = Path(uploaded_file.name).suffix.lower()
    path = directory / f"{doc_type}_{index}{suffix}"
    path.write_bytes(uploaded_file.getbuffer())
    return path


with st.sidebar:
    if past_runs:
        st.subheader("📜 Riwayat Hasil Run")
        run_ids = [r[0] for r in past_runs]
        current_active_id = st.session_state.get("latest_result", {}).get("run_id")
        current_idx = run_ids.index(current_active_id) if current_active_id in run_ids else 0
        selected_run_id = st.selectbox(
            "Tampilkan Run Tersimpan:",
            options=run_ids,
            index=current_idx,
            format_func=lambda rid: run_lookup.get(rid, rid),
            key="history_run_dropdown",
            help="Pilih hasil analisis sebelumnya untuk dilihat kembali tanpa perlu mengunggah ulang berkas.",
        )
        if current_active_id != selected_run_id:
            loaded_run = db.get_run(selected_run_id)
            if loaded_run:
                st.session_state["latest_result"] = loaded_run
                st.rerun()
        if st.button("🔄 Muat Ulang Hasil Run", use_container_width=True):
            loaded_run = db.get_run(selected_run_id)
            if loaded_run:
                st.session_state["latest_result"] = loaded_run
                st.rerun()
        st.markdown("---")

    st.header("Input Dokumen")
    upload_mode = st.radio(
        "Mode Unggah",
        ["⚡ Unggah Sekaligus (Batch)", "📁 Unggah Per Dokumen (Manual)"],
        index=0,
        help="Mode Unggah Sekaligus memungkinkan Anda memilih/menyeret seluruh berkas permohonan dalam 1 kali klik.",
    )

    upload_map = {k: [] for k in DOCUMENT_TYPES}
    doc_names = {k: v["name"] for k, v in DOCUMENT_TYPES.items()}
    doc_keys = list(DOCUMENT_TYPES.keys())

    if upload_mode == "⚡ Unggah Sekaligus (Batch)":
        st.caption("Pilih atau seret seluruh berkas permohonan (PDF & foto plat label) sekaligus.")
        batch_files = st.file_uploader(
            "Unggah Semua Berkas Permohonan",
            type=["pdf", "jpg", "jpeg", "png", "bmp", "webp"],
            accept_multiple_files=True,
            key="batch_uploader",
        )
        if batch_files:
            st.markdown(f"**{len(batch_files)} berkas terpilih:**")
            for idx, file in enumerate(batch_files):
                # Read bytes for content classification (PDF headers or image plates)
                file_bytes = file.getvalue()
                detected_type, reason = _cached_classify_document(file.name, file.size, file_bytes[:512], file_bytes)
                default_idx = doc_keys.index(detected_type) if detected_type in doc_keys else 0

                is_confident = reason != "Default"
                icon = "✅" if is_confident else "⚠️"
                with st.expander(f"{icon} {file.name} ➔ {doc_names[detected_type]}", expanded=not is_confident):
                    st.caption(f"Metode deteksi: **{reason}**")
                    chosen_types = st.multiselect(
                        "Kategori Dokumen (Bisa pilih lebih dari satu):",
                        options=doc_keys,
                        default=[detected_type] if detected_type in doc_keys else [],
                        format_func=lambda k: doc_names[k],
                        key=f"batch_sel_{idx}_{file.name}",
                    )
                for ct in chosen_types:
                    upload_map[ct].append(file)

            active_categories = sum(1 for v in upload_map.values() if v)
            st.info(f"📋 **{active_categories} dari {len(DOCUMENT_TYPES)}** kategori dokumen teridentifikasi.")
    else:
        st.caption("Upload berkas secara spesifik pada masing-masing kategori dokumen.")
        for doc_type, meta in DOCUMENT_TYPES.items():
            extensions = ["pdf"] if meta["kind"] == "pdf" else ["jpg", "jpeg", "png", "bmp", "webp", "pdf"]
            label = meta["name"]
            uploaded = st.file_uploader(
                label,
                type=extensions,
                accept_multiple_files=True,
                key=f"uploader_{doc_type}",
            )
            if uploaded:
                upload_map[doc_type].extend(uploaded)

    run_button = st.button("Proses Extraction + Cross-check", type="primary", use_container_width=True)

if run_button:
    uploaded_any = any(upload_map.values())
    if not uploaded_any:
        st.error("Belum ada dokumen yang diunggah.")
        st.stop()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_dir = Path(temp_dir)
        inputs = {}
        file_display = {}
        for doc_type, files in upload_map.items():
            if not files:
                continue
            paths = []
            for idx, uploaded in enumerate(files, start=1):
                path = save_uploaded(uploaded, temp_dir, doc_type, idx)
                paths.append(path)
            inputs[doc_type] = paths
            file_display[doc_type] = [f.name for f in files]

        try:
            status_container = st.status("Memulai proses ekstraksi...", expanded=True)
            progress_bar = st.progress(0)
            
            def progress_callback(doc_type, filename, current, total):
                percentage = int((current / total) * 100) if total > 0 else 100
                progress_bar.progress(percentage)
                status_container.update(label=f"Memproses {current}/{total}: {filename} ({DOCUMENT_TYPES.get(doc_type, {}).get('name', doc_type)})")
                
            with status_container:
                st.write("Sedang membaca PDF, menjalankan OCR, melakukan extraction dan cross-check...")
                result = execute_run(inputs, on_progress=progress_callback)
                status_container.update(label="Proses selesai", state="complete", expanded=False)
                
            result["file_display"] = file_display
            db.save_run_generic(result)
            st.session_state["latest_result"] = result
            st.success(f"Proses selesai. Run ID: {result['run_id']}")
        except Exception as exc:
            st.exception(exc)

def _clean_status_str(status):
    """Normalize status to a clean string: e.g. MatchingStatus.SESUAI -> 'SESUAI'."""
    if hasattr(status, "value"):
        s = str(status.value)
    else:
        s = str(status or "")
    s = s.upper().strip()
    if "." in s:
        s = s.split(".")[-1].strip()
    return s


def _status_emoji(status):
    clean = _clean_status_str(status)
    if clean == "SESUAI":
        return "✅"
    if clean in {"PERLU REVIEW", "WARNING"}:
        return "🟡"
    if clean == "TIDAK SESUAI":
        return "❌"
    if clean == "TIDAK DITEMUKAN":
        return "⚪"
    return "ℹ️"


def render_field_comparison(fields, section_key):
    """Render a horizontal matrix: one row per field and one column per source document."""
    if not fields:
        st.info("Belum ada field yang dapat dibandingkan pada bagian ini.")
        return

    status_options = ["Semua status", "TIDAK SESUAI", "PERLU REVIEW", "WARNING", "TIDAK DITEMUKAN", "SESUAI"]
    selected_status = st.selectbox(
        "Filter hasil",
        status_options,
        key=f"filter_{section_key}",
        help="Pilih status untuk memusatkan perhatian pada perbedaan atau data yang perlu diperiksa manual.",
    )
    ordered_fields = list(fields.items())
    if selected_status != "Semua status":
        ordered_fields = [(k, v) for k, v in ordered_fields if _clean_status_str(v.get("status", "")) == selected_status]

    if not ordered_fields:
        st.success("Tidak ada field dengan status yang dipilih.")
        return

    # Build a union of source columns so values from different documents are compared
    # horizontally on the same row. Group by (document_type, filename) so that multiple
    # fields from different pages of the same document appear in the same column.
    unique_columns = []
    seen_identities = set()
    col_label_counts = {}

    for field_key, field in ordered_fields:
        for source in (field.get("sources", []) or []):
            doc_type = source.get("document_type", "Dokumen")
            doc_label = DOCUMENT_TYPES.get(
                doc_type, {}
            ).get("name", str(doc_type).replace("_", " ").title())
            file_name = source.get("file_name") or source.get("document_name")
            identity = (doc_type, str(file_name or ""))
            if identity not in seen_identities:
                seen_identities.add(identity)
                base_label = f"{doc_label} · {file_name}" if file_name else doc_label
                if base_label in col_label_counts:
                    col_label_counts[base_label] += 1
                    col_label = f"{base_label} ({col_label_counts[base_label]})"
                else:
                    col_label_counts[base_label] = 1
                    col_label = base_label
                unique_columns.append((col_label, identity))

    matrix_rows = []
    details = []
    for field_key, field in ordered_fields:
        label = field.get("field_label") or field_key.replace("_", " ").title()
        if field_key == "project_name" and label in {"Nama proyek", "Project Name"}:
            label = "Nama instansi"
        elif field_key == "project_address" and label in {"Alamat proyek", "Project Address"}:
            label = "Alamat instansi"
        status = _clean_status_str(field.get("status") or "BELUM DINILAI")
        score = field.get("score")
        row = {
            "Field yang dibandingkan": label,
            "Status": f"{_status_emoji(status)} {status}",
            "Skor": f"{score:.1f}/100" if isinstance(score, (int, float)) else "—",
        }
        source_values = {}
        for source in (field.get("sources", []) or []):
            doc_type = source.get("document_type", "Dokumen")
            file_name = str(source.get("file_name") or source.get("document_name") or "")
            identity = (doc_type, file_name)
            value = source.get("value")
            display_value = str(value).strip() if value is not None and str(value).strip() else "— Tidak ditemukan —"
            if identity in source_values:
                if source_values[identity] in {"— Tidak ditemukan —", "—"}:
                    source_values[identity] = display_value
                elif display_value not in {"— Tidak ditemukan —", "—"} and display_value not in source_values[identity]:
                    source_values[identity] += f" | {display_value}"
            else:
                source_values[identity] = display_value
        for col_label, identity in unique_columns:
            row[col_label] = source_values.get(identity, "—")
        matrix_rows.append(row)
        details.append((label, field, status, score))

    st.caption("Perbandingan dibaca dari kiri ke kanan: setiap baris adalah satu field, sedangkan setiap kolom setelah Status/Skor adalah dokumen sumber. Geser tabel secara horizontal untuk melihat dokumen di sebelah kanan.")
    st.dataframe(
        pd.DataFrame(matrix_rows),
        use_container_width=True,
        hide_index=True,
        height=min(560, 42 * (len(matrix_rows) + 1) + 8),
        column_config={
            "Field yang dibandingkan": st.column_config.TextColumn("Field yang dibandingkan", width="medium"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
            "Skor": st.column_config.TextColumn("Skor kemiripan", width="small"),
        },
    )

    # Keep explanations and discrepancy evidence available without cluttering the matrix.
    with st.expander("Lihat penjelasan status dan detail perbedaan", expanded=False):
        for label, field, status, score in details:
            clean_s = _clean_status_str(status)
            st.markdown(f"**{_status_emoji(clean_s)} {label} — {clean_s}**")
            if isinstance(score, (int, float)):
                st.caption(f"Skor kemiripan: {score:.1f}/100")
            reason = field.get("reason")
            if reason:
                st.write(f"Penjelasan: {reason}")
            discrepancies = field.get("discrepancies", []) or []
            if discrepancies:
                st.error("Perbedaan yang terdeteksi: " + "; ".join(str(x) for x in discrepancies))
            if not field.get("sources"):
                st.warning("Tidak ada bukti sumber yang tersedia untuk field ini.")
            st.divider()


result = st.session_state.get("latest_result")
if result:
    st.header("Hasil")

    summary = result.get("summary", {})
    status_order = ["SESUAI", "WARNING", "PERLU REVIEW", "TIDAK SESUAI", "TIDAK DITEMUKAN"]
    cols = st.columns(len(status_order))
    for col, status in zip(cols, status_order):
        key = status.lower().replace(" ", "_")
        count = summary.get(status, summary.get(key, 0))
        col.metric(status, count)

    # 1. Compliance and Validation Report
    compliance = result.get("compliance")
    if compliance:
        st.subheader("1. Evaluasi Aturan & Kepatuhan Perizinan BAPETEN")
        if compliance.get("is_compliant"):
            st.success("Permohonan memenuhi persyaratan dasar perizinan (Tidak ada temuan kritis).")
        else:
            st.error(f"Ditemukan {compliance.get('critical_count', 0)} temuan kritis yang harus diperbaiki pemohon.")

        issues = compliance.get("issues", [])
        if issues:
            issues_df = pd.DataFrame(issues)
            visible_cols = [c for c in ["severity", "category", "rule_name", "description", "recommendation"] if c in issues_df.columns]
            st.dataframe(issues_df[visible_cols], use_container_width=True, hide_index=True)

    # 2. Hierarchical Cross-Check Report
    report = result.get("cross_check_report")
    if report:
        st.subheader("2. Perbandingan Antar-Dokumen")
        st.caption("Baca setiap field dari kiri ke kanan untuk membandingkan nilai yang ditemukan di dokumen sumber. Status otomatis adalah alat bantu; pastikan temuan penting diverifikasi terhadap dokumen asli.")

        # 1. Identitas Fasilitas
        fac = report.get("facility")
        if fac:
            st.markdown("### 🏢 1. Identitas Fasilitas")
            fac_fields = fac.get("fields", {})
            st.caption("Bandingkan nilai dari setiap dokumen. Perbedaan dan data yang belum ditemukan ditandai agar mudah ditinjau.")
            render_field_comparison(fac_fields, "facility")

            # Detailed tree breakdown of source documents for Nama instansi
            p_name_sources = fac_fields.get("project_name", {}).get("sources", [])
            with st.expander("🔍 Rincian Lintas Dokumen: Nama Instansi (Formulir, Sprint, TLD, PPKR, dll)", expanded=False):
                doc_order = [
                    ("formulir", "Formulir"),
                    ("sprint", "Sprint"),
                    ("tld", "TLD"),
                    ("sistem_manajemen", "Sistem Manajemen"),
                    ("program_perawatan", "Program Perawatan"),
                    ("ppkr", "PPKR"),
                    ("paparan_radiasi", "Hasil Pengukuran"),
                    ("uji_fungsi", "Hasil Uji Fungsi"),
                    ("uji_kesesuaian", "Uji Kesesuaian"),
                ]
                tree_rows = []
                src_map = {s.get("document_type"): s for s in p_name_sources}
                uploaded_doc_map = result.get("documents", {})
                for d_key, d_label in doc_order:
                    s_item = src_map.get(d_key)
                    uploaded_files = uploaded_doc_map.get(d_key, [])
                    is_uploaded = bool(uploaded_files)

                    if is_uploaded:
                        status_berkas = "✅ Diunggah"
                        file_name = uploaded_files[0] if uploaded_files else "-"
                        if s_item and s_item.get("value"):
                            status_ekstraksi = "✅ Ditemukan"
                            val_text = s_item.get("value")
                            page_text = str(s_item.get("page") or "-")
                        else:
                            status_ekstraksi = "⚠️ Belum Terdeteksi di Teks"
                            val_text = "(Nama instansi belum terdeteksi pada teks)"
                            page_text = "-"
                    else:
                        status_berkas = "⚪ Tidak Diunggah"
                        status_ekstraksi = "-"
                        file_name = "-"
                        val_text = "-"
                        page_text = "-"

                    tree_rows.append({
                        "Dokumen": d_label,
                        "Status Berkas": status_berkas,
                        "Status Ekstraksi": status_ekstraksi,
                        "Nilai Ekstraksi Nama Instansi": val_text,
                        "File Sumber": file_name,
                        "Halaman": page_text,
                    })
                st.dataframe(pd.DataFrame(tree_rows), use_container_width=True, hide_index=True)

            # Detailed tree breakdown of source documents for Alamat instansi
            p_addr_sources = fac_fields.get("project_address", {}).get("sources", [])
            with st.expander("🔍 Rincian Lintas Dokumen: Alamat Instansi (Formulir, Sprint, TLD, PPKR, dll)", expanded=False):
                tree_addr_rows = []
                src_addr_map = {s.get("document_type"): s for s in p_addr_sources}
                for d_key, d_label in doc_order:
                    s_item = src_addr_map.get(d_key)
                    uploaded_files = uploaded_doc_map.get(d_key, [])
                    is_uploaded = bool(uploaded_files)

                    if is_uploaded:
                        status_berkas = "✅ Diunggah"
                        file_name = uploaded_files[0] if uploaded_files else "-"
                        if s_item and s_item.get("value"):
                            status_ekstraksi = "✅ Ditemukan"
                            val_text = s_item.get("value")
                            page_text = str(s_item.get("page") or "-")
                        else:
                            status_ekstraksi = "⚠️ Belum Terdeteksi di Teks"
                            val_text = "(Alamat instansi belum terdeteksi pada teks)"
                            page_text = "-"
                    else:
                        status_berkas = "⚪ Tidak Diunggah"
                        status_ekstraksi = "-"
                        file_name = "-"
                        val_text = "-"
                        page_text = "-"

                    tree_addr_rows.append({
                        "Dokumen": d_label,
                        "Status Berkas": status_berkas,
                        "Status Ekstraksi": status_ekstraksi,
                        "Nilai Ekstraksi Alamat Instansi": val_text,
                        "File Sumber": file_name,
                        "Halaman": page_text,
                    })
                st.dataframe(pd.DataFrame(tree_addr_rows), use_container_width=True, hide_index=True)

        # 2. Personel
        personnel = report.get("personnel", [])
        ppr_rep_list = report.get("ppr", [])
        sprint_docs_all = result.get("extractions", {}).get("sprint", [])
        sib_docs_all = result.get("extractions", {}).get("sib", [])

        if personnel or ppr_rep_list or sprint_docs_all or sib_docs_all:
            st.markdown("### 👨‍⚕️ 2. Personel")
            st.caption(
                "Pemeriksaan data personel dibagi menjadi 2 kelompok berdasarkan formulir permohonan BAPETEN: "
                "1) Data Petugas Lainnya yang Menangani Sumber Radiasi Pengion (memerlukan SIP), dan "
                "2) Data Petugas Proteksi Radiasi / PPR (memerlukan SIB & Surat Perintah)."
            )

            def _is_ppr_person(p_dict):
                lbl = str(p_dict.get('entity_label') or "").upper()
                if "PPR" in lbl or "PROTEKSI" in lbl:
                    return True
                p_flds = p_dict.get("fields", {})
                prof_srcs = p_flds.get("profession", {}).get("sources", [])
                for s in prof_srcs:
                    s_val = str(s.get("value") or "").upper()
                    if "PPR" in s_val or "PROTEKSI" in s_val:
                        return True
                for f_key in ["ppr_name", "profession"]:
                    for s in p_flds.get(f_key, {}).get("sources", []):
                        if s.get("document_type") in {"sib", "sprint"}:
                            return True
                return False

            def _extract_person_clean_name(p_dict):
                p_flds = p_dict.get("fields", {})
                for k in ["ppr_name", "person_name"]:
                    if k in p_flds:
                        for s in p_flds[k].get("sources", []):
                            val = str(s.get("value") or "").strip()
                            if val:
                                norm = normalize_person_name(val)
                                if norm:
                                    return norm
                lbl = str(p_dict.get('entity_label') or "")
                lbl_clean = re.sub(r'^(?:Personel|PPR)\s*#\d+\s*:\s*', '', lbl, flags=re.I)
                lbl_clean = re.sub(r'\s*\([^)]*\)$', '', lbl_clean)
                return normalize_person_name(lbl_clean)

            other_personnel = [p for p in personnel if not _is_ppr_person(p)]

            # Kumpulkan kandidat PPR dari personnel dan report['ppr'], lalu dedup ketat berdasarkan nama orang
            raw_ppr_candidates = [p for p in personnel if _is_ppr_person(p)] + ppr_rep_list
            ppr_personnel = []
            seen_ppr_names = set()

            for p in raw_ppr_candidates:
                clean_name = _extract_person_clean_name(p)
                is_duplicate = False
                for seen_name in seen_ppr_names:
                    if clean_name == seen_name or (clean_name and seen_name and fuzz.token_sort_ratio(clean_name, seen_name) >= 75):
                        is_duplicate = True
                        break
                if not is_duplicate and clean_name:
                    ppr_personnel.append(p)
                    seen_ppr_names.add(clean_name)

            # -------------------------------------------------------------
            # Sub-bagian 1: Data Petugas Lainnya yang Menangani Sumber Radiasi Pengion
            # -------------------------------------------------------------
            st.markdown("#### 1. Data Petugas Lainnya yang Menangani Sumber Radiasi Pengion")
            st.caption(
                "Mencakup Dokter Spesialis Radiologi, Radiografer, Fisikawan Medik, atau staf penanganan radiasi lainnya. "
                "Tabel perbandingan memeriksa kesesuaian Nama & Profesi. Rincian dokumen izin SIP (Masa berlaku & Alamat praktik) "
                "ditampilkan mandiri tanpa digabung ke tabel perbandingan."
            )

            if other_personnel:
                for idx, p in enumerate(other_personnel, start=1):
                    p_label = p.get('entity_label') or f"Petugas #{idx}"
                    p_status = _clean_status_str(p.get('status') or "SESUAI")
                    p_fields = p.get("fields", {})

                    with st.expander(f"{p_label} — Status: {p_status}", expanded=(idx == 1)):
                        # A. Tabel Perbandingan Lintas Dokumen: Khusus Nama & Profesi
                        table_fields = {
                            k: v for k, v in p_fields.items()
                            if k in ["person_name", "profession"]
                        }
                        if table_fields:
                            render_field_comparison(table_fields, f"other_personnel_{idx}")

                        # B. Rincian Khusus Dokumen Izin: Surat Izin Praktik (SIP)
                        norm_target = normalize_person_name(p_label)
                        sip_sources = [
                            s for s in (p_fields.get("practice_location", {}).get("sources", []) +
                                       p_fields.get("valid_until", {}).get("sources", []))
                            if s.get("document_type") == "sip"
                        ]
                        matched_sip_doc = None
                        for doc in result.get("extractions", {}).get("sip", []):
                            f = doc.get("fields", {})
                            s_name = f.get("person_name", {}).get("value", "")
                            if s_name and (fuzz.token_sort_ratio(normalize_person_name(s_name), norm_target) >= 70 or
                                           normalize_person_name(s_name) in norm_target):
                                matched_sip_doc = doc
                                break

                        has_sip = bool(sip_sources or matched_sip_doc)
                        if has_sip:
                            st.markdown("##### 📄 Rincian Khusus Dokumen: Surat Izin Praktik (SIP)")
                            st.caption("Khusus dokumen SIP. Masa berlaku dan alamat praktik ditampilkan mandiri tanpa digabung ke tabel perbandingan.")
                            sip_f = matched_sip_doc.get("fields", {}) if matched_sip_doc else {}
                            sip_valid = (
                                p_fields.get("valid_until", {}).get("sources", [{}])[0].get("value")
                                if sip_sources else sip_f.get("valid_until", {}).get("value")
                            ) or "— Tidak ditemukan —"
                            sip_addr = (
                                p_fields.get("practice_location", {}).get("sources", [{}])[0].get("value")
                                if sip_sources else sip_f.get("practice_location", {}).get("value")
                            ) or "— Tidak ditemukan —"
                            sip_file = (
                                matched_sip_doc.get("file_name") if matched_sip_doc
                                else (sip_sources[0].get("document_name") if sip_sources else "-")
                            )

                            with st.container(border=True):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.markdown(f"**📅 Masa Berlaku SIP:** `{sip_valid}`")
                                    st.markdown(f"**📁 File Sumber:** `{sip_file}`")
                                with c2:
                                    st.markdown(f"**🏥 Alamat Praktik:** `{sip_addr}`")
                                    loc_reason = p_fields.get("practice_location", {}).get("reason")
                                    if loc_reason:
                                        st.caption(f"Status Lokasi: {loc_reason}")
                        else:
                            st.caption("ℹ️ Dokumen Surat Izin Praktik (SIP) tidak ditemukan atau belum terpetakan untuk personel ini.")
            else:
                st.info("Data Petugas Lainnya yang Menangani Sumber Radiasi Pengion tidak ditemukan pada formulir permohonan.")

            # -------------------------------------------------------------
            # Sub-bagian 2: Data Petugas Proteksi Radiasi (PPR)
            # -------------------------------------------------------------
            st.markdown("---")
            st.markdown("#### 2. Data Petugas Proteksi Radiasi (PPR)")
            st.caption(
                "Petugas Proteksi Radiasi (PPR) yang ditunjuk instansi. Dokumen perizinan yang dipersyaratkan adalah "
                "Surat Izin Bekerja (SIB) BAPETEN dan Surat Perintah (Sprint) Penunjukan PPR. "
                "Rincian masa berlaku SIB serta Kepada, Pengesahan, dan crop tanda tangan & stempel fisik ditampilkan mandiri."
            )

            rendered_sprint_indices = set()
            rendered_sib_indices = set()
            sprint_docs = result.get("extractions", {}).get("sprint", [])
            sib_docs = result.get("extractions", {}).get("sib", [])

            if ppr_personnel:
                for idx, p in enumerate(ppr_personnel, start=1):
                    raw_lbl = p.get('entity_label') or f"PPR #{idx}"
                    p_label = re.sub(r'^(?:Personel|PPR)\s*#\d+\s*:\s*', f'PPR #{idx}: ', raw_lbl)
                    if not re.match(r'^PPR\s*#\d+:', p_label, flags=re.I):
                        p_label = f"PPR #{idx}: {p_label}"

                    p_status = _clean_status_str(p.get('status') or "SESUAI")
                    p_fields = p.get("fields", {})

                    with st.expander(f"{p_label} — Status: {p_status}", expanded=True):
                        # A. Tabel Perbandingan Lintas Dokumen: Nama PPR & Profesi
                        table_fields = {}
                        if "ppr_name" in p_fields and p_fields["ppr_name"].get("sources"):
                            table_fields["ppr_name"] = p_fields["ppr_name"]
                        elif "person_name" in p_fields:
                            table_fields["person_name"] = p_fields["person_name"]
                        if "profession" in p_fields and p_fields["profession"].get("sources"):
                            table_fields["profession"] = p_fields["profession"]

                        if table_fields:
                            render_field_comparison(table_fields, f"ppr_personnel_{idx}")

                        # B. Rincian Khusus Dokumen Izin SIB & Surat Perintah
                        clean_target_name = _extract_person_clean_name(p)
                        norm_target = normalize_person_name(clean_target_name or p_label)

                        # 1. Dokumen SIB (Surat Izin Bekerja)
                        sib_sources = [
                            s for s in p_fields.get("valid_until", {}).get("sources", [])
                            if s.get("document_type") == "sib"
                        ]
                        matched_sib_idx = None
                        matched_sib_doc = None
                        for s_i, doc in enumerate(sib_docs):
                            f = doc.get("fields", {})
                            s_name = f.get("ppr_name", {}).get("value", "") or f.get("person_name", {}).get("value", "")
                            if s_name and (fuzz.token_sort_ratio(normalize_person_name(s_name), norm_target) >= 70 or
                                           normalize_person_name(s_name) in norm_target or
                                           norm_target in normalize_person_name(s_name)):
                                matched_sib_doc = doc
                                matched_sib_idx = s_i
                                break

                        if matched_sib_doc is None and len(sib_docs) == 1 and len(ppr_personnel) == 1:
                            matched_sib_doc = sib_docs[0]
                            matched_sib_idx = 0

                        has_sib = bool(sib_sources or matched_sib_doc)
                        if has_sib:
                            if matched_sib_idx is not None:
                                rendered_sib_indices.add(matched_sib_idx)

                            st.markdown("##### 📄 Rincian Khusus Dokumen: Surat Izin Bekerja (SIB)")
                            st.caption("Khusus dokumen SIB BAPETEN. Masa berlaku ditampilkan mandiri tanpa digabung ke tabel perbandingan.")
                            sib_f = matched_sib_doc.get("fields", {}) if matched_sib_doc else {}
                            sib_valid = (
                                p_fields.get("valid_until", {}).get("sources", [{}])[0].get("value")
                                if sib_sources else sib_f.get("valid_until", {}).get("value")
                            ) or "— Tidak ditemukan —"
                            sib_file = (
                                matched_sib_doc.get("file_name") if matched_sib_doc
                                else (sib_sources[0].get("document_name") if sib_sources else "-")
                            )

                            with st.container(border=True):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.markdown(f"**📅 Masa Berlaku SIB:** `{sib_valid}`")
                                with c2:
                                    st.markdown(f"**📁 File Sumber:** `{sib_file}`")
                        else:
                            st.caption("ℹ️ Dokumen Surat Izin Bekerja (SIB) tidak ditemukan atau belum terpetakan untuk PPR ini.")

                        # 2. Dokumen Surat Perintah (Sprint)
                        sprint_sources = [
                            s for s in p_fields.get("ppr_name", {}).get("sources", [])
                            if s.get("document_type") == "sprint"
                        ]
                        matched_sprint_idx = None
                        matched_sprint_doc = None
                        for s_i, doc in enumerate(sprint_docs):
                            f = doc.get("fields", {})
                            s_name = f.get("kepada", {}).get("value", "") or f.get("ppr_name", {}).get("value", "")
                            if s_name and (fuzz.token_sort_ratio(normalize_person_name(s_name), norm_target) >= 70 or
                                           normalize_person_name(s_name) in norm_target or
                                           norm_target in normalize_person_name(s_name)):
                                matched_sprint_doc = doc
                                matched_sprint_idx = s_i
                                break

                        if matched_sprint_doc is None and len(sprint_docs) == 1 and len(ppr_personnel) == 1:
                            matched_sprint_doc = sprint_docs[0]
                            matched_sprint_idx = 0

                        has_sprint = bool(sprint_sources or matched_sprint_doc)
                        if has_sprint:
                            if matched_sprint_idx is not None:
                                rendered_sprint_indices.add(matched_sprint_idx)

                            st.markdown("##### 📜 Rincian Khusus Dokumen: Surat Perintah (Sprint)")
                            st.caption("Khusus dokumen Surat Perintah Penunjukan PPR. Field Kepada dan Pengesahan ditampilkan mandiri.")
                            sp_f = matched_sprint_doc.get("fields", {}) if matched_sprint_doc else {}
                            kepada_val = (
                                sp_f.get("kepada", {}).get("value") or sp_f.get("ppr_name", {}).get("value")
                                or (sprint_sources[0].get("value") if sprint_sources else "—")
                            )
                            approval_val = (
                                sp_f.get("pengesahan", {}).get("value") or sp_f.get("approval", {}).get("value")
                                or "—"
                            )
                            sp_file = (
                                matched_sprint_doc.get("file_name") if matched_sprint_doc
                                else (sprint_sources[0].get("document_name") if sprint_sources else "-")
                            )
                            sp_page = sp_f.get("ppr_name", {}).get("page") or 1
                            sp_hosp = sp_f.get("hospital_name", {}).get("value") or ""

                            with st.container(border=True):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.markdown(f"**👤 Kepada (Nama PPR):** `{kepada_val}`")
                                    st.markdown(f"**📁 File Sumber:** `{sp_file}` (Halaman {sp_page})")
                                    if sp_hosp:
                                        st.markdown(f"**🏢 Instansi:** `{sp_hosp}`")
                                with c2:
                                    st.markdown(f"**✍️ Pengesahan:** `{approval_val}` *(Tanda tangan dan stempel)*")
                                    sp_preview = get_sprint_signature_preview(matched_sprint_doc or (sprint_docs[0] if sprint_docs else None))
                                    if sp_preview:
                                        st.caption("🔍 **Crop Tanda Tangan & Stempel Fisik:**")
                                        st.image(sp_preview, caption=f"Pengesahan: {approval_val}", use_container_width=True)
                        else:
                            st.caption("ℹ️ Dokumen Surat Perintah (Sprint) tidak ditemukan atau belum terpetakan untuk PPR ini.")

            # Tampilkan Surat Perintah mandiri hanya jika benar-benar ada dokumen yang belum ditampilkan
            unrendered_sprints = [
                sp for s_i, sp in enumerate(sprint_docs)
                if s_i not in rendered_sprint_indices
            ]
            if unrendered_sprints:
                if ppr_personnel:
                    st.markdown("##### 📜 Dokumen Surat Perintah (Sprint) Tambahan")
                else:
                    st.markdown("##### 📜 Rincian Khusus Dokumen: Surat Perintah (Sprint)")
                st.caption("Khusus dokumen Surat Perintah Penunjukan Petugas Proteksi Radiasi (PPR):")
                for s_idx, sp in enumerate(unrendered_sprints, start=1):
                    sp_fields = sp.get("fields", {})
                    kepada_val = sp_fields.get("kepada", {}).get("value") or sp_fields.get("ppr_name", {}).get("value") or "—"
                    approval_val = sp_fields.get("pengesahan", {}).get("value") or sp_fields.get("approval", {}).get("value") or "—"
                    sp_file = sp.get("file_name", "sprint.pdf")
                    sp_page = sp_fields.get("ppr_name", {}).get("page") or 1
                    sp_hosp = sp_fields.get("hospital_name", {}).get("value") or "—"

                    with st.container(border=True):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f"**👤 Kepada (Nama PPR):** `{kepada_val}`")
                            st.markdown(f"**📁 File Sumber:** `{sp_file}` (Halaman {sp_page})")
                            st.markdown(f"**🏢 Instansi:** `{sp_hosp}`")
                        with c2:
                            st.markdown(f"**✍️ Pengesahan:** `{approval_val}` *(Tanda tangan dan stempel)*")
                            sp_preview = get_sprint_signature_preview(sp)
                            if sp_preview:
                                st.caption("🔍 **Crop Tanda Tangan & Stempel Fisik:**")
                                st.image(sp_preview, caption=f"Pengesahan: {approval_val}", use_container_width=True)

            # Tampilkan SIB mandiri jika belum terpetakan ke expander PPR
            unrendered_sibs = [
                sib for s_i, sib in enumerate(sib_docs)
                if s_i not in rendered_sib_indices
            ]
            if not ppr_personnel and unrendered_sibs:
                st.markdown("##### 📄 Rincian Khusus Dokumen: Surat Izin Bekerja (SIB)")
                for sib in unrendered_sibs:
                    sib_f = sib.get("fields", {})
                    sib_val = sib_f.get("valid_until", {}).get("value") or "—"
                    sib_file = sib.get("file_name", "SIB.pdf")
                    with st.container(border=True):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f"**📅 Masa Berlaku SIB:** `{sib_val}`")
                        with c2:
                            st.markdown(f"**📁 File Sumber:** `{sib_file}`")

            if not ppr_personnel and not unrendered_sprints and not unrendered_sibs:
                st.info("Data Petugas Proteksi Radiasi (PPR) tidak ditemukan pada berkas.")

        # 3. Pemeriksaan peralatan: pesawat dan tabung dikelompokkan dalam satu bagian,
        # tetapi atribut keduanya tetap dipisahkan agar nilai yang dibandingkan tidak tercampur.
        xray_eq = report.get("xray_equipment", [])
        xray_tubes = report.get("xray_tubes", [])
        if xray_eq or xray_tubes:
            st.markdown("### ⚡ 3. Pemeriksaan Pesawat Sinar-X")
            st.caption(
                "Pemeriksaan pesawat dan tabung ditampilkan dalam satu bagian. "
                "Gunakan tabel horizontal pada setiap kelompok untuk membandingkan nilai antar-dokumen dari kiri ke kanan."
            )

            if xray_eq:
                st.markdown("#### A. Identitas Pesawat Sinar-X")
                for idx, eq in enumerate(xray_eq, start=1):
                    label = eq.get("entity_label") or f"Pesawat Sinar-X {idx}"
                    status = _clean_status_str(eq.get("status") or "Status belum tersedia")
                    with st.expander(f"{label} — {status}", expanded=(idx == 1)):
                        render_field_comparison(eq.get("fields", {}), f"equipment_{idx}")
            else:
                st.info("Data identitas pesawat sinar-X tidak ditemukan pada hasil cross-check.")

            if xray_tubes:
                st.markdown("#### B. Identitas Tabung Sinar-X")
                for idx, tube in enumerate(xray_tubes, start=1):
                    label = tube.get("entity_label") or f"Tabung Sinar-X {idx}"
                    status = _clean_status_str(tube.get("status") or "Status belum tersedia")
                    with st.expander(f"{label} — {status}", expanded=(idx == 1)):
                        render_field_comparison(tube.get("fields", {}), f"tube_{idx}")
            else:
                st.info("Data identitas tabung sinar-X tidak ditemukan pada hasil cross-check.")

    st.subheader("3. Kelengkapan Berkas yang Diunggah")
    st.caption("Bagian ini menunjukkan dokumen yang tersedia pada proses ini, bukan keputusan akhir kelayakan izin.")
    st.dataframe(pd.DataFrame(result["presence"]), use_container_width=True, hide_index=True)

    st.subheader("4. Detail Hasil Ekstraksi per Dokumen (Debugging & Troubleshooting)")
    st.caption("Gunakan bagian ini untuk melacak nilai teks asli hasil parser atau OCR per dokumen secara transparan.")
    for doc_type, docs in result.get("extractions", {}).items():
        if not docs:
            continue
        doc_label = DOCUMENT_TYPES.get(doc_type, {}).get("name", doc_type)
        st.markdown(f"#### 📄 {doc_label} (`{doc_type}`)")
        for idx, doc in enumerate(docs, start=1):
            file_name = doc.get("file_name", f"file #{idx}")
            with st.expander(f"🔍 {file_name} — file #{idx} ({doc.get('source_kind', 'dokumen')})", expanded=False):
                fields_dict = doc.get("fields", {})
                
                scalar_rows = []
                complex_fields = []

                configured_keys = DOCUMENT_FIELDS.get(doc_type, [])
                raw_keys = list(configured_keys) + [k for k in fields_dict if k not in configured_keys]

                # Deduplicate and filter fields:
                # 1. Skip header and all_xray_rows from standard processing
                # 2. Skip composite unit_type_serial if unit_type and/or unit_serial_number are available
                # 3. Skip composite tube_type_serial if tube_type and/or tube_serial_number are available
                # 4. Skip tube_model if tube_type is present
                filtered_keys = []
                has_unit_sep = ("unit_type" in fields_dict or "unit_serial_number" in fields_dict)
                has_tube_sep = ("tube_type" in fields_dict or "tube_serial_number" in fields_dict)

                for k in raw_keys:
                    if k in ("header", "all_xray_rows"):
                        continue
                    if k == "unit_type_serial" and has_unit_sep:
                        continue
                    if k == "tube_type_serial" and has_tube_sep:
                        continue
                    if k == "tube_model" and ("tube_type" in fields_dict or "tube_serial_number" in fields_dict):
                        continue
                    if k not in filtered_keys:
                        filtered_keys.append(k)

                # Canonical ordering for scalar rows:
                # 1. hospital_name, 2. hospital_address, 3. unit_brand, 4. unit_type,
                # 5. unit_serial_number, 6. tube_brand, 7. tube_type, 8. tube_serial_number,
                # then any remaining fields
                CANONICAL_ORDER = [
                    "hospital_name",
                    "hospital_address",
                    "unit_brand",
                    "unit_type",
                    "unit_serial_number",
                    "tube_brand",
                    "tube_type",
                    "tube_serial_number",
                ]
                def key_sort_score(k):
                    if k in CANONICAL_ORDER:
                        return (0, CANONICAL_ORDER.index(k))
                    return (1, k)

                ordered_keys = sorted(filtered_keys, key=key_sort_score)

                for field_key in ordered_keys:
                    item = fields_dict.get(field_key, {})
                    value = item.get("value") if isinstance(item, dict) else item
                    
                    if isinstance(value, (list, dict)):
                        complex_fields.append((field_key, value, item if isinstance(item, dict) else {}))
                    else:
                        scalar_rows.append({
                            "Field Key": field_key,
                            "Nama Field": FIELD_DEFINITIONS.get(field_key, {}).get("label", field_key.replace("_", " ").title()),
                            "Nilai Ekstraksi": str(value if value is not None else ""),
                            "Halaman": item.get("page") if isinstance(item, dict) else "-",
                            "Metode": item.get("method") if isinstance(item, dict) else "-",
                            "Confidence": f"{item.get('confidence'):.2f}" if isinstance(item, dict) and item.get("confidence") is not None else "-",
                        })
                        
                if scalar_rows:
                    st.markdown("**Nilai Field Standar (Teks):**")
                    st.dataframe(pd.DataFrame(scalar_rows), use_container_width=True, hide_index=True)
                
                # Render list/table/dict fields clearly for debugging
                for c_key, c_val, c_meta in complex_fields:
                    c_title = c_key.replace("_", " ").title()
                    st.markdown(f"**Data Terstruktur / Tabel: `{c_key}` ({c_title})**")
                    if isinstance(c_val, list):
                        if c_val:
                            clean_list = []
                            for row_item in c_val:
                                if isinstance(row_item, dict):
                                    clean_row = {
                                        k: v for k, v in row_item.items()
                                        if k not in ("unit_type_serial", "tube_type_serial")
                                    }
                                    clean_list.append(clean_row)
                                else:
                                    clean_list.append(row_item)
                            st.dataframe(pd.DataFrame(clean_list), use_container_width=True, hide_index=True)
                        else:
                            st.info(f"Tabel {c_title} kosong.")
                    elif isinstance(c_val, dict):
                        clean_dict = {
                            k: v for k, v in c_val.items()
                            if k not in ("unit_type_serial", "tube_type_serial")
                        }
                        st.dataframe(pd.DataFrame([clean_dict]), use_container_width=True, hide_index=True)
                        with st.expander(f"Rincian Kolom `{c_key}` (Key-Value)"):
                            kv_rows = [
                                {
                                    "Field Key": k,
                                    "Nama Atribut": FIELD_DEFINITIONS.get(k, {}).get("label", k.replace("_", " ").title()),
                                    "Nilai Ekstraksi": str(v),
                                }
                                for k, v in clean_dict.items()
                            ]
                            st.dataframe(pd.DataFrame(kv_rows), use_container_width=True, hide_index=True)

    with st.expander("Schema field yang digunakan"):
        st.json(result["schema"])

    st.download_button(
        "Download hasil JSON",
        data=json.dumps(result, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        file_name=f"{result['run_id']}.json",
        mime="application/json",
    )

with st.expander("Riwayat proses"):
    rows = db.list_runs()
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["run_id", "created_at", "file_count"]), use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada riwayat.")
