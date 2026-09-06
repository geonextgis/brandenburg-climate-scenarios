# Restructure record

What this repository is, where each part came from, and which decisions were
judgement calls rather than mechanical ports. Written 2026-08-23.

## Sources

| | path |
| --- | --- |
| Architecture reference | `/data01/FDS/halder/soil-amelioration-scenarios` (Germany-wide, 5 crops, 5 soil scenarios) |
| Data and model | `/beegfs/halder/SIMPLACE_WDIR/Brandenburg_1KM_*` (7 workspaces, ~280 GB) |

The predecessor workspaces are **untouched**. Only their inputs were copied
(~52 MB); the ~280 GB of `out/` stayed where it is, and remains readable there.

## What was carried over, and what was not

**Carried over from the reference:** the orchestration layer (`experiments.yaml`
+ `generate.py` + the campaign/submit drivers + `hold_nodes.py` +
`consolidate_outputs.py`), the whole agentic calibration layer
(`optimization/`), the Claude Code agents and commands, the climate registry
(same 5 GCMs, same 3 scenarios, same HYRAS-BC source), the CO₂ records and the
historical CO₂ reconstruction, and the repo conventions (portable roots,
generated-not-hand-edited run dirs, ledgered calibration).

**Deliberately not carried over:** everything to do with soil amelioration
scenarios — `data/raw/soil_scenarios/`, the `--soil` selector, the `soil` axis of
the experiment matrix and of `consolidate_outputs.py`, and the per-experiment
staging of `soil.csv`. Soil is a fixed property of the Brandenburg sites, so
`data/soil/` is a symlinked shared input like `crop/` and `management/`.

## Decisions worth recording

### 1. CO₂ was a constant and is now a scenario input

The inherited Brandenburg solutions hard-coded `vCO2 = 380` into
`RadiationUseEfficiency.cCO`. Every one of the six was byte-identical in
structure, so `orchestration/patch_solution_co2.py` applies the same four-part,
idempotent edit to all of them and `--check` reports the state. The constant is
commented rather than deleted so the change stays legible.

This is the difference between an ssp370 run that experiences 2100's climate at
2000's CO₂ and one that experiences both. It also reaches water use, not only
assimilation, via `RTMCO` — which matters more here than in the reference,
because Brandenburg's soils are sandy and water-limited.

### 2. The baseline project table had to be built, not copied

The reference's per-crop `project_<crop>.csv` carries `start_date`, `end_date`
and `vIDPL` per row. The Brandenburg tables carried none of them: the period and
the planting date were constants in `solution.sol.xml`, and the table was a flat
15 066-row site list. That is enough for one scenario run and not enough for a
scenario matrix.

`orchestration/build_baseline_project.py` builds the per-season table from the
site inventory plus the observed DWD sowing dates, **and** rewrites the proj.xml
header that reads it. Those two are written by one script on purpose: a project
CSV whose columns do not match its header is not an error SIMPLACE reports, it is
a silent column shift.

The old site list is preserved as `project/sites_<crop>.csv` and is the one
tracked input in `project/`.

### 3. The site→climate join had to be rebuilt

Brandenburg's `vColumn`/`vRow` are DWD grid coordinates. HYRAS-BC is a different
grid (0.01°, masked to the German land area). `orchestration/build_point_grid.py`
does an exact nearest-neighbour join with longitude scaled by cos(latitude);
snapping to the grid step was tried first and failed for 273 sites that land in
holes in the land mask. 15 066 sites → 13 424 distinct cells; 361 Oder-border
sites are >2.2 km from their cell and are kept, with a printed note.

All 17 sources were spot-checked for file coverage over the Brandenburg cells:
complete.

### 4. Deduplication

Three things were duplicated per crop in the source workspaces and are now
single-copy: the 25 MB raw DWD phenology record (`data/raw/`, symlinked into each
crop), the cluster and local drivers (`simplace/runners/`, they were identical),
and the CO₂ records (`climate/co2/`, they are a property of the scenario). The
preprocessing notebooks were likewise hoisted to `notebooks/01_preprocessing/`.

### 5. Three limitations were surfaced rather than papered over

Each of these was found while porting and is documented at the code it affects,
in `CLAUDE.md`, and in the agent instructions that must not work around it.

> This section records the state at the time of the restructure. One of the three
> — no vernalisation — was resolved on 2026-09-07 by
> `orchestration/patch_crop_vernalisation.py`; see `CLAUDE.md`. The other two
> stand.

- **The growth stage is yield-only.** The reference calibrated LAI and yield
  jointly, for a sound reason that still holds. But the inherited
  `LAI_<crop>.csv` files are on the Germany-wide BZE point set with **zero**
  overlap with the Brandenburg sites, and `maize` and `sugar_beet` have no LAI
  file at all. Approximating an LAI view from that would have been worse than
  not having one. What it would take to restore the joint stage is written down
  in `optimization/config.yaml`.
- **There is no vernalisation** anywhere in this model configuration — no
  `crop.xml` defines `VBASE`/`VERSAT`/`VERNRT` and no solution wires them in. The
  parameters are declared but disabled, with the reason attached. This biases
  projected winter-crop phenology early under warming, which is directly relevant
  to the question this repo exists to answer, so it is stated in the README as
  well. Adding vernalisation is a modelling decision, not a restructuring one.
- **Observed planting dates are sparse for some crops** (potato ~26 % observed,
  spring barley ~48 %). `build_baseline_project.py` reports the fraction every
  time it runs and warns when the majority falls back to a median.

### 6. Observations are district-level, so the objectives aggregate

The reference joined simulated phenology to observations per site. Brandenburg's
phenology observations are per NUTS-3 district and season. Attaching one district
observation to each of its ~800 sites would have replicated a single measurement
800 times inside the RMSE — the loss would be dominated by how many sites a
district contains, and the apparent sample size would be three orders of
magnitude larger than the evidence. So simulated dates are averaged to the
district before the join, exactly as the yield view already did. The metric
labels say "districts", not "locations".

## Verification performed

| check | result |
| --- | --- |
| `optimization/test_calibrate.py` | 71/71 pass, 1 skip (vernalisation, correctly) |
| All six solutions well-formed XML after the CO₂ patch | pass |
| CO₂ patch idempotent (second run is a no-op) | pass |
| `build_co2_historical.py --check` | all records gap-free and covering their periods |
| `generate.py --dry-run` over all 17 climates | all probe clean: no bad temperature ranges, no calendar drift |
| Run dir generated for `DWD` and `GFDL-ESM4_ssp370` | correct grid remap, divider, filename template, staged SSP CO₂ |
| Calibration run dir built end to end | 6 800 rows / 400 sites, CO₂ staged |

**Not verified: no SIMPLACE simulation has been run.** The model has not executed
against the CO₂-patched solutions or the new project tables. Smoke-test one
experiment with its `config_smoke.yaml` before committing cluster time to the
matrix.
