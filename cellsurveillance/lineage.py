"""Identity and lineage: occlusions, long gaps and cell divisions.

With an NLS reporter a division looks like this: the nuclear signal disperses
at nuclear envelope breakdown (the nucleus is lost or the whole rounded cell
lights up), and afterwards two smaller nuclei appear next to each other.
Two nuclei that merely touch and separate again look similar, so a split only
counts as a division if it is preceded by that mitotic signature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Fate
from .track import Chains, TrackParams, _segment_table, find_merges_and_splits


class _Union:
    """Tracks joined into one identity. Two tracks that exist at the same time are never joined."""

    def __init__(self, spans: dict):
        self.parent = {}
        self.spans = {k: [tuple(v)] for k, v in spans.items()}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, keep, drop) -> bool:
        a, b = self.find(keep), self.find(drop)
        if a == b:
            return False
        for s0, s1 in self.spans.get(a, []):
            for t0, t1 in self.spans.get(b, []):
                if s0 <= t1 and t0 <= s1:
                    return False
        self.parent[b] = a
        self.spans[a] = self.spans.get(a, []) + self.spans.pop(b, [])
        return True


def relink(det: pd.DataFrame, tp: TrackParams, n_frames: int, mitosis_gap: int = 8, long_gap: int = 16, log=print):
    """Re-join tracks that were interrupted by an occlusion or a long gap.

    Returns (det with updated `track`, split candidates, gap-division candidates, occlusions).
    """
    merges, splits, chains = find_merges_and_splits(det, tp, n_frames)
    tab = _segment_table(det, "track")
    union = _Union({t: (r.t0, r.t1) for t, r in tab.iterrows()})
    occlusions = []
    open_merges = merges.to_dict("records") if len(merges) else []
    used_merge = set()
    used_track = {}
    remaining_splits = []
    has_split = set()

    for s in (splits.sort_values("frame").to_dict("records") if len(splits) else []):
        j, m, frame = s["track"], s["mother"], s["frame"]
        has_split.add(j)
        best = None
        for k, mg in enumerate(open_merges):
            if k in used_merge or mg["into"] != m or not (0 <= frame - mg["frame"] <= tp.max_occlusion):
                continue
            ratio = tab.at[j, "a0"] / max(mg["area"], 1)
            if used_track.get(mg["track"]):
                continue
            if 0.5 <= ratio <= 2.0 and (best is None or abs(np.log(ratio)) < best[1]):
                best = (k, abs(np.log(ratio)))
        if best is not None:
            mg = open_merges[best[0]]
            if union.join(mg["track"], j):
                used_merge.add(best[0])
                used_track[mg["track"]] = True
                occlusions.append(dict(track=mg["track"], hidden_by=m, first_frame=mg["frame"], last_frame=frame - 1))
            else:
                remaining_splits.append(s)
        else:
            remaining_splits.append(s)

    merged_away = {mg["track"] for k, mg in enumerate(open_merges) if k not in used_merge}

    # starts with no neighbour: look for a track that ended shortly before
    ended = tab[(tab.t1 < n_frames - 1)]
    starts = tab[(tab.t0 > 0) & ~tab.index.isin(has_split) & ~tab.border0.astype(bool)]
    claims = {}
    for j, r in starts.iterrows():
        cand = ended[(ended.t1 < r.t0) & (ended.t1 >= r.t0 - long_gap - 1) & (ended.index != j)]
        if cand.empty:
            continue
        d = np.hypot(cand.x1 - r.x0, cand.y1 - r.y0)
        gap = r.t0 - cand.t1
        reach = np.where(gap <= mitosis_gap + 1, 1.3 * tp.split_dist, 0.8 * tp.max_dist)
        d = d[d <= reach]
        if d.empty:
            continue
        claims.setdefault(d.idxmin(), []).append((j, float(d.min())))
    gap_divisions = []
    for m, js in claims.items():
        js = sorted(js, key=lambda v: v[1])
        if len(js) >= 2:
            gap_divisions.append(dict(mother=m, a=js[0][0], b=js[1][0], frame=int(min(tab.at[js[0][0], "t0"],
                                                                                   tab.at[js[1][0], "t0"]))))
        elif m not in merged_away:
            j = js[0][0]
            ratio = tab.at[j, "a0"] / max(tab.at[m, "a1"], 1)
            if 0.4 <= ratio <= 1.8:
                union.join(m, j)

    det = det.copy()
    det["track"] = det["track"].map(union.find)
    if det.duplicated(["track", "frame"]).any():          # cannot happen; if it ever does, keep the tracks apart
        raise AssertionError("a cell was given two positions in one frame")
    for rec in remaining_splits:
        rec["track"], rec["mother"] = union.find(rec["track"]), union.find(rec["mother"])
    remaining_splits = [r for r in remaining_splits if r["track"] != r["mother"]]
    for rec in gap_divisions:
        for k in ("mother", "a", "b"):
            rec[k] = union.find(rec[k])
    for rec in occlusions:
        rec["track"], rec["hidden_by"] = union.find(rec["track"]), union.find(rec["hidden_by"])
    merged_away = {union.find(t) for t in merged_away}
    log(f"  {len(occlusions)} occlusions resolved, {len(remaining_splits) + len(gap_divisions)} candidate divisions")
    return det, pd.DataFrame(remaining_splits), pd.DataFrame(gap_divisions), pd.DataFrame(occlusions), merged_away


def _mitotic_signature(rows: pd.DataFrame, baseline_cn: float) -> tuple[bool, str]:
    """Did the reporter leave the nucleus in these frames?

    Two touching nuclei that are segmented as one and then separate look like a
    division in outline, but their reporter never leaves the nucleus. So the
    evidence has to be in the signal: the cytoplasm rising towards the nuclear
    level, or no nucleus to be found where there is still reporter.
    """
    if rows.empty:
        return False, ""
    cn = rows["cn_ref"]
    high = max(0.5, baseline_cn + 0.3)
    dispersed = cn >= high
    if (dispersed & rows["abnormal_mask"]).any():
        return True, "reporter filled the cell"
    if dispersed.any():
        return True, "reporter dispersed"
    lost = ~rows["detected"]
    if "reference_lost" in rows:
        lost = lost & (rows["reference_lost"] | cn.isna() | (cn >= baseline_cn + 0.2))
    if lost.any():
        return True, "nucleus lost"
    return False, ""


def classify_divisions(frames: pd.DataFrame, splits: pd.DataFrame, gap_divisions: pd.DataFrame, fate: Fate,
                       log=print):
    """Decide which candidate splits are divisions, cut the mother tracks and assign final cell ids.

    Returns (frames with `cell` and `parent`, divisions table).
    """
    frames = frames.sort_values(["track", "frame"]).reset_index(drop=True)
    by_track = {t: g for t, g in frames.groupby("track", sort=False)}
    L = fate.mitotic_lookback_frames
    divisions, cuts = [], {}          # cuts: track -> list of (first daughter frame, division index)

    def area_at(track, lo, hi):
        g = by_track[track]
        a = g.loc[g["detected"] & g["frame"].between(lo, hi) & ~g["abnormal_mask"], "area"]
        if a.empty:
            a = g.loc[g["detected"] & g["frame"].between(lo, hi), "area"]
        return float(a.median()) if len(a) else np.nan

    def evaluate(mother, first_a, first_b, a_track, b_track, kind):
        g = by_track[mother]
        first = min(first_a, first_b)
        before = g[g["frame"] < first]
        if len(before) < 3:
            return None
        mother_area = area_at(mother, first - L - 8, first - L - 1)
        if not np.isfinite(mother_area):
            mother_area = area_at(mother, first - 20, first - 1)
        da = area_at(a_track, first_a, first_a + 2)
        db = area_at(b_track, first_b, first_b + 2)
        if not (np.isfinite(mother_area) and np.isfinite(da) and np.isfinite(db)):
            return None
        ra, rb = da / mother_area, db / mother_area
        sibling = min(da, db) / max(da, db)
        area_ok = (fate.division_area_ratio_min <= ra <= fate.division_area_ratio_max and
                   fate.division_area_ratio_min <= rb <= fate.division_area_ratio_max and
                   sibling >= fate.division_sibling_ratio_min)
        baseline = float(before["cn_ref"].iloc[:-L].median()) if len(before) > L + 2 else float(before["cn_ref"].median())
        window = g[g["frame"].between(first - L, max(first_a, first_b) - 1)]
        sig, why = _mitotic_signature(window, baseline)
        if kind == "gap" and not sig:
            sig, why = True, "nucleus lost"
        if not area_ok:
            return None
        return dict(mother_track=mother, frame=int(first), daughter_a_area=da, daughter_b_area=db,
                    mother_area=mother_area, area_ratio_a=ra, area_ratio_b=rb, sibling_ratio=sibling,
                    mitotic_signature=why, confidence="high" if sig else "low")

    for s in (splits.to_dict("records") if len(splits) else []):
        m, j, frame = s["mother"], s["track"], int(s["frame"])
        if m not in by_track or j not in by_track:
            continue
        g = by_track[m]
        # if the mother went through a gap just before, daughter A starts after the gap
        det_frames = g.loc[g["detected"], "frame"].to_numpy()
        after = det_frames[det_frames >= frame - L]
        gaps = np.flatnonzero(np.diff(det_frames) > 1)
        first_a = frame
        for k in gaps:
            if frame - L <= det_frames[k + 1] <= frame + L:
                first_a = int(det_frames[k + 1])
        if len(after) == 0:
            continue
        rec = evaluate(m, first_a, frame, m, j, "split")
        if rec is None:
            continue
        rec.update(daughter_b_track=j, first_a=first_a, first_b=frame)
        divisions.append(rec)

    for s in (gap_divisions.to_dict("records") if len(gap_divisions) else []):
        m, a, b = s["mother"], s["a"], s["b"]
        if not all(t in by_track for t in (m, a, b)) or len({m, a, b}) < 3:
            continue
        fa, fb = int(by_track[a]["frame"].min()), int(by_track[b]["frame"].min())
        rec = evaluate(m, fa, fb, a, b, "gap")
        if rec is None:
            continue
        rec.update(daughter_a_track=a, daughter_b_track=b, first_a=fa, first_b=fb)
        divisions.append(rec)

    divisions = pd.DataFrame(divisions)
    # --- assign final cell ids; only high-confidence divisions cut the mother
    frames["piece"] = 0
    parent_of = {}                     # (track, piece) -> (track, piece) of mother
    if len(divisions):
        divisions = divisions.sort_values("frame").reset_index(drop=True)
        divisions["daughter_a_track"] = divisions.get("daughter_a_track", pd.Series(dtype=float))
        piece_count = {}
        for i, d in divisions.iterrows():
            if d.confidence != "high":
                continue
            m = d.mother_track
            mother_piece = piece_count.get(m, 0)
            first = min(d.first_a, d.first_b)
            sel_m = (frames["track"] == m) & (frames["piece"] == mother_piece)
            if pd.isna(d.daughter_a_track):          # daughter A is the continuation of the mother track
                new_piece = mother_piece + 1
                piece_count[m] = new_piece
                frames.loc[sel_m & (frames["frame"] >= d.first_a), "piece"] = new_piece
                frames.loc[sel_m & (frames["frame"] >= first) & (frames["frame"] < d.first_a), "piece"] = -1
                parent_of[(m, new_piece)] = (m, mother_piece)
                divisions.at[i, "_a"] = f"{m}|{new_piece}"
            else:
                a = d.daughter_a_track
                parent_of[(a, 0)] = (m, mother_piece)
                divisions.at[i, "_a"] = f"{a}|0"
            parent_of[(d.daughter_b_track, 0)] = (m, mother_piece)
            divisions.at[i, "_b"] = f"{d.daughter_b_track}|0"
            divisions.at[i, "_m"] = f"{m}|{mother_piece}"
    frames = frames[frames["piece"] >= 0].copy()
    key = frames["track"].astype(str) + "|" + frames["piece"].astype(str)
    first_frame = frames.groupby(key)["frame"].min().sort_values(kind="stable")
    cell_id = {k: i for i, k in enumerate(first_frame.index, start=1)}
    frames["cell"] = key.map(cell_id)
    parent = {cell_id[f"{t}|{p}"]: cell_id[f"{mt}|{mp}"] for (t, p), (mt, mp) in parent_of.items()
              if f"{t}|{p}" in cell_id and f"{mt}|{mp}" in cell_id}
    frames["parent"] = frames["cell"].map(parent).astype("Int64")
    if len(divisions):
        for col, src in (("mother", "_m"), ("daughter_a", "_a"), ("daughter_b", "_b")):
            divisions[col] = divisions[src].map(cell_id).astype("Int64") if src in divisions else pd.NA
        # a division whose mother has no frames of her own left (two splits at once) cannot be placed in a lineage
        orphan = (divisions["confidence"] == "high") & divisions["mother"].isna()
        divisions.loc[orphan, "confidence"] = "low"
        low = divisions["confidence"] == "low"
        track_cell = frames.groupby("track")["cell"].first()
        divisions.loc[low, "mother"] = divisions.loc[low, "mother_track"].map(track_cell)
        divisions.loc[low, "daughter_b"] = divisions.loc[low, "daughter_b_track"].map(track_cell)
        divisions = divisions.drop(columns=[c for c in ("_m", "_a", "_b", "daughter_a_track", "daughter_b_track",
                                                        "mother_track", "first_a", "first_b") if c in divisions])
    n_high = int((divisions["confidence"] == "high").sum()) if len(divisions) else 0
    log(f"  {n_high} divisions ({len(divisions) - n_high} more with low confidence)")
    return frames.drop(columns=["piece"]), divisions
