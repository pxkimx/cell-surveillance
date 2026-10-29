"""Benchmark: a simulated crowded movie with known tracks and events, scored automatically.

    python3 tests/benchmark.py                     # default scenario
    python3 tests/benchmark.py --cells 60 --seed 3 --set tracking.max_gap_frames=4

The simulation copies what makes the real movies hard: nuclei that saturate the
camera, cells that crawl over one another, ruptures from faint to flooding,
lobed nuclei, cells that die or leave, and video compression.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import cv2
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cellsurveillance.config import Config  # noqa: E402
from cellsurveillance.pipeline import analyze  # noqa: E402


def simulate(path: str, n_cells: int = 40, n_frames: int = 120, size: int = 900, seed: int = 0,
             saturate: bool = True, divisions: int = 3) -> dict:
    rng = np.random.default_rng(seed)
    cells = []

    def new_cell(t0, x=None, y=None, scale=1.0):
        edge = x is None and t0 > 0
        if x is None:
            if edge:                                              # walks in from a side
                side = rng.integers(4)
                x, y = [(-20, rng.uniform(0, size)), (size + 20, rng.uniform(0, size)),
                        (rng.uniform(0, size), -20), (rng.uniform(0, size), size + 20)][side]
            else:
                x, y = rng.uniform(40, size - 40, 2)
        c = dict(id=len(cells), t0=t0, t1=n_frames - 1, x=float(x), y=float(y),
                 dir=rng.uniform(0, 2 * np.pi) if not edge else np.arctan2(size / 2 - y, size / 2 - x),
                 speed=rng.gamma(2.2, 1.6), a=rng.uniform(14, 19) * scale, b=rng.uniform(10, 13) * scale,
                 rot=rng.uniform(0, np.pi), lobes=int(rng.random() < 0.2) * rng.integers(2, 5),
                 cyto=rng.uniform(18, 38), bright=rng.uniform(0.75, 1.0), fate="alive", events=[], track=[])
        cells.append(c)
        return c

    for _ in range(n_cells):
        new_cell(0)
    truth = dict(ruptures=[], deaths=[], divisions=[])
    # schedule events
    for c in list(cells):
        t = rng.integers(5, 25)
        while t < n_frames - 6:
            if rng.random() < 0.7:
                dur = int(np.clip(rng.geometric(0.22), 1, 25))
                mag = rng.choice([rng.uniform(0.25, 0.6), rng.uniform(0.6, 1.0)])
                c["events"].append((int(t), int(t + dur - 1), float(mag)))
            t += int(rng.integers(12, 45))
    dying = rng.choice(len(cells), size=max(2, n_cells // 8), replace=False)
    for i in dying:
        c = cells[i]
        c["death"] = int(rng.integers(20, n_frames - 12))
        c["death_kind"] = rng.choice(["vanish", "fragment"])
        c["events"] = [e for e in c["events"] if e[1] < c["death"] - 4]
    dividing = [i for i in rng.permutation(len(cells)) if i not in dying][:divisions]
    for i in dividing:
        c = cells[i]
        c["division"] = int(rng.integers(20, n_frames - 25))
        c["events"] = [e for e in c["events"] if e[1] < c["division"] - 6]

    frames = np.zeros((n_frames, size, size), np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    for t in range(n_frames):
        if t > 0 and rng.random() < 0.06:
            new_cell(t)
        cyto = np.zeros((size, size), np.float32)
        nuc = np.zeros((size, size), np.float32)
        for c in list(cells):
            if t < c["t0"] or c["fate"] in ("dead", "gone", "divided"):
                continue
            if t > c["t0"]:
                c["dir"] += rng.normal(0, 0.45)
                if rng.random() < 0.04:
                    c["dir"] = rng.uniform(0, 2 * np.pi)
                step = c["speed"] * rng.uniform(0.3, 1.7) * (3.0 if rng.random() < 0.03 else 1.0)
                c["x"] += np.cos(c["dir"]) * step
                c["y"] += np.sin(c["dir"]) * step
                c["rot"] += rng.normal(0, 0.06)
            x, y = c["x"], c["y"]
            if not (-30 < x < size + 30 and -30 < y < size + 30):
                c["fate"], c["t1"] = "gone", t - 1
                continue
            level, nuc_level, scale, draw_nucleus, pieces = c["cyto"], 330.0 * c["bright"], 1.0, True, 0
            for a, b, mag in c["events"]:
                if a <= t <= b:
                    decay = np.exp(-(t - a) / max((b - a + 1) / 2.0, 1.0)) if b > a else 1.0
                    level = c["cyto"] + mag * decay * (nuc_level - c["cyto"]) * 0.75
                    # the reporter equilibrates at most: the nucleus never ends up dimmer than the cytoplasm
                    nuc_level = max(nuc_level * (1 - 0.45 * mag * decay), level * 1.12)
            if "death" in c and t >= c["death"] - 4:
                k = t - (c["death"] - 4)
                if t >= c["death"]:
                    c["fate"], c["t1"] = "dead", c["death"] - 1
                    continue
                if c["death_kind"] == "fragment":
                    scale, pieces = 1 - 0.13 * k, k + 2
                else:
                    scale = 1 - 0.08 * k
                level *= max(1 - 0.22 * k, 0.1)
            if "division" in c:
                d = c["division"]
                if d - 3 <= t < d:                                 # nuclear envelope breakdown: no nucleus
                    draw_nucleus, level = False, 0.30 * nuc_level
                if t >= d:
                    c["fate"], c["t1"] = "divided", d - 1
                    kids = []
                    for sgn in (-1, 1):
                        k = new_cell(t, x + sgn * np.cos(c["rot"]) * 16, y + sgn * np.sin(c["rot"]) * 16, 0.78)
                        k["dir"], k["cyto"], k["bright"] = c["rot"] + (0 if sgn > 0 else np.pi), c["cyto"], c["bright"]
                        k["speed"] = max(c["speed"], 2.0)
                        kids.append(k["id"])
                    truth["divisions"].append(dict(cell=c["id"], frame=int(d), daughters=kids))
                    continue
            c["track"].append((t, float(x), float(y)))
            ca, cb = c["a"] * 2.6, c["b"] * 2.2
            cv2.ellipse(cyto, (int(x), int(y)), (int(ca), int(cb)), np.degrees(c["dir"]), 0, 360, float(level), -1, cv2.LINE_AA)
            if draw_nucleus:
                layer = np.zeros((size, size), np.float32)
                if pieces:
                    for j in range(pieces):
                        ang = j / pieces * 2 * np.pi + c["rot"]
                        r = c["a"] * 0.55 * (1 + 0.25 * pieces / 6)
                        cv2.circle(layer, (int(x + np.cos(ang) * r), int(y + np.sin(ang) * r)), max(int(c["a"] * 0.3 * scale), 2),
                                   float(nuc_level), -1, cv2.LINE_AA)
                else:
                    cv2.ellipse(layer, (int(x), int(y)), (max(int(c["a"] * scale), 2), max(int(c["b"] * scale), 2)),
                                np.degrees(c["rot"]), 0, 360, float(nuc_level), -1, cv2.LINE_AA)
                    for j in range(c["lobes"]):
                        ang = j / max(c["lobes"], 1) * 2 * np.pi + c["rot"]
                        cv2.circle(layer, (int(x + np.cos(ang) * c["a"] * 0.85), int(y + np.sin(ang) * c["b"] * 0.85)),
                                   int(c["b"] * 0.5), float(nuc_level), -1, cv2.LINE_AA)
                nuc = np.maximum(nuc, layer)
        img = np.maximum(cv2.GaussianBlur(cyto, (0, 0), 3.0), cv2.GaussianBlur(nuc, (0, 0), 1.1))
        frames[t] = img + rng.normal(3, 2.0, img.shape)
    for c in cells:
        for a, b, mag in c["events"]:
            if a >= c["t0"] and b <= c["t1"]:
                truth["ruptures"].append(dict(cell=c["id"], start=int(a), end=int(b), magnitude=mag))
        if c["fate"] == "dead":
            truth["deaths"].append(dict(cell=c["id"], frame=int(c["death"])))
    truth["tracks"] = pd.DataFrame([(c["id"], t, x, y) for c in cells for t, x, y in c["track"]],
                                   columns=["gt", "frame", "x", "y"])
    ceiling = 255.0 if saturate else float(np.percentile(frames, 99.99))
    out = np.clip(frames / ceiling * 255.0 if not saturate else frames, 0, 255).astype(np.uint8)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"avc1"), 6, (size, size))
    for f in out:
        bgr = np.zeros((size, size, 3), np.uint8)
        bgr[..., 1] = f
        writer.write(bgr)
    writer.release()
    truth["n_frames"], truth["size"] = n_frames, size
    return truth


def score(res, truth, gate: float = 14.0) -> dict:
    gt = truth["tracks"]
    pred = res.frames[res.frames["detected"]][["cell", "frame", "x", "y"]]
    pairs = []
    n_gt = n_pred = n_match = 0
    inside = lambda d: d[(d.x > 25) & (d.y > 25) & (d.x < truth["size"] - 25) & (d.y < truth["size"] - 25)]
    for t in range(truth["n_frames"]):
        g, p = inside(gt[gt.frame == t]), inside(pred[pred.frame == t])
        n_gt += len(g); n_pred += len(p)
        if g.empty or p.empty:
            continue
        d = np.hypot(g.x.to_numpy()[:, None] - p.x.to_numpy()[None], g.y.to_numpy()[:, None] - p.y.to_numpy()[None])
        r, c = linear_sum_assignment(np.where(d <= gate, d, 1e6))
        for i, j in zip(r, c):
            if d[i, j] <= gate:
                pairs.append((int(g["gt"].iloc[i]), int(p["cell"].iloc[j]), t)); n_match += 1
    m = pd.DataFrame(pairs, columns=["gt", "cell", "frame"]).sort_values(["gt", "frame"])
    switches = int((m.groupby("gt")["cell"].apply(lambda s: (s != s.shift()).sum() - 1)).sum())
    fragments = float(m.groupby("gt")["cell"].nunique().mean())
    cell_of = {(g, f): c for g, c, f in pairs}
    gt_of = {(c, f): g for g, c, f in pairs}

    # a track counts as followed if one predicted cell covers at least 80% of it
    cover = m.groupby(["gt", "cell"]).size().groupby("gt").max() / gt.groupby("gt").size().reindex(m["gt"].unique())
    followed = float((cover >= 0.8).mean())

    ev = res.events
    hits, durations = set(), []
    good = 0
    for e in (ev.itertuples() if len(ev) else []):
        g = next((gt_of[(e.cell, f)] for f in range(e.start_frame, e.end_frame + 1) if (e.cell, f) in gt_of), None)
        ok = False
        for k, r in enumerate(truth["ruptures"]):
            if r["cell"] == g and e.start_frame <= r["end"] + 1 and e.end_frame >= r["start"] - 1:
                ok = True
                if k not in hits:
                    hits.add(k); durations.append((e.end_frame - e.start_frame) - (r["end"] - r["start"]))
        good += ok
    visible = [k for k, r in enumerate(truth["ruptures"]) if any((r["cell"], f) in cell_of for f in range(r["start"], r["end"] + 1))]
    out = dict(
        detection_recall=n_match / max(n_gt, 1), detection_precision=n_match / max(n_pred, 1),
        tracks_followed=followed, fragments_per_cell=fragments, id_switches=switches,
        predicted_tracks=int(res.cells.shape[0]), true_cells=int(gt["gt"].nunique()),
        rupture_recall=len(hits) / max(len(truth["ruptures"]), 1), rupture_precision=good / max(len(ev), 1),
        ruptures_true=len(truth["ruptures"]), ruptures_called=int(len(ev)),
        rupture_duration_error_frames=float(np.mean(np.abs(durations))) if durations else float("nan"))

    dead = res.cells[res.cells["fate"] == "death"]
    found, right = set(), 0
    for r in dead.itertuples():
        g = gt_of.get((r.cell, int(r.last_frame)))
        hit = next((k for k, d in enumerate(truth["deaths"]) if d["cell"] == g and abs(d["frame"] - 1 - r.last_frame) <= 5), None)
        if hit is not None:
            found.add(hit); right += 1
    out.update(death_recall=len(found) / max(len(truth["deaths"]), 1), death_precision=right / max(len(dead), 1),
               deaths_true=len(truth["deaths"]), deaths_called=int(len(dead)))
    div = res.divisions[res.divisions["confidence"] == "high"] if len(res.divisions) else res.divisions
    found, right = set(), 0
    for r in (div.dropna(subset=["mother"]).itertuples() if len(div) else []):
        g = next((gt_of[(int(r.mother), f)] for f in range(int(r.frame) - 8, int(r.frame)) if (int(r.mother), f) in gt_of), None)
        hit = next((k for k, d in enumerate(truth["divisions"]) if d["cell"] == g and abs(d["frame"] - r.frame) <= 5), None)
        if hit is not None:
            found.add(hit); right += 1
    out.update(division_recall=len(found) / max(len(truth["divisions"]), 1), division_precision=right / max(len(div), 1),
               divisions_true=len(truth["divisions"]), divisions_called=int(len(div)))
    return out


def run(n_cells=40, n_frames=120, size=900, seed=0, overrides=(), saturate=True, keep=None, quiet=True) -> dict:
    folder = keep or tempfile.mkdtemp(prefix="cs-bench-")
    os.makedirs(folder, exist_ok=True)
    movie = os.path.join(folder, f"sim_{n_cells}_{seed}.mp4")
    truth = simulate(movie, n_cells, n_frames, size, seed, saturate)
    cfg = Config()
    cfg.calibration.pixel_size_um, cfg.calibration.frame_interval_min = 0.625, 10.0
    for item in overrides:
        key, _, value = item.partition("=")
        cfg.set(key, yaml.safe_load(value))
    res = analyze(movie, cfg, os.path.join(folder, f"out_{n_cells}_{seed}"), log=(lambda *a: None) if quiet else print,
                  show_bars=False, reuse=False, keep_earlier=False, record=False)
    return score(res, truth)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", type=int, default=40)
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--unsaturated", action="store_true")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--keep")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = [run(a.cells, a.frames, a.size, s, a.set, not a.unsaturated, a.keep) for s in a.seeds]
    table = pd.DataFrame(rows, index=[f"seed {s}" for s in a.seeds])
    table.loc["mean"] = table.mean()
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    print(table.T.round(3).to_string())
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(table.loc["mean"].to_dict(), fh, indent=1)
