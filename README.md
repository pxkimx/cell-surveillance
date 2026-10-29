# Cell Surveillance

Tracks every cell in a live-cell movie of a nuclear (NLS) fluorescent reporter and measures
nuclear ruptures, movement, divisions, deaths and nuclear shape, cell by cell.

A free Mac app by Paul H. Kim. Project page, demo movie and an example report:
[paul-h-kim.com/software/cell-surveillance](https://paul-h-kim.com/software/cell-surveillance). Source:
[github.com/pxkimx/cell-surveillance](https://github.com/pxkimx/cell-surveillance), MIT licence.

## Install

Python 3.10 or newer with the packages in `pyproject.toml` (numpy, scipy, pandas, scikit-image, OpenCV,
matplotlib, Pillow, PyYAML, tqdm, tifffile, Streamlit, Plotly). An Anaconda installation has them all; otherwise:

```bash
pip install -e .
```

Then `scripts/build_app.sh` builds the double-clickable `Cell Surveillance.app` (macOS) and copies it to
`~/Desktop/Toolbox`. The example movies used during development are not part of this repository.

## Start the app

Double-click **Cell Surveillance.app** (here, or the copy in `~/Desktop/Toolbox`). It opens in your
browser and runs entirely on this computer; nothing is uploaded and it is not reachable from the
network. `Cell Surveillance.command` does the same but shows the log in a Terminal window.

If the project folder is ever moved or renamed, run `scripts/build_app.sh` once: the app stores the
folder's location.

**Light or dark.** The ☀ Light | ☾ Dark pill beside the menu switches the look; the choice is remembered. The
page reconnects in a few seconds, because Streamlit takes its widget colours only when the server starts. The
PDF report keeps its own printable look either way.

**Closing it.** Close the browser tab and the app quits completely within a few seconds: the server
stops, a running analysis is stopped with it, and the icon leaves the Dock. Reloading the page does
not quit it. Quitting or force-quitting the icon in the Dock stops everything too. If the browser
itself crashes, the app quits after three minutes without a window. To use the app again, open it
from the Toolbox. (`cellsurveillance/lifecycle.py` holds the rules.)

## Using it

The menu runs across the top: **Setup**, then the results views, then **History**.

Behind every page runs an animated microscope field (see *The background* below). It is a drawing,
not data, and it never blocks a click. The **Animation** switch at the right of the menu turns it off.

**Setup** has four steps, side by side.

1. **Movie** — drop a movie on the box, or choose one from disk. MOV, MP4, AVI and TIFF are read.
   A dropped movie is copied to `~/Documents/Cell Surveillance/Dropped movies`, because a browser
   never reveals where a dropped file came from.
2. **Calibrate** — nothing here is pre-filled, and nothing is carried over from the last movie.
   - *Minutes between frames*: must be entered for every movie. It is not stored in a MOV file.
   - *Scale*: if a scale bar is found it is shown outlined; tick the box to confirm that it is the
     scale bar and enter the length it represents. Otherwise enter the pixel size, or choose to
     report in pixels.
3. **Measure** — tick what you need: nuclear rupture, movement, division, death, nuclear shape,
   crowding. Anything left unticked is not computed.
4. **Run** — the button stays disabled until the calibration is complete. A 194-frame,
   1434 × 1434 movie takes about 90 seconds.

**Results**

| View | What it shows |
|---|---|
| Overview | Totals, the annotated movie, events over time |
| Ruptures | The threshold control, how many ruptures each threshold would give, and image strips of individual ruptures |
| Movement | Tracks, speed, persistence |
| Division & death | How each track ended, with tables of divisions and deaths |
| Cells | Any one cell: image strip, reporter trace, speed, every measurement |
| Region | Drag a box on the image to export the cropped movie, tables and report for that region |
| Export | Every file, a zip of all tables, and buttons to rebuild the movie or the report |

If results were made without a confirmed calibration, a warning stays at the top until the real
values are entered under **Calibration of these results**. Entering them recalculates every time,
speed, distance and area without tracking again.

**History** lists every analysis with a thumbnail and its totals, so earlier results can be
reopened. Analysing a movie again does not overwrite it: the earlier results move to an
`earlier runs` folder inside the results folder and stay in the list.

A folder of movies can be moved together with its `Cell Surveillance results` folder. Results
look for their movie next to the results folder when the place recorded at analysis time no
longer exists. If a moved analysis is missing from History, use **Open a results folder…** there.

## Command line

```bash
cd "Cell Surveillance"          # the project folder

# one movie
python3 -m cellsurveillance analyze movie.mov --interval-min 15 --scale-bar-um 100

# a folder: write a table of the movies, fill in the calibration of each, then analyse
python3 -m cellsurveillance calibration-template "/path/to/movies"
python3 -m cellsurveillance analyze "/path/to/movies" --calibration "/path/to/movies/calibration.csv"

# correct the calibration of finished results (no re-tracking)
python3 -m cellsurveillance recalibrate "/path/to/results/movie" --interval-min 15

# change what counts as a rupture (no re-tracking)
python3 -m cellsurveillance recall "/path/to/results/movie" --rupture-threshold 0.2

# export one region
python3 -m cellsurveillance roi "/path/to/results/movie" --roi 300,300,900,800
```

The frame interval and scale are never assumed. Without them the command asks, movie by movie, or
stops if there is nobody to ask. A single value is applied to a whole folder only with
`--same-for-all`.

Results are written next to the movie in `Cell Surveillance results/<movie name>/`.

## Output files

| File | Contents |
|---|---|
| `report.pdf` | Summary, population plots, rupture/movement/shape/fate pages, image galleries of ruptures, divisions and deaths, methods |
| `annotated_movie.mp4` | The movie with each nucleus outlined by state, cell numbers, trails and a running event count |
| `cells_summary.csv` | One row per cell: fate, lineage, rupture counts and durations, movement, shape, crowding |
| `cells_per_frame.csv` | One row per cell per frame: position, speed, reporter intensities, rupture state, shape |
| `rupture_events.csv` | One row per rupture: start, duration, size, recovery, shape and speed beforehand, outcome |
| `divisions.csv` | Mother, daughters, time, daughter symmetry, confidence |
| `deaths.csv` | Time, confidence, evidence, rupture history |
| `population_summary.csv` | Totals and rates for the whole movie |
| `population_timecourse.csv` | Cell count, fraction ruptured, cumulative events at every frame |
| `rupture_threshold_sweep.csv` | How many ruptures would be called at each threshold |
| `settings_used.yaml` | Every setting used, including whether the calibration was confirmed |

## What is measured

**Nuclear rupture** — number per cell, start time, duration, size (peak rise of reporter in the
cytoplasm), time to peak, recovery half-time, time between ruptures, fraction of time ruptured,
ruptures still open when tracking ended, nuclear shape and cell speed just before the rupture,
time from last rupture to death.

**Movement** — path length, net and maximum displacement, persistence, mean and maximum speed,
mean turning angle, MSD exponent and diffusion coefficient, speed while ruptured versus intact.

**Division** — time, mother and daughters, lineage and generation, daughter size symmetry,
cell-cycle length for cells seen from birth to division.

**Death** — time, confidence (high / medium / low), evidence.

**Nuclear shape** — area, perimeter, circularity, solidity (lobulation), aspect ratio, number of
fragments, micronuclei count and area, growth rate.

**Crowding** — distance to the nearest neighbour and number of neighbours within 50 µm.

## How events are called

**Rupture.** The reporter is measured in the nucleus and in a ring of cytoplasm around it. A
rupture is called when the signal crosses the threshold, in one of four modes:

| Mode | A rupture is called when… |
|---|---|
| `ratio_rise` (default) | the cytoplasm/nucleus ratio rises above the cell's own baseline by the threshold |
| `cyto_rise` | the cytoplasm intensity (0–255) rises above the cell's own baseline by the threshold |
| `ratio_abs` | the cytoplasm/nucleus ratio exceeds the threshold |
| `cyto_abs` | the cytoplasm intensity exceeds the threshold |

Not counted as ruptures: nuclear envelope breakdown before a division; the collapse of the nucleus
as a cell dies (listed as `terminal`); anything while the cell touches the image edge; a weak rise
that coincides with a much larger rupture in a touching neighbour, whose cytoplasm reaches into
this cell's ring.

**Division.** A nucleus that loses its reporter and is replaced by two smaller nuclei. Two touching
nuclei that separate look the same in outline, so the evidence has to be in the signal: the
reporter must have left the nucleus. Splits without that are listed as low confidence and do not
split the track.

**Death.** A track that simply stops is not a death. The reporter must be gone from where the
nucleus was, and either the nucleus was seen to shrink, fade or break up, or nothing takes its
place. A nucleus that disappears while touching another is recorded as *hidden by neighbour*.

## How well it works

`tests/benchmark.py` simulates crowded movies with known tracks and events (saturated nuclei, cells
crawling over one another, ruptures from faint to flooding, lobed nuclei, deaths, divisions, video
compression) and scores the result. Averages over four simulated movies of about 53 cells:

| Measure | First version | Now |
|---|---|---|
| Objects tracked that are really nuclei | 69% | 99% |
| Tracks reported, for 53 true cells | 140 | 57 |
| Cells followed for at least 80% of their time by one track | 52% | 66% |
| Ruptures found | 89% | 90% |
| Rupture calls that are real | 74% | 85% |
| Deaths found | 58% | 81% |
| Death calls that are real | 6% | 61% |
| Divisions found | 22% | 50% |
| Division calls that are real | 19% | 71% |

A simulation is not your data. These numbers say the method is sound and show where it is weak
(identity is lost when nuclei overlap completely; a third of deaths and divisions are still
miscalled). They do not replace checking calls against your own counts.

```bash
python3 -m pytest tests            # 11 tests on a small synthetic movie, about 15 seconds
python3 tests/benchmark.py         # the benchmark above, about 2 minutes
```

## Settings

Every setting has a default chosen from the movie. To change one, pass `--set section.option=value`
or a YAML file with `--config`. The ones most likely to matter:

| Setting | Meaning |
|---|---|
| `segmentation.nuclear_diameter_um` | Typical nuclear diameter, if the automatic estimate is wrong |
| `segmentation.rel_threshold` | Fraction of the local peak that counts as nucleus (0.5; 0.8 for saturated movies) |
| `segmentation.min_brightness` | Peak a nucleus must reach, as a fraction of the brightest nuclei (0.25) |
| `segmentation.min_contrast` | How much brighter than its surroundings a nucleus must be to start a track |
| `tracking.max_link_distance_um` | Furthest a nucleus may move between two frames |
| `tracking.max_gap_frames` | Longest disappearance that is bridged |
| `tracking.drift_correction` | Subtract the median movement of all cells (stage drift) |
| `rupture.min_duration_frames` | Shortest rupture counted |
| `rupture.count_at_track_start` | Count ruptures already under way when a cell is first seen |
| `rupture.ignore_spillover` | Drop weak rises explained by a neighbour's rupture |

## Limitations

- Movies exported as MOV/MP4 are 8-bit and compressed. Intensities are relative, not quantitative.
  If the nuclei are saturated, a rupture is detected from the rise in the cytoplasm only. Analysing
  the original microscope files (as TIFF) will be more sensitive.
- With only a nuclear reporter, division and death are inferred. There is no viability dye and no
  chromatin marker. Check the galleries in the report.
- Where nuclei overlap for many frames, identities can swap. The *hidden by neighbour* and *track
  lost* fates count the tracks that ended for this reason.

## The background

`cellsurveillance/hero.py` draws the animated field behind the app. It imitates a two-channel
movie: a green NLS reporter and a red histone. Cells crawl with a lamellipodium and a tail; a
nucleus blebs and ruptures, the reporter floods the cell and the nucleus is left red until the
reporter is re-imported; chromosomes condense, line up and separate, and the cell pinches in two;
a dying cell shrinks, blebs and breaks up; neurons grow branching neurites. The picture is formed
the way a microscope forms one (out-of-focus haze, limited sharpness, camera noise), and the
tracking overlay is drawn sharp on top. It is kept cheap: the picture is drawn small
and enlarged by the browser, twenty times a second. It rests while the app's window is in the
background and while a movie is being analysed, and the **Animation** switch beside the menu turns
it into a still picture that uses no processor time (the choice is remembered).

## Website demo

`scripts/make_demo.py` analyses a small region of one movie and copies the card screenshot, report
pages and demo movie into the website repository. `scripts/publish_demo.sh <minutes between frames>
<scale bar µm>` does that with the real calibration and updates the site branch; it prints the
command that publishes and does not run it.

## Planned additions

- **Cell morphology**: whole-cell size, spreading and membrane changes
- **Dynamics**: organelle movement, vesicle trafficking, cytoskeleton remodelling
- **Molecular activity**: calcium, pH, voltage, enzyme activity, gene-expression reporters
- **Cell interactions**: contact, fusion, communication, immune-cell killing
- **Growth and survival**: proliferation rate and cell-cycle timing from cell-cycle reporters
- **Spatial measurements**: protein location, multi-channel intensity, colocalization
