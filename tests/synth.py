"""Synthetic NLS-reporter movies with known events, for testing."""
from __future__ import annotations

import cv2
import numpy as np
import tifffile


def _ellipse(img, x, y, a, b, angle, value):
    cv2.ellipse(img, (int(round(x)), int(round(y))), (int(round(a)), int(round(b))), angle, 0, 360, float(value), -1,
                cv2.LINE_AA)


def make_movie(path: str, n_frames: int = 60, size: int = 320, seed: int = 3) -> dict:
    """Write a movie and return the ground truth.

    Six cells drift slowly. Cell 0 ruptures twice, cell 1 once, cell 2 divides,
    cell 3 dies, cells 4 and 5 do nothing.
    """
    rng = np.random.default_rng(seed)
    starts = np.array([[70, 70], [230, 80], [90, 230], [240, 230], [160, 150], [160, 40]], float)
    vel = rng.normal(0, 0.35, (6, 2))
    ruptures = {0: [(12, 16), (35, 37)], 1: [(25, 30)]}
    division = dict(cell=2, nebd=28, reform=31)
    death = dict(cell=3, start=38, gone=42)
    frames = np.zeros((n_frames, size, size), np.float32)
    for t in range(n_frames):
        cyto = np.zeros((size, size), np.float32)
        nuc = np.zeros((size, size), np.float32)
        for c in range(6):
            x, y = starts[c] + vel[c] * t + 2.0 * np.sin(t / 9 + c)
            level, nuc_level, nuc_scale, draw_nuc = 22.0, 230.0, 1.0, True
            if any(a <= t <= b for a, b in ruptures.get(c, [])):
                level, nuc_level = 95.0, 180.0
            if c == division["cell"]:
                if division["nebd"] <= t < division["reform"]:
                    level, draw_nuc = 80.0, False
                elif t >= division["reform"]:
                    sep = 9 + 1.2 * (t - division["reform"])
                    _ellipse(cyto, x - sep, y, 22, 17, 0, level)
                    _ellipse(cyto, x + sep, y, 22, 17, 0, level)
                    _ellipse(nuc, x - sep, y, 9, 8, 0, nuc_level)
                    _ellipse(nuc, x + sep, y, 9, 8, 0, nuc_level)
                    continue
            if c == death["cell"]:
                if t >= death["gone"]:
                    continue
                if t >= death["start"]:
                    nuc_scale = 1.0 - 0.18 * (t - death["start"] + 1)
            _ellipse(cyto, x, y, 30, 20, 20 * c, level)
            if draw_nuc:
                _ellipse(nuc, x, y, 14 * nuc_scale, 11 * nuc_scale, 20 * c, nuc_level)
        img = np.maximum(cyto, nuc)
        img = cv2.GaussianBlur(img, (0, 0), 1.2) + rng.normal(3, 1.5, img.shape)
        frames[t] = img
    g = np.clip(frames, 0, 255).astype(np.uint8)
    rgb = np.zeros(g.shape + (3,), np.uint8)
    rgb[..., 1] = g
    tifffile.imwrite(path, rgb, photometric="rgb")
    return dict(n_cells=6, ruptures=ruptures, division=division, death=death, n_frames=n_frames)
