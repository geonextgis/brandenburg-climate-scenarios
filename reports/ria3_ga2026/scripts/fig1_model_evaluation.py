"""Figure 1 — the model reproduces observed regional yields.

DWD-driven baseline simulation (calibrated crop.xml) aggregated to NUTS-3
districts, against observed district yields. Per crop: the Brandenburg+Berlin
mean of the districts observed in that year (obs vs sim on the same districts),
with the observed between-district range.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import _style as S

CAL_START = 1995  # optimization/config.yaml: yield view year_start


def main() -> None:
    S.setup()
    d = pd.read_parquet(S.DATA / "district_obs_sim.parquet")
    fig, axes = plt.subplots(1, 5, figsize=(13.33, 4.6), sharex=True)
    fig.subplots_adjust(left=0.04, right=0.985, top=0.74, bottom=0.22, wspace=0.3)
    stats = []
    for ax, crop in zip(axes, S.CROPS):
        c = d[d.crop == crop]
        y = c.groupby("year").agg(obs=("obs", "mean"), sim=("sim", "mean"),
                                  lo=("obs", lambda s: s.quantile(0.1)),
                                  hi=("obs", lambda s: s.quantile(0.9)), n=("obs", "size"))
        y = y[y.n >= 3]
        cal = y[y.index >= CAL_START]
        ax.axvspan(1978, CAL_START - 0.5, color=S.NEUTRAL, lw=0, zorder=0)
        ax.fill_between(y.index, y.lo, y.hi, color=S.GRID, lw=0, label="Observed, district 10–90 %")
        ax.plot(y.index, y.obs, color=S.INK, lw=1.6, marker="o", ms=3.2, label="Observed (district mean)")
        ax.plot(y.index, y.sim, color=S.SCEN_COLOR["ssp126"], lw=2, label="SIMPLACE, DWD weather")
        rmse = float(np.sqrt(((cal.sim - cal.obs) ** 2).mean()))
        r = float(np.corrcoef(cal.sim, cal.obs)[0, 1])
        bias = float((cal.sim - cal.obs).mean())
        rel = 100 * rmse / cal.obs.mean()
        stats.append((crop, int(cal.n.sum()), c.NUTS_ID.nunique(), cal.index.min(), cal.index.max(),
                      r, rmse, rel, bias, cal.obs.std(), cal.sim.std()))
        unit = "t DM/ha" if crop == "potato" else "t/ha"
        ax.set_title(S.CROP_LABEL[crop], pad=16)
        ax.text(0, 1.015, f"{unit} · bias {bias:+.2f} · r {r:.2f} · RMSE {rmse:.2f}".replace("-", "−"),
                transform=ax.transAxes, fontsize=7.9, color=S.INK2, va="bottom")
        ax.set_xlim(1978, 2024)
        ax.set_xticks([1980, 2000, 2020])
        lo = np.floor(min(y.lo.min(), y.sim.min()))
        ax.set_ylim(max(0, lo - 0.5), np.ceil(max(y.hi.max(), y.sim.max())) + 0.5)
    axes[0].text(1979, axes[0].get_ylim()[1], "before\ncalibration\nwindow", fontsize=7.5,
                 color=S.MUTED, va="top", ha="left")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h[::-1], l[::-1], loc="lower center", ncol=3, bbox_to_anchor=(0.5, 0.06))
    S.headline(fig, "The calibrated model hits Brandenburg's regional yield level without bias",
               "Mean yield of the observed NUTS-3 districts vs. the 1 km simulation (DWD weather, observed " + S.CO2 + "). "
               "Scores: annual means 1995–2023, the calibration window")
    S.footnote(fig, "Yield statistics are district-level; simulated sites (15 066, 1 km) are averaged to the same districts and years. "
               "Potato observations converted to dry matter (× 0.21).\n"
               "Pre-1995 observations carry a technology/management trend the model does not represent. Years with < 3 observed districts omitted.", y=0.003)
    S.save(fig, "fig1_model_evaluation")
    pd.DataFrame(stats, columns=["crop", "district_years", "districts", "first", "last",
                                 "r_yearly", "rmse_yearly_t_ha", "rmse_pct", "bias_t_ha",
                                 "sd_obs", "sd_sim"]).round(3).to_csv(
        S.FIGS / "fig1_stats.csv", index=False)


if __name__ == "__main__":
    main()
