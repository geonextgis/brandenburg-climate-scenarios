# Climate and CO₂ scenario layer

This directory holds the inputs that vary by **scenario** rather than by crop.

## `co2/` — atmospheric CO₂ records

Four monthly records, `year,month,average` (ppm). One copy each: CO₂ is a
property of the scenario, not of the crop, so it is not duplicated per crop the
way the reference project did it.

| file | source | span | used by |
| --- | --- | --- | --- |
| `co2_mm_observed.csv` | NOAA/Scripps Mauna Loa monthly mean | 1958-03 … 2026-06 | input to the historical build; not staged directly |
| `co2_mm_historical.csv` | **generated** — Law Dome spline spliced onto Mauna Loa | 1951-01 … 2026-06 | DWD, HYRAS OBS, every GCM `historical`, and all calibration |
| `co2_mm_ssp126_future.csv` | SSP1-2.6 concentration pathway | 2015 … 2500 | every `*_ssp126` experiment |
| `co2_mm_ssp370_future.csv` | SSP3-7.0 concentration pathway | 2015 … 2500 | every `*_ssp370` experiment |

`co2_mm_historical.csv` is generated because the Mauna Loa record starts seven
years after the historical period does, and the solution does an exact
`(year, month)` lookup on **every simulated day** — a month with no row is a
NullPointerException, not a gap. `orchestration/build_co2_historical.py` prepends
1951-01 … 1958-02 from the Law Dome ice-core/firn spline
(`data/external/law_dome_co2_spline_annual.csv`) with a Mauna-Loa-derived
seasonal cycle and a fitted splice offset, and copies the observed months through
verbatim. Regenerate or validate it with:

```bash
python orchestration/build_co2_historical.py            # rebuild
python orchestration/build_co2_historical.py --check    # validate every record
```

## How a record reaches the model

`orchestration/generate.py` copies the record bound to the experiment's climate
into that run dir as `data/co2/co2.csv`. The binding lives in the climate
registry (`build_climate_registry`), not in a hand-written config — that is what
prevents an SSP experiment from silently running on the observed record. The
generator then refuses to write a run dir whose simulation windows extend past
its CO₂ record.

Inside the solution, `CO2Supply` exposes the monthly value as a daily driving
variable and feeds `RadiationUseEfficiency.cCO`, which scales RUE against
`crop.COTableFactor` / `crop.COTableCo2` and returns `RTMCO`, the transpiration
ratio modifier used by `LintulWaterStress`. See `orchestration/patch_solution_co2.py`
and the *CO₂ forcing* section of `CLAUDE.md`.

## Weather

Weather is **not** copied into the repo. Each run dir's `config.yaml` carries a
`mount_data` path that the runner binds to `/data` inside the Singularity
container. The roots are configured in `orchestration/experiments.yaml`:

- `climate_dwd` — DWD observations, tab-delimited gzip, foldered by row
- `climate_root_hyras` — HYRAS bias-corrected NEX-GDDP-CMIP6, comma-delimited
  plain CSV, foldered by column, on a different grid (see
  `orchestration/build_point_grid.py`)
