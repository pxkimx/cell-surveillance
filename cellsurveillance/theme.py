"""Light and dark looks for the app.

The dark look is the original one, so nothing changes until the user picks Light. The
choice is kept in the preferences file (see history.py), read when the server starts, and
turned into Streamlit's own theme settings and into CSS variables, so the first paint is
already in the chosen look. The PDF report has its own, printable palette in style.py.
"""
from __future__ import annotations

from . import history

THEMES = ("dark", "light")

PALETTES = {
    "dark": dict(
        bg="#061216", panel="#0e2229", panel2="#12303a", ink="#f4fbf8", ink2="#c8d7d1", muted="#8ea7a8",
        line="rgba(131,207,210,.24)", accent="#2dd4bf", pink="#ff4081", cyan="#5ac8ff",
        # surfaces that were written as colours rather than variables
        panel_grad="linear-gradient(180deg, rgba(18,48,58,.72), rgba(10,26,32,.8))",
        tile_grad="linear-gradient(160deg, rgba(18,48,58,.85), rgba(8,22,27,.9))",
        card_grad="linear-gradient(160deg, rgba(18,48,58,.7), rgba(8,22,27,.8))",
        nav_bg="rgba(14,34,41,.72)", nav_ink_hover="#ffffff",
        nav_active="linear-gradient(135deg, rgba(45,212,191,.30), rgba(57,135,229,.22))", nav_active_ink="#ffffff",
        veil="rgba(4,15,19,.85)", hero_glow="rgba(2,9,11,.78)", hero_glow2="rgba(2,9,11,.45)", hero_shadow="0 2px 22px rgba(0,0,0,.9), 0 0 2px rgba(0,0,0,.6)",
        hero_text_shadow="0 1px 10px #000, 0 0 3px #000", hero_desc="#c3d6d3",
        drop_bg="rgba(6,18,22,.6)", metric_bg="rgba(14,34,41,.7)", media_bg="#000000", primary_ink="#03181a",
        sheen="rgba(255,255,255,.07)", scan="rgba(131,207,210,.16)", chip_warn="#fab219",
        # charts
        chart_ink="#f4fbf8", chart_ink2="#c8d7d1", chart_muted="#8ea7a8", chart_surface="#061216", chart_hover="#0e2229",
        chart_grid="rgba(173,224,226,.13)", chart_axis="rgba(173,224,226,.30)",
        blue="#3987e5", orange="#d95926", aqua="#199e70", neutral="#5d7274",
        # Streamlit's own widgets
        st_base="dark", st_primary="#2dd4bf", st_bg="#061216", st_bg2="#0e2229", st_text="#eef7f4",
    ),
    "light": dict(
        bg="#f3f4f6", panel="#ffffff", panel2="#fbfbfd", ink="#1d1d1f", ink2="#3f4a4d", muted="#5c676b",
        line="rgba(0,0,0,.12)", accent="#0a7366", pink="#d6336c", cyan="#1f7fc2",
        panel_grad="linear-gradient(180deg, rgba(255,255,255,.86), rgba(251,251,253,.92))",
        tile_grad="linear-gradient(160deg, rgba(255,255,255,.92), rgba(246,247,249,.96))",
        card_grad="linear-gradient(160deg, rgba(255,255,255,.9), rgba(246,247,249,.94))",
        nav_bg="rgba(255,255,255,.8)", nav_ink_hover="#000000",
        nav_active="linear-gradient(135deg, rgba(10,115,102,.16), rgba(31,127,194,.12))", nav_active_ink="#0b4f47",
        veil="rgba(243,244,246,.86)", hero_glow="rgba(243,244,246,.9)", hero_glow2="rgba(243,244,246,.6)", hero_shadow="none",
        hero_text_shadow="none", hero_desc="#3f4a4d",
        drop_bg="rgba(255,255,255,.7)", metric_bg="rgba(255,255,255,.8)", media_bg="#e9ebee", primary_ink="#ffffff",
        sheen="rgba(255,255,255,.5)", scan="rgba(0,0,0,.08)", chip_warn="#9a5b00",
        chart_ink="#1d1d1f", chart_ink2="#3f4a4d", chart_muted="#5c676b", chart_surface="#f3f4f6", chart_hover="#ffffff",
        chart_grid="rgba(0,0,0,.08)", chart_axis="rgba(0,0,0,.25)",
        blue="#2563c9", orange="#c2410c", aqua="#0f766e", neutral="#6b7a7e",
        st_base="light", st_primary="#0a7366", st_bg="#f3f4f6", st_bg2="#ffffff", st_text="#1d1d1f",
    ),
}


def current() -> str:
    """The user's choice; dark, the original look, until they pick."""
    choice = history.preferences().get("theme", "dark")
    return choice if choice in THEMES else "dark"


def streamlit_flags(name: str) -> list:
    """Command-line settings that put Streamlit's own widgets in this look."""
    p = PALETTES[name]
    return ["--theme.base", p["st_base"], "--theme.primaryColor", p["st_primary"], "--theme.backgroundColor", p["st_bg"],
            "--theme.secondaryBackgroundColor", p["st_bg2"], "--theme.textColor", p["st_text"]]


def css_variables(name: str) -> str:
    """The :root block for the app's own styling, in this look."""
    p = PALETTES[name]
    keys = ("bg", "panel", "panel2", "ink", "ink2", "muted", "line", "accent", "pink", "cyan", "panel-grad", "tile-grad", "card-grad",
            "nav-bg", "nav-ink-hover", "nav-active", "nav-active-ink", "veil", "hero-glow", "hero-glow2", "hero-shadow",
            "hero-text-shadow", "hero-desc", "drop-bg", "metric-bg", "media-bg", "primary-ink", "sheen", "scan", "chip-warn")
    body = " ".join(f"--{k}:{p[k.replace('-', '_')]};" for k in keys)
    return f':root {{ {body} --mono: ui-monospace, SFMono-Regular, Menlo, monospace; }}\nhtml {{ color-scheme: {name}; }}'


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)
