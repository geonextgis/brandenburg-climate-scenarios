"""Figure 3 — where gains and losses fall (1 km, 2071-2100 vs 1985-2014).

Per site and GCM: mean yield 2071-2100 under each SSP over mean yield
1985-2014 of that GCM's historical run. Mapped: ensemble median across the 5
GCMs. Sites where fewer than 4 of 5 GCMs agree on the sign of the median are
overdrawn with a small dark dot (robustness after the IPCC AR6 convention).
"""
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm
from pyproj import Transformer

import _style as S

LIM = 45


def fmt(v: float) -> str:
    return "±0" if abs(v) < 0.5 else f"{v:+.0f}".replace("-", "−")


def site_change(p: pd.DataFrame) -> pd.DataFrame:
    ref = p[(p.period == "ref") & (p.scen == "historical")].set_index(["crop", "gcm", "vLocationID"])["yield"]
    fut = p[(p.period == "far") & p.scen.isin(["ssp126", "ssp370"])].copy()
    fut["d"] = 100 * (fut["yield"].values / ref.reindex(
        pd.MultiIndex.from_frame(fut[["crop", "gcm", "vLocationID"]])).values - 1)
    g = fut.groupby(["crop", "scen", "vLocationID"])["d"]
    med = g.median().rename("median")
    out = med.to_frame()
    sign = np.sign(out["median"])
    agree = fut.join(sign.rename("s"), on=["crop", "scen", "vLocationID"])
    out["agree"] = (np.sign(agree["d"]) == agree["s"]).groupby(
        [agree.crop, agree.scen, agree.vLocationID]).sum()
    return out.reset_index()


def main() -> None:
    S.setup()
    p = pd.read_parquet(S.DATA / "period_site.parquet", columns=[
        "vLocationID", "yield", "period", "crop", "gcm", "scen"])
    p = p[p.gcm.isin(S.GCMS)]
    ch = site_change(p)
    pts = pd.read_csv(S.ROOT / "data" / "raw" / "point_to_nearest_grid.csv",
                      usecols=["PointID", "Latitude", "Longitude"]).rename(columns={"PointID": "vLocationID"})
    tr = Transformer.from_crs(4326, 3035, always_xy=True)
    pts["x"], pts["y"] = tr.transform(pts.Longitude.values, pts.Latitude.values)
    ch = ch.merge(pts[["vLocationID", "x", "y"]], on="vLocationID")
    nuts = gpd.read_file(S.ROOT / "data" / "external" / "nuts3_2021_DE3_DE4.geojson").to_crs(3035)
    outline = nuts.dissolve()

    fig, axes = plt.subplots(2, 5, figsize=(13.33, 6.9))
    fig.subplots_adjust(left=0.065, right=0.985, top=0.84, bottom=0.16, wspace=0.02, hspace=0.06)
    norm = TwoSlopeNorm(0, -LIM, LIM)
    stats = []
    for j, crop in enumerate(S.CROPS):
        for i, scen in enumerate(["ssp126", "ssp370"]):
            ax = axes[i, j]
            c = ch[(ch.crop == crop) & (ch.scen == scen)]
            nuts.boundary.plot(ax=ax, color=S.AXIS, lw=0.35, zorder=1)
            sc = ax.scatter(c.x, c.y, c=c["median"], s=0.9, marker="s", lw=0,
                            cmap=S.DIVERGING, norm=norm, zorder=2, rasterized=True)
            low = c[c.agree < 4]
            ax.scatter(low.x, low.y, s=0.08, color=S.INK, lw=0, zorder=3, rasterized=True)
            outline.boundary.plot(ax=ax, color=S.INK2, lw=0.6, zorder=4)
            ax.set_axis_off()
            ax.set_aspect("equal")
            q = c["median"].quantile([0.1, 0.5, 0.9]).values
            ax.text(0.02, 0.02, f"median {fmt(q[1])} %\n10–90 %: {fmt(q[0])} … {fmt(q[2])}",
                    transform=ax.transAxes, fontsize=7.8, color=S.INK2, va="bottom")
            stats.append((crop, scen, *q, (c.agree >= 4).mean()))
            if i == 0:
                ax.set_title(S.CROP_LABEL[crop], loc="center")
        axes[0, 0].text(-0.06, 0.5, "SSP1-2.6", transform=axes[0, 0].transAxes, rotation=90,
                        va="center", ha="center", fontsize=11, fontweight="bold", color=S.SCEN_DARK["ssp126"])
        axes[1, 0].text(-0.06, 0.5, "SSP3-7.0", transform=axes[1, 0].transAxes, rotation=90,
                        va="center", ha="center", fontsize=11, fontweight="bold", color=S.SCEN_DARK["ssp370"])
    cax = fig.add_axes([0.33, 0.105, 0.34, 0.022])
    cb = fig.colorbar(sc, cax=cax, orientation="horizontal", extend="both")
    cb.set_label("Yield change 2071–2100 vs. 1985–2014 (%), median of 5 GCMs", color=S.INK2)
    cb.outline.set_visible(False)
    fig.text(0.70, 0.116, "•  black dot: < 4 of 5 GCMs agree on the sign", fontsize=8.3, color=S.INK2, va="center")
    S.headline(fig, "Under SSP3-7.0 the south is the hotspot: smallest cereal gains, largest potato losses",
               "Wheat +16 % south of 52.2° N vs. +41 % north of 52.8° N; potato −31 % vs. −20 %. Maize is the exception "
               "(−5 % south, −18 % north). 1 km sites, NUTS-3 outlines")
    S.footnote(fig, "Gains in wheat, rapeseed and barley rest on the model's CO$_2$ fertilisation (Fig. 2). "
               "White space = no arable site in the inventory.", y=0.006)
    S.save(fig, "fig3_yield_change_maps")
    pd.DataFrame(stats, columns=["crop", "scen", "p10", "p50", "p90", "share_robust"]).round(3).to_csv(
        S.FIGS / "fig3_stats.csv", index=False)


if __name__ == "__main__":
    main()
