"""Figure 2 — two futures diverge, and for C3 crops the gain is the CO2 term.

Brandenburg+Berlin mean yield per harvest year, as % change against each GCM's
own 1985-2014 historical mean; each GCM's historical run is joined to its SSP
run and smoothed with a 21-year centred mean before the ensemble statistics
(median line, min-max band across the 5 GCMs).

Dashed line: the change in the radiation-use-efficiency CO2 multiplier alone
(crop.xml COTable, clamped above 720 ppm), computed from the same CO2 the crop
experienced. It is the yield change a pure RUE response would give with
climate held fixed — a reference, not a counterfactual simulation; CO2 also
reduces transpiration in LINTUL5, which this line does not include.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import _style as S

WIN = 21


def smoothed(a: pd.DataFrame, crop: str, scen: str, col: str) -> pd.DataFrame:
    out = {}
    for g in S.GCMS:
        h = a[(a.crop == crop) & (a.gcm == g) & (a.scen == "historical")].set_index("year")
        f = a[(a.crop == crop) & (a.gcm == g) & (a.scen == scen)].set_index("year")
        s = pd.concat([h[col], f[col]]).sort_index()
        s = s[~s.index.duplicated()]
        s = s.reindex(range(s.index.min(), s.index.max() + 1))
        out[g] = s.rolling(WIN, center=True, min_periods=WIN - 4).mean()
    return pd.DataFrame(out)


def main() -> None:
    S.setup()
    a = pd.read_parquet(S.DATA / "annual_state.parquet")
    a = a[a.gcm.isin(S.GCMS)].copy()
    a["rue"] = [S.rue_co2_factor(c, v) for c, v in zip(a.crop, a.co2)]
    ref = (a[(a.scen == "historical") & a.year.between(1985, 2014)]
           .groupby(["crop", "gcm"])[["yield", "rue"]].mean())
    a["dy"] = 100 * (a["yield"] / [ref.loc[(c, g), "yield"] for c, g in zip(a.crop, a.gcm)] - 1)
    a["drue"] = 100 * (a["rue"] / [ref.loc[(c, g), "rue"] for c, g in zip(a.crop, a.gcm)] - 1)

    fig, axes = plt.subplots(1, 5, figsize=(13.33, 5.0), sharey=True)
    fig.subplots_adjust(left=0.055, right=0.985, top=0.8, bottom=0.22, wspace=0.12)
    rows = []
    for ax, crop in zip(axes, S.CROPS):
        ax.axhline(0, color=S.AXIS, lw=0.9, zorder=1)
        for scen in ["ssp126", "ssp370"]:
            y = smoothed(a, crop, scen, "dy")
            r = smoothed(a, crop, scen, "drue").median(axis=1)
            fut = y.index >= 2014
            col = S.SCEN_COLOR[scen]
            ax.fill_between(y.index[fut], y.min(axis=1)[fut], y.max(axis=1)[fut],
                            color=col, alpha=0.18, lw=0)
            ax.plot(y.index[fut], y.median(axis=1)[fut], color=col, lw=2.2,
                    label=f"{S.SCEN_LABEL[scen]} yield (median, GCM range)")
            ax.plot(r.index[fut], r[fut], color=S.SCEN_DARK[scen], lw=1.2, ls=(0, (3, 2)),
                    label=f"{S.SCEN_LABEL[scen]}: {S.CO2}–RUE multiplier alone")
            if scen == "ssp126":
                hist = y.index <= 2014
                ax.fill_between(y.index[hist], y.min(axis=1)[hist], y.max(axis=1)[hist],
                                color=S.MUTED, alpha=0.18, lw=0)
                ax.plot(y.index[hist], y.median(axis=1)[hist], color=S.MUTED, lw=2,
                        label="Historical runs")
            end = y.loc[2085]
            rows.append((crop, scen, end.median(), end.min(), end.max(), r.loc[2085]))
            last = y.median(axis=1).dropna()
            ax.annotate(("±0" if abs(end.median()) < 0.5 else f"{end.median():+.0f}".replace("-", "−")) + " %", (last.index[-1], last.iloc[-1]), xytext=(3, 0),
                        textcoords="offset points", va="center", fontsize=9,
                        fontweight="bold", color=S.SCEN_DARK[scen])
        ax.set_title(S.CROP_LABEL[crop] + ("  (C4)" if crop == "maize" else ""))
        ax.set_xlim(1960, 2113)
        ax.set_xticks([1980, 2020, 2060])
    axes[0].set_ylabel("Yield change vs. 1985–2014 (%)")
    axes[0].set_ylim(-52, 55)
    h, l = axes[0].get_legend_handles_labels()
    lut = dict(zip(l, h))
    keys = ["Historical runs"] + [k for scen in ("SSP1-2.6", "SSP3-7.0") for k in l if k.startswith(scen)]
    fig.legend([lut[k] for k in keys], keys, loc="lower center", ncol=5,
               bbox_to_anchor=(0.5, 0.05), fontsize=8.6, handlelength=2.4)
    S.headline(fig, f"Winter cereals and rapeseed gain about what {S.CO2} adds; potato and maize lose despite it",
               "Brandenburg mean yield, 21-year running mean, 5 bias-corrected CMIP6 GCMs per pathway; "
               "label = ensemble median for 2075–2095")
    S.footnote(fig, f"Each GCM is compared with its own historical run. Dashed: yield change implied by the model's RUE–{S.CO2} table alone "
               "(×1.35 at ≥ 720 ppm for C3 crops, ×1.07 for maize),\nat the CO$_2$ each crop experienced; it omits the "
               f"{S.CO2} effect on transpiration. Maize means are over harvested site-seasons (84 % in 1985–2014, ≈ 100 % in the future).", y=0.003)
    S.save(fig, "fig2_yield_trajectories")
    pd.DataFrame(rows, columns=["crop", "scen", "dyield_2085_median", "min", "max", "drue_2085"]).round(1).to_csv(
        S.FIGS / "fig2_stats.csv", index=False)


if __name__ == "__main__":
    main()
