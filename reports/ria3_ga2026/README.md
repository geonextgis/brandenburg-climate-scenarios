# LL-SYSTAIN GA 2026 — RIA 3, ZALF contribution: figures

**Climate, CO₂ and Brandenburg's arable systems: productivity, water and nitrogen**

Six figures from the SIMPLACE/LINTUL5 1 km simulations (15 066 sites,
5 calibrated crops × 17 climate scenarios; sugar beet is not yet simulated).
PNG at 300 dpi and SVG in `figures/`; the numbers behind each figure are in
`figures/fig*_stats.csv` / `fig6_scorecard.csv`.

```bash
bash reports/ria3_ga2026/scripts/run_all.sh     # ~2 min on 28 cores
```

| step | script | output |
| --- | --- | --- |
| 1 | `01_extract.py` | `data/sites/<crop>/<exp>.parquet` — 25 columns of the 24 GB consolidated tables, keyed to PointID + NUTS-3 |
| 2 | `02_aggregate.py` | `data/annual_state.parquet`, `data/period_site.parquet`, `data/district_obs_sim.parquet` |
| 3 | `fig1` … `fig6` | `figures/` |

## Story line (one slide per figure)

**1 · Credibility — the model hits the regional yield level** (`fig1_model_evaluation`)
*Takeaway:* Over the 1995–2023 calibration window the 1 km simulation reproduces
Brandenburg's district-mean yields with near-zero bias for all five crops
(|bias| ≤ 0.08 t/ha). Year-to-year skill is good for maize (r 0.88), spring
barley (0.76) and potato (0.73), and weaker for winter wheat (0.43) and rapeseed (0.31).
*Caption:* Mean yield of observed NUTS-3 districts vs. SIMPLACE driven by DWD
weather and observed CO₂. Grey band: between-district 10–90 % range. The
shaded pre-1995 years carry a technology and management trend the model
does not represent. Simulated potato varies about twice as much from year to
year as observed potato.

**2 · Two futures diverge, and for C3 crops the gain is the CO₂ term** (`fig2_yield_trajectories`)
*Takeaway:* Under SSP3-7.0, wheat (+32 %), rapeseed (+25 %) and barley (+36 %)
gain roughly what the model's CO₂ response alone delivers (+34 %). Potato
(−27 %) and C4 maize (−13 %) lose despite it, and the gap to the dashed line
is the climate penalty. Under SSP1-2.6 the changes are smaller in both
directions.
*Caption:* Brandenburg mean yield change vs. 1985–2014, 21-year running mean.
Line: median of 5 bias-corrected CMIP6 GCMs. Band: GCM range. Dashed: change
implied by the RUE–CO₂ table alone (×1.35 at ≥ 720 ppm for C3 crops, ×1.07
for maize); it omits CO₂'s effect on transpiration.

**3 · Where — the sandy south is the hotspot** (`fig3_yield_change_maps`)
*Takeaway:* The signs are robust (≥ 4 of 5 GCMs agree at 83–100 % of sites,
except maize under SSP1-2.6). The magnitudes follow a north–south gradient.
Under SSP3-7.0, wheat gains +16 % south of 52.2° N vs. +41 % north of
52.8° N, and potato loses −31 % vs. −20 %. Maize runs the other way
(−5 % south, −18 % north).
*Caption:* Ensemble-median yield change 2071–2100 vs. 1985–2014 at each
1 km site. Black dots: < 4 of 5 GCMs agree on the sign.

**4 · Mechanism — faster development, more stress, CO₂ water saving** (`fig4_water_phenology`)
*Takeaway:* All crops flower earlier: by 27 days for wheat under SSP3-7.0, and
8–17 days for the others. In-season water stress rises for four of five crops
(+4 to +8 points; barley −2). Water productivity rises 36–44 % for wheat,
rapeseed and barley, which is how CO₂ carries them through. For potato it
falls 20 %, and for maize 5 %.
*Caption:* Change 2071–2100 vs. 1985–2014, Brandenburg mean. Dot: GCM
median. Bar: GCM range. Stress = 1 − TRANRF from sowing to harvest. Water
productivity = yield per m³ transpired.

**5 · The environmental cost — nitrate leaching** (`fig5_nitrogen_tradeoff`)
*Takeaway:* With fertiliser held at today's rates, median nitrate leaching
rises for every crop and pathway. In absolute terms the winter crops dominate:
+25 to +37 kg N/ha per season window at the typical site, with N loss per
tonne up 9–25 %. Spring crops leach little (a few kg N/ha), but each tonne
of potato, maize or barley costs 2–3× as much leached N.
*Caption:* (a) Yield change vs. leaching change at the typical site (median
across sites). Dot: GCM median. Whiskers: GCM range. (b) kg N leached per t
yield, GCM-paired ratio. Model-derived and not validated against leaching
measurements.

**6 · Synthesis — no crop improves on every axis** (`fig6_sustainability_scorecard`)
*Takeaway:* The CO₂-driven gains in cereal and rapeseed yield, stability and
water productivity come with more nitrate leaching. Potato and maize
deteriorate on nearly every indicator under SSP3-7.0. This is the
productivity–environment trade-off that RIA 3's systemic assessment needs at
regional scale: adaptation that targets yield alone would deepen the nitrogen
problem.
*Caption:* Ensemble-median change 2071–2100 vs. 1985–2014. Colour = direction
for the agri-environment system, scaled per indicator. Faded "~" = < 4 of 5
GCMs agree on the sign.

## What these results can and cannot support

- **The future yield gains are conditional on CO₂ fertilisation.** All five
  crop.xml files share a RUE–CO₂ table (×1.35 at 720 ppm, clamped above — confirmed
  in the simplace_5.0-3897 bytecode). That response is at the upper end of
  free-air CO₂ enrichment (FACE) evidence. No constant-CO₂ (climate-only)
  experiment exists yet. The dashed line in Fig. 2 is a reference, not that
  counterfactual. Running the counterfactual is the most valuable next experiment.
- **Management is frozen at today's level.** Sowing rules and N fertiliser
  do not change, and there is no cultivar adaptation, irrigation or crop-rotation
  change.
- **Leaching is model-derived and not validated.** Fluxes are summed over the
  simulation window (1 Jan of the sowing year → harvest), which for winter
  crops includes the pre-sowing fallow. Levels therefore compare within crop
  types, not across them. A few organic-rich sites leach extreme amounts, so
  medians are reported.
- **Maize** fails to mature on 16 % of site-seasons in 1985–2014 (≈ 0 % in
  the future). Its yields are means over harvested site-seasons.
- **No biodiversity or planetary-boundary claims.** The indicators are
  field-scale yield, water and nitrogen fluxes. They can feed PIK's and SGN's
  models as pressure layers, but they are not boundary or biodiversity
  metrics themselves.

## Data provenance checks performed

- Every run used the promoted (best-calibrated) `crop.xml` — run-dir
  `MANIFEST.json` digests match `optimization/calibration/<crop>/growth/best_crop.xml`.
- The consolidated tables carry no PointID. `01_extract.py` validates each
  `projectid` join on climate cell + harvest year. One experiment
  (maize/ACCESS-CM2_historical, whose run dir was regenerated after it ran) failed
  that check and was rebuilt from its per-site files. Spot checks against
  per-site files agree to float32 precision.

District outlines: `data/external/nuts3_2021_DE3_DE4.geojson`, the Berlin +
Brandenburg subset of Eurostat GISCO NUTS 2021 (1:1 M, EPSG:4326),
© EuroGeographics for the administrative boundaries.
