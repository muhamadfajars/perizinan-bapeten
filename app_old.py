from pathlib import Path
import json
import tempfile

import pandas as pd
import streamlit as st

from config import DB_PATH, DOCUMENT_TYPES, DOCUMENT_FIELDS
from src.pipeline import execute_run
from src.storage.database import Database
from src.extraction.classifier import classify_document

st.set_page_config(page_title="BAPETEN Document Cross-check", layout="wide")
st.title("BAPETEN — Document Extraction & Cross-check")
st.caption("Ekstraksi field dan validasi konsistensi antar-dokumen untuk membantu evaluator. Sistem tidak mengambil keputusan izin. (Engine v2.3 - Auto-Classification Batch Upload & Smart Matching)")

db = Database(DB_PATH)
past_runs = db.list_runs(limit=25)
run_lookup = {r[0]: f"{r[0]} ({r[1]} - {r[2]} berkas)" for r in past_runs}

# Auto-restore latest run from database on page load/refresh if session state was cleared
if "latest_result" not in st.session_state and past_runs:
    try:
        newest_run = db.get_run(past_runs[0][0])
        if newest_run:
            st.session_state["latest_result"] = newest_run
    except Exception:
        pass


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
                # Read bytes for PDF content classification if needed
                file_bytes = file.getvalue() if file.name.lower().endswith(".pdf") else None
                detected_type, reason = classify_document(file.name, file_bytes)
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
        st.subheader("2. Hasil Cross-Check Permohonan")

        # 1. Identitas Fasilitas
        fac = report.get("facility")
        if fac:
            st.markdown("### 🏢 1. Identitas Fasilitas")
            fac_fields = fac.get("fields", {})
            fac_rows = []
            for f_key in ["project_name", "project_address"]:
                f_val = fac_fields.get(f_key, {})
                if f_val:
                    fac_rows.append({
                        "Field": f_val.get("field_label", f_key),
                        "Status": f_val.get("status"),
                        "Score": f"{f_val.get('score'):.1f}" if f_val.get('score') is not None else "-",
                        "Penjelasan": f_val.get("reason"),
                        "Dokumen Sumber": " | ".join(f"{s.get('document_type')}: {s.get('value')}" for s in f_val.get("sources", [])),
                    })
            if fac_rows:
                st.dataframe(pd.DataFrame(fac_rows), use_container_width=True, hide_index=True)

            # Detailed tree breakdown of source documents for Nama proyek
            p_name_sources = fac_fields.get("project_name", {}).get("sources", [])
            with st.expander("🔍 Rincian Lintas Dokumen: Nama Proyek (Formulir, Sprint, TLD, PPKR, dll)", expanded=False):
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
                            val_text = "(Nama faskes belum terdeteksi pada teks)"
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
                        "Nilai Ekstraksi Nama Proyek": val_text,
                        "File Sumber": file_name,
                        "Halaman": page_text,
                    })
                st.dataframe(pd.DataFrame(tree_rows), use_container_width=True, hide_index=True)

        # 2. Personel
        personnel = report.get("personnel", [])
        if personnel:
            st.markdown("### 👨‍⚕️ 2. Personel")
            for idx, p in enumerate(personnel, start=1):
                with st.expander(f"{p.get('entity_label')} — Status: {p.get('status')}", expanded=(idx == 1)):
                    p_rows = []
                    # Keep canonical order: Nama, Profesi/Keahlian, Nama PPR, Masa berlaku, Tempat praktik
                    field_order = ["person_name", "profession", "ppr_name", "valid_until", "practice_location"]
                    for f_key in field_order:
                        f_val = p.get("fields", {}).get(f_key, {})
                        if f_val:
                            p_rows.append({
                                "Field": f_val.get("field_label", f_key),
                                "Status": f_val.get("status"),
                                "Score": f"{f_val.get('score'):.1f}" if f_val.get('score') is not None else "-",
                                "Penjelasan": f_val.get("reason"),
                                "Dokumen Sumber": " | ".join(f"{s.get('document_type')}: {s.get('value')}" for s in f_val.get("sources", [])) if f_val.get("sources") else "-",
                            })
                    st.dataframe(pd.DataFrame(p_rows), use_container_width=True, hide_index=True)

        # 3. Pesawat Sinar-X
        xray_eq = report.get("xray_equipment", [])
        if xray_eq:
            st.markdown("### ⚡ 3. Pesawat Sinar-X")
            for idx, eq in enumerate(xray_eq, start=1):
                with st.expander(f"{eq.get('entity_label')} — Status: {eq.get('status')}", expanded=True):
                    eq_rows = []
                    field_order = ["unit_brand", "unit_type", "unit_serial_number"]
                    for f_key in field_order:
                        f_val = eq.get("fields", {}).get(f_key, {})
                        if f_val:
                            eq_rows.append({
                                "Field": f_val.get("field_label", f_key),
                                "Status": f_val.get("status"),
                                "Score": f"{f_val.get('score'):.1f}" if f_val.get('score') is not None else "-",
                                "Penjelasan": f_val.get("reason"),
                                "Dokumen Sumber": " | ".join(f"{s.get('document_type')}: {s.get('value')}" for s in f_val.get("sources", [])),
                            })
                    st.dataframe(pd.DataFrame(eq_rows), use_container_width=True, hide_index=True)

        # 4. Tabung Sinar-X
        xray_tubes = report.get("xray_tubes", [])
        if xray_tubes:
            st.markdown("### 🔬 4. Tabung Sinar-X")
            for idx, tube in enumerate(xray_tubes, start=1):
                with st.expander(f"{tube.get('entity_label')} — Status: {tube.get('status')}", expanded=True):
                    tube_rows = []
                    field_order = ["tube_brand", "tube_type", "tube_serial_number"]
                    for f_key in field_order:
                        f_val = tube.get("fields", {}).get(f_key, {})
                        if f_val:
                            tube_rows.append({
                                "Field": f_val.get("field_label", f_key),
                                "Status": f_val.get("status"),
                                "Score": f"{f_val.get('score'):.1f}" if f_val.get('score') is not None else "-",
                                "Penjelasan": f_val.get("reason"),
                                "Dokumen Sumber": " | ".join(f"{s.get('document_type')}: {s.get('value')}" for s in f_val.get("sources", [])),
                            })
                    st.dataframe(pd.DataFrame(tube_rows), use_container_width=True, hide_index=True)

    st.subheader("3. Kelengkapan Berkas yang Diunggah")
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
                all_keys = list(configured_keys) + [k for k in fields_dict if k not in configured_keys and k != "all_xray_rows"]

                for field_key in all_keys:
                    item = fields_dict.get(field_key, {})
                    value = item.get("value") if isinstance(item, dict) else item
                    
                    if isinstance(value, (list, dict)):
                        complex_fields.append((field_key, value, item if isinstance(item, dict) else {}))
                    else:
                        scalar_rows.append({
                            "Field Key": field_key,
                            "Nama Field": field_key.replace("_", " ").title(),
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
                            st.dataframe(pd.DataFrame(c_val), use_container_width=True, hide_index=True)
                        else:
                            st.info(f"Tabel {c_title} kosong.")
                    elif isinstance(c_val, dict):
                        # Show as horizontal dataframe for easy column view
                        st.dataframe(pd.DataFrame([c_val]), use_container_width=True, hide_index=True)
                        with st.expander(f"Rincian Kolom `{c_key}` (Key-Value)"):
                            kv_rows = [
                                {"Field Key": k, "Nama Atribut": k.replace("_", " ").title(), "Nilai Ekstraksi": str(v)}
                                for k, v in c_val.items()
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
