# Brandenburg Climate + CO₂ Scenarios

Crop-model (SIMPLACE / LINTUL5) simulation framework for evaluating crop response
to future climate **and rising atmospheric CO₂** on the Brandenburg 1 km site
grid (15 066 sites, 19 NUTS-3 districts), with agents driving model calibration.

**Crops** (calibrated in two stages: phenology, then yield):
winter wheat, winter rapeseed, spring barley, potato, maize, sugar beet.

**Experiment matrix:** 17 climate scenarios × 6 crops = **102 experiments**.

| Type       | Period    | Climate                   | Scenarios | CO₂      | Management (`vIDPL`)        |
| ---------- | --------- | ------------------------- | --------- | -------- | --------------------------- |
| Baseline   | 1979–2024 | DWD observations          | 1         | observed | dynamic, per observed season |
| Historical | 1951–2014 | HYRAS-BC OBS + 5 GCMs     | 6         | observed | district median              |
| Future     | 2015–2100 | 5 GCMs × {SSP126, SSP370} | 10        | per SSP  | district median              |

Each future experiment runs under the CO₂ pathway of its own scenario — ~403 ppm
in 2015 rising to ~600 ppm (ssp126) or ~870 ppm (ssp370) by 2100 — which reaches
the crop through LINTUL5's radiation-use-efficiency and transpiration-ratio
response. Before this repository existed, the same model ran every scenario at a
fixed 380 ppm.

## Layout

```
climate/co2/         the CO2 scenario records, staged per experiment
data/raw/            site -> climate-cell mapping, raw DWD phenology
docs/                design notes, including the restructure record
notebooks/           00_exploration .. 04_evaluation
optimization/        agentic calibration: local Ollama agents + Claude Code agents
orchestration/       experiments.yaml + the builders and the run-dir generator
simplace/runners/    the shared SLURM/Singularity and local drivers
simplace/<crop>/     the SIMPLACE model, its inputs, and its run dirs
```

## Quickstart

```bash
# List the 17 climate sources and the CO2 record each one carries
python orchestration/generate.py --list-climates

# Preview without writing anything (probes the weather, checks value ranges)
python orchestration/generate.py --crop maize --climate DWD --dry-run

# Generate one isolated run dir (simplace/<crop>/runs/<climate>/)
python orchestration/generate.py --crop maize --climate GFDL-ESM4_ssp370

# Submit it
python simplace/runners/simplace_runner_cluster.py \
    simplace/maize/runs/GFDL-ESM4_ssp370/config.yaml
```

`--crop` and `--climate` each accept a single value, a comma-separated list, or
`all`. Generating the full matrix also writes a campaign sbatch script that holds
one allocation across every experiment — see `orchestration/README.md`.

## Prerequisites

A fresh clone does **not** contain the derived tables — they are gitignored
(~10 GB across the matrix) and are rebuilt from the tracked inputs:

```bash
python orchestration/build_point_grid.py                  # sites -> HYRAS cells
python orchestration/build_co2_historical.py              # pre-1958 CO2 reconstruction
python orchestration/patch_solution_co2.py --check        # solutions are CO2-driven?
python orchestration/build_baseline_project.py --crop all # baseline tables (~70 MB each)
```

Observations (`simplace/<crop>/data_observed/`) come from
`notebooks/01_preprocessing/`. SIMPLACE itself runs from a Singularity image on
the cluster (`slurm.singularity_image` in `orchestration/experiments.yaml`).

Self-test the calibration layer without touching the cluster:

```bash
python optimization/test_calibrate.py
```

## Paths

Nothing hard-codes the repository location: the root is derived from each file's
own path, so the checkout can be moved or cloned anywhere. Both config files set
`repo_root: auto`; set `BRANDENBURG_SCENARIOS_ROOT` to override. Paths *outside*
the repo (the shared climate stores) are absolute and live in
`orchestration/experiments.yaml`.

## Known limitations

Two properties of the inherited data and model shape what can be concluded
here. They are documented in full in `CLAUDE.md` and at the code that is affected:

- **The canopy is not observed** on these sites, so the growth stage calibrates
  yield only and leaf area is constrained by an agronomic envelope, not by data.
- **Observed planting dates are sparse for potato and spring barley**, so their
  baseline management is closer to constant than to year-by-year.

A third — no vernalisation, which biased projected winter-crop phenology early
under warming — was resolved on 2026-09-07 by
`orchestration/patch_crop_vernalisation.py`. Results produced before that date
still carry it.
