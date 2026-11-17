"""Figure 6 — synthesis: no crop improves on every axis.

Crops x indicators, 2071-2100 vs 1985-2014, ensemble median of the 5 GCMs
(each against its own historical run), for SSP1-2.6 and SSP3-7.0.

Colour encodes desirability, not sign: blue = better for the agri-environment
system, red = worse, scaled per indicator to its largest absolute change.
Cells where fewer than 4 of 5 GCMs agree on the sign are faded and marked "~".

Indicators (definitions as in 02_aggregate.py):
  yield              mean yield, %                         higher = better
  low-yield years    share of seasons < 75 % of the site's 1985-2014 median, pp
                                                           lower = better
  water stress       1 - in-season TRANRF, pp              lower = better
  water productivity yield per m3 transpired, %            higher = better
  nitrate leaching   typical site, kg N/ha                  lower = better
  N-loss intensity   typical site, kg N per t yield, %      lower = better
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch

import _style as S

IND = [  # key, label, unit, kind, sign (+1 higher=better)
    ("yield", "Yield", "%", "pct", +1),
    ("lowyield", "Low-yield\nyears", "pp", "pp", -1),
    ("stress", "Water\nstress", "pp", "pp", -1),
    ("wp", "Water\nproductivity", "%", "pct", +1),
    ("nleach", "Nitrate\nleaching", "kg N/ha", "diff", -1),
    ("intensity", "N loss per\ntonne", "%", "pct", -1),
]


def per_gcm(p: pd.DataFrame) -> pd.DataFrame:
    p = p.assign(intensity=p["nleach"] / p["yield"].where(p["yield"] > 0.1))
    g = p.groupby(["crop", "gcm", "scen", "period"])
    return g.agg(yield_=("yield", "mean"), lowyield=("lowyield", "mean"), stress=("stress", "mean"),
                 wp=("wp", "mean"), nleach=("nleach", "median"),
                 intensity=("intensity", "median")).rename(columns={"yield_": "yield"}).reset_index()


def main() -> None:
    S.setup()
    p = pd.read_parquet(S.DATA / "period_site.parquet")
    p = p[p.gcm.isin(S.GCMS)]
    a = per_gcm(p)
    ref = a[(a.scen == "historical") & (a.period == "ref")].set_index(["crop", "gcm"])
    fut = a[(a.period == "far") & a.scen.isin(["ssp126", "ssp370"])].reset_index(drop=True)
    b = ref.loc[list(zip(fut.crop, fut.gcm))].reset_index(drop=True)
    ch = fut[["crop", "gcm", "scen"]].copy()
    for key, _, _, kind, _ in IND:
        if kind == "pct":
            ch[key] = 100 * (fut[key] / b[key] - 1)
        elif kind == "pp":
            ch[key] = 100 * (fut[key] - b[key])
        else:
            ch[key] = fut[key] - b[key]
    med = ch.groupby(["crop", "scen"])[[k for k, *_ in IND]].median()
    agree = ch.join(np.sign(med), on=["crop", "scen"], rsuffix="_m")
    robust = pd.DataFrame({k: (np.sign(agree[k]) == agree[k + "_m"]) for k, *_ in IND})
    robust[["crop", "scen"]] = agree[["crop", "scen"]]
    robust = robust.groupby(["crop", "scen"]).sum() >= 4

    scens = ["ssp126", "ssp370"]
    ncol = len(IND) * 2
    fig = plt.figure(figsize=(13.33, 5.9))
    ax = fig.add_axes([0.13, 0.17, 0.86, 0.67])
    ax.set_xlim(0, ncol)
    ax.set_ylim(len(S.CROPS), -1.1)
    ax.set_axis_off()
    for k, (key, label, unit, kind, sign) in enumerate(IND):
        scale = np.nanmax(np.abs(med[key].values))
        x0 = 2 * k
        ax.text(x0 + 1, -0.62, label, ha="center", va="bottom", fontsize=10, fontweight="bold", color=S.INK)
        ax.text(x0 + 1, -0.6, f"({unit})", ha="center", va="top", fontsize=8, color=S.MUTED)
        for j, scen in enumerate(scens):
            ax.text(x0 + j + 0.5, -0.12, S.SCEN_LABEL[scen], ha="center", va="bottom", fontsize=7.8,
                    color=S.SCEN_DARK[scen], fontweight="bold")
            for i, crop in enumerate(S.CROPS):
                v = med.loc[(crop, scen), key]
                ok = bool(robust.loc[(crop, scen), key])
                good = sign * v / scale  # -1 worst .. +1 best
                col = S.DIVERGING(0.5 + 0.5 * np.clip(good, -1, 1))
                ax.add_patch(FancyBboxPatch((x0 + j + 0.04, i + 0.06), 0.92, 0.88,
                                            boxstyle="round,pad=0,rounding_size=0.06",
                                            fc=col, ec="none", alpha=1.0 if ok else 0.35))
                txt = ("±0" if abs(v) < 0.5 else f"{v:+.0f}").replace("-", "−")
                dark = abs(good) > 0.55 and ok
                ax.text(x0 + j + 0.5, i + 0.5, txt + ("" if ok else " ~"), ha="center", va="center",
                        fontsize=10, fontweight="bold" if ok else "normal",
                        color="white" if dark else (S.INK if ok else S.INK2))
        if k:
            ax.plot([x0, x0], [-0.05, len(S.CROPS)], color="white", lw=4)
    for i, crop in enumerate(S.CROPS):
        ax.text(-0.15, i + 0.5, S.CROP_LABEL[crop], ha="right", va="center", fontsize=10.5, color=S.INK)

    # legend: desirability scale
    lax = fig.add_axes([0.13, 0.085, 0.22, 0.03])
    grad = np.linspace(0, 1, 256)[None, :]
    lax.imshow(grad, aspect="auto", cmap=S.DIVERGING)
    lax.set_yticks([])
    lax.set_xticks([0, 255])
    lax.set_xticklabels(["worse", "better"])
    lax.tick_params(length=0, labelsize=8.5)
    for sp in lax.spines.values():
        sp.set_visible(False)
    fig.text(0.37, 0.1, "Colour = direction for the agri-environment system, scaled per indicator.   "
             "~ faded: < 4 of 5 GCMs agree on the sign.", fontsize=8.5, color=S.INK2, va="center")
    S.headline(fig, "No crop gets better on every axis: CO$_2$-driven gains in cereal yield come with more nitrate leaching",
               "Ensemble-median change 2071–2100 vs. 1985–2014, Brandenburg. Numbers are the change in the unit shown")
    S.footnote(fig, "Low-yield years: seasons below 75 % of the site's own 1985–2014 median. Water stress: 1 − in-season TRANRF. "
               "Leaching and N loss per tonne: typical site (median), model-derived, not validated against measurements.\n"
               "Management (sowing rule, N fertiliser) held at today's level. "
               "Biodiversity and planetary-boundary effects are not resolved by these simulations and are not implied.", y=0.006)
    S.save(fig, "fig6_sustainability_scorecard")
    out = med.round(2)
    out.columns = [f"{c}_median" for c in out.columns]
    out.join(robust.add_suffix("_robust")).to_csv(S.FIGS / "fig6_scorecard.csv")


if __name__ == "__main__":
    main()
