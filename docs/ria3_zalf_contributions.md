# RIA 3 Interlinkages Brainstorming — Step 1

## 3.2 ZALF

*Draft, 11 September 2026*

---

### Potential contribution / output 1

**Title of output:**
High-resolution crop yield projections for Berlin-Brandenburg under climate change and rising CO₂

**Short description:**
Process-based crop simulations (SIMPLACE / LINTUL5) for six major arable crops (winter wheat, winter rapeseed, spring barley, potato, maize and sugar beet) on 15,066 agricultural sites on a 1 km grid, under 17 climate scenarios:

- **Observed baseline:** DWD observations, 1979–2023
- **Historical:** HYRAS observations and 5 bias-corrected CMIP6 GCMs (ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, MIROC6), 1951–2014
- **Future:** the same 5 GCMs under SSP1-2.6 and SSP3-7.0, 2015–2100

CO₂ follows the scenario: the observed record for historical runs and SSP-specific concentrations for future runs. The projections therefore include the effect of CO₂ on crop growth and water use, not only the climate signal. This matters on Brandenburg's sandy, water-limited soils.

Results are one record per site and season and can be aggregated to the 19 NUTS-3 districts: 102 experiments (17 scenarios × 6 crops), about 19 million site-season records per crop.

*Status: winter wheat simulated for all 17 scenarios; the other five crops are in calibration or preparation.*

**Type of output:**
Model output / Scenario data

**Spatial scale:**
Berlin-Brandenburg (1 km sites; aggregable to NUTS-3 districts and state level)

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☒ Food
☒ Water
☒ Soil
☐ Planetary boundaries
☐ Other

**Potential relevance for RIA 3 task(s):**
☒ Task 3.1
☒ Task 3.2
☒ Task 3.3

**Potential users within RIA 3:**
Groups working on regional food production and food security, land-use and agricultural transformation, and climate-impact synthesis; biodiversity groups that need agricultural pressure or intensity layers.

**Possible input requirements:**
- Calibrated crop parameters: development timing checked against DWD phenology observations, yield checked against district yield statistics
- DWD observed climate and NEX-GDDP-CMIP6 projections bias-corrected to HYRAS
- CO₂ records: Mauna Loa and Law Dome for the past, SSP concentrations for the future
- Soil profiles for each site
- Sowing dates from the DWD phenology network
- Fertiliser management assumptions
- HPC resources

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 2

**Title of output:**
Agro-environmental indicator set for arable crops (site × season × scenario)

**Short description:**
A set of indicators taken directly from the simulations:

- **Crop production:** yield, above-ground biomass, maximum LAI
- **Crop development:** dates of emergence, flowering and maturity; season length
- **Water:** crop water stress, actual transpiration and evapotranspiration, drainage and seepage, plant-available soil water
- **Nutrients:** crop N uptake, nitrogen nutrition index, nitrate leaching, P uptake and leaching
- **Growing-season conditions:** rainfall, radiation, minimum and maximum temperature, and the CO₂ concentration the crop experienced

Derived indicators:

- yield change relative to the baseline
- year-to-year yield variability and frequency of low-yield years
- shifts in crop development (days)
- water productivity
- nitrogen-loss intensity

**Type of output:**
Indicator

**Spatial scale:**
Berlin-Brandenburg (1 km sites → NUTS-3 → state)

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☒ Food
☒ Water
☒ Soil
☒ Planetary boundaries (nitrogen and phosphorus flows, green-water use)
☐ Other

**Potential relevance for RIA 3 task(s):**
☒ Task 3.1
☒ Task 3.2
☒ Task 3.3

**Potential users within RIA 3:**
Groups working on sustainability indicators and planetary boundaries, water and soil assessments, and trade-off and synergy analysis (e.g. yield vs. nitrate leaching vs. water use).

**Possible input requirements:**
- Output 1
- Agreement on indicator definitions, reference periods and thresholds
- For nitrogen, phosphorus and water-balance indicators: validation data (e.g. lysimeter or leaching measurements), as these terms are model-derived and not yet validated against observations

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 3

**Title of output:**
Calibrated, CO₂-responsive crop model setup and scenario framework for Brandenburg (re-runnable on request)

**Short description:**
A configured SIMPLACE / LINTUL5 model for six crops, including:

- vernalisation and daylength response for winter crops
- a CO₂ response acting on both growth (radiation-use efficiency) and transpiration

It comes with an automated scenario pipeline covering experiment generation, climate and CO₂ input validation, HPC campaign runs, completeness checks and output consolidation. It can simulate new scenarios defined by partners, for example:

- alternative climate forcings
- adapted sowing dates or crop choice
- different fertilisation levels
- changed soil properties
- a climate-only counterfactual with CO₂ held constant

**Type of output:**
Model / Method

**Spatial scale:**
Berlin-Brandenburg (transferable; a Germany-wide version exists, see output 7)

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☒ Food
☒ Water
☒ Soil
☐ Planetary boundaries
☐ Other

**Potential relevance for RIA 3 task(s):**
☐ Task 3.1
☒ Task 3.2
☒ Task 3.3

**Potential users within RIA 3:**
Partners who want to test the agricultural consequences of their own scenarios, such as transformation, adaptation or land-use pathways.

**Possible input requirements:**
- Scenario definitions from partners (management, crop allocation, daily climate data)
- Agreed assumptions about management
- HPC time

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 4

**Title of output:**
Harmonised input and observation datasets for Brandenburg arable agriculture

**Short description:**
- A 1 km inventory of 15,066 agricultural sites, each assigned to its NUTS-3 district and linked to the DWD and HYRAS climate grids
- Soil profiles for each site
- District-level crop development observations from the DWD phenology network (sowing, flowering, maturity), 1979–2022, for six crops
- District-level yield statistics (≈1995–2022)
- Sowing dates per district and season, with the share observed vs. filled from district medians
- Monthly atmospheric CO₂ from 1951: 1951–1958 reconstructed from the Law Dome ice-core record, then Mauna Loa observations
- Monthly SSP1-2.6 and SSP3-7.0 CO₂ concentrations, 2015–2100
- Bias-corrected climate ensemble data for the Brandenburg grid cells, checked for plausible value ranges

**Type of output:**
Data

**Spatial scale:**
Berlin-Brandenburg

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future (future coverage refers to the CO₂ and climate forcing data)

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☐ Food
☐ Water
☒ Soil
☐ Planetary boundaries
☐ Other

**Potential relevance for RIA 3 task(s):**
☒ Task 3.1
☐ Task 3.2
☐ Task 3.3

**Potential users within RIA 3:**
Any group needing consistent regional agricultural, climate or CO₂ input data for Brandenburg.

**Possible input requirements:**
- Largely available already
- Licence and redistribution terms for the DWD data, yield statistics and bias-corrected climate data to be clarified before sharing

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 5

**Title of output:**
Climate-impact and risk assessment of Brandenburg arable systems

**Short description:**
An analysis of the scenario ensemble:

- projected yield changes per crop, district, SSP and period (e.g. 2031–2060 and 2071–2100 vs. 1985–2014), with uncertainty ranges across GCMs
- shifts in crop development, and how often sensitive growth stages coincide with hot or dry periods
- frequency of low-yield years
- water limitation on sandy soils as a driver of yield losses
- maps of spatial hotspots
- SSP1-2.6 vs. SSP3-7.0 comparison: the consequences for agriculture of missing climate targets

**Type of output:**
Analysis / Map

**Spatial scale:**
Berlin-Brandenburg (NUTS-3 and 1 km)

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☒ Food
☒ Water
☒ Soil
☐ Planetary boundaries
☐ Other

**Potential relevance for RIA 3 task(s):**
☒ Task 3.1
☒ Task 3.2
☒ Task 3.3

**Potential users within RIA 3:**
Groups working on risk and vulnerability, food security and stakeholder communication; the Task 3.2 synthesis.

**Possible input requirements:**
- Outputs 1 and 2
- Reference periods and thresholds (e.g. a definition of "crop failure") agreed with partners
- Statistical, spatial and scenario analysis

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 6

**Title of output:**
Transparent, AI-agent-driven calibration method for process-based crop models

**Short description:**
A calibration approach without a black-box optimiser:

- AI agents propose each parameter change, naming the mechanism behind it and the effect they expect
- every change is checked against parameter constraints and plausibility limits (harvest index, biomass)
- every step is recorded in a full audit log
- runs either on local language models (no data leaves the institute) or on Claude

A reusable way to make model calibration traceable and reproducible.

**Type of output:**
Method / Knowledge product

**Spatial scale:**
Transferable (applied to Berlin-Brandenburg and Germany)

**Temporal scale:**
☒ Historical ☒ Current ☐ Near future ☐ Long-term future

**Main thematic domain(s):**
☐ Climate
☐ Biodiversity
☒ Agriculture
☐ Food
☐ Water
☐ Soil
☐ Planetary boundaries
☒ Other (modelling methodology, AI)

**Potential relevance for RIA 3 task(s):**
☒ Task 3.1
☐ Task 3.2
☒ Task 3.3
(cross-cutting: supports model credibility in all tasks)

**Potential users within RIA 3:**
Any group calibrating process-based models (crop, hydrological, ecosystem).

**Possible input requirements:**
- Observations of the target variable
- Parameter bounds and constraints based on expert knowledge

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 7

**Title of output:**
Germany-wide crop simulations of soil amelioration scenarios under climate change

**Short description:**
A related ZALF project using the same simulation framework:

- 5 crops (winter wheat, winter rapeseed, spring barley, potato, maize) at agricultural soil-inventory (BZE) sites across Germany
- a baseline soil plus 4 soil amelioration variants, combined with the same 17 climate scenarios: 85 experiments per crop
- calibrated on LAI and yield together

Shows how much soil improvement could contribute as an adaptation measure under climate change.

**Type of output:**
Scenario / Model output

**Spatial scale:**
Germany (including a Brandenburg subset)

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☒ Food
☒ Water
☒ Soil
☐ Planetary boundaries
☐ Other

**Potential relevance for RIA 3 task(s):**
☐ Task 3.1
☒ Task 3.2
☒ Task 3.3

**Potential users within RIA 3:**
Groups working on adaptation pathways and soil and land-management transformation; cross-scale comparison of Germany and Brandenburg.

**Possible input requirements:**
- Soil scenario definitions
- Calibrated crop parameters
- The same climate ensemble

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]

---

### Potential contribution / output 8

**Title of output:**
Knowledge products on climate impacts for Brandenburg agriculture

**Short description:**
- District-level maps and an atlas of projected changes in yield, crop development and water stress
- An interactive dashboard for exploring results by scenario, crop and district
- Scientific publications (scenario results, calibration method)
- Policy-relevant summaries for regional stakeholders

**Type of output:**
Knowledge product / Map

**Spatial scale:**
Berlin-Brandenburg

**Temporal scale:**
☒ Historical ☒ Current ☒ Near future ☒ Long-term future

**Main thematic domain(s):**
☒ Climate
☐ Biodiversity
☒ Agriculture
☒ Food
☒ Water
☒ Soil
☐ Planetary boundaries
☐ Other

**Potential relevance for RIA 3 task(s):**
☒ Task 3.1
☒ Task 3.2
☒ Task 3.3

**Potential users within RIA 3:**
Stakeholder and communication work, the joint RIA 3 synthesis, and decision-makers.

**Possible input requirements:**
- Outputs 1, 2 and 5

**Potential connections with other institutional outputs:**
[Leave open for later brainstorming]
