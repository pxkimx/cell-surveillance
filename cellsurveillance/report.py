"""PDF report."""
from __future__ import annotations

import datetime as dt
import os
from typing import Optional

import logging

import matplotlib
matplotlib.use("Agg")
logging.getLogger("fontTools").setLevel(logging.ERROR)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec

from . import __version__
from .rupture import MODES, signal_column
from .style import (AQUA, AXIS, BLUE, EVENT_COLORS, GRID, INK, INK_2, MUTED, NEUTRAL, ORANGE, SEQUENTIAL, SURFACE,
                    apply_matplotlib_style)
from .viz import cell_strip

PAGE = (8.27, 11.69)     # A4 portrait, inches
FUTURE = [
    ("Cell morphology", "whole-cell size, spreading and membrane changes (needs a cytoplasm or membrane marker)"),
    ("Dynamics", "organelle movement, vesicle trafficking, cytoskeleton remodelling"),
    ("Molecular activity", "calcium, pH, voltage, enzyme activity, gene-expression reporters"),
    ("Cell interactions", "contact, fusion, communication, immune-cell killing"),
    ("Growth and survival", "proliferation rate and cell-cycle timing from cell-cycle reporters"),
    ("Spatial measurements", "protein location, multi-channel intensity, colocalization"),
]
FATE_LABELS = {"end_of_movie": "Tracked to end", "divided": "Divided", "death": "Died", "left_field": "Left the field",
               "occluded": "Hidden by neighbour", "lost": "Track lost"}


def _unit(meta) -> str:
    return "µm" if meta["units"] == "um" else "px"


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    if isinstance(v, (bool, np.bool_)):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        if float(v).is_integer() and abs(v) < 1e6:
            return f"{int(v):,}"
        return f"{v:,.3g}" if abs(v) < 100 else f"{v:,.0f}"
    return str(v)


def _page(pdf, title: str, subtitle: str = "", footer: str = ""):
    fig = plt.figure(figsize=PAGE)
    fig.text(0.07, 0.955, title, fontsize=15, fontweight="bold", color=INK, va="top")
    if subtitle:
        fig.text(0.07, 0.928, subtitle, fontsize=9, color=INK_2, va="top")
    fig.add_artist(plt.Line2D([0.07, 0.93], [0.912, 0.912], color=AXIS, lw=0.8))
    fig.text(0.07, 0.025, footer, fontsize=7, color=MUTED)
    fig.text(0.93, 0.025, f"Cell Surveillance {__version__}", fontsize=7, color=MUTED, ha="right")
    return fig


def _tile(fig, rect, label, value, note=""):
    ax = fig.add_axes(rect)
    ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fc="#f4f3ef", ec="none"))
    ax.text(0.08, 0.80, label, fontsize=7.5, color=INK_2, va="top", transform=ax.transAxes)
    ax.text(0.08, 0.52, value, fontsize=17, fontweight="bold", color=INK, va="center", transform=ax.transAxes)
    if note:
        ax.text(0.08, 0.14, note, fontsize=7, color=MUTED, va="bottom", transform=ax.transAxes)


def _hist(ax, values, color, xlabel, title, bins=20, unit_fmt="{:.3g}"):
    values = pd.Series(values).dropna()
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    if values.empty:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", color=MUTED, transform=ax.transAxes)
        return
    ax.hist(values, bins=bins, color=color, edgecolor=SURFACE, linewidth=1.2)
    med = values.median()
    ax.axvline(med, color=INK_2, lw=0.9)
    ax.annotate("median " + unit_fmt.format(med), (med, 1), xycoords=("data", "axes fraction"),
                xytext=(4, -3), textcoords="offset points", fontsize=7.5, color=INK_2, va="top")
    ax.grid(axis="x", visible=False)


def _summary_page(pdf, res, footer):
    meta, cells, events, an = res.meta, res.cells, res.events, res.cfg.analysis
    hours = meta["n_frames"] * meta["interval_min"] / 60
    fig = _page(pdf, "Cell Surveillance report", meta["movie"], footer)
    tiles = [("Cells tracked", _fmt(len(cells)), f"{res.timecourse['n_cells'].iloc[0]} at start, "
                                                 f"{res.timecourse['n_cells'].iloc[-1]} at end")]
    if an.rupture:
        tiles.append(("Nuclear ruptures", _fmt(len(events)),
                      f"{_fmt(int(cells['ruptured'].sum()))} cells ({cells['ruptured'].mean():.0%})"))
        done = events[events["repaired"]] if len(events) else events
        tiles.append(("Median rupture duration", (_fmt(float(done["duration_min"].median())) + " min") if len(done) else "–",
                      "repaired ruptures only"))
    if an.division:
        n_div = int((res.divisions["confidence"] == "high").sum()) if len(res.divisions) else 0
        tiles.append(("Divisions", _fmt(n_div), "with mitotic signature"))
    if an.death:
        tiles.append(("Deaths", _fmt(int((cells["fate"] == "death").sum())), "signal lost or nucleus collapsed"))
    if an.movement:
        tiles.append(("Mean speed", f"{cells['mean_speed_um_per_min'].mean():.2f}", f"{_unit(meta)}/min"))
    n_col = 3
    for i, (label, value, note) in enumerate(tiles[:6]):
        r, c = divmod(i, n_col)
        _tile(fig, [0.07 + c * 0.292, 0.79 - r * 0.115, 0.275, 0.10], label, value, note)

    ax = fig.add_axes([0.07, 0.07, 0.86, 0.47])
    ax.set_axis_off()
    rows = [(str(m).replace("(um", "(µm").replace("um2", "µm²").replace("um/", "µm/"), _fmt(v))
            for m, v in res.summary.itertuples(index=False)]
    half = (len(rows) + 1) // 2
    for col, chunk in enumerate((rows[:half], rows[half:])):
        x = 0.0 + col * 0.52
        for i, (m, v) in enumerate(chunk):
            y = 1 - (i + 0.5) / max(half, 1)
            if i % 2 == 0:
                ax.add_patch(plt.Rectangle((x, y - 0.5 / half), 0.48, 1 / half, fc="#f4f3ef", ec="none",
                                           transform=ax.transAxes))
            ax.text(x + 0.01, y, m, fontsize=7.6, color=INK_2, va="center", transform=ax.transAxes)
            ax.text(x + 0.47, y, v, fontsize=7.6, color=INK, va="center", ha="right", transform=ax.transAxes)
    missing = [name for name, key in (("time between frames", "interval_confirmed"), ("scale", "size_confirmed"))
               if not meta.get(key)]
    if missing:
        fig.text(0.07, 0.578, "Calibration not confirmed: " + " and ".join(missing) + ". "
                 + ("Times, durations and speeds" if "time between frames" in missing else "Distances and areas")
                 + " may be wrong until the values are entered in the app.",
                 fontsize=7.6, color="#d03b3b", fontweight="bold")
    fig.text(0.07, 0.555, "All measurements", fontsize=10, fontweight="bold")
    fig.text(0.07, 0.60, f"{meta['n_frames']} frames · {hours:.1f} h at {meta['interval_min']:g} min per frame · "
                         f"{meta['width']}×{meta['height']} px · {meta['pixel_size']:.4g} {_unit(meta)}/px · "
                         f"analysed {dt.datetime.now():%Y-%m-%d %H:%M}", fontsize=8, color=INK_2)
    pdf.savefig(fig)
    plt.close(fig)


def _population_page(pdf, res, footer):
    tc, an = res.timecourse, res.cfg.analysis
    fig = _page(pdf, "Population over time", "Every panel shares the same time axis.", footer)
    panels = [("n_cells", "Cells in the field", "cells", NEUTRAL)]
    if an.rupture:
        panels.append(("fraction_ruptured", "Fraction of cells ruptured at each time point", "fraction", BLUE))
    if an.movement and "mean_speed_um_per_min" in tc:
        panels.append(("mean_speed_um_per_min", "Mean speed", f"{_unit(res.meta)}/min", NEUTRAL))
    gs = GridSpec(len(panels) + 1, 1, left=0.10, right=0.93, top=0.88, bottom=0.07, hspace=0.55)
    for i, (col, title, ylabel, color) in enumerate(panels):
        ax = fig.add_subplot(gs[i])
        ax.plot(tc["time_h"], tc[col], color=color if color != NEUTRAL else INK_2, lw=1.6)
        ax.fill_between(tc["time_h"], 0, tc[col], color=color, alpha=0.12, lw=0)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        ax.set_xlim(0, tc["time_h"].max())
    ax = fig.add_subplot(gs[len(panels)])
    series = [("cumulative_ruptures", "Ruptures", "rupture", an.rupture),
              ("cumulative_divisions", "Divisions", "division", an.division),
              ("cumulative_deaths", "Deaths", "death", an.death)]
    for col, name, key, on in series:
        if on and col in tc:
            ax.plot(tc["time_h"], tc[col], color=EVENT_COLORS[key], label=name)
            ax.annotate(f"{name} {int(tc[col].iloc[-1])}", (tc["time_h"].iloc[-1], tc[col].iloc[-1]),
                        xytext=(-4, 5), textcoords="offset points", ha="right", fontsize=7.5, color=INK_2)
    ax.set_yscale("symlog", linthresh=10)
    ax.set_title("Cumulative events (log scale above 10)")
    ax.set_ylabel("events")
    ax.set_xlabel("time (h)")
    ax.set_xlim(0, tc["time_h"].max())
    ax.legend(loc="upper left", ncol=3)
    pdf.savefig(fig)
    plt.close(fig)


def _rupture_page(pdf, res, footer):
    ev, cells, meta, cfg = res.events, res.cells, res.meta, res.cfg
    desc = MODES[cfg.rupture.mode][2]
    fig = _page(pdf, "Nuclear rupture", f"A rupture is called when the {desc} exceeds {meta['rupture_threshold']:.3g}.",
                footer)
    gs = GridSpec(3, 2, left=0.10, right=0.93, top=0.88, bottom=0.07, hspace=0.5, wspace=0.3)
    done = ev[ev["repaired"]] if len(ev) else ev
    _hist(fig.add_subplot(gs[0, 0]), done["duration_min"] if len(done) else [], BLUE, "duration (min)",
          "Rupture duration (repaired)", unit_fmt="{:.0f} min")
    _hist(fig.add_subplot(gs[0, 1]), ev["peak_signal"] if len(ev) else [], BLUE, "peak signal above baseline",
          "Rupture magnitude")
    ax = fig.add_subplot(gs[1, 0])
    counts = cells["n_ruptures"].clip(upper=8).value_counts().sort_index()
    ax.bar(counts.index, counts.values, width=0.62, color=BLUE)
    ax.set_xticks(range(0, 9))
    ax.set_xticklabels([str(i) for i in range(8)] + ["8+"])
    ax.set_title("Ruptures per cell")
    ax.set_xlabel("ruptures")
    ax.set_ylabel("cells")
    ax.grid(axis="x", visible=False)
    ax = fig.add_subplot(gs[1, 1])
    sw = res.sweep
    if len(sw):
        ax.plot(sw["threshold"], sw["ruptures"], color=BLUE)
        ax.axvline(meta["rupture_threshold"], color=INK_2, lw=0.9)
        ax.annotate(f"threshold used {meta['rupture_threshold']:.3g}", (meta["rupture_threshold"], 1),
                    xycoords=("data", "axes fraction"), xytext=(4, -3), textcoords="offset points", fontsize=7.5,
                    color=INK_2, va="top")
    ax.set_title("Ruptures called at each threshold")
    ax.set_xlabel("threshold")
    ax.set_ylabel("ruptures")
    ax.set_ylim(bottom=0)

    ax = fig.add_subplot(gs[2, :])
    f = res.frames
    order = cells.sort_values(["n_ruptures", "observed_min"], ascending=[False, False])["cell"].head(60).to_numpy()
    rank = {c: i for i, c in enumerate(order)}
    sub = f[f["cell"].isin(rank)]
    y = sub["cell"].map(rank).to_numpy()
    t = sub["time_min"].to_numpy() / 60
    step = meta["interval_min"] / 60
    ax.barh(y[~sub["ruptured"].to_numpy()], step, left=t[~sub["ruptured"].to_numpy()], height=0.7, color="#e9e8e3", lw=0)
    ax.barh(y[sub["ruptured"].to_numpy()], step, left=t[sub["ruptured"].to_numpy()], height=0.7, color=BLUE, lw=0)
    ax.set_ylim(len(order) - 0.5, -0.5)
    ax.set_yticks([])
    ax.set_xlim(0, meta["n_frames"] * step)
    ax.set_xlabel("time (h)")
    ax.set_ylabel(f"{len(order)} most affected cells")
    ax.set_title("When each cell was ruptured (blue) while tracked (grey)")
    ax.grid(visible=False)
    pdf.savefig(fig)
    plt.close(fig)


def _movement_page(pdf, res, footer):
    cells, f, u = res.cells, res.frames, _unit(res.meta)
    note = "Positions are corrected for stage drift." if res.meta["drift_corrected"] else \
        f"Not corrected for stage drift (estimated {res.meta['drift_um']:.0f} {u} over the movie)."
    fig = _page(pdf, "Cell movement", note, footer)
    gs = GridSpec(3, 2, left=0.10, right=0.93, top=0.88, bottom=0.07, hspace=0.5, wspace=0.3,
                  height_ratios=[1.5, 1, 1])
    long = cells[cells["n_frames"] >= 10].sort_values("path_length_um", ascending=False)
    ax = fig.add_subplot(gs[0, 0])
    for c in long["cell"].head(150):
        g = f[f["cell"] == c]
        ax.plot(g["x_um"] - g["x_um"].iloc[0], g["y_um"].iloc[0] - g["y_um"], color=BLUE, lw=0.6, alpha=0.45)
    lim = max(np.abs(ax.get_xlim()).max(), np.abs(ax.get_ylim()).max())
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_title("Tracks from a common origin")
    ax.set_xlabel(f"x ({u})"); ax.set_ylabel(f"y ({u})")
    ax = fig.add_subplot(gs[0, 1])
    for c in long["cell"].head(300):
        g = f[f["cell"] == c]
        ax.plot(g["x_um"], g["y_um"], color=BLUE, lw=0.6, alpha=0.5)
    ax.set_xlim(0, res.meta["width"] * res.meta["pixel_size"])
    ax.set_ylim(res.meta["height"] * res.meta["pixel_size"], 0)
    ax.set_aspect("equal")
    ax.set_title("Tracks in the field of view")
    ax.set_xlabel(f"x ({u})"); ax.set_ylabel(f"y ({u})")
    _hist(fig.add_subplot(gs[1, 0]), long["mean_speed_um_per_min"], BLUE, f"mean speed ({u}/min)", "Speed",
          unit_fmt="{:.2f}")
    _hist(fig.add_subplot(gs[1, 1]), long["persistence"], BLUE, "net displacement / path length", "Persistence",
          unit_fmt="{:.2f}")
    _hist(fig.add_subplot(gs[2, 0]), long["net_displacement_um"], BLUE, f"net displacement ({u})", "Net displacement",
          unit_fmt="{:.0f}")
    _hist(fig.add_subplot(gs[2, 1]), long["msd_alpha"], BLUE, "MSD exponent α (1 = random, 2 = directed)",
          "Mode of migration", unit_fmt="{:.2f}")
    pdf.savefig(fig)
    plt.close(fig)


def _morphology_page(pdf, res, footer):
    cells, tc, u = res.cells, res.timecourse, _unit(res.meta)
    fig = _page(pdf, "Nuclear morphology", "One value per cell, averaged over the frames in which it was tracked.", footer)
    gs = GridSpec(3, 2, left=0.10, right=0.93, top=0.88, bottom=0.07, hspace=0.5, wspace=0.3)
    _hist(fig.add_subplot(gs[0, 0]), cells["mean_area_um2"], BLUE, f"area ({u}²)", "Nuclear area", unit_fmt="{:.0f}")
    _hist(fig.add_subplot(gs[0, 1]), cells["mean_circularity"], BLUE, "circularity (1 = circle)", "Circularity",
          unit_fmt="{:.2f}")
    _hist(fig.add_subplot(gs[1, 0]), cells["mean_solidity"], BLUE, "solidity (low = lobulated)", "Solidity",
          unit_fmt="{:.2f}")
    _hist(fig.add_subplot(gs[1, 1]), cells["mean_aspect_ratio"], BLUE, "major / minor axis", "Elongation",
          unit_fmt="{:.2f}")
    ax = fig.add_subplot(gs[2, 0])
    if "mean_solidity" in tc:
        ax.plot(tc["time_h"], tc["mean_solidity"], color=BLUE)
    ax.set_title("Mean solidity over time"); ax.set_xlabel("time (h)"); ax.set_ylabel("solidity")
    ax = fig.add_subplot(gs[2, 1])
    if "ruptured" in cells and cells["ruptured"].nunique() == 2:
        groups = [cells.loc[~cells["ruptured"], "mean_solidity"].dropna(), cells.loc[cells["ruptured"], "mean_solidity"].dropna()]
        bp = ax.boxplot(groups, widths=0.45, patch_artist=True, showfliers=False,
                        medianprops=dict(color=INK, lw=1.2), whiskerprops=dict(color=AXIS), capprops=dict(color=AXIS))
        for patch, color in zip(bp["boxes"], (NEUTRAL, BLUE)):
            patch.set(facecolor=color, edgecolor="none", alpha=0.85)
        ax.set_xticklabels([f"never ruptured\n(n={len(groups[0])})", f"ruptured\n(n={len(groups[1])})"])
        ax.set_ylabel("solidity")
        ax.grid(axis="x", visible=False)
    ax.set_title("Nuclear shape and rupture")
    pdf.savefig(fig)
    plt.close(fig)


def _fate_page(pdf, res, footer):
    cells, an = res.cells, res.cfg.analysis
    fig = _page(pdf, "Cell fate", "How each track ended. Deaths and divisions are inferred from the nuclear reporter alone.",
                footer)
    gs = GridSpec(3, 2, left=0.10, right=0.93, top=0.88, bottom=0.07, hspace=0.5, wspace=0.35)
    ax = fig.add_subplot(gs[0, :])
    counts = cells["fate"].value_counts().reindex(list(FATE_LABELS)).fillna(0)
    ypos = np.arange(len(counts))[::-1]
    ax.barh(ypos, counts.values, height=0.55, color=BLUE)
    ax.set_yticks(ypos)
    ax.set_yticklabels([FATE_LABELS[k] for k in counts.index], color=INK_2)
    for yy, v in zip(ypos, counts.values):
        ax.text(v, yy, f"  {int(v)}", va="center", fontsize=8, color=INK_2)
    ax.set_title("Track outcome")
    ax.set_xlabel("cells")
    ax.grid(axis="y", visible=False)
    ax = fig.add_subplot(gs[1, 0])
    start = cells[cells["first_frame"] == 0]
    if len(start) and an.death:
        t = np.sort(start.loc[start["fate"] == "death", "death_time_min"].dropna().to_numpy()) / 60
        at_risk = len(start)
        surv = 1 - np.arange(1, len(t) + 1) / at_risk
        ax.step(np.concatenate([[0], t, [res.timecourse["time_h"].max()]]),
                np.concatenate([[1], surv, [surv[-1] if len(surv) else 1]]), where="post", color=AQUA)
        ax.set_ylim(0, 1.02)
    ax.set_title("Survival of cells present at the start")
    ax.set_xlabel("time (h)"); ax.set_ylabel("fraction not dead")
    ax = fig.add_subplot(gs[1, 1])
    if an.death and an.rupture and "n_ruptures" in cells:
        grp = cells.assign(group=np.where(cells["n_ruptures"] == 0, "0", np.where(cells["n_ruptures"] == 1, "1", "2+")))
        rate = grp.groupby("group")["fate"].apply(lambda s: (s == "death").mean()).reindex(["0", "1", "2+"])
        n = grp["group"].value_counts().reindex(["0", "1", "2+"]).fillna(0)
        ax.bar(range(3), rate.fillna(0).values, width=0.5, color=AQUA)
        ax.set_xticks(range(3))
        ax.set_xticklabels([f"{k} ruptures\n(n={int(n[k])})" for k in ("0", "1", "2+")])
        ax.set_ylabel("fraction that died")
        ax.grid(axis="x", visible=False)
    ax.set_title("Death by number of ruptures")
    ax = fig.add_subplot(gs[2, 0])
    if an.division and len(res.divisions):
        d = res.divisions[res.divisions["confidence"] == "high"]
        _hist(ax, d["sibling_ratio"], ORANGE, "smaller / larger daughter nucleus", "Daughter symmetry", bins=12,
              unit_fmt="{:.2f}")
    else:
        ax.set_title("Daughter symmetry")
        ax.text(0.5, 0.5, "no divisions", ha="center", va="center", color=MUTED, transform=ax.transAxes)
    ax = fig.add_subplot(gs[2, 1])
    if an.death and "min_from_last_rupture_to_death" in cells:
        _hist(ax, cells["min_from_last_rupture_to_death"].dropna() / 60, AQUA, "hours", "Time from last rupture to death",
              bins=15, unit_fmt="{:.1f} h")
    else:
        ax.set_title("Time from last rupture to death")
    pdf.savefig(fig)
    plt.close(fig)


def _trace(ax, g, res, highlight=None):
    col = signal_column(res.cfg.rupture.mode)
    t = g["time_min"] / 60
    step = res.meta["interval_min"] / 60
    for a, e in _spans(g["ruptured"].to_numpy()):
        ax.axvspan(t.iloc[a] - step / 2, t.iloc[e] + step / 2, color=BLUE, alpha=0.14, lw=0)
    for a, e in _spans(g["mitotic"].to_numpy()):
        ax.axvspan(t.iloc[a] - step / 2, t.iloc[e] + step / 2, color=ORANGE, alpha=0.14, lw=0)
    ax.plot(t, g[col], color=INK, lw=1.1)
    rise = MODES[res.cfg.rupture.mode][1]
    thr = res.meta["rupture_threshold"]
    if rise:
        ax.plot(t, g["rupture_baseline"] + thr, color=MUTED, lw=0.8)
    else:
        ax.axhline(thr, color=MUTED, lw=0.8)
    if highlight is not None:
        ax.set_xlim(*highlight)
    ax.set_ylim(bottom=0)
    ax.tick_params(labelsize=6.5)


def _spans(flags):
    padded = np.concatenate([[False], flags, [False]])
    ch = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(ch[::2], ch[1::2] - 1))


def _gallery_pages(pdf, res, signal, labels, footer, n_events):
    ev = res.events
    if ev.empty or signal is None:
        return
    rng = np.random.default_rng(0)
    # a third largest, a third smallest (the ones closest to the threshold), a third at random
    k = max(n_events // 3, 1)
    ranked = ev.sort_values("peak_signal", ascending=False)
    big, small = ranked.head(k), ranked.tail(k)
    rest = ev.drop(big.index.union(small.index))
    pick = pd.concat([big, rest.sample(min(len(rest), k), random_state=1), small])
    pick = pick[~pick.index.duplicated()]
    per_page, interval = 8, res.meta["interval_min"]
    half = int(max(res.meta["nuclear_radius_px"] * 3.2, 24))
    by_cell = {c: g.sort_values("frame") for c, g in res.frames[res.frames["cell"].isin(pick["cell"])].groupby("cell")}
    for p0 in range(0, len(pick), per_page):
        fig = _page(pdf, "Rupture gallery", "Image strip follows the cell; pink outline = ruptured. "
                    "Trace: reporter signal (black), rupture threshold (grey), called rupture (blue band).", footer)
        chunk = pick.iloc[p0:p0 + per_page]
        for i, e in enumerate(chunk.itertuples()):
            top = 0.885 - i * 0.104
            g = by_cell[e.cell]
            a, b = e.start_frame - 3, e.end_frame + 4
            fl = np.arange(a, b + 1)
            if len(fl) > 10:
                fl = np.unique(np.round(np.linspace(a, b, 10)).astype(int))
            strip = cell_strip(signal, labels, g, fl, half=half, tile=96, interval=interval)
            ax = fig.add_axes([0.07, top - 0.088, 0.62, 0.075])
            ax.imshow(strip, aspect="equal")
            ax.set_anchor("W")
            ax.set_axis_off()
            fig.text(0.07, top - 0.006, f"Cell {e.cell} · rupture {e.event} · starts {e.start_min / 60:.1f} h · "
                     f"{e.duration_min:.0f} min · peak {e.peak_signal:.2f}"
                     + ("" if e.repaired else " · not repaired"), fontsize=7.5, color=INK_2, va="bottom")
            ax2 = fig.add_axes([0.73, top - 0.085, 0.20, 0.07])
            t0, t1 = max(a - 8, g["frame"].min()), min(b + 8, g["frame"].max())
            _trace(ax2, g[g["frame"].between(t0, t1)], res)
            ax2.grid(visible=False)
        pdf.savefig(fig)
        plt.close(fig)


def _strip_rows(pdf, title, subtitle, footer, items, per_page=9):
    """Pages of captioned image strips. `items` = list of (caption, strip image)."""
    for p0 in range(0, len(items), per_page):
        fig = _page(pdf, title, subtitle, footer)
        for i, (caption, strip) in enumerate(items[p0:p0 + per_page]):
            top = 0.885 - i * 0.093
            fig.text(0.07, top - 0.004, caption, fontsize=7.5, color=INK_2, va="bottom")
            ax = fig.add_axes([0.07, top - 0.082, 0.86, 0.072])
            ax.imshow(strip, aspect="equal"); ax.set_anchor("W"); ax.set_axis_off()
        pdf.savefig(fig)
        plt.close(fig)


def _division_pages(pdf, res, signal, labels, footer, n=18):
    d = res.divisions
    if signal is None or d.empty:
        return
    d = d[d["confidence"] == "high"].head(n)
    half = int(max(res.meta["nuclear_radius_px"] * 3.6, 24))
    items = []
    for r in d.itertuples():
        mother = res.frames[res.frames["cell"] == r.mother].sort_values("frame")
        child = res.frames[res.frames["cell"] == r.daughter_b].sort_values("frame")
        if mother.empty or child.empty:
            continue
        before = cell_strip(signal, labels, mother, np.arange(r.frame - 6, r.frame), half=half, tile=96,
                            interval=res.meta["interval_min"])
        after = cell_strip(signal, labels, child, np.arange(r.frame, r.frame + 5), half=half, tile=96,
                           interval=res.meta["interval_min"])
        gap = np.full((before.shape[0], 10, 3), 252, np.uint8)
        items.append((f"Cell {r.mother} divided at {r.time_min / 60:.1f} h into cells {r.daughter_a} and {r.daughter_b}"
                      f" · {r.mitotic_signature} · daughter ratio {r.sibling_ratio:.2f}", np.hstack([before, gap, after])))
    _strip_rows(pdf, "Division gallery", "Left: the mother before division. Right: the view follows one daughter. "
                "Yellow outline = mitosis.", footer, items)


def _death_pages(pdf, res, signal, labels, footer, n=18):
    dead = res.cells[res.cells["fate"] == "death"]
    if signal is None or dead.empty:
        return
    dead = dead.sort_values("death_confidence").head(n)
    half = int(max(res.meta["nuclear_radius_px"] * 3.6, 24))
    items = []
    for r in dead.itertuples():
        g = res.frames[res.frames["cell"] == r.cell].sort_values("frame")
        fl = np.arange(r.last_frame - 6, r.last_frame + 5)
        strip = cell_strip(signal, labels, g, fl, half=half, tile=96, interval=res.meta["interval_min"])
        items.append((f"Cell {r.cell} · last seen {r.last_time_min / 60:.1f} h · {r.death_confidence} confidence · "
                      f"{r.fate_evidence}", strip))
    _strip_rows(pdf, "Death gallery", "The last frames of each cell and the same position afterwards.", footer, items)


def _cell_pages(pdf, res, signal, labels, footer, n_cells):
    cells = res.cells
    if signal is None or cells.empty:
        return
    score = cells.get("n_ruptures", pd.Series(0, index=cells.index)) * 10 + cells["n_frames"] / cells["n_frames"].max()
    pick = cells.loc[score.sort_values(ascending=False).index].head(n_cells)
    half = int(max(res.meta["nuclear_radius_px"] * 3.2, 24))
    u = _unit(res.meta)
    per_page = 3
    for p0 in range(0, len(pick), per_page):
        fig = _page(pdf, "Individual cells", "Cells with the most ruptures. Blue band = ruptured, orange band = mitosis.", footer)
        for i, c in enumerate(pick.iloc[p0:p0 + per_page].itertuples()):
            g = res.frames[res.frames["cell"] == c.cell].sort_values("frame")
            top = 0.88 - i * 0.285
            fig.text(0.07, top, f"Cell {c.cell}", fontsize=10, fontweight="bold", va="top")
            fig.text(0.18, top - 0.002, f"{FATE_LABELS.get(c.fate, c.fate)} · tracked {c.observed_min / 60:.1f} h · "
                     f"{getattr(c, 'n_ruptures', 0)} ruptures", fontsize=8, color=INK_2, va="top")
            fl = np.unique(np.round(np.linspace(g["frame"].min(), g["frame"].max(), 12)).astype(int))
            strip = cell_strip(signal, labels, g, fl, half=half, tile=96, interval=res.meta["interval_min"])
            ax = fig.add_axes([0.07, top - 0.095, 0.86, 0.07])
            ax.imshow(strip, aspect="equal"); ax.set_anchor("W"); ax.set_axis_off()
            ax1 = fig.add_axes([0.10, top - 0.175, 0.83, 0.065])
            _trace(ax1, g, res)
            ax1.set_ylabel(MODES[res.cfg.rupture.mode][0].replace("cn_ref", "cyto/nuc").replace("cyto_ref", "cytoplasm"),
                           fontsize=7)
            ax1.set_xticklabels([])
            ax2 = fig.add_axes([0.10, top - 0.255, 0.83, 0.065], sharex=ax1)
            if "speed_um_per_min" in g:
                ax2.plot(g["time_min"] / 60, g["speed_um_per_min"], color=INK_2, lw=1.0)
            ax2.set_ylabel(f"speed ({u}/min)", fontsize=7)
            ax2.set_xlabel("time (h)", fontsize=7)
            ax2.set_ylim(bottom=0)
            ax2.tick_params(labelsize=6.5)
        pdf.savefig(fig)
        plt.close(fig)


def _methods_page(pdf, res, footer):
    meta, cfg = res.meta, res.cfg
    fig = _page(pdf, "Methods and limitations", "", footer)
    text = [
        ("Segmentation", f"Reporter channel: {meta['channel']}"
         + (" separated from transmitted light" if meta["composite"] else "") +
         ". A nucleus is a compact region brighter than its surroundings; fragments closer than "
         f"{cfg.segmentation.group_radius_um * 2:g} µm are grouped into one nucleus. Touching nuclei are separated "
         "using their outlines in the previous frame."),
        ("Tracking", "Nuclei are linked frame to frame by minimising displacement and change in area, then joined across "
         f"gaps of up to {cfg.tracking.max_gap_frames} frames. Tracks shorter than {cfg.tracking.min_track_frames} "
         "frames are discarded."),
        ("Rupture", "The reporter is measured inside the nucleus and in a ring of cytoplasm around it. "
         f"Mode '{cfg.rupture.mode}', threshold {meta['rupture_threshold']:.3g}. When the nucleus is not detectable "
         "or the whole cell is flooded with reporter, the last normal nuclear outline is used."),
        ("Division", "A division is a nucleus that loses its reporter (nuclear envelope breakdown) and is replaced by two "
         "smaller nuclei. Splits without that signature are listed as low confidence and do not split the track."),
        ("Death", "A death is a track that ends away from the image edge with the reporter signal gone from that "
         "position, or with the nucleus shrinking, fading and fragmenting. Without a viability dye this is an inference."),
        ("Limitations", "The movie is 8-bit and compressed"
         + ("; nuclei are saturated, so the nuclear intensity cannot fall measurably and ruptures are detected mainly "
            "from the rise in cytoplasmic signal" if meta["saturated"] else "") +
         ". Intensities are relative. Crowded regions where nuclei overlap for long periods are tracked less reliably. "
         "Review the annotated movie before drawing conclusions from individual cells."),
    ]
    y = 0.885
    for head, body in text:
        fig.text(0.07, y, head, fontsize=9.5, fontweight="bold", va="top")
        import textwrap
        lines = textwrap.wrap(body, 112)
        fig.text(0.07, y - 0.02, "\n".join(lines), fontsize=8, color=INK_2, va="top", linespacing=1.5)
        y -= 0.035 + 0.0165 * len(lines)
    y -= 0.01
    fig.text(0.07, y, "Planned additions", fontsize=9.5, fontweight="bold", va="top")
    for k, (name, what) in enumerate(FUTURE):
        fig.text(0.07, y - 0.024 - k * 0.019, f"{name}:", fontsize=8, color=INK, va="top")
        fig.text(0.24, y - 0.024 - k * 0.019, what, fontsize=8, color=INK_2, va="top")
    pdf.savefig(fig)
    plt.close(fig)


def write_pdf(res, path: str, signal: Optional[np.ndarray] = None, labels: Optional[np.ndarray] = None,
              title_note: str = "") -> str:
    """Write the PDF report. `signal` and `labels` enable the image galleries."""
    apply_matplotlib_style()
    an = res.cfg.analysis
    footer = res.meta["movie"] + (f" · {title_note}" if title_note else "")
    if labels is None:
        labels = res.labels
    with PdfPages(path) as pdf:
        _summary_page(pdf, res, footer)
        _population_page(pdf, res, footer)
        if an.rupture:
            _rupture_page(pdf, res, footer)
        if an.movement:
            _movement_page(pdf, res, footer)
        if an.morphology:
            _morphology_page(pdf, res, footer)
        if an.death or an.division:
            _fate_page(pdf, res, footer)
        if an.rupture and signal is not None and labels is not None:
            _gallery_pages(pdf, res, signal, labels, footer, res.cfg.output.n_event_filmstrips)
            _cell_pages(pdf, res, signal, labels, footer, res.cfg.output.n_cell_pages)
        if an.division and signal is not None and labels is not None:
            _division_pages(pdf, res, signal, labels, footer)
        if an.death and signal is not None and labels is not None:
            _death_pages(pdf, res, signal, labels, footer)
        _methods_page(pdf, res, footer)
        info = pdf.infodict()
        info["Title"] = f"Cell Surveillance report - {res.meta['movie']}"
        info["Creator"] = f"Cell Surveillance {__version__}"
    return path
