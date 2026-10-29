"""Configuration for the nuclear rupture tracker.

All distances are in micrometres and all times in minutes; they are converted
to pixels / frames using `pixel_size_um` and `frame_interval_min`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Optional

import yaml


@dataclass
class Calibration:
    pixel_size_um: Optional[float] = None   # µm per pixel. None -> derive from scale bar, else 1.0 (units become px)
    scale_bar_um: Optional[float] = None    # real length of the burned-in scale bar, used to derive pixel size
    frame_interval_min: Optional[float] = None   # real time between frames. No default: it differs for every movie
    interval_confirmed: bool = False        # the frame interval was entered by the user for this movie
    size_confirmed: bool = False            # the scale bar or pixel size was confirmed by the user for this movie


@dataclass
class Input:
    channel: str = "auto"         # auto | red | green | blue | gray | <int> (TIFF channel index)
    composite: str = "auto"       # auto | yes | no. yes = reporter is overlaid on transmitted light
    mask_overlays: bool = True    # blank white burned-in text / scale bars
    max_frames: Optional[int] = None
    crop: Optional[list] = None   # [x0, y0, x1, y1] in pixels


@dataclass
class Segmentation:
    smooth_sigma_um: float = 0.6
    nuclear_diameter_um: Optional[float] = None  # None -> estimated from the movie
    low_threshold: Optional[float] = None        # intensity above background (0-255). None -> automatic
    rel_threshold: Optional[float] = None        # fraction of local peak that counts as nucleus. None -> 0.5, or 0.8 if saturated
    min_nucleus_area_um2: Optional[float] = None # None -> a quarter of the typical nuclear area
    min_contrast: float = 1.3                    # nucleus / surrounding intensity needed to start a track
    min_brightness: float = 0.25                 # peak of a nucleus, as a fraction of the brightest nuclei in the movie
    max_nucleus_area_um2: float = 4000.0
    min_fragment_area_um2: float = 2.0
    group_radius_um: float = 2.0                 # fragments closer than ~2x this are one nucleus
    micronucleus_assoc_um: float = 9.0           # small bodies this close to a nucleus are counted as its micronuclei
    split_touching: bool = True
    split_min_radius_frac: float = 0.55          # seed must be at least this fraction of the typical nuclear radius
    split_h_frac: float = 0.15                   # depth of the saddle (fraction of typical radius) required to split
    ring_gap_um: float = 1.5                     # gap between nucleus edge and cytoplasm ring
    ring_width_um: float = 4.0
    ring_percentile: float = 75.0                # percentile of ring pixels used as the cytoplasm level
    border_margin_um: float = 3.0


@dataclass
class Tracking:
    max_link_distance_um: Optional[float] = None  # None -> 1.2 x nuclear diameter
    max_gap_frames: int = 3
    gap_distance_factor: float = 2.0
    area_weight: float = 0.5                       # penalty on log area ratio
    max_split_distance_um: Optional[float] = None  # None -> 1.5 x nuclear diameter
    min_track_frames: int = 5
    drift_correction: bool = False              # subtract the median displacement of all cells (stage drift)


@dataclass
class Rupture:
    # What is measured:
    #   ratio_rise : rise of cytoplasm/nucleus ratio above the cell's own baseline (default)
    #   cyto_rise  : rise of cytoplasm intensity (0-255, background subtracted) above the cell's baseline
    #   ratio_abs  : cytoplasm/nucleus ratio above a fixed value
    #   cyto_abs   : cytoplasm intensity above a fixed value
    mode: str = "ratio_rise"
    threshold: Optional[float] = None       # the rupture threshold in the units of `mode`. None -> automatic
    off_fraction: float = 0.5               # rupture ends when the signal falls below threshold * off_fraction
    min_duration_frames: int = 1
    min_off_frames: int = 2
    max_plateau_frames: int = 6             # end a rupture that settles below the threshold for this long
    baseline_window_frames: int = 12
    merge_gap_frames: int = 1               # events separated by <= this many frames are merged
    noise_factor: float = 4.0               # a noisy cell must also rise by this many times its own noise (0 = off)
    count_at_track_start: bool = False      # count ruptures already under way when the cell is first seen
    ignore_at_image_edge: bool = True       # no ruptures are called while the cell touches the image edge
    ignore_spillover: bool = True           # drop a weak rise that coincides with a much larger rupture next door
    auto_sigma: float = 5.0                 # automatic threshold = auto_sigma x noise of the signal
    auto_min_ratio: float = 0.10
    auto_min_cyto: float = 20.0


@dataclass
class Fate:
    death_min_frames_before_end: int = 4
    division_area_ratio_min: float = 0.2    # daughter area / mother area
    division_area_ratio_max: float = 0.95
    division_sibling_ratio_min: float = 0.4 # smaller daughter / larger daughter
    mitotic_lookback_frames: int = 4
    post_mitotic_frames: int = 3            # reporter is still being re-imported; no ruptures are called here
    death_signal_fraction: float = 0.3      # signal left at the last position, relative to before, that counts as gone
    neighbor_radius_um: float = 50.0


@dataclass
class Analysis:
    """Which measurements to run. Tracking itself is always performed."""
    rupture: bool = True
    movement: bool = True
    division: bool = True
    death: bool = True
    morphology: bool = True
    neighbors: bool = True


@dataclass
class Output:
    overlay_video: bool = True
    overlay_scale: float = 1.0
    pdf_report: bool = True
    html_report: bool = True
    n_event_filmstrips: int = 24
    n_cell_pages: int = 12
    trail_frames: int = 15


@dataclass
class Config:
    calibration: Calibration = field(default_factory=Calibration)
    input: Input = field(default_factory=Input)
    segmentation: Segmentation = field(default_factory=Segmentation)
    tracking: Tracking = field(default_factory=Tracking)
    rupture: Rupture = field(default_factory=Rupture)
    fate: Fate = field(default_factory=Fate)
    analysis: Analysis = field(default_factory=Analysis)
    output: Output = field(default_factory=Output)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str) -> None:
        with open(path, "w") as fh:
            yaml.safe_dump(self.to_dict(), fh, sort_keys=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        cfg = cls()
        for section in fields(cls):
            sub = getattr(cfg, section.name)
            known = {f.name for f in fields(sub)}
            for key, value in (d.get(section.name) or {}).items():
                if key not in known:
                    raise KeyError(f"Unknown config option: {section.name}.{key}")
                setattr(sub, key, value)
        return cfg

    @classmethod
    def load(cls, path: Optional[str]) -> "Config":
        if path is None:
            return cls()
        with open(path) as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})

    def set(self, dotted: str, value) -> None:
        """Set `section.option` from a command-line override."""
        section, _, key = dotted.partition(".")
        sub = getattr(self, section)
        if not hasattr(sub, key):
            raise KeyError(f"Unknown config option: {dotted}")
        setattr(sub, key, value)
