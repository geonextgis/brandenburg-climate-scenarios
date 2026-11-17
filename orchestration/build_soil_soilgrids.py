#!/usr/bin/env python
"""Rebuild the Brandenburg site soil table from ISRIC SoilGrids v2.0.

Why this exists
---------------
The inherited ``simplace/<crop>/data/soil/soil.csv`` (originally
``soil_data_Brandenburg.csv``, no build script survives) is wrong south of
~52.25 N: ~5 400 sites carry a silt-loam profile (~6 % sand, ~21 % clay) where
the BZE-LW survey measures sand (~84 %) and SoilGrids predicts sand (66-82 %).
North of that line its texture is in the right range but has no site-level
skill (r ~ -0.1 against BZE). See notebooks/00_exploration/01_soil_inputs_across_crops.ipynb.

What it does
------------
1. ``--download`` crops the SoilGrids 250 m mean maps (sand, silt, clay, soc,
   bdod at the six standard depths) to the Brandenburg bounding box and caches
   them in ``data/external/soilgrids/`` (re-fetchable, gitignored as *.tif).
2. Each 1 km site takes the mean of the valid 250 m pixels in the 1 km square
   centred on it (falling back to the nearest valid pixel within 2 km).
3. The six SoilGrids depths (0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm) are
   overlap-weighted onto the six SIMPLACE layers (0-10, 10-30, 30-50, 50-70,
   70-100, 100-200 cm).
4. SoilGrids is regionally biased here, and regresses toward the mean: against
   the 229 BZE-LW profiles in Berlin + Brandenburg it puts topsoil carbon at
   3.5x the measured level (0-5 cm alone: 5.9 % vs 1.1 %), the effect of its
   training data including forest and grassland surfaces, and makes the subsoil
   10-14 pp less sandy than measured. Sand, clay and carbon are therefore
   quantile-mapped per layer onto the distribution of the BZE-LW mineral
   profiles (no layer with C >= 12 %): SoilGrids decides *where* a site ranks, BZE-LW
   decides the values. Cross-validated (5 x 2-fold, held-out points), this takes
   the PAWC(0-1 m) bias from +27 mm to about -1 mm; see --validate.
   Bulk density is not taken from SoilGrids: its topsoil map is speckled by land
   cover, too narrow (5-95 % range 0.18 vs 0.69 g/cm3 measured), has no skill
   against BZE-LW (r ~ 0) and is inconsistent with the corrected carbon. It is
   derived instead from the corrected sand, clay and carbon with a least-squares
   PTF (sand, clay, log C, log depth) fitted on the BZE-LW mineral profiles,
   clipped to their range; cross-validated it raises bd skill from r 0.08 to 0.19.
5. Hydraulic properties come from the HYPRES continuous pedotransfer functions
   (Woesten et al. 1999, Geoderma 90:169-185) -> van Genuchten curve with
   theta_r = 0.01, topsoil flag on the 0-30 cm layers, OM = 1.724 x C:
       sat = theta_s, fc = theta(330 cm, pF 2.5), wp = theta(15 000 cm, pF 4.2),
       res = theta(30 000 cm, pF 4.5)
   Layers with C >= 12 % (peat) use the HYPRES 'organic' class curve, which the
   continuous functions do not cover. Applied to the inherited file's own
   texture this reproduces its fc / wp / sat to a median 0.007 / 0.009 / 0.001
   m3/m3, so the hydraulic method is unchanged and only the texture is new.
6. The file's own conventions are kept: soilwater_init = fc,
   soilwater_red = wp + 0.5 (fc - wp), the *_global values are thickness-weighted
   profile means. Every column the inherited file holds constant (layer depths,
   N/P initial pools, pH, CaCO3, drainage_rate, ...) is copied unchanged, in the
   same row order and column order.

Known gap: SoilGrids resolves no peat at 1 km here (0 layers with C >= 12 %),
while ~5 % of BZE-LW points are peat; the quantile maps exclude those points so
mineral soils are not pulled toward peat values. Peat sites need a peat map.

Coarse fragments (cfvo) are not applied: the inherited schema has no stone
column and Brandenburg's arable soils are nearly stone-free.

The output is a *candidate*, written to ``data/interim/soil/``. It does not
touch ``simplace/<crop>/data/soil/soil.csv``; installing it means re-running
calibration and the scenario matrix.

Usage:
    python orchestration/build_soil_soilgrids.py --download     # fetch rasters once (~1 min)
    python orchestration/build_soil_soilgrids.py                # build the candidate table
    python orchestration/build_soil_soilgrids.py --validate     # compare old/new against BZE-LW
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / "data" / "external" / "soilgrids"
OUT_DIR = REPO_ROOT / "data" / "interim" / "soil"
TEMPLATE = REPO_ROOT / "simplace" / "winter_wheat" / "data" / "soil" / "soil.csv"
SITES = REPO_ROOT / "data" / "raw" / "point_to_nearest_grid.csv"
BZE_ROOT = Path("/data01/FDS/halder/soil-amelioration-scenarios/data/raw")

SG_URL = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{depth}_mean.vrt"
PROPS = {  # property: divisor to the unit soil.csv uses
    "sand": 10.0,   # g/kg   -> %
    "silt": 10.0,   # g/kg   -> %
    "clay": 10.0,   # g/kg   -> %
    "soc": 100.0,   # dg/kg  -> % (g C / 100 g)
    "bdod": 100.0,  # cg/cm3 -> g/cm3
}
SG_DEPTHS = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200)]
SIM_LAYERS = [(0, 10), (10, 30), (30, 50), (50, 70), (70, 100), (100, 200)]
BBOX = (11.1, 51.25, 14.9, 53.65)  # lon/lat, Berlin + Brandenburg plus a margin
TOPSOIL_LAYERS = 2                 # layers 1-2 (0-30 cm) take the HYPRES topsoil flag

H_FC, H_WP, H_RES = 330.0, 15000.0, 30000.0  # suction heads, cm
THETA_R = 0.01
PEAT_C = 12.0                                  # % C above which a layer is organic
PEAT_VG = dict(ts=0.766, tr=0.010, a=0.0130, n=1.2039)  # HYPRES class 'organic'


def _depth_label(d: tuple[int, int]) -> str:
    return f"{d[0]}-{d[1]}cm"


def download() -> None:
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds

    CACHE.mkdir(parents=True, exist_ok=True)
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="120",
               GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="5")
    with rasterio.Env(**env):
        for prop in PROPS:
            for d in SG_DEPTHS:
                out = CACHE / f"{prop}_{_depth_label(d)}_mean.tif"
                if out.exists():
                    continue
                with rasterio.open("/vsicurl/" + SG_URL.format(prop=prop, depth=_depth_label(d))) as src:
                    t = Transformer.from_crs(4326, src.crs, always_xy=True)
                    xs, ys = t.transform([BBOX[0], BBOX[2], BBOX[0], BBOX[2]],
                                         [BBOX[1], BBOX[1], BBOX[3], BBOX[3]])
                    win = from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)
                    win = win.round_offsets().round_lengths()
                    arr = src.read(1, window=win)
                    prof = src.profile | dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                                              transform=src.window_transform(win), compress="deflate",
                                              tiled=True, blockxsize=256, blockysize=256)
                    with rasterio.open(out, "w", **prof) as dst:
                        dst.write(arr, 1)
                print(f"  {out.name}  {arr.shape}")
    (CACHE / "SOURCE.json").write_text(json.dumps({
        "source": "ISRIC SoilGrids v2.0 (Poggio et al. 2021, SOIL 7:217-240), CC-BY 4.0",
        "url_template": SG_URL, "bbox_lonlat": BBOX, "statistic": "mean",
    }, indent=2))


# Carbon is smoothed with a 5 km box mean before sampling. Its 1 km-scale
# variation has no skill against BZE-LW (topsoil r 0.05) and, through the bulk
# density PTF, speckles bd; at 5 km, cross-validated, carbon r rises to 0.13,
# bd r from 0.11 to 0.18, and PAWC is unchanged.
SMOOTH_PX = {"soc": 20}  # 250 m pixels


def _nan_box_mean(a: np.ndarray, size: int) -> np.ndarray:
    from scipy.ndimage import uniform_filter

    valid = ~np.isnan(a)
    num = uniform_filter(np.where(valid, a, 0.0), size, mode="nearest")
    den = uniform_filter(valid.astype(float), size, mode="nearest")
    return np.where(valid, num / np.maximum(den, 1e-9), np.nan)


def sample_sites(lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    """Per property and SoilGrids depth, the 1 km-square mean at each site."""
    import rasterio
    from pyproj import Transformer
    from scipy.ndimage import distance_transform_edt

    out = {}
    for prop, div in PROPS.items():
        for d in SG_DEPTHS:
            path = CACHE / f"{prop}_{_depth_label(d)}_mean.tif"
            if not path.exists():
                sys.exit(f"missing {path.name} - run with --download first")
            with rasterio.open(path) as src:
                a = src.read(1).astype(float)
                a[(a == src.nodata) | (a <= 0)] = np.nan
                if prop in SMOOTH_PX:
                    a = _nan_box_mean(a, SMOOTH_PX[prop])
                x, y = Transformer.from_crs(4326, src.crs, always_xy=True).transform(lon, lat)
                r, c = rasterio.transform.rowcol(src.transform, x, y)
                r, c = np.asarray(r), np.asarray(c)
            # 1 km square = 4 x 4 pixels of 250 m, centred on the site's pixel
            vals = np.full((len(r), 16), np.nan)
            k = 0
            for dr in (-2, -1, 0, 1):
                for dc in (-2, -1, 0, 1):
                    rr = np.clip(r + dr, 0, a.shape[0] - 1)
                    cc = np.clip(c + dc, 0, a.shape[1] - 1)
                    vals[:, k] = a[rr, cc]
                    k += 1
            v = np.nanmean(vals, axis=1)
            miss = np.isnan(v)
            if miss.any():  # nearest valid pixel within 2 km (8 px)
                dist, (ir, ic) = distance_transform_edt(np.isnan(a), return_indices=True)
                nr, nc = ir[r[miss], c[miss]], ic[r[miss], c[miss]]
                ok = dist[r[miss], c[miss]] <= 8
                v[np.where(miss)[0][ok]] = a[nr[ok], nc[ok]]
            out[(prop, d)] = v / div
    return out


def load_bze() -> pd.DataFrame:
    """BZE-LW profiles (SIMPLACE layout) in Berlin + Brandenburg, with coordinates."""
    import geopandas as gpd

    pts = gpd.read_file(BZE_ROOT / "Site_Soil_BZE_WGS84.gpkg")
    pts = pts[pts.STATE_NAME.isin(["Brandenburg", "Berlin"])]
    bze = pd.read_csv(BZE_ROOT / "soil_scenarios" / "S1_BZE.csv")
    return pts[["PointID", "Latitude", "Longitude"]].merge(bze, left_on="PointID", right_on="location")


def layers(df: pd.DataFrame, base: str) -> np.ndarray:
    return df[[f"{base}_{i}" for i in range(1, 7)]].values


QMAP_Q = np.linspace(0.01, 0.99, 99)


def quantile_map(x: np.ndarray, src: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Per layer: map x through the quantiles of src onto the quantiles of ref."""
    return np.column_stack([np.interp(x[:, j], np.quantile(src[:, j], QMAP_Q), np.quantile(ref[:, j], QMAP_Q))
                            for j in range(x.shape[1])])


def soilgrids_layers(lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    """Sand, clay (texture closed to 100 %), carbon and bulk density on the SIMPLACE layers."""
    sg = sample_sites(lat, lon)
    sand, silt, clay = (to_sim_layers(sg, p) for p in ("sand", "silt", "clay"))
    tot = sand + silt + clay
    return {"sand": 100 * sand / tot, "clay": 100 * clay / tot,
            "carbon": to_sim_layers(sg, "soc"), "bd": to_sim_layers(sg, "bdod")}


LAYER_MID_CM = np.array([5.0, 20.0, 40.0, 60.0, 85.0, 150.0])
BD_RANGE = (0.9, 1.95)  # g/cm3, the BZE-LW mineral range


def _bd_design(sand: np.ndarray, clay: np.ndarray, carbon: np.ndarray, layer: int) -> np.ndarray:
    lc, d = np.log(np.clip(carbon, 0.02, None)), np.log(LAYER_MID_CM[layer])
    return np.column_stack([np.ones_like(sand), sand, clay, lc, lc**2, np.full_like(sand, d), d * lc, sand * d])


def fit_bd_ptf(bze: pd.DataFrame, fit: np.ndarray) -> np.ndarray:
    """Least-squares bulk-density PTF on measured BZE-LW profiles: sand, clay, log C, log depth."""
    X = np.vstack([_bd_design(layers(bze, "sand")[fit, j], layers(bze, "clay")[fit, j],
                              layers(bze, "carbon")[fit, j], j) for j in range(6)])
    y = np.concatenate([layers(bze, "bulkdensity")[fit, j] for j in range(6)])
    return np.linalg.lstsq(X, y, rcond=None)[0]


def bias_correct(site: dict, at_bze: dict, bze: pd.DataFrame, fit: np.ndarray) -> dict:
    """Quantile-map sand, clay and carbon onto the BZE-LW profiles selected by `fit`,
    then derive bulk density from them with a PTF fitted on the same profiles."""
    out = dict(site)
    for k, col in (("sand", "sand"), ("clay", "clay"), ("carbon", "carbon")):
        out[k] = quantile_map(site[k], at_bze[k][fit], layers(bze, col)[fit])
    out["clay"] = np.minimum(out["clay"], 100 - out["sand"] - 0.5)
    coef = fit_bd_ptf(bze, fit)
    out["bd"] = np.clip(np.column_stack([_bd_design(out["sand"][:, j], out["clay"][:, j], out["carbon"][:, j], j) @ coef
                                         for j in range(6)]), *BD_RANGE)
    return out


def to_sim_layers(sg: dict, prop: str) -> np.ndarray:
    """Overlap-weighted average of the SoilGrids depths onto the SIMPLACE layers."""
    cols = []
    for top, bot in SIM_LAYERS:
        w, acc = 0.0, 0.0
        for d in SG_DEPTHS:
            ov = max(0, min(bot, d[1]) - max(top, d[0]))
            if ov:
                acc = acc + ov * sg[(prop, d)]
                w += ov
        cols.append(acc / w)
    return np.column_stack(cols)


def hypres(clay, silt, om, bd, topsoil):
    """HYPRES continuous PTFs (Woesten et al. 1999): theta_s, alpha (1/cm), n."""
    cl, si = np.clip(clay, 0.5, None), np.clip(silt, 0.5, None)
    om, D, T = np.clip(om, 0.1, None), bd, topsoil
    ts = (0.7919 + 0.001691 * cl - 0.29619 * D - 0.000001491 * si**2 + 0.0000821 * om**2
          + 0.02427 / cl + 0.01113 / si + 0.01472 * np.log(si) - 0.0000733 * om * cl
          - 0.000619 * D * cl - 0.001183 * D * om - 0.0001664 * T * si)
    a = np.exp(-14.96 + 0.03135 * cl + 0.0351 * si + 0.646 * om + 15.29 * D - 0.192 * T
               - 4.671 * D**2 - 0.000781 * cl**2 - 0.00687 * om**2 + 0.0449 / om
               + 0.0663 * np.log(si) + 0.1482 * np.log(om) - 0.04546 * D * si
               - 0.4852 * D * om + 0.00673 * T * cl)
    n = 1 + np.exp(-25.23 - 0.02195 * cl + 0.0074 * si - 0.1940 * om + 45.5 * D - 7.24 * D**2
                   + 0.0003658 * cl**2 + 0.002885 * om**2 - 12.81 / D - 0.1524 / si
                   - 0.01958 / om - 0.2876 * np.log(si) - 0.0709 * np.log(om) - 44.6 * np.log(D)
                   - 0.02264 * D * cl + 0.0896 * D * om + 0.00718 * T * cl)
    return ts, a, n


def vg_theta(h, ts, tr, a, n):
    return tr + (ts - tr) / (1 + (a * h) ** n) ** (1 - 1 / n)


def hydraulics(sand, clay, carbon, bd) -> dict[str, np.ndarray]:
    silt = 100 - sand - clay
    topsoil = np.zeros_like(sand)
    topsoil[:, :TOPSOIL_LAYERS] = 1
    ts, a, n = hypres(clay, silt, 1.724 * carbon, bd, topsoil)
    tr = np.full_like(ts, THETA_R)
    peat = carbon >= PEAT_C
    ts[peat], tr[peat], a[peat], n[peat] = PEAT_VG["ts"], PEAT_VG["tr"], PEAT_VG["a"], PEAT_VG["n"]
    out = {"sat": ts, "fc": vg_theta(H_FC, ts, tr, a, n), "wp": vg_theta(H_WP, ts, tr, a, n),
           "res": vg_theta(H_RES, ts, tr, a, n)}
    out["peat"] = peat
    return out


def build() -> Path:
    tpl = pd.read_csv(TEMPLATE)
    sites = pd.read_csv(SITES).set_index("PointID").loc[tpl["location"]]
    site = soilgrids_layers(sites["Latitude"].values, sites["Longitude"].values)
    bad = np.isnan(np.column_stack(list(site.values()))).any(axis=1)
    if bad.any():
        sys.exit(f"{bad.sum()} sites have no valid SoilGrids pixel within 2 km: "
                 f"{tpl['location'][bad].tolist()[:10]} ...")
    bze = load_bze()
    at_bze = soilgrids_layers(bze["Latitude"].values, bze["Longitude"].values)
    mineral = (layers(bze, "carbon") < PEAT_C).all(axis=1)
    site = bias_correct(site, at_bze, bze, mineral)
    sand, clay, carbon, bd = site["sand"], site["clay"], site["carbon"], site["bd"]
    hy = hydraulics(sand, clay, carbon, bd)

    new = tpl.copy()
    thick = np.diff([0] + [b for _, b in SIM_LAYERS]) / 100.0
    for i in range(6):
        j = i + 1
        new[f"sand_{j}"], new[f"clay_{j}"] = sand[:, i], clay[:, i]
        new[f"carbon_{j}"], new[f"bulkdensity_{j}"] = carbon[:, i], bd[:, i]
        new[f"soilwater_sat_{j}"], new[f"soilwater_fc_{j}"] = hy["sat"][:, i], hy["fc"][:, i]
        new[f"soilwater_wp_{j}"], new[f"soilwater_res_{j}"] = hy["wp"][:, i], hy["res"][:, i]
        new[f"soilwater_init_{j}"] = hy["fc"][:, i]
        new[f"soilwater_red_{j}"] = hy["wp"][:, i] + 0.5 * (hy["fc"][:, i] - hy["wp"][:, i])
    new["soilwater_fc_global"] = (hy["fc"] * thick).sum(axis=1) / thick.sum()
    new["soilwater_sat_global"] = (hy["sat"] * thick).sum(axis=1) / thick.sum()

    # the curve must be ordered in every layer, or SIMPLACE's water balance misbehaves
    order = (hy["res"] < hy["wp"]) & (hy["wp"] < hy["fc"]) & (hy["fc"] < hy["sat"])
    assert order.all(), f"{(~order).sum()} layers violate res < wp < fc < sat"
    assert list(new.columns) == list(tpl.columns) and len(new) == len(tpl)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "soil_soilgrids.csv"
    new.to_csv(path, index=False)
    (OUT_DIR / "soil_soilgrids.provenance.json").write_text(json.dumps({
        "texture_carbon_bd": "ISRIC SoilGrids v2.0, 250 m mean, 1 km-square mean per site; "
                             "carbon pre-smoothed with a 5 km box mean",
        "bias_correction": f"sand, clay, carbon quantile-mapped per layer onto {int(mineral.sum())} "
                           "BZE-LW mineral profiles (Berlin + Brandenburg); bulk density from a PTF "
                           "(sand, clay, log C, log depth) fitted on the same profiles",
        "hydraulics": "HYPRES continuous PTF (Woesten et al. 1999), van Genuchten; "
                      f"fc=theta({H_FC:.0f} cm), wp=theta({H_WP:.0f} cm), res=theta({H_RES:.0f} cm), "
                      f"theta_r={THETA_R}, topsoil flag layers 1-{TOPSOIL_LAYERS}, OM=1.724*C; "
                      f"C>={PEAT_C}% -> HYPRES organic class",
        "conventions": "init=fc; red=wp+0.5(fc-wp); *_global thickness-weighted 0-200 cm",
        "unchanged_from": str(TEMPLATE.relative_to(REPO_ROOT)),
        "peat_layers": int(hy["peat"].sum()),
    }, indent=2))
    print(f"wrote {path.relative_to(REPO_ROOT)}  ({len(new)} sites, {int(hy['peat'].sum())} peat layers)")
    return path


def pawc_1m(df: pd.DataFrame) -> pd.Series:
    thick = np.array([0.1, 0.2, 0.2, 0.2, 0.3, 0.0])  # top metre only
    fc = df[[f"soilwater_fc_{i}" for i in range(1, 7)]].values
    wp = df[[f"soilwater_wp_{i}" for i in range(1, 7)]].values
    return pd.Series(((fc - wp) * thick * 1000).sum(axis=1), index=df.index)


def _score(o: np.ndarray, s: np.ndarray) -> dict:
    return dict(bias=np.mean(s - o), mae=np.mean(np.abs(s - o)), r=np.corrcoef(o, s)[0, 1])


def validate() -> None:
    """Old and new table against the BZE-LW measured profiles in Berlin + Brandenburg.

    Two tests. (1) Each table at the site nearest each BZE-LW point. The quantile
    maps were fitted on these same points, so the candidate's *bias* here is
    in-sample. (2) Cross-validation of the correction: 5 x 2-fold, maps fitted on
    one half, scored on the other, with PAWC referenced to HYPRES applied to the
    measured profile, so the method is held fixed and only the inputs differ.
    """
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    bze = load_bze()
    sites = pd.read_csv(SITES).set_index("PointID")
    t = Transformer.from_crs(4326, 3035, always_xy=True)
    tree = cKDTree(np.column_stack(t.transform(sites.Longitude.values, sites.Latitude.values)))
    dist, idx = tree.query(np.column_stack(t.transform(bze.Longitude.values, bze.Latitude.values)))
    near = sites.index.values[idx]
    mineral = (layers(bze, "carbon") < PEAT_C).all(axis=1)

    rows = []
    for name, path in {"inherited": TEMPLATE, "soilgrids": OUT_DIR / "soil_soilgrids.csv"}.items():
        df = pd.read_csv(path).set_index("location").loc[near].reset_index()
        for var, f in [("sand_1 %", lambda x: x["sand_1"]), ("sand_4 %", lambda x: x["sand_4"]),
                       ("clay_1 %", lambda x: x["clay_1"]), ("carbon_1 %", lambda x: x["carbon_1"]),
                       ("PAWC 0-1 m mm", pawc_1m)]:
            o, s = f(bze).values, f(df).values
            for region, m in [("all", mineral), ("north", mineral & (bze.Latitude.values >= 52.25)),
                              ("south", mineral & (bze.Latitude.values < 52.25))]:
                rows.append(dict(table=name, var=var, region=region, n=int(m.sum()),
                                 bze_median=np.median(o[m]), sim_median=np.median(s[m]), **_score(o[m], s[m])))
    res = pd.DataFrame(rows).round(3)

    at_bze = soilgrids_layers(bze["Latitude"].values, bze["Longitude"].values)
    thick = np.array([0.1, 0.2, 0.2, 0.2, 0.3, 0.0])
    ref = hydraulics(layers(bze, "sand"), layers(bze, "clay"), layers(bze, "carbon"), layers(bze, "bulkdensity"))
    ref_pawc = ((ref["fc"] - ref["wp"]) * thick * 1000).sum(axis=1)
    cv = []
    for seed in range(5):
        fold = np.random.default_rng(seed).integers(0, 2, len(bze))
        for k in (0, 1):
            fit, ev = mineral & (fold != k), mineral & (fold == k)
            for name, v in {"raw": at_bze, "corrected": bias_correct(at_bze, at_bze, bze, fit)}.items():
                hy = hydraulics(v["sand"], v["clay"], v["carbon"], v["bd"])
                pawc = ((hy["fc"] - hy["wp"]) * thick * 1000).sum(axis=1)
                for var, o, s in [("sand_1 %", layers(bze, "sand")[:, 0], v["sand"][:, 0]),
                                  ("sand_4 %", layers(bze, "sand")[:, 3], v["sand"][:, 3]),
                                  ("carbon_1 %", layers(bze, "carbon")[:, 0], v["carbon"][:, 0]),
                                  ("PAWC 0-1 m mm", ref_pawc, pawc)]:
                    cv.append(dict(soilgrids=name, var=var, **_score(o[ev], s[ev])))
    cv = pd.DataFrame(cv).groupby(["var", "soilgrids"]).mean().round(2)

    old = pd.read_csv(TEMPLATE).set_index("location").loc[near]
    peat = ~mineral
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT_DIR / "validation_bze.csv", index=False)
    cv.to_csv(OUT_DIR / "validation_bze_cv.csv")
    print(f"BZE-LW points: {len(bze)} ({int(mineral.sum())} mineral, {int(peat.sum())} peat), "
          f"median distance to site {np.median(dist) / 1000:.2f} km")
    print("\n(1) tables at the nearest site, mineral points (candidate bias is in-sample)")
    print(res.pivot_table(index=["var", "region"], columns="table", values=["bias", "mae", "r"]).round(2)
          .to_string())
    print("\n(2) correction cross-validated on held-out points (5 x 2-fold mean)")
    print(cv.to_string())
    print(f"\npeat: {int(peat.sum())} BZE-LW peat points; the inherited table marks "
          f"{int((old['carbon_1'].values[peat] >= PEAT_C).sum())} of them as organic, the candidate 0")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--download", action="store_true", help="fetch and cache the SoilGrids rasters")
    ap.add_argument("--validate", action="store_true", help="compare old and new tables with BZE-LW")
    args = ap.parse_args()
    if args.download:
        download()
    elif args.validate:
        validate()
    else:
        build()


if __name__ == "__main__":
    main()
