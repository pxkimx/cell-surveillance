"""Shared colours and chart styling."""
from __future__ import annotations

# chart chrome
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# categorical slots, fixed order; each event type keeps its colour in every chart
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
EVENT_COLORS = {"rupture": BLUE, "division": ORANGE, "death": AQUA}
NEUTRAL = "#b9b8b1"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# outline colours drawn on the microscopy image (RGB); chosen to stand apart from a green reporter
STATE_RGB = {"intact": (90, 200, 255), "ruptured": (255, 64, 129), "mitotic": (255, 214, 10),
             "undetected": (150, 150, 150), "death": (255, 140, 0)}


def apply_matplotlib_style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.titlepad": 8, "axes.labelsize": 8.5, "axes.labelcolor": INK_2, "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "grid.linestyle": "-", "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 8,
        "ytick.labelsize": 8, "xtick.major.size": 0, "ytick.major.size": 0, "text.color": INK,
        "lines.linewidth": 1.6, "lines.solid_capstyle": "round", "legend.frameon": False, "legend.fontsize": 8,
        "pdf.fonttype": 42,
    })
