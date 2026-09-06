# Experiment orchestration layer

Human-readable YAML control surface for the 17-experiment climate + CO₂ matrix
per crop, and the builders that produce the inputs it needs.

| file | what it does |
| --- | --- |
| `experiments.yaml` | the single config: crops, climate sources, periods, CO₂ bindings, SLURM defaults |
| `generate.py` | builds one isolated, reproducible run directory per `(crop, climate)` |
| `build_point_grid.py` | joins the 15 066 Brandenburg sites to the HYRAS climate grid |
| `build_baseline_project.py` | builds each crop's baseline table **and** the proj.xml header that reads it |
| `patch_solution_co2.py` | replaces the fixed 380 ppm CO₂ in a solution with the scenario record |
| `build_co2_historical.py` | reconstructs 1951-01 … 1958-02 CO₂ ahead of the Mauna Loa record |
| `hold_nodes.py` | holds one SLURM allocation across a calibration session |
| `consolidate_outputs.py` | collapses each experiment's per-location outputs into one table |

## Order of operations

The builders are not interchangeable — each consumes the previous one's output:

```bash
python orchestration/build_point_grid.py            # data/raw/point_to_nearest_grid.csv
python orchestration/build_co2_historical.py        # climate/co2/co2_mm_historical.csv
python orchestration/patch_solution_co2.py --crop all
python orchestration/build_baseline_project.py --crop all
python orchestration/generate.py --crop all --climate all
```

Everything except `generate.py` is idempotent and safe to re-run; `--check` /
`--dry-run` on each reports state without writing.

## Usage

```bash
python orchestration/generate.py --list-climates                      # 17 climates + their CO2
python orchestration/generate.py --crop maize --climate DWD           # baseline
python orchestration/generate.py --crop maize --climate GFDL-ESM4_ssp370 [--dry-run]
```

Each call writes `simplace/<crop>/runs/<climate>/` containing a project table, a
templated `project.proj.xml`, the scenario CO₂ as `data/co2/co2.csv`, symlinks to
the crop's shared inputs and solution, and a `config.yaml`. Submit with the
shared runner:

```bash
python simplace/runners/simplace_runner_cluster.py simplace/<crop>/runs/<exp_id>/config.yaml
```

Run dirs are independent, so all 102 can be generated and submitted in parallel.

## What the generator handles (contracts that differ by climate source)

| | Baseline (DWD) | HYRAS (OBS + 5 GCMs) |
|---|---|---|
| Grid | the DWD `vColumn`/`vRow` in the crop's baseline table | `point_to_nearest_grid.csv` (a different grid) |
| Weather folder key | `${vRow}` | `${vColumn}` |
| Weather filename | `daily_mean_RES1_C{col}R{row}.csv.gz` | `<MODEL>_<SCEN>_<dates>_C{col}R{row}.csv` |
| Delimiter | tab (`<divider />`) | comma (`<divider>,</divider>`) |
| `vIDPL` | dynamic per observed season | median per NUTS-3 district |
| CO₂ record | observed | observed (historical) / per-SSP (future) |
| Period | 1979–2024, clamped to coverage | 1951–2014 / 2015–2100 |

It also checks two things that are otherwise invisible until a run has already
been wasted:

- **weather value ranges**, not only date coverage. A GCM delivered with the
  Kelvin→Celsius conversion applied twice has correct dates, correct row counts,
  and produces no model output at all. `generate.py` probes the temperature
  columns of one representative file per climate and refuses to stay quiet.
- **CO₂ coverage against the actual windows.** The CO₂ resource does an exact
  `(year, month)` lookup every simulated day, so a window that runs past the end
  of its record is a NullPointerException. The run dir is not written.

## Submitting a set of experiments

`generate.py` writes two drivers into `simplace/runs_submit/` for whatever it just
generated. They differ only in **who owns the nodes**:

| | `campaign_<label>_<hash>.sbatch` | `submit_<label>_<hash>.sh` |
|---|---|---|
| Allocation | one, `slurm.campaign_nodes`, held start to finish | one set per experiment, released after each |
| Experiments | sequential inside that allocation, each using all of it | `cluster_nodes // num_nodes` at a time |
| Queue waits | once, before the first experiment | once **per experiment** |
| Run with | `sbatch campaign_....sbatch` | `bash submit_....sh` |

```bash
sbatch simplace/runs_submit/campaign_<label>_<hash>.sbatch                       # preferred
sbatch --export=ALL,SIMPLACE_RESUME=1 simplace/runs_submit/campaign_<label>_<hash>.sbatch  # resume
```

The campaign job is the one to use when the partition is busy: re-queueing between
experiments is what dominates wall-clock there. Inside the allocation each
experiment runs as `nodes × num_tasks_per_node` concurrent `srun` job steps
(`simplace_runner_cluster.py --mode alloc`) over location-aligned chunks of its
project table — nothing is submitted, so nothing waits.

Its two costs are worth knowing before you submit:

- **It starts only when `campaign_nodes` are free at once.** A smaller
  `campaign_nodes` starts sooner; a larger one finishes sooner once started.
- **`campaign_walltime` has to cover every experiment end to end.** Each
  experiment writes `.completed_<exp_id>` in its run dir on success, and the job
  refuses to start an experiment it cannot finish (exit 3 → the loop stops
  cleanly rather than losing a half-written experiment to the walltime). Resubmit
  with `SIMPLACE_RESUME=1` to pick up the rest.

Progress: `simplace/runs_submit/logs/campaign_<label>_<hash>-<jobid>.out` for the
campaign, `<run_dir>/log/step_<exp>_<first>_<last>.out` for an individual chunk.

## Scale, and the knob for it

The Brandenburg grid is about five times denser than the Germany-wide project
this layer was adapted from. Per crop:

| | rows | size |
|---|---|---|
| baseline table (46 seasons) | ~680 000 | ~70 MB |
| historical experiment (64 seasons) | ~950 000 | ~95 MB |
| future experiment (86 seasons) | ~1 300 000 | ~130 MB |

The full matrix is roughly 10 GB of project tables before a single output file is
written, and one experiment can produce up to 15 066 of those. When proving a
workflow rather than producing results, thin the site set in `experiments.yaml`:

```yaml
points:
  stride: 10          # every 10th site: 1 507 sites instead of 15 066
```

`build_baseline_project.py` applies it, and everything downstream inherits the
smaller site set from the baseline table.
