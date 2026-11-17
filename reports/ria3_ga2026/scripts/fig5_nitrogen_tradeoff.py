"""Figure 5 — the productivity-environment trade-off: nitrate leaching.

Per GCM, 2071-2100 vs that GCM's 1985-2014 historical run, for the typical
site (median across the 15 066 sites of each site's period mean):

  a  yield change (%) against nitrate-leaching change (kg N/ha per simulation
     window); dot = ensemble median, whiskers = GCM range
  b  nitrogen-loss intensity, kg N leached per t yield (median across sites of
     site-level leaching / site-level yield), reference vs both SSPs

Fertiliser N is held at today's level in every scenario, so the changes are the
response of an unchanged management system to climate and CO2. Leaching is a
model output not validated against measurements (no lysimeter data used).
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import _style as S

LABEL_OFFSET = {  # (dx, dy, ha) in points from the SSP3-7.0 dot
    "winter_wheat": (8, -14, "left"), "winter_rapeseed": (-8, 8, "right"),
    "spring_barley": (0, 10, "center"), "potato": (-6, 10, "right"), "maize": (6, 10, "left"),
}


def site_stats(p: pd.DataFrame) -> pd.DataFrame:
    p = p.assign(intensity=p["nleach"] / p["yield"].where(p["yield"] > 0.1))
    g = p.groupby(["crop", "gcm", "scen", "period"])
    return g.agg(yield_=("yield", "median"), nleach=("nleach", "median"),
                 intensity=("intensity", "median")).reset_index()


def main() -> None:
    S.setup()
    p = pd.read_parquet(S.DATA / "period_site.parquet",
                        columns=["vLocationID", "yield", "nleach", "crop", "gcm", "scen", "period"])
    p = p[p.gcm.isin(S.GCMS)]
    s = site_stats(p)
    ref = s[(s.scen == "historical") & (s.period == "ref")].set_index(["crop", "gcm"])
    fut = s[(s.period == "far") & s.scen.isin(["ssp126", "ssp370"])].copy()
    b = ref.loc[list(zip(fut.crop, fut.gcm))]
    fut["dy"] = 100 * (fut["yield_"].values / b["yield_"].values - 1)
    fut["dn"] = fut["nleach"].values - b["nleach"].values
    fut["dn_pct"] = 100 * (fut["nleach"].values / b["nleach"].values - 1)

    fig = plt.figure(figsize=(13.33, 5.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1], left=0.06, right=0.985, top=0.79,
                          bottom=0.17, wspace=0.28)
    ax = fig.add_subplot(gs[0])
    ax.axhline(0, color=S.AXIS, lw=0.9)
    ax.axvline(0, color=S.AXIS, lw=0.9)
    ax.grid(axis="x", color=S.GRID, lw=0.6)
    rows = []
    for crop in S.CROPS:
        pts = {}
        for scen in ["ssp126", "ssp370"]:
            f = fut[(fut.crop == crop) & (fut.scen == scen)]
            mx, my = f.dy.median(), f.dn.median()
            pts[scen] = (mx, my)
            col = S.SCEN_COLOR[scen]
            ax.plot([f.dy.min(), f.dy.max()], [my, my], color=col, lw=1.6, alpha=0.4)
            ax.plot([mx, mx], [f.dn.min(), f.dn.max()], color=col, lw=1.6, alpha=0.4)
            ax.plot(mx, my, "o", ms=9, color=col, mec="white", mew=1.5, zorder=4,
                    label=S.SCEN_LABEL[scen] if crop == S.CROPS[0] else None)
            rows.append((crop, scen, mx, f.dy.min(), f.dy.max(), my, f.dn.min(), f.dn.max(),
                         f.dn_pct.median(), ref.loc[crop, "nleach"].median()))
        (x1, y1), (x2, y2) = pts["ssp126"], pts["ssp370"]
        ax.plot([0, x1, x2], [0, y1, y2], color=S.MUTED, lw=0.8, ls=":", zorder=2)
        dx, dy, ha = LABEL_OFFSET[crop]
        ax.annotate(S.CROP_LABEL[crop], (x2, y2), xytext=(dx, dy), textcoords="offset points",
                    ha=ha, fontsize=9.5, fontweight="bold", color=S.INK)
    ax.set_xlim(-50, 55)
    yl = ax.get_ylim()
    ax.set_ylim(min(-5, yl[0]), yl[1] * 1.08)
    ax.text(0.98, 0.97, "more yield,\nmore leaching", transform=ax.transAxes, ha="right", va="top",
            fontsize=9, color=S.MUTED, style="italic")
    ax.text(0.02, 0.97, "less yield,\nmore leaching", transform=ax.transAxes, ha="left", va="top",
            fontsize=9, color=S.MUTED, style="italic")
    ax.set_xlabel("Yield change (%)")
    ax.set_ylabel("Nitrate-leaching change (kg N/ha)")
    ax.set_title("a  Median leaching rises for every crop and pathway")
    ax.legend(loc="lower right")

    ax2 = fig.add_subplot(gs[1])
    yp = {c: i for i, c in enumerate(S.CROPS[::-1])}
    inten = s.copy()
    for crop in S.CROPS:
        y = yp[crop]
        r = ref.loc[crop, "intensity"]
        vals = {"historical": (r.median(), r.min(), r.max())}
        for scen in ["ssp126", "ssp370"]:
            f = fut[(fut.crop == crop) & (fut.scen == scen)].intensity
            vals[scen] = (f.median(), f.min(), f.max())
        for scen, dy in [("historical", 0.22), ("ssp126", 0), ("ssp370", -0.22)]:
            m, lo, hi = vals[scen]
            ax2.plot([lo, hi], [y + dy, y + dy], color=S.SCEN_COLOR[scen], lw=2, alpha=0.4, zorder=2)
            ax2.plot(m, y + dy, "o", ms=8, color=S.SCEN_COLOR[scen], mec="white", mew=1.3, zorder=3,
                     label=("1985–2014" if scen == "historical" else S.SCEN_LABEL[scen] + ", 2071–2100")
                     if crop == S.CROPS[0] else None)
        # paired: each GCM against its own historical run, then the median
        f370 = fut[(fut.crop == crop) & (fut.scen == "ssp370")].set_index("gcm").intensity
        ratio = (f370 / ref.loc[crop, "intensity"]).median()
        ax2.annotate(f"×{ratio:.1f}", (vals["ssp370"][2], y - 0.22), xytext=(6, 0),
                     textcoords="offset points", va="center", fontsize=9, color=S.SCEN_DARK["ssp370"],
                     fontweight="bold")
    ax2.set_xscale("log")
    ax2.set_xlim(0.1, 80)
    ax2.set_xticks([0.1, 0.3, 1, 3, 10, 30])
    ax2.set_xticklabels(["0.1", "0.3", "1", "3", "10", "30"])
    ax2.set_yticks(list(yp.values()))
    ax2.set_yticklabels([S.CROP_LABEL[k] for k in yp], fontsize=10, color=S.INK)
    ax2.grid(axis="x", color=S.GRID, lw=0.6)
    ax2.grid(axis="y", visible=False)
    ax2.set_xlabel("kg N leached per t yield (log scale)")
    ax2.set_title("b  Nitrogen-loss intensity  (×: SSP3-7.0 vs. today, GCM-paired median)")
    ax2.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0), fontsize=8.5, ncol=1)
    ax2.set_ylim(-0.5, len(S.CROPS) - 0.1)
    S.headline(fig, "Winter crops carry the nitrate burden (+25–37 kg N/ha); spring crops lose little, but 2–3× as much per tonne",
               "Typical 1 km site (median across sites), 2071–2100 vs. 1985–2014, fertiliser held at today's rates. "
               "Dot: median of 5 GCMs, whiskers: GCM range")
    S.footnote(fig, "Leaching = nitrate below the soil profile, summed over each simulation window (1 Jan of the sowing year to harvest); "
               "winter-crop windows include the pre-sowing fallow, so levels compare within, not across, crop types.\n"
               "Model-derived and not yet validated against leaching measurements. Medians, because a few organic-rich soils leach extreme amounts.",
               y=0.006)
    S.save(fig, "fig5_nitrogen_tradeoff")
    pd.DataFrame(rows, columns=["crop", "scen", "dyield_pct", "dy_min", "dy_max", "dnleach_kgN",
                                "dn_min", "dn_max", "dnleach_pct", "nleach_ref_kgN"]).round(2).to_csv(
        S.FIGS / "fig5_stats.csv", index=False)


if __name__ == "__main__":
    main()
