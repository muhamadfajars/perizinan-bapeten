from pathlib import Path
import json
import re
import tempfile
from datetime import datetime

import pandas as pd
import streamlit as st
import altair as alt
from rapidfuzz import fuzz

from config import DB_PATH, DOCUMENT_TYPES, DOCUMENT_FIELDS, FIELD_DEFINITIONS
from src.pipeline import execute_run
from src.storage.database import Database
from src.extraction.classifier import classify_document
from src.matching.normalizer import normalize_person_name
from src.matching.cross_check_engine import evaluate_field_sources, SourceEvidence
from src.extraction.signature_cropper import get_sprint_signature_preview

# ═══════════════════════════════════════════════════════════════════
# PAGE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="BAPETEN · Verifikasi Dokumen Perizinan",
    page_icon="⚛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════
# RENDER HTML HELPER (Fixes CommonMark 4-space code block glitch)
# ═══════════════════════════════════════════════════════════════════
def render_html(html_str: str):
    """Renders raw HTML safely in Streamlit without being converted to code blocks."""
    clean_lines = [line.strip() for line in html_str.splitlines() if line.strip()]
    st.markdown("".join(clean_lines), unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# ULTRA-PREMIUM DARK THEME CSS
# ═══════════════════════════════════════════════════════════════════
render_html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --bg-dark: #090d16;
    --surface-1: #0f172a;
    --surface-2: #1e293b;
    --border-subtle: rgba(255, 255, 255, 0.07);
    --border-strong: rgba(255, 255, 255, 0.14);
    --accent-blue: #38bdf8;
    --accent-emerald: #10b981;
    --accent-amber: #f59e0b;
    --accent-rose: #f43f5e;
    --accent-violet: #a855f7;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
}

html, body, [data-testid="stAppViewContainer"], .main, .block-container {
    background-color: var(--bg-dark) !important;
    color: var(--text-primary) !important;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0b1120 0%, #070a12 100%) !important;
    border-right: 1px solid var(--border-subtle) !important;
}
section[data-testid="stSidebar"] * {
    color: var(--text-secondary) !important;
}
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, 
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] strong {
    color: var(--text-primary) !important;
}

h1, h2, h3, h4, h5, h6, p, span, label, div {
    color: var(--text-primary);
}
.mono {
    font-family: 'JetBrains Mono', monospace !important;
}

/* Top Header */
.inst-header {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
    border: 1px solid var(--border-subtle);
    border-radius: 16px;
    padding: 1.4rem 1.8rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    display: flex;
    justify-content: space-between;
    align-items: center;
    backdrop-filter: blur(12px);
}
.inst-title-area {
    display: flex;
    align-items: center;
    gap: 1.2rem;
}
.inst-logo-badge {
    width: 50px;
    height: 50px;
    border-radius: 14px;
    background: linear-gradient(135deg, #0284c7, #6366f1);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.8rem;
    box-shadow: 0 4px 15px rgba(2, 132, 199, 0.4);
}
.inst-title {
    font-size: 1.35rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin: 0;
    background: linear-gradient(135deg, #f8fafc 0%, #cbd5e1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.inst-sub {
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin-top: 0.2rem;
}

/* Applicant Summary Card */
.applicant-card {
    background: linear-gradient(135deg, #131d31 0%, #0e1726 100%);
    border: 1px solid rgba(56, 189, 248, 0.2);
    border-radius: 16px;
    padding: 1.4rem 1.8rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}
.applicant-card::after {
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 350px;
    height: 350px;
    background: radial-gradient(circle, rgba(56, 189, 248, 0.08) 0%, transparent 70%);
    border-radius: 50%;
    pointer-events: none;
}
.app-meta-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 1.5rem;
    margin-top: 1rem;
}
.app-meta-item {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 0.8rem 1rem;
}
.app-meta-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    font-weight: 600;
    margin-bottom: 0.25rem;
}
.app-meta-val {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-primary);
}

/* Verdict Box */
.verdict-box {
    border-radius: 14px;
    padding: 1.2rem 1.6rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 1.2rem;
    border: 1px solid;
}
.vb-pass {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(16, 185, 129, 0.03));
    border-color: rgba(16, 185, 129, 0.3);
}
.vb-warn {
    background: linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(245, 158, 11, 0.03));
    border-color: rgba(245, 158, 11, 0.3);
}
.vb-fail {
    background: linear-gradient(135deg, rgba(244, 63, 94, 0.12), rgba(244, 63, 94, 0.03));
    border-color: rgba(244, 63, 94, 0.3);
}
.vb-icon {
    font-size: 2.5rem;
    line-height: 1;
}
.vb-content h3 {
    margin: 0;
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: -0.01em;
}
.vb-content p {
    margin: 0.3rem 0 0 0;
    font-size: 0.85rem;
    color: var(--text-secondary);
    line-height: 1.5;
}

/* KPI Scorecard Grid */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 1.5rem;
}
.kpi-card {
    background: #0f172a;
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 1.1rem 1.2rem;
    position: relative;
    overflow: hidden;
    transition: all 0.25s ease;
}
.kpi-card:hover {
    transform: translateY(-2px);
    border-color: var(--border-strong);
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3);
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
}
.kpi-green::before { background: var(--accent-emerald); }
.kpi-amber::before { background: var(--accent-amber); }
.kpi-rose::before { background: var(--accent-rose); }
.kpi-slate::before { background: var(--text-muted); }

.kpi-num {
    font-size: 2.2rem;
    font-weight: 800;
    line-height: 1;
    margin-bottom: 0.35rem;
    letter-spacing: -0.03em;
}
.kpi-green .kpi-num { color: #34d399; }
.kpi-amber .kpi-num { color: #fbbf24; }
.kpi-rose .kpi-num { color: #f87171; }
.kpi-slate .kpi-num { color: #94a3b8; }

.kpi-label {
    font-size: 0.74rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-secondary);
}
.kpi-desc {
    font-size: 0.72rem;
    color: var(--text-muted);
    margin-top: 0.2rem;
}

/* Findings Cards */
.finding-card {
    background: #0f172a;
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 1.1rem 1.4rem;
    margin-bottom: 0.8rem;
    border-left: 4px solid;
    transition: all 0.2s ease;
}
.finding-card:hover {
    background: #131e36;
    border-color: rgba(255, 255, 255, 0.15);
}
.fc-critical { border-left-color: var(--accent-rose); }
.fc-warning { border-left-color: var(--accent-amber); }
.fc-info { border-left-color: var(--accent-blue); }

.fc-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
}
.fc-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-primary);
}
.fc-badge {
    font-size: 0.68rem;
    font-weight: 700;
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.badge-critical { background: rgba(244, 63, 94, 0.2); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.4); }
.badge-warning { background: rgba(245, 158, 11, 0.2); color: #fde68a; border: 1px solid rgba(245, 158, 11, 0.4); }
.badge-info { background: rgba(56, 189, 248, 0.2); color: #bae6fd; border: 1px solid rgba(56, 189, 248, 0.4); }

.fc-body {
    font-size: 0.84rem;
    color: var(--text-secondary);
    line-height: 1.5;
}
.fc-action {
    margin-top: 0.6rem;
    padding: 0.6rem 0.8rem;
    background: rgba(255, 255, 255, 0.02);
    border-radius: 8px;
    border: 1px dashed rgba(255, 255, 255, 0.1);
    font-size: 0.78rem;
    color: #cbd5e1;
}

/* Spotlight Profile Card (PPR) */
.spotlight-card {
    background: linear-gradient(135deg, #131d33 0%, #0c1424 100%);
    border: 1px solid rgba(168, 85, 247, 0.25);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1.2rem;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.25);
}
.spotlight-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.2rem;
}
.spotlight-avatar {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    background: linear-gradient(135deg, #7c3aed, #a855f7);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.8rem;
    box-shadow: 0 4px 15px rgba(124, 58, 237, 0.4);
}
.spotlight-info h4 {
    margin: 0;
    font-size: 1.15rem;
    font-weight: 800;
}
.spotlight-info p {
    margin: 0.2rem 0 0 0;
    font-size: 0.8rem;
    color: var(--text-secondary);
}

/* Personnel Mini Cards */
.personnel-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
    margin: 1rem 0;
}
.personnel-card {
    background: #0f172a;
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 1rem 1.2rem;
    transition: all 0.2s ease;
}
.personnel-card:hover {
    border-color: rgba(255, 255, 255, 0.15);
    transform: translateY(-2px);
}
.p-role-tag {
    font-size: 0.68rem;
    font-weight: 700;
    padding: 0.15rem 0.5rem;
    border-radius: 20px;
    background: rgba(56, 189, 248, 0.15);
    color: #7dd3fc;
    display: inline-block;
    margin-bottom: 0.4rem;
}

/* Equipment Specs Card */
.equip-card {
    background: #0f172a;
    border: 1px solid var(--border-subtle);
    border-radius: 14px;
    padding: 1.4rem;
    margin-bottom: 1.2rem;
}
.equip-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 0.8rem;
    margin-bottom: 1rem;
}
.equip-title {
    font-size: 1.1rem;
    font-weight: 700;
}

/* Clean HTML Matrix Table */
.matrix-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin: 1rem 0;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border-subtle);
    background: #0f172a;
}
.matrix-table th {
    background: #1e293b;
    padding: 0.75rem 1rem;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    text-align: left;
    border-bottom: 1px solid var(--border-subtle);
}
.matrix-table td {
    padding: 0.7rem 1rem;
    font-size: 0.82rem;
    color: var(--text-primary);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.matrix-table tr:last-child td {
    border-bottom: none;
}
.matrix-table tr:hover td {
    background: rgba(255, 255, 255, 0.02);
}

/* Status Badges */
.pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.02em;
}
.pill-match { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.pill-review { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.pill-fail { background: rgba(244, 63, 94, 0.15); color: #f87171; border: 1px solid rgba(244, 63, 94, 0.3); }
.pill-missing { background: rgba(100, 116, 139, 0.15); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }

/* Tab Styling Overrides */
.stTabs [data-baseweb="tab-list"] {
    background: #0f172a !important;
    border-radius: 12px !important;
    padding: 6px !important;
    gap: 6px !important;
    border: 1px solid var(--border-subtle) !important;
    margin-bottom: 1.5rem !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    color: var(--text-secondary) !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 8px 18px !important;
    background: transparent !important;
    border: none !important;
    transition: all 0.2s ease !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: var(--text-primary) !important;
    background: rgba(255, 255, 255, 0.03) !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: #1e293b !important;
    color: #38bdf8 !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2) !important;
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* Modern Inputs & Selectboxes */
[data-baseweb="select"] > div, [data-baseweb="input"] > div {
    background: #0f172a !important;
    border-color: var(--border-subtle) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
}
[data-testid="stExpander"] {
    background: #0f172a !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 10px !important;
    margin-bottom: 0.6rem !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    color: var(--text-primary) !important;
}
[data-testid="stExpander"] summary:hover {
    color: #38bdf8 !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-dark); }
::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #334155; }
</style>
""")


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════
def _clean_status_str(status):
    if hasattr(status, "value"):
        s = str(status.value)
    else:
        s = str(status or "")
    s = s.upper().strip()
    if "." in s:
        s = s.split(".")[-1].strip()
    return s


def _render_pill(status_str):
    s = _clean_status_str(status_str)
    if s == "SESUAI":
        return '<span class="pill pill-match">✓ Sesuai</span>'
    elif s in {"PERLU REVIEW", "WARNING"}:
        return f'<span class="pill pill-review">⚠ {s.title()}</span>'
    elif s == "TIDAK SESUAI":
        return '<span class="pill pill-fail">✗ Tidak Sesuai</span>'
    elif s == "TIDAK DITEMUKAN":
        return '<span class="pill pill-missing">○ Belum Ada</span>'
    return f'<span class="pill pill-missing">{s}</span>'


def _render_parameter_card(category_label, field_title, fv, docs_map):
    """Renders a separated, card-based parameter breakdown with status badge, notes, and clean source table."""
    sources = fv.get("sources", [])
    
    clean_sources = []
    for s in sources:
        dt = s.get("document_type", "dokumen")
        dname = DOCUMENT_TYPES.get(dt, {}).get("name", dt.replace("_", " ").title())
        val = str(s.get("value") or "—").strip()
        # Clean inspection test tokens if present
        val = re.sub(r"\s*\b(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Colimator(?:\s+Rotation)?|Mechanical|InSpec|Brake|Batere|Status)\s*(?:PASS|FAIL)?\b.*$", "", val, flags=re.I)
        val = re.sub(r"\s*\b(?:PASS|FAIL)\b.*$", "", val, flags=re.I).strip(" :;-,") or "—"
        fname = s.get("file_name") or s.get("document_name") or (docs_map.get(dt, ["-"])[0] if dt in docs_map else "-")
        page = s.get("page") or "-"
        clean_sources.append({
            "document_type": dt,
            "document_name": fname,
            "display_name": dname,
            "value": val,
            "page": page,
        })

    # Dynamically evaluate status and reason with smart tolerance
    fstatus = _clean_status_str(fv.get("status", "SESUAI"))
    reason_msg = fv.get("reason", "")

    # For hospital name, address, or personnel name, dynamically compute tolerance-based cross check
    if "Nama Rumah Sakit" in field_title or fv.get("field_key") == "project_name":
        ev = [SourceEvidence(document_type=s["document_type"], document_name=s["document_name"], value=s["value"], page=s["page"]) for s in clean_sources if s["value"] not in ("—", "")]
        if len(ev) > 1:
            check_res = evaluate_field_sources("project_name", "Nama instansi", ev, mode="facility_name")
            fstatus = _clean_status_str(check_res.status)
            reason_msg = check_res.reason
    elif "Alamat" in field_title or fv.get("field_key") == "project_address":
        ev = [SourceEvidence(document_type=s["document_type"], document_name=s["document_name"], value=s["value"], page=s["page"]) for s in clean_sources if s["value"] not in ("—", "")]
        if len(ev) > 1:
            check_res = evaluate_field_sources("project_address", "Alamat instansi", ev, mode="fuzzy_address")
            fstatus = _clean_status_str(check_res.status)
            reason_msg = check_res.reason
    elif fv.get("field_key") in {"person_name", "ppr_name"} or "Nama Personel" in field_title or "Nama Petugas" in field_title:
        ev = [SourceEvidence(document_type=s["document_type"], document_name=s["document_name"], value=s["value"], page=s["page"]) for s in clean_sources if s["value"] not in ("—", "")]
        if len(ev) > 1:
            check_res = evaluate_field_sources(fv.get("field_key") or "person_name", field_title, ev, mode="fuzzy_name")
            fstatus = _clean_status_str(check_res.status)
            reason_msg = check_res.reason
    else:
        if reason_msg:
            reason_msg = re.sub(r"\s*(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?)\s*PASS\b", "", reason_msg, flags=re.I)

    badge_html = _render_pill(fstatus)
    if fstatus == "TIDAK DITEMUKAN" and len(clean_sources) == 1:
        badge_html = '<span class="pill pill-review" style="background:rgba(148, 163, 184, 0.12); color:#94a3b8; border:1px solid rgba(148, 163, 184, 0.25);">○ 1 Dokumen Terdaftar</span>'
        if not reason_msg or "Data hanya ditemukan pada 1 dokumen" in reason_msg:
            reason_msg = f"Data tercantum pada {clean_sources[0]['display_name']}, belum ada berkas pembanding lain yang diunggah."

    card_html = f"""
    <div style="background:#0f172a; border:1px solid var(--border-subtle); border-radius:12px; padding:1.2rem; margin-bottom:1.2rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.8rem;">
            <div>
                <span style="font-size:0.75rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">{category_label}</span>
                <h4 style="margin:0.2rem 0 0 0; font-size:1.1rem; font-weight:800;">{field_title}</h4>
            </div>
            <div>{badge_html}</div>
        </div>
    """
    if reason_msg:
        color_note = "#fca5a5" if fstatus == "TIDAK SESUAI" else ("#fde68a" if fstatus in {"PERLU REVIEW", "WARNING"} else "#94a3b8")
        card_html += f"""
        <div style="font-size:0.82rem; color:{color_note}; margin-bottom:0.8rem;">
            {reason_msg}
        </div>
        """
        
    if clean_sources:
        t_rows = ""
        for s in clean_sources:
            page_info = f" (Hal. {s['page']})" if s.get('page') not in (None, "-", "") else ""
            t_rows += f"<tr><td style='font-weight:700; color:#38bdf8; width:35%;'>{s['display_name']}</td><td style='font-weight:600; width:35%;'>{s['value']}</td><td style='color:#64748b; width:30%;'>{s['document_name']}{page_info}</td></tr>"
        
        card_html += f"""
        <table class="matrix-table">
            <thead><tr><th>Dokumen Sumber</th><th>Nilai Tertera</th><th>Berkas Fisik</th></tr></thead>
            <tbody>{t_rows}</tbody>
        </table>
        """
    else:
        card_html += """
        <div style="font-size:0.82rem; color:#64748b; font-style:italic; padding:0.4rem 0;">
            Tidak ada data tertera pada berkas permohonan.
        </div>
        """
    card_html += "</div>"
    render_html(card_html)

def _render_sip_consolidated_card(idx, v_field, l_field, docs_map):
    """Renders a single consolidated card for doctor's SIP credentials (validity & practice location) to prevent duplicate 1-row cards."""
    v_sources = v_field.get("sources", []) if v_field else []
    l_sources = l_field.get("sources", []) if l_field else []
    if not v_sources and not l_sources:
        return

    v_val = v_sources[0].get("value", "—") if v_sources else "—"
    v_doc = v_sources[0].get("file_name") or v_sources[0].get("document_name") or "Surat Izin Praktik (SIP)"
    v_page = v_sources[0].get("page")
    v_p_str = f" (Hal. {v_page})" if v_page not in (None, "-", "") else ""

    l_val = l_sources[0].get("value", "—") if l_sources else "—"
    l_doc = l_sources[0].get("file_name") or l_sources[0].get("document_name") or "Surat Izin Praktik (SIP)"
    l_page = l_sources[0].get("page")
    l_p_str = f" (Hal. {l_page})" if l_page not in (None, "-", "") else ""

    v_status = _clean_status_str(v_field.get("status", "SESUAI")) if v_field else "SESUAI"
    l_status = _clean_status_str(l_field.get("status", "SESUAI")) if l_field else "SESUAI"

    overall_status = "SESUAI"
    if "TIDAK SESUAI" in (v_status, l_status):
        overall_status = "TIDAK SESUAI"
    elif "PERLU REVIEW" in (v_status, l_status) or "WARNING" in (v_status, l_status):
        overall_status = "PERLU REVIEW"

    badge_html = _render_pill(overall_status)

    notes = []
    if v_field and v_field.get("reason"):
        notes.append(v_field["reason"])
    if l_field and l_field.get("reason"):
        notes.append(l_field["reason"])
    note_html = ""
    if notes:
        note_html = f"<div style='font-size:0.82rem; color:#94a3b8; margin-bottom:0.8rem;'>{' · '.join(notes)}</div>"

    card_html = f"""
    <div style="background:#0f172a; border:1px solid var(--border-subtle); border-radius:12px; padding:1.2rem; margin-bottom:1.2rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.8rem;">
            <div>
                <span style="font-size:0.75rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">Kredensial Izin Personel #{idx}</span>
                <h4 style="margin:0.2rem 0 0 0; font-size:1.1rem; font-weight:800;">Surat Izin Praktik (SIP)</h4>
            </div>
            <div>{badge_html}</div>
        </div>
        {note_html}
        <table class="matrix-table">
            <thead>
                <tr>
                    <th style="width:25%;">Parameter SIP</th>
                    <th style="width:45%;">Nilai Tertera</th>
                    <th style="width:30%;">Berkas Sumber</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="font-weight:700; color:#38bdf8;">Masa Berlaku Izin</td>
                    <td style="font-weight:600;"><strong style="color:#34d399;">{v_val}</strong> <span style="font-size:0.75rem; color:#64748b;">(Aktif)</span></td>
                    <td style="color:#64748b;">{v_doc}{v_p_str}</td>
                </tr>
                <tr>
                    <td style="font-weight:700; color:#38bdf8;">Tempat Praktik</td>
                    <td style="font-weight:600;">{l_val}</td>
                    <td style="color:#64748b;">{l_doc}{l_p_str}</td>
                </tr>
            </tbody>
        </table>
    </div>
    """
    render_html(card_html)



def _extract_applicant_details(res):
    """Extracts institutional profile from result object for presentation."""
    details = {
        "hospital_name": "Tidak Terdeteksi",
        "hospital_address": "Tidak Terdeteksi",
        "ppr_name": "-",
        "ppr_sib_valid": "-",
        "xray_units": [],
        "total_docs": 0,
        "run_date": "",
    }
    if not res:
        return details

    def _clean_disp_str(v):
        if not v:
            return ""
        s = re.sub(r"\s*\b(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?|Colimator(?:\s+Rotation)?|Mechanical|InSpec|Brake|Batere|Status)\s*(?:PASS|FAIL)?\b.*$", "", str(v), flags=re.I)
        return re.sub(r"\s*\b(?:PASS|FAIL)\b.*$", "", s, flags=re.I).strip(" :;-,")

    # Hospital Name
    fac = res.get("cross_check_report", {}).get("facility", {}).get("fields", {})
    for s in fac.get("project_name", {}).get("sources", []):
        if s.get("value") and str(s.get("value")).strip():
            details["hospital_name"] = _clean_disp_str(s.get("value"))
            break
    if details["hospital_name"] == "Tidak Terdeteksi":
        for doc in res.get("extractions", {}).get("formulir", []):
            val = doc.get("fields", {}).get("hospital_name", {}).get("value")
            if val:
                details["hospital_name"] = _clean_disp_str(val)
                break

    # Hospital Address
    for s in fac.get("project_address", {}).get("sources", []):
        if s.get("value") and str(s.get("value")).strip():
            details["hospital_address"] = _clean_disp_str(s.get("value"))
            break

    # PPR Info
    for doc in res.get("extractions", {}).get("sib", []) + res.get("extractions", {}).get("sprint", []):
        df = doc.get("fields", {})
        for k in ["ppr_name", "kepada", "person_name"]:
            if k in df and df[k].get("value"):
                details["ppr_name"] = str(df[k].get("value")).strip()
                break
        if df.get("valid_until", {}).get("value"):
            details["ppr_sib_valid"] = str(df.get("valid_until", {}).get("value")).strip()
        if details["ppr_name"] != "-":
            break

    # X-ray units
    xeq = res.get("cross_check_report", {}).get("xray_equipment", [])
    for u in xeq:
        details["xray_units"].append(u.get("entity_label") or "Pesawat Sinar-X")

    # Document count
    udm = res.get("documents", {})
    details["total_docs"] = sum(len(flist) for flist in udm.values()) if udm else 0

    return details


def _collect_all_findings(res):
    """Collects critical discrepancies and review warnings across all sections."""
    findings = []
    if not res:
        return findings

    # 1. Compliance issues
    for iss in res.get("compliance", {}).get("issues", []):
        sev = str(iss.get("severity", "WARNING")).upper()
        findings.append({
            "section": "Kepatuhan Regulasi",
            "severity": "KRITIS" if "CRITICAL" in sev or "KRITIS" in sev else "PERINGATAN",
            "title": iss.get("rule_name", "Pemeriksaan Regulasi"),
            "target": iss.get("affected_entity") or "Umum",
            "description": iss.get("description", ""),
            "recommendation": iss.get("recommendation", "Periksa dokumen fisik atau mintakan dokumen pendukung."),
        })

    # 2. Cross-check discrepancies
    rep = res.get("cross_check_report", {})
    def inspect_fields(sec_name, entity_label, fields_dict):
        for fk, fv in fields_dict.items():
            st_clean = _clean_status_str(fv.get("status", ""))
            if st_clean in {"TIDAK SESUAI", "PERLU REVIEW", "WARNING"}:
                flabel = fv.get("field_label") or fk.replace("_", " ").title()
                disc = fv.get("discrepancies", [])
                action_text = "; ".join(disc) if disc else "Bandingkan nilai field antar berkas terkait."
                findings.append({
                    "section": sec_name,
                    "severity": "KRITIS" if st_clean == "TIDAK SESUAI" else "PERINGATAN",
                    "title": f"{flabel} ({sec_name})",
                    "target": entity_label,
                    "description": fv.get("reason") or f"Perbedaan nilai ditemukan pada {flabel}.",
                    "recommendation": action_text,
                })

    if "facility" in rep:
        inspect_fields("Fasilitas & Instansi", "Instansi", rep["facility"].get("fields", {}))

    for p in rep.get("personnel", []):
        inspect_fields("Personel Medis", p.get("entity_label", "Personel"), p.get("fields", {}))

    for p in rep.get("ppr", []):
        inspect_fields("Petugas Proteksi Radiasi", p.get("entity_label", "PPR"), p.get("fields", {}))

    for u in rep.get("xray_equipment", []):
        inspect_fields("Pesawat Sinar-X", u.get("entity_label", "Unit"), u.get("fields", {}))

    for t in rep.get("xray_tubes", []):
        inspect_fields("Tabung Sinar-X", t.get("entity_label", "Tabung"), t.get("fields", {}))

    return findings


# ═══════════════════════════════════════════════════════════════════
# DATABASE & APPLICATION STATE
# ═══════════════════════════════════════════════════════════════════
db = Database(DB_PATH)
past_runs = db.list_runs(limit=30)


@st.cache_data(show_spinner=False)
def _get_run_summary_label(run_id):
    try:
        r_data = db.get_run(run_id)
        if not r_data:
            return run_id
        dtls = _extract_applicant_details(r_data)
        hname = dtls["hospital_name"]
        if len(hname) > 30:
            hname = hname[:27] + "..."
        cd = r_data.get("created_at", "")
        t_str = cd[5:16].replace("T", " ") if cd else ""
        cnt = dtls["total_docs"]
        return f"🏥 {hname} · {cnt} Berkas ({t_str})"
    except Exception:
        return run_id


run_options = [r[0] for r in past_runs]
run_labels = {r_id: _get_run_summary_label(r_id) for r_id in run_options}

if past_runs and "latest_result" not in st.session_state:
    try:
        st.session_state["latest_result"] = db.get_run(past_runs[0][0])
    except Exception:
        pass


@st.cache_data(show_spinner=False)
def _cached_classify_document(filename, file_size, head_bytes, file_bytes):
    return classify_document(filename, file_bytes)


def save_uploaded(uploaded_file, directory, doc_type, index):
    suffix = Path(uploaded_file.name).suffix.lower()
    path = directory / f"{doc_type}_{index}{suffix}"
    path.write_bytes(uploaded_file.getbuffer())
    return path


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION & UPLOAD
# ═══════════════════════════════════════════════════════════════════
with st.sidebar:
    render_html("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
        <div style="font-size:2rem; line-height:1;">⚛️</div>
        <div>
            <div style="font-size:1.15rem; font-weight:800; color:#f8fafc; letter-spacing:-0.02em;">BAPETEN</div>
            <div style="font-size:0.75rem; color:#38bdf8; font-weight:600;">VERIFIKASI DOKUMEN PERIZINAN</div>
        </div>
    </div>
    """)
    st.caption("Sistem Verifikasi & Cross-Check Izin Pemanfaatan Radiasi Pengion.")
    render_html("<hr style='margin:10px 0; border-color:rgba(255,255,255,0.08);'>")

    # 1. Past Runs Selector
    if past_runs:
        st.markdown("##### 📜 Riwayat Uji Dokumen")
        curr_id = st.session_state.get("latest_result", {}).get("run_id")
        def_idx = run_options.index(curr_id) if curr_id in run_options else 0
        selected_run_id = st.selectbox(
            "Pilih Batch",
            options=run_options,
            index=def_idx,
            format_func=lambda rid: run_labels.get(rid, rid),
            key="sb_run_selector",
            label_visibility="collapsed",
        )
        if curr_id != selected_run_id:
            loaded_run = db.get_run(selected_run_id)
            if loaded_run:
                st.session_state["latest_result"] = loaded_run
                st.rerun()

        render_html("<hr style='margin:10px 0; border-color:rgba(255,255,255,0.08);'>")

    # 2. Upload Area
    st.markdown("##### 📂 Uji Batch Baru")
    upload_mode = st.radio("Mode Unggah", ["⚡ Batch Cepat (Auto-Detect)", "📁 Manual per Kategori"], index=0, label_visibility="collapsed")

    upload_map = {k: [] for k in DOCUMENT_TYPES}
    doc_names = {k: v["name"] for k, v in DOCUMENT_TYPES.items()}
    doc_keys = list(DOCUMENT_TYPES.keys())

    if "Batch" in upload_mode:
        batch_files = st.file_uploader(
            "Seret semua berkas PDF / Gambar permohonan",
            type=["pdf", "jpg", "jpeg", "png", "bmp", "webp"],
            accept_multiple_files=True,
            key="batch_uploader",
        )
        if batch_files:
            st.caption(f"📁 {len(batch_files)} berkas dipilih")
            for idx, file in enumerate(batch_files):
                fbytes = file.getvalue()
                detected_type, reason = _cached_classify_document(file.name, file.size, fbytes[:512], fbytes)
                is_conf = reason != "Default"
                icon = "✅" if is_conf else "⚠️"
                with st.expander(f"{icon} {file.name[:25]}", expanded=not is_conf):
                    chosen = st.multiselect(
                        "Kategori Dokumen",
                        options=doc_keys,
                        default=[detected_type] if detected_type in doc_keys else [],
                        format_func=lambda k: doc_names[k],
                        key=f"sb_up_{idx}_{file.name}",
                        label_visibility="collapsed",
                    )
                for ct in chosen:
                    upload_map[ct].append(file)
            active_cat = sum(1 for v in upload_map.values() if v)
            st.info(f"📋 {active_cat} dari {len(doc_keys)} jenis dokumen terdeteksi.")
    else:
        for doc_type, meta in DOCUMENT_TYPES.items():
            exts = ["pdf"] if meta["kind"] == "pdf" else ["jpg", "jpeg", "png", "bmp", "webp", "pdf"]
            up_files = st.file_uploader(meta["name"], type=exts, accept_multiple_files=True, key=f"sb_manual_{doc_type}")
            if up_files:
                upload_map[doc_type].extend(up_files)

    render_html("<div style='height:8px;'></div>")
    process_btn = st.button("🚀 Proses Verifikasi Berkas", type="primary", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# EXECUTE EXTRACTION PIPELINE
# ═══════════════════════════════════════════════════════════════════
if process_btn:
    if not any(upload_map.values()):
        st.error("Silakan unggah setidaknya 1 berkas permohonan.")
        st.stop()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_dir = Path(temp_dir)
        inputs, file_display = {}, {}
        for doc_type, files in upload_map.items():
            if not files:
                continue
            paths = []
            for idx, uploaded in enumerate(files, start=1):
                paths.append(save_uploaded(uploaded, temp_dir, doc_type, idx))
            inputs[doc_type] = paths
            file_display[doc_type] = [f.name for f in files]

        try:
            status_box = st.status("Memproses verifikasi dokumen...", expanded=True)
            p_bar = st.progress(0)

            def on_prog(doc_type, filename, current, total):
                pct = int((current / total) * 100) if total > 0 else 100
                p_bar.progress(pct)
                status_box.update(label=f"Ekstraksi & Analisis ({current}/{total}): {filename}")

            with status_box:
                st.write("Menjalankan OCR cerdas, ekstraksi entitas, dan validasi silang...")
                result_obj = execute_run(inputs, on_progress=on_prog)
                status_box.update(label="✅ Verifikasi Selesai!", state="complete", expanded=False)

            result_obj["file_display"] = file_display
            db.save_run_generic(result_obj)
            st.session_state["latest_result"] = result_obj
            st.rerun()
        except Exception as err:
            st.exception(err)


# ═══════════════════════════════════════════════════════════════════
# MAIN CONTENT AREA
# ═══════════════════════════════════════════════════════════════════
active_run = st.session_state.get("latest_result")

if active_run:
    app_details = _extract_applicant_details(active_run)
    all_findings = _collect_all_findings(active_run)
    crit_count = sum(1 for f in all_findings if f["severity"] == "KRITIS")
    warn_count = sum(1 for f in all_findings if f["severity"] == "PERINGATAN")

    summary_stats = active_run.get("summary", {})
    cnt_sesuai = summary_stats.get("sesuai", summary_stats.get("SESUAI", 0))
    cnt_review = summary_stats.get("perlu_review", summary_stats.get("PERLU REVIEW", 0))
    cnt_tidak_sesuai = summary_stats.get("tidak_sesuai", summary_stats.get("TIDAK SESUAI", 0))
    cnt_tidak_ditemukan = summary_stats.get("tidak_ditemukan", summary_stats.get("TIDAK DITEMUKAN", 0))
    total_checked = summary_stats.get("total_fields_checked", cnt_sesuai + cnt_review + cnt_tidak_sesuai + cnt_tidak_ditemukan)

    match_pct = (cnt_sesuai / total_checked * 100) if total_checked > 0 else 0

    # ── 1. Top Header (Removed BALIS and Sistem Audit) ──
    render_html(f"""
    <div class="inst-header">
        <div class="inst-title-area">
            <div class="inst-logo-badge">⚛️</div>
            <div>
                <h1 class="inst-title">BAPETEN · VERIFIKASI KONSISTENSI DOKUMEN PERIZINAN</h1>
                <div class="inst-sub">Direktorat Perizinan Fasilitas Radiasi dan Zat Radioaktif</div>
            </div>
        </div>
        <div style="text-align:right;">
            <span style="background:rgba(56, 189, 248, 0.15); color:#38bdf8; font-weight:700; font-size:0.75rem; padding:0.35rem 0.8rem; border-radius:20px; border:1px solid rgba(56, 189, 248, 0.3);">
                Batch: {active_run.get('run_id', 'UNKNOWN')[:12]}
            </span>
        </div>
    </div>
    """)

    # ── 2. Applicant Profile Card (Executive Context) ──
    render_html(f"""
    <div class="applicant-card">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
                <span style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em; color:#38bdf8; font-weight:700;">
                    Profil Pemohon & Objek Izin
                </span>
                <div style="font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:0.2rem;">
                    🏥 {app_details['hospital_name']}
                </div>
                <div style="font-size:0.85rem; color:#94a3b8; margin-top:0.3rem;">
                    📍 {app_details['hospital_address']}
                </div>
            </div>
            <div style="text-align:right;">
                <span style="font-size:0.75rem; color:#64748b;">Jumlah Berkas Diuji</span>
                <div style="font-size:1.3rem; font-weight:800; color:#38bdf8;">
                    {app_details['total_docs']} Berkas PDF
                </div>
            </div>
        </div>
    </div>
    """)

    # ── 3. Executive Decision Verdict Callout ──
    if crit_count > 0:
        vb_class = "vb-fail"
        vb_icon = "🚨"
        vb_title = f"REKOMENDASI: PERLU REVISI PEMOHON ({crit_count} KETIDAKSESUAIAN KRITIS)"
        vb_desc = f"Ditemukan {crit_count} ketidaksesuaian nilai antar-dokumen yang menjadi syarat utama perizinan. Evaluator disarankan meminta klarifikasi atau perbaikan dokumen sebelum persetujuan diterbitkan."
    elif warn_count > 0:
        vb_class = "vb-warn"
        vb_icon = "⚠️"
        vb_title = f"REKOMENDASI: DAPAT DIPROSES DENGAN CATATAN ({warn_count} PERLU KONFIRMASI)"
        vb_desc = f"Seluruh data utama identitas dan peralatan sinkron. Terdapat {warn_count} catatan administratif atau variasi penulisan sekunder yang memerlukan konfirmasi evaluator."
    else:
        vb_class = "vb-pass"
        vb_icon = "✅"
        vb_title = "REKOMENDASI: MEMENUHI SYARAT (100% SINKRON & VALID)"
        vb_desc = "Seluruh dokumen permohonan, spesifikasi alat, identitas instansi, dan petugas proteksi radiasi dinyatakan konsisten tanpa temuan ketidaksesuaian."

    render_html(f"""
    <div class="verdict-box {vb_class}">
        <div class="vb-icon">{vb_icon}</div>
        <div class="vb-content">
            <h3>{vb_title}</h3>
            <p>{vb_desc}</p>
        </div>
    </div>
    """)

    # ── 4. Key Metric KPI Strip ──
    render_html(f"""
    <div class="kpi-grid">
        <div class="kpi-card kpi-green">
            <div class="kpi-num">{cnt_sesuai}</div>
            <div class="kpi-label">Field Sesuai</div>
            <div class="kpi-desc">{match_pct:.0f}% konsistensi dokumen</div>
        </div>
        <div class="kpi-card kpi-amber">
            <div class="kpi-num">{cnt_review}</div>
            <div class="kpi-label">Perlu Review</div>
            <div class="kpi-desc">Variasi teks / konfirmasi</div>
        </div>
        <div class="kpi-card kpi-rose">
            <div class="kpi-num">{cnt_tidak_sesuai}</div>
            <div class="kpi-label">Tidak Sesuai</div>
            <div class="kpi-desc">Perbedaan nilai antar-dokumen</div>
        </div>
        <div class="kpi-card kpi-slate">
            <div class="kpi-num">{cnt_tidak_ditemukan}</div>
            <div class="kpi-label">Belum Terdeteksi</div>
            <div class="kpi-desc">Field opsional / tidak ada</div>
        </div>
    </div>
    """)

    personnel_count = len(active_run.get("cross_check_report", {}).get("personnel", [])) or 1
    # ── 5. Main Presentation Tabs ──
    tab_temuan, tab_instansi, tab_personel, tab_pesawat, tab_checklist, tab_audit = st.tabs([
        f"🚨  Temuan & Catatan ({len(all_findings)})",
        "🏢  Instansi & Fasilitas",
        f"👨‍⚕️  Petugas & PPR ({personnel_count})",
        f"⚡  Pesawat Sinar-X ({len(app_details['xray_units']) or 1})",
        "📋  Kelengkapan Dokumen",
        "🔍  Detail Ekstraksi OCR",
    ])

    # ─────────────────────────────────────────────────────────────
    # TAB 1: TEMUAN & CATATAN (ACTIONABLE BRIEFING)
    # ─────────────────────────────────────────────────────────────
    with tab_temuan:
        render_html("""
        <div style="margin-bottom:1rem;">
            <h3 style="margin:0; font-size:1.15rem; font-weight:800;">🚨 Ikhtisar Temuan & Rekomendasi Evaluator</h3>
            <p style="margin:0.2rem 0 0 0; font-size:0.82rem; color:#94a3b8;">
                Daftar lengkap ketidaksesuaian data, masa berlaku, dan catatan teknis yang perlu diperiksa atau diklarifikasi.
            </p>
        </div>
        """)

        filtered_findings = all_findings

        if not filtered_findings:
            render_html("""
            <div style="background:rgba(16, 185, 129, 0.08); border:1px solid rgba(16, 185, 129, 0.2); border-radius:12px; padding:2rem; text-align:center;">
                <div style="font-size:2.5rem; margin-bottom:0.5rem;">🎉</div>
                <div style="font-size:1.1rem; font-weight:700; color:#34d399;">Tidak Ada Temuan Bermasalah</div>
                <div style="font-size:0.85rem; color:#94a3b8; margin-top:0.3rem;">Semua dokumen dan data yang diperiksa telah sinkron dan memenuhi regulasi BAPETEN.</div>
            </div>
            """)
        else:
            for item in filtered_findings:
                is_crit = item["severity"] == "KRITIS"
                f_card_cls = "fc-critical" if is_crit else "fc-warning"
                f_badge_cls = "badge-critical" if is_crit else "badge-warning"
                badge_text = "KRITIS / DISCREPANCY" if is_crit else "PERLU REVIEW / CATATAN"

                render_html(f"""
                <div class="finding-card {f_card_cls}">
                    <div class="fc-header">
                        <div class="fc-title">📌 {item['title']} <span style="font-weight:400; color:#64748b; font-size:0.8rem;">· {item['target']}</span></div>
                        <span class="fc-badge {f_badge_cls}">{badge_text}</span>
                    </div>
                    <div class="fc-body">
                        {item['description']}
                    </div>
                    <div class="fc-action">
                        💡 <strong>Saran Tindakan:</strong> {item['recommendation']}
                    </div>
                </div>
                """)

    # ─────────────────────────────────────────────────────────────
    # TAB 2: INSTANSI & FASILITAS
    # ─────────────────────────────────────────────────────────────
    with tab_instansi:
        render_html("""
        <div style="margin-bottom:1rem;">
            <h3 style="margin:0; font-size:1.15rem; font-weight:800;">🏢 Verifikasi Identitas Fasilitas & Instansi</h3>
            <p style="margin:0.2rem 0 0 0; font-size:0.82rem; color:#94a3b8;">
                Perbandingan konsistensi nama dan alamat rumah sakit / instansi pemohon di seluruh dokumen yang diunggah.
            </p>
        </div>
        """)

        fac_rep = active_run.get("cross_check_report", {}).get("facility", {}).get("fields", {})
        docs_map = active_run.get("documents", {})
        
        # 1. Nama Instansi
        pname_field = fac_rep.get("project_name", {})
        _render_parameter_card("Field Identitas", "Nama Rumah Sakit / Instansi Pemohon", pname_field, docs_map)

        # 2. Alamat Instansi
        paddr_field = fac_rep.get("project_address", {})
        _render_parameter_card("Field Identitas", "Alamat Rumah Sakit / Lokasi Fasilitas", paddr_field, docs_map)

    # ─────────────────────────────────────────────────────────────
    # TAB 3: PPR & PERSONEL
    # ─────────────────────────────────────────────────────────────
    with tab_personel:
        docs_map = active_run.get("documents", {})
        personnel_list = active_run.get("cross_check_report", {}).get("personnel", [])

        # Data PPR dari dokumen SIB & Sprint
        sprint_docs = active_run.get("extractions", {}).get("sprint", [])
        sib_docs = active_run.get("extractions", {}).get("sib", [])
        sprint_doc_main = sprint_docs[0] if sprint_docs else None
        sib_doc_main = sib_docs[0] if sib_docs else None

        sprint_fields = sprint_doc_main.get("fields", {}) if sprint_doc_main else {}
        sib_fields = sib_doc_main.get("fields", {}) if sib_doc_main else {}

        ppr_display_name = (
            sprint_fields.get("kepada", {}).get("value") or
            sprint_fields.get("ppr_name", {}).get("value") or
            sib_fields.get("ppr_name", {}).get("value") or
            app_details["ppr_name"]
        )
        ppr_sib_date = sib_fields.get("valid_until", {}).get("value") or app_details["ppr_sib_valid"]
        sprint_approval = sprint_fields.get("pengesahan", {}).get("value") or sprint_fields.get("approval", {}).get("value") or "Pimpinan Fasilitas"

        # Filter PPR agar TIDAK duplikat masuk ke daftar 'Data Petugas Lainnya'
        def _is_ppr_person(p):
            pf = p.get("fields", {})
            for s in pf.get("profession", {}).get("sources", []):
                val = str(s.get("value") or "").lower()
                if "ppr" in val or "proteksi" in val:
                    return True
            p_clean = ""
            for s in pf.get("person_name", {}).get("sources", []):
                if s.get("value"):
                    p_clean = str(s.get("value")).strip()
                    break
            if not p_clean:
                p_clean = p.get("entity_label", "")
            if ppr_display_name and p_clean and fuzz.ratio(p_clean.lower(), ppr_display_name.lower()) >= 80:
                return True
            return False

        other_personnel = [p for p in personnel_list if not _is_ppr_person(p)]

        # ─────────────────────────────────────────────────────────────
        # 1. DATA PETUGAS LAINNYA YANG MENANGANI SUMBER RADIASI PENGION
        # ─────────────────────────────────────────────────────────────
        render_html("""
        <div style="margin-bottom:1.5rem;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:#38bdf8;">
                    Bagian 1
                </span>
            </div>
            <h3 style="margin:0.2rem 0 0 0; font-size:1.25rem; font-weight:800; color:#38bdf8;">
                1. Data Petugas Lainnya yang Menangani Sumber Radiasi Pengion
            </h3>
            <p style="margin:0.25rem 0 0 0; font-size:0.83rem; color:#94a3b8;">
                Verifikasi konsistensi nama, kualifikasi/profesi, dan Surat Izin Praktik (SIP) dokter spesialis radiologi serta staf radiografer.
            </p>
        </div>
        """)

        if other_personnel:
            for idx, p in enumerate(other_personnel, start=1):
                plabel = p.get("entity_label") or f"Personel #{idx}"
                pstatus = _clean_status_str(p.get("status") or "SESUAI")
                pf = p.get("fields", {})

                p_role = "Tenaga Medis"
                for s in pf.get("profession", {}).get("sources", []):
                    if s.get("value"):
                        p_role = str(s.get("value"))
                        break

                raw_name = plabel
                if ":" in raw_name:
                    raw_name = raw_name.split(":", 1)[1]
                if "(" in raw_name:
                    raw_name = raw_name.split("(", 1)[0]
                p_clean_name = raw_name.strip() or f"Personel #{idx}"

                # Personnel Entity Header Banner
                render_html(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; background:#111c35; border:1px solid rgba(56, 189, 248, 0.22); border-radius:12px; padding:0.9rem 1.4rem; margin:1.6rem 0 1rem 0;">
                    <div>
                        <span style="font-size:0.72rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">
                            Personel #{idx} · {p_role}
                        </span>
                        <div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin-top:2px;">
                            👨‍⚕️ {p_clean_name}
                        </div>
                    </div>
                    <div>{_render_pill(pstatus)}</div>
                </div>
                """)

                # 1. Parameter Nama Personel (clean title without duplicate name suffix)
                if "person_name" in pf:
                    _render_parameter_card(
                        f"Field Identitas Personel #{idx}",
                        "Nama Personel",
                        pf["person_name"],
                        docs_map,
                    )

                # 2. Parameter Profesi / Kualifikasi (clean title without duplicate name suffix)
                if "profession" in pf and pf["profession"].get("sources"):
                    _render_parameter_card(
                        f"Kualifikasi Personel #{idx}",
                        "Kualifikasi / Profesi",
                        pf["profession"],
                        docs_map,
                    )

                # 3. Parameter SIP: gabungkan Masa Berlaku dan Tempat Praktik dalam 1 kartu terpadu agar tidak terlihat duplikat
                has_v = "valid_until" in pf and bool(pf["valid_until"].get("sources"))
                has_l = "practice_location" in pf and bool(pf["practice_location"].get("sources"))
                if has_v and has_l:
                    _render_sip_consolidated_card(idx, pf.get("valid_until"), pf.get("practice_location"), docs_map)
                elif has_v:
                    _render_parameter_card(
                        f"Kredensial Izin Personel #{idx}",
                        "Masa Berlaku Izin Praktik (SIP)",
                        pf["valid_until"],
                        docs_map,
                    )
                elif has_l:
                    _render_parameter_card(
                        f"Kredensial Lokasi Personel #{idx}",
                        "Kesesuaian Tempat Praktik (SIP)",
                        pf["practice_location"],
                        docs_map,
                    )
        else:
            st.info("Tidak ada daftar petugas lainnya yang terdaftar.")

        # ─────────────────────────────────────────────────────────────
        # 2. DATA PETUGAS PROTEKSI RADIASI (PPR)
        # ─────────────────────────────────────────────────────────────
        render_html("""
        <div style="margin:2.8rem 0 1.2rem 0; padding-top:1.5rem; border-top:1px solid rgba(168, 85, 247, 0.3);">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:#a855f7;">
                    Bagian 2
                </span>
            </div>
            <h3 style="margin:0.2rem 0 0 0; font-size:1.25rem; font-weight:800; color:#c084fc;">
                2. Data Petugas Proteksi Radiasi (PPR)
            </h3>
            <p style="margin:0.25rem 0 0 0; font-size:0.83rem; color:#94a3b8;">
                Verifikasi keabsahan Surat Izin Bekerja (SIB) BAPETEN dan Surat Perintah (Sprint) penunjukan resmi dari pimpinan fasilitas.
            </p>
        </div>
        """)

        col_ppr_info, col_ppr_stamp = st.columns([3, 2])
        with col_ppr_info:
            render_html(f"""
            <div class="spotlight-card">
                <div class="spotlight-header">
                    <div class="spotlight-avatar">🛡️</div>
                    <div class="spotlight-info">
                        <span style="font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#a855f7;">
                            Pejabat Wajib Regulasi
                        </span>
                        <h4>{ppr_display_name}</h4>
                        <p>Petugas Proteksi Radiasi (PPR) Medik</p>
                    </div>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:0.8rem;">
                    <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border-subtle); border-radius:10px; padding:0.8rem;">
                        <div style="font-size:0.7rem; color:#64748b; font-weight:700;">SURAT IZIN BEKERJA (SIB)</div>
                        <div style="font-size:0.95rem; font-weight:700; color:#34d399; margin-top:0.2rem;">🟢 AKTIF</div>
                        <div style="font-size:0.78rem; color:#cbd5e1; margin-top:0.2rem;">Berlaku s/d: <strong>{ppr_sib_date}</strong></div>
                    </div>
                    <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border-subtle); border-radius:10px; padding:0.8rem;">
                        <div style="font-size:0.7rem; color:#64748b; font-weight:700;">SURAT PERINTAH (SPRINT)</div>
                        <div style="font-size:0.95rem; font-weight:700; color:#38bdf8; margin-top:0.2rem;">🟢 SAH DITERBITKAN</div>
                        <div style="font-size:0.78rem; color:#cbd5e1; margin-top:0.2rem;">Oleh: <strong>{sprint_approval[:25]}</strong></div>
                    </div>
                </div>
            </div>
            """)

        with col_ppr_stamp:
            sig_crop = get_sprint_signature_preview(sprint_doc_main) if sprint_doc_main else None
            if sig_crop and str(sig_crop).startswith("data:image"):
                render_html(f"""
                <div style="background:#0f172a; border:1px solid var(--border-subtle); border-radius:12px; padding:1rem; text-align:center;">
                    <div style="font-size:0.8rem; font-weight:700; color:#a855f7; margin-bottom:8px;">✍️ Bukti Tanda Tangan & Stempel Basah (Sprint)</div>
                    <img src="{sig_crop}" style="max-width:100%; max-height:160px; border-radius:8px; border:1px solid rgba(255,255,255,0.1);" />
                    <div style="font-size:0.72rem; color:#64748b; margin-top:6px;">Tanda tangan pejabat pengesah & stempel resmi RS</div>
                </div>
                """)
            elif sig_crop and Path(str(sig_crop)).exists():
                render_html("<div style='font-size:0.8rem; font-weight:700; color:#a855f7; margin-bottom:4px;'>✍️ Bukti Tanda Tangan & Stempel Basah (Sprint)</div>")
                st.image(str(sig_crop), caption="Tanda tangan pejabat pengesah & stempel resmi RS", width=360)
            else:
                render_html(f"""
                <div style="background:#0f172a; border:1px solid var(--border-subtle); border-radius:12px; padding:1.2rem; text-align:center;">
                    <div style="font-size:1.8rem; margin-bottom:0.4rem;">✍️</div>
                    <div style="font-size:0.9rem; font-weight:700; color:#f8fafc;">Surat Perintah (Sprint) Fisik</div>
                    <div style="font-size:0.78rem; color:#94a3b8; margin-top:0.2rem;">
                        Pengesahan: <strong>{sprint_approval[:30]}</strong><br>
                        Tanda tangan & stempel fisik diverifikasi dari berkas asli.
                    </div>
                </div>
                """)

        # Perbandingan Parameter Kredensial PPR Antar Dokumen
        ppr_rep_list = active_run.get("cross_check_report", {}).get("ppr", [])
        if ppr_rep_list:
            for ppr_item in ppr_rep_list:
                ppr_f = ppr_item.get("fields", {})
                if "ppr_name" in ppr_f and ppr_f["ppr_name"].get("sources"):
                    _render_parameter_card(
                        "Field Identitas PPR",
                        "Nama Petugas Proteksi Radiasi (PPR)",
                        ppr_f["ppr_name"],
                        docs_map,
                    )
                if "valid_until" in ppr_f and ppr_f["valid_until"].get("sources"):
                    _render_parameter_card(
                        "Kredensial SIB",
                        "Masa Berlaku Surat Izin Bekerja (SIB)",
                        ppr_f["valid_until"],
                        docs_map,
                    )

    # ─────────────────────────────────────────────────────────────
    # TAB 4: PESAWAT SINAR-X
    # ─────────────────────────────────────────────────────────────
    with tab_pesawat:
        render_html("""
        <div style="margin-bottom:1rem;">
            <h3 style="margin:0; font-size:1.15rem; font-weight:800;">⚡ Spesifikasi Pesawat & Tabung Sinar-X</h3>
            <p style="margin:0.2rem 0 0 0; font-size:0.82rem; color:#94a3b8;">
                Verifikasi silang nomor seri, merk, dan model pesawat serta tabung sinar-X antar izin impor, formulir, dan uji fungsi.
            </p>
        </div>
        """)

        x_eq_list = active_run.get("cross_check_report", {}).get("xray_equipment", [])
        x_tb_list = active_run.get("cross_check_report", {}).get("xray_tubes", [])
        docs_map = active_run.get("documents", {})

        if not x_eq_list and not x_tb_list:
            st.info("Data peralatan sinar-X tidak ditemukan pada hasil ekstraksi.")
        else:
            # ── A. Pesawat Sinar-X Units ──
            for idx, eq in enumerate(x_eq_list, start=1):
                eq_label = eq.get("entity_label") or f"Pesawat Sinar-X Unit #{idx}"
                eq_status = _clean_status_str(eq.get("status") or "SESUAI")
                eq_fields = eq.get("fields", {})

                render_html(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; background:#131d31; border:1px solid rgba(56, 189, 248, 0.25); border-radius:12px; padding:0.9rem 1.4rem; margin:1.2rem 0 1rem 0;">
                    <div>
                        <span style="font-size:0.72rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">Pesawat Sinar-X</span>
                        <div style="font-size:1.15rem; font-weight:800; color:#f8fafc;">⚡ {eq_label}</div>
                    </div>
                    <div>{_render_pill(eq_status)}</div>
                </div>
                """)

                param_titles = {
                    "unit_brand": "Merk Pesawat Sinar-X (Brand)",
                    "unit_type": "Tipe / Model Pesawat Sinar-X (Type)",
                    "unit_serial_number": "Nomor Seri Pesawat Sinar-X (Serial Number)",
                }
                order = ["unit_brand", "unit_type", "unit_serial_number"] + [k for k in eq_fields if k not in ["unit_brand", "unit_type", "unit_serial_number"]]
                for fk in order:
                    if fk in eq_fields:
                        fv = eq_fields[fk]
                        ftitle = param_titles.get(fk, fv.get("field_label") or fk.replace("_", " ").title())
                        _render_parameter_card("Parameter Pesawat Sinar-X", ftitle, fv, docs_map)

            # ── B. Tabung Sinar-X Tubes ──
            for idx, tb in enumerate(x_tb_list, start=1):
                tb_label = tb.get("entity_label") or f"Tabung Sinar-X #{idx}"
                tb_status = _clean_status_str(tb.get("status") or "SESUAI")
                tb_fields = tb.get("fields", {})

                render_html(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; background:#19142b; border:1px solid rgba(168, 85, 247, 0.25); border-radius:12px; padding:0.9rem 1.4rem; margin:1.5rem 0 1rem 0;">
                    <div>
                        <span style="font-size:0.72rem; text-transform:uppercase; color:#a855f7; font-weight:700;">Tabung Sinar-X (X-Ray Tube)</span>
                        <div style="font-size:1.15rem; font-weight:800; color:#f8fafc;">🔬 {tb_label}</div>
                    </div>
                    <div>{_render_pill(tb_status)}</div>
                </div>
                """)

                tb_param_titles = {
                    "tube_brand": "Merk Tabung Sinar-X (Tube Brand)",
                    "tube_type": "Tipe / Model Tabung Sinar-X (Tube Model / Type)",
                    "tube_serial_number": "Nomor Seri Tabung Sinar-X (Tube Serial Number)",
                }
                order = ["tube_brand", "tube_type", "tube_serial_number"] + [k for k in tb_fields if k not in ["tube_brand", "tube_type", "tube_serial_number"]]
                for fk in order:
                    if fk in tb_fields:
                        fv = tb_fields[fk]
                        ftitle = tb_param_titles.get(fk, fv.get("field_label") or fk.replace("_", " ").title())
                        _render_parameter_card("Parameter Tabung Sinar-X", ftitle, fv, docs_map)

    # ─────────────────────────────────────────────────────────────
    # TAB 5: KELENGKAPAN DOKUMEN (CHECKLIST)
    # ─────────────────────────────────────────────────────────────
    with tab_checklist:
        render_html(f"""
        <div style="margin-bottom:1rem;">
            <h3 style="margin:0; font-size:1.15rem; font-weight:800;">📋 Checklist {len(DOCUMENT_TYPES)} Dokumen Persyaratan Permohonan</h3>
            <p style="margin:0.2rem 0 0 0; font-size:0.82rem; color:#94a3b8;">
                Standar kelengkapan administrasi berkas izin pemanfaatan radiasi sesuai Peraturan BAPETEN.
            </p>
        </div>
        """)

        udm = active_run.get("documents", {})
        chk_rows = ""
        for idx, (dk, meta) in enumerate(DOCUMENT_TYPES.items(), start=1):
            is_present = dk in udm and len(udm[dk]) > 0
            flist = udm.get(dk, [])
            fn_str = ", ".join(flist) if flist else "—"
            st_pill = '<span class="pill pill-match">✓ Terunggah</span>' if is_present else '<span class="pill pill-missing">○ Belum Ada</span>'

            chk_rows += f"<tr><td style='font-weight:700; color:#64748b;'>#{idx}</td><td style='font-weight:700; color:#f8fafc;'>{meta['name']}</td><td style='font-family:\"JetBrains Mono\", monospace; font-size:0.78rem; color:#94a3b8;'>{fn_str}</td><td>{st_pill}</td></tr>"

        render_html(f"""
        <table class="matrix-table">
            <thead><tr><th>No</th><th>Jenis Dokumen Persyaratan</th><th>Nama File Terunggah</th><th>Status Kelengkapan</th></tr></thead>
            <tbody>{chk_rows}</tbody>
        </table>
        """)

    # ─────────────────────────────────────────────────────────────
    # TAB 6: DETAIL EKSTRAKSI OCR (DEEP DIVE)
    # ─────────────────────────────────────────────────────────────
    with tab_audit:
        render_html("""
        <div style="margin-bottom:1rem;">
            <h3 style="margin:0; font-size:1.15rem; font-weight:800;">🔍 Hasil Ekstraksi Entitas & Nilai Asli OCR</h3>
            <p style="margin:0.2rem 0 0 0; font-size:0.82rem; color:#94a3b8;">
                Inspeksi teknis nilai hasil bacaan engine OCR dan parser field per lembar dokumen.
            </p>
        </div>
        """)

        for doc_type, docs in active_run.get("extractions", {}).items():
            if not docs:
                continue
            dname = DOCUMENT_TYPES.get(doc_type, {}).get("name", doc_type)
            with st.expander(f"📄 {dname} ({len(docs)} berkas)", expanded=False):
                for d_idx, doc in enumerate(docs, start=1):
                    fn = doc.get("file_name", f"file_{d_idx}")
                    st.markdown(f"**Berkas: `{fn}`**")
                    f_dict = doc.get("fields", {})
                    scalar_list = []
                    expected_order = DOCUMENT_FIELDS.get(doc_type, list(f_dict.keys()))
                    for fk in expected_order:
                        if fk in ("all_xray_rows", "header", "document_number", "document_date", "xray_data"):
                            continue
                        fitem = f_dict.get(fk, {"value": "-", "page": "-", "method": "not_found"})
                        val = fitem.get("value") if isinstance(fitem, dict) else fitem
                        if isinstance(val, list):
                            if val:
                                val_str = ", ".join(f"{p.get('name', '')} ({p.get('role', '')})".strip() for p in val if isinstance(p, dict) and p.get('name'))
                                val_str = val_str or "-"
                            else:
                                val_str = "-"
                        elif isinstance(val, dict):
                            parts = [f"{k}: {v}" for k, v in val.items() if v and str(v).strip() not in ("-", "—") and k != "page"]
                            val_str = " | ".join(parts) if parts else "-"
                        else:
                            val_str = str(val or "-").strip() or "-"

                        scalar_list.append({
                            "Field": fk,
                            "Nilai Ekstraksi": val_str,
                            "Halaman": fitem.get("page", "-") if isinstance(fitem, dict) else "-",
                            "Metode": fitem.get("method", "-") if isinstance(fitem, dict) else "-",
                        })
                    if scalar_list:
                        st.dataframe(pd.DataFrame(scalar_list), use_container_width=True, hide_index=True)

        st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)
        st.download_button(
            "📥 Unduh Laporan JSON",
            data=json.dumps(active_run, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            file_name=f"BAPETEN_Verifikasi_{active_run.get('run_id')}.json",
            mime="application/json",
            use_container_width=True,
        )

else:
    # ── Empty State ──
    render_html("""
    <div style="background:#0f172a; border:1px solid var(--border-subtle); border-radius:16px; padding:4rem 2rem; text-align:center; margin-top:2rem;">
        <div style="font-size:3.5rem; margin-bottom:1rem; opacity:0.6;">📂</div>
        <div style="font-size:1.3rem; font-weight:800; color:#f8fafc; margin-bottom:0.4rem;">Belum Ada Berkas yang Diperiksa</div>
        <div style="font-size:0.88rem; color:#94a3b8; max-width:480px; margin:0 auto 1.5rem auto; line-height:1.6;">
            Pilih riwayat pengujian dari menu sidebar, atau unggah batch berkas permohonan baru untuk memulai verifikasi otomatis.
        </div>
    </div>
    """)
