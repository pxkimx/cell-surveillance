"""Build the website demo: a small region of one movie, analysed from start to finish.

    python3 scripts/make_demo.py --interval-min 15 --scale-bar-um 100      # with the real calibration
    python3 scripts/make_demo.py --draft                                   # placeholder calibration, marked unconfirmed

Writes a complete results folder for the region, then copies what the website
needs (card screenshot, report pages, demo movie) into the site repository.
Nothing is committed or published by this script.

The card screenshot step starts headless Google Chrome, which shows a Chrome icon
in the Dock while it runs. The 0.3.0 card was made without it, from pictures taken
in the Claude browser pane and stitched together; see _website-export-0.3.0/NOTES.md.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from cellsurveillance.cli import write_outputs  # noqa: E402
from cellsurveillance.config import Config  # noqa: E402
from cellsurveillance.io import find_scale_bar, iter_frames  # noqa: E402
from cellsurveillance.pipeline import analyze  # noqa: E402

MOVIES = os.path.join(HERE, "NM rupture")          # the example movies were moved into the tool folder on 2026-09-29
MOVIE = os.path.join(MOVIES, "Prog2 (Converted).mov")
REGION = (440, 80, 920, 560)                      # x0, y0, x1, y1 in pixels
OUT = os.path.join(MOVIES, "Cell Surveillance results", "Demo region (Prog2)")
SITE = os.environ.get("CS_SITE_REPO", os.path.expanduser("~/Documents/GitHub/paul-h-kim-site"))   # the website repository
PORT = 8771                                       # test port registered on the team board


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval-min", type=float)
    ap.add_argument("--scale-bar-um", type=float)
    ap.add_argument("--draft", action="store_true", help="use placeholder calibration and mark it unconfirmed")
    ap.add_argument("--no-site", action="store_true")
    a = ap.parse_args()
    if not a.draft and (a.interval_min is None or a.scale_bar_um is None):
        raise SystemExit("Give --interval-min and --scale-bar-um (the real values for this movie), or --draft.")

    bar = find_scale_bar(next(iter_frames(MOVIE, max_frames=1)))
    cfg = Config()
    cfg.input.crop = list(REGION)
    cal = cfg.calibration
    cal.frame_interval_min = a.interval_min if a.interval_min else 10.0
    cal.pixel_size_um = (a.scale_bar_um if a.scale_bar_um else 100.0) / bar[2]   # the bar is outside the region
    cal.interval_confirmed = cal.size_confirmed = not a.draft
    res = analyze(MOVIE, cfg, OUT, show_bars=False, keep_earlier=False)
    write_outputs(res, cfg, video=True, pdf=True, signal=res.signal)
    if a.no_site:
        return

    # ---- pictures of the app
    shots = os.path.join(OUT, "website")
    shutil.rmtree(shots, ignore_errors=True)
    os.makedirs(shots)
    app = subprocess.Popen([sys.executable, "-W", "ignore", "-m", "cellsurveillance", "app", "--port", str(PORT),
                            "--headless"], cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(6)
        url = f"http://localhost:{PORT}/?results={urllib.parse.quote(OUT)}&view="
        # show the movie at its busiest moment rather than at the first frame
        busiest = int(res.timecourse["n_ruptured"].rolling(5, center=True, min_periods=1).mean().idxmax())
        seek = ("(() => { const v = document.querySelector('video'); if (v) { v.pause(); v.currentTime = %.2f; } })()"
                % (busiest / 6.0))
        for view, name, height in (("Overview", "card", 1250), ("Ruptures", "ruptures", 1250)):
            subprocess.run([sys.executable, os.path.join(HERE, "scripts", "screenshot.py"), url + view,
                            os.path.join(shots, name + ".png"), "--width", "2000", "--height", str(height), "--scale", "1",
                            "--wait", "16", "--js",
                            "document.querySelectorAll('details').forEach(d => d.open = false)", "--js", seek],
                           check=True)
    finally:
        app.terminate()

    # ---- copy into the site
    import cv2
    import pymupdf
    img_dir = os.path.join(SITE, "public", "images", "tools")
    pages = os.path.join(img_dir, "cell-surveillance-report")
    shutil.rmtree(pages, ignore_errors=True)
    os.makedirs(pages)
    cv2.imwrite(os.path.join(img_dir, "cell-surveillance.jpg"), cv2.imread(os.path.join(shots, "card.png")),
                [cv2.IMWRITE_JPEG_QUALITY, 88])
    doc = pymupdf.open(os.path.join(OUT, "report.pdf"))
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=170)
        pix.pil_save(os.path.join(pages, f"page-{i:02d}.jpg"), format="JPEG", quality=86, optimize=True)
    shutil.copy2(os.path.join(OUT, "annotated_movie.mp4"), os.path.join(SITE, "public", "tools",
                                                                     "cell-surveillance-demo.mp4"))
    hours = res.meta["n_frames"] * res.meta["interval_min"] / 60
    size_um = (REGION[2] - REGION[0]) * res.meta["pixel_size"]
    with open(os.path.join(SITE, "public", "tools", "cell-surveillance-report-example.html"), "w") as fh:
        fh.write(report_page(len(doc), hours, size_um, res, a.draft))
    print(f"site assets written: card image, {len(doc)} report pages, demo movie")


def report_page(n_pages, hours, size_um, res, draft):
    figures = "\n".join(
        f'      <figure class="report-page"><img src="/images/tools/cell-surveillance-report/page-{i:02d}.jpg" '
        f'alt="Cell Surveillance report example page {i}" loading="{"eager" if i < 3 else "lazy"}">'
        f'<figcaption>Page {i} of {n_pages}</figcaption></figure>' for i in range(1, n_pages + 1))
    n_rupt, n_cells = len(res.events), len(res.cells)
    warn = ('<p class="note"><b>Draft.</b> The time between frames and the scale of this movie have not been '
            'confirmed yet, so the times and distances below are placeholders.</p>' if draft else "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cell Surveillance - final report example</title>
  <style>
    :root {{ color-scheme: dark; --bg: #071114; --panel: #102229; --text: #f4fbf8; --muted: #9ab0b3; --accent: #2dd4bf; --line: rgba(173,224,226,.2); }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top right, rgba(45,212,191,.24), transparent 34%), var(--bg); color: var(--text); }}
    header {{ position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; padding: 18px clamp(16px, 5vw, 56px); border-bottom: 1px solid var(--line); background: rgba(7,17,20,.88); backdrop-filter: blur(16px); }}
    .kicker {{ margin: 0 0 6px; color: var(--accent); font: 800 .72rem/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .12em; text-transform: uppercase; }}
    h1 {{ margin: 0; font: 500 clamp(1.9rem, 4vw, 3.4rem)/1.02 Georgia, serif; letter-spacing: -.04em; }}
    h2 {{ margin: 34px 0 12px; font: 500 1.6rem/1.1 Georgia, serif; letter-spacing: -.03em; }}
    p {{ max-width: 76ch; color: var(--muted); line-height: 1.55; }}
    a {{ color: inherit; }}
    .back {{ display: inline-flex; align-items: center; gap: 8px; padding: 10px 14px; border: 1px solid var(--line); border-radius: 999px; color: var(--text); text-decoration: none; background: rgba(255,255,255,.06); font-weight: 800; font-size: .86rem; }}
    main {{ width: min(1080px, calc(100% - 28px)); margin: 26px auto 56px; }}
    .note {{ margin: 0 0 22px; padding: 18px 20px; border: 1px solid var(--line); border-radius: 18px; background: rgba(16,34,41,.82); box-shadow: 0 22px 50px rgba(0,0,0,.22); }}
    .note b {{ color: var(--text); }}
    .demo {{ max-width: 760px; margin: 0 auto 8px; overflow: hidden; border: 1px solid var(--line); border-radius: 18px; background: #000; box-shadow: 0 22px 60px rgba(0,0,0,.32); }}
    .demo video {{ display: block; width: 100%; height: auto; max-height: 82vh; background: #000; }}
    .demo figcaption, .report-page figcaption {{ padding: 10px 14px; background: #0d1f20; color: var(--muted); font: 800 .72rem/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; text-transform: uppercase; }}
    .key {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 18px; margin: 12px 2px 0; color: var(--muted); font-size: .86rem; }}
    .key i {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
    .report-stack {{ display: grid; gap: 22px; }}
    .report-page {{ margin: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 18px; background: #fff; box-shadow: 0 22px 60px rgba(0,0,0,.32); }}
    .report-page img {{ display: block; width: 100%; height: auto; background: #fff; }}
  </style>
</head>
<body>
  <header>
    <div>
      <p class="kicker">Full version · Final report example</p>
      <h1>Cell Surveillance report preview</h1>
    </div>
    <a class="back" href="/#tools">Back to helpful tools</a>
  </header>
  <main>
    {warn}
    <p class="note">This demo follows a {size_um:.0f} × {size_um:.0f} µm region of one of my live-cell movies of cells expressing a nuclear reporter (nls-GFP) for about {hours:.1f} hours. Cell Surveillance tracked {n_cells} nuclei through the region and called {n_rupt} nuclear membrane ruptures, each one a moment when the reporter escaped into the cytoplasm and was later re-imported. The movie shows what the app draws on top of the recording; the pages below are the PDF report it writes.</p>
    <h2>Annotated movie</h2>
    <figure class="demo">
      <video src="/tools/cell-surveillance-demo.mp4" controls loop muted playsinline autoplay></video>
      <figcaption>Every nucleus outlined and numbered, with its recent track</figcaption>
    </figure>
    <div class="key"><span><i style="background:#5ac8ff"></i>Intact nucleus</span><span><i style="background:#ff4081"></i>Ruptured</span><span><i style="background:#ffd60a"></i>Dividing</span><span><i style="background:#ff8c00"></i>Death</span></div>
    <h2>PDF report</h2>
    <section class="report-stack" aria-label="Cell Surveillance report example pages">
{figures}
    </section>
  </main>
</body>
</html>
"""


if __name__ == "__main__":
    main()
