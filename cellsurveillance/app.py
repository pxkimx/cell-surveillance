"""Cell Surveillance app. Start it by double-clicking Cell Surveillance.app, or with `cell-surveillance app`."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import subprocess
import sys
import zipfile

import cv2
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cellsurveillance import __version__, history, lifecycle, theme  # noqa: E402
from cellsurveillance.cli import default_outdir  # noqa: E402
from cellsurveillance.config import Config  # noqa: E402
from cellsurveillance.hero import background_html  # noqa: E402
from cellsurveillance.io import TIFF_EXT, VIDEO_EXT, extract_signal, find_scale_bar, iter_frames, load_movie  # noqa: E402
from cellsurveillance.pipeline import INTERNAL, load_results, recalibrate, recall  # noqa: E402
from cellsurveillance.report import FATE_LABELS, FUTURE, write_pdf  # noqa: E402
from cellsurveillance.roi import MEMBERSHIP, cells_in_roi, export_roi, subset  # noqa: E402
from cellsurveillance.rupture import MODES, signal_column  # noqa: E402
from cellsurveillance.segment import make_params, segment_frame  # noqa: E402
from cellsurveillance.style import STATE_RGB  # noqa: E402
from cellsurveillance.viz import boundaries, cell_strip  # noqa: E402

st.set_page_config(page_title="Cell Surveillance", page_icon="🔬", layout="wide", initial_sidebar_state="collapsed")

# The app is dark, like the microscope room, until the user picks Light. The PDF report keeps the printable palette in style.py.
THEME = theme.current()
P = theme.PALETTES[THEME]
INK, INK_2, MUTED = P["chart_ink"], P["chart_ink2"], P["chart_muted"]
SURFACE, PANEL = P["chart_surface"], P["chart_hover"]
GRID, AXIS = P["chart_grid"], P["chart_axis"]
BLUE, ORANGE, AQUA = P["blue"], P["orange"], P["aqua"]            # chart series
NEUTRAL = P["neutral"]
ACCENT = P["accent"]
EVENT_COLORS = {"rupture": BLUE, "division": ORANGE, "death": AQUA}

CSS = """
<style>
__ROOT__
html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Segoe UI", sans-serif; }
.stApp { background: var(--bg); isolation: isolate; }
.block-container { padding-top: 1.3rem; padding-bottom: 4rem; max-width: 1380px; position: relative; --veil: 150px; }

/* ---- the animated field behind everything: fixed to the window, under the page, never in the way of a click */
div[data-testid="stElementContainer"]:has(> iframe[data-testid="stIFrame"]) { position: fixed !important; inset: 0;
    width: 100vw !important; height: 100vh !important; margin: 0; z-index: -2; pointer-events: none; opacity: 1 !important; }
div[data-testid="stElementContainer"]:has(> iframe[data-testid="stIFrame"]) > iframe { width: 100% !important; height: 100% !important;
    border: 0; display: block; }
/* a veil over the field wherever there is something to read; it starts below the heading and moves with the page */
.block-container::before { content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none; background: var(--veil);
    -webkit-mask-image: linear-gradient(90deg, transparent, #000 4.5rem, #000 calc(100% - 4.5rem), transparent),
                        linear-gradient(180deg, transparent calc(var(--veil) - 80px), #000 calc(var(--veil) + 60px));
    mask-image: linear-gradient(90deg, transparent, #000 4.5rem, #000 calc(100% - 4.5rem), transparent),
                linear-gradient(180deg, transparent calc(var(--veil) - 80px), #000 calc(var(--veil) + 60px));
    -webkit-mask-composite: source-in; mask-composite: intersect; }
.block-container:has(.cs-hero) { --veil: 470px; }
.block-container:has(.cs-hero.compact) { --veil: 300px; }
.cs-hero { padding: 3.2rem 0 4.2rem; max-width: 600px; pointer-events: none; position: relative; }
.cs-hero::before { content: ""; position: absolute; inset: 0 -9rem 0 -6rem; z-index: -1;
                   background: radial-gradient(ellipse at 38% 50%, var(--hero-glow), var(--hero-glow2) 45%, transparent 72%); }
.cs-hero .k { margin: 0 0 .8rem; color: var(--accent); font: 800 .7rem/1 var(--mono); letter-spacing: .16em; text-transform: uppercase;
              text-shadow: var(--hero-text-shadow); }
.cs-hero h1 { margin: 0 0 .8rem; padding: 0; font: 500 3.5rem/1 Georgia, "Times New Roman", serif !important; letter-spacing: -.035em;
              text-shadow: var(--hero-shadow); }
.cs-hero .d { margin: 0; color: var(--hero-desc); font-size: .98rem; line-height: 1.55; text-shadow: var(--hero-text-shadow); }
.cs-hero.compact { padding: 1rem 0 1.6rem; }
.cs-hero.compact h1 { font-size: 2.1rem !important; margin: 0; } .cs-hero.compact .d { display: none; } .cs-hero.compact .k { margin-bottom: .5rem; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"], #MainMenu, footer { display:none !important; }
h1, h2, h3, h4, h5 { font-family: Georgia, "Times New Roman", serif; font-weight: 500; letter-spacing: -.025em; color: var(--ink); }

/* ---- brand bar */
.cs-top { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:.9rem; }
.cs-brand { display:flex; align-items:center; gap:.8rem; }
.cs-mark { width:44px; height:44px; border-radius:13px; position:relative; flex:none; overflow:hidden;
           background: linear-gradient(145deg,#1b2d52,#07131a); border:1px solid rgba(255,255,255,.14);
           box-shadow: 0 0 0 1px rgba(45,212,191,.18), 0 8px 26px rgba(45,212,191,.22); }
.cs-mark i { position:absolute; left:11px; top:13px; width:22px; height:17px; border-radius:50%; background:#58f082;
             box-shadow:0 0 12px rgba(88,240,130,.9); transform:rotate(-24deg); animation: cs-breathe 3.6s ease-in-out infinite; }
.cs-mark b { position:absolute; left:8px; top:10px; width:28px; height:23px; border-radius:50%; border:2px solid var(--cyan);
             transform:rotate(-24deg); }
.cs-mark u { position:absolute; right:7px; top:8px; width:9px; height:9px; border-radius:50%; background:var(--pink);
             border:1.5px solid #fff; animation: cs-ping 2.4s ease-out infinite; }
@keyframes cs-breathe { 0%,100% { opacity:1; transform:rotate(-24deg) scale(1);} 50% { opacity:.78; transform:rotate(-24deg) scale(.93);} }
@keyframes cs-ping { 0% { box-shadow:0 0 0 0 rgba(255,64,129,.75);} 70%,100% { box-shadow:0 0 0 11px rgba(255,64,129,0);} }
.cs-name { font: 500 1.5rem/1 Georgia, serif; letter-spacing:-.03em; color:var(--ink); }
.cs-tag { margin-top:5px; font: 700 .64rem/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--accent); }
.cs-status { display:flex; align-items:center; gap:.55rem; font: 600 .7rem/1.3 var(--mono); letter-spacing:.07em;
             color:var(--ink2); text-transform:uppercase; text-align:right; }
.cs-led { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px var(--accent);
          animation: cs-led 2s ease-in-out infinite; flex:none; }
.cs-led.warn { background:#fab219; box-shadow:0 0 10px #fab219; }
@keyframes cs-led { 0%,100% { opacity:1;} 50% { opacity:.35;} }

/* ---- top navigation */
div[data-testid="stButtonGroup"] { margin:.1rem 0 .2rem; }
div[data-testid="stButtonGroup"] button { font: 700 .74rem/1 var(--mono) !important; letter-spacing:.09em; text-transform:uppercase;
    padding:.72rem 1.15rem !important; border-color:var(--line) !important; background:var(--nav-bg) !important;
    color:var(--ink2) !important; transition: all .18s ease; }
div[data-testid="stButtonGroup"] button:hover { color:var(--nav-ink-hover) !important; border-color:var(--accent) !important;
    box-shadow: 0 0 0 1px rgba(45,212,191,.35), 0 6px 22px rgba(45,212,191,.16); transform: translateY(-1px); }
div[data-testid="stButtonGroup"] button[kind="segmented_controlActive"],
div[data-testid="stButtonGroup"] button[aria-checked="true"], div[data-testid="stButtonGroup"] button[aria-pressed="true"] {
    background: var(--nav-active) !important; color:var(--nav-active-ink) !important;
    border-color: var(--accent) !important; box-shadow: 0 0 18px rgba(45,212,191,.28); }
.cs-scan { height:2px; margin:.5rem 0 1.3rem; border-radius:2px; position:relative; overflow:hidden; background:var(--scan); }
.cs-scan::after { content:""; position:absolute; top:0; bottom:0; width:24%; left:0; transform:translateX(-100%);
    background:linear-gradient(90deg, transparent, var(--accent), transparent); animation: cs-scan 4.2s linear infinite; will-change: transform; }
@keyframes cs-scan { to { transform:translateX(417%); } }

/* ---- setup steps */
.cs-steps { display:grid; grid-template-columns:repeat(4,1fr); gap:0; margin:1.1rem 0 .9rem; }
.cs-stepper { position:relative; padding:0 .6rem 0 0; }
.cs-stepper .dot { width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center;
    font: 800 .74rem/1 var(--mono); color:var(--ink2); border:1.5px solid var(--line); background:var(--panel); position:relative; z-index:1; }
.cs-stepper::before { content:""; position:absolute; left:30px; right:0; top:14px; height:2px; background:var(--line); }
.cs-stepper:last-child::before { display:none; }
.cs-stepper.done .dot { background:var(--accent); border-color:var(--accent); color:#04201c; box-shadow:0 0 14px rgba(45,212,191,.55); }
.cs-stepper.done::before { background:linear-gradient(90deg, var(--accent), rgba(45,212,191,.25)); }
.cs-stepper.now .dot { border-color:var(--pink); color:#fff; animation: cs-ping 2s ease-out infinite; }
.cs-stepper .t { margin-top:.5rem; font: 700 .68rem/1.2 var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--ink); }
.cs-stepper .s { margin-top:.2rem; font-size:.78rem; color:var(--muted); }
.cs-stepper.done .s { color:var(--accent); }

/* ---- panels */
div[data-testid="stVerticalBlockBorderWrapper"] { border-color: var(--line) !important; border-radius:16px !important;
    background: var(--panel-grad);
    transition: border-color .2s ease, box-shadow .2s ease; animation: cs-rise .5s ease both; }
div[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: rgba(45,212,191,.55) !important;
    box-shadow: 0 14px 40px rgba(0,0,0,.35), 0 0 0 1px rgba(45,212,191,.12); }
@keyframes cs-rise { from { opacity:0; transform: translateY(10px);} to { opacity:1; transform:none;} }
.cs-kicker { margin:0 0 .55rem; font: 800 .66rem/1 var(--mono); letter-spacing:.15em; text-transform:uppercase; color:var(--accent); }
.cs-kicker em { font-style:normal; color:var(--muted); margin-right:.5rem; }

[data-testid="stFileUploaderDropzone"] { border:1.5px dashed rgba(131,207,210,.5) !important; border-radius:14px !important;
    background: repeating-linear-gradient(135deg, rgba(45,212,191,.05) 0 12px, transparent 12px 24px), var(--drop-bg) !important;
    transition: all .2s ease; }
[data-testid="stFileUploaderDropzone"] button { display:none !important; }
[data-testid="stFileUploaderDropzoneInstructions"] small { display:none; }
[data-testid="stFileUploaderDropzone"]:hover { border-color:var(--accent) !important; box-shadow: inset 0 0 40px rgba(45,212,191,.14); }

/* ---- readouts */
.cs-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:.8rem; margin:.2rem 0 1.3rem; }
.cs-tile { position:relative; overflow:hidden; border:1px solid var(--line); border-radius:16px; padding:1rem 1.1rem .95rem;
           background: var(--tile-grad); animation: cs-rise .55s ease both; }
.cs-tile:nth-child(2) { animation-delay:.06s; } .cs-tile:nth-child(3) { animation-delay:.12s; }
.cs-tile:nth-child(4) { animation-delay:.18s; } .cs-tile:nth-child(5) { animation-delay:.24s; }
.cs-tile:nth-child(6) { animation-delay:.30s; }
.cs-tile::before { content:""; position:absolute; left:0; top:0; height:2px; width:100%;
    background:linear-gradient(90deg, var(--c, var(--accent)), transparent 70%); }
.cs-tile::after { content:""; position:absolute; inset:0; background:linear-gradient(100deg, transparent 35%, var(--sheen) 50%, transparent 65%);
    transform:translateX(-100%); animation: cs-sheen 5s ease-in-out infinite; }
@keyframes cs-sheen { 0%,70% { transform:translateX(-100%);} 100% { transform:translateX(100%);} }
.cs-tile .l { font: 700 .64rem/1.2 var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }
.cs-tile .v { font: 500 2.15rem/1.15 Georgia, serif; letter-spacing:-.03em; color:var(--ink); margin:.3rem 0 .1rem; }
.cs-tile .n { font-size:.76rem; color:var(--ink2); }
.cs-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:.4rem; }
.cs-card { border:1px solid var(--line); border-radius:16px; padding:1.1rem 1.2rem; height:100%;
           background:var(--card-grad); animation: cs-rise .5s ease both; }
.cs-card b { display:block; margin-bottom:.3rem; font: 500 1.12rem/1.2 Georgia, serif; color:var(--ink); }
.cs-card span { color:var(--ink2); font-size:.86rem; line-height:1.55; }
.cs-card .k { font: 800 .62rem/1 var(--mono); letter-spacing:.15em; color:var(--accent); text-transform:uppercase; margin-bottom:.6rem; display:block; }
.cs-soon { border:1px dashed rgba(131,207,210,.4); border-radius:12px; padding:.7rem .9rem; color:var(--ink2); font-size:.84rem; margin-bottom:.5rem; }
.cs-soon b { color:var(--ink); }
.cs-note { color:var(--ink2); font-size:.86rem; }
.cs-title { display:flex; align-items:baseline; gap:.8rem; flex-wrap:wrap; margin:.1rem 0 .15rem; }
.cs-title h2 { margin:0; font-size:1.7rem; }
.cs-meta { font: 600 .72rem/1.5 var(--mono); letter-spacing:.04em; color:var(--muted); }

/* ---- history */
.cs-hist { display:flex; gap:.9rem; align-items:center; }
.cs-hist img { width:92px; height:92px; object-fit:cover; border-radius:12px; border:1px solid var(--line); flex:none; }
.cs-hist .nm { font: 500 1.05rem/1.2 Georgia, serif; color:var(--ink); word-break:break-word; }
.cs-hist .dt { font: 600 .64rem/1.4 var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:.25rem 0 .35rem; }
.cs-hist .nums { font-size:.8rem; color:var(--ink2); }
.cs-chip { display:inline-block; padding:.12rem .5rem; border-radius:999px; font: 700 .62rem/1.5 var(--mono); letter-spacing:.05em;
           border:1px solid var(--line); color:var(--ink2); margin-right:.3rem; }
.cs-chip.ok { border-color:rgba(45,212,191,.6); color:var(--accent); } .cs-chip.no { border-color:rgba(250,178,25,.6); color:var(--chip-warn); }

/* ---- the Animation switch beside the menu never wraps its label */
.st-key-animate, .st-key-animate *, .st-key-theme_pick * { white-space: nowrap; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-animate) { flex-wrap: nowrap !important; align-items: flex-start; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-animate) > div[data-testid="stColumn"] {
    flex: 1 1 0 !important; min-width: 0 !important; width: auto !important; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-animate) > div[data-testid="stColumn"]:has(.st-key-animate),
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-animate) > div[data-testid="stColumn"]:has(.st-key-theme_pick) {
    flex: 0 0 auto !important; min-width: max-content !important; }
div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-animate) > div[data-testid="stColumn"]:has(.st-key-animate) { padding-top: .45rem; }
.st-key-animate { display: flex; justify-content: flex-end; }
.st-key-theme_pick div[data-testid="stButtonGroup"] { border: 1px solid var(--line); border-radius: 999px; padding: 2px; background: var(--nav-bg); }
.st-key-theme_pick div[data-testid="stButtonGroup"] button { border-radius: 999px !important; border-color: transparent !important; background: transparent !important;
    padding: .5rem .8rem !important; }

/* ---- controls */
.stButton > button, .stDownloadButton > button { border-radius:12px; font-weight:700; letter-spacing:.01em; transition: all .18s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-1px); box-shadow:0 8px 24px rgba(45,212,191,.2); }
.stButton > button[kind="primary"] { background: linear-gradient(135deg, var(--accent), var(--cyan)); border:0; color:var(--primary-ink); }
.stButton > button[kind="primary"]:disabled { background: rgba(131,207,210,.14); color: var(--muted); }
div[data-testid="stProgress"] > div > div > div > div { background: linear-gradient(90deg, #2dd4bf, #5ac8ff); box-shadow:0 0 14px rgba(45,212,191,.7); }
div[data-testid="stMetric"] { border:1px solid var(--line); border-radius:14px; padding:.8rem 1rem; background:var(--metric-bg); }
div[data-testid="stMetricValue"] { font-family: Georgia, serif; }
div[data-testid="stImage"] img, video { border-radius:14px; border:1px solid var(--line); background:var(--media-bg); }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>
"""
st.markdown(CSS.replace("__ROOT__", theme.css_variables(THEME)), unsafe_allow_html=True)
S = st.session_state
if "animate" not in S:
    S.animate = bool(history.preferences().get("animate", True))
if "theme_pick" not in S:
    S.theme_pick = THEME
# The animated field is the background of every page. It is always the same element in the same place,
# so it keeps running while the rest of the page is redrawn. Switched off, it is a single still picture.
# The same page tells the server when the window is closed, so that the app can quit completely (see lifecycle.py).
components.html(background_html(animate=S.animate, close_url=lifecycle.start(), theme=THEME), height=0)

MEASURE_OPTIONS = [
    ("rupture", "Nuclear rupture", "number, duration, size and timing of each rupture"),
    ("movement", "Cell movement", "distance, speed, persistence, mode of migration"),
    ("division", "Cell division", "divisions, lineage, daughter symmetry"),
    ("death", "Cell death", "deaths and when they happened"),
    ("morphology", "Nuclear shape", "area, roundness, lobulation, fragments, micronuclei"),
    ("neighbors", "Crowding", "distance to neighbours and local density"),
]
DROP_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "Cell Surveillance", "Dropped movies")
S = st.session_state
S.setdefault("movie", "")
S.setdefault("results_dir", "")
S.setdefault("roi", None)


def open_results(folder: str, view: str = "Overview") -> bool:
    folder = folder.rstrip("/")
    meta_path = os.path.join(folder, INTERNAL, "meta.json")
    if not os.path.exists(meta_path):
        return False
    with open(meta_path) as fh:
        S.movie = history.locate_movie(folder, json.load(fh))
    S.results_dir, S.roi, S.go = folder, None, view
    return True


asked = st.query_params.get("results")
if asked and not S.get("_asked_done"):
    open_results(asked, st.query_params.get("view") or "Overview")
    S._asked_done = True


# ----------------------------------------------------------------------------- helpers
def kicker(number: str, text: str):
    st.markdown(f'<p class="cs-kicker"><em>{number}</em>{text}</p>', unsafe_allow_html=True)


def tiles(items):
    colors = {"rupture": BLUE, "division": ORANGE, "death": AQUA}
    html = ""
    for item in items:
        l, v, n = item[:3]
        c = colors.get(item[3]) if len(item) > 3 else None
        style = f' style="--c:{c}"' if c else ""
        html += f'<div class="cs-tile"{style}><div class="l">{l}</div><div class="v">{v}</div><div class="n">{n}</div></div>'
    st.markdown(f'<div class="cs-grid">{html}</div>', unsafe_allow_html=True)


def choose_file(folder: bool = False) -> str:
    """Native macOS file dialog."""
    if sys.platform != "darwin":
        return ""
    script = ('POSIX path of (choose folder with prompt "Choose a results folder")' if folder else
              'POSIX path of (choose file with prompt "Choose a movie")')
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
        return out.stdout.strip()
    except Exception:
        return ""


@st.cache_data(show_spinner=False)
def movie_info(path: str, mtime: float) -> dict:
    cap = cv2.VideoCapture(path)
    info = dict(n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), w=int(cap.get(3)), h=int(cap.get(4)), fps=cap.get(5))
    ok, first = cap.read()
    cap.release()
    if not ok:
        first = next(iter_frames(path))
        info.update(n=0, h=first.shape[0], w=first.shape[1])
    bar = find_scale_bar(first)
    info["bar"], info["bar_px"] = bar, (bar[2] if bar else None)
    if bar:                                   # a close-up of the candidate, for the user to confirm
        x, y, w, h = bar
        pad_x, pad_y = max(w // 3, 30), 45
        x0, y0 = max(x - pad_x, 0), max(y - pad_y, 0)
        crop = cv2.cvtColor(first[y0:y + h + pad_y, x0:x + w + pad_x], cv2.COLOR_BGR2RGB).copy()
        cv2.rectangle(crop, (x - x0 - 4, y - y0 - 4), (x - x0 + w + 3, y - y0 + h + 3), (255, 64, 129), 2)
        info["bar_image"] = crop
    return info


@st.cache_data(show_spinner=False)
def read_frame(path: str, index: int, mtime: float, crop: tuple = None) -> np.ndarray:
    """One frame of the movie. `crop` (x0, y0, x1, y1) is the part that was analysed, when it was not the whole image."""
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        frame = next(iter_frames(path))
    if crop:
        x0, y0, x1, y1 = [int(v) for v in crop]
        frame = frame[y0:y1, x0:x1]
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


@st.cache_data(show_spinner="Finding nuclei in this frame…")
def preview_outlines(path: str, index: int, mtime: float, cfg_dict: dict):
    cfg = Config.from_dict(cfg_dict)
    cfg.input.max_frames = 3
    movie = load_movie(path, cfg, log=lambda *a: None)
    p = make_params(movie, cfg, log=lambda *a: None)
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    sig = extract_signal(frame, movie.channel, movie.composite, cfg.input.mask_overlays)
    labels = segment_frame(sig, p, movie.exclude)
    return (boundaries(labels, thick=True), int(labels.max()), 2 * p.radius * movie.pixel_size_um,
            "µm" if movie.units == "um" else "px")


@st.cache_resource(show_spinner="Loading results…")
def get_results(outdir: str, stamp: float):
    return load_results(outdir, with_labels=True, recompute=False)


@st.cache_resource(show_spinner="Loading movie…")
def get_signal(path: str, mtime: float, cfg_yaml: str):
    cfg = Config.load(cfg_yaml)
    return load_movie(path, cfg, log=lambda *a: None).signal


@st.cache_data(show_spinner=False)
def thumbnail(outdir: str, stamp: float) -> str:
    path = os.path.join(outdir, INTERNAL, "thumbnail.jpg")
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()


def base_layout(fig, height=300, title=None, x=None, y=None, legend=False):
    top = (74 if legend else 44) if title else 12
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=top, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="-apple-system, Helvetica Neue, Arial", size=12, color=INK_2),
                      title=dict(text=title or "", font=dict(size=15, color=INK, family="Georgia, serif"), x=0,
                                 xanchor="left", y=0.97, yanchor="top"),
                      showlegend=legend, legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0,
                                                     font=dict(color=INK_2)),
                      hoverlabel=dict(bgcolor="#0e2229", bordercolor=ACCENT, font=dict(size=12, color=INK)), bargap=0.12)
    fig.update_xaxes(title=x, showgrid=False, linecolor=AXIS, ticks="", zeroline=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(title=y, gridcolor=GRID, linecolor="rgba(0,0,0,0)", ticks="", zeroline=False, rangemode="tozero",
                     tickfont=dict(color=MUTED))
    return fig


def hist(values, color, title, x, nbins=24, hover="%{y} at %{x}"):
    v = pd.Series(values).dropna()
    fig = go.Figure(go.Histogram(x=v, nbinsx=nbins, marker=dict(color=color, line=dict(color=SURFACE, width=1.5)),
                                 hovertemplate=hover + "<extra></extra>"))
    if len(v):
        fig.add_vline(x=float(v.median()), line=dict(color=INK_2, width=1))
        fig.add_annotation(x=float(v.median()), y=1, yref="paper", text=f"median {v.median():.3g}", showarrow=False,
                           xanchor="left", yanchor="top", xshift=5, font=dict(size=11, color=INK_2))
    return base_layout(fig, title=title, x=x, y="count")


def draw_frame(rgb, outline=None, roi=None, max_w=1100):
    img = rgb.copy()
    if outline is not None:
        img[outline] = STATE_RGB["intact"]
    if roi:
        x0, y0, x1, y1 = [int(v) for v in roi]
        dim = (img * 0.45).astype(np.uint8)
        dim[y0:y1, x0:x1] = img[y0:y1, x0:x1]
        img = dim
        cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 255), max(2, img.shape[1] // 500))
    return img


def current_config() -> Config:
    """Settings from the setup page. Calibration values are only ever what the user entered for this movie."""
    cfg = Config()
    cal = S.get("calibration", {})
    cfg.calibration.frame_interval_min = cal.get("interval_min")
    cfg.calibration.scale_bar_um = cal.get("scale_bar_um")
    cfg.calibration.pixel_size_um = cal.get("pixel_size_um")
    cfg.calibration.interval_confirmed = cal.get("interval_min") is not None
    cfg.calibration.size_confirmed = bool(cal.get("scale_bar_um") or cal.get("pixel_size_um"))
    for key, _, _ in MEASURE_OPTIONS:
        setattr(cfg.analysis, key, bool(S.get(f"m_{key}", True)))
    cfg.output.overlay_video = bool(S.get("out_video", True))
    cfg.output.pdf_report = bool(S.get("out_pdf", True))
    cfg.rupture.mode = S.get("r_mode", "ratio_rise")
    cfg.rupture.threshold = None if S.get("r_auto", True) else float(S.get("r_thr", 0.1))
    return cfg


def run_analysis(path: str, outdir: str, cfg: Config):
    os.makedirs(outdir, exist_ok=True)
    cfg_path = os.path.join(outdir, "settings_requested.yaml")
    cfg.save(cfg_path)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, "-W", "ignore", "-m", "cellsurveillance", "analyze", path, "-o", outdir, "--config", cfg_path,
           "--progress", "--interval-min", repr(float(cfg.calibration.frame_interval_min))]
    if cfg.calibration.scale_bar_um:
        cmd += ["--scale-bar-um", repr(float(cfg.calibration.scale_bar_um))]
    elif cfg.calibration.pixel_size_um:
        cmd += ["--pixel-size", repr(float(cfg.calibration.pixel_size_um))]
    else:
        cmd.append("--uncalibrated")
    if not cfg.output.overlay_video:
        cmd.append("--no-video")
    if not cfg.output.pdf_report:
        cmd.append("--no-pdf")
    bar = st.progress(0.0, text="Starting…")
    log_box = st.empty()
    lines = []
    # a lower priority, so that the rest of the computer stays responsive while every core is segmenting
    # and its own process group, so that quitting the app stops the analysis and its workers with it
    proc = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                            start_new_session=True, preexec_fn=lambda: os.nice(10),
                            env={**os.environ, lifecycle.APP_ENV: str(os.getpid())})
    lifecycle.register_child(proc)
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith("@@PROGRESS"):
            _, frac, stage = line.split(" ", 2)
            bar.progress(min(float(frac), 1.0), text=stage + "…")
        elif line.strip():
            lines.append(line.strip())
            log_box.caption(" · ".join(lines[-2:]))
    proc.wait()
    bar.empty()
    log_box.empty()
    if proc.returncode != 0:
        st.error("The analysis did not finish.\n\n" + "\n".join(lines[-8:]))
        return False
    return True


# ----------------------------------------------------------------------------- what is loaded
res = None
if S.results_dir and os.path.exists(os.path.join(S.results_dir, INTERNAL, "meta.json")):
    res = get_results(S.results_dir, os.path.getmtime(os.path.join(S.results_dir, INTERNAL, "meta.json")))
elif S.results_dir:
    S.results_dir = ""

# ----------------------------------------------------------------------------- brand bar and top menu
if res is not None:
    confirmed = res.meta.get("interval_confirmed") and res.meta.get("size_confirmed")
    status = (f'<span class="cs-led{"" if confirmed else " warn"}"></span><span>{res.meta["movie"]}<br>'
              f'{"calibrated" if confirmed else "calibration not confirmed"}</span>')
else:
    status = '<span class="cs-led"></span><span>ready<br>no movie loaded</span>'
st.markdown('<div class="cs-top"><div class="cs-brand"><div class="cs-mark"><i></i><b></b><u></u></div><div>'
            '<div class="cs-name">Cell Surveillance</div>'
            f'<div class="cs-tag">single-cell tracking · v{__version__}</div></div></div>'
            f'<div class="cs-status">{status}</div></div>', unsafe_allow_html=True)

menu = ["Setup"]
if res is not None:
    an_ = res.cfg.analysis
    menu += ["Overview"] + (["Ruptures"] if an_.rupture else []) + (["Movement"] if an_.movement else []) + \
            (["Division & death"] if (an_.division or an_.death) else []) + ["Cells", "Region", "Export"]
menu.append("History")
if S.get("go"):                                   # a button asked to switch view
    S.view = S.pop("go")
if S.get("view") not in menu:
    S.view = "Overview" if res is not None else "Setup"
menu_col, theme_col, anim_col = st.columns([8, 1.3, 1.3], vertical_alignment="center")
with menu_col:
    view = st.segmented_control("Menu", menu, label_visibility="collapsed", key="view") or S.view


def pick_theme():
    """Remember the look and start the server again in it (Streamlit reads its widget theme only at start-up)."""
    if S.theme_pick not in theme.THEMES or S.theme_pick == THEME:
        return
    history.set_preference("theme", S.theme_pick)
    lifecycle.relaunch(int(st.get_option("server.port")), bool(st.get_option("server.headless")))


theme_col.segmented_control("Look", ["light", "dark"], format_func=lambda t: {"light": "☀\u00a0Light", "dark": "☾\u00a0Dark"}[t],
                            key="theme_pick", label_visibility="collapsed", on_change=pick_theme,
                            help="Light or dark look. The choice is remembered; the page reconnects in a few seconds.")
anim_col.toggle("Animation", key="animate", on_change=lambda: history.set_preference("animate", S.animate),
                help="The moving background. It rests by itself while this window is in the background and while a "
                     "movie is being analysed. Switch it off for a still picture that uses no processor time.")
st.markdown('<div class="cs-scan"></div>', unsafe_allow_html=True)

# ----------------------------------------------------------------------------- history
if view == "History":
    found = history.entries()
    st.markdown('<div class="cs-title"><h2>Earlier analyses</h2>'
                f'<span class="cs-meta">{len(found)} saved</span></div>', unsafe_allow_html=True)
    st.caption("Every analysis is kept. Analysing a movie again moves the earlier results to an 'earlier runs' folder "
               "instead of replacing them.")
    top_l, top_r = st.columns([3, 1])
    query = top_l.text_input("Search", placeholder="Search by movie name", label_visibility="collapsed")
    if top_r.button("Open a results folder…", width="stretch"):
        picked = choose_file(folder=True)
        if picked and open_results(picked):
            history.register(picked)
            st.rerun()
        elif picked:
            st.warning("That folder has no Cell Surveillance results.")
    if query:
        found = [e for e in found if query.lower() in (e["movie"] + " " + (e.get("title") or "")).lower()]
    if not found:
        st.info("Nothing here yet. Analyses appear in this list as soon as they finish.")
    cols = st.columns(3)
    for i, e in enumerate(found):
        with cols[i % 3].container(border=True):
            when = dt.datetime.fromisoformat(e["analysed_at"]).strftime("%d %b %Y · %H:%M")
            img = thumbnail(e["outdir"], os.path.getmtime(os.path.join(e["outdir"], INTERNAL, "meta.json")))
            picture = f'<img src="{img}" alt="">' if img else ""
            nums = " · ".join(f"{e[k]} {k}" for k in ("cells", "ruptures", "divisions", "deaths") if e.get(k) is not None)
            chips = (f'<span class="cs-chip {"ok" if e["interval_confirmed"] else "no"}">'
                     f'{e["interval_min"]:g} min/frame{"" if e["interval_confirmed"] else " ?"}</span>'
                     f'<span class="cs-chip {"ok" if e["size_confirmed"] else "no"}">'
                     f'{"scale ok" if e["size_confirmed"] else "scale ?"}</span>'
                     + ('<span class="cs-chip">earlier run</span>' if e["earlier_run"] else ""))
            st.markdown(f'<div class="cs-hist">{picture}<div><div class="nm">{e.get("title") or e["movie"]}</div>'
                        f'<div class="dt">{when}</div><div class="nums">{nums}</div>'
                        f'<div style="margin-top:.4rem">{chips}</div></div></div>', unsafe_allow_html=True)
            b1, b2 = st.columns([2, 1])
            if b1.button("Open", key=f"open_{e['outdir']}", type="primary", width="stretch"):
                open_results(e["outdir"])
                st.rerun()
            if b2.button("Hide", key=f"hide_{e['outdir']}", width="stretch",
                         help="Remove from this list. The files stay where they are."):
                history.forget(e["outdir"])
                st.rerun()
    st.stop()

# ----------------------------------------------------------------------------- setup
if view == "Setup":
    st.markdown(f'<div class="cs-hero{" compact" if S.movie else ""}"><p class="k">Live-cell imaging · single-cell tracking</p>'
                '<h1>Follow every cell.</h1><p class="d">Every nucleus is tracked through the movie. Ruptures, movement, '
                'divisions and deaths are measured cell by cell.</p></div>', unsafe_allow_html=True)

    path = S.movie
    ok = bool(path) and os.path.isfile(path) and os.path.splitext(path)[1].lower() in VIDEO_EXT | TIFF_EXT
    info = movie_info(path, os.path.getmtime(path)) if ok else None
    stepper = st.empty()
    c1, c2, c3, c4 = st.columns([1.15, 1.15, 1, 1], gap="medium")

    with c1.container(border=True):
        kicker("01", "Movie")
        dropped = st.file_uploader("Drop a movie here", type=[e.lstrip(".") for e in sorted(VIDEO_EXT | TIFF_EXT)],
                                   label_visibility="collapsed", key="dropped",
                                   help="Drag a movie onto this box, or use Browse.")
        if dropped is not None and S.get("_dropped_id") != dropped.file_id:
            # a browser never reveals where a dropped file came from, so a copy is kept in the app's own folder
            os.makedirs(DROP_FOLDER, exist_ok=True)
            target = os.path.join(DROP_FOLDER, os.path.basename(dropped.name))
            if not (os.path.exists(target) and os.path.getsize(target) == dropped.size):
                with open(target, "wb") as fh:
                    fh.write(dropped.getbuffer())
            S._dropped_id = dropped.file_id
            S.movie, S.results_dir, S.roi = target, "", None
            st.rerun()
        if st.button("Choose a movie on this Mac…", width="stretch",
                     help="Uses the movie where it is, without copying it."):
            picked = choose_file()
            if picked:
                S.movie, S.results_dir, S.roi = picked, "", None
                st.rerun()
        typed = st.text_input("Movie file", value=S.movie, placeholder="or paste a path: /path/to/movie.mov",
                              label_visibility="collapsed")
        if typed != S.movie:
            S.movie, S.results_dir, S.roi = typed.strip().strip('"'), "", None
            st.rerun()
        if path and not ok:
            st.caption("⚠️ File not found, or not a movie (mov, mp4, avi, tif).")
        if info:
            st.caption(f"**{os.path.basename(path)}**  \n{info['n']} frames · {info['w']}×{info['h']} px")
            if path.startswith(DROP_FOLDER):
                st.caption("Dropped movies are copied to Documents › Cell Surveillance; results are saved beside them.")

    # Nothing in the calibration is pre-filled, and every widget is tied to the movie, so a value entered for one
    # movie is never carried over to the next.
    missing, calibration = [], {}
    with c2.container(border=True):
        kicker("02", "Calibrate")
        if not info:
            st.caption("Choose a movie first. The time between frames and the scale are asked for every movie.")
            missing.append("a movie")
        else:
            interval = st.number_input("Minutes between frames", min_value=0.0, value=None, step=1.0,
                                       placeholder="Enter for this movie", key=f"interval|{path}",
                                       help="The real time between two frames when this movie was recorded. It is "
                                            "not stored in the file and is different for every movie.")
            if interval and interval > 0:
                calibration["interval_min"] = float(interval)
            else:
                missing.append("minutes between frames")
            modes = ["Scale bar in the movie", "Pixel size", "No scale (report in pixels)"]
            mode = st.radio("Scale", modes, index=None, key=f"scale_mode|{path}",
                            help="Choose how the size of a pixel is known for this movie.")
            if mode == modes[0]:
                if info["bar"]:
                    st.image(info["bar_image"], width="stretch",
                             caption=f"Found this bar, {info['bar_px']} px long")
                    sure = st.checkbox("Yes, the outlined bar is the scale bar", key=f"bar_ok|{path}")
                    length = st.number_input("Length the bar represents (µm)", min_value=0.0, value=None,
                                             placeholder="Read it from the movie", key=f"bar_um|{path}")
                    if sure and length and length > 0:
                        calibration["scale_bar_um"] = float(length)
                        st.caption(f"= {length / info['bar_px']:.4g} µm per pixel")
                    else:
                        missing.append("scale bar confirmation and length")
                else:
                    st.caption("No scale bar was found in this movie. Choose **Pixel size** instead.")
                    missing.append("a scale")
            elif mode == modes[1]:
                px_um = st.number_input("Micrometres per pixel", min_value=0.0, value=None, step=0.01, format="%.4f",
                                        placeholder="From the microscope", key=f"px_um|{path}")
                if px_um and px_um > 0:
                    calibration["pixel_size_um"] = float(px_um)
                else:
                    missing.append("pixel size")
            elif mode is None:
                missing.append("a scale")
    S.calibration = calibration

    with c3.container(border=True):
        kicker("03", "Measure")
        for key, name, what in MEASURE_OPTIONS:
            st.checkbox(name, value=True, key=f"m_{key}", help=what.capitalize() + ".")
        with st.popover("Rupture threshold", width="stretch"):
            st.selectbox("A rupture is a…", list(MODES), format_func=lambda m: MODES[m][2], key="r_mode")
            st.checkbox("Choose the threshold automatically", value=True, key="r_auto")
            if not S.r_auto:
                ratio = MODES[S.r_mode][0] == "cn_ref"
                st.number_input("Threshold", min_value=0.0, value=0.10 if ratio else 25.0,
                                step=0.01 if ratio else 1.0, format="%.3f" if ratio else "%.1f", key="r_thr")
            st.caption("You can change this after the analysis without tracking again.")
        with st.popover("Outputs", width="stretch"):
            st.checkbox("Annotated movie", value=True, key="out_video")
            st.checkbox("PDF report", value=True, key="out_pdf")
            st.caption("Measurement tables (CSV) are always written.")
    n_measures = sum(bool(S.get(f"m_{k}", True)) for k, _, _ in MEASURE_OPTIONS)

    outdir = default_outdir(path) if ok else ""
    ready = ok and not missing
    with c4.container(border=True):
        kicker("04", "Run")
        checks = [("Movie chosen", ok), ("Minutes between frames", "interval_min" in calibration),
                  ("Scale", ok and not any(m for m in missing if "scale" in m or "pixel" in m)),
                  (f"{n_measures} measurements", n_measures > 0)]
        st.markdown("".join(f'<div style="font-size:.86rem;margin:.18rem 0;color:{"#c8d7d1" if d else "#8ea7a8"}">'
                            f'<span style="color:{"#2dd4bf" if d else "#fab219"};font-weight:800">{"✓" if d else "○"}</span>'
                            f'&nbsp; {t}</div>' for t, d in checks), unsafe_allow_html=True)
        st.write("")
        go_run = st.button("Analyse movie", type="primary", width="stretch", disabled=not ready)
        if ok and missing:
            st.caption("Still needed: " + ", ".join(missing) + ".")
        previous = ok and os.path.exists(os.path.join(outdir, INTERNAL, "meta.json"))
        if previous:
            if st.button("Open its last results", width="stretch"):
                open_results(outdir)
                st.rerun()
            st.caption("This movie was analysed before. Analysing again keeps those results under 'earlier runs'.")

    done = [ok, ok and not missing, ok and not missing and n_measures > 0, False]
    labels = [("Movie", os.path.basename(path) if ok else "drop or browse"),
              ("Calibrate", "entered" if done[1] else "time and scale"),
              ("Measure", f"{n_measures} selected"), ("Run", "ready" if ready else "waiting")]
    now = next((i for i, d in enumerate(done) if not d), 3)
    stepper.markdown('<div class="cs-steps">' + "".join(
        f'<div class="cs-stepper {"done" if done[i] else ("now" if i == now else "")}"><div class="dot">'
        f'{"✓" if done[i] else i + 1}</div><div class="t">{t}</div><div class="s">{s}</div></div>'
        for i, (t, s) in enumerate(labels)) + "</div>", unsafe_allow_html=True)

    if go_run and ready:
        with st.container(border=True):
            kicker("··", f"Analysing {os.path.basename(path)}")
            if run_analysis(path, outdir, current_config()):
                get_results.clear()
                open_results(outdir)
                st.rerun()

    if ok:
        st.markdown(f'<div class="cs-title"><h2>Preview</h2><span class="cs-meta">{os.path.basename(path)}</span></div>',
                    unsafe_allow_html=True)
        mtime = os.path.getmtime(path)
        left, right = st.columns([3, 1])
        with right:
            idx = st.slider("Frame", 1, max(info["n"], 1), 1) - 1
            show = st.toggle("Show detected nuclei", value=True)
            st.markdown('<p class="cs-note">This is what will be tracked. If nuclei are missed or merged, the '
                        'detection settings can be adjusted; see the README.</p>', unsafe_allow_html=True)
        with left:
            rgb = read_frame(path, idx, mtime)
            outline = None
            if show:
                try:
                    outline, n, diameter, units = preview_outlines(path, idx, mtime, current_config().to_dict())
                    right.metric("Nuclei in this frame", n)
                    right.metric("Typical diameter", f"{diameter:.1f} {units}")
                except Exception as err:  # preview must never block the analysis
                    right.caption(f"Preview unavailable: {err}")
            st.image(draw_frame(rgb, outline), width="stretch")
    else:
        cols = st.columns(3)
        cards = [("Track", "Every nucleus, every frame", "Nuclei are found, followed through the movie, and kept "
                  "apart when they touch. Dim or briefly lost nuclei are bridged."),
                 ("Detect", "Rupture, division, death", "A rupture is the reporter flooding the cytoplasm. You set "
                  "the threshold and see exactly which events it admits."),
                 ("Export", "Movie, report, tables", "Annotated movie, PDF report and CSV tables, for the whole field "
                  "or for a region you draw.")]
        for col, (k, t, d) in zip(cols, cards):
            col.markdown(f'<div class="cs-card"><span class="k">{k}</span><b>{t}</b><span>{d}</span></div>',
                         unsafe_allow_html=True)
        st.write("")
        with st.expander("Planned additions"):
            for name, what in FUTURE:
                st.markdown(f'<div class="cs-soon"><b>{name}</b> — {what}</div>', unsafe_allow_html=True)
    st.stop()

# ----------------------------------------------------------------------------- results
outdir = S.results_dir
meta, cells, events, frames, an = res.meta, res.cells, res.events, res.frames, res.cfg.analysis
u = "µm" if meta["units"] == "um" else "px"
hours = meta["n_frames"] * meta["interval_min"] / 60

head_l, head_r = st.columns([4, 1])
region = meta.get("crop")
region_note = (f' · region x {region[0]}–{region[2]}, y {region[1]}–{region[3]} px' if region else "")
head_l.markdown(f'<div class="cs-title"><h2>{meta["movie"]}</h2></div><div class="cs-meta">{meta["n_frames"]} frames · '
                f'{hours:.1f} h at {meta["interval_min"]:g} min per frame · {meta["pixel_size"]:.4g} {u}/px{region_note}</div>',
                unsafe_allow_html=True)
if head_r.button("Open results folder", width="stretch"):
    subprocess.run(["open", outdir])

# ----- calibration of these results: shown loudly until the user has supplied both values
unconfirmed = [name for name, key in (("time between frames", "interval_confirmed"), ("scale", "size_confirmed"))
               if not meta.get(key)]
if unconfirmed:
    st.warning("**Calibration not confirmed: " + " and ".join(unconfirmed) + ".** "
               + (f"These results assume {meta['interval_min']:g} minutes per frame, which was never entered for this "
                  "movie, so every time, duration and speed may be wrong. " if "time between frames" in unconfirmed else "")
               + ("Distances and areas rely on a scale that was not confirmed. " if "scale" in unconfirmed else "")
               + "Enter the real values below.")
with st.expander("Calibration of these results", expanded=bool(unconfirmed)):
    st.caption("Changing these does not repeat the tracking. Every time, speed, distance and area is recalculated, "
               "and the report and annotated movie are rebuilt.")
    k = f"|{outdir}"
    c1, c2, c3 = st.columns([1, 1.5, 0.8])
    new_interval = c1.number_input("Minutes between frames", min_value=0.0, step=1.0, key="re_interval" + k,
                                   value=float(meta["interval_min"]) if meta.get("interval_confirmed") else None,
                                   placeholder="Enter for this movie")
    options = (["Scale bar in the movie"] if meta.get("scale_bar_px") else []) + ["Pixel size", "Keep as it is"]
    how = c2.radio("Scale", options, index=len(options) - 1, horizontal=True, key="re_mode" + k)
    new_bar = new_px = None
    if how == "Scale bar in the movie":
        bar_info = movie_info(meta["path"], os.path.getmtime(meta["path"])) if os.path.exists(meta["path"]) else None
        if bar_info and bar_info.get("bar"):
            c2.image(bar_info["bar_image"], caption=f"Found this bar, {bar_info['bar_px']} px long")
        sure = c2.checkbox("Yes, the outlined bar is the scale bar", key="re_bar_ok" + k)
        length = c2.number_input("Length the bar represents (µm)", min_value=0.0, value=None,
                                 placeholder="Read it from the movie", key="re_bar" + k)
        new_bar = float(length) if (sure and length and length > 0) else None
    elif how == "Pixel size":
        value = c2.number_input("Micrometres per pixel", min_value=0.0, value=None, step=0.01, format="%.4f",
                                placeholder="From the microscope", key="re_px" + k)
        new_px = float(value) if value and value > 0 else None
    changed = (new_interval and new_interval > 0 and (not meta.get("interval_confirmed")
                                                       or abs(new_interval - meta["interval_min"]) > 1e-9)) \
        or new_bar is not None or new_px is not None
    c3.write("")
    c3.write("")
    if c3.button("Apply calibration", type="primary", width="stretch", disabled=not changed):
        bar = st.progress(0.0, text="Recalculating…")
        new = recalibrate(outdir, interval_min=float(new_interval) if new_interval and new_interval > 0 else None,
                          pixel_size_um=new_px, scale_bar_um=new_bar, log=lambda *a: None)
        new.labels = res.labels
        if os.path.exists(os.path.join(outdir, "report.pdf")):
            bar.progress(0.1, text="Writing report…")
            sig = get_signal(meta["path"], os.path.getmtime(meta["path"]), os.path.join(outdir, "settings_used.yaml"))
            write_pdf(new, os.path.join(outdir, "report.pdf"), signal=sig)
        if os.path.exists(os.path.join(outdir, "annotated_movie.mp4")):
            from cellsurveillance.viz import render_overlay
            render_overlay(new, os.path.join(outdir, "annotated_movie.mp4"),
                           progress=lambda f: bar.progress(0.2 + 0.8 * min(f, 1.0), text="Writing movie…"))
        bar.empty()
        get_results.clear()
        st.rerun()

if view == "Overview":
    items = [("Cells tracked", f"{len(cells):,}", f"{res.timecourse['n_cells'].iloc[0]} at start · "
                                                   f"{res.timecourse['n_cells'].iloc[-1]} at end")]
    if an.rupture:
        done = events[events["repaired"]] if len(events) else events
        items += [("Nuclear ruptures", f"{len(events):,}", f"{int(cells['ruptured'].sum())} cells · "
                                                            f"{cells['ruptured'].mean():.0%} of all"),
                  ("Median rupture duration", f"{done['duration_min'].median():.0f} min" if len(done) else "–",
                   "repaired ruptures")]
    if an.division:
        n_div = int((res.divisions["confidence"] == "high").sum()) if len(res.divisions) else 0
        items.append(("Divisions", f"{n_div}", "with mitotic signature"))
    if an.death:
        items.append(("Deaths", f"{int((cells['fate'] == 'death').sum())}", "inferred from the reporter"))
    if an.movement:
        items.append(("Mean speed", f"{cells['mean_speed_um_per_min'].mean():.2f}", f"{u} per minute"))
    tiles(items)

    left, right = st.columns([1.15, 1])
    with left:
        video = os.path.join(outdir, "annotated_movie.mp4")
        if os.path.exists(video):
            st.video(video, loop=True)
            st.markdown(
                "".join(f'<span class="cs-dot" style="background:rgb{STATE_RGB[k]}"></span>{n}&nbsp;&nbsp;&nbsp;'
                        for k, n in (("intact", "intact"), ("ruptured", "ruptured"), ("mitotic", "dividing"),
                                     ("death", "death"))), unsafe_allow_html=True)
        else:
            st.info("The annotated movie was not requested for this analysis.")
    with right:
        tc = res.timecourse
        fig = go.Figure()
        for col, name, key, on in (("cumulative_ruptures", "Ruptures", "rupture", an.rupture),
                                   ("cumulative_divisions", "Divisions", "division", an.division),
                                   ("cumulative_deaths", "Deaths", "death", an.death)):
            if on and col in tc:
                fig.add_trace(go.Scatter(x=tc["time_h"], y=tc[col], name=name, mode="lines",
                                         line=dict(color=EVENT_COLORS[key], width=2),
                                         hovertemplate=name + " %{y}<extra></extra>"))
        fig = base_layout(fig, height=250, title="Events so far", x="time (h)", y="events", legend=True)
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, width="stretch")
        if an.rupture:
            fig = go.Figure(go.Scatter(x=tc["time_h"], y=tc["fraction_ruptured"], mode="lines", fill="tozeroy",
                                       line=dict(color=BLUE, width=2), fillcolor="rgba(57,135,229,0.16)",
                                       hovertemplate="%{y:.1%} ruptured at %{x:.1f} h<extra></extra>"))
            fig = base_layout(fig, height=230, title="Cells ruptured at each time", x="time (h)", y="fraction")
            fig.update_yaxes(tickformat=".0%")
            st.plotly_chart(fig, width="stretch")
    with st.expander("All population measurements"):
        st.dataframe(res.summary.astype(str), width="stretch", hide_index=True)

if an.rupture:
    if view == "Ruptures":
        col = signal_column(res.cfg.rupture.mode)
        ratio = col == "cn_ref"
        st.markdown("##### What counts as a rupture")
        c1, c2, c3 = st.columns([1.6, 1.4, 0.8])
        mode = c1.selectbox("Measure", list(MODES), index=list(MODES).index(res.cfg.rupture.mode),
                            format_func=lambda m: MODES[m][2].capitalize())
        hi = float(res.sweep["threshold"].max()) if len(res.sweep) else (1.0 if ratio else 200.0)
        same = mode == res.cfg.rupture.mode
        thr = c2.slider("Threshold", 0.0, max(hi, float(meta["rupture_threshold"]) * 1.5),
                        float(meta["rupture_threshold"]) if same else hi / 4, step=0.005 if ratio else 1.0,
                        format="%.3f" if ratio else "%.0f",
                        help="Raise it to keep only large ruptures; lower it to include small leaks.")
        c3.write("")
        c3.write("")
        if c3.button("Apply", type="primary", width="stretch",
                     disabled=same and abs(thr - meta["rupture_threshold"]) < 1e-9):
            with st.spinner("Re-calling ruptures…"):
                new = recall(outdir, threshold=float(thr), mode=mode, log=lambda *a: None)
                new.labels = res.labels
                if os.path.exists(os.path.join(outdir, "report.pdf")):
                    sig = get_signal(meta["path"], os.path.getmtime(meta["path"]), os.path.join(outdir, "settings_used.yaml"))
                    write_pdf(new, os.path.join(outdir, "report.pdf"), signal=sig)
            get_results.clear()
            st.rerun()
        st.caption(f"Now using **{MODES[res.cfg.rupture.mode][2]} ≥ {meta['rupture_threshold']:.3g}**. "
                   "Applying a new threshold updates every table and the report; the annotated movie is refreshed from the Export tab.")

        a, b = st.columns(2)
        with a:
            sw = res.sweep
            fig = go.Figure(go.Scatter(x=sw["threshold"], y=sw["ruptures"], mode="lines+markers",
                                       line=dict(color=BLUE, width=2), marker=dict(size=7, line=dict(color=SURFACE, width=2)),
                                       hovertemplate="threshold %{x:.3g}: %{y} ruptures<extra></extra>"))
            fig.add_vline(x=meta["rupture_threshold"], line=dict(color=INK_2, width=1))
            fig.add_annotation(x=meta["rupture_threshold"], y=1, yref="paper", text="in use", showarrow=False,
                               xanchor="left", yanchor="top", xshift=5, font=dict(size=11, color=INK_2))
            st.plotly_chart(base_layout(fig, title="Ruptures called at each threshold", x="threshold", y="ruptures"),
                            width="stretch")
        with b:
            done = events[events["repaired"]] if len(events) else events
            st.plotly_chart(hist(done["duration_min"] if len(done) else [], BLUE, "Rupture duration", "minutes",
                                 hover="%{y} ruptures of %{x} min"), width="stretch")
        a, b = st.columns(2)
        with a:
            counts = cells["n_ruptures"].clip(upper=8).value_counts().sort_index()
            fig = go.Figure(go.Bar(x=[str(i) if i < 8 else "8+" for i in counts.index], y=counts.values,
                                   marker=dict(color=BLUE, cornerradius=4), width=0.6,
                                   hovertemplate="%{y} cells with %{x} ruptures<extra></extra>"))
            st.plotly_chart(base_layout(fig, title="Ruptures per cell", x="ruptures", y="cells"), width="stretch")
        with b:
            st.plotly_chart(hist(events["peak_signal"] if len(events) else [], BLUE, "Rupture size",
                                 "peak signal above baseline"), width="stretch")

        st.markdown("##### Look at individual ruptures")
        if len(events):
            ev = events.sort_values(["cell", "event"]).reset_index(drop=True)
            order = st.segmented_control("Show", ["Largest", "Smallest", "Longest", "In order"], default="Largest")
            key = {"Largest": ("peak_signal", False), "Smallest": ("peak_signal", True),
                   "Longest": ("duration_min", False), "In order": ("start_frame", True)}[order or "Largest"]
            ev = ev.sort_values(key[0], ascending=key[1]).head(12)
            sig = get_signal(meta["path"], os.path.getmtime(meta["path"]), os.path.join(outdir, "settings_used.yaml"))
            half = int(max(meta["nuclear_radius_px"] * 3.2, 24))
            for e in ev.itertuples():
                g = frames[frames["cell"] == e.cell].sort_values("frame")
                fl = np.arange(e.start_frame - 3, e.end_frame + 5)
                if len(fl) > 10:
                    fl = np.unique(np.round(np.linspace(fl[0], fl[-1], 10)).astype(int))
                l, r = st.columns([2.4, 1])
                l.caption(f"**Cell {e.cell}** · starts {e.start_min / 60:.1f} h · lasts {e.duration_min:.0f} min · "
                          f"size {e.peak_signal:.2f}" + ("" if e.repaired else " · not repaired"))
                l.image(cell_strip(sig, res.labels, g, fl, half=half, tile=110, interval=meta["interval_min"]),
                        width="stretch")
                w = g[g["frame"].between(e.start_frame - 12, e.end_frame + 12)]
                fig = go.Figure(go.Scatter(x=w["time_min"] / 60, y=w[col], mode="lines", line=dict(color=INK, width=1.6),
                                           hovertemplate="%{y:.2f} at %{x:.1f} h<extra></extra>"))
                fig.add_vrect(x0=e.start_min / 60 - meta["interval_min"] / 120,
                              x1=(e.start_min + e.duration_min) / 60 - meta["interval_min"] / 120,
                              fillcolor=BLUE, opacity=0.14, line_width=0)
                r.plotly_chart(base_layout(fig, height=150, x=None, y=None), width="stretch",
                               key=f"ev_{e.cell}_{e.event}")
        else:
            st.info("No ruptures at this threshold.")

if an.movement:
    if view == "Movement":
        long = cells[cells["n_frames"] >= 10].sort_values("path_length_um", ascending=False)
        tiles([("Median path length", f"{long['path_length_um'].median():.0f} {u}", "total distance travelled"),
               ("Median net displacement", f"{long['net_displacement_um'].median():.0f} {u}", "start to end"),
               ("Mean speed", f"{long['mean_speed_um_per_min'].mean():.2f}", f"{u} per minute"),
               ("Median persistence", f"{long['persistence'].median():.2f}", "1 = straight line")])
        if not meta["drift_corrected"]:
            st.caption(f"Positions are not corrected for stage drift (estimated {meta['drift_um']:.0f} {u} over the movie).")
        a, b = st.columns(2)
        fig1, fig2 = go.Figure(), go.Figure()
        for c in long["cell"].head(120):
            g = frames[frames["cell"] == c]
            fig1.add_trace(go.Scattergl(x=g["x_um"] - g["x_um"].iloc[0], y=g["y_um"].iloc[0] - g["y_um"], mode="lines",
                                        line=dict(color=BLUE, width=1), opacity=0.45, hoverinfo="skip"))
            fig2.add_trace(go.Scattergl(x=g["x_um"], y=g["y_um"], mode="lines", line=dict(color=BLUE, width=1),
                                        opacity=0.5, name=f"cell {c}", hovertemplate=f"cell {c}<extra></extra>"))
        fig1 = base_layout(fig1, height=430, title="Tracks from a common origin", x=f"x ({u})", y=f"y ({u})")
        fig1.update_yaxes(scaleanchor="x", rangemode="normal")
        fig2 = base_layout(fig2, height=430, title="Tracks in the field of view", x=f"x ({u})", y=f"y ({u})")
        fig2.update_yaxes(scaleanchor="x", autorange="reversed", rangemode="normal")
        a.plotly_chart(fig1, width="stretch")
        b.plotly_chart(fig2, width="stretch")
        a, b = st.columns(2)
        a.plotly_chart(hist(long["mean_speed_um_per_min"], BLUE, "Speed", f"mean speed ({u}/min)"), width="stretch")
        b.plotly_chart(hist(long["persistence"], BLUE, "Persistence", "net displacement ÷ path length"),
                       width="stretch")

if an.division or an.death:
    if view == "Division & death":
        counts = cells["fate"].value_counts().reindex(list(FATE_LABELS)).fillna(0)
        fig = go.Figure(go.Bar(y=[FATE_LABELS[k] for k in counts.index][::-1], x=counts.values[::-1], orientation="h",
                               marker=dict(color=BLUE, cornerradius=4), width=0.55, text=counts.values[::-1].astype(int),
                               textposition="outside", hovertemplate="%{x} cells<extra></extra>"))
        fig = base_layout(fig, height=280, title="How each track ended", x="cells")
        fig.update_yaxes(showgrid=False)
        fig.update_xaxes(showgrid=True, gridcolor=GRID)
        st.plotly_chart(fig, width="stretch")
        st.caption("Divisions and deaths are inferred from the nuclear reporter alone. Check the galleries in the PDF "
                   "report before relying on individual calls.")
        a, b = st.columns(2)
        if an.division:
            a.markdown("##### Divisions")
            a.dataframe(res.divisions, width="stretch", hide_index=True, height=320)
        if an.death:
            dead = cells[cells["fate"] == "death"]
            keep = [c for c in ("cell", "death_time_min", "death_confidence", "fate_evidence", "n_ruptures") if c in dead]
            b.markdown("##### Deaths")
            b.dataframe(dead[keep], width="stretch", hide_index=True, height=320)

if view == "Cells":
    l, r = st.columns([1, 2.2])
    with l:
        sort_by = st.selectbox("Sort cells by", [c for c in ("n_ruptures", "observed_min", "path_length_um",
                                                             "mean_speed_um_per_min", "cell") if c in cells])
        ranked = cells.sort_values(sort_by, ascending=sort_by == "cell")
        show_cols = [c for c in ("cell", "fate", "n_ruptures", "observed_min") if c in ranked]
        pick = st.dataframe(ranked[show_cols], width="stretch", hide_index=True, height=520,
                            on_select="rerun", selection_mode="single-row")
        rows = pick.selection.rows if pick and pick.selection else []
        cell_id = int(ranked.iloc[rows[0]]["cell"]) if rows else int(ranked.iloc[0]["cell"])
    with r:
        row = cells[cells["cell"] == cell_id].iloc[0]
        g = frames[frames["cell"] == cell_id].sort_values("frame")
        st.markdown(f"#### Cell {cell_id}")
        st.caption(f"{FATE_LABELS.get(row.fate, row.fate)} · tracked {row.observed_min / 60:.1f} h · "
                   f"started by {row.start_reason.replace('_', ' ')}")
        sig = get_signal(meta["path"], os.path.getmtime(meta["path"]), os.path.join(outdir, "settings_used.yaml"))
        fl = np.unique(np.round(np.linspace(g["frame"].min(), g["frame"].max(), 10)).astype(int))
        st.image(cell_strip(sig, res.labels, g, fl, half=int(max(meta["nuclear_radius_px"] * 3.2, 24)), tile=120,
                            interval=meta["interval_min"]), width="stretch")
        t = g["time_min"] / 60
        if an.rupture:
            col = signal_column(res.cfg.rupture.mode)
            fig = go.Figure(go.Scatter(x=t, y=g[col], mode="lines", line=dict(color=INK, width=1.6),
                                       hovertemplate="%{y:.2f} at %{x:.1f} h<extra></extra>"))
            for e in (events[events["cell"] == cell_id].itertuples() if len(events) else []):
                fig.add_vrect(x0=e.start_min / 60, x1=(e.start_min + e.duration_min) / 60, fillcolor=BLUE, opacity=0.14,
                              line_width=0)
            st.plotly_chart(base_layout(fig, height=210, title="Reporter in the cytoplasm (blue = ruptured)",
                                        x=None, y=MODES[res.cfg.rupture.mode][2].split(" over")[0]),
                            width="stretch")
        if an.movement:
            fig = go.Figure(go.Scatter(x=t, y=g["speed_um_per_min"], mode="lines", line=dict(color=INK_2, width=1.6),
                                       hovertemplate="%{y:.2f} at %{x:.1f} h<extra></extra>"))
            st.plotly_chart(base_layout(fig, height=190, title="Speed", x="time (h)", y=f"{u}/min"),
                            width="stretch")
        with st.expander("All measurements for this cell"):
            st.dataframe(row.dropna().astype(str).rename("value"), width="stretch")

if view == "Region":
    st.markdown("##### Select a region")
    st.caption("Drag a box on the image, or type the coordinates. Export writes the cropped annotated movie, the "
               "tables and a report for just the cells in that region."
               + (" This analysis was itself made on part of the movie (x {0}–{2}, y {1}–{3} px); the coordinates here "
                  "are counted from the corner of that part.".format(*meta["crop"]) if meta.get("crop") else ""))
    W, H = meta["width"], meta["height"]
    l, r = st.columns([2.2, 1])
    with r:
        fidx = st.slider("Frame shown", 1, meta["n_frames"], 1, key="roi_frame") - 1
        cur = S.roi or (W // 4, H // 4, 3 * W // 4, 3 * H // 4)
        c1, c2 = st.columns(2)
        x0 = c1.number_input("Left (px)", 0, W - 16, int(cur[0]), step=10)
        x1 = c2.number_input("Right (px)", 16, W, int(cur[2]), step=10)
        y0 = c1.number_input("Top (px)", 0, H - 16, int(cur[1]), step=10)
        y1 = c2.number_input("Bottom (px)", 16, H, int(cur[3]), step=10)
        roi = (min(x0, x1 - 16), min(y0, y1 - 16), x1, y1)
        member = st.selectbox("Include", list(MEMBERSHIP), format_func=lambda m: MEMBERSHIP[m].capitalize())
        inside = cells_in_roi(frames, roi, member)
        sub = subset(res, inside, roi)
        px = meta["pixel_size"]
        st.metric("Cells in region", len(inside))
        st.caption(f"{(roi[2] - roi[0]) * px:.0f} × {(roi[3] - roi[1]) * px:.0f} {u}"
                   + (f" · {len(sub.events)} ruptures" if an.rupture else ""))
        want_video = st.checkbox("Cropped annotated movie", value=True)
        want_pdf = st.checkbox("PDF report for the region", value=True)
        if st.button("Export region", type="primary", width="stretch", disabled=not inside):
            name = "region_" + "_".join(str(int(v)) for v in roi)
            sig = get_signal(meta["path"], os.path.getmtime(meta["path"]),
                             os.path.join(outdir, "settings_used.yaml")) if want_pdf else None
            bar = st.progress(0.0, text="Exporting region…")
            out = export_roi(res, roi, os.path.join(outdir, name), membership=member, video=want_video, pdf=want_pdf,
                             signal=sig, progress=lambda f: bar.progress(min(f, 1.0), text="Writing movie…"),
                             log=lambda *a: None)
            bar.empty()
            S.last_region = os.path.join(outdir, name)
            st.success(f"Saved to {S.last_region}")
        if S.get("last_region") and os.path.exists(os.path.join(S.last_region, "annotated_movie.mp4")):
            st.video(os.path.join(S.last_region, "annotated_movie.mp4"), loop=True)
    with l:
        rgb = read_frame(meta["path"], fidx, os.path.getmtime(meta["path"]),
                         tuple(meta["crop"]) if meta.get("crop") else None)
        shown = draw_frame(rgb, boundaries(res.labels[fidx], thick=True), roi)
        k = max(1, int(np.ceil(W / 1000)))
        small = shown[::k, ::k]
        fig = go.Figure(go.Image(z=small, dx=k, dy=k, hoverinfo="skip"))
        gx, gy = np.meshgrid(np.linspace(0, W, 40), np.linspace(0, H, 40))
        fig.add_trace(go.Scatter(x=gx.ravel(), y=gy.ravel(), mode="markers", marker=dict(size=1, opacity=0),
                                 hoverinfo="skip", showlegend=False))
        fig.update_layout(height=640, margin=dict(l=0, r=0, t=0, b=0), dragmode="select", paper_bgcolor="rgba(0,0,0,0)",
                          newselection=dict(line=dict(color="#ffffff", width=2)))
        fig.update_xaxes(visible=False, range=[0, W])
        fig.update_yaxes(visible=False, range=[H, 0], scaleanchor="x")
        sel = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="box", key="roi_plot",
                              config=dict(displayModeBar=False))
        box = sel.selection.box if sel and sel.selection and sel.selection.box else None
        if box:
            bx, by = sorted(box[0]["x"]), sorted(box[0]["y"])
            new = (int(max(bx[0], 0)), int(max(by[0], 0)), int(min(bx[1], W)), int(min(by[1], H)))
            if new != S.roi and new[2] - new[0] >= 16 and new[3] - new[1] >= 16:
                S.roi = new
                st.rerun()

if view == "Export":
    st.markdown("##### Files")
    st.caption(f"Everything is already saved in `{outdir}`.")
    files = [("report.pdf", "PDF report", "application/pdf"), ("annotated_movie.mp4", "Annotated movie", "video/mp4"),
             ("cells_summary.csv", "One row per cell", "text/csv"),
             ("cells_per_frame.csv", "One row per cell per frame", "text/csv"),
             ("rupture_events.csv", "One row per rupture", "text/csv"), ("divisions.csv", "Divisions", "text/csv"),
             ("deaths.csv", "Deaths", "text/csv"), ("population_summary.csv", "Population summary", "text/csv"),
             ("population_timecourse.csv", "Population over time", "text/csv"),
             ("rupture_threshold_sweep.csv", "Ruptures at each threshold", "text/csv"),
             ("settings_used.yaml", "Settings used", "text/yaml")]
    present = [(f, n, m) for f, n, m in files if os.path.exists(os.path.join(outdir, f))]
    cols = st.columns(3)
    for i, (f, name, mime) in enumerate(present):
        with cols[i % 3]:
            size = os.path.getsize(os.path.join(outdir, f))
            with open(os.path.join(outdir, f), "rb") as fh:
                st.download_button(f"{name}", fh.read(), file_name=f, mime=mime, width="stretch",
                                   help=f"{f} · {size / 1e6:.1f} MB" if size > 1e5 else f"{f} · {size / 1e3:.0f} kB")
    st.write("")
    a, b, c = st.columns(3)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f, _, _ in present:
            if f.endswith((".csv", ".yaml")):
                z.write(os.path.join(outdir, f), f)
    a.download_button("All tables (zip)", buf.getvalue(), file_name=f"{os.path.splitext(meta['movie'])[0]}_tables.zip",
                      mime="application/zip", width="stretch", type="primary")
    if b.button("Rebuild annotated movie", width="stretch",
                help="Use this after changing the rupture threshold."):
        from cellsurveillance.viz import render_overlay
        bar = st.progress(0.0, text="Writing movie…")
        render_overlay(res, os.path.join(outdir, "annotated_movie.mp4"),
                       progress=lambda f: bar.progress(min(f, 1.0), text="Writing movie…"))
        bar.empty()
        st.rerun()
    if c.button("Rebuild PDF report", width="stretch"):
        with st.spinner("Writing report…"):
            sig = get_signal(meta["path"], os.path.getmtime(meta["path"]), os.path.join(outdir, "settings_used.yaml"))
            write_pdf(res, os.path.join(outdir, "report.pdf"), signal=sig)
        st.rerun()
    st.write("")
    with st.expander("Planned additions"):
        for name, what in FUTURE:
            st.markdown(f'<div class="cs-soon"><b>{name}</b> — {what}</div>', unsafe_allow_html=True)
