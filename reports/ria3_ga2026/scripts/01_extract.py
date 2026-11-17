"""Step 1 — reduce the consolidated SIMPLACE outputs to an analysis table.

The consolidated tables (data/processed/consolidated/<crop>/<exp>_yearly.csv.gz,
~24 GB gzipped) carry ~110 columns per site-season. The GA figures need ~25 of
them. This script reads each experiment once, keeps those columns, attaches
the site key (vLocationID, vNUTSID — see *Keying*), and writes one parquet per
experiment to reports/ria3_ga2026/data/sites/.

    python reports/ria3_ga2026/scripts/01_extract.py [--jobs 17]

Keying. The consolidated tables do not carry the PointID; it was the name of
each per-location file. It is recovered by joining `projectid` against the run
dir's project.csv — but a run dir regenerated *after* its simulation ran (this
happened to maize on 2026-10-12) holds a project.csv that no longer describes
the outputs. So every join is validated: the climate cell in the output's
`simulationid` and the harvest year must both agree with the project row. An
experiment that fails is rebuilt from its per-location files instead
(runs/<exp>/out/<exp>/yearly/<PointID>_yearly.csv), where the key is certain.
District membership always comes from data/raw/point_to_nearest_grid.csv.

A note on accumulation windows: every SUM/AVG output in the yearly record is
accumulated from the simulation start (1 Jan of the sowing year) to harvest.
For winter crops that window therefore includes the pre-sowing fallow months;
for spring/summer crops it is Jan .. harvest. Fluxes (rain, drainage, nitrate
leaching) are per *simulation window*, not per calendar year.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "data" / "processed" / "consolidated"
OUT = ROOT / "reports" / "ria3_ga2026" / "data" / "sites"

COLS = [
    "projectid", "simulationid", "Year", "DOY", "PlantingDOY", "AnthesisDOY", "MaturityDOY", "CO2",
    "Yield_t_ha", "AGBiomass_t_ha", "maxLAI", "Rain", "Tmax", "Tmin",
    "TRANRF", "NNI", "cropNuptake_kg_ha", "inputChemN_kg_ha",
    "NitrateLossSeepage_SUM_kg_ha", "WDRAIN_SUM", "ActualTranspiration",
    "ActualEvapotranspiration", "PotentialEvapotranspiration",
    "TotalCropAvailWaterContent_Avg", "DevStage",
]


def _read(src: Path, cols: list[str]) -> pd.DataFrame:
    types = {c: pa.float32() for c in cols}
    types.update(projectid=pa.int64(), Year=pa.int16(), DOY=pa.int16(), simulationid=pa.string())
    return pacsv.read_csv(
        src,
        parse_options=pacsv.ParseOptions(delimiter=";"),
        convert_options=pacsv.ConvertOptions(include_columns=cols, column_types=types),
    ).to_pandas()


def _from_consolidated(crop: str, exp: str) -> pd.DataFrame | str:
    """Consolidated table keyed through project.csv; a str return = why it failed."""
    df = _read(SRC / crop / f"{exp}_yearly.csv.gz", COLS)
    proj = pd.read_csv(
        ROOT / "simplace" / crop / "runs" / exp / "project" / "project.csv",
        sep=";", usecols=["projectid", "simulationid", "vLocationID", "start_date", "end_date"],
    )
    n0 = len(df)
    df = df.merge(proj, on="projectid", how="inner", suffixes=("", "_proj"),
                  validate="many_to_one")
    if len(df) != n0:
        return f"{n0 - len(df):,} rows have no projectid in project.csv"
    cell = df["simulationid"].str.split("__").str[-1]
    y0 = df["start_date"].str[:4].astype(int)
    y1 = df["end_date"].str[:4].astype(int)
    bad = (cell != df["simulationid_proj"]) | (df["Year"] < y0) | (df["Year"] > y1)
    if bad.any():
        return f"{int(bad.sum()):,} rows disagree with project.csv on cell/year"
    return df.drop(columns=["projectid", "simulationid", "simulationid_proj",
                            "start_date", "end_date"])


def _from_location_files(crop: str, exp: str) -> pd.DataFrame:
    ydir = ROOT / "simplace" / crop / "runs" / exp / "out" / exp / "yearly"
    cols = [c for c in COLS if c not in ("projectid", "simulationid")]
    parts = []
    for f in sorted(ydir.glob("*_yearly.csv")):
        if f.stat().st_size == 0:
            continue
        d = _read(f, cols)
        d["vLocationID"] = int(f.name.split("_")[0])
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def job(args: tuple[str, str]) -> str:
    crop, exp = args
    src = SRC / crop / f"{exp}_yearly.csv.gz"
    dst = OUT / crop / f"{exp}.parquet"
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return f"skip {crop}/{exp}"
    df = _from_consolidated(crop, exp)
    how = "consolidated"
    if isinstance(df, str):
        how = f"per-location files ({df})"
        df = _from_location_files(crop, exp)
    nuts = pd.read_csv(ROOT / "data" / "raw" / "point_to_nearest_grid.csv",
                       usecols=["PointID", "NUTS_ID"]).rename(
        columns={"PointID": "vLocationID", "NUTS_ID": "vNUTSID"})
    n0 = len(df)
    df = df.merge(nuts, on="vLocationID", how="inner", validate="many_to_one")
    if len(df) != n0:
        raise RuntimeError(f"{crop}/{exp}: {n0 - len(df)} rows with unknown PointID")
    df["vLocationID"] = df["vLocationID"].astype("int32")
    df["vNUTSID"] = df["vNUTSID"].astype("category")
    dst.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), dst, compression="zstd")
    return f"ok   {crop}/{exp}: {len(df):,} rows via {how}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=17)
    a = ap.parse_args()
    man = pd.read_csv(SRC / "manifest.csv")
    tasks = list(man[["crop", "exp_id"]].itertuples(index=False, name=None))
    with ProcessPoolExecutor(a.jobs) as ex:
        for msg in ex.map(job, tasks):
            print(msg, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
