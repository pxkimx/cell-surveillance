"""Region of interest: restrict the results and the movie to part of the field."""
from __future__ import annotations

import os
from dataclasses import replace
from typing import Optional

import numpy as np
import pandas as pd

from .metrics import population_summary, population_timecourse
from .pipeline import Results, write_tables

MEMBERSHIP = {
    "inside_most": "cells that spend most of their time inside the region",
    "inside_any": "cells that enter the region at any time",
    "inside_start": "cells that are inside the region when first seen",
    "inside_always": "cells that never leave the region",
}


def cells_in_roi(frames: pd.DataFrame, roi: tuple, membership: str = "inside_most") -> set:
    x0, y0, x1, y1 = roi
    inside = frames["x"].between(x0, x1) & frames["y"].between(y0, y1)
    g = inside.groupby(frames["cell"])
    if membership == "inside_any":
        keep = g.any()
    elif membership == "inside_always":
        keep = g.all()
    elif membership == "inside_start":
        first = frames.sort_values("frame").groupby("cell").head(1)
        keep = (first["x"].between(x0, x1) & first["y"].between(y0, y1)).groupby(first["cell"]).any()
    elif membership == "inside_most":
        keep = g.mean() >= 0.5
    else:
        raise ValueError(f"membership must be one of {', '.join(MEMBERSHIP)}")
    return set(keep.index[keep])


def subset(res: Results, cells: set, roi: Optional[tuple] = None, with_sweep: bool = False) -> Results:
    """Results restricted to `cells`, with population tables recomputed."""
    frames = res.frames[res.frames["cell"].isin(cells)].copy()
    table = res.cells[res.cells["cell"].isin(cells)].copy()
    events = res.events[res.events["cell"].isin(cells)].copy() if len(res.events) else res.events
    divisions = res.divisions[res.divisions["mother"].isin(cells)].copy() if len(res.divisions) else res.divisions
    terminal = res.terminal[res.terminal["cell"].isin(cells)].copy() if res.terminal is not None and len(res.terminal) \
        else res.terminal
    meta = dict(res.meta)
    if roi is not None:
        meta["roi"] = [int(v) for v in roi]
        meta["movie"] = f"{res.meta['movie']} · region x {roi[0]}-{roi[2]}, y {roi[1]}-{roi[3]} px"
    tc = population_timecourse(frames, events, table, divisions, meta["n_frames"], meta["interval_min"])
    summary = population_summary(table, events, divisions, tc, res.cfg, meta) if len(table) else pd.DataFrame(
        columns=["measurement", "value"])
    if roi is not None and len(summary):
        px = meta["pixel_size"]
        area = (roi[2] - roi[0]) * (roi[3] - roi[1]) * px ** 2
        extra = pd.DataFrame([("Region (px: x0, y0, x1, y1)", ", ".join(str(int(v)) for v in roi)),
                              (f"Region area ({meta['units']}2)", area)], columns=["measurement", "value"])
        summary = pd.concat([summary.iloc[:7], extra, summary.iloc[7:]], ignore_index=True)
    sweep = res.sweep
    if with_sweep and res.cfg.analysis.rupture and len(frames) and "cn_ref" in frames:
        from .rupture import threshold_sweep
        sweep = threshold_sweep(frames.drop(columns=["ruptured", "rupture_event", "rupture_signal",
                                                     "rupture_baseline"], errors="ignore"),
                                res.cfg.rupture, meta["interval_min"])
    return replace(res, meta=meta, frames=frames, cells=table, events=events, divisions=divisions, timecourse=tc,
                   summary=summary, terminal=terminal, sweep=sweep)


def export_roi(res: Results, roi: tuple, outdir: str, membership: str = "inside_most", video: bool = True,
               pdf: bool = True, signal: Optional[np.ndarray] = None, progress=None, log=print) -> dict:
    """Write the tables, the cropped annotated movie and the report for one region."""
    from .report import write_pdf
    from .viz import render_overlay
    H, W = res.meta["height"], res.meta["width"]
    roi = (max(int(roi[0]), 0), max(int(roi[1]), 0), min(int(roi[2]), W), min(int(roi[3]), H))
    if roi[2] - roi[0] < 16 or roi[3] - roi[1] < 16:
        raise ValueError("The region is too small.")
    os.makedirs(outdir, exist_ok=True)
    cells = cells_in_roi(res.frames, roi, membership)
    sub = subset(res, cells, roi, with_sweep=True)
    out = {"tables": write_tables(sub, outdir), "n_cells": len(cells)}
    log(f"  region {roi}: {len(cells)} cells ({MEMBERSHIP[membership]})")
    if video:
        out["video"] = render_overlay(sub, os.path.join(outdir, "annotated_movie.mp4"), roi=roi, cells=cells,
                                      labels=res.labels, progress=progress, all_frames=res.frames)
    if pdf and len(cells):
        out["pdf"] = write_pdf(sub, os.path.join(outdir, "report.pdf"), signal=signal, labels=res.labels,
                               title_note="region of interest")
    return out
