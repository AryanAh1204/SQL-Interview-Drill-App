import os
import random
import time
from pathlib import Path

import anthropic
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # optional dependency — timer still works on interaction
    st_autorefresh = None

load_dotenv()

from bank import load_bank, pick_question
from datasets import DATASETS, ensure_datasets
from db import get_connection, introspect_schema, result_diff, safe_execute
from generator import TOPICS
from grader import get_style_feedback, grade
from storage import (
    get_daily_stats,
    get_stats,
    get_streak,
    get_weakest_topic,
    log_attempt,
    login_user,
    register_user,
)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SQL Drill",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark theme CSS + hover interactions ───────────────────────────────────────
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">

<style>
/* ── Base ── */
html, body, [class*="css"] {
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace !important;
}
.stApp {
    background: #0f0f23 !important;
    color: #c0caf5 !important;
}
.stApp > header {
    background: transparent !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0d0e1c !important;
    border-right: 1px solid #2a2d3e !important;
}
[data-testid="stSidebar"] * { color: #c0caf5 !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stSlider label {
    color: #7aa2f7 !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
}

/* ── Headings ── */
h1 { color: #7aa2f7 !important; text-shadow: 0 0 30px #7aa2f740; }
h2 { color: #bb9af7 !important; }
h3 { color: #9ece6a !important; }

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #7aa2f7, #bb9af7, #9ece6a) !important;
    background-size: 200% 200% !important;
    background-position: 0% 50% !important;
    color: #0f0f23 !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
    letter-spacing: 0.05em !important;
    padding: 0.5rem 1.4rem !important;
    transition: background-position 0.6s ease, transform 0.2s ease, box-shadow 0.2s ease !important;
    box-shadow: 0 0 0px transparent !important;
}
.stButton > button:hover {
    background-position: 100% 50% !important;
    transform: translateY(-2px) scale(1.03) !important;
    box-shadow: 0 0 26px #7aa2f790, 0 0 50px #bb9af740, 0 4px 16px #00000060 !important;
    cursor: pointer !important;
}
.stButton > button:active {
    transform: translateY(0) scale(0.98) !important;
}

/* ── Text inputs / text areas ── */
.stTextArea textarea, .stTextInput input {
    background: #1a1b2e !important;
    color: #c0caf5 !important;
    border: 1px solid #2a2d3e !important;
    border-radius: 8px !important;
    font-family: 'JetBrains Mono', monospace !important;
    caret-color: #7aa2f7 !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: #7aa2f7 !important;
    box-shadow: 0 0 0 2px #7aa2f730, 0 0 16px #7aa2f720 !important;
}
.stTextArea textarea:hover, .stTextInput input:hover {
    border-color: #565f89 !important;
}

/* ── Selectbox / dropdowns ── */
[data-testid="stSelectbox"] > div > div {
    background: #1a1b2e !important;
    border: 1px solid #2a2d3e !important;
    border-radius: 8px !important;
    color: #c0caf5 !important;
    transition: border-color 0.2s, background 0.3s, box-shadow 0.3s !important;
    cursor: pointer !important;
}
/* Make the whole selectbox area clickable + pointer cursor */
[data-testid="stSelectbox"] *,
[data-baseweb="select"],
[data-baseweb="select"] * {
    cursor: pointer !important;
}
[data-testid="stSelectbox"] > div > div:hover {
    border-color: #7aa2f7 !important;
    background: linear-gradient(135deg, #1a1b2e, #232544) !important;
    box-shadow: 0 0 18px #7aa2f750, inset 0 0 20px #7aa2f712 !important;
}

/* ── Dropdown menu options ── */
[data-baseweb="menu"] li,
[data-baseweb="popover"] li,
[role="option"] {
    cursor: pointer !important;
    transition: background 0.15s, color 0.15s, padding-left 0.15s !important;
}
[data-baseweb="menu"] li:hover,
[data-baseweb="popover"] li:hover,
[role="option"]:hover {
    background: linear-gradient(90deg, #7aa2f730, #bb9af720) !important;
    color: #c0caf5 !important;
    padding-left: 1.2rem !important;
    box-shadow: inset 3px 0 0 #7aa2f7 !important;
}

/* ── Radio buttons (difficulty) — pointer + hover ── */
[data-testid="stRadio"] label,
[data-testid="stRadio"] label * {
    cursor: pointer !important;
}
[data-testid="stRadio"] label:hover {
    color: #7aa2f7 !important;
}

/* ── Toggle + generic clickable widgets ── */
[data-testid="stToggle"] *,
.stCheckbox *,
label[data-baseweb="checkbox"] * {
    cursor: pointer !important;
}

/* ── Cards (custom HTML divs) ── */
.drill-card {
    position: relative;
    background: #1a1b2e;
    border: 1px solid #2a2d3e;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1rem;
    overflow: hidden;
    transition: border-color 0.25s, transform 0.25s, box-shadow 0.25s, background 0.4s;
    animation: slideIn 0.4s ease;
}
/* Animated gradient sweep that reveals on hover */
.drill-card::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, #7aa2f710, #bb9af712, #9ece6a10);
    background-size: 200% 200%;
    opacity: 0;
    transition: opacity 0.4s;
    pointer-events: none;
    animation: gradientShift 6s ease infinite;
}
.drill-card:hover::before { opacity: 1; }
.drill-card:hover {
    border-color: #7aa2f7;
    transform: translateY(-3px);
    box-shadow: 0 8px 32px #7aa2f730, 0 0 0 1px #7aa2f740, 0 0 60px #bb9af715;
}
@keyframes gradientShift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
@keyframes slideIn {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ── Badges ── */
.badge {
    display: inline-block;
    padding: 2px 12px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    transition: transform 0.15s, box-shadow 0.15s;
    cursor: default;
}
.badge:hover { transform: scale(1.08); box-shadow: 0 0 12px currentColor; }
.badge-easy   { background: #9ece6a22; color: #9ece6a; border: 1px solid #9ece6a60; }
.badge-medium { background: #ff9e6422; color: #ff9e64; border: 1px solid #ff9e6460; }
.badge-hard   { background: #f7768e22; color: #f7768e; border: 1px solid #f7768e60; }
.badge-topic  { background: #7aa2f722; color: #7aa2f7; border: 1px solid #7aa2f760; }
.badge-ds     { background: #bb9af722; color: #bb9af7; border: 1px solid #bb9af760; }

/* ── Timer ── */
.timer-display {
    font-size: 2.4rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: #7aa2f7;
    text-shadow: 0 0 18px #7aa2f750;
    font-variant-numeric: tabular-nums;
    transition: color 0.3s, text-shadow 0.3s;
}
.timer-pressure {
    color: #f7768e !important;
    text-shadow: 0 0 24px #f7768e70 !important;
    animation: pulse-glow 1s ease-in-out infinite alternate;
}
@keyframes pulse-glow {
    from { text-shadow: 0 0 10px #f7768e50; }
    to   { text-shadow: 0 0 30px #f7768e90; }
}

/* ── Result banners ── */
.result-pass {
    background: #9ece6a18;
    border: 1px solid #9ece6a60;
    border-radius: 10px;
    padding: 0.8rem 1.2rem;
    color: #9ece6a;
    font-weight: 700;
    animation: bannerPop 0.35s ease;
}
.result-fail {
    background: #f7768e18;
    border: 1px solid #f7768e60;
    border-radius: 10px;
    padding: 0.8rem 1.2rem;
    color: #f7768e;
    font-weight: 700;
    animation: bannerPop 0.35s ease;
}
@keyframes bannerPop {
    0%   { transform: scale(0.95); opacity: 0; }
    60%  { transform: scale(1.02); }
    100% { transform: scale(1);    opacity: 1; }
}

/* ── Progress bar ── */
.stProgress > div > div {
    background: linear-gradient(90deg, #7aa2f7, #bb9af7) !important;
    border-radius: 4px !important;
    transition: all 0.3s !important;
}
.stProgress > div {
    background: #2a2d3e !important;
    border-radius: 4px !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #1a1b2e !important;
    border: 1px solid #2a2d3e !important;
    border-radius: 10px !important;
    transition: border-color 0.2s !important;
}
[data-testid="stExpander"]:hover {
    border-color: #565f89 !important;
}
[data-testid="stExpander"] summary { color: #7aa2f7 !important; }

/* ── Tabs ── */
[data-testid="stTab"] {
    background: transparent !important;
    color: #565f89 !important;
    border-bottom: 2px solid transparent !important;
    transition: all 0.2s !important;
}
[data-testid="stTab"]:hover { color: #7aa2f7 !important; }
[aria-selected="true"][data-testid="stTab"] {
    color: #7aa2f7 !important;
    border-bottom: 2px solid #7aa2f7 !important;
}

/* ── Dataframe / table ── */
[data-testid="stDataFrame"] {
    border: 1px solid #2a2d3e !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}
[data-testid="stDataFrame"] th {
    background: #1a1b2e !important;
    color: #7aa2f7 !important;
}
[data-testid="stDataFrame"] tr:hover td {
    background: #7aa2f710 !important;
}

/* ── Divider ── */
hr { border-color: #2a2d3e !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0f0f23; }
::-webkit-scrollbar-thumb { background: #2a2d3e; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #7aa2f7; }

/* ── Cursor glow trail (large ambient light that lights up the background) ── */
#cursor-glow {
    pointer-events: none;
    position: fixed;
    width: 380px; height: 380px;
    border-radius: 50%;
    background: radial-gradient(circle, #7aa2f730 0%, #bb9af718 35%, transparent 70%);
    transform: translate(-50%, -50%);
    transition: opacity 0.3s;
    z-index: 0;
    mix-blend-mode: screen;
    filter: blur(8px);
}
</style>

""", unsafe_allow_html=True)

# Cursor glow — injected via components.html so the JS actually runs, then
# attaches the glow elements + listener to the PARENT (main app) document.

components.html(
    """
    <script>
    const doc = window.parent.document;
    if (!doc.getElementById('cursor-glow')) {
        const glow = doc.createElement('div');
        glow.id = 'cursor-glow';
        doc.body.appendChild(glow);
        doc.addEventListener('mousemove', e => {
            glow.style.left = e.clientX + 'px';
            glow.style.top  = e.clientY + 'px';
        });
    }
    </script>
    """,
    height=0,
)


# ── Session state init ─────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "available_datasets": None,
        "question": None,
        "ref_df": None,
        "start_time": None,
        "elapsed": 0.0,
        "fail_count": 0,
        "graded": False,
        "grade_result": None,
        "feedback": None,
        "schema_cache": {},
        "username": None,
        "animate": None,
        "login_attempts": 0,
        "sess_total": 0,
        "sess_passed": 0,
        "sess_time": 0.0,
        "mock_active": False,
        "mock_done": False,
        "mock_qs": [],
        "mock_refs": [],
        "mock_i": 0,
        "mock_results": [],
        "mock_overall_start": None,
        "mock_q_start": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ── Bootstrap datasets ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Downloading datasets...")
def bootstrap():
    available = ensure_datasets()
    return available


available_datasets = bootstrap()
if not available_datasets:
    st.error("No datasets could be loaded. Check your internet connection and restart.")
    st.stop()


# ── Question bank ──────────────────────────────────────────────────────────────
@st.cache_resource
def load_question_bank():
    return load_bank()


QUESTION_BANK = load_question_bank()
if not QUESTION_BANK:
    st.error("question_bank.json is empty or missing. Run `python build_bank.py` to generate it.")
    st.stop()

# ── Anthropic client (OPTIONAL — only used for post-answer style feedback) ──────
api_key = os.getenv("ANTHROPIC_API_KEY", "")
if not api_key:
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        api_key = ""
client = anthropic.Anthropic(api_key=api_key) if api_key else None


# ── Sign-in gate ───────────────────────────────────────────────────────────────
def render_login():
    st.markdown(
        """<div style="text-align:center; padding:2rem 0 1rem 0;">
            <span style="font-size:3rem;">⚡</span>
            <div style="font-size:1.8rem; font-weight:700;
                background:linear-gradient(135deg,#7aa2f7,#bb9af7);
                -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                letter-spacing:0.1em;">SQL DRILL</div>
            <div style="font-size:0.8rem; color:#565f89; letter-spacing:0.2em;">SIGN IN TO TRACK YOUR PROGRESS</div>
        </div>""",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        tab_in, tab_up = st.tabs(["Sign In", "Create Account"])
        with tab_in:
            u = st.text_input("Username", key="login_user")
            p = st.text_input("Password", type="password", key="login_pass")
            # Simple per-session rate limit: block after repeated failures.
            attempts = st.session_state.get("login_attempts", 0)
            locked = attempts >= 5
            if locked:
                st.error("Too many failed attempts. Reload the page to try again.")
            if st.button("Sign In", use_container_width=True, key="do_login", disabled=locked):
                ok, msg = login_user(u, p)
                if ok:
                    st.session_state.login_attempts = 0
                    st.session_state.username = u.strip().lower()
                    st.rerun()
                else:
                    st.session_state.login_attempts = attempts + 1
                    st.error(msg)
            st.caption("Or continue without an account:")
            if st.button("Continue as Guest", use_container_width=True, key="guest"):
                st.session_state.username = "guest"
                st.rerun()
        with tab_up:
            nu = st.text_input("Choose a username", key="reg_user")
            np = st.text_input("Choose a password", type="password", key="reg_pass")
            if st.button("Create Account", use_container_width=True, key="do_reg"):
                ok, msg = register_user(nu, np)
                if ok:
                    st.session_state.username = nu.strip().lower()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)


if not st.session_state.username:
    render_login()
    st.stop()

username = st.session_state.username


# ── Schema helper ──────────────────────────────────────────────────────────────
def get_schema(ds_id: str) -> dict:
    if ds_id not in st.session_state.schema_cache:
        conn = get_connection(available_datasets[ds_id])
        st.session_state.schema_cache[ds_id] = introspect_schema(conn)
        conn.close()
    return st.session_state.schema_cache[ds_id]


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 0.5rem 0 0.6rem 0;">
        <span style="font-size:2.2rem;">⚡</span>
        <div style="font-size:1.3rem; font-weight:700;
            background:linear-gradient(135deg,#7aa2f7,#bb9af7);
            -webkit-background-clip:text; -webkit-text-fill-color:transparent;
            letter-spacing:0.1em;">SQL DRILL</div>
        <div style="font-size:0.7rem; color:#565f89; letter-spacing:0.15em;">INTERVIEW PREP</div>
    </div>
    """, unsafe_allow_html=True)

    # User badge + sign out
    st.markdown(
        f"""<div style="display:flex; align-items:center; justify-content:space-between;
            background:#1a1b2e; border:1px solid #2a2d3e; border-radius:8px;
            padding:0.4rem 0.8rem; margin-bottom:0.6rem;">
            <span style="font-size:0.8rem; color:#9ece6a;">👤 {username}</span>
        </div>""",
        unsafe_allow_html=True,
    )
    if st.button("Sign Out", use_container_width=True, key="signout"):
        st.session_state.username = None
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    # Dataset picker
    ds_options = list(available_datasets.keys())
    ds_labels = {
        ds_id: f"{DATASETS[ds_id]['emoji']}  {ds_id.title()}"
        for ds_id in ds_options
    }
    selected_ds = st.selectbox(
        "DATASET",
        ds_options,
        format_func=lambda x: ds_labels[x],
    )

    # Tables drop down from the dataset
    schema = get_schema(selected_ds)
    ds_meta_side = DATASETS[selected_ds]
    with st.expander(f"{ds_meta_side['emoji']} {selected_ds.title()} — {len(schema)} tables", expanded=True):
        for table, cols in schema.items():
            with st.expander(f"🗂 {table}", expanded=False):
                rows = "".join(
                    f"<tr>"
                    f"<td style='padding:3px 10px 3px 0; color:#c0caf5; font-size:0.78rem; white-space:nowrap;'>{c}</td>"
                    f"<td style='padding:3px 0; color:#565f89; font-size:0.7rem; text-align:right;'>{t}</td>"
                    f"</tr>"
                    for c, t in cols
                )
                st.markdown(
                    f"<table style='width:100%; border-collapse:collapse;'>{rows}</table>",
                    unsafe_allow_html=True,
                )

    st.markdown("<hr>", unsafe_allow_html=True)

    # Topic picker
    weakest = get_weakest_topic(username)
    topic_options = ["🎯 Target my weakness"] + TOPICS
    topic_label = st.selectbox("TOPIC", topic_options)

    # Difficulty
    difficulty = st.radio(
        "DIFFICULTY",
        ["easy", "medium", "hard"],
        horizontal=True,
    )

    st.markdown("<hr>", unsafe_allow_html=True)

    # Pressure mode
    pressure_mode = st.toggle("⏱ Pressure Mode", value=False)
    if pressure_mode:
        pressure_seconds = st.slider("Countdown (seconds)", 60, 600, 300, 30)

    # Sound + animation effects toggle
    effects_on = st.toggle("🔊 Sound & animation", value=True)
    if effects_on:
        volume_pct = st.slider("Volume", 0, 100, 90, 1)
    else:
        volume_pct = 0

    st.markdown("<hr>", unsafe_allow_html=True)

    # Dataset description
    meta = DATASETS[selected_ds]
    st.markdown(
        f"""<div style="font-size:0.72rem; color:#565f89; line-height:1.6;">
        <span style="color:{meta['color']};font-weight:700;">{meta['emoji']} {selected_ds.title()}</span><br>
        {meta['description']}
        </div>""",
        unsafe_allow_html=True,
    )

    # Session summary
    if st.session_state.sess_total:
        st.markdown("<hr>", unsafe_allow_html=True)
        tot = st.session_state.sess_total
        passed = st.session_state.sess_passed
        avg = st.session_state.sess_time / tot
        rate = round(passed / tot * 100)
        st.markdown(
            f"""<div style="font-size:0.72rem; color:#565f89; line-height:1.7;">
            <span style="color:#7aa2f7; font-weight:700; letter-spacing:0.06em;">THIS SESSION</span><br>
            {tot} attempted · <span style="color:#9ece6a;">{passed} passed</span> ({rate}%)<br>
            avg {int(avg // 60):02d}:{int(avg % 60):02d} per question
            </div>""",
            unsafe_allow_html=True,
        )


# ── Hints (derived locally from topic + required columns — no API) ──────────────
_TOPIC_HINTS = {
    "single-table aggregation": "Aggregate with COUNT/SUM/AVG/MIN/MAX. No GROUP BY needed if you want one overall number; add GROUP BY to break it down per category.",
    "GROUP BY + HAVING": "GROUP BY the dimension, aggregate the measure, then filter the *groups* with HAVING (not WHERE — WHERE filters rows before grouping).",
    "CTEs": "Build it in stages with WITH name AS (...). Compute an intermediate result first, then SELECT from it — much cleaner than nesting subqueries.",
    "window functions (ROW_NUMBER / RANK / DENSE_RANK)": "Use a window: func() OVER (PARTITION BY ... ORDER BY ...). ROW_NUMBER = unique 1..n; RANK leaves gaps after ties; DENSE_RANK doesn't. To keep only top-N per group, wrap it in a CTE and filter on the rank.",
    "LAG / LEAD": "LAG(col) OVER (PARTITION BY ... ORDER BY ...) reads the previous row; LEAD reads the next. The first row of each partition is NULL — that's expected.",
    "running totals / rolling aggregates": "SUM(col) OVER (ORDER BY ... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) gives a running total. Narrow the frame (e.g. 2 PRECEDING) for a rolling window.",
    "multi-table JOIN": "JOIN on the shared key. Use INNER JOIN to keep only matches, LEFT JOIN to keep all left-side rows (unmatched right columns become NULL).",
    "correlated subqueries": "The inner query references the outer row. Often a window function or a JOIN to an aggregated subquery is cleaner and faster — worth considering.",
}


def build_hint(q: dict) -> str:
    base = _TOPIC_HINTS.get(q["topic"], "Think about which tables and columns the question is really asking about.")
    cols = ", ".join(q.get("required_columns", []))
    extra = f"\n\nYour result should include these column(s): **{cols}**." if cols else ""
    order = "\n\nOrder matters here — add an ORDER BY." if q.get("order_matters") else ""
    return base + extra + order


# ── Result animations ──────────────────────────────────────────────────────────
_SOUNDS_DIR = Path(__file__).parent / "assets" / "sounds"
_AUDIO_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
               ".m4a": "audio/mp4", ".aac": "audio/aac"}


@st.cache_data(show_spinner=False)
def _load_sound(kind: str):
    """Return (data_url) for a bundled correct/wrong sound, or None if absent.

    Looks for assets/sounds/correct.* (kind='pass') or wrong.* (kind='fail').
    """
    import base64

    stem = "correct" if kind == "pass" else "wrong"
    if not _SOUNDS_DIR.exists():
        return None
    for f in sorted(_SOUNDS_DIR.glob(f"{stem}.*")):
        mime = _AUDIO_MIME.get(f.suffix.lower())
        if mime:
            b64 = base64.b64encode(f.read_bytes()).decode()
            return f"data:{mime};base64,{b64}"
    return None


def play_animation(kind: str, volume: float = 0.9):
    """Fire a one-shot full-screen animation onto the parent document.

    kind == 'pass' -> confetti crackers burst.
    kind == 'fail' -> a big thumbs-down waves across the screen.
    volume -> 0.0–1.0 master volume for the sound effect.

    Sound: plays a bundled audio file (assets/sounds/correct|wrong.*) if present,
    otherwise falls back to a synthesized Web Audio cue.
    """
    vol = max(0.0, min(1.0, float(volume)))
    # The "correct" clip is mastered louder than the "wrong" one, so attenuate it
    # so both sit at a comparable level for the same slider setting.
    if kind == "pass":
        vol *= 0.35
    sound_url = _load_sound(kind)
    if sound_url:
        sound_js = (
            "try { const a = new (window.parent || window).Audio('" + sound_url + "');"
            f" a.volume = {vol}; a.play().catch(()=>{{}}); }} catch (e) {{}}"
        )
    else:
        sound_js = None

    pass_synth = """
        try {
            const W = window.parent || window;
            const AC = W.AudioContext || W.webkitAudioContext;
            const ac = W.__sqlDrillAudio || (W.__sqlDrillAudio = new AC());
            if (ac.resume) ac.resume();
            const notes = [523.25, 659.25, 783.99, 1046.50]; // C5 E5 G5 C6
            notes.forEach((f, i) => {
                const t = ac.currentTime + i * 0.12;
                const o = ac.createOscillator(), g = ac.createGain();
                o.type = 'triangle'; o.frequency.value = f;
                const hold = (i === notes.length - 1) ? 0.55 : 0.16;
                g.gain.setValueAtTime(0.0001, t);
                g.gain.exponentialRampToValueAtTime(Math.max(0.0002, 0.36*__VOL__), t + 0.02);
                g.gain.exponentialRampToValueAtTime(0.0001, t + hold);
                o.connect(g).connect(ac.destination);
                o.start(t); o.stop(t + hold + 0.05);
            });
        } catch (e) {}
    """
    fail_synth = """
        try {
            const W = window.parent || window;
            const AC = W.AudioContext || W.webkitAudioContext;
            const ac = W.__sqlDrillAudio || (W.__sqlDrillAudio = new AC());
            if (ac.resume) ac.resume();
            const notes = [233.08, 220.00, 207.65, 174.61]; // Bb3 A3 Ab3 F3 descending
            notes.forEach((f, i) => {
                const t = ac.currentTime + i * 0.32;
                const dur = (i === notes.length - 1) ? 0.85 : 0.3;
                const o = ac.createOscillator(), g = ac.createGain();
                const lp = ac.createBiquadFilter();
                lp.type = 'lowpass'; lp.frequency.value = 900;
                o.type = 'sawtooth';
                o.frequency.setValueAtTime(f * 1.06, t);
                o.frequency.exponentialRampToValueAtTime(f, t + 0.12);
                g.gain.setValueAtTime(0.0001, t);
                g.gain.exponentialRampToValueAtTime(Math.max(0.0002, 0.32*__VOL__), t + 0.04);
                g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
                o.connect(lp).connect(g).connect(ac.destination);
                o.start(t); o.stop(t + dur + 0.05);
            });
        } catch (e) {}
    """

    # Choose audio: bundled file if present, else the synthesized fallback.
    audio_js = sound_js if sound_js else (pass_synth if kind == "pass" else fail_synth)

    if kind == "pass":
        js = audio_js + """
        const doc = window.parent.document;
        const cv = doc.createElement('canvas');
        cv.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:99999';
        cv.width = window.parent.innerWidth; cv.height = window.parent.innerHeight;
        doc.body.appendChild(cv);
        const ctx = cv.getContext('2d');
        const colors = ['#7aa2f7','#bb9af7','#9ece6a','#ff9e64','#f7768e','#e0af68'];
        const parts = [];
        // Two cracker bursts from the lower corners
        [[0.15,1],[0.85,1]].forEach(([fx,fy]) => {
            for (let i=0;i<90;i++){
                const a = (Math.random()*Math.PI/2) + (fx<0.5?-Math.PI/2:Math.PI) ;
                const sp = 9 + Math.random()*9;
                parts.push({
                    x: fx*cv.width, y: fy*cv.height,
                    vx: Math.cos(a)*sp + (fx<0.5?6:-6),
                    vy: -Math.abs(Math.sin(a)*sp) - 6,
                    s: 5+Math.random()*6, c: colors[(Math.random()*colors.length)|0],
                    rot: Math.random()*6.28, vr:(Math.random()-0.5)*0.4, life: 1
                });
            }
        });
        let frame = 0;
        (function anim(){
            ctx.clearRect(0,0,cv.width,cv.height);
            parts.forEach(p => {
                p.vy += 0.28; p.x += p.vx; p.y += p.vy; p.rot += p.vr; p.life -= 0.008;
                ctx.save(); ctx.translate(p.x,p.y); ctx.rotate(p.rot);
                ctx.globalAlpha = Math.max(0,p.life); ctx.fillStyle = p.c;
                ctx.fillRect(-p.s/2,-p.s/2,p.s,p.s*0.6); ctx.restore();
            });
            frame++;
            if (frame < 150) requestAnimationFrame(anim); else cv.remove();
        })();
        """
    else:
        js = audio_js + """
        const doc = window.parent.document;
        const el = doc.createElement('div');
        el.textContent = '👎';
        el.style.cssText = 'position:fixed;top:42%;left:-160px;font-size:130px;z-index:99999;'
            + 'pointer-events:none;filter:drop-shadow(0 6px 18px rgba(0,0,0,.5));'
            + 'transition:none;transform-origin:center';
        doc.body.appendChild(el);
        const start = performance.now(); const dur = 2600;
        const W = window.parent.innerWidth + 320;
        (function anim(t){
            const k = Math.min(1,(t-start)/dur);
            const x = -160 + k*W;
            const wave = Math.sin(k*Math.PI*8)*22;     // up-down waving
            const tilt = Math.sin(k*Math.PI*8)*18;     // rocking tilt
            el.style.left = x + 'px';
            el.style.transform = 'translateY(' + wave + 'px) rotate(' + tilt + 'deg)';
            if (k < 1) requestAnimationFrame(anim); else el.remove();
        })(start);
        """
    js = js.replace("__VOL__", str(vol))
    components.html(f"<script>{js}</script>", height=0)


# ── Main tabs ──────────────────────────────────────────────────────────────────
tab_drill, tab_mock, tab_stats = st.tabs(["⚡  Drill", "🎤  Mock Interview", "📊  Stats"])


# ═══════════════════════════════════════════════════════════════════════════════
# DRILL TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_drill:
    col_main, col_timer = st.columns([3, 1])

    with col_main:
        st.markdown(
            f"""<h2 style="margin-bottom:0.2rem;">{meta['emoji']} {DATASETS[selected_ds]['industry']}</h2>
            <div style="font-size:0.8rem; color:#565f89; margin-bottom:1.2rem;">
            {DATASETS[selected_ds]['description'][:120]}...
            </div>""",
            unsafe_allow_html=True,
        )

    with col_timer:
        timer_slot = st.empty()

    # ── New Question button ────────────────────────────────────────────────────
    gen_col, _ = st.columns([1, 3])
    with gen_col:
        gen_clicked = st.button("⚡ New Question  ·  ⌘/Ctrl+K", use_container_width=True)

    # Keyboard shortcut: Ctrl+K / Cmd+K loads a new question. Same cross-iframe
    # approach as the submit shortcut so it fires from inside the editor too.
    components.html(
        """
        <script>
        (function () {
            const pdoc = window.parent.document;
            function clickNew() {
                const btn = Array.from(pdoc.querySelectorAll('button'))
                    .find(b => b.innerText && b.innerText.includes('New Question'));
                if (btn) { btn.click(); }
            }
            function handler(e) {
                if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
                    e.preventDefault(); e.stopPropagation(); clickNew();
                }
            }
            function attach(d) {
                if (!d || d.__sqlDrillNewKey) return;
                try { d.addEventListener('keydown', handler, true); d.__sqlDrillNewKey = true; } catch (err) {}
            }
            function scan() {
                attach(pdoc);
                pdoc.querySelectorAll('iframe').forEach(function (f) {
                    try { attach(f.contentDocument); } catch (err) {}
                });
            }
            scan();
            setInterval(scan, 800);
        })();
        </script>
        """,
        height=0,
    )

    if gen_clicked:
        # Resolve topic (None = any topic)
        actual_topic = None if topic_label == "🎯 Target my weakness" else topic_label
        if topic_label == "🎯 Target my weakness":
            w = get_weakest_topic(username)
            actual_topic = w[1] if w else None

        # Track which bank indices we've already shown this session (per dataset)
        seen = st.session_state.setdefault("seen_idx", set())

        q, idx = pick_question(
            QUESTION_BANK,
            dataset=selected_ds,
            topic=actual_topic,
            difficulty=difficulty,
            exclude=seen,
        )

        if q is None:
            st.warning(
                "No question in the bank matches that dataset/topic/difficulty. "
                "Try a different combination."
            )
        else:
            seen.add(idx)
            # Run the reference SQL locally to get the expected result set (no API)
            conn = get_connection(available_datasets[selected_ds])
            ref_df, err = safe_execute(q["reference_sql"], conn)
            conn.close()
            if err or ref_df is None:
                st.error(f"Bank question has a broken reference query: {err}")
            else:
                st.session_state.question = q
                st.session_state.ref_df = ref_df
                st.session_state.start_time = time.time()
                st.session_state.elapsed = 0.0
                st.session_state.fail_count = 0
                st.session_state.graded = False
                st.session_state.grade_result = None
                st.session_state.feedback = None

    # ── Display question ───────────────────────────────────────────────────────
    q = st.session_state.question
    if q:
        diff_class = f"badge-{q['difficulty']}"
        st.markdown(
            f"""<div class="drill-card">
            <div style="margin-bottom:0.6rem;">
                <span class="badge badge-ds">{selected_ds}</span>&nbsp;
                <span class="badge {diff_class}">{q['difficulty']}</span>&nbsp;
                <span class="badge badge-topic">{q['topic']}</span>
            </div>
            <div style="color:#565f89; font-size:0.8rem; font-style:italic; margin-bottom:0.8rem; line-height:1.6;">
                {q['business_context']}
            </div>
            <div style="font-size:1.05rem; font-weight:500; color:#c0caf5; line-height:1.7;">
                {q['question']}
            </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── Hint (no API; derived from topic + required columns) ─────────────────
        with st.expander("💡 Stuck? Show a hint", expanded=False):
            st.markdown(build_hint(q))

        # ── Timer update ───────────────────────────────────────────────────────
        if st.session_state.start_time and not st.session_state.graded:
            st.session_state.elapsed = time.time() - st.session_state.start_time
            # Tick the stopwatch / countdown live (1s) while a question is active.
            if st_autorefresh is not None:
                st_autorefresh(interval=1000, key="timer_tick")

        elapsed = st.session_state.elapsed
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60

        if pressure_mode:
            remaining = max(0, pressure_seconds - int(elapsed))
            rem_m = remaining // 60
            rem_s = remaining % 60
            is_urgent = remaining < 60
            timer_cls = "timer-pressure" if is_urgent else "timer-display"
            timer_slot.markdown(
                f"""<div class="{timer_cls}">{rem_m:02d}:{rem_s:02d}</div>
                <div style="font-size:0.7rem; color:#565f89;">remaining</div>""",
                unsafe_allow_html=True,
            )
            prog_val = remaining / pressure_seconds
            if remaining == 0:
                st.warning("⏰ Time's up! You can still submit your answer.")
        else:
            timer_slot.markdown(
                f"""<div class="timer-display">{mins:02d}:{secs:02d}</div>
                <div style="font-size:0.7rem; color:#565f89;">elapsed</div>""",
                unsafe_allow_html=True,
            )

        # ── SQL Editor ────────────────────────────────────────────────────────
        try:
            from streamlit_ace import st_ace
            user_sql = st_ace(
                placeholder="-- Write your SQL query here...\nSELECT ...",
                language="sql",
                theme="dracula",
                font_size=14,
                height=220,
                key=f"ace_{id(q)}",
                auto_update=True,
            )
        except ImportError:
            user_sql = st.text_area(
                "Your SQL Query",
                placeholder="-- Write your SQL query here...\nSELECT ...",
                height=220,
                key=f"sql_{id(q)}",
            )

        # ── Submit ────────────────────────────────────────────────────────────
        submit_col, _ = st.columns([1, 3])
        with submit_col:
            submit_clicked = st.button(
                "▶ Submit Answer  ·  ⌘/Ctrl+↵",
                use_container_width=True,
                key="submit",
            )

        # Keyboard shortcut: Ctrl+Enter (Win/Linux) or Cmd+Enter (Mac) submits.
        # The Ace editor lives in its own iframe, so we install the listener on the
        # parent document AND every same-origin iframe document (incl. the editor),
        # rescanning periodically to catch iframes that mount after this runs.
        components.html(
            """
            <script>
            (function () {
                const parent = window.parent;
                const pdoc = parent.document;
                function clickSubmit() {
                    const btn = Array.from(pdoc.querySelectorAll('button'))
                        .find(b => b.innerText && b.innerText.includes('Submit Answer'));
                    if (btn) { btn.click(); }
                }
                function handler(e) {
                    if ((e.ctrlKey || e.metaKey) && (e.key === 'Enter' || e.keyCode === 13)) {
                        e.preventDefault(); e.stopPropagation();
                        clickSubmit();
                    }
                }
                function attach(d) {
                    if (!d || d.__sqlDrillKey) return;
                    try { d.addEventListener('keydown', handler, true); d.__sqlDrillKey = true; } catch (err) {}
                }
                function scan() {
                    attach(pdoc);
                    pdoc.querySelectorAll('iframe').forEach(function (f) {
                        try { attach(f.contentDocument); } catch (err) {}
                    });
                }
                scan();
                setInterval(scan, 800);
            })();
            </script>
            """,
            height=0,
        )

        if submit_clicked and user_sql and user_sql.strip():
            elapsed_at_submit = time.time() - st.session_state.start_time if st.session_state.start_time else 0
            conn = get_connection(available_datasets[selected_ds])

            result = grade(
                user_sql=user_sql,
                ref_df=st.session_state.ref_df,
                question=q,
                conn=conn,
            )
            conn.close()

            st.session_state.grade_result = result
            st.session_state.graded = True
            st.session_state.elapsed = elapsed_at_submit
            # One-shot animation trigger (consumed once in the result block)
            st.session_state.animate = "pass" if result["passed"] else "fail"
            # Session running totals
            st.session_state.sess_total += 1
            st.session_state.sess_passed += int(result["passed"])
            st.session_state.sess_time += elapsed_at_submit

            if not result["passed"]:
                st.session_state.fail_count += 1
            elif client is not None:
                # Optional style feedback on pass — only if an API key is configured
                with st.spinner("Getting style feedback..."):
                    try:
                        fb = get_style_feedback(
                            user_sql=user_sql,
                            ref_sql=q["reference_sql"],
                            question_text=q["question"],
                            client=client,
                        )
                        st.session_state.feedback = fb
                    except Exception:
                        st.session_state.feedback = None

            log_attempt(
                username=username,
                dataset=selected_ds,
                topic=q["topic"],
                difficulty=q["difficulty"],
                time_seconds=elapsed_at_submit,
                passed=result["passed"],
                my_sql=user_sql,
            )

        # ── Grade result ──────────────────────────────────────────────────────
        gr = st.session_state.grade_result
        if gr:
            # One-shot celebration / commiseration animation (if effects enabled)
            if st.session_state.animate:
                if effects_on:
                    play_animation(st.session_state.animate, volume=volume_pct / 100)
                st.session_state.animate = None

            if gr["passed"]:
                st.markdown(
                    f"""<div class="result-pass">
                    ✅ &nbsp;<strong>CORRECT</strong> — {gr['reason']}
                    </div>""",
                    unsafe_allow_html=True,
                )
                if st.session_state.feedback:
                    with st.expander("💬 Interviewer Feedback", expanded=True):
                        st.markdown(
                            f"<div style='color:#c0caf5; line-height:1.7;'>{st.session_state.feedback}</div>",
                            unsafe_allow_html=True,
                        )
            else:
                st.markdown(
                    f"""<div class="result-fail">
                    ❌ &nbsp;<strong>INCORRECT</strong> — {gr['reason']}
                    </div>""",
                    unsafe_allow_html=True,
                )

                # Result diff — teach what's off without leaking the answer early.
                diff = result_diff(
                    st.session_state.ref_df, gr["user_df"], q["required_columns"]
                )
                cA, cB = st.columns(2)
                cA.metric("Expected rows", diff["expected_rows"])
                cB.metric("Your rows", diff["your_rows"])
                if diff["aligned"]:
                    st.caption(
                        f"🧩 {len(diff['missing'])} expected row(s) missing · "
                        f"{len(diff['extra'])} unexpected row(s) in your result."
                    )
                    # Row-level values unlock alongside the reference (after 2 fails).
                    if st.session_state.fail_count >= 2:
                        if len(diff["missing"]) > 0:
                            st.markdown("**Rows you're missing** (in the expected answer):")
                            st.dataframe(diff["missing"].head(20), use_container_width=True)
                        if len(diff["extra"]) > 0:
                            st.markdown("**Extra rows you returned** (not in the expected answer):")
                            st.dataframe(diff["extra"].head(20), use_container_width=True)
                else:
                    st.caption(f"🧩 {diff['summary']}")

            # Reveal answer (unlocked after 2 failures)
            if st.session_state.fail_count >= 2:
                with st.expander(
                    f"🔓 Reveal Reference Answer (unlocked after {st.session_state.fail_count} failures)",
                    expanded=False,
                ):
                    st.code(q["reference_sql"], language="sql")
                    import json as _json
                    _sql_lit = _json.dumps(q["reference_sql"])
                    components.html(
                        f"""
                        <button id="copybtn" style="
                            background:linear-gradient(135deg,#7aa2f7,#bb9af7); color:#0f0f23;
                            border:none; border-radius:8px; padding:6px 14px; font-weight:700;
                            font-family:monospace; cursor:pointer;">📋 Copy SQL</button>
                        <script>
                        const b = document.getElementById('copybtn');
                        b.addEventListener('click', async () => {{
                            try {{ await navigator.clipboard.writeText({_sql_lit}); b.textContent = '✅ Copied'; }}
                            catch (e) {{ b.textContent = '⚠ Copy failed'; }}
                            setTimeout(() => b.textContent = '📋 Copy SQL', 1500);
                        }});
                        </script>
                        """,
                        height=44,
                    )
            elif not gr["passed"]:
                st.caption(
                    f"💡 Reference answer unlocks after 2 failed attempts "
                    f"({2 - st.session_state.fail_count} remaining)"
                )

            # Preview user's result
            if gr["user_df"] is not None and len(gr["user_df"]) > 0:
                with st.expander("🔍 Your Result Preview (first 20 rows)", expanded=False):
                    st.dataframe(gr["user_df"].head(20), use_container_width=True)

    else:
        st.markdown(
            """<div class="drill-card" style="text-align:center; padding:2.5rem; color:#565f89;">
            <div style="font-size:2.5rem; margin-bottom:0.5rem;">⚡</div>
            <div style="font-size:1.1rem; color:#7aa2f7; font-weight:600;">Ready to drill?</div>
            <div style="margin-top:0.4rem;">Pick a topic and difficulty in the sidebar, then click New Question.</div>
            </div>""",
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# STATS TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_stats:
    st.markdown(f"<h2>📊 {username.title()}'s Progress</h2>", unsafe_allow_html=True)

    # ── Streaks ────────────────────────────────────────────────────────────────
    streak = get_streak(username)
    DAILY_GOAL = 5
    s1, s2, s3 = st.columns(3)
    s1.metric("🔥 Current streak", f"{streak['current']} day{'s' if streak['current'] != 1 else ''}")
    s2.metric("🏆 Best streak", f"{streak['best']} day{'s' if streak['best'] != 1 else ''}")
    s3.metric(
        f"🎯 Today ({streak['today']}/{DAILY_GOAL})",
        "Goal met! ✅" if streak["today"] >= DAILY_GOAL else f"{DAILY_GOAL - streak['today']} to go",
    )

    stats_df = get_stats(username)
    weakest = get_weakest_topic(username)

    if stats_df.empty:
        st.markdown(
            """<div class="drill-card" style="text-align:center; padding:2rem; color:#565f89;">
            <div style="font-size:1.8rem; margin-bottom:0.4rem;">📭</div>
            No attempts yet. Head to the Drill tab and solve some questions!
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        if weakest:
            wds, wtopic = weakest
            st.markdown(
                f"""<div class="drill-card" style="border-color:#f7768e60; background:#f7768e08;">
                <strong style="color:#f7768e;">⚠ Weakest Area:</strong>
                <span style="color:#c0caf5; margin-left:0.5rem;">{wtopic}</span>
                <span style="color:#565f89; font-size:0.8rem; margin-left:0.5rem;">on {wds}</span>
                <br><span style="font-size:0.78rem; color:#565f89; margin-top:0.3rem; display:block;">
                Set topic to "🎯 Target my weakness" to focus here.</span>
                </div>""",
                unsafe_allow_html=True,
            )

        # Summary table
        display_df = stats_df.copy()
        display_df["pass_rate"] = display_df["pass_rate"].apply(lambda x: f"{x}%")
        display_df["avg_time_seconds"] = display_df["avg_time_seconds"].apply(
            lambda x: f"{int(x//60):02d}:{int(x%60):02d}"
        )
        display_df.columns = ["Dataset", "Topic", "Attempts", "Pass Rate", "Avg Time", "Median Time (raw)"]
        display_df = display_df.drop(columns=["Median Time (raw)"])
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Bar chart
        st.markdown("<h3>Pass Rate by Topic</h3>", unsafe_allow_html=True)
        chart_df = stats_df.set_index("topic")[["pass_rate"]].rename(columns={"pass_rate": "Pass Rate %"})
        st.bar_chart(chart_df)

        # Trend over time
        daily = get_daily_stats(username)
        if len(daily) >= 2:
            st.markdown("<h3>Accuracy Over Time</h3>", unsafe_allow_html=True)
            acc = daily.set_index("day")[["pass_rate"]].rename(columns={"pass_rate": "Pass Rate %"})
            st.line_chart(acc, color="#9ece6a")

            st.markdown("<h3>Practice Volume</h3>", unsafe_allow_html=True)
            vol = daily.set_index("day")[["attempts", "passed"]].rename(
                columns={"attempts": "Attempts", "passed": "Passed"}
            )
            st.bar_chart(vol, color=["#7aa2f7", "#9ece6a"])

        # Per-dataset breakdown
        st.markdown("<h3>Attempts by Dataset</h3>", unsafe_allow_html=True)
        ds_summary = (
            stats_df.groupby("dataset")
            .agg(attempts=("attempts", "sum"), pass_rate=("pass_rate", "mean"))
            .reset_index()
        )
        for _, row in ds_summary.iterrows():
            ds_id = row["dataset"]
            ds_meta = DATASETS.get(ds_id, {})
            emoji = ds_meta.get("emoji", "📦")
            color = ds_meta.get("color", "#7aa2f7")
            st.markdown(
                f"""<div class="drill-card" style="border-color:{color}40; display:inline-block; width:100%;">
                <span style="color:{color}; font-weight:700;">{emoji} {ds_id.title()}</span>
                <span style="color:#565f89; font-size:0.8rem; margin-left:0.8rem;">{int(row['attempts'])} attempts</span>
                <span style="color:#9ece6a; font-size:0.9rem; margin-left:0.8rem; font-weight:600;">{row['pass_rate']:.1f}% pass rate</span>
                </div>""",
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK INTERVIEW TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_mock:
    st.markdown("<h2>🎤 Mock Interview</h2>", unsafe_allow_html=True)

    def _reset_mock():
        for k, v in {
            "mock_active": False, "mock_done": False, "mock_qs": [], "mock_refs": [],
            "mock_i": 0, "mock_results": [], "mock_overall_start": None, "mock_q_start": None,
        }.items():
            st.session_state[k] = v

    # ── Setup screen ────────────────────────────────────────────────────────────
    if not st.session_state.mock_active and not st.session_state.mock_done:
        st.markdown(
            """<div style="color:#565f89; font-size:0.9rem; line-height:1.7; margin-bottom:1rem;">
            A timed round of back-to-back questions — no hints, no answer reveals. Solve each,
            submit, and get a scorecard at the end. Just like the real thing.</div>""",
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            n_q = st.slider("Questions", 3, 10, 5)
        with c2:
            ds_choice = st.selectbox("Dataset", ["Mixed"] + list(available_datasets.keys()),
                                     format_func=lambda x: x.title())
        with c3:
            diff_choice = st.selectbox("Difficulty", ["Mixed", "easy", "medium", "hard"])

        if st.button("▶ Start Interview", use_container_width=False):
            pool = [
                q for q in QUESTION_BANK
                if (ds_choice == "Mixed" or q["dataset"] == ds_choice)
                and (diff_choice == "Mixed" or q["difficulty"] == diff_choice)
            ]
            if len(pool) < n_q:
                st.warning(f"Only {len(pool)} questions match — pick a broader filter.")
            else:
                chosen = random.sample(pool, n_q)
                refs = []
                ok = True
                for q in chosen:
                    conn = get_connection(available_datasets[q["dataset"]])
                    ref_df, err = safe_execute(q["reference_sql"], conn)
                    conn.close()
                    if err or ref_df is None:
                        ok = False
                        break
                    refs.append(ref_df)
                if not ok:
                    st.error("Could not prepare the question set — try again.")
                else:
                    _reset_mock()
                    st.session_state.mock_qs = chosen
                    st.session_state.mock_refs = refs
                    st.session_state.mock_active = True
                    st.session_state.mock_overall_start = time.time()
                    st.session_state.mock_q_start = time.time()
                    st.rerun()

    # ── Active interview ────────────────────────────────────────────────────────
    elif st.session_state.mock_active:
        qs = st.session_state.mock_qs
        i = st.session_state.mock_i
        q = qs[i]
        total = len(qs)

        # Overall timer (counts up, live)
        if st_autorefresh is not None:
            st_autorefresh(interval=1000, key="mock_tick")
        overall = int(time.time() - st.session_state.mock_overall_start)

        head_l, head_r = st.columns([3, 1])
        with head_l:
            st.markdown(
                f"<div style='color:#7aa2f7; font-weight:700; letter-spacing:0.06em;'>"
                f"QUESTION {i+1} / {total}</div>",
                unsafe_allow_html=True,
            )
        with head_r:
            st.markdown(
                f"<div class='timer-display' style='font-size:1.6rem;'>{overall//60:02d}:{overall%60:02d}</div>",
                unsafe_allow_html=True,
            )
        st.progress(i / total)

        diff_class = f"badge-{q['difficulty']}"
        st.markdown(
            f"""<div class="drill-card">
            <div style="margin-bottom:0.6rem;">
                <span class="badge badge-ds">{q['dataset']}</span>&nbsp;
                <span class="badge {diff_class}">{q['difficulty']}</span>&nbsp;
                <span class="badge badge-topic">{q['topic']}</span>
            </div>
            <div style="color:#565f89; font-size:0.8rem; font-style:italic; margin-bottom:0.8rem; line-height:1.6;">
                {q['business_context']}
            </div>
            <div style="font-size:1.05rem; font-weight:500; color:#c0caf5; line-height:1.7;">
                {q['question']}
            </div>
            </div>""",
            unsafe_allow_html=True,
        )

        try:
            from streamlit_ace import st_ace
            mock_sql = st_ace(
                placeholder="-- Your SQL here...\nSELECT ...",
                language="sql", theme="dracula", font_size=14, height=200,
                key=f"mock_ace_{i}", auto_update=True,
            )
        except ImportError:
            mock_sql = st.text_area("Your SQL Query", height=200, key=f"mock_sql_{i}")

        bcol1, bcol2, _ = st.columns([1, 1, 2])
        submit_mock = bcol1.button("▶ Submit & Next", use_container_width=True, key=f"mock_submit_{i}")
        skip_mock = bcol2.button("⏭ Skip", use_container_width=True, key=f"mock_skip_{i}")

        def _record(passed, sql_text):
            q_time = time.time() - st.session_state.mock_q_start
            st.session_state.mock_results.append({
                "topic": q["topic"], "difficulty": q["difficulty"],
                "dataset": q["dataset"], "passed": passed, "time": q_time,
            })
            log_attempt(
                username=username, dataset=q["dataset"], topic=q["topic"],
                difficulty=q["difficulty"], time_seconds=q_time,
                passed=passed, my_sql=sql_text,
            )
            if i + 1 >= total:
                st.session_state.mock_active = False
                st.session_state.mock_done = True
            else:
                st.session_state.mock_i = i + 1
                st.session_state.mock_q_start = time.time()
            st.rerun()

        if submit_mock and mock_sql and mock_sql.strip():
            conn = get_connection(available_datasets[q["dataset"]])
            res = grade(user_sql=mock_sql, ref_df=st.session_state.mock_refs[i], question=q, conn=conn)
            conn.close()
            _record(res["passed"], mock_sql)
        elif skip_mock:
            _record(False, "")

        st.caption("No hints or reveals during a mock interview — that's the point. 💪")

    # ── Scorecard ───────────────────────────────────────────────────────────────
    elif st.session_state.mock_done:
        results = st.session_state.mock_results
        total = len(results)
        passed = sum(r["passed"] for r in results)
        total_time = int(time.time() - st.session_state.mock_overall_start) if st.session_state.mock_overall_start else int(sum(r["time"] for r in results))
        score_pct = round(passed / total * 100) if total else 0
        verdict = ("🟢 Strong" if score_pct >= 80 else
                   "🟡 Solid, keep drilling" if score_pct >= 50 else
                   "🔴 Needs work")

        st.markdown(
            f"""<div class="drill-card" style="text-align:center; border-color:#7aa2f7;">
            <div style="font-size:0.8rem; color:#565f89; letter-spacing:0.1em;">INTERVIEW COMPLETE</div>
            <div style="font-size:3rem; font-weight:800;
                background:linear-gradient(135deg,#7aa2f7,#bb9af7);
                -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
                {passed} / {total}</div>
            <div style="color:#c0caf5; font-size:1.1rem;">{score_pct}% · {verdict}</div>
            <div style="color:#565f89; font-size:0.85rem; margin-top:0.4rem;">
                Total time {total_time//60:02d}:{total_time%60:02d}</div>
            </div>""",
            unsafe_allow_html=True,
        )

        import pandas as _pd
        card = _pd.DataFrame([
            {
                "#": idx + 1,
                "Topic": r["topic"],
                "Difficulty": r["difficulty"],
                "Dataset": r["dataset"],
                "Result": "✅ Pass" if r["passed"] else "❌ Fail",
                "Time": f"{int(r['time'])//60:02d}:{int(r['time'])%60:02d}",
            }
            for idx, r in enumerate(results)
        ])
        st.dataframe(card, use_container_width=True, hide_index=True)

        if st.button("🔄 New Interview", use_container_width=False):
            _reset_mock()
            st.rerun()
