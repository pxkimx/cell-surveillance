"""End-to-end analysis of one movie, and fast re-analysis from saved results."""
from __future__ import annotations

import json
import os
import pickle
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from . import __version__, history
from .config import Config
from .fate import assign_fates
from .io import Movie, load_movie
from .lineage import classify_divisions, relink
from .measure import add_reference_measurements
from .metrics import (add_neighbors, add_positions, annotate_events, population_summary, population_timecourse,
                      summarize_cells)
from .rupture import detect_ruptures, threshold_sweep
from .segment import make_params, segment_movie
from .track import build_tracks, make_track_params

INTERNAL = "analysis_data"
MAX_MITOSIS_FRAMES = 12

# columns of the per-frame export, in order, with the analysis they belong to
FRAME_COLUMNS = [
    ("cell", None), ("parent", None), ("frame", None), ("time_min", None), ("x_um", None), ("y_um", None),
    ("detected", None), ("at_border", None),
    ("ruptured", "rupture"), ("rupture_event", "rupture"), ("rupture_signal", "rupture"),
    ("rupture_baseline", "rupture"), ("cn_ref", "rupture"), ("cyto_ref", "rupture"), ("nuc_ref", "rupture"),
    ("abnormal_mask", "rupture"), ("signal_absent", "rupture"), ("reference_lost", "rupture"),
    ("near_edge", "rupture"), ("terminal_loss", "death"), ("mitotic", "division"),
    ("step_um", "movement"), ("speed_um_per_min", "movement"),
    ("area_um2", "morphology"), ("perimeter_um", "morphology"), ("circularity", "morphology"),
    ("solidity", "morphology"), ("aspect_ratio", "morphology"), ("eccentricity", "morphology"),
    ("major_axis_um", "morphology"), ("minor_axis_um", "morphology"), ("orientation", "morphology"),
    ("n_fragments", "morphology"), ("n_micronuclei", "morphology"), ("micronuclei_area_um2", "morphology"),
    ("nuc_saturated_frac", "morphology"),
    ("nearest_neighbor_um", "neighbors"), ("neighbors_in_radius", "neighbors"),
]
RENAME = {"cn_ref": "cyto_nuc_ratio", "cyto_ref": "cytoplasm_intensity", "nuc_ref": "nuclear_intensity",
          "abnormal_mask": "signal_flooded"}


@dataclass
class Results:
    outdir: str
    meta: dict
    cfg: Config
    frames: pd.DataFrame
    cells: pd.DataFrame
    events: pd.DataFrame
    divisions: pd.DataFrame
    timecourse: pd.DataFrame
    summary: pd.DataFrame
    sweep: pd.DataFrame
    labels: Optional[np.ndarray] = None
    signal: Optional[np.ndarray] = None
    terminal: Optional[pd.DataFrame] = None     # loss of nuclear signal at death, kept apart from ruptures

    def export_frames(self) -> pd.DataFrame:
        return export_frames(self.frames, self.cfg, self.meta["pixel_size"])


def export_frames(frames: pd.DataFrame, cfg: Config, px: float) -> pd.DataFrame:
    f = frames.copy()
    if "area" in f:
        f["area_um2"] = f["area"] * px ** 2
        f["perimeter_um"] = f["perimeter"] * px
        f["major_axis_um"], f["minor_axis_um"] = f["major_axis"] * px, f["minor_axis"] * px
        f["micronuclei_area_um2"] = f["micronuclei_area"] * px ** 2
    cols = [c for c, group in FRAME_COLUMNS if c in f and (group is None or getattr(cfg.analysis, group))]
    return f[cols].rename(columns=RENAME)


def _noop(*_):
    pass


def _cached_segmentation(outdir: str, path: str, p):
    """Labels and detections from a previous run with identical segmentation settings."""
    cache = os.path.join(outdir, INTERNAL, "detections.pkl")
    if not os.path.exists(cache):
        return None
    try:
        with open(cache, "rb") as fh:
            saved = pickle.load(fh)
        if saved["params"] == p and saved["path"] == os.path.abspath(path) and \
                saved["mtime"] == os.path.getmtime(path):
            return load_labels(outdir), saved["det"]
    except Exception:
        return None
    return None


class CalibrationError(ValueError):
    """The user has not supplied a calibration value that cannot be guessed."""


def analyze(path: str, cfg: Config, outdir: str, log: Callable = print,
            progress: Callable[[str, float], None] = _noop, show_bars: bool = True, reuse: bool = True,
            keep_earlier: bool = True, record: bool = True) -> Results:
    """Run the full analysis on one movie and write all outputs to `outdir`.

    If `outdir` already holds a finished analysis it is moved to 'earlier runs' first, not overwritten.
    """
    interval = cfg.calibration.frame_interval_min
    if interval is None or not float(interval) > 0:
        raise CalibrationError("The time between frames was not given. It is different for every movie and is not "
                               "stored in the file, so it has to be entered.")
    t_start = time.time()
    earlier = history.archive(outdir) if (keep_earlier and record) else None
    os.makedirs(os.path.join(outdir, INTERNAL), exist_ok=True)
    log(f"Analyzing {os.path.basename(path)}")
    if earlier:
        log(f"  the previous results were kept in '{os.path.relpath(earlier, outdir)}'")

    progress("Reading movie", 0.02)
    movie = load_movie(path, cfg, log)
    p = make_params(movie, cfg, log)

    progress("Finding nuclei", 0.08)
    cached = _cached_segmentation(outdir, path, p) if reuse else None
    if cached is not None:
        labels, det = cached
        log("  segmentation reused from the previous run")
    else:
        labels, det = segment_movie(movie, p, log, progress=show_bars,
                                    on_step=lambda f: progress("Finding nuclei", 0.08 + 0.45 * f))
        if det.empty:
            raise RuntimeError("No nuclei were found. Check the channel and threshold settings.")
        np.savez_compressed(os.path.join(outdir, INTERNAL, "labels.npz"), labels=labels)
        with open(os.path.join(outdir, INTERNAL, "detections.pkl"), "wb") as fh:
            pickle.dump(dict(params=p, det=det, path=os.path.abspath(path), mtime=os.path.getmtime(path)), fh)

    progress("Tracking cells", 0.55)
    tp = make_track_params(cfg, p, movie)
    det = build_tracks(det, tp, log)
    det, splits, gap_divs, occlusions, merged_away = relink(det, tp, movie.n_frames, log=log)

    progress("Measuring reporter signal", 0.62)
    frames, probes = add_reference_measurements(det, labels, movie, p, log=log)

    progress("Building lineages", 0.70)
    if cfg.analysis.division:
        frames, divisions = classify_divisions(frames, splits, gap_divs, cfg.fate, log)
    else:
        frames, divisions = classify_divisions(frames, pd.DataFrame(), pd.DataFrame(), cfg.fate, _noop)

    meta = dict(movie=os.path.basename(path), path=os.path.abspath(path), n_frames=movie.n_frames,
                height=movie.shape[0], width=movie.shape[1], pixel_size=movie.pixel_size_um, units=movie.units,
                interval_min=movie.frame_interval_min, interval_confirmed=bool(cfg.calibration.interval_confirmed),
                size_confirmed=bool(cfg.calibration.size_confirmed) and movie.units == "um",
                scale_bar_um=cfg.calibration.scale_bar_um,
                channel=movie.channel, composite=movie.composite,
                saturated=movie.saturated, scale_bar_px=movie.scale_bar_px, crop=movie.crop,
                nuclear_radius_px=p.radius, low_threshold=p.low_threshold, version=__version__)
    state = dict(frames=frames, probes=probes, divisions=divisions, merged_away=merged_away,
                 occlusions=occlusions, seg_params=p)
    with open(os.path.join(outdir, INTERNAL, "state.pkl"), "wb") as fh:
        pickle.dump(state, fh)

    res = _finish(outdir, meta, cfg, state, log, progress)
    res.labels = labels
    res.signal = movie.signal
    meta["seconds"] = round(time.time() - t_start, 1)
    _write_meta(outdir, meta, cfg)
    try:
        from .io import iter_frames
        history.save_thumbnail(outdir, next(iter_frames(path, max_frames=1, crop=movie.crop)))
        if record:
            history.register(outdir)
    except Exception as err:                  # the history is a convenience; it must never fail an analysis
        log(f"  (history not updated: {err})")
    log(f"  finished in {meta['seconds']:.0f} s -> {outdir}")
    progress("Done", 1.0)
    return res


def _finish(outdir: str, meta: dict, cfg: Config, state: dict, log, progress=_noop) -> Results:
    """Everything downstream of tracking: events, fates, summaries and tables."""
    frames, divisions, p = state["frames"].copy(), state["divisions"], state["seg_params"]
    meta.setdefault("interval_confirmed", False)      # results made before calibration had to be confirmed
    meta.setdefault("size_confirmed", False)
    px, interval, T = meta["pixel_size"], meta["interval_min"], meta["n_frames"]
    an = cfg.analysis

    frames["mitotic"] = False
    if len(divisions):
        L = cfg.fate.mitotic_lookback_frames
        for d in divisions[divisions["confidence"] == "high"].itertuples():
            frames.loc[(frames["cell"] == d.mother) & (frames["frame"] >= d.frame - L), "mitotic"] = True
            # the reporter disperses from nuclear envelope breakdown onwards: walk back to where that started
            m = frames[(frames["cell"] == d.mother) & (frames["frame"] < d.frame - L)].sort_values("frame")
            calm = float(m["cn_ref"].median()) if len(m) else 0.0
            for r in m.iloc[::-1].head(MAX_MITOSIS_FRAMES).itertuples():
                dispersed = (not r.detected) or r.abnormal_mask or not np.isfinite(r.cn_ref) or \
                    r.cn_ref >= max(0.6, calm + 0.35)
                if not dispersed:
                    break
                frames.loc[r.Index, "mitotic"] = True
            for child in (d.daughter_a, d.daughter_b):
                if pd.notna(child):
                    sel = frames["cell"] == child
                    first = frames.loc[sel, "frame"].min()
                    frames.loc[sel & (frames["frame"] < first + cfg.fate.post_mitotic_frames), "mitotic"] = True

    edge = np.minimum.reduce([frames["x"], frames["y"], meta["width"] - 1 - frames["x"],
                              meta["height"] - 1 - frames["y"]])
    frames["near_edge"] = frames["at_border"].fillna(False).astype(bool) | (edge < 1.5 * p.radius)

    progress("Calling ruptures", 0.78)
    if an.rupture:
        frames, events, thr = detect_ruptures(frames, cfg.rupture, interval, radius_px=p.radius)
        sweep = threshold_sweep(frames, cfg.rupture, interval)
        calls = (len(events), events["cell"].nunique() if len(events) else 0)
    else:
        events, thr, sweep = pd.DataFrame(), None, pd.DataFrame()
        frames["ruptured"] = False
        frames["rupture_event"] = 0
    if "terminal_loss" not in frames:
        frames["terminal_loss"] = False
    meta["rupture_threshold"] = thr
    meta["rupture_mode"] = cfg.rupture.mode

    progress("Measuring movement", 0.84)
    frames, drift = add_positions(frames, px, interval, T, cfg.tracking.drift_correction and an.movement)
    meta["drift_um"] = float(np.hypot(*drift[-1]))
    meta["drift_corrected"] = bool(cfg.tracking.drift_correction and an.movement)
    if an.neighbors:
        frames = add_neighbors(frames, cfg.fate.neighbor_radius_um if meta["units"] == "um"
                               else cfg.fate.neighbor_radius_um / p.scale)

    progress("Classifying cell fates", 0.88)
    fates = assign_fates(frames, state["probes"], divisions, state["merged_away"], T,
                         (meta["height"], meta["width"]), edge_px=2.5 * p.radius, low_threshold=p.low_threshold,
                         fate=cfg.fate, detect_death=an.death, radius_px=p.radius)
    # loss of the nuclear signal as a cell dies is not a rupture that could be repaired
    terminal = pd.DataFrame()
    if len(events):
        died = events["cell"].map(fates.set_index("cell")["fate"]) == "death"
        last = events["ongoing_at_track_end"]
        events["kind"] = np.where(last & died, "terminal", np.where(last, "ongoing", "repaired"))
        terminal = events[events["kind"] == "terminal"]
        events = events[events["kind"] != "terminal"].reset_index(drop=True)
        for e in terminal.itertuples():
            sel = (frames["cell"] == e.cell) & frames["frame"].between(e.start_frame, e.end_frame)
            frames.loc[sel, ["ruptured", "rupture_event", "terminal_loss"]] = [False, 0, True]
    cells = summarize_cells(frames, events, fates, divisions, cfg, px, interval)
    events = annotate_events(events, cells, frames, interval, px)
    terminal = annotate_events(terminal, cells, frames, interval, px)
    tc = population_timecourse(frames, events, cells, divisions, T, interval)
    summary = population_summary(cells, events, divisions, tc, cfg, meta)
    if len(divisions):
        divisions = divisions.copy()
        divisions["time_min"] = divisions["frame"] * interval
        for c in ("mother_area", "daughter_a_area", "daughter_b_area"):
            divisions[c + "_um2"] = divisions.pop(c) * px ** 2
    if an.rupture:
        log(f"  {len(events)} ruptures in {events['cell'].nunique() if len(events) else 0} cells, "
            f"{len(terminal)} terminal losses of nuclear signal (mode={cfg.rupture.mode}, threshold={thr:.3g})")
    log(f"  fates: " + ", ".join(f"{k} {v}" for k, v in cells["fate"].value_counts().items()))

    res = Results(outdir, meta, cfg, frames, cells, events, divisions, tc, summary, sweep, terminal=terminal)
    write_tables(res, outdir)
    with open(os.path.join(outdir, INTERNAL, "results.pkl"), "wb") as fh:
        pickle.dump(res, fh)
    return res


def write_tables(res: Results, outdir: str, prefix: str = "") -> list[str]:
    """Write the CSV exports. Returns the list of files written."""
    os.makedirs(outdir, exist_ok=True)
    an = res.cfg.analysis
    tables = {"cells_summary": res.cells, "cells_per_frame": res.export_frames(),
              "population_summary": res.summary, "population_timecourse": res.timecourse}
    if an.rupture:
        parts = [t for t in (res.events, res.terminal) if t is not None and len(t)]
        tables["rupture_events"] = pd.concat(parts, ignore_index=True).sort_values(["cell", "start_frame"]) \
            if parts else res.events
        tables["rupture_threshold_sweep"] = res.sweep
    if an.division:
        tables["divisions"] = res.divisions
    if an.death:
        dead = res.cells[res.cells["fate"] == "death"]
        keep = [c for c in ("cell", "lineage", "death_time_min", "death_confidence", "fate_evidence", "n_ruptures",
                            "min_from_last_rupture_to_death", "x_end_um", "y_end_um", "observed_min") if c in dead]
        tables["deaths"] = dead[keep]
    written = []
    for name, table in tables.items():
        path = os.path.join(outdir, f"{prefix}{name}.csv")
        table.to_csv(path, index=False, float_format="%.5g")
        written.append(path)
    return written


def _write_meta(outdir: str, meta: dict, cfg: Config) -> None:
    with open(os.path.join(outdir, INTERNAL, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    cfg.save(os.path.join(outdir, "settings_used.yaml"))


def load_results(outdir: str, with_labels: bool = False, cfg: Optional[Config] = None, log=_noop,
                 recompute: bool = True) -> Results:
    """Reload a finished analysis, re-calling events with `cfg` if one is given."""
    saved = os.path.join(outdir, INTERNAL, "results.pkl")
    if cfg is None and not recompute and os.path.exists(saved):
        try:
            with open(saved, "rb") as fh:
                res = pickle.load(fh)
            res.outdir = outdir
            res.meta["path"] = history.locate_movie(outdir, res.meta)
            if with_labels:
                res.labels = load_labels(outdir)
            return res
        except Exception:
            pass
    with open(os.path.join(outdir, INTERNAL, "meta.json")) as fh:
        meta = json.load(fh)
    meta["path"] = history.locate_movie(outdir, meta)
    with open(os.path.join(outdir, INTERNAL, "state.pkl"), "rb") as fh:
        state = pickle.load(fh)
    if cfg is None:
        cfg = Config.load(os.path.join(outdir, "settings_used.yaml"))
    res = _finish(outdir, meta, cfg, state, log)
    _write_meta(outdir, meta, cfg)
    history.register(outdir)
    if with_labels:
        res.labels = load_labels(outdir)
    return res


def recalibrate(outdir: str, interval_min: Optional[float] = None, pixel_size_um: Optional[float] = None,
                scale_bar_um: Optional[float] = None, log=print) -> Results:
    """Apply a frame interval and/or pixel size given by the user to a finished analysis.

    Tracking is kept. Every time, speed, distance and area is recomputed from the new values.
    """
    with open(os.path.join(outdir, INTERNAL, "meta.json")) as fh:
        meta = json.load(fh)
    meta["path"] = history.locate_movie(outdir, meta)
    with open(os.path.join(outdir, INTERNAL, "state.pkl"), "rb") as fh:
        state = pickle.load(fh)
    cfg = Config.load(os.path.join(outdir, "settings_used.yaml"))
    if interval_min is not None:
        if not float(interval_min) > 0:
            raise CalibrationError("The time between frames must be greater than zero.")
        meta["interval_min"] = float(interval_min)
        meta["interval_confirmed"] = True
        cfg.calibration.frame_interval_min = float(interval_min)
        cfg.calibration.interval_confirmed = True
    if scale_bar_um is not None:
        if not meta.get("scale_bar_px"):
            raise CalibrationError("No scale bar was found in this movie; give the pixel size instead.")
        pixel_size_um = float(scale_bar_um) / meta["scale_bar_px"]
        meta["scale_bar_um"] = float(scale_bar_um)
        cfg.calibration.scale_bar_um = float(scale_bar_um)
    if pixel_size_um is not None:
        if not float(pixel_size_um) > 0:
            raise CalibrationError("The pixel size must be greater than zero.")
        meta["pixel_size"], meta["units"], meta["size_confirmed"] = float(pixel_size_um), "um", True
        cfg.calibration.size_confirmed = True
        if scale_bar_um is None:
            cfg.calibration.pixel_size_um = float(pixel_size_um)
            cfg.calibration.scale_bar_um = None
            meta["scale_bar_um"] = None
    meta.setdefault("interval_confirmed", False)
    meta.setdefault("size_confirmed", False)
    res = _finish(outdir, meta, cfg, state, log)
    _write_meta(outdir, meta, cfg)
    history.register(outdir)
    log(f"  calibration: {meta['interval_min']:g} min per frame, {meta['pixel_size']:.4g} {meta['units']}/px")
    return res


def load_labels(outdir: str) -> np.ndarray:
    return np.load(os.path.join(outdir, INTERNAL, "labels.npz"))["labels"]


def recall(outdir: str, threshold: Optional[float] = None, mode: Optional[str] = None, log=print, **rupture) -> Results:
    """Re-call ruptures with a new threshold without segmenting or tracking again."""
    cfg = Config.load(os.path.join(outdir, "settings_used.yaml"))
    if mode:
        cfg.rupture.mode = mode
    cfg.rupture.threshold = threshold
    for key, value in rupture.items():
        setattr(cfg.rupture, key, value)
    return load_results(outdir, cfg=cfg, log=log)
