#!/usr/bin/env python
"""Generate isolated, reproducible run directories for the Brandenburg climate + CO2 matrix.

One experiment = (crop, climate). For each, this builds a self-contained run dir
under ``simplace/<crop>/runs/<exp_id>/`` so that all 17 experiments per crop can
be generated and submitted without clobbering each other:

    runs/<exp_id>/
      solution/solution.sol.xml   (rendered: the crop's solution minus the outputs
                                   this run does not write — see outputs.daily)
      data/{crop,management,slim,soilcnp,soil} -> symlinks to the crop's shared inputs
      data/co2/co2.csv            (real file: the CO2 forcing for this climate)
      project/project.proj.xml    (templated: weather path + divider per climate)
      project/project.csv         (generated: period + grid + vIDPL management)
      config.yaml                 (the `cluster:` block for simplace_runner_cluster.py)
      MANIFEST.json               (what this run reads and writes — checked afterwards
                                   by orchestration/check_runs.py)
      out/                        (created by the runner)

``data/crop`` stays a symlink to the crop's shared inputs, so the calibrated
``crop.xml`` that ``calibrate.py promote`` writes is what every run reads: the
production matrix never carries its own stale copy of the parameters. Its
digest is recorded in MANIFEST.json so a finished run can still prove which
parameters it ran with.

There is **no soil-scenario dimension** in this project. Soil is a fixed property
of the Brandenburg 1 km sites, so ``data/soil`` is a symlink like the other
shared inputs rather than a per-experiment staged file. CO2 *is* staged per
experiment, because it is the one input the climate scenario changes.

Climate contracts, which differ by source:
  * DWD baseline:  ${_DATADIR_}/${vRow}/daily_mean_RES1_C${vColumn}R${vRow}.csv.gz,
                   TAB-delimited, gzip, foldered by ROW. Uses the DWD grid already
                   baked into the crop's baseline project table.
  * HYRAS (OBS + 5 GCMs): foldered by COLUMN, plain comma-delimited .csv with the
                   model/scenario/date-range in the filename. Uses the grid in
                   data/raw/point_to_nearest_grid.csv, which is a *different* grid
                   — see orchestration/build_point_grid.py.

vIDPL management:
  * baseline  -> dynamic per observed season (already in the baseline project table)
  * hist/fut  -> median vIDPL per NUTS-3 district, computed from that same table,
                 so projected management is anchored in observed practice.

Three properties of a hist/future project table are taken from the crop's own
baseline table rather than configured, so every experiment stays comparable with
the baseline it is evaluated against:
  * window length  -> winter_wheat/winter_rapeseed span 2 calendar years
                      (Y-01-01 .. Y+1-12-31), the four spring/summer crops 1.
                      See baseline_span_years().
  * site set       -> the PointIDs the crop actually has inputs for, not every row
                      of point_to_nearest_grid.csv. See baseline_points().
  * last start year-> pulled back by the span so the final window ends inside
                      the climate period.

Usage:
  python orchestration/generate.py --list-climates
  python orchestration/generate.py --crop maize --climate DWD
  python orchestration/generate.py --crop maize --climate GFDL-ESM4_ssp370 --dry-run
  python orchestration/generate.py --crop all --climate all
  python orchestration/generate.py --crop winter_wheat --climate all --no-daily
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

# Repo root derived from this file's location (orchestration/generate.py), so the
# checkout can be moved or cloned anywhere without editing config. Overridable via
# the BRANDENBURG_SCENARIOS_ROOT env var or an explicit `repo_root:` in
# experiments.yaml.
REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV = "BRANDENBURG_SCENARIOS_ROOT"


def resolve_repo_root(cfg: dict) -> Path:
    """Repo root: explicit config > env var > this file's location.

    A stale absolute `repo_root` is the one failure that does not announce itself —
    if an older copy of the checkout still exists (and the Brandenburg_1KM_*
    workspaces under /beegfs/halder/SIMPLACE_WDIR are exactly that), every run
    silently reads and writes *there*. So an explicitly configured root must
    actually look like this repo, or we refuse it.
    """
    raw = cfg.get("repo_root") or os.environ.get(ROOT_ENV) or "auto"
    if str(raw).strip().lower() in ("", "auto", "none"):
        return REPO_ROOT
    root = Path(raw).expanduser().resolve()
    if not (root / "simplace").is_dir() or not (root / "climate" / "co2").is_dir():
        raise SystemExit(
            f"configured repo_root does not look like this repo: {root}\n"
            f"  (no simplace/ + climate/co2/ inside it).  Set `repo_root: auto` in "
            f"experiments.yaml to derive it from the checkout location ({REPO_ROOT}).")
    return root


# --- DWD weather contract (baseline) ---------------------------------------
DWD_WEATHER = "${_DATADIR_}/${vRow}/daily_mean_RES1_C${vColumn}R${vRow}.csv.gz"
DWD_DIVIDER = None  # whitespace/tab -> SIMPLACE self-closing <divider />

# Shared crop input subdirs that are symlinked. Soil is here, not staged: this
# project has no soil-scenario dimension.
SHARED_DATA_SUBDIRS = ["crop", "management", "slim", "soilcnp", "soil"]

# Locations included in the generated config_smoke.yaml. Enough to exercise every
# input path (weather, soil, co2, management) on one node in a few minutes.
SMOKE_LOCATIONS = 3

# `frequence="DAILY"` on an <output> is what makes SIMPLACE write one row per
# simulated day per site. For the production matrix that is the dominant cost:
# a winter-wheat future experiment is ~15 066 sites x ~86 windows x 730 days,
# i.e. ~10^9 rows, against ~1.3 M rows of yearly output for the same run. The
# analysis in notebooks/04_evaluation reads the yearly table only, so daily
# output is turned off per run (`outputs.daily: false`) rather than per crop —
# calibration still needs it, and the shared solution is left untouched.
DAILY_FREQUENCE = re.compile(r'\bfrequence\s*=\s*"DAILY"', re.IGNORECASE)


@dataclass
class Climate:
    id: str
    kind: str            # "baseline" | "historical" | "future"
    mount_data: str      # bound to /data; weather paths are relative to it
    weather_path: str    # SIMPLACE filename template (uses ${_DATADIR_} ${vColumn} ${vRow})
    divider: str | None  # None -> whitespace; "," -> comma
    start: int
    end: int
    idpl_rule: str       # "dynamic" | "nuts_median"
    grid: str            # "baseline" (reuse the crop's table) | "hyras"
    co2_file: str        # which climate/co2/*.csv is staged as data/co2/co2.csv


def build_climate_registry(cfg: dict) -> dict[str, Climate]:
    """The 17 climate sources described by experiments.yaml.

    1 DWD baseline + 1 HYRAS OBS + 5 GCM historical + 5 GCM x 2 SSP future.

    Each carries the CO2 record it must be run with. Binding CO2 to the climate
    here — rather than leaving it to whoever writes the config — is what stops an
    SSP run from silently experiencing the observed record.
    """
    root = cfg["climate_root_hyras"]
    hist = cfg["periods"]["historical"]
    fut = cfg["periods"]["future"]
    base = cfg["periods"]["baseline"]
    co2_obs = cfg["co2"]["observed"]
    co2_ssp = cfg["co2"]["by_ssp"]
    reg: dict[str, Climate] = {}

    # 1) DWD baseline observations.
    reg["DWD"] = Climate(
        id="DWD", kind="baseline", mount_data=cfg["climate_dwd"],
        weather_path=DWD_WEATHER, divider=DWD_DIVIDER,
        start=int(base["start"]), end=int(base["end"]),
        idpl_rule="dynamic", grid="baseline", co2_file=co2_obs,
    )

    # 2) HYRAS OBS — the bias-correction reference, on the HYRAS grid.
    reg["HYRAS_OBS"] = Climate(
        id="HYRAS_OBS", kind="historical", mount_data=f"{root}/OBS",
        weather_path=("${_DATADIR_}/${vColumn}/"
                      f"obs_{hist['datestr']}_C${{vColumn}}R${{vRow}}.csv"),
        divider=",", start=hist["start"], end=hist["end"],
        idpl_rule="nuts_median", grid="hyras", co2_file=co2_obs,
    )

    # 3) 5 GCMs x historical.
    for m in cfg["gcms"]:
        reg[f"{m}_historical"] = Climate(
            id=f"{m}_historical", kind="historical",
            mount_data=f"{root}/{m}/historical",
            weather_path=("${_DATADIR_}/${vColumn}/"
                          f"{m}_historical_{hist['datestr']}_C${{vColumn}}R${{vRow}}.csv"),
            divider=",", start=hist["start"], end=hist["end"],
            idpl_rule="nuts_median", grid="hyras", co2_file=co2_obs,
        )

    # 4) 5 GCMs x {ssp126, ssp370} future — each with its own CO2 pathway.
    for m in cfg["gcms"]:
        for ssp in cfg["ssps"]:
            reg[f"{m}_{ssp}"] = Climate(
                id=f"{m}_{ssp}", kind="future",
                mount_data=f"{root}/{m}/{ssp}",
                weather_path=("${_DATADIR_}/${vColumn}/"
                              f"{m}_{ssp}_{fut['datestr']}_C${{vColumn}}R${{vRow}}.csv"),
                divider=",", start=fut["start"], end=fut["end"],
                idpl_rule="nuts_median", grid="hyras", co2_file=co2_ssp[ssp],
            )
    return reg


# --- weather coverage -------------------------------------------------------
# A simulation window that runs past the end of its weather file is not caught by
# anything: SIMPLACE reads until the rows run out and dies with a
# NullPointerException on the first missing day. The nominal period in
# experiments.yaml (and in the HYRAS *filenames*) is therefore not trustworthy on
# its own, so probe the data and keep only whole windows.
_COVERAGE_CACHE: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}


def weather_file_for(climate: Climate, col: int, row: int) -> Path:
    """Resolve the SIMPLACE weather template to a real path on disk."""
    rel = (climate.weather_path
           .replace("${_DATADIR_}", str(climate.mount_data))
           .replace("${vColumn}", str(col))
           .replace("${vRow}", str(row)))
    return Path(rel)


def probe_coverage(climate: Climate, col: int, row: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last date actually present in this climate's weather files.

    All cells of a source share one time axis, so one representative file is
    enough; the result is cached per climate id.
    """
    if climate.id in _COVERAGE_CACHE:
        return _COVERAGE_CACHE[climate.id]

    path = weather_file_for(climate, col, row)
    if not path.exists():
        raise FileNotFoundError(
            f"weather file missing for climate {climate.id}: {path}\n"
            f"  (probed with vColumn={col}, vRow={row})")

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        lines = fh.read().splitlines()
    sep = climate.divider or None          # None -> any whitespace
    body = [l for l in lines[1:] if l.strip()]
    first = pd.Timestamp(body[0].split(sep)[0].strip())
    last = pd.Timestamp(body[-1].split(sep)[0].strip())
    _COVERAGE_CACHE[climate.id] = (first, last)
    return first, last


def probe_value_ranges(climate: Climate, col: int, row: int) -> dict:
    """Min/max of the temperature columns of one representative weather file.

    Date coverage is not enough to trust a source. In the reference project an
    entire GCM scenario shipped with the Kelvin->Celsius conversion applied twice
    (TempMin around -270 C): the files existed, the dates spanned the full period,
    generation had no reason to object, and SIMPLACE then produced no output at
    all while still writing completion markers. A bad *value range* is invisible
    unless something looks, so this looks — cheaply, on one file, at generation
    time. Returns {} for a source whose columns it does not recognise.
    """
    path = weather_file_for(climate, col, row)
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, sep=climate.divider or r"\s+", engine="python", nrows=20000)
    except Exception:
        return {}
    out = {}
    for name in ("TempMin", "TempMean", "TempMax"):
        if name in df.columns:
            col_vals = pd.to_numeric(df[name], errors="coerce")
            col_vals = col_vals[col_vals > -900]      # -999 is the missing sentinel
            if len(col_vals):
                out[name] = (float(col_vals.min()), float(col_vals.max()))
    return out


def implausible_temperatures(ranges: dict) -> list[str]:
    """Names of temperature columns outside anything physically credible for Germany."""
    bad = []
    for name, (lo, hi) in ranges.items():
        if lo < -60.0 or hi > 60.0:
            bad.append(f"{name} {lo:.1f}..{hi:.1f} C")
    return bad


def clamp_to_coverage(df: pd.DataFrame, cov: tuple[pd.Timestamp, pd.Timestamp]) -> tuple[pd.DataFrame, int]:
    """Drop simulation windows not fully inside the weather record.

    Dropped, not truncated: a window cut short never reaches harvest, and the
    yearly output only fires on HarvestManagement.DoHarvest, so a truncated window
    would contribute nothing but would still look like a successful simulation.
    """
    first, last = cov
    keep = (pd.to_datetime(df["start_date"]) >= first) & (pd.to_datetime(df["end_date"]) <= last)
    out = df.loc[keep].copy()
    out["projectid"] = range(1, len(out) + 1)
    return out, int((~keep).sum())


def calendar_drift(climate: Climate, cov: tuple[pd.Timestamp, pd.Timestamp]) -> int:
    """Days between the climate's nominal start and the data's actual start.

    Large drift means a no-leap (365-day) model calendar was re-stamped onto
    consecutive real dates: the offset grows through the record, so a sowing date
    fixed by day-of-year lands progressively earlier in the real season. That is a
    scientific problem in the source data, not something generation can repair —
    it is surfaced so it cannot be missed.
    """
    if climate.grid == "baseline":
        return 0
    return int(abs((cov[0] - pd.Timestamp(f"{climate.start}-01-01")).days))


# --- project.proj.xml templating -------------------------------------------
def render_proj_xml(template_text: str, climate: Climate) -> str:
    """Rewrite the project-data CSV path and the weather interface for a climate."""
    text = re.sub(
        r"(<interface id=\"projectdata\".*?<filename>)[^<]*(</filename>)",
        r"\1${_WORKDIR_}/project/project.csv\2",
        template_text, flags=re.DOTALL,
    )

    divider_tag = "<divider />" if climate.divider is None else f"<divider>{climate.divider}</divider>"

    def _weather(match: re.Match) -> str:
        head = match.group(1)   # up to and including <poolsize>...</poolsize>
        return (f"{head}\n\t\t\t{divider_tag}"
                f"\n\t\t\t<filename>{climate.weather_path}</filename>\n\t\t")

    text, n = re.subn(
        r"(<interface id=\"weatherfile\"[^>]*>.*?</poolsize>).*?(?=</interface>)",
        _weather, text, flags=re.DOTALL,
    )
    if n != 1:
        raise RuntimeError(f"weatherfile interface not rewritten cleanly (matched {n}x)")
    return text


# --- solution rendering -----------------------------------------------------
def render_solution(template_text: str, keep_daily: bool) -> tuple[str, list[str]]:
    """Return the run's solution, with the DAILY outputs removed unless kept.

    The crop's own ``solution/solution.sol.xml`` is the calibration solution and
    stays as it is: the calibration diagnostics plot simulated LAI and DVS curves
    and need the daily table. A production run does not — nothing downstream of
    ``consolidate_outputs.py`` reads it — so the run dir gets a *rendered copy*
    rather than the symlink it used to get, exactly like ``data/co2/co2.csv``:
    what the experiment was run with is recorded in the experiment.

    Removing the ``<output>`` leaves its ``<interface>`` referenced by nothing, so
    that goes too — otherwise SIMPLACE still creates the (empty) ``daily/``
    directory it points at. An interface is only dropped when the id it declares
    no longer appears anywhere else in the file.

    Returns (text, removed_output_ids). Raises if the result is not parseable XML
    or if no <output> survived at all — a solution with nothing left to write
    still simulates every site, quietly, which is the failure mode this whole
    file exists to prevent.
    """
    if keep_daily:
        return template_text, []

    removed: list[str] = []
    interfaces: list[str] = []

    def _drop(match: re.Match) -> str:
        head = match.group(1)
        if not DAILY_FREQUENCE.search(head):
            return match.group(0)
        oid = re.search(r'id="([^"]+)"', head)
        iface = re.search(r'interface="([^"]+)"', head)
        removed.append(oid.group(1) if oid else "?")
        if iface:
            interfaces.append(iface.group(1))
        return (f'<!-- output {removed[-1]} (frequence=DAILY) removed by '
                f'orchestration/generate.py: outputs.daily is off for this run -->')

    text = re.sub(r"(<output\b[^>]*>).*?</output>", _drop, template_text, flags=re.DOTALL)

    for iface in interfaces:
        # The interface declaration itself contributes one occurrence of the id.
        # Anything more means something still reads or writes through it.
        if len(re.findall(rf'"{re.escape(iface)}"', text)) > 1:
            continue
        text = re.sub(rf'\s*<interface id="{re.escape(iface)}"[^>]*>.*?</interface>',
                      f'\n\t\t<!-- interface {iface} removed with its DAILY output -->',
                      text, flags=re.DOTALL)

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RuntimeError(f"rendered solution is not valid XML: {exc}") from exc
    kept = [o.get("id") for o in root.iter("output")]
    if not kept:
        raise RuntimeError(
            "rendered solution declares no <output> at all — SIMPLACE would run "
            "every site to completion and write nothing.")
    return text, removed


def write_or_replace(path: Path, text: str) -> None:
    """Write a real file where a symlink from an older generation may still sit."""
    if path.is_symlink() or path.exists():
        path.unlink()
    path.write_text(text)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit(repo: Path) -> str | None:
    """Short HEAD, when there is a git to ask. Provenance, never a requirement."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True)
    except (OSError, FileNotFoundError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def calibration_state(repo: Path, crop: str) -> dict:
    """Best iteration + objective per stage, straight from the calibration ledger.

    Recorded in the run manifest so a finished experiment says which calibration
    produced the parameters it ran with, instead of only which file it read.
    """
    out = {}
    for stage in ("phenology", "growth"):
        state = repo / "optimization" / "calibration" / crop / stage / "state.json"
        if not state.exists():
            continue
        try:
            s = json.loads(state.read_text())
        except (OSError, ValueError):
            continue
        best = repo / "optimization" / "calibration" / crop / stage / "best_crop.xml"
        out[stage] = {
            "best_iteration": s.get("best_iteration"),
            "best_objective": s.get("best_objective"),
            "iterations": s.get("n_iterations"),
            "updated": s.get("updated"),
            "best_crop_sha256": sha256(best) if best.exists() else None,
        }
    return out


# --- project.csv generation -------------------------------------------------
def nuts_median_idpl(baseline_csv: Path) -> tuple[dict[str, int], int]:
    """Median planting day-of-year per NUTS-3 district, from the baseline table."""
    df = pd.read_csv(baseline_csv, sep=";", usecols=["vNUTSID", "vIDPL"])
    per_nuts = df.groupby("vNUTSID")["vIDPL"].median().round().astype(int).to_dict()
    global_median = int(round(df["vIDPL"].median()))
    return per_nuts, global_median


def parse_grid(grid_id: str) -> tuple[int, int]:
    """'C794R269' -> (794, 269)."""
    m = re.fullmatch(r"C(\d+)R(\d+)", str(grid_id).strip())
    if not m:
        raise ValueError(f"bad grid id: {grid_id!r}")
    return int(m.group(1)), int(m.group(2))


def baseline_span_years(baseline_csv: Path) -> int:
    """Calendar years a simulation window spans, read off the crop's baseline table.

    Winter crops are sown in autumn of year Y and harvested in summer of Y+1, so
    their windows run Y-01-01 .. (Y+1)-12-31 (span 1); spring and summer crops fit
    in one calendar year (span 0). Read from the data rather than re-declared here,
    because getting it wrong is silent: a winter crop cut off at 31 Dec of the
    sowing year never reaches harvest, and the yearly output only fires on
    HarvestManagement.DoHarvest, so the run "succeeds" with header-only files.
    """
    df = pd.read_csv(baseline_csv, sep=";", usecols=["start_date", "end_date"])
    spans = (pd.to_datetime(df["end_date"]).dt.year
             - pd.to_datetime(df["start_date"]).dt.year).unique()
    if len(spans) != 1:
        raise RuntimeError(f"{baseline_csv} mixes window lengths: {sorted(spans)}")
    return int(spans[0])


def baseline_sites(baseline_csv: Path) -> pd.DataFrame:
    """One row per site the crop actually has inputs for.

    point_to_nearest_grid.csv may carry sites a given crop has no location or
    fertilizer row for. Simulating those would fail for want of an input, and
    would also make the baseline and hist/future site sets non-comparable — so
    the baseline table, not the grid mapping, decides who is simulated.

    The per-site attributes (lat/lon, district, state) come from here too, so a
    hist/future table carries exactly what the baseline carries.
    """
    df = pd.read_csv(baseline_csv, sep=";",
                     usecols=["vLocationID", "vlat", "vlon", "vNUTSID",
                              "vSTATE_ID", "vSTATE_NAME", "vIDPL"])
    return df.drop_duplicates(subset="vLocationID").reset_index(drop=True)


def build_hyras_project(point_grid_csv: Path, baseline_csv: Path,
                        climate: Climate) -> pd.DataFrame:
    """One row per (site, start year) over the climate period; vIDPL = district median.

    Window length and site set both come from the crop's baseline table, so a
    hist/future experiment simulates the same crop cycle over the same sites as
    the baseline it will be compared against.
    """
    pg = pd.read_csv(point_grid_csv, usecols=["PointID", "nearest_grid_id"])
    per_nuts, global_median = nuts_median_idpl(baseline_csv)
    span = baseline_span_years(baseline_csv)

    sites = baseline_sites(baseline_csv)
    pg = pg[pg["PointID"].isin(set(sites["vLocationID"]))]
    merged = sites.merge(pg, left_on="vLocationID", right_on="PointID", how="left")
    missing = merged["nearest_grid_id"].isna().sum()
    if missing:
        raise RuntimeError(
            f"{missing} baseline site(s) absent from {point_grid_csv.name}. "
            f"Re-run: python orchestration/build_point_grid.py")

    cols = merged["nearest_grid_id"].map(parse_grid)
    merged["vColumn"] = [c for c, _ in cols]
    merged["vRow"] = [r for _, r in cols]
    merged["vIDPL_med"] = merged["vNUTSID"].map(per_nuts).fillna(global_median).astype(int)

    # Last window must end inside the climate period, so a span-1 crop stops one
    # start-year early rather than running off the end of the weather file.
    years = list(range(climate.start, climate.end - span + 1))
    rep = merged.loc[merged.index.repeat(len(years))].reset_index(drop=True)
    rep["year"] = years * len(merged)

    out = pd.DataFrame({
        "projectid": range(1, len(rep) + 1),
        "simulationid": rep["nearest_grid_id"],
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
        "vIDPL": rep["vIDPL_med"],
    })
    # Location-contiguous: the cluster runner splits work on location boundaries,
    # because SIMPLACE writes one output file per location.
    return out.sort_values(["vLocationID", "start_date"]).reset_index(drop=True)


# --- run-dir assembly -------------------------------------------------------
def link_or_replace(src: Path, dst: Path) -> None:
    if dst.is_symlink() or dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    dst.symlink_to(src)


def generate(crop: str, climate: Climate, cfg: dict, dry_run: bool = False,
             keep_daily: bool | None = None) -> dict:
    repo = resolve_repo_root(cfg)
    crop_dir = repo / "simplace" / crop
    exp_id = climate.id
    run_dir = crop_dir / cfg["paths"]["runs_subdir"] / exp_id

    baseline_csv = crop_dir / "project" / f"project_{crop}.csv"
    co2_src = repo / cfg["paths"]["co2_dir"] / climate.co2_file
    proj_template_path = crop_dir / "project" / "project.proj.xml"
    solution_src = crop_dir / "solution" / "solution.sol.xml"

    if keep_daily is None:
        keep_daily = bool(cfg.get("outputs", {}).get("daily", False))

    plan = {
        "exp_id": exp_id, "crop": crop, "climate": climate.id,
        "run_dir": str(run_dir), "mount_data": climate.mount_data,
        "grid": climate.grid, "idpl_rule": climate.idpl_rule,
        "co2": climate.co2_file,
        "period": f"{climate.start}-{climate.end}",
        "daily_output": keep_daily,
    }

    for need in (baseline_csv, co2_src, proj_template_path, solution_src):
        if not need.exists():
            raise FileNotFoundError(
                f"{need}\n"
                f"  baseline tables are built by orchestration/build_baseline_project.py")

    # Probe the weather before doing any work: cached per climate, fails loudly if
    # the source is missing, and --dry-run should surface a bad calendar or a bad
    # value range before an experiment is ever submitted.
    if climate.grid == "baseline":
        head = pd.read_csv(baseline_csv, sep=";", usecols=["vColumn", "vRow"], nrows=1)
        probe_col, probe_row = int(head["vColumn"][0]), int(head["vRow"][0])
    else:
        head = pd.read_csv(repo / cfg["paths"]["point_grid"],
                           usecols=["nearest_grid_id"], nrows=1)
        probe_col, probe_row = parse_grid(head["nearest_grid_id"][0])
    cov = probe_coverage(climate, probe_col, probe_row)
    plan["coverage"] = f"{cov[0].date()}..{cov[1].date()}"
    plan["drift_days"] = calendar_drift(climate, cov)
    plan["bad_ranges"] = implausible_temperatures(
        probe_value_ranges(climate, probe_col, probe_row))

    if dry_run:
        plan["status"] = "dry-run (nothing written)"
        return plan

    # Directory skeleton + symlinks to shared inputs.
    (run_dir / "project").mkdir(parents=True, exist_ok=True)
    (run_dir / "data" / "co2").mkdir(parents=True, exist_ok=True)
    (run_dir / "out").mkdir(parents=True, exist_ok=True)
    (run_dir / "solution").mkdir(parents=True, exist_ok=True)
    # The solution is rendered, not symlinked: which outputs this experiment
    # writes is a property of the experiment. data/crop stays a symlink, so the
    # promoted (calibrated) crop.xml is picked up without regenerating anything.
    solution_text, dropped_outputs = render_solution(solution_src.read_text(), keep_daily)
    write_or_replace(run_dir / "solution" / "solution.sol.xml", solution_text)
    plan["dropped_outputs"] = dropped_outputs
    for sub in SHARED_DATA_SUBDIRS:
        link_or_replace(crop_dir / "data" / sub, run_dir / "data" / sub)

    # CO2 forcing (real file, not a symlink — the run dir records what it was run
    # with). Every crop solution reads data/co2/co2.csv; which record lands there
    # is what makes an SSP run actually experience SSP CO2.
    shutil.copyfile(co2_src, run_dir / "data" / "co2" / "co2.csv")

    # Project table.
    out_csv = run_dir / "project" / "project.csv"
    if climate.grid == "baseline":
        df = pd.read_csv(baseline_csv, sep=";")
    else:
        df = build_hyras_project(repo / cfg["paths"]["point_grid"], baseline_csv, climate)

    df, dropped = clamp_to_coverage(df, cov)
    if df.empty:
        raise RuntimeError(f"{exp_id}: no simulation window fits inside "
                           f"{cov[0].date()}..{cov[1].date()}")
    df.to_csv(out_csv, sep=";", index=False)

    # CO2 record must cover every month of every window, or the (year, month)
    # lookup is a NullPointerException on the first uncovered day.
    co2 = pd.read_csv(run_dir / "data" / "co2" / "co2.csv")
    co2_span = (int(co2["year"].min()), int(co2["year"].max()))
    win = (int(df["start_date"].min()[:4]), int(df["end_date"].max()[:4]))
    if win[0] < co2_span[0] or win[1] > co2_span[1]:
        raise RuntimeError(
            f"{exp_id}: CO2 record {climate.co2_file} covers {co2_span[0]}-{co2_span[1]} "
            f"but the windows span {win[0]}-{win[1]}. A month with no row is a "
            f"NullPointerException, not a gap.")
    plan["co2_span"] = f"{co2_span[0]}-{co2_span[1]}"
    plan["co2_ppm"] = (f"{co2[co2['year'] == win[0]]['average'].mean():.0f}"
                       f"->{co2[co2['year'] == win[1]]['average'].mean():.0f} ppm")

    span = baseline_span_years(baseline_csv)
    plan["rows"] = len(df)
    plan["points"] = df["vLocationID"].nunique()
    plan["window_years"] = span + 1
    plan["dropped"] = dropped
    plan["period"] = (f"{df['start_date'].min()[:4]}-{df['end_date'].max()[:4]} "
                      f"({plan['window_years']}-year windows)")

    # Templated proj.xml (weather path + divider for this climate).
    (run_dir / "project" / "project.proj.xml").write_text(
        render_proj_xml(proj_template_path.read_text(), climate))

    # Cluster config consumed by simplace/runners/simplace_runner_cluster.py.
    s = cfg["slurm"]
    cluster_cfg = {"cluster": {
        "exp_name": exp_id,
        "work_dir": str(run_dir),
        "output_dir": "out/",
        "solution": "solution/solution.sol.xml",
        "project": "project/project.proj.xml",
        "input_csv": str(out_csv),
        "mount_data": climate.mount_data,
        "singularity_image": s["singularity_image"],
        "debug": False,
        "testrun": False,
        "num_tasks_per_node": s["num_tasks_per_node"],
        "num_nodes": s["num_nodes"],
        "cpus_per_node": s.get("cpus_per_node", 80),
        "partition": s["partition"],
        "walltime": s["walltime"],
        "start_line": 1,
    }}
    with open(run_dir / "config.yaml", "w") as fh:
        yaml.safe_dump(cluster_cfg, fh, sort_keys=False)

    # Smoke config: same inputs, first few locations only, one node. Generated
    # rather than hand-written so it cannot drift from the experiment it tests.
    # exp_name is prefixed so a smoke run cannot overwrite real output.
    smoke_locs = df["vLocationID"].unique()[:SMOKE_LOCATIONS]
    smoke_cfg = {"cluster": dict(cluster_cfg["cluster"],
                                 exp_name=f"SMOKE_{exp_id}",
                                 num_nodes=1,
                                 num_tasks_per_node=2,
                                 walltime="00:20:00",
                                 end_line=int(df["vLocationID"].isin(smoke_locs).sum()))}
    with open(run_dir / "config_smoke.yaml", "w") as fh:
        yaml.safe_dump(smoke_cfg, fh, sort_keys=False)

    # Run manifest. `check_runs.py` verifies a finished experiment against this:
    # which CO2 record was staged, which crop.xml (i.e. which calibration) the run
    # read, which outputs the solution was allowed to write, and how many sites
    # and windows were asked for. Written last, so its presence means the run dir
    # was assembled completely.
    manifest = {
        "exp_id": exp_id,
        "crop": crop,
        "climate": {
            "id": climate.id, "kind": climate.kind,
            "mount_data": climate.mount_data,
            "weather_path": climate.weather_path,
            "coverage": plan["coverage"],
            "idpl_rule": climate.idpl_rule,
            "grid": climate.grid,
        },
        "co2": {
            "record": climate.co2_file,
            "source": str(co2_src),
            "sha256": sha256(co2_src),
            "span": plan["co2_span"],
            "ppm": plan["co2_ppm"],
        },
        "project": {
            "rows": plan["rows"], "points": plan["points"],
            "period": plan["period"], "window_years": plan["window_years"],
            "dropped_windows": plan["dropped"],
        },
        "outputs": {
            "daily": keep_daily,
            "removed": dropped_outputs,
            "yearly_dir": str(run_dir / "out" / exp_id / "yearly"),
        },
        "inputs": {
            "crop_xml": str(crop_dir / "data" / "crop" / "crop.xml"),
            "crop_xml_sha256": sha256(crop_dir / "data" / "crop" / "crop.xml"),
            "solution_source_sha256": sha256(solution_src),
        },
        "calibration": calibration_state(repo, crop),
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": git_commit(repo),
    }
    (run_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")

    plan["status"] = "generated"
    plan["submit"] = (f"python simplace/runners/simplace_runner_cluster.py "
                      f"{run_dir / 'config.yaml'}")
    plan["smoke"] = (f"python simplace/runners/simplace_runner_cluster.py "
                     f"{run_dir / 'config_smoke.yaml'}")
    return plan


def write_campaign_script(path: Path, listing: Path, repo: Path, cfg: dict,
                          n_exp: int) -> dict:
    """One sbatch script that holds its nodes for the whole campaign.

    The per-experiment path (``submit_*.sh``) submits fresh SLURM jobs for every
    experiment, so the nodes are handed back between experiments and the next one
    queues behind whatever else arrived meanwhile — on a busy partition that wait
    dominates the wall-clock. This script instead asks for the nodes once and runs
    every experiment sequentially *inside* that allocation as srun job steps
    (``simplace_runner_cluster.py --mode alloc``). Nothing is released until the
    last experiment is done.

    The cost is one large allocation: it starts only when the whole node set is
    free at once, and its walltime must cover every experiment end to end.
    Anything not reached is left for a resumed submission (SIMPLACE_RESUME=1),
    which is why each experiment writes a completion marker.
    """
    s = cfg["slurm"]
    nodes = int(s.get("campaign_nodes", s["num_nodes"]))
    tasks = int(s["num_tasks_per_node"])
    cpus_per_node = int(s.get("cpus_per_node", 80))
    cpus_per_task = max(1, cpus_per_node // tasks)
    walltime = str(s.get("campaign_walltime", "24:00:00"))
    mem_per_cpu = s.get("mem_per_cpu")
    logdir = repo / "simplace" / "runs_submit" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)

    # Memory has to be requested per CPU, or the first srun step on a node claims
    # all of it and the sibling steps stall inside our own allocation.
    mem_line = f"#SBATCH --mem-per-cpu={mem_per_cpu}\n" if mem_per_cpu else ""

    path.write_text(f"""#!/bin/bash
#SBATCH --job-name=simplace_{path.stem}
#SBATCH --partition={s['partition']}
#SBATCH --nodes={nodes}
#SBATCH --ntasks-per-node={tasks}
#SBATCH --cpus-per-task={cpus_per_task}
{mem_line}#SBATCH --time={walltime}
#SBATCH --output={logdir}/{path.stem}-%j.out
#
# Generated by orchestration/generate.py — {n_exp} experiment(s) in ONE allocation.
#
# {nodes} node(s) x {tasks} task(s) x {cpus_per_task} cpu(s) are allocated once, up
# front, and held until the last experiment finishes. Each experiment runs inside
# this allocation as srun job steps (simplace_runner_cluster.py --mode alloc);
# no experiment submits its own job, so none of them ever waits in the queue
# again. Submit with:  sbatch {path.name}
#
# Resume an interrupted campaign (skips experiments that wrote a completion
# marker):  sbatch --export=ALL,SIMPLACE_RESUME=1 {path.name}
set -uo pipefail
cd "{repo}"

LIST="{listing}"

# Preflight: a config that no longer exists means the run dir was regenerated
# under a different name or removed. Fail before burning allocation time.
while read -r crop cfgfile; do
  [ -n "${{crop:-}}" ] || continue
  [ -f "$cfgfile" ] || {{ echo "missing config: $cfgfile" >&2; exit 1; }}
done < "$LIST"

RUNNER_FLAGS=()
[ "${{SIMPLACE_RESUME:-0}}" = "1" ] && RUNNER_FLAGS+=(--skip-completed)

echo "[campaign] job $SLURM_JOB_ID  nodes=$SLURM_JOB_NUM_NODES  start $(date)"
trap 'echo "[campaign] terminating (walltime or scancel) at $(date)"' TERM

failed=0
done_n=0
# fd 3 so the runner cannot swallow the experiment list from stdin.
while read -r crop cfgfile <&3; do
  [ -n "${{crop:-}}" ] || continue
  echo "[campaign] === $cfgfile ($(date +%T)) ==="
  python "simplace/runners/simplace_runner_cluster.py" "$cfgfile" --mode alloc \\
      ${{RUNNER_FLAGS[@]+"${{RUNNER_FLAGS[@]}}"}}
  rc=$?
  case $rc in
    0) done_n=$((done_n + 1)) ;;
    3) echo "[campaign] not enough walltime left — stopping cleanly." \\
            "Resubmit with SIMPLACE_RESUME=1 to finish the rest."; break ;;
    *) failed=$((failed + 1)); echo "[campaign] FAILED (rc=$rc): $cfgfile" ;;
  esac
done 3< "$LIST"

echo "[campaign] finished $done_n/{n_exp} experiment(s), $failed failed, $(date)"
[ "$failed" -eq 0 ]
""")
    path.chmod(0o755)
    return {"nodes": nodes, "tasks": tasks, "cpus_per_task": cpus_per_task,
            "walltime": walltime, "logdir": logdir}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(Path(__file__).with_name("experiments.yaml")))
    ap.add_argument("--crop")
    ap.add_argument("--climate")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-climates", action="store_true")
    ap.add_argument("--daily", dest="daily", action="store_true", default=None,
                    help="keep the DAILY outputs in the generated run dirs "
                         "(default: whatever `outputs.daily` says in the config)")
    ap.add_argument("--no-daily", dest="daily", action="store_false",
                    help="drop every frequence=DAILY output — yearly output only")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    registry = build_climate_registry(cfg)

    if args.list_climates:
        print(f"{len(registry)} climate sources:")
        for c in registry.values():
            print(f"  {c.id:24s} {c.kind:11s} {c.start}-{c.end:<6d} "
                  f"idpl={c.idpl_rule:12s} co2={c.co2_file}")
        return 0

    missing = [n for n in ("crop", "climate") if not getattr(args, n)]
    if missing:
        ap.error(f"--{', --'.join(missing)} required (or use --list-climates)")

    def resolve(value: str, universe: list[str], what: str) -> list[str]:
        if value == "all":
            return list(universe)
        picked = [v.strip() for v in value.split(",")]
        bad = [v for v in picked if v not in universe]
        if bad:
            ap.error(f"unknown {what}: {bad}; choose from {universe}")
        return picked

    crops = resolve(args.crop, list(cfg["crops"]), "crop")
    climates = resolve(args.climate, list(registry), "climate")

    plans = []
    for crop in crops:
        for clim in climates:
            plan = generate(crop, registry[clim], cfg, args.dry_run,
                            keep_daily=args.daily)
            plans.append(plan)
            extra = ""
            if "rows" in plan:
                extra = (f"  rows={plan['rows']:,}  points={plan['points']:,}"
                         f"  {plan['period']}  CO2 {plan['co2']} {plan['co2_ppm']}"
                         f"  outputs={'daily+yearly' if plan['daily_output'] else 'yearly'}")
                if plan["dropped"]:
                    extra += f"  dropped={plan['dropped']:,}"
            print(f"  [{plan['status']:>9s}] {crop:16s} {clim:22s}{extra}")

    print(f"\n{len(plans)} experiment(s) processed.")

    # Source-data problems are properties of the climate, not of this run, so
    # report them once at the end rather than burying them in per-experiment lines.
    bad = sorted({(p["climate"], "; ".join(p["bad_ranges"]))
                  for p in plans if p.get("bad_ranges")})
    if bad:
        print("\nWARNING — implausible temperatures in the weather source:")
        for cid, detail in bad:
            print(f"  {cid:24s} {detail}")
        print("  SIMPLACE will run and may write nothing at all while still\n"
              "  reporting success. Do not submit these until the source is fixed.")

    drifted = sorted({(p["climate"], p["coverage"], p["drift_days"])
                      for p in plans if p.get("drift_days", 0) > 15})
    if drifted:
        print("\nWARNING — weather does not start where its filename claims:")
        for cid, coverage, days in drifted:
            print(f"  {cid:24s} covers {coverage}  ({days} days off nominal start)")
        print("  A no-leap model calendar re-stamped onto real dates drifts through\n"
              "  the record, so a day-of-year sowing rule lands progressively earlier\n"
              "  in the real season. Windows past the data end were dropped, but the\n"
              "  seasonal misalignment cannot be fixed here — confirm the intended\n"
              "  handling with whoever produced the dataset before using these runs.")

    if not args.dry_run:
        repo = resolve_repo_root(cfg)
        submit_dir = repo / "simplace" / "runs_submit"
        submit_dir.mkdir(parents=True, exist_ok=True)

        # Name the script after its content, not its selection, so successive
        # full-matrix calls cannot silently overwrite each other's script.
        configs = [f"{p['run_dir']}/config.yaml" for p in plans]
        digest = hashlib.sha1("\n".join(sorted(configs)).encode()).hexdigest()[:8]
        label = "-".join(x for x in (
            crops[0] if len(crops) == 1 else f"{len(crops)}crops",
            climates[0] if len(climates) == 1 else f"{len(climates)}clim") if x)
        script = submit_dir / f"submit_{label}_{digest}.sh"

        # Bounded concurrency. Each runner takes num_nodes nodes and BLOCKS until
        # they finish, so running all of them at once would oversubscribe the
        # partition and leave one squeue-poller per experiment hammering slurmctld.
        total = int(cfg["slurm"].get("cluster_nodes", 100))
        per_exp = int(cfg["slurm"]["num_nodes"])
        par = max(1, total // per_exp)

        listing = submit_dir / f"{script.stem}.list"
        listing.write_text("".join(f"{p['crop']} {p['run_dir']}/config.yaml\n"
                                   for p in plans))

        script.write_text(f"""#!/bin/bash
# Generated by orchestration/generate.py — {len(plans)} experiment(s).
#
# Each line of {listing.name} is one experiment. The runner submits that
# experiment's SLURM jobs ({per_exp} nodes each) and blocks until they finish, so
# they are driven {par} at a time: {par} x {per_exp} = {par * per_exp} nodes, against a
# partition of {total}. Do NOT background every line instead — that oversubscribes
# the partition and starts one squeue poller per experiment.
#
# NOTE: this path releases its nodes after every experiment, so each one queues
# again from scratch. To hold the nodes for the whole set instead, submit
# campaign_{label}_{digest}.sbatch (generated alongside this script).
set -euo pipefail
cd "{repo}"

while read -r crop cfgfile; do
  [ -f "$cfgfile" ] || {{ echo "missing config: $cfgfile" >&2; exit 1; }}
done < "{listing}"

xargs -P {par} -L1 -a "{listing}" \\
  sh -c 'python simplace/runners/simplace_runner_cluster.py "$1" --mode sbatch'
""")
        script.chmod(0o755)

        campaign = submit_dir / f"campaign_{label}_{digest}.sbatch"
        geom = write_campaign_script(campaign, listing, repo, cfg, len(plans))
        slots = geom["nodes"] * geom["tasks"]

        print(f"\nCampaign script (one allocation, held throughout): {campaign}")
        print(f"  allocation:      {geom['nodes']} nodes x {geom['tasks']} tasks x "
              f"{geom['cpus_per_task']} cpus = {slots} concurrent SIMPLACE steps")
        print(f"  walltime:        {geom['walltime']} for all {len(plans)} "
              f"experiment(s), run sequentially inside the one allocation")
        print(f"  run it with:     sbatch {campaign}")
        print(f"  resume:          sbatch --export=ALL,SIMPLACE_RESUME=1 {campaign}")
        print(f"  job log:         {geom['logdir']}/{campaign.stem}-<jobid>.out")

        print(f"\nPer-experiment submit script (nodes released between "
              f"experiments): {script}")
        print(f"  experiment list: {listing}")
        print(f"  concurrency:     {par} experiment(s) x {per_exp} nodes = "
              f"{par * per_exp}/{total} nodes")
        print(f"  run it with:     bash {script}")
        if plans:
            print(f"  smoke test one:  {plans[0]['smoke']}")

        # Submit scripts are cheap to regenerate but expensive to trust when stale.
        stale = []
        candidates = sorted(submit_dir.glob("submit_*.sh")) + \
            sorted(submit_dir.glob("campaign_*.sbatch"))
        for s_path in candidates:
            if s_path in (script, campaign):
                continue
            text = s_path.read_text()
            manifest = s_path.with_suffix(".list")
            if not manifest.exists():
                named = re.search(r"(/\S+\.list)", text)
                manifest = Path(named.group(1)) if named else manifest
            refs = ([l.split()[-1] for l in manifest.read_text().splitlines() if l.strip()]
                    if manifest.exists()
                    else re.findall(r"/\S+/config\.yaml", text))
            gone = [r for r in refs if not Path(r).exists()]
            if gone:
                stale.append((s_path, len(gone), len(refs)))
        if stale:
            print("\nStale submit scripts (reference run dirs that no longer exist):")
            for s_path, gone, total_refs in stale:
                print(f"  {s_path}  ({gone}/{total_refs} missing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
