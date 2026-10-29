"""A record of every analysis, so earlier results can be found and reopened."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from typing import Optional

HOME = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Cell Surveillance")
REGISTRY = os.path.join(HOME, "history.json")
INTERNAL = "analysis_data"
EARLIER = "earlier runs"
RESULTS = "Cell Surveillance results"
KEEP_IN_PLACE = {"labels.npz", "detections.pkl"}       # the segmentation is reused by the next run


def _read() -> list:
    try:
        with open(REGISTRY) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _write(entries: list) -> None:
    os.makedirs(HOME, exist_ok=True)
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(entries, fh, indent=1)
    os.replace(tmp, REGISTRY)


def locate_movie(outdir: str, meta: dict) -> str:
    """Where the movie is now.

    Results are written to '<movie folder>/Cell Surveillance results/<name>'. When that folder is moved
    together with its movies, the path recorded at analysis time no longer exists; the movie is then
    looked for next to the results folder.
    """
    path = meta.get("path", "")
    if path and os.path.exists(path):
        return path
    parts = os.path.abspath(outdir).split(os.sep)
    if RESULTS in parts and meta.get("movie"):
        moved = os.path.join(os.sep.join(parts[:len(parts) - 1 - parts[::-1].index(RESULTS)]) or os.sep, meta["movie"])
        if os.path.exists(moved):
            return moved
    return path


def describe(outdir: str) -> Optional[dict]:
    """What the history shows for one results folder, read from the folder itself."""
    meta_path = os.path.join(outdir, INTERNAL, "meta.json")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as fh:
        meta = json.load(fh)
    folder = os.path.basename(os.path.abspath(outdir))
    stem = os.path.splitext(meta.get("movie", ""))[0]
    entry = dict(outdir=os.path.abspath(outdir), movie=meta.get("movie", ""), path=locate_movie(outdir, meta),
                 title=meta.get("movie", "") if folder == stem or EARLIER in os.path.abspath(outdir) else folder,
                 region=meta.get("crop"),
                 analysed_at=dt.datetime.fromtimestamp(os.path.getmtime(meta_path)).isoformat(timespec="seconds"),
                 n_frames=meta.get("n_frames"), interval_min=meta.get("interval_min"),
                 pixel_size=meta.get("pixel_size"), units=meta.get("units"),
                 interval_confirmed=bool(meta.get("interval_confirmed")), size_confirmed=bool(meta.get("size_confirmed")),
                 rupture_threshold=meta.get("rupture_threshold"), rupture_mode=meta.get("rupture_mode"),
                 earlier_run=EARLIER in os.path.abspath(outdir).split(os.sep))
    summary = os.path.join(outdir, "population_summary.csv")
    if os.path.exists(summary):
        import csv
        with open(summary, newline="") as fh:
            rows = {r["measurement"]: r["value"] for r in csv.DictReader(fh)}
        for key, name in (("cells", "Cells tracked"), ("ruptures", "Ruptures"), ("divisions", "Divisions"),
                          ("deaths", "Deaths")):
            try:
                entry[key] = int(float(rows[name]))
            except (KeyError, ValueError):
                entry[key] = None
    return entry


def register(outdir: str) -> None:
    entry = describe(outdir)
    if entry is None:
        return
    entries = [e for e in _read() if e.get("outdir") != entry["outdir"]]
    entries.append(entry)
    _write(entries)


def forget(outdir: str) -> None:
    """Remove from the list. The files are not touched."""
    _write([e for e in _read() if e.get("outdir") != os.path.abspath(outdir)])


def entries() -> list:
    """Every recorded analysis whose folder still exists, newest first, refreshed from disk."""
    out, changed = [], False
    for e in _read():
        fresh = describe(e.get("outdir", ""))
        if fresh is None:
            changed = True
            continue
        out.append(fresh)
    if changed:
        _write(out)
    return sorted(out, key=lambda e: e["analysed_at"], reverse=True)


def archive(outdir: str) -> Optional[str]:
    """Move a finished analysis aside before the movie is analysed again. Returns the new folder."""
    meta_path = os.path.join(outdir, INTERNAL, "meta.json")
    if not os.path.exists(meta_path):
        return None
    stamp = dt.datetime.fromtimestamp(os.path.getmtime(meta_path)).strftime("%Y-%m-%d %H.%M.%S")
    dest = os.path.join(outdir, EARLIER, stamp)
    if os.path.exists(dest):
        return None
    os.makedirs(os.path.join(dest, INTERNAL))
    for name in os.listdir(outdir):
        if name in (INTERNAL, EARLIER) or name.startswith("."):
            continue
        shutil.move(os.path.join(outdir, name), os.path.join(dest, name))
    for name in os.listdir(os.path.join(outdir, INTERNAL)):
        src = os.path.join(outdir, INTERNAL, name)
        if name == "detections.pkl":
            continue
        if name in KEEP_IN_PLACE:
            shutil.copy2(src, os.path.join(dest, INTERNAL, name))
        else:
            shutil.move(src, os.path.join(dest, INTERNAL, name))
    forget(outdir)
    register(dest)
    return dest


def save_thumbnail(outdir: str, first_frame_bgr) -> None:
    import cv2
    h, w = first_frame_bgr.shape[:2]
    scale = 360 / max(w, 1)
    small = cv2.resize(first_frame_bgr, (360, max(int(h * scale), 1)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(os.path.join(outdir, INTERNAL, "thumbnail.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 85])


PREFERENCES = os.path.join(HOME, "preferences.json")


def preferences() -> dict:
    """Small choices that should survive closing the app, such as whether the background is animated."""
    try:
        with open(PREFERENCES) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def set_preference(key: str, value) -> None:
    prefs = preferences()
    prefs[key] = value
    os.makedirs(HOME, exist_ok=True)
    tmp = PREFERENCES + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(prefs, fh, indent=1)
    os.replace(tmp, PREFERENCES)
