"""Nuclear rupture calling from the cytoplasm / nucleus reporter signal.

A rupture lets the NLS reporter leak into the cytoplasm, so the cytoplasmic
signal rises abruptly and returns as the envelope is repaired and the reporter
is re-imported. What counts as a rupture is controlled by `rupture.mode` and
`rupture.threshold`; this step only needs the per-frame table, so the threshold
can be changed without re-tracking.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Rupture

MODES = {
    "ratio_rise": ("cn_ref", True, "rise in cytoplasm/nucleus ratio over the cell's baseline"),
    "cyto_rise": ("cyto_ref", True, "rise in cytoplasm intensity over the cell's baseline"),
    "ratio_abs": ("cn_ref", False, "cytoplasm/nucleus ratio"),
    "cyto_abs": ("cyto_ref", False, "cytoplasm intensity"),
}


def signal_column(mode: str) -> str:
    return MODES[mode][0]


def noise_level(frames: pd.DataFrame, column: str) -> float:
    d = frames.sort_values(["cell", "frame"]).groupby("cell")[column].diff().dropna().to_numpy()
    if d.size < 20:
        return 0.0
    return float(np.median(np.abs(d - np.median(d))) * 1.4826 / np.sqrt(2))


def auto_threshold(frames: pd.DataFrame, cfg: Rupture) -> float:
    column, rise, _ = MODES[cfg.mode]
    noise = noise_level(frames, column)
    floor = cfg.auto_min_ratio if column == "cn_ref" else cfg.auto_min_cyto
    if rise:
        return float(max(cfg.auto_sigma * noise, floor))
    typical = float(frames[column].median())
    return float(typical + max(cfg.auto_sigma * noise, floor))


def _call_track(x: np.ndarray, blocked: np.ndarray, thr: float, cfg: Rupture, rise: bool):
    """State machine for one cell. Returns (signal, baseline, ruptured flags)."""
    n = len(x)
    W = max(int(cfg.baseline_window_frames), 3)
    signal = np.full(n, np.nan)
    baseline = np.full(n, np.nan)
    ruptured = np.zeros(n, bool)
    off = thr * cfg.off_fraction if rise else thr
    usable = np.isfinite(x) & ~blocked
    first = x[usable][:W]
    start_base = float(np.percentile(first, 25)) if first.size else np.nan
    history = []                 # recent non-ruptured values
    active, frozen = False, np.nan
    below = weak = 0             # consecutive frames under the off level / under the threshold
    tail = []                    # indices of the usable frames of the current event

    def close(k):
        """End the event, releasing its last k usable frames."""
        nonlocal active, below, weak
        released = tail[len(tail) - k:]
        if released:
            ruptured[released[0]:released[-1] + 1] = False
            history.extend(x[released])
        active, below, weak = False, 0, 0
        tail.clear()

    for t in range(n):
        if not rise:
            base = 0.0
        elif active:
            base = frozen
        else:
            # early in a track the first values may already be elevated, so start from the low quartile
            base = float(np.median(history[-W:])) if len(history) >= 3 else start_base
        baseline[t] = base
        if not usable[t]:
            if blocked[t]:
                if active:
                    close(below)
            else:
                ruptured[t] = active
            continue
        s = x[t] - base
        signal[t] = s
        if not active:
            if s >= thr:
                active, frozen = True, base
                ruptured[t] = True
                tail.append(t)
            else:
                history.append(x[t])
            continue
        ruptured[t] = True
        tail.append(t)
        below = below + 1 if s < off else 0
        weak = weak + 1 if s < thr else 0
        if below >= cfg.min_off_frames:
            close(below)
        elif rise and cfg.max_plateau_frames and weak >= cfg.max_plateau_frames:
            close(weak)          # a new steady level, not a rupture in progress
    if active and below:          # trailing sub-threshold frames are not part of the rupture
        close(below)
    return signal, baseline, ruptured


def _runs(flags: np.ndarray):
    padded = np.concatenate([[False], flags, [False]])
    change = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(change[::2], change[1::2] - 1))


def detect_ruptures(frames: pd.DataFrame, cfg: Rupture, interval_min: float, threshold: float | None = None,
                    radius_px: float = 0.0):
    """Call ruptures. Returns (frames with rupture columns, events table, threshold used)."""
    if cfg.mode not in MODES:
        raise ValueError(f"rupture.mode must be one of {', '.join(MODES)}")
    column, rise, _ = MODES[cfg.mode]
    thr = threshold if threshold is not None else cfg.threshold
    if thr is None:
        thr = auto_threshold(frames, cfg)
    frames = frames.sort_values(["cell", "frame"]).reset_index(drop=True)
    blocked_col = np.zeros(len(frames), bool)
    skip = ["mitotic", "signal_absent", "reference_lost"] + (["near_edge"] if cfg.ignore_at_image_edge else [])
    for col in skip:                              # no rupture is called in these frames
        if col in frames:
            blocked_col |= frames[col].fillna(False).to_numpy(bool)
    sig = np.full(len(frames), np.nan)
    base = np.full(len(frames), np.nan)
    rup = np.zeros(len(frames), bool)
    event_id = np.zeros(len(frames), np.int64)
    events = []
    x_all = frames[column].to_numpy(float)
    f_all = frames["frame"].to_numpy()
    bounds = frames.groupby("cell", sort=False).indices
    for cell, idx in bounds.items():
        idx = np.sort(idx)
        x, blocked = x_all[idx], blocked_col[idx]
        cell_thr = thr
        if rise and cfg.noise_factor > 0:
            d = np.diff(x[np.isfinite(x) & ~blocked])
            if d.size >= 8:
                noise = np.median(np.abs(d - np.median(d))) * 1.4826 / np.sqrt(2)
                cell_thr = max(thr, cfg.noise_factor * noise)
        s, b, r = _call_track(x, blocked, cell_thr, cfg, rise)
        runs = _runs(r)
        # merge events separated by a short dip, drop events that are too short
        merged = []
        for a, e in runs:
            if merged and a - merged[-1][1] - 1 <= cfg.merge_gap_frames:
                merged[-1] = (merged[-1][0], e)
            else:
                merged.append((a, e))
        r[:] = False
        k = 0
        for a, e in merged:
            if e - a + 1 < cfg.min_duration_frames:
                continue
            first_usable = int(np.argmax(np.isfinite(x) & ~blocked))
            if a <= first_usable and not cfg.count_at_track_start:
                continue
            k += 1
            r[a:e + 1] = True
            event_id[idx[a:e + 1]] = k
            seg = s[a:e + 1]
            peak = int(np.nanargmax(seg)) if np.isfinite(seg).any() else 0
            peak_val = float(np.nanmax(seg)) if np.isfinite(seg).any() else np.nan
            after = seg[peak:]
            half = np.flatnonzero(after <= 0.5 * peak_val)
            row = frames.iloc[idx[a]]
            prev = frames.iloc[idx[max(a - 1, 0)]]
            events.append(dict(
                cell=cell, event=k, start_frame=int(f_all[idx[a]]), end_frame=int(f_all[idx[e]]),
                start_min=f_all[idx[a]] * interval_min, duration_frames=int(e - a + 1),
                duration_min=(e - a + 1) * interval_min, peak_signal=peak_val, threshold=float(cell_thr),
                peak_value=float(np.nanmax(x[a:e + 1])) if np.isfinite(x[a:e + 1]).any() else np.nan,
                baseline=float(b[a]), time_to_peak_min=peak * interval_min,
                recovery_half_time_min=float(half[0] * interval_min) if len(half) else np.nan,
                starts_at_track_start=bool(a == 0), ongoing_at_track_end=bool(e == len(idx) - 1),
                nucleus_lost=bool((~frames["detected"].to_numpy()[idx[a:e + 1]]).any()),
                signal_flooded=bool(frames["abnormal_mask"].to_numpy()[idx[a:e + 1]].any()),
                x=float(row.x), y=float(row.y),
                area_before=float(prev.get("area", np.nan)), circularity_before=float(prev.get("circularity", np.nan)),
                aspect_ratio_before=float(prev.get("aspect_ratio", np.nan)),
                solidity_before=float(prev.get("solidity", np.nan))))
        sig[idx], base[idx], rup[idx] = s, b, r
    events = pd.DataFrame(events)
    if len(events):
        events["repaired"] = ~events["ongoing_at_track_end"]
        events["spillover_from"] = _spillover(events, radius_px)
        if cfg.ignore_spillover and events["spillover_from"].notna().any():
            for e in events[events["spillover_from"].notna()].itertuples():
                sel = bounds[e.cell][np.isin(f_all[bounds[e.cell]], np.arange(e.start_frame, e.end_frame + 1))]
                rup[sel], event_id[sel] = False, 0
            events = events[events["spillover_from"].isna()].copy()
            events["event"] = events.groupby("cell").cumcount() + 1
            for e in events.itertuples():
                sel = bounds[e.cell][np.isin(f_all[bounds[e.cell]], np.arange(e.start_frame, e.end_frame + 1))]
                event_id[sel] = e.event
            events = events.reset_index(drop=True)
    frames["rupture_signal"] = sig
    frames["rupture_baseline"] = base
    frames["ruptured"] = rup
    frames["rupture_event"] = event_id
    return frames, events, float(thr)


def _spillover(events: pd.DataFrame, radius_px: float) -> pd.Series:
    """For each event, the cell whose much larger rupture next door explains it, if there is one.

    The cytoplasm of a ruptured cell can reach into the ring measured around a
    neighbouring nucleus. The neighbour then shows a rise at the same moment, but a
    much smaller one.
    """
    out = pd.Series(np.nan, index=events.index, dtype=float)
    if not radius_px or len(events) < 2:
        return out
    from scipy.spatial import cKDTree
    xy = events[["x", "y"]].to_numpy()
    tree = cKDTree(xy)
    start, end = events["start_frame"].to_numpy(), events["end_frame"].to_numpy()
    peak, cell = events["peak_signal"].to_numpy(), events["cell"].to_numpy()
    for i, near in enumerate(tree.query_ball_point(xy, 4.5 * radius_px)):
        for j in near:
            if j == i or cell[j] == cell[i]:
                continue
            same_time = start[i] <= end[j] + 1 and end[i] >= start[j] - 1 and abs(start[i] - start[j]) <= 2
            if same_time and peak[i] < 0.5 * peak[j] and peak[i] < 0.35:
                out.iloc[i] = cell[j]
                break
    return out


def threshold_sweep(frames: pd.DataFrame, cfg: Rupture, interval_min: float, n: int = 25) -> pd.DataFrame:
    """Number of ruptures called as a function of the threshold, to help choosing one."""
    column, rise, _ = MODES[cfg.mode]
    x = frames[column].dropna()
    if rise:
        hi = float(np.nanpercentile(x, 99.5) - np.nanpercentile(x, 5))
        grid = np.linspace(max(hi / 40, 1e-3), max(hi, 1e-2), n)
    else:
        grid = np.linspace(float(np.nanpercentile(x, 50)), float(np.nanpercentile(x, 99.8)), n)
    rows = []
    n_cells = frames["cell"].nunique()
    for thr in grid:
        _, ev, _ = detect_ruptures(frames, cfg, interval_min, threshold=float(thr))
        rows.append(dict(threshold=float(thr), ruptures=len(ev),
                         cells_with_rupture=ev["cell"].nunique() if len(ev) else 0,
                         fraction_of_cells=(ev["cell"].nunique() / n_cells) if len(ev) and n_cells else 0.0,
                         median_duration_min=float(ev["duration_min"].median()) if len(ev) else np.nan))
    return pd.DataFrame(rows)
