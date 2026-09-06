#!/usr/bin/env python
"""Build each crop's baseline project table, and the proj.xml header that reads it.

The Brandenburg 1 km workspace this repo was restructured from ran **one fixed
window with one fixed planting date for every site**: the simulation period and
``vIDPL`` were constants in ``solution.sol.xml``, and the project table was a
flat 15 066-row site list with no dates at all. That is enough for a single
scenario run and not enough for a scenario *matrix* — a baseline you can compare
a 2015-2100 projection against has to span the observed record year by year, and
its planting dates have to come from what was actually observed.

This script produces that table:

    project/project_<crop>.csv     one row per (site, window start year), `;`-delimited
    projectid;simulationid;vColumn;vRow;vLocationID;vlat;vlon;vNUTSID;vSTATE_ID;
    vSTATE_NAME;start_date;end_date;vIDPL

and rewrites ``project/project.proj.xml`` so its header declares the three new
columns (``startdate``, ``enddate``, ``vIDPL``). Those two artifacts are written
together **on purpose**: a project CSV whose columns do not match the header is
not an error SIMPLACE reports, it is a silent column shift.

Everything downstream reads this table:

* ``generate.py`` takes the baseline experiment from it directly, and derives the
  window length (``baseline_span_years``) and the site set from it for every
  historical/future experiment — so hist/future stay comparable with the
  baseline they are evaluated against.
* the district-median ``vIDPL`` used for hist/future is the median of *this*
  table's ``vIDPL``, so future management is anchored in observed practice.

## Planting dates

``vIDPL`` is the planting day-of-year. For the baseline it is **dynamic**: the
DWD-observed sowing DOY for that site's NUTS-3 district in that season
(``data_observed/phenology_<crop>.csv``). Observations are district-level and
have gaps — potato ends in 1990, maize starts in 1991 — so the fallback chain is:

    observed (district, season)  ->  district median  ->  global median

The fallback is counted and reported. A crop where most rows fall back to the
global median has a baseline whose "dynamic" management is nearly constant, and
that has to be visible before the results are interpreted.

## Windows

Winter crops are sown in autumn of year Y and harvested in Y+1, so their window
is ``Y-01-01 .. Y+1-12-31`` and the observation that supplies the sowing date is
the one filed under ``harvest_year = Y+1``. Spring and summer crops fit one
calendar year. Which crop is which comes from ``crops:`` in experiments.yaml
(``span_years``, ``sown_previous_autumn``).

Windows are written over the nominal baseline period; ``generate.py`` clamps them
to the weather actually on disk when it builds a run dir, so there is exactly one
place that decides what the weather record can support.

Usage:
    python orchestration/build_baseline_project.py --crop all
    python orchestration/build_baseline_project.py --crop winter_wheat --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

# Columns of the generated table, in order. The proj.xml header is written from
# this list, so the two cannot drift apart.
COLUMNS = ["projectid", "simulationid", "vColumn", "vRow", "vLocationID",
           "vlat", "vlon", "vNUTSID", "vSTATE_ID", "vSTATE_NAME",
           "start_date", "end_date", "vIDPL"]

# SIMPLACE variable id per CSV column, for the proj.xml <header>. `startdate` and
# `enddate` are the solution's own variable names — supplying them from the
# project table is what overrides the solution's fixed period per row.
HEADER_VARS = [
    ("projectid", "CHAR", 'key="projectid"'),
    ("simulationid", "CHAR", 'key="simulationid"'),
    ("vColumn", "INT", ""),
    ("vRow", "INT", ""),
    ("vLocationID", "INT", ""),
    ("vlat", "DOUBLE", ""),
    ("vlon", "DOUBLE", ""),
    ("vNUTSID", "CHAR", ""),
    ("vSTATE_ID", "CHAR", ""),
    ("vSTATE_NAME", "CHAR", ""),
    ("startdate", "DATE", ""),
    ("enddate", "DATE", ""),
    ("vIDPL", "INT", ""),
]


def phenology_path(crop: str) -> Path:
    """The crop's observed phenology table.

    ``maize`` keeps the DWD name (``phenology_maize.csv``) while its folder in the
    old workspace was ``grain_maize``; the restructured tree uses ``maize``
    throughout, so the two now agree and this is a plain lookup with a fallback
    for any crop whose observation file was named differently.
    """
    d = REPO_ROOT / "simplace" / crop / "data_observed"
    direct = d / f"phenology_{crop}.csv"
    if direct.exists():
        return direct
    hits = sorted(d.glob("phenology_*.csv"))
    if len(hits) == 1:
        return hits[0]
    raise FileNotFoundError(f"no unambiguous phenology file for {crop} in {d}: {hits}")


def sowing_lookup(crop: str) -> tuple[dict, dict, int]:
    """(district, season) -> sowing DOY, plus the district and global medians."""
    df = pd.read_csv(phenology_path(crop))
    need = {"NUTS_ID", "harvest_year", "sowing_doy"}
    if not need.issubset(df.columns):
        raise RuntimeError(f"{phenology_path(crop)} lacks {need - set(df.columns)}")
    df = df.dropna(subset=["sowing_doy"])
    per_season = {(n, int(y)): int(round(d)) for n, y, d
                  in df[["NUTS_ID", "harvest_year", "sowing_doy"]].itertuples(index=False)}
    per_nuts = (df.groupby("NUTS_ID")["sowing_doy"].median()
                .round().astype(int).to_dict())
    global_median = int(round(df["sowing_doy"].median()))
    return per_season, per_nuts, global_median


def build(crop: str, cfg: dict) -> tuple[pd.DataFrame, dict]:
    crop_cfg = cfg["crops"][crop]
    span = int(crop_cfg["span_years"])
    autumn_sown = bool(crop_cfg["sown_previous_autumn"])
    period = cfg["periods"]["baseline"]

    sites = pd.read_csv(REPO_ROOT / "simplace" / crop / "project" / f"sites_{crop}.csv")
    per_season, per_nuts, global_median = sowing_lookup(crop)

    # Optional thinning, for a cheaper matrix while a workflow is being proven.
    stride = int(cfg.get("points", {}).get("stride", 1) or 1)
    if stride > 1:
        sites = sites.iloc[::stride].reset_index(drop=True)

    years = list(range(int(period["start"]), int(period["end"]) - span + 1))
    base = sites[["vColumn", "vRow", "vLocationID", "vlat", "vlon",
                  "vNUTSID", "vSTATE_ID", "vSTATE_NAME"]].copy()
    rep = base.loc[base.index.repeat(len(years))].reset_index(drop=True)
    rep["year"] = years * len(base)

    # The observation that supplies the sowing date is filed under the HARVEST
    # year, which for an autumn-sown crop is the year after the window opens.
    harvest_year = rep["year"] + (1 if autumn_sown else 0)

    keys = list(zip(rep["vNUTSID"], harvest_year))
    idpl, source = [], []
    for (nuts, hy) in keys:
        v = per_season.get((nuts, int(hy)))
        if v is not None:
            idpl.append(v); source.append("observed"); continue
        v = per_nuts.get(nuts)
        if v is not None:
            idpl.append(v); source.append("district_median"); continue
        idpl.append(global_median); source.append("global_median")

    out = pd.DataFrame({
        "projectid": range(1, len(rep) + 1),
        "simulationid": "C" + rep["vColumn"].astype(str) + "R" + rep["vRow"].astype(str),
        "vColumn": rep["vColumn"],
        "vRow": rep["vRow"],
        "vLocationID": rep["vLocationID"],
        "vlat": rep["vlat"],
        "vlon": rep["vlon"],
        "vNUTSID": rep["vNUTSID"],
        "vSTATE_ID": rep["vSTATE_ID"],
        "vSTATE_NAME": rep["vSTATE_NAME"],
        "start_date": rep["year"].astype(str) + "-01-01",
        "end_date": (rep["year"] + span).astype(str) + "-12-31",
        "vIDPL": idpl,
    })
    # Location-contiguous: SIMPLACE writes one output file per location, so the
    # cluster runner splits work on location boundaries. A table interleaved by
    # year would make every split unsafe.
    out = out.sort_values(["vLocationID", "start_date"]).reset_index(drop=True)
    out["projectid"] = range(1, len(out) + 1)

    counts = pd.Series(source).value_counts().to_dict()
    stats = {
        "rows": len(out), "points": out["vLocationID"].nunique(),
        "years": f"{years[0]}-{years[-1] + span}", "window_years": span + 1,
        "idpl_source": counts,
        "idpl_range": (int(out["vIDPL"].min()), int(out["vIDPL"].max())),
    }
    return out[COLUMNS], stats


def render_proj_xml(text: str, crop: str) -> str:
    """Point the projectdata interface at project_<crop>.csv and rewrite its header.

    The delimiter also changes: the legacy site tables were comma-delimited, and
    the generated tables are `;`-delimited (matching the reference project so the
    two repos' tooling is interchangeable, and so a NUTS name containing a comma
    cannot shift a column).
    """
    text = re.sub(
        r'(<interface id="projectdata".*?<divider>)[^<]*(</divider>)',
        r'\1;\2', text, flags=re.DOTALL)
    text = re.sub(
        r'(<interface id="projectdata".*?<filename>)[^<]*(</filename>)',
        rf'\1${{_WORKDIR_}}/project/project_{crop}.csv\2', text, flags=re.DOTALL)

    header = "\n".join(
        f'\t\t\t\t<var id="{vid}" datatype="{dt}"{" " + extra if extra else ""} />'
        for vid, dt, extra in HEADER_VARS)
    new_text, n = re.subn(
        r'(<resource id="proj" interface="projectdata">\s*<header>).*?(</header>)',
        lambda m: f"{m.group(1)}\n{header}\n\t\t\t{m.group(2)}",
        text, flags=re.DOTALL)
    if n != 1:
        raise RuntimeError(f"project header not rewritten cleanly (matched {n}x)")
    return new_text


def main() -> int:
    cfg = yaml.safe_load((REPO_ROOT / "orchestration" / "experiments.yaml").read_text())
    crops = list(cfg["crops"])

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crop", default="all", help="crop, comma list, or 'all'")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    picked = crops if args.crop == "all" else [c.strip() for c in args.crop.split(",")]
    bad = [c for c in picked if c not in crops]
    if bad:
        ap.error(f"unknown crop(s): {bad}; choose from {crops}")

    for crop in picked:
        df, st = build(crop, cfg)
        src = st["idpl_source"]
        obs = src.get("observed", 0)
        frac = obs / st["rows"] if st["rows"] else 0.0
        print(f"{crop:16s} rows={st['rows']:>9,}  points={st['points']:>6,}  "
              f"{st['years']}  window={st['window_years']}y  "
              f"vIDPL {st['idpl_range'][0]}-{st['idpl_range'][1]}  "
              f"observed={frac:5.1%}")
        for k in ("district_median", "global_median"):
            if src.get(k):
                print(f"{'':16s}   fallback {k}: {src[k]:,} rows "
                      f"({src[k] / st['rows']:.1%})")
        if frac < 0.5:
            print(f"{'':16s}   NOTE: most rows fall back to a median, so this "
                  f"baseline's management is near-constant, not year-by-year.")

        if args.dry_run:
            continue

        crop_dir = REPO_ROOT / "simplace" / crop / "project"
        out_csv = crop_dir / f"project_{crop}.csv"
        df.to_csv(out_csv, sep=";", index=False)

        proj = crop_dir / "project.proj.xml"
        proj.write_text(render_proj_xml(proj.read_text(), crop))
        print(f"{'':16s}   wrote {out_csv.relative_to(REPO_ROOT)} "
              f"({out_csv.stat().st_size / 1e6:.1f} MB) + project.proj.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
