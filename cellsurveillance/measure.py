"""Reference measurements.

The cytoplasm/nucleus ratio is only meaningful when it is measured against the
real nuclear outline. When the nucleus is not detected (gap) or its mask is
abnormal (for example the whole cell is flooded with reporter and segmented as
one object), the outline from the nearest normal frame is placed at the
expected position and the intensities are measured there.
"""
from __future__ import annotations

import warnings

import cv2
import numpy as np
import pandas as pd

from .io import Movie
from .segment import SegParams, _disk, background_level

REF_COLS = ("nuc_ref", "cyto_ref", "cn_ref")
MAX_RATIO = 1.1


def _running_median(values: np.ndarray, window: int = 41) -> np.ndarray:
    # the window must be much longer than a rupture or a mitosis, or the event itself becomes the reference
    return pd.Series(values).rolling(window, center=True, min_periods=1).median().to_numpy()


class ReferenceMeter:
    def __init__(self, movie: Movie, labels: np.ndarray, p: SegParams):
        self.movie, self.labels, self.p = movie, labels, p
        self._bg = {}
        self.margin = p.ring_gap + p.ring_width + 2
        self.k_in, self.k_out = _disk(p.ring_gap), _disk(p.ring_gap + p.ring_width)

    def background(self, t: int) -> float:
        if t not in self._bg:
            self._bg[t] = background_level(self.movie.signal[t])[0]
        return self._bg[t]

    def mask_of(self, row) -> tuple[np.ndarray, float, float]:
        """Mask of a detection and its centroid relative to the mask's corner."""
        y0, x0, y1, x1 = int(row.y0), int(row.x0), int(row.y1), int(row.x1)
        mask = self.labels[int(row.frame), y0:y1, x0:x1] == int(row.label)
        return mask, row.y - y0, row.x - x0

    def measure(self, t: int, mask: np.ndarray, cy: float, cx: float, y: float, x: float, own_label: int = 0,
                search: int = 0) -> dict:
        """Place `mask` with its centroid (cy, cx) near (y, x) in frame t and measure.

        With `search` > 0 the outline is moved by up to that many pixels to where
        it covers the most reporter, which follows a nucleus that moved unevenly.
        """
        H, W = self.movie.shape
        m = self.margin + search
        top, left = int(round(y - cy)) - m, int(round(x - cx)) - m
        h, w = mask.shape[0] + 2 * m, mask.shape[1] + 2 * m
        ys, xs = max(top, 0), max(left, 0)
        ye, xe = min(top + h, H), min(left + w, W)
        out = dict.fromkeys(REF_COLS, np.nan)
        out["dx"] = out["dy"] = 0.0
        if ye - ys < 3 or xe - xs < 3:
            return out
        # region of the frame, zero-padded where it falls outside the image
        img = np.zeros((h, w), np.float32)
        valid = np.zeros((h, w), bool)
        others = np.zeros((h, w), bool)
        sl = (slice(ys - top, ye - top), slice(xs - left, xe - left))
        img[sl] = self.movie.signal[t, ys:ye, xs:xe].astype(np.float32) - self.background(t)
        lab = self.labels[t, ys:ye, xs:xe]
        others[sl] = cv2.dilate(((lab > 0) & (lab != own_label)).astype(np.uint8), self.k_in) > 0
        valid[sl] = ~self.movie.exclude[ys:ye, xs:xe]
        valid &= ~others

        dy = dx = 0
        if search > 0 and mask.any():
            tmpl = mask.astype(np.float32)
            inner = (slice(self.margin, h - self.margin), slice(self.margin, w - self.margin))
            score = cv2.matchTemplate(np.where(valid, img, 0)[inner], tmpl, cv2.TM_CCORR) / max(tmpl.sum(), 1)
            gy, gx = np.mgrid[-search:search + 1, -search:search + 1]
            score = score - 12.0 * np.hypot(gy, gx) / search
            k = np.unravel_index(np.argmax(score), score.shape)
            dy, dx = int(gy[k]), int(gx[k])
        padded = np.zeros((h, w), np.uint8)
        padded[m + dy:m + dy + mask.shape[0], m + dx:m + dx + mask.shape[1]] = mask
        placed = padded > 0
        nuc = placed & valid
        ring = (cv2.dilate(padded, self.k_out) > 0) & ~(cv2.dilate(padded, self.k_in) > 0) & valid
        out["dx"], out["dy"] = float(dx), float(dy)
        if nuc.sum() >= max(5, 0.6 * placed.sum()):
            out["nuc_ref"] = float(img[nuc].mean())
        if ring.sum() >= 10:
            # with the cell's own mask abnormal, a touching neighbour can sit in the ring: the median ignores it
            q = 50.0 if own_label else self.p.ring_percentile
            out["cyto_ref"] = float(np.percentile(img[ring], q))
        if np.isfinite(out["nuc_ref"]) and np.isfinite(out["cyto_ref"]):
            out["cn_ref"] = max(out["cyto_ref"], 0.0) / max(out["nuc_ref"], 1.0)
        return out


def _probe(meter: "ReferenceMeter", t: int, mask: np.ndarray, cy: float, cx: float, y: float, x: float):
    """What is at a position in frame t: mean reporter signal, and how much of it belongs to any nucleus."""
    H, W = meter.movie.shape
    top, left = int(round(y - cy)), int(round(x - cx))
    ys, xs = max(top, 0), max(left, 0)
    ye, xe = min(top + mask.shape[0], H), min(left + mask.shape[1], W)
    if ye - ys < 2 or xe - xs < 2:
        return np.nan, np.nan
    m = mask[ys - top:ye - top, xs - left:xe - left]
    if m.sum() < 5:
        return np.nan, np.nan
    img = meter.movie.signal[t, ys:ye, xs:xe].astype(np.float32) - meter.background(t)
    occupied = meter.labels[t, ys:ye, xs:xe] > 0
    return float(img[m].mean()), float(occupied[m].mean())


def add_reference_measurements(det: pd.DataFrame, labels: np.ndarray, movie: Movie, p: SegParams,
                               probe_frames: int = 4, log=print):
    """Fill gaps and re-measure abnormal frames.

    Returns (frames, probes): `frames` has one row per track per frame from the
    first to the last detection; `probes` holds the signal left at the last
    position in the frames after each track ends.
    """
    meter = ReferenceMeter(movie, labels, p)
    search = max(int(round(0.8 * p.radius)), 2)
    T = movie.n_frames
    out_rows, probes = [], []
    n_gap = n_abnormal = 0
    det = det.sort_values(["track", "frame"])
    for tid, g in det.groupby("track", sort=False):
        g = g.reset_index(drop=True)
        f = g["frame"].to_numpy()
        area = g["area"].to_numpy(float)
        med = _running_median(area)
        abnormal = (area > 1.5 * med) | (area < 0.5 * med)
        if abnormal.all():
            abnormal[:] = False
        normal = np.flatnonzero(~abnormal)
        fn = f[normal]
        g["detected"] = True
        g["abnormal_mask"] = abnormal
        g["area_ref"] = med
        g["nuc_ref"], g["cyto_ref"], g["cn_ref"] = g["nuc_mean"], g["cyto"], g["cn_ratio"]
        detections = g

        def reference_for(t):
            k = np.searchsorted(fn, t, side="right") - 1      # previous normal frame
            if k < 0 or (k + 1 < len(fn) and fn[k + 1] - t < t - fn[k] and t - fn[k] > 10):
                k = min(k + 1, len(fn) - 1)
            return meter.mask_of(detections.iloc[normal[k]])

        xs_n, ys_n = g["x"].to_numpy()[normal], g["y"].to_numpy()[normal]
        # abnormal frames: keep the detection, re-measure against the reference outline
        for i in np.flatnonzero(abnormal):
            t = int(f[i])
            mask, cy, cx = reference_for(t)
            x, y = np.interp(t, fn, xs_n), np.interp(t, fn, ys_n)
            m = meter.measure(t, mask, cy, cx, y, x, own_label=int(g.at[i, "label"]), search=search)
            for c in REF_COLS:
                g.at[i, c] = m[c]
            n_abnormal += 1
        # gap frames
        missing = np.setdiff1d(np.arange(f[0], f[-1] + 1), f)
        rows = []
        for t in missing:
            mask, cy, cx = reference_for(t)
            x, y = np.interp(t, f, detections["x"].to_numpy()), np.interp(t, f, detections["y"].to_numpy())
            m = meter.measure(int(t), mask, cy, cx, y, x, search=search)
            rows.append(dict(track=tid, frame=int(t), x=x + m["dx"], y=y + m["dy"], detected=False,
                             abnormal_mask=False, area_ref=float(np.interp(t, f, med)), label=0, strong=False,
                             at_border=False, **{c: m[c] for c in REF_COLS}))
            n_gap += 1
        if rows:
            g = pd.concat([g, pd.DataFrame(rows)], ignore_index=True).sort_values("frame")
        out_rows.append(g)
        # what is left at the last position after the track ends
        if f[-1] < T - 1:
            last = detections.iloc[-1]
            mask, cy, cx = reference_for(int(f[-1]))
            vals = [_probe(meter, t, mask, cy, cx, last.y, last.x) for t in range(int(f[-1]) + 1,
                                                                        min(int(f[-1]) + 1 + probe_frames, T))]
            before = g["nuc_ref"].dropna().iloc[-3:].median()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                post_nuc = float(np.nanmedian([v[0] for v in vals]))
                occupied = float(np.nanmedian([v[1] for v in vals]))
            probes.append(dict(track=tid, post_nuc=post_nuc, post_occupied=occupied, pre_nuc=float(before)))
    frames = pd.concat(out_rows, ignore_index=True)
    # no reporter where the nucleus should be: the ratio is meaningless there
    typical = frames.groupby("track")["nuc_ref"].transform("median")
    frames["signal_absent"] = frames["nuc_ref"] < np.maximum(p.low_threshold, 0.2 * typical)
    # cytoplasm brighter than the nucleus is not a rupture: the outline is no longer on the nucleus
    frames["reference_lost"] = frames["cn_ref"] > MAX_RATIO
    frames.loc[frames["signal_absent"] | frames["reference_lost"] | frames["nuc_ref"].isna(), "cn_ref"] = np.nan
    frames["detected"] = frames["detected"].astype(bool)
    frames["abnormal_mask"] = frames["abnormal_mask"].astype(bool)
    log(f"  reference outline used for {n_gap} undetected and {n_abnormal} abnormal frames")
    return frames, pd.DataFrame(probes, columns=["track", "post_nuc", "post_occupied", "pre_nuc"])
