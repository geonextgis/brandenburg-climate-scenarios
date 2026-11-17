"""Step 2 — derive indicators and aggregate the site-season table.

Reads reports/ria3_ga2026/data/sites/<crop>/<exp>.parquet (from 01_extract.py)
and writes, to reports/ria3_ga2026/data/:

    annual_state.parquet   crop x experiment x harvest year, Brandenburg+Berlin
    period_site.parquet    crop x experiment x period x site
    district_obs_sim.parquet  DWD-driven simulation vs observed district yields

    python reports/ria3_ga2026/scripts/02_aggregate.py

Derived indicators (per site-season)
------------------------------------
stress      In-season water stress, 1 - TRANRF_season. The yearly TRANRF is an
            AVG over the whole simulation window (1 Jan of the sowing year to
            harvest) and is 0 before sowing, so it is rescaled to the days
            from sowing to harvest: TRANRF * window_days / (window_days - PlantingDOY).
            0 = unstressed, 1 = no transpiration.
wp          Transpiration water productivity, kg yield per m3 transpired
            (100 * Yield_t_ha / ActualTranspiration_mm).
nleach      Nitrate leached below the profile over the simulation window,
            kg N/ha (NitrateLossSeepage_SUM_kg_ha). Model-derived, not
            validated against measurements; the distribution has a long upper
            tail on high-organic-matter soils, so district/state summaries use
            the median as the headline and keep the mean alongside.
lowyield    1 if the season yielded < 75 % of the site's own 1985-2014 median
            under the same GCM (historical run), else 0.

Climate-change signals are always computed GCM by GCM against that GCM's own
historical run over 1985-2014, so GCM bias in the absolute level cancels.
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "reports" / "ria3_ga2026" / "data"
SITES = DATA / "sites"

CROPS = ["winter_wheat", "winter_rapeseed", "spring_barley", "potato", "maize"]
WINTER = {"winter_wheat", "winter_rapeseed"}
GCMS = ["ACCESS-CM2", "CanESM5", "EC-Earth3", "GFDL-ESM4", "MIROC6"]
PERIODS = {"ref": (1985, 2014), "mid": (2031, 2060), "far": (2071, 2100)}
N_SITES = 15066


def parse_exp(exp: str) -> tuple[str, str]:
    if exp == "DWD":
        return "DWD", "baseline"
    if exp == "HYRAS_OBS":
        return "HYRAS", "historical"
    gcm, scen = exp.rsplit("_", 1)
    return gcm, scen


def load(crop: str, exp: str) -> pd.DataFrame:
    d = pd.read_parquet(SITES / crop / f"{exp}.parquet")
    pre = 365.25 if crop in WINTER else 0.0
    window = pre + d["DOY"].astype("float64")
    season = window - d["PlantingDOY"].astype("float64")
    tr = (d["TRANRF"] * window / season).clip(0, 1)
    d["stress"] = (1 - tr).astype("float32")
    d["wp"] = (100 * d["Yield_t_ha"] / d["ActualTranspiration"].where(d["ActualTranspiration"] > 1)).astype("float32")
    d["nleach"] = d["NitrateLossSeepage_SUM_kg_ha"]
    return d


def annual(crop: str, exp: str) -> pd.DataFrame:
    d = load(crop, exp)
    g = d.groupby("Year")
    out = pd.DataFrame({
        "n_harvested": g.size(),
        "yield": g["Yield_t_ha"].mean(),
        "yield_p10": g["Yield_t_ha"].quantile(0.10),
        "yield_p90": g["Yield_t_ha"].quantile(0.90),
        "biomass": g["AGBiomass_t_ha"].mean(),
        "stress": g["stress"].mean(),
        "wp": g["wp"].median(),
        "nleach_med": g["nleach"].median(),
        "nleach_mean": g["nleach"].mean(),
        "nuptake": g["cropNuptake_kg_ha"].mean(),
        "co2": g["CO2"].mean(),
        "anthesis": g["AnthesisDOY"].mean(),
        "tmax": g["Tmax"].mean(),
        "rain": g["Rain"].mean(),
    }).reset_index().rename(columns={"Year": "year"})
    gcm, scen = parse_exp(exp)
    out["harvest_share"] = out["n_harvested"] / N_SITES
    return out.assign(crop=crop, exp=exp, gcm=gcm, scen=scen)


def per_period(crop: str, exp: str, ref_median: pd.Series | None) -> pd.DataFrame:
    d = load(crop, exp)
    parts = []
    for p, (y0, y1) in PERIODS.items():
        s = d[(d["Year"] >= y0) & (d["Year"] <= y1)]
        if s.empty:
            continue
        if ref_median is not None:
            thr = 0.75 * s["vLocationID"].map(ref_median)
            low = (s["Yield_t_ha"] < thr).astype("float32").where(thr.notna())
        else:
            low = pd.Series(np.nan, index=s.index, dtype="float32")
        s = s.assign(low=low)
        g = s.groupby("vLocationID")
        parts.append(pd.DataFrame({
            "nuts": g["vNUTSID"].first().astype(str),
            "n": g.size(),
            "yield": g["Yield_t_ha"].mean(),
            "yield_cv": g["Yield_t_ha"].std() / g["Yield_t_ha"].mean(),
            "stress": g["stress"].mean(),
            "wp": g["wp"].mean(),
            "nleach": g["nleach"].mean(),
            "nleach_med": g["nleach"].median(),
            "lowyield": g["low"].mean(),
            "anthesis": g["AnthesisDOY"].mean(),
            "co2": g["CO2"].mean(),
        }).reset_index().assign(period=p))
    gcm, scen = parse_exp(exp)
    return pd.concat(parts).assign(crop=crop, exp=exp, gcm=gcm, scen=scen)


def crop_job(crop: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    exps = sorted(p.stem for p in (SITES / crop).glob("*.parquet"))
    ann = pd.concat([annual(crop, e) for e in exps])
    per = []
    for model in GCMS + ["HYRAS"]:
        hist = "HYRAS_OBS" if model == "HYRAS" else f"{model}_historical"
        h = load(crop, hist)
        h = h[(h["Year"] >= 1985) & (h["Year"] <= 2014)]
        ref_median = h.groupby("vLocationID")["Yield_t_ha"].median()
        targets = [hist] if model == "HYRAS" else [hist, f"{model}_ssp126", f"{model}_ssp370"]
        per += [per_period(crop, e, ref_median) for e in targets]
    return ann, pd.concat(per)


def obs_vs_sim() -> pd.DataFrame:
    import yaml
    cfg = yaml.safe_load(open(ROOT / "optimization" / "config.yaml"))
    rows = []
    for crop in CROPS:
        d = pd.read_parquet(SITES / crop / "DWD.parquet", columns=["vNUTSID", "Year", "Yield_t_ha"])
        sim = (d.groupby(["vNUTSID", "Year"], observed=True)["Yield_t_ha"].mean()
                .rename("sim").reset_index()
                .rename(columns={"vNUTSID": "NUTS_ID", "Year": "year"}))
        obs = pd.read_csv(ROOT / "simplace" / crop / "data_observed" / f"yield_{crop}.csv",
                          usecols=["NUTS_ID", "year", "yield"])
        obs["obs"] = obs["yield"] * cfg["crops"][crop]["dm_fraction"]
        m = sim.merge(obs[["NUTS_ID", "year", "obs"]], on=["NUTS_ID", "year"], how="inner")
        rows.append(m.assign(crop=crop))
    return pd.concat(rows)


def main() -> int:
    with ProcessPoolExecutor(len(CROPS)) as ex:
        res = list(ex.map(crop_job, CROPS))
    ann = pd.concat([r[0] for r in res], ignore_index=True)
    per = pd.concat([r[1] for r in res], ignore_index=True)
    ann.to_parquet(DATA / "annual_state.parquet")
    per.to_parquet(DATA / "period_site.parquet")
    ovs = obs_vs_sim()
    ovs.to_parquet(DATA / "district_obs_sim.parquet")
    print(f"annual_state {len(ann):,}  period_site {len(per):,}  obs_sim {len(ovs):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
