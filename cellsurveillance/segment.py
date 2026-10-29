"""Nucleus segmentation and per-frame measurements for an NLS reporter.

The NLS reporter marks the nucleus and leaks into the cytoplasm on rupture, so a
nucleus is defined as a compact region that is bright relative to its own
surroundings, not by one global threshold. Fragments of a lobulated or
micronucleated nucleus are grouped into one object.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage.measure import regionprops_table
from skimage.morphology import h_maxima
from skimage.segmentation import expand_labels, watershed

from .config import Config
from .io import Movie


ASSUMED_DIAMETER_UM = 18.0


@dataclass
class SegParams:
    """Segmentation parameters in pixel units."""
    sigma: float
    radius: float            # typical nuclear radius
    low_threshold: float
    rel_threshold: float
    min_contrast: float
    weak_contrast: float     # relaxed criteria: enough to continue a track, not to start one
    weak_area: float
    bright_min: float        # peak intensity above background that a nucleus must reach
    scale: float             # um per pixel used to scale parameters
    min_area: float
    max_area: float
    min_frag_area: float
    group_radius: int
    assoc_dist: float
    ring_gap: int
    ring_width: int
    ring_percentile: float
    border: int
    split: bool
    split_min_radius: float
    split_h: float


def _disk(r: int) -> np.ndarray:
    r = max(int(round(r)), 1)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def background_level(img: np.ndarray) -> tuple[float, float]:
    """Mode of the dark pixels and the noise around it."""
    hist = np.bincount(img.ravel(), minlength=256).astype(float)
    cutoff = int(np.searchsorted(np.cumsum(hist), 0.6 * img.size)) + 1
    hist = ndi.uniform_filter1d(hist, 3)
    bg = int(np.argmax(hist[:cutoff]))
    dark = img[img <= bg + 12].astype(np.float32)
    below = dark[dark <= bg]
    sigma = float(np.sqrt(np.mean((below - bg) ** 2))) if below.size > 10 else 1.0
    upper = dark[dark >= bg]
    if upper.size > 10:
        sigma = max(sigma, float(np.sqrt(np.mean((upper - bg) ** 2))) * 0.6)
    return float(bg), max(sigma, 1.0)


def estimate_radius(movie: Movie) -> float:
    """Typical nuclear radius (px) from compact bright objects in a few frames."""
    radii = []
    for t in np.linspace(0, movie.n_frames - 1, min(6, movie.n_frames)).astype(int):
        img = cv2.GaussianBlur(movie.signal[t], (0, 0), 1.5)
        bg, _ = background_level(movie.signal[t])
        top = np.percentile(img, 99.5)
        mask = (img > bg + 0.6 * (top - bg)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            if area >= 30 and area / (w * h) > 0.6 and 0.4 < w / h < 2.5:
                radii.append(np.sqrt(area / np.pi))
    if not radii:
        return 12.0
    return float(np.median(radii))


def make_params(movie: Movie, cfg: Config, log=print) -> SegParams:
    seg = cfg.segmentation
    if movie.units == "um":
        px = movie.pixel_size_um
        radius = seg.nuclear_diameter_um / px / 2 if seg.nuclear_diameter_um else estimate_radius(movie)
    else:
        # no calibration: scale the parameters by assuming a typical nucleus
        radius = estimate_radius(movie)
        px = (seg.nuclear_diameter_um or ASSUMED_DIAMETER_UM) / (2 * radius)
    bright = movie.signal[:: max(1, movie.n_frames // 8)]
    bg, sigma = background_level(bright[0])
    top = float(np.percentile(bright, 99.5))
    low = seg.low_threshold if seg.low_threshold is not None else max(6 * sigma, 0.12 * (top - bg))
    rel = seg.rel_threshold if seg.rel_threshold is not None else (0.8 if movie.saturated else 0.5)
    typical_area = np.pi * radius ** 2
    if seg.min_nucleus_area_um2 is not None:
        min_area = seg.min_nucleus_area_um2 / px ** 2
    else:
        min_area = 0.25 * typical_area
    p = SegParams(
        sigma=max(seg.smooth_sigma_um / px, 0.5),
        radius=radius,
        low_threshold=float(low),
        rel_threshold=float(rel),
        min_contrast=seg.min_contrast,
        weak_contrast=1.0 + 0.4 * (seg.min_contrast - 1.0),
        weak_area=0.6 * min_area,
        bright_min=seg.min_brightness * (top - bg),
        scale=px,
        min_area=min_area,
        max_area=seg.max_nucleus_area_um2 / px ** 2,
        min_frag_area=max(seg.min_fragment_area_um2 / px ** 2, 4),
        group_radius=max(int(round(seg.group_radius_um / px)), 1),
        assoc_dist=seg.micronucleus_assoc_um / px,
        ring_gap=max(int(round(seg.ring_gap_um / px)), 1),
        ring_width=max(int(round(seg.ring_width_um / px)), 2),
        ring_percentile=seg.ring_percentile,
        border=max(int(round(seg.border_margin_um / px)), 2),
        split=seg.split_touching,
        split_min_radius=seg.split_min_radius_frac * radius,
        split_h=max(seg.split_h_frac * radius, 1.0),
    )
    log(f"  nuclear diameter ~{2 * radius * movie.pixel_size_um:.1f} {movie.units} ({2 * radius:.0f} px), "
        f"low threshold={p.low_threshold:.0f}, relative threshold={p.rel_threshold:.2f}")
    return p


def nuclear_mask(img: np.ndarray, p: SegParams, exclude: np.ndarray):
    """Binary mask of nuclear material, plus smoothed image and background."""
    bg, sigma = background_level(img)
    smooth = cv2.GaussianBlur(img, (0, 0), p.sigma).astype(np.float32) - bg
    local_max = cv2.dilate(smooth, _disk(p.radius))
    mask = (smooth > p.low_threshold) & (smooth >= p.rel_threshold * local_max) & ~exclude
    mask = ndi.binary_fill_holes(mask)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= p.min_frag_area
    return keep[lab], smooth, bg, sigma


def group_and_split(mask: np.ndarray, p: SegParams) -> np.ndarray:
    """Label image in which each nucleus (with all its fragments) has one label."""
    grouped = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, _disk(p.group_radius))
    n, regions = cv2.connectedComponents(grouped, connectivity=8)
    if p.split and n > 1:
        dist = cv2.distanceTransform(grouped, cv2.DIST_L2, 5)
        dist_s = cv2.GaussianBlur(dist, (0, 0), max(p.radius * 0.15, 1.0))
        peaks = h_maxima(dist_s, p.split_h) > 0
        peaks &= dist_s >= p.split_min_radius
        seeds, n_seeds = ndi.label(peaks, structure=np.ones((3, 3)))
        if n_seeds:
            seed_region = regions[peaks]
            seeds_per_region = np.bincount(np.unique(np.stack([seed_region, seeds[peaks]], 1), axis=0)[:, 0],
                                           minlength=n)
            multi = seeds_per_region >= 2
            if multi.any():
                to_split = multi[regions]
                markers = np.where(to_split, seeds, 0)
                split = watershed(-dist_s, markers, mask=to_split)
                regions = np.where(to_split, split + n, regions)
    labels = np.where(mask, regions, 0)
    # relabel consecutively
    uniq, inv = np.unique(labels, return_inverse=True)
    return inv.reshape(labels.shape).astype(np.int32)


PROPS = ("label", "area", "centroid", "bbox", "perimeter", "eccentricity", "major_axis_length",
         "minor_axis_length", "orientation", "solidity", "mean_intensity", "max_intensity")


def _grouped_percentiles(labels: np.ndarray, values: np.ndarray, n_labels: int, q) -> np.ndarray:
    """Percentiles of `values` for each label 1..n_labels; NaN where a label has no pixels."""
    out = np.full((n_labels + 1, len(q)), np.nan, np.float32)
    if labels.size == 0:
        return out
    order = np.argsort(labels, kind="stable")
    labels, values = labels[order], values[order]
    bounds = np.flatnonzero(np.diff(labels)) + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [labels.size]])
    for s, e in zip(starts, ends):
        out[labels[s]] = np.percentile(values[s:e], q)
    return out


def _relabel(labels: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Keep the listed labels and renumber them 1..k."""
    lut = np.zeros(int(labels.max()) + 1, np.int32)
    lut[keep] = np.arange(1, len(keep) + 1)
    return lut[labels]


def _cytoplasm_lobes(labels, ids, ok, peak, area, p: SegParams) -> np.ndarray:
    """Objects that are part of a flooded cell body rather than a nucleus.

    When a nucleus ruptures the cytoplasm can become bright enough to be segmented
    in its own right, as lobes on either side of the nucleus. A lobe is dimmer
    than the nucleus it lies next to and is not a compact shape; a nucleus that
    is merely dim is still compact, and a lobulated nucleus is still bright.
    """
    from scipy.spatial import cKDTree
    t = regionprops_table(labels, properties=("label", "centroid", "inertia_tensor_eigvals"))
    lam = np.sqrt(np.clip(t["inertia_tensor_eigvals-0"] * t["inertia_tensor_eigvals-1"], 1e-6, None))
    fill = area / (4 * np.pi * lam)                       # 1 for an ellipse, lower for a crescent or a star
    xy = np.stack([t["centroid-1"], t["centroid-0"]], 1)
    lobe = np.zeros(len(ids), bool)
    tree = cKDTree(xy)
    for i in np.flatnonzero(ok & (fill < 0.86)):
        near = [j for j in tree.query_ball_point(xy[i], 3.4 * p.radius) if j != i and ok[j]]
        if near and peak[i] < 0.88 * max(peak[j] for j in near):
            lobe[i] = True
    return lobe


def segment_frame(img: np.ndarray, p: SegParams, exclude: np.ndarray) -> np.ndarray:
    """Label image of candidate nuclei (strong and weak) in one frame."""
    mask, smooth, bg, _ = nuclear_mask(img, p, exclude)
    labels = group_and_split(mask, p)
    n = int(labels.max())
    if n == 0:
        return labels.astype(np.uint16)
    area = np.bincount(labels.ravel(), minlength=n + 1)
    # contrast against the immediate surroundings rejects cytoplasmic plateaus
    lab16 = labels.astype(np.uint16)
    inner = cv2.dilate(lab16, _disk(p.ring_gap))
    outer = cv2.dilate(lab16, _disk(p.ring_gap + p.ring_width))
    ring = (outer > 0) & (inner == 0) & ~exclude
    raw = img.astype(np.float32) - bg
    ids = np.arange(1, n + 1)
    nuc = ndi.mean(raw, labels, ids)
    cyto = _grouped_percentiles(outer[ring].astype(np.int64), raw[ring], n, (50.0,))[1:, 0]
    contrast = nuc / np.clip(np.nan_to_num(cyto, nan=0.0), 1.0, None)
    # bright cytoplasm has an edge of its own and would pass for a nucleus; it never reaches nuclear brightness
    inside = labels > 0
    peak = _grouped_percentiles(labels[inside].astype(np.int64), smooth[inside], n, (90.0,))[1:, 0]
    ok = ((area[1:] >= p.weak_area) & (area[1:] <= p.max_area) & (contrast >= p.weak_contrast)
          & (peak >= 0.6 * p.bright_min))
    if ok.sum() > 1:
        ok &= ~_cytoplasm_lobes(labels, ids, ok, peak, area[1:], p)
    return _relabel(labels, ids[ok]).astype(np.uint16)


def resolve_merges(prev: np.ndarray, cur: np.ndarray, p: SegParams) -> tuple[np.ndarray, int]:
    """Split objects in `cur` that cover two or more separate nuclei of the previous frame.

    Only used forwards in time, so a dividing nucleus is never split retroactively.
    """
    both = (prev > 0) & (cur > 0)
    if not both.any():
        return cur, 0
    n_prev, n_cur = int(prev.max()), int(cur.max())
    pair, overlap = np.unique(prev[both].astype(np.int64) * (n_cur + 1) + cur[both], return_counts=True)
    pl, cl = pair // (n_cur + 1), pair % (n_cur + 1)
    prev_area = np.bincount(prev.ravel(), minlength=n_prev + 1)
    cur_area = np.bincount(cur.ravel(), minlength=n_cur + 1)
    claims = overlap >= 0.4 * prev_area[pl]
    out = cur.copy()
    next_label = n_cur + 1
    n_split = 0
    for c in np.unique(cl[claims]):
        owners = pl[claims & (cl == c)]
        if len(owners) < 2:
            continue
        total = prev_area[owners].sum()
        if not (0.7 * total <= cur_area[c] <= 1.5 * total):
            continue
        ys, xs = np.nonzero(cur == c)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        obj = cur[y0:y1, x0:x1] == c
        before = prev[y0:y1, x0:x1]
        markers = np.zeros(obj.shape, np.int32)
        for k, o in enumerate(owners, start=1):
            m = ((before == o) & obj).astype(np.uint8)
            core = cv2.erode(m, _disk(2))
            markers[(core if core.any() else m) > 0] = k
        closed = cv2.morphologyEx(obj.astype(np.uint8), cv2.MORPH_CLOSE, _disk(p.group_radius))
        dist = cv2.distanceTransform(closed, cv2.DIST_L2, 5)
        parts = watershed(-dist, markers, mask=closed > 0)
        parts = np.where(obj, parts, 0)
        sizes = np.bincount(parts.ravel(), minlength=len(owners) + 1)[1:]
        if (sizes < p.weak_area).any():
            continue
        sub = out[y0:y1, x0:x1]
        for k in range(2, len(owners) + 1):
            sub[parts == k] = next_label
            next_label += 1
        n_split += 1
    return out, n_split


def measure_labels(img: np.ndarray, labels: np.ndarray, frame: int, p: SegParams, exclude: np.ndarray) -> pd.DataFrame:
    """Morphology and intensity of every nucleus in a label image."""
    labels = labels.astype(np.int32)
    n = int(labels.max())
    if n == 0:
        return pd.DataFrame()
    mask, smooth, bg, sigma = nuclear_mask(img, p, exclude)
    raw = img.astype(np.float32) - bg
    props = pd.DataFrame(regionprops_table(labels, intensity_image=raw, properties=PROPS))
    props = props.rename(columns={
        "centroid-0": "y", "centroid-1": "x", "bbox-0": "y0", "bbox-1": "x0", "bbox-2": "y1", "bbox-3": "x1",
        "mean_intensity": "nuc_mean", "max_intensity": "nuc_max", "major_axis_length": "major_axis",
        "minor_axis_length": "minor_axis"})
    idx = props["label"].to_numpy()

    # cytoplasm ring; small bright bodies are kept out of it
    bodies = mask & (labels == 0)
    inner = expand_labels(labels, p.ring_gap)
    outer = expand_labels(labels, p.ring_gap + p.ring_width)
    ring = (outer > 0) & (inner == 0) & ~exclude & ~bodies
    ring_stats = _grouped_percentiles(outer[ring], raw[ring], n, (50.0, p.ring_percentile, 90.0))
    props["cyto_median"] = ring_stats[idx, 0]
    props["cyto"] = ring_stats[idx, 1]
    props["cyto_p90"] = ring_stats[idx, 2]
    props["ring_px"] = np.bincount(outer[ring], minlength=n + 1)[idx]
    occupied = ring & (smooth > max(3 * sigma, 0.4 * p.low_threshold))
    props["ring_occupied"] = np.bincount(outer[occupied], minlength=n + 1)[idx] / props["ring_px"].clip(lower=1)
    props["contrast"] = props["nuc_mean"] / props["cyto_median"].fillna(0).clip(lower=1.0)
    inside = labels > 0
    peak = _grouped_percentiles(labels[inside].astype(np.int64), smooth[inside], n, (90.0,))
    props["nuc_peak"] = peak[idx, 0]
    props["strong"] = ((props["area"] >= p.min_area) & (props["contrast"] >= p.min_contrast)
                       & (props["nuc_peak"] >= p.bright_min))

    # fragments per nucleus
    _, cc = cv2.connectedComponents((labels > 0).astype(np.uint8), connectivity=8)
    inside = labels > 0
    pairs = np.unique(np.stack([labels[inside], cc[inside]], 1), axis=0)
    props["n_fragments"] = np.bincount(pairs[:, 0], minlength=n + 1)[idx]

    # small bright bodies next to a nucleus are counted as its micronuclei
    props["n_micronuclei"] = 0
    props["micronuclei_area"] = 0.0
    n_b, b_lab, b_stats, b_cent = cv2.connectedComponentsWithStats(bodies.astype(np.uint8), connectivity=8)
    if n_b > 1:
        b_area = b_stats[1:, cv2.CC_STAT_AREA]
        ok = (b_area >= p.min_frag_area) & (b_area < p.weak_area)
        if ok.any():
            dist, (iy, ix) = ndi.distance_transform_edt(labels == 0, return_indices=True)
            cy = b_cent[1:, 1][ok].round().astype(int)
            cx = b_cent[1:, 0][ok].round().astype(int)
            near = dist[cy, cx] <= p.assoc_dist
            owner = labels[iy[cy, cx], ix[cy, cx]][near]
            row_of = pd.Series(props.index, index=props["label"])
            counts = pd.Series(owner).value_counts()
            areas = pd.Series(b_area[ok][near].astype(float)).groupby(owner).sum()
            props.loc[row_of[counts.index].to_numpy(), "n_micronuclei"] = counts.to_numpy()
            props.loc[row_of[areas.index].to_numpy(), "micronuclei_area"] = areas.to_numpy()

    h, w = img.shape
    props["at_border"] = ((props["y0"] <= p.border) | (props["x0"] <= p.border) |
                          (props["y1"] >= h - p.border) | (props["x1"] >= w - p.border))
    props["circularity"] = (4 * np.pi * props["area"] / props["perimeter"].clip(lower=1) ** 2).clip(upper=1.0)
    props["aspect_ratio"] = props["major_axis"] / props["minor_axis"].clip(lower=1)
    sat_level = float(img.max()) - bg - 3
    props["nuc_saturated_frac"] = ndi.mean(raw >= sat_level, labels, idx)
    props["cn_ratio"] = props["cyto"].clip(lower=0) / props["nuc_mean"].clip(lower=1.0)
    props["background"] = bg
    props["frame"] = frame
    return props


def measure_at(img: np.ndarray, mask: np.ndarray, others: np.ndarray, p: SegParams, exclude: np.ndarray) -> dict:
    """Intensities for a reference nuclear outline placed on a frame."""
    bg, _ = background_level(img)
    raw = img.astype(np.float32) - bg
    m = mask.astype(np.uint8)
    ring = ((cv2.dilate(m, _disk(p.ring_gap + p.ring_width)) > 0) & ~(cv2.dilate(m, _disk(p.ring_gap)) > 0)
            & ~others & ~exclude)
    nuc = raw[mask]
    out = {"nuc_mean": float(nuc.mean()) if nuc.size else np.nan, "background": bg}
    if ring.sum() >= 10:
        out["cyto_median"], out["cyto"], out["cyto_p90"] = (float(v) for v in
                                                           np.percentile(raw[ring], (50.0, p.ring_percentile, 90.0)))
    else:
        out["cyto_median"] = out["cyto"] = out["cyto_p90"] = np.nan
    out["cn_ratio"] = max(out["cyto"], 0) / max(out["nuc_mean"], 1.0) if np.isfinite(out["cyto"]) else np.nan
    return out


def _segment_one(args):
    img, p, exclude = args
    return segment_frame(img, p, exclude)


def _measure_one(args):
    img, labels, t, p, exclude = args
    return measure_labels(img, labels, t, p, exclude)


def _pool_map(fn, jobs, n, n_jobs, desc, progress, on_step=None):
    from tqdm import tqdm

    def consume(results):
        if progress:
            results = tqdm(results, total=n, desc=desc, unit="frame", leave=False)
        out = []
        for r in results:
            out.append(r)
            if on_step:
                on_step(len(out) / n)
        return out

    jobs = list(jobs)
    if n_jobs > 1 and n > 8:
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool
        try:
            import os
            from .lifecycle import worker_start          # workers stop if this process is killed
            with ProcessPoolExecutor(n_jobs, initializer=worker_start, initargs=(os.getpid(),)) as pool:
                return consume(pool.map(fn, jobs, chunksize=2))
        except (BrokenProcessPool, OSError, RuntimeError):
            pass          # worker processes cannot start here (a notebook, a piped script): use this process
    return consume(fn(j) for j in jobs)


def segment_movie(movie: Movie, p: SegParams, log=print, progress=True, n_jobs: int = 0, on_step=None):
    """Segment and measure every frame. Returns (label stack, detections DataFrame)."""
    import os
    T = movie.n_frames
    n_jobs = n_jobs or max(1, min(8, (os.cpu_count() or 2) - 2))
    jobs = ((movie.signal[t], p, movie.exclude) for t in range(T))
    step = (lambda f: on_step(0.6 * f)) if on_step else None
    label_stack = np.stack(_pool_map(_segment_one, jobs, T, n_jobs, "  segmenting", progress, step))

    n_split = 0
    for t in range(1, T):
        label_stack[t], k = resolve_merges(label_stack[t - 1], label_stack[t], p)
        n_split += k

    jobs = ((movie.signal[t], label_stack[t], t, p, movie.exclude) for t in range(T))
    step = (lambda f: on_step(0.6 + 0.4 * f)) if on_step else None
    rows = [r for r in _pool_map(_measure_one, jobs, T, n_jobs, "  measuring", progress, step) if len(r)]
    det = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    log(f"  {len(det)} nuclei detected ({len(det) / max(T, 1):.0f} per frame), "
        f"{n_split} touching nuclei separated using the previous frame")
    return label_stack, det
