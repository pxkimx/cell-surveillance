"""Every page of the app opens, on a whole-image result and on a result analysed on a region."""
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cellsurveillance.config import Config  # noqa: E402
from cellsurveillance.pipeline import analyze  # noqa: E402
from synth import make_movie  # noqa: E402

APP = os.path.join(ROOT, "cellsurveillance", "app.py")
VIEWS = ["Overview", "Ruptures", "Movement", "Division & death", "Cells", "Region", "Export"]


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    folder = tmp_path_factory.mktemp("pages")
    path = str(folder / "synthetic.tif")
    make_movie(path)
    out = {}
    for name, crop in (("whole", None), ("region", [30, 20, 230, 200])):
        cfg = Config()
        cfg.calibration.pixel_size_um = 0.65
        cfg.calibration.frame_interval_min = 10
        cfg.calibration.interval_confirmed = cfg.calibration.size_confirmed = True
        cfg.input.crop = crop
        res = analyze(path, cfg, str(folder / name), log=lambda *a: None, show_bars=False, record=False)
        assert len(res.cells) > 0
        out[name] = str(folder / name)
    return out


def open_page(outdir, view):
    at = AppTest.from_file(APP, default_timeout=180)
    at.query_params["results"] = outdir
    at.query_params["view"] = view
    at.run()
    return at


@pytest.mark.parametrize("kind", ["whole", "region"])
@pytest.mark.parametrize("view", VIEWS)
def test_results_page_opens(results, kind, view):
    at = open_page(results[kind], view)
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["view"] == view


def test_setup_and_history_open():
    for view in ("Setup", "History"):
        at = AppTest.from_file(APP, default_timeout=180)
        at.query_params["view"] = view
        at.run()
        assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("look", ["light", "dark"])
def test_overview_opens_in_both_looks(results, look, tmp_path, monkeypatch):
    from cellsurveillance import history
    monkeypatch.setattr(history, "PREFERENCES", str(tmp_path / "preferences.json"))
    history.set_preference("theme", look)
    at = open_page(results["whole"], "Overview")
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["theme_pick"] == look
    html = "".join(m.value for m in at.markdown)
    assert f"color-scheme: {look}" in html

