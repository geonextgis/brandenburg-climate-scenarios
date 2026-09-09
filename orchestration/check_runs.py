#!/usr/bin/env python
"""Verify that generated experiments ran, and ran with what they were meant to.

A SIMPLACE experiment can finish with exit status 0 and still be wrong, and every
way it does so is quiet:

  * the CO2 record staged into the run dir is not the one the scenario calls for,
    so an SSP run experiences the observed atmosphere and the whole point of the
    matrix is lost;
  * the parameters moved after the run dir was generated (a calibration promoted
    in between), so half the matrix ran on one crop.xml and half on another;
  * a job step died and its slice of the sites simply has no output — which looks
    exactly like sites that never reached harvest, unless you look at whether the
    missing PointIDs form a contiguous block;
  * the yearly files exist but hold nothing but their header, the signature of a
    window that never reached HarvestManagement.DoHarvest.

So this checks the four things a finished experiment has to be able to prove:
what it read, what it was allowed to write, that it finished, and that what it
wrote is populated and internally consistent.

    python orchestration/check_runs.py --crop winter_wheat
    python orchestration/check_runs.py --crop winter_wheat --climate DWD --verbose
    python orchestration/check_runs.py --crop all --sample 10

Exit status: 0 if every experiment passes, 1 if any FAILed, 2 if the selection
matched no run dir at all.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import (  # noqa: E402  (same directory, not a package)
    build_climate_registry,
    render_solution,
    resolve_repo_root,
)

YEARLY_RE = re.compile(r"^(\d+)_yearly\.csv$")

# A run of this many consecutive missing locations is not physics. Job steps are
# split on location boundaries into num_nodes x num_tasks_per_node chunks — 400
# chunks over 15 066 sites is ~38 locations each — so a block this long means a
# step failed rather than that those particular sites never matured.
BLOCK_THRESHOLD = 25

# TODO outranks FAIL so an experiment that was never started cannot hide behind
# a warning from an experiment that was: "all runs completed" has to be false
# for both, but they need different things done about them.
OK, WARN, FAIL, TODO = "OK", "WARN", "FAIL", "TODO"
RANK = {OK: 0, WARN: 1, FAIL: 2, TODO: 3}


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    crop: str
    exp_id: str
    run_dir: Path
    checks: list[Check] = field(default_factory=list)
    summary: str = ""

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def status(self) -> str:
        return max((c.status for c in self.checks), key=lambda s: RANK[s], default=OK)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def yearly_files(yearly_dir: Path) -> list[tuple[int, os.DirEntry]]:
    """(PointID, dir entry) per location file. Sizes come free with the scandir."""
    out = []
    if not yearly_dir.is_dir():
        return out
    with os.scandir(yearly_dir) as it:
        for e in it:
            m = YEARLY_RE.match(e.name)
            if m and e.is_file():
                out.append((int(m.group(1)), e))
    out.sort()
    return out


def missing_blocks(expected: list[int], present: set[int]) -> list[tuple[int, int, int]]:
    """Maximal runs of consecutive *positions* in `expected` that have no output.

    Position, not PointID: the runner slices the project table by line, so a dead
    job step removes a contiguous stretch of the table's own ordering.
    Returns (first_index, last_index, length), longest first.
    """
    runs, start = [], None
    for i, loc in enumerate(expected):
        if loc not in present:
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i - 1, i - start))
            start = None
    if start is not None:
        runs.append((start, len(expected) - 1, len(expected) - start))
    runs.sort(key=lambda r: -r[2])
    return runs


def read_co2_column(path: Path, sep: str = ";") -> tuple[float, float] | None:
    """(min, max) of the yearly output's CO2 column for one location."""
    try:
        df = pd.read_csv(path, sep=sep)
    except Exception:
        return None
    col = next((c for c in df.columns if c.strip().upper() == "CO2"), None)
    if col is None or df.empty:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return (float(s.min()), float(s.max())) if not s.empty else None


def expected_co2_range(record: Path, years: tuple[int, int]) -> tuple[float, float]:
    """What the staged record says the crop should have experienced in those years."""
    df = pd.read_csv(record)
    sel = df[(df["year"] >= years[0]) & (df["year"] <= years[1])]["average"]
    return float(sel.min()), float(sel.max())


def check_experiment(crop: str, exp_id: str, run_dir: Path, cfg: dict, repo: Path,
                     registry: dict, sample: int) -> Report:
    rep = Report(crop, exp_id, run_dir)
    climate = registry.get(exp_id)

    # --- 1. the run dir is assembled ----------------------------------------
    manifest_path = run_dir / "MANIFEST.json"
    project_csv = run_dir / "project" / "project.csv"
    solution_path = run_dir / "solution" / "solution.sol.xml"
    config_path = run_dir / "config.yaml"
    for need in (config_path, project_csv, solution_path):
        if not need.exists():
            rep.add("assembled", FAIL, f"missing {need.relative_to(run_dir)}")
            return rep
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if manifest is None:
        rep.add("manifest", WARN,
                "no MANIFEST.json — run dir predates check_runs.py; "
                "regenerate it to make the provenance checks meaningful")

    # --- 2. what it read: CO2 record and crop parameters --------------------
    staged_co2 = run_dir / "data" / "co2" / "co2.csv"
    if climate is None:
        rep.add("co2", WARN, f"{exp_id} is not a climate in experiments.yaml")
    elif not staged_co2.exists():
        rep.add("co2", FAIL, "data/co2/co2.csv is not staged")
    else:
        want = repo / cfg["paths"]["co2_dir"] / climate.co2_file
        if sha256(staged_co2) != sha256(want):
            rep.add("co2", FAIL,
                    f"staged data/co2/co2.csv is NOT {climate.co2_file} — this "
                    f"climate ran on the wrong atmosphere")
        else:
            rep.add("co2", OK, climate.co2_file)

    crop_xml = repo / "simplace" / crop / "data" / "crop" / "crop.xml"
    crop_sha = sha256(crop_xml) if crop_xml.exists() else None
    if manifest and crop_sha:
        was = manifest.get("inputs", {}).get("crop_xml_sha256")
        if was and was != crop_sha:
            rep.add("parameters", FAIL,
                    "crop.xml changed since this run dir was generated — the run "
                    "did not use the parameters now in the repo (promote + "
                    "regenerate + rerun, or this experiment is not comparable)")
        else:
            rep.add("parameters", OK, f"crop.xml {crop_sha[:12]}")
    best = repo / "optimization" / "calibration" / crop / "growth" / "best_crop.xml"
    if crop_sha and best.exists() and sha256(best) != crop_sha:
        rep.add("promoted", WARN,
                "crop.xml differs from the growth stage's best_crop.xml — the "
                "calibration best was never promoted, or was superseded")

    # --- 3. what it was allowed to write ------------------------------------
    sol_text = solution_path.read_text()
    if solution_path.is_symlink():
        rep.add("solution", WARN, "solution is a symlink (pre-outputs-switch run dir)")
    daily_declared = re.findall(r'<output\b[^>]*frequence="DAILY"[^>]*>', sol_text)
    want_daily = bool(cfg.get("outputs", {}).get("daily", False))
    if manifest:
        want_daily = bool(manifest.get("outputs", {}).get("daily", want_daily))
    all_outputs = re.findall(r"<output\b[^>]*>", sol_text)
    harvest = [o for o in all_outputs if "DoHarvest" in o]
    if daily_declared and not want_daily:
        rep.add("outputs", FAIL, f"{len(daily_declared)} DAILY output(s) still declared")
    elif not harvest:
        rep.add("outputs", FAIL,
                "no output fires on HarvestManagement.DoHarvest — this run "
                "simulates every site and writes nothing")
    else:
        rep.add("outputs", OK, "daily+yearly" if daily_declared else "yearly only")

    # Drift: the shared solution may have been patched after generation.
    shared = repo / "simplace" / crop / "solution" / "solution.sol.xml"
    if shared.exists():
        rendered, _ = render_solution(shared.read_text(), keep_daily=want_daily)
        if rendered != sol_text:
            rep.add("solution drift", WARN,
                    "the crop's solution has changed since this run dir was "
                    "generated — rerun generate.py before submitting")

    daily_dir = run_dir / "out" / exp_id / "daily"
    n_daily = sum(1 for _ in daily_dir.iterdir()) if daily_dir.is_dir() else 0
    if n_daily and not want_daily:
        rep.add("daily files", FAIL, f"{n_daily:,} daily file(s) written into {daily_dir}")

    # --- 4. is the output there, and populated ------------------------------
    marker = run_dir / f".completed_{exp_id}"
    proj = pd.read_csv(project_csv, sep=";",
                       usecols=["vLocationID", "start_date", "end_date"])
    expected = list(dict.fromkeys(proj["vLocationID"].tolist()))
    windows = len(proj)
    yearly_dir = run_dir / "out" / exp_id / "yearly"
    files = yearly_files(yearly_dir)
    present = {loc for loc, _ in files}

    if not files:
        if marker.exists():
            rep.add("output", FAIL,
                    f"the experiment reported success but {yearly_dir} is empty — "
                    f"check the weather source's value ranges (generate.py "
                    f"--dry-run) and <run_dir>/log/")
        else:
            rep.add("output", TODO, "not run yet — no output and no completion marker")
        rep.summary = f"0/{len(expected):,} sites"
        return rep

    # Only worth saying once there is output to qualify: an experiment that never
    # started is a TODO above, not an experiment missing its marker.
    if not marker.exists():
        rep.add("completed", WARN,
                "output present but no completion marker — the campaign never "
                "finished this experiment, or it was run in sbatch mode (which "
                "writes none)")
    else:
        rep.add("completed", OK, marker.name)

    # Header-only files: exactly one line, i.e. a location that reached no
    # harvest in any of its windows.
    header_len = len(open(files[0][1].path, "rb").readline())
    empty = [loc for loc, e in files if e.stat().st_size <= header_len + 1]

    missing = [loc for loc in expected if loc not in present]
    blocks = missing_blocks(expected, present) if missing else []
    big = [b for b in blocks if b[2] >= BLOCK_THRESHOLD]
    coverage = len(present) / len(expected) if expected else 0.0

    if big:
        # Translate the position range back into project.csv data lines, which is
        # what the runner's start_line/end_line speak.
        line_of = proj.groupby("vLocationID", sort=False).size().cumsum().shift(
            fill_value=0) + 1
        detail = "; ".join(
            f"{b[2]} sites at lines "
            f"{int(line_of.iloc[b[0]])}-{int(line_of.iloc[b[1]])}" for b in big[:3])
        rep.add("site coverage", FAIL,
                f"{len(missing):,} site(s) with no output, in contiguous block(s) "
                f"— a job step failed, not physics: {detail}. Confirm with sacct, "
                f"then rerun the experiment.")
    elif missing:
        rep.add("site coverage", WARN,
                f"{len(missing):,}/{len(expected):,} site(s) never reached harvest "
                f"(scattered — physics, not a failed step)")
    else:
        rep.add("site coverage", OK, f"{len(present):,}/{len(expected):,} sites")

    if empty:
        rep.add("empty files", WARN if len(empty) < len(files) * 0.05 else FAIL,
                f"{len(empty):,} header-only file(s) — those windows never reached "
                f"DoHarvest")

    # --- 6. spot-check the content, including the CO2 the crop experienced ---
    step = max(1, len(files) // max(1, sample))
    picked = [e for _, e in files[::step]][:sample]
    seen_lo, seen_hi, rows = None, None, 0
    for e in picked:
        with open(e.path, "rb") as fh:
            rows += max(0, sum(1 for _ in fh) - 1)
        rng = read_co2_column(Path(e.path))
        if rng:
            seen_lo = rng[0] if seen_lo is None else min(seen_lo, rng[0])
            seen_hi = rng[1] if seen_hi is None else max(seen_hi, rng[1])

    if climate is not None and seen_lo is not None:
        years = (int(proj["start_date"].min()[:4]), int(proj["end_date"].max()[:4]))
        want_lo, want_hi = expected_co2_range(
            repo / cfg["paths"]["co2_dir"] / climate.co2_file, years)
        # The simulated range is a subset of the record's (sites do not span every
        # window), so it only has to sit inside it — but well inside means the
        # right pathway, and outside means the wrong file reached the model.
        if not (want_lo - 1 <= seen_lo and seen_hi <= want_hi + 1):
            rep.add("CO2 in output", FAIL,
                    f"output CO2 {seen_lo:.0f}-{seen_hi:.0f} ppm is outside the "
                    f"{climate.co2_file} range {want_lo:.0f}-{want_hi:.0f} ppm")
        else:
            rep.add("CO2 in output", OK,
                    f"{seen_lo:.0f}-{seen_hi:.0f} ppm (record {want_lo:.0f}-"
                    f"{want_hi:.0f})")
    elif seen_lo is None:
        rep.add("CO2 in output", WARN, "no CO2 column in the sampled yearly files")

    est = int(rows / max(1, len(picked)) * len(files))
    rep.summary = (f"{len(present):,}/{len(expected):,} sites  "
                   f"~{est:,} rows of {windows:,} windows  "
                   f"cov {coverage:6.1%}")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(Path(__file__).with_name("experiments.yaml")))
    ap.add_argument("--crop", default="all", help="crop, comma list, or 'all'")
    ap.add_argument("--climate", default="all", help="climate, comma list, or 'all'")
    ap.add_argument("--sample", type=int, default=5,
                    help="yearly files per experiment to open for the row and CO2 "
                         "checks (default 5)")
    ap.add_argument("--verbose", action="store_true",
                    help="print every check, not only WARN/FAIL")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    repo = resolve_repo_root(cfg)
    registry = build_climate_registry(cfg)
    runs_subdir = cfg.get("paths", {}).get("runs_subdir", "runs")

    def pick(value: str, universe: list[str]) -> list[str]:
        return list(universe) if value == "all" else [v.strip() for v in value.split(",")]

    crops = pick(args.crop, list(cfg["crops"]))
    climates = pick(args.climate, list(registry))

    reports: list[Report] = []
    for crop in crops:
        runs = repo / "simplace" / crop / runs_subdir
        if not runs.is_dir():
            continue
        for exp_id in climates:
            run_dir = runs / exp_id
            if not run_dir.is_dir():
                continue
            reports.append(check_experiment(crop, exp_id, run_dir, cfg, repo,
                                            registry, args.sample))

    if not reports:
        print("no run dirs matched — generate them first with "
              "orchestration/generate.py")
        return 2

    width = max(len(r.exp_id) for r in reports)
    for r in reports:
        print(f"  [{r.status:>4s}] {r.crop:14s} {r.exp_id:{width}s}  {r.summary}")
        for c in r.checks:
            if args.verbose or c.status != OK:
                print(f"           {c.status:>4s}  {c.name}: {c.detail}")

    n_fail = sum(1 for r in reports if r.status == FAIL)
    n_warn = sum(1 for r in reports if r.status == WARN)
    n_todo = sum(1 for r in reports if r.status == TODO)
    print(f"\n{len(reports)} experiment(s): {len(reports) - n_fail - n_warn - n_todo} "
          f"OK, {n_warn} with warnings, {n_fail} failed, {n_todo} not run.")
    if n_fail:
        print("A FAIL means the experiment must be rerun or regenerated — do not "
              "consolidate it.")
    if n_todo:
        print("TODO means the experiment has no output at all yet: resume the "
              "campaign with\n"
              "  sbatch --export=ALL,SIMPLACE_RESUME=1 "
              "simplace/runs_submit/campaign_<label>_<hash>.sbatch")
    return 1 if (n_fail or n_todo) else 0


if __name__ == "__main__":
    sys.exit(main())
