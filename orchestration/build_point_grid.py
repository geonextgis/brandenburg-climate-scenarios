#!/usr/bin/env python
"""Map the Brandenburg 1 km site grid onto the HYRAS-BC climate grid.

The baseline (DWD) climate is addressed by the ``vColumn``/``vRow`` already
carried in each crop's site table — that is the DWD grid. The HYRAS
bias-corrected CMIP files are on a **different** grid (0.01 deg lat/lon), so a
historical or future experiment cannot reuse those column/row numbers. This
script builds the join once, into ``data/raw/point_to_nearest_grid.csv``, which
``generate.py`` reads for every non-baseline climate.

Source of the HYRAS grid: ``<climate_root_hyras>/latlon_to_rowcol.json`` — a
list of ``[[lat, lon], [row, col]]`` pairs covering Germany (755 x 889 cells).
The grid is regular (0.01 deg) but masked to the German land area, so ~35 % of
its bounding box holds no cell and rounding to the nearest step is not enough —
sites on the Oder border would land in a hole. The join is therefore an exact
nearest-neighbour search (scipy cKDTree) with longitude scaled by cos(latitude),
so "nearest" means nearest on the ground.

Output columns mirror the reference repository's contract so the orchestration
code is shared:

    PointID, NUTS_ID, NUTS_NAME, STATE_NAME, Latitude, Longitude,
    nearest_grid_id, nearest_latitude, nearest_longitude, distance_deg

``nearest_grid_id`` is ``C<col>R<row>``. ``NUTS_NAME`` is filled from the NUTS-3
code where the site tables carry no name column (the Brandenburg tables carry
``vNUTSID``/``vSTATE_ID``/``vSTATE_NAME`` only).

Usage:
    python orchestration/build_point_grid.py                 # write data/raw/point_to_nearest_grid.csv
    python orchestration/build_point_grid.py --check         # validate an existing mapping
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "orchestration"))


def _load_cfg() -> dict:
    return yaml.safe_load((REPO_ROOT / "orchestration" / "experiments.yaml").read_text())


def load_hyras_grid(json_path: Path) -> pd.DataFrame:
    """The HYRAS cell centres as a DataFrame of (lat, lon, row, col)."""
    raw = json.loads(json_path.read_text())
    lat = np.fromiter((e[0][0] for e in raw), dtype=float, count=len(raw))
    lon = np.fromiter((e[0][1] for e in raw), dtype=float, count=len(raw))
    row = np.fromiter((e[1][0] for e in raw), dtype=np.int32, count=len(raw))
    col = np.fromiter((e[1][1] for e in raw), dtype=np.int32, count=len(raw))
    return pd.DataFrame({"lat": lat, "lon": lon, "row": row, "col": col})


def nearest_cells(sites: pd.DataFrame, grid: pd.DataFrame,
                  warn_deg: float = 0.02) -> pd.DataFrame:
    """Nearest HYRAS cell per site, by exact KD-tree search.

    The HYRAS grid is regular (0.01 deg) but **masked to the German land area**,
    so ~35 % of the bounding box has no cell. Snapping to the nearest grid step
    therefore lands in a hole for sites near water or the national border, which
    is why this is a real nearest-neighbour search and not a rounding.

    Longitude is scaled by cos(latitude) so "nearest" is nearest on the ground,
    not nearest in degrees — at 52.5 deg N a degree of longitude is 0.61 of a
    degree of latitude, and the Oder-border sites are exactly where that matters.

    Sites further than ``warn_deg`` from any cell are reported, not dropped: on
    the Brandenburg footprint these are the Oder valley sites just inside the
    German border, whose nearest German climate cell is up to ~7 km away. That is
    a property of the HYRAS domain, not an error, but it must not be invisible.
    """
    from scipy.spatial import cKDTree

    lat0 = float(np.deg2rad(sites["Latitude"].mean()))
    scale = float(np.cos(lat0))

    tree = cKDTree(np.column_stack([grid["lat"].to_numpy(),
                                    grid["lon"].to_numpy() * scale]))
    query = np.column_stack([sites["Latitude"].to_numpy(),
                             sites["Longitude"].to_numpy() * scale])
    dist, idx = tree.query(query, k=1)

    hit = grid.iloc[idx].reset_index(drop=True)
    out = sites.reset_index(drop=True).copy()
    out["nearest_grid_id"] = ["C{}R{}".format(c, r) for c, r
                              in zip(hit["col"].astype(int), hit["row"].astype(int))]
    out["nearest_latitude"] = hit["lat"].to_numpy()
    out["nearest_longitude"] = hit["lon"].to_numpy()
    out["distance_deg"] = dist

    far = out[out["distance_deg"] > warn_deg]
    if not far.empty:
        print(f"  NOTE: {len(far):,} site(s) are more than {warn_deg} deg "
              f"(~{warn_deg * 111:.1f} km) from the nearest HYRAS cell — "
              f"max {far['distance_deg'].max():.4f} deg.")
        print(f"        HYRAS is masked to the German land area, so sites on the "
              f"Oder border take the nearest cell inland. They are kept.")
    return out


def read_sites(cfg: dict) -> pd.DataFrame:
    """The union of every crop's site table — one row per PointID.

    All six crops currently share one 15 066-point table, but reading the union
    rather than one crop's file means adding a crop with a different footprint
    does not silently leave its extra points unmapped.
    """
    frames = []
    for crop in cfg["crops"]:
        path = REPO_ROOT / "simplace" / crop / "project" / f"sites_{crop}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path)
        frames.append(df[["vLocationID", "vlat", "vlon", "vNUTSID",
                          "vSTATE_ID", "vSTATE_NAME"]])
    sites = (pd.concat(frames, ignore_index=True)
             .drop_duplicates(subset="vLocationID")
             .sort_values("vLocationID")
             .reset_index(drop=True))
    return sites.rename(columns={"vLocationID": "PointID",
                                 "vlat": "Latitude",
                                 "vlon": "Longitude",
                                 "vNUTSID": "NUTS_ID",
                                 "vSTATE_NAME": "STATE_NAME"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="validate the existing mapping instead of rewriting it")
    args = ap.parse_args()

    cfg = _load_cfg()
    out_path = REPO_ROOT / cfg["paths"]["point_grid"]
    grid_json = Path(cfg["climate_root_hyras"]) / "latlon_to_rowcol.json"

    if args.check:
        if not out_path.exists():
            print(f"missing: {out_path}", file=sys.stderr)
            return 1
        pg = pd.read_csv(out_path)
        sites = read_sites(cfg)
        missing = set(sites["PointID"]) - set(pg["PointID"])
        print(f"{out_path.relative_to(REPO_ROOT)}: {len(pg):,} points, "
              f"{pg['nearest_grid_id'].nunique():,} distinct climate cells")
        print(f"  max snap distance: {pg['distance_deg'].max():.4f} deg")
        print(f"  sites not mapped:  {len(missing)}")
        return 0 if not missing else 1

    if not grid_json.exists():
        raise SystemExit(f"HYRAS grid index not found: {grid_json}")

    sites = read_sites(cfg)
    grid = load_hyras_grid(grid_json)
    print(f"sites: {len(sites):,}   HYRAS cells: {len(grid):,}")

    mapped = nearest_cells(sites, grid)
    # NUTS_NAME is not carried by the Brandenburg site tables; keep the column so
    # the schema matches the reference repo's contract, filled with the code.
    mapped["NUTS_NAME"] = mapped["NUTS_ID"]
    cols = ["PointID", "NUTS_ID", "NUTS_NAME", "STATE_NAME", "Latitude", "Longitude",
            "nearest_grid_id", "nearest_latitude", "nearest_longitude", "distance_deg"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mapped[cols].to_csv(out_path, index=False)

    print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    print(f"  {len(mapped):,} points -> {mapped['nearest_grid_id'].nunique():,} "
          f"distinct climate cells")
    print(f"  snap distance: max {mapped['distance_deg'].max():.4f} deg, "
          f"mean {mapped['distance_deg'].mean():.4f} deg")
    cols_used = mapped["nearest_grid_id"].str.split("R").str[0].str[1:].astype(int)
    rows_used = mapped["nearest_grid_id"].str.split("R").str[1].astype(int)
    print(f"  climate cell extent: C{cols_used.min()}..C{cols_used.max()}  "
          f"R{rows_used.min()}..R{rows_used.max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
