"""Shared look, labels and helpers for the RIA 3 GA figures.

Colour roles (validated for CVD with the dataviz palette validator):
  SSP1-2.6 blue #2a78d6, SSP3-7.0 orange #eb6834 — categorical slots 1-2;
  historical / reference runs are a recessive neutral, always direct-labelled.
  Diverging maps and the scorecard: red (worse) <- neutral gray -> blue (better).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "reports" / "ria3_ga2026" / "data"
FIGS = ROOT / "reports" / "ria3_ga2026" / "figures"

CROPS = ["winter_wheat", "winter_rapeseed", "spring_barley", "potato", "maize"]
CROP_LABEL = {
    "winter_wheat": "Winter wheat", "winter_rapeseed": "Winter rapeseed",
    "spring_barley": "Spring barley", "potato": "Potato", "maize": "Grain maize",
}
GCMS = ["ACCESS-CM2", "CanESM5", "EC-Earth3", "GFDL-ESM4", "MIROC6"]
SCEN_LABEL = {"ssp126": "SSP1-2.6", "ssp370": "SSP3-7.0", "historical": "Historical"}
CO2 = "CO$_2$"
PERIOD_LABEL = {"ref": "1985–2014", "mid": "2031–2060", "far": "2071–2100"}

INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#ffffff"
NEUTRAL = "#f0efec"
SCEN_COLOR = {"ssp126": "#2a78d6", "ssp370": "#eb6834", "historical": "#898781"}
SCEN_DARK = {"ssp126": "#1c5cab", "ssp370": "#b8461a", "historical": "#52514e"}

# red (worse) -> neutral -> blue (better); equal steps per arm
DIVERGING = LinearSegmentedColormap.from_list(
    "worse_better",
    ["#7f1d1d", "#c2393a", "#e88b86", NEUTRAL, "#86b6ef", "#2a78d6", "#104281"],
)

# CO2 response of radiation-use efficiency, from every crop.xml (COTableCo2 /
# COTableFactor). SIMPLACE's AFGEN clamps outside the table (checked in the
# simplace_5.0-3897 bytecode), so the factor saturates above 720 ppm.
CO2_TABLE_X = [40.0, 360.0, 720.0]
CO2_TABLE_Y = {c: [0.0, 1.0, 1.35] for c in CROPS}
CO2_TABLE_Y["maize"] = [0.0, 1.0, 1.07]


def rue_co2_factor(crop: str, co2) -> np.ndarray:
    return np.interp(np.asarray(co2, dtype=float), CO2_TABLE_X, CO2_TABLE_Y[crop])


def setup() -> None:
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans"],
        "font.size": 9.5,
        "axes.titlesize": 10.5,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.labelsize": 9.5,
        "axes.labelcolor": INK2,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK2,
        "ytick.labelcolor": INK2,
        "xtick.major.size": 3,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "svg.fonttype": "none",
        "lines.solid_capstyle": "round",
        "mathtext.fontset": "custom",
        "mathtext.rm": "Arial",
        "mathtext.it": "Arial:italic",
        "mathtext.bf": "Arial:bold",
        "mathtext.default": "regular",
    })


def headline(fig, title: str, subtitle: str | None = None, y: float = 0.985) -> None:
    fig.text(0.012, y, title, ha="left", va="top", fontsize=14, fontweight="bold", color=INK)
    if subtitle:
        fig.text(0.012, y - 0.052, subtitle, ha="left", va="top", fontsize=10, color=INK2)


def footnote(fig, text: str, y: float = 0.012) -> None:
    fig.text(0.012, y, text, ha="left", va="bottom", fontsize=7.5, color=MUTED)


def save(fig, name: str) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / f"{name}.png", dpi=300)
    fig.savefig(FIGS / f"{name}.svg")
    plt.close(fig)
    print(f"wrote {FIGS / name}.png/.svg")


def period_of(year: int) -> str | None:
    if 1985 <= year <= 2014:
        return "ref"
    if 2031 <= year <= 2060:
        return "mid"
    if 2071 <= year <= 2100:
        return "far"
    return None
