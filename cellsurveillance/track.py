"""Tracking: frame-to-frame linking, gap closing, merges (occlusions) and splits."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

BIG = 1e12


@dataclass
class TrackParams:
    """Tracking parameters in pixel / frame units."""
    max_dist: float
    gap_dist: float
    split_dist: float
    max_gap: int
    area_weight: float
    min_frames: int
    max_occlusion: int = 40
    momentum: float = 0.5


def _area_penalty(a, b, w):
    return (1.0 + w * np.abs(np.log(np.maximum(a, 1) / np.maximum(b, 1)))) ** 2


def _lap(cost: np.ndarray, no_link_cost: float):
    """Assignment with the option of leaving rows/columns unlinked (Jaqaman et al. 2008)."""
    n, m = cost.shape
    full = np.full((n + m, n + m), BIG)
    full[:n, :m] = cost
    full[:n, m:][np.diag_indices(n)] = no_link_cost
    full[n:, :m][np.diag_indices(m)] = no_link_cost
    lower = cost.T.copy()
    lower[lower < BIG] = 1e-6
    full[n:, m:] = lower
    rows, cols = linear_sum_assignment(full)
    return [(r, c) for r, c in zip(rows, cols) if r < n and c < m and cost[r, c] < BIG]


def link_frames(det: pd.DataFrame, tp: TrackParams) -> np.ndarray:
    """Link detections in consecutive frames. Returns a segment id for every detection."""
    seg = np.full(len(det), -1, np.int64)
    frames = det["frame"].to_numpy()
    xy = det[["x", "y"]].to_numpy()
    area = det["area"].to_numpy()
    index_by_frame = {f: np.flatnonzero(frames == f) for f in np.unique(frames)}
    next_id = 0
    prev = np.array([], int)
    velocity = np.zeros_like(xy)            # smoothed displacement of the track each detection belongs to
    for f in range(int(frames.min()), int(frames.max()) + 1):
        cur = index_by_frame.get(f, np.array([], int))
        if len(prev) and len(cur):
            cost = np.full((len(prev), len(cur)), BIG)
            pairs = cKDTree(xy[prev]).query_ball_tree(cKDTree(xy[cur]), tp.max_dist)
            # a crawling cell keeps its heading for a while, which tells two nuclei apart after they cross
            expected = xy[prev] + tp.momentum * velocity[prev]
            for i, js in enumerate(pairs):
                if js:
                    js = np.asarray(js)
                    d2 = ((xy[cur[js]] - expected[i]) ** 2).sum(1)
                    cost[i, js] = d2 * _area_penalty(area[cur[js]], area[prev[i]], tp.area_weight)
            for i, j in _lap(cost, 0.5 * tp.max_dist ** 2 * 1.5):
                seg[cur[j]] = seg[prev[i]]
                velocity[cur[j]] = 0.5 * velocity[prev[i]] + 0.5 * (xy[cur[j]] - xy[prev[i]])
        new = cur[seg[cur] < 0]
        seg[new] = np.arange(next_id, next_id + len(new))
        next_id += len(new)
        prev = cur
    return seg


def _segment_table(det: pd.DataFrame, key: str) -> pd.DataFrame:
    d = det.sort_values([key, "frame"])
    g = d.groupby(key, sort=True)
    tab = g.agg(t0=("frame", "first"), t1=("frame", "last"), x0=("x", "first"), y0=("y", "first"),
                x1=("x", "last"), y1=("y", "last"), n=("frame", "size"),
                border0=("at_border", "first"), border1=("at_border", "last"))
    tab["a0"] = g["area"].apply(lambda s: s.iloc[:3].median())
    tab["a1"] = g["area"].apply(lambda s: s.iloc[-3:].median())
    tab["a_med"] = g["area"].median()
    return tab


def close_gaps(det: pd.DataFrame, seg: np.ndarray, tp: TrackParams) -> np.ndarray:
    """Join segments across short gaps. Returns a chain id for every detection."""
    tab = _segment_table(det.assign(seg=seg), "seg")
    ids = tab.index.to_numpy()
    ends = tab[["x1", "y1"]].to_numpy()
    starts = tab[["x0", "y0"]].to_numpy()
    t0, t1 = tab["t0"].to_numpy(), tab["t1"].to_numpy()
    a0, a1 = tab["a0"].to_numpy(), tab["a1"].to_numpy()

    tree = cKDTree(starts)
    cand = []
    for i, js in enumerate(tree.query_ball_point(ends, tp.gap_dist)):
        for j in js:
            gap = t0[j] - t1[i]
            if i == j or gap < 1 or gap > tp.max_gap + 1:
                continue
            ratio = a0[j] / max(a1[i], 1)
            d2 = ((starts[j] - ends[i]) ** 2).sum()
            if d2 > tp.max_dist ** 2 and not (0.5 <= ratio <= 2.0):
                continue      # long jumps are only accepted between nuclei of similar size
            cand.append((i, j, d2 * _area_penalty(a0[j], a1[i], tp.area_weight) * (1 + 0.15 * (gap - 1))))
    parent = {i: i for i in range(len(ids))}
    if cand:
        rows = sorted({c[0] for c in cand})
        cols = sorted({c[1] for c in cand})
        r_of = {r: k for k, r in enumerate(rows)}
        c_of = {c: k for k, c in enumerate(cols)}
        cost = np.full((len(rows), len(cols)), BIG)
        for i, j, c in cand:
            cost[r_of[i], c_of[j]] = c
        for r, c in _lap(cost, 0.5 * tp.gap_dist ** 2 * 1.5):
            parent[cols[c]] = rows[r]

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    chain_of_seg = {ids[i]: ids[root(i)] for i in range(len(ids))}
    return np.array([chain_of_seg[s] for s in seg])


class Chains:
    """Fast lookup of chain position / area by frame, with interpolation across gaps."""

    def __init__(self, det: pd.DataFrame, key: str = "track"):
        self.rows = {}
        d = det.sort_values([key, "frame"])
        for tid, g in d.groupby(key, sort=False):
            self.rows[tid] = (g["frame"].to_numpy(), g["x"].to_numpy(), g["y"].to_numpy(), g["area"].to_numpy())

    def span(self, tid):
        f = self.rows[tid][0]
        return int(f[0]), int(f[-1])

    def pos(self, tid, frame):
        f, x, y, _ = self.rows[tid]
        return np.array([np.interp(frame, f, x), np.interp(frame, f, y)])

    def area(self, tid, frame_lo, frame_hi):
        f, _, _, a = self.rows[tid]
        sel = (f >= frame_lo) & (f <= frame_hi)
        return float(np.median(a[sel])) if sel.any() else np.nan

    def detected(self, tid, frame):
        f = self.rows[tid][0]
        k = np.searchsorted(f, frame)
        return k < len(f) and f[k] == frame

    def last_gap_before(self, tid, frame, lookback):
        """Latest frame pair (a, b) with b - a > 1 and frame - lookback <= b <= frame."""
        f = self.rows[tid][0]
        k = np.flatnonzero((np.diff(f) > 1) & (f[1:] <= frame) & (f[1:] >= frame - lookback))
        if len(k) == 0:
            return None
        return int(f[k[-1]]), int(f[k[-1] + 1])


def find_merges_and_splits(det: pd.DataFrame, tp: TrackParams, n_frames: int):
    """Candidate merges (a track ends by fusing with a neighbour) and splits (a track starts next to another)."""
    chains = Chains(det)
    tab = _segment_table(det, "track")
    spans = {tid: chains.span(tid) for tid in tab.index}
    by_frame = {f: g[["track", "x", "y", "area"]].to_numpy() for f, g in det.groupby("frame")}

    merges, splits = [], []
    for tid, r in tab.iterrows():
        # --- merge: this track ends, a neighbour grows by about this track's area
        if r.t1 < n_frames - 1 and (r.t1 + 1) in by_frame:
            nxt = by_frame[r.t1 + 1]
            d = np.hypot(nxt[:, 1] - r.x1, nxt[:, 2] - r.y1)
            found = False
            for k in np.flatnonzero(d <= tp.split_dist):
                other = int(nxt[k, 0])
                if other == tid or spans[other][0] > r.t1:
                    continue
                found = found or _record_merge(merges, chains, tid, r, other, float(d[k]))
            if not found:
                # no neighbour grew, but one is touching: the nucleus has slid under it, or over it
                radius = np.sqrt(max(r.a1, r.a_med) / np.pi)      # a nucleus going under looks smaller than it is
                for k in np.argsort(d):
                    other = int(nxt[k, 0])
                    if other == tid or spans[other][0] > r.t1:
                        continue
                    if d[k] <= 1.15 * (radius + np.sqrt(nxt[k, 3] / np.pi)):
                        merges.append(dict(track=tid, into=other, frame=int(r.t1 + 1), dist=float(d[k]),
                                           area=float(r.a1), gain=0.0, kind="touching"))
                    break
        # --- split: this track starts next to an existing track
        if r.t0 > 0:
            best = None
            for other, (s0, s1) in spans.items():
                if other == tid or s0 >= r.t0 or s1 < r.t0 - 1:
                    continue
                d = float(np.hypot(*(chains.pos(other, r.t0 - 1) - np.array([r.x0, r.y0]))))
                if d <= tp.split_dist and (best is None or d < best[1]):
                    best = (other, d)
            if best is not None:
                splits.append(dict(track=tid, mother=best[0], frame=int(r.t0), dist=best[1]))
    return pd.DataFrame(merges), pd.DataFrame(splits), chains


def make_track_params(cfg, seg_params, movie) -> TrackParams:
    trk, px = cfg.tracking, seg_params.scale
    diameter = 2 * seg_params.radius
    max_dist = trk.max_link_distance_um / px if trk.max_link_distance_um else 1.2 * diameter
    split = trk.max_split_distance_um / px if trk.max_split_distance_um else 1.5 * diameter
    return TrackParams(max_dist=max_dist, gap_dist=trk.gap_distance_factor * max_dist, split_dist=split,
                       max_gap=trk.max_gap_frames, area_weight=trk.area_weight, min_frames=trk.min_track_frames)


def _record_merge(merges: list, chains: "Chains", tid, r, other: int, dist: float) -> bool:
    before = chains.area(other, r.t1 - 2, r.t1)
    after = chains.area(other, r.t1 + 1, r.t1 + 3)
    gain = after - before
    # a nucleus sliding under its neighbour adds to it for a frame or two, then is hidden
    jump = chains.area(other, r.t1 + 1, r.t1 + 1) - chains.area(other, r.t1, r.t1)
    if np.isfinite(jump) and 0.35 * r.a1 <= jump <= 1.6 * r.a1:
        gain = jump
    if np.isfinite(gain) and 0.35 * r.a1 <= gain <= 1.6 * r.a1:
        merges.append(dict(track=tid, into=other, frame=int(r.t1 + 1), dist=dist, area=float(r.a1),
                           gain=float(gain), kind="merged"))
        return True
    return False


def build_tracks(det: pd.DataFrame, tp: TrackParams, log=print) -> pd.DataFrame:
    """Assign a provisional `track` id to every detection (links + gap closing)."""
    det = det.copy()
    seg = link_frames(det, tp)
    det["track"] = close_gaps(det, seg, tp)
    stats = det.groupby("track").agg(n=("frame", "size"), strong=("strong", "sum"))
    keep = stats.index[(stats.n >= tp.min_frames) & (stats.strong >= min(3, tp.min_frames))]
    n_all = len(stats)
    det = det[det["track"].isin(keep)].copy()
    # consecutive ids ordered by first appearance
    order = det.groupby("track")["frame"].min().sort_values(kind="stable").index
    remap = {old: new for new, old in enumerate(order, start=1)}
    det["track"] = det["track"].map(remap)
    log(f"  {det['track'].nunique()} tracks kept ({n_all - len(keep)} short or faint tracks discarded)")
    return det
