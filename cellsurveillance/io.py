"""Movie loading and reporter-signal extraction."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, Optional

import cv2
import numpy as np

from .config import Config

VIDEO_EXT = {".mov", ".mp4", ".avi", ".m4v", ".mkv", ".wmv"}
TIFF_EXT = {".tif", ".tiff"}
CHANNEL_INDEX = {"blue": 0, "green": 1, "red": 2}   # OpenCV frames are BGR


@dataclass
class Movie:
    path: str
    signal: np.ndarray            # (T, H, W) uint8 reporter signal
    exclude: np.ndarray           # (H, W) bool, static burned-in overlays
    channel: str
    composite: bool
    pixel_size_um: float
    units: str                    # "um" or "px"
    frame_interval_min: Optional[float]
    scale_bar_px: Optional[int]
    saturated: bool
    crop: Optional[tuple]

    @property
    def n_frames(self) -> int:
        return self.signal.shape[0]

    @property
    def shape(self) -> tuple:
        return self.signal.shape[1:]

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]


def iter_frames(path: str, max_frames: Optional[int] = None, crop=None) -> Iterator[np.ndarray]:
    """Yield BGR uint8 frames from a video or TIFF."""
    ext = os.path.splitext(path)[1].lower()
    if ext in TIFF_EXT:
        yield from _iter_tiff(path, max_frames, crop)
        return
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {path}")
    n = 0
    while max_frames is None or n < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if crop is not None:
            x0, y0, x1, y1 = crop
            frame = frame[y0:y1, x0:x1]
        yield frame
        n += 1
    cap.release()


def _iter_tiff(path, max_frames, crop):
    import tifffile
    arr = tifffile.imread(path)
    if arr.ndim == 2:
        arr = arr[None]
    if arr.ndim == 4 and arr.shape[1] <= 4 and arr.shape[-1] > 4:   # (T, C, H, W) -> (T, H, W, C)
        arr = np.moveaxis(arr, 1, -1)
    if arr.dtype != np.uint8:
        lo, hi = np.percentile(arr[:: max(1, len(arr) // 10)], [0.1, 99.99])
        arr = np.clip((arr.astype(np.float32) - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    for frame in arr[:max_frames]:
        if frame.ndim == 2:
            frame = np.repeat(frame[..., None], 3, axis=2)
        elif frame.shape[-1] < 3:
            frame = np.concatenate([frame] + [frame[..., :1]] * (3 - frame.shape[-1]), axis=2)
        else:
            frame = frame[..., 2::-1]      # RGB -> BGR
        if crop is not None:
            x0, y0, x1, y1 = crop
            frame = frame[y0:y1, x0:x1]
        yield np.ascontiguousarray(frame)


def _choose_channel(sample: np.ndarray) -> tuple[str, bool]:
    """Pick the reporter channel and detect transmitted-light composites."""
    s = sample.astype(np.float32)
    spread = (s.max(axis=-1) - s.min(axis=-1)).mean()
    if spread < 2.0:
        return "gray", False
    excess = {}
    for name, idx in CHANNEL_INDEX.items():
        others = [i for i in range(3) if i != idx]
        excess[name] = np.clip(s[..., idx] - s[..., others].mean(axis=-1), 0, None).mean()
    channel = max(excess, key=excess.get)
    others = [i for i in range(3) if i != CHANNEL_INDEX[channel]]
    composite = float(np.median(s[..., others].mean(axis=-1))) > 15.0
    return channel, composite


def extract_signal(frame: np.ndarray, channel: str, composite: bool, mask_overlays: bool = True) -> np.ndarray:
    """Reporter signal (uint8) from one BGR frame."""
    if channel == "gray":
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    idx = CHANNEL_INDEX[channel]
    others = [i for i in range(3) if i != idx]
    if composite:
        base = (frame[..., others[0]].astype(np.int16) + frame[..., others[1]]) // 2
        return np.clip(frame[..., idx].astype(np.int16) - base, 0, 255).astype(np.uint8)
    sig = frame[..., idx].copy()
    if mask_overlays:
        sig[overlay_mask(frame)] = 0
    return sig


def _white_level(frame: np.ndarray) -> float:
    """Darkest channel value that still counts as a white or grey annotation.

    A single-colour reporter leaks little into the other channels, so anything
    bright in all three is an annotation. Transmitted light raises the floor.
    """
    floor = float(np.median(frame.min(axis=-1)))
    return max(100.0, floor + 80.0)


def _neutral_bright(frame: np.ndarray) -> np.ndarray:
    """Pixels that are bright and colourless: annotations, never a single-colour reporter."""
    lo, hi = frame.min(axis=-1), frame.max(axis=-1)
    return (lo > _white_level(frame)) & (hi - lo < 50)


def overlay_mask(frame: np.ndarray) -> np.ndarray:
    """White burned-in annotations (text, scale bar)."""
    white = _neutral_bright(frame)
    if not white.any():
        return white
    # text and scale bars are made of strokes; isolated pixels are compression noise
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 12
    return cv2.dilate(keep[lab].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0


def find_scale_bar(frame: np.ndarray) -> Optional[tuple]:
    """Bounding box (x, y, width, height) of what looks like a horizontal scale bar, if there is one.

    This is only a suggestion: the user has to confirm it and say what length it represents.
    """
    white = _neutral_bright(frame).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    best = None
    for i in range(1, n):
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if w >= 20 and h <= 12 and w / max(h, 1) >= 8 and stats[i, cv2.CC_STAT_AREA] >= 0.8 * w * h:
            if best is None or w > best[2]:
                best = (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]), int(w), int(h))
    return best


def detect_scale_bar(frame: np.ndarray) -> Optional[int]:
    """Length in pixels of the candidate scale bar."""
    bar = find_scale_bar(frame)
    return bar[2] if bar else None


def load_movie(path: str, cfg: Config, log=print) -> Movie:
    crop = tuple(cfg.input.crop) if cfg.input.crop else None
    frames = iter_frames(path, cfg.input.max_frames, crop)
    first = next(frames)

    channel, composite = cfg.input.channel, cfg.input.composite
    auto_channel, auto_composite = _choose_channel(first)
    if channel == "auto":
        channel = auto_channel
    if composite == "auto":
        composite = auto_composite if channel != "gray" else False
    else:
        composite = str(composite).lower() in ("yes", "true", "1")

    scale_bar_px = detect_scale_bar(first)
    cal = cfg.calibration
    units = "um"
    if cal.pixel_size_um:
        pixel_size = float(cal.pixel_size_um)
    elif cal.scale_bar_um and scale_bar_px:
        pixel_size = float(cal.scale_bar_um) / scale_bar_px
    else:
        pixel_size, units = 1.0, "px"
        log("  WARNING: no pixel size given; distances are reported in pixels.")

    signal, static = [], None
    for frame in _chain(first, frames):
        signal.append(extract_signal(frame, channel, composite, cfg.input.mask_overlays))
        if cfg.input.mask_overlays:
            m = overlay_mask(frame)
            static = m.astype(np.uint16) if static is None else static + m
    signal = np.stack(signal)
    if static is None:
        exclude = np.zeros(signal.shape[1:], bool)
    else:
        exclude = static >= 0.9 * len(signal)

    bright = signal[:: max(1, len(signal) // 8)]
    fg = bright[bright > np.percentile(bright, 97)]
    ceiling = int(bright.max())
    saturated = bool((fg >= ceiling - 3).mean() > 0.3) if fg.size else False

    log(f"  {len(signal)} frames, {signal.shape[2]}x{signal.shape[1]} px, channel={channel}, "
        f"composite={composite}, saturated={saturated}, pixel={pixel_size:.4g} {units}/px"
        + (f", scale bar={scale_bar_px} px" if scale_bar_px else ""))
    return Movie(path=path, signal=signal, exclude=exclude, channel=channel, composite=composite,
                 pixel_size_um=pixel_size, units=units, frame_interval_min=float(cal.frame_interval_min) if cal.frame_interval_min else None,
                 scale_bar_px=scale_bar_px, saturated=saturated, crop=crop)


def _chain(first, rest):
    yield first
    yield from rest


def find_movies(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    out = []
    for name in sorted(os.listdir(path)):
        if name.startswith("."):
            continue
        if os.path.splitext(name)[1].lower() in VIDEO_EXT | TIFF_EXT:
            out.append(os.path.join(path, name))
    return out
