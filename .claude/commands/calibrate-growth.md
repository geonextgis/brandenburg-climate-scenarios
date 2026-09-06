---
description: Run the yield calibration loop for a crop (stage 2; Claude decides the parameters, no optimizer)
argument-hint: <crop> [--iterations N] [--locations N]
---

Run the **yield** calibration for **$ARGUMENTS** (default crop: `winter_wheat`).
Delegate to the `growth-calibrator` agent.

One view, one component: simulated yield aggregated to NUTS-3 districts against
the district statistics in `data_observed/yield_<crop>.csv`.

**The canopy is not observed here.** The Germany-wide project this repository was
derived from calibrated LAI and yield jointly, because the same parameters move
biomass and leaf area. That physics is unchanged — but the inherited GLASS-LAI
observations are on a point set with zero overlap with the Brandenburg sites, and
two crops have none at all. So a canopy parameter moved in this stage is measured
only through the yield it produces, and the `crop_reference` envelope (harvest
index, above-ground biomass) in `calibration.yaml` is the only guard against
fixing a yield error with an implausible canopy. Check it every iteration.

## Before you start

Stage 1 must be finished and handed over:

```bash
python optimization/calibrate.py status  --crop <crop> --target phenology
python optimization/calibrate.py handoff --crop <crop>          # if not already done
```

`handoff` copies the phenology-calibrated `crop.xml` into the growth run dir and
re-anchors the freeze on it. If it says the production `crop.xml` does not carry
the calibrated phenology yet, tell the user — `promote --target phenology --yes`
comes first.

## The loop

1. `python optimization/calibrate.py status --crop <crop> --target growth`
2. Iteration 0 with no `--params` — the baseline objective to beat.
3. Then, each iteration: read the diagnostics, name the mechanism, change one
   parameter, and state what you expect to happen to the yield **and** to the
   canopy — the second one is unmeasured, which is why it has to be predicted
   out loud.
4. Stop when the objective plateaus, when the RMSE is inside the spread of the
   district statistics, or when the stopping rule fires.

Pre-flight with `--dry-run` (free, no simulation). Use `--locations 40` while
working out the machinery and the configured subset for the run that counts.

## Reporting

- best iteration and its yield RMSE
- the parameter path from baseline to best, with the reason for each step
- **where simulated harvest index and above-ground biomass ended up relative to
  `crop_reference`** — an objective improvement that left that envelope is a
  regression, not a result
- what you believe still limits the fit (water limitation on Brandenburg's sandy
  soils is a common answer that no parameter in this stage can fix)

## Never

- Edit `crop.xml` or anything under `simplace/<crop>/data/` by hand.
- Run `calibrate.py promote` — that is the user's decision.
- Claim the canopy is calibrated.
