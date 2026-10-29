"""What happened to each cell: how its track starts and ends."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Fate

FATES = ("divided", "death", "left_field", "end_of_movie", "occluded", "lost")


def assign_fates(frames: pd.DataFrame, probes: pd.DataFrame, divisions: pd.DataFrame, merged_away: set,
                 n_frames: int, shape: tuple, edge_px: float, low_threshold: float, fate: Fate,
                 detect_death: bool = True, radius_px: float = 15.0) -> pd.DataFrame:
    """One row per cell with `start_reason`, `fate` and the evidence behind a death call.

    A track that simply stops is not a death. The cell may have moved further than
    the tracker follows, in which case a new track starts nearby. A death needs the
    reporter to be gone from where the nucleus was, and either the nucleus was seen
    to shrink, fade or break up, or nothing takes its place.
    """
    H, W = shape
    from scipy.spatial import cKDTree
    starts = frames[frames["detected"]].sort_values("frame").groupby("cell").first()
    starts = starts[starts["frame"] > 0]
    start_tree = cKDTree(starts[["x", "y"]].to_numpy()) if len(starts) else None
    start_frame = starts["frame"].to_numpy() if len(starts) else np.array([])
    start_cell = starts.index.to_numpy() if len(starts) else np.array([])
    det = frames[frames["detected"]].sort_values(["cell", "frame"])
    g = det.groupby("cell")
    first, last = g.first(), g.last()
    out = pd.DataFrame({"cell": first.index, "track": first["track"].to_numpy(),
                        "first_frame": first["frame"].to_numpy(), "last_frame": last["frame"].to_numpy()})
    parent = frames.groupby("cell")["parent"].first()
    out["parent"] = out["cell"].map(parent).astype("Int64")

    mothers = set()
    if len(divisions):
        mothers = set(divisions.loc[divisions["confidence"] == "high", "mother"].dropna().astype(int))

    def near_edge(r):
        return bool(r.at_border) or min(r.x, r.y, W - 1 - r.x, H - 1 - r.y) <= edge_px

    start_edge = first.apply(near_edge, axis=1).to_numpy()
    end_edge = last.apply(near_edge, axis=1).to_numpy()
    out["start_reason"] = np.select(
        [out["parent"].notna().to_numpy(), out["first_frame"].to_numpy() == 0, start_edge],
        ["division", "movie_start", "entered_field"], default="appeared")

    probe = probes.set_index("track") if len(probes) else pd.DataFrame(columns=["post_nuc", "pre_nuc"])
    last_cell_of_track = out.sort_values("last_frame").groupby("track")["cell"].last()
    fates, evidence, confidence = [], [], []
    for i, r in out.iterrows():
        cell = r.cell
        if cell in mothers:
            fates.append("divided"); evidence.append(""); confidence.append("")
            continue
        if r.last_frame >= n_frames - 1 - 1:
            fates.append("end_of_movie"); evidence.append(""); confidence.append("")
            continue
        if end_edge[i]:
            fates.append("left_field"); evidence.append(""); confidence.append("")
            continue
        touching = r.track in merged_away and last_cell_of_track.get(r.track) == cell
        if touching and not detect_death:
            fates.append("occluded"); evidence.append("hidden by a neighbouring nucleus"); confidence.append("")
            continue
        if not detect_death or r.last_frame > n_frames - 1 - fate.death_min_frames_before_end:
            fates.append("lost"); evidence.append(""); confidence.append("")
            continue
        rows = det[det["cell"] == cell]
        tail, body = rows.iloc[-4:], rows.iloc[:-4]
        clues = []
        gone = taken = False
        if r.track in probe.index and last_cell_of_track.get(r.track) == cell:
            post, pre = probe.at[r.track, "post_nuc"], probe.at[r.track, "pre_nuc"]
            occupied = probe.at[r.track, "post_occupied"] if "post_occupied" in probe else 0.0
            # another nucleus sitting where this one was means the track was handed over, not that the cell died
            taken = bool(np.isfinite(occupied) and occupied > 0.25)
            if np.isfinite(post) and post <= max(low_threshold, fate.death_signal_fraction * pre) and not taken:
                gone = True
                clues.append("signal disappeared")
        if len(body) >= 3:
            if tail["area"].median() < 0.6 * body["area"].median():
                clues.append("nucleus shrank")
            if tail["n_fragments"].max() >= body["n_fragments"].median() + 2:
                clues.append("nucleus fragmented")
            if tail["nuc_mean"].median() < 0.6 * body["nuc_mean"].median():
                clues.append("signal faded")
        # did another track begin close by, just after this one stopped? Then the cell was lost, not dead
        last_row = rows.iloc[-1]
        replaced = False
        if start_tree is not None:
            near = start_tree.query_ball_point([last_row.x, last_row.y], 5.0 * radius_px)
            replaced = any(start_cell[j] != cell and 0 < start_frame[j] - r.last_frame <= 6 for j in near)
        precursors = [c for c in clues if c != "signal disappeared"]
        replaced = replaced or taken
        if touching and not (gone and len(precursors) >= 2):
            # next to another nucleus a disappearance proves nothing, unless the nucleus was seen to break down
            fates.append("occluded"); confidence.append(""); evidence.append("hidden by a neighbouring nucleus")
            continue
        if gone and precursors and not replaced:
            fates.append("death"); confidence.append("high")
        elif gone and not replaced:
            fates.append("death"); confidence.append("medium")
            clues.append("nothing took its place")
        elif len(precursors) >= 2 and not replaced:
            fates.append("death"); confidence.append("low")
        else:
            fates.append("lost"); confidence.append("")
            clues = (["another nucleus is in its place"] if taken else ["another track began nearby"]) if replaced else []
        evidence.append(", ".join(clues))
    out["fate"] = fates
    out["fate_evidence"] = evidence
    out["death_confidence"] = confidence
    return out
