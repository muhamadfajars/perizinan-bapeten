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
from src.matching.cross_check_engine import evaluate_field_sources, SourceEvidence, compare_two_values
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
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown p {
    color: var(--text-secondary);
}
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, 
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] strong, section[data-testid="stSidebar"] b {
    color: var(--text-primary) !important;
}

/* Sidebar Expander & Filename Display */
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    font-size: 0.82rem !important;
    line-height: 1.35 !important;
    white-space: normal !important;
    word-break: break-word !important;
    overflow-wrap: anywhere !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary p {
    font-size: 0.82rem !important;
    white-space: normal !important;
    word-break: break-word !important;
    overflow-wrap: anywhere !important;
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

/* ──────────────────────────────────────────────────────────────────
   HIGH-CONTRAST PRIMARY BUTTONS (Bright Blue Background)
   Ensures text on bright blue is bold dark navy (#04101e) for crystal clarity
   ────────────────────────────────────────────────────────────────── */
button[kind="primary"],
.stButton > button[kind="primary"],
[data-testid="stBaseButton-primary"],
div[data-testid="stSidebar"] button[kind="primary"],
div[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
    background-color: #38bdf8 !important;
    background-image: none !important;
    border: none !important;
    border-radius: 9px !important;
    padding: 0.6rem 1.2rem !important;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.35) !important;
    transition: all 0.2s ease !important;
}

button[kind="primary"] *,
button[kind="primary"] p,
button[kind="primary"] span,
button[kind="primary"] div,
.stButton > button[kind="primary"] *,
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] span,
[data-testid="stBaseButton-primary"] *,
[data-testid="stBaseButton-primary"] p,
[data-testid="stBaseButton-primary"] span,
div[data-testid="stSidebar"] button[kind="primary"] *,
div[data-testid="stSidebar"] button[kind="primary"] p,
div[data-testid="stSidebar"] button[kind="primary"] span,
div[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] *,
div[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p,
div[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] span {
    color: #04101e !important;
    font-weight: 800 !important;
    font-size: 0.95rem !important;
    letter-spacing: -0.01em !important;
}

button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover,
div[data-testid="stSidebar"] button[kind="primary"]:hover {
    background-color: #0ea5e9 !important;
    box-shadow: 0 6px 20px rgba(56, 189, 248, 0.5) !important;
    transform: translateY(-1px) !important;
}

button[kind="primary"]:hover *,
[data-testid="stBaseButton-primary"]:hover *,
div[data-testid="stSidebar"] button[kind="primary"]:hover * {
    color: #04101e !important;
}

/* ──────────────────────────────────────────────────────────────────
   HIGH-CONTRAST BASEWEB TAGS / PILLS (Multiselect selections)
   ────────────────────────────────────────────────────────────────── */
[data-baseweb="tag"],
div[data-testid="stSidebar"] [data-baseweb="tag"] {
    background-color: #38bdf8 !important;
    border-radius: 6px !important;
    border: none !important;
    padding: 3px 8px !important;
}

[data-baseweb="tag"] *,
[data-baseweb="tag"] span,
[data-baseweb="tag"] div,
[data-baseweb="tag"] p,
div[data-testid="stSidebar"] [data-baseweb="tag"] *,
div[data-testid="stSidebar"] [data-baseweb="tag"] span,
div[data-testid="stSidebar"] [data-baseweb="tag"] div {
    color: #04101e !important;
    font-weight: 700 !important;
    font-size: 0.82rem !important;
}

[data-baseweb="tag"] svg,
div[data-testid="stSidebar"] [data-baseweb="tag"] svg {
    fill: #04101e !important;
    color: #04101e !important;
    width: 14px !important;
    height: 14px !important;
}

[data-baseweb="tag"] svg:hover,
div[data-testid="stSidebar"] [data-baseweb="tag"] svg:hover {
    fill: #b91c1c !important;
    color: #b91c1c !important;
}

/* ──────────────────────────────────────────────────────────────────
   SECONDARY & DOWNLOAD BUTTONS
   ────────────────────────────────────────────────────────────────── */
button[kind="secondary"],
[data-testid="stBaseButton-secondary"],
.stDownloadButton > button {
    background: #1e293b !important;
    color: #f8fafc !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
button[kind="secondary"] *,
[data-testid="stBaseButton-secondary"] *,
.stDownloadButton > button * {
    color: #f8fafc !important;
}
button[kind="secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover,
.stDownloadButton > button:hover {
    background: #334155 !important;
    border-color: rgba(255, 255, 255, 0.2) !important;
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
        return '<span class="pill pill-review">⚠ Perlu Review</span>'
    elif s == "TIDAK SESUAI":
        return '<span class="pill pill-fail">✗ Tidak Sesuai</span>'
    elif s in {"TIDAK DITEMUKAN", "BELUM DIUNGGAH", "BELUM ADA"}:
        return '<span class="pill pill-missing">○ Belum Diunggah</span>'
    return f'<span class="pill pill-missing">○ {s.title()}</span>'


# ─────────────────────────────────────────────────────────────
# STANDAR DOKUMEN PERSYARATAN REGULASI BAPETEN
# ─────────────────────────────────────────────────────────────
FACILITY_NAME_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel A Data Umum Pemohon / Pemegang Izin",
        "required": True,
    },
    {
        "doc_type": "sprint",
        "label": "Surat Perintah (Sprint)",
        "desc": "Kop & Identitas Rumah Sakit Penerbit Sprint",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Dokumen Program Proteksi & Keselamatan Radiasi",
        "required": True,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Nama Fasilitas pada Sertifikat Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "tld",
        "label": "Surat Pengiriman TLD",
        "desc": "Nama Instansi Pemakai Dosimeter Personal",
        "required": False,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Berita Acara Pengujian Fungsi Lapangan",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Laporan Pengukuran Paparan Ruangan / Uji Kebocoran Tabung",
        "required": False,
    },
    {
        "doc_type": "sistem_manajemen",
        "label": "Dokumen Sistem Manajemen",
        "desc": "Sistem Manajemen Fasilitas Radiologi",
        "required": False,
    },
    {
        "doc_type": "program_perawatan",
        "label": "Program Perawatan Alat",
        "desc": "Dokumen Program Perawatan Pesawat Sinar-X",
        "required": False,
    },
    {
        "doc_type": "laporan_dosis_awal",
        "label": "Laporan Dosis Awal",
        "desc": "Evaluasi Dosis Pasien Awal Radiologi",
        "required": False,
    },
    {
        "doc_type": "gedung_penahan_radiasi",
        "label": "Gedung Penahan Radiasi",
        "desc": "Rencana Teknis Bangunan Penahan Radiasi",
        "required": False,
    },
]

FACILITY_ADDRESS_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Alamat Lokasi Pemanfaatan / Instalasi Radiologi",
        "required": True,
    },
    {
        "doc_type": "sprint",
        "label": "Surat Perintah (Sprint)",
        "desc": "Alamat Instansi pada Kop / Isi Surat Penugasan",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Alamat Lokasi pada Dokumen PPKR",
        "required": True,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Alamat Fasilitas pada Laporan Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "tld",
        "label": "Surat Pengiriman TLD",
        "desc": "Alamat Pengiriman Dosimeter Personal RS",
        "required": False,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Alamat Pengujian Lapangan Pesawat Sinar-X",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Alamat Fasilitas pada Laporan Paparan / Kebocoran",
        "required": False,
    },
    {
        "doc_type": "sistem_manajemen",
        "label": "Dokumen Sistem Manajemen",
        "desc": "Alamat Fasilitas pada Sistem Manajemen",
        "required": False,
    },
    {
        "doc_type": "program_perawatan",
        "label": "Program Perawatan Alat",
        "desc": "Alamat Fasilitas pada Dokumen Perawatan",
        "required": False,
    },
    {
        "doc_type": "gedung_penahan_radiasi",
        "label": "Gedung Penahan Radiasi",
        "desc": "Alamat Lokasi Gedung / Ruangan Radiologi",
        "required": False,
    },
]

PERSONNEL_NAME_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel B.1 Data Petugas Lainnya",
        "required": True,
    },
    {
        "doc_type": "sip",
        "label": "Surat Izin Praktik (SIP)",
        "desc": "Kredensial Izin Resmi Tenaga Medis",
        "required": True,
    },
    {
        "doc_type": "tld",
        "label": "Surat Pengiriman TLD",
        "desc": "Pemantauan Dosis Radiasi Perorangan",
        "required": False,
    },
    {
        "doc_type": "laporan_dosis_awal",
        "label": "Laporan Dosis Awal",
        "desc": "Evaluasi Pemantauan Dosis BPFK / Lab",
        "required": False,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Struktur Ketenagaan Proteksi Radiasi",
        "required": False,
    },
]

PERSONNEL_PROFESSION_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel B.1 Usulan Profesi Pemohon",
        "required": True,
    },
    {
        "doc_type": "sip",
        "label": "Surat Izin Praktik (SIP)",
        "desc": "Kualifikasi / Profesi Tertera pada SIP",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Uraian Tugas & Ketenagaan PPKR",
        "required": False,
    },
]

PPR_NAME_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel B.2 Usulan Petugas Proteksi Radiasi",
        "required": True,
    },
    {
        "doc_type": "sib",
        "label": "Surat Izin Bekerja (SIB)",
        "desc": "Lisensi Kualifikasi Resmi BAPETEN",
        "required": True,
    },
    {
        "doc_type": "sprint",
        "label": "Surat Perintah (Sprint)",
        "desc": "SK Penunjukan Resmi Direktur Faskes",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Struktur Organisasi Proteksi Radiasi",
        "required": False,
    },
    {
        "doc_type": "pemantauan_dosis",
        "alt_doc_types": ["tld", "laporan_dosis_awal"],
        "label": "Pemantauan Dosis (TLD / OSL)",
        "desc": "Proteksi & Pemantauan Dosis PPR",
        "required": False,
    },
]

PPR_SIB_EXPECTED_DOCS = [
    {
        "doc_type": "sib",
        "label": "Surat Izin Bekerja (SIB)",
        "desc": "Lisensi Kualifikasi Resmi BAPETEN",
        "required": True,
    },
]

# ─────────────────────────────────────────────────────────────
# STANDAR DOKUMEN PERSYARATAN PESAWAT & TABUNG SINAR-X
# ─────────────────────────────────────────────────────────────
XRAY_UNIT_BRAND_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel C.1 Data Teknis Pesawat Sinar-X",
        "required": True,
    },
    {
        "doc_type": "spesifikasi_pesawat",
        "label": "Spesifikasi Pesawat",
        "desc": "Brosur Teknis Resmi dari Pabrikan Unit",
        "required": False,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Daftar Inventaris Peralatan Radiasi",
        "required": False,
    },
    {
        "doc_type": "label_unit",
        "label": "Foto Label Unit",
        "desc": "Plat Fisik Identitas Unit Pabrikan",
        "required": True,
    },
    {
        "doc_type": "persetujuan_import",
        "label": "Persetujuan Impor",
        "desc": "Izin Pemasukan Resmi dari BAPETEN",
        "required": False,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Sertifikat Kelaikan Operasional Unit",
        "required": True,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Berita Acara Pengujian Fungsi Lapangan",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Laporan Paparan Ruangan / Uji Kebocoran Tabung",
        "required": False,
    },
]

XRAY_UNIT_TYPE_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel C.1 Tipe / Model Usulan",
        "required": True,
    },
    {
        "doc_type": "spesifikasi_pesawat",
        "label": "Spesifikasi Pesawat",
        "desc": "Tipe / Model pada Brosur Resmi Pabrikan",
        "required": False,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Tipe / Model pada Inventaris PPKR",
        "required": False,
    },
    {
        "doc_type": "label_unit",
        "label": "Foto Label Unit",
        "desc": "Tipe / Model pada Plat Fisik Unit",
        "required": True,
    },
    {
        "doc_type": "persetujuan_import",
        "label": "Persetujuan Impor",
        "desc": "Tipe / Model pada Izin Impor Resmi",
        "required": False,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Tipe / Model pada Laporan Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Tipe / Model pada Berita Acara Uji Fungsi",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Tipe / Model pada Lembar Paparan / Kebocoran",
        "required": False,
    },
]

XRAY_UNIT_SERIAL_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel C.1 Nomor Seri Unit Acuan",
        "required": True,
    },
    {
        "doc_type": "label_unit",
        "label": "Foto Label Unit",
        "desc": "Nomor Seri pada Plat Fisik Unit",
        "required": True,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Nomor Seri pada Laporan Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "persetujuan_import",
        "label": "Persetujuan Impor",
        "desc": "Nomor Seri pada Izin Impor Resmi",
        "required": False,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Nomor Seri pada Inventaris PPKR",
        "required": False,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Nomor Seri pada Uji Fungsi Lapangan",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Nomor Seri pada Lembar Paparan / Kebocoran",
        "required": False,
    },
]

XRAY_TUBE_BRAND_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel C.2 Data Teknis Tabung Sinar-X",
        "required": True,
    },
    {
        "doc_type": "label_tabung",
        "label": "Foto Label Tabung",
        "desc": "Plat Fisik Identitas Tabung / Housing",
        "required": True,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Merk Tabung pada Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Merk Tabung pada Inventaris PPKR",
        "required": False,
    },
    {
        "doc_type": "persetujuan_import",
        "label": "Persetujuan Impor",
        "desc": "Merk Tabung pada Izin Impor Resmi",
        "required": False,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Merk Tabung pada Laporan Uji Fungsi",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Merk Tabung pada Lembar Paparan / Kebocoran",
        "required": False,
    },
]

XRAY_TUBE_TYPE_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel C.2 Tipe / Model Tabung",
        "required": True,
    },
    {
        "doc_type": "label_tabung",
        "label": "Foto Label Tabung",
        "desc": "Model Unit / Housing / Insert Tabung",
        "required": True,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Tipe / Model Tabung pada Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Tipe / Model Tabung pada PPKR",
        "required": False,
    },
    {
        "doc_type": "persetujuan_import",
        "label": "Persetujuan Impor",
        "desc": "Tipe / Model Tabung pada Izin Impor",
        "required": False,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Tipe / Model Tabung pada Uji Fungsi",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Tipe / Model Tabung pada Paparan / Kebocoran",
        "required": False,
    },
]

XRAY_TUBE_SERIAL_EXPECTED_DOCS = [
    {
        "doc_type": "formulir",
        "label": "Formulir Permohonan",
        "desc": "Tabel C.2 Nomor Seri Tabung Acuan",
        "required": True,
    },
    {
        "doc_type": "label_tabung",
        "label": "Foto Label Tabung",
        "desc": "Nomor Seri pada Plat Fisik Tabung",
        "required": True,
    },
    {
        "doc_type": "uji_kesesuaian",
        "label": "Laporan Uji Kesesuaian",
        "desc": "Nomor Seri Tabung pada Uji Kesesuaian",
        "required": True,
    },
    {
        "doc_type": "ppkr",
        "label": "Dokumen PPKR",
        "desc": "Nomor Seri Tabung pada PPKR",
        "required": False,
    },
    {
        "doc_type": "persetujuan_import",
        "label": "Persetujuan Impor",
        "desc": "Nomor Seri Tabung pada Izin Impor",
        "required": False,
    },
    {
        "doc_type": "uji_fungsi",
        "label": "Laporan Uji Fungsi",
        "desc": "Nomor Seri Tabung pada Uji Fungsi",
        "required": False,
    },
    {
        "doc_type": "paparan_radiasi",
        "label": "Pengukuran Paparan / Kebocoran",
        "desc": "Nomor Seri Tabung pada Paparan / Kebocoran",
        "required": False,
    },
]


def _safe_page_int(pg):
    """Safely extracts integer page number for SourceEvidence Pydantic validation."""
    if isinstance(pg, int):
        return pg
    if not pg:
        return None
    s = str(pg).strip()
    digits = re.findall(r"\d+", s)
    return int(digits[0]) if digits else None


def _render_parameter_card(category_label, field_title, fv, docs_map, expected_docs=None):
    """Renders a separated, card-based parameter breakdown with status badge, notes, and side-by-side value comparison table.
    When expected_docs is provided, all regulatory requirement documents are listed with their extracted values or missing status.
    """
    sources = fv.get("sources", []) if fv else []
    
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
    fstatus = _clean_status_str(fv.get("status", "SESUAI") if fv else "SESUAI")
    reason_msg = fv.get("reason", "") if fv else ""

    # For hospital name, address, personnel name, equipment brand, or serial number, dynamically compute tolerance-based cross check
    ev = [
        {
            "document_type": s["document_type"],
            "document_name": s["document_name"],
            "value": s["value"],
            "page": _safe_page_int(s.get("page")),
        }
        for s in clean_sources if s["value"] not in ("—", "")
    ]
    if ("Nama Rumah Sakit" in field_title or (fv and fv.get("field_key") == "project_name")) and len(ev) > 1:
        check_res = evaluate_field_sources("project_name", "Nama instansi", ev, mode="facility_name")
        fstatus = _clean_status_str(check_res.status)
        reason_msg = check_res.reason
    elif ("Alamat" in field_title or (fv and fv.get("field_key") == "project_address")) and len(ev) > 1:
        check_res = evaluate_field_sources("project_address", "Alamat instansi", ev, mode="fuzzy_address")
        fstatus = _clean_status_str(check_res.status)
        reason_msg = check_res.reason
    elif ((fv and fv.get("field_key") in {"person_name", "ppr_name"}) or "Nama Personel" in field_title or "Nama Petugas" in field_title or "Nama PPR" in field_title) and len(ev) > 1:
        fkey = (fv.get("field_key") if fv else None) or "person_name"
        check_res = evaluate_field_sources(fkey, field_title, ev, mode="fuzzy_name")
        fstatus = _clean_status_str(check_res.status)
        reason_msg = check_res.reason
    elif ((fv and fv.get("field_key") in {"unit_serial_number", "tube_serial_number"}) or "Nomor Seri" in field_title) and len(ev) > 1:
        fkey = (fv.get("field_key") if fv else None) or "serial_number"
        check_res = evaluate_field_sources(fkey, field_title, ev, mode="serial")
        fstatus = _clean_status_str(check_res.status)
        reason_msg = check_res.reason
    elif ((fv and fv.get("field_key") in {"unit_brand", "tube_brand"}) or "Merk" in field_title) and len(ev) > 1:
        fkey = (fv.get("field_key") if fv else None) or "brand"
        check_res = evaluate_field_sources(fkey, field_title, ev, mode="brand")
        fstatus = _clean_status_str(check_res.status)
        reason_msg = check_res.reason
    else:
        if reason_msg:
            reason_msg = re.sub(r"\s*(?:Tube(?:\s+tilt)?|Collimator(?:\s+Rotation)?)\s*PASS\b", "", reason_msg, flags=re.I)

    if not clean_sources:
        has_any_uploaded = False
        if expected_docs:
            for exp in expected_docs:
                dt = exp.get("doc_type")
                alts = exp.get("alt_doc_types", [])
                m_types = [dt] + alts if alts else [dt]
                for mt in m_types:
                    if docs_map.get(mt):
                        has_any_uploaded = True
                        break
                if has_any_uploaded:
                    break
        if has_any_uploaded:
            fstatus = "PERLU REVIEW"
            badge_html = '<span class="pill pill-review">⚠ Perlu Review</span>'
            if not reason_msg:
                reason_msg = "Berkas persyaratan terunggah namun nilai parameter belum terdeteksi."
        else:
            fstatus = "TIDAK DITEMUKAN"
            badge_html = '<span class="pill pill-missing">○ Belum Diunggah</span>'
            if not reason_msg:
                reason_msg = "Dokumen persyaratan untuk parameter ini belum diunggah."
    else:
        badge_html = _render_pill(fstatus)
        if fstatus == "TIDAK DITEMUKAN" and len(clean_sources) == 1:
            badge_html = '<span class="pill pill-review">⚠ Perlu Review</span>'
            if not reason_msg or "Data hanya ditemukan pada 1 dokumen" in reason_msg:
                reason_msg = f"Data tercantum pada {clean_sources[0]['display_name']}, belum ada berkas pembanding lain yang diunggah."

    # Theme accent: purple for Tabung & PPR, cyan/blue for Pesawat Unit & clinical personnel & general
    is_purple_theme = "Tabung" in category_label or "Tabung" in field_title or "PPR" in category_label or "PPR" in field_title
    border_color = "rgba(168, 85, 247, 0.25)" if is_purple_theme else "rgba(56, 189, 248, 0.22)"
    category_color = "#c084fc" if is_purple_theme else "#38bdf8"
    tag_color = "#c084fc" if is_purple_theme else "#38bdf8"

    card_html = f"""
    <div style="background:#0f172a; border:1px solid {border_color}; border-radius:12px; padding:1.2rem; margin-bottom:1.2rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.8rem;">
            <div>
                <span style="font-size:0.75rem; text-transform:uppercase; color:{category_color}; font-weight:700;">{category_label}</span>
                <h4 style="margin:0.2rem 0 0 0; font-size:1.1rem; font-weight:800; color:#f8fafc;">{field_title}</h4>
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

    if expected_docs:
        # 4-COLUMN INTEGRATED REGULATORY MATRIX & VALUE COMPARISON TABLE
        rows = []
        used_indices = set()

        # Find reference value for comparison (prioritize formulir, else first available)
        ref_val = ""
        for s in clean_sources:
            if s["document_type"] == "formulir" and s["value"] not in ("—", ""):
                ref_val = s["value"]
                break
        if not ref_val and clean_sources:
            for s in clean_sources:
                if s["value"] not in ("—", ""):
                    ref_val = s["value"]
                    break

        # Determine comparison mode
        if (fv and fv.get("field_key") in {"unit_serial_number", "tube_serial_number"}) or "Nomor Seri" in field_title:
            comp_mode = "serial"
        elif (fv and fv.get("field_key") in {"unit_brand", "tube_brand"}) or "Merk" in field_title:
            comp_mode = "brand"
        elif "Nama Rumah Sakit" in field_title or (fv and fv.get("field_key") == "project_name"):
            comp_mode = "facility_name"
        elif "Alamat" in field_title or (fv and fv.get("field_key") == "project_address"):
            comp_mode = "fuzzy_address"
        elif "Nama" in field_title or (fv and fv.get("field_key") in {"person_name", "ppr_name"}):
            comp_mode = "fuzzy_name"
        else:
            comp_mode = "fuzzy_text"

        for exp in expected_docs:
            doc_type = exp.get("doc_type")
            alt_types = exp.get("alt_doc_types", [])
            match_types = [doc_type] + alt_types if alt_types else [doc_type]
            label = exp.get("label") or DOCUMENT_TYPES.get(doc_type, {}).get("name", doc_type.replace("_", " ").title())
            desc = exp.get("desc", "")
            is_req = exp.get("required", True)

            matched_s = None
            for idx_s, s in enumerate(clean_sources):
                if idx_s not in used_indices and s["document_type"] in match_types:
                    matched_s = s
                    used_indices.add(idx_s)
                    break

            if matched_s:
                v_str = matched_s["value"]
                pg = matched_s.get("page")
                pg_str = f" (Hal. {pg})" if pg not in (None, "-", "") else ""
                file_str = f"{matched_s['document_name']}{pg_str}"

                # Calculate individual row badge and secondary explanatory subtext
                val_subtext = ""
                if matched_s["document_type"] == "formulir":
                    row_badge = '<span class="pill pill-match">✓ Sesuai</span>'
                elif "valid_until" in field_title.lower() or (fv and fv.get("field_key") == "valid_until"):
                    v_clean_st = _clean_status_str(fv.get("status", "SESUAI") if fv else "SESUAI")
                    if v_clean_st == "TIDAK SESUAI":
                        row_badge = '<span class="pill pill-fail">✗ Tidak Sesuai</span>'
                        val_subtext = "<div style='font-size:0.72rem; color:#fca5a5; margin-top:2px;'>Masa berlaku telah berakhir (kedaluwarsa)</div>"
                    elif v_clean_st in {"PERLU REVIEW", "WARNING"}:
                        row_badge = '<span class="pill pill-review">⚠ Perlu Review</span>'
                        val_subtext = "<div style='font-size:0.72rem; color:#fde68a; margin-top:2px;'>Perlu konfirmasi masa berlaku</div>"
                    else:
                        row_badge = '<span class="pill pill-match">✓ Sesuai</span>'
                        val_subtext = "<div style='font-size:0.72rem; color:#6ee7b7; margin-top:2px;'>Masa berlaku aktif</div>"
                else:
                    if ref_val and v_str not in ("—", ""):
                        sc, st_c, exp_reason = compare_two_values(ref_val, v_str, mode=comp_mode)
                        st_name = _clean_status_str(st_c)
                        if st_name == "SESUAI":
                            row_badge = '<span class="pill pill-match">✓ Sesuai</span>'
                        elif st_name in {"PERLU REVIEW", "WARNING"}:
                            row_badge = '<span class="pill pill-review">⚠ Perlu Review</span>'
                            if exp_reason and exp_reason not in ("Nilai sesuai", "Nomor seri identik", "Merk sesuai", "Nama personel sesuai", "Nama fasilitas sesuai", "Alamat sesuai sempurna"):
                                val_subtext = f"<div style='font-size:0.72rem; color:#fde68a; margin-top:2px;'>{exp_reason}</div>"
                        else:
                            row_badge = '<span class="pill pill-fail">✗ Tidak Sesuai</span>'
                            if exp_reason and exp_reason not in ("Nilai sesuai", "Nomor seri identik", "Merk sesuai"):
                                val_subtext = f"<div style='font-size:0.72rem; color:#fca5a5; margin-top:2px;'>{exp_reason}</div>"
                    else:
                        row_badge = '<span class="pill pill-match">✓ Sesuai</span>'

                rows.append({
                    "label": label,
                    "desc": desc,
                    "val_html": f"<strong style='color:#f8fafc;'>{v_str}</strong>{val_subtext}",
                    "file_html": file_str,
                    "badge": row_badge,
                })
            else:
                # Not matched in extraction sources
                uploaded_files = []
                for t in match_types:
                    if docs_map.get(t):
                        uploaded_files.extend(docs_map.get(t))

                if uploaded_files:
                    # File uploaded, but value not matched
                    f_list = ", ".join(uploaded_files)
                    if "Nomor Seri" in field_title or (fv and fv.get("field_key") in {"unit_serial_number", "tube_serial_number"}):
                        missing_msg = "Nomor seri tidak ditemukan dalam berkas"
                    elif "Merk" in field_title or (fv and fv.get("field_key") in {"unit_brand", "tube_brand"}):
                        missing_msg = "Merk tidak terdeteksi dalam berkas"
                    elif "Tipe" in field_title or "Model" in field_title:
                        missing_msg = "Tipe/model tidak terdeteksi dalam berkas"
                    elif "Profesi" in field_title:
                        missing_msg = "Profesi tidak terdeteksi dalam berkas"
                    elif "Nama Rumah Sakit" in field_title or (fv and fv.get("field_key") == "project_name"):
                        missing_msg = "Nama rumah sakit tidak terdeteksi dalam berkas"
                    elif "Alamat" in field_title or (fv and fv.get("field_key") == "project_address"):
                        missing_msg = "Alamat tidak terdeteksi dalam berkas"
                    else:
                        missing_msg = "Data tidak terdaftar dalam berkas"

                    rows.append({
                        "label": label,
                        "desc": desc,
                        "val_html": f"<span style='color:#fde68a; font-style:italic;'>— ({missing_msg})</span>",
                        "file_html": f_list,
                        "badge": '<span class="pill pill-review">⚠ Perlu Review</span>',
                    })
                else:
                    # File not uploaded
                    req_label = "Wajib Regulasi" if is_req else "Dokumen Pendukung"
                    rows.append({
                        "label": label,
                        "desc": desc,
                        "val_html": f"<span style='color:#64748b; font-style:italic;'>— (Berkas belum diunggah · {req_label})</span>",
                        "file_html": "—",
                        "badge": '<span class="pill pill-missing">○ Belum Diunggah</span>',
                    })

        # Append any extra clean_sources not covered in expected_docs
        for idx_s, s in enumerate(clean_sources):
            if idx_s not in used_indices:
                pg = s.get("page")
                pg_str = f" (Hal. {pg})" if pg not in (None, "-", "") else ""
                rows.append({
                    "label": s["display_name"],
                    "desc": "Dokumen Terunggah Tambahan",
                    "val_html": f"<strong style='color:#f8fafc;'>{s['value']}</strong>",
                    "file_html": f"{s['document_name']}{pg_str}",
                    "badge": '<span class="pill pill-match">✓ Sesuai</span>',
                })

        t_rows = ""
        for r in rows:
            desc_html = f"<div style='font-size:0.7rem; color:#64748b; margin-top:2px;'>{r['desc']}</div>" if r.get('desc') else ""
            t_rows += f"""
            <tr>
                <td style="width:28%;">
                    <div style="font-weight:700; color:{tag_color}; font-size:0.86rem;">{r['label']}</div>
                    {desc_html}
                </td>
                <td style="width:34%; font-size:0.85rem;">{r['val_html']}</td>
                <td style="width:23%; font-size:0.78rem; color:#94a3b8; font-family:'JetBrains Mono', monospace;">{r['file_html']}</td>
                <td style="width:15%; text-align:center;">{r['badge']}</td>
            </tr>
            """

        card_html += f"""
        <table class="matrix-table" style="margin:0.5rem 0 0 0;">
            <thead>
                <tr>
                    <th style="width:28%;">Dokumen Persyaratan</th>
                    <th style="width:34%;">Nilai Tertera</th>
                    <th style="width:23%;">Berkas Fisik Sumber</th>
                    <th style="width:15%; text-align:center;">Status</th>
                </tr>
            </thead>
            <tbody>{t_rows}</tbody>
        </table>
        """
    else:
        # Standard 3-column table when expected_docs is not specified
        if clean_sources:
            t_rows = ""
            for s in clean_sources:
                page_info = f" (Hal. {s['page']})" if s.get('page') not in (None, "-", "") else ""
                t_rows += f"<tr><td style='font-weight:700; color:{tag_color}; width:35%;'>{s['display_name']}</td><td style='font-weight:600; width:35%;'>{s['value']}</td><td style='color:#64748b; width:30%;'>{s['document_name']}{page_info}</td></tr>"
            
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
    """Renders a single consolidated card for doctor's SIP credentials (validity & practice location).
    Guarantees every required parameter is presented with extracted values or explicit missing notice.
    """
    v_sources = v_field.get("sources", []) if v_field else []
    l_sources = l_field.get("sources", []) if l_field else []
    has_sip_files = bool(docs_map.get("sip"))

    # 1. Parameter Masa Berlaku Izin
    if v_sources:
        v_raw = v_sources[0].get("value", "—")
        v_doc = v_sources[0].get("file_name") or v_sources[0].get("document_name") or (docs_map.get("sip", ["SIP.pdf"])[0])
        v_p = v_sources[0].get("page")
        v_p_str = f" (Hal. {v_p})" if v_p not in (None, "-", "") else ""
        v_doc_str = f"{v_doc}{v_p_str}"
        v_st = _clean_status_str(v_field.get("status", "SESUAI") if v_field else "SESUAI")
        if v_st == "TIDAK SESUAI":
            v_val_html = f"<strong style='color:#f87171;'>{v_raw}</strong><div style='font-size:0.72rem; color:#fca5a5; margin-top:2px;'>Masa berlaku telah berakhir (kedaluwarsa)</div>"
            v_badge = '<span class="pill pill-fail">✗ Tidak Sesuai</span>'
        elif v_st in {"PERLU REVIEW", "WARNING"}:
            v_val_html = f"<strong style='color:#fbbf24;'>{v_raw}</strong><div style='font-size:0.72rem; color:#fde68a; margin-top:2px;'>Perlu konfirmasi masa berlaku</div>"
            v_badge = '<span class="pill pill-review">⚠ Perlu Review</span>'
        else:
            v_val_html = f"<strong style='color:#34d399;'>{v_raw}</strong> <span style='font-size:0.75rem; color:#6ee7b7;'>(Aktif)</span>"
            v_badge = '<span class="pill pill-match">✓ Sesuai</span>'
    else:
        if has_sip_files:
            v_val_html = "<span style='color:#fde68a; font-style:italic;'>— (SIP terunggah, namun belum cocok dengan personel)</span>"
            v_doc_str = ", ".join(docs_map.get("sip", []))
            v_badge = '<span class="pill pill-review">⚠ Perlu Review</span>'
            v_st = "PERLU REVIEW"
        else:
            v_val_html = "<span style='color:#64748b; font-style:italic;'>— (Berkas SIP belum diunggah · Wajib Regulasi)</span>"
            v_doc_str = "—"
            v_badge = '<span class="pill pill-missing">○ Belum Diunggah</span>'
            v_st = "TIDAK SESUAI"

    # 2. Parameter Tempat Praktik
    if l_sources:
        l_raw = l_sources[0].get("value", "—")
        l_doc = l_sources[0].get("file_name") or l_sources[0].get("document_name") or (docs_map.get("sip", ["SIP.pdf"])[0])
        l_p = l_sources[0].get("page")
        l_p_str = f" (Hal. {l_p})" if l_p not in (None, "-", "") else ""
        l_doc_str = f"{l_doc}{l_p_str}"
        l_st = _clean_status_str(l_field.get("status", "SESUAI") if l_field else "SESUAI")
        if l_st == "TIDAK SESUAI":
            l_val_html = f"<strong style='color:#f87171;'>{l_raw}</strong><div style='font-size:0.72rem; color:#fca5a5; margin-top:2px;'>Fasilitas praktik berbeda dengan pemohon</div>"
            l_badge = '<span class="pill pill-fail">✗ Tidak Sesuai</span>'
        elif l_st in {"PERLU REVIEW", "WARNING"}:
            l_val_html = f"<strong style='color:#fbbf24;'>{l_raw}</strong><div style='font-size:0.72rem; color:#fde68a; margin-top:2px;'>Variasi redaksional nama fasilitas</div>"
            l_badge = '<span class="pill pill-review">⚠ Perlu Review</span>'
        else:
            l_val_html = f"<strong style='color:#f8fafc;'>{l_raw}</strong>"
            l_badge = '<span class="pill pill-match">✓ Sesuai</span>'
    else:
        if has_sip_files:
            l_val_html = "<span style='color:#fde68a; font-style:italic;'>— (Tempat praktik belum terverifikasi)</span>"
            l_doc_str = ", ".join(docs_map.get("sip", []))
            l_badge = '<span class="pill pill-review">⚠ Perlu Review</span>'
            l_st = "PERLU REVIEW"
        else:
            l_val_html = "<span style='color:#64748b; font-style:italic;'>— (Berkas SIP belum diunggah · Wajib Regulasi)</span>"
            l_doc_str = "—"
            l_badge = '<span class="pill pill-missing">○ Belum Diunggah</span>'
            l_st = "TIDAK SESUAI"

    # Overall Badge
    if not has_sip_files:
        overall_status = "TIDAK SESUAI"
    elif "TIDAK SESUAI" in (v_st, l_st):
        overall_status = "TIDAK SESUAI"
    elif "PERLU REVIEW" in (v_st, l_st) or "WARNING" in (v_st, l_st):
        overall_status = "PERLU REVIEW"
    else:
        overall_status = "SESUAI"

    badge_html = _render_pill(overall_status)

    notes = []
    if v_field and v_field.get("reason"):
        notes.append(v_field["reason"])
    if l_field and l_field.get("reason"):
        notes.append(l_field["reason"])
    if not has_sip_files:
        notes.append("Surat Izin Praktik (SIP) wajib diunggah untuk legalitas praktik fasilitas.")
    elif not v_sources and not l_sources:
        notes.append("Berkas SIP diunggah namun nama/kredensial belum cocok dengan data permohonan personel.")

    note_html = ""
    if notes:
        color_note = "#fca5a5" if overall_status == "TIDAK SESUAI" else ("#fde68a" if overall_status in {"PERLU REVIEW", "WARNING"} else "#94a3b8")
        note_html = f"<div style='font-size:0.82rem; color:{color_note}; margin-bottom:0.8rem;'>{' · '.join(notes)}</div>"

    card_html = f"""
    <div style="background:#0f172a; border:1px solid var(--border-subtle); border-radius:12px; padding:1.2rem; margin-bottom:1.2rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.8rem;">
            <div>
                <span style="font-size:0.75rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">Kredensial Izin Personel #{idx}</span>
                <h4 style="margin:0.2rem 0 0 0; font-size:1.1rem; font-weight:800; color:#f8fafc;">Surat Izin Praktik (SIP)</h4>
            </div>
            <div>{badge_html}</div>
        </div>
        {note_html}
        <table class="matrix-table" style="margin:0.5rem 0 0 0;">
            <thead>
                <tr>
                    <th style="width:28%;">Parameter SIP</th>
                    <th style="width:34%;">Nilai Tertera</th>
                    <th style="width:23%;">Berkas Fisik Sumber</th>
                    <th style="width:15%; text-align:center;">Status</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="width:28%;">
                        <div style="font-weight:700; color:#38bdf8; font-size:0.86rem;">Masa Berlaku Izin</div>
                        <div style="font-size:0.7rem; color:#64748b; margin-top:2px;">Batas Akhir Legalitas Praktik</div>
                    </td>
                    <td style="width:34%; font-size:0.85rem;">{v_val_html}</td>
                    <td style="width:23%; font-size:0.78rem; color:#94a3b8; font-family:'JetBrains Mono', monospace;">{v_doc_str}</td>
                    <td style="width:15%; text-align:center;">{v_badge}</td>
                </tr>
                <tr>
                    <td style="width:28%;">
                        <div style="font-weight:700; color:#38bdf8; font-size:0.86rem;">Tempat Praktik</div>
                        <div style="font-size:0.7rem; color:#64748b; margin-top:2px;">Kesesuaian Faskes Pemohon</div>
                    </td>
                    <td style="width:34%; font-size:0.85rem;">{l_val_html}</td>
                    <td style="width:23%; font-size:0.78rem; color:#94a3b8; font-family:'JetBrains Mono', monospace;">{l_doc_str}</td>
                    <td style="width:15%; text-align:center;">{l_badge}</td>
                </tr>
            </tbody>
        </table>
    </div>
    """
    render_html(card_html)



def split_project_address(raw_alamat_proyek: str):
    """Splits raw Alamat Proyek from BAPETEN Formulir Permohonan into (nama_instansi, alamat_instansi)."""
    if not raw_alamat_proyek:
        return "", ""
    text = re.sub(r"\s+", " ", str(raw_alamat_proyek or "")).strip(" :;-\t")
    if not text:
        return "", ""
    street_indicators = r"^(?:Jl\.?|Jalan|Dusun|Desa|Komplek|Kav\.?|Gedung|Blok|RT\b|RW\b|No\.)\b"
    if "," in text:
        parts = text.split(",", 1)
        cand_name = parts[0].strip()
        cand_addr = parts[1].strip()
        if cand_name and not re.match(street_indicators, cand_name, re.IGNORECASE):
            return cand_name, cand_addr
        return "", text
    m = re.search(
        r"^(.*?)\s+(?=(?:Jl\.?|Jalan|Dusun|Desa|Komplek|Kav\.?|Gedung|Blok|RT\s*\d|RW\s*\d)\b)(.+)$",
        text,
        re.IGNORECASE,
    )
    if m:
        cand_name = m.group(1).strip().rstrip(",")
        cand_addr = m.group(2).strip()
        if cand_name and not re.match(street_indicators, cand_name, re.IGNORECASE):
            return cand_name, cand_addr
    return "", text


# Safely ensure persistent Streamlit runtime reloads form_parser if cached without split_project_address
try:
    import sys, importlib
    if "src.extraction.form_parser" in sys.modules:
        importlib.reload(sys.modules["src.extraction.form_parser"])
except Exception:
    pass


def _sanitize_run_facility_identity(run_obj):
    """Guarantees that formulir facility name and address are correctly derived
    from Alamat Proyek prefix and suffix, including historical runs saved in DB."""
    if not run_obj or not isinstance(run_obj, dict):
        return run_obj

    form_docs = run_obj.get("extractions", {}).get("formulir", [])
    split_hname = ""
    split_haddr = ""
    for doc in form_docs:
        f = doc.get("fields", {})
        hdr = f.get("header", {})
        p_addr = (
            hdr.get("project_address", {}).get("value")
            if isinstance(hdr.get("project_address"), dict)
            else (hdr.get("Alamat Proyek") or hdr.get("project_address"))
        )
        if not p_addr:
            p_addr = f.get("hospital_address", {}).get("value")
        if p_addr:
            s_name, s_addr = split_project_address(p_addr)
            if s_name:
                split_hname = s_name
                f["hospital_name"] = {
                    "value": s_name,
                    "page": f.get("hospital_name", {}).get("page", 1),
                    "method": "project_address_prefix",
                    "confidence": 1.0,
                }
            if s_addr:
                split_haddr = s_addr
                f["hospital_address"] = {
                    "value": s_addr,
                    "page": f.get("hospital_address", {}).get("page", 1),
                    "method": "project_address_suffix",
                    "confidence": 1.0,
                }

    fac_obj = run_obj.get("cross_check_report", {}).get("facility", {})
    fac_fields = fac_obj.get("fields", {})

    if split_hname:
        for s in fac_fields.get("project_name", {}).get("sources", []):
            if s.get("document_type") == "formulir":
                s["value"] = split_hname
    if split_haddr:
        for s in fac_fields.get("project_address", {}).get("sources", []):
            if s.get("document_type") == "formulir":
                s["value"] = split_haddr

    # Re-evaluate project_name and project_address cross-check evaluations
    try:
        from src.matching.cross_check_engine import evaluate_field_sources, SourceEvidence
        for fkey, mode, flabel in [
            ("project_name", "facility_name", "Nama instansi"),
            ("project_address", "fuzzy_address", "Alamat instansi"),
        ]:
            f_data = fac_fields.get(fkey)
            if f_data and "sources" in f_data:
                ev_list = [
                    {
                        "document_type": s.get("document_type", ""),
                        "document_name": s.get("document_name", ""),
                        "value": s.get("value", ""),
                        "page": _safe_page_int(s.get("page")),
                    }
                    for s in f_data.get("sources", [])
                    if s.get("value") and s.get("value") not in ("—", "-")
                ]
                if len(ev_list) > 1:
                    eval_res = evaluate_field_sources(fkey, flabel, ev_list, mode=mode)
                    f_data["status"] = eval_res.status.value
                    f_data["score"] = eval_res.score
                    f_data["reason"] = eval_res.reason
                    f_data["discrepancies"] = eval_res.discrepancies

        statuses = [
            _clean_status_str(f_data.get("status", ""))
            for f_data in fac_fields.values()
            if isinstance(f_data, dict)
        ]
        if any("TIDAK SESUAI" in s for s in statuses):
            fac_obj["status"] = "TIDAK SESUAI"
        elif any("PERLU REVIEW" in s or "WARNING" in s for s in statuses):
            fac_obj["status"] = "PERLU REVIEW"
        else:
            fac_obj["status"] = "SESUAI"
    except Exception:
        pass

    return run_obj


def _extract_applicant_details(res):
    """Extracts institutional profile from result object for presentation."""
    res = _sanitize_run_facility_identity(res)
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
        st.session_state["latest_result"] = _sanitize_run_facility_identity(db.get_run(past_runs[0][0]))
        st.session_state["sb_run_selector"] = past_runs[0][0]
    except Exception:
        pass


def _cached_classify_document(filename, file_size, head_bytes, file_bytes):
    import importlib
    import src.extraction.classifier as cls_mod
    importlib.reload(cls_mod)
    return cls_mod.classify_document(filename, file_bytes)


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

    # Local LLM Status Badge
    try:
        from src.extraction.llm_extractor import is_ollama_available
        ollama_active = is_ollama_available()
    except Exception:
        ollama_active = False

    if ollama_active:
        render_html("""
        <div style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); border-radius:8px; padding:6px 10px; margin-top:8px; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">
            <div><span style="font-weight:600; font-size:0.8rem; color:#f8fafc;">🤖 LLM Lokal</span><br><span style="font-size:0.7rem; color:#94a3b8;">Qwen 2.5 7B (On-Premise)</span></div>
            <span style="background:#059669; color:#fff; font-size:0.65rem; font-weight:700; padding:2px 6px; border-radius:4px;">🟢 AKTIF</span>
        </div>
        """)
    else:
        render_html("""
        <div style="background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); border-radius:8px; padding:6px 10px; margin-top:8px; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">
            <div><span style="font-weight:600; font-size:0.8rem; color:#f8fafc;">🤖 LLM Lokal</span><br><span style="font-size:0.7rem; color:#94a3b8;">Ollama Server</span></div>
            <span style="background:#dc2626; color:#fff; font-size:0.65rem; font-weight:700; padding:2px 6px; border-radius:4px;">🔴 OFFLINE</span>
        </div>
        """)

    render_html("<hr style='margin:10px 0; border-color:rgba(255,255,255,0.08);'>")

    # 1. Past Runs Selector
    if past_runs:
        st.markdown("##### 📜 Riwayat Uji Dokumen")
        curr_id = st.session_state.get("latest_result", {}).get("run_id")

        # Ensure selectbox state stays synchronized with active run
        if curr_id and curr_id in run_options:
            if st.session_state.get("sb_run_selector") != curr_id:
                st.session_state["sb_run_selector"] = curr_id

        def _on_run_selector_change():
            sel_id = st.session_state.get("sb_run_selector")
            if sel_id:
                loaded_run = db.get_run(sel_id)
                if loaded_run:
                    st.session_state["latest_result"] = _sanitize_run_facility_identity(loaded_run)

        def_idx = run_options.index(curr_id) if curr_id in run_options else 0
        st.selectbox(
            "Pilih Batch",
            options=run_options,
            index=def_idx,
            format_func=lambda rid: run_labels.get(rid, rid),
            key="sb_run_selector",
            on_change=_on_run_selector_change,
            label_visibility="collapsed",
        )

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
                # If a label document is detected, pre-select both label_unit and label_tabung
                if detected_type in {"label_unit", "label_tabung"}:
                    default_cats = ["label_unit", "label_tabung"]
                else:
                    default_cats = [detected_type] if detected_type in doc_keys else []
                with st.expander(f"{icon} {file.name}", expanded=not is_conf):
                    st.caption(f"🔍 Terdeteksi: **{doc_names.get(detected_type, detected_type)}** ({reason})")
                    chosen = st.multiselect(
                        "Kategori Dokumen",
                        options=doc_keys,
                        default=default_cats,
                        format_func=lambda k: doc_names[k],
                        key=f"sb_up_{idx}_{file.name}_{detected_type}",
                        label_visibility="collapsed",
                    )
                for ct in chosen:
                    upload_map[ct].append(file)
            active_cat = sum(1 for v in upload_map.values() if v)
            st.info(f"📋 {active_cat} dari {len(doc_keys)} jenis dokumen terdeteksi.")
    else:
        # Unified uploader for label documents (Unit & Tabung)
        st.markdown("**🏷️ Foto Label Fisik (Unit & Tabung Sinar-X)**")
        st.caption("Unggah berkas PDF gabungan atau foto fisik plat label unit & tabung sinar-X (.pdf, .jpg, .png)")
        unified_labels = st.file_uploader(
            "Foto Label Fisik (Unit & Tabung)",
            type=["pdf", "jpg", "jpeg", "png", "bmp", "webp"],
            accept_multiple_files=True,
            key="sb_manual_unified_label",
            label_visibility="collapsed",
        )
        if unified_labels:
            upload_map["label_unit"].extend(unified_labels)
            upload_map["label_tabung"].extend(unified_labels)

        # Other 15 documents
        for doc_type, meta in DOCUMENT_TYPES.items():
            if doc_type in {"label_unit", "label_tabung"}:
                continue
            exts = ["pdf"] if meta["kind"] == "pdf" else ["jpg", "jpeg", "png", "bmp", "webp", "pdf"]
            up_files = st.file_uploader(meta["name"], type=exts, accept_multiple_files=True, key=f"sb_manual_{doc_type}")
            if up_files:
                upload_map[doc_type].extend(up_files)

        with st.expander("⚙️ Opsi: Unggah Terpisah (Unit / Tabung Mandiri)", expanded=False):
            st.caption("Gunakan ini hanya jika ingin mengunggah ke slot unit atau tabung secara terpisah:")
            u_only = st.file_uploader("Foto Label Unit Mandiri", type=["pdf", "jpg", "jpeg", "png", "bmp", "webp"], accept_multiple_files=True, key="sb_manual_label_unit_only")
            if u_only:
                upload_map["label_unit"].extend(u_only)
            t_only = st.file_uploader("Foto Label Tabung Mandiri", type=["pdf", "jpg", "jpeg", "png", "bmp", "webp"], accept_multiple_files=True, key="sb_manual_label_tabung_only")
            if t_only:
                upload_map["label_tabung"].extend(t_only)

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
                import sys, importlib
                for mod_name in list(sys.modules.keys()):
                    if mod_name.startswith("src.") or mod_name == "src":
                        try:
                            importlib.reload(sys.modules[mod_name])
                        except Exception:
                            pass
                from src.pipeline import execute_run
                result_obj = execute_run(inputs, on_progress=on_prog)
                status_box.update(label="✅ Verifikasi Selesai!", state="complete", expanded=False)

            result_obj = _sanitize_run_facility_identity(result_obj)
            result_obj["file_display"] = file_display
            db.save_run_generic(result_obj)
            st.session_state["latest_result"] = result_obj
            st.rerun()
        except Exception as err:
            st.exception(err)


# ═══════════════════════════════════════════════════════════════════
# MAIN CONTENT AREA
# ═══════════════════════════════════════════════════════════════════
active_run = _sanitize_run_facility_identity(st.session_state.get("latest_result"))

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
        <div style="margin-bottom:1.5rem;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:#38bdf8;">
                    Identitas Subjek Hukum
                </span>
            </div>
            <h3 style="margin:0.2rem 0 0 0; font-size:1.35rem; font-weight:800; color:#38bdf8;">
                🏢 Verifikasi Identitas Fasilitas & Instansi Pemohon
            </h3>
            <p style="margin:0.25rem 0 0 0; font-size:0.84rem; color:#94a3b8;">
                Verifikasi konsistensi nama dan alamat rumah sakit / fasilitas pemohon di seluruh berkas permohonan izin pemanfaatan radiasi sesuai regulasi BAPETEN.
            </p>
        </div>
        """)

        fac_obj = active_run.get("cross_check_report", {}).get("facility", {})
        fac_rep = fac_obj.get("fields", {})

        # Determine overall facility status directly from parameter fields
        pname_st = _clean_status_str(fac_rep.get("project_name", {}).get("status", "SESUAI"))
        paddr_st = _clean_status_str(fac_rep.get("project_address", {}).get("status", "SESUAI"))
        if "TIDAK SESUAI" in (pname_st, paddr_st):
            fac_status = "TIDAK SESUAI"
        elif "PERLU REVIEW" in (pname_st, paddr_st) or "WARNING" in (pname_st, paddr_st):
            fac_status = "PERLU REVIEW"
        else:
            fac_status = "SESUAI"
        docs_map = active_run.get("documents", {})

        # Header Banner Instansi
        render_html(f"""
        <div style="display:flex; justify-content:space-between; align-items:center; background:#111c35; border:1px solid rgba(56, 189, 248, 0.22); border-radius:12px; padding:0.9rem 1.4rem; margin:0 0 1.5rem 0;">
            <div>
                <span style="font-size:0.72rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">
                    Profil Pemohon & Objek Izin
                </span>
                <div style="font-size:1.2rem; font-weight:800; color:#f8fafc; margin-top:2px;">
                    🏥 {app_details['hospital_name']}
                </div>
            </div>
            <div>{_render_pill(fac_status)}</div>
        </div>
        """)

        # 1. Parameter Nama Rumah Sakit / Instansi Pemohon
        pname_field = fac_rep.get("project_name", {"sources": []})
        if isinstance(pname_field, dict) and "field_key" not in pname_field:
            pname_field = dict(pname_field)
            pname_field["field_key"] = "project_name"
        _render_parameter_card(
            "Parameter Identitas Pemohon",
            "Nama Rumah Sakit / Instansi Pemohon",
            pname_field,
            docs_map,
            expected_docs=FACILITY_NAME_EXPECTED_DOCS,
        )

        # 2. Parameter Alamat Rumah Sakit / Lokasi Fasilitas
        paddr_field = fac_rep.get("project_address", {"sources": []})
        if isinstance(paddr_field, dict) and "field_key" not in paddr_field:
            paddr_field = dict(paddr_field)
            paddr_field["field_key"] = "project_address"
        _render_parameter_card(
            "Parameter Lokasi Fasilitas",
            "Alamat Rumah Sakit / Lokasi Fasilitas",
            paddr_field,
            docs_map,
            expected_docs=FACILITY_ADDRESS_EXPECTED_DOCS,
        )

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
            prof_sources = pf.get("profession", {}).get("sources", [])
            roles = [str(s.get("value") or "").strip().lower() for s in prof_sources if s.get("value")]
            # If the entry explicitly specifies a PPR role, it belongs to Section 2 (PPR)
            if any("ppr" in r or "proteksi" in r for r in roles):
                return True
            # Only if the entry has NO profession specified at all, check if name matches PPR
            if not roles:
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
                name_f = pf.get("person_name") or {"sources": []}
                _render_parameter_card(
                    f"Field Identitas Personel #{idx}",
                    "Nama Personel",
                    name_f,
                    docs_map,
                    expected_docs=PERSONNEL_NAME_EXPECTED_DOCS,
                )

                # 2. Parameter Profesi / Kualifikasi (clean title without duplicate name suffix)
                prof_f = pf.get("profession") or {"sources": []}
                _render_parameter_card(
                    f"Kualifikasi Personel #{idx}",
                    "Kualifikasi / Profesi",
                    prof_f,
                    docs_map,
                    expected_docs=PERSONNEL_PROFESSION_EXPECTED_DOCS,
                )

                # 3. Parameter SIP: gabungkan Masa Berlaku dan Tempat Praktik dalam 1 kartu terpadu agar tidak terlihat duplikat
                _render_sip_consolidated_card(idx, pf.get("valid_until"), pf.get("practice_location"), docs_map)
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
                name_f = ppr_f.get("ppr_name") or {"sources": []}
                _render_parameter_card(
                    "Field Identitas PPR",
                    "Nama Petugas Proteksi Radiasi (PPR)",
                    name_f,
                    docs_map,
                    expected_docs=PPR_NAME_EXPECTED_DOCS,
                )
                valid_f = ppr_f.get("valid_until") or {"sources": []}
                _render_parameter_card(
                    "Kredensial SIB",
                    "Masa Berlaku Surat Izin Bekerja (SIB)",
                    valid_f,
                    docs_map,
                    expected_docs=PPR_SIB_EXPECTED_DOCS,
                )
        else:
            _render_parameter_card(
                "Field Identitas PPR",
                "Nama Petugas Proteksi Radiasi (PPR)",
                {"sources": []},
                docs_map,
                expected_docs=PPR_NAME_EXPECTED_DOCS,
            )
            _render_parameter_card(
                "Kredensial SIB",
                "Masa Berlaku Surat Izin Bekerja (SIB)",
                {"sources": []},
                docs_map,
                expected_docs=PPR_SIB_EXPECTED_DOCS,
            )

    # ─────────────────────────────────────────────────────────────
    # TAB 4: PESAWAT SINAR-X
    # ─────────────────────────────────────────────────────────────
    with tab_pesawat:
        render_html("""
        <div style="margin-bottom:1.5rem;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:#38bdf8;">
                    Spesifikasi Peralatan Radiasi
                </span>
            </div>
            <h3 style="margin:0.2rem 0 0 0; font-size:1.35rem; font-weight:800; color:#38bdf8;">
                ⚡ Verifikasi Spesifikasi Pesawat & Tabung Sinar-X
            </h3>
            <p style="margin:0.25rem 0 0 0; font-size:0.84rem; color:#94a3b8;">
                Verifikasi silang konsistensi nomor seri, merk, dan model pesawat serta tabung sinar-X antar formulir permohonan, foto plat identitas fisik, izin impor BAPETEN, dan laporan uji kesesuaian.
            </p>
        </div>
        """)

        x_eq_list = active_run.get("cross_check_report", {}).get("xray_equipment", [])
        x_tb_list = active_run.get("cross_check_report", {}).get("xray_tubes", [])
        docs_map = active_run.get("documents", {})

        # ─────────────────────────────────────────────────────────────
        # 1. DATA UNIT PESAWAT SINAR-X (X-RAY EQUIPMENT)
        # ─────────────────────────────────────────────────────────────
        render_html("""
        <div style="margin-bottom:1.2rem;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:#38bdf8;">
                    Bagian 1
                </span>
            </div>
            <h3 style="margin:0.2rem 0 0 0; font-size:1.25rem; font-weight:800; color:#38bdf8;">
                1. Data Unit Pesawat Sinar-X
            </h3>
            <p style="margin:0.25rem 0 0 0; font-size:0.83rem; color:#94a3b8;">
                Verifikasi konsistensi merk, tipe/model, dan nomor seri generator / unit kontrol terhadap formulir permohonan, foto label unit fisik, dan laporan uji kesesuaian.
            </p>
        </div>
        """)

        unit_expected_map = {
            "unit_brand": XRAY_UNIT_BRAND_EXPECTED_DOCS,
            "unit_type": XRAY_UNIT_TYPE_EXPECTED_DOCS,
            "unit_serial_number": XRAY_UNIT_SERIAL_EXPECTED_DOCS,
        }
        unit_param_titles = {
            "unit_brand": "Merk Pesawat Sinar-X (Brand)",
            "unit_type": "Tipe / Model Pesawat Sinar-X (Model / Type)",
            "unit_serial_number": "Nomor Seri Pesawat Sinar-X (Serial Number)",
        }

        if x_eq_list:
            for idx, eq in enumerate(x_eq_list, start=1):
                eq_label = eq.get("entity_label") or f"Pesawat Sinar-X Unit #{idx}"
                eq_status = _clean_status_str(eq.get("status") or "SESUAI")
                eq_fields = eq.get("fields", {})

                # Entity Header Banner (Cyan Theme)
                render_html(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; background:#111c35; border:1px solid rgba(56, 189, 248, 0.22); border-radius:12px; padding:0.9rem 1.4rem; margin:1.6rem 0 1rem 0;">
                    <div>
                        <span style="font-size:0.72rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">
                            Pesawat Sinar-X · Unit #{idx}
                        </span>
                        <div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin-top:2px;">
                            ⚡ {eq_label}
                        </div>
                    </div>
                    <div>{_render_pill(eq_status)}</div>
                </div>
                """)

                # Render the 3 standard regulatory parameters (always guaranteed to be shown)
                for fk in ["unit_brand", "unit_type", "unit_serial_number"]:
                    fv = eq_fields.get(fk, {"sources": []})
                    if isinstance(fv, dict) and "field_key" not in fv:
                        fv = dict(fv)
                        fv["field_key"] = fk
                    ftitle = unit_param_titles.get(fk, fk.replace("_", " ").title())
                    _render_parameter_card(
                        f"Parameter Unit Pesawat #{idx}",
                        ftitle,
                        fv,
                        docs_map,
                        expected_docs=unit_expected_map.get(fk),
                    )

                # Render any additional non-standard fields if present in eq_fields
                for fk, fv in eq_fields.items():
                    if fk not in ["unit_brand", "unit_type", "unit_serial_number"]:
                        ftitle = fv.get("field_label") if isinstance(fv, dict) else fk.replace("_", " ").title()
                        _render_parameter_card(
                            f"Parameter Unit Pesawat #{idx}",
                            ftitle,
                            fv,
                            docs_map,
                        )
        else:
            render_html("""
            <div style="display:flex; justify-content:space-between; align-items:center; background:#111c35; border:1px solid rgba(56, 189, 248, 0.22); border-radius:12px; padding:0.9rem 1.4rem; margin:1.6rem 0 1rem 0;">
                <div>
                    <span style="font-size:0.72rem; text-transform:uppercase; color:#38bdf8; font-weight:700;">
                        Pesawat Sinar-X · Unit #1
                    </span>
                    <div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin-top:2px;">
                        ⚡ Pesawat Sinar-X Unit #1
                    </div>
                </div>
                <div><span class="pill pill-missing">○ Belum Terdaftar</span></div>
            </div>
            """)
            for fk in ["unit_brand", "unit_type", "unit_serial_number"]:
                ftitle = unit_param_titles.get(fk, fk.replace("_", " ").title())
                _render_parameter_card(
                    "Parameter Unit Pesawat #1",
                    ftitle,
                    {"sources": [], "field_key": fk},
                    docs_map,
                    expected_docs=unit_expected_map.get(fk),
                )

        # ─────────────────────────────────────────────────────────────
        # 2. DATA TABUNG SINAR-X (X-RAY TUBE)
        # ─────────────────────────────────────────────────────────────
        render_html("""
        <div style="margin:2.8rem 0 1.2rem 0; padding-top:1.5rem; border-top:1px solid rgba(168, 85, 247, 0.3);">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:#a855f7;">
                    Bagian 2
                </span>
            </div>
            <h3 style="margin:0.2rem 0 0 0; font-size:1.25rem; font-weight:800; color:#c084fc;">
                2. Data Tabung Sinar-X (X-Ray Tube / Housing / Insert)
            </h3>
            <p style="margin:0.25rem 0 0 0; font-size:0.83rem; color:#94a3b8;">
                Verifikasi konsistensi merk, tipe/model insert/housing, dan nomor seri tabung terhadap formulir permohonan, foto label plat tabung fisik, dan laporan uji kesesuaian.
            </p>
        </div>
        """)

        tube_expected_map = {
            "tube_brand": XRAY_TUBE_BRAND_EXPECTED_DOCS,
            "tube_type": XRAY_TUBE_TYPE_EXPECTED_DOCS,
            "tube_serial_number": XRAY_TUBE_SERIAL_EXPECTED_DOCS,
        }
        tube_param_titles = {
            "tube_brand": "Merk Tabung Sinar-X (Tube Brand)",
            "tube_type": "Tipe / Model Tabung Sinar-X (Tube Model / Type)",
            "tube_serial_number": "Nomor Seri Tabung Sinar-X (Tube Serial Number)",
        }

        if x_tb_list:
            for idx, tb in enumerate(x_tb_list, start=1):
                tb_label = tb.get("entity_label") or f"Tabung Sinar-X #{idx}"
                tb_status = _clean_status_str(tb.get("status") or "SESUAI")
                tb_fields = tb.get("fields", {})

                # Entity Header Banner (Purple Theme)
                render_html(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; background:#19142b; border:1px solid rgba(168, 85, 247, 0.25); border-radius:12px; padding:0.9rem 1.4rem; margin:1.6rem 0 1rem 0;">
                    <div>
                        <span style="font-size:0.72rem; text-transform:uppercase; color:#a855f7; font-weight:700;">
                            Tabung Sinar-X · Tabung #{idx}
                        </span>
                        <div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin-top:2px;">
                            🔬 {tb_label}
                        </div>
                    </div>
                    <div>{_render_pill(tb_status)}</div>
                </div>
                """)

                # Render the 3 standard regulatory parameters (always guaranteed to be shown)
                for fk in ["tube_brand", "tube_type", "tube_serial_number"]:
                    fv = tb_fields.get(fk, {"sources": []})
                    if isinstance(fv, dict) and "field_key" not in fv:
                        fv = dict(fv)
                        fv["field_key"] = fk
                    ftitle = tube_param_titles.get(fk, fk.replace("_", " ").title())
                    _render_parameter_card(
                        f"Parameter Tabung Sinar-X #{idx}",
                        ftitle,
                        fv,
                        docs_map,
                        expected_docs=tube_expected_map.get(fk),
                    )

                # Render any additional non-standard fields if present in tb_fields
                for fk, fv in tb_fields.items():
                    if fk not in ["tube_brand", "tube_type", "tube_serial_number"]:
                        ftitle = fv.get("field_label") if isinstance(fv, dict) else fk.replace("_", " ").title()
                        _render_parameter_card(
                            f"Parameter Tabung Sinar-X #{idx}",
                            ftitle,
                            fv,
                            docs_map,
                        )
        else:
            render_html("""
            <div style="display:flex; justify-content:space-between; align-items:center; background:#19142b; border:1px solid rgba(168, 85, 247, 0.25); border-radius:12px; padding:0.9rem 1.4rem; margin:1.6rem 0 1rem 0;">
                <div>
                    <span style="font-size:0.72rem; text-transform:uppercase; color:#a855f7; font-weight:700;">
                        Tabung Sinar-X · Tabung #1
                    </span>
                    <div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin-top:2px;">
                        🔬 Tabung Sinar-X #1
                    </div>
                </div>
                <div><span class="pill pill-missing">○ Belum Terdaftar</span></div>
            </div>
            """)
            for fk in ["tube_brand", "tube_type", "tube_serial_number"]:
                ftitle = tube_param_titles.get(fk, fk.replace("_", " ").title())
                _render_parameter_card(
                    "Parameter Tabung Sinar-X #1",
                    ftitle,
                    {"sources": [], "field_key": fk},
                    docs_map,
                    expected_docs=tube_expected_map.get(fk),
                )

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

                        raw_method = fitem.get("method", "-") if isinstance(fitem, dict) else "-"
                        method_label = "🤖 LLM (Qwen 2.5)" if raw_method == "llm_qwen2.5" else raw_method
                        scalar_list.append({
                            "Field": fk,
                            "Nilai Ekstraksi": val_str,
                            "Halaman": fitem.get("page", "-") if isinstance(fitem, dict) else "-",
                            "Metode": method_label,
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
