import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cellsurveillance.config import Config  # noqa: E402
from cellsurveillance.pipeline import analyze, recall  # noqa: E402
from cellsurveillance.roi import export_roi  # noqa: E402
from synth import make_movie  # noqa: E402


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    folder = tmp_path_factory.mktemp("movie")
    path = str(folder / "synthetic.tif")
    truth = make_movie(path)
    cfg = Config()
    cfg.calibration.pixel_size_um = 0.65
    cfg.calibration.frame_interval_min = 10
    res = analyze(path, cfg, str(folder / "out"), log=lambda *a: None, show_bars=False)
    return res, truth, str(folder / "out")


def test_every_cell_is_tracked(run):
    res, truth, _ = run
    first = res.frames[res.frames["frame"] == 0]
    assert len(first) == truth["n_cells"]
    # the four cells without a division or death are followed for the whole movie
    full = res.cells[(res.cells["first_frame"] == 0) & (res.cells["fate"] == "end_of_movie")]
    assert len(full) == 4


def test_ruptures_are_counted_and_timed(run):
    res, truth, _ = run
    expected = sorted(a for spans in truth["ruptures"].values() for a, _ in spans)
    found = sorted(res.events["start_frame"])
    assert found == expected
    assert sorted(res.cells["n_ruptures"])[-2:] == [1, 2]
    assert res.cells["n_ruptures"].sum() == 3
    durations = dict(zip(res.events["start_frame"], res.events["duration_frames"]))
    for spans in truth["ruptures"].values():
        for a, b in spans:
            assert abs(durations[a] - (b - a + 1)) <= 1


def test_division_is_found(run):
    res, truth, _ = run
    high = res.divisions[res.divisions["confidence"] == "high"]
    assert len(high) == 1
    # the division is timed when the two daughter nuclei can be told apart
    assert abs(int(high["frame"].iloc[0]) - truth["division"]["reform"]) <= 3
    assert (res.cells["start_reason"] == "division").sum() == 2
    assert (res.cells["fate"] == "divided").sum() == 1


def test_death_is_found(run):
    res, truth, _ = run
    dead = res.cells[res.cells["fate"] == "death"]
    assert len(dead) == 1
    assert abs(int(dead["last_frame"].iloc[0]) + 1 - truth["death"]["gone"]) <= 2


def test_threshold_changes_the_calls(run):
    res, _, out = run
    strict = recall(out, threshold=5.0, log=lambda *a: None)
    assert len(strict.events) == 0
    again = recall(out, threshold=None, log=lambda *a: None)
    assert len(again.events) == len(res.events)


def test_movement_is_calibrated(run):
    res, _, _ = run
    cells = res.cells[res.cells["fate"] == "end_of_movie"]
    assert (cells["path_length_um"] > 0).all()
    assert (cells["net_displacement_um"] <= cells["path_length_um"] + 1e-6).all()


def test_region_export(run):
    res, _, out = run
    result = export_roi(res, (0, 0, 160, 160), os.path.join(out, "region"), video=True, pdf=False, log=lambda *a: None)
    assert result["n_cells"] >= 1
    assert os.path.getsize(result["video"]) > 0
    assert any(p.endswith("cells_summary.csv") for p in result["tables"])


def test_frame_interval_is_never_assumed(tmp_path):
    from cellsurveillance.pipeline import CalibrationError
    assert Config().calibration.frame_interval_min is None
    path = str(tmp_path / "m.tif")
    make_movie(path, n_frames=6, size=128)
    with pytest.raises(CalibrationError):
        analyze(path, Config(), str(tmp_path / "out"), log=lambda *a: None, show_bars=False)


def test_recalibrating_rescales_times_and_distances(run):
    from cellsurveillance.pipeline import recalibrate
    res, _, out = run
    before = res.events.sort_values(["cell", "start_frame"])["duration_min"].to_numpy()
    path_before = res.cells.sort_values("cell")["path_length_um"].to_numpy()
    new = recalibrate(out, interval_min=30, pixel_size_um=1.3, log=lambda *a: None)
    after = new.events.sort_values(["cell", "start_frame"])["duration_min"].to_numpy()
    assert after == pytest.approx(before * 3)
    assert new.cells.sort_values("cell")["path_length_um"].to_numpy() == pytest.approx(path_before * 2, rel=1e-6)
    assert new.meta["interval_confirmed"] and new.meta["size_confirmed"]
    recalibrate(out, interval_min=10, pixel_size_um=0.65, log=lambda *a: None)


def test_command_line_refuses_to_guess(tmp_path, capsys):
    from cellsurveillance.cli import main, read_calibration, write_calibration_template
    for name in ("a.tif", "b.tif"):
        make_movie(str(tmp_path / name), n_frames=6, size=128)
    # no interval given and nobody to ask: both movies are skipped, nothing is analysed
    assert main(["analyze", str(tmp_path), "--no-video", "--no-pdf", "--progress"]) == 1
    assert not (tmp_path / "Cell Surveillance results").exists()
    # one value for a whole folder needs an explicit --same-for-all
    with pytest.raises(SystemExit):
        main(["analyze", str(tmp_path), "--interval-min", "10", "--no-video", "--no-pdf"])
    template = write_calibration_template(str(tmp_path))
    rows = read_calibration(template)
    assert set(rows) == {"a.tif", "b.tif"}
    assert all(v["interval_min"] is None for v in rows.values())


def test_reanalysis_keeps_the_earlier_run(tmp_path, monkeypatch):
    from cellsurveillance import history
    monkeypatch.setattr(history, "REGISTRY", str(tmp_path / "history.json"))
    monkeypatch.setattr(history, "HOME", str(tmp_path))
    path = str(tmp_path / "m.tif")
    make_movie(path, n_frames=20, size=200)
    cfg = Config()
    cfg.calibration.frame_interval_min = 5
    out = str(tmp_path / "out")
    analyze(path, cfg, out, log=lambda *a: None, show_bars=False)
    assert [e["outdir"] for e in history.entries()] == [out]
    cfg.calibration.frame_interval_min = 20
    analyze(path, cfg, out, log=lambda *a: None, show_bars=False)
    found = history.entries()
    assert len(found) == 2
    earlier = [e for e in found if e["earlier_run"]]
    assert len(earlier) == 1 and earlier[0]["interval_min"] == 5
    assert os.path.exists(os.path.join(earlier[0]["outdir"], "cells_summary.csv"))
    from cellsurveillance.pipeline import load_results
    assert load_results(earlier[0]["outdir"], with_labels=True, recompute=False).meta["interval_min"] == 5


def test_results_find_their_movie_after_the_folder_is_moved(tmp_path):
    """Results sit in '<movie folder>/Cell Surveillance results/<name>'; moving the folder must not lose the movie."""
    from cellsurveillance import history
    movies = tmp_path / "moved here"
    out = movies / "Cell Surveillance results" / "clip"
    out.mkdir(parents=True)
    (movies / "clip.mov").write_bytes(b"x")
    meta = {"movie": "clip.mov", "path": "/somewhere/that/no/longer/exists/clip.mov"}
    assert history.locate_movie(str(out), meta) == str(movies / "clip.mov")
    earlier = out / "earlier runs" / "2026-01-01 10.00.00"
    earlier.mkdir(parents=True)
    assert history.locate_movie(str(earlier), meta) == str(movies / "clip.mov")
    here = {"movie": "clip.mov", "path": str(movies / "clip.mov")}
    assert history.locate_movie(str(out), here) == here["path"]
    gone = {"movie": "other.mov", "path": "/nowhere/other.mov"}
    assert history.locate_movie(str(out), gone) == "/nowhere/other.mov"
