"""Per-cell and population measurements."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .config import Config


def estimate_drift(frames: pd.DataFrame, n_frames: int) -> np.ndarray:
    """Cumulative median displacement of all cells, (n_frames, 2) in pixels."""
    d = frames[frames["detected"]].sort_values(["cell", "frame"])
    same = d["cell"].to_numpy()[1:] == d["cell"].to_numpy()[:-1]
    step = (d["frame"].to_numpy()[1:] - d["frame"].to_numpy()[:-1]) == 1
    ok = same & step
    dx = (d["x"].to_numpy()[1:] - d["x"].to_numpy()[:-1])[ok]
    dy = (d["y"].to_numpy()[1:] - d["y"].to_numpy()[:-1])[ok]
    f = d["frame"].to_numpy()[1:][ok]
    drift = np.zeros((n_frames, 2))
    med = pd.DataFrame({"f": f, "dx": dx, "dy": dy}).groupby("f").median()
    drift[med.index.to_numpy(), 0] = med["dx"].to_numpy()
    drift[med.index.to_numpy(), 1] = med["dy"].to_numpy()
    return np.cumsum(drift, axis=0)


def add_positions(frames: pd.DataFrame, px: float, interval: float, n_frames: int, correct_drift: bool):
    """Calibrated positions, displacement and speed for every frame."""
    frames = frames.sort_values(["cell", "frame"]).reset_index(drop=True)
    drift = estimate_drift(frames, n_frames)
    f = frames["frame"].to_numpy()
    x, y = frames["x"].to_numpy(float), frames["y"].to_numpy(float)
    if correct_drift:
        x, y = x - drift[f, 0], y - drift[f, 1]
    frames["time_min"] = f * interval
    frames["x_um"], frames["y_um"] = x * px, y * px
    same = np.concatenate([[False], frames["cell"].to_numpy()[1:] == frames["cell"].to_numpy()[:-1]])
    dt = np.concatenate([[1], np.diff(f)]) * interval
    step = np.hypot(np.concatenate([[0], np.diff(frames["x_um"])]), np.concatenate([[0], np.diff(frames["y_um"])]))
    frames["step_um"] = np.where(same, step, np.nan)
    frames["speed_um_per_min"] = np.where(same, step / np.maximum(dt, 1e-9), np.nan)
    return frames, drift * px


def add_neighbors(frames: pd.DataFrame, radius_um: float) -> pd.DataFrame:
    nn = np.full(len(frames), np.nan)
    count = np.zeros(len(frames), int)
    for _, idx in frames.groupby("frame").indices.items():
        pts = frames[["x_um", "y_um"]].to_numpy()[idx]
        if len(pts) < 2:
            continue
        tree = cKDTree(pts)
        d, _ = tree.query(pts, k=2)
        nn[idx] = d[:, 1]
        count[idx] = np.array([len(v) - 1 for v in tree.query_ball_point(pts, radius_um)])
    frames["nearest_neighbor_um"] = nn
    frames["neighbors_in_radius"] = count
    return frames


def _msd_fit(x: np.ndarray, y: np.ndarray, interval: float):
    n = len(x)
    max_lag = min(n // 3, 30)
    if max_lag < 3:
        return np.nan, np.nan
    lags = np.arange(1, max_lag + 1)
    msd = np.array([np.mean((x[l:] - x[:-l]) ** 2 + (y[l:] - y[:-l]) ** 2) for l in lags])
    ok = msd > 0
    if ok.sum() < 3:
        return np.nan, np.nan
    slope, intercept = np.polyfit(np.log(lags[ok] * interval), np.log(msd[ok]), 1)
    return float(slope), float(np.exp(intercept) / 4)


def _movement(g: pd.DataFrame, interval: float) -> dict:
    x, y = g["x_um"].to_numpy(), g["y_um"].to_numpy()
    steps = g["step_um"].to_numpy()[1:]
    path = float(np.nansum(steps))
    net = float(np.hypot(x[-1] - x[0], y[-1] - y[0]))
    out = dict(path_length_um=path, net_displacement_um=net,
               max_displacement_um=float(np.hypot(x - x[0], y - y[0]).max()),
               persistence=net / path if path > 0 else np.nan,
               mean_speed_um_per_min=float(np.nanmean(g["speed_um_per_min"])) if len(g) > 1 else np.nan,
               max_speed_um_per_min=float(np.nanmax(g["speed_um_per_min"])) if len(g) > 1 else np.nan)
    if len(x) >= 3:
        hx, hy = np.diff(x), np.diff(y)
        ang = np.arctan2(hy, hx)
        moving = np.hypot(hx, hy) > 0.2
        turn = np.abs(np.angle(np.exp(1j * np.diff(ang))))[moving[1:] & moving[:-1]]
        out["mean_turning_angle_deg"] = float(np.degrees(turn.mean())) if len(turn) else np.nan
    else:
        out["mean_turning_angle_deg"] = np.nan
    if g["frame"].diff().dropna().eq(1).all():
        out["msd_alpha"], out["diffusion_coeff_um2_per_min"] = _msd_fit(x, y, interval)
    else:
        out["msd_alpha"], out["diffusion_coeff_um2_per_min"] = np.nan, np.nan
    if "ruptured" in g and g["ruptured"].any() and (~g["ruptured"]).any():
        out["speed_while_ruptured"] = float(g.loc[g["ruptured"], "speed_um_per_min"].mean())
        out["speed_while_intact"] = float(g.loc[~g["ruptured"], "speed_um_per_min"].mean())
    return out


def _morphology(g: pd.DataFrame, px: float) -> dict:
    d = g[g["detected"] & ~g["abnormal_mask"]]
    if d.empty:
        d = g[g["detected"]]
    area = d["area"] * px ** 2
    out = dict(mean_area_um2=float(area.mean()), area_cv=float(area.std() / area.mean()) if len(area) > 1 else np.nan,
               area_first_um2=float(area.iloc[:3].mean()), area_last_um2=float(area.iloc[-3:].mean()),
               mean_circularity=float(d["circularity"].mean()), min_circularity=float(d["circularity"].min()),
               mean_solidity=float(d["solidity"].mean()), min_solidity=float(d["solidity"].min()),
               mean_aspect_ratio=float(d["aspect_ratio"].mean()), max_aspect_ratio=float(d["aspect_ratio"].max()),
               mean_fragments=float(d["n_fragments"].mean()), max_fragments=int(d["n_fragments"].max()),
               mean_micronuclei=float(d["n_micronuclei"].mean()), max_micronuclei=int(d["n_micronuclei"].max()))
    if len(area) >= 5:
        t = d["time_min"].to_numpy() / 60
        out["area_growth_um2_per_h"] = float(np.polyfit(t, area.to_numpy(), 1)[0])
    return out


def summarize_cells(frames: pd.DataFrame, events: pd.DataFrame, fates: pd.DataFrame, divisions: pd.DataFrame,
                    cfg: Config, px: float, interval: float) -> pd.DataFrame:
    an = cfg.analysis
    ev_by_cell = {c: e for c, e in events.groupby("cell")} if len(events) else {}
    rows = []
    for cell, g in frames.groupby("cell", sort=True):
        g = g.sort_values("frame")
        n = len(g)
        row = dict(cell=cell, n_frames=n, n_frames_detected=int(g["detected"].sum()),
                   first_time_min=float(g["time_min"].iloc[0]), last_time_min=float(g["time_min"].iloc[-1]),
                   observed_min=n * interval, x_start_um=float(g["x_um"].iloc[0]), y_start_um=float(g["y_um"].iloc[0]),
                   x_end_um=float(g["x_um"].iloc[-1]), y_end_um=float(g["y_um"].iloc[-1]))
        if an.rupture:
            ev = ev_by_cell.get(cell)
            usable = int((~g["mitotic"]).sum()) if "mitotic" in g else n
            k = 0 if ev is None else len(ev)
            row.update(n_ruptures=k, ruptured=bool(k > 0),
                       ruptures_per_hour=k / (usable * interval / 60) if usable else np.nan,
                       time_ruptured_min=float(g["ruptured"].sum() * interval),
                       fraction_time_ruptured=float(g["ruptured"].mean()),
                       baseline_cn_ratio=float(g.loc[~g["ruptured"], "cn_ref"].median()),
                       mean_cn_ratio=float(g["cn_ref"].mean()), max_cn_ratio=float(g["cn_ref"].max()),
                       mean_cyto_intensity=float(g["cyto_ref"].mean()), mean_nuclear_intensity=float(g["nuc_ref"].mean()))
            if k:
                row.update(first_rupture_min=float(ev["start_min"].min()),
                           time_to_first_rupture_min=float(ev["start_min"].min() - row["first_time_min"]),
                           mean_rupture_duration_min=float(ev["duration_min"].mean()),
                           median_rupture_duration_min=float(ev["duration_min"].median()),
                           max_rupture_duration_min=float(ev["duration_min"].max()),
                           mean_rupture_magnitude=float(ev["peak_signal"].mean()),
                           max_rupture_magnitude=float(ev["peak_signal"].max()),
                           n_unrepaired_ruptures=int((~ev["repaired"]).sum()),
                           mean_interval_between_ruptures_min=float(ev["start_min"].diff().mean()) if k > 1 else np.nan)
        if an.movement:
            row.update(_movement(g, interval))
        if an.morphology:
            row.update(_morphology(g, px))
        if an.neighbors and "nearest_neighbor_um" in g:
            row.update(mean_nearest_neighbor_um=float(g["nearest_neighbor_um"].mean()),
                       mean_neighbors_in_radius=float(g["neighbors_in_radius"].mean()))
        rows.append(row)
    cells = pd.DataFrame(rows).merge(
        fates.drop(columns=["track"]).rename(columns={"first_frame": "first_frame", "last_frame": "last_frame"}),
        on="cell", how="left")

    # lineage
    parent = cells.set_index("cell")["parent"]
    gen, root = {}, {}
    for c in cells["cell"]:
        chain, p = [c], parent.get(c)
        while pd.notna(p):
            chain.append(int(p)); p = parent.get(int(p))
        gen[c], root[c] = len(chain) - 1, chain[-1]
    cells["generation"] = cells["cell"].map(gen)
    cells["lineage"] = cells["cell"].map(root)
    if an.division and len(divisions):
        high = divisions[divisions["confidence"] == "high"]
        # a mother with three daughters (multipolar division) appears twice
        div_time = high.dropna(subset=["mother"]).groupby("mother")["frame"].min() * interval
        cells["division_time_min"] = cells["cell"].map(div_time)
        born = cells["start_reason"] == "division"
        cells["cell_cycle_min"] = np.where(born & cells["division_time_min"].notna(),
                                           cells["division_time_min"] - cells["first_time_min"], np.nan)
    if an.death:
        cells["death_time_min"] = np.where(cells["fate"] == "death", cells["last_time_min"] + interval, np.nan)
        if an.rupture and len(events):
            last_rupture = events.groupby("cell")["end_frame"].max() * interval
            gap = cells["death_time_min"] - cells["cell"].map(last_rupture)
            cells["min_from_last_rupture_to_death"] = gap
    front = ["cell", "parent", "lineage", "generation", "start_reason", "fate", "death_confidence", "fate_evidence",
             "first_frame", "last_frame"]
    return cells[[c for c in front if c in cells] + [c for c in cells if c not in front]]


def annotate_events(events: pd.DataFrame, cells: pd.DataFrame, frames: pd.DataFrame, interval: float, px: float):
    """Add context to each rupture: what the cell did before and what happened afterwards."""
    if events.empty:
        return events
    events = events.copy()
    info = cells.set_index("cell")
    events["cell_fate"] = events["cell"].map(info["fate"])
    end_time = events["cell"].map(info["last_time_min"])
    events["min_until_track_end"] = end_time - events["end_frame"] * interval
    events["area_before_um2"] = events.pop("area_before") * px ** 2
    events["x_um"], events["y_um"] = events.pop("x") * px, events.pop("y") * px
    if "speed_um_per_min" in frames:
        speed = frames.set_index(["cell", "frame"])["speed_um_per_min"]
        before = []
        for r in events.itertuples():
            vals = [speed.get((r.cell, f), np.nan) for f in range(r.start_frame - 3, r.start_frame)]
            before.append(np.nanmean(vals) if np.isfinite(vals).any() else np.nan)
        events["speed_before_um_per_min"] = before
    return events


def population_timecourse(frames: pd.DataFrame, events: pd.DataFrame, cells: pd.DataFrame, divisions: pd.DataFrame,
                          n_frames: int, interval: float) -> pd.DataFrame:
    g = frames.groupby("frame")
    tc = pd.DataFrame({"frame": np.arange(n_frames)})
    tc["time_min"] = tc["frame"] * interval
    tc["time_h"] = tc["time_min"] / 60
    tc["n_cells"] = tc["frame"].map(g.size()).fillna(0).astype(int)
    if "ruptured" in frames:
        tc["n_ruptured"] = tc["frame"].map(g["ruptured"].sum()).fillna(0).astype(int)
        tc["fraction_ruptured"] = tc["n_ruptured"] / tc["n_cells"].clip(lower=1)
        tc["mean_cn_ratio"] = tc["frame"].map(g["cn_ref"].mean())
        starts = events["start_frame"].value_counts() if len(events) else pd.Series(dtype=int)
        tc["new_ruptures"] = tc["frame"].map(starts).fillna(0).astype(int)
        tc["cumulative_ruptures"] = tc["new_ruptures"].cumsum()
    if "speed_um_per_min" in frames:
        tc["mean_speed_um_per_min"] = tc["frame"].map(g["speed_um_per_min"].mean())
    if "area" in frames:
        tc["mean_fragments"] = tc["frame"].map(g["n_fragments"].mean())
        tc["mean_solidity"] = tc["frame"].map(g["solidity"].mean())
    if len(divisions):
        d = divisions[divisions["confidence"] == "high"]["frame"].value_counts()
        tc["cumulative_divisions"] = tc["frame"].map(d).fillna(0).cumsum().astype(int)
    deaths = cells.loc[cells["fate"] == "death", "last_frame"].add(1).value_counts()
    tc["cumulative_deaths"] = tc["frame"].map(deaths).fillna(0).cumsum().astype(int)
    return tc


def population_summary(cells: pd.DataFrame, events: pd.DataFrame, divisions: pd.DataFrame, tc: pd.DataFrame,
                       cfg: Config, meta: dict) -> pd.DataFrame:
    an = cfg.analysis
    hours = cells["observed_min"].sum() / 60
    rows = [("Movie", meta["movie"]), ("Frames", meta["n_frames"]),
            ("Frame interval (min)", meta["interval_min"]),
            ("Frame interval entered by user", bool(meta.get("interval_confirmed", False))),
            ("Duration (h)", meta["n_frames"] * meta["interval_min"] / 60),
            (f"Pixel size ({meta['units']}/px)", meta["pixel_size"]),
            ("Scale confirmed by user", bool(meta.get("size_confirmed", False))),
            ("Cells tracked", len(cells)), ("Cells in first frame", int(tc["n_cells"].iloc[0])),
            ("Cells in last frame", int(tc["n_cells"].iloc[-1])), ("Total cell-hours observed", hours),
            ("Median track length (h)", cells["observed_min"].median() / 60)]
    if an.rupture:
        rows += [("Rupture mode", cfg.rupture.mode), ("Rupture threshold", meta["rupture_threshold"]),
                 ("Ruptures", len(events)), ("Cells with at least one rupture", int(cells["ruptured"].sum())),
                 ("Fraction of cells with a rupture", cells["ruptured"].mean()),
                 ("Ruptures per cell", len(events) / max(len(cells), 1)),
                 ("Ruptures per 100 cell-hours", 100 * len(events) / hours if hours else np.nan)]
        if len(events):
            done = events[events["kind"] == "repaired"]
            rows += [("Median rupture duration (min)", done["duration_min"].median()),
                     ("Mean rupture duration (min)", done["duration_min"].mean()),
                     ("Longest rupture (min)", events["duration_min"].max()),
                     ("Ruptures still open when tracking ended", int((events["kind"] == "ongoing").sum())),
                     ("Ruptures with nucleus lost or signal flooded", int((events["nucleus_lost"] | events["signal_flooded"]).sum()))]
    if an.division:
        n_div = int((divisions["confidence"] == "high").sum()) if len(divisions) else 0
        rows += [("Divisions", n_div),
                 ("Possible divisions (low confidence)", (len(divisions) - n_div) if len(divisions) else 0),
                 ("Divisions per 100 cell-hours", 100 * n_div / hours if hours else np.nan)]
        if "cell_cycle_min" in cells and cells["cell_cycle_min"].notna().any():
            rows.append(("Median cell cycle (h)", cells["cell_cycle_min"].median() / 60))
    if an.death:
        dead = cells[cells["fate"] == "death"]
        rows += [("Deaths", len(dead)), ("Deaths, high or medium confidence", int(dead["death_confidence"].isin(["high", "medium"]).sum())),
                 ("Deaths per 100 cell-hours", 100 * len(dead) / hours if hours else np.nan)]
        if an.rupture:
            rows.append(("Deaths in cells that had ruptured", int(dead["ruptured"].sum())))
    if an.movement:
        rows += [("Mean speed (um/min)", cells["mean_speed_um_per_min"].mean()),
                 ("Median path length (um)", cells["path_length_um"].median()),
                 ("Median net displacement (um)", cells["net_displacement_um"].median()),
                 ("Median persistence", cells["persistence"].median()),
                 ("Estimated stage drift (um)", meta["drift_um"]), ("Drift corrected", meta["drift_corrected"])]
    if an.morphology:
        rows += [("Mean nuclear area (um2)", cells["mean_area_um2"].mean()),
                 ("Mean circularity", cells["mean_circularity"].mean()),
                 ("Mean solidity", cells["mean_solidity"].mean()),
                 ("Cells with fragmented nucleus (>=3 fragments)", int((cells["max_fragments"] >= 3).sum())),
                 ("Cells with micronuclei", int((cells["max_micronuclei"] >= 1).sum()))]
    for f in ("divided", "death", "left_field", "end_of_movie", "occluded", "lost"):
        rows.append((f"Fate: {f}", int((cells["fate"] == f).sum())))
    return pd.DataFrame(rows, columns=["measurement", "value"])
