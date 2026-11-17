"""Figure 4 — how the climate signal reaches yield: development, water, CO2.

Brandenburg mean per GCM, 2071-2100 vs that GCM's 1985-2014 historical run;
dot = ensemble median, bar = GCM min-max.

  a  anthesis date shift (days)
  b  in-season water stress, 1 - TRANRF over sowing..harvest (see 02_aggregate.py),
     change in percentage points
  c  transpiration water productivity, kg yield per m3 transpired (% change)
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import _style as S

PANELS = [
    ("anthesis", "diff", "a  Flowering date", "Shift (days)  ← earlier"),
    ("stress", "pp", "b  In-season water stress", "Change (percentage points)"),
    ("wp", "pct", "c  Water productivity of transpiration", "Change (%)"),
]


def changes(p: pd.DataFrame) -> pd.DataFrame:
    g = p.groupby(["crop", "gcm", "scen", "period"])[["anthesis", "stress", "wp", "yield"]].mean()
    ref = g.xs(("historical", "ref"), level=("scen", "period"))
    fut = g.xs("far", level="period").reset_index()
    rows = []
    for _, r in fut.iterrows():
        b = ref.loc[(r.crop, r.gcm)]
        rows.append(dict(crop=r.crop, gcm=r.gcm, scen=r.scen,
                         anthesis=r.anthesis - b.anthesis,
                         stress=100 * (r.stress - b.stress),
                         wp=100 * (r.wp / b.wp - 1),
                         stress_ref=100 * b.stress))
    return pd.DataFrame(rows)


def main() -> None:
    S.setup()
    p = pd.read_parquet(S.DATA / "period_site.parquet")
    p = p[p.gcm.isin(S.GCMS)]
    c = changes(p)
    c = c[c.scen.isin(["ssp126", "ssp370"])]

    fig, axes = plt.subplots(1, 3, figsize=(13.33, 5.2), sharey=True)
    fig.subplots_adjust(left=0.115, right=0.985, top=0.78, bottom=0.2, wspace=0.1)
    ypos = {crop: i for i, crop in enumerate(S.CROPS[::-1])}
    off = {"ssp126": 0.15, "ssp370": -0.15}
    summary = c.groupby(["crop", "scen"])[["anthesis", "stress", "wp"]].agg(["median", "min", "max"])
    for ax, (col, kind, title, xlabel) in zip(axes, PANELS):
        ax.axvline(0, color=S.AXIS, lw=0.9, zorder=1)
        for scen in ["ssp126", "ssp370"]:
            for crop in S.CROPS:
                m, lo, hi = summary.loc[(crop, scen), col]
                y = ypos[crop] + off[scen]
                ax.plot([lo, hi], [y, y], color=S.SCEN_COLOR[scen], lw=2.2, alpha=0.45,
                         solid_capstyle="round", zorder=2)
                ax.plot(m, y, "o", ms=8, color=S.SCEN_COLOR[scen], mec="white", mew=1.5, zorder=3,
                        label=S.SCEN_LABEL[scen] if crop == S.CROPS[0] else None)
                if scen == "ssp370":
                    ax.annotate(f"{m:+.0f}".replace("-", "−"), (m, y), xytext=(0, -11),
                                textcoords="offset points", ha="center", fontsize=8,
                                color=S.SCEN_DARK[scen])
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.grid(axis="x", color=S.GRID, lw=0.6)
        ax.grid(axis="y", visible=False)
        ax.set_ylim(-0.6, len(S.CROPS) - 0.4)
    axes[0].set_yticks(list(ypos.values()))
    axes[0].set_yticklabels([S.CROP_LABEL[k] for k in ypos], fontsize=10, color=S.INK)
    for k, ax in enumerate(axes):
        if k:
            ax.tick_params(axis="y", length=0)
    axes[2].legend(loc="lower right", handletextpad=0.3, borderaxespad=0.2)
    S.headline(fig, f"Water stress rises for four of five crops, yet {S.CO2} lifts water productivity for cereals and rapeseed, not potato or maize",
               "Brandenburg mean, 2071–2100 vs. 1985–2014. Dot: median of 5 GCMs (SSP3-7.0 value labelled), bar: GCM range")
    S.footnote(fig, "Water stress = 1 − TRANRF averaged from sowing to harvest (0 = unstressed). "
               f"Water productivity = yield per m³ transpired; it includes the model's {S.CO2} effect on growth and on transpiration. "
               "All crops develop faster in the warmer climate (a).", y=0.006)
    S.save(fig, "fig4_water_phenology")
    summary.round(2).to_csv(S.FIGS / "fig4_stats.csv")


if __name__ == "__main__":
    main()
