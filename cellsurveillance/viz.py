"""Annotated movies and image strips."""
from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .io import iter_frames
from .style import STATE_RGB

FONT_PATHS = ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf",
              "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_K3 = np.ones((3, 3), np.uint8)


def font(size: int) -> ImageFont.ImageFont:
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def boundaries(labels: np.ndarray, thick: bool = False) -> np.ndarray:
    lab = labels.astype(np.uint16)
    b = (lab > 0) & ((cv2.erode(lab, _K3) != lab) | (cv2.dilate(lab, _K3) != lab))
    if thick:
        b = cv2.dilate(b.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    return b


def nice_scale_bar(width_um: float) -> float:
    target = width_um / 5
    for v in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v >= target:
            return float(v)
    return 1000.0


def state_of(frames: pd.DataFrame) -> np.ndarray:
    dying = frames["terminal_loss"].to_numpy(bool) if "terminal_loss" in frames else np.zeros(len(frames), bool)
    return np.select([frames["ruptured"].to_numpy(), dying, frames["mitotic"].to_numpy(),
                      ~frames["detected"].to_numpy()],
                     ["ruptured", "death", "mitotic", "undetected"], default="intact")


def render_overlay(res, out_path: str, roi: Optional[tuple] = None, cells: Optional[set] = None,
                   scale: float = 1.0, fps: float = 6.0, show_ids: bool = True, show_trails: bool = True,
                   show_hud: bool = True, labels: Optional[np.ndarray] = None, progress=None,
                   frame_range: Optional[tuple] = None, all_frames: Optional[pd.DataFrame] = None) -> str:
    """Write an annotated movie. `roi` = (x0, y0, x1, y1) in pixels crops the output.

    `cells` are the cells that are counted in the caption. If `all_frames` is given, every cell in it is
    outlined, so that nuclei passing through a region are marked even though they are not counted in it.
    """
    meta, frames = res.meta, res.frames
    if labels is None:
        labels = res.labels
    if labels is None:
        from .pipeline import load_labels
        labels = load_labels(res.outdir)
    T, H, W = labels.shape
    x0, y0, x1, y1 = (0, 0, W, H) if roi is None else [int(v) for v in roi]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    out_w, out_h = int((x1 - x0) * scale) // 2 * 2, int((y1 - y0) * scale) // 2 * 2
    px, interval = meta["pixel_size"], meta["interval_min"]
    trail = res.cfg.output.trail_frames

    f = frames if cells is None else frames[frames["cell"].isin(cells)]
    f = f.assign(state=state_of(f)).sort_values(["cell", "frame"])
    counted = {t: (len(g), int(g["ruptured"].sum())) for t, g in f.groupby("frame")}
    if all_frames is not None:
        f = all_frames.assign(state=state_of(all_frames)).sort_values(["cell", "frame"])
    by_frame = {t: g for t, g in f.groupby("frame")}
    tracks = {c: (g["frame"].to_numpy(), g["x"].to_numpy(), g["y"].to_numpy()) for c, g in f.groupby("cell")}
    info = res.cells.set_index("cell")
    deaths = info[(info["fate"] == "death")]
    if cells is not None:
        deaths = deaths[deaths.index.isin(cells)]
    death_marks = [(int(r.last_frame) + 1, c) for c, r in deaths.iterrows()]
    births = {}
    if len(res.divisions):
        for d in res.divisions[res.divisions["confidence"] == "high"].itertuples():
            if pd.notna(d.daughter_a) and pd.notna(d.daughter_b):
                births[(int(d.daughter_a), int(d.daughter_b))] = int(d.frame)
    tc = res.timecourse.set_index("frame")
    rupture_starts = res.events[["cell", "start_frame"]] if len(res.events) else pd.DataFrame(columns=["cell", "start_frame"])
    if cells is not None and len(rupture_starts):
        rupture_starts = rupture_starts[rupture_starts["cell"].isin(cells)]
    cum_rupt = np.cumsum(np.bincount(rupture_starts["start_frame"].to_numpy(int), minlength=T)) if len(rupture_starts) else np.zeros(T, int)

    palette = np.zeros((6, 3), np.uint8)
    codes = {"intact": 1, "ruptured": 2, "mitotic": 3, "undetected": 4, "death": 5}
    for name, k in codes.items():
        palette[k] = STATE_RGB[name]
    # text is sized to the picture, so a small region is not buried under its own caption
    hud_px = int(np.clip(out_w / 34, 10, 22))
    f_id, f_hud, f_small = font(int(np.clip(out_w / 60, 9, 13))), font(hud_px), font(int(np.clip(out_w / 48, 9, 14)))

    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"avc1"), fps, (out_w, out_h))
    if not writer.isOpened():
        writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_w, out_h))
    lo, hi = frame_range if frame_range else (0, T)
    for t, bgr in enumerate(iter_frames(meta["path"], crop=tuple(meta["crop"]) if meta.get("crop") else None)):
        if t >= T or t >= hi:
            break
        if t < lo:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        g = by_frame.get(t)
        lab = labels[t]
        if g is not None:
            lut = np.zeros(int(lab.max()) + 1, np.uint8)
            det = g[g["detected"] & (g["label"] > 0)]
            lut[det["label"].to_numpy(int)] = det["state"].map(codes).to_numpy()
            edge = boundaries(lab, thick=scale >= 1)
            code = lut[lab]
            sel = edge & (code > 0)
            rgb[sel] = palette[code[sel]]
        rgb = rgb[y0:y1, x0:x1]
        if scale != 1.0:
            rgb = cv2.resize(rgb, (out_w, out_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        else:
            rgb = np.ascontiguousarray(rgb[:out_h, :out_w])

        def to_xy(x, y):
            return (x - x0) * scale, (y - y0) * scale

        if g is not None and show_trails:
            for r in g.itertuples():
                fr, xs, ys = tracks[r.cell]
                k1 = np.searchsorted(fr, t, side="right")
                k0 = max(np.searchsorted(fr, t - trail), 0)
                if k1 - k0 >= 2:
                    pts = np.stack(to_xy(xs[k0:k1], ys[k0:k1]), 1).round().astype(np.int32)
                    cv2.polylines(rgb, [pts], False, STATE_RGB[r.state], 1, cv2.LINE_AA)
        img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(img, "RGBA")
        if g is not None:
            r_px = meta["nuclear_radius_px"] * scale
            for r in g.itertuples():
                x, y = to_xy(r.x, r.y)
                if not (0 <= x < out_w and 0 <= y < out_h):
                    continue
                if r.state == "undetected":
                    draw.ellipse([x - r_px, y - r_px, x + r_px, y + r_px], outline=STATE_RGB["undetected"] + (200,))
                if r.state == "ruptured":
                    rr = r_px * 1.7
                    draw.ellipse([x - rr, y - rr, x + rr, y + rr], outline=STATE_RGB["ruptured"] + (230,), width=2)
                if show_ids:
                    draw.text((x + r_px * 0.9, y - r_px * 1.1), str(r.cell), font=f_id, fill=(255, 255, 255, 235),
                              stroke_width=2, stroke_fill=(0, 0, 0, 200))
            for (a, b), t0 in births.items():
                if t0 <= t < t0 + 8 and a in tracks and b in tracks:
                    pa = to_xy(np.interp(t, tracks[a][0], tracks[a][1]), np.interp(t, tracks[a][0], tracks[a][2]))
                    pb = to_xy(np.interp(t, tracks[b][0], tracks[b][1]), np.interp(t, tracks[b][0], tracks[b][2]))
                    draw.line([pa, pb], fill=STATE_RGB["mitotic"] + (230,), width=2)
        for t0, c in death_marks:
            if t0 <= t < t0 + 10 and c in tracks:
                x, y = to_xy(tracks[c][1][-1], tracks[c][2][-1])
                s = 9 * scale
                col = STATE_RGB["death"] + (240,)
                draw.line([x - s, y - s, x + s, y + s], fill=col, width=3)
                draw.line([x - s, y + s, x + s, y - s], fill=col, width=3)
        if show_hud:
            n_now, n_rup = counted.get(t, (0, 0))
            n_div = sum(1 for v in births.values() if v <= t)
            n_dead = sum(1 for v, _ in death_marks if v <= t)
            lines = [f"{t * interval / 60:5.1f} h   frame {t + 1}/{T}",
                     f"cells {n_now}   ruptured now {n_rup}",
                     f"ruptures {int(cum_rupt[t])}   divisions {n_div}   deaths {n_dead}"]
            pad, lh = int(8 * scale) + 4, f_hud.size + 5
            wbox = int(max(draw.textlength(s, font=f_hud) for s in lines)) + 2 * pad
            draw.rectangle([0, 0, wbox, lh * len(lines) + 2 * pad - 4], fill=(0, 0, 0, 150))
            for i, s in enumerate(lines):
                draw.text((pad, pad - 2 + i * lh), s, font=f_hud, fill=(255, 255, 255, 255))
            keys = [("intact", "intact"), ("ruptured", "ruptured"), ("mitotic", "dividing"), ("death", "death")]
            yk = out_h - (f_small.size + 8) - 6
            xk = 8
            total = sum(int(draw.textlength(n, font=f_small)) + 34 for _, n in keys)
            draw.rectangle([0, yk - 6, total + 12, out_h], fill=(0, 0, 0, 150))
            for key, name in keys:
                draw.rectangle([xk, yk + 3, xk + 14, yk + f_small.size - 1], fill=STATE_RGB[key] + (255,))
                draw.text((xk + 20, yk), name, font=f_small, fill=(255, 255, 255, 255))
                xk += int(draw.textlength(name, font=f_small)) + 34
            if roi is not None and meta["units"] == "um":
                bar_um = nice_scale_bar((x1 - x0) * px)
                bar_px = bar_um / px * scale
                xb, yb = out_w - 14 - bar_px, out_h - 18
                draw.rectangle([xb, yb, xb + bar_px, yb + 4], fill=(255, 255, 255, 255))
                label = f"{bar_um:g} µm"
                draw.text((xb + bar_px / 2 - draw.textlength(label, font=f_small) / 2, yb - f_small.size - 4), label,
                          font=f_small, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 200))
        writer.write(cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR))
        if progress:
            progress((t - lo + 1) / max(min(hi, T) - lo, 1))
    writer.release()
    return out_path


def cell_strip(signal: np.ndarray, labels: np.ndarray, rows: pd.DataFrame, frame_list, half: int = 48,
               tile: int = 96, interval: float = 1.0, gamma: float = 0.6) -> np.ndarray:
    """RGB image strip following one cell through `frame_list`."""
    T, H, W = signal.shape
    rows = rows.assign(state=state_of(rows)).set_index("frame")
    fx, xs, ys = rows.index.to_numpy(), rows["x"].to_numpy(), rows["y"].to_numpy()
    f_small = font(10)
    tiles = []
    for t in frame_list:
        canvas = np.zeros((tile, tile, 3), np.uint8)
        if 0 <= t < T:
            cx, cy = np.interp(t, fx, xs), np.interp(t, fx, ys)
            xa, ya = int(round(cx)) - half, int(round(cy)) - half
            sx0, sy0, sx1, sy1 = max(xa, 0), max(ya, 0), min(xa + 2 * half, W), min(ya + 2 * half, H)
            crop = np.zeros((2 * half, 2 * half), np.uint8)
            crop[sy0 - ya:sy1 - ya, sx0 - xa:sx1 - xa] = signal[t, sy0:sy1, sx0:sx1]
            g = (255 * (crop / 255.0) ** gamma).astype(np.uint8)
            rgb = np.stack([g, g, g], -1)
            if t in rows.index and rows.at[t, "detected"]:
                lab = np.zeros((2 * half, 2 * half), bool)
                lab[sy0 - ya:sy1 - ya, sx0 - xa:sx1 - xa] = labels[t, sy0:sy1, sx0:sx1] == int(rows.at[t, "label"])
                rgb[boundaries(lab.astype(np.uint16))] = STATE_RGB[rows.at[t, "state"]]
            canvas = cv2.resize(rgb, (tile, tile), interpolation=cv2.INTER_LINEAR)
            img = Image.fromarray(canvas)
            d = ImageDraw.Draw(img)
            state = rows.at[t, "state"] if t in rows.index else "undetected"
            d.text((3, 2), f"{t * interval / 60:.1f} h", font=f_small, fill=(255, 255, 255), stroke_width=1,
                   stroke_fill=(0, 0, 0))
            if state in ("ruptured", "mitotic", "death"):
                d.rectangle([0, tile - 4, tile, tile], fill=STATE_RGB[state])
            canvas = np.asarray(img)
        tiles.append(canvas)
        tiles.append(np.full((tile, 2, 3), 252, np.uint8))
    return np.hstack(tiles[:-1])
