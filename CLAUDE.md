# Brandenburg Climate + CO₂ Scenario Framework

Crop-model (SIMPLACE / LINTUL5) simulation framework for evaluating crop response
to future climate **and rising atmospheric CO₂** on the Brandenburg 1 km site
grid, with agents driving the model calibration.

Six crops: winter wheat, winter rapeseed, spring barley, potato, maize,
sugar beet. They are calibrated in two stages — phenology first, then yield —
and the calibrated crops drive a 17-climate scenario matrix.

> **Paths are portable — do not hard-code the repo location.** The repo root is
> derived from the file that needs it: `orchestration/generate.py`,
> `orchestration/consolidate_outputs.py` and `optimization/common.py` all expose
> `resolve_repo_root()`, and all honour the `BRANDENBURG_SCENARIOS_ROOT`
> environment variable. Both config files set `repo_root: auto`.
>
> The predecessor workspaces still exist at
> `/beegfs/halder/SIMPLACE_WDIR/Brandenburg_1KM_*` (~280 GB, mostly `out/`).
> They are **not** this repo and nothing here writes to them. A stale absolute
> `repo_root` pointing at one would fail *silently*, which is why an explicit
> root is validated for `simplace/` + `climate/co2/` before it is accepted.

## What is different from the Germany-wide reference project

This repository's architecture is adapted from
`/data01/FDS/halder/soil-amelioration-scenarios`. Four differences matter for
every decision made here:

1. **No soil-scenario dimension.** Soil is a fixed property of the Brandenburg
   1 km sites. `data/soil/` is a symlinked shared input, not a staged per-run
   file, and the matrix is 17 experiments per crop, not 85.
2. **CO₂ is the scenario lever that was added.** See *CO₂ forcing* below — it
   was a hard-coded constant in the inherited solutions.
3. **Observations are at NUTS-3 district resolution**, not per site. Both the
   phenology and the yield objectives aggregate simulated sites to districts
   before scoring. There are 19 districts (Brandenburg + Berlin).
4. **The growth stage is yield-only.** The reference calibrated LAI and yield
   jointly; there are no LAI observations on these sites. See *Calibration*.

## Repository Layout

```
climate/co2/                   # CO2 scenario records — one copy, staged per run
data/
  raw/
    point_to_nearest_grid.csv  # 15 066 sites -> nearest HYRAS cell (generated)
    DE_DWD_UBN_Crop.csv        # raw DWD phenology record (shared, symlinked in)
  external/  interim/  processed/
docs/                          # design notes and the restructure record
notebooks/                     # 00_exploration .. 04_evaluation
orchestration/                 # experiments.yaml + the builders and the generator
optimization/                  # agentic calibration (phenology, then yield)
simplace/
  runners/                     # the shared cluster + local drivers
  <crop>/                      # one folder per crop (the simulation engine)
  runs_submit/                 # generated campaign/submit scripts + logs
```

### Per-crop folder (`simplace/<crop>/`)
- `project/sites_<crop>.csv`  — the 15 066-site inventory (**input**, tracked)
- `project/project_<crop>.csv` — the baseline table, one row per (site, season),
  with `start_date`, `end_date` and `vIDPL`. **Generated** by
  `orchestration/build_baseline_project.py`; ~70 MB.
- `project/project.proj.xml`  — SIMPLACE project definition (interfaces + header)
- `solution/solution.sol.xml` — SIMPLACE solution, CO₂-wired
- `data/`                     — model inputs (crop, soil, management, slim, soilcnp)
- `data_observed/`            — observed phenology / yield (district-level) and LAI
- `runs/<exp_id>/`            — generated run dirs, one per climate. Each holds its
  own `config.yaml` (+ `config_smoke.yaml`), `project/project.csv`, templated
  `project.proj.xml`, and a staged `data/co2/co2.csv`. Produced by
  `orchestration/generate.py` — do not hand-edit.
- `runs_optim/calib_<target>/` — isolated calibration run dirs (generated)
- `out/<EXP_NAME>/{daily,yearly}/` — simulation outputs

## Key Data Contracts

**`vLocationID` (= `PointID`) is the primary key** linking sites to climate cells
and to their district.

**Site inventory** (`project/sites_<crop>.csv`, `,`-delimited):
`projectid,simulationid,vColumn,vRow,vLocationID,vlat,vlon,vNUTSID,vSTATE_ID,vSTATE_NAME`
`vColumn`/`vRow` here are the **DWD** grid. All six crops share one 15 066-site set.

**Generated project table** (`project/project_<crop>.csv` and each run dir's
`project/project.csv`, `;`-delimited) adds three columns:
`...;start_date;end_date;vIDPL` — and the proj.xml header declares them as
`startdate`, `enddate`, `vIDPL`, which is what overrides the solution's own fixed
period and planting date per row. **The CSV column order and the header order
must match**; a mismatch is not an error SIMPLACE reports, it is a silent column
shift. Both are written by the same script for that reason.

**Site → climate cell** (`data/raw/point_to_nearest_grid.csv`):
`PointID, NUTS_ID, NUTS_NAME, STATE_NAME, Latitude, Longitude, nearest_grid_id,
nearest_latitude, nearest_longitude, distance_deg`, `nearest_grid_id` = `C<col>R<row>`.
The 15 066 sites map onto 13 424 distinct HYRAS cells. 361 sites along the Oder
are more than 2.2 km from their cell — HYRAS is masked to the German land area, so
border sites take the nearest cell inland. Rebuild with
`python orchestration/build_point_grid.py`.

**Weather interface** (from `project.proj.xml`) is rewritten per climate by
`generate.py`; `_DATADIR_` is bound to the climate source via `mount_data`.

## Climate Sources

- **DWD observations (baseline):**
  `/beegfs/common/data/climate/dwd/csvs/germany_ubn_1951-01-01_to_2024-08-30`
- **HYRAS bias-corrected CMIP (historical + future):**
  `/data01/FDS/muduchuru/Atmos/NEXGDDP_HYRAS_BC_CSV/<MODEL>/<SCENARIO>/<col>/...`
  - Models: `ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, MIROC6`, plus `OBS` (HYRAS).
  - Scenarios per GCM: `historical, ssp126, ssp370`.

The two sources differ in **layout and delimiter**: DWD is tab-delimited gzip
foldered by *row*; HYRAS is comma-delimited plain CSV foldered by *column*, and
on a different grid entirely. `generate.py` rewrites the `weatherfile` interface
(divider + filename) per climate, so the solution's own weather interface is
always overridden.

**Validate value ranges, not just date coverage, when a source is refreshed.**
`generate.py` probes both. The reference project lost 50 experiments to a GCM
delivery in which the Kelvin→Celsius conversion had been applied twice
(`TempMin` ≈ −270 °C): the files existed, the dates spanned the period, SIMPLACE
produced no output at all, and completion markers were written anyway. As of
2026-08-23 all 17 sources probe clean over the Brandenburg cells.

## CO₂ forcing

**This is the substantive model change in this repository.** The inherited
Brandenburg solutions drove radiation-use efficiency from a constant:

```xml
<var id="vCO2" datatype="DOUBLE">380</var>
<input id="cCO" source="vCO2"/>
```

380 ppm is roughly the year-2000 atmosphere. An ssp370 run to 2100 would have had
the temperature and precipitation of the scenario with none of the fertilisation,
and every projected yield change would have been climate-only — silently, not
deliberately.

`orchestration/patch_solution_co2.py` replaced it with a monthly record:

| element | what it does |
| --- | --- |
| `<interface id="co2observedfile">` | reads `${_WORKDIR_}/data/co2/co2.csv` |
| `<resource id="co2observed">` | DAILY frequency, keyed `(CURRENT.YEAR, CURRENT.MONTH)` |
| `<simcomponent id="CO2Supply">` | exposes the monthly value as a daily variable |
| `<input id="cCO" source="CO2Supply.CO2"/>` | feeds RadiationUseEfficiency |
| `CO2` in the daily + yearly output | records what the crop actually experienced |

From there CO₂ reaches growth through LINTUL5's own response: RUE is scaled by
interpolating `crop.COTableFactor` against `crop.COTableCo2` (both already
present in every `crop.xml`), and the component returns `RTMCO`, the CO₂
transpiration-ratio modifier that `LintulWaterStress` consumes. **So CO₂ acts on
assimilation and on water use** — which is why it matters most on Brandenburg's
sandy, water-limited soils.

The script is idempotent; `--check` reports whether each crop is CO₂-driven.

Which record is staged is decided by the climate, in the registry — not by
whoever writes a config. That binding is what stops an SSP run from experiencing
the observed record:

| climate | staged file | span |
| --- | --- | --- |
| DWD, HYRAS OBS, all GCM `historical` | `co2_mm_historical.csv` | 1951-01 … 2026-06 |
| `ssp126` / `ssp370` | `co2_mm_ssp126_future.csv` / `co2_mm_ssp370_future.csv` | 2015 … 2500 |

The resource does an exact `(year, month)` lookup on every simulated day, so **a
month with no row is a NullPointerException, not a gap**. `generate.py` refuses
to write a run dir whose windows extend past its CO₂ record.

`co2_mm_historical.csv` is **generated**, not raw: `co2_mm_observed.csv` is the
Mauna Loa record and starts 1958-03, seven years after the historical period
does. `orchestration/build_co2_historical.py` prepends 1951-01 … 1958-02 from the
Law Dome ice-core/firn spline (`data/external/law_dome_co2_spline_annual.csv`)
with a Mauna-Loa-derived seasonal cycle and a splice offset, and copies the
observed months through verbatim. Re-run it (`--check` to validate only) if the
observed record is updated.

The records live once, in `climate/co2/`, because CO₂ is a property of the
scenario and not of the crop.

## Experiment Matrix

| Type       | Period      | Climate                   | Scenarios | CO₂        | Management (`vIDPL`)             |
| ---------- | ----------- | ------------------------- | --------- | ---------- | -------------------------------- |
| Baseline   | 1979–2024   | DWD observations          | 1         | observed   | dynamic, per observed season     |
| Historical | 1951–2014   | HYRAS OBS + 5 GCMs        | 6         | observed   | district median                  |
| Future     | 2015–2100   | 5 GCMs × {SSP126, SSP370} | 10        | per SSP    | district median                  |
| **Total**  |             |                           | **17**    |            |                                  |

**17 climate scenarios × 6 crops = 102 experiments.**

Periods above are *nominal*. The actual windows written into each `project.csv`
are narrower, for two reasons `generate.py` handles automatically:

- **Window length is per crop.** `winter_wheat` and `winter_rapeseed` are sown in
  autumn of year Y and harvested in Y+1, so a window is `Y-01-01 .. Y+1-12-31`;
  the four spring/summer crops fit one calendar year. Length is read off the
  crop's own baseline table (`baseline_span_years`), never assumed. Getting this
  wrong is silent: a winter crop cut off at 31 Dec of the sowing year never
  reaches harvest, and the yearly output only fires on
  `HarvestManagement.DoHarvest`, so the run "succeeds" with header-only files.
- **Windows are clamped to the weather on disk** (`probe_coverage` +
  `clamp_to_coverage`). A window running past the end of its weather file dies
  with a NullPointerException. DWD stops on 2024-08-30, which pulls the baseline
  back to a last window of 2023 for spring crops and 2022 for winter crops.

**Scale.** This grid is ~5× denser than the reference project's. A baseline table
is ~680 000 rows (70 MB); a future experiment is ~1.3 M rows (130 MB). The full
matrix is roughly 10 GB of project tables before any output is written, and one
experiment can write up to 15 066 output files. Thin the site set with
`points: {stride: N}` in `experiments.yaml` when proving a workflow.

**A complete run is not 15 066 output files.** SIMPLACE writes
`out/<exp>/yearly/<PointID>_yearly.csv` only once that site reaches
`HarvestManagement.DoHarvest`, and one row per harvest — so a site that never
matures gets **no file at all**. To tell "never matured" from "the step crashed",
check whether the missing PointIDs are scattered (physics) or form a contiguous
`start_line`–`end_line` block (a failed job step), and confirm against `sacct`.

## Running Simulations

Generate the run dirs, then submit:

```bash
python orchestration/generate.py --crop all --climate all
sbatch simplace/runs_submit/campaign_<label>_<hash>.sbatch     # one held allocation
```

`generate.py` writes two drivers for the same experiment list. They differ in who
owns the nodes:

- **`campaign_<label>_<hash>.sbatch` (preferred).** One allocation of
  `slurm.campaign_nodes`, requested once and **held until the last experiment
  finishes**. Every experiment runs inside it as `nodes × num_tasks_per_node`
  concurrent `srun` job steps (`simplace_runner_cluster.py --mode alloc`), so no
  experiment is ever submitted and none re-queues. On a busy partition the
  re-queue wait is most of the wall-clock, which is the reason to prefer this.
  Costs: it starts only when `campaign_nodes` are free simultaneously, and
  `slurm.campaign_walltime` must cover all experiments end to end. Each
  experiment writes `.completed_<exp_id>` in its run dir, and the job refuses to
  start one it cannot finish (exit 3, clean stop) — resume with
  `sbatch --export=ALL,SIMPLACE_RESUME=1 campaign_....sbatch`.
- **`submit_<label>_<hash>.sh`.** The per-experiment path: each runner submits its
  own SLURM jobs, blocks, and **releases the nodes when that experiment ends**.
  It drives `slurm.cluster_nodes // slurm.num_nodes` experiments at a time. Do not
  background every line instead — that oversubscribes the partition and starts one
  `squeue` poller per experiment.

The cluster driver is shared, not duplicated per crop:

```bash
python simplace/runners/simplace_runner_cluster.py <run_dir>/config.yaml              # auto
python simplace/runners/simplace_runner_cluster.py <run_dir>/config.yaml --mode alloc # inside an allocation
```

`--mode auto` (the default) resolves in this order: an explicit `--jobid`; the
allocation we are running inside (only when `SLURM_JOB_NUM_NODES` is set, i.e. the
campaign job — `SLURM_JOB_ID` alone is not enough, a shell opened inside a
long-lived `salloc` inherits it); an allocation held by `hold_nodes.py`; otherwise
`sbatch`. Both modes split work **only on location boundaries** — SIMPLACE writes
one output file per location, so a location handled by two invocations clobbers
itself.

Smoke-test first with the run dir's `config_smoke.yaml` (3 locations, 1 node,
output namespaced `SMOKE_<exp_id>`).

Consolidate finished experiments into one table each with
`python orchestration/consolidate_outputs.py` — the per-location files are a poor
shape for analysis and a worse one for a shared filesystem.

## Rebuilding the inputs

A fresh clone does not contain the derived tables (they are gitignored). In order:

```bash
python orchestration/build_point_grid.py          # sites -> HYRAS cells
python orchestration/build_co2_historical.py      # 1951-01 .. 1958-02 reconstruction
python orchestration/patch_solution_co2.py --check       # confirm the solutions are CO2-driven
python orchestration/patch_crop_vernalisation.py --check # confirm the winter crops vernalise
python orchestration/build_baseline_project.py --crop all   # the baseline tables (~70 MB each)
python orchestration/generate.py --crop all --climate all
```

`data_observed/{phenology,yield,LAI}_<crop>.csv` come from
`notebooks/01_preprocessing/`.

## Calibration

**Two stages**, in this order:

1. **`phenology`** — thermal time (`TSUM1`, `TSUM2`, `TEFFMX`, …), calibrated
   from scratch. Everything downstream is dated off DVS, so the development clock
   is settled first and then frozen.
2. **`growth`** — **yield**, with the stage-1 phenology frozen.

**There is no optimizer.** No Optuna, no Bayesian search, no sampler. Every
parameter change comes from an agent that reads the diagnostics, names a
mechanism, and states what it expects to happen. Two agent runtimes drive the
same machinery:

- **Local (Ollama)** — `python optimization/agentic.py run --crop <crop> --target growth`.
  Agents in `optimization/agents/` talk to a local model server; nothing leaves
  the machine. `agentic.py check` reports whether Ollama is reachable and the
  configured models are pulled.
- **Claude Code** — `/calibrate-phenology`, `/calibrate-growth`, driven by the
  agents in `.claude/agents/`.

Both go through `optimization/calibrate.py`, the only path to `crop.xml`. It
validates against the constraints in `calibration.yaml`, verifies the freeze by
re-reading the written XML, mirrors the file into every view, runs SIMPLACE,
scores with `optimization/objectives.py` + `optimization/evaluation.py`, and
appends to `optimization/calibration/<crop>/<stage>/ledger.jsonl`.

```bash
python orchestration/hold_nodes.py hold --nodes 40 --walltime 08:00:00      # optional
python optimization/calibrate.py run     --crop <crop> --target phenology   # iterate
python optimization/calibrate.py promote --crop <crop> --target phenology --yes
python optimization/calibrate.py handoff --crop <crop>                      # seeds stage 2
python optimization/calibrate.py run     --crop <crop> --target growth      # iterate
python optimization/calibrate.py promote --crop <crop> --target growth --yes
python orchestration/hold_nodes.py release                                  # end of session
```

Nothing writes to `simplace/<crop>/data/crop/crop.xml` except
`calibrate.py promote --yes`; do not edit it by hand. `restore-baseline` puts a
stage's starting parameters back if a calibration goes somewhere useless.

Self-test, no cluster needed: `python optimization/test_calibrate.py`
(72 checks).
See `optimization/README.md` for the full contract and runbook.

### Two limitations to state, not to work around

These are properties of the data and the model as inherited. They are documented
where they bite (`optimization/config.yaml`, `optimization/calibration.yaml`,
`.claude/agents/growth-calibrator.md`) and they belong in any write-up of results.
A third — no vernalisation — was resolved on 2026-09-07; see below.

1. **The canopy is not observed.** The inherited `data_observed/LAI_<crop>.csv`
   is on the Germany-wide BZE point set, with **zero overlap** with the
   Brandenburg sites; `maize` and `sugar_beet` have no LAI file at all. So the
   growth stage scores yield only, and a canopy parameter moved there is measured
   only through the yield it produces. The `crop_reference` envelope (harvest
   index, above-ground biomass) in `calibration.yaml` is the only guard against
   fixing a yield error with an implausible canopy — check it every iteration.
   Restoring the joint stage needs an `LAI_<crop>.csv` keyed on Brandenburg
   PointIDs plus a `project_<crop>_LAI.csv`.

2. **Observed planting dates are sparse for some crops.** `vIDPL` in the baseline
   table is the DWD-observed sowing DOY for that district and season, falling back
   to the district median. `build_baseline_project.py` reports the fraction that
   is genuinely observed: winter wheat, winter rapeseed and sugar beet ~96 %,
   maize ~70 %, spring barley ~48 %, **potato ~26 %** (observations end in 1990).
   A crop mostly on the fallback has a baseline whose "dynamic" management is
   near-constant, which weakens any inference about management adaptation.

### Vernalisation (resolved 2026-09-07)

This was limitation #2 and it is worth keeping in view, because every result
produced before that date carries it. Both winter crops used to develop on pure
thermal time: no `crop.xml` defined `VBASE`/`VERSAT`/`VERNRT` and no solution
wired `cVBASE`/`cVERSAT`/`cVERNRT` into the LINTUL5 Phenology component. Since
vernalisation is the mechanism by which a warm winter *delays* a winter crop,
warming could only ever accelerate phenology, and projected winter-crop anthesis
was biased early under ssp370 with the yield effect biased optimistic.

`orchestration/patch_crop_vernalisation.py` turns it on (idempotent, `--check`
reports state). Per winter crop it makes four edits, and all four are required —
any three of them fail silently or fatally:

| edit | file | without it |
| --- | --- | --- |
| `IDSL` -> 2, `VERSAT`/`VBASE`/`VERNRT` added | `data/crop/crop.xml` | the component skips the whole vernalisation branch, **silently** |
| `<res>` for the three, in the `crop` resource | `solution/solution.sol.xml` | `NullPointerException` in `FWSimComponent.performLinks`, naming neither parameter nor component |
| `cVBASE`/`cVERSAT`/`cVERNRT` inputs to `Phenology` | `solution/solution.sol.xml` | the parameters are read but never reach the component |
| `VernalisationFactor` + `VERN` in the daily output | `solution/solution.sol.xml` | no way to audit whether vernalisation actually engaged |

`IDSL == 2` is the single gate in the component, and it enables the **photoperiod
response as well** — the two are not separable. Winter wheat moved 0 -> 2, so its
`PhotoperiodTableFactor` is now live; its table is flat (factor 1.0 above 8 h
daylength), so at 52-53 deg N the effect is ~1.0 except for a few midwinter days
at DVS ~0.1. Small, but not zero. Winter rapeseed was already `IDSL=2` — it had
been running the vernalisation branch with `VBASE=VERSAT=0` and a null `VERNRT`,
which the `VERSAT - VBASE == 0` guard rendered inert; wiring the parameters
removes that exposure.

Values (`winter_wheat` VBASE 14 / VERSAT 70; `winter_rapeseed` 7 / 24) come from
the Germany-wide reference project. `VBASE` and `VERSAT` are now calibratable in
stage 1 and frozen for stage 2; `VERNRT` stays frozen — the response *shape* is a
cultivar property, the two thresholds are the levers.

**Expect the phenology baseline to get worse before calibration improves it.**
Vernalisation delays anthesis (8-16 d at a Berlin site over two seasons), and the
pre-vernalisation residual was already ~26 d late, so `TSUM1` has to come down
correspondingly. Any calibration ledger predating this change is not comparable
and should be archived, not continued.
