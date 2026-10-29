"""Command line interface.

    cell-surveillance app
    cell-surveillance analyze  MOVIE --interval-min 15 --scale-bar-um 100
    cell-surveillance analyze  FOLDER --calibration calibration.csv
    cell-surveillance calibration-template FOLDER
    cell-surveillance recalibrate RESULTS_FOLDER --interval-min 15
    cell-surveillance recall   RESULTS_FOLDER --rupture-threshold 0.2
    cell-surveillance roi      RESULTS_FOLDER --roi 200,200,800,700

The time between frames and the scale are never assumed. They are taken from
the command line (one movie), from a calibration file (several movies), or
asked for movie by movie.
"""
from __future__ import annotations

import argparse
import copy
import csv
import os
import subprocess
import sys
from typing import Optional

import yaml

from . import __version__
from .config import Analysis, Config
from .io import find_movies, find_scale_bar, iter_frames, load_movie
from .pipeline import CalibrationError, analyze, load_results, recalibrate, recall
from .rupture import MODES

MEASUREMENTS = [f for f in Analysis.__dataclass_fields__]
APP_PORT = 8531
APP_FLAGS = ["--server.address", "localhost", "--browser.gatherUsageStats", "false", "--server.maxUploadSize", "4000"]
CALIBRATION_COLUMNS = ["movie", "frames", "width_px", "height_px", "scale_bar_found_px", "interval_min",
                       "scale_bar_um", "pixel_size_um"]


def default_outdir(movie: str) -> str:
    name = os.path.splitext(os.path.basename(movie))[0]
    return os.path.join(os.path.dirname(os.path.abspath(movie)), "Cell Surveillance results", name)


def write_outputs(res, cfg: Config, video: bool, pdf: bool, signal=None, log=print) -> None:
    from .report import write_pdf
    from .viz import render_overlay
    if signal is None and (pdf or video):
        signal = res.signal if res.signal is not None else load_movie(res.meta["path"], cfg, log=lambda *a: None).signal
    if pdf:
        write_pdf(res, os.path.join(res.outdir, "report.pdf"), signal=signal)
        log("  wrote report.pdf")
    if video:
        render_overlay(res, os.path.join(res.outdir, "annotated_movie.mp4"), scale=cfg.output.overlay_scale)
        log("  wrote annotated_movie.mp4")


# ----------------------------------------------------------------------------- calibration
def movie_facts(movie: str) -> dict:
    import cv2
    first = next(iter_frames(movie, max_frames=1))
    cap = cv2.VideoCapture(movie)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
    cap.release()
    return dict(frames=n, width=first.shape[1], height=first.shape[0], bar=find_scale_bar(first))


def write_calibration_template(folder: str, path: Optional[str] = None) -> str:
    """A table of the movies in `folder` for the user to fill in."""
    movies = find_movies(folder)
    if not movies:
        raise SystemExit(f"No movies found in {folder}")
    path = path or os.path.join(folder if os.path.isdir(folder) else os.path.dirname(folder), "calibration.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CALIBRATION_COLUMNS)
        for movie in movies:
            f = movie_facts(movie)
            w.writerow([os.path.basename(movie), f["frames"], f["width"], f["height"], f["bar"][2] if f["bar"] else "",
                        "", "", ""])
    return path


def read_calibration(path: str) -> dict:
    """{movie file name: {interval_min, scale_bar_um, pixel_size_um}} from a filled-in template."""
    out = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            def number(key):
                text = (row.get(key) or "").strip()
                return float(text) if text else None
            out[os.path.basename(row["movie"].strip())] = dict(
                interval_min=number("interval_min"), scale_bar_um=number("scale_bar_um"),
                pixel_size_um=number("pixel_size_um"))
    return out


def _ask(prompt: str, allow_blank: bool = False) -> Optional[float]:
    while True:
        text = input(prompt).strip()
        if not text and allow_blank:
            return None
        try:
            value = float(text)
            if value > 0:
                return value
        except ValueError:
            pass
        print("    Please enter a number greater than zero.")


def calibrate(movie: str, base: Config, given: dict, interactive: bool) -> Config:
    """Settings for one movie with the calibration the user gave for it."""
    cfg = copy.deepcopy(base)
    cal = cfg.calibration
    cal.frame_interval_min = cal.pixel_size_um = cal.scale_bar_um = None
    cal.interval_confirmed = cal.size_confirmed = False
    name = os.path.basename(movie)
    facts = movie_facts(movie)
    bar = facts["bar"]

    interval = given.get("interval_min")
    if interval is None and interactive:
        print(f"\n{name}: {facts['frames']} frames, {facts['width']}x{facts['height']} px")
        interval = _ask("    Minutes between frames: ")
    if interval is None:
        raise CalibrationError(
            f"{name}: the time between frames was not given. Pass --interval-min for a single movie, or fill in a "
            "calibration file for a folder (see 'cell-surveillance calibration-template').")
    cal.frame_interval_min, cal.interval_confirmed = float(interval), True

    pixel, bar_um = given.get("pixel_size_um"), given.get("scale_bar_um")
    if pixel is None and bar_um is None and interactive and not given.get("uncalibrated"):
        if bar:
            print(f"    A bar {bar[2]} px long was found at x={bar[0]}, y={bar[1]}. If that is the scale bar, enter "
                  "the length it represents.")
            bar_um = _ask("    Scale bar length in micrometres (Enter if this is not the scale bar): ", allow_blank=True)
        if bar_um is None:
            pixel = _ask("    Micrometres per pixel (Enter to report sizes in pixels): ", allow_blank=True)
    if bar_um is not None:
        if not bar:
            raise CalibrationError(f"{name}: a scale bar length was given but no scale bar was found in the movie. "
                                   "Give the pixel size instead.")
        cal.scale_bar_um, cal.size_confirmed = float(bar_um), True
        print(f"  {name}: scale bar {bar[2]} px = {bar_um:g} um, so {bar_um / bar[2]:.4g} um/px")
    elif pixel is not None:
        cal.pixel_size_um, cal.size_confirmed = float(pixel), True
    else:
        print(f"  {name}: no scale given; sizes and distances will be in pixels")
    return cfg


# ----------------------------------------------------------------------------- arguments
def _build_config(args) -> Config:
    cfg = Config.load(args.config)
    if args.channel:
        cfg.input.channel = args.channel
    if args.rupture_mode:
        cfg.rupture.mode = args.rupture_mode
    if args.rupture_threshold is not None:
        cfg.rupture.threshold = args.rupture_threshold
    if args.measure:
        chosen = {m.strip() for m in args.measure.split(",")}
        unknown = chosen - set(MEASUREMENTS)
        if unknown:
            raise SystemExit(f"Unknown measurement(s): {', '.join(sorted(unknown))}. Choose from {', '.join(MEASUREMENTS)}.")
        for m in MEASUREMENTS:
            setattr(cfg.analysis, m, m in chosen)
    if args.crop:
        cfg.input.crop = [int(v) for v in args.crop.split(",")]
    for item in args.set or []:
        key, _, value = item.partition("=")
        cfg.set(key, yaml.safe_load(value))
    cfg.output.overlay_video = not args.no_video
    cfg.output.pdf_report = not args.no_pdf
    return cfg


def _emit(stage: str, fraction: float) -> None:
    """Machine-readable progress for the app."""
    print(f"@@PROGRESS {fraction:.4f} {stage}", flush=True)


def _roi(text: str) -> tuple:
    parts = [int(float(v)) for v in text.split(",")]
    if len(parts) != 4:
        raise SystemExit("--roi needs four numbers: x0,y0,x1,y1 (pixels)")
    return tuple(parts)


def _add_calibration_arguments(p) -> None:
    p.add_argument("--interval-min", type=float, help="minutes between frames in this movie")
    p.add_argument("--scale-bar-um", type=float, help="length that the scale bar in the movie represents")
    p.add_argument("--pixel-size", type=float, help="micrometres per pixel")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cell-surveillance", description=f"Cell Surveillance {__version__}: "
                                 "track single cells and measure nuclear rupture, movement, division and death.")
    sub = ap.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="analyse a movie, or every movie in a folder")
    a.add_argument("input")
    a.add_argument("-o", "--out", help="results folder (default: 'Cell Surveillance results' next to the movie)")
    a.add_argument("--config", help="YAML settings file")
    _add_calibration_arguments(a)
    a.add_argument("--calibration", help="filled-in calibration.csv with one row per movie")
    a.add_argument("--same-for-all", action="store_true",
                   help="use --interval-min and the scale for every movie in the folder")
    a.add_argument("--uncalibrated", action="store_true", help="report sizes in pixels without asking for a scale")
    a.add_argument("--channel", choices=["auto", "red", "green", "blue", "gray"])
    a.add_argument("--rupture-mode", choices=list(MODES))
    a.add_argument("--rupture-threshold", type=float, help="what counts as a rupture (default: automatic)")
    a.add_argument("--measure", help=f"comma-separated list from: {', '.join(MEASUREMENTS)} (default: all)")
    a.add_argument("--crop", help="analyse only this part of the image: x0,y0,x1,y1")
    a.add_argument("--roi", help="also export this region separately: x0,y0,x1,y1")
    a.add_argument("--set", action="append", metavar="SECTION.OPTION=VALUE", help="any other setting")
    a.add_argument("--no-video", action="store_true")
    a.add_argument("--no-pdf", action="store_true")
    a.add_argument("--fresh", action="store_true", help="do not reuse a previous segmentation")
    a.add_argument("--progress", action="store_true", help=argparse.SUPPRESS)

    t = sub.add_parser("calibration-template", help="write calibration.csv listing the movies in a folder, to fill in")
    t.add_argument("folder")
    t.add_argument("-o", "--out")

    c = sub.add_parser("recalibrate", help="apply the real frame interval or scale to finished results (no re-tracking)")
    c.add_argument("results")
    _add_calibration_arguments(c)
    c.add_argument("--no-video", action="store_true")
    c.add_argument("--no-pdf", action="store_true")

    r = sub.add_parser("recall", help="re-call ruptures with a new threshold (fast, no re-tracking)")
    r.add_argument("results")
    r.add_argument("--rupture-threshold", type=float)
    r.add_argument("--rupture-mode", choices=list(MODES))
    r.add_argument("--no-video", action="store_true")
    r.add_argument("--no-pdf", action="store_true")

    e = sub.add_parser("roi", help="export the movie and the measurements for one region")
    e.add_argument("results")
    e.add_argument("--roi", required=True, help="x0,y0,x1,y1 in pixels")
    e.add_argument("--name", default=None)
    e.add_argument("--membership", default="inside_most",
                   choices=["inside_most", "inside_any", "inside_start", "inside_always"])
    e.add_argument("--no-video", action="store_true")
    e.add_argument("--no-pdf", action="store_true")

    p = sub.add_parser("app", help="open the Cell Surveillance app in your browser")
    p.add_argument("--port", type=int, default=APP_PORT)
    p.add_argument("--headless", action="store_true", help="do not open the browser")
    args = ap.parse_args(argv)

    if args.command == "app":
        here = os.path.dirname(os.path.abspath(__file__))
        # Streamlit runs inside this process, so that stopping the app really stops it, and so that the
        # watchers that make it quit when its window is closed are running before any browser connects.
        from streamlit.web import cli as streamlit_cli
        from . import lifecycle, theme
        lifecycle.start()
        # Streamlit's own widgets take the user's light or dark choice from the start, so the page never flashes the other look
        sys.argv = ["streamlit", "run", os.path.join(here, "app.py"), "--server.port", str(args.port),
                    "--server.headless", "true" if args.headless else "false"] + APP_FLAGS + theme.streamlit_flags(theme.current())
        return streamlit_cli.main()

    if args.command == "calibration-template":
        path = write_calibration_template(args.folder, args.out)
        print(f"Wrote {path}\nFill in interval_min for every movie, and either scale_bar_um (only if the bar found "
              "is really the scale bar) or pixel_size_um. Then run:\n"
              f'  cell-surveillance analyze "{args.folder}" --calibration "{path}"')
        return 0

    if args.command == "analyze":
        cfg = _build_config(args)
        movies = find_movies(args.input)
        if not movies:
            raise SystemExit(f"No movies found in {args.input}")
        table = read_calibration(args.calibration) if args.calibration else {}
        from_args = dict(interval_min=args.interval_min, scale_bar_um=args.scale_bar_um, pixel_size_um=args.pixel_size)
        if len(movies) > 1 and not args.same_for_all and any(v is not None for v in from_args.values()):
            raise SystemExit("The frame interval and scale differ between movies, so values on the command line are "
                             "only applied to a whole folder with --same-for-all. Otherwise use --calibration "
                             "(see 'cell-surveillance calibration-template') or leave them out to be asked.")
        interactive = sys.stdin.isatty() and not args.progress
        if args.progress:                                   # started by the app: never outlive it
            from .lifecycle import APP_ENV, die_with_parent
            die_with_parent(int(os.environ.get(APP_ENV, "0") or 0))
        failed = []
        for movie in movies:
            given = dict(table.get(os.path.basename(movie), {}))
            for key, value in from_args.items():
                if value is not None:
                    given[key] = value
            given["uncalibrated"] = args.uncalibrated
            try:
                movie_cfg = calibrate(movie, cfg, given, interactive)
            except CalibrationError as err:
                print(f"SKIPPED {err}")
                failed.append(movie)
                continue
            out = args.out if args.out and len(movies) == 1 else (
                os.path.join(args.out, os.path.splitext(os.path.basename(movie))[0]) if args.out else default_outdir(movie))
            report = _emit if args.progress else (lambda *_: None)
            res = analyze(movie, movie_cfg, out, reuse=not args.fresh, show_bars=not args.progress,
                          progress=lambda stage, f: report(stage, 0.85 * f))
            report("Writing report and movie", 0.87)
            write_outputs(res, movie_cfg, movie_cfg.output.overlay_video, movie_cfg.output.pdf_report, signal=res.signal)
            report("Done", 1.0)
            if args.roi:
                from .roi import export_roi
                roi = _roi(args.roi)
                export_roi(res, roi, os.path.join(out, "region_" + "_".join(map(str, roi))),
                           video=movie_cfg.output.overlay_video, pdf=movie_cfg.output.pdf_report, signal=res.signal)
        return 1 if failed else 0

    if args.command == "recalibrate":
        if args.interval_min is None and args.scale_bar_um is None and args.pixel_size is None:
            raise SystemExit("Give --interval-min, --scale-bar-um or --pixel-size.")
        res = recalibrate(args.results, interval_min=args.interval_min, pixel_size_um=args.pixel_size,
                          scale_bar_um=args.scale_bar_um)
        write_outputs(res, res.cfg, not args.no_video, not args.no_pdf)
        return 0

    if args.command == "recall":
        res = recall(args.results, threshold=args.rupture_threshold, mode=args.rupture_mode)
        res.labels = None
        write_outputs(res, res.cfg, not args.no_video, not args.no_pdf)
        print(res.summary.to_string(index=False))
        return 0

    if args.command == "roi":
        from .roi import export_roi
        res = load_results(args.results, with_labels=True)
        roi = _roi(args.roi)
        name = args.name or "region_" + "_".join(map(str, roi))
        signal = load_movie(res.meta["path"], res.cfg, log=lambda *a: None).signal if not args.no_pdf else None
        export_roi(res, roi, os.path.join(args.results, name), membership=args.membership,
                   video=not args.no_video, pdf=not args.no_pdf, signal=signal)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
